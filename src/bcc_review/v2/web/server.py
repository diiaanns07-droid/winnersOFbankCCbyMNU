"""HTTP-сервер веб-демо v2 на стандартной библиотеке.

Маршруты::

    GET  /                          загрузка файла, выбор провайдера, последние проверки
    POST /api/jobs                  файл (multipart) + provider + model → 303 /jobs/<id> (JSON при Accept: application/json)
    GET  /jobs/<id>                 прогресс по этапам, затем отчёт и выгрузки
    GET  /api/jobs/<id>             состояние задания (для опроса)
    GET  /jobs/<id>/files/<имя>     скачать файл отчёта (?inline=1 — открыть в браузере)
    GET  /api/providers             какие провайдеры доступны
    GET  /healthz                   ok
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shlex
import socket
import sys
import time
import urllib.request
import webbrowser
from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from .runner import (ALLOWED_EXT, FILES, MAX_UPLOAD, FixtureRunner, Job, JobStore, PipelineRunner, Worker,
                     check_provider, load_dotenv, provider_status)

ASSETS = Path(__file__).with_name("assets")
# №39: tokens.css — дизайн-система; agent.* — BCC AI (№40), отдаются, когда файлы появятся
ASSET_NAMES = ("app.css", "app.js", "tokens.css", "agent.css", "agent.js")
REPO = Path(__file__).resolve().parents[4]
JOB_PATH = re.compile(r"^/(api/)?jobs/(?P<id>\d{8}-\d{6}-[0-9a-f]{6})(?P<rest>/.*)?$")

VERDICT = {"no": ("Нельзя", "no"), "conditional": ("С условиями", "cond"), "yes": ("Можно", "yes")}


def e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


class App:
    def __init__(self, store: JobStore, worker: Worker, *, default_provider: str = "auto", sample: Path | None = None):
        self.store = store
        self.worker = worker
        self.default_provider = default_provider
        self.sample = sample if sample and sample.is_file() else None

    def start(self, file_name: str, data: bytes, provider: str, model: str, *, parent: str = "",
              answers: bytes = b"") -> Job:
        job = self.store.create(file_name, data, provider, model, parent=parent, answers=answers)
        self.worker.submit(job)
        return job


# ─────────────────────────────── страницы ───────────────────────────────

def _layout(title: str, body: str, *, sub: str = "") -> str:
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230E7C55'/%3E%3Cpath d='M9 16.5l4.5 4.5L23 11' stroke='white' stroke-width='3.2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<link rel="stylesheet" href="/assets/app.css">
</head><body>
<header class="top"><a class="brand" href="/"><span class="logo" aria-hidden="true"></span><span><span class="bname">Ревью требований</span>
<span class="bsub">{e(sub or "ИИ-агент статического ревью ТЗ · BCC-HUB × MNU")}</span></span></a></header>
{body}
<script src="/assets/app.js"></script>
</body></html>"""


