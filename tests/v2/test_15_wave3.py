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


def test_latin_allow_standards_bodies_iana():
    """Просьба №13: IANA — имя организации стандартов (как ISO/RFC), не английский текст в отчёте."""
    from evaluation.v2.common import latin_words

    assert latin_words("смещение UTC+5 с идентификатором IANA (база tz)", set()) == []
    assert latin_words("поле note не заполнено", set()) == ["note"]


def test_shell_quote_posix_and_windows(monkeypatch):
    """Просьба №20: на Windows строку команды разбирает cmd.exe — нужны двойные кавычки, не одинарные shlex."""
    from evaluation.v2 import common

    assert common.shell_quote("/tmp/а б/report.md") == "'/tmp/а б/report.md'"
    monkeypatch.setattr(common.os, "name", "nt")
    assert common.shell_quote(r"C:\bcc\новые ТЗ\source.md") == '"C:\\bcc\\новые ТЗ\\source.md"'
    assert common.shell_quote(r"C:\bcc\source.md") == r"C:\bcc\source.md"


def test_run_shell_reads_utf8_output():
    import sys

    from evaluation.v2 import common

    cmd = f"{common.shell_quote(sys.executable)} -c \"import sys; sys.stderr.write('ошибка ₸')\""
    r = common.run_shell(cmd, 60, dict(__import__('os').environ))
    assert r.returncode == 0 and "ошибка ₸" in r.stderr


def test_score_required_keyword_group():
    """Просьба №08: у К4 группа «чтение» обязательна — «нет операции» на общей строке-опоре не засчитывается за К4."""
    import re

    from evaluation.v2 import score as sc

    item = {"_groups": [{52}], "_kw": [re.compile("чтени|получени"), re.compile("нет|не описан"), re.compile("операци")],
            "keywords": {"min": 2, "required": [0]}, "anchors": {"policy": "any"}, "kinds": []}
    other = {"_lines": {52}, "_text": "нет ключа идемпотентности для повторной операции", "_title": ""}
    k4 = {"_lines": {52}, "_text": "нет операции чтения настроек", "_title": ""}
    assert sc.pair_info(item, other)["status"] != "match"
    assert sc.pair_info(item, k4)["status"] == "match"
    item["keywords"].pop("required")
    assert sc.pair_info(item, other)["status"] == "match"  # без required — прежнее поведение


def test_put_results_block_inserts_first_and_replaces(tmp_path):
    from evaluation.v2.common import put_results_block

    p = tmp_path / "R.md"
    p.write_text("# Результаты\n\nшапка\n\n## Старый раздел\n\nтекст\n", encoding="utf-8")
    put_results_block(p, "gate", "итог 1\n", "Итог ворот")
    put_results_block(p, "verdict", "таблица\n", "Вердикт")
    put_results_block(p, "gate", "итог 2\n", "Итог ворот")
    t = p.read_text(encoding="utf-8")
    assert t.index("## Вердикт") < t.index("## Итог ворот") < t.index("## Старый раздел")
    assert "итог 2" in t and "итог 1" not in t and t.count("<!-- gate:start -->") == 1


def test_gate_render_summary_lists_red_with_owners():
    checks = [{"name": "A: С", "target": "≥ 18/20", "fact": "17/20", "ok": False, "owners": "№10 | №05", "source": "з"},
              {"name": "B", "target": "0", "fact": "0", "ok": True, "owners": ""},
              {"name": "C", "target": "есть", "fact": "нет", "ok": None, "owners": "№15"}]
    text = gate.render_summary(checks, "Ворота, 15:30")
    assert "зелёных 1, красных 1, без замера 1" in text and "| A: С | 17/20 (≥ 18/20) | з | №10 / №05 |" in text
    assert "Без замера: C." in text


def test_score_second_chance_for_focused_out_strict_pair():
    """Просьба №07: замечание о С15 (строки 121 и 156) не уходит в дубль С3 — у С15 строгая пара, заголовок о нём."""
    import json as _json

    from evaluation.v2 import score as sc
    from evaluation.v2.common import ROOT

    gold = sc.load_gold(ROOT / "evaluation/v2/official/gold.yaml")
    rep = _json.loads((ROOT / "evaluation/v2/measurements/zamer_13_00_9bd5954_haiku/report.json").read_text(encoding="utf-8"))
    res = sc.score_report(rep, gold, arbiter="off")
    got = {a["gold"]: a["finding"] for a in res["assignment"]}
    assert got.get("С15") == "D-18"  # «Шаг 5 возвращает прежний порог, но в ответе ERROR amount не описан»
    assert all(d["finding"] != "D-18" for d in res["duplicates"])
    assert {"К1", "К2", "К3", "К4", "К5"} <= set(got)


