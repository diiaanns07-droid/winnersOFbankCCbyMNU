"""Экспорт в Word: нативные комментарии рецензента в копии исходного DOCX (№03).

Контракт: ``write_docx(report, input_path, output_path) -> Path``.

* Исходный файл не меняется. Аннотации пишутся в отдельную копию, по умолчанию
  ``<имя отчёта>.annotated.docx`` (см. :func:`default_output_path`).
* Перед записью SHA-256 входа сверяется с ``report.document.id`` и
  ``report.run.source_sha256``. Если файл другой версии, копия не создаётся и
  поднимается :class:`SourceMismatchError` с объяснением на русском. Тот же
  результат без исключения возвращает :func:`annotate_docx`.
* Комментарий ставится на диапазон из ``Evidence`` ``{block_id, start, end, quote}``.
  Цитата сверяется с ``block.text[start:end]``. Run на границе цитаты разрезается
  с глубокой копией ``w:rPr``, затем вызывается документированный
  ``python-docx Document.add_comment``. Получается пара
  ``w:commentRangeStart``/``w:commentRangeEnd`` и ``w:commentReference``.
* Если границу нельзя разрезать без потери форматирования или смысла (поле Word,
  формула, run с рисунком или ``w:sym``), привязка расширяется до ближайшего
  доказанного участка. Точность прямо названа в комментарии и в результате:
  ``exact`` -- точно по цитате, ``run`` -- до границ неделимого run,
  ``paragraph`` -- абзац(ы) с цитатой целиком, ``cell`` -- ячейка целиком.
  Для сноски и текстового поля комментарий ставится на абзац, где стоит знак
  сноски или рамка: Word не комментирует эти места напрямую.
* Уже имеющиеся комментарии, форматирование и текст сохраняются. После записи
  копия открывается повторно и проверяется (см. ``AnnotationResult.checks``).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from docx.document import Document as _DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run

from bcc_review.readers.docx import (
    MAIN_PART,
    BlockSpec,
    DocxLayout,
    DocxReadError,
    ParagraphRef,
    locate,
    open_docx_bytes,
    scan_paragraph,
)

__all__ = [
    "ARTIFACT_SUFFIX",
    "AnnotationResult",
    "Anchor",
    "Skipped",
    "WordExportError",
    "SourceMismatchError",
    "UnsupportedSourceError",
    "annotate_docx",
    "write_docx",
    "default_output_path",
    "verify_annotated",
    "comment_spans",
    "build_comment_text",
    "DocxReadError",
]

ARTIFACT_SUFFIX = ".annotated.docx"
DEFAULT_AUTHOR = "BCC Review"
DEFAULT_INITIALS = "BCC"
REPORTABLE_STATUSES = (None, "confirmed", "needs_review")

SEVERITY_RU = {"critical": "Критичный", "major": "Существенный", "minor": "Незначительный"}
STATUS_RU = {"confirmed": "подтверждено", "needs_review": "требует проверки"}
READINESS_RU = {"ready": "можно начинать", "not_ready": "нельзя начинать", "unknown": "не определена"}
PRECISION_RU = {
    "exact": "точная, по цитате",
    "run": "расширена до границ неделимого фрагмента",
    "paragraph": "абзац целиком",
    "cell": "ячейка таблицы целиком",
}
_PRECISION_RANK = {"exact": 0, "run": 1, "paragraph": 2, "cell": 3}
SKIP_REASON_RU = {
    "no_evidence": "у замечания нет текстовой опоры",
    "quote_not_found": "цитаты нет в тексте блока",
    "quote_ambiguous": "цитата встречается в блоке несколько раз, координаты её не подтверждают",
    "block_not_found": "блока нет в документе",
    "block_text_mismatch": "текст блока в отчёте не совпадает с документом",
    "quote_is_separator": "цитата состоит только из разделителя",
}
_NOT_PUBLISHED = ("status_not_reportable",)
_ISO = "ISO/IEC/IEEE 29148:2018"
# Подписи кодов критериев контракта (contracts.INDIVIDUAL_CRITERIA / SET_CRITERIA).
CRITERIA_RU = {
    "necessary": f"Необходимость ({_ISO}, 5.2.5)",
    "appropriate": f"Уместность ({_ISO}, 5.2.5)",
    "unambiguous": f"Однозначность ({_ISO}, 5.2.5)",
    "complete": f"Полнота ({_ISO}, 5.2.5)",
    "singular": f"Единичность ({_ISO}, 5.2.5)",
    "feasible": f"Осуществимость ({_ISO}, 5.2.5)",
    "verifiable": f"Проверяемость ({_ISO}, 5.2.5)",
    "correct": f"Корректность ({_ISO}, 5.2.5)",
    "conforming": f"Соответствие шаблону ({_ISO}, 5.2.5)",
    "set_complete": f"Полнота набора ({_ISO}, 5.2.6)",
    "set_consistent": f"Согласованность набора ({_ISO}, 5.2.6)",
    "set_feasible": f"Осуществимость набора ({_ISO}, 5.2.6)",
    "set_comprehensible": f"Понятность набора ({_ISO}, 5.2.6)",
    "set_validatable": f"Возможность валидации набора ({_ISO}, 5.2.6)",
    "ranked": "Ранжирование по важности и стабильности (IEEE 830-1998, 4.3.5)",
    "modifiable": "Модифицируемость (IEEE 830-1998, 4.3.7)",
    "traceable": "Прослеживаемость (IEEE 830-1998, 4.3.8)",
}
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


# ------------------------------------------------------------------ результат


class WordExportError(RuntimeError):
    """Аннотированную копию построить нельзя. ``code`` -- машинный код причины."""

    code = "word_export_error"

    def __init__(self, message: str, result: "AnnotationResult | None" = None) -> None:
        super().__init__(message)
        self.result = result


class SourceMismatchError(WordExportError):
    code = "source_mismatch"


class UnsupportedSourceError(WordExportError):
    code = "unsupported_input"


@dataclass
class Anchor:
    """Комментарий в копии и узел, к которому он привязан."""

    finding_id: str
    block_id: str
    comment_id: int
    precision: str  # exact | run | paragraph | cell
    start: int
    end: int
    quote: str
    ref: str  # структурная ссылка: p16, t2.r3.c3, fn2
    label: str  # «Таблица 2, строка 3, столбец 3 «Ожидаемый результат»»
    path: str  # XPath узла в части part
    part: str = MAIN_PART
    note: str | None = None
    # что комментарий охватывает в сохранённой копии (перечитано из файла после записи):
    # {"block_id", "start", "end", "text"} в координатах block.text
    covered: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Skipped:
    finding_id: str | None
    block_id: str | None
    reason: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class AnnotationResult:
    status: str  # written | source_mismatch | unsupported_input | verification_failed
    input_path: str
    output_path: str | None
    source_sha256: str | None
    expected_sha256: str | None
    message: str
    artifact: str | None = None
    output_sha256: str | None = None
    anchors: list[Anchor] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    summary_comment_id: int | None = None
    comments_before: int = 0
    comments_after: int = 0
    checks: dict[str, Any] = field(default_factory=dict)
    findings_total: int = 0  # публикуемые замечания (confirmed / needs_review)
    evidence_total: int = 0  # их опоры без повторов

    @property
    def counts(self) -> dict[str, int]:
        """Счётчик: сколько замечаний и опор отмечено в тексте и сколько пропущено."""
        return {
            "findings": self.findings_total,
            "findings_anchored": len({a.finding_id for a in self.anchors}),
            "evidence": self.evidence_total,
            "evidence_anchored": len(self.anchors),
            "comments_added": len(self.anchors),
            "skipped": len([s for s in self.skipped if s.reason not in _NOT_PUBLISHED]),
        }

    def unanchored_ru(self) -> list[str]:
        """«F-C — у замечания нет текстовой опоры» для замечаний без единого комментария."""
        anchored = {a.finding_id for a in self.anchors}
        out, seen = [], set()
        for s in self.skipped:
            if s.reason in _NOT_PUBLISHED or s.finding_id in anchored or s.finding_id in seen:
                continue
            seen.add(s.finding_id)
            out.append(f"{s.finding_id} — {SKIP_REASON_RU.get(s.reason, s.reason)}")
        partial = sorted({s.finding_id for s in self.skipped if s.finding_id in anchored})
        out += [f"{fid} — отмечена только часть опор" for fid in partial]
        return out

    def counts_ru(self) -> str:
        c = self.counts
        return (f"отмечено {c['findings_anchored']} из {c['findings']} замечаний "
                f"(опор {c['evidence_anchored']} из {c['evidence']})")

    @property
    def complete(self) -> bool:
        """Все опоры публикуемых замечаний получили комментарий."""
        return self.status == "written" and not [s for s in self.skipped
                                                 if s.reason not in ("no_evidence", "status_not_reportable")]

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["complete"] = self.complete
        d["counts"] = self.counts
        return d

    def warnings(self) -> list[dict[str, Any]]:
        """Предупреждения в формате контракта ``{code, message, stage, block_ids}``."""
        if self.status != "written":
            return [{"code": f"docx_export_{self.status}", "message": self.message, "stage": "export_docx",
                     "block_ids": []}]
        out = []
        for s in self.skipped:
            if s.reason in ("no_evidence", "status_not_reportable"):
                continue
            out.append({"code": f"docx_export_{s.reason}", "stage": "export_docx",
                        "message": f"{s.finding_id}: комментарий не поставлен — {s.detail}",
                        "block_ids": [s.block_id] if s.block_id else []})
        if self.counts["skipped"]:  # общий счётчик пропусков, в том числе замечаний без опоры
            out.append({"code": "docx_export_unanchored", "stage": "export_docx",
                        "message": f"В {self.artifact} {self.counts_ru()}; без места в тексте: "
                                   + "; ".join(self.unanchored_ru()) + ".",
                        "block_ids": sorted({s.block_id for s in self.skipped if s.block_id})})
        return out

    def summary_ru(self) -> str:
        if self.status != "written":
            return self.message
        by: dict[str, int] = {}
        for a in self.anchors:
            by[a.precision] = by.get(a.precision, 0) + 1
        parts = ", ".join(f"{PRECISION_RU[k]}: {v}" for k, v in
                          sorted(by.items(), key=lambda kv: _PRECISION_RANK[kv[0]]))
        s = f"В копию {self.artifact} добавлено комментариев: {len(self.anchors)}"
        if parts:
            s += f" ({parts})"
        if self.summary_comment_id is not None:
            s += ", плюс общий комментарий со сводкой"
        if self.skipped:
            s += f". Без привязки: {len(self.skipped)} (" + "; ".join(
                f"{x.finding_id or '—'}: {x.reason}" for x in self.skipped) + ")"
        return s + "."


# ------------------------------------------------------------ чтение отчёта


def _as_dict(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_dict(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return _as_dict(obj.model_dump(mode="json"))
    if hasattr(obj, "to_dict"):
        return _as_dict(obj.to_dict())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _as_dict(dataclasses.asdict(obj))
    if hasattr(obj, "__dict__"):
        return _as_dict(vars(obj))
    return obj


def _text(value: Any) -> str | None:
    """Строка из str, dict (text/action/prompt/...) или списка."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for k in ("text", "action", "prompt", "after", "question", "fix", "value", "name", "title"):
            if isinstance(value.get(k), str) and value[k].strip():
                return value[k].strip()
        return None
    if isinstance(value, (list, tuple)):
        items = [t for t in (_text(v) for v in value) if t]
        return "; ".join(items[:3]) or None
    return str(value)


