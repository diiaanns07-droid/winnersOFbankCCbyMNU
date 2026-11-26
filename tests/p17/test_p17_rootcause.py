"""Группировка первопричин: два разных дефекта с одинаковыми объектом и условием.

Фикстура :mod:`p17_rootcause`: F-1 (месяц учёта) и F-2 (правила push) имеют одинаковые
``cause.object`` и ``cause.condition``, но разные опоры и исходы — это две задачи.
F-3 — явный дубль F-1, F-4 — неподтверждённая находка.
"""

from __future__ import annotations

import copy
import csv
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from p17_helpers import independent_counts, independent_groups, row_numbers, section
from p17_rootcause import build_rootcause_report, strip_optional

from bcc_review import contracts as C
from bcc_review.exports._common import confirmed_groups, group_findings
from bcc_review.exports.jira import COLUMNS, write_jira_csv
from bcc_review.exports.markdown import check_markdown, render_markdown, write_markdown

ROOT = Path(__file__).resolve().parents[2]


def export(report, tmp_path, name="r"):
    """Штатные точки входа: write_markdown и write_jira_csv, CSV читается csv.reader."""
    md_path = write_markdown(report, tmp_path / f"{name}.md")
    csv_path = write_jira_csv(report, tmp_path / f"{name}.jira.csv")
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    return md_path.read_text(encoding="utf-8"), rows


def row_id(row):
    return re.match(r"^\[([^\]]+)\]", row[0]).group(1)


def confirmed_sets(report):
    return {frozenset(str(m["id"]) for m in g["members"]) for g in confirmed_groups(report)}


def test_fixture_is_valid_contract_v1():
    report = build_rootcause_report()
    C.validate(report)
    assert C.evidence_errors(report) == []
    f = {x["id"]: x for x in report["findings"]}
    # Условие задачи: у F-1 и F-2 совпадают объект и условие, различаются опоры, исходы и исправление.
    assert f["F-1"]["cause"]["object"] == f["F-2"]["cause"]["object"] == "операция по карте"
    assert f["F-1"]["cause"]["condition"] == f["F-2"]["cause"]["condition"] == "покупка проведена"
    assert {e["block_id"] for e in f["F-1"]["evidence"]}.isdisjoint({e["block_id"] for e in f["F-2"]["evidence"]})
    assert set(f["F-1"]["cause"]["outcomes"]).isdisjoint(f["F-2"]["cause"]["outcomes"])
    assert f["F-1"]["recommendation"] != f["F-2"]["recommendation"]
    assert f["F-3"]["duplicate_of"] == "F-1"
    assert f["F-4"]["status"] == "needs_review"


def test_two_independent_defects_in_markdown_and_csv(tmp_path):
    report = build_rootcause_report()
    md, rows = export(report, tmp_path)
    assert check_markdown(md, report) == []
    assert row_numbers(md, "Уникальных подтверждённых дефектов")[:4] == [2, 2, 0, 0]
    assert row_numbers(md, "Замечаний в Report")[:4] == [4, 2, 2, 0]
    assert row_numbers(md, "По статусу")[:2] == [3, 1]
    assert rows[0] == COLUMNS
    data = rows[1:]
    assert [row_id(r) for r in data] == ["F-1", "F-2"]
    assert len(data) == independent_counts(report)["defects_unique"] == 2
    for r in data:  # каждая задача CSV ведёт на карточку в отчёте
        assert f'<a id="f-{row_id(r).lower()}"></a>{row_id(r)} ·' in md
    by_id = {row_id(r): dict(zip(COLUMNS, r, strict=True)) for r in data}
    f1, f2 = by_id["F-1"]["Description"], by_id["F-2"]["Description"]
    # Собственные опоры, исходы и исправление у каждой задачи.
    assert "> Месяц определяется по дате совершения покупки в Алматы." in f1
    assert "> Февральский счётчик вырос на 4 000 ₸" in f1
    assert "Исход Б: Сумма засчитана в февраль" in f1
    assert "Ожидаемое решение: Привести критерий приёмки №2 к Ф-2" in f1
    assert "> На карту приходится максимум один такой push за календарный месяц." in f2
    assert "Исход А: Push не отправляется" in f2
    assert "Ожидаемое решение: Указать, сбрасывает ли смена порога месячный лимит push" in f2
    assert "Февральский" not in f2 and "F-3" not in f2 and "F-1" not in f2
    assert by_id["F-1"]["Priority"] == by_id["F-2"]["Priority"] == "Highest"


