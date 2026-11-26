"""Адаптер Gemini (Google Gen AI SDK) для семантических этапов bcc_review.

Контракт (общий с адаптером Anthropic, исполнитель №11):

    GeminiAdapter().invoke(*, model, messages, schema, timeout_s)
        -> {"data", "usage", "model", "request_id", "meta"}

* ``messages`` — список ``{"role": "system"|"user"|"assistant", "content": str | [{"type": "text", "text": str}]}``;
* ``schema`` — полная JSON Schema (draft 2020-12) ожидаемого объекта;
* ``timeout_s`` — бюджет всего вызова, включая резервную модель.

Адаптер делает ровно одну попытку на модель: SDK-ретраи выключены, повторы,
общий таймер и выбор другого провайдера принадлежат runtime. Резервная модель
вызывается только из явно заданного списка (``GEMINI_FALLBACK_MODELS``), каждая
модель не более одного раза и только если в бюджете осталось ``min_attempt_s``.

Ответ принимается только при ``finish_reason == STOP``, непустом тексте, валидном
JSON и полной валидации по исходной схеме. Всё остальное становится
``ProviderError`` с точной категорией (``kind``). Других исключений ``invoke``
наружу не выпускает.

Проверка с реальным ключом: ``python -m bcc_review.providers.gemini models|doctor``.
"""

from __future__ import annotations

import copy
import email.utils
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MIN_ATTEMPT_S = 5.0
API_HOST = "generativelanguage.googleapis.com"
KEY_HELP = "Ключ выдаёт Google AI Studio: https://aistudio.google.com/apikey"
MODELS_HELP = "Список моделей, доступных ключу: python -m bcc_review.providers.gemini models"


# --------------------------------------------------------------------------- errors


class ErrorKind(StrEnum):
    CONFIG = "config"                        # нет ключа, SDK или зависимости
    AUTH = "auth"                            # ключ недействителен, доступ или регион запрещены
    RATE_LIMITED = "rate_limited"            # 429, минутный лимит (RPM/TPM)
    QUOTA_EXHAUSTED = "quota_exhausted"      # 429, дневная квота или лимит 0 у модели
    OVERLOADED = "overloaded"                # 503/500/502: перегрузка или сбой сервера
    MODEL_UNAVAILABLE = "model_unavailable"  # 404: модели нет или она снята
    TIMEOUT = "timeout"                      # клиентский тайм-аут, 504, бюджет исчерпан
    NETWORK = "network"                      # DNS, соединение, прокси
    BAD_REQUEST = "bad_request"              # 400: запрос или схема отвергнуты
    BLOCKED = "blocked"                      # фильтр безопасности, recitation и т. п.
    EMPTY = "empty"                          # нет кандидатов или текста
    TRUNCATED = "truncated"                  # MAX_TOKENS: выходной бюджет исчерпан
    INVALID_OUTPUT = "invalid_output"        # не JSON или не проходит схему
    UNKNOWN = "unknown"


RETRYABLE = frozenset({
    ErrorKind.RATE_LIMITED, ErrorKind.OVERLOADED, ErrorKind.TIMEOUT,
    ErrorKind.NETWORK, ErrorKind.EMPTY, ErrorKind.INVALID_OUTPUT,
})
# Ошибки, при которых имеет смысл резервная модель: квоты и доступность у Gemini
# считаются отдельно по каждой модели.
FALLBACK_ON = frozenset({
    ErrorKind.MODEL_UNAVAILABLE, ErrorKind.QUOTA_EXHAUSTED,
    ErrorKind.OVERLOADED, ErrorKind.RATE_LIMITED,
})
# Отказы, которые не пройдут до конца прогона: модель с ними больше не вызывается
# этим экземпляром адаптера (экономия квоты и времени), пока не вызван reset_model_state().
STICKY = frozenset({ErrorKind.MODEL_UNAVAILABLE, ErrorKind.QUOTA_EXHAUSTED})


def _shared_error_base() -> type[Exception]:
    """Общий ProviderError из bootstrap (Max/№11), если он уже есть в пакете."""
    for name in ("bcc_review.providers.base", "bcc_review.providers.errors"):
        try:
            module = __import__(name, fromlist=["ProviderError"])
        except ImportError:
            continue
        base = getattr(module, "ProviderError", None)
        if isinstance(base, type) and issubclass(base, Exception):
            return base
    return Exception


