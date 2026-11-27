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

from .sheet import build_sheet, load_report, read_source
from .runner import (ALLOWED_EXT, FILES, MAX_UPLOAD, FixtureRunner, Job, JobStore, PipelineRunner, Worker,
                     check_provider, load_dotenv, provider_status)

ASSETS = Path(__file__).with_name("assets")
# №39: tokens.css — дизайн-система, шрифты листа (OFL); agent.* — BCC AI (№40), отдаются, когда файлы появятся
ASSET_NAMES = ("app.css", "app.js", "tokens.css", "agent.css", "agent.js",
               "pt-serif-400.woff2", "pt-serif-700.woff2", "jetbrains-mono-400.woff2", "fonts-OFL.txt")
ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2",
               ".txt": "text/plain; charset=utf-8"}
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

# ── №39: знак продукта (свой, не логотип банка) — для favicon; в шапке живёт дрон BCC AI (№40) ──
_MARK = ('<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true" focusable="false">'
         '<rect width="32" height="32" rx="7" fill="#0B1220"/>'
         '<path d="M9 7.5h10.5l4 4V24a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V8.5a1 1 0 0 1 1-1z" fill="#fff"/>'
         '<path d="M11 13h7M11 16.5h9M11 20h5" stroke="#B9C3CF" stroke-width="1.4" stroke-linecap="round"/>'
         '<path d="M11 16.5h9" stroke="#DCA262" stroke-width="2.6" stroke-linecap="round" opacity=".75"/>'
         '<circle cx="23.5" cy="22.5" r="4.6" fill="#00B975"/>'
         '<path d="M21.4 22.6l1.5 1.5 2.8-3" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round" '
         'stroke-linejoin="round"/></svg>')
_FAVICON = "data:image/svg+xml," + quote(_MARK.format(s=32).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1),
                                          safe="")
# чернила печати: неровная кромка и непрокрас (feTurbulence), без картинок
_INK = ('<svg class="b-defs" width="0" height="0" aria-hidden="true" focusable="false" '
        'style="position:absolute;width:0;height:0;overflow:hidden"><filter id="b-ink" x="-6%" y="-12%" '
        'width="112%" height="124%"><feTurbulence type="fractalNoise" baseFrequency=".95" numOctaves="2" seed="11" '
        'result="grain"/><feColorMatrix in="grain" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -3.2 2.45" '
        'result="holes"/><feComposite in="SourceGraphic" in2="holes" operator="in" result="inked"/>'
        '<feTurbulence type="fractalNoise" baseFrequency=".035" numOctaves="2" seed="4" result="warp"/>'
        '<feDisplacementMap in="inked" in2="warp" scale="2.6" xChannelSelector="R" yChannelSelector="G"/></filter></svg>')

# короткие имена провайдеров
_SHORT = {"auto": "Авто", "claude_cli": "Claude Code", "gemini": "Gemini", "anthropic": "Claude API",
          "openai": "Свой сервер", "mock": "Демо без модели", "offline": "Только правила"}
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
    doc = f'<span class="b-bar-doc" title="{e(sub)}">{e(sub)}</span>' if sub else ""
    st = f'<span class="b-status {mod}" id="pstatus" title="{e(status)}">{e(status)}</span>' if status else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0B1220">
<title>{e(title)}</title>
<link rel="icon" href="{_FAVICON}">
<link rel="preload" href="/assets/pt-serif-400.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/tokens.css">
<link rel="stylesheet" href="/assets/app.css">
{agent_css}
</head><body class="b-desk">
{_INK}
<header class="b-bar">
  <a class="b-bar-brand" href="/" aria-label="BCC Review — на стол"><div class="b-bar-agent" data-bcc-agent data-size="24" data-mood="idle"></div>BCC Review</a>{doc}
  <div class="b-bar-end">{st}</div>
