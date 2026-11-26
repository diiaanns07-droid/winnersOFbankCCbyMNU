"""Готовность 2: одна бизнес-правка закрывает первый дефект и оставляет второй.
Принятое решение без новой редакции и второй прогон с техническим сбоем не закрывают дефект."""

import pytest

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    CONFLICT_QUOTES,
    F4,
    F4_FIXED,
    V1_IDS,
    WITNESS_INPUT,
    assert_partition,
    by_old,
    check,
    clone,
    document,
    make_findings,
    report,
    requirements,
    v1_paras,
    v1_report,
)

FIX_QUOTE = "в текущем календарном месяце push по карте ещё не отправлялся"
IDS = {k: v.replace("R", "S") for k, v in V1_IDS.items()}


def _fixed(**kw):
    paras = [(s, sid, F4_FIXED if t == F4 else t, rid.replace("R", "S")) for s, sid, t, rid in v1_paras()]
    doc = document(paras, prefix="c")
    return doc, requirements(doc, paras)


def _scenario_check(doc, **over):
    args = dict(
        doc=doc,
        scope="set",
        quotes=[FIX_QUOTE, CONFLICT_QUOTES[0]],
        scenario=WITNESS_INPUT,
        reason="Оба пункта дают один исход: повторного push в месяце нет",
    )
    args.update(over)
    return check("C-1", [IDS["F3"], IDS["F4"]], "И8", "passed", **args)


def _current(checks=(), status="complete", names=("tz", "nfr", "read", "units"), **over):
    doc, reqs = _fixed()
    return report(doc, reqs, make_findings(doc, IDS, names, prefix="G", **over), checks=checks, status=status)


def test_business_fix_closes_conflict_and_keeps_timezone_defect():
    prev = v1_report()
    doc, _ = _fixed()
    cur = _current(checks=[_scenario_check(doc)])
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    status, e = st["F-1"]
    assert status == "resolved" and e["status_ru"] == "исправлено в тексте"
    assert e["proof"]["kind"] == "conflict_reconciled" and e["proof"]["check_ids"] == ["C-1"]
    assert e["proof"]["scenario"] == WITNESS_INPUT
    assert any(x["quote"] == FIX_QUOTE and x["verified"] for x in e["new_evidence"])
    assert {x["quote"] for x in e["old_evidence"]} == set(CONFLICT_QUOTES)
    assert e["view"]["old_quote"] == CONFLICT_QUOTES[1]  # изменившийся фрагмент Ф-4
    assert e["view"]["new_quote"] == FIX_QUOTE
    assert "убрано «независимо от истории предыдущей настройки»" in e["view"]["behavior_change"]
    assert st["F-2"][0] == "persisting" and st["F-2"][1]["status_ru"] == "сохранилось"
    assert {k for k, _ in st.values()} == {"resolved", "persisting"}
    assert diff["introduced"] == [] and diff["unassessed"] == []


def test_accepted_answer_without_new_edition_does_not_close():
    """Ответ по --answers при прежнем тексте: «нужно подтверждение», обе опоры из одного текста."""
    prev = v1_report()
    cur = clone(prev)
    cur["findings"] = make_findings(cur["document"], V1_IDS, ("tz", "nfr", "read", "units"), prefix="G")
    cur["decisions"] = [
        {
            "id": "D-1",
            "question_id": "Q-1",
            "finding_ids": ["F-1"],
            "status": "accepted",
            "answer": "Ф-3 главнее: не более одного push за календарный месяц",
        }
    ]
    # даже «положительная» проверка, сделанная по ответу, не заменяет правку текста
    cur["checks"] = [
        check(
            "C-1",
            ["R-3", "R-4"],
            "И8",
            "passed",
            doc=cur["document"],
            scope="set",
            quotes=CONFLICT_QUOTES,
            scenario=WITNESS_INPUT,
        )
    ]
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["status_ru"] == "нужно подтверждение"
    assert e["reason_code"] == "answer_only" and "D-1" in e["reason"]
    assert e["decision_refs"][0]["id"] == "D-1" and e["view"]["decision_ref"]["id"] == "D-1"
    assert [x["quote"] for x in e["old_evidence"]] == CONFLICT_QUOTES
    assert [x["quote"] for x in e["new_evidence"]] == CONFLICT_QUOTES  # опора в «новой» редакции та же
    assert all(x["verified"] for x in e["new_evidence"])
    assert e["recheck"]["scenario"] == WITNESS_INPUT
    assert not diff["resolved"]


def test_answer_with_finding_still_reported_is_persisting_with_note():
    prev = v1_report()
    cur = clone(prev)
    cur["decisions"] = [{"id": "D-1", "finding_ids": ["F-1"], "answer": "Ф-3 главнее", "status": "accepted"}]
    diff = compare_reports(prev, cur)
    status, e = by_old(diff)["F-1"]
    assert status == "persisting" and "формулировка в документе прежняя" in e["reason"]
    assert e["view"]["decision_ref"]["id"] == "D-1"


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_technical_failure_of_second_run_closes_nothing(status):
    prev = v1_report()
    doc, _ = _fixed()
    names = () if status == "failed" else ("tz",)
    cur = _current(checks=[_scenario_check(doc)], status=status, names=names)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert diff["resolved"] == []
    st = by_old(diff)
    assert st["F-1"][0] == "unassessed" and st["F-1"][1]["reason_code"] == "run_incomplete"
    assert f"«{status}»" in st["F-1"][1]["reason"]
    if status == "partial":
        assert st["F-2"][0] == "persisting"  # найденное в неполном прогоне всё равно сохранилось
    assert any(w["code"] == "current_incomplete" for w in diff["warnings"])


