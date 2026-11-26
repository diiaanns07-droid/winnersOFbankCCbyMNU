"""Провайдер ``openai``: любой OpenAI-совместимый сервер (№02) — «закрытый контур» банка.

Ollama, vLLM, LM Studio, llama.cpp server, OpenRouter, корпоративный шлюз: ``POST {base}/chat/completions``.
Без внешних зависимостей (стандартный ``urllib``), поэтому работает в изолированной сети.

Переменные окружения:

* ``OPENAI_BASE_URL`` — адрес API, например ``http://localhost:11434/v1`` (Ollama), ``http://gpu:8000/v1`` (vLLM),
  ``http://localhost:1234/v1`` (LM Studio), ``https://openrouter.ai/api/v1``; без ``/v1`` в конце — добавляется;
* ``OPENAI_MODEL`` — имя модели на сервере (``qwen3:32b``, ``meta-llama/Llama-3.3-70B-Instruct``…);
* ``OPENAI_API_KEY`` — ключ, если сервер его требует (Ollama и vLLM обычно нет);
* ``OPENAI_MAX_TOKENS`` (по умолчанию 16 000), ``OPENAI_TEMPERATURE`` (по умолчанию 0),
  ``OPENAI_RESPONSE_FORMAT`` — ``json_schema`` (по умолчанию), ``json_object`` или ``none``.

Формат ответа: сначала ``response_format: json_schema`` (структурированный вывод); если сервер его не
поддерживает (400/422 о ``response_format``) — ``json_object``, затем без ``response_format``; схема тогда
передаётся текстом в системном промпте. Ответ в любом случае разбирается как JSON и проверяется по полной
схеме локально (``jsonschema``). Выбранный режим запоминается до конца прогона.
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Sequence

from bcc_review.contracts import ProviderError

__all__ = ["OpenAICompatProvider", "extract_json", "normalize_base_url"]

PROVIDER = "openai"
DEFAULT_MAX_TOKENS = 16000
MODES = ("json_schema", "json_object", "none")
SETUP_HELP = ("Задайте OPENAI_BASE_URL (например http://localhost:11434/v1 для Ollama) и OPENAI_MODEL "
              "(например qwen3:32b); OPENAI_API_KEY — если сервер требует ключ.")

# transport(url, body: bytes, headers: dict, timeout_s) -> (status, headers: dict, body: bytes)
Transport = Callable[[str, bytes, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


def normalize_base_url(raw: str) -> str:
    base = (raw or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    if base and not re.search(r"/v\d+[a-z0-9]*$", base) and not base.endswith("/openai"):
        base += "/v1"
    return base


def extract_json(text: str) -> Any:
    """JSON из текста модели: целиком, из блока ```json``` или первый объект ``{…}``."""
    s = (text or "").strip()
    s = re.sub(r"^<think>.*?</think>\s*", "", s, flags=re.DOTALL)  # рассуждающие модели (qwen3, deepseek-r1)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, flags=re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = s.find("{")
    if start >= 0:
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(s[start:])
            return obj
        except json.JSONDecodeError:
            pass
    raise ValueError("в ответе нет JSON-объекта")


def _urllib_transport(url: str, body: bytes, headers: Mapping[str, str], timeout_s: float) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - адрес задаёт оператор
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b""


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = (headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            return max(0.0, email.utils.parsedate_to_datetime(raw).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def _schema_text(schema: Mapping[str, Any]) -> str:
    return ("Ответ — только один JSON-объект строго по этой JSON Schema, без пояснений и без markdown:\n"
            + json.dumps(schema, ensure_ascii=False))


class OpenAICompatProvider:
    """OpenAI-совместимый ``/chat/completions``. ``transport`` подменяется в тестах."""

    name = PROVIDER
    handles_retries = False

    def __init__(self, *, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 env: Mapping[str, str] | None = None, transport: Transport | None = None,
                 mode: str | None = None, max_tokens: int | None = None) -> None:
        env = os.environ if env is None else env
        self.base_url = normalize_base_url(base_url or env.get("OPENAI_BASE_URL") or "")
        if not self.base_url:
            raise ProviderError("not_configured", f"Не задан OPENAI_BASE_URL. {SETUP_HELP}")
        self.default_model = (model or env.get("OPENAI_MODEL") or "").strip()
        self._api_key = (api_key or env.get("OPENAI_API_KEY") or "").strip() or None
        mode = (mode or env.get("OPENAI_RESPONSE_FORMAT") or "json_schema").strip().lower()
        if mode not in MODES:
            raise ProviderError("not_configured", f"OPENAI_RESPONSE_FORMAT={mode!r}: допустимо {', '.join(MODES)}.")
        self.mode = mode
        try:
            self.max_tokens = int(max_tokens or env.get("OPENAI_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
            temp = (env.get("OPENAI_TEMPERATURE") or "").strip()
            self.temperature = float(temp) if temp else 0.0
        except ValueError:
            raise ProviderError("not_configured", "OPENAI_MAX_TOKENS / OPENAI_TEMPERATURE: ожидается число.") from None
        self._transport = transport or _urllib_transport
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "bcc-review"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _body(self, model: str, messages: list[dict[str, str]], schema: Mapping[str, Any], mode: str,
              max_tokens: int) -> dict[str, Any]:
        msgs = [dict(m) for m in messages]
        if mode != "json_schema":
            hint = _schema_text(schema)
            if msgs and msgs[0]["role"] == "system":
                msgs[0]["content"] = f"{msgs[0]['content']}\n\n{hint}"
            else:
                msgs.insert(0, {"role": "system", "content": hint})
        body: dict[str, Any] = {"model": model, "messages": msgs, "max_tokens": max_tokens,
                                "temperature": self.temperature, "stream": False}
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "stage_output", "schema": schema, "strict": False}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _error(self, status: int, headers: Mapping[str, str], raw: bytes, model: str) -> ProviderError:
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            payload = {}
        err = payload.get("error") if isinstance(payload, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or raw.decode("utf-8", "replace")[:300]
        msg = str(msg).strip()[:300]
        low = msg.lower()
        where = f"{self.base_url} (HTTP {status})"
        retry = _retry_after(headers)

        def e(kind: str, text: str) -> ProviderError:
            return ProviderError(kind, f"{text} Ответ сервера: {msg}" if msg else text, retry_after_s=retry,
                                 status=status, model=model)

        if status in (401, 403):
            return e("auth", f"Сервер {where} отклонил ключ. Проверьте OPENAI_API_KEY.")
        if status == 404 or "model" in low and ("not found" in low or "does not exist" in low or "not exist" in low):
            return e("not_found", f"Модель «{model}» или адрес не найдены на {where}. Проверьте OPENAI_MODEL "
                                  "(для Ollama: «ollama list», загрузка — «ollama pull <модель>») и OPENAI_BASE_URL.")
        if status == 429:
            if "quota" in low or "insufficient" in low or "credit" in low:
                return e("quota", f"Квота или баланс исчерпаны на {where}.")
            return e("rate_limit", f"Слишком много запросов к {where}.")
        if status in (408, 504):
            return e("timeout", f"Сервер {where} не уложился во время ответа.")
        if status in (502, 503, 529):
            return e("overloaded", f"Сервер {where} перегружен или модель загружается.")
        if status >= 500:
            return e("server", f"Сбой сервера {where}.")
        if "context" in low and ("length" in low or "too long" in low or "exceed" in low):
            return e("bad_request", f"Документ не помещается в контекст модели «{model}» на {where}: "
                                    "увеличьте контекст (Ollama: num_ctx) или выберите модель с большим окном.")
        return e("bad_request", f"Сервер {where} отклонил запрос.")

    @staticmethod
    def _format_rejected(err: ProviderError) -> bool:
        low = (err.message or "").lower()
        return err.kind == "bad_request" and any(s in low for s in (
            "response_format", "json_schema", "json schema", "structured", "guided", "grammar", "schema"))

    def _validate(self, data: Any, schema: Mapping[str, Any], model: str) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:  # pragma: no cover
            return
        errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda x: list(map(str, x.absolute_path)))
        if errors:
            first = errors[0]
            path = "/" + "/".join(map(str, first.absolute_path))
            raise ProviderError("invalid_output", f"Ответ модели «{model}» не прошёл проверку по схеме: {path}: "
                                                  f"{first.message[:200]} (всего нарушений: {len(errors)}).", model=model)

    # ------------------------------------------------------------------ public

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float, max_output_tokens: int | None = None, **_: Any) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        if not model:
            raise ProviderError("not_configured", f"Не задан OPENAI_MODEL. {SETUP_HELP}")
        clean = [{"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")} for m in messages]
        max_tokens = int(max_output_tokens or self.max_tokens)
        url = f"{self.base_url}/chat/completions"
        start_mode = self.mode
        for mode in MODES[MODES.index(start_mode):]:
            body = json.dumps(self._body(model, clean, schema, mode, max_tokens), ensure_ascii=False).encode("utf-8")
            started = time.monotonic()
            try:
                status, headers, raw = self._transport(url, body, self._headers(), float(timeout_s))
            except (socket.timeout, TimeoutError):
                raise ProviderError("timeout", f"{self.base_url} не ответил за {timeout_s:.0f} с (модель {model}). "
                                               "Локальной модели может требоваться больше времени.", model=model) from None
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    raise ProviderError("timeout", f"{self.base_url} не ответил за {timeout_s:.0f} с.", model=model) from None
                raise ProviderError("network", f"Нет соединения с {self.base_url}: {reason}. Запущен ли сервер модели "
                                               "(Ollama: «ollama serve»)? Верен ли OPENAI_BASE_URL?", model=model) from None
            except OSError as exc:
                raise ProviderError("network", f"Нет соединения с {self.base_url}: {exc}.", model=model) from None
            if status >= 400:
                err = self._error(status, headers, raw, model)
                if mode != "none" and self._format_rejected(err):
                    continue
                raise err
            with self._lock:
                self.mode = mode
            return self._parse(raw, schema, model, mode, time.monotonic() - started)
        raise ProviderError("bad_request", f"{self.base_url} отклонил все режимы JSON-ответа.", model=model)

    def _parse(self, raw: bytes, schema: Mapping[str, Any], model: str, mode: str, seconds: float) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
            choice = payload["choices"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("invalid_output", f"{self.base_url} вернул ответ не в формате OpenAI "
                                                  "(нет choices[0]).", model=model) from None
        message = choice.get("message") or {}
        finish = str(choice.get("finish_reason") or "stop")
        text = message.get("content")
        if isinstance(text, list):
            text = "".join(str(p.get("text") or "") for p in text if isinstance(p, Mapping))
        text = str(text or "")
        if finish == "length":
            raise ProviderError("truncated", f"Ответ модели «{model}» обрезан по лимиту токенов "
                                             f"(max_tokens={self.max_tokens}).", model=model)
        if message.get("refusal"):
            raise ProviderError("refusal", f"Модель отказалась отвечать: {str(message['refusal'])[:200]}", model=model)
        if not text.strip():
            raise ProviderError("invalid_output", f"Модель «{model}» вернула пустой ответ.", model=model)
        try:
            data = extract_json(text)
        except ValueError:
            raise ProviderError("invalid_output", f"Ответ модели «{model}» — не JSON: {text[:120]!r}", model=model) from None
        self._validate(data, schema, model)
        u = payload.get("usage") or {}
        usage = {"input_tokens": int(u.get("prompt_tokens") or 0), "output_tokens": int(u.get("completion_tokens") or 0)}
        return {"data": data, "usage": usage, "model": str(payload.get("model") or model),
                "request_id": str(payload.get("id") or ""), "stop_reason": "end_turn",
                "meta": {"provider": PROVIDER, "base_url": self.base_url, "response_format": mode,
                         "seconds": round(seconds, 2)}}
