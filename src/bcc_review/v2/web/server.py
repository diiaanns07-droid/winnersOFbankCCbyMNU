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
import threading
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

from .sheet import VERDICT as VERDICT_WORD, build_sheet, load_report, plural, read_source
from .runner import (ALLOWED_EXT, FILES, MAX_UPLOAD, FixtureRunner, Job, JobStore, PipelineRunner, Worker,
                     check_provider, load_dotenv, provider_status)
from . import onboarding as _onboarding  # №40: знакомство, /api/key, файлы BCC AI

ASSETS = Path(__file__).with_name("assets")
# №39: tokens.css — дизайн-система, шрифты Inter и JetBrains Mono (OFL); agent.* — BCC AI (№40), отдаются, когда файлы появятся
ASSET_NAMES = ("app.css", "app.js", "tokens.css", "agent.css", "agent.js",
               "inter-400.woff2", "inter-600.woff2", "inter-700.woff2", "jetbrains-mono-400.woff2", "fonts-OFL.txt")
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

# ── №39: знак продукта (свой, не логотип банка): лист с отметкой и зелёной галочкой «сверено» ──
_MARK = ('<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true" focusable="false">'
         '<rect width="32" height="32" rx="9" fill="#008556"/>'
         '<path d="M9.5 7h10l4 4v13.5a1.5 1.5 0 0 1-1.5 1.5H9.5A1.5 1.5 0 0 1 8 24.5v-16A1.5 1.5 0 0 1 9.5 7z" fill="#fff"/>'
         '<path d="M11.5 13h7M11.5 20h5" stroke="#C9D3DC" stroke-width="1.5" stroke-linecap="round"/>'
         '<path d="M11.5 16.5h9" stroke="#FBE1BA" stroke-width="3" stroke-linecap="round"/>'
         '<circle cx="23.2" cy="23.2" r="4.8" fill="#00B975" stroke="#fff" stroke-width="1.4"/>'
         '<path d="M21.1 23.3l1.5 1.5 2.7-3" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round" '
         'stroke-linejoin="round"/></svg>')
_FAVICON = "data:image/svg+xml," + quote(_MARK.format(s=32).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1),
                                          safe="")

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
<meta name="theme-color" content="#F3F6F5">
<title>{e(title)}</title>
<link rel="icon" href="{_FAVICON}">
<link rel="preload" href="/assets/inter-400.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/tokens.css">
<link rel="stylesheet" href="/assets/app.css">
{agent_css}
</head><body class="b-desk">
<header class="b-bar">
  <a class="b-bar-brand" href="/" aria-label="BCC Review — на главную"><div class="b-bar-agent" data-bcc-agent data-size="48" data-mood="idle"></div><span class="b-bar-mark">{_MARK.format(s=34)}</span><span class="b-bar-name">BCC Review</span></a>{doc}
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


# №54 (правка 49): AIshka 96 стоит на раскрытом листе главной, у строки вердикта — как над листом проверки
_DESK_AISHKA = '<div class="desk-aishka" data-bcc-agent data-size="96" data-mood="idle" aria-hidden="true"></div>'


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


def _leaf(j: Job, *, on: bool = False) -> str:
    s = j.summary or {}
    when = time.strftime("%d.%m %H:%M", time.localtime(j.created))
    if j.state == "done":
        cls, word = VERDICT_WORD.get(s.get("development", ""), ("cond", "нет вердикта"))
        crit = int(s.get("critical") or 0)
        line = (f'<div class="b-verdict"><span class="main">Разработка: <b class="{cls}">{e(word)}</b></span>'
                f'<span>{crit} {plural(crit, "блокер", "блокера", "блокеров")}</span></div>' if crit else
                f'<div class="b-verdict"><span class="main">Разработка: <b class="{cls}">{e(word)}</b></span>'
                f'<span>блокеров нет</span></div>')
    else:
        label = {"queued": "в очереди", "running": "идёт проверка", "failed": "ошибка прогона"}.get(j.state, j.state)
        line = f'<div class="b-verdict"><span>{e(label)}</span></div>'
    cur = ' aria-current="page"' if on else ""
    return (f'<a class="b-leaf{" on" if on else ""}" href="/jobs/{e(j.id)}"{cur}>'
            f'<span class="b-leaf-t">{e(Path(j.file_name).stem)}</span>{line}'
            f'<span class="b-leaf-m">{e(when)} · {e(_SHORT.get(j.provider, j.provider))}</span></a>')


