"""Провайдер ``gemini`` для v2 (№02): Google Gemini с цепочкой моделей и повторами.

Обёртка над адаптером v1 ``bcc_review.providers.gemini.GeminiAdapter`` (там санитайзер схемы под
ограничения Gemini, классификация ошибок API и строгая проверка ответа: ``finish_reason=STOP``, JSON,
полная JSON Schema). Адаптер v1 делает ровно один запрос к одной модели; здесь сверху — политика
надёжности, которой v1 не хватало на живых прогонах (404 у ``gemini-2.5-flash``, 503 у ``gemini-3.8-flash``):

* модель по умолчанию ``gemini-3.8-flash`` (``GEMINI_MODEL``), затем цепочка ``GEMINI_FALLBACK_MODELS``
  (по умолчанию ``gemini-3.6-flash,gemini-3.5-flash-lite``);
* 503/500/504/перегрузка/тайм-аут — до 3 повторов с паузой 2, 5, 10 с, затем следующая модель;
* 404 (модель снята или недоступна ключу) и квота (дневная, нулевая) — сразу следующая модель,
  и до конца прогона эта модель больше не вызывается;
* 429 (минутный лимит) — ждём Retry-After из ответа (не дольше ``GEMINI_MAX_RATE_WAIT_S``, 65 с),
  до 2 раз, затем следующая модель;
* нет сети — 2 повтора, затем ошибка (другая модель не поможет);
* неверный ключ, плохой запрос, отказ фильтром, обрезанный ответ — сразу наверх: повтор не поможет,
  а обрезку (``truncated``) ``LLMClient`` лечит делением пакета.

``max_output_tokens`` — 32 000 (``GEMINI_MAX_OUTPUT_TOKENS``). Рассуждения — умеренные: для Gemini 3
``thinking_level=medium``, для 2.x ``thinking_budget=4096`` (``GEMINI_THINKING_LEVEL`` /
``GEMINI_THINKING_BUDGET``, ``off`` — не передавать). Если модель отвергла настройку рассуждений (400),
запрос повторяется без неё. Фактическая модель (``model_version`` ответа) возвращается в ``model`` и
попадает в паспорт прогона; попытки — в ``meta.attempts``.

Провайдер сам повторяет временные ошибки (``handles_retries = True``): ``LLMClient`` не должен
повторять их ещё раз поверх.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from bcc_review.contracts import ProviderError

__all__ = ["DEFAULT_FALLBACKS", "DEFAULT_MODEL", "GeminiProvider", "settings"]

PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_FALLBACKS = ("gemini-3.6-flash", "gemini-3.5-flash-lite")
DEFAULT_MAX_OUTPUT_TOKENS = 32000
DEFAULT_THINKING_LEVEL = "medium"   # Gemini 3.x
DEFAULT_THINKING_BUDGET = 4096      # Gemini 2.x
RETRY_DELAYS_S = (2.0, 5.0, 10.0)   # 503/500/504/overloaded/timeout
NETWORK_DELAYS_S = (2.0, 5.0)
RATE_WAITS = 2
RETRY_SLACK_S = 120.0               # запас времени на повторы сверх таймаута вызова
DEFAULT_MAX_RATE_WAIT_S = 65.0
DEFAULT_CONCURRENCY = 4
KEY_HELP = "Бесплатный ключ: https://aistudio.google.com/apikey — добавьте в .env строку GEMINI_API_KEY=<ключ>."

TRANSIENT = frozenset({"overloaded", "server", "timeout"})
NEXT_MODEL = frozenset({"not_found", "quota"})
_OFF = ("off", "none", "no", "0", "false", "disable", "disabled")


def _models(raw: str | Iterable[str] | None) -> list[str]:
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    out: list[str] = []
    for item in items:
        item = (item or "").strip().removeprefix("models/")
        if item and item not in out:
            out.append(item)
    return out


def _num(env: Mapping[str, str], name: str, default: float | None) -> float | None:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ProviderError("not_configured", f"{name}={raw!r}: ожидается число.") from None


def settings(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Настройки из окружения (значение ключа наружу не выводится)."""
    env = os.environ if env is None else env
    raw_fb = env.get("GEMINI_FALLBACK_MODELS")
    fallbacks = list(DEFAULT_FALLBACKS) if raw_fb is None else (
        [] if raw_fb.strip().lower() in _OFF else _models(raw_fb))
    return {
        "api_key": (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip() or None,
        "model": (env.get("GEMINI_MODEL") or "").strip().removeprefix("models/") or DEFAULT_MODEL,
        "fallback_models": fallbacks,
        "max_output_tokens": int(_num(env, "GEMINI_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS) or 0)
        or DEFAULT_MAX_OUTPUT_TOKENS,
        "thinking_level": (env.get("GEMINI_THINKING_LEVEL") or "").strip().lower() or None,
        "thinking_budget": (env.get("GEMINI_THINKING_BUDGET") or "").strip().lower() or None,
        "temperature": _num(env, "GEMINI_TEMPERATURE", None),
        "max_rate_wait_s": float(_num(env, "GEMINI_MAX_RATE_WAIT_S", DEFAULT_MAX_RATE_WAIT_S) or 0),
        "concurrency": int(_num(env, "GEMINI_CONCURRENCY", DEFAULT_CONCURRENCY) or DEFAULT_CONCURRENCY),
        "total_timeout_s": _num(env, "GEMINI_TOTAL_TIMEOUT_S", None),
    }


def thinking_for(model: str, level: str | None, budget: str | None) -> dict[str, Any]:
    """Параметры рассуждений для модели: ``{"thinking_level": ...}`` или ``{"thinking_budget": ...}`` или ``{}``."""
    if (level or "") in _OFF or (budget or "") in _OFF:
        return {}
    if budget:
        try:
            return {"thinking_budget": int(float(budget))}
        except ValueError:
            raise ProviderError("not_configured", f"GEMINI_THINKING_BUDGET={budget!r}: ожидается число токенов.") from None
    if level:
        return {"thinking_level": level}
    if model.startswith("gemini-3"):
        return {"thinking_level": DEFAULT_THINKING_LEVEL}
    if model.startswith("gemini-2.5"):
        return {"thinking_budget": DEFAULT_THINKING_BUDGET}
    return {}


def _with_schema_text(messages: list[dict[str, Any]], schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Схема ответа текстом в системном сообщении (режим без response_json_schema)."""
    import json
    hint = ("Ответ — только один JSON-объект строго по этой JSON Schema, без пояснений и без markdown:\n"
            + json.dumps(schema, ensure_ascii=False))
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            m["content"] = f"{m.get('content') or ''}\n\n{hint}"
            return out
    return [{"role": "system", "content": hint}, *out]


def _us_pacific_offset_h(utc: "datetime.datetime") -> int:
    """Смещение тихоокеанского времени США от UTC: −7 летом (2-е воскресенье марта — 1-е воскресенье ноября), −8 зимой.

    Без zoneinfo: на Windows без пакета tzdata база часовых поясов недоступна.
    """
    import datetime as dt

    def sunday(year: int, month: int, nth: int) -> dt.datetime:
        d = dt.datetime(year, month, 1)
        d += dt.timedelta(days=(6 - d.weekday()) % 7 + 7 * (nth - 1))
        return d

    y = utc.year
    start = sunday(y, 3, 2).replace(hour=10)   # 02:00 PST = 10:00 UTC
    end = sunday(y, 11, 1).replace(hour=9)     # 02:00 PDT = 09:00 UTC
    naive = utc.replace(tzinfo=None)
    return -7 if start <= naive < end else -8


def daily_reset_local(now_utc: "datetime.datetime | None" = None) -> str:
    """Когда сбросится дневная квота Gemini (полночь по тихоокеанскому времени США) — в местном времени машины."""
    import datetime as dt
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    off = _us_pacific_offset_h(now)
    pacific = now + dt.timedelta(hours=off)
    midnight = (pacific + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    reset_utc = (midnight - dt.timedelta(hours=_us_pacific_offset_h(midnight - dt.timedelta(hours=off))))
    reset_utc = reset_utc.replace(tzinfo=dt.timezone.utc)
    local = reset_utc.astimezone()
    day = "сегодня" if local.date() == now.astimezone().date() else "завтра"
    return f"{local:%H:%M} {day} по местному времени (полночь по тихоокеанскому времени США)"


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _describe(kind: str, status: Any) -> str:
    names = {"overloaded": "перегружена", "server": "сбой сервера", "timeout": "тайм-аут", "network": "нет сети",
             "not_found": "недоступна ключу (404)", "quota": "квота исчерпана", "rate_limit": "лимит запросов (429)",
             "auth": "ключ отклонён", "bad_request": "запрос отклонён", "refusal": "отказ фильтром",
             "truncated": "ответ обрезан", "invalid_output": "ответ не по схеме", "not_configured": "не настроено"}
    text = names.get(kind, kind)
    return f"{text}, HTTP {status}" if status and str(status) not in text else text


class GeminiProvider:
    """Gemini с цепочкой моделей. ``adapter_factory(model, thinking)`` и ``sleep`` подменяются в тестах.

    ``adapter_factory(model, thinking, schema_mode="native"|"text")`` возвращает объект с методом
    ``invoke(model=, messages=, schema=, timeout_s=, max_output_tokens=)`` в формате адаптера v1
    (успех — dict, ошибка — ``ProviderError``). ``schema_mode="text"`` — запрос без ``response_json_schema``
    (только JSON), схема передаётся текстом в системном промпте, ответ проверяется локально по полной схеме.
    """

    name = PROVIDER
    handles_retries = True

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 fallback_models: Iterable[str] | str | None = None, env: Mapping[str, str] | None = None,
                 adapter_factory: Callable[[str, dict[str, Any]], Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 retry_delays: Sequence[float] = RETRY_DELAYS_S, network_delays: Sequence[float] = NETWORK_DELAYS_S,
                 max_rate_wait_s: float | None = None, max_output_tokens: int | None = None,
                 concurrency: int | None = None) -> None:
        cfg = settings(env)
        self._api_key = api_key or cfg["api_key"]
        self.default_model = (model or cfg["model"]).strip().removeprefix("models/")
        self.fallback_models = _models(fallback_models) if fallback_models is not None else cfg["fallback_models"]
        self.max_output_tokens = int(max_output_tokens or cfg["max_output_tokens"])
        self.thinking_level = cfg["thinking_level"]
        self.thinking_budget = cfg["thinking_budget"]
        self.temperature = cfg["temperature"]
        self.max_rate_wait_s = float(cfg["max_rate_wait_s"] if max_rate_wait_s is None else max_rate_wait_s)
        self.total_timeout_s = cfg["total_timeout_s"]
        self.retry_delays = tuple(retry_delays)
        self.network_delays = tuple(network_delays)
        self._factory = adapter_factory or self._v1_adapter
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._gate = threading.BoundedSemaphore(max(1, int(concurrency or cfg["concurrency"])))
        self._adapters: dict[tuple[str, tuple], Any] = {}
        self._dead: dict[str, ProviderError] = {}       # модели, отключённые до конца прогона (404, квота)
        self._no_thinking: set[str] = set()              # модели, отвергшие настройку рассуждений
        self._text_schema: set[str] = set()              # модели, отвергшие схему ответа (слишком сложная)

    # ------------------------------------------------------------------ adapters

    def _v1_adapter(self, model: str, thinking: dict[str, Any], schema_mode: str = "native") -> Any:
        if not self._api_key:
            raise ProviderError("not_configured", f"Не задан GEMINI_API_KEY. {KEY_HELP}", model=model)
        from bcc_review.providers.gemini import GeminiAdapter
        cls = GeminiAdapter
        if schema_mode == "text":
            class TextSchemaAdapter(GeminiAdapter):
                def _schema_bundle(self, schema: Mapping[str, Any]) -> Any:
                    wire, log, validator = super()._schema_bundle(schema)
                    return None, [*log, {"path": "/", "keyword": "*", "action": "schema sent as text"}], validator
            cls = TextSchemaAdapter
        return cls(api_key=self._api_key, model=model, fallback_models=[], min_attempt_s=1.0,
                   temperature=self.temperature, max_output_tokens=self.max_output_tokens,
                   thinking_budget=thinking.get("thinking_budget"), thinking_level=thinking.get("thinking_level"))

    def _adapter(self, model: str) -> tuple[Any, dict[str, Any], str]:
        thinking = {} if model in self._no_thinking else thinking_for(model, self.thinking_level, self.thinking_budget)
        mode = "text" if model in self._text_schema else "native"
        key = (model, tuple(sorted(thinking.items())), mode)
        with self._lock:
            if key not in self._adapters:
                self._adapters[key] = (self._factory(model, thinking, schema_mode=mode) if mode == "text"
                                       else self._factory(model, thinking))
            return self._adapters[key], thinking, mode

    def model_chain(self, model: str | None = None) -> list[str]:
        return _models([(model or "").strip() or self.default_model, *self.fallback_models])

    def reset(self) -> None:
        """Забыть модели, отключённые в этом прогоне."""
        with self._lock:
            self._dead.clear()
            self._no_thinking.clear()

    # ------------------------------------------------------------------ invoke

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float, max_output_tokens: int | None = None, **_: Any) -> dict[str, Any]:
        chain = self.model_chain(model)
        per_call = max(5.0, float(timeout_s or 300))
        # Бюджет всего invoke: таймаут вызывающего (LLMClient уже ограничил его остатком лимита этапа) + запас на
        # быстрые повторы (503, Retry-After). Зависший запрос не растянет этап втрое.
        total = float(self.total_timeout_s) if self.total_timeout_s else per_call + RETRY_SLACK_S
        deadline = self._clock() + total
        attempts: list[dict[str, Any]] = []
        last: ProviderError | None = None
        # лимит этапа — не ниже лимита провайдера: у Gemini рассуждения расходуют тот же лимит
        max_tokens = max(int(max_output_tokens or 0), self.max_output_tokens)
        clean = [{"role": m.get("role"), "content": m.get("content")} for m in messages]

        for current in chain:
            dead = self._dead.get(current)
            if dead is not None:
                attempts.append({"model": current, "skipped": dead.kind})
                last = last or dead
                continue
            transient = network = rate = 0
            while True:
                remaining = deadline - self._clock()
                if remaining < 5:
                    raise self._final(last or ProviderError("timeout", f"Бюджет времени вызова Gemini ({total:.0f} с) "
                                                                       "исчерпан.", model=current), chain, attempts)
                try:
                    adapter, thinking, mode = self._adapter(current)
                except ProviderError as exc:
                    raise self._final(exc, chain, attempts) from None
                started = self._clock()
                sent = _with_schema_text(clean, schema) if mode == "text" else clean
                try:
                    with self._gate:
                        result = adapter.invoke(model=current, messages=sent, schema=schema,
                                                timeout_s=min(per_call, remaining), max_output_tokens=max_tokens)
                except ProviderError as exc:
                    last = exc
                    kind = exc.kind
                    attempts.append({"model": current, "kind": kind, "status": exc.status,
                                     "retry_after_s": exc.retry_after_s, "seconds": round(self._clock() - started, 2)})
                    if kind in NEXT_MODEL:
                        self._dead[current] = exc
                        break
                    if kind in TRANSIENT:
                        if transient < len(self.retry_delays):
                            self._sleep(self.retry_delays[transient])
                            transient += 1
                            continue
                        break
                    if kind == "rate_limit":
                        wait = exc.retry_after_s
                        if wait is None:
                            wait = self.retry_delays[min(rate, len(self.retry_delays) - 1)] * 2
                        if rate < RATE_WAITS and wait <= self.max_rate_wait_s and deadline - self._clock() > wait + 5:
                            self._sleep(wait + 0.5)
                            rate += 1
                            continue
                        break
                    if kind == "network":
                        if network < len(self.network_delays):
                            self._sleep(self.network_delays[network])
                            network += 1
                            continue
                        raise self._final(exc, chain, attempts) from None
                    low = (exc.message or "").lower()
                    if kind == "bad_request" and thinking and "think" in low:
                        self._no_thinking.add(current)
                        continue
                    if kind == "bad_request" and mode == "native" and ("schema" in low or "too many states" in low):
                        self._text_schema.add(current)
                        continue
                    raise self._final(exc, chain, attempts) from None
                out = self._normalize(result, chain, current, attempts, thinking)
                out["meta"]["schema_mode"] = mode
                return out
        assert last is not None
        raise self._final(last, chain, attempts, exhausted=True)

    # ------------------------------------------------------------------ results

    def _normalize(self, result: Mapping[str, Any], chain: list[str], called: str, attempts: list[dict[str, Any]],
                   thinking: Mapping[str, Any]) -> dict[str, Any]:
        u = result.get("usage") or {}
        out_tokens = _int(u.get("output_tokens"))
        think = _int(u.get("thinking_tokens"))
        usage = {"input_tokens": _int(u.get("input_tokens")), "output_tokens": out_tokens + think,
                 "thinking_tokens": think, "cache_read_input_tokens": _int(u.get("cache_read_input_tokens"))}
        meta = dict(result.get("meta") or {})
        actual = str(result.get("model") or called)
        meta.update({"provider": PROVIDER, "requested_model": chain[0], "called_model": called,
                     "fallback_used": called != chain[0], "attempts": attempts, "model_chain": chain,
                     "thinking": dict(thinking),
                     "physical_calls": 1 + sum(1 for a in attempts if "kind" in a)})
        stop = str(result.get("stop_reason") or "STOP").upper()
        return {"data": result.get("data"), "usage": usage, "model": actual,
                "request_id": str(result.get("request_id") or ""),
                "stop_reason": "max_tokens" if stop == "MAX_TOKENS" else "end_turn", "meta": meta}

    def _final(self, exc: ProviderError, chain: list[str], attempts: list[dict[str, Any]],
               exhausted: bool = False) -> ProviderError:
        """Ошибка наружу: исходный kind, понятное сообщение, история попыток."""
        message = exc.message or exc.kind
        if exhausted and len(chain) > 1:
            tried: dict[str, list[str]] = {}
            for a in attempts:
                tried.setdefault(a["model"], []).append(_describe(a.get("kind") or a.get("skipped") or "?", a.get("status")))
            parts = [f"{m}: {', '.join(sorted(set(v)))}" + (f" ×{len(v)}" if len(v) > 1 else "")
                     for m, v in tried.items()]
            message = (f"Все модели Gemini из цепочки недоступны ({'; '.join(parts)}). Последняя ошибка: {message} "
                       "Задайте другую модель (GEMINI_MODEL, GEMINI_FALLBACK_MODELS) — список моделей ключа: "
                       "python -m bcc_review doctor.")
        subkind = getattr(exc, "subkind", None)
        if exc.kind == "quota" and (subkind == "per_day" or "дневн" in message.lower() or "perday" in message.lower()):
            subkind = "per_day"
            if "восстановится" not in message:
                message = f"{message} Квота восстановится около {daily_reset_local()}."
        err = ProviderError(exc.kind, message, retry_after_s=exc.retry_after_s, status=exc.status,
                            request_id=exc.request_id, usage=exc.usage, model=exc.model)
        err.subkind = subkind  # type: ignore[attr-defined]
        err.attempts = attempts  # type: ignore[attr-defined]
        err.physical_calls = sum(1 for a in attempts if "kind" in a)  # type: ignore[attr-defined]
        err.model_chain = chain  # type: ignore[attr-defined]
        err.provider = PROVIDER  # type: ignore[attr-defined]
        return err

    # ------------------------------------------------------------------ doctor

    def list_models(self) -> list[dict[str, Any]]:
        """Модели ключа с generateContent (``models.list``)."""
        adapter, _, _ = self._adapter(self.default_model)
        if not hasattr(adapter, "list_models"):
            return []
        return adapter.list_models()
