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
    assert ok.startswith("Код прогонов сверен: 2 из 2") and "⚠" not in ok
    bad = final.code_note("abc1234", [[{"commit": "aaa1111"}, {"commit": "ccc3333"}]])
    assert bad.startswith("⚠") and "`ccc3333`" in bad and "aaa1111" not in bad
    assert "git не знает: ddd4444" in final.code_note("abc1234", [[{"commit": "ddd4444"}, {"commit": "aaa1111"}]])
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
