"""Сбои и граничные случаи: нет ключа, сеть, неполный парсинг, перезагрузка страницы, перезапуск сервера."""

from __future__ import annotations

import json
import threading

import pytest

from bcc_review.web import devengine
from bcc_review.web.engine import EngineSpec, resolve_engine

from .conftest import CountingEngine, make_pdf

KEY_VARS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def no_keys(monkeypatch):
    for k in KEY_VARS:
        monkeypatch.delenv(k, raising=False)


def test_missing_key_runs_rules_only_and_says_report_is_incomplete(make_server, case_bytes, no_keys):
    engine = CountingEngine()
    client = make_server(engine, name="shared")  # не dev: предварительная проверка ищет ключ
    home = client.get("/")[2].decode()
    assert "Ключ LLM не найден" in home and "ANTHROPIC_API_KEY" in home
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert engine.calls[0]["options"]["offline_lint"] is True
    assert st["status"] == "partial"
    assert st["report"]["mode"] == "rules_only"
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "Отчёт неполный" in page
    assert "только правила (без LLM)" in page
    assert "не определено: проверка неполная" in page  # движок не выдал готовность без семантики


def test_placeholder_key_counts_as_missing(make_server, case_bytes, monkeypatch, no_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    client = make_server(CountingEngine(), name="shared")
    assert client.app.service.preflight()["key_present"] is False


def test_engine_failing_on_missing_key_offers_rules_only_retry(make_server, case_bytes):
    engine = CountingEngine(scenario="no_key")
    client = make_server(engine)
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "failed"
    assert st["error"]["kind"] == "missing_key" and "ANTHROPIC_API_KEY" in st["error"]["message"]
    assert st["artifacts"] == []
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "Причина:" in page and "Проверить только по правилам (без LLM)" in page
    code, _, body = client.post_form(f"/runs/{st['run_id']}/retry", {"offline": "1"})
    assert code == 201
    retry = client.wait(json.loads(body)["run_id"])
    assert retry["status"] == "partial" and retry["report"]["mode"] == "rules_only"
    assert retry["revision"] == st["revision"] and retry["lineage_id"] == st["lineage_id"]
    # Повторный клик по той же кнопке — тот же запуск.
    code, _, body = client.post_form(f"/runs/{st['run_id']}/retry", {"offline": "1"})
    assert code == 200 and json.loads(body)["run_id"] == retry["run_id"]
    assert len(engine.calls) == 2


def test_network_failure_shows_actual_mode_and_warning(make_server, case_bytes):
    client = make_server(CountingEngine(scenario="network"))
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "partial" and st["report"]["mode"] == "rules_only"
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "Отчёт неполный" in page and "LLM недоступна" in page
    assert "только правила (без LLM)" in page


def test_partial_parse_is_visible(make_server, case_bytes):
    client = make_server(CountingEngine(scenario="parse_partial"))
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "partial"
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "документ разобран не полностью" in page
    assert "Таблица на строках 140–158 не распознана" in page


def test_pdf_with_empty_page_is_partial(make_server):
    client = make_server(CountingEngine())
    pdf = make_pdf(["Requirements F-1 threshold 1000", ""])
    st = client.wait(client.upload("scan.pdf", pdf)["run_id"])
    assert st["status"] == "partial"
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "Страница 2: текст не извлечён" in page


def test_engine_crash_reports_reason_and_completed_stages(make_server, case_bytes):
    client = make_server(CountingEngine(scenario="crash"))
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "failed"
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "Внутренняя ошибка движка на этапе проверки смысла" in page
    assert 'class="done"><span class="ico">✓</span> чтение документа' in page
    assert 'class="fail"' in page
    assert "Повторить запуск" in page


def test_reopening_page_during_job_shows_live_state(make_server, case_bytes):
    hold = threading.Event()
    client = make_server(CountingEngine(hold=hold))
    rid = client.upload("case_ab.md", case_bytes)["run_id"]
    st = client.wait(rid, until=lambda s: s["status"] == "running" and s["events"])
    assert st["final"] is False and st["artifacts"] == []
    for _ in range(2):  # «закрыл и снова открыл» страницу
        page = client.get(f"/runs/{rid}")[2].decode()
        assert 'data-run-status="running"' in page
        assert "выполняется" in page and "чтение документа" in page
        assert 'id="verdict"' not in page
    # Без измеренных прогонов срок не обещаем.
    assert "по измеренным прогонам" not in page
    hold.set()
    assert client.wait(rid)["status"] == "complete"
    assert 'data-run-status="complete"' in client.get(f"/runs/{rid}")[2].decode()


def test_eta_only_from_measured_runs(make_server, case_bytes):
    hold = threading.Event()
    engine = CountingEngine()
    client = make_server(engine)
    client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    engine.hold = hold
    rid = client.upload("case_ab.md", case_bytes)["run_id"]
    client.wait(rid, until=lambda s: s["status"] == "running")
    page = client.get(f"/runs/{rid}")[2].decode()
    assert "по измеренным прогонам этого движка: медиана" in page and "(1 шт.)" in page
    hold.set()
    client.wait(rid)


def test_server_restart_during_job_marks_interrupted(make_server, case_bytes, tmp_path):
    hold = threading.Event()
    data = tmp_path / "shared"
    first = make_server(CountingEngine(hold=hold), data_dir=data)
    rid = first.upload("case_ab.md", case_bytes)["run_id"]
    first.wait(rid, until=lambda s: s["status"] == "running")
    # Новый процесс сервера над теми же файлами (старый поток ещё висит на hold).
    second = make_server(CountingEngine(), data_dir=data)
    st = second.get_json(f"/api/runs/{rid}")
    assert st["status"] == "failed" and st["error"]["kind"] == "interrupted"
    page = second.get(f"/runs/{rid}")[2].decode()
    assert "веб-сервер перезапустили" in page and "Повторить запуск" in page
    hold.set()


def test_shared_engine_missing_blocks_new_runs_but_not_pages(make_server, case_bytes):
    spec = resolve_engine("bcc_review.not_merged_yet:run_review")  # как до влития движка
    assert not spec.available
    client = make_server(spec)
    home = client.get("/")[2].decode()
    assert "Новый анализ недоступен" in home and "No module named" in home
    code, _, body = client.post_form("/api/runs", {"upload_key": "k" * 16}, {"file": ("case_ab.md", case_bytes)})
    assert code == 503


def test_auto_never_picks_dev_engine_silently(monkeypatch):
    monkeypatch.setenv("BCC_REVIEW_ENGINE", "bcc_review.web.devengine:run_review")
    spec = resolve_engine("auto")
    assert spec.func is not devengine.run_review


def test_cross_origin_post_rejected(make_server, case_bytes):
    client = make_server()
    code, _, _ = client.post_form("/api/runs", {"upload_key": "x" * 16}, {"file": ("a.md", b"# a")}, headers={"Origin": "http://evil.example"})
    assert code == 403


def test_unsupported_format_and_traversal(make_server):
    client = make_server()
    code, _, body = client.post_form("/api/runs", {"upload_key": "y" * 16}, {"file": ("tool.exe", b"MZ")})
    assert code == 415 and "не поддерживается" in json.loads(body)["error"]
    assert client.get("/runs/../../etc/passwd")[0] == 404
    assert client.get("/runs/20260101-000000-abcdef/files/../run.json")[0] == 404


def test_demo_mode_is_separate_and_labelled(make_server, case_bytes, tmp_path):
    from bcc_review.web.__main__ import main

    data = tmp_path / "live"
    live = make_server(CountingEngine(), data_dir=data)
    parent = live.wait(live.upload("case_ab.md", case_bytes)["run_id"])
    code, _, body = live.post_form(f"/runs/{parent['run_id']}/revisions", {"a_Q-01": "Приоритет Ф-4"})
    child = live.wait(json.loads(body)["run_id"])
    bundle = tmp_path / "bundle"
    assert main(["pack", child["run_id"], "--data-dir", str(data), "--out", str(bundle)]) == 0
    manifest = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["runs"]) == {parent["run_id"], child["run_id"]}  # родитель попал автоматически

    viewer = make_server(CountingEngine(), data_dir=tmp_path / "empty", demo_dir=bundle)
    home = viewer.get("/")[2].decode()
    assert "Сохранённые прогоны (демонстрация, не живой анализ)" in home
    page = viewer.get(f"/demo/runs/{child['run_id']}")[2].decode()
    assert "Демонстрация сохранённого прогона" in page and "dev-mock" in page
    assert "(Алматы)" in page
    assert 'id="confirm-form"' not in page
    assert viewer.get(f"/demo/runs/{child['run_id']}/compare")[0] == 200
    assert viewer.get(f"/demo/runs/{child['run_id']}/files/report.md")[0] == 200
    code, _, _ = viewer.post_form(f"/demo/runs/{child['run_id']}/revisions", {"a_Q-01": "x"})
    assert code == 404
    assert len(viewer.app.runner.store.list_runs()) == 0


