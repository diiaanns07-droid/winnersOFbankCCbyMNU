"""Резервный экспорт замечаний в CSV для импорта в Jira (пока не влит модуль №17 ``bcc_review.exports.jira``).

Одна строка на замечание. Кодировка UTF-8 с BOM (Excel и импорт Jira распознают кириллицу),
разделитель — запятая, кавычки и переводы строк экранирует модуль :mod:`csv`.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Mapping

from . import report_common as rc

COLUMNS = ("Summary", "Issue Type", "Priority", "Labels", "Description")
PRIORITY = {"critical": "Highest", "major": "High", "minor": "Low"}
SUMMARY_LIMIT = 250


def _summary(finding: Mapping[str, Any]) -> str:
    title = rc.short_text(finding.get("title"), 1000)
    text = f"[{rc.severity_label(finding.get('severity'))}] {finding.get('id')}: {title}"
    if len(text) <= SUMMARY_LIMIT:
        return text
    return text[: SUMMARY_LIMIT - 1].rstrip() + "…"


def _label(value: Any) -> str:
    """Метка Jira не может содержать пробелы."""
    return re.sub(r"\s+", "_", str(value).strip())


def _labels(finding: Mapping[str, Any]) -> str:
    labels = ["bcc-review"] + [_label(finding[k]) for k in ("kind", "criterion") if finding.get(k)]
    return " ".join(rc.unique(labels))


def _description(report: Mapping[str, Any], finding: Mapping[str, Any],
                 blocks: Mapping[str, Mapping[str, Any]], reqs: Mapping[str, Mapping[str, Any]]) -> str:
    run = report.get("run") or {}
    lines = [
        f"Замечание {finding.get('id')}: {rc.severity_label(finding.get('severity'))}, "
        f"{rc.kind_label(finding.get('kind'))}.",
        f"Критерий: {rc.criterion_label(finding.get('criterion', ''))}.",
        f"Статус: {rc.label(rc.FINDING_STATUS_LABELS, finding.get('status'))}; "
        f"привязка: {rc.label(rc.ANCHOR_STATUS_LABELS, finding.get('anchor_status'))}; "
        f"{rc.label(rc.MEANING_STATUS_LABELS, finding.get('meaning_status'))}.",
    ]
    if finding.get("req_ids"):
        names = []
        for rid in finding["req_ids"]:
            source_id = (reqs.get(rid) or {}).get("source_id")
            names.append(f"{rid} ({source_id})" if source_id else rid)
        lines.append("Требования: " + ", ".join(names) + ".")

    lines += ["", "Цитаты из документа:"]
    evidence = rc.finding_evidence(finding)
    if evidence:
        lines += [f"- «{ev.get('quote')}» — {rc.describe_place(report, ev, index=blocks)}" for ev in evidence]
    elif finding.get("hints"):
        lines += [f"- «{h.get('quote')}» — {rc.hint_location(report, h, index=blocks)} (подсказка модели, не сверена)"
                  for h in finding["hints"]]
    else:
        lines.append("- цитата не найдена, место требует ручной проверки")

    witness = finding.get("witness")
    if witness:
        lines += ["", f"Сценарий противоречия: {witness.get('input')}",
                  f"- Исход A: {witness.get('outcome_a')}", f"- Исход B: {witness.get('outcome_b')}"]

    lines += ["", f"Последствие: {finding.get('impact') or 'не указано'}"]
    if finding.get("blocked_decision"):
        lines.append(f"Блокирует решение: {finding['blocked_decision']}")
    lines.append(f"Рекомендация: {finding.get('recommendation') or 'не сформулирована'}")
    lines += ["", f"Источник: прогон {run.get('run_id') or 'без ID'}, файл "
                  f"{run.get('source_name') or (report.get('document') or {}).get('source_name') or 'без имени'}, "
                  f"SHA-256 {run.get('source_sha256') or (report.get('document') or {}).get('id') or 'не указан'}."]
    return "\n".join(lines)


def write_jira_csv(report: Mapping[str, Any], output_path: str | Path) -> Path:
    """Записать замечания отчёта в CSV для Jira и вернуть путь к файлу."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = rc.block_index(report)
    reqs = rc.requirement_index(report)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for finding in rc.sorted_findings(report.get("findings") or []):
            writer.writerow((
                _summary(finding),
                "Task",
                PRIORITY.get(finding.get("severity"), "Medium"),
                _labels(finding),
                _description(report, finding, blocks, reqs),
            ))
    return path
