"""№32: качество вопросов — без почти одинаковых, каждый блокирующий critical в вопросе, не больше 8.

Мера сходства (`clarify.question_similarity`) и пороги подобраны на 20 сохранённых отчётах (762 пары вопросов):
ни одна пара разных вопросов не сливается; замер — `tests/v2/fixtures/32_questions/measure.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import clarify  # noqa: E402
from test_11_clarify import load_view  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "32_questions"

TTL_A = {"topic": "Срок действия QR-кода без суммы",
         "question": "Сколько действует QR-код без суммы: 15 минут с создания, как в требовании, или до конца "
                     "календарного дня, как в правилах метода?"}
TTL_B = {"topic": "Время жизни QR-кода без суммы",
         "question": "Сколько действует QR-код без суммы — 15 минут или до конца дня?"}
OTHER = {"topic": "Лимит числа оплат QR-кода без суммы",
         "question": "Сколько раз можно оплатить один QR-код без суммы до его отмены?"}


def _f(fid, sev="major", blocks="both", kind="contradiction"):
    return {"id": fid, "severity": sev, "blocks": blocks, "kind": kind, "title": fid, "evidence": []}


def _q(base, ids, blocking=False):
    return dict(base, finding_ids=list(ids), blocking=blocking, options=["Первый вариант", "Второй вариант"])


def test_similarity_measure():
    text, shared = clarify.question_similarity(_q(TTL_A, ["D-01"]), _q(TTL_B, ["D-01", "D-02"]))
    assert 0.5 <= text < 0.6 and shared == 1.0
    assert clarify.is_similar(_q(TTL_A, ["D-01"]), _q(TTL_B, ["D-01"]))  # перефразировка с тем же дефектом
    assert not clarify.is_similar(_q(TTL_A, ["D-01"]), _q(TTL_B, ["D-05"]))  # без общих дефектов — порог 0,6
    assert not clarify.is_similar(_q(TTL_A, ["D-01"]), _q(OTHER, ["D-01"]))  # тот же дефект, другое решение
    # числа различают вопросы, короткие тексты — только полное совпадение
    assert not clarify.is_similar({"topic": "Тема 3", "question": "Вопрос 3?"}, {"topic": "Тема 4", "question": "Вопрос 4?"})
    same = {"topic": "Код ответа", "question": "Какой код вернуть при отказе антифрода в методе перевода?"}
    assert clarify.is_similar(dict(same), dict(same))


def test_merge_keeps_first_and_unions_findings():
    by_id = {"D-01": _f("D-01"), "D-02": _f("D-02", "critical"), "D-03": _f("D-03")}
    w: list[str] = []
    out = clarify.merge_similar([_q(TTL_A, ["D-01"]), _q(OTHER, ["D-03"]), _q(TTL_B, ["D-01", "D-02"])], by_id, w)
    assert [q["topic"] for q in out] == [TTL_A["topic"], OTHER["topic"]]
    assert out[0]["finding_ids"] == ["D-01", "D-02"] and out[0]["blocking"] is True  # critical слитого не потерян
    assert len(w) == 1 and "слит с похожим" in w[0]


def test_cap_keeps_question_of_uncovered_critical():
    findings = [_f(f"D-{i:02d}") for i in range(1, 12)] + [_f("D-20", "critical")]
    qs = [_q({"topic": f"Тема номер {i}", "question": f"Какое значение {i} нужно для дефекта {i}?"}, [f"D-{i:02d}"])
          for i in range(1, 12)]
    qs.append(_q({"topic": "Последний", "question": "Как решить критичное расхождение в последнем пункте?"},
                 ["D-20"], blocking=True))
    w: list[str] = []
    out = clarify.cap_questions(qs, findings, w)
    assert len(out) == clarify.MAX_QUESTIONS
    assert any("D-20" in q["finding_ids"] for q in out)
    assert [q["topic"] for q in out[:7]] == [f"Тема номер {i}" for i in range(1, 8)]  # порядок важности сохранён
    assert w and w[0].startswith("clarify: оставлено 8 вопросов из 12")


def test_cap_reports_critical_left_without_question():
    findings = [_f(f"D-{i:02d}", "critical") for i in range(1, 11)]
    qs = [_q({"topic": f"Тема номер {i}", "question": f"Какое значение {i} верно для пункта {i}?"}, [f"D-{i:02d}"],
             blocking=True) for i in range(1, 11)]
    w: list[str] = []
    out = clarify.cap_questions(qs, findings, w)
    assert len(out) == 8 and "без вопроса остались критичные D-09, D-10" in w[0]


def test_postprocess_merges_paraphrase(monkeypatch):
    findings = [dict(_f("D-01", "critical"), evidence=[{"quote": "Возврат уменьшает расходы", "line_start": 38,
                                                        "line_end": 38, "verified": "exact"}]),
                dict(_f("D-02"), evidence=[{"quote": "Возврат уменьшает расходы", "line_start": 38, "line_end": 38,
                                            "verified": "exact"}])]
    ev = [{"quote": "Возврат уменьшает расходы", "line": 38}]
    raw = {"questions": [dict(_q(TTL_A, ["D-01"], True), to="Аналитик", why="…", evidence=ev),
                         dict(_q(TTL_B, ["D-01", "D-02"]), to="Аналитик", why="…", evidence=ev)]}
    w: list[str] = []
    qs = clarify.postprocess(raw, findings, load_view(), w)
    assert len(qs) == 1 and qs[0]["finding_ids"] == ["D-01", "D-02"] and qs[0]["id"] == "Q-01"
    assert any("слит с похожим" in x for x in w)


def test_measure_on_saved_reports():
    sys.path.insert(0, str(FIX))
    import measure  # noqa: E402

    res = measure.main()
    assert res["reports"] >= 20
    assert res["after"]["similar_pairs"] == 0 and res["after"]["over_cap"] == 0
    assert res["after"]["critical_without"] <= res["before"]["critical_without"]
    assert res["after"]["no_if_no_answer"] == 0
