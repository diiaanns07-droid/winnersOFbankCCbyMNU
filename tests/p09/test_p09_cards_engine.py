"""Стык с движком Max на двух похожих дефектах: compare_reports вызывается движком.

1. Engine.run_compare с каноническими отчётами: загрузчик модулей, ContextBuilder, расширение
   impacted_req_ids и отметка этапа compare — настоящие; №13 и №17 рисуют результат через слоты движка.
2. run_review(..., compare_path=канонический v1, mock_script): вторую редакцию строит сам движок
   (№01 чтение, №04 инвентарь, №06 cross, №07 evidence); транспорт — runtime.mock:MockAdapter.
"""

import hashlib
import json

import pytest

engine = pytest.importorskip("bcc_review.engine", reason="движок Max ещё не в ветке")

from bcc_review.contracts import RunOptions, validate  # noqa: E402
from bcc_review.runtime.context import ContextBuilder  # noqa: E402
from p09_cards import V2_PARAS, cards_v1, cards_v2, mock_script_v2  # noqa: E402
from p09_case import assert_valid_report, by_old, markdown  # noqa: E402
from test_p09_cards import rows  # noqa: E402


def _inputs(tmp_path):
    v1 = tmp_path / "cards_v1.json"
    v1.write_text(json.dumps(cards_v1(), ensure_ascii=False), encoding="utf-8")
    src = tmp_path / "cards_v2.md"
    src.write_text(markdown(V2_PARAS), encoding="utf-8")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == cards_v2()["document"]["id"]
    return v1, src


def test_engine_run_compare_with_canonical_reports(tmp_path):
    v1, src = _inputs(tmp_path)
    cur = cards_v2()
    opts = RunOptions.coerce(
        {"provider": "mock", "compare_path": str(v1), "trace": False, "artifacts_dir": str(tmp_path / "art")}
    )
    eng = engine.Engine(src, tmp_path / "r2.md", opts)
    diff = eng.run_compare(cur, ContextBuilder(cur["document"], cur["requirements"]))
    mod = eng.mods.get("compare_reports")
    assert (mod.origin, mod.path) == ("team", "bcc_review.decisions.diff:compare_reports")
    rec = eng.stats.stages["compare"]
    assert rec.status == "ok" and rec.implementation == "team:bcc_review.decisions.diff:compare_reports"
    assert rows(diff) == [
        ("F-2", "coverage R-1↔R-2", "исправлено в тексте", "text_changed_rechecked"),
        ("F-1", "F-1", "сохранилось", "same_root_cause_severity_changed"),
    ]
    validate(diff, "Diff")
    cur["diff"] = diff
    assert_valid_report(cur)

    # №17 (Markdown) и №13 (HTML) — модули команды через слоты движка
    md_mod, html_mod = eng.mods.get("write_markdown"), eng.mods.get("write_html")
    assert md_mod.origin == "team" and html_mod.origin == "team"
    md = md_mod.func(cur, tmp_path / "r2.md").read_text(encoding="utf-8")
    html = html_mod.func(cur, tmp_path / "r2.html").read_text(encoding="utf-8")
    for text in (md, html):
        assert "Источник исправления К-1 (R-3) → 1.1 (R-1)" in text
        assert "источник Д-1 (R-1) → 2.1 (R-3)" in text


def test_cli_compare_second_edition_built_by_engine(tmp_path):
    v1, src = _inputs(tmp_path)
    script = tmp_path / "script_v2.json"
    script.write_text(json.dumps(mock_script_v2(), ensure_ascii=False), encoding="utf-8")
    opts = {
        "provider": "mock",
        "mock_script": str(script),
        "compare_path": str(v1),
        "use_cache": False,
        "trace": False,
        "artifacts_dir": str(tmp_path / "art"),
    }
    engine.run_review(src, tmp_path / "r2.md", options=opts)
    rep = json.loads((tmp_path / "r2.json").read_text(encoding="utf-8"))
    validate(rep)
    mods = rep["run"]["modules"]
    assert mods["compare_reports"] == "team:bcc_review.decisions.diff:compare_reports"
    assert mods["review_set"] == "team:bcc_review.analysis.cross:review_set"
    assert mods["provider"] == "runtime.mock:MockAdapter"
    assert {(c["req_id"], c["status"]) for c in rep["coverage"]} == {("R-001", "covered"), ("R-003", "conflict")}

    st = by_old(rep["diff"])
    assert st["F-2"][0] == "resolved" and st["F-2"][1]["proof"]["kind"] == "coverage_reconciled"
    assert "покрытие 1.1 (R-001) критерием 1.2 (R-002) — covered (было conflict)" in st["F-2"][1]["reason"]
    assert st["F-1"][0] != "resolved"  # дебетовая не закрыта ни при каком состоянии стыка
    lost = [x for x in rep.get("rejected", []) if "hint_a" in x["reason"]]
    if lost:
        # стык №06 → контракт: кандидат-конфликт с witness.evidence_a/b вместо hint_a/hint_b отклоняется
        # этапом evidence, поэтому дебетовой находки в новом отчёте нет — только покрытие conflict
        assert st["F-1"][0] == "unassessed" and st["F-1"][1]["reason_code"] == "anchor_unchanged"
        assert "Профильный этап по-прежнему отмечает противоречие" in st["F-1"][1]["reason"]
    else:
        assert st["F-1"][0] == "persisting"
