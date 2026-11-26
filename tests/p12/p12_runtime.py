"""Эталонный мини-runtime для сценарных тестов №12.

Это НЕ runtime Max. Модуль повторяет только протокол, который Max реализует у
себя: общий дедлайн, ограниченные ретраи по ``retryable`` и ``retry_after``,
учёт физических вызовов, честный статус complete|partial|failed. Тесты на нём
показывают, что данных ``ProviderError`` достаточно, чтобы runtime остановился
без бесконечного цикла и пометил недоступные этапы.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from bcc_review.providers.gemini import ErrorKind, ProviderError

# После этих категорий провайдер считается выключенным до конца прогона.
PROVIDER_DOWN = frozenset({ErrorKind.CONFIG, ErrorKind.AUTH, ErrorKind.MODEL_UNAVAILABLE,
                           ErrorKind.QUOTA_EXHAUSTED})
HARD_LOOP_GUARD = 50


@dataclass
class Stage:
    name: str
    messages: list[dict[str, Any]]
    schema: dict[str, Any]


@dataclass
class RunResult:
    status: str = "complete"
    physical_calls: int = 0
    stages: list[dict[str, Any]] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_stages(
    adapter: Any,
    stages: Sequence[Stage],
    *,
    model: str,
    deadline_s: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    max_retries: int = 3,
    base_backoff_s: float = 2.0,
) -> RunResult:
    result = RunResult()
    started = clock()
    down: ProviderError | None = None
    for stage in stages:
        if down is not None:
            result.stages.append({"stage": stage.name, "status": "unavailable", "kind": str(down.kind),
                                  "reason": "провайдер недоступен после предыдущего этапа"})
            continue
        retries = 0
        for _ in range(HARD_LOOP_GUARD):
            remaining = deadline_s - (clock() - started)
            if remaining <= 0:
                result.stages.append({"stage": stage.name, "status": "unavailable", "kind": "timeout",
                                      "reason": "общий дедлайн исчерпан"})
                break
            try:
                res = adapter.invoke(model=model, messages=stage.messages, schema=stage.schema, timeout_s=remaining)
            except ProviderError as err:
                result.physical_calls += err.physical_calls
                wait = err.retry_after if err.retry_after is not None else base_backoff_s * (2 ** retries)
                fits = (clock() - started) + wait < deadline_s
                if err.retryable and retries < max_retries and fits:
                    retries += 1
                    sleep(wait)
                    continue
                result.stages.append({"stage": stage.name, "status": "unavailable", "kind": str(err.kind),
                                      "retry_after": err.retry_after, "retries": retries, "message": err.message})
                if err.kind in PROVIDER_DOWN or err.kind in (ErrorKind.RATE_LIMITED, ErrorKind.OVERLOADED):
                    down = err
                break
            else:
                result.physical_calls += res["usage"]["physical_calls"]
                if res["model"] not in result.models:
                    result.models.append(res["model"])
                if res["meta"]["fallback_used"]:
                    result.warnings.append(f"{stage.name}: резервная модель {res['meta']['called_model']} "
                                           f"вместо {res['meta']['requested_model']}")
                result.stages.append({"stage": stage.name, "status": "done", "data": res["data"],
                                      "model": res["model"], "retries": retries})
                break
        else:  # pragma: no cover - защитный предел, тест упадёт, если он достигнут
            raise AssertionError(f"этап {stage.name}: превышен защитный предел итераций")
    done = sum(1 for s in result.stages if s["status"] == "done")
    result.status = "complete" if done == len(stages) else ("partial" if done else "failed")
    return result
