"""Проверка состава прогонов до подсчёта (evaluation/harness/audit): по одному нарушению на копию прогона.

Каталоги прогонов собираются в tmp в обеих раскладках раннера: 0.1.0 (reports/<case>__<fmt>/, так пишет
счётчик сборки 2821989) и 0.1.2 (reports/<12 hex>/ + reports/index.json). Сквозной тест гоняет раннер этой
ветки с подставным продуктом. Настоящий продукт 2821989 проверяется на открытом стенде:
python -m evaluation.dev composition (результат — evaluation/dev/results/composition_open_stand.json).
"""
from __future__ import annotations

import ast
import hashlib
import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from evaluation.harness.audit import EXIT_INPUT, EXIT_OK, EXIT_UNKNOWN, EXIT_VIOLATIONS, audit
from evaluation.harness.audit.__main__ import main as audit_main

REPO = Path(__file__).resolve().parents[2]
A, B, C = "fam.mutant_a", "fam.mutant_b", "fam.base"  # C — чистый кейс
COMMIT = "2821989bc5a3691a26352de28ae4a11aae677360"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@pytest.fixture
def gold(tmp_path: Path) -> Path:
    rows = [{"case_id": A, "family": "fam", "source_sha256": sha(A), "issue_type": "unit_mismatch",
             "anchors": [{"quote": "q"}], "expected_outcome": "present"},
            {"case_id": B, "family": "fam", "source_sha256": sha(B), "issue_type": "status_conflict",
             "anchors": [{"quote": "q"}], "expected_outcome": "present"},
            {"case_id": C, "family": "fam", "source_sha256": sha(C), "issue_type": None, "anchors": [],
             "expected_outcome": "clean"}]
    p = tmp_path / "labels.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def make_report(cid: str, mode: str, **kw) -> dict:
    llm = mode == "rules_plus_llm"
    stages = [{"name": "inventory", "status": "ok", "calls": 1 if llm else 0, "cache_hits": 0, "reason": None},
              {"name": "individual", "status": "ok" if llm else "skipped", "calls": 2 if llm else 0, "cache_hits": 0,
               "reason": None if llm else "модель не вызывалась: режим --offline-lint"}]
    run = {"run_id": kw.pop("run_id", f"run-{mode}-{cid}"), "source_sha256": kw.pop("sha", sha(cid)),
           "source_name": "source.md", "agent_version": "0.1.0", "agent_commit": kw.pop("commit", COMMIT),
           "provider": "anthropic" if llm else "none", "model": "claude-x" if llm else None, "mode": mode,
           "status": kw.pop("status", "complete"), "status_reasons": kw.pop("status_reasons", []),
           "calls": {"physical": 3 if llm else 0, "cache_hits": 0, "failed": 0, "retries": 0},
           "tokens": {"input": 10 if llm else 0, "output": 5 if llm else 0}, "stages": kw.pop("stages", stages)}
    run.update(kw)
    return {"schema_version": "1.0", "run": run, "document": {"id": run["source_sha256"], "format": "markdown"},
            "findings": [], "summary": {"requirements": 4, "reviewed_requirements": 0}}


