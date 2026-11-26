"""Модульные проверки №06: опоры, деньги, даты, подсказки №04, ограничения witness."""

from decimal import Decimal

from p06_helpers import evidence_ok

from bcc_review.analysis.cross import eval_constraint, outcomes_incompatible, sentence_spans
from bcc_review.analysis.facts import (
    Audit, DocView, Resolver, extract_facts, find_stamps, fmt_money, parse_money, reconcile_facts, to_minor,
)

DOC = {
    "id": "x", "title": "t", "format": "md", "warnings": [],
    "blocks": [
        {"id": "b1", "kind": "paragraph", "section": ["T", "Цели"], "text": "Клиент   **видит** порог «1 000 ₸».", "loc": {"line_start": 1}},
        {"id": "b2", "kind": "paragraph", "section": ["T", "Цели"], "text": "Порог хранится в тенге. Порог хранится в тенге.", "loc": {"line_start": 2}},
    ],
}


def test_resolver_exact_normalized_relocated_rejected():
    audit = Audit()
    r = Resolver(DocView(DOC), external=False, audit=audit)  # локальный путь №06
    ev = r({"block_id": "b1", "quote": "Клиент видит порог \"1 000 ₸\""})  # пробелы, Markdown и кавычки
    assert ev and evidence_ok(DOC, ev) and ev["quote"].startswith("Клиент   **видит**")
    ev2 = r({"block_id": "b1", "quote": "Порог хранится в тенге"})  # не тот блок → перенос
    assert ev2["block_id"] == "b2"
    assert r({"block_id": "b2", "quote": "Порог хранится в тенге"})  # дважды в блоке → ambiguous
    assert r({"block_id": "b1", "quote": "порог в тиынах"}) is None
    d = audit.as_dict()
    assert (d["checked"], d["confirmed"], d["relocated"], d["ambiguous"], d["rejected"]) == (4, 1, 1, 1, 1)


def test_default_resolver_is_07_and_counts_statuses():
    """По умолчанию цитаты проверяет №07 (или резерв движка) — ответы {status, evidence}."""
    from bcc_review.analysis.facts import auto_resolver

    if auto_resolver() is None:
        import pytest

        pytest.skip("резолвер №07 и резерв движка недоступны вне ветки интеграции")
    audit = Audit()
    r = Resolver(DocView(DOC), audit=audit)
    assert audit.via_07
    ev = r({"block_id": "b1", "quote": "Клиент   **видит** порог"})
    assert ev and evidence_ok(DOC, ev)
    assert r({"block_id": "b1", "quote": "порог в тиынах"}) is None
    d = audit.as_dict()
    assert d["checked"] == 2 and d["confirmed"] == 1 and d["rejected"] == 1 and "№07" in d["note"]


def test_external_resolver_from_07_is_authoritative():
    calls = []

    def ext(document, hint):
        calls.append(hint)
        return None

    r = Resolver(DocView(DOC), external=ext)
    assert r({"block_id": "b1", "quote": "Клиент"}) is None and calls


def test_money_exact():
    assert parse_money("48 500 ₸")[2] == 4_850_000
    assert parse_money("100 тиын")[2] == 100 == parse_money("1 ₸")[2]
    assert to_minor(Decimal("0.005"), "KZT") is None  # дробный тиын не округляется молча
    assert fmt_money(30_000_100) == "300 001 ₸"


def test_stamps_and_timezones():
    s = find_stamps("Покупка 31 января в 23:58 на 4 000 ₸ | Провести 1 февраля в 00:03 по Алматы")
    assert [(x.day, x.month, x.hour, x.minute, x.offset) for x in s] == [(31, 1, 23, 58, None), (1, 2, 0, 3, 5)]
    utc = find_stamps("31 января в 23:58 по UTC")[0]
    assert utc.in_offset(5).month == 2  # 23:58 UTC = 04:58 1 февраля по Алматы


