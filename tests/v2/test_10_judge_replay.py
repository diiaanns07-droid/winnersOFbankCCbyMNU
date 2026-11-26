"""Повтор живого ответа судьи (sonnet) на реальных кандидатах линз — без сети.

Фикстуры `tests/v2/fixtures/10_judge/`: кандидаты линз (аналитик sonnet и haiku, набор, риски) с уже сверенными
цитатами и сохранённый ответ модели-судьи. Тест проверяет сборку реестра кодом на реальных данных.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, simple_view  # noqa: E402

FX = ROOT / "tests" / "v2" / "fixtures" / "10_judge"


def replay(case: str, doc: Path, segment: Path):
    cands = json.loads((FX / f"{case}.candidates.json").read_text(encoding="utf-8"))["candidates"]
    resp = json.loads((FX / f"{case}.judge_sonnet.json").read_text(encoding="utf-8"))
    reqs = json.loads(segment.read_text(encoding="utf-8"))["requirements"]
    for i, r in enumerate(reqs, 1):
        r.setdefault("id", f"R-{i:02d}")
    llm = FakeLLM(resp)
    res = judge.run(Ctx(llm, view=simple_view(doc), requirements=reqs), cands)
    return cands, res, llm


def lines(f):
    return {e["line_start"] for e in f["evidence"]}


def test_official_replay():
    cands, res, llm = replay("official", ROOT / "release/input/requirements.md",
                             ROOT / "tests/v2/fixtures/official/segment.json")
    assert len(llm.calls) == 1
    all_placed(res, [c["id"] for c in cands])
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    assert 3 <= len(crit) <= 7
    # К1 (38↔64), К2 (39↔40), К4 (29/52/103), К3 (121/163/171) — critical
    for need in ({38, 64}, {39, 40}, {52, 103}, {121, 163}):
        assert any(need <= lines(f) for f in crit), need
    assert 15 <= len(res["findings"]) <= 45
    assert res["checklist_source"] == "document" and len(res["checklist"]) == 14
    v = judge.compute_verdict(res["findings"])
    assert v["development"] == "no" and v["testing"] == "no"
    assert all(f["priority"] == 0 for f in res["findings"] if f["severity"] == "minor")
    for f in res["findings"]:
        assert 1 <= len(f["evidence"]) <= 5 and f["standard_refs"] and f["sources"]
        assert all(e["verified"] != "missing" for e in f["evidence"])


def test_clean_base_replay():
    base = ROOT / "evaluation/dev/corpus/cases/autopay.base/source.md"
    cands, res, _ = replay("autopay.base", base, ROOT / "tests/v2/fixtures/autopay.base/segment.json")
    all_placed(res, [c["id"] for c in cands])
    assert not [f for f in res["findings"] if f["severity"] == "critical"]
    v = judge.compute_verdict(res["findings"])
    assert v["development"] != "no" and v["testing"] != "no"
    assert res["checklist_source"] == "bank" and len(res["checklist"]) == 14
