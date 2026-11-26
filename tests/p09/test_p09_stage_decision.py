"""Охват по этапу, нашедшему замечание, и закрытие внесённым решением (стык с --answers движка и №08).

Решение закрывает замечание только вместе с правкой, которая заменила опорный фрагмент и есть в новой
редакции, при завершённом этапе-нашедшем и без «issue» на сторонах. Ответ без правки, правка в
другом месте или упавший этап — «нужно подтверждение»."""

import pytest

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    CONFLICT_QUOTES,
    F2,
    F2_FIXED,
    F4,
    F4_FIXED,
    QUESTION_Q1,
    assert_partition,
    by_old,
    check,
    document,
    ev,
    replace,
    report,
    requirements,
    v1_paras,
    v1_report,
)


def _prev(stage="cross"):
    prev = v1_report(names=("conflict",), questions=[QUESTION_Q1])
    prev["findings"][0]["stage"] = stage
    prev["checks"] = [dict(c, status="unknown", finding_ids=[]) for c in prev["checks"]]  # как у движка без правил
    return prev


def _decision(
    prev, old=CONFLICT_QUOTES[1], new="следующее достижение вызывает push, если в этом месяце push ещё не был"
):
    e = ev(prev["document"], old)
    return {
        "question_id": "Q-001",
        "source_sha256": prev["document"]["id"],
        "answer": "Лимит одного push в месяц сохраняется",
        "edits": [dict(e, old=old, new=new)],
    }


def _cur(prev, mapping, *, decision=None, checks=(), stages=None, status="partial", warnings=()):
    paras = replace(v1_paras(), mapping)
    doc = document(paras, warnings=warnings)
    rep = report(
        doc,
        requirements(doc, paras),
        [],
        checks=list(checks),
        status=status,
        run_id="run-2",
        decisions=[decision] if decision else [],
    )
    rep["run"]["stages"] = stages or [
        {"name": "individual", "status": "failed", "calls": 1, "cache_hits": 0, "reason": "модель не ответила"},
        {"name": "cross", "status": "ok", "calls": 1, "cache_hits": 0, "reason": None},
    ]
    rep["run"]["incomplete_stages"] = [st["name"] for st in rep["run"]["stages"] if st["status"] != "ok"]
    return rep


NEW_F4 = F4.replace(CONFLICT_QUOTES[1], "следующее достижение вызывает push, если в этом месяце push ещё не был")


def test_applied_decision_on_anchor_closes_when_finding_stage_completed():
    prev = _prev()
    cur = _cur(prev, {F4: NEW_F4}, decision=_decision(prev))
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    status, e = by_old(diff)["F-1"]
    assert status == "resolved" and e["proof"]["kind"] == "decision_applied" and e["proof"]["decision"] == "Q-001"
    assert (
        "этап cross новой редакции завершён" in e["reason"] and "отдельной перепроверки сценария не было" in e["reason"]
    )
    assert any("ещё не был" in x["quote"] for x in e["evidence"])
    assert e["decision_refs"][0]["touches_anchor_of"] == ["F-1"] and e["decision_refs"][0]["edits_applied"] is True


def test_failed_finding_stage_blocks_closure():
    prev = _prev(stage="individual")
    cur = _cur(prev, {F4: NEW_F4}, decision=_decision(prev))
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "run_incomplete"
    assert "Этап individual" in e["reason"] and "модель не ответила" in e["reason"]


def test_partial_read_blocks_closure_even_with_decision():
    prev = _prev()
    lost = {"code": "partial_read", "message": "страница 3 не прочитана"}
    cur = _cur(prev, {F4: NEW_F4}, decision=_decision(prev), warnings=[lost])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "run_incomplete" and "прочитана не полностью" in e["reason"]


def test_answer_without_edit_does_not_close():
    prev = _prev()
    d = _decision(prev)
    d.pop("edits")
    cur = _cur(prev, {F4: F4_FIXED}, decision=d)
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["decision_refs"][0]["id"] == "Q-001"  # связь через вопрос видна


def test_edit_elsewhere_does_not_close():
    """Решение внесено, но правило в другом пункте (Ф-2), а противоречие Ф-3/Ф-4 в тексте не тронуто."""
    prev = _prev()
    tz = "по дате совершения покупки в Алматы"
    d = _decision(prev, old=tz, new="по дате совершения покупки по времени Алматы")
    cur = _cur(prev, {F2: F2.replace(tz, "по дате совершения покупки по времени Алматы")}, decision=d)
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert e["decision_refs"][0]["touches_anchor_of"] == []


def test_edit_not_applied_in_new_edition_does_not_close():
    """Решение с правкой есть, но новая редакция содержит другой текст Ф-4."""
    prev = _prev()
    cur = _cur(prev, {F4: F4_FIXED}, decision=_decision(prev))
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["decision_refs"][0]["edits_applied"] is False


def test_issue_on_side_beats_decision():
    prev = _prev()
    bad = check("R-4", "correct", "issue", finding_ids=["G-7"])
    cur = _cur(prev, {F4: NEW_F4}, decision=_decision(prev), checks=[bad])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_failed"


@pytest.mark.parametrize("stage,expected", [("cross", "resolved"), ("individual", "unassessed")])
def test_simple_defect_follows_its_own_stage(stage, expected):
    """Ф-2 исправлен и проверен «pass»; прогон partial из-за другого этапа не мешает, своего — мешает."""
    prev = v1_report(names=("tz",))
    prev["findings"][0]["stage"] = stage
    cur = _cur(prev, {F2: F2_FIXED}, checks=[check("R-2", "unambiguous", "pass")])
    assert by_old(compare_reports(prev, cur))["F-1"][0] == expected
