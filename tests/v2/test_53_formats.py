"""№53: один документ в MD, PDF и DOCX читается одинаково — те же строки, виды блоков и разделы.

Фикстуры создаются прямо в тесте (свои маленькие документы, без текста официального ТЗ)."""
from __future__ import annotations

import importlib.util

import pytest

from bcc_review.v2 import docview as dv

needs_pdf = pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="нет pymupdf")
needs_docx = pytest.mark.skipif(importlib.util.find_spec("docx") is None, reason="нет python-docx")

MD = """# Card limits

## Statuses

### 403 Forbidden

A foreign card returns 404, the same as a missing card.
**404**

```json
{"message":"Card not found"}
```

### 500 Server error

```json
{"message":"Service error"}
```
"""


def _norm(view: dict) -> list[str]:
    return [" ".join(ln["text"].split()) for ln in view["lines"] if ln["text"].strip()]


def _by_text(view: dict) -> dict[str, dict]:
    return {" ".join(ln["text"].split()): ln for ln in view["lines"] if ln["text"].strip()}


def _pdf(path) -> None:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for text, font, size in [("Card limits", "hebo", 20), ("Statuses", "hebo", 16), ("403 Forbidden", "hebo", 13),
                             ("A foreign card returns 404, the same as a missing card.", "helv", 11),
                             ("404", "hebo", 13), ('{"message":"Card not found"}', "cour", 11),
                             ("500 Server error", "hebo", 13), ('{"message":"Service error"}', "cour", 11)]:
        page.insert_text((56, y), text, fontname=font, fontsize=size)
        y += size * 2.2
    doc.save(str(path))


def _docx(path, *, code_style: bool = False) -> None:
    import docx
    from docx.enum.style import WD_STYLE_TYPE
    d = docx.Document()
    d.add_heading("Card limits", 0)
    d.add_heading("Statuses", 1)
    d.add_heading("403 Forbidden", 2)
    p = d.add_paragraph("A foreign card returns 404, the same as a missing card.")
    p.add_run().add_break()
    p.add_run("404").bold = True
    style = d.styles.add_style("Source Code", WD_STYLE_TYPE.PARAGRAPH) if code_style else None
    for head, body in [(None, '{"message":"Card not found"}'), ("500 Server error", '{"message":"Service error"}')]:
        if head:
            d.add_heading(head, 2)
        if style is not None:
            d.add_paragraph(body, style=style)
        else:
            d.add_paragraph().add_run(body).font.name = "Consolas"
    d.save(str(path))


@needs_pdf
def test_pdf_letterless_bold_label_is_not_heading(tmp_path):
    _pdf(tmp_path / "s.pdf")
    v = dv.load(tmp_path / "s.pdf")
    lines = _by_text(v)
    assert lines["403 Forbidden"]["heading"]
    label = lines["404"]
    assert not label["heading"] and label["kind"] != "heading" and label["level"] == 0
    # метка и код под ней — в разделе ответа 403, как в Markdown, а не в «разделе 404»
    assert label["section"].endswith("403 Forbidden")
    assert lines['{"message":"Card not found"}']["section"].endswith("403 Forbidden")
    assert lines['{"message":"Service error"}']["section"].endswith("500 Server error")


def test_letterless_heading_demoted_keeps_previous_section():
    blocks = [
        {"id": "b1", "kind": "heading", "text": "Statuses", "section": ["Statuses"]},
        {"id": "b2", "kind": "heading", "text": "403 Forbidden", "section": ["Statuses", "403 Forbidden"]},
        {"id": "b3", "kind": "paragraph", "text": "Foreign card.", "section": ["Statuses", "403 Forbidden"]},
        {"id": "b4", "kind": "heading", "text": "404", "section": ["Statuses", "404"], "level": 3,
         "loc": {"level": 3}},
        {"id": "b5", "kind": "code", "text": "{}", "section": ["Statuses", "404"]},
        {"id": "b6", "kind": "heading", "text": "500 Server error", "section": ["Statuses", "500 Server error"]},
        {"id": "b7", "kind": "heading", "text": "2.1", "section": ["Statuses", "500 Server error", "2.1"]},
        {"id": "b8", "kind": "paragraph", "text": "x", "section": ["Statuses", "500 Server error", "2.1", "Sub"]},
    ]
    out = dv._demote_letterless_headings(blocks)
    assert [b["kind"] for b in out] == ["heading", "heading", "paragraph", "paragraph", "code", "heading",
                                        "paragraph", "paragraph"]
    assert out[3]["section"] == out[4]["section"] == ["Statuses", "403 Forbidden"]
    assert "level" not in out[3] and "level" not in out[3]["loc"]
    assert out[5]["section"] == ["Statuses", "500 Server error"]
    assert out[7]["section"] == ["Statuses", "500 Server error", "Sub"]


@needs_docx
@pytest.mark.parametrize("code_style", [False, True])
def test_docx_monospace_paragraph_is_code(tmp_path, code_style):
    _docx(tmp_path / "s.docx", code_style=code_style)
    lines = _by_text(dv.load(tmp_path / "s.docx"))
    assert lines['{"message":"Card not found"}']["kind"] == "code"
    assert lines['{"message":"Service error"}']["kind"] == "code"
    assert lines["A foreign card returns 404, the same as a missing card."]["kind"] == "paragraph"
    assert lines["404"]["kind"] == "paragraph" and not lines["404"]["heading"]


