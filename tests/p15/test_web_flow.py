"""Путь аналитика через HTTP: загрузка → вердикт → ответ → новая редакция → сравнение → скачивание."""

from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from bcc_review.web.answers import parse_answers
from bcc_review.web.store import RUN_ID_RE

from .conftest import _tail  # noqa: F401
from .conftest import CountingEngine


def _diff_keys(store, child_id, kind="resolved"):
    """match_key замечаний dev-движка из diff (old_ids — в родительском отчёте, new_ids — в текущем)."""
    child = json.load(open(store.report_json(child_id), encoding="utf-8"))
    parent_id = store.load(child_id)["parent_run_id"]
    parent = json.load(open(store.report_json(parent_id), encoding="utf-8"))
    by_id = {f["id"]: f["match_key"] for f in parent["findings"]} if kind == "resolved" else {f["id"]: f["match_key"] for f in child["findings"]}
    ids_field = "old_ids" if kind == "resolved" else "new_ids"
    return [by_id[i] for d in child["diff"][kind] for i in d[ids_field]]


def _complete(client, case_bytes, name="case_ab.md"):
    created = client.upload(name, case_bytes)
    return client.wait(created["run_id"])


def test_upload_runs_engine_and_lists_real_artifacts(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    status, headers, body = client.get("/")
    assert status == 200 and "Загрузить ТЗ" in body.decode()

    st = _complete(client, case_bytes)
    assert st["status"] == "complete"
    assert RUN_ID_RE.match(st["run_id"])
    assert len(engine.calls) == 1
    call = engine.calls[0]
    # Движок получил путь к входу и report.md внутри каталога запуска, отдельный tmp_dir и run_id.
    assert _tail(call["input"], f"{st['run_id']}/input/case_ab.md")
    assert _tail(call["report"], f"{st['run_id']}/artifacts/report.md")
    assert _tail(call["options"]["tmp_dir"], f"{st['run_id']}/tmp")
    assert call["options"]["exports"] == ["html"]

    names = {a["name"] for a in st["artifacts"]}
    assert {"report.md", "report.json", "report.html"} <= names
    store = client.app.store
    assert not store.tmp_dir(st["run_id"]).exists(), "временные данные удалены после завершения"
    for a in st["artifacts"]:
        code, hdr, data = client.get(f"/runs/{st['run_id']}/files/{a['name']}")
        assert code == 200
        assert data == (store.artifacts_dir(st["run_id"]) / a["name"]).read_bytes()
        assert hdr["Content-Disposition"].startswith("attachment")

    # Стадии, которые сообщил движок, видны на странице.
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "нельзя начинать" in page
    assert "чтение документа" in page and "сверка опор" in page
    assert "F-001" in page and "<mark>" in page


def test_same_filename_gets_different_run_ids(make_server, case_bytes):
    client = make_server()
    a = client.upload("case_ab.md", case_bytes)
    b = client.upload("case_ab.md", case_bytes)
    assert a["run_id"] != b["run_id"]
    assert not a["duplicate"] and not b["duplicate"]
    client.wait(a["run_id"]), client.wait(b["run_id"])


def test_resubmitting_same_upload_form_is_not_a_second_run(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    key = uuid.uuid4().hex
    first = client.upload("case_ab.md", case_bytes, key=key)
    second = client.upload("case_ab.md", case_bytes, key=key)
    assert second == {"run_id": first["run_id"], "duplicate": True}
    client.wait(first["run_id"])
    assert len(engine.calls) == 1
    # HTML-форма: редирект на тот же запуск с пометкой о повторе.
    code, hdr, _ = client.post_form("/api/runs", {"upload_key": key}, {"file": ("case_ab.md", case_bytes)}, json_accept=False)
    assert code == 303 and hdr["Location"] == f"/runs/{first['run_id']}?dup=1"
    assert "уже было принято" in client.get(hdr["Location"])[2].decode()


def _answer_fields(qid="Q-01", text="Приоритет Ф-4: смена порога открывает право на новый push."):
    return {f"a_{qid}": text, f"p_{qid}": "аналитик (веб-форма)", f"qt_{qid}": "вопрос"}


def test_answer_confirm_creates_child_revision_with_diff(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    parent = _complete(client, case_bytes)
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", _answer_fields())
    assert code == 201, body
    child_id = json.loads(body)["run_id"]
    child = client.wait(child_id)
    assert child["status"] == "complete"
    assert child["parent_run_id"] == parent["run_id"] and child["revision"] == 2
    assert child["lineage_id"] == parent["lineage_id"]

    call = engine.calls[-1]
    assert _tail(call["options"]["compare_path"], f"{parent['run_id']}/artifacts/report.json")
    answers = parse_answers(open(call["options"]["answers_path"], encoding="utf-8").read())
    assert answers.by_id()["Q-01"].provenance == "аналитик (веб-форма)"
    assert child["answers"]["provenance"] == {"аналитик (веб-форма)": 1}

    page = client.get(f"/runs/{child_id}")[2].decode()
    assert "Сравнение с редакцией 1" in page
    assert "Устранено: <b>1</b>" in page
    assert "Что ещё требует внимания" in page
    cmp_page = client.get(f"/runs/{child_id}/compare")[2].decode()
    assert "Устранены (1)" in cmp_page and "Ф-3 и Ф-4" in cmp_page
    # Оба отчёта открываются.
    for rid in (parent["run_id"], child_id):
        code, hdr, data = client.get(f"/runs/{rid}/files/report.md?inline=1")
        assert code == 200 and hdr["Content-Disposition"].startswith("inline") and data
    # answers.md, с которым запущена редакция, доступен для скачивания.
    code, _, data = client.get(f"/runs/{child_id}/input/answers.md")
    assert code == 200 and "Q-01" in data.decode()


def test_double_confirm_does_not_start_second_paid_run(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    parent = _complete(client, case_bytes)
    calls_before = len(engine.calls)
    barrier = threading.Barrier(12)

    def click(_):
        barrier.wait()
        return client.post_form(f"/runs/{parent['run_id']}/revisions", _answer_fields())

    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(click, range(12)))
    ids = {json.loads(b)["run_id"] for c, _, b in results}
    assert len(ids) == 1
    assert sorted(c for c, _, _ in results) == [200] * 11 + [201]
    client.wait(ids.pop())
    assert len(engine.calls) == calls_before + 1


def test_decision_for_stale_revision_points_to_latest(make_server, case_bytes):
    client = make_server()
    parent = _complete(client, case_bytes)
    child = json.loads(client.post_form(f"/runs/{parent['run_id']}/revisions", _answer_fields())[2])["run_id"]
    client.wait(child)
    # Другое решение к старой редакции: 409 и ссылка на актуальный результат.
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", _answer_fields(text="Приоритет Ф-3"))
    assert code == 409
    data = json.loads(body)
    assert data["latest_run_id"] == child and data["stale"] is True
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", _answer_fields(text="Приоритет Ф-3"), json_accept=False)
    html = body.decode()
    assert code == 409 and "Редакция устарела" in html and f"/runs/{child}" in html
    # Старая страница сама предупреждает и не предлагает форму.
    page = client.get(f"/runs/{parent['run_id']}")[2].decode()
    assert 'id="stale"' in page and 'id="confirm-form"' not in page


def test_questions_md_roundtrip_via_answers_file(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    parent = _complete(client, case_bytes)
    code, hdr, data = client.get(f"/runs/{parent['run_id']}/questions.md")
    assert code == 200 and hdr["Content-Disposition"].startswith("attachment")
    text = data.decode()
    assert "## Q-01" in text and "## Q-03" in text
    # questions.md реально лежит среди артефактов (сформирован веб-слоем из report.json).
    names = {a["name"]: a["origin"] for a in client.get_json(f"/api/runs/{parent['run_id']}")["artifacts"]}
    assert names.get("web/questions.md") == "web"

    # Аналитик вписывает ответ в раздел Q-03 и меняет строку происхождения.
    section = re.search(r"## Q-03\n.*?Ответ:\n", text, re.S).group(0)
    filled_section = section.replace("Источник ответа: аналитик (веб-форма)", "Источник ответа: аналитик (файл answers.md)") + "400 Bad Request, пример 200 с ERROR удалить.\n"
    filled = text.replace(section, filled_section)
    assert filled != text
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", {}, {"answers_file": ("answers.md", filled.encode())})
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"])
    assert child["answers"]["origin"] == "upload"
    assert child["answers"]["provenance"] == {"аналитик (файл answers.md)": 1}
    assert _diff_keys(client.app.store, child["run_id"]) == ["api200"]


def test_empty_answers_rejected(make_server, case_bytes):
    client = make_server()
    parent = _complete(client, case_bytes)
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", {"a_Q-01": "  "})
    assert code == 400 and "ответ" in json.loads(body)["error"]
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", {}, {"answers_file": ("answers.md", b"## Q-1\n\xd0\x9e\xd1\x82\xd0\xb2\xd0\xb5\xd1\x82:\n\n")})
    assert code == 400


def test_decision_option_and_demo_answer_provenance(make_server, case_bytes, tmp_path):
    from bcc_review.web.service import Settings

    demo = tmp_path / "demo_answers.md"
    demo.write_text(
        "## Ф-3, Ф-4\nИсточник ответа: демонстрационный ответ команды, подготовлен 26.11.2026 для показа; не решение банка\nОтвет:\nПриоритет Ф-4.\n",
        encoding="utf-8",
    )
    client = make_server(settings=Settings(demo_answers=demo))
    parent = _complete(client, case_bytes)
    page = client.get(f"/runs/{parent['run_id']}")[2].decode()
    assert "Подставить демонстрационный ответ" in page
    assert "не решение банка" in page
    assert 'name="d_Q-02" value="1"' in page
    # Выбран вариант решения без своего текста — в answers.md попадает текст варианта и его происхождение.
    code, _, body = client.post_form(
        f"/runs/{parent['run_id']}/revisions",
        {"a_Q-02": "", "d_Q-02": "1", "p_Q-02": "вариант 1 из вопроса Q-02 (предложение движка, модель dev-mock)"},
    )
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"])
    text = open(client.app.store.input_dir(child["run_id"]) / "answers.md", encoding="utf-8").read()
    assert "По дате совершения в Asia/Almaty" in text
    assert "Источник ответа: вариант 1 из вопроса Q-02" in text


def test_revised_document_upload_becomes_new_revision(make_server, case_bytes):
    client = make_server()
    parent = _complete(client, case_bytes)
    fixed = case_bytes.decode().replace("На карту приходится максимум один такой push за календарный месяц.", "Лимит push сбрасывается при смене порога.").encode()
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", {}, {"document": ("case_ab_v2.md", fixed)})
    assert code == 201
    child = client.wait(json.loads(body)["run_id"])
    assert child["input"]["original_name"] == "case_ab_v2.md"
    assert child["input"]["sha256"] != parent["input"]["sha256"]
    assert "f3f4" in _diff_keys(client.app.store, child["run_id"])


def test_no_new_answers_means_no_new_run(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    r1 = _complete(client, case_bytes)
    calls = len(engine.calls)
    code, _, body = client.post_form(f"/runs/{r1['run_id']}/revisions", {})
    assert code == 400 and "повторный анализ не нужен" in json.loads(body)["error"]
    assert len(engine.calls) == calls and client.app.store.children(r1["run_id"]) == []
