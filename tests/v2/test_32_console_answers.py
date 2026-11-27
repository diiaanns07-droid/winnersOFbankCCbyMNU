"""№32: ответы в консоли для ``--interactive`` (№22) — вопросы по одному → текст файла ответов.

Текст, который собирает консоль, разбирает тот же ``parse_answers_text``, что и файл ``--answers``: буква, свой
текст, Enter — пропустить. Проверяем круг «ввод → файл → разбор → привязка к вопросам».
"""
from __future__ import annotations

from bcc_review.v2.stages import recheck

SHA = "ab" * 32
QUESTIONS = [
    {"id": "Q-01", "topic": "Срок хранения записи", "question": "Сколько дней хранится запись?", "blocking": True,
     "to": "Владелец продукта", "options": ["30 дней с момента создания", "90 дней с момента создания",
                                            "Бессрочно до удаления клиентом"],
     "finding_ids": ["D-01"], "if_no_answer": "D-01 блокирует разработку"},
    {"id": "Q-02", "topic": "Код ответа (при отказе)", "question": "Какой код вернуть при отказе?",
     "options": ["400", "422"], "finding_ids": ["D-02", "D-05"]},
    {"id": "Q-03", "topic": "Часовой пояс", "question": "По какому времени считать конец дня?",
     "options": ["UTC", "Время Астаны"], "finding_ids": ["D-03"]},
]


def _roundtrip(replies: dict, decisions=()) -> dict:
    text = recheck.answers_file_text(QUESTIONS, replies, document="tz.md", sha256=SHA, decisions=decisions)
    parsed = recheck.parse_answers_text(text)
    warnings: list[str] = []
    resolved = recheck.resolve_answers(QUESTIONS, parsed, warnings)
    return {"text": text, "parsed": parsed, "resolved": resolved, "warnings": warnings}


def test_letter_text_and_skip_round_trip():
    r = _roundtrip({"Q-01": "b", "Q-02": "Код 409, если запись уже есть"})
    by = {a["question_id"]: a for a in r["resolved"]["answered"]}
    assert by["Q-01"]["choice"] == "B" and by["Q-01"]["answer"] == "90 дней с момента создания"
    assert by["Q-02"]["choice"] == "" and "409" in by["Q-02"]["answer"]
    assert r["resolved"]["unanswered"] == ["Q-03"]
    assert r["resolved"]["decisions"] == []
    assert r["parsed"]["document_sha256"] == SHA
    assert "Q-01 [Срок хранения записи]: B — 90 дней с момента создания" in r["text"]
    assert "Q-02 [Код ответа (при отказе)]: Код 409" in r["text"]  # тема со скобками разбирается
    assert "Q-03 [Часовой пояс]: ?" in r["text"]
    assert not [w for w in r["warnings"] if "не разобрана" in w]


def test_cyrillic_and_digit_letters():
    r = _roundtrip({"Q-01": "Б", "Q-02": "2", "Q-03": "а"})
    by = {a["question_id"]: a for a in r["resolved"]["answered"]}
    assert (by["Q-01"]["choice"], by["Q-02"]["choice"], by["Q-03"]["choice"]) == ("B", "B", "A")
    # в файл пишется латинская буква — второй прогон не гадает, «В» это B или третий вариант
    assert "Q-01 [Срок хранения записи]: B — " in r["text"]


def test_letter_with_comment_keeps_comment():
    r = _roundtrip({"Q-01": "C — но удалять по запросу клиента"})
    a = r["resolved"]["answered"][0]
    assert a["choice"] == "C" and "удалять по запросу клиента" in a["answer"]


def test_soft_refusal_is_no_answer():
    r = _roundtrip({"Q-01": "не знаю", "Q-02": "решим позже на встрече"})
    assert r["resolved"]["answered"] == []
    assert set(r["resolved"]["unanswered"]) == {"Q-01", "Q-02", "Q-03"}


def test_decisions_section():
    r = _roundtrip({}, decisions=["Журнал операций хранить 5 лет", "  "])
    assert r["resolved"]["decisions"] == ["Журнал операций хранить 5 лет"]
    assert "## Решения" in r["text"]


def test_reply_line_errors_and_echo():
    bad = recheck.reply_line(QUESTIONS[1], "D")
    assert bad["error"] and "варианта D нет" in bad["error"] and "A–B" in bad["error"]
    ok = recheck.reply_line(QUESTIONS[0], "В")
    assert "русская «В» понята как B" in ok["echo"]
    assert recheck.reply_line(QUESTIONS[0], "")["skip"]
    assert recheck.reply_line(QUESTIONS[0], "90 дней с момента создания")["echo"].startswith("текст варианта B")
    assert "откладывает" in recheck.reply_line(QUESTIONS[0], "решим позже")["echo"]


def test_format_question():
    s = recheck.format_question(QUESTIONS[0], 1, 3)
    assert s.startswith("Вопрос 1 из 3 · Q-01 [Срок хранения записи] · блокер · кому: Владелец продукта")
    assert "  A — 30 дней с момента создания" in s and "Если ответа не будет: D-01" in s


def test_console_flow_with_retry_and_decisions():
    inputs = iter(["D", "a", "", "своё: конец дня по Астане", "Журнал хранить 5 лет", ""])
    out: list[str] = []
    res = recheck.console_answers(QUESTIONS, ask=lambda p: next(inputs), say=out.append, document="tz.md",
                                  sha256=SHA)
    assert res["answered"] == 2 and not res["stopped"]
    assert res["decisions"] == ["Журнал хранить 5 лет"]
    joined = "\n".join(out)
    assert "варианта D нет" in joined and "→ вариант A" in joined and "→ без ответа" in joined
    parsed = recheck.parse_answers_text(res["text"])
    resolved = recheck.resolve_answers(QUESTIONS, parsed, [])
    assert {a["question_id"] for a in resolved["answered"]} == {"Q-01", "Q-03"}
    assert resolved["decisions"] == ["Журнал хранить 5 лет"]


def test_console_stop_and_eof():
    feed = iter(["a", "стоп"])
    res = recheck.console_answers(QUESTIONS, ask=lambda p: next(feed), say=lambda s: None)
    assert res["stopped"] and res["answered"] == 1
    assert "Q-02 [Код ответа (при отказе)]: ?" in res["text"]  # оставшиеся — без ответа, их можно дописать

    def eof(_prompt):
        raise EOFError
    res = recheck.console_answers(QUESTIONS, ask=eof, say=lambda s: None)
    assert res["stopped"] and res["answered"] == 0
    assert recheck.parse_answers_text(res["text"])["answers"]  # строки «?» есть, ответа нет
    assert recheck.resolve_answers(QUESTIONS, recheck.parse_answers_text(res["text"]), [])["answered"] == []


def test_answers_path():
    assert recheck.answers_path("out/report.md").name == "report.answers.md"