def test_silence_without_recheck_is_not_a_closure():
    prev = v1_report()
    diff = compare_reports(prev, _current())
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert WITNESS_INPUT[:40] in e["reason"]
    assert e["recheck"]["stage"] == "diff_recheck" and e["recheck"]["new_req_ids"] == ["S-3", "S-4"]


@pytest.mark.parametrize(
    "over",
    [
        {"quotes": [FIX_QUOTE]},  # опора только со стороны Ф-4, сторона Ф-3 не подтверждена текстом
        {"scenario": "Клиент меняет порог дважды за день"},  # другой сценарий
        {"quotes": []},  # нет опоры в новом тексте
    ],
)
def test_conflict_needs_same_scenario_and_anchor(over):
    doc, _ = _fixed()
    diff = compare_reports(v1_report(), _current(checks=[_scenario_check(doc, **over)]))
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"


def test_check_covering_one_side_only_is_not_enough():
    doc, _ = _fixed()
    one_side = check("C-1", [IDS["F4"]], "И8", "passed", doc=doc, quotes=[FIX_QUOTE], scenario=WITNESS_INPUT)
    status, e = by_old(compare_reports(v1_report(), _current(checks=[one_side])))["F-1"]
    assert status == "unassessed"


def test_negative_recheck_without_matching_finding_is_unassessed():
    doc, _ = _fixed()
    bad = check("C-9", [IDS["F3"], IDS["F4"]], "И8", "failed", doc=doc, quotes=[FIX_QUOTE])
    status, e = by_old(compare_reports(v1_report(), _current(checks=[bad])))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_failed" and "C-9" in e["reason"]


def test_severity_change_is_persisting_not_introduced():
    doc, _ = _fixed()
    cur = _current(checks=[_scenario_check(doc)], tz={"severity": "critical", "title": "Граница месяца не определена"})
    diff = compare_reports(v1_report(), cur)
    status, e = by_old(diff)["F-2"]
    assert status == "persisting" and e["severity_change"] == "raised"
    assert (
        e["severity"] == {"old": "major", "new": "critical"} and e["reason_code"] == "same_root_cause_severity_changed"
    )
    assert "это не новая первопричина" in e["reason"]
    assert diff["introduced"] == []


def test_simple_defect_closed_by_requirement_recheck():
    """Ф-2: добавлен UTC+5, перепроверка по И3 положительна — «исправлено в тексте»."""
    from p09_case import F2, F2_FIXED

    prev = v1_report(names=("tz",))
    paras = [(s, sid, F2_FIXED if t == F2 else t, rid) for s, sid, t, rid in v1_paras()]
    doc = document(paras, prefix="d")
    ok = check("C-2", ["R-2"], "И3", "passed", doc=doc, quotes=["по времени Алматы (UTC+5)"])
    cur = report(doc, requirements(doc, paras), [], checks=[ok])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "resolved" and e["proof"]["kind"] == "requirement_rechecked"
    assert "«в Алматы» → «по времени Алматы (UTC+5)»" in e["view"]["behavior_change"]
    # тот же сценарий без проверки — нужно подтверждение
    cur["checks"] = []
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"


def test_anchor_unchanged_elsewhere_edited():
    """Документ правили в другом месте; опора замечания дословно прежняя — не закрыто."""
    prev = v1_report(names=("nfr",))
    doc, reqs = _fixed()
    ok = check("C-3", [IDS["NFR"]], "И7", "passed", doc=doc)
    cur = report(doc, reqs, [], checks=[ok])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert e["new_evidence"][0]["quote"] == "в течение минуты после получения события"


READ_METHOD = "Метод getLimit возвращает порог, признак включения и сумму расходов за текущий месяц."


def _with_read_method():
    from p09_case import B

    paras = list(v1_paras()) + [((B, "Чтение настроек"), None, READ_METHOD, "R-11")]
    doc = document(paras, prefix="r")
    return doc, paras


def test_omission_closed_only_by_appeared_contract():
    """К4: «нет метода чтения» закрывается опорой на появившийся текст, а не тишиной."""
    prev = v1_report(names=("read",))
    doc, paras = _with_read_method()
    ok = check(
        "C-5",
        ["R-7", "R-11"],
        "Н1",
        "passed",
        doc=doc,
        scope="set",
        quotes=[READ_METHOD],
        reason="Описан метод чтения настроек",
    )
    cur = report(doc, requirements(doc, paras), [], checks=[ok])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "resolved" and e["proof"]["kind"] == "contract_appeared"
    assert e["view"]["new_quote"] == READ_METHOD


def test_omission_with_only_old_text_as_proof_is_unassessed():
    prev = v1_report(names=("read",))
    doc, paras = _with_read_method()
    stale = check(
        "C-5", ["R-7"], "Н1", "passed", doc=doc, scope="set", quotes=["Приложение читает и сохраняет настройки"]
    )
    cur = report(doc, requirements(doc, paras), [], checks=[stale])
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["reason"].startswith("Текст в месте опоры изменён") and "обещанный контракт" in e["reason"]
