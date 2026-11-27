"""Офлайн-режим (`--provider offline`): предварительная проверка без модели.

    from bcc_review.v2.rules import offline
    report = offline.build(view, requirements=None)     # dict по форме report.json (CONTRACT 2.6)
    md = offline.render(report)                         # Markdown: рендер №13, если он есть, иначе свой

Что в отчёте: только кандидаты и сигналы правил. Вердикт:
* «не определено» (`undetermined`) — по умолчанию: смысл требований без модели не проверялся;
* «нельзя» (`no`) — только если правило нашло конфликт двух цитат об одном предмете или критичный дефект
  (обещанная, но не описанная операция) — так же считает `render.jsonout.rule_verdict` №13;
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


HOW_TO_FULL = [
    "Получите бесплатный ключ модели: https://aistudio.google.com/apikey (войдите своим аккаунтом и создайте "
    "ключ).",
    "Создайте в корне репозитория файл `.env` из шаблона `.env.example` и впишите ключ в строку "
    "`GEMINI_API_KEY=` (или задайте переменную окружения `GEMINI_API_KEY`).",
    "Повторите ту же команду `python -m bcc_review <файл требований> <отчёт.md>` — агент сам найдёт ключ, "
    "полная проверка занимает несколько минут.",
]


def verdict(findings: list[dict]) -> dict:
    """Офлайн-вердикт; совпадает с `render.jsonout.rule_verdict` для provider = offline (иначе `verify` упадёт):
    «нельзя» — при противоречии двух цитат об одном предмете или критичном дефекте правила (обещанная, но не
    описанная операция); иначе «не определено». «Можно» без модели не бывает."""
    proven = [f for f in findings if (f.get("rule_conflict") and len(f.get("evidence") or []) >= 2)
              or f.get("severity") == "critical"]
    dev = [f for f in proven if f.get("blocks") in ("development", "both")]
    test = [f for f in proven if f.get("blocks") in ("testing", "both")]
    blocking = dev or test
    tail = ("Смысл требований без модели не проверялся (противоречия правил, критерии приёмки, полнота основной "
            "функции), поэтому отсутствие других замечаний не означает, что их нет. Для полного ревью нужен ключ "
            "модели: бесплатный ключ — https://aistudio.google.com/apikey, строка GEMINI_API_KEY в файле .env.")
    if blocking:
        conf = [f["id"] for f in blocking if f.get("rule_conflict")][:5]
        crit = [f["id"] for f in blocking if f.get("severity") == "critical" and not f.get("rule_conflict")][:3]
        parts = []
        if conf:
            parts.append(f"противоречия двух мест документа с цитатами ({', '.join(conf)})")
        if crit:
            parts.append(f"обещанную, но не описанную операцию ({', '.join(crit)})")
        what = "разработку" if dev and not test else ("тестирование" if test and not dev else "разработку и тестирование")
        summary = (f"Даже без модели правила нашли {' и '.join(parts)}: {what} начинать нельзя, пока это не исправлено. "
                   + tail)
    else:
        summary = "Вердикт не определён: без модели проверены только формальные признаки. " + tail
    return {"development": "no" if dev else "undetermined", "testing": "no" if test else "undetermined",
            "summary": summary, "fix_first": [f["id"] for f in blocking[:3]]}


def _git_state() -> tuple[str, bool]:
    """Коммит агента и признак незакоммиченных правок (для паспорта); без git — пусто."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    try:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=5).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=5).stdout.strip())
        return commit, dirty
    except Exception:  # noqa: BLE001
        return "", False


