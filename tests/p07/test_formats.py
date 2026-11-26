"""Evidence для каждого типа файла: координаты считает reader, а не модель.

Строка Markdown и страница PDF сверяются независимым чтением исходного файла.
"""

from __future__ import annotations

import json

import pytest
from p07_helpers import FIXTURES, block_with

from bcc_review.analysis.evidence import locate, resolve_hint


def resolved(doc: dict, block_id: str, quote: str) -> tuple[dict, dict]:
    res = resolve_hint(doc, {"block_id": block_id, "quote": quote})
    assert res["status"] == "matched", res
    ev = res["evidence"]
    block = next(b for b in doc["blocks"] if b["id"] == ev["block_id"])
    assert block["text"][ev["start"]:ev["end"]] == ev["quote"]
    return ev, locate(doc, ev)


@pytest.mark.parametrize(
    ("fragment", "quote", "line", "line_end"),
    [
        ("Ф-1.", "Ф-1. Держатель задаёт порог от 1 000 до 1 000 000 ₸ включительно", 5, 5),
        ("Знак", "Знак 𝟙 обозначает первичный лимит 50 000 ₸", 23, 23),
        ("Знак", "проверка выполняется по времени UTC+5", 23, 24),
        ("GET", "/alerts/saveLimit", 30, 30),
    ],
)
def test_markdown_line_and_column_from_reader(md_doc: dict, fragment: str, quote: str,
                                              line: int, line_end: int) -> None:
    ev, where = resolved(md_doc, block_with(md_doc, fragment), quote)
    assert (where["line"], where["line_end"]) == (line, line_end)
    # независимая сверка с исходным файлом по reader-координатам (loc.map): первый и последний символ
    raw_lines = (FIXTURES / "case.md").read_text(encoding="utf-8").split("\n")
    assert raw_lines[where["line"] - 1][where["col"]] == ev["quote"][0]
    assert raw_lines[where["line_end"] - 1][where["col_end"] - 1] == ev["quote"][-1]


@pytest.mark.parametrize(
    ("fragment", "quote", "page"),
    [
        ("Система", "проверку порога по времени UTC+5", 1),
        ("SMS", "не более 10 ₸", 1),
        ("более 100", "более 100 ₸ за операцию", 2),
    ],
)
def test_pdf_page_from_reader(pdf_doc: dict, fragment: str, quote: str, page: int) -> None:
    import pdfplumber

    ev, where = resolved(pdf_doc, block_with(pdf_doc, fragment), quote)
    assert where["page"] == where["page_end"] == page
    assert where["rects"] and all(len(rect) == 4 for rect in where["rects"])
    with pdfplumber.open(FIXTURES / "case.pdf") as pdf:
        assert ev["quote"] in pdf.pages[page - 1].extract_text()
        others = [p.extract_text() for i, p in enumerate(pdf.pages) if i != page - 1]
        for rect in where["rects"]:  # прямоугольник фрагмента действительно содержит текст опоры
            assert pdf.pages[page - 1].crop(rect).extract_text().strip()
    assert all(ev["quote"] not in text for text in others)


def test_pdf_hyphenation_keeps_literal(pdf_doc: dict) -> None:
    ev, where = resolved(pdf_doc, block_with(pdf_doc, "Система"), "проверку порога")
    assert ev["quote"] == "про-\nверку порога"
    assert len(where["rects"]) == 2  # опора на двух строках — два фрагмента


@pytest.mark.parametrize(
    ("fragment", "quote", "path"),
    [
        ("Ф-1.", "от 1 000 до 1 000 000 ₸ включительно", "body/p[3]"),
        ("максимум", "максимум один push за календарный месяц", "body/tbl[1]/tr[2]/tc[2]"),
    ],
)
def test_docx_path_from_reader(docx_doc: dict, fragment: str, quote: str, path: str) -> None:
    import docx

    ev, where = resolved(docx_doc, block_with(docx_doc, fragment), quote)
    assert where["path"] == path and where["part"] == "word/document.xml"
    d = docx.Document(str(FIXTURES / "case.docx"))
    if "/tbl[" in path:
        assert ev["quote"] in d.tables[0].cell(1, 1).text
    else:
        assert ev["quote"] in d.paragraphs[2].text


def test_map_from_contract_example() -> None:
    # блок b0003 из contracts/examples/minimal_report.json: «* **Ф-1.** На карту …» → «Ф-1. На карту …»
    doc = {"id": "x", "format": "markdown", "blocks": [{
        "id": "b0003", "kind": "list_item", "section": [], "loc": {"line_start": 4, "line_end": 4,
                                                                    "map": [[0, 4, 4], [4, 4, 10]]},
        "text": "Ф-1. На карту приходится максимум один push за календарный месяц."}]}
    _, where = resolved(doc, "b0003", "максимум один push за календарный месяц")
    assert (where["line"], where["col"], where["col_end"]) == (4, 31, 70)
    source = "* **Ф-1.** На карту приходится максимум один push за календарный месяц."
    assert source[31:70] == "максимум один push за календарный месяц"


def test_page_breaks_and_line_starts_inside_block() -> None:
    doc = {"id": "x", "format": "pdf", "blocks": [
        {"id": "p", "text": "конец страницы один начало страницы два", "section": [],
         "loc": {"page": 4, "page_breaks": [20], "line_start": 10, "line_starts": [0, 20]}}]}
    ev, where = resolved(doc, "p", "один начало")
    assert (where["page"], where["page_end"], where["line"], where["line_end"]) == (4, 5, 10, 11)
    assert where["label"] == "стр. 4–5, строки 10–11"


def test_one_evidence_example_per_format(md_doc: dict, pdf_doc: dict, docx_doc: dict, capsys) -> None:
    examples = {
        "md": resolved(md_doc, block_with(md_doc, "Знак"), "Знак 𝟙 обозначает первичный лимит 50 000 ₸"),
        "pdf": resolved(pdf_doc, block_with(pdf_doc, "Система"), "проверку порога по времени UTC+5"),
        "docx": resolved(docx_doc, block_with(docx_doc, "максимум"), "максимум один push за календарный месяц"),
    }
    with capsys.disabled():
        for fmt, (ev, where) in examples.items():
            print(f"\n[{fmt}] evidence = {json.dumps(ev, ensure_ascii=False)}  →  {where['label']}")
    assert set(examples) == {"md", "pdf", "docx"}
