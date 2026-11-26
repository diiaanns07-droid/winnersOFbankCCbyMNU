"""Сопоставление общего формата messages/schema с форматом Gemini."""

from __future__ import annotations

from typing import Any

import pytest

from bcc_review.providers.gemini import (
    ErrorKind,
    ProviderError,
    SchemaConversionError,
    to_gemini_messages,
    to_gemini_schema,
)

from .p12_support import synthetic_schema

UNSUPPORTED = {"$ref", "$defs", "$schema", "$id", "pattern", "minLength", "maxLength", "uniqueItems",
               "const", "oneOf", "allOf", "not", "if", "then", "else", "patternProperties", "multipleOf"}


def walk_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "properties":
                keys.add(key)
            keys |= walk_keys(value) if key != "properties" else set().union(*(walk_keys(v) for v in value.values()))
    elif isinstance(node, list):
        for item in node:
            keys |= walk_keys(item)
    return keys


def test_synthetic_schema_is_reduced_to_supported_subset() -> None:
    wire, log = to_gemini_schema(synthetic_schema())
    assert not walk_keys(wire) & UNSUPPORTED
    props = wire["properties"]
    assert props["stage"] == {"enum": ["requirement_check"]}
    assert props["notes"] == {"description": "Пояснение модели или null",
                              "anyOf": [{"type": "string"}, {"type": "null"}]}
    candidates = props["candidates"]
    assert candidates["minItems"] == 0 and candidates["type"] == "array"
    item = candidates["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["criterion"]["description"] == (
        'Код критерия И1–И9 или Н1–Н8 [ограничения: pattern="^(И[1-9]|Н[1-8])$"]'), "pattern уходит подсказкой"
    assert item["properties"]["hints"]["items"]["properties"]["quote"]["description"] == (
        "Дословная подстрока block.text [ограничения: minLength=1]")
    assert item["properties"]["title"]["description"] == "[ограничения: minLength=1, maxLength=200]"
    assert item["properties"]["hints"]["items"]["required"] == ["block_id", "quote"]
    assert set(item["required"]) >= {"scope", "severity", "hints"}
    actions = {(e["path"], e["keyword"]) for e in log}
    assert ("/properties/candidates/items/properties/criterion", "pattern") in actions
    assert ("/properties/candidates/items/properties/hints/items/properties/quote", "minLength") in actions
    assert ("/properties/candidates/items/properties/inspected_block_ids", "uniqueItems") in actions
    assert ("/properties/stage", "const") in actions
    assert ("/", "$id") in actions
    moved = {e["keyword"] for e in log if e["action"] == "moved to description"}
    assert moved == {"pattern", "minLength", "maxLength", "uniqueItems"}
    assert not any(e["keyword"] == "$defs" for e in log), "корневые $defs удаляются молча после подстановки"


def test_conversion_is_idempotent_and_does_not_mutate_input() -> None:
    original = synthetic_schema()
    snapshot = synthetic_schema()
    wire, _ = to_gemini_schema(original)
    again, log = to_gemini_schema(wire)
    assert again == wire and log == []
    assert original == snapshot


def test_oneof_and_anyof_merge_regardless_of_key_order() -> None:
    a, _ = to_gemini_schema({"oneOf": [{"type": "string"}], "anyOf": [{"type": "integer"}]})
    b, _ = to_gemini_schema({"anyOf": [{"type": "integer"}], "oneOf": [{"type": "string"}]})
    assert sorted(x["type"] for x in a["anyOf"]) == sorted(x["type"] for x in b["anyOf"]) == ["integer", "string"]


def test_formats_and_type_lists() -> None:
    wire, log = to_gemini_schema({"type": "object", "properties": {
        "at": {"type": "string", "format": "date-time"},
        "url": {"type": "string", "format": "uri"},
        "n": {"type": ["integer"]},
        "maybe": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 3},
    }})
    p = wire["properties"]
    assert p["at"]["format"] == "date-time"
    assert "format" not in p["url"]
    assert p["n"] == {"type": "integer"}
    assert p["maybe"] == {"anyOf": [{"type": "array", "items": {"type": "string"}, "maxItems": 3}, {"type": "null"}]}
    assert {"path": "/properties/url", "keyword": "format:uri", "action": "moved to description"} in log
    assert p["url"]["description"] == '[ограничения: format="uri"]'


@pytest.mark.parametrize("schema, needle", [
    ({"$defs": {"n": {"type": "object", "properties": {"next": {"$ref": "#/$defs/n"}}}}, "$ref": "#/$defs/n"},
     "рекурсивная"),
    ({"$ref": "https://example.org/x.json"}, "внешняя"),
    ({"$ref": "#/$defs/missing"}, "не найден"),
])
def test_unconvertible_schemas_fail_loudly(schema: dict[str, Any], needle: str) -> None:
    with pytest.raises(SchemaConversionError, match=needle):
        to_gemini_schema(schema)


def test_messages_mapping_roles_merge_and_blocks() -> None:
    system, contents = to_gemini_messages([
        {"role": "system", "content": "Правила: только JSON."},
        {"role": "system", "content": [{"type": "text", "text": "Язык — русский."}]},
        {"role": "user", "content": "Документ A"},
        {"role": "user", "content": [{"type": "text", "text": "Документ B"}]},
        {"role": "assistant", "content": "{\"candidates\": []}"},
        {"role": "user", "content": "Проверь ещё раз"},
    ])
    assert system == "Правила: только JSON.\n\nЯзык — русский."
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[0]["parts"] == [{"text": "Документ A"}, {"text": "Документ B"}]


@pytest.mark.parametrize("messages", [
    [{"role": "system", "content": "только система"}],
    [{"role": "tool", "content": "x"}],
    [{"role": "user", "content": [{"type": "image", "source": "..."}]}],
    [{"role": "user", "content": 42}],
])
def test_bad_messages_are_provider_errors(messages: list[dict[str, Any]]) -> None:
    with pytest.raises(ProviderError) as info:
        to_gemini_messages(messages)
    assert info.value.kind == ErrorKind.BAD_REQUEST and not info.value.transient
