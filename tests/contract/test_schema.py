"""Контракт v1: схема актуальна, пример валиден, инварианты опор соблюдены."""

import copy
import json
from pathlib import Path

import pytest

from bcc_review import contracts as C

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"


def load_example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_schema_file_in_sync():
    assert (ROOT / "contracts" / "v1.json").read_text(encoding="utf-8") == C.schema_json(), \
        "contracts/v1.json устарел: python -m bcc_review.contracts --write"


def test_schema_is_valid_draft_2020_12():
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(C.REPORT_SCHEMA)


def test_example_report_valid():
    rep = load_example()
    C.validate(rep)
    assert C.evidence_errors(rep) == []


def test_example_source_hash_matches_file():
    rep = load_example()
    src = ROOT / "contracts" / "examples" / "two_linked_requirements.md"
    assert C.sha256_file(src) == rep["document"]["id"] == rep["run"]["source_sha256"]


def test_example_conflict_has_two_bindings():
    f = load_example()["findings"][0]
    assert f["kind"] == "conflict" and f["status"] == "confirmed"
    assert {f["witness"]["evidence_a"]["block_id"], f["witness"]["evidence_b"]["block_id"]} == {"b0003", "b0004"}


@pytest.mark.parametrize("key", C.REPORT_KEYS)
def test_missing_top_level_key_rejected(key):
    rep = load_example()
    del rep[key]
    with pytest.raises(C.ContractError):
        C.validate(rep)


def test_empty_lists_not_null():
    rep = load_example()
    rep["checklist"] = None
    with pytest.raises(C.ContractError):
        C.validate(rep)


def test_bad_enum_rejected():
    rep = load_example()
    rep["findings"][0]["severity"] = "blocker"
    with pytest.raises(C.ContractError):
        C.validate(rep)


def test_tampered_quote_detected():
    rep = load_example()
    rep["findings"][0]["evidence"][0]["quote"] = "максимум два push"
    assert any("цитата не совпадает" in e for e in C.evidence_errors(rep))


def test_confirmed_without_anchor_detected():
    rep = load_example()
    rep["findings"][0]["anchor_status"] = "incomplete"
    assert any("confirmed без" in e for e in C.evidence_errors(rep))


def test_unknown_requirement_reference_detected():
    rep = load_example()
    rep["findings"][0]["req_ids"].append("R-99")
    assert any("R-99" in e for e in C.evidence_errors(rep))


def test_subschema_candidate():
    cand = {"scope": "set", "kind": "conflict", "criterion": "set_consistent", "severity": "critical",
            "title": "t", "impact": "i", "req_ids": ["R-01"], "hints": [{"block_id": "b0003", "quote": "q"}]}
    C.validate(cand, "Candidate")
    bad = copy.deepcopy(cand)
    bad["scope"] = "global"
    with pytest.raises(C.ContractError):
        C.validate(bad, "Candidate")


def test_provider_error_kinds():
    e = C.ProviderError("rate_limit", retry_after_s=3)
    assert e.transient and e.retry_after_s == 3
    assert not C.ProviderError("truncated").transient
    assert C.ProviderError("weird").kind == "unknown"


def test_run_options_coerce():
    o = C.RunOptions.coerce({"provider": "mock", "exports": ["html"]})
    assert o.provider == "mock" and o.exports == ("html",)
    with pytest.raises(C.ContractError):
        C.RunOptions.coerce({"nope": 1})
