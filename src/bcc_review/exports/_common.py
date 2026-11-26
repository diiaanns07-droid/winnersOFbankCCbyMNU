"""Общие помощники экспортёров Markdown и Jira CSV.

Модуль читает канонический Report (контракт v1) и ничего в нём не меняет.
Экспортёры получают объект Report от движка (pydantic-модель, dataclass,
словарь или путь к report.json) и приводят его к обычному словарю JSON.
Все числа, статусы и вердикты дальше считаются только из этого словаря.

Имена полей и перечисления — из bcc_review.contracts (контракт v1). Если
необязательного поля нет, экспорт пишет «нет данных», а не придумывает значение.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

NBSP = " "

# --------------------------------------------------------------------------
# Приведение Report к словарю
# --------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return str(obj)


def as_report_dict(report: Any) -> dict[str, Any]:
    """Вернуть глубокую копию Report в виде словаря JSON.

    Принимает pydantic-модель, dataclass, Mapping, объект с ``to_dict()``
    или путь к report.json.
    """
    if isinstance(report, (str, Path)):
        return json.loads(Path(report).read_text(encoding="utf-8"))
    if hasattr(report, "model_dump"):
        data = report.model_dump(mode="json")
    elif dataclasses.is_dataclass(report) and not isinstance(report, type):
        data = dataclasses.asdict(report)
    elif isinstance(report, Mapping):
        data = report
    elif hasattr(report, "to_dict"):
        data = report.to_dict()
    else:
        raise TypeError(f"Неподдерживаемый тип Report: {type(report).__name__}")
    return json.loads(json.dumps(data, ensure_ascii=False, default=_json_default))


def first(mapping: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Первое непустое значение по списку возможных имён поля."""
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return default


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


# --------------------------------------------------------------------------
# Русская грамматика чисел и форматирование
# --------------------------------------------------------------------------

# Формы: (1, 2–4, 5+). Для конструкции «из N» — формы родительного падежа.
REQ = ("требование", "требования", "требований")
REQ_GEN = ("требования", "требований", "требований")
FINDING = ("замечание", "замечания", "замечаний")
FINDING_GEN = ("замечания", "замечаний", "замечаний")
DEFECT = ("дефект", "дефекта", "дефектов")
DEFECT_GEN = ("дефекта", "дефектов", "дефектов")
QUOTE = ("цитата", "цитаты", "цитат")
QUOTE_GEN = ("цитаты", "цитат", "цитат")
CALL = ("вызов", "вызова", "вызовов")
TOKEN = ("токен", "токена", "токенов")
RECORD = ("запись", "записи", "записей")
RECORD_GEN = ("записи", "записей", "записей")
CRITERION = ("критерий", "критерия", "критериев")
CRITERION_GEN = ("критерия", "критериев", "критериев")
REPEAT = ("повтор", "повтора", "повторов")
OPORA = ("опора", "опоры", "опор")
OPORA_GEN = ("опоры", "опор", "опор")


def plural(n: int | float, forms: tuple[str, str, str]) -> str:
    """Форма слова для числа n по правилам русского языка.

    Дробные числа согласуются с формой родительного падежа единственного
    числа: «1,5 требования».
    """
    if isinstance(n, float) and not n.is_integer():
        return forms[1]
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def fmt_int(n: int | None) -> str:
    """Целое с неразрывными пробелами между разрядами для чисел от 1 000 (как в документах банка)."""
    if n is None:
        return "—"
    n = int(n)
    s = str(abs(n))
    if len(s) > 3:
        groups = []
        while s:
            groups.append(s[-3:])
            s = s[:-3]
        s = NBSP.join(reversed(groups))
    return ("−" if n < 0 else "") + s


def count(n: int, forms: tuple[str, str, str]) -> str:
    """«1 требование», «3 требования», «11 требований»."""
    return f"{fmt_int(n)} {plural(n, forms)}"


def of_count(k: int, n: int, gen_forms: tuple[str, str, str]) -> str:
    """«4 из 21 требования», «4 из 6 требований» — знаменатель всегда виден."""
    return f"{fmt_int(k)} из {fmt_int(n)} {plural(n, gen_forms)}"


def _round1(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fmt_pct(k: int, n: int) -> str:
    """Доля в процентах с десятичной запятой; при n == 0 — прочерк."""
    if not n:
        return "—"
    value = _round1(100.0 * k / n)
    if value == value.to_integral_value():
        text = str(int(value))
    else:
        text = str(value).replace(".", ",")
    return f"{text}{NBSP}%"


def fmt_ratio(k: int, n: int, gen_forms: tuple[str, str, str]) -> str:
    """«4 из 6 требований (66,7 %)»."""
    return f"{of_count(k, n, gen_forms)} ({fmt_pct(k, n)})"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "нет данных"
    seconds = float(seconds)
    if seconds < 60:
        value = _round1(seconds)
        text = str(int(value)) if value == value.to_integral_value() else str(value).replace(".", ",")
        return f"{text}{NBSP}с"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours}{NBSP}ч")
    if minutes or hours:
        parts.append(f"{minutes}{NBSP}мин")
    if secs and not hours:
        parts.append(f"{secs}{NBSP}с")
    return " ".join(parts)


def parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_datetime(value: Any) -> str:
    dt = parse_time(value)
    if dt is None:
        return str(value) if value else "нет данных"
    text = dt.strftime("%d.%m.%Y %H:%M:%S")
    if dt.utcoffset() is not None:
        offset = dt.strftime("%z")
        text += " UTC" + (offset[:3] + ":" + offset[3:] if offset not in ("+0000", "-0000") else "")
    return text


# --------------------------------------------------------------------------
# Справочники подписей (коды — из bcc_review.contracts, контракт v1)
# --------------------------------------------------------------------------

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
SEVERITY_LABEL = {  # согласовано со словом «замечание» (ср. р.)
    "critical": "критичное",
    "major": "существенное",
    "minor": "незначительное",
}
SEVERITY_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡"}

STATUS_LABEL = {
    "confirmed": "подтверждено",
    "needs_review": "требует проверки человеком",
}
ANCHOR_LABEL = {"supported": "цитата найдена в документе", "incomplete": "опора неполная"}
MEANING_LABEL = {
    "confirmed": "смысл подтверждён",
    "uncertain": "смысл под вопросом",
    "unchecked": "смысл не проверялся",
    "deterministic": "найдено правилом",
}
BLOCKS_LABEL = {"development": "разработку", "testing": "тестирование"}
REVIEW_STATE = {"reviewed": "full", "partial": "partial", "not_reviewed": "none"}
CHECK_MARK = {"yes": "Да", "no": "Нет", "na": "Не требуется", "unknown": "Не определено"}
COVERAGE_LABEL = {
    "covered": "✔ покрыто",
    "partial": "◐ частично",
    "conflict": "✖ противоречит",
    "uncovered": "✖ не покрыто",
    "unknown": "⏸ не определено",
}

# Коды критериев ISO/IEC/IEEE 29148:2018 (5.2.5, 5.2.6) и IEEE 830-1998 (4.3).
CRITERIA = {
    "necessary": ("Необходимость", "29148 5.2.5"),
    "appropriate": ("Уместность (без лишних проектных решений)", "29148 5.2.5"),
    "unambiguous": ("Однозначность", "29148 5.2.5; 830 4.3.2"),
    "complete": ("Полнота формулировки", "29148 5.2.5; 830 4.3.3"),
    "singular": ("Единичность", "29148 5.2.5"),
    "feasible": ("Осуществимость", "29148 5.2.5"),
    "verifiable": ("Проверяемость", "29148 5.2.5; 830 4.3.6"),
    "correct": ("Корректность", "29148 5.2.5; 830 4.3.1"),
    "conforming": ("Соответствие шаблону и терминологии", "29148 5.2.5"),
    "set_complete": ("Полнота набора", "29148 5.2.6; 830 4.3.3"),
    "set_consistent": ("Согласованность набора", "29148 5.2.6; 830 4.3.4"),
    "set_feasible": ("Осуществимость набора", "29148 5.2.6"),
    "set_comprehensible": ("Понятность набора", "29148 5.2.6"),
    "set_validatable": ("Возможность валидации набора", "29148 5.2.6"),
    "ranked": ("Ранжирование по важности и стабильности", "830 4.3.5"),
    "modifiable": ("Модифицируемость", "830 4.3.7"),
    "traceable": ("Прослеживаемость", "830 4.3.8"),
}
INDIVIDUAL_CODES = tuple(list(CRITERIA)[:9])
SET_CODES = tuple(list(CRITERIA)[9:])

KIND_LABEL = {
    "ambiguity": "Двусмысленность",
    "unverifiable": "Непроверяемость",
    "incomplete": "Неполнота",
    "conflict": "Противоречие",
    "omission": "Пропуск",
    "non_singular": "Неатомарность",
    "design_in_requirement": "Проектное решение в требовании",
    "terminology": "Несогласованная терминология",
    "traceability": "Нарушение прослеживаемости",
    "placeholder": "Незаполненный шаблон",
    "infeasible": "Нереализуемость",
    "incorrect": "Некорректность",
    "duplicate": "Дублирование",
    "format": "Оформление",
    "other": "Прочее",
}

