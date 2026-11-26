"""read_docx: порядок, строки таблиц с ячейками, loc с частью OOXML, путём и runs."""

from __future__ import annotations

import hashlib

import pytest
from p03_fixtures import CYR_TEXT, PHRASE, bold_quote_doc, cyrillic_doc, repeated_phrase_doc, rich_doc

from bcc_review.contracts import BLOCK_KINDS, validate
from bcc_review.readers.docx import ROW_SEPARATOR, DocxReadError, locate, read_docx


def test_document_matches_contract_and_ids(tmp_path):
    path = bold_quote_doc(tmp_path / "a.docx")
    doc = read_docx(path)
    validate(doc.to_dict(), "Document")
    assert doc.id == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (doc.format, doc.source_name, doc.title) == ("docx", "a.docx", "Функциональные требования")
    assert [b.id for b in doc.blocks] == ["b0001", "b0002", "b0003"]
    assert [b.loc["ref"] for b in doc.blocks] == ["p1", "p2", "p3"]
    assert [b.kind for b in doc.blocks] == ["heading", "paragraph", "paragraph"]
    assert doc.blocks[1].section == ["Функциональные требования"]


def test_quote_across_bold_and_normal_runs_is_mapped(tmp_path):
    b = read_docx(bold_quote_doc(tmp_path / "a.docx")).by_ref("p2")
    loc = b.loc
    assert (loc["part"], loc["path"], loc["anchor"]) == ("word/document.xml", "/w:document/w:body/w:p[2]", "paragraph")
    runs = loc["runs"]
    assert runs[0] == {"path": "/w:document/w:body/w:p[2]/w:r[1]", "start": 0, "end": 5, "fmt": ["b"]}
    assert runs[1]["path"].endswith("/w:p[2]/w:r[2]") and runs[1]["start"] == 5 and "fmt" not in runs[1]
    quote = "Ф-2. Месяц определяется"
    s = b.text.index(quote)
    covered = [r for r in runs if r["start"] < s + len(quote) and r["end"] > s]
    assert [r.get("fmt", []) for r in covered] == [["b"], []]
    assert "".join(b.text[r["start"]:r["end"]] for r in runs) == b.text


def test_real_order_rows_and_cells(tmp_path):
    doc = read_docx(repeated_phrase_doc(tmp_path / "r.docx"))
    assert [(b.loc["ref"], b.kind) for b in doc.blocks] == [
        ("p1", "heading"), ("p2", "paragraph"), ("t1.r1", "table_header"), ("t1.r2", "table_row"), ("p3", "paragraph")]
    assert all(b.kind in BLOCK_KINDS for b in doc.blocks)
    row = doc.by_ref("t1.r2")
    assert row.text == f"amount{ROW_SEPARATOR}Клиент задаёт {PHRASE}."
    assert row.section == ["Ф-1. Порог"]
    loc = row.loc
    assert (loc["anchor"], loc["path"]) == ("row", "/w:document/w:body/w:tbl[1]/w:tr[2]")
    t = loc["table"]
    assert (t["ref"], t["row"], t["rows"], t["cols"], t["columns"], t["header_row"]) == \
        ("t1", 2, 2, 2, ["Параметр", "Правило"], False)
    assert doc.by_ref("t1.r1").loc["table"]["header_row_source"] == "first_row"
    c2 = loc["cells"][1]
    assert c2["ref"] == "t1.r2.c2" and c2["path"] == "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]"
    assert row.text[c2["start"]:c2["end"]] == f"Клиент задаёт {PHRASE}."
    assert c2["column_header"] == "Правило" and c2["label"] == "Таблица 1, строка 2, столбец 2 «Правило»"
    assert loc["paragraphs"] == [
        {"path": "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[1]/w:p[1]", "start": 0, "end": 6, "cell": 1},
        {"path": "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]/w:p[1]", "start": 9, "end": c2["end"], "cell": 2}]
    s = row.text.index(PHRASE)
    place = locate(row, s, s + len(PHRASE))
    assert (place["anchor"], place["ref"], place["cell"]["col"]) == ("cell", "t1.r2.c2", 2)
    whole = locate(row.to_dict(), 0, len(row.text))  # dict из report.json тоже подходит
    assert (whole["anchor"], whole["ref"]) == ("row", "t1.r2")
    assert [b.loc["order"] for b in doc.blocks] == list(range(1, 6))
    assert any(w["code"] == "docx_existing_comments" for w in doc.warnings)


def test_codepoint_offsets_with_non_bmp_and_cyrillic(tmp_path):
    b = read_docx(cyrillic_doc(tmp_path / "c.docx")).by_ref("p2")
    assert b.text == CYR_TEXT
    italic = [r for r in b.loc["runs"] if r.get("fmt") == ["i"]][0]
    assert b.text[italic["start"]:italic["end"]] == "возврат уменьшает"
    assert b.text.index("Ф-2") == 2  # 🙂 -- одна кодовая точка (в UTF-16 было бы две)


