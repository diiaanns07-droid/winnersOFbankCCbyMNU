"""Фикстуры №06. Хелперы — в p06_helpers (импорт `from conftest import …` перехватили бы conftest других каталогов)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for p in (HERE.parents[1] / "src", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from p06_helpers import FIXTURES, load_markdown, read_doc  # noqa: E402


@pytest.fixture
def load():
    def _load(name: str, loader: str = "engine", **kw) -> dict:
        if loader == "engine":
            return read_doc(FIXTURES / name)
        return load_markdown(FIXTURES / name, table_mode=kw.get("table_mode", "row"))
    return _load


@pytest.fixture
def case_doc():
    return read_doc(FIXTURES / "case_ab.md")
