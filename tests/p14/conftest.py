"""Пути для тестов №14: пакет из src/ и общие фикстуры рядом."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
for p in (SRC, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import p14_fixtures as fx  # noqa: E402


@pytest.fixture(scope="session")
def case_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fx.build_pdf(tmp_path_factory.mktemp("p14pdf") / "spec.pdf")


@pytest.fixture(scope="session")
def case_blocks(case_pdf: Path) -> list[dict]:
    return fx.extract_blocks(case_pdf)


@pytest.fixture(scope="session")
def case_report(case_pdf: Path, case_blocks: list[dict]) -> dict:
    return fx.pdf_report(case_pdf, case_blocks)


@pytest.fixture(scope="session")
def exported_pdf(tmp_path_factory: pytest.TempPathFactory, case_pdf: Path, case_report: dict):
    from bcc_review.exports.pdf import export_pdf

    out = tmp_path_factory.mktemp("p14out") / "spec.annotated.pdf"
    return export_pdf(case_report, case_pdf, out)


@pytest.fixture(scope="session")
def case_md(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("p14md") / "spec.md"
    p.write_text(fx.MARKDOWN, encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def md_report(case_md: Path) -> dict:
    return fx.md_report(case_md)


@pytest.fixture(scope="session")
def exported_md(tmp_path_factory: pytest.TempPathFactory, case_md: Path, md_report: dict):
    from bcc_review.exports.pdf import export_pdf

    out = tmp_path_factory.mktemp("p14mdout") / "spec.md.pdf"
    return export_pdf(md_report, case_md, out)
