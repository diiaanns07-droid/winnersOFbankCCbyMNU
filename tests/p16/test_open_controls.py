"""Три контрольных случая на открытом корпусе через настоящий CLI подсчёта.

Ручной ответ записан до запуска: evaluation/dev/controls/expected.json.
"""
from __future__ import annotations

import copy
import itertools
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.dev import controls
from evaluation.harness.runner import run_manifest
from evaluation.harness.schema import Manifest, parse_gold, parse_predictions, read_jsonl
from evaluation.harness.score import matrix_rows, score
from evaluation.harness.taxonomy import Taxonomy

REPO = Path(__file__).resolve().parents[2]
CTRL = REPO / "evaluation" / "dev" / "controls"
CORPUS = REPO / "evaluation" / "dev" / "corpus"
EXP = json.loads((CTRL / "expected.json").read_text(encoding="utf-8"))["expected"]
TAX = Taxonomy.load()
FAKE = (f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).with_name('fake_bcc_review.py')))} "
        "{input} {output}")


def ratio(v):
    if v is None:
        return None
    a, b = v.split("/")
    return pytest.approx(int(a) / int(b), abs=1e-12)


def cli(tmp: Path, *extra: str) -> tuple[dict, list[dict], str]:
    r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(CTRL / "labels.jsonl"),
                        "--pred", str(CTRL / "predictions.jsonl"), "--manifest", str(CTRL / "manifest.json"),
                        "--out-dir", str(tmp), *extra], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp / "metrics.json").read_text(encoding="utf-8"))
    return m, read_jsonl(tmp / "matrix.jsonl"), r.stdout


def test_controls_reproduce_and_corpus_unchanged():
    assert controls.check() == []
    # контроли не меняют корпус seed 1
    assert json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["corpus_semantic_sha256"] == \
        "8ddcb3f85b7d6f2d2392dddd5ea4ee1744f1a4fb1e35b7a9e807e44b041f7288"


@pytest.mark.parametrize("policy", ["hierarchy", "exact"])
def test_cli_matches_hand_answer(tmp_path, policy):
    m, matrix, out = cli(tmp_path, "--type-match", policy)
    e = EXP[policy]
    for k in ("tp", "fp", "fn", "duplicates", "pending_adjudication", "clean_false_alarms", "tp_parent_level"):
        assert m["micro"][k] == e[k], k
    for k in ("precision", "recall", "f1", "precision_strict"):
        assert m["micro"][k] == ratio(e[k]), k
    assert f"правило типов: {policy}" in out
    assert {p.name for p in tmp_path.iterdir()} >= {"metrics.json", "matrix.jsonl", "adjudication.jsonl", "summary.txt"}
    if policy == "hierarchy":
        got = sorted([r["outcome"], r["case_id"], r["label_id"], r["defect_id"]] for r in matrix)
        assert got == sorted(e["matrix"])
        fp = {r["defect_id"]: r for r in matrix if r["outcome"] == "FP"}
        c1 = controls.C1
        assert fp["F-08"]["disputed_with"] == [f"{c1}#1", f"{c1}#2"] and fp["F-08"]["pending"] is True
        assert fp["F-01"]["reasons"] == ["clean_false_alarm"] and fp["F-01"]["case_id"] == controls.C3
        dup = next(r for r in matrix if r["outcome"] == "DUP")
        assert (dup["defect_id"], dup["kept_defect_id"]) == ("F-01", "F-02")   # меньший pred_key, не первая строка
        for cid, exp in e["per_case"].items():
            for k, v in exp.items():
                assert m["per_case"][cid][k] == ratio(v), (cid, k)


def _run(pred_rows, policy="hierarchy"):
    g = parse_gold(read_jsonl(CTRL / "labels.jsonl"), TAX)
    p, r = parse_predictions(copy.deepcopy(pred_rows), TAX)
    return score(g, p, r, TAX, type_match=policy, manifest=Manifest.load(CTRL / "manifest.json"))


