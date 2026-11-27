"""№02: Claude API (кэш, чистые messages, откат beta/effort) и OpenAI-совместимый сервер (без сети)."""

from __future__ import annotations

import json
import socket
import urllib.error

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.anthropic_api import AnthropicProvider, to_cached_messages
from bcc_review.v2.providers.openai_compat import OpenAICompatProvider, extract_json, normalize_base_url

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string", "enum": ["да", "нет"]}}}
DOC = "<документ>\n" + "\n".join(f"L{i:03d}| строка документа номер {i}" for i in range(1, 120)) + "\n</документ>\n"
USER = DOC + "<требования>\nR-01 …\n</требования>\n\nЗадание этапа: найди дефекты."
MESSAGES = [{"role": "system", "content": "Системный промпт", "cache": True},
            {"role": "user", "content": USER, "cache": {"ttl": "1h"}}]


# --------------------------------------------------------------------------- anthropic


def test_cached_messages_strip_service_fields_and_mark_document_prefix():
    wire = to_cached_messages(MESSAGES)
    assert all(set(m) == {"role", "content"} for m in wire)       # нет поля cache и прочих
    assert wire[0] == {"role": "system", "content": "Системный промпт"}
    blocks = wire[1]["content"]
    # две точки кэша: документ (общий для всех этапов) и таблица требований (общая для линз, судьи, вопросов)
    assert isinstance(blocks, list) and len(blocks) == 3
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and blocks[0]["text"].endswith("</документ>")
    assert blocks[1]["cache_control"] == {"type": "ephemeral"} and blocks[1]["text"].startswith("<требования>")
    assert blocks[1]["text"].endswith("</требования>")
    assert blocks[2]["text"].startswith("Задание этапа") and "cache_control" not in blocks[2]
    import re
    joined = " ".join(b["text"] for b in blocks)
    assert re.sub(r"\s+", " ", joined) == re.sub(r"\s+", " ", USER)   # текст не потерян


def test_cache_points_skip_per_lens_signals_and_segment_has_one():
    lens = DOC + "\n<требования>\nR-01 …\n</требования>\n\n<сигналы>\nS-1 …\n</сигналы>\n\nЗадание линзы."
    blocks = to_cached_messages([{"role": "system", "content": "S"}, {"role": "user", "content": lens}])[1]["content"]
    cached = [b["text"].splitlines()[-1] for b in blocks if b.get("cache_control")]
    assert cached == ["</документ>", "</требования>"]            # сигналы у каждой линзы свои — не кэшируем
    assert blocks[-1]["text"].startswith("<сигналы>")
    seg = to_cached_messages([{"role": "user", "content": DOC + "\nЗадание нарезки."}])[0]["content"]
    assert [b.get("cache_control") is not None for b in seg] == [True, False]


def test_short_user_message_not_split():
    wire = to_cached_messages([{"role": "user", "content": "<a>\nx\n</a>\nзадание"}])
    assert wire[0]["content"] == "<a>\nx\n</a>\nзадание"


class FakeAnthropic:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.created = []
        self.calls = []

    def factory(self, **options):
        self.created.append(options)
        fake = self

        class Adapter:
            def invoke(self, *, model, messages, schema, timeout_s):
                fake.calls.append({"model": model, "messages": messages, "options": options})
                item = fake.outcomes.pop(0) if len(fake.outcomes) > 1 else fake.outcomes[0]
                if isinstance(item, Exception):
                    raise item
                return item

        return Adapter()


OK = {"data": {"answer": "да"}, "usage": {"input_tokens": 5, "output_tokens": 9, "cache_read_input_tokens": 3000,
                                          "cache_creation_input_tokens": 0, "cost_usd": 0.01},
      "model": "claude-opus-5-5", "request_id": "req_1", "stop_reason": "end_turn"}


def test_anthropic_success_and_defaults():
    fake = FakeAnthropic([OK])
    p = AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=fake.factory)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"} and r["model"] == "claude-opus-5-5"
    assert r["usage"]["input_tokens"] == 3005 and r["stop_reason"] == "end_turn"
    assert fake.created[0]["max_tokens"] == 32000
    sent = fake.calls[0]["messages"]
    assert all(set(m) == {"role", "content"} for m in sent)
    assert r["meta"]["cached_prefix"] is True