def _question_and_fix(report: dict[str, Any], finding: dict[str, Any]) -> tuple[str | None, str | None]:
    """Вопрос из ``report.questions[].prompt`` по ``finding_ids``, исправление -- ``recommendation``."""
    fid = finding.get("id")
    question = None
    for q in report.get("questions") or []:
        if isinstance(q, dict) and fid in (q.get("finding_ids") or []):
            question = _text(q.get("prompt") or q.get("question") or q.get("text"))
            options = [o for o in (q.get("options") or []) if isinstance(o, str) and o.strip()]
            if question and options:
                question += " Варианты: " + " / ".join(o.strip().rstrip(".") for o in options[:3]) + "."
            if question:
                break
    if not question:
        question = _text(finding.get("question"))
    fix = None
    for k in ("recommendation", "fix", "suggestion"):
        fix = _text(finding.get(k))
        if fix:
            break
    return question, fix


def _short(s: str, n: int = 90) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build_comment_text(
    finding: dict[str, Any],
    *,
    quote: str,
    precision: str,
    reason: str | None = None,
    question: str | None = None,
    fix: str | None = None,
    other_places: Iterable[str] = (),
) -> str:
    """Текст комментария: ID, серьёзность, последствие, вопрос или исправление, точность."""
    fid = finding.get("id") or "—"
    sev = SEVERITY_RU.get(str(finding.get("severity")), str(finding.get("severity") or "серьёзность не указана"))
    status = STATUS_RU.get(str(finding.get("status")), finding.get("status"))
    lines = [f"[{fid}] {sev}" + (f" · {status}" if status else "")]
    title = _text(finding.get("title"))
    if title:
        lines.append(title)
    crit = _text(finding.get("criterion"))
    if crit:
        lines.append(f"Критерий: {CRITERIA_RU.get(crit, crit)}")
    impact = _text(finding.get("impact"))
    lines.append(f"Последствие: {impact}" if impact else "Последствие: не указано в отчёте")
    blocked = _text(finding.get("blocked_decision"))
    if blocked:
        lines.append(f"Блокирует решение: {blocked}")
    witness = finding.get("witness")
    if isinstance(witness, dict) and witness.get("input"):
        lines.append(f"Сценарий: {_text(witness.get('input'))} → по одному месту: {_text(witness.get('outcome_a'))}; "
                     f"по другому: {_text(witness.get('outcome_b'))}")
    if question:
        lines.append(f"Вопрос автору: {question}")
    if fix:
        lines.append(f"Исправление: {fix}")
    if not question and not fix:
        lines.append(f"Вопрос автору: подтвердите или исправьте формулировку «{_short(quote, 60)}».")
    req_ids = finding.get("req_ids") or []
    if req_ids:
        lines.append("Требования: " + ", ".join(str(r) for r in req_ids))
    others = [o for o in other_places if o]
    if others:
        lines.append("Связанное место: " + "; ".join(others))
    if precision != "exact":
        lines.append(f"Точные слова: «{_short(quote, 120)}»")
    lines.append(f"Привязка: {PRECISION_RU.get(precision, precision)}" + (f" ({reason})" if reason else ""))
    return "\n".join(lines)


