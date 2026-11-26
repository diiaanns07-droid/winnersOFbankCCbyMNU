"""Два режима продукта, сетевая песочница rules_only, сравнение, адаптеры Report и меток."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.harness.adapter import flat_labels_to_gold, report_to_rows
from evaluation.harness.compare import build_table
from evaluation.harness.runner import run_manifest
from evaluation.harness.schema import Manifest, parse_gold, parse_predictions, read_jsonl
from evaluation.harness.score import score
from evaluation.harness.taxonomy import Taxonomy

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "evaluation" / "dev" / "corpus"
FAKE = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).with_name('fake_bcc_review.py')))} {{input}} {{output}}"
TAX = Taxonomy.load()
SUBSET = ["cashback.base", "cashback.two_statuses.bad_category_200", "transfer_limit.drop_promised.no_read_method",
          "autopay.base", "edge.empty"]


def _score(out: Path, fmt=None):
    gold = parse_gold(read_jsonl(CORPUS / "labels.jsonl"), TAX)
    gold = [g for g in gold if g.case_id in SUBSET]
    preds, runs = parse_predictions(read_jsonl(out / "predictions.jsonl"), TAX)
    m = score(gold, preds, runs, TAX, manifest=Manifest.load(CORPUS / "manifest.json"), render_format=fmt)
    m["inputs"] = {"gold": {"sha256": "same"}, "manifest": {"sha256": "same"}}
    return m


@pytest.fixture(scope="module")
def two_modes(tmp_path_factory):
    root = tmp_path_factory.mktemp("modes")
    import os
    os.environ["GEMINI_API_KEY"] = "dummy-test-value"   # должен исчезнуть в rules_only
    try:
        cfgs = {mode: run_manifest(str(CORPUS / "manifest.json"), mode, str(root / mode), TAX, product_cmd=FAKE,
                                   cases=SUBSET, cache="off") for mode in ("rules_only", "rules_plus_llm")}
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    return root, cfgs


def test_rules_only_has_zero_physical_calls_and_sandbox(two_modes):
    root, cfgs = two_modes
    assert cfgs["rules_only"]["network_sandbox"] is True and "GEMINI_API_KEY" in cfgs["rules_only"]["removed_env"]
    m = _score(root / "rules_only")
    assert m["runs"]["physical_calls"]["total"] == 0 and m["runs"]["violations"] == []
    for rep in (root / "rules_only" / "reports").rglob("report.json"):
        run = json.loads(rep.read_text(encoding="utf-8"))["run"]
        assert run["debug_secret_env"] == [] and run["debug_https_proxy"] == "http://127.0.0.1:9"
        assert run["calls"]["physical"] == 0 and run["mode"] == "rules_only" and run["provider"] == "none"
    llm = _score(root / "rules_plus_llm")
    assert llm["runs"]["physical_calls"]["total"] > 0


def test_same_manifest_and_cache_for_both_modes_and_table(two_modes):
    root, cfgs = two_modes
    assert cfgs["rules_only"]["manifest_sha256"] == cfgs["rules_plus_llm"]["manifest_sha256"]
    assert cfgs["rules_only"]["cache"] == cfgs["rules_plus_llm"]["cache"]
    md, data = build_table({"rules_only": _score(root / "rules_only"), "rules_plus_llm": _score(root / "rules_plus_llm")})
    assert data["comparable"], data["reasons"]
    row = {r["metric"]: r for r in data["rows"]}
    assert row["Физические вызовы LLM"]["rules_only"] == "0"
    assert row["Физические вызовы LLM"]["rules_plus_llm"] != "0"
    assert "Ложные тревоги на чистых" in md


def test_missing_measurements_are_visible_in_table(two_modes):
    """Если продукт не сообщил токены или прогон пропущен, в таблице «—» с причиной, а не ноль."""
    root, _ = two_modes
    a = _score(root / "rules_only")
    b = json.loads(json.dumps(_score(root / "rules_plus_llm")))
    b["runs"]["tokens"] = {"measured_runs": 0, "input": None, "output": None, "note": None}
    b["runs"]["duration_s"]["measured_runs"] = 0
    b["counts"]["missing_measurements"] = 1
    b["missing_measurements"] = [{"case_id": "autopay.base", "format": "md", "reason": "нет прогона"}]
    md, data = build_table({"rules_only": a, "rules_plus_llm": b})
    row = {r["metric"]: r for r in data["rows"]}
    assert row["Токены вход / выход"]["rules_plus_llm"] == "— (не сообщены)"
    assert row["Длительность, с: всего / медиана"]["rules_plus_llm"] == "— (не измерено)"
    assert row["Пропуски измерений"]["rules_plus_llm"] == "1"
    assert "autopay.base (md): нет прогона" in md


def test_rules_only_violation_is_caught(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MISBEHAVE", "calls_in_rules_only")
    run_manifest(str(CORPUS / "manifest.json"), "rules_only", str(tmp_path), TAX, product_cmd=FAKE,
                 cases=["cashback.base"])
    rows = read_jsonl(tmp_path / "predictions.jsonl")
    run = next(r for r in rows if r["record"] == "run")
    assert any("physical_calls=1" in v for v in run["violations"])


def test_different_cache_is_not_comparable(two_modes):
    root, _ = two_modes
    a, b = _score(root / "rules_only"), _score(root / "rules_plus_llm")
    b["runs"]["cache"] = ["{'policy': 'readwrite', 'dir': '/x'}"]
    ok, reasons = build_table({"a": a, "b": b})[1]["comparable"], build_table({"a": a, "b": b})[1]["reasons"]
    assert not ok and any("кэш" in r for r in reasons)


def test_missing_product_output_is_failed_run(tmp_path):
    run_manifest(str(CORPUS / "manifest.json"), "rules_only", str(tmp_path), TAX,
                 product_cmd=f"{shlex.quote(sys.executable)} -c pass", cases=["cashback.base"])
    run = next(r for r in read_jsonl(tmp_path / "predictions.jsonl") if r["record"] == "run")
    assert run["status"] == "failed" and "нет report.json" in run["violations"][0]


def test_formats_do_not_add_independent_cases(tmp_path):
    for fmt in ("md", "pdf", "docx"):
        run_manifest(str(CORPUS / "manifest.json"), "rules_only", str(tmp_path / fmt), TAX, product_cmd=FAKE,
                     cases=["cashback.base", "edge.empty"], fmt=fmt)
    merged = tmp_path / "all.jsonl"
    merged.write_text("".join((tmp_path / f / "predictions.jsonl").read_text(encoding="utf-8")
                              for f in ("md", "pdf", "docx")), encoding="utf-8")
    gold = [g for g in parse_gold(read_jsonl(CORPUS / "labels.jsonl"), TAX) if g.case_id in ("cashback.base", "edge.empty")]
    preds, runs = parse_predictions(read_jsonl(merged), TAX)
    m = score(gold, preds, runs, TAX, manifest=Manifest.load(CORPUS / "manifest.json"))
    assert m["counts"]["independent_cases"] == 2
    assert m["counts"]["physical_renders_measured"] == 6
    assert set(m["per_format"]) == {"md", "pdf", "docx"}
    assert all(v["cases_measured"] == 2 for v in m["per_format"].values())
    assert {x["format"] for x in m["format_consistency"]} == {"pdf", "docx"}
    empty = m["edge_cases"]["empty_input"][0]
    assert empty["findings"] == 0 and empty["empty_input_warning"] is True


# ------------------------------------------------------------------------- адаптеры
def _valid_report(**over) -> dict:
    """Report по контракту v1 с двумя находками: конфликт с witness и черновик с неизвестным kind."""
    blocks = [{"id": "b0001", "kind": "list_item", "section": ["A"], "text": "Порог от 100 до 5 000 ₸.",
               "loc": {"line_start": 3, "line_end": 3}},
              {"id": "b0002", "kind": "table_row", "section": ["B"], "text": "threshold | Порог баланса в тиынах",
               "loc": {"line_start": 9, "line_end": 9}}]
    e1 = {"block_id": "b0001", "start": 0, "end": 24, "quote": "Порог от 100 до 5 000 ₸."}
    e2 = {"block_id": "b0002", "start": 12, "end": 34, "quote": "Порог баланса в тиынах"}
    base = {"scope": "set", "criterion": "set_consistent", "severity": "major", "title": "Единицы", "impact": "x100",
            "req_ids": [], "hints": [], "anchor_status": "supported", "meaning_status": "confirmed",
            "blocks": ["development"], "witness": None}
    rep = {
        "schema_version": "1.0",
        "run": {"run_id": "r1", "source_sha256": "a" * 64, "agent_version": "0.1.0", "agent_commit": "abc123",
                "provider": "gemini", "model": "gemini-x", "mode": "rules_plus_llm", "status": "partial",
                "started_at": "2026-11-26T10:00:00Z", "finished_at": "2026-11-26T10:00:42Z", "duration_s": 42.0,
                "calls": {"physical": 7, "cache_hits": 2, "failed": 0, "retries": 1},
                "tokens": {"input": 1000, "output": 200}, "stages": [], "incomplete_stages": ["bank"],
                "evidence_audit": {"checked": 2, "confirmed": 2, "ambiguous": 0, "rejected": 0, "note": ""}},
        "document": {"id": "a" * 64, "title": "t", "format": "markdown", "blocks": blocks, "warnings": []},
        "requirements": [], "checks": [], "facts": [], "coverage": [], "questions": [], "checklist": [],
        "test_cases": [], "decisions": [], "diff": None, "warnings": [],
        "verdict": {"development": {"status": "not_ready", "reasons": [], "finding_ids": []},
                    "testing": {"status": "unknown", "reasons": [], "finding_ids": []}, "first_actions": []},
        "summary": {"requirements": 0, "reviewed_requirements": 0, "findings": 2,
                    "by_severity": {"critical": 0, "major": 1, "minor": 1},
                    "by_status": {"confirmed": 1, "needs_review": 1}, "critical_ids": [],
                    "checks": {"pass": 0, "issue": 0, "unknown": 0, "na": 0}},
        "findings": [
            {**base, "id": "F-001", "kind": "conflict", "status": "confirmed", "evidence": [e1],
             "witness": {"input": "threshold=1000", "outcome_a": "1000 ₸", "outcome_b": "10 ₸",
                         "evidence_a": e1, "evidence_b": e2}},
            {**base, "id": "F-002", "kind": "weird_new_kind", "severity": "minor", "status": "needs_review",
             "anchor_status": "incomplete", "meaning_status": "unchecked", "evidence": [],
             "hints": [{"block_id": "b0002", "quote": "в тиынах"}]},
        ],
    }
    rep.update(over)
    return rep


def test_report_adapter_maps_evidence_witness_hints_and_run():
    rows = report_to_rows(_valid_report(), TAX, render_id="x@md", case_id="x")
    f1, f2, run = rows
    assert f1["issue_type"] == "contradiction" and f1["defect_id"] == "F-001" and f1["format"] == "md"
    assert [a["quote"] for a in f1["anchors"]] == ["Порог от 100 до 5 000 ₸.", "Порог баланса в тиынах"]
    assert f1["anchors"][0]["locator"] == "line_end=3,line_start=3" and f1["scenario"] == "threshold=1000"
    assert f1["anchor_status"] == "supported" and f1["meaning_status"] == "confirmed"
    assert f2["issue_type"] is None and f2["kind"] == "weird_new_kind" and f2["anchors"][0]["quote"] == "в тиынах"
    assert (run["physical_calls"], run["cache_hits"], run["tokens_in"], run["tokens_out"], run["duration_s"]) == \
        (7, 2, 1000, 200, 42.0)
    assert run["status"] == "partial" and run["mode"] == "rules_plus_llm" and run["incomplete_stages"] == ["bank"]
    preds, runs = parse_predictions(rows, TAX)
    assert preds[1].issue_type == "other" and not preds[1].kind_mapped and runs[0].physical_calls == 7


def test_flat_labels_adapter():
    flat = [{"case_id": "c", "family": "f", "source_sha256": "b" * 64, "defect_id": "D-1", "type": "conflict",
             "criterion": "29148", "severity": "critical", "quote": "A", "line": 12, "related_quote": "B",
             "explanation": "e"}]
    g = flat_labels_to_gold(flat, TAX)[0]
    assert g["label_id"] == "D-1" and g["issue_type"] == "contradiction" and g["expected_outcome"] == "present"
    assert g["anchors"] == [{"role": "primary", "quote": "A", "locator": "line:12"},
                            {"role": "related", "quote": "B", "locator": None}]
    assert g["anchor_policy"] == "all"
    parse_gold([g], TAX)


# --------------------------------------------------------------- стык с контрактом v1
contracts = pytest.importorskip("bcc_review.contracts", reason="bootstrap bcc/integration не в checkout")


def test_contract_kinds_are_all_mapped():
    for kind in contracts.FINDING_KINDS:
        issue_type, mapped = TAX.map_kind(kind)
        assert mapped, kind
    assert TAX.map_kind("conflict")[0] == "contradiction" and TAX.map_kind("omission")[0] == "missing_element"


def test_test_report_fixture_is_contract_valid():
    rep = _valid_report()
    contracts.validate(rep)
    assert contracts.evidence_errors(rep) == []


def test_contract_example_adapts():
    rep = json.loads((REPO / "contracts" / "examples" / "minimal_report.json").read_text(encoding="utf-8"))
    contracts.validate(rep)
    rows = report_to_rows(rep, TAX)
    run = rows[-1]
    findings = rows[:-1]
    assert run["physical_calls"] == rep["run"]["calls"]["physical"] and run["mode"] == "mock"
    assert run["source_sha256"] == rep["document"]["id"] and run["format"] == "md"
    f = findings[0]
    assert f["issue_type"] == "contradiction"
    quotes = {a["quote"] for a in f["anchors"]}
    assert {"максимум один push за календарный месяц",
            "следующее достижение вызывает push независимо от истории"} <= quotes


@pytest.mark.parametrize("fmt", ["md", "pdf", "docx"])
def test_fake_product_reports_are_contract_valid(tmp_path, fmt):
    case = "transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method"
    for mode in ("rules_only", "mock"):
        run_manifest(str(CORPUS / "manifest.json"), mode, str(tmp_path / mode), TAX, product_cmd=FAKE,
                     cases=[case], fmt=fmt)
        for rep_path in (tmp_path / mode / "reports").rglob("report.json"):
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            contracts.validate(rep)
            assert contracts.evidence_errors(rep) == []
            assert rep["run"]["debug_no_cache"] is True   # --cache off → --no-cache


def _product_ready() -> bool:
    """Движок подключён, если CLI пишет OUTPUT.json (временная оболочка cli.py печатает usage)."""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "r.md"
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        subprocess.run([sys.executable, "-m", "bcc_review", str(REPO / "contracts/examples/two_linked_requirements.md"),
                        str(out), "--offline-lint"], cwd=REPO, env=env, capture_output=True, timeout=120)
        return out.with_suffix(".json").exists()


def test_real_product_rules_only_if_engine_connected(tmp_path, monkeypatch):
    """Стыковой тест с настоящим продуктом: включается, когда движок пишет report.json."""
    if not _product_ready():
        pytest.skip("python -m bcc_review ещё не пишет OUTPUT.json (cli.py — временная оболочка bootstrap)")
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    cmd = f"{shlex.quote(sys.executable)} -m bcc_review {{input}} {{output}}"
    cfg = run_manifest(str(CORPUS / "manifest.json"), "rules_only", str(tmp_path), TAX, product_cmd=cmd,
                       cases=["cashback.base", "cashback.two_statuses.bad_category_200", "edge.empty"], cwd=str(REPO))
    runs = [r for r in read_jsonl(tmp_path / "predictions.jsonl") if r["record"] == "run"]
    assert cfg["network_sandbox"] and all(r["status"] != "failed" for r in runs), runs
    assert all(r["physical_calls"] == 0 and not r["violations"] for r in runs), runs
    for rep_path in (tmp_path / "reports").rglob("report.json"):
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        contracts.validate(rep)
