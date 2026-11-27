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

# ── №39: знак продукта (свой, не логотип банка): лист ТЗ с галочкой и золотой точкой «сверено» ──
_MARK = ('<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true" focusable="false">'
         '<rect width="32" height="32" rx="9" fill="#008556"/>'
         '<path d="M10 9.5h8.5l3.5 3.5v9.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 9 22.5v-11.5A1.5 1.5 0 0 1 10.5 9.5z" '
         'fill="#fff" opacity=".96"/>'
         '<path d="M12.6 17.4l2.4 2.4 4.6-4.9" stroke="#008556" stroke-width="2.2" fill="none" '
         'stroke-linecap="round" stroke-linejoin="round"/>'
         '<circle cx="23.5" cy="9" r="3.6" fill="#DCA262" stroke="#008556" stroke-width="1.6"/></svg>')
_FAVICON = "data:image/svg+xml," + quote(_MARK.format(s=32).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1),
                                          safe="")

# короткие имена провайдеров для сегмента и строки состояния
_SHORT = {"auto": "Авто", "claude_cli": "Claude Code", "gemini": "Gemini", "anthropic": "Claude API",
          "openai": "Свой сервер", "mock": "Демо", "offline": "Только правила"}
_NO_MODEL = ("mock", "offline")
_HINT = {"gemini": 'Нет ключа. Он бесплатный: <a href="https://aistudio.google.com/apikey" target="_blank" '
                   'rel="noopener">получить за минуту</a>, затем GEMINI_API_KEY=… в файле .env.',
         "anthropic": "Нет ключа: добавьте ANTHROPIC_API_KEY=… в файл .env.",
         "openai": "Нет адреса: добавьте OPENAI_BASE_URL=http://localhost:11434/v1 (Ollama) в файл .env.",
         "claude_cli": "Не найден: установите Claude Code и войдите в аккаунт."}


def _provider_line(provs: list[dict[str, Any]]) -> tuple[str, str]:
    """Строка состояния в шапке: (текст, модификатор класса .b-status)."""
    first = provs[0].get("resolved", "offline") if provs else "offline"
    if first in _NO_MODEL:
        return "Без ключа: только правила и готовые отчёты", "stale"
    note = {"claude_cli": "по подписке", "openai": "свой сервер"}.get(first, "ключ найден")
    return f"{_SHORT.get(first, first)} · {note}", ""


def _layout(title: str, body: str, *, sub: str = "") -> str:
    try:
        status, mod = _provider_line(provider_status())
    except Exception:  # noqa: BLE001 — шапка не должна падать из-за проверки провайдеров
        status, mod = "", ""
    agent_css = '<link rel="stylesheet" href="/assets/agent.css">' if (ASSETS / "agent.css").is_file() else ""
    agent_js = '<script src="/assets/agent.js" defer></script>' if (ASSETS / "agent.js").is_file() else ""
    crumb = f'<span class="tb-sub" title="{e(sub)}">{e(sub)}</span>' if sub else ""
    st = f'<span class="b-status {mod}" id="pstatus" title="{e(status)}">{e(status)}</span>' if status else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#F3F6F5">
<title>{e(title)}</title>
<link rel="icon" href="{_FAVICON}">
<link rel="stylesheet" href="/assets/tokens.css">
<link rel="stylesheet" href="/assets/app.css">
{agent_css}
</head><body class="b-root">
<header class="tb-wrap"><div class="tb b-glass">
  <a class="tb-brand" href="/" aria-label="BCC Review — на главную">{_MARK.format(s=30)}<span class="tb-name">BCC Review</span></a>{crumb}
  <div class="tb-end">{st}<div class="tb-agent" data-bcc-agent data-size="40" data-mood="idle"></div></div>
