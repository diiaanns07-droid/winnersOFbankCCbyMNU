"""Общий контракт v1 агента статического ревью ТЗ.

Единственный источник правды о типах на стыках 18 модулей. Файл ``contracts/v1.json``
генерируется из :data:`REPORT_SCHEMA` командой ``python -m bcc_review.contracts --write``
и проверяется тестом ``tests/contract``. Правки контракта вносит владелец интерфейса (Max).

Ключевые правила:

* ``Document.id`` — SHA-256 исходных байтов файла.
* Координаты в ``block.text`` — кодовые точки Unicode с нуля, правая граница исключена.
  Для подтверждённой опоры выполняется ``block.text[start:end] == quote``.
* Строки Markdown и страницы PDF нумеруются с 1.
* Списки без записей — пустые массивы, а не ``null``.
* Семантический модуль получает ``ask(stage, payload, schema)`` и обратно — объект,
  уже проверенный по ``schema``. Ошибка — исключение :class:`AskError`.
* Адаптер провайдера сообщает об ошибке через :class:`ProviderError`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, TypedDict

SCHEMA_VERSION = "1.0"
CONTRACT_ID = "bcc-review/contract/v1"

# --------------------------------------------------------------------------- перечисления
SEVERITIES = ("critical", "major", "minor")
SCOPES = ("requirement", "set")
FINDING_STATUSES = ("confirmed", "needs_review")
ANCHOR_STATUSES = ("supported", "incomplete")
# Подтверждение смысла — отдельный от цитаты результат проверки.
MEANING_STATUSES = ("confirmed", "uncertain", "unchecked", "deterministic")
CHECK_STATUSES = ("pass", "issue", "unknown", "na")
COVERAGE_STATUSES = ("covered", "partial", "conflict", "uncovered", "unknown")
HINT_STATUSES = ("matched", "missing", "ambiguous")
RUN_STATUSES = ("complete", "partial", "failed")
RUN_MODES = ("rules_plus_llm", "rules_only", "mock")
READINESS = ("ready", "not_ready", "unknown")
STAGE_STATUSES = ("ok", "cached", "partial", "failed", "skipped")
REVIEW_STATUSES = ("reviewed", "partial", "not_reviewed")
CHECK_MARKS = ("yes", "no", "na", "unknown")
BLOCK_KINDS = ("heading", "paragraph", "list_item", "table_header", "table_row", "code", "quote", "other")
DOC_FORMATS = ("markdown", "text", "pdf", "docx", "html")
PROVIDERS = ("anthropic", "gemini", "mock", "none")
BLOCKS_TARGETS = ("development", "testing")
FINDING_KINDS = (
    "ambiguity", "unverifiable", "incomplete", "conflict", "omission", "non_singular",
    "design_in_requirement", "terminology", "traceability", "placeholder", "infeasible",
    "incorrect", "duplicate", "format", "other",
)
# Коды критериев (ISO/IEC/IEEE 29148:2018 5.2.5/5.2.6, IEEE 830-1998 4.3). Конфиг серьёзности — criteria.toml (№05).
INDIVIDUAL_CRITERIA = (
    "necessary", "appropriate", "unambiguous", "complete", "singular",
    "feasible", "verifiable", "correct", "conforming",
)
SET_CRITERIA = ("set_complete", "set_consistent", "set_feasible", "set_comprehensible", "set_validatable",
                "ranked", "modifiable", "traceable")
# Коды предупреждений документа, означающие неполное чтение (готовность не может быть положительной).
PARTIAL_READ_CODES = ("partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input")
# Информационные предупреждения чтения: на полноту прогона не влияют.
INFO_WARNING_CODES = ("encoding_guess", "empty_page", "images_not_read", "pdf_repaired")

# Коды выхода CLI (согласуются с №18).
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_BLOCKER = 3          # --fail-on blocker и готовность разработки/тестирования не «ready»
EXIT_VERIFY_FAILED = 4    # verify нашёл расхождение
EXIT_PARTIAL = 5          # --fail-on partial и прогон не complete


# --------------------------------------------------------------------------- типы (для подсказок IDE)
class Hint(TypedDict, total=False):
    block_id: str
    quote: str
    context: str


class Evidence(TypedDict):
    block_id: str
    start: int
    end: int
    quote: str


class Block(TypedDict):
    id: str
    kind: str
    section: list[str]
    text: str
    loc: dict[str, Any]


class Document(TypedDict):
    id: str
    title: str
    format: str
    blocks: list[Block]
    warnings: list[dict[str, Any]]


class Requirement(TypedDict, total=False):
    id: str
    source_id: Optional[str]
    text: str
    block_ids: list[str]
    evidence: list[Evidence]
    hints: list[Hint]
    kind: str
    review_status: str
    review_reason: Optional[str]


class Candidate(TypedDict, total=False):
    scope: str
    kind: str
    criterion: str
    severity: str
    title: str
    impact: str
    req_ids: list[str]
    hints: list[Hint]
    inspected_block_ids: list[str]
    recommendation: str
    blocked_decision: str
    cause: dict[str, Any]
    witness: dict[str, Any]
    source: str
    stage: str


Report = dict  # каноническая форма — dict по REPORT_SCHEMA


# --------------------------------------------------------------------------- ошибки
TRANSIENT_KINDS = ("rate_limit", "overloaded", "server", "timeout", "network")
PROVIDER_ERROR_KINDS = TRANSIENT_KINDS + (
    "auth", "not_configured", "bad_request", "not_found", "refusal", "truncated", "invalid_output",
    "quota", "unknown",
)


class ProviderError(Exception):
    """Ошибка адаптера провайдера (№11, №12). ``kind`` — из :data:`PROVIDER_ERROR_KINDS`.

    ``retry_after_s`` — значение Retry-After в секундах, если провайдер его прислал.
    Повторы и бюджет решает движок, адаптер сам не повторяет запрос.
    """

    def __init__(self, kind: str, message: str = "", *, retry_after_s: Optional[float] = None,
                 status: Optional[int] = None, request_id: Optional[str] = None,
                 usage: Optional[dict[str, int]] = None, model: Optional[str] = None):
        super().__init__(message or kind)
        self.kind = kind if kind in PROVIDER_ERROR_KINDS else "unknown"
        self.message = message or kind
        self.retry_after_s = retry_after_s
        self.status = status
        self.request_id = request_id
        self.usage = usage or {}
        self.model = model

    @property
    def transient(self) -> bool:
        return self.kind in TRANSIENT_KINDS


class AskError(Exception):
    """``ask`` не смог вернуть проверенный объект. Модуль может перехватить и вернуть частичный результат."""

    def __init__(self, stage: str, kind: str, message: str = ""):
        super().__init__(f"{stage}: {kind}: {message}" if message else f"{stage}: {kind}")
        self.stage = stage
        self.kind = kind
        self.message = message


class BudgetExhausted(AskError):
    def __init__(self, stage: str, message: str = ""):
        super().__init__(stage, "budget_exhausted", message)


class ContractError(ValueError):
    """Объект нарушает контракт v1."""


# --------------------------------------------------------------------------- интерфейсы
class Ask(Protocol):
    def __call__(self, stage: str, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> dict: ...


class ProviderAdapter(Protocol):
    """Адаптер провайдера: №11 (Anthropic), №12 (Gemini), mock.

    ``invoke`` возвращает ``{"data": <объект по schema>, "usage": {"input_tokens", "output_tokens", ...},
    "model": <фактическая модель>, "request_id": str|None, "stop_reason": str|None}``.
    Усечённый ответ → ``ProviderError("truncated")``; невалидный JSON → ``ProviderError("invalid_output")``.
    """

    name: str

    def invoke(self, *, model: str, messages: list[dict[str, Any]], schema: Mapping[str, Any],
               timeout_s: float) -> dict[str, Any]: ...


# Формат payload для ask(stage, payload, schema):
#   {"task": str — инструкция этапа на русском (промпт модуля),
#    "input": любой JSON — данные этапа,
#    "context": {"mode": "auto"|"full"|"blocks"|"none", "block_ids": [...]}  — необязательно}
# Движок сам прикладывает текст документа: малый документ целиком (части A и B вместе),
# большой — индекс всех требований + запрошенные блоки + блоки по межсекционным ссылкам.
ASK_PAYLOAD_KEYS = ("task", "input", "context")


@dataclass
class RunOptions:
    """Параметры ``run_review``. CLI и веб (№15) передают один и тот же объект (или dict)."""

    provider: str = "anthropic"            # anthropic | gemini | mock | none
    model: Optional[str] = None            # по умолчанию из ANTHROPIC_MODEL / GEMINI_MODEL
    offline_lint: bool = False             # только детерминированные правила
    answers_path: Optional[str] = None     # --answers answers.md
    compare_path: Optional[str] = None     # --compare old.json
    exports: tuple[str, ...] = ()          # html, pdf, docx, jira
    cache_dir: Optional[str] = None
    use_cache: bool = True
    max_calls: int = 40                    # физические вызовы на прогон (включая повторы)
    max_seconds: float = 1500.0            # общий бюджет времени
    max_tokens: Optional[int] = None       # суммарный бюджет токенов (вход+выход), None — без лимита
    max_retries: int = 3                   # конечные повторы временных ошибок
    timeout_s: float = 300.0               # таймаут одного вызова
    trace: bool = True                     # безопасная JSONL-трасса этапов
    fail_on: Optional[str] = None          # blocker | partial
    mock_script: Optional[str] = None      # JSON со сценарием mock-провайдера
    allow_partial_ready: bool = False      # разрешить «ready» при partial (по умолчанию — нет)
    full_context_chars: int = 120_000      # порог «малого» документа
    run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    artifacts_dir: Optional[str] = None

    @classmethod
    def coerce(cls, options: "RunOptions | Mapping[str, Any] | None") -> "RunOptions":
        if options is None:
            return cls()
        if isinstance(options, cls):
            return options
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(options) - known
        if unknown:
            raise ContractError(f"неизвестные параметры run_review: {sorted(unknown)}")
        data = dict(options)
        if "exports" in data and data["exports"] is not None:
            data["exports"] = tuple(data["exports"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["exports"] = list(self.exports)
        return d


# --------------------------------------------------------------------------- JSON Schema
def _obj(props: dict[str, Any], required: list[str] | tuple[str, ...] = (), *, extra: bool = True) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": extra}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def _enum(values: tuple[str, ...]) -> dict:
    return {"type": "string", "enum": list(values)}


def _ref(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}"}


_STR = {"type": "string"}
_NSTR = {"type": ["string", "null"]}
_INT0 = {"type": "integer", "minimum": 0}
_STRS = _arr(_STR)

DEFS: dict[str, Any] = {
    "Hint": _obj({"block_id": _NSTR, "quote": _STR, "context": _STR}, ["quote"]),
    "Evidence": _obj({"block_id": _STR, "start": _INT0, "end": _INT0, "quote": _STR},
                     ["block_id", "start", "end", "quote"]),
    "Loc": _obj({
        "line_start": {"type": "integer", "minimum": 1},
        "line_end": {"type": "integer", "minimum": 1},
        "map": {"type": "array"},
        "page": {"type": "integer", "minimum": 1},
        "fragments": _arr(_obj({"start": _INT0, "end": _INT0,
                                "rect": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                                "quad": {"type": "array"}}, ["start", "end", "rect"])),
        "part": _STR, "path": _STR, "runs": {"type": "array"},
        "level": {"type": "integer", "minimum": 1}, "columns": _STRS, "empty": {"type": "boolean"},
        "bbox": {"type": "array", "items": {"type": "number"}}, "table": {},
        "row": {"type": "integer"}, "furniture": {"type": "boolean"}, "lang": _NSTR,
    }),
    "Block": _obj({"id": _STR, "kind": _enum(BLOCK_KINDS), "section": _STRS, "text": _STR, "loc": _ref("Loc")},
                  ["id", "kind", "section", "text", "loc"]),
    "Warning": {"anyOf": [_STR, _obj({"code": _STR, "message": _STR, "stage": _STR, "block_ids": _STRS,
                                      "page": {"type": "integer", "minimum": 1}},
                                     ["code", "message"])]},
    "Document": _obj({
        "id": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "title": _STR, "format": _enum(DOC_FORMATS), "source_name": _STR,
        "blocks": _arr(_ref("Block")), "warnings": _arr(_ref("Warning")),
    }, ["id", "title", "format", "blocks", "warnings"]),
    "Requirement": _obj({
        "id": _STR, "source_id": _NSTR, "text": _STR, "block_ids": _STRS,
        "evidence": _arr(_ref("Evidence")), "hints": _arr(_ref("Hint")), "kind": _STR,
        "section": _STRS,
        "review_status": _enum(REVIEW_STATUSES), "review_reason": _NSTR,
    }, ["id", "source_id", "text", "block_ids", "evidence", "review_status", "review_reason"]),
    "Check": _obj({
        "req_id": _STR, "criterion": _STR, "status": _enum(CHECK_STATUSES), "reason": _STR,
        "finding_ids": _STRS, "source": _STR,
    }, ["req_id", "criterion", "status", "reason"]),
    "Cause": _obj({"object": _STR, "condition": _STR, "outcomes": _STRS}, ["object"]),
    "Witness": _obj({
        "input": _STR, "outcome_a": _STR, "outcome_b": _STR,
        "evidence_a": _ref("Evidence"), "evidence_b": _ref("Evidence"),
    }, ["input", "outcome_a", "outcome_b", "evidence_a", "evidence_b"]),
    "WitnessDraft": _obj({
        "input": _STR, "outcome_a": _STR, "outcome_b": _STR,
        "hint_a": _ref("Hint"), "hint_b": _ref("Hint"),
    }, ["input", "outcome_a", "outcome_b", "hint_a", "hint_b"]),
    "Candidate": _obj({
        "scope": _enum(SCOPES), "kind": _STR, "criterion": _STR, "severity": _enum(SEVERITIES),
        "title": _STR, "impact": _STR, "req_ids": _STRS, "hints": _arr(_ref("Hint")),
        "inspected_block_ids": _STRS, "recommendation": _STR, "blocked_decision": _STR,
        "cause": _ref("Cause"), "witness": _ref("WitnessDraft"), "source": _STR, "stage": _STR,
    }, ["scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints"]),
    "Finding": _obj({
        "id": _STR, "scope": _enum(SCOPES), "kind": _STR, "criterion": _STR, "severity": _enum(SEVERITIES),
        "title": _STR, "impact": _STR, "req_ids": _STRS, "hints": _arr(_ref("Hint")),
        "evidence": _arr(_ref("Evidence")),
        "status": _enum(FINDING_STATUSES), "anchor_status": _enum(ANCHOR_STATUSES),
        "meaning_status": _enum(MEANING_STATUSES), "meaning_reason": _STR,
        "recommendation": _STR, "blocked_decision": _STR,
        "blocks": _arr(_enum(BLOCKS_TARGETS)),
        "witness": {"anyOf": [{"type": "null"}, _ref("Witness")]},
        "inspected_block_ids": _STRS, "merged_from": _STRS,
        "cause": {"anyOf": [{"type": "null"}, _ref("Cause")]},
        "source": _STR, "stage": _STR, "notes": _STRS,
    }, ["id", "scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "evidence",
        "status", "anchor_status", "meaning_status", "blocks", "witness"]),
    "Fact": _obj({
        "id": _STR, "subject": _STR, "field": _STR, "value": {}, "unit": _NSTR, "type": _NSTR,
        "direction": _NSTR, "range": {}, "req_ids": _STRS, "evidence": _arr(_ref("Evidence")),
    }, ["id", "subject", "field", "value", "evidence"]),
    "Coverage": _obj({
        "req_id": _STR, "obligation": _STR, "acceptance_ids": _STRS, "status": _enum(COVERAGE_STATUSES),
        "explanation": _STR, "hints": _arr(_ref("Hint")), "evidence": _arr(_ref("Evidence")),
    }, ["req_id", "obligation", "acceptance_ids", "status", "explanation"]),
    "Question": _obj({
        "id": _STR, "finding_ids": _STRS, "prompt": _STR, "options": _STRS, "affected_req_ids": _STRS,
    }, ["id", "finding_ids", "prompt", "options", "affected_req_ids"]),
    "Edit": _obj({"block_id": _STR, "start": _INT0, "end": _INT0, "old": _STR, "new": _STR},
                 ["block_id", "start", "end", "old", "new"]),
    "Decision": _obj({
        "question_id": _STR, "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "answer": _STR, "edits": _arr(_ref("Edit")), "note": _STR,
    }, ["question_id", "source_sha256", "answer"]),
    "ChecklistRow": _obj({
        "id": _STR, "text": _STR, "available": _enum(CHECK_MARKS), "checked": _enum(CHECK_MARKS),
        "note": _STR, "finding_ids": _STRS, "evidence": _arr(_ref("Evidence")),
    }, ["text", "available", "checked", "note", "finding_ids", "evidence"]),
    "TestCase": _obj({
        "id": _STR, "precondition": _STR, "action": _STR, "expected": _STR, "req_ids": _STRS,
        "open_question_id": _NSTR,
    }, ["id", "precondition", "action", "expected", "req_ids", "open_question_id"]),
    "DiffEntry": _obj({
        "old_ids": _STRS, "new_ids": _STRS, "reason": _STR, "evidence": _arr(_ref("Evidence")),
    }, ["old_ids", "new_ids", "reason", "evidence"]),
    "Diff": _obj({
        "previous": _obj({"source_sha256": _STR, "run_id": _NSTR}, ["source_sha256"]),
        "current": _obj({"source_sha256": _STR, "run_id": _NSTR}, ["source_sha256"]),
        "resolved": _arr(_ref("DiffEntry")), "persisting": _arr(_ref("DiffEntry")),
        "introduced": _arr(_ref("DiffEntry")), "unassessed": _arr(_ref("DiffEntry")),
        "impacted_req_ids": _STRS, "warnings": _arr(_ref("Warning")),
    }, ["previous", "current", "resolved", "persisting", "introduced", "unassessed", "warnings"]),
    "Readiness": _obj({
        "status": _enum(READINESS), "reasons": _STRS, "finding_ids": _STRS,
    }, ["status", "reasons", "finding_ids"]),
    "Verdict": _obj({
        "development": _ref("Readiness"), "testing": _ref("Readiness"),
        "first_actions": _arr(_obj({"order": {"type": "integer", "minimum": 1}, "action": _STR,
                                    "finding_ids": _STRS}, ["order", "action", "finding_ids"])),
        "basis": _STR,
    }, ["development", "testing", "first_actions"]),
    "Stage": _obj({
        "name": _STR, "status": _enum(STAGE_STATUSES), "calls": _INT0, "cache_hits": _INT0,
        "retries": _INT0, "model": _NSTR, "reason": _NSTR, "duration_s": {"type": "number", "minimum": 0},
        "input_tokens": _INT0, "output_tokens": _INT0, "implementation": _STR,
    }, ["name", "status", "calls", "cache_hits", "reason"]),
    "EvidenceAudit": _obj({
        "checked": _INT0, "confirmed": _INT0, "ambiguous": _INT0, "rejected": _INT0, "note": _STR,
    }, ["checked", "confirmed", "ambiguous", "rejected", "note"]),
    "Run": _obj({
        "run_id": _STR, "parent_run_id": _NSTR,
        "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "source_name": _STR,
        "agent_version": _STR, "agent_commit": _NSTR,
        "provider": _enum(PROVIDERS), "model": _NSTR, "requested_model": _NSTR,
        "models_seen": _STRS,
        "mode": _enum(RUN_MODES), "status": _enum(RUN_STATUSES), "status_reasons": _STRS,
        "started_at": _STR, "finished_at": _STR, "duration_s": {"type": "number", "minimum": 0},
        "calls": _obj({"physical": _INT0, "cache_hits": _INT0, "failed": _INT0, "retries": _INT0},
                      ["physical", "cache_hits", "failed", "retries"]),
        "tokens": _obj({"input": _INT0, "output": _INT0, "cache_read": _INT0}, ["input", "output"]),
        "budget": _obj({"max_calls": _INT0, "max_seconds": {"type": "number"}, "max_tokens": {"type": ["integer", "null"]},
                        "exhausted": {"type": "boolean"}, "reason": _NSTR}, ["max_calls", "max_seconds", "exhausted"]),
        "stages": _arr(_ref("Stage")), "incomplete_stages": _STRS,
        "modules": {"type": "object", "additionalProperties": _STR},
        "evidence_audit": _ref("EvidenceAudit"),
        "options": {"type": "object"},
        "context_policy": _STR,
    }, ["run_id", "source_sha256", "agent_version", "provider", "model", "mode", "status",
        "started_at", "finished_at", "calls", "tokens", "stages", "incomplete_stages", "evidence_audit"]),
    "Summary": _obj({
        "requirements": _INT0, "reviewed_requirements": _INT0, "findings": _INT0,
        "by_severity": _obj({s: _INT0 for s in SEVERITIES}, SEVERITIES),
        "by_status": _obj({s: _INT0 for s in FINDING_STATUSES}, FINDING_STATUSES),
        "critical_ids": _STRS,
        "checks": _obj({s: _INT0 for s in CHECK_STATUSES}, CHECK_STATUSES),
    }, ["requirements", "reviewed_requirements", "findings", "by_severity", "by_status", "critical_ids", "checks"]),
}

REPORT_KEYS = ("schema_version", "run", "document", "requirements", "checks", "findings", "facts", "coverage",
               "questions", "checklist", "test_cases", "decisions", "diff", "verdict", "summary", "warnings")

REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/contracts/v1.json",
    "title": "BCC requirements review report, contract v1",
    "description": "Канонический Report. Markdown, HTML, PDF, DOCX и Jira строятся из этого объекта.",
    "type": "object",
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "run": _ref("Run"),
        "document": _ref("Document"),
        "requirements": _arr(_ref("Requirement")),
        "checks": _arr(_ref("Check")),
        "findings": _arr(_ref("Finding")),
        "facts": _arr(_ref("Fact")),
        "coverage": _arr(_ref("Coverage")),
        "questions": _arr(_ref("Question")),
        "checklist": _arr(_ref("ChecklistRow")),
        "test_cases": _arr(_ref("TestCase")),
        "decisions": _arr(_ref("Decision")),
        "diff": {"anyOf": [{"type": "null"}, _ref("Diff")]},
        "verdict": _ref("Verdict"),
        "summary": _ref("Summary"),
        "warnings": _arr(_ref("Warning")),
        "excluded": _arr(_obj({"block_ids": _STRS, "reason": _STR}, ["block_ids", "reason"])),
        "rejected": _arr(_obj({"candidate": {"type": "object"}, "reason": _STR, "stage": _STR}, ["candidate", "reason"])),
    },
    "required": list(REPORT_KEYS),
    "additionalProperties": True,
    "$defs": DEFS,
}


def as_plain(obj: Any) -> Any:
    """Объект модуля → JSON-совместимые dict/list контракта (рекурсивно): ``to_dict()``, dataclass, кортежи."""
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return as_plain(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__") and not isinstance(obj, type):
        return as_plain(asdict(obj))
    if isinstance(obj, Mapping):
        return {str(k): as_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [as_plain(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def normalize_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Привести Document читателя к единой форме стыка (движок вызывает после чтения):

    * ``section`` — полный путь заголовков от корня (если читатель дал ``loc.section_ids``);
    * ``loc.columns`` — заголовки столбцов для строк таблиц (если они лежат в ``loc.table.columns``).
    """
    doc = as_plain(doc)
    blocks = doc.get("blocks", [])
    heads = {b["id"]: b["text"] for b in blocks if b.get("kind") == "heading"}
    for b in blocks:
        loc = b.setdefault("loc", {})
        ids = loc.get("section_ids")
        if isinstance(ids, list) and ids and all(i in heads for i in ids):
            path = [heads[i] for i in ids]
            if not b.get("section") or b["section"] == path[-len(b["section"]):]:
                b["section"] = path
        tbl = loc.get("table")
        if b.get("kind") in ("table_header", "table_row") and "columns" not in loc and isinstance(tbl, dict)                 and isinstance(tbl.get("columns"), list):
            loc["columns"] = list(tbl["columns"])
    return doc


