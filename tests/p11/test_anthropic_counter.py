"""Физические вызовы: десять логических не превращаются незаметно в десятки физических."""

from __future__ import annotations

import pytest

from bcc_review.providers.anthropic import ProviderError


def test_ten_logical_calls_are_ten_physical(make_adapter, messages, schema):
    events = []
    names = ["rate_limit_429_retry_after", "overloaded_529", "server_500", "timeout_raise", "connect_raise",
             "success_candidates", "success_candidates", "max_tokens_stop", "wrong_schema_200",
             "success_candidates"]
    adapter = make_adapter(*names, on_physical_call=events.append)
    outcomes = []
    for _ in names:
        try:
            adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=10)
            outcomes.append("ok")
        except ProviderError as err:
            outcomes.append(err.kind)

    assert outcomes == ["rate_limit", "overloaded", "server", "timeout", "network",
                        "ok", "ok", "truncated", "invalid_output", "ok"]
    assert adapter.physical_calls == 10
    messages_events = [e for e in events if e["endpoint"] == "messages"]
    assert len(messages_events) == 10
    assert all(e["retry_count"] == 0 for e in messages_events)
    assert [e["endpoint"] for e in events].count("models") == 1  # модель проверена один раз
    assert adapter.transport.remaining == 0
    assert len([j for j in adapter.journal if j["endpoint"] == "messages"]) == 10


def test_sdk_retries_if_enabled_are_still_counted(make_adapter, messages, schema):
    """Если кто-то включит повторы SDK, общий счётчик всё равно видит каждую попытку."""
    events = []
    adapter = make_adapter("overloaded_529", "overloaded_529", "overloaded_529",
                           max_retries=2, on_physical_call=events.append)
    with pytest.raises(ProviderError) as info:
        adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=10)
    assert info.value.kind == "overloaded"
    retries = [e["retry_count"] for e in events if e["endpoint"] == "messages"]
    assert retries == [0, 1, 2]
    assert adapter.physical_calls == 3
    assert adapter.last_call["physical_calls"] == 3


def test_broken_counter_hook_does_not_become_network_error(make_adapter, messages, schema):
    def hook(event):
        raise RuntimeError("budget backend down")

    adapter = make_adapter("success_candidates", on_physical_call=hook)
    result = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=10)
    assert result["request_id"] == "req_synth_success_01"
    assert adapter.physical_calls == 1
