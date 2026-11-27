"""№02: модель времени прогона на бесплатном Gemini — настоящие ``LLMClient`` и ``GeminiProvider``, ускоренные часы.

Ключа Gemini в облаке нет, поэтому решения о параллельности, темпе запросов и повторах проверяются здесь:
граф вызовов как у ``pipeline`` (нарезка → 4 линзы и набор параллельно → судья → проверка судьи → вопросы),
«сервер» ведёт окно запросов в минуту по каждой модели (429 с Retry-After) и отвечает за время этапа из
замера (секунды на вызов). Часы ускорены в ``SCALE`` раз: минута прогона — доли секунды теста, потоки идут
по-настоящему параллельно, паузы ``LLMClient`` (темп ``--rpm``) и провайдера (семафор, Retry-After) — настоящие.

Время этапов по умолчанию — замер haiku на официальном документе (класс скорости Gemini Flash, 27.11 09:00).
Запуск таблицы сравнения: ``python tests/v2/test_02_wallclock.py``.
"""

from __future__ import annotations

import concurrent.futures as cf
import sys
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:  # запуск файлом, без conftest
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.contracts import ProviderError  # noqa: E402
from bcc_review.v2.llm import LLMClient  # noqa: E402
from bcc_review.v2.providers import gemini as gem  # noqa: E402

SCALE = 250.0
# порядок запуска как в pipeline._parallel_reviewers (№01, a055425): самый долгий — первым
PARALLEL = ("consistency", "lens_architect", "lens_analyst", "lens_risk", "lens_qa")
# секунды на вызов: haiku (effort=low), официальный документ, прогон 27.11 08:58 (runs/20261127-085847-77dc)
HAIKU_S = {"segment": 59.2, "lens_analyst": 35.8, "lens_architect": 63.3, "lens_qa": 82.2, "lens_risk": 87.3,
           "consistency": 135.5, "judge": 119.9, "judge_check": 17.0, "clarify": 38.4}
SCHEMA = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


class ScaledClock:
    def __init__(self, scale: float = SCALE):
        self.scale, self.t0 = scale, time.monotonic()

    def now(self) -> float:
        return (time.monotonic() - self.t0) * self.scale

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds / self.scale)


class FreeTierServer:
    """Окно запросов в минуту по каждой модели; 429 несёт Retry-After, как настоящий ответ Google."""

    def __init__(self, clock: ScaledClock, *, rpm: int = 10, latency: dict | None = None, factor: float = 1.0,
                 fail_503: int = 0):
        self.clock, self.rpm, self.latency, self.factor = clock, rpm, dict(latency or HAIKU_S), factor
        self.fail_503 = fail_503
        self.lock = threading.Lock()
        self.window: dict[str, deque] = {}
        self.log: list[tuple[float, str, str, str]] = []   # (время, модель, этап, исход)
        self.in_flight = 0
        self.max_in_flight = 0

    def call(self, model: str, stage: str) -> dict:
        with self.lock:
            now = self.clock.now()
            win = self.window.setdefault(model, deque())
            while win and now - win[0] >= 60:
                win.popleft()
            if len(win) >= self.rpm:
                retry = max(1.0, 60 - (now - win[0]) + 1)
                self.log.append((now, model, stage, "429"))
                raise ProviderError("rate_limit", "429 RESOURCE_EXHAUSTED per minute", retry_after_s=retry, status=429)
            if self.fail_503 > 0:
                self.fail_503 -= 1
                self.log.append((now, model, stage, "503"))
                raise ProviderError("overloaded", "503 UNAVAILABLE", status=503)
            win.append(now)
            self.log.append((now, model, stage, "200"))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self.clock.sleep(self.latency.get(stage, 30.0) * self.factor)
        finally:
            with self.lock:
                self.in_flight -= 1
        return {"data": {"ok": True}, "usage": {"input_tokens": 20000, "output_tokens": 8000}, "model": model,
                "request_id": "sim", "stop_reason": "STOP", "meta": {}}

    def outcomes(self) -> list[str]:
        return [o for *_, o in self.log]


_tls = threading.local()


class SimProvider(gem.GeminiProvider):
    def invoke(self, *, stage: str = "", **kw):
        _tls.stage = stage
        return super().invoke(stage=stage, **kw)


def make_provider(server: FreeTierServer, clock: ScaledClock, **kw) -> SimProvider:
    class Adapter:
        def __init__(self, model):
            self.model = model

        def invoke(self, *, model, messages, schema, timeout_s, max_output_tokens=None, **_):
            return server.call(model, getattr(_tls, "stage", ""))

    return SimProvider(api_key="sim", env=kw.pop("env", {}), sleep=clock.sleep, clock=clock.now,
                       adapter_factory=lambda model, thinking, schema_mode="native": Adapter(model), **kw)


