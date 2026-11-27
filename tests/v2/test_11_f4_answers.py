"""№11, ранняя обратная связь F4: два адресата отвечают на один вопрос по-разному; мягкий отказ от решения.

Проверки общие — на синтетических вопросах и ответах, без файлов экзамена F4.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import recheck, revise  # noqa: E402
from test_11_clarify import FakeCtx, FakeLLM  # noqa: E402

QS = [
    {"id": "Q-01", "topic": "Код ответа при отказе антифрода", "question": "Какой код вернуть при отказе антифрода?",
     "options": ["422", "403"], "finding_ids": ["D-01"]},
    {"id": "Q-02", "topic": "Маршрут вызова между сервисами", "question": "Через какой сервис идёт вызов перевода?",
     "options": ["Через шлюз", "Напрямую"], "finding_ids": ["D-02"]},
    {"id": "Q-03", "topic": "Срок хранения идентификатора запроса", "question": "Сколько хранить requestId?",
     "options": ["24 часа", "48 часов"], "finding_ids": ["D-03"]},
]
FINDINGS = [{"id": f"D-0{i}", "severity": "critical", "kind": "contradiction", "title": f"Дефект {i}",
             "blocks": "both", "priority": i, "evidence": [], "problem": "…", "scenario": "…"} for i in (1, 2, 3)]
TWO = ("Q-01 [Код ответа при отказе антифрода]: Команда рисков: на отказ антифрода возвращаем 422, деньги не списываем.\n"
       "Q-01 [Код ответа при отказе антифрода]: Владелец API: на тот же отказ возвращаем 403, деньги не списываем.\n")


def _report():
    return {"findings": FINDINGS, "questions": QS, "verdict": {}, "run": {"status": "complete"}}


def _resp(decisions):
    return {"decisions": [dict({"severity": "critical", "title": "", "problem": "", "by": [], "conflicting_answers": [],
                                "reason": "", "status": "open"}, **d) for d in decisions], "candidates": []}


# --------------------------------------------------------------------------- два адресата
@pytest.mark.parametrize("renumber", [False, True])
def test_two_addressees_both_bound_to_question(renumber):
    text = TWO.replace("Q-01", "Q-07") if renumber else TWO  # номер устарел — привязка по теме
    r = recheck.resolve_answers(QS, recheck.load_answers(text))
    assert r["decisions"] == []
    q = next(a for a in r["answered"] if a["question_id"] == "Q-01")
    assert [x["label"] for x in q["replies"]] == ["Q-01.1", "Q-01.2"]
    assert "422" in q["replies"][0]["text"] and "403" in q["replies"][1]["text"]


def test_two_addressees_without_topic_hint():
    text = "Q-01: на отказ возвращаем 422.\nQ-01: на отказ возвращаем 403.\n"
    q = recheck.resolve_answers(QS, recheck.load_answers(text))["answered"][0]
    assert len(q["replies"]) == 2


def test_both_replies_reach_recheck_prompt():
    llm = FakeLLM(_resp([{"finding_id": "D-01"}]))
    recheck.run(FakeCtx(llm), FINDINGS, TWO, QS)
    user = llm.calls[0]["user"]
    assert "Q-01.1" in user and "Q-01.2" in user and "422" in user and "403" in user


@pytest.mark.parametrize("named", [["Q-01"], ["Q-01.1", "Q-01.2"]])
def test_conflicting_replies_keep_defect_open(named):
    resp = _resp([{"finding_id": "D-01", "status": "resolved", "by": ["Q-01"], "conflicting_answers": named,
                   "reason": "выбран код"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-01")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-01.1", "Q-01.2"]
    assert clar["answer_conflicts"][0]["answers"] == ["Q-01.1", "Q-01.2"]


def test_closing_by_one_reply_ignores_other_stays_open():
    resp = _resp([{"finding_id": "D-01", "status": "resolved", "by": ["Q-01.1"], "reason": "снят ответом Q-01.1"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-01")
    assert ch["status"] == "open" and "Q-01.2" in ch["reason"]


def test_complementary_replies_close_when_both_named():
    resp = _resp([{"finding_id": "D-01", "status": "resolved", "by": ["Q-01"], "reason": "снят ответом Q-01"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-01")
    assert ch["status"] == "resolved" and ch["answer_ids"] == ["Q-01.1", "Q-01.2"] and ch["question_ids"] == ["Q-01"]


def test_conflict_not_written_to_revision_as_agreed():
    resp = _resp([{"finding_id": "D-01", "conflicting_answers": ["Q-01"], "reason": "ответы расходятся"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    block, _ = revise._answers_block(clar)
    assert "ответы расходятся" in block and "<уточнить" in block


# --------------------------------------------------------------------------- мягкий отказ
@pytest.mark.parametrize("soft", [
    "Не знаю, решение по маршруту примем после встречи команд.",
    "Пока не знаю.",
    "Решим позже.",
    "Хороший вопрос. Обсудим потом.",
    "Ещё решаем.",
    "Вопрос пока открыт.",
    "TBD",
])
def test_soft_refusal_is_not_an_answer(soft):
    w: list[str] = []
    r = recheck.resolve_answers(QS, recheck.load_answers(f"Q-02 [Маршрут вызова между сервисами]: {soft}\n"), w)
    assert "Q-02" in r["unanswered"] and not r["answered"] and r["decisions"] == []
    assert any("Q-02" in x for x in w)


def test_soft_refusal_keeps_defect_open_and_out_of_revision():
    text = "Q-02 [Маршрут вызова между сервисами]: Пока не знаю, решим после встречи.\n"
    llm = FakeLLM(_resp([]))
    clar = recheck.apply_answers(FakeCtx(llm), _report(), text)["clarification"]
    assert not llm.calls  # пересматривать нечего — ответа нет
    assert "Q-02" in clar["unanswered"] and not clar["answers"]
    assert "Пока не знаю" not in revise._answers_block(clar)[0]


def test_soft_general_decision_is_dropped():
    r = recheck.resolve_answers(QS, recheck.load_answers("Q-01: A\n\n## Решения\n- Про лимиты договоримся отдельно.\n"))
    assert r["decisions"] == []


def test_partial_answer_keeps_rule_and_marks_deferred_part():
    text = ("Q-03 [Срок хранения идентификатора запроса]: Храним 48 часов с первого запроса. "
            "Что делать после истечения срока, ещё решаем.\n")
    r = recheck.resolve_answers(QS, recheck.load_answers(text))
    a = r["answered"][0]
    assert "48 часов" in a["answer"] and "ещё решаем" not in a["answer"]
    assert a["deferred"] == ["Что делать после истечения срока, ещё решаем."]
    assert "владелец не решил" in recheck._format_answers(r)
    assert "не решено владельцем" in revise._answers_block(r)[0]


@pytest.mark.parametrize("rule", [
    "Если тип карты не определён, возвращаем 400.",
    "QR действует, пока открыт заказ.",
    "Push отправляем, когда порог достигнут, после проведения покупки.",
    "Здесь ещё ни одного push не было, поэтому шлём сразу.",
])
def test_rules_with_similar_words_are_answers(rule):
    body, deferred = recheck.split_deferred(rule)
    assert body == rule and deferred == []


# --------------------------------------------------------------------------- разные буквы у адресатов
LETTERS = "Q-03 [Срок хранения идентификатора запроса]: A\nQ-03 [Срок хранения идентификатора запроса]: B\n"


@pytest.mark.parametrize("model_status", ["resolved", "open"])
def test_different_letters_are_conflict_without_model_opinion(model_status):
    resp = _resp([{"finding_id": "D-03", "status": model_status, "by": ["Q-03"] if model_status != "open" else [],
                   "reason": "выбран срок"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), LETTERS)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-03")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-03.1", "Q-03.2"]
    assert clar["answer_conflicts"][0]["answers"] == ["Q-03.1", "Q-03.2"]


def test_different_letters_conflict_when_model_fails():
    clar = recheck.apply_answers(FakeCtx(FakeLLM(exc=RuntimeError("нет сети"))), _report(), LETTERS)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-03")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-03.1", "Q-03.2"]


def test_same_letter_twice_is_one_reply():
    text = "Q-03: B\nQ-03: B\n"
    a = recheck.resolve_answers(QS, recheck.load_answers(text))["answered"][0]
    assert len(a["replies"]) == 1 and not a.get("choice_conflict")


# --------------------------------------------------------------------------- частичный ответ
PARTIAL = ("Q-03 [Срок хранения идентификатора запроса]: Храним 48 часов с первого запроса. "
           "Что делать после истечения срока, ещё решаем.\n")


def test_partial_answer_cannot_fully_resolve():
    resp = _resp([{"finding_id": "D-03", "status": "resolved", "by": ["Q-03"], "reason": "срок задан ответом Q-03"}])
    out = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), PARTIAL)
    ch = next(c for c in out["clarification"]["changes"] if c["finding_id"] == "D-03")
    assert ch["status"] == "changed" and ch["severity_after"] == "critical"
    left = next(f for f in out["findings_after"] if f["id"] == "D-03")
    assert "ещё решаем" in left["problem"]


def test_full_answer_still_resolves():
    text = "Q-03 [Срок хранения идентификатора запроса]: Храним 48 часов с первого запроса, потом запрос новый.\n"
    resp = _resp([{"finding_id": "D-03", "status": "resolved", "by": ["Q-03"], "reason": "срок задан ответом Q-03"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), text)["clarification"]
    assert next(c for c in clar["changes"] if c["finding_id"] == "D-03")["status"] == "resolved"


@pytest.mark.parametrize("text", ["Q-03: B, но что после срока — решим позже", "Q-03: B. Пока не знаю, как считать срок"])
def test_deferred_comment_to_letter_is_not_rule(text):
    a = recheck.resolve_answers(QS, recheck.load_answers(text))["answered"][0]
    assert a["choice"] == "B" and a["answer"] == "48 часов" and a["deferred"]


def test_plain_comment_to_letter_is_kept():
    a = recheck.resolve_answers(QS, recheck.load_answers("Q-03: B — считаем от первого запроса"))["answered"][0]
    assert a["answer"] == "48 часов (считаем от первого запроса)" and a["deferred"] == []


def test_postponed_listed_in_report_section():
    text = PARTIAL + "Q-02 [Маршрут вызова между сервисами]: Не знаю, примем после встречи команд.\n"
    resp = _resp([{"finding_id": "D-03", "status": "changed", "by": ["Q-03"], "reason": "срок задан ответом Q-03"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), text)["clarification"]
    assert [(p["question_id"], p["partial"]) for p in clar["postponed"]] == [("Q-02", False), ("Q-03", True)]
    md = recheck.render_markdown(clar)
    assert "Владелец отложил решение" in md and "Q-02 (весь ответ)" in md and "Q-03 (часть ответа)" in md


def test_second_addressee_with_own_topic_words_is_second_reply():
    text = ("Q-01 [Код ответа при отказе антифрода]: Команда рисков: на отказ антифрода возвращаем 422.\n"
            "Q-01 [Что вернуть API на отказ антифрода]: Владелец API: на тот же отказ возвращаем 403.\n")
    r = recheck.resolve_answers(QS, recheck.load_answers(text))
    assert r["decisions"] == []
    assert [x["label"] for x in r["answered"][0]["replies"]] == ["Q-01.1", "Q-01.2"]


def test_other_number_on_taken_question_is_not_merged():
    # ответ с другим номером, чья тема совпала с уже занятым вопросом, — не вторая реплика этого вопроса
    text = ("Q-01 [Код ответа при отказе антифрода]: возвращаем 422.\n"
            "Q-05 [Код ответа при отказе антифрода]: возвращаем 403.\n")
    r = recheck.resolve_answers(QS, recheck.load_answers(text))
    q1 = next(a for a in r["answered"] if a["question_id"] == "Q-01")
    assert len(q1["replies"]) == 1


@pytest.mark.parametrize("data", [
    {"answers": {"Q-01": ["на отказ возвращаем 422", {"text": "на отказ возвращаем 403"}]}},
    [{"id": "Q-01", "text": "на отказ возвращаем 422"}, {"id": "Q-01", "text": "на отказ возвращаем 403"}],
])
def test_json_two_replies(data):
    a = recheck.resolve_answers(QS, recheck.load_answers(data))["answered"][0]
    assert [r["text"] for r in a["replies"]] == ["на отказ возвращаем 422", "на отказ возвращаем 403"]


def test_json_soft_refusal():
    r = recheck.resolve_answers(QS, recheck.load_answers({"Q-02": {"text": "пока не знаю, решим после встречи"}}))
    assert r["answered"] == [] and r["postponed"][0]["question_id"] == "Q-02"


def test_duplicate_model_decisions_most_cautious_wins():
    resp = _resp([{"finding_id": "D-01", "status": "open", "conflicting_answers": ["Q-01"], "reason": "ответы расходятся"},
                  {"finding_id": "D-01", "status": "resolved", "by": ["Q-01"], "reason": "снят ответом Q-01"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-01")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-01.1", "Q-01.2"]


# --------------------------------------------------------------------------- редакция при расходящихся ответах
def _rw(fid, new):
    return {"finding_id": fid, "edits": [{"action": "replace", "line": 1, "old": "x", "new": new}]}


def test_conflict_rewrite_without_marker_is_dropped():
    resp = _resp([{"finding_id": "D-01", "conflicting_answers": ["Q-01"], "reason": "ответы расходятся"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    assert revise.unsettled_findings(clar) == {"D-01"}
    assert revise._answers_block(clar)[1].get("D-01") is None  # правка не ссылается на несогласованный ответ
    w: list[str] = []
    kept = revise.drop_unsettled([_rw("D-01", "возвращаем 422"), _rw("D-02", "через шлюз")], {"D-01"}, w)
    assert [r["finding_id"] for r in kept] == ["D-02"] and "D-01" in w[0]
    kept = revise.drop_unsettled([_rw("D-01", "возвращаем <уточнить: 422 или 403>")], {"D-01"}, [])
    assert len(kept) == 1


def test_agreed_replies_are_not_unsettled():
    resp = _resp([{"finding_id": "D-01", "status": "resolved", "by": ["Q-01"], "reason": "снят ответом Q-01"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    assert revise.unsettled_findings(clar) == set()
    assert revise._answers_block(clar)[1]["D-01"] == ["Q-01"]


# --------------------------------------------------------------------------- форматы строки ответа
@pytest.mark.parametrize("line,qid,topic,choice,text", [
    ("Q-01 [Момент утраты льготного периода (LOST)]: B", "Q-01", "Момент утраты льготного периода (LOST)", 1, ""),
    ("Q-02 [Срок [UTC+5] хранения]: 48 часов", "Q-02", "Срок [UTC+5] хранения", None, "48 часов"),
    ("Q-07 (тема): свой ответ", "Q-07", "тема", None, "свой ответ"),
    ("**Q-04.** B", "Q-04", "", 1, ""),
    ("Q-05) A", "Q-05", "", 0, ""),
    ("Вопрос 6: B", "Q-06", "", 1, ""),
    ("| Q-03 | Срок хранения | 48 часов |", "Q-03", "Срок хранения", None, "48 часов"),
])
def test_answer_line_forms(line, qid, topic, choice, text):
    a = recheck.parse_answers_text(line)["answers"]
    assert [(x["id"], x["topic_hint"], x["choice"], x["text"]) for x in a] == [(qid, topic, choice, text)]


def test_html_export_with_parenthesis_topic_binds():
    # так строку выгружает кнопка «Скачать ответы» HTML-отчёта; раньше строка терялась без предупреждения
    qs = [dict(QS[0], topic="Момент утраты льготного периода (LOST)")]
    r = recheck.resolve_answers(qs, recheck.load_answers("Q-01 [Момент утраты льготного периода (LOST)]: B\n"))
    assert r["answered"][0]["choice"] == "B"


def test_table_header_and_empty_answer_are_skipped():
    text = "| Вопрос | Тема | Ответ |\n| :--- | :--- | :--- |\n| Q-01 | Тема | |\n| Q-02 | Маршрут | Через шлюз |\n"
    a = recheck.parse_answers_text(text)["answers"]
    assert [(x["id"], x["text"]) for x in a] == [("Q-02", "Через шлюз")]


def test_unparsed_question_line_is_warned():
    w: list[str] = []
    recheck.resolve_answers(QS, recheck.load_answers("Q-01 ответ без разделителя\n"), w)
    assert any("не разобрана" in x for x in w)


@pytest.mark.parametrize("enc", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1251"])
def test_answers_file_encodings(tmp_path, enc):
    p = tmp_path / "answers.md"
    p.write_bytes("Q-02 [Маршрут вызова между сервисами]: Через шлюз платежей.\r\n".encode(enc))
    a = recheck.load_answers(str(p))["answers"]
    assert a[0]["id"] == "Q-02" and a[0]["text"] == "Через шлюз платежей."


def test_answers_json_file_in_utf16(tmp_path):
    p = tmp_path / "answers.json"
    p.write_bytes('{"Q-01": "B"}'.encode("utf-16"))
    assert recheck.load_answers(str(p))["answers"][0]["choice"] == 1


@pytest.mark.parametrize("dec", ["Квитанцию можно скачать 12 дней.", ["Квитанцию можно скачать 12 дней."],
                                 [{"text": "Квитанцию можно скачать 12 дней."}]])
def test_json_decisions_forms(dec):
    assert recheck.load_answers({"Q-01": "B", "decisions": dec})["decisions"] == ["Квитанцию можно скачать 12 дней."]


def test_revise_crash_keeps_recheck(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("сломалась редакция")
    monkeypatch.setattr(revise, "run", boom)
    resp = _resp([{"finding_id": "D-01", "conflicting_answers": ["Q-01"], "reason": "ответы расходятся"}])
    out = revise.run_modes(FakeCtx(FakeLLM(resp)), _report(), answers=TWO, do_revise=True)
    assert out["clarification"]["answer_conflicts"] and out["revise_stats"]["status"] == "failed"


def test_cyrillic_v_is_b_with_warning():
    qs = [dict(QS[0], options=["422", "403", "409"])]
    w: list[str] = []
    a = recheck.resolve_answers(qs, recheck.load_answers("Q-01: В\n"), w)["answered"][0]
    assert a["choice"] == "B" and any("кириллическая «В»" in x for x in w)
    w2: list[str] = []
    recheck.resolve_answers(qs, recheck.load_answers("Q-01: Б\n"), w2)
    assert not any("кириллическая" in x for x in w2)


# --------------------------------------------------------------------------- перенос строки ответа
def test_wrapped_answer_without_indent_is_kept():
    text = "Q-02 [Маршрут вызова между сервисами]: Вызов идёт через шлюз платежей,\nбез прямого обращения к процессингу.\n\nQ-01: A\n"
    a = {x["id"]: x for x in recheck.parse_answers_text(text)["answers"]}
    assert a["Q-02"]["text"] == "Вызов идёт через шлюз платежей, без прямого обращения к процессингу."
    assert a["Q-01"]["choice"] == 0


def test_letter_with_comment_on_next_line():
    a = recheck.parse_answers_text("Q-03: B\nсчитаем от первого запроса\n")["answers"][0]
    assert a["choice"] == 1 and a["comment"] == "считаем от первого запроса"


@pytest.mark.parametrize("text,choice,body", [("Q-03:\nB\n", 1, ""), ("Q-02:\nЧерез шлюз платежей.\n", None,
                                                                         "Через шлюз платежей.")])
def test_value_on_next_line(text, choice, body):
    a = recheck.parse_answers_text(text)["answers"][0]
    assert a["choice"] == choice and a["text"] == body


def test_explicit_no_answer_has_no_continuation():
    text = "Q-04: ?\nэто строка-пояснение вне ответа\n"
    a = recheck.parse_answers_text(text)["answers"][0]
    assert a["choice"] is None and a["text"] == ""


def test_blank_line_ends_answer():
    text = "Q-02: Через шлюз.\n\nПримечание для команды, не ответ.\n"
    assert recheck.parse_answers_text(text)["answers"][0]["text"] == "Через шлюз."


# --------------------------------------------------------------------------- вопросы старого или чужого отчёта
def test_question_without_id_does_not_crash():
    w: list[str] = []
    qs = [{"topic": "без номера", "question": "?", "options": ["a", "b"]}, "не словарь", QS[0]]
    r = recheck.resolve_answers(qs, recheck.load_answers("Q-01: A\n"), w)
    assert r["answered"][0]["question_id"] == "Q-01" and any("нет номера" in x for x in w)


def test_question_ids_in_other_format_bind_and_label():
    qs = [dict(q, id=q["id"].replace("Q-0", "Q-")) for q in QS]  # «Q-1», «Q-2», «Q-3» в старом отчёте
    r = recheck.resolve_answers(qs, recheck.load_answers("Q-01: A\nQ-01: B\n"))
    a = r["answered"][0]
    assert a["question_id"] == "Q-1" and [x["label"] for x in a["replies"]] == ["Q-1.1", "Q-1.2"]
    valid = recheck.answer_labels(r)
    assert recheck.norm_labels(["Q-01.2", "q-1"], valid) == ["Q-1.2", "Q-1"]
    resp = _resp([{"finding_id": "D-01", "status": "resolved", "by": ["Q-01"], "reason": "снят ответом Q-01"}])
    rep = dict(_report(), questions=qs)
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), rep, "Q-01: A\nQ-01: B\n")["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-01")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-1.1", "Q-1.2"]  # разные буквы — конфликт


def test_conflict_shows_reply_texts():
    resp = _resp([{"finding_id": "D-01", "conflicting_answers": ["Q-01"], "reason": "ответы расходятся"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), TWO)["clarification"]
    texts = clar["answer_conflicts"][0]["texts"]
    assert "422" in texts["Q-01.1"] and "403" in texts["Q-01.2"]
    md = recheck.render_markdown(clar)
    assert "Q-01.1 «Команда рисков: на отказ антифрода возвращаем 422" in md and "↔ Q-01.2 «Владелец API" in md


@pytest.mark.parametrize("soft", ["Решение пока не принято.", "Пока неизвестно.", "Вопрос на согласовании у юристов.",
                                  "В процессе согласования с процессингом.", "Ждём решения от рисков.",
                                  "Как обычно.", "По ситуации."])
def test_more_soft_refusals(soft):
    r = recheck.resolve_answers(QS, recheck.load_answers(f"Q-02 [Маршрут вызова между сервисами]: {soft}\n"))
    assert "Q-02" in r["unanswered"] and not r["answered"]


def test_vague_sentence_keeps_rule_part():
    text = "Q-03 [Срок хранения идентификатора запроса]: Храним 48 часов с первого запроса. Остальное как обычно.\n"
    a = recheck.resolve_answers(QS, recheck.load_answers(text))["answered"][0]
    assert a["answer"] == "Храним 48 часов с первого запроса." and a["deferred"] == ["Остальное как обычно."]


@pytest.mark.parametrize("rule", ["Ждём подтверждения эмитента 30 секунд, затем отказ 504.",
                                  "Статус платежа неизвестен — возвращаем 202 и опрашиваем процессинг."])
def test_rules_near_soft_words_stay(rule):
    assert recheck.split_deferred(rule) == (rule, [])


# --------------------------------------------------------------------------- текст варианта вместо буквы
def test_option_text_is_recognized_as_choice():
    a = recheck.resolve_answers(QS, recheck.load_answers("Q-03: 48 часов.\n"))["answered"][0]
    assert a["choice"] == "B" and a["answer"] == "48 часов"


def test_two_addressees_pasting_different_options_conflict():
    resp = _resp([{"finding_id": "D-03", "status": "resolved", "by": ["Q-03"], "reason": "срок задан"}])
    text = "Q-03: 24 часа\nQ-03: B) 48 часов\n"
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), text)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-03")
    assert ch["status"] == "open" and ch["answer_conflict"] == ["Q-03.1", "Q-03.2"]


@pytest.mark.parametrize("item,choice,comment", [
    ({"question_id": "Q-03", "option_index": 1, "option": "48 часов", "text": ""}, "B", ""),
    ({"question_id": "Q-03", "option_index": 0, "text": "от первого запроса"}, "A", "от первого запроса"),
    ({"question_id": "Q-03", "option": "48 часов", "text": "от первого запроса"}, "B", "от первого запроса"),
])
def test_web_answers_schema(item, choice, comment):
    data = {"schema": "bcc-review/answers-1", "answers": [item]}
    a = recheck.resolve_answers(QS, recheck.load_answers(data))["answered"][0]
    assert a["choice"] == choice and a["answer"] == QS[2]["options"]["AB".index(choice)] + (f" ({comment})" if comment else "")


def test_own_text_longer_than_option_stays_own():
    a = recheck.resolve_answers(QS, recheck.load_answers("Q-03: 48 часов, но только для карт в тенге\n"))["answered"][0]
    assert a["choice"] == "" and a["answer"].startswith("48 часов, но только")


def test_letter_with_repeated_option_text_has_no_duplicate():
    a = recheck.resolve_answers(QS, recheck.load_answers("Q-03: B) 48 часов\n"))["answered"][0]
    assert a["answer"] == "48 часов"
