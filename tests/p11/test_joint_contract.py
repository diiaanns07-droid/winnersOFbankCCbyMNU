"""Стыковой тест с контрактом Max (bcc/integration, contracts/HANDOFF.md).

Адаптер поднимает общий ``bcc_review.contracts.ProviderError`` — тот класс, который
ловит Asker, — и передаёт поля контракта именованно.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import bcc_review.providers.anthropic as adapter_mod
from bcc_review import contracts

ROOT = Path(__file__).resolve().parents[2]


def test_adapter_uses_shared_provider_error():
    assert adapter_mod.ProviderError is contracts.ProviderError
    assert adapter_mod.PROVIDER_ERROR_SOURCE == "bcc_review.contracts"


def test_provider_error_fields_follow_contract_signature():
    sig = inspect.signature(contracts.ProviderError.__init__)
    assert list(sig.parameters)[1:3] == ["kind", "message"]
    keyword_only = {n for n, p in sig.parameters.items() if p.kind is inspect.Parameter.KEYWORD_ONLY}
    assert {"retry_after_s", "status", "request_id", "usage", "model"} <= keyword_only

    err = adapter_mod._make_error(adapter_mod.KIND_RATE_LIMIT, 7.0, http_status=429, request_id="req_x",
                                  detail="Временный лимит")
    assert (err.kind, err.message, err.retry_after_s, err.status, err.request_id, err.usage, err.model) == (
        "rate_limit", "Временный лимит", 7.0, 429, "req_x", {}, None)
    assert err.transient is True


def test_candidate_schema_matches_contract_when_published():
    contract = ROOT / "contracts" / "v1.json"
    if not contract.exists():
        pytest.skip("contracts/v1.json ещё не опубликован")
    text = json.dumps(json.loads(contract.read_text(encoding="utf-8")), ensure_ascii=False)
    for field in ("scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints",
                  "block_id", "quote"):
        assert f'"{field}"' in text, f"поле {field} из тестовой схемы p11 не найдено в contracts/v1.json"
