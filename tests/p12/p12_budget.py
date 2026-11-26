"""Общий бюджет и честное число запросов: одна стадия через настоящий ``runtime.asker.Asker``.

Участвуют реальные ``Asker``, ``Budget``, ``Cache``, ``StageStats``, ``Tracer``, ``ContextBuilder`` из
``bcc/integration`` и ``GeminiAdapter`` №12 с настоящим SDK google-genai. Имитируется только HTTP-транспорт
(``MockTransport`` с фикстурами ``tests/p12/fixtures/gemini``) и часы (``FakeClock``): сеть не используется.

Таблица для передачи (обе версии Asker — как в HEAD и с предложенным diff для Max):

    python -m tests.p12.p12_budget
"""

from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

from bcc_review.contracts import AskError, BudgetExhausted
from bcc_review.providers.gemini import GeminiAdapter
from bcc_review.runtime.asker import Asker
from bcc_review.runtime.context import ContextBuilder
from bcc_review.runtime.core import Budget, Cache, StageStats, Tracer

from .p12_support import TEST_KEY, FakeClock, FakeGemini, synthetic_schema

PRIMARY, LITE = "gemini-2.5-flash", "gemini-2.5-flash-lite"
LATENCY_S = 1.5
STAGE = "individual"
DOC = {"id": "0" * 64, "title": "Синтетический документ №12", "format": "md", "warnings": [],
       "blocks": [{"id": "b0001", "kind": "paragraph", "section": [], "loc": {"line_start": 1, "line_end": 1},
                   "text": "Система должна быстро отправлять push клиенту."}]}
PAYLOAD = {"task": "Найди дефекты требования R-001.", "input": {"req_id": "R-001"}}


@dataclass
class StageRun:
    asker: str
    sent: dict[str, int]
    requests: list[dict[str, Any]]      # t (от начала этапа), model, status
    passport: dict[str, Any]            # те же поля, что engine кладёт в Report.run
    status: str                         # ok | budget_exhausted | ask_error:<kind>
    stop_reason: str | None
    stage_end_s: float
    sleeps: list[float]
    trace: list[dict[str, Any]] = field(default_factory=list)
    data: Any = None

    @property
    def sent_total(self) -> int:
        return sum(self.sent.values())


def gated_asker() -> type:
    from .p12_asker_patch import load_gated_module
    return load_gated_module().Asker


def run_stage(*, asker_cls: type = Asker, max_calls: int, primary: str | None = "err_503_overloaded",
              max_seconds: float = 600.0, cache_dir: str | None = None) -> StageRun:
    """Одна стадия: основная модель отвечает ``primary``, запасная — успехом. ``primary=None`` — пустой сценарий."""
    clock = FakeClock()
    fake = FakeGemini(clock)
    if primary is not None:
        fake.on(PRIMARY, (primary, LATENCY_S)).on(LITE, ("ok_one_finding_lite", LATENCY_S))
    adapter = GeminiAdapter(api_key=TEST_KEY, model=PRIMARY, fallback_models=[LITE], http_client=fake.http_client(),
                            clock=clock)
    budget = Budget(max_calls, max_seconds, clock=clock)
    stats = StageStats()
    trace_path = Path(tempfile.mkdtemp(prefix="p12-trace-")) / "trace.jsonl"
    asker = asker_cls(adapter=adapter, provider="gemini", model=PRIMARY, budget=budget, cache=Cache(cache_dir),
                      stats=stats, tracer=Tracer(trace_path, "p12"), context=ContextBuilder(DOC), sleep=clock.sleep)
    started = clock()
    data = None
    with mock.patch.object(random, "uniform", return_value=0.0):  # джиттер Asker: детерминированно
        try:
            data = asker(STAGE, PAYLOAD, synthetic_schema())
            status, stop = "ok", None
        except BudgetExhausted as exc:
            status, stop = "budget_exhausted", exc.message
        except AskError as exc:
            status, stop = f"ask_error:{exc.kind}", exc.message.split(" (")[0][:90]
    tot = stats.totals()
    passport = {  # engine.Engine._run_block: run.model / models_seen / calls / budget
        "model": tot["models"][-1] if tot["models"] else None, "models_seen": tot["models"],
        "calls": {"physical": tot["physical"], "cache_hits": tot["cache_hits"], "failed": tot["failed"],
                  "retries": tot["retries"]},
        "budget": budget.to_dict(), "budget_calls": budget.calls,
    }
    trace = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        rec.pop("ts", None)
        rec.pop("run_id", None)
        trace.append(rec)
    return StageRun(
        asker=asker_cls.__module__.rsplit(".", 1)[-1],
        sent={m: fake.calls_for(m) for m in (PRIMARY, LITE)},
        requests=[{"t": round(r["t"] - started, 3), "model": r["model"], "status": r.get("status")}
                  for r in fake.requests],
        passport=passport, status=status, stop_reason=stop, stage_end_s=round(clock() - started, 3),
        sleeps=list(clock.sleeps), trace=trace, data=data,
    )


CASES = [
    ("лимит 1, flash 503 → lite", dict(max_calls=1)),
    ("лимит 2, flash 503 → lite", dict(max_calls=2)),
    ("лимит 1, flash quota → lite", dict(max_calls=1, primary="err_429_rpd")),
    ("лимит 2, flash quota → lite", dict(max_calls=2, primary="err_429_rpd")),
    ("тёплый кэш после лимита 2", "warm"),
    ("лимит 2, flash 429 Retry-After 39 с, остаток 30 с", dict(max_calls=2, primary="err_429_rpm", max_seconds=30.0)),
]


def matrix() -> list[tuple[str, str, StageRun]]:
    rows = []
    for label, asker_cls in (("Asker HEAD", Asker), ("Asker + diff Max", gated_asker())):
        for case, kwargs in CASES:
            if kwargs == "warm":
                cache = tempfile.mkdtemp(prefix="p12-cache-")
                run_stage(asker_cls=asker_cls, max_calls=2, cache_dir=cache)
                result = run_stage(asker_cls=asker_cls, max_calls=2, primary=None, cache_dir=cache)
            else:
                result = run_stage(asker_cls=asker_cls, **kwargs)
            rows.append((label, case, result))
    return rows


def render(rows: list[tuple[str, str, StageRun]]) -> str:
    out = ["| Asker | Случай | Ушло запросов (flash / lite) | Отчёт: calls.physical · model · models_seen "
           "| Статус | Причина остановки |", "|---|---|---|---|---|---|"]
    for label, case, r in rows:
        p = r.passport
        seen = ", ".join(m.removeprefix("gemini-") for m in p["models_seen"]) or "—"
        model = (p["model"] or "—").removeprefix("gemini-")
        hits = f" · cache_hits {p['calls']['cache_hits']}" if p["calls"]["cache_hits"] else ""
        out.append(f"| {label} | {case} | {r.sent[PRIMARY]} / {r.sent[LITE]} | "
                   f"{p['calls']['physical']} · {model} · [{seen}]{hits} | {r.status} | {r.stop_reason or '—'} |")
    return "\n".join(out)


if __name__ == "__main__":
    print("Имитация: HTTP-транспорт SDK (MockTransport + фикстуры) и часы FakeClock; Asker/Budget/Cache — настоящие.")
    print(render(matrix()))
