"""Фикстуры №14 устроены как Report v1 и проходят проверку контракта команды (bcc_review.contracts)."""

from __future__ import annotations

import pytest

contracts = pytest.importorskip("bcc_review.contracts", reason="контракт bcc/integration не подключён")


def _clean(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


def test_fixture_reports_validate_against_contract(case_report, md_report):
    for rep in (case_report, md_report):
        contracts.validate(_clean(rep))


def test_only_intentional_bad_evidence_is_flagged(case_report, md_report):
    """F-06 (PDF) и F-07 (MD) — намеренно неверные опоры; остальное контракт принимает."""
    for rep, bad in ((case_report, "F-06"), (md_report, "F-07")):
        idx = [i for i, f in enumerate(rep["findings"]) if f["id"] == bad][0]
        errs = contracts.evidence_errors(_clean(rep))
        assert errs and all(e.startswith(f"findings[{idx}]") for e in errs), errs


def test_pdf_fixture_loc_matches_contract_shape(case_blocks):
    for b in case_blocks:
        contracts.validate(b, "Block")
        assert b["id"].startswith("b") and b["loc"]["page"] >= 1
        for fr in b["loc"]["fragments"]:
            assert set(fr) == {"start", "end", "rect"}