def _verdict_lines(report: dict[str, Any]) -> list[str]:
    v = report.get("verdict") or {}
    if not isinstance(v, dict):
        return [f"Вердикт: {_text(v)}"] if v else []

    def word(x: Any) -> str | None:
        if isinstance(x, dict):
            x = x.get("status")
        if isinstance(x, bool):
            return READINESS_RU["ready" if x else "not_ready"]
        return READINESS_RU.get(str(x), _text(x)) if x is not None else None

    out = []
    dev, test = word(v.get("development")), word(v.get("testing"))
    if dev or test:
        out.append(f"Разработка: {dev or '—'} · Тестирование: {test or '—'}")
    actions = v.get("first_actions") or []
    acts = [t for t in (_text(a) for a in (actions if isinstance(actions, list) else [actions])) if t]
    if acts:
        out.append("Первые действия: " + " ".join(f"{i}) {_short(a, 120)}" for i, a in enumerate(acts[:3], 1)))
    return out


# ---------------------------------------------------------- работа с OOXML


def _child_len(child: Any) -> int:
    name = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
    if name == "t":
        return len(child.text or "")
    if name in ("tab", "br", "cr", "noBreakHyphen"):
        return 1
    return 0


def split_run(r: Any, k: int) -> Any:
    """Разрезать ``w:r`` после ``k`` символов текста и вернуть правую часть.

    Обе части получают одинаковый ``w:rPr`` (глубокая копия) и атрибуты run.
    Вызывать только для run, где ``RunSpan.splittable`` истинно и ``0 < k < len``.
    """
    new = OxmlElement("w:r")
    for attr, val in r.attrib.items():
        new.set(attr, val)
    rpr = r.find(qn("w:rPr"))
    if rpr is not None:
        new.append(copy.deepcopy(rpr))
    acc = 0
    moving = False
    for child in [c for c in r if c is not rpr]:
        if moving:
            new.append(child)
            continue
        n = _child_len(child)
        if acc + n <= k:
            acc += n
            continue
        if acc >= k:
            moving = True
            new.append(child)
            continue
        cut = k - acc  # граница внутри w:t
        txt = child.text or ""
        child.text = txt[:cut]
        child.set(_XML_SPACE, "preserve")
        nt = OxmlElement("w:t")
        nt.text = txt[cut:]
        nt.set(_XML_SPACE, "preserve")
        new.append(nt)
        moving = True
        acc += n
    r.addnext(new)
    return new


