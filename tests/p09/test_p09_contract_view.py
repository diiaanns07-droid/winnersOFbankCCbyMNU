"""Стык с контрактом v1, детерминизм, данные для HTML/веб-демо (№13, №15) и CLI."""

import json
import os
import pathlib
import random
import subprocess
import sys

import pytest

from bcc_review.contracts import validate
from bcc_review.decisions.diff import compare_reports, render_markdown, to_view
from p09_case import (
    F2,
    F2_FIXED,
    assert_partition,
    assert_valid_report,
    by_old,
    clone,
    demo_pair,
    document,
    finding,
    issue_checks,
    replace,
    report,
    requirements,
    v1_paras,
    v1_report,
)

GOLDEN = pathlib.Path(__file__).parent / "golden"
SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
UPDATE = os.environ.get("P09_UPDATE_GOLDEN") == "1"


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def test_fixture_reports_satisfy_contract():
    for rep in (v1_report(), v1_report(rules=True, names=("conflict", "dup", "single")), *demo_pair()):
        assert_valid_report(rep)


def test_demo_has_all_statuses_with_reasons():
    prev, cur = demo_pair()
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    status, e = st["F-1"]
    assert status == "resolved" and "Q-001" in e["reason"] and "правка внесена" in e["reason"]
    assert e["decision_refs"][0]["edits_applied"] is True
    assert st["F-2"][0] == "persisting" and st["F-2"][1]["severity_change"] == "raised"
    assert st["F-3"][0] == "unassessed" and st["F-3"][1]["reason_code"] == "obligation_missing"
    assert st["F-4"][0] == "persisting"
    assert st["F-5"][0] == "unassessed" and st["F-5"][1]["reason_code"] == "recheck_missing"
    assert [e["new_ids"] for e in diff["introduced"]] == [["G-3"]]
    assert diff["impacted_req_ids"] == ["S-4", "S-8", "S-6"]


def test_report_with_embedded_diff_is_valid():
    """Стыковой тест: движок кладёт результат в Report.diff, отчёт проходит validate и evidence_errors."""
    prev, cur = demo_pair()
    cur["diff"] = compare_reports(prev, cur)
    assert_valid_report(cur)
    validate(cur["diff"], "Diff")
    assert cur["diff"]["previous"] == {"source_sha256": prev["document"]["id"], "run_id": "run-1"}
    assert cur["diff"]["current"] == {"source_sha256": cur["document"]["id"], "run_id": "run-2"}


def test_previous_report_with_its_own_diff_is_accepted():
    prev, cur = demo_pair()
    prev["diff"] = compare_reports(clone(prev), clone(prev))  # прошлый отчёт сам был сравнением
    base = compare_reports(*demo_pair())
    out = compare_reports(prev, cur)
    for side in ("previous", "current"):
        out["basis"][side]["report_sha256"] = base["basis"][side]["report_sha256"]
    assert _dump(out) == _dump(base)  # поле diff входа на результат не влияет


def test_result_is_deterministic_and_order_independent():
    prev, cur = demo_pair()
    first = _dump(compare_reports(prev, cur))
    assert _dump(compare_reports(clone(prev), clone(cur))) == first
    rnd = random.Random(9)
    for _ in range(5):
        p, c = clone(prev), clone(cur)
        for rep in (p, c):
            for key in ("findings", "requirements", "checks", "decisions", "questions"):
                rnd.shuffle(rep[key])
        shuffled = compare_reports(p, c)
        for side in ("previous", "current"):  # хеш входа честно меняется вместе с порядком списков
            shuffled["basis"][side]["report_sha256"] = json.loads(first)["basis"][side]["report_sha256"]
        assert _dump(shuffled) == first


def test_entries_sorted_by_severity_then_position():
    diff = compare_reports(*demo_pair())
    for key in ("resolved", "persisting", "introduced", "unassessed"):
        ranks = [
            {"critical": 0, "major": 1, "minor": 2}[e["severity"]["new"] or e["severity"]["old"]] for e in diff[key]
        ]
        assert ranks == sorted(ranks), key
        assert [e["id"] for e in diff[key]] == [f"{e['id'].split('-')[0]}-{k}" for k, e in enumerate(diff[key], 1)]


def test_top_level_shape_and_hashes():
    prev, cur = demo_pair()
    diff = compare_reports(prev, cur)
    assert set(diff) == {
        "previous",
        "current",
        "resolved",
        "persisting",
        "introduced",
        "unassessed",
        "impacted_req_ids",
        "warnings",
        "basis",
    }
    assert diff["basis"]["previous"]["source_sha256"] == prev["document"]["id"]
    assert len(diff["basis"]["previous"]["report_sha256"]) == 64
    assert all(set(w) == {"code", "message"} for w in diff["warnings"])


def test_view_rows_for_html_and_web_demo():
    view = to_view(compare_reports(*demo_pair()))
    assert view["summary"] == {"resolved": 1, "persisting": 2, "unassessed": 2, "introduced": 1, "severity_changed": 1}
    statuses = {r["status_ru"] for r in view["previous_findings"]}
    assert statuses <= {"исправлено в тексте", "сохранилось", "нужно подтверждение"}
    assert {r["status_ru"] for r in view["new_findings"]} == {"новое замечание"}
    keys = {"old_quote", "new_quote", "entity", "behavior_change", "decision_ref", "reason", "status_ru", "severity"}
    for r in view["previous_findings"] + view["new_findings"]:
        assert keys <= set(r)
    res = next(r for r in view["previous_findings"] if r["status"] == "resolved")
    assert res["entity"] == "Ф-3 ↔ Ф-4" and res["decision_ref"]["id"] == "Q-001"
    assert res["old_quote"] != res["new_quote"]