class ProviderError(_shared_error_base()):  # type: ignore[misc]
    """Единственный тип ошибки, который выпускает ``invoke``."""

    def __init__(
        self,
        kind: ErrorKind | str,
        message: str,
        *,
        provider: str = PROVIDER,
        model: str | None = None,
        status: int | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
        retry_after_source: str | None = None,
        request_id: str | None = None,
        physical_calls: int = 0,
        attempts: list[dict[str, Any]] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        Exception.__init__(self, message)  # базовый класс bootstrap может иметь иную сигнатуру
        self.kind = ErrorKind(kind)
        self.message = message
        self.provider = provider
        self.model = model
        self.status = status
        self.retryable = self.kind in RETRYABLE if retryable is None else retryable
        self.retry_after = retry_after
        self.retry_after_source = retry_after_source
        self.request_id = request_id
        self.physical_calls = physical_calls
        self.attempts = attempts or []
        self.detail = detail or {}

    @property
    def fallback_eligible(self) -> bool:
        return self.kind in FALLBACK_ON

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind), "message": self.message, "provider": self.provider,
            "model": self.model, "status": self.status, "retryable": self.retryable,
            "retry_after": self.retry_after, "retry_after_source": self.retry_after_source,
            "request_id": self.request_id, "physical_calls": self.physical_calls,
            "attempts": self.attempts, "detail": self.detail,
        }

    def __str__(self) -> str:
        return self.message


# --------------------------------------------------------------------------- settings


def _env_float(environ: Mapping[str, str], name: str, default: float | None) -> float | None:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ProviderError(ErrorKind.CONFIG, f"{name}={raw!r}: ожидается число.") from None


def parse_model_list(raw: str | Iterable[str] | None) -> list[str]:
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    seen: list[str] = []
    for item in items:
        item = item.strip().removeprefix("models/")
        if item and item not in seen:
            seen.append(item)
    return seen


def settings_from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Настройки из окружения. Секрет не логируется и не попадает в ошибки."""
    env = os.environ if environ is None else environ
    budget = _env_float(env, "GEMINI_THINKING_BUDGET", None)
    max_tokens = _env_float(env, "GEMINI_MAX_OUTPUT_TOKENS", None)
    return {
        "api_key": (env.get("GEMINI_API_KEY") or "").strip() or None,
        "model": (env.get("GEMINI_MODEL") or "").strip().removeprefix("models/") or DEFAULT_MODEL,
        "fallback_models": parse_model_list(env.get("GEMINI_FALLBACK_MODELS")),
        "min_attempt_s": _env_float(env, "GEMINI_MIN_ATTEMPT_S", DEFAULT_MIN_ATTEMPT_S),
        "thinking_budget": None if budget is None else int(budget),
        "thinking_level": (env.get("GEMINI_THINKING_LEVEL") or "").strip() or None,
        "max_output_tokens": None if max_tokens is None else int(max_tokens),
        "temperature": _env_float(env, "GEMINI_TEMPERATURE", None),
    }


# --------------------------------------------------------------------------- schema

# Консервативное подмножество JSON Schema, которое отправляется в response_json_schema.
# Всё прочее удаляется с записью в журнал и проверяется локально по полной схеме.
_PASSTHROUGH = frozenset({
    "type", "title", "description", "enum", "required", "minItems", "maxItems",
    "minimum", "maximum",
})
_SCHEMA_MAPS = ("properties",)
_SCHEMA_LISTS = ("anyOf", "prefixItems")
_FORMATS = frozenset({"date-time", "date", "time"})
_SILENT_DROP = frozenset({"$schema", "$id", "$comment", "$defs", "definitions"})


class SchemaConversionError(ValueError):
    pass


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Any:
    if not ref.startswith("#"):
        raise SchemaConversionError(f"внешняя ссылка $ref не поддерживается: {ref}")
    node: Any = root
    for raw in [p for p in ref[1:].split("/") if p]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or key not in node:
            raise SchemaConversionError(f"$ref не найден: {ref}")
        node = node[key]
    return node


def to_gemini_schema(schema: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Явное приведение JSON Schema к подмножеству для Gemini.

    Возвращает (схема для провода, журнал изменений). Журнал попадает в meta и
    в отчёт о совместимости; полный контроль остаётся за локальной валидацией.
    """
    log: list[dict[str, str]] = []

    def note(path: str, keyword: str, action: str) -> None:
        log.append({"path": path or "/", "keyword": keyword, "action": action})

    def conv(node: Any, path: str, refs: tuple[str, ...]) -> Any:
        if isinstance(node, bool):
            return node
        if not isinstance(node, Mapping):
            raise SchemaConversionError(f"{path or '/'}: узел схемы должен быть объектом")
        if "$ref" in node:
            ref = node["$ref"]
            if ref in refs:
                raise SchemaConversionError(f"{path or '/'}: рекурсивная схема ({ref}) не поддерживается")
            target = _resolve_ref(schema, ref)
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            note(path, "$ref", f"inlined {ref}")
            return conv(merged, path, refs + (ref,))

        out: dict[str, Any] = {}
        for key, value in node.items():
            here = f"{path}/{key}"
            if key in _PASSTHROUGH:
                out[key] = copy.deepcopy(value)
            elif key in _SCHEMA_MAPS:
                out[key] = {name: conv(sub, f"{here}/{name}", refs) for name, sub in value.items()}
            elif key in _SCHEMA_LISTS:
                out.setdefault(key, []).extend(conv(sub, f"{here}/{i}", refs) for i, sub in enumerate(value))
            elif key in ("items", "additionalProperties"):
                out[key] = conv(value, here, refs)
            elif key == "oneOf":
                out.setdefault("anyOf", []).extend(conv(s, f"{here}/{i}", refs) for i, s in enumerate(value))
                note(path, key, "rewritten as anyOf")
            elif key == "const":
                out["enum"] = [copy.deepcopy(value)]
                note(path, key, "rewritten as enum")
            elif key == "format":
                if value in _FORMATS:
                    out[key] = value
                else:
                    note(path, f"format:{value}", "dropped")
            elif key in _SILENT_DROP:
                if not (key in ("$defs", "definitions") and path == ""):
                    note(path, key, "dropped")
            else:
                note(path, key, "dropped")

        types = out.get("type")
        if isinstance(types, list):
            del out["type"]
            if len(types) == 1:
                out["type"] = types[0]
            elif "anyOf" in out:
                note(path, "type[]", "dropped (anyOf already present)")
            else:
                shared: dict[str, Any] = {k: out.pop(k) for k in ("title", "description") if k in out}
                variants = []
                for t in types:
                    variant = {"type": t}
                    if t != "null":
                        variant.update({k: copy.deepcopy(v) for k, v in out.items()})
                    variants.append(variant)
                out = {**shared, "anyOf": variants}
                note(path, "type[]", "rewritten as anyOf")
        return out

    return conv(schema, "", ()), log