def test_unknown_engine_report_status_is_not_trusted_blindly(make_server, case_bytes):
    def weird(input_path, report_md, *, options=None):
        rep = devengine.run_review(input_path, report_md, options={**(options or {}), "dev_delay": 0})
        rep["run"]["status"] = "done"
        open(str(report_md).replace(".md", ".json"), "w", encoding="utf-8").write(json.dumps(rep, ensure_ascii=False))
        return rep

    client = make_server(EngineSpec("shared", "tests:weird", weird))
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "partial"
    assert any("неизвестный run.status" in w for w in st["warnings"])


def test_engine_without_report_is_failed(make_server, case_bytes):
    client = make_server(EngineSpec("shared", "tests:noop", lambda i, r, *, options=None: None))
    st = client.wait(client.upload("case_ab.md", case_bytes)["run_id"])
    assert st["status"] == "failed" and st["error"]["kind"] == "no_report"


@pytest.mark.parametrize("kind, expected", [("not_configured", "missing_key"), ("auth", "missing_key"), ("overloaded", "network"), ("refusal", "engine_error")])
def test_provider_error_kinds_map_to_next_step(kind, expected):
    from bcc_review.contracts import ProviderError
    from bcc_review.web.engine import classify_error

    assert classify_error(ProviderError(kind, "сообщение адаптера"))["kind"] == expected
