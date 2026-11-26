"""Два похожих дефекта, исправлен один: дебетовые и корпоративные карты.

Обе находки названы одинаково и цитируют одинаковый текст. Тождество задают источник (пункт правила
и его критерий приёмки), условие (witness.input) и исход. На коде 6780abf корпоративная находка
«сливалась» с сохранившейся дебетовой: её цитата после правки К-1 осталась только в дебетовом
правиле, и поиск опоры уходил в чужой раздел (см. test_old_code_merged_corporate_into_debit).
"""

import json
import random

import pytest

from bcc_review.decisions.diff import compare_reports, render_markdown, to_view
from p09_cards import (
    K_INPUT,
    Q_ACC,
    Q_FIX,
    Q_RULE,
    TITLE,
    cards_v1,
    cards_v2,
    clone,
    v2_corporate_unreadable,
    v2_foreign_failure,
    v2_profile_failed,
    v2_profile_pair_missing,
)
from p09_case import assert_partition, assert_valid_report, by_old


def rows(diff: dict) -> list[tuple]:
    """Строки «старая находка → новая находка или доказательство → статус → основание»."""
    out = []
    for key in ("resolved", "persisting", "unassessed", "introduced"):
        for e in diff[key]:
            proof = e.get("proof") or {}
            right = ", ".join(e["new_ids"]) or ", ".join(proof.get("check_refs") or []) or "—"
            out.append((", ".join(e["old_ids"]) or "—", right, e["status_ru"], e["reason_code"]))
    return out


def test_canonical_reports_are_valid_and_findings_look_identical():
    v1, v2 = cards_v1(), cards_v2()
    assert_valid_report(v1)
    assert_valid_report(v2)
    f1, f2 = v1["findings"]
    assert f1["title"] == f2["title"] == TITLE and f1["kind"] == f2["kind"] == "conflict"
    assert [e["quote"] for e in f1["evidence"]] == [e["quote"] for e in f2["evidence"]] == [Q_RULE, Q_ACC]
    assert f1["evidence"][0]["block_id"] != f2["evidence"][0]["block_id"]  # одинаковый текст, разные места
    assert f1["witness"]["input"] != f2["witness"]["input"]  # различает их условие сценария
    assert v2["findings"][0]["title"] == TITLE and v2["findings"][0]["id"] == "F-1"
    # в новой редакции «R-1» — корпоративное правило, а не дебетовое: id ничего не доказывают
    assert "корпоративной" in v2["requirements"][0]["text"] and "дебетовой" in v1["requirements"][0]["text"]


def test_fix_belongs_to_corporate_card_and_debit_defect_persists():
    prev, cur = cards_v1(), cards_v2()
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert rows(diff) == [
        ("F-2", "coverage R-1↔R-2", "исправлено в тексте", "text_changed_rechecked"),
        ("F-1", "F-1", "сохранилось", "same_root_cause_severity_changed"),
    ]
    st = by_old(diff)
    res = st["F-2"][1]
    assert res["proof"]["kind"] == "coverage_reconciled"
    assert res["proof"]["coverage"] == {
        "req_id": "R-1",
        "acceptance_ids": ["R-2"],
        "status": "covered",
        "previous_status": "conflict",
        "explanation": cur["coverage"][0]["explanation"],
    }
    assert any(e["quote"] == Q_FIX for e in res["evidence"])  # опора правки в новой редакции
    assert "Источник исправления К-1 (R-3) → 1.1 (R-1)" in res["reason"]
    assert f"условие «{K_INPUT}»" in res["reason"]
    assert (
        "F-1 («Критерий приёмки противоречит правилу отправки push», 2.1 (R-3), 2.2 (R-4)) — другой источник"
        in res["reason"]
    )
    assert res["view"]["behavior_change"].startswith("К-1: «достигают порога» → «превышают порог»")

    per = st["F-1"][1]
    assert per["new_ids"] == ["F-1"] and per["severity"] == {"old": "critical", "new": "major"}
    assert per["severity_change"] == "lowered"
    assert "источник Д-1 (R-1) → 2.1 (R-3); Д-КП-1 (R-2) → 2.2 (R-4)" in per["reason"]
    assert "условие «Дебетовая карта: расходы 49 000 ₸, порог 50 000 ₸, покупка 1 000 ₸» то же" in per["reason"]
    assert "исход тот же" in per["reason"]
    assert per["identity"]["old"]["source"] == ["Д-1 (R-1)", "Д-КП-1 (R-2)"]
    assert per["identity"]["new"]["source"] == ["2.1 (R-3)", "2.2 (R-4)"]
    m = per["match"]["F-1->F-1"]
    assert m["same_condition"] is True and m["requirements"] == 1.0

    # критерии приёмки только перенумерованы: «Д-КП-1.» → «2.2.» не считается правкой текста
    rm = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"]}
    assert rm["R-2"]["changes"] == ["renumbered"] and rm["R-4"]["changes"] == ["renumbered"]
    assert rm["R-3"]["new_ids"] == ["R-1"] and "reworded" in rm["R-3"]["changes"]
    assert diff["impacted_req_ids"] == ["R-1"]
    assert not diff["introduced"]