# --------------------------------------------------------------------------- messages


def _text_of(content: Any, index: int) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        chunks = []
        for block in content:
            is_text = isinstance(block, Mapping) and block.get("type", "text") == "text"
            if is_text and isinstance(block.get("text"), str):
                chunks.append(block["text"])
            else:
                raise ProviderError(ErrorKind.BAD_REQUEST,
                                    f"messages[{index}]: поддерживаются только текстовые блоки, получено {block!r:.80}")
        return "\n\n".join(chunks)
    raise ProviderError(ErrorKind.BAD_REQUEST, f"messages[{index}].content: ожидается строка или список блоков")


def to_gemini_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """system -> system_instruction; user -> user; assistant -> model; подряд идущие роли склеиваются."""
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    roles = {"user": "user", "assistant": "model", "model": "model"}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        text = _text_of(msg.get("content"), i)
        if role == "system":
            system.append(text)
            continue
        if role not in roles:
            raise ProviderError(ErrorKind.BAD_REQUEST, f"messages[{i}].role={role!r} не поддерживается")
        if contents and contents[-1]["role"] == roles[role]:
            contents[-1]["parts"].append({"text": text})
        else:
            contents.append({"role": roles[role], "parts": [{"text": text}]})
    if not any(c["role"] == "user" for c in contents):
        raise ProviderError(ErrorKind.BAD_REQUEST, "messages: нет ни одного сообщения пользователя")
    return ("\n\n".join(system) or None), contents


# --------------------------------------------------------------------------- error mapping

_RETRY_IN = re.compile(r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s)\b", re.IGNORECASE)
_SAFETY_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII",
                   "LANGUAGE", "IMAGE_SAFETY", "MODEL_ARMOR"}


def _duration_s(value: Any) -> float | None:
    if isinstance(value, str) and value.endswith("s"):
        try:
            return float(value[:-1])
        except ValueError:
            return None
    if isinstance(value, Mapping):  # {"seconds": .., "nanos": ..}
        return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
    return None


def _retry_after(details: list[Mapping[str, Any]], headers: Any, message: str) -> tuple[float | None, str | None]:
    """retry_after только из реальных данных ответа: RetryInfo, Retry-After, текст сервера."""
    for item in details:
        if str(item.get("@type", "")).endswith("google.rpc.RetryInfo"):
            seconds = _duration_s(item.get("retryDelay"))
            if seconds is not None:
                return seconds, "retry_info"
    raw = None
    try:
        raw = headers.get("retry-after") if headers is not None else None
    except Exception:  # noqa: BLE001 - заголовки разных транспортов
        raw = None
    if raw:
        raw = str(raw).strip()
        if raw.isdigit():
            return float(raw), "header"
        try:
            when = email.utils.parsedate_to_datetime(raw)
            return max(0.0, when.timestamp() - time.time()), "header"
        except (TypeError, ValueError):
            pass
    match = _RETRY_IN.search(message or "")
    if match:
        value = float(match.group(1))
        return (value / 1000 if match.group(2).lower() == "ms" else value), "message"
    return None, None


