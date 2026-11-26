"""Независимая перепроверка артефакта отчёта без обращения к модели.

``verify_report(report_path, source_path)`` заново читает оригинал штатным
reader, пересчитывает SHA-256 и сверяет с ``REPORT.json`` (контракт v1):

* JSON Schema ``contracts/v1.json`` (через :mod:`bcc_review.contracts`);
* SHA-256 источника в ``run.source_sha256`` и ``document.id``;
* встроенные ``document.blocks`` против прочитанных заново (ID, текст, раздел, ``loc``);
* каждую опору ``{block_id, start, end, quote}`` в любом месте отчёта
  (требования, замечания, свидетели конфликтов, факты, покрытие, чек-лист):
  блок существует, координаты в пределах текста, ``block.text[start:end] == quote``,
  граница не режет число, слово или отрицание, а указанные строка/страница/путь
  совпадают с вычисленными по reader-координатам;
* правки решений (``decisions[].edits``) для текущей версии источника;
* разделы (``section``), уникальность ID и ссылки (``req_ids``, ``finding_ids``,
  ``affected_req_ids``, ``open_question_id``, ``block_ids`` …);
* достаточность опор у замечаний ``confirmed`` (``anchor_status = supported``;
  конфликт — свидетель с двумя разными опорами; пропуск — область поиска);
* числа фактов против их цитат;
* ``summary`` (числа, ``by_severity``, ``by_status``, ``critical_ids``, ``checks``),
  согласованность ``verdict`` с подтверждёнными критичными и статусом прогона,
  арифметику ``run.evidence_audit``.

Итог: ``{ok, exit_code, errors, warnings, counts, source}``. Единица учёта опор —
объект Evidence в отчёте; каждое вхождение считается отдельно.

Проверка удостоверяет согласованность предоставленных файлов между собой.
Авторство генерации подтверждается воспроизводимым настоящим прогоном и
журналом вызовов модели, а не этой проверкой.

Оболочку ``python -m bcc_review verify`` пишет интеграция (``main(argv)``
возвращает код выхода по контракту); самостоятельный запуск —
``python -m bcc_review.verification REPORT.json SOURCE``.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from bcc_review import contracts as C
from bcc_review.analysis.evidence import (
    DocumentIndex,
    check_evidence,
    check_finding_support,
    describe,
    locate,
)

__all__ = ["ERRORS", "find_reader", "main", "render_text", "summary_counts", "verify_report"]

ID_COLLECTIONS = ("requirements", "findings", "facts", "questions", "test_cases", "checklist")
REQUIRED_IDS = ("requirements", "findings", "facts", "questions", "test_cases")
REF_KEYS = {
    "req_ids": "requirements", "req_id": "requirements", "affected_req_ids": "requirements",
    "finding_ids": "findings", "critical_ids": "findings",
    "fact_ids": "facts",
    "question_id": "questions", "open_question_id": "questions", "question_ids": "questions",
    "test_case_ids": "test_cases",
    "block_ids": "blocks", "inspected_block_ids": "blocks", "block_id": "blocks",
}
# diff ссылается на предыдущий отчёт, rejected — на отброшенных кандидатов, run и document сверяются отдельно
SKIP_TOP = ("run", "diff", "document", "rejected")
LOC_KEYS = ("line", "line_end", "col", "col_end", "page", "page_end", "path", "part")
READER_BY_SUFFIX = {
    ".md": ("bcc_review.readers.text", "read_text"),
    ".markdown": ("bcc_review.readers.text", "read_text"),
    ".txt": ("bcc_review.readers.text", "read_text"),
    ".html": ("bcc_review.readers.text", "read_text"),
    ".htm": ("bcc_review.readers.text", "read_text"),
    ".pdf": ("bcc_review.readers.pdf", "read_pdf"),
    ".docx": ("bcc_review.readers.docx", "read_docx"),
}
GENERIC_READERS = (("bcc_review.readers", "read_document"), ("bcc_review.engine", "read_document"))
EXEC_ERRORS = frozenset({"report_missing", "source_unreadable", "reader_unavailable", "reader_failed"})

ERRORS: dict[str, str] = {
    "report_missing": "файл отчёта не открывается",
    "report_unreadable": "файл отчёта не читается как JSON-объект",
    "source_unreadable": "исходный файл не открывается",
    "reader_unavailable": "штатный reader для этого формата не найден, перепроверить источник нельзя",
    "reader_failed": "reader не смог прочитать исходный файл",
    "schema_invalid": "отчёт нарушает JSON Schema контракта v1",
    "source_sha_missing": "в отчёте нет SHA-256 источника (run.source_sha256 или document.id)",
    "source_sha_mismatch": "SHA-256 исходного файла не совпадает с записанным в отчёте",
    "document_id_mismatch": "document.id не совпадает с SHA-256 исходного файла",
    "document_block_mismatch": "блок документа в отчёте не совпадает с прочитанным заново",
    "document_mismatch": "title, format или warnings документа в отчёте не совпадают с прочитанными заново",
    "missing_id": "у записи нет id",
    "duplicate_id": "id повторяется",
    "dangling_reference": "ссылка на несуществующий id",
    "unknown_section": "раздела с такими заголовками нет в документе",
    "section_mismatch": "раздел не совпадает с разделом блока",
    "evidence_loc_mismatch": "строка/страница/путь опоры не совпадает с вычисленными по reader-координатам",
    "evidence_wrong_occurrence": "опора указывает на другое вхождение той же цитаты, а не на текст требования",
    "evidence_outside_requirement": "опора замечания уровня требования лежит вне текста его требования",
    "decision_edit_mismatch": "правка решения не совпадает с текстом текущего источника",
    "unsupported_confirmed_finding": "у замечания со статусом confirmed недостаточно опор",
    "summary_count_mismatch": "счётчик сводки не совпадает с пересчитанным по спискам",
    "summary_list_mismatch": "список ID в сводке не совпадает с пересчитанным",
    "verdict_inconsistent": "готовность противоречит подтверждённым критичным замечаниям или статусу прогона",
    "run_status_inconsistent": "чтение документа неполное, а прогон помечен complete",
    "audit_arithmetic": "в run.evidence_audit проверено ≠ подтверждено + неоднозначно + отклонено",
    "fact_value_not_in_quote": "число факта не встречается в его цитате",
    # предупреждения
    "schema_unchecked": "пакет jsonschema недоступен, схема не проверялась",
    "audit_missing": "в отчёте нет run.evidence_audit",
    "run_not_complete": "прогон помечен как незавершённый",
    "reader_id_differs": "reader вернул document.id, не равный SHA-256 файла",
    "evidence_skipped": "источник не совпал или не прочитан: опоры не сверялись",
    "decision_other_version": "решение относится к другой версии источника, правки не сверялись",
}


def _err(code: str, path: str = "", detail: str = "") -> dict:
    message = ERRORS.get(code) or describe(code.removeprefix("evidence_")) or code
    if detail:
        message = f"{message}: {detail}"
    return {"code": code, "path": path, "message": message}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, Mapping):
            return None
        data = data.get(part)
    return data


def _items(report: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = report.get(key)
    return [x for x in value if isinstance(x, Mapping)] if isinstance(value, list) else []


def _is_evidence(node: Any) -> bool:
    return isinstance(node, Mapping) and {"block_id", "start", "end", "quote"} <= node.keys()


def _walk(node: Any, path: str) -> Iterator[tuple[str, Any]]:
    yield path, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def _walk_report(report: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    for key, value in report.items():
        if key not in SKIP_TOP:
            yield from _walk(value, key)


def _plain(obj: Any) -> Any:
    """JSON-форма объекта reader (кортежи → списки), чтобы сравнивать со встроенной копией."""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=lambda o: getattr(o, "__dict__", str(o))))


_NUM_RE = re.compile(r"\d{1,3}(?:[    ]\d{3}(?!\d))+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.finditer(text):
        token = re.sub(r"[    ]", "", m.group()).replace(",", ".")
        out.add(token.rstrip("0").rstrip(".") if "." in token else token)
    return out


def _describe_callable(func: Any) -> str:
    """``модуль:имя`` функции; для обёртки (lambda движка) — и вложенной функции reader."""
    name = f"{getattr(func, '__module__', '?')}:{getattr(func, '__qualname__', type(func).__name__)}"
    inner = []
    for cell in getattr(func, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if callable(value) and not isinstance(value, type):
            inner.append(_describe_callable(value))
    return " → ".join([name, *inner])


def find_reader(source_path: str | os.PathLike[str] | None = None) -> Callable[[str], Any] | None:
    """Штатный reader: ``BCC_REVIEW_READER=module:function``, общий диспетчер или reader формата.

    Точки входа по ``contracts/HANDOFF.md``: ``bcc_review.readers.text:read_text``,
    ``bcc_review.readers.pdf:read_pdf``, ``bcc_review.readers.docx:read_docx``.
    """
    spec = os.environ.get("BCC_REVIEW_READER")
    candidates = [tuple(spec.split(":", 1))] if spec and ":" in spec else []
    candidates += list(GENERIC_READERS)
    if source_path is not None:
        suffix = Path(source_path).suffix.casefold()
        if suffix in READER_BY_SUFFIX:
            candidates.append(READER_BY_SUFFIX[suffix])
    for module_name, attr in candidates:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        func = getattr(module, attr, None)
        if callable(func):
            return func
    return None


def summary_counts(report: Mapping[str, Any]) -> dict[str, Any]:
    """``Report.summary`` по контракту v1, пересчитанный по спискам отчёта.

    ``by_severity`` и ``by_status`` — разбиения всех замечаний (их суммы равны
    ``findings``); ``critical_ids`` — подтверждённые критичные замечания.
    """
    reqs = _items(report, "requirements")
    finds = _items(report, "findings")
    checks = _items(report, "checks")
    return {
        "requirements": len(reqs),
        "reviewed_requirements": sum(r.get("review_status") == "reviewed" for r in reqs),
        "findings": len(finds),
        "by_severity": {sev: sum(f.get("severity") == sev for f in finds) for sev in C.SEVERITIES},
        "by_status": {st: sum(f.get("status") == st for f in finds) for st in C.FINDING_STATUSES},
        "critical_ids": [f.get("id") for f in finds
                         if f.get("status") == "confirmed" and f.get("severity") == "critical"],
        "checks": {st: sum(c.get("status") == st for c in checks) for st in C.CHECK_STATUSES},
    }


class _Verifier:
    def __init__(self, report_path: Path, source_path: Path,
                 reader: Callable[[str], Any] | None) -> None:
        self.report_path = report_path
        self.source_path = source_path
        self.reader = reader
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.counts: dict[str, Any] = {
            "unit": "evidence",
            "note": (
                "Единица учёта — объект Evidence {block_id,start,end,quote} в REPORT.json "
                "(требования, замечания, свидетели конфликтов, факты, покрытие, чек-лист); каждое "
                "вхождение считается отдельно. Подтверждено — текст по координатам буквально равен "
                "цитате и место совпадает; неоднозначно — опора верна, но та же цитата повторяется "
                "в блоке; отклонено — блок, координаты, текст, граница или место неверны."
            ),
            "checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "skipped": 0,
            "counters_checked": 0, "references_checked": 0, "findings_checked": 0, "edits_checked": 0,
        }
        self.source: dict[str, Any] = {}
        self.report: dict[str, Any] = {}
        self.raw = b""
        self.index: DocumentIndex | None = None
        self.document: Any = None

    # -- запуск -----------------------------------------------------------------

    def run(self) -> dict:
        if self._load():
            self._check_schema()
            source_ok = self._check_source()
            if source_ok and self._read_document():
                self._check_document()
                self._check_evidence()
                self._check_edits()
                self._check_sections()
                self._check_findings_support()
            else:
                skipped = sum(1 for _, node in _walk_report(self.report) if _is_evidence(node))
                self.counts["skipped"] = skipped
                if skipped:
                    self.warnings.append(_err("evidence_skipped", detail=f"{skipped} опор"))
            self._check_ids_and_refs()
            self._check_facts()
            self._check_summary()
            self._check_verdict()
            self._check_audit()
        codes = {e["code"] for e in self.errors}
        if codes & EXEC_ERRORS:
            exit_code = C.EXIT_ERROR
        elif codes:
            exit_code = C.EXIT_VERIFY_FAILED
        else:
            exit_code = C.EXIT_OK
        return {
            "ok": not self.errors,
            "exit_code": exit_code,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "source": self.source,
            "implementation": {"verify": f"{__name__}:verify_report ({__file__})",
                               "reader": self.source.get("reader")},
            "report_path": str(self.report_path),
            "source_path": str(self.source_path),
        }

    def _load(self) -> bool:
        try:
            text = self.report_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.errors.append(_err("report_missing", detail=str(exc)))
            return False
        try:
            data = json.loads(text)
        except ValueError as exc:
            self.errors.append(_err("report_unreadable", detail=str(exc)))
            return False
        if not isinstance(data, dict):
            self.errors.append(_err("report_unreadable", detail="верхний уровень не объект"))
            return False
        self.report = data
        try:
            self.raw = self.source_path.read_bytes()
        except OSError as exc:
            self.errors.append(_err("source_unreadable", detail=str(exc)))
            return False
        return True

    def _check_schema(self) -> None:
        try:
            problems = C.validation_errors(self.report, C.REPORT_SCHEMA, limit=20)
        except RuntimeError:
            self.warnings.append(_err("schema_unchecked"))
            return
        for problem in problems:
            path, _, detail = problem.partition(": ")
            self.errors.append(_err("schema_invalid", path, detail))

    # -- источник -----------------------------------------------------------------

    def _check_source(self) -> bool:
        sha = hashlib.sha256(self.raw).hexdigest()
        claimed = _dig(self.report, "run.source_sha256")
        doc_id = _dig(self.report, "document.id")
        self.source = {"sha256": sha, "report_sha256": claimed, "matches": None}
        ok = True
        if not claimed and not doc_id:
            self.errors.append(_err("source_sha_missing", "run.source_sha256"))
            ok = False
        if claimed and claimed != sha:
            self.errors.append(_err("source_sha_mismatch", "run.source_sha256",
                                    f"в отчёте {str(claimed)[:12]}…, у файла {sha[:12]}…"))
            ok = False
        if doc_id and doc_id != sha:
            self.errors.append(_err("document_id_mismatch", "document.id",
                                    f"в отчёте {str(doc_id)[:12]}…, у файла {sha[:12]}…"))
            ok = False
        self.source["matches"] = ok
        return ok

    def _read_document(self) -> bool:
        reader = self.reader or find_reader(self.source_path)
        if reader is None:
            self.errors.append(_err("reader_unavailable", detail=self.source_path.suffix or "без расширения"))
            return False
        try:
            document = reader(str(self.source_path))
            normalize = getattr(C, "normalize_document", None)  # тот же стык, что у движка; идемпотентно
            if normalize is not None:
                document = normalize(document)
        except Exception as exc:  # noqa: BLE001 — reader чужой, причину показываем как есть
            self.errors.append(_err("reader_failed", detail=f"{type(exc).__name__}: {exc}"))
            return False
        if _get(document, "id") not in (None, self.source["sha256"]):
            self.warnings.append(_err("reader_id_differs", detail=str(_get(document, "id"))))
        self.document = document
        self.source["reader"] = _describe_callable(reader)
        self.index = DocumentIndex(document)
        self.source["format"] = _get(document, "format")
        self.source["blocks"] = len(self.index.order)
        return True

    # -- документ и опоры -----------------------------------------------------------

    def _check_document(self) -> None:
        assert self.index is not None
        embedded = self.report.get("document")
        if isinstance(embedded, Mapping):
            differs = [key for key in ("title", "format", "warnings")
                       if key in embedded and _plain(embedded[key]) != _plain(_get(self.document, key))]
            if differs:
                self.errors.append(_err("document_mismatch", "document", ", ".join(differs)))
        blocks = _dig(self.report, "document.blocks")
        if not isinstance(blocks, list):
            return
        if len(blocks) != len(self.index.order):
            self.errors.append(_err("document_block_mismatch", "document.blocks",
                                    f"в отчёте {len(blocks)}, в источнике {len(self.index.order)}"))
        bad = 0
        for i, block in enumerate(blocks):
            bid = _get(block, "id")
            fresh = self.index.blocks.get(bid)
            differs = [key for key in ("text", "section", "kind", "loc")
                       if fresh is None or _plain(_get(block, key)) != _plain(_get(fresh, key))]
            if differs:
                bad += 1
                if bad <= 5:
                    detail = f"{bid}: нет в источнике" if fresh is None else f"{bid}: {', '.join(differs)}"
                    self.errors.append(_err("document_block_mismatch", f"document.blocks[{i}]", detail))

    def _requirement_spans(self) -> dict[str, tuple[list[str], list[tuple[str, int, int]]]]:
        """Путь опоры замечания уровня требования → (его req_ids, диапазоны опор этих требований)."""
        spans: dict[Any, list[tuple[str, int, int]]] = {}
        for req in _items(self.report, "requirements"):
            spans[req.get("id")] = [(e["block_id"], e["start"], e["end"]) for e in req.get("evidence") or []
                                    if _is_evidence(e) and isinstance(e["start"], int) and isinstance(e["end"], int)]
        out: dict[str, tuple[list[str], list[tuple[str, int, int]]]] = {}
        for i, finding in enumerate(_items(self.report, "findings")):
            if finding.get("scope") != "requirement":
                continue
            req_ids = [rid for rid in finding.get("req_ids") or [] if spans.get(rid)]
            ranges = [span for rid in req_ids for span in spans[rid]]
            for j, _ in enumerate(finding.get("evidence") or [] if ranges else []):
                out[f"findings[{i}].evidence[{j}]"] = (req_ids, ranges)
        return out

    def _occurrence_problem(self, path: str, node: Mapping[str, Any],
                            req_ids: list[str], ranges: list[tuple[str, int, int]]) -> tuple[str, str] | None:
        """Опора вне текста своего требования: ошибка, если та же цитата есть внутри требования."""
        assert self.index is not None
        bid, start, end, quote = node["block_id"], node["start"], node["end"], node["quote"]
        if any(b == bid and s <= start and end <= e for b, s, e in ranges):
            return None
        here = locate(None, node, index=self.index)["label"]
        for b, s, e in ranges:
            k = self.index.text(b).find(quote, s, e) if b in self.index.blocks else -1
            if k != -1:
                there = locate(None, {"block_id": b, "start": k, "end": k + len(quote)}, index=self.index)["label"]
                return ("evidence_wrong_occurrence",
                        f"в отчёте [{start},{end}) {bid}, {here}; у {', '.join(req_ids)} та же цитата "
                        f"стоит в [{k},{k + len(quote)}) {b}, {there}")
        self.warnings.append(_err("evidence_outside_requirement", path, f"{here}; требования {', '.join(req_ids)}"))
        return None

    def _check_evidence(self) -> None:
        assert self.index is not None
        scoped = self._requirement_spans()
        for path, node in _walk_report(self.report):
            if not _is_evidence(node):
                continue
            self.counts["checked"] += 1
            result = check_evidence(None, node, index=self.index)
            status = result["status"]
            if status == "rejected":
                detail = ""
                if "expected" in result:
                    exp = result["expected"]
                    detail = f"ожидалось [{exp['start']},{exp['end']}), указано [{node['start']},{node['end']})"
                elif "found" in result:
                    detail = f"по координатам «{result['found']}», в отчёте «{node['quote']}»"
                self.errors.append(_err(f"evidence_{result['reason']}", path, detail))
                self.counts["rejected"] += 1
                continue
            problems = self._loc_problems(node)
            if path in scoped:
                wrong = self._occurrence_problem(path, node, *scoped[path])
                if wrong:
                    problems.append(wrong)
            section = node.get("section")
            if isinstance(section, list) and section != self.index.section(node["block_id"]):
                problems.append(("section_mismatch", f"{section} ≠ {self.index.section(node['block_id'])}"))
            if problems:
                for code, detail in problems:
                    self.errors.append(_err(code, path, detail))
                self.counts["rejected"] += 1
                continue
            if status == "ambiguous":
                self.warnings.append(_err("evidence_repeated_in_block", path, f"«{node['quote']}»"))
                self.counts["ambiguous"] += 1
            else:
                self.counts["confirmed"] += 1

    def _loc_problems(self, node: Mapping[str, Any]) -> list[tuple[str, str]]:
        assert self.index is not None
        claimed: dict[str, Any] = {}
        if isinstance(node.get("loc"), Mapping):
            claimed.update({k: v for k, v in node["loc"].items() if k in LOC_KEYS})
        claimed.update({k: node[k] for k in LOC_KEYS if k in node})
        if not claimed:
            return []
        actual = locate(None, node, index=self.index)
        return [("evidence_loc_mismatch", f"{key}: в отчёте {value!r}, по reader {actual.get(key)!r}")
                for key, value in claimed.items() if actual.get(key) != value]

    def _check_edits(self) -> None:
        assert self.index is not None
        for i, decision in enumerate(_items(self.report, "decisions")):
            edits = [e for e in decision.get("edits") or [] if isinstance(e, Mapping)]
            if not edits:
                continue
            if decision.get("source_sha256") != self.source["sha256"]:
                self.warnings.append(_err("decision_other_version", f"decisions[{i}]"))
                continue
            for j, edit in enumerate(edits):
                self.counts["edits_checked"] += 1
                probe = {"block_id": edit.get("block_id"), "start": edit.get("start"),
                         "end": edit.get("end"), "quote": edit.get("old")}
                result = check_evidence(None, probe, index=self.index)
                if result["status"] == "rejected" and result["reason"] in {
                        "unknown_block", "bad_coordinates", "out_of_range", "offset_mismatch", "quote_mismatch"}:
                    self.errors.append(_err("decision_edit_mismatch", f"decisions[{i}].edits[{j}]",
                                            describe(result["reason"])))

    def _check_sections(self) -> None:
        assert self.index is not None
        all_sections = [self.index.section(bid) for bid in self.index.order]
        for i, req in enumerate(_items(self.report, "requirements")):
            section = req.get("section")
            if not isinstance(section, list):
                continue
            block_ids = [b for b in req.get("block_ids") or [] if b in self.index.blocks]
            if block_ids:
                if all(self.index.section(b) != section for b in block_ids):
                    self.errors.append(_err("section_mismatch", f"requirements[{i}].section", " / ".join(section)))
            elif not any(s[:len(section)] == section for s in all_sections):
                self.errors.append(_err("unknown_section", f"requirements[{i}].section", " / ".join(section)))

    def _check_findings_support(self) -> None:
        assert self.index is not None
        for i, finding in enumerate(_items(self.report, "findings")):
            if finding.get("status") != "confirmed":
                continue
            self.counts["findings_checked"] += 1
            for problem in check_finding_support(None, finding, index=self.index):
                self.errors.append(_err("unsupported_confirmed_finding", f"findings[{i}]",
                                        f"{finding.get('id')}: {problem['message']}"))

    # -- внутренняя согласованность -------------------------------------------------

    def _collection_ids(self) -> dict[str, set]:
        ids: dict[str, set] = {}
        for name in ID_COLLECTIONS:
            seen: set = set()
            for i, item in enumerate(_items(self.report, name)):
                item_id = item.get("id")
                if item_id is None:
                    if name in REQUIRED_IDS:
                        self.errors.append(_err("missing_id", f"{name}[{i}]"))
                    continue
                if item_id in seen:
                    self.errors.append(_err("duplicate_id", f"{name}[{i}].id", str(item_id)))
                seen.add(item_id)
            ids[name] = seen
        if self.index is not None:
            ids["blocks"] = set(self.index.blocks)
        return ids

    def _check_ids_and_refs(self) -> None:
        ids = self._collection_ids()
        for path, node in _walk_report(self.report):
            if not isinstance(node, Mapping):
                continue
            for key, value in node.items():
                target = REF_KEYS.get(key)
                if target is None or (key == "block_id" and _is_evidence(node)):
                    continue
                if key == "block_id" and path.startswith("decisions"):
                    continue  # правки решений сверяются в _check_edits
                if target not in ids:  # блоки без прочитанного источника не сверяем
                    continue
                for ref in value if isinstance(value, list) else [value]:
                    if ref is None:
                        continue
                    self.counts["references_checked"] += 1
                    if ref not in ids[target]:
                        self.errors.append(_err("dangling_reference", f"{path}.{key}",
                                                f"{ref!r} нет в {target}"))

    def _check_facts(self) -> None:
        for i, fact in enumerate(_items(self.report, "facts")):
            value = fact.get("value")
            if value is None or isinstance(value, (bool, dict, list)):
                continue
            wanted = _numbers(str(value))
            quotes = " | ".join(ev.get("quote", "") for ev in fact.get("evidence") or [] if _is_evidence(ev))
            missing = wanted - _numbers(quotes)
            if wanted and missing:
                self.errors.append(_err("fact_value_not_in_quote", f"facts[{i}].value",
                                        f"{', '.join(sorted(missing))} нет в «{quotes}»"))

    def _check_summary(self) -> None:
        summary = self.report.get("summary")
        if not isinstance(summary, Mapping):
            return
        canonical = summary_counts(self.report)
        for key, expected in canonical.items():
            actual = summary.get(key)
            if actual is None:
                continue
            if key == "critical_ids":
                self.counts["counters_checked"] += 1
                if not isinstance(actual, list) or sorted(map(str, actual)) != sorted(map(str, expected)):
                    self.errors.append(_err("summary_list_mismatch", "summary.critical_ids",
                                            f"в отчёте {actual}, по спискам {expected}"))
            elif isinstance(expected, dict):
                for sub, value in expected.items():
                    got = actual.get(sub) if isinstance(actual, Mapping) else None
                    if got is None:
                        continue
                    self.counts["counters_checked"] += 1
                    if got != value:
                        self.errors.append(_err("summary_count_mismatch", f"summary.{key}.{sub}",
                                                f"в отчёте {got}, по спискам {value}"))
            else:
                self.counts["counters_checked"] += 1
                if actual != expected:
                    self.errors.append(_err("summary_count_mismatch", f"summary.{key}",
                                            f"в отчёте {actual}, по спискам {expected}"))

    def _check_verdict(self) -> None:
        verdict = self.report.get("verdict")
        if not isinstance(verdict, Mapping):
            return
        run = self.report.get("run") if isinstance(self.report.get("run"), Mapping) else {}
        run_status = run.get("status")
        if run_status in C.RUN_STATUSES and run_status != "complete":
            self.warnings.append(_err("run_not_complete", "run.status", run_status))
        source_doc = self.document if self.document is not None else self.report.get("document")
        warnings = _get(source_doc, "warnings")
        partial_codes = [w.get("code") for w in warnings or [] if isinstance(w, Mapping)
                         and w.get("code") in C.PARTIAL_READ_CODES]
        if partial_codes and run_status == "complete":
            self.errors.append(_err("run_status_inconsistent", "run.status", ", ".join(partial_codes)))
        allow_partial = bool(_dig(self.report, "run.options.allow_partial_ready"))
        critical = [f for f in _items(self.report, "findings")
                    if f.get("status") == "confirmed" and f.get("severity") == "critical"]
        for target in C.BLOCKS_TARGETS:
            if _dig(verdict, f"{target}.status") != "ready":
                continue
            blockers = [f.get("id") for f in critical if target in (f.get("blocks") or C.BLOCKS_TARGETS)]
            if blockers:
                self.errors.append(_err("verdict_inconsistent", f"verdict.{target}.status",
                                        f"ready при подтверждённых критичных {blockers}"))
            if run_status != "complete" and not allow_partial:
                self.errors.append(_err("verdict_inconsistent", f"verdict.{target}.status",
                                        f"ready при прогоне {run_status!r}"))

    def _check_audit(self) -> None:
        audit = _dig(self.report, "run.evidence_audit")
        if not isinstance(audit, Mapping):
            self.warnings.append(_err("audit_missing", "run.evidence_audit"))
            return
        parts = [audit.get(k) for k in ("checked", "confirmed", "ambiguous", "rejected")]
        if not all(isinstance(p, int) for p in parts) or parts[0] != sum(parts[1:]):
            self.errors.append(_err("audit_arithmetic", "run.evidence_audit", f"{parts}"))


def verify_report(report_path: str | os.PathLike[str], source_path: str | os.PathLike[str], *,
                  reader: Callable[[str], Any] | None = None) -> dict:
    """Перепроверить пару отчёт/источник без обращения к модели.

    ``reader(path) -> Document`` — штатный reader; по умолчанию его ищет
    :func:`find_reader`. Возвращает ``{ok, exit_code, errors, warnings, counts, source}``;
    каждая ошибка — ``{code, path, message}``; ``exit_code`` — 0, 1 (ошибка
    выполнения) или 4 (расхождение) по ``contracts``.
    """
    return _Verifier(Path(report_path), Path(source_path), reader).run()


def render_text(result: Mapping[str, Any]) -> str:
    """Русский текстовый итог перепроверки."""
    c = result["counts"]
    src = result.get("source") or {}
    lines = ["Перепроверка отчёта без обращения к модели",
             f"  отчёт:    {result.get('report_path', '')}",
             f"  источник: {result.get('source_path', '')}"]
    if src.get("sha256"):
        verdict = "совпадает с отчётом" if src.get("matches") else "НЕ совпадает с отчётом"
        lines.append(f"  SHA-256:  {src['sha256']} — {verdict}")
    impl = result.get("implementation") or {}
    lines.append(f"  verify:   {impl.get('verify', '—')}")
    lines.append(f"  reader:   {impl.get('reader') or 'не вызывался'}")
    lines.append("Опоры (единица учёта — объект Evidence {block_id,start,end,quote} в отчёте; "
                 "каждое вхождение отдельно):")
    tail = f" · пропущено {c['skipped']}" if c.get("skipped") else ""
    lines.append(f"  проверено {c['checked']} · подтверждено {c['confirmed']} · "
                 f"неоднозначно {c['ambiguous']} · отклонено {c['rejected']}{tail}")
    lines.append(f"Сверено: счётчиков сводки {c['counters_checked']}, ссылок на ID {c['references_checked']}, "
                 f"замечаний confirmed {c['findings_checked']}, правок решений {c['edits_checked']}")
    for title, items in (("Ошибки", result["errors"]), ("Предупреждения", result["warnings"])):
        if items:
            lines.append(f"{title} ({len(items)}):")
            lines.extend(f"  [{e['code']}] {e['path'] or '—'}: {e['message']}" for e in items)
    lines.append("ИТОГ: ПРОЙДЕНА" if result["ok"] else "ИТОГ: НЕ ПРОЙДЕНА")
    lines.append("Проверка удостоверяет согласованность отчёта и источника между собой. Авторство "
                 "генерации подтверждают воспроизводимый прогон агента и журнал вызовов модели.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """``verify REPORT.json SOURCE [--json]`` → 0 пройдена, 1 ошибка выполнения, 2 вызов, 4 расхождение."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "verify":
        args = args[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if len(args) != 2:
        print("использование: python -m bcc_review verify REPORT.json SOURCE [--json]", file=sys.stderr)
        return C.EXIT_USAGE
    result = verify_report(args[0], args[1])
    print(json.dumps(result, ensure_ascii=False, indent=2) if as_json else render_text(result))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
