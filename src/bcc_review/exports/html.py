"""Автономный HTML-отчёт ревью ТЗ (направление №13).

Публичный интерфейс::

    write_html(report, output_path) -> Path

``report`` — канонический Report контракта v1 (``contracts/v1.json``): dict,
pydantic-модель, dataclass или путь к ``report.json``. Результат — один
``.html`` без внешних ресурсов. Его можно открыть с диска без сети и сервера.

Стабильные якоря для веб-интерфейса (№15) и Markdown-отчёта (№17):

* ``#finding-<id>`` — карточка замечания, см. :func:`finding_anchor`;
* ``#block-<id>`` — блок исходного документа, см. :func:`block_anchor`;
* ``#question-<id>``, ``#req-<id>`` — вопрос и требование;
* разделы: ``#summary``, ``#workspace``, ``#requirements``, ``#questions``,
  ``#checklist``, ``#coverage``, ``#diff``, ``#test-cases``, ``#facts``, ``#run``.

Подсветка строится в Python по проверенным диапазонам. Координаты контракта
заданы в кодовых точках Unicode, Python индексирует строки так же, поэтому
браузеру не нужно переводить кодовые точки в UTF-16. Каждая опора проверяется
условием ``block.text[start:end] == quote``. Опора, которая ему не отвечает,
не подсвечивается и помечается в карточке как неподтверждённая.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import html as _html
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "ANSWERS_FORMAT",
    "anchor_slug",
    "answers_markdown",
    "answers_storage_key",
    "block_anchor",
    "finding_anchor",
    "answer_one_line",
    "legacy_answers_storage_key",
    "parse_answers_markdown",
    "question_anchor",
    "question_fingerprint",
    "render_html",
    "requirement_anchor",
    "write_html",
]

GENERATOR = "bcc_review.exports.html/1.0"
ANSWERS_FORMAT = "bcc-review-answers/2"
DRAFT_FORMAT = "bcc-review-answers-draft/2"
LEGACY_DRAFT_FORMAT = "bcc-review-answers-draft/1"
ASSETS_DIR = Path(__file__).with_name("html_assets")

# --------------------------------------------------------------------------- #
# Якоря
# --------------------------------------------------------------------------- #

_SAFE_ID_CHARS = re.compile(r"[A-Za-z0-9.\-]")


def anchor_slug(raw: Any) -> str:
    """Однозначно переводит ID в безопасный фрагмент якоря.

    Латинские буквы, цифры, ``.`` и ``-`` остаются как есть. Любой другой
    символ, включая ``_``, кодируется как ``_<hex>_``. Обычные ID вроде
    ``F-001`` или ``b0012`` поэтому не меняются, а разные ID не совпадают.
    """
    out = []
    for ch in str(raw):
        out.append(ch if _SAFE_ID_CHARS.fullmatch(ch) else f"_{ord(ch):x}_")
    return "".join(out) or "_"


def finding_anchor(finding_id: Any) -> str:
    return "finding-" + anchor_slug(finding_id)


def block_anchor(block_id: Any) -> str:
    return "block-" + anchor_slug(block_id)


def question_anchor(question_id: Any) -> str:
    return "question-" + anchor_slug(question_id)


def requirement_anchor(req_id: Any) -> str:
    return "req-" + anchor_slug(req_id)


def answers_storage_key(document_sha256: str) -> str:
    """Ключ localStorage черновика ответов версии документа. Внутри записи лежат по отпечатку вопроса."""
    return f"bcc-review/answers/v2/{document_sha256}"


def legacy_answers_storage_key(document_sha256: str) -> str:
    """Ключ черновика старого формата (только Q-ID). Читается для явного показа, не пишется."""
    return f"bcc-review/answers/v1/{document_sha256}"


# --------------------------------------------------------------------------- #
# Подписи (перечисления — из contracts.py)
# --------------------------------------------------------------------------- #

SEVERITY_ORDER = ("critical", "major", "minor")
SEVERITY = {
    "critical": ("Критичное", "▲", "Критичные"),
    "major": ("Существенное", "◆", "Существенные"),
    "minor": ("Незначительное", "●", "Незначительные"),
}
STATUS = {"confirmed": "Подтверждено", "needs_review": "Требует проверки"}
ANCHOR = {"supported": "опора подтверждена", "incomplete": "опора неполная"}
MEANING = {
    "confirmed": "смысл подтверждён",
    "uncertain": "смысл под вопросом",
    "unchecked": "смысл не проверялся",
    "deterministic": "правило без LLM",
}
TARGETS = {"development": "разработку", "testing": "тестирование"}
RUN_STATUS = {
    "complete": "Прогон завершён",
    "partial": "Прогон неполный",
    "failed": "Прогон завершился ошибкой",
}
RUN_MODE = {
    "rules_plus_llm": "Правила + LLM",
    "rules_only": "Только правила (без LLM)",
    "mock": "Подставная модель (mock)",
}
SCOPE = {"requirement": "Требование", "set": "Набор требований"}
KIND = {
    "ambiguity": "Неоднозначность",
    "unverifiable": "Непроверяемость",
    "incomplete": "Неполнота",
    "conflict": "Противоречие",
    "omission": "Пропуск",
    "non_singular": "Неединичность",
    "design_in_requirement": "Проектное решение в требовании",
    "terminology": "Терминология",
    "traceability": "Прослеживаемость",
    "placeholder": "Незаполненный шаблон",
    "infeasible": "Нереализуемость",
    "incorrect": "Некорректность",
    "duplicate": "Дубль",
    "format": "Оформление",
    "other": "Другое",
}
# Подписи по умолчанию. criteria.toml (№05) и report.criteria имеют приоритет.
CRITERIA_DEFAULT = {
    "necessary": "Необходимость",
    "appropriate": "Уместность",
    "unambiguous": "Однозначность",
    "complete": "Полнота",
    "singular": "Единичность",
    "feasible": "Осуществимость",
    "verifiable": "Проверяемость",
    "correct": "Корректность",
    "conforming": "Соответствие шаблону",
    "set_complete": "Полнота набора",
    "set_consistent": "Согласованность набора",
    "set_feasible": "Осуществимость набора",
    "set_comprehensible": "Понятность набора",
    "set_validatable": "Возможность валидации",
    "ranked": "Ранжирование",
    "modifiable": "Модифицируемость",
    "traceable": "Прослеживаемость",
}
READINESS = {
    # статус: (класс, глиф, подпись)
    "ready": ("ok", "✓", "Можно начинать"),
    "not_ready": ("no", "✕", "Нельзя начинать"),
    "unknown": ("unk", "?", "Не определено"),
}
# Три статуса старых замечаний и отдельный список новых (Diff контракта).
DIFF_OLD = (
    ("resolved", "Исправлено", "✓"),
    ("persisting", "Осталось", "•"),
    ("unassessed", "Не оценено", "?"),
)
VALUE_LABELS = {
    # Отметки чек-листа
    "yes": "Да",
    "no": "Нет",
    "na": "Не требуется",
    # Проверки, покрытие, этапы, статусы требований
    "pass": "✓ норма",
    "issue": "✕ замечание",
    "unknown": "? не определено",
    "covered": "✓ покрыто",
    "partial": "◐ частично",
    "conflict": "✕ противоречие",
    "uncovered": "○ не покрыто",
    "ok": "✓ выполнен",
    "cached": "✓ из кэша",
    "failed": "✕ ошибка",
    "skipped": "— пропущен",
    "reviewed": "✓ проверено",
    "not_reviewed": "○ не проверено",
}
LABEL_KEYS = {"available", "checked", "status", "review_status"}
HEADER_LABELS = {
    "id": "ID",
    "text": "Текст",
    "available": "Создано или доступно",
    "checked": "Проверено",
    "status": "Статус",
    "value": "Значение",
    "answer": "Ответ",
    "note": "Примечание",
    "notes": "Примечания",
    "reason": "Обоснование",
    "finding_ids": "Замечания",
    "req_ids": "Требования",
    "req_id": "Требование",
    "affected_req_ids": "Затронутые требования",
    "block_ids": "Блоки",
    "criterion": "Критерий",
    "scope": "Охват",
    "precondition": "Предусловие",
    "action": "Действие",
    "expected": "Ожидаемый результат",
    "open_question_id": "Открытый вопрос",
    "obligation": "Обязательство",
    "acceptance_ids": "Критерии приёмки",
    "explanation": "Пояснение",
    "subject": "Объект",
    "field": "Поле",
    "unit": "Единица",
    "type": "Тип",
    "direction": "Направление",
    "range": "Диапазон",
    "source": "Источник",
    "hints": "Подсказки модели",
    "evidence": "Опора",
    "source_id": "ID в документе",
    "name": "Этап",
    "calls": "Вызовы",
    "cache_hits": "Из кэша",
    "retries": "Повторы",
    "model": "Модель",
    "duration_s": "Время, с",
    "input_tokens": "Токены вход",
    "output_tokens": "Токены выход",
    "implementation": "Реализация",
}

_SECTION_LINKS = (
    ("summary", "Итог"),
    ("workspace", "Ревью"),
    ("requirements", "Требования"),
    ("questions", "Вопросы"),
    ("checklist", "Чек-лист"),
    ("coverage", "Покрытие"),
    ("diff", "Сравнение версий"),
    ("test-cases", "Тест-кейсы"),
    ("run", "Паспорт"),
)

# --------------------------------------------------------------------------- #
# Нормализация входа
# --------------------------------------------------------------------------- #

_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _to_plain(report: Any) -> dict[str, Any]:
    """Report в виде обычного словаря JSON-типов."""
    if isinstance(report, (str, Path)):
        return json.loads(Path(report).read_text(encoding="utf-8"))
    if isinstance(report, Mapping):
        return json.loads(json.dumps(report, ensure_ascii=False, default=_json_default))
    dump = getattr(report, "model_dump", None)
    if callable(dump):  # pydantic v2
        return dump(mode="json", by_alias=True)
    for name in ("to_dict", "dict"):
        fn = getattr(report, name, None)
        if callable(fn):
            return _to_plain(fn())
    if dataclasses.is_dataclass(report) and not isinstance(report, type):
        return _to_plain(dataclasses.asdict(report))
    raise TypeError(f"write_html: неподдерживаемый тип Report: {type(report)!r}")


def _json_default(obj: Any) -> Any:
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json", by_alias=True)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _dom_safe(text: str) -> tuple[str, int]:
    """Заменяет символы, которые не переживают DOM, на U+FFFD (1 кодовая точка → 1).

    U+0000 HTML-парсер выбрасывает, одиночные суррогаты нельзя записать в UTF-8.
    Длина строки в кодовых точках сохраняется, координаты опор остаются верными.
    """
    count = text.count("\x00")
    if count:
        text = text.replace("\x00", "�")
    text, n = _LONE_SURROGATE.subn("�", text)
    return text, count + n


def _sanitize(obj: Any, counter: list[int]) -> Any:
    if isinstance(obj, str):
        clean, n = _dom_safe(obj)
        counter[0] += n
        return clean
    if isinstance(obj, list):
        return [_sanitize(x, counter) for x in obj]
    if isinstance(obj, dict):
        return {str(_sanitize(k, counter)): _sanitize(v, counter) for k, v in obj.items()}
    return obj


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in _as_list(value) if isinstance(v, dict)]


def _first(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, Mapping):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _warning_text(w: Any) -> str:
    if isinstance(w, Mapping):
        msg = str(_first(w, "message", "text", default="") or "")
        tail = ", ".join(str(w[k]) for k in ("code", "stage") if w.get(k))
        return f"{msg} ({tail})" if tail and msg else (msg or tail)
    return str(w)


# --------------------------------------------------------------------------- #
# Экранирование
# --------------------------------------------------------------------------- #


def _e(value: Any) -> str:
    """Экранирует текст для HTML-содержимого и атрибутов (CR — как ``&#13;``)."""
    return _html.escape("" if value is None else str(value), quote=True).replace("\r", "&#13;")


def _text(value: str) -> str:
    """Экранирует текст документа так, чтобы DOM-текст совпал с исходным.

    HTML-парсер нормализует CR и CRLF в LF. Ссылка ``&#13;`` даёт U+000D без
    нормализации, поэтому ``textContent`` равен ``block.text``.
    """
    return _html.escape(value, quote=False).replace("\r", "&#13;")


def _json_for_script(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _csp_hash(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


# --------------------------------------------------------------------------- #
# Опоры и подсветка
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Ev:
    id: str
    block_id: str
    start: int | None
    end: int | None
    quote: str
    ok: bool
    reason: str
    finding_ids: list[str] = dataclasses.field(default_factory=list)


class _Evidence:
    """Реестр опор: проверка координат и общие ID для подсветки и кнопок."""

    def __init__(self, blocks: Mapping[str, dict[str, Any]]):
        self.blocks = blocks
        self.items: dict[str, _Ev] = {}
        self._by_key: dict[tuple[Any, ...], str] = {}

    def verify(self, block_id: Any, start: Any, end: Any, quote: Any) -> tuple[bool, str]:
        block = self.blocks.get(str(block_id)) if block_id is not None else None
        if block is None:
            return False, "блок не найден в документе"
        if not _is_int(start) or not _is_int(end):
            return False, "нет символьных координат"
        text = block.get("text") or ""
        if not (0 <= start < end <= len(text)):
            return False, f"координаты {start}–{end} вне блока длиной {len(text)}"
        if not isinstance(quote, str) or not quote:
            return False, "нет цитаты"
        if text[start:end] != quote:
            return False, "цитата не совпадает с текстом блока по координатам"
        return True, ""

    def add(self, ev: Mapping[str, Any], *, finding_id: str | None = None) -> _Ev:
        block_id = ev.get("block_id")
        start, end, quote = ev.get("start"), ev.get("end"), ev.get("quote")
        key = (str(block_id), start, end, quote if isinstance(quote, str) else None)
        ev_id = self._by_key.get(key)
        if ev_id is None:
            ok, reason = self.verify(block_id, start, end, quote)
            ev_id = f"ev-{len(self.items) + 1}"
            self._by_key[key] = ev_id
            self.items[ev_id] = _Ev(
                id=ev_id,
                block_id=str(block_id),
                start=start if _is_int(start) else None,
                end=end if _is_int(end) else None,
                quote=quote if isinstance(quote, str) else "",
                ok=ok,
                reason=reason,
            )
        item = self.items[ev_id]
        if finding_id is not None and finding_id not in item.finding_ids:
            item.finding_ids.append(finding_id)
        return item

    def in_block(self, block_id: str) -> list[_Ev]:
        return [ev for ev in self.items.values() if ev.ok and ev.block_id == block_id]

    def stats(self) -> dict[str, int]:
        total = len(self.items)
        ok = sum(1 for ev in self.items.values() if ev.ok)
        return {"total": total, "ok": ok, "rejected": total - ok}


def _segments(text: str, evs: list[_Ev], sev_of: Mapping[str, str]) -> str:
    """Режет текст блока по границам опор, сегмент хранит все покрывающие опоры.

    Пересечения и вложения дают несколько сегментов с разными наборами
    ``data-ev``. Порядок и содержимое текста не меняются.
    """
    if not evs:
        return _text(text)
    points = {0, len(text)}
    for ev in evs:
        points.add(ev.start)  # type: ignore[arg-type]
        points.add(ev.end)  # type: ignore[arg-type]
    pts = sorted(points)
    out: list[str] = []
    for a, b in zip(pts, pts[1:]):
        if a >= b:
            continue
        piece = _text(text[a:b])
        cover = [ev for ev in evs if ev.start <= a and b <= ev.end]  # type: ignore[operator]
        if not cover:
            out.append(piece)
            continue
        fids: list[str] = []
        for ev in cover:
            for fid in ev.finding_ids:
                if fid not in fids:
                    fids.append(fid)
        ranks = [SEVERITY_ORDER.index(sev_of[f]) for f in fids if sev_of.get(f) in SEVERITY_ORDER]
        attrs = [
            f'data-ev="{" ".join(ev.id for ev in cover)}"',
            f'data-cp="{a}:{b}"',
            f'data-n="{len(fids)}"',
        ]
        cls = "hl"
        if ranks:
            attrs.append(f'data-sev="{SEVERITY_ORDER[min(ranks)]}"')
        if not fids:
            cls += " hl-q"
        # Опора замечания — семантическая подсветка <mark>; опоры требований и фактов без замечаний — <span>.
        tag = "mark" if fids else "span"
        out.append(f'<{tag} class="{cls}" {" ".join(attrs)}>{piece}</{tag}>')
    return "".join(out)


# --------------------------------------------------------------------------- #
# Координаты
# --------------------------------------------------------------------------- #


def _range(a: Any, b: Any) -> str:
    if a is None:
        return ""
    if b is None or b == a:
        return str(a)
    return f"{a}–{b}"


def _loc_page(loc: Any) -> int | None:
    if isinstance(loc, Mapping):
        for k in ("page", "page_start"):
            if _is_int(loc.get(k)):
                return int(loc[k])
    return None


def _fmt_loc(loc: Any) -> str:
    """Человекочитаемое место блока: страница, строки, путь DOCX."""
    if loc is None:
        return ""
    if isinstance(loc, (str, int)):
        return str(loc)
    if not isinstance(loc, Mapping):
        return ""
    parts: list[str] = []
    page = _range(_first(loc, "page", "page_start"), loc.get("page_end"))
    if page:
        parts.append(f"стр. {page}")
    a, b = loc.get("line_start", loc.get("line")), loc.get("line_end")
    if a is not None:
        parts.append(("строки " if b not in (None, a) else "строка ") + _range(a, b))
    if loc.get("path"):
        parts.append(str(loc["path"]))
    elif loc.get("part"):
        parts.append(str(loc["part"]))
    return " · ".join(parts)


def _ev_place(block: Mapping[str, Any], start: int | None) -> str:
    """Место опоры: точная строка по ``loc.map`` (Markdown/TXT) или страница (PDF)."""
    loc = block.get("loc") if isinstance(block.get("loc"), Mapping) else {}
    text = block.get("text") or ""
    page = _loc_page(loc)
    mapping = loc.get("map") if isinstance(loc, Mapping) else None
    if _is_int(start) and isinstance(mapping, list) and mapping:
        best = None
        for entry in mapping:
            if isinstance(entry, list) and len(entry) >= 2 and _is_int(entry[0]) and _is_int(entry[1]) and entry[0] <= start:
                if best is None or entry[0] >= best[0]:
                    best = entry
        if best is not None:
            line = best[1] + text[best[0] : start].count("\n")
            return (f"стр. {page} · " if page else "") + f"строка {line}"
    return _fmt_loc(loc)


# --------------------------------------------------------------------------- #
# Критерии
# --------------------------------------------------------------------------- #


def _criteria_labels(report: Mapping[str, Any]) -> dict[str, str]:
    labels = dict(CRITERIA_DEFAULT)
    toml_path = Path(__file__).resolve().parents[1] / "criteria.toml"
    if toml_path.is_file():
        try:
            import tomllib

            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            _collect_labels(data, labels)
        except Exception:  # конфиг соседнего модуля не должен ломать отчёт
            pass
    _collect_labels(report.get("criteria"), labels)
    return labels


def _collect_labels(node: Any, labels: dict[str, str], key: str | None = None) -> None:
    if isinstance(node, Mapping):
        name = _first(node, "name_ru", "title_ru", "label_ru", "name", "title", "label")
        code = _first(node, "code", "id", default=key)
        if isinstance(name, str) and code is not None and re.search(r"[А-Яа-яЁё]", name):
            labels[str(code)] = name
        for k, v in node.items():
            if isinstance(v, (Mapping, list)):
                _collect_labels(v, labels, str(k))
    elif isinstance(node, list):
        for item in node:
            _collect_labels(item, labels)


# --------------------------------------------------------------------------- #
# Ответы на вопросы: формат обмена с №08 (--answers)
# --------------------------------------------------------------------------- #


def _question_id(q: Mapping[str, Any], index: int) -> str:
    return str(_first(q, "id", "question_id", default=f"Q-{index + 1:02d}"))


def _question_text(q: Mapping[str, Any]) -> str:
    return str(_first(q, "prompt", "text", "question", "title", default=""))


def _question_findings(q: Mapping[str, Any]) -> list[str]:
    return [str(x) for x in _as_list(_first(q, "finding_ids", default=[]))]


def _decisions_by_question(report: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for d in _dicts(report.get("decisions")):
        qid = d.get("question_id")
        if qid is not None:
            out.setdefault(str(qid), []).append(d)
    return out


def _doc_sha(report: Mapping[str, Any]) -> str:
    return str((report.get("document") or {}).get("id") or (report.get("run") or {}).get("source_sha256") or "")


def _finding_anchors(report: Mapping[str, Any], finding_ids: Iterable[str]) -> list[str]:
    by_id = {str(f.get("id")): f for f in _dicts(report.get("findings"))}
    anchors: set[str] = set()
    for fid in finding_ids:
        f = by_id.get(str(fid))
        if f is None:
            continue
        evs = list(_dicts(f.get("evidence")))
        w = f.get("witness")
        if isinstance(w, Mapping):
            for side in ("evidence_a", "evidence_b"):
                evs += _dicts(w.get(side))
        for ev in evs:
            anchors.add(f"{ev.get('block_id')}:{ev.get('start')}:{ev.get('end')}:{ev.get('quote')}")
    return sorted(anchors)


def question_fingerprint(report: Any, question: Mapping[str, Any]) -> str:
    """Отпечаток вопроса: SHA-256 от документа, текста вопроса и опор его замечаний.

    Q-ID и ID замечаний нумеруются заново в каждом прогоне, поэтому в отпечаток не входят.
    Тот же вопрос с той же привязкой к тексту документа даёт тот же отпечаток в любом
    прогоне; другой текст вопроса или другие опоры дают другой.
    """
    rep = report if isinstance(report, Mapping) else _to_plain(report)
    payload = {
        "v": 1,
        "document": _doc_sha(rep),
        "prompt": _one_line(_question_text(question)),
        "anchors": _finding_anchors(rep, _question_findings(question)),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decision_state(report: Mapping[str, Any], d: Mapping[str, Any], fp: str) -> str:
    """``ok`` | ``qid_only`` | ``other_question`` | ``other_version`` для Decision под Q-ID вопроса."""
    doc_id, src = _doc_sha(report), str(d.get("source_sha256") or "")
    if src and doc_id and src != doc_id:
        return "other_version"
    dfp = d.get("question_fingerprint")
    if not dfp:
        return "qid_only"
    return "ok" if str(dfp) == fp else "other_question"


def _report_answer(report: Mapping[str, Any], qid: str, fp: str) -> str:
    """Ответ, учтённый прогоном (Decision), если он относится к этому вопросу этой версии документа."""
    for d in _decisions_by_question(report).get(qid, []):
        answer = d.get("answer")
        if isinstance(answer, str) and answer.strip() and _decision_state(report, d, fp) in ("ok", "qid_only"):
            return answer
    return ""


def answer_one_line(answer: str) -> str:
    """Ответ одной строкой: опубликованный ``parse_answers`` читает «Ответ: …» до конца строки."""
    parts = re.split(r"\r\n|\r|\n", answer or "")
    return " ".join(x.strip(" \t") for x in parts if x.strip(" \t"))


def _answers_header(report: Mapping[str, Any]) -> list[str | None]:
    """Шапка файла ответов. ``None`` — место строки ``exported_at``."""
    doc = report.get("document") or {}
    run = report.get("run") or {}
    return [
        "---",
        f"format: {ANSWERS_FORMAT}",
        f"source_sha256: {_doc_sha(report)}",
        f"document_title: {_one_line(doc.get('title'))}",
        f"report_run_id: {_one_line(run.get('run_id'))}",
        f"report_agent_version: {_one_line(run.get('agent_version'))}",
        None,
        "---",
        "",
        "# Ответы на уточняющие вопросы",
        "",
        "> Черновик ответов аналитика к отчёту ревью. Исходный документ этим файлом не изменён.",
        "> Ответ — одна строка «Ответ: …» под своим «## Q-ID». Q-ID действует только в прогоне report_run_id;",
        "> «Отпечаток вопроса» связывает ответ с текстом вопроса и его опорами в документе.",
        "> Учесть ответы: python -m bcc_review INPUT OUTPUT.md --answers answers.md",
        "",
    ]


def _answers_question_head(q: Mapping[str, Any], index: int, fp: str) -> list[str]:
    lines = [f"## {_question_id(q, index)}", ""]
    text = _question_text(q).replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        lines.append("> " + line if line else ">")
    lines.append("")
    options = [str(o) for o in _as_list(q.get("options")) if o not in (None, "")]
    if options:
        lines.append("Варианты: " + " | ".join(_one_line(o) for o in options))
    fids = _question_findings(q)
    if fids:
        lines.append("Замечания: " + ", ".join(fids))
    lines += [f"Отпечаток вопроса: {fp}", ""]
    return lines


def answers_markdown(report: Any, answers: Mapping[str, str], *, exported_at: str) -> str:
    """Файл ответов для ``--answers``: JS в HTML строит тот же текст байт в байт.

    ``answers`` — черновики по Q-ID ЭТОГО отчёта. Карточка «## Q-ID» есть у каждого вопроса,
    последнее поле — «Ответ: …» одной строкой; у открытого вопроса поле пустое (так его читает
    №08: вопрос остаётся открытым, Decision не создаётся). Пустой черновик заменяется ответом,
    уже учтённым прогоном для этого же вопроса.
    """
    rep = report if isinstance(report, dict) else _to_plain(report)
    lines: list[str] = []
    for item in _answers_header(rep):
        lines.append(f"exported_at: {exported_at}" if item is None else item)
    chosen = []
    for i, q in enumerate(_dicts(rep.get("questions"))):
        qid = _question_id(q, i)
        fp = question_fingerprint(rep, q)
        one = answer_one_line(answers.get(qid) or "") or answer_one_line(_report_answer(rep, qid, fp))
        chosen.append((i, q, qid, fp, one))
    missing = [qid for _, _, qid, _, one in chosen if not one]
    if missing:
        lines += ["Без ответа: " + ", ".join(missing), ""]
    for i, q, _qid, fp, one in chosen:
        lines += _answers_question_head(q, i, fp) + [f"Ответ: {one}" if one else "Ответ:", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def parse_answers_markdown(text: str) -> dict[str, Any]:
    """Эталонный разбор файла ответов (форматы 2 и 1).

    Возвращает ``{"meta", "answers": {Q-ID: ответ}, "fingerprints": {Q-ID: отпечаток}, "unanswered": [...]}``.
    Decision для №08: ``{question_id, source_sha256 = meta["source_sha256"], answer,
    question_fingerprint}``.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            key, sep, value = lines[i].partition(":")
            if sep:
                meta[key.strip()] = value.strip()
            i += 1
        i += 1
    answers: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    unanswered: list[str] = []
    current: str | None = None
    buf: list[str] | None = None  # формат 1: блок после «### Ответ»

    def flush() -> None:
        if current is not None and buf is not None:
            body = "\n".join(buf).strip("\n")
            if body.strip():
                answers[current] = body

    for line in lines[i:]:
        if line.startswith("## "):
            flush()
            current, buf = line[3:].strip().split(" ")[0], None
        elif current is None and line.startswith("Без ответа:"):
            unanswered += [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        elif current is not None and buf is None and line.startswith("Отпечаток вопроса:"):
            fingerprints[current] = line.split(":", 1)[1].strip()
        elif current is not None and buf is None and line.startswith("Ответ:"):
            value = line.split(":", 1)[1].strip()
            if value:
                answers[current] = value
        elif current is not None and buf is None and line.strip() == "### Ответ":
            buf = []
        elif buf is not None:
            buf.append(line[1:] if line.startswith("\\") else line)
    flush()
    return {"meta": meta, "answers": answers, "fingerprints": fingerprints, "unanswered": unanswered}


# --------------------------------------------------------------------------- #
# Рендер
# --------------------------------------------------------------------------- #


class _Renderer:
    def __init__(self, report: dict[str, Any], *, pdf_href: str | None):
        replaced = [0]
        self.r = _sanitize(report, replaced)
        self.pdf_href = pdf_href
        self.doc: dict[str, Any] = self.r.get("document") or {}
        self.run: dict[str, Any] = self.r.get("run") or {}
        self.doc_id = _doc_sha(self.r)
        self.blocks_list = _dicts(self.doc.get("blocks"))
        self.blocks = {str(b.get("id")): b for b in self.blocks_list}
        self.block_order = [str(b.get("id")) for b in self.blocks_list]
        self.findings = _dicts(self.r.get("findings"))
        self.requirements = _dicts(self.r.get("requirements"))
        self.questions = _dicts(self.r.get("questions"))
        self.decisions = _decisions_by_question(self.r)
        self.qfp = {_question_id(q, i): question_fingerprint(self.r, q) for i, q in enumerate(self.questions)}
        # Decision привязан, только если его Q-ID есть в этом прогоне и отпечаток не противоречит.
        self.dec_attached: list[dict[str, Any]] = []
        self.dec_unattached: list[tuple[dict[str, Any], str]] = []
        for d in _dicts(self.r.get("decisions")):
            qid = str(d.get("question_id"))
            if qid not in self.qfp:
                self.dec_unattached.append((d, f"в этом прогоне нет вопроса {qid}: Q-ID относится к прогону, где был задан вопрос"))
                continue
            state = _decision_state(self.r, d, self.qfp[qid])
            if state in ("ok", "qid_only"):
                self.dec_attached.append(d)
            elif state == "other_question":
                self.dec_unattached.append((d, f"отпечаток вопроса не совпал с {qid} этого прогона"))
            else:
                self.dec_unattached.append((d, "ответ дан к другой версии документа"))
        self.crit_labels = _criteria_labels(self.r)
        self.render_warnings: list[str] = []
        if replaced[0]:
            self.render_warnings.append(
                f"Заменено непредставимых в HTML символов (U+0000, одиночные суррогаты): {replaced[0]}."
            )
        self.ids = {
            "finding": {str(f.get("id")) for f in self.findings},
            "block": set(self.block_order),
            "question": {_question_id(q, i) for i, q in enumerate(self.questions)},
            "req": {str(q.get("id")) for q in self.requirements},
        }
        self.all_ids = set().union(*self.ids.values())
        self.ev = _Evidence(self.blocks)
        self.sev_of: dict[str, str] = {}
        self.f_ev: dict[str, dict[str, list[str]]] = {}
        self.f_blocks: dict[str, list[str]] = {}
        self.req_ev: dict[str, list[str]] = {}
        self._register()

    # ------------------------------------------------------------ registry
    def _register(self) -> None:
        seen: set[str] = set()
        for i, f in enumerate(self.findings):
            fid = str(f.get("id") or f"F-{i + 1:03d}")
            if fid in seen:
                self.render_warnings.append(f"Повторяющийся ID замечания: {fid}.")
            seen.add(fid)
            f["id"] = fid
            sev = str(f.get("severity") or "minor")
            self.sev_of[fid] = sev if sev in SEVERITY else "minor"
            groups: dict[str, list[str]] = {"ev": [], "a": [], "b": []}
            witness = f.get("witness") if isinstance(f.get("witness"), Mapping) else None
            if witness:
                for side in ("a", "b"):
                    for ev in _dicts(witness.get(f"evidence_{side}")):
                        item = self.ev.add(ev, finding_id=fid)
                        if item.id not in groups[side]:
                            groups[side].append(item.id)
            for ev in _dicts(f.get("evidence")):
                item = self.ev.add(ev, finding_id=fid)
                if item.id not in groups["ev"] + groups["a"] + groups["b"]:
                    groups["ev"].append(item.id)
            self.f_ev[fid] = groups
            blocks: list[str] = []
            for ev_id in groups["a"] + groups["b"] + groups["ev"]:
                b = self.ev.items[ev_id].block_id
                if b in self.blocks and b not in blocks:
                    blocks.append(b)
            for h in _dicts(f.get("hints")):
                b = str(h.get("block_id"))
                if b in self.blocks and b not in blocks:
                    blocks.append(b)
            self.f_blocks[fid] = blocks
        for req in self.requirements:
            rid = str(req.get("id"))
            self.req_ev[rid] = [self.ev.add(ev).id for ev in _dicts(req.get("evidence"))]
        # Опоры фактов, покрытия, чек-листа и diff регистрируются заранее,
        # чтобы попасть в подсветку документа.
        for key in ("facts", "coverage", "checklist", "diff", "decisions", "test_cases"):
            self._prescan(self.r.get(key))

    def _prescan(self, node: Any) -> None:
        if isinstance(node, Mapping):
            if "block_id" in node and "quote" in node and "start" in node:
                self.ev.add(node)
                return
            for v in node.values():
                self._prescan(v)
        elif isinstance(node, list):
            for v in node:
                self._prescan(v)

    # ------------------------------------------------------------ helpers
    def link(self, raw: Any) -> str:
        """ID → ссылка на якорь, если такой объект есть в отчёте."""
        s = str(raw)
        if s in self.ids["finding"]:
            sev = self.sev_of.get(s, "minor")
            return (
                f'<a class="ref ref-f sev-{sev}" href="#{finding_anchor(s)}">'
                f'<span class="sr-only">{SEVERITY[sev][0]}: </span>{_e(s)}</a>'
            )
        if s in self.ids["block"]:
            return f'<a class="ref ref-b" href="#{block_anchor(s)}">{_e(s)}</a>'
        if s in self.ids["question"]:
            return f'<a class="ref" href="#{question_anchor(s)}">{_e(s)}</a>'
        if s in self.ids["req"]:
            return f'<a class="ref" href="#{requirement_anchor(s)}">{_e(s)}</a>'
        return f'<span class="ref ref-x">{_e(s)}</span>'

    def links(self, values: Any) -> str:
        items = [self.link(v) for v in _as_list(values) if v not in (None, "")]
        return '<span class="refs">' + " ".join(items) + "</span>" if items else "—"

    def crit(self, code: Any) -> str:
        if code in (None, ""):
            return ""
        code = str(code)
        return self.crit_labels.get(code, code)

    def block_src(self, block_id: str, start: int | None = None) -> str:
        b = self.blocks.get(block_id)
        if b is None:
            return _e(block_id)
        path = [str(s) for s in _as_list(b.get("section")) if s]
        section = ("… › " if len(path) > 2 else "") + " › ".join(path[-2:])
        bits = [_e(block_id)]
        if section:
            bits.append(_e(section))
        place = _ev_place(b, start)
        if place:
            bits.append(_e(place))
        return " · ".join(bits)

    def value(self, v: Any, key: str = "") -> str:
        if v is None or v == "":
            return "—"
        if isinstance(v, bool):
            return "Да" if v else "Нет"
        if isinstance(v, (int, float)):
            return _e(v)
        if isinstance(v, str):
            if key in LABEL_KEYS and v in VALUE_LABELS:
                return f'<span class="val val-{_e(v)}">{_e(VALUE_LABELS[v])}</span>'
            if key in ("criterion",):
                return _e(self.crit(v))
            if key.endswith(("_id", "_ids")) or v in self.all_ids:
                return self.link(v)
            return f'<span class="pre">{_e(v)}</span>'
        if isinstance(v, list):
            if not v:
                return "—"
            if all(isinstance(x, (str, int)) for x in v):
                if key.endswith("_ids") or any(str(x) in self.all_ids for x in v):
                    return self.links(v)
                return _e(", ".join(str(x) for x in v))
            if all(isinstance(x, Mapping) and "block_id" in x and "start" in x for x in v):
                return " ".join(self.ev_button(self.ev.add(x)) for x in v)
            if all(isinstance(x, Mapping) and "quote" in x for x in v):
                return " ".join(self.hint_html(x) for x in v)
            return "<br>".join(self.value(x) for x in v)
        if isinstance(v, Mapping):
            if "block_id" in v and "start" in v and "quote" in v:
                return self.ev_button(self.ev.add(v))
            return "; ".join(f"{_e(HEADER_LABELS.get(k, k))}: {self.value(x, k)}" for k, x in v.items())
        return _e(v)

    def table(self, rows: list[dict[str, Any]], *, caption: str, row_anchor: str | None = None, keys: list[str] | None = None) -> str:
        if not rows:
            return ""
        if keys is None:
            keys = []
            for row in rows:
                for k in row:
                    if k not in keys:
                        keys.append(k)
        head = "".join(f'<th scope="col">{_e(HEADER_LABELS.get(k, k))}</th>' for k in keys)
        body = []
        for row in rows:
            rid = ""
            if row_anchor and row.get("id") is not None:
                rid = f' id="{row_anchor}-{anchor_slug(row["id"])}"'
            cells = "".join(f"<td>{self.value(row.get(k), k)}</td>" for k in keys)
            body.append(f"<tr{rid}>{cells}</tr>")
        return (
            f'<div class="tbl-wrap" role="region" aria-label="{_e(caption)}" tabindex="0">'
            f'<table><caption class="sr-only">{_e(caption)}</caption><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>'
        )

    def kv(self, pairs: Iterable[tuple[str, Any]]) -> str:
        rows = [f"<div><dt>{_e(k)}</dt><dd>{v}</dd></div>" for k, v in pairs]
        return f'<dl class="kv">{"".join(rows)}</dl>' if rows else ""

    def sev_badge(self, sev: str) -> str:
        label, glyph, _ = SEVERITY.get(sev, SEVERITY["minor"])
        return f'<span class="sev sev-{sev}"><span aria-hidden="true">{glyph}</span> {label}</span>'

    def hint_html(self, h: Mapping[str, Any]) -> str:
        b = str(h.get("block_id") or "")
        where = self.link(b) if b in self.blocks else "блок не указан"
        return (
            f'<span class="q-item q-hint"><span class="small muted">Подсказка без координат:</span> '
            f'<q>{_text(str(h.get("quote") or ""))}</q> {where}</span>'
        )

    def ev_button(self, ev: _Ev, *, side: str | None = None, context: int = 0) -> str:
        src = self.block_src(ev.block_id, ev.start)
        side_txt = f"стороны {side.upper()} " if side else ""
        if ev.ok:
            side_attr = f' data-side="{side}"' if side else ""
            before = after = ""
            if context:
                text = self.blocks[ev.block_id].get("text") or ""
                s, e = int(ev.start or 0), int(ev.end or 0)
                pre, post = text[max(0, s - context) : s], text[e : e + context]
                if pre.strip():
                    before = f'<span class="q-ctx">{"…" if s > context else ""}{_e(_one_line(pre))} </span>'
                if post.strip():
                    gap = "" if post[:1] in ".,;:!?)»…" else " "
                    tail = "…" if e + context < len(text) else ""
                    after = f'<span class="q-ctx">{gap}{_e(_one_line(post))}{tail}</span>'
            return (
                f'<span class="q-item"><span class="q-line">{before}'
                f'<button type="button" class="q-btn" data-ev="{ev.id}"{side_attr}>'
                f'<span class="sr-only">Показать в документе цитату {side_txt}</span>'
                f"<q>{_text(ev.quote)}</q></button>{after}</span>"
                f'<span class="q-src">{src}</span></span>'
            )
        blink = (
            f' <a class="ref ref-b" href="#{block_anchor(ev.block_id)}">открыть блок {_e(ev.block_id)}</a>'
            if ev.block_id in self.blocks
            else ""
        )
        return (
            f'<span class="q-item q-bad"><span class="warn"><span aria-hidden="true">⚠</span> '
            f"Опора не подтверждена: {_e(ev.reason)}.</span> "
            f"<q>{_text(ev.quote) or '—'}</q>{blink}"
            f'<span class="q-src">{src}</span></span>'
        )

    def section(self, sid: str, title: str, inner: str, *, empty: str) -> str:
        return (
            f'<section id="{sid}" class="sec" aria-labelledby="{sid}-h"><h2 id="{sid}-h">{_e(title)}</h2>'
            f'{inner or f"<p class=muted>{_e(empty)}</p>"}</section>'
        )

    def warnings_all(self) -> list[str]:
        warns = [_warning_text(w) for w in _as_list(self.r.get("warnings"))]
        warns += ["Документ: " + _warning_text(w) for w in _as_list(self.doc.get("warnings"))]
        return warns + self.render_warnings

    # ------------------------------------------------------------ header & summary
    def header(self) -> str:
        status = str(self.run.get("status") or "unknown")
        nav = []
        for anchor, label in _SECTION_LINKS:
            if anchor == "diff" and not self.r.get("diff"):
                continue
            extra = ""
            if anchor == "questions" and self.questions:
                extra = f' <span class="cnt">{len(self.questions)}</span>'
            nav.append(f'<li><a href="#{anchor}">{label}{extra}</a></li>')
        return (
            '<header class="bar"><div class="bar-in">'
            '<div class="bar-title"><span class="kicker">Ревью ТЗ</span> '
            f'<span class="doc-title">{_e(self.doc.get("title") or "Документ без названия")}</span></div>'
            f'<span class="run-chip run-{_e(status)}">{_e(RUN_STATUS.get(status, "Статус прогона не указан"))}</span>'
            f'<nav aria-label="Разделы отчёта"><ul>{"".join(nav)}</ul></nav>'
            "</div></header>"
        )

    _STAGE_REASON = re.compile(r"^([A-Za-z_][\w#.\-]*):\s+(.+)$", re.S)

    def run_reason_groups(self) -> list[tuple[str, list[str]]]:
        """``status_reasons`` вида «этап: причина», сгруппированные по тексту причины (крупные группы первыми)."""
        groups: dict[str, list[str]] = {}
        for raw in _as_list(self.run.get("status_reasons")):
            text = " ".join(str(raw).split())
            m = self._STAGE_REASON.match(text)
            stage, reason = (m.group(1), m.group(2)) if m else ("", text)
            stages = groups.setdefault(reason, [])
            if stage and stage not in stages:
                stages.append(stage)
        return sorted(groups.items(), key=lambda kv: -len(kv[1]))

    def run_banner(self) -> str:
        """Статус прогона для первого экрана: код статуса, главная причина, остальное — в <details>."""
        status = str(self.run.get("status") or "")
        if status == "complete":
            return ""
        head = {"partial": "Прогон неполный", "failed": "Прогон завершился ошибкой"}.get(status, "Статус прогона не указан")
        tail = {
            "partial": "Часть проверок не выполнена: отсутствие замечания не доказывает отсутствие дефекта.",
            "failed": "Отчёт содержит только то, что успели проверить.",
        }.get(status, "Отчёт нельзя считать полным.")
        groups = self.run_reason_groups()
        stages = [str(x) for x in _as_list(self.run.get("incomplete_stages"))]
        if groups:
            reason, st = groups[0]
            primary = reason.rstrip(".") + (f" — этапы: {', '.join(st)}" if st else "")
            more = len(groups) - 1
        else:
            primary = ("не выполнены этапы: " + ", ".join(stages)) if stages else "причина в отчёте не указана"
            more = 0
        notes = [str(x) for x in _as_list(self.run.get("status_reasons"))]
        if stages:
            notes.append("Не выполнены этапы: " + ", ".join(stages))
        notes += self.warnings_all()
        details = (
            f'<details class="run-more"><summary>Все причины и предупреждения ({len(notes)})</summary>'
            "<ul>" + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul></details>"
            if notes
            else ""
        )
        return (
            '<div class="banner banner-run" id="run-state" role="note" aria-labelledby="run-state-h">'
            f'<p class="run-head" id="run-state-h"><strong><span aria-hidden="true">⚠</span> {head}</strong> '
            f'<code class="run-code">status: {_e(status or "—")}</code></p>'
            f'<p class="run-reason"><b>Причина:</b> {_e(primary)}{f"; ещё причин: {more}" if more else ""}.</p>'
            f'<p class="small run-tail">{tail}</p>{details}</div>'
        )

    def verdict_tile(self, title: str, data: Any, key: str) -> str:
        if isinstance(data, bool):
            data = {"status": "ready" if data else "not_ready"}
        if isinstance(data, str):
            data = {"status": data}
        data = data if isinstance(data, Mapping) else {}
        status = str(data.get("status") or "")
        if not status and isinstance(data.get("ready"), bool):
            status = "ready" if data["ready"] else "not_ready"
        cls, glyph, label = READINESS.get(status, ("unk", "?", "Решение не сформировано"))
        reasons = [" ".join(str(r).split()) for r in _as_list(_first(data, "reasons", "reason", default=[])) if r]
        blockers = _as_list(_first(data, "finding_ids", "blocking_finding_ids", default=[]))
        run_reasons = [" ".join(str(x).split()) for x in _as_list(self.run.get("status_reasons")) if x]

        def repeats_run_status(r: str) -> bool:
            return r.startswith(("Прогон partial", "Прогон failed", "Прогон неполный")) or any(x in r for x in run_reasons)

        own = [r for r in reasons if not repeats_run_status(r)]
        shown = own[0] if own else (reasons[0] if reasons else "")
        rest = [r for r in reasons if r != shown]
        prelim = ""
        if self.run.get("status") != "complete":
            prelim = '<span class="prelim">предварительно: прогон неполный</span>'
        reasons_html = f'<p class="tile-r">{_e(shown)}</p>' if shown else ""
        if rest:
            reasons_html += (
                f'<details class="tile-more"><summary>Всё обоснование ({len(reasons)})</summary><ul>'
                + "".join(f"<li>{_e(r)}</li>" for r in reasons)
                + "</ul></details>"
            )
        return (
            f'<div class="tile tile-{cls}" id="verdict-{key}" role="group" aria-labelledby="verdict-{key}-h">'
            f'<h3 id="verdict-{key}-h">{_e(title)}</h3>'
            f'<p class="tile-v"><span aria-hidden="true" class="glyph">{glyph}</span> {_e(label)}</p>{prelim}'
            f'{f"<p class=small>Блокируют: {self.links(blockers)}</p>" if blockers else ""}'
            f"{reasons_html}</div>"
        )

    def summary(self) -> str:
        v = self.r.get("verdict") if isinstance(self.r.get("verdict"), Mapping) else {}
        s = self.r.get("summary") if isinstance(self.r.get("summary"), Mapping) else {}
        counts = {k: 0 for k in SEVERITY_ORDER}
        for f in self.findings:
            counts[self.sev_of[f["id"]]] += 1
        review = sum(1 for f in self.findings if f.get("status") == "needs_review")
        open_q = sum(1 for qid, fp in self.qfp.items() if not _report_answer(self.r, qid, fp))
        n_req = len(self.requirements)
        reviewed = s.get("reviewed_requirements")
        req_label = f"{reviewed} из {n_req} требований проверено" if _is_int(reviewed) and reviewed != n_req else "требований"
        req_num = "" if _is_int(reviewed) and reviewed != n_req else str(n_req)
        stat_html = (
            f'<li><a href="#requirements"><b>{req_num}</b> {_e(req_label)}</a></li>'
            f'<li><a href="#workspace"><b>{len(self.findings)}</b> замечаний</a></li>'
        )
        stat_html += "".join(
            f'<li class="sev-{k}"><a href="#workspace" data-filter-sev="{k}"><b>{counts[k]}</b> '
            f'<span aria-hidden="true">{SEVERITY[k][1]}</span> {SEVERITY[k][2].lower()}</a></li>'
            for k in SEVERITY_ORDER
        )
        for target, label in (("development", "блокируют разработку"), ("testing", "блокируют тестирование")):
            n = sum(1 for f in self.findings if target in _as_list(f.get("blocks")))
            if n:
                stat_html += f'<li><a href="#workspace" data-filter-blocks="{target}"><b>{n}</b> {label}</a></li>'
        stat_html += f'<li><a href="#workspace" data-filter-status="needs_review"><b>{review}</b> требуют проверки</a></li>'
        stat_html += f'<li><a href="#questions"><b>{open_q}</b> открытых вопросов</a></li>'
        actions = _dicts(_first(v, "first_actions", default=[]))
        actions.sort(key=lambda a: a.get("order") if _is_int(a.get("order")) else 10**6)
        act_items = []
        for a in actions:
            text = _first(a, "action", "text", "title", default="")
            refs = _first(a, "finding_ids", default=[])
            act_items.append(f"<li>{_e(text)} {self.links(refs) if refs else ''}</li>")
        for a in _as_list(_first(v, "first_actions", default=[])):
            if isinstance(a, str):
                act_items.append(f"<li>{_e(a)}</li>")
        dec_html = ""
        if self.dec_attached or self.dec_unattached:
            dec_html = (
                f'<p class="small">Ответов из --answers: {len(self.dec_attached) + len(self.dec_unattached)}; '
                f'привязано к вопросам этого прогона: <a href="#questions">{len(self.dec_attached)}</a>'
                + (
                    f'; <a class="warn" href="#ans-unattached">без вопроса: {len(self.dec_unattached)}</a>'
                    if self.dec_unattached
                    else ""
                )
                + ".</p>"
            )
        basis = _first(v, "basis", "summary", default="")
        return (
            '<section id="summary" class="summary" aria-labelledby="summary-h">'
            '<h2 id="summary-h">Итог ревью</h2>'
            '<div class="verdict">'
            f'{self.verdict_tile("Разработка", _first(v, "development", "dev"), "development")}'
            f'{self.verdict_tile("Тестирование", _first(v, "testing", "test"), "testing")}'
            "</div>"
            f"{self.run_banner()}"
            '<div class="actions" id="first-actions"><h3>Что сделать первым</h3>'
            f'{"<ol>" + "".join(act_items) + "</ol>" if act_items else "<p class=muted>Первые действия в отчёте не указаны.</p>"}'
            f"{dec_html}</div>"
            f'{f"<p class=verdict-sum>{_e(basis)}</p>" if basis else ""}'
            f'<ul class="stats" aria-label="Сводка">{stat_html}</ul>'
            "</section>"
        )

    # ------------------------------------------------------------ document
    def document_pane(self) -> str:
        parts: list[str] = []
        excluded: dict[str, str] = {}
        for ex in _dicts(self.r.get("excluded")):
            for b in _as_list(ex.get("block_ids")):
                excluded[str(b)] = str(ex.get("reason") or "")
        read_warn: dict[str, str] = {}
        for w in _dicts(self.doc.get("warnings")):
            for b in _as_list(w.get("block_ids")):
                read_warn[str(b)] = str(w.get("code") or w.get("message") or "")
        prev_section: list[str] | None = None
        prev_page: int | None = None
        prev_kind = ""
        fids_by_block: dict[str, list[str]] = {}
        for fid, blocks in self.f_blocks.items():
            for b in blocks:
                fids_by_block.setdefault(b, []).append(fid)
        for b in self.blocks_list:
            bid = str(b.get("id"))
            kind = str(b.get("kind") or "paragraph")
            text = b.get("text") if isinstance(b.get("text"), str) else ""
            section = [str(x) for x in _as_list(b.get("section"))]
            page = _loc_page(b.get("loc"))
            if page is not None and page != prev_page:
                parts.append(f'<div class="page-mark" aria-hidden="true"><span>Страница {page}</span></div>')
                prev_page = page
            if section != prev_section and kind != "heading" and section and prev_kind != "heading":
                parts.append(f'<div class="sec-mark">{_e(" › ".join(section))}</div>')
            prev_section, prev_kind = section, kind
            loc = _fmt_loc(b.get("loc"))
            fids = fids_by_block.get(bid, [])
            pdf = ""
            if self.pdf_href and page is not None:
                pdf = f' <a class="pdf-link" href="{_e(self.pdf_href)}#page={page}">PDF, стр. {page}</a>'
            btn = ""
            if fids:
                word = _plural(len(fids), "замечание", "замечания", "замечаний")
                btn = (
                    f'<button type="button" class="blk-f" data-fids="{_e(" ".join(fids))}" '
                    f'aria-label="Блок {_e(bid)}: {len(fids)} {word}">{len(fids)} {word}</button>'
                )
            flags = ""
            if bid in excluded:
                flags += f'<span class="blk-flag" title="{_e(excluded[bid])}">исключён из проверки: {_e(excluded[bid])}</span>'
            if bid in read_warn:
                flags += f'<span class="blk-flag">чтение: {_e(read_warn[bid])}</span>'
            level = min(len(section) + 1, 4) if kind == "heading" else 0
            body = _segments(text, self.ev.in_block(bid), self.sev_of)
            parts.append(
                f'<div class="blk blk-{_e(kind)}{" lvl-" + str(level) if level else ""}{" blk-ex" if bid in excluded else ""}" '
                f'id="{block_anchor(bid)}" data-block="{_e(bid)}">'
                f'<div class="blk-meta"><a class="blk-id" href="#{block_anchor(bid)}" title="Ссылка на блок">{_e(bid)}</a>'
                f'{f"<span class=loc>{_e(loc)}</span>" if loc else ""}{pdf}{flags}{btn}</div>'
                f'<div class="blk-text" data-text>{body}</div></div>'
            )
        if not self.blocks_list:
            parts.append('<p class="empty">Документ не содержит блоков текста.</p>')
        fmt = self.doc.get("format") or "—"
        pdf_note = (
            f'Оригинал: <a href="{_e(self.pdf_href)}">PDF</a>.'
            if self.pdf_href
            else "Оригинальный файл не приложен к этому отчёту. Страницы и строки указаны у каждого блока."
        )
        return (
            '<section class="pane pane-doc" id="doc-pane" aria-labelledby="doc-h" data-pane="doc">'
            '<div class="pane-head"><h2 id="doc-h">Исходный документ</h2>'
            f'<p class="small muted">{_e(self.doc.get("title") or "")} · формат {_e(fmt)} · блоков {len(self.blocks_list)} · '
            f"{pdf_note}</p></div>"
            '<div class="ret" id="ret" hidden><span id="ret-label" class="ret-label"></span>'
            '<button type="button" class="btn" id="ret-prev">← Предыдущая цитата</button>'
            '<button type="button" class="btn" id="ret-next">Следующая цитата →</button>'
            '<button type="button" class="btn btn-pri" id="ret-back">Вернуться к замечанию</button></div>'
            '<div class="chooser" id="chooser" role="dialog" aria-modal="false" aria-labelledby="chooser-h" hidden>'
            '<div class="chooser-head"><h3 id="chooser-h">Замечания к фрагменту</h3>'
            '<button type="button" class="btn" id="chooser-close">Закрыть</button></div><ul id="chooser-list"></ul></div>'
            f'<div class="doc-scroll" id="doc-scroll" tabindex="-1">{"".join(parts)}</div>'
            "</section>"
        )

    # ------------------------------------------------------------ findings
    def finding_card(self, f: dict[str, Any]) -> str:
        fid = f["id"]
        sev = self.sev_of[fid]
        status = str(f.get("status") or "")
        kind = str(f.get("kind") or "")
        scope = str(f.get("scope") or "")
        criterion = f.get("criterion")
        groups = self.f_ev[fid]
        witness = f.get("witness") if isinstance(f.get("witness"), Mapping) else None
        targets = [t for t in _as_list(f.get("blocks")) if t in TARGETS]
        meta = [KIND.get(kind, kind), self.crit(criterion), SCOPE.get(scope, scope)]
        meta_html = " · ".join(_e(m) for m in meta if m)
        status_html = f'<span class="st st-{_e(status)}">{_e(STATUS.get(status, status))}</span>' if status else ""
        block_html = "".join(
            f'<span class="blocks-tag"><span aria-hidden="true">⊘</span> блокирует {TARGETS[t]}</span> ' for t in targets
        )
        locs = []
        for b in self.f_blocks[fid][:4]:
            blk = self.blocks.get(b) or {}
            loc = _fmt_loc(blk.get("loc"))
            locs.append(f"{b}{' · ' + loc if loc else ''}")
        loc_line = "; ".join(locs) + (" …" if len(self.f_blocks[fid]) > 4 else "")

        body: list[str] = []
        if witness:
            body.append(self.witness_html(fid, witness))
        elif kind == "conflict":
            body.append('<p class="warn small">Свидетель конфликта (witness) не приложен: противоречие не подтверждено двумя опорами.</p>')
        # Основание
        inner = ""
        cause = f.get("cause") if isinstance(f.get("cause"), Mapping) else None
        if cause:
            outcomes = [str(o) for o in _as_list(cause.get("outcomes")) if o]
            inner += f'<p><b>{_e(cause.get("object") or "")}</b>'
            if cause.get("condition"):
                inner += f" — условие: {_e(cause['condition'])}"
            inner += "</p>"
            if outcomes:
                inner += "<ul>" + "".join(f"<li>{_e(o)}</li>" for o in outcomes) + "</ul>"
        crit_line = self.crit(criterion)
        checks = []
        if crit_line:
            checks.append(f"критерий «{crit_line}»")
        if f.get("anchor_status") in ANCHOR:
            checks.append(ANCHOR[f["anchor_status"]])
        if f.get("meaning_status") in MEANING:
            checks.append(MEANING[f["meaning_status"]])
        if checks:
            line = "; ".join(checks)
            inner += f'<p class="small muted">{_e(line[:1].upper() + line[1:])}.</p>'
        if f.get("meaning_reason"):
            inner += f'<p class="small">{_e(f["meaning_reason"])}</p>'
        if inner:
            body.append(f'<div class="fd"><h4>Основание</h4>{inner}</div>')
        # Последствие
        inner = f"<p>{_e(f['impact'])}</p>" if f.get("impact") else ""
        if f.get("blocked_decision"):
            inner += f'<p class="blocked"><b>Блокирует решение:</b> {_e(f["blocked_decision"])}</p>'
        if inner:
            body.append(f'<div class="fd"><h4>Последствие</h4>{inner}</div>')
        # Источник
        src_items = [self.ev_button(self.ev.items[e], context=60) for e in groups["ev"]]
        src_items += [self.hint_html(h) for h in _dicts(f.get("hints")) if not self._hint_covered(h, groups)]
        inspected = _as_list(f.get("inspected_block_ids"))
        if src_items or inspected or not witness:
            inner = "".join(src_items)
            if inspected:
                inner += f'<p class="small">Проверены блоки: {self.links(inspected)}</p>'
            if not inner:
                inner = '<p class="muted">Текстовой опоры нет.</p>'
            body.append(f'<div class="fd"><h4>{"Другие опоры" if witness else "Источник"}</h4>{inner}</div>')
        # Вопрос
        questions = [
            (_question_id(q, i), _question_text(q)) for i, q in enumerate(self.questions) if fid in _question_findings(q)
        ]
        if questions:
            inner = "".join(
                f'<p>{_e(text)} <a class="ref" href="#{question_anchor(qid)}">Ответить на {_e(qid)}</a></p>'
                for qid, text in questions
            )
            body.append(f'<div class="fd"><h4>Уточняющий вопрос</h4>{inner}</div>')
        if f.get("recommendation"):
            body.append(f'<div class="fd"><h4>Как исправить</h4><p>{_e(f["recommendation"])}</p></div>')
        extra = []
        reqs = _as_list(f.get("req_ids"))
        if reqs:
            extra.append(f"Требования: {self.links(reqs)}")
        if f.get("merged_from"):
            extra.append(f"Объединено из: {_e(', '.join(str(x) for x in _as_list(f['merged_from'])))}")
        if f.get("source") or f.get("stage"):
            extra.append(f"Источник находки: {_e(' / '.join(str(f[k]) for k in ('source', 'stage') if f.get(k)))}")
        for note in _as_list(f.get("notes")):
            extra.append(_e(note))
        if extra:
            body.append('<p class="small muted">' + "<br>".join(extra) + "</p>")
        unverified = sum(1 for g in groups.values() for e in g if not self.ev.items[e].ok)
        warn = ""
        if unverified:
            warn = f'<span class="warn small"><span aria-hidden="true">⚠</span> неподтверждённых опор: {unverified}</span>'
        search = " ".join(
            [fid, str(f.get("title") or ""), str(f.get("impact") or ""), str(f.get("blocked_decision") or "")]
            + [self.ev.items[e].quote for g in groups.values() for e in g]
        ).lower()
        return (
            f'<li><article class="fc sev-{sev}" id="{finding_anchor(fid)}" data-fid="{_e(fid)}" data-sev="{sev}" '
            f'data-crit="{_e(criterion or "")}" data-status="{_e(status)}" data-kind="{_e(kind)}" '
            f'data-blocks="{_e(" ".join(targets))}" data-search="{_e(search)}">'
            f'<h3 class="fc-h"><button type="button" class="fc-toggle" aria-expanded="true" aria-controls="fd-{anchor_slug(fid)}">'
            f'{self.sev_badge(sev)} <span class="fc-id">{_e(fid)}</span> '
            f'<span class="fc-title">{_e(f.get("title") or "Без названия")}</span></button></h3>'
            f'<p class="fc-meta">{status_html} {block_html} {meta_html}'
            f'{f" · <span class=fc-loc>{_e(loc_line)}</span>" if loc_line else ""} {warn}</p>'
            f'<div class="fc-body" id="fd-{anchor_slug(fid)}">{"".join(body)}</div>'
            "</article></li>"
        )

    def _hint_covered(self, hint: Mapping[str, Any], groups: Mapping[str, list[str]]) -> bool:
        """Подсказка уже превращена в подтверждённую опору — не дублировать."""
        q = hint.get("quote")
        return any(self.ev.items[e].quote == q and self.ev.items[e].ok for g in groups.values() for e in g)

    def witness_html(self, fid: str, w: Mapping[str, Any]) -> str:
        groups = self.f_ev[fid]

        def side(letter: str, outcome: Any) -> str:
            quotes = "".join(self.ev_button(self.ev.items[e], side=letter, context=60) for e in groups[letter])
            if not quotes:
                quotes = '<p class="warn small">Цитата этой стороны не приложена.</p>'
            return (
                f'<div class="w-side w-{letter}"><h5><span class="side-tag" aria-hidden="true">{letter.upper()}</span> '
                f"Исход {letter.upper()}</h5><p>{_e(outcome) if outcome else '—'}</p>{quotes}</div>"
            )

        return (
            '<div class="witness"><h4>Конфликт: один вход, два несовместимых исхода</h4>'
            f'<p class="w-in"><b>Вход.</b> {_e(w.get("input") or "—")}</p>'
            f'<div class="w-sides">{side("a", w.get("outcome_a"))}{side("b", w.get("outcome_b"))}</div></div>'
        )

    def findings_pane(self) -> str:
        ordered = sorted(self.findings, key=lambda f: SEVERITY_ORDER.index(self.sev_of[f["id"]]))
        counts = {k: sum(1 for f in self.findings if self.sev_of[f["id"]] == k) for k in SEVERITY_ORDER}
        crits: list[str] = []
        for f in self.findings:
            c = f.get("criterion")
            if c not in (None, "") and str(c) not in crits:
                crits.append(str(c))
        crit_opts = "".join(
            f'<option value="{_e(c)}">{_e(self.crit(c))}</option>' for c in sorted(crits, key=lambda c: self.crit(c))
        )
        sev_boxes = "".join(
            f'<label class="chk sev-{k}"><input type="checkbox" name="sev" value="{k}" checked> '
            f'<span aria-hidden="true">{SEVERITY[k][1]}</span> {SEVERITY[k][2]} <span class="cnt">{counts[k]}</span></label>'
            for k in SEVERITY_ORDER
        )
        disabled = "" if self.findings else " disabled"
        filters = (
            f'<form class="filters" id="filters" aria-label="Фильтры замечаний"><fieldset{disabled}>'
            '<legend class="sr-only">Фильтры</legend>'
            f'<div class="f-sev" role="group" aria-label="Серьёзность">{sev_boxes}</div>'
            '<div class="f-row">'
            f'<label>Критерий <select name="crit"><option value="">Все критерии</option>{crit_opts}</select></label>'
            '<label>Статус <select name="status"><option value="">Все</option>'
            '<option value="confirmed">Подтверждено</option><option value="needs_review">Требует проверки</option></select></label>'
            '<label>Блокирует <select name="blocks"><option value="">Неважно</option>'
            '<option value="development">разработку</option><option value="testing">тестирование</option></select></label>'
            '<label class="f-q">Поиск <input type="search" name="q" autocomplete="off" placeholder="ID, текст, цитата"></label>'
            '<button type="reset" class="btn">Сбросить</button>'
            "</div></fieldset></form>"
        )
        if self.findings:
            cards = "".join(self.finding_card(f) for f in ordered)
            listing = (
                f'<p class="f-count" id="f-count" role="status">Показано {len(self.findings)} из {len(self.findings)}</p>'
                f'<ol class="f-list" id="f-list">{cards}</ol>'
                '<div class="empty" id="f-empty" hidden><p>Нет замечаний, подходящих под фильтры.</p>'
                '<button type="button" class="btn" id="f-reset">Сбросить фильтры</button></div>'
            )
        elif self.run.get("status") == "complete":
            listing = (
                '<div class="empty" id="f-none"><p><strong>Замечаний нет.</strong> '
                f"Проверено блоков документа: {len(self.blocks_list)}.</p></div>"
            )
        else:
            listing = (
                '<div class="empty empty-warn" id="f-none"><p><strong>Замечаний нет, но прогон неполный.</strong> '
                "Отсутствие замечаний не подтверждено: часть проверок не выполнена.</p></div>"
            )
        return (
            '<section class="pane pane-findings" id="findings-pane" aria-labelledby="fp-h" data-pane="findings">'
            f'<div class="pane-head"><h2 id="fp-h">Замечания <span class="cnt">{len(self.findings)}</span></h2>'
            f"{filters}</div>"
            f'<div class="f-scroll" id="f-scroll">{listing}</div>'
            "</section>"
        )

    def workspace(self) -> str:
        return (
            '<section id="workspace" class="ws" aria-label="Ревью: документ и замечания" data-view="findings">'
            '<div class="ws-switch" role="group" aria-label="Показать панель">'
            '<button type="button" class="btn" data-view="findings" aria-pressed="true">Замечания</button>'
            '<button type="button" class="btn" data-view="doc" aria-pressed="false">Документ</button></div>'
            f"{self.document_pane()}{self.findings_pane()}"
            "</section>"
        )

    # ------------------------------------------------------------ other sections
    def requirements_section(self) -> str:
        if not self.requirements:
            return self.section("requirements", "Требования", "", empty="Список требований пуст.")
        by_req: dict[str, list[str]] = {}
        for f in self.findings:
            for r in _as_list(f.get("req_ids")):
                by_req.setdefault(str(r), []).append(f["id"])
        rows = []
        for req in self.requirements:
            rid = str(req.get("id"))
            evs = "".join(self.ev_button(self.ev.items[e]) for e in self.req_ev.get(rid, []))
            rs = str(req.get("review_status") or "")
            rs_html = self.value(rs, "review_status") if rs else "—"
            if req.get("review_reason"):
                rs_html += f'<br><span class="small muted">{_e(req["review_reason"])}</span>'
            rows.append(
                f'<tr id="{requirement_anchor(rid)}"><th scope="row">{_e(rid)}</th>'
                f'<td>{_e(req.get("source_id") or "—")}</td>'
                f'<td><span class="pre">{_e(req.get("text") or "")}</span>{f"<div class=ev-list>{evs}</div>" if evs else ""}</td>'
                f"<td>{rs_html}</td>"
                f'<td>{self.links(req.get("block_ids"))}</td><td>{self.links(by_req.get(rid, []))}</td></tr>'
            )
        table = (
            '<div class="tbl-wrap" role="region" aria-label="Требования" tabindex="0"><table>'
            '<caption class="sr-only">Нарезка требований</caption><thead><tr>'
            '<th scope="col">ID</th><th scope="col">ID в документе</th><th scope="col">Формулировка</th>'
            '<th scope="col">Проверка</th><th scope="col">Блоки</th><th scope="col">Замечания</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
        )
        return self.section("requirements", f"Требования ({len(self.requirements)})", table, empty="")

    def decision_html(self, d: Mapping[str, Any], fp: str) -> str:
        src = str(d.get("source_sha256") or "")
        state = _decision_state(self.r, d, fp)
        stale = state in ("other_version", "other_question")
        head = {
            "other_version": '<span class="warn small"><span aria-hidden="true">⚠</span> Ответ дан к другой версии документа '
            f"(sha256 {_e(src[:12])}…): в этом прогоне он не учтён.</span>",
            "other_question": '<span class="warn small"><span aria-hidden="true">⚠</span> Ответ из файла относится к другому '
            "вопросу с тем же Q-ID (отпечаток вопроса не совпал): к этому вопросу не применён.</span>",
            "ok": '<span class="small"><span aria-hidden="true">✓</span> Ответ учтён при этом прогоне (файл --answers), '
            "отпечаток вопроса совпал:</span>",
            "qid_only": '<span class="small"><span aria-hidden="true">✓</span> Ответ учтён при этом прогоне (файл --answers). '
            "Связь с вопросом сверена только по Q-ID: убедитесь, что ответ относится к этому вопросу.</span>",
        }[state]
        edits = []
        for ed in _dicts(d.get("edits")):
            b = str(ed.get("block_id") or "")
            edits.append(
                f"<li>{self.link(b)}: <del>{_e(ed.get('old') or '')}</del> → <ins>{_e(ed.get('new') or '')}</ins></li>"
            )
        edits_html = (
            '<p class="small muted">Предложенные правки (в исходный документ не внесены, применяет живое приложение):</p>'
            f'<ul class="edits">{"".join(edits)}</ul>'
            if edits
            else ""
        )
        note = f'<p class="small muted">{_e(d["note"])}</p>' if d.get("note") else ""
        return (
            f'<div class="ans-done{" ans-stale" if stale else ""}">{head}'
            f'<p class="pre">{_e(d.get("answer") or "")}</p>{note}{edits_html}</div>'
        )

    def unattached_html(self) -> str:
        if not self.dec_unattached:
            return ""
        rows = "".join(
            f"<li><b>{_e(d.get('question_id'))}</b> — {_e(reason)}."
            f'<p class="pre">{_e(d.get("answer") or "")}</p>'
            f'<p class="small muted">source_sha256 {_e(str(d.get("source_sha256") or "—")[:12])}…'
            f'{"; правок: " + str(len(_dicts(d.get("edits")))) if _dicts(d.get("edits")) else ""}</p></li>'
            for d, reason in self.dec_unattached
        )
        return (
            '<div class="banner banner-warn" id="ans-unattached" role="region" aria-labelledby="ans-unattached-h">'
            '<h3 id="ans-unattached-h">Ответы из --answers без вопроса в этом прогоне</h3>'
            '<p class="small">Прогон учёл файл ответов, но заново построил вопросы, и эти ответы не относятся ни к одному '
            "из них. Ни к какому вопросу ниже они не приписаны; проверьте, учтено ли решение в тексте документа.</p>"
            f'<ul class="orphans">{rows}</ul></div>'
        )

    def questions_section(self) -> str:
        if not self.questions:
            return self.section("questions", "Открытые вопросы", self.unattached_html(), empty="Уточняющих вопросов нет.")
        items = []
        for i, q in enumerate(self.questions):
            qid = _question_id(q, i)
            slug = anchor_slug(qid)
            fp = self.qfp[qid]
            done_html = "".join(self.decision_html(d, fp) for d in self.decisions.get(qid, []))
            options = [str(o) for o in _as_list(q.get("options")) if o not in (None, "")]
            opt_html = ""
            if options:
                opt_html = (
                    f'<div class="opts" role="group" aria-label="Варианты ответа на {_e(qid)}">'
                    '<span class="small muted">Варианты:</span> '
                    + "".join(
                        f'<button type="button" class="btn opt" data-qid="{_e(qid)}" data-opt="{_e(o)}">{_e(o)}</button>'
                        for o in options
                    )
                    + "</div>"
                )
            refs = [f"Замечания: {self.links(_question_findings(q))}"]
            if q.get("affected_req_ids"):
                refs.append(f"Требования: {self.links(q['affected_req_ids'])}")
            items.append(
                f'<li><article class="qa" id="{question_anchor(qid)}" data-qid="{_e(qid)}">'
                f'<h3><span class="q-id">{_e(qid)}</span> <span class="pre">{_e(_question_text(q))}</span></h3>'
                f'<p class="small">{" · ".join(refs)}</p>'
                f"{done_html}{opt_html}"
                f'<label class="ans-l" for="ans-{slug}">Черновик ответа на {_e(qid)} '
                '<span class="small muted">(хранится только в этом браузере, документ не меняет)</span></label>'
                f'<textarea id="ans-{slug}" class="ans" data-qid="{_e(qid)}" data-qfp="{fp}" rows="3">\n</textarea>'
                "</article></li>"
            )
        tools = (
            '<div class="ans-tools" id="ans-tools">'
            '<p class="banner banner-info" id="ans-note" role="note">Черновики ответов не меняют исходный документ, '
            "вердикт и статусы замечаний. Черновик привязан к тексту вопроса, а не к его номеру: в другом прогоне "
            "Q-01 может означать другой вопрос. Чтобы учесть ответы, выгрузите их в Markdown и запустите проверку "
            f'заново с <code>--answers</code>. Документ: <code title="{_e(self.doc_id)}">sha256 {_e(self.doc_id[:12])}…</code></p>'
            '<div class="banner banner-warn" id="ans-orphans" role="region" aria-labelledby="ans-orphans-h" hidden>'
            '<h3 id="ans-orphans-h">Черновики к вопросам, которых нет в этом отчёте</h3>'
            '<p class="small">Эти ответы сохранены в браузере для других вопросов этого документа и сюда не подставлены. '
            "Если ответ подходит к вопросу этого прогона, перенесите его вручную.</p>"
            '<ul id="ans-orphans-list" class="orphans"></ul></div>'
            '<p class="small" id="ans-status" role="status"></p>'
            '<div class="btns"><button type="button" class="btn btn-pri" id="ans-export">Выгрузить ответы (.md)</button>'
            '<button type="button" class="btn" id="ans-copy">Скопировать Markdown</button>'
            '<button type="button" class="btn" id="ans-clear">Очистить черновик</button></div>'
            '<details id="ans-md-box"><summary>Показать Markdown для ручного копирования</summary>'
            '<label class="sr-only" for="ans-md">Markdown ответов</label>'
            '<textarea id="ans-md" readonly rows="10">\n</textarea></details></div>'
        )
        open_q = sum(1 for qid, fp in self.qfp.items() if not _report_answer(self.r, qid, fp))
        return self.section(
            "questions",
            f"Открытые вопросы ({open_q} из {len(self.questions)})",
            self.unattached_html() + tools + f'<ol class="qa-list">{"".join(items)}</ol>',
            empty="",
        )

    def checklist_section(self) -> str:
        rows = _dicts(self.r.get("checklist"))
        keys = ["id", "text", "available", "checked", "note", "finding_ids", "evidence"]
        keys = [k for k in keys if any(k in r for r in rows)] + sorted({k for r in rows for k in r} - set(keys))
        inner = self.table(rows, caption="Чек-лист ревью требований", row_anchor="check", keys=keys)
        return self.section("checklist", "Чек-лист ревью требований", inner, empty="Чек-лист не заполнен в этом прогоне.")

    def coverage_section(self) -> str:
        cov = self.r.get("coverage")
        rows = _dicts(cov)
        inner = ""
        if rows:
            stat: dict[str, int] = {}
            for r in rows:
                stat[str(r.get("status"))] = stat.get(str(r.get("status")), 0) + 1
            inner += (
                '<ul class="stats stats-cov">'
                + "".join(f"<li><b>{n}</b> {_e(VALUE_LABELS.get(k, k))}</li>" for k, n in stat.items())
                + "</ul>"
            )
            keys = ["req_id", "obligation", "acceptance_ids", "status", "explanation", "evidence", "hints"]
            keys = [k for k in keys if any(k in r for r in rows)]
            inner += self.table(rows, caption="Покрытие требований критериями приёмки", keys=keys)
        elif isinstance(cov, Mapping) and cov:
            inner += self.kv((HEADER_LABELS.get(k, k), self.value(v, k)) for k, v in cov.items())
        checks = _dicts(self.r.get("checks"))
        if checks:
            stat = {}
            for c in checks:
                stat[str(c.get("status"))] = stat.get(str(c.get("status")), 0) + 1
            summary = ", ".join(f"{VALUE_LABELS.get(k, k)} — {n}" for k, n in stat.items())
            keys = [k for k in ("req_id", "criterion", "status", "reason", "finding_ids", "source") if any(k in c for c in checks)]
            inner += (
                f'<details class="checks"><summary>Выполненные проверки ({len(checks)}: {_e(summary)})</summary>'
                f'{self.table(checks, caption="Проверки требований по критериям", keys=keys)}</details>'
            )
        return self.section("coverage", "Покрытие проверки", inner, empty="Данные о покрытии не переданы.")

    def diff_section(self) -> str:
        diff = self.r.get("diff")
        if not isinstance(diff, Mapping) or not diff:
            return self.section(
                "diff", "Сравнение версий", "", empty="Сравнение с предыдущим отчётом не запускалось (--compare)."
            )
        prev = diff.get("previous") if isinstance(diff.get("previous"), Mapping) else {}
        cur = diff.get("current") if isinstance(diff.get("current"), Mapping) else {}
        head = self.kv(
            [
                ("Прошлая версия", f'<code>{_e(str(prev.get("source_sha256") or "—")[:12])}…</code> {_e(prev.get("run_id") or "")}'),
                ("Текущая версия", f'<code>{_e(str(cur.get("source_sha256") or "—")[:12])}…</code> {_e(cur.get("run_id") or "")}'),
            ]
        )
        counts = []
        rows = []
        for key, label, glyph in DIFF_OLD:
            entries = _dicts(diff.get(key))
            counts.append(f'<li><b>{len(entries)}</b> <span aria-hidden="true">{glyph}</span> {label.lower()}</li>')
            for en in entries:
                evs = " ".join(self.ev_button(self.ev.add(x)) for x in _dicts(en.get("evidence")))
                rows.append(
                    f'<tr><td><span class="dst dst-{key}"><span aria-hidden="true">{glyph}</span> {label}</span></td>'
                    f"<td>{_e(', '.join(str(x) for x in _as_list(en.get('old_ids'))) or '—')}</td>"
                    f"<td>{self.links(en.get('new_ids'))}</td>"
                    f"<td>{_e(en.get('reason') or '')}{f'<div class=ev-list>{evs}</div>' if evs else ''}</td></tr>"
                )
        new = _dicts(diff.get("introduced"))
        counts.append(f'<li><b>{len(new)}</b> <span aria-hidden="true">+</span> новых</li>')
        old_html = (
            '<div class="tbl-wrap" role="region" aria-label="Замечания прошлой версии" tabindex="0"><table>'
            '<caption class="sr-only">Статусы замечаний прошлой версии</caption><thead><tr>'
            '<th scope="col">Статус</th><th scope="col">Было (ID прошлого отчёта)</th>'
            '<th scope="col">Сейчас</th><th scope="col">Пояснение</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            if rows
            else "<p class=muted>Замечаний прошлой версии нет.</p>"
        )
        new_items = []
        for en in new:
            ids = _as_list(en.get("new_ids"))
            titles = [next((str(f.get("title") or "") for f in self.findings if f["id"] == str(i)), "") for i in ids]
            reason = f' <span class="small">({_e(en["reason"])})</span>' if en.get("reason") else ""
            new_items.append(f"<li>{self.links(ids)} {_e('; '.join(t for t in titles if t))}{reason}</li>")
        extra = ""
        if diff.get("impacted_req_ids"):
            extra += f"<p>Затронутые требования: {self.links(diff['impacted_req_ids'])}</p>"
        warns = [_warning_text(w) for w in _as_list(diff.get("warnings"))]
        if warns:
            extra += "<ul>" + "".join(f"<li class=warn>{_e(w)}</li>" for w in warns) + "</ul>"
        inner = (
            f'{head}<ul class="stats stats-diff">{"".join(counts)}</ul>'
            f"<h3>Замечания прошлой версии</h3>{old_html}"
            f"<h3>Новые замечания ({len(new_items)})</h3>"
            + (f'<ul class="new-list">{"".join(new_items)}</ul>' if new_items else "<p class=muted>Новых замечаний нет.</p>")
            + extra
        )
        return self.section("diff", "Сравнение версий", inner, empty="")

    def tests_section(self) -> str:
        rows = _dicts(self.r.get("test_cases"))
        keys = ["id", "precondition", "action", "expected", "req_ids", "open_question_id"]
        keys = [k for k in keys if any(k in r for r in rows)] + sorted({k for r in rows for k in r} - set(keys))
        inner = self.table(rows, caption="Черновик тест-кейсов", row_anchor="tc", keys=keys)
        if inner:
            inner = '<p class="small muted">Черновик для тестировщика: проверьте ожидаемые результаты по требованиям.</p>' + inner
        return self.section("test-cases", "Черновик тест-кейсов", inner, empty="Тест-кейсы не сформированы.")

    def facts_section(self) -> str:
        facts = _dicts(self.r.get("facts"))
        if not facts:
            return self.section("facts", "Факты документа", "", empty="Таблица фактов не передана.")
        keys = ["id", "subject", "field", "value", "unit", "type", "direction", "range", "req_ids", "evidence"]
        keys = [k for k in keys if any(k in r for r in facts)]
        inner = self.table(facts, caption="Факты документа", keys=keys)
        return self.section("facts", f"Факты документа ({len(facts)})", inner, empty="")

    def run_section(self) -> str:
        run = self.run
        src = str(run.get("source_sha256") or "")
        mismatch = ""
        if self.doc.get("id") and src and self.doc.get("id") != src:
            mismatch = (
                '<p class="banner banner-run" role="note"><strong>Хеш документа не совпадает с хешем источника прогона.</strong> '
                "Отчёт мог быть собран по другой редакции файла.</p>"
            )
        calls = run.get("calls")
        if isinstance(calls, Mapping):
            calls_txt = (
                f"физических {calls.get('physical', '—')}, из кэша {calls.get('cache_hits', '—')}, "
                f"повторов {calls.get('retries', '—')}, ошибок {calls.get('failed', '—')}"
            )
        else:
            calls_txt = calls
        tokens = run.get("tokens")
        tokens_txt = (
            f"вход {tokens.get('input', '—')}, выход {tokens.get('output', '—')}" if isinstance(tokens, Mapping) else tokens
        )
        budget = run.get("budget") if isinstance(run.get("budget"), Mapping) else {}
        budget_txt = ""
        if budget:
            budget_txt = f"вызовов ≤ {budget.get('max_calls', '—')}, секунд ≤ {budget.get('max_seconds', '—')}"
            if budget.get("exhausted"):
                budget_txt += f"; исчерпан: {budget.get('reason') or 'да'}"
        models = ", ".join(str(m) for m in _as_list(run.get("models_seen")))
        rows = [
            ("Документ", self.doc.get("title")),
            ("Формат", self.doc.get("format")),
            ("Файл", _first(self.doc, "source_name", default=run.get("source_name"))),
            ("SHA-256 документа", self.doc.get("id")),
            ("SHA-256 источника прогона", src),
            ("Блоков", len(self.blocks_list)),
            ("ID прогона", run.get("run_id")),
            ("Родительский прогон", run.get("parent_run_id")),
            ("Версия агента", run.get("agent_version")),
            ("Коммит агента", run.get("agent_commit")),
            ("Провайдер", run.get("provider")),
            ("Модель (фактическая)", run.get("model")),
            ("Модель (запрошенная)", run.get("requested_model")),
            ("Модели в ответах", models),
            ("Режим", RUN_MODE.get(str(run.get("mode")), run.get("mode"))),
            ("Начало", run.get("started_at")),
            ("Окончание", run.get("finished_at")),
            ("Длительность, с", run.get("duration_s")),
            ("Вызовы модели", calls_txt),
            ("Токены", tokens_txt),
            ("Бюджет", budget_txt),
            ("Контекст", run.get("context_policy")),
            ("Статус", RUN_STATUS.get(str(run.get("status")), run.get("status"))),
            ("Схема отчёта", self.r.get("schema_version")),
        ]
        dl = self.kv((k, f'<span class="pre">{_e(v)}</span>') for k, v in rows if v not in (None, "", []))
        parts = [mismatch, dl]
        reasons = [str(x) for x in _as_list(run.get("status_reasons"))]
        if reasons:
            parts.append("<h3>Причины статуса</h3><ul>" + "".join(f"<li>{_e(x)}</li>" for x in reasons) + "</ul>")
        stages = _dicts(run.get("stages"))
        if stages:
            keys = [k for k in ("name", "status", "calls", "cache_hits", "retries", "model", "duration_s", "reason", "implementation") if any(k in s for s in stages)]
            parts.append("<h3>Этапы</h3>" + self.table(stages, caption="Этапы прогона", keys=keys))
        modules = run.get("modules")
        if isinstance(modules, Mapping) and modules:
            parts.append("<h3>Модули</h3>" + self.kv((str(k), _e(v)) for k, v in modules.items()))
        audit = run.get("evidence_audit")
        if isinstance(audit, Mapping):
            labels = {"checked": "Проверено", "confirmed": "Подтверждено", "ambiguous": "Неоднозначно", "rejected": "Отклонено", "note": "Учёт"}
            parts.append("<h3>Аудит опор (из прогона)</h3>" + self.kv((labels.get(k, k), _e(v)) for k, v in audit.items()))
        st = self.ev.stats()
        rejected = [ev for ev in self.ev.items.values() if not ev.ok]
        rej_html = "".join(
            f"<li>{_e(ev.id)}: блок {self.link(ev.block_id)} — {_e(ev.reason)}"
            f"{' (' + ', '.join(ev.finding_ids) + ')' if ev.finding_ids else ''}</li>"
            for ev in rejected
        )
        parts.append(
            "<h3>Проверка опор при сборке HTML</h3>"
            f'<p>Опор: {st["total"]}; совпали с текстом блока: {st["ok"]}; не подтверждены и не подсвечены: {st["rejected"]}.</p>'
            f'{f"<ul>{rej_html}</ul>" if rej_html else ""}'
            '<p id="dom-check" role="status" class="small">Проверка подсветки в браузере не выполнялась (нужен JavaScript).</p>'
        )
        rejected_c = _dicts(self.r.get("rejected"))
        if rejected_c:
            items = "".join(
                f"<li>{_e(_first(r.get('candidate'), 'title', default='кандидат'))} — {_e(r.get('reason') or '')}"
                f"{' (' + _e(r['stage']) + ')' if r.get('stage') else ''}</li>"
                for r in rejected_c
            )
            parts.append(f"<details><summary>Отклонено при проверке ({len(rejected_c)})</summary><ul>{items}</ul></details>")
        excluded = _dicts(self.r.get("excluded"))
        if excluded:
            items = "".join(f"<li>{self.links(x.get('block_ids'))} — {_e(x.get('reason') or '')}</li>" for x in excluded)
            parts.append(f"<details><summary>Исключено из проверки ({len(excluded)})</summary><ul>{items}</ul></details>")
        warns = self.warnings_all()
        if warns:
            parts.append("<h3>Предупреждения</h3><ul>" + "".join(f"<li>{_e(w)}</li>" for w in warns) + "</ul>")
        parts.append(
            f'<p class="small muted">Файл собран {GENERATOR}. Открывается без сети и сервера. '
            "Правки документа выполняет живое приложение.</p>"
        )
        return self.section("run", "Паспорт прогона", "".join(parts), empty="")

    # ------------------------------------------------------------ data for JS
    def view_model(self) -> dict[str, Any]:
        findings = {}
        for f in self.findings:
            fid = f["id"]
            g = self.f_ev[fid]
            findings[fid] = {
                "sev": self.sev_of[fid],
                "title": str(f.get("title") or ""),
                "a": g["a"],
                "b": g["b"],
                "ev": g["ev"],
                "blocks": self.f_blocks[fid],
                "anchor": finding_anchor(fid),
            }
        evs = {
            ev.id: {
                "b": ev.block_id,
                "s": ev.start,
                "e": ev.end,
                "q": ev.quote,
                "ok": ev.ok,
                "f": ev.finding_ids,
                "anchor": block_anchor(ev.block_id),
                "place": _ev_place(self.blocks[ev.block_id], ev.start) if ev.block_id in self.blocks else "",
            }
            for ev in self.ev.items.values()
        }
        return {
            "v": 1,
            "generator": GENERATOR,
            "doc": {"id": self.doc_id, "title": str(self.doc.get("title") or "")},
            "run": {"status": self.run.get("status")},
            "findings": findings,
            "ev": evs,
            "answers": {
                "format": ANSWERS_FORMAT,
                "draftFormat": DRAFT_FORMAT,
                "legacyFormat": LEGACY_DRAFT_FORMAT,
                "storageKey": answers_storage_key(self.doc_id),
                "legacyKey": legacy_answers_storage_key(self.doc_id),
                "runId": str(self.run.get("run_id") or ""),
                "header": _answers_header(self.r),
                "questions": [
                    {
                        "id": _question_id(q, i),
                        "fp": self.qfp[_question_id(q, i)],
                        "prompt": _one_line(_question_text(q)),
                        "head": _answers_question_head(q, i, self.qfp[_question_id(q, i)]),
                        "reportAnswer": _report_answer(self.r, _question_id(q, i), self.qfp[_question_id(q, i)]),
                    }
                    for i, q in enumerate(self.questions)
                ],
            },
        }

    def page(self) -> str:
        css = (ASSETS_DIR / "report.css").read_text(encoding="utf-8")
        js = (ASSETS_DIR / "report.js").read_text(encoding="utf-8")
        body = (
            '<a class="skip" href="#workspace">Перейти к ревью</a>'
            f"{self.header()}<main>{self.summary()}{self.workspace()}"
            f"{self.requirements_section()}{self.questions_section()}{self.checklist_section()}"
            f"{self.coverage_section()}{self.diff_section()}{self.tests_section()}{self.facts_section()}"
            f"{self.run_section()}</main>"
            '<div id="live" class="sr-only" aria-live="polite"></div>'
        )
        data = _json_for_script(self.view_model())
        csp = (
            "default-src 'none'; img-src data:; "
            f"style-src {_csp_hash(css)}; script-src {_csp_hash(js)}; "
            "base-uri 'none'; form-action 'none'"
        )
        title = f"Ревью ТЗ — {self.doc.get('title') or 'документ'}"
        return (
            "<!doctype html>\n"
            '<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
            f'<meta name="generator" content="{GENERATOR}">\n'
            f'<meta name="bcc-review:generator-sha256" content="{generator_fingerprint()}">\n'
            f'<meta name="bcc-review:document-sha256" content="{_e(self.doc_id)}">\n'
            f'<meta name="bcc-review:schema-version" content="{_e(self.r.get("schema_version") or "")}">\n'
            f'<meta name="bcc-review:run-id" content="{_e(self.run.get("run_id") or "")}">\n'
            f"<title>{_e(title)}</title>\n<style>{css}</style>\n</head>\n"
            f"<body>\n{body}\n"
            f'<script type="application/json" id="bcc-data">{data}</script>\n'
            f"<script>{js}</script>\n</body>\n</html>\n"
        )


def generator_fingerprint() -> str:
    """SHA-256 кода генератора (html.py и html_assets): одинаков у всех HTML одной версии генератора."""
    h = hashlib.sha256()
    for path in (Path(__file__), ASSETS_DIR / "report.css", ASSETS_DIR / "report.js"):
        h.update(path.read_bytes())
    return h.hexdigest()


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


# --------------------------------------------------------------------------- #
# Публичные функции
# --------------------------------------------------------------------------- #


def render_html(report: Any, *, pdf_href: str | None = None) -> str:
    """Строит текст автономного HTML-отчёта."""
    return _Renderer(_to_plain(report), pdf_href=pdf_href).page()


def write_html(report: Any, output_path: str | Path, *, pdf_href: str | None = None) -> Path:
    """Пишет автономный HTML-отчёт и возвращает путь к файлу.

    ``pdf_href`` — необязательная относительная ссылка на оригинальный PDF
    (артефакт №14). Без неё номера страниц всё равно видны у каждого блока.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_html(report, pdf_href=pdf_href)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path.resolve()


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m bcc_review.exports.html",
        description="Собрать автономный HTML-отчёт из report.json",
    )
    parser.add_argument("report", help="путь к report.json (Report контракта v1)")
    parser.add_argument("output", help="путь к .html")
    parser.add_argument("--pdf-href", default=None, help="относительная ссылка на оригинальный PDF")
    args = parser.parse_args(list(argv) if argv is not None else None)
    out = write_html(Path(args.report), args.output, pdf_href=args.pdf_href)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
