"""№02: выбор auto, понятные ошибки, doctor (без сети, ключи не печатаются)."""

from __future__ import annotations

import pytest

from bcc_review.contracts import PROVIDER_ERROR_KINDS, ProviderError
from bcc_review.v2.providers import doctor
from bcc_review.v2.providers.doctor import explain, load_dotenv, make_provider, normalize_name, resolve_auto, run_doctor

NO_CLI = lambda name: None  # noqa: E731
HAS_CLI = lambda name: "/usr/bin/claude" if name == "claude" else None  # noqa: E731


@pytest.fixture(autouse=True)
def posix(monkeypatch):
    monkeypatch.setattr("bcc_review.v2.providers.claude_cli._is_windows", lambda: False)


@pytest.mark.parametrize("env,which,expected", [
    ({"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a", "OPENAI_BASE_URL": "u"}, HAS_CLI, "gemini"),
    ({"GOOGLE_API_KEY": "g"}, NO_CLI, "gemini"),
    ({"ANTHROPIC_API_KEY": "a", "OPENAI_BASE_URL": "u"}, HAS_CLI, "anthropic"),
    ({"OPENAI_BASE_URL": "http://localhost:11434/v1"}, HAS_CLI, "openai"),
    ({}, HAS_CLI, "claude_cli"),
    ({}, NO_CLI, "offline"),
    ({"GEMINI_API_KEY": "   "}, NO_CLI, "offline"),
    ({"ANTHROPIC_BASE_URL": "http://proxy"}, NO_CLI, "offline"),   # адрес без ключа — не повод выбрать Claude API
])
def test_resolve_auto_order(env, which, expected):
    name, reason = resolve_auto(env, which)
    assert name == expected and reason


def test_normalize_name_aliases_and_unknown():
    assert normalize_name("claude") == "claude_cli"
    assert normalize_name("Ollama") == "openai"
    assert normalize_name(None) == "auto"
    with pytest.raises(ProviderError) as e:
        normalize_name("gpt5")
    assert e.value.kind == "not_configured"


def test_make_provider_kinds():
    assert make_provider("offline", env={}) is None
    assert make_provider("gemini", env={"GEMINI_API_KEY": "k"}).name == "gemini"
    assert make_provider("openai", env={"OPENAI_BASE_URL": "http://h:1/v1", "OPENAI_MODEL": "m"}).name == "openai"
    assert make_provider("claude_cli", env={}).name == "claude_cli"
    with pytest.raises(ProviderError):
        make_provider("anthropic", env={})


@pytest.mark.parametrize("kind", PROVIDER_ERROR_KINDS)
@pytest.mark.parametrize("provider", ["gemini", "anthropic", "openai", "claude_cli", None])
def test_explain_every_kind_is_russian_with_advice(kind, provider):
    text = explain(ProviderError(kind, "Исходное сообщение."), provider)
    assert "Исходное сообщение." in text
    assert "Traceback" not in text
    assert any("а" <= ch <= "я" for ch in text.lower())


def test_explain_specific_advice():
    text = explain(ProviderError("not_configured", "Не задан GEMINI_API_KEY."), "gemini")
    assert "aistudio.google.com/apikey" in text
    text = explain(ProviderError("not_found", "Модель недоступна."), "gemini")
    assert "doctor" in text and "GEMINI_MODEL" in text
    assert "Ошибка:" in explain(ValueError("x"))


def test_load_dotenv(tmp_path):
    f = tmp_path / ".env"
    f.write_text("﻿# comment\nGEMINI_API_KEY='abc'\nexport GEMINI_MODEL=gemini-x\nEMPTY=\n", encoding="utf-8")
    env = {"GEMINI_MODEL": "keep"}
    assert load_dotenv(f, env) is True
    assert env == {"GEMINI_MODEL": "keep", "GEMINI_API_KEY": "abc"}
    assert load_dotenv(tmp_path / "missing", env) is False


