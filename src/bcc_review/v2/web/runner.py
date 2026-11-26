"""Запуск анализа для веб-демо: проверка провайдеров, задания, прогресс по этапам.

Анализ выполняет pipeline v2 отдельным процессом — ровно той же командой, что в README
(`python -m bcc_review ВХОД ОТЧЁТ.md --provider …`). Прогресс веб читает из каталога прогона
(`runs/<run_id>/stages/<этап>.json`, `trace.jsonl`), поэтому ему не нужен доступ к внутренностям
pipeline. Для тестов и показа без модели есть `FixtureRunner`: проигрывает этапы и собирает отчёт
из готового report.json.
"""
from __future__ import annotations

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

STAGES: list[tuple[str, str]] = [
    ("docview", "Чтение документа"),
    ("rules", "Правила"),
    ("segment", "Нарезка требований"),
    ("lens:analyst", "Аналитик"),
    ("lens:qa", "Тестировщик"),
    ("lens:architect", "Архитектор"),
    ("lens:risk", "Риски"),
    ("consistency", "Набор целиком"),
    ("judge", "Судья"),
    ("clarify", "Вопросы владельцу"),
    ("report", "Отчёт"),
]
PARALLEL = {"lens:analyst", "lens:qa", "lens:architect", "lens:risk", "consistency"}
STAGE_ALIASES = {"lens_analyst": "lens:analyst", "lens_qa": "lens:qa", "lens_architect": "lens:architect",
                 "lens_risk": "lens:risk", "analyst": "lens:analyst", "qa": "lens:qa", "architect": "lens:architect",
                 "risk": "lens:risk", "render": "report", "verdict": "report", "quotes": "judge"}

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm"}
MAX_UPLOAD = 20 * 1024 * 1024

