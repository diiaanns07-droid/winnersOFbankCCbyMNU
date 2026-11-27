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


def test_questions_from_another_revision_cannot_be_answered_by_number_alone():
    from test_11_clarify import FakeCtx, FakeLLM

    questions = [{"id": "Q-01", "topic": "Выбор канала", "question": "Где показать уведомление?",
                  "options": ["Личный кабинет", "Экран карты"], "finding_ids": []}]
    report = {"document": {"file": "spec.md", "sha256": "a" * 64}, "questions": questions, "findings": []}
    changed = "> Документ: spec.md, SHA-256 " + "b" * 64 + "\nQ-01: B"
    result = recheck.apply_answers(FakeCtx(FakeLLM({})), report, changed)["clarification"]
    assert result["answers"] == [] and result["decisions"] == []
    assert result["answers_document"]["match"] is False
    assert result["needs_confirmation"][0]["text"] == "B"
    stale_text = changed.replace("Q-01: B", "Q-01 [Складская логистика]: Груз складируем на терминале.")
    unbound = recheck.apply_answers(FakeCtx(FakeLLM({})), report, stale_text)["clarification"]
    assert unbound["decisions"] == [] and unbound["needs_confirmation"][0]["topic"] == "Складская логистика"
    by_topic = changed.replace("Q-01: B", "Q-05 [Выбор канала]: Личный кабинет.")
    linked = recheck.apply_answers(FakeCtx(FakeLLM({})), report, by_topic)["clarification"]
    assert linked["answers"][0]["question_id"] == "Q-01"
    same = changed.replace("b" * 64, "a" * 64)
    matched = recheck.apply_answers(FakeCtx(FakeLLM({})), report, same)["clarification"]
    assert matched["answers_document"]["match"] is True
    assert matched["answers"][0]["answer"] == "Экран карты"


def test_distinct_units_in_orphan_replies_do_not_create_a_conflict():
    def replies(left, right):
        return {("Q-19", "Порядок возврата"): [
            {"label": "Решение-1", "topic": "Порядок возврата", "text": left},
            {"label": "Решение-2", "topic": "Порядок возврата", "text": right},
        ]}
    assert recheck.decision_clashes(replies("Возвращаем 200 тенге.", "Срок возврата 48 часов.")) == []
    assert recheck.decision_clashes(replies("Возвращаем 200 тенге.", "Возвращаем 350 тенге."))
    assert recheck.decision_clashes(replies("Возвращаем 423 при блокировке.", "Возвращаем 409 при блокировке."))


def test_html_and_console_count_open_blockers_after_answers():
    from bcc_review.v2.render import console, html

    demo = Path(__file__).resolve().parents[2] / "reports/demo_answers/qr"
    answered = json.loads((demo / "qr.json").read_text(encoding="utf-8"))
    rendered = html.render_html(answered)
    assert "критичных 0, существенных 1, незначительных 8" in rendered.split("</head>", 1)[0]
    hero = rendered.split('<section class="hero"', 1)[1].split("</section>", 1)[0]
    assert "Предварительная оценка по ответам владельца" in hero
    assert 'class="tnum">0</span>' in hero
    assert "Предварительная оценка по ответам владельца" in console.summary(answered)
    answered["clarification"]["needs_confirmation"] = [{"question_id": "Q-08", "topic": "Продление",
                                                        "text": "На один месяц", "possible_questions": ["Q-01", "Q-02"]}]
    pending = html.render_html(answered).split("Подтвердить привязку ответов", 1)[1]
    assert "На один месяц" in pending and "Q-01, Q-02" in pending
    reread = json.loads((demo / "qr.revised.review.json").read_text(encoding="utf-8"))
    assert "Предварительная оценка по ответам владельца" not in html.render_html(reread)
