"""Общие фикстуры №02. Пакет src/bcc_review подключается без установки."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for path in (ROOT / 'src', HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

FIXTURES = HERE / 'fixtures'


@pytest.fixture(scope='session')
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(scope='session')
def sample_doc():
    from bcc_review.readers.pdf import read_pdf
    return read_pdf(FIXTURES / 'p02_sample.pdf', ocr='off')
