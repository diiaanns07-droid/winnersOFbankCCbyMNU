"""Замер качества вопросов на сохранённых отчётах — без вызовов модели.

Документы: 9 ТЗ open2 (прогоны sonnet 08:20 и haiku 05:20) и официальный ТЗ (замер 13:00, sonnet и haiku) — 10
документов, 20 отчётов; плюс живые прогоны №32 (`tests/v2/fixtures/32_live`). По каждому отчёту — вопросов, больше
лимита (8 при critical, иначе 5), блокирующий critical без вопроса, пар почти одинаковых вопросов
(`clarify.is_similar`), вопросов с одним вариантом или без «если ответа не будет».

«как есть» — вопросы в сохранённом отчёте (код того прогона); «сейчас» — те же вопросы через постобработку
текущего кода: слияние похожих (`merge_similar`), лимит с приоритетом непокрытых critical (`cap_questions`),
вопрос кодом по critical без вопроса (`cover_critical`) и «если ответа не будет».

    python tests/v2/fixtures/32_questions/measure.py [--md]
"""
from __future__ import annotations

import glob
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import clarify as cl  # noqa: E402


def reports() -> list[tuple[str, Path]]:
    out = []
    for run in ("sonnet_0820", "haiku_0520"):
        for p in sorted((ROOT / "evaluation/v2/open2/results" / run).glob("*.md.json")):
            out.append((f"open2 {run.split('_')[0]} {p.name.split('.')[0]}", p))
    for model in ("sonnet", "haiku"):
        p = ROOT / f"evaluation/v2/measurements/zamer_13_00_9bd5954_{model}/report.json"
        if p.exists():
            out.append((f"официальный {model} 13:00", p))
    for d in sorted(glob.glob(str(ROOT / "tests/v2/fixtures/32_live/*/report_before.json"))):
        out.append((f"живой sonnet {Path(d).parent.name} (№32)", Path(d)))
    return out


def metrics(questions: list[dict], findings: list[dict]) -> dict:
    crit = {f["id"] for f in findings if f.get("severity") == "critical" and f.get("blocks", "both") != "none"
            and f.get("id")}
    covered = {fid for q in questions for fid in q.get("finding_ids") or []}
    return {"questions": len(questions), "over_cap": max(0, len(questions) - cl.question_cap(findings)),
            "critical_without": len(crit - covered), "similar_pairs": sum(1 for a, b in itertools.combinations(questions, 2)
                                                                          if cl.is_similar(a, b)),
            "no_if_no_answer": sum(1 for q in questions if not q.get("if_no_answer")),
            "one_option": sum(1 for q in questions if len(q.get("options") or []) < 2)}


def now(questions: list[dict], findings: list[dict]) -> list[dict]:
    by_id = {f.get("id"): f for f in findings}
    qs = [dict(q, finding_ids=[x for x in q.get("finding_ids") or [] if x in by_id]) for q in questions]
    qs = [q for q in qs if q["finding_ids"]]
    w: list[str] = []
    qs = cl.merge_similar(qs, by_id, w)
    qs = cl.cap_questions(qs, findings, w)
    return cl.cover_critical(qs, findings, w)


def main(md: bool = False) -> dict:
    rows, tot_a, tot_b = [], {}, {}
    for name, p in reports():
        r = json.loads(p.read_text(encoding="utf-8"))
        findings = r.get("findings") or []
        qs = r.get("questions") or []
        a, b = metrics(qs, findings), metrics(now(json.loads(json.dumps(qs)), findings), findings)
        for k in a:
            tot_a[k] = tot_a.get(k, 0) + a[k]
            tot_b[k] = tot_b.get(k, 0) + b[k]
        rows.append((name, a, b))
    keys = ["questions", "over_cap", "critical_without", "similar_pairs", "no_if_no_answer", "one_option"]
    head = ["Отчёт", "вопросов", "сверх лимита", "critical без вопроса", "похожих пар", "без «если не ответят»", "< 2 вариантов"]
    if md:
        print("| " + " | ".join(head) + " |")
        print("| :--- |" + " ---: |" * (len(head) - 1))
    for name, a, b in rows + [("Итого", tot_a, tot_b)]:
        cells = [f"{a[k]} → {b[k]}" if a[k] != b[k] else str(a[k]) for k in keys]
        print(("| " + " | ".join([name] + cells) + " |") if md else f"{name:40} " + "  ".join(f"{c:>8}" for c in cells))
    return {"before": tot_a, "after": tot_b, "reports": len(rows)}


if __name__ == "__main__":
    main("--md" in sys.argv)
