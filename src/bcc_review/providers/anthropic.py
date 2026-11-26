"""Основной клиент Claude API для bcc_review (направление №11).

Публичный контракт (согласован с движком Max):

    AnthropicAdapter.invoke(*, model, messages, schema, timeout_s)
        -> {"data": <объект по схеме>, "usage": {...}, "model": <фактическая модель>,
            "request_id": <request-id ответа>}

Любая ошибка интеграции поднимается как ``ProviderError(kind, retry_after_s=None)``
из общей библиотеки. Внешний бюджет повторов и кэш принадлежат Max, поэтому
собственные повторы SDK выключены (``max_retries=0``): один ``invoke`` даёт ровно
один физический POST /v1/messages. Каждый физический HTTP-запрос (включая
повторы, если их всё же включить) считается через event hook httpx2 и
передаётся в общий счётчик ``on_physical_call``.

Ответ модели запрашивается в режиме JSON outputs (``output_config.format``).
Ограничения, которые API не принимает (minLength, minimum, maxItems, pattern и
т. п.), переносятся в description схемы запроса, а полная исходная схема
проверяется локально через jsonschema. Поля ``block_id`` и ``quote`` в данных —
обычные строки: координаты и сверку с первоисточником делает №07.

Подставной транспорт (``RecordedTransport``) подключается вместо сетевого на
уровне httpx2, поэтому записанные ответы проходят через тот же SDK, ту же
проверку ответа и ту же классификацию ошибок, что и боевые.
"""

from __future__ import annotations

import copy
import datetime as _dt
import email.utils
import importlib
import json
import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, MutableMapping, Sequence

import anthropic
import httpx2
import jsonschema

log = logging.getLogger(__name__)

PROVIDER = "anthropic"
ADAPTER_VERSION = "p11-1"

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"
DEFAULT_FALLBACKS = "default"
DEFAULT_MODEL_CHECK_TIMEOUT_S = 30.0
OFFICIAL_BASE_URL = "https://api.anthropic.com"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

#: Переменные окружения, которые читает адаптер (для README и .env.example, №18).
ENV_VARS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "ключ Claude API (обязателен для живого режима; секрет, в git не класть)",
    "ANTHROPIC_MODEL": f"идентификатор модели, по умолчанию {DEFAULT_MODEL}",
    "ANTHROPIC_MAX_TOKENS": f"потолок ответа в токенах, по умолчанию {DEFAULT_MAX_TOKENS}",
    "ANTHROPIC_EFFORT": f"low|medium|high|xhigh|max, пусто = не передавать; по умолчанию {DEFAULT_EFFORT}",
    "ANTHROPIC_FALLBACKS": "default | off | список моделей через запятую; по умолчанию default",
    "ANTHROPIC_BASE_URL": f"не задавать для сдачи; по умолчанию {OFFICIAL_BASE_URL}",
}


# --------------------------------------------------------------------------- #
# ProviderError: общий контракт Max. До публикации bootstrap — совместимая копия.
# --------------------------------------------------------------------------- #

_SHARED_ERROR_MODULES = ("bcc_review.providers.base", "bcc_review.errors")


