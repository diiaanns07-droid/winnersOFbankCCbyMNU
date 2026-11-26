"""Стыковой тест с bootstrap Max (bcc/integration, contracts/HANDOFF.md).

Пока общая библиотека не опубликована, проверяется совместимая копия
ProviderError. После появления SHA тест начинает требовать общий класс.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest

import bcc_review.providers.anthropic as adapter_mod

ROOT = Path(__file__).resolve().parents[2]


def _shared_error():
    for name in adapter_mod._SHARED_ERROR_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        cls = getattr(module, "ProviderError", None)
        if cls is not None:
            return cls, name
    return None, None


def test_provider_error_signature_matches_contract():
    sig = inspect.signature(adapter_mod.ProviderError.__init__)
    params = list(sig.parameters)[1:3]
    assert params == ["kind", "retry_after_s"]
    assert sig.parameters["retry_after_s"].default is None
    err = adapter_mod.ProviderError("auth")
    assert err.kind == "auth" and err.retry_after_s is None


def test_adapter_uses_shared_provider_error_when_published():
    shared, module = _shared_error()
    if shared is None:
        pytest.skip("bootstrap Max ещё не опубликован: используется bootstrap-fallback")
    assert adapter_mod.ProviderError is shared
    assert adapter_mod.PROVIDER_ERROR_SOURCE == module


def test_candidate_schema_matches_contract_when_published():
    contract = ROOT / "contracts" / "v1.json"
    if not contract.exists():
        pytest.skip("contracts/v1.json ещё не опубликован")
    text = json.dumps(json.loads(contract.read_text(encoding="utf-8")), ensure_ascii=False)
    for field in ("scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints",
                  "block_id", "quote"):
        assert f'"{field}"' in text, f"поле {field} из тестовой схемы p11 не найдено в contracts/v1.json"
