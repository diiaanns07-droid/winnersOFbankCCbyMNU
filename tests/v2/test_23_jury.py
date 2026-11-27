"""№23: путь жюри — плохие входы и выгрузки дают понятную русскую ошибку, код выхода и никакой трассировки.

Всё без сети и без ключа: провайдеры ``mock`` и ``offline``, прогон в этом же процессе (как ``python -m bcc_review``).
Тесты с ``xfail(strict=True)`` — найденные ошибки, отданные владельцам (см. ``docs/plan-v2/status/23.md``):
когда владелец исправит, тест станет XPASS и пометку надо снять.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
PDF = ROOT / "release" / "input" / "requirements.pdf"

for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
    os.environ.pop(key, None)


def _cli(tmp_path: Path, capsys, *args: str) -> tuple[int, str]:
    from bcc_review import __main__ as top

    argv = list(args)
    if argv and argv[0] not in ("verify", "doctor", "stage"):
        argv += ["--no-cache", "--runs-dir", str(tmp_path / "runs"), "-q"]
    code = top.main(argv)
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def _no_trace(text: str) -> None:
    assert "Traceback" not in text
    assert not re.search(r"\b(?:Error|Exception):", text), text[-800:]


# --- входы, которых нет или которые не читаются ---------------------------------------------------------------


def test_missing_input(tmp_path, capsys):
    code, out = _cli(tmp_path, capsys, str(tmp_path / "нет.md"), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    assert code == 2 and "Файл не найден" in out
    _no_trace(out)


def test_missing_answers_file(tmp_path, capsys):
    code, out = _cli(tmp_path, capsys, str(DOC), str(tmp_path / "o" / "r.md"), "--provider", "mock",
                     "--answers", str(tmp_path / "нет.txt"))
    assert code == 2 and "Файл ответов не найден" in out


@pytest.mark.parametrize("name,data,needle", [
    ("zero.pdf", b"", "PDF"),
    ("fake.pdf", b"not a pdf\n", "не является PDF"),
    ("fake.docx", b"not a docx\n", "не является DOCX"),
])
def test_broken_binary_input(tmp_path, capsys, name, data, needle):
    src = tmp_path / name
    src.write_bytes(data)
    code, out = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    assert code != 0, out
    assert needle in out
    _no_trace(out)


def test_password_pdf(tmp_path, capsys):
    pymupdf = pytest.importorskip("pymupdf")
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "F-1. The system shall send a notification.")
    src = tmp_path / "locked.pdf"
    d.save(str(src), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    code, out = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    assert code != 0 and "паролем" in out
    _no_trace(out)


def test_empty_file_says_no_text(tmp_path, capsys):
    src = tmp_path / "empty.md"
    src.write_bytes(b"")
    code, out = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    assert "нет текста" in out
    _no_trace(out)


@pytest.mark.xfail(strict=True, reason="№23 → №22: пустой документ даёт код 0; бриф жюри — код ≠ 0 (просьба в статусе 23)")
def test_empty_file_nonzero_exit(tmp_path, capsys):
    src = tmp_path / "empty.md"
    src.write_bytes(b"")
    code, _ = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    assert code != 0


def test_scanned_pdf_hints_ocr(tmp_path, capsys):
    pymupdf = pytest.importorskip("pymupdf")
    d = pymupdf.open()
    d.new_page().draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    src = tmp_path / "scan.pdf"
    d.save(str(src))
    code, out = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "r.md"), "--provider", "mock")
    _no_trace(out)
    assert re.search(r"скан|распозна|OCR", out, re.I), out[-600:]


# --- кодировки и переводы строк (Windows) --------------------------------------------------------------------


@pytest.mark.parametrize("encoding,bom", [("cp1251", b""), ("utf-16-le", b"\xff\xfe"), ("utf-8", b"\xef\xbb\xbf")])
def test_non_utf8_text_is_decoded(tmp_path, capsys, encoding, bom):
    text = "# Требования\r\n\r\nФ-1. Система должна отправлять уведомление в течение 5 секунд.\r\n"
    src = tmp_path / "tz.md"
    src.write_bytes(bom + text.encode(encoding))
    out_md = tmp_path / "o" / "r.md"
    code, out = _cli(tmp_path, capsys, str(src), str(out_md), "--provider", "mock")
    assert code == 0, out
    rep = out_md.with_suffix(".json").read_text(encoding="utf-8")
    assert "уведомление" in rep and "Ð" not in rep and "Ã" not in rep


def test_crlf_official_document_verifies(tmp_path, capsys):
    """Документ с Windows-переводами строк: цитаты находятся, verify сходится."""
    src = tmp_path / "requirements.md"
    src.write_bytes(DOC.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    out_md = tmp_path / "o" / "r.md"
    code, out = _cli(tmp_path, capsys, str(src), str(out_md), "--provider", "mock")
    assert code == 0, out
    code, out = _cli(tmp_path, capsys, "verify", str(out_md.with_suffix(".json")), str(src))
    assert code == 0, out


def test_big_markdown_offline(tmp_path, capsys):
    """Markdown ~5 МБ без модели: отчёт записан, без трассировки и за разумное время."""
    import time

    line = "Ф-{}. Система должна отправлять уведомление клиенту в течение {} секунд после операции по карте.\n"
    body = "# Большое ТЗ\n\n" + "".join(line.format(i, i % 60 + 1) for i in range(1, 30_000))
    src = tmp_path / "big.md"
    src.write_text(body, encoding="utf-8")
    assert src.stat().st_size > 4_000_000
    t = time.monotonic()
    code, out = _cli(tmp_path, capsys, str(src), str(tmp_path / "o" / "big.md"), "--provider", "offline")
    assert code == 0, out
    assert time.monotonic() - t < 120
    _no_trace(out)


# --- куда пишется отчёт ----------------------------------------------------------------------------------------


def test_output_under_a_file(tmp_path, capsys):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    code, out = _cli(tmp_path, capsys, str(DOC), str(blocker / "r.md"), "--provider", "mock")
    assert code == 2 and "Не удаётся записать отчёт" in out


def test_output_equals_input(tmp_path, capsys):
    src = tmp_path / "tz.md"
    src.write_bytes(DOC.read_bytes())
    code, out = _cli(tmp_path, capsys, str(src), str(src), "--provider", "mock")
    assert code == 2 and "совпадает с файлом требований" in out
    assert src.read_bytes() == DOC.read_bytes()


def test_output_dir_created_and_folder_target(tmp_path, capsys):
    code, out = _cli(tmp_path, capsys, str(DOC), str(tmp_path / "новая" / "папка") + os.sep, "--provider", "mock")
    assert code == 0, out
    assert (tmp_path / "новая" / "папка" / "requirements.md").is_file()


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="права на каталог не действуют для root и на Windows")
def test_output_read_only_dir(tmp_path, capsys):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        code, out = _cli(tmp_path, capsys, str(DOC), str(ro / "r.md"), "--provider", "mock")
    finally:
        ro.chmod(0o755)
    assert code == 2 and "нет прав" in out


# --- verify ----------------------------------------------------------------------------------------------------


def test_verify_missing_report(tmp_path, capsys):
    code, out = _cli(tmp_path, capsys, "verify", str(tmp_path / "нет.json"), str(DOC))
    assert code != 0
    assert "Traceback" not in out


# --- выгрузки из README ------------------------------------------------------------------------------------------


def test_all_exports_from_readme(tmp_path, capsys):
    out_md = tmp_path / "o" / "r.md"
    code, out = _cli(tmp_path, capsys, str(DOC), str(out_md), "--provider", "mock", "--export", "html,jira,docx,pdf")
    assert code == 0, out
    for suffix in (".md", ".json", ".html", ".jira.csv"):
        assert out_md.with_suffix(suffix).is_file(), suffix
    assert list(out_md.parent.glob("r*.docx")), "нет Word-выгрузки"
    assert list(out_md.parent.glob("r*.pdf")), "нет PDF-выгрузки"


def test_pdf_input_with_exports(tmp_path, capsys):
    pytest.importorskip("pymupdf")
    out_md = tmp_path / "o" / "r.md"
    code, out = _cli(tmp_path, capsys, str(PDF), str(out_md), "--provider", "offline", "--export", "pdf,jira")
    assert code == 0, out
    assert out_md.with_suffix(".annotated.pdf").is_file()
    code, out = _cli(tmp_path, capsys, "verify", str(out_md.with_suffix(".json")), str(PDF))
    assert code == 0, out


# --- демонстрация без ключа ------------------------------------------------------------------------------------


def test_mock_demo_matches_recorded_run(tmp_path, capsys):
    """``--provider mock`` по документу кейса — то, что жюри запустит без ключа (SUBMISSION, шаг 3)."""
    out_md = tmp_path / "o" / "mock.md"
    code, out = _cli(tmp_path, capsys, str(DOC), str(out_md), "--provider", "mock")
    assert code == 0
    assert "несуществующего кандидата" not in out
    rep = json.loads(out_md.with_suffix(".json").read_text(encoding="utf-8"))
    crit = [f for f in rep.get("findings", []) if f.get("severity") == "critical"]
    assert len(crit) >= 4


# --- кодировка по умолчанию нигде не используется (Windows: cp1251) -------------------------------------------


def test_agent_never_relies_on_default_encoding(tmp_path):
    """``-X warn_default_encoding``: каждый ``open()``/``read_text()`` без ``encoding=`` в коде агента — предупреждение.

    На Windows такая строка читает и пишет в cp1251; mock-прогон с выгрузками, ответами, verify — без них.
    Вызовы ``git`` (ASCII-вывод) не в счёт.
    """
    out_md = tmp_path / "o" / "r.md"
    env = dict(os.environ, PYTHONWARNINGS="always::EncodingWarning")
    runs = ["--no-cache", "--runs-dir", str(tmp_path / "runs"), "-q"]
    cmds = [
        [str(DOC), str(out_md), "--provider", "mock", "--export", "html,jira,docx,pdf", *runs],
        [str(DOC), str(tmp_path / "o" / "a.md"), "--provider", "mock", "--answers",
         str(ROOT / "examples" / "v2" / "answers.md"), "--revise", *runs],
        ["verify", str(out_md.with_suffix(".json")), str(DOC)],
        ["doctor"],
    ]
    bad = []
    for args in cmds:
        p = subprocess.run([sys.executable, "-X", "warn_default_encoding", "-m", "bcc_review", *args], cwd=ROOT,
                           env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        lines = p.stderr.splitlines()
        for i, ln in enumerate(lines):
            if "EncodingWarning" in ln and "bcc_review" in ln.replace("\\", "/").split("EncodingWarning")[0]:
                src = lines[i + 1] if i + 1 < len(lines) else ""
                if '"git"' not in src and "--version" not in src:
                    bad.append(ln.strip() + " | " + src.strip())
    assert not bad, "\n".join(sorted(set(bad)))
