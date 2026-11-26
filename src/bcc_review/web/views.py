"""HTML-страницы веб-демо. Серверный рендер, без внешних ресурсов (работает офлайн)."""

from __future__ import annotations

import html
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import report_view as rv
from .answers import ANALYST, match_demo_answer
from .store import parse_ts

try:  # Казахстан с 01.03.2024 живёт в UTC+5; на Windows без tzdata — фиксированный сдвиг
    from zoneinfo import ZoneInfo

    ALMATY = ZoneInfo("Asia/Almaty")
except Exception:  # pragma: no cover
    ALMATY = timezone(timedelta(hours=5), "UTC+5")

STATUS = {
    "started": ("в очереди", "neutral"),
    "running": ("выполняется", "info"),
    "complete": ("готово", "ok"),
    "partial": ("готово частично", "warn"),
    "failed": ("ошибка", "bad"),
}


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_time(ts: str | None) -> str:
    dt = parse_ts(ts)
    if not dt:
        return "—"
    return dt.astimezone(ALMATY).strftime("%d.%m.%Y %H:%M:%S") + " (Алматы)"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    return f"{s // 60} мин {s % 60:02d} с" if s >= 60 else f"{seconds:.1f} с"


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} Б"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    return f"{n / 1024 / 1024:.1f} МБ"


def status_badge(status: str) -> str:
    label, tone = STATUS.get(status, (status, "neutral"))
    return f'<span class="badge {tone}" data-status="{e(status)}">{e(label)} <code>{e(status)}</code></span>'


