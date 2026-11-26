"""Один маленький реальный вызов Claude API. По умолчанию пропускается.

Запускать только в выделенном интеграционном прогоне (координируют Max и №18):

    BCC_P11_LIVE=1 ANTHROPIC_API_KEY=... python -m pytest tests/p11/test_live_smoke.py -s

Тест печатает паспорт с фактической моделью ответа и request_id.
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BCC_P11_LIVE") != "1", reason="живой вызов только при BCC_P11_LIVE=1")


@pytest.fixture(autouse=True)
def _no_real_credentials():
    """Перекрывает очистку окружения из conftest: здесь ключ нужен."""


def test_live_small_call():
    from bcc_review.providers.anthropic import AnthropicAdapter

    adapter = AnthropicAdapter(max_tokens=2000, effort="low")
    schema = {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": ["ok", "defect"]}, "quote": {"type": "string"}},
        "required": ["verdict", "quote"],
        "additionalProperties": False,
    }
    messages = [
        {"role": "system", "content": "Ты проверяешь одно требование. Ответь JSON по схеме."},
        {"role": "user", "content": "Требование: «Система должна быстро отправлять push». "
                                    "Есть ли дефект проверяемости? В quote процитируй проблемное слово."},
    ]
    result = adapter.invoke(model=None, messages=messages, schema=schema, timeout_s=120)
    print(json.dumps({"result": result, "passport": adapter.passport()}, ensure_ascii=False, indent=2))
    assert result["model"] and result["request_id"]
    assert adapter.passport()["run_mode"] == "rules_plus_llm"
    assert adapter.passport()["official_endpoint"] is True
    assert adapter.physical_calls == 1
