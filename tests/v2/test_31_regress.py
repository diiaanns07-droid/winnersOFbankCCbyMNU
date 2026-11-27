"""№31: ворота регрессии на mock — официальный ТЗ в md/docx/pdf проходит весь конвейер, счётчик не проседает.

Пороги — по mock на `2eac95c` (md: К 5/5, С 16/20, 31 замечание, цитат 109/109; docx: К 5/5, С 15/20; pdf: заготовок
mock под PDF нет, поэтому проверяем только, что прогон доходит до отчёта без сбоя и цитаты сверены). Живой замер —
`python -m evaluation.v2.nightly`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.v2 import score as sc

ROOT = Path(__file__).resolve().parents[2]
FLOOR = {"md": {"K": 5, "C": 15}, "docx": {"K": 5, "C": 14}}


def _run(fmt: str, tmp: Path) -> dict:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    out = tmp / f"r_{fmt}.md"
    r = subprocess.run([sys.executable, "-m", "bcc_review", str(ROOT / "release" / "input" / f"requirements.{fmt}"),
                        str(out), "--provider", "mock"], cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=300)
    assert r.returncode in (0, 1, 2), r.stderr[-800:]  # 0 — можно, 1/2 — вердикт; 3+ — сбой
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("fmt", ["md", "docx"])
def test_mock_official_floor(fmt, tmp_path):
    if fmt == "docx":
        pytest.importorskip("docx")
    rep = _run(fmt, tmp_path)
    assert rep["run"]["status"] == "complete"
    s = sc.score_report(rep, sc.load_gold(sc.DEFAULT_GOLD), arbiter="off", cache_path=sc.DEFAULT_CACHE)
    rc = s["recall"]
    assert rc["critical"]["n"] >= FLOOR[fmt]["K"]
    assert rc["major"]["n"] >= FLOOR[fmt]["C"]
    assert s["quotes"]["missing"] == 0 and s["quotes"]["total"] > 50
    assert 20 <= s["counts"]["findings"] <= 45


def test_mock_pdf_reaches_report(tmp_path):
    pytest.importorskip("pymupdf")
    rep = _run("pdf", tmp_path)
    assert rep["run"]["status"] in ("complete", "partial")
    assert rep["findings"]
    ev = [e for f in rep["findings"] for e in f.get("evidence") or []]
    assert ev and all(e.get("verified") != "missing" for e in ev)


def test_nightly_dry_run_plan(capsys):
    from evaluation.v2 import nightly

    assert nightly.main(["--commit", "abc1234", "--dry-run"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert sum("evaluation.v2.measure" in x for x in out) == 18  # 3 формата × 2 модели × 3
    assert any("requirements.pdf" in x and "--no-cache" in x for x in out)
    assert any("--clean20 haiku" in x for x in out)
    assert nightly.main(["--commit", "x", "--models", "opus", "--dry-run"]) == 2