def _load_shared_provider_error() -> tuple[type[Exception] | None, str | None]:
    for name in _SHARED_ERROR_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        cls = getattr(module, "ProviderError", None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls, name
    return None, None


class _BootstrapProviderError(Exception):
    """Временная копия контракта ``ProviderError(kind, retry_after_s=None)``.

    Используется, только пока общая библиотека Max не опубликована. Стыковой
    тест ``tests/p11/test_joint_contract.py`` проверяет, что после публикации
    адаптер берёт общий класс.
    """

    def __init__(self, kind: str, retry_after_s: float | None = None) -> None:
        super().__init__(kind, retry_after_s)
        self.kind = kind
        self.retry_after_s = retry_after_s

    def __str__(self) -> str:
        detail = getattr(self, "detail", None)
        return f"{self.kind}: {detail}" if detail else str(self.kind)


_shared_cls, _shared_module = _load_shared_provider_error()
ProviderError: type[Exception] = _shared_cls or _BootstrapProviderError
PROVIDER_ERROR_SOURCE: str = _shared_module or "bootstrap-fallback"


# --------------------------------------------------------------------------- #
# Категории ошибок
# --------------------------------------------------------------------------- #

KIND_AUTH = "auth"
KIND_QUOTA = "quota_exhausted"
KIND_RATE_LIMIT = "rate_limited"
KIND_OVERLOADED = "overloaded"
KIND_TIMEOUT = "timeout"
KIND_INCOMPLETE = "incomplete"
KIND_SCHEMA = "schema_violation"
KIND_REFUSAL = "refusal"
KIND_BAD_REQUEST = "invalid_request"
KIND_MODEL_NOT_FOUND = "model_not_found"
KIND_SERVER = "server_error"
KIND_NETWORK = "network"
KIND_UNKNOWN = "unknown"

#: kind -> (можно ли повторить тот же запрос, описание для отчёта и журнала)
ERROR_KINDS: dict[str, tuple[bool, str]] = {
    KIND_AUTH: (False, "отказ авторизации или доступа (401/403, ключ не задан)"),
    KIND_QUOTA: (False, "исчерпана квота или кредит (402, 429 со spend-limit)"),
    KIND_RATE_LIMIT: (True, "временный лимит запросов (429), ждать retry_after_s"),
    KIND_OVERLOADED: (True, "перегрузка API (529 overloaded_error)"),
    KIND_TIMEOUT: (True, "тайм-аут клиента или шлюза (408/504)"),
    KIND_INCOMPLETE: (False, "неполный ответ: stop_reason max_tokens и подобные"),
    KIND_SCHEMA: (True, "ответ не прошёл JSON-схему или не является JSON"),
    KIND_REFUSAL: (False, "модель отказалась отвечать (stop_reason refusal)"),
    KIND_BAD_REQUEST: (False, "некорректный запрос (400/413/422)"),
    KIND_MODEL_NOT_FOUND: (False, "модель не найдена или недоступна ключу (404)"),
    KIND_SERVER: (True, "ошибка сервера API (500/502/503)"),
    KIND_NETWORK: (True, "сетевая ошибка до получения ответа"),
    KIND_UNKNOWN: (False, "не удалось однозначно классифицировать"),
}

_QUOTA_ERROR_CODES = frozenset(
    {
        "enforced_spend_limit_reached",
        "contract_spend_limit_reached",
        "linked_organization_spend_limit_reached",
        "linked_organization_billing_unavailable",
    }
)


def _make_error(kind: str, retry_after_s: float | None = None, **attrs: Any) -> Exception:
    """Создать ProviderError по контракту и добавить диагностические атрибуты.

    Конструктор вызывается строго с ``(kind, retry_after_s)``, остальные поля
    ставятся атрибутами, чтобы не зависеть от сигнатуры общего класса.
    """
    err = ProviderError(kind, retry_after_s)
    defaults: dict[str, Any] = {
        "provider": PROVIDER,
        "subkind": None,
        "detail": ERROR_KINDS.get(kind, (False, ""))[1],
        "http_status": None,
        "error_type": None,
        "error_code": None,
        "request_id": None,
        "requested_model": None,
        "model": None,
        "usage": None,
        "retryable": ERROR_KINDS.get(kind, (False, ""))[0],
        "ambiguous": False,
        "alternatives": (),
    }
    defaults.update(attrs)
    for key, value in defaults.items():
        if key in ("kind", "retry_after_s"):
            continue
        try:
            setattr(err, key, value)
        except AttributeError:  # общий класс со __slots__: оставляем только контракт
            pass
    return err


# --------------------------------------------------------------------------- #
# Защита секретов в сообщениях и журнале
# --------------------------------------------------------------------------- #

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{4,}"), "sk-ant-***"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 ***"),
    (
        re.compile(r"(?i)\b(x-api-key|authorization|anthropic-api-key)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"),
        r"\1\2***",
    ),
)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Убрать из строки ключи, bearer-токены и значения приватных заголовков."""
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _truncate(text: str | None, limit: int = 300) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Retry-After
# --------------------------------------------------------------------------- #


def parse_retry_after(headers: Mapping[str, str], *, now: _dt.datetime | None = None) -> float | None:
    """Секунды ожидания из ``retry-after-ms`` или ``retry-after`` (число или HTTP-дата)."""
    raw_ms = headers.get("retry-after-ms")
    if raw_ms:
        try:
            return max(0.0, float(raw_ms) / 1000.0)
        except ValueError:
            pass
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return max(0.0, (when - now).total_seconds())


# --------------------------------------------------------------------------- #
# Схема: исходная (проверяется локально) -> схема запроса (принимает API)
# --------------------------------------------------------------------------- #

_SUPPORTED_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)
_PASS_THROUGH = frozenset({"type", "required", "$ref", "enum", "const", "description", "title", "default"})
_META = frozenset({"$schema", "$id", "$comment", "examples"})


def to_wire_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Привести JSON Schema к подмножеству, которое принимает structured outputs.

    Неподдержанные ограничения не теряются: они дописываются в description,
    чтобы модель их видела, а исполнение проверяет локальный валидатор.
    Поддерживает ``"type": [..., "null"]``, на котором падает ``anthropic.transform_schema``.
    """
    return _wire(copy.deepcopy(dict(schema)))


def _is_object_schema(node: Mapping[str, Any]) -> bool:
    typ = node.get("type")
    if typ == "object" or (isinstance(typ, list) and "object" in typ):
        return True
    return typ is None and "properties" in node


def _wire(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _wire(sub) for name, sub in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _wire(value)
        elif key in ("anyOf", "allOf") and isinstance(value, list):
            out[key] = [_wire(sub) for sub in value]
        elif key == "oneOf" and isinstance(value, list):
            out["anyOf"] = [_wire(sub) for sub in value]
        elif key in ("$defs", "definitions") and isinstance(value, dict):
            out[key] = {name: _wire(sub) for name, sub in value.items()}
        elif key in _PASS_THROUGH:
            out[key] = value
        elif key == "additionalProperties":
            if value not in (False, None):
                extras[key] = value if isinstance(value, bool) else "schema"
        elif key == "format":
            if value in _SUPPORTED_FORMATS:
                out[key] = value
            else:
                extras[key] = value
        elif key == "minItems":
            if value in (0, 1):
                out[key] = value
            else:
                extras[key] = value
        elif key in _META:
            continue
        else:
            extras[key] = value
    if _is_object_schema(out):
        out.setdefault("properties", {})
        out["additionalProperties"] = False
    if extras:
        note = "{" + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(extras.items())) + "}"
        out["description"] = f"{out['description']}\n\n{note}" if out.get("description") else note
    return out


