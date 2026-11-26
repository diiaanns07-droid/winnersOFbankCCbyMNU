"""Провайдер ``anthropic`` для v2 (№02): Claude API по ключу ``ANTHROPIC_API_KEY``.

Обёртка над адаптером v1 ``bcc_review.providers.anthropic.AnthropicAdapter`` (SDK ``anthropic``,
structured outputs через ``output_config.format``, локальная проверка по полной JSON Schema,
классификация ошибок API с русскими сообщениями). Что меняет v2:

* в ``messages`` уходят только ``role`` и ``content`` — служебные поля вроде ``cache`` из v1 давали
  400 на каждом вызове; кэширование промпта делается штатно, через ``cache_control``:
  на системном промпте и на блоке документа (общий префикс всех этапов: документ → требования →
  сигналы; текст задания этапа идёт последним, отдельным блоком без кэша);
* ``max_tokens`` по умолчанию 32 000 (в v1 16 000 обрезали пакеты), ``ANTHROPIC_MAX_TOKENS``;
* без лишнего вызова ``GET /v1/models`` перед каждым этапом (``verify_model=False``);
* если API отверг beta серверных запасных моделей или параметр ``effort`` (400) — тот же запрос
  сразу повторяется без них, и до конца прогона они не передаются.

Повторы временных ошибок (429/529/5xx) делает ``LLMClient`` (``handles_retries = False``).
Переменные: ``ANTHROPIC_API_KEY``, ``ANTHROPIC_MODEL`` (по умолчанию ``claude-opus-5-5``),
``ANTHROPIC_MAX_TOKENS``, ``ANTHROPIC_EFFORT``, ``ANTHROPIC_FALLBACKS`` (``default|off|список``).
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Callable, Mapping, Sequence

from bcc_review.contracts import ProviderError

__all__ = ["AnthropicProvider", "DEFAULT_MODEL", "to_cached_messages"]

PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 32000
MIN_CACHE_PREFIX_CHARS = 2000   # короче — кэш не окупается (минимум API ~1024 токена)
KEY_HELP = "Ключ Claude API: https://console.anthropic.com/settings/keys — строка ANTHROPIC_API_KEY=<ключ> в .env."
_CLOSING_TAG = re.compile(r"^[ \t]*</[^<>\n]{1,60}>[ \t]*$", re.MULTILINE)


def to_cached_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Сообщения для Messages API: только ``role``/``content``, ``cache_control`` на префиксе документа.

    Системные сообщения остаются строками (адаптер v1 сам ставит ``cache_control`` на последний
    системный блок). В последнем сообщении ``user`` общий префикс — всё до последнего закрывающего
    тега на отдельной строке (``</документ>``, ``</требования>``, ``</сигналы>``) — становится отдельным
    кэшируемым блоком; задание этапа — следующим блоком.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content")
        if isinstance(content, list):  # уже блоки: оставить только text
            text = "".join(str(b.get("text") or "") for b in content if isinstance(b, Mapping))
        else:
            text = "" if content is None else str(content)
        out.append({"role": role, "content": text})
    users = [i for i, m in enumerate(out) if m["role"] == "user"]
    if users:
        i = users[-1]
        text = out[i]["content"]
        tags = list(_CLOSING_TAG.finditer(text))
        if tags:
            cut = tags[-1].end()
            prefix, rest = text[:cut], text[cut:].lstrip("\n")
            if len(prefix) >= MIN_CACHE_PREFIX_CHARS and rest.strip():
                out[i]["content"] = [
                    {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": rest},
                ]
    return out


class AnthropicProvider:
    """Claude API. ``adapter_factory(**options)`` подменяется в тестах (по умолчанию — адаптер v1)."""

    name = PROVIDER
    handles_retries = False

    def __init__(self, *, api_key: str | None = None, model: str | None = None, max_tokens: int | None = None,
                 env: Mapping[str, str] | None = None, adapter_factory: Callable[..., Any] | None = None) -> None:
        env = os.environ if env is None else env
        self._env = env
        self._api_key = (api_key or env.get("ANTHROPIC_API_KEY") or "").strip() or None
        if not self._api_key and adapter_factory is None:
            raise ProviderError("not_configured", f"Не задан ANTHROPIC_API_KEY. {KEY_HELP}")
        self.default_model = (model or env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip()
        raw = (env.get("ANTHROPIC_MAX_TOKENS") or "").strip()
        try:
            self.max_tokens = int(max_tokens or (int(raw) if raw else DEFAULT_MAX_TOKENS))
        except ValueError:
            raise ProviderError("not_configured", f"ANTHROPIC_MAX_TOKENS={raw!r}: ожидается число.") from None
        self._factory = adapter_factory or self._v1_adapter
        self._lock = threading.Lock()
        self._adapters: dict[tuple, Any] = {}
        self.fallbacks_off = False
        self.effort_off = False

    def _v1_adapter(self, **options: Any) -> Any:
        try:
            from bcc_review.providers.anthropic import AnthropicAdapter
        except ImportError:
            raise ProviderError("not_configured", "Не установлен пакет anthropic: pip install anthropic==2.14.0") from None
        try:
            return AnthropicAdapter(api_key=self._api_key, env=self._env, verify_model=False, **options)
        except ValueError as exc:  # неверное значение ANTHROPIC_* в окружении
            raise ProviderError("not_configured", f"Настройка Claude API: {exc}") from None

    def _adapter(self, max_tokens: int) -> Any:
        options: dict[str, Any] = {"max_tokens": max_tokens}
        if self.fallbacks_off:
            options["fallbacks"] = "off"
        if self.effort_off:
            options["effort"] = ""
        key = tuple(sorted(options.items()))
        with self._lock:
            if key not in self._adapters:
                self._adapters[key] = self._factory(**options)
            return self._adapters[key]

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float, max_output_tokens: int | None = None, **_: Any) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        wire = to_cached_messages(messages)
        max_tokens = int(max_output_tokens or self.max_tokens)
        for _attempt in range(3):
            adapter = self._adapter(max_tokens)
            try:
                result = adapter.invoke(model=model, messages=wire, schema=schema, timeout_s=timeout_s)
            except ProviderError as exc:
                text = f"{getattr(exc, 'subkind', '') or ''} {exc.message or ''}".lower()
                if exc.kind == "bad_request" and not self.fallbacks_off and (
                        "beta" in text or "fallback" in text):
                    self.fallbacks_off = True
                    continue
                if exc.kind == "bad_request" and not self.effort_off and "effort" in text:
                    self.effort_off = True
                    continue
                raise
            usage = dict(result.get("usage") or {})
            for k in ("input_tokens", "output_tokens"):
                usage[k] = int(usage.get(k) or 0)
            usage["input_tokens"] += int(usage.get("cache_read_input_tokens") or 0) + int(
                usage.get("cache_creation_input_tokens") or 0)
            stop = result.get("stop_reason") or "end_turn"
            return {"data": result.get("data"), "usage": usage, "model": result.get("model") or model,
                    "request_id": result.get("request_id") or "",
                    "stop_reason": "max_tokens" if stop == "max_tokens" else "end_turn",
                    "cost_usd": usage.get("cost_usd"),
                    "meta": {"provider": PROVIDER, "requested_model": model,
                             "fallbacks": "off" if self.fallbacks_off else "default",
                             "cached_prefix": isinstance(wire[-1].get("content"), list) if wire else False}}
        raise ProviderError("bad_request", "Claude API отклонил запрос даже без beta-параметров.", model=model)