def test_clarity_sentences_ignore_abbreviations():
    """«Ф-2 (стр. 38) относит…» — одно предложение: точка после «стр.»/«п.»/«см.» не конец предложения
    (на haiku 15:30 рубрика «проблема» падала у 28 из 30 карточек только из-за «стр. N»)."""
    from evaluation.v2 import score as sc

    assert len(sc._sentences("Ф-2 (стр. 38) относит покупку к месяцу. Критерий (стр. 64) требует роста.")) == 2
    assert len(sc._sentences("См. п. 5 логики метода. Итог 1 000 ₸.")) == 2
    assert len(sc._sentences("Первое. Второе. Третье.")) == 3


def test_cleantable_tilde_times_are_older_and_open2_edition():
    from evaluation.v2 import cleantable as ct

    old = ct._row("№18: чистые версии (2-я редакция)", "haiku", "№18 haiku_clean2_0835", "~0835", "qr_clean", {}, {})
    new = ct._row("№18: чистые версии (2-я редакция)", "haiku", "замер 15:30", "2026-11-27 15:35", "qr_clean", {}, {})
    assert ct.latest([old, new])[("№18: чистые версии (2-я редакция)", "haiku")][0]["label"] == "замер 15:30"
    assert ct._set_of("evaluation/v2/clean/fx/source.md") == "чистые ТЗ №20"
    assert ct._set_of("evaluation/v2/open2/qr_clean/source.md", ["нет-такого"], "2026-11-27 15:35").endswith("(2-я редакция)")
    assert ct._set_of("evaluation/v2/open2/qr_clean/source.md", [], "2026-11-27 05:20").endswith("(1-я редакция)")


def test_final_numbers_collects_runs_by_commit(tmp_path, monkeypatch):
    import json as _json

    from evaluation.v2 import final

    v2 = tmp_path / "evaluation" / "v2"
    (v2 / "measurements" / "m1").mkdir(parents=True)
    (v2 / "measurements" / "m1" / "score.json").write_text(_json.dumps({"clarity": {"n": 10, "passed": 9}}),
                                                          encoding="utf-8")
    rows = [{"label": "замер: abc1234, sonnet", "model": "sonnet", "status": "complete", "K": 5, "K_as_critical": 5,
             "C": 18, "findings": 29, "duplicates": 1, "critical_false": 0, "duration_s": 180, "calls": 9,
             "cost_usd": 0.8, "dir": "evaluation/v2/measurements/m1", "C_missed": ["С15", "С17"]},
            {"label": "замер: abc1234, sonnet #2", "model": "sonnet", "status": "complete", "K": 5, "K_as_critical": 4,
             "C": 19, "findings": 31, "duplicates": 0, "critical_false": 0, "duration_s": 170, "calls": 9,
             "cost_usd": 0.7, "dir": "нет", "C_missed": ["С17"]},
            {"label": "другой: fff0000, haiku", "model": "haiku"}]
    (v2 / "history.jsonl").write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    monkeypatch.setattr(final, "V2", v2)
    monkeypatch.setattr(final, "ROOT", tmp_path)
    text = final.render("abc1234", "abc1234", "", checks=[])
    assert "| sonnet | 2 | 2 | 5/5 | 4–5 | 18–19 | 29–31 | 0–1 | 0 | 2.8–3.0 | 9 | 90 % | 0.70–0.80 |" in text
    assert "sonnet — С15 (1 из 2), С17 (2 из 2)" in text and "haiku" not in text


