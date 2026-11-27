"""№24: закрытый контур банка — Ollama / vLLM через ``--provider openai`` одной командой из README.

Поддельный OpenAI-совместимый сервер (настоящий HTTP) с причудами локальных моделей: нет поддержки
``json_schema`` (400), блок рассуждений ``<think>`` перед JSON, JSON в ```json. Прогон CLI отдельным процессом.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
_spec = importlib.util.spec_from_file_location("fake_gemini_24c", ROOT / "tests/v2/fixtures/24_gemini/fake_gemini.py")
fake_gemini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_gemini)


@pytest.mark.parametrize("quirks", [{}, {"reject_json_schema": True, "think": True, "fence": True}],
                         ids=["vllm", "old-ollama-qwen3"])
def test_closed_loop_one_command(tmp_path, quirks):
    out = tmp_path / "report.md"
    with fake_gemini.FakeOpenAI(**quirks) as fake:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("GEMINI_", "GOOGLE_", "ANTHROPIC_", "OPENAI_"))}
        env.update({"OPENAI_BASE_URL": f"{fake.url}/v1", "OPENAI_MODEL": "qwen3:8b",
                    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "PYTHONIOENCODING": "utf-8"})
        proc = subprocess.run([sys.executable, "-m", "bcc_review", str(DOC), str(out), "--provider", "openai",
                               "--no-cache", "--runs-dir", str(tmp_path / "runs")],
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
        log = list(fake.log)
    text = proc.stdout + proc.stderr
    assert "Traceback" not in text and proc.returncode == 0, text[-3000:]
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["run"]["status"] == "complete", text[-2000:]
    assert data["verdict"]["development"] == "no"
    assert data["run"]["provider"] == "openai"
    if quirks.get("reject_json_schema"):
        # json_schema отвергнут один раз — дальше провайдер помнит режим и не тратит запросы
        assert sum(1 for r in log if r["kind"] == "json_schema") == 1