def _reference_run(comment_id: int) -> Any:
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rpr.append(OxmlElement("w:rStyle", attrs={qn("w:val"): "CommentReference"}))
    r.append(rpr)
    r.append(OxmlElement("w:commentReference", attrs={qn("w:id"): str(comment_id)}))
    return r


def _boundary(p_el: Any, local: int, side: str) -> tuple[Any | None, str, str | None]:
    """Найти run, который начинается (side=start) или кончается (side=end) в ``local``.

    Возвращает ``(w:r | None, точность, причина)``. Делимый run режется.
    """
    for rs in scan_paragraph(p_el).runs:
        if rs.length <= 0:
            continue
        edge = rs.start if side == "start" else rs.end
        inside = rs.start < local < rs.end
        if edge != local and not inside:
            continue
        if rs.kind == "math":
            return None, "paragraph", "граница попадает в формулу OMML"
        if rs.in_field:
            return None, "paragraph", "граница попадает в поле Word, его результат пересчитывается"
        if edge == local:
            return rs.el, "exact", None
        if rs.splittable:
            right = split_run(rs.el, local - rs.start)
            return (right if side == "start" else rs.el), "exact", None
        return rs.el, "run", "run содержит рисунок, символ или иной неделимый элемент"
    return None, "paragraph", "граница не найдена среди run абзаца"


@dataclass
class _Plan:
    mode: str  # runs | paragraphs | point
    precision: str
    reason: str | None
    first: Any
    last: Any
    # Что диапазон обязан охватить в сохранённой копии (координаты block.text блока block_id):
    # span -- ровно этот участок; для precision="run" span=None, и участок должен
    # содержать цитату и лежать внутри bounds.
    block_id: str = ""
    span: tuple[int, int] | None = None
    bounds: tuple[int, int] = (0, 0)


def _fallback(spec: BlockSpec, paras: list[ParagraphRef], first_i: int, last_i: int,
              reason: str | None) -> _Plan:
    precision = "paragraph"
    cells = {p.cell for p in paras[first_i:last_i + 1]}
    if spec.loc.get("anchor") == "row" and len(cells) == 1 and None not in cells:
        cell = next(iter(cells))
        if [p for p in paras if p.cell == cell] == paras[first_i:last_i + 1]:
            precision = "cell"
    lo, hi = paras[first_i].start, paras[last_i].end
    return _Plan("paragraphs", precision, reason, paras[first_i].el, paras[last_i].el, spec.id, (lo, hi), (lo, hi))


def _plan(spec: BlockSpec, start: int, end: int) -> _Plan | None:
    if spec.host is not None and spec.host_paragraph is not None:
        what = "сноска" if spec.loc.get("anchor") == "note" else "текстовое поле"
        reason = f"{what}: Word не ставит комментарий внутрь, привязано к абзацу со знаком"
        hp = spec.host_paragraph
        return _Plan("paragraphs", "paragraph", reason, hp.el, hp.el, spec.host.id, (hp.start, hp.end),
                     (hp.start, hp.end))
    paras = spec.paragraphs
    first_i = next((i for i, p in enumerate(paras) if p.end > start), None)
    last_i = next((i for i in range(len(paras) - 1, -1, -1) if paras[i].start < end), None)
    if first_i is None or last_i is None or first_i > last_i:
        return None
    pf, pl = paras[first_i], paras[last_i]
    s_local = max(start, pf.start) - pf.start
    e_local = min(end, pl.end) - pl.start
    first_r, prec_s, why_s = _boundary(pf.el, s_local, "start")
    if first_r is None:
        return _fallback(spec, paras, first_i, last_i, why_s)
    last_r, prec_e, why_e = _boundary(pl.el, e_local, "end")
    if last_r is None:
        return _fallback(spec, paras, first_i, last_i, why_e)
    precision = max(prec_s, prec_e, key=lambda k: _PRECISION_RANK[k])
    return _Plan("runs", precision, why_s or why_e, first_r, last_r, spec.id,
                 (start, end) if precision == "exact" else None, (pf.start, pl.end))


_MARKER_TAGS = (qn("w:commentRangeStart"), qn("w:commentRangeEnd"), qn("w:commentReference"))


