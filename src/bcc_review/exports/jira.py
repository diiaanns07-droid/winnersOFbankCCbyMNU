"""Нейтральный Jira CSV из Report.

Публичный интерфейс::

    write_jira_csv(report, output_path) -> Path
    jira_rows(report) -> list[dict[str, str]]
    select_jira_groups(report) -> list[dict]   # что попадёт в CSV

Колонки: Summary, Description, Issue Type, Priority, Labels. Одна
первопричина даёт одну запись: дубли внутри находки движок сводит в
``merged_from``; отдельные находки сливаются в одну строку только по явной
связи (``duplicate_of``, ``root_cause_id``, ID в ``merged_from``) или при
совпадении причины вместе с исходами (``cause.object``, ``cause.condition``,
``cause.outcomes`` и семейство вида). Одинаковых объекта и условия мало. По умолчанию в CSV
идут только подтверждённые находки (``status: confirmed``); находки «на
проверке» добавляются флагом ``include_needs_review=True``. Снятые кандидаты
(``Report.rejected``) не экспортируются.

Файл: UTF-8 без BOM, разделитель — запятая, все поля в кавычках,
кавычки внутри поля удваиваются, переводы строк внутри Description — ``\\n``,
конец записи — ``\\r\\n`` (RFC 4180). Значения Issue Type и Priority —
стандартные для Jira; банк сопоставляет их со своими полями на шаге импорта.

Запуск без движка::

    python -m bcc_review.exports.jira REPORT.json OUTPUT.csv
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._common import (
    BLOCKS_LABEL,
    LINK_LABEL,
    SEVERITY_LABEL,
    STATUS_LABEL,
    DocIndex,
    as_list,
    as_report_dict,
    criterion_name,
    criterion_ref,
    evidence_of,
    finding_status,
    findings_all,
    group_findings,
    kind_name,
    merged_candidates,
    requirement_index,
    run_info,
)

__all__ = ["COLUMNS", "DEFAULT_PRIORITY", "write_jira_csv", "jira_rows", "select_jira_groups", "check_jira_csv"]

COLUMNS = ["Summary", "Description", "Issue Type", "Priority", "Labels"]
DEFAULT_PRIORITY = {"critical": "Highest", "major": "High", "minor": "Low"}
DEFAULT_ISSUE_TYPE = "Task"
SUMMARY_LIMIT = 255  # предел поля Summary в Jira


def select_jira_groups(report: Any, include_needs_review: bool = False) -> list[dict[str, Any]]:
    """Первопричины, которые станут записями CSV.

    Группировка — как в Markdown-сводке. Группа попадает в CSV, если в ней
    есть подтверждённая находка (или находка на проверке при
    ``include_needs_review``).
    """
    data = as_report_dict(report)
    allowed = {"confirmed"} | ({"needs_review"} if include_needs_review else set())
    selected = [f for f in findings_all(data) if finding_status(f) in allowed]
    return group_findings(selected)


def _label(text: Any) -> str:
    """Метка Jira: без пробелов и запятых."""
    return re.sub(r"[\s,]+", "_", str(text).strip()) if text is not None else ""


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _quote_lines(text: Any) -> list[str]:
    """Цитата построчно с префиксом «> », чтобы начало строки не читалось как разметка."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [f"> {line}" for line in lines]


def _req_names(req_ids: list[Any], reqs: Mapping[str, Mapping[str, Any]]) -> str:
    names = []
    for rid in req_ids:
        req = reqs.get(str(rid))
        source = req.get("source_id") if req else None
        names.append(f"{rid} ({source})" if source else str(rid))
    return ", ".join(names)


