"""Стык №02 ↔ №07: подсказка {block_id, quote} → Evidence (№07) → прямоугольники (№02).

Пропускается, пока модуля №07 (bcc_review.analysis.evidence) нет в ветке. Проверено вручную
с ветки bcc/p07-evidence@cfebfff (см. tests/p02/README.md).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from bcc_review.readers.pdf import locate_span, read_pdf

evidence = pytest.importorskip('bcc_review.analysis.evidence')
FIX = Path(__file__).resolve().parent / 'fixtures'


def test_hint_from_page_two_resolves_and_highlights_on_page_two(tmp_path):
    doc = read_pdf(FIX / 'p02_sample.pdf', ocr='off')
    block = next(b for b in doc['blocks'] if b['loc']['page'] == 2 and 'Порог уведомления' in b['text'])
    result = evidence.resolve_hint(doc, {'block_id': block['id'], 'quote': 'Порог уведомления составляет 75 000 ₸'})
    assert result['status'] == 'matched'
    ev = result['evidence']
    assert ev['block_id'] == block['id'] and block['text'][ev['start']:ev['end']] == ev['quote']
    rects = locate_span(block, ev['start'], ev['end'])
    assert rects['page'] == 2 and rects['precision'] == 'exact' and len(rects['rects']) == 2
    where = evidence.locate(doc, ev)
    assert where['page'] == 2 and where['rects']           # №07 видит ту же страницу и фрагменты
    pdf = pymupdf.open(FIX / 'p02_sample.pdf')
    for rect in rects['rects']:
        pdf[1].add_highlight_annot(pymupdf.Rect(rect))
    pdf.save(tmp_path / 'joint.pdf')
    page = pymupdf.open(tmp_path / 'joint.pdf')[1]
    words = [w[4] for annot in page.annots() for w in page.get_text('words', clip=annot.rect)]
    assert words == ['Порог', 'уведомления', 'составляет', '75', '000', '₸']


def test_same_quote_on_two_pages_is_ambiguous_without_block():
    doc = read_pdf(FIX / 'p02_sample.pdf', ocr='off')
    result = evidence.resolve_hint(doc, {'block_id': None, 'quote': 'Порог уведомления составляет'})
    assert result['status'] in ('ambiguous', 'matched')
    if result['status'] == 'ambiguous':
        pages = {next(b for b in doc['blocks'] if b['id'] == o['block_id'])['loc']['page'] for o in result['occurrences']}
        assert pages == {1, 2}
