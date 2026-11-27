"""Конкуренты на нашем счётчике: опубликованные отчёты по официальному документу → `score.score_report`.

    python -m evaluation.v2.competitors                 # скачать (out/competitors/), посчитать, таблица в stdout
    python -m evaluation.v2.competitors --write         # + раздел «Мы и конкуренты» в evaluation/v2/RESULTS.md
    python -m evaluation.v2.competitors --dir ПАПКА     # отчёты уже скачаны: ПАПКА/<имя>.json

Берутся те же опубликованные файлы, что в разборе F4 (`docs/plan-v2/f4/competitors.md`, ветка `eval/blind-v2`):
коммиты закреплены ниже. В счёт идут только действующие замечания (ERA216 — `open`, SoloHive — `active`,
azekowka — `confirmed`); слитые и отклонённые — нет. Отчёты конкурентов в репозиторий не кладём — только числа.

Оговорки (печатаются вместе с таблицей): эталон — наш (`docs/task-analysis.md`, раздел 5), а не организаторов;
сопоставление — по цитатам и ключевым словам (арбитр — только кэш), тип замечания у ERA216 и SoloHive не указан
(у нас он даёт небольшую прибавку к сходству); у каждого конкурента — один опубликованный прогон, их модели и
входы разные (SoloHive — PDF через OpenRouter, ERA216 — другой хеш Markdown).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from . import score as sc
from .common import ROOT

V2 = ROOT / "evaluation" / "v2"
RESULTS = V2 / "RESULTS.md"
START, END = "<!-- competitors:start -->", "<!-- competitors:end -->"
RAW = "https://raw.githubusercontent.com/"

SOURCES = {
    "ERA216": {"path": "ERA216/Hac/3bfe28f962e812e5beecf4fa57a01eb546e472ab/reports/report.json",
               "model": "Gemini 3.6 Flash (по паспорту отчёта)", "active": ("open",)},
    "SoloHive": {"path": "khusrav11/solohive/479ff57c1962a31c5c64294c9ffddcef05eb8b2e/reports/report.json",
                 "model": "Gemini 3.8 Flash через OpenRouter, вход PDF", "active": ("active",)},
    "azekowka": {"path": "azekowka/ai-requirements-validator-task/c704a9e2dffe59390c7c104a517aedfa10ae4ce8/"
                         "reports/requirements-report.json", "model": "Claude Opus 5.5", "active": ("confirmed",)},
}
KIND_MAP = {"ambiguous": "ambiguity", "contradiction": "contradiction", "incomplete": "incomplete",
            "infeasible": "infeasible", "unverifiable": "unverifiable"}


def fetch(dest: Path) -> dict[str, Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, s in SOURCES.items():
        p = dest / f"{name}.json"
        if not p.exists():
            with urllib.request.urlopen(RAW + s["path"], timeout=60) as r:  # noqa: S310 — фиксированные адреса
                p.write_bytes(r.read())
        out[name] = p
    return out


def _sev(x) -> str:
    s = str(x or "").lower()
    return s if s in ("critical", "major", "minor") else "minor"


def _verdict(v: dict) -> dict:
    v = v or {}
    def m(x):
        x = str(x).lower()
        return "no" if x in ("false", "no", "not_ready") else ("yes" if x in ("true", "yes", "ready") else "conditional")
    if "ready_for_development" in v:
        return {"development": m(v["ready_for_development"]), "testing": m(v.get("ready_for_testing"))}
    if "dev_status" in v:
        return {"development": m(v["dev_status"]), "testing": m(v.get("test_status"))}
    return {"development": m(v.get("development")), "testing": m(v.get("testing"))}


def adapt(name: str, data: dict, gold: dict) -> dict:
    """Отчёт конкурента → отчёт v2 нашего счётчика (только действующие замечания)."""
    active = SOURCES[name]["active"]
    fs = []
    for f in data.get("findings") or []:
        if str(f.get("status") or active[0]).lower() not in active:
            continue
        ev = []
        for e in f.get("evidence") or []:
            if not isinstance(e, dict) or not str(e.get("quote") or "").strip():
                continue
            ls = e.get("line_start", e.get("line"))
            ev.append({"quote": e["quote"], "line_start": ls, "line_end": e.get("line_end", ls), "verified": "exact"})
        fs.append({"id": f"D-{len(fs) + 1:02d}", "title": str(f.get("title") or ""), "severity": _sev(f.get("severity")),
                   "kind": KIND_MAP.get(str(f.get("defect_type") or ""), "other"), "evidence": ev,
                   "problem": str(f.get("problem") or f.get("explanation") or f.get("description") or ""),
                   "scenario": str(f.get("scenario") or ""), "impact": "",
                   "recommendation": str(f.get("recommendation") or ""), "rewrite": str(f.get("rewrite") or ""),
                   "question": "", "sources": [name]})
    return {"schema": "bcc-review/2", "run": {"status": "complete"}, "findings": fs,
            "document": {"sha256": gold.get("sha256"), "format": "md"}, "verdict": _verdict(data.get("verdict"))}


def score_one(name: str, path: Path, gold: dict) -> dict:
    rep = adapt(name, json.loads(path.read_text(encoding="utf-8")), gold)
    res = sc.score_report(rep, gold, arbiter="off", cache_path=sc.DEFAULT_CACHE)
    rc, p = res["recall"], res["precision"]
    return {"name": name, "model": SOURCES[name]["model"], "findings": res["counts"]["findings"],
            "by_severity": res["counts"]["by_severity"], "K": rc["critical"]["n"],
            "K_crit": len(rc["critical"]["as_critical"]), "C": rc["major"]["n"], "key25": rc["key_25"]["n"],
            "critical_false": len(res["severity"]["critical_false"]), "duplicates": p["duplicates"],
            "outside": p["outside_real"] + p["outside_false"] + p["outside_unknown"],
            "quotes": f"{res['quotes']['total'] - res['quotes']['missing']}/{res['quotes']['total']}",
            "verdict": rep["verdict"]}


def ours() -> list[dict]:
    """Последний замер каждой нашей модели на официальном документе (history.jsonl)."""
    rows = [json.loads(x) for x in (V2 / "history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("version") != "v2":
            continue
        k = next((m for m in ("opus", "sonnet", "haiku", "gemini") if m in f"{r.get('model')}".lower()), None)
        if k:
            latest[k] = r
    out = []
    for k in ("sonnet", "haiku", "opus", "gemini"):
        r = latest.get(k)
        if r:
            out.append({"name": f"BCC Review — {k}", "model": r.get("label", ""), "findings": r["findings"],
                        "by_severity": r.get("by_severity") or {}, "K": r["K"], "K_crit": r["K_as_critical"],
                        "C": r["C"], "key25": r["key25"], "critical_false": r["critical_false"],
                        "duplicates": r["duplicates"],
                        "outside": (r.get("outside_real") or 0) + (r.get("outside_false") or 0)
                        + (r.get("outside_unknown") or 0),
                        "quotes": f"{(r.get('quotes_total') or 0) - (r.get('quotes_missing') or 0)}/{r.get('quotes_total')}",
                        "verdict": {}})
    return out


def render(rows: list[dict]) -> str:
    L = ["| Отчёт | Модель / прогон | Замечаний (cr/maj/min) | К1–К5 | К критичными | С1–С20 | Ключевые 25 | "
         "Крит. ложных | Дубли | Вне эталона | Цитаты найдены |",
         "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    for r in rows:
        b = r.get("by_severity") or {}
        L.append(f"| {r['name']} | {r['model']} | {r['findings']} ({b.get('critical', 0)}/{b.get('major', 0)}/"
                 f"{b.get('minor', 0)}) | {r['K']}/5 | {r['K_crit']} | {r['C']}/20 | {r['key25']}/25 | "
                 f"{r['critical_false']} | {r['duplicates']} | {r['outside']} | {r['quotes']} |")
    L += ["", "Оговорки: эталон — наш (`docs/task-analysis.md`, раздел 5), а не организаторов; сопоставление — по цитатам "
          "и ключевым словам, арбитр — только кэш (спорное без решения не засчитано); у конкурентов — один опубликованный "
          "прогон на закреплённом коммите, только действующие замечания; модели и входы у всех разные (SoloHive — PDF, "
          "ERA216 — Markdown с другим хешем). «Вне эталона» — не обязательно ложные: эталон не исчерпывает все дефекты. "
          "Пересчитать: `python -m evaluation.v2.competitors --write`."]
    return "\n".join(L) + "\n"


def write_results(text: str) -> None:
    res = RESULTS.read_text(encoding="utf-8")
    block = f"{START}\n{text}{END}"
    if START in res and END in res:
        res = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, res, flags=re.S)
    else:
        anchor = "\n## Ворота второй волны"
        sec = "\n## Мы и конкуренты на одном счётчике (официальный документ)\n\n" + block + "\n"
        res = res.replace(anchor, sec + anchor, 1) if anchor in res else res.rstrip() + "\n" + sec
    RESULTS.write_text(res, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.competitors", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="папка с уже скачанными <имя>.json")
    ap.add_argument("--write", action="store_true", help="записать таблицу в evaluation/v2/RESULTS.md")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    paths = ({n: Path(a.dir) / f"{n}.json" for n in SOURCES} if a.dir else fetch(ROOT / "out" / "competitors"))
    rows = ours() + [score_one(n, p, gold) for n, p in paths.items() if p.exists()]
    text = render(rows)
    print(text)
    if a.write:
        write_results(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
