"""Категории ошибок: квота, перегрузка, отказ, модель, тайм-аут, пустой и усечённый ответ."""

from __future__ import annotations

import sys

import pytest
from p12_support import MESSAGES, TEST_KEY, httpx_lib, load_fixture

from bcc_review.providers.gemini import ErrorKind, GeminiAdapter, ProviderError

K = ErrorKind


def call(make_adapter, fake, schema, step, **kwargs):
    fake.on("gemini-2.5-flash", step)
    with pytest.raises(ProviderError) as info:
        make_adapter(**kwargs).invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
    return info.value


@pytest.mark.parametrize("fixture, kind, retryable, retry_after, source", [
    ("err_400_api_key_invalid", K.AUTH, False, None, None),
    ("err_403_no_key", K.AUTH, False, None, None),
    ("err_400_location", K.AUTH, False, None, None),
    ("err_429_rpm", K.RATE_LIMITED, True, 39.0, "retry_info"),
    ("err_429_retry_after_header", K.RATE_LIMITED, True, 17.0, "header"),
    ("err_429_bare", K.RATE_LIMITED, True, None, None),
    ("err_429_rpd", K.QUOTA_EXHAUSTED, False, 12.0, "retry_info"),
    ("err_429_limit_zero", K.QUOTA_EXHAUSTED, False, 7.0, "retry_info"),
    ("err_503_overloaded", K.OVERLOADED, True, None, None),
    ("err_500_internal", K.OVERLOADED, True, None, None),
    ("err_504_deadline", K.TIMEOUT, True, None, None),
    ("err_404_model", K.MODEL_UNAVAILABLE, False, None, None),
    ("err_400_schema_too_complex", K.BAD_REQUEST, False, None, None),
])
def test_http_error_categories(make_adapter, fake, schema, fixture, kind, retryable, retry_after, source) -> None:
    err = call(make_adapter, fake, schema, fixture)
    assert (err.kind, err.retryable, err.retry_after, err.retry_after_source) == (kind, retryable, retry_after, source)
    assert err.status == load_fixture(fixture)["http_status"]
    assert err.physical_calls == 1 and len(fake.requests) == 1, "SDK-ретраи выключены"
    assert err.provider == "gemini" and err.model == "gemini-2.5-flash"
    assert err.message and TEST_KEY not in str(err.to_dict())


def test_invalid_key_message_is_actionable(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "err_400_api_key_invalid")
    assert "GEMINI_API_KEY" in err.message and "aistudio.google.com/apikey" in err.message
    assert "API_KEY_INVALID" in err.message
    assert err.detail["reasons"] == ["API_KEY_INVALID"]


def test_quota_details_distinguish_minute_day_and_zero(make_adapter, fake, schema) -> None:
    rpm = call(make_adapter, fake, schema, "err_429_rpm")
    assert rpm.detail["quota_ids"] == ["GenerateRequestsPerMinutePerProjectPerModel-FreeTier"]
    assert "39 с" in rpm.message
    fake.script.clear()
    zero = call(make_adapter, fake, schema, "err_429_limit_zero")
    assert zero.detail["limit_zero"] is True and zero.fallback_eligible
    assert "нулевая квота" in zero.message


def test_schema_rejection_is_flagged(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "err_400_schema_too_complex")
    assert err.detail["schema_rejected"] is True


@pytest.mark.parametrize("fixture, kind, retryable", [
    ("max_tokens_truncated", K.TRUNCATED, False),
    ("max_tokens_no_text", K.TRUNCATED, False),
    ("empty_no_candidates", K.EMPTY, True),
    ("empty_text_stop", K.EMPTY, True),
    ("prompt_blocked", K.BLOCKED, False),
    ("safety_finish", K.BLOCKED, False),
    ("schema_violation", K.INVALID_OUTPUT, True),
    ("not_json", K.INVALID_OUTPUT, True),
])
def test_incomplete_responses_never_succeed(make_adapter, fake, schema, fixture, kind, retryable) -> None:
    err = call(make_adapter, fake, schema, fixture)
    assert (err.kind, err.retryable) == (kind, retryable)
    assert err.request_id == load_fixture(fixture)["body"]["responseId"]
    assert err.detail["usage"]["input_tokens"] == 812


def test_truncation_reports_thinking_budget(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "max_tokens_no_text")
    assert err.detail["finish_reason"] == "MAX_TOKENS"
    assert err.detail["usage"]["thinking_tokens"] == 2048
    assert "рассуждения 2048" in err.message


def test_schema_violation_lists_paths(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "schema_violation")
    paths = {v["path"] for v in err.detail["violations"]}
    assert "/candidates/0/severity" in paths and "/candidates/0" in paths  # severity вне enum, нет impact


def test_full_schema_is_validated_locally_beyond_gemini_subset(make_adapter, fake, schema) -> None:
    """pattern не уходит в Gemini, но нарушение pattern всё равно ловится у нас."""
    body = load_fixture("ok_one_finding")
    text = body["body"]["candidates"][0]["content"]["parts"][0]["text"]
    body["body"]["candidates"][0]["content"]["parts"][0]["text"] = text.replace('"R-001"', '"Ф-1"')
    err = call(make_adapter, fake, schema, body)
    assert err.kind is K.INVALID_OUTPUT
    assert err.detail["violations"][0]["path"] == "/candidates/0/req_ids/0"


@pytest.mark.parametrize("exc, kind", [
    (httpx_lib.ReadTimeout("read timed out"), K.TIMEOUT),
    (httpx_lib.ConnectTimeout("connect timed out"), K.TIMEOUT),
    (httpx_lib.ConnectError("Name or service not known"), K.NETWORK),
    (RuntimeError("неожиданное"), K.UNKNOWN),
])
def test_transport_failures_become_provider_errors(make_adapter, fake, schema, exc, kind) -> None:
    err = call(make_adapter, fake, schema, exc)
    assert err.kind is kind and err.physical_calls == 1


def test_html_gateway_error_is_overload(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, lambda request: httpx_lib.Response(502, text="<html>Bad Gateway</html>"))
    assert err.kind is K.OVERLOADED and err.status == 502


def test_missing_key_fails_before_network(fake, schema) -> None:
    adapter = GeminiAdapter(api_key=None, http_client=fake.http_client())
    with pytest.raises(ProviderError) as info:
        adapter.invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
    assert info.value.kind is K.CONFIG and info.value.physical_calls == 0 and fake.requests == []
    assert "GEMINI_API_KEY" in info.value.message


def test_missing_sdk_is_config_error(monkeypatch, schema) -> None:
    monkeypatch.setitem(sys.modules, "google.genai", None)
    with pytest.raises(ProviderError) as info:
        GeminiAdapter(api_key=TEST_KEY).invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=5)
    assert info.value.kind is K.CONFIG and "pip install google-genai" in info.value.message


def test_zero_budget_makes_no_call(make_adapter, fake, schema) -> None:
    fake.on("*", "ok_empty")
    with pytest.raises(ProviderError) as info:
        make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=0)
    assert info.value.kind is K.TIMEOUT and info.value.physical_calls == 0 and fake.requests == []


def test_invalid_stage_schema_is_rejected_before_call(make_adapter, fake) -> None:
    with pytest.raises(ProviderError) as info:
        make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema={"type": 5}, timeout_s=10)
    assert info.value.kind is K.BAD_REQUEST and fake.requests == []
