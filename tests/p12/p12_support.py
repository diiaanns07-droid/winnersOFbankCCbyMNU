"""Помощники тестов №12: подставной HTTP-транспорт Gemini и управляемые часы.

Ответы подаются на уровне HTTP через MockTransport, поэтому разбор ответа и
ошибок проходит через настоящий код google-genai, а не через заглушку SDK.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("google.genai", reason="нужен google-genai: pip install google-genai")

try:  # google-genai 3.x по умолчанию использует httpx2, старые версии — httpx
    import httpx2 as httpx_lib
except ImportError:  # pragma: no cover
    import httpx as httpx_lib  # type: ignore[no-redef]


FIXTURES = Path(__file__).parent / "fixtures"
GEMINI_FIXTURES = FIXTURES / "gemini"
TEST_KEY = "AIzaTEST-not-a-real-key-p12"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((GEMINI_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def synthetic_schema() -> dict[str, Any]:
    return json.loads((FIXTURES / "synthetic_schema.json").read_text(encoding="utf-8"))


MESSAGES = [
    {"role": "system", "content": "Ты проверяешь требования. Отвечай только JSON по схеме."},
    {"role": "user", "content": "Блок b1: «Система должна быстро отправлять push клиенту.»"},
]


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeGemini:
    """Сценарий ответов по моделям. Последний шаг повторяется («залипает»)."""

    URL = re.compile(r"/models/([^/:]+):generateContent$")

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.script: dict[str, list[Any]] = {}
        self.requests: list[dict[str, Any]] = []

    def on(self, model: str, *steps: Any) -> FakeGemini:
        self.script.setdefault(model, []).extend(steps)
        return self

    def calls_for(self, model: str) -> int:
        return sum(1 for r in self.requests if r["model"] == model)

    def handler(self, request: Any) -> Any:
        if request.url.path.endswith("/models"):
            self.requests.append({"model": None, "list": True, "headers": dict(request.headers)})
            return httpx_lib.Response(200, json=load_fixture("models_list")["body"])
        match = self.URL.search(request.url.path)
        assert match, f"неожиданный URL {request.url}"
        model = match.group(1)
        record = {
            "model": model,
            "t": self.clock.now,
            "body": json.loads(request.content.decode("utf-8")),
            "timeout": request.extensions.get("timeout"),
            "headers": dict(request.headers),
        }
        self.requests.append(record)
        queue = self.script.get(model) or self.script.get("*")
        assert queue, f"для модели {model} нет сценария"
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        latency = 0.0
        if isinstance(step, tuple):
            step, latency = step
        self.clock.advance(latency)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            step = step(request)
            if isinstance(step, httpx_lib.Response):
                return step
        fixture = load_fixture(step) if isinstance(step, str) else step
        record["status"] = fixture["http_status"]
        return httpx_lib.Response(fixture["http_status"], json=fixture["body"], headers=fixture.get("headers") or {})

    def http_client(self) -> Any:
        return httpx_lib.Client(transport=httpx_lib.MockTransport(self.handler))
