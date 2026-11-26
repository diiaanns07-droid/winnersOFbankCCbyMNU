"""Общие фикстуры тестов HTML-отчёта (№13).

Пакет ``bcc_review`` ещё не устанавливается через pyproject, поэтому ``src``
добавляется в путь импорта. После появления bootstrap это станет лишним.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fixture_builder import VARIANTS, build_report  # noqa: E402


@pytest.fixture()
def report() -> dict:
    return build_report(table_rows=40)


@pytest.fixture(params=sorted(VARIANTS))
def any_variant(request) -> tuple[str, dict]:
    return request.param, VARIANTS[request.param]()
