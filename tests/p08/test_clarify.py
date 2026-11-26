"""Выбор вопросов: только решения, которые меняют реализацию или приёмку."""
from __future__ import annotations

import pytest

from bcc_review.decisions import CLARIFY_SCHEMA, STAGE, build_questions
from bcc_review.decisions._demo import TERM_WORKDAY, make_scripted_ask
from bcc_review.decisions._doc import DocView
from bcc_review.decisions.clarify import OWNER_ROLES, decision_family


def test_only_confirmed_decision_findings_become_questions(doc, findings, ask):
    log: list[str] = []
    qs = build_questions(doc, findings, ask, warnings=log)
    used = {fid for q in qs for fid in q.finding_ids}
    assert used == {"F-01", "F-02", "F-03", "F-04", "F-05"}
    # F-06 редакционная, F-07 не подтверждена, F-08 — опора не совпала с текстом
    assert not used & {"F-06", "F-07", "F-08"}
    assert any(w.startswith("[no_evidence] F-08") for w in log)


def test_one_answer_merges_findings_and_independent_conflict_stays_separate(questions, qf):
    fee = qf(questions, "F-01")
    assert fee.finding_ids == ["F-01", "F-02"]  # общий фрагмент «Тарифы» — один ответ
    assert fee.affected_req_ids == ["R-02", "R-06", "R-07"]
    sched = qf(questions, "F-03")
    assert sched is not fee and sched.finding_ids == ["F-03"]


def test_ranking_puts_critical_business_conflicts_first(questions):
    assert [q.id for q in questions] == ["Q-01", "Q-02", "Q-03", "Q-04"]
    assert questions[0].finding_ids == ["F-01", "F-02"]
    assert questions[1].finding_ids == ["F-03"]
    assert [q.severity for q in questions] == ["critical", "critical", "major", "major"]
    assert all(q.rank_reason for q in questions)
    assert questions[-1].kind == "align_to_source"
    assert "ответ уже есть в документе" in questions[-1].rank_reason
    assert questions[0].priority > questions[1].priority > questions[2].priority > questions[3].priority


def test_card_has_owner_blocks_quotes_and_coordinates(doc, questions):
    d = DocView(doc)
    for q in questions:
        assert q.owner in OWNER_ROLES
        assert q.blocks and q.prompt and q.why and q.situation
        assert q.source_sha256 == doc["id"]
        assert q.sources, q.id
        for s in q.sources:
            b = d.block(s["block_id"])
            assert b.text[s["start"]:s["end"]] == s["quote"]
            assert s["loc"].startswith("строка ")
        assert len(q.options) >= 2


def test_options_have_distinct_observable_results_and_exact_old(doc, questions):
    d = DocView(doc)
    for q in questions:
        results = {o.observable_result for o in q.options}
        assert len(results) == len(q.options), q.id
        for o in q.options:
            for e in o.edits:
                assert d.block(e["block_id"]).text[e["start"]:e["end"]] == e["old"]
                assert e["source_sha256"] == doc["id"]
                assert e["question_id"] == q.id


def test_document_answer_is_verified_and_hypothesis_kept_separate(questions, qf):
    bank = qf(questions, "F-04")
    assert bank.kind == "align_to_source"
    assert bank.document_answer["quote"] == TERM_WORKDAY
    assert bank.document_answer["loc"].startswith("строка 14")
    fee = qf(questions, "F-01")
    assert fee.hypothesis and "прежней версии" in fee.hypothesis
    assert all(fee.hypothesis not in o.interpretation for o in fee.options)


def test_invented_limit_is_flagged_in_card(questions, qf):
    gap = qf(questions, "F-05")
    b = gap.option("B")
    assert b.edits and b.edits[0]["invented"] == ["50 000 ₸"]
    assert any(w.startswith("[invented_value]") for w in b.warnings)
    assert not gap.option("A").warnings


def test_payload_and_schema(ask, questions):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(CLARIFY_SCHEMA)
    assert len(ask.calls) == 1  # малый документ — один физический вызов
    stage, payload, schema = ask.calls[0]
    assert stage == STAGE == "clarify" and schema is CLARIFY_SCHEMA
    assert set(payload) == {"task", "input", "context"}  # contracts/HANDOFF.md
    assert "Не придумывай чисел" in payload["task"]
    assert {g["group_id"] for g in payload["input"]["groups"]} == {"G1", "G2", "G3", "G4"}
    assert payload["context"]["mode"] == "auto"
    used = {e["block_id"] for q in questions for s in [q.sources] for e in s}
    assert set(payload["context"]["block_ids"]) == used  # только блоки с опорами вопросов


def test_schema_fits_structured_outputs():
    """additionalProperties: false и полный required у каждого объекта, без min*/max*."""
    def walk(node, path="$"):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, path
                assert sorted(node["required"]) == sorted(node["properties"]), path
            for bad in ("minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength"):
                assert bad not in node, f"{path}.{bad}"
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(CLARIFY_SCHEMA)


# --- модель ошиблась: код не доверяет ей ------------------------------------------------


def _wrap(doc, mutator):
    scripted = make_scripted_ask(doc)

    def _ask(stage, payload, schema):
        resp = scripted(stage, payload, schema)
        mutator(resp, payload["input"])
        return resp
    return _ask


