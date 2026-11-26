"""Доказательство 3: тест модели через подставной транспорт."""
import pytest

from bcc_review.analysis.individual import STAGE, review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import requirement
from tests.p05.helpers import REQ_CODES, FakeAsk, cands_of, checks_of, doc_from_lines, passes


def _doc():
    doc = doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **Ф-1.** Клиент задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.",
        "- **Ф-2.** Месяц определяется по дате покупки.",
        "- **Ф-3.** Push отправляется один раз в месяц.",
        "- **Ф-4.** Возврат уменьшает расходы месяца исходной покупки.",
    )
    reqs = [requirement(doc, f"R{i}", f"Ф-{i}.", f"Ф-{i}") for i in range(1, 5)]
    return doc, reqs


GOOD_REASONS = {
    "И3": "Порог задан целым числом в тенге с обеими включёнными границами 1 000 и 1 000 000.",
    "И7": "Проверяется граничными значениями 999, 1 000, 1 000 000 и 1 000 001 с ожидаемым отказом или приёмом.",
}


def _answer(payload):
    results = [passes("R1", GOOD_REASONS)]
    results.append({"req_id": "R2", "checks": [
        {"criterion": "И3", "status": "issue", "reason": "Часовой пояс месяца не указан.",
         "quote": "Месяц определяется по дате покупки",
         "condition": "Покупка 31.01 в 23:30 UTC — это уже 1 февраля по UTC+5.",
         "impact": "Покупка попадёт в разные месяцы в зависимости от пояса сервера.",
         "fix": "«Месяц определяется по дате покупки в часовом поясе <уточнить у владельца: пояс>».",
         "question": "В каком часовом поясе считается календарный месяц?",
         "severity": "major", "blocks": "both", "scenario": "Покупка 31.01 23:30 UTC: январь или февраль?",
         "root_cause": "month_timezone_undefined"},
    ]})
    results.append({"req_id": "R3", "checks": [
        {"criterion": "И3", "status": "issue", "reason": "Неясно, календарный ли месяц.",
         "quote": "не чаще одного раза в скользящие 30 дней",  # выдуманная цитата
         "condition": "—", "impact": "—", "severity": "major", "blocks": "verify", "scenario": "—"},
    ]})
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
    assert "999" in good["И7"]["reason"] and "включённ" in good["И3"]["reason"]
    assert cands_of(res, "R1") == []

    # обоснованный дефект: буквальная цитата из блока
    (cand,) = cands_of(res, "R2")
    block = next(b for b in doc["blocks"] if b["id"] == cand["hints"][0]["block_id"])
    assert cand["hints"][0]["quote"] in block["text"]
    assert cand["severity"] == "major" and cand["question"]
    assert checks_of(res, "R2")["И3"]["refs"] == [cand["ref"]]

    # выдуманная цитата не становится замечанием
    assert checks_of(res, "R3")["И3"]["status"] == "unknown"
    assert cands_of(res, "R3") == []
    assert any(w.startswith("individual.quote_not_found: R3/И3") for w in res["warnings"])

    # пропущенный ответ → unknown, а не «замечаний нет»
    missed = checks_of(res, "R4")
    assert {c["status"] for c in missed.values()} == {"unknown"}
    assert all("не вернула" in c["reason"] for c in missed.values())
    assert any(w.startswith("individual.missing_answer: R4") for w in res["warnings"])

    # транспорт: один вызов, этап, схема с кодами из TOML
    assert len(ask.calls) == 1 and res["meta"]["calls"] == 1
    stage, payload, schema = ask.calls[0]
    assert stage == STAGE == "individual"
    enum = schema["properties"]["results"]["items"]["properties"]["checks"]["items"]["properties"]["criterion"]["enum"]
    assert enum == REQ_CODES
    assert payload["req_ids"] == ["R1", "R2", "R3", "R4"]
    assert "Ф-1." in payload["user"] and "[b3]" in payload["user"]


def test_transport_failure_degrades_to_unknown_without_crash():
    doc, reqs = _doc()
    res = review_individual(doc, reqs, ask=FakeAsk(raises=TimeoutError("503 overloaded")))
    assert len(res["checks"]) == len(reqs) * len(REQ_CODES)
    assert {c["status"] for c in res["checks"]} <= {"unknown", "na"}
    assert any("individual.ask_failed" in w and "503" in w for w in res["warnings"])


def test_generic_pass_is_not_accepted():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R2", "checks": [{"criterion": "И8", "status": "pass", "reason": "Соответствует."}]}]})
    res = review_individual(doc, reqs[1:2], ask=ask)
    assert checks_of(res, "R2")["И8"]["status"] == "unknown"