def index_page(app: App, *, error: str = "", provider: str = "", model: str = "") -> str:
    provs = provider_status()
    sel = provider or app.default_provider
    opts = []
    for p in provs:
        mark = "" if p["ok"] else " — недоступен"
        opts.append(f'<option value="{e(p["id"])}" data-ok="{1 if p["ok"] else 0}" data-note="{e(p["note"])}" '
                    f'data-models="{e(",".join(p["models"]))}"{" selected" if p["id"] == sel else ""}>'
                    f'{e(p["label"])}{mark}</option>')
    sample = ""
    if app.sample:
        sample = (f'<button type="submit" class="btn ghost" name="sample" value="1" formnovalidate>'
                  f'Проверить пример: {e(app.sample.name)}</button>')
    rows = []
    for j in app.store.recent():
        s = j.summary or {}
        v = VERDICT.get(s.get("development", ""), ("—", "none"))
        state = {"queued": "в очереди", "running": "идёт анализ", "done": "готово", "failed": "ошибка"}.get(j.state, j.state)
        counts = (f'<span class="c crit">{s.get("critical", 0)}</span><span class="c major">{s.get("major", 0)}</span>'
                  f'<span class="c minor">{s.get("minor", 0)}</span>') if j.state == "done" else ""
        rows.append(f'<tr><td><a href="/jobs/{e(j.id)}">{e(j.file_name)}</a></td>'
                    f'<td>{e(time.strftime("%d.%m %H:%M", time.localtime(j.created)))}</td>'
                    f'<td>{e(j.provider)}{(" · " + e(j.model)) if j.model else ""}</td>'
                    f'<td><span class="st st-{e(j.state)}">{e(state)}</span></td>'
                    f'<td>{f"<span class=vd-{v[1]}>{e(v[0])}</span>" if j.state == "done" else ""}</td><td>{counts}</td></tr>')
    recent = (f'<section class="card recent"><h2>Последние проверки</h2><div class="tw"><table><thead><tr><th>Файл</th>'
              f'<th>Когда</th><th>Провайдер</th><th>Статус</th><th>Разработка</th><th>Замечания</th></tr></thead>'
              f'<tbody>{"".join(rows)}</tbody></table></div></section>') if rows else ""
    err = f'<div class="error" role="alert">{e(error)}</div>' if error else ""
    body = f"""<main class="wrap">
<section class="intro">
  <h1>Проверка требований до начала разработки</h1>
  <p>Загрузите техническое задание — агент найдёт противоречия, пробелы и непроверяемые формулировки.
  Каждое замечание — с дословной цитатой и номером строки, которые проверены программой.</p>
</section>
<form class="card upload" id="form" method="post" action="/api/jobs" enctype="multipart/form-data">
  {err}
  <label class="drop" id="drop">
    <input type="file" name="file" id="file" accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm" required>
    <span class="dicon" aria-hidden="true"></span>
    <span class="dtitle">Перетащите файл требований сюда или <u>выберите на компьютере</u></span>
    <span class="dsub">PDF, Word (DOCX), Markdown, TXT, HTML · до 20 МБ</span>
    <span class="fname" id="fname"></span>
  </label>
  <div class="row">
    <label class="fld">Модель<select name="provider" id="provider">{"".join(opts)}</select></label>
    <label class="fld narrow">Вариант модели<input name="model" id="model" list="models" value="{e(model)}" placeholder="по умолчанию" autocomplete="off"><datalist id="models"></datalist></label>
  </div>
  <p class="pnote" id="pnote"></p>
  <div class="actions"><button type="submit" class="btn big" id="go">Проверить требования</button>{sample}</div>
</form>
{recent}
<section class="how">
  <div><b>1. Документ</b><span>Читаем PDF, Word, Markdown; нумеруем строки, нарезаем требования и присваиваем им ID.</span></div>
  <div><b>2. Четыре ревьюера</b><span>Аналитик, тестировщик, архитектор и риски смотрят параллельно, отдельно — согласованность набора.</span></div>
  <div><b>3. Судья</b><span>Убирает дубли и ложные срабатывания, ставит критичность и выносит вердикт: можно ли начинать.</span></div>
</section>
</main>"""
    return _layout("Ревью требований", body)


# ─────────────────── страница задания: прогресс и отчёт (№41) ───────────────────

_CALLS = re.compile(r"готово за .*?вызовов (\d+)")
FILE_NOTE = {"html": "отчёт целиком, открывается без сервера", "md": "для Git и вики", "json": "для систем и CI",
             "docx": "для согласования", "pdf": "для печати", "csv": "задачи в Jira",
             "docx_annotated": "исходный документ с комментариями", "pdf_annotated": "исходный PDF с выделениями",
             "revised": "ТЗ с правками по ответам"}
EXTRA_TABS = [("clarify", "До и после"), ("tests", "Тест-кейсы"), ("checklist", "Чек-лист банка"),
              ("checks", "Проверки"), ("segment", "Нарезка"), ("rejected", "Отклонённые"), ("passport", "Паспорт")]


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _dur(s: Any) -> str:
    try:
        s = max(0, round(float(s)))
    except (TypeError, ValueError):
        return ""
    return f"{s} с" if s < 60 else f"{s // 60} мин {s % 60:02d} с"


