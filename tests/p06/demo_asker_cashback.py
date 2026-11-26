"""Сквозной сценарий №06 через настоящий Asker на записанном транспорте: три случая про кэшбэк.

    python tests/p06/demo_asker_cashback.py

Ответы модели — из кассеты tests/p06/fixtures/cassette_cashback.json (имитация для разработческой проверки).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from test_p06_asker_cashback import run_scenario  # noqa: E402


def main() -> int:
    total = 0
    for name in ("cashback_two_dates", "cashback_by_operation", "cashback_missing_rule"):
        doc, inv, res, transport, stats, budget = run_scenario(name)
        lines = {b["id"]: b["loc"].get("line_start") for b in doc["blocks"]}
        total += len(transport.requests)
        print(f"=== {name}: вызовов двойника {len(transport.requests)} "
              f"({', '.join(r['stage'] for r in transport.requests)}); этап cross: calls={stats.stages['cross'].calls}, "
              f"cache_hits={stats.stages['cross'].cache_hits}; опоры: {res['evidence_audit']['checked']} проверено, "
              f"{res['evidence_audit']['rejected']} отклонено")
        for c in res["candidates"]:
            print(f"  [{c['subkind']} · {c['kind']} · {c['criterion']} · {c['severity']}] {c['title']}"
                  + (f"  (подтверждено: {', '.join(c['confirmed_by'])})" if c.get("confirmed_by") else ""))
            w = c.get("witness")
            if w:
                for side in ("a", "b"):
                    ev = w[f"evidence_{side}"]
                    print(f"    {side.upper()}: {ev['block_id']}[{ev['start']}:{ev['end']}] строка {lines[ev['block_id']]}: «{ev['quote']}»")
                print(f"    объект: {c['cause']['object']}")
                print(f"    влияние: {c['impact']}")
                print(f"    блокирует решение: {c['blocked_decision']}")
            if c.get("inspected_scope"):
                print(f"    просмотрено: {c['inspected_scope']['span']}; разделы: {'; '.join(c['inspected_scope']['sections'])}")
                print(f"    искали: {'; '.join(c['searched_for'])}")
                print(f"    опоры: {' | '.join(h['quote'] for h in c['hints'])}")
            if c.get("question"):
                print(f"    вопрос №08: {c['question']}")
        for x in res["comparisons"]:
            if x["aspect"] in ("period_anchor", "semantic") and x["verdict"] == "compatible":
                print(f"  совместимо ({x['aspect']}): {x['explanation'][:200]}")
    print(f"=== итого физических вызовов двойника: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
