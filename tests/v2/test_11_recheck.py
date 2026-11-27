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
        "problem": "По ответу Q-01 ошибка суммы — 400, а пример 200 содержит ERROR.", "scenario": "amount=500",
        "impact": "Тест", "recommendation": "Убрать пример", "rewrite": "", "question": "", "blocks": "testing"}
FAKE = dict(CAND, title="Выдуманная цитата", evidence=[{"quote": "нет такой строки в документе", "line": 3}])


def test_recheck_is_honest(findings, questions):
    q1 = questions[0]
    answers = f"{q1['id']}: A\n"
    resp = _resp([
        {"finding_id": q1["finding_ids"][0], "status": "resolved", "by": [q1["id"]], "reason": "Ответ задаёт правило"},
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
    q_of = {fid: q["id"] for q in crit for fid in q["finding_ids"]}
    decisions = [{"finding_id": fid, "status": "resolved", "by": [q_of[fid]], "reason": "закрыто ответом"}
                 for fid in affected]
    decisions[-1] = {"finding_id": affected[-1], "status": "changed", "by": [q_of[affected[-1]]], "reason": "частично",
                     "severity": "minor", "title": "Осталось уточнить текст"}
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


def test_question_closed_by_decision_is_not_unanswered(findings, questions, stub_judge):
    q = next(x for x in questions if len(x["finding_ids"]) == 1 and not x["blocking"])
    fid = q["finding_ids"][0]
    ctx = FakeCtx(FakeLLM(_resp([{"finding_id": fid, "status": "resolved", "by": ["Решение-1"],
                                  "reason": "общее решение"}])))
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    clar = recheck.apply_answers(ctx, report, "## Решения\n- Учитываются только покупки у торговцев.\n")["clarification"]
    assert q["id"] in clar["closed_by_decisions"] and q["id"] not in clar["unanswered"]


def test_general_decision_affects_major(findings, questions):
    ctx = FakeCtx(FakeLLM(_resp([{"finding_id": "D-09", "status": "resolved", "reason": "закрыто, Решение-1"}])))
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


# --------------------------------------------------------------------------- третья волна: закрывает только прямой ответ
def test_resolved_requires_named_answer(findings, questions):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "resolved", "by": [], "reason": "Владелец ответил"}])
    res = recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q1['id']}: A\n", questions)
    rc = {g["id"]: g["recheck"] for g in res["findings"]}[fid]
    assert rc["status"] == "open" and "не назван ответ" in rc["reason"]


def test_resolved_by_unknown_answer_stays_open(findings, questions):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "changed", "by": ["Q-77", "Решение-3"], "reason": "частично",
                   "severity": "minor"}])
    res = recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q1['id']}: A\n", questions)
    rc = {g["id"]: g["recheck"] for g in res["findings"]}[fid]
    assert rc["status"] == "open" and rc["severity_after"] == rc["severity_before"]


def test_closing_answer_is_recorded(findings, questions):
    q1, q2 = questions[0], questions[1]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "resolved", "by": ["q-" + q2["id"][2:].lstrip("0"), "решение 1"],
                   "reason": "правило задано"}])
    answers = f"{q1['id']}: A\n{q2['id']}: B\n\n## Решения\n- Общее правило.\n"
    res = recheck.run(FakeCtx(FakeLLM(resp)), findings, answers, questions)
    rc = {g["id"]: g["recheck"] for g in res["findings"]}[fid]
    assert rc["status"] == "resolved"
    assert rc["answer_ids"] == [q2["id"], "Решение-1"] and rc["question_ids"] == [q2["id"]]
    assert q1["id"] in rc["linked_question_ids"]


def test_by_label_from_reason_is_accepted(findings, questions):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "resolved", "reason": f"Ответ {q1['id']} задаёт правило"}])
    res = recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q1['id']}: A\n", questions)
    assert {g["id"]: g["recheck"] for g in res["findings"]}[fid]["status"] == "resolved"