def test_markdown_section_lists_old_and_new_separately():
    md = render_markdown(compare_reports(*demo_pair()))
    assert "### Прежние замечания" in md and "### Новые замечания" in md
    assert md.count("| исправлено в тексте |") == 1 and md.count("| нужно подтверждение |") == 2


@pytest.mark.parametrize(
    "name,build",
    [
        ("demo_diff.json", lambda d: _dump(d)),
        ("demo_view.json", lambda d: _dump(to_view(d))),
        ("demo_diff.md", lambda d: render_markdown(d)),
    ],
)
def test_golden_example_for_13_and_15(name, build):
    prev, cur = demo_pair()
    text = build(compare_reports(prev, cur))
    path = GOLDEN / name
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        (GOLDEN / "demo_previous.json").write_text(_dump(prev), encoding="utf-8")
        (GOLDEN / "demo_current.json").write_text(_dump(cur), encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, f"обновите эталон: P09_UPDATE_GOLDEN=1 pytest tests/p09 ({name})"


def _run_cli(*args):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "bcc_review.decisions.diff", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_cli_on_golden_inputs(tmp_path):
    out, view, md = tmp_path / "d.json", tmp_path / "v.json", tmp_path / "d.md"
    proc = _run_cli(GOLDEN / "demo_previous.json", GOLDEN / "demo_current.json", "-o", out, "--view", view, "--md", md)
    assert proc.returncode == 0, proc.stderr
    assert "исправлено в тексте: 1; сохранилось: 2; нужно подтверждение: 2; новые: 1" in proc.stderr
    assert out.read_text(encoding="utf-8") == (GOLDEN / "demo_diff.json").read_text(encoding="utf-8")
    assert json.loads(view.read_text(encoding="utf-8"))["summary"]["resolved"] == 1


def test_cli_reports_bad_input(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    proc = _run_cli(bad, bad)
    assert proc.returncode == 2 and "ожидается Report" in proc.stderr


def test_sparse_reports_do_not_crash():
    """Отчёт без блоков и проверок (например, старый report.json): всё объяснимо, ничего не закрыто."""
    prev = v1_report()
    cur = clone(prev)
    cur["document"] = {"id": "f" * 64, "title": "x", "format": "markdown", "blocks": [], "warnings": []}
    cur["run"]["source_sha256"] = "f" * 64
    cur["requirements"], cur["findings"], cur["checks"] = [], [], []
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert not diff["resolved"] and len(diff["unassessed"]) == 5
    assert any(w["code"] == "no_blocks" for w in diff["warnings"])
    with pytest.raises(TypeError):
        compare_reports([], cur)


def test_contested_weak_candidate_is_order_independent():
    """Две старые находки в одном пункте и одна новая рядом: не склеиваются, новая видна отдельно."""
    pdoc = document(v1_paras())
    olds = [
        finding(
            "F-1",
            pdoc,
            req_ids=["R-2"],
            kind="ambiguity",
            criterion="unambiguous",
            severity="major",
            title="Часовой пояс Алматы не задан",
            quotes=["в Алматы"],
        ),
        finding(
            "F-2",
            pdoc,
            req_ids=["R-2"],
            kind="ambiguity",
            criterion="unambiguous",
            severity="major",
            title="«Проведённая покупка» не определена",
            quotes=["проведённые покупки"],
        ),
    ]
    prev = report(pdoc, requirements(pdoc, v1_paras()), olds)
    paras = replace(v1_paras(), {F2: F2_FIXED})
    cdoc = document(paras)
    new = finding(
        "G-1",
        cdoc,
        req_ids=["R-2"],
        kind="ambiguity",
        criterion="unambiguous",
        severity="major",
        title="Возврат: месяц исходной покупки не определён",
        quotes=["Возврат уменьшает расходы"],
    )
    cur = report(cdoc, requirements(cdoc, paras), [new], checks=issue_checks([new]), run_id="run-2")
    base = _dump(compare_reports(prev, cur))
    swapped = clone(prev)
    swapped["findings"].reverse()
    out = compare_reports(swapped, cur)
    out["basis"]["previous"]["report_sha256"] = json.loads(base)["basis"]["previous"]["report_sha256"]
    assert _dump(out) == base
    diff = json.loads(base)
    assert_partition(diff, prev, cur)
    assert not diff["resolved"] and not diff["persisting"]  # «проведённая покупка» ≠ «возврат»: не склеено
    [intro] = diff["introduced"]
    assert intro["new_ids"] == ["G-1"] and [p["old_id"] for p in intro["possible_old"]] == ["F-2", "F-1"]
    st = by_old(diff)
    assert st["F-2"][1]["candidates"][0]["new_id"] == "G-1" and "G-1" in st["F-2"][1]["reason"]
    # проверка «issue» по Ф-2 от новой находки не даёт закрыть старые даже при правке текста
    assert {st[i][1]["reason_code"] for i in ("F-1", "F-2")} == {"recheck_failed"}
