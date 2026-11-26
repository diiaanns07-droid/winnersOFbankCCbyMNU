"""Офлайн-режим (`--provider offline`): предварительная проверка без модели.

    from bcc_review.v2.rules import offline
    report = offline.build(view, requirements=None)     # dict по форме report.json (CONTRACT 2.6)
    md = offline.render(report)                         # Markdown: рендер №13, если он есть, иначе свой

Что в отчёте: только кандидаты и сигналы правил. Вердикт:
* «не определено» (`undetermined`) — по умолчанию: смысл требований без модели не проверялся;
* «нельзя» (`no`) — только если правило нашло конфликт двух цитат об одном предмете;
* «можно начинать» (`yes`) — никогда.
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from . import run as run_rules

TITLE = "Предварительная проверка без модели"

STANDARD_REFS = {
    "necessary": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5"],
    "appropriate": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5"],
    "unambiguous": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5", "IEEE 830-1998 п. 4.3.2"],
    "complete": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5", "IEEE 830-1998 п. 4.3.3"],
    "singular": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5"],
    "feasible": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5"],
    "verifiable": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5", "IEEE 830-1998 п. 4.3.6"],
    "correct": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5", "IEEE 830-1998 п. 4.3.1"],
    "conforming": ["ISO/IEC/IEEE 29148:2018 п. 5.2.5"],
    "language": ["ISO/IEC/IEEE 29148:2018 п. 5.2.7"],
    "set_complete": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6", "IEEE 830-1998 п. 4.3.3"],
    "set_consistent": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6", "IEEE 830-1998 п. 4.3.4"],
    "set_feasible": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6"],
    "set_comprehensible": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6"],
    "set_validatable": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6"],
    "ranked": ["IEEE 830-1998 п. 4.3.5"],
    "modifiable": ["IEEE 830-1998 п. 4.3.7"],
    "traceable": ["IEEE 830-1998 п. 4.3.8"],
    "risk": ["чек-лист ревью требований банка"],
}

NOT_CHECKED = [
    "противоречия между требованиями и критериями приёмки по смыслу (сценарий «вход → исход A / исход B»);",
    "полнота правил основной функции: границы, ошибки, повторы, отмены, возвраты;",
    "определённость ключевых событий и терминов, роли и права доступа;",
    "проверяемость нефункциональных требований и покрытие критериями приёмки;",
    "риски информационной безопасности и эксплуатации за пределами контракта API.",
]


def _verify(view: dict, cands: list[dict], requirements: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """Сверка цитат №03, если модуль есть; иначе — простая проверка вхождения в строку."""
    try:
        from bcc_review.v2 import quotes  # type: ignore

        res = quotes.verify_candidates(view, cands, requirements or [])
        return list(res.get("candidates") or []), list(res.get("rejected") or [])
    except Exception:  # noqa: BLE001 — сверки №03 ещё нет: проверяем сами
        from ._text import norm

        by_n = {int(x.get("n", i)): x for i, x in enumerate(view.get("lines") or [], 1)}
        kept, rejected = [], []
        for c in cands:
            evs = []
            for e in c["evidence"]:
                ln = by_n.get(int(e["line"])) or {}
                if norm(e["quote"]) and norm(e["quote"]) in norm(str(ln.get("text", ""))):
                    evs.append({**e, "verified": "exact", "line_start": e["line"], "line_end": e["line"],
                                "page": ln.get("page"), "section": ln.get("section", "")})
            if evs:
                kept.append({**c, "evidence": evs})
            else:
                rejected.append({**c, "reason": "цитата не найдена"})
        return kept, rejected


def _finding(i: int, c: dict) -> dict:
    evidence = []
    for e in c["evidence"]:
        evidence.append({"quote": e.get("quote", ""), "line_start": e.get("line_start", e.get("line")),
                         "line_end": e.get("line_end", e.get("line")), "page": e.get("page"),
                         "section": e.get("section", ""), "verified": e.get("verified", "exact")})
    return {
        "id": f"D-{i:02d}", "candidate_ids": [c["id"]] if c.get("id") else [], "title": c["title"],
        "kind": c["kind"], "criterion": c["criterion"], "standard_refs": STANDARD_REFS.get(c["criterion"], []),
        "severity": c["severity"], "requirement_ids": c.get("requirement_ids", []), "evidence": evidence,
        "problem": c["problem"], "scenario": c.get("scenario", ""), "impact": c.get("impact", ""),
        "recommendation": c.get("recommendation", ""), "rewrite": c.get("rewrite", ""),
        "question": c.get("question", ""), "blocks": c.get("blocks", "none"), "priority": 0,
        "sources": [c["source"]], "rule_conflict": bool(c.get("rule_conflict")),
    }


def verdict(findings: list[dict]) -> dict:
    conflicts = [f for f in findings if f.get("rule_conflict") and len(f.get("evidence") or []) >= 2]
    dev = [f for f in conflicts if f.get("blocks") in ("development", "both")]
    test = [f for f in conflicts if f.get("blocks") in ("testing", "both")]
    base = ("Модель не вызывалась: проверены только формальные признаки — контракт API, единицы измерения, "
            "заглушки и шаблон, язык требований. Смысл требований без модели не проверялся")
    if dev or test:
        ids = ", ".join(f["id"] for f in (dev or test)[:5])
        summary = (f"Правила нашли противоречие двух мест документа об одном предмете ({ids}): "
                   f"{'разработку' if dev else ''}{' и ' if dev and test else ''}{'тестирование' if test else ''} "
                   f"начинать нельзя, пока оно не исправлено. {base}, поэтому остальное не оценено.")
    else:
        summary = (f"{base}, поэтому вердикт не определён: отсутствие замечаний здесь не означает, что "
                   "документ готов. Для вердикта запустите проверку с моделью.")
    return {"development": "no" if dev else "undetermined", "testing": "no" if test else "undetermined",
            "summary": summary, "fix_first": [f["id"] for f in (dev or test)[:3]]}


def build(view: dict, requirements: Any = None, *, started_at: str | None = None,
          rules_out: dict | None = None) -> dict:
    """Отчёт по форме report.json для прогона без модели."""
    t0 = time.monotonic()
    started = started_at or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    out = rules_out if rules_out is not None else run_rules(view, requirements)
    reqs = requirements.get("requirements") if isinstance(requirements, dict) else (requirements or [])
    cands = []
    for i, c in enumerate(out["candidates"], 1):
        cands.append({**c, "id": c.get("id") or f"C-{i:03d}"})
    kept, rejected = _verify(view, cands, list(reqs or []))
    findings = [_finding(i, c) for i, c in enumerate(kept, 1)]
    sev = {k: sum(1 for f in findings if f["severity"] == k) for k in ("critical", "major", "minor")}
    quotes_total = sum(len(f["evidence"]) for f in findings)
    with_findings = {r for f in findings for r in f["requirement_ids"]}
    finished = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    return {
        "schema": "bcc-review/2",
        "title": TITLE,
        "run": {"agent": "bcc_review", "version": "2", "provider": "offline", "model_requested": "",
                "models_used": [], "calls": {"total": 0, "cached": 0, "failed": 0, "split": 0},
                "tokens": {"input": 0, "output": 0}, "cost_usd": 0.0, "status": "complete",
                "started_at": started, "finished_at": finished, "duration_s": round(time.monotonic() - t0, 2),
                "stages": {"rules": "ok", "segment": "skipped", "lenses": "skipped", "consistency": "skipped",
                           "judge": "skipped", "clarify": "skipped"},
                "warnings": list(out.get("warnings") or []) + [
                    "Модель не вызывалась (--provider offline): отчёт — предварительная проверка правилами."]},
        "document": {k: view.get(k) for k in ("title", "file", "format", "sha256", "pages")} | {
            "lines": len(view.get("lines") or [])},
        "requirements": list(reqs or []), "excluded": [], "findings": findings, "rejected": rejected,
        "signals": out["signals"], "acceptance_checks": [], "pair_checks": [], "trace": [], "glossary": [],
        "test_cases": [], "questions": [], "checklist": [], "verdict": verdict(findings),
        "not_checked": NOT_CHECKED,
        "summary": {"requirements": len(reqs or []), "findings": sev,
                    "requirements_without_findings": max(0, len(reqs or []) - len(with_findings)),
                    "quotes_verified": quotes_total},
    }


VERDICT_RU = {"no": "нельзя", "undetermined": "не определено", "conditional": "с условиями", "yes": "можно"}
SEV_RU = {"critical": "критичное", "major": "существенное", "minor": "незначительное"}


def render(report: dict) -> str:
    """Markdown: рендер №13, если он умеет офлайн-отчёт, иначе короткий запасной рендер."""
    try:
        from bcc_review.v2.render import markdown as md13  # type: ignore

        return md13.render(report)
    except Exception:  # noqa: BLE001 — рендера №13 ещё нет
        return render_fallback(report)


def _place(e: dict) -> str:
    a, b = e.get("line_start"), e.get("line_end")
    s = f"строка {a}" if a == b or not b else f"строки {a}–{b}"
    return (f"с. {e['page']}, " if e.get("page") else "") + s


def render_fallback(report: dict) -> str:
    v = report["verdict"]
    doc = report.get("document") or {}
    f = report["findings"]
    s = report["summary"]["findings"]
    out = [f"# {TITLE}: {doc.get('title') or doc.get('file') or 'документ'}", ""]
    out += ["> Модель не вызывалась. Это проверка детерминированными правилами: контракт API, единицы, "
            "заглушки и шаблон, язык требований. Отсутствие замечаний не означает готовность документа.", ""]
    out += ["## Кратко", "",
            f"* **Начинать разработку:** {VERDICT_RU.get(v['development'], v['development'])}",
            f"* **Начинать тестирование:** {VERDICT_RU.get(v['testing'], v['testing'])}",
            f"* **Обоснование:** {v['summary']}",
            f"* **Замечаний:** {len(f)} (критичных {s['critical']}, существенных {s['major']}, "
            f"незначительных {s['minor']}); все цитаты сверены с документом.", ""]
    out += ["## Замечания правил", ""]
    if not f:
        out += ["Правила замечаний не нашли.", ""]
    for x in f:
        out += [f"### {x['id']}. {x['title']}", "",
                f"*{SEV_RU.get(x['severity'], x['severity']).capitalize()}* · "
                f"{', '.join(x['standard_refs']) or '—'}", ""]
        for e in x["evidence"]:
            out.append(f"* {_place(e)}: «{e['quote']}»")
        out += ["", f"**Проблема.** {x['problem']}", ""]
        if x.get("scenario"):
            out += [f"**Сценарий.** {x['scenario']}", ""]
        if x.get("impact"):
            out += [f"**Последствия.** {x['impact']}", ""]
        out += [f"**Что сделать.** {x['recommendation']}", ""]
        if x.get("rewrite"):
            out += [f"**Формулировка.** {x['rewrite']}", ""]
    sig = [g for g in report.get("signals") or [] if g.get("kind") != "inventory"]
    if sig:
        out += ["## Подсказки для ручной проверки", "",
                "Места, на которые правила обращают внимание; это не замечания.", ""]
        for g in sig[:20]:
            out.append(f"* строка {g['line']}: «{g['quote']}» — {g['message']}")
        out.append("")
    out += ["## Что без модели не проверялось", ""] + [f"* {t}" for t in report.get("not_checked") or []]
    out += ["", f"Документ: `{doc.get('file', '')}`, строк: {doc.get('lines', 0)}, sha256 `{(doc.get('sha256') or '')[:12]}`."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    """`python -m bcc_review.v2.rules.offline ВХОД ОТЧЁТ.md [--json ОТЧЁТ.json]` — без модели и без сети."""
    import argparse
    import json
    from pathlib import Path

    from ._view import load

    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.rules.offline")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    report = build(load(a.input))
    Path(a.output).write_text(render(report), encoding="utf-8")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    v = report["verdict"]
    print(f"{TITLE}: замечаний {len(report['findings'])}; разработка — {VERDICT_RU[v['development']]}, "
          f"тестирование — {VERDICT_RU[v['testing']]}. Отчёт: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
