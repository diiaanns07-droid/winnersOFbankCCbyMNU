"""Готовность 1: перестановка абзацев и новые внутренние id сохраняют persisting;
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
    by_old,
    document,
    finding,
    make_findings,
    report,
    requirements,
    v1_paras,
    v1_report,
)

# Ф-2 и Ф-3 поменялись местами и номерами, НФТ ушли за данные, добавлен Ф-5,
# все id блоков, требований и замечаний новые.
V2_PARAS = [
    (S_FT, "Ф-1", F1, "Q-7"),
    (S_FT, "Ф-2", F3, "Q-6"),
    (S_FT, "Ф-3", F2, "Q-5"),
    (S_FT, "Ф-4", F4, "Q-4"),
    (S_FT, "Ф-5", F5_NEW, "Q-8"),
    (S_DATA, None, DATA, "Q-3"),
    (S_NFR, None, NFR, "Q-2"),
    (S_INT, None, INT, "Q-1"),
]
V2_IDS = {"F1": "Q-7", "F2": "Q-5", "F3": "Q-6", "F4": "Q-4", "NFR": "Q-2", "DATA": "Q-3", "INT": "Q-1"}
V2_NUMBERING = {"units": "N-1", "read": "N-2", "nfr": "N-3", "tz": "N-4", "conflict": "N-5"}


def _v2(extra_defect: bool = True) -> dict:
    doc = document(V2_PARAS, prefix="x")
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
                "N-6",
                doc,
                req_ids=["Q-8"],
                kind="ambiguity",
                criterion="И3",
                severity="major",
                title="«Остаток бюджета» не определён",
                quotes=["остаток бюджета на месяц"],
            )
        )
    return report(doc, requirements(doc, V2_PARAS), fs)


def test_reorder_and_new_ids_keep_persisting_and_one_new_defect():
    prev, cur = v1_report(), _v2()
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert diff["resolved"] == [] and diff["unassessed"] == []
    pairs = {e["old_ids"][0]: e["new_ids"] for e in diff["persisting"]}
    assert pairs == {"F-1": ["N-5"], "F-2": ["N-4"], "F-3": ["N-3"], "F-4": ["N-2"], "F-5": ["N-1"]}
    for e in diff["persisting"]:
        assert e["old_evidence"] and all(x["verified"] for x in e["old_evidence"])
        assert e["new_evidence"] and all(x["verified"] for x in e["new_evidence"])
        assert e["severity_change"] is None
    [new] = diff["introduced"]
    assert new["new_ids"] == ["N-6"] and new["origin"] == "new_text" and new["reason_code"] == "new_root_cause"
    assert new["view"]["new_quote"] == "остаток бюджета на месяц"


def test_requirement_map_follows_text_not_numbers():
    diff = compare_reports(v1_report(), _v2())
    m = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert m["R-2"]["new_ids"] == ["Q-5"] and "renumbered" in m["R-2"]["changes"]  # Ф-2 → Ф-3
    assert m["R-3"]["new_ids"] == ["Q-6"] and "renumbered" in m["R-3"]["changes"]  # Ф-3 → Ф-2
    assert m["R-5"]["new_ids"] == ["Q-2"] and m["R-5"]["changes"] == []
    added = [r for r in diff["basis"]["requirement_map"] if r["relation"] == "added"]
    assert [r["new_ids"] for r in added] == [["Q-8"]]


def test_line_numbers_and_finding_order_do_not_matter():
    """Строки сдвинулись у всех блоков после Ф-4, порядок замечаний обратный."""
    prev, cur = v1_report(), _v2(extra_defect=False)
    cur["findings"].reverse()
    diff = compare_reports(prev, cur)
    assert len(diff["persisting"]) == 5 and not diff["introduced"] and not diff["unassessed"]
    st = by_old(diff)
    assert st["F-2"][1]["view"]["old_loc"] != st["F-2"][1]["view"]["new_loc"]


def test_rerun_same_text_new_internal_ids():
    """Тот же текст, другие id блоков/требований/замечаний: всё сохранилось, SHA совпадает."""
    prev = v1_report()
    paras = [(s, sid, t, f"T-{k}") for k, (s, sid, t, _) in enumerate(v1_paras(), 1)]
    doc = document(paras, prefix="z")
    ids = {"F1": "T-1", "F2": "T-2", "F3": "T-3", "F4": "T-4", "NFR": "T-5", "DATA": "T-6", "INT": "T-7"}
    cur = report(doc, requirements(doc, paras), make_findings(doc, ids, prefix="K"))
    diff = compare_reports(prev, cur)
    assert_partition(diff, prev, cur)
    assert len(diff["persisting"]) == 5 and not diff["introduced"]
    assert diff["basis"]["same_source"] is True
    assert any(w["code"] == "same_source" for w in diff["warnings"])
