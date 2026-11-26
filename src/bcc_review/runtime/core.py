"""Инфраструктура прогона: атомарная запись, бюджет, кэш, трасса и учёт этапов для паспорта."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..contracts import BudgetExhausted, canonical_json, sha256_bytes

CACHE_FORMAT = "bcc-cache/1"


# --------------------------------------------------------------------------- атомарная запись
def atomic_write_text(path: str | Path, text: str) -> Path:
    """Запись через временный файл в том же каталоге и ``os.replace``: читатель видит старую или новую версию."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write_json(path: str | Path, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- бюджет
class Budget:
    """Общий бюджет прогона: физические вызовы (включая повторы), секунды, токены."""

    def __init__(self, max_calls: int, max_seconds: float, max_tokens: Optional[int] = None,
                 clock=time.monotonic):
        self.max_calls = max_calls
        self.max_seconds = max_seconds
        self.max_tokens = max_tokens
        self._clock = clock
        self.started = clock()
        self.calls = 0
        self.tokens = 0
        self.exhausted_reason: Optional[str] = None

    def elapsed(self) -> float:
        return self._clock() - self.started

    def remaining_s(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed())

    def check(self, stage: str) -> None:
        reason = None
        if self.calls >= self.max_calls:
            reason = f"исчерпан лимит вызовов модели ({self.max_calls})"
        elif self.remaining_s() <= 0:
            reason = f"исчерпан бюджет времени ({self.max_seconds:.0f} с)"
        elif self.max_tokens is not None and self.tokens >= self.max_tokens:
            reason = f"исчерпан бюджет токенов ({self.max_tokens})"
        if reason:
            self.exhausted_reason = self.exhausted_reason or reason
            raise BudgetExhausted(stage, reason)

    def note_call(self) -> None:
        self.calls += 1

    def note_tokens(self, n: int) -> None:
        self.tokens += max(0, int(n or 0))

    def to_dict(self) -> dict[str, Any]:
        return {"max_calls": self.max_calls, "max_seconds": self.max_seconds, "max_tokens": self.max_tokens,
                "exhausted": self.exhausted_reason is not None, "reason": self.exhausted_reason}


