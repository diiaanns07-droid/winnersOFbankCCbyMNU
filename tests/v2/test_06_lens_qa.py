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
    assert lens_qa.SCHEMA["required"] == ["acceptance_checks", "nfr_checks", "candidates", "test_cases"]
    for name in ("row_requirement_id", "row_facts", "rule_requirement_ids", "expected_by_rules", "stated", "verdict"):
        assert name in props, f"поле CONTRACT 2.5 {name}"


def test_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(lens_qa.SCHEMA)
    for f in sorted(QA.glob("*.json")):
        data = _json(f)
        data.setdefault("nfr_checks", [])  # ответы записаны до шага nfr_checks (mock дописывает пустой список)
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
    # рубрика понятности: номер критерия в таблице и собственный номер правила, без ID нарезки
    assert cand["title"] == "Критерий приёмки №1 противоречит правилу П-1"
    assert not re.search(r"R-\d", " ".join(cand[k] for k in ("title", "problem", "scenario", "impact",
                                                              "recommendation", "question")))
    assert cand["scenario"] and cand["impact"] and cand["question"]
    assert "«10 + 5 = 15, ограничено до 12»" in cand["impact"] and "критерию приёмки №1" in cand["impact"]
    assert cand["rewrite"] == "Итог 12" and cand["source"] == "lens:qa"
    assert cand["rewrite_line"] == 30, "«было → стало» заменяет строку приёмки, а не правило"
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
                 requirement_ids=["R-02"], evidence=[{"quote": "Итог показывается быстро", "line": 12}])
    out = lens_qa.postprocess({"acceptance_checks": [_check()], "candidates": [dup, other]}, REQS)
    titles = [c["title"] for c in out["candidates"]]
    assert "Критерий противоречит правилу" not in titles and "Нет метрики" in titles
    assert sum(c["severity"] == "critical" for c in out["candidates"]) == 1


def test_model_critical_is_demoted_only_acceptance_conflict_stays_critical():
    """Critical линзы — только вычисленный конфликт строки приёмки; кандидат модели — не выше major
    (противоречие двух правил — зона проверки набора, серьёзность ставит судья), с подсказкой severity_hint."""
    c = {"title": "Нет метрики", "kind": "unverifiable", "criterion": "verifiable", "severity": "critical",
         "requirement_ids": ["R-02"], "evidence": [{"quote": "Ответ приходит быстро", "line": 12}], "problem": "p",
         "scenario": "s",
         "impact": "i", "recommendation": "r", "rewrite": "", "question": "", "blocks": "none"}
    conflict = dict(c, title="Два исхода", kind="contradiction", criterion="set_consistent")
    out = lens_qa.postprocess({"candidates": [c, conflict]}, REQS)
    sev = {x["title"]: (x["severity"], x["blocks"]) for x in out["candidates"]}
    assert sev["Нет метрики"][0] == "major"
    assert sev["Два исхода"] == ("major", "testing")
    assert all(x["severity_hint"] == "critical" for x in out["candidates"])
    acc = lens_qa.postprocess({"acceptance_checks": [_check()]}, REQS)["candidates"]
    assert [x["severity"] for x in acc] == ["critical"]


def test_schema_field_names_in_texts_become_russian():
    raw = {"title": "Acceptance не покрывает границы", "kind": "missing_element", "criterion": "set_validatable",
           "severity": "major", "requirement_ids": [], "evidence": [], "problem": "Строки acceptance_checks пусты",
           "scenario": "", "impact": "", "recommendation": "", "rewrite": "", "question": "", "blocks": "testing"}
    c = lens_qa.normalize_candidate(raw)
    assert c["title"].startswith("Критерии приёмки") and "acceptance" not in c["problem"].lower()
    t = lens_qa.normalize_test_case({"title": "Граница", "then": "Итог по test cases", "expected_defined": True})
    assert "тест-кейсы" in t["then"]


