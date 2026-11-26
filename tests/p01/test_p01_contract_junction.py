"""Стыковой тест reader №01 с контрактом v1 (bcc/integration, контракт 431f76d).

* каждый Document проходит ``bcc_review.contracts.validate(..., "Document")``;
* вход примера Max (``contracts/examples/two_linked_requirements.md``) даёт тот же Document, что лежит
  в ``contracts/examples/minimal_report.json``: id, kind, section, text, строки и ``loc.map``;
* опора, построенная по Document, проходит ``evidence_errors`` контракта.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bcc_review import contracts as C
from bcc_review.readers.text import read_text

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
EXAMPLES = ROOT / "contracts" / "examples"
FIXTURES = [FIX / "official_requirements.md", FIX / "spec_ab.md", FIX / "notes.txt",
            EXAMPLES / "two_linked_requirements.md"]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_document_validates_against_contract_v1(path):
    d = json.loads(json.dumps(read_text(path).to_dict(), ensure_ascii=False))
    C.validate(d, "Document")
    assert {b["kind"] for b in d["blocks"]} <= set(C.BLOCK_KINDS)
    assert d["format"] in C.DOC_FORMATS
    assert not [w for w in d["warnings"] if w["code"] in C.PARTIAL_READ_CODES]


def test_reader_reproduces_contract_example_document():
    ref = json.loads((EXAMPLES / "minimal_report.json").read_text(encoding="utf-8"))["document"]
    got = read_text(EXAMPLES / "two_linked_requirements.md").to_dict()
    for key in ("id", "title", "format", "source_name", "warnings"):
        assert got[key] == ref[key], key
    keys = ("id", "kind", "section", "text")
    loc_keys = ("line_start", "line_end", "map")
    assert [({k: b[k] for k in keys}, {k: b["loc"][k] for k in loc_keys}) for b in got["blocks"]] == \
           [({k: b[k] for k in keys}, {k: b["loc"][k] for k in loc_keys}) for b in ref["blocks"]]


def test_evidence_built_from_reader_passes_contract_invariants():
    report = json.loads((EXAMPLES / "minimal_report.json").read_text(encoding="utf-8"))
    report = copy.deepcopy(report)
    report["document"] = read_text(EXAMPLES / "two_linked_requirements.md").to_dict()
    C.validate(report)
    assert C.evidence_errors(report) == []
