"""№25: большой документ (150+ страниц) — время чтения и нарезки растёт линейно, без O(n²).

Документ собирается в тесте: 80 разделов по 8 требований и таблица полей в каждом (MD — 2 000+ строк, PDF — 160
страниц в полном замере). В наборе — PDF на 20 и 60 страниц (отношение времени, а не абсолютное время: облако и
ноутбук жюри разные) и MD/DOCX целиком.

Замер 27.11 (облако, PyMuPDF 1.28.2): PDF 160 стр. — docview 22 с (из них 17 с — поиск таблиц читателя v1, линейно),
нарезка без модели 9,7 → 1,0 с; MD 2 161 строка — нарезка 9,3 → 0,9 с (было: каждое требование проверялось
нормализацией всего документа).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q
from bcc_review.v2.stages import segment as S

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _req(s: int, r: int) -> str:
    return (f"Т-{s}.{r}. Система обрабатывает операцию типа {s}-{r} не дольше {r} секунд и пишет запись "
            f"в журнал раздела {s}.")


def _md(sections: int) -> str:
    md = ["# Большое ТЗ", ""]
    for s in range(1, sections + 1):
        md += [f"## {s}. Раздел {s}", ""]
        for r in range(1, 9):
            md += [_req(s, r), ""]
        md += ["| Поле | Тип | Описание |", "|---|---|---|"]
        md += [f"| field_{s}_{k} | string | Описание поля {k} раздела {s} |" for k in range(6)] + [""]
    return "\n".join(md)


def _pdf(path: Path, sections: int) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    hs = ParagraphStyle("h", fontName="DejaVu", fontSize=13, leading=16, spaceBefore=8, spaceAfter=4)
    ps = ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=13, spaceAfter=5)
    story = []
    for s in range(1, sections + 1):
        story.append(Paragraph(f"{s}. Раздел {s}", hs))
        story += [Paragraph(_req(s, r), ps) for r in range(1, 9)]
        rows = [["Поле", "Тип", "Описание"]] + [[f"field_{s}_{k}", "string", f"Описание поля {k} раздела {s}"]
                                                for k in range(6)]
        t = Table(rows)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"), ("FONTNAME", (0, 0), (-1, -1), "DejaVu")]))
        story += [t, PageBreak(), Paragraph("Пояснение к разделу: поле заполняется из профиля клиента. " * 30, ps),
                  PageBreak()]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def _timed(fn, *a):
    t = time.perf_counter()
    out = fn(*a)
    return out, time.perf_counter() - t


def test_big_markdown_reads_and_segments_fast(tmp_path):
    p = tmp_path / "big.md"
    p.write_text(_md(80), encoding="utf-8")
    v, t_load = _timed(dv.load, p)
    assert len(v["lines"]) > 2000
    seg, t_seg = _timed(S.heuristic_segment, v)
    assert len(seg["requirements"]) >= 640
    assert t_load < 10 and t_seg < 6, (t_load, t_seg)
    # цитаты: каждая 10-я строка требования — на своей строке
    for s in range(1, 81, 10):
        ln = next(x for x in v["lines"] if x["text"] == _req(s, 3))
        m = Q.verify_quote(v, _req(s, 3)[:60])
        assert m and m["line_start"] == ln["n"]


def test_segment_time_grows_linearly(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(_md(15), encoding="utf-8")
    b.write_text(_md(60), encoding="utf-8")
    va, vb = dv.load(a), dv.load(b)
    _timed(S.heuristic_segment, va)  # прогрев
    _, ta = _timed(S.heuristic_segment, va)
    _, tb = _timed(S.heuristic_segment, vb)
    # вчетверо больше строк: линейно — ≈ 4×, квадратично — ≈ 16× (до исправления было 11×)
    assert tb < 8 * max(ta, 0.02), (ta, tb)


@pytest.mark.skipif(not Path(FONT).is_file(), reason="нет шрифта DejaVu")
def test_big_pdf_time_grows_linearly(tmp_path):
    pytest.importorskip("pymupdf")
    pytest.importorskip("reportlab")
    small, big = tmp_path / "s.pdf", tmp_path / "b.pdf"
    _pdf(small, 10)
    _pdf(big, 40)
    vs, ts = _timed(dv.load, small)
    vb, tb = _timed(dv.load, big)
    assert vs["pages"] == 20 and vb["pages"] == 80
    assert tb < 8 * max(ts, 0.05), (ts, tb)
    # ни одной потерянной строки требования, страница — та, где требование в PDF
    reqs = [x for x in vb["lines"] if x["text"].startswith("Т-")]
    assert len(reqs) == 320
    assert all(x["page"] == 1 + 2 * (int(x["text"][2:].split(".")[0]) - 1) for x in reqs)
    seg, t_seg = _timed(S.heuristic_segment, vb)
    assert len(seg["requirements"]) >= 320 and t_seg < 5
