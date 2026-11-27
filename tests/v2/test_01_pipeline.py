"""Тесты каркаса v2 (№01): клиент модели, контекст, mock, конвейер, команда stage, вердикт."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2 import pipeline
from bcc_review.v2.context import Context
from bcc_review.v2.llm import BudgetExceeded, LLMClient, LLMError, Truncated, merge_lists
from bcc_review.v2.providers.mock import MockProvider
from bcc_review.v2.types import CANDIDATES_SCHEMA, conform, empty_for

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
          "properties": {"items": {"type": "array", "items": {"type": "string"}}}}


class FakeProvider:
    name = "fake"
    handles_retries = False

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def invoke(self, *, model, messages, schema, timeout_s, max_output_tokens=None, stage="", **_):
        self.calls.append({"stage": stage, "user": messages[-1]["content"], "model": model})
        step = self.script.pop(0) if self.script else {"items": []}
        if callable(step):
            step = step(messages[-1]["content"])
        if isinstance(step, Exception):
            raise step
        return {"data": step, "usage": {"input_tokens": 10, "output_tokens": 5}, "model": model or "m",
                "stop_reason": "end_turn"}


def client(script, **kw):
    kw.setdefault("sleep", lambda s: None)
    return LLMClient(FakeProvider(script), model="m", provider_name="fake", **kw)


# --------------------------------------------------------------------------- LLMClient

def test_ask_validates_and_repairs_once():
    llm = client([{"items": [1]}, {"items": ["ok"]}])
    assert llm.ask("s", "sys", "user", SCHEMA) == {"items": ["ok"]}
    assert llm.stats["calls"] == 2 and llm.stats["repaired"] == 1
    assert "не прошёл проверку" in llm.provider.calls[1]["user"]


def test_ask_invalid_twice_raises():
    llm = client([{"items": [1]}, {"items": [2]}])
    with pytest.raises(LLMError) as e:
        llm.ask("s", "sys", "user", SCHEMA)
    assert e.value.kind == "invalid_output"


def test_transient_errors_are_retried():
    llm = client([ProviderError("overloaded", "busy"), ProviderError("rate_limit", "slow", retry_after_s=1),
                  {"items": ["a"]}])
    assert llm.ask("s", "sys", "user", SCHEMA) == {"items": ["a"]}
    assert llm.stats["retries"] == 2 and llm.stats["calls"] == 3


def test_fallback_model_on_not_found():
    llm = client([ProviderError("not_found", "no model"), {"items": ["b"]}], fallback_models=["m2"])
    assert llm.ask("s", "sys", "user", SCHEMA) == {"items": ["b"]}
    assert [c["model"] for c in llm.provider.calls] == ["m", "m2"]


def test_budget_is_enforced():
    llm = client([{"items": []}] * 5, max_calls=2)
    llm.ask("s", "a", "1", SCHEMA)
    llm.ask("s", "a", "2", SCHEMA)
    with pytest.raises(BudgetExceeded):
        llm.ask("s", "a", "3", SCHEMA)


def test_ask_split_halves_truncated_batch():
    def answer(user):
        items = user.split(",")
        if len(items) > 2:
            raise ProviderError("truncated", "too long")
        return {"items": items}

    llm = client([answer] * 10)
    out = llm.ask_split("s", lambda it: ("sys", ",".join(it)), list("abcd"), SCHEMA, merge_lists)
    assert sorted(out["items"]) == list("abcd")
    assert llm.stats["split"] == 1
    # не больше одного деления на этап: половина, которая снова обрезана, — ошибка этапа, а не каскад
    llm = client([answer] * 10)
    with pytest.raises(Truncated):
        llm.ask_split("s", lambda it: ("sys", ",".join(it)), list("abcdef"), SCHEMA, merge_lists)


def test_stage_timeout_and_rpm():
    t = [0.0]
    llm = LLMClient(FakeProvider([{"items": []}] * 5), model="m", provider_name="fake", stage_timeout_s=100,
                    rpm=30, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    llm.ask("s", "a", "1", SCHEMA)
    llm.ask("s", "a", "2", SCHEMA)
    assert t[0] == pytest.approx(2.0)  # 30 в минуту — пауза 2 с между запросами
    t[0] += 200
    with pytest.raises(BudgetExceeded):
        llm.ask("s", "a", "3", SCHEMA)
    assert llm.ask("other", "a", "4", SCHEMA) == {"items": []}


def test_truncated_retries_with_bigger_limit_then_raises():
    llm = client([ProviderError("truncated", "x"), {"items": ["ok"]}])
    assert llm.ask("s", "sys", "u", SCHEMA, max_output_tokens=8000) == {"items": ["ok"]}
    assert llm.stats["expanded"] == 1


def test_truncated_single_item_raises():
    llm = client([ProviderError("truncated", "x")] * 3)
    with pytest.raises(Truncated):
        llm.ask_split("s", lambda it: ("sys", "u"), ["one"], SCHEMA, merge_lists)


def test_cache_roundtrip(tmp_path):
    llm = client([{"items": ["x"]}], cache_dir=tmp_path)
    assert llm.ask("s", "a", "u", SCHEMA) == {"items": ["x"]}
    llm2 = client([], cache_dir=tmp_path)
    assert llm2.ask("s", "a", "u", SCHEMA) == {"items": ["x"]}
    assert llm2.stats["cached"] == 1 and llm2.stats["calls"] == 0


# --------------------------------------------------------------------------- типы, mock, контекст

def test_conform_and_empty():
    assert empty_for(CANDIDATES_SCHEMA) == {"candidates": []}
    raw = {"requirements": [{"id": "R-01", "page": None, "quote": "q"}], "extra": 1}
    sch = {"type": "object", "additionalProperties": False, "required": ["requirements"],
           "properties": {"requirements": {"type": "array", "items": {
               "type": "object", "additionalProperties": False, "required": ["quote", "kind"],
               "properties": {"quote": {"type": "string"}, "kind": {"type": "string", "enum": ["a", "b"]}}}}}}
    assert conform(raw, sch) == {"requirements": [{"quote": "q", "kind": "a"}]}


def test_mock_reads_fixture_and_falls_back_to_empty(tmp_path):
    (tmp_path / "lens_x.json").write_text(json.dumps({"candidates": [], "junk": 1}), encoding="utf-8")
    m = MockProvider(fixtures_dir=tmp_path)
    r = m.invoke(model=None, messages=[{"role": "user", "content": "u"}], schema=CANDIDATES_SCHEMA, stage="lens_x")
    assert r["data"] == {"candidates": []} and r["meta"]["source"] == "fixture"
    r = m.invoke(model=None, messages=[{"role": "user", "content": "u"}], schema=SCHEMA, stage="nothing")
    assert r["data"] == {"items": []} and r["meta"]["source"] == "empty"


def test_prompt_order_document_requirements_signals_task():
    view = {"lines": [{"n": 1, "text": "Первая строка", "page": None}, {"n": 2, "text": "Вторая", "page": 2}]}
    ctx = Context(view=view, requirements=[{"id": "R-01", "kind": "functional", "line_start": 1, "line_end": 1,
                                            "summary": "кратко"}],
                  signals=[{"id": "S-01", "line": 1, "quote": "Первая", "message": "сигнал", "rule": "x"}])
    system, user = ctx.prompt("lens_analyst")
    assert "ревьюеров требований" in system
    i_doc, i_req, i_task = user.index("<документ>"), user.index("<требования>"), user.rindex("линза")
    assert i_doc < i_req < i_task
    assert "L002| [с.2] Вторая" in user


def test_verdict_rule():
    crit = {"severity": "critical", "blocks": "development"}
    majors = [{"severity": "major", "blocks": "both"}] * 3
    assert pipeline.verdict_rule([crit], "complete") == {"development": "no", "testing": "yes"}
    assert pipeline.verdict_rule(majors, "complete") == {"development": "conditional", "testing": "conditional"}
    assert pipeline.verdict_rule([], "partial") == {"development": "conditional", "testing": "conditional"}
    assert pipeline.verdict_rule([crit], "failed") == {"development": "none", "testing": "none"}


# --------------------------------------------------------------------------- конвейер на mock

def _run(tmp_path, **opts):
    out = tmp_path / "out" / "r.md"
    o = {"provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False, **opts}
    report, written = pipeline.review(OFFICIAL, out, o)
    return report, written, out


def test_mock_pipeline_end_to_end(tmp_path):
    report, written, out = _run(tmp_path)
    run = report["run"]
    assert run["status"] in ("complete", "partial")
    assert run["calls"]["total"] <= 12
    assert out.is_file() and Path(written["json"]).is_file()
    data = json.loads(Path(written["json"]).read_text(encoding="utf-8"))
    assert data["schema"] == "bcc-review/2" and data["requirements"]
    stages = Path(tmp_path / "runs" / run["run_id"] / "stages")
    for name in ("segment", "rules", "lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency",
                 "quotes", "judge", "clarify"):
        assert (stages / f"{name}.json").is_file(), name
    assert (tmp_path / "runs" / run["run_id"] / "trace.jsonl").is_file()


def test_failing_stage_does_not_break_run(tmp_path, monkeypatch):
    from bcc_review.v2.stages import lens

    def boom(ctx, name):
        if name == "risk":
            raise RuntimeError("линза упала")
        return {"candidates": []}

    monkeypatch.setattr(lens, "run_named", boom)
    report, _, out = _run(tmp_path)
    assert report["run"]["stages"]["lens_risk"] == "failed"
    assert report["run"]["status"] == "partial"
    assert any("lens_risk" in w for w in report["run"]["warnings"])
    assert out.is_file()


def test_candidate_without_quote_never_reaches_judge(tmp_path, monkeypatch):
    from bcc_review.v2.stages import judge, lens
    good = {"title": "t", "kind": "ambiguity", "criterion": "unambiguous", "severity": "major", "requirement_ids": [],
            "evidence": [{"quote": "Месяц определяется по дате совершения покупки", "line": 38}], "problem": "p",
            "scenario": "", "impact": "", "recommendation": "", "rewrite": "", "question": "", "blocks": "both"}
    bad = dict(good, title="выдумка", evidence=[{"quote": "Такой фразы в документе нет совсем", "line": 3}])
    monkeypatch.setattr(lens, "run_named", lambda ctx, name: {"candidates": [dict(good), dict(bad)]
                                                              if name == "analyst" else []})
    seen = []
    real = judge.run

    def spy(ctx, candidates):
        seen.extend(candidates)
        return real(ctx, candidates)

    monkeypatch.setattr(judge, "run", spy)
    report, _, _ = _run(tmp_path, consistency=False)
    titles = [c["title"] for c in seen]
    assert "выдумка" not in titles and "t" in titles
    assert any(r.get("reason_code") == "no_quote" for r in report["rejected"])


def test_stage_rerun_reuses_other_stages(tmp_path):
    report, _, _ = _run(tmp_path)
    src = pipeline.RunDir(tmp_path / "runs" / report["run"]["run_id"], create=False)
    out = tmp_path / "again.md"
    rep2, _ = pipeline.review(OFFICIAL, out, {"provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False},
                              reuse=src, rerun={"judge"})
    st = rep2["run"]["stage_stats"]
    assert st["segment"].get("reused") and st["lens_qa"].get("reused")
    assert not st["judge"].get("reused")
    assert rep2["run"]["calls"]["total"] <= 3


def test_offline_provider_builds_report(tmp_path):
    report, written, out = _run(tmp_path, provider="offline")
    assert report["run"]["provider"] == "offline"
    assert out.is_file()


def test_cli_routes_engine_and_help(capsys):
    from bcc_review.__main__ import _engine
    assert _engine(["--engine", "v1", "a.md", "b.md"]) == ("v1", ["a.md", "b.md"])
    assert _engine(["a.md", "b.md"]) == ("v2", ["a.md", "b.md"])


def test_raw_responses_saved_for_mock_fixtures(tmp_path):
    report, _, _ = _run(tmp_path)
    resp = tmp_path / "runs" / report["run"]["run_id"] / "responses"
    assert (resp / "segment.json").is_file() and (resp / "judge.json").is_file()
    assert isinstance(json.loads((resp / "judge.json").read_text(encoding="utf-8")), list)


def test_recorded_official_run_reproduces_verdict(tmp_path):
    """Записанные ответы живого прогона sonnet (tests/v2/fixtures/official) дают тот же вердикт без сети."""
    report, _, _ = _run(tmp_path)
    sev = [f["severity"] for f in report["findings"]]
    assert report["run"]["status"] == "complete"
    assert sev.count("critical") >= 2 and len(sev) >= 15
    assert report["verdict"]["development"] == "no"
    assert all(e.get("verified") != "missing" for f in report["findings"] for e in f.get("evidence") or [])


def test_cli_output_limit_error_is_treated_as_truncation():
    err = ProviderError("unknown", "claude -p вернул ошибку (success). [claude -p, модель haiku: API Error: Claude's "
                                   "response exceeded the 16000 output token maximum.")
    llm = client([err, {"items": ["ok"]}])
    assert llm.ask("s", "sys", "u", SCHEMA) == {"items": ["ok"]}
    assert llm.stats["expanded"] == 1


def test_fatal_provider_error_stops_further_calls():
    llm = client([ProviderError("auth", "ключ не принят"), {"items": ["never"]}])
    with pytest.raises(LLMError):
        llm.ask("a", "s", "u1", SCHEMA)
    with pytest.raises(LLMError) as e:
        llm.ask("b", "s", "u2", SCHEMA)
    assert e.value.kind == "auth" and llm.stats["calls"] == 1


def test_bad_provider_config_gives_rules_report_with_explanation(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report, _, out = _run(tmp_path, provider="anthropic")
    assert out.is_file()
    assert report["run"].get("model_error") and report["run"]["warnings"][0] == report["run"]["model_error"]


def test_acceptance_checks_linked_to_findings():
    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p.warnings = []
    extras = {"acceptance_checks": [{"row_requirement_id": "R-14"}, {"row_requirement_id": "R-15"}],
              "pair_checks": [], "glossary": []}
    kept = [{"id": "C-001", "acceptance_row": "R-14"}, {"id": "C-002"}]
    findings = [{"id": "D-01", "candidate_ids": ["C-001", "C-002"]}]
    p._link(extras, kept, findings)
    assert extras["acceptance_checks"][0]["finding_ids"] == ["D-01"]
    assert extras["acceptance_checks"][1]["finding_ids"] == []
