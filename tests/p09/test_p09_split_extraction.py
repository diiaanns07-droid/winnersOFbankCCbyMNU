"""Готовность 3: дублированный старый пункт разделили на два, а один раздел исчез из извлечения.
Результат объяснимый; удаление источника не изображается как доказанное исправление."""

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    DATA,
    F1,
    F2,
    F3,
    F4,
    F4_PART1,
    F4_PART2,
    INT,
    NFR,
    RULE1,
    RULE2,
    RULE3,
    S_DATA,
    S_FT,
    S_INT,
    S_NFR,
    S_RULES,
    assert_partition,
    assert_valid_report,
    by_old,
    check,
    document,
    finding,
    issue_checks,
    report,
    requirements,
    v1_paras,
    v1_report,
    witness,
)

NAMES = ("conflict", "dup", "single")
LOST = {"code": "partial_read", "message": "Страница 4 (Часть B, «Особые правила») не прочитана: пустой текстовый слой"}


def _paras(rules_text: bool):
    p = [
        (S_FT, "Ф-1", F1, "R-1"),
        (S_FT, "Ф-2", F2, "R-2"),
        (S_FT, "Ф-3", F3, "R-3"),
        (S_FT, "Ф-4.1", F4_PART1, "R-4"),
        (S_FT, "Ф-4.2", F4_PART2, "R-5"),
        (S_NFR, None, NFR, "R-6"),
        (S_DATA, None, DATA, "R-7"),
        (S_INT, None, INT, "R-8"),
    ]
    if rules_text:  # текст раздела на месте, но требования из него не извлечены
        p += [(S_RULES, "1", RULE1, None), (S_RULES, "2", RULE2, None), (S_RULES, "3", RULE3, None)]
    return p


def _current(*, rules_text=False, lost=False, rechecks=("R-4", "R-5")):
    paras = _paras(rules_text)
    doc = document(paras, warnings=[LOST] if lost else ())
    conflict = finding(
        "F-1",
        doc,
        req_ids=["R-3", "R-5"],
        kind="conflict",
        criterion="set_consistent",
        severity="critical",
        title="Ф-3 и Ф-4.2: лимит одного push против push «независимо от истории»",
        quotes=[],
        scope="set",
        witness=witness(doc),
    )
    conflict["evidence"] = [conflict["witness"]["evidence_a"], conflict["witness"]["evidence_b"]]
    checks = issue_checks([conflict]) + [check(r, "singular", "pass", reason="одно обязательство") for r in rechecks]
    return report(
        doc,
        requirements(doc, paras),
        [conflict],
        checks=checks,
        status="partial" if lost else "complete",
        run_id="run-2",
    )


def test_split_and_section_lost_in_extraction_explained():
    """Раздел «Особые правила» не прочитан (partial_read) — прогон partial: ничего не закрыто, всё объяснено."""
    prev = v1_report(rules=True, names=NAMES)
    cur = _current(lost=True)
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    assert st["F-1"][0] == "persisting" and st["F-1"][1]["new_ids"] == ["F-1"]  # противоречие осталось в Ф-4.2
    assert not diff["resolved"]

    status, e = st["F-2"]  # дубль Ф-4 ↔ «Особые правила», п. 3
    assert status == "unassessed" and e["reason_code"] == "run_incomplete"
    assert "«Особые правила»" in e["reason"] and "вероятно, потерян при чтении" in e["reason"]
    assert "Удаление источника не доказывает исправления" in e["reason"]
    rel = {r["old_ids"][0]: r for r in e["requirements"]}
    assert rel["R-10"]["relation"] == "missing" and rel["R-4"]["relation"] == "split"
    assert [x["quote"] for x in e["old_evidence"]] == [F4_PART1.rstrip("."), RULE3]
    assert [x["quote"] for x in e["evidence"]] == [F4_PART1.rstrip(".")]  # уцелела только одна сторона дубля

    status, e = st["F-3"]  # «неединичный» Ф-4 разделён и перепроверен, но прогон неполный
    assert status == "unassessed" and e["reason_code"] == "run_incomplete"
    assert e["requirements"][0]["relation"] == "split" and e["requirements"][0]["new_ids"] == ["R-4", "R-5"]
    assert "разделён на 2 пункта" in e["view"]["behavior_change"]
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert {m[r]["missing"] for r in ("R-8", "R-9", "R-10")} == {"section_missing"}
    assert any(w["code"] == "extraction" for w in diff["warnings"])


def test_split_closes_and_removed_section_needs_confirmation():
    """Полный прогон: раздел удалён автором. Разделение закрыто перепроверкой, дубль — нужно подтверждение."""
    prev = v1_report(rules=True, names=NAMES)
    cur = _current()
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    status, e = st["F-3"]
    assert status == "resolved" and e["proof"]["check_refs"] == ["R-4/singular", "R-5/singular"]
    [link] = e["requirements"]
    assert link["relation"] == "split" and link["old_ids"] == ["R-4"] and link["new_ids"] == ["R-4", "R-5"]
    assert {x["quote"] for x in e["evidence"]} == {"Ф-4.1. " + F4_PART1, "Ф-4.2. " + F4_PART2}
    status, e = st["F-2"]
    assert status == "unassessed" and e["reason_code"] == "obligation_missing"
    assert "удалён автором или не прочитан" in e["reason"] and "не доказывает исправления" in e["reason"]
    assert e["recheck"]["missing_old_req_ids"] == ["R-10"]
    assert diff["impacted_req_ids"] == ["R-4", "R-5"]


def test_text_present_but_not_extracted_is_extraction_gap():
    prev = v1_report(rules=True, names=NAMES)
    diff = compare_reports(prev, _current(rules_text=True))
    status, e = by_old(diff)["F-2"]
    assert status == "unassessed" and e["reason_code"] == "obligation_missing"
    assert "пробел извлечения" in e["reason"]
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-10"]["missing"] == "extraction_gap"


def test_split_without_recheck_needs_confirmation():
    prev = v1_report(rules=True, names=NAMES)
    status, e = by_old(compare_reports(prev, _current(rechecks=())))["F-3"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["recheck"]["new_req_ids"] == ["R-4", "R-5"]


def test_half_rechecked_split_is_not_closed():
    prev = v1_report(rules=True, names=NAMES)
    status, e = by_old(compare_reports(prev, _current(rechecks=("R-4",))))["F-3"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing" and "R-5/singular" in e["reason"]


def test_merge_of_two_items_into_one():
    """Обратный случай: два старых пункта слиты в один — связь merge, а не исчезновение."""
    prev_paras = list(v1_paras())
    prev_paras[3] = (S_FT, "Ф-4а", F4_PART1, "R-4")
    prev_paras.insert(4, (S_FT, "Ф-4б", F4_PART2, "R-4b"))
    pdoc = document(prev_paras)
    prev = report(pdoc, requirements(pdoc, prev_paras), [])
    cdoc = document(v1_paras())
    cur = report(cdoc, requirements(cdoc, v1_paras()), [], run_id="run-2")
    m = {r["old_ids"][0]: r for r in compare_reports(prev, cur)["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-4"]["relation"] == "merge" and m["R-4b"]["relation"] == "merge"
    assert m["R-4"]["new_ids"] == m["R-4b"]["new_ids"] == ["R-4"]
    assert F4.startswith(F4_PART1)
