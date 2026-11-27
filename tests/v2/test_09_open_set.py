"""№09: открытый набор №18 (новые домены) — записанные ответы haiku этапа набора, без сети.

* чистые версии `qr_clean`, `capital_clean`: ни одного critical. Раньше haiku выдавал здесь «200 — успешный ↔ отказ
  тоже 200», «можно отменить, если нет перевода в обработке ↔ оплаченный — 410» и «список карт не описан»;
* `insurance`: два разных противоречия у одного пункта (возврат премии ↔ строка приёмки; ставка после отказа ↔
  особое правило API) — два замечания, а не одно склеенное;
* `qr`: граница диапазона суммы ↔ строка приёмки — critical `boundary_conflict`.

Документы, нарезка и ответы скопированы из `evaluation/v2/open2` (№18) и прогона этапа на haiku.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2.stages import consistency as C
from test_09_recorded import load_view

FIX = Path(__file__).resolve().parent / "fixtures" / "09_open"


def run(case: str) -> dict:
    view = load_view(FIX / case / "source.md")
    reqs = json.loads((FIX / case / "segment.json").read_text(encoding="utf-8"))["requirements"]
    raw = json.loads((FIX / case / "consistency.haiku.json").read_text(encoding="utf-8"))
    return C.postprocess(raw, view, reqs)


def lines_of(c: dict) -> set[int]:
    return {e["line"] for e in c["evidence"] if e.get("verified") != "missing"}


@pytest.mark.parametrize("case", ["qr_clean", "capital_clean"])
def test_clean_versions_have_no_critical(case):
    out = run(case)
    assert [c["title"] for c in out["candidates"] if c["severity"] == "critical"] == []


def test_two_conflicts_of_one_clause_stay_separate():
    out = run("insurance")
    crit = [c for c in out["candidates"] if c["severity"] == "critical" and c["origin"] == "pair_check"]
    refund = [c for c in crit if {40, 66} <= lines_of(c)]
    rate = [c for c in crit if {40, 130} <= lines_of(c)]
    assert refund and rate and refund[0] is not rate[0]


def test_amount_boundary_against_acceptance_row_is_critical():
    out = run("qr")
    assert any(c["kind"] == "boundary_conflict" and c["severity"] == "critical" and {37, 67} <= lines_of(c)
               for c in out["candidates"])
