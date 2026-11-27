"""№28 — линза «Аналитик»: critical с цитатой из раздела описания API понижается до major.

Без сети: записанные ответы haiku (tests/v2/fixtures/28_analyst — промпт v28a, отклонённый по замеру вариант с обходом
тем; для проверки постобработки важны только кандидаты) и настоящие документы (docview).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from bcc_review.v2 import docview  # noqa: E402
from bcc_review.v2.stages import lens_analyst as A  # noqa: E402

FIX = ROOT / "tests" / "v2" / "fixtures" / "28_analyst"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _run(view: dict, answer: dict) -> list[dict]:
    """Как `lens_analyst.run`: постобработка с флагами API по документу."""
    cands = answer["candidates"]
    return A.postprocess(cands, mature=A.maturity(view)["mature"],
                         api_flags=A.touches_api(view, cands, A.api_lines(view)))


def test_api_lines_are_rest_part():
    view = docview.load(OFFICIAL)
    api = A.api_lines(view)
    assert 118 in api and 163 in api  # логика метода, статусы
    assert not ({23, 38, 39, 40, 46, 49, 64} & api)  # цели, правила, НФТ, данные, приёмка


def test_api_side_critical_is_major_on_clean_doc():
    """grace_clean (чистое ТЗ №18): «шаг 3 метода берёт платежи после даты выписки ↔ платёж уменьшает сумму» —
    ложный critical haiku (тот же шаблон у №05 на v23). Цитата шага логики метода → major с подсказкой судье."""
    view = docview.load(OPEN2 / "grace_clean" / "source.md")
    out = _run(view, _json(FIX / "grace_clean.haiku-v28a.json"))
    assert not [c for c in out if c["severity"] == "critical"]
    hinted = [c for c in out if c.get("severity_hint") == "critical"]
    assert len(hinted) == 1 and hinted[0]["severity"] == "major"


@pytest.mark.parametrize("name", ["official", "official_r2"])
def test_official_month_conflict_stays_critical(name):
    """Официальный: «по дате совершения или проведения» (правило ↔ критерий приёмки, без API) — critical (К1)."""
    view = docview.load(OFFICIAL)
    out = _run(view, _json(FIX / f"{name}.haiku-v28a.json"))
    crit = [c for c in out if c["severity"] == "critical"]
    assert crit and all(64 in [e.get("line") for e in c["evidence"]] or 40 in [e.get("line") for e in c["evidence"]]
                        for c in crit)
    assert any(64 in [e.get("line") for e in c["evidence"]] for c in crit)


def test_no_document_means_old_behaviour():
    d = _json(FIX / "grace_clean.haiku-v28a.json")
    old = A.postprocess(d["candidates"], mature=False)
    assert [c["severity"] for c in old].count("critical") == 1


def test_touches_api_uses_verified_line():
    """Строка модели сбита (999) — раздел берётся по найденной цитате."""
    view = docview.load(OFFICIAL)
    quote = view["lines"][117]["text"][:60]
    flags = A.touches_api(view, [{"evidence": [{"quote": quote, "line": 999}]},
                                 {"evidence": [{"quote": view["lines"][37]["text"][:60], "line": 120}]}],
                          A.api_lines(view))
    assert flags == [True, False]


# ---------------------------------------------------------------- два просмотра

def _cand(title: str, sev: str, lines: list[int], kind: str = "ambiguity") -> dict:
    return {"title": title, "kind": kind, "criterion": "unambiguous", "severity": sev, "requirement_ids": [],
            "evidence": [{"quote": f"цитата {n}", "line": n} for n in lines], "problem": "п", "scenario": "с",
            "impact": "и", "recommendation": "р", "rewrite": "", "question": "", "blocks": "both"}


def test_merge_views_keeps_agreed_severity_and_demotes_single():
    a = [_cand("общее", "major", [38]), _cand("только первый", "major", [40])]
    b = [_cand("общее иначе", "major", [38, 64]), _cand("только второй", "critical", [23, 46], "event_conflict")]
    out = A.merge_views(a, b, [{38}, {40}], [{38, 64}, {23, 46}])
    assert [(c["title"], c["severity"], c["views"]) for c in out] == [
        ("общее", "major", 2), ("только первый", "minor", 1), ("только второй", "minor", 1)]
    assert out[2]["severity_hint"] == "critical"


class _Ctx:
    def __init__(self, view, llm=object(), options=None):
        self.view, self.llm, self.options, self.warnings = view, llm, options or {}, []

    def warn(self, msg):
        self.warnings.append(msg)


def _fake_lens_run(answers: dict):
    """Ответ по просмотру: второй просмотр узнаётся по клиенту модели (`_SecondView`)."""
    def run(ctx, name):
        key = "second" if isinstance(ctx.llm, A._SecondView) else "first"
        got = answers[key]
        if isinstance(got, Exception):
            raise got
        return {"candidates": [dict(c) for c in got]}
    return run


def test_run_two_views_on_immature_document():
    view = docview.load(OFFICIAL)
    q38, q64 = view["lines"][37]["text"][:50], view["lines"][63]["text"][:40]
    first = [{**_cand("месяц", "critical", [38, 64], "event_conflict"),
              "evidence": [{"quote": q38, "line": 38}, {"quote": q64, "line": 64}]}, _cand("редкое", "major", [29])]
    second = [{**_cand("месяц-2", "critical", [38], "event_conflict"),
               "evidence": [{"quote": q38, "line": 38}, {"quote": q64, "line": 64}]}]
    out = A.run(_Ctx(view), lens_run=_fake_lens_run({"first": first, "second": second}))
    assert [(c["title"], c["severity"]) for c in out["candidates"]] == [("месяц", "critical"), ("редкое", "minor")]
    assert out["views"] == {"first": 2, "second": 1, "agreed": 1}


def test_run_one_view_on_mature_document():
    from evaluation.v2 import corpus as cp
    path = next(c["path"] for c in cp.select_cases("md", None) if c["case_id"] == "cardblock.base")
    view = docview.load(path)
    calls = []

    def run(ctx, name):
        calls.append(type(ctx.llm).__name__)
        return {"candidates": []}
    out = A.run(_Ctx(view), lens_run=run)
    assert calls == ["object"] and "views" not in out


def test_run_second_view_failure_keeps_first():
    view = docview.load(OFFICIAL)
    ctx = _Ctx(view)
    out = A.run(ctx, lens_run=_fake_lens_run({"first": [_cand("одно", "major", [29])], "second": RuntimeError("сбой")}))
    assert [(c["title"], c["severity"]) for c in out["candidates"]] == [("одно", "major")]
    assert ctx.warnings and "не удался" in ctx.warnings[0]


def test_run_both_views_fail_raises():
    with pytest.raises(RuntimeError):
        A.run(_Ctx(docview.load(OFFICIAL)), lens_run=_fake_lens_run({"first": RuntimeError("a"), "second": RuntimeError("b")}))


def test_second_view_changes_prompt_and_passes_attributes():
    class LLM:
        stats = {"calls": 0}

        def ask(self, stage, system, user, schema, **kw):
            return {"user": user}
    v = A._SecondView(LLM())
    assert v.ask("lens_analyst", "s", "задание", {})["user"].endswith(A.SECOND_VIEW)
    assert v.stats == {"calls": 0}

@pytest.mark.parametrize(
    ("provider", "model", "options", "expected_calls"),
    [
        ("mock", None, {}, 1),
        ("gemini", "gemini-3.6-flash", {}, 2),
        ("gemini", "gemini-3.6-flash", {"passes": 2}, 1),
        ("claude_cli", "sonnet", {"analyst_passes": 1}, 1),
    ],
)
def test_analyst_call_count_in_combined_pipeline(monkeypatch, provider, model, options, expected_calls):
    from types import SimpleNamespace

    monkeypatch.delenv("BCC_ANALYST_PASSES", raising=False)
    llm = SimpleNamespace(provider_name=provider, model=model)
    ctx = _Ctx(docview.load(OFFICIAL), llm=llm, options=options)
    calls = []

    def review(ctx, name):
        calls.append(name)
        return {"candidates": []}

    result = A.run(ctx, lens_run=review)
    assert calls == ["analyst"] * expected_calls
    assert result["passes"] == expected_calls
