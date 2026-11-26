"""Импорт ответа владельца только в ту редакцию, к вопросам которой он дан.

Документы A и B: одно имя ``tz.md``, разные SHA-256, одинаковый номер вопроса ``Q-01``.
В A он про месяц учёта, в B — про повторный push после смены порога. Ответ, скачанный
из A, загружается в просмотр B.

Две реализации движка:
* dev-движок веба — всегда (нумерация вопросов последовательная, как у настоящего);
* настоящий ``bcc_review.run_review`` с локальным mock-провайдером — если движок ветки
  задаёт вопросы (нужен bcc/integration с модулем правил, 6be9e97+). Сценарий
  провайдера выбирается по версии документа (mock_A.json / mock_B.json).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from bcc_review.web.answers import P08_PARSER_DEFAULT, P08_PARSER_ENV, _load, read_import
from bcc_review.web.engine import EngineSpec, resolve_engine
from bcc_review.web.service import Settings

from .conftest import CASE, FIXTURES, CountingEngine

VERSIONS = FIXTURES / "versions"
DOC_A = (VERSIONS / "A" / "tz.md").read_bytes()
DOC_B = (VERSIONS / "B" / "tz.md").read_bytes()
EDIT_B = ("На карту приходится максимум один такой push за календарный месяц.",
          "На карту приходится не более одного push за календарный месяц, если порог не менялся.")


class VersionedMockEngine:
    """Настоящий run_review; mock-сценарий A или B по тексту документа. Считает вызовы."""

    def __init__(self, func):
        self.func = func
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, input_path, report_md, *, options=None):
        text = Path(input_path).read_text(encoding="utf-8")
        script = VERSIONS / ("mock_A.json" if "Февральский счётчик" in text else "mock_B.json")
        with self._lock:
            self.calls.append(Path(input_path).parent.parent.name)
        return self.func(input_path, report_md, options={**(options or {}), "mock_script": str(script)})


def _upload_ab(client):
    a = client.wait(client.upload("tz.md", DOC_A)["run_id"], timeout=120)
    b = client.wait(client.upload("tz.md", DOC_B)["run_id"], timeout=120)
    assert a["status"] in ("complete", "partial") and b["status"] in ("complete", "partial")
    assert a["input"]["original_name"] == b["input"]["original_name"] == "tz.md"
    assert a["input"]["sha256"] != b["input"]["sha256"]
    return a, b


@pytest.fixture(params=["dev", "shared-mock"])
def ab(request, make_server, tmp_path):
    if request.param == "dev":
        engine = CountingEngine()
        client = make_server(engine)
    else:
        spec = resolve_engine("auto")
        if not spec.available:
            pytest.skip(f"общий движок не найден: {spec.error}")
        engine = VersionedMockEngine(spec.func)
        client = make_server(EngineSpec("shared", "bcc_review:run_review (mock по версии)", engine),
                             settings=Settings(provider="mock", cache_dir=tmp_path / "cache"))
    a, b = _upload_ab(client)
    if not _questions(client, a["run_id"]) or not _questions(client, b["run_id"]):
        pytest.skip("движок этой ветки не задал вопросов к A/B (нужен bcc/integration с модулем правил)")
    return client, engine, a, b


def _questions(client, run_id):
    report = json.loads(client.app.store.report_json(run_id).read_text(encoding="utf-8"))
    return [(q["id"], q["prompt"]) for q in report["questions"]]


def _fill(questions_md: str, qid: str, answer: str, edit: tuple[str, str] | None = None) -> str:
    """Аналитик вписывает ответ после «Ответ:» в разделе вопроса (и при желании правку)."""
    section = re.search(rf"## {re.escape(qid)}\n.*?Ответ:[^\n]*\n?", questions_md, re.S).group(0)
    tail = f"Ответ: {answer}\n" + (f"Правка: «{edit[0]}» → «{edit[1]}»\n" if edit else "")
    return questions_md.replace(section, re.sub(r"Ответ:[^\n]*\n?$", tail, section))


def test_answer_from_other_version_starts_nothing(ab):
    client, engine, a, b = ab
    (qa, prompt_a), (qb, prompt_b) = _questions(client, a["run_id"])[0], _questions(client, b["run_id"])[0]
    assert qa == qb and prompt_a != prompt_b  # один номер — разный смысл

    answers_a = _fill(client.get(f"/runs/{a['run_id']}/questions.md")[2].decode(), qa, "По дате совершения покупки")
    calls_before = len(engine.calls)
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers.md", answers_a.encode())})

    assert code == 409, body
    err = json.loads(body)
    assert err["reason"] == "stale_answers"
    assert err["declared_sha256"] == a["input"]["sha256"] and err["target_sha256"] == b["input"]["sha256"]
    assert [r["run_id"] for r in err["matching_runs"]] == [a["run_id"]]
    assert err["question_clash"] == [{"qid": qa, "in_file": prompt_a, "here": prompt_b}]
    assert client.app.store.children(b["run_id"]) == []
    assert len(engine.calls) == calls_before  # на этой попытке движок не вызывался
    # Импорт сохранён байт в байт и помечен отклонённым.
    rec = client.app.store.load_import(b["run_id"], err["import_id"])
    assert rec["status"] == "rejected" and rec["reason"] == "stale_answers" and rec["declared_sha256"] == a["input"]["sha256"]
    assert client.app.store.import_original(b["run_id"], err["import_id"]).read_bytes() == answers_a.encode()

    # Обычный браузерный ответ: страница с причиной, обоими вопросами и ссылкой на вопросы A.
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers.md", answers_a.encode())}, json_accept=False)
    page = body.decode()
    assert code == 409 and "Ответы не применены" in page
    assert prompt_a in page and prompt_b in page and f'href="/runs/{a["run_id"]}#action"' in page
    assert f'href="/runs/{b["run_id"]}/questions.md"' in page and 'id="no-runs">0' in page
    assert client.app.store.children(b["run_id"]) == [] and len(engine.calls) == calls_before


def test_own_answer_creates_one_revision_and_repeat_returns_it(ab):
    client, engine, a, b = ab
    qb = _questions(client, b["run_id"])[0][0]
    answers_b = _fill(client.get(f"/runs/{b['run_id']}/questions.md")[2].decode(), qb,
                      "После смены порога разрешён ещё один push", EDIT_B).encode()
    calls_before = len(engine.calls)
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers.md", answers_b)})
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"], timeout=120)
    assert child["status"] in ("complete", "partial"), child["error"]
    assert len(engine.calls) == calls_before + 1
    # Повтор того же файла — та же редакция, движок не вызывается.
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers.md", answers_b)})
    assert code == 200 and json.loads(body) == {"run_id": child["run_id"], "duplicate": True}
    assert [c["run_id"] for c in client.app.store.children(b["run_id"])] == [child["run_id"]]
    assert len(engine.calls) == calls_before + 1

    store = client.app.store
    report = json.loads(store.report_json(child["run_id"]).read_text(encoding="utf-8"))
    assert child["input"]["sha256"] == b["input"]["sha256"]          # решение применено к версии B
    assert report["document"]["id"] not in (a["input"]["sha256"], b["input"]["sha256"])  # редакция со своим SHA
    assert [d["question_id"] for d in report["decisions"]] == [qb]
    # Оригинал импорта и собранный answers.md различимы.
    assert (store.input_dir(child["run_id"]) / "answers_uploaded.md").read_bytes() == answers_b
    meta = child["answers"]["import"]
    assert meta["declared_sha256"] == b["input"]["sha256"] and meta["format"] == "web"
    imports = store.list_imports(b["run_id"])
    assert [(i["status"], i.get("child_run_id")) for i in imports] == [("accepted", child["run_id"]), ("duplicate", child["run_id"])]


# --------------------------------------------------------------------------- форматы (dev-движок)
@pytest.fixture
def dev_ab(make_server):
    engine = CountingEngine()
    client = make_server(engine)
    a, b = _upload_ab(client)
    return client, engine, a, b


def html13_export(sha: str, qid: str, prompt: str, answer: str) -> str:
    """Файл в формате экспорта автономного HTML №13 (answers_markdown, 540c310)."""
    body = "\n".join(("\\" + ln if ln.startswith(("#", "\\")) else ln) for ln in answer.split("\n"))
    return (
        "---\nformat: bcc-review-answers/1\n"
        f"source_sha256: {sha}\ndocument_title: Уведомление о расходах по карте\nreport_run_id: r\n"
        "report_agent_version: 0.1.0\nexported_at: 2026-11-26T12:00:00.000Z\n---\n\n"
        "# Ответы на уточняющие вопросы\n\n> Черновик ответов аналитика к отчёту ревью. Исходный документ этим файлом не изменён.\n\n"
        f"## {qid}\n\n> {prompt}\n\nВарианты: А | Б\n\n### Ответ\n\n{body}\n"
    )


def test_html13_export_multiline_accepted_for_own_version_only(dev_ab):
    client, engine, a, b = dev_ab
    qb, prompt_b = _questions(client, b["run_id"])[0]
    answer = "Приоритет Ф-4: после смены порога разрешён ещё один push.\n# не заголовок, а строка ответа\nТретья строка."
    foreign = html13_export(a["input"]["sha256"], qb, "вопрос из A", answer)
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers-a.md", foreign.encode())})
    assert code == 409 and json.loads(body)["reason"] == "stale_answers" and json.loads(body)["format"] == "html13"

    calls = len(engine.calls)
    own = html13_export(b["input"]["sha256"], qb, prompt_b, answer)
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("answers-b.md", own.encode())})
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"])
    assert len(engine.calls) == calls + 1
    imp = child["answers"]["import"]
    assert imp["format"] == "html13" and "№13" in imp["parser"]
    composed = (client.app.store.input_dir(child["run_id"]) / "answers.md").read_text(encoding="utf-8")
    assert f"source_sha256: {b['input']['sha256']}" in composed
    parsed = read_import(composed.encode())
    assert parsed.answers[0].text == answer  # многострочный ответ и «#» в начале строки сохранены
    assert parsed.answers[0].provenance.startswith("черновик аналитика из HTML-отчёта №13 (answers-b.md")


def test_file_without_sha_is_not_applied_and_manual_path_stays(dev_ab):
    client, engine, a, b = dev_ab
    qb, prompt_b = _questions(client, b["run_id"])[0]
    legacy = f"## {qb}\nОтвет: После смены порога разрешён ещё один push\n".encode()
    calls = len(engine.calls)
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("old.md", legacy)})
    err = json.loads(body)
    assert code == 409 and err["reason"] == "no_sha" and err["declared_sha256"] is None
    assert client.app.store.children(b["run_id"]) == [] and len(engine.calls) == calls

    page = client.get(err["manual_url"].split("#")[0])[2].decode()
    assert 'id="manual-import"' in page and prompt_b in page and "Перенести в ответ на Q-01" in page
    assert "перенесено аналитиком вручную из файла без версии old.md" in page
    # Ручной перенос — обычная форма: ответ к вопросам этой версии с подписью происхождения.
    prov = f"перенесено аналитиком вручную из файла без версии old.md ({err['import_id']})"
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {
        f"a_{qb}": "После смены порога разрешён ещё один push", f"p_{qb}": prov,
        "questions_sha256": b["input"]["sha256"],
    })
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"])
    assert child["answers"]["provenance"] == {prov: 1} and child["answers"]["import"] is None


def test_conflicting_shas_and_form_answers_for_other_version(dev_ab):
    client, engine, a, b = dev_ab
    qb = _questions(client, b["run_id"])[0][0]
    both = f"source_sha256: {a['input']['sha256']}\nsource_sha256: {b['input']['sha256']}\n\n## {qb}\nОтвет: да\n"
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("x.md", both.encode())})
    assert code == 409 and json.loads(body)["reason"] == "sha_conflict"
    # Ответы в форме даны к вопросам B, а загружается новая редакция документа — не смешивать.
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions",
                                     {f"a_{qb}": "да", "questions_sha256": b["input"]["sha256"]},
                                     {"document": ("tz.md", DOC_B + b"\n")})
    assert code == 409 and json.loads(body)["reason"] == "form_other_version"
    assert client.app.store.children(b["run_id"]) == [] and len(engine.calls) == 2


def test_p08_card_format_accepted(dev_ab):
    client, engine, a, b = dev_ab
    qb, prompt_b = _questions(client, b["run_id"])[0]
    card = (f"<!-- bcc-review:answers v1 -->\n# Вопросы владельцу продукта\n\nsource_sha256: {b['input']['sha256']}\n\n"
            f"## {qb}. {prompt_b}\n\n| Поле | Значение |\n| :--- | :--- |\n\n**Варианты:**\n\n- **A. Да**\n\nОтвет: A\n")
    code, _, body = client.post_form(f"/runs/{b['run_id']}/revisions", {}, {"answers_file": ("questions-p08.md", card.encode())})
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"])
    assert child["answers"]["import"]["format"] == "p08"


def test_next_round_checks_engine_revision_and_keeps_earlier_edit(make_server):
    """Ответы не переносятся по номеру: следующий круг проверяет файл редакции, в нём уже есть прежняя правка."""
    client = make_server(CountingEngine())
    r1 = client.wait(client.upload("case_ab.md", CASE.read_bytes())["run_id"])
    e1 = ("На карту приходится максимум один такой push за календарный месяц.", "Лимит push сбрасывается при смене порога.")
    code, _, body = client.post_form(f"/runs/{r1['run_id']}/revisions", {"a_Q-01": "Приоритет Ф-4", "eo_Q-01": e1[0], "en_Q-01": e1[1]})
    r2 = client.wait(json.loads(body)["run_id"])
    rep2 = json.loads(client.app.store.report_json(r2["run_id"]).read_text(encoding="utf-8"))
    assert rep2["questions"][0]["id"] == "Q-01" and "31 января" in rep2["questions"][0]["prompt"]  # Q-01 теперь другой вопрос
    e2 = ("Февральский счётчик вырос на 4 000 ₸", "Январский счётчик вырос на 4 000 ₸")
    code, _, body = client.post_form(f"/runs/{r2['run_id']}/revisions", {"a_Q-01": "По дате совершения", "eo_Q-01": e2[0], "en_Q-01": e2[1]})
    assert code == 201, body
    r3 = client.wait(json.loads(body)["run_id"])
    assert r3["input"]["sha256"] == rep2["document"]["id"]  # вход третьей редакции — редакция B второго круга
    assert r3["input"]["derived_from"]["run_id"] == r2["run_id"]
    rep3 = json.loads(client.app.store.report_json(r3["run_id"]).read_text(encoding="utf-8"))
    text = "\n".join(bl["text"] for bl in rep3["document"]["blocks"])
    assert e1[1] in text and e2[1] in text and e1[0] not in text  # обе правки на месте


# --------------------------------------------------------------------------- опубликованный №08
def _p08():
    import os

    target = os.environ.get(P08_PARSER_ENV) or P08_PARSER_DEFAULT
    func = _load(target)
    if func is None:
        pytest.skip(f"парсер №08 не установлен ({target}); в тестовой копии: {P08_PARSER_ENV}=p08_decisions.answers:parse_answers")
    return func


def test_published_p08_parser_agrees_where_compatible(tmp_path):
    parse = _p08()
    sha = "b" * 64
    web = f"<!-- bcc-review answers v1; run_id=r -->\nsource_sha256: {sha}\n\n## Q-01\nВопрос: Повторный push?\nИсточник ответа: аналитик (веб-форма)\nОтвет: Да, разрешён\n"
    aset = parse(web)
    imp = read_import(web.encode())
    assert imp.parser.startswith("№08")
    assert aset.source_sha256 == imp.declared_sha256 == sha
    assert [(d.question_id, d.answer) for d in aset] == [(x.qid, x.text) for x in imp.answers] == [("Q-01", "Да, разрешён")]
    # Экспорт №13 (### Ответ) №08 не читает: [no_answer_field] — веб берёт разбор №13.
    html = html13_export(sha, "Q-01", "Повторный push?", "Да\nвторая строка")
    assert len(list(parse(html))) == 0 and any("no_answer_field" in w for w in parse(html).warnings)
    imp = read_import(html.encode())
    assert imp.format == "html13" and [(x.qid, x.text) for x in imp.answers] == [("Q-01", "Да\nвторая строка")]
