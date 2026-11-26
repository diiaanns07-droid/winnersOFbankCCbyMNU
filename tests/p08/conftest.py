"""Фикстуры №08: синтетический документ о досрочном погашении, находки «как от
Max» и подставной транспорт ask. Всё детерминировано, сеть и ключи не нужны."""
from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bcc_review.decisions import build_questions, render_questions_md  # noqa: E402
from bcc_review.decisions._demo import SYNTHETIC_DOC, make_scripted_ask, synthetic_findings  # noqa: E402
from bcc_review.decisions._doc import load_markdown  # noqa: E402


@pytest.fixture
def src_path(tmp_path: Path) -> Path:
    """Копия синтетического ТЗ во временной папке (исходник примеров не трогаем)."""
    p = tmp_path / "loan_tz.md"
    shutil.copyfile(SYNTHETIC_DOC, p)
    return p


@pytest.fixture
def doc(src_path: Path) -> dict:
    return load_markdown(src_path)


@pytest.fixture
def findings(doc: dict) -> list[dict]:
    return synthetic_findings(doc)


@pytest.fixture
def ask(doc):
    calls: list[tuple] = []
    scripted = make_scripted_ask(doc)

    def _ask(stage, payload, schema):
        calls.append((stage, copy.deepcopy(payload), schema))
        return scripted(stage, payload, schema)

    _ask.calls = calls
    return _ask


@pytest.fixture
def questions(doc, findings, ask):
    return build_questions(doc, findings, ask)


@pytest.fixture
def questions_md(doc, questions) -> str:
    return render_questions_md(doc, questions)


def _q_by_findings(questions, fid: str):
    return next(q for q in questions if fid in q.finding_ids)


@pytest.fixture
def qf():
    """qf(questions, "F-01") -> вопрос, который закрывает находку."""
    return _q_by_findings
