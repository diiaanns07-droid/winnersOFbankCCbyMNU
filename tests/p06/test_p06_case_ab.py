"""Кейс организаторов (часть A + REST API B): идентификаторы и суммы из задания.

Офлайн: К1 (приёмка №2 ↔ Ф-2 на стыке 31.01/01.02), К4 (обещано чтение — метода нет),
200-ERROR/400 — вопрос (без общего входа), границы/единицы/типы совместимы.
С подставной моделью: К2 (Ф-3 ↔ Ф-4) и К3 (неверная сумма: 400 или 200 с ERROR) подтверждаются
программой по ограничениям и фактам; вопрос 200/400 снимается.
"""

import pytest

from p06_helpers import ScriptedAsk, block_with, evidence_ok, requirements_from

from bcc_review.analysis.cross import review_set
from bcc_review.analysis.facts import reconcile_facts


def by_kind(res, kind):
    return [c for c in res["candidates"] if c.get("subkind") == kind]


@pytest.mark.parametrize("loader,mode", [("engine", "row"), ("p06", "row"), ("p06", "table")])
def test_offline_case_findings(load, loader, mode):
    """Штатный читатель движка и синтетический (с разметкой, строка/целая таблица) дают одно и то же."""
    doc = load("case_ab.md", loader=loader, table_mode=mode)
    reqs = requirements_from(doc)
    assert [r["source_id"] for r in reqs] == ["Ф-1", "Ф-2", "Ф-3", "Ф-4"]
    res = review_set(doc, reqs)

    # К1: witness на данных документа, обе опоры из текста
    k1 = by_kind(res, "conflict")
    assert len(k1) == 1
    w = k1[0]["witness"]
    assert w["evidence_a"]["quote"] == "Месяц определяется по дате совершения покупки в Алматы."
    assert w["evidence_b"]["quote"] == "Февральский счётчик вырос на 4 000 ₸"
    assert (w["outcome_a_value"], w["outcome_b_value"]) == ("январь", "февраль")
    assert {x["value"] for x in w["input_detail"]["document_data"]} >= {"31 января в 23:58", "1 февраля в 00:03 по Алматы"}
    assert all(evidence_ok(doc, x["evidence"]) for x in w["input_detail"]["document_data"])
    assert w["input_detail"]["illustrative"][0]["value"] == "Алматы (UTC+5)"
    assert k1[0]["req_ids"] == ["R-02"] and k1[0]["acceptance_ids"] == ["AC-2"]

    # К4: обещание, границы просмотра и что искали
    gap = by_kind(res, "missing_contract")
    assert len(gap) == 1
    g = gap[0]
    assert "читает и сохраняет настройки" in g["promise"]["quote"] and evidence_ok(doc, g["promise"])
    assert g["inspected_scope"]["span"] in ("строки 95–197", "строки 95–198")  # читатели по-разному считают ограду кода
    assert g["found"] == ["GET /alerts/saveLimit — сохранение"]
    assert any("get/read/list" in s for s in g["searched_for"])
    controller = next(b["id"] for b in doc["blocks"] if "AlertsController" in b["text"] and "table" in b["kind"])
    assert {controller, block_with(doc, "Проверьте сумму")["id"]} <= set(g["inspected_block_ids"])

    # 200-ERROR и 400: только вопрос
    q = [c for c in by_kind(res, "question") if "HTTP 200" in c["title"]]
    assert len(q) == 1 and "Проверьте сумму" in q[0]["question"]

    # совместимые сравнения по фактам
    cmp = {(c["aspect"], c["verdict"]) for c in res["comparisons"]}
    assert ("range", "compatible") in cmp and ("type", "compatible") in cmp and ("size", "compatible") in cmp
    assert ("range", "mismatch") not in cmp

    # покрытие: 10 обязательств, связь ≠ покрытие
    s = res["coverage_summary"]
    assert s["denominator"] == 10 and s["covered"] == 0 and s["conflict"] == 1
    st = {c["obligation_id"]: c["status"] for c in res["coverage"]}
    assert st["Ф-2#1"] == "conflict" and st["Ф-1#1"] == "uncovered" and st["Ф-4#1"] == "uncovered"


