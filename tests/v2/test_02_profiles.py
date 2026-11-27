"""№02: профили моделей, окно запросов Gemini по модели, рассуждение по этапам, разбор трассы (без сети)."""

from __future__ import annotations

import json

import pytest

from bcc_review.v2.providers import profiles, timing
from bcc_review.v2.providers.claude_cli import ClaudeCLIProvider
from bcc_review.v2.providers.gemini import GeminiProvider, thinking_for

SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]


@pytest.mark.parametrize("model,fam", [
    ("gemini-3.8-flash", "gemini-flash"), ("models/gemini-3.5-flash-lite", "gemini-flash-lite"),
    ("gemini-2.5-pro", "gemini-pro"), ("haiku", "haiku"), ("claude-haiku-5-5", "haiku"),
    ("sonnet", "sonnet"), ("claude-opus-5-5", "opus"), ("claude-x", "claude"), ("llama3", "other"), (None, "other")])
def test_family(model, fam):
    assert profiles.family(model) == fam
    assert profiles.for_model(model)["family"] == fam


def test_every_profile_has_output_limit_and_gemini_rate():
    for name, prof in profiles.PROFILES.items():
        assert int(prof["max_output_tokens"]) >= 16000, name
        if name.startswith("gemini"):
            assert prof["rpm"] > 0 and prof["concurrency"] >= 1, name
    assert profiles.for_model("gemini-3.8-flash")["concurrency"] == 5   # 4 линзы + набор разом


def test_gemini_thinking_by_generation_and_explicit_env_wins():
    assert thinking_for("gemini-3.8-flash", None, None) == {"thinking_level": "medium"}
    assert thinking_for("gemini-3.8-flash", None, None, "judge") == {"thinking_level": "medium"}
    assert thinking_for("gemini-3.8-flash", None, None, "segment") == {"thinking_level": "low"}
    assert thinking_for("gemini-3.8-flash", None, None, "clarify") == {"thinking_level": "low"}
    assert thinking_for("gemini-2.5-flash", None, None) == {"thinking_budget": 4096}
    assert thinking_for("gemini-2.5-flash", None, None, "segment") == {"thinking_budget": 1024}
    assert thinking_for("gemini-1.5-flash", None, None) == {}
    assert thinking_for("gemini-3.8-flash", "high", None, "segment") == {"thinking_level": "high"}   # env важнее
    assert thinking_for("gemini-3.8-flash", None, "2048") == {"thinking_budget": 2048}
    assert thinking_for("gemini-3.8-flash", "off", None) == {}


def test_stage_effort_applies_per_stage(monkeypatch):
    monkeypatch.setitem(profiles.STAGE_EFFORT, "gemini-flash", {"segment": "low"})
    monkeypatch.setitem(profiles.STAGE_EFFORT, "sonnet", {"clarify": "low"})
    assert thinking_for("gemini-3.8-flash", None, None, "segment") == {"thinking_level": "low"}
    assert thinking_for("gemini-3.8-flash", None, None, "judge") == {"thinking_level": "medium"}
    assert profiles.claude_effort("sonnet", "clarify") == "low"
    assert profiles.claude_effort("sonnet", "judge") is None
    p = ClaudeCLIProvider(model="sonnet", env={}, binary="claude")
    cmd = p.build_command("sonnet", SCHEMA, None, "clarify")
    assert cmd[cmd.index("--effort") + 1] == "low"
    assert "--effort" not in p.build_command("sonnet", SCHEMA, None, "judge")
    explicit = ClaudeCLIProvider(model="sonnet", effort="high", env={}, binary="claude")   # явное важнее профиля
    cmd = explicit.build_command("sonnet", SCHEMA, None, "clarify")
    assert cmd[cmd.index("--effort") + 1] == "high"


def test_haiku_profile_effort_low_without_pipeline():
    p = ClaudeCLIProvider(model="haiku", env={}, binary="claude")
    cmd = p.build_command("haiku", SCHEMA, None, "lens_qa")
    assert cmd[cmd.index("--effort") + 1] == "low"


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 1))
        self.t += s


def provider(clock, **kw):
    class Adapter:
        def invoke(self, **_):
            return {"data": {"answer": "да"}, "usage": {}, "model": "m", "stop_reason": "STOP", "meta": {}}

    return GeminiProvider(api_key="k", env=kw.pop("env", {}), sleep=clock.sleep, clock=clock.now,
                          adapter_factory=lambda model, thinking, schema_mode="native": Adapter(), **kw)


