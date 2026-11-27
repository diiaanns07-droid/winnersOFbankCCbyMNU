"""Тесты №12: офлайн-режим (без модели) — вердикт, отчёт, запасной рендер."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.rules import offline  # noqa: E402
from bcc_review.v2.rules._view import fallback_load  # noqa: E402

OFFICIAL = ROOT / "release" / "input" / "requirements.md"
CLEAN = ROOT / "evaluation" / "dev" / "corpus" / "cases" / "cashback.base" / "source.md"


def test_official_offline_report():
    r = offline.build(fallback_load(OFFICIAL))
    assert r["run"]["provider"] == "offline" and r["run"]["calls"]["total"] == 0
    assert r["verdict"]["development"] in ("no", "undetermined")
    assert r["verdict"]["development"] == "no"          # есть конфликт двух цитат об одном предмете
    assert "yes" not in (r["verdict"]["development"], r["verdict"]["testing"])
    assert r["findings"] and all(f["evidence"] for f in r["findings"])
    assert all(e["verified"] in ("exact", "normalized", "fuzzy") for f in r["findings"] for e in f["evidence"])
    assert all(f["standard_refs"] for f in r["findings"])
    assert [f["id"] for f in r["findings"]][:2] == ["D-01", "D-02"]
    assert r["summary"]["findings"]["critical"] + r["summary"]["findings"]["major"] >= 5


def test_clean_offline_is_undetermined():
    r = offline.build(fallback_load(CLEAN))
    assert r["findings"] == []
    assert r["verdict"]["development"] == "undetermined" and r["verdict"]["testing"] == "undetermined"
    md = offline.render_fallback(r)
    assert offline.TITLE in md and "не определено" in md
    assert "можно" not in md.lower().replace("можно начинать", "")
    assert "отсутствие других замечаний не означает, что их нет" in md


def test_verdict_rule():
    one = {"id": "D-01", "rule_conflict": True, "blocks": "development", "evidence": [{}, {}]}
    weak = {"id": "D-02", "rule_conflict": True, "blocks": "both", "evidence": [{}]}
    plain = {"id": "D-03", "rule_conflict": False, "blocks": "both", "evidence": [{}, {}]}
    assert offline.verdict([one])["development"] == "no"
    assert offline.verdict([one])["testing"] == "undetermined"
    assert offline.verdict([weak, plain])["development"] == "undetermined"
    crit = {"id": "D-04", "severity": "critical", "blocks": "development", "evidence": [{}]}
    assert offline.verdict([crit])["development"] == "no"


def test_verdict_matches_report_rule():
    """Офлайн-вердикт №12 совпадает с правилом кода №13 — иначе verify отклонит отчёт."""
    try:
        from bcc_review.v2.render import jsonout
    except Exception:  # noqa: BLE001
        return
    for path in (OFFICIAL, CLEAN):
        r = offline.build(fallback_load(path))
        rule = jsonout.rule_verdict(r)
        assert {k: r["verdict"][k] for k in ("development", "testing")} == rule


def test_fallback_render_short(tmp_path):
    r = offline.build(fallback_load(OFFICIAL))
    md = offline.render_fallback(r)
    lines = md.splitlines()
    assert len(lines) < 400
    for h in ("## Итог", "## Как получить полную проверку", "## Замечания без модели", "## Что без модели не проверялось"):
        assert h in md
    assert "нельзя" in md
    out = tmp_path / "r.md"
    assert offline.main([str(OFFICIAL), str(out), "--json", str(tmp_path / "r.json")]) == 0
    assert out.read_text(encoding="utf-8").startswith("# ")


def test_brief_report_for_jury():
    r = offline.build(fallback_load(OFFICIAL), reason="не задан GEMINI_API_KEY")
    md = offline.render_brief(r)
    lines = md.splitlines()
    assert len(lines) <= 200
    assert lines[0].startswith("# Предварительная проверка без модели")
    assert "не задан GEMINI_API_KEY" in md and "https://aistudio.google.com/apikey" in md
    assert "GEMINI_API_KEY=" in md and "## Как получить полную проверку" in md
    assert "Без модели найдено 15 замечаний" in md or "Без модели найдено" in md
    assert "можно начинать" not in md.replace("нельзя начинать", "")
    assert r["offline"]["how_to_full"] and r["offline"]["found"].startswith("Без модели найдено")
    clean = offline.render_brief(offline.build(fallback_load(CLEAN)))
    assert "❔ не определено" in clean and "замечаний не нашли" in clean and len(clean.splitlines()) <= 60
