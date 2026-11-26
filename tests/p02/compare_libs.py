"""Сравнение библиотек PDF на фикстуре №02 (не pytest-тест, запускается вручную).

    python tests/p02/compare_libs.py [tests/p02/fixtures/p02_sample.pdf]

Для каждой установленной библиотеки печатает, что она сохраняет:
кириллицу, знак ₸, порядок двух колонок, ячейки таблицы и рамку слова «составляет»
на странице 1 (в пунктах, начало координат — левый верхний угол неповёрнутой страницы).
Отсутствующая библиотека пропускается с пометкой.
"""
from __future__ import annotations

import sys
from pathlib import Path

PDF = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'fixtures' / 'p02_sample.pdf')
LEFT = 'Левая колонка, абзац два'
RIGHT = 'Правая колонка, абзац один'
WORD = 'составляет'


def verdict(name, page1, page2, table, box):
    flat1 = ' '.join(page1.split())
    flat2 = ' '.join(page2.split())
    order = (flat2.find(LEFT) < flat2.find(RIGHT)) if LEFT in flat2 and RIGHT in flat2 else None
    print(f'\n== {name}')
    print(f'  кириллица: {"Держатель карты" in flat1}; ₸ на стр. 1: {flat1.count("₸")} (ожидается 9)')
    print(f'  две колонки: левая раньше правой = {order}')
    print(f'  перенос: {"согла- сования" in flat1 or "согла-сования" in flat1 or "согласования" in flat1}')
    print(f'  таблица стр. 1: {table}')
    print(f'  рамка «{WORD}» стр. 1: {box}')


def with_pypdf():
    from pypdf import PdfReader
    reader = PdfReader(PDF)
    verdict('pypdf (zerde)', reader.pages[0].extract_text(), reader.pages[1].extract_text(),
            'нет API таблиц', 'нет координат слов в extract_text()')


def with_pdfplumber():
    import pdfplumber
    with pdfplumber.open(PDF) as pdf:
        p1, p2 = pdf.pages[0], pdf.pages[1]
        tables = p1.extract_tables()
        rows = tables[0][:2] if tables else None
        words = [w for w in p1.extract_words() if w['text'] == WORD]
        box = [round(v, 2) for v in (words[0]['x0'], words[0]['top'], words[0]['x1'], words[0]['bottom'])] if words else None
        verdict('pdfplumber / pdfminer', p1.extract_text(), p2.extract_text(), rows, box)


def with_pypdfium2():
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(PDF)
    texts, box = [], None
    for index in (0, 1):
        page = pdf[index]
        text = page.get_textpage()
        texts.append(text.get_text_range())
        if index == 0:
            content = texts[0]
            at = content.find(WORD)
            if at >= 0:
                height = page.get_height()
                xs, ys = [], []
                for i in range(at, at + len(WORD)):
                    left, bottom, right, top = text.get_charbox(i)
                    xs += [left, right]
                    ys += [height - top, height - bottom]
                box = [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]
    verdict('pypdfium2 (RAG preview)', texts[0], texts[1], 'нет API таблиц', box)


def with_pymupdf():
    import pymupdf
    doc = pymupdf.open(PDF)
    p1, p2 = doc[0], doc[1]
    tables = p1.find_tables().tables
    rows = tables[0].extract()[:2] if tables else None
    words = [w for w in p1.get_text('words') if w[4] == WORD]
    box = [round(v, 2) for v in words[0][:4]] if words else None
    verdict(f'PyMuPDF {pymupdf.VersionBind} (выбрана)', p1.get_text(sort=True), p2.get_text(), rows, box)
    print('  внимание: порядок двух колонок у PyMuPDF зависит от потока; читалка №02 упорядочивает блоки сама')


for probe in (with_pypdf, with_pdfplumber, with_pypdfium2, with_pymupdf):
    try:
        probe()
    except ImportError as error:
        print(f'\n== {probe.__name__[5:]}: не установлена ({error.name})')
