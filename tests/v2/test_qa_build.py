"""Контроль сборки `bcc/v2` (qa-build): стыки, которые не ловят тесты отдельных ролей.

1. Windows: ТЗ и файл ответов, сохранённые Блокнотом в ANSI (cp1251) или «Юникоде» (UTF-16 LE с BOM),
   читаются так же, как UTF-8. Раньше `docview` такой документ читал, а нарезка (`segment._raw_source_lines`),
   редакция (`revise._source_lines`) и ответы (`recheck.load_answers`) брали файл только как UTF-8:
   ТЗ из текущей папки давало 0 требований, `--answers/--revise` молча не выполнялся (код 0).
2. Mock-прогон по официальному документу: записанные решения судьи ссылаются на существующих кандидатов
   (иначе у дефектов чужие цитаты и источники).

Прогоны — провайдер mock, без сети.
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
ANSWERS = ROOT / "examples" / "v2" / "answers.md"
FIXTURES = ROOT / "tests" / "v2" / "fixtures" / "official"

ENCODINGS = {
    "ansi": lambda t: t.replace("\n", "\r\n").encode("cp1251", errors="replace"),
    "utf16": lambda t: t.replace("\n", "\r\n").encode("utf-16"),  # Блокнот «Юникод»: UTF-16 LE с BOM
    "utf8bom": lambda t: b"\xef\xbb\xbf" + t.replace("\n", "\r\n").encode("utf-8"),
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        env.pop(key, None)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "bcc_review", *args], cwd=cwd, env=_env(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)


def _write(path: Path, text: str, enc: str) -> Path:
    path.write_bytes(ENCODINGS[enc](text))
    return path


@pytest.mark.parametrize("enc", sorted(ENCODINGS))
def test_load_answers_reads_notepad_encodings(tmp_path, enc):
    from bcc_review.v2.stages.recheck import load_answers

    text = ANSWERS.read_text(encoding="utf-8")
    expected = load_answers(str(ANSWERS))
    got = load_answers(str(_write(tmp_path / f"answers_{enc}.md", text, enc)))
    assert len(got["answers"]) == len(expected["answers"]) > 0
    if enc != "ansi":  # в cp1251 нет части знаков (≤, ₸) — они заменяются, сами ответы те же
        assert got == expected


@pytest.mark.parametrize("enc", sorted(ENCODINGS))
def test_segment_and_revise_read_source_in_notepad_encodings(tmp_path, enc):
    from bcc_review.v2.stages import revise, segment

    text = SOURCE.read_text(encoding="utf-8")
    p = _write(tmp_path / f"req_{enc}.md", text, enc)
    want = text.splitlines()
    raw = segment._raw_source_lines({"format": "md", "file": str(p)})
    assert raw is not None and len(raw) == len(want)
    assert raw[0] == want[0]  # заголовок «# …» распознаётся
    lines, from_file = revise._source_lines(None, {"path": str(p), "lines": [{"text": s} for s in want]})
    assert from_file and len(lines) == len(want) and lines[0] == want[0]


@pytest.mark.parametrize("enc", ["ansi", "utf16"])
def test_cli_notepad_document_and_answers_from_current_folder(tmp_path, enc):
    """Как на Windows: ТЗ и ответы в текущей папке, относительные пути, mock-прогон с --answers --revise."""
    _write(tmp_path / "tz.md", SOURCE.read_text(encoding="utf-8"), enc)
    _write(tmp_path / "answers.md", ANSWERS.read_text(encoding="utf-8"), enc)
    proc = _run(["tz.md", "out/tz.md", "--provider", "mock", "--mock-dir", str(FIXTURES), "--no-cache",
                 "--answers", "answers.md", "--revise"], tmp_path)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads((tmp_path / "out" / "tz.json").read_text(encoding="utf-8"))
    warnings = report["run"].get("warnings") or []
    assert not [w for w in warnings if "UnicodeDecodeError" in w or "codec" in w], warnings
    assert len(report["requirements"]) >= 30, warnings
    assert (tmp_path / "out" / "tz.revised.md").is_file(), warnings
    assert report.get("clarification"), "таблица «до / после» не построена"
    verify = _run(["verify", "out/tz.json", "tz.md"], tmp_path)
    assert verify.returncode == 0, verify.stdout[-2000:] + verify.stderr[-2000:]


@pytest.mark.xfail(reason="qa-build: mock-фикстура судьи записана до постобработки lens_risk (7e16ccd) — номера "
                          "кандидатов сдвинулись; нужна перезапись tests/v2/fixtures/official (№01)", strict=False)
def test_mock_judge_refers_to_existing_candidates(tmp_path):
    proc = _run([str(SOURCE), str(tmp_path / "m.md"), "--provider", "mock", "--no-cache"], tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    bad = [w for w in report["run"].get("warnings") or [] if "несуществующего кандидата" in w]
    assert not bad, bad
