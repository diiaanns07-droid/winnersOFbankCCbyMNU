"""Клиент модели v2: проверка схемы, повторы, запасные модели, кэш, трасса, бюджет, деление обрезанных ответов.

Интерфейс (CONTRACT.md, раздел 3)::

    llm.ask(stage, system, user, schema, max_output_tokens=16000) -> dict
    llm.ask_split(stage, build, items, schema, merge) -> dict

Провайдер — любой объект с ``invoke(*, model, messages, schema, timeout_s, max_output_tokens=None, **kw)``
(``providers/*``). Ошибки провайдера — ``bcc_review.contracts.ProviderError``.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:
    from bcc_review.contracts import ProviderError
except Exception:  # pragma: no cover - v1 всегда рядом, но v2 не должен падать без него
    class ProviderError(Exception):  # type: ignore[no-redef]
        def __init__(self, kind: str, message: str = "", **kw: Any):
            super().__init__(message or kind)
            self.kind, self.message = kind, message or kind
            self.retry_after_s = kw.get("retry_after_s")

TRANSIENT = {"rate_limit", "overloaded", "server", "timeout", "network"}
NEXT_MODEL = {"not_found", "overloaded", "quota"}  # после повторов — следующая модель цепочки
BACKOFF = (2, 4, 8, 16, 32)
MAX_TIMEOUT_RETRIES = 1  # таймаут claude -p — минуты; повторяем один раз
REPAIR_NOTE = ("\n\nПредыдущий ответ не прошёл проверку JSON Schema: {errors}\n"
               "Верни полный ответ заново строго по схеме.")


class LLMError(Exception):
    """Вызов не удался после повторов. ``kind`` — вид ошибки провайдера."""

    def __init__(self, stage: str, kind: str, message: str):
        super().__init__(f"{stage}: {kind}: {message}")
        self.stage, self.kind, self.message = stage, kind, message


class Truncated(LLMError):
    """Ответ обрезан по лимиту выходных токенов — сигнал для ``ask_split``."""

    def __init__(self, stage: str, message: str = "ответ обрезан по лимиту выходных токенов"):
        super().__init__(stage, "truncated", message)


class BudgetExceeded(LLMError):
    """Исчерпан бюджет вызовов или времени прогона."""

    def __init__(self, stage: str, message: str):
        super().__init__(stage, "budget", message)


def _validator(schema: dict):
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return None
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema)


def schema_errors(data: Any, schema: dict, limit: int = 5) -> list[str]:
    v = _validator(schema)
    if v is None:
        return []
    out = []
    for e in v.iter_errors(data):
        path = "/".join(str(p) for p in e.absolute_path) or "(корень)"
        out.append(f"{path}: {e.message[:200]}")
        if len(out) >= limit:
            break
    return out


class LLMClient:
    def __init__(self, provider: Any, *, model: str | None = None, provider_name: str = "",
                 fallback_models: Sequence[str] = (), max_calls: int = 16, max_seconds: float = 1500.0,
                 max_retries: int = 5, timeout_s: float = 600.0, cache_dir: str | Path | None = None,
                 trace: Callable[[dict], None] | None = None, max_split_depth: int = 3,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.provider_name = provider_name or getattr(provider, "name", "") or type(provider).__name__
        self.model = model
        self.fallback_models = [m for m in fallback_models if m and m != model]
        self.max_calls = int(max_calls)
        self.max_seconds = float(max_seconds)
        self.max_retries = int(max_retries)
        self.timeout_s = float(timeout_s)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.trace = trace
        self.max_split_depth = max_split_depth
        self._sleep, self._clock = sleep, clock
        self._t0 = clock()
        self._lock = threading.Lock()
        self.stats: dict[str, Any] = {"calls": 0, "cached": 0, "failed": 0, "split": 0, "repaired": 0,
                                      "retries": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                                      "models_used": [], "seconds": 0.0, "by_stage": {}}

    # ------------------------------------------------------------------ служебное

    def _stage_stats(self, stage: str) -> dict:
        return self.stats["by_stage"].setdefault(stage, {"calls": 0, "cached": 0, "failed": 0, "split": 0,
                                                         "tokens_in": 0, "tokens_out": 0, "seconds": 0.0})

    def _emit(self, record: dict) -> None:
        if self.trace:
            try:
                self.trace(record)
            except Exception:  # noqa: BLE001 — трасса не роняет прогон
                pass

    def _key(self, model: str | None, system: str, user: str, schema: dict) -> str:
        blob = json.dumps([self.provider_name, model or "", system, user, schema], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Any:
        if not self.cache_dir:
            return None
        p = self.cache_dir / f"{key}.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _cache_put(self, key: str, payload: dict) -> None:
        if not self.cache_dir:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_dir / f"{key}.tmp{threading.get_ident()}"
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_dir / f"{key}.json")
        except OSError:
            pass

    def elapsed(self) -> float:
        return self._clock() - self._t0

    def _take_call(self, stage: str) -> None:
        with self._lock:
            if self.stats["calls"] >= self.max_calls:
                raise BudgetExceeded(stage, f"исчерпан бюджет вызовов модели ({self.max_calls})")
            if self.elapsed() > self.max_seconds:
                raise BudgetExceeded(stage, f"исчерпан бюджет времени прогона ({self.max_seconds:.0f} с)")
            self.stats["calls"] += 1
            self._stage_stats(stage)["calls"] += 1

    def _invoke(self, stage: str, model: str | None, system: str, user: str, schema: dict,
                max_output_tokens: int) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self.provider.invoke(model=model, messages=messages, schema=schema, timeout_s=self.timeout_s,
                                    max_output_tokens=max_output_tokens, stage=stage)

    def _account(self, stage: str, result: dict, seconds: float) -> None:
        usage = result.get("usage") or {}
        tin = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        tout = int(usage.get("output_tokens") or 0)
        cost = result.get("cost_usd")
        if cost is None:
            cost = usage.get("cost_usd")
        with self._lock:
            st = self._stage_stats(stage)
            self.stats["tokens_in"] += tin
            self.stats["tokens_out"] += tout
            st["tokens_in"] += tin
            st["tokens_out"] += tout
            st["seconds"] = round(st["seconds"] + seconds, 2)
            self.stats["seconds"] = round(self.stats["seconds"] + seconds, 2)
            if cost:
                self.stats["cost_usd"] = round(self.stats["cost_usd"] + float(cost), 6)
            used = (result.get("meta") or {}).get("models_used") or [result.get("model")]
            for m in used:
                if m and m not in self.stats["models_used"]:
                    self.stats["models_used"].append(m)

    # ------------------------------------------------------------------ публичное

    def ask(self, stage: str, system: str, user: str, schema: dict, *, max_output_tokens: int = 16000) -> dict:
        """Один логический вызов: ответ, прошедший схему. Ошибки — ``LLMError`` / ``Truncated`` / ``BudgetExceeded``."""
        key = self._key(self.model, system, user, schema)
        cached = self._cache_get(key)
        if cached is not None and not schema_errors(cached.get("data"), schema):
            with self._lock:
                self.stats["cached"] += 1
                self._stage_stats(stage)["cached"] += 1
            self._emit({"stage": stage, "cached": True, "model": cached.get("model"), "key": key[:16]})
            return cached["data"]

        handles_retries = bool(getattr(self.provider, "handles_retries", False))
        chain = [self.model] + ([] if handles_retries else self.fallback_models)
        last: LLMError | None = None
        for model in chain:
            try:
                data, result = self._ask_model(stage, model, system, user, schema, max_output_tokens, handles_retries)
            except (Truncated, BudgetExceeded):
                raise
            except LLMError as exc:
                last = exc
                if exc.kind in NEXT_MODEL and model != chain[-1]:
                    self._emit({"stage": stage, "event": "fallback_model", "from": model, "kind": exc.kind})
                    continue
                raise
            self._cache_put(key, {"data": data, "model": result.get("model"), "stage": stage})
            return data
        raise last or LLMError(stage, "unknown", "нет модели для вызова")

    def _ask_model(self, stage: str, model: str | None, system: str, user: str, schema: dict,
                   max_output_tokens: int, handles_retries: bool) -> tuple[Any, dict]:
        attempt = 0
        timeouts = 0
        repaired = False
        cur_user = user
        while True:
            self._take_call(stage)
            t0 = self._clock()
            try:
                result = self._invoke(stage, model, system, cur_user, schema, max_output_tokens)
            except ProviderError as exc:
                seconds = self._clock() - t0
                kind = getattr(exc, "kind", "unknown")
                msg = getattr(exc, "message", str(exc))
                self._account(stage, {"usage": getattr(exc, "usage", None) or {}}, seconds)
                self._emit({"stage": stage, "model": model, "error": kind, "message": str(msg)[:300],
                            "seconds": round(seconds, 1), "attempt": attempt})
                if kind == "truncated":
                    raise Truncated(stage, str(msg)) from None
                retry = (kind in TRANSIENT and not handles_retries and attempt < self.max_retries
                         and not (kind == "timeout" and timeouts >= MAX_TIMEOUT_RETRIES))
                if retry:
                    timeouts += kind == "timeout"
                    delay = getattr(exc, "retry_after_s", None) or BACKOFF[min(attempt, len(BACKOFF) - 1)]
                    attempt += 1
                    with self._lock:
                        self.stats["retries"] += 1
                    self._sleep(min(float(delay), 60.0))
                    continue
                with self._lock:
                    self.stats["failed"] += 1
                    self._stage_stats(stage)["failed"] += 1
                raise LLMError(stage, kind, str(msg)) from None
            except (BudgetExceeded, LLMError):
                raise
            except Exception as exc:  # noqa: BLE001 — неожиданная ошибка провайдера = неудачный вызов
                with self._lock:
                    self.stats["failed"] += 1
                    self._stage_stats(stage)["failed"] += 1
                self._emit({"stage": stage, "model": model, "error": "unknown",
                            "message": f"{type(exc).__name__}: {exc}"[:300]})
                raise LLMError(stage, "unknown", f"{type(exc).__name__}: {exc}") from None

            seconds = self._clock() - t0
            self._account(stage, result, seconds)
            if result.get("stop_reason") == "max_tokens":
                self._emit({"stage": stage, "model": result.get("model"), "error": "truncated",
                            "seconds": round(seconds, 1)})
                raise Truncated(stage)
            data = result.get("data")
            errors = schema_errors(data, schema)
            self._emit({"stage": stage, "model": result.get("model") or model, "seconds": round(seconds, 1),
                        "usage": result.get("usage"), "cost_usd": result.get("cost_usd"),
                        "schema_errors": errors[:3], "attempt": attempt, "repair": repaired})
            if not errors:
                return data, result
            if repaired:
                with self._lock:
                    self.stats["failed"] += 1
                    self._stage_stats(stage)["failed"] += 1
                raise LLMError(stage, "invalid_output", "ответ не прошёл схему: " + "; ".join(errors[:3]))
            repaired = True
            with self._lock:
                self.stats["repaired"] += 1
            cur_user = user + REPAIR_NOTE.format(errors="; ".join(errors))

    def ask_split(self, stage: str, build: Callable[[list], tuple[str, str]], items: list, schema: dict,
                  merge: Callable[[list], dict], *, max_output_tokens: int = 16000, _depth: int = 0) -> dict:
        """Запрос по пакету ``items``; если ответ обрезан — пакет делится пополам (бюджет вызовов общий).

        ``build(items) -> (system, user)``, ``merge([ответы]) -> ответ``. Делится не глубже ``max_split_depth``.
        """
        items = list(items)
        system, user = build(items)
        try:
            return self.ask(stage, system, user, schema, max_output_tokens=max_output_tokens)
        except Truncated:
            if len(items) < 2 or _depth >= self.max_split_depth:
                raise
            with self._lock:
                self.stats["split"] += 1
                self._stage_stats(stage)["split"] += 1
            self._emit({"stage": stage, "event": "split", "items": len(items), "depth": _depth + 1})
            mid = len(items) // 2
            parts = [self.ask_split(stage, build, part, schema, merge, max_output_tokens=max_output_tokens,
                                    _depth=_depth + 1) for part in (items[:mid], items[mid:])]
            return merge(parts)

    def summary(self) -> dict:
        s = self.stats
        return {"calls": {"total": s["calls"], "cached": s["cached"], "failed": s["failed"], "split": s["split"]},
                "tokens": {"input": s["tokens_in"], "output": s["tokens_out"]},
                "cost_usd": round(s["cost_usd"], 4), "models_used": list(s["models_used"])}


def merge_lists(parts: Iterable[dict]) -> dict:
    """Слияние частей ответа: списки складываются, строки — первая непустая."""
    out: dict[str, Any] = {}
    for p in parts:
        for k, v in (p or {}).items():
            if isinstance(v, list):
                out.setdefault(k, []).extend(v)
            elif isinstance(v, dict):
                cur = out.setdefault(k, {})
                if isinstance(cur, dict):
                    for kk, vv in v.items():
                        if isinstance(vv, list):
                            cur.setdefault(kk, []).extend(vv)
                        else:
                            cur.setdefault(kk, vv)
            else:
                if not out.get(k):
                    out[k] = v
    return out
