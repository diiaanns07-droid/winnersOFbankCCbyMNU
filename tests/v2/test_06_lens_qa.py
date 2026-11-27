"""№06 — линза «Тестировщик»: постобработка acceptance_checks, кандидаты, тест-кейсы, промпт.

Без сети: проверяется код на записанных ответах модели (tests/v2/fixtures/06_qa/*.json — сырые ответы
claude -p на официальном документе и корпусе evaluation/dev) и на синтетических ответах.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import lens_qa  # noqa: E402

FIX = ROOT / "tests" / "v2" / "fixtures"
QA = FIX / "06_qa"
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "lens_qa.md"


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _segment(case: str) -> list[dict]:
    """Нарезка, с которой записаны ответы модели (копия из bcc/v2 f26f06a): №04 меняет свои фикстуры, ID сдвигаются."""
    return _json(QA / "segments" / f"{case}.json")["requirements"]


def _check(**kw) -> dict:
    base = {"row_requirement_id": "R-03", "row_quote": "Значение 10 | Добавить 5", "row_line": 30,
            "row_facts": "Было 10, добавлено 5.", "assumptions": "", "rule_requirement_ids": ["R-01"],
            "rule_evidence": [{"quote": "Итог не превышает 12", "line": 10}],
            "expected_by_rules": "10 + 5 = 15, ограничено до 12", "stated": "Итог 15", "stated_line": 30,
            "verdict": "conflict", "conflict_kind": "boundary_conflict",
            "explanation": "Правило ограничивает итог 12.", "fix": "Итог 12"}
    base.update(kw)
    return base


REQS = [{"id": "R-01", "source_id": "П-1", "kind": "functional", "line_start": 10, "line_end": 10},
        {"id": "R-02", "source_id": "", "kind": "functional", "line_start": 12, "line_end": 12},
        {"id": "R-03", "source_id": "Критерии, строка 1", "kind": "acceptance", "line_start": 30, "line_end": 30},
        {"id": "R-04", "source_id": "Критерии, строка 2", "kind": "acceptance", "line_start": 31, "line_end": 31}]


# ---------------------------------------------------------------- схема и промпт

def test_schema_reasoning_order():
    props = list(lens_qa.ACCEPTANCE_CHECK_SCHEMA["properties"])
    order = [props.index(k) for k in ("row_facts", "rule_requirement_ids", "expected_by_rules", "stated", "verdict")]
    assert order == sorted(order), "ожидаемый результат по правилам должен выводиться до заявленного"
    assert lens_qa.SCHEMA["required"] == ["acceptance_checks", "candidates", "test_cases"]
    for name in ("row_requirement_id", "row_facts", "rule_requirement_ids", "expected_by_rules", "stated", "verdict"):
        assert name in props, f"поле CONTRACT 2.5 {name}"


def test_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(lens_qa.SCHEMA)
    for f in sorted(QA.glob("*.json")):
        data = _json(f)
        for c in data["candidates"]:  # try_prompt.py дописывает найденную строку цитаты
            for e in c["evidence"]:
                e.pop("verified_line", None)
        jsonschema.validate(data, lens_qa.SCHEMA)


FORBIDDEN = ["push", "savelimit", "тиын", "порог", "алмат", "уведомлен", "кэшбэк", "лимит", "карт",
             "покупк", "держател", "расход", "счётчик", "alerts", "limit_kzt", "cardid", "₸", "тенге"]


def test_prompt_has_no_document_words():
    text = PROMPT.read_text(encoding="utf-8").lower()
    hits = [w for w in FORBIDDEN if w in text]
    assert not hits, f"слова конкретного ТЗ в промпте: {hits}"
    assert not re.search(r"\bф-\d", text) and not re.search(r"\b(кб|ап|бк|лп)-\d", text)


def test_prompt_is_russian():
    text = PROMPT.read_text(encoding="utf-8")
    prose = re.sub(r"`[^`]*`", "", text)
    fields = {"JSON"}
    for sch in (lens_qa.SCHEMA, lens_qa.ACCEPTANCE_CHECK_SCHEMA, lens_qa.CANDIDATE_SCHEMA, lens_qa.TEST_CASE_SCHEMA):
        for k in sch["properties"]:
            fields |= set(k.split("_"))
    latin = [w for w in re.findall(r"[A-Za-z]{4,}", prose) if w not in fields]
    assert not latin, f"английские слова в тексте промпта: {latin[:10]}"


# ---------------------------------------------------------------- acceptance_checks → кандидаты

def test_conflict_becomes_critical_with_both_quotes():
    out = lens_qa.postprocess({"acceptance_checks": [_check()]}, REQS)
    [cand] = out["candidates"]
    assert cand["severity"] == "critical" and cand["kind"] == "boundary_conflict"
    assert cand["criterion"] == "set_consistent" and cand["blocks"] == "both"
    assert cand["requirement_ids"] == ["R-03", "R-01"]
    lines = [e["line"] for e in cand["evidence"]]
    assert 10 in lines and 30 in lines, "цитата правила и цитата строки приёмки"
    assert "R-01 (П-1)" in cand["title"] and "R-03" in cand["title"]
    assert cand["scenario"] and cand["impact"] and cand["question"]
    assert cand["rewrite"] == "Итог 12" and cand["source"] == "lens:qa"
    assert cand["origin"] == "acceptance_check" and cand["acceptance_row"] == "R-03"


def test_undefined_becomes_major_and_match_gives_nothing():
    checks = [_check(verdict="undefined", conflict_kind="none"),
              _check(row_requirement_id="R-04", row_line=31, stated_line=31, verdict="match", fix="ненужное")]
    out = lens_qa.postprocess({"acceptance_checks": checks}, REQS)
    [cand] = out["candidates"]
    assert cand["severity"] == "major" and cand["kind"] == "incomplete" and cand["blocks"] == "testing"
    assert out["acceptance_checks"][1]["fix"] == "" and out["acceptance_checks"][1]["conflict_kind"] == "none"


def test_conflict_without_rule_quote_is_not_a_conflict():
    out = lens_qa.postprocess({"acceptance_checks": [_check(rule_evidence=[])]}, REQS)
    assert out["acceptance_checks"][0]["verdict"] == "undefined"
    assert all(c["severity"] != "critical" for c in out["candidates"])


def test_conflict_with_identical_expected_is_match():
    out = lens_qa.postprocess({"acceptance_checks": [_check(expected_by_rules="Итог 15.", stated="итог 15")]}, REQS)
    assert out["acceptance_checks"][0]["verdict"] == "match" and out["candidates"] == []


def test_conflict_kind_defaults_to_contradiction():
    out = lens_qa.postprocess({"acceptance_checks": [_check(conflict_kind="none")]}, REQS)
    assert out["candidates"][0]["kind"] == "contradiction"


def test_rows_keyed_by_line_and_resolved_by_line():
    """Без таблицы требований модель даёт всем строкам один «ID» — строки не должны теряться."""
    checks = [_check(row_requirement_id="б/н", row_line=30, verdict="match"),
              _check(row_requirement_id="б/н", row_line=31, stated_line=31)]
    out = lens_qa.postprocess({"acceptance_checks": checks}, REQS)
    assert [c["row_requirement_id"] for c in out["acceptance_checks"]] == ["R-03", "R-04"]
    assert out["warnings"] == []
    no_table = lens_qa.postprocess({"acceptance_checks": checks}, None)
    assert len(no_table["acceptance_checks"]) == 2
    assert "в строке 31" in no_table["candidates"][0]["title"]


def test_line_wins_over_model_id():
    out = lens_qa.postprocess({"acceptance_checks": [_check(row_requirement_id="R-04", row_line=30)]}, REQS)
    assert out["acceptance_checks"][0]["row_requirement_id"] == "R-03"


def test_recorded_answers_survive_resegmentation():
    """Текущая нарезка №04 (другие ID): строки приёмки всё равно сопоставляются по номеру строки."""
    reqs = _json(FIX / "official" / "segment.json")["requirements"]
    out = lens_qa.postprocess(_json(QA / "official.sonnet.json"), reqs)
    rows = {r["id"] for r in reqs if r["kind"] == "acceptance"}
    assert {c["row_requirement_id"] for c in out["acceptance_checks"]} == rows
    assert sum(c.get("origin") == "acceptance_check" for c in out["candidates"]) == 1


def test_duplicate_row_dropped_and_missing_row_reported():
    out = lens_qa.postprocess({"acceptance_checks": [_check(), _check()]}, REQS)
    assert len(out["acceptance_checks"]) == 1
    assert any("дважды" in w for w in out["warnings"])
    assert any("R-04" in w and "не исполнена" in w for w in out["warnings"])


def test_model_duplicate_of_acceptance_conflict_removed():
    dup = {"title": "Критерий противоречит правилу", "kind": "event_conflict", "criterion": "set_consistent",
           "severity": "critical", "requirement_ids": ["R-03", "R-01"], "evidence": [{"quote": "Итог 15", "line": 30}],
           "problem": "p", "scenario": "s", "impact": "i", "recommendation": "r", "rewrite": "", "question": "",
           "blocks": "both"}
    other = dict(dup, title="Нет метрики", kind="unverifiable", criterion="verifiable", severity="major",
                 requirement_ids=["R-02"])
    out = lens_qa.postprocess({"acceptance_checks": [_check()], "candidates": [dup, other]}, REQS)
    titles = [c["title"] for c in out["candidates"]]
    assert "Критерий противоречит правилу" not in titles and "Нет метрики" in titles
    assert sum(c["severity"] == "critical" for c in out["candidates"]) == 1


def test_non_conflict_critical_from_model_is_demoted():
    c = {"title": "Нет метрики", "kind": "unverifiable", "criterion": "verifiable", "severity": "critical",
         "requirement_ids": ["R-02"], "evidence": [{"quote": "x", "line": 12}], "problem": "p", "scenario": "s",
         "impact": "i", "recommendation": "r", "rewrite": "", "question": "", "blocks": "none"}
    conflict = dict(c, title="Два исхода", kind="contradiction", criterion="set_consistent")
    out = lens_qa.postprocess({"candidates": [c, conflict]}, REQS)
    sev = {x["title"]: (x["severity"], x["blocks"]) for x in out["candidates"]}
    assert sev["Нет метрики"][0] == "major"
    assert sev["Два исхода"] == ("critical", "testing")


# ---------------------------------------------------------------- тест-кейсы

def test_test_cases_numbered_capped_and_undefined_marked():
    tc = {"requirement_ids": ["R-01"], "title": "Граница", "given": "Значение 12", "when": "Добавить 1",
          "then": "Итог 12", "gap": "", "expected_defined": True}
    raw = [dict(tc, title=f"Тест {i}") for i in range(17)]
    raw[1] = dict(tc, then="Код ответа", expected_defined=False)
    raw[2] = dict(tc, then="Итог 12. Не определено требованиями: код ответа", expected_defined=True)
    out = lens_qa.postprocess({"test_cases": raw}, REQS)
    tests = out["test_cases"]
    assert len(tests) == lens_qa.MAX_TEST_CASES and [t["id"] for t in tests[:3]] == ["T-01", "T-02", "T-03"]
    assert list(tests[0])[0] == "id"
    assert tests[1]["then"].startswith("Не определено требованиями") and not tests[1]["expected_defined"]
    assert not tests[2]["expected_defined"]
    assert any(f"оставлено {lens_qa.MAX_TEST_CASES}" in w for w in out["warnings"])


# ---------------------------------------------------------------- записанные ответы модели

@pytest.mark.parametrize("model", ["sonnet", "haiku"])
def test_official_k1_found_via_acceptance_checks(model):
    """К1: строка приёмки 2 (L64) противоречит правилу отнесения операции к периоду (L38)."""
    reqs = _segment("official")
    out = lens_qa.postprocess(_json(QA / f"official.{model}.json"), reqs)
    verdicts = {c["row_requirement_id"]: c["verdict"] for c in out["acceptance_checks"]}
    assert verdicts == {"R-13": "match", "R-14": "conflict", "R-15": "match"}
    k1 = [c for c in out["candidates"] if c.get("origin") == "acceptance_check"]
    assert len(k1) == 1 and k1[0]["severity"] == "critical"
    assert {"R-14", "R-06"} <= set(k1[0]["requirement_ids"])
    assert {38, 64} <= {e["line"] for e in k1[0]["evidence"]}
    assert out["warnings"] == [] or all("тест-кейсов" in w for w in out["warnings"])
    assert 10 <= len(out["test_cases"]) <= lens_qa.MAX_TEST_CASES


@pytest.mark.parametrize("run", [1, 2, 3])
def test_official_k1_on_weak_model_stage_runs(run):
    """Вторая волна: этап `stage lens_qa` на haiku, три прогона без кэша — К1 critical, один вызов, без обрезки."""
    st = _json(QA / "stage" / f"official.haiku-w2-{run}.json")
    assert st["status"] == "ok" and st["calls"] == 1
    out = st["output"]
    verdicts = {c["row_line"]: c["verdict"] for c in out["acceptance_checks"]}
    assert verdicts == {63: "match", 64: "conflict", 65: "match"}
    k1 = [c for c in out["candidates"] if c.get("origin") == "acceptance_check"]
    assert len(k1) == 1 and k1[0]["severity"] == "critical"
    assert {38, 64} <= {e["line"] for e in k1[0]["evidence"]}
    assert all(c["severity"] != "critical" for c in out["candidates"]
               if c["kind"] not in lens_qa.CONFLICT_KINDS + ["incorrect"])


@pytest.mark.parametrize("case", ["autopay.base", "cardblock.base", "cashback.base", "transfer_limit.base"])
def test_clean_bases_have_no_conflicts(case):
    reqs = _segment(case)
    out = lens_qa.postprocess(_json(QA / f"{case}.haiku.json"), reqs)
    assert out["acceptance_checks"], "строки приёмки исполнены"
    assert all(c["verdict"] == "match" for c in out["acceptance_checks"])
    assert not lens_qa.missing_rows(out["acceptance_checks"], reqs)
    assert all(c["severity"] != "critical" for c in out["candidates"])


@pytest.mark.parametrize("case,line", [("autopay.range_boundary.trigger_at_threshold", 46),
                                       ("cashback.range_boundary.cap_strict", 48),
                                       ("transfer_limit.range_boundary.reaching_rejects", 41),
                                       ("cardblock.range_boundary.days_400_at_30", 42)])
def test_range_boundary_mutants_found(case, line):
    out = lens_qa.postprocess(_json(QA / f"{case}.sonnet.json"))
    conflicts = [c for c in out["acceptance_checks"] if c["verdict"] == "conflict"]
    assert [c["row_line"] for c in conflicts] == [line]
    crit = [c for c in out["candidates"] if c.get("origin") == "acceptance_check"]
    assert crit and crit[0]["severity"] == "critical" and crit[0]["kind"] == "boundary_conflict"


# ---------------------------------------------------------------- run(ctx) на поддельном контексте

class _LLM:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def ask(self, stage, system, user, schema, **kw):
        self.calls.append((stage, user))
        self.kw = kw
        return self.answers.pop(0)


class _Ctx:
    def __init__(self, llm, requirements):
        self.llm, self.requirements = llm, requirements

    def prompt(self, name, **kw):
        assert name == "lens_qa"
        return "system", "user"


def test_run_retries_missing_rows_once():
    first = {"acceptance_checks": [_check(verdict="match")], "candidates": [], "test_cases": []}
    second = {"acceptance_checks": [_check(row_requirement_id="R-04", row_line=31, stated_line=31)],
              "candidates": [], "test_cases": []}
    llm = _LLM([first, second])
    out = lens_qa.run(_Ctx(llm, REQS))
    assert len(llm.calls) == 2 and "R-04" in llm.calls[1][1]
    assert [c["row_requirement_id"] for c in out["acceptance_checks"]] == ["R-03", "R-04"]
    assert out["warnings"] == [] and out["candidates"][0]["severity"] == "critical"


def test_run_without_missing_rows_makes_one_call():
    full = {"acceptance_checks": [_check(verdict="match"), _check(row_requirement_id="R-04", row_line=31,
                                                                  verdict="match")],
            "candidates": [], "test_cases": []}
    llm = _LLM([full])
    out = lens_qa.run(_Ctx(llm, REQS))
    assert len(llm.calls) == 1 and out["candidates"] == []
    # лимит ответа сразу 32 000: на haiku 16 000 включают рассуждение, обрезанная попытка стоит целого вызова
    assert llm.kw.get("max_output_tokens") == lens_qa.MAX_OUTPUT_TOKENS == 32000


def test_other_topic_both_acceptance_conflicts_found():
    """Документ другой тематики (release/input/other_topic_cashback.md): D1 — строка 2 приёмки ↔ правило окна
    выбора (L39 ↔ L19), D2 — строка 3 превышает месячный потолок (L40 ↔ L20)."""
    out = lens_qa.postprocess(_json(QA / "other_topic_cashback.sonnet.json"))
    verdicts = {c["row_line"]: c["verdict"] for c in out["acceptance_checks"]}
    assert verdicts == {38: "match", 39: "conflict", 40: "conflict"}
    crit = [c for c in out["candidates"] if c.get("origin") == "acceptance_check"]
    assert len(crit) == 2 and all(c["severity"] == "critical" for c in crit)
    assert {19, 39} <= {e["line"] for e in crit[0]["evidence"]}
    assert {20, 40} <= {e["line"] for e in crit[1]["evidence"]}


def test_run_batches_many_acceptance_rows():
    reqs = [{"id": f"R-{i:02d}", "source_id": "", "kind": "acceptance", "line_start": 100 + i, "line_end": 100 + i}
            for i in range(1, 24)]

    def answer(ids):
        return {"acceptance_checks": [_check(row_requirement_id=r, row_line=100 + int(r[2:]), verdict="match")
                                      for r in ids], "candidates": [], "test_cases": []}

    ids = [r["id"] for r in reqs]
    llm = _LLM([answer(ids[:10]), answer(ids[10:20]), answer(ids[20:])])
    out = lens_qa.run(_Ctx(llm, reqs))
    assert len(llm.calls) == 3
    assert "R-01" in llm.calls[0][1] and "13 строк" in llm.calls[0][1]
    assert "R-11" in llm.calls[1][1] and "R-21" in llm.calls[2][1]
    assert len(out["acceptance_checks"]) == 23 and out["warnings"] == []


def test_run_survives_failed_extra_call():
    class _Failing(_LLM):
        def ask(self, stage, system, user, schema, **kw):
            if self.calls:
                self.calls.append((stage, user))
                raise RuntimeError("перегрузка")
            return super().ask(stage, system, user, schema)

    llm = _Failing([{"acceptance_checks": [_check(verdict="match")], "candidates": [], "test_cases": []}])
    out = lens_qa.run(_Ctx(llm, REQS))
    assert len(out["acceptance_checks"]) == 1
    assert any("перегрузка" in w for w in out["warnings"])


def test_run_truncated_main_answer_falls_back_to_split_calls():
    from bcc_review.v2.llm import Truncated

    class _Trunc(_LLM):
        def ask(self, stage, system, user, schema, **kw):
            self.calls.append((stage, user))
            if stage == "lens_qa":
                raise Truncated(stage)
            if stage == "lens_qa_short":
                assert "пустой список" in user
                return {"acceptance_checks": [], "candidates": [], "test_cases": [
                    {"requirement_ids": ["R-01"], "title": "Граница", "given": "Значение 12", "when": "Добавить 1",
                     "then": "Итог 12", "gap": "", "expected_defined": True}]}
            return {"acceptance_checks": [_check(verdict="match"), _check(row_requirement_id="R-04", row_line=31,
                                                                          stated_line=31)],
                    "candidates": [], "test_cases": []}

    warned: list[str] = []
    ctx = _Ctx(_Trunc([]), REQS)
    ctx.warn = warned.append
    out = lens_qa.run(ctx)
    assert [s for s, _ in ctx.llm.calls] == ["lens_qa", "lens_qa_short", "lens_qa_rows"]
    assert len(out["acceptance_checks"]) == 2 and out["test_cases"][0]["id"] == "T-01"
    assert out["_partial"] is True and any("обрезан" in w for w in warned)
    assert out["candidates"][0]["severity"] == "critical"


def test_provider_error_about_output_limit_counts_as_truncation():
    from bcc_review.v2.llm import LLMError

    class _CliLimit(_LLM):
        def ask(self, stage, system, user, schema, **kw):
            self.calls.append((stage, user))
            if stage == "lens_qa":
                raise LLMError(stage, "unknown", "claude -p: API Error: Claude's response exceeded the 16000 "
                                                 "output token maximum.")
            return {"acceptance_checks": [_check(verdict="match"), _check(row_requirement_id="R-04", row_line=31,
                                                                          stated_line=31, verdict="match")]
                    if stage == "lens_qa_rows" else [], "candidates": [], "test_cases": []}

    out = lens_qa.run(_Ctx(_CliLimit([]), REQS))
    assert len(out["acceptance_checks"]) == 2 and out["_partial"] is True


def test_other_provider_errors_are_not_swallowed():
    from bcc_review.v2.llm import LLMError

    class _Down(_LLM):
        def ask(self, stage, system, user, schema, **kw):
            raise LLMError(stage, "network", "соединение разорвано")

    with pytest.raises(LLMError):
        lens_qa.run(_Ctx(_Down([]), REQS))
