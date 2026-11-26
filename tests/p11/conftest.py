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


#: Наблюдения стыка Asker → адаптер → транспорт (test_asker_path.py); печатаются в конце прогона.
OBSERVATIONS: list[tuple[str, int, int, str, str]] = []


def observe(scenario: str, transport: Any, clock: Any, engine_error: str) -> None:
    pause = " + ".join(f"{s:g} с" for s in clock.sleeps) or "0"
    OBSERVATIONS.append((scenario, transport.count("GET"), transport.count("POST"), pause, engine_error))


#: Исходы одного ответа в report.json (test_response_metadata.py); печатаются в конце прогона.
OUTCOMES: list[tuple[str, ...]] = []


def outcome(*row: Any) -> None:
    OUTCOMES.append(tuple(str(c) for c in row))


def pytest_terminal_summary(terminalreporter: Any) -> None:
    tr = terminalreporter
    if OBSERVATIONS:
        tr.section("p11: Asker → AnthropicAdapter → ScriptedTransport (httpx2)")
        tr.write_line("| сценарий | GET | POST | пауза | тип ошибки в движке |")
        tr.write_line("|---|---|---|---|---|")
        for row in OBSERVATIONS:
            tr.write_line("| " + " | ".join(str(c) for c in row) + " |")
    if OUTCOMES:
        tr.section("p11: один ответ → Engine.run_individual / build_checks / build_run (report.json)")
        tr.write_line("| исход ответа | POST | GET | фактическая модель | успешная стадия | подпись в отчёте |")
        tr.write_line("|---|---|---|---|---|---|")
        for row in OUTCOMES:
            tr.write_line("| " + " | ".join(row) + " |")


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