def _error_body(exc: Any) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    body = getattr(exc, "details", None)
    if isinstance(body, list) and len(body) == 1:
        body = body[0]
    if isinstance(body, Mapping) and isinstance(body.get("error"), Mapping):
        body = body["error"]
    body = dict(body) if isinstance(body, Mapping) else {}
    details = [d for d in body.get("details") or [] if isinstance(d, Mapping)]
    return body, details


def classify_api_error(exc: Any, model: str) -> ProviderError:
    """Переводит errors.APIError SDK в ProviderError с точной категорией."""
    body, details = _error_body(exc)
    code = int(getattr(exc, "code", None) or body.get("code") or 0)
    status = str(body.get("status") or getattr(exc, "status", "") or "")
    server_msg = str(body.get("message") or getattr(exc, "message", "") or "").strip()
    reasons = {str(d.get("reason")) for d in details if d.get("reason")}
    violations = [v for d in details for v in d.get("violations") or [] if isinstance(v, Mapping)]
    quota_ids = [str(v.get("quotaId", "")) for v in violations if v.get("quotaId")]
    headers = getattr(getattr(exc, "response", None), "headers", None)
    retry_after, source = _retry_after(details, headers, server_msg)
    detail: dict[str, Any] = {"http_status": code, "status": status, "server_message": server_msg[:500]}
    if reasons:
        detail["reasons"] = sorted(reasons)
    if quota_ids:
        detail["quota_ids"] = quota_ids
    low = server_msg.lower()
    where = f"{code} {status}".strip()

    def err(kind: ErrorKind, text: str, **kw: Any) -> ProviderError:
        return ProviderError(kind, text, model=model, status=code or None, retry_after=retry_after,
                             retry_after_source=source, detail=detail, **kw)

    if "API_KEY_INVALID" in reasons or "api key not valid" in low or "api key expired" in low:
        return err(ErrorKind.AUTH, f"Gemini отклонил ключ API ({where}, API_KEY_INVALID). "
                                   f"Проверьте GEMINI_API_KEY в .env. {KEY_HELP}")
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        quota = ", ".join(quota_ids) or "квота не указана"
        limit_zero = any(str(v.get("quotaValue", "")).strip() == "0" for v in violations) or "limit: 0" in low
        per_day = any("perday" in q.lower() for q in quota_ids)
        if limit_zero:
            detail["limit_zero"] = True
            return err(ErrorKind.QUOTA_EXHAUSTED, f"У модели {model} для этого ключа нулевая квота ({quota}): "
                                                  f"на бесплатном тарифе модель недоступна. {MODELS_HELP}",
                       retryable=False)
        if per_day:
            return err(ErrorKind.QUOTA_EXHAUSTED, f"Исчерпана дневная квота модели {model} ({quota}). Повтор в этом "
                                                  f"запуске бесполезен: дождитесь сброса квоты, задайте другую модель "
                                                  "(GEMINI_MODEL / GEMINI_FALLBACK_MODELS) или другой ключ.",
                       retryable=False)
        wait = f" Сервер просит повторить через {retry_after:g} с." if retry_after is not None else ""
        return err(ErrorKind.RATE_LIMITED, f"Превышен лимит запросов к модели {model} ({where}; {quota}).{wait}")
    if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return err(ErrorKind.AUTH, f"Gemini запретил доступ ({where}): {server_msg or 'нет доступа'}. "
                                   "Проверьте GEMINI_API_KEY и что Generative Language API включён "
                                   f"для проекта ключа. {KEY_HELP}")
    if code == 400 and status == "FAILED_PRECONDITION":
        return err(ErrorKind.AUTH, f"Gemini недоступен для этого ключа ({where}): {server_msg}. "
                                   "Обычно это регион без бесплатного тарифа или не подключённый биллинг.")
    if code == 404 or status == "NOT_FOUND" or ("not found" in low and "model" in low):
        return err(ErrorKind.MODEL_UNAVAILABLE, f"Модель {model} недоступна этому ключу или снята с API ({where}). "
                                                f"{MODELS_HELP}; затем задайте GEMINI_MODEL.")
    if code in (408, 504) or status == "DEADLINE_EXCEEDED":
        return err(ErrorKind.TIMEOUT, f"Gemini не уложился во время ответа ({where}) для модели {model}.")
    if code in (500, 502, 503) or status in ("UNAVAILABLE", "INTERNAL"):
        return err(ErrorKind.OVERLOADED, f"Модель {model} временно перегружена или недоступна ({where}).")
    if 400 <= code < 500:
        if "schema" in low:
            detail["schema_rejected"] = True
        return err(ErrorKind.BAD_REQUEST, f"Gemini отклонил запрос ({where}): {server_msg[:300]}")
    if code >= 500:
        return err(ErrorKind.OVERLOADED, f"Сбой сервера Gemini ({where}) для модели {model}.")
    return err(ErrorKind.UNKNOWN, f"Неожиданный ответ Gemini ({where}): {server_msg[:300]}")