</div></header>
{body}
<script src="/assets/app.js"></script>
{agent_js}
</body></html>"""


def _gallery(app: App) -> str:
    try:  # №43 — готовые отчёты; до его вливания блока нет
        from .gallery import gallery_block
    except ImportError:
        return ""
    try:
        return gallery_block(app) or ""
    except Exception:  # noqa: BLE001 — главная открывается, даже если галерея сломалась
        return ""


def index_page(app: App, *, error: str = "", provider: str = "", model: str = "") -> str:
    provs = provider_status()
    ids = [p["id"] for p in provs]
    sel = provider if provider in ids else (app.default_provider if app.default_provider in ids else "auto")
    caps = []
    for p in provs:
        ok = bool(p["ok"])
        what = e(p["note"]) if ok else _HINT.get(p["id"], e(p["note"]))
        if p["id"] == "auto":
            res = next((q for q in provs if q["id"] == p.get("resolved")), None)
            what = e(f'Сейчас — «{res["label"]}»: {res["note"]}') if res else what
        caps.append(f'<label class="pv{"" if ok else " off"}" title="{e(p["label"])}">'
                    f'<input type="radio" name="provider" value="{e(p["id"])}"{" checked" if p["id"] == sel else ""} '
                    f'data-ok="{1 if ok else 0}" data-models="{e(",".join(p["models"]))}" data-label="{e(p["label"])}" '
                    f'data-note="{e(what)}"><i aria-hidden="true"></i>{e(_SHORT.get(p["id"], p["label"]))}</label>')
    sample = ""
    if app.sample:
        sample = (f'<button type="submit" class="b-button quiet" name="sample" value="1" formnovalidate '
                  f'title="{e(app.sample.name)}">Проверить пример</button>')
    rows = []
    for j in app.store.recent()[:5]:
        s = j.summary or {}
        if j.state == "done":
            v = VERDICT.get(s.get("development", ""), ("—", "none"))
            cls = {"no": "crit", "cond": "major", "yes": "ok"}.get(v[1], "plain")
            badge = f'<span class="b-badge {cls}">Разработка: {e(v[0].lower())}</span>'
        else:
            label = {"queued": "в очереди", "running": "идёт анализ", "failed": "ошибка"}.get(j.state, j.state)
            badge = f'<span class="b-badge {"crit" if j.state == "failed" else "plain"}">{e(label)}</span>'
        when = time.strftime("%d.%m %H:%M", time.localtime(j.created))
        rows.append(f'<li><a class="b-row" href="/jobs/{e(j.id)}"><span class="rc-name">{e(j.file_name)}</span>'
                    f'<span class="b-note rc-meta">{e(when)} · {e(_SHORT.get(j.provider, j.provider))}</span>{badge}</a></li>')
    recent = (f'<section class="home-sec b-rise"><h2 class="b-h2">Последние проверки</h2>'
              f'<ul class="b-surface b-list">{"".join(rows)}</ul></section>') if rows else ""
    err = (f'<p class="home-err" role="alert">{e(error)}</p>') if error else ""
    body = f"""<main class="b-wrap home">
<section class="home-head b-rise">
  <h1 class="b-title">Проверка ТЗ до разработки</h1>
  <p class="b-lead">Агент найдёт противоречия и пробелы — каждое замечание с цитатой и номером строки.</p>
</section>
<form class="home-form b-surface b-rise" id="form" method="post" action="/api/jobs" enctype="multipart/form-data">
  <label class="drop" id="drop">
    <input type="file" name="file" id="file" accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm" required>
    <span class="drop-ic" aria-hidden="true"><svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 16V5m0 0l-4.5 4.5M12 5l4.5 4.5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 15v2.5A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg></span>
    <span class="drop-t">Перетащите файл или <u>выберите</u></span>
    <span class="b-note">PDF, Word, Markdown, TXT, HTML · до 20 МБ</span>
    <span class="drop-f" id="fname" aria-live="polite"></span>
  </label>
  <div class="home-side">
    <fieldset class="pv-set"><legend class="b-label">Модель</legend>
      <div class="b-segment pv-seg" id="provider" role="radiogroup">{"".join(caps)}</div>
    </fieldset>
    <p class="pv-note" id="pnote" aria-live="polite"></p>
    <details class="pv-more" id="pmore"><summary>Вариант модели</summary>
      <input class="b-field" name="model" id="model" list="models" value="{e(model)}" placeholder="по умолчанию" autocomplete="off" aria-label="Вариант модели"><datalist id="models"></datalist>
    </details>
    {err}
    <div class="home-act"><button type="submit" class="b-button primary" id="go">Проверить</button>{sample}</div>
  </div>
</form>
{_gallery(app)}
{recent}
<details class="home-how b-rise"><summary>Как это работает</summary>
  <ol>
    <li><b>Документ.</b> Читаем PDF, Word, Markdown; нумеруем строки и нарезаем требования.</li>
    <li><b>Четыре ревьюера.</b> Аналитик, тестировщик, архитектор и риски смотрят параллельно.</li>
    <li><b>Судья.</b> Убирает дубли и ложные срабатывания, ставит критичность и выносит вердикт.</li>
    <li><b>Сверка.</b> Каждая цитата и номер строки проверяются программой по исходному тексту.</li>
  </ol>