FORMAT_LABEL = {"markdown": "Markdown", "md": "Markdown", "text": "TXT", "pdf": "PDF", "docx": "DOCX", "html": "HTML"}
MODE_LABEL = {
    "rules_plus_llm": "правила + LLM",
    "rules_only": "только правила (без LLM)",
    "mock": "подставной транспорт (mock), без реальной модели",
}
RUN_STATUS_LABEL = {
    "complete": "завершён полностью",
    "partial": "завершён частично",
    "failed": "завершился ошибкой",
}
STAGE_STATUS_LABEL = {
    "ok": "выполнен",
    "cached": "из кэша",
    "partial": "частично",
    "failed": "ошибка",
    "skipped": "пропущен",
}
PARTIAL_READ_CODES = ("partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input")
SET_STAGE_NAMES = ("cross", "set", "review_set")


def criterion_name(code: Any) -> str:
    if not code:
        return "критерий не указан"
    entry = CRITERIA.get(str(code).lower())
    return entry[0] if entry else str(code)


def criterion_ref(code: Any) -> str:
    entry = CRITERIA.get(str(code).lower()) if code else None
    return entry[1] if entry else ""


def kind_name(kind: Any) -> str:
    if not kind:
        return "Замечание"
    return KIND_LABEL.get(str(kind).lower(), str(kind))


def critical_category(finding: Mapping[str, Any]) -> str:
    """Категория п. 6 ТЗ: contradictory | unverifiable | incomplete | other."""
    kind = str(finding.get("kind") or "").lower()
    crit = str(finding.get("criterion") or "").lower()
    if kind == "conflict" or crit == "set_consistent":
        return "contradictory"
    if kind == "unverifiable" or crit == "verifiable":
        return "unverifiable"
    if kind in {"incomplete", "omission"} or crit in {"complete", "set_complete"}:
        return "incomplete"
    return "other"


def warning_text(w: Any) -> str:
    if isinstance(w, Mapping):
        code = w.get("code")
        msg = first(w, "message", "text", default="")
        return f"{code}: {msg}" if code else str(msg)
    return str(w)


# --------------------------------------------------------------------------
# Документ, места и цитаты
# --------------------------------------------------------------------------


class DocIndex:
    """Индекс блоков документа: место, раздел и сверка цитат."""

    def __init__(self, report: Mapping[str, Any]):
        document = report.get("document") or {}
        self.blocks: dict[str, dict[str, Any]] = {}
        for block in as_list(document.get("blocks")):
            if isinstance(block, Mapping) and block.get("id") is not None:
                self.blocks[str(block["id"])] = dict(block)
        self.format = str(document.get("format") or "").lower()
        self.title = str(document.get("title") or "")

    def block(self, block_id: Any) -> dict[str, Any] | None:
        return self.blocks.get(str(block_id)) if block_id is not None else None

    def section(self, block_id: Any) -> str:
        """Путь разделов без заголовка-названия документа (он и так в шапке отчёта)."""
        block = self.block(block_id)
        if not block:
            return ""
        section = [str(s) for s in as_list(block.get("section")) if s]
        if section and section[0] == self.title:
            section = section[1:]
        return " › ".join(section)

    def _line_at(self, block: Mapping[str, Any], offset: int) -> int | None:
        loc = block.get("loc") or {}
        if not isinstance(loc, Mapping):
            return loc if isinstance(loc, int) else None
        text = block.get("text") or ""
        offset = max(0, min(int(offset), len(text)))
        mapping = [m for m in as_list(loc.get("map")) if isinstance(m, Sequence) and len(m) >= 2]
        if mapping:
            # Символы с позиции text_start идут подряд со строки line исходника.
            best = None
            for entry in mapping:
                if int(entry[0]) <= offset and (best is None or int(entry[0]) >= int(best[0])):
                    best = entry
            if best is not None:
                return int(best[1]) + text[int(best[0]) : offset].count("\n")
        start = loc.get("line_start", loc.get("line"))
        end = loc.get("line_end", start)
        if not isinstance(start, int):
            return None
        if isinstance(end, int) and end > start and text.count("\n") == end - start:
            return start + text[:offset].count("\n")
        return start

    def line_span(self, block_id: Any, start: int | None = None, end: int | None = None) -> tuple[int, int] | None:
        """Строки исходника (с 1) для блока или для отрезка [start, end) в нём."""
        block = self.block(block_id)
        if not block:
            return None
        loc = block.get("loc") or {}
        if start is None:
            if isinstance(loc, Mapping) and isinstance(loc.get("line_start", loc.get("line")), int):
                a = loc.get("line_start", loc.get("line"))
                b = loc.get("line_end", a)
                return a, b if isinstance(b, int) else a
            return None
        a = self._line_at(block, start)
        if a is None:
            return None
        last = max(int(start), int(end if end is not None else start) - 1)
        b = self._line_at(block, last) or a
        return a, max(a, b)

    def place(self, block_id: Any, start: int | None = None, end: int | None = None, *, with_section: bool = True) -> str:
        """Место: «раздел, строка N» / «раздел, страница N» / «раздел, DOCX путь»."""
        block = self.block(block_id)
        if not block:
            return f"блок {block_id} (нет в документе)"
        loc = block.get("loc") or {}
        loc = loc if isinstance(loc, Mapping) else {}
        span = self.line_span(block_id, start, end)
        if "page" in loc:
            where = f"страница {loc['page']}"
        elif "path" in loc:
            where = f"DOCX {loc.get('part', '')}:{loc['path']}".replace(" :", " ")
        elif span:
            a, b = span
            where = f"строка {a}" if a == b else f"строки {a}–{b}"
        else:
            where = f"блок {block_id}"
        section = self.section(block_id) if with_section else ""
        return f"{section}, {where}" if section else where

    def short_place(self, block_id: Any, start: int | None = None, end: int | None = None) -> str:
        return self.place(block_id, start, end, with_section=False)

    def check_evidence(self, ev: Mapping[str, Any]) -> str:
        """Сверка опоры: ok | mismatch | missing_block | no_offsets."""
        block = self.block(ev.get("block_id"))
        if block is None:
            return "missing_block"
        start, end, quote = ev.get("start"), ev.get("end"), ev.get("quote")
        if not isinstance(start, int) or not isinstance(end, int):
            return "no_offsets"
        text = block.get("text") or ""
        return "ok" if text[start:end] == quote else "mismatch"


