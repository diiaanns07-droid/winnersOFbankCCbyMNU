"""№22 — ядро v2.1: сбой этапа без ложного вердикта, --replay, --runs N, --max-cost, --interactive."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2 import pipeline

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"


def _run(tmp_path, name="r", **opts):
    out = tmp_path / "out" / f"{name}.md"
    o = {"provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False, **opts}
    report, written = pipeline.review(OFFICIAL, out, o)
    return report, written, out


def _verify(written) -> int:
    from bcc_review.v2 import verify
    return verify.main([written["json"], str(OFFICIAL)])


# --------------------------------------------------------------------------- 5. сбой этапа → «не определено»

def test_verdict_rule_incomplete_keeps_no_and_hides_yes():
    crit = {"severity": "critical", "blocks": "development"}
    assert pipeline.verdict_rule([crit], "partial", ["judge"]) == {"development": "no", "testing": "undetermined"}
    assert pipeline.verdict_rule([], "partial", ["lens_risk"]) == {"development": "undetermined",
                                                                  "testing": "undetermined"}
    majors = [{"severity": "major", "blocks": "both"}] * 3
    assert pipeline.verdict_rule(majors, "partial", ["consistency"])["testing"] == "undetermined"
    assert pipeline.verdict_rule([], "partial") == {"development": "conditional", "testing": "conditional"}


def _no_blockers(monkeypatch):
    """Судья без блокеров: иначе вердикт «нельзя» и проверка «не определено» ничего не покажет."""
    from bcc_review.v2.stages import judge
    real = judge.run

    def soft(ctx, cands):
        out = real(ctx, cands)
        for f in out.get("findings") or []:
            f["severity"], f["blocks"] = "minor", "none"
        return out
    monkeypatch.setattr(judge, "run", soft)


def test_failed_lens_gives_undetermined_not_yes(tmp_path, monkeypatch):
    from bcc_review.v2.stages import lens
    _no_blockers(monkeypatch)
    real = lens.run_named

    def boom(ctx, name):
        if name == "risk":
            raise RuntimeError("линза упала")
        return real(ctx, name)
    monkeypatch.setattr(lens, "run_named", boom)
    report, written, _ = _run(tmp_path)
    assert report["run"]["stages"]["lens_risk"] == "failed"
    assert report["run"]["incomplete_stages"] == ["lens_risk"]
    assert report["verdict"]["development"] == "undetermined"
    assert report["verdict"]["testing"] == "undetermined"
    assert any("«Риски»" in w for w in report["run"]["warnings"])
    md = Path(written["md"]).read_text(encoding="utf-8")
    assert "не определено" in md
    assert _verify(written) == 0


def test_failed_judge_gives_undetermined(tmp_path, monkeypatch):
    from bcc_review.v2.stages import judge

    def boom(ctx, cands):
        raise RuntimeError("судья упал")
    monkeypatch.setattr(judge, "run", boom)
    report, written, _ = _run(tmp_path)
    assert report["run"]["stages"]["judge"] == "failed"
    for k in ("development", "testing"):
        assert report["verdict"][k] in ("no", "undetermined")
    assert _verify(written) == 0


def test_complete_run_has_no_incomplete_marker(tmp_path):
    report, _, _ = _run(tmp_path)
    assert "incomplete_stages" not in report["run"]
