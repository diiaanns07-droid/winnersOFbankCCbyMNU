"""Этап «Архитектор» в каркасе №01: Context + LLMClient + mock-провайдер с записанным ответом sonnet."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "tests" / "v2" / "fixtures" / "07_mock"
DOC = ROOT / "release" / "input" / "requirements.md"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"

pytest.importorskip("bcc_review.v2.pipeline")

from bcc_review.v2 import docview, quotes  # noqa: E402
from bcc_review.v2.context import Context  # noqa: E402
from bcc_review.v2.llm import LLMClient  # noqa: E402
from bcc_review.v2.providers.mock import MockProvider  # noqa: E402
from bcc_review.v2.stages import lens, lens_architect  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    view = docview.load(str(DOC))
    seg = json.loads(SEGMENT.read_text(encoding="utf-8"))
    llm = LLMClient(MockProvider(fixtures_dir=MOCK), model="mock", provider_name="mock", sleep=lambda s: None)
    signals = [{"id": "S-01", "rule": "api.safe_method_change", "kind": "api", "line": 104, "lines": [104],
                "quote": "REST type | GET", "message": "Метод изменяет данные, но объявлен как GET.",
                "note": "Метод изменяет данные, но объявлен как GET.", "audience": ["architect"]}]
    return Context(view=view, llm=llm, requirements=seg["requirements"], signals=signals)


def test_runner_uses_own_schema():
    assert lens.schema_for("architect") is lens_architect.SCHEMA


def test_prompt_message_order_and_signals(ctx):
    system, user = ctx.prompt("lens_architect")
    assert system.strip()
    doc_at, task_at = user.find("<документ>"), user.find("## Задача: линза «Архитектор»")
    assert 0 <= doc_at < task_at, "документ — первым, задание — последним"
    assert "<требования>" in user[:task_at]


def test_run_named_postprocesses_and_keeps_inventory(ctx):
    out = lens.run_named(ctx, "architect")
    cands = out["candidates"]
    assert 1 <= len(cands) <= lens_architect.MAX_CANDIDATES
    assert all(c["source"] == "lens:architect" for c in cands)
    sev = [c["severity"] for c in cands]
    assert sev == sorted(sev, key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s])
    assert set(out["inventory"]) == {"operations", "promises", "codes", "fields", "branches"}
    reqs = {r["id"] for r in ctx.requirements}
    assert all(set(c["requirement_ids"]) <= reqs for c in cands)


def test_recorded_quotes_verified_by_docview(ctx):
    out = lens.run_named(ctx, "architect")
    bad = []
    for c in out["candidates"]:
        for e in c["evidence"]:
            m = quotes.verify_quote(ctx.view, e["quote"], line_hint=e.get("line"))
            if not m or m["verified"] not in ("exact", "normalized"):
                bad.append((e.get("line"), e["quote"]))
    assert not bad, bad


class _OverflowOnceLLM:
    """Первый вызов — переполнение вывода, как у `claude -p` на слабой модели; дальше — части ответа."""

    def __init__(self, answer: dict):
        self.answer, self.calls = answer, []

    def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
        from bcc_review.v2.llm import LLMError
        self.calls.append(user[-2000:])
        if len(self.calls) == 1:
            raise LLMError(stage, "unknown", "API Error: Claude's response exceeded the 16000 output token maximum.")
        half = len(self.calls) - 2
        cands = self.answer["candidates"][half::2]
        return {"inventory": self.answer["inventory"], "candidates": cands}


def test_output_overflow_falls_back_to_two_parts(ctx):
    answer = json.loads((MOCK / "lens_architect.json").read_text(encoding="utf-8"))
    fake = _OverflowOnceLLM(answer)
    local = Context(view=ctx.view, llm=fake, requirements=ctx.requirements, signals=ctx.signals)
    out = lens.run_named(local, "architect")
    assert len(fake.calls) == 3
    assert "Ограничение этого запроса" in fake.calls[1] and "Ограничение этого запроса" in fake.calls[2]
    assert any("двумя частями" in w for w in local.warnings)
    assert len(out["candidates"]) == min(len(answer["candidates"]), lens_architect.MAX_CANDIDATES)
    assert out["inventory"]["codes"]


def test_split_requirements_api_vs_rest(ctx):
    parts = lens_architect.split_requirements(ctx.requirements)
    assert len(parts) == 2 and set(parts[0]).isdisjoint(parts[1])
    kinds = {r["id"]: r["kind"] for r in ctx.requirements}
    assert all(kinds[i] in lens_architect.API_KINDS for i in parts[0])
    assert lens_architect.split_requirements([{"id": "R-01", "kind": "api"}, {"id": "R-02", "kind": "api"}]) == [
        ["R-01"], ["R-02"]]


def test_other_errors_are_not_swallowed(ctx):
    from bcc_review.v2.llm import LLMError

    class _Broken:
        def ask(self, stage, *a, **k):
            raise LLMError(stage, "auth", "нет ключа")

    local = Context(view=ctx.view, llm=_Broken(), requirements=ctx.requirements, signals=ctx.signals)
    with pytest.raises(LLMError):
        lens.run_named(local, "architect")


def test_fallback_stops_when_first_part_overflows_too(ctx):
    from bcc_review.v2.llm import LLMError

    class _AlwaysOverflow:
        calls = 0

        def ask(self, stage, *a, **k):
            type(self).calls += 1
            raise LLMError(stage, "unknown", "response exceeded the 16000 output token maximum")

    local = Context(view=ctx.view, llm=_AlwaysOverflow(), requirements=ctx.requirements, signals=ctx.signals)
    with pytest.raises(RuntimeError):
        lens.run_named(local, "architect")
    assert _AlwaysOverflow.calls == 2  # исходный запрос + первая часть, вторую не тратим


def test_whole_document_single_call_without_split(ctx):
    answer = json.loads((MOCK / "lens_architect.json").read_text(encoding="utf-8"))

    class _Spy:
        asks, splits = 0, 0

        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            type(self).asks += 1
            assert "Ограничение этого запроса" not in user
            return answer

        def ask_split(self, *a, **k):  # pragma: no cover - не должен вызываться
            type(self).splits += 1
            raise AssertionError("линза не делит пакет требований")

    local = Context(view=ctx.view, llm=_Spy(), requirements=ctx.requirements, signals=ctx.signals)
    out = lens.run_named(local, "architect")
    assert (_Spy.asks, _Spy.splits) == (1, 0)
    assert out["candidates"]


def test_output_limit_by_provider(ctx):
    class _L:
        def __init__(self, name):
            self.provider_name = name

    for name, want in (("claude_cli", 32000), ("gemini", 32000), ("anthropic", 32000), ("openai", 16000), ("", 16000)):
        local = Context(view=ctx.view, llm=_L(name), requirements=ctx.requirements)
        assert lens_architect.output_limit(local) == want, name


def test_branch_candidates_from_inventory(ctx):
    inv = {"branches": [
        {"operation": "m", "step": "отказ по сумме", "line": 121, "outcome": ""},
        {"operation": "m", "step": "проверка сессии", "line": 117, "outcome": ""},        # шаг не называет исход
        {"operation": "m", "step": "успех", "line": 120, "outcome": "200 {...}"}]}
    out = lens_architect.branch_candidates(inv, ctx.view, [])
    assert [c["evidence"][0]["line"] for c in out] == [121]
    c = out[0]
    assert c["title"].startswith("Ветка логики без ответа") and c["severity"] == "major"
    m = quotes.verify_quote(ctx.view, c["evidence"][0]["quote"], line_hint=121)
    assert m and m["verified"] == "exact" and m["line_start"] == 121
    view = {"lines": [{"n": 1, "text": "4. Сохранить настройку и вернуть 200."}]}
    assert lens_architect.branch_candidates(
        {"branches": [{"operation": "m", "step": "успех", "line": 1, "outcome": ""}]}, view, []) == []
    covered = [{"title": "Ветка логики без ответа: x", "evidence": [{"quote": "q", "line": 121}]}]
    assert lens_architect.branch_candidates(inv, ctx.view, covered) == []


def test_run_adds_missing_branch_candidate(ctx):
    answer = json.loads((MOCK / "lens_architect.json").read_text(encoding="utf-8"))
    answer = dict(answer, inventory=dict(answer["inventory"], branches=[
        {"operation": "m", "step": "отказ по сумме", "line": 121, "outcome": ""}]))
    answer["candidates"] = [c for c in answer["candidates"] if not c["title"].startswith("Ветка логики")][:5]

    class _One:
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            return answer

    local = Context(view=ctx.view, llm=_One(), requirements=ctx.requirements, signals=ctx.signals)
    out = lens.run_named(local, "architect")
    assert any(c["title"].startswith("Ветка логики без ответа") and c["evidence"][0]["line"] == 121
               for c in out["candidates"])
