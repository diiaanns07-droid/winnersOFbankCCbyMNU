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


def test_verify_missing_report_goes_to_v2(tmp_path, monkeypatch):
    """``python -m bcc_review verify нет.json ТЗ.md`` — отвечает v2 (по-русски, «файл отчёта не найден», №33
    ``91b43493``), а не v1 с «[Errno 2] No such file or directory» (просьба №33)."""
    import bcc_review.cli as v1cli
    import bcc_review.v2.__main__ as v2main
    from bcc_review.__main__ import main
    seen = []

    def fake(name):
        def run(argv):
            seen.append((name, list(argv)))
            return 4
        return run

    monkeypatch.setattr(v2main, "main", fake("v2"))
    monkeypatch.setattr(v1cli, "main", fake("v1"))
    missing = str(tmp_path / "нет.json")
    assert main(["verify", missing, "ТЗ.md"]) == 4
    assert seen == [("v2", ["verify", missing, "ТЗ.md"])]


def test_verify_existing_v1_report_still_goes_to_v1(tmp_path, monkeypatch):
    import bcc_review.cli as v1cli
    import bcc_review.v2.__main__ as v2main
    from bcc_review.__main__ import main
    seen = []
    monkeypatch.setattr(v2main, "main", lambda argv: seen.append("v2") or 0)
    monkeypatch.setattr(v1cli, "main", lambda argv: seen.append("v1") or 0)
    old = tmp_path / "v1.json"
    old.write_text(json.dumps({"schema": "bcc-review/1"}), encoding="utf-8")
    v2rep = tmp_path / "v2.json"
    v2rep.write_text(json.dumps({"schema": "bcc-review/2"}), encoding="utf-8")
    assert main(["verify", str(old), "ТЗ.md"]) == 0
    assert main(["verify", str(v2rep), "ТЗ.md"]) == 0
    assert seen == ["v1", "v2"]