# --------------------------------------------------------------------------- кэш
class Cache:
    """Кэш ответов модели по содержимому. Ключ включает провайдера, запрошенную и фактическую модель,
    этап, версию контракта, хеш промпта, хеш схемы, хеш входа и параметры вызова."""

    def __init__(self, root: Optional[str | Path], enabled: bool = True):
        self.root = Path(root) if root else None
        self.enabled = bool(enabled and self.root)
        self._aliases: dict[str, str] = {}
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)
            alias_file = self.root / "model_aliases.json"
            if alias_file.exists():
                try:
                    self._aliases = json.loads(alias_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    self._aliases = {}

    def resolve_model(self, provider: str, model: str) -> str:
        """Фактическая модель, которой в прошлый раз ответил провайдер на запрос ``model``."""
        return self._aliases.get(f"{provider}:{model}", model)

    def note_model(self, provider: str, requested: str, actual: Optional[str]) -> None:
        if not self.enabled or not actual:
            return
        key = f"{provider}:{requested}"
        if self._aliases.get(key) != actual:
            self._aliases[key] = actual
            atomic_write_json(self.root / "model_aliases.json", self._aliases)

    @staticmethod
    def make_key(**parts: Any) -> str:
        return sha256_bytes(canonical_json({"format": CACHE_FORMAT, **parts}).encode("utf-8"))

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        p = self._path(key)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        if self.enabled:
            atomic_write_json(self._path(key), value)


# --------------------------------------------------------------------------- трасса
class Tracer:
    """Безопасная JSONL-трасса: только служебные поля, без текста документа и ключей."""

    SAFE_FIELDS = {"stage", "event", "status", "duration_s", "model", "input_tokens", "output_tokens",
                   "kind", "retry_after_s", "attempt", "cache_key", "reason", "calls", "implementation",
                   "provider", "requested_model", "delay_s", "count", "request_id"}

    def __init__(self, path: Optional[str | Path], run_id: str):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> None:
        if not self.path:
            return
        rec = {"ts": utc_now(), "run_id": self.run_id, "event": event}
        for k, v in fields.items():
            if k in self.SAFE_FIELDS and v is not None:
                if isinstance(v, str) and len(v) > 300:
                    v = v[:300] + "…"
                rec[k] = v
        with self._lock, open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- учёт этапов
@dataclass
class StageRecord:
    name: str
    status: str = "ok"
    calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    models: list[str] = field(default_factory=list)
    reason: Optional[str] = None
    duration_s: float = 0.0
    implementation: Optional[str] = None
    llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = {"name": self.name, "status": self.status, "calls": self.calls, "cache_hits": self.cache_hits,
             "retries": self.retries, "model": self.models[-1] if self.models else None, "reason": self.reason,
             "duration_s": round(self.duration_s, 3), "input_tokens": self.input_tokens,
             "output_tokens": self.output_tokens}
        if self.implementation:
            d["implementation"] = self.implementation
        return d


class StageStats:
    """Счётчики для паспорта: числа берутся из фактических вызовов, а не из плана."""

    def __init__(self) -> None:
        self.stages: dict[str, StageRecord] = {}
        self._lock = threading.Lock()

    @staticmethod
    def base(stage: str) -> str:
        return stage.split("#", 1)[0]

    def get(self, stage: str) -> StageRecord:
        name = self.base(stage)
        with self._lock:
            if name not in self.stages:
                self.stages[name] = StageRecord(name)
            return self.stages[name]

    def call(self, stage: str, *, ok: bool, usage: Optional[dict] = None, model: Optional[str] = None,
             retry: bool = False) -> None:
        rec = self.get(stage)
        rec.llm = True
        rec.calls += 1
        if retry:
            rec.retries += 1
        if not ok:
            rec.failed_calls += 1
        usage = usage or {}
        rec.input_tokens += int(usage.get("input_tokens") or 0)
        rec.output_tokens += int(usage.get("output_tokens") or 0)
        rec.cache_read_tokens += int(usage.get("cache_read_input_tokens") or usage.get("cache_read") or 0)
        if model and model not in rec.models:
            rec.models.append(model)

    def cache_hit(self, stage: str, model: Optional[str]) -> None:
        rec = self.get(stage)
        rec.llm = True
        rec.cache_hits += 1
        if model and model not in rec.models:
            rec.models.append(model)

    def mark(self, stage: str, status: str, reason: Optional[str] = None, *,
             implementation: Optional[str] = None, duration_s: Optional[float] = None) -> StageRecord:
        rec = self.get(stage)
        order = {"ok": 0, "cached": 0, "skipped": 1, "partial": 2, "failed": 3}
        # итоговый статус этапа — худший из отмеченных
        if order.get(status, 0) >= order.get(rec.status, 0):
            rec.status = status
            if reason:
                rec.reason = reason
        elif reason and not rec.reason:
            rec.reason = reason
        if implementation:
            rec.implementation = implementation
        if duration_s is not None:
            rec.duration_s += duration_s
        return rec

    def totals(self) -> dict[str, Any]:
        recs = list(self.stages.values())
        models: list[str] = []
        for r in recs:
            for m in r.models:
                if m not in models:
                    models.append(m)
        return {
            "physical": sum(r.calls for r in recs),
            "cache_hits": sum(r.cache_hits for r in recs),
            "failed": sum(r.failed_calls for r in recs),
            "retries": sum(r.retries for r in recs),
            "input": sum(r.input_tokens for r in recs),
            "output": sum(r.output_tokens for r in recs),
            "cache_read": sum(r.cache_read_tokens for r in recs),
            "models": models,
            "llm_ok": any(r.llm and r.status in ("ok", "cached", "partial") and (r.calls - r.failed_calls + r.cache_hits) > 0
                          for r in recs),
        }
