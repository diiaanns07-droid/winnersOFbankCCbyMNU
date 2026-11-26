"""№02: Gemini — повторы 2/5/10 с, откат по цепочке моделей, 404, 429, квота, сеть (без сети)."""

from __future__ import annotations

import json

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.gemini import (DEFAULT_FALLBACKS, DEFAULT_MODEL, GeminiProvider, settings,
                                            thinking_for)

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "U", "cache": {"x": 1}}]


def ok(model, data=None):
    return {"data": data or {"answer": "да"}, "usage": {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5},
            "model": f"{model}-001", "request_id": "rid", "stop_reason": "STOP", "meta": {"called_model": model}}


def err(kind, status=None, retry_after=None, message=""):
    return ProviderError(kind, message or kind, status=status, retry_after_s=retry_after)


class Script:
    """Фейковые адаптеры v1: по каждой модели — очередь ответов (dict) или ошибок (ProviderError)."""

    def __init__(self, plan):
        self.plan = {m: list(v) for m, v in plan.items()}
        self.calls = []
        self.thinking = {}

    def factory(self, model, thinking, schema_mode="native"):
        script = self
        self.modes = getattr(self, "modes", [])
        self.modes.append((model, schema_mode))

        class Adapter:
            def invoke(self, *, model, messages, schema, timeout_s, max_output_tokens=None):
                script.calls.append(model)
                script.thinking.setdefault(model, []).append(dict(thinking))
                script.last_messages = messages
                script.last_max_tokens = max_output_tokens
                queue = script.plan.get(model) or [ok(model)]
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(item, Exception):
                    raise item
                return item

        return Adapter()


def make(plan, **kw):
    script = Script(plan)
    sleeps = []
    p = GeminiProvider(api_key="k", env={}, adapter_factory=script.factory, sleep=sleeps.append, **kw)
    return p, script, sleeps


def test_defaults():
    cfg = settings({})
    assert cfg["model"] == DEFAULT_MODEL == "gemini-3.8-flash"
    assert cfg["fallback_models"] == list(DEFAULT_FALLBACKS) == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert cfg["max_output_tokens"] == 32000
    assert settings({"GEMINI_FALLBACK_MODELS": "off"})["fallback_models"] == []
    assert settings({"GEMINI_FALLBACK_MODELS": "a, models/b,a"})["fallback_models"] == ["a", "b"]
    assert settings({"GOOGLE_API_KEY": "g"})["api_key"] == "g"


def test_success_first_model_normalized():
    p, s, sleeps = make({})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"}
    assert r["model"] == "gemini-3.8-flash-001"           # фактическая версия модели — в паспорт
    assert r["stop_reason"] == "end_turn"
    assert r["usage"] == {"input_tokens": 100, "output_tokens": 25, "thinking_tokens": 5, "cache_read_input_tokens": 0}
    assert r["meta"]["fallback_used"] is False and r["meta"]["requested_model"] == "gemini-3.8-flash"
    assert s.calls == ["gemini-3.8-flash"] and sleeps == []
    assert s.last_messages == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    assert s.last_max_tokens == 32000


def test_503_three_retries_2_5_10_then_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("overloaded", 503)] * 4})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 4 + ["gemini-3.6-flash"]
    assert sleeps == [2.0, 5.0, 10.0]
    assert r["meta"]["fallback_used"] is True and r["meta"]["called_model"] == "gemini-3.6-flash"
    assert len(r["meta"]["attempts"]) == 4


def test_503_recovers_on_retry():
    p, s, sleeps = make({"gemini-3.8-flash": [err("overloaded", 503), ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 2 and sleeps == [2.0]
    assert r["meta"]["fallback_used"] is False


@pytest.mark.parametrize("kind,status", [("server", 500), ("timeout", 504)])
def test_other_transient_kinds_retry(kind, status):
    p, s, sleeps = make({"gemini-3.8-flash": [err(kind, status)] * 4})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [2.0, 5.0, 10.0] and s.calls[-1] == "gemini-3.6-flash"


def test_404_goes_to_next_model_immediately_and_is_remembered():
    p, s, sleeps = make({"gemini-3.8-flash": [err("not_found", 404)]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash", "gemini-3.6-flash"] and sleeps == []
    assert r["model"] == "gemini-3.6-flash-001"
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls[-1] == "gemini-3.6-flash" and s.calls.count("gemini-3.8-flash") == 1  # 404 больше не вызывается


def test_quota_goes_to_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("quota", 429)], "gemini-3.6-flash": [err("quota", 429)]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"] and sleeps == []
    assert r["meta"]["called_model"] == "gemini-3.5-flash-lite"


def test_429_waits_retry_after_then_succeeds():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=12.0), ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [12.5] and s.calls == ["gemini-3.8-flash"] * 2
    assert r["meta"]["fallback_used"] is False


def test_429_long_retry_after_switches_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=3600.0)]})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [] and s.calls == ["gemini-3.8-flash", "gemini-3.6-flash"]