def test_schema_requires_by():
    item = recheck.SCHEMA["properties"]["decisions"]["items"]
    assert "by" in item["required"] and item["properties"]["by"]["type"] == "array"


def test_conflicting_answers_keep_defect_open(findings, questions, stub_judge):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "resolved", "by": [q1["id"]],
                   "conflicting_answers": [q1["id"], "Решение-1"], "reason": "ответы расходятся"}])
    answers = f"{q1['id']}: A\n\n## Решения\n- Противоположное правило.\n"
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), report, answers)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == fid)
    assert ch["status"] == "open" and "противоречат" in ch["reason"]
    assert clar["answer_conflicts"] == [{"finding_id": fid, "answers": [q1["id"], "Решение-1"], "reason": ch["reason"]}]
    assert "противоречат друг другу" in recheck.render_markdown(clar)


def test_new_candidate_repeating_old_defect_is_rejected(findings, questions):
    q1 = questions[0]
    old = next(f for f in findings if len({e["line_start"] for e in f["evidence"]}) >= 2)
    e1, e2 = old["evidence"][0], old["evidence"][1]
    twin = dict(CAND, title="Тот же конфликт заново", evidence=[{"quote": e1["quote"], "line": e1["line_start"]},
                                                                  {"quote": e2["quote"], "line": e2["line_start"]}])
    res = recheck.run(FakeCtx(FakeLLM(_resp([], [twin, CAND]))), findings, f"{q1['id']}: A\n", questions)
    assert [c["title"] for c in res["new_candidates"]] == [CAND["title"]]
    assert any(r["reason"].startswith("повторяет дефект") for r in res["rejected"])


def test_single_line_twin_needs_same_essence(findings):
    old = next(f for f in findings if f["id"] == "D-04")
    ev = [{"line_start": old["evidence"][0]["line_start"]}]
    assert recheck.duplicate_of(ev, [old], "Ответ противоречит примеру ответа API") == ""
    assert recheck.duplicate_of(ev, [old], old["title"]) == "D-04"


def test_partial_answer_keeps_critical_conflict(findings, questions):
    crit = next(f for f in findings if f["severity"] == "critical" and f["kind"] in clarify.CONFLICT_KINDS)
    q = next(x for x in questions if crit["id"] in x["finding_ids"])
    resp = _resp([{"finding_id": crit["id"], "status": "changed", "by": [q["id"]], "severity": "major",
                   "reason": "закрыта только одна граница", "title": "Осталась верхняя граница"}])
    res = recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q['id']}: A\n", questions)
    rc = {g["id"]: g["recheck"] for g in res["findings"]}[crit["id"]]
    assert rc["status"] == "changed" and rc["severity_after"] == "critical"


def test_reason_without_line_codes(findings, questions):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "resolved", "by": [q1["id"]],
                   "reason": f"{q1['id']} задаёт правило; критерий L064 переписывается (L171)."}])
    rc = {g["id"]: g["recheck"] for g in recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q1['id']}: A\n",
                                                     questions)["findings"]}[fid]
    assert "L064" not in rc["reason"] and "L171" not in rc["reason"] and q1["id"] in rc["reason"]