def test_other_candidates_limited_conflicts_kept():
    """Противоречия модели остаются все; прочих — по одному: покрытие приёмкой, проверяемость, пустой раздел."""
    base = {"requirement_ids": ["R-02"], "evidence": [{"quote": "x", "line": 12}], "problem": "p", "scenario": "s",
            "impact": "i", "recommendation": "r", "rewrite": "", "question": "", "blocks": "testing",
            "severity": "major"}
    raw = [dict(base, title="Неоднозначность", kind="ambiguity", criterion="unambiguous"),
           dict(base, title="Контракт", kind="api_contract", criterion="complete"),
           dict(base, title="Два исхода", kind="contradiction", criterion="set_consistent", severity="critical"),
           dict(base, title="Метрика", kind="unverifiable", criterion="verifiable",
                evidence=[{"quote": "Ответ приходит мгновенно", "line": 12}]),
           dict(base, title="Коды", kind="status_conflict", criterion="set_consistent"),
           dict(base, title="Покрытие", kind="missing_element", criterion="set_validatable")]
    raw.append(dict(base, title="Покрытие-2", kind="missing_element", criterion="set_validatable", severity="minor"))
    raw.append(dict(base, title="Заглушка", kind="placeholder", criterion="complete", requirement_ids=[]))
    raw.append(dict(base, title="Заглушка-2", kind="placeholder", criterion="complete", severity="minor"))
    out = lens_qa.postprocess({"candidates": raw}, REQS)
    assert [c.get("model_title", c["title"]) for c in out["candidates"]] == ["Два исхода", "Метрика", "Коды", "Покрытие",
                                                                         "Заглушка"]
    assert out["candidates"][-1]["severity"] == "minor"  # пустой раздел тестирования — minor
    assert {d["title"] for d in out["dropped"]} == {"Неоднозначность", "Контракт", "Покрытие-2", "Заглушка-2"}
    assert all("не больше 3" in d["reason"] for d in out["dropped"])
    # неоднозначность одного места без своих видов — тоже снимается: это зона аналитика
    only = lens_qa.postprocess({"candidates": [raw[0]]}, REQS)
    assert only["candidates"] == [] and [d["title"] for d in only["dropped"]] == ["Неоднозначность"]


def test_coverage_is_one_minor_remark_with_share_and_closing_tests():
    """Покрытие приёмкой — всегда minor (разбор №18: major на каждом ТЗ, и на чистом); в problem — доля
    проверенных функциональных требований, заголовок — факт, рекомендация — тест-кейсы, закрывающие пробел."""
    cover = {"requirement_ids": ["R-03"], "evidence": [{"quote": "x", "line": 30}], "title": "Покрытие",
             "problem": "Не покрыты границы.", "scenario": "s", "impact": "i", "recommendation": "Дополнить таблицу",
             "rewrite": "", "question": "", "blocks": "testing", "severity": "major", "kind": "missing_element",
             "criterion": "set_validatable"}
    tc = {"requirement_ids": ["R-01"], "title": "Граница", "given": "g", "when": "w", "then": "t", "gap": "",
          "expected_defined": True}
    tests = [tc, dict(tc, gap="граница"), dict(tc, gap="повтор"), dict(tc, gap="отмена")]
    half = lens_qa.postprocess({"acceptance_checks": [_check(verdict="match")], "candidates": [cover],
                                "test_cases": tests}, REQS)
    c = half["candidates"][0]
    assert c["severity"] == "minor" and c["severity_hint"] == "major"
    assert c["problem"].startswith("Строки приёмки проверяют 1 из 2 функциональных требований.")
    assert c["title"] == "Критерии приёмки проверяют 1 из 2 функциональных требований"
    assert c["model_title"] == "Покрытие"
    assert c["recommendation"].startswith("Дополнить таблицу. Непокрытые ветки закрывают тест-кейсы T-02–T-04")
    none = lens_qa.postprocess({"acceptance_checks": [_check(verdict="match", rule_requirement_ids=[],
                                                            rule_evidence=[])],
                                "candidates": [dict(cover)]}, REQS)
    assert none["candidates"][0]["severity"] == "minor", "и при 0 из 2 — minor: тест-кейсы закрывают пробел"
    assert none["candidates"][0]["title"] == "Критерии приёмки проверяют 0 из 2 функциональных требований"
    assert "тест-кейсы" not in none["candidates"][0]["recommendation"], "нет тест-кейсов с gap — нет ссылки"
    # без нарезки доли не посчитать — только серьёзность
    bare = lens_qa.postprocess({"candidates": [cover]})["candidates"][0]
    assert bare["severity"] == "minor" and bare["title"] == "Покрытие"