def _iter_errors_deep(errors: Iterable[jsonschema.ValidationError]) -> Iterator[jsonschema.ValidationError]:
    for err in errors:
        yield err
        if err.context:
            yield from _iter_errors_deep(err.context)


def _set_at(root: Any, path: Sequence[Any], value: Any) -> bool:
    if not path:
        return False
    node = root
    for step in list(path)[:-1]:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return False
    try:
        node[path[-1]] = value
    except (KeyError, IndexError, TypeError):
        return False
    return True


def normalize_enum_case(instance: Any, validator: jsonschema.protocols.Validator) -> int:
    """Исправить регистр строк enum/const, если совпадение единственно.

    Документация structured outputs не гарантирует регистр значений enum.
    Возвращает число исправлений (записывается в журнал вызова).
    """
    fixed = 0
    for _ in range(64):
        changed = False
        for err in _iter_errors_deep(validator.iter_errors(instance)):
            if err.validator not in ("enum", "const") or not isinstance(err.instance, str):
                continue
            options = err.validator_value if err.validator == "enum" else [err.validator_value]
            matches = [o for o in options if isinstance(o, str) and o.casefold() == err.instance.casefold()]
            if len(set(matches)) == 1 and _set_at(instance, list(err.absolute_path), matches[0]):
                fixed += 1
                changed = True
                break
        if not changed:
            break
    return fixed


# --------------------------------------------------------------------------- #
# Подставной транспорт для записанных ответов API
# --------------------------------------------------------------------------- #

_RAISE_KINDS: dict[str, type[httpx2.TransportError]] = {
    "timeout": httpx2.ReadTimeout,
    "connect_timeout": httpx2.ConnectTimeout,
    "connect": httpx2.ConnectError,
}


def load_fixture(path: str | os.PathLike[str]) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class RecordedTransport(httpx2.BaseTransport):
    """Отдаёт записанные HTTP-ответы Claude API по очереди.

    Формат записи: ``{"response": {"status", "headers", "body"|"text"}}`` или
    ``{"raise": "timeout"|"connect_timeout"|"connect"}``. Ответы GET
    /v1/models/{id} берутся из ``models``; модели нет — честный 404 API.
    Сохраняются только метод, путь, тело запроса и имена заголовков (без значений).
    """

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]] = (),
        *,
        models: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._queue: deque[Mapping[str, Any]] = deque(records)
        self._models = {k: v for k, v in (models or {}).items() if not k.startswith("_")}  # "_synthetic" и т. п.
        self.requests: list[dict[str, Any]] = []
        self.names: list[str] = [str(r.get("name", "")) for r in records]

    @property
    def remaining(self) -> int:
        return len(self._queue)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "json": body,
                "header_names": sorted(request.headers.keys()),
            }
        )
        if request.method == "GET" and request.url.path.startswith("/v1/models/"):
            model_id = request.url.path.rsplit("/", 1)[-1]
            info = self._models.get(model_id)
            if info is None:
                return httpx2.Response(
                    404,
                    headers={"request-id": "req_mock_models_404"},
                    json={
                        "type": "error",
                        "error": {"type": "not_found_error", "message": f"model: {model_id}"},
                        "request_id": "req_mock_models_404",
                    },
                )
            return httpx2.Response(200, headers={"request-id": "req_mock_models"}, json=dict(info))
        if not self._queue:
            raise RuntimeError("RecordedTransport: записанные ответы закончились")
        record = self._queue.popleft()
        if "raise" in record:
            exc_cls = _RAISE_KINDS[str(record["raise"])]
            raise exc_cls(f"mock {record['raise']}", request=request)
        resp = record["response"]
        headers = dict(resp.get("headers") or {})
        if "text" in resp:
            return httpx2.Response(int(resp["status"]), headers=headers, text=str(resp["text"]))
        return httpx2.Response(int(resp["status"]), headers=headers, json=resp.get("body"))


# --------------------------------------------------------------------------- #
# Адаптер
# --------------------------------------------------------------------------- #

_OK_STOP = frozenset({"end_turn", "stop_sequence"})
_INCOMPLETE_STOP = frozenset({"max_tokens", "model_context_window_exceeded", "pause_turn", "tool_use", "compaction"})


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом, получено {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} должен быть больше нуля")
    return value


def _parse_effort(raw: str | None) -> str | None:
    if raw is None:
        return DEFAULT_EFFORT
    raw = raw.strip().lower()
    if raw in ("", "none", "off", "default"):
        return None
    if raw not in EFFORT_LEVELS:
        raise ValueError(f"ANTHROPIC_EFFORT: ожидается одно из {EFFORT_LEVELS}, получено {raw!r}")
    return raw


def _parse_fallbacks(raw: str | Sequence[str] | None) -> str | list[dict[str, str]] | None:
    if raw is None:
        return DEFAULT_FALLBACKS
    if not isinstance(raw, str):
        models = [m for m in raw if m]
        return [{"model": m} for m in models] or None
    raw = raw.strip()
    if raw.lower() in ("", "off", "none", "false", "0"):
        return None
    if raw.lower() == "default":
        return "default"
    return [{"model": m.strip()} for m in raw.split(",") if m.strip()]


