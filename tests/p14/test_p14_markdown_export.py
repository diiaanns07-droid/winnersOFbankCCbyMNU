"""Производный PDF из русского Markdown: ₸, таблицы, переносы, карта строк, аннотации."""

from __future__ import annotations

import json

import pymupdf
import pytest

import p14_fixtures as fx
from p14_helpers import by_finding, close
from bcc_review.exports.pdf import (
    MANIFEST_NAME,
    MissingGlyphError,
    UnsupportedFormatError,
    _MdRenderer,
    export_pdf,
    missing_glyphs,
    page_label,
    read_annotations,
    verify_export,
)


@pytest.fixture(scope="module")
def annots(exported_md):
    return read_annotations(exported_md.output_path)


def _page_of(result, line: int) -> int:
    return [e["page"] for e in result.line_map[str(line)] if not e.get("repeated") and e.get("page")][0]


def test_readable_russian_pdf_with_tenge(exported_md):
    assert exported_md.missing_glyphs == [] and exported_md.warnings == []
    with pymupdf.open(exported_md.output_path) as d:
        text = " ".join(d[0].get_text().split())
        for s in ("₸", "Уведомление о расходах по карте", "Әә Іі Ңң Ғғ Үү Ұұ Ққ Өө Һһ", "«кавычки»", "№ 5"):
            assert s in text, s
        fonts = {f[3] for p in d for f in p.get_fonts()}
    assert {"Noto Sans Regular", "Noto Sans Bold"} <= fonts, fonts


def test_export_pages_are_labelled_and_origin_stated(exported_md, case_md):
    with pymupdf.open(exported_md.output_path) as d:
        n = d.page_count
        assert n >= 2
        assert [page_label(d, i) for i in range(n)] == [f"Экспорт-{i + 1}" for i in range(n)]
        for i in range(n):
            assert f"Страница экспорта {i + 1} из {n}" in d[i].get_text()
        first = d[0].get_text()
        assert "Производная PDF-версия для чтения — это не исходный документ" in first
        assert fx.sha256(case_md) in first.replace("\n", "")
        assert fx.sha256(case_md) in d.metadata["keywords"]


def test_line_map_covers_source_lines(exported_md, case_md):
    lines = case_md.read_text(encoding="utf-8").splitlines()
    for i, s in enumerate(lines, 1):
        assert str(i) in exported_md.line_map, f"строка {i} не попала в карту"
        entries = exported_md.line_map[str(i)]
        if s.strip() and not s.startswith("```") and not set(s.replace("|", "").strip()) <= set(":- "):
            assert any(e.get("page") for e in entries), f"строка {i} не размещена"
    merged = [b for b in exported_md.block_map.values() if b["lines"] == [9, 10]]
    assert merged and merged[0]["pages"] == [1]


def test_gutter_prints_source_line_numbers(exported_md, md_report):
    ln = md_report["_lines"]["f1"]
    page = _page_of(exported_md, ln)
    rect = pymupdf.Rect(exported_md.line_map[str(ln)][0]["rect"])
    with pymupdf.open(exported_md.output_path) as d:
        gutter = d[page - 1].get_textbox(pymupdf.Rect(0, rect.y0, _MdRenderer.X0 - 1, rect.y1)).strip()
    assert gutter == str(ln)


def test_highlight_matches_rendered_words(annots, exported_md, md_report):
    (h,) = by_finding(annots, "F-01")
    ln = md_report["_lines"]["f1"]
    assert h["page"] == _page_of(exported_md, ln)
    with pymupdf.open(exported_md.output_path) as d:
        words = d[h["page"] - 1].get_text("words")
    seq = ["от", "1", "000", "до", "1", "000", "000", "₸"]
    for i in range(len(words)):
        if [w[4] for w in words[i : i + len(seq)]] == seq:
            want = pymupdf.Rect(words[i][:4]) | pymupdf.Rect(words[i + len(seq) - 1][:4])
            break
    else:
        raise AssertionError("фраза не найдена в PDF")
    assert len(h["quads"]) == 1 and close(h["quads"][0], want)


