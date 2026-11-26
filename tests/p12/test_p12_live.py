"""Живая проверка на реальном ключе. По умолчанию пропускается.

    export GEMINI_API_KEY=...            # ключ команды/жюри, не коммитить
    export GEMINI_MODEL=gemini-2.5-flash # модель из `python -m bcc_review.providers.gemini models`
    P12_LIVE=1 PYTHONPATH=src python -m pytest tests/p12/test_p12_live.py -v -s

Тест тратит 2–3 запроса из квоты модели.
"""

from __future__ import annotations

import json
import os

import pytest
from jsonschema import Draft202012Validator

from bcc_review.providers.gemini import GeminiAdapter, ProviderError

from .p12_support import synthetic_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("P12_LIVE") != "1" or not os.environ.get("GEMINI_API_KEY"),
    reason="живой прогон: нужны P12_LIVE=1 и GEMINI_API_KEY",
)

SYSTEM = ("Ты аналитик банка и проверяешь требования по ISO/IEC/IEEE 29148. Отвечай только JSON по схеме. "
          "stage всегда 'requirement_check'. Цитата в hints — дословная подстрока блока. Тексты на русском.")


def ask(adapter: GeminiAdapter, user: str) -> dict:
    try:
        result = adapter.invoke(model=None, messages=[{"role": "system", "content": SYSTEM},
                                                       {"role": "user", "content": user}],
                                schema=synthetic_schema(), timeout_s=120)
    except ProviderError as err:
        pytest.fail(f"Gemini: {json.dumps(err.to_dict(), ensure_ascii=False)}")
    meta_keys = ("requested_model", "called_model", "fallback_used", "latency_s")
    passport = {k: result[k] for k in ("model", "request_id", "stop_reason", "usage")}
    passport["meta"] = {k: result["meta"][k] for k in meta_keys}
    print(json.dumps(passport, ensure_ascii=False))
    Draft202012Validator(synthetic_schema()).validate(result["data"])
    return result


def test_live_models_list() -> None:
    rows = GeminiAdapter.from_env().list_models()
    print(json.dumps([r["id"] for r in rows if r["flash"]], ensure_ascii=False))
    assert any(r["flash"] for r in rows)


def test_live_one_finding() -> None:
    result = ask(GeminiAdapter.from_env(),
                 "Требование R-001 (блок b1): «Система должна быстро отправлять push клиенту.» "
                 "Найди дефекты этого требования.")
    assert result["data"]["candidates"], "ожидалась хотя бы одна находка про «быстро»"


def test_live_empty_list() -> None:
    result = ask(GeminiAdapter.from_env(),
                 "Требование R-002 (блок b2): «Порог задаётся целым числом тенге от 1 000 до 1 000 000 включительно.» "
                 "Верни candidates только для противоречий между двумя разными требованиями. "
                 "Здесь одно требование, поэтому противоречий нет: верни пустой массив candidates.")
    assert result["data"]["candidates"] == []