class FakeGemini:
    name = "gemini"

    def __init__(self, models=None, error=None, live_error=None):
        self.models, self.error, self.live_error = models or [], error, live_error

    def model_chain(self, model=None):
        return [model or "gemini-3.8-flash", "gemini-3.6-flash"]

    def list_models(self):
        if self.error:
            raise self.error
        return [{"id": m} for m in self.models]

    def invoke(self, *, model, messages, schema, timeout_s):
        if self.live_error:
            raise self.live_error
        return {"data": {"ok": False, "requirement": "x", "problem": "y"}, "usage": {"input_tokens": 10, "output_tokens": 5},
                "model": "gemini-3.8-flash-001", "meta": {"fallback_used": False}}


def run(env, fake=None, **kw):
    lines = []
    factory = (lambda name, env=None: fake) if fake is not None else None
    code = run_doctor(env=env, out=lines.append, which=NO_CLI, factory=factory, **kw)
    return code, "\n".join(lines)


def test_doctor_gemini_models_and_live_without_printing_key(monkeypatch):
    monkeypatch.setattr(doctor, "isinstance", isinstance, raising=False)
    secret = "AIzaSy-SECRET-VALUE-123"
    fake = FakeGemini(models=["gemini-3.8-flash", "gemini-3.5-flash-lite"])
    from bcc_review.v2.providers import gemini as gmod
    monkeypatch.setattr(gmod, "GeminiProvider", FakeGemini)
    code, text = run({"GEMINI_API_KEY": secret, "GEMINI_MODEL": "gemini-3.8-flash"}, fake, live=True)
    assert secret not in text
    assert "GEMINI_API_KEY: задан" in text
    assert "Провайдер: gemini" in text
    assert "[ок]  gemini-3.8-flash" in text and "[нет] gemini-3.6-flash — нет у этого ключа" in text
    assert "Модель ответила" in text and code == 0


def test_doctor_bad_key_and_failed_live(monkeypatch):
    from bcc_review.v2.providers import gemini as gmod
    monkeypatch.setattr(gmod, "GeminiProvider", FakeGemini)
    bad = ProviderError("auth", "Gemini отклонил ключ API (400 INVALID_ARGUMENT, API_KEY_INVALID).")
    code, text = run({"GEMINI_API_KEY": "k"}, FakeGemini(error=bad, live_error=bad), live=True)
    assert code == 2 and "Что исправить" in text and "ключ" in text


def test_doctor_offline_explains_what_to_do():
    code, text = run({}, None)
    assert code == 1 and "offline" in text and "aistudio.google.com/apikey" in text


def test_doctor_not_configured_provider():
    code, text = run({}, None, provider="anthropic")
    assert code == 1 and "ANTHROPIC_API_KEY" in text


