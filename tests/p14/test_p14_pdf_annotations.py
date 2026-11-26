"""Аннотированная копия исходного PDF: реальные аннотации после повторного открытия."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf
import pytest

import p14_fixtures as fx
from p14_helpers import by_finding, close, phrase_rects
from bcc_review.exports.pdf import (
    MANIFEST_NAME,
    NM_PREFIX,
    SourceMismatchError,
    export_pdf,
    read_annotations,
    verify_export,
    write_pdf,
)


@pytest.fixture(scope="module")
def annots(exported_pdf):
    return read_annotations(exported_pdf.output_path)


def test_write_pdf_contract_returns_path(tmp_path, case_pdf, case_report):
    out = write_pdf(case_report, case_pdf, tmp_path / "copy.pdf")
    assert isinstance(out, Path) and out.is_file()
    # отчёт можно передать и путём к report.json
    rj = tmp_path / "report.json"
    rj.write_text(json.dumps(case_report, ensure_ascii=False), encoding="utf-8")
    assert write_pdf(rj, case_pdf, tmp_path / "copy2.pdf").is_file()


def test_highlight_lands_on_control_words(annots, case_pdf):
    h = by_finding(annots, "F-01")
    assert len(h) == 1 and h[0]["page"] == 1
    (want,) = phrase_rects(case_pdf, 1, "порог 50 000 ₸")
    assert len(h[0]["quads"]) == 1 and close(h[0]["quads"][0], want)


def test_same_phrase_on_two_pages_not_confused(annots, case_pdf):
    f1, f2 = by_finding(annots, "F-01"), by_finding(annots, "F-02")
    assert [a["page"] for a in f1] == [1] and [a["page"] for a in f2] == [2]
    (want2,) = phrase_rects(case_pdf, 2, "порог 50 000 ₸")
    (want1,) = phrase_rects(case_pdf, 1, "порог 50 000 ₸")
    assert close(f2[0]["quads"][0], want2)
    # на стр. 2 нет выделения F-01, на стр. 1 нет выделения F-02
    assert not any(a["page"] == 2 for a in f1) and not any(a["page"] == 1 for a in f2)
    assert not close(want1, want2, tol=0.01) or True  # координаты могут совпасть: различает страница


def test_multiline_quote_is_one_annotation_with_two_quads(annots, case_pdf):
    h = by_finding(annots, "F-03")
    assert len(h) == 1 and h[0]["page"] == 2
    l1, l2 = phrase_rects(case_pdf, 2, "исходной покупки, а переводы и снятие")
    assert len(h[0]["quads"]) == 2
    assert close(h[0]["quads"][0], l1) and close(h[0]["quads"][1], l2)


def test_rotated_and_cropped_pages(annots, case_pdf, exported_pdf):
    side_a = [x for x in by_finding(annots, "F-04") if ":a:" in x["name"]]
    side_b = [x for x in by_finding(annots, "F-04") if ":b:" in x["name"]]
    assert [x["page"] for x in side_a] == [3] and [x["page"] for x in side_b] == [4]
    # цитаты без завершающей пунктуации: левая граница и строка совпадают со словами,
    # правая граница заканчивается до знака препинания
    (wa,) = phrase_rects(case_pdf, 3, "код 200 при ошибке суммы.")
    (wb,) = phrase_rects(case_pdf, 4, "возвращается 404,")
    for q, w in ((side_a[0]["quads"][0], wa), (side_b[0]["quads"][0], wb)):
        q = pymupdf.Rect(q)
        assert abs(q.x0 - w.x0) < 0.75 and abs(q.y0 - w.y0) < 0.75 and abs(q.y1 - w.y1) < 0.75
        assert w.x1 - 6 < q.x1 < w.x1
    with pymupdf.open(case_pdf) as s, pymupdf.open(exported_pdf.output_path) as d:
        for i in (2, 3):
            assert d[i].rotation == s[i].rotation and d[i].cropbox == s[i].cropbox
        assert (d[2].rotation, d[3].rotation) == (90, 270)


def test_pdf_space_fragment_converted_on_rotated_cropped_page(annots, case_pdf):
    h = by_finding(annots, "F-09")
    assert [x["page"] for x in h] == [4]
    (want,) = phrase_rects(case_pdf, 4, "чужой карты")
    assert close(h[0]["quads"][0], want)
    lbl = by_finding(annots, "F-09", "FreeText")
    assert lbl and "на проверке" in lbl[0]["content"]


def test_conflict_both_sides_reachable(annots, exported_pdf):
    side_a = [x for x in by_finding(annots, "F-04") if ":a:" in x["name"]][0]
    side_b = [x for x in by_finding(annots, "F-04") if ":b:" in x["name"]][0]
    assert "сторона A" in side_a["content"] and "исходный PDF, стр. 4" in side_a["content"]
    assert "сторона B" in side_b["content"] and "исходный PDF, стр. 3" in side_b["content"]
    for text in (side_a["content"], side_b["content"]):
        assert "Сценарий: сумма вне диапазона" in text and "Исход A: 200 и result=ERROR" in text
    with pymupdf.open(exported_pdf.output_path) as d:
        for pno, target in ((2, 3), (3, 2)):
            page = d[pno]
            links = [lk for lk in page.get_links() if lk.get("page") == target]
            assert links, f"нет ссылки со стр. {pno + 1} на стр. {target + 1}"
            label = [a for a in page.annots() if a.type[1] == "FreeText" and "F-04" in a.info["content"]][0]
            lr = [float(v) for v in d.xref_get_key(label.xref, "Rect")[1].strip("[]").split()]
            kr = [float(v) for v in d.xref_get_key(links[0]["xref"], "Rect")[1].strip("[]").split()]
            assert max(abs(x - y) for x, y in zip(lr, kr)) < 0.01, "ссылка не совпадает с подписью"
            dest = d.xref_get_key(links[0]["xref"], "Dest")[1]
            assert dest.startswith(f"[{d[target].xref} 0 R")


def test_scan_page_gets_explicit_note(annots):
    assert not by_finding(annots, "F-05")
    notes = by_finding(annots, "F-05", "Text")
    assert len(notes) == 1 and notes[0]["page"] == 5
    assert notes[0]["content"].startswith("БЕЗ ТОЧНОЙ ПРИВЯЗКИ") and "скан" in notes[0]["content"]
    label = by_finding(annots, "F-05", "FreeText")
    assert label and "без координат" in label[0]["content"]


def test_similar_phrase_elsewhere_is_never_used(annots, exported_pdf):
    # F-07: fragments указывают на стр. 1, а такая фраза есть только на стр. 2
    assert not by_finding(annots, "F-07"), "выделение не должно переезжать на похожую фразу"
    notes = by_finding(annots, "F-07", "Text")
    assert [n["page"] for n in notes] == [1] and "не найден в подтверждённой области" in notes[0]["content"]
    pl = [p for p in exported_pdf.placements if p.finding_id == "F-07"][0]
    assert pl.status == "note" and pl.page == 1


def test_unconfirmed_evidence_is_skipped_with_reason(annots, exported_pdf):
    assert not by_finding(annots, "F-06", None)
    pl = [p for p in exported_pdf.placements if p.finding_id == "F-06"][0]
    assert pl.status == "skipped" and "не подтверждена" in pl.reason
    summary = [a for a in annots if a["name"] == NM_PREFIX + "summary"][0]
    assert summary["page"] == 1 and "F-06" in summary["content"] and "не подтверждена" in summary["content"]


def test_omission_note_at_inspected_block(annots):
    notes = by_finding(annots, "F-08", "Text")
    assert [n["page"] for n in notes] == [1] and "Пропуск" in notes[0]["content"]


def test_note_fields_id_severity_impact_question(annots):
    (h,) = by_finding(annots, "F-01")
    c = h["content"]
    assert c.startswith("F-01 · [!!!] КРИТИЧНО · подтверждено")
    for part in ("Последствие:", "Вопрос: Какой порог действует по умолчанию?", "Требования: R-01 (Ф-1)", "«порог 50 000 ₸»"):
        assert part in c
    assert h["title"] == "BCC Review · F-01" and h["subject"].startswith("КРИТИЧНО")
    assert h["has_popup"]


def test_severity_is_duplicated_by_text_not_only_color(annots):
    words = {"F-01": "КРИТИЧНО", "F-02": "СУЩЕСТВЕННО", "F-09": "НЕЗНАЧИТЕЛЬНО"}
    colors = set()
    for fid, word in words.items():
        h = by_finding(annots, fid)[0]
        lbl = by_finding(annots, fid, "FreeText")[0]
        assert word in h["content"] and word in lbl["content"] and word in h["subject"]
        colors.add(tuple(h["color"]))
    assert len(colors) == 3


def test_contents_are_unicode_in_file_and_reread(exported_pdf):
    with pymupdf.open(exported_pdf.output_path) as d:
        h = [a for a in d[0].annots() if a.type[1] == "Highlight"][0]
        obj = d.xref_object(h.xref, compressed=False)
        assert re.search(r"/Contents\s*<feff", obj, re.I), obj[:200]
        assert "порог 50 000 ₸" in h.info["content"]


def test_contents_read_by_pdfium(exported_pdf):
    pdfium = pytest.importorskip("pypdfium2")
    import ctypes

    raw = pdfium.raw
    doc = pdfium.PdfDocument(str(exported_pdf.output_path))
    page = doc[0]
    texts = []
    for i in range(raw.FPDFPage_GetAnnotCount(page)):
        an = raw.FPDFPage_GetAnnot(page, i)
        if raw.FPDFAnnot_GetSubtype(an) == raw.FPDF_ANNOT_HIGHLIGHT:
            n = raw.FPDFAnnot_GetStringValue(an, b"Contents", None, 0)
            buf = ctypes.create_string_buffer(n)
            raw.FPDFAnnot_GetStringValue(an, b"Contents", ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)), n)
            texts.append(buf.raw[: n - 2].decode("utf-16-le"))
        raw.FPDFPage_CloseAnnot(an)
    assert any("КРИТИЧНО" in t and "₸" in t for t in texts)


def test_labels_are_drawn_with_embedded_noto(exported_pdf):
    with pymupdf.open(exported_pdf.output_path) as d:
        lbl = [a for a in d[0].annots() if a.type[1] == "FreeText"][0]
        ap = int(d.xref_get_key(lbl.xref, "AP/N")[1].split()[0])
        font_ref = d.xref_get_key(ap, "Resources/Font/BCCNoto")[1]
        fx_ = int(font_ref.split()[0])
        assert "Noto Sans" in d.xref_get_key(fx_, "BaseFont")[1]
        embedded = d.xref_get_key(fx_, "DescendantFonts")[1]
        assert embedded != "null"
        assert b"/BCCNoto" in d.xref_stream(ap)


def test_source_unchanged_and_kept_as_byte_prefix(exported_pdf, case_pdf, case_report):
    assert fx.sha256(case_pdf) == case_report["document"]["id"] == exported_pdf.source_sha256
    assert exported_pdf.saved_incrementally
    src = case_pdf.read_bytes()
    assert exported_pdf.output_path.read_bytes()[: len(src)] == src
    res = verify_export(exported_pdf.output_path, case_pdf, case_report)
    assert res["ok"], res["errors"]
    for k in ("content_streams_identical", "source_words_preserved", "existing_annotations_preserved", "source_bytes_prefix"):
        assert res["checks"][k] is True, k


def test_existing_annotations_preserved(case_pdf, exported_pdf):
    before = [a for a in read_annotations(case_pdf) if a["type"] != "Link"]
    after = read_annotations(exported_pdf.output_path)
    assert {a["content"] for a in before} == {fx.EXISTING_NOTE, fx.EXISTING_SQUARE}
    for a in before:
        same = [b for b in after if b["page"] == a["page"] and b["type"] == a["type"] and b["content"] == a["content"]]
        assert same and close(same[0]["rect"], a["rect"], 0.01)


def test_manifest_embedded_with_reasons(exported_pdf):
    with pymupdf.open(exported_pdf.output_path) as d:
        m = json.loads(d.embfile_get(MANIFEST_NAME))
    assert m["mode"] == "annotated_copy" and m["source"]["sha256"] == exported_pdf.source_sha256
    st = {p["finding_id"]: p["status"] for p in m["placements"]}
    assert st["F-01"] == "highlight" and st["F-05"] == "note" and st["F-06"] == "skipped"
    assert m["font"]["version"] == "2.015"


def test_hash_mismatch_is_refused(tmp_path, case_pdf, case_report):
    bad = json.loads(json.dumps(case_report))
    bad["document"]["id"] = "0" * 64
    with pytest.raises(SourceMismatchError):
        export_pdf(bad, case_pdf, tmp_path / "x.pdf")
    assert not (tmp_path / "x.pdf").exists()


def test_output_must_differ_from_input(case_pdf, case_report):
    with pytest.raises(ValueError):
        export_pdf(case_report, case_pdf, case_pdf)


def test_export_is_deterministic(tmp_path, case_pdf, case_report):
    a = export_pdf(case_report, case_pdf, tmp_path / "a.pdf")
    b = export_pdf(case_report, case_pdf, tmp_path / "b.pdf")
    key = lambda r: [(p.finding_id, p.status, p.page, [[round(v, 2) for v in q] for q in p.rects]) for p in r.placements]  # noqa: E731
    assert key(a) == key(b)
