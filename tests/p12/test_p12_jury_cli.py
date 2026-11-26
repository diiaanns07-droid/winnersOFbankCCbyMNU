"""Путь жюри через публичный CLI: ключ Gemini только из окружения.

Штатные: ``bcc_review.cli.main`` → ``engine.setup_provider`` → ``GeminiAdapter()`` **без аргументов** →
``runtime.asker.Asker`` → SDK google-genai. Имитируется только самый нижний HTTP-транспорт SDK
(``HTTPTransport.handle_request`` у httpx2/httpx): конверт ответа — фикстура ``ok_empty.json``, текст —
объект под ``responseJsonSchema`` этого же запроса (``runtime.mock.synth``). Сети нет.

Тест различает конструкторы: на ``gemini.py`` из 6f7bfbf (сейчас в bcc/integration 2821989)
``GeminiAdapter()`` не читает GEMINI_API_KEY — запросов 0, режим rules_only.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from bcc_review import cli
from bcc_review.runtime.mock import synth

from .p12_support import ROOT, load_fixture

EXAMPLE = ROOT / "contracts" / "examples" / "two_linked_requirements.md"
SYNTHETIC_KEY = "AIzaSyntheticP12KeyNotReal000000000000"
ARGV_TAIL = ["--provider", "gemini", "--max-calls", "2", "--max-seconds", "90", "--no-cache"]


def _handler(module, seen: list[dict]):
    def handle_request(self, request):
        request.read()
        body = json.loads(request.content or b"{}")
        schema = (body.get("generationConfig") or {}).get("responseJsonSchema") or {}
        seen.append({"lib": module.__name__, "path": request.url.path,
                     "key_from_env": request.headers.get("x-goog-api-key") == SYNTHETIC_KEY})
        fixture = load_fixture("ok_empty")
        envelope = fixture["body"]
        envelope["candidates"][0]["content"]["parts"] = [{"text": json.dumps(synth(schema), ensure_ascii=False)}]
        return module.Response(fixture["http_status"], json=envelope, request=request)
    return handle_request


def _patch_lowest_transport(monkeypatch) -> list[dict]:
    seen: list[dict] = []
    for name in ("httpx2", "httpx"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(module.HTTPTransport, "handle_request", _handler(module, seen))
    return seen


def test_public_cli_reads_key_from_environment_and_reaches_model(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SYNTHETIC_KEY)  # только окружение, как у жюри
    seen = _patch_lowest_transport(monkeypatch)
    out = tmp_path / "OUT.md"

    assert cli.main([str(EXAMPLE), str(out), *ARGV_TAIL]) == 0
    run = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["run"]

    assert seen, "GeminiAdapter() не отправил ни одного запроса: ключ из окружения не прочитан"
    assert all(r["key_from_env"] and r["path"].endswith(":generateContent") for r in seen)
    assert run["modules"]["provider"] == "team:bcc_review.providers.gemini:GeminiAdapter"
    assert run["calls"]["physical"] == len(seen) == 2
    assert run["mode"] == "rules_plus_llm" and run["model"] == "gemini-2.5-flash"
    assert run["budget"]["exhausted"] is True and run["budget"]["reason"] == "исчерпан лимит вызовов модели (2)"
    reached = {s["name"]: s["calls"] for s in run["stages"] if s["calls"]}
    assert sum(reached.values()) == 2 and "inventory" in reached
    assert run["status"] == "partial" and run["incomplete_stages"], "бюджет 2 — честный partial"
    assert not any("GEMINI_API_KEY" in r for r in run["status_reasons"])

    capsys.readouterr()
    assert cli.main(["verify", str(out.with_suffix(".json")), str(EXAMPLE)]) == 0
    assert capsys.readouterr().out.startswith("verify: OK")
