"""№32: спорящие реплики двух адресатов на вопрос, которого нет в новом прогоне.

Живой прогон на ТЗ с переводом по QR (27.11, sonnet): полный прогон с ``--answers`` перегенерировал вопросы, темы
«код при отказе» в нём не оказалось — обе реплики адресатов (одно значение у одного, другое у другого) ушли в общие
решения порознь. Конфликт кодом не ловился: в ``answer_conflicts`` и в файле следующего круга его не было, а
редакция могла вписать одно из значений (на живом прогоне модель случайно поставила маркер сама).
Проверки — на синтетических вопросах и ответах, без файлов экзамена.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import recheck, revise  # noqa: E402
from test_11_clarify import FakeCtx, FakeLLM  # noqa: E402

# новый прогон: под номером Q-01 — другой вопрос, вопроса о коде блокировки нет совсем
QS = [
    {"id": "Q-01", "topic": "Срок хранения журнала", "question": "Сколько хранить журнал?",
     "options": ["1 год", "5 лет"], "finding_ids": ["D-01"]},
    {"id": "Q-02", "topic": "Часовой пояс конца дня", "question": "По какому времени считать конец дня?",
     "options": ["UTC", "Время Астаны"], "finding_ids": ["D-02"]},
]
FINDINGS = [{"id": f"D-0{i}", "severity": "major", "kind": "incompleteness", "title": f"Дефект {i}",
             "blocks": "development", "priority": i, "evidence": [], "problem": "…", "scenario": "…"}
            for i in (1, 2)] + [
    {"id": "D-03", "severity": "major", "kind": "incompleteness", "title": "Не задан код ответа при блокировке счёта",
     "blocks": "development", "priority": 3, "evidence": [], "scenario": "…",
     "problem": "При блокировке счёта код ответа не указан, клиент не знает, создана ли операция."}]
CLASH = ("Q-07 [Код ответа при блокировке счёта]: Команда безопасности: при блокировке возвращаем 423, операцию не создаём.\n"
         "Q-07 [Код ответа при блокировке счёта]: Владелец API: при блокировке возвращаем 409, операцию не создаём.\n")
EXTEND = ("Q-07 [Срок хранения ключа запроса]: Ключ храним 48 часов с первого запроса.\n"
          "Q-07 [Срок хранения ключа запроса]: Да, 48 часов; после изменения суммы под тем же ключом — 409.\n")


def _report():
    return {"findings": FINDINGS, "questions": QS, "verdict": {}, "run": {"status": "complete"},
            "document": {"file": "tz.md", "sha256": "ab" * 32}}


def _resp(decisions):
    return {"decisions": [dict({"severity": "major", "title": "", "problem": "", "by": [], "conflicting_answers": [],
                                "reason": "", "status": "open"}, **d) for d in decisions], "candidates": []}


def test_orphan_replies_with_different_values_are_conflict():
    w: list[str] = []
    res = recheck.resolve_answers(QS, recheck.parse_answers_text(CLASH), w)
    assert res["answered"] == [] and len(res["decisions"]) == 2
    assert res["decision_conflicts"] == [{
        "question_id": "Q-07", "topic": "Код ответа при блокировке счёта", "answers": ["Решение-1", "Решение-2"],
        "texts": {"Решение-1": "Команда безопасности: при блокировке возвращаем 423, операцию не создаём.",
                  "Решение-2": "Владелец API: при блокировке возвращаем 409, операцию не создаём."}}]
    assert any("расходятся в значениях" in x for x in w)


def test_labels_count_owner_decisions_first():
    text = "## Решения\n\n- Журнал хранить 5 лет\n\n" + CLASH
    res = recheck.resolve_answers(QS, recheck.parse_answers_text(text), [])
    assert res["decision_conflicts"][0]["answers"] == ["Решение-2", "Решение-3"]
    assert res["decisions"][0] == "Журнал хранить 5 лет"


def test_complementary_orphan_replies_are_not_conflict():
    res = recheck.resolve_answers(QS, recheck.parse_answers_text(EXTEND), [])
    assert len(res["decisions"]) == 2 and "decision_conflicts" not in res


def test_conflict_reaches_clarification_and_next_round():
    clar = recheck.apply_answers(FakeCtx(FakeLLM(_resp([]))), _report(), CLASH)["clarification"]
    c = [x for x in clar["answer_conflicts"] if not x["finding_id"]]
    assert len(c) == 1 and c[0]["question_id"] == "Q-07" and set(c[0]["texts"]) == {"Решение-1", "Решение-2"}
    nr = [n for n in clar["next_round"] if n["kind"] == "conflict"]
    assert len(nr) == 1 and nr[0]["question_id"] == "Q-07"
    # своя тема реплик, а не тема вопроса с тем же номером в этом прогоне
    assert all(x.startswith("Q-07 [Код ответа при блокировке счёта]: ") for x in nr[0]["lines"])
    text = recheck.render_next_answers(clar, "tz.md", "report.md")
    assert "> Q-07: ответы расходятся, оставьте одну строку" in text  # без пустых скобок дефекта
    assert "## Решения" not in text  # спорящие решения не повторяются как согласованные
    md = recheck.render_markdown(clar)
    assert "Q-07 [Код ответа при блокировке счёта]" in md and "423" in md and "409" in md


def test_model_closing_by_one_side_is_reopened():
    resp = _resp([{"finding_id": "D-03", "status": "resolved", "by": ["Решение-1"], "reason": "снят решением"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), _report(), CLASH)["clarification"]
    ch = next((c for c in clar["changes"] if c["finding_id"] == "D-03"), None)
    assert ch is not None and ch["status"] == "open" and set(ch["answer_conflict"]) == {"Решение-1", "Решение-2"}
    conf = [x for x in clar["answer_conflicts"] if x["finding_id"] == "D-03"]
    assert conf and conf[0]["question_id"] == "Q-07"  # одна запись, обогащённая номером и темой
    assert not [x for x in clar["answer_conflicts"] if not x["finding_id"]]


def test_revision_does_not_pick_a_side():
    clar = recheck.apply_answers(FakeCtx(FakeLLM(_resp([]))), _report(), CLASH)["clarification"]
    assert revise.decision_targets(clar) == []  # ни одна сторона не вносится отдельной правкой
    block, _ = revise._answers_block(clar)
    assert block.count("расходится с другим ответом") == 2 and "<уточнить" in block
    assert set(revise.disputed_values(clar)) == {"423", "409"}
    rw = [{"finding_id": "D-02", "answer_ids": [], "edits": [
        {"action": "replace", "line": 3, "old": "вернуть ошибку", "new": "вернуть код 423"},
        {"action": "replace", "line": 4, "old": "код ошибки", "new": "код <уточнить: 423 или 409>"},
        {"action": "replace", "line": 5, "old": "срок", "new": "срок 30 дней"}]}]
    w: list[str] = []
    out = revise.check_values(rw, clar, ["вернуть ошибку", "код ошибки", "срок 30 дней"], {}, w)
    news = [e["new"] for r in out for e in r["edits"]]
    assert "вернуть код 423" not in news
    assert "код <уточнить: 423 или 409>" in news and "срок 30 дней" in news
    assert any("ответы адресатов расходятся" in x for x in w)


def test_bound_reply_conflict_values_also_guarded():
    # спор адресатов на заданный вопрос (модель назвала конфликт): значение одной стороны в чужой правке — тоже выбор
    qs = QS + [{"id": "Q-03", "topic": "Код ответа при блокировке счёта", "question": "Какой код вернуть?",
                "options": ["423", "409"], "finding_ids": ["D-03"]}]
    text = CLASH.replace("Q-07", "Q-03")
    rep = dict(_report(), questions=qs)
    resp = _resp([{"finding_id": "D-03", "conflicting_answers": ["Q-03"], "reason": "ответы расходятся"}])
    clar = recheck.apply_answers(FakeCtx(FakeLLM(resp)), rep, text)["clarification"]
    assert set(revise.disputed_values(clar)) == {"423", "409"}
    rw = [{"finding_id": "D-01", "answer_ids": [], "edits": [
        {"action": "insert_after", "line": 2, "old": "", "new": "При блокировке возвращается 409."}]}]
    assert revise.check_values(rw, clar, ["а", "б"], {}, []) == []
