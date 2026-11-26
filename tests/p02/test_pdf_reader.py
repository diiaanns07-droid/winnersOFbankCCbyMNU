"""Тесты читалки PDF №02: текст, ячейки, координаты, граничные случаи, контракт v1.

Запуск: python -m pytest tests/contract tests/p02 -q
Базовый путь — только PyMuPDF на CPU; тест OCR пропускается, если tessdata нет.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import p02_builders as builders
import pymupdf
import pytest

from bcc_review.contracts import PARTIAL_READ_CODES, validate
from bcc_review.readers.pdf import (
    PdfReadError,
    diagnose_pdf,
    locate_span,
    main,
    ocr_languages,
    page_only_warning,
    read_pdf,
)

FIX = Path(__file__).resolve().parent / 'fixtures'
PHRASE = 'Порог уведомления составляет'
ALL_FIXTURES = ['p02_sample.pdf', 'p02_rotated90.pdf', 'p02_rotated_text.pdf', 'p02_scan_mixed.pdf',
                'case_requirements_chromium.pdf', 'chromium_layouts.pdf']


# --------------------------------------------------------------------------- помощники
def _find(doc: dict, needle: str, page: int | None = None) -> list[dict]:
    hits = [b for b in doc['blocks'] if needle in b['text'] and (page is None or b['loc']['page'] == page)]
    assert hits, f'нет блока с «{needle}»'
    return hits


def _by_id(doc: dict, block_id: str) -> dict:
    return next(b for b in doc['blocks'] if b['id'] == block_id)


def _span(block: dict, quote: str) -> tuple[int, int]:
    start = block['text'].index(quote)
    return start, start + len(quote)


def _iou(a, b) -> float:
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    inter = area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))
    return inter / (area(a) + area(b) - inter) if inter else 0.0


def _word_boxes(page: pymupdf.Page, word: str):
    """Рамки слова по независимому от читалки API PyMuPDF (get_text('words'))."""
    return [w[:4] for w in page.get_text('words') if w[4].strip('.,:;«»()') == word]


def _annotate_and_reopen(src: Path, page_no: int, rects, out: Path) -> list[list[str]]:
    """Как №14: подсветить прямоугольники, сохранить, открыть заново, прочитать слова под подсветкой."""
    doc = pymupdf.open(src)
    page = doc[page_no - 1]
    for rect in rects:
        page.add_highlight_annot(pymupdf.Rect(rect))
    doc.save(out)
    again = pymupdf.open(out)[page_no - 1]
    return [[w[4] for w in again.get_text('words', clip=annot.rect)] for annot in again.annots()]


def _codes(doc: dict) -> set[tuple[str, int | None]]:
    return {(w['code'], w['page']) for w in doc['warnings']}


def _partial(doc: dict) -> bool:
    return any(w['code'] in PARTIAL_READ_CODES for w in doc['warnings'])


# --------------------------------------------------------------------------- доказательство 1: та же фраза на двух страницах
def test_same_phrase_on_two_pages_quote_from_page_two_lands_on_page_two(sample_doc, tmp_path):
    first = _find(sample_doc, PHRASE, page=1)[0]
    second = _find(sample_doc, PHRASE, page=2)[0]
    assert '50 000 ₸' in first['text'] and '75 000 ₸' in second['text']

    # Подсказка {block_id, quote} со второй страницы: та же фраза, другой блок → координаты страницы 2.
    start, end = _span(second, PHRASE)
    loc = locate_span(_by_id(sample_doc, second['id']), start, end)
    assert loc['page'] == 2 and loc['precision'] == 'exact' and loc['block_id'] == second['id']
    loc1 = locate_span(first, *_span(first, PHRASE))
    assert loc1['page'] == 1 and loc1['rects'] != loc['rects']

    # Сумма со второй страницы: «75 000 ₸» переносится на две строки — два прямоугольника.
    amount = locate_span(second, *_span(second, '75 000 ₸'))
    assert amount['page'] == 2 and len(amount['rects']) == 2
    page2 = pymupdf.open(FIX / 'p02_sample.pdf')[1]
    assert any(_iou(amount['rects'][0], box) > 0 for box in _word_boxes(page2, '75'))
    assert any(_iou(amount['rects'][1], box) > 0.8 for box in _word_boxes(page2, '₸'))
    words = _annotate_and_reopen(FIX / 'p02_sample.pdf', 2, amount['rects'], tmp_path / 'p2.pdf')
    assert words == [['75', '000'], ['₸']]


# --------------------------------------------------------------------------- доказательство 2: повторное открытие, поворот, колонки
@pytest.mark.parametrize('name', ALL_FIXTURES)
def test_every_fragment_reopens_onto_its_own_word(name):
    """Каждый фрагмент после повторного открытия лежит внутри рамки слова PDF, содержащего его текст."""
    doc = read_pdf(FIX / name, ocr='off')
    pdf = pymupdf.open(FIX / name)
    words: dict[int, list] = {}
    checked = 0
    for block in doc['blocks']:
        number = block['loc']['page'] - 1
        if number not in words:
            words[number] = [(w[:4], w[4]) for w in pdf[number].get_text('words')]
        for frag in block['loc']['fragments']:
            piece = block['text'][frag['start']:frag['end']]
            x0, y0, x1, y1 = frag['rect']
            homes = [text for box, text in words[number]
                     if piece in text and box[0] - 0.6 <= x0 and box[1] - 0.6 <= y0
                     and x1 <= box[2] + 0.6 and y1 <= box[3] + 0.6]
            assert homes, (block['id'], piece, frag['rect'])
            checked += 1
    assert checked > 50


def test_word_rect_matches_independent_word_box(sample_doc):
    block = _find(sample_doc, PHRASE, page=1)[0]
    loc = locate_span(block, *_span(block, 'составляет'))
    page = pymupdf.open(FIX / 'p02_sample.pdf')[0]
    assert max(_iou(loc['rects'][0], box) for box in _word_boxes(page, 'составляет')) > 0.95


def test_page_with_rotate_90_keeps_unrotated_coordinates(tmp_path):
    plain = read_pdf(FIX / 'p02_sample.pdf', ocr='off')
    turned = read_pdf(FIX / 'p02_rotated90.pdf', ocr='off')
    a = next(b for b in plain['blocks'] if b['loc']['page'] == 1 and PHRASE in b['text'])
    b = next(b for b in turned['blocks'] if PHRASE in b['text'])
    assert a['text'] == b['text'] and b['loc']['rotation'] == 90
    assert [f['rect'] for f in a['loc']['fragments']] == [f['rect'] for f in b['loc']['fragments']]
    loc = locate_span(b, *_span(b, '50 000 ₸'))
    assert _annotate_and_reopen(FIX / 'p02_rotated90.pdf', 1, loc['rects'], tmp_path / 'r.pdf') == [['50', '000', '₸']]
    # Для показа повёрнутой страницы: Rect * rotation_matrix — слово стоит вертикально.
    page = pymupdf.open(FIX / 'p02_rotated90.pdf')[0]
    view = pymupdf.Rect(loc['rects'][0]) * page.rotation_matrix
    assert view.height > view.width and page.rect.contains(view)
    # Таблица на повёрнутой странице найдена (find_tables ищет на неповёрнутой).
    assert [x['kind'] for x in turned['blocks']].count('table_row') == 2 and not turned['warnings']


def test_text_across_mediabox_on_rotated_page(tmp_path):
    doc = read_pdf(FIX / 'p02_rotated_text.pdf', ocr='off')
    block = _find(doc, '90 000 ₸')[0]
    frag = block['loc']['fragments'][0]
    assert frag['dir'] == [0.0, -1.0] and block['loc']['rotation'] == 90
    loc = locate_span(block, *_span(block, '90 000 ₸'))
    assert loc['precision'] == 'exact' and len(loc['rects']) == 1
    rect = pymupdf.Rect(loc['rects'][0])
    assert rect.height > rect.width                 # в неповёрнутой системе строка идёт вертикально
    page = pymupdf.open(FIX / 'p02_rotated_text.pdf')[0]
    view = rect * page.rotation_matrix
    assert view.width > view.height                 # а читатель видит её горизонтальной
    assert _annotate_and_reopen(FIX / 'p02_rotated_text.pdf', 1, loc['rects'], tmp_path / 't.pdf') == [['90', '000', '₸']]
    # Часть слова на вертикальной строке режется по оси y.
    start = block['text'].index('уведомления')
    part = locate_span(block, start, start + 3)
    whole = locate_span(block, start, start + len('уведомления'))
    assert part['precision'] == 'approx'
    assert part['rects'][0][0] == whole['rects'][0][0] and part['rects'][0][1] > whole['rects'][0][1]


def test_two_columns_left_before_right():
    order = [b['text'] for b in read_pdf(FIX / 'p02_sample.pdf', ocr='off')['blocks'] if b['loc']['page'] == 2]
    left, right = 'Левая колонка, абзац два', 'Правая колонка, абзац один'
    assert (next(i for i, t in enumerate(order) if t.startswith(left))
            < next(i for i, t in enumerate(order) if t.startswith(right)))
    turned = [b['text'] for b in read_pdf(FIX / 'p02_rotated_text.pdf', ocr='off')['blocks']]
    assert [t.split(':')[0] for t in turned[2:]] == ['Левая колонка, абзац один', 'Левая колонка, абзац два',
                                                     'Правая колонка, абзац один']
    css = [b['text'] for b in read_pdf(FIX / 'chromium_layouts.pdf', ocr='off')['blocks']]
    first = next(i for i, t in enumerate(css) if t.startswith('Первая колонка'))
    second = next(i for i, t in enumerate(css) if t.startswith('Вторая колонка'))
    heading = css.index('Ключ — значение без линеек')
    assert first < second < heading


# --------------------------------------------------------------------------- текст: переносы, строки, таблицы
def test_hyphenation_joins_text_but_keeps_both_source_pieces(sample_doc):
    block = _find(sample_doc, 'согласования', page=1)[0]
    loc = locate_span(block, *_span(block, 'согласования'))
    assert len(loc['rects']) == 2 and loc['rects'][0][1] < loc['rects'][1][1]
    page = pymupdf.open(FIX / 'p02_sample.pdf')[0]
    assert page.get_textbox(pymupdf.Rect(loc['rects'][0])).strip() == 'согла-'
    assert page.get_textbox(pymupdf.Rect(loc['rects'][1])).strip() == 'сования'
    frags = block['loc']['fragments']
    pieces = [f for f in frags if block['text'][f['start']:f['end']] in ('согла', 'сования')]
    assert pieces[0].get('hyphen') is True and pieces[0]['end'] == pieces[1]['start']


def test_hyphen_inside_compound_kept_without_space():
    case = read_pdf(FIX / 'case_requirements_chromium.pdf', ocr='off')
    curl = _find(case, 'curl -G')[0]
    assert "--data 'cardId=demo-42&amount=50000&enabled=1'" in curl['text']


def test_table_rows_cells_and_header(sample_doc):
    rows = [b for b in sample_doc['blocks'] if b['loc']['page'] == 1 and b['kind'].startswith('table')]
    header, first = rows[0], rows[1]
    assert header['kind'] == 'table_header' and header['text'] == 'Исходные условия | Действие | Ожидаемый результат'
    table = first['loc']['table']
    assert table['header'] == ['Исходные условия', 'Действие', 'Ожидаемый результат'] and table['header_restored']
    cells = {c['col']: first['text'][c['start']:c['end']] for c in table['cells']}
    assert cells == {0: 'Расходы 48 500 ₸, порог 50 000 ₸', 1: 'Покупка на 1 500 ₸', 2: 'Итог 50 000 ₸ и один push'}
    # Ячейка с переносом строки внутри: координаты покрывают обе строки ячейки.
    loc = locate_span(first, table['cells'][0]['start'], table['cells'][0]['end'])
    assert len(loc['rects']) == 2


def test_multipage_tables_repeated_and_restored_header(sample_doc):
    t2 = [b['loc']['table'] for b in sample_doc['blocks'] if b['loc'].get('table', {}).get('id') == 'T2']
    assert [t['part'] for t in t2].count(2) == 3
    assert [t['row'] for t in t2 if not t['header_row']] == list(range(1, 15))
    repeated = [t for t in t2 if t.get('repeated_header')]
    assert len(repeated) == 1 and repeated[0]['header_source'] == 'repeated'
    t3 = [(b['loc']['page'], b['loc']['table']) for b in sample_doc['blocks']
          if b['loc'].get('table', {}).get('id') == 'T3']
    tail = [t for page, t in t3 if page == 5]
    assert [t['row'] for t in tail] == [13, 14]
    assert all(t['header'] == ['Код', 'Лимит', 'Валюта'] and t['header_source'] == 'page 4' and t['header_restored']
               for t in tail)
    summary = {t['id']: t for t in sample_doc['extraction']['tables']}
    assert summary['T2'] == {'id': 'T2', 'pages': [3, 4], 'parts': 2, 'header_restored': True}
    assert summary['T3'] == {'id': 'T3', 'pages': [4, 5], 'parts': 2, 'header_restored': True}


def test_merged_header_cells_flattened():
    doc = read_pdf(FIX / 'chromium_layouts.pdf', ocr='off')
    row = _find(doc, 'Покупка | 48 500')[0]
    assert row['loc']['table']['header'] == ['Сценарий', 'Сумма, ₸ / до', 'Сумма, ₸ / после']
    assert [b['kind'] for b in doc['blocks'] if b['loc'].get('table')].count('table_header') == 2


def test_borderless_grid_kept_as_blocks_with_warning():
    doc = read_pdf(FIX / 'chromium_layouts.pdf', ocr='off')
    warning = [w for w in doc['warnings'] if w['code'] == 'layout_grid_unreliable']
    assert len(warning) == 1 and warning[0]['page'] == 1
    texts = [b['text'] for b in doc['blocks']]
    i = texts.index('Наименование задачи')
    assert texts[i:i + 4] == ['Наименование задачи', 'Месячный порог расходов по карте', 'Продукт',
                              'Мобильный банк, учебный кейс']
    assert not any(b['loc'].get('table') for b in doc['blocks'] if b['text'] in texts[i:i + 4])


def test_headings_sections_and_furniture(sample_doc):
    heading = _find(sample_doc, '1. Общие сведения')[0]
    assert heading['kind'] == 'heading' and heading['section'] == ['Месячный порог расходов по карте', '1. Общие сведения']
    para = _find(sample_doc, PHRASE, page=2)[0]
    assert para['section'] == ['Месячный порог расходов по карте', '2. Колонки']
    furniture = [b['text'] for b in sample_doc['blocks'] if b['loc'].get('furniture')]
    assert all(b['kind'] == 'other' for b in sample_doc['blocks'] if b['loc'].get('furniture'))
    assert 'Стр. 3' in furniture and furniture.count('Учебный кейс · месячный порог расходов') == 5


# --------------------------------------------------------------------------- доказательство 3: нет текстового слоя
def test_scan_page_reports_page_number_and_completeness(tmp_path):
    path = builders.scan_mixed(tmp_path / 'mixed.pdf')
    doc = read_pdf(path, ocr='off')
    validate(doc, 'Document')
    assert {('ocr_required', 2), ('page_blank', 3), ('partial_read', 4), ('partial_read', None)} <= _codes(doc)
    summary = next(w for w in doc['warnings'] if w['code'] == 'partial_read' and w['page'] is None)
    assert summary['severity'] == 'error' and summary['pages'] == [2, 4] and summary['completeness'] < 1
    ext = doc['extraction']
    assert ext['completeness'] < 1 and ext['pages_unread'] == [2, 4]
    assert ext['pages_status'] == {'1': 'text', '2': 'scan', '3': 'blank', '4': 'partial', '5': 'text'}
    assert not [b for b in doc['blocks'] if b['loc']['page'] == 2 and not b['loc'].get('furniture')]
    diagnostic = diagnose_pdf(path, ocr='off')
    assert diagnostic['ok'] is False and diagnostic['code'] == 'partial' and diagnostic['pages'] == [2, 4]
    assert 'Страница 2' in diagnostic['message']


def test_document_without_text_layer_has_no_blocks_and_partial_codes(tmp_path):
    path = builders.all_scan(tmp_path / 'scan.pdf')
    doc = read_pdf(path, ocr='off')
    validate(doc, 'Document')
    assert doc['blocks'] == [] and doc['extraction']['completeness'] == 0.0
    assert {('ocr_required', 1), ('ocr_required', 2)} <= _codes(doc) and _partial(doc)
    diagnostic = diagnose_pdf(path, ocr='off')
    assert diagnostic['ok'] is False and diagnostic['code'] == 'no_text' and diagnostic['pages'] == [1, 2]
    assert 'OCR отключён' in diagnostic['message']


@pytest.mark.parametrize('builder, code, page_status', [
    (builders.blank_only, 'page_blank', 'blank'),
    (builders.vector_page, 'unreadable_page', 'vector'),
])
def test_empty_extraction_is_never_a_clean_document(tmp_path, builder, code, page_status):
    """Пустое извлечение не даёт позитивного вердикта: ноль блоков и код неполного чтения (готовность не ready)."""
    path = builder(tmp_path / 'x.pdf')
    doc = read_pdf(path, ocr='off')
    validate(doc, 'Document')
    assert doc['blocks'] == [] and doc['extraction']['completeness'] == 0.0
    assert (code, 1) in _codes(doc) and doc['extraction']['pages_status']['1'] == page_status
    assert _partial(doc)
    assert diagnose_pdf(path, ocr='off')['ok'] is False


def test_garbled_font_is_reported_and_not_turned_into_blocks(tmp_path):
    path = builders.without_tounicode(tmp_path / 'garbled.pdf')
    doc = read_pdf(path, ocr='off')
    garbled = sorted(w['page'] for w in doc['warnings'] if w['code'] == 'decode_error' and w['severity'] == 'error')
    assert garbled and 2 in garbled
    assert not [b for b in doc['blocks'] if b['loc']['page'] in garbled]
    assert doc['extraction']['completeness'] < 1 and _partial(doc)


def test_encrypted_pdf(tmp_path):
    locked = builders.encrypted(tmp_path / 'locked.pdf')
    with pytest.raises(PdfReadError) as error:
        read_pdf(locked, ocr='off')
    assert error.value.code == 'encrypted' and diagnose_pdf(locked)['code'] == 'encrypted'
    assert read_pdf(locked, ocr='off', password='user-02')['blocks']
    owner = builders.encrypted(tmp_path / 'owner.pdf', user_pw='')
    doc = read_pdf(owner, ocr='off')
    assert ('pdf_encrypted_owner', None) in _codes(doc) and doc['extraction']['completeness'] == 1.0
    assert not _partial(doc)


def test_not_a_pdf(tmp_path):
    path = tmp_path / 'x.pdf'
    path.write_text('# Markdown, не PDF', encoding='utf-8')
    with pytest.raises(PdfReadError) as error:
        read_pdf(path)
    assert error.value.code == 'not_pdf'


def test_no_false_alarm_for_logo_or_text_over_scan(tmp_path):
    logo = read_pdf(builders.with_logo(tmp_path / 'logo.pdf'), ocr='off')
    assert logo['warnings'] == [] and logo['extraction']['completeness'] == 1.0
    scanned = read_pdf(builders.text_over_scan(tmp_path / 'scan_text.pdf'), ocr='off')
    assert [w['code'] for w in scanned['warnings']] == ['page_text_over_image']
    assert scanned['warnings'][0]['severity'] == 'info' and scanned['extraction']['completeness'] == 1.0
    assert any(PHRASE in b['text'] for b in scanned['blocks']) and not _partial(scanned)
    clean = read_pdf(FIX / 'p02_sample.pdf', ocr='off')
    assert clean['warnings'] == []


@pytest.mark.skipif(ocr_languages() is None, reason='локальный OCR недоступен: нет tessdata rus/eng')
def test_optional_ocr_recovers_scan_with_coordinates(tmp_path):
    path = builders.scan_mixed(tmp_path / 'mixed.pdf')
    doc = read_pdf(path)
    assert ('page_ocr', 2) in _codes(doc) and ('ocr_required', 2) not in _codes(doc)
    ocr_blocks = [b for b in doc['blocks'] if b['loc']['page'] == 2 and b['loc'].get('ocr')]
    assert ocr_blocks
    # Скан — растровая копия страницы 2 фикстуры: слово OCR стоит там же, где слово текстового слоя.
    word = next(b for b in ocr_blocks if 'составляет' in b['text'])
    loc = locate_span(word, *_span(word, 'составляет'))
    original = _word_boxes(pymupdf.open(FIX / 'p02_sample.pdf')[1], 'составляет')
    assert max(_iou(loc['rects'][0], box) for box in original) > 0.5


# --------------------------------------------------------------------------- перевод диапазонов и контракт
def test_locate_span_partial_word_and_page_only(sample_doc):
    block = _find(sample_doc, PHRASE, page=1)[0]
    start = block['text'].index('составляет')
    part = locate_span(block, start, start + 5)
    whole = locate_span(block, start, start + 10)
    assert part['precision'] == 'approx' and part['rects'][0][0] == whole['rects'][0][0]
    assert part['rects'][0][2] < whole['rects'][0][2]
    stripped = {'id': block['id'], 'text': block['text'], 'loc': {'page': 1, 'fragments': []}}
    only_page = locate_span(stripped, 0, 5)
    assert only_page['precision'] == 'page' and only_page['rects'] == [] and only_page['page'] == 1
    assert only_page['warning']['code'] == 'locate_page_only' and only_page['warning']['page'] == 1
    assert page_only_warning('b0042', 3, 'текст')['message'].startswith('Цитата «текст» из блока b0042')


@pytest.mark.parametrize('name', ALL_FIXTURES)
def test_contract_v1(name):
    doc = read_pdf(FIX / name, ocr='off')
    validate(doc, 'Document')
    assert doc['id'] == hashlib.sha256((FIX / name).read_bytes()).hexdigest() and doc['format'] == 'pdf'
    ids = [b['id'] for b in doc['blocks']]
    assert ids == [f'b{i:04d}' for i in range(1, len(ids) + 1)]
    for block in doc['blocks']:
        for frag in block['loc']['fragments']:
            assert 0 <= frag['start'] < frag['end'] <= len(block['text'])
            piece = block['text'][frag['start']:frag['end']]
            assert piece == piece.strip() and not re.search(r'\s', piece)
            x0, y0, x1, y1 = frag['rect']
            assert x0 <= x1 and y0 <= y1
    json.dumps(doc, ensure_ascii=False)


def test_deterministic(sample_doc):
    assert read_pdf(FIX / 'p02_sample.pdf', ocr='off') == sample_doc


def test_case_document_printed_by_chromium():
    """Выданный кейс (A + B), напечатанный из браузера: требования дословно, все ₸, колонтитулы отделены."""
    doc = read_pdf(FIX / 'case_requirements_chromium.pdf', ocr='off')
    assert doc['extraction']['completeness'] == 1.0 and not doc['warnings']
    expected = {
        'Ф-1.': 'Ф-1. Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно. '
                'По умолчанию уведомление выключено.',
        'Ф-4.': 'Ф-4. При изменении порога накопленная сумма сохраняется. Если она ниже нового порога, следующее '
                'достижение вызывает push независимо от истории предыдущей настройки.',
    }
    for rid, text in expected.items():
        block = next(b for b in doc['blocks'] if b['text'].startswith(rid))
        assert block['text'] == text and block['kind'] == 'list_item'
        assert block['section'][-1] == 'Функциональные требования'
    content = [b for b in doc['blocks'] if not b['loc'].get('furniture')]
    assert sum(b['text'].count('₸') for b in content) == 12
    furniture = {b['text'] for b in doc['blocks'] if b['loc'].get('furniture')}
    assert furniture >= {'27.11.2026, 10:00', 'file:///requirements.html', '1/6'}
    rest = _find(doc, 'REST type | GET')[0]
    assert rest['loc']['table']['header'] == ['Поле', 'Значение'] and rest['section'][-1] == 'Общие параметры'
    checklist = [b['loc']['table'] for b in doc['blocks'] if b['loc'].get('table', {}).get('id') == 'T3']
    assert {t['part'] for t in checklist} == {1, 2} and max(t['row'] for t in checklist) == 14
    assert _find(doc, '{"message":"Карта не найдена"}')[0]['kind'] == 'code'


def test_cli_diagnose_exit_codes(capsys, tmp_path):
    assert main([str(FIX / 'p02_sample.pdf'), '--diagnose', '--ocr', 'off']) == 0
    assert json.loads(capsys.readouterr().out)['ok'] is True
    assert main([str(FIX / 'p02_scan_mixed.pdf'), '--diagnose', '--ocr', 'off']) == 5
    assert json.loads(capsys.readouterr().out)['code'] == 'partial'
    scan = builders.all_scan(tmp_path / 'scan.pdf')
    assert main([str(scan), '--diagnose', '--ocr', 'off']) == 1
    out = json.loads(capsys.readouterr().out)
    assert out['code'] == 'no_text' and out['pages'] == [1, 2]
