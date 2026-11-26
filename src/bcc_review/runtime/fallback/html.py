"""Резервный экспорт отчёта в один самодостаточный HTML (пока не влит модуль №13 ``bcc_review.exports.html``).

Без внешних ресурсов и без JavaScript: стили встроены, тема следует ``prefers-color-scheme``.
Якоря стабильны: замечание — ``id="finding-<id>"``, блок документа — ``id="block-<id>"``.
Текст документа выводится блок за блоком, каждая опора ``block.text[start:end]`` обёрнута в ``<mark>``
со ссылкой на своё замечание.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from . import report_common as rc

_CSS = """
:root {
  --bg: #f7f6f2; --fg: #1f1f22; --muted: #5d6066; --line: #dedad1; --card: #ffffff;
  --accent: #0b57a4; --mark: #ffe48a; --mark-fg: #1f1f22;
  --crit: #a8231b; --crit-bg: #fbe4e1; --major: #8a5300; --major-bg: #fdeccb;
  --minor: #35622f; --minor-bg: #e3f1de; --ok: #2f6b2a; --bad: #a8231b; --unk: #7a6a00;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141416; --fg: #e7e5df; --muted: #a2a3a8; --line: #34343a; --card: #1d1d21;
    --accent: #7db4ff; --mark: #6b5a12; --mark-fg: #fff6d5;
    --crit: #ff8a80; --crit-bg: #3d1a18; --major: #ffc266; --major-bg: #3a2a10;
    --minor: #9fd494; --minor-bg: #1c3019; --ok: #9fd494; --bad: #ff8a80; --unk: #e5d36a;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
header.top { padding: 24px 16px 12px; border-bottom: 1px solid var(--line); background: var(--card); }
header.top h1 { margin: 0 0 6px; font-size: 1.45rem; line-height: 1.25; }
header.top .meta { margin: 0 0 10px; color: var(--muted); font-size: .9rem; }
nav a { margin-right: 14px; }
main { max-width: 1080px; margin: 0 auto; padding: 8px 16px 48px; }
section { margin-top: 28px; }
h2 { font-size: 1.2rem; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 1.02rem; margin: 18px 0 8px; }
a { color: var(--accent); }
code { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: .85em; word-break: break-all; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: .92rem; }
th, td { border: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: var(--bg); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-wrap { overflow-x: auto; }
.banner { border-left: 4px solid var(--major); background: var(--major-bg); padding: 10px 12px; border-radius: 4px; }
.readiness { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.ready-card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
.ready-card h3 { margin: 0 0 4px; }
.ready-card .status { font-weight: 700; font-size: 1.05rem; margin: 0 0 6px; }
.st-ready { color: var(--ok); } .st-not_ready { color: var(--bad); } .st-unknown { color: var(--unk); }
.ready-card ul { margin: 0; padding-left: 18px; }
.finding { background: var(--card); border: 1px solid var(--line); border-left-width: 5px; border-radius: 8px;
           padding: 12px 14px; margin: 12px 0; }
.finding:target, .block:target { outline: 2px solid var(--accent); outline-offset: 2px; }
.finding.sev-critical { border-left-color: var(--crit); }
.finding.sev-major { border-left-color: var(--major); }
.finding.sev-minor { border-left-color: var(--minor); }
.finding h3 { margin: 6px 0 8px; }
.badge { display: inline-block; font-size: .78rem; font-weight: 600; padding: 1px 8px; border-radius: 10px;
         margin-right: 6px; border: 1px solid var(--line); }
.badge.sev-critical { background: var(--crit-bg); color: var(--crit); border-color: transparent; }
.badge.sev-major { background: var(--major-bg); color: var(--major); border-color: transparent; }
.badge.sev-minor { background: var(--minor-bg); color: var(--minor); border-color: transparent; }
dl.props { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0; }
dl.props dt { color: var(--muted); }
dl.props dd { margin: 0; }
dl.props ul { margin: 0; padding-left: 18px; }
.quote { font-style: normal; }
.doc { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 6px 0; }
.block { display: grid; grid-template-columns: 7.5rem 1fr; gap: 10px; padding: 3px 14px; }
.block .loc { color: var(--muted); font-size: .78rem; padding-top: 3px; text-align: right; }
.block .loc a { color: inherit; text-decoration: none; }
.block .text { white-space: pre-wrap; overflow-wrap: anywhere; }
.block.heading .text { font-weight: 700; font-size: 1.08rem; padding-top: 8px; }
.block.lvl-1 .text { font-size: 1.3rem; } .block.lvl-2 .text { font-size: 1.18rem; }
.block.table_header .text, .block.table_row .text, .block.code .text {
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: .86rem; }
.block.excluded .text { color: var(--muted); }
.tag { display: inline-block; font-size: .72rem; padding: 0 6px; margin-right: 4px; border-radius: 8px;
       border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
mark { background: var(--mark); color: var(--mark-fg); border-radius: 2px; padding: 0 1px; }
mark a { color: inherit; text-decoration: none; }
mark.sev-critical { box-shadow: inset 0 -2px 0 var(--crit); }
mark.sev-major { box-shadow: inset 0 -2px 0 var(--major); }
sup.ref { font-size: .7rem; margin-left: 1px; }
.muted { color: var(--muted); }
@media (max-width: 640px) {
  .block { grid-template-columns: 1fr; gap: 0; }
  .block .loc { text-align: left; }
  dl.props { grid-template-columns: 1fr; }
}
@media print { nav { display: none; } .finding, .block { break-inside: avoid; } }
"""


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


class _Html:
    def __init__(self, report: Mapping[str, Any]):
        self.report = report
        self.run: Mapping[str, Any] = report.get("run") or {}
        self.document: Mapping[str, Any] = report.get("document") or {}
        self.summary: Mapping[str, Any] = report.get("summary") or {}
        self.blocks = rc.block_index(report)
        self.findings = rc.finding_index(report)
        self.reqs = rc.requirement_index(report)
        self.complete = rc.run_complete(report)

    # ---- ссылки
    def flink(self, fid: str) -> str:
        if fid in self.findings:
            return f'<a href="#{_e(rc.finding_anchor(fid))}">{_e(fid)}</a>'
        return f"{_e(fid)} <span class=\"muted\">(нет в списке замечаний)</span>"

    def flinks(self, ids: Iterable[str]) -> str:
        return ", ".join(self.flink(fid) for fid in rc.unique(ids))

    def blink(self, ref: Any) -> str:
        """Место в документе со ссылкой на блок."""
        block_id = ref.get("block_id") if isinstance(ref, Mapping) else ref
        text = _e(rc.describe_location(self.report, ref, index=self.blocks))
        if block_id in self.blocks:
            return f'<a href="#{_e(rc.block_anchor(block_id))}">{text}</a>'
        return text

    def req_label(self, rid: str) -> str:
        source_id = (self.reqs.get(rid) or {}).get("source_id")
        return f"{rid} ({source_id})" if source_id else rid

    def finding_places(self, f: Mapping[str, Any]) -> str:
        evidence = rc.finding_evidence(f)
        if evidence:
            return "; ".join(rc.unique(self.blink(ev) for ev in evidence))
        hinted = rc.unique(self.blink(h["block_id"]) for h in f.get("hints") or [] if h.get("block_id"))
        if hinted:
            return "по подсказке модели, цитата не сверена: " + "; ".join(hinted)
        return "место в документе не установлено"

    def incomplete(self) -> str:
        note = rc.incomplete_note(self.report)
        return _e(note[:1].upper() + note[1:] + ".")

    # ---- разделы
    def header(self) -> str:
        title = self.document.get("title") or self.run.get("source_name") or "документ без названия"
        meta = [self.run.get("source_name") or self.document.get("source_name") or "файл без имени",
                f"прогон {self.run.get('run_id') or 'без ID'}",
                rc.format_datetime(self.run.get("finished_at")),
                f"модель: {self.run.get('model') or 'модель не вызывалась'}"]
        nav = "".join(f'<a href="#{a}">{t}</a>' for a, t in (
            ("verdict", "Итог"), ("summary", "Сводка"), ("passport", "Паспорт"),
            ("findings", "Замечания"), ("document", "Документ")))
        return (f'<header class="top"><h1>Ревью требований: {_e(title)}</h1>'
                f'<p class="meta">{" · ".join(_e(m) for m in meta)}</p><nav>{nav}</nav></header>')

    def verdict(self) -> str:
        verdict = self.report.get("verdict") or {}
        out = ['<section id="verdict"><h2>Итог</h2>']
        if not self.complete:
            out.append(f'<p class="banner"><strong>Проверка неполная.</strong> {self.incomplete()} '
                       "Выводы относятся только к проверенной части документа.</p>")
        out.append('<div class="readiness">')
        for key, name in (("development", "Разработка"), ("testing", "Тестирование")):
            r = verdict.get(key) or {}
            status = r.get("status", "unknown")
            reasons = "".join(f"<li>{_e(x)}</li>" for x in r.get("reasons") or []) or "<li>причины не указаны</li>"
            ids = r.get("finding_ids") or []
            refs = f"<p>Замечания: {self.flinks(ids)}</p>" if ids else ""
            out.append(f'<div class="ready-card"><h3>{name}</h3>'
                       f'<p class="status st-{_e(status)}">{_e(rc.label(rc.READINESS_LABELS, status))}</p>'
                       f"<ul>{reasons}</ul>{refs}</div>")
        out.append("</div>")
        if verdict.get("basis"):
            out.append(f"<p>Основание вердикта: {_e(verdict['basis'])}</p>")

        out.append("<h3>Критичные замечания</h3>")
        critical = [self.findings[fid] for fid in rc.critical_ids(self.report) if fid in self.findings]
        if critical:
            out.append("<ul>" + "".join(
                f"<li>{self.flink(f['id'])} · {_e(rc.kind_label(f.get('kind')))}: {_e(f.get('title'))} — "
                f"{self.finding_places(f)}"
                + ("" if f.get("status") == "confirmed"
                   else f", {_e(rc.label(rc.FINDING_STATUS_LABELS, f.get('status')))}") + "</li>"
                for f in critical) + "</ul>")
        elif self.complete:
            out.append("<p>Критичных замечаний нет.</p>")
        else:
            out.append("<p>Критичных замечаний не найдено, но проверка неполная: "
                       "отсутствие критичных дефектов не доказано.</p>")

        out.append("<h3>Что исправить в первую очередь</h3>")
        actions = sorted(verdict.get("first_actions") or [], key=lambda a: a.get("order", 0))
        if actions:
            out.append("<ol>" + "".join(
                f"<li>{_e(a.get('action'))}"
                + (f" — {self.flinks(a['finding_ids'])}" if a.get("finding_ids") else "") + "</li>"
                for a in actions) + "</ol>")
        else:
            out.append("<p>Первоочередные исправления не сформированы"
                       + ("." if self.complete else ": проверка неполная.") + "</p>")
        return "".join(out) + "</section>"

    def summary_table(self) -> str:
        def v(*path: str) -> str:
            value: Any = self.summary
            for key in path:
                if not isinstance(value, Mapping) or key not in value:
                    return "не указано"
                value = value[key]
            return _e(value)

        rows = [
            ("Требований выделено", v("requirements")), ("Требований проверено", v("reviewed_requirements")),
            ("Замечаний всего", v("findings")), ("— критичных", v("by_severity", "critical")),
            ("— существенных", v("by_severity", "major")), ("— незначительных", v("by_severity", "minor")),
            ("— подтверждённых", v("by_status", "confirmed")),
            ("— требующих проверки", v("by_status", "needs_review")),
            ("Проверок по критериям: соответствует", v("checks", "pass")),
            ("Проверок по критериям: нарушение", v("checks", "issue")),
            ("Проверок по критериям: не определено", v("checks", "unknown")),
            ("Проверок по критериям: неприменимо", v("checks", "na")),
        ]
        body = "".join(f'<tr><td>{_e(k)}</td><td class="num">{val}</td></tr>' for k, val in rows)
        return (f'<section id="summary"><h2>Сводка</h2><div class="table-wrap"><table>'
                f"<tr><th>Показатель</th><th>Значение</th></tr>{body}</table></div></section>")

    def passport(self) -> str:
        run, doc = self.run, self.document
        calls = run.get("calls") or {}
        tokens = run.get("tokens") or {}
        budget = run.get("budget") or {}
        status = rc.label(rc.RUN_STATUS_LABELS, run.get("status"))
        if run.get("status_reasons"):
            status += ": " + "; ".join(run["status_reasons"])
        max_tokens = budget.get("max_tokens")
        commit = f"коммит {run['agent_commit']}" if run.get("agent_commit") else "коммит не определён"
        rows = [
            ("Документ", doc.get("title")),
            ("Исходный файл", run.get("source_name") or doc.get("source_name")),
            ("SHA-256 файла", run.get("source_sha256") or doc.get("id")),
            ("ID прогона", run.get("run_id")),
            ("Начало", rc.format_datetime(run.get("started_at"))),
            ("Окончание", rc.format_datetime(run.get("finished_at"))),
            ("Длительность", rc.format_seconds(run.get("duration_s"))),
            ("Провайдер", rc.label(rc.PROVIDER_LABELS, run.get("provider"))),
            ("Модель (фактическая)", run.get("model") or "модель не вызывалась"),
            ("Версия агента", f"{run.get('agent_version') or 'не указана'}, {commit}"),
            ("Режим", rc.label(rc.RUN_MODE_LABELS, run.get("mode"))),
            ("Статус прогона", status),
            ("Вызовы модели", f"физических {calls.get('physical', 0)}, из кэша {calls.get('cache_hits', 0)}, "
                              f"повторов {calls.get('retries', 0)}, неудачных {calls.get('failed', 0)}"),
            ("Токены", f"вход {tokens.get('input', 0)}, выход {tokens.get('output', 0)}"),
            ("Бюджет", f"до {budget.get('max_calls', 'не указано')} вызовов, "
                       f"{budget.get('max_seconds', 'не указано')} с, "
                       f"токены: {max_tokens if max_tokens is not None else 'без лимита'}; "
                       f"исчерпан: {rc.yes_no(budget.get('exhausted'))}"),
        ]
        body = "".join(f"<tr><th>{_e(k)}</th><td>{_e(val if val is not None else 'не указано')}</td></tr>"
                       for k, val in rows)
        out = [f'<section id="passport"><h2>Паспорт прогона</h2><div class="table-wrap"><table>{body}</table></div>']

        stages = run.get("stages") or []
        if stages:
            out.append("<h3>Этапы</h3><div class=\"table-wrap\"><table><tr><th>Этап</th><th>Статус</th>"
                       "<th>Вызовы</th><th>Из кэша</th><th>Модель</th><th>Причина</th></tr>")
            out += [f"<tr><td>{_e(s.get('name'))}</td><td>{_e(rc.label(rc.STAGE_STATUS_LABELS, s.get('status')))}</td>"
                    f"<td class=\"num\">{_e(s.get('calls', 0))}</td><td class=\"num\">{_e(s.get('cache_hits', 0))}</td>"
                    f"<td>{_e(s.get('model') or '—')}</td><td>{_e(s.get('reason') or '—')}</td></tr>" for s in stages]
            out.append("</table></div>")
        incomplete = run.get("incomplete_stages") or []
        out.append(f"<p>Незавершённые этапы: {_e(', '.join(incomplete) if incomplete else 'нет')}.</p>")
        modules = run.get("modules") or {}
        if modules:
            out.append("<p>Реализации модулей: " + "; ".join(
                f"{_e(k)} — <code>{_e(val)}</code>" for k, val in sorted(modules.items())) + ".</p>")
        audit = run.get("evidence_audit") or {}
        if audit:
            out.append(f"<p>Сверка цитат: проверено {_e(audit.get('checked'))}, подтверждено "
                       f"{_e(audit.get('confirmed'))}, неоднозначно {_e(audit.get('ambiguous'))}, отклонено "
                       f"{_e(audit.get('rejected'))}. {_e(audit.get('note') or '')}</p>")
        return "".join(out) + "</section>"

    def finding_card(self, f: Mapping[str, Any]) -> str:
        sev = f.get("severity") or "minor"
        props: list[tuple[str, str]] = [
            ("Критерий", _e(rc.criterion_label(f.get("criterion", "")))),
            ("Тип", _e(f"{rc.kind_label(f.get('kind'))}; область: {rc.label(rc.SCOPE_LABELS, f.get('scope'))}")),
        ]
        if f.get("req_ids"):
            props.append(("Требования", _e(", ".join(self.req_label(r) for r in f["req_ids"]))))
        evidence = list(f.get("evidence") or [])
        if evidence:
            items = "".join(f'<li><span class="quote">«{_e(ev.get("quote"))}»</span> — {self.blink(ev)}'
                            + self._section_suffix(ev.get("block_id")) + "</li>" for ev in evidence)
            props.append(("Цитаты", f"<ul>{items}</ul>"))
        elif f.get("hints"):
            items = "".join(f'<li>«{_e(h.get("quote"))}» — '
                            f'{self.blink(h["block_id"]) if h.get("block_id") else "блок не указан"}</li>'
                            for h in f["hints"])
            props.append(("Цитаты", f"<span class=\"muted\">не сверены с текстом, подсказки модели:</span>"
                                    f"<ul>{items}</ul>"))
        else:
            props.append(("Цитаты", "нет; место в документе не установлено"))
        props.append(("Последствие", _e(f.get("impact") or "не указано")))
        if f.get("blocked_decision"):
            props.append(("Блокирует решение", _e(f["blocked_decision"])))
        if f.get("blocks"):
            props.append(("Блокирует", _e(", ".join(rc.label(rc.BLOCKS_TARGET_LABELS, b) for b in f["blocks"]))))
        witness = f.get("witness")
        if witness:
            sides = "".join(
                f"<li>Исход {s.upper()}: {_e(witness.get(f'outcome_{s}'))} — "
                f"«{_e((witness.get(f'evidence_{s}') or {}).get('quote'))}», "
                f"{self.blink(witness.get(f'evidence_{s}') or {})}</li>" for s in ("a", "b"))
            props.append(("Сценарий противоречия", f"{_e(witness.get('input'))}<ul>{sides}</ul>"))
        props.append(("Рекомендация", _e(f.get("recommendation") or "не сформулирована")))
        props.append(("Статус", _e(rc.label(rc.FINDING_STATUS_LABELS, f.get("status")))))
        props.append(("Привязка цитаты", _e(rc.label(rc.ANCHOR_STATUS_LABELS, f.get("anchor_status")))))
        meaning = rc.label(rc.MEANING_STATUS_LABELS, f.get("meaning_status"))
        if f.get("meaning_reason"):
            meaning += f" — {f['meaning_reason']}"
        props.append(("Смысл", _e(meaning)))
        dl = "".join(f"<dt>{_e(k)}</dt><dd>{val}</dd>" for k, val in props)
        return (f'<article class="finding sev-{_e(sev)}" id="{_e(rc.finding_anchor(f["id"]))}">'
                f'<span class="badge sev-{_e(sev)}">{_e(rc.severity_label(sev))}</span>'
                f'<span class="badge">{_e(f["id"])}</span>'
                f"<h3>{_e(f.get('title'))}</h3><dl class=\"props\">{dl}</dl></article>")

    def _section_suffix(self, block_id: Optional[str]) -> str:
        section = rc.section_path(self.report, block_id, index=self.blocks)
        return f', раздел «{_e(section)}»' if section else ""

    def findings_section(self) -> str:
        findings = rc.sorted_findings(self.report.get("findings") or [])
        out = ['<section id="findings"><h2>Замечания</h2>']
        if findings:
            out += [self.finding_card(f) for f in findings]
        elif self.summary.get("findings") == 0 and self.complete:
            out.append("<p>Замечаний нет.</p>")
        else:
            out.append(f"<p>Замечаний не найдено, но проверка неполная. {self.incomplete()} "
                       "Отсутствие замечаний не означает, что в документе нет дефектов.</p>")
        return "".join(out) + "</section>"

    # ---- документ с подсветкой опор
    def _spans_by_block(self) -> dict[str, list[tuple[int, int, Mapping[str, Any]]]]:
        spans: dict[str, list[tuple[int, int, Mapping[str, Any]]]] = {}
        for f in rc.sorted_findings(self.findings.values()):
            for ev in rc.finding_evidence(f):
                block = self.blocks.get(ev.get("block_id"))
                if block is None:
                    continue
                start, end = int(ev.get("start", 0)), int(ev.get("end", 0))
                start, end = max(0, start), min(len(block.get("text", "")), end)
                if start < end:
                    spans.setdefault(block["id"], []).append((start, end, f))
        return spans

    @staticmethod
    def _marked_text(text: str, spans: list[tuple[int, int, Mapping[str, Any]]]) -> str:
        """Текст блока, где каждый отрезок опоры — ``<mark>`` со ссылкой на замечание.

        Перекрывающиеся опоры режутся на отрезки; отрезок ведёт на самое серьёзное из покрывающих
        замечаний, а в конце каждой опоры стоит сноска на её замечание.
        """
        if not spans:
            return _e(text)
        cuts = sorted({0, len(text)} | {s for s, _, _ in spans} | {e for _, e, _ in spans})
        out: list[str] = []
        for a, b in zip(cuts, cuts[1:]):
            piece = text[a:b]
            covering = [f for s, e, f in spans if s <= a and e >= b]
            if covering:
                main = covering[0]  # spans уже упорядочены по серьёзности
                ids = ", ".join(rc.unique(str(f["id"]) for f in covering))
                out.append(f'<mark class="sev-{_e(main.get("severity"))}" title="{_e(ids)}">'
                           f'<a href="#{_e(rc.finding_anchor(main["id"]))}">{_e(piece)}</a></mark>')
            else:
                out.append(_e(piece))
            ending = rc.unique(str(f["id"]) for s, e, f in spans if e == b)
            out += [f'<sup class="ref"><a href="#{_e(rc.finding_anchor(fid))}">{_e(fid)}</a></sup>'
                    for fid in ending]
        return "".join(out)

    def document_section(self) -> str:
        spans = self._spans_by_block()
        req_by_block: dict[str, list[str]] = {}
        for r in self.report.get("requirements") or []:
            for block_id in r.get("block_ids") or []:
                req_by_block.setdefault(block_id, []).append(r["id"])
        excluded: dict[str, str] = {}
        for item in self.report.get("excluded") or []:
            for block_id in item.get("block_ids") or []:
                excluded[block_id] = item.get("reason") or "исключено"

        out = ['<section id="document"><h2>Текст документа</h2>',
               '<p class="muted">Подсвечены цитаты, на которые опираются замечания; '
               "щелчок по подсветке ведёт к замечанию.</p><div class=\"doc\">"]
        for block in self.document.get("blocks") or []:
            bid = block.get("id", "")
            kind = block.get("kind", "other")
            classes = ["block", _e(kind)]
            level = (block.get("loc") or {}).get("level")
            if kind == "heading" and level:
                classes.append(f"lvl-{_e(level)}")
            if bid in excluded:
                classes.append("excluded")
            tags = "".join(f'<span class="tag">{_e(rid)}</span>' for rid in req_by_block.get(bid, []))
            if bid in excluded:
                tags += f'<span class="tag" title="{_e(excluded[bid])}">исключено</span>'
            loc = _e(rc.describe_location(self.report, bid, index=self.blocks))
            out.append(f'<div class="{" ".join(classes)}" id="{_e(rc.block_anchor(bid))}">'
                       f'<div class="loc"><a href="#{_e(rc.block_anchor(bid))}">{loc}</a></div>'
                       f'<div class="text">{tags}{self._marked_text(block.get("text", ""), spans.get(bid, []))}'
                       "</div></div>")
        if not self.document.get("blocks"):
            out.append('<p class="muted" style="padding:0 14px">Текст документа в отчёт не передан.</p>')
        return "".join(out) + "</div></section>"

    def render(self) -> str:
        title = self.document.get("title") or self.run.get("source_name") or "документ без названия"
        return (
            "<!doctype html>\n"
            '<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="color-scheme" content="light dark">\n'
            f"<title>Ревью требований: {_e(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
            + self.header() + "\n<main>\n"
            + "\n".join((self.verdict(), self.summary_table(), self.passport(), self.findings_section(),
                         self.document_section()))
            + "\n</main>\n</body>\n</html>\n"
        )


def render_html(report: Mapping[str, Any]) -> str:
    return _Html(report).render()


def write_html(report: Mapping[str, Any], output_path: str | Path) -> Path:
    """Записать самодостаточный HTML-отчёт (UTF-8) и вернуть путь к файлу."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8", newline="\n")
    return path
