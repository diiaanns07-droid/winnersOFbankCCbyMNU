"""№43: «Готовые отчёты» и примеры документов на главной веб-демо — система полезна с первой секунды.

Что лежит где::

    examples/examples.json      какие отчёты и документы показывать (пути от корня репозитория)
    examples/mock/              «Демо без модели»: отчёт официального ТЗ, --provider mock (сгенерирован инструментом)

Готовый отчёт кладётся в хранилище заданий веба (`JobStore`) как обычное завершённое задание с номером
`00000000-000043-<6 hex от содержимого>` — и открывается тем же экраном `/jobs/<id>`, что и своя проверка: без ключа,
без сети и без повторного анализа. Запись `examples.json`, у которой нет файлов, не показывается.

Маршруты (одна строка в `do_GET`/`do_POST` сервера, пометка `# №43`)::

    GET  /examples/<отчёт>          положить готовое задание (если его ещё нет) → 303 /jobs/<id>
    POST /examples/check/<документ> проверить пример: с ключом — «Автовыбор», без ключа — mock или offline → 303 /jobs/<id>
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from dataclasses import asdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import runner as R

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples" / "examples.json"
REPO = HERE.parents[3]  # src/bcc_review/v2/web → корень репозитория
PREFIX = "00000000-000043-"  # номер готового задания: проходит JOB_PATH сервера и не путается с настоящими
NO_MODEL = ("mock", "offline")

_VERDICT = {"no": ("нельзя", "crit"), "conditional": ("с условиями", "major"), "yes": ("можно", "ok")}
_NO_KEY = {"mock": "демо без модели", "offline": "только правила"}
_SHORT = {"claude_cli": "Claude Code", "gemini": "Gemini", "anthropic": "Claude API", "openai": "свой сервер модели"}
_LOCK = threading.Lock()
_META: dict[tuple[str, int, int], dict[str, Any]] = {}  # (путь json, mtime, размер) → сведения для карточки


def e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


def is_ready(job: Any) -> bool:
    """Готовое задание галереи (для фильтра «Последние проверки»): принимает Job или его номер."""
    return str(getattr(job, "id", job) or "").startswith(PREFIX)


# ─────────────────────────────── examples.json ───────────────────────────────

def load_examples(path: Path | None = None, repo: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Записи examples.json с абсолютными путями и признаком `ok` — есть ли все нужные файлы."""
    path, repo = Path(path or EXAMPLES), Path(repo or REPO)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"reports": [], "documents": []}
    reports, docs = [], []
    for r in raw.get("reports") or []:
        rec = dict(r)
        for k in ("json", "html", "md", "source", *(key for key, *_ in R.FILES)):
            if isinstance(rec.get(k), str) and rec[k]:
                rec[k] = repo / rec[k]
        rec["ok"] = all(isinstance(rec.get(k), Path) and rec[k].is_file() for k in ("json", "html", "source"))
        reports.append(rec)
    for d in raw.get("documents") or []:
        rec = dict(d)
        rec["path"] = repo / str(rec.get("path") or "")
        rec["ok"] = rec["path"].is_file() and rec["path"].suffix.lower() in R.ALLOWED_EXT
        rec.setdefault("file_name", rec["path"].name)
        docs.append(rec)
    return {"reports": reports, "documents": docs}


def model_label(run: dict[str, Any]) -> str:
    """«Claude Sonnet», «Gemini 3.8 Flash», «Демо без модели» — из паспорта прогона."""
    prov = run.get("provider") or ""
    if prov == "mock":
        return "Демо без модели"
    if prov == "offline":
        return "Только правила"
    out: list[str] = []
    for m in [*(run.get("models_used") or []), run.get("model_requested") or ""]:
        m = str(m).strip()
        if not m:
            continue
        low = m.lower()
        fam = next((f for f in ("opus", "sonnet", "haiku") if f in low), "")
        if fam:
            lbl = "Claude " + fam.capitalize()
        elif low.startswith("gemini"):
            lbl = " ".join(p.capitalize() if p.isalpha() else p for p in low.split("-"))
        else:
            lbl = m
        if lbl not in out:
            out.append(lbl)
        if run.get("models_used"):
            break  # первая использованная модель; запрошенная — только если использованных нет
    return ", ".join(out) or _SHORT.get(prov, prov) or "модель"


