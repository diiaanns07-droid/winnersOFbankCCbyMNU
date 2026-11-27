"""№56: реплика без собственного предмета без привязки к вопросу — переспросить, а не вносить общим решением."""
from bcc_review.v2.stages import recheck

QUESTIONS = [
    {"id": "Q-01", "topic": "Срок хранения выписки", "question": "Сколько дней хранится выписка?",
     "options": ["30 дней", "90 дней"], "finding_ids": ["D-01"]},
    {"id": "Q-02", "topic": "Код ответа при блокировке карты", "question": "Какой код вернуть?",
     "options": ["403", "423"], "finding_ids": ["D-02"]},
]


def _resolve(text: str) -> dict:
    return recheck.resolve_answers(QUESTIONS, recheck.parse_answers_text(text))


def test_decision_that_only_names_an_option_is_asked_not_applied():
    res = _resolve("Q-01: A\n\n## Решения\n\n- По сроку — второй вариант.\n")
    assert res["decisions"] == []
    pend = res["needs_confirmation"]
    assert [p["text"] for p in pend] == ["По сроку — второй вариант."]
    assert [a["question_id"] for a in res["answered"]] == ["Q-01"]


def test_answer_to_missing_number_without_subject_is_asked():
    res = _resolve("Q-07: Да, так и оставляем.\n")
    assert res["decisions"] == []
    assert res["needs_confirmation"][0]["question_id"] == "Q-07"


def test_unmatched_topic_with_bare_confirmation_is_asked():
    res = _resolve("Q-01: B\nQ-02 [Напоминание]: Да, включаем.\n")
    assert res["decisions"] == []
    assert res["needs_confirmation"][0]["text"] == "Да, включаем."
    assert [a["question_id"] for a in res["answered"]] == ["Q-01"]


def test_self_contained_rules_stay_general_decisions():
    res = _resolve("## Решения\n\n- Push отправляем не позже 10:00 по местному времени.\n"
                   "- Да, клиент может отключить уведомления в настройках профиля.\n")
    assert len(res["decisions"]) == 2
    assert not res.get("needs_confirmation")
    orphan = _resolve("Q-09: Выписку храним 180 дней, после этого удаляем.\n")
    assert orphan["decisions"] and not orphan.get("needs_confirmation")


def test_needs_binding_rule():
    for text in ("второй вариант", "Как в варианте B.", "Делаем по варианту 2", "B", "Да.", "Согласен",
                 "Да, так и оставляем.", "Нет, не нужно"):
        assert recheck.needs_binding(text), text
    for text in ("Да, клиент может отключить уведомления в настройках профиля.", "Срок — 14 календарных дней",
                 "Нет ограничения по сумме перевода внутри банка для своих счетов", ""):
        assert not recheck.needs_binding(text), text
