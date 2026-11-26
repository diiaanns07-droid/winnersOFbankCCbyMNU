"""Область действия определения: число из другого места документа не делает пункт проверяемым.

Три коротких ТЗ про подтверждение перевода (tests/p05/fixtures/transfer_*.md), одна версия критериев:
1. «в установленный срок» явно ссылается на общее правило ОП-1 (таймер, точка отсчёта, порог);
2. такое число есть только в разделе про другой продукт (кредитные карты);
3. срок нигде не определён.
ПР-2 в каждом ТЗ — чистый контроль: «быстро» стоит в названии кнопки.
"""
import re

import pytest

from bcc_review.analysis.individual import build_prompt, review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import load_fixture, requirement
from tests.p05.helpers import FakeAsk, cands_of, checks_of, doc_from_lines, passes, wcodes

CASES = {"linked": "transfer_linked.md", "other_product": "transfer_other_product.md", "undefined": "transfer_undefined.md"}
CRIT = load_criteria()


def _case(name):
    doc = load_fixture(CASES[name])
    return doc, [requirement(doc, "ПР-1", "ПР-1.", "ПР-1"), requirement(doc, "ПР-2", "ПР-2.", "ПР-2")]


def _run(name, ask=None):
    doc, reqs = _case(name)
    return doc, review_individual(doc, reqs, ask=ask, criteria=CRIT)


def _numbers_outside_markers(text):
    """Числа правки вне маркеров <уточнить у владельца: …>."""
    bare = re.sub(r"<уточнить[^<>]*>", "", text or "")
    return re.findall(r"(?<![\w-])\d+", bare)


def test_linked_general_rule_keeps_the_definition():
    doc, res = _run("linked")
    chk = checks_of(res, "ПР-1")["verifiable"]
    assert chk["status"] == "pass"
    op1 = next(b for b in doc["blocks"] if b["text"].startswith("ОП-1."))
    assert "ОП-1" in chk["reason"] and f"[{op1['id']}]" in chk["reason"]
    assert "не позднее 120 секунд с момента отправки кода" in chk["reason"]
    assert "явная ссылка" in chk["reason"]
    assert cands_of(res, "ПР-1") == []


def test_number_from_other_product_does_not_make_requirement_verifiable():
    doc, res = _run("other_product")
    chk = checks_of(res, "ПР-1")["verifiable"]
    assert chk["status"] == "issue" and chk["severity"] == "major"
    kk1 = next(b for b in doc["blocks"] if b["text"].startswith("КК-1."))
    # точное основание: где искали, что нашли и почему не применили
    assert "Переводы между картами" in chk["reason"]
    assert f"[{kk1['id']}]" in chk["reason"] and "Кредитные карты" in chk["reason"]
    assert "ссылки" in chk["reason"]
    (cand,) = cands_of(res, "ПР-1")
    assert cand["hints"][0]["quote"] == "в установленный срок"
    assert "300 секунд" in cand["question"] and "КК-1" in cand["question"]
    assert _numbers_outside_markers(cand["recommendation"]) == []
    assert cand["blocked_decision"] == ("Разработка: какой тайм-аут и от какого события заложить для «Клиент подтверждает "
                                        "перевод»; приёмка: при каком времени тест ожидает успех, а при каком — отказ.")
    assert cand["blocks"] == ["development", "testing"]


def test_undefined_term_gets_exact_basis_and_owner_question():
    _, res = _run("undefined")
    chk = checks_of(res, "ПР-1")["verifiable"]
    assert chk["status"] == "issue" and chk["severity"] == "major"
    assert "не определён" in chk["reason"] and "ни в пункте" in chk["reason"]
    (cand,) = cands_of(res, "ПР-1")
    assert "Какой срок" in cand["question"]
    assert _numbers_outside_markers(cand["recommendation"]) == []


@pytest.mark.parametrize("name", list(CASES))
def test_button_name_is_a_clean_control(name):
    _, res = _run(name)
    assert cands_of(res, "ПР-2") == []
    chk = checks_of(res, "ПР-2")["verifiable"]
    assert chk["status"] != "issue"
    assert "«Подтвердить быстро»" in chk["reason"]