def test_facts_table_has_exact_money_and_evidence(case_doc):
    out = reconcile_facts(case_doc)
    facts = out["facts"]
    amount = [f for f in facts if f["field"] == "amount" and f["direction"] == "request"][0]
    assert amount["range"] == {"min": "1000", "max": "1000000", "min_inclusive": True, "max_inclusive": True,
                               "min_minor": 100000, "max_minor": 100000000}
    assert amount["binding"] == "limit_kzt" and amount["unit"] == "KZT" and amount["type"] == "integer"
    assert amount["enriched_by"]  # включённость границ — из «Особых правил»
    purchase = [f for f in facts if f["field"] == "сумму покупки"][0]
    assert purchase["unit"] == "tiyn"
    for f in facts:
        assert f["evidence"] and all(evidence_ok(case_doc, e) for e in f["evidence"]), f["id"]
        for k in ("subject", "field", "scope", "direction", "type", "value", "range", "unit", "condition", "evidence"):
            assert k in f


def _amount_fact_id(doc):
    return next(f["id"] for f in reconcile_facts(doc)["facts"] if f["field"] == "amount" and f["direction"] == "request")


def _k2(pa, pb):
    qa = "На карту приходится максимум один такой push за календарный месяц."
    qb = "Если она ниже нового порога, следующее достижение вызывает push независимо от истории предыдущей настройки."
    return {
        "verdict": "conflict",
        "title": "Ф-3 и Ф-4 дают разный ответ о втором push в месяце",
        "impact": "После смены порога реализация не знает, отправлять ли второй push в том же месяце.",
        "a": {"object": "push о достижении порога", "owner": "карта", "condition": "push в этом месяце уже был",
              "moment": "календарный месяц", "expected": "второй push не отправляется", "quote": qa,
              "constraints": [{"var": "push в текущем месяце уже отправлен", "op": "eq", "value": "да"}]},
        "b": {"object": "push о достижении порога", "owner": "карта", "condition": "порог изменён, сумма ниже нового",
              "moment": "следующее достижение", "expected": "push отправляется", "quote": qb,
              "constraints": [{"var": "порог изменён", "op": "eq", "value": "да"},
                              {"var": "накопленная сумма после смены", "op": "lt", "value": "$новый порог"}]},
        "witness": {
            "input": [
                {"var": "push в текущем месяце уже отправлен", "value": "да", "source": "illustrative",
                 "why": "10 января расходы достигли порога 50 000 ₸"},
                {"var": "порог изменён", "value": "да", "source": "illustrative", "why": "15 января порог 60 000 ₸"},
                {"var": "накопленная сумма после смены", "value": "50 000 ₸", "source": "illustrative"},
                {"var": "новый порог", "value": "60 000 ₸", "source": "illustrative"},
            ],
            "outcome_a": "второй push в январе не отправляется", "outcome_b": "push отправляется",
            "outcome_target": "push при достижении 60 000 ₸ 20 января", "outcome_a_value": "нет", "outcome_b_value": "да",
            "evidence_a": {"block_id": pa["block_id"], "quote": "максимум один такой push за календарный месяц"},
            "evidence_b": {"block_id": pb["block_id"], "quote": "следующее достижение вызывает push независимо от истории предыдущей настройки"},
        },
    }


def _k3(fact_id, status_block, example_block):
    def build(pa, pb):
        return {
            "verdict": "conflict",
            "title": "Неверная сумма описана двумя исходами: 400 и 200 с ERROR",
            "a": {"condition": "параметры запроса заполнены неверно", "expected": "HTTP 400",
                  "constraints": [{"var": "amount", "op": "outside", "value": f"range:{fact_id}"}]},
            "b": {"condition": "при отклонении суммы — результат ERROR (пример под 200)", "expected": "HTTP 200, result=ERROR",
                  "constraints": [{"var": "amount", "op": "outside", "value": f"range:{fact_id}"}]},
            "witness": {
                "input": [{"var": "amount", "value": "999", "source": "illustrative",
                           "why": "на 1 ₸ ниже нижней границы 1 000 из Logic"}],
                "outcome_a": "HTTP 400 «Некорректный запрос»", "outcome_b": "HTTP 200 с {\"result\":\"ERROR\"}",
                "outcome_target": "код HTTP-ответа", "outcome_a_value": "400", "outcome_b_value": "200",
                "evidence_a": {"block_id": status_block, "quote": "Ответ в случае, если параметры запроса заполнены неверно."},
                "evidence_b": {"block_id": example_block, "quote": "{\"result\":\"ERROR\",\"message\":\"Проверьте сумму\"}"},
            },
        }
    return build


