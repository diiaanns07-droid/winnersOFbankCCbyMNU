"""№15: счётчик эталона официального документа, адаптер корпуса и анти-подгонка (без сети)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

yaml = pytest.importorskip("yaml")

from evaluation.v2 import antifit, score  # noqa: E402
from evaluation.v2.common import load_doc, locate  # noqa: E402

GOLD = score.load_gold(score.DEFAULT_GOLD)
ITEMS = {it["id"]: it for it in GOLD["items"]}
DOC = ROOT / GOLD["document"]


def _finding(fid: str, item: dict, severity: str | None = None, kind: str | None = None) -> dict:
    ev = []
    for gr in item["anchors"]["groups"]:
        first = sorted(score.parse_lines(gr["lines"]))[0]
        ev.append({"quote": gr["quote"], "line_start": first, "line_end": first, "verified": "exact"})
    return {"id": fid, "title": item["title"], "kind": kind or item["kinds"][0], "criterion": "set_consistent",
            "severity": severity or item["level"], "problem": " ".join(str(item["essence"]).split()),
            "scenario": "", "impact": "", "recommendation": "", "rewrite": "", "question": "",
            "evidence": ev, "sources": ["lens:test"], "blocks": "both"}


def _report(findings: list[dict], verdict: dict | None = None) -> dict:
    return {"schema": "bcc-review/2", "run": {"status": "complete", "provider": "mock", "model_requested": "mock",
                                              "duration_s": 60, "calls": {"total": 8}},
            "document": {"file": "requirements.md", "format": "md", "sha256": GOLD["sha256"], "lines": 198},
            "findings": findings, "rejected": [], "questions": [],
            "verdict": verdict or {"development": "no", "testing": "no", "summary": "Разработку начинать нельзя."}}


def _score(rep: dict, **kw) -> dict:
    return score.score_report(rep, GOLD, arbiter="off", cache_path=Path("/nonexistent/arbiter.jsonl"), **kw)


def test_gold_is_complete_and_anchors_exist():
    ids = [it["id"] for it in GOLD["items"]]
    assert [i for i in ids if i.startswith("К")] == [f"К{i}" for i in range(1, 6)]
    assert [i for i in ids if i.startswith("С")] == [f"С{i}" for i in range(1, 21)]
    assert {it["parent"] for it in GOLD["items"] if it["level"] == "minor"} == {f"М{i}" for i in range(1, 9)}
    assert score.parse_lines("165-171,40") == {40, *range(165, 172)}
    lines = load_doc(DOC)
    assert len(lines) == 198
    for it in GOLD["items"]:
        assert it["owners"], it["id"]
        for gr in it["anchors"]["groups"]:
            want = score.parse_lines(gr["lines"])
            loc = locate(lines, gr["quote"], min(want))
            assert loc, (it["id"], gr["quote"])
            assert set(range(loc["line_start"], loc["line_end"] + 1)) & want, (it["id"], gr["lines"], loc)


def test_perfect_report_finds_all_key_items():
    fs = [_finding(f"D-{i:02d}", it) for i, it in enumerate(GOLD["items"], 1) if it["level"] != "minor"]
    res = _score(_report(fs))
    assert res["recall"]["critical"]["n"] == 5
    assert res["recall"]["major"]["n"] == 20
    assert res["counts"]["duplicates"] == 0
    assert res["quotes"]["missing"] == 0
    assert res["severity"]["accuracy_exact"] == 1.0
    gates = {g["metric"]: g["ok"] for g in res["gates"]}
    assert gates["К1–К5 найдены"] and gates["С1–С20 найдены"] and gates["критичных ложных"]


def test_duplicates_severity_and_outside():
    k1 = ITEMS["К1"]
    fs = [_finding("D-01", k1), _finding("D-02", k1, severity="major"),
          {"id": "D-03", "title": "Нет описания резервного копирования", "kind": "missing_element",
           "severity": "critical", "problem": "Нигде не сказано, как часто делать резервные копии.",
           "evidence": [{"quote": "Этой цитаты нет в документе", "line_start": 5, "line_end": 5,
                         "verified": "missing"}], "sources": ["lens:risk"]},
          _finding("D-04", ITEMS["С3"], severity="critical")]
    res = _score(_report(fs))
    assert res["recall"]["critical"]["found"] == ["К1"]
    assert [d["finding"] for d in res["duplicates"]] == ["D-02"]
    assert [o["finding"] for o in res["outside"]] == ["D-03"]
    assert res["quotes"]["missing"] == 1
    crit_false = {x["finding"] for x in res["severity"]["critical_false"]}
    assert crit_false == {"D-03", "D-04"}
    miss = {m["gold"]: m for m in res["misses"]}
    assert "К2" in miss and "consistency" in miss["К2"]["owners"]


def test_conflict_needs_both_sides():
    k2 = ITEMS["К2"]
    f = _finding("D-01", k2)
    f["evidence"] = f["evidence"][:1]  # только одна сторона противоречия
    res = _score(_report([f]))
    assert "К2" not in res["recall"]["critical"]["found"]
    assert "К2" in res["recall"]["critical"]["lenient"]  # спорная пара: без арбитра — только нестрого


def test_language_checks():
    f = _finding("D-01", ITEMS["С1"])
    f["recommendation"] = "Рекомендуется уточнить требования и повысить качество, use POST instead"
    res = _score(_report([f]))
    assert len(res["language"]["generic"]) >= 2
    assert {"use", "instead"} <= {e["word"] for e in res["language"]["english"]}


def test_v1_report_is_readable():
    rep = json.loads((ROOT / "release/reports/offline/requirements.json").read_text(encoding="utf-8"))
    res = _score(rep)
    assert res["report"]["version"] == "v1"
    assert res["counts"]["findings"] > 0
    assert res["verdict"]["got"] == {"development": "no", "testing": "no"}


def test_antifit_dictionary():
    bad = "Проверь порог push по Алматы, метод saveLimit, Ф-2 и тиыны."
    hits = {h["why"] for h in antifit.scan_text(bad)}
    assert len(hits) >= 5
    ok = "Проверь, что граница диапазона включена в обоих местах, а единицы измерения совпадают."
    assert antifit.scan_text(ok) == []


def test_prompts_have_no_official_document_words():
    paths = antifit.default_paths()
    if not paths:
        pytest.skip("промптов v2 ещё нет")
    res = antifit.scan(paths)
    assert res == {}, "\n".join(f"{f}:{h['line']}: «{h['match']}» — {h['why']}" for f, hs in res.items() for h in hs)
