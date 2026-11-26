"""Ложные срабатывания и обоснование порогов сходства (маленький пример из кейса)."""

import pytest

from bcc_review.decisions import diff as D
from bcc_review.decisions.diff import compare_reports, containment, text_similarity
from p09_case import (
    DATA,
    F1,
    F2,
    F2_FIXED,
    F3,
    F4,
    F4_FIXED,
    F4_PART1,
    F4_PART2,
    INT,
    NFR,
    RULE1,
    RULE3,
    S_DATA,
    S_FT,
    S_INT,
    S_NFR,
    assert_partition,
    by_old,
    check,
    document,
    finding,
    issue_checks,
    replace,
    report,
    requirements,
    v1_paras,
    v1_report,
)

F3_PARA = (
    "Push отправляется клиенту, когда расходы за месяц переходят с суммы ниже порога на сумму не меньше "
    "порога. Для одной карты — не более одного такого push в календарный месяц."
)
NFR2 = "Push передаётся на отправку не позднее 60 секунд с момента получения события процессинга (95-й перцентиль)."

SAME = [
    ("перенумерация", F1, F1),
    ("правка Ф-2", F2, F2_FIXED),
    ("перефраз Ф-3", F3, F3_PARA),
    ("правка Ф-4", F4, F4_FIXED),
]
DIFFERENT = [
    ("Ф-3~Ф-4", F3, F4),
    ("Ф-1~правило 1", F1, RULE1),
    ("Ф-2~данные", F2, DATA),
    ("Ф-3~НФТ", F3, NFR),
    ("перефраз Ф-3~Ф-4", F3_PARA, F4),
]


@pytest.mark.parametrize("name,a,b", SAME)
def test_same_obligation_scores_above_confident(name, a, b):
    assert text_similarity(a, b) >= D.REQ_CONFIDENT, name


@pytest.mark.parametrize("name,a,b", DIFFERENT)
def test_different_obligations_score_below_candidate(name, a, b):
    assert text_similarity(a, b) < D.REQ_CANDIDATE, name


def test_split_parts_are_contained_but_duplicate_is_not():
    assert containment(F4_PART1, F4) >= D.PART_CONTAINMENT
    assert containment(F4_PART2, F4) >= D.PART_CONTAINMENT
    assert containment(RULE3, F4) < D.PART_CONTAINMENT  # смысловой дубль — не часть разделения


def test_normalization_numbers_quotes_yo():
    assert D._norm("от 1 000 до 1 000 000 ₸") == "от 1000 до 1000000 ₸"
    assert D._norm("«Порог» — ЁЛКА") == '"порог" - елка'


def test_strip_label_only_strips_item_numbers():
    assert D.strip_label("Ф-1. Держатель карты") == "Держатель карты"
    assert D.strip_label("п. 3 Изменение порога") == "Изменение порога"
    assert D.strip_label("2) Повторное сохранение") == "Повторное сохранение"
    assert D.strip_label("Ф-4.2. Если накопленная") == "Если накопленная"
    assert D.strip_label("1 000 ₸ — нижняя граница") == "1 000 ₸ — нижняя граница"
    assert D.strip_label("Если 5 дней нет событий") == "Если 5 дней нет событий"
    assert D.strip_label("1.5 часа на ответ") == "1.5 часа на ответ"


def test_same_kind_at_other_place_is_not_persisting():
    """Старая неоднозначность Ф-2 исправлена; новая неоднозначность Ф-1 — новая, а не «сохранилось»."""
    prev = v1_report(names=("tz",))
    paras = replace(v1_paras(), {F2: F2_FIXED})
    doc = document(paras)
    new = finding(
        "G-1",
        doc,
        req_ids=["R-1"],
        kind="ambiguity",
        criterion="unambiguous",
        severity="major",
        title="Не определено, что такое «активная карта»",
        quotes=["активной карты KZT"],
    )
    checks = issue_checks([new]) + [check("R-2", "unambiguous", "pass")]
    cur = report(doc, requirements(doc, paras), [new], checks=checks, run_id="run-2")
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert by_old(diff)["F-1"][0] == "resolved"
    [intro] = diff["introduced"]
    assert intro["new_ids"] == ["G-1"] and intro["origin"] == "existing_text"
    assert intro["reason_code"] == "new_finding_old_text" and intro["old_evidence"][0]["quote"] == "активной карты KZT"


def test_deleted_requirement_not_aligned_to_neighbour():
    """Ф-3 удалён: не подменяется похожим Ф-4, противоречие не закрывается удалением."""
    prev = v1_report(names=("conflict",))
    paras = replace(v1_paras(), {F3: None, F4: F4_FIXED})
    doc = document(paras)
    cur = report(doc, requirements(doc, paras), [], checks=[check("R-4", "correct", "pass")], run_id="run-2")
    diff = compare_reports(prev, cur)
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-3"]["relation"] == "missing" and m["R-3"]["missing"] == "removed"
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "obligation_missing"
    assert "Удаление не доказывает исправления" in e["reason"]


