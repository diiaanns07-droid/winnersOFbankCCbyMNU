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
import re
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


def _date(v: Any) -> str:
    """Дата прогона так, как она записана в отчёте (его часовой пояс), а не по часам сервера (в Docker — UTC)."""
    try:
        return datetime.fromisoformat(str(v)).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return ""


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
        "date": _date(run.get("started_at")),
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
    notice = rec.get("notice") or f"Готовый отчёт: {meta['model']}, {meta['date']} — открыт из файла, модель не вызывалась."
    extra = R._notice(meta["report"])
    job = R.Job(id=jid, file_name=fname, input_path=str(final / "input" / fname),
                provider=str(run.get("provider") or ""),
                model=", ".join(m for m in run.get("models_used") or [] if m != run.get("provider")),
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
    """Чем пойдёт проверка — коротко, для листа в стопке: «демо, без ключа», «только правила», «модель: Gemini»."""
    if provider == "mock":
        return "демо, без ключа"
    if provider == "offline":
        return "только правила"
    return "модель: " + _SHORT.get(provider, provider)


# ─────────────────────────────── стопка листов на главной ───────────────────────────────
#
# Светлый стол (bcc-ui.md, разделы 2–6, с правкой 20:25): белые листы внахлёст — верхний виден целиком (начало
# документа мелким набором, модель, дата, сверка цитат), из-под него выглядывают нижние: название и строка вердикта
# «Разработка: нельзя · 5 блокеров». Цветом — только слово вердикта (красное «нельзя», зелёное «можно»). Наведение
# или фокус выдвигает лист целиком. Вторая стопка — «Свой документ» и примеры, которые проверяются одним нажатием.

_CSS = """<style>
.g43{display:flex;flex-direction:column;gap:20px;min-width:0;color:var(--b-ink,#0F2841)}
.g43-sec{min-width:0}
.g43-cap{margin:0 0 10px 2px;font-size:13px;line-height:1.3;font-weight:600;letter-spacing:.02em;color:var(--b-ink-2,#3A5068)}
.g43-pile{--h:140px;--band:84px;display:flex;flex-direction:column;min-width:0}
.g43-pile.docs{--h:108px;--band:56px}
.g43-slot{position:relative;height:var(--h);min-width:0;
  transition:margin-top var(--b-base,220ms) var(--b-ease,cubic-bezier(.2,.8,.2,1));
  animation:g43-in var(--b-slow,360ms) var(--b-ease,cubic-bezier(.2,.8,.2,1)) both;animation-delay:calc(var(--i,0) * 40ms)}
.g43-slot+.g43-slot{margin-top:calc(var(--band) - var(--h))}
.g43-slot+.g43-slot:hover,.g43-slot+.g43-slot:focus-within{margin-top:8px}
.g43-slot.own{height:auto}
.g43-slot>form{height:100%;margin:0}
@keyframes g43-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.g43-leaf{box-sizing:border-box;display:flex;flex-direction:column;justify-content:flex-end;gap:3px;width:100%;height:100%;
  margin:0;padding:12px 14px 14px;border:0;border-radius:var(--b-r-md,14px);overflow:hidden;
  background:var(--b-paper,#fff);color:var(--b-ink,#0F2841);font:inherit;text-align:left;text-decoration:none;cursor:pointer;
  box-shadow:0 0 0 1px rgba(15,40,65,.07),0 1px 2px rgba(15,40,65,.05),0 8px 22px rgba(15,40,65,.07);
  transition:box-shadow var(--b-fast,120ms) var(--b-ease,ease),transform var(--b-fast,120ms) var(--b-ease,ease)}
.b-root a.g43-leaf,a.g43-leaf{color:var(--b-ink,#0F2841);text-decoration:none}
.g43-leaf:hover{box-shadow:0 0 0 1px rgba(15,40,65,.08),0 2px 6px rgba(15,40,65,.05),0 16px 40px rgba(15,40,65,.10)}
.g43-leaf:active{transform:scale(.985)}
.g43-leaf:focus-visible{outline:3px solid rgba(0,185,117,.55);outline-offset:2px}
.g43-leaf.on{box-shadow:0 0 0 1.5px var(--b-green,#00B975),0 1px 2px rgba(15,40,65,.05),0 8px 22px rgba(15,40,65,.07)}
.g43-leaf>*{flex-shrink:0}
.g43-pv{flex:1 1 0;min-height:0;overflow:hidden;margin-bottom:6px;font-size:13px;line-height:1.35;
  color:var(--b-ink-2,#3A5068);transition:opacity var(--b-base,220ms) var(--b-ease,ease)}
.g43-leaf>.g43-pv{flex-shrink:1}
.g43-pv>span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g43-slot+.g43-slot .g43-pv,.g43-slot+.g43-slot .g43-meta{opacity:0;transition:opacity var(--b-base,220ms) var(--b-ease,ease)}
.g43-slot+.g43-slot:hover .g43-pv,.g43-slot+.g43-slot:focus-within .g43-pv{opacity:1}
.g43-slot+.g43-slot:hover .g43-meta,.g43-slot+.g43-slot:focus-within .g43-meta{opacity:1}
.g43-pile.docs .g43-slot .g43-meta{opacity:1}
.g43-meta{font:11.5px/1.4 var(--b-mono,ui-monospace,Consolas,monospace);color:var(--b-ink-3,#5B6F84);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g43-t{font-size:15px;line-height:1.35;font-weight:600;letter-spacing:-.005em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.g43-v{display:flex;flex-direction:column;align-items:flex-start;gap:1px;font-size:14px;line-height:1.4;
  color:var(--b-ink-2,#3A5068);font-variant-numeric:tabular-nums}
.g43-v .main{color:var(--b-ink,#0F2841);font-weight:600}
.g43-v b{font-weight:700}
.g43-v b.no{color:var(--b-red,#C2362B)} .g43-v b.yes{color:var(--b-green-ink,#00704A)}
.g43-v b.cond,.g43-v b.none{color:var(--b-ink,#0F2841)}
.g43-own{justify-content:flex-start;padding:13px 14px}
.g43-own .g43-meta{white-space:normal;font:13px/1.35 var(--b-font,inherit);color:var(--b-ink-2,#3A5068)}
.g43-pile.docs .g43-leaf:not(.g43-own) .g43-meta{font:13px/1.35 var(--b-font,inherit);color:var(--b-ink-2,#3A5068)}
.g43-own .g43-t{color:var(--b-green-ink,#00704A)}
@media (max-width:760px){
  .g43{gap:14px}
  .g43-pile,.g43-pile.docs{flex-direction:row;gap:10px;overflow-x:auto;scroll-snap-type:x proximity;
    padding:2px 2px 10px;scrollbar-width:none}
  .g43-pile::-webkit-scrollbar{display:none}
  .g43-slot,.g43-slot+.g43-slot,.g43-slot+.g43-slot:hover,.g43-slot+.g43-slot:focus-within{flex:0 0 168px;height:auto;margin:0;scroll-snap-align:start}
  .g43-leaf{min-height:88px;padding:12px 14px;justify-content:flex-start}
  .g43-pv,.g43-pile:not(.docs) .g43-meta{display:none}
  .g43-slot+.g43-slot .g43-meta{opacity:1}
  .g43-meta{white-space:normal}
}
@media (prefers-reduced-motion:reduce){.g43-slot,.g43-leaf,.g43-pv{animation:none;transition:none}}
</style>"""

_VWORD = {"no": ("нельзя", "no"), "conditional": ("с условиями", "cond"), "yes": ("можно", "yes")}
_PV: dict[tuple[str, int], list[str]] = {}
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def verdict_html(summary: dict[str, Any]) -> str:
    """Строка вердикта листа в две строки, как у листов №39: «Разработка: <b>нельзя</b>» и «5 блокеров».

    Цветом — только слово (красное «нельзя», зелёное «можно»).
    """
    word, cls = _VWORD.get(str(summary.get("development") or ""), ("нет вердикта", "none"))
    crit = int(summary.get("critical") or 0)
    tail = f"{crit} {_plural(crit, 'блокер', 'блокера', 'блокеров')}" if crit else "блокеров нет"
    return f'<span class="main">Разработка: <b class="{cls}">{e(word)}</b></span><span>{e(tail)}</span>'


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def preview_lines(path: Path, n: int = 1) -> list[str]:
    """Первые строки документа (по умолчанию — заголовок) для листа в стопке: Markdown без разметки, у PDF — первая страница."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_mtime_ns)
    if key in _PV:
        return _PV[key]
    text = ""
    try:
        if path.suffix.lower() in (".md", ".markdown", ".txt"):
            text = path.read_text(encoding="utf-8", errors="replace")[:6000]
        elif path.suffix.lower() == ".pdf":
            import pymupdf  # уже в зависимостях; нет его — миниатюра без текста
            with pymupdf.open(path) as doc:
                text = doc[0].get_text()[:6000] if doc.page_count else ""
    except Exception:  # noqa: BLE001
        text = ""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= set("|-: "):
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            line = " · ".join(c for c in cells if c)
        line = _MD_LINK.sub(r"\1", line.lstrip("#>*- ").replace("**", "").replace("`", "")).strip()
        if line:
            out.append(line[:90])
        if len(out) >= n:
            break
    if len(_PV) > 64:
        _PV.clear()
    _PV[key] = out
    return out


def _pv(lines: list[str]) -> str:
    return f'<span class="g43-pv" aria-hidden="true">{"".join(f"<span>{e(x)}</span>" for x in lines)}</span>' if lines else \
        '<span class="g43-pv" aria-hidden="true"></span>'


def _quotes(report: dict[str, Any]) -> str:
    s = report.get("summary") or {}
    v, t = s.get("quotes_verified"), s.get("quotes_total")
    return f"цитат {v} из {t}" if isinstance(v, int) and isinstance(t, int) and t else ""


def reports_block(app: Any, examples: dict[str, list[dict[str, Any]]] | None = None) -> str:
    """Стопка готовых отчётов: листы внахлёст, ссылки /examples/<id> → готовое задание."""
    ex = examples if examples is not None else load_examples()
    ready = ensure_ready(app, ex)
    recs = [r for r in ex["reports"] if r["id"] in ready]
    own_done = any(j.state == "done" for j in app.store.recent())
    leaves = []
    for i, rec in enumerate(recs):
        on = i == 0 and not own_done  # этот лист №39 раскрывает на столе, пока своих проверок нет
        on_cls, on_attr = (" on", 'aria-current="page" ') if on else ("", "")  # без «\"» в f-строке: Python 3.11
        m = report_meta(rec["json"])
        date = m["date"][:5] if m["date"] else ""
        meta = " · ".join(x for x in (rec.get("subtitle") or m["model"], date) if x)
        quotes = _quotes(m["report"])
        title = rec.get("title") or rec["id"]
        leaves.append(
            f'<div class="g43-slot" style="z-index:{len(recs) - i};--i:{i}">'
            f'<a class="g43-leaf{on_cls}" href="/examples/{e(rec["id"])}" data-job="{e(ready[rec["id"]])}" {on_attr}'
            f'title="{e(meta)}{" · " + e(quotes) if quotes else ""}" '
            f'aria-label="{e(title)}: разработка — {e(m["verdict"])}, {e(m["line"].split(", ", 1)[-1])}; {e(meta)}">'
            f'{_pv(preview_lines(rec["source"]))}<span class="g43-meta">{e(meta)}</span>'
            f'<span class="g43-t">{e(title)}</span><span class="g43-v">{verdict_html(m["summary"])}</span></a></div>')
    return "".join(leaves)


def documents_block(examples: dict[str, list[dict[str, Any]]] | None = None, *, own: bool = True) -> str:
    """Вторая стопка: «Свой документ» (открывает выбор файла панели, input#file) и примеры — проверка одним нажатием."""
    ex = examples if examples is not None else load_examples()
    docs = [d for d in ex["documents"] if d.get("ok")]
    n = len(docs) + (1 if own else 0)
    leaves = []
    if own:
        leaves.append(f'<div class="g43-slot own" style="z-index:{n};--i:0"><label class="g43-leaf g43-own" for="file">'
                      f'<span class="g43-t">Свой документ</span>'
                      f'<span class="g43-meta">перетащите файл на стол или выберите</span></label></div>')
    for j, d in enumerate(docs):
        i = j + (1 if own else 0)
        prov = pick_provider(d)
        hint = _doc_hint(d, prov)
        title = d.get("title") or d["id"]
        leaves.append(f'<div class="g43-slot" style="z-index:{n - i};--i:{i}">'
                      f'<form method="post" action="/examples/check/{e(d["id"])}">'
                      f'<button type="submit" class="g43-leaf" title="Проверить этот документ ({e(hint)})" '
                      f'aria-label="Проверить этот документ: {e(title)}, {e(hint)}">'
                      f'{_pv(preview_lines(d["path"]))}<span class="g43-t">{e(title)}</span>'
                      f'<span class="g43-meta">{e(hint)}</span></button></form></div>')
    return "".join(leaves)


def job_leaf(job: Any, *, i: int = 0, n: int = 1) -> str:
    """Своя проверка тем же листом (для стопки №39): название, строка вердикта, время и модель."""
    s = job.summary or {}
    when = time.strftime("%d.%m %H:%M", time.localtime(job.created))
    if job.state == "done":
        line = verdict_html(s)
    else:
        line = e({"queued": "в очереди", "running": "идёт проверка", "failed": "ошибка прогона"}.get(job.state, job.state))
    meta = " · ".join(x for x in (when, _SHORT.get(job.provider, job.provider)) if x)
    return (f'<div class="g43-slot" style="z-index:{n - i};--i:{i}"><a class="g43-leaf" href="/jobs/{e(job.id)}">'
            f'{_pv(preview_lines(Path(job.input_path)))}<span class="g43-meta">{e(meta)}</span>'
            f'<span class="g43-t">{e(Path(job.file_name).stem)}</span><span class="g43-v">{line}</span></a></div>')


def gallery_block(app: Any) -> str:
    """Стопка готовых листов для стола (левая колонка №39): готовые отчёты + «Свой документ» и примеры."""
    try:
        ex = load_examples()
        reports = reports_block(app, ex)
        docs = documents_block(ex)
    except Exception:  # noqa: BLE001 — стопка не должна ронять главную
        return ""
    parts = [_CSS, '<div class="g43" id="ready">']
    if reports:
        parts.append('<section class="g43-sec" aria-labelledby="g43-h1"><h2 class="g43-cap" id="g43-h1">Готовые отчёты</h2>'
                     f'<div class="g43-pile">{reports}</div></section>')
    parts.append('<section class="g43-sec" aria-labelledby="g43-h2"><h2 class="g43-cap" id="g43-h2">Проверить</h2>'
                 f'<div class="g43-pile docs">{docs}</div></section>')
    parts.append("</div>")
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