def test_duplicate_f3_traceable_through_f1(tmp_path):
    md, rows = export(build_rootcause_report(), tmp_path)
    card1 = section(md, '#### <a id="f-f-1"></a>F-1')
    card3 = section(md, '#### <a id="f-f-3"></a>F-3')
    assert "**Та же первопричина:** [F-3](#f-f-3) (существенное, подтверждено, явная ссылка `duplicate_of`)" in card1
    assert "**Повтор первопричины [F-1](#f-f-1)** (явная ссылка `duplicate_of`)" in card3
    head = md[: md.find("## 1. Паспорт прогона")]
    assert "Повтор той же первопричины: [F-3](#f-f-3) (явная ссылка `duplicate_of`)." in head
    fixes = section(md, "## 6. Итог и приоритетные правки")
    assert "[F-1](#f-f-1) Месяц учёта покупки" in fixes and "(+ [F-3](#f-f-3))" in fixes
    assert "[F-2](#f-f-2) Правила отправки push" in fixes
    f1 = next(r for r in rows[1:] if row_id(r) == "F-1")
    assert "ID замечания: F-1 (та же первопричина: F-3 — явная ссылка duplicate_of)" in f1[1]


def test_unconfirmed_f4_visible_with_status_and_not_merged(tmp_path):
    report = build_rootcause_report()
    md, rows = export(report, tmp_path)
    card4 = section(md, '#### <a id="f-f-4"></a>F-4')
    assert "**Статус:** требует проверки человеком" in card4
    assert "**Проверка смысла:** смысл под вопросом" in card4
    assert "Та же первопричина" not in card4 and "Повтор первопричины" not in card4
    assert "F-4" not in {row_id(r) for r in rows[1:]}
    wider = write_jira_csv(report, tmp_path / "wide.csv", include_needs_review=True)
    with open(wider, newline="", encoding="utf-8") as fh:
        wide = list(csv.reader(fh))[1:]
    assert [row_id(r) for r in wide] == ["F-1", "F-2", "F-4"]
    assert "needs-review" in wide[2][4].split()


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))), ids=lambda o: "".join(map(str, o)))
def test_permutation_keeps_groups_and_links(tmp_path, order):
    report = build_rootcause_report()
    report["findings"] = [report["findings"][i] for i in order]
    assert confirmed_sets(report) == {frozenset({"F-1", "F-3"}), frozenset({"F-2"})}
    groups = {g["primary"]["id"]: g for g in group_findings(report["findings"])}
    assert set(groups) == {"F-1", "F-2", "F-4"}
    assert groups["F-1"]["link_of"] == {"F-3": "duplicate_of"}
    md, rows = export(report, tmp_path, "p")
    assert check_markdown(md, report) == []
    assert sorted(row_id(r) for r in rows[1:]) == ["F-1", "F-2"]
    assert "**Повтор первопричины [F-1](#f-f-1)** (явная ссылка `duplicate_of`)" in md


def test_same_object_and_condition_alone_never_merge():
    report = build_rootcause_report()
    for f in report["findings"]:
        f["cause"]["outcomes"] = []
        f.pop("duplicate_of", None)
    assert confirmed_sets(report) == {frozenset({"F-1"}), frozenset({"F-2"}), frozenset({"F-3"})}


def test_proven_cause_and_outcomes_merge_without_explicit_link():
    report = build_rootcause_report()
    del report["findings"][2]["duplicate_of"]  # F-3: те же объект, условие и исходы (в другом порядке)
    groups = {g["primary"]["id"]: g for g in confirmed_groups(report)}
    assert {frozenset(m["id"] for m in g["members"]) for g in groups.values()} == {
        frozenset({"F-1", "F-3"}), frozenset({"F-2"})}
    assert groups["F-1"]["link_of"] == {"F-3": "cause"}
    md = render_markdown(report)
    assert "**Повтор первопричины [F-1](#f-f-1)** (совпали причина и исходы (`cause`))" in md


def test_same_cause_but_other_family_not_merged():
    report = build_rootcause_report()
    f3 = report["findings"][2]
    del f3["duplicate_of"]
    f3["kind"] = "ambiguity"  # другое семейство дефекта — та же формулировка причины не доказывает дубль
    assert confirmed_sets(report) == {frozenset({"F-1"}), frozenset({"F-2"}), frozenset({"F-3"})}


