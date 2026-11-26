"""Доказательство 1: смена правила на границе расчётного периода в независимом сюжете.

Кешбэк: до 30 июня включительно 1 %, с 1 июля 2 %, ставка определяется по дате совершения покупки
(Астана). Приёмка: покупка 30 июня 23:55, проведение 1 июля 00:05, ожидается 2 %. Две реальные
цитаты («… 1 % …» и «… 2 % — 200 ₸») поддерживают разные исходы одного события.
"""

from conftest import block_with, evidence_ok, requirements_from

from bcc_review.analysis.cross import review_set


def _conflicts(res):
    return [c for c in res["candidates"] if c["kind"] == "conflict"]


def test_boundary_event_gives_two_real_quotes_with_different_outcomes(load):
    doc = load("cashback_boundary.md")
    res = review_set(doc, requirements_from(doc))
    conflicts = _conflicts(res)
    assert len(conflicts) == 1, [c["title"] for c in res["candidates"]]
    w = conflicts[0]["witness"]

    # обе стороны — подтверждённые опоры текущего документа
    assert evidence_ok(doc, w["evidence_a"]) and evidence_ok(doc, w["evidence_b"])
    rule_block = block_with(doc, "До 30 июня включительно")
    acc_block = block_with(doc, "Покупка 30 июня в 23:55")
    assert w["evidence_a"]["block_id"] == rule_block["id"] and "1 %" in w["evidence_a"]["quote"]
    assert w["evidence_b"]["block_id"] == acc_block["id"] and "2 %" in w["evidence_b"]["quote"]

    # один конкретный вход: оба момента из документа, пояс — явная иллюстративная оговорка
    data = {x["value"]: x for x in w["input_detail"]["document_data"]}
    assert {"30 июня в 23:55", "1 июля в 00:05"} <= set(data)
    assert all(evidence_ok(doc, x["evidence"]) for x in w["input_detail"]["document_data"])
    assert [x["name"] for x in w["input_detail"]["illustrative"]] == ["пояс времени момента"]
    assert "UTC+5" in w["input_detail"]["illustrative"][0]["value"]

    # несовместимые исходы, вычисленные программой
    assert (w["outcome_a_value"], w["outcome_b_value"]) == ("1 %", "2 %")
    assert conflicts[0]["checks"] == {"evidence": "program", "preconditions": "program", "outcomes": "program"}
    # правило-якорь КБ-3 и правило КБ-1 — сторона A; КБ-2 лишь поддерживает исход B
    assert conflicts[0]["req_ids"] == ["R-01", "R-03"]
    assert conflicts[0]["acceptance_ids"] == ["AC-1"]
    assert any("Ставка определяется по дате совершения" in h["quote"] for h in conflicts[0]["hints"])


def test_same_period_row_is_compatible_and_coverage_keeps_denominator(load):
    doc = load("cashback_boundary.md")
    res = review_set(doc, requirements_from(doc))
    # вторая строка (1 июля → 2 %) совместима и залогирована как сравнение
    assert any(c["aspect"] == "period" and c["verdict"] == "compatible" and "Приёмка №2" in c["explanation"]
               for c in res["comparisons"])
    status = {c["obligation_id"]: c["status"] for c in res["coverage"]}
    assert status["КБ-1#1"] == "conflict" and status["КБ-3#1"] == "conflict"
    assert status["КБ-2#1"] == "partial"  # связана, но первая строка сама в конфликте — не covered
    s = res["coverage_summary"]
    assert s["denominator"] == 3 and s["covered"] == 0 and s["conflict"] == 2


def test_two_anchor_rules_with_different_events_conflict(load):
    """Вариант: два правила относят один объект к разным событиям при одинаковых условиях."""
    from p06_mdloader import load_markdown

    doc = load_markdown(
        "# Расходы\n\n## Часть A\n\n### Функциональные требования\n"
        "* **Р-1.** Месяц определяется по дате совершения покупки по времени Астаны.\n\n"
        "### Требования к интеграции\n"
        "Месяц определяется по дате проведения операции по времени Астаны.\n"
    )
    res = review_set(doc, requirements_from(doc))
    conflicts = _conflicts(res)
    assert len(conflicts) == 1
    w = conflicts[0]["witness"]
    assert w["outcome_a_value"] != w["outcome_b_value"]
    assert evidence_ok(doc, w["evidence_a"]) and evidence_ok(doc, w["evidence_b"])
    assert w["input_detail"]["document_data"] == [] and len(w["input_detail"]["illustrative"]) == 2