def _story_roots(doc: Any) -> list[Any]:
    """Корни частей, где могут лежать маркеры комментариев: тело, колонтитулы, сноски."""
    roots = [doc.element]
    for rel in doc.part.rels.values():
        if rel.is_external or rel.reltype.rsplit("/", 1)[-1] not in ("header", "footer", "footnotes", "endnotes"):
            continue
        root = getattr(rel.target_part, "element", None)
        if root is None:
            from lxml import etree

            root = etree.fromstring(rel.target_part.blob)
        roots.append(root)
    return roots


def _comments_root(doc: Any) -> Any | None:
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/comments") and not rel.is_external:
            return rel.target_part.element
    return None


def _used_comment_ids(doc: Any) -> set[int]:
    """Номера, занятые комментариями и маркерами комментариев во всех частях.

    python-docx выдаёт новому комментарию ``max(comments.xml) + 1`` и не видит
    маркеры без записи в comments.xml. Такой номер нельзя брать: Word связал бы
    комментарий с чужой парой границ -- например, с копией той же фразы.
    """
    used: set[int] = set()
    for root in _story_roots(doc):
        for el in root.iter(*_MARKER_TAGS):
            v = _int_or_none(el.get(qn("w:id")))
            if v is not None:
                used.add(v)
    croot = _comments_root(doc)
    if croot is not None:
        used |= {v for v in (_int_or_none(c.get(qn("w:id"))) for c in croot.findall(qn("w:comment"))) if v is not None}
    return used


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _free_id(cid: int, reserved: set[int]) -> int:
    return cid if cid not in reserved else max(reserved | {cid}) + 1


def _renumber_comment(doc: Any, old: int, new: int) -> None:
    croot = _comments_root(doc)
    mine = [c for c in croot.findall(qn("w:comment")) if c.get(qn("w:id")) == str(old)]
    assert len(mine) == 1, "новый комментарий должен быть единственным с этим номером в comments.xml"
    mine[0].set(qn("w:id"), str(new))


def _apply(doc: Any, plan: _Plan, text: str, author: str, initials: str, reserved: set[int]) -> int:
    """Создать комментарий и его границы; номер берётся вне ``reserved`` и туда добавляется."""
    if plan.mode == "runs":
        comment = doc.add_comment([Run(plan.first, doc), Run(plan.last, doc)], text=text,
                                  author=author, initials=initials)
        cid = comment.comment_id
        new = _free_id(cid, reserved)
        if new != cid:  # python-docx не знает о чужих маркерах: перенумеровать только свои три
            start, end = plan.first.getprevious(), plan.last.getnext()
            ref = end.getnext().find(qn("w:commentReference"))
            assert start.tag == _MARKER_TAGS[0] and end.tag == _MARKER_TAGS[1] and ref is not None
            for el in (start, end, ref):
                el.set(qn("w:id"), str(new))
            _renumber_comment(doc, cid, new)
        reserved.add(new)
        return new
    comment = doc.comments.add_comment(text=text, author=author, initials=initials)
    cid = _free_id(comment.comment_id, reserved)
    if cid != comment.comment_id:
        _renumber_comment(doc, comment.comment_id, cid)
    reserved.add(cid)
    start = OxmlElement("w:commentRangeStart", attrs={qn("w:id"): str(cid)})
    end = OxmlElement("w:commentRangeEnd", attrs={qn("w:id"): str(cid)})
    ppr = plan.first.find(qn("w:pPr"))
    if ppr is not None:
        ppr.addnext(start)
    else:
        plan.first.insert(0, start)
    if plan.mode == "point":  # пустой диапазон в начале абзаца: слова не выделяются
        start.addnext(end)
        end.addnext(_reference_run(cid))
        return cid
    plan.last.append(end)
    plan.last.append(_reference_run(cid))
    return cid


# --------------------------------------------------------------- проверки


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _comment_snapshot(doc: Any) -> dict[int, tuple[str, str]]:
    root = None
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/comments") and not rel.is_external:
            root = rel.target_part.element
    if root is None:
        return {}
    out = {}
    for c in root.findall(qn("w:comment")):
        text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in c.iter(qn("w:p")))
        out[int(c.get(qn("w:id")))] = (c.get(qn("w:author")) or "", text)
    return out


def _markers(doc: Any) -> dict[int, dict[str, list[int]]]:
    """Позиции маркеров комментариев в порядке документа."""
    res: dict[int, dict[str, list[int]]] = {}
    tags = {qn("w:commentRangeStart"): "start", qn("w:commentRangeEnd"): "end", qn("w:commentReference"): "ref"}
    for i, el in enumerate(doc.element.body.iter(*tags.keys())):
        cid = int(el.get(qn("w:id")))
        res.setdefault(cid, {"start": [], "end": [], "ref": []})[tags[el.tag]].append(i)
    return res


