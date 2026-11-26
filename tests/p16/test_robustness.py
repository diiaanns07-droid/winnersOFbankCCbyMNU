"""Устойчивость счётчика: порядок строк и повтор формата не меняют результат.

Ручной ответ записан до запуска в evaluation/harness/controls/robustness/expected.json.
"""
from __future__ import annotations

import copy
import itertools
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from evaluation.harness.schema import Manifest, parse_gold, parse_predictions, read_jsonl
from evaluation.harness.score import score
from evaluation.harness.taxonomy import Taxonomy

REPO = Path(__file__).resolve().parents[2]
CTRL = REPO / "evaluation" / "harness" / "controls" / "robustness"
TAX = Taxonomy.load()
EXP = json.loads((CTRL / "expected.json").read_text(encoding="utf-8"))["expected"]


def rows():
    return read_jsonl(CTRL / "labels.jsonl"), read_jsonl(CTRL / "predictions.jsonl")


def run(gold_rows, pred_rows, type_match="hierarchy", manifest=False):
    g = parse_gold(copy.deepcopy(gold_rows), TAX)
    p, r = parse_predictions(copy.deepcopy(pred_rows), TAX)
    return score(g, p, r, TAX, type_match=type_match,
                 manifest=Manifest.load(CTRL / "manifest.json") if manifest else None)


def _strip(obj):
    """Без поля where (номер входной строки — это происхождение, а не результат)."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k != "where"}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def canon(m) -> str:
    return json.dumps(_strip(m), ensure_ascii=False, sort_keys=True)


def frac(v):
    if v is None:
        return None
    a, b = v.split("/")
    return float(Fraction(int(a), int(b)))


@pytest.mark.parametrize("policy", ["hierarchy", "exact"])
def test_counter_matches_hand_answer(policy):
    g, p = rows()
    m = run(g, p, policy)
    e = EXP[policy]
    mi = m["micro"]
    for k in ("tp", "fp", "fn", "duplicates", "pending_adjudication", "clean_false_alarms", "tp_parent_level"):
        assert mi[k] == e[k], k
    for k in ("precision", "recall", "f1", "precision_strict"):
        assert mi[k] == pytest.approx(frac(e[k]), abs=1e-12), k
    assert {t["label_id"]: t["defect_id"] for t in m["true_positives"]} == e["tp_pairs"]
    assert {d["defect_id"]: d["duplicate_of"] for d in m["duplicates"]} == e["duplicates_of"]
    disputed = sorted([fp["defect_id"], n["label_id"], n["reason"]] for fp in m["false_positives"] for n in fp["near"])
    assert disputed == sorted(e["disputed_pairs"])
    assert m["counts"]["independent_cases"] == e["independent_cases"]
    assert m["policy"]["type_match"] == policy


def test_empty_denominators_keep_defined_values():
    g, p = rows()
    pc = run(g, p)["per_case"]
    for cid, exp in EXP["hierarchy"]["per_case"].items():
        for k, v in exp.items():
            assert pc[cid][k] == (None if v is None else pytest.approx(frac(v), abs=1e-12)), (cid, k)


@pytest.mark.parametrize("policy", ["hierarchy", "exact"])
def test_all_permutations_of_findings_give_identical_result(policy):
    g, p = rows()
    runs = [r for r in p if r["record"] == "run"]
    finds = [r for r in p if r["record"] == "finding"]
    outputs = set()
    for perm in itertools.permutations(finds):          # 5! = 120
        m = run(g, runs + list(perm), policy)
        if policy == "hierarchy":
            assert m["micro"]["tp"] == 2 and {t["label_id"] for t in m["true_positives"]} == {"rb.conflict#A", "rb.conflict#B"}
        outputs.add(canon(m))
    assert len(outputs) == 1


def test_all_permutations_of_gold_rows_give_identical_result():
    g, p = rows()
    outputs = {canon(run(list(perm), p)) for perm in itertools.permutations(g)}   # 4! = 24
    assert len(outputs) == 1


def test_seeded_joint_shuffles_of_all_rows():
    g, p = rows()
    base = canon(run(g, p))
    rnd = random.Random(20261127)
    for _ in range(200):
        g2, p2 = g[:], p[:]
        rnd.shuffle(g2)
        rnd.shuffle(p2)
        assert canon(run(g2, p2)) == base


def test_format_repeat_does_not_improve_metrics():
    g, p = rows()
    md_only = run(g, p, manifest=True)
    conflict_sha = next(x["source_sha256"] for x in g if x["case_id"] == "rb.conflict")
    # те же строки (находки и run) для DOCX того же case_id
    docx = [{k: v for k, v in r.items() if k != "source_sha256"} | {"render_id": "rb.conflict@docx"}
            for r in p if r.get("source_sha256") == conflict_sha]
    both = run(g, p + docx, manifest=True)
    assert both["counts"]["independent_cases"] == md_only["counts"]["independent_cases"] == EXP["format_repeat"]["independent_cases"]
    assert both["micro"] == md_only["micro"]
    assert both["per_format"]["docx"]["cases_measured"] == EXP["format_repeat"]["per_format_docx_cases"]
    assert both["counts"]["physical_renders_measured"] == md_only["counts"]["physical_renders_measured"] + 1


def test_conflicting_run_rows_resolved_conservatively():
    """Две разные строки run для одного представления: берётся худший статус в любом порядке."""
    g, p = rows()
    failed = dict(p[0], status="failed")
    a = run(g, p + [failed])
    b = run(g, [failed] + p)
    assert canon(a) == canon(b)
    assert [x["case_id"] for x in a["missing_measurements"]] == ["rb.conflict"]
    assert any("разные строки run" in w for w in a["warnings"])


def test_cli_output_distinguishes_policies(tmp_path):
    outs = {}
    for policy in ("hierarchy", "exact"):
        r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(CTRL / "labels.jsonl"),
                            "--pred", str(CTRL / "predictions.jsonl"), "--type-match", policy,
                            "--out", str(tmp_path / f"{policy}.json")], cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs[policy] = r.stdout
    assert "правило типов: hierarchy" in outs["hierarchy"] and "уровня parent: 1" in outs["hierarchy"]
    assert "правило типов: exact" in outs["exact"] and "уровня parent: 0" in outs["exact"]
    assert "TP=2 " in outs["hierarchy"] and "TP=1 " in outs["exact"]