def test_identical_phrase_second_occurrence(annots, exported_md, md_report):
    (h,) = by_finding(annots, "F-03")
    dup, first = md_report["_lines"]["dup"], md_report["_lines"]["f2"]
    p_dup, p_first = _page_of(exported_md, dup), _page_of(exported_md, first)
    assert p_dup != p_first, "фикстура должна разносить фразы по разным страницам"
    assert h["page"] == p_dup
    line_rect = pymupdf.Rect(exported_md.line_map[str(dup)][0]["rect"])
    q = pymupdf.Rect(h["quads"][0])
    assert line_rect.y0 - 0.5 <= q.y0 and q.y1 <= line_rect.y1 + 0.5


def test_multiline_quote_spans_two_source_lines(annots, exported_md, md_report):
    (h,) = by_finding(annots, "F-04")
    assert len(h["quads"]) == 2
    ln = md_report["_lines"]["f3"]
    r1 = pymupdf.Rect(exported_md.line_map[str(ln)][-1]["rect"])
    r2 = pymupdf.Rect(exported_md.line_map[str(ln + 1)][0]["rect"])
    q1, q2 = (pymupdf.Rect(q) for q in h["quads"])
    assert abs(q1.y0 - r1.y0) < 0.5 and abs(q2.y0 - r2.y0) < 0.5


def test_conflict_sides_on_different_pages_are_linked(annots, exported_md):
    a = [x for x in by_finding(annots, "F-02") if ":a:" in x["name"]]
    b = [x for x in by_finding(annots, "F-02") if ":b:" in x["name"]]
    assert a and b and a[0]["page"] != b[0]["page"]
    assert f"стр. экспорта {b[0]['page']}" in a[0]["content"] and f"стр. экспорта {a[0]['page']}" in b[0]["content"]
    links = [x for x in annots if x["type"] == "Link"]
    assert {(x["page"], x["to_page"]) for x in links} >= {(a[0]["page"], b[0]["page"]), (b[0]["page"], a[0]["page"])}


def test_long_table_breaks_with_repeated_header(exported_md, md_report):
    lm = exported_md.line_map
    rows = [i for i in range(22, 22 + fx.MARKDOWN_ROWS)]
    pages = {_page_of(exported_md, r) for r in rows}
    assert len(pages) >= 2, "таблица должна переходить на следующую страницу"
    assert any(e.get("repeated") for e in lm["20"]), "шапка таблицы не повторена"
    for r in rows:
        assert len([e for e in lm[str(r)] if not e.get("repeated")]) >= 1
    row30 = md_report["_lines"]["row30"]
    logic_cell = [e for e in lm[str(row30)] if not e.get("repeated")]
    ys = {round(e["rect"][1]) for e in logic_cell}
    assert len(ys) >= 3, "длинная ячейка должна переноситься на несколько строк"


def test_long_unbreakable_token_stays_inside_column(exported_md, md_report):
    ln = md_report["_lines"]["row12"]
    for e in exported_md.line_map[str(ln)]:
        r = pymupdf.Rect(e["rect"])
        assert r.x0 >= _MdRenderer.X0 - 0.01 and r.x1 <= _MdRenderer.X1 + 0.01


def test_needs_review_label(annots):
    lbl = by_finding(annots, "F-05", "FreeText")
    assert lbl and "на проверке" in lbl[0]["content"] and "СУЩЕСТВЕННО" in lbl[0]["content"]


def test_unconfirmed_md_evidence_skipped(exported_md):
    pl = [p for p in exported_md.placements if p.finding_id == "F-07"][0]
    assert pl.status == "skipped" and "не подтверждена" in pl.reason


def test_verify_and_hash(exported_md, case_md, md_report):
    assert fx.sha256(case_md) == md_report["document"]["id"]
    res = verify_export(exported_md.output_path, case_md, md_report)
    assert res["ok"], res["errors"]
    with pymupdf.open(exported_md.output_path) as d:
        m = json.loads(d.embfile_get(MANIFEST_NAME))
    assert m["mode"] == "derived_from_markdown" and m["line_map"]["1"][0]["page"] == 1


