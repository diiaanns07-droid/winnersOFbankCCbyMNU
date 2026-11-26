"""Синтетический медленный движок для проверки длинного запуска (№15).

Подключается в штатный слот веба, как общий движок::

    BCC_REVIEW_ENGINE=tests.p15.slow_engine:run_review python -m bcc_review.web

и получает только поля ``RunOptions`` — как настоящий ``run_review`` (колбэка ``progress``
у него нет, живые этапы веб читает из JSONL-трассы в ``artifacts_dir``).

Счётчик вызовов ведёт сам движок, независимо от веба: каждая обработка — строка
``start`` в ``$P15_SLOW_DIR/calls.jsonl`` (номер вызова, run_id, SHA-256 входа, pid) и
строка ``end`` с исходом. По нему тест сверяет «один запуск — одна обработка».

Переменные окружения:

* ``P15_SLOW_DIR``   — каталог счётчика (обязателен для подсчёта);
* ``P15_SLOW_DELAY`` — сколько секунд «думает» движок (по умолчанию 3);
* ``P15_SLOW_PLAN``  — исходы по номеру вызова через запятую, последний повторяется:
  ``complete`` (полный отчёт), ``partial`` (LLM недоступна → только правила, отчёт есть),
  ``network`` (техническая ошибка провайдера, отчёта нет), ``crash`` (исключение без kind).

Тело отчёта строит ``devengine`` (Report v1 с проверкой контракта); от движка здесь
важны длительность, исход и честный счётчик, а не качество замечаний.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from bcc_review.web import devengine

try:  # тот же класс ошибки, что поднимают адаптеры провайдеров (№11/№12)
    from bcc_review.contracts import ProviderError
except Exception:  # pragma: no cover - контракт есть в обеих ветках
    class ProviderError(Exception):  # type: ignore[no-redef]
        def __init__(self, kind: str, message: str = ""):
            super().__init__(message or kind)
            self.kind = kind

_lock = threading.Lock()
# Этапы и формат трассы — как у общего движка (bcc/integration, runtime/core.Tracer):
# run_start, call_ok внутри этапа с моделью, stage_end со статусом.
STAGES = ("read", "lint", "inventory", "cross", "evidence")
LLM_STAGES = ("cross",)


def _dir() -> Path | None:
    raw = os.environ.get("P15_SLOW_DIR")
    return Path(raw) if raw else None


def _append(record: dict[str, Any]) -> int:
    """Записать строку счётчика; вернуть номер вызова (1, 2, …) для строки start."""
    base = _dir()
    if base is None:
        return 0
    base.mkdir(parents=True, exist_ok=True)
    path = base / "calls.jsonl"
    with _lock:
        n = 0
        if path.is_file():
            n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if '"event": "start"' in line)
        if record.get("event") == "start":
            n += 1
            record = {"n": n, **record}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return n


def calls(base: Path) -> list[dict[str, Any]]:
    """Прочитать счётчик: строки start/end по порядку."""
    path = Path(base) / "calls.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def starts(base: Path) -> list[dict[str, Any]]:
    return [c for c in calls(base) if c.get("event") == "start"]


def _outcome(n: int) -> str:
    plan = [p.strip() for p in os.environ.get("P15_SLOW_PLAN", "complete").split(",") if p.strip()] or ["complete"]
    return plan[min(n, len(plan)) - 1] if n else plan[0]


def run_review(input_path: str, report_md: str, *, options: dict | None = None) -> dict:
    opts = dict(options or {})
    run_id = opts.get("run_id")
    data = Path(input_path).read_bytes()
    n = _append({"event": "start", "run_id": run_id, "input_sha256": hashlib.sha256(data).hexdigest(),
                 "pid": os.getpid(), "ts": time.time()})
    outcome = _outcome(n)
    delay = float(os.environ.get("P15_SLOW_DELAY", "3"))
    art = Path(opts.get("artifacts_dir") or Path(report_md).parent)
    art.mkdir(parents=True, exist_ok=True)
    trace = art / "trace.jsonl"

    def emit(event: str, **fields: Any) -> None:
        with open(trace, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "run_id": run_id, "event": event, **fields}, ensure_ascii=False) + "\n")

    try:
        emit("run_start", provider=opts.get("provider"))
        step = delay / len(STAGES)
        for stage in STAGES:
            if stage in LLM_STAGES:
                time.sleep(step / 2)
                if outcome == "network":
                    emit("call_error", stage=stage, kind="network")
                    raise ProviderError("network", "LLM-провайдер недоступен: соединение сброшено (синтетический сбой)")
                emit("call_ok", stage=stage)
                time.sleep(step / 2)
            else:
                time.sleep(step)
            if outcome == "crash" and stage == "evidence":
                raise RuntimeError("синтетическое падение движка")
            emit("stage_end", stage=stage, status="partial" if outcome == "partial" and stage in LLM_STAGES else "ok")
        dev_opts = {k: v for k, v in opts.items() if k in devengine.RUN_OPTION_KEYS}
        dev_opts["dev_scenario"] = "network" if outcome == "partial" else "ok"
        dev_opts["dev_delay"] = 0
        report = devengine.run_review(input_path, report_md, options=dev_opts)
    except BaseException as exc:
        _append({"event": "end", "n": n, "run_id": run_id, "outcome": outcome, "error": f"{type(exc).__name__}: {exc}", "ts": time.time()})
        raise
    _append({"event": "end", "n": n, "run_id": run_id, "outcome": outcome, "status": report["run"]["status"], "ts": time.time()})
    return report