def test_sentence_spans_keep_numbers_and_ids():
    t = "* **Ф-1.** Порог от 1 000 до 1 000 000 ₸ включительно. По умолчанию выключено."
    parts = [t[a:b] for a, b in sentence_spans(t, 11)]
    assert parts == ["Порог от 1 000 до 1 000 000 ₸ включительно.", "По умолчанию выключено."]


def test_hints_from_04_enrich_and_reject():
    doc = {
        "id": "h", "title": "t", "format": "md", "warnings": [],
        "blocks": [{"id": "r1", "kind": "table_header", "section": ["T", "REST API", "Параметры запроса"],
                    "text": "| Parameter | Format | Logic |", "loc": {}},
                   {"id": "r2", "kind": "table_row", "section": ["T", "REST API", "Параметры запроса"],
                    "text": "| `amount` | integer | 1 000–1 000 000 |", "loc": {}}],
    }
    hints = [
        {"field": "amount", "unit": "тенге", "range": {"min": 1000, "max": 1000000, "min_inclusive": True, "max_inclusive": True},
         "hint": {"block_id": "r2", "quote": "1 000–1 000 000"}},
        {"field": "cardId", "type": "string", "hint": {"block_id": "r2", "quote": "`cardId`"}},
    ]
    fs = extract_facts(doc, hints)
    amount = [f for f in fs.facts if f.field == "amount"][0]
    assert amount.unit == "KZT" and amount.range["min_inclusive"] is True and amount.range["min_minor"] == 100_000
    assert "№04:unit" in amount.enriched_by
    assert any("без подтверждённой опоры не использованы: 1" in w for w in fs.warnings)
    out = reconcile_facts(doc, hints)
    assert out["evidence_audit"]["rejected"] == 1


def test_constraints_and_outcomes():
    class FS:  # минимальный FactSet для range:
        def by_id(self):
            from bcc_review.analysis.facts import Fact
            return {"FX-1": Fact(id="FX-1", unit="KZT", range={"min": "1000", "max": "1000000", "min_inclusive": True,
                                                              "max_inclusive": True, "min_minor": 100000, "max_minor": 100000000})}

    fs = FS()
    assign = {"amount": "999", "лимит": "50 000 ₸", "снято": "55 000 ₸", "статус": "отменён"}
    assert eval_constraint({"var": "amount", "op": "outside", "value": "range:FX-1"}, assign, fs) is True
    assert eval_constraint({"var": "amount", "op": "inside", "value": "range:FX-1"}, assign, fs) is False
    assert eval_constraint({"var": "снято", "op": "gt", "value": "$лимит"}, assign, fs) is True
    assert eval_constraint({"var": "статус", "op": "eq", "value": "подтверждён"}, assign, fs) is False
    assert eval_constraint({"var": "нет такой", "op": "eq", "value": "1"}, assign, fs) is None
    assert outcomes_incompatible({"outcome_a": "push не отправляется", "outcome_b": "push отправляется"})[0]
    assert not outcomes_incompatible({"outcome_a": "push «Платёж выполнен»", "outcome_b": "push «Платёж отменён»"})[0]
    assert not outcomes_incompatible({"outcome_a": "1 ₸", "outcome_b": "100 тиын", "outcome_a_value": "1 ₸",
                                      "outcome_b_value": "100 тиын"})[0]


def test_sentence_spans_ignore_pdf_soft_wraps():
    t = "В расходы\nвходят проведённые покупки. Возврат уменьшает расходы месяца исходной\nпокупки."
    assert [t[a:b] for a, b in sentence_spans(t)] == ["В расходы\nвходят проведённые покупки.",
                                                      "Возврат уменьшает расходы месяца исходной\nпокупки."]
    t2 = "Первое правило.\nВторое правило\nпродолжается.\n* пункт списка"
    assert [t2[a:b] for a, b in sentence_spans(t2)] == ["Первое правило.", "Второе правило\nпродолжается.", "пункт списка"]
