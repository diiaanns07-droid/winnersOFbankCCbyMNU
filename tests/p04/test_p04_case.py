"""Кейс BCC-HUB: docs/requirements.md @928c1aa364265426105b69ba7a3444eac11b22db.

Идентификаторы и суммы задания используются только здесь, в тестах конкретного кейса.
"""

from __future__ import annotations

import hashlib

from bcc_review.analysis.inventory import build_inventory
from p04_support import FIXTURES, QuoteModel, assert_invariants, block_by_text, fates, fixture_document, load_spec

CASE_SHA256 = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"


def _doc():
    return fixture_document("case_requirements.md")


def test_fixture_is_the_published_case():
    raw = (FIXTURES / "case_requirements.md").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CASE_SHA256 == _doc()["id"]


def test_case_rules_only():
    doc = _doc()
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    reqs = inv["requirements"]
    by_sid = {}
    for r in reqs:
        by_sid.setdefault(r["source_id"], []).append(r)
    # Ф-2 — четыре правила в одном пункте
    assert [len(by_sid[k]) for k in ("Ф-1", "Ф-2", "Ф-3", "Ф-4")] == [2, 4, 2, 2]
    assert len(reqs) == 49 and inv["block_coverage"]["source_units"] == 39
    # критерии приёмки и контракт доступны сквозной проверке
    assert inv["block_coverage"]["by_kind"]["acceptance"] == 3
    assert inv["block_coverage"]["by_kind"] == {"ui": 3, "functional": 10, "nonfunctional": 1, "data": 1,
                                          "integration": 2, "acceptance": 3, "contract": 29}
    # «1.» в «Логике работы метода» и в «Особых правилах» — разные пункты
    ones = [r for r in reqs if r["source_id"] == "1"]
    assert [r["source_ref"] for r in ones] == ["Логика работы метода › 1", "Особые правила › 1"]
    # статусы: номер из строки, а для абзаца под «403. Forbidden» — из заголовка
    status = {r["source_id"] for r in reqs if r["kind"] == "contract" and (r["source_id"] or "").isdigit()
              and len(r["source_id"]) == 3}
    assert status == {"200", "400", "401", "403", "500"}
    fourteen = next(r for r in reqs if "Для чужой карты" in r["hints"][0]["quote"])
    assert fourteen["source_id"] == "403" and fourteen["source_ref"] == "403. Unsuccessful — Forbidden"
    # шаблоны банка исключены с причиной; подпись — не требование
    blocks_of = {}
    for g in inv["excluded"]:
        blocks_of.setdefault(g["category"], []).extend(g["block_ids"])
    checklist = blocks_of["review_checklist"]
    assert len(checklist) == 16  # абзац-пояснение, шапка и 14 пунктов чек-листа
    assert sum(1 for g in inv["excluded"] if g["category"] == "review_checklist") == 2  # у групп разные причины
    sign = block_by_text(doc, "| | | |")["id"]
    assert fates(inv)[sign] == "excluded" and sign in blocks_of["approval"]
    assert block_by_text(doc, "заполняются тестировщиками")["id"] in blocks_of["placeholder"]
    # без модели схемы остаются явным остатком
    assert inv["unprocessed_block_ids"] == [
        block_by_text(doc, "Мобильное приложение → сервис настроек")["id"],
        block_by_text(doc, "Проведение покупки → пересчёт расходов")["id"],
        block_by_text(doc, "Процессинг → сервис расходов")["id"],
        block_by_text(doc, "Приложение → AlertsController")["id"],
    ]
    assert inv["block_coverage"]["level"] == "partial"


def test_case_rules_facts_for_code_checks():
    inv = build_inventory(_doc())
    facts = inv["fact_hints"]
    amount = {f["direction"]: f for f in facts if f["field"] == "amount"}
    assert amount["request"]["type"] == "integer" and amount["response"]["type"] == "string"
    assert amount["request"]["db_field"] == amount["response"]["db_field"] == "limit_kzt"
    assert amount["request"]["range"] == {"min": 1000, "max": 1000000, "min_inclusive": None, "max_inclusive": None}
    enabled = {f["direction"]: f for f in facts if f["field"] == "enabled"}
    assert enabled["request"]["values"] == enabled["response"]["values"] == ["0", "1"]
    assert enabled["request"]["type"] == "integer" and enabled["response"]["type"] == "string"
    units = {(f["field"], f["unit"]) for f in facts if f["unit"]}
    assert ("сумму покупки", "тиын") in units and ("порог", "тенге") in units
    f1 = next(f for f in facts if f["range"] and f["range"]["min"] == 1000 and f["direction"] == "business")
    assert f1["range"]["min_inclusive"] is True and f1["unit"] == "тенге"


def test_case_with_golden_model_single_call_full_coverage():
    doc = _doc()
    model = QuoteModel(load_spec("case_model_spec.json"), doc)
    inv = build_inventory(doc, model)
    assert_invariants(doc, inv)
    assert len(model.calls) == 1 and inv["block_coverage"]["level"] == "complete"
    assert inv["block_coverage"]["llm_status"] == "complete" and inv["mode"] == "rules_plus_llm"
    reqs = inv["requirements"]
    assert len(reqs) == 58
    f1 = [r for r in reqs if r["source_id"] == "Ф-1"]
    assert [r["id"] for r in f1] == ["R-002.1", "R-002.2", "R-002.3", "R-002.4", "R-002.5"]
    assert [r["hints"][0]["quote"] for r in f1] == [
        "Держатель активной карты KZT задаёт", "целый порог", "от 1 000", "до 1 000 000 ₸ включительно",
        "По умолчанию уведомление выключено"]
    # двойной пробел в ответе модели исправлен на дословный фрагмент источника
    amount = next(r for r in reqs if r["text"].startswith("Query-параметр amount"))
    assert amount["hints"][0]["quote"] == "`amount` | integer | 32 bit | Да | 1 000–1 000 000"
    assert inv["block_coverage"]["evidence"]["repaired"] == 1
    # шаг sequence с передачей данных — обязательство интеграции, архитектура — design
    seq = [r for r in reqs if r["kind"] == "integration" and r["section"][-1] == "Sequence Diagram"]
    assert len(seq) == 3
    design = next(g for g in inv["excluded"] if g["category"] == "design")
    assert len(design["block_ids"]) == 3 and design["cross_check"] is True
    # пустые строки модели — неизвестность, а не значение
    last = next(f for f in inv["fact_hints"] if f["origin"] == "llm" and f["range"] and f["range"]["min"] is None
                and f["range"]["min_inclusive"] is True)
    assert last["value"] is None and last["condition"] is None
    # правила дополняют факты, которых модель не дала (cardId, result, message)
    assert {f["field"] for f in inv["fact_hints"] if f["origin"] == "rules"} == {"cardId", "result", "message"}
