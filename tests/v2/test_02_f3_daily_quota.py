"""№02 (F3, волна 3): дневная квота бесплатного ключа Gemini — живой замер 27.11.

Бесплатный тариф: 20 запросов в сутки на каждую модель Flash (``GenerateRequestsPerDayPerProjectPerModel-FreeTier``,
квота на проект Google), 500 у ``gemini-3.5-flash-lite``; прогон — 9–10 запросов. Поэтому цепочка по умолчанию
идёт по всем Flash и только потом на Flash-Lite (на официальном документе Flash-Lite даёт К 3/5).
"""

from __future__ import annotations

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers import doctor
from bcc_review.v2.providers.gemini import DEFAULT_FALLBACKS, DEFAULT_MODEL, GeminiProvider, quota_limit

from test_02_gemini import MESSAGES, SCHEMA, Script, ok

SERVER_TEXT = ("You exceeded your current quota, please check your plan and billing details. * Quota exceeded for "
               "metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, "
               "model: gemini-3.8-flash")


def day_quota(model: str) -> ProviderError:
    e = ProviderError("quota", f"Исчерпана дневная квота модели {model} (GenerateRequestsPerDayPerProjectPerModel-"
                               "FreeTier).", status=429, retry_after_s=8500.0)
    e.subkind = "per_day"  # type: ignore[attr-defined]
    e.detail = {"server_message": SERVER_TEXT.replace("gemini-3.8-flash", model)}  # type: ignore[attr-defined]
    return e


def test_default_chain_tries_every_flash_before_flash_lite():
    chain = [DEFAULT_MODEL, *DEFAULT_FALLBACKS]
    flash = [m for m in chain if "lite" not in m]
    lite = [m for m in chain if "lite" in m]
    assert len(flash) == 4 and chain == flash + lite, chain


def test_daily_quota_of_primary_moves_to_next_flash_not_to_lite():
    script = Script({"gemini-3.8-flash": [day_quota("gemini-3.8-flash")]})
    p = GeminiProvider(api_key="k", env={}, adapter_factory=script.factory, sleep=lambda s: None)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["meta"]["called_model"] == "gemini-3.7-flash"
    assert r["meta"]["attempts"][0]["quota_limit"] == 20
    # квота — до конца прогона: следующий этап сразу на 3.7, без повторного запроса к 3.8
    p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert script.calls == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.7-flash"]


def test_all_flash_quotas_spent_lands_on_lite_with_explanation_in_trace():
    plan = {m: [day_quota(m)] for m in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash")}
    plan["gemini-3.5-flash-lite"] = [ok("gemini-3.5-flash-lite")]
    script = Script(plan)
    p = GeminiProvider(api_key="k", env={}, adapter_factory=script.factory, sleep=lambda s: None)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["meta"]["called_model"] == "gemini-3.5-flash-lite" and r["meta"]["physical_calls"] == 5
    assert r["usage"]["attempts"][0].startswith("gemini-3.8-flash 429")


def test_quota_limit_parsed_from_server_text():
    assert quota_limit(day_quota("gemini-3.6-flash")) == 20
    assert quota_limit(ProviderError("quota", "без числа")) is None


def test_doctor_live_explains_why_fallback_answered():
    attempts = [{"model": "gemini-3.8-flash", "kind": "quota", "subkind": "per_day", "status": 429, "quota_limit": 20},
                {"model": "gemini-3.7-flash", "kind": "not_found", "status": 404},
                {"model": "gemini-3.6-flash", "rpm_wait_s": 3.0}]
    lines = doctor._attempt_lines(attempts)
    assert len(lines) == 2
    assert "gemini-3.8-flash: исчерпана дневная квота (20 запросов в сутки на модель); восстановится около" in lines[0]
    assert "gemini-3.7-flash: модель недоступна этому ключу (404)" in lines[1]


def test_doctor_prints_free_tier_budget_for_gemini():
    class Fake:
        def model_chain(self, model=None):
            return [DEFAULT_MODEL, *DEFAULT_FALLBACKS]

        def list_models(self):
            return [{"id": m} for m in self.model_chain()]

    out: list[str] = []
    doctor.run_doctor(provider="gemini", env={"GEMINI_API_KEY": "k"}, out=out.append,
                      which=lambda n: None, factory=lambda name, env=None, **kw: Fake())
    text = "\n".join(out)
    assert "20 запросов в сутки на каждую модель Flash" in text


ENV_EXAMPLE_CHAIN = {"GEMINI_MODEL": "gemini-3.8-flash", "GEMINI_FALLBACK_MODELS": "gemini-3.6-flash,gemini-3.5-flash-lite"}


def test_old_env_example_chain_still_uses_other_flash_before_lite():
    """Жюри копирует .env.example со старым списком: после суточной квоты 3.8 и 3.6 — резервные Flash, не Lite."""
    plan = {m: [day_quota(m)] for m in ("gemini-3.8-flash", "gemini-3.6-flash")}
    script = Script(plan)
    p = GeminiProvider(api_key="k", env=ENV_EXAMPLE_CHAIN, adapter_factory=script.factory, sleep=lambda s: None)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert script.calls == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.7-flash"]
    assert r["meta"]["called_model"] == "gemini-3.7-flash"
    assert r["meta"]["model_chain"] == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash",
                                        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def test_reserve_is_not_used_without_quota_problems_or_when_off():
    script = Script({"gemini-3.8-flash": [ProviderError("not_found", "404", status=404)]})
    p = GeminiProvider(api_key="k", env=ENV_EXAMPLE_CHAIN, adapter_factory=script.factory, sleep=lambda s: None)
    assert p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)["meta"]["called_model"] == "gemini-3.6-flash"
    plan = {m: [day_quota(m)] for m in ("gemini-3.8-flash", "gemini-3.6-flash")}
    script = Script(plan)
    p = GeminiProvider(api_key="k", env={**ENV_EXAMPLE_CHAIN, "GEMINI_RESERVE_MODELS": "off"},
                       adapter_factory=script.factory, sleep=lambda s: None)
    r = p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    assert r["meta"]["called_model"] == "gemini-3.5-flash-lite"


def test_nobody_answers_explains_daily_quota_not_last_404():
    plan = {m: [day_quota(m)] for m in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")}
    plan.update({m: [ProviderError("not_found", "404", status=404)]
                 for m in ("gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite")})
    p = GeminiProvider(api_key="k", env=ENV_EXAMPLE_CHAIN, adapter_factory=Script(plan).factory, sleep=lambda s: None)
    try:
        p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=60)
    except ProviderError as e:
        assert e.kind == "quota" and "восстановится около" in e.message
        assert doctor.headline(e, "gemini").startswith("Дневная квота бесплатного ключа Gemini исчерпана")
    else:
        raise AssertionError("ожидалась ошибка квоты")
