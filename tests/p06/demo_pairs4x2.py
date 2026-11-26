"""Матрица 4×2 №06: путь каждого документа от фактов до результата проверки, в двух режимах.

    python tests/p06/demo_pairs4x2.py

Режим «правила» — модуль без модели. Режим «записанный транспорт» — настоящий Asker движка и кассета
tests/p06/fixtures/pairs4x2/cassette_pairs4x2.json: проверяет, что модуль делает с ответом модели,
а не то, найдёт ли дефект сама модель.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from bcc_review.runtime.modules import Modules  # noqa: E402
from test_p06_pairs4x2 import CASES, CATEGORIES, _line, conflicts, touches_pair, trace  # noqa: E402

RU = {"unit": "единицы", "event": "событие", "boundary": "граница", "status": "статус"}


def outcome(t: dict, mode: str) -> str:
    cs = [c for c in conflicts(t[mode]) if touches_pair(c, t["sides"])]
    if t["case"].endswith("_compatible"):
        n = len(conflicts(t[mode]))
        return "ложных 0" if n == 0 else f"ЛОЖНЫХ {n}"
    if not cs:
        return "пропуск"
    c = cs[0]
    kind = c.get("conflict_type") or c["subkind"]
    via = c["origin"] + (f"+{','.join(c['confirmed_by'])}" if c.get("confirmed_by") else "")
    return f"найден: {kind} ({via})"


def main() -> int:
    resolve = Modules().get("resolve_candidate").func
    traces = {case: trace(case) for case in CASES}
    for case in CASES:
        t = traces[case]
        doc = t["doc"]
        print(f"=== {case}")
        print("  1. факты по обеим сторонам пары:")
        for f in t["facts"]:
            r = f.range
            rng = f" {r['min']}..{r['max']} (вкл. {r['min_inclusive']}/{r['max_inclusive']})" if r else ""
            print(f"     {f.id} [{f.source}] «{f.field}» {f.unit or '—'}{rng}  ← «{f.evidence['quote']}»")
        if not t["facts"]:
            print("     — (числовых фактов нет: вид дефекта не числовой или формулировка не разобрана)")
        p = t["pair"]
        print(f"  2. отбор пары: {'отправлена модели' if p['selected'] else 'НЕ отправлена модели'}"
              f" ({p['how'] or 'вес ' + str(p['score'])}; отобрано {p['sent']} из {p['considered']})")
        for mode, title in (("rules", "правила"), ("recorded", "записанный транспорт")):
            extra = ""
            if mode == "recorded":
                extra = f"; ответ кассеты {'дошёл до модуля' if t['delivered'] else 'НЕ дошёл (пару не отправили)'}"
            print(f"  3–5. {title}: {outcome(t, mode)}{extra}")
            for c in conflicts(t[mode]):
                w = c["witness"]
                print(f"     вид: {c.get('conflict_type') or c['subkind']} · {c['criterion']} · {c['severity']} — {c['title']}")
                for side in ("a", "b"):
                    ev = w[f"evidence_{side}"]
                    print(f"     {side.upper()}: {ev['block_id']}[{ev['start']}:{ev['end']}] строка {_line(doc, ev)}: «{ev['quote']}»")
                print(f"     проверка: {c.get('checks')}; №07: {resolve(doc, c)['anchor_status']}")
            for x in t[mode]["comparisons"]:
                if x["aspect"] == "semantic":
                    print(f"     модуль: {x['verdict']} — {x['explanation'][:170]}")
    print("\n=== матрица 4×2 (правила | записанный транспорт)")
    print(f"{'вид':10s} | {'конфликт':58s} | совместимые правила")
    for cat in CATEGORIES:
        a, b = traces[f"{cat}_conflict"], traces[f"{cat}_compatible"]
        print(f"{RU[cat]:10s} | {outcome(a, 'rules') + ' | ' + outcome(a, 'recorded'):58s} | "
              f"{outcome(b, 'rules')} | {outcome(b, 'recorded')}")
    fp = sum(len(conflicts(traces[f'{c}_compatible'][m])) for c in CATEGORIES for m in ("rules", "recorded"))
    print(f"ложных срабатываний на четырёх согласованных парах (оба режима): {fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
