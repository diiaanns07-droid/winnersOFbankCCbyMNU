"""Сгенерировать образцы отчётов p17 и проверяемый перечень (MANIFEST.md).

Запуск из корня репозитория::

    python tests/p17/p17_make_samples.py            # перезаписать tests/p17/samples/
    python tests/p17/p17_make_samples.py --check    # только сверить, что образцы актуальны

Образцы построены на синтетическом Report (режим mock) по нейтральному
документу. Это демонстрация формата и сверки, а не прогон модели.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from p17_fixtures import build_report, neutral_source  # noqa: E402

from bcc_review.exports._common import summary_numbers  # noqa: E402
from bcc_review.exports.jira import render_jira_csv  # noqa: E402
from bcc_review.exports.markdown import check_markdown, render_markdown  # noqa: E402

SAMPLES = HERE / "samples"
VARIANTS = [
    ("complete-numbered", "complete", True, "Полный прогон, документ с нумерацией ТР-1…ТР-5"),
    ("complete-unnumbered", "complete", False, "Полный прогон, документ без нумерации: ID присвоены агентом"),
    ("partial-numbered", "partial", True, "Частичный прогон: R-06 частично, R-07 не проверено; verdict ошибочно «ready»"),
    ("failed-numbered", "failed", True, "Прогон упал после нарезки: проверок и находок нет"),
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for numbered in (True, False):
        name = "source-numbered.md" if numbered else "source-unnumbered.md"
        files[name] = neutral_source(numbered).encode("utf-8")
    manifest = [
        "# Образцы отчётов p17: проверяемый перечень",
        "",
        "Сгенерировано `python tests/p17/p17_make_samples.py`. Синтетический Report контракта v1 (режим mock), "
        "нейтральный документ «Бронирование переговорных комнат». Не является прогоном модели. "
        "Каждый `report.json` проходит `bcc_review.contracts.validate` и `evidence_errors`.",
        "",
        "Проверка любого образца: `python -m bcc_review.exports.markdown --check <report.md> <report.json>`.",
        "",
        "| Образец | Сценарий | Статус прогона | Требований (полностью / частично / нет) | "
        "Дефектов уникальных (🔴/🟠/🟡) | Записей Jira | Сверка MD↔JSON | SHA-256 входа |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for key, variant, numbered, title in VARIANTS:
        report = build_report(variant, numbered)
        report_json = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        md = render_markdown(report)
        csv_text = render_jira_csv(report)
        files[f"{key}/report.json"] = report_json
        files[f"{key}/report.md"] = md.encode("utf-8")
        files[f"{key}/report.jira.csv"] = csv_text.encode("utf-8")
        n = summary_numbers(report)
        jira_count = len(list(csv.DictReader(io.StringIO(csv_text, newline=""))))
        problems = check_markdown(md, report)
        manifest.append(
            f"| `{key}` | {title} | `{n['run_status']}` | {n['requirements_total']} "
            f"({n['requirements_reviewed']} / {n['requirements_partial']} / {n['requirements_not_reviewed']}) | "
            f"{n['defects_unique']} ({n['defects_critical']}/{n['defects_major']}/{n['defects_minor']}) | "
            f"{jira_count} | {'совпадает' if not problems else 'РАСХОЖДЕНИЕ'} | `{report['run']['source_sha256'][:12]}…` |"
        )
    manifest += ["", "## Контрольные суммы файлов", "", "| Файл | SHA-256 |", "| :--- | :--- |"]
    for name in sorted(files):
        manifest.append(f"| `{name}` | `{_sha(files[name])}` |")
    files["MANIFEST.md"] = ("\n".join(manifest) + "\n").encode("utf-8")
    return files


def main(argv: list[str]) -> int:
    files = build_files()
    if "--check" in argv:
        stale = [n for n, data in files.items() if not (SAMPLES / n).exists() or (SAMPLES / n).read_bytes() != data]
        if stale:
            print("Устаревшие образцы:", *stale, sep="\n  ")
            return 1
        print(f"Образцы актуальны: {len(files)} файлов.")
        return 0
    for name, data in files.items():
        path = SAMPLES / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Записано {len(files)} файлов в {SAMPLES}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
