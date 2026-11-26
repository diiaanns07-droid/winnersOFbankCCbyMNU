"""Ложные срабатывания и устойчивость к форме входа."""

import json

import pytest

from conftest import FIXTURES, requirements_from

from bcc_review.analysis.cross import review_set
from p06_mdloader import load_markdown

API_TAIL = (
    "\n## Часть B. REST API\n\n### Общие параметры\n\n| Поле | Значение |\n| :--- | :--- |\n"
    "| **REST type** | POST |\n| **Request URL** | `/alerts/saveLimit` |\n"
)


def test_push_through_service_is_not_a_promised_api_read():
    doc = load_markdown("# Д\n\n## Часть A\n\n### Требования к интеграции\n"
                        "Клиент получает push через сервис уведомлений.\n" + API_TAIL)
    res = review_set(doc, [])
    assert [c for c in res["candidates"] if c["kind"] == "missing_contract"] == []


def test_explicit_api_read_promise_without_read_method_is_a_gap():
    doc = load_markdown("# Д\n\n## Часть A\n\n### Требования к интеграции\n"
                        "Приложение получает настройки через REST API.\n" + API_TAIL)
    gaps = [c for c in review_set(doc, [])["candidates"] if c["kind"] == "missing_contract"]
    assert len(gaps) == 1 and gaps[0]["found"] == ["POST /alerts/saveLimit — сохранение"]


def test_ambiguous_event_stamp_does_not_produce_conflict():
    doc = load_markdown(
        "# Д\n\n## Часть A\n\n### Функциональные требования\n"
        "* **Ф-1.** Месяц определяется по дате совершения покупки в Алматы.\n\n### Критерии приемки\n\n"
        "| Исходные условия | Действие | Ожидаемый результат |\n| :--- | :--- | :--- |\n"
        "| 31 января в 23:58 | Покупка проведена 1 февраля в 00:03 | Январский счётчик вырос |\n"
    )
    res = review_set(doc, requirements_from(doc))
    assert [c for c in res["candidates"] if c["kind"] == "conflict"] == []


def test_acceptance_table_as_single_requirement_gets_unique_ids():
    doc = load_markdown((FIXTURES / "case_ab.md").read_text(encoding="utf-8"), table_mode="table")
    reqs = requirements_from(doc)
    acc_block = next(b for b in doc["blocks"] if b["kind"] == "table" and "Ожидаемый результат" in b["text"])
    reqs.append({"id": "R-AC", "source_id": None, "text": acc_block["text"], "block_ids": [acc_block["id"]], "evidence": []})
    res = review_set(doc, reqs)
    ids = [a["acceptance_id"] for a in res["acceptance"]]
    assert ids == ["AC-1", "AC-2", "AC-3"]
    assert res["coverage_summary"]["denominator"] == 10  # строки приёмки не стали обязательствами


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.md")))
def test_result_is_json_serializable_and_contract_shaped(name):
    doc = load_markdown(FIXTURES / name)
    res = review_set(doc, requirements_from(doc), fact_hints={"facts": []})
    json.dumps(res, ensure_ascii=False)
    assert {"facts", "coverage", "candidates", "warnings"} <= set(res)
    for c in res["candidates"]:
        assert {"scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints"} <= set(c)
        assert c["scope"] in ("requirement", "set") and c["severity"] in ("critical", "major", "minor")
        if c["kind"] == "conflict":
            assert {"input", "outcome_a", "outcome_b", "evidence_a", "evidence_b"} <= set(c["witness"])
        if c["kind"] == "missing_contract":
            assert c["inspected_block_ids"]
    for cv in res["coverage"]:
        assert {"req_id", "obligation", "acceptance_ids", "status", "explanation", "hints"} <= set(cv)
        assert cv["status"] in ("covered", "partial", "conflict", "uncovered", "unknown")
