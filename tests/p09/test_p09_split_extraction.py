"""Готовность 3: дублированный старый пункт разделили на два, а один раздел исчез из извлечения.
Результат объяснимый; удаление источника не изображается как доказанное исправление."""

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    CONFLICT_QUOTES,
    DATA,
    F1,
    F2,
    F3,
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
    by_old,
    check,
    document,
    finding,
    report,
    requirements,
    v1_report,
)

NAMES = ("conflict", "dup", "single")
EXTRACTION_WARNING = "Страница 4 (Часть B, «Особые правила») не извлечена: пустой текстовый слой"


def _paras(rules_text: bool):
    p = [
        (S_FT, "Ф-1", F1, "U-1"),
        (S_FT, "Ф-2", F2, "U-2"),
        (S_FT, "Ф-3", F3, "U-3"),
        (S_FT, "Ф-4.1", F4_PART1, "U-4"),
        (S_FT, "Ф-4.2", F4_PART2, "U-5"),
        (S_NFR, None, NFR, "U-6"),
        (S_DATA, None, DATA, "U-7"),
        (S_INT, None, INT, "U-8"),
    ]
    if rules_text:  # текст раздела на месте, но требования из него не извлечены
        p += [(S_RULES, "1", RULE1, None), (S_RULES, "2", RULE2, None), (S_RULES, "3", RULE3, None)]
    return p


def _current(*, rules_text=False, checks=True, warnings=(EXTRACTION_WARNING,)):
    paras = _paras(rules_text)
    doc = document(paras, prefix="s", warnings=() if rules_text else warnings)
    conflict = finding(
        "M-1",
        doc,
        req_ids=["U-3", "U-5"],
        kind="conflict",
        criterion="И8",
        severity="critical",
        title="Ф-3 и Ф-4.2: лимит одного push против push «независимо от истории»",
        quotes=CONFLICT_QUOTES,
        scope="set",
        witness={
            "input": "push уже был; порог изменён",
            "outcome_a": "нет push",
            "outcome_b": "push",
            "evidence_a": None,
            "evidence_b": None,
        },
    )
    cs = (
        [
            check("C-1", ["U-4"], "И5", "passed", doc=doc, reason="одно обязательство"),
            check("C-2", ["U-5"], "И5", "passed", doc=doc, reason="одно обязательство"),
        ]
        if checks
        else []
    )
    return report(doc, requirements(doc, paras), [conflict], checks=cs)


def test_split_and_missing_section_explained():
    prev = v1_report(rules=True, names=NAMES)
    cur = _current()
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)

    # F-1: противоречие сохранилось, хотя Ф-4 разделён (Ф-4 → Ф-4.1 + Ф-4.2)
    assert st["F-1"][0] == "persisting" and st["F-1"][1]["new_ids"] == ["M-1"]

    # F-3: «неединичный» Ф-4 разделён на два, обе части перепроверены — исправлено в тексте
    status, e = st["F-3"]
    assert status == "resolved" and e["proof"]["check_ids"] == ["C-1", "C-2"]
    [link] = e["requirements"]
    assert link["relation"] == "split" and link["old_ids"] == ["R-4"] and link["new_ids"] == ["U-4", "U-5"]
    assert "разделён на 2 пункта" in e["view"]["behavior_change"]
    assert {x["quote"] for x in e["new_evidence"]} == {F4_PART1, F4_PART2}

    # F-2: дубль Ф-4 ↔ «Особые правила», п. 3 — раздел пропал из извлечения: нужно подтверждение
    status, e = st["F-2"]
    assert status == "unassessed" and e["reason_code"] == "obligation_missing"
    assert "«Особые правила»" in e["reason"] and "не доказывает исправления" in e["reason"]
    assert EXTRACTION_WARNING in e["reason"]
    rel = {r["old_ids"][0]: r for r in e["requirements"]}
    assert rel["R-10"]["relation"] == "missing" and rel["R-4"]["relation"] == "split"
    assert [x["quote"] for x in e["old_evidence"]] == [F4_PART1.rstrip("."), RULE3]
    assert [x["quote"] for x in e["new_evidence"]] == [F4_PART1.rstrip(".")]  # сохранилась только одна сторона
    assert e["recheck"]["new_req_ids"] == ["U-4", "U-5"]
    assert diff["resolved"] and not diff["introduced"]
    assert any(w["code"] == "extraction" for w in diff["warnings"])
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert {m[r]["missing"] for r in ("R-8", "R-9", "R-10")} == {"section_missing"}


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
    status, e = by_old(compare_reports(prev, _current(checks=False)))["F-3"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert e["recheck"]["new_req_ids"] == ["U-4", "U-5"]


def test_half_rechecked_split_is_not_closed():
    prev = v1_report(rules=True, names=NAMES)
    cur = _current()
    cur["checks"] = cur["checks"][:1]  # проверена только Ф-4.1
    status, e = by_old(compare_reports(prev, cur))["F-3"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"


def test_merge_of_two_items_into_one():
    """Обратный случай: два старых пункта слиты в один — связь merge, а не исчезновение."""
    from p09_case import F4, v1_paras

    prev_paras = [(s, sid, t, rid) for s, sid, t, rid in v1_paras()]
    prev_paras[3] = (S_FT, "Ф-4а", F4_PART1, "R-4")
    prev_paras.insert(4, (S_FT, "Ф-4б", F4_PART2, "R-4b"))
    pdoc = document(prev_paras)
    prev = report(pdoc, requirements(pdoc, prev_paras), [])
    cur_paras = [(s, sid, t, rid) for s, sid, t, rid in v1_paras()]
    cdoc = document(cur_paras, prefix="m")
    cur = report(cdoc, requirements(cdoc, cur_paras), [])
    m = {r["old_ids"][0]: r for r in compare_reports(prev, cur)["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-4"]["relation"] == "merge" and m["R-4b"]["relation"] == "merge"
    assert m["R-4"]["new_ids"] == m["R-4b"]["new_ids"] == ["R-4"]
    assert F4  # исходный Ф-4 = слияние частей
