"""Общие фикстуры tests/p07: путь к пакету, синтетические документы, запрет сети."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for extra in (ROOT / "src", HERE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import synthetic_reader  # noqa: E402
from p07_helpers import FIXTURES  # noqa: E402


@pytest.fixture(scope="session")
def md_doc() -> dict:
    return synthetic_reader.read(FIXTURES / "case.md")


@pytest.fixture(scope="session")
def pdf_doc() -> dict:
    pytest.importorskip("pdfplumber")
    return synthetic_reader.read(FIXTURES / "case.pdf")


@pytest.fixture(scope="session")
def docx_doc() -> dict:
    pytest.importorskip("docx")
    return synthetic_reader.read(FIXTURES / "case.docx")


@pytest.fixture(scope="session")
def bcc_doc() -> dict:
    return synthetic_reader.read(FIXTURES / "bcc_requirements.md")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list:
    """Любая попытка сетевого соединения (вызов LLM) роняет тест."""
    attempts: list = []

    def guard(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.append(address)
        raise AssertionError(f"сетевой вызов запрещён: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: guard(None, a))
    return attempts