</header>
{body}
<script src="/assets/app.js"></script>
{agent_js}
</body></html>"""


def _gallery(app: App) -> str:
    try:  # №43 — готовые отчёты стопкой; до его вливания блока нет
        from .gallery import gallery_block
    except ImportError:
        return ""
    try:
        return gallery_block(app) or ""
    except Exception:  # noqa: BLE001 — стол открывается, даже если стопка сломалась
        return ""


def _job_files(app: App, job: Job) -> list[tuple[str, str]]:
    out = app.store.dir(job.id) / "out"
    return [(lbl, f"/jobs/{job.id}/files/{n}") for k, n, lbl, _ in FILES
            if k not in ("json",) and (out / n).is_file()]


def _top_sheet(app: App) -> dict[str, Any] | None:
    """Раскрытый лист на столе: своя последняя готовая проверка, иначе первый готовый отчёт №43."""
    for j in app.store.recent():
        if j.state != "done":
            continue
        rep = load_report(app.store.dir(j.id) / "out" / "report.json")
        if rep:
            return {"report": rep, "raw": read_source(j.input_path), "name": j.file_name, "href": f"/jobs/{j.id}",
                    "files": _job_files(app, j), "id": j.id}
    try:
        from .gallery import load_examples
        recs = load_examples().get("reports") or []
    except Exception:  # noqa: BLE001 — №43 ещё не влит или examples.json не читается
        recs = []
    for r in recs:
        rep = load_report(r.get("json")) if r.get("ok") else None
        if rep:
            src = r.get("source")
            return {"report": rep, "raw": read_source(src), "name": Path(str(src)).name if src else r.get("title", ""),
                    "href": f"/examples/{r.get('id')}", "files": [("Отчёт и выгрузки", f"/examples/{r.get('id')}")],
                    "id": ""}
    return None


def _leaf(j: Job) -> str:
    s = j.summary or {}
    if j.state == "done":
        v = (j.summary or {}).get("development", "")
        cls, word = {"no": ("crit", "Нельзя"), "conditional": ("cond", "Условно"), "yes": ("ok", "Можно")}.get(v, ("cond", "—"))
        stamp = f'<span class="b-stamp mini {cls}">{word}</span>'
        meta = f'{s.get("critical", 0)} блок. · {s.get("major", 0)} сущ.'
    else:
        stamp = ""
        meta = {"queued": "в очереди", "running": "идёт проверка", "failed": "ошибка прогона"}.get(j.state, j.state)
    when = time.strftime("%d.%m %H:%M", time.localtime(j.created))
    return (f'<a class="b-leaf" href="/jobs/{e(j.id)}"><span class="b-leaf-t">{e(Path(j.file_name).stem)}</span>'
            f'<span class="b-leaf-m">{e(when)} · {e(meta)}</span>{stamp}</a>')


def index_page(app: App, *, error: str = "", provider: str = "", model: str = "") -> str:
    provs = provider_status()
    ids = [p["id"] for p in provs]
    sel = provider if provider in ids else (app.default_provider if app.default_provider in ids else "auto")
    opts = []
    for p in provs:
        ok = bool(p["ok"])
        what = e(p["note"]) if ok else _HINT.get(p["id"], e(p["note"]))
        if p["id"] == "auto":
            res = next((q for q in provs if q["id"] == p.get("resolved")), None)
            what = e(f'Сейчас — «{res["label"]}»: {res["note"]}') if res else what
        opts.append(f'<label class="pv{"" if ok else " off"}"><input type="radio" name="provider" value="{e(p["id"])}"'
                    f'{" checked" if p["id"] == sel else ""} data-ok="{1 if ok else 0}" '
                    f'data-models="{e(",".join(p["models"]))}" data-short="{e(_SHORT.get(p["id"], p["label"]))}" '
                    f'data-note="{e(what)}"><i aria-hidden="true"></i><span>{e(p["label"])}</span></label>')
    top = _top_sheet(app)
    sheet = build_sheet(top["report"], top["raw"], file_name=top["name"]) if top else None
    if sheet is None and app.sample:  # проверок ещё нет: на столе чистый лист примера
        sheet = build_sheet(None, read_source(app.sample), file_name=f"{app.sample.name} · пример, ещё не проверен")
    leaves = [_leaf(j) for j in app.store.recent()[:6] if not top or j.id != top.get("id")][:4]
    stack = _gallery(app) + (f'<div class="b-stack">{"".join(leaves)}</div>' if leaves else "")
    sample = (f'<button type="submit" class="pv-sample" name="sample" value="1" formnovalidate>'
              f'Проверить пример: {e(app.sample.name)}</button>') if app.sample else ""
    href = top["href"] if top else ""
    q = sheet.questions if sheet and top else 0
    acts = ""
    if top:
        files = "".join(f'<a href="{e(u)}">{e(lbl)}</a>' for lbl, u in top["files"])
        acts = (f'<span class="sep" aria-hidden="true"></span>'
                f'<a href="{e(href)}#questions"><span>Вопросы<span class="long"> владельцу</span></span><b class="n">{q}</b></a>'
                f'<a href="{e(href)}#revised"><span class="long">Исправленная редакция</span><span class="short">Редакция</span></a>'
                f'<details class="b-menu"><summary>Выгрузить</summary><div class="b-menu-pop">{files}</div></details>')
    cur = next((p for p in provs if p["id"] == sel), provs[0])
    err = f'<p class="dock-msg bad" id="dmsg" role="alert">{e(error)}</p>' if error else \
        '<p class="dock-msg" id="dmsg" role="status" hidden></p>'
    body = f"""<div class="desk" id="desk">