def _description(group: Mapping[str, Any], data: Mapping[str, Any], idx: DocIndex) -> str:
    f = group["primary"]
    reqs = requirement_index(data)
    sev = str(f.get("severity") or "").lower()
    status = finding_status(f)
    lines: list[str] = []
    ids = str(f.get("id"))
    if group["others"]:
        ids += " (та же первопричина: " + ", ".join(
            f"{m.get('id')} — {LINK_LABEL.get(group['link_of'].get(str(m.get('id')), ''), 'связь не указана')}"
            .replace("`", "")
            for m in group["others"]
        ) + ")"
    lines.append(f"ID замечания: {ids}")
    merged = [x for m in group["members"] for x in merged_candidates(m)]
    if merged:
        lines.append(f"Объединено при подготовке: {', '.join(merged)}")
    req_ids = []
    for m in group["members"]:
        for rid in as_list(m.get("req_ids")):
            if rid not in req_ids:
                req_ids.append(rid)
    lines.append(f"Требования: {_req_names(req_ids, reqs) or 'не указаны'}")
    ref = criterion_ref(f.get("criterion"))
    lines.append(
        f"Тип: {kind_name(f.get('kind'))}. Критерий: {criterion_name(f.get('criterion'))}"
        + (f" ({ref})" if ref else "")
        + f". Серьёзность: {SEVERITY_LABEL.get(sev, sev or 'не указана')}. "
        f"Статус: {STATUS_LABEL.get(status, status)}."
    )
    lines.append("")
    lines.append(f"Суть: {_one_line(f.get('title')) or 'не указана'}")

    evs = evidence_of(f)
    kind = str(f.get("kind") or "").lower()
    inspected = as_list(f.get("inspected_block_ids"))
    for i, ev in enumerate(evs, 1):
        lines.append("")
        if kind in {"contradiction", "conflict"} and len(evs) >= 2:
            label = f"Место {i}"
        elif inspected:
            label = "Обещание в тексте"
        else:
            label = "Место" if len(evs) == 1 else f"Место {i}"
        lines.append(f"{label}: {idx.place(ev.get('block_id'), ev.get('start'), ev.get('end'))}")
        lines.append("Цитата:")
        lines.extend(_quote_lines(ev.get("quote")))
    if not evs:
        lines.append("")
        lines.append("Цитата: в отчёте нет подтверждённой опоры.")
    if inspected:
        sections = []
        for bid in inspected:
            place = idx.place(bid)
            if place not in sections:
                sections.append(place)
        lines.append("")
        lines.append("Проверено, где описание должно быть: " + "; ".join(sections))

    witness = f.get("witness")
    if isinstance(witness, Mapping):
        lines.append("")
        lines.append(f"Сценарий-свидетель: {_one_line(witness.get('input'))}")
        lines.append(f"Исход А: {_one_line(witness.get('outcome_a'))}")
        lines.append(f"Исход Б: {_one_line(witness.get('outcome_b'))}")

    lines.append("")
    lines.append(f"Последствия: {f.get('impact') or 'не указаны в отчёте'}")
    blocks = ", ".join(BLOCKS_LABEL.get(str(b), str(b)) for b in as_list(f.get("blocks")))
    if blocks or f.get("blocked_decision"):
        parts = ([f"блокирует {blocks}"] if blocks else []) + (
            [f"решение: {f['blocked_decision']}"] if f.get("blocked_decision") else []
        )
        lines.append("Что блокирует: " + "; ".join(parts))
    rec = f.get("recommendation")
    lines.append(f"Ожидаемое решение: {rec or 'агент не сформулировал; решение за аналитиком'}")

    doc = data.get("document") or {}
    info = run_info(data)
    lines.append("")
    lines.append(
        f"Источник: отчёт проверки требований, документ «{doc.get('title') or 'без названия'}», "
        f"SHA-256 {info['source_sha256'] or 'нет данных'}, прогон {info['run_id'] or info['started_at'] or 'нет данных'}, "
        f"статус прогона {info['status']}, модель {info['model'] or 'нет данных'}."
    )
    text = "\n".join(lines)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _summary(f: Mapping[str, Any]) -> str:
    sev = str(f.get("severity") or "").lower()
    text = f"[{f.get('id')}] {kind_name(f.get('kind'))}: {_one_line(f.get('title'))}"
    if sev:
        text += f" ({SEVERITY_LABEL.get(sev, sev)})"
    if len(text) > SUMMARY_LIMIT:
        text = text[: SUMMARY_LIMIT - 1].rstrip() + "…"
    return text