def _transport_kind(exc: BaseException) -> ErrorKind | None:
    names = {f"{c.__module__.split('.')[0]}.{c.__name__}" for c in type(exc).__mro__}
    libs = ("httpx", "httpx2")
    if any(f"{lib}.TimeoutException" in names for lib in libs) or isinstance(exc, TimeoutError):
        return ErrorKind.TIMEOUT
    if any(f"{lib}.TransportError" in names for lib in libs) or isinstance(exc, ConnectionError):
        return ErrorKind.NETWORK
    return None


# --------------------------------------------------------------------------- adapter


def _sdk() -> tuple[Any, Any, Any]:
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise ProviderError(ErrorKind.CONFIG, "Не установлен пакет google-genai: pip install google-genai "
                                              f"({exc}).", retryable=False) from None
    return genai, types, errors


def _validator(schema: Mapping[str, Any]) -> Any:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise ProviderError(ErrorKind.CONFIG, "Не установлен пакет jsonschema: pip install jsonschema") from None
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001 - jsonschema.SchemaError
        raise ProviderError(ErrorKind.BAD_REQUEST, f"Схема этапа некорректна: {getattr(exc, 'message', exc)}") from None
    return Draft202012Validator(schema)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3]
        stripped = stripped[4:] if stripped[:4].lower() == "json" else stripped
    return stripped.strip()


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "name", None) or getattr(value, "value", None) or value)


def _usage(meta: Any) -> dict[str, int | None]:
    def get(name: str) -> int | None:
        value = getattr(meta, name, None) if meta is not None else None
        return int(value) if value is not None else None
    return {
        "input_tokens": get("prompt_token_count"),
        "output_tokens": get("candidates_token_count"),
        "thinking_tokens": get("thoughts_token_count"),
        "cached_tokens": get("cached_content_token_count"),
        "total_tokens": get("total_token_count"),
    }