def _margin_head(report: dict[str, Any]) -> str:
    """Шапка полей: сколько замечаний и вопросов, и легенда отметок — те же знаки, что у заметок."""
    fs = report.get("findings") or []
    n = {k: sum(1 for f in fs if f.get("severity") == k) for k in ("critical", "major", "minor")}
    q = len(report.get("questions") or [])
    total = len(fs)
    legend = "".join(
        f'<span class="lg {c}">{n[k]} {plural(n[k], *w)}</span>' for k, c, w in (
            ("critical", "crit", ("блокер", "блокера", "блокеров")),
            ("major", "major", ("существенное", "существенных", "существенных")),
            ("minor", "minor", ("незначительное", "незначительных", "незначительных"))) if n[k])
    ask = f' · {q} {plural(q, "вопрос", "вопроса", "вопросов")}' if q else ""
    return (f'<div class="b-margin-head"><b>{total} {plural(total, "замечание", "замечания", "замечаний")}{ask}</b>'
            f'<div class="b-legend">{legend}</div></div>')


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
        sheet = build_sheet(None, read_source(app.sample), file_name=app.sample.name)
    leaves = [_leaf(j, on=bool(top) and j.id == top.get("id")) for j in app.store.recent()[:5]]
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
    elif app.sample:  # проверок ещё нет: на столе чистый лист примера — его и проверить
        acts = (f'<span class="sep" aria-hidden="true"></span><button type="submit" name="sample" value="1" '
                f'formnovalidate>Проверить этот лист</button>')
    cur = next((p for p in provs if p["id"] == sel), provs[0])
    err = f'<p class="dock-msg bad" id="dmsg" role="alert">{e(error)}</p>' if error else \
        '<p class="dock-msg" id="dmsg" role="status" hidden></p>'
    body = f"""<form class="b-dock" id="form" method="post" action="/api/jobs" enctype="multipart/form-data">
  {err}
  <label class="primary" id="pick"><input class="vh" type="file" name="file" id="file" accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm" required>Свой документ</label>
  <noscript><button type="submit">Проверить</button></noscript>
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
<div class="desk" id="desk">
<aside class="desk-stack" aria-label="Готовые листы">{stack}</aside>
<aside class="desk-map" aria-label="Карта листа">{f'<div class="b-map" id="map">{sheet.map}<span class="b-map-view" id="mapview"></span></div>' if sheet else ''}</aside>
<main class="desk-sheet">{sheet.html if sheet else ''}{_DESK_AISHKA if sheet else ''}</main>
<div class="desk-notes{' b-margin' if sheet and sheet.notes else ''}">{_margin_head(top["report"]) if top and sheet and sheet.notes else ''}</div>
</div>
<div class="veil" id="veil" hidden><div class="veil-sheet"><b>Отпустите файл</b>BCC AI сразу начнёт проверку<small>PDF, Word, Markdown, TXT, HTML · до 20 МБ</small></div></div>"""
    sub = (top or {}).get("name") or (f"Пример: {app.sample.name}" if app.sample else "")
    return _layout("BCC Review · Проверка требований", body, sub=sub)


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
    return f"""<nav class="b-dock jb-dock" id="dock" aria-label="Отчёт">
  <a class="jb-d" href="/" title="Положить на стол свой документ">Свой документ</a><span class="jb-sep" aria-hidden="true"></span>
  <button type="button" class="jb-d" data-view="findings" aria-pressed="true">Правка <span class="jb-n">{f["findings"]}</span></button>
  <button type="button" class="jb-d" data-view="questions" aria-pressed="false"{"" if q else " disabled"}>Вопросы владельцу <span class="jb-n">{q}</span></button>
  <button type="button" class="jb-d" data-view="revised" data-rt="{revised}" aria-pressed="false">Исправленная редакция</button>
  <button type="button" class="jb-d" data-menu="more" aria-haspopup="menu" aria-expanded="false">Ещё ▾</button>
  <span class="jb-sep" aria-hidden="true"></span>
  <button type="button" class="jb-d" data-menu="files" aria-haspopup="menu" aria-expanded="false">Выгрузить ▾</button>
  <button type="button" class="jb-d jb-go primary" id="recheck" hidden{"" if not job.answers_path else " disabled"}>Проверить заново</button>
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
    mood = "speak" if f["critical"] else "happy"  # AIshka (№40): говорит о блокерах или радуется, что их нет
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
    <div class="jb-agent" id="agent-home"><div data-bcc-agent data-size="96" data-mood="work" id="agent"></div></div>
    <div class="jb-say"><b id="stage">{"жду очереди" if job.state == "queued" else "читаю"}</b>
    <span id="pline"><span id="elapsed">0 с</span><span id="calls"></span> · {e(job.provider)}{(" · " + e(job.model)) if job.model else ""}</span></div>
  </div>
  <div class="jb-err" id="err" hidden><p class="jb-errline" id="errtext" role="alert"></p><p class="jb-todo" id="todo"></p>
  <a class="jb-btn" href="/">Новая проверка</a></div>
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

    def log_message(self, fmt: str, *args: Any) -> None:  # №42: журнал — в <data-dir>/web.log, в консоль только 5xx
        _log_request_line(self, fmt % args)

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
        if _onboarding.handle_get(self, urlsplit(self.path).path): return  # №40: /welcome, /assets/agent.*  # noqa: E701
        url = urlsplit(self.path)
        path = url.path
        if path.startswith("/examples/"): from . import gallery; return gallery.handle(self)  # №43  # noqa: E701,E702
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
        if _onboarding.handle_post(self, urlsplit(self.path).path): return  # №40: POST /api/key  # noqa: E701
        path = urlsplit(self.path).path
        if path.startswith("/examples/"): from . import gallery; return gallery.handle(self)  # №43  # noqa: E701,E702
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

    def handle_error(self, request: Any, client_address: Any) -> None:  # №42: без трейсбэков в консоли
        _server_error(self, client_address)


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


PORTS = (8014, 8030)  # №42: порт по умолчанию и последний, который пробуем, если предыдущие заняты
# №42: --check проверяет установку — эти модули должны импортироваться из окружения (requirements.txt)
_CHECK_MODULES = ("jsonschema", "google.genai", "anthropic", "pymupdf", "docx", "yaml")
_LOG_LOCK = threading.Lock()
_LOG_MAX = 2 * 1024 * 1024  # web.log больше 2 МБ — в web.log.1, начинаем заново


def _sysenv(name: str) -> str:
    """Переменные терминала и системы (TERM, COLORTERM, NO_COLOR, DISPLAY…) — не настройки агента: в .env.example их нет."""
    return os.environ.get(name, "")


# ── консоль: журнал — в файл, на экран — только то, что нужно человеку ──

def _log_to_file(root: Path | None, text: str) -> None:
    if root is None:
        return
    path = Path(root) / "web.log"
    try:
        with _LOG_LOCK:
            if path.is_file() and path.stat().st_size > _LOG_MAX:
                path.replace(path.with_name("web.log.1"))
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass


def _app_root(handler_cls: Any) -> Path | None:
    store = getattr(getattr(handler_cls, "app", None), "store", None)
    return getattr(store, "root", None)


def _log_request_line(handler: BaseHTTPRequestHandler, text: str) -> None:
    """№42: журнал запросов — в <data-dir>/web.log; в консоль — только ответы 5xx (ошибки сервера)."""
    if any(k in text for k in ("/api/jobs/", "/healthz")):  # опрос прогресса и проверка живости — без шума
        return
    root = _app_root(handler)
    _log_to_file(root, text)
    if re.search(r'" 5\d\d ', text):
        _say(f"Ошибка сервера: {text.strip()} — подробности в {Path(root or '.') / 'web.log'}", err=True)


def _server_error(server: Any, client_address: Any) -> None:
    """№42: обрыв соединения браузером (закрыл вкладку, ушёл со страницы) — не ошибка; прочее — в web.log."""
    exc = sys.exc_info()[1]
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return
    import traceback

    root = _app_root(getattr(server, "RequestHandlerClass", None))
    _log_to_file(root, f"ошибка при обработке запроса от {client_address}:\n{traceback.format_exc()}")
    _say(f"Ошибка при обработке запроса: {type(exc).__name__}: {exc} — подробности в "
         f"{Path(root or '.') / 'web.log'}", err=True)


def _enable_vt(stream: Any) -> bool:
    """Windows 10+: включить разбор ANSI-последовательностей в консоли. Нельзя — без цвета."""
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = k32.GetStdHandle(-12 if stream is sys.stderr else -11)
        mode = wintypes.DWORD()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x0004) or bool(k32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001 — старая консоль или не Windows
        return False


def _color_depth(stream: Any) -> int:
    """0 — без цвета (не терминал, NO_COLOR, TERM=dumb), 256 или 16 млн (24 бита)."""
    try:
        tty = bool(stream.isatty())
    except (AttributeError, ValueError):
        tty = False
    if not tty or "NO_COLOR" in os.environ or _sysenv("TERM") == "dumb":
        return 0
    if os.name == "nt" and not _enable_vt(stream):
        return 0
    truecolor = _sysenv("COLORTERM") in ("truecolor", "24bit") or _sysenv("WT_SESSION") or \
        _sysenv("TERM_PROGRAM") in ("iTerm.app", "vscode", "WezTerm")
    return 24 if truecolor else 256


_GREEN = ((0, 133, 86), 29)     # BCC Green Strong #008556: читается и на белом терминале, и на тёмном
_GOLD = ((220, 162, 98), 179)   # BCC Gold #DCA262
_MUTED = ((139, 152, 165), 245)
_RED = ((224, 95, 85), 167)


def _paint(text: str, color: tuple[tuple[int, int, int], int] | None, depth: int, *, bold: bool = False,
           underline: bool = False) -> str:
    if not depth:
        return text
    codes = (["1"] if bold else []) + (["4"] if underline else [])
    if color:
        (r, g, b), c256 = color
        codes.append(f"38;2;{r};{g};{b}" if depth == 24 else f"38;5;{c256}")
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text


def _say(text: str, *, err: bool = False, color: tuple[tuple[int, int, int], int] | None = None) -> None:
    stream = sys.stderr if err else sys.stdout
    depth = _color_depth(stream)
    print(_paint(text, color or (_RED if err else None), depth), file=stream, flush=True)


def _ready_line(url: str, note: str = "", depth: int = 0) -> str:
    """Одна строка после знакомства: «Система открыта: http://127.0.0.1:8014 · остановить — Ctrl+C»."""
    tail = f" · {note}" if note else ""
    return (_paint("Система открыта: ", None, depth, bold=True) + _paint(url.rstrip("/"), _GREEN, depth, bold=True)
            + _paint(f"{tail} · остановить — Ctrl+C", _MUTED, depth))


