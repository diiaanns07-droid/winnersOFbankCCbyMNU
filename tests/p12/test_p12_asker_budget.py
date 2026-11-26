"""Совместная граница бюджета Asker × GeminiAdapter до сетевого вызова.

Настоящие runtime.asker.Asker / Budget / Cache / StageStats / Tracer из bcc/integration и GeminiAdapter
с настоящим SDK; имитируются только HTTP-транспорт (MockTransport + фикстуры) и часы.
«Asker + diff Max» — тот же asker.py из HEAD с заменами из p12_asker_patch.py (tests/p12/max_asker_call_gate.diff).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bcc_review.runtime.asker import Asker
from bcc_review.runtime.mock import MockAdapter

from .p12_asker_patch import (
    PatchDoesNotApply,
    already_applied,
    patched_source,
    unified_diff,
)
from .p12_budget import LITE, PRIMARY, gated_asker, render, run_stage

HEAD, GATED = "head", "gated"


@pytest.fixture(params=[HEAD, GATED])
def variant(request):
    """Поведение, которого ждём: если Max уже влил diff, HEAD ведёт себя как вариант с гейтом."""
    return GATED if request.param == GATED or already_applied() else HEAD


def asker_cls(variant: str) -> type:
    return Asker if variant == HEAD else gated_asker()


# --------------------------------------------------------------------------- лимит 1


@pytest.mark.parametrize("primary", ["err_503_overloaded", "err_429_rpd", "err_404_model", "err_500_internal"])
def test_limit_one_never_sends_a_second_request(variant, primary) -> None:
    r = run_stage(asker_cls=asker_cls(variant), max_calls=1, primary=primary)
    assert r.sent_total == 1 and r.sent == {PRIMARY: 1, LITE: 0}
    assert r.passport["calls"]["physical"] == 1 == r.passport["budget_calls"]
    assert r.status != "ok" and r.passport["model"] == PRIMARY


def test_limit_one_transient_stops_on_budget_before_network(variant) -> None:
    r = run_stage(asker_cls=asker_cls(variant), max_calls=1)
    assert r.status == "budget_exhausted" and r.stop_reason == "исчерпан лимит вызовов модели (1)"
    assert r.passport["budget"] == {"max_calls": 1, "max_seconds": 600.0, "max_tokens": None, "exhausted": True,
                                    "reason": "исчерпан лимит вызовов модели (1)"}
    assert [x["model"] for x in r.requests] == [PRIMARY]


# --------------------------------------------------------------------------- лимит 2


def test_limit_two_503_switches_and_counts_both_requests(variant) -> None:
    r = run_stage(asker_cls=asker_cls(variant), max_calls=2)
    assert r.status == "ok" and r.data["candidates"][0]["severity"] == "major"
    assert r.sent == {PRIMARY: 1, LITE: 1}
    assert r.passport["calls"] == {"physical": 2, "cache_hits": 0, "failed": 1, "retries": 1 if variant == HEAD else 0}
    assert r.passport["budget_calls"] == 2
    assert r.passport["model"] == LITE and r.passport["models_seen"] == [PRIMARY, LITE]
    if variant == HEAD:  # переключение — повтором движка после его паузы
        assert r.requests == [{"t": 0.0, "model": PRIMARY, "status": 503}, {"t": 3.5, "model": LITE, "status": 200}]
        assert r.sleeps == [2.0] and r.stage_end_s == 5.0
    else:  # переключение — внутри invoke, после разрешения гейта
        assert r.requests == [{"t": 0.0, "model": PRIMARY, "status": 503}, {"t": 1.5, "model": LITE, "status": 200}]
        assert r.sleeps == [] and r.stage_end_s == 3.0
        assert [e["event"] for e in r.trace] == ["fallback_call", "call_error", "call_ok"]


def test_limit_two_quota_needs_the_gate(variant) -> None:
    """quota не временная: Asker HEAD не повторяет, запасная модель достижима только через гейт."""
    r = run_stage(asker_cls=asker_cls(variant), max_calls=2, primary="err_429_rpd")
    if variant == HEAD:
        assert r.status == "ask_error:quota" and r.sent == {PRIMARY: 1, LITE: 0}
        assert r.passport["calls"]["physical"] == 1
    else:
        assert r.status == "ok" and r.sent == {PRIMARY: 1, LITE: 1}
        assert r.passport["calls"]["physical"] == 2 and r.passport["model"] == LITE


# --------------------------------------------------------------------------- кэш и время


def test_warm_cache_makes_no_request_and_keeps_actual_model(variant) -> None:
    cache = tempfile.mkdtemp(prefix="p12-cache-")
    cold = run_stage(asker_cls=asker_cls(variant), max_calls=2, cache_dir=cache)
    assert cold.status == "ok" and cold.passport["model"] == LITE
    warm = run_stage(asker_cls=asker_cls(variant), max_calls=2, primary=None, cache_dir=cache)
    assert warm.status == "ok" and warm.sent_total == 0 and warm.requests == []
    assert warm.passport["calls"] == {"physical": 0, "cache_hits": 1, "failed": 0, "retries": 0}
    assert warm.passport["model"] == LITE and warm.data == cold.data
    assert [e["event"] for e in warm.trace] == ["cache_hit"]
    aliases = (Path(cache) / "model_aliases.json").read_text(encoding="utf-8")
    assert f'"gemini:{PRIMARY}": "{LITE}"' in aliases, "ключ кэша помнит фактическую модель"


def test_retry_after_longer_than_remaining_time(variant) -> None:
    r = run_stage(asker_cls=asker_cls(variant), max_calls=2, primary="err_429_rpm", max_seconds=30.0)
    assert r.sleeps == [], "39 с паузы не помещаются в 30 с: никто не спит"
    if variant == HEAD:
        assert r.status == "budget_exhausted"
        assert r.stop_reason == "пауза Retry-After 39 с превышает остаток бюджета времени"
        assert r.sent == {PRIMARY: 1, LITE: 0} and r.passport["calls"]["physical"] == 1
    else:  # у запасной модели своя квота: ответ без ожидания, в пределах лимита вызовов
        assert r.status == "ok" and r.sent == {PRIMARY: 1, LITE: 1}
        assert r.passport["calls"]["physical"] == 2 and r.passport["model"] == LITE
        assert r.stage_end_s == 3.0 < 30.0


def test_retry_after_with_limit_one_still_one_request(variant) -> None:
    r = run_stage(asker_cls=asker_cls(variant), max_calls=1, primary="err_429_rpm", max_seconds=30.0)
    assert r.sent_total == 1 and r.status == "budget_exhausted" and r.sleeps == []


# --------------------------------------------------------------------------- сам diff для Max


def test_committed_diff_matches_patch_against_current_asker() -> None:
    if already_applied():
        pytest.skip("diff уже влит в runtime/asker.py")
    committed = (Path(__file__).parent / "max_asker_call_gate.diff").read_text(encoding="utf-8")
    assert committed == unified_diff(), (
        "diff устарел: python -m tests.p12.p12_asker_patch > tests/p12/max_asker_call_gate.diff")


def test_patch_fails_loudly_if_asker_changes() -> None:
    with pytest.raises(PatchDoesNotApply):
        patched_source("class Asker:\n    pass\n")


def test_anthropic_adapter_is_not_gated() -> None:
    pytest.importorskip("anthropic", reason="адаптер №11 требует необязательный пакет anthropic")
    from bcc_review.providers.anthropic import AnthropicAdapter
    assert not getattr(AnthropicAdapter, "supports_call_gate", False)


def test_gate_is_opt_in_for_other_adapters() -> None:
    assert not getattr(MockAdapter, "supports_call_gate", False)
    from bcc_review.runtime.context import ContextBuilder
    from bcc_review.runtime.core import Budget, Cache, StageStats, Tracer

    from .p12_budget import DOC, PAYLOAD, synthetic_schema
    stats = StageStats()
    asker = gated_asker()(adapter=MockAdapter(model="mock-1"), provider="mock", model="mock-1",
                          budget=Budget(1, 60), cache=Cache(None), stats=stats, tracer=Tracer(None, "p12"),
                          context=ContextBuilder(DOC))
    asker("individual", PAYLOAD, synthetic_schema())  # MockAdapter.invoke не принимает call_gate
    assert stats.totals()["physical"] == 1


def test_matrix_renders() -> None:
    text = render([("Asker HEAD", "лимит 1", run_stage(max_calls=1))])
    assert "| Asker HEAD | лимит 1 | 1 / 0 | 1 · 2.5-flash · [2.5-flash] | budget_exhausted |" in text
