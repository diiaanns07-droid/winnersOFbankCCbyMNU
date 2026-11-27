"""№24, этап 2: обрезанный ответ — целые элементы вместо потерянного этапа (провайдер + патч №22 для llm.py).

Провайдер gemini (№24) к обрезке прикладывает ``partial`` — целые элементы ответа. Решает вызывающий: сначала
этап делит пакет или просит короче; когда делить нечего — ``LLMClient.salvaged`` берёт целые элементы, а прогон
помечается частичным с предупреждением. Код в ``llm.py`` и ``pipeline.py`` — у №22, готовый патч:
``tests/v2/fixtures/24_gemini/22_llm_salvage.patch`` (``git apply -p1 …``). До патча тесты ниже пропускаются.
"""
from __future__ import annotations

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.llm import LLMClient, Truncated

needs_patch = pytest.mark.skipif(not hasattr(LLMClient, "salvaged"),
                                 reason="ждёт патч №22: tests/v2/fixtures/24_gemini/22_llm_salvage.patch")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["candidates"],
          "properties": {"candidates": {"type": "array", "items": {"type": "string"}}}}


class TruncatingProvider:
    name = "gemini"
    handles_retries = True

    def __init__(self, partial):
        self.partial, self.calls = partial, 0

    def invoke(self, **kw):
        self.calls += 1
        exc = ProviderError("truncated", "Ответ Gemini обрезан по лимиту выходных токенов (MAX_TOKENS).")
        exc.partial = self.partial
        exc.salvage = {"items": {"candidates": len((self.partial or {}).get("candidates") or [])}}
        raise exc


def client(partial):
    return LLMClient(TruncatingProvider(partial), model="gemini-3.8-flash", provider_name="gemini",
                     sleep=lambda s: None)


def build(items):
    return "система", "проверь: " + ", ".join(map(str, items))


def merge(parts):
    return {"candidates": [c for p in parts for c in p.get("candidates", [])]}


@needs_patch
def test_split_exhausted_returns_whole_elements():
    llm = client({"candidates": ["A", "B"]})
    out = llm.ask_split("lens_analyst", build, ["R1"], SCHEMA, merge, max_output_tokens=32000)
    assert out == {"candidates": ["A", "B"]}
    assert llm.stats["salvaged"] == 1 and llm.stats["by_stage"]["lens_analyst"]["salvaged"] == 1


@needs_patch
def test_halves_salvaged_after_split():
    llm = client({"candidates": ["A"]})
    out = llm.ask_split("lens_analyst", build, ["R1", "R2"], SCHEMA, merge, max_output_tokens=32000)
    assert out == {"candidates": ["A", "A"]}          # обе половины обрезаны — у каждой взяты целые элементы
    assert llm.stats["split"] == 1 and llm.stats["salvaged"] == 2


@needs_patch
def test_without_partial_truncation_still_raises():
    llm = client(None)
    with pytest.raises(Truncated):
        llm.ask_split("lens_analyst", build, ["R1"], SCHEMA, merge, max_output_tokens=32000)


@needs_patch
def test_invalid_partial_is_not_used():
    llm = client({"candidates": [1, 2]})                 # не проходит схему — не берём
    with pytest.raises(Truncated):
        llm.ask_split("lens_analyst", build, ["R1"], SCHEMA, merge, max_output_tokens=32000)


def test_truncation_keeps_partial_on_exception():
    """Без патча: обрезка по-прежнему наверх (этап делит пакет), прогон не падает."""
    llm = client({"candidates": ["A"]})
    with pytest.raises(Truncated) as e:
        llm.ask("judge", "система", "запрос", SCHEMA, max_output_tokens=32000)
    if hasattr(LLMClient, "salvaged"):
        assert e.value.partial == {"candidates": ["A"]}
