"""Связка веб-слоя с общим движком ``run_review``.

Веб не содержит своей логики качества и своего клиента LLM: он вызывает
``run_review(input_path, report_md, *, options=None)`` из общего пакета и
читает то, что движок записал на диск (OUTPUT.md + соседний OUTPUT.json).

Что веб кладёт в ``options`` (имена полей ``bcc_review.contracts.RunOptions``;
``RunOptions.coerce`` отвергает незнакомые ключи, поэтому лишнего веб не шлёт):

* ``provider``       — если задан при запуске сервера или найден только ключ Gemini;
* ``offline_lint``   — True, если ключа нет или пользователь выбрал «только правила»;
* ``exports``        — по умолчанию ("html",): артефакт №13;
* ``answers_path``   — answers.md редакции (повторная проверка с ответами, №08);
* ``compare_path``   — report.json родительской редакции (diff №09);
* ``run_id``, ``parent_run_id`` — идентификаторы веб-слоя, попадают в run паспорта;
* ``artifacts_dir``  — каталог артефактов запуска.

``progress`` (callable(stage, state, detail)) и ``tmp_dir`` передаются, только если
их объявил ``RunOptions`` (предложение для Max) или подключён dev-движок. Без них этапы
во время работы берутся из JSONL-трассы движка в каталоге артефактов, а после
завершения — из ``report.run.stages``.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import statistics
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .store import RunStore, parse_ts, utcnow

AUTO_CANDIDATES = (
    "bcc_review:run_review",          # contracts/HANDOFF.md, строка №15
    "bcc_review.engine:run_review",
)
# Параметры run_review, которые веб заполняет сам (имена — поля RunOptions из bcc_review.contracts).
WEB_OPTION_KEYS = ("provider", "offline_lint", "exports", "answers_path", "compare_path", "run_id", "parent_run_id", "artifacts_dir", "mock_script", "cache_dir")
# Расширения веб-слоя: передаются, только если движок их объявил (RunOptions) или это dev-движок.
EXTRA_OPTION_KEYS = ("progress", "tmp_dir")

PROVIDER_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


@dataclass
class EngineSpec:
    name: str  # "shared" | "dev" | "custom"
    target: str
    func: Callable[..., Any] | None
    version: str | None = None
    error: str | None = None
    tried: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.func is not None

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "target": self.target, "version": self.version}


def _load_target(target: str) -> Callable[..., Any]:
    mod_name, _, attr = target.partition(":")
    module = importlib.import_module(mod_name)
    func = getattr(module, attr or "run_review")
    if not callable(func):
        raise TypeError(f"{target} не вызываемый объект")
    return func


def _package_version() -> str | None:
    try:
        import bcc_review  # type: ignore

        return getattr(bcc_review, "__version__", None)
    except Exception:  # pragma: no cover
        return None


def resolve_engine(spec: str = "auto") -> EngineSpec:
    spec = spec or "auto"
    if spec == "dev":
        from . import devengine

        return EngineSpec("dev", "bcc_review.web.devengine:run_review", devengine.run_review, devengine.AGENT_VERSION)
    if spec != "auto":
        try:
            return EngineSpec("custom", spec, _load_target(spec), _package_version())
        except Exception as exc:
            return EngineSpec("custom", spec, None, error=f"{type(exc).__name__}: {exc}", tried=[spec])
    env_target = os.environ.get("BCC_REVIEW_ENGINE")
    candidates = ((env_target,) if env_target else ()) + AUTO_CANDIDATES
    errors = []
    for target in candidates:
        try:
            func = _load_target(target)
        except Exception as exc:
            errors.append(f"{target}: {type(exc).__name__}: {exc}")
            continue
        if func.__module__.startswith("bcc_review.web"):
            continue  # никогда не подхватывать dev-движок молча
        if target.startswith("bcc_review:") and importlib.util.find_spec("bcc_review.engine") is None:
            errors.append(f"{target}: объявлен, но модуль bcc_review.engine ещё не влит в ветку")
            continue
        return EngineSpec("shared", target, func, _package_version(), tried=list(candidates))
    return EngineSpec(
        "shared",
        "не найден",
        None,
        error="Общий движок run_review не найден. Проверено: " + "; ".join(errors),
        tried=list(candidates),
    )


# --------------------------------------------------------------------------- preflight
def load_dotenv(path: Path) -> list[str]:
    """Подхватить .env, не перетирая уже заданные переменные. Значения не логируются."""
    loaded = []
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ and value:
            os.environ[key] = value
            loaded.append(key)
    return loaded


_PLACEHOLDER_MARKERS = ("your_", "_here", "changeme", "xxx")


def _key_present(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return bool(value) and not any(m in value.lower() for m in _PLACEHOLDER_MARKERS)


def preflight(provider: str | None, engine: EngineSpec) -> dict[str, Any]:
    """Предварительная проверка ключа. Фактический режим всё равно берётся из отчёта."""
    if engine.name == "dev":
        return {"provider": "mock", "key_present": True, "key_names": [], "offline": False, "note": "dev-движок: ключ не нужен"}
    if provider == "mock":
        return {"provider": "mock", "key_present": True, "key_names": [], "offline": False,
                "note": "mock-провайдер движка: синтетические ответы модели, ключ не нужен"}
    providers = [provider] if provider else list(PROVIDER_KEYS)
    found = []
    for p in providers:
        for name in PROVIDER_KEYS.get(p, ()):
            if _key_present(name):
                found.append((p, name))
    names = [n for p in providers for n in PROVIDER_KEYS.get(p, ())]
    if found:
        return {"provider": provider or found[0][0], "key_present": True, "key_names": [found[0][1]], "offline": False, "note": f"ключ {found[0][1]} найден"}
    return {
        "provider": provider,
        "key_present": False,
        "key_names": names,
        "offline": True,
        "note": "ключ не найден (" + " / ".join(names) + "): будет выполнена только проверка по правилам",
    }


# --------------------------------------------------------------------------- runner
def classify_error(exc: BaseException) -> dict[str, Any]:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    kind_attr = str(getattr(exc, "kind", "") or "")  # ProviderError / AskError из bcc_review.contracts
    if kind_attr in ("auth", "not_configured"):
        kind, next_step = "missing_key", "offline"
    elif kind_attr in ("rate_limit", "overloaded", "server", "timeout", "network", "quota", "budget_exhausted"):
        kind, next_step = "network", "retry"
    elif "api_key" in lowered or "apikey" in lowered or "api key" in lowered or "ключ" in lowered:
        kind, next_step = "missing_key", "offline"
    elif any(w in lowered for w in ("connection", "timeout", "network", "503", "429", "unavailable")):
        kind, next_step = "network", "retry"
    else:
        kind, next_step = "engine_error", "retry"
    message = str(exc).strip() or type(exc).__name__
    return {"kind": kind, "type": type(exc).__name__, "message": message[:2000], "next_step": next_step}


def read_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "report.json не создан"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"report.json не читается: {exc}"
    if not isinstance(data, dict) or "run" not in data:
        return None, "report.json не похож на Report v1 (нет поля run)"
    return data, None


class Runner:
    """Очередь запусков. Состояние живёт в файлах, поток только исполняет."""

    def __init__(self, store: RunStore, engine: EngineSpec, *, workers: int = 1):
        self.store = store
        self.engine = engine
        self.pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="bcc-run")
        self._active: set[str] = set()
        self._guard = threading.Lock()
        self.engine_calls = 0  # сколько раз этот процесс вызвал run_review (для проверки «ноль запусков»)

    def submit(self, run_id: str) -> None:
        with self._guard:
            if run_id in self._active:
                return
            self._active.add(run_id)
        self.pool.submit(self._execute, run_id)

    def is_active(self, run_id: str) -> bool:
        with self._guard:
            return run_id in self._active

    def queue_position(self, run_id: str) -> int:
        """Сколько запусков ждут впереди (0 — уже исполняется или очереди нет)."""
        waiting = [r for r in self.store.list_runs() if r.get("status") == "started"]
        waiting.sort(key=lambda r: r.get("created_at") or "")
        ids = [r["run_id"] for r in waiting]
        return ids.index(run_id) if run_id in ids else 0

    def measured_eta(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """Оценка только по реально измеренным прогонам того же движка и режима."""
        offline = bool((run.get("options") or {}).get("offline_lint"))
        durations = self.store.measured_durations((run.get("engine") or {}).get("name"), offline)
        if not durations:
            return None
        return {"median_s": statistics.median(durations), "samples": len(durations)}

    def _execute(self, run_id: str) -> None:
        try:
            self._execute_inner(run_id)
        finally:
            with self._guard:
                self._active.discard(run_id)

    def _execute_inner(self, run_id: str) -> None:
        store = self.store
        rec = store.load(run_id)
        t0 = time.monotonic()
        store.update(run_id, status="running", started_at=utcnow(), stage=None)
        store.append_event(run_id, {"stage": "engine", "state": "start", "detail": self.engine.target})

        def progress(stage: str, state: str = "done", detail: str | None = None, **_: Any) -> None:
            try:
                store.append_event(run_id, {"stage": str(stage), "state": str(state), "detail": detail})
                if state in ("start", "running"):
                    store.update(run_id, stage=str(stage))
                elif state in ("done", "skip") and store.load(run_id).get("stage") == str(stage):
                    store.update(run_id, stage=None)  # сбой после этого места не припишется завершённому этапу
            except Exception:  # прогресс не должен ронять прогон
                pass

        inp = store.input_path(run_id)
        options = {k: v for k, v in (rec.get("options") or {}).items() if k in WEB_OPTION_KEYS}
        if rec.get("answers"):
            options["answers_path"] = str(store.input_dir(run_id) / rec["answers"]["file"])
        if rec.get("parent_run_id"):
            parent_json = store.report_json(rec["parent_run_id"])
            if parent_json.is_file():
                options["compare_path"] = str(parent_json)
            options["parent_run_id"] = rec["parent_run_id"]
        options["run_id"] = run_id
        options["artifacts_dir"] = str(store.artifacts_dir(run_id))
        extras = {"progress": progress, "tmp_dir": str(store.tmp_dir(run_id))}
        accepted = engine_option_fields(self.engine)
        dropped = []
        for k, v in extras.items():
            if accepted is None or k in accepted:
                options[k] = v
            else:
                dropped.append(k)
        if accepted is not None:
            for k in [k for k in options if k not in accepted]:
                dropped.append(k)
                options.pop(k)
        store.update(run_id, engine_options=sorted(k for k in options if k != "progress"), engine_options_dropped=sorted(dropped))

        error = None
        ret = None
        try:
            if self.engine.func is None:
                raise RuntimeError(self.engine.error or "движок недоступен")
            with self._guard:
                self.engine_calls += 1
            ret = self.engine.func(str(inp), str(store.report_md(run_id)), options=options)
        except BaseException as exc:  # noqa: BLE001 — SystemExit из CLI-кода тоже ошибка запуска
            error = classify_error(exc)
            error["trace_tail"] = traceback.format_exc(limit=3)[-1500:]
            failed_stage = store.load(run_id).get("stage") or "engine"  # этап, на котором упал движок
            store.append_event(run_id, {"stage": failed_stage, "state": "fail", "detail": error["message"]})

        report, report_problem = read_report(store.report_json(run_id))
        if report is None and isinstance(ret, dict) and "run" in ret and error is None:
            report_problem = (report_problem or "") + "; движок вернул Report, но не записал report.json"

        run_meta = (report or {}).get("run") or {}
        warnings = []
        if report is None:
            status = "failed"
            if error is None:
                error = {"kind": "no_report", "type": "", "message": report_problem or "движок завершился без отчёта", "next_step": "retry"}
        else:
            status = run_meta.get("status") if run_meta.get("status") in ("complete", "partial", "failed") else "partial"
            if run_meta.get("status") not in ("complete", "partial", "failed"):
                warnings.append(f"В report.json неизвестный run.status={run_meta.get('status')!r}; показываем как partial")
            if error is not None:
                status = "partial"  # отчёт есть, но движок упал после записи
                warnings.append(f"Отчёт записан, но движок завершился ошибкой: {error['message']}")

        store.cleanup_tmp(run_id)
        duration = round(time.monotonic() - t0, 3)
        summary = None
        if report is not None:
            summary = {
                "mode": run_meta.get("mode"),
                "provider": run_meta.get("provider"),
                "model": run_meta.get("model"),
                "calls": run_meta.get("calls"),
                "agent_version": run_meta.get("agent_version"),
                "source_sha256": run_meta.get("source_sha256"),
                "document_sha256": (report.get("document") or {}).get("id"),
                "report_status": run_meta.get("status"),
            }
        store.append_event(run_id, {"stage": "engine", "state": "fail" if status == "failed" else "done", "detail": status})
        store.update(
            run_id,
            status=status,
            stage=None,
            finished_at=utcnow(),
            duration_s=duration,
            error=error,
            warnings=warnings,
            report=summary,
            artifacts=store.list_artifacts(run_id),
        )


def elapsed_s(run: dict[str, Any]) -> float | None:
    start = parse_ts(run.get("started_at"))
    if not start:
        return None
    end = parse_ts(run.get("finished_at"))
    from datetime import datetime, timezone

    return round(((end or datetime.now(timezone.utc)) - start).total_seconds(), 1)


def accepts_options(func: Callable[..., Any]) -> bool:
    try:
        return "options" in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover
        return True


def engine_option_fields(engine: EngineSpec) -> set[str] | None:
    """Какие ключи options примет движок. None — принимает всё (dev-движок)."""
    if engine.name == "dev":
        return None
    try:
        from bcc_review.contracts import RunOptions  # type: ignore

        return set(RunOptions.__dataclass_fields__)
    except Exception:
        return set(WEB_OPTION_KEYS)


_TRACE_STATE = {
    "start": "start", "started": "start", "running": "start", "begin": "start",
    "ok": "done", "done": "done", "cached": "done", "end": "done", "finished": "done",
    "partial": "done", "skipped": "skip", "skip": "skip",
    "failed": "fail", "fail": "fail", "error": "fail",
}


def trace_events(artifacts_dir: Path, limit_bytes: int = 2_000_000) -> list[dict[str, Any]]:
    """Этапы из JSONL-трассы движка (RunOptions.trace) — живой статус без колбэка.

    Берём строки с полем этапа (stage|name) и состояния (status|state|event);
    остальное в трассе (вызовы модели и т. п.) пропускаем. Тексты документа не читаем.
    """
    out: list[dict[str, Any]] = []
    if not artifacts_dir.is_dir():
        return out
    for path in sorted(artifacts_dir.rglob("*.jsonl")):
        if "trace" not in path.name or path.stat().st_size > limit_bytes:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            stage = obj.get("stage") or obj.get("name")
            event = str(obj.get("event") or "")
            if event in ("call_ok", "call_error", "call_invalid", "cache_hit", "retry"):
                state = "start"  # вызовы модели внутри этапа: этап идёт
            elif event and event not in ("stage_start", "stage_end", "stage"):
                continue  # run_start/run_end и прочее — не этапы
            else:
                state = _TRACE_STATE.get(str(obj.get("status") or obj.get("state") or event).lower())
            if stage and state:
                out.append({"ts": obj.get("ts") or obj.get("time"), "stage": str(stage), "state": state, "detail": obj.get("reason"), "source": "trace"})
    return out