def jira_rows(
    report: Any,
    *,
    issue_type: str = DEFAULT_ISSUE_TYPE,
    priority_map: Mapping[str, str] | None = None,
    include_needs_review: bool = False,
    extra_labels: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Строки CSV: по одной на первопричину, порядок — как в Report."""
    data = as_report_dict(report)
    idx = DocIndex(data)
    priorities = {**DEFAULT_PRIORITY, **(priority_map or {})}
    rows = []
    for group in select_jira_groups(data, include_needs_review=include_needs_review):
        f = group["primary"]
        sev = str(f.get("severity") or "").lower()
        labels = ["bcc-review", f"severity-{sev or 'none'}"]
        if f.get("kind"):
            labels.append(f"kind-{f['kind']}")
        if f.get("scope"):
            labels.append(f"scope-{f['scope']}")
        labels.extend(f"blocks-{b}" for b in as_list(f.get("blocks")))
        if finding_status(f) != "confirmed":
            labels.append("needs-review")
        labels.extend(extra_labels)
        rows.append(
            {
                "Summary": _summary(f),
                "Description": _description(group, data, idx),
                "Issue Type": issue_type,
                "Priority": priorities.get(sev, priorities.get("major", "Medium")),
                "Labels": " ".join(dict.fromkeys(_label(x) for x in labels if _label(x))),
            }
        )
    return rows


def render_jira_csv(report: Any, **options: Any) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writeheader()
    for row in jira_rows(report, **options):
        writer.writerow(row)
    return buf.getvalue()


def write_jira_csv(report: Any, output_path: str | os.PathLike[str], **options: Any) -> Path:
    """Записать CSV для импорта в Jira (UTF-8, без BOM) и вернуть путь."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_jira_csv(report, **options)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def check_jira_csv(csv_path: str | os.PathLike[str], report: Any, **options: Any) -> list[str]:
    """Сверить Jira CSV с Report. Пустой список — расхождений нет.

    Файл читается обычным ``csv.reader``. Проверяются заголовок, число записей
    (= уникальные подтверждённые дефекты, если не включены находки на проверке),
    ID основной находки каждой первопричины и побайтное совпадение всех полей
    с тем, что экспорт строит из этого Report.
    """
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    problems: list[str] = []
    if not rows or rows[0] != COLUMNS:
        return [f"заголовок CSV {rows[0] if rows else []} вместо {COLUMNS}"]
    data = as_report_dict(report)
    expected = jira_rows(data, **options)
    got = [dict(zip(COLUMNS, r, strict=False)) for r in rows[1:]]
    want_ids = [str(g["primary"].get("id")) for g in select_jira_groups(data, options.get("include_needs_review", False))]
    got_ids = [m.group(1) if (m := re.match(r"^\[([^\]]+)\]", r.get("Summary", ""))) else "?" for r in got]
    if got_ids != want_ids:
        problems.append(f"ID записей CSV {got_ids}, ожидалось {want_ids}")
    if not options.get("include_needs_review"):
        from ._common import (
            summary_numbers,  # noqa: PLC0415 — та же сводка, что в Markdown
        )

        unique = summary_numbers(data)["defects_unique"]
        if len(got) != unique:
            problems.append(f"записей CSV {len(got)}, уникальных подтверждённых дефектов в Report {unique}")
    for i, (g, w) in enumerate(zip(got, expected, strict=False), 1):
        for col in COLUMNS:
            if g.get(col) != w[col]:
                problems.append(f"запись {i} ({got_ids[i - 1]}): поле {col} не совпадает с Report")
    return problems


def _main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--check":
        problems = check_jira_csv(Path(argv[1]), Path(argv[2]))
        if problems:
            print("Расхождения:", *problems, sep="\n  ")
            return 4
        print("Jira CSV совпадает с Report.")
        return 0
    if len(argv) == 2:
        print(write_jira_csv(Path(argv[0]), argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
