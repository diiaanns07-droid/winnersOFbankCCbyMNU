"""Стык движка Max и адаптера №11: Asker → AnthropicAdapter → подставной HTTP-транспорт.

Сеть не используется. Транспорт — ``ScriptedTransport`` ниже (httpx2.BaseTransport,
синтетические ответы Messages API), часы заданы (``FakeClock``), пауза Asker —
``FakeClock.sleep``. Этап и схема — реальные из модуля individual
(``build_prompt``, ``response_schema``, ``STAGE#1``).

Проверяется то, что видит движок: класс ошибки (``bcc_review.contracts.ProviderError``),
её kind из словаря контракта, request_id, сообщение, Retry-After, число GET и POST,
паузы и выход в бюджет.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import httpx2
import pytest

from bcc_review import contracts as C
from bcc_review.analysis.individual import STAGE, build_prompt, response_schema
from bcc_review.runtime.asker import Asker
from bcc_review.runtime.context import ContextBuilder
from bcc_review.runtime.core import Budget, Cache, StageStats, Tracer
from bcc_review.runtime.modules import Modules

from conftest import observe

MODEL = "claude-opus-5-5"
KEY = "test-key-not-a-secret"

DOC = {"blocks": [
    {"id": "blk-001", "kind": "heading", "text": "Уведомления", "section": [], "loc": {"level": 2}},
    {"id": "blk-002", "kind": "paragraph", "section": ["Уведомления"],
     "text": "Ф-3. Система отправляет клиенту максимум один push за календарный месяц."},
]}
REQS = [{"id": "R-01", "text": DOC["blocks"][1]["text"], "block_ids": ["blk-002"], "kind": "functional",
         "source_id": "Ф-3"}]

CHECK = {
    "criterion": "unambiguous", "status": "issue", "reason": "Не указан часовой пояс календарного месяца.",
    "quote": "максимум один push за календарный месяц", "condition": "push в 23:30 по Алматы 31-го числа",
    "outcomes": ["засчитан в текущий месяц", "засчитан в следующий месяц"],
    "impact": "Разработка и тестирование выберут разные границы месяца.", "fix": "Указать часовой пояс.",
    "question": "По какому часовому поясу считается календарный месяц?", "severity": "major",
    "kind": "ambiguity", "blocks": "both", "blocked_decision": "граница месяца",
    "scenario": "push 31-го в 23:30", "root_cause": "нет часового пояса",
}
DATA = {"results": [{"req_id": "R-01", "checks": [CHECK]}]}


# --------------------------------------------------------------------------- инфраструктура теста
class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def http_error(status: int, etype: str, message: str, request_id: str, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, headers={"request-id": request_id, **headers},
                           json={"type": "error", "error": {"type": etype, "message": message},
                                 "request_id": request_id})


def message_ok(data: Any, *, request_id: str, model: str = MODEL, usage: dict | None = None) -> httpx2.Response:
    body = {"id": "msg_p11", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": usage or {"input_tokens": 1834, "output_tokens": 412,
                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
    return httpx2.Response(200, headers={"request-id": request_id}, json=body)


def model_info(model: str = MODEL) -> httpx2.Response:
    return httpx2.Response(200, headers={"request-id": "req_p11_models"},
                           json={"id": model, "type": "model", "display_name": model,
                                 "created_at": "2026-09-22T00:00:00Z", "max_input_tokens": 1000000,
                                 "max_tokens": 128000})


class ScriptedTransport(httpx2.BaseTransport):
    """Синтетические HTTP-ответы по очереди: отдельно для GET /v1/models/{id} и POST /v1/messages."""

    def __init__(self, clock: FakeClock, *, posts: list[httpx2.Response] = (),
                 gets: list[httpx2.Response] | None = None) -> None:
        self.clock = clock
        self.posts = deque(posts)
        self.gets = deque(gets if gets is not None else [model_info()])
        self.requests: list[tuple[str, str, float]] = []

    def count(self, method: str) -> int:
        return sum(1 for m, _, _ in self.requests if m == method)

    def times(self, method: str) -> list[float]:
        return [t for m, _, t in self.requests if m == method]

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append((request.method, request.url.path, self.clock()))
        if request.method == "GET" and request.url.path.startswith("/v1/models/"):
            queue = self.gets
        elif request.method == "POST" and request.url.path == "/v1/messages":
            queue = self.posts
        else:
            raise AssertionError(f"неожиданный запрос {request.method} {request.url.path}")
        if not queue:
            raise AssertionError(f"лишний запрос {request.method} {request.url.path}")
        return queue.popleft()


class RecordingTracer(Tracer):
    def __init__(self) -> None:
        super().__init__(None, "p11-asker-path")
        self.events: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> None:
        self.events.append({"event": event, **fields})

    def of(self, event: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == event]


def team_adapter_class():
    """Тот же класс, который движок берёт из слота ``anthropic`` (не резерв)."""
    res = Modules().get("anthropic")
    assert res.origin == "team", res.error
    assert res.path == "bcc_review.providers.anthropic:AnthropicAdapter"
    return res.func


def build(transport: ScriptedTransport, clock: FakeClock, *, max_retries: int, max_calls: int = 40,
          max_seconds: float = 600.0):
    adapter = team_adapter_class()(transport=transport, env={"ANTHROPIC_API_KEY": KEY}, clock=clock)
    budget = Budget(max_calls, max_seconds, clock=clock)
    stats, tracer = StageStats(), RecordingTracer()
    asker = Asker(adapter=adapter, provider="anthropic", model=MODEL, budget=budget, cache=Cache(None, enabled=False),
                  stats=stats, tracer=tracer, context=ContextBuilder(DOC, REQS), max_retries=max_retries,
                  timeout_s=60.0, sleep=clock.sleep)
    return adapter, asker, budget, stats, tracer


STAGE_1 = f"{STAGE}#1"


def ask(asker: Asker) -> dict:
    return asker(STAGE_1, build_prompt(DOC, REQS), response_schema())


# --------------------------------------------------------------------------- сценарии
def test_429_retry_after_then_200_with_one_retry_budget():
    clock = FakeClock()
    transport = ScriptedTransport(clock, posts=[
        http_error(429, "rate_limit_error", "per-minute rate limit", "req_p11_429", **{"retry-after": "7"}),
        message_ok(DATA, request_id="req_p11_ok"),
    ])
    adapter, asker, budget, stats, tracer = build(transport, clock, max_retries=1, max_calls=2)

    assert ask(asker) == DATA

    assert transport.count("GET") == 1 and transport.count("POST") == 2
    assert clock.sleeps == [7.0]  # ровно Retry-After, без джиттера и без экспоненты
    t1, t2 = transport.times("POST")
    assert t2 - t1 == 7.0
    assert budget.calls == 2 and adapter.physical_calls == 2
    (err,) = tracer.of("call_error")  # ветка ``except ProviderError`` в Asker
    assert err["kind"] == "rate_limit" and err["retry_after_s"] == 7.0
    assert tracer.of("retry")[0]["delay_s"] == 7.0
    assert adapter.journal[-2]["request_id"] == "req_p11_429"
    rec = stats.get(STAGE_1)
    assert (rec.calls, rec.retries, rec.failed_calls) == (2, 1, 1)
    observe("429 Retry-After: 7 → 200, max_retries=1, max_calls=2", transport, clock, "— (успех со 2-й попытки)")


@pytest.mark.parametrize("on", ["POST", "GET"])
def test_401_is_final(on):
    clock = FakeClock()
    unauthorized = http_error(401, "authentication_error", "invalid x-api-key", "req_p11_401")
    if on == "POST":
        transport = ScriptedTransport(clock, posts=[unauthorized])
    else:  # живой неверный ключ получит 401 уже на проверке модели
        transport = ScriptedTransport(clock, gets=[unauthorized])
    adapter, asker, budget, stats, tracer = build(transport, clock, max_retries=3)

    with pytest.raises(C.AskError) as info:
        ask(asker)

    assert not isinstance(info.value, C.BudgetExhausted)
    assert info.value.kind == "auth" and info.value.stage == STAGE_1
    cause = info.value.__cause__
    assert type(cause) is C.ProviderError  # общий класс контракта, а не копия адаптера
    assert cause.kind == "auth" and not cause.transient
    assert cause.status == 401 and cause.request_id == "req_p11_401" and cause.retry_after_s is None
    assert "ANTHROPIC_API_KEY" in cause.message and "invalid x-api-key" in cause.message
    assert info.value.message == cause.message
    assert [e["kind"] for e in tracer.of("call_error")] == ["auth"] and not tracer.of("retry")
    assert transport.count("GET") == 1 and transport.count("POST") == (1 if on == "POST" else 0)
    assert clock.sleeps == [] and budget.calls == 1
    observe(f"401 на {on}, max_retries=3", transport, clock, f"AskError(auth) ← {type(cause).__module__}.ProviderError")


def test_missing_key_zero_requests(monkeypatch, tmp_path):
    clock = FakeClock()
    transport = ScriptedTransport(clock)
    with pytest.raises(C.ProviderError) as info:
        team_adapter_class()(transport=transport, mode="live", env={})
    assert type(info.value) is C.ProviderError and info.value.kind == "not_configured"
    assert "ANTHROPIC_API_KEY" in info.value.message
    assert transport.requests == []

    # Путь движка: setup_provider создаёт адаптер без аргументов, как в боевом прогоне.
    from bcc_review.engine import Engine

    sent: list[str] = []

    def no_network(self, request):
        sent.append(f"{request.method} {request.url}")
        raise AssertionError("сетевой запрос без ключа")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", no_network)
    src = tmp_path / "tz.md"
    src.write_text("# ТЗ\n\nФ-3. Один push в месяц.\n", encoding="utf-8")
    engine = Engine(src, tmp_path / "out.md", C.RunOptions(provider="anthropic", trace=False,
                                                           artifacts_dir=str(tmp_path / "art")))
    engine.setup_provider()
    assert engine.adapter is None
    assert engine.unavailable.startswith("anthropic: not_configured: ")  # ветка ``except ProviderError``
    assert sent == []
    observe("ключ не задан (Engine.setup_provider)", transport, clock, "ProviderError(not_configured) → unavailable")


def test_valid_response_reaches_asker_with_actual_model_and_usage():
    clock = FakeClock()
    usage = {"input_tokens": 5210, "output_tokens": 600, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 4096,
             "iterations": [{"type": "message", "input_tokens": 5210, "output_tokens": 3},
                            {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 5210,
                             "output_tokens": 597}]}
    transport = ScriptedTransport(clock, posts=[
        message_ok(DATA, request_id="req_p11_ok", model="claude-opus-4-8", usage=usage)])
    adapter, asker, budget, stats, tracer = build(transport, clock, max_retries=0)

    assert ask(asker) == DATA

    assert transport.count("GET") == 1 and transport.count("POST") == 1
    rec = stats.get(STAGE_1)
    assert rec.models == ["claude-opus-4-8"]  # фактическая, а не запрошенная claude-opus-5-5
    assert (rec.input_tokens, rec.output_tokens, rec.cache_read_tokens) == (5210, 600, 4096)
    assert budget.tokens == 5810
    (ok,) = tracer.of("call_ok")
    assert ok["model"] == "claude-opus-4-8" and ok["request_id"] == "req_p11_ok"
    passport = adapter.passport()
    assert passport["transport"] == "custom-transport" and passport["fallback_used"] == 1
    assert passport["physical_calls"] == {"messages": 1, "models": 1, "other": 0}
    observe("валидный 200 (server-side fallback → claude-opus-4-8)", transport, clock, "— (данные по схеме)")


@pytest.mark.parametrize(("label", "retry_after", "max_calls", "max_seconds", "sleeps"), [
    ("max_calls=1", "7", 1, 600.0, [7.0]),
    ("Retry-After 120 > остатка 60 с", "120", 40, 60.0, []),
])
def test_exhausted_budget_blocks_retry(label, retry_after, max_calls, max_seconds, sleeps):
    clock = FakeClock()
    transport = ScriptedTransport(clock, posts=[
        http_error(429, "rate_limit_error", "per-minute rate limit", "req_p11_429", **{"retry-after": retry_after})])
    adapter, asker, budget, stats, tracer = build(transport, clock, max_retries=3, max_calls=max_calls,
                                                  max_seconds=max_seconds)

    with pytest.raises(C.BudgetExhausted) as info:
        ask(asker)

    assert [e["kind"] for e in tracer.of("call_error")] == ["rate_limit"]  # ветка ``except ProviderError``
    if info.value.__cause__ is not None:  # пауза больше остатка: исходная ошибка сохранена
        assert type(info.value.__cause__) is C.ProviderError
        assert info.value.__cause__.retry_after_s == float(retry_after)
        assert info.value.__cause__.request_id == "req_p11_429"
    assert transport.count("POST") == 1 and adapter.physical_calls == 1
    assert clock.sleeps == sleeps
    observe(f"429 Retry-After: {retry_after}, бюджет исчерпан ({label})", transport, clock, "BudgetExhausted")


def test_adapter_kinds_are_contract_kinds():
    from bcc_review.providers import anthropic as adapter_mod

    assert adapter_mod.ProviderError is C.ProviderError
    assert set(adapter_mod.ERROR_KINDS) <= set(C.PROVIDER_ERROR_KINDS)
    transient = {k for k, (retry, _) in adapter_mod.ERROR_KINDS.items() if retry}
    # единственное расхождение — invalid_output: адаптер считает повтор осмысленным, движок не повторяет
    assert transient - set(C.TRANSIENT_KINDS) == {"invalid_output"}
    assert set(C.TRANSIENT_KINDS) <= transient
