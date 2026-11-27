"""Запуск анализа для веб-демо: проверка провайдеров, задания, прогресс по этапам.

Анализ выполняет pipeline v2 отдельным процессом — ровно той же командой, что в README
(`python -m bcc_review ВХОД ОТЧЁТ.md --provider …`). Прогресс веб читает из каталога прогона
(`runs/<run_id>/stages/<этап>.json`, `trace.jsonl`), поэтому ему не нужен доступ к внутренностям
pipeline. Для тестов и показа без модели есть `FixtureRunner`: проигрывает этапы и собирает отчёт
из готового report.json.
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

STAGES: list[tuple[str, str]] = [  # имена — как у файлов runs/<id>/stages/<этап>.json pipeline v2
    ("docview", "Чтение документа"),
    ("segment", "Нарезка требований"),
    ("rules", "Правила"),
    ("lens_analyst", "Аналитик"),
    ("lens_qa", "Тестировщик"),
    ("lens_architect", "Архитектор"),
    ("lens_risk", "Риски"),
    ("consistency", "Набор целиком"),
    ("quotes", "Сверка цитат кодом"),
    ("judge", "Судья"),
    ("clarify", "Вопросы владельцу"),
    ("recheck", "Пересмотр по ответам"),
    ("revise", "Исправленное ТЗ"),
    ("report", "Отчёт"),
]
PARALLEL = {"lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency"}
ANSWER_STAGES = {"recheck", "revise"}  # показываются только при --answers
STAGE_ALIASES = {"lens:analyst": "lens_analyst", "lens:qa": "lens_qa", "lens:architect": "lens_architect",
                 "lens:risk": "lens_risk", "analyst": "lens_analyst", "qa": "lens_qa", "architect": "lens_architect",
                 "risk": "lens_risk", "render": "report", "verdict": "report", "answers": "recheck"}
STATE_OF = {"ok": "done", "partial": "done", "failed": "failed", "skipped": "skipped"}
_LOG_STAGE = re.compile(r"^\s+([a-z_:]+): (запуск|готово|СБОЙ|взят)")

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm"}
MAX_UPLOAD = 20 * 1024 * 1024

FILES = [  # (ключ, имя файла в out/, подпись, mime)
    ("html", "report.html", "HTML", "text/html; charset=utf-8"),
    ("md", "report.md", "Markdown", "text/markdown; charset=utf-8"),
    ("json", "report.json", "JSON", "application/json"),
    ("docx", "report.docx", "Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("pdf", "report.pdf", "PDF", "application/pdf"),
    ("csv", "report.jira.csv", "Jira CSV", "text/csv; charset=utf-8"),
    ("docx_annotated", "report.annotated.docx", "Word с комментариями",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("pdf_annotated", "report.annotated.pdf", "PDF с выделениями", "application/pdf"),
    ("revised", "report.revised.md", "Исправленное ТЗ", "text/markdown; charset=utf-8"),
    ("answers_next", "report.answers-next.md", "Следующий круг ответов", "text/markdown; charset=utf-8"),
    ("confluence", "report.confluence.txt", "Confluence", "text/plain; charset=utf-8"),
]


# ─────────────────────────────── провайдеры ───────────────────────────────

def load_dotenv(path: Path | None = None) -> None:
    """Прочитать .env (KEY=VALUE) без перезаписи уже заданных переменных — тем же загрузчиком, что CLI.

    Блокнот пишет UTF-8 с BOM, PowerShell 5.1 (`echo … > .env`) — UTF-16: раньше веб в первом случае не видел
    ключ, во втором падал трейсбэком, а CLI оба файла читал. Как и CLI, без .env в текущем каталоге берём .env
    из корня репозитория.
    """
    try:
        from bcc_review.v2.providers import doctor
    except Exception:  # noqa: BLE001 — без провайдеров веб всё равно покажет «Демо без модели»
        return
    for p in ([Path(path)] if path is not None else [Path(".env"), Path(__file__).resolve().parents[4] / ".env"]):
        try:
            if doctor.load_dotenv(p):
                return
        except (OSError, UnicodeError):
            return


def _auto_choice(env: Any) -> str:
    """Какой провайдер выберет `--provider auto` у CLI (тот же порядок: Gemini, Claude API, свой сервер, Claude CLI)."""
    try:
        from bcc_review.v2.providers.doctor import resolve_auto
        return resolve_auto(env)[0]
    except Exception:  # noqa: BLE001
        return "offline"


def _have_claude_cli(env: Any) -> bool:
    try:
        from bcc_review.v2.providers.claude_cli import find_cli
        return bool(find_cli(env))
    except Exception:  # noqa: BLE001
        return bool(shutil.which("claude"))


def provider_status() -> list[dict[str, Any]]:
    """Какие провайдеры доступны прямо сейчас и почему нет, если нет."""
    env = os.environ
    have_claude = _have_claude_cli(env)
    gem = bool((env.get("GEMINI_API_KEY") or "").strip() or (env.get("GOOGLE_API_KEY") or "").strip())
    ant = bool((env.get("ANTHROPIC_API_KEY") or "").strip())
    oai = bool((env.get("OPENAI_BASE_URL") or "").strip())
    out = [
        {"id": "claude_cli", "label": "Claude через Claude Code CLI", "ok": have_claude,
         "note": "без API-ключа, по подписке Claude Code" if have_claude else "команда «claude» не найдена",
         "models": ["opus", "sonnet", "haiku"]},
        {"id": "gemini", "label": "Google Gemini", "ok": gem,
         "note": "ключ найден" if gem else "нет GEMINI_API_KEY в окружении или .env",
         "models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]},
        {"id": "anthropic", "label": "Claude API", "ok": ant,
         "note": "ключ найден" if ant else "нет ANTHROPIC_API_KEY в окружении или .env",
         "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]},
        {"id": "openai", "label": "Закрытый контур (Ollama, vLLM)", "ok": oai,
         "note": env.get("OPENAI_BASE_URL", "") if oai else "нет OPENAI_BASE_URL — адрес своего сервера модели",
         "models": []},
        {"id": "mock", "label": "Демо без модели (заготовленные ответы)", "ok": True,
         "note": "для проверки установки, работает без сети", "models": []},
        {"id": "offline", "label": "Без модели: только правила", "ok": True,
         "note": "быстро, но находит только формальные дефекты", "models": []},
    ]
    first = _auto_choice(env)
    if not any(p["id"] == first and p["ok"] for p in out):
        first = next((p["id"] for p in out[:4] if p["ok"]), "offline")
    label = next(p["label"] for p in out if p["id"] == first)
    out.insert(0, {"id": "auto", "label": f"Автовыбор: {label}", "ok": True, "note": "первый доступный провайдер",
                   "models": [], "resolved": first})
    return out


def check_provider(pid: str, model: str = "") -> str:
    """Пустая строка — можно запускать; иначе понятное сообщение для пользователя."""
    if pid == "openai" and os.environ.get("OPENAI_BASE_URL") and not (model or os.environ.get("OPENAI_MODEL")):
        return ("Свой сервер модели: не указана модель. Впишите её в поле «Вариант модели» (например qwen3:8b для "
                "Ollama) или задайте OPENAI_MODEL в файле .env.")
    for p in provider_status():
        if p["id"] == pid:
            if p["ok"]:
                return ""
            hint = {"gemini": "Получите бесплатный ключ в Google AI Studio и добавьте строку GEMINI_API_KEY=… в файл .env.",
                    "anthropic": "Добавьте строку ANTHROPIC_API_KEY=… в файл .env.",
                    "openai": "Укажите OPENAI_BASE_URL=http://localhost:11434/v1 (Ollama) в файле .env.",
                    "claude_cli": "Установите Claude Code (npm i -g @anthropic-ai/claude-code) и войдите в аккаунт."}.get(pid, "")
            return f"{p['label']}: {p['note']}. {hint} Без ключа можно выбрать «Демо без модели»."
    return f"Неизвестный провайдер: {pid}"


# ─────────────────────────────── задания ───────────────────────────────

@dataclass
class Job:
    id: str
    file_name: str
    input_path: str
    provider: str
    model: str
    created: float
    state: str = "queued"               # queued | running | done | failed
    started: float | None = None
    finished: float | None = None
    error: str = ""
    stages: dict[str, str] = field(default_factory=lambda: {k: "pending" for k, _ in STAGES})
    stage_times: dict[str, float] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    notice: str = ""                    # предупреждение к готовому отчёту (модель недоступна, прогон неполный)
    parent: str = ""                    # задание, на вопросы которого отвечали
    answers_path: str = ""              # файл ответов владельца (--answers)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("input_path", None)
        d["answers_path"] = bool(self.answers_path)
        d["log"] = self.log[-40:]
        d["elapsed"] = round((self.finished or time.time()) - (self.started or self.created), 1)
        d["stage_list"] = [{"id": k, "label": lbl, "state": self.stages.get(k, "pending"),
                            "parallel": k in PARALLEL} for k, lbl in STAGES
                           if k not in ANSWER_STAGES or self.answers_path]
        return d


class JobStore:
    """Задания в памяти + `job.json` на диске (чтобы список переживал перезапуск сервера)."""

    def __init__(self, root: Path):
        # абсолютный корень: анализ идёт дочерним процессом с cwd = папка задания, и относительные пути
        # (по умолчанию --data-dir .bcc_web) там не находятся — «Файл не найден: .bcc_web\jobs\…\input\…»
        self.root = Path(root).resolve()
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        gi = self.root / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n", encoding="utf-8")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        for p in sorted((self.root / "jobs").glob("*/job.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                job = Job(**{k: v for k, v in d.items() if k in Job.__dataclass_fields__})
                if job.state in ("queued", "running"):
                    job.state, job.error = "failed", "Сервер был перезапущен во время анализа."
                self.jobs[job.id] = job
            except Exception:  # noqa: BLE001
                continue

    def dir(self, job_id: str) -> Path:
        return self.root / "jobs" / job_id

    def create(self, file_name: str, data: bytes, provider: str, model: str, *, parent: str = "",
               answers: bytes = b"") -> Job:
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        d = self.dir(jid)
        (d / "input").mkdir(parents=True)
        safe = safe_filename(file_name)
        inp = d / "input" / safe
        inp.write_bytes(data)
        job = Job(id=jid, file_name=safe, input_path=str(inp), provider=provider, model=model, created=time.time(),
                  parent=parent)
        if answers:
            ap = d / "input" / "answers.md"
            ap.write_bytes(answers)
            job.answers_path = str(ap)
        with self.lock:
            self.jobs[jid] = job
        self.save(job)
        return job

    def save(self, job: Job) -> None:
        p = self.dir(job.id) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def recent(self, n: int = 12) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)[:n]


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "txt"
    stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip(" ._") or "document"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext).lower() or "txt"
    return f"{stem[:80]}.{ext}"


# ─────────────────────────────── исполнители ───────────────────────────────

def _norm_stage(name: str) -> str | None:
    name = name.strip()
    name = STAGE_ALIASES.get(name, name)
    return name if any(name == k for k, _ in STAGES) else None


class PipelineRunner:
    """Запускает `python -m bcc_review ВХОД out/report.md` и следит за каталогом прогона.

    `cache_dir` — общий кэш ответов модели для всех проверок веба (повторная проверка того же файла — мгновенно).
    `pace` — для съёмки демо: этапы показываются не быстрее одного раза в `pace` секунд (сам анализ не замедляется).
    """

    def __init__(self, store: JobStore, *, extra_args: list[str] | None = None, timeout_s: float = 3600,
                 cache_dir: Path | None = None, pace: float = 0.0):
        self.store = store
        self.extra_args = list(extra_args or [])
        self.timeout_s = timeout_s
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.pace = float(pace or 0)

    def command(self, job: Job, out_md: Path, runs_dir: Path) -> list[str]:
        cmd = [sys.executable, "-m", "bcc_review", job.input_path, str(out_md), "--provider", job.provider]
        if job.model:
            cmd += ["--model", job.model]
        if job.answers_path:
            cmd += ["--answers", job.answers_path, "--revise"]
        cmd += ["--export", "jira,docx,pdf", "--runs-dir", str(runs_dir), "--run-id", job.id]
        if self.cache_dir:
            cmd += ["--cache-dir", str(self.cache_dir.resolve())]
        return cmd + self.extra_args

    def run(self, job: Job, progress: Callable[[Job], None]) -> None:
        d = self.store.dir(job.id)
        out = d / "out"
        out.mkdir(exist_ok=True)
        runs = d / "runs"
        runs.mkdir(exist_ok=True)
        cmd = self.command(job, out / "report.md", runs)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", BCC_REVIEW_RUNS_DIR=str(runs))
        log_path = d / "run.log"
        shadow = copy.deepcopy(job)  # истинное состояние этапов; на экран — через _reveal (темп)
        self._last_reveal = 0.0
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(cmd, cwd=str(d), stdout=logf, stderr=subprocess.STDOUT, env=env, text=True)
            t0 = time.time()
            while proc.poll() is None:
                time.sleep(0.5)
                self._scan(shadow, runs, log_path)
                self._reveal(job, shadow)
                progress(job)
                if time.time() - t0 > self.timeout_s:
                    proc.kill()
                    job.error = f"Анализ не уложился в {int(self.timeout_s // 60)} мин и был остановлен."
                    break
        self._scan(shadow, runs, log_path)
        while self.pace and self._reveal(job, shadow):  # досмотреть этапы в темпе съёмки
            progress(job)
            time.sleep(0.2)
        self._reveal(job, shadow, force=True)
        report_json = self._find_report_json(d)
        if report_json:
            self._collect(job, report_json, out)
        fatal = job.summary.get("fatal", False)
        if "html" in job.files and not fatal:
            job.state = "done"  # отчёт есть — показываем, даже если модель подвела (об этом — job.notice)
            for k in job.stages:
                if job.stages[k] in ("pending", "running"):
                    job.stages[k] = "done" if (k == "report" or job.stages[k] == "running") else "skipped"
        else:
            job.state = "failed"
            if fatal and job.notice:
                job.error = job.notice + " Проверьте, что файл открывается и содержит текст, а не только скан страниц."
            elif not job.error:
                lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                bangs = [x.strip(" !") for x in lines if x.strip().startswith("!")]
                tail = bangs[:2] or lines[-4:]
                job.error = "Анализ завершился с ошибкой. " + (" ".join(tail)[-600:] if tail else "")
        progress(job)

    def _reveal(self, job: Job, shadow: Job, *, force: bool = False) -> bool:
        """Перенести состояние этапов с «истинного» на экран; с темпом — по одному шагу. True — ещё есть что показать."""
        job.log, job.stage_times = shadow.log, dict(shadow.stage_times)
        if not self.pace or force:
            job.stages.update(shadow.stages)
            return False
        order = [k for k, _ in STAGES if k not in ANSWER_STAGES or job.answers_path]
        final = ("done", "failed", "skipped")
        for k in order:
            if job.stages.get(k) in final:
                continue
            group = [x for x in order if x in PARALLEL] if k in PARALLEL else [k]
            if all(shadow.stages.get(g) in final for g in group):
                if time.time() - self._last_reveal < self.pace:
                    for g in group:  # пока ждём темпа — этап «идёт»
                        if job.stages.get(g) == "pending":
                            job.stages[g] = "running"
                    return True
                for g in group:
                    job.stages[g] = shadow.stages[g]
                self._last_reveal = time.time()
                nxt = next((x for x in order if job.stages.get(x) == "pending"), None)
                if nxt:
                    for g in ([x for x in order if x in PARALLEL] if nxt in PARALLEL else [nxt]):
                        job.stages[g] = "running"
                return True
            for g in group:
                if shadow.stages.get(g) == "running" and job.stages.get(g) == "pending":
                    job.stages[g] = "running"
            return False
        return False

    def _scan(self, job: Job, runs: Path, log_path: Path) -> None:
        now = round(time.time() - (job.started or time.time()), 1)
        order = [k for k, _ in STAGES if k not in ANSWER_STAGES or job.answers_path]

        def mark(st: str, state: str) -> None:
            if st in job.stages and job.stages[st] != state and job.stages[st] not in ("failed",):
                job.stages[st] = state
                if state in ("done", "failed"):
                    job.stage_times[st] = now

        try:
            log = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            log = []
        job.log = log[-40:]
        if any(line.startswith("Документ:") for line in log) or any(runs.glob("*/stages/*.json")):
            mark("docview", "done")
        for line in log:  # «  lens_qa: запуск» → идёт
            m = _LOG_STAGE.match(line)
            st = _norm_stage(m.group(1)) if m else None
            if st and m.group(2) == "запуск" and job.stages.get(st) == "pending":
                mark(st, "running")
        for p in runs.glob("*/stages/*.json"):  # файл этапа — этап завершён, статус внутри
            st = _norm_stage(p.stem)
            if not st:
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — файл ещё пишется
                continue
            mark(st, STATE_OF.get(rec.get("status", "ok"), "done"))
            if isinstance(rec.get("seconds"), (int, float)):  # длительность самого этапа, а не время от старта
                job.stage_times[st] = round(float(rec["seconds"]), 1)
        # этапы идут по порядку: всё до последнего завершённого последовательного этапа уже пройдено
        last = max((i for i, k in enumerate(order) if job.stages.get(k) in ("done", "failed", "skipped")
                    and k not in PARALLEL), default=-1)
        for k in order[:last]:
            if job.stages.get(k) in ("pending", "running"):
                mark(k, "skipped" if job.stages[k] == "pending" else "done")
        if not any(v == "running" for v in job.stages.values()):
            nxt = next((k for k in order if job.stages.get(k) == "pending"), None)
            if nxt:
                for k in ([x for x in order if x in PARALLEL and job.stages[x] == "pending"] if nxt in PARALLEL else [nxt]):
                    mark(k, "running")

    @staticmethod
    def _find_report_json(d: Path) -> Path | None:
        cands = [d / "out" / "report.json", *sorted(d.glob("out/*.json")), *sorted(d.glob("runs/*/report.json"))]
        return next((c for c in cands if c.is_file()), None)

    def _collect(self, job: Job, report_json: Path, out: Path) -> None:
        if report_json.parent != out:
            shutil.copy2(report_json, out / "report.json")
        try:
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        # каждый формат — ищем в out/ и в каталоге прогона; HTML при необходимости собираем сами
        names = {k: n for k, n, _, _ in FILES}
        d = out.parent
        for key, name in names.items():
            dst = out / name
            if dst.exists():
                continue
            ext = name.split(".", 1)[1]
            cand = next((p for p in [*d.glob(f"out/*.{ext}"), *d.glob(f"runs/*/report.{ext}")] if p.is_file()), None)
            if cand:
                shutil.copy2(cand, dst)
        if not (out / "report.html").exists():
            from bcc_review.v2.render import html as H
            try:
                view = H.load_view(job.input_path)
            except Exception:  # noqa: BLE001
                view = None
            H.write(report, view, out / "report.html")
        if not (out / "report.confluence.txt").exists():  # вики-разметка для «Вставить → Разметка» в Confluence
            try:
                from bcc_review.v2.render import confluence
                confluence.write(report, out / "report.confluence.txt")
            except Exception:  # noqa: BLE001 — выгрузка необязательна, отчёт уже есть
                pass
        job.files = {k: n for k, n, _, _ in FILES if (out / n).exists()}
        job.summary = _summary(report)
        job.notice = _notice(report)


def _notice(report: dict) -> str:
    run = report.get("run") or {}
    warns = [str(w) for w in run.get("warnings") or []]
    if run.get("provider") == "offline" and run.get("status") != "failed":
        return ("Проверка без модели: найдены только формальные дефекты по правилам (заглушки, единицы, коды ответов, "
                "язык). Противоречия по смыслу ищет модель — выберите провайдера с ключом.")
    if run.get("model_error"):
        return f"Модель недоступна — отчёт построен только правилами. {run['model_error']}"
    broken = next((w for w in warns if w.startswith("Прогон прерван")), "")
    if broken:
        return "Документ не удалось прочитать: " + broken.split(":", 1)[-1].strip()
    if run.get("status") == "failed":
        first = next((w for w in warns if w.startswith("Этап")), "")
        return ("Модель не ответила — отчёт неполный, вердикт не вынесен. " + first).strip()
    if run.get("status") == "partial":
        bad = [k for k, v in (run.get("stages") or {}).items() if v in ("failed", "partial")]
        return "Прогон неполный: не все этапы завершены" + (f" ({', '.join(bad)})" if bad else "") + " — вердикт не выше «с условиями»."
    return ""


def _summary(report: dict) -> dict[str, Any]:
    f = report.get("findings") or []
    v = report.get("verdict") or {}
    return {"critical": sum(1 for x in f if x.get("severity") == "critical"),
            "major": sum(1 for x in f if x.get("severity") == "major"),
            "minor": sum(1 for x in f if x.get("severity") == "minor"),
            "development": v.get("development", ""), "testing": v.get("testing", ""),
            "status": (report.get("run") or {}).get("status", ""),
            "model": ", ".join((report.get("run") or {}).get("models_used") or []),
            "fatal": not (report.get("document") or {}).get("lines") and (report.get("run") or {}).get("status") == "failed"}


class FixtureRunner(PipelineRunner):
    """Показ без pipeline: этапы идут по таймеру, отчёт — из готового report.json (только для демо и тестов)."""

    def __init__(self, store: JobStore, fixture: Path, *, step_s: float = 0.6):
        super().__init__(store)
        self.fixture = Path(fixture)
        self.step_s = step_s

    def run(self, job: Job, progress: Callable[[Job], None]) -> None:
        out = self.store.dir(job.id) / "out"
        out.mkdir(exist_ok=True)
        order = [k for k, _ in STAGES if k not in ANSWER_STAGES or job.answers_path]
        i = 0
        while i < len(order):
            k = order[i]
            group = [x for x in order[i:] if x in PARALLEL] if k in PARALLEL else [k]
            for g in group:
                job.stages[g] = "running"
            progress(job)
            time.sleep(self.step_s * (2 if k in PARALLEL else 1))
            for g in group:
                job.stages[g] = "done"
                job.stage_times[g] = round(time.time() - (job.started or time.time()), 1)
            i += len(group)
        report = json.loads(self.fixture.read_text(encoding="utf-8"))
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        self._collect(job, out / "report.json", out)
        job.state = "done"
        progress(job)


class Worker:
    """Одна очередь заданий: модель дорогая, параллельно гоняем не больше `workers` прогонов."""

    def __init__(self, store: JobStore, runner: PipelineRunner, workers: int = 1):
        self.store = store
        self.runner = runner
        self.sem = threading.Semaphore(workers)

    def submit(self, job: Job) -> None:
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job.id}").start()

    def _run(self, job: Job) -> None:
        with self.sem:
            job.state = "running"
            job.started = time.time()
            self.store.save(job)
            try:
                self.runner.run(job, self.store.save)
            except Exception as exc:  # noqa: BLE001
                job.state = "failed"
                job.error = f"Внутренняя ошибка веб-демо: {exc}"
            job.finished = time.time()
            self.store.save(job)