def test_verifiability_only_vague_words_stay_others_dropped():
    """Модельное «непроверяемо» остаётся только при размытой оценке (major); числовой норматив, цель продукта и
    «не описано, что показать» у функции — снимаются в dropped с причиной (на чистых ТЗ это был только шум)."""
    reqs = [{"id": "R-01", "kind": "goal", "line_start": 5, "line_end": 5},
            {"id": "R-02", "kind": "nonfunctional", "line_start": 20, "line_end": 20}]
    base = {"title": "НФТ", "problem": "p", "scenario": "s", "impact": "i", "recommendation": "r", "rewrite": "",
            "question": "", "blocks": "testing", "severity": "major", "kind": "unverifiable", "criterion": "verifiable",
            "requirement_ids": ["R-02"]}

    def run(quote, line=20, ids=("R-02",), extra=()):
        c = dict(base, evidence=[{"quote": quote, "line": line}], requirement_ids=list(ids))
        return lens_qa.postprocess({"candidates": [c]}, reqs + list(extra))

    def sev(*a, **k):
        out = run(*a, **k)
        return out["candidates"][0]["severity"] if out["candidates"] else "dropped"

    assert sev("Методы отвечают не дольше 2 с для 95 % запросов.") == "dropped"
    assert "числом" in run("Методы отвечают не дольше 2 с для 95 % запросов.")["dropped"][0]["reason"]
    assert sev("Ответ приходит мгновенно.") == "major"
    assert sev("Ответ быстрый, доступность 99,9 %.") == "major"  # размытое слово рядом с числом
    assert sev("Сообщение отправляется в течение минуты после события.") == "major"
    fn = [{"id": "R-03", "kind": "functional", "line_start": 30, "line_end": 30}]
    assert sev("В сообщении указывается причина", line=30, ids=("R-03",), extra=fn) == "dropped"
    assert sev("Экран удобный и понятный", line=30, ids=("R-03",), extra=fn) == "major"
    goal = run("Снизить число ошибок.", line=5, ids=("R-01",))
    assert goal["candidates"] == [] and "цель продукта" in goal["dropped"][0]["reason"]
    assert sev("Снизить число ошибок.", line=20, ids=("R-01",)) == "major"  # цитата из НФТ — не только цель


def test_vague_words_quotes_not_doubled_in_title():
    nfr = {"requirement_id": "R-02", "quote": "Ответ приходит быстро и всегда актуален.", "line": 20, "metric": "",
           "start_end": "", "share": "", "load": "", "vague_words": "«быстро», «всегда актуален»", "rewrite": ""}
    out = lens_qa.postprocess({"nfr_checks": [nfr]}, [{"id": "R-02", "kind": "nonfunctional", "line_start": 20,
                                                       "line_end": 20}])
    title = out["candidates"][0]["title"]
    assert "««" not in title and "»»" not in title and "«быстро»" in title, title


