"""№11: вопросы владельцу на реальных ответах модели по новым ТЗ №18 (сохранённые отчёты открытого набора).

Сохранённые вопросы прогоняются через текущую постобработку кода (как если бы модель вернула их сейчас):
проверяется, что код держит правила третьей волны на чужих документах — не больше 8 вопросов (5 без critical),
блокирующие только по critical, цитаты обеих сторон у конфликтов, 2–4 варианта, без внутренних кодов.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import pytest

from bcc_review.v2.stages import clarify

ROOT = Path(__file__).resolve().parents[2]
# BCC_OPEN2_RESULTS — дополнительные каталоги с results/<метка>/*.md.json (например, ветка №18 до слияния)
_DIRS = [ROOT / "evaluation" / "v2" / "open2" / "results"] + \
    [Path(p) for p in os.environ.get("BCC_OPEN2_RESULTS", "").split(os.pathsep) if p]
REPORTS = sorted({p for d in _DIRS for p in glob.glob(str(d / "*" / "*.md.json"))})
_CODE = re.compile(r"\b(?:[DRC]-\d{1,3}|L\d{2,4})\b|lens:")


def _view(report_path: str) -> dict:
    case = Path(report_path).name.split(".")[0]
    from bcc_review.v2 import docview
    return docview.load(str(ROOT / "evaluation" / "v2" / "open2" / case / "source.md"))


def _as_raw(q: dict) -> dict:
    return {**q, "evidence": [{"quote": e["quote"], "line": e.get("line_start") or 0} for e in q.get("evidence") or []]}


@pytest.mark.skipif(not REPORTS, reason="нет сохранённых отчётов открытого набора")
@pytest.mark.parametrize("path", REPORTS, ids=[Path(p).parent.name + "/" + Path(p).name for p in REPORTS])
def test_questions_on_new_documents(path):
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    findings = list(r.get("findings_before") or r.get("findings") or [])
    by_id = {f["id"]: f for f in findings}
    raw = {"questions": [_as_raw(q) for q in r.get("questions") or []]}
    view = _view(path)
    qs = clarify.postprocess(raw, findings, view)
    assert len(qs) <= clarify.question_cap(findings)
    has_serious = any(f["severity"] in ("critical", "major") for f in findings)
    for q in qs:
        linked = [by_id[i] for i in q["finding_ids"]]
        lines = {e.get("line_start") for e in q["evidence"]}
        # стороны конфликта — различные цитаты (противоречие бывает внутри одной строки)
        sides = clarify.count_sides(q["evidence"])
        assert lines, f"{q['id']}: нет цитаты"
        assert 2 <= len(q["options"]) <= 4, f"{q['id']}: вариантов {len(q['options'])}"
        if any(f.get("kind") in clarify.CONFLICT_KINDS for f in linked):
            assert sides >= 2, f"{q['id']}: у конфликта цитата одной стороны"
        assert not all(clarify.is_formatting(f) for f in linked), f"{q['id']}: вопрос об оформлении"
        assert not any("<уточнить" in o for o in q["options"]), f"{q['id']}: <уточнить> в варианте"
        assert q["blocking"] == any(f["severity"] == "critical" and f.get("blocks", "both") != "none" for f in linked)
        if has_serious:
            assert any(f["severity"] in ("critical", "major") for f in linked), f"{q['id']}: только minor"
        text = " ".join([q["question"], q["why"], *q["options"]])
        assert not _CODE.search(text), f"{q['id']}: внутренний код в тексте: {text[:200]}"
    # блокирующие — первыми
    flags = [q["blocking"] for q in qs]
    assert flags == sorted(flags, reverse=True)