def test_anthropic_beta_rejected_retries_without_fallbacks():
    beta = ProviderError("bad_request", "Некорректный запрос. HTTP 400: anthropic-beta not enabled")
    fake = FakeAnthropic([beta, OK])
    p = AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=fake.factory)
    r = p.invoke(model="claude-sonnet-5-5", messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"}
    assert fake.created[-1]["fallbacks"] == "off" and p.fallbacks_off
    assert len(fake.calls) == 2


def test_anthropic_effort_rejected_retries_without_effort():
    fake = FakeAnthropic([ProviderError("bad_request", "HTTP 400: effort is not supported for this model"), OK])
    p = AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=fake.factory)
    p.invoke(model="claude-haiku-5-5", messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert fake.created[-1]["effort"] == ""


@pytest.mark.parametrize("kind", ["auth", "rate_limit", "overloaded", "quota", "not_found", "truncated"])
def test_anthropic_errors_pass_through(kind):
    fake = FakeAnthropic([ProviderError(kind, kind)])
    p = AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=fake.factory)
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == kind and len(fake.calls) == 1


def test_anthropic_missing_key():
    with pytest.raises(ProviderError) as e:
        AnthropicProvider(env={})
    assert e.value.kind == "not_configured" and "ANTHROPIC_API_KEY" in e.value.message


def test_anthropic_v1_adapter_request_has_no_cache_field():
    """Сквозь настоящий адаптер v1 и SDK: тело запроса без поля cache, cache_control на system и документе."""
    pytest.importorskip("anthropic")
    import httpx2

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps({"answer": "нет"})}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}}, headers={"request-id": "req_x"})

    from bcc_review.providers.anthropic import AnthropicAdapter

    def factory(**options):
        return AnthropicAdapter(api_key="sk-ant-test", env={}, verify_model=False,
                                transport=httpx2.MockTransport(handler), **options)

    p = AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=factory)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "нет"}
    body = seen["body"]
    assert "cache" not in json.dumps([{k: v for k, v in m.items() if k != "content"} for m in body["messages"]])
    assert all(set(m) == {"role", "content"} for m in body["messages"])
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["max_tokens"] == 32000
    assert body["output_config"]["format"]["type"] == "json_schema"


# --------------------------------------------------------------------------- openai-compatible


class FakeHTTP:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, url, body, headers, timeout_s):
        self.requests.append({"url": url, "body": json.loads(body), "headers": dict(headers), "timeout": timeout_s})
        item = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(item, BaseException):
            raise item
        return item


