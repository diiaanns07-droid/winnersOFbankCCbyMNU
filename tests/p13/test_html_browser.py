"""Браузерная проверка HTML-отчёта (№13) через Node Playwright.

Нужны ``node`` и пакет ``playwright`` (глобальный или локальный). Без них
тест пропускается с понятной причиной. Python-пакет playwright не требуется.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bcc_review.exports import html as H
from fixture_builder import VARIANTS

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "browser" / "check_report.cjs"


def _node_env() -> dict[str, str] | None:
    node = shutil.which("node")
    if not node:
        return None
    env = dict(os.environ)
    npm = shutil.which("npm")
    if npm and "NODE_PATH" not in env:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
        if root:
            env["NODE_PATH"] = root
    probe = subprocess.run([node, "-e", "require(process.env.PLAYWRIGHT_MODULE || 'playwright')"], env=env, capture_output=True, timeout=60)
    return env if probe.returncode == 0 else None


EXAMPLE = HERE.parents[1] / "contracts" / "examples" / "minimal_report.json"


def prepare(workdir: Path) -> dict[str, dict]:
    reports = {}
    builders = dict(VARIANTS)
    if EXAMPLE.is_file():  # эталон Max из контракта v1 — стыковая проверка
        builders["minimal"] = lambda: json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for name, build in builders.items():
        rep = build()
        (workdir / f"{name}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        H.write_html(rep, workdir / f"{name}.html")
        reports[name] = rep
    return reports


def run_checks(workdir: Path, shots: Path | None = None) -> subprocess.CompletedProcess:
    env = _node_env()
    if env is None:
        pytest.skip("нет node или пакета playwright для Node")
    args = ["node", str(SCRIPT), str(workdir)] + ([str(shots)] if shots else [])
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=600)


@pytest.fixture(scope="module")
def browser_run(tmp_path_factory):
    work = tmp_path_factory.mktemp("p13-browser")
    reports = prepare(work)
    proc = run_checks(work)
    results_file = work / "results.json"
    if not results_file.exists():
        pytest.fail(f"скрипт не записал results.json\n{proc.stdout}\n{proc.stderr}")
    return work, reports, json.loads(results_file.read_text(encoding="utf-8")), proc


def test_browser_checks_all_pass(browser_run):
    _, _, results, proc = browser_run
    failed = [r for r in results if not r["ok"]]
    assert len(results) >= 15, proc.stdout
    assert not failed, "\n\n".join(f"{r['name']}\n{r['details']}" for r in failed)


def test_exported_answers_match_python_format(browser_run):
    work, reports, _, _ = browser_run
    typed = json.loads((work / "answers-typed.json").read_text(encoding="utf-8"))
    exported = Path(typed.pop("file")).read_text(encoding="utf-8")
    parsed = H.parse_answers_markdown(exported)
    expected = H.answers_markdown(reports["synthetic"], typed, exported_at=parsed["meta"]["exported_at"])
    assert exported == expected
    assert parsed["meta"]["source_sha256"] == reports["synthetic"]["document"]["id"]
    assert parsed["answers"]["Q-01"] == H.answer_one_line(typed["Q-01"])