def test_others_only_closures_count(findings, questions):
    q1 = questions[0]
    linked = set(q1["finding_ids"])
    other = next(f for f in findings if f["severity"] == "major" and f["id"] not in linked
                 and not any(f["id"] in q["finding_ids"] for q in questions[:1]))
    minor = next(f for f in findings if f["severity"] == "minor")
    third = next(f for f in findings if f["severity"] == "major" and f["id"] not in linked | {other["id"]})
    resp = _resp([{"finding_id": other["id"], "status": "resolved", "by": ["Решение-1"], "reason": "закрыто"},
                  {"finding_id": third["id"], "status": "open", "reason": "не касается"},
                  {"finding_id": minor["id"], "status": "resolved", "by": ["Решение-1"], "reason": "minor"}])
    llm = FakeLLM(resp)
    res = recheck.run(FakeCtx(llm), findings, f"{q1['id']}: A\n\n## Решения\n- Правило.\n", questions)
    rc = {g["id"]: g["recheck"] for g in res["findings"]}
    assert rc[other["id"]]["status"] == "resolved" and rc[other["id"]]["affected"]
    assert not rc[third["id"]]["affected"]  # «open» по дефекту вне вопросов не превращает его в затронутый
    assert rc[minor["id"]]["status"] == "open" and not rc[minor["id"]]["affected"]
    assert other["title"] in llm.calls[0]["user"] and minor["title"] not in llm.calls[0]["user"].split("<остальные_дефекты>")[1]


def test_decisions_only_make_one_call(findings, questions):
    target = next(f for f in findings if f["severity"] == "major")
    llm = FakeLLM(_resp([{"finding_id": target["id"], "status": "resolved", "by": ["Решение-1"], "reason": "ok"}]))
    res = recheck.run(FakeCtx(llm), findings, "## Решения\n- Общее правило для всех.\n", questions)
    assert len(llm.calls) == 1
    assert {g["id"]: g["recheck"] for g in res["findings"]}[target["id"]]["status"] == "resolved"


def test_topic_binding_uses_answer_text():
    qs = [{"id": "Q-01", "topic": "Повторное уведомление после смены лимита", "finding_ids": ["D-01"],
           "question": "Отправлять ли второе уведомление в месяце после смены лимита?",
           "options": ["Нет, одно в месяц", "Да, после каждой смены"]},
          {"id": "Q-02", "topic": "Возврат после отправленного уведомления", "finding_ids": ["D-02"],
           "question": "Уменьшает ли возврат покупки сумму месяца, если уведомление уже отправлено?",
           "options": ["Уменьшает, уведомление не отзывается", "Не уменьшает"]}]
    text = ("Q-05 [возвраты и повторное уведомление]: Возврат покупки уменьшает сумму месяца исходной покупки, "
            "уже отправленное уведомление не отзывается.\n"
            "Q-06 [лимит уведомлений при изменении лимита]: Не более одного уведомления в месяц, в том числе "
            "после смены лимита.\n")
    res = recheck.resolve_answers(qs, recheck.load_answers(text))
    got = {a["question_id"]: a["answer"] for a in res["answered"]}
    assert got["Q-02"].startswith("Возврат покупки") and got["Q-01"].startswith("Не более одного")


def test_empty_reason_is_filled_by_status(findings, questions):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "changed", "by": [q1["id"]], "reason": "", "severity": "major"}])
    rc = {g["id"]: g["recheck"] for g in recheck.run(FakeCtx(FakeLLM(resp)), findings, f"{q1['id']}: A\n",
                                                     questions)["findings"]}[fid]
    assert rc["status"] == "changed" and rc["reason"] == f"частично снят ответом {q1['id']}"


def test_answer_clash_from_reason_only(findings, questions, stub_judge):
    q1 = questions[0]
    fid = q1["finding_ids"][0]
    resp = _resp([{"finding_id": fid, "status": "open", "by": [], "conflicting_answers": [],
                   "reason": f"{q1['id']} задаёт одно значение, а Решение-1 — другое: ответы противоречат друг другу."}])
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), report,
                                 f"{q1['id']}: A\n\n## Решения\n- Другое правило.\n")["clarification"]
    assert [c["finding_id"] for c in clar["answer_conflicts"]] == [fid]
    # «противоречит документу» с одним ответом — не противоречие ответов
    resp2 = _resp([{"finding_id": fid, "status": "open", "by": [], "reason": f"{q1['id']} противоречит пункту документа."}])
    clar2 = recheck.apply_answers(FakeCtx(FakeLLM(resp2)), report, f"{q1['id']}: A\n")["clarification"]
    assert clar2["answer_conflicts"] == []


