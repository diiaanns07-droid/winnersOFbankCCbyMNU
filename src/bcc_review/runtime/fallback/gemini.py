"""Резервный адаптер Gemini (пока не влит модуль №12 ``bcc_review.providers.gemini``).

Только стандартная библиотека. Один вызов ``invoke`` — один запрос ``generateContent``; единственный
повтор внутри адаптера — переход с ``responseJsonSchema`` на ``responseSchema`` (подмножество OpenAPI),
если API отверг первое поле. Повторы временных ошибок и бюджет решает движок по ``ProviderError``.

Ключ передаётся только заголовком ``x-goog-api-key``: его нет ни в URL, ни в сообщениях исключений.
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping, Optional

from ...contracts import ProviderError

__all__ = ["GeminiAdapter", "sanitize_schema"]

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# (url, headers, body, timeout) -> (status, headers, body)
Transport = Callable[[str, dict, bytes, float], tuple[int, dict, bytes]]

_REFUSAL_REASONS = frozenset({"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"})
_SCHEMA_KEYS = frozenset({
    "type", "format", "title", "description", "nullable", "enum", "maxItems", "minItems", "properties",
    "required", "minProperties", "maxProperties", "minLength", "maxLength", "pattern", "example", "anyOf",
    "propertyOrdering", "default", "items", "minimum", "maximum",
})
_FORMATS = {"string": {"enum", "date-time"}, "integer": {"int32", "int64"}, "number": {"float", "double"}}


# --------------------------------------------------------------------------- транспорт
def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, dict, bytes]:
    """HTTP POST через ``urllib``. Ответ 4xx/5xx возвращается как есть, сетевые ошибки — исключением."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL задаёт конфигурация
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read()
        except Exception:  # noqa: BLE001
            payload = b""
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, payload


# --------------------------------------------------------------------------- схема
def sanitize_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """JSON Schema → подмножество OpenAPI для ``responseSchema``.

    ``$ref`` раскрываются из ``$defs``/``definitions``; ``additionalProperties``, ``$schema``, ``$id`` и
    прочие неподдержанные ключи отбрасываются; ``const`` → ``enum``; ``["string", "null"]`` →
    ``type: string, nullable: true``; ``oneOf`` → ``anyOf``.
    """
    defs: dict[str, Any] = {}
    for key in ("$defs", "definitions"):
        if isinstance(schema.get(key), Mapping):
            defs.update(schema[key])

    def resolve(ref: str, stack: tuple[str, ...]) -> tuple[Optional[Mapping[str, Any]], tuple[str, ...]]:
        name = ref.rsplit("/", 1)[-1]
        if name in stack or name not in defs:
            return None, stack
        return defs[name], stack + (name,)

    def conv(node: Any, stack: tuple[str, ...]) -> Any:
        if not isinstance(node, Mapping):
            return node
        node = dict(node)
        while "$ref" in node:
            target, stack = resolve(str(node.pop("$ref")), stack)
            if target is None:
                return {"type": "object", "description": "рекурсивная или неизвестная ссылка"}
            node = {**target, **node}
        if "allOf" in node:
            for part in node.pop("allOf") or []:
                part = conv(part, stack)
                if isinstance(part, Mapping):
                    for k, v in part.items():
                        if k == "properties":
                            node.setdefault("properties", {}).update(v)
                        elif k == "required":
                            node["required"] = list(dict.fromkeys(list(node.get("required", [])) + list(v)))
                        else:
                            node.setdefault(k, v)
        if "oneOf" in node and "anyOf" not in node:
            node["anyOf"] = node.pop("oneOf")
        out: dict[str, Any] = {}
        nullable = bool(node.get("nullable"))

        typ = node.get("type")
        if isinstance(typ, list):
            types = [t for t in typ if t != "null"]
            nullable = nullable or len(types) < len(typ)
            if len(types) == 1:
                typ = types[0]
            elif not types:
                typ = "string"
            else:
                typ = None
                out["anyOf"] = [{"type": t} for t in types]
        elif typ == "null":
            typ, nullable = "string", True
        if typ:
            out["type"] = typ

        if "const" in node and "enum" not in node:
            node["enum"] = [node["const"]]
        if "enum" in node:
            values = [v for v in node["enum"] if v is not None]
            nullable = nullable or len(values) < len(node["enum"])
            if values and all(isinstance(v, str) for v in values):
                out["enum"] = values
                out.setdefault("type", "string")

        for key, value in node.items():
            if key not in _SCHEMA_KEYS or key in ("type", "enum", "nullable"):
                continue
            if key == "properties" and isinstance(value, Mapping):
                out["properties"] = {k: conv(v, stack) for k, v in value.items()}
            elif key == "items":
                out["items"] = conv(value, stack) if isinstance(value, Mapping) else {"type": "string"}
            elif key == "anyOf":
                raw = list(value or [])
                rest = [v for v in raw if not (isinstance(v, Mapping) and v.get("type") == "null")]
                nullable = nullable or len(rest) < len(raw)
                variants = [conv(v, stack) for v in rest]
                if len(variants) == 1 and isinstance(variants[0], Mapping):
                    for k, v in variants[0].items():
                        out.setdefault(k, v)
                elif variants:
                    out["anyOf"] = variants
            elif key == "format":
                if value in _FORMATS.get(str(out.get("type")), set()):
                    out["format"] = value
            else:
                out[key] = value

        if "properties" in out:
            out.setdefault("type", "object")
            out["required"] = [r for r in out.get("required", []) if r in out["properties"]]
            if not out["required"]:
                out.pop("required")
            out["propertyOrdering"] = list(out["properties"])
        elif "items" in out:
            out.setdefault("type", "array")
        if nullable:
            out["nullable"] = True
        return out

    return conv(schema, ())


