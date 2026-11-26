"""Порог 1 000 ₸ и четыре границы в разных строках: знак, значение и единица против текста и страницы.

Фикстуры (make_fixtures.py: build_boundaries, эталоны *.expected.json — рамки по метрикам шрифта,
независимо от PyMuPDF):

* p02_boundaries.pdf — таблица «№ | Сумма операции, ₸ | Действие», строки «≥ 1 000», «< 1 000»,
  «≤ 1 000» на стр. 1 и «> 1 000» на стр. 2 (перенос без повтора шапки); единица только в шапке;
  между знаком и числом и между разрядами — U+00A0; шрифт DejaVu Sans, в нём есть все эти глифы;
* p02_boundaries_unsupported.pdf — то же, но в строке 1 знак «⩾» набран шрифтом без этого глифа
  (Liberation Sans): на странице .notdef, в текстовом слое знака нет.

Сначала проверяется сам PDF (глифы и NBSP в текстовом слое), потом читалка и путь движка.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf
import pytest

from bcc_review.contracts import PARTIAL_READ_CODES, validate
from bcc_review.readers.pdf import locate_span, read_pdf

HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures'
PDF = FIX / 'p02_boundaries.pdf'
UNSUPPORTED = FIX / 'p02_boundaries_unsupported.pdf'
SHA = {PDF.name: 'ac6108159402556a82d90e76ac1a598127273ba919dc2368433a329de50379df',
       UNSUPPORTED.name: '263ebb8e7bd4fa0391586be36caa984d49a74cb374211c7984ed86c44f1aee37'}
TRUTH = {path.name: json.loads(path.with_suffix('.expected.json').read_text(encoding='utf-8'))
         for path in (PDF, UNSUPPORTED)}
NBSP = '\u00a0'
SIGNS = '≥<≤>'
UNIT_COLUMN = 'Сумма операции, ₸'


@pytest.fixture(scope='module')
def doc() -> dict:
    return read_pdf(PDF, ocr='off')


@pytest.fixture(scope='module')
def bad() -> dict:
    return read_pdf(UNSUPPORTED, ocr='off')


def _close(a, b, tol: float = 0.05) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _sign_chars(path: Path) -> list[dict]:
    """Знак каждой строки таблицы прямо из потока глифов PDF (texttrace): код Unicode, номер глифа, рамка."""
    out = []
    for page in pymupdf.open(path):
        for span in page.get_texttrace():
            chars = span['chars']
            text = ''.join(chr(c[0]) for c in chars)
            for i, (ucs, gid, _, bbox) in enumerate(chars):
                if abs(bbox[0] - 101.0) < 0.05 and (text[i + 1:].startswith(f'{NBSP}1{NBSP}000') or len(chars) == 1):
                    out.append({'page': page.number + 1, 'ucs': ucs, 'gid': gid, 'font': span['font'],
                                'bbox': [round(v, 2) for v in bbox]})
    return out


# --------------------------------------------------------------------------- сначала сам PDF
@pytest.mark.parametrize('path', [PDF, UNSUPPORTED], ids=['main', 'unsupported'])
def test_fixture_bytes_are_pinned(path):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SHA[path.name]


def test_source_pdf_draws_real_glyphs_and_keeps_nbsp():
    """До сравнения с читалкой: в PDF стоят настоящие глифы ≥ < ≤ > (не .notdef), ширина — как у глифа
    DejaVu Sans по метрикам reportlab, в текстовом слое U+00A0 сохранён (reportlab сам его теряет)."""
    truth = TRUTH[PDF.name]
    assert {k: v for k, v in truth['fonts']['DejaVuSans.ttf']['glyph_ids'].items() if k != 'U+2A7E'} == {
        'U+2265': 3312, 'U+2264': 3311, 'U+003C': 31, 'U+003E': 33, 'U+20B8': 2958, 'U+00A0': 3}
    signs = _sign_chars(PDF)
    assert [(s['page'], chr(s['ucs'])) for s in signs] == [(1, '≥'), (1, '<'), (1, '≤'), (2, '>')]
    for sign, cond in zip(signs, truth['conditions']):
        assert sign['gid'] != 0 and sign['font'] == 'DejaVuSans', sign
        assert _close(sign['bbox'], cond['sign_glyphs']), (sign, cond)
    doc = pymupdf.open(PDF)
    layer = ''.join(page.get_text('text', flags=pymupdf.TEXT_PRESERVE_WHITESPACE) for page in doc)
    for sign in SIGNS:
        assert f'{sign}{NBSP}1{NBSP}000' in layer
    assert f'1{NBSP}000{NBSP}₸' in layer and UNIT_COLUMN in layer
    unit = [c for page in doc for span in page.get_texttrace() if 'Bold' in span['font']
            for c in span['chars'] if c[0] == ord('₸')]
    assert len(unit) == 1 and unit[0][1] != 0                           # ₸ шапки — тоже настоящий глиф


def test_source_pdf_check_catches_missing_glyph():
    """Та же проверка на варианте без глифа: знак строки 1 — .notdef (номер глифа 0), остальные целы."""
    truth = TRUTH[UNSUPPORTED.name]
    assert truth['fonts']['LiberationSans-Regular.ttf']['glyph_ids']['U+2A7E'] is None
    first = truth['conditions'][0]
    assert (first['sign'], first['visible'], first['glyph_id']) == ('⩾', '.notdef', None)
    signs = _sign_chars(UNSUPPORTED)
    assert signs[0]['gid'] == 0 and signs[0]['font'] == 'LiberationSans' and signs[0]['ucs'] in (0, 0xFFFD)
    assert [chr(s['ucs']) for s in signs[1:]] == ['<', '≤', '>'] and all(s['gid'] for s in signs[1:])


def test_independent_extractor_sees_the_same_layer():
    """pdfminer (другой разборщик) видит те же знаки и U+00A0; знака без глифа в его тексте нет."""
    high = pytest.importorskip('pdfminer.high_level')
    layout = pytest.importorskip('pdfminer.layout')

    def cells(path):
        return [(page, el.get_text().strip()) for page, items in enumerate(high.extract_pages(path), 1)
                for el in items if isinstance(el, layout.LTTextContainer) and el.get_text().strip().endswith(f'1{NBSP}000')]
    assert cells(PDF) == [(1, f'{s}{NBSP}1{NBSP}000') for s in '≥<≤'] + [(2, f'>{NBSP}1{NBSP}000')]
    assert cells(UNSUPPORTED)[0] == (1, f'\x00{NBSP}1{NBSP}000')


# --------------------------------------------------------------------------- читалка
def _rows(document: dict) -> dict[int, dict]:
    return {b['loc']['table']['row']: b for b in document['blocks'] if b['kind'] == 'table_row'}


def _condition(block: dict) -> dict:
    """Знак, значение и единица строки, как их видит потребитель Document: текст ячейки и имя колонки."""
    table = block['loc']['table']
    cell = next(c for c in table['cells'] if c['col'] == 1)
    text = block['text'][cell['start']:cell['end']]
    sign, value = text.split(' ', 1)
    return {'text': text, 'sign': sign, 'value': int(value.replace(' ', '')), 'start': cell['start'],
            'end': cell['end'], 'column': table['columns'][1], 'unit': table['columns'][1].rsplit(', ', 1)[-1]}


def test_four_conditions_keep_sign_value_unit_and_page(doc):
    validate(doc, 'Document')
    assert doc['warnings'] == [] and doc['extraction']['completeness'] == 1.0
    rows = _rows(doc)
    assert sorted(rows) == [1, 2, 3, 4] and {b['loc']['table']['id'] for b in rows.values()} == {'T1'}
    for truth in TRUTH[PDF.name]['conditions']:
        block = rows[truth['row']]
        got = _condition(block)
        assert block['loc']['page'] == truth['page']
        assert got['text'] == f'{truth["sign"]} 1 000'                       # NBSP → U+0020 (README: нормализация)
        assert f'U+{ord(got["sign"]):04X}' == truth['sign_codepoint']
        assert (got['value'], got['column'], got['unit']) == (1000, UNIT_COLUMN, truth['unit'])
        sign = locate_span(block, got['start'], got['start'] + 1)
        value = locate_span(block, got['start'] + 2, got['end'])
        assert sign['precision'] == value['precision'] == 'exact' and sign['page'] == truth['page']
        assert _close(sign['rects'][0], truth['sign_glyphs']) and _close(value['rects'][0], truth['value_glyphs'])
    # включительные и исключительные границы — разные строки, по одному знаку в строке
    assert [_condition(rows[r])['sign'] for r in (1, 2, 3, 4)] == list(SIGNS)
    assert all(sum(block['text'].count(s) for s in SIGNS) == 1 for block in rows.values())


def test_moved_row_takes_unit_from_header_on_previous_page(doc):
    moved = _rows(doc)[4]
    table = moved['loc']['table']
    assert (moved['loc']['page'], table['part'], table['link'], table['header_source']) == (2, 2, 'header_carried', 'page 1')
    assert table['header_restored']
    # PyMuPDF 2.x не видит таблицу из одной строки — её собирает _ruled_grids; 1.26.5 находит сам.
    assert table.get('source') == ('ruled_lines' if int(pymupdf.VersionBind.split('.')[0]) >= 2 else None)
    header = next(b for b in doc['blocks'] if b['kind'] == 'table_header')
    assert header['loc']['page'] == 1 and header['text'] == f'№ | {UNIT_COLUMN} | Действие'
    between = doc['blocks'][doc['blocks'].index(_rows(doc)[3]) + 1:doc['blocks'].index(moved)]
    assert [(b['kind'], b['loc'].get('furniture')) for b in between] == [('other', True), ('other', True)]


def test_threshold_definition_keeps_nbsp_value_and_unit(doc):
    truth = TRUTH[PDF.name]['threshold']
    block = next(b for b in doc['blocks'] if b['text'].startswith('Порог проверки'))
    assert block['kind'] == 'paragraph' and block['loc']['page'] == truth['page']
    assert block['text'] == truth['definition'].replace(NBSP, ' ')
    assert re.search(r'— 1 000 ₸ ', block['text'])


def test_unsupported_sign_warns_instead_of_guessing(doc, bad):
    """Знак без глифа: в тексте «�» на месте знака, decode_error со страницей и блоком; знак не подставлен
    ни из соседних строк («<», «≤»), ни из похожего «≥»; остальные три условия как в основной фикстуре."""
    validate(bad, 'Document')
    rows, good = _rows(bad), _rows(doc)
    first = _condition(rows[1])
    assert first['text'] == '\ufffd 1 000' and first['sign'] == '\ufffd'
    assert not set(rows[1]['text']) & set(SIGNS + '⩾')
    assert (first['value'], first['unit'], rows[1]['loc']['page']) == (1000, '₸', 1)
    assert [rows[r]['text'] for r in (2, 3, 4)] == [good[r]['text'] for r in (2, 3, 4)]
    warnings = [w for w in bad['warnings'] if w['code'] == 'decode_error']
    assert len(warnings) == 1 and len(bad['warnings']) == 1
    warning = warnings[0]
    assert (warning['severity'], warning['page'], warning['count'], warning['block_ids']) == ('warning', 1, 1, [rows[1]['id']])
    assert warning['code'] in PARTIAL_READ_CODES and rows[1]['id'] in warning['message']
    place = locate_span(rows[1], first['start'], first['start'] + 1)    # место знака подсвечивается
    truth = TRUTH[UNSUPPORTED.name]['conditions'][0]['sign_glyphs']
    rect = place['rects'][0]
    assert place['precision'] == 'exact' and _close([rect[0], rect[2]], [truth[0], truth[2]])
    assert min(rect[3], truth[3]) - max(rect[1], truth[1]) > 0.9 * (truth[3] - truth[1])


# --------------------------------------------------------------------------- путь движка (bcc/integration)
def test_engine_load_keeps_signs_columns_and_warning(tmp_path):
    """Обычная загрузка движка (read_document и run_review --offline-lint): те же тексты, страницы и
    loc.columns; на варианте без глифа этап read = partial из-за decode_error с block_ids.

    Пропускается, пока в ветке нет движка (в bcc/integration есть).
    """
    engine = pytest.importorskip('bcc_review.engine')
    from bcc_review import contracts
    for path, stage in ((PDF, 'ok'), (UNSUPPORTED, 'partial')):
        direct = read_pdf(path, ocr='off')
        loaded = engine.read_document(path)
        report = contracts.as_plain(engine.run_review(path, tmp_path / f'{path.stem}.md', options=contracts.RunOptions.coerce(
            {'provider': 'none', 'offline_lint': True, 'use_cache': False, 'trace': False})))
        assert report['run']['modules']['read_pdf'] == 'team:bcc_review.readers.pdf:read_pdf'
        assert next(s for s in report['run']['stages'] if s['name'] == 'read')['status'] == stage
        for document in (loaded, report['document']):
            assert [(b['id'], b['text'], b['loc']['page']) for b in document['blocks']] == \
                   [(b['id'], b['text'], b['loc']['page']) for b in direct['blocks']]
            for row in _rows(document).values():
                assert row['loc']['columns'] == ['№', UNIT_COLUMN, 'Действие']
        if path is UNSUPPORTED:
            warning = next(w for w in report['document']['warnings'] if w['code'] == 'decode_error')
            assert warning['block_ids'] == ['b0006'] and report['run']['status'] == 'partial'
        markdown = (tmp_path / f'{path.stem}.md').read_text(encoding='utf-8')
        assert '\\< 1 000' in markdown and '\\> 1 000' in markdown and '≤ 1 000' in markdown


def test_p06_repro_reader_side_is_complete():
    """Воспроизведение для №06 (repro_p06_boundaries.py): половина №02 — четыре условия со знаком,
    значением, единицей и страницей. Что делает №06, тест не фиксирует: это печатает сам скрипт."""
    pytest.importorskip('bcc_review.engine')
    pytest.importorskip('bcc_review.analysis.facts')
    import repro_p06_boundaries as repro
    result = repro.reproduce(PDF)
    assert [(c['row'], c['page'], c['sign'], c['value'], c['unit'], c['table']) for c in result['reader']] == [
        (1, 1, '≥', '1000', '₸', 'T1'), (2, 1, '<', '1000', '₸', 'T1'), (3, 1, '≤', '1000', '₸', 'T1'),
        (4, 2, '>', '1000', '₸', 'T1')]
    assert len(result['p06']) == 4 and isinstance(result['lost'], list)
