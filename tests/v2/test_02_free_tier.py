"""№02: симулятор бесплатного тарифа Gemini — полный прогон официального документа без сети.

Цепочка как у жюри: ``python -m bcc_review ВХОД ОТЧЁТ.md --provider gemini`` → pipeline → LLMClient →
GeminiProvider → настоящий адаптер v1 и типы google-genai. Подменён только сетевой клиент SDK: «сервер»
ведёт окно запросов в минуту (429 с RetryInfo), дневную квоту (429 PerDay), волны 503 и 404 по моделям,
а успешный ответ — записанный ответ этапа из mock-фикстур официального документа. Время — модельное
(паузы провайдера не ждут по-настоящему), поэтому тест идёт секунды, а «время прогона» считается по часам симулятора.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path

import pytest

genai = pytest.importorskip("google.genai")

from google.genai import errors, types  # noqa: E402

from bcc_review.v2.providers import doctor  # noqa: E402
from bcc_review.v2.providers.gemini import GeminiProvider  # noqa: E402
from bcc_review.v2.providers.mock import MockProvider  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
PRIMARY, SECOND, LITE = "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"


class SimClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []
        self.lock = threading.Lock()

    def now(self) -> float:
        with self.lock:
            return self.t

    def sleep(self, seconds: float) -> None:
        with self.lock:
            self.t += seconds
            self.sleeps.append(seconds)

    def advance(self, seconds: float) -> None:
        with self.lock:
            self.t += seconds


def api_error(code, status, message, details=None):
    return errors.APIError(code, {"error": {"code": code, "status": status, "message": message,
                                            "details": details or []}})


class FreeTier:
    """Модель бесплатного тарифа: лимиты считаются отдельно по каждой модели, как у Google."""

    def __init__(self, clock: SimClock, models: dict[str, dict], *, key_valid: bool = True, latency_s: float = 20.0):
        self.clock, self.models, self.key_valid, self.latency_s = clock, models, key_valid, latency_s
        self.lock = threading.Lock()
        self.window: dict[str, deque] = {m: deque() for m in models}
        self.day: dict[str, int] = {m: 0 for m in models}
        self.served_503: dict[str, int] = {m: 0 for m in models}
        self.log: list[tuple[str, str]] = []   # (модель, исход)

    def call(self, model: str) -> None:
        with self.lock:
            now = self.clock.now()
            cfg = self.models.get(model)
            if not self.key_valid:
                self.log.append((model, "400 key"))
                raise api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                                [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}])
            if cfg is None or cfg.get("missing"):
                self.log.append((model, "404"))
                raise api_error(404, "NOT_FOUND", f"models/{model} is not found for API version v1beta")
            if self.day[model] >= cfg.get("rpd", 250):
                self.log.append((model, "429 day"))
                raise api_error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                     "quotaValue": str(cfg.get("rpd", 250))}]}])
            win = self.window[model]
            while win and now - win[0] >= 60:
                win.popleft()
            if len(win) >= cfg.get("rpm", 10):
                retry = max(1, int(60 - (now - win[0])) + 1)
                self.log.append((model, "429 rpm"))
                raise api_error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota.", [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                                     "quotaValue": str(cfg.get("rpm", 10))}]},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{retry}s"}])
            if self.served_503[model] < cfg.get("fail_503", 0):
                self.served_503[model] += 1
                self.log.append((model, "503"))
                raise api_error(503, "UNAVAILABLE", "The model is overloaded. Please try again later.")
            win.append(now)
            self.day[model] += 1
            self.log.append((model, "200"))
        self.clock.advance(self.latency_s)


_tls = threading.local()


class SimGemini(GeminiProvider):
    """GeminiProvider с «сетью» симулятора; этап и схема запроса нужны, чтобы вернуть записанный ответ."""

    def invoke(self, *, stage: str = "", schema=None, **kw):
        _tls.stage, _tls.schema = stage, schema
        return super().invoke(schema=schema, stage=stage, **kw)


def make_sim(tier: FreeTier, clock: SimClock) -> SimGemini:
    answers = MockProvider(fixtures_dir=ROOT / "tests" / "v2" / "fixtures" / "official")
    holder: dict = {}

    def factory(model, thinking, schema_mode="native"):
        adapter = holder["p"]._v1_adapter(model, thinking, schema_mode)

        class Models:
            def generate_content(self, *, model, contents, config):
                tier.call(model)
                data = answers.invoke(model=model, messages=[], schema=_tls.schema, stage=_tls.stage)["data"]
                return types.GenerateContentResponse(
                    candidates=[types.Candidate(
                        content=types.Content(role="model", parts=[types.Part(text=json.dumps(data, ensure_ascii=False))]),
                        finish_reason="STOP")],
                    usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=12000,
                                                                              candidates_token_count=3000),
                    model_version=f"{model}-001", response_id="sim")

        class Client:
            models = Models()

        adapter._client = Client()
        return adapter

    p = SimGemini(api_key="sim-key", env={"GEMINI_FALLBACK_MODELS": f"{SECOND},{LITE}", "GEMINI_RESERVE_MODELS": "off"},
                  adapter_factory=factory, sleep=clock.sleep, clock=clock.now)
    holder["p"] = p
    return p


def run_review(tmp_path, monkeypatch, provider) -> tuple[int, dict]:
    from bcc_review.v2 import __main__ as cli
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor, "make_provider", lambda name=None, **kw: provider)
    out = tmp_path / "report.md"
    code = cli.main([str(DOC), str(out), "--provider", "gemini", "--no-cache", "-q", "--no-html", "--rpm", "0"])
    return code, json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


def tier_of(**models):
    defaults = {PRIMARY: {"rpm": 10, "rpd": 250}, SECOND: {"rpm": 10, "rpd": 250}, LITE: {"rpm": 15, "rpd": 1000}}
    for name, cfg in models.items():
        defaults[{"primary": PRIMARY, "second": SECOND, "lite": LITE}[name]].update(cfg)
    return defaults


def outcomes(tier, model=None):
    return [o for m, o in tier.log if model is None or m == model]


# --------------------------------------------------------------------------- сценарии


def test_free_tier_rpm_window_waits_retry_after_and_completes(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"rpm": 3}), latency_s=0.0)   # залп без задержки, 3 запроса в минуту
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    run = report["run"]
    assert run["status"] == "complete", run.get("warnings")
    assert code == 0
    assert "429 rpm" in outcomes(tier, PRIMARY)                  # лимит сработал…
    assert any(s > 2 for s in clock.sleeps)                       # …и провайдер ждал Retry-After
    assert not [o for o in outcomes(tier) if o in ("400 key", "429 day")]


def test_free_tier_503_waves_fall_back_to_next_model(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"fail_503": 12}))     # волна перегрузки основной модели
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    run = report["run"]
    assert run["status"] == "complete", run.get("warnings")
    assert "200" in outcomes(tier, SECOND)                        # часть этапов ушла на запасную модель
    used = " ".join(run.get("models_used") or [])
    assert SECOND in used                                         # фактическая модель — в паспорте
    assert [s for s in clock.sleeps if s in (2.0, 5.0, 10.0)]     # повторы 2/5/10 с до отката


def test_free_tier_primary_retired_404_uses_next_model(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"missing": True}))
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    assert report["run"]["status"] == "complete", report["run"].get("warnings")
    assert outcomes(tier, PRIMARY).count("404") == 1             # 404 один раз — дальше модель не зовётся
    assert all(m != PRIMARY for m in report["run"]["models_used"])


def test_free_tier_daily_quota_moves_down_the_chain(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"rpd": 0}, second={"rpd": 2}))
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    assert report["run"]["status"] == "complete", report["run"].get("warnings")
    assert "200" in outcomes(tier, LITE)
    assert outcomes(tier, PRIMARY).count("429 day") == 1


def test_free_tier_all_daily_quotas_exhausted_explains_reset_time(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"rpd": 0}, second={"rpd": 0}, lite={"rpd": 0}))
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    run = report["run"]
    assert code == 3 and run["status"] != "complete"
    first = run["warnings"][0]
    assert first.startswith("Дневная квота бесплатного ключа Gemini исчерпана"), first
    assert "восстановится около" in first and "по местному времени" in first
    assert len(tier.log) == 3                                     # по одному запросу на модель, дальше не зовём


def test_free_tier_invalid_key_one_request_and_clear_first_warning(tmp_path, monkeypatch):
    clock = SimClock()
    tier = FreeTier(clock, tier_of(), key_valid=False)
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    run = report["run"]
    assert code == 3
    assert len(tier.log) == 1                                     # после неверного ключа модель больше не зовётся
    assert run["warnings"][0].startswith("Google не принял ключ Gemini"), run["warnings"][0]
    assert report["findings"]                                     # отчёт всё равно построен (правила)


def test_free_tier_realistic_limits_fit_in_six_minutes(tmp_path, monkeypatch):
    """Реалистичные лимиты (10 запросов/мин) и задержка 20 с на ответ: прогон без 429 и в пределах 6 минут модели."""
    clock = SimClock()
    tier = FreeTier(clock, tier_of(), latency_s=20.0)
    code, report = run_review(tmp_path, monkeypatch, make_sim(tier, clock))
    assert report["run"]["status"] == "complete"
    assert set(outcomes(tier)) == {"200"}
    calls = len(tier.log)
    assert calls <= 12
    assert clock.now() <= 6 * 60 * 2   # сумма задержек всех вызовов (последовательная оценка сверху)


def test_free_tier_nov_2026_limits_three_runs_a_day(tmp_path, monkeypatch):
    """Лимиты бесплатного ключа на ноябрь 2026: Flash — 5 в минуту и 20 в сутки на модель (AI Studio, живой 429 F3),
    Flash-Lite — 15 и 500. Жюри запускает агента три раза за день на одном проекте Google: первые два прогона целиком
    на основной Flash (по 9 запросов), третий — 2 запроса на основной, один отказ «суточная квота», остальное на
    следующей Flash; все три — complete, ни одного 429 «в минуту», ни одного сбоя этапа."""
    clock = SimClock()
    tier = FreeTier(clock, tier_of(primary={"rpm": 5, "rpd": 20}, second={"rpm": 5, "rpd": 20},
                                   lite={"rpm": 15, "rpd": 500}), latency_s=20.0)
    reports = []
    for i in range(3):
        before = len(tier.log)
        (tmp_path / f"run{i}").mkdir()
        code, report = run_review(tmp_path / f"run{i}", monkeypatch, make_sim(tier, clock))
        reports.append((report, tier.log[before:]))
    for report, log in reports:
        assert report["run"]["status"] == "complete", report["run"].get("warnings")
        assert not any("не выполнен" in w for w in report["run"].get("warnings") or [])
        assert [o for _, o in log].count("200") == 9                       # 9 запросов модели на прогон
        assert "429 rpm" not in [o for _, o in log]
    first, second, third = (log for _, log in reports)
    assert {m for m, _ in first} == {PRIMARY} and {m for m, _ in second} == {PRIMARY}
    assert tier.day[PRIMARY] == 20
    prim = [o for m, o in third if m == PRIMARY]
    # отказы квоты — только у запросов, ушедших параллельно до первого отказа; дальше модель в прогоне не зовётся
    assert 1 <= prim.count("429 day") <= 6 and "200" not in prim[prim.index("429 day"):], prim
    assert any(m.startswith(SECOND) for m in reports[2][0]["run"]["models_used"])   # фактическая версия модели
