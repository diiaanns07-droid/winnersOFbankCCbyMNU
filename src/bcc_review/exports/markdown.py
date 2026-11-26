"""Официальный русский отчёт в Markdown по Report контракта v1.

Публичный интерфейс::

    write_markdown(report, output_path) -> Path
    render_markdown(report) -> str
    check_markdown(markdown, report) -> list[str]   # пустой список — числа сходятся

Все показанные числа, статусы и вердикты берутся из одного Report. Цитаты
и ID выводятся как есть; текст экранируется так, чтобы ``|``, ``*``, ``<``,
переносы строк и начало строки вида ``1.`` или ``#`` не ломали таблицы
и цитаты.

Запуск без движка (сверка и демонстрация)::

    python -m bcc_review.exports.markdown REPORT.json OUTPUT.md
    python -m bcc_review.exports.markdown --check OUTPUT.md REPORT.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._common import (
    BLOCKS_LABEL,
    CHECK_MARK,
    COVERAGE_LABEL,
    CRITERIA,
    CRITERION,
    CRITERION_GEN,
    DEFECT,
    FINDING,
    FORMAT_LABEL,
    INDIVIDUAL_CODES,
    MEANING_LABEL,
    MODE_LABEL,
    NBSP,
    OPORA_GEN,
    QUOTE_GEN,
    REQ,
    REQ_GEN,
    RUN_STATUS_LABEL,
    SET_CODES,
    SET_STAGE_NAMES,
    SEVERITY_ICON,
    SEVERITY_LABEL,
    STAGE_STATUS_LABEL,
    STATUS_LABEL,
    TOKEN,
    DocIndex,
    as_list,
    as_report_dict,
    count,
    criterion_name,
    criterion_ref,
    critical_category,
    evidence_of,
    finding_status,
    findings_all,
    first_actions,
    fmt_datetime,
    fmt_duration,
    fmt_int,
    fmt_ratio,
    group_findings,
    kind_name,
    of_count,
    partial_read_warnings,
    provider_state,
    readiness_display,
    rejected_items,
    requirement_index,
    requirement_states,
    run_info,
    severity_rank,
    slug,
    summary_mismatches,
    summary_numbers,
    verdict_part,
    warning_text,
)

__all__ = ["write_markdown", "render_markdown", "check_markdown", "SUMMARY_MARKER"]

SUMMARY_MARKER = "bcc-review:summary"

# --------------------------------------------------------------------------
# Экранирование Markdown (CommonMark + таблицы GFM)
# --------------------------------------------------------------------------

_SPECIAL = re.compile(r"([\\`*_\[\]<>|#~&!])")
_LEADING_BLOCK = re.compile(r"^([-+=])")
_LEADING_ORDERED = re.compile(r"^(\d+)([.)])")


def _esc_inline(line: str) -> str:
    return _SPECIAL.sub(r"\\\1", line)


def _esc_line(line: str) -> str:
    """Экранирование строки, которая начинает строку Markdown (цитата, пункт списка)."""
    line = _esc_inline(line)
    stripped = line.lstrip(" ")
    pad = len(line) - len(stripped)
    stripped = _LEADING_BLOCK.sub(r"\\\1", stripped)
    stripped = _LEADING_ORDERED.sub(r"\1\\\2", stripped)
    # Ведущие пробелы превращаются в неразрывные, иначе 4 пробела дают блок кода.
    return NBSP * pad + stripped


def _lines(text: Any) -> list[str]:
    return str(text if text is not None else "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def esc(text: Any) -> str:
    """Текст внутри строки Markdown или ячейки таблицы; переносы — ``<br>``."""
    return "<br>".join(_esc_inline(line) for line in _lines(text))


def esc_lead(text: Any) -> str:
    """Как esc, но безопасно и в начале строки или пункта списка."""
    return "<br>".join(_esc_line(line) for line in _lines(text))


def quote_block(text: Any, prefix: str = "") -> list[str]:
    """Многострочная цитата как блок ``>`` с жёсткими переносами строк."""
    lines = [_esc_line(line) for line in _lines(text)]
    out = []
    for i, line in enumerate(lines):
        tail = "\\" if i < len(lines) - 1 else ""
        out.append(f"{prefix}> {line}{tail}".rstrip(" "))
    return out


def shorten(text: Any, limit: int = 140) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:") + "…"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Таблица GFM. Ячейки уже экранированы вызывающим кодом."""
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(":---" for _ in header) + " |"]
    for row in rows:
        out.append("| " + " | ".join(cell if cell != "" else " " for cell in row) + " |")
    return out


READINESS_LABEL = {
    "ready": "✅ Можно начинать",
    "not_ready": "⛔ Нельзя начинать",
    "unknown": "❔ Не определено в отчёте",
    "unconfirmed": "❔ Не подтверждено: прогон неполный",
    "unconfirmed_failed": "❔ Не подтверждено: прогон завершился ошибкой",
}
CHECK_STATE_LABEL = {"full": "✅ полностью", "partial": "◐ частично", "none": "✖ не проверено"}
REQ_KIND_LABEL = {
    "functional": "функциональное",
    "nonfunctional": "нефункциональное",
    "non_functional": "нефункциональное",
    "acceptance": "критерий приёмки",
    "data": "требование к данным",
    "integration": "интеграция",
    "interface": "интерфейс",
    "constraint": "ограничение",
    "api": "API",
}
CHECK_ICON = {"passed": "✔", "failed": "✖", "skipped": "⏸", "na": "—"}

SUMMARY_ROWS = {
    "total": "Выделено требований",
    "reviewed": "Проверено полностью",
    "partial": "Проверено частично",
    "not_reviewed": "Не проверено",
    "clean": "Без подтверждённых замечаний",
    "findings": "Замечаний в Report",
    "status": "По статусу",
    "unique": "Уникальных подтверждённых дефектов",
    "merged": "Объединено при подготовке отчёта",
    "rejected": "Снято при самопроверке",
    "checks": "Проверок по критериям",
    "evidence": "Цитаты замечаний, сверенные с документом",
}


def _is_conflict(f: Mapping[str, Any]) -> bool:
    return str(f.get("kind") or "").lower() == "conflict" or str(f.get("criterion") or "").lower() == "set_consistent"


def _is_coverage(f: Mapping[str, Any]) -> bool:
    return str(f.get("criterion") or "").lower() == "set_validatable"


def _is_promise(f: Mapping[str, Any]) -> bool:
    """Пропуск: опора — обещание в тексте, а место описания проверено и не найдено."""
    kind = str(f.get("kind") or "").lower()
    crit = str(f.get("criterion") or "").lower()
    return (kind == "omission" or crit == "set_complete") and bool(as_list(f.get("inspected_block_ids")))


def _is_omission(f: Mapping[str, Any]) -> bool:
    kind = str(f.get("kind") or "").lower()
    return kind == "omission" or (kind == "incomplete" and bool(as_list(f.get("inspected_block_ids")))) or (
        str(f.get("criterion") or "").lower() == "set_complete"
    )


# --------------------------------------------------------------------------
# Рендерер
# --------------------------------------------------------------------------


