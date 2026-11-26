"""Короткая сводка в терминал после прогона (владелец №13).

    print(console.summary(report, md_path="reports/x.md", json_path="reports/x.json"))
"""

from __future__ import annotations

from . import jsonout
from .markdown import BLOCKS, PROVIDERS, STATUS, duration, plural, shorten

READY = {"no": "нельзя", "conditional": "с условиями", "yes": "можно", "none": "не вынесен"}


def summary(report: dict, *, md_path: str | None = None, json_path: str | None = None, width: int = 100) -> str:
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
    model = ", ".join(run.get("models_used") or []) or PROVIDERS.get(run.get("provider"), run.get("provider") or "—")
    lines.append(f"Прогон {STATUS.get(run.get('status'), run.get('status') or '—')}: {duration(run.get('duration_s'))}, "
                 f"{calls} {plural(int(calls or 0), 'вызов', 'вызова', 'вызовов')} модели, {model}; "
                 f"цитат сверено {s.get('quotes_verified', 0)} из {s.get('quotes_total', s.get('quotes_verified', 0))}")
    out = [p for p in (md_path, json_path) if p]
    if out:
        lines.append("Отчёт: " + " и ".join(out))
    for w in (run.get("warnings") or [])[:3]:
        lines.append(f"  ! {shorten(w, width - 4)}")
    return "\n".join(lines)
