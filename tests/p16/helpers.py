"""Общие помощники тестов p16: сборка эталона и предсказаний в памяти."""
from __future__ import annotations

import hashlib

from evaluation.harness.schema import parse_gold, parse_predictions
from evaluation.harness.score import score
from evaluation.harness.taxonomy import Taxonomy

TAX = Taxonomy.load()


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def gold_row(case: str, issue_type, anchors, outcome="present", family="t", policy="all", label_id=None, src=None):
    r = {"case_id": case, "family": family, "source_sha256": src or sha(case), "issue_type": issue_type,
         "anchors": [{"role": role, "quote": q} for role, q in anchors], "expected_outcome": outcome,
         "anchor_policy": policy}
    if label_id:
        r["label_id"] = label_id
    return r


def pred_row(case: str, issue_type, quotes, defect_id=None, mode=None, fmt=None, src=None, **kw):
    r = {"record": "finding", "source_sha256": src or sha(case), "issue_type": issue_type,
         "anchors": [{"quote": q} for q in quotes], "defect_id": defect_id}
    if mode:
        r["mode"] = mode
    if fmt:
        r["format"] = fmt
    r.update(kw)
    return r


def run_row(case: str, mode=None, status="complete", fmt=None, src=None, **kw):
    r = {"record": "run", "source_sha256": src or sha(case), "status": status}
    if mode:
        r["mode"] = mode
    if fmt:
        r["format"] = fmt
    r.update(kw)
    return r


def do_score(gold, preds, **kw):
    g = parse_gold([dict(x, _line=i + 1) for i, x in enumerate(gold)], TAX)
    p, runs = parse_predictions([dict(x, _line=i + 1) for i, x in enumerate(preds)], TAX)
    return score(g, p, runs, TAX, **kw)
