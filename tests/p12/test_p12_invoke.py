"""Успешные ответы и форма запроса к Gemini через настоящий SDK и подставной транспорт."""

from __future__ import annotations

import inspect
import json

from jsonschema import Draft202012Validator
from p12_support import MESSAGES, TEST_KEY, load_fixture

from bcc_review.providers.gemini import GeminiAdapter, to_gemini_schema

CONTRACT_KEYS = {"data", "usage", "model", "request_id"}


def test_invoke_signature_matches_shared_contract() -> None:
    params = inspect.signature(GeminiAdapter.invoke).parameters
    for name in ("model", "messages", "schema", "timeout_s"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is inspect.Parameter.empty


def test_one_finding_passes_full_schema(make_adapter, fake, schema) -> None:
    fake.on("gemini-2.5-flash", "ok_one_finding")
    result = make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)

    assert CONTRACT_KEYS <= set(result)
    Draft202012Validator(schema).validate(result["data"])
    finding = result["data"]["candidates"][0]
    assert finding["title"] == "Не определено «быстро» для отправки push"
    assert finding["hints"] == [{"block_id": "b1", "quote": "быстро отправлять push"}]
    assert result["model"] == "gemini-2.5-flash"
    assert result["request_id"] == "syn-ok-one-0001"
    assert result["usage"] == {"input_tokens": 812, "output_tokens": 143, "thinking_tokens": 246,
                               "cached_tokens": None, "total_tokens": 1201, "physical_calls": 1}
    meta = result["meta"]
    assert meta["fallback_used"] is False and meta["attempts"] == []
    assert meta["finish_reason"] == "STOP" and meta["called_model"] == "gemini-2.5-flash"
    assert meta["schema_adjustments"], "журнал приведения схемы передаётся в meta"


def test_empty_findings_are_a_valid_result_not_an_empty_response(make_adapter, fake, schema) -> None:
    fake.on("gemini-2.5-flash", "ok_empty")
    result = make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
    assert result["data"] == {"stage": "requirement_check", "candidates": [], "notes": "Дефектов не найдено"}
    Draft202012Validator(schema).validate(result["data"])
    assert result["usage"]["thinking_tokens"] is None


def test_top_level_empty_array_is_accepted(make_adapter, fake) -> None:
    body = load_fixture("ok_empty")
    body["body"]["candidates"][0]["content"]["parts"] = [{"text": "[]"}]
    fake.on("gemini-2.5-flash", body)
    result = make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES,
                                   schema={"type": "array", "items": {"type": "string"}}, timeout_s=30)
    assert result["data"] == []


def test_thought_parts_are_ignored_and_fences_tolerated(make_adapter, fake, schema) -> None:
    fake.on("gemini-2.5-flash", "ok_with_thought_part", "ok_fenced_json")
    adapter = make_adapter()
    for _ in range(2):
        result = adapter.invoke(model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=60)
        assert result["data"]["candidates"] == []


def test_wire_request_shape(make_adapter, fake, schema) -> None:
    fake.on("*", "ok_empty")
    adapter = make_adapter()
    adapter.invoke(model="models/gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=42.5)
    adapter.invoke(model="gemini-3-flash-preview", messages=MESSAGES, schema=schema, timeout_s=30)

    first, second = fake.requests
    assert first["model"] == "gemini-2.5-flash", "префикс models/ снимается"
    body = first["body"]
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == to_gemini_schema(schema)[0]
    assert config["candidateCount"] == 1 and config["temperature"] == 0.0
    assert "maxOutputTokens" not in config, "по умолчанию лимит не ставим: рассуждения не должны съедать JSON"
    assert body["systemInstruction"]["parts"][0]["text"] == MESSAGES[0]["content"]
    assert body["contents"] == [{"role": "user", "parts": [{"text": MESSAGES[1]["content"]}]}]
    assert "быстро" in json.dumps(body, ensure_ascii=False)
    assert first["timeout"]["read"] == 42.5
    assert first["headers"]["x-goog-api-key"] == TEST_KEY
    assert "temperature" not in second["body"]["generationConfig"], "у Gemini 3 температура по умолчанию"


def test_optional_generation_settings(make_adapter, fake, schema) -> None:
    fake.on("*", "ok_empty")
    make_adapter(max_output_tokens=4096, thinking_budget=0).invoke(
        model="gemini-2.5-flash", messages=MESSAGES, schema=schema, timeout_s=30, temperature=0.2)
    config = fake.requests[0]["body"]["generationConfig"]
    assert config["maxOutputTokens"] == 4096
    # SDK 3.6.1 кладёт thinkingConfig в snake_case; proto3 JSON на сервере принимает оба написания.
    thinking = config.get("thinkingConfig") or config.get("thinking_config")
    assert thinking in ({"thinkingBudget": 0}, {"thinking_budget": 0})
    assert config["temperature"] == 0.2


def test_list_models_keeps_generate_content_and_puts_flash_first(make_adapter) -> None:
    rows = make_adapter().list_models()
    assert [r["id"] for r in rows] == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
    assert rows[0]["output_token_limit"] == 65536