def _canon(m) -> str:
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "where"}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    return json.dumps([strip(m), matrix_rows(m)], ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize("policy", ["hierarchy", "exact"])
def test_permutations_of_findings(policy):
    rows = read_jsonl(CTRL / "predictions.jsonl")
    runs = [r for r in rows if r["record"] == "run"]
    finds = [r for r in rows if r["record"] == "finding"]
    outs = {_canon(_run(runs + list(perm), policy)) for perm in itertools.permutations(finds)}   # 5! = 120
    assert len(outs) == 1


def test_reversed_file_through_cli(tmp_path):
    """Тот же вход в обратном порядке строк через CLI даёт ту же матрицу."""
    rev = tmp_path / "rev.jsonl"
    rev.write_text("".join(reversed((CTRL / "predictions.jsonl").read_text(encoding="utf-8").splitlines(True))),
                   encoding="utf-8")
    a, ma, _ = cli(tmp_path / "a")
    r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(CTRL / "labels.jsonl"),
                        "--pred", str(rev), "--manifest", str(CTRL / "manifest.json"), "--out-dir", str(tmp_path / "b")],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    b = json.loads((tmp_path / "b" / "metrics.json").read_text(encoding="utf-8"))
    clean = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    assert clean(read_jsonl(tmp_path / "b" / "matrix.jsonl")) == clean(ma) and b["micro"] == a["micro"]


def test_zero_denominators():
    rows = [r for r in read_jsonl(CTRL / "predictions.jsonl") if r["record"] == "run"]
    m = _run(rows)
    ze = EXP["no_findings"]
    for k, v in ze["micro"].items():
        assert m["micro"][k] == ratio(v), k
    for cid, exp in ze["per_case"].items():
        for k, v in exp.items():
            assert m["per_case"][cid][k] == ratio(v), (cid, k)


def test_report_paths_fit_windows_budget(tmp_path):
    """Самый длинный case_id: относительные пути прогона ≤ 80 символов (база Windows ≈ 120, предел 260)."""
    longest = max((c["case_id"] for c in json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["cases"]),
                  key=len)
    out = tmp_path / "o"
    run_manifest(str(CORPUS / "manifest.json"), "rules_only", str(out), TAX, product_cmd=FAKE, cases=[longest],
                 fmt="docx")
    rel = [p.relative_to(tmp_path).as_posix() for p in out.rglob("*")]
    report_dirs = [x for x in rel if x.count("/") == 2 and x.startswith("o/reports/") and not x.endswith(".json")]
    # движок кладёт рядом артефакты этапов: <dir>/report.artifacts/stages/03-individual.json
    worst = max([len(x) for x in rel] + [len(d + "/report.artifacts/stages/03-individual.json") for d in report_dirs])
    assert report_dirs and worst <= 80, (worst, max(rel, key=len))
    index = json.loads((out / "reports" / "index.json").read_text(encoding="utf-8"))
    assert list(index.values()) == [f"{longest}@docx"]


def test_single_command_with_docs_dir(tmp_path):
    """Команда для закрытого корпуса: ключ + каталог документов, без ручного манифеста."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for case in json.loads((CTRL / "manifest.json").read_text(encoding="utf-8"))["cases"]:
        r = case["renders"][0]
        shutil.copy(CTRL / r["path"], docs / f"{case['control']}.md")
    (docs / "notes.txt").write_text("не из эталона", encoding="utf-8")
    out = tmp_path / "out"
    res = subprocess.run([sys.executable, "-m", "evaluation.harness", "run", "--gold", str(CTRL / "labels.jsonl"),
                          "--docs", str(docs), "--mode", "rules_only", "--product-cmd", FAKE, "--out", str(out)],
                         cwd=REPO, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "лишних файлов 1" in res.stdout and "кейсов без файла 0" in res.stdout
    for name in ("manifest.json", "predictions.jsonl", "metrics.json", "matrix.jsonl", "adjudication.jsonl",
                 "summary.txt", "run_config.json"):
        assert (out / name).exists(), name
    m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert m["counts"]["independent_cases"] == 3 and m["counts"]["missing_measurements"] == 0
    assert m["policy"]["mode"] == "rules_only" and m["runs"]["physical_calls"]["total"] == 0
    assert m["policy_version"] == "bcc-eval-policy/1" and len(m["harness_sha256"]) == 64


def test_docs_dir_missing_file_is_missing_measurement(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(CORPUS / "cases" / "cashback.base" / "source.md", docs / "a.md")
    out = tmp_path / "out"
    res = subprocess.run([sys.executable, "-m", "evaluation.harness", "run", "--gold", str(CTRL / "labels.jsonl"),
                          "--docs", str(docs), "--mode", "rules_only", "--product-cmd", FAKE, "--out", str(out)],
                         cwd=REPO, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert m["counts"]["independent_cases"] == 1 and m["counts"]["missing_measurements"] == 2
    assert {x["case_id"] for x in m["missing_measurements"]} == {controls.C1, controls.C2}
