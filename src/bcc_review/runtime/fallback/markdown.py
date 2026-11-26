"""Резервный экспорт отчёта в Markdown (пока не влит модуль №17 ``bcc_review.exports.markdown``).

Строит русский отчёт из канонического ``Report`` и ничего не пересчитывает: числа сводки — из
``report["summary"]``, места — из ``block.loc``. Разделы идут в порядке п. 6 ТЗ: итог, паспорт,
методика, нарезка, проверка каждого требования, проверка набора, замечания, сводка, приложения.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from . import report_common as rc

_APPENDIX_LETTERS = "АБВГДЕЖИКЛМН"


class _Ctx:
    """Отчёт и индексы, общие для всех разделов."""

    def __init__(self, report: Mapping[str, Any]):
        self.report = report
        self.run: Mapping[str, Any] = report.get("run") or {}
        self.document: Mapping[str, Any] = report.get("document") or {}
        self.summary: Mapping[str, Any] = report.get("summary") or {}
        self.blocks = rc.block_index(report)
        self.findings = rc.finding_index(report)
        self.reqs = rc.requirement_index(report)
        self.complete = rc.run_complete(report)

    # ---- ссылки и места
    def link(self, finding_id: str) -> str:
        if finding_id in self.findings:
            return f"[{finding_id}](#{rc.finding_anchor(finding_id)})"
        return f"{finding_id} (нет в списке замечаний)"

    def links(self, finding_ids: Iterable[str]) -> str:
        return ", ".join(self.link(fid) for fid in rc.unique(finding_ids))

    def loc(self, ref: Any) -> str:
        return rc.describe_location(self.report, ref, index=self.blocks)

    def place(self, ref: Any) -> str:
        return rc.describe_place(self.report, ref, index=self.blocks)

    def req_label(self, req_id: str) -> str:
        req = self.reqs.get(req_id)
        if req is None:
            return f"{req_id} (нет в нарезке)"
        source_id = req.get("source_id")
        return f"{req_id} ({source_id})" if source_id else req_id

    def finding_places(self, finding: Mapping[str, Any]) -> str:
        """Где искать замечание в документе: сверенные опоры, иначе блоки подсказок модели."""
        evidence = rc.finding_evidence(finding)
        if evidence:
            return "; ".join(rc.unique(self.loc(ev) for ev in evidence))
        hinted = rc.unique(self.loc(h["block_id"]) for h in finding.get("hints") or [] if h.get("block_id"))
        if hinted:
            return "по подсказке модели, цитата не сверена: " + "; ".join(hinted)
        inspected = rc.unique(self.loc(b) for b in finding.get("inspected_block_ids") or [])
        if inspected:
            return "просмотренные фрагменты: " + "; ".join(inspected)
        return "место в документе не установлено"

    def finding_line(self, finding: Mapping[str, Any], *, with_severity: bool = False) -> str:
        """Одна строка о замечании: ссылка, тип, заголовок, место, требования, статус."""
        parts = [self.link(finding["id"])]
        if with_severity:
            parts.append(rc.severity_label(finding.get("severity")))
        parts.append(rc.kind_label(finding.get("kind")))
        line = " · ".join(parts) + f": {rc.md_inline(finding.get('title'))} — {self.finding_places(finding)}"
        req_ids = finding.get("req_ids") or []
        if req_ids:
            line += " · " + ", ".join(self.req_label(r) for r in req_ids)
        if finding.get("status") != "confirmed":
            line += f", {rc.label(rc.FINDING_STATUS_LABELS, finding.get('status'))}"
        return line

    def incomplete_sentence(self) -> str:
        return _cap(rc.incomplete_note(self.report)) + "."

    def summary_value(self, *path: str) -> str:
        value: Any = self.summary
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                return "не указано"
            value = value[key]
        return str(value)


# --------------------------------------------------------------------------- мелкие помощники
def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "не указано" if value is None else str(value)


def _table(header: Iterable[str], rows: Iterable[Iterable[Any]], align: Optional[Iterable[str]] = None) -> list[str]:
    header = list(header)
    align = list(align) if align is not None else [":---"] * len(header)
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    for row in rows:
        out.append("| " + " | ".join(rc.md_cell(c) for c in row) + " |")
    return out


def _quote(text: Any) -> str:
    return f"«{rc.md_inline(text)}»"


def _json_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "не указано" if value is None else str(value)


# --------------------------------------------------------------------------- 1. Итог
def _verdict(ctx: _Ctx) -> list[str]:
    verdict = ctx.report.get("verdict") or {}
    out = ["## 1. Итог", ""]
    if not ctx.complete:
        out += [f"> **Проверка неполная.** {ctx.incomplete_sentence()} "
                "Выводы относятся только к проверенной части документа.", ""]

    rows = []
    for key, name in (("development", "Разработка"), ("testing", "Тестирование")):
        readiness = verdict.get(key) or {}
        status = rc.label(rc.READINESS_LABELS, readiness.get("status", "unknown"))
        reasons = "\n".join(readiness.get("reasons") or []) or "причины не указаны"
        ids = readiness.get("finding_ids") or []
        rows.append((name, f"**{status}**", reasons, ctx.links(ids) if ids else "—"))
    out += _table(("Этап", "Готовность", "Почему", "Замечания"), rows) + [""]
    if verdict.get("basis"):
        out += [f"Основание вердикта: {rc.md_inline(verdict['basis'])}", ""]

    out += ["**Критичные замечания**", ""]
    critical = [ctx.findings[fid] for fid in rc.critical_ids(ctx.report) if fid in ctx.findings]
    missing = [fid for fid in rc.critical_ids(ctx.report) if fid not in ctx.findings]
    if critical or missing:
        out += [f"- {ctx.finding_line(f)}" for f in critical]
        out += [f"- {fid}: замечание указано в сводке, но отсутствует в списке замечаний" for fid in missing]
    elif ctx.complete:
        out.append("Критичных замечаний нет.")
    else:
        out.append("Критичных замечаний не найдено, но проверка неполная: отсутствие критичных дефектов не доказано.")
    out.append("")

    out += ["**Что исправить в первую очередь**", ""]
    actions = sorted(verdict.get("first_actions") or [], key=lambda a: a.get("order", 0))
    if actions:
        for action in actions:
            ids = action.get("finding_ids") or []
            tail = f" — {ctx.links(ids)}" if ids else ""
            out.append(f"{action.get('order', '')}. {rc.md_inline(action.get('action'))}{tail}")
    elif ctx.complete:
        out.append("Первоочередных исправлений агент не назначил.")
    else:
        out.append("Первоочередные исправления не сформированы: проверка неполная.")
    return out + [""]


# --------------------------------------------------------------------------- 2. Паспорт
def _passport(ctx: _Ctx) -> list[str]:
    run, doc = ctx.run, ctx.document
    calls = run.get("calls") or {}
    tokens = run.get("tokens") or {}
    budget = run.get("budget") or {}

    status = rc.label(rc.RUN_STATUS_LABELS, run.get("status"))
    if run.get("status_reasons"):
        status += ": " + "; ".join(run["status_reasons"])
    run_id = str(run.get("run_id") or "не указан")
    if run.get("parent_run_id"):
        run_id += f" (родительский прогон {run['parent_run_id']})"
    commit = f"коммит {run['agent_commit']}" if run.get("agent_commit") else "коммит не определён"
    token_text = f"вход {_num(tokens.get('input'))}, выход {_num(tokens.get('output'))}"
    if tokens.get("cache_read"):
        token_text += f", прочитано из кэша провайдера {_num(tokens['cache_read'])}"
    max_tokens = budget.get("max_tokens")
    budget_text = (f"до {_num(budget.get('max_calls'))} вызовов, {_num(budget.get('max_seconds'))} с, "
                   f"токены: {_num(max_tokens) if max_tokens is not None else 'без лимита'}; "
                   f"исчерпан: {rc.yes_no(budget.get('exhausted'))}")
    if budget.get("reason"):
        budget_text += f" ({budget['reason']})"

    rows: list[tuple[str, Any]] = [
        ("Документ", doc.get("title") or "без названия"),
        ("Исходный файл", run.get("source_name") or doc.get("source_name") or "не указан"),
        ("Формат", doc.get("format") or "не указан"),
        ("SHA-256 файла", f"`{run.get('source_sha256') or doc.get('id') or 'не указан'}`"),
        ("ID прогона", run_id),
        ("Начало", rc.format_datetime(run.get("started_at"))),
        ("Окончание", rc.format_datetime(run.get("finished_at"))),
        ("Длительность", rc.format_seconds(run.get("duration_s"))),
        ("Провайдер", rc.label(rc.PROVIDER_LABELS, run.get("provider"))),
        ("Модель (фактическая)", run.get("model") or "модель не вызывалась"),
    ]
    if run.get("requested_model") and run.get("requested_model") != run.get("model"):
        rows.append(("Запрошенная модель", run["requested_model"]))
    seen = run.get("models_seen") or []
    if seen and seen != [run.get("model")]:
        rows.append(("Модели в ответах", ", ".join(seen)))
    rows += [
        ("Версия агента", f"{run.get('agent_version') or 'не указана'}, {commit}"),
        ("Режим", rc.label(rc.RUN_MODE_LABELS, run.get("mode"))),
        ("Статус прогона", status),
        ("Вызовы модели", f"физических {_num(calls.get('physical'))}, из кэша {_num(calls.get('cache_hits'))}, "
                          f"повторов {_num(calls.get('retries'))}, неудачных {_num(calls.get('failed'))}"),
        ("Токены", token_text),
        ("Бюджет", budget_text),
    ]
    if run.get("context_policy"):
        rows.append(("Контекст документа для модели", run["context_policy"]))
    out = ["## 2. Паспорт прогона", ""] + _table(("Параметр", "Значение"), rows) + [""]

    out += ["**Этапы**", ""]
    stages = run.get("stages") or []
    if stages:
        out += _table(("Этап", "Статус", "Вызовы", "Из кэша", "Модель", "Причина"), (
            (s.get("name"), rc.label(rc.STAGE_STATUS_LABELS, s.get("status")), _num(s.get("calls")),
             _num(s.get("cache_hits")), s.get("model") or "—", s.get("reason") or "—")
            for s in stages), (":---", ":---", "---:", "---:", ":---", ":---"))
    else:
        out.append("Этапы прогона не зафиксированы.")
    out.append("")

    incomplete = run.get("incomplete_stages") or []
    out.append("Незавершённые этапы: " + (", ".join(incomplete) if incomplete else "нет") + ".")
    out.append("")

    modules = run.get("modules") or {}
    if modules:
        out += ["**Реализации модулей**", ""]
        out += _table(("Модуль", "Реализация"), sorted(modules.items())) + [""]
    else:
        out += ["Реализации модулей в паспорте не указаны.", ""]

    audit = run.get("evidence_audit") or {}
    audit_text = (f"Сверка цитат с текстом документа: проверено {_num(audit.get('checked'))}, "
                  f"подтверждено {_num(audit.get('confirmed'))}, неоднозначно {_num(audit.get('ambiguous'))}, "
                  f"отклонено {_num(audit.get('rejected'))}.")
    if audit.get("note"):
        audit_text += f" {rc.md_inline(audit['note'])}"
    return out + [audit_text, ""]


# --------------------------------------------------------------------------- 3. Методика
def _method(ctx: _Ctx) -> list[str]:
    out = [
        "## 3. Методика и критерии", "",
        "Каждое требование проверяется по свойствам ISO/IEC/IEEE 29148:2018 п. 5.2.5 (коды И1–И9), "
        "набор требований — по п. 5.2.6 того же стандарта и IEEE 830-1998 п. 4.3 (коды Н1–Н8). "
        "Цитаты сверяются программой с текстом документа, а место (строка, страница, абзац) вычисляется "
        "по исходному файлу. Статус «подтверждено» ставится только замечанию, цитата которого найдена "
        "в тексте; остальные помечены «требует проверки».", "",
    ]
    rows = [(rc.criterion_code(c), rc.criterion_name(c), rc.criterion_clause(c), rc.CRITERIA[c][3])
            for c in rc.INDIVIDUAL_ORDER + rc.SET_ORDER if c in rc.CRITERIA]
    out += _table(("Код", "Критерий", "Пункт стандарта", "Что проверяется"), rows) + [""]
    out += _table(("Серьёзность", "Когда ставится"), (
        ("критичное", "блокирует разработку или тестирование: противоречие, непроверяемое или неполное "
                      "ключевое правило, нереализуемость"),
        ("существенное", "высокий риск неверной реализации"),
        ("незначительное", "оформление, стиль, терминология"),
    ))
    return out + [""]


# --------------------------------------------------------------------------- 4. Нарезка
def _inventory(ctx: _Ctx) -> list[str]:
    out = ["## 4. Нарезка требований", "",
           f"Выделено требований: {ctx.summary_value('requirements')}, "
           f"проверено: {ctx.summary_value('reviewed_requirements')}.", ""]
    reqs = ctx.report.get("requirements") or []
    if reqs:
        with_status = any(r.get("review_status", "reviewed") != "reviewed" for r in reqs)
        header = ["ID в отчёте", "ID в документе", "Краткая формулировка", "Место"]
        if with_status:
            header.append("Статус проверки")
        rows = []
        for r in reqs:
            row = [r.get("id"), r.get("source_id") or "нет (ID присвоен агентом)", rc.short_text(r.get("text"), 200),
                   "; ".join(rc.requirement_locations(ctx.report, r, index=ctx.blocks)) or "место не установлено"]
            if with_status:
                status = rc.label(rc.REVIEW_STATUS_LABELS, r.get("review_status", "reviewed"))
                if r.get("review_reason"):
                    status += f": {r['review_reason']}"
                row.append(status)
            rows.append(row)
        out += _table(header, rows)
    elif ctx.complete:
        out.append("Агент не выделил в документе ни одного требования.")
    else:
        out.append(f"Требования не выделены. {ctx.incomplete_sentence()}")
    out += ["", "**Исключённые фрагменты**", ""]

    if "excluded" not in ctx.report:
        out.append("Сведения об исключённых фрагментах в отчёт не переданы.")
    elif not ctx.report["excluded"]:
        out.append("Агент не исключал фрагменты документа из нарезки.")
    else:
        for item in ctx.report["excluded"]:
            parts = []
            for block_id in item.get("block_ids") or []:
                block = ctx.blocks.get(block_id)
                text = f" {_quote(rc.short_text(block.get('text'), 80))}" if block else ""
                parts.append(f"{block_id}{text} ({ctx.loc(block_id)})")
            where = "; ".join(parts) or "блоки не указаны"
            out.append(f"- {where} — {rc.md_inline(item.get('reason') or 'причина не указана')}")
    return out + [""]


# --------------------------------------------------------------------------- 5. Каждое требование
def _merge_status(current: Optional[str], new: str) -> str:
    if current is None:
        return new
    return max(current, new, key=lambda s: rc.CHECK_STATUS_WEIGHT.get(s, 0))


def _individual(ctx: _Ctx) -> list[str]:
    checks = ctx.report.get("checks") or []
    reqs = ctx.report.get("requirements") or []
    out = ["## 5. Проверка каждого требования", ""]
    if not reqs:
        out.append("Проверять нечего: нарезка не дала требований." if ctx.complete
                   else f"Поэлементная проверка не выполнена. {ctx.incomplete_sentence()}")
        return out + [""]

    columns = list(rc.INDIVIDUAL_ORDER)
    for check in checks:
        if check.get("criterion") and check["criterion"] not in columns:
            columns.append(check["criterion"])
    cells: dict[tuple[str, str], str] = {}
    by_req: dict[str, list[Mapping[str, Any]]] = {}
    for check in checks:
        key = (check.get("req_id"), check.get("criterion"))
        cells[key] = _merge_status(cells.get(key), check.get("status", "unknown"))
        by_req.setdefault(check.get("req_id"), []).append(check)

    legend = ", ".join(f"{rc.CHECK_STATUS_MARKS[s]} {rc.CHECK_STATUS_LABELS[s]}" for s in rc.CHECK_STATUS_MARKS)
    out += [f"Обозначения: {legend}, {rc.NO_CHECK_MARK} проверка не проводилась. "
            "Коды критериев — в разделе 3.", ""]
    if not checks:
        out += [("Записей поэлементной проверки нет." if ctx.complete
                 else f"Записей поэлементной проверки нет. {ctx.incomplete_sentence()}"), ""]
    rows = []
    for r in reqs:
        row = [ctx.req_label(r["id"])]
        for c in columns:
            status = cells.get((r["id"], c))
            row.append(rc.CHECK_STATUS_MARKS.get(status, "?") if status else rc.NO_CHECK_MARK)
        rows.append(row)
    out += _table(["Требование"] + [rc.criterion_code(c) for c in columns], rows,
                  [":---"] + [":---:"] * len(columns)) + [""]

    out += ["### Результаты по требованиям", ""]
    for r in reqs:
        rid = r["id"]
        linked = [f for f in rc.sorted_findings(ctx.findings.values()) if rid in (f.get("req_ids") or [])]
        for check in by_req.get(rid, []):
            for fid in check.get("finding_ids") or []:
                if fid in ctx.findings and ctx.findings[fid] not in linked:
                    linked.append(ctx.findings[fid])
        places = "; ".join(rc.requirement_locations(ctx.report, r, index=ctx.blocks)) or "место не установлено"
        head = f"**{ctx.req_label(rid)}** — {places}"
        if r.get("review_status", "reviewed") != "reviewed":
            head += f"; {rc.label(rc.REVIEW_STATUS_LABELS, r.get('review_status'))}"
            if r.get("review_reason"):
                head += f": {rc.md_inline(r['review_reason'])}"
        out.append(head)
        out.append("")
        if linked:
            out.append("- Замечания: " + ", ".join(
                f"{ctx.link(f['id'])} ({rc.severity_label(f.get('severity'))})" for f in linked))
        else:
            out.append("- Замечаний по требованию не найдено.")
        passed: dict[str, list[str]] = {"pass": [], "na": []}
        for check in sorted(by_req.get(rid, []), key=lambda c: columns.index(c["criterion"])
                            if c.get("criterion") in columns else len(columns)):
            status = check.get("status", "unknown")
            name = f"{rc.criterion_name(check.get('criterion', ''))} ({rc.criterion_code(check.get('criterion', ''))})"
            if status in passed:
                passed[status].append(name)
                continue
            line = f"- {rc.CHECK_STATUS_MARKS.get(status, '?')} {name}: {rc.md_inline(check.get('reason'))}"
            if check.get("finding_ids"):
                line += f" → {ctx.links(check['finding_ids'])}"
            out.append(line)
        for status, names in passed.items():
            if names:
                out.append(f"- {rc.CHECK_STATUS_MARKS[status]} {_cap(rc.CHECK_STATUS_LABELS[status])}: "
                           + ", ".join(rc.unique(names)))
        if rid not in by_req:
            out.append(f"- {rc.NO_CHECK_MARK} Проверка по критериям для требования не выполнялась.")
        out.append("")
    return out


# --------------------------------------------------------------------------- 6. Набор
def _witness_lines(ctx: _Ctx, witness: Mapping[str, Any], *, full_place: bool = True) -> list[str]:
    """Сценарий-свидетель противоречия: вход и два исхода с цитатами и местами."""
    lines = [f"  - Входная ситуация: {rc.md_inline(witness.get('input'))}"]
    for side in ("a", "b"):
        ev = witness.get(f"evidence_{side}") or {}
        where = ctx.place(ev) if full_place else ctx.loc(ev)
        lines.append(f"  - Исход {side.upper()}: {rc.md_inline(witness.get(f'outcome_{side}'))} — "
                     f"{_quote(ev.get('quote'))}, {where}")
    return lines


def _set_review(ctx: _Ctx) -> list[str]:
    out = ["## 6. Проверка набора", "", "### Замечания к набору требований", ""]
    set_findings = [f for f in rc.sorted_findings(ctx.findings.values()) if f.get("scope") == "set"]
    if set_findings:
        out += [f"- {ctx.finding_line(f, with_severity=True)}" for f in set_findings]
    elif ctx.complete:
        out.append("Замечаний к набору требований не найдено.")
    else:
        out.append(f"Замечаний к набору не найдено, но проверка неполная. {ctx.incomplete_sentence()}")
    out.append("")

    rows = []
    for code in rc.SET_ORDER:
        ids = [f["id"] for f in rc.sorted_findings(ctx.findings.values()) if f.get("criterion") == code]
        empty = "нарушений не выявлено" if ctx.complete else "нарушений не выявлено, проверка неполная"
        rows.append((rc.criterion_code(code), rc.criterion_name(code), ctx.links(ids) if ids else empty))
    out += _table(("Код", "Критерий набора", "Замечания"), rows) + [""]

    out += ["### Противоречия", ""]
    conflicts = [f for f in rc.sorted_findings(ctx.findings.values())
                 if f.get("kind") == "conflict" and f.get("witness")]
    conflicts.sort(key=lambda f: f.get("status") != "confirmed")
    for f in conflicts:
        out.append(f"- {ctx.link(f['id'])} ({rc.label(rc.FINDING_STATUS_LABELS, f.get('status'))}): "
                   f"{rc.md_inline(f.get('title'))}")
        out += _witness_lines(ctx, f["witness"])
    unwitnessed = [f for f in ctx.findings.values() if f.get("kind") == "conflict" and not f.get("witness")]
    if unwitnessed:
        out.append("- Без сценария-свидетеля (требуют проверки): "
                   + "; ".join(f"{ctx.link(f['id'])} — {ctx.finding_places(f)}" for f in unwitnessed))
    if not conflicts and not unwitnessed:
        out.append("Противоречий между требованиями не найдено." if ctx.complete
                   else f"Противоречий не найдено, но проверка неполная. {ctx.incomplete_sentence()}")
    out.append("")

    out += ["### Покрытие критериями приёмки", ""]
    coverage = ctx.report.get("coverage") or []
    if coverage:
        rows = []
        for c in coverage:
            refs = list(c.get("evidence") or [])
            places = rc.unique(ctx.loc(ev) for ev in refs) or rc.unique(
                ctx.loc(h["block_id"]) for h in c.get("hints") or [] if h.get("block_id"))
            rows.append((ctx.req_label(c.get("req_id", "")), c.get("obligation"),
                         ", ".join(c.get("acceptance_ids") or []) or "нет",
                         rc.label(rc.COVERAGE_STATUS_LABELS, c.get("status")), c.get("explanation"),
                         "; ".join(places) or "место не установлено"))
        out += _table(("Требование", "Обязательство", "Критерии приёмки", "Статус", "Пояснение", "Место"), rows)
    elif ctx.complete:
        out.append("Покрытие требований критериями приёмки в этом прогоне не оценивалось.")
    else:
        out.append(f"Покрытие критериями приёмки не оценено. {ctx.incomplete_sentence()}")
    out += ["", "### Факты: числа, сроки, лимиты", ""]

    facts = ctx.report.get("facts") or []
    if facts:
        rows = []
        for fact in facts:
            value = _json_value(fact.get("value"))
            if fact.get("unit"):
                value += f" {fact['unit']}"
            places = rc.unique(ctx.loc(ev) for ev in fact.get("evidence") or [])
            rows.append((fact.get("id"), fact.get("subject"), fact.get("field"), value,
                         ", ".join(ctx.req_label(r) for r in fact.get("req_ids") or []) or "—",
                         "; ".join(places) or "место не установлено"))
        out += _table(("ID", "Объект", "Параметр", "Значение", "Требования", "Место"), rows)
    elif ctx.complete:
        out.append("Числовые параметры в этом прогоне не извлекались.")
    else:
        out.append(f"Числовые параметры не извлечены. {ctx.incomplete_sentence()}")
    return out + [""]


# --------------------------------------------------------------------------- 7. Замечания
def _finding_card(ctx: _Ctx, f: Mapping[str, Any]) -> list[str]:
    fid = f["id"]
    out = [f'<a id="{rc.finding_anchor(fid)}"></a>', "",
           f"### {fid} · {rc.severity_label(f.get('severity'))} · {rc.md_inline(f.get('title'))}", "",
           f"- **Критерий:** {rc.criterion_label(f.get('criterion', ''))}",
           f"- **Тип:** {rc.kind_label(f.get('kind'))}; область: {rc.label(rc.SCOPE_LABELS, f.get('scope'))}"]
    if f.get("req_ids"):
        out.append("- **Требования:** " + ", ".join(ctx.req_label(r) for r in f["req_ids"]))

    evidence = list(f.get("evidence") or [])
    if evidence:
        out.append("- **Цитаты из документа:**")
        out += [f"  - {_quote(ev.get('quote'))} — {ctx.place(ev)}" for ev in evidence]
    else:
        hints = f.get("hints") or []
        if hints:
            out.append("- **Цитаты из документа:** не сверены с текстом, ниже — подсказки модели:")
            out += [f"  - {_quote(h.get('quote'))} — {rc.hint_location(ctx.report, h, index=ctx.blocks)}"
                    for h in hints]
        else:
            out.append(f"- **Цитаты из документа:** нет; {ctx.finding_places(f)}.")

    out.append(f"- **Последствие:** {rc.md_inline(f.get('impact') or 'не указано')}")
    if f.get("blocked_decision"):
        out.append(f"- **Блокирует решение:** {rc.md_inline(f['blocked_decision'])}")
    if f.get("blocks"):
        out.append("- **Блокирует:** " + ", ".join(rc.label(rc.BLOCKS_TARGET_LABELS, b) for b in f["blocks"]))
    if f.get("witness"):
        out.append("- **Сценарий противоречия:**")
        out += _witness_lines(ctx, f["witness"], full_place=False)
    out.append(f"- **Рекомендация:** {rc.md_inline(f.get('recommendation') or 'не сформулирована')}")
    out.append(f"- **Статус:** {rc.label(rc.FINDING_STATUS_LABELS, f.get('status'))}")
    out.append(f"- **Привязка цитаты:** {rc.label(rc.ANCHOR_STATUS_LABELS, f.get('anchor_status'))}")
    meaning = rc.label(rc.MEANING_STATUS_LABELS, f.get("meaning_status"))
    if f.get("meaning_reason"):
        meaning += f" — {rc.md_inline(f['meaning_reason'])}"
    out.append(f"- **Смысл:** {meaning}")
    if f.get("merged_from"):
        out.append("- **Объединено из:** " + ", ".join(f["merged_from"]))
    for note in f.get("notes") or []:
        out.append(f"- **Примечание:** {rc.md_inline(note)}")
    return out + [""]


def _findings(ctx: _Ctx) -> list[str]:
    out = ["## 7. Замечания", ""]
    findings = rc.sorted_findings(ctx.report.get("findings") or [])
    if findings:
        for f in findings:
            out += _finding_card(ctx, f)
        return out
    if ctx.summary.get("findings") == 0 and ctx.complete:
        out.append("Замечаний нет.")
    elif ctx.summary.get("findings"):
        out.append(f"Список замечаний пуст, хотя в сводке их {ctx.summary_value('findings')}: отчёт неполный.")
    else:
        out.append(f"Замечаний не найдено, но проверка неполная. {ctx.incomplete_sentence()} "
                   "Отсутствие замечаний не означает, что в документе нет дефектов.")
    return out + [""]


# --------------------------------------------------------------------------- 8. Сводка
def _summary(ctx: _Ctx) -> list[str]:
    v = ctx.summary_value
    rows = [
        ("Требований выделено", v("requirements")),
        ("Требований проверено", v("reviewed_requirements")),
        ("Замечаний всего", v("findings")),
        ("— критичных", v("by_severity", "critical")),
        ("— существенных", v("by_severity", "major")),
        ("— незначительных", v("by_severity", "minor")),
        ("— подтверждённых", v("by_status", "confirmed")),
        ("— требующих проверки", v("by_status", "needs_review")),
        ("Проверок по критериям: соответствует", v("checks", "pass")),
        ("Проверок по критериям: нарушение", v("checks", "issue")),
        ("Проверок по критериям: не определено", v("checks", "unknown")),
        ("Проверок по критериям: неприменимо", v("checks", "na")),
    ]
    out = ["## 8. Сводка", ""]
    if not ctx.complete:
        out += [f"Числа относятся только к проверенной части документа. {ctx.incomplete_sentence()}", ""]
    out += _table(("Показатель", "Значение"), rows, (":---", "---:")) + ["", "### Критичные дефекты", ""]

    groups: dict[str, list[Mapping[str, Any]]] = {key: [] for key, _, _ in rc.CRITICAL_GROUPS}
    ids = rc.critical_ids(ctx.report)
    for fid in ids:
        if fid in ctx.findings:
            groups[rc.critical_group(ctx.findings[fid])].append(ctx.findings[fid])
    if not ids:
        out.append("Критичных дефектов нет." if ctx.complete
                   else "Критичных дефектов не найдено, но проверка неполная.")
        return out + [""]
    for key, name, _ in rc.CRITICAL_GROUPS:
        if not groups[key]:
            out += [f"**{name}:** нет.", ""]
            continue
        out += [f"**{name}:**", ""]
        out += [f"- {ctx.link(f['id'])}: {rc.md_inline(f.get('title'))} — {ctx.finding_places(f)}"
                for f in groups[key]]
        out.append("")
    return out


# --------------------------------------------------------------------------- 9. Приложения
def _questions(ctx: _Ctx) -> list[str]:
    out: list[str] = []
    for q in ctx.report.get("questions") or []:
        out.append(f"**{q.get('id')}.** {rc.md_inline(q.get('prompt'))}")
        out.append("")
        for k, option in enumerate(q.get("options") or [], 1):
            out.append(f"{k}. {rc.md_inline(option)}")
        links = []
        if q.get("finding_ids"):
            links.append("замечания " + ctx.links(q["finding_ids"]))
        if q.get("affected_req_ids"):
            links.append("требования " + ", ".join(ctx.req_label(r) for r in q["affected_req_ids"]))
        if links:
            out += ["", "Связано: " + "; ".join(links) + "."]
        out.append("")
    return out


def _decisions(ctx: _Ctx) -> list[str]:
    out = []
    for d in ctx.report.get("decisions") or []:
        line = f"- {d.get('question_id')}: {rc.md_inline(d.get('answer'))}"
        edits = d.get("edits") or []
        if edits:
            line += "; правки: " + "; ".join(
                f"{ctx.loc(e)} {_quote(e.get('old'))} → {_quote(e.get('new'))}" for e in edits)
        if d.get("note"):
            line += f" ({rc.md_inline(d['note'])})"
        out.append(line)
    return out + [""]


def _checklist(ctx: _Ctx) -> list[str]:
    rows = []
    for k, row in enumerate(ctx.report.get("checklist") or [], 1):
        places = rc.unique(ctx.loc(ev) for ev in row.get("evidence") or [])
        rows.append((row.get("id") or str(k), row.get("text"),
                     rc.label(rc.CHECK_MARK_LABELS, row.get("available")),
                     rc.label(rc.CHECK_MARK_LABELS, row.get("checked")), row.get("note") or "—",
                     ctx.links(row.get("finding_ids") or []) or "—", "; ".join(places) or "—"))
    return _table(("№", "Пункт чек-листа", "Есть в ТЗ", "Проверено", "Комментарий", "Замечания", "Место"),
                  rows) + [""]


def _test_cases(ctx: _Ctx) -> list[str]:
    rows = [(t.get("id"), t.get("precondition"), t.get("action"), t.get("expected"),
             ", ".join(ctx.req_label(r) for r in t.get("req_ids") or []) or "—",
             t.get("open_question_id") or "—")
            for t in ctx.report.get("test_cases") or []]
    return _table(("ID", "Предусловие", "Действие", "Ожидаемый результат", "Требования", "Открытый вопрос"),
                  rows) + [""]


_DIFF_PARTS = (("resolved", "Устранено"), ("persisting", "Сохраняется"),
               ("introduced", "Появилось в новой редакции"), ("unassessed", "Не удалось оценить"))


def _diff(ctx: _Ctx) -> list[str]:
    diff = ctx.report["diff"]
    prev, cur = diff.get("previous") or {}, diff.get("current") or {}

    def side(info: Mapping[str, Any]) -> str:
        text = f"SHA-256 `{info.get('source_sha256', 'не указан')}`"
        return text + (f", прогон {info['run_id']}" if info.get("run_id") else "")

    out = [f"Предыдущая редакция: {side(prev)}.", "", f"Текущая редакция: {side(cur)}.", ""]
    for key, name in _DIFF_PARTS:
        entries = diff.get(key) or []
        if not entries:
            out += [f"**{name}:** нет.", ""]
            continue
        out += [f"**{name}:**", ""]
        for e in entries:
            old = ", ".join(e.get("old_ids") or []) or "—"
            new = ctx.links(e.get("new_ids") or []) or "—"
            places = rc.unique(ctx.loc(ev) for ev in e.get("evidence") or [])
            tail = f" ({'; '.join(places)})" if places else ""
            out.append(f"- {old} → {new}: {rc.md_inline(e.get('reason'))}{tail}")
        out.append("")
    if diff.get("impacted_req_ids"):
        out += ["Затронутые требования: " + ", ".join(ctx.req_label(r) for r in diff["impacted_req_ids"]) + ".", ""]
    warnings = diff.get("warnings") or []
    if warnings:
        out += [f"- Предупреждение сравнения: {rc.md_inline(rc.warning_text(w))}" for w in warnings] + [""]
    return out


def _warning_line(ctx: _Ctx, warning: Any, origin: str) -> str:
    line = f"- {origin}: {rc.md_inline(rc.warning_text(warning))}"
    if isinstance(warning, Mapping) and warning.get("block_ids"):
        line += " — " + "; ".join(rc.unique(ctx.loc(b) for b in warning["block_ids"]))
    return line


def _warnings(ctx: _Ctx) -> list[str]:
    out = [_warning_line(ctx, w, "прогон") for w in ctx.report.get("warnings") or []]
    out += [_warning_line(ctx, w, "чтение документа") for w in ctx.document.get("warnings") or []]
    return out + [""]


def _rejected(ctx: _Ctx) -> list[str]:
    out = []
    for item in ctx.report.get("rejected") or []:
        cand = item.get("candidate") or {}
        title = cand.get("title") or rc.kind_label(cand.get("kind")) or "кандидат без названия"
        meta = [m for m in (rc.severity_label(cand["severity"]) if cand.get("severity") else "",
                            rc.criterion_label(cand["criterion"]) if cand.get("criterion") else "") if m]
        line = f"- {rc.md_inline(title)}"
        if meta:
            line += f" ({', '.join(meta)})"
        hinted = rc.unique(ctx.loc(h["block_id"]) for h in cand.get("hints") or [] if h.get("block_id"))
        if hinted:
            line += f" — {'; '.join(hinted)}"
        line += f". Причина отклонения: {rc.md_inline(item.get('reason'))}"
        if item.get("stage"):
            line += f" (этап {item['stage']})"
        out.append(line)
    return out + [""]


def _appendices(ctx: _Ctx) -> list[str]:
    report = ctx.report
    has_warnings = bool(report.get("warnings") or ctx.document.get("warnings"))
    parts = [
        ("Вопросы аналитику", bool(report.get("questions")), _questions),
        ("Учтённые ответы аналитика", bool(report.get("decisions")), _decisions),
        ("Чек-лист ревью банка", bool(report.get("checklist")), _checklist),
        ("Черновик тест-кейсов", bool(report.get("test_cases")), _test_cases),
        ("Сравнение с предыдущей редакцией", bool(report.get("diff")), _diff),
        ("Предупреждения", has_warnings, _warnings),
        ("Отклонённые кандидаты", bool(report.get("rejected")), _rejected),
    ]
    out: list[str] = []
    present = [(title, build) for title, ok, build in parts if ok]
    for letter, (title, build) in zip(_APPENDIX_LETTERS, present):
        out += [f"## Приложение {letter}. {title}", ""] + build(ctx)
    return out


# --------------------------------------------------------------------------- сборка
def render_markdown(report: Mapping[str, Any]) -> str:
    ctx = _Ctx(report)
    title = ctx.document.get("title") or ctx.run.get("source_name") or "документ без названия"
    commit = ctx.run.get("agent_commit")
    agent = f"bcc-review {ctx.run.get('agent_version') or ''}".strip() + (f" (коммит {commit})" if commit else "")
    lines = [
        f"# Ревью требований: {rc.md_inline(title)}", "",
        f"Отчёт сформирован автоматически агентом {agent} по файлу "
        f"{ctx.run.get('source_name') or ctx.document.get('source_name') or 'без имени'}, "
        f"прогон {ctx.run.get('run_id') or 'без ID'}, {rc.format_datetime(ctx.run.get('finished_at'))}.", "",
    ]
    for section in (_verdict, _passport, _method, _inventory, _individual, _set_review, _findings, _summary,
                    _appendices):
        lines += section(ctx)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def write_markdown(report: Mapping[str, Any], output_path: str | Path) -> Path:
    """Записать Markdown-отчёт (UTF-8, LF) и вернуть путь к файлу."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return path
