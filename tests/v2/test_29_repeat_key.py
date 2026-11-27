"""№29 — страховка линзы «Риски»: обещание «повтор события не меняет итог» без признака повтора.

Если модель не написала замечание о повторах, а документ обещает устойчивость к повторной доставке и не называет,
по какому признаку повтор узнаётся, — код добавляет major с цитатой строки обещания. На документах, где признак
назван или о повторах не сказано ничего, страховка молчит (чистые open2, №20 и корпус).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview, quotes
from bcc_review.v2.stages import lens_risk as R

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
CLEAN = sorted(glob.glob(str(ROOT / "evaluation/v2/open2/*_clean/source.md"))) + \
    sorted(glob.glob(str(ROOT / "evaluation/v2/clean/*/source.md"))) + \
    sorted(glob.glob(str(ROOT / "evaluation/dev/corpus/cases/*/source.md")))


class _Ctx:
    def __init__(self, view: dict, candidates: list[dict], requirements: list | None = None):
        self.view, self.requirements, self.signals = view, requirements or [], []
        self._c = candidates

    def prompt(self, stage):
        return "s", "u"

    def warn(self, msg):
        pass


def _run(view: dict, candidates: list[dict], requirements: list | None = None) -> dict:
    import bcc_review.v2.stages.lens as lens
    ctx = _Ctx(view, candidates, requirements)
    orig = lens.run
    lens.run = lambda c, name: {"candidates": [dict(x) for x in c._c]}
    try:
        return R.run(ctx)
    finally:
        lens.run = orig


def _cand(title: str, quote: str, line: int, severity: str = "major", kind: str = "ops_risk") -> dict:
    return {"title": title, "kind": kind, "criterion": "risk", "severity": severity, "requirement_ids": [],
            "evidence": [{"quote": quote, "line": line}], "problem": "п", "scenario": "с", "impact": "и",
            "recommendation": "р", "rewrite": "", "question": "", "blocks": "development"}


def test_official_promise_without_key_adds_major_with_verified_quote():
    view = docview.load(OFFICIAL)
    out = _run(view, [])
    extra = [c for c in out["candidates"] if c.get("origin") == "doc_text"]
    assert len(extra) == 1
    c = extra[0]
    assert c["severity"] == "major" and c["kind"] == "ops_risk" and c["blocks"] == "both"
    ev = dict(c["evidence"][0])
    quotes.verify_evidence(view, ev, [])
    assert ev["verified"] in ("exact", "normalized")
    assert "Повторная доставка" in ev["quote"] and "дочерний документ" not in ev["quote"]  # только своё предложение
    for k in ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question"):
        assert c[k].strip()


def test_official_model_wrote_repeat_no_duplicate():
    view = docview.load(OFFICIAL)
    line = next(x for x in view["lines"] if "Повторная доставка" in x["text"])
    model = [_cand("Повтор события процессинга не распознаётся по ключу", line["text"][-80:], line["n"])]
    out = _run(view, model)
    assert not [c for c in out["candidates"] if c.get("origin") == "doc_text"]
    assert len(out["candidates"]) == 1


def test_fallback_survives_limit_of_twelve():
    view = docview.load(OFFICIAL)
    text = next(x for x in view["lines"] if x["n"] == 104)["text"]
    model = [_cand(f"Сумма в строке запроса GET, случай {i}", text, 104, kind="security") for i in range(12)]
    out = _run(view, model)
    assert len(out["candidates"]) == 12
    assert [c for c in out["candidates"] if c.get("origin") == "doc_text"]


def test_requirement_ids_from_segmentation():
    view = docview.load(OFFICIAL)
    n = next(x for x in view["lines"] if "Повторная доставка" in x["text"])["n"]
    reqs = [{"id": "R-07", "line_start": n, "line_end": n}, {"id": "R-01", "line_start": 37, "line_end": 37}]
    out = _run(view, [], reqs)
    extra = [c for c in out["candidates"] if c.get("origin") == "doc_text"]
    assert extra and extra[0]["requirement_ids"] == ["R-07"]


@pytest.mark.parametrize("path", CLEAN, ids=lambda p: Path(p).parent.name)
def test_no_fallback_on_clean_and_corpus(path):
    out = _run(docview.load(path), [])
    assert not [c for c in out["candidates"] if c.get("origin") == "doc_text"]


def test_key_named_in_other_line_closes_question():
    view = {"lines": [
        {"n": 1, "text": "Повторная доставка события сохраняет исходный итог.", "section": "Интеграция"},
        {"n": 2, "text": "Дубль узнаётся по идентификатору события eventId.", "section": "Интеграция"},
    ]}
    assert R.repeat_promise_line(view) is None
    view["lines"][1]["text"] = "Событие содержит сумму и дату."
    assert R.repeat_promise_line(view)["n"] == 1


def test_mock_official_answer_unchanged():
    """Mock-ответ линзы по официальному ТЗ уже содержит замечание о повторах — страховка его не дублирует."""
    raw = json.loads((ROOT / "tests" / "v2" / "fixtures" / "official" / "lens_risk.json").read_text("utf-8"))
    data = raw[0] if isinstance(raw, list) else raw
    out = _run(docview.load(OFFICIAL), data.get("candidates") or [])
    assert not [c for c in out["candidates"] if c.get("origin") == "doc_text"]
    assert any(R.REPEAT_TOPIC_RE.search(c["title"]) for c in out["candidates"])
