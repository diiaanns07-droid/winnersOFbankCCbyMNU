"""Доказательство 2 (негативный контроль): одно условие для подтверждённого события, другое — для
отменённого. Совпадающие слова («Для … платежа месяц определяется по дате …», «клиент получает push»)
не порождают противоречия ни в правилах, ни после «наивного» ответа модели.
"""

from conftest import ScriptedAsk, requirements_from

from bcc_review.analysis.cross import review_set


def test_offline_same_words_different_conditions_no_conflict(load):
    doc = load("payment_states.md")
    res = review_set(doc, requirements_from(doc))
    assert [c for c in res["candidates"] if c["kind"] == "conflict"] == []
    expl = " ".join(c["explanation"] for c in res["comparisons"])
    # два правила привязки распознаны и признаны совместимыми из-за разных условий
    assert any(c["aspect"] == "period_anchor" and c["verdict"] == "compatible" for c in res["comparisons"]), expl
    # строка приёмки про отменённый платёж проверена по правилу П-2 и согласуется с ним
    assert any(c["aspect"] == "period" and c["verdict"] == "compatible" and "феврал" in c["explanation"]
               for c in res["comparisons"]), expl


def _naive_conflict(with_constraints: bool):
    def build(pa, pb):
        res = {
            "verdict": "conflict",
            "a": {"condition": "платёж подтверждён", "expected": "push «Платёж выполнен»",
                  "quote": "Для подтверждённого платежа клиент получает push «Платёж выполнен»."},
            "b": {"condition": "платёж отменён", "expected": "push «Платёж отменён»",
                  "quote": "Для отменённого платежа клиент получает push «Платёж отменён»."},
            "witness": {
                "input": [{"var": "статус платежа", "value": "подтверждён", "source": "illustrative",
                           "why": "модель взяла одно событие"}],
                "outcome_a": "push «Платёж выполнен»", "outcome_b": "push «Платёж отменён»",
                "evidence_a": {"block_id": pa["block_id"], "quote": "клиент получает push «Платёж выполнен»"},
                "evidence_b": {"block_id": pb["block_id"], "quote": "клиент получает push «Платёж отменён»"},
            },
            "title": "Разные push для одного платежа",
        }
        if with_constraints:
            res["a"]["constraints"] = [{"var": "статус платежа", "op": "eq", "value": "подтверждён"}]
            res["b"]["constraints"] = [{"var": "статус платежа", "op": "eq", "value": "отменён"}]
        return res
    return build


def test_naive_model_conflict_rejected_by_disjoint_preconditions(load):
    doc = load("payment_states.md")
    ask = ScriptedAsk(pair_rules=[("Платёж выполнен", "Платёж отменён", _naive_conflict(True))])
    res = review_set(doc, requirements_from(doc), ask)
    assert ask.matched, "пара П-3/П-4 должна попасть к модели"
    assert [c for c in res["candidates"] if c["kind"] == "conflict"] == []
    rej = [c for c in res["comparisons"] if c["aspect"] == "semantic" and c["verdict"] == "compatible"]
    assert rej and "условия не пересекаются" in rej[0]["explanation"] and "отменён" in rej[0]["explanation"]


def test_naive_model_conflict_without_constraints_is_not_confirmed(load):
    doc = load("payment_states.md")
    ask = ScriptedAsk(pair_rules=[("Платёж выполнен", "Платёж отменён", _naive_conflict(False))])
    res = review_set(doc, requirements_from(doc), ask)
    assert [c for c in res["candidates"] if c["kind"] == "conflict"] == []
    # без общего условия кандидат может уйти №08 только вопросом
    assert all(c.get("subkind") == "question" for c in res["candidates"])
