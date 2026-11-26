"""Категории ошибок по словарю контракта v1: квота, перегрузка, отказ, модель, тайм-аут, пустой и усечённый ответ."""

from __future__ import annotations

import sys

import pytest
from p12_support import MESSAGES, TEST_KEY, httpx_lib, load_fixture

from bcc_review.contracts import PROVIDER_ERROR_KINDS, TRANSIENT_KINDS
from bcc_review.providers.gemini import ErrorKind, GeminiAdapter, GeminiError, ProviderError

K = ErrorKind


def call(make_adapter, fake, schema, step, **kwargs) -> GeminiError:
    fake.on("gemini-2.5-flash", step)
    with pytest.raises(ProviderError) as info:
        make_adapter(**kwargs).invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
    assert isinstance(info.value, GeminiError)
    return info.value


def test_kinds_are_exactly_from_contract_vocabulary() -> None:
    assert {k.value for k in ErrorKind} <= set(PROVIDER_ERROR_KINDS)


@pytest.mark.parametrize("fixture, kind, subkind, retry_after_s, source", [
    ("err_400_api_key_invalid", K.AUTH, "invalid_key", None, None),
    ("err_403_no_key", K.AUTH, "permission_denied", None, None),
    ("err_400_location", K.AUTH, "location_or_billing", None, None),
    ("err_429_rpm", K.RATE_LIMIT, "per_minute", 39.0, "retry_info"),
    ("err_429_retry_after_header", K.RATE_LIMIT, "unspecified", 17.0, "header"),
    ("err_429_bare", K.RATE_LIMIT, "unspecified", None, None),
    ("err_429_rpd", K.QUOTA, "per_day", 12.0, "retry_info"),
    ("err_429_limit_zero", K.QUOTA, "limit_zero", 7.0, "retry_info"),
    ("err_503_overloaded", K.OVERLOADED, "http_503", None, None),
    ("err_500_internal", K.SERVER, "http_500", None, None),
    ("err_504_deadline", K.TIMEOUT, "server_timeout", None, None),
    ("err_404_model", K.NOT_FOUND, "model", None, None),
    ("err_400_schema_too_complex", K.BAD_REQUEST, "schema_rejected", None, None),
])
def test_http_error_categories(make_adapter, fake, schema, fixture, kind, subkind, retry_after_s, source) -> None:
    err = call(make_adapter, fake, schema, fixture)
    assert (err.kind, err.subkind, err.retry_after_s, err.retry_after_source) == (kind, subkind, retry_after_s, source)
    assert err.transient is (kind in TRANSIENT_KINDS)
    assert err.status == load_fixture(fixture)["http_status"]
    assert err.physical_calls == 1 and len(fake.requests) == 1, "SDK-ретраи выключены"
    assert err.provider == "gemini" and err.model == "gemini-2.5-flash"
    assert err.message and TEST_KEY not in str(err.to_dict())


def test_daily_quota_is_not_transient_even_with_retry_delay(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "err_429_rpd")
    assert err.retry_after_s == 12.0 and not err.transient, "сервер прислал retryDelay, но квота дневная"


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
    assert zero.subkind == "limit_zero" and zero.fallback_eligible
    assert "нулевая квота" in zero.message


@pytest.mark.parametrize("fixture, kind, subkind", [
    ("max_tokens_truncated", K.TRUNCATED, "max_tokens"),
    ("max_tokens_no_text", K.TRUNCATED, "max_tokens"),
    ("empty_no_candidates", K.INVALID_OUTPUT, "empty_candidates"),
    ("empty_text_stop", K.INVALID_OUTPUT, "empty_text"),
    ("prompt_blocked", K.REFUSAL, "prompt_prohibited_content"),
    ("safety_finish", K.REFUSAL, "finish_safety"),
    ("schema_violation", K.INVALID_OUTPUT, "schema_mismatch"),
    ("not_json", K.INVALID_OUTPUT, "not_json"),
])
def test_incomplete_responses_never_succeed(make_adapter, fake, schema, fixture, kind, subkind) -> None:
    err = call(make_adapter, fake, schema, fixture)
    assert (err.kind, err.subkind) == (kind, subkind) and not err.transient
    assert err.request_id == load_fixture(fixture)["body"]["responseId"]
    assert err.usage["input_tokens"] == 812, "потраченные токены видны движку и на ошибке"