def test_shuffled_inputs_give_the_same_result():
    prev, cur = cards_v1(), cards_v2()
    base = compare_reports(prev, cur)
    rnd = random.Random(2026)
    for _ in range(10):
        p, c = clone(prev), clone(cur)
        for rep in (p, c):
            for key in ("findings", "requirements", "checks", "coverage"):
                rnd.shuffle(rep[key])
            for f in rep["findings"]:
                rnd.shuffle(f["evidence"])
                rnd.shuffle(f["req_ids"])
        out = compare_reports(p, c)
        for side in ("previous", "current"):  # хеш входа честно меняется вместе с порядком списков
            out["basis"][side]["report_sha256"] = base["basis"][side]["report_sha256"]
        assert rows(out) == rows(base)
        assert [e["reason"] for k in ("resolved", "persisting") for e in out[k]] == [
            e["reason"] for k in ("resolved", "persisting") for e in base[k]
        ]


@pytest.mark.parametrize("severity", ["critical", "major", "minor"])
def test_only_severity_of_persisting_finding_changes(severity):
    diff = compare_reports(cards_v1(), cards_v2(debit_severity=severity))
    st = by_old(diff)
    assert st["F-1"][0] == "persisting" and st["F-2"][0] == "resolved"
    expected = None if severity == "critical" else "lowered"
    assert st["F-1"][1]["severity_change"] == expected
    assert st["F-1"][1]["reason_code"] == "same_root_cause" + ("_severity_changed" if expected else "")
    assert not diff["introduced"]


# --- контроли из той же второй редакции ---------------------------------------------------


def test_missing_profile_stage_leaves_fix_unassessed():
    prev, cur = cards_v1(), v2_profile_failed()
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    assert st["F-2"][0] == "unassessed" and st["F-2"][1]["reason_code"] == "run_incomplete"
    assert "Этап cross, который нашёл замечание, во втором прогоне не завершён" in st["F-2"][1]["reason"]
    assert st["F-2"][1]["recheck"]["scenario"] == K_INPUT
    assert st["F-1"][0] == "persisting"  # найденное этапом другого прогона всё равно найдено
    assert not diff["resolved"]


def test_profile_stage_ok_but_pair_not_checked_is_unassessed():
    diff = compare_reports(cards_v1(), v2_profile_pair_missing())
    status, e = by_old(diff)["F-2"]
    assert status == "unassessed" and e["reason_code"] == "recheck_missing"
    assert "R-1/correct, R-2/correct" in e["reason"]


def test_unreadable_corporate_section_is_not_a_fix():
    prev, cur = cards_v1(), v2_corporate_unreadable()
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    st = by_old(diff)
    status, e = st["F-2"]
    assert status == "unassessed" and e["reason_code"] == "run_incomplete"
    assert "прочитана не полностью" in e["reason"]
    assert "Раздел «Корпоративные карты › Функциональные требования»" in e["reason"]
    assert "Удаление источника не доказывает исправления" in e["reason"]
    assert st["F-1"][0] == "persisting" and st["F-1"][1]["new_ids"] == ["F-1"]


