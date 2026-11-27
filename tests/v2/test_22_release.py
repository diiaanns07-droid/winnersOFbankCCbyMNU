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
<<<<<<< HEAD
=======


def test_passport_commands_use_command_line_paths(tmp_path, monkeypatch):
    """Команды проверки в паспорте — с путями из командной строки (просьба №33, их af4969c9); без doc_path у рендера —
    прежний паспорт, а не упрощённый отчёт."""
    import inspect
    from pathlib import Path
    from bcc_review.v2 import pipeline
    from bcc_review.v2.render import markdown
    root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(root)
    out = tmp_path / "reports" / "r.md"
    report, written = pipeline.review("release/input/requirements.md", out,
                                      {"provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False})
    md = Path(written["md"]).read_text(encoding="utf-8")
    assert not any("упрощённо" in w for w in report["run"]["warnings"])
    if "doc_path" in inspect.signature(markdown.render).parameters:
        line = next(x for x in md.splitlines() if "bcc_review verify" in x)
        assert "release/input/requirements.md" in line and "r.json" in line
>>>>>>> 80b4f371
