"""Короткая сводка в терминал после прогона (владелец №13).

    print(console.summary(report, md_path="reports/x.md", json_path="reports/x.json"))
"""

from __future__ import annotations

from . import jsonout
from .markdown import BLOCKS, STATUS, _clean_report, duration, plural, shorten

READY = {"no": "нельзя", "conditional": "с условиями", "yes": "можно", "undetermined": "не определено",
         "none": "не вынесен"}
PLAIN_PROVIDERS = {"claude_cli": "Claude Code (claude -p)", "gemini": "Google Gemini", "anthropic": "Anthropic API",
                   "openai": "OpenAI-совместимый сервер", "mock": "mock", "offline": "без модели"}


def summary(report: dict, *, md_path: str | None = None, json_path: str | None = None, width: int = 100) -> str:
    try:
        return _summary(_clean_report(report), md_path, json_path, width)
    except Exception as exc:  # noqa: BLE001 — сводка в терминал не должна ронять прогон
        paths = " и ".join(p for p in (md_path, json_path) if p)
        return f"BCC Review: сводка не построена ({type(exc).__name__}); отчёт: {paths or '—'}"


def _summary(report: dict, md_path, json_path, width: int) -> str:
    run = report.get("run", {}) or {}
    doc = report.get("document", {}) or {}
    s = report.get("summary") or jsonout.compute_summary(report)
    v = report.get("verdict", {}) or {}
    fs = s.get("findings", {})
    total = sum(fs.get(k, 0) for k in ("critical", "major", "minor"))
    nq = len(report.get("questions") or [])
    lines = [
        f"BCC Review: «{doc.get('title') or doc.get('file') or 'документ'}» — {s.get('requirements', 0)} "
        f"{plural(s.get('requirements', 0), 'требование', 'требования', 'требований')}, {total} "
        f"{plural(total, 'дефект', 'дефекта', 'дефектов')} (критичных {fs.get('critical', 0)}, существенных "
        f"{fs.get('major', 0)}, незначительных {fs.get('minor', 0)}), вопросов {nq}",
        f"Разработка: {READY.get(v.get('development'), '—')} · тестирование: {READY.get(v.get('testing'), '—')}",
    ]
    by_id = {f.get("id"): f for f in report.get("findings") or []}
    first = [by_id[i] for i in v.get("fix_first") or [] if i in by_id][:3]
    if not first:
        first = [f for f in report.get("findings") or [] if f.get("severity") == "critical"][:3]
    for f in first:
        lines.append(f"  {f['id']} {shorten(f.get('title'), width - 8)}"
                     + (f" — блокирует {BLOCKS[f['blocks']]}" if f.get("severity") == "critical"
                        and f.get("blocks") in BLOCKS and f.get("blocks") != "none" else ""))
    calls = (run.get("calls") or {}).get("total", 0)
    model = ", ".join(run.get("models_used") or []) or PLAIN_PROVIDERS.get(run.get("provider"), run.get("provider") or "—")
    cached = (run.get("calls") or {}).get("cached", 0)
    lines.append(f"Прогон {STATUS.get(run.get('status'), run.get('status') or '—')}: {duration(run.get('duration_s'))}, "
                 f"{calls} {plural(int(calls or 0), 'вызов', 'вызова', 'вызовов')} модели"
                 + (f" (+{cached} из кэша)" if cached else "") + f", {model}; "
                 f"цитат сверено {s.get('quotes_verified', 0)} из {s.get('quotes_total', s.get('quotes_verified', 0))}")
    out = [p for p in (md_path, json_path) if p]
    if out:
        lines.append("Отчёт: " + " и ".join(out))
    for w in (run.get("warnings") or [])[:3]:
        lines.append(f"  ! {shorten(w, width - 4)}")
    return "\n".join(lines)
