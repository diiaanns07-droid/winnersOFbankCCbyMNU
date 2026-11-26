"""Успешный записанный ответ: данные, фактическая модель, request_id, счётчики."""

from __future__ import annotations

import os

import pytest

from conftest import load


def _keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def test_success_returns_contract_fields(make_adapter, messages, schema):
    adapter = make_adapter("success_candidates")
    result = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)

    assert set(result) == {"data", "usage", "model", "request_id"}
    assert result["data"] == load("expected_candidates")
    assert result["model"] == "claude-opus-5-5"
    assert result["request_id"] == "req_synth_success_01"

    usage = result["usage"]
    assert usage["input_tokens"] == 5210
    assert usage["output_tokens"] == 612
    assert usage["cache_read_input_tokens"] == 4096
    assert usage["cache_creation_input_tokens"] == 1024
    assert usage["cache_creation"] == {"ephemeral_5m_input_tokens": 1024, "ephemeral_1h_input_tokens": 0}
    assert usage["service_tier"] == "standard"
    assert usage["physical_calls"] == 1
    # тариф не задан -> стоимость неизвестна, а не ноль
    assert usage["cost_usd"] is None and usage["cost_basis"] is None


def test_rerun_needs_no_key(make_adapter, messages, schema):
    assert "ANTHROPIC_API_KEY" not in os.environ
    for _ in range(2):
        adapter = make_adapter("success_candidates")
        assert adapter.invoke(model=None, messages=messages, schema=schema, timeout_s=5)["model"] == "claude-opus-5-5"


def test_request_shape_and_model_probe(make_adapter, messages, schema):
    adapter = make_adapter("success_candidates")
    adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)
    sent = adapter.transport.requests

    assert [(r["method"], r["path"]) for r in sent] == [
        ("GET", "/v1/models/claude-opus-5-5"),
        ("POST", "/v1/messages"),
    ]
    body = sent[1]["json"]
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    for banned in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert banned not in body
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert body["output_config"]["effort"] == "high"
    assert "minLength" not in set(_keys(fmt["schema"]))  # как ключ не уходит, только текстом в description
    assert "{minLength: 1}" in str(fmt["schema"])
    assert fmt["schema"]["additionalProperties"] is False
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [messages[1]]
    assert body["fallbacks"] == "default"
    assert "anthropic-beta" in sent[1]["header_names"]
    assert "authorization" in sent[1]["header_names"]


def test_passport_marks_mock_and_actual_model(make_adapter, messages, schema):
    adapter = make_adapter("success_candidates")
    adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)
    passport = adapter.passport()

    assert passport["run_mode"] == "mock"
    assert passport["transport"] == "recorded-fixture"
    assert passport["official_endpoint"] is False
    assert passport["credential"] == "mock"
    assert passport["models_seen"] == ["claude-opus-5-5"]
    assert passport["verified_models"]["claude-opus-5-5"]["max_tokens"] == 128000
    assert passport["physical_calls"] == {"messages": 1, "models": 1, "other": 0}
    assert passport["api_versions"] == ["2026-10-21"]
    assert passport["sdk"].startswith("anthropic==")
    assert passport["cost_usd"] is None
    assert adapter.last_call["status"] == "ok"
    assert adapter.last_call["mode"] == "mock"
    assert adapter.last_call["model"] == "claude-opus-5-5"


def test_fallback_records_serving_model(make_adapter, messages, schema):
    adapter = make_adapter("fallback_200")
    result = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)

    assert result["model"] == "claude-opus-4-8"  # фактическая модель, не запрошенная
    assert adapter.last_call["requested_model"] == "claude-opus-5-5"
    assert adapter.last_call["fallback_used"] is True
    assert [i["type"] for i in result["usage"]["iterations"]] == ["message", "fallback_message"]
    assert adapter.passport()["models_seen"] == ["claude-opus-4-8"]
    assert adapter.passport()["fallback_used"] == 1


def test_enum_case_normalized_and_logged(make_adapter, messages, schema):
    adapter = make_adapter("enum_case_200")
    data = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)["data"]
    assert data["candidates"][0]["severity"] == "critical"
    assert data["candidates"][0]["scope"] == "set"
    assert adapter.last_call["enum_case_fixes"] == 2


def test_cost_only_with_explicit_prices(make_adapter, messages, schema):
    prices = {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write_5m": 5.0}}
    adapter = make_adapter("success_candidates", prices=prices)
    usage = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)["usage"]
    expected = (5210 * 4.0 + 612 * 20.0 + 4096 * 0.2 + 1024 * 5.0) / 1_000_000
    assert usage["cost_usd"] == pytest.approx(expected)
    assert adapter.passport()["cost_usd"] == pytest.approx(expected)

    partial = make_adapter("success_candidates", prices={"claude-opus-5-5": {"input": 4.0, "output": 20.0}})
    usage = partial.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)["usage"]
    assert usage["cost_usd"] is None
    assert "cache_read" in usage["cost_basis"]


def test_env_configuration(make_adapter, messages, schema, monkeypatch):
    env = {"ANTHROPIC_MODEL": "claude-opus-5-5", "ANTHROPIC_EFFORT": "", "ANTHROPIC_FALLBACKS": "off",
           "ANTHROPIC_MAX_TOKENS": "4000"}
    adapter = make_adapter("success_candidates", env=env)
    adapter.invoke(model=None, messages=messages, schema=schema, timeout_s=30)
    sent = adapter.transport.requests[-1]
    assert sent["json"]["model"] == "claude-opus-5-5"
    assert sent["json"]["max_tokens"] == 4000
    assert "effort" not in sent["json"]["output_config"]
    assert "fallbacks" not in sent["json"]
    assert "anthropic-beta" not in sent["header_names"]
    assert adapter.passport()["fallbacks"] is None


def test_from_fixture_files_entry_point(messages, schema):
    from bcc_review.providers.anthropic import AnthropicAdapter
    from conftest import FIXTURES

    adapter = AnthropicAdapter.from_fixture_files(
        [FIXTURES / "success_candidates.json"], models_path=FIXTURES / "model_info.json"
    )
    result = adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)
    assert result["request_id"] == "req_synth_success_01"
    assert adapter.passport()["run_mode"] == "mock"
    assert "_synthetic" not in adapter.passport()["verified_models"]


def test_replay_without_models_skips_model_probe(messages, schema):
    from bcc_review.providers.anthropic import AnthropicAdapter

    adapter = AnthropicAdapter.replay([load("success_candidates")])
    adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=30)
    assert [r["path"] for r in adapter.transport.requests] == ["/v1/messages"]
    assert adapter.passport()["verified_models"] == {}
