"""Стыковой тест с bootstrap Max (bcc/integration, контракт v1 431f76d) и адаптером №11.

    PYTHONPATH=src python -m pytest tests/contract tests/p12/test_p12_contract_join.py -v -rs

Любой FAIL здесь — расхождение типов, которое нужно согласовать до слияния.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest
from p12_support import FIXTURES, MESSAGES, ROOT, load_fixture, synthetic_schema

from bcc_review import contracts
from bcc_review.providers import gemini

P11_SCHEMA = FIXTURES / "shared" / "p11_schema_candidates.json"


def p11_schema() -> dict:
    return json.loads(P11_SCHEMA.read_text(encoding="utf-8"))


def contract_stage_schema() -> dict:
    """Схема этапа на базе Candidate из контракта: {"candidates": [Candidate]} с общими $defs."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": contracts.DEFS,
            "type": "object", "additionalProperties": False, "required": ["candidates"],
            "properties": {"candidates": {"type": "array", "items": {"$ref": "#/$defs/Candidate"}}}}


def test_gemini_error_is_the_shared_provider_error() -> None:
    assert gemini.ProviderError is contracts.ProviderError
    assert issubclass(gemini.GeminiError, contracts.ProviderError)
    err = gemini.GeminiError("rate_limit", "x", retry_after_s=3.0, status=429, request_id="r", model="m",
                             usage={"input_tokens": 1})
    base = contracts.ProviderError("rate_limit", "x", retry_after_s=3.0, status=429, request_id="r", model="m",
                                   usage={"input_tokens": 1})
    for name in ("kind", "message", "retry_after_s", "status", "request_id", "usage", "model", "transient"):
        assert getattr(err, name) == getattr(base, name), name


def test_every_kind_survives_contract_normalisation() -> None:
    for kind in gemini.ErrorKind:
        assert contracts.ProviderError(kind.value).kind == kind.value, "иначе контракт превратит kind в unknown"


def test_adapter_matches_provider_adapter_protocol() -> None:
    proto = inspect.signature(contracts.ProviderAdapter.invoke).parameters
    ours = inspect.signature(gemini.GeminiAdapter.invoke).parameters
    for name in ("model", "messages", "schema", "timeout_s"):
        assert ours[name].kind is proto[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert gemini.GeminiAdapter.name == "gemini" and "gemini" in contracts.PROVIDERS


def test_result_has_contract_keys(make_adapter, fake) -> None:
    fake.on("*", "ok_empty")
    result = make_adapter().invoke(model=None, messages=MESSAGES, schema=synthetic_schema(), timeout_s=30)
    assert {"data", "usage", "model", "request_id", "stop_reason"} <= set(result)
    assert {"input_tokens", "output_tokens"} <= set(result["usage"])
    assert result["stop_reason"] == "STOP" and result["meta"]["requested_model"] == gemini.DEFAULT_MODEL
    json.dumps(result, ensure_ascii=False)  # результат сериализуем без SDK-объектов


@pytest.mark.parametrize("schema_factory, found, nothing", [
    (synthetic_schema, "ok_one_finding", "ok_empty"),
    (p11_schema, "ok_p11_candidates", "ok_p11_empty"),
    (p11_schema, "ok_contract_candidates", "ok_p11_empty"),
    (contract_stage_schema, "ok_contract_candidates", "ok_p11_empty"),
], ids=["p12-synthetic", "p11-shared", "p11-shared-normalized", "contract-Candidate"])
def test_one_finding_and_empty_list_pass_stage_schema(make_adapter, fake, schema_factory, found, nothing) -> None:
    fake.on("*", found, nothing)
    adapter = make_adapter()
    schema = schema_factory()
    one = adapter.invoke(model=None, messages=MESSAGES, schema=schema, timeout_s=30)
    empty = adapter.invoke(model=None, messages=MESSAGES, schema=schema, timeout_s=30)
    assert one["data"]["candidates"] and empty["data"]["candidates"] == []


@pytest.mark.parametrize("fixture", ["ok_one_finding", "ok_contract_candidates"])
def test_findings_pass_contract_candidate(make_adapter, fake, fixture) -> None:
    fake.on("*", fixture)
    schema = synthetic_schema() if fixture == "ok_one_finding" else contract_stage_schema()
    result = make_adapter().invoke(model=None, messages=MESSAGES, schema=schema, timeout_s=30)
    for candidate in result["data"]["candidates"]:
        contracts.validate(candidate, "Candidate")


def test_p11_schema_allows_null_lists_that_contract_rejects(make_adapter, fake) -> None:
    """Открытый вопрос к №11 и Max: в схеме №11 inspected_block_ids может быть null, в контракте — только массив."""
    fake.on("*", "ok_p11_candidates")
    result = make_adapter().invoke(model=None, messages=MESSAGES, schema=p11_schema(), timeout_s=30)
    candidate = result["data"]["candidates"][0]
    assert candidate["inspected_block_ids"] is None
    with pytest.raises(contracts.ContractError, match="inspected_block_ids"):
        contracts.validate(candidate, "Candidate")


def test_p11_shared_schema_conversion_log() -> None:
    wire, log = gemini.to_gemini_schema(p11_schema())
    actions = {(e["keyword"], e["action"]) for e in log}
    assert ("minLength", "moved to description") in actions
    assert ("type[]", "rewritten as anyOf") in actions  # inspected_block_ids: ["array", "null"]
    assert wire["properties"]["candidates"]["items"]["properties"]["hints"]["minItems"] == 1


def test_whole_contract_schema_converts() -> None:
    wire, log = gemini.to_gemini_schema(json.loads((ROOT / "contracts" / "v1.json").read_text(encoding="utf-8")))
    assert isinstance(wire, dict) and log


def test_p11_adapter_signature_if_present() -> None:
    try:
        module = importlib.import_module("bcc_review.providers.anthropic")
    except ImportError:
        pytest.skip("адаптер №11 ещё не влит в эту ветку")
    theirs = inspect.signature(module.AnthropicAdapter.invoke).parameters
    for name in ("model", "messages", "schema", "timeout_s"):
        assert name in theirs and theirs[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_shared_fixture_provenance_is_recorded() -> None:
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert "p11_schema_candidates.json" in readme
    assert load_fixture("ok_p11_candidates")["body"]["modelVersion"]
    assert Path(P11_SCHEMA).exists()
