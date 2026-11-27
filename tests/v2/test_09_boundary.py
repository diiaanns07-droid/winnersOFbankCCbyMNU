"""№09: шаг 2б — граничные значения на записанных ответах живых моделей (без сети).

Мутанты `range_boundary` корпуса и их чистые близнецы различаются одним словом границы:
* «не выше лимита» ↔ строка приёмки «баланс равен лимиту → пополнения нет» — конфликт;
* «меньше 10 000» ↔ строка приёмки «итог 10 000» — конфликт; в базе «не превышает 10 000» — совместимо;
* «не превысит» ↔ «достигла бы или превысила бы — отказ» — конфликт двух требований; в базе только «превысила бы».

Ответы записаны прогоном `claude -p` с промптом `prompts/consistency.md` (шаг 2б), нарезка — эвристика по пунктам.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2.stages import consistency as C
from test_09_recorded import load_view

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "09_boundary"
CORPUS = ROOT / "evaluation" / "dev" / "corpus" / "cases"


def recorded(case: str) -> list[tuple[str, str]]:
    return [(case, p.stem.split(".", 1)[1]) for p in sorted((FIX / case).glob("consistency.*.json"))]


def run(case: str, model: str) -> dict:
    view = load_view(CORPUS / case / "source.md")
    reqs = json.loads((FIX / case / "segment.json").read_text(encoding="utf-8"))["requirements"]
    raw = json.loads((FIX / case / f"consistency.{model}.json").read_text(encoding="utf-8"))
    return C.postprocess(raw, view, reqs)


def lines_of(c: dict) -> set[int]:
    return {e["line"] for e in c["evidence"] if e.get("verified") != "missing"}


# мутант → строки обеих сторон конфликта по метке корпуса
MUTANTS = {
    "autopay.range_boundary.trigger_at_threshold": {27, 46},
    "cashback.range_boundary.cap_strict": {28, 48},
    "transfer_limit.range_boundary.reaching_rejects": {25, 26},
}
TWINS = {"cashback.base": 28, "transfer_limit.base": 26}


@pytest.mark.parametrize("case,model", [x for c in MUTANTS for x in recorded(c)])
def test_boundary_mutant_gives_one_critical_boundary_conflict(case, model):
    out = run(case, model)
    want = MUTANTS[case]
    hits = [c for c in out["candidates"] if want <= lines_of(c)]
    assert hits, [c["title"] for c in out["candidates"]]
    c = hits[0]
    assert c["origin"] == "pair_check" and c["kind"] == "boundary_conflict" and c["severity"] == "critical"
    # одна граница — одно замечание: пары про ту же строку склеены
    assert len([x for x in out["candidates"] if x["kind"] == "boundary_conflict"]) == 1


@pytest.mark.parametrize("case,model", [x for c in TWINS for x in recorded(c)])
def test_clean_twin_has_no_conflict_on_the_same_boundary(case, model):
    out = run(case, model)
    assert [p for p in out["pair_checks"] if p["verdict"] == "conflict"] == []
    assert [c for c in out["candidates"] if c["severity"] == "critical"] == []
    line = TWINS[case]
    assert not [c for c in out["candidates"] if c["kind"] in C.CONFLICT_KINDS and line in lines_of(c)]
