"""№11: вопросы владельцу на сохранённых отчётах открытого набора №18 (новые ТЗ, реальные ответы модели)."""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from bcc_review.v2.stages import clarify

ROOT = Path(__file__).resolve().parents[2]
REPORTS = sorted(glob.glob(str(ROOT / "evaluation" / "v2" / "open2" / "results" / "*" / "*.md.json")))


@pytest.mark.skipif(not REPORTS, reason="нет сохранённых отчётов открытого набора")
@pytest.mark.parametrize("path", REPORTS, ids=[Path(p).parent.name + "/" + Path(p).name for p in REPORTS])
def test_questions_quote_both_sides_and_have_options(path):
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    findings = {f["id"]: f for f in (r.get("findings_before") or r.get("findings") or [])}
    qs = r.get("questions") or []
    assert len(qs) <= clarify.MAX_QUESTIONS
    for q in qs:
        lines = {e.get("line_start") for e in q.get("evidence") or []}
        assert lines, f"{q['id']}: нет цитаты"
        assert 2 <= len(q.get("options") or []) <= 4, f"{q['id']}: вариантов {len(q.get('options') or [])}"
        linked = [findings[i] for i in q.get("finding_ids") or [] if i in findings]
        assert linked, f"{q['id']}: нет связанных дефектов"
        if any(f.get("kind") in clarify.CONFLICT_KINDS for f in linked):
            assert len(lines) >= 2, f"{q['id']}: у конфликта цитата одной стороны"
        assert not all(clarify.is_formatting(f) for f in linked), f"{q['id']}: вопрос об оформлении"
        assert not any("<уточнить" in o for o in q["options"]), f"{q['id']}: <уточнить> в варианте"
