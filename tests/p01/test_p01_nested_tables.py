"""№01, второй проход: GFM-таблица внутри нумерованного пункта списка («1. Комиссия»).

Фикстура ``nested_tables.md``: два раздела с одинаковым пунктом «1. Комиссия», под каждым после
пустой строки таблица с отступом пункта; «не более 10 000 ₸» повторяется в разных ячейках; в строке 23
эмодзи перед суммой, **жирный** и ``\\|`` внутри ячейки; в строках 27–31 тот же рисунок таблицы в
fenced-коде. На прежнем коде (d9742fb) строки таблицы теряли пункт (нет ``loc.parent``), а следующий
пункт «2.» начинал новый список.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from bcc_review.readers.text import Block, Document, parse_bytes, read_text, span_to_source, table_records

FIX = Path(__file__).parent / "fixtures"
NESTED = FIX / "nested_tables.md"
NESTED_SHA256 = "2ee7904b1deffe587b2c379e4c20ecbeb51668d9f1da1c4800ef416446fe770e"
GOLDEN_IDS = FIX / "ids_d9742fb.json"  # ID прежнего reader (d9742fb) на тех же фикстурах
PHRASE = "не более 10 000 ₸"
PART_A = ["Тарифы по картам", "Часть A. Дебетовые карты"]
PART_B = ["Тарифы по картам", "Часть B. Кредитные карты"]


def raw_lines(data: bytes) -> list[str]:
    """Строки сырого файла своим кодом, без reader."""
    return re.split(r"\r\n|\r|\n", data.decode("utf-8-sig"))


def line_byte_starts(data: bytes) -> list[int]:
    """Смещение в байтах начала каждой строки (BOM входит в строку 1)."""
    first = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    return [first] + [m.end() for m in re.finditer(rb"\r\n|\r|\n", data)]


def at(doc: Document, line: int) -> Block:
    (b,) = [b for b in doc.blocks if b.loc["line_start"] == line]
    return b


def map_only(block: Block) -> Block:
    """Тот же блок только с контрактным ``loc.map`` — как его увидит модуль без ``spans``."""
    return Block(block.id, block.kind, block.section, block.text,
                 {k: v for k, v in block.loc.items() if k != "spans"})


def cell_hits(doc: Document, phrase: str) -> list[dict]:
    """Запись «раздел, строка, ячейка, цитата» для каждого вхождения фразы в ячейку таблицы."""
    out = []
    for rec in table_records(doc):
        for cell in rec["cells"]:
            k = cell["value"].find(phrase)
            while k >= 0:
                out.append({"section": rec["section"], "line": rec["line"], "cell": cell["index"],
                            "column": cell["column"], "quote": phrase, "block_id": rec["block_id"],
                            "start": cell["start"] + k, "end": cell["start"] + k + len(phrase),
                            "parent": rec["parent"]})
                k = cell["value"].find(phrase, k + 1)
    return out


VARIANTS = {
    "lf": lambda d: d,
    "bom_crlf": lambda d: b"\xef\xbb\xbf" + d.replace(b"\n", b"\r\n"),
}


def test_fixture_bytes_are_pinned():
    data = NESTED.read_bytes()
    assert hashlib.sha256(data).hexdigest() == NESTED_SHA256 == read_text(NESTED).id
    assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")


def test_rows_under_numbered_rule_keep_section_line_cells_and_parent():
    doc = read_text(NESTED)
    lines = raw_lines(NESTED.read_bytes())
    rows = [b for b in doc.blocks if b.kind == "table_row"]
    assert [b.loc["line_start"] for b in rows] == [9, 10, 22, 23]
    for b in rows:
        rule = doc.block(b.loc["parent"])
        assert (rule.kind, rule.text, rule.loc["list"]["number"]) == ("list_item", "Комиссия", 1)
        assert rule.section == b.section == (PART_A if b.loc["line_start"] < 16 else PART_B)
        header = doc.block(b.loc["table"]["header_id"])
        assert header.loc["parent"] == rule.id
        assert [c["column"] for c in b.loc["cells"]] == ["Операция", "Условие", "Лимит"]
        # настоящая строка: отступ пункта и крайние «|» есть в файле, в text их нет
        raw = lines[b.loc["line_start"] - 1]
        assert raw.startswith("   | ") and not b.text.startswith(("|", " "))
        # обратная карта: якоря map совпадают со spans, каждый дословный отрезок — символы файла
        assert b.loc["map"] == [[t0, ln, c0] for t0, _t1, ln, c0, _c1, _k in b.loc["spans"]]
        for t0, t1, ln, c0, c1, kind in b.loc["spans"]:
            assert kind == "v" and ln == b.loc["line_start"]
            assert b.text[t0:t1] == lines[ln - 1][c0:c1]
    marked = at(doc, 23)
    assert marked.text == "Перевод на карту | 💳 не более 10 000 ₸ | карта | счёт"
    assert [marked.text[c["start"]:c["end"]] for c in marked.loc["cells"]] == [
        "Перевод на карту", "💳 не более 10 000 ₸", "карта | счёт"]
    assert marked.loc["map"] == [[0, 23, 5], [21, 23, 28], [38, 23, 47], [47, 23, 57]]


def test_same_phrase_in_two_sections_gives_two_distinct_records():
    doc = read_text(NESTED)
    hits = cell_hits(doc, PHRASE)
    assert [(h["section"][-1], h["line"], h["cell"], h["column"]) for h in hits] == [
        ("Часть A. Дебетовые карты", 9, 1, "Условие"),
        ("Часть A. Дебетовые карты", 10, 2, "Лимит"),
        ("Часть B. Кредитные карты", 22, 1, "Условие"),
        ("Часть B. Кредитные карты", 23, 1, "Условие"),
    ]
    # строки 9 и 22 текстуально одинаковы в этой ячейке: различают их только блок и раздел
    a, b = hits[0], hits[2]
    assert doc.block(a["block_id"]).text[:40] == doc.block(b["block_id"]).text[:40]
    assert (a["block_id"], a["parent"]) != (b["block_id"], b["parent"])
    lines = raw_lines(NESTED.read_bytes())
    for h in hits:
        block = doc.block(h["block_id"])
        assert block.text[h["start"]:h["end"]] == PHRASE
        (ln, c0, c1), = span_to_source(block, h["start"], h["end"])
        assert (ln, lines[ln - 1][c0:c1]) == (h["line"], PHRASE)


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_quote_in_second_section_restores_exact_raw_chars_and_bytes(variant, tmp_path):
    data = VARIANTS[variant](NESTED.read_bytes())
    path = tmp_path / "nested_tables.md"
    path.write_bytes(data)
    doc = read_text(path)
    row = at(doc, 23)
    assert row.section == PART_B

    quote = "💳 не более 10 000 ₸ | карта | счёт"  # видимый текст: эмодзи, жирный, \| сняты
    start = row.text.index(quote)
    end = start + len(quote)
    expected_raw = "💳 **не более 10 000 ₸** | карта \\| счёт"
    lines = raw_lines(data)
    starts = line_byte_starts(data)
    for block in (row, map_only(row)):
        (ln, c0, c1), = span_to_source(block, start, end)
        assert (ln, lines[ln - 1][c0:c1]) == (23, expected_raw)
        raw = lines[ln - 1]
        b0 = starts[ln - 1] + len(raw[:c0].encode())
        b1 = starts[ln - 1] + len(raw[:c1].encode())
        assert data[b0:b1].decode("utf-8") == expected_raw
    # границы блока в байтах — ровно строка 23 файла без её окончания
    eol = b"\r\n" if variant == "bom_crlf" else b"\n"
    assert data[row.loc["byte_start"]:row.loc["byte_end"]] == lines[22].encode()
    assert data[row.loc["byte_end"]:row.loc["byte_end"] + len(eol)] == eol
    assert [b.id for b in doc.blocks] == [b.id for b in read_text(NESTED).blocks]


def test_table_drawing_inside_fenced_code_stays_code():
    doc = read_text(NESTED)
    code = at(doc, 27)
    rule = doc.block(code.loc["parent"])
    assert (code.kind, code.loc["line_end"], code.loc["fence"]["closed"]) == ("code", 31, True)
    assert (rule.text, rule.loc["list"]["number"]) == ("Пример в коде", 2)
    assert code.text == ("| Операция | Условие | Лимит |\n| :--- | :--- | :--- |\n"
                         "| Перевод на карту | 💳 **не более 10 000 ₸** | карта \\| счёт |")
    assert not [b for b in doc.blocks if b.kind.startswith("table") and 27 <= b.loc["line_start"] <= 31]
    assert not [r for r in table_records(doc) if 27 <= r["line"] <= 31]
    assert [h["line"] for h in cell_hits(doc, PHRASE)] == [9, 10, 22, 23]  # строки 28–30 не факты

    top = parse_bytes(b"```\n| a | b |\n| - | - |\n| 1 | 2 |\n```\n", "md")
    assert [(b.kind, b.text) for b in top.blocks] == [("code", "| a | b |\n| - | - |\n| 1 | 2 |")]


def test_list_continues_after_nested_table():
    doc = read_text(NESTED)
    items = [b for b in doc.blocks if b.kind == "list_item"]
    assert [(b.loc["line_start"], b.loc["list"]["id"], b.loc["list"]["item"], b.loc["list"]["number"])
            for b in items] == [(5, 1, 1, 1), (12, 1, 2, 2), (18, 2, 1, 1), (25, 2, 2, 2)]
    assert at(doc, 14).loc["parent"] == at(doc, 12).id


@pytest.mark.parametrize("src, parent_line", [
    ("1. Комиссия\n   | a | b |\n   | - | - |\n   | 1 | 2 |\n", 1),            # без пустой строки
    ("10. Комиссия\n\n    | a | b |\n    | - | - |\n    | 1 | 2 |\n", 1),      # отступ пункта 4
    ("1. Правила\n   - Комиссия\n\n     | a | b |\n     | - | - |\n     | 1 | 2 |\n", 2),  # вложенный
    ("1. Комиссия\n\n\t| a | b |\n\t| - | - |\n\t| 1 | 2 |\n", 1),            # табуляция
], ids=["no_blank_line", "indent_4", "nested_item", "tab"])
def test_nested_table_variants_attach_to_their_item(src, parent_line):
    doc = parse_bytes(src.encode(), "md")
    rows = [b for b in doc.blocks if b.kind == "table_row"]
    assert len(rows) == 1 and rows[0].text == "1 | 2"
    assert doc.block(rows[0].loc["parent"]).loc["line_start"] == parent_line


def test_table_outdented_from_item_is_top_level_and_ends_the_list():
    doc = parse_bytes("1. Комиссия\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n2. Возврат\n".encode(), "md")
    row = next(b for b in doc.blocks if b.kind == "table_row")
    assert "parent" not in row.loc
    first, second = [b for b in doc.blocks if b.kind == "list_item"]
    assert first.loc["list"]["id"] != second.loc["list"]["id"]


def test_ids_of_unchanged_fixtures_match_previous_reader():
    golden = json.loads(GOLDEN_IDS.read_text(encoding="utf-8"))
    for name, rows in golden.items():
        doc = read_text(FIX / name)
        got = [[b.id, b.kind, b.loc["line_start"], b.loc["line_end"],
                hashlib.sha1(b.text.encode()).hexdigest()[:12]] for b in doc.blocks]
        assert got == rows, name
