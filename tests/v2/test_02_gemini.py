"""№02: Gemini — повторы 2/5/10 с, откат по цепочке моделей, 404, 429, квота, сеть (без сети)."""

from __future__ import annotations

import json

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.gemini import (DEFAULT_FALLBACKS, DEFAULT_MODEL, GeminiProvider, settings,
                                            thinking_for)

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "U", "cache": {"x": 1}}]


def ok(model, data=None):
    return {"data": data or {"answer": "да"}, "usage": {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5},
            "model": f"{model}-001", "request_id": "rid", "stop_reason": "STOP", "meta": {"called_model": model}}


def err(kind, status=None, retry_after=None, message=""):
    return ProviderError(kind, message or kind, status=status, retry_after_s=retry_after)


class Script:
    """Фейковые адаптеры v1: по каждой модели — очередь ответов (dict) или ошибок (ProviderError)."""

    def __init__(self, plan):
        self.plan = {m: list(v) for m, v in plan.items()}
        self.calls = []
        self.thinking = {}

    def factory(self, model, thinking, schema_mode="native"):
        script = self
        self.modes = getattr(self, "modes", [])
        self.modes.append((model, schema_mode))

        class Adapter:
            def invoke(self, *, model, messages, schema, timeout_s, max_output_tokens=None):
                script.calls.append(model)
                script.thinking.setdefault(model, []).append(dict(thinking))
                script.last_messages = messages
                script.last_max_tokens = max_output_tokens
                queue = script.plan.get(model) or [ok(model)]
                item = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(item, Exception):
                    raise item
                return item

        return Adapter()


# Политику повторов проверяем на прежней короткой цепочке (3.8 → 3.6 → 3.5-lite); цепочка по умолчанию — test_defaults
LEGACY_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]


def make(plan, **kw):
    kw.setdefault("fallback_models", LEGACY_CHAIN)
    script = Script(plan)
    sleeps = []
    p = GeminiProvider(api_key="k", env={}, adapter_factory=script.factory, sleep=sleeps.append, **kw)
    return p, script, sleeps


def test_defaults():
    cfg = settings({})
    assert cfg["model"] == DEFAULT_MODEL == "gemini-3.8-flash"
    # бесплатный тариф: 20 запросов в сутки на каждую Flash (замер F3 27.11) — сначала все Flash, потом Flash-Lite
    assert cfg["fallback_models"] == list(DEFAULT_FALLBACKS) == [
        "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert cfg["max_output_tokens"] is None                       # по профилю модели
    assert settings({"GEMINI_MAX_OUTPUT_TOKENS": "20000"})["max_output_tokens"] == 20000
    assert settings({"GEMINI_FALLBACK_MODELS": "off"})["fallback_models"] == []
    assert settings({"GEMINI_FALLBACK_MODELS": "a, models/b,a"})["fallback_models"] == ["a", "b"]
    assert settings({"GOOGLE_API_KEY": "g"})["api_key"] == "g"


def test_success_first_model_normalized():
    p, s, sleeps = make({})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"}
    assert r["model"] == "gemini-3.8-flash-001"           # фактическая версия модели — в паспорт
    assert r["stop_reason"] == "end_turn"
    assert {k: r["usage"][k] for k in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_input_tokens")} \
        == {"input_tokens": 100, "output_tokens": 25, "thinking_tokens": 5, "cache_read_input_tokens": 0}
    assert r["usage"]["thinking"] == "medium"                     # уровень рассуждения — в трассу
    assert r["meta"]["fallback_used"] is False and r["meta"]["requested_model"] == "gemini-3.8-flash"
    assert s.calls == ["gemini-3.8-flash"] and sleeps == []
    assert s.last_messages == [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    assert s.last_max_tokens == 65536                             # потолок Gemini 3: рассуждения в том же лимите


def test_503_three_retries_2_5_10_then_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("overloaded", 503)] * 4})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 4 + ["gemini-3.6-flash"]
    assert sleeps == [2.0, 5.0, 10.0]
    assert r["meta"]["fallback_used"] is True and r["meta"]["called_model"] == "gemini-3.6-flash"
    assert len(r["meta"]["attempts"]) == 4 and r["meta"]["physical_calls"] == 5


def test_503_recovers_on_retry():
    p, s, sleeps = make({"gemini-3.8-flash": [err("overloaded", 503), ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 2 and sleeps == [2.0]
    assert r["meta"]["fallback_used"] is False


@pytest.mark.parametrize("kind,status", [("server", 500), ("timeout", 504)])
def test_other_transient_kinds_retry(kind, status):
    p, s, sleeps = make({"gemini-3.8-flash": [err(kind, status)] * 4})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [2.0, 5.0, 10.0] and s.calls[-1] == "gemini-3.6-flash"


def test_404_goes_to_next_model_immediately_and_is_remembered():
    p, s, sleeps = make({"gemini-3.8-flash": [err("not_found", 404)]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash", "gemini-3.6-flash"] and sleeps == []
    assert r["model"] == "gemini-3.6-flash-001"
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls[-1] == "gemini-3.6-flash" and s.calls.count("gemini-3.8-flash") == 1  # 404 больше не вызывается


def test_quota_goes_to_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("quota", 429)], "gemini-3.6-flash": [err("quota", 429)]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"] and sleeps == []
    assert r["meta"]["called_model"] == "gemini-3.5-flash-lite"


def test_429_waits_retry_after_then_succeeds():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=12.0), ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [12.5] and s.calls == ["gemini-3.8-flash"] * 2
    assert r["meta"]["fallback_used"] is False


def test_429_long_retry_after_switches_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=3600.0)]})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [] and s.calls == ["gemini-3.8-flash", "gemini-3.6-flash"]