def chat(content, finish="stop", model="qwen3:32b"):
    return 200, {}, json.dumps({"id": "chatcmpl-1", "model": model, "choices": [
        {"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30}}).encode()


def http_error(status, message, headers=None):
    return status, headers or {}, json.dumps({"error": {"message": message}}).encode()


def oai(replies, **kw):
    http = FakeHTTP(replies)
    env = {"OPENAI_BASE_URL": "http://localhost:11434", "OPENAI_MODEL": "qwen3:32b"}
    env.update(kw.pop("env", {}))
    return OpenAICompatProvider(env=env, transport=http, **kw), http


def test_openai_json_schema_success():
    p, http = oai([chat('{"answer": "да"}')])
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["data"] == {"answer": "да"} and r["model"] == "qwen3:32b"
    assert r["usage"] == {"input_tokens": 120, "output_tokens": 30}
    req = http.requests[0]
    assert req["url"] == "http://localhost:11434/v1/chat/completions"
    assert req["body"]["response_format"]["type"] == "json_schema"
    assert req["body"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert all(set(m) == {"role", "content"} for m in req["body"]["messages"])
    assert "Authorization" not in req["headers"]


def test_openai_api_key_header():
    p, http = oai([chat('{"answer": "да"}')], env={"OPENAI_API_KEY": "sk-local"})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert http.requests[0]["headers"]["Authorization"] == "Bearer sk-local"


def test_openai_falls_back_to_json_object_then_none():
    p, http = oai([http_error(400, "response_format json_schema is not supported"),
                   http_error(400, "response_format type json_object unsupported"),
                   chat('Вот ответ:\n```json\n{"answer": "нет"}\n```')])
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["data"] == {"answer": "нет"} and r["meta"]["response_format"] == "none"
    modes = [req["body"].get("response_format", {}).get("type") for req in http.requests]
    assert modes == ["json_schema", "json_object", None]
    assert "JSON Schema" in http.requests[1]["body"]["messages"][0]["content"]   # схема текстом
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert "response_format" not in http.requests[-1]["body"]                  # режим запомнен


def test_openai_schema_mismatch_is_invalid_output():
    p, _ = oai([chat('{"answer": "может быть"}')])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "invalid_output" and "/answer" in e.value.message


def test_openai_not_json_and_empty():
    p, _ = oai([chat("не знаю")])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "invalid_output"
    p2, _ = oai([chat("")])
    with pytest.raises(ProviderError) as e2:
        p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e2.value.kind == "invalid_output"


@pytest.mark.parametrize("reply,kind,transient", [
    (http_error(401, "invalid api key"), "auth", False),
    (http_error(404, 'model "qwen9" not found, try pulling it first'), "not_found", False),
    (http_error(429, "rate limited", {"retry-after": "7"}), "rate_limit", True),
    (http_error(429, "insufficient credits"), "quota", False),
    (http_error(503, "loading model"), "overloaded", True),
    (http_error(500, "boom"), "server", True),
    (http_error(504, "gateway timeout"), "timeout", True),
    (http_error(400, "context length exceeded: 40000 > 8192"), "bad_request", False),
    (chat('{"answer": "да"', finish="length"), "truncated", False),
])
def test_openai_error_kinds(reply, kind, transient):
    p, _ = oai([reply])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == kind and e.value.transient is transient
    if kind == "rate_limit":
        assert e.value.retry_after_s == 7.0


def test_openai_connection_refused_and_timeout():
    p, _ = oai([urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "network" and "ollama serve" in e.value.message
    p2, _ = oai([socket.timeout("timed out")])
    with pytest.raises(ProviderError) as e2:
        p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e2.value.kind == "timeout"


def test_openai_not_configured():
    with pytest.raises(ProviderError) as e:
        OpenAICompatProvider(env={})
    assert e.value.kind == "not_configured" and "OPENAI_BASE_URL" in e.value.message
    p = OpenAICompatProvider(env={"OPENAI_BASE_URL": "http://x/v1"}, transport=FakeHTTP([chat("{}")]))
    with pytest.raises(ProviderError) as e2:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e2.value.kind == "not_configured" and "OPENAI_MODEL" in e2.value.message


def test_normalize_base_url_and_extract_json():
    assert normalize_base_url("http://localhost:11434") == "http://localhost:11434/v1"
    assert normalize_base_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"
    assert normalize_base_url("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1"
    assert normalize_base_url("http://h:8000/v1/chat/completions") == "http://h:8000/v1"
    assert extract_json('<think>рассуждаю {нет}</think>\n{"a": 1}') == {"a": 1}
    assert extract_json('Ответ: {"a": {"b": 2}} конец') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json("ничего")


def test_stage_limits_anthropic_and_openai():
    fake = FakeAnthropic([OK])
    AnthropicProvider(api_key="sk-ant-test", env={}, adapter_factory=fake.factory).invoke(
        model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, max_output_tokens=8000)
    assert fake.created[-1]["max_tokens"] == 32000
    p, http = oai([chat('{"answer": "да"}')])
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30, max_output_tokens=8000)
    assert http.requests[-1]["body"]["max_tokens"] == 16000
    p2, http2 = oai([chat('{"answer": "да"}')], env={"OPENAI_MAX_TOKENS": "4096"})
    p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30, max_output_tokens=8000)
    assert http2.requests[-1]["body"]["max_tokens"] == 4096
