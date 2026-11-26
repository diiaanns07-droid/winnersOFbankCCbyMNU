"""Общие фикстуры tests/p11: адаптер Anthropic поверх записанных ответов, без ключа."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_ENV_TO_CLEAR = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_MAX_TOKENS",
    "ANTHROPIC_EFFORT",
    "ANTHROPIC_FALLBACKS",
    "ANTHROPIC_PROFILE",
)


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный прогон не требует ключа: окружение очищается для каждого теста."""
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)


def load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def models() -> dict[str, Any]:
    return {k: v for k, v in load("model_info").items() if not k.startswith("_")}


@pytest.fixture
def schema() -> dict[str, Any]:
    return load("schema_candidates")


@pytest.fixture
def messages() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "Ты проверяешь ТЗ. Отвечай только JSON по схеме."},
        {"role": "user", "content": "Документ: <blocks>...</blocks>. Найди противоречия набора."},
    ]


@pytest.fixture
def make_adapter():
    from bcc_review.providers.anthropic import AnthropicAdapter

    def _make(*names: str, **kwargs: Any) -> AnthropicAdapter:
        return AnthropicAdapter.replay([load(n) for n in names], models=kwargs.pop("models", models()), **kwargs)

    return _make
