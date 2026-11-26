"""Стыковой тест с контрактом v1 (bcc/integration, коммит 431f76d): Document, Evidence, Report."""

from __future__ import annotations

import pytest
from p03_fixtures import CASE_DOCX, evidence, finding, make_report, ref_id, rich_doc

from bcc_review.contracts import BLOCK_KINDS, PARTIAL_READ_CODES, evidence_errors, validate
from bcc_review.exports.word import annotate_docx
from bcc_review.readers.docx import read_docx


@pytest.mark.parametrize("make", ["case", "rich"])
def test_docx_document_matches_contract(tmp_path, make):
    path = CASE_DOCX if make == "case" else rich_doc(tmp_path / "rich.docx")
    doc = read_docx(path).to_dict()
    validate(doc, "Document")
    assert doc["format"] == "docx" and len(doc["id"]) == 64
    assert [b["id"] for b in doc["blocks"]] == [f"b{i:04d}" for i in range(1, len(doc["blocks"]) + 1)]
    assert {b["kind"] for b in doc["blocks"]} <= set(BLOCK_KINDS)
    for w in doc["warnings"]:
        validate(w, "Warning")
    assert not [w for w in doc["warnings"] if w["code"] in PARTIAL_READ_CODES]


def test_docx_evidence_and_report_match_contract(tmp_path):
    doc = read_docx(CASE_DOCX)
    ev = evidence(doc, ref_id(doc, "p16"), "Ф-2. Месяц определяется")
    validate(ev, "Evidence")
    report = make_report(doc, [finding("F-001", [ev], req_ids=["R-F2"])])  # внутри validate + evidence_errors
    assert evidence_errors(report) == []
    res = annotate_docx(report, CASE_DOCX, tmp_path / "report.annotated.docx")
    for w in res.warnings():
        validate(w, "Warning")