def comment_spans(doc: Any, ids: Iterable[int]) -> dict[int, dict[str, Any] | None]:
    """Что охватывает каждый комментарий в документе, в координатах ``block.text``.

    Позиции маркеров пересчитываются по XML документа (число видимых символов
    абзаца до маркера по тем же правилам, что у ридера), ID блоков -- по обходу
    ридера. ``None``, если маркеров не ровно по одному или они не в блоках.
    """
    layout = DocxLayout(doc)
    where: dict[Any, tuple[BlockSpec, ParagraphRef]] = {}
    for spec in layout.specs:
        for ref in spec.paragraphs:
            if ref.el.tag == qn("w:p") and spec.host is None:
                where[ref.el] = (spec, ref)
    want = {int(i) for i in ids}
    found: dict[int, dict[str, list[Any]]] = {i: {"start": [], "end": []} for i in want}
    for el in doc.element.body.iter(_MARKER_TAGS[0], _MARKER_TAGS[1]):
        cid = _int_or_none(el.get(qn("w:id")))
        if cid in found:
            found[cid]["start" if el.tag == _MARKER_TAGS[0] else "end"].append(el)

    def position(mk: Any) -> tuple[BlockSpec, int] | None:
        p = mk.getparent()
        while p is not None and p.tag != qn("w:p"):
            p = p.getparent()
        if p not in where:
            return None
        spec, ref = where[p]
        ends = {rs.el: rs.end for rs in ref.scan.runs}
        pos = 0
        for el in p.iter():
            if el is mk:
                return spec, ref.start + pos
            if el in ends:
                pos = max(pos, ends[el])
        return None

    out: dict[int, dict[str, Any] | None] = {}
    for cid, m in found.items():
        if len(m["start"]) != 1 or len(m["end"]) != 1:
            out[cid] = None
            continue
        a, b = position(m["start"][0]), position(m["end"][0])
        if a is None or b is None or a[0] is not b[0] or a[1] > b[1]:
            out[cid] = None
            continue
        out[cid] = {"block_id": a[0].id, "start": a[1], "end": b[1], "text": a[0].text[a[1]:b[1]]}
    return out


def verify_annotated(input_path: Path | str, output_path: Path | str,
                     new_comment_ids: Iterable[int] | None = None) -> dict[str, Any]:
    """Открыть копию повторно и сверить с исходником, не доверяя процессу записи."""
    src = Path(input_path).read_bytes()
    out = Path(output_path).read_bytes()
    checks: dict[str, Any] = {}
    d_in = open_docx_bytes(src, Path(input_path).name)
    d_out = open_docx_bytes(out, Path(output_path).name)
    checks["reopened"] = True
    l_in, l_out = DocxLayout(d_in), DocxLayout(d_out)
    checks["text_unchanged"] = [(s.id, s.text) for s in l_in.specs] == [(s.id, s.text) for s in l_out.specs]
    before, after = _comment_snapshot(d_in), _comment_snapshot(d_out)
    checks["existing_comments_preserved"] = all(after.get(k) == v for k, v in before.items())
    m_in, m_out = _markers(d_in), _markers(d_out)
    checks["existing_markers_preserved"] = all(
        {k: len(v) for k, v in m_out.get(cid, {}).items()} == {k: len(v) for k, v in m.items()}
        for cid, m in m_in.items()
    )
    new_ids = sorted(set(new_comment_ids) if new_comment_ids is not None else set(after) - set(before))
    paired = True
    for cid in new_ids:
        m = m_out.get(cid)
        if not m or not (len(m["start"]) == len(m["end"]) == len(m["ref"]) == 1) \
                or not (m["start"][0] < m["end"][0] < m["ref"][0]) or cid not in after:
            paired = False
    checks["new_ranges_paired"] = paired
    checks["new_comment_ids"] = new_ids
    checks["comments_part"] = "word/comments.xml" in set(zipfile.ZipFile(io.BytesIO(out)).namelist())
    checks["spans"] = comment_spans(d_out, new_ids)
    return checks


_GATING_CHECKS = ("reopened", "text_unchanged", "existing_comments_preserved", "existing_markers_preserved",
                  "new_ranges_paired", "comments_part", "source_unchanged", "anchors_match_plan")


def _span_matches(plan: _Plan, ev_start: int, ev_end: int, span: dict[str, Any] | None) -> bool:
    if span is None or span["block_id"] != plan.block_id:
        return False
    s, e = span["start"], span["end"]
    if plan.span is not None:
        return (s, e) == plan.span
    lo, hi = plan.bounds  # precision="run": содержит цитату и не выходит за абзацы цитаты
    return lo <= s <= ev_start and ev_end <= e <= hi


# ------------------------------------------------------------ точка входа


def default_output_path(report_path: Path | str) -> Path:
    """``reports/report.md`` -> ``reports/report.annotated.docx``."""
    p = Path(report_path)
    stem = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(stem + ARTIFACT_SUFFIX)


def _mismatch_message(expected: str, actual: str) -> str:
    return (
        f"Отчёт построен для другой версии документа: в отчёте SHA-256 {expected[:12]}…, "
        f"у переданного файла {actual[:12]}…. Комментарии не добавлены, копия не создана: "
        "ID блоков и координаты цитат верны только для той версии, по которой строился отчёт. "
        "Запустите ревью для этого файла заново или сравните редакции через --compare."
    )


