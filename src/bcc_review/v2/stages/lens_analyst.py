"""Постобработка ответа линзы «Аналитик» (владелец — №05).

Модель, особенно слабая, нарушает правила промпта: завышает серьёзность, дублирует один дефект,
выходит за лимит кандидатов. Здесь эти правила применяются кодом, детерминированно:

1. кандидат без единой цитаты отбрасывается;
2. дубли (тот же тип и тот же набор строк-цитат) схлопываются в первого;
3. неединичность (`non_singular`) не бывает выше `minor`;
4. `critical` без сценария, последствий, с `blocks = none` или без расхождения двух мест документа (тип не из
   расхождений — `ambiguity`, `incomplete`…, или все цитаты из одной строки) понижается до `major`:
   critical у этой линзы — только когда другое место документа прямо поддерживает иное толкование;
5. `critical` больше двух — лишние понижаются до `major`;
6. **зрелый документ** (см. `maturity`) — строгий режим: остаются только расхождения двух мест документа
   (единицы, границы, события, противоречие правил) — `MATURE_MAX_OTHER_MAJOR = 0` прочих `major`, `minor` нет.
   Замер на корпусе (haiku, v13 с одним прочим major): прочие major на мутантах — 21 лишнее замечание при
   1 попадании, на чистых — 7 из 8 замечаний. На сыром документе линза работает в полную силу;
7. сортировка: critical → major → minor, внутри — порядок модели;
8. не больше 12 кандидатов.

Признаки зрелости считаются кодом по тексту документа, без модели: есть раздел терминов, указана версия,
явный часовой пояс (UTC/GMT), нет заглушек («заполняются…», «TBD», неотмеченное «Да / Нет», прочерк
вместо значения). Зрелый — 3 признака из 4.
"""
from __future__ import annotations

import re
from typing import Any

MAX_CANDIDATES = 12
MAX_OUTPUT_TOKENS = 32000  # `lens.run` берёт его из модуля: рассуждение слабой модели + JSON
MAX_CRITICAL = 2
MATURE_MIN_SIGNS = 3
MATURE_MAX_OTHER_MAJOR = 0
_RANK = {"critical": 0, "major": 1, "minor": 2}
_MINOR_ONLY_KINDS = {"non_singular"}
_CONFLICT_KINDS = {"event_conflict", "boundary_conflict", "unit_mismatch", "contradiction", "status_conflict"}
_CRITICAL_KINDS = _CONFLICT_KINDS

_TERMS = re.compile(r"^\s*(?:#+\s*)?(?:термин\w*|глоссари\w*|определени[яе](?:\s+термин\w*)?)\s*:?\s*$", re.I)
_VERSION = re.compile(r"верси[яи]\b[^\n]*\d", re.I)
_TZ = re.compile(r"\b(?:UTC|GMT)\b", re.I)
_PLACEHOLDER = re.compile(
    r"\bTBD\b|\bTODO\b|заполня\w*\s+\w+|не\s+заполнен\w*|Да\s*/\s*Нет|:\s*[—-]\s*(?:\.|$)|\|\s*—\s*(?:\||$)", re.I)


def _texts(view: Any) -> list[str]:
    if isinstance(view, dict):
        return [str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in view.get("lines") or []]
    if isinstance(view, str):
        return view.splitlines()
    return []


def maturity(view: Any) -> dict:
    """Признаки вычитанного документа по его тексту. `mature` — не меньше `MATURE_MIN_SIGNS` из 4."""
    lines = _texts(view)
    signs = {
        "terms": any(_TERMS.match(t) for t in lines),
        "version": any(_VERSION.search(t) for t in lines),
        "timezone": any(_TZ.search(t) for t in lines),
        "no_placeholders": bool(lines) and not any(_PLACEHOLDER.search(t) for t in lines),
    }
    score = sum(signs.values())
    return {**signs, "score": score, "mature": score >= MATURE_MIN_SIGNS}


def _lines(c: dict) -> tuple:
    out = []
    for ev in c.get("evidence") or []:
        n = ev.get("line_start", ev.get("line"))
        out.append(n if isinstance(n, int) else str(ev.get("quote", "")).strip().lower())
    return tuple(sorted(out, key=str))


def _has_evidence(c: dict) -> bool:
    return any(str(ev.get("quote", "")).strip() for ev in c.get("evidence") or [])


def _is_conflict(c: dict) -> bool:
    """Расхождение двух мест: тип расхождения и цитаты хотя бы из двух разных строк."""
    if c.get("kind") not in _CONFLICT_KINDS:
        return False
    lines = {ev.get("line_start", ev.get("line")) for ev in c.get("evidence") or []}
    return len({n for n in lines if isinstance(n, int)}) >= 2


def postprocess(candidates: list[dict[str, Any]], *, mature: bool = False, max_candidates: int = MAX_CANDIDATES,
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
        if sev == "critical" and (not _is_conflict(c)
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

    if mature:
        strict, other = [], 0
        for c in kept:
            if c["severity"] == "minor":
                continue
            if c["severity"] == "major" and not _is_conflict(c):
                other += 1
                if other > MATURE_MAX_OTHER_MAJOR:
                    continue
            strict.append(c)
        kept = strict

    order = sorted(range(len(kept)), key=lambda i: (_RANK[kept[i]["severity"]], i))
    return [kept[i] for i in order][:max_candidates]


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01);
    он сам берёт `MAX_OUTPUT_TOKENS` из этого модуля."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    m = maturity(getattr(ctx, "view", None))
    out = dict(lens_run(ctx, "analyst"))
    out["candidates"] = postprocess(out.get("candidates") or [], mature=m["mature"])
    out["document_maturity"] = m
    return out
