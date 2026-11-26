"""№02: Gemini через настоящий адаптер v1 и типы google-genai; подменён только клиент SDK (без сети)."""

from __future__ import annotations

import json

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.gemini import GeminiProvider

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]


genai = pytest.importorskip("google.genai")


class FakeModels:
    def __init__(self, items):
        self.items = list(items)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, config))
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, Exception):
            raise item
        return item


def api_error(code, status, message, details=None):
    from google.genai import errors
    return errors.APIError(code, {"error": {"code": code, "status": status, "message": message,
                                            "details": details or []}})


def response(text, finish="STOP", model_version="gemini-3.8-flash-002"):
    from google.genai import types
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]),
                                    finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=50, candidates_token_count=7),
        model_version=model_version, response_id="resp-1")


def sdk_provider(plan):
    """GeminiProvider поверх настоящего адаптера v1, у которого подменён только клиент SDK."""
    from bcc_review.providers.gemini import GeminiAdapter
    fakes = {}
    sleeps = []

    def factory(model, thinking):
        adapter = GeminiAdapter(api_key="k", model=model, fallback_models=[], min_attempt_s=1.0, temperature=None,
                                max_output_tokens=32000, thinking_budget=thinking.get("thinking_budget"),
                                thinking_level=thinking.get("thinking_level"))
        fakes[model] = FakeModels(plan.get(model, [response(json.dumps({"answer": "ок"}), model_version=model)]))

        class Client:
            models = fakes[model]

        adapter._client = Client()
        return adapter

    return GeminiProvider(api_key="k", env={}, adapter_factory=factory, sleep=sleeps.append), fakes, sleeps


def test_sdk_503_then_404_then_success_on_third_model():
    plan = {"gemini-3.8-flash": [api_error(503, "UNAVAILABLE", "The model is overloaded.")],
            "gemini-3.6-flash": [api_error(404, "NOT_FOUND", "models/gemini-3.6-flash is not found")]}
    p, fakes, sleeps = sdk_provider(plan)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "ок"} and r["model"] == "gemini-3.5-flash-lite"
    assert len(fakes["gemini-3.8-flash"].calls) == 4 and len(fakes["gemini-3.6-flash"].calls) == 1
    assert sleeps == [2.0, 5.0, 10.0]
    cfg = fakes["gemini-3.8-flash"].calls[0][1]
    assert cfg.max_output_tokens == 32000 and cfg.response_json_schema["required"] == ["answer"]
    assert str(cfg.thinking_config.thinking_level).upper().endswith("MEDIUM")


def test_sdk_429_retry_info_and_quota():
    retry = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"},
             {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
              "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]
    plan = {"gemini-3.8-flash": [api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded", retry),
                                 response(json.dumps({"answer": "да"}))]}
    p, fakes, sleeps = sdk_provider(plan)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [7.5] and r["data"] == {"answer": "да"}

    daily = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
              "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]
    p2, fakes2, sleeps2 = sdk_provider({"gemini-3.8-flash": [api_error(429, "RESOURCE_EXHAUSTED", "Quota", daily)]})
    r2 = p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps2 == [] and r2["meta"]["called_model"] == "gemini-3.6-flash"


def test_sdk_invalid_key_is_auth_with_russian_advice():
    plan = {"gemini-3.8-flash": [api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                                           [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                             "reason": "API_KEY_INVALID"}])]}
    p, fakes, sleeps = sdk_provider(plan)
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "auth" and "GEMINI_API_KEY" in e.value.message and sleeps == []


def test_sdk_max_tokens_is_truncated_and_bad_json_invalid():
    p, _, _ = sdk_provider({"gemini-3.8-flash": [response('{"answer": "обр', finish="MAX_TOKENS")]})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "truncated"
    p2, _, _ = sdk_provider({"gemini-3.8-flash": [response('{"wrong": 1}')]})
    with pytest.raises(ProviderError) as e2:
        p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e2.value.kind == "invalid_output"