def _schema_field_rejected(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace")
    low = text.lower()
    return ("responsejsonschema" in low or "response_json_schema" in low
            or ("unknown name" in low and "generation" in low))


# --------------------------------------------------------------------------- разбор ответа
def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    name = name.lower()
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return str(v)
    return None


def _retry_after(headers: Mapping[str, Any], error: Mapping[str, Any]) -> Optional[float]:
    value = _header(headers, "retry-after")
    if value:
        value = value.strip()
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                return max(0.0, when.timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    for detail in error.get("details") or []:
        if isinstance(detail, Mapping) and "retryDelay" in detail:
            m = re.fullmatch(r"\s*([\d.]+)\s*s?\s*", str(detail["retryDelay"]))
            if m:
                return float(m.group(1))
    m = re.search(r"retry in ([\d.]+)\s*s", str(error.get("message", "")), re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def _per_day_quota(error: Mapping[str, Any]) -> bool:
    message = str(error.get("message", "")).lower()
    if "per day" in message or "perday" in message or "daily" in message or "limit: 0" in message:
        return True
    for detail in error.get("details") or []:
        if not isinstance(detail, Mapping):
            continue
        for v in detail.get("violations") or []:
            if isinstance(v, Mapping) and re.search(r"per ?day|daily", str(v.get("quotaId", "")) + " "
                                                    + str(v.get("quotaMetric", "")), re.IGNORECASE):
                return True
    return False


def _error_body(body: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(body.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return {"message": body[:300].decode("utf-8", errors="replace")}
    if isinstance(obj, list) and obj:
        obj = obj[0]
    if isinstance(obj, Mapping) and isinstance(obj.get("error"), Mapping):
        return dict(obj["error"])
    return {}


def _strip_fence(text: str) -> str:
    s = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    return m.group(1) if m else s


# --------------------------------------------------------------------------- адаптер
class GeminiAdapter:
    """Адаптер провайдера Gemini (``ProviderAdapter`` контракта v1)."""

    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, *, transport: Optional[Transport] = None,
                 base_url: str = DEFAULT_BASE_URL, max_output_tokens: int = 65536):
        if api_key is None:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._api_key = (api_key or "").strip() or None
        self._transport: Transport = transport or urllib_transport
        self.base_url = base_url.rstrip("/")
        self.max_output_tokens = max_output_tokens

    def __repr__(self) -> str:
        return f"GeminiAdapter(base_url={self.base_url!r}, configured={self._api_key is not None})"

    @property
    def configured(self) -> bool:
        return self._api_key is not None

    # ------------------------------------------------------------------ публичный вызов
    def invoke(self, *, model: str, messages: list[dict[str, Any]], schema: Mapping[str, Any],
               timeout_s: float) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderError("not_configured",
                                "не задан ключ Gemini: переменная окружения GEMINI_API_KEY или GOOGLE_API_KEY")
        model = (model or "").strip()
        if model.startswith("models/"):
            model = model[len("models/"):]
        if not model:
            raise ProviderError("bad_request", "не указана модель Gemini (GEMINI_MODEL или --model)")
        url = f"{self.base_url}/models/{urllib.parse.quote(model, safe='-._~')}:generateContent"

        status, headers, body = self._post(url, self._body(messages, dict(schema), "responseJsonSchema"), timeout_s)
        if status == 400 and _schema_field_rejected(body):
            status, headers, body = self._post(
                url, self._body(messages, sanitize_schema(schema), "responseSchema"), timeout_s)
        if not 200 <= status < 300:
            raise self._http_error(status, headers, body, model)
        return self._parse(body, headers, model)

    # ------------------------------------------------------------------ запрос
    def _body(self, messages: list[dict[str, Any]], schema: Mapping[str, Any], field: str) -> bytes:
        system: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            role = m.get("role", "user")
            if role == "system":
                system.append(content)
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
        if not contents:
            raise ProviderError("bad_request", "в запросе нет сообщения пользователя")
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                field: schema,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _post(self, url: str, body: bytes, timeout_s: float) -> tuple[int, dict, bytes]:
        headers = {"Content-Type": "application/json; charset=utf-8", "x-goog-api-key": self._api_key or ""}
        # Исключения транспорта не прикрепляются цепочкой (``from None``): их текст мог бы содержать ключ.
        try:
            status, resp_headers, resp_body = self._transport(url, headers, body, timeout_s)
        except ProviderError:
            raise
        except (TimeoutError, socket.timeout):
            raise ProviderError("timeout", f"Gemini не ответил за {timeout_s:g} с") from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise ProviderError("timeout", f"Gemini не ответил за {timeout_s:g} с") from None
            raise ProviderError("network", self._scrub(f"сеть недоступна: {reason}")) from None
        except (ConnectionError, OSError) as exc:
            raise ProviderError("network", self._scrub(f"сетевая ошибка: {type(exc).__name__}: {exc}")) from None
        except Exception as exc:  # noqa: BLE001 - http.client.HTTPException и прочее
            raise ProviderError("network", self._scrub(f"ошибка HTTP-клиента: {type(exc).__name__}: {exc}")) from None
        return int(status), dict(resp_headers or {}), resp_body or b""

    # ------------------------------------------------------------------ ответ
    def _http_error(self, status: int, headers: Mapping[str, Any], body: bytes, model: str) -> ProviderError:
        error = _error_body(body)
        api_status = str(error.get("status", ""))
        text = str(error.get("message", "")).strip()
        reasons = " ".join(str(d.get("reason", "")) for d in error.get("details") or [] if isinstance(d, Mapping))
        retry = _retry_after(headers, error)
        if status in (401, 403) or "API_KEY_INVALID" in reasons or "api key not valid" in text.lower():
            kind = "auth"
        elif status == 429 or api_status == "RESOURCE_EXHAUSTED":
            kind = "quota" if _per_day_quota(error) else "rate_limit"
        elif status == 503:
            kind = "overloaded"
        elif status == 404:
            kind = "not_found"
        elif status == 408:
            kind = "timeout"
        elif status >= 500:
            kind = "server"
        elif 400 <= status < 500:
            kind = "bad_request"
        else:
            kind = "unknown"
        detail = f"{api_status}: {text}" if api_status and text else (api_status or text or "без описания")
        message = self._scrub(f"Gemini HTTP {status}: {detail}"[:500])
        return ProviderError(kind, message, retry_after_s=retry, status=status, model=model)

    def _parse(self, body: bytes, headers: Mapping[str, Any], requested: str) -> dict[str, Any]:
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProviderError("server", "Gemini вернул ответ не в формате JSON", status=200) from exc
        if not isinstance(obj, Mapping):
            raise ProviderError("server", "Gemini вернул неожиданный ответ", status=200)
        meta = obj.get("usageMetadata") or {}
        usage = {
            "input_tokens": int(meta.get("promptTokenCount") or 0),
            "output_tokens": int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0),
        }
        if meta.get("cachedContentTokenCount"):
            usage["cache_read"] = int(meta["cachedContentTokenCount"])
        model = str(obj.get("modelVersion") or requested)
        request_id = obj.get("responseId") or _header(headers, "x-request-id")

        def fail(kind: str, message: str) -> ProviderError:
            return ProviderError(kind, message, status=200, request_id=request_id, usage=usage, model=model)

        feedback = obj.get("promptFeedback") or {}
        candidates = obj.get("candidates") or []
        if feedback.get("blockReason"):
            raise fail("refusal", f"Gemini отклонил запрос: {feedback['blockReason']}")
        if not candidates:
            raise fail("refusal", "Gemini не вернул ни одного варианта ответа")
        cand = candidates[0] or {}
        reason = str(cand.get("finishReason") or "STOP")
        if reason == "MAX_TOKENS":
            raise fail("truncated", f"ответ Gemini обрезан по лимиту maxOutputTokens={self.max_output_tokens}")
        if reason in _REFUSAL_REASONS:
            raise fail("refusal", f"Gemini прервал ответ: {reason}")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, Mapping) and not p.get("thought"))
        if not text.strip():
            raise fail("invalid_output", f"Gemini вернул пустой ответ (finishReason={reason})")
        try:
            data = json.loads(_strip_fence(text))
        except ValueError as exc:
            raise fail("invalid_output", f"ответ Gemini — не JSON ({exc.msg}, позиция {exc.pos})") from exc
        return {"data": data, "usage": usage, "model": model, "request_id": request_id,
                "stop_reason": reason.lower()}

    def _scrub(self, text: str) -> str:
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return text
