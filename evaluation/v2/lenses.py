"""Сводка по сохранённым ответам линз в ветках `origin/v2/*` (до судьи): кто что находит из эталона.

    git fetch origin && python -m evaluation.v2.lenses [--pattern official] [--out lenses.md]

Берёт из каждой ветки `tests/v2/fixtures/**/<pattern>*.json` с полем `candidates`, оценивает по эталону официального
документа (без арбитра — только детерминированные совпадения) и печатает таблицу и объединённое покрытие
(лучший ответ каждой ветки).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from . import score as sc
from .common import ROOT

LENS_BY_BRANCH = {"05": "analyst", "06": "qa", "07": "architect", "08": "risk", "09": "consistency", "12": "rules",
                  "10": "judge"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(ROOT)).stdout


def collect(pattern: str) -> list[dict]:
    out = []
    branches = [b.strip() for b in _git("branch", "-r").splitlines() if b.strip().startswith("origin/v2/")]
    for b in branches:
        for path in _git("ls-tree", "-r", "--name-only", b, "--", "tests/v2/fixtures").splitlines():
            name = Path(path).name
            if not path.endswith(".json") or pattern not in name.lower():
                continue
            try:
                data = json.loads(_git("show", f"{b}:{path}"))
            except json.JSONDecodeError:
                continue
            if not sc._find_candidate_lists(data):
                continue
            nn = re.search(r"v2/(\d\d)", b)
            out.append({"branch": b.replace("origin/", ""), "path": path, "lens": LENS_BY_BRANCH.get(nn.group(1) if nn else "", "?"),
                        "data": data, "commit": _git("log", "-1", "--format=%h", b, "--", path).strip()})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.lenses", description=__doc__)
    ap.add_argument("--pattern", default="official")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    items = collect(a.pattern)
    L = ["| Ветка | Ответ | Коммит | Кандидатов | К | С | Свои пункты | Не найдено из своих | Вне эталона |",
         "| :--- | :--- | :--- | ---: | :--- | ---: | ---: | :--- | ---: |"]
    best: dict[str, tuple[int, dict]] = {}
    for it in items:
        rep = sc.as_report(it["data"], gold)
        res = sc.score_report(rep, gold, arbiter="off")
        found = {x["gold"] for x in res["assignment"]}
        mine = [g for g in gold["items"] if it["lens"] in g.get("owners", [])]
        miss = [g["id"] for g in mine if g["id"] not in found]
        k = res["recall"]["key_25"]["n"]
        L.append(f"| {it['branch']} | {Path(it['path']).name} | {it['commit']} | {res['counts']['findings']} | "
                 f"{', '.join(res['recall']['critical']['found']) or '—'} | {res['recall']['major']['n']}/20 | "
                 f"{len(mine) - len(miss)}/{len(mine)} | {', '.join(miss) or '—'} | {res['counts']['outside_gold']['total']} |")
        for c in rep["findings"]:
            c.setdefault("source", f"lens:{it['lens']}")
        if k > best.get(it["branch"], (-1, {}))[0]:
            best[it["branch"]] = (k, rep)
    union = [f for _, rep in best.values() for f in rep["findings"]]
    for i, f in enumerate(union, 1):
        f["id"] = f"U-{i:03d}"
    ures = sc.score_report(sc.as_report({"candidates": union}, gold), gold, arbiter="off")
    missed = [m["gold"] for m in ures["misses"] if m["level"] != "minor"]
    L += ["", f"Объединение лучших ответов веток ({', '.join(best)}): К {ures['recall']['critical']['n']}/5 "
              f"({', '.join(ures['recall']['critical']['found']) or '—'}), С {ures['recall']['major']['n']}/20, "
              f"ключевые {ures['recall']['key_25']['n']}/25. Никто не нашёл: {', '.join(missed) or '—'}."]
    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
