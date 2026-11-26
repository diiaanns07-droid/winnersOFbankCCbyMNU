"""Структуры данных v2 (CONTRACT.md, раздел 2): перечисления, TypedDict и JSON Schema ответов модели.

Все структуры — обычные ``dict``. Пустые списки ``[]``, необязательные строки ``""``.
"""
from __future__ import annotations

from typing import Any, TypedDict

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
SEVERITIES = ["critical", "major", "minor"]
BLOCKS = ["development", "testing", "both", "none"]
REQUIREMENT_KINDS = ["functional", "nonfunctional", "data", "integration", "ui", "process", "architecture", "api",
                     "acceptance", "constraint", "goal", "other"]
VERIFIED = ["exact", "normalized", "fuzzy", "missing"]
STAGE_STATES = ["ok", "partial", "failed", "skipped"]
RUN_STATES = ["complete", "partial", "failed"]

# Этапы конвейера в порядке выполнения. Линзы и набор идут параллельно.
LENSES = ["analyst", "qa", "architect", "risk"]
STAGES = ["segment", "rules"] + [f"lens_{x}" for x in LENSES] + ["consistency", "quotes", "judge", "clarify"]

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
    "risk": ["Чек-лист ревью требований банка"],
}


class Line(TypedDict, total=False):
    n: int
    text: str
    page: int | None
    section: str
    src_line: int
    block_id: str


class DocView(TypedDict, total=False):
    title: str
    file: str
    format: str
    sha256: str
    lines: list[Line]
    pages: int | None
    warnings: list[str]


class Requirement(TypedDict, total=False):
    id: str
    source_id: str
    kind: str
    section: str
    summary: str
    quote: str
    line_start: int
    line_end: int
    page: int | None


class Evidence(TypedDict, total=False):
    quote: str
    line: int
    line_start: int
    line_end: int
    page: int | None
    section: str
    verified: str


class Candidate(TypedDict, total=False):
    id: str
    source: str
    title: str
    kind: str
    criterion: str
    severity: str
    requirement_ids: list[str]
    evidence: list[Evidence]
    problem: str
    scenario: str
    impact: str
    recommendation: str
    rewrite: str
    question: str
    blocks: str


class Finding(Candidate, total=False):
    candidate_ids: list[str]
    standard_refs: list[str]
    priority: int
    sources: list[str]


# --------------------------------------------------------------------------- JSON Schema ответов модели

def obj(props: dict, required: list | None = None) -> dict:
    """Объект схемы со строгими полями (все обязательны, лишние запрещены) — формат, который понимают все провайдеры."""
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": list(props) if required is None else required}


STR = {"type": "string"}
INT = {"type": "integer"}
EVIDENCE_SCHEMA = {"type": "array", "items": obj({"quote": STR, "line": INT})}
CANDIDATE_SCHEMA = obj({
    "title": STR, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": SEVERITIES},
    "requirement_ids": {"type": "array", "items": STR}, "evidence": EVIDENCE_SCHEMA,
    "problem": STR, "scenario": STR, "impact": STR, "recommendation": STR, "rewrite": STR, "question": STR,
    "blocks": {"type": "string", "enum": BLOCKS},
})
CANDIDATES_SCHEMA = obj({"candidates": {"type": "array", "items": CANDIDATE_SCHEMA}})


def empty_for(schema: dict) -> Any:
    """Минимальное значение, проходящее схему: пустые списки, пустые строки, первые значения перечислений."""
    if not isinstance(schema, dict):
        return None
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0])
    if t == "object":
        props = schema.get("properties") or {}
        return {k: empty_for(props.get(k, {})) for k in (schema.get("required") or [])}
    if t == "array":
        return []
    if t == "string":
        return ""
    if t in ("integer", "number"):
        return 0
    if t == "boolean":
        return False
    if t == "null":
        return None
    return None


def conform(value: Any, schema: dict) -> Any:
    """Привести значение к схеме мягко: убрать лишние поля объектов, дописать недостающие обязательные.

    Нужен mock-провайдеру (в фикстурах бывают служебные поля `id`, `page`) и для записанных ответов.
    Типы не исправляет: если значение не того типа — возвращает его как есть, проверка схемы это поймает.
    """
    if not isinstance(schema, dict):
        return value
    t = schema.get("type")
    if t == "object" and isinstance(value, dict):
        props = schema.get("properties")
        if props is None:
            return value
        out = {}
        for k, v in value.items():
            if k in props:
                out[k] = conform(v, props[k])
            elif schema.get("additionalProperties", True) is not False:
                out[k] = v
        for k in schema.get("required") or []:
            if k not in out:
                out[k] = empty_for(props.get(k, {}))
        return out
    if t == "array" and isinstance(value, list):
        items = schema.get("items")
        return [conform(v, items) for v in value] if isinstance(items, dict) else value
    return value
