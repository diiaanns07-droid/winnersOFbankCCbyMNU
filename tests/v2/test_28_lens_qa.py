"""№28 — линза «Тестировщик»: точность на вычитанных документах (корпус `evaluation/dev`).

Без сети: записанные ответы модели (tests/v2/fixtures/06_qa — сырые ответы haiku на чистых базах корпуса,
официальном документе и ТЗ №18) и синтетические ответы, документ — настоящий (docview).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from bcc_review.v2 import docview  # noqa: E402
from bcc_review.v2.stages import lens_qa  # noqa: E402

QA = ROOT / "tests" / "v2" / "fixtures" / "06_qa"
CORPUS_BASES = ("autopay.base", "cardblock.base", "cashback.base", "transfer_limit.base")


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _corpus_view(case_id: str) -> dict:
    from evaluation.v2 import corpus as cp
    path = next(c["path"] for c in cp.select_cases("md", None) if c["case_id"] == case_id)
    return docview.load(path)


def _coverage(cands: list[dict]) -> list[dict]:
    return [c for c in cands if c["kind"] == "missing_element" and c["criterion"] == "set_validatable"
            or "покрыва" in c["title"].lower() or "проверяют" in c["title"].lower()]


@pytest.mark.parametrize("case", CORPUS_BASES)
def test_mature_corpus_base_has_no_coverage_note(case):
    """Чистая база корпуса (термины, версия, UTC+5, нет заглушек): замечание о покрытии приёмкой — в dropped.
    Код до №28 давал его на каждом из 8 чистых документов корпуса (8 из 11 ложных замечаний линзы, замер 13:00)."""
    view = _corpus_view(case)
    seg = _json(QA / "segments" / f"{case}.json")["requirements"]
    raw = _json(QA / f"{case}.haiku.json")
    out = lens_qa.postprocess(raw, seg, view)
    assert not _coverage(out["candidates"]), [c["title"] for c in out["candidates"]]
    assert any(d["reason"] == lens_qa.COVERAGE_MATURE_REASON for d in out["dropped"])
    assert out["candidates"] == [], [c["title"] for c in out["candidates"]]  # на чистой базе — ни одного замечания
    # без документа — прежнее поведение (одно minor о покрытии)
    old = lens_qa.postprocess(raw, seg)
    assert len(_coverage(old["candidates"])) == 1 and old["candidates"][0]["severity"] == "minor"


@pytest.mark.parametrize("case", ["official"])
def test_immature_official_keeps_coverage_note(case):
    """Официальный документ не вычитан (заглушки, нет версии и терминов): покрытие приёмкой — пункт эталона С18."""
    view = docview.load(ROOT / "release" / "input" / "requirements.md")
    seg = _json(QA / "segments" / "official.json")["requirements"]
    out = lens_qa.postprocess(_json(QA / "official.haiku.json"), seg, view)
    assert len(_coverage(out["candidates"])) == 1
    assert any(c["severity"] == "critical" and c.get("origin") == "acceptance_check" for c in out["candidates"])


@pytest.mark.parametrize("name", ["grace_clean", "qr_clean", "capital_clean", "insurance_clean",
                                  "grace", "qr", "capital", "insurance"])
def test_open2_unchanged_with_document(name):
    """ТЗ №18 (незрелые): с документом линза даёт то же, что и без него — правило зрелости их не задевает."""
    d = _json(QA / "open2" / f"{name}.haiku-w3.json")
    view = docview.load(ROOT / "evaluation" / "v2" / "open2" / name / "source.md")
    with_doc = lens_qa.postprocess(d["responses"][0], d["requirements"], view)
    without = lens_qa.postprocess(d["responses"][0], d["requirements"])
    assert [(c["severity"], c["title"]) for c in with_doc["candidates"]] == \
        [(c["severity"], c["title"]) for c in without["candidates"]]


def _nfr(quote: str, line: int, rid: str = "R-99") -> dict:
    return {"requirement_id": rid, "quote": quote, "line": line, "metric": "10 секунд", "start_end": "после ответа 200",
            "share": "", "load": "", "vague_words": "", "rewrite": ""}


def test_deadline_in_functional_section_is_not_unverifiable():
    """Срок из раздела «Функциональные требования» (БК-5 корпуса) — функциональный предел для каждого события: доля
    и нагрузка не нужны, даже если нарезка пометила требование нефункциональным."""
    view = _corpus_view("cardblock.base")
    line = next(x["n"] for x in view["lines"] if "БК-5" in x["text"])
    quote = "Блокировка вступает в силу не позднее 10 секунд после ответа 200 метода blockCard"
    reqs = [{"id": "R-99", "kind": "nonfunctional", "line_start": line, "line_end": line, "source_id": "БК-5"}]
    out = lens_qa.postprocess({"nfr_checks": [_nfr(quote, line)]}, reqs, view)
    assert not [c for c in out["candidates"] if c.get("origin") == "nfr_check"]
    assert out["nfr_checks"][0]["conditions_from"] == "functional"
    # строка модели сбита на 3 — раздел берётся по найденной цитате, а не по номеру модели
    out = lens_qa.postprocess({"nfr_checks": [_nfr(quote, line + 30)]}, reqs, view)
    assert not [c for c in out["candidates"] if c.get("origin") == "nfr_check"]


def test_deadline_in_nfr_section_still_needs_conditions():
    """Официальный: НФТ «в течение минуты» в разделе нефункциональных — замечание о проверяемости остаётся (С13)."""
    view = docview.load(ROOT / "release" / "input" / "requirements.md")
    line = next(x["n"] for x in view["lines"] if "в течение минуты" in x["text"])
    quote = next(x["text"] for x in view["lines"] if "в течение минуты" in x["text"])
    reqs = [{"id": "R-20", "kind": "nonfunctional", "line_start": line, "line_end": line, "source_id": ""}]
    nfr = {**_nfr(quote, line, "R-20"), "metric": "в течение минуты", "start_end": ""}
    out = lens_qa.postprocess({"nfr_checks": [nfr]}, reqs, view)
    got = [c for c in out["candidates"] if c.get("origin") == "nfr_check"]
    assert len(got) == 1 and got[0]["severity"] == "major"


def test_section_at_bounds():
    view = {"lines": [{"n": 1, "text": "x", "section": "Часть A › Функциональные требования"}]}
    assert lens_qa.section_at(view, 1).endswith("Функциональные требования")
    assert lens_qa.section_at(view, 0) == lens_qa.section_at(view, 5) == lens_qa.section_at(None, 1) == ""
    assert not lens_qa._FUNCTIONAL_SECTION.search("Нефункциональные требования")
    assert lens_qa._FUNCTIONAL_SECTION.search("Функциональные требования")


@pytest.mark.parametrize("case", ["autopay.range_boundary.trigger_at_threshold", "cardblock.range_boundary.days_400_at_30",
                                  "cashback.range_boundary.cap_strict", "transfer_limit.range_boundary.reaching_rejects"])
def test_corpus_mutant_keeps_acceptance_conflict(case):
    """Мутант корпуса (заложена граница в строке приёмки, ответы sonnet): противоречие строки приёмки остаётся
    critical, а лишнее замечание о покрытии на вычитанном документе уходит."""
    view = _corpus_view(case)
    seg = _json(QA / "segments" / f"{case.split('.')[0]}.base.json")["requirements"]
    out = lens_qa.postprocess(_json(QA / f"{case}.sonnet.json"), seg, view)
    assert [c["severity"] for c in out["candidates"]] == ["critical"]
    assert out["candidates"][0]["origin"] == "acceptance_check"


def test_model_candidate_without_quote_goes_to_dropped():
    """Кандидат модели без цитаты — в dropped линзы с причиной (раньше доходил до сверки и отклонялся там)."""
    cand = {"title": "Покрытие", "kind": "missing_element", "criterion": "set_validatable", "severity": "minor",
            "requirement_ids": [], "evidence": [{"quote": " ", "line": 3}], "problem": "п", "scenario": "", "impact": "",
            "recommendation": "", "rewrite": "", "question": "", "blocks": "testing"}
    out = lens_qa.postprocess({"candidates": [cand]}, [])
    assert out["candidates"] == []
    assert [d["reason"] for d in out["dropped"]] == [lens_qa.NO_QUOTE_REASON]


def test_acceptance_row_without_quotes_builds_no_candidate():
    """Строка приёмки `undefined` без цитат строки, заявленного и правила: замечание не строится, только предупреждение."""
    check = {"row_requirement_id": "", "row_quote": "", "row_line": 0, "row_facts": "ф", "assumptions": "",
             "rule_requirement_ids": [], "rule_evidence": [], "derivation": "", "expected_by_rules": "не определено",
             "stated": "", "stated_line": 0, "verdict": "undefined", "conflict_kind": "none", "explanation": "", "fix": ""}
    out = lens_qa.postprocess({"acceptance_checks": [check]}, [])
    assert out["candidates"] == [] and len(out["acceptance_checks"]) == 1
    assert any("без цитат" in w for w in out["warnings"])
