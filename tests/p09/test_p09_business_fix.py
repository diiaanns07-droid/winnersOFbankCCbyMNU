"""Готовность 2: одна бизнес-правка закрывает первый дефект и оставляет второй.
Принятое решение без новой редакции и второй прогон с техническим сбоем не закрывают дефект."""

import pytest

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    B,
    CONFLICT_QUOTES,
    F2,
    F2_FIXED,
    F4,
    F4_FIXED,
    FIX_QUOTE,
    V1_IDS,
    WITNESS_INPUT,
    assert_partition,
    assert_valid_report,
    by_old,
    check,
    clone,
    document,
    issue_checks,
    make_findings,
    replace,
    report,
    requirements,
    v1_paras,
    v1_report,
)

IDS = {k: v.replace("R", "S") for k, v in V1_IDS.items()}
QUESTION = {
    "id": "Q-001",
    "finding_ids": ["F-1"],
    "prompt": "Сбрасывает ли смена порога месячный лимит push?",
    "options": ["Да", "Нет"],
    "affected_req_ids": ["R-3", "R-4"],
}


def _fixed_paras():
    return [(s, sid, t, rid.replace("R", "S")) for s, sid, t, rid in replace(v1_paras(), {F4: F4_FIXED})]


def _scenario_checks(doc, scenario=WITNESS_INPUT):
    return [
        check(
            "S-3",
            "correct",
            "pass",
            reason="Один исход: повторного push нет",
            source="diff_recheck",
            scenario=scenario,
            doc=doc,
            quotes=[CONFLICT_QUOTES[0]],
        ),
        check(
            "S-4",
            "correct",
            "pass",
            reason="Ф-4 ограничен месячным лимитом",
            source="diff_recheck",
            scenario=scenario,
            doc=doc,
            quotes=[FIX_QUOTE],
        ),
    ]


def _current(extra=(), status="complete", names=("tz", "nfr", "read", "units"), **over):
    paras = _fixed_paras()
    doc = document(paras)
    fs = make_findings(doc, IDS, names, prefix="G", **over)
    checks = issue_checks(fs) + [c(doc) if callable(c) else c for c in extra]
    return report(doc, requirements(doc, paras), fs, checks=checks, status=status, run_id="run-2")


def test_business_fix_closes_conflict_and_keeps_timezone_defect():
    prev = v1_report()
    cur = _current(extra=[lambda d: _scenario_checks(d)[0], lambda d: _scenario_checks(d)[1]])
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    status, e = st["F-1"]
    assert status == "resolved" and e["status_ru"] == "исправлено в тексте"
    assert e["proof"]["kind"] == "conflict_reconciled" and e["proof"]["check_refs"] == ["S-3/correct", "S-4/correct"]
    assert e["proof"]["scenario"] == WITNESS_INPUT
    assert any(x["quote"] == FIX_QUOTE for x in e["evidence"])
    assert {x["quote"] for x in e["old_evidence"]} == set(CONFLICT_QUOTES)
    assert e["view"]["old_quote"] == CONFLICT_QUOTES[1]  # изменившийся фрагмент Ф-4
    assert e["view"]["new_quote"] == FIX_QUOTE
    assert "убрано «независимо от истории предыдущей настройки»" in e["view"]["behavior_change"]
    assert st["F-2"][0] == "persisting" and st["F-2"][1]["status_ru"] == "сохранилось"
    assert {k for k, _ in st.values()} == {"resolved", "persisting"}
    assert diff["introduced"] == [] and diff["unassessed"] == []
    assert diff["impacted_req_ids"] == ["S-4"]
    cur["diff"] = diff  # стык: отчёт с вложенным Diff остаётся валидным
    assert_valid_report(cur)


