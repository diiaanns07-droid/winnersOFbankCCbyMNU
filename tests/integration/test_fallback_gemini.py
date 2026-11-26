"""Резервный адаптер Gemini на поддельном транспорте: формат запроса, разбор ответа, карта ошибок,
переход responseJsonSchema → responseSchema, ключ не утекает. Сети нет."""

from __future__ import annotations

import json
import socket
import urllib.error

import pytest

from bcc_review import contracts
from bcc_review.contracts import ProviderError
from bcc_review.runtime.fallback.gemini import GeminiAdapter, sanitize_schema

KEY = "AIzaTEST-secret-key-0123456789"
BASE = "https://generativelanguage.googleapis.com/v1beta"
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "note": {"type": ["string", "null"]}},
    "required": ["ok", "note"],
    "additionalProperties": False,
}
MESSAGES = [{"role": "system", "content": "Ты ревьюер ТЗ."}, {"role": "user", "content": "Проверь требование Ф-3."}]


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body.decode("utf-8")),
                           "timeout": timeout})
        resp = self.responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp


def ok_response(text='{"ok": true, "note": null}', finish="STOP", **extra):
    payload = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "thoughtsTokenCount": 50,
                          "totalTokenCount": 200},
        "modelVersion": "gemini-2.5-pro-002",
        "responseId": "resp-123",
    }
    payload.update(extra)
    return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode()


def error_response(status, message, api_status="", details=None, headers=None):
    body = {"error": {"code": status, "message": message, "status": api_status, "details": details or []}}
    return status, headers or {}, json.dumps(body).encode()


def invoke(adapter):
    return adapter.invoke(model="gemini-2.5-pro", messages=MESSAGES, schema=SCHEMA, timeout_s=42)


def raised(adapter) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        invoke(adapter)
    return info.value


