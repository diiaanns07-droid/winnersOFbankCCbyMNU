"""Фикстуры pytest для тестов №12 (адаптер Gemini)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from bcc_review.providers.gemini import GeminiAdapter

from .p12_support import TEST_KEY, FakeClock, FakeGemini, synthetic_schema


@pytest.fixture(autouse=True)
def _isolate_gemini_env(request, monkeypatch) -> None:
    """GeminiAdapter() читает GEMINI_* из окружения: офлайн-тесты не должны зависеть от shell разработчика."""
    if request.module.__name__.endswith("test_p12_live"):
        return
    for name in [n for n in os.environ if n.startswith("GEMINI_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake(clock: FakeClock) -> FakeGemini:
    return FakeGemini(clock)


@pytest.fixture
def make_adapter(fake: FakeGemini, clock: FakeClock):
    def build(**kwargs: Any) -> GeminiAdapter:
        kwargs.setdefault("api_key", TEST_KEY)
        return GeminiAdapter(http_client=fake.http_client(), clock=clock, **kwargs)
    return build


@pytest.fixture
def schema() -> dict[str, Any]:
    return synthetic_schema()
