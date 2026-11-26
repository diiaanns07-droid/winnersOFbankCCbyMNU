"""Набор 1. Атомарность: один пункт — несколько проверяемых обязательств с общим источником.

Пункт П-1 задаёт нижнюю границу, верхнюю границу и поведение по умолчанию. Каждое обязательство
получает уникальный внутренний ID, общий source_id и группу, а цитата остаётся дословной.
Одинаковый локальный номер «1.» в разных разделах — разные пункты.
"""

from __future__ import annotations

from bcc_review.analysis.inventory import build_inventory
from p04_support import QuoteModel, assert_invariants, block_by_text, md_document, warned

ATOMIC_MD = """# Лимит переводов

## Функциональные требования

* **П-1.** Клиент задаёт лимит от 100 до 50 000 ₸ включительно. По умолчанию лимит выключен.
* **П-2.** Изменение лимита вступает в силу сразу.

## Правила обработки

1. Сумма округляется до целого тенге.
2. Повторный запрос с тем же ключом не создаёт новый перевод.

## Правила отображения

1. Лимит показывается на экране перевода.

## Схема взаимодействия

Приложение → сервис лимитов → процессинг.
"""

ATOMIC_SPEC = {
    "items": [
        {"kind": "functional", "source_id": "П-1", "text": "Нижняя граница лимита — 100 ₸ включительно", "quotes": ["от 100"]},
        {"kind": "functional", "source_id": "П-1", "text": "Верхняя граница лимита — 50 000 ₸ включительно", "quotes": ["до 50 000 ₸ включительно"]},
        {"kind": "functional", "source_id": "П-1", "text": "По умолчанию лимит выключен", "quotes": ["По умолчанию лимит выключен"]},
        {"kind": "functional", "source_id": "П-2", "text": "Новый лимит действует сразу после изменения", "quotes": ["Изменение лимита вступает в силу сразу"]},
        {"kind": "functional", "source_id": "1", "text": "Сумма округляется до целого тенге", "quotes": ["Сумма округляется до целого тенге"]},
        {"kind": "functional", "source_id": "2", "text": "Повтор запроса с тем же ключом не создаёт перевод", "quotes": ["Повторный запрос с тем же ключом не создаёт новый перевод"]},
        {"kind": "ui", "source_id": "1", "text": "Лимит виден на экране перевода", "quotes": ["Лимит показывается на экране перевода"]},
    ],
    "excluded": [
        {"category": "design", "reason": "Схема взаимодействия без самостоятельного обязательства", "contains": ["Приложение → сервис лимитов"]},
    ],
    "facts": [
        {"subject": "лимит", "field": "лимит", "direction": "business", "type": None, "value": None, "unit": "₸",
         "range": {"min": 100, "max": 50000, "min_inclusive": True, "max_inclusive": True}, "condition": None,
         "quotes": ["лимит от 100 до 50 000 ₸ включительно"]},
    ],
}


def _doc():
    return md_document(ATOMIC_MD, "atomic.md")


def test_three_obligations_share_source_and_keep_verbatim_quotes():
    doc = _doc()
    inv = build_inventory(doc, QuoteModel(ATOMIC_SPEC, doc))
    assert_invariants(doc, inv)
    p1 = [r for r in inv["requirements"] if r["source_id"] == "П-1"]
    assert [r["id"] for r in p1] == ["R-001.1", "R-001.2", "R-001.3"]
    assert {r["group"] for r in p1} == {"R-001"}
    assert [r["text"] for r in p1] == [
        "Нижняя граница лимита — 100 ₸ включительно",
        "Верхняя граница лимита — 50 000 ₸ включительно",
        "По умолчанию лимит выключен",
    ]
    source = block_by_text(doc, "**П-1.**")
    # общий источник восстанавливается: все три опоры в одном блоке с номером П-1
    assert {bid for r in p1 for bid in r["block_ids"]} == {source["id"]}
    assert all(r["source_ref"] == "Функциональные требования › П-1" for r in p1)
    for r in p1:
        (h,) = r["hints"]
        assert h["quote"] in source["text"]
    # краткая формулировка — пересказ, доказательство — дословная подстрока
    assert p1[0]["text"] != p1[0]["hints"][0]["quote"]
    # факт с явными границами и единицей для сверки кодом
    fact = next(f for f in inv["fact_hints"] if f["origin"] == "llm")
    assert fact["range"] == {"min": 100, "max": 50000, "min_inclusive": True, "max_inclusive": True}
    assert fact["unit"] == "тенге"
    # факт связан только с теми атомами, чьи опоры пересекаются с его цитатой (границы, не «по умолчанию»)
    assert fact["req_ids"] == ["R-001.1", "R-001.2"]


