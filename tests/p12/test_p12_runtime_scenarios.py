"""Сценарии прогона поверх эталонного мини-runtime (протокол Max, не его код)."""

from __future__ import annotations

from p12_runtime import HARD_LOOP_GUARD, Stage, run_stages
from p12_support import MESSAGES

PRIMARY, LITE = "gemini-2.5-flash", "gemini-2.5-flash-lite"
STAGE_NAMES = ["segment", "requirements", "set_check", "critic", "verdict"]


def stages(schema, names=STAGE_NAMES):
    return [Stage(name, MESSAGES, schema) for name in names]


def run(adapter, schema, clock, *, names=STAGE_NAMES, deadline_s=600.0):
    return run_stages(adapter, stages(schema, names), model=PRIMARY, deadline_s=deadline_s,
                      clock=clock, sleep=clock.sleep)


def test_503_then_success_is_one_retry(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "err_503_overloaded", "ok_one_finding")
    result = run(make_adapter(), schema, clock, names=["requirements"])
    assert result.status == "complete"
    assert result.stages[0]["status"] == "done" and result.stages[0]["retries"] == 1
    assert result.physical_calls == 2 == len(fake.requests)
    assert clock.sleeps == [2.0], "без retry_after runtime берёт свою паузу"


def test_429_until_deadline_stops_without_infinite_loop(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "err_429_rpm")  # залипает: каждый вызов отвечает 429 с RetryInfo 39s
    result = run(make_adapter(), schema, clock, names=["requirements", "set_check"], deadline_s=100.0)

    assert len(fake.requests) == 3 < HARD_LOOP_GUARD
    assert clock.sleeps == [39.0, 39.0], "runtime ждёт ровно retry_after от сервера"
    first, second = result.stages
    assert first["status"] == "unavailable" and first["kind"] == "rate_limit" and first["retry_after_s"] == 39.0
    assert second == {"stage": "set_check", "status": "unavailable", "kind": "rate_limit",
                      "reason": "провайдер недоступен после предыдущего этапа"}
    assert result.status == "failed" and result.physical_calls == 3


def test_provider_disconnect_after_two_stages_gives_partial(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "ok_one_finding", "ok_empty", "err_404_model")
    result = run(make_adapter(), schema, clock)

    assert result.status == "partial"
    assert [s["status"] for s in result.stages] == ["done", "done", "unavailable", "unavailable", "unavailable"]
    assert result.stages[0]["data"]["candidates"][0]["severity"] == "major"
    assert result.stages[1]["data"]["candidates"] == []
    assert {s["kind"] for s in result.stages[2:]} == {"not_found"}
    assert "GEMINI_MODEL" in result.stages[2]["message"]
    assert result.physical_calls == 3 == len(fake.requests), "после отказа модели вызовов больше нет"


def test_fallback_mid_run_is_visible_in_passport(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "ok_one_finding", "ok_empty", "err_429_rpd").on(LITE, "ok_one_finding_lite")
    result = run(make_adapter(fallback_models=[LITE]), schema, clock, names=STAGE_NAMES[:4])

    assert result.status == "complete"
    assert result.models == [PRIMARY, LITE]
    assert [s["model"] for s in result.stages] == [PRIMARY, PRIMARY, LITE, LITE]
    assert result.warnings == [f"set_check: резервная модель {LITE} вместо {PRIMARY}",
                               f"critic: резервная модель {LITE} вместо {PRIMARY}"]
    # после дневной квоты основная модель в этом прогоне больше не вызывается
    assert result.physical_calls == 5 == len(fake.requests)
    assert fake.calls_for(PRIMARY) == 3 and fake.calls_for(LITE) == 2


def test_truncated_stage_never_counts_as_complete(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "ok_one_finding", "max_tokens_truncated", "ok_empty")
    result = run(make_adapter(), schema, clock, names=STAGE_NAMES[:3])
    assert result.status == "partial"
    assert result.stages[1]["status"] == "unavailable" and result.stages[1]["kind"] == "truncated"
    assert result.stages[2]["status"] == "done", "усечение — ошибка этапа, а не всего провайдера"


def test_empty_response_is_reported_not_complete(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "ok_one_finding", "empty_no_candidates", "ok_empty")
    result = run(make_adapter(), schema, clock, names=STAGE_NAMES[:3])
    assert result.status == "partial"
    assert (result.stages[1]["kind"], result.stages[1]["subkind"]) == ("invalid_output", "empty_candidates")
    assert result.stages[1]["retries"] == 0, "invalid_output по контракту не временная: движок не повторяет"
    assert result.stages[2]["status"] == "done" and len(fake.requests) == 3


def test_invalid_key_stops_everything_with_clear_message(make_adapter, fake, schema, clock) -> None:
    fake.on(PRIMARY, "err_400_api_key_invalid")
    result = run(make_adapter(), schema, clock)
    assert result.status == "failed" and len(fake.requests) == 1
    assert {s["kind"] for s in result.stages} == {"auth"}
    assert "GEMINI_API_KEY" in result.stages[0]["message"]
