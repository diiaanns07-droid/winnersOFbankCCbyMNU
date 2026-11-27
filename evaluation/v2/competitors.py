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
    # Волна 4 (№31): ещё три опубликованных отчёта по официальному документу; у каждого своя схема — свой адаптер.
    "ReqAudit": {"path": "kubectl-bekzhan/ReqAudit/a38c53fc8e58b13b353218aa63d84168820fa4ef/reports/"
                         "requirements-report.json", "model": "Claude Haiku 5.5, 3 прогона (по паспорту)",
                 "adapter": "reqaudit"},
    "reqcheck-agent": {"path": "asimzhanovvv/reqcheck-agent/87af5d50ada49dae9dbeca813d830316d397a05f/report/report.json",
                       "model": "Qwen 3.8 Omni Flash (по паспорту)", "adapter": "reqcheck"},
    "goodgame": {"path": "zhneo/goodgame/bc1f3366fd419176873696038c65abf13bbf8781/reports/report.json",
                 "model": "Gemini 3.5 Flash Lite (по паспорту), другой хеш Markdown", "adapter": "goodgame"},
}
# Соперники без опубликованного отчёта по официальному документу (смотрели закреплённый коммит) — в таблицу не идут.
NO_REPORT = {"yernururue/bcc-hack": "ee1a936a2a693e749476bd5c78e082ccb55c30bc"}
RU_SEV = {"критичная": "critical", "высокая": "major", "средняя": "major", "низкая": "minor"}
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


def _ev(quote, line) -> dict | None:
    q = str(quote or "").strip()
    if not q:
        return None
    ln = line if isinstance(line, int) else None
    return {"quote": q, "line_start": ln, "line_end": ln, "verified": "exact"}


def _finding(n: int, name: str, title: str, sev: str, ev: list, problem: str, fix: str, kind: str = "other") -> dict:
    return {"id": f"D-{n:02d}", "title": title, "severity": sev, "kind": kind, "evidence": [e for e in ev if e],
            "problem": problem, "scenario": "", "impact": "", "recommendation": fix, "rewrite": "", "question": "",
            "sources": [name]}


def _crit_kind(c: str) -> str:
    c = str(c or "").lower()
    for k, v in (("consist", "contradiction"), ("противореч", "contradiction"), ("ambig", "ambiguity"),
                 ("однознач", "ambiguity"), ("complete", "incomplete"), ("полн", "incomplete"),
                 ("verif", "unverifiable"), ("проверя", "unverifiable"), ("feasib", "infeasible"),
                 ("выполн", "infeasible")):
        if k in c:
            return v
    return "other"


def adapt_reqaudit(name: str, data: dict) -> list[dict]:
    fs = []
    for f in data.get("findings") or []:
        if f.get("dropped_reason"):
            continue
        loc = f.get("location") or {}
        ev = [_ev(f.get("quote"), loc.get("line_start")),
              _ev(f.get("related_quote"), (f.get("related_location") or {}).get("line_start"))]
        ev += [_ev(q, (l or {}).get("line_start")) for q, l in zip(f.get("extra_quotes") or [],
                                                                   f.get("extra_locations") or [])]
        title = str(f.get("explanation") or "").split(". ")[0][:120]
        fs.append(_finding(len(fs) + 1, name, title, _sev(f.get("severity")), ev, str(f.get("explanation") or ""),
                           str(f.get("suggestion") or ""), _crit_kind(f.get("criterion"))))
    return fs


def adapt_reqcheck(name: str, data: dict) -> list[dict]:
    fs = []
    for f in data.get("findings") or []:
        qs, ls = f.get("quotes") or [], f.get("lines") or []
        ev = [_ev(q, ls[i] if i < len(ls) and len(ls) == len(qs) else None) for i, q in enumerate(qs)]
        fs.append(_finding(len(fs) + 1, name, str(f.get("title") or ""), RU_SEV.get(str(f.get("severity")), "minor"),
                           ev, str(f.get("problem") or ""), str(f.get("fix") or ""), _crit_kind(f.get("criterion"))))
    return fs


def adapt_goodgame(name: str, data: dict) -> list[dict]:
    fs = []
    raw = [f for rc in data.get("requirement_checks") or [] for f in rc.get("findings") or []]
    raw += list((data.get("set_check") or {}).get("findings") or [])
    for f in raw:
        ev = [_ev(f.get("quote"), None)] + [_ev(q, None) for q in f.get("related_quotes") or []]
        title = str(f.get("explanation") or "").split(". ")[0][:120]
        fs.append(_finding(len(fs) + 1, name, title, _sev(f.get("severity")), ev, str(f.get("explanation") or ""),
                           str(f.get("fix") or ""), _crit_kind(f.get("criterion"))))
    return fs


def _verdict_other(name: str, data: dict) -> dict:
    if name == "ReqAudit":
        r = str(data.get("readiness") or "").lower()
        v = "no" if "not" in r or "block" in r else ("yes" if r in ("ready", "ready_for_dev") else "conditional")
        return {"development": v, "testing": v}
    if name == "goodgame":
        ok = (data.get("verdict") or {}).get("ready")
        v = "yes" if ok is True else "no"
        return {"development": v, "testing": v}
    lv = str((data.get("verdict") or {}).get("level") or "").lower()
    return {"development": lv or "conditional", "testing": lv or "conditional"}


ADAPTERS = {"reqaudit": adapt_reqaudit, "reqcheck": adapt_reqcheck, "goodgame": adapt_goodgame}


def adapt(name: str, data: dict, gold: dict) -> dict:
    """Отчёт конкурента → отчёт v2 нашего счётчика (только действующие замечания)."""
    ad = SOURCES[name].get("adapter")
    if ad:
        return {"schema": "bcc-review/2", "run": {"status": "complete"}, "findings": ADAPTERS[ad](name, data),
                "document": {"sha256": gold.get("sha256"), "format": "md"}, "verdict": _verdict_other(name, data)}
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
        if re.search(r"\b(pdf|docx)\b", r.get("label") or "", re.I):  # соперники — по Markdown; PDF/DOCX — отдельно
            continue
        if r.get("dir") and not (ROOT / r["dir"] / "score.json").exists():  # строка без сохранённого замера
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
          "ERA216 и goodgame — Markdown с другим хешем). ReqAudit — слитые замечания без отсеянных (`dropped_reason`), "
          "reqcheck-agent — все из `findings` (высокая и средняя → major), goodgame — замечания по требованиям и по "
          "набору. Без опубликованного отчёта по официальному документу: "
          + ", ".join(f"{k} (`{v[:7]}`)" for k, v in NO_REPORT.items()) + ". «Вне эталона» — не обязательно ложные: эталон не исчерпывает все дефекты. "
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
