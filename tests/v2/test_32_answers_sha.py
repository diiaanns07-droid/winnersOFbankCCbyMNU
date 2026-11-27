"""№32: SHA-256 документа в шапке файла ответов — предупреждение, если ответы составлены по другой редакции.

Идея mynbaev1989-cell (код не копируется): файл ответов помнит, к какому документу он написан. Если между отчётом
с вопросами и запуском ``--answers`` документ изменился, номера строк и вопросы могли сместиться — владелец
должен это увидеть, а не получить молча пересмотр по чужим вопросам.
"""
from __future__ import annotations

import json

from bcc_review.v2.stages import recheck

SHA = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
OTHER = "0" * 64

QUESTIONS = [
    {"id": "Q-01", "topic": "Срок хранения", "question": "Сколько дней хранить запись?",
     "options": ["30 дней", "90 дней"], "finding_ids": ["D-01"], "blocking": False},
]
FINDINGS = [
    {"id": "D-01", "title": "Срок хранения не задан", "severity": "major", "kind": "incompleteness",
     "evidence": [{"line_start": 3, "line_end": 3, "quote": "запись хранится"}]},
]


def _report(sha: str = SHA) -> dict:
    return {"findings": FINDINGS, "questions": QUESTIONS, "verdict": {"development": "conditional"},
            "run": {"status": "complete"}, "document": {"file": "tz.md", "sha256": sha}}


def test_header_line_is_parsed_and_not_an_answer():
    text = "\n".join(["# Ответы", *recheck.answers_header("tz.md", SHA), "", "Q-01 [Срок хранения]: B"])
    parsed = recheck.parse_answers_text(text)
    assert parsed["document_sha256"] == SHA
    assert [a["id"] for a in parsed["answers"]] == ["Q-01"]
    assert parsed["decisions"] == []
    assert not parsed.get("unparsed")


def test_short_sha_and_heading_form():
    parsed = recheck.parse_answers_text(f"# Ответы на вопросы по tz.md (SHA-256 {SHA[:12]}…)\n\nQ-01: A\n")
    assert parsed["document_sha256"] == SHA[:12]
    check = recheck.check_document(parsed, {"sha256": SHA}, [])
    assert check["match"] is True


def test_sha_in_answer_text_is_ignored():
    # хеш внутри ответа владельца — не шапка (строки ответа не «>» и не «#»)
    parsed = recheck.parse_answers_text(f"Q-01: свой текст, SHA-256 {OTHER}\n")
    assert "document_sha256" not in parsed


def test_json_forms():
    for data in ({"document_sha256": SHA, "answers": {"Q-01": "B"}},
                 {"sha256": SHA.upper(), "Q-01": "B"},
                 {"document": {"file": "tz.md", "sha256": SHA}, "answers": [{"id": "Q-01", "answer": "B"}]}):
        parsed = recheck.parse_answers_json(data)
        assert parsed["document_sha256"] == SHA, data
        assert [a["id"] for a in parsed["answers"]] == ["Q-01"]
    assert "document_sha256" not in recheck.parse_answers_json({"sha256": "не хеш", "Q-01": "B"})


def test_check_document_cases():
    w: list[str] = []
    assert recheck.check_document({}, {"sha256": SHA}, w)["match"] is None and not w  # старый файл — молча
    assert recheck.check_document({"document_sha256": SHA}, {"sha256": SHA}, w)["match"] is True and not w
    res = recheck.check_document({"document_sha256": OTHER}, {"file": "tz.md", "sha256": SHA}, w)
    assert res["match"] is False
    assert len(w) == 1 and "другой редакции" in w[0] and OTHER[:12] in w[0] and SHA[:12] in w[0]


def test_apply_answers_warns_on_changed_document(tmp_path):
    ans = tmp_path / "answers.md"
    ans.write_text("\n".join([*recheck.answers_header("tz.md", OTHER), "Q-01: ?"]), encoding="utf-8")
    out = recheck.apply_answers(None, _report(), str(ans))
    clar = out["clarification"]
    assert clar["answers_document"]["match"] is False
    assert any("другой редакции" in x for x in clar["warnings"])
    md = recheck.render_markdown(clar, out["findings_after"])
    assert "Ответы составлены по другой редакции документа" in md


def test_apply_answers_same_document_no_warning(tmp_path):
    ans = tmp_path / "answers.json"
    ans.write_text(json.dumps({"document_sha256": SHA, "answers": {"Q-01": "?"}}), encoding="utf-8")
    clar = recheck.apply_answers(None, _report(), str(ans))["clarification"]
    assert clar["answers_document"]["match"] is True
    assert not any("другой редакции" in x for x in clar["warnings"])
    assert "другой редакции" not in recheck.render_markdown(clar)


def test_next_round_file_carries_sha_and_round_trips(tmp_path):
    ans = tmp_path / "answers.md"
    ans.write_text("Q-01: не знаю\n", encoding="utf-8")
    clar = recheck.apply_answers(None, _report(), str(ans))["clarification"]
    assert clar["answers_document"]["match"] is None  # в первом файле SHA не было
    text = recheck.render_next_answers(clar, "tz.md", "report.md", SHA)
    assert f"SHA-256 {SHA}" in text
    assert "python -m bcc_review tz.md report.md" in text
    again = recheck.parse_answers_text(text)
    assert again["document_sha256"] == SHA
    # следующий круг по изменённому документу — предупреждение
    w: list[str] = []
    assert recheck.check_document(again, {"sha256": OTHER}, w)["match"] is False and w


def test_next_round_from_run_modes_has_sha(tmp_path):
    from bcc_review.v2.stages import revise

    ans = tmp_path / "answers.md"
    ans.write_text("Q-01: решим позже\n", encoding="utf-8")
    out = revise.run_modes(None, _report(), answers=str(ans), report_path=tmp_path / "report.md")
    path = tmp_path / "report.answers-next.md"
    assert out["clarification"]["next_answers_file"] == str(path)
    assert recheck.answers_sha(path.read_text(encoding="utf-8")) == SHA


def test_interactive_header_of_22_is_read():
    # шапка файла ответов из --interactive №22 (`__main__.write_answers_file`, adec09c6): 12 знаков и «…»
    text = (f"> Документ: tz.md; SHA-256 {SHA[:12]}…; файл можно поправить и передать снова: --answers этот_файл.\n\n"
            "Q-01 [Срок хранения]: B — 90 дней\n")
    parsed = recheck.parse_answers_text(text)
    assert parsed["document_sha256"] == SHA[:12]
    assert recheck.check_document(parsed, {"sha256": SHA}, [])["match"] is True
    w: list[str] = []
    assert recheck.check_document(parsed, {"sha256": OTHER}, w)["match"] is False and w
