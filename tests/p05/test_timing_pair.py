"""Доказательство 1: «операция выполняется быстро» и обязательство с таймером, точкой отсчёта и границей."""
from bcc_review.analysis.individual import review_individual
from tests.p05.docfix import requirement
from tests.p05.helpers import cands_of, checks_of, doc_from_lines


def _pair_doc():
    return doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **ФТ-1.** Операция выполняется быстро.",
        "## Нефункциональные требования",
        "- **НФТ-1.** Сервис передаёт push на отправку не позднее 60 секунд после получения события процессинга.",
    )


def test_vague_speed_is_issue_and_timer_is_pass():
    doc = _pair_doc()
    reqs = [requirement(doc, "R1", "ФТ-1", "ФТ-1"), requirement(doc, "R2", "НФТ-1", "НФТ-1")]
    res = review_individual(doc, reqs)

    vague = checks_of(res, "R1")["verifiable"]
    timed = checks_of(res, "R2")["verifiable"]
    assert vague["status"] == "issue"
    assert timed["status"] == "pass"
    assert vague["reason"] != timed["reason"]

    # «быстро»: буквальная цитата, условие, последствие, правка без выдуманного числа и вопрос
    (cand,) = cands_of(res, "R1")
    assert cand["criterion"] == "verifiable" and cand["kind"] == "unverifiable" and cand["severity"] == "major"
    assert cand["hints"] == [{"block_id": reqs[0]["block_ids"][0], "quote": "быстро", "context": "ФТ-1. Операция выполняется быстро."}]
    assert "быстро" in cand["cause"]["condition"] and cand["impact"] and cand["blocked_decision"]
    assert cand["blocks"] == ["development", "testing"]
    assert "<уточнить у владельца" in cand["recommendation"] and not any(ch.isdigit() for ch in cand["recommendation"])
    assert "срок" in cand["question"]

    # таймер: граница, длительность и точка отсчёта названы, дефекта нет
    assert "не позднее 60 секунд" in timed["reason"]
    assert "после получения события процессинга" in timed["reason"]
    assert cands_of(res, "R2") == []


def test_timer_without_start_point_is_minor_issue():
    doc = doc_from_lines("# ТЗ", "## Нефункциональные требования", "- **НФТ-2.** Ответ возвращается не позднее 2 секунд.")
    res = review_individual(doc, [requirement(doc, "R1", "НФТ-2", "НФТ-2")])
    chk = checks_of(res, "R1")["verifiable"]
    assert chk["status"] == "issue" and chk["severity"] == "minor"
    (cand,) = res["candidates"]
    assert cand["hints"][0]["quote"] == "не позднее 2 секунд"
    assert "точк" in cand["title"]


def test_data_window_is_not_a_deadline():
    doc = doc_from_lines("# ТЗ", "## Функциональные требования", "- **Ф-1.** Клиент видит выписку за 30 дней.")
    res = review_individual(doc, [requirement(doc, "R1", "Ф-1", "Ф-1")])
    assert res["candidates"] == []


def test_measurable_neighbor_line_resolves_vague_word():
    doc = doc_from_lines(
        "# ТЗ",
        "## Нефункциональные требования",
        "- **НФТ-3.** Поиск по истории операций работает быстро.",
        "Время ответа — не более 2 секунд от отправки запроса для 95% запросов.",
    )
    res = review_individual(doc, [requirement(doc, "R1", "НФТ-3", "НФТ-3")])
    chk = checks_of(res, "R1")["verifiable"]
    assert chk["status"] == "pass"
    assert "не более 2 секунд от отправки запроса" in chk["reason"]
    assert res["candidates"] == []


def test_neighbor_owned_by_other_requirement_does_not_resolve():
    doc = doc_from_lines(
        "# ТЗ",
        "## Нефункциональные требования",
        "- **НФТ-4.** Экран выписки открывается быстро.",
        "- **НФТ-5.** Push уходит не более чем за 10 секунд после проведения покупки.",
    )
    reqs = [requirement(doc, "R1", "НФТ-4", "НФТ-4"), requirement(doc, "R2", "НФТ-5", "НФТ-5")]
    res = review_individual(doc, reqs)
    assert checks_of(res, "R1")["verifiable"]["status"] == "issue"
    assert checks_of(res, "R2")["verifiable"]["status"] == "pass"
