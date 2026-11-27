"""Короткая сводка в терминал после прогона (владелец №13).

    print(console.summary(report, md_path="reports/x.md", json_path="reports/x.json"))
"""

from __future__ import annotations

from . import jsonout
import re

from . import markdown as _md
from .markdown import BLOCKS, STATUS, _clean_report, duration, plural, shorten


def plain_warn(text) -> str:
    """Предупреждение этапа для терминала: «Этап consistency не выполнен» → «Этап «Набор целиком» не выполнен»,
    critical → критичный, «линза» → «роль»; без разметки Markdown."""
    s = _md.dejargon(" ".join(str(text or "").split()))
    m = _md._STAGE_PREFIX.match(s)
    if m and _md.stage_key(m.group(1)) in _md.STAGES:
        s = f"{_md.STAGES[_md.stage_key(m.group(1))][0]}: " + s[m.end():]
    s = _md._EXC_PAREN.sub("", _md._EXC.sub("", s))
    s = _md._STAGE_WORD.sub(lambda m: f"«{_md.STAGES[m.group(1)][0]}»", s)
    s = _md._SEV_WORD.sub(lambda m: _md.SEV_NAME[m.group(1)], s)
    return _md.count_words(_md._LREF.sub(_md._lref, s))

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
    nreq = s.get("requirements", 0)
    reqs = (f"{nreq} {plural(nreq, 'требование', 'требования', 'требований')}" if nreq or run.get("provider") != "offline"
            else "требования без модели не выделялись")
    lines = [
        f"BCC Review: «{doc.get('title') or doc.get('file') or 'документ'}» — {reqs}, {total} "
        f"{plural(total, 'дефект', 'дефекта', 'дефектов')} (критичных {fs.get('critical', 0)}, существенных "
        f"{fs.get('major', 0)}, незначительных {fs.get('minor', 0)}), вопросов {nq}",
    ]
    verdict = f"Разработка: {READY.get(v.get('development'), '—')} · тестирование: {READY.get(v.get('testing'), '—')}"
    # те же блокеры и тот же порядок, что на первом экране отчёта; число блокеров — всегда полное (раньше терминал
    # показывал 3 блокера при счётчике 4); без блокеров — три пункта «исправить первым»
    ctx = _md._Ctx(report)
    blockers = _md._blockers(ctx)
    order = _md._first_screen_fix(ctx, blockers)
    shown = [f for f in order if f in blockers] + [f for f in blockers if f not in order]
    if blockers:
        same = len({f.get("blocks") for f in blockers}) == 1
        n = len(blockers)
        lines.append(verdict + (f" — блокер 1, останавливает {BLOCKS.get(blockers[0].get('blocks'), '—')}:" if n == 1
                                else f" — блокеров {n}" + (f", каждый останавливает "
                                                           f"{BLOCKS.get(blockers[0].get('blocks'), '—')}:" if same else ":")))
        top = shown[:3] if n > 4 else shown
        for f in top:
            tail = "" if same else f" — блокирует {BLOCKS.get(f.get('blocks'), '—')}"
            lines.append(f"  {f['id']} {shorten(f.get('title'), width - 8 - len(tail))}{tail}")
        if len(shown) > len(top):
            rest = shown[len(top):]
            lines.append(f"  и ещё {len(rest)}: " + ", ".join(f["id"] for f in rest) + " — в отчёте, раздел «Кратко»")
    else:
        lines.append(verdict)
        first = order[:3]
        if first:
            lines[-1] += " — исправить первым:"
        for f in first:
            lines.append(f"  {f['id']} {shorten(f.get('title'), width - 8)}")
    calls = (run.get("calls") or {}).get("total", 0)
    model = ", ".join(run.get("models_used") or []) or PLAIN_PROVIDERS.get(run.get("provider"), run.get("provider") or "—")
    cached = (run.get("calls") or {}).get("cached", 0)
    why = ""
    if run.get("status") == "partial":
        try:
            why = _md._partial_reason(_md._Ctx(report))
        except Exception:  # noqa: BLE001
            why = ""
    lines.append(f"Прогон {STATUS.get(run.get('status'), run.get('status') or '—')}"
                 + (f" ({re.sub(r'`', '', why)})" if why else "") + f": {duration(run.get('duration_s'))}, "
                 f"{calls} {plural(int(calls or 0), 'вызов', 'вызова', 'вызовов')} модели"
                 + (f" (+{cached} из кэша)" if cached else "") + f", {model}; "
                 f"цитат сверено {s.get('quotes_verified', 0)} из {s.get('quotes_total', s.get('quotes_verified', 0))}")
    out = [p for p in (md_path, json_path) if p]
    if out:
        lines.append("Отчёт: " + " и ".join(out))
    warns = [str(w) for w in run.get("warnings") or []]
    err = " ".join(str(run.get("model_error") or "").split())
    if err:  # объяснение, почему модель не работала, и где взять ключ — целиком, одной строкой (№02)
        lines.append(f"  ! {err}")
        warns = [w for w in warns if " ".join(w.split()) != err]
    for w in warns[:3 if not err else 2]:
        lines.append(f"  ! {shorten(plain_warn(w), width - 4)}")
    return "\n".join(lines)
