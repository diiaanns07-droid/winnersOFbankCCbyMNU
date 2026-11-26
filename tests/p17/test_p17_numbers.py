"""Сверка сводных чисел Markdown с JSON и показ полноты прогона."""

from __future__ import annotations

import copy

import pytest
from p17_fixtures import build_report
from p17_helpers import independent_counts, row_numbers, section

from bcc_review.exports.markdown import check_markdown, render_markdown

# Ожидаемые значения конкретных фикстур (зафиксированы вручную).
EXPECTED = {
    "complete": {
        "requirements_total": 9, "requirements_reviewed": 9, "requirements_partial": 0, "requirements_not_reviewed": 0,
        "requirements_clean": 4, "findings_total": 7, "findings_critical": 2, "findings_major": 3, "findings_minor": 2,
        "findings_confirmed": 6, "findings_needs_review": 1, "merged_candidates": 1, "defects_unique": 5,
        "same_cause_merged": 1, "defects_critical": 2, "defects_major": 2, "defects_minor": 1, "rejected": 1,
        "checks_pass": 73, "checks_issue": 6, "checks_unknown": 0, "checks_na": 2,
    },
    "partial": {
        "requirements_total": 9, "requirements_reviewed": 7, "requirements_partial": 1, "requirements_not_reviewed": 1,
        "requirements_clean": 4, "findings_total": 7, "findings_critical": 2, "findings_major": 3, "findings_minor": 2,
        "findings_confirmed": 6, "findings_needs_review": 1, "merged_candidates": 1, "defects_unique": 5,
        "same_cause_merged": 1, "defects_critical": 2, "defects_major": 2, "defects_minor": 1, "rejected": 1,
        "checks_pass": 57, "checks_issue": 6, "checks_unknown": 16, "checks_na": 2,
    },
    "failed": {
        "requirements_total": 9, "requirements_reviewed": 0, "requirements_partial": 0, "requirements_not_reviewed": 9,
        "requirements_clean": 0, "findings_total": 0, "findings_critical": 0, "findings_major": 0, "findings_minor": 0,
        "findings_confirmed": 0, "findings_needs_review": 0, "merged_candidates": 0, "defects_unique": 0,
        "same_cause_merged": 0, "defects_critical": 0, "defects_major": 0, "defects_minor": 0, "rejected": 0,
        "checks_pass": 0, "checks_issue": 0, "checks_unknown": 0, "checks_na": 0,
    },
}


@pytest.mark.parametrize("variant", ["complete", "partial", "failed"])
def test_fixture_expectations_match_independent_count(variant):
    assert independent_counts(build_report(variant)) == EXPECTED[variant]


@pytest.mark.parametrize("variant", ["complete", "partial", "failed"])
def test_json_summary_matches_lists(variant):
    report = build_report(variant)
    exp = independent_counts(report)
    s = report["summary"]
    assert s["requirements"] == exp["requirements_total"]
    assert s["reviewed_requirements"] == exp["requirements_reviewed"]
    assert s["findings"] == exp["findings_total"]
    assert s["by_status"] == {"confirmed": exp["findings_confirmed"], "needs_review": exp["findings_needs_review"]}


@pytest.mark.parametrize("numbered", [True, False])
@pytest.mark.parametrize("variant", ["complete", "partial", "failed"])
def test_visible_summary_matches_json(variant, numbered):
    report = build_report(variant, numbered)
    e = independent_counts(report)
    md = render_markdown(report)
    total = e["requirements_total"]
    assert row_numbers(md, "Выделено требований")[0] == total
    assert row_numbers(md, "Проверено полностью")[:2] == [e["requirements_reviewed"], total]
    assert row_numbers(md, "Проверено частично")[:2] == [e["requirements_partial"], total]
    assert row_numbers(md, "Не проверено")[:2] == [e["requirements_not_reviewed"], total]
    assert row_numbers(md, "Без подтверждённых замечаний")[:2] == [e["requirements_clean"], e["requirements_reviewed"]]
    assert row_numbers(md, "Замечаний в Report")[:4] == [
        e["findings_total"], e["findings_critical"], e["findings_major"], e["findings_minor"]]
    assert row_numbers(md, "По статусу")[:2] == [e["findings_confirmed"], e["findings_needs_review"]]
    assert row_numbers(md, "Уникальных подтверждённых дефектов")[:4] == [
        e["defects_unique"], e["defects_critical"], e["defects_major"], e["defects_minor"]]
    assert row_numbers(md, "Объединено при подготовке отчёта")[:2] == [e["merged_candidates"], e["same_cause_merged"]]
    assert row_numbers(md, "Снято при самопроверке")[0] == e["rejected"]
    assert row_numbers(md, "Проверок по критериям")[:4] == [
        e["checks_pass"], e["checks_issue"], e["checks_unknown"], e["checks_na"]]
    assert check_markdown(md, report) == []
    assert "Сверка `summary`" not in md


def test_duplicate_with_two_severities_counts_once_at_higher_severity():
    md = render_markdown(build_report("complete"))
    # F-003 (существенное) и F-004 (незначительное, duplicate_of F-003) — один дефект «существенное».
    assert row_numbers(md, "Уникальных подтверждённых дефектов")[:4] == [5, 2, 2, 1]
    # В Report.summary обе записи остаются: 7 замечаний, 3 существенных, 2 незначительных.
    assert row_numbers(md, "Замечаний в Report")[:4] == [7, 2, 3, 2]
    fixes = section(md, "## 6. Итог и приоритетные правки")
    assert "[F-003](#f-f-003) Нефункциональное требование не содержит измеримых показателей (+ [F-004](#f-f-004))" in fixes
    numbered = [line for line in fixes.splitlines() if line[:2] in {"1.", "2.", "3.", "4.", "5.", "6."}]
    assert not any(" [F-004](#f-f-004) «" in line or line.split(" ")[2:3] == ["[F-004](#f-f-004)"] for line in numbered)


