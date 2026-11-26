"""Одна сумма в разных местах PDF: точная страница, строка таблицы и координаты каждого вхождения.

Малый пример p02_amounts.pdf (генератор make_fixtures.py → p02_amounts.expected.json, рамки глифов
из метрик шрифта, независимо от PyMuPDF): «50 000 ₸» в строках 1, 3, 8 таблицы, в абзацах, в нижнем
колонтитуле каждой страницы, в строке 13, перенесённой на стр. 2, и в таблице «Поле | Значение» под
жирным заголовком. Доказанные расхождения прежнего кода (fff7197):

* PyMuPDF 2.x не видит таблицу из одной строки: строка 13 на стр. 2 читалась тремя абзацами без
  таблицы и номера строки (на 1.26.5 — верно);
* PyMuPDF принимает жирный заголовок над таблицей за «внешнюю» шапку: «Поле | Значение» становилась
  строкой данных, у таблицы не было имён колонок (обе версии; так же в release/input/requirements.pdf).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from bcc_review.contracts import validate
from bcc_review.readers.pdf import locate_span, read_pdf

HERE = Path(__file__).resolve().parent
PDF = HERE / 'fixtures' / 'p02_amounts.pdf'
TRUTH = json.loads((HERE / 'fixtures' / 'p02_amounts.expected.json').read_text(encoding='utf-8'))
AMOUNT = TRUTH['amount']
TEAM_PDF = HERE.parents[1] / 'release' / 'input' / 'requirements.pdf'
TEAM_SHA = 'fbca9c8282f440754d43c2ec689a27a9ccc32ac07a1c4b30a7ca22c21d7e4de2'   # release/README.md


@pytest.fixture(scope='module')
def doc() -> dict:
    return read_pdf(PDF, ocr='off')


def _iou(a, b) -> float:
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    inter = area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))
    return inter / (area(a) + area(b) - inter) if inter else 0.0


def words_at(page: pymupdf.Page, rect) -> list[str]:
    """Слова страницы, центр которых внутри прямоугольника (повторное чтение без рендера).

    Не clip: у шрифтов с большим межстрочным полем (CharisSIL в командной копии) рамки глифов
    соседних строк перекрываются на несколько пунктов, и clip захватывает слово строкой выше.
    """
    return [w[4] for w in page.get_text('words')
            if rect[0] <= (w[0] + w[2]) / 2 <= rect[2] and rect[1] <= (w[1] + w[3]) / 2 <= rect[3]]


def occurrences(doc: dict, needle: str) -> list[dict]:
    """Каждое вхождение: блок, диапазон, страница, место (таблица/строка, колонтитул, абзац), рамки."""
    out = []
    for block in doc['blocks']:
        start = block['text'].find(needle)
        while start >= 0:
            where = locate_span(block, start, start + len(needle))
            table = block['loc'].get('table')
            out.append({'block_id': block['id'], 'start': start, 'end': start + len(needle),
                        'page': block['loc']['page'], 'kind': block['kind'],
                        'furniture': bool(block['loc'].get('furniture')),
                        'table': table['id'] if table else None, 'row': table['row'] if table else None,
                        'columns': table.get('columns') if table else None,
                        'rects': where['rects'], 'precision': where['precision']})
            start = block['text'].find(needle, start + 1)
    return out


def test_every_amount_has_block_page_row_and_coordinates(doc):
    validate(doc, 'Document')
    found = occurrences(doc, AMOUNT)
    assert len(found) == len(TRUTH['occurrences']) == 9
    tables = {}
    for truth in TRUTH['occurrences']:
        hits = [o for o in found if o['page'] == truth['page'] and len(o['rects']) == 1
                and _iou(o['rects'][0], truth['glyphs']) > 0.95]
        assert len(hits) == 1, truth
        hit = hits[0]
        assert hit['precision'] == 'exact'
        if truth['where'] == 'footer':
            assert hit['furniture'] and hit['kind'] == 'other' and hit['table'] is None
        elif truth['where'] == 'paragraph':
            assert hit['kind'] == 'paragraph' and not hit['furniture']
        else:
            assert hit['kind'] == 'table_row' and hit['row'] == truth['row'], (truth, hit)
            tables.setdefault(truth['table'], set()).add(hit['table'])
    assert all(len(ids) == 1 for ids in tables.values()) and len({next(iter(v)) for v in tables.values()}) == 2
    footers = [o for o in found if o['furniture']]
    assert [o['page'] for o in footers] == [1, 2] and footers[0]['rects'] == footers[1]['rects']
    assert footers[0]['block_id'] != footers[1]['block_id']


def test_last_row_moved_to_next_page_stays_in_its_table(doc):
    rows = [b for b in doc['blocks'] if b['loc'].get('table') and b['text'].split(' | ')[0].isdigit()]
    assert [b['loc']['table']['row'] for b in rows] == list(range(1, 14))
    assert len({b['loc']['table']['id'] for b in rows}) == 1
    moved = rows[-1]
    table = moved['loc']['table']
    assert moved['loc']['page'] == 2 and moved['kind'] == 'table_row' and table['part'] == 2
    assert table['link'] == 'header_carried' and table['header_source'] == 'page 1'
    cells = {table['header'][c['col']]: moved['text'][c['start']:c['end']] for c in table['cells']}
    assert cells == {'№': '13', 'Операция': 'Покупка техники', 'Сумма, ₸': AMOUNT}
    assert not [b for b in doc['blocks'] if b['loc']['page'] == 2 and b['text'] in ('13', 'Покупка техники', AMOUNT)]


def test_bold_heading_above_table_is_not_its_header(doc):
    header = next(b for b in doc['blocks'] if b['text'] == 'Поле | Значение')
    row = next(b for b in doc['blocks'] if b['text'] == f'Лимит | {AMOUNT}')
    heading = next(b for b in doc['blocks'] if b['text'] == '2. Сведения о карте')
    assert header['kind'] == 'table_header' and heading['kind'] == 'heading'
    assert row['loc']['table']['row'] == 2 and row['loc']['table']['columns'] == ['Поле', 'Значение']
    assert row['loc']['table']['id'] == header['loc']['table']['id'] != heading['loc'].get('table')


def test_pair_for_p14_rereads_to_the_same_words(doc):
    """Пара для №14: блок, диапазон и прямоугольник; повторное чтение текста в рамке — без рендера."""
    moved = next(o for o in occurrences(doc, AMOUNT) if o['page'] == 2 and o['kind'] == 'table_row' and o['row'] == 13)
    assert (moved['block_id'], moved['start'], moved['end']) == ('b0020', 23, 31)
    rect = moved['rects'][0]
    truth = next(t for t in TRUTH['occurrences'] if t['where'] == 'table' and t['row'] == 13)
    assert _iou(rect, truth['glyphs']) > 0.95 and all(abs(a - b) <= 0.05 for a, b in zip(rect, truth['glyphs']))
    page = pymupdf.open(PDF)[1]
    assert [w[4] for w in page.get_text('words', clip=pymupdf.Rect(rect))] == ['50', '000', '₸']
    assert words_at(page, rect) == ['50', '000', '₸']


def test_fragment_without_coordinates_gets_page_only_warning(doc):
    row = next(b for b in doc['blocks'] if b['id'] == 'b0020')
    gap = row['text'].index(' | ')
    separator = locate_span(row, gap, gap + 3)            # разделитель ячеек: глифов на странице нет
    assert separator['precision'] == 'page' and separator['rects'] == [] and separator['page'] == 2
    warning = separator['warning']
    assert (warning['code'], warning['page'], warning['block_id']) == ('locate_page_only', 2, 'b0020')
    assert 'только к странице 2' in warning['message']
    no_layer = dict(row, loc={'page': 2, 'fragments': []})   # блок без координат слов (скан, чужой reader)
    start = row['text'].index(AMOUNT)
    result = locate_span(no_layer, start, start + len(AMOUNT))
    assert result['precision'] == 'page' and result['warning']['code'] == 'locate_page_only'
    assert f'«{AMOUNT}»' in result['warning']['message']
    cut = locate_span(row, start + 1, start + 5)           # «0 00» режет слова: точность приблизительная
    assert cut['precision'] == 'approx' and cut['warning'] is None and len(cut['rects']) == 1


@pytest.mark.skipif(not TEAM_PDF.exists() or hashlib.sha256(TEAM_PDF.read_bytes()).hexdigest() != TEAM_SHA,
                    reason='release/input/requirements.pdf (fbca9c82…) есть в bcc/integration с 2821989')
def test_team_pdf_copy_repeats_and_header():
    team = read_pdf(TEAM_PDF, ocr='off')
    validate(team, 'Document')
    first = next(b for b in team['blocks'] if b['loc']['page'] == 1 and b['loc'].get('table'))
    assert first['kind'] == 'table_header' and first['text'] == 'Поле | Значение'
    repeat = [o for o in occurrences(team, AMOUNT)]
    assert [(o['page'], o['block_id'], o['row'], o['start']) for o in repeat] == [(2, 'b0041', 1, 24), (2, 'b0041', 1, 70)]
    assert all(o['precision'] == 'exact' for o in repeat)
    page2 = pymupdf.open(TEAM_PDF)[1]
    for o in repeat:
        assert words_at(page2, o['rects'][0]) == ['50', '000', '₸']
    raw = [(o['page'], o['kind']) for o in occurrences(team, '50000')]
    assert raw == [(4, 'table_row'), (5, 'code')]


def test_engine_and_evidence_end_to_end(tmp_path):
    """Сквозной сценарий в интеграции: движок (offline-lint, без сети) читает PDF штатным read_pdf,
    №07 привязывает цитату «50 000 ₸»: с block_id — к перенесённой строке, без него — неоднозначно.

    Пропускается, пока в ветке нет движка и №07 (в bcc/integration с 6be9e97 есть).
    """
    engine = pytest.importorskip('bcc_review.engine')
    evidence = pytest.importorskip('bcc_review.analysis.evidence')
    from bcc_review import contracts
    report = contracts.as_plain(engine.run_review(PDF, tmp_path / 'report.md', options=contracts.RunOptions.coerce(
        {'provider': 'none', 'offline_lint': True, 'use_cache': False, 'trace': False})))
    assert report['run']['modules']['read_pdf'] == 'team:bcc_review.readers.pdf:read_pdf'
    document = report['document']
    moved = next(b for b in document['blocks'] if b['id'] == 'b0020')
    assert (moved['loc']['page'], moved['loc']['columns']) == (2, ['№', 'Операция', 'Сумма, ₸'])
    matched = evidence.resolve_hint(document, {'block_id': 'b0020', 'quote': AMOUNT})
    assert matched['status'] == 'matched'
    assert matched['evidence'] == {'block_id': 'b0020', 'start': 23, 'end': 31, 'quote': AMOUNT}
    loose = evidence.resolve_hint(document, {'block_id': None, 'quote': AMOUNT})
    assert loose['status'] == 'ambiguous'
    pages = {b['id']: b['loc']['page'] for b in document['blocks']}
    assert sorted(pages[o['block_id']] for o in loose['occurrences']) == [1, 1, 1, 1, 1, 2, 2, 2, 2]
