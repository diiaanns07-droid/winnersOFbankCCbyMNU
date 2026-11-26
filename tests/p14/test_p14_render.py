"""Отрисовка результата: выделения и подписи видны в MuPDF, PDFium и poppler."""

from __future__ import annotations

import shutil
import subprocess

import pymupdf
import pytest
from p14_helpers import by_finding

from bcc_review.exports.pdf import read_annotations, render_page_png

DPI = 72


def _is_white(px) -> bool:
    return all(c >= 245 for c in px[:3])


def _probe_points(exported_pdf):
    """(страница 0-based, точка в экранных координатах) внутри выделения рядом с углом."""
    annots = read_annotations(exported_pdf.output_path)
    pts = []
    with pymupdf.open(exported_pdf.output_path) as d:
        for fid, sel in (("F-01", None), ("F-04", ":a:"), ("F-04", ":b:"), ("F-09", None)):
            h = [a for a in by_finding(annots, fid) if sel is None or sel in a["name"]][0]
            page = d[h["page"] - 1]
            r = pymupdf.Rect(h["quads"][0]) * page.rotation_matrix
            pts.append((h["page"] - 1, (int(r.x0 + 1.5), int(r.y0 + 1.5)), fid))
    return pts


def test_render_page_with_highlight_mupdf(tmp_path, exported_pdf, case_pdf):
    png = render_page_png(exported_pdf.output_path, 1, tmp_path / "p1.png", dpi=110)
    assert png.is_file() and png.stat().st_size > 10_000
    for pno, (x, y), fid in _probe_points(exported_pdf):
        with pymupdf.open(exported_pdf.output_path) as d, pymupdf.open(case_pdf) as s:
            got = d[pno].get_pixmap(dpi=DPI, annots=True).pixel(x, y)
            src = s[pno].get_pixmap(dpi=DPI, annots=True).pixel(x, y)
        assert _is_white(src) and not _is_white(got), (fid, pno + 1, got)


def test_label_is_visible_ink(exported_pdf):
    with pymupdf.open(exported_pdf.output_path) as d:
        for pno in (0, 2, 3):
            page = d[pno]
            lbl = [a for a in page.annots() if a.type[1] == "FreeText"][0]
            r = lbl.rect * page.rotation_matrix  # clip задаётся в экранных координатах
            pix = page.get_pixmap(dpi=144, annots=True, clip=r)
            dark = sum(
                1
                for yy in range(pix.height)
                for xx in range(pix.width)
                if sum(pix.pixel(xx, yy)[:3]) < 200
            )
            assert dark > 40, f"подпись на стр. {pno + 1} пустая ({dark}, {r})"


def test_labels_do_not_cover_source_text(exported_pdf, case_pdf):
    assert not any("поверх текста" in w for w in exported_pdf.warnings)
    with pymupdf.open(case_pdf) as s, pymupdf.open(exported_pdf.output_path) as d:
        for pno in range(d.page_count):
            src_page = s[pno]
            rows = [pymupdf.Rect(line["bbox"]) * src_page.rotation_matrix
                    for b in src_page.get_text("dict")["blocks"] if b["type"] == 0 for line in b["lines"]]
            page = d[pno]
            for a in page.annots():
                if a.type[1] != "FreeText" or not (a.info.get("id") or "").startswith("bcc-review:"):
                    continue
                lr = a.rect * page.rotation_matrix
                assert not any(lr.intersects(t) for t in rows), (pno + 1, a.info["content"])


def test_pdfium_renders_highlights(exported_pdf):
    pdfium = pytest.importorskip("pypdfium2")
    doc = pdfium.PdfDocument(str(exported_pdf.output_path))
    for pno, (x, y), fid in _probe_points(exported_pdf):
        img = doc[pno].render(scale=DPI / 72, draw_annots=True).to_pil().convert("RGB")
        assert not _is_white(img.getpixel((x, y))), (fid, pno + 1)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler (pdftoppm) не установлен")
def test_poppler_renders_highlights(tmp_path, exported_pdf):
    Image = pytest.importorskip("PIL.Image")
    subprocess.run(
        ["pdftoppm", "-cropbox", "-r", str(DPI), "-png", str(exported_pdf.output_path), str(tmp_path / "pp")],
        check=True,
        capture_output=True,
    )
    pngs = sorted(tmp_path.glob("pp-*.png"))
    for pno, (x, y), fid in _probe_points(exported_pdf):
        img = Image.open(pngs[pno]).convert("RGB")
        assert not _is_white(img.getpixel((x, y))), (fid, pno + 1)


def test_markdown_render_has_tenge_ink(tmp_path, exported_md):
    """₸ действительно нарисован встроенным шрифтом, а не пустым .notdef."""
    with pymupdf.open(exported_md.output_path) as d:
        page = d[0]
        hit = [c for b in page.get_text("rawdict")["blocks"] if b["type"] == 0
               for line in b["lines"] for s in line["spans"] for c in s["chars"] if c["c"] == "₸"]
        assert hit
        span_fonts = {s["font"] for b in page.get_text("dict")["blocks"] if b["type"] == 0
                      for line in b["lines"] for s in line["spans"] if "₸" in s["text"]}
        assert all("NotoSans" in f for f in span_fonts), span_fonts
        r = pymupdf.Rect(hit[0]["bbox"])
        pix = page.get_pixmap(dpi=288, clip=r)
        dark = sum(1 for yy in range(pix.height) for xx in range(pix.width) if sum(pix.pixel(xx, yy)[:3]) < 300)
        assert dark > 15
    render_page_png(exported_md.output_path, 1, tmp_path / "md1.png")