def test_rules_only_splits_sentences_and_keeps_parent_id():
    doc = _doc()
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    p1 = [r for r in inv["requirements"] if r["source_id"] == "П-1"]
    assert [r["id"] for r in p1] == ["R-001.1", "R-001.2"]
    assert p1[0]["hints"][0]["quote"] == "Клиент задаёт лимит от 100 до 50 000 ₸ включительно."
    assert p1[1]["hints"][0]["quote"] == "По умолчанию лимит выключен."
    ranges = [f for f in inv["fact_hints"] if f["range"]]
    assert ranges[0]["range"] == {"min": 100, "max": 50000, "min_inclusive": True, "max_inclusive": True}
    assert ranges[0]["unit"] == "тенге" and ranges[0]["direction"] == "business"
    default = next(f for f in inv["fact_hints"] if f["condition"] == "по умолчанию")
    assert (default["field"], default["value"]) == ("лимит", "выключен")
    rounding = next(f for f in inv["fact_hints"] if f["type"] == "integer")
    assert rounding["unit"] == "тенге" and rounding["field"] is None
    # схема без номера в rules_only — явный остаток с причиной, а не потеря
    design = block_by_text(doc, "Приложение → сервис лимитов")
    assert inv["unprocessed_block_ids"] == [design["id"]]
    assert "семантический этап" in inv["block_coverage"]["blocks"][-1]["reason"]


def test_same_local_number_in_different_sections_is_not_merged():
    doc = _doc()
    for inv in (build_inventory(doc), build_inventory(doc, QuoteModel(ATOMIC_SPEC, doc))):
        ones = [r for r in inv["requirements"] if r["source_id"] == "1"]
        assert len(ones) == 2
        assert ones[0]["id"] != ones[1]["id"] and ones[0]["group"] != ones[1]["group"]
        assert [r["source_ref"] for r in ones] == ["Правила обработки › 1", "Правила отображения › 1"]
        assert ones[0]["section"] != ones[1]["section"]
        assert not warned(inv, "duplicate_source_id")


def test_duplicate_number_inside_one_section_is_reported():
    md = "# Док\n\n## Правила\n\n1. Первое правило действует всегда.\n2. Второе правило.\n1. Снова первое правило.\n"
    doc = md_document(md)
    inv = build_inventory(doc)
    ones = [r for r in inv["requirements"] if r["source_id"] == "1"]
    assert len(ones) == 2 and ones[0]["group"] != ones[1]["group"]
    assert warned(inv, "duplicate_source_id", "«1»")


def test_ids_reproducible_and_independent_of_model_output_order():
    doc = _doc()

    def reverse(resp, call_no, payload):
        resp["items"] = list(reversed(resp["items"]))
        resp["excluded"] = list(reversed(resp["excluded"]))
        return resp

    a = build_inventory(doc, QuoteModel(ATOMIC_SPEC, doc))
    b = build_inventory(doc, QuoteModel(ATOMIC_SPEC, doc))
    c = build_inventory(doc, QuoteModel(ATOMIC_SPEC, doc, mutate=reverse))
    assert a == b
    key = [(r["id"], r["text"], r["hints"]) for r in a["requirements"]]
    assert key == [(r["id"], r["text"], r["hints"]) for r in c["requirements"]]


def test_sentence_split_respects_abbreviations_and_numbers():
    md = ("# Док\n\n## Требования\n\n"
          "1. Комиссия 1,5 % взимается с переводов, платежей и т. д. по тарифу банка. Тариф утверждает "
          "А. Б. Иванов. Срок — 3 дня.\n")
    doc = md_document(md)
    inv = build_inventory(doc)
    texts = [r["hints"][0]["quote"] for r in inv["requirements"]]
    assert texts == [
        "Комиссия 1,5 % взимается с переводов, платежей и т. д. по тарифу банка.",
        "Тариф утверждает А. Б. Иванов.",
        "Срок — 3 дня.",
    ]
