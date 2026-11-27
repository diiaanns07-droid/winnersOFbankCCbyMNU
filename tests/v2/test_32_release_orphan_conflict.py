"""№32, исправление в релиз: спорящие реплики двух адресатов на вопрос, которого нет в новом прогоне.

Полный прогон с ``--answers`` перегенерирует вопросы; если темы вопроса в новом прогоне нет, обе реплики («423» у
одного адресата, «409» у другого) уходили в общие решения порознь — и ``--revise`` вносил ОБЕ в исправленную
редакцию отдельными новыми требованиями («[добавлено: Решение-1]», «[добавлено: Решение-2]»): документ с двумя
противоречащими кодами. Живой случай — ТЗ перевода по QR, sonnet, 27.11 17:05 (вопрос «отказ антифрода»: 422 ↔ 403).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import recheck, revise  # noqa: E402
from test_11_clarify import FakeCtx, FakeLLM  # noqa: E402

QS = [{"id": "Q-01", "topic": "Срок хранения журнала", "question": "Сколько хранить журнал?",
       "options": ["1 год", "5 лет"], "finding_ids": ["D-01"]}]
FINDINGS = [{"id": "D-01", "severity": "major", "kind": "incompleteness", "title": "Срок хранения журнала не задан",
             "blocks": "development", "priority": 1, "evidence": [], "problem": "…", "scenario": "…"},
            {"id": "D-02", "severity": "major", "kind": "incompleteness", "title": "Не задан код ответа при блокировке счёта",
             "blocks": "development", "priority": 2, "evidence": [], "scenario": "…",
             "problem": "При блокировке счёта код ответа не указан, клиент не знает, создана ли операция."}]
CLASH = ("Q-07 [Код ответа при блокировке счёта]: Команда безопасности: при блокировке возвращаем 423, операцию не создаём.\n"
         "Q-07 [Код ответа при блокировке счёта]: Владелец API: при блокировке возвращаем 409, операцию не создаём.\n")


def _report():
    return {"findings": FINDINGS, "questions": QS, "verdict": {}, "run": {"status": "complete"}}


def _resp(decisions):
    return {"decisions": [dict({"severity": "major", "title": "", "problem": "", "by": [], "conflicting_answers": [],
                                "reason": "", "status": "open"}, **d) for d in decisions], "candidates": []}


def test_conflicting_orphan_replies_not_written_into_revision():
    clar = recheck.apply_answers(FakeCtx(FakeLLM(_resp([]))), _report(), CLASH)["clarification"]
    assert len(clar["decisions"]) == 2
    conf = [c for c in clar["answer_conflicts"] if not c["finding_id"]]
    assert len(conf) == 1 and conf[0]["answers"] == ["Решение-1", "Решение-2"] and conf[0]["question_id"] == "Q-07"
    assert revise.decision_targets(clar) == []  # было: оба решения — отдельные правки редакции
    assert any("расходятся в значениях" in w for w in clar["warnings"])
    md = recheck.render_markdown(clar)
    assert "Q-07 [Код ответа при блокировке счёта]" in md and "423" in md and "409" in md


def test_finding_closed_by_one_side_stays_open():
    resp = _resp([{"finding_id": "D-02", "status": "resolved", "by": ["Решение-1"], "reason": "снят решением"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), CLASH)["clarification"]
    ch = next(c for c in clar["changes"] if c["finding_id"] == "D-02")
    assert ch["status"] == "open" and set(ch["answer_conflict"]) == {"Решение-1", "Решение-2"}


def test_complementary_replies_still_written():
    text = ("Q-07 [Срок хранения ключа запроса]: Ключ храним 48 часов с первого запроса.\n"
            "Q-07 [Срок хранения ключа запроса]: Да, 48 часов; после изменения суммы под тем же ключом — 409.\n")
    clar = recheck.apply_answers(FakeCtx(FakeLLM(_resp([]))), _report(), text)["clarification"]
    assert not clar["answer_conflicts"]
    assert [t["id"] for t in revise.decision_targets(clar)] == ["Решение-1", "Решение-2"]
