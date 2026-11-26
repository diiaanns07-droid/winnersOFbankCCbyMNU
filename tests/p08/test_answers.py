"""Файл вопросов с пустыми «Ответ:» и разбор --answers (в том числе экспорт HTML №13)."""
from __future__ import annotations

import re

import pytest

from bcc_review.decisions import interpret, parse_answers
from bcc_review.decisions._demo import EXAMPLES_DIR
from bcc_review.decisions.__main__ import fill_answers


def test_questions_file_has_empty_answer_per_card(doc, questions, questions_md):
    assert questions_md.startswith("<!-- bcc-review:answers v1 -->")
    assert f"source_sha256: {doc['id']}" in questions_md
    assert len(re.findall(r"(?m)^Ответ:\s*$", questions_md)) == len(questions)
    for label in ("Владелец решения", "Что блокируется", "**Вопрос.**", "**Почему важно.**",
                  "Исходные цитаты и координаты", "**Свой ответ.**", "**Отложить.**"):
        assert questions_md.count(label) == len(questions), label
    n_options = sum(len(q.options) for q in questions)
    for label in ("Трактовка:", "Наблюдаемый результат:", "Последствия:"):
        assert questions_md.count(label) == n_options, label
    assert "Источник ответа в документе" in questions_md
    assert "Гипотеза о намерении автора (не решение" in questions_md
    aset = parse_answers(questions_md, questions=questions, expected_sha=doc["id"])
    assert aset.source_sha256 == doc["id"]
    assert aset.decisions == [] and aset.open_ids == ["Q-01", "Q-02", "Q-03", "Q-04"]
    assert aset.unknown_ids == aset.duplicate_ids == []


def test_filled_template_roundtrip_with_multiline_answer(doc, questions, questions_md):
    text = fill_answers(questions_md, {
        "Q-01": "A",
        "Q-03": "Минимум 10 000 ₸.\nНиже — отказ.\nФормулировка: Минимальная сумма — 10 000 ₸.",
    })
    aset = parse_answers(text, questions=questions, expected_sha=doc["id"])
    assert [d.question_id for d in aset.decisions] == ["Q-01", "Q-03"]
    q3 = aset.decision("Q-03")
    assert q3.answer == "Минимум 10 000 ₸.\nНиже — отказ.\nФормулировка: Минимальная сумма — 10 000 ₸."
    assert q3.choice == "custom" and q3.wording == "Минимальная сумма — 10 000 ₸."
    assert aset.open_ids == ["Q-02", "Q-04"]  # пустые не обрабатываются


def test_unknown_and_duplicate_ids(doc, questions):
    text = f"""<!-- bcc-review:answers v1 -->
source_sha256: {doc['id']}

## Q-01
Ответ: A

## Q-01. повтор карточки с другим ответом
Ответ: B

## Q-02
Ответ: отложить

## Q-02
Ответ: отложить

## Q-09
Ответ: A
"""
    aset = parse_answers(text, questions=questions, expected_sha=doc["id"])
    assert aset.unknown_ids == ["Q-09"]
    assert aset.duplicate_ids == ["Q-01", "Q-02"]
    assert aset.decision("Q-01") is None  # два разных ответа — решение не принято
    assert aset.decision("Q-02").choice == "defer"
    codes = {w.split("]")[0] + "]" for w in aset.warnings}
    assert {"[duplicate_conflict]", "[duplicate_id]", "[unknown_id]", "[missing_card]"} <= codes
    assert set(aset.open_ids) == {"Q-03", "Q-04"}


def test_html_export_minimal_format_reads_with_same_code(doc, questions):
    """Экспорт HTML №13: без карточек, CRLF, BOM, NBSP, жирное «Ответ:», комментарии."""
    body = (
        "﻿<!-- bcc-review:answers v1 -->\r\n"
        f"<!-- source_sha256: {doc['id']} -->\r\n\r\n"
        "### Q-01\r\n**Ответ:** B\r\n\r\n"
        "### Q-02\r\nОтвет: <!-- подсказка из формы -->\r\n\r\n"
        "### Q-03\r\nОтвет:\r\n  Минимум задаёт казначейство.\r\n  Формулировка: Минимальная сумма "
        "частичного досрочного погашения не ограничивается.\r\n---\r\n"
        "### Q-04\r\n**Ответ**: отложить\r\n"
    )
    aset = parse_answers(body, questions=questions, expected_sha=doc["id"])
    assert aset.source_sha256 == doc["id"]
    assert {d.question_id: d.choice for d in aset.decisions} == {"Q-01": "B", "Q-03": "custom", "Q-04": "defer"}
    assert aset.decision("Q-03").answer.endswith("не ограничивается.")
    assert aset.open_ids == ["Q-02"]
    ref = parse_answers(EXAMPLES_DIR / "answers_html_export.md", questions=questions, expected_sha=doc["id"])
    assert ref.source_sha256 == doc["id"] and ref.decisions


def test_committed_demo_answers_are_labelled_and_parse(doc, questions):
    for v, expected in (("A", {"Q-01": "A", "Q-02": "defer", "Q-03": "custom", "Q-04": "A"}),
                        ("B", {"Q-01": "B", "Q-03": "B"})):
        p = EXAMPLES_DIR / f"answers_team_{v}.md"
        assert "Демонстрационные ответы команды" in p.read_text(encoding="utf-8")
        aset = parse_answers(p, questions=questions, expected_sha=doc["id"])
        assert {d.question_id: d.choice for d in aset.decisions} == expected
        assert aset.source_sha256 == doc["id"]


