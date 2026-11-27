"""Ворота третьей волны (WAVE3.md) в `evaluation.v2.gate`: новые и чистые ТЗ, разброс, понятность. Без сети."""
from __future__ import annotations

from evaluation.v2 import gate


def _newtz(**kw):
    d = {"label": "проба", "at": "2026-11-27 13:00",
         "harness": {"tp": 18, "fn": 2, "support": 20, "recall": 0.9, "fp": 2},
         "clean": {"n": 4, "critical": 0, "docs_with_critical": 0, "major": 5, "verdict_no": 0},
         "details": {"fp": [{"clean": True, "severity": "major", "case_id": "a_clean", "owners": ["№05"]}] * 4
                     + [{"clean": True, "severity": "major", "case_id": "b_clean", "owners": ["№08"]}]},
         "per_issue_type": {}}
    d.update(kw)
    return d


def test_newtz_gates_recall_precision_and_clean_rules():
    ch = {c["name"].split(": ")[1]: c for c in gate.newtz_gates("Новые ТЗ", _newtz(), gate.NEWTZ, "№15")}
    assert ch["recall"]["ok"] is True and ch["precision"]["ok"] is True  # 18 / (18 + 2) = 90 %
    assert ch["critical на чистых"]["ok"] is True and ch["вердикт «нельзя» на чистых"]["ok"] is True
    major = ch["major на чистом ≤ 3"]
    assert major["ok"] is False and major["owners"].startswith("a_clean 4")


def test_newtz_gates_precision_red_and_clean_critical():
    d = _newtz(harness={"tp": 10, "fn": 10, "support": 20, "recall": 0.5, "fp": 10},
               clean={"n": 4, "critical": 2, "docs_with_critical": 1, "major": 0, "verdict_no": 1},
               details={"fp": [{"clean": True, "severity": "critical", "case_id": "a_clean", "owners": ["№09"]}] * 2})
    ch = {c["name"].split(": ")[1]: c for c in gate.newtz_gates("Новые ТЗ", d, gate.NEWTZ, "№15")}
    assert ch["recall"]["ok"] is False and ch["precision"]["ok"] is False
    assert ch["critical на чистых"]["ok"] is False and "№09" in ch["critical на чистых"]["owners"]
    assert ch["вердикт «нельзя» на чистых"]["ok"] is False


def test_newtz_gates_no_run_is_waiting():
    (c,) = gate.newtz_gates("Чистые ТЗ №20, haiku", None, gate.NEWTZ, "№20, №15")
    assert c["ok"] is None and "нет замера" in c["fact"]


def test_wave3_targets():
    assert gate.OFFICIAL["sonnet"]["K_crit"] == 5 and gate.OFFICIAL["sonnet"]["minutes"] == 3
    assert gate.OFFICIAL["gemini"]["minutes"] == 4 and gate.OFFICIAL["gemini"]["calls"] == 10
    assert gate.CORPUS["f1"] == 0.75 and gate.NEWTZ["precision"] == 0.85 and gate.STABILITY_SPREAD == 0.20


def test_clarity_gate_reads_score(monkeypatch):
    score = {"clarity": {"n": 10, "passed": 8, "worst": [{"id": "D-03", "source": "lens:qa", "fails": ["заголовок"]}]}}
    monkeypatch.setattr(gate, "_score_for", lambda row: score)
    (c,) = gate.clarity_gates({"label": "x", "at": "2026-11-27 13:00"})
    assert c["ok"] is False and "80 %" in c["fact"] and "D-03" in c["owners"]
    score["clarity"]["passed"] = 10
    assert gate.clarity_gates({"label": "x", "at": "2026-11-27 13:00"})[0]["ok"] is True


def test_clarity_rubric_rows():
    from evaluation.v2 import score as sc

    good = {"id": "D-01", "title": "Критерий приёмки №2 относит покупку к другому месяцу", "kind": "event_conflict",
            "severity": "critical", "evidence": [{"quote": "q", "line_start": 38}],
            "problem": "Правило относит покупку к месяцу совершения. Критерий — к месяцу проведения.",
            "scenario": "Покупка 31 января в 23:58, проведена 1 февраля: по правилу январь, по критерию февраль.",
            "impact": "Тест по критерию упадёт на верном коде.", "rewrite": "Было: … Стало: …", "question": "",
            "recommendation": "Исправить критерий.", "sources": ["lens:qa"]}
    assert sc.clarity_row(good, set())["fails"] == []
    bad = {**good, "id": "D-02", "title": " ".join(["слово"] * 13), "scenario": "Без чисел", "rewrite": "",
           "problem": "Раз. Два. Три.", "impact": "", "evidence": [{"quote": "q"}],
           "recommendation": "Кандидат C-007 от lens:qa"}
    assert set(sc.clarity_row(bad, set())["fails"]) == {"заголовок", "место", "проблема", "сценарий", "последствие",
                                                        "исправление", "язык"}
    missing = {**good, "id": "D-03", "kind": "missing_element", "scenario": "Приложение открывает экран без значения."}
    assert sc.clarity_row(missing, set())["fails"] == []  # «обещано, но не описано» — сценарий без чисел допустим
    ref = {**good, "id": "D-04", "recommendation": "Добавить тест-кейсы T-01–T-05 и вопрос Q-02 из отчёта."}
    assert sc.clarity_row(ref, set())["fails"] == []  # ссылки на D-/Q-/T- отчёта — не внутренние коды
    res = sc.clarity_of([{**good, "raw": good}, {**bad, "raw": bad}], set())
    assert res["n"] == 2 and res["passed"] == 1 and res["worst"][0]["id"] == "D-02"
