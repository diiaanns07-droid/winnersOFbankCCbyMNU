"""Доказательство 3: тест модели через подставной транспорт."""
from importlib import resources

import pytest

from bcc_review.analysis.individual import STAGE, review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import requirement
from tests.p05.helpers import REQ_CODES, FakeAsk, blank, cands_of, checks_of, doc_from_lines, issue, passes, wcodes


def _doc(keep_markup: bool = False):
    doc = doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **Ф-1.** Клиент задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.",
        "- **Ф-2.** Месяц определяется по дате покупки.",
        "- **Ф-3.** Push отправляется один раз в месяц.",
        "- **Ф-4.** Возврат уменьшает расходы месяца исходной покупки.",
        keep_markup=keep_markup,
    )
    reqs = [requirement(doc, f"R{i}", f"Ф-{i}.", f"Ф-{i}") for i in range(1, 5)]
    return doc, reqs


GOOD_REASONS = {
    "unambiguous": "Порог задан целым числом в тенге с обеими включёнными границами 1 000 и 1 000 000.",
    "verifiable": "Проверяется граничными значениями 999, 1 000, 1 000 000 и 1 000 001 с ожидаемым отказом или приёмом.",
}


def _answer(payload):
    results = [passes("R1", GOOD_REASONS)]
    results.append({"req_id": "R2", "checks": [issue(
        "unambiguous", "Часовой пояс месяца не указан.", "Месяц определяется по дате покупки",
        condition="Покупка 31.01 в 23:30 UTC — это уже 1 февраля по UTC+5.",
        outcomes=["январь", "февраль"],
        impact="Покупка попадёт в разные месяцы в зависимости от пояса сервера.",
        fix="«Месяц определяется по дате покупки в часовом поясе <уточнить у владельца: пояс>».",
        question="В каком часовом поясе считается календарный месяц?",
        scenario="Покупка 31.01 23:30 UTC: январь или февраль?", root_cause="month_timezone_undefined")]})
    results.append({"req_id": "R3", "checks": [issue(
        "unambiguous", "Неясно, календарный ли месяц.", "не чаще одного раза в скользящие 30 дней")]})  # выдуманная цитата
    # R4 модель пропустила
    return {"results": results}


def test_every_requirement_gets_checks_and_correct_one_has_no_invented_defect():
    doc, reqs = _doc()
    ask = FakeAsk(_answer)
    res = review_individual(doc, reqs, ask=ask)

    # все требования × все критерии
    for r in reqs:
        assert set(checks_of(res, r["id"])) == set(REQ_CODES)
    assert len(res["checks"]) == len(reqs) * len(REQ_CODES)

    # корректное требование: содержательный pass без дефектов
    good = checks_of(res, "R1")
    assert all(c["status"] == "pass" for c in good.values())
    assert "999" in good["verifiable"]["reason"] and "включённ" in good["unambiguous"]["reason"]
    assert cands_of(res, "R1") == []

    # обоснованный дефект: буквальная цитата из блока, поля контракта
    (cand,) = cands_of(res, "R2")
    block = next(b for b in doc["blocks"] if b["id"] == cand["hints"][0]["block_id"])
    assert cand["hints"][0]["quote"] in block["text"]
    assert cand["severity"] == "major" and cand["question"] and cand["kind"] == "ambiguity"
    assert cand["cause"]["outcomes"] == ["январь", "февраль"] and cand["source"] == "llm" and cand["stage"] == "individual"
    assert checks_of(res, "R2")["unambiguous"]["candidate_refs"] == [cand["ref"]]

    # выдуманная цитата не становится замечанием
    assert checks_of(res, "R3")["unambiguous"]["status"] == "unknown"
    assert cands_of(res, "R3") == []
    assert any(w["code"] == "individual.quote_not_found" and w["message"].startswith("R3/unambiguous") for w in res["warnings"])

    # пропущенный ответ → unknown, а не «замечаний нет»
    missed = checks_of(res, "R4")
    assert {c["status"] for c in missed.values()} == {"unknown"}
    assert all("не вернула" in c["reason"] for c in missed.values())
    assert "individual.missing_answer" in wcodes(res)

    # транспорт: один вызов, этап, payload {task, input, context}, схема с кодами из TOML
    assert len(ask.calls) == 1 and res["meta"]["calls"] == 1
    stage, payload, schema = ask.calls[0]
    assert stage == STAGE == "individual"
    assert set(payload) == {"task", "input", "context"}
    item = schema["properties"]["results"]["items"]["properties"]["checks"]["items"]
    assert item["properties"]["criterion"]["enum"] == REQ_CODES
    assert payload["input"]["req_ids"] == ["R1", "R2", "R3", "R4"]
    assert payload["context"]["mode"] == "auto" and set(reqs[0]["block_ids"]) <= set(payload["context"]["block_ids"])
    assert payload["input"]["requirements"][0]["text"].startswith("Ф-1.")


def test_transport_failure_degrades_to_unknown_without_crash():
    from bcc_review.contracts import BudgetExhausted

    doc, reqs = _doc()
    res = review_individual(doc, reqs, ask=FakeAsk(raises=BudgetExhausted("individual", "max_calls")))
    assert len(res["checks"]) == len(reqs) * len(REQ_CODES)
    assert {c["status"] for c in res["checks"]} <= {"unknown", "na"}
    assert any(w["code"] == "individual.ask_failed" and "BudgetExhausted" in w["message"] for w in res["warnings"])