def subschema(name: str) -> dict[str, Any]:
    """Схема одного типа (``Document``, ``Candidate``…) с общими ``$defs`` — для проверки на стыках."""
    if name not in DEFS:
        raise KeyError(name)
    return {"$schema": REPORT_SCHEMA["$schema"], "$defs": DEFS, **_ref(name)}


# --------------------------------------------------------------------------- проверка
def _validator(schema: Mapping[str, Any]):
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema в основных зависимостях
        raise RuntimeError("нужен пакет jsonschema: pip install jsonschema") from exc
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema)


def validation_errors(obj: Any, schema: Mapping[str, Any], limit: int = 20) -> list[str]:
    errs = []
    for err in sorted(_validator(schema).iter_errors(obj), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errs.append(f"{path}: {err.message}")
        if len(errs) >= limit:
            break
    return errs


def validate(obj: Any, name: str = "Report") -> None:
    """Проверить объект по контракту. ``name`` — ``Report`` или имя из ``DEFS``."""
    schema = REPORT_SCHEMA if name == "Report" else subschema(name)
    errs = validation_errors(obj, schema)
    if errs:
        raise ContractError(f"{name} нарушает контракт v1: " + "; ".join(errs))


def evidence_errors(report: Mapping[str, Any]) -> list[str]:
    """Семантические инварианты, которых нет в JSON Schema: опоры совпадают с текстом блоков, ID уникальны."""
    errs: list[str] = []
    blocks = {b["id"]: b for b in report.get("document", {}).get("blocks", [])}
    if len(blocks) != len(report.get("document", {}).get("blocks", [])):
        errs.append("document.blocks: повторяющиеся id блоков")

    def check_ev(where: str, ev: Any) -> None:
        if not isinstance(ev, Mapping) or not {"block_id", "start", "end", "quote"} <= set(ev):
            errs.append(f"{where}: опора не в формате Evidence")
            return
        b = blocks.get(ev.get("block_id"))
        if b is None:
            errs.append(f"{where}: блок {ev.get('block_id')!r} отсутствует")
            return
        if not (0 <= ev["start"] <= ev["end"] <= len(b["text"])):
            errs.append(f"{where}: диапазон {ev['start']}:{ev['end']} вне блока {b['id']}")
        elif b["text"][ev["start"]:ev["end"]] != ev["quote"]:
            errs.append(f"{where}: цитата не совпадает с текстом блока {b['id']}")

    for kind in ("requirements", "findings", "facts", "coverage", "checklist"):
        ids = [x.get("id") for x in report.get(kind, []) if x.get("id") is not None]
        if len(ids) != len(set(ids)):
            errs.append(f"{kind}: повторяющиеся id")
        for i, item in enumerate(report.get(kind, [])):
            for j, ev in enumerate(item.get("evidence", []) or []):
                check_ev(f"{kind}[{i}].evidence[{j}]", ev)
            w = item.get("witness")
            if w:
                check_ev(f"{kind}[{i}].witness.evidence_a", w["evidence_a"])
                check_ev(f"{kind}[{i}].witness.evidence_b", w["evidence_b"])
    req_ids = {r["id"] for r in report.get("requirements", [])}
    for i, f in enumerate(report.get("findings", [])):
        for rid in f.get("req_ids", []):
            if rid not in req_ids:
                errs.append(f"findings[{i}]: ссылка на неизвестное требование {rid}")
        if f.get("status") == "confirmed" and f.get("anchor_status") != "supported":
            errs.append(f"findings[{i}]: confirmed без подтверждённой опоры")
        if f.get("kind") == "conflict" and f.get("status") == "confirmed" and not f.get("witness"):
            errs.append(f"findings[{i}]: подтверждённый конфликт без witness")
    return errs


# --------------------------------------------------------------------------- утилиты
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Стабильная сериализация для хешей и кэша."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def empty_report_skeleton() -> dict[str, Any]:
    """Списки пустые, а не null: удобно для модулей, которые заполняют часть отчёта."""
    return {
        "schema_version": SCHEMA_VERSION, "run": {}, "document": {}, "requirements": [], "checks": [],
        "findings": [], "facts": [], "coverage": [], "questions": [], "checklist": [], "test_cases": [],
        "decisions": [], "diff": None, "verdict": {}, "summary": {}, "warnings": [], "excluded": [], "rejected": [],
    }


def schema_json() -> str:
    return json.dumps(REPORT_SCHEMA, ensure_ascii=False, indent=2) + "\n"


def _main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[2]
    target = root / "contracts" / "v1.json"
    if "--write" in argv:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(schema_json(), encoding="utf-8", newline="\n")
        print(f"записано: {target}")
        return 0
    if "--check" in argv:
        ok = target.exists() and target.read_text(encoding="utf-8") == schema_json()
        print("contracts/v1.json актуален" if ok else "contracts/v1.json устарел: python -m bcc_review.contracts --write")
        return 0 if ok else 1
    sys.stdout.write(schema_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
