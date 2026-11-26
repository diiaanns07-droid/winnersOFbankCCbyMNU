"""Стык с контрактом v1 (bcc/integration): типы, пример Max и перепроверка без модели."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import synthetic_reader

from bcc_review import contracts as C
from bcc_review.analysis.evidence import EvidenceAudit, resolve_candidate, resolve_hint
from bcc_review.verification import summary_counts, verify_report

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts" / "examples"
SOURCE = EXAMPLES / "two_linked_requirements.md"
REPORT = EXAMPLES / "minimal_report.json"


@pytest.fixture(scope="module")
def example() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_synthetic_reader_reproduces_example_document(example: dict) -> None:
    doc = synthetic_reader.read(SOURCE)
    C.validate(doc, "Document")
    assert doc == {k: example["document"][k] for k in doc}


def test_resolver_reproduces_example_evidence(example: dict) -> None:
    doc = example["document"]
    f = example["findings"][0]
    audit = EvidenceAudit()
    candidate = {k: f[k] for k in ("scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints")}
    candidate["witness"] = {k: f["witness"][k] for k in ("input", "outcome_a", "outcome_b")}
    res = resolve_candidate(doc, candidate, audit=audit)
    assert res["anchor_status"] == f["anchor_status"] == "supported"
    assert res["evidence"] == f["evidence"]
    assert res["witness"] == f["witness"]
    C.validate(res["witness"], "Witness")
    for ev in res["evidence"]:
        C.validate(ev, "Evidence")
    C.validate(audit.to_dict(), "EvidenceAudit")
    assert {k: audit.to_dict()[k] for k in ("checked", "confirmed", "ambiguous", "rejected")} == \
        {k: example["run"]["evidence_audit"][k] for k in ("checked", "confirmed", "ambiguous", "rejected")}


def test_requirement_evidence_from_hint(example: dict) -> None:
    doc = example["document"]
    for req in example["requirements"]:
        res = resolve_hint(doc, {"block_id": req["block_ids"][0], "quote": req["text"]})
        assert [res["evidence"]] == req["evidence"]


def test_example_summary_matches_canonical(example: dict) -> None:
    assert summary_counts(example) == example["summary"]


def test_verify_accepts_example_and_rejects_tampering(tmp_path: Path, example: dict, no_network: list) -> None:
    result = verify_report(REPORT, SOURCE, reader=synthetic_reader.read)
    assert result["ok"], result["errors"]
    assert result["counts"]["confirmed"] == result["counts"]["checked"] == 6
    bad = json.loads(json.dumps(example))
    bad["summary"]["by_severity"]["critical"] = 0
    path = tmp_path / "report.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    result = verify_report(path, SOURCE, reader=synthetic_reader.read)
    assert result["exit_code"] == C.EXIT_VERIFY_FAILED
    assert [e["path"] for e in result["errors"]] == ["summary.by_severity.critical"]
    source = tmp_path / SOURCE.name
    shutil.copy(SOURCE, source)
    source.write_bytes(source.read_bytes() + b"\n")
    result = verify_report(REPORT, source, reader=synthetic_reader.read)
    assert {e["code"] for e in result["errors"]} == {"source_sha_mismatch", "document_id_mismatch"}
    assert not no_network
