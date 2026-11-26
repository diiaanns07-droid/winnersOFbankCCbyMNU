"""Стык №01 → №07 на таблице внутри пункта списка.

Использует опубликованный модуль №07 (``bcc_review.analysis.evidence``: ``resolve_hint``, ``locate``)
и нормализацию стыка движка (``contracts.normalize_document``). Если модуля №07 в checkout нет
(ветка от контракта без среза интеграции), тест пропускается с причиной.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bcc_review.readers.text import read_text

evidence = pytest.importorskip("bcc_review.analysis.evidence", reason="модуль №07 не в этом checkout")
contracts = pytest.importorskip("bcc_review.contracts")

NESTED = Path(__file__).parent / "fixtures" / "nested_tables.md"


def _doc() -> dict:
    doc = read_text(NESTED).to_dict()
    normalize = getattr(contracts, "normalize_document", None)
    return normalize(doc) if normalize else doc


def _row(doc: dict, line: int) -> dict:
    (b,) = [b for b in doc["blocks"] if b["loc"]["line_start"] == line]
    return b


def test_p07_locates_quote_from_nested_table_in_raw_file():
    doc = _doc()
    row = _row(doc, 23)
    res = evidence.resolve_hint(doc, {"block_id": row["id"], "quote": "💳 не более 10 000 ₸ | карта | счёт"})
    assert res["status"] == "matched"
    place = evidence.locate(doc, res["evidence"])
    assert (place["line"], place["line_end"], place["section"][-1]) == (23, 23, "Часть B. Кредитные карты")
    raw = re.split(r"\r\n|\r|\n", NESTED.read_text(encoding="utf-8"))[22]
    assert raw[place["col"]:place["col_end"]] == "💳 **не более 10 000 ₸** | карта \\| счёт"
    assert row["loc"]["parent"] == _row(doc, 18)["id"]  # пункт «1. Комиссия» части B


def test_p07_needs_block_binding_for_phrase_repeated_in_both_sections():
    doc = _doc()
    phrase = "не более 10 000 ₸ в сутки"
    assert evidence.resolve_hint(doc, {"block_id": None, "quote": phrase})["status"] == "ambiguous"
    for line, part in ((9, "Часть A. Дебетовые карты"), (22, "Часть B. Кредитные карты")):
        res = evidence.resolve_hint(doc, {"block_id": _row(doc, line)["id"], "quote": phrase})
        place = evidence.locate(doc, res["evidence"])
        assert (res["status"], place["line"], place["section"][-1]) == ("matched", line, part)


def test_p07_residual_ambiguity_same_number_twice_in_one_line():
    """Строка 14 ``limit_spec``: «50 000 ₸» дважды в одном блоке — block_id не разрешает, нужен контекст."""
    for name in ("limit_spec.lf.md", "limit_spec.crlf_bom.md"):
        doc = read_text(Path(__file__).parent / "fixtures" / name).to_dict()
        normalize = getattr(contracts, "normalize_document", None)
        doc = normalize(doc) if normalize else doc
        block = _row(doc, 14)
        bare = evidence.resolve_hint(doc, {"block_id": block["id"], "quote": "50 000 ₸"})
        assert (bare["status"], bare["reason"]) == ("ambiguous", "multiple_occurrences")
        res = evidence.resolve_hint(doc, {"block_id": block["id"], "quote": "50 000 ₸", "before": "лимит "})
        place = evidence.locate(doc, res["evidence"])
        assert (res["status"], place["line"], place["col"], place["col_end"]) == ("matched", 14, 52, 60)
