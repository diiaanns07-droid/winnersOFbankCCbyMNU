"""Производные PDF для граничных случаев №02. Нужен только PyMuPDF, шрифты не нужны.

Каждая функция берёт текстовую фикстуру p02_sample.pdf и пишет новый PDF:
скан вместо страницы, пустая страница, картинка без текста, шифрование,
шрифт без ToUnicode, страница из одних кривых. Используется в тестах (tmp_path)
и в make_fixtures.py для коммитных копий.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / 'fixtures' / 'p02_sample.pdf'
FIXED_META = {'creationDate': "D:20261127000000+05'00'", 'modDate': "D:20261127000000+05'00'",
              'producer': 'bcc_review p02 builders', 'creator': 'tests/p02/builders.py'}


def _save(doc: pymupdf.Document, out: Path, **kw) -> Path:
    doc.set_metadata(dict(doc.metadata or {}, **FIXED_META, title=out.stem))
    doc.save(out, garbage=4, deflate=True, no_new_id=True, **kw)
    return out


def _scan_of(src: pymupdf.Document, page_index: int, target: pymupdf.Document, dpi: int = 110) -> pymupdf.Page:
    """Страница-«скан»: растровое изображение исходной страницы без текстового слоя."""
    page = src[page_index]
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    new = target.new_page(width=page.rect.width, height=page.rect.height)
    new.insert_image(new.rect, stream=pix.tobytes('png'))
    return new


def scan_mixed(out: Path) -> Path:
    """1 — текст, 2 — скан, 3 — пустая, 4 — текст + большая картинка без текста, 5 — текст."""
    src = pymupdf.open(SAMPLE)
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=0, to_page=0)
    _scan_of(src, 1, doc)
    doc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    doc.insert_pdf(src, from_page=3, to_page=3)
    page = doc[3]
    pix = src[2].get_pixmap(dpi=60, clip=pymupdf.Rect(56, 520, 540, 780))
    page.insert_image(pymupdf.Rect(56, 300, 540, 520), stream=pix.tobytes('png'))
    doc.insert_pdf(src, from_page=4, to_page=4)
    return _save(doc, out)


def all_scan(out: Path) -> Path:
    src = pymupdf.open(SAMPLE)
    doc = pymupdf.open()
    for i in range(2):
        _scan_of(src, i, doc)
    return _save(doc, out)


def blank_only(out: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    return _save(doc, out)


def encrypted(out: Path, user_pw: str = 'user-02', owner_pw: str = 'owner-02') -> Path:
    doc = pymupdf.open(SAMPLE)
    return _save(doc, out, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw=owner_pw,
                 permissions=pymupdf.PDF_PERM_PRINT)


def without_tounicode(out: Path, pages: tuple[int, ...] = (1,)) -> Path:
    """Шрифты без /ToUnicode на выбранных страницах (с 0): текстовый слой есть, но читается «кашей».

    Подмножества TrueType у reportlab закодированы своей таблицей, поэтому без ToUnicode
    MuPDF отдаёт латиницу и управляющие символы вместо кириллицы — как у «битых» PDF из практики.
    """
    doc = pymupdf.open(SAMPLE)
    for index in pages:
        for font in doc[index].get_fonts(full=True):
            xref = font[0]
            if doc.xref_get_key(xref, 'ToUnicode')[0] != 'null':
                doc.xref_set_key(xref, 'ToUnicode', 'null')
    return _save(doc, out)


def vector_page(out: Path) -> Path:
    """Страница без текста и картинок, но с сотнями контуров (текст «в кривых»)."""
    doc = pymupdf.open()
    page = doc.new_page()
    shape = page.new_shape()
    for i in range(120):
        y = 60 + (i // 10) * 30
        x = 60 + (i % 10) * 45
        shape.draw_bezier((x, y), (x + 10, y - 12), (x + 20, y + 12), (x + 30, y))
    shape.finish(color=(0, 0, 0), width=1.2)
    shape.commit()
    return _save(doc, out)


def rotated_copy(out: Path, rotation: int = 90, page_index: int = 0) -> Path:
    """Текстовая страница фикстуры с /Rotate: содержимое прежнее, читатель видит его повёрнутым."""
    doc = pymupdf.open(SAMPLE)
    doc.select([page_index])
    doc[0].set_rotation(rotation)
    return _save(doc, out)


def with_logo(out: Path) -> Path:
    """Текстовая страница с маленьким логотипом (около 2–3% площади): не повод для предупреждения."""
    src = pymupdf.open(SAMPLE)
    pix = src[0].get_pixmap(dpi=30, clip=pymupdf.Rect(56, 60, 440, 90))
    doc = pymupdf.open(SAMPLE)
    doc.select([0])
    doc[0].insert_image(pymupdf.Rect(440, 40, 540, 110), stream=pix.tobytes('png'))
    return _save(doc, out)


def text_over_scan(out: Path) -> Path:
    """«Распознанный скан»: картинка на всю страницу, поверх неё исходный текстовый слой."""
    src = pymupdf.open(SAMPLE)
    doc = pymupdf.open(SAMPLE)
    doc.select([0])
    page = doc[0]
    pix = src[0].get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
    page.insert_image(page.rect, stream=pix.tobytes('png'), overlay=False)
    return _save(doc, out)
