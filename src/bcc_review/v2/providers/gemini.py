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

``max_output_tokens`` — потолок модели из профиля (2.5 и 3.x — 65 536; ``GEMINI_MAX_OUTPUT_TOKENS``),
если API отверг лимит — 32 768, затем 8 192. Рассуждения — умеренные: для Gemini 3
``thinking_level=medium``, для 2.x ``thinking_budget=4096`` (``GEMINI_THINKING_LEVEL`` /
``GEMINI_THINKING_BUDGET``, ``off`` — не передавать). Если модель отвергла настройку рассуждений (400),
запрос повторяется без неё. Фактическая модель (``model_version`` ответа) возвращается в ``model`` и
попадает в паспорт прогона; попытки — в ``meta.attempts``.

Провайдер сам повторяет временные ошибки (``handles_retries = True``): ``LLMClient`` не должен
повторять их ещё раз поверх.

Третья волна (замер — ``tests/v2/test_02_wallclock.py``, модель времени прогона):

* параллельность по умолчанию 5 — все четыре линзы и набор идут разом (при 4 пятый этап ждал свободного
  места и удлинял прогон на 40–45 с);
* темп — скользящее окно запросов в минуту **по каждой модели** (``GEMINI_RPM``, по умолчанию из профиля:
  Flash 10, Flash-Lite 15): запрос ждёт, только если в последние 60 с к этой модели ушло уже столько
  запросов. Квоты Google считаются по модели, поэтому запасная модель окна основной не ждёт
  (``paces_requests = True`` — фиксированный шаг ``--rpm`` поверх не нужен);
* пустой ответ, ответ не JSON, нечитаемый ответ, необычный ``finish_reason`` — один повтор на той же модели,
  затем следующая модель цепочки: «молча пустых» ответов наверх нет;
* ответ не по схеме возвращается как есть: ``LLMClient`` один раз просит модель исправить его по списку
  нарушений (раньше этап сразу падал без попытки починки);
* рассуждения по этапам — из профиля модели (``profiles.py``);
* перегрузка в часы пик: если у модели исчерпаны повторы 503, следующие 10 минут она пробуется один раз без
  пауз, при 503 — сразу запасная (модель времени: основная перегружена весь прогон — 8,5 → 6,5 мин, вместо 45
  запросов 21). Успешный ответ снимает «охлаждение».
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, Mapping, Sequence

from bcc_review.contracts import ProviderError

from . import profiles

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
COOL_S = 600.0                      # после исчерпанных повторов 503: столько секунд модель — одна попытка без пауз
DEFAULT_MAX_RATE_WAIT_S = 65.0
DEFAULT_CONCURRENCY = 5             # 4 линзы + набор идут разом (модель времени: при 4 прогон дольше на 40–45 с)
RATE_WINDOW_S = 60.0
KEY_HELP = "Бесплатный ключ: https://aistudio.google.com/apikey — добавьте в .env строку GEMINI_API_KEY=<ключ>."

TRANSIENT = frozenset({"overloaded", "server", "timeout"})
NEXT_MODEL = frozenset({"not_found", "quota"})
# «Пустой» ответ модели (нет текста, не JSON, нечитаемый, необычный finish_reason): один повтор, затем другая модель
EMPTY_SUBKINDS = frozenset({"empty_candidates", "empty_text", "not_json", "unreadable_response"})
EMPTY_RETRIES = 1
_OFF = ("off", "none", "no", "0", "false", "disable", "disabled")


def is_empty_answer(exc: ProviderError) -> bool:
    """Ответ пришёл, но пользы в нём нет: повтор обычно помогает (известная болезнь моделей с рассуждением)."""
    if exc.kind != "invalid_output":
        return False
    sub = str(getattr(exc, "subkind", "") or "")
    return sub in EMPTY_SUBKINDS or (sub.startswith("finish_") and sub != "finish_stop")


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
        "max_output_tokens": int(_num(env, "GEMINI_MAX_OUTPUT_TOKENS", 0) or 0) or None,   # None — по профилю модели
        "thinking_level": (env.get("GEMINI_THINKING_LEVEL") or "").strip().lower() or None,
        "thinking_budget": (env.get("GEMINI_THINKING_BUDGET") or "").strip().lower() or None,
        "temperature": _num(env, "GEMINI_TEMPERATURE", None),
        "max_rate_wait_s": float(_num(env, "GEMINI_MAX_RATE_WAIT_S", DEFAULT_MAX_RATE_WAIT_S) or 0),
        "concurrency": int(_num(env, "GEMINI_CONCURRENCY", 0) or 0) or None,   # None — по профилю модели
        "total_timeout_s": _num(env, "GEMINI_TOTAL_TIMEOUT_S", None),
        "rpm": _num(env, "GEMINI_RPM", None),   # None — по профилю модели; 0 — без окна
    }


