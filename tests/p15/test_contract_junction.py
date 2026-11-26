"""Стыковой тест с общим движком Max. Пропускается, пока bootstrap не опубликован.

Включается сам, когда в checkout появятся:
* ``contracts/v1.json`` — сверка типов фикстуры dev-движка и отчёта общего движка;
* ``run_review`` в пакете ``bcc_review`` — реальный прогон через Runner веб-слоя
  в режиме ``offline_lint`` (без сети и ключа).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.web import devengine, report_view
from bcc_review.web.engine import Runner, resolve_engine
from bcc_review.web.store import RunStore

from .conftest import _tail  # noqa: F401
from .conftest import CASE, ROOT

SCHEMA = ROOT / "contracts" / "v1.json"


def _validate(report: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, schema)


@pytest.mark.skipif(not SCHEMA.is_file(), reason="contracts/v1.json ещё не опубликован (bootstrap Max)")
def test_dev_fixture_matches_contract(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    report = devengine.run_review(CASE, out, options={"dev_delay": 0})
    _validate(json.loads(out.with_suffix(".json").read_text(encoding="utf-8")))
    assert report["schema_version"] == "1.0"


def _shared_engine():
    spec = resolve_engine("auto")
    if not spec.available:
        pytest.skip(f"общий движок не найден: {spec.error}")
    return spec


def test_shared_engine_through_web_runner(tmp_path: Path) -> None:
    spec = _shared_engine()
    store = RunStore(tmp_path)
    rid = store.create_run(
        original_name="case_ab.md",
        data=CASE.read_bytes(),
        options={"export": ["html"], "offline_lint": True},
        engine=spec.describe(),
    )
    runner = Runner(store, spec)
    runner._execute(rid)  # синхронно, без пула
    rec = store.load(rid)
    assert rec["status"] in ("complete", "partial"), rec["error"]
    report = json.loads(store.report_json(rid).read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.0"
    assert report["run"]["source_sha256"] == rec["input"]["sha256"]
    assert report["run"]["mode"] == "rules_only"
    if SCHEMA.is_file():
        _validate(report)
    view = report_view.build(report)
    assert view.contract_notes == []
    names = {a["name"] for a in rec["artifacts"]}
    assert {"report.md", "report.json"} <= names


EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"


def _contract_engine(report_source: Path | None = None, *, hold=None, seen: list | None = None):
    """Движок-заглушка «как общий»: принимает только RunOptions и пишет заданный Report."""
    from bcc_review.contracts import RunOptions

    def run_review(input_path, report_md, *, options=None):
        opts = RunOptions.coerce(options)  # упадёт, если веб передал лишний ключ
        if seen is not None:
            seen.append(opts)
        out = Path(report_md)
        trace = Path(opts.artifacts_dir) / "trace.jsonl"
        trace.write_text(json.dumps({"stage": "read", "status": "ok"}) + "\n" + json.dumps({"stage": "cross", "status": "start"}) + "\n", encoding="utf-8")
        if hold is not None:
            hold.wait(10)
        report = json.loads((report_source or EXAMPLE).read_text(encoding="utf-8"))
        report["run"]["run_id"] = opts.run_id
        out.write_text("# Отчёт\n", encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return report

    return run_review


@pytest.mark.skipif(not EXAMPLE.is_file(), reason="нет contracts/examples/minimal_report.json")
def test_web_options_pass_runoptions_coerce_and_example_renders(make_server):
    from bcc_review.web.engine import EngineSpec

    seen: list = []
    client = make_server(EngineSpec("shared", "contract-stub", _contract_engine(seen=seen)))
    created = client.upload("two_linked_requirements.md", (ROOT / "contracts/examples/two_linked_requirements.md").read_bytes())
    st = client.wait(created["run_id"])
    assert st["status"] == "complete", st["error"]
    opts = seen[0]
    assert opts.run_id == created["run_id"] and opts.exports == ("html",)
    assert _tail(opts.artifacts_dir, f"{created['run_id']}/artifacts")
    rec = client.app.store.load(created["run_id"])
    assert rec["engine_options_dropped"] == ["progress", "tmp_dir"]  # пока их нет в RunOptions
    page = client.get(f"/runs/{created['run_id']}")[2].decode()
    assert "нельзя начинать" in page and "Подтверждён критичный конфликт F-001" in page
    assert page.count('class="fragment"') == 2 and page.count("<mark>") == 2
    assert 'name="d_Q-001" value="1"' in page and "Сбрасывает ли смена порога месячный лимит push?" in page
    assert "Расхождения с контрактом" not in page
    assert "проверка смысла" in page  # этапы из report.run.stages
    # Ответ на вопрос примера → дочерний запуск с answers_path и compare_path.
    code, _, body = client.post_form(f"/runs/{created['run_id']}/revisions", {"a_Q-001": "", "d_Q-001": "2", "p_Q-001": "вариант 2"})
    assert code == 201, body
    client.wait(json.loads(body)["run_id"])
    assert _tail(seen[1].answers_path, "/input/answers.md") and _tail(seen[1].compare_path, f"{created['run_id']}/artifacts/report.json")
    assert seen[1].parent_run_id == created["run_id"]
    assert "Нет, лимит один push в месяц сохраняется" in Path(seen[1].answers_path).read_text(encoding="utf-8")


def test_live_stages_from_engine_trace(make_server):
    import threading

    from bcc_review.web.engine import EngineSpec

    hold = threading.Event()
    client = make_server(EngineSpec("shared", "contract-stub", _contract_engine(hold=hold)))
    rid = client.upload("two_linked_requirements.md", (ROOT / "contracts/examples/two_linked_requirements.md").read_bytes())["run_id"]
    st = client.wait(rid, until=lambda s: any(e.get("source") == "trace" for e in s["events"]))
    assert [(e["stage"], e["state"]) for e in st["events"] if e.get("source") == "trace"] == [("read", "done"), ("cross", "start")]
    page = client.get(f"/runs/{rid}")[2].decode()
    assert '<span class="ico">✓</span> чтение документа' in page and '<span class="ico">…</span> проверка набора' in page
    hold.set()
    client.wait(rid)


MOCK_BCC = ROOT / "tests" / "integration" / "fixtures" / "mock_bcc.json"
EDIT_OLD = "На карту приходится максимум один такой push за календарный месяц."
EDIT_NEW = "После смены порога в том же месяце разрешён ещё один push."


def _mock_script(tmp_path: Path) -> Path:
    """Сценарий mock-провайдера Max + этап questions (вопрос к конфликту Ф-3/Ф-4); фикстура не должна отстать от Max."""
    fixture = ROOT / "tests" / "p15" / "fixtures" / "mock_case_web.json"
    script = json.loads(MOCK_BCC.read_text(encoding="utf-8"))
    ours = json.loads(fixture.read_text(encoding="utf-8"))
    assert {k: v for k, v in ours.items() if k != "questions"} == script, "mock_case_web.json устарел: пересоберите из mock_bcc.json"
    return fixture


@pytest.mark.skipif(not MOCK_BCC.is_file(), reason="нет tests/integration/fixtures/mock_bcc.json (движок Max)")
def test_real_engine_full_path_with_mock_provider(make_server, tmp_path):
    from bcc_review.web.service import Settings

    spec = _shared_engine()
    client = make_server(spec, settings=Settings(provider="mock", mock_script=_mock_script(tmp_path), cache_dir=tmp_path / "cache",
                                                 demo_answers=ROOT / "tests" / "p15" / "fixtures" / "demo_answers.md"))
    home = client.get("/")[2].decode()
    assert "mock-провайдер движка" in home
    parent = client.wait(client.upload("case_ab.md", CASE.read_bytes())["run_id"], timeout=120)
    assert parent["status"] in ("complete", "partial"), parent["error"]
    assert parent["report"]["mode"] == "mock" and parent["report"]["provider"] == "mock"
    page = client.get(f"/runs/{parent['run_id']}")[2].decode()
    # 091e504: конфликт из сценария → «нельзя начинать»; 6be9e97+: модули команды, прогон partial → «не определено».
    assert ("нельзя начинать" in page or "не определено" in page) and "Расхождения с контрактом" not in page
    report1 = json.loads(client.app.store.report_json(parent["run_id"]).read_text(encoding="utf-8"))
    q1 = report1["questions"][0]
    qid = q1["id"]  # Q-001 у резервного движка, Q-01 у №08
    assert page.count("<mark>") >= 2 and f"<b>{qid}.</b>" in page
    assert "Подставить демонстрационный ответ" in page and "не решение банка" in page  # ключи «Ф-3, Ф-4»
    assert "объединение замечаний" in page  # этапы из report.run.stages настоящего движка
    names = {a["name"] for a in parent["artifacts"]}
    assert {"report.md", "report.json", "report.html", "trace.jsonl"} <= names
    assert "Служебные файлы движка" in page

    # Правка в форме, которую движок применит: «Формулировка» к цели вопроса №08 или «было → стало».
    fields = {f"a_{qid}": "Да, смена порога сбрасывает лимит.", f"p_{qid}": "аналитик (веб-форма)"}
    if q1.get("target"):
        assert 'name="w_' + qid + '"' in page and "Движок заменит предложение с выделенным фрагментом" in page
        fields[f"w_{qid}"] = EDIT_NEW
    else:
        fields.update({f"eo_{qid}": EDIT_OLD, f"en_{qid}": EDIT_NEW})
    code, _, body = client.post_form(f"/runs/{parent['run_id']}/revisions", fields)
    assert code == 201, body
    child = client.wait(json.loads(body)["run_id"], timeout=120)
    assert child["status"] in ("complete", "partial"), child["error"]
    report = json.loads(client.app.store.report_json(child["run_id"]).read_text(encoding="utf-8"))
    assert report["run"]["run_id"] == child["run_id"] and report["run"]["parent_run_id"] == parent["run_id"]
    assert [d["question_id"] for d in report["decisions"]] == [qid] and len(report["decisions"][0]["edits"]) == 1
    stages = {s["name"]: s["status"] for s in report["run"]["stages"]}
    assert stages.get("answers") == "ok", report["run"]["stages"]
    revision = [a["name"] for a in child["artifacts"] if ".rev-" in a["name"] and a["name"].endswith(".md")]
    assert revision, "движок записал редакцию B отдельным файлом"
    assert EDIT_NEW in (client.app.store.artifacts_dir(child["run_id"]) / revision[0]).read_text(encoding="utf-8")
    assert report["diff"] is not None
    child_page = client.get(f"/runs/{child['run_id']}")[2].decode()
    assert "Сравнение с редакцией 1" in child_page and "Решения, учтённые движком (1)" in child_page
    assert revision[0] in child_page
    # Изменённый пункт виден на странице новой редакции: было → стало и пункт целиком.
    assert 'id="changes"' in child_page and EDIT_NEW in child_page


PDF = ROOT / "tests" / "integration" / "fixtures" / "bcc_requirements.pdf"


@pytest.mark.skipif(not PDF.is_file(), reason="нет PDF-фикстуры движка")
def test_real_engine_pdf_upload_offline(make_server, tmp_path):
    pytest.importorskip("pymupdf", reason="чтение PDF движком требует pymupdf (extra [pdf])")
    from bcc_review.web.service import Settings

    client = make_server(_shared_engine(), settings=Settings(cache_dir=tmp_path / "cache"))
    created = client.upload("bcc_requirements.pdf", PDF.read_bytes())
    st = client.wait(created["run_id"], timeout=180)
    assert st["status"] in ("complete", "partial"), st["error"]
    report = json.loads(client.app.store.report_json(created["run_id"]).read_text(encoding="utf-8"))
    assert report["document"]["format"] == "pdf"
    page = client.get(f"/runs/{created['run_id']}")[2].decode()
    assert "Расхождения с контрактом" not in page and "чтение документа" in page
    assert all("page" in b["loc"] for b in report["document"]["blocks"])
    if report["findings"]:  # без ключа (rules_only) замечаний может не быть
        assert "стр. " in page
