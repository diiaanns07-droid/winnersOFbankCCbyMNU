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


def test_competitors_adapter_keeps_active_and_maps_fields():
    from evaluation.v2 import competitors as cp

    gold = {"sha256": "x"}
    era = {"findings": [{"status": "open", "severity": "critical", "title": "Т", "problem": "П",
                         "evidence": [{"quote": "q", "line_start": 38, "line_end": 38}]}],
           "verdict": {"ready_for_development": False, "ready_for_testing": False}}
    rep = cp.adapt("ERA216", era, gold)
    assert len(rep["findings"]) == 1 and rep["findings"][0]["severity"] == "critical"
    assert rep["verdict"] == {"development": "no", "testing": "no"}
    solo = {"findings": [{"status": "active", "severity": "MAJOR", "title": "А", "explanation": "Е",
                          "evidence": [{"quote": "q", "line": 16}]},
                         {"status": "merged", "severity": "MAJOR", "title": "Б", "evidence": [{"quote": "q", "line": 1}]}],
            "verdict": {"dev_status": "no", "test_status": "no"}}
    rep = cp.adapt("SoloHive", solo, gold)
    assert [f["title"] for f in rep["findings"]] == ["А"]
    assert rep["findings"][0]["severity"] == "major" and rep["findings"][0]["evidence"][0]["line_start"] == 16
    azk = {"findings": [{"status": "rejected", "severity": "major", "title": "X", "evidence": []},
                        {"status": "confirmed", "severity": "minor", "title": "Y", "defect_type": "ambiguous",
                         "evidence": [{"quote": "q", "line_start": 2, "line_end": 2}]}],
           "verdict": {"development": "not_ready", "testing": "not_ready"}}
    rep = cp.adapt("azekowka", azk, gold)
    assert [f["kind"] for f in rep["findings"]] == ["ambiguity"] and rep["verdict"]["testing"] == "no"


def test_cleantable_latest_and_p1_rule():
    from evaluation.v2 import cleantable as ct

    old = ct._row("чистые ТЗ №20", "haiku", "старый", "2026-11-27 09:00", "fx", {"critical": 2, "major": 9}, {"development": "no"})
    new_ok = ct._row("чистые ТЗ №20", "haiku", "новый", "2026-11-27 13:00", "fx", {"critical": 0, "major": 2, "minor": 5},
                     {"development": "conditional", "testing": "conditional"})
    new_bad = ct._row("чистые ТЗ №20", "haiku", "новый", "2026-11-27 13:00", "qr_v2", {"critical": 0, "major": 4},
                      {"development": "conditional", "testing": "conditional"})
    groups = ct.latest([old, new_ok, new_bad])
    assert [r["case"] for r in groups[("чистые ТЗ №20", "haiku")]] == ["fx", "qr_v2"]
    text = ct.render(groups)
    assert "| чистые ТЗ №20 | haiku | новый" in text and "❌" in text  # qr_v2: major 4 > 3
    assert "qr_v2 ❗" in text and "| fx |" in text


def test_corpus_gates_clean_only_run_takes_f1_from_run_with_defects():
    """Прогон корпуса только по чистым (support = 0) не даёт F1 = 0: recall и F1 — из последнего прогона с дефектами."""
    clean_only = {"label": "чистые 13:00", "at": "2026-11-27 13:00",
                  "harness": {"recall": 0.0, "tp": 0, "support": 0, "f1": 0.0, "precision": 0.0},
                  "clean": {"n": 8, "measured": 8, "critical": 0, "docs_with_critical": 0, "docs_over_1_finding": 0,
                            "max_findings": 1, "verdict_no": 0},
                  "details": {"fp": []}, "per_issue_type": {}, "failed": 0, "cases": 8}
    full = {"label": "полный 08:30", "at": "2026-11-27 08:30",
            "harness": {"recall": 0.9, "tp": 9, "support": 10, "f1": 0.8, "precision": 0.7},
            "clean": clean_only["clean"], "details": {"fp": []}, "per_issue_type": {}, "failed": 0, "cases": 33}
    ch = {c["name"].split(": ")[1]: c for c in gate.corpus_gates("Корпус", clean_only, gate.CORPUS, "№15", full)}
    assert ch["F1 (строгий)"]["ok"] is True and ch["F1 (строгий)"]["source"].startswith("полный 08:30")
    assert ch["critical на чистых"]["source"].startswith("чистые 13:00")
    alone = {c["name"].split(": ")[1]: c for c in gate.corpus_gates("Корпус", clean_only, gate.CORPUS, "№15")}
    assert alone["F1 (строгий)"]["ok"] is None  # ⏳, а не ❌ F1 = 0


def test_cleantable_external_rows_from_status(tmp_path):
    import json as _json

    from evaluation.v2 import cleantable as ct

    p = tmp_path / "ext.json"
    p.write_text(_json.dumps([{"set": "№18: чистые версии (2-я редакция)", "model": "sonnet", "label": "№19 (статус)",
                               "at": "2026-11-27 12:05", "rows": [
                                   {"case": "qr_clean", "critical": 0, "major": 2, "minor": 12,
                                    "verdict": {"development": "yes", "testing": "yes"}}]}]), encoding="utf-8")
    rows = ct._external_rows(p)
    assert rows[0]["case"] == "qr_clean" and rows[0]["major"] == 2 and rows[0]["model"] == "sonnet"
    assert "| qr_clean | №18: чистые версии (2-я редакция) | sonnet | 0 | 2 | 12 | можно / можно |" in ct.render(ct.latest(rows))
    assert ct._external_rows(tmp_path / "нет.json") == []


def test_cleantable_verdict_table():
    from evaluation.v2 import cleantable as ct

    rows = [ct._row("чистые ТЗ №20", "haiku", "р", "2026-11-27 15:00", c, {"critical": cr}, {"development": v, "testing": v})
            for c, cr, v in (("fx", 1, "no"), ("qr_v2", 0, "conditional"), ("roundup", 0, "yes"))]
    text = ct.render_verdicts(ct.latest(rows))
    assert "| чистые ТЗ №20 | haiku | р (15:00) | 1 | 1 | 1 из 3 | 1 | fx |" in text


def test_newtz_set_separates_clean20_from_open2():
    assert gate._newtz_set({"rows": [{"doc": "evaluation/v2/clean/fx/source.md"}]}) == "№20"
    assert gate._newtz_set({"rows": [{"doc": "C:\\repo\\evaluation\\v2\\clean\\fx\\source.md"}]}) == "№20"
    assert gate._newtz_set({"rows": [{"doc": "evaluation/v2/open2/qr_clean/source.md"}]}) == "open2"
    assert gate._newtz_set({"rows": []}) == "open2"