@pytest.mark.parametrize("link", ["root_cause_id", "merged_from"])
def test_other_explicit_links(link):
    report = build_rootcause_report()
    f1, f3 = report["findings"][0], report["findings"][2]
    del f3["duplicate_of"]
    f3["cause"] = None
    if link == "root_cause_id":
        f1["root_cause_id"] = f3["root_cause_id"] = "RC-month"
    else:
        f1["merged_from"] = ["C-03", "F-3"]
    groups = {g["primary"]["id"]: g for g in confirmed_groups(report)}
    assert groups["F-1"]["link_of"] == {"F-3": link}
    assert set(groups) == {"F-1", "F-2"}


def test_missing_cause_keeps_explicit_links_only(tmp_path):
    report = build_rootcause_report()
    for f in report["findings"]:
        f["cause"] = None
    C.validate(report)
    md, rows = export(report, tmp_path, "nocause")
    assert check_markdown(md, report) == []
    assert [row_id(r) for r in rows[1:]] == ["F-1", "F-2"]  # F-3 держится явной ссылкой
    del report["findings"][2]["duplicate_of"]
    md, rows = export(report, tmp_path, "nolink")
    assert [row_id(r) for r in rows[1:]] == ["F-1", "F-2", "F-3"]
    assert row_numbers(md, "Уникальных подтверждённых дефектов")[0] == 3


def test_old_report_without_optional_fields(tmp_path):
    report = strip_optional(build_rootcause_report())
    assert not any(k in f for f in report["findings"] for k in ("cause", "merged_from", "duplicate_of"))
    C.validate(report)
    assert C.evidence_errors(report) == []
    md, rows = export(report, tmp_path, "old")
    assert check_markdown(md, report) == []
    assert [row_id(r) for r in rows[1:]] == ["F-1", "F-2", "F-3"]
    assert "Повтор первопричины" not in md and "Та же первопричина" not in md
    assert row_numbers(md, "Объединено при подготовке отчёта")[:2] == [0, 0]


def test_independent_grouping_agrees_with_exporter():
    variants = [build_rootcause_report(), strip_optional(build_rootcause_report())]
    no_link = build_rootcause_report()
    del no_link["findings"][2]["duplicate_of"]
    variants.append(no_link)
    for report in variants:
        confirmed = [f for f in report["findings"] if f["status"] == "confirmed"]
        assert {frozenset(g) for g in independent_groups(confirmed)} == confirmed_sets(report)


def test_development_and_testing_verdicts_stay_separate():
    md = render_markdown(build_rootcause_report())
    assert (
        "| Разработка | ⛔ Нельзя начинать | Не определён месяц учёта покупки (F-1); Не определено правило второго push "
        "(F-2) ([F-1](#f-f-1), [F-2](#f-f-2)) |"
    ) in md
    assert (
        "| Тестирование | ⛔ Нельзя начинать | Ожидаемый результат критерия приёмки №2 противоречит Ф-2 (F-1, F-3); "
        "Нет точки отсчёта для «в течение минуты» (F-4, на проверке) ([F-1](#f-f-1), [F-3](#f-f-3), [F-4](#f-f-4)) |"
    ) in md
    concl = section(md, "## 6. Итог и приоритетные правки")
    assert "- **Разработка:** ⛔ Нельзя начинать." in concl and "- **Тестирование:** ⛔ Нельзя начинать." in concl
    assert '"verdict_development": "not_ready"' in md and '"verdict_testing": "not_ready"' in md


def test_cli_check_exit_codes(tmp_path):
    report = build_rootcause_report()
    jpath = tmp_path / "report.json"
    jpath.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    md_path = write_markdown(report, tmp_path / "report.md")
    cmd = [sys.executable, "-m", "bcc_review.exports.markdown", "--check", str(md_path), str(jpath)]
    env_path = str(ROOT / "src")
    ok = subprocess.run(cmd, capture_output=True, text=True, env={"PYTHONPATH": env_path}, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "Числа отчёта совпадают с Report." in ok.stdout
    # Отчёт, собранный прежним правилом (F-1+F-2 слиты), не проходит сверку с этим JSON.
    bad = md_path.read_text(encoding="utf-8").replace('"defects_unique": 2', '"defects_unique": 1')
    bad_path = tmp_path / "bad.md"
    bad_path.write_text(bad, encoding="utf-8")
    res = subprocess.run([*cmd[:4], str(bad_path), str(jpath)], capture_output=True, text=True,
                         env={"PYTHONPATH": env_path}, check=False)
    assert res.returncode == 4
    assert "defects_unique: в Markdown 1, в Report 2" in res.stdout


def test_report_not_mutated():
    report = build_rootcause_report()
    before = copy.deepcopy(report)
    render_markdown(report)
    confirmed_groups(report)
    assert report == before
