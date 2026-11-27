"""Детерминированные правила v2 (№12): сигналы высокой точности для линз и кандидаты для судьи.

    from bcc_review.v2 import rules
    out = rules.run(view, requirements)       # {"signals": [...], "candidates": [...]}
    block = rules.format_signals(out["signals"], audience="architect")   # текст блока <сигналы>

* Кандидат — схема CONTRACT 2.3, `source` = `rules:<правило>`. Цитаты — подстроки строк документа.
* Сигнал — подсказка линзе: `{"id": "S-01", "rule", "kind", "line", "lines", "quote", "message", "note",
  "audience"}` (`lines` — все строки доказательств правила, `note` = `message`),
  `audience` ⊂ {analyst, qa, architect, risk, consistency}.
* Правила не знают слов конкретного документа: словари общие для банковских ТЗ.
"""
from __future__ import annotations

from typing import Any

from . import api, conflicts, injection, language, placeholders, promises, terms, units
from ._text import Doc, build_doc

__all__ = ["run", "format_signals", "signals_for"]

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
# False — линзы получают пустой блок <сигналы> (замер вклада сигналов); кандидаты правил судье идут как обычно.
SIGNALS_ENABLED = True
# True (по умолчанию, замер в status/12.md) — сигнал правила, которое само передало кандидата судье, помечается
# «уже у судьи»: линза его не дублирует,
# а только дополняет (вторая сторона, последствие). Остальные сигналы — подсказки для проверки.
MARK_COVERED = True
AUDIENCES = ("analyst", "qa", "architect", "risk", "consistency")


def _split_requirements(requirements: Any) -> tuple[list[dict] | None, list[dict]]:
    if requirements is None:
        return None, []
    if isinstance(requirements, dict):
        return list(requirements.get("requirements") or []) or None, list(requirements.get("excluded") or [])
    return list(requirements) or None, []


def _req_ids(evidence: list[dict], reqs: list[dict] | None) -> list[str]:
    if not reqs:
        return []
    ids: list[str] = []
    for e in evidence:
        n = e.get("line") or 0
        best = None
        for r in reqs:
            a = int(r.get("line_start") or 0)
            b = int(r.get("line_end") or a)
            if a <= n <= b:
                span = b - a
                if best is None or span < best[0]:
                    best = (span, r.get("id") or "")
        if best and best[1] and best[1] not in ids:
            ids.append(best[1])
    return ids


def _hidden(view: dict) -> list[dict]:
    """Скрытый текст исходного файла: `view["hidden"]` (docview зовёт `rules.hidden.scan_bytes`); для Markdown и TXT
    без него — по строкам документа (комментарии и инлайн-HTML в разметке видны и в строках)."""
    if isinstance(view.get("hidden"), list):
        return view["hidden"]
    if str(view.get("format") or "").lower() in ("md", "markdown", "txt", ""):
        from . import hidden as _hid

        raw = "\n".join(str(ln.get("text", "") if isinstance(ln, dict) else ln) for ln in view.get("lines") or [])
        return _hid.scan_bytes(raw.encode("utf-8"), "md")
    return []


def run(view: dict, requirements: Any = None) -> dict:
    """Все правила по документу. `requirements` — список требований или выход segment целиком."""
    doc: Doc = build_doc(view)
    reqs, excluded = _split_requirements(requirements)
    out: dict = {"signals": [], "candidates": []}
    for name, fn in (("api", lambda: api.run(doc, out)),
                     ("promises", lambda: promises.run(doc, out)),
                     ("units", lambda: units.run(doc, out)),
                     ("conflicts", lambda: conflicts.run(doc, out)),
                     ("injection", lambda: injection.run(doc, out, _hidden(view))),
                     ("placeholders", lambda: placeholders.run(doc, out)),
                     ("language", lambda: language.run(doc, out, reqs, excluded)),
                     ("terms", lambda: terms.run(doc, out))):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — одно сломанное правило не роняет прогон
            out.setdefault("warnings", []).append(f"Правило {name} не выполнено: {type(exc).__name__}: {exc}")
    out.pop("_methods", None)
    cands = []
    for c in out["candidates"]:
        if not c.get("evidence"):
            continue
        c["requirement_ids"] = _req_ids(c["evidence"], reqs)
        cands.append(c)
    cands.sort(key=lambda c: (SEVERITY_ORDER.get(c["severity"], 3), c["evidence"][0]["line"]))
    sigs = sorted(out["signals"], key=lambda s: (s["line"], s["rule"]))
    uniq, seen = [], set()
    for s in sigs:
        key = (s["rule"], s["line"], s["quote"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    ev_lines = {}
    for c in cands:
        ev_lines.setdefault(c["source"].split(":", 1)[1], sorted({e["line"] for e in c["evidence"]}))
    for i, s in enumerate(uniq, 1):
        s["id"] = f"S-{i:02d}"
        s["covered"] = s["rule"] in ev_lines  # у правила есть свой кандидат для судьи
        # вид, удобный линзам (№07): все строки доказательств и пояснение
        s["lines"] = ev_lines.get(s["rule"]) or [s["line"]]
        s["note"] = s["message"]
    res = {"signals": uniq, "candidates": cands}
    if out.get("warnings"):
        res["warnings"] = out["warnings"]
    return res


def signals_for(signals: list[dict], audience: str | None = None) -> list[dict]:
    if not audience:
        return list(signals)
    return [s for s in signals if not s.get("audience") or audience in s["audience"]]


def format_signals(signals: list[dict], audience: str | None = None, limit: int = 40) -> str:
    """Текст блока `<сигналы>`: по строке на сигнал, «S-03 · L104 · «цитата» — пояснение».

    Сигналы — подсказки правил, а не готовые дефекты: модель проверяет их по документу сама.
    """
    if not SIGNALS_ENABLED:
        return "Сигналов правил нет."  # замер вклада сигналов: линзы без блока <сигналы>, кандидаты правил остаются
    items = signals_for(signals, audience)[:limit]
    if not items:
        return "Сигналов правил нет."
    lines = ["Подсказки детерминированных правил (проверь каждую по тексту; это не готовые дефекты):"]
    if MARK_COVERED and any(s.get("covered") for s in items):
        lines.append("Пометка «уже у судьи»: правило само передало это замечание судье. Отдельного кандидата о том же "
                     "не пиши; пиши, только если добавляешь то, чего в сигнале нет (вторую сторону, другое место, "
                     "сценарий с числами).")
    for s in items:
        q = s.get("quote", "")
        q = q if len(q) <= 90 else q[:87] + "…"
        mark = "уже у судьи · " if MARK_COVERED and s.get("covered") else ""
        lines.append(f"{s.get('id', 'S-?')} · L{int(s.get('line') or 0):03d} · {mark}«{q}» — {s.get('message', '')}")
    return "\n".join(lines)
