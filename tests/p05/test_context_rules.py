"""Доказательство 2 и ложные срабатывания: заголовок интерфейса, кнопки, примеры, цитаты клиента."""
import re

from bcc_review.analysis.individual import review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import block_of, requirement
from tests.p05.helpers import cands_of, checks_of, doc_from_lines


def test_same_word_in_ui_heading_and_obligation():
    doc = doc_from_lines(
        "# ТЗ",
        "## Экран «Быстрый перевод»",
        "### Быстрый перевод",
        "- **ПР-1.** На экране «Быстрый перевод» есть кнопка «Перевести быстро» и поле суммы.",
        "- **ПР-2.** Перевод между своими картами выполняется быстро.",
    )
    reqs = [requirement(doc, "R1", "ПР-1", "ПР-1"), requirement(doc, "R2", "ПР-2", "ПР-2")]
    res = review_individual(doc, reqs)

    assert cands_of(res, "R1") == []
    assert all(c["status"] != "issue" for c in checks_of(res, "R1").values())
    (cand,) = cands_of(res, "R2")
    assert cand["req_ids"] == ["R2"]
    assert [h["block_id"] for h in cand["hints"]] == reqs[1]["block_ids"]
    heading_ids = {b["id"] for b in doc["blocks"] if b["kind"] == "heading"}
    assert not heading_ids & {h["block_id"] for c in res["candidates"] for h in c["hints"]}


def test_heading_block_inside_requirement_is_not_an_obligation():
    doc = doc_from_lines("# ТЗ", "## Функциональные требования", "### Быстрые платежи", "Платёж по шаблону проводится быстро.")
    head, body = block_of(doc, "Быстрые платежи"), block_of(doc, "Платёж по шаблону")
    req = {"id": "R1", "source_id": None, "text": "Быстрые платежи. Платёж по шаблону проводится быстро.",
           "block_ids": [head["id"], body["id"]], "evidence": []}
    res = review_individual(doc, [req])
    (cand,) = res["candidates"]
    assert [h["block_id"] for h in cand["hints"]] == [body["id"]]


def test_button_names_examples_and_customer_quotes_are_masked():
    doc = doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **Ф-1.** Нажатие на кнопку Быстрый платёж открывает список шаблонов клиента.",
        "- **Ф-2.** Подсказка показывает пример формулировки (например, «мгновенный перевод») под полем назначения.",
        "- **Ф-3.** Клиент говорит: хочу быстро видеть остаток. Остаток отображается на главном экране после входа.",
        "- **Ф-4.** Раздел «Удобные платежи» содержит не более 20 шаблонов.",
    )
    reqs = [requirement(doc, f"R{i}", f"Ф-{i}", f"Ф-{i}") for i in range(1, 5)]
    res = review_individual(doc, reqs)
    assert res["candidates"] == [], res["candidates"]


def test_weak_word_is_unknown_with_question_not_a_defect():
    doc = doc_from_lines("# ТЗ", "## Функциональные требования", "- **Ф-1.** Курс конвертации фиксируется в момент авторизации операции.")
    res = review_individual(doc, [requirement(doc, "R1", "Ф-1", "Ф-1")])
    chk = checks_of(res, "R1")["И7"]
    assert chk["status"] == "unknown" and chk["question"]
    assert res["candidates"] == []


def test_goal_section_uses_alternative_criterion_and_minor_severity():
    doc = doc_from_lines("# ТЗ", "## Цели", "Клиент оперативно узнаёт о расходах.")
    res = review_individual(doc, [requirement(doc, "R1", "оперативно")])
    chk = checks_of(res, "R1")
    assert chk["И7"]["status"] == "na"  # цель валидируют, а не верифицируют
    assert chk["И3"]["status"] == "issue" and chk["И3"]["severity"] == "minor"


def test_open_list_loophole_and_dedup_across_requirements():
    doc = doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **Ф-1.** Неуспешными считаются ответы 400, 401 и т. д.",
        "- **Ф-2.** Отчёт формируется быстро.",
        "## Нефункциональные требования",
        "- **НФТ-1.** Выгрузка формируется быстро.",
        "- **НФТ-2.** При необходимости система повторяет отправку.",
    )
    reqs = [requirement(doc, "R1", "Ф-1", "Ф-1"), requirement(doc, "R2", "Ф-2", "Ф-2"),
            requirement(doc, "R3", "НФТ-1", "НФТ-1"), requirement(doc, "R4", "НФТ-2", "НФТ-2")]
    res = review_individual(doc, reqs)
    assert checks_of(res, "R1")["И4"]["status"] == "issue"
    assert checks_of(res, "R4")["И3"]["status"] == "issue"
    speed = [c for c in res["candidates"] if c["hints"][0]["quote"] == "быстро"]
    assert len(speed) == 1 and speed[0]["req_ids"] == ["R2", "R3"]
    assert len(speed[0]["hints"]) == 2
    assert checks_of(res, "R2")["И7"]["refs"] == checks_of(res, "R3")["И7"]["refs"] == [speed[0]["ref"]]


def test_placeholders_respect_table_semantics():
    doc = doc_from_lines(
        "# API",
        "## Часть B. REST API",
        "### Ответ",
        "| Parameter | Format | Logic | Description | DB field |",
        "| :--- | :--- | :--- | :--- | :--- |",
        "| `result` | string | OK / ERROR | Исход сохранения | — |",
        "### Общие параметры",
        "| Поле | Значение |",
        "| :--- | :--- |",
        "| **Swagger** | — |",
        "| **Owner** | TBD |",
    )
    reqs = [requirement(doc, "R1", "`result`"), requirement(doc, "R2", "Swagger"), requirement(doc, "R3", "Owner")]
    res = review_individual(doc, reqs)
    assert cands_of(res, "R1") == []
    (sw,) = cands_of(res, "R2")
    assert sw["severity"] == "minor" and sw["hints"][0]["quote"] == "**Swagger** | —"
    (tbd,) = cands_of(res, "R3")
    assert tbd["hints"][0]["quote"].endswith("TBD")