def test_rpm_window_is_sliding_and_per_model():
    clock = Clock()
    p = provider(clock, rpm=3)
    for _ in range(3):
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=300)
    assert clock.sleeps == []                          # три запроса подряд — без пауз (окно, а не шаг)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=300)
    assert clock.sleeps == [60.5]                      # четвёртый ждёт, пока первый выйдет из окна
    assert r["usage"]["rpm_wait_s"] == 60.5 and "ждал окно" in r["usage"]["attempts"][0]
    clock.sleeps.clear()
    p.invoke(model="gemini-3.6-flash", messages=MESSAGES, schema=SCHEMA, timeout_s=300)
    assert clock.sleeps == []                          # у другой модели своя квота


def test_rpm_from_profile_and_env_and_off():
    clock = Clock()
    assert provider(clock).rpm_for("gemini-3.8-flash") == 10
    assert provider(clock).rpm_for("gemini-3.5-flash-lite") == 15
    assert provider(clock, env={"GEMINI_RPM": "4"}).rpm_for("gemini-3.8-flash") == 4
    off = provider(clock, env={"GEMINI_RPM": "0"})
    for _ in range(30):
        off.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=300)
    assert clock.sleeps == []


def test_rpm_wait_never_exceeds_call_budget():
    clock = Clock()
    p = provider(clock, rpm=1)
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=300)
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=10)   # бюджет 10+120 с — дождаться можно
    assert clock.sleeps == [60.5]
    p2 = provider(Clock(), rpm=1, env={"GEMINI_TOTAL_TIMEOUT_S": "30"})
    p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    p2.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=30)  # не успеть — отправляем, 429 решит Retry-After


def test_concurrency_default_and_env():
    assert provider(Clock()).concurrency == 5
    assert provider(Clock(), env={"GEMINI_CONCURRENCY": "2"}).concurrency == 2
    assert provider(Clock(), model="gemini-2.5-pro").concurrency == 2
    assert GeminiProvider.paces_requests is True


def test_timing_summary_and_render(tmp_path):
    run = tmp_path / "runs" / "20261127-120000-abcd"
    run.mkdir(parents=True)
    rows = [
        {"stage": "segment", "model": "m", "seconds": 30, "usage": {"input_tokens": 9000, "output_tokens": 4000,
                                                                      "thinking_tokens": 1000}},
        {"stage": "lens_qa", "model": "m", "seconds": 40, "usage": {"output_tokens": 5000, "num_turns": 3}},
        {"stage": "consistency", "model": "m", "seconds": 60, "usage": {"output_tokens": 9000,
                                                                          "attempts": ["m 503 overloaded"]}},
        {"stage": "consistency", "event": "split", "items": 40},
        {"stage": "judge", "model": "m", "seconds": 80, "usage": {}},
        {"stage": "judge", "model": "m", "seconds": 10, "usage": {}},
        {"stage": "clarify", "model": "m", "error": "timeout", "message": "не ответил", "seconds": 5},
        {"stage": "clarify", "cached": True, "model": "m"},
    ]
    (run / "trace.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    s = timing.summary(timing.load(run))
    assert s["critical_path_s"] == 30 + 60 + 90 + 5
    assert s["stages"]["judge"]["calls"] == 2 and s["errors"] == 1
    text = timing.render(run, s)
    assert "ходов CLI 3" in text and "попытки: m 503 overloaded" in text and "ОШИБКА timeout" in text
    assert "consistency split" in text
    assert timing.main([str(run)]) == 0
    assert timing.latest_run(tmp_path / "runs") == run


def test_measured_stage_profile_sonnet_and_gemini():
    """Принятые замером отступления: нарезка и вопросы — low; линзы, набор, судья — по умолчанию."""
    for fam in ("sonnet", "gemini-flash"):
        assert profiles.STAGE_EFFORT[fam] == {"segment": "low", "clarify": "low"}, fam
    p = ClaudeCLIProvider(model="sonnet", env={}, binary="claude")
    for stage, effort in (("segment", "low"), ("clarify", "low"), ("judge", None), ("consistency", None),
                          ("lens_qa", None)):
        cmd = p.build_command("sonnet", SCHEMA, None, stage)
        assert (cmd[cmd.index("--effort") + 1] if "--effort" in cmd else None) == effort, stage
    assert "opus" not in profiles.STAGE_EFFORT        # opus — контрольные прогоны, без непроверенных отступлений
