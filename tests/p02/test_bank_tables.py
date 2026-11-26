"""Соседние таблицы одной сетки на стыке страниц (p02_bank_tables.pdf).

Риск: «Операция | Сумма, ₸» в конце стр. 1 и «Код HTTP | Причина» в начале стр. 2 имеют одно
число колонок и одни границы. До правки (288d727) вторая таблица считалась продолжением T1:
шапка «Код HTTP | Причина» становилась строкой данных T1 (row 11), а «409 | Повтор события» —
строкой 13 T1 с колонками «Операция» и «Сумма, ₸». Эталон связок и контрольные области ячеек
пишет сам генератор (make_fixtures.py → p02_bank_tables.expected.json), независимо от PyMuPDF.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from bcc_review import contracts
from bcc_review.contracts import validate
from bcc_review.readers.pdf import locate_span, read_pdf

FIX = Path(__file__).resolve().parent / 'fixtures'
PDF = FIX / 'p02_bank_tables.pdf'
TRUTH = json.loads((FIX / 'p02_bank_tables.expected.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def doc() -> dict:
    return read_pdf(PDF, ocr='off')


def _rows(doc: dict) -> list[dict]:
    return [b for b in doc['blocks'] if b['loc'].get('table')]


def _row(doc: dict, prefix: str) -> dict:
    return next(b for b in _rows(doc) if b['text'].startswith(prefix))


def _cells(block: dict) -> dict[str, str]:
    """Значения строки по именам колонок её таблицы."""
    table = block['loc']['table']
    return {table['header'][c['col']]: block['text'][c['start']:c['end']] for c in table['cells']}


def _iou(a, b) -> float:
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    inter = area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))
    return inter / (area(a) + area(b) - inter) if inter else 0.0


def _inside(rect, area, pad: float = 0.5) -> bool:
    return area[0] - pad <= rect[0] and area[1] - pad <= rect[1] and rect[2] <= area[2] + pad and rect[3] <= area[3] + pad


def test_adjacent_table_with_own_header_is_a_new_table(doc):
    validate(doc, 'Document')
    operations = _row(doc, 'Покупка №10')
    header = _row(doc, 'Код HTTP')
    row = _row(doc, '409')
    assert operations['loc']['page'] == 1 and operations['loc']['table']['id'] == 'T1'
    assert header['kind'] == 'table_header' and header['loc']['page'] == 2
    table = row['loc']['table']
    assert row['kind'] == 'table_row' and row['loc']['page'] == 2
    assert table['id'] == 'T2' != operations['loc']['table']['id'] and table['part'] == 1 and table['row'] == 2
    assert table['header'] == table['columns'] == ['Код HTTP', 'Причина'] and table['header_source'] == 'same_page'
    assert table['link'] == 'new_header' and table['adjacent_to'] == 'T1'
    assert _cells(row) == {'Код HTTP': '409', 'Причина': 'Повтор события'}
    assert row['text'] == '409 | Повтор события'
    assert not any(w['code'] == 'table_continuation_uncertain' and w.get('page') == 2 for w in doc['warnings'])


def test_true_continuations_keep_id_and_row_numbers(doc):
    limits = [b['loc']['table'] for b in _rows(doc) if b['loc']['table']['id'] == _row(doc, 'Карта *1001')['loc']['table']['id']]
    assert [t['row'] for t in limits if not t['header_row']] == list(range(1, 14))
    assert {t['part'] for t in limits} == {1, 2} and sum(bool(t.get('repeated_header')) for t in limits) == 1
    cont = _row(doc, 'Карта *1011')
    assert cont['loc']['page'] == 4 and cont['loc']['table']['link'] == 'repeated_header'
    assert _cells(cont) == {'Карта': 'Карта *1011', 'Лимит, ₸': '550 000'}

    debit = _row(doc, '11.11.2026')
    first = _row(doc, '01.11.2026')
    assert debit['loc']['page'] == 6 and debit['loc']['table']['id'] == first['loc']['table']['id']
    assert debit['loc']['table']['row'] == 11 and debit['loc']['table']['header_source'] == 'page 5'
    assert debit['loc']['table']['link'] == 'header_carried'
    assert _cells(debit) == {'Дата': '11.11.2026', 'Списание, ₸': '7700 ₸'}


def test_ambiguous_seam_keeps_values_and_marks_link_uncertain(doc):
    key = _row(doc, 'Ключ')
    table = key['loc']['table']
    previous = _row(doc, 'Параметр 10')['loc']['table']
    assert key['loc']['page'] == 8 and key['kind'] == 'table_row' and key['text'] == 'Ключ | Описание'
    assert table['id'] != previous['id'] and table['link'] == 'uncertain' and table['maybe_continues'] == previous['id']
    assert table['header'] is None and 'columns' not in table and not table['header_restored']
    warning = next(w for w in doc['warnings'] if w['code'] == 'table_continuation_uncertain')
    assert warning['page'] == 8 and warning['pages'] == [7, 8] and warning['maybe_continues'] == previous['id']
    expected = TRUTH['cells']['Ключ'][0]
    assert _iou(locate_span(key, 0, 4)['rects'][0], expected['glyphs']) > 0.95
    summary = {t['id']: t for t in doc['extraction']['tables']}
    assert summary[table['id']]['maybe_continues'] == previous['id'] and not summary[table['id']]['header_restored']


def test_tables_match_generator_truth(doc):
    """Каждая таблица эталона — одна логическая таблица читалки на своих страницах, с той же шапкой."""
    by_first_page: dict[int, dict] = {}
    for block in _rows(doc):
        by_first_page.setdefault(block['loc']['page'], block['loc']['table'])
    ids = {}
    for entry in TRUTH['tables']:
        tables = [by_first_page[p] for p in entry['pages']]
        assert len({t['id'] for t in tables}) == 1, entry['name']
        ids[entry['name']] = tables[0]['id']
        assert tables[0]['header'] == entry.get('header'), entry['name']
        if entry.get('link'):
            assert tables[-1]['link'] == entry['link'], entry['name']
    assert len(set(ids.values())) == len(ids)               # разные таблицы эталона — разные ID
    assert by_first_page[8]['maybe_continues'] == ids['params']


def test_409_coordinates_match_generator_control_area(doc, tmp_path):
    row = _row(doc, '409')
    digits = row['text'].index('409')
    where = locate_span(row, digits, digits + 3)
    control = TRUTH['cells']['409'][0]
    assert (where['page'], where['precision'], len(where['rects'])) == (control['page'], 'exact', 1)
    rect = where['rects'][0]
    assert _inside(rect, control['cell']) and _iou(rect, control['glyphs']) > 0.95
    reason = _row(doc, '409')['text'].index('Повтор события')
    reason_rect = locate_span(row, reason, reason + len('Повтор события'))['rects'][0]
    assert _iou(reason_rect, TRUTH['cells']['Повтор события'][0]['glyphs']) > 0.95
    # Как №14: подсветка, сохранение, повторное открытие — под рамкой ровно «409».
    pdf = pymupdf.open(PDF)
    pdf[1].add_highlight_annot(pymupdf.Rect(rect))
    pdf.save(tmp_path / 'p409.pdf')
    page = pymupdf.open(tmp_path / 'p409.pdf')[1]
    assert [[w[4] for w in page.get_text('words', clip=a.rect)] for a in page.annots()] == [['409']]


@pytest.mark.skipif(not hasattr(contracts, 'normalize_document'),
                    reason='normalize_document есть в bcc/integration с 6be9e97, в этой ветке контракт 3e6b569')
def test_engine_normalization_gives_http_columns(doc):
    """Стык с движком: normalize_document кладёт loc.table.columns в loc.columns для правил и чек-листа."""
    plain = contracts.normalize_document(json.loads(json.dumps(doc, ensure_ascii=False)))
    validate(plain, 'Document')
    row = next(b for b in plain['blocks'] if b['text'].startswith('409'))
    assert row['loc']['columns'] == ['Код HTTP', 'Причина']
    operation = next(b for b in plain['blocks'] if b['text'].startswith('Покупка №10'))
    assert operation['loc']['columns'] == ['Операция', 'Сумма, ₸']
    key = next(b for b in plain['blocks'] if b['text'] == 'Ключ | Описание')
    assert 'columns' not in key['loc']


def test_engine_and_annotated_pdf_put_409_on_page_two(tmp_path):
    """Сквозной стык в интеграции: движок (offline-lint, без сети и модели) → Report → экспорт №14.

    Опора F-409 = {b0019, [0, 3), "409"}; подсветка №14 должна лечь на стр. 2 ровно на «409».
    Пропускается, пока в ветке нет движка и экспорта №14 (в bcc/integration@6a6c503 есть).
    """
    engine = pytest.importorskip('bcc_review.engine')
    exporter = pytest.importorskip('bcc_review.exports.pdf')
    report = engine.run_review(PDF, tmp_path / 'report.md',
                               options=contracts.RunOptions.coerce({'provider': 'none', 'offline_lint': True,
                                                                    'use_cache': False, 'trace': False}))
    report = contracts.as_plain(report)
    assert report['run']['modules']['read_pdf'] == 'team:bcc_review.readers.pdf:read_pdf'
    row = next(b for b in report['document']['blocks'] if b['text'] == '409 | Повтор события')
    assert (row['id'], row['loc']['page'], row['loc']['columns']) == ('b0019', 2, ['Код HTTP', 'Причина'])
    finding = dict(report['findings'][0], id='F-409', title='Код 409 в таблице кодов HTTP',
                   evidence=[{'block_id': row['id'], 'start': 0, 'end': 3, 'quote': '409'}])
    report['findings'] = [finding]
    validate(report)
    assert contracts.evidence_errors(report) == []
    exporter.write_pdf(report, PDF, tmp_path / 'annotated.pdf')
    pdf = pymupdf.open(tmp_path / 'annotated.pdf')
    marks = [(page.number + 1, [w[4] for w in page.get_text('words', clip=a.rect)])
             for page in pdf for a in page.annots() if a.type[1] == 'Highlight']
    assert marks == [(2, ['409'])]
