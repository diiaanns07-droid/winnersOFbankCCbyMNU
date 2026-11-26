"""№09: разбор ответа этапа consistency кодом (без сети, синтетические ответы модели)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from bcc_review.v2.stages import consistency as C

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "consistency.md"

DOC = [
    "# Вклад",                                                     # 1
    "Цель: клиент видит доход по вкладу сразу после пополнения.",   # 2
    "* **В-1.** Вклад можно пополнять не более трёх раз в квартал.",  # 3
    "* **В-2.** Пополнение через кассу доступно всегда, независимо от числа предыдущих пополнений.",  # 4
    "* **В-3.** Минимальная сумма вклада — 10 000.",                # 5
    "* **В-4.** Минимальная сумма пополнения — 1 000.",             # 6
    "Доход начисляется банком на следующий рабочий день.",          # 7
    "| Сумма 10 000 | Пополнить на 1 000 | Сумма 11 000 |",         # 8
    "Хранить идентификатор вклада, сумму вклада и дату пополнения.",  # 9
    "Клиент открывает вклад, держатель счёта пополняет его.",       # 10
]
VIEW = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(DOC, 1)]}
REQS = [
    {"id": "R-01", "source_id": "", "kind": "goal", "line_start": 2, "line_end": 2},
    {"id": "R-02", "source_id": "В-1", "kind": "functional", "line_start": 3, "line_end": 3},
    {"id": "R-03", "source_id": "В-2", "kind": "functional", "line_start": 4, "line_end": 4},
    {"id": "R-04", "source_id": "В-3", "kind": "functional", "line_start": 5, "line_end": 5},
    {"id": "R-05", "source_id": "В-4", "kind": "functional", "line_start": 6, "line_end": 6},
    {"id": "R-06", "source_id": "", "kind": "functional", "line_start": 7, "line_end": 7},
    {"id": "R-07", "source_id": "Критерии, строка 1", "kind": "acceptance", "line_start": 8, "line_end": 8},
    {"id": "R-08", "source_id": "", "kind": "data", "line_start": 9, "line_end": 9},
]


def pair(**kw):
    base = {"a": "R-02", "b": "R-03", "subject": "число пополнений вклада за квартал", "same_subject": True,
            "quote_a": "Вклад можно пополнять не более трёх раз в квартал.", "line_a": 3,
            "quote_b": "Пополнение через кассу доступно всегда", "line_b": 4,
            "scenario": "В квартале три пополнения онлайн, клиент пополняет в кассе.",
            "outcome_a": "четвёртое пополнение запрещено", "outcome_b": "пополнение разрешено",
            "verdict": "conflict", "kind": "event_conflict", "title": "", "impact": "", "recommendation": "",
            "question": ""}
    base.update(kw)
    return base


def answer(**kw):
    base = {"subjects": [], "pair_checks": [], "glossary": [], "trace": [], "candidates": []}
    base.update(kw)
    return base


def test_schema_is_valid_json_schema_and_accepts_empty_answer():
    jsonschema.Draft202012Validator.check_schema(C.SCHEMA)
    jsonschema.validate(answer(), C.SCHEMA)
    jsonschema.validate(answer(pair_checks=[pair()]), C.SCHEMA)


def test_conflict_on_same_subject_with_two_places_is_critical_with_two_quotes():
    out = C.postprocess(answer(pair_checks=[pair()]), VIEW, REQS)
    [c] = out["candidates"]
    assert c["severity"] == "critical"
    assert c["kind"] == "event_conflict"
    assert c["criterion"] == "set_consistent"
    assert c["source"] == "consistency"
    assert c["requirement_ids"] == ["R-02", "R-03"]
    assert [e["line"] for e in c["evidence"]] == [3, 4]
    assert all(e["verified"] != "missing" for e in c["evidence"])
    assert c["blocks"] == "both" and c["scenario"] and c["impact"]
    assert out["pair_checks"][0]["verdict"] == "conflict"
    assert "_ev" not in out["pair_checks"][0]


def test_different_subjects_are_never_compared():
    p = pair(a="R-04", b="R-05", subject="минимальные суммы", same_subject=False,
             quote_a="Минимальная сумма вклада — 10 000.", line_a=5,
             quote_b="Минимальная сумма пополнения — 1 000.", line_b=6, kind="boundary_conflict")
    out = C.postprocess(answer(pair_checks=[p]), VIEW, REQS)
    assert out["candidates"] == []
    assert out["pair_checks"][0]["verdict"] == "compatible"


def test_compatible_pair_gives_no_candidate():
    out = C.postprocess(answer(pair_checks=[pair(verdict="compatible")]), VIEW, REQS)
    assert out["candidates"] == []


def test_conflict_with_one_missing_quote_is_downgraded_to_major():
    out = C.postprocess(answer(pair_checks=[pair(quote_b="Этой фразы в документе нет")]), VIEW, REQS)
    [c] = out["candidates"]
    assert c["severity"] == "major"
    assert out["pair_checks"][0]["verified_b"] == "missing"


def test_conflict_without_any_found_quote_is_dropped():
    out = C.postprocess(answer(pair_checks=[pair(quote_a="нет такой", quote_b="и такой нет")]), VIEW, REQS)
    assert out["candidates"] == []


def test_line_hint_is_corrected_by_quote_search():
    out = C.postprocess(answer(pair_checks=[pair(line_a=30, line_b=1)]), VIEW, REQS)
    p = out["pair_checks"][0]
    assert (p["line_a"], p["line_b"]) == (3, 4)


def test_undefined_is_major_ambiguity_and_capped():
    pairs = [pair(verdict="undefined", subject=f"предмет {i}", quote_a=q, line_a=n,
                  quote_b="Доход начисляется банком на следующий рабочий день.", line_b=7)
             for i, (q, n) in enumerate([("Вклад можно пополнять", 3), ("Пополнение через кассу", 4),
                                          ("Минимальная сумма вклада", 5), ("Минимальная сумма пополнения", 6),
                                          ("Хранить идентификатор вклада", 9), ("Клиент открывает вклад", 10)])]
    out = C.postprocess(answer(pair_checks=pairs), VIEW, REQS)
    assert len(out["candidates"]) == C.MAX_UNDEFINED_CANDIDATES
    assert {c["severity"] for c in out["candidates"]} == {"major"}
    assert {c["kind"] for c in out["candidates"]} == {"ambiguity"}
    assert len(out["pair_checks"]) == 6


def test_undefined_unit_mismatch_keeps_kind():
    out = C.postprocess(answer(pair_checks=[pair(verdict="undefined", kind="unit_mismatch")]), VIEW, REQS)
    assert out["candidates"][0]["kind"] == "unit_mismatch"
    assert out["candidates"][0]["criterion"] == "unambiguous"


def test_duplicate_pairs_and_self_pairs_are_removed():
    same = pair(quote_b="Вклад можно пополнять не более трёх раз в квартал.", line_b=3)
    out = C.postprocess(answer(pair_checks=[pair(), pair(a="R-03", b="R-02"), same]), VIEW, REQS)
    assert len(out["pair_checks"]) == 1
    assert len(out["candidates"]) == 1


def test_model_candidate_repeating_pair_conflict_is_dropped_others_kept():
    dup = {"title": "В-1 противоречит В-2", "kind": "event_conflict", "criterion": "set_consistent",
           "severity": "critical", "requirement_ids": ["R-02", "R-03"],
           "evidence": [{"quote": "не более трёх раз в квартал", "line": 3},
                        {"quote": "независимо от числа предыдущих пополнений", "line": 4}],
           "problem": "п", "scenario": "с", "impact": "и", "recommendation": "р", "rewrite": "", "question": "",
           "blocks": "both"}
    goal = {"title": "Цель обещает доход сразу, а начисление — на следующий день", "kind": "contradiction",
            "criterion": "set_feasible", "severity": "critical", "requirement_ids": [],
            "evidence": [{"quote": "клиент видит доход по вкладу сразу после пополнения", "line": 2},
                         {"quote": "Доход начисляется банком на следующий рабочий день.", "line": 7}],
            "problem": "п", "scenario": "", "impact": "и", "recommendation": "р", "rewrite": "", "question": "",
            "blocks": "both"}
    out = C.postprocess(answer(pair_checks=[pair()], candidates=[dup, goal]), VIEW, REQS)
    origins = [c["origin"] for c in out["candidates"]]
    assert origins == ["pair_check", "model"]
    g = out["candidates"][1]
    assert g["severity"] == "major"  # critical без сценария понижается
    assert g["requirement_ids"] == ["R-01", "R-06"]  # ID восстановлены по строкам цитат


def test_model_candidate_without_quotes_is_dropped_and_enums_sanitized():
    bad = {"title": "т", "kind": "weird", "criterion": "weird", "severity": "weird", "requirement_ids": ["R-99"],
           "evidence": [{"quote": "Хранить идентификатор вклада", "line": 9}], "problem": "", "scenario": "",
           "impact": "", "recommendation": "", "rewrite": "", "question": "", "blocks": "weird"}
    empty = dict(bad, evidence=[])
    out = C.postprocess(answer(candidates=[bad, empty]), VIEW, REQS)
    [c] = out["candidates"]
    assert (c["kind"], c["criterion"], c["severity"], c["blocks"]) == ("other", "set_consistent", "major", "none")
    assert c["requirement_ids"] == ["R-08"]


def test_glossary_major_gives_terminology_candidate_none_gives_nothing():
    g_major = {"concept": "участник, который распоряжается вкладом",
               "terms": [{"term": "Клиент", "line": 10}, {"term": "держатель счёта", "line": 10}],
               "problem": "Неясно, один ли это человек.", "severity": "major"}
    g_none = {"concept": "вклад", "terms": [{"term": "Вклад", "line": 3}, {"term": "вклада", "line": 5}],
              "problem": "", "severity": "none"}
    g_single = {"concept": "одно", "terms": [{"term": "Вклад", "line": 3}], "problem": "", "severity": "major"}
    out = C.postprocess(answer(glossary=[g_major, g_none, g_single]), VIEW, REQS)
    assert len(out["glossary"]) == 2
    [c] = out["candidates"]
    assert c["kind"] == "terminology" and c["severity"] == "major" and c["origin"] == "glossary"
    assert len(c["evidence"]) == 2
    assert "«Клиент»" in c["title"]


def test_trace_keeps_known_ids_acceptance_only_and_fills_missing():
    raw = [{"requirement_id": "R-02", "verified_by": ["R-07", "R-03", "R-99"], "implemented_by": ["R-08", "R-02"],
            "note": ""},
           {"requirement_id": "R-99", "verified_by": [], "implemented_by": [], "note": "чужой"},
           {"requirement_id": "R-06", "verified_by": [], "implemented_by": [], "note": ""}]
    out = C.postprocess(answer(trace=raw), VIEW, REQS)
    ids = [t["requirement_id"] for t in out["trace"]]
    assert ids == ["R-02", "R-03", "R-04", "R-05", "R-06", "R-08"]
    t2 = out["trace"][0]
    assert t2["verified_by"] == ["R-07"] and t2["implemented_by"] == ["R-08"] and t2["note"] == ""
    t6 = next(t for t in out["trace"] if t["requirement_id"] == "R-06")
    assert t6["note"] == "нет критерия приёмки"
    cov = C.coverage(out["trace"])
    assert cov["total"] == 6 and cov["verified"] == 1
    md = C.coverage_table_md(out["trace"], REQS)
    assert md.startswith("| Требование |") and "R-02 (В-1)" in md and "1 из 6" in md


def test_output_keys_match_contract():
    out = C.postprocess(answer(pair_checks=[pair()]), VIEW, REQS)
    assert {"candidates", "pair_checks", "trace", "glossary"} <= set(out)
    contract_pair = {"a", "b", "subject", "same_subject", "quote_a", "line_a", "quote_b", "line_b", "scenario",
                     "outcome_a", "outcome_b", "verdict"}
    assert contract_pair <= set(out["pair_checks"][0])
    json.dumps(out, ensure_ascii=False)


def test_empty_or_broken_answer_does_not_crash():
    assert C.postprocess({}, VIEW, REQS)["candidates"] == []
    assert C.postprocess(None, VIEW, [])["trace"] == []


class _FakeLLM:
    def __init__(self, data):
        self.data, self.calls = data, []

    def ask(self, stage, system, user, schema, **kw):
        self.calls.append((stage, schema))
        return self.data


class _FakeCtx:
    def __init__(self, data):
        self.view, self.requirements, self.llm = VIEW, REQS, _FakeLLM(data)

    def prompt(self, name, **kw):
        assert name == "consistency"
        return "system", "user"


def test_run_uses_one_call_with_stage_schema():
    ctx = _FakeCtx(answer(pair_checks=[pair()]))
    out = C.run(ctx)
    assert ctx.llm.calls == [("consistency", C.SCHEMA)]
    assert out["candidates"][0]["severity"] == "critical"


BANNED = ["push", "savelimit", "тиын", "порог", "алматы", "ф-1", "ф-2", "ф-3", "ф-4", "alertscontroller",
          "limit_kzt", "48 500", "50 000", "календарный месяц"]


def test_prompt_has_no_words_of_official_document():
    text = PROMPT.read_text(encoding="utf-8").lower()
    for w in BANNED:
        assert w not in text, w


def test_prompt_is_russian():
    text = PROMPT.read_text(encoding="utf-8")
    words = re.findall(r"[A-Za-z][A-Za-z_]{3,}", text)
    allowed = {"subjects", "places", "subject", "pair_checks", "same_subject", "quote_a", "line_a", "quote_b",
               "line_b", "scenario", "outcome_a", "outcome_b", "verdict", "conflict", "compatible", "undefined",
               "kind", "event_conflict", "status_conflict", "boundary_conflict", "unit_mismatch", "contradiction",
               "ambiguity", "incomplete", "title", "impact", "recommendation", "question", "glossary", "concept",
               "terms", "problem", "severity", "major", "minor", "none", "trace", "functional", "nonfunctional",
               "data", "integration", "constraint", "requirement_id", "verified_by", "implemented_by", "note",
               "candidates", "missing_element", "set_consistent", "set_feasible", "set_complete", "modifiable",
               "duplicate", "ranked", "traceable", "traceability", "critical", "requirement_ids", "blocks", "false"}
    stray = {w for w in words if w.lower() not in allowed and w not in allowed}
    assert not stray, stray


@pytest.mark.parametrize("kind", C.TRACE_KINDS)
def test_trace_kinds_are_contract_kinds(kind):
    assert kind in {"functional", "nonfunctional", "data", "integration", "ui", "process", "architecture", "api",
                    "acceptance", "constraint", "goal", "other"}
