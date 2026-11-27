"""P1 третьей волны — точность на чистых ТЗ: по каждому чистому документу critical, major, minor и вердикт.

    python -m evaluation.v2.cleantable             # таблицы в stdout
    python -m evaluation.v2.cleantable --write     # + первая таблица evaluation/v2/RESULTS.md (<!-- clean:… -->)

Источники (берётся последний прогон каждого набора и модели):
* корпус `evaluation/dev` — `evaluation/v2/corpus_results/*/summary.json`, кейсы с `expected: clean` (базы и перефразы);
* чистые ТЗ №20 и чистые версии №18 — `evaluation/v2/newtz_results/*/summary.json` (`newtz run|score … --save`),
  строки с `variant: clean`; набор определяется по пути документа (`evaluation/v2/clean/` — №20, `open2/` — №18);
* прогоны №18 — `evaluation/v2/open2/results/*/summary.json` (формат `open2/run.py`), строки `variant: clean`;
* прогоны других ролей, у которых в git только таблица в статусе (№19, №10 — прогоны на своих машинах), —
  `evaluation/v2/clean_external.json`: числа переписаны из статуса со ссылкой на коммит, метка «(статус №NN)».

Цель WAVE3 (P1): на чистом документе 0 critical, вердикт не «нельзя», major ≤ 3 (только настоящие).
Разметка «настоящий / по делу, но minor / ложный» — у №19 (`evaluation/v2/measurements/19_*/clean_review.md`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .common import ROOT, cluster_by_title, put_results_block

V2 = ROOT / "evaluation" / "v2"
RESULTS = V2 / "RESULTS.md"
EXTERNAL = V2 / "clean_external.json"
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


def _row(set_name: str, model: str, label: str, at: str, case: str, sev: dict, verdict: dict | None,
         calls: int | None = None, findings: list[dict] | None = None) -> dict:
    """`calls` — вызовов модели в прогоне документа: 0 у модели — повтор ответов из кэша (не новая выборка).
    `findings` — ложные замечания документа (critical и major: серьёзность, заголовок, источники, владельцы); None —
    в сводке прогона их нет."""
    keep = None if findings is None else [
        {k: f.get(k) for k in ("severity", "title", "sources", "owners")} for f in findings
        if isinstance(f, dict) and f.get("severity") in ("critical", "major")]
    return {"set": set_name, "model": _kind(model, label), "label": label, "at": at or "", "case": case,
            "critical": int(sev.get("critical") or 0), "major": int(sev.get("major") or 0),
            "minor": int(sev.get("minor") or 0), "verdict": verdict or {}, "calls": calls, "findings": keep}


def _corpus_rows() -> list[dict]:
    out = []
    for p in sorted((V2 / "corpus_results").glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for c in d.get("per_case") or []:
            if c.get("expected") != "clean" or c.get("status") in (None, "failed") or c["case_id"] == "edge.empty":
                continue
            out.append(_row("корпус: базы и перефразы", d.get("model"), d.get("label", p.parent.name), d.get("at", ""),
                            c["case_id"], c.get("by_severity") or {}, c.get("verdict"), c.get("calls")))
    return out


OPEN2_EDITION2 = "4d108e42"  # №18: вторая редакция чистых версий open2 (27.11 08:32) — в дереве с тех пор она


def _has_edition2(commits: list[str]) -> bool | None:
    """Есть ли в коде прогона вторая редакция чистых open2: None — коммиты git не знает."""
    import subprocess

    known = None
    for c in commits:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", OPEN2_EDITION2, c], cwd=str(ROOT),
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True
        if r.returncode == 1:
            known = False
    return known


def _set_of(doc: str | None, commits: list[str] | None = None, at: str = "") -> str:
    doc = str(doc or "").replace("\\", "/")
    if "/v2/clean/" in doc or doc.startswith("evaluation/v2/clean/"):
        return "чистые ТЗ №20"
    if "open2" in doc:
        ed2 = _has_edition2(commits or [])
        if ed2 is None:  # коммит неизвестен — по времени прогона
            ed2 = at >= "2026-11-27 08:40"
        return f"№18: чистые версии ({'2' if ed2 else '1'}-я редакция)"
    return "прочие чистые"


def _newtz_rows() -> list[dict]:
    out = []
    for p in sorted((V2 / "newtz_results").glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for r in d.get("rows") or []:
            if r.get("variant") != "clean" or r.get("status") in (None, "failed"):
                continue
            sev = r.get("fa_by_severity") or r.get("by_severity") or {}
            commits = [c for c in [r.get("commit"), *(d.get("commit") or [])] if c]
            out.append(_row(_set_of(r.get("doc"), commits, d.get("at", "")), d.get("model"),
                            d.get("label", p.parent.name), d.get("at", ""), r["case"], sev, r.get("verdict"),
                            r.get("calls"), r.get("false_alarms") if isinstance(r.get("false_alarms"), list) else None))
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
                            f"~{p.parent.name.split('_')[-1]}", r["case"], r.get("by_severity") or {}, r.get("verdict"),
                            r.get("calls")))
    return out


def _external_rows(path: Path | None = None) -> list[dict]:
    """Прогоны из статусов других ролей: [{set, model, label, at, source, rows: [{case, critical, major, minor,
    verdict: {development, testing}}]}]. Нужны, пока сами `summary.json` не закоммичены."""
    path = path or EXTERNAL
    if not path.exists():
        return []
    out = []
    for run in json.loads(path.read_text(encoding="utf-8")):
        for r in run.get("rows") or []:
            out.append(_row(run["set"], run.get("model"), run["label"], run.get("at", ""), r["case"],
                            {k: r.get(k, 0) for k in ("critical", "major", "minor")}, r.get("verdict")))
    return out


def latest(rows: list[dict]) -> dict[tuple, list[dict]]:
    """(набор, модель) → строки последнего прогона."""
    def when(r: dict) -> tuple:
        # «~0835» — прогоны open2/run.py без даты (вторая волна): старше любого прогона с полной датой
        at = r["at"] or ""
        return (0 if at.startswith("~") or not at else 1, at, r["label"])

    best: dict[tuple, tuple] = {}
    for r in rows:
        k = (r["set"], r["model"])
        if k not in best or when(r) > best[k]:
            best[k] = when(r)
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        k = (r["set"], r["model"])
        if when(r) == best[k]:
            out.setdefault(k, []).append(r)
    return out


def _verdict(v: dict) -> str:
    ru = {"no": "нельзя", "conditional": "с условиями", "yes": "можно", "undetermined": "не определено", None: "—"}
    return f"{ru.get(v.get('development'), v.get('development'))} / {ru.get(v.get('testing'), v.get('testing'))}"


def render_verdicts(groups: dict[tuple, list[dict]], heading: bool = True) -> str:
    """«Вердикт на исправленных ТЗ» (таблица №01): по каждому набору — сколько чистых документов получили
    «можно», «с условиями», «нельзя» (по разработке) в последнем прогоне модели; цель — «нельзя» 0."""
    order = ["чистые ТЗ №20", "№18: чистые версии (2-я редакция)", "№18: чистые версии (1-я редакция)",
             "корпус: базы и перефразы", "прочие чистые"]
    keys = sorted((k for k in groups if not k[1].startswith("офлайн")),
                  key=lambda k: (order.index(k[0]) if k[0] in order else 9, k[1]))
    L = (["### Вердикт на исправленных ТЗ (цель: «нельзя» 0, critical 0)", ""] if heading else
         ["Цель: на исправленном (чистом) ТЗ «нельзя» 0 и critical 0. Последний прогон каждого набора и модели;"
          " пересчитать — `python -m evaluation.v2.cleantable --write`.", ""]) + [
         "| Набор | Модель | Прогон | «можно» | «с условиями» | «нельзя» | critical | Документы с «нельзя» |",
         "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |"]
    for k in keys:
        rs = groups[k]
        dev = [(r["verdict"] or {}).get("development") for r in rs]
        no_docs = [r["case"] for r in rs if "no" in (r["verdict"] or {}).values()]
        L.append(f"| {k[0]} | {k[1]} | {rs[0]['label']} ({rs[0]['at'][11:16] or rs[0]['at']}) | "
                 f"{dev.count('yes')} | {dev.count('conditional')} | {len(no_docs)} из {len(rs)} | "
                 f"{sum(r['critical'] for r in rs)} | {', '.join(sorted(no_docs)) or '—'} |")
    return "\n".join(L) + "\n\n"


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


ORDER = ["чистые ТЗ №20", "№18: чистые версии (2-я редакция)", "№18: чистые версии (1-я редакция)",
         "корпус: базы и перефразы", "прочие чистые"]
SUPERSEDED = {"№18: чистые версии (1-я редакция)"}  # документы заменены второй редакцией — в устойчивость не идут
_SHA = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,8}\b")


def _is_no(r: dict) -> bool:
    return "no" in (r["verdict"] or {}).values()


def stability(rows: list[dict]) -> dict[tuple, dict[str, list[dict]]]:
    """(набор, модель) → документ → его прогоны по времени. Только прогоны модели: без правил без модели (они
    детерминированы), без повторов ответов из кэша (`calls` = 0 — та же выборка, что у исходного прогона) и без
    заменённых наборов (`SUPERSEDED`)."""
    out: dict[tuple, dict[str, list[dict]]] = {}
    for r in rows:
        if r["model"].startswith("офлайн") or r.get("calls") == 0 or r["set"] in SUPERSEDED:
            continue
        out.setdefault((r["set"], r["model"]), {}).setdefault(r["case"], []).append(r)
    for docs in out.values():
        for rs in docs.values():
            rs.sort(key=lambda r: (0 if r["at"].startswith("~") or not r["at"] else 1, r["at"], r["label"]))
    return out


def render_stability(rows: list[dict]) -> str:
    """«Устойчивость по документам»: в скольких прогонах модели на наборе документ получил «нельзя» и critical.
    Во всех — систематика (чинить первым), в части — шум модели; наборы и модели с одним прогоном не показываются."""
    groups = {k: v for k, v in stability(rows).items() if max(len(rs) for rs in v.values()) > 1}
    if not groups:
        return ""
    keys = sorted(groups, key=lambda k: (ORDER.index(k[0]) if k[0] in ORDER else 9, k[1]))
    L = ["", "### Чистые ТЗ — устойчивость по документам (все прогоны модели, без повторов из кэша)", "",
         "Сколько раз документ получил «нельзя» и critical во всех прогонах этой модели на наборе (на разных коммитах). "
         "Во всех — систематика: чинить первым; в части — шум модели.", "",
         "| Документ | Набор | Модель | Прогонов | «нельзя» | critical (прогонов) | major по прогонам | Итог |",
         "| :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- |"]
    notes = []
    for k in keys:
        docs = groups[k]
        flagged = []
        for case, rs in docs.items():
            no, crit = sum(_is_no(r) for r in rs), sum(1 for r in rs if r["critical"])
            if no or crit:
                flagged.append((-max(no, crit), -no, case, rs, no, crit))
        for _, _, case, rs, no, crit in sorted(flagged):
            n = len(rs)
            worst = max(no, crit)
            verdict = ("один прогон" if n == 1 else
                       f"во всех {n} — систематика" if worst == n else f"{worst} из {n} — плавает")
            L.append(f"| {case} | {k[0]} | {k[1]} | {n} | {no} | {crit} | "
                     f"{', '.join(str(r['major']) for r in rs)} | {verdict} |")
        runs = sorted({(r["at"], r["label"]) for rs in docs.values() for r in rs},
                      key=lambda x: (0 if x[0].startswith("~") or not x[0] else 1, x[0]))
        clean = sorted(c for c, rs in docs.items() if not any(_is_no(r) or r["critical"] for r in rs))
        codes = ", ".join(f"{at[11:16] or at}" + (f" ({_SHA.findall(lb)[0]})" if _SHA.findall(lb) else "")
                          for at, lb in runs)
        notes.append(f"{k[0]}, {k[1]} — прогонов {len(runs)}: {codes}; во всех без «нельзя» и critical: "
                     f"{', '.join(clean) or '—'}.")
    L += ["", *[f"* {n}" for n in notes]]
    return "\n".join(L) + "\n"


def recurring(rows: list[dict], min_runs: int = 2) -> list[dict]:
    """Повторяющиеся ложные замечания (critical и major) на чистом документе: одна и та же жалоба в ≥ `min_runs`
    прогонах модели (выборка — как в `stability`). Жалобы склеиваются по заголовку (`common.cluster_by_title`) —
    модель каждый раз формулирует её чуть иначе."""
    out = []
    for (set_name, model), docs in stability(rows).items():
        for case, rs in docs.items():
            rs = [r for r in rs if r.get("findings") is not None]
            if len(rs) < min_runs:
                continue
            for c in cluster_by_title([(i, f) for i, r in enumerate(rs) for f in r["findings"]]):
                runs = sorted({i for i, _ in c})
                if len(runs) < min_runs:
                    continue
                sev = {i: ("critical" if any(f.get("severity") == "critical" for j, f in c if j == i) else "major")
                       for i in runs}
                src: dict[str, int] = {}
                for i in runs:
                    for x in sorted({x for j, f in c if j == i for x in (f.get("sources") or [])}):
                        src[x] = src.get(x, 0) + 1
                owners = sorted({o for _, f in c for o in (f.get("owners") or [])})
                out.append({"set": set_name, "model": model, "case": case, "runs": len(runs), "of": len(rs),
                            "severity": [sev[i] for i in runs], "at": [rs[i]["at"] for i in runs],
                            "last": len(rs) - 1 in runs, "title": c[-1][1].get("title") or "",
                            "sources": src, "owners": owners})
    out.sort(key=lambda x: (ORDER.index(x["set"]) if x["set"] in ORDER else 9, x["model"],
                            -("critical" in x["severity"]), -x["runs"], x["case"]))
    return out


def render_recurring(rows: list[dict]) -> str:
    """Таблица «повторяющиеся ложные замечания»: что именно модель раз за разом находит на чистом документе."""
    rec = recurring(rows)
    if not rec:
        return ""
    sev = {"critical": "c", "major": "m"}
    L = ["", "### Чистые ТЗ — повторяющиеся ложные замечания (critical и major в 2 и больше прогонах)", "",
         "Одна жалоба (заголовки близки по словам) в нескольких прогонах модели на том же чистом документе: в каждом — "
         "систематическая ошибка линзы или судьи, либо неясное место документа (тогда — автору набора). Серьёзность "
         "по прогонам: c — critical, m — major.", "",
         "| Документ | Набор | Модель | Прогонов | Серьёзность | Замечание (последняя формулировка) | В последнем прогоне | "
         "Источники (прогонов) | Владельцы |",
         "| :--- | :--- | :--- | ---: | :--- | :--- | :---: | :--- | :--- |"]
    for x in rec:
        src = ", ".join(f"{k.replace('lens:', '')} {v}" for k, v in sorted(x["sources"].items(), key=lambda kv: (-kv[1], kv[0])))
        title = x["title"].replace("|", "/")
        L.append(f"| {x['case']} | {x['set']} | {x['model']} | {x['runs']} из {x['of']} | "
                 f"{' '.join(sev[v] for v in x['severity'])} | {title} | {'да' if x['last'] else 'нет'} | {src} | "
                 f"{', '.join(x['owners'])} |")
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
    rows = _corpus_rows() + _newtz_rows() + _open2_rows() + _external_rows()
    groups = latest(rows)
    text = render_verdicts(groups) + render(groups) + render_stability(rows) + render_recurring(rows)
    print(text)
    if a.write:
        write_results(render(groups) + render_stability(rows) + render_recurring(rows))
        put_results_block(RESULTS, "verdict", render_verdicts(groups, heading=False), "Вердикт на исправленных ТЗ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