<aside class="desk-stack" aria-label="Стопка листов">{stack}</aside>
<aside class="desk-map" aria-label="Карта листа">{f'<div class="b-map" id="map">{sheet.map}<span class="b-map-view" id="mapview"></span></div>' if sheet else ''}</aside>
<main class="desk-sheet">{sheet.html if sheet else ''}</main>
<div class="desk-notes" aria-hidden="true"></div>
</div>
<form class="b-dock" id="form" method="post" action="/api/jobs" enctype="multipart/form-data">
  {err}
  <label class="primary" id="pick"><input class="vh" type="file" name="file" id="file" accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm" required>Свой документ</label>
  {acts}
  <span class="sep" aria-hidden="true"></span>
  <details class="b-menu" id="pmenu"><summary id="pcur">{e(_SHORT.get(cur["id"], cur["label"]))}</summary>
    <div class="b-menu-pop pv-pop" role="radiogroup" aria-label="Модель">
      <div class="hint">Модель для своего документа</div>
      {"".join(opts)}
      <p class="pv-note" id="pnote"></p>
      <input class="b-field pv-model" name="model" id="model" list="models" value="{e(model)}" placeholder="вариант модели — по умолчанию" autocomplete="off" aria-label="Вариант модели"><datalist id="models"></datalist>
      {sample}
    </div>
  </details>
</form>
<div class="veil" id="veil" hidden><div class="veil-sheet"><b>Отпустите файл</b>лист ляжет на стол, и BCC AI начнёт проверку<small>PDF, Word, Markdown, TXT, HTML · до 20 МБ</small></div></div>"""
    return _layout("BCC Review · Проверка требований", body, sub=(top or {}).get("name") or "")


def job_page(job: Job) -> str:
    links = "".join(f'<a class="dl" data-key="{k}" href="/jobs/{e(job.id)}/files/{n}" hidden>{lbl}</a>'
                    for k, n, lbl, _ in FILES)
    body = f"""<main class="jobwrap" data-job="{e(job.id)}">
<section class="card prog" id="prog">
  <div class="phead">
    <div class="pinfo"><div class="pfile">{e(job.file_name)}</div>
    <div class="pmeta">{e(job.provider)}{(" · " + e(job.model)) if job.model else ""} · <span id="elapsed">0 с</span> · <span id="pstate">в очереди</span><span id="vsum"></span></div></div>
    <div class="dls"><span class="dll" id="dll" hidden>Скачать:</span>{links}
    <a class="dl" id="newtab" href="/jobs/{e(job.id)}/files/report.html?inline=1" target="_blank" rel="noopener" hidden>Открыть отдельно ↗</a>
    <form class="answers" id="answers" hidden title="Отметьте варианты во вкладке «Вопросы» отчёта, нажмите «Скачать ответы» и загрузите файл: агент перепроверит замечания и покажет вердикт «до и после» и исправленное ТЗ.">
      <label class="dl ans">Загрузить ответы ↻<input type="file" name="answers" accept=".md,.txt,.json" hidden></label></form>
    <a class="btn ghost" href="/">Новая проверка</a></div>
  </div>
  {f'<p class="parent">Повторная проверка с ответами владельца к <a href="/jobs/{e(job.parent)}">исходной проверке</a>.</p>' if job.parent else ''}
  <ol class="stages" id="stages"></ol>

  <div class="notice" id="notice" role="status" hidden></div>
  <div class="error" id="err" hidden></div>
  <details class="log"><summary>Журнал запуска</summary><pre id="log"></pre></details>
</section>
<section class="result" id="result" hidden><iframe id="frame" title="Отчёт ревью"></iframe></section>
</main>"""
    return _layout(f"Проверка: {job.file_name}", body, sub=job.file_name)


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
                ctype = ASSET_TYPES.get(p.suffix, "application/octet-stream")
                return self._send(200, p.read_bytes(), ctype)
            return self._html(404, _layout("Не найдено", '<main class="wrap"><p>Файл не найден.</p></main>'))
        m = JOB_PATH.match(path)
        if m:
            job = self.app.store.get(m.group("id"))
            if not job:
                return self._not_found()
            rest = m.group("rest") or ""
            if m.group(1):  # /api/jobs/<id>
                return self._json(200, job.public())
            if not rest:
                return self._html(200, job_page(job))
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
