"""Детерминированная генерация PDF-фикстур №02.

Фикстуры собирает reportlab, а читает PyMuPDF: производитель и читатель разные,
поэтому тест не проверяет MuPDF самим собой. Готовые PDF лежат в репозитории,
и для тестов reportlab не нужен. Перегенерация (нужны reportlab и шрифт DejaVu):

    python tests/p02/fixtures/make_fixtures.py

Содержимое синтетическое, суммы и фразы подобраны под проверки №02:
одна фраза на страницах 1 и 2 с разными суммами, таблица с линейками,
перенос слова, две колонки, таблицы на две страницы с повтором шапки и без него,
колонтитулы на каждой странице; банковский пример с соседними таблицами в одной сетке
(p02_bank_tables.pdf) и эталоном связок и областей ячеек (p02_bank_tables.expected.json).
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
             Path('/usr/share/fonts/truetype/liberation'), Path('/Library/Fonts'), Path('C:/Windows/Fonts')]

# Фразы, на которые опираются тесты (tests/p02/test_pdf_reader.py).
PHRASE = 'Порог уведомления составляет'
PAGE1_SUM = '50 000 ₸'
PAGE2_SUM = '75 000 ₸'


def _font(name: str) -> str:
    for directory in FONT_DIRS:
        if (directory / name).exists():
            return str(directory / name)
    sys.exit(f'Нужен шрифт {name} (пакеты fonts-dejavu, fonts-liberation): DejaVu — кириллица, ₸, ≥ ≤; '
             'Liberation Sans — шрифт без ⩾ для варианта с неподдерживаемым знаком.')


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


# Банковский пример: четыре пары страниц в одной сетке из двух колонок (x 56.69 | 226.77 | 538.58).
BANK_GRID = (56.69, 226.77, 538.58)
BANK_ROW = 20.0
BANK_SIZE = 10.5


def _bank_table(c, top: float, rows: list[tuple[str, list[str]]], areas: dict, page: int) -> float:
    """Таблица с линейками на canvas. rows: (стиль, ячейки); стиль head — жирная шапка с заливкой,
    plain_head — шапка без выделения, data — строка данных. top и возвращаемый низ — от верха страницы.
    В areas пишется контрольная область каждой ячейки: рамка ячейки и рамка глифов по метрикам шрифта."""
    height = A4[1]
    x0, x1 = BANK_GRID[0], BANK_GRID[-1]
    bottom = top + BANK_ROW * len(rows)
    for i, (style, cells) in enumerate(rows):
        y = top + i * BANK_ROW
        if style == 'head':
            c.setFillColor(colors.HexColor('#e0e0e0'))
            c.rect(x0, height - y - BANK_ROW, x1 - x0, BANK_ROW, stroke=0, fill=1)
            c.setFillColor(colors.black)
        font = 'DejaVu-Bold' if style == 'head' else 'DejaVu'
        c.setFont(font, BANK_SIZE)
        baseline = y + 14
        for col, text in enumerate(cells):
            tx = BANK_GRID[col] + 5
            c.drawString(tx, height - baseline, text)
            ascent = pdfmetrics.getAscent(font, BANK_SIZE)
            descent = pdfmetrics.getDescent(font, BANK_SIZE)
            areas.setdefault(text, []).append({
                'page': page, 'col': col, 'style': style,
                'cell': [round(v, 2) for v in (BANK_GRID[col], y, BANK_GRID[col + 1], y + BANK_ROW)],
                'glyphs': [round(v, 2) for v in (tx, baseline - ascent, tx + pdfmetrics.stringWidth(text, font, BANK_SIZE),
                                                  baseline - descent)]})
    c.setLineWidth(0.6)
    for i in range(len(rows) + 1):
        y = height - (top + i * BANK_ROW)
        c.line(x0, y, x1, y)
    for x in BANK_GRID:
        c.line(x, height - top, x, height - bottom)
    return bottom


def _bank_text(c, top: float, text: str, bold: bool = False, size: float = BANK_SIZE) -> None:
    c.setFont('DejaVu-Bold' if bold else 'DejaVu', size)
    c.drawString(BANK_GRID[0], A4[1] - top, text)


def build_bank_tables(path: Path, expected: Path) -> None:
    """Короткий банковский PDF: соседние таблицы на стыке страниц в одной сетке.

    стр. 1–2  две РАЗНЫЕ таблицы: «Операция | Сумма, ₸» в конце стр. 1, «Код HTTP | Причина»
              со своей шапкой и строкой «409 | Повтор события» в начале стр. 2;
    стр. 3–4  одна таблица «Карта | Лимит, ₸», продолжение под повторённой шапкой;
    стр. 5–6  одна таблица «Дата | Списание, ₸», продолжение без повтора шапки;
    стр. 7–8  заведомо неоднозначно: шапка без выделения, на стр. 8 первая строка тоже без выделения.
    Рядом пишется expected (JSON): эталон связок и контрольные области ячеек из этой же разметки.
    """
    import json

    from reportlab.pdfgen import canvas as rl_canvas
    _styles()
    c = rl_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle('Фикстура №02: банковские таблицы на стыке страниц')
    areas: dict = {}
    page = 0

    def new_page():
        nonlocal page
        if page:
            c.showPage()
        page += 1
        c.setFont('DejaVu', 8)
        c.drawString(BANK_GRID[0], A4[1] - 12 * mm, 'Банковский пример · таблицы на стыке страниц')
        c.drawRightString(BANK_GRID[-1], 10 * mm, f'Стр. {page}')

    def first_part(title, note, head_style, header, data):
        new_page()
        _bank_text(c, 70, title, bold=True, size=14)
        _bank_text(c, 100, note)
        return _bank_table(c, 560, [(head_style, header)] + [('data', r) for r in data], areas, page)

    def second_part(rows, after):
        new_page()
        bottom = _bank_table(c, 60, rows, areas, page)
        _bank_text(c, bottom + 30, after)

    ops = [[f'Покупка №{i}', f'{i * 1500:,} ₸'.replace(',', ' ')] for i in range(1, 11)]
    first_part('1. Операции по карте', 'Таблица операций заканчивается внизу страницы.', 'head', ['Операция', 'Сумма, ₸'], ops)
    second_part([('head', ['Код HTTP', 'Причина']), ('data', ['200', 'Порог сохранён']),
                 ('data', ['409', 'Повтор события']), ('data', ['422', 'Сумма вне диапазона'])],
                'Коды ответов сервиса уведомлений — отдельная таблица со своей шапкой.')
    limits = [[f'Карта *{1000 + i}', f'{i * 50} 000'] for i in range(1, 14)]
    first_part('2. Лимиты по картам', 'Таблица продолжается на следующей странице под повторённой шапкой.', 'head',
               ['Карта', 'Лимит, ₸'], limits[:10])
    second_part([('head', ['Карта', 'Лимит, ₸'])] + [('data', r) for r in limits[10:]],
                'Конец таблицы лимитов.')
    debits = [[f'{i:02d}.11.2026', f'{i * 700} ₸'] for i in range(1, 14)]
    first_part('3. Списания', 'Таблица продолжается на следующей странице без повтора шапки.', 'head',
               ['Дата', 'Списание, ₸'], debits[:10])
    second_part([('data', r) for r in debits[10:]], 'Конец таблицы списаний.')
    params = [[f'Параметр {i}', f'Значение {i}'] for i in range(1, 11)]
    first_part('4. Неоднозначный стык', 'Шапка не выделена, следующая страница начинается такой же строкой.',
               'plain_head', ['Параметр', 'Значение'], params)
    second_part([('data', ['Ключ', 'Описание']), ('data', ['retry', 'Повтор запроса']), ('data', ['ttl', 'Срок жизни'])],
                'По документу нельзя сказать, продолжение это или новая таблица без шапки.')
    c.save()
    truth = {
        'source': 'tests/p02/fixtures/make_fixtures.py: build_bank_tables',
        'units': 'пункты, начало — левый верхний угол неповёрнутой страницы (как у PyMuPDF)',
        'tables': [
            {'name': 'operations', 'pages': [1], 'header': ['Операция', 'Сумма, ₸']},
            {'name': 'http_codes', 'pages': [2], 'header': ['Код HTTP', 'Причина'], 'not_continuation_of': 'operations'},
            {'name': 'limits', 'pages': [3, 4], 'header': ['Карта', 'Лимит, ₸'], 'link': 'repeated_header'},
            {'name': 'debits', 'pages': [5, 6], 'header': ['Дата', 'Списание, ₸'], 'link': 'header_carried'},
            {'name': 'params', 'pages': [7], 'header': ['Параметр', 'Значение']},
            {'name': 'keys', 'pages': [8], 'link': 'uncertain', 'maybe_continues': 'params'},
        ],
        'cells': {k: v for k, v in areas.items() if k in ('409', 'Повтор события', 'Код HTTP', 'Покупка №10',
                                                         'Карта *1011', '11.11.2026', 'Ключ')},
    }
    expected.write_text(json.dumps(truth, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


AMOUNT_GRID = (56.69, 96.0, 400.0, 538.58)
AMOUNT = '50 000 ₸'


def build_amounts(path: Path, expected: Path) -> None:
    """Одна сумма «50 000 ₸» в разных местах: строки 1, 3, 8 таблицы, абзац, нижний колонтитул каждой
    страницы и строка 13 таблицы, перенесённая на стр. 2 (без повтора шапки).

    Рядом пишется expected (JSON): каждое вхождение суммы со страницей, местом (table/paragraph/footer),
    номером строки таблицы и рамкой глифов по метрикам шрифта — независимо от PyMuPDF.
    """
    import json

    from reportlab.pdfgen import canvas as rl_canvas
    _styles()
    height = A4[1]
    c = rl_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle('Фикстура №02: одна сумма в таблице, абзаце и колонтитуле')
    found: list[dict] = []

    def glyphs(x: float, baseline: float, text: str, font: str, size: float, start: int = 0) -> list[float]:
        x0 = x + pdfmetrics.stringWidth(text[:start], font, size)
        x1 = x0 + pdfmetrics.stringWidth(AMOUNT, font, size)
        return [round(v, 2) for v in (x0, baseline - pdfmetrics.getAscent(font, size), x1,
                                      baseline - pdfmetrics.getDescent(font, size))]

    def text(x: float, baseline: float, value: str, font: str = 'DejaVu', size: float = BANK_SIZE, where: str = '',
             page: int = 0) -> None:
        c.setFont(font, size)
        c.drawString(x, height - baseline, value)
        if AMOUNT in value and where:
            found.append({'page': page, 'where': where, 'row': None,
                          'glyphs': glyphs(x, baseline, value, font, size, value.index(AMOUNT))})

    def furniture(page: int) -> None:
        text(AMOUNT_GRID[0], 12 * mm, 'Выписка по карте *1234 · ноябрь 2026', size=8)
        text(AMOUNT_GRID[0], height - 10 * mm, f'Порог уведомления {AMOUNT} · стр. {page} из 2', size=8,
             where='footer', page=page)

    def table(top: float, rows: list[tuple[str, list[str]]], page: int, first_row: int, grid=AMOUNT_GRID,
              name: str = 'operations') -> float:
        """Стили строк: head — жирная шапка с заливкой; bold_head — жирная шапка без заливки;
        kv — жирный ключ и обычное значение; data — обычная строка."""
        x0, x1 = grid[0], grid[-1]
        for i, (style, cells) in enumerate(rows):
            y = top + i * BANK_ROW
            if style == 'head':
                c.setFillColor(colors.HexColor('#e0e0e0'))
                c.rect(x0, height - y - BANK_ROW, x1 - x0, BANK_ROW, stroke=0, fill=1)
                c.setFillColor(colors.black)
            for col, value in enumerate(cells):
                bold = style in ('head', 'bold_head') or (style == 'kv' and col == 0)
                font = 'DejaVu-Bold' if bold else 'DejaVu'
                c.setFont(font, BANK_SIZE)
                c.drawString(grid[col] + 5, height - (y + 14), value)
                if value == AMOUNT:
                    found.append({'page': page, 'where': 'table', 'table': name, 'row': first_row + i,
                                  'cell': [round(v, 2) for v in (grid[col], y, grid[col + 1], y + BANK_ROW)],
                                  'glyphs': glyphs(grid[col] + 5, y + 14, value, font, BANK_SIZE)})
        bottom = top + BANK_ROW * len(rows)
        c.setLineWidth(0.6)
        for i in range(len(rows) + 1):
            c.line(x0, height - (top + i * BANK_ROW), x1, height - (top + i * BANK_ROW))
        for x in grid:
            c.line(x, height - top, x, height - bottom)
        return bottom

    operations = ['Покупка в супермаркете', 'Перевод на свой счёт', 'Покупка билетов', 'Оплата связи',
                  'Покупка в аптеке', 'Снятие наличных', 'Оплата такси', 'Покупка одежды', 'Кафе', 'Возврат покупки',
                  'Покупка книг', 'Оплата парковки', 'Покупка техники']
    sums = [AMOUNT, '12 300 ₸', AMOUNT, '4 500 ₸', '2 100 ₸', '20 000 ₸', '3 300 ₸', AMOUNT, '5 600 ₸', '−7 800 ₸',
            '9 900 ₸', '1 200 ₸', AMOUNT]
    data = [('data', [str(i + 1), op, amount]) for i, (op, amount) in enumerate(zip(operations, sums))]
    furniture(1)
    text(AMOUNT_GRID[0], 70, '1. Операции за ноябрь', font='DejaVu-Bold', size=14)
    text(AMOUNT_GRID[0], 100, f'Порог уведомления — {AMOUNT} в месяц.', where='paragraph', page=1)
    text(AMOUNT_GRID[0], 120, 'Последняя строка таблицы перенесена на следующую страницу без повтора шапки.')
    table(520, [('head', ['№', 'Операция', 'Сумма, ₸'])] + data[:12], 1, 0)
    c.showPage()
    furniture(2)
    bottom = table(60, data[12:], 2, 13)
    text(AMOUNT_GRID[0], bottom + 30, f'Итог: четыре покупки по {AMOUNT} и девять других операций.',
         where='paragraph', page=2)
    # Как в командной PDF-копии: жирный заголовок вплотную над таблицей «Поле | Значение» без заливки,
    # ключи жирные. PyMuPDF принимает заголовок за внешнюю шапку (header.external = True).
    text(AMOUNT_GRID[0], 170, '2. Сведения о карте', font='DejaVu-Bold', size=14)
    table(180, [('bold_head', ['Поле', 'Значение']), ('kv', ['Карта', '*1234']), ('kv', ['Лимит', AMOUNT]),
                ('kv', ['Валюта', 'KZT'])], 2, 0, grid=(56.69, 226.77, 538.58), name='card')
    c.save()
    truth = {'source': 'tests/p02/fixtures/make_fixtures.py: build_amounts', 'amount': AMOUNT,
             'units': 'пункты, начало — левый верхний угол неповёрнутой страницы (как у PyMuPDF)',
             'table': {'header': ['№', 'Операция', 'Сумма, ₸'], 'rows': 13, 'pages': [1, 2],
                       'moved_row': 13, 'link': 'header_carried'},
             'card_table': {'header': ['Поле', 'Значение'], 'page': 2, 'rows': 3},
             'occurrences': found}
    expected.write_text(json.dumps(truth, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


BOUNDARY_GRID = (56.69, 96.0, 260.0, 538.58)
BOUNDARY_FONTS = ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')
MISSING_GLYPH_FONT = 'LiberationSans-Regular.ttf'    # в нём нет ⩾ (U+2A7E) и ₸
NBSP = '\u00a0'
THRESHOLD = f'1{NBSP}000'
# Четыре условия одного порога: знак, сторона границы, входит ли сама 1 000 в условие, действие.
BOUNDARY_ROWS = [
    ('≥', 'lower', True, 'Запросить SMS-код'),
    ('<', 'upper', False, 'Провести без SMS-кода'),
    ('≤', 'upper', True, 'Не уведомлять мониторинг'),
    ('>', 'lower', False, 'Уведомить мониторинг'),
]
UNSUPPORTED_SIGN = '⩾'    # «больше или равно» с наклонной чертой: шрифт строки 1 его не содержит


def _register_nbsp_font(name: str, file: str) -> None:
    """TTF-шрифт reportlab, который сохраняет U+00A0 в текстовом слое.

    reportlab в ``TTFont.splitString`` заменяет NBSP обычным пробелом (``if code==0xa0: code = 32``):
    в PDF попадает код пробела, и ToUnicode даёт U+0020 — неразрывного пробела в документе уже нет
    (так было на первой сборке, видно и в pdfminer, и в PyMuPDF). Здесь та же функция без этой строки:
    NBSP получает свой код подмножества с глифом пробела, ToUnicode отображает его в U+00A0.
    """
    import inspect
    import textwrap

    from reportlab.pdfbase import ttfonts
    source = textwrap.dedent(inspect.getsource(ttfonts.TTFont.splitString))
    fold = 'if code==0xa0: code = 32'
    if source.count(fold) != 1:
        sys.exit(f'reportlab: в TTFont.splitString не найдена строка «{fold}» — проверьте сохранение NBSP вручную.')
    namespace: dict = {}
    code = compile(source.replace(fold, 'pass'), '<reportlab TTFont.splitString без замены NBSP>', 'exec')
    exec(code, vars(ttfonts), namespace)  # noqa: S102
    font_class = type('NbspTTFont', (ttfonts.TTFont,), {'splitString': namespace['splitString']})
    font = font_class(name, _font(file))
    # registerFont делает новое имя псевдонимом уже зарегистрированного шрифта с тем же начертанием
    # (_dynFaceNames): после _styles() «DejaVuNbsp» молча стал бы обычным «DejaVu» с заменой NBSP.
    other = pdfmetrics._dynFaceNames.pop(font.face.name, None)
    try:
        pdfmetrics._fonts.pop(name, None)
        pdfmetrics.registerFont(font)
    finally:
        if other is not None:
            pdfmetrics._dynFaceNames[font.face.name] = other
    if pdfmetrics.getFont(name) is not font:
        sys.exit(f'reportlab зарегистрировал вместо {name} другой шрифт: NBSP не сохранится.')


def build_boundaries(path: Path, expected: Path, *, unsupported: bool = False) -> None:
    """Порог 1 000 и четыре границы в разных строках таблицы; единица только в шапке.

    стр. 1  заголовок раздела, абзац «Порог проверки — 1 000 ₸ за одну операцию.», таблица
            «№ | Сумма операции, ₸ | Действие» (жирная шапка с заливкой) и строки 1–3:
            «≥ 1 000», «< 1 000», «≤ 1 000»;
    стр. 2  строка 4 «> 1 000», перенесённая без повтора шапки: единица осталась в шапке на стр. 1.
    Между знаком и числом и между разрядами — неразрывный пробел U+00A0. Колонтитулы: верхний
    повторяется, нижний «Стр. N из 2». Шрифт DejaVu Sans: глифы ≥ ≤ < > ₸ и NBSP в нём есть
    (номера глифов пишутся в эталон; test_boundaries.py проверяет PDF до сравнения с читалкой).

    ``unsupported=True`` — вариант с неподдерживаемым символом: в строке 1 вместо «≥» стоит «⩾»,
    набранный шрифтом Liberation Sans, где этого глифа нет. reportlab пишет .notdef (код 0,
    ToUnicode → U+0000): на странице виден пустой прямоугольник, в тексте знака нет.

    Рядом пишется expected (JSON): каждое условие со страницей, строкой, видимым знаком (кодовая точка),
    значением, единицей шапки, включённостью границы и рамками глифов знака и числа по метрикам шрифта.
    """
    import hashlib
    import json

    from reportlab.pdfbase.ttfonts import TTFontFile
    from reportlab.pdfgen import canvas as rl_canvas
    regular, bold, missing = 'DejaVuNbsp', 'DejaVuNbsp-Bold', 'LiberationNbsp'
    _register_nbsp_font(regular, BOUNDARY_FONTS[0])
    _register_nbsp_font(bold, BOUNDARY_FONTS[1])
    faces = {regular: TTFontFile(_font(BOUNDARY_FONTS[0])), bold: TTFontFile(_font(BOUNDARY_FONTS[1]))}
    if unsupported:
        _register_nbsp_font(missing, MISSING_GLYPH_FONT)
        faces[missing] = TTFontFile(_font(MISSING_GLYPH_FONT))
        if ord(UNSUPPORTED_SIGN) in faces[missing].charToGlyph:
            sys.exit(f'В {MISSING_GLYPH_FONT} есть глиф {UNSUPPORTED_SIGN}: вариант «неподдерживаемый символ» не получится.')
    height = A4[1]
    c = rl_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle('Фикстура №02: границы порога 1 000 ₸' + (', неподдерживаемый знак' if unsupported else ''))
    header = ['№', 'Сумма операции, ₸', 'Действие']
    unit = '₸'
    conditions: list[dict] = []
    grid = BOUNDARY_GRID
    signs = [(UNSUPPORTED_SIGN if unsupported and i == 0 else sign, *rest) for i, (sign, *rest) in enumerate(BOUNDARY_ROWS)]

    def box(x: float, baseline: float, text: str, font: str, size: float) -> list[float]:
        return [round(v, 2) for v in (x, baseline - pdfmetrics.getAscent(font, size),
                                      x + pdfmetrics.stringWidth(text, font, size),
                                      baseline - pdfmetrics.getDescent(font, size))]

    def furniture(page: int) -> None:
        c.setFont(regular, 8)
        c.drawString(grid[0], height - 12 * mm, 'Тарифы по картам · пороги проверки операций')
        c.drawRightString(grid[-1], 10 * mm, f'Стр. {page} из 2')

    def rows(top: float, items: list[tuple[str, list[str]]], page: int) -> float:
        x0, x1 = grid[0], grid[-1]
        for i, (style, cells) in enumerate(items):
            y = top + i * BANK_ROW
            if style == 'head':
                c.setFillColor(colors.HexColor('#e0e0e0'))
                c.rect(x0, height - y - BANK_ROW, x1 - x0, BANK_ROW, stroke=0, fill=1)
                c.setFillColor(colors.black)
            font = bold if style == 'head' else regular
            baseline = y + 14
            for col, value in enumerate(cells):
                c.setFont(font, BANK_SIZE)
                if style == 'data' and col == 1:
                    continue
                c.drawString(grid[col] + 5, height - baseline, value)
            if style != 'data':
                continue
            number = int(cells[0])
            sign, side, inclusive, action = signs[number - 1]
            sign_font = missing if sign == UNSUPPORTED_SIGN else font
            tx = grid[1] + 5
            c.setFont(sign_font, BANK_SIZE)                 # знак — своим шрифтом, число — основным
            c.drawString(tx, height - baseline, sign)
            vx = tx + pdfmetrics.stringWidth(sign, sign_font, BANK_SIZE)
            c.setFont(font, BANK_SIZE)
            c.drawString(vx, height - baseline, NBSP + THRESHOLD)
            glyph = faces[sign_font].charToGlyph.get(ord(sign))
            conditions.append({
                'row': number, 'page': page, 'drawn': cells[1], 'codepoints': [f'U+{ord(ch):04X}' for ch in cells[1]],
                'sign': sign, 'sign_codepoint': f'U+{ord(sign):04X}', 'sign_font': Path(_font(
                    MISSING_GLYPH_FONT if sign_font == missing else BOUNDARY_FONTS[0])).name,
                'glyph_id': glyph, 'visible': sign if glyph else '.notdef',
                'value': '1000', 'value_text': THRESHOLD, 'unit': unit, 'unit_from': 'header page 1',
                'side': side, 'inclusive': inclusive, 'action': action,
                'cell': [round(v, 2) for v in (grid[1], y, grid[2], y + BANK_ROW)],
                'sign_glyphs': box(tx, baseline, sign, sign_font, BANK_SIZE),
                'value_glyphs': box(vx + pdfmetrics.stringWidth(NBSP, font, BANK_SIZE), baseline, THRESHOLD, font,
                                    BANK_SIZE)})
        bottom = top + BANK_ROW * len(items)
        c.setLineWidth(0.6)
        for i in range(len(items) + 1):
            c.line(x0, height - (top + i * BANK_ROW), x1, height - (top + i * BANK_ROW))
        for x in grid:
            c.line(x, height - top, x, height - bottom)
        return bottom

    data = [('data', [str(i + 1), f'{sign}{NBSP}{THRESHOLD}', action]) for i, (sign, _, _, action) in enumerate(signs)]
    furniture(1)
    c.setFont(bold, 14)
    c.drawString(grid[0], height - 70, '1. Порог проверки операции')
    c.setFont(regular, BANK_SIZE)
    definition = f'Порог проверки — {THRESHOLD}{NBSP}{unit} за одну операцию.'
    c.drawString(grid[0], height - 100, definition)
    c.drawString(grid[0], height - 120, 'Последняя строка таблицы перенесена на следующую страницу без повтора шапки.')
    rows(680, [('head', header)] + data[:3], 1)
    c.showPage()
    furniture(2)
    bottom = rows(60, data[3:], 2)
    c.setFont(regular, BANK_SIZE)
    c.drawString(grid[0], height - (bottom + 30), 'Конец таблицы порогов.')
    c.save()
    fonts = sorted({BOUNDARY_FONTS[0], BOUNDARY_FONTS[1]} | ({MISSING_GLYPH_FONT} if unsupported else set()))
    truth = {
        'source': 'tests/p02/fixtures/make_fixtures.py: build_boundaries' + (' (unsupported=True)' if unsupported else ''),
        'units': 'пункты, начало — левый верхний угол неповёрнутой страницы (как у PyMuPDF)',
        'fonts': {name: {'sha256': hashlib.sha256(Path(_font(name)).read_bytes()).hexdigest(),
                         'glyph_ids': {f'U+{ord(ch):04X}': TTFontFile(_font(name)).charToGlyph.get(ord(ch))
                                       for ch in '≥≤<>₸⩾' + NBSP}} for name in fonts},
        'threshold': {'text': THRESHOLD, 'value': '1000', 'unit': unit, 'definition': definition, 'page': 1},
        'table': {'header': header, 'unit_column': 1, 'pages': [1, 2], 'moved_row': 4, 'link': 'header_carried'},
        'conditions': conditions,
    }
    expected.write_text(json.dumps(truth, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def main() -> None:
    rl_config.invariant = 1
    build_sample(HERE / 'p02_sample.pdf')
    build_rotated_text(HERE / 'p02_rotated_text.pdf')
    build_bank_tables(HERE / 'p02_bank_tables.pdf', HERE / 'p02_bank_tables.expected.json')
    build_amounts(HERE / 'p02_amounts.pdf', HERE / 'p02_amounts.expected.json')
    build_boundaries(HERE / 'p02_boundaries.pdf', HERE / 'p02_boundaries.expected.json')
    build_boundaries(HERE / 'p02_boundaries_unsupported.pdf', HERE / 'p02_boundaries_unsupported.expected.json',
                     unsupported=True)
    sys.path.insert(0, str(HERE.parent))
    import p02_builders as builders  # производные PDF: только PyMuPDF
    builders.scan_mixed(HERE / 'p02_scan_mixed.pdf')
    builders.rotated_copy(HERE / 'p02_rotated90.pdf')
    for name in ('p02_sample.pdf', 'p02_rotated_text.pdf', 'p02_bank_tables.pdf', 'p02_amounts.pdf', 'p02_boundaries.pdf',
                 'p02_boundaries_unsupported.pdf', 'p02_scan_mixed.pdf', 'p02_rotated90.pdf'):
        print('ok', HERE / name)


if __name__ == '__main__':
    main()
