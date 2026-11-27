"""Регрессии пересмотра на двух независимых основаниях: ответ владельца и строка ТЗ."""
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
    from pathlib import Path
    import json

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
