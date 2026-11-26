"""Стыковой тест с движком Max: run_review(..., compare_path=пример контракта) вызывает этот модуль.

Прошлый отчёт — ``contracts/examples/minimal_report.json`` (конфликт F-001 между Ф-1 и Ф-2), новая
редакция — тот же документ с исправленным Ф-2. Провайдер mock без сценария даёт прогон partial,
поэтому ни одно замечание не должно закрыться, а причина должна это объяснять.
"""

import json
import pathlib

import pytest

engine = pytest.importorskip("bcc_review.engine", reason="движок Max ещё не в ветке")

from bcc_review.contracts import evidence_errors, validate  # noqa: E402
from bcc_review.decisions.diff import compare_reports  # noqa: E402
from p09_case import by_old  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLE_MD = ROOT / "contracts" / "examples" / "two_linked_requirements.md"
EXAMPLE_JSON = ROOT / "contracts" / "examples" / "minimal_report.json"
OLD_F2 = "следующее достижение вызывает push независимо от истории."
NEW_F2 = "следующее достижение вызывает push, только если в этом календарном месяце push ещё не отправлялся."


def _run(tmp_path, source: pathlib.Path) -> dict:
    out = tmp_path / f"{source.stem}-report.md"
    opts = {
        "provider": "mock",
        "compare_path": str(EXAMPLE_JSON),
        "use_cache": False,
        "trace": False,
        "artifacts_dir": str(tmp_path / "artifacts"),
    }
    engine.run_review(source, out, options=opts)
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


def test_engine_calls_team_module_and_keeps_report_valid(tmp_path):
    src = tmp_path / "v2.md"
    text = EXAMPLE_MD.read_text(encoding="utf-8")
    assert OLD_F2 in text
    src.write_text(text.replace(OLD_F2, NEW_F2), encoding="utf-8")
    rep = _run(tmp_path, src)
    validate(rep)
    assert evidence_errors(rep) == []
    assert rep["run"]["modules"]["compare_reports"].startswith("team:bcc_review.decisions.diff")
    diff = rep["diff"]
    validate(diff, "Diff")
    prev = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    assert diff["previous"]["source_sha256"] == prev["document"]["id"] != diff["current"]["source_sha256"]
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    f1 = next(r["id"] for r in rep["requirements"] if r.get("source_id") == "Ф-1")
    f2 = next(r["id"] for r in rep["requirements"] if r.get("source_id") == "Ф-2")
    assert m["R-01"]["new_ids"] == [f1] and m["R-01"]["changes"] == []
    assert m["R-02"]["new_ids"] == [f2] and m["R-02"]["changes"] == ["reworded"]
    assert f2 in diff["impacted_req_ids"]
    # mock без сценария: решения нет, сценарий не перепроверен — противоречие не закрывается
    status, e = by_old(diff)["F-001"]
    assert status == "unassessed" and e["reason_code"] in ("run_incomplete", "recheck_missing")
    assert e["recheck"]["scenario"] == prev["findings"][0]["witness"]["input"]
    assert "Сравнение с" in pathlib.Path(tmp_path / "v2-report.md").read_text(encoding="utf-8")


def test_engine_same_document_cannot_close(tmp_path):
    src = tmp_path / "same.md"
    src.write_bytes(EXAMPLE_MD.read_bytes())
    rep = _run(tmp_path, src)
    diff = rep["diff"]
    assert diff["previous"]["source_sha256"] == diff["current"]["source_sha256"]
    assert not diff["resolved"]
    if not rep["findings"]:  # замечание пропало при том же тексте — только «нужно подтверждение»
        status, e = by_old(diff)["F-001"]
        assert status == "unassessed" and "SHA-256 совпадает" in e["reason"]


def test_direct_call_matches_engine_on_same_inputs(tmp_path):
    """Модуль — чистая функция: прямой вызов на тех же отчётах даёт те же статусы, что внутри движка."""
    src = tmp_path / "v2.md"
    src.write_text(EXAMPLE_MD.read_text(encoding="utf-8").replace(OLD_F2, NEW_F2), encoding="utf-8")
    rep = _run(tmp_path, src)
    prev = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    cur = dict(rep, diff=None)
    direct = compare_reports(prev, cur)
    for key in ("resolved", "persisting", "introduced", "unassessed"):
        assert [(e["old_ids"], e["new_ids"], e["reason_code"]) for e in direct[key]] == [
            (e["old_ids"], e["new_ids"], e["reason_code"]) for e in rep["diff"][key]
        ]
