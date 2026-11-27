"""Живой путь v1 (план Б): три сбоя из разбора BCC-quality-08d3af5.

1. Адаптер команды получает строго {role, content}: поле «cache» Claude API отклонял с HTTP 400.
2. Обрезанный ответ делит пакет пополам в общем бюджете вызовов, а не выбрасывает его.
3. Цитата с несколькими вхождениями привязывается к блоку требования этого замечания.
"""

import json
import re
import types

from bcc_review import contracts as C
from bcc_review import engine
from bcc_review.contracts import ProviderError
from bcc_review.runtime.mock import synth

from .conftest import BCC, run

_STAGE = re.compile(r"^ЭТАП: (\S+)", re.M)
SEEN: list[list[dict]] = []


class StrictAdapter:
    """Как адаптер №11: сообщение с лишним полем — ошибка запроса (так отвечал Claude API)."""
    name = "anthropic"
    params = {"strict": True}

    def __init__(self, *a, **k):
        pass

    def invoke(self, *, model, messages, schema, timeout_s):
        SEEN.append(messages)
        for i, m in enumerate(messages):
            extra = set(m) - {"role", "content"}
            if extra:
                raise ProviderError("bad_request", f"messages.{i}.{sorted(extra)[0]}: Extra inputs are not permitted",
                                    status=400)
        return {"data": synth(schema), "usage": {"input_tokens": 10, "output_tokens": 5}, "model": "claude-opus-5-5",
                "request_id": "req-strict"}


class TruncatingAdapter:
    """Обрезает ответ этапа individual, если в пакете больше трёх требований."""
    name = "anthropic"
    params = {"truncating": True}

    def __init__(self, *a, **k):
        pass

    def invoke(self, *, model, messages, schema, timeout_s):
        body = messages[-1]["content"]
        stage = _STAGE.search(body).group(1)
        if stage.startswith("individual"):
            reqs = json.loads(body.split("ВХОДНЫЕ ДАННЫЕ (JSON):", 1)[1])["requirements"]
            if len(reqs) > 3:
                raise ProviderError("truncated", "stop_reason=max_tokens", usage={"input_tokens": 100, "output_tokens": 16000},
                                    model="claude-opus-5-5")
            data = {"requirements": [{"req_id": r["req_id"], "checks": [
                {"criterion": c, "status": "pass", "reason": "выполнено"} for c in C.INDIVIDUAL_CRITERIA], "issues": []}
                for r in reqs]}
        else:
            data = synth(schema)
        return {"data": data, "usage": {"input_tokens": 100, "output_tokens": 50}, "model": "claude-opus-5-5",
                "request_id": "req-trunc"}


def _use(monkeypatch, cls_name):
    from bcc_review.runtime import modules

    monkeypatch.setitem(modules.SLOTS, "anthropic", ("tests.nonexistent:X", f"tests.integration.test_live_path_fixes:{cls_name}"))


def test_team_adapter_gets_only_role_and_content(tmp_path, monkeypatch):
    _use(monkeypatch, "StrictAdapter")
    SEEN.clear()
    rep = run(tmp_path, BCC, provider="anthropic", use_cache=False)
    assert SEEN, "адаптер не вызывался"
    assert all(set(m) <= {"role", "content"} for msgs in SEEN for m in msgs)
    assert rep["run"]["mode"] == "rules_plus_llm"
    assert rep["run"]["calls"]["failed"] == 0


def test_cache_hint_kept_for_adapter_that_supports_it():
    from bcc_review.runtime.asker import Asker
    from bcc_review.runtime.context import ContextBuilder
    from bcc_review.runtime.fallback.anthropic import AnthropicAdapter

    doc = engine.read_document(BCC)
    ctx = ContextBuilder(doc)
    for adapter, expected in ((AnthropicAdapter(api_key="x"), True), (StrictAdapter(), False)):
        asker = Asker(adapter=adapter, provider="anthropic", model="m", budget=None, cache=None, stats=None,
                      tracer=None, context=ctx)
        msgs, _ = asker.build_messages("s", {"task": "t", "input": {}})
        assert any(m.get("cache") for m in msgs) is expected


def test_truncated_batch_is_split_not_dropped(tmp_path, monkeypatch):
    _use(monkeypatch, "TruncatingAdapter")
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")
    rep = run(tmp_path, BCC, provider="anthropic", use_cache=False, max_calls=80)
    assert all(r["review_status"] == "reviewed" for r in rep["requirements"]), \
        [(r["id"], r["review_reason"]) for r in rep["requirements"] if r["review_status"] != "reviewed"][:5]
    ind = next(s for s in rep["run"]["stages"] if s["name"] == "individual")
    assert ind["status"] == "ok"
    assert rep["run"]["calls"]["failed"] >= 1          # обрезанные попытки учтены в паспорте
    trace = (tmp_path / "report.md.artifacts" / "trace.jsonl").read_text(encoding="utf-8")
    assert '"event": "ask_split"' in trace


def test_split_respects_call_budget(tmp_path, monkeypatch):
    _use(monkeypatch, "TruncatingAdapter")
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")
    rep = run(tmp_path, BCC, provider="anthropic", use_cache=False, max_calls=6)
    assert rep["run"]["calls"]["physical"] <= 6
    assert rep["run"]["status"] == "partial" and rep["run"]["budget"]["exhausted"]


def test_quote_with_several_occurrences_binds_to_requirement_block():
    doc = {"id": "0" * 64, "title": "t", "format": "markdown", "warnings": [], "blocks": [
        {"id": "b0001", "kind": "paragraph", "section": ["Цели"], "text": "Клиент видит сумму операции.", "loc": {}},
        {"id": "b0002", "kind": "table_row", "section": ["API"], "text": "amount | сумму операции | integer", "loc": {}},
    ]}
    stub = types.SimpleNamespace(req_blocks={"R-02": ["b0002"]})
    cand = {"req_ids": ["R-02"], "hints": [{"block_id": None, "quote": "сумму операции"}],
            "witness": {"hint_a": {"block_id": "b0001", "quote": "сумму операции"}, "hint_b": {"quote": "integer"}}}
    out = engine.Engine.prefer_requirement_occurrence(stub, doc, cand)
    assert out["hints"][0]["block_id"] == "b0002"
    assert out["witness"]["hint_a"]["block_id"] == "b0002"
    assert out["witness"]["hint_b"] == {"quote": "integer"}           # уникальная цитата не трогается
    unrelated = engine.Engine.prefer_requirement_occurrence(stub, doc, {"req_ids": ["R-09"], "hints": cand["hints"]})
    assert unrelated["hints"][0]["block_id"] is None


def test_split_payload_helpers():
    p = {"task": "t", "input": {"requirements": [1, 2, 3, 4, 5], "other": "x"}, "context": {"mode": "auto"}}
    a, b = engine.split_payload(p)
    assert a["input"]["requirements"] == [1, 2] and b["input"]["requirements"] == [3, 4, 5]
    assert a["input"]["other"] == "x" and a["task"] == "t"
    assert engine.split_payload({"task": "t", "input": {"requirements": [1]}}) is None
    merged = engine.merge_split_results({"requirements": [1], "meta": "a"}, {"requirements": [2], "meta": "b"})
    assert merged == {"requirements": [1, 2], "meta": "a"}