def test_foreign_stage_failure_keeps_full_proof():
    prev, cur = cards_v1(), v2_foreign_failure()
    assert cur["run"]["status"] == "partial" and cur["run"]["incomplete_stages"] == ["individual", "bank"]
    diff = compare_reports(prev, cur)
    st = by_old(diff)
    assert st["F-2"][0] == "resolved" and st["F-2"][1]["proof"]["kind"] == "coverage_reconciled"
    assert st["F-1"][0] == "persisting"


def test_issue_on_fixed_rule_beats_coverage():
    cur = cards_v2()
    cur["checks"][0].update(status="issue", finding_ids=["F-9"], reason="правило 1.1 противоречит 1.2")
    status, e = by_old(compare_reports(cards_v1(), cur))["F-2"]
    assert status == "unassessed" and e["reason_code"] == "recheck_failed"


def test_coverage_with_unverifiable_evidence_is_not_proof():
    cur = cards_v2()
    cur["coverage"][0]["evidence"][0]["start"] += 1
    status, e = by_old(compare_reports(cards_v1(), cur))["F-2"]
    assert status == "unassessed"


def test_old_code_merged_corporate_into_debit():
    """Регресс 6780abf: без источника опор корпоративная F-2 сливалась с дебетовой F-1.

    Воспроизводит механизм напрямую: цитата F-2 «push отправляется, когда … достигают порога» в новой
    редакции есть только в дебетовом правиле. Поиск без ограничения по источнику находит её там."""
    from bcc_review.decisions import diff as D

    prev, cur = cards_v1(), cards_v2()
    ed = D._Edition(cur, "current")
    corporate_blocks = [b["id"] for b in cur["document"]["blocks"] if "корпоративной" in b["text"]]
    unrestricted = ed.locate(Q_RULE, corporate_blocks)
    assert unrestricted is not None and "дебетовой" in ed.block_by_id[unrestricted["block_id"]]["text"]
    restricted = ed.locate(Q_RULE, corporate_blocks, only=True)
    assert restricted is None or "корпоративной" in ed.block_by_id[restricted["block_id"]]["text"]
    diff = compare_reports(prev, cur)
    assert [e["old_ids"] for e in diff["persisting"]] == [["F-1"]]  # не [["F-1", "F-2"]], как было


def test_view_and_markdown_for_13_and_17():
    diff = compare_reports(cards_v1(), cards_v2())
    view = to_view(diff)
    assert view["summary"] == {"resolved": 1, "persisting": 1, "unassessed": 0, "introduced": 0, "severity_changed": 1}
    by_id = {r["old_ids"][0]: r for r in view["previous_findings"]}
    assert by_id["F-2"]["entity"] == "К-1 ↔ К-КП-1" and by_id["F-2"]["new_quote"] == Q_FIX
    assert by_id["F-1"]["entity"] == "Д-1 ↔ Д-КП-1" and by_id["F-1"]["severity_change"] == "lowered"
    md = render_markdown(diff)
    assert md.count("| исправлено в тексте |") == 1 and md.count("| сохранилось |") == 1
    json.dumps(diff, ensure_ascii=False)


def test_witness_input_from_p06_object_or_its_str_is_a_condition():
    """№06 даёт witness.input объектом, №07 кладёт в Finding его str(): смещения блоков не условие."""
    from bcc_review.decisions.diff import witness_condition

    obj = {
        "description": "Дебетовая карта: расходы 49 000 ₸, порог 50 000 ₸, покупка 1 000 ₸",
        "document_data": [
            {
                "name": "порог",
                "value": "50000",
                "evidence": {"block_id": "b0006", "start": 41, "end": 49, "quote": "50 000 ₸"},
            }
        ],
        "illustrative": [],
        "assignments": {"расходы после покупки": "равны порогу"},
    }
    expected = (
        "Дебетовая карта: расходы 49 000 ₸, порог 50 000 ₸, покупка 1 000 ₸; расходы после покупки = равны порогу"
    )
    assert witness_condition({"input": obj}) == expected
    assert witness_condition({"input": str(obj)}) == expected
    moved = dict(
        obj,
        document_data=[
            {
                "name": "порог",
                "value": "50000",
                "evidence": {"block_id": "b0012", "start": 7, "end": 15, "quote": "50 000 ₸"},
            }
        ],
    )
    assert witness_condition({"input": str(moved)}) == expected  # другая редакция — то же условие
    assert witness_condition({"input": "просто строка"}) == "просто строка"


