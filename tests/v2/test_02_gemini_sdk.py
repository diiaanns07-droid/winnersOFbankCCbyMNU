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
        self.contents = []

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, config))
        self.contents.append(contents)
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
    fakes = {}
    sleeps = []

    holder = {}

    def factory(model, thinking, schema_mode="native"):
        adapter = holder["p"]._v1_adapter(model, thinking, schema_mode)
        if model not in fakes:
            fakes[model] = FakeModels(plan.get(model, [response(json.dumps({"answer": "ок"}), model_version=model)]))

        class Client:
            models = fakes[model]

        adapter._client = Client()
        return adapter

    holder["p"] = GeminiProvider(api_key="k", env={}, adapter_factory=factory, sleep=sleeps.append)
    return holder["p"], fakes, sleeps


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
    # ответ не по схеме отдаётся как есть: проверку и одну починку по списку нарушений делает LLMClient
    p2, _, _ = sdk_provider({"gemini-3.8-flash": [response('{"wrong": 1}')]})
    r2 = p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r2["data"] == {"wrong": 1}


def test_sdk_not_json_retried_once_then_next_model():
    """Ответ не JSON — один повтор на той же модели, затем следующая модель; наверх не уходит «пустой» ответ."""
    p, fakes, sleeps = sdk_provider({"gemini-3.8-flash": [response("не JSON вовсе")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert len(fakes["gemini-3.8-flash"].calls) == 2
    assert r["model"] == "gemini-3.6-flash" and r["data"] == {"answer": "ок"}
    kinds = [a.get("subkind") for a in r["meta"]["attempts"] if "kind" in a]
    assert kinds == ["not_json", "not_json"]


def test_sdk_empty_text_retry_succeeds_on_same_model():
    p, fakes, sleeps = sdk_provider({"gemini-3.8-flash": [response(""), response(json.dumps({"answer": "да"}))]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"} and r["meta"]["called_model"] == "gemini-3.8-flash"
    assert len(fakes["gemini-3.8-flash"].calls) == 2


def test_sdk_empty_everywhere_explains_in_russian():
    plan = {m: [response("")] for m in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")}
    p, fakes, sleeps = sdk_provider(plan)
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "invalid_output"
    assert "пустой ответ" in e.value.message and e.value.message.startswith("Все модели Gemini")
    assert sum(len(f.calls) for f in fakes.values()) == 6


def test_llm_client_repairs_gemini_schema_mismatch_once():
    """Сквозь LLMClient: ответ не по схеме → одна починка с перечнем нарушений → принятый ответ."""
    from bcc_review.v2.llm import LLMClient
    p, fakes, sleeps = sdk_provider({"gemini-3.8-flash": [response('{"wrong": 1}'),
                                                          response(json.dumps({"answer": "исправлено"}))]})
    llm = LLMClient(p, provider_name="gemini", rpm=0, sleep=lambda s: None)
    data = llm.ask("judge", "S", "U", SCHEMA)
    assert data == {"answer": "исправлено"} and llm.stats["repaired"] == 1 and llm.stats["calls"] == 2
    second = fakes["gemini-3.8-flash"].calls[1][1]   # второй запрос несёт перечень нарушений
    assert second is not None


def test_sdk_schema_rejected_then_text_mode_without_response_schema():
    plan = {"gemini-3.8-flash": [api_error(400, "INVALID_ARGUMENT", "The specified schema produces a constraint that "
                                           "has too many states for serving."),
                                 response(json.dumps({"answer": "да"}))]}
    p, fakes, sleeps = sdk_provider(plan)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"} and r["meta"]["schema_mode"] == "text"
    first, second = fakes["gemini-3.8-flash"].calls
    assert first[1].response_json_schema is not None
    assert second[1].response_json_schema is None and second[1].response_mime_type == "application/json"
    assert second[1].system_instruction == "S"                      # общий префикс (неявный кэш) не тронут
    assert "JSON Schema" in json.dumps(fakes["gemini-3.8-flash"].contents[1], ensure_ascii=False, default=str)