def test_case_with_scripted_model_confirms_k2_k3(case_doc):
    doc = case_doc
    fid = _amount_fact_id(doc)
    status_block = block_with(doc, "параметры запроса заполнены неверно")["id"]
    example_block = block_with(doc, "Проверьте сумму")["id"]
    ask = ScriptedAsk(pair_rules=[
        ("максимум один такой push", "независимо от истории", _k2),
        ("заполнены неверно", "Проверьте сумму", _k3(fid, status_block, example_block)),
    ])
    res = review_set(doc, requirements_from(doc), ask)
    assert len(ask.matched) == 2, ask.matched
    stages = [c[0] for c in ask.calls]
    assert stages.count("cross#pairs") == 2 and stages.count("cross#coverage") == 1
    assert res["stats"]["mode"] == "rules_plus_llm" and res["stats"]["llm_calls"] == 3

    conf = {c["title"]: c for c in by_kind(res, "conflict")}
    k2 = conf["Ф-3 и Ф-4 дают разный ответ о втором push в месяце"]
    assert k2["checks"]["preconditions"] == "program" and k2["req_ids"] == ["R-03", "R-04"]
    assert k2["slots"]["a"]["expected"] == "второй push не отправляется"
    k3 = conf["Неверная сумма описана двумя исходами: 400 и 200 с ERROR"]
    assert k3["checks"]["preconditions"] == "program"
    for c in (k2, k3):
        assert evidence_ok(doc, c["witness"]["evidence_a"]) and evidence_ok(doc, c["witness"]["evidence_b"])
    # вопрос 200/400 снят подтверждённым конфликтом на тех же опорах
    assert not [c for c in by_kind(res, "question") if "HTTP 200" in c["title"]]
    assert any(c["aspect"] == "question" and c["verdict"] == "resolved" for c in res["comparisons"])
    # К1 и К4 по правилам сохранились
    assert any("стыке периодов" in t for t in conf) and by_kind(res, "missing_contract")


def test_model_with_disjoint_amount_conditions_is_rejected(case_doc):
    """Если вход модели не нарушает границу, «конфликт» 400/200 отклоняется как совместимость."""
    doc = case_doc
    fid = _amount_fact_id(doc)
    build = _k3(fid, block_with(doc, "параметры запроса заполнены неверно")["id"], block_with(doc, "Проверьте сумму")["id"])

    def inside(pa, pb):
        r = build(pa, pb)
        r["witness"]["input"][0]["value"] = "50000"
        return r

    res = review_set(doc, requirements_from(doc), ScriptedAsk(pair_rules=[("заполнены неверно", "Проверьте сумму", inside)]))
    assert not [c for c in by_kind(res, "conflict") if "400" in c["title"]]
    assert any(c["aspect"] == "semantic" and c["verdict"] == "compatible" and "amount" in c["explanation"]
               for c in res["comparisons"])


def test_fabricated_quote_is_rejected_and_counted(case_doc):
    def fake(pa, pb):
        r = _k2(pa, pb)
        r["witness"]["evidence_b"]["quote"] = "push отправляется всегда при смене порога"
        return r

    res = review_set(case_doc, requirements_from(case_doc),
                     ScriptedAsk(pair_rules=[("максимум один такой push", "независимо от истории", fake)]))
    assert not [c for c in by_kind(res, "conflict") if "Ф-3 и Ф-4" in c["title"]]
    q = [c for c in by_kind(res, "question") if "Ф-3 и Ф-4" in c["title"]]
    assert q and "опор не найдена" in q[0]["reason"]
    assert res["evidence_audit"]["rejected"] >= 1


def test_provider_failure_keeps_rule_results(case_doc):
    ask = ScriptedAsk(fail_stages={"cross#pairs", "cross#coverage"})
    res = review_set(case_doc, requirements_from(case_doc), ask)
    assert res["stats"]["status"] == "partial" and set(res["stats"]["llm_failed"]) == {"cross#pairs", "cross#coverage"}
    assert any("не удалось" in w for w in res["warnings"])
    assert by_kind(res, "conflict") and by_kind(res, "missing_contract")
    assert res["coverage_summary"]["denominator"] == 10 and res["coverage_summary"]["covered"] == 0


def test_cross_section_pass_covers_role_pairs(case_doc):
    ask = ScriptedAsk()
    res = review_set(case_doc, requirements_from(case_doc), ask)
    roles = res["stats"]["pairs_by_role"]
    for rp in ("business_rules×acceptance", "business_rules×business_rules", "business_rules×ui",
               "business_rules×integration", "integration×api", "ui×api", "acceptance×api"):
        assert roles.get(rp, 0) > 0, (rp, roles)
    sent = [p for stage, payload, _ in ask.calls if stage == "cross#pairs" for p in payload["input"]["pairs"]]
    assert len(sent) == res["stats"]["pairs_selected"] <= 60
    assert {p["selected_by"] for p in sent} == {"facts_hint", "cross_section", "entities"}
