"""Стыковой тест с контрактом v1 (bcc/integration, contracts/HANDOFF.md @ 3e6b569).

Объекты №08 проверяются тем же кодом, что и в движке: ``bcc_review.contracts``."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema", reason="основная зависимость: pip install -e .[dev]")
C = pytest.importorskip("bcc_review.contracts", reason="контракт v1 (bcc/integration) не подключён")

from bcc_review.decisions import apply_answers, build_questions, parse_answers  # noqa: E402
from bcc_review.decisions._demo import (  # noqa: E402
    EXAMPLES_DIR, SYNTHETIC_DOC, make_scripted_ask, recheck, synthetic_findings, synthetic_requirements,
)
from bcc_review.decisions._doc import load_document, load_markdown  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_fixture_objects_match_contract(doc, findings):
    C.validate(doc, "Document")
    for r in synthetic_requirements(doc):
        C.validate(r, "Requirement")
    for f in findings + recheck(doc):
        C.validate(f, "Finding")


def test_questions_edits_and_decisions_match_contract(doc, findings, questions, src_path, tmp_path):
    for q in questions:
        d = q.to_dict()
        C.validate(d, "Question")
        assert all(isinstance(o, str) for o in d["options"])  # Question.options: list[str]
        for o in d["option_details"]:
            for e in o["edits"]:
                C.validate(e, "Edit")
    res = apply_answers(doc, questions, EXAMPLES_DIR / "answers_team_A.md", findings=findings,
                        output_md=tmp_path / "rev.md", source=src_path)
    assert [d["question_id"] for d in res["decisions"]] == ["Q-01", "Q-02", "Q-03", "Q-04"]
    for d in res["decisions"]:
        C.validate(d, "Decision")
    assert res["decisions"][1]["edits"] == [] and res["decisions"][1]["decision_status"] == "deferred"


def test_full_report_with_p08_sections_is_valid(doc, findings, questions, src_path, tmp_path):
    """Report = пример Max, в который подставлены document/requirements/findings/questions/decisions №08."""
    rep = json.loads((ROOT / "contracts" / "examples" / "minimal_report.json").read_text(encoding="utf-8"))
    res = apply_answers(doc, questions, EXAMPLES_DIR / "answers_team_B.md", findings=findings,
                        output_md=tmp_path / "rev.md", source=src_path)
    rep = copy.deepcopy(rep)
    rep["run"]["source_sha256"] = doc["id"]
    rep["document"] = doc
    rep["requirements"] = synthetic_requirements(doc)
    rep["findings"] = [f for f in findings if f["id"] != "F-08"]  # F-08 — заведомо битая опора
    for k in ("checks", "facts", "coverage", "checklist", "test_cases"):
        rep[k] = []
    rep["questions"] = [q.to_dict() for q in questions]
    rep["decisions"] = res["decisions"]
    C.validate(rep)
    assert C.evidence_errors(rep) == []


def test_parse_answers_entry_point_from_handoff(doc, questions):
    """HANDOFF: parse_answers(path, document) -> list[Decision]."""
    decisions = parse_answers(EXAMPLES_DIR / "answers_team_A.md", doc)
    assert [d.question_id for d in decisions] == ["Q-01", "Q-02", "Q-03", "Q-04"]
    assert len(decisions) == 4 and decisions[0].choice == "A"
    assert all(d.source_sha256 == doc["id"] for d in decisions)
    assert decisions.open_ids == [] and decisions.unknown_ids == []


def test_engine_reader_gives_same_questions():
    try:
        engine_doc = load_document(SYNTHETIC_DOC)
    except RuntimeError:
        pytest.skip("читателя движка нет")
    fallback = load_markdown(SYNTHETIC_DOC)
    if engine_doc == fallback:
        pytest.skip("читатель №01 (bcc_review.readers.text) ещё не влит — используется запасной")
    C.validate(engine_doc, "Document")
    a = build_questions(fallback, synthetic_findings(fallback), make_scripted_ask(fallback))
    b = build_questions(engine_doc, synthetic_findings(engine_doc), make_scripted_ask(engine_doc))
    assert [q.finding_ids for q in a] == [q.finding_ids for q in b]
    assert [[e["old"] for o in q.options for e in o.edits] for q in a] == \
           [[e["old"] for o in q.options for e in o.edits] for q in b]