def test_persisting_identity_survives_p07_stringified_witness():
    prev, cur = cards_v1(), cards_v2()
    for rep, bid in ((prev, "b0006"), (cur, "b0012")):
        for f in rep["findings"]:
            w = f["witness"]
            w["input"] = str(
                {
                    "description": w["input"],
                    "document_data": [{"evidence": {"block_id": bid, "start": 3}}],
                    "assignments": {},
                }
            )
    st = by_old(compare_reports(prev, cur))
    assert st["F-1"][0] == "persisting" and st["F-1"][1]["match"]["F-1->F-1"]["same_condition"] is True
    assert st["F-2"][0] == "resolved"


def test_coverage_conflict_blocks_closure_even_with_scenario_pass():
    """Текст К-1 изменён, проверки pass со сценарием, но профильный этап всё ещё видит конфликт пары."""
    cur = cards_v2()
    for c in cur["checks"][:2]:
        c["scenario"] = K_INPUT
    cur["coverage"][0]["status"] = "conflict"
    status, e = by_old(compare_reports(cards_v1(), cur))["F-2"]
    assert status == "unassessed" and e["reason_code"] == "recheck_failed"
    assert "покрытие 1.1 (R-1) критерием 1.2 (R-2) — conflict" in e["reason"]


def test_lost_finding_on_unchanged_text_reports_profile_conflict():
    """Дебетовая находка пропала из нового отчёта, текст тот же, покрытие — conflict: не закрыто, объяснено."""
    cur = cards_v2()
    cur["findings"] = []
    cur["checks"] = [c for c in cur["checks"] if c["req_id"] in ("R-1", "R-2")]
    status, e = by_old(compare_reports(cards_v1(), cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert (
        "Профильный этап по-прежнему отмечает противоречие: покрытие 2.1 (R-3) критерием 2.2 (R-4) — conflict"
        in e["reason"]
    )


GOLDEN_FILES = ("cards_diff.json", "cards_view.json", "cards_diff.md")


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_cards_example_for_13_and_17(name):
    """Пример для №13 (HTML) и №17 (Markdown): входы, diff, строки view и раздел Markdown."""
    import os
    import pathlib

    golden = pathlib.Path(__file__).parent / "golden"
    prev, cur = cards_v1(), cards_v2()
    diff = compare_reports(prev, cur)
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=2) + "\n"  # noqa: E731
    text = {
        "cards_diff.json": dump(diff),
        "cards_view.json": dump(to_view(diff)),
        "cards_diff.md": render_markdown(diff),
    }[name]
    if os.environ.get("P09_UPDATE_GOLDEN") == "1":
        from p09_cards import mock_script_v2

        (golden / name).write_text(text, encoding="utf-8")
        (golden / "cards_previous.json").write_text(dump(prev), encoding="utf-8")
        (golden / "cards_current.json").write_text(dump(cur), encoding="utf-8")
        (golden / "cards_mock_script_v2.json").write_text(dump(mock_script_v2()), encoding="utf-8")
        try:  # рендеры смежных модулей — образец, не эталон (их меняют №17 и №13)
            from bcc_review.exports.html import write_html
            from bcc_review.exports.markdown import write_markdown

            full = dict(cur, diff=diff)
            write_markdown(full, golden / "cards_report_p17.md")
            write_html(full, golden / "cards_report_p13.html")
        except ImportError:
            pass
    assert (golden / name).read_text(encoding="utf-8") == text, f"P09_UPDATE_GOLDEN=1 pytest tests/p09 ({name})"