def test_objective_rule_finding_survives_model_pass_and_heuristic_one_is_overridden():
    doc = doc_from_lines(
        "# ТЗ",
        "## Общие параметры",
        "| **Request URL** | Dev: `/alerts/x` . Prod: — |",
        "## Функциональные требования",
        "- **Ф-1.** Клиент видит быстро обновляемый баланс: обновление каждые 5 секунд.",
    )
    reqs = [requirement(doc, "R1", "Request URL"), requirement(doc, "R2", "Ф-1", "Ф-1")]
    ask = FakeAsk({"results": [
        passes("R1", {"И4": "Все поля строки заполнены, адрес Dev указан явно и проверяем."}),
        passes("R2", {"И7": "«Быстро» раскрыто тут же: обновление каждые 5 секунд, это измеримо."}),
    ]})
    res = review_individual(doc, reqs, ask=ask)
    assert checks_of(res, "R1")["И4"]["status"] == "issue"  # прочерк есть буквально
    assert checks_of(res, "R2")["И7"]["status"] == "pass"


def test_critical_needs_scenario_and_blocks_none_is_minor():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R2", "checks": [
        {"criterion": "И3", "status": "issue", "reason": "Пояс не указан.", "quote": "по дате покупки",
         "impact": "Разные месяцы.", "severity": "critical", "root_cause": "tz"},
        {"criterion": "И9", "status": "issue", "reason": "Нет слова «должен».", "quote": "Месяц определяется",
         "impact": "Стиль.", "severity": "major", "blocks": "none", "root_cause": "modal"},
    ]}]})
    res = review_individual(doc, reqs[1:2], ask=ask)
    by_crit = {c["criterion"]: c for c in res["candidates"]}
    assert by_crit["И3"]["severity"] == "major"
    assert any("critical → major" in n for n in by_crit["И3"]["calibration"])
    assert by_crit["И9"]["severity"] == "minor"


def test_invented_numbers_in_fix_become_owner_question():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R3", "checks": [
        {"criterion": "И3", "status": "issue", "reason": "«Один раз в месяц» без точки отсчёта.",
         "quote": "один раз в месяц", "condition": "Повторное достижение после возврата.",
         "impact": "Два push или ни одного.", "fix": "Не более 1 push за календарный месяц UTC+5 и повтор через 30 минут.",
         "severity": "major", "blocks": "verify", "scenario": "Возврат после push и новое достижение."},
    ]}]})
    res = review_individual(doc, reqs[2:3], ask=ask)
    (cand,) = res["candidates"]
    assert "<уточнить у владельца: 30 минут?>" in cand["fix"]
    assert "<уточнить у владельца: 5?>" in cand["fix"]
    assert "1 000" not in cand["fix"]
    assert "30 минут" in cand["question"]


def test_markdown_in_block_does_not_break_quote_match():
    doc, reqs = _doc()
    ask = FakeAsk({"results": [{"req_id": "R4", "checks": [
        {"criterion": "И4", "status": "issue", "reason": "Нет правила для частичного возврата.",
         "quote": "Ф-4. Возврат уменьшает расходы", "impact": "Неясно, сколько вычесть.",
         "question": "Как учитывать частичный возврат?", "severity": "major", "blocks": "implement",
         "scenario": "Покупка 10 000, возврат 3 000"},
    ]}]})
    res = review_individual(doc, reqs[3:4], ask=ask)
    (cand,) = res["candidates"]
    assert cand["hints"][0]["quote"] == "Ф-4.** Возврат уменьшает расходы"


def test_same_root_cause_from_model_gives_one_candidate():
    doc, reqs = _doc()
    common = {"criterion": "И3", "status": "issue", "reason": "Пояс месяца не задан.", "impact": "Разные месяцы.",
              "severity": "major", "blocks": "both", "scenario": "Покупка 31.01 23:59", "root_cause": "month_timezone_undefined"}
    ask = FakeAsk({"results": [
        {"req_id": "R2", "checks": [dict(common, quote="Месяц определяется по дате покупки")]},
        {"req_id": "R4", "checks": [dict(common, quote="расходы месяца исходной покупки")]},
    ]})
    res = review_individual(doc, [reqs[1], reqs[3]], ask=ask)
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["req_ids"] == ["R2", "R4"] and len(res["candidates"][0]["hints"]) == 2


def test_batches_follow_toml(tmp_path):
    src = load_criteria().source_path
    from importlib import resources

    text = resources.files("bcc_review").joinpath("criteria.toml").read_text("utf-8")
    p = tmp_path / "criteria.toml"
    p.write_text(text.replace("batch_size = 15", "batch_size = 3"), "utf-8")
    crit = load_criteria(p)
    doc, reqs = _doc()
    ask = FakeAsk(lambda payload: {"results": [passes(r) for r in payload["req_ids"]]})
    res = review_individual(doc, reqs, ask=ask, criteria=crit)
    assert [c[1]["req_ids"] for c in ask.calls] == [["R1", "R2", "R3"], ["R4"]]
    assert res["meta"]["calls"] == 2 and src


@pytest.mark.parametrize("bad", [{"results": [{"req_id": "R9", "checks": []}]}, "не json"])
def test_unexpected_answers_are_reported(bad):
    doc, reqs = _doc()
    res = review_individual(doc, reqs[:1], ask=FakeAsk(bad))
    assert res["warnings"]
    assert {c["status"] for c in res["checks"]} <= {"unknown", "pass", "na"}