@pytest.mark.parametrize("answer, choice, comment, wording", [
    ("", "open", "", ""),
    ("  —  ", "open", "", ""),
    ("A", "A", "", ""),
    ("a", "A", "", ""),
    ("А", "A", "", ""),                      # кириллица
    ("Б", "B", "", ""),
    ("Вариант B", "B", "", ""),
    ("вариант в", "B", "", ""),
    ("B. Но показываем комиссию заранее", "B", "Но показываем комиссию заранее", ""),
    ("A. В течение месяца уточним", "A", "В течение месяца уточним", ""),
    ("A\nКомментарий: тариф устарел", "A", "Комментарий: тариф устарел", ""),
    ("В течение трёх рабочих дней", "custom", "", ""),   # «В» — начало фразы, не вариант
    ("С учётом выходных — по ДП-3", "custom", "", ""),
    ("А если клиент в отпуске?", "custom", "", ""),
    ("A, B", "invalid", "A, B", ""),
    ("A и B", "invalid", "A и B", ""),
    ("отложить", "defer", "", ""),
    ("Отложено до решения казначейства", "defer", "до решения казначейства", ""),
    ("Формулировка: Комиссия не взимается.", "custom", "", "Комиссия не взимается."),
    ("B\nФормулировка: Комиссия 1%.", "B", "", "Комиссия 1%."),
])
def test_interpret(answer, choice, comment, wording):
    assert interpret(answer) == (choice, comment, wording)


def test_sha_problems_are_reported(questions):
    no_sha = parse_answers("## Q-01\nОтвет: A\n", questions=questions)
    assert no_sha.source_sha256 is None and any(w.startswith("[no_sha]") for w in no_sha.warnings)
    two = parse_answers(f"source_sha256: {'a' * 64}\nsource_sha256: {'b' * 64}\n## Q-01\nОтвет: A\n")
    assert two.source_sha256 is None and any(w.startswith("[sha_conflict]") for w in two.warnings)
    other = parse_answers(f"source_sha256: {'c' * 64}\n## Q-01\nОтвет: A\n", expected_sha="d" * 64)
    assert any(w.startswith("[stale_answers]") for w in other.warnings)


# --------------------------------------------------------------------------- форматы №13 и резерва Max

from pathlib import Path  # noqa: E402

from bcc_review.decisions import propose_patch  # noqa: E402
from bcc_review.decisions.answers import parse_edit_specs  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def transfer():
    from bcc_review.decisions._doc import load_document

    return load_document(FIX / "transfer_tz.md")


def test_parse_13_export_resolves_option_edit(transfer):
    aset = parse_answers(FIX / "answers13_Q01_A.md", transfer)
    assert aset.source_sha256 == transfer["id"]
    (d,) = list(aset)
    assert (d.question_id, d.choice, d.answer) == ("Q-01", "A", "A")
    assert d.option_text.startswith("На следующий рабочий день — ")
    assert [(e["block_id"], e["start"], e["end"], e["old"], e["new"]) for e in d.edits] == [
        ("b0009", 64, 90, "Перевод исполнен в пятницу", "Перевод исполнен в следующий рабочий день")]
    assert aset.open_ids == ["Q-02", "Q-03"]
    (c,) = aset.get("decisions")  # вид для движка: dict Decision v1
    assert c["question_id"] == "Q-01" and c["edits"][0]["origin"] == "option"


def test_13_escaped_heading_lines_are_unescaped(transfer):
    text = (f"---\nformat: bcc-review-answers/1\nsource_sha256: {transfer['id']}\n---\n\n## Q-01\n\n"
            "> вопрос\n\n### Ответ\n\n\\# не заголовок, а текст ответа\nвторая строка\n")
    (d,) = list(parse_answers(text, transfer))
    assert d.answer == "# не заголовок, а текст ответа\nвторая строка" and d.choice == "custom"


def test_fallback_format_with_explicit_edit(transfer):
    text = (f"source_sha256: {transfer['id']}\n\n## Q-001\nОтвет: перевод исполняется на следующий день\n"
            "Правка: «Перевод исполнен в пятницу» → «Перевод исполнен в понедельник»\n")
    aset = parse_answers(text, transfer)
    (c,) = aset.get("decisions")
    p = propose_patch(transfer, None, c)            # вызов движка
    assert p["state"] == "proposed" and c["patch_state"] == "proposed"
    assert c["edits"] is p["edits"] and c["edits"][0]["origin"] == "owner"


def test_letter_without_options_line_explains_what_is_missing(transfer):
    text = f"source_sha256: {transfer['id']}\n\n## Q-01\nОтвет: A\n"
    (c,) = parse_answers(text, transfer).get("decisions")
    p = propose_patch(transfer, None, c)
    assert p["state"] == "needs_wording" and p["warnings"][0].startswith("[no_option_data]")


def test_edit_specs_with_nested_quotes_and_block_hint():
    specs = parse_edit_specs("A · Правка [b0003]: «выполняется без комиссии» → «выполняется с комиссией по "
                             "разделу «Тарифы»» · Правка: «x» -> «y»", "option")
    assert specs == [
        {"block_id": "b0003", "old": "выполняется без комиссии",
         "new": "выполняется с комиссией по разделу «Тарифы»", "origin": "option"},
        {"block_id": None, "old": "x", "new": "y", "origin": "option"},
    ]


def test_ambiguous_fragment_is_rejected_with_reason(transfer):
    text = (f"source_sha256: {transfer['id']}\n\n## Q-09\nОтвет: свой\n"
            "Правка: «перевод» → «платёж»\n")
    (c,) = parse_answers(text, transfer).get("decisions")
    p = propose_patch(transfer, None, c)
    assert p["state"] == "precondition_failed" and "встречается" in p["warnings"][0]
