"""Резервная Flash-модель: только из явного списка, каждая модель один раз, в пределах бюджета."""

from __future__ import annotations

import pytest
from p12_support import MESSAGES

from bcc_review.providers.gemini import ErrorKind, GeminiAdapter, ProviderError, settings_from_env

PRIMARY, LITE, LATEST = "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"


def invoke(adapter, schema, timeout_s=60.0):
    return adapter.invoke(model=PRIMARY, messages=MESSAGES, schema=schema, timeout_s=timeout_s)


def test_no_fallback_unless_configured(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_404_model").on(LITE, "ok_one_finding_lite")
    with pytest.raises(ProviderError) as info:
        invoke(make_adapter(), schema)
    assert info.value.kind == ErrorKind.NOT_FOUND
    assert fake.calls_for(LITE) == 0 and info.value.physical_calls == 1
    assert info.value.detail["model_chain"] == [PRIMARY]


@pytest.mark.parametrize("primary_failure", ["err_404_model", "err_429_rpd", "err_429_limit_zero",
                                             "err_503_overloaded", "err_429_rpm"])
def test_fallback_model_is_used_and_reported(make_adapter, fake, schema, primary_failure) -> None:
    fake.on(PRIMARY, primary_failure).on(LITE, "ok_one_finding_lite")
    result = invoke(make_adapter(fallback_models=[LITE]), schema)

    assert result["model"] == LITE, "фактическая модель — из modelVersion ответа"
    meta = result["meta"]
    assert meta["fallback_used"] is True
    assert (meta["requested_model"], meta["called_model"], meta["model_version"]) == (PRIMARY, LITE, LITE)
    assert [a["model"] for a in meta["attempts"]] == [PRIMARY]
    assert meta["attempts"][0]["kind"] in {k.value for k in ErrorKind}
    assert result["usage"]["physical_calls"] == 2
    assert [r["model"] for r in fake.requests] == [PRIMARY, LITE]


def test_primary_success_does_not_touch_fallback(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "ok_one_finding").on(LITE, "ok_one_finding_lite")
    result = invoke(make_adapter(fallback_models=[LITE]), schema)
    assert result["model"] == PRIMARY and result["meta"]["fallback_used"] is False
    assert fake.calls_for(LITE) == 0


def test_every_model_tried_once_then_exact_error(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_503_overloaded").on(LITE, "err_503_overloaded").on(LATEST, "err_429_rpm")
    with pytest.raises(ProviderError) as info:
        invoke(make_adapter(fallback_models=[LITE, PRIMARY, LATEST, LITE]), schema)
    err = info.value
    assert [r["model"] for r in fake.requests] == [PRIMARY, LITE, LATEST]
    assert err.kind == ErrorKind.RATE_LIMIT and err.retry_after_s == 39.0 and err.model == LATEST
    assert err.physical_calls == 3 and [a["model"] for a in err.attempts] == [PRIMARY, LITE, LATEST]


@pytest.mark.parametrize("failure, kind", [
    ("err_400_api_key_invalid", ErrorKind.AUTH),
    ("max_tokens_truncated", ErrorKind.TRUNCATED),
    ("schema_violation", ErrorKind.INVALID_OUTPUT),
    ("err_400_schema_too_complex", ErrorKind.BAD_REQUEST),
    ("prompt_blocked", ErrorKind.REFUSAL),
])
def test_no_fallback_for_non_model_specific_failures(make_adapter, fake, schema, failure, kind) -> None:
    fake.on(PRIMARY, failure).on(LITE, "ok_one_finding_lite")
    with pytest.raises(ProviderError) as info:
        invoke(make_adapter(fallback_models=[LITE]), schema)
    assert info.value.kind == kind and fake.calls_for(LITE) == 0


def test_fallback_respects_remaining_budget(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, ("err_503_overloaded", 57.0)).on(LITE, "ok_one_finding_lite")
    with pytest.raises(ProviderError) as info:
        invoke(make_adapter(fallback_models=[LITE], min_attempt_s=5), schema, timeout_s=60)
    err = info.value
    assert err.kind == ErrorKind.OVERLOADED and fake.calls_for(LITE) == 0 and err.physical_calls == 1
    assert err.attempts[-1] == {"model": LITE, "skipped": "budget", "remaining_s": 3.0}


def test_fallback_gets_only_the_remaining_budget(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, ("err_404_model", 20.0)).on(LITE, "ok_one_finding_lite")
    invoke(make_adapter(fallback_models=[LITE]), schema, timeout_s=60)
    assert fake.requests[0]["timeout"]["read"] == 60.0
    assert fake.requests[1]["timeout"]["read"] == 40.0


def test_fallback_kinds_are_configurable(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_503_overloaded").on(LITE, "ok_one_finding_lite")
    with pytest.raises(ProviderError):
        invoke(make_adapter(fallback_models=[LITE], fallback_on=[ErrorKind.NOT_FOUND]), schema)
    assert fake.calls_for(LITE) == 0


def test_env_settings_explicit_list_only() -> None:
    assert settings_from_env({})["fallback_models"] == []
    assert settings_from_env({})["model"] == "gemini-2.5-flash"
    cfg = settings_from_env({"GEMINI_MODEL": "models/gemini-flash-latest",
                             "GEMINI_FALLBACK_MODELS": " models/gemini-2.5-flash-lite, ,gemini-2.5-flash-lite,x ",
                             "GEMINI_MIN_ATTEMPT_S": "8", "GEMINI_API_KEY": "  "})
    assert cfg["model"] == "gemini-flash-latest"
    assert cfg["fallback_models"] == ["gemini-2.5-flash-lite", "x"]
    assert cfg["min_attempt_s"] == 8.0 and cfg["api_key"] is None
    adapter = GeminiAdapter.from_env({"GEMINI_API_KEY": "k", "GEMINI_FALLBACK_MODELS": LITE})
    assert adapter.model_chain(PRIMARY) == [PRIMARY, LITE]


def test_bad_env_number_is_config_error() -> None:
    with pytest.raises(ProviderError) as info:
        settings_from_env({"GEMINI_MIN_ATTEMPT_S": "пять"})
    assert info.value.kind == ErrorKind.NOT_CONFIGURED


def test_model_disabled_for_rest_of_run_after_quota_or_404(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_429_rpd").on(LITE, "ok_one_finding_lite")
    adapter = make_adapter(fallback_models=[LITE])
    invoke(adapter, schema)
    second = invoke(adapter, schema)
    assert fake.calls_for(PRIMARY) == 1 and fake.calls_for(LITE) == 2
    assert second["meta"]["attempts"] == [{"model": PRIMARY, "skipped": "quota", "earlier_in_run": True}]
    assert second["usage"]["physical_calls"] == 1 and second["meta"]["fallback_used"] is True
    adapter.reset_model_state()
    invoke(adapter, schema)
    assert fake.calls_for(PRIMARY) == 2


def test_remembered_failure_without_fallback_costs_no_call(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_404_model")
    adapter = make_adapter()
    with pytest.raises(ProviderError):
        invoke(adapter, schema)
    with pytest.raises(ProviderError) as info:
        invoke(adapter, schema)
    assert info.value.kind == ErrorKind.NOT_FOUND and info.value.physical_calls == 0
    assert info.value.detail["remembered"] is True and len(fake.requests) == 1


def test_transient_failures_are_not_remembered(make_adapter, fake, schema) -> None:
    fake.on(PRIMARY, "err_503_overloaded", "ok_one_finding")
    adapter = make_adapter()
    with pytest.raises(ProviderError):
        invoke(adapter, schema)
    assert invoke(adapter, schema)["model"] == PRIMARY