def run_graph(*, concurrency: int | None = None, client_rpm: float = 10.0, server_rpm: int = 10,
              factor: float = 1.0, latency: dict | None = None, fail_503: int = 0, env: dict | None = None,
              scale: float = SCALE) -> dict:
    """Один прогон графа вызовов. Возвращает модельное время, исходы запросов и максимум одновременных."""
    clock = ScaledClock(scale)
    server = FreeTierServer(clock, rpm=server_rpm, latency=latency, factor=factor, fail_503=fail_503)
    kw = {"env": env or {}}
    if concurrency is not None:
        kw["concurrency"] = concurrency
    provider = make_provider(server, clock, **kw)
    llm = LLMClient(provider, provider_name="gemini", max_calls=16, max_seconds=1500, timeout_s=600,
                    stage_timeout_s=480, rpm=client_rpm, sleep=clock.sleep, clock=clock.now)

    def ask(stage: str) -> None:
        llm.ask(stage, "S", f"U {stage}", SCHEMA)

    ask("segment")
    with cf.ThreadPoolExecutor(max_workers=len(PARALLEL)) as ex:
        list(ex.map(ask, PARALLEL))
    for stage in ("judge", "judge_check", "clarify"):
        ask(stage)
    return {"seconds": clock.now(), "outcomes": server.outcomes(), "max_in_flight": server.max_in_flight,
            "calls": llm.stats["calls"], "log": server.log}


# --------------------------------------------------------------------------- тесты


CRITICAL_S = HAIKU_S["segment"] + max(HAIKU_S[s] for s in PARALLEL) + sum(
    HAIKU_S[s] for s in ("judge", "judge_check", "clarify"))   # 370 с: нарезка + набор + судья + проверка + вопросы


def test_provider_window_runs_all_parallel_stages_at_once_without_429():
    """Провайдер сам держит окно запросов в минуту: без шага --rpm поверх прогон = критический путь, 9 запросов, 0 429."""
    r = run_graph(client_rpm=0)
    assert r["outcomes"] == ["200"] * 9, r["outcomes"]
    assert r["max_in_flight"] == len(PARALLEL)
    assert r["seconds"] <= CRITICAL_S + 15, (r["seconds"], CRITICAL_S)


def test_pipeline_rpm_window_and_provider_window_together_add_nothing():
    """Как у жюри: окно --rpm 10 у LLMClient (№01) и окно по модели у провайдера — без пауз и без 429."""
    r = run_graph(client_rpm=10)
    assert r["outcomes"] == ["200"] * 9, r["outcomes"]
    assert r["seconds"] <= CRITICAL_S + 15, (r["seconds"], CRITICAL_S)


def test_concurrency_four_was_slower():
    """Замер решения: при параллельности 4 пятый рецензент ждёт свободного места — фаза удлиняется на длину этапа.

    Насколько — зависит от того, кто ждёт (набор первым — обычно ждёт короткая линза, ~0–35 с на замере haiku);
    здесь все пять равны 100 с, чтобы эффект был детерминированным."""
    equal = {**HAIKU_S, **{s: 100.0 for s in PARALLEL}}
    four = run_graph(client_rpm=0, concurrency=4, latency=equal)
    five = run_graph(client_rpm=0, latency=equal)
    assert four["max_in_flight"] == 4 and five["max_in_flight"] == 5
    assert five["seconds"] < four["seconds"] - 80, (four["seconds"], five["seconds"])


def test_low_free_tier_rpm_waits_instead_of_failing():
    """Если у модели ключа всего 5 запросов в минуту — окно провайдера ждёт само, 429 нет, прогон завершается."""
    r = run_graph(server_rpm=5, client_rpm=0, env={"GEMINI_RPM": "5"})
    assert r["outcomes"] == ["200"] * 9, r["outcomes"]
    # без знания лимита (окно 10) сервер с лимитом 5 вернёт 429 — провайдер подождёт Retry-After и закончит
    r2 = run_graph(server_rpm=5, client_rpm=0)
    assert r2["outcomes"].count("200") == 9


def test_503_wave_falls_back_and_completes():
    r = run_graph(client_rpm=0, fail_503=6)
    assert r["outcomes"].count("200") == 9 and r["outcomes"].count("503") == 6
    assert r["seconds"] <= CRITICAL_S + 60, r["seconds"]


def _table() -> None:  # pragma: no cover - ручной запуск
    rows = [("параллельность 4 (было), окно --rpm 10", {"concurrency": 4, "client_rpm": 10}),
            ("параллельность 5 (сейчас), окно --rpm 10", {"client_rpm": 10}),
            ("параллельность 5, только окно провайдера", {"client_rpm": 0}),
            ("сервер 5 RPM, GEMINI_RPM=5", {"server_rpm": 5, "client_rpm": 0, "env": {"GEMINI_RPM": "5"}}),
            ("сервер 5 RPM, окно 10 (не знаем лимит)", {"server_rpm": 5, "client_rpm": 0}),
            ("вызовы ×1,5", {"factor": 1.5, "client_rpm": 0}), ("волна 503 ×6", {"fail_503": 6, "client_rpm": 0})]
    print(f"{'вариант':42} {'модельное время':>16} {'запросов':>9} {'429':>4} {'одновременно':>13}")
    for name, kw in rows:
        r = run_graph(**kw)
        o = r["outcomes"]
        print(f"{name:42} {r['seconds'] / 60:13.2f} мин {len(o):9} {o.count('429'):4} {r['max_in_flight']:13}")


if __name__ == "__main__":  # pragma: no cover
    _table()
