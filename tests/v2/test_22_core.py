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


# --------------------------------------------------------------------------- 1. --replay

def _strip(report: dict) -> dict:
    keep = ("findings", "rejected", "questions", "requirements", "checklist")
    return {k: report.get(k) for k in keep} | {"verdict": {k: report["verdict"].get(k)
                                                           for k in ("development", "testing")}}


def test_replay_rebuilds_same_report_without_calls(tmp_path):
    report, written, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    rep2, w2, _ = _run(tmp_path, name="replay", provider="gemini", replay=str(src))  # провайдер не нужен
    assert rep2["run"]["calls"]["total"] == 0
    assert rep2["run"]["replay"]["run_id"] == report["run"]["run_id"]
    assert rep2["run"]["replay"]["calls_live"] == 0
    assert rep2["run"]["provider"] == report["run"]["provider"]
    assert rep2["run"]["models_used"] == report["run"]["models_used"]
    assert _strip(rep2) == _strip(report)
    assert rep2["run"]["status"] == report["run"]["status"]
    assert _verify(w2) == 0
    # повтор повтора: ответы этапов скопированы в новый прогон
    rep3, _, _ = _run(tmp_path, name="replay2", replay=str(tmp_path / "runs" / rep2["run"]["run_id"]))
    assert _strip(rep3) == _strip(report)


def test_replay_missing_response_fails_stage_honestly(tmp_path):
    report, _, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    (src / "stages" / "lens_risk.json").unlink()
    for p in (src / "responses").glob("lens_risk*.json"):
        p.unlink()
    rep2, _, _ = _run(tmp_path, name="replay", replay=str(src))
    assert rep2["run"]["stages"]["lens_risk"] == "failed"
    assert rep2["run"]["calls"]["total"] >= 0 and rep2["run"]["replay"]["calls_live"] == 0
    assert "lens_risk" in rep2["run"]["incomplete_stages"]
    assert "yes" not in (rep2["verdict"]["development"], rep2["verdict"]["testing"])


def test_replay_cli_requires_stage_dir(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    code = main([str(OFFICIAL), str(tmp_path / "r.md"), "--replay", str(tmp_path / "nope")])
    assert code == 2
    assert "Нет сохранённых этапов" in capsys.readouterr().err


def test_replay_cli_end_to_end(tmp_path):
    from bcc_review.v2.__main__ import main
    report, _, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    code = main([str(OFFICIAL), str(tmp_path / "r.md"), "--replay", str(src), "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")])
    assert code == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["run"]["replay"]["run_id"] == report["run"]["run_id"]


# --------------------------------------------------------------------------- 2. --runs N

def test_runs_three_mock_all_stable(tmp_path):
    report, written, _ = _run(tmp_path, runs=3)
    st = report["stability"]
    assert st["runs_counted"] == 3 and st["threshold"] == 2
    assert report["findings"] and all(f["stability"]["k"] == 3 for f in report["findings"])
    assert report["findings_unstable"] == []
    assert st["calls_total"] > report["stability"]["passes"][0]["calls"]
    assert _verify(written) == 0
    md = Path(written["md"]).read_text(encoding="utf-8")
    assert "Устойчивость: независимые проходы" in md and "3 из 3" in md


def test_runs_unstable_goes_to_appendix(tmp_path, monkeypatch):
    """Проход 2 и 3 не находят часть дефектов первого и находят один свой — он идёт в реестр, если в 2 из 3."""
    from bcc_review.v2.stages import judge
    real = judge.run
    calls = {"n": 0}

    def flaky(ctx, cands):
        calls["n"] += 1
        out = real(ctx, cands)
        fs = out.get("findings") or []
        if calls["n"] > 1 and fs:
            out["findings"] = fs[1:]  # первый дефект первого прохода больше не находится
        return out
    monkeypatch.setattr(judge, "run", flaky)
    report, written, _ = _run(tmp_path, runs=3)
    unstable = report["findings_unstable"]
    assert len(unstable) == 1 and unstable[0]["stability"] == {"k": 1, "n": 3, "passes": [1]}
    gone = unstable[0]["id"]
    assert gone not in [f["id"] for f in report["findings"]]
    for q in report.get("questions") or []:
        assert gone not in q.get("finding_ids", [])
    assert gone not in report["verdict"].get("fix_first", [])
    assert _verify(written) == 0
    assert "Неустойчивые замечания" in Path(written["md"]).read_text(encoding="utf-8")


def test_stability_group_matches_by_lines_and_kind():
    from bcc_review.v2 import stability
    a = {"id": "D-01", "kind": "ambiguity", "evidence": [{"line_start": 10, "line_end": 10}], "title": "x"}
    b = {"id": "D-07", "kind": "ambiguity", "evidence": [{"line_start": 10, "line_end": 11}], "title": "y"}
    c = {"id": "D-02", "kind": "missing", "evidence": [{"line_start": 50}], "title": "z"}
    cl = stability.group([[a, c], [b], [dict(c)]])
    assert [sorted(x["hits"]) for x in cl] == [[0, 1], [0, 2]]
    assert stability.similarity(a, c) == 0


def test_failed_pass_not_counted():
    from bcc_review.v2 import stability
    f = {"id": "D-01", "kind": "k", "evidence": [{"line_start": 3}], "title": "t"}
    base = {"run": {"status": "complete"}, "findings": [f], "requirements": [], "verdict": {}}
    bad = {"run": {"status": "failed"}, "findings": []}
    rep = stability.merge(base, [bad, {"run": {"status": "complete"}, "findings": [dict(f)]}], 3)
    assert rep["stability"]["runs_counted"] == 2
    assert rep["findings"][0]["stability"]["k"] == 2
    assert any("не удались" in w for w in rep["run"]["warnings"])


def test_runs_cli_rejects_with_answers(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    ans = tmp_path / "a.md"
    ans.write_text("Q-01: A\n", encoding="utf-8")
    assert main([str(OFFICIAL), str(tmp_path / "r.md"), "--runs", "2", "--answers", str(ans)]) == 2