FILES = [  # (ключ, имя файла в out/, подпись, mime)
    ("html", "report.html", "HTML", "text/html; charset=utf-8"),
    ("md", "report.md", "Markdown", "text/markdown; charset=utf-8"),
    ("json", "report.json", "JSON", "application/json"),
    ("docx", "report.docx", "Word", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("pdf", "report.pdf", "PDF", "application/pdf"),
    ("csv", "report.jira.csv", "Jira CSV", "text/csv; charset=utf-8"),
    ("revised", "report.revised.md", "Исправленное ТЗ", "text/markdown; charset=utf-8"),
]


# ─────────────────────────────── провайдеры ───────────────────────────────

def load_dotenv(path: Path = Path(".env")) -> None:
    """Прочитать .env (KEY=VALUE) без перезаписи уже заданных переменных."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def provider_status() -> list[dict[str, Any]]:
    """Какие провайдеры доступны прямо сейчас и почему нет, если нет."""
    env = os.environ
    have_claude = bool(shutil.which("claude"))
    gem = bool(env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY"))
    ant = bool(env.get("ANTHROPIC_API_KEY"))
    oai = bool(env.get("OPENAI_BASE_URL"))
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
    first = next((p["id"] for p in out[:4] if p["ok"]), "offline")
    label = next(p["label"] for p in out if p["id"] == first)
    out.insert(0, {"id": "auto", "label": f"Автовыбор: {label}", "ok": True, "note": "первый доступный провайдер",
                   "models": [], "resolved": first})
    return out


def check_provider(pid: str) -> str:
    """Пустая строка — можно запускать; иначе понятное сообщение для пользователя."""
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
    parent: str = ""                    # задание, на вопросы которого отвечали
    answers_path: str = ""              # файл ответов владельца (--answers)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("input_path", None)
        d["answers_path"] = bool(self.answers_path)
        d["log"] = self.log[-40:]
        d["elapsed"] = round((self.finished or time.time()) - (self.started or self.created), 1)
        d["stage_list"] = [{"id": k, "label": lbl, "state": self.stages.get(k, "pending"),
                            "parallel": k in PARALLEL} for k, lbl in STAGES]
        return d


class JobStore:
    """Задания в памяти + `job.json` на диске (чтобы список переживал перезапуск сервера)."""

    def __init__(self, root: Path):
        self.root = Path(root)
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
    """Запускает `python -m bcc_review ВХОД out/report.md` и следит за каталогом прогона."""

    def __init__(self, store: JobStore, *, extra_args: list[str] | None = None, timeout_s: float = 3600):
        self.store = store
        self.extra_args = list(extra_args or [])
        self.timeout_s = timeout_s

    def command(self, job: Job, out_md: Path, runs_dir: Path) -> list[str]:
        cmd = [sys.executable, "-m", "bcc_review", job.input_path, str(out_md), "--provider", job.provider]
        if job.model:
            cmd += ["--model", job.model]
        if job.answers_path:
            cmd += ["--answers", job.answers_path, "--revise"]
        cmd += ["--export", "html,json,docx,pdf,jira", "--runs-dir", str(runs_dir)]
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
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(cmd, cwd=str(d), stdout=logf, stderr=subprocess.STDOUT, env=env, text=True)
            t0 = time.time()
            while proc.poll() is None:
                time.sleep(0.7)
                self._scan(job, runs, log_path)
                progress(job)
                if time.time() - t0 > self.timeout_s:
                    proc.kill()
                    job.error = f"Анализ не уложился в {int(self.timeout_s // 60)} мин и был остановлен."
                    break
        self._scan(job, runs, log_path)
        report_json = self._find_report_json(d)
        if report_json:
            self._collect(job, report_json, out)
        if proc.returncode == 0 and "html" in job.files:
            job.state = "done"
            for k in job.stages:
                if job.stages[k] in ("pending", "running"):
                    job.stages[k] = "done" if k == "report" else ("skipped" if job.stages[k] == "pending" else "done")
        else:
            job.state = "failed"
            if not job.error:
                tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
                job.error = "Анализ завершился с ошибкой. " + (" ".join(tail)[-600:] if tail else "")
        progress(job)

    def _scan(self, job: Job, runs: Path, log_path: Path) -> None:
        done = set()
        for p in runs.glob("*/stages/*.json"):
            st = _norm_stage(p.stem)
            if st:
                done.add(st)
        for p in runs.glob("*/trace.jsonl"):
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
                    ev = json.loads(line)
                    st = _norm_stage(str(ev.get("stage", "")))
                    if not st:
                        continue
                    if ev.get("event") in ("stage_end", "end", "done") or ev.get("status") in ("ok", "partial"):
                        done.add(st)
                    elif job.stages.get(st) == "pending":
                        job.stages[st] = "running"
            except Exception:  # noqa: BLE001
                continue
        for st in done:
            if job.stages.get(st) != "done":
                job.stages[st] = "done"
                job.stage_times[st] = round(time.time() - (job.started or time.time()), 1)
        # следующий не начатый этап считаем идущим (линзы идут параллельно)
        order = [k for k, _ in STAGES]
        pending = [k for k in order if job.stages[k] == "pending"]
        if pending and not any(v == "running" for v in job.stages.values()):
            nxt = pending[0]
            group = [k for k in pending if k in PARALLEL] if nxt in PARALLEL else [nxt]
            for k in group:
                job.stages[k] = "running"
        try:
            job.log = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            pass

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
        job.files = {k: n for k, n, _, _ in FILES if (out / n).exists()}
        job.summary = _summary(report)


def _summary(report: dict) -> dict[str, Any]:
    f = report.get("findings") or []
    v = report.get("verdict") or {}
    return {"critical": sum(1 for x in f if x.get("severity") == "critical"),
            "major": sum(1 for x in f if x.get("severity") == "major"),
            "minor": sum(1 for x in f if x.get("severity") == "minor"),
            "development": v.get("development", ""), "testing": v.get("testing", ""),
            "status": (report.get("run") or {}).get("status", ""),
            "model": ", ".join((report.get("run") or {}).get("models_used") or [])}


class FixtureRunner(PipelineRunner):
    """Показ без pipeline: этапы идут по таймеру, отчёт — из готового report.json (только для демо и тестов)."""

    def __init__(self, store: JobStore, fixture: Path, *, step_s: float = 0.6):
        super().__init__(store)
        self.fixture = Path(fixture)
        self.step_s = step_s

    def run(self, job: Job, progress: Callable[[Job], None]) -> None:
        out = self.store.dir(job.id) / "out"
        out.mkdir(exist_ok=True)
        order = [k for k, _ in STAGES]
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