def test_accepted_answer_without_new_edition_does_not_close():
    """Ответ по --answers при прежнем тексте: «нужно подтверждение», обе опоры из одного текста."""
    prev = v1_report(questions=[QUESTION])
    cur = clone(prev)
    cur["run"]["run_id"] = "run-2"
    cur["findings"] = make_findings(cur["document"], V1_IDS, ("tz", "nfr", "read", "units"), prefix="G")
    cur["decisions"] = [
        {
            "question_id": "Q-001",
            "source_sha256": prev["document"]["id"],
            "answer": "Лимит одного push за календарный месяц главнее смены порога",
        }
    ]
    # даже «pass» со сценарием, выставленный по ответу, не заменяет правку текста
    cur["checks"] = issue_checks(cur["findings"]) + [
        check("R-3", "correct", "pass", scenario=WITNESS_INPUT),
        check("R-4", "correct", "pass", scenario=WITNESS_INPUT),
    ]
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["status_ru"] == "нужно подтверждение"
    assert e["reason_code"] == "answer_only" and "Q-001" in e["reason"]
    assert e["decision_refs"][0]["id"] == "Q-001" and e["view"]["decision_ref"]["id"] == "Q-001"
    assert e["decision_refs"][0]["answered_on"] == "previous"
    assert [x["quote"] for x in e["old_evidence"]] == CONFLICT_QUOTES
    assert [x["quote"] for x in e["evidence"]] == CONFLICT_QUOTES  # опора «новой» редакции та же
    assert e["recheck"]["scenario"] == WITNESS_INPUT
    assert not diff["resolved"]


def test_answer_with_finding_still_reported_is_persisting_with_note():
    prev = v1_report(questions=[QUESTION])
    cur = clone(prev)
    cur["decisions"] = [{"question_id": "Q-001", "source_sha256": prev["document"]["id"], "answer": "Ф-3 главнее"}]
    diff = compare_reports(prev, cur)
    status, e = by_old(diff)["F-1"]
    assert status == "persisting" and "формулировка в документе прежняя" in e["reason"]
    assert e["view"]["decision_ref"]["id"] == "Q-001"


def test_decision_edit_not_applied_is_reported():
    """Решение с правкой есть, но в новой редакции правили другое место: правка не внесена."""
    prev = v1_report(questions=[QUESTION], names=("conflict",))
    paras = replace(v1_paras(), {F2: F2_FIXED})
    doc = document(paras)
    f4 = next(b for b in prev["document"]["blocks"] if F4 in b["text"])
    dec = {
        "question_id": "Q-001",
        "source_sha256": prev["document"]["id"],
        "answer": "Ф-3 главнее",
        "edits": [{"block_id": f4["id"], "start": 5, "end": 5 + len(F4), "old": F4, "new": F4_FIXED}],
    }
    cur = report(doc, requirements(doc, paras), [], decisions=[dec], run_id="run-2")
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert e["decision_refs"][0]["edits_applied"] is False and "в текст оно не внесено" in e["reason"]


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_technical_failure_of_second_run_closes_nothing(status):
    prev = v1_report()
    names = () if status == "failed" else ("tz",)
    cur = _current(
        extra=[lambda d: _scenario_checks(d)[0], lambda d: _scenario_checks(d)[1]], status=status, names=names
    )
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert diff["resolved"] == []
    st = by_old(diff)
    assert st["F-1"][0] == "unassessed" and st["F-1"][1]["reason_code"] == "run_incomplete"
    assert f"«{status}»" in st["F-1"][1]["reason"] and "сбой этапа cross" in st["F-1"][1]["reason"]
    if status == "partial":
        assert st["F-2"][0] == "persisting"  # найденное в неполном прогоне всё равно сохранилось
    assert any(w["code"] == "current_incomplete" for w in diff["warnings"])


def test_silence_without_recheck_is_not_a_closure():
    diff = compare_reports(v1_report(), _current())
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert "S-3/correct" in e["reason"] and e["reason"].startswith("Текст в месте опоры изменён")
    assert e["recheck"]["stage"] == "diff_recheck" and e["recheck"]["new_req_ids"] == ["S-3", "S-4"]
    assert e["recheck"]["scenario"] == WITNESS_INPUT


def _broken_evidence(doc):
    c = _scenario_checks(doc)[1]
    c["evidence"][0]["start"] += 1
    return c


@pytest.mark.parametrize(
    "second",
    [
        lambda d: _scenario_checks(d, scenario="Клиент меняет порог дважды за день")[1],  # другой сценарий
        lambda d: check("S-4", "correct", "pass"),  # «pass» без сценария
        _broken_evidence,  # опора проверки не совпадает с текстом
    ],
)
def test_conflict_needs_matching_scenario(second):
    first = lambda d: check("S-3", "correct", "pass")  # noqa: E731
    diff = compare_reports(v1_report(), _current(extra=[first, second]))
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"