# --------------------------------------------------------------------------- layout
def layout(title: str, body: str, *, ctx: dict[str, Any], run_status: str | None = None, run_id: str | None = None) -> str:
    engine = ctx["engine"]
    pf = ctx["preflight"]
    if ctx.get("demo"):
        engine_line = "Режим просмотра сохранённых прогонов: новый анализ не запускается"
    elif not engine.available:
        engine_line = f'<span class="bad-text">Общий движок не найден</span> · {e(engine.error or "")}'
    else:
        ver = f" · версия {e(engine.version)}" if engine.version else ""
        prov = f" · провайдер {e(pf.get('provider'))}" if pf.get("provider") else ""
        key = f' · <span class="{"" if pf["key_present"] else "warn-text"}">{e(pf["note"])}</span>'
        engine_line = f"Движок: <code>{e(engine.target)}</code>{ver}{prov}{key}"
    data_attrs = ""
    if run_status:
        data_attrs = f' data-run-status="{e(run_status)}" data-run-id="{e(run_id)}" data-api="{e(ctx["prefix"])}/api/runs/{e(run_id)}"'
    dev_banner = ""
    if engine.name == "dev" and not ctx.get("demo"):
        dev_banner = (
            '<div class="banner dev">Режим разработки: подключён подставной движок <code>bcc_review.web.devengine</code>. '
            "Отчёты помечены mock и не являются результатом общего движка.</div>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body{data_attrs}>
<header class="top"><a class="brand" href="{e(ctx['prefix'] or '/')}">Ревью ТЗ до разработки</a>
<div class="engine">{engine_line}</div></header>
{dev_banner}
<main>{body}</main>
<script src="/static/app.js" defer></script>
</body></html>"""


# --------------------------------------------------------------------------- home
def home(ctx: dict[str, Any], runs: list[dict[str, Any]], upload_key: str, demo_runs: list[dict[str, Any]]) -> str:
    pf = ctx["preflight"]
    engine = ctx["engine"]
    if engine.available:
        offline_note = ""
        if pf["offline"]:
            offline_note = (
                '<p class="notice warn">Ключ LLM не найден: '
                f"{e(', '.join(pf['key_names']))}. Документ будет проверен только по правилам "
                "(режим rules_only), семантические проверки не выполнятся и отчёт будет неполным.</p>"
            )
        upload = f"""
<section class="card upload">
  <h1>Проверить ТЗ</h1>
  <p>PDF, Markdown, DOCX, TXT или HTML до 25 МБ. Каждый файл получает свой run_id.</p>
  {offline_note}
  <form id="upload-form" method="post" action="/api/runs" enctype="multipart/form-data">
    <input type="hidden" name="upload_key" value="{e(upload_key)}">
    <label class="button primary big" id="upload-label">
      <input id="upload-input" type="file" name="file" required
        accept=".pdf,.md,.markdown,.txt,.docx,.html,.htm">
      <span>Загрузить ТЗ</span>
    </label>
    <noscript><button class="button" type="submit">Отправить</button></noscript>
  </form>
</section>"""
    else:
        upload = f"""
<section class="card error">
  <h1>Новый анализ недоступен</h1>
  <p>{e(engine.error)}</p>
  <p>Для разработки интерфейса запустите <code>python -m bcc_review.web --engine dev</code>;
  для показа сохранённого прогона — <code>python -m bcc_review.web --demo КАТАЛОГ</code>.</p>
</section>"""

    rows = []
    for r in runs[:30]:
        rows.append(
            f"<tr><td><a href=\"/runs/{e(r['run_id'])}\"><code>{e(r['run_id'])}</code></a></td>"
            f"<td>{e(r['input']['original_name'])}</td><td>{e(r.get('revision'))}</td>"
            f"<td>{status_badge(r['status'])}</td><td>{e(fmt_time(r.get('created_at')))}</td></tr>"
        )
    table = (
        "<section><h2>Запуски</h2><table class=\"runs\"><thead><tr><th>run_id</th><th>Файл</th><th>Редакция</th>"
        "<th>Статус</th><th>Создан</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
        if rows
        else ""
    )
    demo = ""
    if demo_runs:
        items = "".join(
            f"<li><a href=\"/demo/runs/{e(r['run_id'])}\">{e(r['input']['original_name'])}, редакция {e(r.get('revision'))}</a> — "
            f"сохранён {e(fmt_time(r.get('finished_at')))}, модель {e((r.get('report') or {}).get('model') or '—')}, "
            f"режим {e((r.get('report') or {}).get('mode') or '—')}</li>"
            for r in demo_runs
        )
        demo = f'<section class="card demo"><h2>Сохранённые прогоны (демонстрация, не живой анализ)</h2><ul>{items}</ul></section>'
    return layout("Ревью ТЗ", upload + demo + table, ctx=ctx)


# --------------------------------------------------------------------------- run page parts
STAGE_STATUS_CLS = {"ok": ("✓", "done"), "cached": ("✓", "done"), "partial": ("!", "partial"), "failed": ("✗", "fail"), "skipped": ("–", "cut")}


def _report_stages(stages: list[dict[str, Any]]) -> str:
    items = []
    for st in stages:
        icon, cls = STAGE_STATUS_CLS.get(str(st.get("status")), ("?", "cut"))
        bits = []
        if st.get("calls"):
            bits.append(f"вызовов {st['calls']}")
        if st.get("cache_hits"):
            bits.append(f"из кэша {st['cache_hits']}")
        if st.get("duration_s") is not None:
            bits.append(fmt_duration(st.get("duration_s")))
        if st.get("reason"):
            bits.append(str(st["reason"]))
        det = f' <span class="muted">{e(" · ".join(bits))}</span>' if bits else ""
        items.append(f'<li class="{cls}" title="{e(st.get("status"))}"><span class="ico">{icon}</span> {e(rv.stage_label(st.get("name")))}{det}</li>')
    return '<ol class="stages" id="stages">' + "".join(items) + "</ol>" if items else ""


def _stages(events: list[dict[str, Any]], status: str, current: str | None) -> str:
    seen: dict[str, str] = {}
    order: list[str] = []
    details: dict[str, str] = {}
    for ev in events:
        st = ev.get("stage")
        if not st or st == "engine":
            continue
        if st not in seen:
            order.append(st)
        seen[st] = ev.get("state") or ""
        if ev.get("detail"):
            details[st] = str(ev["detail"])
    items = []
    for st in order:
        state = seen[st]
        if state in ("done", "skip"):
            icon, cls = "✓", "done"
        elif state == "fail":
            icon, cls = "✗", "fail"
        elif status in ("started", "running"):
            icon, cls = "…", "now"
        else:
            icon, cls = "–", "cut"
        det = f' <span class="muted">{e(details[st])}</span>' if st in details else ""
        items.append(f'<li class="{cls}"><span class="ico">{icon}</span> {e(rv.stage_label(st))}{det}</li>')
    if not items:
        if status == "started":
            return '<p class="muted" id="stages-empty">Ожидает очереди.</p>'
        if status == "running":
            return '<p class="muted" id="stages-empty">Движок выполняется и пока не сообщил этапы.</p>'
        return ""
    return '<ol class="stages" id="stages">' + "".join(items) + "</ol>"


def status_section(run: dict[str, Any], events: list[dict[str, Any]], *, eta: dict[str, Any] | None, queue_pos: int, elapsed: float | None, ctx: dict[str, Any], report_stages: list[dict[str, Any]] | None = None) -> str:
    status = run["status"]
    lines = [f'<div class="status-line">{status_badge(status)}']
    if status in ("started", "running"):
        lines.append(f' · прошло <span id="elapsed">{e(fmt_duration(elapsed or 0))}</span>')
        if status == "started" and queue_pos:
            lines.append(f" · перед вами в очереди: {queue_pos}")
        if eta:
            lines.append(
                f' · <span id="eta">по измеренным прогонам этого движка: медиана {e(fmt_duration(eta["median_s"]))} '
                f'({e(eta["samples"])} шт.)</span>'
            )
        lines.append(' · <a href="" id="refresh">обновить</a>')
    else:
        lines.append(f" · длительность {e(fmt_duration(run.get('duration_s')))} (измерено)")
    lines.append("</div>")
    stages_html = _report_stages(report_stages) if report_stages else _stages(events, status, run.get("stage"))
    body = "".join(lines) + stages_html
    if status == "failed":
        err = run.get("error") or {}
        actions = []
        if not ctx.get("demo") and ctx["engine"].available:
            nxt = err.get("next_step")
            if nxt == "offline":
                actions.append(_post_button(f"/runs/{run['run_id']}/retry", "Проверить только по правилам (без LLM)", {"offline": "1"}, primary=True))
                actions.append(_post_button(f"/runs/{run['run_id']}/retry", "Повторить с LLM", {"offline": "0"}))
            elif err.get("kind") == "interrupted" or nxt == "retry":
                actions.append(_post_button(f"/runs/{run['run_id']}/retry", "Повторить запуск", {"offline": "0"}, primary=True))
                actions.append(_post_button(f"/runs/{run['run_id']}/retry", "Проверить только по правилам", {"offline": "1"}))
        hint = {
            "missing_key": "Ключ LLM не найден. Добавьте его в .env и перезапустите сервер или выполните проверку только по правилам.",
            "network": "Провайдер LLM недоступен. Повторите позже или выполните проверку только по правилам.",
            "interrupted": "Запуск прервали. Отчёт не создан. Повторите запуск.",
            "no_report": "Движок завершился, но не записал report.json.",
        }.get(err.get("kind"), "Движок завершился ошибкой. Отчёт не создан.")
        body += (
            f'<div class="notice bad" id="error"><b>Причина:</b> {e(err.get("message"))}'
            f'{" <code>" + e(err.get("type")) + "</code>" if err.get("type") else ""}'
            f'<br><b>Что можно сделать:</b> {e(hint)}<div class="actions">{"".join(actions)}</div></div>'
        )
    for w in run.get("warnings") or []:
        body += f'<p class="notice warn">{e(w)}</p>'
    return f'<section class="card" id="status"><h2>Статус</h2>{body}</section>'


def _post_button(action: str, label: str, fields: dict[str, str], *, primary: bool = False) -> str:
    hidden = "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in fields.items())
    cls = "button primary" if primary else "button"
    return f'<form method="post" action="{e(action)}" class="inline once">{hidden}<button class="{cls}" type="submit">{e(label)}</button></form>'


def verdict_section(view: rv.ReportView, run: dict[str, Any], files: dict[str, str]) -> str:
    def cell(title: str, r: dict[str, Any]) -> str:
        ids = " ".join(f'<a href="#{e(i)}">{e(i)}</a>' for i in r.get("finding_ids") or [])
        return (f'<div class="verdict {e(r["tone"])}" data-state="{e(r["state"])}"><div class="vt">{e(title)}</div><div class="vv">{e(r["label"])}</div>'
                f'<div class="vr">{e(r["reason"])}{(" · " + ids) if ids else ""}</div></div>')

    actions = "".join(
        f"<li>{_link_ids(a.get('text', ''))}"
        + ("".join(f' <a href="#{e(i)}">{e(i)}</a>' for i in a.get("finding_ids") or [] if i not in a.get("text", "")))
        + "</li>"
        for a in view.first_actions
    )
    run_meta = view.run
    counts = view.counts
    incompl = ""
    if view.incomplete:
        reasons = []
        if view.mode != "rules_plus_llm":
            reasons.append(f"режим «{view.mode_label}»")
        if run_meta.get("status") != "complete":
            reasons.append(f"run.status = {run_meta.get('status')}")
        if view.doc_partial:
            reasons.append("документ разобран не полностью")
        reasons += [str(x) for x in run_meta.get("status_reasons") or []]
        if run_meta.get("incomplete_stages"):
            reasons.append("незавершённые этапы: " + ", ".join(rv.stage_label(x) for x in run_meta["incomplete_stages"]))
        incompl = f'<p class="notice warn" id="incomplete"><b>Отчёт неполный:</b> {e("; ".join(reasons))}.</p>'
    warn = "".join(f"<li>{e(w)}</li>" for w in dict.fromkeys(view.warnings + view.doc_warnings))
    warn_html = f'<details class="warnings" {"open" if view.incomplete else ""}><summary>Предупреждения движка ({len(view.warnings)})</summary><ul>{warn}</ul></details>' if warn else ""
    quick = " · ".join(f'<a href="{e(href)}" target="_blank" rel="noopener">{e(label)}</a>' for label, href in files.items())
    return f"""<section class="card" id="verdict"><h2>Вердикт</h2>
<div class="verdicts">{cell("Разработка", view.development)}{cell("Тестирование", view.testing)}</div>
{incompl}
<p class="counts" id="counts">Замечаний: <b>{counts['total']}</b> (критичных {counts['critical']}, существенных {counts['major']}, незначительных {counts['minor']}; требуют проверки {counts['needs_review']}) · требований: {counts['requirements']} · открытых вопросов: {counts['questions_open']}</p>
{f'<h3>Сначала исправить</h3><ol class="first">{actions}</ol>' if actions else '<p class="muted">Движок не указал первые действия.</p>'}
<p class="provenance">Режим: <b>{e(view.mode_label)}</b> · модель: <code>{e(run_meta.get('model') or '—')}</code> · провайдер: {e(run_meta.get('provider') or '—')} · физических вызовов: {e(view.calls.get('physical', '—'))}{(' (из кэша ' + e(view.calls.get('cache_hits')) + ')') if view.calls.get('cache_hits') else ''} · версия агента: {e(run_meta.get('agent_version') or '—')}{(' · коммит ' + e(run_meta.get('agent_commit'))) if run_meta.get('agent_commit') else ''}</p>
{f'<p class="muted small">Основание вердикта: {e(view.basis)}</p>' if view.basis else ''}
{f'<p class="open-reports">Открыть отчёт: {quick}</p>' if quick else ''}
{warn_html}
</section>"""


def _link_ids(text: str) -> str:
    return re.sub(r"\b(F-\d+)\b", lambda m: f'<a href="#{m.group(1)}">{m.group(1)}</a>', e(text))


IMPORT_STATUS = {
    "accepted": ("принят → новая редакция", "ok"),
    "duplicate": ("повтор → та же редакция", "info"),
    "rejected": ("отклонён", "bad"),
    "checking": ("проверяется", "neutral"),
}
IMPORT_REASON = {
    "stale_answers": "ответы к другой версии документа",
    "no_sha": "в файле нет source_sha256",
    "sha_conflict": "в файле несколько разных source_sha256",
    "no_answers": "нет заполненных ответов",
    "stale_parent": "редакция устарела",
}


def short(sha: str | None) -> str:
    return (sha or "—")[:12] + ("…" if sha else "")


def manual_import_panel(rec: dict[str, Any], view: rv.ReportView) -> str:
    """Файл без версии: ответы не применены; аналитик сверяет вопрос и переносит ответ сам."""
    current = {q["id"]: q["text"] for q in view.questions}
    rows = []
    for a in rec.get("answers") or []:
        qid = a["qid"]
        here = current.get(qid)
        file_q = a.get("question") or "— (в файле текста вопроса нет)"
        if here is not None:
            btn = (
                f'<button type="button" class="button small demo-fill" data-target="a_{e(qid)}" data-text="{e(a["text"])}" '
                f'data-prov="{e("перенесено аналитиком вручную из файла без версии " + rec["original_name"] + " (" + rec["import_id"] + ")")}">'
                f"Перенести в ответ на {e(qid)}</button>"
            )
            here_html = f"<br><b>Здесь {e(qid)}:</b> {e(here)}"
        else:
            btn, here_html = '<span class="muted small">вопроса с таким номером в этой версии нет</span>', ""
        rows.append(
            f'<li><b>{e(qid)}</b> · <b>в файле:</b> {e(file_q)}{here_html}<br><b>Ответ из файла:</b> '
            f'<span class="file-answer">{e(a["text"])}</span><br>{btn}</li>'
        )
    return (
        f'<div class="notice warn" id="manual-import"><b>Файл {e(rec["original_name"])} без версии документа — не применён.</b> '
        "Сверьте вопрос в файле с вопросом этой версии и перенесите ответ вручную, если смысл совпадает. "
        f'Перенесённый ответ будет подписан как ручной перенос из {e(rec["import_id"])}.'
        f'<ul class="manual-list">{"".join(rows) or "<li>Ответов в файле нет.</li>"}</ul></div>'
    )


def imports_section(run: dict[str, Any], imports: list[dict[str, Any]], prefix: str) -> str:
    if not imports:
        return ""
    rows = []
    for r in imports:
        label, tone = IMPORT_STATUS.get(r.get("status"), (r.get("status"), "neutral"))
        why = IMPORT_REASON.get(r.get("reason"), r.get("reason") or "")
        child = f' · <a href="{prefix}/runs/{e(r["child_run_id"])}">{e(r["child_run_id"])}</a>' if r.get("child_run_id") else ""
        rows.append(
            f'<li id="{e(r["import_id"])}"><span class="badge {tone}">{e(label)}</span> {e(why)}{child} · '
            f'<a href="{prefix}/runs/{e(run["run_id"])}/imports/{e(r["import_id"])}.md" download>{e(r.get("original_name"))}</a> '
            f'<span class="muted small">{e(r.get("format_label") or r.get("format"))} · разбор: {e(r.get("parser"))} · '
            f'заявлено {e(short(r.get("declared_sha256")))} · сверено с {e(short(r.get("target_sha256")))} · '
            f'sha256 файла {e(short(r.get("file_sha256")))} · {e(fmt_time(r.get("created_at")))}</span></li>'
        )
    return f'<details class="card" id="imports"><summary>Импорты файлов ответов ({len(imports)}): оригиналы и итог проверки версии</summary><ul class="files">{"".join(rows)}</ul></details>'


_LETTERED = re.compile(r"^[A-FА-Е][.)]\s")


def _option_label(oid: str, text: str) -> str:
    """Вариант №08 уже начинается с буквы («A. …») — без второй нумерации."""
    return text if _LETTERED.match(text) else f"{oid}. {text}"


def _edit_controls(view: rv.ReportView, q: dict[str, Any], qid: str) -> str:
    """Правка текста, которую движок действительно применит.

    Вопрос №08 несёт ``target``: движок (№08 propose_patch) заменяет предложение с этой цитатой
    на «Формулировку». Пара «было → стало» №08 не читает, поэтому для таких вопросов форма
    предлагает именно формулировку и показывает, что будет заменено. Без ``target``
    (резервный движок, dev-движок) остаётся пара «было → стало».
    """
    target = q.get("target") if isinstance(q.get("target"), dict) else None
    if target and target.get("block_id"):
        blocks = {str(b.get("id")): b for b in (view.raw.get("document") or {}).get("blocks") or []}
        b = blocks.get(str(target["block_id"])) or {}
        text, start, end = str(b.get("text") or ""), target.get("start"), target.get("end")
        quote = str(target.get("quote") or (text[start:end] if isinstance(start, int) and isinstance(end, int) else ""))
        if isinstance(start, int) and isinstance(end, int) and text[start:end] == quote:
            shown = f'{e(text[:start])}<mark>{e(quote)}</mark>{e(text[end:])}'
        else:
            shown = f"<mark>{e(quote)}</mark>"
        where = rv.loc_text(b.get("loc")) or str(target["block_id"])
        return (
            f'<details class="edit" id="ed_a_{e(qid)}"><summary>Новая формулировка пункта (новая редакция)</summary>'
            f'<p class="small">Движок заменит предложение с выделенным фрагментом ({e(where)}):</p>'
            f'<blockquote class="target small">{shown}</blockquote>'
            f'<label class="small">Новая формулировка <input type="text" name="w_{e(qid)}" id="w_a_{e(qid)}"></label></details>'
        )
    return (
        f'<details class="edit" id="ed_a_{e(qid)}"><summary>Правка текста ТЗ (новая редакция)</summary>'
        f'<label class="small">Заменить фрагмент (точно как в документе) <input type="text" name="eo_{e(qid)}" id="eo_a_{e(qid)}"></label>'
        f'<label class="small">на <input type="text" name="en_{e(qid)}" id="en_a_{e(qid)}"></label></details>'
    )


def changes_section(view: rv.ReportView) -> str:
    """Изменённые пункты: правки, которые движок внёс в эту редакцию (decisions[].edits), и пункт целиком."""
    blocks = (view.raw.get("document") or {}).get("blocks") or []
    rows = []
    for d in view.decisions:
        for ed in d.get("edits") or []:
            new = str(ed.get("new") or "")
            block = next((b for b in blocks if new and new in str(b.get("text") or "")), None)
            if block:
                t = str(block["text"])
                i = t.find(new)
                now = f'{e(t[:i])}<mark>{e(new)}</mark>{e(t[i + len(new):])}'
                where = rv.loc_text(block.get("loc")) + f" · {block.get('id')}"
            else:
                now, where = f"<mark>{e(new)}</mark>", "пункт в документе редакции не найден"
            rows.append(
                f'<li><b>{e(d.get("question_id"))}</b> · {e(where)}<br><span class="was">было: «{e(ed.get("old"))}»</span><br>'
                f'<span class="now">стало: «{e(new)}»</span><blockquote class="small">{now}</blockquote></li>'
            )
    if not rows:
        return ""
    return f'<section class="card" id="changes"><h2>Изменённые пункты ({len(rows)})</h2><ul class="changes">{"".join(rows)}</ul></section>'


def action_section(view: rv.ReportView, run: dict[str, Any], *, ctx: dict[str, Any], latest: dict[str, Any] | None, demo_answers: list[dict[str, Any]], manual_import: dict[str, Any] | None = None) -> str:
    if ctx.get("demo"):
        return ""
    rid = run["run_id"]
    if latest and latest["run_id"] != rid:
        return (
            f'<section class="card" id="action"><h2>Действие аналитика</h2><p class="notice warn" id="stale">'
            f"Это не актуальная редакция: после неё запущена редакция {e(latest['revision'])} "
            f"(<a href=\"/runs/{e(latest['run_id'])}\">{e(latest['run_id'])}</a>, {e(STATUS.get(latest['status'], (latest['status'],))[0])}). "
            "Решения отправляйте к актуальной редакции.</p></section>"
        )
    if not ctx["engine"].available:
        return ""
    version = str((view.raw.get("document") or {}).get("id") or view.run.get("source_sha256") or "")
    qs = view.questions
    items = []
    for q in qs:
        qid = str(q["id"])
        refs = " ".join(f'<a href="#{e(fid)}">{e(fid)}</a>' for fid in (q.get("finding_ids") or []))
        opts_html = ""
        for opt in q.get("options_norm") or []:
            oid, text = opt["id"], opt["text"]
            opts_html += (
                f'<label class="opt"><input type="radio" name="d_{e(qid)}" value="{e(oid)}" data-target="a_{e(qid)}" '
                f'data-text="{e(text)}" data-prov="вариант {e(oid)} из вопроса {e(qid)} (предложение движка, модель {e(view.run.get("model") or "—")})">'
                f" {e(_option_label(oid, text))}</label>"
            )
        demo = match_demo_answer(demo_answers, q)
        demo_html = ""
        if demo:
            d_old, d_new = (demo.get("edits") or [("", "")])[0]
            demo_html = (
                f'<button type="button" class="button small demo-fill" data-target="a_{e(qid)}" data-text="{e(demo["text"])}" '
                f'data-edit-old="{e(d_old)}" data-edit-new="{e(d_new)}" data-wording="{e(demo.get("wording") or "")}" '
                f'data-prov="{e(demo["provenance"])}">Подставить демонстрационный ответ</button>'
                f'<span class="muted small">Источник: {e(demo["provenance"])}</span>'
            )
        dec = q.get("decision") or {}
        prev_html = f'<p class="carried">Ответ, учтённый в этой версии: {e(dec.get("answer"))}</p>' if dec.get("answer") else ""
        items.append(
            f"""<div class="question" id="q-{e(qid)}">
<p><b>{e(qid)}.</b> {e(q['text'])} {('<span class="muted">→ ' + refs + '</span>') if refs else ''}</p>
{prev_html}{f'<div class="options">{opts_html}</div>' if opts_html else ''}
<textarea name="a_{e(qid)}" id="a_{e(qid)}" rows="2" placeholder="Ответ аналитика"></textarea>
{_edit_controls(view, q, qid)}
<input type="hidden" name="p_{e(qid)}" id="p_a_{e(qid)}" value="{e(ANALYST)}">
<input type="hidden" name="qt_{e(qid)}" value="{e(q['text'])}">
<div class="prov" id="prov_a_{e(qid)}"></div>{demo_html}
</div>"""
        )
    qhtml = "".join(items) if items else '<p class="muted">Открытых уточняющих вопросов нет. Можно загрузить исправленную редакцию документа.</p>'
    manual = manual_import_panel(manual_import, view) if manual_import else ""
    return f"""<section class="card" id="action"><h2>Действие аналитика</h2>
<p class="version" id="version">Вопросы и ответы относятся к версии документа <code title="{e(version)}">{e(short(version))}</code>.
Файл ответов другой версии не применяется: номер вопроса однозначен только внутри своей версии.</p>
{manual}
<form method="post" action="/runs/{e(rid)}/revisions" enctype="multipart/form-data" id="confirm-form" class="once">
<input type="hidden" name="questions_sha256" value="{e(version)}">
{qhtml}
<div class="files-row">
  <a class="button small" href="/runs/{e(rid)}/questions.md">Скачать questions.md</a>
  <label class="small">или загрузить заполненный answers.md (веб-формат, экспорт HTML №13, файл №08) <input type="file" name="answers_file" accept=".md,.txt"></label>
  <label class="small">или исправленную редакцию документа <input type="file" name="document" accept=".pdf,.md,.markdown,.txt,.docx,.html,.htm"></label>
</div>
<p class="muted small">Ответ без правки текста фиксирует решение, но документ остаётся прежним: замечание закроется только после правки или загрузки исправленной редакции.</p>
<button class="button primary" type="submit" id="confirm">Подтвердить новую редакцию и перепроверить</button>
<p class="muted small">Повторное нажатие не запускает второй анализ: вы попадёте в уже созданный запуск.</p>
</form></section>"""


def import_rejected_page(ctx: dict[str, Any], parent: dict[str, Any], info: dict[str, Any], message: str) -> str:
    """Отклонённый импорт: причина, обе версии, тот же номер вопроса с разным смыслом, куда идти."""
    clash = "".join(
        f'<li><b>{e(c["qid"])}</b> в файле: «{e(c["in_file"] or "текста вопроса в файле нет")}»<br>'
        f'<b>{e(c["qid"])}</b> здесь: «{e(c["here"])}»</li>'
        for c in info.get("question_clash") or []
    )
    runs = "".join(
        f'<li><a class="button small" href="/runs/{e(r["run_id"])}#action">Открыть вопросы той версии: {e(r["original_name"])}, '
        f'редакция {e(r["revision"])} ({e(r["run_id"])})</a></li>'
        for r in info.get("matching_runs") or []
    )
    if not runs and info.get("reason") == "stale_answers":
        runs = "<li class=muted>Запусков с версией из файла в этом хранилище нет.</li>"
    manual = ""
    if info.get("reason") == "no_sha":
        manual = f'<a class="button primary" href="{e(info["manual_url"])}">Сверить вопросы и перенести ответы вручную</a> '
    body = f"""<section class="card" id="import-rejected"><h1>Ответы не применены</h1>
<p class="notice bad">{e(message)}</p>
<dl class="kv">
<dt>Файл</dt><dd>{e(info.get("format_label") or info.get("format"))} · разбор: {e(info.get("parser"))} · <a href="/runs/{e(parent["run_id"])}/imports/{e(info["import_id"])}.md" download>оригинал ({e(info["import_id"])})</a></dd>
<dt>Заявленная версия</dt><dd><code>{e(info.get("declared_sha256") or ", ".join(info.get("sha_values") or []) or "не указана")}</code></dd>
<dt>Документ новой редакции</dt><dd>{e(parent["input"]["original_name"])}, редакция {e(parent.get("revision"))} · <code>{e(info.get("target_sha256"))}</code></dd>
<dt>Новых запусков</dt><dd id="no-runs">0 — анализ не запускался</dd>
</dl>
{f'<h2>Один номер — разные вопросы</h2><ul class="clash">{clash}</ul>' if clash else ''}
<h2>Что можно сделать</h2>
<ul class="next">{runs}
<li><a class="button small" href="{e(info["questions_url"])}">Скачать questions.md этой версии</a></li>
<li>{manual}<a class="button small" href="/runs/{e(parent["run_id"])}#action">Вернуться к редакции {e(parent.get("revision"))}</a></li></ul>
</section>"""
    return layout("Ответы не применены", body, ctx=ctx)


def findings_section(view: rv.ReportView) -> str:
    if not view.findings:
        return '<section class="card" id="findings"><h2>Замечания</h2><p class="muted">Движок не выдал замечаний.</p></section>'
    out = []
    for fv in view.findings:
        frags = []
        for fr in fv.fragments:
            ok = "" if fr.verified else ' <span class="badge warn">опора не подтверждена</span>'
            label = f'<b class="flabel">{e(fr.label)}</b> ' if fr.label else ""
            frags.append(
                f'<figure class="fragment">{label}<figcaption>{e(fr.where or fr.block_id)}{(" · " + e(fr.section)) if fr.section else ""} · <code>{e(fr.block_id)}</code>{ok}</figcaption>'
                f"<blockquote>{e(fr.before)}<mark>{e(fr.quote)}</mark>{e(fr.after)}</blockquote></figure>"
            )
        wit = ""
        if fv.witness:
            w = fv.witness
            wit = (
                f'<div class="witness"><p><b>Сценарий:</b> {e(w.get("input"))}</p>'
                f'<p><b>А:</b> {e(w.get("outcome_a"))}<br><b>Б:</b> {e(w.get("outcome_b"))}</p></div>'
            )
        reqs = f' · требования: {e(", ".join(fv.req_ids))}' if fv.req_ids else ""
        open_attr = " open" if fv.severity == "critical" else ""
        out.append(
            f"""<details class="finding sev-{e(fv.severity)}" id="{e(fv.id)}"{open_attr}>
<summary><span class="sev">{e(fv.severity_label)}</span> <b>{e(fv.id)}</b> {e(fv.title)} <span class="muted">· {e(fv.criterion_label)} · {e(fv.status_label)}{reqs}</span></summary>
{f'<p>{e(fv.impact)}</p>' if fv.impact else ''}{wit}
{f'<p class="small"><b>Блокирует:</b> {e(", ".join(fv.blocks))}{(" — " + e(fv.blocked_decision)) if fv.blocked_decision else ""}</p>' if fv.blocks or fv.blocked_decision else ''}
{f'<p class="small"><b>Рекомендация:</b> {e(fv.recommendation)}</p>' if fv.recommendation else ''}
<div class="fragments">{''.join(frags) or '<p class="muted">Опоры не приведены.</p>'}</div>
</details>"""
        )
    return f'<section class="card" id="findings"><h2>Замечания ({len(view.findings)})</h2>{"".join(out)}</section>'


def attention_section(view: rv.ReportView) -> str:
    items = rv.attention_items(view)
    if not items:
        return '<section class="card" id="attention"><h2>Что ещё требует внимания</h2><p>По данным отчёта открытых пунктов нет.</p></section>'
    lis = "".join(
        f'<li class="att-{e(i["kind"])}">{("<span class=sev>" + e(rv.SEVERITY.get(i["severity"], (i["severity"],))[0]) + "</span> ") if i["severity"] else ""}{_link_ids(i["text"])}</li>'
        for i in items
    )
    return f'<section class="card" id="attention"><h2>Что ещё требует внимания</h2><ul>{lis}</ul></section>'


def compare_summary(view: rv.ReportView, run: dict[str, Any], parent: dict[str, Any] | None, parent_view: rv.ReportView | None, prefix: str) -> str:
    if not run.get("parent_run_id"):
        return ""
    pid = run["parent_run_id"]
    diff = view.diff
    if diff is None:
        dtxt = '<p class="notice warn">Движок не заполнил diff (№09): сравнение замечаний недоступно, ниже — только сводные числа обоих отчётов.</p>'
    else:
        dtxt = (
            f'<p class="diffline">Устранено: <b>{len(diff["resolved"])}</b> · новые: <b>{len(diff["introduced"])}</b> · остались: <b>{len(diff["persisting"])}</b>'
            + (f' · не сопоставлены: <b>{len(diff["unassessed"])}</b>' if diff["unassessed"] else "")
            + "</p>"
        )
    if view.mode == "mock":
        dtxt += ('<p class="muted small" id="mock-diff-note">Режим mock: ответы модели взяты из записанного сценария и после правки '
                 "не меняются, поэтому замечания этапов с моделью повторяются. Изменение текста видно в блоке «Изменённые пункты»; "
                 "переоценку правки даёт прогон с живой моделью.</p>")
    before = parent_view.counts if parent_view else None
    nums = ""
    if before:
        nums = f'<p class="muted">Критичных: {before["critical"]} → {view.counts["critical"]}; всего замечаний: {before["total"]} → {view.counts["total"]}; разработка: {e(parent_view.development["label"])} → {e(view.development["label"])}</p>'
    ans = run.get("answers") or {}
    ans_txt = ""
    if ans:
        prov = "; ".join(f"{k}: {v}" for k, v in (ans.get("provenance") or {}).items())
        imp = ans.get("import") or {}
        imp_txt = ""
        if imp:
            imp_txt = (
                f'<br>Импорт: {e(imp.get("original_name"))} · {e(imp.get("format_label") or imp.get("format"))} · разбор: {e(imp.get("parser"))} · '
                f'заявленная версия <code>{e(short(imp.get("declared_sha256")))}</code> совпала с документом · '
                f'<a href="{prefix}/runs/{e(imp.get("parent_run_id"))}/imports/{e(imp.get("import_id"))}.md">оригинал</a> · '
                f'<a href="{prefix}/runs/{e(run["run_id"])}/input/answers_uploaded.md">копия во входе редакции</a>'
            )
        ans_txt = (
            f'<p class="provenance" id="answers-provenance">Ответы этой редакции: {e(ans.get("count"))} ({e(prov)}) · '
            f'версия <code>{e(short(ans.get("source_sha256")))}</code> · <a href="{prefix}/runs/{e(run["run_id"])}/input/answers.md">собранный answers.md</a>{imp_txt}</p>'
        )
    if view.decisions:
        lis = "".join(
            f"<li><b>{e(d.get('question_id'))}</b>: {e(d.get('answer'))}"
            + (f" <span class=muted>· правок текста: {len(d.get('edits') or [])}</span>" if d.get("edits") else "")
            + (f" <span class=muted>· {e(d.get('note'))}</span>" if d.get("note") else "")
            + "</li>"
            for d in view.decisions
        )
        ans_txt += f'<details class="decisions"><summary>Решения, учтённые движком ({len(view.decisions)})</summary><ul>{lis}</ul></details>'
    return f"""<section class="card" id="compare-summary"><h2>Сравнение с редакцией {e(parent['revision'] if parent else '?')}</h2>
{dtxt}{nums}{ans_txt}
<p><a class="button" href="{prefix}/runs/{e(run['run_id'])}/compare">Открыть сравнение</a>
<a class="button" href="{prefix}/runs/{e(pid)}">Исходный отчёт</a></p></section>"""


def downloads_section(run: dict[str, Any], artifacts: list[dict[str, Any]], prefix: str) -> str:
    if not artifacts:
        msg = "Движок пока не записал файлов." if run["status"] in ("started", "running") else "Движок не записал ни одного файла."
        return f'<section class="card" id="downloads"><h2>Файлы</h2><p class="muted">{msg}</p></section>'

    def row(a: dict[str, Any]) -> str:
        name = a["name"]
        origin = "веб-слой" if a["origin"] == "web" else "движок"
        view_link = ""
        if name.endswith((".html", ".md", ".json", ".jsonl", ".csv", ".txt")):
            view_link = f' · <a href="{prefix}/runs/{e(run["run_id"])}/files/{e(name)}?inline=1" target="_blank" rel="noopener">открыть</a>'
        return (
            f'<li><a href="{prefix}/runs/{e(run["run_id"])}/files/{e(name)}" download>{e(name)}</a> '
            f'<span class="muted">{e(fmt_size(a["size"]))} · {origin} · sha256 {e(a["sha256"][:12])}…</span>{view_link}</li>'
        )

    main = [a for a in artifacts if "/" not in a["name"] or a["name"].startswith("web/")]
    main.sort(key=lambda a: (not a["name"].startswith("report."), a["name"]))
    service = [a for a in artifacts if a not in main]
    extra = ""
    if service:
        extra = f'<details class="service-files"><summary>Служебные файлы движка ({len(service)}): этапы и трасса</summary><ul class="files">{"".join(row(a) for a in service)}</ul></details>'
    return f'<section class="card" id="downloads"><h2>Файлы запуска</h2><ul class="files">{"".join(row(a) for a in main)}</ul>{extra}</section>'


def passport(run: dict[str, Any]) -> str:
    rep = run.get("report") or {}
    inp = run["input"]
    return f"""<footer class="passport"><h2>Паспорт запуска</h2><dl>
<dt>run_id</dt><dd><code>{e(run['run_id'])}</code></dd>
<dt>Файл</dt><dd>{e(inp['original_name'])} → <code>input/{e(inp['file'])}</code>, {e(fmt_size(inp['size']))}, sha256 <code>{e(inp['sha256'])}</code></dd>
<dt>Редакция</dt><dd>{e(run.get('revision'))}{(' · родитель <a href="/runs/' + e(run['parent_run_id']) + '"><code>' + e(run['parent_run_id']) + '</code></a>') if run.get('parent_run_id') else ''}{(' · повтор запуска <code>' + e(run['retry_of']) + '</code>') if run.get('retry_of') else ''}</dd>
<dt>Создан / начат / завершён</dt><dd>{e(fmt_time(run.get('created_at')))} / {e(fmt_time(run.get('started_at')))} / {e(fmt_time(run.get('finished_at')))}</dd>
<dt>Движок</dt><dd><code>{e((run.get('engine') or {}).get('target'))}</code> {e((run.get('engine') or {}).get('version') or '')}</dd>
<dt>Параметры run_review</dt><dd><code>{e(", ".join(run.get('engine_options') or []) or run.get('options'))}</code>{(' · не переданы (нет в RunOptions движка): <code>' + e(", ".join(run['engine_options_dropped'])) + '</code>') if run.get('engine_options_dropped') else ''}</dd>
<dt>Отчёт</dt><dd>режим {e(rep.get('mode') or '—')} · модель {e(rep.get('model') or '—')} · физических вызовов {e((rep.get('calls') or {}).get('physical', '—') if isinstance(rep.get('calls'), dict) else rep.get('calls', '—'))} · source_sha256 <code>{e(rep.get('source_sha256') or '—')}</code></dd>
</dl></footer>"""


def lineage_nav(lineage: list[dict[str, Any]], current: str, prefix: str) -> str:
    if len(lineage) <= 1:
        return ""
    parts = []
    for r in lineage:
        label = f"ред. {r.get('revision')}" + (" (повтор)" if r.get("retry_of") else "")
        tone = STATUS.get(r["status"], ("", "neutral"))[1]
        if r["run_id"] == current:
            parts.append(f'<b class="lin {tone}">{e(label)}</b>')
        else:
            parts.append(f'<a class="lin {tone}" href="{prefix}/runs/{e(r["run_id"])}">{e(label)}</a>')
    return '<nav class="lineage">Редакции: ' + " → ".join(parts) + "</nav>"


def run_page(
    ctx: dict[str, Any],
    run: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    view: rv.ReportView | None,
    report_problem: str | None,
    artifacts: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
    latest: dict[str, Any] | None,
    parent: dict[str, Any] | None,
    parent_view: rv.ReportView | None,
    eta: dict[str, Any] | None,
    queue_pos: int,
    elapsed: float | None,
    demo_answers: list[dict[str, Any]],
    duplicate: bool = False,
    manual_import: dict[str, Any] | None = None,
    imports: list[dict[str, Any]] | None = None,
) -> str:
    prefix = ctx["prefix"]
    demo_banner = ""
    if duplicate:
        demo_banner += (
            '<p class="notice info" id="duplicate">Это действие уже было принято раньше: открыт ранее созданный запуск, '
            "второй анализ не запускался.</p>"
        )
    if ctx.get("demo"):
        rep = run.get("report") or {}
        demo_banner += (
            f'<div class="banner demo" id="demo-banner">Демонстрация сохранённого прогона: выполнен {e(fmt_time(run.get("finished_at")))}, '
            f'модель <code>{e(rep.get("model") or "—")}</code>, режим {e(rep.get("mode") or "—")}. Это не живой анализ — новый запуск отсюда не выполняется.</div>'
        )
    head = f'<h1>{e(run["input"]["original_name"])} <span class="muted">· редакция {e(run.get("revision"))}</span></h1>'
    derived = run["input"].get("derived_from") or {}
    head += (
        f'<p class="muted small" id="input-version">Вход редакции: SHA-256 <code title="{e(run["input"]["sha256"])}">{e(short(run["input"]["sha256"]))}</code>'
        + (f' — файл редакции движка {e(derived.get("artifact"))} из <a href="{prefix}/runs/{e(derived.get("run_id"))}">{e(derived.get("run_id"))}</a>' if derived else "")
        + (f' · документ отчёта <code title="{e(view.raw["document"].get("id"))}">{e(short(view.raw["document"].get("id")))}</code>'
           if view is not None and (view.raw.get("document") or {}).get("id") not in (None, run["input"]["sha256"]) else "")
        + "</p>"
    )
    not_latest = ""
    if latest and latest["run_id"] != run["run_id"] and run["status"] in ("complete", "partial", "failed"):
        not_latest = (
            f'<p class="notice warn" id="not-latest">Открыта редакция {e(run.get("revision"))}, она не актуальная. '
            f'Актуальная — редакция {e(latest.get("revision"))}: <a href="{prefix}/runs/{e(latest["run_id"])}">открыть</a>. '
            f"Статус, вопросы и файлы на этой странице относятся к редакции {e(run.get('revision'))}.</p>"
        )
    body = demo_banner + lineage_nav(lineage, run["run_id"], prefix) + not_latest + head
    body += status_section(run, events, eta=eta, queue_pos=queue_pos, elapsed=elapsed, ctx=ctx, report_stages=view.stages if view else None)
    if view is not None:
        files = {}
        names = {a["name"] for a in artifacts}
        if "report.html" in names:
            files["HTML (№13)"] = f"{prefix}/runs/{run['run_id']}/files/report.html?inline=1"
        if "report.md" in names:
            files["Markdown"] = f"{prefix}/runs/{run['run_id']}/files/report.md?inline=1"
        body += verdict_section(view, run, files)
        body += changes_section(view)
        body += compare_summary(view, run, parent, parent_view, prefix)
        body += attention_section(view) if run.get("parent_run_id") else ""
        body += action_section(view, run, ctx=ctx, latest=latest, demo_answers=demo_answers, manual_import=manual_import)
        body += imports_section(run, imports or [], prefix)
        body += downloads_section(run, artifacts, prefix)
        body += findings_section(view)
        if view.contract_notes:
            body += f'<details class="card muted"><summary>Расхождения с контрактом v1 ({len(view.contract_notes)})</summary><ul>{"".join("<li>" + e(n) + "</li>" for n in view.contract_notes)}</ul></details>'
    else:
        if run["status"] in ("complete", "partial"):
            body += f'<p class="notice bad">Отчёт не читается: {e(report_problem)}</p>'
        body += downloads_section(run, artifacts, prefix)
    body += passport(run)
    return layout(f"{run['input']['original_name']} · {run['run_id']}", body, ctx=ctx, run_status=run["status"], run_id=run["run_id"])


def compare_page(ctx: dict[str, Any], run: dict[str, Any], parent: dict[str, Any], view: rv.ReportView | None, parent_view: rv.ReportView | None) -> str:
    prefix = ctx["prefix"]

    def col(title: str, r: dict[str, Any], v: rv.ReportView | None) -> str:
        if v is None:
            return f'<div class="col"><h2>{e(title)}</h2><p class="muted">Отчёт недоступен ({e(r["status"])})</p></div>'
        crit = "".join(f'<li><a href="{prefix}/runs/{e(r["run_id"])}#{e(f.id)}">{e(f.id)}</a> {e(f.title)}</li>' for f in v.findings if f.severity == "critical")
        return f"""<div class="col"><h2>{e(title)}</h2>
<p><a href="{prefix}/runs/{e(r['run_id'])}"><code>{e(r['run_id'])}</code></a> · {status_badge(r['status'])}</p>
<p>Разработка: <b>{e(v.development['label'])}</b><br>Тестирование: <b>{e(v.testing['label'])}</b></p>
<p>Замечаний {v.counts['total']}: критичных {v.counts['critical']}, существенных {v.counts['major']}, незначительных {v.counts['minor']}</p>
<p class="muted">Режим {e(v.mode_label)} · модель {e(v.run.get('model') or '—')}</p>
<h3>Критичные</h3><ul>{crit or '<li class="muted">нет</li>'}</ul>
<p><a href="{prefix}/runs/{e(r['run_id'])}/files/report.md?inline=1" target="_blank">report.md</a>{(' · <a href="' + prefix + '/runs/' + e(r['run_id']) + '/files/report.html?inline=1" target="_blank">report.html</a>') if (v and (r.get('artifacts') and any(a['name']=='report.html' for a in r['artifacts']))) else ''}</p></div>"""

    diff_html = ""
    if view is not None and view.diff is not None:
        def lst(name: str, title: str) -> str:
            items = view.diff[name]
            lis = "".join(
                f'<li>{("<span class=sev>" + e(rv.SEVERITY.get(d["severity"], (d["severity"],))[0]) + "</span> ") if d["severity"] else ""}'
                f'{e(" → ".join(filter(None, [", ".join(d["old_ids"]), ", ".join(d["new_ids"])])))} {e(d["title"])}'
                f'{(" <span class=muted>· " + e(d["reason"]) + "</span>") if d["reason"] else ""}</li>'
                for d in items
            )
            return f'<div class="col"><h3>{e(title)} ({len(items)})</h3><ul>{lis or "<li class=muted>нет</li>"}</ul></div>'

        diff_html = (
            '<section class="card" id="diff"><h2>Изменения замечаний (diff №09)</h2><div class="cols">'
            + lst("resolved", "Устранены") + lst("introduced", "Новые") + lst("persisting", "Остались") + "</div>"
            + (lst("unassessed", "Не сопоставлены") if view.diff["unassessed"] else "") + "</section>"
        )
    elif view is not None:
        diff_html = '<p class="notice warn">Движок не заполнил diff (№09).</p>'
    att = attention_section(view) if view is not None else ""
    body = (
        f'<h1>Сравнение редакций {e(parent.get("revision"))} и {e(run.get("revision"))}</h1>'
        f'<section class="card"><div class="cols">{col("Исходная редакция " + str(parent.get("revision")), parent, parent_view)}{col("Обновлённая редакция " + str(run.get("revision")), run, view)}</div></section>'
        + diff_html
        + att
    )
    return layout("Сравнение редакций", body, ctx=ctx)


def message_page(ctx: dict[str, Any], title: str, message: str, links: Iterable[tuple[str, str]] = ()) -> str:
    links_html = "".join(f'<a class="button" href="{e(href)}">{e(label)}</a> ' for label, href in links)
    return layout(title, f'<section class="card"><h1>{e(title)}</h1><p>{e(message)}</p><p>{links_html}</p></section>', ctx=ctx)


def new_key() -> str:
    return secrets.token_urlsafe(18)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
