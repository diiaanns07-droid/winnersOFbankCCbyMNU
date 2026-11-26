"""verify_report: корректная пара проходит, каждая подмена даёт свой код и не вызывает модель."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import report_builder
import synthetic_reader
from p07_helpers import FIXTURES

from bcc_review import contracts as C
from bcc_review import verification
from bcc_review.verification import main, render_text, summary_counts, verify_report

SOURCE = FIXTURES / "case.md"
LLM_MODULES = ("anthropic", "google.genai", "google.generativeai", "openai")


@pytest.fixture(scope="module")
def case_report() -> dict:
    return report_builder.build_case_md(SOURCE)


def write(tmp_path: Path, report: dict, name: str = "report.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def finding(report: dict, fid: str) -> dict:
    return next(f for f in report["findings"] if f["id"] == fid)


def test_case_report_matches_contract(case_report: dict) -> None:
    C.validate(case_report)
    assert C.evidence_errors(case_report) == []
    statuses = {f["id"]: (f["status"], f["anchor_status"]) for f in case_report["findings"]}
    assert statuses == {"D-1": ("confirmed", "supported"), "D-2": ("confirmed", "supported"),
                        "D-3": ("confirmed", "supported"), "D-4": ("needs_review", "incomplete"),
                        "D-5": ("confirmed", "supported")}
    d4 = finding(case_report, "D-4")
    assert d4["evidence"] == [] and d4["witness"] is None
    assert d4["notes"][0].startswith("number_mismatch")
    audit = case_report["run"]["evidence_audit"]
    assert audit["rejected"] == 1 and audit["checked"] == audit["confirmed"] + audit["ambiguous"] + audit["rejected"]
    assert summary_counts(case_report) == case_report["summary"]


def test_valid_pair_passes(tmp_path: Path, case_report: dict, no_network: list) -> None:
    before = set(sys.modules)
    result = verify_report(write(tmp_path, case_report), SOURCE, reader=synthetic_reader.read)
    assert result["ok"], render_text(result)
    assert result["exit_code"] == 0
    c = result["counts"]
    assert c["unit"] == "evidence"
    assert c["checked"] == c["confirmed"] + c["ambiguous"] + c["rejected"] > 0
    assert c["rejected"] == 0
    assert c["ambiguous"] == 1  # «Клиент получает push» дважды в блоке: верно по координатам
    assert c["counters_checked"] == 13 and c["references_checked"] > 15
    assert c["findings_checked"] == 4 and c["edits_checked"] == 1
    assert result["source"]["matches"] is True
    assert not no_network
    assert not [m for m in set(sys.modules) - before if m.startswith(LLM_MODULES)]
    text = render_text(result)
    assert "ИТОГ: ПРОЙДЕНА" in text and "единица учёта" in text


def _set_quote(r: dict) -> None:
    finding(r, "D-3")["evidence"][0]["quote"] = "Комиссия составляет более 1000 ₸ за операцию"


def _shift_coords(r: dict) -> None:
    ev = finding(r, "D-1")["evidence"][0]
    ev["start"] -= 2
    ev["end"] -= 2


def _loc_line(r: dict) -> None:
    finding(r, "D-1")["evidence"][0]["loc"]["line"] = 40


def _critical_count(r: dict) -> None:
    r["summary"]["by_severity"]["critical"] += 1


def _critical_list(r: dict) -> None:
    r["summary"]["critical_ids"] = ["D-1", "D-2"]


def _status_count(r: dict) -> None:
    r["summary"]["by_status"]["confirmed"] -= 1


def _ready(r: dict) -> None:
    r["verdict"]["development"]["status"] = "ready"


def _partial_ready(r: dict) -> None:
    for f in r["findings"]:
        f["severity"] = "minor" if f["severity"] == "critical" else f["severity"]
    r["summary"] = summary_counts(r)
    r["verdict"]["testing"] = {"status": "ready", "reasons": [], "finding_ids": []}
    r["run"]["status"] = "partial"


def _unknown_block(r: dict) -> None:
    r["requirements"][0]["evidence"][0]["block_id"] = "b9999"


def _out_of_range(r: dict) -> None:
    r["requirements"][0]["evidence"][0]["end"] = 10_000


def _dangling(r: dict) -> None:
    finding(r, "D-3")["req_ids"] = ["R-404"]


def _dangling_question(r: dict) -> None:
    r["test_cases"][0]["open_question_id"] = "Q-404"


def _duplicate(r: dict) -> None:
    r["requirements"][1]["id"] = "R-1"


def _anchor_status(r: dict) -> None:
    finding(r, "D-4")["status"] = "confirmed"
    r["summary"] = summary_counts(r)


def _same_sides(r: dict) -> None:
    w = finding(r, "D-1")["witness"]
    w["evidence_b"] = dict(w["evidence_a"])


def _equal_outcomes(r: dict) -> None:
    w = finding(r, "D-1")["witness"]
    w["outcome_b"] = w["outcome_a"]


def _omission_scope(r: dict) -> None:
    finding(r, "D-2")["inspected_block_ids"] = []


def _audit(r: dict) -> None:
    r["run"]["evidence_audit"]["confirmed"] += 1


def _fact_value(r: dict) -> None:
    r["facts"][0]["value"] = 100000


def _section(r: dict) -> None:
    r["requirements"][0]["section"] = ["Синтетическое ТЗ: порог расходов", "Комиссии"]


def _embedded_block(r: dict) -> None:
    r["document"]["blocks"][4]["text"] += " (правка)"


def _embedded_loc(r: dict) -> None:
    r["document"]["blocks"][2]["loc"]["map"][1][2] = 11


def _schema(r: dict) -> None:
    del r["findings"][0]["meaning_status"]


def _cut_number(r: dict) -> None:
    ev = r["facts"][0]["evidence"][0]
    ev["quote"] = ev["quote"][2:]
    ev["start"] += 2


def _edit(r: dict) -> None:
    r["decisions"][0]["edits"][0]["old"] = "не более 100 ₸"


def _embedded_warnings(r: dict) -> None:
    r["document"]["warnings"] = [{"code": "partial_read", "message": "страница 2 не прочитана"}]


TAMPERS: list[tuple[str, Callable[[dict], None], str]] = [
    ("цитата", _set_quote, "evidence_quote_mismatch"),
    ("координата", _shift_coords, "evidence_offset_mismatch"),
    ("строка", _loc_line, "evidence_loc_mismatch"),
    ("число критичных", _critical_count, "summary_count_mismatch"),
    ("список критичных", _critical_list, "summary_list_mismatch"),
    ("число по статусу", _status_count, "summary_count_mismatch"),
    ("ready при критичном", _ready, "verdict_inconsistent"),
    ("ready при partial", _partial_ready, "verdict_inconsistent"),
    ("блок", _unknown_block, "evidence_unknown_block"),
    ("диапазон", _out_of_range, "evidence_out_of_range"),
    ("ссылка на требование", _dangling, "dangling_reference"),
    ("ссылка на вопрос", _dangling_question, "dangling_reference"),
    ("дубль ID", _duplicate, "duplicate_id"),
    ("confirmed без опоры", _anchor_status, "unsupported_confirmed_finding"),
    ("одна опора у конфликта", _same_sides, "unsupported_confirmed_finding"),
    ("одинаковые исходы", _equal_outcomes, "unsupported_confirmed_finding"),
    ("область пропуска", _omission_scope, "unsupported_confirmed_finding"),
    ("арифметика аудита", _audit, "audit_arithmetic"),
    ("число факта", _fact_value, "fact_value_not_in_quote"),
    ("раздел", _section, "section_mismatch"),
    ("встроенный блок", _embedded_block, "document_block_mismatch"),
    ("встроенная карта строк", _embedded_loc, "document_block_mismatch"),
    ("схема", _schema, "schema_invalid"),
    ("обрезанное число", _cut_number, "evidence_number_boundary"),
    ("правка решения", _edit, "decision_edit_mismatch"),
    ("предупреждения документа", _embedded_warnings, "document_mismatch"),
]


@pytest.mark.parametrize(("label", "tamper", "code"), TAMPERS, ids=[t[0] for t in TAMPERS])
def test_each_tamper_fails_with_clear_code(tmp_path: Path, case_report: dict, no_network: list,
                                           label: str, tamper: Callable[[dict], None], code: str) -> None:
    report = json.loads(json.dumps(case_report))
    tamper(report)
    result = verify_report(write(tmp_path, report), SOURCE, reader=synthetic_reader.read)
    codes = [e["code"] for e in result["errors"]]
    assert not result["ok"], label
    assert result["exit_code"] == C.EXIT_VERIFY_FAILED
    assert code in codes, (label, result["errors"])
    err = next(e for e in result["errors"] if e["code"] == code)
    assert err["message"] and err["message"] != code  # понятная причина по-русски
    assert "ИТОГ: НЕ ПРОЙДЕНА" in render_text(result)
    assert not no_network


def test_changed_source_file_fails(tmp_path: Path, case_report: dict, no_network: list) -> None:
    source = tmp_path / "case.md"
    shutil.copy(SOURCE, source)
    source.write_bytes(source.read_bytes().replace("не более 10".encode(), "не более 11".encode()))
    result = verify_report(write(tmp_path, case_report), source, reader=synthetic_reader.read)
    codes = {e["code"] for e in result["errors"]}
    assert not result["ok"] and result["exit_code"] == C.EXIT_VERIFY_FAILED
    assert {"source_sha_mismatch", "document_id_mismatch"} <= codes
    assert result["counts"]["checked"] == 0 and result["counts"]["skipped"] > 0
    assert result["source"]["matches"] is False
    assert not no_network


def test_partial_read_requires_partial_run(tmp_path: Path, case_report: dict) -> None:
    warning = {"code": "partial_read", "message": "страница 2 не прочитана"}

    def reader(path: str) -> dict:
        return {**synthetic_reader.read(path), "warnings": [warning]}

    report = json.loads(json.dumps(case_report))
    report["document"]["warnings"] = [warning]
    result = verify_report(write(tmp_path, report), SOURCE, reader=reader)
    assert [e["code"] for e in result["errors"]] == ["run_status_inconsistent"]
    report["run"]["status"] = "partial"
    assert verify_report(write(tmp_path, report), SOURCE, reader=reader)["ok"]


def test_source_is_read_again(tmp_path: Path, case_report: dict) -> None:
    calls: list[str] = []

    def reader(path: str) -> dict:
        calls.append(path)
        return synthetic_reader.read(path)

    assert verify_report(write(tmp_path, case_report), SOURCE, reader=reader)["ok"]
    assert calls == [str(SOURCE)]  # оригинал читается заново, а не берётся из отчёта


def test_reader_is_required(tmp_path: Path, case_report: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BCC_REVIEW_READER", raising=False)
    monkeypatch.setattr(verification, "GENERIC_READERS", ())
    monkeypatch.setattr(verification, "READER_BY_SUFFIX", {".md": ("no_such_reader_module", "read")})
    result = verify_report(write(tmp_path, case_report), SOURCE)
    assert not result["ok"] and result["exit_code"] == C.EXIT_ERROR
    assert [e["code"] for e in result["errors"]] == ["reader_unavailable"]


def test_reader_discovery_by_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BCC_REVIEW_READER", raising=False)
    monkeypatch.setattr(verification, "GENERIC_READERS", ())
    monkeypatch.setattr(verification, "READER_BY_SUFFIX", {".pdf": ("synthetic_reader", "read")})
    assert verification.find_reader("x.pdf") is synthetic_reader.read
    assert verification.find_reader("x.docx") is None


def test_unreadable_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = verify_report(bad, SOURCE, reader=synthetic_reader.read)
    assert not result["ok"] and result["errors"][0]["code"] == "report_unreadable"
    missing = verify_report(tmp_path / "nope.json", SOURCE, reader=synthetic_reader.read)
    assert missing["exit_code"] == C.EXIT_ERROR


@pytest.mark.parametrize(
    ("fixture", "fragment", "quote", "bad_loc"),
    [
        ("case.pdf", "Система", "проверку порога по времени UTC+5", {"page": 2}),
        ("case.docx", "максимум", "максимум один push за календарный месяц", {"path": "body/p[1]"}),
    ],
)
def test_pdf_and_docx_reports_pass(tmp_path: Path, no_network: list, fixture: str, fragment: str,
                                   quote: str, bad_loc: dict) -> None:
    pytest.importorskip("pdfplumber" if fixture.endswith(".pdf") else "docx")
    report = report_builder.build_simple(FIXTURES / fixture, fragment, quote)
    C.validate(report)
    result = verify_report(write(tmp_path, report), FIXTURES / fixture, reader=synthetic_reader.read)
    assert result["ok"], render_text(result)
    assert result["counts"]["confirmed"] == result["counts"]["checked"] == 2
    report["findings"][0]["evidence"][0]["loc"] = bad_loc
    bad = verify_report(write(tmp_path, report, "bad.json"), FIXTURES / fixture, reader=synthetic_reader.read)
    assert [e["code"] for e in bad["errors"]] == ["evidence_loc_mismatch"]


def test_main_exit_codes(tmp_path: Path, case_report: dict, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("BCC_REVIEW_READER", "synthetic_reader:read")
    good = write(tmp_path, case_report)
    assert main(["verify", str(good), str(SOURCE)]) == C.EXIT_OK
    assert "ИТОГ: ПРОЙДЕНА" in capsys.readouterr().out
    report = json.loads(json.dumps(case_report))
    _critical_count(report)
    assert main([str(write(tmp_path, report, "bad.json")), str(SOURCE), "--json"]) == C.EXIT_VERIFY_FAILED
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "summary_count_mismatch"
    assert main([str(good)]) == C.EXIT_USAGE
