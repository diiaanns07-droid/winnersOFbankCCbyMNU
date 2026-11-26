"""Полный конвейер с влитыми модулями команды (без принудительного резерва).

Проверяет стыки: Report валиден, verify проходит, паспорт честно показывает режим и реализации.
"""

import importlib.util

import pytest

from bcc_review import contracts as C
from bcc_review.cli import main

from .conftest import BCC, FIX, run

TEAM_SLOTS = {
    "read_text": "bcc_review.readers.text", "build_inventory": "bcc_review.analysis.inventory",
    "review_individual": "bcc_review.analysis.individual", "review_set": "bcc_review.analysis.cross",
    "resolve_candidate": "bcc_review.analysis.evidence", "load_criteria": "bcc_review.criteria",
}


def _present(mod):
    return importlib.util.find_spec(mod) is not None


def _check(tmp_path, rep, src, name="report"):
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    assert main(["verify", str(tmp_path / f"{name}.json"), str(src)]) == C.EXIT_OK
    for slot, mod in TEAM_SLOTS.items():
        if _present(mod) and slot in rep["run"]["modules"]:
            assert rep["run"]["modules"][slot].startswith("team:"), (slot, rep["run"]["modules"][slot])


def test_offline_lint_with_team_modules(tmp_path):
    rep = run(tmp_path, BCC, offline_lint=True)
    _check(tmp_path, rep, BCC)
    assert rep["run"]["mode"] == "rules_only" and rep["run"]["status"] == "partial"
    assert rep["findings"] and all(f["anchor_status"] == "supported" for f in rep["findings"] if f["status"] == "confirmed")
    assert rep["verdict"]["development"]["status"] != "ready"


def test_no_key_is_rules_only_with_team_modules(tmp_path):
    rep = run(tmp_path, BCC, provider="anthropic")
    _check(tmp_path, rep, BCC)
    assert rep["run"]["mode"] == "rules_only" and rep["run"]["calls"]["physical"] == 0
    assert rep["run"]["model"] is None
    assert {"individual", "cross"} <= set(rep["run"]["incomplete_stages"])
    assert rep["verdict"]["testing"]["status"] != "ready"


def test_gemini_no_key_not_marked_ok(tmp_path):
    rep = run(tmp_path, BCC, provider="gemini")
    stages = {s["name"]: s for s in rep["run"]["stages"]}
    assert stages["individual"]["status"] in ("failed", "skipped")
    assert stages["cross"]["status"] in ("failed", "skipped")


def test_mock_synthetic_with_team_modules(tmp_path):
    rep = run(tmp_path, BCC, provider="mock")
    _check(tmp_path, rep, BCC)
    assert rep["run"]["mode"] == "mock" and rep["run"]["calls"]["physical"] > 0


def test_second_topic_document(tmp_path):
    src = FIX / "other_topic_cashback.md"
    rep = run(tmp_path, src, offline_lint=True)
    _check(tmp_path, rep, src)
    titles = " ".join(f["title"] for f in rep["findings"]).lower()
    assert "get" in titles or "setcategories" in titles     # D4
    assert "тиын" in titles                                  # D7


def test_pdf_with_team_modules(tmp_path):
    src = FIX / "bcc_requirements.pdf"
    rep = run(tmp_path, src, offline_lint=True)
    _check(tmp_path, rep, src)
    assert rep["document"]["format"] == "pdf"
