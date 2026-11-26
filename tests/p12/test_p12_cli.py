"""CLI проверки ключа: python -m bcc_review.providers.gemini models|doctor."""

from __future__ import annotations

import json

from bcc_review.providers import gemini


def run_main(capsys, argv):
    code = gemini.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_doctor_without_key_explains_what_to_do(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    code, out = run_main(capsys, ["doctor"])
    assert code == 2 and out["ok"] is False and out["kind"] == "not_configured"
    assert "GEMINI_API_KEY" in out["message"] and out["physical_calls"] == 0


def test_doctor_success_prints_passport(monkeypatch, capsys, make_adapter, fake) -> None:
    fake.on("gemini-2.5-flash", "err_404_model").on("gemini-2.5-flash-lite", "ok_one_finding_lite")
    adapter = make_adapter(fallback_models=["gemini-2.5-flash-lite"])
    monkeypatch.setattr(gemini.GeminiAdapter, "from_env", classmethod(lambda cls, *a, **k: adapter))
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    code, out = run_main(capsys, ["doctor"])
    assert code == 0 and out["ok"] is True
    assert (out["requested_model"], out["model"]) == ("gemini-2.5-flash", "gemini-2.5-flash-lite")
    assert out["fallback_used"] is True
    assert out["candidates"] == 1 and out["usage"]["physical_calls"] == 2
    assert fake.requests[0]["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_doctor_quota_exit_code(monkeypatch, capsys, make_adapter, fake) -> None:
    fake.on("gemini-2.5-flash", "err_429_rpm")
    adapter = make_adapter()
    monkeypatch.setattr(gemini.GeminiAdapter, "from_env", classmethod(lambda cls, *a, **k: adapter))
    code, out = run_main(capsys, ["doctor", "--model", "gemini-2.5-flash"])
    assert code == 3 and out["kind"] == "rate_limit" and out["retry_after_s"] == 39.0


def test_models_command(monkeypatch, capsys, make_adapter) -> None:
    adapter = make_adapter()
    monkeypatch.setattr(gemini.GeminiAdapter, "from_env", classmethod(lambda cls, *a, **k: adapter))
    code, out = run_main(capsys, ["models"])
    assert code == 0 and out[0]["id"] == "gemini-2.5-flash" and all("embed" not in r["id"] for r in out)


def test_doctor_uses_the_shared_synthetic_schema(schema) -> None:
    assert gemini.DOCTOR_SCHEMA == schema
