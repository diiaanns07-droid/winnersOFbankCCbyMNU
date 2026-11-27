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
from concurrent.futures import ThreadPoolExecutor
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
NEXT_MODEL = {"not_found", "overloaded", "quota"}
# После такой ошибки модель в этом прогоне больше не зовём. Сеть — тоже: сюда она доходит только после всех
# повторов (2+4+8+16+32 с), и иначе каждый следующий этап тратил бы бюджет вызовов на те же повторы.
FATAL = {"auth", "not_configured", "quota", "network"}
BACKOFF = (2, 4, 8, 16, 32)
MAX_TIMEOUT_RETRIES = 1
MAX_OUTPUT_CEILING = 32000  # выше лимит ответа не поднимаем: дальше — деление пакета  # таймаут claude -p — минуты; повторяем один раз
REPAIR_NOTE = ("\n\nПредыдущий ответ не прошёл проверку JSON Schema: {errors}\n"
               "Верни полный ответ заново строго по схеме.")


_TRUNC_MARKS = ("output token maximum", "max_tokens", "max output tokens", "maximum output tokens",
                "response exceeded", "обрезан")


def is_truncation(kind: str, message: str) -> bool:
    """Обрезка по лимиту ответа: вид ``truncated`` или текст ошибки CLI/API («exceeded the 16000 output token maximum»)."""
    msg = (message or "").lower()
    return kind == "truncated" or any(m in msg for m in _TRUNC_MARKS)


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
                 trace: Callable[[dict], None] | None = None, max_split_depth: int = 1,
                 stage_timeout_s: float = 0.0, rpm: float = 0.0,
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
        self.max_split_depth = max_split_depth  # не больше одного деления на этап: каскад делений съедает время
        self.stage_timeout_s = float(stage_timeout_s or 0)  # 0 — без лимита времени этапа
        # Темп запросов (RPM) — скользящее окно: не больше ``rpm`` запросов за любые 60 с. Раньше запросы
        # разносились на 60/rpm с, и при rpm=10 пять параллельных рецензентов стартовали с шагом 6 с (последний —
        # через 24 с); окно даёт тот же лимит без пауз, пока за минуту меньше ``rpm`` запросов (9 за прогон).
        self.rpm = int(float(rpm)) if rpm and float(rpm) >= 1 else 0
        self.min_interval_s = 60.0 / float(rpm) if rpm and float(rpm) > 0 else 0.0
        self._window: list[float] = []  # моменты старта запросов за последние 60 с
        self._stage_t0: dict[str, float] = {}
        self._sleep, self._clock = sleep, clock
        self._t0 = clock()
        self._lock = threading.Lock()
        self.stats: dict[str, Any] = {"calls": 0, "cached": 0, "failed": 0, "split": 0, "repaired": 0,
                                      "retries": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                                      "models_used": [], "seconds": 0.0, "by_stage": {}}
        self.fatal: LLMError | None = None  # первая фатальная ошибка провайдера (ключ, настройка, квота)
        self.responses: dict[str, list] = {}  # сырые ответы по этапам в порядке вызовов — для mock-фикстур

    def _record(self, stage: str, data: Any) -> None:
        with self._lock:
            self.responses.setdefault(stage, []).append(data)

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
            st = self._stage_stats(stage)
            if self.stats["calls"] >= self.max_calls:
                st["budget"] = st.get("budget", 0) + 1
                raise BudgetExceeded(stage, f"исчерпан бюджет вызовов модели ({self.max_calls})")
            if self.elapsed() > self.max_seconds:
                st["budget"] = st.get("budget", 0) + 1
                raise BudgetExceeded(stage, f"исчерпан бюджет времени прогона ({self.max_seconds:.0f} с)")
            t0 = self._stage_t0.setdefault(stage, self._clock())
            if self.stage_timeout_s and self._clock() - t0 > self.stage_timeout_s:
                st["budget"] = st.get("budget", 0) + 1
                raise BudgetExceeded(stage, f"исчерпан лимит времени этапа ({self.stage_timeout_s:.0f} с)")
            self.stats["calls"] += 1
            st["calls"] += 1
            wait = 0.0
            if self.min_interval_s:
                now = self._clock()
                if self.rpm:
                    self._window = [x for x in self._window if x > now - 60.0]
                    # слот: сейчас, если в окне меньше rpm запросов; иначе — когда из окна выйдет rpm-й с конца
                    slot = now if len(self._window) < self.rpm else self._window[-self.rpm] + 60.0
                    self._window.append(slot)
                    self._window.sort()
                else:  # меньше одного запроса в минуту — равные интервалы
                    slot = max(now, self._window[-1] + self.min_interval_s) if self._window else now
                    self._window = [slot]
                wait = max(0.0, slot - now)
        if wait > 0:
            self._emit({"stage": stage, "event": "rpm_wait", "seconds": round(wait, 1)})
            self._sleep(wait)

    def restart_stage_clock(self, stage: str) -> None:
        """Лимит времени этапа заново: поздний вызов вопросов после раннего (его часы шли вместе с судьёй)."""
        with self._lock:
            self._stage_t0.pop(stage, None)

    def call_timeout(self, stage: str) -> float:
        """Таймаут одного вызова: не больше остатка лимита времени этапа (но не меньше минуты)."""
        if not self.stage_timeout_s:
            return self.timeout_s
        left = self.stage_timeout_s - (self._clock() - self._stage_t0.get(stage, self._clock()))
        return max(60.0, min(self.timeout_s, left))

    def _invoke(self, stage: str, model: str | None, system: str, user: str, schema: dict,
                max_output_tokens: int) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self.provider.invoke(model=model, messages=messages, schema=schema, timeout_s=self.call_timeout(stage),
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

    def ask(self, stage: str, system: str, user: str, schema: dict, *, max_output_tokens: int = 16000,
            expand: bool = True) -> dict:
        """Один логический вызов: ответ, прошедший схему. Ошибки — ``LLMError`` / ``Truncated`` / ``BudgetExceeded``."""
        key = self._key(self.model, system, user, schema)
        cached = self._cache_get(key)
        if cached is not None and not schema_errors(cached.get("data"), schema):
            with self._lock:
                self.stats["cached"] += 1
                self._stage_stats(stage)["cached"] += 1
                m = cached.get("model")
                if m and m not in self.stats["models_used"]:
                    self.stats["models_used"].append(m)
            self._emit({"stage": stage, "cached": True, "model": cached.get("model"), "key": key[:16]})
            self._record(stage, cached["data"])
            return cached["data"]

        if self.fatal is not None:
            raise LLMError(stage, self.fatal.kind, "модель недоступна в этом прогоне: " + self.fatal.message)
        handles_retries = bool(getattr(self.provider, "handles_retries", False))
        chain = [self.model] + ([] if handles_retries else self.fallback_models)
        last: LLMError | None = None
        for model in chain:
            try:
                try:
                    data, result = self._ask_model(stage, model, system, user, schema, max_output_tokens,
                                                   handles_retries)
                except Truncated:
                    # этап, который не делит пакет сам, получает одну попытку с удвоенным лимитом ответа
                    if not expand or max_output_tokens >= MAX_OUTPUT_CEILING:
                        raise
                    max_output_tokens = min(max_output_tokens * 2, MAX_OUTPUT_CEILING)
                    with self._lock:
                        self.stats["expanded"] = self.stats.get("expanded", 0) + 1
                    self._emit({"stage": stage, "event": "expand_output", "max_output_tokens": max_output_tokens})
                    data, result = self._ask_model(stage, model, system, user, schema, max_output_tokens,
                                                   handles_retries)
            except (Truncated, BudgetExceeded):
                raise
            except LLMError as exc:
                last = exc
                if exc.kind in NEXT_MODEL and model != chain[-1]:
                    self._emit({"stage": stage, "event": "fallback_model", "from": model, "kind": exc.kind})
                    continue
                if exc.kind in FATAL:
                    with self._lock:
                        if self.fatal is None:
                            self.fatal = exc
                raise
            self._cache_put(key, {"data": data, "model": result.get("model"), "stage": stage})
            self._record(stage, data)
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
                if is_truncation(kind, str(msg)):
                    raise Truncated(stage, str(msg)) from None
                if kind == "invalid_output" and not repaired and not handles_retries:
                    # ответ пришёл, но не JSON / не по схеме на стороне провайдера (claude -p без structured_output):
                    # одна попытка починки, как для ошибок схемы ниже; Gemini (handles_retries) повторяет сам
                    repaired = True
                    with self._lock:
                        self.stats["repaired"] += 1
                    cur_user = user + REPAIR_NOTE.format(errors=str(msg)[:300])
                    continue
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
            # сначала одна попытка с удвоенным лимитом (у моделей с рассуждением деление не помогает), потом деление
            return self.ask(stage, system, user, schema, max_output_tokens=max_output_tokens, expand=_depth == 0)
        except Truncated:
            if len(items) < 2 or _depth >= self.max_split_depth:
                raise
            with self._lock:
                self.stats["split"] += 1
                self._stage_stats(stage)["split"] += 1
            # половинам — лимит, на котором споткнулся полный пакет (после расширения), иначе половина, которой мало
            # 32 000, снова получает 16 000 и обрезается гарантированно; половины идут параллельно
            limit = min(max_output_tokens * 2, MAX_OUTPUT_CEILING) if _depth == 0 else max_output_tokens
            self._emit({"stage": stage, "event": "split", "items": len(items), "depth": _depth + 1,
                        "max_output_tokens": limit})
            mid = len(items) // 2
            halves = (items[:mid], items[mid:])
            with ThreadPoolExecutor(max_workers=2) as pool:
                futs = [pool.submit(self.ask_split, stage, build, part, schema, merge, max_output_tokens=limit,
                                    _depth=_depth + 1) for part in halves]
                results: list[Any] = []
                for fut in futs:
                    try:
                        results.append(fut.result())
                    except LLMError as exc:  # Truncated, BudgetExceeded и прочие сбои одной половины
                        results.append(exc)
            ok = [r for r in results if not isinstance(r, LLMError)]
            if not ok:
                raise next(r for r in results if isinstance(r, LLMError))
            if len(ok) < len(results):
                # одна половина не удалась: этап получает ответ второй и помечается частичным (failed в статистике)
                with self._lock:
                    self.stats["failed"] += 1
                    self._stage_stats(stage)["failed"] += 1
                self._emit({"stage": stage, "event": "split_partial", "items": len(items), "depth": _depth + 1})
            return merge(ok)

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