def job_calls(job: Job) -> int:
    """Вызовы модели по журналу прогона («этап: готово за N с, вызовов K»); 0 — пока неизвестно."""
    return sum(int(m.group(1)) for line in job.log for m in [_CALLS.search(line)] if m)


def report_facts(app: App | None, job: Job) -> dict[str, Any] | None:
    """Что показать над отчётом: вердикт, четыре числа, блокеры — из того же report.json, что и отчёт."""
    if app is None or job.state != "done":
        return None
    try:
        report = json.loads((app.store.dir(job.id) / "out" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    from bcc_review.v2.render import html as H
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    run = report.get("run") or {}
    verdict = report.get("verdict") or {}
    summary = report.get("summary") or {}
    ok, total = H._quotes_verified(report)
    qv, qt = summary.get("quotes_verified"), summary.get("quotes_total")
    if isinstance(qv, int) and isinstance(qt, int) and not isinstance(qv, bool) and qt >= qv >= 0:
        ok, total = qv, qt
    status = run.get("status", "")
    blockers = []
    for f in findings:
        if H._sev(f) != "critical":
            continue
        ev0 = (f.get("evidence") or [{}])[0]
        sec = str(ev0.get("section") or "").split(" › ")[-1]
        blockers.append({"id": f.get("id", ""), "title": f.get("title", ""), "blocks": f.get("blocks", ""),
                         "where": H._lines_label(ev0) + (f" · {sec}" if sec else "")})
    present = {"clarify": bool(report.get("clarification")),
               "rewrites": bool(report.get("rewrites"))}
    return {
        "development": verdict.get("development", "") if status != "failed" else "",
        "testing": verdict.get("testing", "") if status != "failed" else "",
        "critical": len(blockers), "major": sum(1 for f in findings if H._sev(f) == "major"),
        "minor": sum(1 for f in findings if H._sev(f) == "minor"), "findings": len(findings),
        "questions": len(report.get("questions") or []), "quotes_ok": ok, "quotes_total": total,
        "blockers": blockers, "status": status,
        "model": ", ".join(run.get("models_used") or []) or run.get("model_requested") or "",
        "duration": run.get("duration_s"), "calls": (run.get("calls") or {}).get("total"),
        "counts": {"tests": len(report.get("test_cases") or []), "checklist": len(report.get("checklist") or []),
                   "checks": len(report.get("acceptance_checks") or []) + len(report.get("pair_checks") or []),
                   "segment": len(report.get("requirements") or []), "rejected": len(report.get("rejected") or [])},
        "has": present,
    }


def _verdict_html(f: dict) -> str:
    from bcc_review.v2.render.html import VERDICT_LABEL
    parts = []
    for key, label in (("development", "Разработка"), ("testing", "Тестирование")):
        v = f.get(key, "")
        cls = {"no": "no", "conditional": "cond", "yes": "yes"}.get(v, "none")
        word = VERDICT_LABEL.get(v, "нет вердикта").lower()
        parts.append(f'<span class="v v-{cls}">{label}: <b>{e(word)}</b></span>')
    return '<span class="sep">·</span>'.join(parts)


def result_html(job: Job, f: dict, *, agent: bool = True) -> str:
    """Отчёт над рамкой: вердикт, полоса из четырёх чисел, блокеры, вкладки-капсулы, рамка с HTML-отчётом."""
    jid = e(job.id)
    meta = [e(job.file_name), e(f.get("model") or job.provider)]
    if f.get("duration") is not None:
        meta.append(_dur(f["duration"]))
    if f.get("calls"):
        meta.append(f'{f["calls"]} {_plural(f["calls"], "вызов", "вызова", "вызовов")} модели')
    mood = "alert" if f["critical"] else "verified"
    agent_html = (f'<div class="jb-agent" id="agent-slot"><div data-bcc-agent data-size="96" data-mood="{mood}"></div></div>'
                  if agent else '<div class="jb-agent" id="agent-slot"></div>')
    notice = (f'<p class="b-status stale" role="status">{e(job.notice)}</p>' if job.notice else "")
    crit, major, q = f["critical"], f["major"], f["questions"]
    ok, total = f["quotes_ok"], f["quotes_total"]
    qcls = "ok" if total and ok == total else ("major" if total else "")
    strip = (f'<div class="b-strip b-surface jb-strip b-rise" aria-label="Сводка">'
             f'<div class="b-metric {"crit" if crit else "ok"}"><b>{crit}</b><span>{_plural(crit, "блокер", "блокера", "блокеров")}</span></div>'
             f'<div class="b-metric {"major" if major else ""}"><b>{major}</b><span>{_plural(major, "существенное", "существенных", "существенных")}</span></div>'
             f'<div class="b-metric {"major" if q else ""}"><b>{q}</b><span>{_plural(q, "вопрос владельцу", "вопроса владельцу", "вопросов владельцу")}</span></div>'
             f'<div class="b-metric {qcls}"><b>{ok} из {total}</b><span>цитат сверено кодом</span></div></div>')
    rows = []
    for b in f["blockers"][:7]:
        only = {"development": "только разработку", "testing": "только тестирование"}.get(b["blocks"], "")
        rows.append(f'<li><a class="b-row jb-row" href="/jobs/{jid}/files/report.html?inline=1#{e(b["id"])}" data-goto="{e(b["id"])}">'
                    f'<span class="jb-id">{e(b["id"])}</span><span class="jb-t">{e(b["title"])}</span>'
                    + (f'<span class="b-badge plain jb-only">{only}</span>' if only else "")
                    + f'<span class="jb-where">{e(b["where"])}</span><span class="jb-go" aria-hidden="true"></span></a></li>')
    if len(f["blockers"]) > 7:
        rows.append(f'<li class="b-row jb-more-b">и ещё {len(f["blockers"]) - 7} — во вкладке «Замечания»</li>')
    if not rows:
        rows.append('<li class="b-row jb-row ok"><span class="jb-id">✓</span><span class="jb-t">Блокеров нет — '
                    'критичных замечаний не найдено</span></li>')
    blockers = (f'<section class="b-surface jb-block b-rise" aria-labelledby="bh"><div class="jb-bhead">'
                f'<h2 class="b-h2" id="bh">Блокеры</h2><p class="b-note">останавливают работу, исправить первыми</p></div>'
                f'<ul class="b-list">{"".join(rows)}</ul></section>')
    tabs = [("findings", "Замечания", f["findings"]), ("questions", "Вопросы", q), ("doc", "Документ", None),
            ("revised", "Исправленная редакция", None), ("exports", "Выгрузки", None)]
    nav = "".join(f'<button type="button" role="tab" data-view="{k}" aria-selected="{"true" if i == 0 else "false"}">'
                  f'{lbl}{f" <span class=jb-cnt>{n}</span>" if n is not None else ""}</button>'
                  for i, (k, lbl, n) in enumerate(tabs))
    extra = "".join(f'<button type="button" data-rtab="{k}">{lbl}'
                    f'<span class="jb-cnt">{f["counts"].get(k, "")}</span></button>'
                    for k, lbl in EXTRA_TABS if k != "clarify" or f["has"]["clarify"])
    files = "".join(f'<li class="b-row"><span class="jb-fmt">{e(lbl)}<span class="jb-fnote">{e(FILE_NOTE.get(k, ""))}</span></span>'
                    + (f'<a class="b-button small quiet" href="/jobs/{jid}/files/{n}?inline=1" target="_blank" rel="noopener">Открыть ↗</a>'
                       if k in ("html", "pdf", "pdf_annotated") else "")
                    + f'<a class="b-button small" href="/jobs/{jid}/files/{n}" download>Скачать</a></li>'
                    for k, n, lbl, _ in FILES if k in job.files)
    answers = ("" if job.answers_path else
               f'<label class="b-button quiet" title="Файл из «Скачать ответы»: агент перепроверит замечания и покажет «до и после»">'
               f'<span>Загрузить ответы ↻</span><input type="file" name="answers" accept=".md,.txt,.json"></label>')
    clar = ('<button type="button" class="b-button quiet" data-rtab="clarify">До и после</button>'
            if f["has"]["clarify"] else "")
    revised_ready = f["has"]["rewrites"]
    return f"""<header class="jb-hero b-rise">
  {agent_html}
  <div class="jb-hmain"><h1 class="jb-verdict" id="verdict">{_verdict_html(f)}</h1>
  <p class="jb-meta">{" · ".join(meta)}</p>{notice}</div>
  <div class="jb-hact"><a class="b-button small" href="/">Новая проверка</a></div>
</header>
{strip}
{blockers}
<div class="jb-tabbar">
  <nav class="b-segment b-glass jb-tabs" role="tablist" aria-label="Разделы отчёта" id="tabs">{nav}</nav>
  <details class="jb-extra"><summary class="b-button small quiet">Ещё в отчёте</summary>
  <div class="jb-extra-menu b-glass" role="menu">{extra}</div></details>
</div>
<form class="jb-qbar" id="qbar" hidden>
  <p class="b-note">Отметьте варианты ниже, скачайте ответы и загрузите файл — агент перепроверит замечания.</p>
  <button type="button" class="b-button primary" id="dlanswers">Скачать ответы</button>{answers}{clar}
</form>
<section class="b-surface jb-empty" id="revised-empty" hidden{' data-ready="1"' if revised_ready else ''}>
  <h2 class="b-h2">Исправленная редакция</h2>
  <p>Появится после ответов владельца: отметьте варианты во вкладке «Вопросы», скачайте ответы и загрузите файл —
  агент перепроверит замечания и предложит правки текста ТЗ.</p>
  <button type="button" class="b-button primary" data-view="questions">К вопросам</button>
</section>
<section class="b-surface jb-files" id="exports" hidden><ul class="b-list">{files}</ul></section>
<div class="b-surface jb-frame" id="framebox"><iframe id="rframe" title="Отчёт ревью" data-src="/jobs/{jid}/files/report.html?inline=1"></iframe></div>"""


def job_page(job: Job, app: App | None = None) -> str:
    facts = report_facts(app, job)
    css = (ASSETS / "job.css").read_text(encoding="utf-8")
    parent = (f'<p class="jb-parent">Повторная проверка с ответами владельца к '
              f'<a href="/jobs/{e(job.parent)}">исходной проверке</a>.</p>' if job.parent else "")
    prog = f"""<section class="b-surface jb-prog b-rise" id="prog" aria-live="polite"{" hidden" if facts else ""}>
  <div class="jb-phead">
    <div class="jb-agent" id="agent-home">{"" if facts else '<div data-bcc-agent data-size="96" data-mood="scanning" id="agent"></div>'}</div>
    <div><h1 class="jb-ptitle">{e(job.file_name)}</h1>
    <p class="jb-pline" id="pline"><span id="pstate">{"в очереди" if job.state == "queued" else "идёт проверка"}</span> · <span id="elapsed">0 с</span><span id="calls"></span> · {e(job.provider)}{(" · " + e(job.model)) if job.model else ""}</p></div>
  </div>
  <ol class="jb-stages" id="stages"></ol>
  <div class="jb-err" id="err" hidden><p class="b-status error" id="errtext" role="alert"></p>
  <p class="jb-todo" id="todo"></p><a class="b-button primary" href="/">Новая проверка</a></div>
  <details class="jb-log"><summary>Журнал запуска</summary><pre id="log"></pre></details>
</section>"""
    body = f"""<style>{css}</style>
<main class="b-wrap jb" data-job="{e(job.id)}" data-state="{e(job.state)}">
{parent}
{prog}
<section class="jb-result" id="result"{"" if facts else " hidden"}>{result_html(job, facts) if facts else ""}</section>
</main>"""
    page = _layout(f"Проверка: {job.file_name}", body, sub=job.file_name)
    # до вливания №39 _layout ещё без токенов — подключаем сами (после вливания ветка не срабатывает)
    if "/assets/tokens.css" not in page:
        page = page.replace('<link rel="stylesheet" href="/assets/app.css">',
                            '<link rel="stylesheet" href="/assets/tokens.css"><link rel="stylesheet" href="/assets/app.css">')
    if "<body>" in page:
        page = page.replace("<body>", '<body class="b-root">', 1)
    return page


# ─────────────────────────────── обработчик ───────────────────────────────

def _parse_multipart(ctype: str, body: bytes) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    msg = BytesParser(policy=policy.HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True) or b""
        fname = part.get_filename()
        if fname is not None:
            files[name] = (fname, data)
        else:
            fields[name] = data.decode("utf-8", errors="replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "bcc-review-web/2"

    def log_message(self, fmt: str, *args: Any) -> None:  # тише в консоли
        if "/api/jobs/" in (args[0] if args else ""):
            return
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # ── ответы ──
    def _send(self, code: int, body: bytes, ctype: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, code: int, text: str) -> None:
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _wants_json(self) -> bool:
        return "application/json" in (self.headers.get("Accept") or "")

    # ── GET ──
    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        path = url.path
        if path == "/":
            return self._html(200, index_page(self.app))
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain; charset=utf-8")
        if path == "/api/providers":
            return self._json(200, provider_status())
        if path.startswith("/assets/"):
            name = path.rsplit("/", 1)[-1]
            p = ASSETS / name
            if p.is_file() and name in ASSET_NAMES:
                ctype = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                return self._send(200, p.read_bytes(), ctype)
            return self._html(404, _layout("Не найдено", '<main class="wrap"><p>Файл не найден.</p></main>'))
        m = JOB_PATH.match(path)
        if m:
            job = self.app.store.get(m.group("id"))
            if not job:
                return self._not_found()
            rest = m.group("rest") or ""
            if m.group(1):  # /api/jobs/<id>  # №41: + вызовы модели по журналу
                return self._json(200, {**job.public(), "calls": job_calls(job)})
            if not rest:  # №41: ?part=result — отчёт над рамкой, когда прогон закончился при открытой странице
                if "part" in parse_qs(url.query):
                    f = report_facts(self.app, job)
                    return self._html(200 if f else 409, result_html(job, f, agent=False) if f else "")
                return self._html(200, job_page(job, self.app))
            if rest.startswith("/files/"):
                return self._file(job, rest[len("/files/"):], "inline" in parse_qs(url.query))
        return self._not_found()

    def _not_found(self) -> None:
        if self._wants_json() or self.path.startswith("/api/"):
            return self._json(404, {"error": "не найдено"})
        self._html(404, _layout("Не найдено", '<main class="wrap"><section class="card"><h1>Не найдено</h1>'
                                '<p><a href="/">Вернуться к загрузке</a></p></section></main>'))

    def _file(self, job: Job, name: str, inline: bool) -> None:
        known = {n: (lbl, mime) for _, n, lbl, mime in FILES}
        if name not in known:
            return self._not_found()
        p = self.app.store.dir(job.id) / "out" / name
        if not p.is_file():
            return self._not_found()
        stem = Path(job.file_name).stem
        dl = f"{stem}.{name.split('.', 1)[1]}"
        disp = "inline" if inline else "attachment"
        self._send(200, p.read_bytes(), known[name][1],
                   {"Content-Disposition": f"{disp}; filename=\"report.{name.split('.', 1)[1]}\"; filename*=UTF-8''{quote(dl)}"})

    # ── POST ──
    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        m = JOB_PATH.match(path)
        if m and m.group(1) and m.group("rest") == "/answers":
            return self._answers(m.group("id"))
        if path != "/api/jobs":
            return self._not_found()
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD + 64 * 1024:
            return self._fail(413, "Файл больше 20 МБ.")
        body = self.rfile.read(length)
        if len(body) < length:
            return self._fail(400, "Загрузка оборвалась — отправьте файл ещё раз.")
        fields, files = _parse_multipart(self.headers.get("Content-Type", ""), body)
        provider = (fields.get("provider") or self.app.default_provider).strip()
        model = (fields.get("model") or "").strip()[:80]
        if fields.get("sample") and self.app.sample:
            fname, data = self.app.sample.name, self.app.sample.read_bytes()
        else:
            fname, data = files.get("file", ("", b""))
        if not fname or not data:
            return self._fail(400, "Выберите файл требований.", provider, model)
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_EXT:
            return self._fail(400, f"Формат {ext or 'без расширения'} не поддерживается: загрузите PDF, DOCX, MD, TXT или HTML.",
                              provider, model)
        problem = check_provider(provider, model)
        if problem:
            return self._fail(400, problem, provider, model)
        job = self.app.start(fname, data, provider, model)
        if self._wants_json():
            return self._json(201, {"id": job.id, "url": f"/jobs/{job.id}"})
        self._send(303, b"", "text/plain", {"Location": f"/jobs/{job.id}"})

    def _answers(self, parent_id: str) -> None:
        """Ответы владельца на вопросы отчёта → новый прогон того же документа с --answers --revise."""
        parent = self.app.store.get(parent_id)
        if not parent or parent.state != "done":
            return self._json(404, {"error": "Исходная проверка не найдена или ещё не завершена."})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2 * 1024 * 1024:
            return self._json(413, {"error": "Файл ответов больше 2 МБ."})
        fields, files = _parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
        data = files.get("answers", ("", b""))[1] or (fields.get("answers_text") or "").encode("utf-8")
        if not data.strip():
            return self._json(400, {"error": "Загрузите файл ответов (кнопка «Скачать ответы» во вкладке «Вопросы» отчёта)."})
        problem = check_provider(parent.provider, parent.model)
        if problem:
            return self._json(400, {"error": problem})
        src = Path(parent.input_path)
        job = self.app.start(parent.file_name, src.read_bytes(), parent.provider, parent.model,
                             parent=parent.id, answers=data)
        self._json(201, {"id": job.id, "url": f"/jobs/{job.id}"})

    def _fail(self, code: int, msg: str, provider: str = "", model: str = "") -> None:
        if self._wants_json():
            return self._json(code, {"error": msg})
        self._html(code, index_page(self.app, error=msg, provider=provider, model=model))


class _Server(ThreadingHTTPServer):
    """На Windows SO_REUSEADDR пускает второй сервер на занятый порт молча — там берём исключительный порт."""
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(app: App, host: str = "127.0.0.1", port: int = 8014) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = _Server((host, port), handler)
    srv.daemon_threads = True
    return srv


_ADDR_IN_USE = {errno.EADDRINUSE, 10048, 10013}  # 10048/10013 — WSAEADDRINUSE/WSAEACCES (порт занят или запрещён)


def _is_demo_running(host: str, port: int) -> bool:
    """Отвечает ли на этом порту уже запущенное веб-демо (тогда второй запуск не нужен)."""
    probe = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    try:
        with urllib.request.urlopen(f"http://{probe}:{port}/healthz", timeout=1.5) as r:
            return r.read(16) == b"ok" and (r.headers.get("Server") or "").startswith("bcc-review-web")
    except Exception:  # noqa: BLE001 — любой сбой пробы значит «нашего демо там нет»
        return False


def bind_server(app: App, host: str, port: int, *, tries: int = 20) -> tuple[ThreadingHTTPServer | None, str]:
    """Сервер на `port`, а если порт занят чужой программой — на следующем свободном.

    Возвращает (сервер, сообщение). Сервер None — запускать не нужно или нельзя; сообщение объясняет почему
    (по-русски, с адресом уже запущенного демо или подсказкой про --port).
    """
    for p in ([port] + [port + i for i in range(1, tries + 1)] if port else [0]):
        try:
            srv = make_server(app, host, p)
        except OSError as exc:
            if getattr(exc, "winerror", None) not in _ADDR_IN_USE and exc.errno not in _ADDR_IN_USE:
                why = ("такого адреса нет" if isinstance(exc, socket.gaierror) else
                       "нет прав на этот порт (порты до 1024 — только администратору)" if isinstance(exc, PermissionError)
                       else f"ошибка системы {exc.errno}")
                return None, (f"Не удалось запустить веб-демо на {host}:{p}: {why}. "
                              f"Укажите другой адрес: --host 127.0.0.1 --port 8015.")
            if p == port and _is_demo_running(host, port):
                return None, f"Веб-демо уже запущено: http://{host}:{port}/ — откройте этот адрес в браузере."
            continue
        note = "" if p == port else f"Порт {port} занят другой программой — веб-демо запущено на порту {p}."
        return srv, note
    return None, (f"Порты {port}–{port + tries} заняты другими программами. "
                  f"Укажите свободный порт: python -m bcc_review.v2.web --port 9000.")


def build_app(data_dir: Path, *, provider: str = "auto", fixture: Path | None = None, sample: Path | None = None,
              step_s: float = 0.6, workers: int = 1, extra_args: list[str] | None = None,
              cache_dir: Path | None = None, pace: float = 0.0) -> App:
    store = JobStore(data_dir)
    runner = (FixtureRunner(store, fixture, step_s=step_s) if fixture else
              PipelineRunner(store, extra_args=extra_args, cache_dir=cache_dir or Path(data_dir) / "cache", pace=pace))
    if sample is None:
        cand = REPO / "release" / "input" / "requirements.md"
        sample = cand if cand.is_file() else None
    return App(store, Worker(store, runner, workers), default_provider=provider, sample=sample)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.web", description="Веб-демо ревью требований")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8014)
    ap.add_argument("--provider", default="auto", help="провайдер по умолчанию в форме")
    ap.add_argument("--data-dir", default=".bcc_web", help="где хранить загрузки и отчёты")
    ap.add_argument("--sample", help="файл для кнопки «Проверить пример»")
    ap.add_argument("--fixture", help="показ без модели: этапы по таймеру, отчёт из этого report.json")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--pipeline-args", default="", help="доп. флаги для python -m bcc_review, например \"--engine v1\"")
    ap.add_argument("--cache-dir", help="кэш ответов модели, общий для всех проверок (по умолчанию <data-dir>/cache)")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="для съёмки демо: показывать этапы не быстрее раза в N секунд (анализ не замедляется)")
    ap.add_argument("--open", action="store_true", help="открыть браузер")
    a = ap.parse_args(argv)
    load_dotenv()
    app = build_app(Path(a.data_dir), provider=a.provider, fixture=Path(a.fixture) if a.fixture else None,
                    sample=Path(a.sample) if a.sample else None, workers=a.workers,
                    cache_dir=Path(a.cache_dir) if a.cache_dir else None, pace=a.pace,
                    extra_args=shlex.split(a.pipeline_args, posix=(os.name != "nt")))
    srv, note = bind_server(app, a.host, a.port)
    if srv is None:
        running = note.startswith("Веб-демо уже запущено")
        print(note, file=sys.stdout if running else sys.stderr, flush=True)
        if running and a.open:
            webbrowser.open(f"http://{'127.0.0.1' if a.host in ('', '0.0.0.0', '::') else a.host}:{a.port}/")
        return 0 if running else 2
    if note:
        print(note, flush=True)
    url = f"http://{a.host}:{srv.server_address[1]}/"
    print(f"Веб-демо: {url}  (остановить — Ctrl+C)", flush=True)
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
