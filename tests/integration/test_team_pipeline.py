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


def test_analyst_decision_with_team_decisions_module(tmp_path, monkeypatch, bcc_copy):
    """№08 строит вопросы и правку по «Формулировке», №09 закрывает конфликт по новому тексту."""
    import copy
    import json

    if not _present("bcc_review.decisions.clarify"):
        pytest.skip("№08 ещё не влит")
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")  # сценарий конфликта — тестовый двойник
    script = json.loads((FIX / "mock_bcc.json").read_text(encoding="utf-8"))
    s1 = tmp_path / "s1.json"
    s1.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    r1 = run(tmp_path, bcc_copy, "r1.md", provider="mock", mock_script=str(s1), use_cache=False)
    q = next(q for q in r1["questions"] if "Ф-4" in q["prompt"])
    conflict_id = next(f for f in q["finding_ids"] if any(x["id"] == f and x["kind"] == "conflict" for x in r1["findings"]))
    original = C.sha256_file(bcc_copy)
    answers = tmp_path / "answers.md"
    answers.write_text(f"<!-- bcc-review:answers v1 -->\nsource_sha256: {original}\n\n## {q['id']}\n"
                       "Ответ: смена порога не сбрасывает месячный лимит.\n"
                       "Формулировка: На карту приходится максимум один такой push за календарный месяц, "
                       "в том числе после изменения порога.\n", encoding="utf-8")
    script2 = copy.deepcopy(script)
    script2["cross"]["conflicts"] = []
    s2 = tmp_path / "s2.json"
    s2.write_text(json.dumps(script2, ensure_ascii=False), encoding="utf-8")
    r2 = run(tmp_path, bcc_copy, "r2.md", provider="mock", mock_script=str(s2), use_cache=False,
             answers_path=str(answers), compare_path=str(tmp_path / "r1.json"))
    assert C.sha256_file(bcc_copy) == original and r2["run"]["revision_of"] == original
    assert r2["run"]["source_name"] != bcc_copy.name and r2["document"]["id"] != original
    assert r2["decisions"] and r2["decisions"][0]["edits"]
    resolved = [e for e in r2["diff"]["resolved"] if conflict_id in e["old_ids"]]
    assert resolved and any("в том числе после изменения порога" in ev["quote"] for ev in resolved[0]["evidence"])
    omission = next(f["id"] for f in r1["findings"] if f["kind"] == "omission")
    assert any(omission in e["old_ids"] for e in r2["diff"]["persisting"])
    assert main(["verify", str(tmp_path / "r2.json"), str(tmp_path / r2["run"]["source_name"])]) == C.EXIT_OK