def test_429_twice_then_next_model():
    p, s, sleeps = make({"gemini-3.8-flash": [err("rate_limit", 429, retry_after=1.0)] * 3})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert sleeps == [1.5, 1.5] and s.calls == ["gemini-3.8-flash"] * 3 + ["gemini-3.6-flash"]


def test_network_retries_then_raises_without_switching():
    p, s, sleeps = make({"gemini-3.8-flash": [err("network")] * 5})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "network" and sleeps == [2.0, 5.0] and s.calls == ["gemini-3.8-flash"] * 3


@pytest.mark.parametrize("kind", ["auth", "not_configured", "refusal", "truncated", "invalid_output", "bad_request"])
def test_non_retryable_raise_immediately(kind):
    p, s, sleeps = make({"gemini-3.8-flash": [err(kind, 400)]})
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == kind and s.calls == ["gemini-3.8-flash"] and sleeps == []


def test_thinking_rejected_retries_without_thinking():
    p, s, sleeps = make({"gemini-3.8-flash": [err("bad_request", 400, message="Thinking level is not supported"),
                                              ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.thinking["gemini-3.8-flash"] == [{"thinking_level": "medium"}, {}]
    assert r["meta"]["thinking"] == {}


def test_all_models_exhausted_message_lists_chain():
    plan = {m: [err("overloaded", 503)] * 10 for m in ["gemini-3.8-flash", *DEFAULT_FALLBACKS]}
    p, s, sleeps = make(plan)
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "overloaded"
    assert "Все модели Gemini" in e.value.message and "gemini-3.5-flash-lite" in e.value.message
    assert len(s.calls) == 12 and sleeps == [2.0, 5.0, 10.0] * 3
    assert len(e.value.attempts) == 12 and e.value.physical_calls == 12


def test_explicit_model_goes_first():
    p, s, _ = make({})
    p.invoke(model="gemini-3.6-flash", messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.6-flash"]
    assert p.model_chain("gemini-3.6-flash") == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]


def test_deadline_stops_retries():
    now = [0.0]
    fallback = "gemini-3.6-flash"
    script = Script({model: [err("overloaded", 503)] for model in (DEFAULT_MODEL, fallback)})

    def sleep(s):
        now[0] += s

    p = GeminiProvider(api_key="k", env={"GEMINI_TOTAL_TIMEOUT_S": "10"}, fallback_models=[fallback],
                       adapter_factory=script.factory,
                       sleep=sleep, clock=lambda: now[0])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert e.value.kind == "overloaded"
    assert script.calls[:2] == [DEFAULT_MODEL, fallback]
    assert len(script.calls) <= 3


def test_missing_key_is_not_configured_at_creation():
    """Без ключа провайдер не создаётся (как Claude API): конвейер объясняет причину первой строкой."""
    with pytest.raises(ProviderError) as e:
        GeminiProvider(env={})
    assert e.value.kind == "not_configured" and "aistudio.google.com" in e.value.message


def test_pipeline_without_gemini_key_explains_first_and_does_not_fail_each_stage(tmp_path, monkeypatch, capsys):
    from bcc_review.v2 import __main__ as cli
    from pathlib import Path
    doc = Path(__file__).resolve().parents[2] / "release" / "input" / "requirements.md"
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    code = cli.main([str(doc), str(tmp_path / "r.md"), "--provider", "gemini", "--no-html"])
    out = capsys.readouterr()
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert code == 3
    assert report["run"]["warnings"][0].startswith("Не задан ключ Gemini"), report["run"]["warnings"][:2]
    assert "aistudio.google.com/apikey" in report["run"]["warnings"][0]
    text = out.out + out.err
    assert "СБОЙ" not in text                                     # этапы не «падают» по очереди
    assert report["findings"]                                     # отчёт построен правилами


def test_thinking_for():
    assert thinking_for("gemini-3.8-flash", None, None) == {"thinking_level": "medium"}
    assert thinking_for("gemini-2.5-flash", None, None) == {"thinking_budget": 4096}
    assert thinking_for("gemini-3.8-flash", "off", None) == {}
    assert thinking_for("gemini-3.8-flash", None, "2048") == {"thinking_budget": 2048}
    assert thinking_for("gemma-3", None, None) == {}


def test_schema_rejected_retries_same_model_with_schema_as_text():
    p, s, sleeps = make({"gemini-3.8-flash": [err("bad_request", 400, message="Gemini отклонил запрос (400): "
                                                  "The specified schema produces a constraint that has too many states"),
                                              ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.calls == ["gemini-3.8-flash"] * 2 and sleeps == []
    assert ("gemini-3.8-flash", "text") in s.modes
    assert r["meta"]["schema_mode"] == "text"
    assert s.last_messages[0] == {"role": "system", "content": "S"}       # общий префикс для кэша не тронут
    assert '"required": ["answer"]' in s.last_messages[-1]["content"]     # схема текстом — в конце user
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.modes.count(("gemini-3.8-flash", "text")) == 1               # режим запомнен, адаптер переиспользуется


def test_stage_limit_never_lowers_gemini_output_limit():
    p, s, _ = make({})
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, max_output_tokens=8000)
    assert s.last_max_tokens == 65536
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, max_output_tokens=60000)
    assert s.last_max_tokens == 65536
    p2, s2, _ = make({}, max_output_tokens=20000)                 # явный лимит (GEMINI_MAX_OUTPUT_TOKENS) главный…
    p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, max_output_tokens=8000)
    assert s2.last_max_tokens == 20000
    p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60, max_output_tokens=32000)
    assert s2.last_max_tokens == 32000                            # …но лимит этапа его не опускает


def test_old_model_gets_small_limit_and_rejected_limit_is_lowered():
    p, s, _ = make({"gemini-2.0-flash": [ok("gemini-2.0-flash")]})
    p.invoke(model="gemini-2.0-flash", messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.last_max_tokens == 8192
    p, s, sleeps = make({"gemini-3.8-flash": [err("bad_request", 400, message="max_output_tokens must be <= 32768"),
                                              ok("gemini-3.8-flash")]})
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["data"] == {"answer": "да"} and s.calls == ["gemini-3.8-flash"] * 2 and s.last_max_tokens == 32768
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert s.last_max_tokens == 32768 and len(s.calls) == 3       # потолок запомнен для модели


def test_slow_primary_timeout_leaves_time_for_a_working_fallback():
    """doctor --live: первый 504 от основной модели пришёл через 118 с при таймауте 120 с."""
    now = [0.0]
    calls = []
    fallback = "gemini-3.7-flash"

    class SlowPrimary:
        def invoke(self, *, model, timeout_s, **_):
            calls.append(model)
            if model == DEFAULT_MODEL:
                now[0] += min(118.4, timeout_s)
                raise err("timeout", 504)
            return ok(model)

    p = GeminiProvider(env={}, adapter_factory=lambda *_: SlowPrimary(), fallback_models=[fallback],
                       sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    result = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=120)
    assert calls == [DEFAULT_MODEL, fallback]
    assert result["meta"]["called_model"] == fallback
    assert result["meta"]["physical_calls"] == 2


def test_total_budget_is_call_timeout_plus_slack():
    """LLMClient ограничивает таймаут остатком лимита этапа — повторы провайдера не должны растянуть этап втрое."""
    now = [0.0]
    script = Script({"gemini-3.8-flash": [err("timeout", 504)] * 10, "gemini-3.6-flash": [err("timeout", 504)] * 10})

    class SlowAdapter:
        def __init__(self, inner):
            self.inner = inner

        def invoke(self, **kw):
            now[0] += kw["timeout_s"]          # каждый запрос висит до своего таймаута
            return self.inner.invoke(**kw)

    p = GeminiProvider(api_key="k", env={}, fallback_models=["gemini-3.6-flash"],
                       adapter_factory=lambda m, t, **k: SlowAdapter(script.factory(m, t)),
                       sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    with pytest.raises(ProviderError) as e:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=200)
    assert e.value.kind == "timeout"
    assert script.calls == [DEFAULT_MODEL, "gemini-3.6-flash"]
    assert now[0] <= 200 + 120 + 10


def test_overloaded_primary_cools_down_one_try_without_sleep_then_recovers():
    """После исчерпанных повторов 503 модель «остывает»: следующий вызов пробует её один раз без пауз."""
    # окно запросов в минуту выключено: здесь проверяется «охлаждение», а не темп (6 запросов к модели подряд)
    p, s, sleeps = make({"gemini-3.8-flash": [err("overloaded", 503)] * 5 + [ok("gemini-3.8-flash")]}, rpm=0)
    r1 = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r1["meta"]["called_model"] == "gemini-3.6-flash" and sleeps == [2.0, 5.0, 10.0]
    sleeps.clear()
    r2 = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r2["meta"]["called_model"] == "gemini-3.6-flash" and sleeps == []      # одна попытка, без пауз
    assert s.calls.count("gemini-3.8-flash") == 5
    r3 = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)      # основная ожила — снова она
    assert r3["meta"]["called_model"] == "gemini-3.8-flash" and sleeps == []