def make_run(root: Path, mode: str, layout: str = "0.1.0", reports: dict | None = None, rows: dict | None = None,
             skip: tuple = (), manifest_sha: str = "m" * 64, cache: str = "off", harness: str = "0.1.0") -> Path:
    """Каталог прогона, как его пишет раннер: run_config.json, predictions.jsonl, reports/<каталог>/report.json."""
    reports, rows = reports or {}, rows or {}
    root.mkdir(parents=True)
    pred, index = [], {}
    for cid in (A, B, C):
        if cid in skip:
            continue
        rid = f"{cid}@md"
        d = hashlib.sha256(rid.encode()).hexdigest()[:12] if layout == "0.1.2" else rid.replace("@", "__")
        index[d] = rid
        rp = root / "reports" / d / "report.json"
        rep = reports.get(cid, make_report(cid, mode))
        if rep is not None:
            rp.parent.mkdir(parents=True)
            rp.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
            (rp.parent / "stderr.txt").write_text("", encoding="utf-8")
        row = {"record": "run", "case_id": cid, "render_id": rid, "format": "md", "mode": mode,
               "source_sha256": sha(cid), "status": (rep or {}).get("run", {}).get("status", "failed"),
               "report_path": str(rp), "manifest_sha256": manifest_sha, "run_id": (rep or {}).get("run", {}).get("run_id"),
               "cache": {"policy": cache}}
        row.update(rows.get(cid, {}))
        pred.append({"record": "finding", "case_id": cid, "format": "md", "mode": mode, "defect_id": "F-1",
                     "issue_type": "ambiguity", "anchors": [{"quote": "q"}]})
        pred.append(row)
    if layout == "0.1.2":
        (root / "reports").mkdir(exist_ok=True)
        (root / "reports" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (root / "run_config.json").write_text(json.dumps({"mode": mode, "manifest_sha256": manifest_sha,
                                                      "cache": {"policy": cache}, "format": "primary_render",
                                                      "harness_version": harness}), encoding="utf-8")
    (root / "predictions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pred),
                                            encoding="utf-8")
    return root


def triples(res: dict) -> list:
    return sorted((m["code"], m["run"], m["case_id"]) for m in res["matrix"])


def run_audit(gold, tmp_path, ro=None, llm=None, **kw):
    ro = ro or make_run(tmp_path / "ro", "rules_only")
    llm = llm or make_run(tmp_path / "llm", "rules_plus_llm")
    return audit(gold, [f"rules_only={ro}", f"rules_plus_llm={llm}"], **kw)


# ------------------------------------------------------------------ допустимый состав
@pytest.mark.parametrize("layout", ["0.1.0", "0.1.2"])
def test_clean_pair_is_admissible_in_both_runner_layouts(gold, tmp_path, layout):
    res = run_audit(gold, tmp_path, make_run(tmp_path / "ro", "rules_only", layout),
                    make_run(tmp_path / "llm", "rules_plus_llm", layout), expect_agent_commit="2821989")
    assert res["verdict"]["exit_code"] == EXIT_OK
    assert res["matrix"] == [] and res["admissible_case_ids"] == sorted([A, B, C])
    cov = res["llm_coverage"]
    assert cov["rules_only"]["llm_ok"] == 0 and cov["rules_plus_llm"]["llm_ok"] == 3
    p = next(x for x in res["pairs"] if x["case_id"] == A)
    assert p["runs"]["rules_plus_llm"]["report_sha256"] == sha(A) and p["runs"]["rules_plus_llm"]["run_id"]


# ------------------------------------------------------------------ по одному нарушению
def test_same_name_changed_file_is_sha_mismatch(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm",
                   reports={A: make_report(A, "rules_plus_llm", sha=sha(A + " правка"))})
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("sha_mismatch", "rules_plus_llm", A)]
    reason = res["matrix"][0]["reason"]
    assert sha(A + " правка")[:12] in reason and "source_name=source.md" in reason and "прежнего файла" in reason
    assert res["verdict"]["exit_code"] == EXIT_VIOLATIONS and A not in res["admissible_case_ids"]


