"""Что движок видит об одном ответе Claude: четыре исхода и чтение из кэша (№11 → Max).

Путь настоящий: ``Engine.make_ask → Asker → AnthropicAdapter (слот команды) →
RecordedTransport``, этап ``individual#1`` модуля команды. Итог берётся из тех же функций,
что пишут report.json: ``Engine.run_individual``, ``Engine.build_checks``,
``Engine.build_run``; трасса — настоящий ``Tracer`` в ``trace.jsonl``. Нарезка и остальные
этапы не запускаются (inventory отмечен вручную), поэтому ``run.status`` не сравнивается.

Записи транспорта — из ``fixtures/``: конверт (HTTP-статус, request-id, model, stop_reason,
stop_details, usage) без изменений, текстовый блок заменён ответом под схему individual.
Отказ до начала генерации выведен из ``refusal_200``: content пуст, output_tokens = 0.
Сеть и ключ не нужны. Утверждения о движке — факты среза ``bcc/integration`` 2821989.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from bcc_review import contracts as C
from bcc_review.engine import Engine
from bcc_review.providers.anthropic import RecordedTransport
from bcc_review.runtime.context import ContextBuilder
from bcc_review.runtime.modules import Modules

from conftest import load, models, outcome
from test_asker_path import DATA, DOC, REQS, STAGE_1

MODEL = "claude-opus-5-5"
KEY = "test-key-not-a-secret"
AUDIT = {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": ""}

BAD = copy.deepcopy(DATA)
BAD["results"][0]["checks"][0]["severity"] = "blocker"  # вне enum схемы individual


def record(name: str, *, text: str | None = None, content: list | None = None, **usage: int) -> dict[str, Any]:
    rec = copy.deepcopy(load(name))
    body = rec["response"]["body"]
    if content is not None:
        body["content"] = content
    if text is not None:
        body["content"] = [dict(b, text=text) if b.get("type") == "text" else b for b in body["content"]]
    body["usage"].update(usage)
    return rec


RECORDS = {
    "valid": record("success_candidates", text=json.dumps(DATA, ensure_ascii=False)),
    "max_tokens": record("max_tokens_stop", text=json.dumps(DATA, ensure_ascii=False)[:120]),
    "schema": record("wrong_schema_200", text=json.dumps(BAD, ensure_ascii=False)),
    "refusal": record("refusal_200", content=[], output_tokens=0),
}


def run_stage(tmp: Path, records: list[dict[str, Any]], *, cache_dir: Path, run_id: str) -> dict[str, Any]:
    src = tmp / "tz.md"
    src.write_text("# ТЗ\n\n" + DOC["blocks"][1]["text"] + "\n", encoding="utf-8")
    art = tmp / f"{run_id}.artifacts"
    opts = C.RunOptions(provider="anthropic", run_id=run_id, artifacts_dir=str(art), cache_dir=str(cache_dir),
                        trace=True)
    eng = Engine(src, tmp / f"{run_id}.md", opts)
    slot = Modules().get("anthropic")
    assert slot.origin == "team" and slot.path == "bcc_review.providers.anthropic:AnthropicAdapter"
    transport = RecordedTransport(records, models=models())
    # то же, что Engine.setup_provider, только вместо HTTPS — записи транспорта
    eng.provider, eng.requested_model, eng.unavailable = "anthropic", MODEL, None
    eng.adapter, eng.adapter_label = slot.func(transport=transport, env={"ANTHROPIC_API_KEY": KEY}), slot.label
    context = ContextBuilder(DOC, full_context_chars=opts.full_context_chars)
    ask = eng.make_ask(context)
    reqs = copy.deepcopy(REQS)
    context.set_requirements(reqs)
    eng.mark("inventory", "ok")  # нарезка не запускается: требование задано
    ind = eng.run_individual(DOC, reqs, ask)
    checks = eng.build_checks(reqs, ind.get("checks", []), [], ind.get("failed") or {}, True)
    run = eng.build_run(AUDIT)
    sent = [(r["method"], r["path"]) for r in transport.requests]
    return {
        "adapter": eng.adapter, "transport": transport, "ind": ind, "req": reqs[0], "checks": checks, "run": run,
        "stage": next(s for s in run["stages"] if s["name"] == "individual"),
        "trace": [json.loads(x) for x in (art / "trace.jsonl").read_text(encoding="utf-8").splitlines()],
        "posts": sent.count(("POST", "/v1/messages")),
        "gets": sum(1 for m, p in sent if m == "GET" and p.startswith("/v1/models/")),
    }


def event(res: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [e for e in res["trace"] if e["event"] == name and e.get("stage") == STAGE_1]
    return found


# исход, запись, kind в движке (None = успех), request_id, stop_reason, (input, output), успешная стадия
CASES = [
    ("валидный ответ по схеме", "valid", None, "req_synth_success_01", "end_turn", (5210, 612),
     "модуль individual: проверка принята"),
    ("оборван по max_tokens", "max_tokens", "truncated", "req_synth_max_tokens", "max_tokens", (5210, 16000),
     "HTTP 200 и конверт; stop_reason отвергнут адаптером"),
    ("ошибка схемы (severity=blocker)", "schema", "invalid_output", "req_synth_wrong_schema", "end_turn",
     (1200, 340), "JSON разобран; схема не пройдена"),
    ("отказ до начала генерации", "refusal", "refusal", "req_synth_refusal", "refusal", (1200, 0),
     "HTTP 200; генерации нет"),
]


@pytest.mark.parametrize(("label", "key", "kind", "request_id", "stop", "tokens", "reached"), CASES,
                         ids=[c[1] for c in CASES])
def test_one_response_as_engine_sees_it(tmp_path, label, key, kind, request_id, stop, tokens, reached):
    res = run_stage(tmp_path, [RECORDS[key]], cache_dir=tmp_path / "cache", run_id=key)
    run, stage, req = res["run"], res["stage"], res["req"]

    # транспорт: одна служебная проверка модели и ровно один POST, повторов нет ни в одном исходе
    assert (res["posts"], res["gets"]) == (1, 1) and res["transport"].remaining == 0
    assert res["adapter"].passport()["physical_calls"] == {"messages": 1, "models": 1, "other": 0}
    # адаптер: фактическая модель, request_id и stop_reason есть в его журнале во всех четырёх исходах
    last = res["adapter"].last_call
    assert (last["model"], last["request_id"], last["stop_reason"]) == (MODEL, request_id, stop)
    # report.json: модель и токены доходят и при ошибке, служебный GET в calls не входит
    assert (run["provider"], run["requested_model"], run["model"], run["models_seen"]) == (
        "anthropic", MODEL, MODEL, [MODEL])
    assert run["calls"] == {"physical": 1, "cache_hits": 0, "failed": 0 if kind is None else 1, "retries": 0}
    assert (run["tokens"]["input"], run["tokens"]["output"]) == tokens
    assert (stage["calls"], stage["model"], stage["input_tokens"], stage["output_tokens"]) == (1, MODEL, *tokens)
    assert run["modules"]["provider"] == "team:bcc_review.providers.anthropic:AnthropicAdapter"

    if kind is None:
        ok = event(res, "call_ok")
        assert (ok["model"], ok["request_id"], ok["input_tokens"], ok["output_tokens"]) == (MODEL, request_id, *tokens)
        assert not res["ind"].get("failed") and res["ind"]["checks"]
        assert (stage["status"], stage["reason"], run["mode"]) == ("ok", None, "rules_plus_llm")
        # в ответе один критерий из 9, поэтому partial — это свойство данных, а не потеря
        assert (req["review_status"], req["review_reason"]) == ("partial", "модель проверила 1 из 9 критериев")
        assert [(c["criterion"], c["status"]) for c in res["checks"] if c["source"] == "llm"] == [
            ("unambiguous", "issue")]
        assert run["tokens"]["cache_read"] == 4096
        sign = f"individual=ok; mode={run['mode']}; checks: 1 llm-issue"
    else:
        err = event(res, "call_error")
        assert (err["kind"], err["model"], err["attempt"]) == (kind, MODEL, 1)
        # движок не пишет в трассу request_id и токены ошибки: они есть только в журнале адаптера
        assert not {"request_id", "input_tokens", "output_tokens"} & set(err)
        assert not [e for e in res["trace"] if e["event"] in ("retry", "call_invalid")]
        assert res["ind"]["failed"]["R-01"].startswith(f"этап {STAGE_1}: {kind}: ")
        # подпись: stage — общая фраза без kind; kind виден только в requirements[].review_reason
        assert (stage["status"], run["mode"]) == ("failed", "rules_only")
        assert kind not in stage["reason"] and "ошибки перехвачены модулем" in stage["reason"]
        assert f"individual: {stage['reason']}" in run["status_reasons"]
        assert req["review_status"] == "partial" and f"{STAGE_1}: {kind}: " in req["review_reason"]
        assert {(c["status"], c["source"]) for c in res["checks"]} == {("unknown", "rules")}
        sign = f"individual=failed; mode={run['mode']}; review_reason «{kind}»"
        assert {"truncated": "max_tokens", "invalid_output": "schema_mismatch", "refusal": "cyber"}[kind] \
            == res["adapter"].journal[-1]["subkind"]
    outcome(label, res["posts"], res["gets"], run["model"], reached, sign)


def test_cache_read_vs_fresh(tmp_path):
    cache = tmp_path / "cache"
    fresh = run_stage(tmp_path, [RECORDS["valid"]], cache_dir=cache, run_id="fresh")
    cached = run_stage(tmp_path, [], cache_dir=cache, run_id="cached")  # записей нет: любой запрос — ошибка

    assert (fresh["posts"], fresh["gets"]) == (1, 1)
    assert cached["transport"].requests == [] and (cached["posts"], cached["gets"]) == (0, 0)
    assert cached["adapter"].passport()["physical_calls"] == {"messages": 0, "models": 0, "other": 0}
    assert cached["ind"]["checks"] == fresh["ind"]["checks"] and not cached["ind"].get("failed")

    f, c = fresh["run"], cached["run"]
    assert f["calls"] == {"physical": 1, "cache_hits": 0, "failed": 0, "retries": 0}
    assert c["calls"] == {"physical": 0, "cache_hits": 1, "failed": 0, "retries": 0}
    assert f["tokens"] == {"input": 5210, "output": 612, "cache_read": 4096}
    assert c["tokens"] == {"input": 0, "output": 0, "cache_read": 0}
    assert f["model"] == c["model"] == MODEL and f["mode"] == c["mode"] == "rules_plus_llm"
    # статус "cached" есть в STAGE_STATUSES, но движок его не ставит: отличие видно только по счётчикам
    assert fresh["stage"]["status"] == cached["stage"]["status"] == "ok"
    assert (cached["stage"]["calls"], cached["stage"]["cache_hits"]) == (0, 1)

    ok, hit = event(fresh, "call_ok"), event(cached, "cache_hit")
    assert ok["request_id"] == "req_synth_success_01"
    assert set(hit) - {"ts", "run_id", "event"} == {"stage", "model", "cache_key"}  # ни request_id, ни токенов
    assert hit["cache_key"] == ok["cache_key"] and hit["model"] == MODEL

    # происхождение прежнего ответа — только в файле кэша, найти по 12 знакам cache_key из трассы
    (path,) = cache.glob(f"*/{hit['cache_key']}*.json")
    entry = json.loads(path.read_text(encoding="utf-8"))
    assert (entry["request_id"], entry["model"], entry["requested_model"]) == ("req_synth_success_01", MODEL, MODEL)
    assert entry["usage"]["input_tokens"] == 5210 and entry["stage"] == STAGE_1
    assert "stop_reason" not in entry  # Asker кладёт в кэш только data/model/usage/request_id/…
    outcome("тот же валидный ответ из кэша", cached["posts"], cached["gets"], c["model"],
            "кэш: схема прошла повторно в Asker", "individual=ok; calls.physical=0, cache_hits=1, tokens=0")


def test_invoke_returns_stop_reason_from_contract(make_adapter, schema, messages):
    """``contracts.ProviderAdapter``: invoke возвращает и ``stop_reason`` (как резерв, Gemini и mock)."""
    adapter = make_adapter("success_candidates")  # запись без изменений, схема Candidate

    res = adapter.invoke(model=None, messages=messages, schema=schema, timeout_s=30)

    assert set(res) == {"data", "usage", "model", "request_id", "stop_reason"}
    assert res["stop_reason"] == "end_turn" == adapter.last_call["stop_reason"]
    assert (res["model"], res["request_id"]) == (MODEL, "req_synth_success_01")
    assert adapter.transport.remaining == 0 and adapter.physical_calls == 1
