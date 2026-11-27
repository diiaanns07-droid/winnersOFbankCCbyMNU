"""Бесплатный Gemini: одна линза узнаёт о дневном лимите, пока другая ждёт повтор."""
from bcc_review.v2.providers.gemini import GeminiProvider, ProviderError


def test_daily_quota_during_another_stages_backoff_skips_obsolete_retry():
    calls = []
    primary, reserve = "gemini-3.8-flash", "gemini-3.5-flash-lite"
    messages = [{"role": "user", "content": "Проверь требование."}]

    class Adapter:
        def invoke(self, *, model, **kwargs):
            calls.append(model)
            if model == primary and calls.count(primary) == 1:
                raise ProviderError("overloaded", "Сервис временно перегружен", status=503)
            if model == primary and calls.count(primary) == 2:
                error = ProviderError("quota", "Дневной лимит", status=429)
                error.subkind = "per_day"
                raise error
            return {"data": {}, "model": model, "usage": {}}

    def invoke(stage):
        return provider.invoke(model=None, messages=messages, schema={"type": "object"},
                               stage=stage, timeout_s=60)

    def during_backoff(seconds):
        # Пока первый этап ждёт после 503, второй получает 429 и заканчивает работу на резерве.
        assert invoke("lens_qa")["model"] == reserve

    provider = GeminiProvider(api_key="test", model=primary, fallback_models=[reserve],
                              env={"GEMINI_RPM": "0", "GEMINI_RESERVE_MODELS": "off"},
                              adapter_factory=lambda *args, **kwargs: Adapter(), sleep=during_backoff)
    response = invoke("segment")
    assert calls == [primary, primary, reserve, reserve]
    assert response["model"] == reserve
    assert {"model": primary, "skipped": "quota"} in response["meta"]["attempts"]
    assert response["meta"]["physical_calls"] == 2


def test_daily_quota_wakes_another_stage_waiting_for_rpm(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from bcc_review.v2.providers import gemini

    primary, reserve = "gemini-3.8-flash", "gemini-3.5-flash-lite"
    first_sent = threading.Event()
    waiting_for_rpm = threading.Event()
    calls, waits = [], []

    class Adapter:
        def invoke(self, *, model, **kwargs):
            calls.append(model)
            if model == primary:
                first_sent.set()
                assert waiting_for_rpm.wait(3)
                raise ProviderError("quota", "Дневной лимит", status=429)
            return {"data": {}, "model": model, "usage": {}}

    provider = GeminiProvider(api_key="test", model=primary, fallback_models=[reserve],
                              env={"GEMINI_RESERVE_MODELS": "off"}, concurrency=2,
                              adapter_factory=lambda *args, **kwargs: Adapter())
    monkeypatch.setattr(gemini, "RATE_WINDOW_S", 10)
    monkeypatch.setattr(provider, "rpm_for", lambda m: 1 if m == primary else 0)
    wait = provider._wait_for_model

    def measured(model, seconds):
        if model == primary:
            waiting_for_rpm.set()
        elapsed = wait(model, seconds)
        waits.append((seconds, elapsed))
        return elapsed

    monkeypatch.setattr(provider, "_wait_for_model", measured)
    def invoke(stage):
        return provider.invoke(model=None, messages=[], schema={"type": "object"}, stage=stage, timeout_s=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke, "lens_qa")
        assert first_sent.wait(3)
        second = executor.submit(invoke, "consistency")
        assert first.result(timeout=5)["model"] == second.result(timeout=5)["model"] == reserve
    assert calls.count(primary) == 1
    assert len(waits) == 1 and waits[0][0] >= 8 and waits[0][1] < 5
