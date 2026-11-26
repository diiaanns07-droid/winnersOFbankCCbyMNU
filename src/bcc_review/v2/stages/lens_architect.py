"""Линза «Архитектор» (№07): контракт API, полнота операций, стык со спецификацией, данные, события.

Промпт — `prompts/lens_architect.md`. Ответ модели: `candidates` (общая схема кандидатов, CONTRACT 2.3)
плюс `inventory` — опись операций, обещаний, кодов ответа и полей. Опись нужна модели как черновик для
сверки (слабые модели без неё пропускают «нет операции чтения» и расхождения кодов), а отчёту и судье —
как доказательная база.

Постобработка кодом (без модели):
* critical без сценария, последствий или с `blocks = none` понижается до major (CONTRACT, раздел 5);
* точные дубли (тот же вид и тот же набор строк цитат) схлопываются;
* порядок critical → major → minor, не больше MAX_CANDIDATES;
* `requirement_ids`, которых нет в нарезке, убираются (модель иногда ставит ID из документа).
"""
from __future__ import annotations

import copy
from typing import Any

NAME = "architect"
PROMPT = "lens_architect"
SOURCE = "lens:architect"
MAX_CANDIDATES = 14

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": list(props) if required is None else required}


_S = {"type": "string"}
_INT = {"type": "integer"}

CANDIDATE_SCHEMA = _obj({
    "title": _S, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
    "requirement_ids": {"type": "array", "items": _S},
    "evidence": {"type": "array", "items": _obj({"quote": _S, "line": _INT})},
    "problem": _S, "scenario": _S, "impact": _S, "recommendation": _S, "rewrite": _S, "question": _S,
    "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]},
})

INVENTORY_SCHEMA = _obj({
    "operations": {"type": "array", "items": _obj({"name": _S, "method": _S, "purpose": _S, "line": _INT})},
    "promises": {"type": "array", "items": _obj({"what": _S, "line": _INT, "operation": _S})},
    "codes": {"type": "array", "items": _obj({
        "code": _S, "lines": {"type": "array", "items": _INT}, "described": {"type": "boolean"}, "note": _S})},
    "fields": {"type": "array", "items": _obj({"name": _S, "places": _S})},
})


def schema(candidate_schema: dict | None = None) -> dict:
    """Схема ответа линзы: опись + кандидаты (по умолчанию — локальная копия схемы кандидатов)."""
    return _obj({"inventory": INVENTORY_SCHEMA,
                 "candidates": {"type": "array", "items": candidate_schema or CANDIDATE_SCHEMA}})


SCHEMA = schema()


def empty_inventory() -> dict:
    return {"operations": [], "promises": [], "codes": [], "fields": []}


def _evidence_key(c: dict) -> tuple:
    lines = sorted({int(e.get("line") or 0) for e in c.get("evidence") or []})
    return (c.get("kind", ""), tuple(lines))


def unfulfilled_promises(inventory: dict) -> list[dict]:
    """Обещания описи, для которых модель не нашла операции (для отчёта и проверки полноты)."""
    return [p for p in (inventory or {}).get("promises") or [] if not str(p.get("operation") or "").strip()]


def postprocess(data: dict, requirement_ids: set[str] | None = None,
                max_candidates: int = MAX_CANDIDATES) -> dict:
    """Нормализует ответ модели. Не меняет вход; возвращает {"candidates": [...], "inventory": {...}}."""
    data = copy.deepcopy(data or {})
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in data.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        c["evidence"] = [e for e in c.get("evidence") or []
                         if isinstance(e, dict) and str(e.get("quote") or "").strip()]
        if not c["evidence"]:
            continue  # нет цитаты — нет утверждения (системный промпт, правило 2)
        if c.get("severity") not in SEVERITY_ORDER:
            c["severity"] = "major"
        if c["severity"] == "critical" and (not str(c.get("scenario") or "").strip()
                                            or not str(c.get("impact") or "").strip()
                                            or c.get("blocks") in (None, "", "none")):
            c["severity"] = "major"
        if requirement_ids is not None:
            c["requirement_ids"] = [r for r in c.get("requirement_ids") or [] if r in requirement_ids]
        key = _evidence_key(c)
        if key in seen:
            continue
        seen.add(key)
        c.setdefault("source", SOURCE)
        out.append(c)
    out.sort(key=lambda c: SEVERITY_ORDER[c["severity"]])  # sort устойчивый: порядок модели внутри уровня
    inv = data.get("inventory") if isinstance(data.get("inventory"), dict) else {}
    inventory = empty_inventory()
    inventory.update({k: v for k, v in inv.items() if k in inventory and isinstance(v, list)})
    return {"candidates": out[:max_candidates], "inventory": inventory}


def run(ctx: Any) -> dict:
    """Запуск линзы через общий механизм `stages/lens.py` (№01) с собственной схемой и постобработкой."""
    from . import lens  # каркас №01

    raw = lens.run(ctx, NAME)
    reqs = {r.get("id") for r in getattr(ctx, "requirements", None) or [] if isinstance(r, dict)}
    result = postprocess(raw, requirement_ids=reqs or None)
    extras = {k: v for k, v in (raw or {}).items() if k not in ("candidates", "inventory")}
    return {**extras, **result}
