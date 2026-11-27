"""№26, v2.1: судья — правила кода, проверенные повтором живых ответов sonnet и haiku. Без сети."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, cand, finding, response  # noqa: E402

REQS = [{"id": "R-01", "kind": "goal", "line_start": 23, "line_end": 23, "text": "Цель"},
        {"id": "R-06", "kind": "functional", "line_start": 38, "line_end": 38, "text": "Ф"},
        {"id": "R-10", "kind": "nonfunctional", "line_start": 46, "line_end": 46, "text": "НФТ"}]


def _cands(goal_kind: str):
    return [
        cand("C-001", 46, "Сервис передаёт сообщение на отправку в течение минуты", kind="unverifiable",
             criterion="verifiable", severity="major", reqs=("R-10",), source="lens:qa"),
        cand("C-002", 23, "узнать о событии в момент операции", kind=goal_kind, criterion="set_consistent",
             severity="minor", reqs=("R-01", "R-10"), source="consistency",
             extra=[(46, "Сервис передаёт сообщение на отправку в течение минуты")]),
        cand("C-003", 38, "Месяц определяется по дате совершения", kind="ambiguity", reqs=("R-06",)),
    ]


def _resp(goal_kind: str):
    return response([finding("F01", ["C-001"], kind="unverifiable", criterion="verifiable", reqs=("R-10",),
                             title="Срок «в течение минуты» без доли событий"),
                     finding("F02", ["C-002"], kind=goal_kind, criterion="set_consistent", severity="minor",
                             reqs=("R-01", "R-10"), title="Цель «в момент операции» расходится со сроком в минуту"),
                     finding("F03", ["C-003"], reqs=("R-06",))],
                    checklist=[{"n": 1, "answer": "Частично", "comment": "Срок: F02.", "finding_keys": ["F02"]}],
                    summary="Можно начинать с условиями: F01, F02.")


def test_goal_mismatch_minor_becomes_place_of_requirement_finding():
    """Minor «цель ↔ требование» по требованию, которое уже разбирает другой дефект, — место этого дефекта."""
    res = judge.run(Ctx(FakeLLM(_resp("other")), requirements=REQS), _cands("other"))
    all_placed(res, ["C-001", "C-002", "C-003"])
    host = next(f for f in res["findings"] if "C-001" in f["candidate_ids"])
    assert host["candidate_ids"] == ["C-001", "C-002"]
    assert {e["line_start"] for e in host["evidence"]} == {23, 46}
    off = judge.run(Ctx(FakeLLM(_resp("other")), requirements=REQS,
                        options={"judge_check": False, "judge_absorb_goal": False}), _cands("other"))
    assert host["severity"] == next(f for f in off["findings"] if f["candidate_ids"] == ["C-001"])["severity"]
    assert "кроме того, цель «в момент операции» расходится со сроком в минуту (строка 23)" in host["problem"]
    assert len(res["findings"]) == 2
    assert res["checklist"][0]["finding_ids"] == [host["id"]]  # ссылка на поглощённый — к хозяину
    assert any("расхождение с целью" in w for w in res["warnings"])


def test_requirement_property_with_goal_quote_stays_separate():
    """Свойство самого требования (непроверяемо), процитированное вместе с целью, — отдельная находка."""
    res = judge.run(Ctx(FakeLLM(_resp("unverifiable")), requirements=REQS), _cands("unverifiable"))
    assert len(res["findings"]) == 3


def test_goal_rule_off_switch():
    res = judge.run(Ctx(FakeLLM(_resp("other")), requirements=REQS,
                        options={"judge_check": False, "judge_absorb_goal": False}), _cands("other"))
    assert len(res["findings"]) == 3


def test_default_owner_question_only_when_nothing_given():
    """Нет ни формулировки, ни вопроса — у повторяющихся типов (покрытие приёмки, термин, заглушка, откат)
    появляется конкретный вопрос владельцу; данный кандидатом вопрос не заменяется."""
    cs = [cand("C-001", 63, "Исходные условия | Действие | Ожидаемый результат", kind="incomplete",
               severity="minor", title="Критерии приёмки покрывают малую часть требований"),
          cand("C-002", 90, "Удобный интерфейс", kind="ambiguity")]
    cs[1]["question"] = "Что считать удобным?"
    resp = response([finding("F01", ["C-001"], kind="incomplete", severity="minor",
                             title="Критерии приёмки покрывают малую часть требований"),
                     finding("F02", ["C-002"], title="Размытое «удобный интерфейс»")])
    res = judge.run(Ctx(FakeLLM(resp)), cs)
    q1 = next(f for f in res["findings"] if f["candidate_ids"] == ["C-001"])["question"]
    q2 = next(f for f in res["findings"] if f["candidate_ids"] == ["C-002"])["question"]
    assert q1.startswith("Какие случаи") and "критерии приёмки" in q1
    assert q2 == "Что считать удобным?"
    assert judge._default_question({"title": "Нет схемы отката", "kind": "missing_element"}).startswith("Как выключить")
    assert judge._default_question({"title": "Что-то", "kind": "ambiguity"}) == ""
    assert judge._default_question({"title": "Термины", "kind": "terminology", "rewrite": "Готово"}) == ""