@needs_docx
def test_docx_mixed_fonts_paragraph_stays_text(tmp_path):
    import docx
    d = docx.Document()
    d.add_heading("API", 1)
    p = d.add_paragraph("The field ")
    p.add_run("amount").font.name = "Consolas"
    p.add_run(" is an integer.")
    d.save(str(tmp_path / "m.docx"))
    lines = _by_text(dv.load(tmp_path / "m.docx"))
    assert lines["The field amount is an integer."]["kind"] == "paragraph"


@needs_pdf
@needs_docx
def test_same_document_three_formats_same_lines(tmp_path):
    (tmp_path / "s.md").write_text(MD, encoding="utf-8")
    _pdf(tmp_path / "s.pdf")
    _docx(tmp_path / "s.docx")
    views = {e: dv.load(tmp_path / f"s.{e}") for e in ("md", "pdf", "docx")}
    texts = {e: _norm(v) for e, v in views.items()}
    assert texts["pdf"] == texts["md"] == texts["docx"]
    for e in ("pdf", "docx"):
        for a, b in zip(views["md"]["lines"] and [x for x in views["md"]["lines"] if x["text"].strip()],
                        [x for x in views[e]["lines"] if x["text"].strip()]):
            assert (a["kind"] == "code") == (b["kind"] == "code"), (e, a["text"])
            assert a["heading"] == b["heading"], (e, a["text"])
            assert a["section"].split(dv.SECTION_SEP)[-1] == b["section"].split(dv.SECTION_SEP)[-1], (e, a["text"])



def _pdf_rows(path, rows) -> None:
    """PDF по рядам [(отступ сверху, html ряда), …]: каждый ряд — своя строка у того же левого края, шрифты MuPDF
    со всей Юникод-таблицей (тире, маркеры), ``<code>`` — моноширинный."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for gap, html in rows:
        y += gap
        page.insert_htmlbox(pymupdf.Rect(56, y, 560, y + 16), f'<p style="font-size:11px;margin:0">{html}</p>')
        y += 14
    doc.save(str(path))


BODY = '{"message":"The card is not found here","amount":2000}'


@needs_pdf
def test_pdf_inline_code_in_sentence_is_text(tmp_path):
    _pdf_rows(tmp_path / "c.pdf", [(0, "<b>Card API</b>"), (6, f"Reply 200: <code>{BODY}</code>."),
                                   (10, f"<code>{BODY}</code>")])
    lines = [ln for ln in dv.load(tmp_path / "c.pdf")["lines"] if ln["text"].strip()]
    prose = next(ln for ln in lines if ln["text"].startswith("Reply 200"))
    code = next(ln for ln in lines if ln["text"].startswith('{"message"'))
    assert prose["kind"] == "paragraph"      # вставка кода в фразе — текст, как `…` в Markdown
    assert code["kind"] == "code"            # строка целиком моноширинным — код


@needs_pdf
def test_pdf_line_wrapped_before_dash_continues_sentence(tmp_path):
    _pdf_rows(tmp_path / "d.pdf", [
        (0, "<b>Rules</b>"),
        (6, "\u2022 R-7. After blocking the client gets a push with the card mask NNNN, where NNNN"),
        (0, "\u2014 the last four digits of the card number."),
        (6, "\u2022 R-8. The list of states:"), (0, "\u2014 active;"), (0, "\u2014 blocked."),
    ])
    texts = [" ".join(ln["text"].split()) for ln in dv.load(tmp_path / "d.pdf")["lines"] if ln["text"].strip()]
    assert "R-7. After blocking the client gets a push with the card mask NNNN, where NNNN \u2014 the last four " \
           "digits of the card number." in texts, texts
    # перечень после двоеточия — по-прежнему отдельные пункты
    assert texts[-3:] == ["R-8. The list of states:", "\u2014 active;", "\u2014 blocked."], texts


def test_pdf_repeated_table_header_on_new_page_dropped():
    def ln(n, text, kind, page):
        return {"n": n, "text": text, "kind": kind, "page": page, "section": "M", "heading": False, "level": 0}
    lines = [ln(1, "Field | Value", "table_header", 1), ln(2, "Type | POST", "table_row", 1),
             ln(3, "Field | Value", "table_header", 2), ln(4, "Body | JSON", "table_row", 2),
             ln(5, "Text after.", "paragraph", 2), ln(6, "Field | Value", "table_header", 3),
             ln(7, "Type | GET", "table_row", 3)]
    out, n = dv._drop_repeated_headers(lines)
    assert n == 1
    assert [x["text"] for x in out] == ["Field | Value", "Type | POST", "Body | JSON", "Text after.", "Field | Value",
                                        "Type | GET"]
    assert [x["n"] for x in out] == list(range(1, 7))


CORPUS = __import__("pathlib").Path(__file__).resolve().parents[2] / "evaluation" / "dev" / "corpus" / "cases"


@needs_pdf
@needs_docx
@pytest.mark.parametrize("case", sorted(p.parent.name for p in CORPUS.glob("*/source.pdf")
                                        if (p.parent / "source.docx").is_file() and (p.parent / "source.md").is_file()))
def test_corpus_three_formats_read_alike(case, capsys):
    from evaluation.v2 import formats
    d = CORPUS / case
    assert formats.reading_diff([d / "source.md", d / "source.pdf", d / "source.docx"]) == 0, capsys.readouterr().out
