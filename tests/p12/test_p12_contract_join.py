"""Стыковой тест с bootstrap Max/№11. Пропускается, пока общих модулей нет в checkout.

После публикации bcc/integration запустите:
    PYTHONPATH=src python -m pytest tests/p12/test_p12_contract_join.py -v -rs
Любой FAIL здесь — расхождение типов, которое нужно согласовать до слияния.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from p12_support import MESSAGES, ROOT, synthetic_schema

from bcc_review.providers import gemini

BOOTSTRAP_ERRORS = ("bcc_review.providers.base", "bcc_review.providers.errors")


def _first_module(names: tuple[str, ...]) -> Any:
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def test_shared_provider_error_is_the_base() -> None:
    shared = _first_module(BOOTSTRAP_ERRORS)
    if shared is None or not hasattr(shared, "ProviderError"):
        pytest.skip("bootstrap ещё не опубликован: общий ProviderError не найден, используется локальный")
    assert issubclass(gemini.ProviderError, shared.ProviderError)
    err = gemini.ProviderError(gemini.ErrorKind.RATE_LIMITED, "x", retry_after=3.0)
    probe = getattr(shared, "PROVIDER_ERROR_FIELDS", None) or ("kind", "retryable", "retry_after", "provider", "model")
    missing = [name for name in probe if not hasattr(err, name)]
    assert not missing, f"у gemini.ProviderError нет полей общего контракта: {missing}"


def test_error_kinds_match_shared_vocabulary() -> None:
    shared = _first_module(BOOTSTRAP_ERRORS)
    kinds = getattr(shared, "ErrorKind", None) if shared else None
    if kinds is None:
        pytest.skip("общий ErrorKind не опубликован")
    shared_values = {str(getattr(k, "value", k)) for k in kinds}
    ours = {k.value for k in gemini.ErrorKind}
    assert ours <= shared_values, f"категории только у Gemini: {sorted(ours - shared_values)}"


def test_anthropic_adapter_has_same_invoke_contract() -> None:
    module = _first_module(("bcc_review.providers.anthropic",))
    adapter_cls = next((obj for _, obj in inspect.getmembers(module, inspect.isclass)
                        if hasattr(obj, "invoke") and obj.__module__ == module.__name__), None) if module else None
    if adapter_cls is None:
        pytest.skip("адаптер №11 ещё не в checkout")
    theirs = inspect.signature(adapter_cls.invoke).parameters
    for name in ("model", "messages", "schema", "timeout_s"):
        assert name in theirs and theirs[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_contract_candidate_fields_match_synthetic_schema() -> None:
    path = ROOT / "contracts" / "v1.json"
    if not path.exists():
        pytest.skip("contracts/v1.json ещё не опубликован")
    contract = json.loads(path.read_text(encoding="utf-8"))
    defs = {**contract.get("$defs", {}), **contract.get("definitions", {})}
    candidate = next((v for k, v in defs.items() if k.lower() == "candidate"), None)
    if candidate is None:
        pytest.skip("в contracts/v1.json нет определения Candidate")
    ours = set(synthetic_schema()["$defs"]["candidate"]["properties"])
    theirs = set(candidate.get("properties", {}))
    assert ours <= theirs | {"inspected_block_ids"}, f"поля не из контракта: {sorted(ours - theirs)}"


def test_contract_schema_survives_gemini_conversion(make_adapter, fake) -> None:
    """Весь contracts/v1.json должен приводиться к подмножеству Gemini без ошибок."""
    path = ROOT / "contracts" / "v1.json"
    if not path.exists():
        pytest.skip("contracts/v1.json ещё не опубликован")
    contract = json.loads(path.read_text(encoding="utf-8"))
    wire, log = gemini.to_gemini_schema(contract)
    assert isinstance(wire, dict)
    Path(ROOT / "tests" / "p12" / ".last_contract_conversion.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def test_result_shape_is_provider_neutral(make_adapter, fake) -> None:
    fake.on("*", "ok_empty")
    result = make_adapter().invoke(model="gemini-2.5-flash", messages=MESSAGES,
                                   schema=synthetic_schema(), timeout_s=30)
    assert {"data", "usage", "model", "request_id"} <= set(result)
    assert {"input_tokens", "output_tokens", "physical_calls"} <= set(result["usage"])
    json.dumps(result, ensure_ascii=False)  # результат сериализуем без SDK-объектов
