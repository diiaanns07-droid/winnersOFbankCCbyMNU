"""№11: режим ответов (recheck) — разбор ответов, честный пересмотр, вердикт «до / после»."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import clarify, recheck  # noqa: E402
from test_11_clarify import FIX, FakeCtx, FakeLLM  # noqa: E402


@pytest.fixture(scope="module")
def findings() -> list[dict]:
    return json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]


@pytest.fixture(scope="module")
def questions(findings) -> list[dict]:
    raw = json.loads((FIX / "clarify.json").read_text(encoding="utf-8"))
    return clarify.run(FakeCtx(FakeLLM(raw)), findings)["questions"]


# --------------------------------------------------------------------------- разбор
def test_parse_markdown_forms():
    text = """# Ответы
> комментарий Q-09: A не читается

Q-01: B
- **Q-02**: А — по дате покупки
Q-03: свой вариант ответа
  с продолжением на следующей строке
Q-04: ?
Q-5 [момент отнесения]: Г
Q-06: 2
Q-07: В
Q-08: 3 повтора с интервалом 1 минута

## Решения
- Общее решение один.
* Общее решение два.
"""
    p = recheck.parse_answers_text(text)
    a = {x["id"]: x for x in p["answers"]}
    assert "Q-09" not in a
    assert a["Q-01"]["choice"] == 1
    assert a["Q-02"]["choice"] == 0 and a["Q-02"]["comment"] == "по дате покупки"
    assert a["Q-03"]["choice"] is None and a["Q-03"]["text"] == "свой вариант ответа с продолжением на следующей строке"
    assert a["Q-04"]["choice"] is None and a["Q-04"]["text"] == ""
    assert a["Q-05"]["choice"] == 3 and a["Q-05"]["topic_hint"] == "момент отнесения"
    assert a["Q-06"]["choice"] == 1
    assert a["Q-07"]["choice"] == 1  # кириллическая «В» читается как латинская B
    assert a["Q-08"]["choice"] is None and a["Q-08"]["text"].startswith("3 повтора")
    assert p["decisions"] == ["Общее решение один.", "Общее решение два."]


@pytest.mark.parametrize("data", [
    {"Q-01": "B", "Q-02": "свой текст"},
    {"answers": {"Q-01": "B", "Q-02": "свой текст"}},
    [{"id": "Q-01", "answer": "B"}, {"id": "Q-02", "answer": "свой текст"}],
    {"Q-01": {"choice": "B"}, "Q-02": {"text": "свой текст"}},
])
def test_parse_json_forms(data, tmp_path):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for src in (data, str(path), json.dumps(data, ensure_ascii=False)):
        p = recheck.load_answers(src)
        a = {x["id"]: x for x in p["answers"]}
        assert a["Q-01"]["choice"] == 1 and a["Q-02"]["text"] == "свой текст"


def test_resolve_answers(questions):
    parsed = recheck.parse_answers_text(
        "Q-01: A\nQ-02: D\nQ-03: как обычно\nQ-04: B — с оговоркой\nQ-77: решение без вопроса\nQ-78: A\n")
    w: list[str] = []
    r = recheck.resolve_answers(questions, parsed, w)
    by = {a["question_id"]: a for a in r["answered"]}
    assert by["Q-01"]["answer"] == questions[0]["options"][0] and by["Q-01"]["choice"] == "A"
    assert "Q-02" not in by  # варианта D нет
    assert "Q-03" not in by  # расплывчатый ответ не считается
    assert by["Q-04"]["answer"].endswith("(с оговоркой)")
    assert r["decisions"] == ["решение без вопроса"]
    assert "Q-02" in r["unanswered"] and "Q-03" in r["unanswered"]
    assert len(w) >= 4


def test_topic_hint_rebinds_question(questions):
    target = questions[3]
    parsed = {"answers": [{"id": "Q-01", "topic_hint": target["topic"], "choice": None, "text": "Свой ответ",
                           "comment": ""}], "decisions": []}
    r = recheck.resolve_answers(questions, parsed)
    assert r["answered"][0]["question_id"] == target["id"]


# --------------------------------------------------------------------------- вердикт
def f(id_, sev, blocks="both"):
    return {"id": id_, "severity": sev, "blocks": blocks, "priority": 0}


def test_verdict_rule():
    assert recheck.verdict_rule([f("D-1", "critical", "development")])["development"] == "no"
    assert recheck.verdict_rule([f("D-1", "critical", "development")])["testing"] == "yes"
    assert recheck.verdict_rule([f("D-1", "critical", "testing")])["testing"] == "no"
    v = recheck.verdict_rule([f(f"D-{i}", "major") for i in range(3)])
    assert v == {"development": "conditional", "testing": "conditional", "fix_first": ["D-0", "D-1", "D-2"]}
    assert recheck.verdict_rule([f("D-1", "major"), f("D-2", "minor")])["development"] == "yes"
    assert recheck.verdict_rule([], "partial")["development"] == "conditional"
    assert recheck.verdict_rule([], "failed")["development"] == ""


# --------------------------------------------------------------------------- пересмотр
def _resp(decisions, candidates=()):
    return {"decisions": [dict({"severity": "minor", "title": "", "problem": ""}, **d) for d in decisions],
            "candidates": list(candidates)}


CAND = {"title": "Ответ противоречит примеру ответа API", "kind": "contradiction", "criterion": "set_consistent",
        "severity": "major", "requirement_ids": ["R-41"],
        "evidence": [{"quote": '{"result":"ERROR","message":"Проверьте сумму"}', "line": 171}],
        "problem": "По ответу Q-04 ошибка суммы — 400, а пример 200 содержит ERROR.", "scenario": "amount=500",
        "impact": "Тест", "recommendation": "Убрать пример", "rewrite": "", "question": "", "blocks": "testing"}
FAKE = dict(CAND, title="Выдуманная цитата", evidence=[{"quote": "нет такой строки в документе", "line": 3}])


def test_recheck_is_honest(findings, questions):
    q1 = questions[0]
    answers = f"{q1['id']}: A\n"
    resp = _resp([
        {"finding_id": q1["finding_ids"][0], "status": "resolved", "reason": "Ответ задаёт правило"},
        {"finding_id": "D-27", "status": "resolved", "reason": "не связан — должен быть проигнорирован"},
    ], [CAND, FAKE])
    ctx = FakeCtx(FakeLLM(resp))
    res = recheck.run(ctx, findings, answers, questions)
    by = {g["id"]: g["recheck"] for g in res["findings"]}
    assert by[q1["finding_ids"][0]]["status"] == "resolved"
    assert by["D-27"]["status"] == "open" and not by["D-27"]["affected"]
    assert [c["title"] for c in res["new_candidates"]] == [CAND["title"]]
    assert res["new_candidates"][0]["evidence"][0]["line_start"] == 171
    assert res["rejected"][0]["reason"] == "цитата не найдена"
    user = ctx.llm.calls[0]["user"]
    assert q1["options"][0] in user and "{{answers}}" not in user


def test_no_answers_no_call(findings, questions):
    llm = FakeLLM(_resp([]))
    res = recheck.run(FakeCtx(llm), findings, "Q-01: ?\n", questions)
    assert llm.calls == [] and all(g["recheck"]["status"] == "open" for g in res["findings"])


def _stub_judge(ctx, candidates):
    return {"findings": [{"id": f"D-{i:02d}", "candidate_ids": [c["id"]], "title": c["title"], "kind": c["kind"],
                          "criterion": c["criterion"], "severity": c["severity"], "requirement_ids": c["requirement_ids"],
                          "evidence": c["evidence"], "problem": c["problem"], "blocks": c["blocks"], "priority": 0,
                          "sources": [c.get("source", "")]} for i, c in enumerate(candidates, 1)], "rejected": []}


@pytest.fixture()
def stub_judge(monkeypatch):
    from bcc_review.v2.stages import judge
    monkeypatch.setattr(judge, "run", _stub_judge)


def test_judge_failure_falls_back(findings, questions, monkeypatch):
    from bcc_review.v2.stages import judge

    def boom(ctx, candidates):
        raise RuntimeError("judge down")
    monkeypatch.setattr(judge, "run", boom)
    ctx = FakeCtx(FakeLLM(_resp([], [CAND])))
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(ctx, report, f"{questions[0]['id']}: A")
    assert out["clarification"]["new_findings"] == ["D-29"]
    assert any("судья недоступен" in w for w in out["clarification"]["warnings"])


def test_apply_answers_changes_verdict(findings, questions, stub_judge):
    crit = [q for q in questions if any(fid in {"D-01", "D-02", "D-03", "D-04"} for fid in q["finding_ids"])]
    answers = "\n".join(f"{q['id']}: A" for q in crit)
    affected = sorted({fid for q in crit for fid in q["finding_ids"]})
    decisions = [{"finding_id": fid, "status": "resolved", "reason": "закрыто ответом"} for fid in affected]
    decisions[-1] = {"finding_id": affected[-1], "status": "changed", "reason": "частично", "severity": "minor",
                     "title": "Осталось уточнить текст"}
    ctx = FakeCtx(FakeLLM(_resp(decisions, [CAND])))
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(ctx, report, answers)
    clar = out["clarification"]
    assert clar["before"]["verdict"]["development"] == "no"
    assert clar["before"]["findings"]["critical"] == 4
    assert clar["after"]["findings"]["critical"] == 0
    assert clar["after"]["verdict"]["development"] in ("conditional", "yes")
    assert clar["resolved"] == len(affected) - 1 and clar["changed"] == 1
    new_ids = clar["new_findings"]
    assert new_ids == ["D-29"]
    by = {x["id"]: x for x in out["findings_after"]}
    assert by["D-29"]["status_after_answers"] == "new" and by["D-29"]["evidence"][0]["line_start"] == 171
    assert by[affected[-1]]["severity"] == "minor" and by[affected[-1]]["title"] == "Осталось уточнить текст"
    assert all(fid not in by for fid in affected[:-1])
    md = recheck.render_markdown(clar, out["findings_after"])
    assert "| Начинать разработку | нельзя |" in md and "До уточнения" in md and "D-29" in md


def test_general_decision_affects_major(findings, questions):
    ctx = FakeCtx(FakeLLM(_resp([{"finding_id": "D-09", "status": "resolved", "reason": "общее решение"}])))
    res = recheck.run(ctx, findings, "## Решения\n- Учитываются только покупки у торговцев.\n", questions)
    by = {g["id"]: g["recheck"] for g in res["findings"]}
    assert by["D-09"]["status"] == "resolved"
    assert not by["D-28"]["affected"]  # minor общим решением не затрагивается


def test_llm_failure_keeps_findings_open(findings, questions):
    ctx = FakeCtx(FakeLLM(exc=RuntimeError("timeout")))
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(ctx, report, f"{questions[0]['id']}: A")
    clar = out["clarification"]
    assert clar["resolved"] == 0 and clar["after"]["findings"] == clar["before"]["findings"]
    assert clar["after"]["verdict"]["development"] == "no"


def test_example_answers_file_parses():
    p = recheck.load_answers(str(ROOT / "examples" / "v2" / "answers.md"))
    assert len(p["answers"]) == 10 and all(a["topic_hint"] and a["text"] for a in p["answers"])
    assert len(p["decisions"]) == 7
    assert not any("python -m" in a["text"] for a in p["answers"])  # строки-комментарии «>» не читаются