def test_new_conflict_must_name_an_answer(findings, questions):
    """Новый конфликт от ответа — ответ против места документа: без названного ответа он не проверяем."""
    q1 = questions[0]
    anon = dict(CAND, title="Пример успешного ответа не совпадает с описанием полей", scenario="amount=500",
                problem="Пример расходится с таблицей полей.",
                evidence=[{"quote": '{"result":"OK","amount":"50000","enabled":"1"}', "line": 167}])
    res = recheck.run(FakeCtx(FakeLLM(_resp([], [anon, CAND]))), findings, f"{q1['id']}: A\n", questions)
    assert [c["title"] for c in res["new_candidates"]] == [CAND["title"]]
    assert any(r["reason"] == "не назван ответ, с которым расходится документ" for r in res["rejected"])
    assert res["new_candidates"][0]["answer_refs"][0]["id"] == q1["id"]
    assert res["new_candidates"][0]["answer_refs"][0]["text"] == q1["options"][0]


def test_judge_sees_owner_answer_of_new_conflict(findings, questions, monkeypatch):
    """Судья новых конфликтов видит текст ответа (вторую сторону), а дефект — какой ответ его породил."""
    from bcc_review.v2.stages import judge
    seen: list[dict] = []

    def spy(ctx, candidates):
        seen.extend(candidates)
        return _stub_judge(ctx, candidates)
    monkeypatch.setattr(judge, "run", spy)
    q1 = questions[0]
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(FakeCtx(FakeLLM(_resp([], [CAND]))), report, f"{q1['id']}: A")
    assert seen and seen[0]["problem"].startswith("Решение владельца, которое будет вписано в документ:")
    assert q1["options"][0][:40] in seen[0]["problem"]
    new = [f for f in out["findings_after"] if f.get("status_after_answers") == "new"]
    assert new and new[0]["answer_ids"] == [q1["id"]]
    assert not new[0]["problem"].startswith("Решение владельца")  # служебная подсказка судье не идёт в отчёт


def test_judge_tail_about_missing_quote_is_dropped(findings, questions, monkeypatch):
    from bcc_review.v2.stages import judge

    def tail(ctx, candidates):
        res = _stub_judge(ctx, candidates)
        res["findings"][0]["problem"] = ("После ответа Q-01: стр. 180 даёт тело 400 без поля result, а стр. 155 его "
                                         "требует. Ссылка на «» в кандидате в документе не найдена, поэтому опора "
                                         "только на стр. 155.")
        return res
    monkeypatch.setattr(judge, "run", tail)
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(FakeCtx(FakeLLM(_resp([], [CAND]))), report, f"{questions[0]['id']}: A")
    new = [f for f in out["findings_after"] if f.get("status_after_answers") == "new"][0]
    assert new["problem"] == "После ответа Q-01: стр. 180 даёт тело 400 без поля result, а стр. 155 его требует."


def test_judge_rewrite_into_old_defect_is_rejected(findings, questions, monkeypatch):
    """Судья переписал кандидата в прежний дефект (тот же предмет на тех же строках) — это не новый конфликт."""
    from bcc_review.v2.stages import judge
    old = next(f for f in findings if len({e["line_start"] for e in f["evidence"]}) >= 2)

    def rewrite(ctx, candidates):
        res = _stub_judge(ctx, candidates)
        res["findings"][0].update(title=old["title"], evidence=[dict(e) for e in old["evidence"]])
        return res
    monkeypatch.setattr(judge, "run", rewrite)
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = recheck.apply_answers(FakeCtx(FakeLLM(_resp([], [CAND]))), report, f"{questions[0]['id']}: A")
    assert out["clarification"]["new_findings"] == []
    assert any(r["reason"] == f"повторяет дефект {old['id']}" for r in out["rejected_after"])
