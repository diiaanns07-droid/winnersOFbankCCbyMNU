"""Резервный адаптер Claude API (пока не влит модуль №11 ``bcc_review.providers.anthropic``).

Официальный SDK ``anthropic``, structured outputs через ``output_config.format`` (JSON Schema),
адаптивное мышление, потоковая передача с ``get_final_message()``. Повторы SDK отключены
(``max_retries=0``): повторы, Retry-After и бюджет считает движок, чтобы паспорт видел каждый вызов.
Серверный резерв при отказе модели (``fallbacks: "default"``) включён по умолчанию,
фактическая модель ответа попадает в паспорт; выключить — ``BCC_ANTHROPIC_FALLBACKS=off``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Optional

from ...contracts import ProviderError

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _retry_after(exc: Any) -> Optional[float]:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, *, client: Any = None, max_tokens: Optional[int] = None,
                 effort: Optional[str] = None, fallbacks: Optional[str] = None):
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self._client = client
        self.max_tokens = int(max_tokens or os.environ.get("BCC_ANTHROPIC_MAX_TOKENS", 32000))
        self.effort = effort or os.environ.get("BCC_ANTHROPIC_EFFORT", "high")
        fb = fallbacks if fallbacks is not None else os.environ.get("BCC_ANTHROPIC_FALLBACKS", "default")
        self.fallbacks = None if fb in ("", "off", "none", "0") else fb
        self.params = {"max_tokens": self.max_tokens, "effort": self.effort, "fallbacks": self.fallbacks,
                       "thinking": "adaptive", "output": "json_schema"}

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError("not_configured", "не установлен пакет anthropic: pip install \"bcc-review[anthropic]\"") from exc
        if not self._api_key and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            raise ProviderError("not_configured", "не задан ANTHROPIC_API_KEY (см. .env.example)")
        kwargs: dict[str, Any] = {"max_retries": 0}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        self._client = anthropic.Anthropic(**kwargs)
        return self._client

    @staticmethod
    def _split(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        blocks: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] != "user":
                continue
            block: dict[str, Any] = {"type": "text", "text": m["content"]}
            if m.get("cache"):
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return system, [{"role": "user", "content": blocks}]

    def _request(self, client: Any, kwargs: dict[str, Any]) -> Any:
        with client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    def invoke(self, *, model: str, messages: list[dict[str, Any]], schema: Mapping[str, Any],
               timeout_s: float) -> dict[str, Any]:
        client = self._get_client()
        import anthropic

        system, msgs = self._split(messages)
        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": self.max_tokens, "system": system, "messages": msgs,
            "thinking": {"type": "adaptive"},
            "output_config": {"format": {"type": "json_schema", "schema": dict(schema)}, "effort": self.effort},
            "timeout": timeout_s,
        }
        if self.fallbacks:
            kwargs["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
            kwargs["extra_body"] = {"fallbacks": self.fallbacks}
        try:
            try:
                msg = self._request(client, kwargs)
            except anthropic.BadRequestError as exc:
                if self.fallbacks and "fallback" in str(exc).lower():
                    kwargs.pop("extra_headers", None)
                    kwargs.pop("extra_body", None)
                    msg = self._request(client, kwargs)
                else:
                    raise
        except anthropic.AuthenticationError as exc:
            raise ProviderError("auth", f"ключ Anthropic отклонён: {exc.status_code}", status=exc.status_code) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("auth", f"нет доступа: {exc.status_code}", status=exc.status_code) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError("not_found", f"модель {model} не найдена", status=exc.status_code) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate_limit", "превышен лимит запросов", retry_after_s=_retry_after(exc),
                                status=exc.status_code) from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError("bad_request", str(getattr(exc, "message", exc))[:500], status=exc.status_code) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("timeout", f"таймаут {timeout_s:.0f} с") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("network", "нет соединения с API Anthropic") from exc
        except anthropic.APIStatusError as exc:
            kind = "overloaded" if exc.status_code in (503, 529) else ("server" if exc.status_code >= 500 else "bad_request")
            raise ProviderError(kind, f"HTTP {exc.status_code}", retry_after_s=_retry_after(exc),
                                status=exc.status_code) from exc

        u = getattr(msg, "usage", None)
        usage = {
            "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        }
        actual = getattr(msg, "model", None) or model
        request_id = getattr(msg, "_request_id", None) or getattr(msg, "id", None)
        stop = getattr(msg, "stop_reason", None)
        if stop == "max_tokens":
            raise ProviderError("truncated", f"ответ усечён на max_tokens={self.max_tokens}", usage=usage, model=actual,
                                request_id=request_id)
        if stop == "refusal":
            details = getattr(msg, "stop_details", None)
            raise ProviderError("refusal", f"модель отказалась: {getattr(details, 'category', None)}", usage=usage,
                                model=actual, request_id=request_id)
        text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise ProviderError("invalid_output", "в ответе нет текстового блока", usage=usage, model=actual)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProviderError("invalid_output", f"ответ не JSON: {exc}", usage=usage, model=actual) from exc
        return {"data": data, "usage": usage, "model": actual, "request_id": request_id, "stop_reason": stop}
