"""Общие помощники резервных экспортов отчёта (Markdown, HTML, Jira CSV).

Работают только с каноническим ``Report`` (dict по ``contracts.REPORT_SCHEMA``) и ничего
не пересчитывают: места в документе берутся из ``block.loc``, числа — из ``report["summary"]``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from ...contracts import INDIVIDUAL_CRITERIA, SET_CRITERIA, SEVERITIES

# --------------------------------------------------------------------------- подписи перечислений
SEVERITY_LABELS = {"critical": "критичное", "major": "существенное", "minor": "незначительное"}
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

FINDING_STATUS_LABELS = {"confirmed": "подтверждено", "needs_review": "требует проверки"}
ANCHOR_STATUS_LABELS = {
    "supported": "цитата сверена с текстом документа",
    "incomplete": "привязка к тексту неполная",
}
MEANING_STATUS_LABELS = {
    "confirmed": "смысл подтверждён",
    "uncertain": "смысл под сомнением",
    "unchecked": "смысл не проверялся",
    "deterministic": "детерминированное правило",
}
SCOPE_LABELS = {"requirement": "отдельное требование", "set": "набор требований"}

CHECK_STATUS_LABELS = {"pass": "соответствует", "issue": "нарушение", "unknown": "не определено",
                       "na": "неприменимо"}
CHECK_STATUS_MARKS = {"pass": "✓", "issue": "✗", "unknown": "?", "na": "—"}
NO_CHECK_MARK = "·"
# Чем больше, тем важнее при сведении нескольких проверок одного критерия в одну ячейку.
CHECK_STATUS_WEIGHT = {"na": 0, "pass": 1, "unknown": 2, "issue": 3}

COVERAGE_STATUS_LABELS = {"covered": "покрыто", "partial": "покрыто частично", "conflict": "противоречие",
                          "uncovered": "не покрыто", "unknown": "не определено"}
CHECK_MARK_LABELS = {"yes": "да", "no": "нет", "na": "неприменимо", "unknown": "не определено"}

RUN_STATUS_LABELS = {"complete": "завершён полностью", "partial": "завершён частично",
                     "failed": "завершился ошибкой"}
RUN_MODE_LABELS = {"rules_plus_llm": "правила + LLM", "rules_only": "только правила, без LLM",
                   "mock": "тестовый, mock-провайдер"}
PROVIDER_LABELS = {"anthropic": "Anthropic", "gemini": "Google Gemini", "mock": "mock (тестовый)",
                   "none": "без провайдера"}
READINESS_LABELS = {"ready": "можно начинать", "not_ready": "нельзя начинать", "unknown": "не определено"}
STAGE_STATUS_LABELS = {"ok": "выполнен", "cached": "из кэша", "partial": "выполнен частично",
                       "failed": "ошибка", "skipped": "пропущен"}
REVIEW_STATUS_LABELS = {"reviewed": "проверено", "partial": "проверено частично",
                        "not_reviewed": "не проверено"}
BLOCKS_TARGET_LABELS = {"development": "разработку", "testing": "тестирование"}
BLOCK_KIND_LABELS = {"heading": "заголовок", "paragraph": "абзац", "list_item": "пункт списка",
                     "table_header": "шапка таблицы", "table_row": "строка таблицы", "code": "код",
                     "quote": "цитата", "other": "фрагмент"}
FINDING_KIND_LABELS = {
    "ambiguity": "неоднозначность", "unverifiable": "непроверяемость", "incomplete": "неполнота",
    "conflict": "противоречие", "omission": "пропуск", "non_singular": "составное требование",
    "design_in_requirement": "проектное решение в требовании", "terminology": "терминология",
    "traceability": "прослеживаемость", "placeholder": "заглушка", "infeasible": "неосуществимость",
    "incorrect": "некорректность", "duplicate": "дубль", "format": "оформление", "other": "прочее",
}

# Группы критичных дефектов для сводки (п. 6 ТЗ: непроверяемые, противоречивые, неполные).
CRITICAL_GROUPS = (
    ("unverifiable", "Непроверяемые", ("unverifiable",)),
    ("conflict", "Противоречивые", ("conflict",)),
    ("incomplete", "Неполные", ("incomplete", "omission", "placeholder")),
    ("other", "Прочие", ()),
)

# --------------------------------------------------------------------------- критерии
_C29148_IND = "ISO/IEC/IEEE 29148 5.2.5"
_C29148_SET = "ISO/IEC/IEEE 29148 5.2.6"

# код → (короткий код, название, пункты стандартов, вопрос к требованию)
CRITERIA: dict[str, tuple[str, str, str, str]] = {
    "necessary": ("И1", "Необходимость", _C29148_IND,
                  "Без требования возникнет пробел? Это не дубль другого пункта?"),
    "appropriate": ("И2", "Уместность", _C29148_IND,
                    "Требование говорит «что», а не «как»? Нет лишних решений реализации?"),
    "unambiguous": ("И3", "Однозначность", f"{_C29148_IND}; IEEE 830 4.3.2",
                    "Возможно только одно толкование? Термины, единицы и часовые пояса определены?"),
    "complete": ("И4", "Полнота", f"{_C29148_IND}; IEEE 830 4.3.3",
                 "Есть субъект, условие, действие, ограничения, ошибки и границы?"),
    "singular": ("И5", "Единичность", _C29148_IND,
                 "Одно обязательство, а не несколько в одном пункте?"),
    "feasible": ("И6", "Осуществимость", _C29148_IND,
                 "Реализуемо при описанной архитектуре и данных?"),
    "verifiable": ("И7", "Проверяемость", f"{_C29148_IND}; IEEE 830 4.3.6",
                   "Можно объективно доказать выполнение тестом, анализом или инспекцией?"),
    "correct": ("И8", "Корректность", f"{_C29148_IND}; IEEE 830 4.3.1",
                "Соответствует предметной области и не противоречит другим пунктам и критериям приёмки?"),
    "conforming": ("И9", "Соответствие шаблону", _C29148_IND,
                   "Есть ID, модальность «система должна…», единая терминология?"),
    "set_complete": ("Н1", "Полнота набора", f"{_C29148_SET}; IEEE 830 4.3.3",
                     "Описаны все функции, данные, ошибки и граничные случаи?"),
    "set_consistent": ("Н2", "Согласованность набора", f"{_C29148_SET}; IEEE 830 4.3.4",
                       "Нет ли пар требований, дающих разные исходы при одном входе?"),
    "set_feasible": ("Н3", "Осуществимость набора", _C29148_SET,
                     "Набор реализуем целиком в рамках ограничений проекта?"),
    "set_comprehensible": ("Н4", "Понятность набора", _C29148_SET,
                           "Ясно, что ожидается от системы и как требования связаны?"),
    "set_validatable": ("Н5", "Возможность валидации набора", _C29148_SET,
                        "Можно ли доказать, что набор решает задачу заказчика?"),
    "ranked": ("Н6", "Ранжирование по важности и стабильности", "IEEE 830 4.3.5",
               "Указаны приоритет и стабильность требований?"),
    "modifiable": ("Н7", "Модифицируемость", "IEEE 830 4.3.7",
                   "Структура позволяет менять требования без дублей и каскадных правок?"),
    "traceable": ("Н8", "Прослеживаемость", "IEEE 830 4.3.8",
                  "У каждого требования есть источник и связь с критериями приёмки?"),
}


# Порядок критериев в методике и матрице — как в контракте.
INDIVIDUAL_ORDER: tuple[str, ...] = tuple(INDIVIDUAL_CRITERIA)
SET_ORDER: tuple[str, ...] = tuple(SET_CRITERIA)


def criterion_code(code: str) -> str:
    """Короткий код критерия (``И3``, ``Н2``) или исходный код, если критерий вне контракта."""
    return CRITERIA[code][0] if code in CRITERIA else code


def criterion_name(code: str) -> str:
    return CRITERIA[code][1] if code in CRITERIA else code


def criterion_clause(code: str) -> str:
    return CRITERIA[code][2] if code in CRITERIA else ""


def criterion_label(code: str) -> str:
    """«Однозначность (ISO/IEC/IEEE 29148 5.2.5; IEEE 830 4.3.2)»."""
    if code not in CRITERIA:
        return f"{code} (критерий вне контракта v1)" if code else "критерий не указан"
    _, name, clause, _ = CRITERIA[code]
    return f"{name} ({clause})"


def label(mapping: Mapping[str, str], value: Any) -> str:
    """Подпись значения перечисления; неизвестное значение показывается как есть."""
    if value is None:
        return "не указано"
    return mapping.get(value, str(value))


def severity_label(value: Any) -> str:
    return label(SEVERITY_LABELS, value)


def kind_label(value: Any) -> str:
    return label(FINDING_KIND_LABELS, value)


# --------------------------------------------------------------------------- индексы
def block_index(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {b["id"]: b for b in (report.get("document") or {}).get("blocks", []) if "id" in b}


def finding_index(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in report.get("findings", []) if "id" in f}


def requirement_index(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in report.get("requirements", []) if "id" in r}


def sorted_findings(findings: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Сначала критичные, внутри серьёзности — в порядке отчёта."""
    ranked = sorted(enumerate(findings),
                    key=lambda p: (SEVERITY_ORDER.get(p[1].get("severity"), len(SEVERITY_ORDER)), p[0]))
    return [f for _, f in ranked]


