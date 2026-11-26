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
    assert set(out["inventory"]) == {"operations", "promises", "codes", "fields"}
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
