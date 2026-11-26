"""Jira CSV: стандартный csv-reader, экранирование, одна первопричина — одна запись."""

from __future__ import annotations

import copy
import csv

import pytest
from p17_fixtures import build_report
from p17_helpers import independent_counts

from bcc_review.exports.jira import (
    COLUMNS,
    jira_rows,
    select_jira_groups,
    write_jira_csv,
)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return reader.fieldnames, rows


def tricky_report():
    """Report с кавычками, запятыми, переносами и вертикальной чертой в полях."""
    report = build_report("complete")
    f002 = report["findings"][1]
    f002["title"] = 'Слово "быстро", без порога, и статус «свободно | занято»'
    f002["impact"] = 'Строка 1, с запятой\nСтрока 2 с "кавычками"\r\nСтрока 3'
    f005 = report["findings"][4]
    f005["evidence"] = [copy.deepcopy(report["requirements"][6]["evidence"][0])] + f005["evidence"]
    return report


@pytest.mark.parametrize("variant", ["complete", "partial", "failed"])
def test_row_count_equals_unique_confirmed_defects(tmp_path, variant):
    report = build_report(variant)
    fields, rows = read_csv(write_jira_csv(report, tmp_path / "jira.csv"))
    assert fields == COLUMNS
    assert len(rows) == independent_counts(report)["defects_unique"]
    assert len(rows) == len(select_jira_groups(report))


def test_one_root_cause_one_record(tmp_path):
    _, rows = read_csv(write_jira_csv(build_report("complete"), tmp_path / "j.csv"))
    assert [r["Summary"].split("]")[0] + "]" for r in rows] == ["[F-001]", "[F-002]", "[F-003]", "[F-005]", "[F-007]"]
    f003 = next(r for r in rows if r["Summary"].startswith("[F-003]"))
    assert "ID замечания: F-003 (та же первопричина: F-004 — явная ссылка duplicate_of)" in f003["Description"]
    assert f003["Priority"] == "High"
    f002 = next(r for r in rows if r["Summary"].startswith("[F-002]"))
    assert "Объединено при подготовке: C-014" in f002["Description"]


def test_needs_review_excluded_by_default_and_optional():
    report = build_report("complete")
    assert len(jira_rows(report)) == 5
    rows = jira_rows(report, include_needs_review=True)
    assert len(rows) == 6
    assert "needs-review" in next(r for r in rows if r["Summary"].startswith("[F-006]"))["Labels"].split()


def test_cyrillic_commas_quotes_newlines_preserved(tmp_path):
    report = tricky_report()
    expected = jira_rows(report)
    path = write_jira_csv(report, tmp_path / "tricky.csv")
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), "BOM ломает имя первой колонки при импорте"
    _, rows = read_csv(path)
    assert rows == expected
    f002 = next(r for r in rows if r["Summary"].startswith("[F-002]"))
    assert 'Слово "быстро", без порога, и статус «свободно | занято»' in f002["Summary"]
    assert 'Последствия: Строка 1, с запятой\nСтрока 2 с "кавычками"\nСтрока 3' in f002["Description"]
    assert "\r" not in f002["Description"]
    f005 = next(r for r in rows if r["Summary"].startswith("[F-005]"))
    assert "> Сотрудник получает напоминание о встрече:\n> 1. за 15 минут до начала;\n> 2. повторно" in f005["Description"]


def test_description_has_id_place_quote_impact_resolution():
    rows = jira_rows(build_report("complete"))
    f001 = rows[0]["Description"]
    for part in (
        "ID замечания: F-001",
        "Требования: R-03 (ТР-3), R-04 (ТР-4)",
        "Место 1: Функциональные требования, строка 9",
        "> Автор отменяет бронь только до начала встречи.",
        "Место 2: Функциональные требования, строка 10",
        "Сценарий-свидетель: Встреча началась в 10:00",
        "Последствия: Разработчик и тестировщик",
        "Что блокирует: блокирует разработку, тестирование; решение: Разрешать ли отмену брони после начала встречи",
        "Ожидаемое решение: Выбрать одно правило",
        "SHA-256 7f92",
    ):
        assert part in f001, part
    f005 = rows[3]["Description"]
    assert "Обещание в тексте: Требования к уведомлениям, строка 21" in f005
    assert "Проверено, где описание должно быть: Функциональные требования, строка 7;" in f005


def test_priority_issue_type_labels_neutral_and_overridable():
    rows = jira_rows(build_report("complete"))
    assert {r["Issue Type"] for r in rows} == {"Task"}
    assert [r["Priority"] for r in rows] == ["Highest", "High", "High", "Highest", "Low"]
    for r in rows:
        labels = r["Labels"].split(" ")
        assert "bcc-review" in labels
        assert all(label and " " not in label and "," not in label for label in labels)
    assert "blocks-development" in rows[0]["Labels"].split()
    custom = jira_rows(
        build_report("complete"), issue_type="Дефект требований", priority_map={"critical": "Блокер"},
        extra_labels=("ТЗ 42",),
    )
    assert custom[0]["Issue Type"] == "Дефект требований"
    assert custom[0]["Priority"] == "Блокер"
    assert "ТЗ_42" in custom[0]["Labels"].split()


def test_summary_single_line_and_limited():
    report = build_report("complete")
    report["findings"][0]["title"] = "Очень длинное\nназвание " + "слово " * 100
    row = jira_rows(report)[0]
    assert "\n" not in row["Summary"]
    assert len(row["Summary"]) <= 255


def test_rejected_never_exported():
    rows = jira_rows(build_report("complete"), include_needs_review=True)
    assert not any("Пример 10:00–10:30" in r["Summary"] for r in rows)
