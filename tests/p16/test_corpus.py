"""Открытый корпус: воспроизводимость по seed, опоры, форматы, чистые контроли, изоляция."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from evaluation.dev import generator as gen
from evaluation.dev.families import DEFECT_OPS, FAMILIES, OPS
from evaluation.harness.normalize import tokens

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "evaluation" / "dev" / "corpus"


def manifest():
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


def labels():
    return [json.loads(l) for l in (CORPUS / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def test_same_seed_same_semantic_hash():
    a = gen.generate_cases([1])
    b = gen.generate_cases([1])
    assert [c.semantic_sha256 for c in a] == [c.semantic_sha256 for c in b]
    assert gen.corpus_semantic_sha256(a, [1], False) == gen.corpus_semantic_sha256(b, [1], False)


def test_seed_and_version_change_hash(monkeypatch):
    h1 = gen.corpus_semantic_sha256(gen.generate_cases([1]), [1], False)
    h2 = gen.corpus_semantic_sha256(gen.generate_cases([2]), [2], False)
    assert h1 != h2
    monkeypatch.setattr(gen, "GENERATOR_VERSION", "9.9.9")
    assert gen.corpus_semantic_sha256(gen.generate_cases([1]), [1], False) != h1


def test_case_id_is_content_addressed_across_seeds():
    """Разные seed с одним вариантом дают один кейс, а не два «независимых»."""
    cases = gen.generate_cases([1, 2, 3, 4, 5, 6])
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))
    texts = Counter(c.text for c in cases)
    assert max(texts.values()) == 1


def test_committed_corpus_matches_generator():
    r = subprocess.run([sys.executable, "-m", "evaluation.dev", "check", "--corpus", str(CORPUS)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_all_variants_generate_and_anchor_once():
    cases = gen.generate_cases([1], all_variants=True)
    for c in cases:
        toks = tokens(c.text)
        for lab in c.labels:
            for a in lab["anchors"]:
                q = tokens(a["quote"])
                hits = sum(1 for i in range(len(toks) - len(q) + 1) if toks[i:i + len(q)] == q)
                assert hits == 1, (c.case_id, a["quote"])
                assert a["locator"].startswith("md:L")


def test_corpus_structure():
    m = manifest()
    fams = {c["family"] for c in m["cases"]} - {"edge"}
    assert len(fams) >= 4, "несколько независимых тем"
    by_kind = Counter(c["kind"] for c in m["cases"])
    assert by_kind["base"] == len(FAMILIES) and by_kind["combo"] == len(FAMILIES) and by_kind["edge"] == 1
    clean = [c for c in m["cases"] if c["expected_outcome"] == "clean"]
    assert any(c["kind"] == "base" for c in clean), "хотя бы один полностью чистый контроль"
    for fam in FAMILIES:
        ops = {op for c in m["cases"] if c["family"] == fam["family"] and c["kind"] == "mutant" for op in c["ops"]}
        assert ops == set(OPS)
    for c in m["cases"]:
        if c["kind"] in ("mutant", "combo"):
            mut = json.loads((CORPUS / "cases" / c["case_id"] / "mutation.json").read_text(encoding="utf-8"))
            assert mut["transformation"] and mut["expected_effect"] and mut["diff"].startswith("--- base/")
            assert mut["base_source_sha256"] == next(x for x in m["cases"] if x["case_id"] == c["base_case_id"])["renders"][0]["sha256"]


def test_labels_match_sources_and_protocol():
    m = manifest()
    md_sha = {c["case_id"]: next(r["sha256"] for r in c["renders"] if r["format"] == "md") for c in m["cases"]}
    for row in labels():
        assert row["source_sha256"] == md_sha[row["case_id"]]
        assert row["visibility"] == "public"
        for key in ("case_id", "family", "source_sha256", "issue_type", "anchors", "expected_outcome"):
            assert key in row
    for c in m["cases"]:
        src = (CORPUS / c["renders"][0]["path"]).read_bytes()
        assert hashlib.sha256(src).hexdigest() == c["renders"][0]["sha256"]
    present = Counter(r["issue_type"] for r in labels() if r["expected_outcome"] == "present")
    assert set(present) == {"event_conflict", "unit_mismatch", "boundary_conflict", "status_conflict", "missing_element"}


def test_physical_renders_share_case_id_and_contain_text():
    """PDF/DOCX — представления того же case_id; текст опор реально извлекается из файла."""
    from evaluation.dev.render import check_text, extract
    m = manifest()
    with_bin = [c for c in m["cases"] if len(c["renders"]) > 1]
    assert with_bin and all({r["format"] for r in c["renders"]} == {"md", "pdf", "docx"} for c in with_bin)
    by_case = {c["case_id"]: c for c in m["cases"]}
    lab_quotes: dict[str, list[str]] = {}
    for row in labels():
        lab_quotes.setdefault(row["case_id"], []).extend(a["quote"] for a in row["anchors"])
    for c in with_bin:
        assert len({r["render_id"] for r in c["renders"]}) == 3
        md_text = (CORPUS / c["renders"][0]["path"]).read_text(encoding="utf-8")
        for r in c["renders"][1:]:
            p = CORPUS / r["path"]
            assert hashlib.sha256(p.read_bytes()).hexdigest() == r["sha256"]
            fresh = check_text(extract(p, r["format"]), lab_quotes.get(c["case_id"], []), md_text)
            assert fresh["ok"], (c["case_id"], r["format"], fresh)
            assert fresh["tokens_present"] == fresh["anchors_total"]
    assert by_case["edge.empty"]["renders"][0]["bytes"] == 0


def test_dev_corpus_has_no_closed_material():
    assert manifest()["visibility"] == "public"
    assert all(r["visibility"] == "public" for r in labels())
    names = [p.name.lower() for p in (REPO / "evaluation" / "dev").rglob("*")]
    assert not any("closed" in n or "private" in n or "hidden" in n for n in names)


def test_leakcheck_detects_copied_closed_quote(tmp_path):
    from evaluation.harness.leakcheck import fingerprint, leakcheck
    closed = tmp_path / "closed.jsonl"
    closed.write_text(json.dumps({"case_id": "closed.x", "source_sha256": "0" * 64, "anchors": [
        {"quote": "Закрытая формулировка про овердрафт по кредитной линии и пени за просрочку платежа"}]},
        ensure_ascii=False) + "\n", encoding="utf-8")
    fp = fingerprint(str(closed))
    assert "овердрафт" not in json.dumps(fp, ensure_ascii=False)
    assert leakcheck(str(CORPUS), fp)["leak"] is False
    # закрытая цитата, совпадающая с текстом dev-набора, обнаруживается
    leaked = tmp_path / "leaked.jsonl"
    leaked.write_text(json.dumps({"case_id": "closed.y", "source_sha256": "1" * 64, "anchors": [
        {"quote": "Ставка кэшбэка составляет 5 % от суммы покупки."}]}, ensure_ascii=False) + "\n", encoding="utf-8")
    res = leakcheck(str(CORPUS), fingerprint(str(leaked)))
    assert res["leak"] is True and res["closed_quote_ngrams_in_dev_text"] >= 1


def _corpus_scores(pred_rows):
    from evaluation.harness.schema import Manifest, parse_gold, parse_predictions, read_jsonl
    from evaluation.harness.score import score
    from evaluation.harness.taxonomy import Taxonomy
    tax = Taxonomy.load()
    gold = parse_gold(read_jsonl(CORPUS / "labels.jsonl"), tax)
    preds, runs = parse_predictions(pred_rows, tax)
    return score(gold, preds, runs, tax, manifest=Manifest.load(CORPUS / "manifest.json"))


def test_oracle_predictor_scores_perfectly():
    """Эталон, поданный как предсказания, даёт P = R = 1 и ноль ложных тревог на всём dev-корпусе."""
    m = manifest()
    rows = [{"record": "run", "render_id": c["case_id"] + "@md", "status": "complete"} for c in m["cases"]]
    for lab in labels():
        if lab["expected_outcome"] == "present":
            rows.append({"record": "finding", "render_id": lab["case_id"] + "@md", "issue_type": lab["issue_type"],
                         "defect_id": lab["label_id"], "anchors": [{"quote": a["quote"]} for a in lab["anchors"]]})
    s = _corpus_scores(rows)
    present = sum(1 for l in labels() if l["expected_outcome"] == "present")
    assert (s["micro"]["tp"], s["micro"]["fp"], s["micro"]["fn"]) == (present, 0, 0)
    assert s["micro"]["precision"] == 1.0 and s["micro"]["recall"] == 1.0
    assert s["clean_controls"]["false_alarms"] == 0 and s["counts"]["independent_cases"] == len(m["cases"])


def test_null_predictor_on_corpus():
    m = manifest()
    s = _corpus_scores([{"record": "run", "render_id": c["case_id"] + "@md", "status": "complete"} for c in m["cases"]])
    assert s["micro"]["precision"] is None and s["micro"]["recall"] == 0.0
    assert s["clean_controls"]["cases"] == sum(1 for c in m["cases"] if c["expected_outcome"] == "clean")


def test_one_sided_quote_of_conflict_never_covers_both_anchors():
    """Для каждого конфликта цитата одной стороны не должна закрывать обе опоры (иначе TP без второй опоры)."""
    from evaluation.harness.normalize import coverage
    for lab in labels():
        anchors = [a for a in lab["anchors"] if a["role"] in ("a", "b")]
        if len(anchors) == 2:
            a, b = anchors
            assert not coverage(b["quote"], a["quote"]).covered, lab["label_id"]
            assert not coverage(a["quote"], b["quote"]).covered, lab["label_id"]
