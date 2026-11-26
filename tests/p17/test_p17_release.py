"""Сквозной сценарий №17 на комплекте релиза: короткое резюме и Jira из одного Report.

Вход: ``release/reports/offline/requirements.json`` (движок, ``--offline-lint``) и полный
фиксированный пример :mod:`p17_release_example` на том же ТЗ. Без комплекта ``release/`` тесты
пропускаются.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys

import pytest
from p17_release_check import first_screen, main
from p17_release_example import RELEASE_JSON, build_release_example, load_offline

from bcc_review.exports.jira import COLUMNS, check_jira_csv, write_jira_csv
from bcc_review.exports.markdown import check_markdown, render_markdown, write_markdown

pytestmark = pytest.mark.skipif(not RELEASE_JSON.exists(), reason="нет release/reports/offline/requirements.json")


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == COLUMNS
    return [dict(zip(COLUMNS, r, strict=True)) for r in rows[1:]]


def ids(rows):
    return [r["Summary"].split("]", 1)[0].lstrip("[") for r in rows]


def test_one_command_passes(tmp_path, capsys):
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("OK: расхождений нет") == 2 and out.rstrip().endswith("ИТОГ: OK")


def test_offline_first_screen_keeps_partial_visible():
    report = load_offline()
    assert report["run"]["mode"] == "rules_only" and report["run"]["status"] == "partial"
    md = render_markdown(report)
    head = first_screen(md)
    assert "**Прогон:** завершён частично (`partial`) · **Режим:** только правила (без LLM) (`rules_only`) · " \
           "**Модель:** не вызывалась (только правила)" in head
    assert "> ⚠️ **Прогон завершён частично.**" in head
    assert "| Разработка | ❔ Не подтверждено: прогон неполный |" in head
    assert "| Тестирование | ❔ Не подтверждено: прогон неполный |" in head
    assert "и ещё 2 — полный список в паспорте" in head
    assert head.count("модель не вызывалась: режим --offline-lint") == 3  # не повторяется в обоих вердиктах
    assert "**Самые важные подтверждённые замечания** (показано 5 из 23" in head
    assert "Можно начинать" not in md
    passport = md.split("## 1. Паспорт прогона", 1)[1].split("\n## 2.", 1)[0]
    reasons_row = next(line for line in passport.splitlines() if line.startswith("| Причины статуса |"))
    assert reasons_row.count("<br>") == len(report["run"]["status_reasons"]) - 1 == 4
    assert "bank: чек-лист размечен по правилам без модели" in reasons_row
    assert check_markdown(md, report) == []


def test_full_example_two_critical_and_csv_semantics(tmp_path):
    report = build_release_example()
    md_path = write_markdown(report, tmp_path / "example.md")
    csv_path = write_jira_csv(report, tmp_path / "example.jira.csv")
    assert check_markdown(md_path, report) == []
    assert check_jira_csv(csv_path, report) == []
    head = first_screen(md_path.read_text(encoding="utf-8"))
    assert "**Критичные проблемы: 2 дефекта**" in head
    assert "1. [F-027](#f-f-027) 🔴" in head and "2. [F-028](#f-f-028) 🔴" in head
    assert "| Разработка | ⛔ Нельзя начинать |" in head and "| Тестирование | ⛔ Нельзя начинать |" in head
    rows = read_rows(csv_path)
    by_id = dict(zip(ids(rows), rows, strict=True))
    # Две бизнес-проблемы с одной цитатой — две записи.
    f = {x["id"]: x for x in report["findings"]}
    assert f["F-027"]["evidence"][0] == f["F-029"]["evidence"][0]
    assert "F-027" in by_id and "F-029" in by_id
    quote = "> На карту приходится максимум один такой push за календарный месяц."
    assert quote in by_id["F-027"]["Description"] and quote in by_id["F-029"]["Description"]
    # Дубль одной причины: одна запись F-028, повтор назван; в Markdown — та же связь.
    assert "F-030" not in by_id
    assert "ID замечания: F-028 (та же первопричина: F-030 — явная ссылка duplicate_of)" in by_id["F-028"]["Description"]
    assert "**Повтор первопричины [F-028](#f-f-028)** (явная ссылка `duplicate_of`)" in md_path.read_text(encoding="utf-8")
    # Кавычки и переносы читаются обратно.
    assert f'Ожидаемое решение: {f["F-027"]["recommendation"]}' in by_id["F-027"]["Description"]
    assert '\n"смена порога сбрасывает месячный лимит"' in by_id["F-027"]["Description"]
    assert 'разработчик выберет правило "наугад".' in by_id["F-027"]["Description"]
    assert len(rows) == json.loads(md_path.read_text(encoding="utf-8").split("bcc-review:summary ", 1)[1]
                                   .split(" -->")[0])["defects_unique"] == 26


def test_tampering_is_detected(tmp_path):
    report = build_release_example()
    md = render_markdown(report)
    bad_totals = md.replace("уникальных подтверждённых дефектов 26:", "уникальных подтверждённых дефектов 25:", 1)
    assert any("«Итоги»" in p for p in check_markdown(bad_totals, report))
    bad_top = md.replace("2. [F-028](#f-f-028) 🔴", "2. [F-029](#f-f-029) 🔴", 1)
    assert any("главные находки" in p for p in check_markdown(bad_top, report))
    csv_path = write_jira_csv(report, tmp_path / "j.csv")
    text = csv_path.read_text(encoding="utf-8").replace("Highest", "High", 1)
    tampered = tmp_path / "bad.csv"
    tampered.write_text(text, encoding="utf-8", newline="")
    assert any("Priority" in p for p in check_jira_csv(tampered, report))


def test_jira_cli_check_exit_codes(tmp_path):
    report = build_release_example()
    jpath = tmp_path / "report.json"
    jpath.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    csv_path = write_jira_csv(report, tmp_path / "report.jira.csv")
    cmd = [sys.executable, "-m", "bcc_review.exports.jira", "--check"]
    ok = subprocess.run([*cmd, str(csv_path), str(jpath)], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and "Jira CSV совпадает с Report." in ok.stdout
    other = tmp_path / "offline.json"
    other.write_text(RELEASE_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    bad = subprocess.run([*cmd, str(csv_path), str(other)], capture_output=True, text=True, check=False)
    assert bad.returncode == 4