def test_final_marks_cache_replay_and_splits_gate_by_code():
    """Набор без вызовов модели — «повтор из кэша», а не выборка; ворота — сколько строк на коде релиза и что в них красное."""
    from evaluation.v2 import final

    assert final._calls({"runs": 8, "time": {"calls": 0, "cost_usd": 0}}) == "0 — повтор из кэша"
    assert final._calls({"cases": 33, "time": {"calls": 278, "cost_usd": 1.813}}) == "278, $1.81"
    assert final._calls({"runs": 4}) == "—"
    assert [final._rows(n) for n in (1, 3, 11, 21, 53, 112)] == [
        "1 строка", "3 строки", "11 строк", "21 строка", "53 строки", "112 строк"]
    checks = [{"name": "Официальный, sonnet: время", "ok": False, "fact": "3.1 мин", "target": "≤ 3 мин",
               "owners": "№10", "source": "релиз: abc1234, sonnet (16:15)"},
              {"name": "Официальный, sonnet: К1–К5", "ok": True, "fact": "5/5", "target": "≥ 5/5",
               "source": "релиз: abc1234, sonnet (16:15)"},
              {"name": "Официальный, Opus: дубли", "ok": False, "fact": "7", "target": "0",
               "source": "стабильность Opus: e2f2cba, opus #1"},
              {"name": "Официальный, Gemini: замер", "ok": None, "fact": "нет замера", "target": "есть", "source": None},
              {"name": "справка", "ok": True, "info": True, "source": "релиз: abc1234"}]
    text = "\n".join(final.gate_lines("abc1234", checks))
    assert "(4 строки," in text and "на этом коде 2 — ✅ 1, ❌ 1, ⏳ 0" in text and "без замера 1" in text
    assert "| Официальный, sonnet: время | 3.1 мин (≤ 3 мин) | №10 |" in text
    assert "стабильность Opus: e2f2cba, opus #1 — 1 (✅ 0, ❌ 1, ⏳ 0)" in text
    assert "Opus: дубли |" not in text  # красное чужого кода — не в таблице релиза


