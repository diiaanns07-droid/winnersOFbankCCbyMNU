"""CLI модуля решений (№08).

    python -m bcc_review.decisions demo [--out DIR] [--write-answers]
    python -m bcc_review.decisions questions SOURCE REPORT.json [-o questions.md]
    python -m bcc_review.decisions apply SOURCE REPORT.json ANSWERS.md -o REVISION.md
    python -m bcc_review.decisions close MANIFEST.revision.json NEW_REPORT.json
    python -m bcc_review.decisions status PREVIOUS.json CURRENT.json   # статус каждого вопроса

REPORT.json — Report v1 (нужны document, findings и, для apply, questions).
Основной сценарий пользователя — ``python -m bcc_review INPUT OUTPUT.md --answers
answers.md`` в движке; этот CLI нужен для отладки модуля и офлайн-демо.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._doc import DocView, load_document, load_markdown, sha256_file, short_sha, to_plain
from .answers import ANSWERS_MARKER, apply_answers, render_apply_summary_md, write_questions
from .clarify import Question, build_questions
from .patches import closure_status, question_statuses

DEMO_LABEL = ("> **Демонстрационные ответы команды.** Синтетический пример для проверки модуля "
              "решений; это не решения владельца продукта.")
DEMO_ANSWERS = {
    "A": {
        "Q-01": "A\nКомментарий: тариф остался от прошлой версии продукта, комиссию не берём.",
        "Q-02": "отложить — ждём решения казначейства по календарю переносов",
        "Q-03": "Свой вариант: минимум 10 000 ₸, ниже — отказ с сообщением.\n"
                "Формулировка: Минимальная сумма частичного досрочного погашения — 10 000 ₸.",
        "Q-04": "A",
    },
    "B": {
        "Q-01": "B",
        "Q-03": "B",
    },
}


def fill_answers(questions_md: str, answers: dict[str, str], label: str | None = DEMO_LABEL) -> str:
    """Заполнить поля «Ответ:» шаблона вопросов (как сделал бы владелец)."""
    import re

    parts = re.split(r"(?m)^(?=## Q-\d+)", questions_md)
    out = []
    for part in parts:
        m = re.match(r"## (Q-\d+)", part)
        if m and answers.get(m.group(1)):
            part = re.sub(r"(?m)^Ответ:[ \t]*$", lambda _: "Ответ: " + answers[m.group(1)], part, count=1)
        out.append(part)
    text = "".join(out)
    if label:
        text = text.replace(ANSWERS_MARKER, ANSWERS_MARKER + "\n" + label, 1)
    return text


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(to_plain(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def run_demo(out_dir: Path, write_answers: bool = False) -> dict:
    from ._demo import (
        EXAMPLES_DIR, SYNTHETIC_DOC, make_scripted_ask, recheck, synthetic_findings, synthetic_requirements,
    )

    import shutil

    out_dir.mkdir(parents=True, exist_ok=True)
    before = out_dir / SYNTHETIC_DOC.name  # «до» рядом с «после»: папка самодостаточна
    if before.resolve() != SYNTHETIC_DOC.resolve():
        shutil.copyfile(SYNTHETIC_DOC, before)
    doc = load_markdown(before)
    findings = synthetic_findings(doc)
    log: list[str] = []
    questions = build_questions(doc, findings, make_scripted_ask(doc), warnings=log)
    _dump(out_dir / "report_before.json", {
        "schema_version": "1.0",
        "note": "Синтетический частичный Report: document, requirements, findings, questions. "
                "Находки подставные (как от Max), вопросы — через подставной транспорт ask.",
        "document": doc, "requirements": synthetic_requirements(doc), "findings": findings,
        "questions": [q.to_dict() for q in questions], "warnings": log,
        "recheck_before": recheck(doc),
    })
    qpath = write_questions(doc, questions, out_dir / "questions.md")
    summary = {"source_sha256": doc["id"], "questions": [q.id for q in questions], "variants": {}}
    for variant, answers in DEMO_ANSWERS.items():
        apath = EXAMPLES_DIR / f"answers_team_{variant}.md"
        if write_answers or not apath.exists():
            apath.write_text(fill_answers(qpath.read_text(encoding="utf-8"), answers), encoding="utf-8", newline="\n")
        result = apply_answers(doc, questions, apath, findings=findings,
                               output_md=out_dir / f"revision_{variant}.md", source=before)
        (out_dir / f"revision_{variant}.apply.md").write_text(render_apply_summary_md(result), encoding="utf-8", newline="\n")
        row = {"statuses": result["statuses"], "revision": result["revision"], "warnings": result["warnings"]}
        if result["revision"]:
            new_doc = load_markdown(result["revision"])  # повторное чтение реально записанного файла
            new_findings = recheck(new_doc)
            closure = closure_status(result["manifest"], new_doc, new_findings)
            _dump(out_dir / f"revision_{variant}.closure.json",
                  {"note": "Повторный анализ подставной перепроверкой _demo.recheck по файлу редакции.",
                   "findings_after": new_findings, **closure})
            row["closure"] = closure
        summary["variants"][variant] = row
    return summary


def _load_report(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _document(source: str, report: dict):
    d = report.get("document") or {}
    if d.get("blocks"):
        if d.get("id") and Path(source).exists() and sha256_file(source) != d["id"]:
            sys.exit(f"SOURCE ({short_sha(sha256_file(source))}) не совпадает с документом отчёта "
                     f"({short_sha(d['id'])})")
        return d
    return load_document(source)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.decisions", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="офлайн-цикл на синтетическом документе")
    d.add_argument("--out", default=None)
    d.add_argument("--write-answers", action="store_true", help="перезаписать answers_team_*.md")
    q = sub.add_parser("questions", help="файл вопросов из Report.json")
    q.add_argument("source")
    q.add_argument("report")
    q.add_argument("-o", "--output", default="questions.md")
    a = sub.add_parser("apply", help="применить answers.md и записать редакцию")
    a.add_argument("source")
    a.add_argument("report")
    a.add_argument("answers")
    a.add_argument("-o", "--output", required=True)
    st = sub.add_parser("status", help="статус вопросов прошлого отчёта после прогона с --answers")
    st.add_argument("previous")
    st.add_argument("current")
    c = sub.add_parser("close", help="статус закрытия по повторному анализу редакции")
    c.add_argument("manifest")
    c.add_argument("new_report")
    args = ap.parse_args(argv)

    if args.cmd == "demo":
        from ._demo import EXAMPLES_DIR

        out = Path(args.out) if args.out else EXAMPLES_DIR / "generated"
        s = run_demo(out, write_answers=args.write_answers)
        print(f"Документ {short_sha(s['source_sha256'])}: вопросы {', '.join(s['questions'])} → {out}")
        for v, row in s["variants"].items():
            print(f"\nВариант {v}: редакция {row['revision'] or 'не создана'}")
            fixes = {r["question_id"]: r["fix_label"] for r in row.get("closure", {}).get("questions", [])}
            for st in row["statuses"]:
                print(f"  {st['question_id']}: выбор={st['choice']:<7} решение={st['decision_status']:<22} "
                      f"текст={st['patch_state']:<15} после повторного анализа: {fixes.get(st['question_id'], '—')}")
        return 0
    if args.cmd == "questions":
        report = _load_report(args.report)
        doc = _document(args.source, report)
        qs = report.get("questions") or [q.to_dict() for q in build_questions(doc, report.get("findings", []))]
        p = write_questions(doc, qs, args.output)
        print(f"{p}: вопросов {len(qs)}, source_sha256 {DocView(doc).id}")
        return 0
    if args.cmd == "apply":
        report = _load_report(args.report)
        doc = _document(args.source, report)
        qs = [Question.from_dict(x) for x in report.get("questions", [])]
        res = apply_answers(doc, qs, Path(args.answers), findings=report.get("findings", []),
                            output_md=args.output, source=args.source)
        print(render_apply_summary_md(res))
        return 0 if not res["collisions"] else 2
    if args.cmd == "status":
        print("| Вопрос | Сторона | Ответ | Решение | Текст |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for r in question_statuses(args.previous, args.current):
            print(f"| {r['question_id']} | {r['side'] or '—'} | {r['answer'] or '—'} | {r['decision_status']} | "
                  f"{r['text_state_ru']} |")
        return 0
    if args.cmd == "close":
        new = _load_report(args.new_report)
        res = closure_status(args.manifest, new["document"], new.get("findings", []))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