def test_document_run_twice_is_repeat(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    rerun = make_run(tmp_path / "llm" / "rerun", "rules_plus_llm", skip=(A, C),
                     reports={B: make_report(B, "rules_plus_llm", run_id="run-second")})
    (llm / "predictions.jsonl").write_text((llm / "predictions.jsonl").read_text(encoding="utf-8")
                                           + (rerun / "predictions.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("repeat", "rules_plus_llm", B)]
    assert "run-second" in res["matrix"][0]["reason"] and "объединит находки" in res["matrix"][0]["reason"]


def test_identical_row_written_twice_is_repeat(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    lines = (llm / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    row_b = next(l for l in lines if '"record": "run"' in l and B in l)
    (llm / "predictions.jsonl").write_text("\n".join(lines + [row_b]) + "\n", encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("repeat", "rules_plus_llm", B)]
    assert "одна и та же строка" in res["matrix"][0]["reason"]


def test_deleted_report_on_clean_input_is_missing_while_counter_would_count_it(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    (llm / "reports" / f"{C}__md" / "report.json").unlink()  # строка run complete и находка остались
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("missing_report", "rules_plus_llm", C)]
    reason = res["matrix"][0]["reason"]
    assert "status=complete" in reason and "посчитает кейс измеренным" in reason and "precision завысится" in reason
    assert res["matrix"][0]["expected_outcome"] == "clean"


def test_failed_run_reason_includes_stderr_of_crashed_product(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm", reports={C: None},
                   rows={C: {"status": "failed", "violations": ["нет report.json рядом с OUTPUT.md (exit=1)"]}})
    d = llm / "reports" / f"{C}__md"
    d.mkdir(parents=True)
    (d / "stderr.txt").write_text('anthropic {"status": "error", "kind": "overloaded", "http_status": 529}\n'
                                  "Traceback (most recent call last):\n_BootstrapProviderError: overloaded\n",
                                  encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("missing_report", "rules_plus_llm", C)]
    assert "exit=1" in res["matrix"][0]["reason"] and "_BootstrapProviderError: overloaded" in res["matrix"][0]["reason"]


def test_report_without_run_row_is_missing_for_counter(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    lines = [l for l in (llm / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
             if not ('"record": "run"' in l and A in l)]
    (llm / "predictions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("missing_report", "rules_plus_llm", A)]
    assert "подсчёт его не увидит" in res["matrix"][0]["reason"]


def test_symmetric_missing_is_excluded_not_violation(gold, tmp_path):
    failed = {"status": "failed", "status_reasons": ["inventory: не выделено ни одного требования"]}
    ro = make_run(tmp_path / "ro", "rules_only", reports={C: make_report(C, "rules_only", **failed)})
    llm = make_run(tmp_path / "llm", "rules_plus_llm", reports={C: make_report(C, "rules_only", **failed)})
    res = run_audit(gold, tmp_path, ro, llm)
    assert res["verdict"]["exit_code"] == EXIT_OK and res["matrix"] == []
    assert res["verdict"]["excluded_symmetric"] == [C] and res["admissible_case_ids"] == [A, B]


def test_requested_llm_but_report_rules_only_is_mode_mismatch(gold, tmp_path):
    no_key = make_report(B, "rules_only", provider="anthropic", status="partial",
                         status_reasons=["individual: anthropic: адаптер не создан: auth: Не задан ANTHROPIC_API_KEY"])
    res = run_audit(gold, tmp_path, llm=make_run(tmp_path / "llm", "rules_plus_llm", reports={B: no_key}))
    assert triples(res) == [("mode_mismatch", "rules_plus_llm", B)]
    reason = res["matrix"][0]["reason"]
    assert "запрошен rules_plus_llm, report.run.mode=rules_only" in reason and "ANTHROPIC_API_KEY" in reason


def test_rules_only_with_physical_calls_is_mode_mismatch(gold, tmp_path):
    rep = make_report(A, "rules_only")
    rep["run"]["calls"]["physical"] = 1
    res = run_audit(gold, tmp_path, ro=make_run(tmp_path / "ro", "rules_only", reports={A: rep}))
    assert triples(res) == [("mode_mismatch", "rules_only", A)]


def test_rules_plus_llm_without_successful_stage_is_mode_mismatch(gold, tmp_path):
    stages = [{"name": "individual", "status": "failed", "calls": 2, "cache_hits": 0, "reason": "529"}]
    rep = make_report(A, "rules_plus_llm", status="partial", stages=stages)
    res = run_audit(gold, tmp_path, llm=make_run(tmp_path / "llm", "rules_plus_llm", reports={A: rep}))
    assert triples(res) == [("mode_mismatch", "rules_plus_llm", A)]


# ------------------------------------------------------------------ допустимый partial
def test_partial_after_successful_response_is_admissible_and_shown_separately(gold, tmp_path):
    stages = [{"name": "inventory", "status": "ok", "calls": 2, "cache_hits": 0, "reason": None},
              {"name": "individual", "status": "failed", "calls": 0, "cache_hits": 0, "reason": "overloaded"}]
    rep = make_report(A, "rules_plus_llm", status="partial", stages=stages)
    llm = make_run(tmp_path / "llm", "rules_plus_llm", reports={A: rep})
    (llm / "reports" / f"{A}__md" / "stderr.txt").write_text(
        'anthropic {"status": "error", "kind": "overloaded", "http_status": 529}\n' * 2, encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert res["verdict"]["exit_code"] == EXIT_OK and res["matrix"] == []
    partial = [i for i in res["info"] if i["code"] == "partial"]
    assert [(i["run"], i["case_id"]) for i in partial] == [("rules_plus_llm", A)]
    assert "individual=failed" in partial[0]["reason"] and "отчёт их не учёл" in partial[0]["reason"]
    assert A in res["admissible_case_ids"]


def test_complete_report_with_unreported_adapter_errors_is_hidden_partial(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    (llm / "reports" / f"{B}__md" / "stderr.txt").write_text(
        'anthropic {"status": "error", "kind": "overloaded", "http_status": 529}\n' * 2, encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert res["verdict"]["exit_code"] == EXIT_OK
    partial = [i for i in res["info"] if i["code"] == "partial"]
    assert [(i["run"], i["case_id"]) for i in partial] == [("rules_plus_llm", B)]
    assert partial[0]["reason"].startswith("скрытый partial: report.run.status=complete")
    assert res["llm_coverage"]["rules_plus_llm"]["reports_with_unreported_errors"] == 1


# ------------------------------------------------------------------ неизвестно
def test_old_report_without_fields_is_unknown_not_admissible(gold, tmp_path):
    rep = make_report(C, "rules_plus_llm")
    for k in ("mode", "stages", "calls"):
        rep["run"].pop(k)
    res = run_audit(gold, tmp_path, llm=make_run(tmp_path / "llm", "rules_plus_llm", reports={C: rep}))
    assert triples(res) == [("unknown", "rules_plus_llm", C)]
    assert res["verdict"]["exit_code"] == EXIT_UNKNOWN and C not in res["admissible_case_ids"]
    assert "run.mode" in res["matrix"][0]["reason"] and "run.stages" in res["matrix"][0]["reason"]


def test_rules_only_report_needs_no_stages(gold, tmp_path):
    rep = make_report(A, "rules_only")
    rep["run"].pop("stages")
    res = run_audit(gold, tmp_path, ro=make_run(tmp_path / "ro", "rules_only", reports={A: rep}))
    assert res["verdict"]["exit_code"] == EXIT_OK


def test_unreadable_report_is_unknown(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    (llm / "reports" / f"{A}__md" / "report.json").write_text("{обрезан", encoding="utf-8")
    res = run_audit(gold, tmp_path, llm=llm)
    assert triples(res) == [("unknown", "rules_plus_llm", A)]


# ------------------------------------------------------------------ условия прогонов
def test_different_product_build_blocks_all_pairs(gold, tmp_path):
    llm = make_run(tmp_path / "llm", "rules_plus_llm",
                   reports={c: make_report(c, "rules_plus_llm", commit="f91d3b6" + "0" * 33) for c in (A, B, C)})
    res = run_audit(gold, tmp_path, llm=llm)
    assert ("config_mismatch", "rules_only, rules_plus_llm", "*") in triples(res)
    assert res["admissible_case_ids"] == [] and res["verdict"]["exit_code"] == EXIT_VIOLATIONS


def test_expected_agent_commit_and_cache(gold, tmp_path):
    ro = make_run(tmp_path / "ro", "rules_only", cache="on")
    res = run_audit(gold, tmp_path, ro=ro, expect_agent_commit="f91d3b6")
    codes = triples(res)
    assert ("config_mismatch", "rules_only", "*") in codes and ("config_mismatch", "rules_plus_llm", "*") in codes
    assert any("cache различается" in m["reason"] for m in res["matrix"])


# ------------------------------------------------------------------ CLI и независимость
def test_cli_writes_matrix_and_exit_codes(gold, tmp_path, capsys):
    llm = make_run(tmp_path / "llm", "rules_plus_llm")
    (llm / "reports" / f"{C}__md" / "report.json").unlink()
    ro = make_run(tmp_path / "ro", "rules_only")
    out = tmp_path / "audit"
    rc = audit_main(["--gold", str(gold), "--run", f"rules_only={ro}", "--run", f"rules_plus_llm={llm}",
                     "--out", str(out)])
    assert rc == EXIT_VIOLATIONS
    matrix = [json.loads(l) for l in (out / "matrix.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(m["code"], m["case_id"]) for m in matrix] == [("missing_report", C)]
    assert (out / "admissible_case_ids.txt").read_text(encoding="utf-8").split() == [A, B]
    md = (out / "composition.md").read_text(encoding="utf-8")
    assert "## Матрица: нарушение → case_id → причина" in md and "## Пары по ID и SHA" in md
    assert "missing_report" in capsys.readouterr().out
    assert audit_main(["--gold", str(gold), "--run", str(tmp_path / "нет")]) == EXIT_INPUT


def test_audit_reads_files_only_and_does_not_import_counter():
    pkg = REPO / "evaluation" / "harness" / "audit"
    for p in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.level <= 1 and not (node.module or "").startswith(("evaluation", "score", "matching")), p
                assert node.module not in ("score", "matching", "runner", "adapter"), p
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] in ("argparse", "hashlib", "json", "sys") for a in node.names), p


def test_end_to_end_with_branch_runner_and_fake_product(tmp_path):
    from evaluation.harness.runner import run_manifest
    from evaluation.harness.taxonomy import Taxonomy
    corpus = REPO / "evaluation" / "dev" / "corpus"
    subset = ["cashback.base", "cashback.unit_change.accrued_in_tiyn", "autopay.drop_promised.no_409_status"]
    gold = tmp_path / "labels.jsonl"
    gold.write_text("".join(l + "\n" for l in (corpus / "labels.jsonl").read_text(encoding="utf-8").splitlines()
                            if json.loads(l)["case_id"] in subset), encoding="utf-8")
    fake = f"{shlex.quote(sys.executable)} {shlex.quote(str(REPO / 'tests' / 'p16' / 'fake_bcc_review.py'))} {{input}} {{output}}"
    for mode in ("rules_only", "rules_plus_llm"):
        run_manifest(str(corpus / "manifest.json"), mode, str(tmp_path / mode), Taxonomy.load(), product_cmd=fake,
                     cases=subset, cache="off")
    specs = [f"rules_only={tmp_path / 'rules_only'}", f"rules_plus_llm={tmp_path / 'rules_plus_llm'}"]
    res = audit(gold, specs)
    assert res["verdict"]["exit_code"] == EXIT_OK and res["admissible_case_ids"] == sorted(subset)
    assert res["llm_coverage"]["rules_plus_llm"]["llm_ok"] == 3  # stages пуст: по run.calls
    copy = tmp_path / "copy"
    shutil.copytree(tmp_path / "rules_plus_llm", copy)  # копия: report_path в строках указывает на оригинал
    idx = json.loads((copy / "reports" / "index.json").read_text(encoding="utf-8"))
    short = next(k for k, v in idx.items() if v == "cashback.base@md")
    (copy / "reports" / short / "report.json").unlink()
    res = audit(gold, [specs[0], f"rules_plus_llm={copy}"])
    assert triples(res) == [("missing_report", "rules_plus_llm", "cashback.base")]


# ------------------------------------------------------------------ открытый стенд
def test_open_stand_result_matches_hand_answer():
    expected = json.loads((REPO / "evaluation" / "dev" / "composition_controls" / "expected.json")
                          .read_text(encoding="utf-8"))["scenarios"]
    result = json.loads((REPO / "evaluation" / "dev" / "results" / "composition_open_stand.json")
                        .read_text(encoding="utf-8"))
    assert result["ok"] is True and set(result["scenarios"]) == set(expected)
    for name, exp in expected.items():
        got = result["scenarios"][name]
        assert got["exit_code"] == exp["exit_code"], name
        assert sorted(map(list, got["matrix"])) == sorted(exp["matrix"]), name
        assert sorted(map(list, got["partial"])) == sorted(exp["partial"]), name
        assert got["admissible"] == exp["admissible"], name
        if exp["exit_code"] != EXIT_OK:  # существующий comparable() этих нарушений не видит
            assert got["existing_compare"]["comparable"] is True, name
