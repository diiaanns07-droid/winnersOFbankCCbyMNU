"""№33: `verify` — сообщения по-русски при плохом входе (просьба №23 через №22)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import verify  # noqa: E402

DOC = ROOT / "release" / "input" / "requirements.md"
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"


def _run(capsys, *argv) -> tuple[int, str]:
    code = verify.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out + out.err


def _english(text: str) -> list[str]:
    return re.findall(r"\b(?:No such|Errno|Expecting|Permission|denied|directory|Is a)\b", text)


def test_missing_report_or_document_is_explained_in_russian(capsys, tmp_path):
    code, out = _run(capsys, tmp_path / "нет.json", DOC)
    assert code == verify.EXIT_VERIFY_FAILED and "файл отчёта не найден" in out and not _english(out)
    code, out = _run(capsys, SAMPLE, tmp_path / "нет.md")
    assert code == verify.EXIT_VERIFY_FAILED and "документ не найден" in out and not _english(out)
    code, out = _run(capsys, SAMPLE, tmp_path)
    assert code == verify.EXIT_VERIFY_FAILED and "это папка" in out and not _english(out)


def test_broken_json_is_explained_in_russian(capsys, tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text("{не json", encoding="utf-8")
    code, out = _run(capsys, bad, DOC)
    assert code == verify.EXIT_VERIFY_FAILED and "не читается как JSON (строка 1" in out and not _english(out)