@pytest.mark.parametrize("model", ["sonnet", "haiku"])
def test_official_coverage_one_minor(model):
    """Официальный документ: одно замечание о покрытии (3 строки приёмки на 11 функциональных), minor."""
    out = lens_qa.postprocess(_json(QA / f"official.{model}.json"), _segment("official"))
    cover = [c for c in out["candidates"] if c["kind"] == "missing_element" and c["criterion"] == "set_validatable"]
    assert len(cover) == 1 and cover[0]["severity"] == "minor"
    assert cover[0]["title"].startswith("Критерии приёмки проверяют ")


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
    # приёмка проверяет половину правил и больше — непокрытые ветки на чистом документе только minor
    assert all(c["severity"] == "minor" for c in out["candidates"]
               if c["kind"] == "missing_element" and c["criterion"] == "set_validatable")


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

_TC = [{"requirement_ids": ["R-01"], "title": "Граница", "given": "Дано", "when": "Когда", "then": "Итог 12",
        "gap": "", "expected_defined": True}]


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
    first = {"acceptance_checks": [_check(verdict="match")], "candidates": [], "test_cases": _TC}
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
            "candidates": [], "test_cases": _TC}
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
                                      for r in ids], "candidates": [], "test_cases": _TC if "R-01" in ids else []}

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


# ---------------------------------------------------------------- nfr_checks → замечание о проверяемости

def _nfr(**kw) -> dict:
    base = {"requirement_id": "R-05", "quote": "Сообщение передаётся в течение минуты после события", "line": 20,
            "metric": "в течение минуты", "start_end": "от события до передачи", "share": "", "load": "",
            "vague_words": "", "rewrite": "Сообщение передаётся не позднее 60 с для <уточнить: доля> событий."}
    base.update(kw)
    return base


NFR_REQS = REQS + [{"id": "R-05", "source_id": "", "kind": "nonfunctional", "line_start": 20, "line_end": 20},
                   {"id": "R-06", "source_id": "НФ-2", "kind": "nonfunctional", "line_start": 21, "line_end": 21}]


def test_nfr_without_share_and_load_is_major_from_code():
    model = {"title": "НФТ без метрики", "kind": "unverifiable", "criterion": "verifiable", "severity": "major",
             "requirement_ids": ["R-05"], "evidence": [{"quote": "в течение минуты", "line": 20}], "problem": "p",
             "scenario": "s", "impact": "i", "recommendation": "r", "rewrite": "", "question": "", "blocks": "testing"}
    out = lens_qa.postprocess({"nfr_checks": [_nfr()], "candidates": [model]}, NFR_REQS)
    [c] = out["candidates"]
    assert c["origin"] == "nfr_check" and c["severity"] == "major" and c["kind"] == "unverifiable"
    assert c["requirement_ids"] == ["R-05"] and c["evidence"][0]["line"] == 20
    assert c["title"] == "Норматив «в течение минуты» (строка 20) нельзя проверить: нет доли событий и нагрузки"
    assert "нагрузка" in c["problem"] and c["rewrite"].startswith("Сообщение")
    assert [d["title"] for d in out["dropped"]] == ["НФТ без метрики"], "модельное того же вида — в dropped"


def test_nfr_measurable_gives_no_finding_and_vague_is_major():
    tidy = _nfr(quote="Метод отвечает не дольше 1 с для 95 % запросов", metric="не дольше 1 с",
                start_end="не указано", share="95 % запросов", load="")
    assert lens_qa.postprocess({"nfr_checks": [tidy]}, NFR_REQS)["candidates"] == []
    vague = _nfr(requirement_id="R-06", line=21, quote="Расчёт выполняется мгновенно", metric="", start_end="",
                 vague_words="")
    [c] = lens_qa.postprocess({"nfr_checks": [tidy, vague]}, NFR_REQS)["candidates"]
    assert c["severity"] == "major" and c["title"].startswith("НФ-2: «мгновенн")