def test_renumbering_collision_follows_text():
    """Вставлен новый Ф-3, старый Ф-3 стал Ф-4 и переформулирован: номер не перетягивает пару."""
    prev = v1_report(names=())
    inserted = "Push не отправляется по закрытым или заблокированным картам."
    paras = [
        (S_FT, "Ф-1", F1, "N1"),
        (S_FT, "Ф-2", F2, "N2"),
        (S_FT, "Ф-3", inserted, "N3"),
        (S_FT, "Ф-4", F3_PARA, "N4"),
        (S_FT, "Ф-5", F4, "N5"),
        (S_NFR, None, NFR, "N6"),
        (S_DATA, None, DATA, "N7"),
        (S_INT, None, INT, "N8"),
    ]
    doc = document(paras)
    diff = compare_reports(prev, report(doc, requirements(doc, paras), [], run_id="run-2"))
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-3"]["new_ids"] == ["N4"] and set(m["R-3"]["changes"]) == {"reworded", "renumbered"}
    assert m["R-4"]["new_ids"] == ["N5"] and m["R-4"]["changes"] == ["renumbered"]
    assert [r["new_ids"] for r in diff["basis"]["requirement_map"] if r["relation"] == "added"] == [["N3"]]


def test_reworded_in_same_section_matches_and_closes_with_recheck():
    prev = v1_report(names=("nfr",))
    paras = replace(v1_paras(), {NFR: NFR2})
    doc = document(paras)
    cur = report(doc, requirements(doc, paras), [], checks=[check("R-5", "verifiable", "pass")], run_id="run-2")
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "resolved"
    assert e["requirements"][0]["relation"] == "same" and "reworded" in e["requirements"][0]["changes"]


def _moved_nfr():
    paras = replace(v1_paras(), {NFR: None})
    paras.append((("Часть A. Новый функционал", "Показатели качества"), None, NFR2, "R-5"))
    doc = document(paras)
    return report(doc, requirements(doc, paras), [], checks=[check("R-5", "verifiable", "pass")], run_id="run-2")


def test_reworded_and_moved_is_ambiguous_without_engine():
    prev = v1_report(names=("nfr",))
    diff = compare_reports(prev, _moved_nfr())
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "alignment_ambiguous"
    [link] = e["requirements"]
    assert link["relation"] == "ambiguous"


def test_engine_identity_with_verified_quotes_aligns_but_check_still_required():
    calls = []

    def ask(stage, payload, schema):
        calls.append((stage, payload, schema))
        return {
            "match_id": payload["input"]["candidates"][0]["id"],
            "old_quote": "получения события",
            "new_quote": "получения события процессинга",
            "reason": "то же НФТ о сроке передачи push",
        }

    prev = v1_report(names=("nfr",))
    cur = _moved_nfr()
    diff = compare_reports(prev, cur, ask=ask)
    stage, payload, schema = calls[0]
    assert stage == "diff_identity" and set(payload) == {"task", "input", "context"}
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    status, e = by_old(diff)["F-1"]
    assert status == "resolved" and e["requirements"][0]["via"] == "model"
    cur["checks"] = []  # модель подтвердила идентичность, но перепроверки нет — не закрыто
    status, e = by_old(compare_reports(prev, cur, ask=ask))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"


@pytest.mark.parametrize(
    "answer",
    [
        {"match_id": "R-5", "old_quote": "выдуманная цитата модели", "new_quote": "получения события", "reason": "x"},
        {"match_id": "R-99", "old_quote": "получения события", "new_quote": "получения события", "reason": "x"},
        RuntimeError("503"),
    ],
)
def test_engine_identity_rejected_when_unverifiable(answer):
    def ask(stage, payload, schema):
        if isinstance(answer, Exception):
            raise answer
        return answer

    diff = compare_reports(v1_report(names=("nfr",)), _moved_nfr(), ask=ask)
    status, e = by_old(diff)["F-1"]
    assert status == "unassessed" and e["reason_code"] == "alignment_ambiguous"
    assert any(w["code"] in ("identity_unverified", "identity_ask_failed") for w in diff["warnings"])


def test_unverified_old_evidence_is_flagged():
    prev = v1_report(names=("tz",))
    prev["findings"][0]["evidence"][0]["start"] += 1  # координаты разошлись с цитатой
    diff = compare_reports(prev, v1_report(names=("tz",)))
    [e] = diff["persisting"]
    assert e["old_evidence"][0]["verified"] is False
    assert any(w["code"] == "unverified_evidence" for w in diff["warnings"])
