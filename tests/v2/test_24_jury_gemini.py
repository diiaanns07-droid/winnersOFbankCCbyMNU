"""№24: сценарий жюри с бесплатным ключом Gemini — без ключа и без интернета.

Агент запускается как у жюри (``python -m bcc_review ТЗ отчёт.md --provider gemini``) отдельным процессом;
настоящий SDK ``google-genai`` ходит по HTTP к поддельному серверу Gemini (``GOOGLE_GEMINI_BASE_URL``), который
отвечает записанными ответами этапов и по сценарию — отказами: 429 с Retry-After, 503, обрыв соединения,
обрезанный JSON, пустой ответ, блок безопасности, 400 «схема слишком сложная», неверный ключ, дневная квота.

Требование: каждый путь заканчивается повтором, запасной моделью или частичным отчётом; никогда — падением
(трассировкой Python) или ложным «можно». На официальном ТЗ есть блокеры, поэтому вердикт — «нельзя» либо
«не вынесен» (если модель недоступна совсем), но не «можно».
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("google.genai")

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
_spec = importlib.util.spec_from_file_location("fake_gemini_24", ROOT / "tests/v2/fixtures/24_gemini/fake_gemini.py")
fake_gemini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_gemini)


def jury_run(tmp_path: Path, faults: list[dict], *extra: str, env_extra: dict | None = None):
    """Прогон CLI против поддельного сервера: (код выхода, вывод, JSON отчёта или None, журнал сервера)."""
    out = tmp_path / "report.md"
    with fake_gemini.FakeGemini(faults) as fake:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GEMINI_", "GOOGLE_", "ANTHROPIC_", "OPENAI_"))}
        env.update({"GOOGLE_GEMINI_BASE_URL": fake.url, "GEMINI_API_KEY": "fake-jury-key",
                    "GEMINI_RPM": "0",   # окно запросов проверяет test_24_gemini_faults; здесь — без минутных пауз
                    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
                    "PYTHONIOENCODING": "utf-8", **(env_extra or {})})
        proc = subprocess.run([sys.executable, "-m", "bcc_review", str(DOC), str(out), "--provider", "gemini",
                               "--no-cache", "--runs-dir", str(tmp_path / "runs"), "--rpm", "0", *extra],
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        log = list(fake.log)
    js = out.with_suffix(".json")
    data = json.loads(js.read_text(encoding="utf-8")) if js.is_file() else None
    return proc.returncode, proc.stdout + proc.stderr, data, log


def assert_honest(code: int, text: str, data: dict | None) -> tuple[str, dict]:
    """Нет падения, отчёт есть, вердикт не «можно»; возвращает (статус прогона, вердикт)."""
    assert "Traceback" not in text, text[-3000:]
    assert data is not None, f"нет отчёта JSON (код {code}):\n{text[-3000:]}"
    assert code in (0, 3), f"код выхода {code}:\n{text[-3000:]}"
    verdict = data["verdict"]
    assert verdict["development"] != "yes" and verdict["testing"] != "yes", verdict
    return data["run"]["status"], verdict


def test_clean_run_is_complete_and_blocked(tmp_path):
    code, text, data, log = jury_run(tmp_path, [])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete"
    assert verdict["development"] == "no"
    assert data["run"]["provider"] == "gemini"
    assert {r["stage"] for r in log} >= {"segment", "lens_analyst", "lens_qa", "lens_architect", "lens_risk",
                                          "consistency", "judge"}
    assert all(r["model"] == "gemini-3.8-flash" for r in log)


def test_every_transient_fault_recovers_to_complete(tmp_path):
    """Один прогон — все временные отказы разом: каждый этап получает свой, итог — complete и «нельзя»."""
    faults = [{"kind": "empty", "stage": "segment"},
              {"kind": "no_candidates", "stage": "lens_analyst"},
              {"kind": "400_schema", "stage": "lens_architect"},
              {"kind": "drop", "stage": "lens_risk"},
              {"kind": "429", "stage": "lens_qa", "retry_after": 1},
              {"kind": "503", "stage": "consistency"},
              {"kind": "truncated_json", "stage": "judge"}]
    code, text, data, log = jury_run(tmp_path, faults)
    status, verdict = assert_honest(code, text, data)
    assert status == "complete", text[-2000:]
    assert verdict["development"] == "no"
    fired = {(r["stage"], r["kind"]) for r in log}
    # 400 «схема» у архитектора не уводит остальные этапы в режим «схема текстом» (v2.1: было 8 этапов, стало 1)
    assert {r["stage"] for r in log if r["schema_mode"] == "text"} == {"lens_architect"}
    assert {(f["stage"], f["kind"]) for f in faults} <= fired   # каждый отказ действительно случился
    assert code == 0


def test_overloaded_primary_falls_back_to_next_flash(tmp_path):
    code, text, data, log = jury_run(tmp_path, [{"kind": "503", "model": "gemini-3.8-flash", "times": 999}])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete"
    assert verdict["development"] == "no"
    assert "gemini-3.7-flash" in data["run"]["models_used"]


def test_daily_quota_on_primary_uses_chain(tmp_path):
    code, text, data, log = jury_run(tmp_path, [{"kind": "429_day", "model": "gemini-3.8-flash", "times": 999}])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete"
    # квота основной модели — она вызвана один раз, дальше прогон её не трогает
    assert sum(1 for r in log if r["model"] == "gemini-3.8-flash") == 1


def test_judge_blocked_by_safety_is_partial_not_yes(tmp_path):
    code, text, data, log = jury_run(tmp_path, [{"kind": "safety", "stage": "judge", "times": 99}])
    status, verdict = assert_honest(code, text, data)
    assert status == "partial"
    assert verdict["development"] in ("no", "none")


def test_lens_recitation_stop_once_recovers(tmp_path):
    """v2.1: одна остановка RECITATION у линзы — повтор, прогон complete (было: partial, линза потеряна)."""
    code, text, data, log = jury_run(tmp_path, [{"kind": "finish_recitation", "stage": "lens_risk"}])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete" and verdict["development"] == "no"


def test_lens_safety_stop_is_partial_with_reason(tmp_path):
    code, text, data, log = jury_run(tmp_path, [{"kind": "finish_safety", "stage": "lens_risk", "times": 99}])
    status, verdict = assert_honest(code, text, data)
    assert status == "partial"
    assert "фильтр" in text


@pytest.mark.parametrize("kind, words", [
    ("401", ["ключ", "aistudio.google.com/apikey"]),
    ("429_day", ["квота", "восстановится"]),
    ("drop", ["соединения", "прокси"]),
])
def test_dead_provider_gives_rules_report_with_russian_reason(tmp_path, kind, words):
    """Ключ неверен, квота исчерпана, сети нет: отчёт правилами, понятная причина по-русски, без «можно»."""
    code, text, data, log = jury_run(tmp_path, [{"kind": kind, "times": 9999}])
    status, verdict = assert_honest(code, text, data)
    assert status in ("partial", "failed")
    low = text.lower()
    for w in words:
        assert w.lower() in low, (w, text[-2000:])
    # неверный ключ и сеть не перебирают всю цепочку на каждом этапе
    if kind in ("401", "drop"):
        assert len(log) <= 4, [(r["stage"], r["model"], r["kind"]) for r in log]


def test_judge_truncated_by_thinking_recovers_on_low(tmp_path):
    """Этап 2: судья упёрся в предел ответа из-за рассуждения — повтор с «low», прогон complete, «нельзя»."""
    code, text, data, log = jury_run(tmp_path, [{"kind": "max_tokens", "stage": "judge", "thoughts": 60000}])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete" and verdict["development"] == "no"
    judge = [(r["kind"], r["thinking"]) for r in log if r["stage"] == "judge"]
    assert judge == [("max_tokens", "MEDIUM"), ("ok", "LOW")]


def test_lens_truncated_json_is_split_by_stage(tmp_path):
    """Обрезан сам JSON (рассуждения мало): провайдер не повторяет вслепую, линза делит пакет — complete."""
    code, text, data, log = jury_run(tmp_path, [{"kind": "max_tokens", "stage": "lens_analyst", "thoughts": 10}])
    status, verdict = assert_honest(code, text, data)
    assert status == "complete" and verdict["development"] == "no"
    assert [r["kind"] for r in log if r["stage"] == "lens_analyst"] == ["max_tokens", "ok", "ok"]
