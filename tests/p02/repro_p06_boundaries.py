"""Воспроизведение для №06: четыре границы порога 1 000 ₸ из PDF — что отдаёт №02 и что видит №06.

Запуск в bcc/integration (нужны движок и bcc_review.analysis.facts):

    python tests/p02/repro_p06_boundaries.py [PDF]      # по умолчанию fixtures/p02_boundaries.pdf

Печатает JSON: для каждого условия — блок, страница, строка таблицы, знак, значение и единица из шапки
по данным читалки (engine.read_document), затем — шапка таблицы, к которой №06 (facts.iter_tables)
отнёс эту строку, и факты reconcile_facts со ссылкой на этот блок. Код выхода 1, пока №06 теряет
знак или единицу хотя бы одного условия; 0 — когда все четыре дошли.

На fixtures/p02_boundaries.pdf (SHA-256 ac610815…) с bcc/integration@2821989 и веткой №06 2cdb9d3:
строка 4 (b0011, стр. 2, перенесена без повтора шапки) попадает в отдельную таблицу, где сама
становится шапкой ['4', '> 1 000', 'Уведомить мониторинг'] — между частями стоят колонтитулы b0009,
b0010, и смежность блоков рвётся, хотя у b0011 loc.table.id = T1, row = 4, loc.columns с «₸».
Ни одно из четырёх условий не становится фактом: «≥ < ≤ >» не разбираются, фактом стал только
абзац b0003 «Порог проверки — 1 000 ₸».
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF = HERE / 'fixtures' / 'p02_boundaries.pdf'
CELL = re.compile(r'^(?P<sign>\S)\s(?P<value>\d{1,3}(?:\s\d{3})*)$')


def reader_view(document: dict) -> list[dict]:
    """Условия из Document читалки: знак, значение и единица шапки (loc.columns) по каждой строке T1."""
    out = []
    for block in document['blocks']:
        table = block['loc'].get('table')
        if block['kind'] != 'table_row' or not table:
            continue
        cell = next(c for c in table['cells'] if c['col'] == 1)
        text = block['text'][cell['start']:cell['end']]
        match = CELL.match(text)
        column = block['loc'].get('columns', table.get('columns') or [None, None])[1]
        out.append({'block_id': block['id'], 'page': block['loc']['page'], 'table': table['id'], 'row': table['row'],
                    'link': table.get('link'), 'cell': text, 'sign': match['sign'] if match else None,
                    'value': match['value'].replace(' ', '') if match else None,
                    'unit': '₸' if column and column.rstrip().endswith('₸') else None, 'column': column})
    return out


def _facts():
    from bcc_review.analysis import facts  # модуль №06 есть в bcc/integration
    return facts


def p06_view(document: dict, conditions: list[dict], result: dict) -> list[dict]:
    """Что №06 делает с теми же строками: шапка таблицы iter_tables и факты reconcile_facts по блоку."""
    facts = _facts()
    tables = facts.iter_tables(facts.DocView(document))
    out = []
    for cond in conditions:
        bid = cond['block_id']
        table = next((t for t in tables if bid in t.block_ids), None)
        as_header = table is not None and any(c.block_id == bid for c in table.header)
        header = [c.text for c in table.header] if table else None
        cited = [f for f in result['facts']
                 if bid in {e.get('block_id') for e in (f['evidence'] if isinstance(f['evidence'], list) else [f['evidence']])
                            if isinstance(e, dict)}]
        unit_seen = bool(header) and not as_header and any(h.rstrip().endswith('₸') for h in header)
        out.append({'block_id': bid, 'table_header': header, 'row_used_as_header': as_header,
                    'unit_from_header': unit_seen,
                    'facts': [{k: f.get(k) for k in ('id', 'field', 'value', 'range', 'unit')} for f in cited]})
    return out


def reproduce(pdf: Path = PDF) -> dict:
    from bcc_review import engine
    document = engine.read_document(pdf)            # тот же путь, что у движка: read_pdf + normalize_document
    result = _facts().reconcile_facts(document, None)
    conditions = reader_view(document)
    seen = p06_view(document, conditions, result)
    lost = [{'block_id': c['block_id'], 'row': c['row'], 'page': c['page'], 'sign': c['sign'],
             'lost': [what for what, ok in (('unit', s['unit_from_header']), ('sign', bool(s['facts']))) if not ok]}
            for c, s in zip(conditions, seen)]
    return {'pdf': pdf.name, 'reader': conditions, 'p06': seen,
            'all_facts': [{k: f.get(k) for k in ('id', 'field', 'value', 'unit')} for f in result['facts']],
            'lost': [x for x in lost if x['lost']]}


def main(argv: list[str]) -> int:
    pdf = Path(argv[1]) if len(argv) > 1 else PDF
    report = reproduce(pdf)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report['lost'] else 0


if __name__ == '__main__':
    sys.path.insert(0, str(HERE.parents[1] / 'src'))
    raise SystemExit(main(sys.argv))