</details>
</main>"""
    return _layout("Проверка требований · BCC Review", body)


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
    from bcc_review.v2.render import jsonout as J
    from bcc_review.v2.render import markdown as M
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    run = report.get("run") or {}
    verdict = report.get("verdict") or {}
    summary = report.get("summary") or J.compute_summary(report)
    fs = summary.get("findings") or {}
    ok, total = H._quotes_verified(report)
    qv, qt = summary.get("quotes_verified"), summary.get("quotes_total")
    if isinstance(qv, int) and isinstance(qt, int) and not isinstance(qv, bool) and qt >= qv >= 0:
        ok, total = qv, qt
    status = run.get("status", "")
    # блокеры — те же и в том же порядке, что на первом экране Markdown-отчёта и в итоге терминала
    ctx = M._Ctx(report)
    bl = M._blockers(ctx)
    order = M._first_screen_fix(ctx, bl)
    blockers = []
    for f in [f for f in order if f in bl] + [f for f in bl if f not in order]:
        ev0 = (f.get("evidence") or [{}])[0]
        sec = str(ev0.get("section") or "").split(" › ")[-1]
        blockers.append({"id": f.get("id", ""), "title": f.get("title", ""), "blocks": f.get("blocks", ""),
                         "where": H._lines_label(ev0) + (f" · {sec}" if sec else "")})
    major = fs.get("major", sum(1 for f in J.open_findings(report) if H._sev(f) == "major"))
    present = {"clarify": bool(report.get("clarification")),
               "rewrites": bool(report.get("rewrites"))}
    return {
        "development": verdict.get("development", "") if status != "failed" else "",
        "testing": verdict.get("testing", "") if status != "failed" else "",
        "critical": len(blockers), "major": major, "findings": len(findings),
        "questions": len(report.get("questions") or []), "quotes_ok": ok, "quotes_total": total,
        "blockers": blockers, "status": status,
        "model": ", ".join(run.get("models_used") or []) or run.get("model_requested") or "",
        "duration": run.get("duration_s"), "calls": (run.get("calls") or {}).get("total"),
        "counts": {"tests": len(report.get("test_cases") or []), "checklist": len(report.get("checklist") or []),
                   "checks": len(report.get("acceptance_checks") or []) + len(report.get("pair_checks") or []),
                   "segment": len(report.get("requirements") or []), "rejected": len(report.get("rejected") or [])},
        "has": present,
    }


_SHEET_CACHE: dict[str, list[dict]] = {}


def _sheet_lines(job: Job, limit: int = 400) -> list[dict]:
    """Строки документа для листа на столе (нумерация — как в отчёте); не прочитался — пустой лист."""
    if job.id in _SHEET_CACHE:
        return _SHEET_CACHE[job.id]
    lines: list[dict] = []
    try:
        from bcc_review.v2.render import html as H
        lines = [ln for ln in (H.load_view(job.input_path) or {}).get("lines") or [] if isinstance(ln, dict)][:limit]
    except Exception:  # noqa: BLE001 — лист без текста всё равно покажем, сканер идёт по пустым строкам
        lines = []
    _SHEET_CACHE[job.id] = lines
    return lines


def _sheet_html(job: Job) -> str:
    rows = []
    for ln in _sheet_lines(job):
        text = str(ln.get("text") or "")
        cls = "ln" + (" h" if ln.get("heading") or ln.get("kind") == "heading" else "") + ("" if text.strip() else " blank")
        rows.append(f'<div class="{cls}"><span class="no">{e(ln.get("n", ""))}</span><span class="tx">{e(text) or "&#8203;"}</span></div>')
    if not rows:
        rows = ['<div class="ln skel"><span class="no"></span><span class="tx"></span></div>'] * 24
    return "".join(rows)


def _dock_html(job: Job, f: dict) -> str:
    """Единственное стекло на экране: правка, вопросы, исправленная редакция, ещё, выгрузить, свой документ."""
    jid = e(job.id)
    q = f["questions"]
    files = "".join(f'<a role="menuitem" href="/jobs/{jid}/files/{n}" download><span>{e(lbl)}</span>'
                    f'<small>{e(FILE_NOTE.get(k, ""))}</small></a>' for k, n, lbl, _ in FILES if k in job.files)
    files += ('<button type="button" role="menuitem" data-act="answers-md"><span>Ответы на вопросы</span>'
              '<small>файл для --answers</small></button>' if q else "")
    files += (f'<a role="menuitem" href="/jobs/{jid}/files/report.html?inline=1" target="_blank" rel="noopener">'
              f'<span>Открыть отчёт отдельно ↗</span><small>тот же лист, без сервера</small></a>' if "html" in job.files else "")
    extra = "".join(f'<button type="button" role="menuitem" data-rtab="{k}"><span>{lbl}</span>'
                    f'<small>{f["counts"].get(k, "")}</small></button>'
                    for k, lbl in EXTRA_TABS if k != "clarify" or f["has"]["clarify"])
    revised = "rewrites" if f["has"]["rewrites"] else ""
    return f"""<nav class="jb-dock" id="dock" aria-label="Отчёт">
  <a class="jb-d" href="/" title="Положить на стол свой документ">Свой документ</a><span class="jb-sep" aria-hidden="true"></span>
  <button type="button" class="jb-d" data-view="findings" aria-pressed="true">Правка <span class="jb-n">{f["findings"]}</span></button>
  <button type="button" class="jb-d" data-view="questions" aria-pressed="false"{"" if q else " disabled"}>Вопросы владельцу <span class="jb-n">{q}</span></button>
  <button type="button" class="jb-d" data-view="revised" data-rt="{revised}" aria-pressed="false">Исправленная редакция</button>
  <button type="button" class="jb-d" data-menu="more" aria-haspopup="menu" aria-expanded="false">Ещё ▾</button>
  <span class="jb-sep" aria-hidden="true"></span>
  <button type="button" class="jb-d" data-menu="files" aria-haspopup="menu" aria-expanded="false">Выгрузить ▾</button>
  <button type="button" class="jb-d jb-go" id="recheck" hidden{"" if not job.answers_path else " disabled"}>Проверить заново</button>
