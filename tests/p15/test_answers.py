"""questions.md / answers.md и демонстрационные ответы."""

from __future__ import annotations

import json

from bcc_review.web import devengine
from bcc_review.web.answers import Answer, compose_answers, load_demo_answers, match_demo_answer, parse_answers, read_import, render_questions

from .conftest import CASE, FIXTURES


def test_compose_parse_roundtrip_keeps_provenance_and_multiline():
    answers = [
        Answer("Q-1", "Строка 1\nСтрока 2", "аналитик (веб-форма)", "Вопрос?"),
        Answer("Q-2", "Да", "демонстрационный ответ команды (не решение банка)"),
    ]
    parsed = parse_answers(compose_answers(answers, run_id="r1", source_sha256="ab" * 32))
    assert parsed.meta["run_id"] == "r1"
    assert [(a.qid, a.text, a.provenance) for a in parsed.answers] == [(a.qid, a.text, a.provenance) for a in answers]


def test_questions_md_is_bound_to_report_version(tmp_path):
    report = devengine.run_review(CASE, tmp_path / "report.md", options={"dev_delay": 0})
    text = render_questions(report, "r1")
    assert parse_answers(text).answers == []  # пустые ответы не считаются ответами
    for q in report["questions"]:
        assert f"## {q['id']}" in text and q["prompt"] in text
    imp = read_import(text.encode())
    assert imp.format == "web" and imp.declared_sha256 == report["document"]["id"]


def test_answer_lines_with_hash_survive_roundtrip():
    a = Answer("Q-01", "Первая строка\n## не раздел\n\\ обратная черта", "аналитик", "Вопрос?")
    text = compose_answers([a], run_id="r", source_sha256="c" * 64)
    assert "\n\\## не раздел" in text
    assert parse_answers(text).answers[0].text == a.text
    assert read_import(text.encode()).answers[0].text == a.text


def test_team_demo_answers_match_case_questions(tmp_path):
    report = devengine.run_review(CASE, tmp_path / "report.md", options={"dev_delay": 0})
    demo = load_demo_answers(FIXTURES / "demo_answers.md")
    matched = {q["id"]: match_demo_answer(demo, q) for q in report["questions"]}
    assert matched["Q-01"]["text"].startswith("Приоритет Ф-4")
    assert matched["Q-03"]["text"].startswith("Неверная сумма — 400")
    assert matched["Q-02"]["text"].startswith("Месяц определяется")
    assert matched["Q-04"] is None
    assert all("не решение банка" in m["provenance"] for m in matched.values() if m)


def test_dev_report_is_one_object_in_md_and_json(tmp_path):
    report = devengine.run_review(CASE, tmp_path / "report.md", options={"dev_delay": 0})
    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(report, ensure_ascii=False))
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert all(f["id"] in md for f in report["findings"])
