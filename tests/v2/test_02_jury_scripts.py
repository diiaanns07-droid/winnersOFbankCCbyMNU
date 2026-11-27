"""№02: черновики scripts/jury_check.{sh,ps1} и scripts/jury_summary.py для №16 (лежат в фикстурах №02)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

D = Path(__file__).parent / "fixtures" / "02_providers" / "jury_scripts"


def test_sh_syntax_and_steps():
    text = (D / "jury_check.sh").read_text(encoding="utf-8")
    for step in ("doctor --live", "verify", "jury_summary.py", "--no-cache"):
        assert step in text
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n", str(D / "jury_check.sh")]).returncode == 0


def test_ps1_has_bom_for_windows_powershell_5():
    raw = (D / "jury_check.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "без BOM Windows PowerShell 5.1 прочтёт русский текст как cp1251"
    text = raw.decode("utf-8-sig")
    for step in ("doctor --live", "verify", "jury_summary.py", "OutputEncoding"):
        assert step in text


@pytest.mark.parametrize("status,vcode,ok", [("complete", 0, True), ("partial", 0, False), ("complete", 1, False)])
def test_summary_prints_russian_passport(tmp_path, status, vcode, ok):
    report = {"run": {"status": status, "provider": "gemini", "models_used": ["gemini-3.8-flash-001"],
                      "calls": {"total": 9, "cached": 0, "failed": 0, "split": 0}, "tokens": {"input": 120000, "output": 30000},
                      "cost_usd": 0.0, "duration_s": 280.0, "warnings": []},
              "summary": {"findings": {"critical": 4, "major": 14, "minor": 14}, "quotes_verified": "87/87"},
              "verdict": {"development": "no", "testing": "conditional"}}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    import os
    r = subprocess.run([sys.executable, str(D / "jury_summary.py"), str(path), "281", "0", str(vcode)],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # Windows без UTF-8 (просьба №16)
    assert (r.returncode == 0) is ok
    out = r.stdout
    assert "gemini-3.8-flash-001" in out and "Вызовов модели:   9" in out
    assert "разработка — нельзя, тестирование — условно" in out
    assert ("всё работает" in out) is ok