def test_unverified_document_answer_becomes_hypothesis(doc, findings, qf):
    def m(resp, payload):
        for q in resp["questions"]:
            if "document_answer" in q:
                q["document_answer"]["quote"] = "Банковский день — любой день, кроме воскресенья."
    log: list[str] = []
    qs = build_questions(doc, findings, _wrap(doc, m), warnings=log)
    bank = qf(qs, "F-04")
    assert bank.kind == "decision" and bank.document_answer is None
    assert "не подтверждено" in bank.hypothesis
    assert any(w.startswith("[document_answer_unverified]") for w in log)


def test_llm_edit_with_wrong_old_is_rejected(doc, findings):
    def m(resp, payload):
        resp["questions"][0]["options"][0]["edits"][0]["old"] = "Комиссия 2% от суммы"
    log: list[str] = []
    qs = build_questions(doc, findings, _wrap(doc, m), warnings=log)
    a = qs[0].option("A")
    assert a.edits == [] and any(w.startswith("[edit_rejected]") for w in a.warnings)
    assert any(w.startswith("[edit_block_unknown]") or w.startswith("[edit_old_not_found]") for w in log)


def test_indistinct_options_fall_back_to_witness(doc, findings, qf):
    def m(resp, payload):
        for o in resp["questions"][0]["options"]:
            o["observable_result"] = "Что-то произойдёт."
    log: list[str] = []
    qs = build_questions(doc, findings, _wrap(doc, m), warnings=log)
    fee = qf(qs, "F-01")
    assert fee.origin == "rule"
    assert [o.observable_result for o in fee.options] == [
        "Кредит выдан 10 января, досрочное погашение 10 марта на 200 000 ₸: по ДП-2 комиссия 0 ₸.",
        "Кредит выдан 10 января, досрочное погашение 10 марта на 200 000 ₸: по разделу «Тарифы» "
        "комиссия 1% от суммы досрочного погашения.",
    ]
    assert any(w.startswith("[options_indistinct]") for w in log)


def test_ask_failure_falls_back_to_rules(doc, findings):
    def boom(stage, payload, schema):
        raise TimeoutError("503 из провайдера")
    log: list[str] = []
    qs = build_questions(doc, findings, boom, warnings=log)
    assert len(qs) == 4 and all(q.origin == "rule" for q in qs)
    assert any(w.startswith("[llm_failed]") for w in log)
    # без модели конфликт всё равно даёт два различимых исхода из witness
    assert len({o.observable_result for o in qs[0].options}) == 2


def test_merge_without_shared_requirement_or_block_is_rejected(doc, findings, qf):
    def m(resp, payload):
        ids = {f["id"]: g["group_id"] for g in payload["groups"] for f in g["findings"]}
        for q in resp["questions"]:
            if q["group_ids"] == [ids["F-03"]]:
                resp["questions"].append({**q, "group_ids": [ids["F-03"], ids["F-04"]]})
                break
    log: list[str] = []
    qs = build_questions(doc, findings, _wrap(doc, m), warnings=log)
    assert qf(qs, "F-03") is not qf(qs, "F-04")
    assert any(w.startswith("[merge_rejected]") for w in log)
    # собственные вопросы модели для обеих групп сохранились, а не заменены правилами
    assert qf(qs, "F-03").origin == qf(qs, "F-04").origin == "llm"
    assert qf(qs, "F-04").kind == "align_to_source"


def test_merge_with_shared_requirement_is_accepted(doc, findings, qf):
    # F-09 опирается на тот же фрагмент ДП-5, что F-04, и задевает R-03 вместе с F-03
    fs = findings + [dict(next(f for f in findings if f["id"] == "F-04"), id="F-09", req_ids=["R-03"])]

    def m(resp, payload):
        ids = {f["id"]: g["group_id"] for g in payload["groups"] for f in g["findings"]}
        sched = next(q for q in resp["questions"] if q["group_ids"] == [ids["F-03"]])
        resp["questions"].append({**sched, "group_ids": [ids["F-03"], ids["F-09"]]})

    qs = build_questions(doc, fs, _wrap(doc, m))
    assert qf(qs, "F-03").finding_ids == ["F-03", "F-04", "F-09"]
    assert len(qs) == 3


def test_llm_cannot_skip_critical_conflict(doc, findings, qf):
    def m(resp, payload):
        gid = next(g["group_id"] for g in payload["groups"] if any(f["id"] == "F-03" for f in g["findings"]))
        resp["questions"] = [q for q in resp["questions"] if q["group_ids"] != [gid]]
        resp["skipped"].append({"group_id": gid, "reason": "неважно"})
    qs = build_questions(doc, findings, _wrap(doc, m))
    assert qf(qs, "F-03").origin == "rule"


def test_limit_keeps_most_important_and_logs_queue(doc, findings, ask):
    log: list[str] = []
    qs = build_questions(doc, findings, ask, limit=2, warnings=log)
    assert [q.finding_ids for q in qs] == [["F-01", "F-02"], ["F-03"]]
    assert any(w.startswith("[queued]") and "F-05" in w for w in log)


@pytest.mark.parametrize("finding, family", [
    ({"kind": "conflict"}, "conflict"),
    ({"kind": "x", "criterion": "И7 Verifiable"}, "unverifiable"),
    ({"kind": "duplicate", "criterion": "И1"}, None),
    ({"kind": "template"}, None),
    ({"kind": "style", "needs_decision": True}, "ambiguity"),
    ({"kind": "gap", "needs_decision": False}, None),
    ({"kind": "whatever", "witness": {"input": "x"}}, "conflict"),
])
def test_decision_family(finding, family):
    assert decision_family(finding) == family