class GeminiAdapter:
    """Gemini через официальный SDK ``google-genai``.

    ``http_client`` (httpx/httpx2 Client) и ``clock`` подменяются в тестах.
    """

    name = PROVIDER

    def __init__(
        self,
        api_key: str | None = None,
        *,
        fallback_models: Iterable[str] | str | None = None,
        min_attempt_s: float = DEFAULT_MIN_ATTEMPT_S,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
        fallback_on: Iterable[ErrorKind | str] = FALLBACK_ON,
        http_client: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self.fallback_models = parse_model_list(fallback_models)
        self.min_attempt_s = float(min_attempt_s)
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thinking_budget = thinking_budget
        self.thinking_level = thinking_level
        self.fallback_on = frozenset(ErrorKind(k) for k in fallback_on)
        self._http_client = http_client
        self._clock = clock
        self._client: Any = None
        self._sticky: dict[str, ProviderError] = {}
        self._schemas: dict[str, tuple[dict[str, Any], list[dict[str, str]], Any]] = {}

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **overrides: Any) -> GeminiAdapter:
        cfg = settings_from_env(environ)
        cfg.pop("model")
        cfg.update(overrides)
        return cls(**cfg)

    # -- client ---------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderError(ErrorKind.CONFIG, "Не задан GEMINI_API_KEY. Добавьте строку GEMINI_API_KEY=<ключ> "
                                                      f"в .env или в окружение. {KEY_HELP}", retryable=False)
            genai, types, _ = _sdk()
            options = types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1),  # повторы делает runtime, не SDK
                httpx_client=self._http_client,
            )
            self._client = genai.Client(api_key=self._api_key, http_options=options)
        return self._client

    def reset_model_state(self) -> None:
        """Забыть модели, отключённые в этом прогоне (квота, 404)."""
        self._sticky.clear()

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
        self._client = None

    # -- helpers --------------------------------------------------------------

    def model_chain(self, model: str) -> list[str]:
        primary = (model or "").strip().removeprefix("models/")
        if not primary:
            raise ProviderError(ErrorKind.CONFIG, f"Не указана модель Gemini (GEMINI_MODEL). {MODELS_HELP}")
        return parse_model_list([primary, *self.fallback_models])

    def _schema_bundle(self, schema: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]], Any]:
        key = json.dumps(schema, sort_keys=True, ensure_ascii=False)
        if key not in self._schemas:
            validator = _validator(schema)
            try:
                wire, log = to_gemini_schema(schema)
            except SchemaConversionError as exc:
                raise ProviderError(ErrorKind.BAD_REQUEST, f"Схему нельзя передать в Gemini: {exc}") from None
            self._schemas[key] = (wire, log, validator)
        return self._schemas[key]

    def _config(self, types: Any, model: str, system: str | None, wire: dict[str, Any],
                remaining_s: float, temperature: float | None, max_output_tokens: int | None) -> Any:
        if temperature is None:
            # Для Gemini 3 Google советует температуру по умолчанию; для 2.x фиксируем 0.
            temperature = None if model.startswith("gemini-3") else 0.0
        thinking = None
        if self.thinking_budget is not None or self.thinking_level:
            thinking = types.ThinkingConfig(thinking_budget=self.thinking_budget,
                                            thinking_level=(self.thinking_level or "").upper() or None)
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=wire,
            candidate_count=1,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_config=thinking,
            http_options=types.HttpOptions(timeout=max(1000, int(remaining_s * 1000))),
        )

    def _accept(self, response: Any, model: str, validator: Any) -> tuple[Any, dict[str, Any]]:
        """Проверка ответа: только STOP + непустой текст + JSON + полная схема."""
        usage = _usage(getattr(response, "usage_metadata", None))
        request_id = getattr(response, "response_id", None)
        info = {"usage": usage, "model_version": getattr(response, "model_version", None)}

        def fail(kind: ErrorKind, text: str, **detail: Any) -> ProviderError:
            # retryable берётся из категории: EMPTY/INVALID_OUTPUT — да, TRUNCATED/BLOCKED — нет.
            return ProviderError(kind, text, model=model, request_id=request_id, detail={**info, **detail})

        feedback = getattr(response, "prompt_feedback", None)
        block = _enum_name(getattr(feedback, "block_reason", None))
        if block and block != "BLOCKED_REASON_UNSPECIFIED":
            raise fail(ErrorKind.BLOCKED, f"Gemini заблокировал запрос фильтром ({block}).", block_reason=block)
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise fail(ErrorKind.EMPTY, "Gemini вернул ответ без кандидатов: content пуст.")
        candidate = candidates[0]
        finish = _enum_name(getattr(candidate, "finish_reason", None))
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        info["finish_reason"] = finish
        if finish == "MAX_TOKENS":
            raise fail(ErrorKind.TRUNCATED,
                       f"Ответ Gemini обрезан по лимиту выходных токенов (MAX_TOKENS): выдано "
                       f"{usage['output_tokens']} ток., рассуждения {usage['thinking_tokens']} ток. "
                       "JSON неполный, результат не принят.", text_chars=len(text))
        if finish in _SAFETY_REASONS:
            raise fail(ErrorKind.BLOCKED, f"Gemini остановил ответ фильтром ({finish}).")
        if not text.strip():
            raise fail(ErrorKind.EMPTY, f"Gemini вернул пустой content (finish_reason={finish}).")
        if finish != "STOP":
            raise fail(ErrorKind.INVALID_OUTPUT, f"Ответ Gemini не завершён штатно (finish_reason={finish}).")
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError as exc:
            raise fail(ErrorKind.INVALID_OUTPUT, f"Ответ Gemini не является JSON: {exc.msg} (позиция {exc.pos}).",
                       snippet=text[:200]) from None
        problems = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if problems:
            listed = [{"path": "/" + "/".join(map(str, e.absolute_path)), "error": e.message[:200]}
                      for e in problems[:5]]
            first = listed[0]
            raise fail(ErrorKind.INVALID_OUTPUT, f"Ответ Gemini не прошёл проверку по схеме: {first['path']}: "
                                                 f"{first['error']} (всего нарушений: {len(problems)}).",
                       violations=listed)
        return data, {**info, "request_id": request_id}

    # -- public ---------------------------------------------------------------

    def invoke(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
        timeout_s: float,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        started = self._clock()
        deadline = started + float(timeout_s)
        chain = self.model_chain(model)
        system, contents = to_gemini_messages(messages)
        wire, schema_log, validator = self._schema_bundle(schema)
        client = self._get_client()
        _, types, errors = _sdk()
        max_tokens = max_output_tokens if max_output_tokens is not None else self.max_output_tokens
        temp = temperature if temperature is not None else self.temperature

        attempts: list[dict[str, Any]] = []
        calls = 0
        last: ProviderError | None = None
        for index, current in enumerate(chain):
            earlier = self._sticky.get(current)
            if earlier is not None:
                attempts.append({"model": current, "skipped": str(earlier.kind), "earlier_in_run": True})
                last = ProviderError(earlier.kind, earlier.message, model=current, status=earlier.status,
                                     retryable=earlier.retryable, retry_after=earlier.retry_after,
                                     retry_after_source=earlier.retry_after_source,
                                     detail={**earlier.detail, "remembered": True})
                continue
            remaining = deadline - self._clock()
            if index > 0 and remaining < self.min_attempt_s:
                attempts.append({"model": current, "skipped": "budget", "remaining_s": round(max(remaining, 0.0), 3)})
                break
            if remaining <= 0:
                last = ProviderError(ErrorKind.TIMEOUT, f"Бюджет вызова Gemini ({timeout_s:g} с) исчерпан до запроса.",
                                     model=current, detail={"reason": "budget_exhausted_before_call"})
                break
            call_started = self._clock()
            calls += 1
            try:
                response = client.models.generate_content(
                    model=current, contents=contents,
                    config=self._config(types, current, system, wire, remaining, temp, max_tokens))
                data, info = self._accept(response, current, validator)
            except ProviderError as exc:
                last = exc
            except errors.APIError as exc:
                last = classify_api_error(exc, current)
            except Exception as exc:  # noqa: BLE001 - наружу выходит только ProviderError
                kind = _transport_kind(exc)
                if kind is ErrorKind.TIMEOUT:
                    last = ProviderError(kind, f"Gemini не ответил за {remaining:.0f} с (модель {current}).",
                                         model=current)
                elif kind is ErrorKind.NETWORK:
                    last = ProviderError(kind, f"Нет соединения с {API_HOST}: {type(exc).__name__}: {exc}. "
                                               "Проверьте сеть и прокси.", model=current)
                elif isinstance(exc, errors.UnknownApiResponseError):
                    last = ProviderError(ErrorKind.INVALID_OUTPUT, f"Gemini вернул нечитаемый ответ: {exc}",
                                         model=current)
                else:
                    last = ProviderError(ErrorKind.UNKNOWN, f"Сбой вызова Gemini: {type(exc).__name__}: {exc}",
                                         model=current, retryable=False)
            else:
                version = info.get("model_version")
                return {
                    "data": data,
                    "usage": {**info["usage"], "physical_calls": calls},
                    "model": version or current,
                    "request_id": info.get("request_id"),
                    "meta": {
                        "provider": PROVIDER,
                        "requested_model": chain[0],
                        "called_model": current,
                        "model_version": version,
                        "fallback_used": current != chain[0],
                        "attempts": attempts,
                        "finish_reason": info.get("finish_reason"),
                        "schema_adjustments": schema_log,
                        "latency_s": round(self._clock() - call_started, 3),
                    },
                }
            attempts.append({"model": current, "kind": str(last.kind), "status": last.status,
                             "retry_after": last.retry_after, "elapsed_s": round(self._clock() - call_started, 3)})
            if last.kind in STICKY:
                self._sticky[current] = last
            if last.kind not in self.fallback_on:
                break

        assert last is not None
        last.physical_calls = calls
        last.attempts = attempts
        last.detail.setdefault("requested_model", chain[0])
        last.detail["model_chain"] = chain
        raise last

    def list_models(self) -> list[dict[str, Any]]:
        """Модели, которые ключ может вызывать через generateContent."""
        client = self._get_client()
        _, _, errors = _sdk()
        try:
            models = list(client.models.list(config={"page_size": 200}))
        except errors.APIError as exc:
            raise classify_api_error(exc, "models.list") from None
        rows = []
        for item in models:
            actions = list(getattr(item, "supported_actions", None) or [])
            if "generateContent" not in actions:
                continue
            rows.append({
                "id": str(item.name).removeprefix("models/"),
                "display_name": getattr(item, "display_name", None),
                "input_token_limit": getattr(item, "input_token_limit", None),
                "output_token_limit": getattr(item, "output_token_limit", None),
                "flash": "flash" in str(item.name),
            })
        return sorted(rows, key=lambda r: (not r["flash"], r["id"]))


# --------------------------------------------------------------------------- CLI

# Общая синтетическая схема этапа (копия tests/p12/fixtures/synthetic_schema.json, равенство проверяет тест).
DOCTOR_SCHEMA: dict[str, Any] = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
 '$id': 'bcc_review/synthetic/stage-candidates-v1',
 'title': 'Синтетическая схема этапа: кандидаты в замечания',
 'description': 'Общая фикстура №11/№12 до публикации contracts/v1.json. Форма Candidate — по контракту v1.',
 'type': 'object',
 'additionalProperties': False,
 'required': ['stage', 'candidates', 'notes'],
 'properties': {'stage': {'const': 'requirement_check'},
                'candidates': {'type': 'array', 'minItems': 0, 'items': {'$ref': '#/$defs/candidate'}},
                'notes': {'type': ['string', 'null'], 'description': 'Пояснение модели или null'}},
 '$defs': {'hint': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['block_id', 'quote'],
                    'properties': {'block_id': {'type': 'string', 'pattern': '^b[0-9]+$'},
                                   'quote': {'type': 'string',
                                             'minLength': 1,
                                             'description': 'Дословная подстрока block.text'},
                                   'context': {'type': 'string'}}},
           'candidate': {'type': 'object',
                         'additionalProperties': False,
                         'required': ['scope',
                                      'kind',
                                      'criterion',
                                      'severity',
                                      'title',
                                      'impact',
                                      'req_ids',
                                      'hints'],
                         'properties': {'scope': {'enum': ['requirement', 'set']},
                                        'kind': {'enum': ['ambiguity',
                                                          'unverifiable',
                                                          'incomplete',
                                                          'conflict',
                                                          'omission',
                                                          'design_leak',
                                                          'non_singular',
                                                          'terminology']},
                                        'criterion': {'type': 'string',
                                                      'pattern': '^(И[1-9]|Н[1-8])$',
                                                      'description': 'Код критерия И1–И9 или Н1–Н8'},
                                        'severity': {'enum': ['critical', 'major', 'minor']},
                                        'title': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                                        'impact': {'type': 'string'},
                                        'req_ids': {'type': 'array',
                                                    'items': {'type': 'string', 'pattern': '^R-[0-9]{3}$'}},
                                        'hints': {'type': 'array', 'items': {'$ref': '#/$defs/hint'}},
                                        'inspected_block_ids': {'type': 'array',
                                                                'uniqueItems': True,
                                                                'items': {'type': 'string'}}}}}}