def test_429_twice_then_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=1.0)] * 3})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [1.5, 1.5] and s.calls == ["gemini-3.8-flash"] * 3 + ["gemini-3.6-flash"]


def test_network_retries_then_raises_without_switching():
    p, s, sleeps = make({"gemini-3.8-flash": [err("network")] * 5})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "network" and sleeps == [2.0, 5.0] and s.calls == ["gemini-3.8-flash"] * 3


@pytest.mark.parametrize("kind", ["auth", "not_configured", "refusal", "truncated", "invalid_output", "bad_request"])
def test_non_retryable_raise_immediately(kind):
    p, s, sleeps = make({"gemini-3.8-flash": [err(kind, 400)]})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == kind and s.calls == ["gemini-3.8-flash"] and sleeps == []


def test_thinking_rejected_retries_without_thinking():
    p, s, sleeps = make({"gemini-3.8-flash": [err("bad_request", 400, message="Thinking level is not supported"),
                                              ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.thinking["gemini-3.8-flash"] == [{"thinking_level": "medium"}, {}]
    assert r["meta"]["thinking"] == {}


def test_all_models_exhausted_message_lists_chain():
    plan = {m: [err("overloaded", 503)] * 10 for m in ["gemini-3.8-flash", *DEFAULT_FALLBACKS]}
    p, s, sleeps = make(plan)
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "overloaded"
    assert "Все модели Gemini" in e.value.message and "gemini-3.5-flash-lite" in e.value.message
    assert len(s.calls) == 12 and sleeps == [2.0, 5.0, 10.0] * 3
    assert len(e.value.attempts) == 12


def test_explicit_model_goes_first():
    p, s, _ = make({})
    p.invoke(model="gemini-3.6-flash", messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.6-flash"]
    assert p.model_chain("gemini-3.6-flash") == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]


def test_deadline_stops_retries():
    now = [0.0]
    script = Script({"gemini-3.8-flash": [err("overloaded", 503)] * 10})

    def sleep(s):
        now[0] += s

    p = GeminiProvider(api_key="k", env={"GEMINI_TOTAL_TIMEOUT_S": "10"}, adapter_factory=script.factory,
                       sleep=sleep, clock=lambda: now[0])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "overloaded"
    assert len(script.calls) <= 3


def test_missing_key_is_not_configured():
    p = GeminiProvider(env={})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "not_configured" and "aistudio.google.com" in e.value.message


def test_thinking_for():
    assert thinking_for("gemini-3.8-flash", None, None) == {"thinking_level": "medium"}
    assert thinking_for("gemini-2.5-flash", None, None) == {"thinking_budget": 4096}
    assert thinking_for("gemini-3.8-flash", "off", None) == {}
    assert thinking_for("gemini-3.8-flash", None, "2048") == {"thinking_budget": 2048}
    assert thinking_for("gemma-3", None, None) == {}


def test_schema_rejected_retries_same_model_with_schema_as_text():
    p, s, sleeps = make({"gemini-3.8-flash": [err("bad_request", 400, message="Gemini отклонил запрос (400): "
                                                  "The specified schema produces a constraint that has too many states"),
                                              ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 2 and sleeps == []
    assert ("gemini-3.8-flash", "text") in s.modes
    assert r["meta"]["schema_mode"] == "text"
    assert '"required": ["answer"]' in s.last_messages[0]["content"]      # схема текстом в system
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.modes.count(("gemini-3.8-flash", "text")) == 1               # режим запомнен, адаптер переиспользуется