# --------------------------------------------------------------------------- успех и формат запроса
def test_success_request_shape_usage_and_model():
    t = FakeTransport(ok_response())
    result = invoke(GeminiAdapter(KEY, transport=t))
    assert result == {
        "data": {"ok": True, "note": None},
        "usage": {"input_tokens": 120, "output_tokens": 80},
        "model": "gemini-2.5-pro-002",
        "request_id": "resp-123",
        "stop_reason": "stop",
    }
    (call,) = t.calls
    assert call["url"] == f"{BASE}/models/gemini-2.5-pro:generateContent"
    assert call["headers"]["x-goog-api-key"] == KEY
    assert call["timeout"] == 42
    body = call["body"]
    assert body["systemInstruction"] == {"parts": [{"text": "Ты ревьюер ТЗ."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Проверь требование Ф-3."}]}]
    assert body["generationConfig"] == {"temperature": 0, "responseMimeType": "application/json",
                                        "responseJsonSchema": SCHEMA, "maxOutputTokens": 65536}


def test_model_falls_back_to_requested_and_models_prefix_is_stripped():
    status, headers, raw = ok_response()
    payload = json.loads(raw)
    del payload["modelVersion"]
    t = FakeTransport((status, headers, json.dumps(payload).encode()))
    result = GeminiAdapter(KEY, transport=t).invoke(model="models/gemini-2.5-flash", messages=MESSAGES,
                                                    schema=SCHEMA, timeout_s=5)
    assert result["model"] == "gemini-2.5-flash"
    assert t.calls[0]["url"].endswith("/models/gemini-2.5-flash:generateContent")


def test_key_from_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", KEY)
    t = FakeTransport(ok_response())
    invoke(GeminiAdapter(transport=t))
    assert t.calls[0]["headers"]["x-goog-api-key"] == KEY
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-env-key")
    t = FakeTransport(ok_response())
    invoke(GeminiAdapter(transport=t))
    assert t.calls[0]["headers"]["x-goog-api-key"] == "gemini-env-key"


def test_missing_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    t = FakeTransport()
    err = raised(GeminiAdapter(transport=t))
    assert err.kind == "not_configured" and not err.transient
    assert t.calls == []


# --------------------------------------------------------------------------- ошибки HTTP
def test_429_retry_after_header():
    t = FakeTransport(error_response(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED",
                                     headers={"Retry-After": "7"}))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert (err.kind, err.retry_after_s, err.status) == ("rate_limit", 7.0, 429)
    assert err.transient
    assert len(t.calls) == 1  # адаптер сам не повторяет


def test_429_retry_info_in_body():
    details = [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_paid_tier_input_token_count",
                         "quotaId": "GenerateContentPaidTierInputTokensPerModelPerMinute"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"},
    ]
    t = FakeTransport(error_response(429, "You exceeded your current quota.", "RESOURCE_EXHAUSTED", details))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert (err.kind, err.retry_after_s) == ("rate_limit", 17.0)


def test_429_daily_quota_is_quota():
    details = [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                         "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3600s"},
    ]
    t = FakeTransport(error_response(429, "You exceeded your current quota.", "RESOURCE_EXHAUSTED", details))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert (err.kind, err.retry_after_s) == ("quota", 3600.0)
    assert not err.transient


@pytest.mark.parametrize(("status", "kind"), [
    (503, "overloaded"), (500, "server"), (502, "server"), (504, "server"),
    (401, "auth"), (403, "auth"), (404, "not_found"), (400, "bad_request"), (413, "bad_request"),
])
def test_status_mapping(status, kind):
    t = FakeTransport(error_response(status, "something happened", "X"))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert (err.kind, err.status) == (kind, status)
    assert len(t.calls) == 1


def test_invalid_api_key_400_is_auth():
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]
    t = FakeTransport(error_response(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT",
                                     details))
    assert raised(GeminiAdapter(KEY, transport=t)).kind == "auth"


@pytest.mark.parametrize(("exc", "kind"), [
    (socket.timeout("timed out"), "timeout"),
    (TimeoutError("timed out"), "timeout"),
    (urllib.error.URLError(socket.timeout("timed out")), "timeout"),
    (urllib.error.URLError("[Errno 11001] getaddrinfo failed"), "network"),
    (ConnectionResetError("reset by peer"), "network"),
])
def test_transport_exceptions(exc, kind):
    err = raised(GeminiAdapter(KEY, transport=FakeTransport(exc)))
    assert err.kind == kind and err.transient


# --------------------------------------------------------------------------- ответ модели
def test_max_tokens_is_truncated():
    t = FakeTransport(ok_response(text='{"ok": tr', finish="MAX_TOKENS"))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert err.kind == "truncated"
    assert err.usage == {"input_tokens": 120, "output_tokens": 80}
    assert err.model == "gemini-2.5-pro-002"


@pytest.mark.parametrize("reason", ["SAFETY", "RECITATION", "PROHIBITED_CONTENT"])
def test_blocked_finish_is_refusal(reason):
    assert raised(GeminiAdapter(KEY, transport=FakeTransport(ok_response(finish=reason)))).kind == "refusal"


def test_prompt_block_and_no_candidates_are_refusal():
    blocked = (200, {}, json.dumps({"promptFeedback": {"blockReason": "SAFETY"},
                                    "usageMetadata": {"promptTokenCount": 9}}).encode())
    assert raised(GeminiAdapter(KEY, transport=FakeTransport(blocked))).kind == "refusal"
    empty = (200, {}, json.dumps({"candidates": [], "usageMetadata": {"promptTokenCount": 9}}).encode())
    assert raised(GeminiAdapter(KEY, transport=FakeTransport(empty))).kind == "refusal"


def test_invalid_json_is_invalid_output():
    t = FakeTransport(ok_response(text="Конечно! Вот ответ: ok=true"))
    err = raised(GeminiAdapter(KEY, transport=t))
    assert err.kind == "invalid_output" and not err.transient


def test_thought_parts_are_ignored():
    status, headers, raw = ok_response()
    payload = json.loads(raw)
    payload["candidates"][0]["content"]["parts"].insert(0, {"text": "размышления модели", "thought": True})
    result = invoke(GeminiAdapter(KEY, transport=FakeTransport((status, headers, json.dumps(payload).encode()))))
    assert result["data"] == {"ok": True, "note": None}


# --------------------------------------------------------------------------- ключ не утекает
def test_api_key_never_in_url_or_errors():
    leaking = [
        error_response(400, f"Bad value near key={KEY}", "INVALID_ARGUMENT"),
        error_response(429, "Resource has been exhausted", "RESOURCE_EXHAUSTED", headers={"Retry-After": "1"}),
        urllib.error.URLError(f"proxy refused https://x/?key={KEY}"),
        OSError(f"socket error with {KEY}"),
        ok_response(text="not json"),
    ]
    for resp in leaking:
        t = FakeTransport(resp)
        adapter = GeminiAdapter(KEY, transport=t)
        err = raised(adapter)
        for text in (str(err), err.message, repr(err), repr(adapter), str(err.__dict__), str(err.__cause__)):
            assert KEY not in text
        assert err.__suppress_context__ or err.__context__ is None or KEY not in str(err.__context__)
        assert KEY not in t.calls[0]["url"] and "key=" not in t.calls[0]["url"]


# --------------------------------------------------------------------------- responseJsonSchema → responseSchema
def test_schema_field_fallback_retries_once_with_sanitized_schema():
    rejected = error_response(
        400, 'Invalid JSON payload received. Unknown name "responseJsonSchema" at \'generation_config\': '
             "Cannot find field.", "INVALID_ARGUMENT")
    t = FakeTransport(rejected, ok_response())
    result = invoke(GeminiAdapter(KEY, transport=t))
    assert result["data"] == {"ok": True, "note": None}
    assert len(t.calls) == 2
    first, second = (c["body"]["generationConfig"] for c in t.calls)
    assert "responseJsonSchema" in first and "responseSchema" not in first
    assert "responseSchema" in second and "responseJsonSchema" not in second
    assert second["responseSchema"]["properties"]["note"] == {"type": "string", "nullable": True}
    assert "additionalProperties" not in json.dumps(second["responseSchema"])


def test_schema_field_fallback_happens_only_once():
    rejected = error_response(400, 'Unknown name "responseJsonSchema" at \'generation_config\'', "INVALID_ARGUMENT")
    t = FakeTransport(rejected, error_response(400, 'Unknown name "responseSchema" at \'generation_config\'',
                                               "INVALID_ARGUMENT"))
    assert raised(GeminiAdapter(KEY, transport=t)).kind == "bad_request"
    assert len(t.calls) == 2


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_sanitized_schema_is_openapi_subset():
    source = contracts.subschema("Candidate")
    source["$defs"] = dict(source["$defs"])
    source["$defs"]["Hint"] = {**source["$defs"]["Hint"], "properties": {
        **source["$defs"]["Hint"]["properties"], "mark": {"const": "x"}}}
    clean = sanitize_schema(source)
    text = json.dumps(clean, ensure_ascii=False)
    for banned in ("additionalProperties", "$ref", "$defs", "$schema", "const"):
        assert banned not in text, banned
    for node in _walk(clean):
        assert not isinstance(node.get("type"), list)
    hint = clean["properties"]["hints"]["items"]
    assert hint["properties"]["block_id"] == {"type": "string", "nullable": True}
    assert hint["properties"]["mark"] == {"type": "string", "enum": ["x"]}
    assert clean["properties"]["severity"]["enum"] == list(contracts.SEVERITIES)
    assert clean["properties"]["witness"]["properties"]["hint_a"]["required"] == ["quote"]
    assert clean["required"][:3] == ["scope", "kind", "criterion"]