def _set_title(title: str) -> None:
    if _color_depth(sys.stdout):
        sys.stdout.write(f"\x1b]0;{title}\x07")
        sys.stdout.flush()


def _shown_host(host: str) -> str:
    return "127.0.0.1" if host in ("", "0.0.0.0", "::") else host


def _get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — только свой локальный адрес
        return r.status, r.read()


def _wait_ready(url: str, timeout: float = 15.0) -> bool:
    """Ждём, пока сервер ответит на /healthz (браузер открываем только после этого)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if _get(url + "healthz", timeout=1.0) == (200, b"ok"):
                return True
        except Exception:  # noqa: BLE001 — ещё не поднялся
            pass
        time.sleep(0.1)
    return False


def _has_gui() -> bool:
    """Linux без графики (ssh, сервер): webbrowser запустил бы текстовый lynx/w3m прямо в этом терминале."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(_sysenv("DISPLAY") or _sysenv("WAYLAND_DISPLAY"))


def _env_path() -> Path:
    """Куда знакомство в терминале запишет ключ: тот же .env, что читает load_dotenv (текущий каталог или корень)."""
    for p in (Path.cwd() / ".env", REPO / ".env"):
        if p.is_file():
            return p
    return Path.cwd() / ".env"


_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _use_aishka(tty_agent: Any) -> None:
    """Владелец, 20:25: в терминале — яркий AIshka (`aishka.py`), а не тёмный дрон. Пока `tty_agent` (№40) рисует
    дрона, подставляем ему отрисовку AIshka (тот же вызов `render(name, mode, small=…)`). Перейдёт сам — пусть
    объявит `MASCOT = "aishka"`, и подмена не нужна."""
    if getattr(tty_agent, "MASCOT", "") == "aishka" or not hasattr(tty_agent, "render"):
        return
    try:
        from . import aishka

        tty_agent.render = aishka.render
    except Exception:  # noqa: BLE001 — останется прежний рисунок, знакомство не ломаем
        pass