</nav>
<div class="jb-menu" id="menu-more" role="menu" hidden>{extra}</div>
<div class="jb-menu" id="menu-files" role="menu" hidden>{files}</div>
<p class="jb-toast" id="toast" role="status" hidden></p>"""


def result_html(job: Job, f: dict, *, agent: bool = True) -> str:
    """Готовая правка: лист-отчёт на весь стол (HTML-отчёт в режиме встраивания) и стеклянная панель внизу.

    Вердикт — печать на листе, блокеры — красные пометки и заметки на полях; здесь — только данные для BCC AI."""
    jid = e(job.id)
    first = f["blockers"][0]["id"] if f["blockers"] else ""
    say = (f'Готово. {f["critical"]} {_plural(f["critical"], "блокер", "блокера", "блокеров")} — начните с {first}.'
           if first else "Готово. Блокеров нет.")
    mood = "alert" if f["critical"] else "verified"
    parent = (f'<p class="jb-parent jb-parent-done">Повторная проверка с ответами владельца — '
              f'<a href="/jobs/{e(job.parent)}">исходная правка</a>.</p>' if job.parent else "")
    # панель — раньше листа: Tab попадает сначала в панель, потом в лист
    return (_dock_html(job, f) + parent +
            f'\n<iframe class="jb-report" id="rframe" title="Правка документа" data-src="/jobs/{jid}/files/report.html?inline=1" '
            f'data-mood="{mood}" data-say="{e(say)}"></iframe>')


def job_page(job: Job, app: App | None = None) -> str:
    facts = report_facts(app, job)
    css = (ASSETS / "job.css").read_text(encoding="utf-8")
    parent = (f'<p class="jb-parent">Повторная проверка с ответами владельца — <a href="/jobs/{e(job.parent)}">'
              f'исходная правка</a>.</p>' if job.parent else "")
    if facts:
        inner = result_html(job, facts)
    else:
        inner = f"""{parent}<section class="jb-scan" id="scan" aria-live="polite" aria-label="Проверка документа">
  <div class="jb-sheet" id="sheet"><div class="jb-beam" id="beam" aria-hidden="true"></div>{_sheet_html(job)}</div>
  <div class="jb-pilot" id="pilot">
    <div class="jb-agent" id="agent-home"><div data-bcc-agent data-size="80" data-mood="scanning" id="agent"></div></div>
    <div class="jb-say"><b id="stage">{"жду очереди" if job.state == "queued" else "читаю"}</b>
    <span id="pline"><span id="elapsed">0 с</span><span id="calls"></span> · {e(job.provider)}{(" · " + e(job.model)) if job.model else ""}</span></div>
  </div>
  <div class="jb-err" id="err" hidden><p class="jb-errline" id="errtext" role="alert"></p><p class="jb-todo" id="todo"></p>
  <a class="jb-btn" href="/">Новая проверка</a></div>
  <ol class="jb-stages" id="stages" hidden></ol>
  <details class="jb-log"><summary>Журнал запуска</summary><pre id="log"></pre></details>
</section>
<section class="jb-result" id="result" hidden></section>"""
    body = f"""<style>{css}</style>
<main class="jb{" done" if facts else ""}" data-job="{e(job.id)}" data-state="{e(job.state)}">
{inner}
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
