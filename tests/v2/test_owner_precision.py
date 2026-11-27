"""Регрессии пересмотра на двух независимых основаниях: ответ владельца и строка ТЗ."""
import json
from pathlib import Path
from types import SimpleNamespace

from bcc_review.v2.stages import judge, recheck


def test_same_lines_can_describe_unrelated_changes():
    old = {"id": "D-12", "title": "Не задан срок действия согласия", "problem": "Когда истекает согласие?",
           "evidence": [{"line_start": 12, "quote": "Согласие хранится до отзыва."},
                        {"line_start": 18, "quote": "Для нового согласия нужна подпись."}]}
    other = [{"line_start": 12, "quote": "Уведомления доступны только в кабинете."},
             {"line_start": 19, "quote": "Оператор печатает квитанцию."}]
    assert recheck.duplicate_of(other, [old], "Ответ меняет канал уведомлений") == ""
    assert recheck.duplicate_of(old["evidence"], [old], old["title"]) == "D-12"


def test_judge_receives_complete_owner_decision_separately_from_tz(monkeypatch):
    proposal = "Уточнение по расписанию. " * 22 + "По выходным расчёт остаётся ручным."
    recorded = []

    def ask(ctx, system, user, schema):
        recorded.append((system, user))
        return {}

    monkeypatch.setattr(judge, "_ask", ask)
    source = {"id": "C-101", "source": "recheck", "title": "Разное правило расчёта",
              "evidence": [{"line_start": 9, "quote": "Ежедневный расчёт автоматический.", "verified": "exact"}],
              "answer_refs": [{"id": "Q-04", "text": proposal}]}
    judge._call_judge(SimpleNamespace(), [recheck.for_judge(source)], [["C-101"]], "", [])
    system, user = recorded.pop()
    assert "ответ владельца" in system.lower()
    assert proposal in user and "Q-04" in user and "C-101" in user
    assert proposal not in system
    judge._call_judge(SimpleNamespace(), [{**source, "source": "lens:analyst"}], [["C-101"]], "", [])
    ordinary_system, ordinary_user = recorded.pop()
    assert ordinary_system == ""
    assert proposal not in ordinary_user


def test_answered_report_distinguishes_revision_from_an_independent_read():
    from bcc_review.v2.render import markdown

    demo = Path(__file__).resolve().parents[2] / "reports/demo_answers/qr"
    answered = json.loads((demo / "qr.json").read_text(encoding="utf-8"))
    reread = json.loads((demo / "qr.revised.review.json").read_text(encoding="utf-8"))
    first = markdown.render(answered).split("**Почему.", 1)[0]
    assert "Предварительная оценка по ответам владельца" in first
    assert "отдельная проверка исправленного текста" in first
    blocker_line = next(line for line in markdown.render(answered).splitlines() if line.startswith("- 🔴") and "D-01" in line)
    assert "Q-01" in blocker_line and "стр. 54" in blocker_line and "Приложения" in blocker_line
    assert "Предварительная оценка по ответам владельца" not in markdown.render(reread)


def test_same_topic_in_two_questions_waits_for_an_owner_choice():
    questions = [
        {"id": "Q-01", "topic": "Срок действия согласия", "question": "Каков срок в первом канале?",
         "options": ["Тридцать дней", "Девяносто дней"], "finding_ids": ["D-01"]},
        {"id": "Q-02", "topic": "Срок действия согласия", "question": "Каков срок во втором канале?",
         "options": ["Один год", "Пять лет"], "finding_ids": ["D-02"]},
    ]
    for answer in ["Q-01 [Срок действия согласия]: B",
                   "Q-08 [Срок действия согласия]: Срок действия согласия 42 дня"]:
        resolved = recheck.resolve_answers(questions, recheck.parse_answers_text(answer))
        assert resolved["answered"] == [] and resolved["decisions"] == []
        waiting, = resolved["needs_confirmation"]
        assert waiting["possible_questions"] == ["Q-01", "Q-02"]
        assert waiting["text"] and resolved["unanswered"] == ["Q-01", "Q-02"]


def test_letter_on_missing_topic_is_not_applied_to_a_reused_number():
    questions = [{"id": "Q-01", "topic": "Выбор склада", "question": "Где хранить архив?",
                  "options": ["Городской склад", "Областной склад"]}]
    resolved = recheck.resolve_answers(questions, recheck.parse_answers_text("Q-01 [Начисление баллов]: B"))
    assert resolved["answered"] == [] and resolved["decisions"] == []
    assert resolved["needs_confirmation"][0]["text"] == "B"
    control = recheck.resolve_answers(questions, recheck.parse_answers_text("Q-01: B"))
    assert control["answered"][0]["answer"] == "Областной склад"
