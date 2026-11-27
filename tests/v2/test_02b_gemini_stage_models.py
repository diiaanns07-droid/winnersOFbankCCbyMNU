"""№02-Б: модель по этапу для Gemini (``GEMINI_STAGE_MODELS``) — по умолчанию выключено, без сети."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.providers.gemini import GeminiProvider, settings  # noqa: E402
from test_02_gemini import MESSAGES, SCHEMA, Script, err  # noqa: E402

CHAIN = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


def provider(env, plan=None):
    script = Script(plan or {})
    p = GeminiProvider(api_key="k", model="gemini-3.6-flash", fallback_models=CHAIN, env=env,
                       adapter_factory=script.factory, sleep=lambda s: None)
    return p, script


def test_stage_models_parsed_and_off_by_default():
    assert settings({})["stage_models"] == {}
    assert settings({"GEMINI_STAGE_MODELS": " segment = models/gemini-3.5-flash-lite , bad, =x, clarify="})[
        "stage_models"] == {"segment": "gemini-3.5-flash-lite"}


def test_stage_model_goes_first_only_for_its_stage():
    p, s = provider({"GEMINI_STAGE_MODELS": "segment=gemini-3.5-flash-lite"})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, stage="segment")
    assert s.calls == ["gemini-3.5-flash-lite"] and r["meta"]["fallback_used"] is False
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, stage="lens_qa")
    assert s.calls[-1] == "gemini-3.6-flash"   # остальные этапы — основная модель


def test_stage_model_failure_falls_back_to_usual_chain():
    p, s = provider({"GEMINI_STAGE_MODELS": "segment=gemini-3.5-flash-lite"},
                    {"gemini-3.5-flash-lite": [err("not_found", 404)]})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, stage="segment")
    assert s.calls == ["gemini-3.5-flash-lite", "gemini-3.6-flash"]


def test_without_setting_segment_uses_primary():
    p, s = provider({})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, stage="segment")
    assert s.calls == ["gemini-3.6-flash"]
