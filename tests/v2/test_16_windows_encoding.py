"""№16: агент работает там, где кодировка по умолчанию не UTF-8 (Windows: cp1251/cp1252).

На Windows ``open()`` без ``encoding=`` пишет и читает в кодировке ANSI, а вывод в файл или конвейер
(`> log.txt`, CI) идёт в cp1252/cp1251 — кириллица, «ёлочки» и тире там роняют прогон до записи отчёта.
Здесь это воспроизводится на любой ОС: локаль C и ``PYTHONUTF8=0`` дают кодировку по умолчанию ASCII
(строже Windows), а stdout перенаправлен в cp1252. Прогон — провайдер mock, без сети.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "release" / "input" / "requirements.md"


def _v2_ready() -> bool:
    return (ROOT / "src" / "bcc_review" / "v2" / "pipeline.py").exists()


pytestmark = pytest.mark.skipif(not _v2_ready(), reason="каркаса v2 ещё нет")


def _legacy_env(stdout_encoding: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "PYTHONUTF8", "PYTHONIOENCODING"))}
    env.update({"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
                "PYTHONIOENCODING": stdout_encoding})
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        env.pop(key, None)
    return env


def _run(args: list[str], cwd: Path, stdout_encoding: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "bcc_review", *args], cwd=cwd, env=_legacy_env(stdout_encoding),
                          capture_output=True, timeout=600)


def _tail(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout + proc.stderr).decode("utf-8", "replace")[-3000:]


def test_mock_report_is_written_in_utf8_without_utf8_locale(tmp_path):
    """Файлы отчёта пишутся в UTF-8 при любой кодировке ОС (stdout здесь UTF-8, проверяется только запись файлов)."""
    out = tmp_path / "отчёт" / "requirements.md"
    proc = _run([str(SOURCE), str(out), "--provider", "mock", "--no-cache"], tmp_path, "utf-8")
    assert proc.returncode == 0, _tail(proc)
    text = out.read_text(encoding="utf-8")  # UnicodeDecodeError — файл записан не в UTF-8
    assert any("а" <= ch <= "я" for ch in text.lower())
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report.get("schema", "").startswith("bcc-review/")
    verify = _run(["verify", str(out.with_suffix(".json")), str(SOURCE)], tmp_path, "utf-8")
    assert verify.returncode == 0, _tail(verify)


def test_console_output_survives_cp1252_pipe(tmp_path):
    """Вывод в конвейер с кодировкой cp1252 (PowerShell `> log.txt`, CI на Windows) не роняет прогон."""
    out = tmp_path / "requirements.md"
    proc = _run([str(SOURCE), str(out), "--provider", "mock", "--no-cache"], tmp_path, "cp1252")
    assert proc.returncode == 0, _tail(proc)
    assert out.exists() and out.with_suffix(".json").exists()


def test_dotenv_written_by_windows_powershell_is_read(tmp_path):
    """`echo GEMINI_API_KEY=… > .env` в Windows PowerShell 5.1 пишет UTF-16 с BOM: ключ всё равно должен читаться."""
    from bcc_review.v2.providers import doctor

    env_file = tmp_path / ".env"
    env_file.write_bytes("GEMINI_API_KEY=AIzaFAKE-utf16\r\n".encode("utf-16"))
    env: dict[str, str] = {}
    assert doctor.load_dotenv(env_file, env)
    assert env.get("GEMINI_API_KEY") == "AIzaFAKE-utf16"


def test_dotenv_from_notepad_with_bom_and_crlf_is_read(tmp_path):
    """Блокнот Windows: UTF-8 с BOM и CRLF; пробелы и кавычки вокруг значения — ключ читается без них."""
    from bcc_review.v2.providers import doctor

    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xef\xbb\xbf# comment\r\nGEMINI_API_KEY = \"AIzaFAKE-notepad\"\r\n")
    env: dict[str, str] = {}
    assert doctor.load_dotenv(env_file, env)
    assert env.get("GEMINI_API_KEY") == "AIzaFAKE-notepad"