def test_nfr_model_vague_words_need_dictionary_or_missing_number():
    """Слабая модель пишет в vague_words обычные уточнения: при числовом нормативе без слов словаря — не размыто;
    пропускная способность («200 операций в секунду») — сама нагрузка; «<уточнить: …>» — элемент не назван."""
    noisy = _nfr(quote="Операция выполняется не дольше 3 с для 95 % запросов без учёта ручной проверки",
                 metric="не дольше 3 с", share="95 % запросов", vague_words="без учёта ручной проверки")
    rate = _nfr(quote="Сервис выдерживает 200 операций в секунду", metric="200 операций в секунду", share="",
                load="", vague_words="выдерживает")
    assert lens_qa.postprocess({"nfr_checks": [noisy, rate]}, NFR_REQS)["candidates"] == []
    vague = _nfr(quote="Сведения отображаются быстро", metric="", vague_words="")
    assert lens_qa.normalize_nfr_check(vague)["vague_words"] == "быстро"
    assert lens_qa.normalize_nfr_check(_nfr(start_end="<уточнить: от запроса до ответа>"))["start_end"] == ""


def test_model_texts_use_document_names_not_internal_ids():
    """Рубрика понятности: в текстах модели ID нарезки и «L038» → номер документа и «строка 38»."""
    idx = {r["id"]: r for r in REQS}
    text = lens_qa.humanize_ids("Строка R-03 противоречит R-01 (L010); код по L163 или L165–L171.", idx)
    assert text == "Критерий приёмки №1 противоречит П-1 (строка 10); код по строке 163 или строки 165–171."


def test_run_asks_again_when_answer_has_only_acceptance_rows():
    """haiku изредка возвращает только acceptance_checks: один повтор за кандидатами и тест-кейсами, строки
    приёмки не переисполняются; всего вызовов — 2."""
    rows = [_check(verdict="match"), _check(row_requirement_id="R-04", row_line=31, verdict="match")]
    rest = {"acceptance_checks": [], "nfr_checks": [], "candidates": [], "test_cases": _TC}
    llm = _LLM([{"acceptance_checks": rows, "nfr_checks": [], "candidates": [], "test_cases": []}, rest])
    out = lens_qa.run(_Ctx(llm, REQS))
    assert [st for st, _ in llm.calls] == ["lens_qa", "lens_qa_rest"]
    assert "строки приёмки уже исполнены" in llm.calls[1][1]
    assert len(out["acceptance_checks"]) == 2 and [t["id"] for t in out["test_cases"]] == ["T-01"]


def test_near_amount_conflict_is_rounding_not_conflict():
    """conflict, где выведенное и заявленное различаются только вычисленной суммой с копейками меньше чем на 1 %
    (ошибка счёта модели, sonnet на чистом ТЗ: 11 903,07 против верных 11 890,36), — match с пометкой; целые
    значения (границы, счёт) и расхождение больше 1 % — остаются conflict."""
    near = lens_qa.near_amount_only
    assert near("К остатку прибавлено 11 903,07 ₸, клиент получил push",
                "К остатку прибавлено 11 890,36 ₸, клиент получил push") == (11903.07, 11890.36)
    assert near("Итог 49 999 ₸, push нет", "Итог 50 000 ₸ и один push") is None  # целые — граница и счёт
    assert near("Возвращено 36 000 ₸ (полная премия)", "Возвращено 32 400 ₸ (90 % премии)") is None  # 10 %
    assert near("Начислено 0,38 ₸, push не отправлен", "Начислено 0,38 ₸, клиент получил push") is None
    assert near("Проценты 120,50 ₸, карта заблокирована, выплата отменена",
                "Проценты 120,40 ₸ зачислены на карту") is None  # остальной текст другой
    raw = _check(verdict="conflict", expected_by_rules="Итог 1 000,05 ₸", stated="Итог 1 000,00 ₸")
    c = lens_qa.normalize_check(raw)
    assert c["verdict"] == "match" and c["near_amount"] == [1000.05, 1000.0]
    assert "меньше 1 %" in c["assumptions"] and "1 000,05" in c["assumptions"]
    out = lens_qa.postprocess({"acceptance_checks": [raw]}, REQS)
    assert not [x for x in out["candidates"] if x.get("origin") == "acceptance_check"]