def thinking_for(model: str, level: str | None, budget: str | None, stage: str = "") -> dict[str, Any]:
    """Параметры рассуждений для модели: ``{"thinking_level": ...}`` или ``{"thinking_budget": ...}`` или ``{}``.

    Явные ``GEMINI_THINKING_LEVEL`` / ``GEMINI_THINKING_BUDGET`` важнее профиля; без них — профиль модели и этапа.
    """
    if (level or "") in _OFF or (budget or "") in _OFF:
        return {}
    if budget:
        try:
            return {"thinking_budget": int(float(budget))}
        except ValueError:
            raise ProviderError("not_configured", f"GEMINI_THINKING_BUDGET={budget!r}: ожидается число токенов.") from None
    if level:
        return {"thinking_level": level}
    return profiles.gemini_thinking(model, stage)


def _with_schema_text(messages: list[dict[str, Any]], schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Схема ответа текстом в конце последнего сообщения user (режим без response_json_schema).

    Не в системном промпте: системный промпт и начало сообщения (документ, требования) одинаковы у всех
    этапов — это общий префикс для неявного кэша Gemini; схема у каждого этапа своя и идёт последней.
    """
    import json
    hint = ("Ответ — только один JSON-объект строго по этой JSON Schema, без пояснений и без markdown:\n"
            + json.dumps(schema, ensure_ascii=False))
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m.get("role") == "user":
            m["content"] = f"{m.get('content') or ''}\n\n{hint}"
            return out
    return [*out, {"role": "user", "content": hint}]


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


def _is_output_limit_error(low: str) -> bool:
    """400 из-за слишком большого max_output_tokens (модель старше 2.5)."""
    return any(m in low for m in ("max_output_tokens", "maxoutputtokens", "max output tokens", "output token"))


def _attempt_note(a: Mapping[str, Any]) -> str:
    """Короткая запись попытки для трассы: «gemini-3.8-flash 503», «gemini-3.8-flash ждал окно 12 с»."""
    if "rpm_wait_s" in a:
        return f"{a.get('model')} ждал окно {a['rpm_wait_s']} с"
    if "skipped" in a:
        return f"{a.get('model')} пропущена ({a['skipped']})"
    what = a.get("subkind") or a.get("kind") or "?"
    status = f" {a['status']}" if a.get("status") else ""
    return f"{a.get('model')}{status} {what}".strip()


class _PassValidator:
    """Валидатор без нарушений: адаптер v1 отдаёт ответ, проверку по схеме делает ``LLMClient`` (с починкой)."""

    def iter_errors(self, _data: Any) -> list:
        return []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _describe(kind: str, status: Any) -> str:
    names = {"overloaded": "перегружена", "server": "сбой сервера", "timeout": "тайм-аут", "network": "нет сети",
             "not_found": "недоступна ключу (404)", "quota": "квота исчерпана", "rate_limit": "лимит запросов (429)",
             "auth": "ключ отклонён", "bad_request": "запрос отклонён", "refusal": "отказ фильтром",
             "truncated": "ответ обрезан", "invalid_output": "ответ не по схеме", "not_configured": "не настроено",
             "empty": "пустой ответ"}
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
    paces_requests = True   # окно запросов в минуту по каждой модели — здесь; фиксированный шаг --rpm поверх не нужен

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 fallback_models: Iterable[str] | str | None = None, env: Mapping[str, str] | None = None,
                 adapter_factory: Callable[[str, dict[str, Any]], Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 retry_delays: Sequence[float] = RETRY_DELAYS_S, network_delays: Sequence[float] = NETWORK_DELAYS_S,
                 max_rate_wait_s: float | None = None, max_output_tokens: int | None = None,
                 concurrency: int | None = None, rpm: float | None = None) -> None:
        cfg = settings(env)
        self._api_key = api_key or cfg["api_key"]
        self.default_model = (model or cfg["model"]).strip().removeprefix("models/")
        self.fallback_models = _models(fallback_models) if fallback_models is not None else cfg["fallback_models"]
        self.rpm = rpm if rpm is not None else cfg["rpm"]   # None — по профилю каждой модели
        self._window: dict[str, deque] = {}
        self._window_lock = threading.Lock()
        explicit = max_output_tokens or cfg["max_output_tokens"]
        self.max_output_tokens = int(explicit) if explicit else None   # None — потолок модели из профиля
        self._out_cap: dict[str, int] = {}                             # модели, отвергшие большой лимит ответа
        self._cooling: dict[str, float] = {}   # перегруженные модели: до какого времени — одна попытка без пауз
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
        self.concurrency = int(concurrency or cfg["concurrency"]
                               or profiles.for_model(self.default_model).get("concurrency") or DEFAULT_CONCURRENCY)
        self._gate = threading.BoundedSemaphore(max(1, self.concurrency))
        self._adapters: dict[tuple[str, tuple], Any] = {}
        self._dead: dict[str, ProviderError] = {}       # модели, отключённые до конца прогона (404, квота)
        self._no_thinking: set[tuple] = set()            # (модель, настройка рассуждений), которую модель отвергла
        self._text_schema: set[str] = set()              # модели, отвергшие схему ответа (слишком сложная)

    # ------------------------------------------------------------------ adapters

    def _v1_adapter(self, model: str, thinking: dict[str, Any], schema_mode: str = "native") -> Any:
        if not self._api_key:
            raise ProviderError("not_configured", f"Не задан GEMINI_API_KEY. {KEY_HELP}", model=model)
        from bcc_review.providers.gemini import GeminiAdapter
        text_mode = schema_mode == "text"

        class LenientAdapter(GeminiAdapter):
            """Ответ не по схеме возвращается как есть: проверку и одну починку по списку нарушений делает
            ``LLMClient`` (адаптер v1 бросал invalid_output, и этап падал без попытки исправить ответ)."""

            def _schema_bundle(self, schema: Mapping[str, Any]) -> Any:
                wire, log, _validator = super()._schema_bundle(schema)
                if text_mode:
                    wire, log = None, [*log, {"path": "/", "keyword": "*", "action": "schema sent as text"}]
                return wire, log, _PassValidator()

        cls = LenientAdapter
        return cls(api_key=self._api_key, model=model, fallback_models=[], min_attempt_s=1.0,
                   temperature=self.temperature, max_output_tokens=self.max_output_tokens,
                   thinking_budget=thinking.get("thinking_budget"), thinking_level=thinking.get("thinking_level"))

    def _adapter(self, model: str, stage: str = "") -> tuple[Any, dict[str, Any], str]:
        thinking = thinking_for(model, self.thinking_level, self.thinking_budget, stage)
        if (model, tuple(sorted(thinking.items()))) in self._no_thinking:
            thinking = {}   # отвергнута именно эта настройка: другой уровень (low у нарезки) остаётся в силе
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

    def output_limit(self, model: str, stage_limit: int = 0) -> int:
        """Лимит ответа запроса: не ниже лимита этапа и потолка модели — рассуждения Gemini расходуют тот же лимит.

        Потолок — ``GEMINI_MAX_OUTPUT_TOKENS`` или профиль (Gemini 2.5 и 3.x — 65 536). Обрезка на 32 000 у
        набора (у haiku 34,5 тыс. токенов с рассуждением) раньше означала провал этапа: повтор «с удвоенным
        лимитом» упирался в тот же потолок, а набор пакет не делит.
        """
        ceiling = int(self.max_output_tokens or profiles.gemini_max_output(model))
        limit = max(int(stage_limit or 0), ceiling)
        cap = self._out_cap.get(model)
        return min(limit, cap) if cap else limit

    def rpm_for(self, model: str) -> float:
        """Сколько запросов в минуту слать модели: ``GEMINI_RPM`` или профиль (бесплатный тариф)."""
        if self.rpm is not None:
            return max(0.0, float(self.rpm))
        return float(profiles.for_model(model).get("rpm") or 0)

    def _pace(self, model: str, deadline: float) -> float:
        """Скользящее окно: ждём, только если за последние 60 с к модели ушло уже ``rpm`` запросов.

        Возвращает секунды ожидания (0 — без паузы). Запрос занимает место в окне сразу, до отправки.
        """
        rpm = self.rpm_for(model)
        if rpm <= 0:
            return 0.0
        limit = max(1, int(rpm))
        with self._window_lock:
            win = self._window.setdefault(model, deque())
            now = self._clock()
            while win and now - win[0] >= RATE_WINDOW_S:
                win.popleft()
            wait = 0.0
            if len(win) >= limit:
                wait = max(0.0, win[len(win) - limit] + RATE_WINDOW_S - now + 0.5)
                if now + wait > deadline - 5:
                    wait = 0.0   # не успеваем дождаться: отправляем, 429 обработает Retry-After
            win.append(now + wait)
        if wait > 0:
            self._sleep(wait)
        return wait

    # ------------------------------------------------------------------ invoke

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float, max_output_tokens: int | None = None, stage: str = "", **_: Any) -> dict[str, Any]:
        chain = self.model_chain(model)
        per_call = max(5.0, float(timeout_s or 300))
        # Бюджет всего invoke: таймаут вызывающего (LLMClient уже ограничил его остатком лимита этапа) + запас на
        # быстрые повторы (503, Retry-After). Зависший запрос не растянет этап втрое.
        total = float(self.total_timeout_s) if self.total_timeout_s else per_call + RETRY_SLACK_S
        deadline = self._clock() + total
        attempts: list[dict[str, Any]] = []
        last: ProviderError | None = None
        stage_limit = int(max_output_tokens or 0)
        clean = [{"role": m.get("role"), "content": m.get("content")} for m in messages]

        for current in chain:
            dead = self._dead.get(current)
            if dead is not None:
                attempts.append({"model": current, "skipped": dead.kind})
                last = last or dead
                continue
            transient = network = rate = empty = 0
            while True:
                remaining = deadline - self._clock()
                if remaining < 5:
                    raise self._final(last or ProviderError("timeout", f"Бюджет времени вызова Gemini ({total:.0f} с) "
                                                                       "исчерпан.", model=current), chain, attempts)
                try:
                    adapter, thinking, mode = self._adapter(current, stage)
                except ProviderError as exc:
                    raise self._final(exc, chain, attempts) from None
                sent = _with_schema_text(clean, schema) if mode == "text" else clean
                max_tokens = self.output_limit(current, stage_limit)
                started = self._clock()
                try:
                    with self._gate:
                        waited = self._pace(current, deadline)
                        if waited:
                            attempts.append({"model": current, "rpm_wait_s": round(waited, 1)})
                        started = self._clock()
                        remaining = deadline - started
                        result = adapter.invoke(model=current, messages=sent, schema=schema,
                                                timeout_s=max(5.0, min(per_call, remaining)),
                                                max_output_tokens=max_tokens)
                except ProviderError as exc:
                    last = exc
                    kind = exc.kind
                    attempts.append({"model": current, "kind": kind, "status": exc.status,
                                     "subkind": getattr(exc, "subkind", None),
                                     "retry_after_s": exc.retry_after_s, "seconds": round(self._clock() - started, 2)})
                    if kind in NEXT_MODEL:
                        self._dead[current] = exc
                        break
                    if is_empty_answer(exc):
                        if empty < EMPTY_RETRIES:
                            empty += 1
                            continue
                        break   # та же модель дважды ответила пустым — следующая модель цепочки
                    if kind in TRANSIENT:
                        cooling = self._cooling.get(current, 0.0) > self._clock()
                        if transient < len(self.retry_delays) and not cooling:
                            self._sleep(self.retry_delays[transient])
                            transient += 1
                            continue
                        # повторы исчерпаны (или модель уже «остывает»): COOL_S секунд пробуем её один раз без пауз
                        self._cooling[current] = self._clock() + COOL_S
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
                    if kind == "bad_request" and _is_output_limit_error(low) and max_tokens > 8192:
                        self._out_cap[current] = 32768 if max_tokens > 32768 else 8192
                        continue
                    if kind == "bad_request" and thinking and "think" in low:
                        self._no_thinking.add((current, tuple(sorted(thinking.items()))))
                        continue
                    if kind == "bad_request" and mode == "native" and ("schema" in low or "too many states" in low):
                        self._text_schema.add(current)
                        continue
                    raise self._final(exc, chain, attempts) from None
                self._cooling.pop(current, None)
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
        # попытки и паузы — в usage, чтобы они попали в trace.jsonl (разбор: python -m bcc_review.v2.providers.timing)
        tried = [_attempt_note(a) for a in attempts]
        if tried:
            usage["attempts"] = tried
        waited = sum(float(a.get("rpm_wait_s") or 0) for a in attempts)
        if waited:
            usage["rpm_wait_s"] = round(waited, 1)
        if thinking:
            usage["thinking"] = next(iter(thinking.values()))
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
                if "rpm_wait_s" in a:
                    continue
                kind = a.get("kind") or a.get("skipped") or "?"
                if kind == "invalid_output" and str(a.get("subkind") or "") in EMPTY_SUBKINDS:
                    kind = "empty"
                tried.setdefault(a["model"], []).append(_describe(kind, a.get("status")))
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