class _Renderer:
    def __init__(self, report: Any):
        self.r = as_report_dict(report)
        self.idx = DocIndex(self.r)
        self.reqs = requirement_index(self.r)
        self.states = requirement_states(self.r)
        self.nums = summary_numbers(self.r)
        self.info = run_info(self.r)
        self.findings = findings_all(self.r)
        self.by_id = {str(f.get("id")): f for f in self.findings}
        self.groups = group_findings(self.findings)
        self.group_of: dict[str, dict[str, Any]] = {}
        for g in self.groups:
            for m in g["members"]:
                self.group_of[str(m.get("id"))] = g
        self.questions = {str(q.get("id")): q for q in as_list(self.r.get("questions")) if isinstance(q, Mapping)}
        self.decisions = [d for d in as_list(self.r.get("decisions")) if isinstance(d, Mapping)]
        self.exporter_notes: list[str] = []
        self._anchors: dict[tuple[str, str], str] = {}
        self._used: set[str] = set()
        for rid in self.reqs:
            self._anchor("r", rid)
        for fid in self.by_id:
            self._anchor("f", fid)
        for qid in self.questions:
            self._anchor("q", qid)
        self.out: list[str] = []

    # --- утилиты ---------------------------------------------------------

    def _anchor(self, kind: str, ident: str) -> str:
        key = (kind, ident)
        if key not in self._anchors:
            base = slug(ident, kind)
            name, n = base, 2
            while name in self._used:
                name, n = f"{base}-{n}", n + 1
            self._used.add(name)
            self._anchors[key] = name
        return self._anchors[key]

    def link_req(self, rid: Any, with_source: bool = True) -> str:
        rid = str(rid)
        if rid not in self.reqs:
            return esc(f"{rid} (нет в списке требований)")
        source = self.reqs[rid].get("source_id")
        tail = f"{NBSP}({esc(source)})" if with_source and source else ""
        return f"[{esc(rid)}](#{self._anchor('r', rid)}){tail}"

    def link_finding(self, fid: Any) -> str:
        fid = str(fid)
        if fid in self.by_id:
            return f"[{esc(fid)}](#{self._anchor('f', fid)})"
        return esc(fid)

    def link_question(self, qid: Any) -> str:
        qid = str(qid)
        if qid in self.questions:
            return f"[{esc(qid)}](#{self._anchor('q', qid)})"
        return esc(qid)

    def emit(self, *lines: str) -> None:
        self.out.extend(lines)

    def blank(self) -> None:
        if self.out and self.out[-1] != "":
            self.out.append("")

    def evidence_mark(self, ev: Mapping[str, Any]) -> str:
        return {
            "ok": "цитата сверена с текстом документа",
            "mismatch": "⚠️ цитата не совпадает с текстом блока",
            "missing_block": "⚠️ блок не найден в документе",
            "no_offsets": "координаты цитаты не указаны",
        }[self.idx.check_evidence(ev)]

    def ev_place(self, ev: Mapping[str, Any]) -> str:
        return self.idx.place(ev.get("block_id"), ev.get("start"), ev.get("end"))

    def emit_evidence(self, ev: Mapping[str, Any], label: str = "Место") -> None:
        self.emit(f"{label}: {esc(self.ev_place(ev))} · {self.evidence_mark(ev)}", "")
        self.emit(*quote_block(ev.get("quote", "")), "")

    def readiness_cell(self, part: str) -> tuple[str, list[str], list[str]]:
        status, reasons, notes = readiness_display(self.r, part)
        if status == "unconfirmed" and self.info["status"] == "failed":
            status = "unconfirmed_failed"
        return READINESS_LABEL.get(status, READINESS_LABEL["unknown"]), reasons, notes

    # --- первый экран ----------------------------------------------------

    def header(self) -> None:
        doc = self.r.get("document") or {}
        title = doc.get("title") or "без названия"
        fmt = FORMAT_LABEL.get(str(doc.get("format") or "").lower(), str(doc.get("format") or "—"))
        status = self.info["status"]
        self.emit(f"# Отчёт о проверке требований: «{esc(title)}»", "")
        self.emit(
            f"**Документ:** {esc(doc.get('source_name') or title)} ({esc(fmt)}) · "
            f"**Прогон:** {esc(RUN_STATUS_LABEL.get(status, status))} · "
            f"**Дата:** {esc(fmt_datetime(self.info['started_at']))} · "
            f"**Модель:** {esc(self.info['model'] or 'нет данных')}",
            "",
        )
        n = self.nums
        total = n["requirements_total"]
        coverage = (
            f"Полностью проверено {fmt_ratio(n['requirements_reviewed'], total, REQ_GEN)}, "
            f"частично — {fmt_int(n['requirements_partial'])}, "
            f"не проверено — {fmt_int(n['requirements_not_reviewed'])}."
        )
        reasons = "; ".join(self.info["status_reasons"])
        why = f" Причина: {esc(reasons.rstrip('. '))}." if reasons else ""
        stages = self.info["incomplete_stages"]
        stage_note = f" Незавершённые этапы: {esc(', '.join(stages))}." if stages else ""
        if status == "complete":
            self.emit(f"> ✅ **Прогон завершён полностью.** {coverage}", "")
        elif status == "partial":
            self.emit(
                f"> ⚠️ **Прогон завершён частично.**{why}{stage_note} {coverage} "
                "Готовность к разработке и тестированию по такому прогону не подтверждается.",
                "",
            )
        elif status == "failed":
            self.emit(
                f"> ⛔ **Прогон завершился ошибкой.**{why}{stage_note} {coverage} "
                "Решение о готовности не принимается, нужен повторный прогон.",
                "",
            )
        else:
            self.emit(f"> ❔ **Статус прогона не указан** (`run.status` = {esc(status)}). {coverage}", "")
        partial_read = partial_read_warnings(self.r)
        if partial_read:
            self.emit(f"> ⚠️ **Документ прочитан не полностью:** {esc('; '.join(partial_read))}", "")
        if self.info["mode"] == "mock":
            self.emit(
                "> ℹ️ Режим **mock**: ответы модели подставлены тестовым транспортом. "
                "Отчёт показывает формат и сверку, а не реальную проверку моделью.",
                "",
            )
        elif self.info["mode"] == "rules_only":
            self.emit("> ℹ️ Режим **только правила**: модель не вызывалась, семантические проверки не выполнялись.", "")

    def first_screen(self) -> None:
        self.emit("## Решение", "")
        rows, notes = [], []
        for part, label in (("development", "Разработка"), ("testing", "Тестирование")):
            shown, reasons, part_notes = self.readiness_cell(part)
            ids = verdict_part(self.r, part)["finding_ids"]
            basis = "; ".join(esc(r) for r in reasons) or "Основание в verdict не указано"
            if ids:
                basis += f" ({', '.join(self.link_finding(x) for x in ids)})"
            rows.append([label, shown, basis])
            notes.extend(part_notes)
        self.emit(*table(["Направление", "Решение", "Основание из отчёта"], rows), "")
        for note in notes:
            self.emit(f"> ⚠️ {esc(note)}", "")
        self.exporter_notes.extend(notes)

        crit_groups = [g for g in self.groups if g["confirmed"] and g["severity"] == "critical"]
        checked_any = self.nums["requirements_reviewed"] + self.nums["requirements_partial"]
        scope_note = " (среди проверенного)" if self.info["status"] != "complete" else ""
        if crit_groups:
            self.emit(f"**Критичные проблемы{scope_note}: {count(len(crit_groups), DEFECT)}**", "")
            for i, g in enumerate(crit_groups, 1):
                extra = ""
                if g["others"]:
                    extra = " Та же первопричина: " + ", ".join(self.link_finding(m.get("id")) for m in g["others"]) + "."
                self.emit(f"{i}. {self.one_line(g['primary'])}{extra}")
            self.blank()
        elif not checked_any and not self.findings:
            self.emit("**Критичные проблемы:** не определены — проверка требований не выполнялась.", "")
        else:
            self.emit(f"**Критичные проблемы{scope_note}:** подтверждённых критичных дефектов нет.", "")
        pending = [f for f in self.findings if finding_status(f) == "needs_review" and severity_rank(f) == 0]
        if pending:
            links = ", ".join(self.link_finding(f.get("id")) for f in pending)
            self.emit(f"**На проверке человеком с серьёзностью «критичное»:** {links}.", "")

        actions = first_actions(self.r)
        if actions:
            self.emit(f"**Первое действие:** {self.action_text(actions[0])}", "")
        else:
            self.emit("**Первое действие:** в `verdict.first_actions` не указано; порядок правок — в разделе 6.", "")

    def one_line(self, f: Mapping[str, Any]) -> str:
        places = [self.idx.short_place(e.get("block_id"), e.get("start"), e.get("end")) for e in evidence_of(f)[:2]]
        reqs = ", ".join(self.link_req(r) for r in as_list(f.get("req_ids")))
        where = f" — {esc(' и '.join(places))}" if places else ""
        req_part = f" Требования: {reqs}." if reqs else ""
        blocked = f" Блокирует решение: {esc(f['blocked_decision'])}." if f.get("blocked_decision") else ""
        return (
            f"{self.link_finding(f.get('id'))} {SEVERITY_ICON.get(str(f.get('severity')), '')} "
            f"**{esc(kind_name(f.get('kind')))}:** {esc(f.get('title') or '')}{where}.{req_part}{blocked}"
        )

    def action_text(self, action: Mapping[str, Any]) -> str:
        refs = [self.link_finding(x) for x in action["finding_ids"]]
        tail = f" ({', '.join(refs)})" if refs else ""
        return f"{esc(action['text'])}{tail}"

    # --- 1. паспорт ------------------------------------------------------

    def passport(self) -> None:
        doc = self.r.get("document") or {}
        info = self.info
        n = self.nums
        version = info["agent_version"] or "нет данных"
        if info["agent_commit"]:
            version += f" (коммит {info['agent_commit']})"
        model = info["model"] or "нет данных"
        if info["requested_model"] and info["requested_model"] != info["model"]:
            model += f" (запрошена {info['requested_model']})"
        if len(info["models_seen"]) > 1:
            model += f"; в ответах: {', '.join(info['models_seen'])}"
        calls = "нет данных"
        if isinstance(info["calls_physical"], int):
            calls = fmt_int(info["calls_physical"])
            extra = []
            for key, label in (("calls_retries", "повторов"), ("calls_failed", "неуспешных"), ("calls_cache_hits", "из кэша")):
                if info[key]:
                    extra.append(f"{label} — {fmt_int(info[key])}")
            if extra:
                calls += f" ({', '.join(extra)})"
        rows = [
            ["Документ", esc(doc.get("title") or "без названия")],
            ["Файл", esc(doc.get("source_name") or info["source_name"] or "нет данных")],
            ["Формат входа", esc(FORMAT_LABEL.get(str(doc.get("format") or "").lower(), doc.get("format") or "—"))],
            ["SHA-256 байтов входа", f"`{info['source_sha256']}`" if info["source_sha256"] else "нет данных"],
            ["Блоков текста в документе", fmt_int(len(self.idx.blocks))],
            ["Идентификатор прогона", esc(info["run_id"] or "нет данных")],
            ["Начало прогона", esc(fmt_datetime(info["started_at"]))],
            ["Окончание прогона", esc(fmt_datetime(info["finished_at"]))],
            ["Длительность", esc(fmt_duration(info["duration_s"]))],
            ["Версия агента", esc(version)],
            ["Версия схемы отчёта", esc(self.r.get("schema_version") or "нет данных")],
            ["Поставщик LLM", esc(info["provider"] or "нет данных")],
            ["Статус поставщика", esc(provider_state(info))],
            ["Модель (фактическая)", esc(model)],
            ["Режим", esc(MODE_LABEL.get(info["mode"], info["mode"] or "нет данных"))],
            ["Физических вызовов модели", calls],
            ["Токены", self.tokens_text()],
            ["Этапы", self.stages_text()],
            ["Статус прогона", f"{esc(RUN_STATUS_LABEL.get(info['status'], info['status']))} (`{esc(info['status'])}`)"],
            [
                "Охват проверки требований",
                f"полностью {fmt_ratio(n['requirements_reviewed'], n['requirements_total'], REQ_GEN)}",
            ],
            ["Предупреждений", fmt_int(len(self.all_warnings()))],
        ]
        if info["modules"]:
            rows.append(["Реализации модулей", esc("; ".join(f"{k}: {v}" for k, v in info["modules"].items()))])
        doc_id = doc.get("id")
        if doc_id and info["source_sha256"] and doc_id != info["source_sha256"]:
            note = "`document.id` не совпадает с `run.source_sha256`: отчёт может относиться к другому файлу"
            rows.append(["⚠️ Сверка идентификатора", note])
            self.exporter_notes.append(note.replace("`", ""))
        self.emit("## 1. Паспорт прогона", "")
        self.emit(*table(["Параметр", "Значение"], rows), "")

    def tokens_text(self) -> str:
        ti, to, cr = self.info["tokens_in"], self.info["tokens_out"], self.info["tokens_cache_read"]
        if ti is None and to is None:
            return "поставщик не сообщил"
        parts = []
        if ti is not None:
            parts.append(f"вход {fmt_int(ti)}")
        if to is not None:
            parts.append(f"выход {fmt_int(to)}")
        if cr:
            parts.append(f"из кэша {fmt_int(cr)}")
        total = (ti or 0) + (to or 0)
        return f"{', '.join(parts)}; всего {count(total, TOKEN)}"

    def stages_text(self) -> str:
        stages = self.info["stages"]
        if not stages:
            return "нет данных"
        parts = []
        for s in stages:
            status = str(s.get("status") or "")
            label = STAGE_STATUS_LABEL.get(status, status)
            calls = s.get("calls")
            text = f"{s.get('name')} — {label}"
            if isinstance(calls, int) and calls:
                text += f", вызовов {calls}"
            if s.get("implementation"):
                text += f", {s['implementation']}"
            if s.get("reason") and status not in {"ok", "cached"}:
                text += f" ({s['reason']})"
            parts.append(text)
        return esc("; ".join(parts))

    # --- 2. нарезка ------------------------------------------------------

    def slicing(self) -> None:
        n = self.nums
        self.emit("## 2. Нарезка требований", "")
        self.emit(
            f"Агент выделил {count(len(self.reqs), REQ)}: "
            f"с ID документа — {fmt_int(n['requirements_with_source_id'])}, "
            f"с ID, присвоенным агентом, — {fmt_int(n['requirements_agent_ids'])}. "
            "Для требований без ID в документе цитата сохранена в разделе 3.",
            "",
        )
        if not self.reqs:
            self.emit("Список требований в Report пуст.", "")
        else:
            rows = []
            for rid, req in self.reqs.items():
                source = esc(req["source_id"]) if req.get("source_id") else "— (присвоен агентом)"
                related = self.findings_for_req(rid)
                conf = sum(1 for f in related if finding_status(f) == "confirmed")
                review = len(related) - conf
                fcell = fmt_int(conf) + (f" (+{fmt_int(review)} на проверке)" if review else "")
                rows.append(
                    [
                        f"[{esc(rid)}](#{self._anchor('r', rid)})",
                        source,
                        esc(shorten(req.get("text") or "")),
                        esc(self.req_place(req)),
                        CHECK_STATE_LABEL[self.states.get(rid, {}).get("state", "none")],
                        fcell,
                    ]
                )
            self.emit(
                *table(["ID в отчёте", "ID в документе", "Краткая формулировка", "Место", "Проверка", "Замечаний"], rows),
                "",
            )
        excluded = [x for x in as_list(self.r.get("excluded")) if isinstance(x, Mapping)]
        if excluded:
            self.emit("**Не вошло в нарезку:**", "")
            for x in excluded:
                places = self.lines_text(as_list(x.get("block_ids")))
                self.emit(f"- {esc_lead(x.get('reason') or 'причина не указана')}: {esc(places)}")
            self.blank()

    def lines_text(self, block_ids: list[Any]) -> str:
        """Номера строк блоков, сжатые в диапазоны: «строки 1, 5–7, 13»."""
        lines: set[int] = set()
        other = []
        for bid in block_ids:
            span = self.idx.line_span(bid)
            if span:
                lines.update(range(span[0], span[1] + 1))
            else:
                other.append(self.idx.short_place(bid))
        ranges, run = [], []
        for n in sorted(lines):
            if run and n == run[-1] + 1:
                run.append(n)
            else:
                if run:
                    ranges.append(run)
                run = [n]
        if run:
            ranges.append(run)
        parts = [str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in ranges]
        word = "строка" if len(lines) == 1 else "строки"
        text = f"{word} {', '.join(parts)}" if parts else ""
        return "; ".join([t for t in [text, *other] if t]) or "—"

    def places_text(self, block_ids: list[Any]) -> str:
        """Блоки, сгруппированные по разделам: «Раздел (строки 7–11); …»."""
        spans: dict[str, list[int]] = {}
        order: list[str] = []
        for bid in block_ids:
            section = self.idx.section(bid) or "без раздела"
            span = self.idx.line_span(bid)
            if section not in spans:
                spans[section] = []
                order.append(section)
            if span:
                spans[section].extend(span)
        parts = []
        for section in order:
            lines = spans[section]
            if lines:
                a, b = min(lines), max(lines)
                parts.append(f"{section} (строка {a})" if a == b else f"{section} (строки {a}–{b})")
            else:
                parts.append(section)
        return "; ".join(parts) or "—"

    def req_place(self, req: Mapping[str, Any]) -> str:
        evs = [e for e in as_list(req.get("evidence")) if isinstance(e, Mapping)]
        if evs:
            return self.ev_place(evs[0])
        blocks = as_list(req.get("block_ids"))
        return self.idx.place(blocks[0]) if blocks else "место не указано"

    def findings_for_req(self, rid: str) -> list[dict[str, Any]]:
        return [f for f in self.findings if rid in {str(x) for x in as_list(f.get("req_ids"))}]

    def owner_req(self, f: Mapping[str, Any]) -> str | None:
        if str(f.get("scope") or "requirement") == "set":
            return None
        for rid in as_list(f.get("req_ids")):
            if str(rid) in self.reqs:
                return str(rid)
        return None

    # --- 3. проверка каждого требования ---------------------------------

    def per_requirement(self) -> None:
        self.emit("## 3. Проверка каждого требования", "")
        self.emit(
            "Критерии — свойства ISO/IEC/IEEE 29148:2018, п. 5.2.5 (коды и пункты — в приложении «Методика»). "
            "✔ — выполнен, ✖ — нарушен, ⏸ — не проверен, — — не применим.",
            "",
        )
        canon = list(CRITERIA)
        for rid, req in self.reqs.items():
            st = self.states[rid]
            title = f"{esc(rid)} · {esc(req['source_id'])}" if req.get("source_id") else f"{esc(rid)} · без ID в документе"
            if req.get("kind"):
                title += f" · {esc(REQ_KIND_LABEL.get(str(req['kind']), req['kind']))}"
            self.emit(f'### <a id="{self._anchor("r", rid)}"></a>{title}', "")
            related = self.findings_for_req(rid)
            conf = [f for f in related if finding_status(f) == "confirmed"]
            done = len(st["passed"]) + len(st["failed"]) + len(st["na"])
            total_crit = done + len(st["skipped"])
            if st["state"] == "full":
                check_line = f"✅ проверено полностью: {count(done, CRITERION)}"
            elif st["state"] == "partial":
                check_line = f"◐ проверено частично: {of_count(done, total_crit, CRITERION_GEN)}"
            else:
                check_line = "✖ не проверено"
            if conf:
                found_line = f"подтверждённых замечаний — {fmt_int(len(conf))}"
            elif st["state"] == "full":
                found_line = "замечаний нет"
            else:
                found_line = "подтверждённых замечаний нет (проверка неполная)"
            review = len(related) - len(conf)
            if review:
                found_line += f", на проверке человеком — {fmt_int(review)}"
            self.emit(f"**Проверка:** {check_line} · **Итог:** {found_line}", "")
            if st["state"] != "full" and st["review_reason"]:
                self.emit(f"**Причина неполной проверки:** {esc(st['review_reason'])}", "")

            evs = [e for e in as_list(req.get("evidence")) if isinstance(e, Mapping)]
            if evs:
                for ev in evs:
                    self.emit_evidence(ev, "Место")
            else:
                self.emit(f"Место: {esc(self.req_place(req))} · опора не указана, показан текст требования", "")
                self.emit(*quote_block(req.get("text", "")), "")

            marks = []
            for bucket in ("passed", "failed", "skipped", "na"):
                marks.extend((code, bucket) for code in st[bucket])
            marks.sort(key=lambda cm: canon.index(cm[0].lower()) if cm[0].lower() in canon else len(canon))
            if marks:
                parts = [f"{CHECK_ICON[bucket]}{NBSP}{esc(criterion_name(code))}" for code, bucket in marks]
                self.emit("**Критерии:** " + " · ".join(parts), "")
            issue_lines = []
            for check in st["checks"]:
                status = str(check.get("status") or "")
                if status in {"issue", "unknown"} and (check.get("reason") or check.get("finding_ids")):
                    links = ", ".join(self.link_finding(x) for x in as_list(check.get("finding_ids")))
                    mark = "✖" if status == "issue" else "⏸"
                    text = f"- {mark} {esc(criterion_name(check.get('criterion')))}: {esc(check.get('reason') or '')}"
                    issue_lines.append(text + (f" → {links}" if links else ""))
            if issue_lines:
                self.emit(*issue_lines, "")

            own = [f for f in related if self.owner_req(f) == rid]
            others = [f for f in related if self.owner_req(f) != rid]
            for f in own:
                self.finding_card(f, level=4)
            if others:
                links = ", ".join(
                    self.link_finding(f.get("id")) + (" (набор)" if f.get("scope") == "set" else "") for f in others
                )
                self.emit(f"**Также затрагивают это требование:** {links}", "")

    # --- карточка замечания ---------------------------------------------

    def finding_card(self, f: Mapping[str, Any], level: int = 4) -> None:
        fid = str(f.get("id"))
        sev = str(f.get("severity") or "").lower()
        status = finding_status(f)
        self.emit(
            f'{"#" * level} <a id="{self._anchor("f", fid)}"></a>{esc(fid)} · {SEVERITY_ICON.get(sev, "")} '
            f"{esc(SEVERITY_LABEL.get(sev, sev or 'серьёзность не указана'))} · {esc(kind_name(f.get('kind')))}",
            "",
        )
        self.emit(f"**Суть:** {esc(f.get('title') or 'не указана')}", "")
        ref = criterion_ref(f.get("criterion"))
        reqs = ", ".join(self.link_req(r) for r in as_list(f.get("req_ids"))) or "—"
        self.emit(
            f"**Критерий:** {esc(criterion_name(f.get('criterion')))}{f' ({esc(ref)})' if ref else ''} · "
            f"**Статус:** {esc(STATUS_LABEL.get(status, status))} · **Требования:** {reqs}",
            "",
        )
        meaning = MEANING_LABEL.get(str(f.get("meaning_status") or ""), "")
        if meaning or f.get("meaning_reason"):
            text = meaning + (f": {f['meaning_reason']}" if f.get("meaning_reason") else "")
            self.emit(f"**Проверка смысла:** {esc(text)}", "")

        evs = evidence_of(f)
        if _is_conflict(f) and len(evs) >= 2:
            for i, ev in enumerate(evs):
                self.emit_evidence(ev, f"Место {chr(ord('А') + i) if i < 2 else i + 1}")
        elif evs:
            label = "Обещание в тексте" if _is_promise(f) else "Место"
            for ev in evs:
                self.emit_evidence(ev, label)
        else:
            self.emit(f"Цитата: в Report нет опоры (`anchor_status` = {esc(f.get('anchor_status') or '—')}).", "")

        inspected = as_list(f.get("inspected_block_ids"))
        if inspected:
            self.emit(f"**Проверено, где описание должно быть:** {esc(self.places_text(inspected))}", "")

        witness = f.get("witness")
        if isinstance(witness, Mapping):
            self.witness_card(f, witness)

        self.emit(f"**Последствия:** {esc(f.get('impact') or 'не указаны в отчёте')}", "")
        if f.get("blocked_decision") or as_list(f.get("blocks")):
            blocks = ", ".join(BLOCKS_LABEL.get(str(b), str(b)) for b in as_list(f.get("blocks")))
            parts = []
            if blocks:
                parts.append(f"блокирует {esc(blocks)}")
            if f.get("blocked_decision"):
                parts.append(f"решение: {esc(f['blocked_decision'])}")
            self.emit(f"**Что блокирует:** {'; '.join(parts)}", "")
        rec = f.get("recommendation")
        self.emit(f"**Что сделать:** {esc(rec) if rec else 'агент не сформулировал; решение за аналитиком'}", "")

        questions = [q for q in self.questions.values() if fid in {str(x) for x in as_list(q.get("finding_ids"))}]
        if questions:
            self.emit("**Вопрос заказчику:** " + ", ".join(self.link_question(q.get("id")) for q in questions), "")
        merged = as_list(f.get("merged_from"))
        if merged:
            self.emit(f"**Объединено при подготовке:** {esc(', '.join(str(m) for m in merged))}", "")
        group = self.group_of.get(fid)
        if group and len(group["members"]) > 1:
            if group["primary"] is f:
                others = ", ".join(
                    f"{self.link_finding(m.get('id'))} ({esc(SEVERITY_LABEL.get(str(m.get('severity')), ''))}, "
                    f"{esc(STATUS_LABEL.get(finding_status(m), finding_status(m)))})"
                    for m in group["others"]
                )
                self.emit(f"**Та же первопричина:** {others} — в сводке дефектов и Jira учтены как один дефект.", "")
            else:
                self.emit(
                    f"**Та же первопричина, что у {self.link_finding(group['primary'].get('id'))}** — "
                    "в сводке дефектов и Jira отдельно не считается.",
                    "",
                )

    def witness_card(self, f: Mapping[str, Any], w: Mapping[str, Any]) -> None:
        reqs = [str(r) for r in as_list(f.get("req_ids"))]
        self.emit(f"> **Карточка-свидетель {esc(f.get('id'))}.** Один сценарий — два несовместимых исхода.")
        self.emit(">")
        self.emit(f"> **Сценарий:** {esc(w.get('input') or 'не указан')}")
        for side, ev_key, out_key, idx in (("А", "evidence_a", "outcome_a", 0), ("Б", "evidence_b", "outcome_b", 1)):
            ev = w.get(ev_key)
            rid = None
            if isinstance(ev, Mapping):
                rid = next((r for r in reqs if ev.get("block_id") in as_list(self.reqs.get(r, {}).get("block_ids"))), None)
            if rid is None and len(reqs) > idx:
                rid = reqs[idx]
            who = f" по {self.link_req(rid)}" if rid else ""
            self.emit(">")
            if isinstance(ev, Mapping):
                self.emit(
                    f"> **Исход {side}{who}:** {esc(w.get(out_key) or 'не указан')}\\",
                    f"> опора: {esc(self.ev_place(ev))} — «{esc(ev.get('quote', ''))}» ({self.evidence_mark(ev)})",
                )
            else:
                self.emit(f"> **Исход {side}{who}:** {esc(w.get(out_key) or 'не указан')} (опора не указана)")
        self.emit("")

    # --- 4. проверка набора ---------------------------------------------

    def set_stage_state(self) -> str | None:
        for s in self.info["stages"]:
            if str(s.get("name")) in SET_STAGE_NAMES:
                return str(s.get("status"))
        return None

    def set_section(self) -> None:
        self.emit("## 4. Проверка всего набора требований", "")
        set_findings = [f for f in self.findings if self.owner_req(f) is None]
        stage = self.set_stage_state()

        self.emit("### 4.1. Критерии набора", "")
        rows = []
        for code in SET_CODES:
            related = [f for f in set_findings if str(f.get("criterion")) == code]
            if related:
                result = "✖ есть замечания"
            elif stage in {"ok", "cached"}:
                result = "✔ замечаний нет"
            elif stage is None:
                result = "✔ замечаний нет (статус этапа не указан)"
            else:
                result = f"⏸ не проверен (этап: {STAGE_STATUS_LABEL.get(stage, stage)})"
            rows.append(
                [
                    esc(criterion_name(code)) + f" ({esc(criterion_ref(code))})",
                    result,
                    ", ".join(self.link_finding(f.get("id")) for f in related) or "—",
                ]
            )
        other_codes = sorted({str(f.get("criterion")) for f in set_findings} - set(SET_CODES))
        for code in other_codes:
            related = [f for f in set_findings if str(f.get("criterion")) == code]
            rows.append([esc(criterion_name(code)), "✖ есть замечания", ", ".join(self.link_finding(f.get("id")) for f in related)])
        self.emit(*table(["Критерий", "Результат", "Замечания"], rows), "")

        conflicts = [f for f in set_findings if _is_conflict(f)]
        coverage = [f for f in set_findings if f not in conflicts and _is_coverage(f)]
        omissions = [f for f in set_findings if f not in conflicts and f not in coverage and _is_omission(f)]
        rest = [f for f in set_findings if f not in conflicts and f not in coverage and f not in omissions]

        self.emit("### 4.2. Противоречия", "")
        for f in conflicts:
            self.finding_card(f, level=4)
        if not conflicts:
            self.emit("Противоречий между требованиями в Report нет.", "")

        self.emit("### 4.3. Пропуски и полнота", "")
        for f in omissions:
            self.finding_card(f, level=4)
        if not omissions:
            self.emit("Пропусков на уровне набора в Report нет.", "")

        self.emit("### 4.4. Покрытие критериями приёмки", "")
        self.acceptance_table()
        for f in coverage:
            self.finding_card(f, level=4)

        self.emit("### 4.5. Прочие замечания к набору", "")
        for f in rest:
            self.finding_card(f, level=4)
        if not rest:
            self.emit("Других замечаний к набору нет.", "")

    def acceptance_table(self) -> None:
        items = [c for c in as_list(self.r.get("coverage")) if isinstance(c, Mapping)]
        if not items:
            self.emit("Матрицы «требование — критерий приёмки» в Report нет (`coverage` пуст).", "")
            return
        rows = []
        for c in items:
            acc = []
            for a in as_list(c.get("acceptance_ids")):
                if str(a) in self.reqs:
                    acc.append(f"{self.link_req(a)}: {esc(shorten(self.reqs[str(a)].get('text'), 80))}")
                else:
                    acc.append(esc(a))
            status = str(c.get("status") or "unknown")
            rows.append(
                [
                    self.link_req(c.get("req_id")),
                    esc(c.get("obligation") or "—"),
                    "<br>".join(acc) or "нет",
                    COVERAGE_LABEL.get(status, esc(status)),
                    esc(c.get("explanation") or "—") if status != "covered" else "—",
                ]
            )
        self.emit(
            *table(["Требование", "Обязательство", "Критерий приёмки из документа", "Покрытие", "Что не покрыто"], rows), ""
        )
        covered = sum(1 for c in items if c.get("status") == "covered")
        self.emit(
            f"Покрыто полностью: {fmt_ratio(covered, len(items), ('обязательства', 'обязательств', 'обязательств'))} "
            "из матрицы покрытия.",
            "",
        )

    # --- 5. сводка ------------------------------------------------------

    def summary(self) -> None:
        n = self.nums
        total = n["requirements_total"]
        full = n["requirements_reviewed"]
        self.emit("## 5. Сводка", "")
        sev_all = (
            f"🔴 {fmt_int(n['findings_critical'])} · 🟠 {fmt_int(n['findings_major'])} · 🟡 {fmt_int(n['findings_minor'])}"
        )
        sev_unique = (
            f"🔴 {fmt_int(n['defects_critical'])} · 🟠 {fmt_int(n['defects_major'])} · 🟡 {fmt_int(n['defects_minor'])}"
        )
        audit = self.info["evidence_audit"]
        rows = [
            [SUMMARY_ROWS["total"], f"{fmt_int(total)} (с ID документа — {fmt_int(n['requirements_with_source_id'])}, "
             f"ID агента — {fmt_int(n['requirements_agent_ids'])})"],
            [SUMMARY_ROWS["reviewed"], fmt_ratio(full, total, REQ_GEN)],
            [SUMMARY_ROWS["partial"], fmt_ratio(n["requirements_partial"], total, REQ_GEN)],
            [SUMMARY_ROWS["not_reviewed"], fmt_ratio(n["requirements_not_reviewed"], total, REQ_GEN)],
            [SUMMARY_ROWS["clean"], f"{of_count(n['requirements_clean'], full, REQ_GEN)}, проверенных полностью"],
            [SUMMARY_ROWS["findings"], f"{fmt_int(n['findings_total'])}: {sev_all}"],
            [SUMMARY_ROWS["status"],
             f"подтверждено {fmt_int(n['findings_confirmed'])}, на проверке человеком {fmt_int(n['findings_needs_review'])}"],
            [SUMMARY_ROWS["unique"], f"{fmt_int(n['defects_unique'])}: {sev_unique}"],
            [SUMMARY_ROWS["merged"],
             f"кандидатов в `merged_from`: {fmt_int(n['merged_candidates'])}; подтверждённых замечаний "
             f"с общей первопричиной: {fmt_int(n['same_cause_merged'])}"],
            [SUMMARY_ROWS["rejected"], fmt_int(n["rejected"])],
            [SUMMARY_ROWS["checks"],
             f"{fmt_int(n['checks_pass'])} выполнено · {fmt_int(n['checks_issue'])} нарушено · "
             f"{fmt_int(n['checks_unknown'])} не проверено · {fmt_int(n['checks_na'])} не применимо"],
            [SUMMARY_ROWS["evidence"],
             f"{fmt_ratio(n['evidence_verified'], n['evidence_total'], QUOTE_GEN)}; "
             f"не совпали или без блока — {fmt_int(n['evidence_failed'])}"],
        ]
        if audit:
            checked = int(audit.get("checked") or 0)
            rows.append(
                [
                    "Опоры по журналу движка",
                    f"подтверждено {fmt_ratio(int(audit.get('confirmed') or 0), checked, OPORA_GEN)}; "
                    f"неоднозначных — {fmt_int(int(audit.get('ambiguous') or 0))}, "
                    f"отклонено — {fmt_int(int(audit.get('rejected') or 0))}",
                ]
            )
        mismatches = summary_mismatches(self.r)
        if mismatches:
            rows.append(["⚠️ Сверка `summary`", esc("; ".join(mismatches))])
            self.exporter_notes.extend(mismatches)
        self.emit(*table(["Показатель", "Значение"], rows), "")
        note = (
            "Знаменатели: доли требований — от всех выделенных требований; «без замечаний» — от проверенных "
            "полностью; «Замечаний в Report» и «По статусу» — значения `summary`; «Уникальных дефектов» — "
            "подтверждённые замечания после объединения по первопричине (`cause`); цитаты — от всех опор "
            "замечаний, сверка `block.text[start:end] == quote` выполнена при экспорте."
        )
        if audit and audit.get("note"):
            note += f" Журнал движка: {esc(audit['note'])}"
        self.emit(note, "")

        self.emit("**Критичные дефекты по категориям п. 6 ТЗ**", "")
        cats: dict[str, list[str]] = {"contradictory": [], "unverifiable": [], "incomplete": [], "other": []}
        for g in self.groups:
            if g["confirmed"] and g["severity"] == "critical":
                cats[critical_category(g["primary"])].append(self.link_finding(g["primary"].get("id")))
        rows = [
            ["Противоречивые", ", ".join(cats["contradictory"]) or "—"],
            ["Непроверяемые", ", ".join(cats["unverifiable"]) or "—"],
            ["Неполные", ", ".join(cats["incomplete"]) or "—"],
        ]
        if cats["other"]:
            rows.append(["Прочие критичные", ", ".join(cats["other"])])
        self.emit(*table(["Категория", "Дефекты"], rows), "")

        marker = {**n, "source_sha256": self.info["source_sha256"], "schema_version": self.r.get("schema_version")}
        self.emit(f"<!-- {SUMMARY_MARKER} {json.dumps(marker, ensure_ascii=False, sort_keys=True)} -->", "")

    # --- 6. итог --------------------------------------------------------

    def conclusion(self) -> None:
        self.emit("## 6. Итог и приоритетные правки", "")
        for part, label in (("development", "Разработка"), ("testing", "Тестирование")):
            shown, reasons, _ = self.readiness_cell(part)
            ids = verdict_part(self.r, part)["finding_ids"]
            tail = f" Связано: {', '.join(self.link_finding(b) for b in ids)}." if ids else ""
            reason_text = "; ".join(esc(r) for r in reasons)
            self.emit(f"- **{label}:** {shown}.{(' ' + reason_text + '.') if reason_text else ''}{tail}")
        verdict = self.r.get("verdict") if isinstance(self.r.get("verdict"), Mapping) else {}
        if verdict.get("basis"):
            self.emit(f"- **Правило вердикта:** {esc(verdict['basis'])}")
        self.blank()
        actions = first_actions(self.r)
        self.emit("**Первые действия (из verdict):**", "")
        if actions:
            for i, a in enumerate(actions, 1):
                self.emit(f"{i}. {self.action_text(a)}")
            self.blank()
        else:
            self.emit("В `verdict.first_actions` действий нет.", "")

        self.emit("**Приоритетные правки** — подтверждённые дефекты по убыванию серьёзности, один пункт на первопричину:", "")
        groups = [g for g in self.groups if g["confirmed"]]
        groups.sort(key=lambda g: (severity_rank(g["primary"]), self.groups.index(g)))
        if not groups:
            self.emit("Подтверждённых дефектов нет.", "")
            return
        for i, g in enumerate(groups, 1):
            f = g["primary"]
            reqs = ", ".join(self.link_req(r) for r in as_list(f.get("req_ids")))
            parts = [f"{i}. {SEVERITY_ICON.get(g['severity'], '')} {self.link_finding(f.get('id'))} {esc(f.get('title') or '')}"]
            if g["others"]:
                parts.append("(+ " + ", ".join(self.link_finding(m.get("id")) for m in g["others"]) + ")")
            if reqs:
                parts.append(f"— {reqs}")
            if f.get("recommendation"):
                parts.append(f"— {esc(f['recommendation'])}")
            self.emit(" ".join(parts))
        self.blank()

    # --- приложения -----------------------------------------------------

    def appendices(self) -> None:
        self.emit("## Приложения", "")
        self.checklist()
        self.questions_section()
        self.acceptance_tests()
        self.decisions_section()
        self.facts()
        self.rejected_section()
        self.warnings_section()
        self.method()

    def checklist(self) -> None:
        items = [c for c in as_list(self.r.get("checklist")) if isinstance(c, Mapping)]
        self.emit("### А. Чек-лист ревью требований", "")
        if not items:
            self.emit("В Report нет заполненного чек-листа (`checklist` пуст).", "")
            return
        self.emit(
            "Отметки проставлены агентом по найденным замечаниям — это **предложение модели**, "
            "окончательную отметку ставит ответственный за ревью.",
            "",
        )
        rows = []
        for c in items:
            refs = [self.link_finding(x) for x in as_list(c.get("finding_ids"))]
            evs = [e for e in as_list(c.get("evidence")) if isinstance(e, Mapping)]
            basis = esc(c.get("note") or "")
            if refs:
                basis = (basis + "<br>" if basis else "") + "Замечания: " + ", ".join(refs)
            if evs:
                places = "; ".join(self.idx.short_place(e.get("block_id"), e.get("start"), e.get("end")) for e in evs)
                basis = (basis + "<br>" if basis else "") + "Опора: " + esc(places)
            rows.append(
                [
                    esc(c.get("text") or "—"),
                    esc(CHECK_MARK.get(str(c.get("available")), c.get("available") or "—")),
                    esc(CHECK_MARK.get(str(c.get("checked")), c.get("checked") or "—")),
                    basis or "—",
                ]
            )
        self.emit(*table(["Пункт", "Создано или доступно", "Проверено", "Обоснование агента"], rows), "")

    def answer_for(self, qid: str) -> Mapping[str, Any] | None:
        for d in self.decisions:
            if str(d.get("question_id")) == qid:
                return d
        return None

    def questions_section(self) -> None:
        self.emit("### Б. Уточняющие вопросы заказчику", "")
        if not self.questions:
            self.emit("Вопросов в Report нет.", "")
            return
        rows = []
        answered = 0
        for qid, q in self.questions.items():
            refs = [self.link_finding(x) for x in as_list(q.get("finding_ids"))]
            refs += [self.link_req(x) for x in as_list(q.get("affected_req_ids"))]
            options = "<br>".join(f"{i}) {esc(o)}" for i, o in enumerate(as_list(q.get("options")), 1)) or "—"
            decision = self.answer_for(qid)
            if decision:
                answered += 1
                answer = f"**{esc(decision.get('answer') or '')}**"
                if decision.get("source_sha256") and decision.get("source_sha256") != self.info["source_sha256"]:
                    answer += "<br>⚠️ ответ дан к другой редакции документа"
            else:
                answer = "нет решения"
            rows.append(
                [f'<a id="{self._anchor("q", qid)}"></a>{esc(qid)}', esc(q.get("prompt") or "—"), ", ".join(refs) or "—",
                 options, answer]
            )
        self.emit(*table(["ID", "Вопрос", "Связано", "Варианты (предложение модели)", "Решение заказчика"], rows), "")
        self.emit(f"Решено заказчиком: {of_count(answered, len(self.questions), ('вопроса', 'вопросов', 'вопросов'))}.", "")

    def acceptance_tests(self) -> None:
        items = [t for t in as_list(self.r.get("test_cases")) if isinstance(t, Mapping)]
        self.emit("### В. Приёмка и черновик тест-кейсов", "")
        self.emit(
            "Критерии приёмки **из документа** — в разделе 4.4. Ниже — **черновик агента** "
            "(предложение модели), его утверждает заказчик или тестировщик.",
            "",
        )
        if not items:
            self.emit("Тест-кейсов в Report нет.", "")
            return
        rows = []
        for t in items:
            qid = t.get("open_question_id")
            if qid:
                state = "решено заказчиком" if self.answer_for(str(qid)) else "ждёт решения"
                open_q = f"{self.link_question(qid)} — {state}"
            else:
                open_q = "—"
            rows.append(
                [
                    esc(t.get("id") or "—"),
                    ", ".join(self.link_req(r) for r in as_list(t.get("req_ids"))) or "—",
                    esc(t.get("precondition") or "—"),
                    esc(t.get("action") or "—"),
                    esc(t.get("expected") or "—"),
                    open_q,
                ]
            )
        self.emit(*table(["ID", "Требования", "Предусловие", "Действие", "Ожидаемый результат", "Открытый вопрос"], rows), "")

    def decisions_section(self) -> None:
        self.emit("### Г. Решения заказчика и версии документа", "")
        if self.decisions:
            rows = []
            for d in self.decisions:
                edits = as_list(d.get("edits"))
                sha = str(d.get("source_sha256") or "")
                version = "текущая редакция" if sha == self.info["source_sha256"] else f"редакция `{esc(sha[:12])}…`"
                rows.append(
                    [
                        self.link_question(d.get("question_id")),
                        f"**{esc(d.get('answer') or '—')}**",
                        fmt_int(len(edits)) if edits else "нет",
                        version,
                        esc(d.get("note") or "—"),
                    ]
                )
            self.emit(*table(["Вопрос", "Решение заказчика", "Правок текста", "К какой версии", "Источник"], rows), "")
        else:
            self.emit("Решений заказчика в Report нет (`decisions` пуст; ответы передаются через `--answers`).", "")
        diff = self.r.get("diff")
        if isinstance(diff, Mapping) and diff:
            prev = (diff.get("previous") or {}).get("source_sha256", "")
            cur = (diff.get("current") or {}).get("source_sha256", "")
            self.emit(f"Сравнение редакций (`--compare`): было `{esc(str(prev)[:12])}…` → стало `{esc(str(cur)[:12])}…`.", "")
            rows = []
            for key, label in (("resolved", "Устранено"), ("persisting", "Осталось"), ("introduced", "Появилось"),
                               ("unassessed", "Не оценено")):
                entries = [e for e in as_list(diff.get(key)) if isinstance(e, Mapping)]
                details = "<br>".join(
                    esc(f"{', '.join(map(str, as_list(e.get('old_ids')))) or '—'} → "
                        f"{', '.join(map(str, as_list(e.get('new_ids')))) or '—'}: {e.get('reason') or ''}")
                    for e in entries
                )
                rows.append([label, fmt_int(len(entries)), details or "—"])
            self.emit(*table(["Изменение", "Замечаний", "Подробности"], rows), "")
            impacted = as_list(diff.get("impacted_req_ids"))
            if impacted:
                self.emit("Затронутые требования: " + ", ".join(self.link_req(r) for r in impacted), "")
        else:
            self.emit("Сравнение с предыдущей редакцией не выполнялось (`diff` = null).", "")

    def facts(self) -> None:
        items = [x for x in as_list(self.r.get("facts")) if isinstance(x, Mapping)]
        if not items:
            return
        self.emit("### Д. Факты документа", "")
        rows = []
        for x in items:
            evs = [e for e in as_list(x.get("evidence")) if isinstance(e, Mapping)]
            place = "; ".join(self.ev_place(e) for e in evs) or "опора не указана"
            value = x.get("value")
            value_text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            if x.get("unit"):
                value_text += f" {x['unit']}"
            rows.append(
                [
                    esc(x.get("id") or "—"),
                    esc(f"{x.get('subject') or ''} — {x.get('field') or ''}".strip(" —")),
                    esc(value_text),
                    ", ".join(self.link_req(r) for r in as_list(x.get("req_ids"))) or "—",
                    esc(place),
                ]
            )
        self.emit(*table(["ID", "Факт", "Значение", "Требования", "Опора"], rows), "")

    def rejected_section(self) -> None:
        items = rejected_items(self.r)
        if not items:
            return
        self.emit("### Е. Снятые замечания", "")
        self.emit("<details>")
        self.emit(f"<summary>Снято при самопроверке: {count(len(items), FINDING)}. Причины — внутри.</summary>", "")
        for item in items:
            cand = item.get("candidate") if isinstance(item.get("candidate"), Mapping) else {}
            reqs = ", ".join(self.link_req(r, with_source=False) for r in as_list(cand.get("req_ids"))) or "—"
            stage = f", этап {esc(item['stage'])}" if item.get("stage") else ""
            self.emit(
                f"- {esc_lead(cand.get('title') or 'без названия')} ({reqs}{stage}). "
                f"Причина снятия: {esc(item.get('reason') or 'не указана')}"
            )
        self.emit("", "</details>", "")

    def all_warnings(self) -> list[str]:
        doc = self.r.get("document") or {}
        out = [warning_text(w) for w in as_list(self.r.get("warnings"))]
        out += ["Документ: " + warning_text(w) for w in as_list(doc.get("warnings"))]
        return out

    def warnings_section(self) -> None:
        warnings = self.all_warnings() + [f"Экспорт: {n}" for n in self.exporter_notes]
        self.emit("### Ж. Предупреждения", "")
        if not warnings:
            self.emit("Предупреждений нет.", "")
            return
        for w in warnings:
            self.emit(f"- {esc_lead(w)}")
        self.blank()

    def method(self) -> None:
        used: list[str] = []
        codes = [str(f.get("criterion") or "") for f in self.findings]
        codes += [code for st in self.states.values() for b in ("passed", "failed", "skipped", "na") for code in st[b]]
        for code in codes:
            if code and code not in used:
                used.append(code)
        canon = list(CRITERIA)
        used.sort(key=lambda c: canon.index(c) if c in canon else len(canon))
        self.emit("### З. Методика: использованные критерии", "")
        rows = [[f"`{c.replace('`', '')}`", esc(criterion_name(c)), esc(criterion_ref(c) or "—")] for c in used]
        rows += [[f"`{c}`", esc(criterion_name(c)), esc(criterion_ref(c))] for c in SET_CODES if c not in used]
        self.emit(*table(["Код", "Свойство", "Пункт стандарта"], rows), "")
        self.emit(
            "Серьёзность: 🔴 критичное — блокирует разработку или тестирование; 🟠 существенное — высокий риск "
            "неверной реализации; 🟡 незначительное — оформление и стиль.",
            "",
        )

    def render(self) -> str:
        self.header()
        self.first_screen()
        self.passport()
        self.slicing()
        self.per_requirement()
        self.set_section()
        self.summary()
        self.conclusion()
        self.appendices()
        while self.out and self.out[-1] == "":
            self.out.pop()
        return "\n".join(self.out) + "\n"


