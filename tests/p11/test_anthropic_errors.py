"""Классификация ошибок: статус этапа отражает факт, а не «пустой успех»."""

from __future__ import annotations

import datetime as dt

import pytest

from bcc_review.providers.anthropic import (
    ERROR_KINDS,
    AnthropicAdapter,
    ProviderError,
    parse_retry_after,
)


def _fail(adapter, messages, schema, model="claude-opus-5-5"):
    with pytest.raises(ProviderError) as info:
        adapter.invoke(model=model, messages=messages, schema=schema, timeout_s=30)
    return info.value


def test_429_with_retry_after(make_adapter, messages, schema):
    adapter = make_adapter("rate_limit_429_retry_after")
    err = _fail(adapter, messages, schema)
    assert err.kind == "rate_limit" and err.transient is True
    assert err.retry_after_s == 7.0
    assert err.retryable is True and err.ambiguous is False
    assert err.http_status == err.status == 429 and err.request_id == "req_synth_429"
    assert "HTTP 429" in err.message and err.usage == {}
    assert adapter.physical_calls == 1  # SDK сам не повторил
    assert adapter.last_call["status"] == "error"
    assert adapter.last_call["kind"] == "rate_limit"
    assert adapter.last_call["retry_after_s"] == 7.0


def test_auth_401(make_adapter, messages, schema):
    err = _fail(make_adapter("auth_401"), messages, schema)
    assert err.kind == "auth" and err.subkind == "authentication"
    assert err.retryable is False and err.transient is False and err.retry_after_s is None
    assert "ANTHROPIC_API_KEY" in err.detail


def test_http_200_max_tokens_is_incomplete(make_adapter, messages, schema):
    adapter = make_adapter("max_tokens_stop")
    err = _fail(adapter, messages, schema)
    assert err.kind == "truncated" and err.subkind == "max_tokens"
    assert err.http_status == 200
    assert err.model == "claude-opus-5-5" and err.request_id == "req_synth_max_tokens"
    assert err.usage["output_tokens"] == 16000  # токены потрачены и учтены
    assert adapter.last_call["stop_reason"] == "max_tokens"
    assert adapter.passport()["usage_total"]["output_tokens"] == 16000


def test_valid_json_wrong_schema(make_adapter, messages, schema):
    err = _fail(make_adapter("wrong_schema_200"), messages, schema)
    assert err.kind == "invalid_output" and err.subkind == "schema_mismatch"
    assert "severity" in err.detail and "hints" in err.detail
    assert err.request_id == "req_synth_wrong_schema"


def test_local_constraint_not_enforced_by_api(make_adapter, messages, schema):
    err = _fail(make_adapter("empty_quote_200"), messages, schema)
    assert err.kind == "invalid_output"
    assert "quote" in err.detail


def test_invalid_json(make_adapter, messages, schema):
    err = _fail(make_adapter("invalid_json_200"), messages, schema)
    assert err.kind == "invalid_output" and err.subkind == "invalid_json"


def test_refusal(make_adapter, messages, schema):
    err = _fail(make_adapter("refusal_200"), messages, schema)
    assert err.kind == "refusal" and err.subkind == "cyber"
    assert err.retryable is False


@pytest.mark.parametrize(
    ("fixture", "kind", "subkind", "retry_after"),
    [
        ("overloaded_529", "overloaded", "overloaded", 0.001),
        ("server_500", "server", "api_error", None),
        ("gateway_504", "timeout", "server_timeout", None),
        ("spend_cap_429", "quota", "enforced_spend_limit_reached", None),
        ("billing_402", "quota", "billing", None),
        ("schema_too_complex_400", "bad_request", "schema_too_complex", None),
        ("timeout_raise", "timeout", "client_timeout", None),
        ("connect_raise", "network", "ConnectError", None),
    ],
)
def test_error_table(make_adapter, messages, schema, fixture, kind, subkind, retry_after):
    adapter = make_adapter(fixture)
    err = _fail(adapter, messages, schema)
    assert (err.kind, err.subkind) == (kind, subkind)
    assert err.retry_after_s == retry_after
    assert err.retryable is ERROR_KINDS[kind][0]
    assert adapter.physical_calls == 1


def test_ambiguous_429_stays_honest(make_adapter, messages, schema):
    err = _fail(make_adapter("rate_limit_429_no_retry_after"), messages, schema)
    assert err.kind == "rate_limit"
    assert err.retry_after_s is None
    assert err.ambiguous is True
    assert err.alternatives == ("quota",)


def test_unknown_model_fails_before_billing(make_adapter, messages, schema):
    adapter = make_adapter("success_candidates")
    err = _fail(adapter, messages, schema, model="claude-opus-9-9")
    assert err.kind == "not_found"
    assert adapter.passport()["physical_calls"] == {"messages": 0, "models": 1, "other": 0}


def test_prefill_rejected_locally(make_adapter, schema):
    adapter = make_adapter("success_candidates")
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "{"}]
    err = _fail(adapter, msgs, schema)
    assert err.kind == "bad_request" and err.subkind == "prefill"
    assert adapter.passport()["physical_calls"]["messages"] == 0


def test_missing_key_in_live_mode_is_not_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "oauth-subscription-token-value")
    with pytest.raises(ProviderError) as info:
        AnthropicAdapter()
    err = info.value
    assert err.kind == "not_configured" and err.subkind == "missing_key"
    assert "ANTHROPIC_AUTH_TOKEN" in err.detail
    assert "oauth-subscription-token-value" not in str(err)


def test_parse_retry_after_forms():
    assert parse_retry_after({"retry-after": "12"}) == 12.0
    assert parse_retry_after({"retry-after-ms": "1500", "retry-after": "9"}) == 1.5
    now = dt.datetime(2026, 11, 26, 12, 0, 0, tzinfo=dt.timezone.utc)
    assert parse_retry_after({"retry-after": "Thu, 26 Nov 2026 12:00:30 GMT"}, now=now) == 30.0
    assert parse_retry_after({"retry-after": "garbage"}) is None
    assert parse_retry_after({}) is None
