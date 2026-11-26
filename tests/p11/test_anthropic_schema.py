"""Схема запроса для structured outputs и локальная проверка полной схемы."""

from __future__ import annotations

import jsonschema
import pytest

from bcc_review.providers.anthropic import ProviderError, normalize_enum_case, to_wire_schema


def test_wire_schema_supported_subset(schema):
    wire = to_wire_schema(schema)
    item = wire["properties"]["candidates"]["items"]
    hint = wire["$defs"]["hint"]

    assert "$schema" not in wire
    assert wire["additionalProperties"] is False and item["additionalProperties"] is False
    assert item["properties"]["inspected_block_ids"]["type"] == ["array", "null"]  # type arrays сохраняются
    assert item["properties"]["hints"]["minItems"] == 1
    assert "minLength" not in hint["properties"]["quote"]
    assert hint["properties"]["quote"]["description"] == "{minLength: 1}"
    assert schema["$defs"]["hint"]["properties"]["quote"]["minLength"] == 1  # исходник не тронут


def test_wire_schema_rewrites_unsupported_keywords():
    src = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "minimum": 0, "maximum": 10, "description": "число"},
            "a": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
            "o": {"oneOf": [{"type": "string", "format": "regex"}, {"type": "null"}]},
            "m": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["n"],
        "additionalProperties": True,
    }
    wire = to_wire_schema(src)
    props = wire["properties"]
    assert props["n"] == {"type": "integer", "description": "число\n\n{maximum: 10, minimum: 0}"}
    assert "minItems" not in props["a"] and "maxItems: 3" in props["a"]["description"]
    assert "oneOf" not in props["o"] and len(props["o"]["anyOf"]) == 2
    assert props["o"]["anyOf"][0]["description"] == '{format: "regex"}'
    assert props["m"]["additionalProperties"] is False and props["m"]["properties"] == {}
    assert wire["additionalProperties"] is False


def test_enum_case_only_when_unique():
    schema = {"type": "object", "properties": {"s": {"enum": ["Major", "major"]}, "t": {"enum": ["minor"]}}}
    data = {"s": "MAJOR", "t": "Minor"}
    fixed = normalize_enum_case(data, jsonschema.Draft202012Validator(schema))
    assert fixed == 1
    assert data == {"s": "MAJOR", "t": "minor"}  # неоднозначный регистр не угадываем


def test_invalid_stage_schema_is_rejected_before_call(make_adapter, messages):
    adapter = make_adapter("success_candidates")
    with pytest.raises(ProviderError) as info:
        adapter.invoke(model="claude-opus-5-5", messages=messages, schema={"type": "nonsense"}, timeout_s=5)
    assert info.value.kind == "invalid_request" and info.value.subkind == "invalid_schema"
    assert adapter.passport()["physical_calls"] == {"messages": 0, "models": 0, "other": 0}
