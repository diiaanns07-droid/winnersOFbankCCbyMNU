"""Доказательство 3: покрытие на уровне обязательств.

Л-1 содержит два обязательства. Приёмка №1 проверяет первое («лимит по умолчанию не задан»),
приёмка №2 спорит со вторым (снятие сверх лимита ожидается выполненным). Показатель не становится
полным покрытием; без модели лексическая связь не даёт covered; при пропущенной странице отсутствие
связи остаётся unknown.
"""

import copy

from p06_helpers import ScriptedAsk, evidence_ok, requirements_from

from bcc_review.analysis.cross import review_set


def _coverage_answer(payload):
    ob = {o["text"][:30]: o["obligation_id"] for o in payload["obligations"]}
    first = next(v for k, v in ob.items() if "По умолчанию" in k)
    second = next(v for k, v in ob.items() if "Снятие сверх" in k)
    acc = {a["text"][:40]: a for a in payload["acceptance"]}
    a1 = next(a for k, a in acc.items() if "Новая карта" in k)
    a2 = next(a for k, a in acc.items() if "Суточный лимит 50 000" in k)
    return {
        "obligations": [{"obligation_id": first, "branches": ["лимит по умолчанию не задан"]},
                        {"obligation_id": second, "branches": ["снятие сверх лимита отклоняется", "сообщение «Лимит превышен»"]}],
        "links": [
            {"obligation_id": first, "acceptance_id": a1["acceptance_id"], "relation": "checks",
             "branches_checked": ["лимит по умолчанию не задан"],
             "explanation": "Проверяет начальное состояние лимита."},
            {"obligation_id": second, "acceptance_id": a2["acceptance_id"], "relation": "contradicts",
             "explanation": "45 000 + 10 000 = 55 000 ₸ больше лимита 50 000 ₸, но ожидается выполнение.",
             "a": {"constraints": [{"var": "снято за сутки с учётом операции", "op": "gt", "value": "$суточный лимит"}]},
             "b": {"constraints": [{"var": "суточный лимит", "op": "eq", "value": "50 000 ₸"},
                                   {"var": "снято ранее", "op": "eq", "value": "45 000 ₸"}]},
             "witness": {
                 "input": [
                     {"var": "суточный лимит", "value": "50 000 ₸", "source": "document",
                      "block_id": a2["block_id"], "quote": "Суточный лимит 50 000 ₸"},
                     {"var": "снято ранее", "value": "45 000 ₸", "source": "document",
                      "block_id": a2["block_id"], "quote": "за сутки снято 45 000 ₸"},
                     {"var": "снято за сутки с учётом операции", "value": "55 000 ₸", "source": "illustrative",
                      "why": "45 000 ₸ + 10 000 ₸ из действия строки"},
                 ],
                 "outcome_a": "снятие отклоняется с сообщением «Лимит превышен»",
                 "outcome_b": "снятие выполнено",
                 "outcome_target": "исход снятия 10 000 ₸", "outcome_a_value": "отклонено", "outcome_b_value": "выполнено",
                 "evidence_a": {"block_id": "", "quote": "Снятие сверх заданного лимита отклоняется с сообщением «Лимит превышен»."},
                 "evidence_b": {"block_id": a2["block_id"], "quote": "Снятие выполнено"},
             }},
        ],
    }


def test_one_checked_one_contradicted_is_not_full_coverage(load):
    doc = load("cash_limit.md")
    ask = ScriptedAsk(coverage=_coverage_answer)
    res = review_set(doc, requirements_from(doc), ask)
    cov = {c["obligation_id"]: c for c in res["coverage"]}
    assert cov["Л-1#1"]["status"] == "covered"
    assert cov["Л-1#2"]["status"] == "conflict"
    assert cov["Л-1#2"]["acceptance_ids"] == ["AC-2"]
    s = res["coverage_summary"]
    assert s["denominator"] == 3 and s["covered"] == 1 and s["conflict"] == 1
    assert s["covered_ratio"] == round(1 / 3, 3) < 1
    req = next(r for r in s["by_requirement"] if r["label"] == "Л-1")
    assert req == {"req_id": "R-01", "label": "Л-1", "obligations": 2, "covered": 1, "status": "conflict"}
    # конфликт подтверждён программой: опоры, вход из документа, предусловия на входе
    conf = [c for c in res["candidates"] if c["kind"] == "conflict"]
    assert len(conf) == 1 and conf[0]["checks"]["preconditions"] == "program"
    w = conf[0]["witness"]
    assert evidence_ok(doc, w["evidence_a"]) and evidence_ok(doc, w["evidence_b"])
    assert [x["name"] for x in w["input_detail"]["document_data"]] == ["суточный лимит", "снято ранее"]
    assert [x["name"] for x in w["input_detail"]["illustrative"]] == ["снято за сутки с учётом операции"]
    # Л-2 ни одна строка не проверяет — uncovered (все страницы на месте)
    assert cov["Л-2#1"]["status"] == "uncovered"


def test_offline_lexical_link_never_becomes_covered(load):
    doc = load("cash_limit.md")
    res = review_set(doc, requirements_from(doc))
    st = [c["status"] for c in res["coverage"]]
    assert "covered" not in st and st.count("partial") >= 1
    assert res["coverage_summary"]["linked"] >= 1 and res["coverage_summary"]["covered"] == 0


def _as_pdf_with_missing_page(doc):
    """Те же блоки, но как PDF: требования на стр. 1, приёмка на стр. 2, стр. 3 не извлечена, стр. 4 есть."""
    d = copy.deepcopy(doc)
    d["format"] = "pdf"
    for b in d["blocks"]:
        page = 2 if any("Критерии" in s for s in b["section"]) else 1
        b["loc"] = {"page": page}
    d["blocks"].append({"id": "p4-1", "kind": "paragraph", "section": ["Суточный лимит снятия наличных", "Приложение"],
                        "text": "Контакты службы поддержки.", "loc": {"page": 4}})
    d["warnings"] = ["Страница 3 не извлечена: пустой текстовый слой"]
    return d


def test_missing_page_keeps_absence_unknown(load):
    doc = _as_pdf_with_missing_page(load("cash_limit.md"))
    res = review_set(doc, requirements_from(doc), ScriptedAsk(coverage=_coverage_answer))
    cov = {c["obligation_id"]: c for c in res["coverage"]}
    assert cov["Л-2#1"]["status"] == "unknown" and "3" in cov["Л-2#1"]["explanation"]
    # положительные выводы, подтверждённые опорами, сохраняются
    assert cov["Л-1#1"]["status"] == "covered" and cov["Л-1#2"]["status"] == "conflict"
    assert res["coverage_summary"]["unknown"] == 1 and res["coverage_summary"]["denominator"] == 3
    assert any("Страницы 3" in w for w in res["warnings"])