def test_truncation_reports_thinking_budget(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "max_tokens_no_text")
    assert err.detail["finish_reason"] == "MAX_TOKENS"
    assert err.usage["thinking_tokens"] == 2048
    assert "рассуждения 2048" in err.message


def test_schema_violation_lists_paths(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, "schema_violation")
    paths = {v["path"] for v in err.detail["violations"]}
    assert "/candidates/0/severity" in paths and "/candidates/0" in paths  # severity вне enum, нет impact


def test_full_schema_is_validated_locally_beyond_gemini_subset(make_adapter, fake, schema) -> None:
    """pattern не уходит в Gemini как ключевое слово, но нарушение pattern всё равно ловится у нас."""
    body = load_fixture("ok_one_finding")
    text = body["body"]["candidates"][0]["content"]["parts"][0]["text"]
    body["body"]["candidates"][0]["content"]["parts"][0]["text"] = text.replace('"R-001"', '"Ф-1"')
    err = call(make_adapter, fake, schema, body)
    assert err.kind == K.INVALID_OUTPUT
    assert err.detail["violations"][0]["path"] == "/candidates/0/req_ids/0"


@pytest.mark.parametrize("exc, kind, subkind", [
    (httpx_lib.ReadTimeout("read timed out"), K.TIMEOUT, "client_timeout"),
    (httpx_lib.ConnectTimeout("connect timed out"), K.TIMEOUT, "client_timeout"),
    (httpx_lib.ConnectError("Name or service not known"), K.NETWORK, "ConnectError"),
    (RuntimeError("неожиданное"), K.UNKNOWN, "RuntimeError"),
])
def test_transport_failures_become_provider_errors(make_adapter, fake, schema, exc, kind, subkind) -> None:
    err = call(make_adapter, fake, schema, exc)
    assert (err.kind, err.subkind) == (kind, subkind) and err.physical_calls == 1


def test_html_gateway_error_is_server(make_adapter, fake, schema) -> None:
    err = call(make_adapter, fake, schema, lambda request: httpx_lib.Response(502, text="<html>Bad Gateway</html>"))
    assert err.kind == K.SERVER and err.status == 502 and err.transient


def test_missing_key_fails_before_network(fake, schema) -> None:
    adapter = GeminiAdapter(api_key=None, http_client=fake.http_client())
    with pytest.raises(ProviderError) as info:
        adapter.invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
    assert info.value.kind == "not_configured" and info.value.subkind == "missing_key"
    assert info.value.physical_calls == 0 and fake.requests == []
    assert "GEMINI_API_KEY" in info.value.message


def test_missing_sdk_is_not_configured(monkeypatch, schema) -> None:
    monkeypatch.setitem(sys.modules, "google.genai", None)
    with pytest.raises(ProviderError) as info:
        GeminiAdapter(api_key=TEST_KEY).invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=5)
    assert info.value.kind == "not_configured" and "pip install google-genai" in info.value.message


def test_zero_budget_makes_no_call(make_adapter, fake, schema) -> None:
    fake.on("*", "ok_empty")
    with pytest.raises(ProviderError) as info:
        make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=0)
    assert info.value.kind == "timeout" and info.value.physical_calls == 0 and fake.requests == []


def test_invalid_stage_schema_is_rejected_before_call(make_adapter, fake) -> None:
    with pytest.raises(ProviderError) as info:
        make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema={"type": 5}, timeout_s=10)
    assert info.value.kind == "bad_request" and info.value.subkind == "invalid_schema" and fake.requests == []