def _greet(port: int, root: Path) -> str:
    """№40 — BCC AI в терминале (`tty_agent.greet`): знакомство и ключ до браузера. Возвращает выбранного провайдера.

    Модуля ещё нет (до вливания №40) или знакомство упало — ничего не спрашиваем, система открывается как есть
    (ключ тогда спросит веб). Ctrl+C во время знакомства — выход.
    """
    try:
        from . import tty_agent  # type: ignore[attr-defined]  # №40
    except ImportError:
        return ""
    _use_aishka(tty_agent)
    try:
        got = tty_agent.greet(port, _env_path())
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 — знакомство не должно мешать открыть систему
        import traceback

        _log_to_file(root, f"знакомство в терминале не удалось: {exc!r}\n{traceback.format_exc()}")
        return ""
    got = str(got or "").strip()
    return got if _PROVIDER_ID.match(got) and got != "auto" else ""


def _self_check(url: str) -> int:
    """--check: /healthz и / отвечают, зависимости импортируются. 0 — всё в порядке."""
    import importlib

    problems: list[str] = []
    for mod in _CHECK_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 — нужна причина, а не трейсбэк
            problems.append(f"не импортируется {mod}: {type(exc).__name__}: {exc}")
    if not _wait_ready(url):
        problems.append(f"{url}healthz не ответил за 15 с")
    else:
        try:
            code, body = _get(url)
            if code != 200 or b"<html" not in body.lower():
                problems.append(f"{url} ответил {code}, но не страницей")
            else:
                print(f"Проверка: {url}healthz — ok, {url} — 200 ({len(body) // 1024} КБ)", flush=True)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{url} не открылся: {exc}")
    for p in problems:
        print(f"Проверка не прошла: {p}", file=sys.stderr, flush=True)
    if not problems:
        print("Установка в порядке: ./start.sh (Windows: START.cmd) откроет BCC Review в браузере.", flush=True)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.web", description="Веб-демо ревью требований")
    ap.add_argument("--host", default="127.0.0.1", help="адрес; 0.0.0.0 — доступ из сети (только в Docker)")
    ap.add_argument("--port", type=int, default=PORTS[0], help=f"порт; занят — следующий свободный до {PORTS[1]}")
    ap.add_argument("--provider", default="auto", help="провайдер по умолчанию в форме")
    ap.add_argument("--data-dir", default=".bcc_web", help="где хранить загрузки и отчёты")
    ap.add_argument("--sample", help="файл для кнопки «Проверить пример»")
    ap.add_argument("--fixture", help="показ без модели: этапы по таймеру, отчёт из этого report.json")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--pipeline-args", default="", help="доп. флаги для python -m bcc_review, например \"--engine v1\"")
    ap.add_argument("--cache-dir", help="кэш ответов модели, общий для всех проверок (по умолчанию <data-dir>/cache)")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="для съёмки демо: показывать этапы не быстрее раза в N секунд (анализ не замедляется)")
    ap.add_argument("--open", action="store_true", help="открыть браузер, когда сервер ответит")
    ap.add_argument("--check", action="store_true",
                    help="проверить установку: поднять сервер, получить /healthz и /, выйти (0 — в порядке)")
    ap.add_argument("--no-tty", action="store_true",
                    help="без знакомства в терминале (ключ не спрашивать): Docker, CI, запуск из скриптов")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # непечатаемый символ — «?», а не UnicodeEncodeError
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    load_dotenv()
    app = build_app(Path(a.data_dir), provider=a.provider, fixture=Path(a.fixture) if a.fixture else None,
                    sample=Path(a.sample) if a.sample else None, workers=a.workers,
                    cache_dir=Path(a.cache_dir) if a.cache_dir else None, pace=a.pace,
                    extra_args=shlex.split(a.pipeline_args, posix=(os.name != "nt")))
    tries = max(0, PORTS[1] - a.port) if PORTS[0] <= a.port <= PORTS[1] else 20
    srv, note = bind_server(app, a.host, a.port, tries=tries)
    if srv is None and a.check and note.startswith("Веб-демо уже запущено"):
        srv, note = bind_server(app, a.host, 0)  # проверяем эту установку, а не уже запущенное демо
    if srv is None:
        running = note.startswith("Веб-демо уже запущено")
        print(note, file=sys.stdout if running else sys.stderr, flush=True)
        if running and a.open and _has_gui():
            webbrowser.open(f"http://{_shown_host(a.host)}:{a.port}/")
        return 0 if running else 2
    port = srv.server_address[1]
    url = f"http://{_shown_host(a.host)}:{port}/"
    serve = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True)
    serve.start()
    if a.check:  # сервер — в фоне, проверка — здесь; знакомства и браузера нет
        if note:
            print(note, flush=True)
        try:
            return _self_check(url)
        finally:
            srv.shutdown()
            srv.server_close()
    _set_title("BCC Review")
    depth = _color_depth(sys.stdout)
    pad = "  " if depth else ""  # в терминале — тот же отступ, что у реплик BCC AI; в журнале — без него
    try:
        if not a.no_tty and a.provider == "auto" and not a.fixture:  # провайдер задан или показ — знакомиться незачем
            chosen = _greet(port, app.store.root)
            if chosen:
                app.default_provider = chosen  # ключ введён в терминале — браузер сразу на главной
        if not _wait_ready(url):
            _say(f"{pad}Сервер не ответил на {url}healthz — откройте {url} вручную.", err=True)
        busy = f"порт {a.port} занят другой программой" if port != a.port and a.port else ""
        print(pad + _ready_line(url, busy, depth), flush=True)
        if a.open and _has_gui():
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001 — нет браузера: адрес уже напечатан
                pass
        while serve.is_alive():  # join с таймаутом: Ctrl+C на Windows срабатывает сразу
            serve.join(0.5)
    except KeyboardInterrupt:
        _say(f"\n{pad}BCC Review остановлен.", color=_MUTED)
    finally:
        srv.shutdown()
        srv.server_close()
    return 0
