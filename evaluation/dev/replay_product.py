"""Продукт bcc_review с записанным транспортом Claude API — для открытого стенда, без сети и без ключа.

    python evaluation/dev/replay_product.py INPUT OUTPUT.md --provider anthropic --no-cache

Это обёртка над настоящим движком (путь к его src — в PYTHONPATH). Подменяется только HTTP-транспорт
адаптера Anthropic: вместо сети отвечают записи из tests/p11/fixtures того же checkout продукта
(каталог — BCC_REPLAY_FIXTURES). Записи синтетические (`"_synthetic": true`); реальные запросы
к Anthropic выполняет только Claude Max, этот файл их не заменяет.

Сценарий выбирается по SHA-256 входного файла: BCC_REPLAY_PLAN = JSON {sha256: сценарий}, иначе `ok`.
* `ok`              — каждый запрос /v1/messages получает конверт success_candidates.json (200, usage, model),
                      в котором текст заменён минимальным ответом, валидным по схеме этапа (runtime.mock.synth;
                      для individual — строка с пустыми checks на каждое требование пакета);
* `fail:ЭТАП[,ЭТАП]` — как `ok`, но запросы этих этапов (строка «ЭТАП: …» промпта) получают overloaded_529.json;
* `no_key`          — транспорт не подменяется, ключа нет: адаптер не создаётся, как при прогоне без ANTHROPIC_API_KEY.
Журнал ответов транспорта пишется рядом с отчётом (OUTPUT.replay.json), даже если продукт упал.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

STAGE_RE = re.compile(r"ЭТАП: ([\w.#-]+)")


def _load(fixtures: Path, name: str) -> dict:
    return json.loads((fixtures / f"{name}.json").read_text(encoding="utf-8"))


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _req_ids(body: dict) -> list[str]:
    """input.req_ids пакета individual из текста запроса."""
    for s in _strings(body.get("messages")):
        m = re.search(r'"req_ids"\s*:\s*\[([^\]]*)\]', s)
        if m:
            return re.findall(r'"([^"]+)"', m.group(1))
    return []


def main(argv: list[str]) -> int:
    for k in [k for k in os.environ if k.startswith("ANTHROPIC_")]:
        os.environ.pop(k)  # ключ не нужен и не должен попасть в адаптер
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        os.environ[k] = "http://127.0.0.1:9"  # всё равно закрыть сеть: транспорт обязан ответить сам
    fixtures = Path(os.environ["BCC_REPLAY_FIXTURES"]).resolve()
    plan = json.loads(os.environ.get("BCC_REPLAY_PLAN") or "{}")
    src = Path(argv[0])
    scenario = plan.get(hashlib.sha256(src.read_bytes()).hexdigest(), "ok")
    if scenario not in ("ok", "no_key") and not scenario.startswith("fail:"):
        raise SystemExit(f"replay: неизвестный сценарий {scenario!r}: ok | no_key | fail:ЭТАП[,ЭТАП]")
    failing = set(scenario[5:].split(",")) if scenario.startswith("fail:") else set()

    import httpx2
    import bcc_review.providers.anthropic as team
    from bcc_review.cli import main as product_main
    from bcc_review.runtime.mock import synth

    success, overloaded = _load(fixtures, "success_candidates"), _load(fixtures, "overloaded_529")
    journal: list[dict] = []

    class ScenarioTransport(httpx2.BaseTransport):
        def handle_request(self, request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content) if request.content else {}
            m = STAGE_RE.search(json.dumps(body, ensure_ascii=False))
            stage = m.group(1) if m else None
            n_messages = sum(1 for j in journal if j["path"].endswith("/v1/messages"))
            if not request.url.path.endswith("/v1/messages"):
                rec = {"status": 404, "headers": {"request-id": "req_replay_404"},
                       "body": {"type": "error", "error": {"type": "not_found_error", "message": "replay"}}}
                fixture = "-"
            elif stage in failing or (stage or "").split("#", 1)[0] in failing:
                rec, fixture = overloaded["response"], "overloaded_529"
            else:
                schema = body["output_config"]["format"]["schema"]
                rec = json.loads(json.dumps(success["response"]))
                answer = synth(schema)
                if (stage or "").startswith("individual"):
                    # минимальный ответ без строки на каждое требование пакета этап считает невыполненным
                    answer = {"results": [{"req_id": rid, "checks": []} for rid in _req_ids(body)]}
                text = json.dumps(answer, ensure_ascii=False)
                rec["body"]["content"] = [c if c["type"] != "text" else {"type": "text", "text": text}
                                          for c in rec["body"]["content"]]
                rec["body"]["id"] = f"msg_replay_{n_messages + 1:03d}"
                fixture = "success_candidates (текст: synth по схеме этапа)"
            journal.append({"path": request.url.path, "stage": stage, "status": rec["status"], "fixture": fixture})
            return httpx2.Response(rec["status"], headers=rec.get("headers") or {}, json=rec.get("body"))

    if scenario != "no_key":
        real = team.AnthropicAdapter
        team.AnthropicAdapter = lambda *a, **kw: real(transport=ScenarioTransport(), mode="mock", env={},
                                                      verify_model=False)
    try:
        return product_main(argv if "--max-retries" in argv else argv + ["--max-retries", "0"])
    finally:
        Path(argv[1]).with_suffix(".replay.json").write_text(
            json.dumps({"scenario": scenario, "fixtures": str(fixtures), "responses": journal}, ensure_ascii=False,
                       indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
