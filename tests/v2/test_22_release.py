"""№22 — исправления в релиз: пустой документ — код выхода ≠ 0 (просьба №23, бриф жюри: плохой вход → код ≠ 0)."""
from __future__ import annotations

import json


def test_empty_document_exit_code_2_and_report_written(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    src = tmp_path / "empty.md"
    src.write_bytes(b"")
    out = tmp_path / "o" / "r.md"
    code = main([str(src), str(out), "--provider", "mock", "-q", "--no-html", "--runs-dir", str(tmp_path / "runs")])
    assert code == 2
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["run"]["empty_input"] is True
    assert data["verdict"]["development"] != "yes"
    assert "нет текста" in capsys.readouterr().out + out.read_text(encoding="utf-8")


def test_whitespace_only_document_exit_code_2(tmp_path):
    from bcc_review.v2.__main__ import main
    src = tmp_path / "blank.txt"
    src.write_text("\n   \n\t\n", encoding="utf-8")
    assert main([str(src), str(tmp_path / "r.md"), "--provider", "mock", "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")]) == 2


def test_normal_document_exit_code_0(tmp_path):
    from pathlib import Path
    from bcc_review.v2.__main__ import main
    official = Path(__file__).resolve().parents[2] / "release" / "input" / "requirements.md"
    assert main([str(official), str(tmp_path / "r.md"), "--provider", "mock", "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")]) == 0
