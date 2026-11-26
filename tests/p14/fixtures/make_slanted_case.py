"""Генератор фикстуры №14 «наклонные строки на повёрнутой странице» и эталона геометрии.

    python tests/p14/fixtures/make_slanted_case.py            # PDF + геометрия
    python tests/p14/fixtures/make_slanted_case.py --document # + Document настоящего ридера №02

Страница 1: «Порог уведомления: 50 000 ₸ …» горизонтально, старый комментарий коллеги.
Страница 2: CropBox со смещением, /Rotate 90, две близкие наклонные строки (15°):
  A «Порог уведомления: 70 000 ₸ …» и B «Порог уведомления: 90 000 ₸ …».
  Строка B лежит внутри осевого прямоугольника цитаты из строки A.

Наклонные строки пишутся сырым content stream с явной матрицей ``Tm`` (без ``morph``), поэтому
эталон (slanted_case.geometry.json) считается ровно из того, что записано: начало базовой линии,
угол, ширина префикса по встроенному шрифту (Identity-H, CID = GID), ascender/descender шрифта.
Координаты переводятся в неповёрнутое пространство страницы PyMuPDF (ось y вниз, минус левый
верхний угол CropBox). Код экспорта сюда не входит.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.exports.pdf import _build_font  # noqa: E402  (закреплённый Noto Sans из pdf_assets)

PDF = HERE / "slanted_case.pdf"
GEOMETRY = HERE / "slanted_case.geometry.json"
DOCUMENT = HERE / "slanted_case.document.json"

W, H = 612.0, 792.0
FS = 11.0
P1_LINES = [
    ((72.0, 120.0), "Порог уведомления: 50 000 ₸ в месяц на карту."),
    ((72.0, 150.0), "Уведомление приходит один раз за календарный месяц."),
]
P2_HEAD = ((72.0, 110.0), "Часть B. Схема порогов (наклонная надпись)")
ANGLE = 15.0  # градусы; положительный — строка поднимается слева направо на экране без /Rotate
P2_A = (120.0, 360.0)
GAP = 13.5  # расстояние между базовыми линиями A и B по перпендикуляру
P2_TEXT_A = "Порог уведомления: 70 000 ₸ в месяц на карту."
P2_TEXT_B = "Порог уведомления: 90 000 ₸ для бизнес-карт."
CROP = (36.0, 48.0, 576.0, 760.0)
ROTATE = 90
OLD_COMMENT = "Комментарий коллеги: сверить порог со страницей 2"
QUOTES = {
    "a": (1, 0, "Порог уведомления: 50 000 ₸"),
    "b": (2, "A", "Порог уведомления: 70 000 ₸"),
    "neighbour": (2, "B", "Порог уведомления: 90 000 ₸"),
}


def _dir(angle: float) -> tuple[float, float]:
    """Единичный вектор базовой линии в координатах PyMuPDF (ось y вниз)."""
    t = math.radians(angle)
    return (math.cos(t), -math.sin(t))


def _origin_b() -> tuple[float, float]:
    dx, dy = _dir(ANGLE)
    nx, ny = -dy, dx  # перпендикуляр «вниз» от строки A
    return (P2_A[0] + nx * GAP, P2_A[1] + ny * GAP)


def _quad(origin, angle, font, text, quote, shift=(0.0, 0.0)):
    i = text.index(quote)
    s0 = font.text_length(text[:i], FS)
    s1 = font.text_length(text[: i + len(quote)], FS)
    dx, dy = _dir(angle)
    ux, uy = dy, -dx  # «вверх» от базовой линии
    asc, desc = font.ascender * FS, font.descender * FS

    def pt(s, h):
        return [round(origin[0] + dx * s + ux * h - shift[0], 3), round(origin[1] + dy * s + uy * h - shift[1], 3)]

    return {"ul": pt(s0, asc), "ur": pt(s1, asc), "ll": pt(s0, desc), "lr": pt(s1, desc)}


def build() -> dict:
    chars = "".join(t for _, t in P1_LINES) + P2_HEAD[1] + P2_TEXT_A + P2_TEXT_B + OLD_COMMENT
    buf = _build_font(chars, 400)
    font = pymupdf.Font(fontbuffer=buf)
    doc = pymupdf.open()
    p1 = doc.new_page(width=W, height=H)
    p1.insert_font(fontname="noto", fontbuffer=buf)
    for pos, text in P1_LINES:
        p1.insert_text(pos, text, fontname="noto", fontsize=FS)
    a = p1.add_text_annot((540, 70), OLD_COMMENT, icon="Comment")
    a.set_info(title="Коллега", content=OLD_COMMENT)
    a.update()
    p2 = doc.new_page(width=W, height=H)
    p2.insert_font(fontname="noto", fontbuffer=buf)
    p2.insert_text(P2_HEAD[0], P2_HEAD[1], fontname="noto", fontsize=FS)
    ob = _origin_b()
    c, s = math.cos(math.radians(ANGLE)), math.sin(math.radians(ANGLE))
    ops = ["q BT"]
    for origin, text in ((P2_A, P2_TEXT_A), (ob, P2_TEXT_B)):
        gids = "".join(f"{font.has_glyph(ord(ch)):04x}" for ch in text)
        # PDF: ось y вверх, поэтому y = H - y_вниз; поворот на +ANGLE против часовой стрелки
        ops.append(f"/noto {FS} Tf {c:.6f} {s:.6f} {-s:.6f} {c:.6f} {origin[0]:.3f} {H - origin[1]:.3f} Tm <{gids}> Tj")
    ops.append("ET Q")
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, "\n".join(ops).encode("latin-1"))
    contents = p2.get_contents() + [xref]
    doc.xref_set_key(p2.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in contents) + "]")
    doc[1].set_cropbox(pymupdf.Rect(*CROP))
    doc[1].set_rotation(ROTATE)
    doc.set_metadata({"title": "p14 slanted case", "creator": "tests/p14/fixtures/make_slanted_case.py"})
    doc.save(PDF, garbage=3, deflate=True, no_new_id=True)
    doc.close()

    shift = (CROP[0], CROP[1])
    geo = {
        "pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
        "font_size": FS, "angle_deg": ANGLE, "crop_box": CROP, "rotation": ROTATE,
        "ascender": font.ascender, "descender": font.descender,
        "lines": {"p1": P1_LINES[0][1], "A": P2_TEXT_A, "B": P2_TEXT_B},
        "old_comment": OLD_COMMENT,
        "quads": {
            "a": {"page": 1, "quote": QUOTES["a"][2], **_quad(P1_LINES[0][0], 0.0, font, P1_LINES[0][1], QUOTES["a"][2])},
            "b": {"page": 2, "quote": QUOTES["b"][2], **_quad(P2_A, ANGLE, font, P2_TEXT_A, QUOTES["b"][2], shift)},
            "neighbour": {"page": 2, "quote": QUOTES["neighbour"][2],
                          **_quad(ob, ANGLE, font, P2_TEXT_B, QUOTES["neighbour"][2], shift)},
        },
        "note": "координаты: неповёрнутая страница PyMuPDF (от левого верхнего угла CropBox, y вниз)",
    }
    GEOMETRY.write_text(json.dumps(geo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return geo


def read_document() -> dict:
    from bcc_review.readers import pdf as reader

    doc = reader.read_pdf(PDF, ocr="off")
    doc["_reader"] = {"module": "bcc_review.readers.pdf", "version": reader.READER_VERSION,
                      "commit": "288d7272025c23e5379502d3e79ee586e08ca384", "pymupdf": pymupdf.VersionBind}
    DOCUMENT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


if __name__ == "__main__":
    g = build()
    print(json.dumps({"pdf": str(PDF), "sha256": g["pdf_sha256"]}, ensure_ascii=False))
    if "--document" in sys.argv:
        d = read_document()
        print(json.dumps({"document": str(DOCUMENT), "blocks": len(d["blocks"]), "reader": d["_reader"]}, ensure_ascii=False))
