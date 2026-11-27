"""Устойчивость дефектов: ``--runs N`` (№22).

N независимых проходов рецензентов и судьи по одной нарезке (нарезка и правила — из первого прохода, чтобы
ID требований совпадали). Дефекты проходов сводятся в группы по строкам цитат и виду дефекта; у каждой группы —
устойчивость k/N (в скольких проходах найден). В реестр идут группы с k ≥ ⌈N/2⌉, остальные — в приложение
``findings_unstable``. Проход, который целиком не удался (status failed), в N не считается.

Отчёт строится на первом проходе: его дефекты, вопросы и чек-лист; дефект, найденный только в других проходах
(но устойчиво), добавляется в реестр с новым ID и пометкой ``stability.first_pass``.
"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any, Callable

KEEP_FIELDS = ("k", "n", "passes")


def _lines(f: dict, first: int | None = None) -> set[int]:
    out: set[int] = set()
    ev = [e for e in (f.get("evidence") or []) if isinstance(e, dict)]
    for e in ev[:first] if first else ev:
        a = e.get("line_start") or e.get("line")
        b = e.get("line_end") or a
        if isinstance(a, int):
            out.update(range(a, (b if isinstance(b, int) and b >= a else a) + 1))
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[0-9a-zа-яё]{4,}", (text or "").lower())}


def similarity(a: dict, b: dict) -> float:
    """0 — разные дефекты; чем больше, тем вероятнее один и тот же. Нужна общая строка цитаты."""
    la, lb = _lines(a), _lines(b)
    if not la or not lb or not (la & lb):
        return 0.0
    jac = len(la & lb) / len(la | lb)
    main = bool(_lines(a, 2) & _lines(b, 2))
    same_kind = a.get("kind") and a.get("kind") == b.get("kind")
    same_crit = a.get("criterion") and a.get("criterion") == b.get("criterion")
    ra, rb = set(a.get("requirement_ids") or []), set(b.get("requirement_ids") or [])
    wa, wb = _words(str(a.get("title") or "") + " " + str(a.get("problem") or "")), \
        _words(str(b.get("title") or "") + " " + str(b.get("problem") or ""))
    words = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    if not (same_kind or same_crit or words >= 0.2 or jac >= 0.5):
        return 0.0
    return round(jac + 0.5 * main + 0.3 * bool(same_kind) + 0.2 * bool(same_crit)
                 + 0.2 * bool(ra & rb) + words, 4)


def group(passes: list[list[dict]]) -> list[dict]:
    """Группы дефектов по проходам: [{"rep": дефект, "pass": i, "hits": {i, …}}] в порядке первого появления."""
    clusters: list[dict] = []
    for i, findings in enumerate(passes):
        pairs = sorted(((similarity(c["rep"], g), ci, gi) for ci, c in enumerate(clusters)
                        for gi, g in enumerate(findings)), key=lambda t: (-t[0], t[1], t[2]))
        used_c: set[int] = set()
        used_g: set[int] = set()
        for score, ci, gi in pairs:
            if score <= 0 or ci in used_c or gi in used_g or i in clusters[ci]["hits"]:
                continue
            clusters[ci]["hits"].add(i)
            used_c.add(ci)
            used_g.add(gi)
        for gi, g in enumerate(findings):
            if gi not in used_g:
                clusters.append({"rep": g, "pass": i, "hits": {i}})
    return clusters


def _next_id(ids: list[str]) -> Callable[[], str]:
    nums = [int(m.group(1)) for x in ids for m in [re.fullmatch(r"D-(\d+)", str(x or ""))] if m]
    state = {"n": max(nums or [0])}

    def nxt() -> str:
        state["n"] += 1
        return f"D-{state['n']:02d}"
    return nxt


def merge(base: dict, others: list[dict], n_requested: int) -> dict:
    """Свести отчёт первого прохода ``base`` с отчётами остальных проходов ``others``."""
    report = base
    ok = [0] + [i + 1 for i, r in enumerate(others) if (r.get("run") or {}).get("status") != "failed"]
    reps = [base] + others
    n = len(ok)
    thr = math.ceil(n / 2)
    clusters = group([list(reps[i].get("findings") or []) for i in ok])
    req_ids = {r.get("id") for r in base.get("requirements") or []}
    nxt = _next_id([f.get("id") for f in base.get("findings") or []])
    kept: list[dict] = []
    unstable: list[dict] = []
    added = 0
    for c in clusters:
        f = c["rep"] if c["pass"] == 0 else copy.deepcopy(c["rep"])
        passes = sorted(ok[i] + 1 for i in c["hits"])
        f["stability"] = {"k": len(c["hits"]), "n": n, "passes": passes}
        if c["pass"] != 0:
            f["stability"]["first_pass"] = ok[c["pass"]] + 1
            f["id"] = nxt()
            f["candidate_ids"] = []
            f["requirement_ids"] = [r for r in f.get("requirement_ids") or [] if r in req_ids]
            f.pop("priority", None)
        if len(c["hits"]) >= thr:
            kept.append(f)
            added += c["pass"] != 0
        else:
            unstable.append(f)
    base_ids = [f.get("id") for f in base.get("findings") or []]
    kept.sort(key=lambda f: (base_ids.index(f["id"]) if f.get("id") in base_ids else len(base_ids)))
    gone = {f.get("id") for f in unstable}
    report["findings"] = kept
    report["findings_unstable"] = unstable
    for q in report.get("questions") or []:
        q["finding_ids"] = [x for x in q.get("finding_ids") or [] if x not in gone]
    for c in report.get("checklist") or []:
        if isinstance(c, dict):
            c["finding_ids"] = [x for x in c.get("finding_ids") or [] if x not in gone]
    v = report.setdefault("verdict", {})
    v["fix_first"] = [x for x in v.get("fix_first") or [] if x not in gone]
    calls = sum(int(((r.get("run") or {}).get("calls") or {}).get("total") or 0) for r in reps)
    cost = sum(float((r.get("run") or {}).get("cost_usd") or 0) for r in reps)
    tok_in = sum(int(((r.get("run") or {}).get("tokens") or {}).get("input") or 0) for r in reps)
    tok_out = sum(int(((r.get("run") or {}).get("tokens") or {}).get("output") or 0) for r in reps)
    report["stability"] = {
        "runs_requested": n_requested, "runs_counted": n, "threshold": thr,
        "rule": f"в реестре — дефекты, найденные не меньше чем в {thr} из {n} проходов",
        "passes": [{"pass": i + 1, "run_id": (r.get("run") or {}).get("run_id"),
                    "status": (r.get("run") or {}).get("status"), "findings": len(r.get("findings") or [])
                    if i else len(base_ids), "calls": int(((r.get("run") or {}).get("calls") or {}).get("total") or 0)}
                   for i, r in enumerate(reps)],
        "kept": len(kept), "unstable": len(unstable), "added_from_other_passes": added,
        "calls_total": calls, "cost_usd_total": round(cost, 4), "tokens_total": {"input": tok_in, "output": tok_out},
    }
    run = report.setdefault("run", {})
    run.setdefault("options", {})["runs"] = n_requested
    run["stability"] = {"runs": n, "threshold": thr, "calls_total": calls}
    failed = [p["pass"] for p in report["stability"]["passes"] if p["status"] == "failed"]
    if failed:
        run.setdefault("warnings", []).append(
            f"Проходы {', '.join(map(str, failed))} из {n_requested} не удались и в устойчивость не считаются "
            f"(считано {n})")
    return report


def repeat(base: dict, p: Any, input_path: str | Path, opts: dict, n: int, log: Callable[[str], None]) -> dict:
    """Проходы 2…N на нарезке первого прохода ``p`` и сведение (``merge``)."""
    from .pipeline import LLM_STAGES, Pipeline, _execute
    others = []
    spent_usd = float((base.get("run") or {}).get("cost_usd") or 0)
    spent_tok = sum(int(v or 0) for v in ((base.get("run") or {}).get("tokens") or {}).values())
    for k in range(2, n + 1):
        o = {**opts, "pass_index": k, "run_id": None, "clarify": False, "answers": None, "revise": False,
             "runs": 1}
        # потолок --max-cost — на все проходы вместе: проходу достаётся остаток
        if opts.get("max_cost_usd"):
            o["max_cost_usd"] = float(opts["max_cost_usd"]) - spent_usd
        if opts.get("max_tokens"):
            o["max_tokens"] = int(opts["max_tokens"]) - spent_tok
        if (opts.get("max_cost_usd") and o["max_cost_usd"] <= 0) or (opts.get("max_tokens") and o["max_tokens"] <= 0):
            base.setdefault("run", {}).setdefault("warnings", []).append(
                f"Проходы {k}–{n} не выполнялись: потолок --max-cost исчерпан")
            break
        log(f"Проход {k} из {n}")
        rep = _execute(Pipeline(input_path, o, reuse=p.run, rerun=set(LLM_STAGES) - {"segment"}, log=log),
                       input_path)
        others.append(rep)
        spent_usd += float((rep.get("run") or {}).get("cost_usd") or 0)
        spent_tok += sum(int(v or 0) for v in ((rep.get("run") or {}).get("tokens") or {}).values())
    return merge(base, others, n)


def markdown(report: dict) -> str:
    """Раздел отчёта: устойчивость проходов и приложение с неустойчивыми дефектами."""
    st = report.get("stability") or {}
    if not st:
        return ""
    n, thr = st.get("runs_counted"), st.get("threshold")
    lines = ["## Устойчивость: независимые проходы", "",
             f"Проверка выполнена {st.get('runs_requested')} раз(а) независимо (засчитано проходов: {n}). "
             f"В реестре — дефекты, найденные не меньше чем в {thr} из {n} проходов; у каждого в JSON — "
             f"`stability.k` из `stability.n`. Вызовов модели всего: {st.get('calls_total')}.", "",
             "| Проход | Статус | Дефектов |", "| ---: | :--- | ---: |"]
    for p in st.get("passes") or []:
        lines.append(f"| {p.get('pass')} | {p.get('status')} | {p.get('findings')} |")
    kept = report.get("findings") or []
    lines += ["", "| Дефект | Найден в проходах |", "| :--- | :--- |"]
    for f in kept:
        s = f.get("stability") or {}
        lines.append(f"| {f.get('id')} | {s.get('k')} из {s.get('n')} |")
    unstable = report.get("findings_unstable") or []
    lines += ["", "### Приложение. Неустойчивые замечания", ""]
    if not unstable:
        lines += ["Нет: все найденные дефекты повторились в большинстве проходов.", ""]
        return "\n".join(lines) + "\n"
    lines += [f"Найдены меньше чем в {thr} из {n} проходов — проверьте вручную; в вердикт не входят.", ""]
    for f in unstable:
        s = f.get("stability") or {}
        ev = next((e for e in f.get("evidence") or [] if isinstance(e, dict)), {})
        where = f"строка {ev.get('line_start')}" if ev.get("line_start") else ""
        lines.append(f"- {s.get('k')} из {s.get('n')} · {f.get('title')}"
                     + (f" — «{ev.get('quote')}», {where}" if ev.get("quote") else ""))
    return "\n".join(lines) + "\n"
