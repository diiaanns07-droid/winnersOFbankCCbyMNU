"""resolve_candidate: две опоры конфликта, область пропуска, отказ при неполных опорах."""

from __future__ import annotations

import pytest
from p07_helpers import make_doc

from bcc_review.analysis.evidence import EvidenceAudit, RepairBudget, resolve_candidate

DOC = make_doc(
    "Ф-3. На карту приходится максимум один push за календарный месяц.",
    "Ф-4. После изменения порога следующее достижение вызывает push независимо от истории.",
    "Порог от 1 000 до 1 000 000 ₸. При превышении порога push не отправляется повторно; "
    "при каждом превышении порога push отправляется.",
    "| GET | /alerts/saveLimit |",
    "Приложение читает и сохраняет настройки через REST API.",
)
WITNESS = {
    "input": "в этом месяце push уже был, затем порог изменён и сумма снова его достигла",
    "outcome_a": "push не отправляется",
    "outcome_b": "push отправляется",
}


def conflict(*hints: dict, witness: dict | None = WITNESS) -> dict:
    cand = {"scope": "set", "kind": "conflict", "criterion": "consistency", "severity": "critical",
            "title": "Ф-3 противоречит Ф-4", "impact": "", "req_ids": ["R-3", "R-4"], "hints": list(hints)}
    if witness is not None:
        cand["witness"] = witness
    return cand


A = {"block_id": "b1", "quote": "максимум один push за календарный месяц"}
B = {"block_id": "b2", "quote": "следующее достижение вызывает push независимо от истории"}


def test_conflict_with_two_anchors_and_witness_is_supported() -> None:
    res = resolve_candidate(DOC, conflict(A, B))
    assert res["anchor_status"] == "supported", res["warnings"]
    w = res["witness"]
    assert w["evidence_a"]["block_id"] == "b1" and w["evidence_b"]["block_id"] == "b2"
    assert w["input"] and w["outcome_a"] != w["outcome_b"]
    assert len(res["evidence"]) == 2


def test_conflict_inside_one_block_with_different_ranges_is_supported() -> None:
    res = resolve_candidate(DOC, conflict(
        {"block_id": "b3", "quote": "push не отправляется повторно", "role": "a"},
        {"block_id": "b3", "quote": "при каждом превышении порога push отправляется", "role": "b"},
    ))
    assert res["anchor_status"] == "supported", res["warnings"]
    a, b = res["witness"]["evidence_a"], res["witness"]["evidence_b"]
    assert a["block_id"] == b["block_id"] == "b3"
    assert a["end"] <= b["start"]


@pytest.mark.parametrize(
    ("hints", "witness", "code"),
    [
        ((A, A), WITNESS, "conflict_same_anchor"),
        ((A, {"block_id": "b2", "quote": "максимум один push за календарный месяц"}), WITNESS,
         "found_in_other_block"),
        ((A, {"block_id": "b2", "quote": "вызывает push не более двух раз"}), WITNESS, "conflict_side_missing"),
        ((A, B), None, "conflict_witness_missing"),
        ((A, B), {**WITNESS, "outcome_b": "Push не отправляется"}, "conflict_outcomes_equal"),
        ((A, B, {"block_id": "b5", "quote": "читает"}), WITNESS, "conflict_sides_unspecified"),
    ],
)
def test_conflict_is_incomplete_without_two_distinct_anchors(hints: tuple, witness: dict | None, code: str) -> None:
    res = resolve_candidate(DOC, conflict(*hints, witness=witness))
    assert res["anchor_status"] == "incomplete"
    assert code in {r["code"] for r in res["reasons"]}, res["reasons"]
    assert any(w.startswith(code) for w in res["warnings"])


def test_conflict_sides_from_witness_hints() -> None:
    cand = conflict(witness={**WITNESS, "hint_a": A, "hint_b": B})
    res = resolve_candidate(DOC, cand)
    assert res["anchor_status"] == "supported", res["warnings"]


def omission(**extra: object) -> dict:
    cand = {"scope": "set", "kind": "omission", "criterion": "completeness", "severity": "critical",
            "title": "Нет метода чтения настроек", "impact": "", "req_ids": ["R-5"],
            "hints": [{"block_id": "b5", "quote": "читает и сохраняет настройки", "role": "promise"}],
            "inspected_block_ids": ["b4"]}
    cand.update(extra)
    return cand


def test_omission_with_promise_and_scope_is_supported() -> None:
    res = resolve_candidate(DOC, omission(absent_terms=["getLimit", "readLimit"]))
    assert res["anchor_status"] == "supported", res["warnings"]
    assert res["inspected_block_ids"] == ["b4"]
    assert res["evidence"][0]["quote"] == "читает и сохраняет настройки"


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"inspected_block_ids": []}, "omission_scope_missing"),
        ({"inspected_block_ids": ["b4", "b99"]}, "unknown_inspected_block"),
        ({"absent_terms": ["saveLimit"]}, "absent_term_present"),
        ({"hints": [{"block_id": "b5", "quote": "читает, сохраняет и удаляет настройки"}]}, "wording_mismatch"),
    ],
)
def test_omission_is_incomplete(extra: dict, code: str) -> None:
    res = resolve_candidate(DOC, omission(**extra))
    assert res["anchor_status"] == "incomplete"
    assert code in {r["code"] for r in res["reasons"]}, res["reasons"]