def test_three_documents_differ_only_by_definition_scope():
    statuses = {name: checks_of(_run(name)[1], "ПР-1")["verifiable"]["status"] for name in CASES}
    assert statuses == {"linked": "pass", "other_product": "issue", "undefined": "issue"}
    reasons = {name: checks_of(_run(name)[1], "ПР-1")["verifiable"]["reason"] for name in CASES}
    assert len(set(reasons.values())) == 3


def test_general_section_without_link_applies_by_subject():
    doc = doc_from_lines(
        "# Подтверждение перевода",
        "## Общие правила",
        "- **ОП-1.** Операция подтверждается одноразовым кодом не позднее 120 секунд с момента отправки кода.",
        "## Переводы между картами",
        "### Функциональные требования",
        "- **ПР-1.** Клиент подтверждает перевод в установленный срок.",
    )
    res = review_individual(doc, [requirement(doc, "ПР-1", "ПР-1.", "ПР-1")])
    chk = checks_of(res, "ПР-1")["verifiable"]
    assert chk["status"] == "pass" and "общего раздела" in chk["reason"]


def test_model_pass_on_out_of_scope_number_is_rejected():
    """Ошибка, ради которой сделан проход: модель видит 300 секунд у кредитных карт и ставит pass."""
    doc, reqs = _case("other_product")
    wrong = passes("ПР-1", {"verifiable": "Срок задан: не позднее 300 секунд с момента отправки кода, это проверяется таймером."})
    res = review_individual(doc, reqs, ask=FakeAsk({"results": [wrong, passes("ПР-2")]}), criteria=CRIT)
    chk = checks_of(res, "ПР-1")["verifiable"]
    assert chk["status"] == "issue"
    assert "300" in chk["reason"] and "Кредитные карты" in chk["reason"]
    assert "individual.out_of_scope_basis" in wcodes(res)


def test_model_pass_on_linked_number_is_kept():
    doc, reqs = _case("linked")
    good = passes("ПР-1", {"verifiable": "Срок задан правилом ОП-1: не позднее 120 секунд с момента отправки кода."})
    res = review_individual(doc, reqs, ask=FakeAsk({"results": [good, passes("ПР-2")]}), criteria=CRIT)
    assert checks_of(res, "ПР-1")["verifiable"]["status"] == "pass"
    assert "individual.out_of_scope_basis" not in wcodes(res)


def test_model_fix_with_out_of_scope_number_is_marked_pending():
    from tests.p05.helpers import issue

    doc, reqs = _case("other_product")
    ans = issue("verifiable", "Срок не назван.", "в установленный срок",
                fix="Клиент подтверждает перевод не позднее 300 секунд с момента отправки кода.",
                question="Какой срок?", blocks="both", scenario="Код отправлен, клиент вводит его через 200 секунд.")
    res = review_individual(doc, reqs, ask=FakeAsk({"results": [{"req_id": "ПР-1", "checks": [ans]}, passes("ПР-2")]}),
                            criteria=CRIT)
    (cand,) = cands_of(res, "ПР-1")
    assert "<уточнить у владельца: 300 секунд?>" in cand["recommendation"]
    assert _numbers_outside_markers(cand["recommendation"]) == []


def test_prompt_lists_applicable_and_foreign_definitions():
    doc, reqs = _case("other_product")
    p = build_prompt(doc, reqs, criteria=CRIT)
    r1 = p["input"]["requirements"][0]
    assert r1["definitions"]["applicable"] == []
    assert [d["section"] for d in r1["definitions"]["other_scope"]] == [["Подтверждение перевода", "Кредитные карты", "Подтверждение платежа"]]
    assert "другого раздела" in p["task"]


def test_range_inclusivity_is_not_borrowed_from_other_product():
    doc = doc_from_lines(
        "# ТЗ",
        "## Кредитные карты",
        "- **КК-1.** Лимит покупки от 100 до 900 ₸ включительно.",
        "## Переводы между картами",
        "- **ПР-1.** Сумма перевода от 100 до 900 ₸.",
    )
    res = review_individual(doc, [requirement(doc, "ПР-1", "ПР-1.", "ПР-1")])
    chk = checks_of(res, "ПР-1")["unambiguous"]
    assert chk["status"] == "issue" and "Кредитные карты" in chk["reason"]
