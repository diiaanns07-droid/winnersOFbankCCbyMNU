"""Детерминированная генерация PDF-фикстур №02.

Фикстуры собирает reportlab, а читает PyMuPDF: производитель и читатель разные,
поэтому тест не проверяет MuPDF самим собой. Готовые PDF лежат в репозитории,
и для тестов reportlab не нужен. Перегенерация (нужны reportlab и шрифт DejaVu):

    python tests/p02/fixtures/make_fixtures.py

Содержимое синтетическое, суммы и фразы подобраны под проверки №02:
одна фраза на страницах 1 и 2 с разными суммами, таблица с линейками,
перенос слова, две колонки, таблицы на две страницы с повтором шапки и без него,
колонтитулы на каждой странице.
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    TableStyle,
)

HERE = Path(__file__).resolve().parent
FONT_DIRS = [Path('/usr/share/fonts/truetype/dejavu'), Path('/usr/share/fonts/dejavu'),
             Path('/Library/Fonts'), Path('C:/Windows/Fonts')]

# Фразы, на которые опираются тесты (tests/p02/test_pdf_reader.py).
PHRASE = 'Порог уведомления составляет'
PAGE1_SUM = '50 000 ₸'
PAGE2_SUM = '75 000 ₸'


def _font(name: str) -> str:
    for directory in FONT_DIRS:
        if (directory / name).exists():
            return str(directory / name)
    sys.exit(f'Нужен шрифт {name} (пакет fonts-dejavu): в нём есть кириллица и знак ₸.')


def _styles():
    pdfmetrics.registerFont(TTFont('DejaVu', _font('DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont('DejaVu-Bold', _font('DejaVuSans-Bold.ttf')))
    body = ParagraphStyle('body', fontName='DejaVu', fontSize=10.5, leading=14, spaceAfter=6)
    return {
        'title': ParagraphStyle('title', parent=body, fontName='DejaVu-Bold', fontSize=18, leading=22, spaceAfter=10),
        'h1': ParagraphStyle('h1', parent=body, fontName='DejaVu-Bold', fontSize=14, leading=18, spaceBefore=6, spaceAfter=6),
        'body': body,
        'cell': ParagraphStyle('cell', parent=body, fontSize=9.5, leading=12, spaceAfter=0),
        'head': ParagraphStyle('head', parent=body, fontName='DejaVu-Bold', fontSize=9.5, leading=12, spaceAfter=0),
    }


def _table(rows, styles, widths, repeat):
    data = [[Paragraph(c, styles['head']) for c in rows[0]]]
    data += [[Paragraph(c, styles['cell']) for c in row] for row in rows[1:]]
    table = LongTable(data, colWidths=widths, repeatRows=repeat)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.6, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    return table


def _furniture(canvas, doc):
    canvas.saveState()
    canvas.setFont('DejaVu', 8)
    canvas.drawString(20 * mm, A4[1] - 12 * mm, 'Учебный кейс · месячный порог расходов')
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f'Стр. {doc.page}')
    canvas.restoreState()


def build_sample(path: Path) -> None:
    s = _styles()
    margin = 20 * mm
    width, height = A4
    full = Frame(margin, margin, width - 2 * margin, height - 2 * margin, id='full')
    top_h = 30 * mm
    gap = 8 * mm
    col_w = (width - 2 * margin - gap) / 2
    col_h = height - 2 * margin - top_h
    top = Frame(margin, height - margin - top_h, width - 2 * margin, top_h, id='top')
    left = Frame(margin, margin, col_w, col_h, id='left')
    right = Frame(margin + col_w + gap, margin, col_w, col_h, id='right')
    doc = BaseDocTemplate(str(path), pagesize=A4, title='Фикстура №02: порог расходов', author='bcc_review p02',
                          subject='Синтетический документ для читалки PDF', creator='make_fixtures.py', invariant=1)
    doc.addPageTemplates([
        PageTemplate(id='one', frames=[full], onPage=_furniture),
        PageTemplate(id='cols', frames=[top, left, right], onPage=_furniture),
    ])
    story = [
        Paragraph('Месячный порог расходов по карте', s['title']),
        Paragraph('1. Общие сведения', s['h1']),
        Paragraph('Держатель карты задаёт месячный порог в тенге. Сервис считает покупки за календарный месяц. '
                  'Когда сумма достигает порога, клиент получает одно push-уведомление.', s['body']),
        Paragraph(f'{PHRASE} {PAGE1_SUM} для новой карты.', s['body']),
        Paragraph('Изменение порога требует согла-<br/>сования с владельцем продукта и не сбрасывает накопленные расходы.',
                  s['body']),
        Spacer(1, 4),
        _table([
            ['Исходные условия', 'Действие', 'Ожидаемый результат'],
            ['Расходы 48 500 ₸, порог 50 000 ₸', 'Покупка на 1 500 ₸', 'Итог 50 000 ₸ и один push'],
            ['Расходы 19 900 ₸, порог 20 000 ₸', 'Перевод 500 ₸', 'Счётчик показывает 19 900 ₸'],
        ], s, [60 * mm, 45 * mm, 65 * mm], repeat=1),
        NextPageTemplate('cols'),
        PageBreak(),
        Paragraph('2. Колонки', s['h1']),
        Paragraph('Левая колонка читается раньше правой.', s['body']),
        FrameBreak(),
        Paragraph('Левая колонка, абзац один. Покупки учитываются в момент авторизации операции.', s['body']),
        Paragraph('Левая колонка, абзац два. Возвраты уменьшают сумму расходов за месяц.', s['body']),
        FrameBreak(),
        Paragraph('Правая колонка, абзац один. Переводы между своими счетами не считаются покупками.', s['body']),
        Paragraph(f'{PHRASE} {PAGE2_SUM} для премиальной карты.', s['body']),
        NextPageTemplate('one'),
        PageBreak(),
        Paragraph('3. Таблица приёмки', s['h1']),
        Paragraph('Таблица продолжается на следующей странице, шапка повторяется.', s['body']),
        Spacer(1, 150 * mm),
        _table([['№', 'Сценарий', 'Сумма']] + [[f'К{i}', f'Сценарий приёмки номер {i}', f'{i} 000 ₸'] for i in range(1, 15)],
               s, [15 * mm, 100 * mm, 55 * mm], repeat=1),
        Paragraph('4. Лимиты без повтора шапки', s['h1']),
        Spacer(1, 135 * mm),
        _table([['Код', 'Лимит', 'Валюта']] + [[f'L{i}', f'{i * 10} 000', 'KZT'] for i in range(1, 15)],
               s, [30 * mm, 80 * mm, 60 * mm], repeat=0),
    ]
    doc.build(story)


def build_rotated_text(path: Path) -> None:
    """Страница с /Rotate 90, текст которой написан поперёк MediaBox: читатель видит обычную
    книжную страницу, а в неповёрнутой системе PyMuPDF строки идут снизу вверх (dir = (0, -1)).
    Ниже заголовка — две колонки. (reportlab при setPageRotation(90) кладёт MediaBox 842×595.)"""
    from reportlab.pdfgen import canvas as rl_canvas
    c = rl_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle('Фикстура №02: повёрнутая страница')
    c.setPageRotation(90)
    c.saveState()
    c.translate(A4[1], 0)              # MediaBox 842×595: x пользователя = 842 − y читателя
    c.rotate(90)                       # система читателя: ширина 595, высота 842, ось y вверх
    width, height = A4
    c.setFont('DejaVu-Bold', 14)
    c.drawString(20 * mm, height - 25 * mm, 'Повёрнутая страница')
    c.setFont('DejaVu', 10.5)
    c.drawString(20 * mm, height - 35 * mm, f'{PHRASE} 90 000 ₸ на повёрнутой странице.')
    styles = _styles()
    column = (width - 40 * mm - 10 * mm) / 2
    top = height - 50 * mm
    left = [Paragraph('Левая колонка, абзац один: покупки учитываются в момент авторизации операции '
                      'и попадают в счётчик текущего месяца.', styles['body']),
            Paragraph('Левая колонка, абзац два: возвраты уменьшают сумму расходов.', styles['body'])]
    right = [Paragraph('Правая колонка, абзац один: переводы между своими счетами не считаются покупками '
                       'и не увеличивают счётчик.', styles['body'])]
    for x, flow in ((20 * mm, left), (20 * mm + column + 10 * mm, right)):
        y = top
        for paragraph in flow:                 # сначала вся левая колонка, затем правая — как у Word и LaTeX
            _, h = paragraph.wrap(column, height)
            paragraph.drawOn(c, x, y - h)
            y -= h + 6
    c.restoreState()
    c.showPage()
    c.save()


def main() -> None:
    rl_config.invariant = 1
    build_sample(HERE / 'p02_sample.pdf')
    build_rotated_text(HERE / 'p02_rotated_text.pdf')
    sys.path.insert(0, str(HERE.parent))
    import p02_builders as builders  # производные PDF: только PyMuPDF
    builders.scan_mixed(HERE / 'p02_scan_mixed.pdf')
    builders.rotated_copy(HERE / 'p02_rotated90.pdf')
    for name in ('p02_sample.pdf', 'p02_rotated_text.pdf', 'p02_scan_mixed.pdf', 'p02_rotated90.pdf'):
        print('ok', HERE / name)


if __name__ == '__main__':
    main()