def test_doctor_main_parses_args(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    code = doctor.main(["--provider", "offline"])
    out = capsys.readouterr().out
    assert code == 1 and "Диагностика bcc_review" in out


def test_is_fatal():
    from bcc_review.v2.providers.doctor import is_fatal
    assert is_fatal(ProviderError("auth", "x")) and is_fatal(ProviderError("quota", "x"))
    assert is_fatal(ProviderError("not_configured", "x"))
    assert not is_fatal(ProviderError("overloaded", "x")) and not is_fatal(ValueError("x"))


# --------------------------------------------------------------------------- первая строка для жюри

from bcc_review.v2.providers.doctor import headline  # noqa: E402


def wrapped(kind, message, **kw):
    """Ошибка так, как её отдаёт LLMClient после фатального сбоя этапа."""
    from bcc_review.v2.llm import LLMError
    err = ProviderError(kind, message, **kw)
    return LLMError("lens_qa", kind, "модель недоступна в этом прогоне: " + err.message)


@pytest.mark.parametrize("kind,message,expect", [
    ("not_configured", "Не задан GEMINI_API_KEY. Бесплатный ключ: https://aistudio.google.com/apikey",
     ["Не задан ключ Gemini", "GEMINI_API_KEY=<ключ>", "aistudio.google.com/apikey"]),
    ("auth", "Gemini отклонил ключ API (400 INVALID_ARGUMENT, API_KEY_INVALID). Проверьте GEMINI_API_KEY в .env.",
     ["Google не принял ключ Gemini", "без кавычек"]),
    ("quota", "Все модели Gemini из цепочки недоступны (…). Исчерпана дневная квота модели gemini-3.5-flash-lite. "
              "Квота восстановится около 13:00 завтра по местному времени (полночь по тихоокеанскому времени США).",
     ["Дневная квота", "13:00 завтра", "другой ключ"]),
    ("not_found", "Модель gemini-3.8-flash недоступна этому ключу или снята с API (404 NOT_FOUND).",
     ["недоступны этому ключу", "python -m bcc_review doctor", "GEMINI_MODEL"]),
    ("network", "Нет соединения с generativelanguage.googleapis.com: ConnectError.",
     ["Нет соединения с Google Gemini", "HTTPS_PROXY"]),
    ("rate_limit", "Превышен лимит запросов к модели gemini-3.8-flash (429).", ["лимит запросов в минуту", "GEMINI_RPM=5"]),
    ("overloaded", "Все модели Gemini из цепочки недоступны (… перегружена ×4).", ["Gemini перегружен"]),
])
def test_headline_for_jury_scenarios(kind, message, expect):
    for exc in (ProviderError(kind, message), wrapped(kind, message)):
        line = headline(exc, "gemini")
        assert "\n" not in line and len(line) <= 260
        for part in expect:
            assert part in line, (part, line)
        assert "модель недоступна в этом прогоне" not in line
        full = explain(exc, "gemini")
        assert full.splitlines()[0] == line


def test_headline_missing_package_and_other_providers():
    line = headline(ProviderError("not_configured", "Не установлен пакет google-genai: pip install google-genai"), "gemini")
    assert "pip install -r requirements.txt" in line and "google-genai" in line
    line = headline(ProviderError("not_configured", "Не задан ANTHROPIC_API_KEY."), "anthropic")
    assert "ANTHROPIC_API_KEY" in line and "\n" not in line
    line = headline(wrapped("auth", "Claude Code не авторизован."), "claude_cli")
    assert "claude" in line.lower() and "войдите" in line


def test_daily_reset_time_in_gemini_quota_error():
    import datetime as dt
    from bcc_review.v2.providers.gemini import _us_pacific_offset_h, daily_reset_local
    assert _us_pacific_offset_h(dt.datetime(2026, 11, 27, 0, 0)) == -8      # зима: PST
    assert _us_pacific_offset_h(dt.datetime(2026, 7, 1, 0, 0)) == -7        # лето: PDT
    text = daily_reset_local(dt.datetime(2026, 11, 26, 20, 0, tzinfo=dt.timezone.utc))
    assert "по местному времени" in text and "полночь по тихоокеанскому" in text


def test_pipeline_auto_prefers_gemini_key_over_installed_claude(monkeypatch):
    """Как у жюри: в .env есть GEMINI_API_KEY, а на машине стоит Claude Code — выбирается Gemini."""
    from bcc_review.v2 import pipeline
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    for name in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    opts = {"provider": "auto", "model": None, "fallback_models": [], "max_calls": 12, "max_seconds": 600,
            "max_retries": 2, "timeout": 600, "cache": False}
    llm, name = pipeline.make_llm(opts, None)
    assert name == "gemini" and llm.provider.name == "gemini"
    monkeypatch.delenv("GEMINI_API_KEY")
    llm2, name2 = pipeline.make_llm(opts, None)
    assert name2 == "claude_cli"


@pytest.mark.parametrize("encoding,raw", [
    ("utf-16 с BOM (PowerShell 5.1: echo … > .env)", "GEMINI_API_KEY=AIzaFAKE-1\r\n".encode("utf-16")),
    ("utf-16-le без BOM", "GEMINI_API_KEY=AIzaFAKE-1\r\n".encode("utf-16-le")),
    ("utf-8 с BOM (Блокнот)", b"\xef\xbb\xbfGEMINI_API_KEY=AIzaFAKE-1\r\n"),
    ("cp1251 с русским комментарием", "# ключ Gemini\nGEMINI_API_KEY=AIzaFAKE-1\n".encode("cp1251")),
])
def test_dotenv_any_windows_encoding(tmp_path, encoding, raw):
    from bcc_review.v2.providers.doctor import load_dotenv
    f = tmp_path / ".env"
    f.write_bytes(raw)
    env: dict = {}
    assert load_dotenv(f, env), encoding
    assert env.get("GEMINI_API_KEY") == "AIzaFAKE-1", encoding