def annotate_docx(
    report: Any,
    input_path: Path | str,
    output_path: Path | str,
    *,
    author: str = DEFAULT_AUTHOR,
    initials: str = DEFAULT_INITIALS,
    summary: bool = True,
) -> AnnotationResult:
    """Построить аннотированную копию и вернуть подробный результат.

    При несовпадении версии исключение не поднимается: статус ``source_mismatch``
    и объяснение лежат в ``message``.
    """
    if not hasattr(_DocxDocument, "add_comment"):  # pragma: no cover - зависит от окружения
        raise WordExportError("Для комментариев Word нужен python-docx >= 1.2 (pip install 'python-docx>=1.2').")
    rep = _as_dict(report) or {}
    input_path = Path(input_path)
    output_path = Path(output_path)
    data = input_path.read_bytes()
    actual = _sha(data)
    document = rep.get("document") or {}
    run = rep.get("run") or {}
    expected_ids = {h for h in (document.get("id"), run.get("source_sha256")) if h}
    expected = document.get("id") or run.get("source_sha256")

    def fail(status: str, msg: str) -> AnnotationResult:
        return AnnotationResult(status=status, input_path=str(input_path), output_path=None,
                                source_sha256=actual, expected_sha256=expected, message=msg)

    fmt = (document.get("format") or "").lower()
    if (fmt and fmt != "docx") or input_path.suffix.lower() != ".docx":
        return fail("unsupported_input",
                    f"Аннотированная копия строится только для входа DOCX, а здесь «{fmt or input_path.suffix}». "
                    "Для этого входа используйте Markdown-, HTML- или PDF-отчёт.")
    if not expected_ids:
        return fail("source_mismatch", "В отчёте нет SHA-256 исходного документа (document.id / "
                    "run.source_sha256), поэтому нельзя доказать, что координаты относятся к этому файлу.")
    if len(expected_ids) > 1:
        return fail("source_mismatch", "В отчёте расходятся document.id и run.source_sha256; "
                    "отчёт противоречив, комментарии не добавлены.")
    if actual != expected:
        return fail("source_mismatch", _mismatch_message(expected, actual))
    if output_path.suffix.lower() != ".docx":
        raise WordExportError(f"Имя копии должно оканчиваться на .docx: {output_path.name}")
    if output_path.resolve() == input_path.resolve() or (
            output_path.exists() and os.path.samefile(output_path, input_path)):
        raise WordExportError("Копия не может перезаписать исходный документ.")

    doc = open_docx_bytes(data, input_path.name)
    layout = DocxLayout(doc)
    before = _comment_snapshot(doc)
    reserved = _used_comment_ids(doc)
    plans: dict[int, tuple[_Plan, int, int]] = {}
    report_texts = {b.get("id"): b.get("text") for b in document.get("blocks") or [] if isinstance(b, dict)}
    result = AnnotationResult(status="written", input_path=str(input_path), output_path=str(output_path),
                              source_sha256=actual, expected_sha256=expected, message="",
                              artifact=output_path.name, comments_before=len(before))

    findings = [f for f in rep.get("findings") or [] if isinstance(f, dict)]
    order = {s.id: s.loc["order"] for s in layout.specs}
    targets = []
    for fi, f in enumerate(findings):
        if f.get("status") not in REPORTABLE_STATUSES:
            result.skipped.append(Skipped(f.get("id"), None, "status_not_reportable",
                                          f"статус «{f.get('status')}» не публикуется в документе"))
            continue
        result.findings_total += 1
        evs = [e for e in f.get("evidence") or [] if isinstance(e, dict)]
        if not evs:
            result.skipped.append(Skipped(f.get("id"), None, "no_evidence",
                                          "у замечания нет текстовой опоры; оно указано в общем комментарии"))
            continue
        seen = set()
        for ev in evs:
            key = (ev.get("block_id"), ev.get("start"), ev.get("end"))
            if key in seen:
                continue
            seen.add(key)
            result.evidence_total += 1
            targets.append((order.get(ev.get("block_id"), 10**9), ev.get("start") or 0, fi, f, ev, evs))
    targets.sort(key=lambda t: t[:3])

    for _, _, _, f, ev, evs in targets:
        fid, bid = f.get("id"), ev.get("block_id")
        spec = layout.by_id.get(bid)
        if spec is None:
            result.skipped.append(Skipped(fid, bid, "block_not_found", f"в документе нет блока {bid}"))
            continue
        if report_texts.get(bid) is not None and report_texts[bid] != spec.text:
            result.skipped.append(Skipped(fid, bid, "block_text_mismatch",
                                          "текст блока в отчёте не совпадает с документом (другая версия ридера)"))
            continue
        quote = ev.get("quote") or ""
        start, end = ev.get("start"), ev.get("end")
        note = None
        valid = isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(spec.text)
        if not (valid and spec.text[start:end] == quote):
            occ = [i for i in range(len(spec.text)) if quote and spec.text.startswith(quote, i)]
            if len(occ) == 1:
                start, end = occ[0], occ[0] + len(quote)
                note = "координаты исправлены по цитате"
            else:
                reason = "quote_ambiguous" if occ else "quote_not_found"
                detail = (f"цитата встречается в блоке {len(occ)} раз, а координаты её не подтверждают"
                          if occ else "цитаты нет в тексте блока")
                result.skipped.append(Skipped(fid, bid, reason, detail))
                continue
        plan = _plan(spec, start, end)
        if plan is None:
            result.skipped.append(Skipped(fid, bid, "quote_is_separator",
                                          "цитата состоит только из разделителя абзацев или ячеек"))
            continue
        place = locate(spec.to_block(), start, end)
        others = []
        for e in evs:
            ob = layout.by_id.get(e.get("block_id"))
            if e is not ev and ob is not None and isinstance(e.get("start"), int) and isinstance(e.get("end"), int):
                lab = locate(ob.to_block(), e["start"], e["end"])["label"]
                if lab != place["label"]:
                    others.append(lab)
        question, fix = _question_and_fix(rep, f)
        text = build_comment_text(f, quote=quote, precision=plan.precision, reason=plan.reason,
                                  question=question, fix=fix, other_places=others)
        cid = _apply(doc, plan, text, author, initials, reserved)
        plans[cid] = (plan, start, end)
        result.anchors.append(Anchor(
            finding_id=fid, block_id=bid, comment_id=cid, precision=plan.precision, start=start, end=end,
            quote=quote, ref=place["ref"], label=place["label"], path=place["path"], part=place["part"],
            note="; ".join(x for x in (note, plan.reason) if x) or None,
        ))

    if summary and layout.specs:
        cid, plan = _summary_comment(doc, layout.specs[0], rep, findings, result, author, initials, reserved)
        result.summary_comment_id = cid
        plans[cid] = (plan, plan.span[0], plan.span[1])

    buf = io.BytesIO()
    doc.save(buf)
    out_bytes = buf.getvalue()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".annotating-", suffix=".docx", dir=output_path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(out_bytes)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp создаёт 0600; копия -- обычный файл пользователя
        os.replace(tmp, output_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    result.output_sha256 = _sha(out_bytes)
    new_ids = [a.comment_id for a in result.anchors] + (
        [result.summary_comment_id] if result.summary_comment_id is not None else [])
    checks = verify_annotated(input_path, output_path, new_ids)
    checks["source_unchanged"] = _sha(input_path.read_bytes()) == actual
    spans = checks.pop("spans")
    for a in result.anchors:
        a.covered = spans.get(a.comment_id)
    mismatched = [cid for cid, (plan, s, e) in plans.items() if not _span_matches(plan, s, e, spans.get(cid))]
    checks["anchors_match_plan"] = not mismatched
    result.checks = checks
    result.comments_after = len(before) + len(new_ids)
    failed = [k for k in _GATING_CHECKS if checks.get(k) is not True]
    if failed:
        # не оставлять копию, где комментарий может стоять не на том месте
        output_path.unlink(missing_ok=True)
        result.status, result.output_path = "verification_failed", None
        result.message = ("Аннотированная копия не прошла проверку после записи (" + ", ".join(failed) + ")"
                          + (f"; диапазоны комментариев {mismatched} не совпали с опорами" if mismatched else "")
                          + ". Копия удалена, чтобы комментарий не оказался на соседнем месте.")
        return result
    result.message = result.summary_ru()
    return result


def _summary_comment(doc: Any, first: BlockSpec, rep: dict[str, Any], findings: list[dict[str, Any]],
                     result: AnnotationResult, author: str, initials: str, reserved: set[int]) -> tuple[int, _Plan]:
    """Общий комментарий со сводкой. На заголовке-первом блоке -- диапазоном по
    заголовку; иначе -- точкой в начале документа, чтобы не выделять слова
    требования (первым блоком может оказаться копия фразы из замечания)."""
    findings = [f for f in findings if f.get("status") in REPORTABLE_STATUSES]
    counts = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        if f.get("severity") in counts:
            counts[f["severity"]] += 1
    lines = ["Сводка ревью ТЗ (BCC Review)"]
    lines += _verdict_lines(rep)
    lines.append(f"Замечаний: {len(findings)} (критичных {counts['critical']}, существенных {counts['major']}, "
                 f"незначительных {counts['minor']}).")
    lines.append(result.counts_ru().replace("отмечено", "Отмечено в тексте:", 1) + ".")
    loose = result.unanchored_ru()
    if loose:
        lines.append("Без места в тексте: " + "; ".join(loose[:20]) + ".")
    lines.append("Подробности, доказательства и вопросы — в отчёте ревью.")
    p0, pn = first.paragraphs[0], first.paragraphs[-1]
    if first.kind == "heading":
        plan = _Plan("paragraphs", "paragraph", None, p0.el, pn.el, first.id, (p0.start, pn.end), (p0.start, pn.end))
    else:
        plan = _Plan("point", "paragraph", None, p0.el, p0.el, first.id, (p0.start, p0.start), (p0.start, p0.start))
    return _apply(doc, plan, "\n".join(lines), author, initials, reserved), plan


def write_docx(report: Any, input_path: Path | str, output_path: Path | str, **options: Any) -> Path:
    """Записать ``report.annotated.docx`` с нативными комментариями и вернуть путь.

    Для DOCX другой версии поднимает :class:`SourceMismatchError`, для входа
    не-DOCX -- :class:`UnsupportedSourceError`. У обоих есть ``.result``
    (:class:`AnnotationResult`) с объяснением на русском.

    Если ``report`` -- dict со списком ``warnings``, туда дописываются
    предупреждения экспорта, включая счётчик ``docx_export_unanchored``
    («отмечено X из N замечаний (опор Y из M)») при пропусках.
    """
    result = annotate_docx(report, input_path, output_path, **options)
    if result.status == "written" and isinstance(report, dict) and isinstance(report.get("warnings"), list):
        # Движок получает от write_docx только путь, а report.json пишет после экспорта
        # из того же объекта: так счётчик пропусков попадает в отчёт без правок движка.
        known = {(w.get("code"), w.get("message")) for w in report["warnings"] if isinstance(w, dict)}
        report["warnings"].extend(w for w in result.warnings() if (w["code"], w["message"]) not in known)
    if result.status == "source_mismatch":
        raise SourceMismatchError(result.message, result)
    if result.status == "unsupported_input":
        raise UnsupportedSourceError(result.message, result)
    if result.status != "written":
        raise WordExportError(result.message, result)
    return Path(result.output_path or output_path)
