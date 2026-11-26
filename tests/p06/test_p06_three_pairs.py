"""Доказательство 4: три пары фактов и соседство 200/ERROR.

1) явно разные границы одного поля → подтверждаемое расхождение с witness;
2) одна сумма в тенге и тиынах (1 ₸ и 100 тиын) → совместимо;
3) integer в запросе и string в ответе с оговорённым строковым представлением → совместимо.
Пример ERROR под 200 при статусе 401 «не передан токен» не даёт ни конфликта, ни вопроса.
"""

from decimal import Decimal

from conftest import evidence_ok, requirements_from

from bcc_review.analysis.cross import review_set
from bcc_review.analysis.facts import reconcile_facts


def test_only_explicit_bounds_mismatch_is_confirmed(load):
    doc = load("transfers_pairs.md")
    res = review_set(doc, requirements_from(doc))
    conflicts = [c for c in res["candidates"] if c["kind"] == "conflict"]
    assert len(conflicts) == 1, [c["title"] for c in res["candidates"]]
    c = conflicts[0]
    assert "Разные границы" in c["title"]
    w = c["witness"]
    assert evidence_ok(doc, w["evidence_a"]) and evidence_ok(doc, w["evidence_b"])
    assert w["evidence_a"]["quote"] == "от 100 до 500 000 ₸ включительно"
    assert w["evidence_b"]["quote"] == "100–300 000"
    # минимальный пример: иллюстративное значение отделено от границ из документа
    assert w["input"]["illustrative"][0]["value"] == "300 001 ₸"
    assert {x["value"] for x in w["input"]["document_data"]} == {"100 ₸–500 000 ₸", "100 ₸–300 000 ₸"}
    assert "допустимо" in w["outcome_a"] and "отклоняется" in w["outcome_b"]
    # нет вопросов: остальные пары совместимы
    assert [x for x in res["candidates"] if x["kind"] == "question"] == []


def test_tenge_and_tiyn_same_amount_compatible(load):
    doc = load("transfers_pairs.md")
    out = reconcile_facts(doc)
    facts = {f["id"]: f for f in out["facts"]}
    vals = [c for c in out["comparisons"] if c["aspect"] == "value"]
    assert len(vals) == 1 and vals[0]["verdict"] == "compatible"
    a, b = (facts[i] for i in vals[0]["fact_ids"])
    assert {a["unit"], b["unit"]} == {"KZT", "tiyn"}
    assert a["value_minor"] == b["value_minor"] == 100  # точный тип: целые тиыны
    assert isinstance(a["value_minor"], int) and Decimal(a["value"]) in (Decimal(1), Decimal(100))


def test_request_integer_response_string_with_stated_representation(load):
    doc = load("transfers_pairs.md")
    out = reconcile_facts(doc)
    types = [c for c in out["comparisons"] if c["aspect"] == "type"]
    assert types and all(c["verdict"] == "compatible" for c in types)
    assert "строковое представление оговорено" in types[0]["explanation"]
    assert evidence_ok(doc, types[0]["evidence"])


def test_200_error_next_to_unrelated_401_is_not_a_conflict(load):
    doc = load("transfers_pairs.md")
    out = reconcile_facts(doc)
    http = [c for c in out["comparisons"] if c["aspect"] == "http_outcome"]
    assert http and all(c["verdict"] == "compatible" for c in http)
    assert out["candidates"] and all("HTTP" not in c["title"] for c in out["candidates"])


def test_type_mismatch_without_stated_conversion_goes_to_question():
    from p06_mdloader import load_markdown

    doc = load_markdown(
        "# API\n\n## Часть B. REST API\n\n### Параметры запроса\n\n"
        "| Parameter | Format | Logic | Description |\n| :--- | :--- | :--- | :--- |\n"
        "| `limit` | integer | 1–10 | Лимит |\n\n### Ответ\n\n"
        "| Parameter | Format | Logic | Description |\n| :--- | :--- | :--- | :--- |\n"
        "| `limit` | string | При успехе | Лимит |\n"
    )
    res = review_set(doc, [])
    assert [c["kind"] for c in res["candidates"]] == ["question"]
    assert res["candidates"][0]["severity"] == "minor"