def finding_evidence(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Опоры замечания вместе с опорами witness, без повторов."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    witness = finding.get("witness") or {}
    for ev in list(finding.get("evidence") or []) + [witness.get("evidence_a"), witness.get("evidence_b")]:
        if not ev:
            continue
        key = (ev.get("block_id"), ev.get("start"), ev.get("end"))
        if key not in seen:
            seen.add(key)
            out.append(ev)
    return out


def critical_ids(report: Mapping[str, Any]) -> list[str]:
    """Критичные замечания в порядке ``summary.critical_ids`` (как их посчитал движок)."""
    summary = report.get("summary") or {}
    if "critical_ids" in summary:
        return list(summary["critical_ids"])
    return [f["id"] for f in report.get("findings", []) if f.get("severity") == "critical"]


def critical_group(finding: Mapping[str, Any]) -> str:
    kind = finding.get("kind")
    for key, _, kinds in CRITICAL_GROUPS:
        if kind in kinds:
            return key
    return "other"


# --------------------------------------------------------------------------- места в документе
def _line_at(loc: Mapping[str, Any], offset: int) -> Optional[int]:
    """Строка исходника для позиции в ``block.text`` по ``loc.map = [[text_start, line, col], ...]``."""
    best = None
    for entry in loc.get("map") or []:
        if len(entry) >= 2 and entry[0] <= offset and (best is None or entry[0] >= best[0]):
            best = entry
    return best[1] if best is not None else None


def _lines_text(first: Optional[int], last: Optional[int]) -> Optional[str]:
    if first is None:
        return None
    if last is None or last == first:
        return f"строка {first}"
    lo, hi = min(first, last), max(first, last)
    return f"строки {lo}–{hi}"


def _line_location(loc: Mapping[str, Any], evidence: Optional[Mapping[str, Any]]) -> Optional[str]:
    if evidence is not None and loc.get("map"):
        start = int(evidence.get("start", 0))
        end = int(evidence.get("end", start))
        first = _line_at(loc, start)
        last = _line_at(loc, max(start, end - 1))
        if first is not None:
            return _lines_text(first, last)
    return _lines_text(loc.get("line_start"), loc.get("line_end"))


def describe_location(report: Mapping[str, Any], ref: Any, *,
                      index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> str:
    """Место опоры или блока в исходном документе: «строка 37», «строки 162–163», «с. 2», путь DOCX.

    ``ref`` — id блока или опора ``{block_id, start, end, quote}``.
    """
    evidence = ref if isinstance(ref, Mapping) else None
    block_id = evidence.get("block_id") if evidence is not None else ref
    blocks = index if index is not None else block_index(report)
    block = blocks.get(block_id) if block_id is not None else None
    if block is None:
        return f"блок {block_id} (нет в документе)" if block_id else "место не указано"
    loc = block.get("loc") or {}
    fmt = (report.get("document") or {}).get("format")

    page = f"с. {loc['page']}" if loc.get("page") else None
    path = str(loc["path"]) if loc.get("path") else None
    lines = _line_location(loc, evidence)
    if fmt == "pdf":
        order = (page, lines, path)
    elif fmt == "docx":
        order = (path, page, lines)
    else:
        order = (lines, page, path)
    for text in order:
        if text:
            return text
    return f"блок {block_id}"


def section_path(report: Mapping[str, Any], block_id: Optional[str], *,
                 index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> str:
    """Раздел блока: «Часть A › Функциональные требования» (пусто, если раздела нет)."""
    blocks = index if index is not None else block_index(report)
    block = blocks.get(block_id) if block_id else None
    if not block:
        return ""
    return " › ".join(s for s in block.get("section") or [] if s)


def describe_place(report: Mapping[str, Any], ref: Any, *,
                   index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> str:
    """Место с разделом и id блока: «строка 4, раздел «Функциональные требования», блок b0003»."""
    blocks = index if index is not None else block_index(report)
    block_id = ref.get("block_id") if isinstance(ref, Mapping) else ref
    parts = [describe_location(report, ref, index=blocks)]
    section = section_path(report, block_id, index=blocks)
    if section:
        parts.append(f"раздел «{section}»")
    if block_id and block_id in blocks:
        parts.append(f"блок {block_id}")
    return ", ".join(parts)


def requirement_locations(report: Mapping[str, Any], requirement: Mapping[str, Any], *,
                          index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> list[str]:
    """Места требования (по опорам, иначе по блокам) без повторов."""
    blocks = index if index is not None else block_index(report)
    refs: list[Any] = list(requirement.get("evidence") or []) or list(requirement.get("block_ids") or [])
    return unique(describe_location(report, r, index=blocks) for r in refs)


def hint_location(report: Mapping[str, Any], hint: Mapping[str, Any], *,
                  index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> str:
    """Место подсказки модели: координаты не сверены, поэтому — место блока целиком."""
    block_id = hint.get("block_id")
    if not block_id:
        return "блок не указан"
    return describe_place(report, block_id, index=index)


# --------------------------------------------------------------------------- текст
def unique(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


# «<» перед латинской буквой, «/», «!» или «?» Markdown-просмотрщик примет за HTML-тег и спрячет
# (например, «<amount>» из описания API); «<= 100» и «<ФИО>» остаются как есть.
_HTML_TAG_START = re.compile(r"<(?=[A-Za-z/!?])")


def _md_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return _HTML_TAG_START.sub("&lt;", text.replace("\r\n", "\n").replace("\r", "\n"))


def md_cell(value: Any) -> str:
    """Текст для ячейки Markdown-таблицы: ``|`` экранируется, переводы строк → ``<br>``."""
    return _md_text(value).replace("|", "\\|").replace("\n", "<br>").strip()


def md_inline(value: Any) -> str:
    """Текст внутри строки списка Markdown: переводы строк → ``<br>``, чтобы не ломать список."""
    return _md_text(value).replace("\n", "<br>").strip()


def short_text(value: Any, limit: int = 160) -> str:
    """Укоротить по границе слова с «…»; переводы строк заменяются пробелом."""
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def anchor_slug(value: Any) -> str:
    """Безопасный фрагмент якоря: буквы, цифры, ``-`` и ``_`` остаются как есть."""
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "-", str(value)).strip("-") or "x"


def finding_anchor(finding_id: Any) -> str:
    return f"finding-{anchor_slug(finding_id)}"


def block_anchor(block_id: Any) -> str:
    return f"block-{anchor_slug(block_id)}"


def format_datetime(value: Any) -> str:
    """ISO 8601 → «2026-11-26 00:00:00 UTC»; нераспознанное значение возвращается как есть."""
    if not value:
        return "не указано"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    offset = dt.utcoffset()
    zone = "UTC" if offset is not None and offset.total_seconds() == 0 else dt.strftime("UTC%z")
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {zone}"


def format_seconds(value: Any) -> str:
    if value is None:
        return "не указано"
    seconds = float(value)
    if seconds < 60:
        return f"{seconds:.1f} с"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)} мин {rest:.0f} с"


def yes_no(value: Any) -> str:
    return "да" if value else "нет"


def warning_text(warning: Any) -> str:
    """Предупреждение контракта (строка или ``{code, message, stage, block_ids}``) одной строкой без мест."""
    if isinstance(warning, Mapping):
        code = warning.get("code")
        message = warning.get("message") or ""
        stage = warning.get("stage")
        head = f"[{code}] " if code else ""
        tail = f" (этап {stage})" if stage else ""
        return f"{head}{message}{tail}"
    return str(warning)


def incomplete_note(report: Mapping[str, Any]) -> str:
    """Почему результат может быть неполным: статус прогона, причины, незавершённые этапы."""
    run = report.get("run") or {}
    parts = [f"прогон {label(RUN_STATUS_LABELS, run.get('status'))}"]
    reasons = [r for r in run.get("status_reasons") or [] if r]
    if reasons:
        parts.append("причины: " + "; ".join(reasons))
    stages = [s for s in run.get("incomplete_stages") or [] if s]
    if stages:
        parts.append("незавершённые этапы: " + ", ".join(stages))
    return "; ".join(parts)


def run_complete(report: Mapping[str, Any]) -> bool:
    return (report.get("run") or {}).get("status") == "complete"
