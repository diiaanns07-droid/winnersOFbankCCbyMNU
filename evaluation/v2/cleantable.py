"""P1 третьей волны — точность на чистых ТЗ: по каждому чистому документу critical, major, minor и вердикт.

    python -m evaluation.v2.cleantable             # таблицы в stdout
    python -m evaluation.v2.cleantable --write     # + первая таблица evaluation/v2/RESULTS.md (<!-- clean:… -->)

Источники (берётся последний прогон каждого набора и модели):
* корпус `evaluation/dev` — `evaluation/v2/corpus_results/*/summary.json`, кейсы с `expected: clean` (базы и перефразы);
* чистые ТЗ №20 и чистые версии №18 — `evaluation/v2/newtz_results/*/summary.json` (`newtz run|score … --save`),
  строки с `variant: clean`; набор определяется по пути документа (`evaluation/v2/clean/` — №20, `open2/` — №18);
* прогоны №18 — `evaluation/v2/open2/results/*/summary.json` (формат `open2/run.py`), строки `variant: clean`.

Цель WAVE3 (P1): на чистом документе 0 critical, вердикт не «нельзя», major ≤ 3 (только настоящие).
Разметка «настоящий / по делу, но minor / ложный» — у №19 (`evaluation/v2/measurements/19_*/clean_review.md`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .common import ROOT

V2 = ROOT / "evaluation" / "v2"
RESULTS = V2 / "RESULTS.md"
START, END = "<!-- clean:start -->", "<!-- clean:end -->"
MAJOR_MAX = 3


def _kind(model: str | None, label: str | None = "") -> str:
    s = f"{model or ''} {label or ''}".lower()
    if "офлайн" in s or "offline" in s:
        return "офлайн (правила)"
    for k in ("gemini", "opus", "haiku", "sonnet"):
        if k in s:
            return k
    return model or "?"


def _row(set_name: str, model: str, label: str, at: str, case: str, sev: dict, verdict: dict | None) -> dict:
    return {"set": set_name, "model": _kind(model, label), "label": label, "at": at or "", "case": case,
            "critical": int(sev.get("critical") or 0), "major": int(sev.get("major") or 0),
            "minor": int(sev.get("minor") or 0), "verdict": verdict or {}}


def _corpus_rows() -> list[dict]:
    out = []
    for p in sorted((V2 / "corpus_results").glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for c in d.get("per_case") or []:
            if c.get("expected") != "clean" or c.get("status") in (None, "failed") or c["case_id"] == "edge.empty":
                continue
            out.append(_row("корпус: базы и перефразы", d.get("model"), d.get("label", p.parent.name), d.get("at", ""),
                            c["case_id"], c.get("by_severity") or {}, c.get("verdict")))
    return out


def _set_of(doc: str | None) -> str:
    doc = str(doc or "")
    if "/v2/clean/" in doc or doc.startswith("evaluation/v2/clean/"):
        return "чистые ТЗ №20"
    if "open2" in doc:
        return "№18: чистые версии (1-я редакция)"
    return "прочие чистые"


def _newtz_rows() -> list[dict]:
    out = []
    for p in sorted((V2 / "newtz_results").glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for r in d.get("rows") or []:
            if r.get("variant") != "clean" or r.get("status") in (None, "failed"):
                continue
            sev = r.get("fa_by_severity") or r.get("by_severity") or {}
            out.append(_row(_set_of(r.get("doc")), d.get("model"), d.get("label", p.parent.name), d.get("at", ""),
                            r["case"], sev, r.get("verdict")))
    return out


def _open2_rows() -> list[dict]:
    out = []
    for p in sorted((V2 / "open2" / "results").glob("*/summary.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("rows") or []
        edition = "2-я редакция" if "clean2" in p.parent.name else "1-я редакция"
        for r in rows:
            if r.get("variant") != "clean" or r.get("status") in (None, "failed"):
                continue
            out.append(_row(f"№18: чистые версии ({edition})", r.get("model"), f"№18 {p.parent.name}",
                            f"~{p.parent.name.split('_')[-1]}", r["case"], r.get("by_severity") or {}, r.get("verdict")))
    return out


def latest(rows: list[dict]) -> dict[tuple, list[dict]]:
    """(набор, модель) → строки последнего прогона."""
    best: dict[tuple, str] = {}
    for r in rows:
        k = (r["set"], r["model"])
        key = (r["at"], r["label"])
        if k not in best or key > best[k]:
            best[k] = key
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        k = (r["set"], r["model"])
        if (r["at"], r["label"]) == best[k]:
            out.setdefault(k, []).append(r)
    return out


def _verdict(v: dict) -> str:
    ru = {"no": "нельзя", "conditional": "с условиями", "yes": "можно", "undetermined": "не определено", None: "—"}
    return f"{ru.get(v.get('development'), v.get('development'))} / {ru.get(v.get('testing'), v.get('testing'))}"


def render(groups: dict[tuple, list[dict]]) -> str:
    order = ["чистые ТЗ №20", "№18: чистые версии (2-я редакция)", "№18: чистые версии (1-я редакция)",
             "корпус: базы и перефразы", "прочие чистые"]
    keys = sorted(groups, key=lambda k: (order.index(k[0]) if k[0] in order else 9, k[1]))
    L = ["### Чистые ТЗ — сводка (P1: 0 critical, не «нельзя», major ≤ 3 на документ)", "",
         "| Набор | Модель | Прогон | Документов | critical (документов) | major всего / макс. | «нельзя» | P1 |",
         "| :--- | :--- | :--- | ---: | :--- | :--- | ---: | :---: |"]
    for k in keys:
        rs = groups[k]
        crit = sum(r["critical"] for r in rs)
        crit_docs = sum(1 for r in rs if r["critical"])
        maj = sum(r["major"] for r in rs)
        mx = max((r["major"] for r in rs), default=0)
        no = sum(1 for r in rs if "no" in (r["verdict"] or {}).values())
        ok = crit == 0 and no == 0 and mx <= MAJOR_MAX
        L.append(f"| {k[0]} | {k[1]} | {rs[0]['label']} ({rs[0]['at'][11:16] or rs[0]['at']}) | {len(rs)} | "
                 f"{crit} ({crit_docs}) | {maj} / {mx} | {no} | {'✅' if ok else '❌'} |")
    L += ["", "### Чистые ТЗ — по документам (последний прогон набора и модели)", "",
          "| Документ | Набор | Модель | critical | major | minor | Вердикт: разработка / тестирование |",
          "| :--- | :--- | :--- | ---: | ---: | ---: | :--- |"]
    for k in keys:
        for r in sorted(groups[k], key=lambda r: r["case"]):
            flag = " ❗" if r["critical"] or r["major"] > MAJOR_MAX or "no" in (r["verdict"] or {}).values() else ""
            L.append(f"| {r['case']}{flag} | {k[0]} | {k[1]} | {r['critical']} | {r['major']} | {r['minor']} | "
                     f"{_verdict(r['verdict'])} |")
    L += ["", "❗ — документ нарушает P1. Разметка каждого critical/major «настоящий / по делу, но minor / ложный» — "
          "№19 (`evaluation/v2/measurements/19_*/clean_review.md`). Пересчитать: `python -m evaluation.v2.cleantable --write`."]
    return "\n".join(L) + "\n"


def write_results(text: str) -> None:
    res = RESULTS.read_text(encoding="utf-8")
    block = f"{START}\n{text}{END}"
    if START in res and END in res:
        res = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, res, flags=re.S)
    else:  # первой таблицей — сразу после заголовка документа
        head, sep, rest = res.partition("\n## ")
        res = head.rstrip() + "\n\n## Чистые ТЗ — точность (P1 третьей волны)\n\n" + block + "\n" + sep + rest
    RESULTS.write_text(res, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.cleantable", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="записать первой таблицей в evaluation/v2/RESULTS.md")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    groups = latest(_corpus_rows() + _newtz_rows() + _open2_rows())
    text = render(groups)
    print(text)
    if a.write:
        write_results(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