DOCTOR_MESSAGES = [
    {"role": "system", "content": "Ты проверяешь требования по ISO/IEC/IEEE 29148. Отвечай только JSON по схеме, "
                                  "stage = 'requirement_check', тексты на русском. Цитата в hints — дословная "
                                  "подстрока блока."},
    {"role": "user", "content": "Требование R-001, блок b1: «Система должна быстро отправлять push клиенту.»\n"
                                "Требование R-002, блок b2: «Порог задаётся от 1 000 до 1 000 000 ₸.»\n"
                                "Найди дефекты формулировок."},
]
EXIT_CODES = {ErrorKind.CONFIG: 2, ErrorKind.AUTH: 2, ErrorKind.RATE_LIMITED: 3,
              ErrorKind.QUOTA_EXHAUSTED: 3, ErrorKind.MODEL_UNAVAILABLE: 4}


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m bcc_review.providers.gemini",
                                     description="Проверка ключа и моделей Gemini для bcc_review")
    parser.add_argument("command", choices=["models", "doctor"])
    parser.add_argument("--model", help=f"модель (по умолчанию GEMINI_MODEL или {DEFAULT_MODEL})")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)
    try:
        settings = settings_from_env()
        adapter = GeminiAdapter.from_env()
        if args.command == "models":
            _print(adapter.list_models())
            return 0
        genai, _, _ = _sdk()
        result = adapter.invoke(model=args.model or settings["model"], messages=DOCTOR_MESSAGES,
                                schema=DOCTOR_SCHEMA, timeout_s=args.timeout)
        meta = result["meta"]
        _print({"ok": True, "sdk": getattr(genai, "__version__", None),
                "requested_model": meta["requested_model"], "model": result["model"],
                "called_model": meta["called_model"], "fallback_used": meta["fallback_used"],
                "request_id": result["request_id"], "latency_s": meta["latency_s"], "usage": result["usage"],
                "finish_reason": meta["finish_reason"], "candidates": len(result["data"]["candidates"]),
                "schema_adjustments": len(meta["schema_adjustments"])})
        return 0
    except ProviderError as exc:
        _print({"ok": False, **exc.to_dict()})
        return EXIT_CODES.get(exc.kind, 1)


if __name__ == "__main__":
    sys.exit(main())
