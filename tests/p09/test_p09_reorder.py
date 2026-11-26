"""Готовность 1: перестановка абзацев и изменение внутренних id сохраняют persisting;
один реальный новый дефект попадает в introduced."""

from bcc_review.decisions.diff import compare_reports
from p09_case import (
    DATA,
    F1,
    F2,
    F3,
    F4,
    F5_NEW,
    INT,
    NFR,
    S_DATA,
    S_FT,
    S_INT,
    S_NFR,
    assert_partition,
    assert_valid_report,
    by_old,
    check,
    document,
    finding,
    issue_checks,
    make_findings,
    report,
    requirements,
    v1_paras,
    v1_report,
)

# Ф-2 и Ф-3 поменялись местами и номерами, НФТ ушли за данные, добавлен Ф-5. Id назначены заново
# в порядке чтения, поэтому тот же «R-2» или «F-1» теперь означает другой пункт или другое замечание.
V2_PARAS = [
    (S_FT, "Ф-1", F1, "R-1"),
    (S_FT, "Ф-2", F3, "R-2"),
    (S_FT, "Ф-3", F2, "R-3"),
    (S_FT, "Ф-4", F4, "R-4"),
    (S_FT, "Ф-5", F5_NEW, "R-5"),
    (S_DATA, None, DATA, "R-6"),
    (S_NFR, None, NFR, "R-7"),
    (S_INT, None, INT, "R-8"),
]
V2_IDS = {"F1": "R-1", "F2": "R-3", "F3": "R-2", "F4": "R-4", "NFR": "R-7", "DATA": "R-6", "INT": "R-8"}
V2_NUMBERING = {"units": "F-1", "read": "F-2", "nfr": "F-3", "tz": "F-4", "conflict": "F-5"}


def _v2(extra_defect: bool = True) -> dict:
    doc = document(V2_PARAS)
    fs = make_findings(
        doc,
        V2_IDS,
        ("units", "read", "nfr", "tz", "conflict"),
        numbering=V2_NUMBERING,
        tz={"title": "Граница месяца: часовой пояс Алматы явно не задан"},
        units={"title": "Единицы суммы покупки и порога различаются"},
    )
    if extra_defect:
        fs.append(
            finding(
                "F-6",
                doc,
                req_ids=["R-5"],
                kind="ambiguity",
                criterion="unambiguous",
                severity="major",
                title="«Остаток бюджета» не определён",
                quotes=["остаток бюджета на месяц"],
            )
        )
    return report(doc, requirements(doc, V2_PARAS), fs, run_id="run-2")


def test_reorder_and_new_ids_keep_persisting_and_one_new_defect():
    prev, cur = v1_report(), _v2()
    assert_valid_report(prev)
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert diff["resolved"] == [] and diff["unassessed"] == []
    pairs = {e["old_ids"][0]: e["new_ids"] for e in diff["persisting"]}
    # одинаковые строки id означают разное: F-1 был конфликтом, а стал единицами измерения
    assert pairs == {"F-1": ["F-5"], "F-2": ["F-4"], "F-3": ["F-3"], "F-4": ["F-2"], "F-5": ["F-1"]}
    for e in diff["persisting"]:
        assert e["old_evidence"] and all(x["verified"] for x in e["old_evidence"])
        assert e["evidence"] and all(x["verified"] for x in e["new_evidence"])
        assert e["severity_change"] is None
    [new] = diff["introduced"]
    assert new["new_ids"] == ["F-6"] and new["origin"] == "new_text" and new["reason_code"] == "new_root_cause"
    assert new["view"]["new_quote"] == "остаток бюджета на месяц"


def test_requirement_map_follows_text_not_numbers_or_ids():
    diff = compare_reports(v1_report(), _v2())
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-2"]["new_ids"] == ["R-3"] and m["R-2"]["changes"] == ["renumbered"]  # Ф-2 → Ф-3, текст тот же
    assert m["R-3"]["new_ids"] == ["R-2"] and m["R-3"]["changes"] == ["renumbered"]  # Ф-3 → Ф-2
    assert m["R-5"]["new_ids"] == ["R-7"] and m["R-5"]["changes"] == []
    added = [r for r in diff["basis"]["requirement_map"] if r["relation"] == "added"]
    assert [r["new_ids"] for r in added] == [["R-5"]]
    assert diff["impacted_req_ids"] == ["R-5"]  # перенумерация и перенос не считаются правкой


def test_renumbering_alone_does_not_close_a_defect():
    """Номер в тексте сменился, замечание пропало, проверка «pass» есть — текст не правили: не закрыто."""
    prev = v1_report(names=("tz",))
    doc = document(V2_PARAS)
    cur = report(doc, requirements(doc, V2_PARAS), [], checks=[check("R-3", "unambiguous", "pass")], run_id="run-2")
    status, e = by_old(compare_reports(prev, cur))["F-1"]
    assert status == "unassessed" and e["reason_code"] == "anchor_unchanged"
    assert e["evidence"][0]["quote"] == "по дате совершения покупки в Алматы"


def test_line_numbers_and_finding_order_do_not_matter():
    """Строки сдвинулись у всех блоков после Ф-1, порядок замечаний обратный."""
    prev, cur = v1_report(), _v2(extra_defect=False)
    cur["findings"].reverse()
    diff = compare_reports(prev, cur)
    assert len(diff["persisting"]) == 5 and not diff["introduced"] and not diff["unassessed"]
    st = by_old(diff)
    assert st["F-2"][1]["view"]["old_loc"] != st["F-2"][1]["view"]["new_loc"]


def test_rerun_same_text_new_internal_ids():
    """Тот же текст, другие id требований и замечаний: всё сохранилось, SHA совпадает."""
    prev = v1_report()
    paras = [(s, sid, t, f"T-{k}") for k, (s, sid, t, _) in enumerate(v1_paras(), 1)]
    doc = document(paras)
    ids = {"F1": "T-1", "F2": "T-2", "F3": "T-3", "F4": "T-4", "NFR": "T-5", "DATA": "T-6", "INT": "T-7"}
    fs = make_findings(doc, ids, prefix="K")
    cur = report(doc, requirements(doc, paras), fs, checks=issue_checks(fs), run_id="run-2")
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert len(diff["persisting"]) == 5 and not diff["introduced"]
    assert diff["basis"]["same_source"] is True
    assert any(w["code"] == "same_source" for w in diff["warnings"])