def test_check_covering_one_side_only_is_not_enough():
    diff = compare_reports(v1_report(), _current(extra=[lambda d: _scenario_checks(d)[1]]))
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and "S-3/correct" in e["reason"]


def test_negative_recheck_without_matching_finding_is_unassessed():
    bad = check("S-4", "correct", "issue", finding_ids=["G-9"])
    status, e = by_old(compare_reports(v1_report(), _current(extra=[bad])))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_failed"
    assert "S-4/correct" in e["reason"] and "G-9" in e["reason"]


def test_severity_change_is_persisting_not_introduced():
    cur = _current(tz={"severity": "critical", "title": "Граница месяца не определена"})
    diff = compare_reports(v1_report(), cur)
    status, e = by_old(diff)["F-2"]
    assert status == "persisting" and e["severity_change"] == "raised"
    assert e["severity"] == {"old": "major", "new": "critical"}
    assert e["reason_code"] == "same_root_cause_severity_changed" and "это не новая первопричина" in e["reason"]
    assert diff["introduced"] == []


def _tz_fixed(checks, review=None):
    paras = replace(v1_paras(), {F2: F2_FIXED})
    doc = document(paras)
    return report(doc, requirements(doc, paras, review=review), [], checks=checks, run_id="run-2")


def test_simple_defect_closed_by_requirement_recheck():
    """Ф-2: добавлен UTC+5, проверка unambiguous по Ф-2 — pass: «исправлено в тексте»."""
    prev = v1_report(names=("tz",))
    status, e = by_old(compare_reports(prev, _tz_fixed([check("R-2", "unambiguous", "pass")])))["F-1"]
    assert status == "resolved" and e["proof"]["kind"] == "requirement_rechecked"
    assert "«в Алматы» → «по времени Алматы (UTC+5)»" in e["view"]["behavior_change"]


@pytest.mark.parametrize(
    "checks,review,code",
    [
        ([], None, "recheck_missing"),
        ([check("R-2", "unambiguous", "unknown")], None, "recheck_missing"),
        ([check("R-2", "unambiguous", "na")], None, "recheck_missing"),
        ([check("R-2", "unambiguous", "pass")], {"R-2": ("partial", "этап individual прерван")}, "recheck_skipped"),
    ],
)
def test_simple_defect_without_explicit_pass_is_unassessed(checks, review, code):
    prev = v1_report(names=("tz",))
    status, e = by_old(compare_reports(prev, _tz_fixed(checks, review)))["F-1"]
    assert status == "unassessed" and e["reason_code"] == code


def test_anchor_unchanged_elsewhere_edited():
    """Документ правили в другом месте; опора замечания дословно прежняя — не закрыто."""
    prev = v1_report(names=("nfr",))
    cur = _current(names=(), extra=[check("S-5", "verifiable", "pass")])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert e["evidence"][0]["quote"] == "в течение минуты после получения события"


READ_METHOD = "Метод getLimit возвращает порог, признак включения и сумму расходов за текущий месяц."


def _with_read_method(checks):
    paras = list(v1_paras()) + [((B, "Чтение настроек"), None, READ_METHOD, "R-11")]
    doc = document(paras)
    return report(doc, requirements(doc, paras), [], checks=checks, run_id="run-2")


def test_omission_closed_only_by_appeared_contract():
    """К4: «нет метода чтения» закрывается опорой на появившийся текст, а не тишиной."""
    prev = v1_report(names=("read",))
    cur = _with_read_method([check("R-7", "complete", "pass"), check("R-11", "complete", "pass")])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "resolved" and e["proof"]["kind"] == "contract_appeared"
    assert e["view"]["new_quote"] == READ_METHOD


def test_omission_with_only_old_text_as_proof_is_unassessed():
    prev = v1_report(names=("read",))
    cur = _with_read_method([check("R-7", "complete", "pass")])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["reason"].startswith("Текст в месте опоры изменён") and "обещанный контракт" in e["reason"]
