"""Постобработка ответа линзы «Аналитик» (владелец — №05).

Модель, особенно слабая, нарушает правила промпта: завышает серьёзность, дублирует один дефект,
выходит за лимит кандидатов. Здесь эти правила применяются кодом, детерминированно:

1. кандидат без единой цитаты отбрасывается;
2. дубли (тот же тип и тот же набор строк-цитат) схлопываются в первого;
3. неединичность (`non_singular`) и чистый язык без последствий не бывают выше `minor`;
4. `critical` без сценария, последствий, с `blocks = none` или с типом, который не означает расхождения
   двух мест документа (`ambiguity`, `incomplete`…), понижается до `major`: critical у этой линзы — только
   когда другое место документа прямо поддерживает иное толкование;
5. `critical` больше двух — лишние понижаются до `major` (линза смотрит на отдельные формулировки,
   несовместимые результаты двух мест ловят другие этапы);
6. сортировка: critical → major → minor, внутри — порядок модели;
7. не больше 12 кандидатов.

Функция чистая: принимает и возвращает списки dict по схеме кандидата (CONTRACT, раздел 2.3).
"""
from __future__ import annotations

from typing import Any

MAX_CANDIDATES = 12
MAX_CRITICAL = 2
_RANK = {"critical": 0, "major": 1, "minor": 2}
_MINOR_ONLY_KINDS = {"non_singular"}
_CRITICAL_KINDS = {"event_conflict", "boundary_conflict", "unit_mismatch", "contradiction", "status_conflict"}


def _lines(c: dict) -> tuple:
    out = []
    for ev in c.get("evidence") or []:
        n = ev.get("line_start", ev.get("line"))
        out.append(n if isinstance(n, int) else str(ev.get("quote", "")).strip().lower())
    return tuple(sorted(out, key=str))


def _has_evidence(c: dict) -> bool:
    return any(str(ev.get("quote", "")).strip() for ev in c.get("evidence") or [])


def postprocess(candidates: list[dict[str, Any]], *, max_candidates: int = MAX_CANDIDATES,
                max_critical: int = MAX_CRITICAL) -> list[dict[str, Any]]:
    """Применить правила линзы к ответу модели. Не меняет входной список."""
    seen: set[tuple] = set()
    kept: list[dict] = []
    for raw in candidates or []:
        if not isinstance(raw, dict) or not _has_evidence(raw):
            continue
        c = dict(raw)
        key = (c.get("kind", ""), _lines(c))
        if key in seen:
            continue
        seen.add(key)
        sev = c.get("severity") if c.get("severity") in _RANK else "major"
        if c.get("kind") in _MINOR_ONLY_KINDS:
            sev = "minor"
        if sev == "critical" and (c.get("kind") not in _CRITICAL_KINDS
                                  or not str(c.get("scenario", "")).strip()
                                  or not str(c.get("impact", "")).strip()
                                  or c.get("blocks", "none") == "none"):
            sev = "major"
        c["severity"] = sev
        kept.append(c)

    critical = 0
    for c in kept:
        if c["severity"] == "critical":
            critical += 1
            if critical > max_critical:
                c["severity"] = "major"

    order = sorted(range(len(kept)), key=lambda i: (_RANK[kept[i]["severity"]], i))
    return [kept[i] for i in order][:max_candidates]


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01)."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    out = dict(lens_run(ctx, "analyst"))
    out["candidates"] = postprocess(out.get("candidates") or [])
    return out
