"""Сквозной прогон движка (bcc_review.run_review) с провайдером gemini: число запросов в Report.run.

Движок, Asker и модули из bcc/integration настоящие, слот провайдера отдаёт GeminiAdapter №12
(«team:bcc_review.providers.gemini:GeminiAdapter»). Имитируется только HTTP-транспорт SDK: основная модель
отвечает 503, запасная — объектом, построенным по присланной схеме (runtime.mock.synth).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bcc_review.engine as engine
import bcc_review.providers.gemini as gemini
from bcc_review import run_review
from bcc_review.runtime.mock import synth

from .p12_support import ROOT, TEST_KEY, FakeClock, FakeGemini, httpx_lib

PRIMARY, LITE = "gemini-2.5-flash", "gemini-2.5-flash-lite"
EXAMPLE = ROOT / "contracts" / "examples" / "two_linked_requirements.md"


def schema_answer(request):
    schema = json.loads(request.content)["generationConfig"]["responseJsonSchema"]
    body = {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(synth(schema))}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10, "totalTokenCount": 110},
            "modelVersion": LITE, "responseId": "p12-e2e"}
    return httpx_lib.Response(200, json=body)


@pytest.mark.parametrize("max_calls", [1, 2])
def test_engine_passport_matches_transport(monkeypatch, tmp_path: Path, max_calls: int) -> None:
    clock = FakeClock()
    fake = FakeGemini(clock).on(PRIMARY, "err_503_overloaded").on(LITE, schema_answer)
    real = gemini.GeminiAdapter
    # движок создаёт адаптер как GeminiAdapter() — подставляем ту же фабрику с имитацией транспорта
    monkeypatch.setattr(gemini, "GeminiAdapter",
                        lambda: real(api_key=TEST_KEY, fallback_models=[LITE], http_client=fake.http_client(),
                                     clock=clock))
    monkeypatch.setattr(engine, "SLEEP", lambda seconds: None)
    report = run_review(EXAMPLE, tmp_path / "report.md",
                        options={"provider": "gemini", "max_calls": max_calls, "use_cache": False})
    run = report["run"]
    sent = {m: fake.calls_for(m) for m in (PRIMARY, LITE)}

    assert run["modules"]["provider"] == "team:bcc_review.providers.gemini:GeminiAdapter"
    assert sum(sent.values()) == run["calls"]["physical"] == max_calls, (sent, run["calls"])
    assert run["budget"]["exhausted"] is True
    assert run["budget"]["reason"] == f"исчерпан лимит вызовов модели ({max_calls})"
    if max_calls == 1:
        assert sent == {PRIMARY: 1, LITE: 0} and run["model"] == PRIMARY
    else:
        assert sent == {PRIMARY: 1, LITE: 1}
        assert run["model"] == LITE and run["models_seen"] == [PRIMARY, LITE]
        assert run["calls"]["failed"] == 1
        assert any(s["name"] == "inventory" and s["status"] == "ok" for s in run["stages"])
    assert run["status"] != "complete"
