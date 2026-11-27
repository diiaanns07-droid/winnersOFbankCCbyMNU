"""Max (проверка на Windows): файл ответов из Блокнота в любой кодировке.

Блокнот русской Windows сохраняет «ANSI» (cp1251) или «Юникод» (UTF-16). Раньше такой файл давал
UnicodeDecodeError, режим --answers не выполнялся молча: ни предупреждения в отчёте и терминале, ни кода ошибки.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2.__main__ import main
from bcc_review.v2.stages.recheck import load_answers

ROOT = Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "examples" / "v2" / "answers.md"
DOC = ROOT / "release" / "input" / "requirements.md"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1251", "utf-16"])
def test_answers_file_in_any_notepad_encoding(tmp_path, encoding):
    text = ANSWERS.read_text(encoding="utf-8")
    p = tmp_path / f"answers.{encoding}.md"
    # как Блокнот: CRLF, а символы вне кодировки (знак тенге в cp1251) заменяются на «?»
    p.write_bytes(text.replace("\n", "\r\n").encode(encoding, errors="replace"))
    got = load_answers(str(p))
    want = load_answers(str(ANSWERS))
    assert len(got["answers"]) == len(want["answers"]) == 10
    assert got["decisions"] == want["decisions"] and got["decisions"]
    assert got["answers"][0]["text"].startswith("Месяц расходов")


def test_answers_mode_failure_is_visible_in_report(tmp_path, monkeypatch):
    from bcc_review.v2.stages import revise

    def boom(*a, **k):
        raise ValueError("файл ответов сломан")

    monkeypatch.setattr(revise, "run_modes", boom)
    out = tmp_path / "r.md"
    code = main([str(DOC), str(out), "--provider", "mock", "--answers", str(ANSWERS)])
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert code == 0
    assert any("--answers" in str(w) and "файл ответов сломан" in str(w) for w in report["run"]["warnings"])