def test_stability_gate_prefers_more_runs_within_same_minute(tmp_path, monkeypatch):
    """Сводка ×3 по двум раундам и ×2 раунда записаны в одну минуту — ворота берут ×3, а не первую в glob."""
    import json as _json

    from evaluation.v2 import gate

    st = tmp_path / "stability"
    st.mkdir()
    for name, n in (("a_x2.json", 2), ("b_x3.json", 3), ("c_old.json", 4)):
        d = {"at": "2026-11-27 16:55" if name != "c_old.json" else "2026-11-27 08:00", "n": n, "models": ["sonnet"],
             "label": f"sonnet ×{n}", "K_all_runs": ["К1", "К2", "К3", "К4", "К5"],
             "per_item": {k: {"found": n, "owners": []} for k in ("К1", "К2", "К3", "К4", "К5")},
             "findings": {"min": 27, "max": 30, "mean": 29.0}}
        (st / name).write_text(_json.dumps(d, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gate, "V2", tmp_path)
    rows = [c for c in gate.stability_gates({}) if c["name"].startswith("Стабильность, sonnet")]
    assert rows and all(c["source"] == "sonnet ×3" for c in rows)
    assert rows[0]["name"].endswith("в 3 из 3") and rows[0]["ok"] is True


def test_final_code_note_flags_runs_on_other_code(monkeypatch):
    """Метка «на abc1234» не доказательство: код каждого прогона сверяется по git, чужой — предупреждение."""
    from evaluation.v2 import final

    same = {"aaa1111": True, "bbb2222": True, "ccc3333": False, "ddd4444": None}
    monkeypatch.setattr(final, "same_code", lambda c, sha: same[c])
    ok = final.code_note("abc1234", [[{"commit": "aaa1111"}], [{"commit": ["aaa1111", "bbb2222"]}], []])
    assert ok.startswith("Код прогонов сверен по git (коммитов прогонов: 2, сверено 2)") and "⚠" not in ok
    bad = final.code_note("abc1234", [[{"commit": "aaa1111"}, {"commit": "ccc3333"}]])
    assert bad.startswith("⚠") and "`ccc3333`" in bad and "aaa1111" not in bad
    assert "; git не знает: ddd4444" in final.code_note("abc1234", [[{"commit": "ddd4444"}, {"commit": "aaa1111"}]])
    assert final.code_note("abc1234", [[{"label": "без коммита"}]]) == ""


def test_gate_history_line_and_codes():
    """Итог ворот в RESULTS — с историей за день (повторы счёта схлопнуты) и кодом, на котором стоят ворота."""
    from evaluation.v2 import gate

    checks = [{"name": "a", "ok": True, "source": "W4-07 после заморозки: 28fe64f, sonnet (16:32)"},
              {"name": "b", "ok": False, "source": "стабильность Opus: e2f2cba, opus #1 (08:34)"},
              {"name": "c", "ok": True, "info": True, "source": "справка: 1234567"},
              {"name": "d", "ok": None, "source": "чистые №20, haiku, deadbee? нет — только слова"}]
    assert gate.codes_of(checks) == ["28fe64f", "e2f2cba"]
    rows = [{"at": "2026-11-27 15:30", "green": 35, "red": ["x"] * 16, "waiting": ["w", "w"]},
            {"at": "2026-11-27 16:24", "green": 39, "red": ["x"] * 12, "waiting": ["w", "w"]},
            {"at": "2026-11-27 16:25", "green": 39, "red": ["x"] * 12, "waiting": ["w", "w"]},
            {"at": "2026-11-27 16:55", "green": 44, "red": ["x"] * 8, "waiting": ["w"]},
            {"at": "2026-11-27 16:56", "green": 44, "red": ["x"] * 8, "waiting": ["w"], "codes": ["28fe64f"]}]
    line = gate.history_line(rows)
    assert line.endswith("15:30 — 35/16/2; 16:25 — 39/12/2; 16:56 на `28fe64f` — 44/8/1.")
    assert gate.history_line(rows[:1]) == ""
    text = gate.render_summary([{"name": "a", "ok": True}], "Ворота WAVE3, 16:55", rows)
    assert "Ворота за день" in text and text.index("Ворота за день") > text.index("зелёных 1")


def test_final_code_diff_lists_changed_files(monkeypatch):
    """Код тега не тот, что мерили, — видно, какие файлы: задевает ли разница основной прогон."""
    import subprocess as _sp

    from evaluation.v2 import final

    out = "12\t0\tsrc/bcc_review/v2/prompts/recheck.md\n533\t64\tsrc/bcc_review/v2/stages/recheck.py\n1\t1\tpyproject.toml\n"
    monkeypatch.setattr(final, "_git", lambda *a: _sp.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert final.code_diff("a", "b") == ("`prompts/recheck.md` (+12/−0), `stages/recheck.py` (+533/−64), "
                                         "`pyproject.toml` (+1/−1)")
    assert final.code_diff("a", "b", limit=1).endswith("и ещё 2")
    monkeypatch.setattr(final, "_git", lambda *a: _sp.CompletedProcess(a, 128, stdout="", stderr="bad"))
    assert final.code_diff("a", "b") == ""


def test_final_newer_code_section(monkeypatch):
    """--newer: официальный документ на более новом коде отдельной таблицей и чем код отличается от кода релиза."""
    from evaluation.v2 import final

    rows = {"new1234": [{"label": "голова: new1234, sonnet", "model": "sonnet", "status": "complete", "K": 5,
                         "K_as_critical": 5, "C": 17, "findings": 27, "duplicates": 0, "critical_false": 0,
                         "duration_s": 150, "calls": 9, "cost_usd": 0.78, "clarity": {}, "commit": "abcdef1"}]}
    monkeypatch.setattr(final, "resolve", lambda ref: (ref, ""))
    monkeypatch.setattr(final, "official", lambda sha: rows.get(sha, []))
    monkeypatch.setattr(final, "same_code", lambda a, b: a == b or (a, b) == ("abcdef1", "new1234"))
    monkeypatch.setattr(final, "code_diff", lambda a, b: "`stages/recheck.py` (+533/−64)")
    text = "\n".join(final.newer_lines("old1234", ["new1234", "none999"]))
    assert "**Проверка на более новом коде `new1234`**" in text and "`stages/recheck.py` (+533/−64)" in text
    assert "| sonnet | 1 | 1 | 5/5 | 5 | 17 | 27 | 0 | 0 | 2.5 | 9 |" in text
    assert "Код прогонов сверен по git" in text and "На `none999` замеров официального документа нет." in text


def test_composite_item_parts_are_not_duplicates():
    """Эталон свёл разные дефекты в один пункт (С2: 403↔404; 201 не описан; «и далее») — три замечания о трёх частях
    не дубли; второе о той же части — дубль; С считается один раз (живой отчёт haiku W4-07 на c6aa9b5)."""
    import json as _json

    from evaluation.v2 import score as sc
    from evaluation.v2.common import ROOT

    gold = sc.load_gold(sc.DEFAULT_GOLD)
    rep = _json.loads((ROOT / "evaluation/v2/measurements/w4_07_zamorozka_c6aa9b5_haiku/report.json")
                      .read_text(encoding="utf-8"))
    res = sc.score_report(rep, gold, arbiter="off")
    parts = {p["finding"]: (p["gold"], p["parts"]) for p in res["parts"]}
    assert parts["D-18"] == ("С2", ["201 не описан"])            # засчитан D-20 «403 или 404 в разных местах»
    assert parts["D-32"] == ("С2", ["открытый перечень «400, 401 и далее»"])
    assert parts["D-22"][0] == "С16" and parts["D-11"][0] == "С12"
    dups = {d["finding"]: d["gold"] for d in res["duplicates"]}
    assert dups.get("D-31") == "С1"  # Content-Type: засчитанное за С1 уже о нём — настоящий дубль
    assert res["precision"]["duplicates"] == 2 and res["precision"]["parts"] == 4
    assert res["recall"]["major"]["n"] == 17 and "С2" in res["recall"]["major"]["found"]


def test_split_parts_needs_disjoint_parts_and_keeps_second_same_part_a_duplicate():
    import re

    from evaluation.v2 import score as sc

    item = {"id": "С9", "_parts": [("a", re.compile("сумм", re.I)), ("b", re.compile("цифр", re.I))]}
    plain = {"id": "С8"}
    by_id = {"С9": item, "С8": plain}
    fmap = {fid: {"id": fid, "title": t, "_title": t, "fields": {"problem": ""}, "_text": t}
            for fid, t in (("D-1", "Какие цифры карты"), ("D-2", "Какая сумма в сообщении"),
                           ("D-3", "Сумма в сообщении не задана"), ("D-4", "Что-то общее"), ("D-5", "Цифры и сумма"))}
    edges = {("С9", f): 2.0 for f in fmap} | {("С8", "D-4"): 2.5}
    dups = {"D-2": "С9", "D-3": "С9", "D-4": "С8", "D-5": "С9"}
    out = sc.split_parts({"С9": "D-1", "С8": "D-9"}, dups, edges, by_id, fmap)
    assert out == {"D-2": ("С9", ["a"])}         # другая часть — не дубль
    assert dups == {"D-3": "С9", "D-4": "С8", "D-5": "С9"}  # та же часть, без частей, пересечение — дубли


def test_rescore_rewrites_history_rows_in_place(tmp_path, monkeypatch):
    """Пересчёт оценок обновляет и строки истории (по `dir`): время и метка замера прежние, метрики — новые."""
    import json as _json

    from evaluation.v2 import measure

    hist = tmp_path / "history.jsonl"
    rows = [{"at": "2026-11-27 16:15", "label": "замер: abc1234, sonnet", "dir": "m/a", "duplicates": 2, "C": 18},
            {"at": "2026-11-27 16:20", "label": "другой", "dir": "m/b", "duplicates": 5}]
    hist.write_text("\n".join(_json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(measure, "HISTORY", hist)
    n = measure._rewrite_history({"m/a": {"at": "сейчас", "label": "чужая", "dir": "m/a", "duplicates": 0, "parts": 2,
                                          "C": 18}})
    got = [_json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines()]
    assert n == 1 and len(got) == 2 and got[1] == rows[1]
    assert got[0]["at"] == "2026-11-27 16:15" and got[0]["label"] == "замер: abc1234, sonnet"
    assert got[0]["duplicates"] == 0 and got[0]["parts"] == 2 and "rescored_at" in got[0]
    assert measure._rewrite_history({}) == 0


def test_part_candidate_may_be_outside_focus():
    """Перечень кодов «201 не описан, «и далее»» ближе к К3 по строкам L151/L165, но по заголовку — другая часть С2,
    чем засчитанное «403 или 404»: часть, а не дубль К3 (живой отчёт sonnet на 747364c)."""
    import json as _json

    from evaluation.v2 import score as sc
    from evaluation.v2.common import ROOT

    gold = sc.load_gold(sc.DEFAULT_GOLD)
    rep = _json.loads((ROOT / "evaluation/v2/measurements/w4_07_golova_17_25_747364c_sonnet/report.json")
                      .read_text(encoding="utf-8"))
    res = sc.score_report(rep, gold, arbiter="off")
    assert {p["finding"]: p["gold"] for p in res["parts"]} == {"D-16": "С2"}
    assert res["precision"]["duplicates"] == 0 and res["recall"]["major"]["n"] == 17


def test_viewdiff_compare_reports_first_difference():
    """Вид документа на двух коммитах: совпал, отличается (строка, поле и кусок вокруг первого отличия), не прочитан."""
    from evaluation.v2 import viewdiff as vd

    line = lambda n, text, section="": [n, text, None, section, n, "", "", 0, False]  # noqa: E731
    a = {"title": "ТЗ", "format": "md", "warnings": [], "pages": None,
         "lines": [line(1, "# ТЗ"), line(2, "Сумма в тиынах, порог в тенге, пересчёт не описан", "Ф-1")]}
    b = {**a, "lines": [line(1, "# ТЗ"), line(2, "Сумма в тиынах, порог в тенге, пересчёт описан", "Ф-1")]}
    res = vd.compare({"x.md": a, "y.md": a, "z.md": a}, {"x.md": a, "y.md": b, "z.md": {"error": "ValueError()"}})
    assert res["docs"] == 3 and res["same"] == ["x.md"]
    assert [d["doc"] for d in res["diff"]] == ["y.md"] and [e["doc"] for e in res["errors"]] == ["z.md"]
    where = res["diff"][0]["where"]
    assert where.startswith("строка 2, text:") and "не описан" in where and "пересчёт описан" in where
    assert vd.first_difference(a, {**a, "title": "Другое"}).startswith("title:")


def test_viewdiff_main_run_prompts_and_summary():
    """Промпты и код этапов делятся на основной прогон и прочее (режим `--answers`): recheck/revise — не основной."""
    from evaluation.v2 import viewdiff as vd

    stages = vd.MAIN_STAGES
    assert vd._in_main("judge_check.md", stages) and vd._in_main("_system.md", stages)
    assert vd._in_main("src/bcc_review/v2/stages/lens_risk.py", stages)
    assert not vd._in_main("recheck.md", stages) and not vd._in_main("revise_check.md", stages)
    res = {"docs": 51, "same": ["d"] * 51, "diff": [], "errors": [], "prompts_main": [],
           "prompts_other": ["recheck.md"], "stage_code_changed": []}
    s = vd.summary_line(res)
    assert s.startswith("вид документов оценки не изменился (51 из 51)") and "вне его — recheck.md" in s
    assert s.endswith("код этапов основного прогона тот же") and vd.same_input(res)
    res["stage_code_changed"] = ["stages/judge.py"]
    assert not vd.same_input(res) and vd.summary_line(res).endswith("изменён: stages/judge.py")


def test_viewdiff_same_commit_builds_view_from_exported_code():
    """Код коммита выгружается `git archive`, вид строит его же docview (не установленный пакет): HEAD → HEAD совпал."""
    from evaluation.v2 import viewdiff as vd

    res = vd.check("HEAD", "HEAD", docs=["release/input/requirements.md"])
    assert res["docs"] == 1 and res["same"] == ["release/input/requirements.md"] and not res["errors"]
    assert res["prompts_changed"] == [] and res["stage_code_changed"] == [] and vd.same_input(res)


def test_gate_official_rows_show_spread_on_same_code(monkeypatch):
    """Вердикт — по последнему прогону; в скобках — разброс той же модели на том же коде (по деревьям git), без
    повторов из кэша (calls 0) и без прогонов на другом коде."""
    trees = {"aaa1111": "T1", "bbb2222": "T1", "ccc3333": "T2"}
    monkeypatch.setattr(gate, "code_tree", lambda c: trees.get(c))
    row = lambda commit, C, calls=9, model="sonnet", d=150.0: {  # noqa: E731
        "commit": commit, "C": C, "calls": calls, "model": model, "provider": "claude_cli", "duration_s": d}
    rows = [row("aaa1111", 19), row("ccc3333", 14), row("bbb2222", 19, calls=0), row("aaa1111", 17, model="haiku"),
            row("bbb2222", 18, d=170.0)]
    peers = gate.same_code_rows(rows, "sonnet", rows[-1])
    assert [r["C"] for r in peers] == [19, 18]  # другой код (14), повтор из кэша и haiku — мимо
    assert gate.spread(peers, "C") == " (на этом коде 18–19 в 2 прогонах)"
    assert gate.spread(peers, "duration_s", minutes=True) == " (на этом коде 2.5–2.8 в 2 прогонах)"
    assert gate.spread(peers[:1], "C") == "" and gate.spread([rows[0], rows[0]], "C") == " (на этом коде так во всех 2)"
    trees.clear()  # код не сверить (коммита нет в git) — только сам последний прогон
    assert gate.same_code_rows(rows, "sonnet", rows[-1]) == [rows[-1]]


def test_corpus_background_splits_mutant_false_positives_by_origin():
    """Ложные на мутантах корпуса 28fe64f (haiku): та же жалоба, что на чистой базе, — 50 из 152; то же место —
    65; только у мутанта — 37. Ни одна верная находка не «та же жалоба» (калибровка порогов)."""
    import json as _json

    from evaluation.v2 import corpus as cp
    from evaluation.v2.common import ROOT

    d = ROOT / "evaluation/v2/corpus_results/w4_07_posle_zamorozki_28fe64f_haiku"
    matrix = [_json.loads(x) for x in (d / "matrix.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    per_case = _json.loads((d / "summary.json").read_text(encoding="utf-8"))["per_case"]
    b = cp.background(d / "predictions.jsonl", matrix, per_case)
    assert (b["fp_mutant"], b["same_complaint"], b["same_place"], b["own"], b["no_base"]) == (152, 50, 65, 37, 0)
    assert b["strict"] <= b["same_complaint"] and list(b["by_owner_same"])[0] == "№09"
    tp_as_fp = [{**m, "outcome": "FP"} for m in matrix if m["outcome"] == "TP"]
    assert cp.background(d / "predictions.jsonl", tp_as_fp)["same_complaint"] == 0
    line = cp.background_line(b)
    assert line.startswith("Ложные на мутантах (152) по происхождению") and "— 50 (33 %" in line
    assert cp._quote_close("Сумма списания не больше лимита", "сумма списания не больше лимита в сутки")
    assert not cp._quote_close("лимит", "лимит")  # меньше трёх слов — не место


def test_quota_runs_are_not_saved_and_rerun_with_reuse(tmp_path):
    """Прогон, упёршийся в лимит подписки (run.model_error), — не замер: --reuse его перезапускает, --save отказывает
    (замер кандидата 868787d в 18:00: корпус — 23 из 33 кейсов «не измерено», ворота показали бы F1 от обрывков)."""
    import json as _json

    from evaluation.v2.common import quota_hit, quota_refusal, reusable_report

    quota = {"run": {"status": "failed", "model_error": "Исчерпан лимит подписки Claude Code. Сброс лимита: 1:20pm (UTC)."}}
    partial = {"run": {"status": "partial", "model_error": "Исчерпан лимит подписки Claude Code."}}
    other = {"run": {"status": "failed", "model_error": "Ответ модели обрезан по лимиту выходных токенов."}}
    ok = {"run": {"status": "complete", "model_error": None}}
    assert quota_hit(quota) and quota_hit(partial) and not quota_hit(other) and not quota_hit(ok)
    paths = {}
    for name, rep in (("quota", quota), ("partial", partial), ("other", other), ("ok", ok)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(_json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert [n for n in paths if reusable_report(paths[n])] == ["partial", "ok"][1:]  # упавшие и лимит — заново
    assert not reusable_report(tmp_path / "broken.json") and not reusable_report(tmp_path / "missing.json")
    rows = [{"quota": True}, {"quota": False}, {"quota": True}]
    msg = quota_refusal(rows, "сводку корпуса")
    assert msg.startswith("не сохраняю сводку корпуса: 2 из 3 прогонов упёрлись в лимит") and "--reuse" in msg
    assert quota_refusal([{"quota": False}], "сводку") == ""


def test_round_stability_takes_earlier_runs_on_same_code(tmp_path, monkeypatch):
    """Стабильность раунда — с прошлыми прогонами модели на том же коде (кандидат 868787d: ×2 в раунде + 17:46 = ×3);
    прогон на другом коде, повтор из кэша и прогоны самого раунда в «прошлые» не попадают."""
    import json as _json

    from evaluation.v2 import round as rnd

    def run(label, commit, calls=9):
        d = tmp_path / label
        d.mkdir()
        (d / "score.json").write_text("{}", encoding="utf-8")
        return {"version": "v2", "label": label, "commit": commit, "calls": calls, "model": "sonnet",
                "provider": "claude_cli", "dir": str(d)}

    rows = [run("old_other_code", "c2"), run("old_same_code", "c1"), run("replay", "c1", calls=0),
            run("round_1", "c1b"), run("round_2", "c1b")]
    hist = tmp_path / "history.jsonl"
    hist.write_text("".join(_json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(gate, "HISTORY", hist)
    monkeypatch.setattr(gate, "code_tree", lambda c: {"c1": "T1", "c1b": "T1", "c2": "T2"}.get(c))
    got = rnd.same_code_scores("sonnet", ["round_1", "round_2"])
    assert [p.split("/")[-2] for p in got] == ["old_same_code"]
    assert rnd.same_code_scores("sonnet", ["нет в истории"]) == []


def test_final_sets_from_other_code_are_marked(monkeypatch):
    """--sets-from: официальный — на коде релиза, корпус и наборы — с названного кода, с пометкой и «входом модели»;
    код прогонов наборов сверяется со своим кодом, а не с кодом релиза."""
    from evaluation.v2 import final

    off = {"rel1234": [{"label": "кандидат: rel1234, sonnet", "model": "sonnet", "status": "complete", "K": 5,
                        "K_as_critical": 5, "C": 18, "findings": 29, "duplicates": 0, "critical_false": 0,
                        "duration_s": 150, "calls": 9, "cost_usd": 0.8, "clarity": {}, "commit": "rel1234"}]}
    corp = {"frz5678": [{"label": "после заморозки: frz5678, haiku", "model": "haiku", "cases": 33, "failed": 0,
                         "harness": {"tp": 27, "fp": 202, "fn": 1, "precision": 0.12, "recall": 0.96, "f1": 0.21},
                         "clean": {"critical": 0, "verdict_no": 0, "measured": 8}, "time": {"calls": 244, "cost_usd": 1.6},
                         "commit": ["frz5678"]}]}
    monkeypatch.setattr(final, "official", lambda sha: off.get(sha, []))
    monkeypatch.setattr(final, "_summaries", lambda folder, sha: corp.get(sha, []) if "corpus" in str(folder) else [])
    monkeypatch.setattr(final, "same_code", lambda a, b: a == b)
    monkeypatch.setattr(final, "view_line", lambda a, b: f"Вход модели ({a} → {b}): вид документов оценки не изменился.")
    monkeypatch.setattr(final, "gate_lines", lambda sha, checks=None: [])
    text = final.render("v2.0.0", "rel1234", "", sets_sha="frz5678")
    assert "**Наборы ниже — на коде `frz5678`**, не на `rel1234`" in text and "Вход модели (frz5678 → rel1234)" in text
    assert "--sets-from frz5678 --write" in text and "| после заморозки: frz5678, haiku | haiku | 33 (0) | 27 | 202 |" in text
    assert "как у `rel1234`" in text and "Код прогонов наборов сверен" in text and "как у `frz5678`" in text
    assert "⚠" not in text  # без --sets-from прогоны frz5678 стояли бы как «код не совпадает»
    plain = final.render("v2.0.0", "rel1234", "")
    assert "Наборы ниже" not in plain and "Корпус" not in plain


def test_measure_does_not_write_history_for_quota_stopped_run(tmp_path, monkeypatch):
    """Официальный замер, где агент упёрся в лимит подписки, в history.jsonl не попадает (иначе ворота взяли бы его
    последним: статус failed, К и С от обрывка); --save-partial — записать как есть."""
    import json as _json

    from evaluation.v2 import measure
    from evaluation.v2.common import ROOT

    rep = _json.loads((ROOT / "evaluation/v2/measurements/w4_07_golova_17_50_868787d_sonnet/report.json")
                      .read_text(encoding="utf-8"))
    rep["run"].update({"status": "partial", "model_error": "Исчерпан лимит подписки Claude Code. Сброс лимита: 1:20pm (UTC)."})
    src = tmp_path / "in" / "report.json"
    src.parent.mkdir()
    src.write_text(_json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    hist = tmp_path / "history.jsonl"
    hist.write_text("", encoding="utf-8")
    monkeypatch.setattr(measure, "HISTORY", hist)
    monkeypatch.setattr(measure, "MEAS", tmp_path / "m")
    monkeypatch.setattr(measure, "update_results", lambda: None)
    monkeypatch.setattr(measure, "ROOT", tmp_path)
    args = ["--from-report", str(src), "--label", "лимит", "--arbiter", "off"]
    assert measure.main(args) == 3 and hist.read_text(encoding="utf-8") == ""
    assert measure.main(args + ["--save-partial"]) == 0 and len(hist.read_text(encoding="utf-8").splitlines()) == 1


def test_round_runs_official_first_and_skips_sets_after_quota(tmp_path, monkeypatch):
    """Раунд: сначала официальный документ, потом наборы; официальный упёрся в лимит подписки — наборы не стартуют."""
    from evaluation.v2 import round as rnd

    started: list[str] = []

    class FakeProc:
        def __init__(self, cmd, cwd=None, stdout=None, stderr=None):
            name = cmd[-1]
            started.append(name)
            if name == "official_sonnet_1" and quota:
                stdout.write("агент упёрся в лимит провайдера (Исчерпан лимит подписки Claude Code.)\n")
            stdout.close()

        def wait(self):
            return 0

    def fake_jobs(*_a, **_k):
        return [("official_sonnet_1", ["x", "official_sonnet_1"]), ("corpus", ["x", "corpus"]),
                ("clean20", ["x", "clean20"])]

    monkeypatch.setattr(rnd.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(rnd.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(rnd, "ROOT", tmp_path)
    for quota, expect in ((False, ["official_sonnet_1", "corpus", "clean20"]), (True, ["official_sonnet_1"])):
        started.clear()
        logs = tmp_path / ("q" if quota else "ok")
        logs.mkdir()
        rcs = rnd.run_waves(fake_jobs(), logs, together=False)
        assert started == expect
        assert (rcs["corpus"] == 3) is quota
