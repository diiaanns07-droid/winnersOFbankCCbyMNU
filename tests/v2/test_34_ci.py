"""Ревью ТЗ в CI: SARIF 2.1.0, GitLab Code Quality, команды GitHub Actions, сводка для PR.

Отчёт строится офлайн-провайдером по документу кейса — без модели и сети, как в workflow без ключа.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bcc_review.v2.render import ci
from bcc_review.v2.render import exports as E

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MD = ROOT / "release/input/requirements.md"


@pytest.fixture(scope="module")
def offline_report(tmp_path_factory) -> tuple[dict, Path]:
    out = tmp_path_factory.mktemp("ci") / "requirements.md"
    proc = subprocess.run([sys.executable, "-m", "bcc_review", str(OFFICIAL_MD), str(out), "--provider", "offline",
                           "--export", "sarif,gitlab", "-q", "--runs-dir", str(out.parent / "runs")],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8")), out


def test_export_writes_sarif_and_gitlab_next_to_report(offline_report):
    report, out = offline_report
    sarif = json.loads(out.with_name("requirements.sarif").read_text(encoding="utf-8"))
    gl = json.loads(out.with_name("requirements.codequality.json").read_text(encoding="utf-8"))
    n = sum(1 for f in report["findings"] if ci._evidence(f))
    assert n > 0
    assert len(sarif["runs"][0]["results"]) == n == len(gl)


def test_sarif_shape_and_locations_point_at_quotes(offline_report):
    report, _ = offline_report
    data = ci._clean(ci.build_sarif(report, OFFICIAL_MD, root=ROOT))
    assert data["version"] == "2.1.0"
    run = data["runs"][0]
    rules = {r["id"]: r for r in run["tool"]["driver"]["rules"]}
    lines = OFFICIAL_MD.read_text(encoding="utf-8").splitlines()
    for res in run["results"]:
        assert res["ruleId"] in rules and run["tool"]["driver"]["rules"][res["ruleIndex"]]["id"] == res["ruleId"]
        assert res["level"] in ("error", "warning", "note")
        phys = res["locations"][0]["physicalLocation"]
        assert phys["artifactLocation"]["uri"] == "release/input/requirements.md"
        reg = phys["region"]
        assert 1 <= reg["startLine"] <= len(lines)
        if "startColumn" in reg:  # колонки — ровно цитата в строке файла
            quote = lines[reg["startLine"] - 1][reg["startColumn"] - 1:reg["endColumn"] - 1]
            assert quote and quote in res["locations"][0]["message"]["text"]
        assert res["partialFingerprints"]["bccFinding/v1"]
    assert run["artifacts"][0]["hashes"]["sha-256"] == report["document"]["sha256"]
    assert run["properties"]["verdict"]["development"] == report["verdict"]["development"]


def test_critical_is_error_and_fingerprint_is_stable(offline_report):
    report, _ = offline_report
    a = ci.build_sarif(report, OFFICIAL_MD, root=ROOT)["runs"][0]["results"]
    b = ci.build_sarif(json.loads(json.dumps(report)), OFFICIAL_MD, root=ROOT)["runs"][0]["results"]
    assert [r["partialFingerprints"] for r in a] == [r["partialFingerprints"] for r in b]
    sev = {r["properties"]["bccId"]: r["level"] for r in a}
    for f in report["findings"]:
        if f["id"] in sev:
            assert sev[f["id"]] == ci.LEVEL[f["severity"]]


def test_github_commands_escape_and_keep_order(offline_report):
    report, _ = offline_report
    cmds = ci.github_commands(report, OFFICIAL_MD, root=ROOT)
    assert cmds and all(c.startswith(("::error ", "::warning ", "::notice ")) for c in cmds)
    for c in cmds:
        props, _, body = c[2:].partition("::")
        assert "\n" not in c and "file=release/input/requirements.md,line=" in props
        assert ":" not in props.split("title=", 1)[1]  # двоеточие в заголовке экранировано
        assert body
    first = E.findings_of(report)[0]["id"]
    assert f"title={first} " in cmds[0]


def test_summary_and_cli(offline_report):
    report, out = offline_report
    md = ci.step_summary(report, OFFICIAL_MD, root=ROOT)
    assert "Разработка: нельзя" in md and "| ID | Серьёзность | Где | Что не так |" in md
    proc = subprocess.run([sys.executable, "-m", "bcc_review.v2.render.ci", str(out.with_suffix(".json")),
                           str(OFFICIAL_MD), "--format", "github"], cwd=ROOT, capture_output=True, timeout=60)
    assert proc.returncode == 0 and proc.stdout.decode("utf-8").startswith("::")


def test_missing_quotes_and_lines_are_not_annotated():
    report = {"document": {"title": "т", "format": "md"}, "verdict": {}, "run": {},
              "findings": [{"id": "D-01", "severity": "major", "criterion": "complete", "title": "нет места",
                            "evidence": [{"quote": "x", "line_start": None, "verified": "exact"}]},
                           {"id": "D-02", "severity": "minor", "criterion": "language", "title": "не найдена",
                            "evidence": [{"quote": "y", "line_start": 3, "verified": "missing"}]}]}
    assert ci.build_sarif(report, OFFICIAL_MD, root=ROOT)["runs"][0]["results"] == []
    assert ci.build_gitlab(report, OFFICIAL_MD, root=ROOT) == []
    assert ci.github_commands(report, OFFICIAL_MD, root=ROOT) == []


def test_unknown_format_message_lists_ci_formats(tmp_path):
    res = E.export({"findings": []}, {}, OFFICIAL_MD, tmp_path / "r", ["xml"])
    assert res[0]["status"] == "skipped" and "sarif" in res[0]["message"]