# Все коды критериев v1 имеют подписи.
assert set(INDIVIDUAL_CODES) | set(SET_CODES) == set(CRITERIA)


# --------------------------------------------------------------------------
# Публичные функции
# --------------------------------------------------------------------------


def render_markdown(report: Any) -> str:
    """Отчёт в виде строки Markdown."""
    return _Renderer(report).render()


def write_markdown(report: Any, output_path: str | os.PathLike[str]) -> Path:
    """Записать отчёт в файл UTF-8 и вернуть путь. Запись атомарная."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_markdown(report)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


_MARKER_RE = re.compile(r"<!-- " + re.escape(SUMMARY_MARKER) + r" (\{.*?\}) -->")


def _row_numbers(md: str, label: str) -> list[int]:
    for line in md.splitlines():
        if line.startswith(f"| {label} |"):
            cell = line.split(" | ", 2)[1] if " | " in line else ""
            return [int(x.replace(NBSP, "")) for x in re.findall(r"\d+(?: \d{3})*", cell)]
    return []


def check_markdown(markdown: str | os.PathLike[str], report: Any) -> list[str]:
    """Сверить числа отчёта Markdown с Report. Пустой список — расхождений нет.

    Проверяются: скрытый маркер сводки против пересчёта из Report, видимые
    строки сводки против Report и равенство SHA-256 входа.
    """
    if isinstance(markdown, os.PathLike) or (isinstance(markdown, str) and "\n" not in markdown and Path(markdown).exists()):
        md = Path(markdown).read_text(encoding="utf-8")
    else:
        md = str(markdown)
    data = as_report_dict(report)
    problems: list[str] = []
    m = _MARKER_RE.search(md)
    if not m:
        return ["В Markdown нет маркера сводки"]
    marker = json.loads(m.group(1))
    expected = summary_numbers(data)
    for key, value in expected.items():
        if marker.get(key) != value:
            problems.append(f"{key}: в Markdown {marker.get(key)!r}, в Report {value!r}")
    sha = run_info(data)["source_sha256"]
    if marker.get("source_sha256") != sha:
        problems.append(f"source_sha256: в Markdown {marker.get('source_sha256')!r}, в Report {sha!r}")
    e = expected
    visible = {
        SUMMARY_ROWS["total"]: [e["requirements_total"]],
        SUMMARY_ROWS["reviewed"]: [e["requirements_reviewed"], e["requirements_total"]],
        SUMMARY_ROWS["partial"]: [e["requirements_partial"], e["requirements_total"]],
        SUMMARY_ROWS["not_reviewed"]: [e["requirements_not_reviewed"], e["requirements_total"]],
        SUMMARY_ROWS["findings"]: [e["findings_total"], e["findings_critical"], e["findings_major"], e["findings_minor"]],
        SUMMARY_ROWS["status"]: [e["findings_confirmed"], e["findings_needs_review"]],
        SUMMARY_ROWS["unique"]: [e["defects_unique"], e["defects_critical"], e["defects_major"], e["defects_minor"]],
        SUMMARY_ROWS["rejected"]: [e["rejected"]],
        SUMMARY_ROWS["checks"]: [e["checks_pass"], e["checks_issue"], e["checks_unknown"], e["checks_na"]],
        SUMMARY_ROWS["evidence"]: [e["evidence_verified"], e["evidence_total"]],
    }
    for label, want in visible.items():
        got = _row_numbers(md, label)
        if got[: len(want)] != want:
            problems.append(f"строка сводки «{label}»: видно {got[: len(want)]}, ожидалось {want}")
    return problems


def _main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--check":
        problems = check_markdown(Path(argv[1]), Path(argv[2]))
        if problems:
            print("Расхождения:", *problems, sep="\n  ")
            return 4
        print("Числа отчёта совпадают с Report.")
        return 0
    if len(argv) == 2:
        print(write_markdown(Path(argv[0]), argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