def test_single_defect_needs_every_hint_confirmed() -> None:
    good = {"block_id": "b3", "quote": "Порог от 1 000 до 1 000 000 ₸"}
    bad = {"block_id": "b3", "quote": "Порог от 1 000 до 100 000 ₸"}
    base = {"scope": "requirement", "kind": "ambiguity", "severity": "major", "req_ids": ["R-1"]}
    assert resolve_candidate(DOC, {**base, "hints": [good]})["anchor_status"] == "supported"
    res = resolve_candidate(DOC, {**base, "hints": [good, bad]})
    assert res["anchor_status"] == "incomplete"
    assert len(res["evidence"]) == 1  # подтверждённая опора сохраняется для отчёта
    assert res["reasons"][0]["code"] == "number_mismatch" and res["reasons"][0]["hint"] == 1
    assert resolve_candidate(DOC, {**base, "hints": []})["reasons"][0]["code"] == "no_hints"


def test_requirement_scope_warning_and_shared_budget() -> None:
    requirements = [{"id": "R-1", "block_ids": ["b3"]}]
    audit, budget = EvidenceAudit(budget=RepairBudget(limit=1)), RepairBudget(limit=1)
    audit.budget = budget
    cand = {"scope": "requirement", "kind": "ambiguity", "severity": "minor", "req_ids": ["R-1"],
            "hints": [{"block_id": "b1", "quote": "максимум один push"}]}
    res = resolve_candidate(DOC, cand, requirements=requirements, budget=budget, audit=audit)
    assert res["anchor_status"] == "supported"
    assert any(w.startswith("evidence_outside_requirement") for w in res["warnings"])
    assert audit.to_dict()["confirmed"] == 1 and audit.to_dict()["repair_budget"] == 1


# --- Кейс BCC: К2, К3, К4 и подмена цифры (идентификаторы и суммы задания) -----------


def block_at(doc: dict, line: int) -> str:
    return next(b["id"] for b in doc["blocks"] if b["loc"]["line_start"] <= line <= b["loc"]["line_end"])


def test_case_k2_f3_vs_f4_conflict(bcc_doc: dict) -> None:
    cand = conflict(
        {"block_id": block_at(bcc_doc, 39),
         "quote": "На карту приходится максимум один такой push за календарный месяц."},
        {"block_id": block_at(bcc_doc, 40),
         "quote": "следующее достижение вызывает push независимо от истории предыдущей настройки"},
    )
    res = resolve_candidate(bcc_doc, cand)
    assert res["anchor_status"] == "supported", res["warnings"]


def test_case_k3_error_inside_200(bcc_doc: dict) -> None:
    cand = conflict(
        {"block_id": block_at(bcc_doc, 163),
         "quote": "**400.** Ответ в случае, если параметры запроса заполнены неверно."},
        {"block_id": block_at(bcc_doc, 171), "quote": '{"result":"ERROR","message":"Проверьте сумму"}'},
        witness={"input": "amount=999", "outcome_a": "HTTP 400", "outcome_b": "HTTP 200 с result=ERROR"},
    )
    res = resolve_candidate(bcc_doc, cand)
    assert res["anchor_status"] == "supported", res["warnings"]


def test_case_k4_missing_read_method(bcc_doc: dict) -> None:
    api_blocks = [b["id"] for b in bcc_doc["blocks"]
                  if b["section"][:2] == ["Уведомление о расходах по карте", "Часть B. REST API"]]
    cand = omission(hints=[{"block_id": block_at(bcc_doc, 52), "quote": "Приложение читает и сохраняет настройки"}],
                    inspected_block_ids=api_blocks, absent_terms=["getLimit", "readLimit", "/alerts/limit"])
    res = resolve_candidate(bcc_doc, cand)
    assert res["anchor_status"] == "supported", res["warnings"]
    assert len(res["inspected_block_ids"]) > 30


def test_case_wrong_threshold_is_not_confirmed(bcc_doc: dict) -> None:
    cand = {"scope": "requirement", "kind": "ambiguity", "severity": "major", "req_ids": ["R-1"],
            "hints": [{"block_id": block_at(bcc_doc, 37), "quote": "целый порог от 1 000 до 100 000 ₸ включительно"}]}
    res = resolve_candidate(bcc_doc, cand)
    assert res["anchor_status"] == "incomplete"
    hint = res["hint_results"][0]
    assert hint["reason"] == "number_mismatch"
    assert hint["candidates"][0]["text"] == "целый порог от 1 000 до 1 000 000 ₸ включительно"
