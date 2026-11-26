"""Сводки по нескольким оценкам официального документа: стабильность и сравнение моделей.

    # стабильность: какие К и С находятся в 3/3, 2/3, 1/3 прогонов
    python -m evaluation.v2.aggregate stability m/opus_1/score.json m/opus_2/score.json m/opus_3/score.json
    # сравнение моделей: метка=score.json
    python -m evaluation.v2.aggregate models opus=m/opus_1/score.json sonnet=m/sonnet/score.json haiku=m/haiku/score.json

Вход — score.json от `python -m evaluation.v2.score`. Вывод — Markdown (для RESULTS.md) в stdout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .score import DEFAULT_GOLD, load_gold


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def stability(paths: list[str]) -> str:
    gold = load_gold(DEFAULT_GOLD)
    runs = [_load(p) for p in paths]
    n = len(runs)
    found = [{a["gold"] for a in r["assignment"]} for r in runs]
    crit = [{a["gold"] for a in r["assignment"] if a["severity"] == "critical"} for r in runs]
    key = [it for it in gold["items"] if it["level"] in ("critical", "major")]
    buckets: dict[int, list[str]] = {k: [] for k in range(n, -1, -1)}
    for it in key:
        buckets[sum(it["id"] in f for f in found)].append(it["id"])
    L = [f"Прогонов: {n} ({', '.join(str(r['report'].get('model')) for r in runs)}).", "",
         "| Пункт | " + " | ".join(f"прогон {i + 1}" for i in range(n)) + " | Итого |",
         "| :--- | " + " | ".join(":---:" for _ in range(n)) + " | ---: |"]
    for it in key:
        cells = []
        for i in range(n):
            if it["id"] in crit[i] and it["level"] == "critical":
                cells.append("да, критичный")
            else:
                cells.append("да" if it["id"] in found[i] else "—")
        L.append(f"| {it['id']} {it['title'][:60]} | " + " | ".join(cells) + f" | {sum(it['id'] in f for f in found)}/{n} |")
    L += ["", "| Найдено в | Пункты |", "| :--- | :--- |"]
    for k, ids in buckets.items():
        L.append(f"| {k}/{n} | {', '.join(ids) or '—'} |")
    ks = [sum(1 for g in f if g.startswith("К")) for f in found]
    cs = [sum(1 for g in f if g.startswith("С")) for f in found]
    L += ["", f"К1–К5 по прогонам: {', '.join(map(str, ks))}; в каждом из {n}: "
              f"{', '.join(i for i in buckets[n] if i.startswith('К')) or '—'}.",
          f"С1–С20 по прогонам: {', '.join(map(str, cs))}; среднее {sum(cs) / max(1, n):.1f}."]
    return "\n".join(L) + "\n"


def models(pairs: list[str]) -> str:
    L = ["| Модель | Статус | К | К крит. | С | Ключевые 25 | Замечаний | Дубли | Вне эталона верно/ложно | "
         "Полезных | Серьёзность верна | Крит. ложных | Цитаты не найдены | Мин | Вызовов | $ |",
         "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for pair in pairs:
        label, path = pair.split("=", 1)
        r = _load(path)
        rc, p, rep = r["recall"], r["precision"], r["report"]
        calls = rep.get("calls") or {}
        dur = rep.get("duration_s")
        L.append(f"| {label} | {rep.get('status')} | {rc['critical']['n']}/5 | {len(rc['critical']['as_critical'])} | "
                 f"{rc['major']['n']}/20 | {rc['key_25']['n']}/25 | {r['counts']['findings']} | {p['duplicates']} | "
                 f"{p['outside_real']}/{p['outside_false']} | {_pct(p['precision_useful'])} | "
                 f"{_pct(r['severity']['accuracy_ok'])} | {len(r['severity']['critical_false'])} | "
                 f"{r['quotes']['missing']}/{r['quotes']['total']} | {'—' if dur is None else f'{dur / 60:.1f}'} | "
                 f"{calls.get('total', '—')} | {rep.get('cost_usd') if rep.get('cost_usd') is not None else '—'} |")
    return "\n".join(L) + "\n"


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f} %"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding="utf-8")
    if not args or args[0] not in ("stability", "models"):
        print(__doc__)
        return 2
    print(stability(args[1:]) if args[0] == "stability" else models(args[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