def test_generic_pass_is_not_accepted():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R2", "checks": [blank("correct", "pass", "Соответствует.")]}]})
    res = review_individual(doc, reqs[1:2], ask=ask)
    assert checks_of(res, "R2")["correct"]["status"] == "unknown"


def test_objective_rule_finding_survives_model_pass_and_heuristic_one_is_overridden():
    doc = doc_from_lines(
        "# ТЗ",
        "## Общие параметры",
        "| **Request URL** | Dev: `/alerts/x` . Prod: — |",
        "## Функциональные требования",
        "- **Ф-1.** Клиент видит быстро обновляемый баланс: обновление по запросу клиента.",
    )
    reqs = [requirement(doc, "R1", "Request URL"), requirement(doc, "R2", "Ф-1", "Ф-1")]
    ask = FakeAsk({"results": [
        passes("R1", {"complete": "Все поля строки заполнены, адрес Dev указан явно и проверяем."}),
        passes("R2", {"verifiable": "«Быстро» здесь описывает вид баланса, обновление идёт по запросу — это наблюдаемо."}),
    ]})
    res = review_individual(doc, reqs, ask=ask)
    assert checks_of(res, "R1")["complete"]["status"] == "issue"  # прочерк есть буквально
    r2 = checks_of(res, "R2")["verifiable"]
    assert r2["status"] == "pass" and "Сигнал правил отклонён" in r2["reason"]


def test_critical_needs_scenario_and_blocks_none_is_minor():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R2", "checks": [
        issue("unambiguous", "Пояс не указан.", "по дате покупки", severity="critical", root_cause="tz"),
        issue("conforming", "Нет слова «должен».", "Месяц определяется", severity="major", blocks="none",
              kind="format", root_cause="modal"),
    ]}]})
    res = review_individual(doc, reqs[1:2], ask=ask)
    by_crit = {c["criterion"]: c for c in res["candidates"]}
    assert by_crit["unambiguous"]["severity"] == "major"
    assert any("critical → major" in n and "scenario" in n for n in by_crit["unambiguous"]["calibration"])
    assert by_crit["conforming"]["severity"] == "minor" and by_crit["conforming"]["blocks"] == []


def test_invented_numbers_in_fix_become_owner_question():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R3", "checks": [issue(
        "unambiguous", "«Один раз в месяц» без точки отсчёта.", "один раз в месяц",
        fix="Не более 1 push за календарный месяц UTC+5 и повтор через 30 минут.", blocks="verify",
        scenario="Возврат после push и новое достижение.")]}]})
    res = review_individual(doc, reqs[2:3], ask=ask)
    (cand,) = res["candidates"]
    assert "<уточнить у владельца: 30 минут?>" in cand["recommendation"]
    assert "<уточнить у владельца: 5?>" in cand["recommendation"]
    assert "1 000" not in cand["recommendation"]
    assert "30 минут" in cand["question"]


def test_markdown_in_block_does_not_break_quote_match():
    doc, reqs = _doc(keep_markup=True)
    ask = FakeAsk({"results": [{"req_id": "R4", "checks": [issue(
        "complete", "Нет правила для частичного возврата.", "Ф-4. Возврат уменьшает расходы", kind="incomplete",
        question="Как учитывать частичный возврат?", blocks="implement", scenario="Покупка 10 000, возврат 3 000")]}]})
    res = review_individual(doc, reqs[3:4], ask=ask)
    (cand,) = res["candidates"]
    assert cand["hints"][0]["quote"] == "Ф-4.** Возврат уменьшает расходы"


def test_same_root_cause_from_model_gives_one_candidate():
    doc, reqs = _doc()
    common = dict(severity="major", blocks="both", scenario="Покупка 31.01 23:59", root_cause="month_timezone_undefined")
    ask = FakeAsk({"results": [
        {"req_id": "R2", "checks": [issue("unambiguous", "Пояс месяца не задан.", "Месяц определяется по дате покупки", **common)]},
        {"req_id": "R4", "checks": [issue("unambiguous", "Пояс месяца не задан.", "расходы месяца исходной покупки", **common)]},
    ]})
    res = review_individual(doc, [reqs[1], reqs[3]], ask=ask)
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["req_ids"] == ["R2", "R4"] and len(res["candidates"][0]["hints"]) == 2


def test_batches_follow_toml(tmp_path):
    text = resources.files("bcc_review").joinpath("criteria.toml").read_text("utf-8")
    p = tmp_path / "criteria.toml"
    p.write_text(text.replace("batch_size = 15", "batch_size = 3"), "utf-8")
    crit = load_criteria(p)
    doc, reqs = _doc()
    ask = FakeAsk(lambda payload: {"results": [passes(r) for r in payload["input"]["req_ids"]]})
    res = review_individual(doc, reqs, ask=ask, criteria=crit)
    assert [c[1]["input"]["req_ids"] for c in ask.calls] == [["R1", "R2", "R3"], ["R4"]]
    assert res["meta"]["calls"] == 2


@pytest.mark.parametrize("bad", [{"results": [{"req_id": "R9", "checks": []}]}, "не json"])
def test_unexpected_answers_are_reported(bad):
    doc, reqs = _doc()
    res = review_individual(doc, reqs[:1], ask=FakeAsk(bad))
    assert res["warnings"]
    assert {c["status"] for c in res["checks"]} <= {"unknown", "pass", "na"}
