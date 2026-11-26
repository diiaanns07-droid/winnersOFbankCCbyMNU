"""Стыковой тест с bootstrap (bcc/integration, контракт v1 431f76d, движок 091e504).

Проверяет: типы пакета по ``bcc_review.contracts``, настоящий загрузчик, сквозной прогон
``run_review`` на mock-провайдере — движок берёт модуль №10 (``team:``), Report валиден,
опоры чек-листа совпадают с текстом блоков.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import fixture as fx
from bcc_review.bank import build_bank_pack, collect_questions

C = pytest.importorskip("bcc_review.contracts")
ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "tests" / "integration" / "fixtures" / "mock_bcc.json"


def test_pack_objects_validate_against_contract():
    c = fx.case()
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], fx.decisions(c["document"]), None,
                           coverage=fx.coverage(), questions=fx.questions(), criteria=fx.CRITERIA)
    C.validate(c["document"], "Document")
    for r in c["requirements"]:
        C.validate(r, "Requirement")
    for f in c["findings"]:
        C.validate(f, "Finding")
    for x in fx.coverage():
        C.validate(x, "Coverage")
    for d in fx.decisions(c["document"]):
        C.validate(d, "Decision")
    for row in pack["checklist"]:
        C.validate(row, "ChecklistRow")
    for tc in pack["test_cases"]:
        C.validate(tc, "TestCase")
    for q in collect_questions(pack):
        C.validate(q, "Question")
    report = {"document": c["document"], "checklist": pack["checklist"]}
    assert C.evidence_errors(report) == []


@pytest.fixture
def engine_env(monkeypatch):
    from bcc_review import engine

    monkeypatch.setattr(engine, "SLEEP", lambda s: None)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    return engine


@pytest.mark.parametrize("provider", ["mock", "none"])
def test_engine_end_to_end_uses_bank_module(tmp_path, engine_env, provider):
    opts = {"provider": provider, "cache_dir": str(tmp_path / "cache"), "artifacts_dir": str(tmp_path / "art")}
    if provider == "mock" and MOCK.exists():
        script = tmp_path / "script.json"
        script.write_text(MOCK.read_text("utf-8"), encoding="utf-8")
        opts["mock_script"] = str(script)
    from bcc_review.contracts import RunOptions

    rep = engine_env.run_review(fx.CASE_MD, tmp_path / "report.md", options=RunOptions.coerce(opts))
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    assert rep["run"]["modules"]["build_bank_pack"].startswith("team:bcc_review.bank.checklist")
    rows = rep["checklist"]
    assert len(rows) == 14 and rows[8]["text"].startswith("Требование содержит архитектуру")
    assert rows[8]["available"] == "yes" and rows[8]["checked"] == "unknown" and "требует подтверждения" in rows[8]["note"]
    biz = {t["values"]["input"] for t in rep["test_cases"] if t.get("kind") == "boundary" and t.get("level") == "business"}
    assert {999, 1000, 1000000, 1000001} <= biz
    on_disk = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert on_disk["checklist"] == rows
    bank_stage = next(s for s in rep["run"]["stages"] if s["name"] == "bank")
    assert bank_stage["status"] in ("ok", "partial")
    # №07: перепроверка отчёта без модели — ссылки open_question_id/req_ids/finding_ids не висят
    from bcc_review.cli import main as cli_main

    assert cli_main(["verify", str(tmp_path / "report.json"), str(fx.CASE_MD)]) == C.EXIT_OK
    # опоры строк — содержательные цитаты: ни шапок таблиц, ни меток «Ф-1.»
    quotes = [e["quote"] for row in rows for e in row["evidence"] if e["quote"].strip("| ")]
    assert all(len(q) >= 4 for q in quotes) and not any(q.startswith(("Parameter |", "Ф-1.")) for q in quotes)
    kinds8 = {f["kind"] for f in rep["findings"] if f["id"] in rows[7]["machine"]["blocking_finding_ids"][:1]}
    assert not kinds8 or kinds8 <= {"conflict", "incorrect"} or rows[7]["machine"]["blocking_finding_ids"] == []
    opened = [t for t in rep["test_cases"] if t.get("status") == "open"]
    assert opened and all(t["open_question_id"] is None and t["open_question"]["id"] for t in opened)
    bank_warn = [w for w in rep["warnings"] if isinstance(w, dict) and w.get("stage") == "bank"]
    assert all(not str(w.get("message", "")).startswith("{") for w in bank_warn)  # читаемые сообщения, не repr словаря
