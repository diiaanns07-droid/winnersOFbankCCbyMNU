"""Тесты линзы «Аналитик» (№05): промпт и постобработка. Без сети."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "lens_analyst.md"
STAGE = ROOT / "src" / "bcc_review" / "v2" / "stages" / "lens_analyst.py"

# Слова официального документа: промпт не должен под него подгоняться.
FORBIDDEN = ["push", "savelimit", "тиын", "порог", "алмат", "alertscontroller", "держател",
             "уведомлен", "расход", "48 500", "50 000", "31 января", "лимит"]


def _load_stage():
    spec = importlib.util.spec_from_file_location("lens_analyst_05", STAGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cand(title, severity="major", kind="ambiguity", lines=(10,), scenario="s", impact="i", blocks="both"):
    return {"title": title, "kind": kind, "criterion": "unambiguous", "severity": severity,
            "requirement_ids": ["R-01"], "evidence": [{"quote": f"цитата {n}", "line": n} for n in lines],
            "problem": "p", "scenario": scenario, "impact": impact, "recommendation": "r", "rewrite": "",
            "question": "", "blocks": blocks}


def test_prompt_exists_and_has_no_official_words():
    text = PROMPT.read_text(encoding="utf-8")
    assert len(text) > 1000
    low = text.lower()
    hits = [w for w in FORBIDDEN if w in low]
    assert not hits, f"слова официального документа в промпте: {hits}"
    assert not re.search(r"\bФ-\d", text)


def test_prompt_covers_all_lens_checks():
    text = PROMPT.read_text(encoding="utf-8")
    for code in ("unambiguous", "complete", "singular", "appropriate", "language"):
        assert f"criterion: {code}" in text, code
    assert "12" in text and "<сигналы>" in text
    assert "29148" in text


def test_prompt_has_no_english_user_text_instructions():
    # служебные коды схемы — латиница; сам текст задания — по-русски
    text = PROMPT.read_text(encoding="utf-8")
    words = re.findall(r"[A-Za-z]{4,}", re.sub(r"`[^`]*`", "", text))
    allowed = {"ISO", "IEEE", "JSON", "critical", "major", "minor"}
    assert not [w for w in words if w not in allowed]


def test_postprocess_drops_no_evidence_and_duplicates():
    pp = _load_stage().postprocess
    a = _cand("A", lines=(38,))
    dup = _cand("A второй раз", lines=(38,))
    empty = dict(_cand("B"), evidence=[])
    blank = dict(_cand("C"), evidence=[{"quote": "  ", "line": 5}])
    out = pp([a, dup, empty, blank])
    assert [c["title"] for c in out] == ["A"]


def test_postprocess_caps_critical_and_count():
    pp = _load_stage().postprocess
    cands = [_cand(f"K{i}", severity="critical", lines=(i,)) for i in range(1, 5)]
    cands += [_cand(f"M{i}", severity="minor", lines=(100 + i,)) for i in range(12)]
    out = pp(cands)
    assert len(out) == 12
    assert [c["severity"] for c in out[:4]] == ["critical", "critical", "major", "major"]
    assert out[0]["title"] == "K1" and out[1]["title"] == "K2"


def test_postprocess_demotes_weak_critical_and_non_singular():
    pp = _load_stage().postprocess
    weak = _cand("нет сценария", severity="critical", scenario="", lines=(1,))
    noblock = _cand("blocks none", severity="critical", blocks="none", lines=(2,))
    ns = _cand("четыре правила в одном", severity="major", kind="non_singular", lines=(3,))
    out = {c["title"]: c["severity"] for c in pp([weak, noblock, ns])}
    assert out == {"нет сценария": "major", "blocks none": "major", "четыре правила в одном": "minor"}


def test_postprocess_sorts_by_severity_keeps_model_order():
    pp = _load_stage().postprocess
    out = pp([_cand("m1", "minor", lines=(1,)), _cand("M1", "major", lines=(2,)),
              _cand("K1", "critical", lines=(3,)), _cand("M2", "major", lines=(4,))])
    assert [c["title"] for c in out] == ["K1", "M1", "M2", "m1"]


def test_postprocess_does_not_mutate_input():
    pp = _load_stage().postprocess
    c = _cand("x", severity="critical", scenario="")
    pp([c])
    assert c["severity"] == "critical"


def test_run_wraps_lens_run():
    mod = _load_stage()
    calls = []

    def fake_lens(ctx, name):
        calls.append(name)
        return {"candidates": [_cand("a", lines=(1,)), _cand("a", lines=(1,))], "extra": 1}

    out = mod.run(object(), lens_run=fake_lens)
    assert calls == ["analyst"] and len(out["candidates"]) == 1 and out["extra"] == 1


@pytest.mark.parametrize("bad", [None, [], [None, "x", 3]])
def test_postprocess_tolerates_garbage(bad):
    assert _load_stage().postprocess(bad) == []
