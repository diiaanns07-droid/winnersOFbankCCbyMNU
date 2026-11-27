"""Счётчик до и после правки (№31, этап 2): те же сохранённые отчёты официального документа, три счётчика.

    python -m evaluation.v2.counterdiff                    # таблица в stdout
    python -m evaluation.v2.counterdiff --write            # + раздел в evaluation/v2/RESULTS.md

* «до» — счётчик и эталон релиза `bcc/v2` (`3e7133c2`: `score.py` и `official/gold.yaml` из git) — им считались
  замеры 13:00 и W4-07;
* «С14» — счётчик №15 после релиза: второй шанс строгой паре с заголовком о теме пункта (`0ff16bb4`), а также
  обязательные ключевые слова К4 «чтение» и С12 «содержит» (`568a6a7b`) = текущий с `displaced=False`;
* «С14+С15» — текущий счётчик: ещё и «вытесненная» пара того же вида (просьба №26).

Без арбитра (`arbiter="off"`): спорные пары без решения в кэше не засчитываются ни в одном столбце. Отчёты не
меняются, `score.json` замеров не перезаписывается.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import score as sc
from .common import ROOT

MEAS = ROOT / "evaluation" / "v2" / "measurements"
RESULTS = ROOT / "evaluation" / "v2" / "RESULTS.md"
BEFORE_REV = "3e7133c2"  # счётчик и эталон в релизе bcc/v2
START, END = "<!-- counterdiff:start -->", "<!-- counterdiff:end -->"


def _old_counter(tmp: Path):
    """Модуль счётчика и эталон из git (`BEFORE_REV`) — без подмены текущего пакета."""
    src = subprocess.run(["git", "show", f"{BEFORE_REV}:evaluation/v2/score.py"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    gold = subprocess.run(["git", "show", f"{BEFORE_REV}:evaluation/v2/official/gold.yaml"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout
    (tmp / "gold.yaml").write_text(gold, encoding="utf-8")
    p = tmp / "score_before.py"
    p.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("evaluation.v2._score_before", p,
                                                  submodule_search_locations=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "evaluation.v2"
    spec.loader.exec_module(mod)
    return mod, mod.load_gold(tmp / "gold.yaml")


def _brief(r: dict) -> dict:
    rec = r["recall"]
    return {"K": len(rec["critical"]["found"]), "Kc": len(rec["critical"].get("as_critical") or []),
            "C": rec["major"]["n"], "key25": rec["key_25"]["n"], "dups": r["counts"]["duplicates"],
            "C_found": sorted(rec["major"]["found"])}


def compute(dirs: list[Path] | None = None) -> list[dict]:
    dirs = dirs or sorted(d for d in MEAS.iterdir() if (d / "report.json").exists())
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    rows = []
    with tempfile.TemporaryDirectory() as t:
        old, old_gold = _old_counter(Path(t))
        for d in dirs:
            data = json.loads((d / "report.json").read_text(encoding="utf-8"))
            md = d / "report.md"
            kw = {"report_md": str(md) if md.exists() else None, "arbiter": "off"}
            b = _brief(old.score_report(old.as_report(data, old_gold), old_gold, **kw))
            rep = sc.as_report(data, gold)
            c14 = _brief(sc.score_report(rep, gold, displaced=False, **kw))
            now = _brief(sc.score_report(rep, gold, displaced=True, **kw))
            rows.append({"name": d.name, "before": b, "c14": c14, "now": now})
    return rows


def render(rows: list[dict]) -> str:
    def f(x: dict) -> str:
        return f"{x['K']}/5 · {x['Kc']} · {x['C']}/20 · {x['key25']}/25 · {x['dups']}"

    changed = [r for r in rows if not (r["before"] == r["c14"] == r["now"])]
    L = [f"Пересчёт {len(rows)} сохранённых отчётов официального тремя счётчиками (`python -m evaluation.v2.counterdiff "
         f"--write`). Столбцы: К найдено · К критичными · С · ключевые 25 · дубли. Изменились {len(changed)}; "
         f"в остальных {len(rows) - len(changed)} — всё как было.", "",
         "| Замер | до (релиз `3e7133c`) | С14 (`0ff16bb4`, `568a6a7b`) | С14+С15 (сейчас) | С засчитаны / сняты |",
         "| :--- | :--- | :--- | :--- | :--- |"]
    for r in changed:
        plus = sorted(set(r["now"]["C_found"]) - set(r["before"]["C_found"]))
        minus = sorted(set(r["before"]["C_found"]) - set(r["now"]["C_found"]))
        what = ", ".join([f"+{x}" for x in plus] + [f"−{x}" for x in minus]) or "только дубли"
        L.append(f"| {r['name']} | {f(r['before'])} | {f(r['c14'])} | {f(r['now'])} | {what} |")
    kb = sum(r["before"]["K"] for r in rows), sum(r["now"]["K"] for r in rows)
    cb = sum(r["before"]["C"] for r in rows), sum(r["now"]["C"] for r in rows)
    L += ["", f"Итого по {len(rows)} отчётам: К найдено {kb[0]} → {kb[1]}, С {cb[0]} → {cb[1]}. Счёт строгий и "
          "детерминированный: С15 засчитывается без слов пункта в заголовке, только если лучший пункт замечания уже "
          "занят более сильным замечанием и вид дефекта совпадает с видами пункта."]
    return "\n".join(L) + "\n"


def write_results(text: str) -> None:
    res = RESULTS.read_text(encoding="utf-8")
    block = f"{START}\n{text}{END}"
    if START in res and END in res:
        res = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, res, flags=re.S)
    else:
        anchor = "\n## Чистые ТЗ — точность"
        sec = "\n## Счётчик до и после правки С14 и С15 (те же отчёты)\n\n" + block + "\n"
        res = res.replace(anchor, sec + anchor, 1) if anchor in res else res.rstrip() + "\n" + sec
    RESULTS.write_text(res, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.counterdiff", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("dirs", nargs="*")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows = compute([Path(d) for d in a.dirs] or None)
    text = render(rows)
    print(text)
    if a.write:
        write_results(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