# --------------------------------------------------------------------------
# Требования и проверки
# --------------------------------------------------------------------------


def requirement_index(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("id")): r for r in as_list(report.get("requirements")) if isinstance(r, Mapping)}


CHECK_BUCKET = {
    "pass": "passed",
    "issue": "failed",
    "unknown": "skipped",
    "na": "na",
    # совместимость с черновыми значениями
    "fail": "failed",
    "ok": "passed",
    "not_checked": "skipped",
}


def requirement_states(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Охват проверки каждого требования.

    state берётся из ``Requirement.review_status`` (reviewed → full, partial →
    partial, not_reviewed → none). Если поля нет — выводится из checks.
    Списки критериев — из ``checks``: pass → passed, issue → failed,
    unknown → skipped, na → na.
    """
    states: dict[str, dict[str, Any]] = {}
    reqs = requirement_index(report)
    for rid in reqs:
        states[rid] = {"passed": [], "failed": [], "skipped": [], "na": [], "reasons": {}, "checks": []}
    for check in as_list(report.get("checks")):
        if not isinstance(check, Mapping):
            continue
        rid = str(first(check, "req_id", "requirement_id", default=""))
        if rid not in states:
            continue
        status = str(first(check, "status", "result", default="unknown")).lower()
        bucket = CHECK_BUCKET.get(status, "skipped")
        code = str(check.get("criterion") or "—")
        st = states[rid]
        if code not in st[bucket]:
            st[bucket].append(code)
        st["checks"].append(check)
        if check.get("reason"):
            st["reasons"][code] = str(check["reason"])
    for rid, st in states.items():
        review = str(reqs[rid].get("review_status") or "").lower()
        if review in REVIEW_STATE:
            st["state"] = REVIEW_STATE[review]
        else:
            done = len(st["passed"]) + len(st["failed"]) + len(st["na"])
            st["state"] = "full" if done and not st["skipped"] else "partial" if done else "none"
        st["review_reason"] = reqs[rid].get("review_reason") or ""
    return states


# --------------------------------------------------------------------------
# Находки и первопричины
# --------------------------------------------------------------------------


def finding_status(finding: Mapping[str, Any]) -> str:
    return str(finding.get("status") or "confirmed").lower()


def findings_all(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [f for f in as_list(report.get("findings")) if isinstance(f, Mapping)]


def rejected_items(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Снятые кандидаты: ``Report.rejected = [{candidate, reason, stage}]``."""
    return [r for r in as_list(report.get("rejected")) if isinstance(r, Mapping)]


def severity_rank(finding: Mapping[str, Any]) -> int:
    return SEVERITY_ORDER.get(str(finding.get("severity", "")).lower(), 9)


def _norm(text: Any) -> str:
    text = " ".join(str(text or "").lower().replace("ё", "е").split())
    return text.strip(" .,;:!?«»\"'")


# Семейства видов дефекта — те же, что в runtime/merge.py движка: противоречие и
# неточность одного факта — одно семейство, пропуск и неполнота — другое и т. д.
KIND_FAMILY = {
    "conflict": "conflict", "incorrect": "conflict", "ambiguity": "ambiguity", "unverifiable": "verifiability",
    "incomplete": "gap", "omission": "gap", "placeholder": "gap", "terminology": "terminology",
    "traceability": "traceability", "non_singular": "structure", "duplicate": "structure",
    "design_in_requirement": "design", "infeasible": "feasibility", "format": "format", "other": "other",
}

LINK_LABEL = {
    "duplicate_of": "явная ссылка `duplicate_of`",
    "root_cause_id": "общий `root_cause_id`",
    "merged_from": "указан в `merged_from`",
    "cause": "совпали причина и исходы (`cause`)",
}


def cause_signature(finding: Mapping[str, Any]) -> tuple[str, str, str, frozenset[str]] | None:
    """Доказанная первопричина: семейство вида, объект, условие и непустой набор исходов.

    Без исходов (``cause.outcomes``) совпадение не доказано: одинаковые объект и
    условие бывают у разных проблем (месяц учёта и правило push при одной и той же
    проведённой покупке).
    """
    cause = finding.get("cause")
    if not isinstance(cause, Mapping):
        return None
    obj, cond = _norm(cause.get("object")), _norm(cause.get("condition"))
    outcomes = frozenset(o for o in (_norm(x) for x in as_list(cause.get("outcomes"))) if o)
    if not obj or not cond or not outcomes:
        return None
    kind = str(finding.get("kind") or "").lower()
    return KIND_FAMILY.get(kind, kind), obj, cond, outcomes


def root_cause_links(findings: list[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """Связи «одна первопричина» между находками: (id, id, основание).

    Основания — только явные связи или доказанное совпадение:
    ``duplicate_of`` (ссылка на другую находку), общий ``root_cause_id``,
    ID другой находки в ``merged_from`` и совпадение :func:`cause_signature`.
    Совпадение одних ``cause.object`` и ``cause.condition`` связью не является.
    """
    ids = [str(f.get("id")) for f in findings]
    known = set(ids)
    links: list[tuple[str, str, str]] = []
    for f in findings:
        fid = str(f.get("id"))
        target = f.get("duplicate_of")
        if target is not None and str(target) in known and str(target) != fid:
            links.append((fid, str(target), "duplicate_of"))
        for other in as_list(f.get("merged_from")):
            if str(other) in known and str(other) != fid:
                links.append((fid, str(other), "merged_from"))
    by_root: dict[str, list[str]] = {}
    by_cause: dict[tuple, list[str]] = {}
    for f in findings:
        fid = str(f.get("id"))
        if f.get("root_cause_id"):
            by_root.setdefault(str(f["root_cause_id"]), []).append(fid)
        sig = cause_signature(f)
        if sig is not None:
            by_cause.setdefault(sig, []).append(fid)
    for reason, buckets in (("root_cause_id", by_root), ("cause", by_cause)):
        for members in buckets.values():
            links.extend((members[0], other, reason) for other in members[1:])
    return links


def _natural_id(fid: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", fid))


def group_findings(findings: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Объединить находки одной первопричины по связям :func:`root_cause_links`.

    Состав групп не зависит от порядка находок в Report. Основная запись —
    подтверждённая; среди них та, что не ссылается на другую через
    ``duplicate_of``, затем самая серьёзная, затем меньший ID. Серьёзность группы —
    серьёзность основной записи. Для каждой неосновной записи сохраняется
    основание связи (``group["link_of"][id]``).
    """
    by_id = {str(f.get("id")): f for f in findings}
    parent = {fid: fid for fid in by_id}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links = root_cause_links(findings)
    for a, b, _ in links:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb, key=_natural_id)] = min(ra, rb, key=_natural_id)

    groups: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for f in findings:
        root = find(str(f.get("id")))
        if root not in groups:
            groups[root] = []
            order.append(root)
        groups[root].append(f)

    result = []
    for root in order:
        members = groups[root]
        member_ids = {str(m.get("id")) for m in members}

        def rank(m: Mapping[str, Any], ids: set[str] = member_ids) -> tuple:
            is_dup = str(m.get("duplicate_of")) in ids and str(m.get("duplicate_of")) != str(m.get("id"))
            return (0 if finding_status(m) == "confirmed" else 1, 1 if is_dup else 0, severity_rank(m),
                    _natural_id(str(m.get("id"))))

        primary = min(members, key=rank)
        link_of: dict[str, str] = {}
        for a, b, reason in links:
            if a in member_ids:
                for x in (a, b):
                    link_of.setdefault(x, reason)
        link_of.pop(str(primary.get("id")), None)
        result.append(
            {
                "key": "group:" + ",".join(sorted(member_ids, key=_natural_id)),
                "primary": primary,
                "members": members,
                "others": [m for m in members if m is not primary],
                "link_of": link_of,
                "severity": str(primary.get("severity", "")).lower(),
                "confirmed": any(finding_status(m) == "confirmed" for m in members),
            }
        )
    return result


def merged_candidates(finding: Mapping[str, Any]) -> list[str]:
    """Кандидаты, поглощённые находкой при подготовке отчёта.

    Движок пишет ``merged_from = [собственный cid, поглощённые…]``, поэтому
    первый элемент — сама находка, а не слияние.
    """
    items = [str(x) for x in as_list(finding.get("merged_from"))]
    return items[1:]


def confirmed_groups(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Уникальные подтверждённые дефекты: первопричины подтверждённых находок."""
    return group_findings([f for f in findings_all(report) if finding_status(f) == "confirmed"])


def evidence_of(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [e for e in as_list(finding.get("evidence")) if isinstance(e, Mapping)]


# --------------------------------------------------------------------------
# Вердикт и прогон
# --------------------------------------------------------------------------


def verdict_status(value: Any) -> str:
    """Статус готовности: ready | not_ready | unknown (контракт v1)."""
    if isinstance(value, Mapping):
        value = first(value, "status", "decision", "ready")
    if isinstance(value, bool):
        return "ready" if value else "not_ready"
    text = str(value or "").lower()
    if text in {"ready", "not_ready", "unknown"}:
        return text
    return "unknown"


def verdict_part(report: Mapping[str, Any], part: str) -> dict[str, Any]:
    verdict = report.get("verdict") or {}
    raw = verdict.get(part) if isinstance(verdict, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {"status": raw}
    reasons = [str(r) for r in as_list(first(raw, "reasons", "reason")) if r]
    return {
        "status": verdict_status(raw),
        "reasons": reasons,
        "finding_ids": [str(x) for x in as_list(first(raw, "finding_ids", "blockers"))],
    }


def first_actions(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    verdict = report.get("verdict") or {}
    items = []
    for i, item in enumerate(as_list(verdict.get("first_actions") if isinstance(verdict, Mapping) else None)):
        if isinstance(item, Mapping):
            items.append(
                {
                    "order": item.get("order") if isinstance(item.get("order"), int) else 10**6 + i,
                    "text": str(first(item, "action", "text", default="")),
                    "finding_ids": [str(x) for x in as_list(item.get("finding_ids"))],
                }
            )
        elif item:
            items.append({"order": 10**6 + i, "text": str(item), "finding_ids": []})
    return sorted(items, key=lambda a: a["order"])


def run_info(report: Mapping[str, Any]) -> dict[str, Any]:
    run = report.get("run") or {}
    calls = run.get("calls") if isinstance(run.get("calls"), Mapping) else {}
    tokens = run.get("tokens") if isinstance(run.get("tokens"), Mapping) else {}
    started, finished = parse_time(run.get("started_at")), parse_time(run.get("finished_at"))
    duration = run.get("duration_s")
    if duration is None and started and finished:
        duration = (finished - started).total_seconds()
    stages = [s for s in as_list(run.get("stages")) if isinstance(s, Mapping)]
    return {
        "run_id": run.get("run_id"),
        "status": str(run.get("status") or "unknown").lower(),
        "status_reasons": [str(r) for r in as_list(run.get("status_reasons"))],
        "incomplete_stages": [str(r) for r in as_list(run.get("incomplete_stages"))],
        "mode": str(run.get("mode") or "").lower(),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "requested_model": run.get("requested_model"),
        "models_seen": [str(m) for m in as_list(run.get("models_seen"))],
        "agent_version": run.get("agent_version"),
        "agent_commit": run.get("agent_commit"),
        "source_sha256": run.get("source_sha256"),
        "source_name": run.get("source_name"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "duration_s": duration,
        "calls_physical": calls.get("physical") if calls else first(run, "physical_calls"),
        "calls_cache_hits": calls.get("cache_hits"),
        "calls_failed": calls.get("failed"),
        "calls_retries": calls.get("retries"),
        "tokens_in": tokens.get("input"),
        "tokens_out": tokens.get("output"),
        "tokens_cache_read": tokens.get("cache_read"),
        "budget": run.get("budget") if isinstance(run.get("budget"), Mapping) else None,
        "stages": stages,
        "modules": run.get("modules") if isinstance(run.get("modules"), Mapping) else {},
        "context_policy": run.get("context_policy"),
        "evidence_audit": run.get("evidence_audit") if isinstance(run.get("evidence_audit"), Mapping) else None,
    }


def provider_state(info: Mapping[str, Any]) -> str:
    """Статус поставщика по фактическим вызовам и этапам прогона."""
    if info.get("provider") in (None, "none") or info.get("mode") == "rules_only":
        return "модель не вызывалась (только правила)"
    # Только этапы, которые обращались к модели: сбой правил или чтения — не статус поставщика.
    bad = [
        s for s in info["stages"]
        if str(s.get("status")) in {"failed", "partial"} and isinstance(s.get("calls"), int) and s["calls"] > 0
    ]
    parts = []
    failed = info.get("calls_failed") or 0
    retries = info.get("calls_retries") or 0
    if not bad and not failed:
        parts.append("ответы получены")
    else:
        parts.append(f"неуспешных вызовов — {fmt_int(failed)}")
        for s in bad:
            reason = f": {s['reason']}" if s.get("reason") else ""
            parts.append(f"этап {s.get('name')} — {STAGE_STATUS_LABEL.get(str(s.get('status')), s.get('status'))}{reason}")
    if retries:
        parts.append(f"повторов — {fmt_int(retries)}")
    budget = info.get("budget") or {}
    if budget.get("exhausted"):
        parts.append(f"бюджет исчерпан{': ' + str(budget['reason']) if budget.get('reason') else ''}")
    return "; ".join(parts)


def partial_read_warnings(report: Mapping[str, Any]) -> list[str]:
    doc = report.get("document") or {}
    out = []
    for w in as_list(doc.get("warnings")):
        if isinstance(w, Mapping) and str(w.get("code")) in PARTIAL_READ_CODES:
            out.append(warning_text(w))
    return out


# --------------------------------------------------------------------------
# Сводные числа и сверка с Report.summary
# --------------------------------------------------------------------------


def summary_numbers(report: Mapping[str, Any]) -> dict[str, Any]:
    """Сводные числа отчёта. Единственный источник чисел для Markdown и Jira.

    Значения, которые есть в ``Report.summary``, берутся оттуда; остальные
    (частично проверенные требования, первопричины, сверка цитат) считаются
    из списков того же Report. Расхождения summary со списками возвращает
    :func:`summary_mismatches`.
    """
    reqs = requirement_index(report)
    states = requirement_states(report)
    findings = findings_all(report)
    confirmed = [f for f in findings if finding_status(f) == "confirmed"]
    groups = confirmed_groups(report)
    index = DocIndex(report)
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    by_sev_json = summary.get("by_severity") if isinstance(summary.get("by_severity"), Mapping) else {}
    by_status_json = summary.get("by_status") if isinstance(summary.get("by_status"), Mapping) else {}
    checks_json = summary.get("checks") if isinstance(summary.get("checks"), Mapping) else {}

    touched = {str(r) for f in confirmed for r in as_list(f.get("req_ids"))}
    full = [r for r in reqs if states[r]["state"] == "full"]

    ev_total = ev_ok = ev_bad = 0
    for f in findings:
        for ev in evidence_of(f):
            ev_total += 1
            verdict = index.check_evidence(ev)
            if verdict == "ok":
                ev_ok += 1
            elif verdict in {"mismatch", "missing_block"}:
                ev_bad += 1

    def from_json(value: Any, fallback: int) -> int:
        return int(value) if isinstance(value, int) else fallback

    sev_count = {s: sum(1 for f in findings if str(f.get("severity")) == s) for s in SEVERITY_ORDER}
    grp_sev = {s: sum(1 for g in groups if g["severity"] == s) for s in SEVERITY_ORDER}
    check_count = {s: 0 for s in ("pass", "issue", "unknown", "na")}
    for c in as_list(report.get("checks")):
        if isinstance(c, Mapping) and str(c.get("status")) in check_count:
            check_count[str(c.get("status"))] += 1
    info = run_info(report)
    return {
        "run_status": info["status"],
        "requirements_total": from_json(summary.get("requirements"), len(reqs)),
        "requirements_with_source_id": sum(1 for r in reqs.values() if r.get("source_id")),
        "requirements_agent_ids": sum(1 for r in reqs.values() if not r.get("source_id")),
        "requirements_reviewed": from_json(summary.get("reviewed_requirements"), len(full)),
        "requirements_partial": sum(1 for r in reqs if states[r]["state"] == "partial"),
        "requirements_not_reviewed": sum(1 for r in reqs if states[r]["state"] == "none"),
        "requirements_clean": sum(1 for r in full if r not in touched),
        "findings_total": from_json(summary.get("findings"), len(findings)),
        "findings_confirmed": from_json(by_status_json.get("confirmed"), len(confirmed)),
        "findings_needs_review": from_json(
            by_status_json.get("needs_review"), sum(1 for f in findings if finding_status(f) == "needs_review")
        ),
        "findings_critical": from_json(by_sev_json.get("critical"), sev_count["critical"]),
        "findings_major": from_json(by_sev_json.get("major"), sev_count["major"]),
        "findings_minor": from_json(by_sev_json.get("minor"), sev_count["minor"]),
        "merged_candidates": sum(len(merged_candidates(f)) for f in findings),
        "defects_unique": len(groups),
        "defects_critical": grp_sev["critical"],
        "defects_major": grp_sev["major"],
        "defects_minor": grp_sev["minor"],
        "same_cause_merged": len(confirmed) - len(groups),
        "rejected": len(rejected_items(report)),
        "evidence_total": ev_total,
        "evidence_verified": ev_ok,
        "evidence_failed": ev_bad,
        "checks_pass": from_json(checks_json.get("pass"), check_count["pass"]),
        "checks_issue": from_json(checks_json.get("issue"), check_count["issue"]),
        "checks_unknown": from_json(checks_json.get("unknown"), check_count["unknown"]),
        "checks_na": from_json(checks_json.get("na"), check_count["na"]),
        "verdict_development": verdict_part(report, "development")["status"],
        "verdict_testing": verdict_part(report, "testing")["status"],
    }


def summary_mismatches(report: Mapping[str, Any]) -> list[str]:
    """Где ``Report.summary`` расходится с перечнями того же Report."""
    summary = report.get("summary")
    if not isinstance(summary, Mapping) or not summary:
        return []
    reqs = requirement_index(report)
    states = requirement_states(report)
    findings = findings_all(report)
    out: list[str] = []

    def cmp(name: str, json_value: Any, actual: Any) -> None:
        if json_value is not None and json_value != actual:
            out.append(f"summary.{name} = {json_value}, по перечням Report — {actual}")

    cmp("requirements", summary.get("requirements"), len(reqs))
    cmp("reviewed_requirements", summary.get("reviewed_requirements"),
        sum(1 for r in reqs if states[r]["state"] == "full"))
    cmp("findings", summary.get("findings"), len(findings))
    for s in SEVERITY_ORDER:
        cmp(f"by_severity.{s}", (summary.get("by_severity") or {}).get(s),
            sum(1 for f in findings if str(f.get("severity")) == s))
    for s in ("confirmed", "needs_review"):
        cmp(f"by_status.{s}", (summary.get("by_status") or {}).get(s),
            sum(1 for f in findings if finding_status(f) == s))
    if summary.get("critical_ids") is not None:
        actual = sorted(str(f.get("id")) for f in findings if str(f.get("severity")) == "critical")
        cmp("critical_ids", sorted(str(x) for x in as_list(summary.get("critical_ids"))), actual)
    for s in ("pass", "issue", "unknown", "na"):
        cmp(f"checks.{s}", (summary.get("checks") or {}).get(s),
            sum(1 for c in as_list(report.get("checks")) if isinstance(c, Mapping) and str(c.get("status")) == s))
    return out


def readiness_display(report: Mapping[str, Any], part: str) -> tuple[str, list[str], list[str]]:
    """Статус готовности для показа с учётом полноты прогона.

    Неполный или неуспешный прогон и неполное чтение документа никогда не
    показываются как готовность: «ready» из verdict показывается как
    «unconfirmed» с пояснением. Возвращает (код, основания, предупреждения).
    """
    vp = verdict_part(report, part)
    info = run_info(report)
    notes: list[str] = []
    status = vp["status"]
    if status == "ready" and info["status"] != "complete":
        notes.append(
            f"В verdict указано «ready», но прогон {RUN_STATUS_LABEL.get(info['status'], info['status'])}: "
            "готовность не подтверждена."
        )
        status = "unconfirmed"
    elif status == "ready" and partial_read_warnings(report):
        notes.append("В verdict указано «ready», но документ прочитан не полностью: готовность не подтверждена.")
        status = "unconfirmed"
    elif status == "unknown" and info["status"] != "complete":
        status = "unconfirmed"
    if status == "ready":
        crit = summary_numbers(report)["defects_critical"]
        if crit:
            notes.append(
                f"В verdict указано «ready», хотя подтверждённых критичных дефектов: {fmt_int(crit)}. Проверьте verdict."
            )
    return status, vp["reasons"], notes


def slug(text: Any, prefix: str) -> str:
    base = re.sub(r"[^0-9a-z]+", "-", str(text).lower()).strip("-")
    if not base or not str(text).isascii():
        # Не-ASCII идентификаторы (например, «Ф-1») получают стабильный хеш-суффикс.
        digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]
        base = f"{base}-{digest}" if base else digest
    return f"{prefix}-{base}"