def _ts(v: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (TypeError, ValueError):
        return None


def report_meta(json_path: Path) -> dict[str, Any]:
    """Сведения для карточки и задания из report.json (с кэшем по времени изменения файла)."""
    st = json_path.stat()
    key = (str(json_path), st.st_mtime_ns, st.st_size)
    if key in _META:
        return _META[key]
    data = json_path.read_bytes()
    report = json.loads(data.decode("utf-8"))
    run = report.get("run") or {}
    s = R._summary(report)
    started = _ts(run.get("started_at"))
    finished = _ts(run.get("finished_at"))
    if started and not finished and isinstance(run.get("duration_s"), (int, float)):
        finished = started + float(run["duration_s"])
    dev = s.get("development", "")
    verdict, cls = _VERDICT.get(dev, ("не вынесен", "plain"))
    crit = int(s.get("critical") or 0)
    meta = {
        "digest": hashlib.sha1(data).hexdigest(),
        "report": report, "run": run, "summary": s,
        "model": model_label(run),
        "date": time.strftime("%d.%m.%Y", time.localtime(started)) if started else "",
        "started": started, "finished": finished,
        "verdict": verdict, "verdict_cls": cls, "critical": crit,
        "line": f"вердикт: {verdict}, " + (f"блокеров {crit}" if crit else "блокеров нет"),
    }
    if len(_META) > 32:
        _META.clear()
    _META[key] = meta
    return meta


# ─────────────────────────────── готовые задания ───────────────────────────────

def ready_id(rec: dict[str, Any], meta: dict[str, Any]) -> str:
    h = hashlib.sha1(f"{rec['id']}\n{meta['digest']}\n{rec['html'].stat().st_size}".encode("utf-8")).hexdigest()
    return PREFIX + h[:6]


def _build_job(store: Any, jid: str, rec: dict[str, Any], meta: dict[str, Any]) -> R.Job:
    """Каталог задания со всеми файлами отчёта; собирается вне jobs/ и переносится туда целиком."""
    final = store.dir(jid)
    tmp = Path(store.root) / "ready43.tmp" / jid
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "input").mkdir(parents=True)
    (tmp / "out").mkdir()
    fname = R.safe_filename(rec.get("file_name") or rec["source"].name)
    shutil.copy2(rec["source"], tmp / "input" / fname)
    for key, name, _lbl, _mime in R.FILES:  # json/html/md и любые выгрузки, если они указаны в записи
        src = rec.get(key)
        if isinstance(src, Path) and src.is_file():
            shutil.copy2(src, tmp / "out" / name)
    run = meta["run"]
    stages = {k: "done" for k, _ in R.STAGES}
    for k, v in (run.get("stages") or {}).items():
        k = R._norm_stage(k)
        if k:
            stages[k] = R.STATE_OF.get(v, "done")
    times = {}
    for k, v in (run.get("stage_stats") or {}).items():
        k = R._norm_stage(k)
        if k and isinstance(v, dict) and isinstance(v.get("seconds"), (int, float)):
            times[k] = round(float(v["seconds"]), 1)
    started = meta["started"] or time.time()
    notice = rec.get("notice") or (f"Готовый отчёт: {meta['model']}, {meta['date']}. Открыт из файла — модель заново "
                                   f"не вызывалась.")
    extra = R._notice(meta["report"])
    job = R.Job(id=jid, file_name=fname, input_path=str(final / "input" / fname),
                provider=str(run.get("provider") or ""), model=", ".join(run.get("models_used") or []),
                created=started, state="done", started=started, finished=meta["finished"] or started,
                stages=stages, stage_times=times,
                files={k: n for k, n, _, _ in R.FILES if (tmp / "out" / n).is_file()},
                log=[f"Готовый отчёт «{rec.get('title', rec['id'])}» из examples.json (№43)."],
                summary=meta["summary"], notice=(notice + " " + extra).strip() if extra else notice)
    # не job.json: JobStore при старте не подхватывает готовые задания в «Последние проверки»; их возвращает ensure_ready
    (tmp / "ready.json").write_text(json.dumps({"example": rec["id"], "digest": meta["digest"], "job": asdict(job)},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    tmp.replace(final)
    try:
        tmp.parent.rmdir()
    except OSError:
        pass
    return job


def _from_disk(store: Any, jid: str, digest: str) -> R.Job | None:
    """Готовое задание, собранное при прошлом запуске сервера (файлы уже на месте) — без повторного копирования."""
    d = store.dir(jid)
    try:
        rec = json.loads((d / "ready.json").read_text(encoding="utf-8"))
        if rec.get("digest") != digest or not (d / "out" / "report.html").is_file():
            return None
        job = R.Job(**{k: v for k, v in rec["job"].items() if k in R.Job.__dataclass_fields__})
        job.input_path = str(d / "input" / job.file_name)  # каталог данных могли перенести
        return job
    except Exception:  # noqa: BLE001
        return None


def _hide_from_recent(store: Any) -> None:
    """«Последние проверки» — только свои проверки пользователя: готовые отчёты живут в своём блоке."""
    if getattr(store, "_g43_recent", False):
        return
    orig = store.recent

    def recent(n: int = 12) -> list[R.Job]:
        return [j for j in orig(len(store.jobs) or n) if not is_ready(j)][:n]

    store.recent, store._g43_recent = recent, True


def ensure_ready(app: Any, examples: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, str]:
    """Положить готовые отчёты в хранилище заданий, если их ещё нет. Возвращает {id записи: номер задания}."""
    store = app.store
    ex = examples if examples is not None else load_examples()
    out: dict[str, str] = {}
    with _LOCK:
        _hide_from_recent(store)
        for rec in ex["reports"]:
            if not rec.get("ok"):
                continue
            try:
                meta = report_meta(rec["json"])
                jid = ready_id(rec, meta)
                if not (store.get(jid) and (store.dir(jid) / "out" / "report.html").is_file()):
                    job = _from_disk(store, jid, meta["digest"]) or _build_job(store, jid, rec, meta)
                    with store.lock:
                        store.jobs[jid] = job
                out[rec["id"]] = jid
            except Exception:  # noqa: BLE001 — битый отчёт просто не показываем, главная не падает
                continue
        keep = set(out.values())
        for jid in [j for j in list(store.jobs) if is_ready(j) and j not in keep]:  # устаревшие версии
            with store.lock:
                store.jobs.pop(jid, None)
        for d in (Path(store.root) / "jobs").glob(PREFIX + "*"):
            if d.name not in keep and (d / "ready.json").is_file():
                shutil.rmtree(d, ignore_errors=True)
    return out


# ─────────────────────────────── примеры документов ───────────────────────────────

def pick_provider(doc: dict[str, Any]) -> str:
    """С ключом — тот провайдер, что выбрал бы «Автовыбор»; без ключа — `no_key` записи (mock или offline)."""
    try:
        resolved = R.provider_status()[0].get("resolved", "offline")
    except Exception:  # noqa: BLE001
        resolved = "offline"
    if resolved in NO_MODEL:
        return doc.get("no_key") if doc.get("no_key") in NO_MODEL else "offline"
    return resolved


def _doc_hint(doc: dict[str, Any], provider: str) -> str:
    if provider in NO_MODEL:
        return "без ключа — " + _NO_KEY[provider]
    return "модель: " + _SHORT.get(provider, provider)


# ─────────────────────────────── блок на главной ───────────────────────────────

_CSS = """<style>
.g43{display:flex;flex-direction:column;gap:14px}
.g43-head{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 14px}
.g43-cards{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.g43-cards>li{display:flex;min-width:0}
.g43-card{display:flex;flex-direction:column;gap:10px;width:100%;min-height:132px;color:inherit;text-decoration:none;
  transition:transform var(--b-fast,120ms) var(--b-ease,ease),box-shadow var(--b-fast,120ms) var(--b-ease,ease)}
.b-root a.g43-card{color:var(--b-ink,#0F2841);text-decoration:none}
.g43-card:hover{transform:translateY(-1px);box-shadow:0 0 0 1px var(--b-hair,rgba(15,40,65,.08)),var(--b-shadow-2,0 16px 40px rgba(15,40,65,.1))}
.g43-card:active{transform:scale(.98)}
.g43-t{font-size:17px;font-weight:650;line-height:1.3;letter-spacing:-.01em}
.g43-m{margin-top:auto;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.g43-try{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px}
.g43-try form{margin:0;display:contents}
.g43-try .g43-lbl{font-weight:600;color:var(--b-ink-2,#3A5068);font-size:15px;margin-right:2px}
@media (max-width:1100px){.g43-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:560px){.g43-cards{grid-template-columns:minmax(0,1fr)}.g43-card{min-height:0}
  .g43-try{display:grid;grid-template-columns:minmax(0,1fr);gap:8px}.g43-try .b-button{width:100%}}
</style>"""


def reports_block(app: Any, examples: dict[str, list[dict[str, Any]]] | None = None) -> str:
    ex = examples if examples is not None else load_examples()
    ready = ensure_ready(app, ex)
    cards = []
    for rec in ex["reports"]:
        if rec["id"] not in ready:
            continue
        m = report_meta(rec["json"])
        cards.append(
            f'<li><a class="b-surface g43-card" href="/examples/{e(rec["id"])}" data-job="{e(ready[rec["id"]])}">'
            f'<span class="g43-t">{e(rec.get("title") or rec["id"])}</span>'
            f'<span class="g43-m"><span class="b-note">{e(m["model"])}{" · " + e(m["date"]) if m["date"] else ""}</span>'
            f'<span class="b-badge {m["verdict_cls"]}">{e(m["line"])}</span></span></a></li>')
    return "".join(cards)


def documents_block(examples: dict[str, list[dict[str, Any]]] | None = None) -> str:
    ex = examples if examples is not None else load_examples()
    btns = []
    for d in ex["documents"]:
        if not d.get("ok"):
            continue
        prov = pick_provider(d)
        hint = _doc_hint(d, prov)
        btns.append(f'<form method="post" action="/examples/check/{e(d["id"])}"><button type="submit" '
                    f'class="b-button small" title="Проверить этот документ: {e(d.get("title"))} ({e(hint)})" '
                    f'aria-label="Проверить этот документ: {e(d.get("title"))}, {e(hint)}">{e(d.get("title"))}</button></form>')
    return "".join(btns)


def _try_note(ex: dict[str, list[dict[str, Any]]]) -> str:
    provs = {pick_provider(d) for d in ex["documents"] if d.get("ok")}
    if provs and provs <= set(NO_MODEL):
        if provs == {"mock", "offline"}:
            return "Без ключа: официальный ТЗ — демо без модели, остальные — только правила."
        return "Без ключа: " + _NO_KEY[next(iter(provs))] + "."
    return "Проверка моделью: " + ", ".join(sorted(_SHORT.get(p, p) for p in provs)) + "." if provs else ""


def gallery_block(app: Any) -> str:
    """Блок «Готовые отчёты» для главной: 3–4 карточки и примеры документов одним нажатием. Пусто — если показывать нечего."""
    try:
        ex = load_examples()
        cards = reports_block(app, ex)
        docs = documents_block(ex)
    except Exception:  # noqa: BLE001 — галерея не должна ронять главную
        return ""
    if not cards and not docs:
        return ""
    parts = [_CSS, '<section class="home-sec b-rise g43" id="ready" aria-labelledby="g43-h">']
    if cards:
        parts.append('<div class="g43-head"><h2 class="b-h2" id="g43-h">Готовые отчёты</h2>'
                     '<span class="b-note">открываются сразу, без ключа и сети</span></div>'
                     f'<ul class="g43-cards">{cards}</ul>')
    else:
        parts.append('<div class="g43-head"><h2 class="b-h2" id="g43-h">Примеры документов</h2></div>')
    if docs:
        note = _try_note(ex)
        parts.append(f'<div class="g43-try" role="group" aria-label="Проверить пример">'
                     f'<span class="g43-lbl">Проверить пример:</span>{docs}</div>'
                     + (f'<p class="b-note" style="margin:0">{e(note)}</p>' if note else ""))
    parts.append("</section>")
    return "".join(parts)


# ─────────────────────────────── маршруты /examples/… ───────────────────────────────

def handle(h: Any) -> None:
    """GET /examples/<отчёт> и POST /examples/check/<документ>; `h` — обработчик запроса сервера."""
    path = urlsplit(h.path).path.rstrip("/")
    parts = path.split("/")[2:]  # ['', 'examples', …]
    ex = load_examples()
    if h.command in ("GET", "HEAD") and len(parts) == 1:
        ready = ensure_ready(h.app, ex)
        jid = ready.get(parts[0])
        if jid:
            return h._send(303, b"", "text/plain", {"Location": f"/jobs/{jid}"})
        return h._not_found()
    if h.command == "POST" and len(parts) == 2 and parts[0] == "check":
        doc = next((d for d in ex["documents"] if d["id"] == parts[1] and d.get("ok")), None)
        if not doc:
            return h._not_found()
        provider = pick_provider(doc)
        problem = R.check_provider(provider, "")
        if problem:
            return h._fail(400, problem, provider, "")
        job = h.app.start(doc["file_name"], doc["path"].read_bytes(), provider, "")
        if h._wants_json():
            return h._json(201, {"id": job.id, "url": f"/jobs/{job.id}", "provider": provider})
        return h._send(303, b"", "text/plain", {"Location": f"/jobs/{job.id}"})
    return h._not_found()