def test_stub_and_template_rows():
    doc = doc_from_lines(
        "# ТЗ",
        "## Требования к тестированию",
        "заполняются тестировщиками",
        "## Ревью требований",
        "| Проверка | Создано | Проверено | Примечания |",
        "| :--- | :--- | :--- | :--- |",
        "| Требование может быть протестировано | Да / Нет | Да / Нет | |",
    )
    reqs = [requirement(doc, "R1", "заполняются"), requirement(doc, "R2", "может быть протестировано")]
    res = review_individual(doc, reqs)
    stub = checks_of(res, "R1")
    assert stub["И4"]["status"] == "issue" and stub["И4"]["severity"] == "minor"
    assert {c["status"] for k, c in stub.items() if k != "И4"} == {"na"}
    assert {c["status"] for c in checks_of(res, "R2").values()} == {"na"}
    assert cands_of(res, "R2") == []
    assert any(w.startswith("individual.template_rows") for w in res["warnings"])


def test_design_decision_depends_on_document_level():
    doc = doc_from_lines(
        "# ТЗ",
        "## Часть A",
        "### Требования к интеграции",
        "- **И-1.** События процессинга читаются из Kafka по стандарту банка.",
        "- **И-2.** Настройки хранятся в таблице PostgreSQL alerts.",
        "## Часть B. REST API",
        "### Логика работы метода",
        "1. Метод принимает JSON и отвечает кодом 200.",
    )
    reqs = [requirement(doc, "R1", "И-1", "И-1"), requirement(doc, "R2", "И-2", "И-2"), requirement(doc, "R3", "Метод принимает")]
    res = review_individual(doc, reqs)
    assert checks_of(res, "R1")["И2"]["status"] == "pass"
    assert "ограничение" in checks_of(res, "R1")["И2"]["reason"]
    assert checks_of(res, "R2")["И2"]["status"] == "unknown" and checks_of(res, "R2")["И2"]["question"]
    assert checks_of(res, "R3")["И2"]["status"] == "pass"
    assert "интерфейса" in checks_of(res, "R3")["И2"]["reason"]
    assert res["candidates"] == []


def test_range_inclusivity():
    doc = doc_from_lines(
        "# ТЗ",
        "## Функциональные требования",
        "- **Ф-1.** Клиент задаёт порог от 1 000 до 50 000 ₸.",
        "- **Ф-2.** Клиент задаёт лимит от 100 до 900 ₸ включительно.",
        "## Часть B. REST API",
        "### Параметры запроса",
        "| `amount` | integer | 32 bit | Да | 100–900 | Лимит |",
    )
    reqs = [requirement(doc, "R1", "Ф-1", "Ф-1"), requirement(doc, "R2", "Ф-2", "Ф-2"), requirement(doc, "R3", "`amount`")]
    res = review_individual(doc, reqs)
    r1 = checks_of(res, "R1")
    assert r1["И3"]["status"] == "issue" and r1["И3"]["severity"] == "minor"
    (cand,) = cands_of(res, "R1")
    assert cand["hints"][0]["quote"] == "от 1 000 до 50 000" and "включительно" in cand["fix"]
    r2 = checks_of(res, "R2")["И7"]
    assert r2["status"] == "pass" and "99 / 100 / 900 / 901" in r2["reason"]
    r3 = checks_of(res, "R3")["И7"]
    assert r3["status"] == "pass" and "включительно" in r3["reason"]


def test_naive_regex_vs_context_aware_rules():
    """Самый рискованный выбор — словарь размытых слов. Сравнение на малом наборе."""
    lines = [
        ("Перевод выполняется быстро.", True),
        ("Отчёт формируется оперативно.", True),
        ("Интерфейс должен быть удобным.", True),
        ("Нажатие на кнопку «Быстрый платёж» открывает шаблоны.", False),
        ("Пример текста (например, «мгновенный перевод») показан под полем.", False),
        ("Клиент говорит: хочу быстро видеть остаток.", False),
        ("Экран Удобные платежи содержит не более 20 шаблонов.", False),
        ("Выгрузка формируется быстро — не более 5 секунд после нажатия кнопки «Выгрузить».", False),
    ]
    doc = doc_from_lines("# ТЗ", "## Функциональные требования", *[f"- **Ф-{i}.** {t}" for i, (t, _) in enumerate(lines, 1)])
    reqs = [requirement(doc, f"R{i}", f"Ф-{i}.", f"Ф-{i}") for i in range(1, len(lines) + 1)]
    res = review_individual(doc, reqs)
    ours = {rid for c in res["candidates"] for rid in c["req_ids"]}

    crit = load_criteria()
    naive_rx = [rx for g in crit.vague for rx in g.strong]
    naive = {f"R{i}" for i, (t, _) in enumerate(lines, 1) if any(rx.search(t) for rx in naive_rx)}
    truth = {f"R{i}" for i, (_, bad) in enumerate(lines, 1) if bad}

    assert ours == truth
    assert len(naive - truth) >= 4  # наивный словарь даёт ложные срабатывания на тех же строках
    assert truth <= naive