def build(view: dict, requirements: Any = None, *, started_at: str | None = None,
          rules_out: dict | None = None, reason: str = "") -> dict:
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
    commit, dirty = _git_state()
    return {
        "schema": "bcc-review/2",
        "title": TITLE,
        "run": {"agent": "bcc_review", "version": "2", "commit": commit, "dirty": dirty,
                "provider": "offline", "model_requested": "",
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
        "offline": {
            "title": TITLE,
            "reason": reason or "модель не настроена: нет ключа модели и программы claude",
            "found": _found_line(findings),
            "how_to_full": HOW_TO_FULL,
            "not_checked": NOT_CHECKED,
        },
        "summary": {"requirements": len(reqs or []), "findings": sev,
                    "requirements_without_findings": max(0, len(reqs or []) - len(with_findings)),
                    "quotes_verified": quotes_total},
    }


VERDICT_RU = {"no": "нельзя", "undetermined": "не определено", "conditional": "с условиями", "yes": "можно"}
VERDICT_MD = {"no": "⛔ нельзя начинать", "undetermined": "❔ не определено", "conditional": "⚠️ с условиями",
              "yes": "✅ можно", "none": "— не вынесен"}
SEV_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡"}


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    return one if n10 == 1 and n100 != 11 else (few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many)


def _found_line(findings: list[dict]) -> str:
    n = len(findings)
    if not n:
        return "Без модели правила замечаний не нашли."
    sev = {k: sum(1 for f in findings if f.get("severity") == k) for k in ("critical", "major", "minor")}
    conf = sum(1 for f in findings if f.get("rule_conflict"))
    s = (f"Без модели найдено {n} {_plural(n, 'замечание', 'замечания', 'замечаний')}: критичных {sev['critical']}, "
         f"существенных {sev['major']}, незначительных {sev['minor']}")
    if conf:
        s += f"; {conf} из них — противоречия двух мест документа, у каждого две цитаты"
    return s + ". Все цитаты сверены с документом."
SEV_RU = {"critical": "критичное", "major": "существенное", "minor": "незначительное"}


def render(report: dict) -> str:
    """Markdown: рендер №13, если он есть, иначе короткий отчёт `render_brief`."""
    try:
        from bcc_review.v2.render import markdown as md13  # type: ignore

        return md13.render(report)
    except Exception:  # noqa: BLE001 — рендера №13 нет или он упал
        return render_brief(report)


def _place(e: dict) -> str:
    a, b = e.get("line_start"), e.get("line_end")
    s = f"строка {a}" if a == b or not b else f"строки {a}–{b}"
    return (f"с. {e['page']}, " if e.get("page") else "") + s


def _first_sentence(text: str, limit: int = 240) -> str:
    """Текст целиком, если короче limit, иначе — столько целых предложений, сколько помещается."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    k = max(cut.rfind(". "), cut.rfind("; "))
    return t[:k + 1] if k > 40 else cut.rsplit(" ", 1)[0] + "…"


def _md(text: str) -> str:
    """Угловые скобки «<уточнить: …>» иначе спрячет рендер Markdown."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def render_brief(report: dict) -> str:
    """Короткий офлайн-отчёт для читателя без ключа: итог, как получить полную проверку, замечания, оговорки.

    На официальном документе — около 120 строк; на чистом — около 40."""
    v = report.get("verdict") or {}
    doc = report.get("document") or {}
    run = report.get("run") or {}
    off = report.get("offline") or {}
    f = report.get("findings") or []
    title = doc.get("title") or doc.get("file") or "документ"
    out = [f"# {TITLE}: «{title}»", "",
           f"> Модель не вызывалась ({off.get('reason') or 'модель не настроена'}). Документ проверен детерминированными "
           "правилами: контракт API, единицы измерения, заглушки и шаблон, язык требований, явные противоречия. "
           "Это предварительная проверка, а не полное ревью.", ""]
    out += ["## Итог", "",
            "| Разработка | Тестирование |", "| :---: | :---: |",
            f"| **{VERDICT_MD.get(v.get('development'), '—')}** | **{VERDICT_MD.get(v.get('testing'), '—')}** |", "",
            off.get("found") or _found_line(f), "", v.get("summary", ""), ""]
    out += ["## Как получить полную проверку", ""]
    out += [f"{i}. {step}" for i, step in enumerate(off.get("how_to_full") or HOW_TO_FULL, 1)]
    out += ["", "Полная проверка добавляет: смысловые противоречия требований и критериев приёмки, неполноту правил "
            "основной функции, вопросы владельцу с вариантами ответа, черновик тест-кейсов и заполненный чек-лист.", ""]
    if f:
        out += ["## Замечания без модели", ""]
        for x in f:
            ev0 = x.get("evidence") or []
            out += [f"### {SEV_ICON.get(x.get('severity'), '')} {x['id']}. {x['title']}", ""]
            for e in ev0[:3]:
                out.append(f"* {_place(e)}: «{e.get('quote', '')}»")
            out += ["", f"**Почему это проблема.** {_md(_first_sentence(x.get('problem', ''), 480))}", "",
                    f"**Что сделать.** {_md(_first_sentence(x.get('recommendation', ''), 320))}", ""]
    # подсказки для человека: без сводок, без служебных указаний модели и без дублей замечаний
    noted = {str(x.get("sources", [""])[0]).split(":", 1)[-1] for x in f}
    sig = [g for g in report.get("signals") or [] if g.get("kind") not in ("inventory", "security")
           and not str(g.get("rule", "")).startswith(("api.", "injection.", "promises."))
           and g.get("rule") not in noted]
    if sig:
        out += ["## Подсказки для ручной проверки", "", "Места, на которые правила обращают внимание; это не замечания.", ""]
        for g in sig[:10]:
            q = g.get("quote", "")
            q = q if len(q) <= 90 else q[:87] + "…"
            out.append(f"* строка {g['line']}: «{q}» — {g.get('message', '')}")
        out.append("")
    out += ["## Что без модели не проверялось", ""] + [f"* {t}" for t in off.get("not_checked") or NOT_CHECKED]
    commit = (run.get("commit") or "")[:7]
    out += ["", f"*Файл `{doc.get('file', '')}`, строк {doc.get('lines', 0)}, SHA-256 `{(doc.get('sha256') or '')[:12]}…`; "
            f"агент{' коммит `' + commit + '`' if commit else ''}; вызовов модели 0. Отчёт сформирован без ручных правок.*"]
    return "\n".join(out) + "\n"


render_fallback = render_brief  # прежнее имя


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
