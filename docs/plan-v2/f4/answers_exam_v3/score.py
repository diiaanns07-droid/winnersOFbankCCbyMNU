"""Счёт экзамена ответов v3 строго по ключу (`key.json`), без модели и без ручных поправок.

    python docs/plan-v2/f4/answers_exam_v3/score.py <каталог_прогона> [--key key.json] [--json итог.json]

В каталоге прогона на каждый кейс — `<кейс>/answered.json` и `<кейс>/answered.revised.md` (выход run_exam.py).
Единица счёта — одна реплика владельца. Она засчитана, только если выполнены ВСЕ условия её ключа:

* ``resolved``  — каждый дефект закрыт (resolved или changed) и в answer_ids есть реплика (``by``);
* ``changed``   — каждый дефект именно changed (частичный ответ: снято не всё);
* ``open``      — каждый дефект не закрыт (нет в изменениях или статус open);
* ``conflict``  — у дефекта статус open и answer_conflict содержит все метки (или конфликт адресатов без вопроса
  в clarification.answer_conflicts с этими метками);
* ``postponed`` — вопрос в clarification.postponed или в unanswered (решение отложено, не выдумано);
* ``confirm``   — реплика в clarification.needs_confirmation (агент переспросил, не применил);
* ``new_conflict`` — в отчёте после ответов есть новый дефект (clarification.new_findings), одна из цитат которого
  на строках из списка;
* ``revised_contains`` / ``revised_not_contains`` — строки в исправленной редакции есть / нет (без учёта регистра,
  пробелов и неразрывных пробелов);
* ``any`` — список альтернативных наборов условий: достаточно одного.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(s: str) -> str:
    s = str(s or "").replace(" ", " ").replace(" ", " ").replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", s).strip().lower()


def label_hit(want: str, labels: list[str]) -> bool:
    """«Q-03» совпадает с «Q-03» и «Q-03.1»; «Q-03.2» — только с ним; «Решение-*» — с любым общим решением."""
    for x in labels or []:
        x = str(x)
        if want.endswith("*") and x.startswith(want[:-1]):
            return True
        if x == want or (("." not in want) and x.split(".")[0] == want):
            return True
    return False


class Case:
    def __init__(self, run_dir: Path, case: str):
        self.case = case
        p = run_dir / case / "answered.json"
        self.ok = p.is_file()
        self.r = json.loads(p.read_text(encoding="utf-8")) if self.ok else {}
        rv = run_dir / case / "answered.revised.md"
        self.revised = norm(rv.read_text(encoding="utf-8")) if rv.is_file() else ""
        self.cl = self.r.get("clarification") or {}
        self.changes = {c["finding_id"]: c for c in self.cl.get("changes") or []}
        self.after = {f.get("id"): f for f in self.r.get("findings") or []}


def check(c: Case, cond: dict, by: str) -> list[str]:
    """Пустой список — все условия выполнены; иначе — что не выполнено."""
    miss: list[str] = []
    if not c.ok:
        return ["нет answered.json"]
    if "any" in cond:
        alts = [check(c, alt, by) for alt in cond["any"]]
        if not any(not m for m in alts):
            miss.append("ни одна альтернатива: " + " | ".join("; ".join(m) for m in alts))
        rest = {k: v for k, v in cond.items() if k != "any"}
        return miss + (check(c, rest, by) if rest else [])
    for fid in cond.get("resolved", []):
        ch = c.changes.get(fid)
        if not ch or ch["status"] not in ("resolved", "changed"):
            miss.append(f"{fid} не закрыт ({ch['status'] if ch else 'нет в изменениях'})")
        elif not label_hit(cond.get("by", by), ch.get("answer_ids") or []):
            miss.append(f"{fid} закрыт не той репликой ({ch.get('answer_ids')})")
    for fid in cond.get("changed", []):
        ch = c.changes.get(fid)
        if not ch or ch["status"] != "changed":
            miss.append(f"{fid} не changed ({ch['status'] if ch else 'нет в изменениях'})")
    for fid in cond.get("open", []):
        ch = c.changes.get(fid)
        if ch and ch["status"] != "open":
            miss.append(f"{fid} должен остаться открытым, а {ch['status']} ({ch.get('answer_ids')})")
    if "conflict" in cond:
        want = cond["conflict"]
        fid, labels = want.get("finding"), want["labels"]
        ok = False
        for ac in c.cl.get("answer_conflicts") or []:
            if (fid is None or ac.get("finding_id") in (fid, None)) and all(label_hit(x, ac.get("answers") or [])
                                                                           for x in labels):
                ok = True
        ch = c.changes.get(fid) if fid else None
        if ch and ch["status"] != "open":
            ok = False
        if not ok:
            miss.append(f"нет конфликта {labels} по {fid} "
                        f"(конфликты: {[(a.get('finding_id'), a.get('answers')) for a in c.cl.get('answer_conflicts') or []]}"
                        f"{', статус ' + ch['status'] if ch else ''})")
    if "postponed" in cond:
        q = cond["postponed"]
        if not (any(p.get("question_id") == q for p in c.cl.get("postponed") or [])
                or q in (c.cl.get("unanswered") or [])):
            miss.append(f"{q} не отложен и не без ответа")
    if "confirm" in cond:
        q = cond["confirm"]
        hits = [p for p in c.cl.get("needs_confirmation") or [] if p.get("question_id") == q.get("question_id")
                and norm(q.get("topic", "")) in norm(p.get("topic", ""))]
        if not hits:
            miss.append(f"нет переспроса {q}")
    if "asked" in cond:
        snip = norm(cond["asked"])
        pend = [p for p in c.cl.get("needs_confirmation") or [] if snip in norm(p.get("text", ""))]
        warn = [w for w in c.cl.get("warnings") or [] if snip in norm(w)
                and re.search(r"подтверд|уточн|переспрос", norm(w))]
        if not pend and not warn:
            miss.append(f"не переспросил про «{cond['asked']}»")
    if "not_closed_by" in cond:
        snip = norm(cond["not_closed_by"])
        labels = [f"Решение-{i + 1}" for i, d in enumerate(c.cl.get("decisions") or []) if snip in norm(d)]
        labels += [r["label"] for a in c.cl.get("answers") or [] for r in a.get("replies") or []
                   if snip in norm(r.get("text", ""))]
        for fid, ch in c.changes.items():
            if ch["status"] in ("resolved", "changed") and set(labels) & set(ch.get("answer_ids") or []):
                miss.append(f"«{cond['not_closed_by']}» ({', '.join(labels)}) закрыл {fid}")
    if "new_conflict" in cond:
        lines = set(cond["new_conflict"])
        hit = False
        for nid in c.cl.get("new_findings") or []:
            f = c.after.get(nid) or {}
            for e in f.get("evidence") or []:
                a, b = int(e.get("line_start") or e.get("line") or 0), int(e.get("line_end") or e.get("line") or 0)
                if any(a <= x <= max(a, b) for x in lines):
                    hit = True
        if not hit:
            miss.append(f"нет нового дефекта на строках {sorted(lines)} (новые: {c.cl.get('new_findings')})")
    for s in cond.get("revised_contains", []):
        if norm(s) not in c.revised:
            miss.append(f"в редакции нет «{s}»")
    for s in cond.get("revised_not_contains", []):
        if norm(s) in c.revised:
            miss.append(f"в редакции есть «{s}»")
    return miss


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--key", default=str(HERE / "key.json"))
    p.add_argument("--json")
    a = p.parse_args(argv)
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    run_dir = Path(a.run_dir)
    cases: dict[str, Case] = {}
    rows, by_class = [], {}
    for u in key["units"]:
        c = cases.setdefault(u["case"], Case(run_dir, u["case"]))
        miss = check(c, u["expect"], u["reply"])
        ok = not miss
        rows.append({"id": u["id"], "case": u["case"], "class": u["class"], "type": u["type"], "ok": ok, "miss": miss})
        t = by_class.setdefault(u["class"], [0, 0])
        t[0] += ok
        t[1] += 1
    total = sum(r["ok"] for r in rows)
    for r in rows:
        print(f"{'✔' if r['ok'] else '✘'} {r['id']:<8} {r['class']:<14} {r['type']:<12} " + "; ".join(r["miss"]))
    print("—" * 60)
    for k, (x, n) in by_class.items():
        print(f"{k}: {x}/{n}")
    print(f"ИТОГО: {total}/{len(rows)}")
    th = key.get("threshold") or {}
    if th:
        contra = by_class.get("contradictory", [0, 0])[0]
        passed = total >= th.get("total", 0) and contra >= th.get("contradictory", 0)
        print(f"Порог {th.get('total')}/{len(rows)} и {th.get('contradictory')}/{by_class.get('contradictory', [0, 0])[1]}"
              f" противоречивых: {'пройден' if passed else 'НЕ пройден'}")
    if a.json:
        Path(a.json).write_text(json.dumps({"total": total, "n": len(rows), "by_class": by_class, "rows": rows},
                                           ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