def _dump(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


class AnthropicAdapter:
    """Адаптер официального Messages API (SDK ``anthropic``) под контракт ``invoke``."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        fallbacks: str | Sequence[str] | None = None,
        base_url: str | None = None,
        transport: httpx2.BaseTransport | None = None,
        mode: str | None = None,
        on_physical_call: Callable[[dict[str, Any]], None] | None = None,
        max_retries: int = 0,
        verify_model: bool = True,
        prices: Mapping[str, Mapping[str, float]] | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        env = os.environ if env is None else env
        self.mode = mode or ("mock" if transport is not None else "live")
        if self.mode not in ("live", "mock"):
            raise ValueError("mode: ожидается 'live' или 'mock'")

        key_source = "argument" if api_key else None
        if not api_key:
            api_key = (env.get("ANTHROPIC_API_KEY") or "").strip() or None
            key_source = "ANTHROPIC_API_KEY" if api_key else None
        if not api_key and self.mode == "mock":
            api_key, key_source = "mock-key-not-a-secret", "mock"
        if not api_key:
            hint = ""
            if (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip():
                hint = " ANTHROPIC_AUTH_TOKEN (подписка/OAuth) намеренно не используется."
            raise _make_error(
                KIND_AUTH,
                subkind="missing_key",
                retryable=False,
                detail="Не задан ANTHROPIC_API_KEY: живой вызов Claude API невозможен." + hint,
            )

        self.default_model = (model or env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL).strip()
        self.max_tokens = int(max_tokens) if max_tokens else _env_int(env, "ANTHROPIC_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        self.effort = _parse_effort(effort if effort is not None else env.get("ANTHROPIC_EFFORT"))
        self.fallbacks = _parse_fallbacks(fallbacks if fallbacks is not None else env.get("ANTHROPIC_FALLBACKS"))
        self.base_url = (base_url or env.get("ANTHROPIC_BASE_URL") or OFFICIAL_BASE_URL).rstrip("/")
        self.verify_model = verify_model
        self.prices = {k: dict(v) for k, v in (prices or {}).items()}
        self._clock = clock
        self._key_source = key_source
        self._secrets = (api_key,) if key_source != "mock" else ()
        self._on_physical_call = on_physical_call
        self.transport = transport  # None в живом режиме; RecordedTransport в mock
        self._transport_name = "recorded-fixture" if isinstance(transport, RecordedTransport) else (
            "custom-transport" if transport is not None else "https"
        )

        self._lock = threading.Lock()
        self._tls = threading.local()
        self._physical: dict[str, int] = {"messages": 0, "models": 0, "other": 0}
        self._api_versions: set[str] = set()
        self._models_seen: dict[str, int] = {}
        self._verified: dict[str, dict[str, Any]] = {}
        self._fallback_used = 0
        self._usage_total: dict[str, int] = {}
        self._cost_total: float | None = 0.0 if self.prices else None  # тариф не задан -> стоимость неизвестна
        self.journal: list[dict[str, Any]] = []
        self.last_call: dict[str, Any] | None = None

        http_kwargs: dict[str, Any] = {"event_hooks": {"request": [self._on_request]}}
        if transport is not None:
            http_kwargs["transport"] = transport
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=self.base_url,
            max_retries=max_retries,
            http_client=anthropic.DefaultHttpxClient(**http_kwargs),
        )

    # ------------------------------------------------------------------ фабрики

    @classmethod
    def from_env(cls, **overrides: Any) -> "AnthropicAdapter":
        return cls(**overrides)

    @classmethod
    def replay(
        cls,
        records: Sequence[Mapping[str, Any]],
        *,
        models: Mapping[str, Mapping[str, Any]] | None = None,
        **kwargs: Any,
    ) -> "AnthropicAdapter":
        """Адаптер в режиме mock поверх записанных ответов (ключ не нужен).

        Без ``models`` проверка модели отключается: подставлять фиктивный
        ModelInfo значило бы выдавать имитацию за проверенный факт.
        """
        kwargs.setdefault("env", {})
        if models is None:
            kwargs.setdefault("verify_model", False)
        return cls(transport=RecordedTransport(records, models=models), mode="mock", **kwargs)

    @classmethod
    def from_fixture_files(
        cls, paths: Sequence[str | os.PathLike[str]], *, models_path: str | os.PathLike[str] | None = None, **kwargs: Any
    ) -> "AnthropicAdapter":
        records = [load_fixture(p) for p in paths]
        models = load_fixture(models_path) if models_path else None
        return cls.replay(records, models=models, **kwargs)

    def __repr__(self) -> str:
        return (
            f"AnthropicAdapter(mode={self.mode!r}, model={self.default_model!r}, "
            f"endpoint={self.base_url!r}, credential={self._key_source!r})"
        )

    # ---------------------------------------------------------- учёт вызовов

    def _on_request(self, request: httpx2.Request) -> None:
        path = request.url.path
        endpoint = "messages" if path.endswith("/v1/messages") else "models" if "/v1/models" in path else "other"
        retry_count = request.headers.get("x-stainless-retry-count", "0")
        version = request.headers.get("anthropic-version")
        with self._lock:
            self._physical[endpoint] += 1
            if version:
                self._api_versions.add(version)
        self._tls.calls = getattr(self._tls, "calls", 0) + 1
        if self._on_physical_call is not None:
            event = {
                "provider": PROVIDER,
                "mode": self.mode,
                "endpoint": endpoint,
                "method": request.method,
                "retry_count": int(retry_count) if retry_count.isdigit() else None,
            }
            try:
                self._on_physical_call(event)
            except Exception:  # счётчик Max не должен превращаться в «сетевую ошибку» SDK
                log.exception("on_physical_call завершился ошибкой; учёт сохранён внутри адаптера")

    @property
    def physical_calls(self) -> int:
        with self._lock:
            return self._physical["messages"]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "physical_calls": dict(self._physical),
                "models_seen": dict(self._models_seen),
                "fallback_used": self._fallback_used,
                "usage_total": dict(self._usage_total),
                "cost_usd": self._cost_total,
            }

    def passport(self) -> dict[str, Any]:
        """Поля для Report.run: режим, поставщик, фактические модели, число вызовов."""
        with self._lock:
            return {
                "provider": PROVIDER,
                "adapter_version": ADAPTER_VERSION,
                "run_mode": "mock" if self.mode == "mock" else "rules_plus_llm",
                "transport": self._transport_name,
                "endpoint": self.base_url,
                "official_endpoint": self.mode == "live" and self.base_url == OFFICIAL_BASE_URL,
                "credential": self._key_source,
                "sdk": f"anthropic=={anthropic.__version__}",
                "api_versions": sorted(self._api_versions),
                "requested_model": self.default_model,
                "models_seen": sorted(self._models_seen),
                "verified_models": copy.deepcopy(self._verified),
                "physical_calls": dict(self._physical),
                "fallbacks": self.fallbacks,
                "fallback_used": self._fallback_used,
                "effort": self.effort,
                "max_tokens": self.max_tokens,
                "usage_total": dict(self._usage_total),
                "cost_usd": self._cost_total,
                "provider_error_source": PROVIDER_ERROR_SOURCE,
            }

    # ------------------------------------------------------- проверка модели

    def check_model(self, model: str | None = None, *, timeout_s: float = DEFAULT_MODEL_CHECK_TIMEOUT_S) -> dict[str, Any]:
        """GET /v1/models/{id}: существует ли модель и доступна ли ключу. Без токенов."""
        model = (model or self.default_model).strip()
        try:
            info = self._client.models.retrieve(model, timeout=self._timeout(timeout_s))
        except anthropic.AnthropicError as exc:
            err = self._classify_exception(exc, requested_model=model, endpoint="models")
            self._record(requested_model=model, endpoint="models", error=err, latency_ms=None)
            raise err from None
        record = {
            "id": info.id,
            "display_name": getattr(info, "display_name", None),
            "max_input_tokens": getattr(info, "max_input_tokens", None),
            "max_tokens": getattr(info, "max_tokens", None),
            "request_id": getattr(info, "_request_id", None),
        }
        with self._lock:
            self._verified[model] = record
        limit = record["max_tokens"]
        if isinstance(limit, int) and self.max_tokens > limit:
            log.warning("ANTHROPIC_MAX_TOKENS=%s больше лимита модели %s (%s)", self.max_tokens, model, limit)
        return dict(record)

    # ------------------------------------------------------------- invoke

    def invoke(
        self,
        *,
        model: str | None,
        messages: Sequence[Mapping[str, Any]],
        schema: Mapping[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        timeout = self._timeout(timeout_s)
        schema_dict = self._schema_dict(schema, model)
        validator = jsonschema.Draft202012Validator(schema_dict)
        system, convo = self._split_messages(messages, model)

        if self.verify_model and model not in self._verified:
            self.check_model(model, timeout_s=min(float(timeout_s), DEFAULT_MODEL_CHECK_TIMEOUT_S))

        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": to_wire_schema(schema_dict)}}
        if self.effort:
            output_config["effort"] = self.effort
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": convo,
            "output_config": output_config,
        }
        if system:
            params["system"] = system
        if self.fallbacks:
            create = self._client.beta.messages.create
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = self.fallbacks
        else:
            create = self._client.messages.create

        self._tls.calls = 0
        started = self._clock()
        try:
            response = create(**params, timeout=timeout)
        except anthropic.AnthropicError as exc:
            latency_ms = round((self._clock() - started) * 1000)
            err = self._classify_exception(exc, requested_model=model, endpoint="messages")
            self._record(requested_model=model, endpoint="messages", error=err, latency_ms=latency_ms)
            raise err from None
        latency_ms = round((self._clock() - started) * 1000)
        physical = getattr(self._tls, "calls", 0)

        actual_model = getattr(response, "model", None)
        request_id = getattr(response, "_request_id", None)
        fallback_used = self._fallback_used_in(response)
        usage = self._usage(response, physical, actual_model, fallback_used)

        try:
            data, enum_fixes = self._check_response(response, validator)
        except Exception as err:
            if not isinstance(err, ProviderError):
                raise
            for key, value in (
                ("requested_model", model),
                ("model", actual_model),
                ("request_id", request_id),
                ("usage", usage),
            ):
                try:
                    setattr(err, key, value)
                except AttributeError:
                    pass
            self._account(actual_model, usage, fallback_used)
            self._record(
                requested_model=model,
                endpoint="messages",
                error=err,
                latency_ms=latency_ms,
                response=response,
                usage=usage,
                fallback_used=fallback_used,
            )
            raise

        self._account(actual_model, usage, fallback_used)
        self._record(
            requested_model=model,
            endpoint="messages",
            latency_ms=latency_ms,
            response=response,
            usage=usage,
            fallback_used=fallback_used,
            enum_fixes=enum_fixes,
        )
        return {"data": data, "usage": usage, "model": actual_model, "request_id": request_id}

    # ------------------------------------------------------ подготовка запроса

    @staticmethod
    def _timeout(timeout_s: float) -> httpx2.Timeout:
        try:
            value = float(timeout_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_s должен быть числом секунд") from exc
        if value <= 0:
            raise ValueError("timeout_s должен быть больше нуля")
        return anthropic.Timeout(value, connect=min(value, 10.0))

    @staticmethod
    def _schema_dict(schema: Any, model: str) -> dict[str, Any]:
        if hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        if not isinstance(schema, Mapping):
            raise _make_error(
                KIND_BAD_REQUEST, subkind="invalid_schema", requested_model=model,
                detail="schema должна быть JSON Schema (dict) или моделью pydantic",
            )
        schema = dict(schema)
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise _make_error(
                KIND_BAD_REQUEST, subkind="invalid_schema", requested_model=model,
                detail=f"Схема этапа некорректна: {_truncate(exc.message)}",
            ) from None
        return schema

    @staticmethod
    def _split_messages(
        messages: Sequence[Mapping[str, Any]], model: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Ведущие сообщения role=system переносятся в параметр ``system``."""
        if not messages:
            raise _make_error(KIND_BAD_REQUEST, subkind="empty_messages", requested_model=model,
                              detail="messages пуст")
        system_blocks: list[dict[str, Any]] = []
        idx = 0
        items = list(messages)
        while idx < len(items) and items[idx].get("role") == "system":
            content = items[idx].get("content")
            if isinstance(content, str):
                system_blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                system_blocks.extend(dict(b) for b in content)
            idx += 1
        convo = [dict(m) for m in items[idx:]]
        if not convo:
            raise _make_error(KIND_BAD_REQUEST, subkind="no_user_message", requested_model=model,
                              detail="после system нет ни одного сообщения user")
        for msg in convo:
            if msg.get("role") not in ("user", "assistant", "system"):
                raise _make_error(KIND_BAD_REQUEST, subkind="bad_role", requested_model=model,
                                  detail=f"недопустимая роль сообщения: {msg.get('role')!r}")
        if convo[-1].get("role") == "assistant":
            raise _make_error(KIND_BAD_REQUEST, subkind="prefill", requested_model=model,
                              detail="последнее сообщение assistant (prefill) несовместимо с JSON outputs")
        if system_blocks:
            last = dict(system_blocks[-1])
            if last.get("type") == "text":
                last.setdefault("cache_control", {"type": "ephemeral"})
            system_blocks[-1] = last
        return system_blocks, convo

    # ------------------------------------------------------- проверка ответа

    @staticmethod
    def _fallback_used_in(response: Any) -> bool:
        usage = getattr(response, "usage", None)
        for item in getattr(usage, "iterations", None) or []:
            if getattr(item, "type", None) == "fallback_message":
                return True
        return any(getattr(block, "type", None) == "fallback" for block in getattr(response, "content", []) or [])

    def _check_response(self, response: Any, validator: Any) -> tuple[Any, int]:
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise _make_error(
                KIND_REFUSAL,
                subkind=category or "refusal",
                http_status=200,
                detail=f"Модель отказалась отвечать (stop_reason=refusal, category={category}).",
            )
        if stop in _INCOMPLETE_STOP:
            raise _make_error(
                KIND_INCOMPLETE,
                subkind=stop,
                http_status=200,
                detail=f"Неполный ответ: stop_reason={stop} при max_tokens={self.max_tokens}; "
                "данные этапа не приняты.",
            )
        if stop not in _OK_STOP:
            raise _make_error(
                KIND_UNKNOWN, subkind="unexpected_stop_reason", http_status=200,
                detail=f"Неизвестный stop_reason={stop!r}; ответ не принят.",
            )
        text = "".join(
            getattr(block, "text", "") for block in getattr(response, "content", []) or []
            if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            raise _make_error(KIND_SCHEMA, subkind="empty_output", http_status=200,
                              detail="В ответе нет текстового блока с JSON.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _make_error(
                KIND_SCHEMA, subkind="invalid_json", http_status=200,
                detail=f"Ответ не является JSON: {exc.msg} (позиция {exc.pos}).",
            ) from None
        enum_fixes = normalize_enum_case(data, validator)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
        if errors:
            listed = "; ".join(
                f"{'/'.join(map(str, e.absolute_path)) or '<корень>'}: {_truncate(e.message, 160)}" for e in errors[:5]
            )
            more = f" (ещё {len(errors) - 5})" if len(errors) > 5 else ""
            raise _make_error(
                KIND_SCHEMA, subkind="schema_mismatch", http_status=200,
                detail=f"JSON не соответствует схеме: {listed}{more}",
            )
        return data, enum_fixes

    # --------------------------------------------------------- usage и cost

    def _usage(self, response: Any, physical: int, model: str | None, fallback_used: bool) -> dict[str, Any]:
        u = getattr(response, "usage", None)

        def field(name: str) -> Any:
            return getattr(u, name, None) if u is not None else None

        iterations = field("iterations")
        usage: dict[str, Any] = {
            "input_tokens": field("input_tokens"),
            "output_tokens": field("output_tokens"),
            "cache_creation_input_tokens": field("cache_creation_input_tokens"),
            "cache_read_input_tokens": field("cache_read_input_tokens"),
            "cache_creation": _dump(field("cache_creation")),
            "service_tier": field("service_tier"),
            "inference_geo": field("inference_geo"),
            "speed": field("speed"),
            "iterations": [_dump(i) for i in iterations] if iterations else None,
            "physical_calls": physical,
            "cost_usd": None,
            "cost_basis": None,
        }
        cost, basis = self._cost(model, usage, fallback_used)
        usage["cost_usd"], usage["cost_basis"] = cost, basis
        return usage

    def _cost(self, model: str | None, usage: Mapping[str, Any], fallback_used: bool) -> tuple[float | None, str | None]:
        if not model or model not in self.prices:
            return None, None
        if fallback_used:
            return None, "fallback: стоимость по нескольким моделям не вычисляется"
        p = self.prices[model]
        parts = {
            "input": usage.get("input_tokens"),
            "output": usage.get("output_tokens"),
            "cache_read": usage.get("cache_read_input_tokens"),
        }
        cc = usage.get("cache_creation") or {}
        if usage.get("cache_creation_input_tokens"):
            if cc:
                parts["cache_write_5m"] = cc.get("ephemeral_5m_input_tokens")
                parts["cache_write_1h"] = cc.get("ephemeral_1h_input_tokens")
            else:
                return None, "нет разбивки cache_creation по TTL"
        total = 0.0
        for name, tokens in parts.items():
            if not tokens:
                continue
            if name not in p:
                return None, f"нет тарифа {name} для {model}"
            total += tokens * float(p[name]) / 1_000_000
        return round(total, 10), f"prices[{model}] USD/MTok"

    def _account(self, model: str | None, usage: Mapping[str, Any], fallback_used: bool) -> None:
        with self._lock:
            if model:
                self._models_seen[model] = self._models_seen.get(model, 0) + 1
            if fallback_used:
                self._fallback_used += 1
            for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    self._usage_total[key] = self._usage_total.get(key, 0) + value
            cost = usage.get("cost_usd")
            if cost is None or self._cost_total is None:
                self._cost_total = None
            else:
                self._cost_total = round(self._cost_total + cost, 10)

    # ------------------------------------------------------ классификация

    def _classify_exception(self, exc: BaseException, *, requested_model: str, endpoint: str) -> Exception:
        common: dict[str, Any] = {"requested_model": requested_model}
        if isinstance(exc, anthropic.APITimeoutError):
            return _make_error(KIND_TIMEOUT, subkind="client_timeout",
                               detail="Тайм-аут ожидания ответа API (timeout_s истёк).", **common)
        if isinstance(exc, anthropic.APIConnectionError):
            cause = type(exc.__cause__).__name__ if exc.__cause__ else None
            return _make_error(KIND_NETWORK, subkind=cause,
                               detail=f"Сетевая ошибка до получения ответа ({cause or 'connection'}).", **common)
        if isinstance(exc, anthropic.APIResponseValidationError):
            return _make_error(KIND_UNKNOWN, subkind="invalid_envelope", http_status=exc.status_code,
                               detail="Ответ API не распознан SDK (конверт сообщения).", **common)
        if isinstance(exc, anthropic.APIStatusError):
            return self._classify_status(exc, endpoint=endpoint, **common)
        if isinstance(exc, anthropic.CredentialsError):
            return _make_error(KIND_AUTH, subkind="credentials", detail="SDK не смог получить учётные данные.",
                               **common)
        return _make_error(KIND_UNKNOWN, subkind=type(exc).__name__,
                           detail=_truncate(redact(str(exc), self._secrets)), **common)

    def _classify_status(self, exc: anthropic.APIStatusError, *, endpoint: str, **common: Any) -> Exception:
        status = exc.status_code
        etype = getattr(exc, "type", None)
        code = getattr(exc, "error_code", None)
        api_msg = _truncate(redact(str(getattr(exc, "api_message", None) or ""), self._secrets)) or ""
        retry_after = parse_retry_after(exc.response.headers)
        base = dict(common, http_status=status, error_type=etype, error_code=code,
                    request_id=getattr(exc, "request_id", None))

        def detail(prefix: str) -> str:
            return f"{prefix} HTTP {status}" + (f": {api_msg}" if api_msg else "")

        if code in _QUOTA_ERROR_CODES or status == 402 or etype == "billing_error":
            return _make_error(KIND_QUOTA, retry_after, subkind=code or "billing",
                               detail=detail("Квота/кредит исчерпаны."), **base)
        if status == 401 or etype == "authentication_error":
            return _make_error(KIND_AUTH, subkind="authentication",
                               detail=detail("Отказ авторизации: проверьте ANTHROPIC_API_KEY."), **base)
        if status == 403 or etype == "permission_error" or code == "organization_on_hold":
            return _make_error(KIND_AUTH, subkind=code or "permission",
                               detail=detail("Нет доступа для этого ключа."), **base)
        if status == 404 or etype == "not_found_error":
            if endpoint == "models" or api_msg.startswith("model:"):
                return _make_error(KIND_MODEL_NOT_FOUND, subkind="model",
                                   detail=detail(f"Модель {common['requested_model']!r} не найдена или недоступна."),
                                   **base)
            return _make_error(KIND_BAD_REQUEST, subkind="not_found", detail=detail("Ресурс не найден."), **base)
        if status == 429 or etype == "rate_limit_error":
            if retry_after is None and code is None:
                return _make_error(
                    KIND_RATE_LIMIT, None, subkind="no_retry_after", ambiguous=True,
                    alternatives=(KIND_QUOTA,),
                    detail=detail("429 без Retry-After и без error_code: временный лимит или исчерпание "
                                  "квоты не различимы; классифицировано как rate_limited, ambiguous."),
                    **base,
                )
            return _make_error(KIND_RATE_LIMIT, retry_after, subkind=code or "rate_limit",
                               detail=detail(f"Временный лимит, повтор через {retry_after} с."), **base)
        if status == 529 or etype == "overloaded_error":
            return _make_error(KIND_OVERLOADED, retry_after, subkind="overloaded",
                               detail=detail("API перегружен."), **base)
        if status in (408, 504) or etype == "timeout_error":
            return _make_error(KIND_TIMEOUT, retry_after, subkind="server_timeout",
                               detail=detail("Тайм-аут на стороне API/шлюза."), **base)
        if status == 413:
            return _make_error(KIND_BAD_REQUEST, subkind="request_too_large",
                               detail=detail("Запрос слишком большой."), **base)
        if status in (400, 422) or etype == "invalid_request_error":
            lowered = api_msg.lower()
            if "prompt is too long" in lowered:
                sub = "context_overflow"
            elif "schema" in lowered and ("complex" in lowered or "compil" in lowered):
                sub = "schema_too_complex"
            elif "anthropic-beta" in lowered or "fallback" in lowered:
                sub = "beta_not_enabled"
            else:
                sub = "invalid_request"
            hint = " Попробуйте ANTHROPIC_FALLBACKS=off." if sub == "beta_not_enabled" else ""
            return _make_error(KIND_BAD_REQUEST, subkind=sub, detail=detail("Некорректный запрос.") + hint, **base)
        if status == 409:
            return _make_error(KIND_UNKNOWN, retry_after, subkind="conflict", retryable=True,
                               detail=detail("Конфликт (409); причина не раскрыта."), **base)
        if status >= 500:
            return _make_error(KIND_SERVER, retry_after, subkind=etype or f"http_{status}",
                               detail=detail("Ошибка сервера API."), **base)
        return _make_error(KIND_UNKNOWN, retry_after, subkind=f"http_{status}",
                           detail=detail("Неклассифицированный ответ."), **base)

    # ------------------------------------------------------------ журнал

    def _record(
        self,
        *,
        requested_model: str,
        endpoint: str,
        latency_ms: int | None,
        error: Exception | None = None,
        response: Any = None,
        usage: Mapping[str, Any] | None = None,
        fallback_used: bool = False,
        enum_fixes: int = 0,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "provider": PROVIDER,
            "mode": self.mode,
            "endpoint": endpoint,
            "requested_model": requested_model,
            "model": getattr(response, "model", None) if response is not None else getattr(error, "model", None),
            "request_id": getattr(response, "_request_id", None) if response is not None
            else getattr(error, "request_id", None),
            "status": "error" if error is not None else "ok",
            "kind": getattr(error, "kind", None),
            "subkind": getattr(error, "subkind", None),
            "retry_after_s": getattr(error, "retry_after_s", None),
            "ambiguous": getattr(error, "ambiguous", False) if error is not None else False,
            "http_status": getattr(error, "http_status", None) if error is not None else 200,
            "stop_reason": getattr(response, "stop_reason", None) if response is not None else None,
            "latency_ms": latency_ms,
            "physical_calls": usage.get("physical_calls") if usage else getattr(self._tls, "calls", None),
            "tokens": {
                k: usage.get(k)
                for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            } if usage else None,
            "fallback_used": fallback_used,
            "enum_case_fixes": enum_fixes,
            "detail": getattr(error, "detail", None),
        }
        text = redact(json.dumps(entry, ensure_ascii=False, default=str), self._secrets)
        safe = json.loads(text)
        with self._lock:
            self.journal.append(safe)
        if endpoint == "messages":
            self.last_call = safe
        (log.warning if error is not None else log.info)("anthropic %s", text)


__all__ = [
    "AnthropicAdapter",
    "ProviderError",
    "PROVIDER_ERROR_SOURCE",
    "RecordedTransport",
    "ERROR_KINDS",
    "ENV_VARS",
    "DEFAULT_MODEL",
    "load_fixture",
    "normalize_enum_case",
    "parse_retry_after",
    "redact",
    "to_wire_schema",
]
