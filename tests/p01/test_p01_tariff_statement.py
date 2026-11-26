"""Чтение тарифа (``fixtures/tariff_read.md``): метод в `коде` и отрицание доходят до агента одной фразой."""

from pathlib import Path

from bcc_review.engine import read_document
from bcc_review.readers.text import Block, source_lines, span_to_source
from bcc_review.runtime.context import render_block

FIXTURE = Path(__file__).parent / "fixtures" / "tariff_read.md"
LIMIT = "Лимит клиента этим методом не изменяется."  # короткая опора: метода в ней нет


def test_short_opora_restores_statement_with_method_and_negation(tmp_path):
    wrapped = tmp_path / "tariff_read.wrapped.md"  # редактор перенёс строку по пробелу внутри метода
    wrapped.write_bytes(FIXTURE.read_bytes().replace("`GET /api".encode(), "`GET\n   /api".encode()))
    item = f"Тариф карты читается методом GET /api/v1/tariffs/{{tariffId}}. {LIMIT}"
    cell = f"Тариф карты читается методом getTariffById. {LIMIT}"
    for path, bid, lines, statement in ((FIXTURE, "b0003", (5, 5), item), (FIXTURE, "b0005", (9, 9), cell),
                                         (wrapped, "b0003", (5, 6), item)):
        b = next(x for x in read_document(path)["blocks"] if x["id"] == bid)  # тот же путь, что у движка
        assert (b["loc"]["line_start"], b["loc"]["line_end"]) == lines
        assert f"[{bid}]" in render_block(b) and statement in render_block(b)  # это видит модель
        at = b["text"].index(LIMIT)  # опора «{block_id, start}» → её пункт или ячейка целиком
        part = next(((c["start"], c["end"]) for c in b["loc"].get("cells", []) if c["start"] <= at < c["end"]),
                    (0, len(b["text"])))
        assert b["text"][part[0]:part[1]] == statement
        src = source_lines(path.read_bytes())
        raw = " ".join(src[ln - 1][c0:c1] for ln, c0, c1 in span_to_source(Block(**b), *part))
        assert raw.replace("`", "") == statement  # диапазоны источника: снята только разметка кода