def test_rich_elements(tmp_path):
    doc = read_docx(rich_doc(tmp_path / "rich.docx"))
    validate(doc.to_dict(), "Document")
    by_text = {b.text: b for b in doc.blocks}
    link = by_text["Текст до гиперссылки и после."].loc["runs"]
    assert [r["path"].rsplit("/w:p[3]/", 1)[1] for r in link] == ["w:r[1]", "w:hyperlink[1]/w:r[1]", "w:r[2]"]
    assert by_text["Текст в элементе управления"].loc["path"].endswith("/w:sdt[1]/w:sdtContent/w:p[1]")
    fld = by_text["См. Ф-3 и критерий 2."]
    assert [r.get("field", False) for r in fld.loc["runs"]] == [False, True, False]
    assert "Порог новый сохраняется." in by_text  # w:del исключён, w:ins учтён
    assert by_text["Галочка  отмечена"].loc["runs"][0]["atomic"] is True
    assert "Первая строка\nвторая строка\tпосле табуляции" in by_text
    # горизонтальное объединение: одна ячейка на 2 столбца сетки; две строки в ячейке
    row = by_text[f"amount, integer{ROW_SEPARATOR}Порог в тенге\nВторая строка ячейки"]
    c1, c3 = row.loc["cells"]
    assert (c1["ref"], c1["col_span"], c3["ref"], c3["column_header"]) == ("t1.r3.c1", 2, "t1.r3.c3", "Описание")
    assert [p["cell"] for p in row.loc["paragraphs"]] == [1, 2, 2]
    assert row.loc["paragraphs"][2]["path"].endswith("/w:tr[3]/w:tc[2]/w:p[2]")
    # вертикальное объединение
    top = by_text[f"400{ROW_SEPARATOR}Некорректный запрос"].loc["cells"][0]
    assert (top["vmerge"], top["row_span"]) == ("restart", 2)
    cont = by_text[f"{ROW_SEPARATOR}Проверьте сумму"].loc["cells"][0]
    assert (cont["vmerge"], cont["merged_into"], cont["start"], cont["end"]) == ("continue", "t2.r2.c1", 0, 0)
    # вложенная таблица идёт после строки-родителя; таблица из одной строки -- без шапки
    outer = by_text[f"Внешняя ячейка{ROW_SEPARATOR}"]
    nested = by_text["Вложенная ячейка"]
    assert outer.kind == nested.kind == "table_row"
    assert doc.blocks.index(nested) == doc.blocks.index(outer) + 1
    assert nested.loc["ref"] == "t3.r1.c2.t1.r1" and nested.loc["table"]["parent_ref"] == "t3.r1.c2"
    assert nested.loc["path"] == "/w:document/w:body/w:tbl[3]/w:tr[1]/w:tc[2]/w:tbl[1]/w:tr[1]"
    assert "вложенная таблица 1" in nested.loc["label"]
    # автонумерация
    assert by_text["Шаг один"].loc["list"]["label"] == "1."
    assert (by_text["Шаг два"].loc["list"]["label"], by_text["Шаг два"].kind) == ("2.", "list_item")
    # текстовое поле и сноска -- отдельные блоки сразу после хозяина
    host = by_text["Перед рамкой "]
    box = by_text["Текст в рамке"]
    assert (box.loc["anchor"], box.loc["ref"], box.loc["host"]["block_id"]) == ("textbox", "p9.tb1", host.id)
    note = by_text[" Курс пересчёта тиынов не определён."]
    assert (note.loc["anchor"], note.loc["part"], note.loc["ref"]) == ("note", "word/footnotes.xml", "fn1")
    assert note.loc["path"] == "/w:footnotes/w:footnote[3]" and note.loc["paragraphs"][0]["path"].endswith("/w:p[1]")
    assert doc.blocks[doc.blocks.index(note) - 1].text == "Порог хранится в тенге без копеек."
    # формула OMML входит текстом и помечена как неделимая
    math = by_text["Условие 1000≤x≤1000000 проверяется на сервере."]
    assert [r.get("math", False) for r in math.loc["runs"]] == [False, True, False]
    # подсказка страницы по w:lastRenderedPageBreak
    assert by_text["На второй странице"].loc["page_hint"] == 2 and by_text["Шаг два"].loc["page_hint"] == 1
    codes = {w["code"] for w in doc.warnings}
    assert {"docx_header_footer", "docx_images", "docx_math", "docx_tracked_changes", "docx_fields"} <= codes
    assert "partial_read" not in codes
    assert doc.title == "Документ"
    assert doc.by_ref("p2").kind == "heading" and doc.by_ref("p2").section == ["Документ", "1. Общие сведения"]


def test_ole_and_garbage_inputs_raise_readable_errors(tmp_path):
    ole = tmp_path / "old.doc"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    with pytest.raises(DocxReadError, match="OLE"):
        read_docx(ole)
    junk = tmp_path / "junk.docx"
    junk.write_text("не zip", encoding="utf-8")
    with pytest.raises(DocxReadError, match="ZIP"):
        read_docx(junk)


def test_reader_is_deterministic(tmp_path):
    path = rich_doc(tmp_path / "rich.docx")
    assert read_docx(path).to_dict() == read_docx(path).to_dict()