def test_partially_checked_requirement_counted_separately():
    md = render_markdown(build_report("partial"))
    assert row_numbers(md, "Проверено полностью")[:2] == [7, 9]
    assert row_numbers(md, "Проверено частично")[:2] == [1, 9]
    assert row_numbers(md, "Не проверено")[:2] == [1, 9]
    assert "| Проверено полностью | 7 из 9 требований (77,8 %) |" in md


def test_summary_mismatch_is_reported():
    report = build_report("complete")
    report["summary"]["findings"] = 8
    report["summary"]["by_severity"]["major"] = 4
    md = render_markdown(report)
    assert "| ⚠️ Сверка `summary` | summary.findings = 8, по перечням Report — 7" in md
    assert "summary.by\\_severity.major = 4, по перечням Report — 3" in md
    # Видимые числа берутся из summary и совпадают с маркером.
    assert row_numbers(md, "Замечаний в Report")[0] == 8
    assert check_markdown(md, report) == []


def test_check_markdown_detects_tampering_and_other_report():
    report = build_report("complete")
    md = render_markdown(report)
    tampered = md.replace("| Проверено полностью | 9 из 9", "| Проверено полностью | 8 из 9", 1)
    assert any("Проверено полностью" in p for p in check_markdown(tampered, report))
    problems = check_markdown(md, build_report("partial"))
    assert any(p.startswith("requirements_reviewed") for p in problems)
    assert any(p.startswith("run_status") for p in problems)


def test_partial_run_never_shown_as_ready():
    report = build_report("partial")
    assert report["verdict"]["development"]["status"] == "ready"  # намеренная ошибка в фикстуре
    md = render_markdown(report)
    head = md[: md.find("## 1. Паспорт прогона")]
    assert "Можно начинать" not in md
    assert "| Разработка | ❔ Не подтверждено: прогон неполный |" in head
    assert "| Тестирование | ❔ Не подтверждено: прогон неполный |" in head
    assert "⚠️ **Прогон завершён частично.** Причина: Этап individual завершён частично" in head
    assert "Незавершённые этапы: individual." in head
    assert "Полностью проверено 7 из 9 требований (77,8 %), частично — 1, не проверено — 1." in head
    assert "Готовность к разработке и тестированию по такому прогону не подтверждается." in head
    assert "Критичные проблемы (среди проверенного): 2 дефекта" in head


def test_partial_read_document_blocks_ready():
    report = build_report("complete")
    report["verdict"]["development"] = {"status": "ready", "reasons": ["Блокеров нет"], "finding_ids": []}
    report["document"]["warnings"] = [{"code": "unreadable_page", "message": "Страница 3 не прочитана"}]
    md = render_markdown(report)
    assert "> ⚠️ **Документ прочитан не полностью:** unreadable\\_page: Страница 3 не прочитана" in md
    assert "| Разработка | ❔ Не подтверждено: прогон неполный |" in md


def test_failed_run_is_distinct():
    md = render_markdown(build_report("failed"))
    head = md[: md.find("## 1. Паспорт прогона")]
    assert "⛔ **Прогон завершился ошибкой.** Причина: Поставщик вернул 503 трижды; проверка не выполнена." in head
    assert "проверка не выполнена.." not in head
    assert "| Разработка | ❔ Не подтверждено: прогон завершился ошибкой |" in head
    assert "**Критичные проблемы:** не определены — проверка требований не выполнялась." in head
    assert "Можно начинать" not in md
    assert "| Статус поставщика | неуспешных вызовов — 3; этап individual — ошибка: server: 503; повторов — 2 |" in md
    assert "| Проверено полностью | 0 из 9 требований (0 %) |" in md


def test_provider_state_ignores_stages_without_model_calls():
    report = build_report("complete")
    report["run"]["stages"].insert(0, {"name": "rules", "status": "failed", "calls": 0, "cache_hits": 0,
                                       "reason": "модуль правил не найден"})
    md = render_markdown(report)
    assert "| Статус поставщика | ответы получены |" in md
    assert "rules — ошибка (модуль правил не найден)" in md  # но в списке этапов сбой виден


def test_complete_ready_run_is_shown_as_ready():
    report = build_report("complete")
    report["verdict"]["development"] = {"status": "ready", "reasons": ["Блокеров нет"], "finding_ids": []}
    md = render_markdown(report)
    assert "| Разработка | ✅ Можно начинать | Блокеров нет |" in md
    assert "В verdict указано «ready», хотя подтверждённых критичных дефектов: 2." in md


def test_three_statuses_distinguishable_in_banner_and_marker():
    banners = {}
    for variant in ("complete", "partial", "failed"):
        md = render_markdown(build_report(variant))
        banners[variant] = next(line for line in md.splitlines() if line.startswith("> ") and "Прогон" in line)
        assert f'"run_status": "{variant}"' in md
    assert len(set(banners.values())) == 3
    assert banners["complete"].startswith("> ✅")
    assert banners["partial"].startswith("> ⚠️")
    assert banners["failed"].startswith("> ⛔")


def test_report_object_not_modified():
    report = build_report("complete")
    before = copy.deepcopy(report)
    render_markdown(report)
    assert report == before