def test_missing_glyph_is_detected(tmp_path):
    assert missing_glyphs("Порог 50 000 ₸ Әә") == []
    assert missing_glyphs("漢 ₸ ▲") == ["漢", "▲"]
    md = tmp_path / "cjk.md"
    md.write_text("# Тест\n\nЗнак 漢 отсутствует в Noto Sans, ₸ есть.\n", encoding="utf-8")
    rep = fx.report_for(md, "md")
    with pytest.raises(MissingGlyphError) as ei:
        export_pdf(rep, md, tmp_path / "strict.pdf", strict_glyphs=True)
    assert ei.value.missing == ["漢"]
    res = export_pdf(rep, md, tmp_path / "lenient.pdf")
    assert res.missing_glyphs == ["漢"] and res.unrendered_glyphs == ["漢"]
    assert any("U+6F22" in w for w in res.warnings)


def test_arrows_use_pinned_fallback_font(tmp_path):
    """В кейсе есть «→»: Noto Sans его не содержит, экспорт это выявляет и набирает Noto Sans Math."""
    md = tmp_path / "arrows.md"
    md.write_text("# Схема\n\nПриложение → сервис настроек → push; 1 000 ≤ порог ≤ 1 000 000 ₸\n", encoding="utf-8")
    res = export_pdf(fx.report_for(md, "md"), md, tmp_path / "arrows.pdf", strict_glyphs=True)
    assert res.missing_glyphs == ["→", "≤"] and res.fallback_glyphs == ["→", "≤"] and res.unrendered_glyphs == []
    assert any("Noto Sans Math" in w for w in res.warnings)
    with pymupdf.open(res.output_path) as d:
        spans = [s for b in d[0].get_text("dict")["blocks"] if b["type"] == 0
                 for line in b["lines"] for s in line["spans"]]
        arrow_fonts = {s["font"] for s in spans if "→" in s["text"]}
        assert arrow_fonts and all("NotoSansMath" in f for f in arrow_fonts), arrow_fonts
        assert "Приложение → сервис настроек → push" in " ".join(d[0].get_text().split())
        fonts = {f[3] for p in d for f in p.get_fonts()}
    assert fonts == {"Noto Sans Regular", "Noto Sans Bold", "Noto Sans Math Regular"}, fonts
    assert res.output_path.stat().st_size < 120_000, "резервный шрифт должен встраиваться подмножеством"


def test_plain_text_input(tmp_path):
    txt = tmp_path / "spec.txt"
    txt.write_text("Строка 1: порог 50 000 ₸\n**не разметка** в TXT\n", encoding="utf-8")
    finding = fx._finding("F-01", "minor", "t", [fx.ev({"id": "b0001", "text": "Строка 1: порог 50 000 ₸"}, "50 000 ₸")])
    rep = fx.report_for(txt, "txt", [finding])
    res = export_pdf(rep, txt, tmp_path / "spec.txt.pdf")
    assert [p.status for p in res.placements] == ["highlight"]
    with pymupdf.open(res.output_path) as d:
        assert "**не разметка**" in d[0].get_text()


def test_docx_is_rejected(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"PK\x03\x04fake")
    rep = {"document": {"id": fx.sha256(p), "format": "docx", "blocks": []}, "findings": []}
    with pytest.raises(UnsupportedFormatError):
        export_pdf(rep, p, tmp_path / "a.pdf")


def test_page_labels_read_by_pdfium(exported_md):
    pdfium = pytest.importorskip("pypdfium2")
    import ctypes

    raw = pdfium.raw
    doc = pdfium.PdfDocument(str(exported_md.output_path))
    labels = []
    for i in range(len(doc)):
        n = raw.FPDF_GetPageLabel(doc, i, None, 0)
        buf = ctypes.create_string_buffer(n)
        raw.FPDF_GetPageLabel(doc, i, buf, n)
        labels.append(buf.raw[: n - 2].decode("utf-16-le"))
    assert labels == [f"Экспорт-{i + 1}" for i in range(len(doc))]
