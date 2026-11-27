"""№24: ``doctor --live`` с Gemini за ≤ 10 с даёт понятный русский диагноз (поддельный сервер, настоящий HTTP).

Было: при перегрузке (503 у всех моделей) диагноз шёл 103 с — повторы 2/5/10 с на каждой из шести моделей
цепочки; при 429 doctor ждал Retry-After; при зависшем соединении список моделей мог ждать без предела.
Прокси сети, отвечающий 403, выдавался за «Google не принял ключ».
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers import doctor

pytest.importorskip("google.genai")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fake_gemini_24d", ROOT / "tests/v2/fixtures/24_gemini/fake_gemini.py")
fake_gemini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_gemini)


def doctor_live(faults, key="fake-key"):
    with fake_gemini.FakeGemini(faults) as fake:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GEMINI_", "GOOGLE_", "ANTHROPIC_", "OPENAI_"))}
        env.update({"GOOGLE_GEMINI_BASE_URL": fake.url, "NO_PROXY": "127.0.0.1,localhost",
                    "no_proxy": "127.0.0.1,localhost", "PYTHONIOENCODING": "utf-8"})
        if key:
            env["GEMINI_API_KEY"] = key
        t0 = time.monotonic()
        proc = subprocess.run([sys.executable, "-m", "bcc_review", "doctor", "--live", "--provider", "gemini",
                               "--env-file", str(ROOT / "tests/v2/fixtures/24_gemini/no.env")],
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return proc.returncode, proc.stdout + proc.stderr, time.monotonic() - t0


@pytest.mark.parametrize("faults, key, words", [
    ([], "", ["Не задан ключ Gemini", "aistudio.google.com/apikey"]),
    ([{"kind": "401", "times": 99}], "fake-key", ["не принял ключ"]),
    ([{"kind": "429_day", "times": 99}], "fake-key", ["Дневная квота", "восстановится", "Ключ рабочий"]),
    ([{"kind": "429", "retry_after": 40, "times": 99}], "fake-key", ["лимит запросов", "Ключ рабочий"]),
    ([{"kind": "503", "times": 99}], "fake-key", ["перегружен"]),
    ([{"kind": "drop", "times": 99}], "fake-key", ["Нет соединения", "прокси"]),
    ([{"kind": "slow", "delay": 60, "times": 99}], "fake-key", ["не ответил", "брандмауэр"]),
    ([{"kind": "slow", "stage": "unknown", "delay": 60, "times": 99}], "fake-key", ["не ответил"]),
    ([{"kind": "403_proxy", "times": 99}], "fake-key", ["прокси или брандмауэр", "ключ тут ни при чём"]),
    ([{"kind": "407", "times": 99}], "fake-key", ["прокси или брандмауэр"]),
])
def test_live_diagnosis_is_fast_and_russian(faults, key, words):
    code, text, seconds = doctor_live(faults, key)
    assert "Traceback" not in text, text[-2000:]
    assert code != 0
    assert seconds <= 10.0, (seconds, text[-1500:])
    for w in words:
        assert w in text, (w, text[-2000:])


def test_live_ok_reports_model_and_time():
    code, text, seconds = doctor_live([])
    assert code == 0 and "Модель ответила" in text and seconds <= 10.0


def test_live_overloaded_primary_reports_fallback_quickly():
    code, text, seconds = doctor_live([{"kind": "503", "model": "gemini-3.8-flash", "times": 99}])
    assert code == 0 and "gemini-3.7-flash (запасная)" in text and seconds <= 10.0


@pytest.mark.parametrize("message, proxy", [
    ("Gemini запретил доступ (403 Forbidden): <html>Access denied</html>", True),
    ("Gemini запретил доступ (403 ): blocked", True),
    ("Gemini отклонил запрос (407 Proxy Authentication Required): x", True),
    ("Gemini запретил доступ (403 PERMISSION_DENIED): Generative Language API has not been used", False),
    ("Gemini отклонил ключ API (400 INVALID_ARGUMENT, API_KEY_INVALID).", False),
])
def test_proxy_refusal_is_not_called_a_bad_key(message, proxy):
    exc = ProviderError("auth" if "403" in message or "ключ" in message else "bad_request", message)
    head = doctor.headline(exc, "gemini")
    assert ("прокси или брандмауэр" in head) is proxy, head
    assert ("не принял ключ" in head) is (not proxy and exc.kind == "auth"), head
