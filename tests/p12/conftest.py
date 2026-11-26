"""Фикстуры pytest для тестов №12 (адаптер Gemini)."""

from __future__ import annotations

from typing import Any

import pytest
from p12_support import TEST_KEY, FakeClock, FakeGemini, synthetic_schema

from bcc_review.providers.gemini import GeminiAdapter


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
