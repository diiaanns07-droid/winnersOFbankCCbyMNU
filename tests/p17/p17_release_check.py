"""Одна команда №17: отчёт и Jira из одного Report — первый экран и машинная сверка.

    python tests/p17/p17_release_check.py [OUTDIR]        # по умолчанию out/p17-release-check

1. Офлайн-отчёт релиза: ``release/reports/offline/requirements.json`` (``rules_only``, ``partial``).
2. Полный фиксированный пример на том же ТЗ (:mod:`p17_release_example`): ``complete``, два критичных.

Для каждого: штатные ``write_markdown`` и ``write_jira_csv``, печать первого экрана, затем сверка —
встроенная (``check_markdown``, ``check_jira_csv``) и независимая от кода экспорта: числа берутся из
JSON, CSV читается обычным ``csv.reader``, первопричины пересчитываются заново. Код выхода 0 —
расхождений нет, 1 — есть.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]

from p17_helpers import SEV_RANK, independent_groups  # noqa: E402
from p17_release_example import (  # noqa: E402
    RELEASE_JSON,
    build_release_example,
    load_offline,
)

from bcc_review import contracts as C  # noqa: E402
from bcc_review.exports.jira import (  # noqa: E402
    COLUMNS,
    check_jira_csv,
    write_jira_csv,
)
from bcc_review.exports.markdown import check_markdown, write_markdown  # noqa: E402

NB = " "
PRIORITY = {"critical": "Highest", "major": "High", "minor": "Low"}
SECTIONS = ["## Решение", "## 1. Паспорт прогона", "## 2. Нарезка требований", "## 3. Проверка каждого требования",
            "## 4. Проверка всего набора требований", "## 5. Сводка", "## 6. Итог и приоритетные правки"]


def _ints(text: str) -> list[int]:
    return [int(x.replace(NB, "")) for x in re.findall(r"\d+(?: \d{3})*", text)]


def first_screen(md: str) -> str:
    return md.split("\n## 1. Паспорт прогона", 1)[0]


def independent_check(report: dict[str, Any], md: str, csv_path: Path) -> tuple[list[str], dict[str, Any]]:
    """Сверка без кода экспорта: JSON → ожидаемые числа и ID, CSV → csv.reader."""
    problems: list[str] = []
    run, summary, findings = report["run"], report["summary"], report["findings"]
    by_id = {f["id"]: f for f in findings}
    head = first_screen(md)

    header = next(line for line in head.splitlines() if line.startswith("**Документ:**"))
    for want in (f"(`{run['status']}`)", f"(`{run['mode']}`)"):
        if want not in header:
            problems.append(f"шапка без {want}")
    model_ok = ("не вызывалась" in header) if not run.get("model") else (f"**Модель:** {run['model']}" in header)
    if not model_ok:
        problems.append(f"шапка: модель не соответствует run.model={run.get('model')!r}")

    for part, label in (("development", "Разработка"), ("testing", "Тестирование")):
        status = report["verdict"][part]["status"]
        if run["status"] != "complete" and status != "not_ready":
            want = "Не подтверждено"
        else:
            want = {"ready": "Можно начинать", "not_ready": "Нельзя начинать", "unknown": "Не определено"}[status]
        row = next((line for line in head.splitlines() if line.startswith(f"| {label} |")), "")
        if want not in row:
            problems.append(f"вердикт «{label}»: ожидалось «{want}» (JSON: {status}, прогон {run['status']})")

    confirmed = [f for f in findings if f["status"] == "confirmed"]
    groups = independent_groups(confirmed)
    gsev = [min((by_id[i]["severity"] for i in g), key=SEV_RANK.get) for g in groups]
    states = [r["review_status"] for r in report["requirements"]]
    want_totals = [
        summary["requirements"], states.count("reviewed"), states.count("partial"), states.count("not_reviewed"),
        summary["findings"], summary["by_severity"]["critical"], summary["by_severity"]["major"],
        summary["by_severity"]["minor"], summary["by_status"]["confirmed"], summary["by_status"]["needs_review"],
        len(groups), gsev.count("critical"), gsev.count("major"), gsev.count("minor"),
    ]
    totals = next((line for line in head.splitlines() if line.startswith("**Итоги:**")), "")
    if _ints(totals) != want_totals:
        problems.append(f"«Итоги»: видно {_ints(totals)}, из JSON {want_totals}")

    top = [re.sub(r"\\(.)", r"\1", m.group(1)) for m in
           (re.match(r"^\d+\. \[((?:\\.|[^\]])+)\]\(#", line) for line in head.splitlines()) if m]
    crit_groups = [g for g, s in zip(groups, gsev, strict=True) if s == "critical"]
    if not top and confirmed:
        problems.append("первый экран без списка подтверждённых находок")
    for fid in top:
        if fid not in by_id or by_id[fid]["status"] != "confirmed":
            problems.append(f"первый экран: {fid} не подтверждённая находка JSON")
    if [SEV_RANK[by_id[f]["severity"]] for f in top if f in by_id] != sorted(
            SEV_RANK[by_id[f]["severity"]] for f in top if f in by_id):
        problems.append(f"первый экран: порядок не по серьёзности {top}")
    if not all(any(f in g for f in top) for g in crit_groups):
        problems.append("первый экран: показаны не все критичные первопричины")

    for heading in SECTIONS:
        if f"\n{heading}\n" not in f"\n{md}":
            problems.append(f"нет раздела {heading}")
    slicing = md.split("## 2. Нарезка требований", 1)[1].split("\n## 3.", 1)[0]
    if sum(1 for line in slicing.splitlines() if line.startswith("| [")) != len(report["requirements"]):
        problems.append("таблица нарезки: число строк не равно числу требований")
    for f in findings:
        if f'<a id="f-{f["id"].lower()}"></a>' not in md:
            problems.append(f"нет карточки {f['id']}")
    if C.evidence_errors(report):
        problems.append("опоры JSON не совпадают с текстом блоков")

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if rows[0] != COLUMNS:
        problems.append(f"заголовок CSV {rows[0]}")
    data = [dict(zip(COLUMNS, r, strict=True)) for r in rows[1:]]
    csv_ids = [re.match(r"^\[([^\]]+)\]", r["Summary"]).group(1) for r in data]
    if len(data) != len(groups):
        problems.append(f"CSV: {len(data)} записей, первопричин в JSON {len(groups)}")
    for g, sev in zip(groups, gsev, strict=True):
        hit = [i for i in csv_ids if i in g]
        if len(hit) != 1:
            problems.append(f"CSV: первопричина {sorted(g)} даёт записей {len(hit)}")
            continue
        row = data[csv_ids.index(hit[0])]
        if row["Priority"] != PRIORITY[sev]:
            problems.append(f"CSV {hit[0]}: приоритет {row['Priority']}, ожидался {PRIORITY[sev]}")
        for other in sorted(g - {hit[0]}):
            if other not in row["Description"]:
                problems.append(f"CSV {hit[0]}: не упомянут повтор {other}")
        rec = by_id[hit[0]].get("recommendation")
        if rec and f"Ожидаемое решение: {rec}" not in row["Description"]:
            problems.append(f"CSV {hit[0]}: текст рекомендации не читается обратно (кавычки/переносы)")
        if f'<a id="f-{hit[0].lower()}"></a>' not in md:
            problems.append(f"CSV {hit[0]}: нет карточки в Markdown")
    facts = {"groups": groups, "csv_ids": csv_ids, "csv_rows": data, "top": top, "totals": want_totals}
    return problems, facts


def example_specific(report: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """Сценарий полного примера: одна цитата — две задачи, дубль — одна задача."""
    problems = []
    by_id = {f["id"]: f for f in report["findings"]}
    shared = by_id["F-027"]["evidence"][0]
    if by_id["F-029"]["evidence"][0] != shared:
        problems.append("F-027 и F-029 должны опираться на одну цитату")
    if not {"F-027", "F-029"} <= set(facts["csv_ids"]):
        problems.append("две бизнес-проблемы с одной цитатой должны остаться двумя записями CSV")
    if "F-030" in facts["csv_ids"]:
        problems.append("дубль F-030 не должен быть отдельной записью CSV")
    row28 = facts["csv_rows"][facts["csv_ids"].index("F-028")]["Description"] if "F-028" in facts["csv_ids"] else ""
    if "F-030 — явная ссылка duplicate_of" not in row28:
        problems.append("запись F-028 должна называть повтор F-030 и основание связи")
    if facts["top"][:2] != ["F-027", "F-028"]:
        problems.append(f"первый экран должен начинаться с F-027, F-028: {facts['top'][:2]}")
    return problems


def check_one(name: str, report: dict[str, Any], outdir: Path, out: list[str], extra=None) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = write_markdown(report, outdir / "report.md")
    csv_path = write_jira_csv(report, outdir / "report.jira.csv")
    md = md_path.read_text(encoding="utf-8")
    problems = [f"check_markdown: {p}" for p in check_markdown(md_path, report)]
    problems += [f"check_jira_csv: {p}" for p in check_jira_csv(csv_path, report)]
    own, facts = independent_check(report, md, csv_path)
    problems += own
    if extra:
        problems += extra(report, facts)
    out.append(f"\n{'=' * 100}\n{name}\n  вход: {outdir / 'report.json'}\n  отчёт: {md_path}\n  Jira: {csv_path}\n")
    out.append(first_screen(md).rstrip())
    out.append(
        f"\n--- сверка {name}: строк CSV {len(facts['csv_ids'])} = первопричин {len(facts['groups'])}; "
        f"ID первого экрана {facts['top']}; «Итоги» из JSON {facts['totals']}"
    )
    out.append("    РАСХОЖДЕНИЯ:\n    " + "\n    ".join(problems) if problems else "    OK: расхождений нет")
    return len(problems)


def main(argv: list[str]) -> int:
    outdir = Path(argv[0]) if argv else ROOT / "out" / "p17-release-check"
    if not RELEASE_JSON.exists():
        print(f"нет {RELEASE_JSON}: нужна ветка с комплектом release/ (bcc/integration @ 2821989)")
        return 1
    offline = load_offline()
    out: list[str] = []
    bad = check_one("1. Офлайн-отчёт релиза (rules_only)", offline, outdir / "offline", out)
    bad += check_one("2. Полный фиксированный пример (complete, два критичных)", build_release_example(offline),
                     outdir / "example", out, example_specific)
    out.append(f"\nИТОГ: {'OK' if not bad else f'расхождений {bad}'}")
    print("\n".join(out))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
