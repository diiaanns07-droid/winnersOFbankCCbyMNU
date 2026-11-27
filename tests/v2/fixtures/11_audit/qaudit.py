"""№11: замер вопросов владельцу по отчёту агента (и эталону, если есть score.json счётчика №15).

    python tests/v2/fixtures/11_audit/qaudit.py report.json [--score score.json] [--json out.json]

Что считает (всё кодом, без модели):
* вопросов, блокирующих; у скольких цитаты обеих сторон (у конфликтов), 2–4 варианта, варианты с числами;
* понятность: внутренние коды (D-…, R-…, L038, lens:…), латиница вне словаря документа, длина вопроса;
* по эталону (score.json): какие пункты К/С закрывает вопрос (через дефекты, сопоставленные эталону),
  покрытие К вопросами, доля «полезных» вопросов (закрывают хотя бы один пункт К или С эталона).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from bcc_review.v2.stages import clarify  # noqa: E402

LATIN_ALLOW = {
    "iso", "iec", "ieee", "http", "https", "api", "rest", "json", "url", "ui", "id", "sms", "push", "kzt", "utc",
    "get", "post", "put", "patch", "delete", "qr", "ios", "android", "pdf", "true", "false", "null", "ok",
    "usd", "eur", "rub", "sla", "uuid", "ttl", "otp", "pin", "pan", "cvv", "iban",
}
_CODE = re.compile(r"\b(?:[DRCQT]-\d{1,3}|L\d{2,4}|lens:\w+|rules:\w+|same_subject|set_(?:consistent|complete|feasible))\b")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_NUM = re.compile(r"\d")


def doc_vocab(report: dict) -> set[str]:
    path = report.get("document", {}).get("file")
    vocab: set[str] = set()
    texts = [r.get("quote", "") for r in report.get("requirements") or []]
    for f in report.get("findings_before") or report.get("findings") or []:
        texts += [e.get("quote", "") for e in f.get("evidence") or []]
    for t in texts:
        for w in _LATIN.findall(t or ""):
            vocab.add(w.lower())
    return vocab


def latin_invented(text: str, vocab: set[str]) -> list[str]:
    out = []
    for w in _LATIN.findall(text or ""):
        lw = w.lower()
        if len(lw) < 2 or lw in LATIN_ALLOW or lw in vocab:
            continue
        out.append(w)
    return out


def audit(report: dict, score: dict | None = None, vocab: set[str] | None = None) -> dict:
    findings = {f["id"]: f for f in (report.get("findings_before") or report.get("findings") or [])}
    qs = report.get("questions") or []
    vocab = vocab if vocab is not None else doc_vocab(report)
    gold_of: dict[str, set[str]] = {}
    if score:
        for row in (score.get("assignment") or []) + (score.get("duplicates") or []):
            gold_of.setdefault(row["finding"], set()).add(row["gold"])
    rows = []
    for q in qs:
        linked = [findings[i] for i in q.get("finding_ids") or [] if i in findings]
        sev = sorted({f.get("severity") for f in linked}, key=lambda s: clarify._SEV_RANK.get(s, 3))
        lines = {e.get("line_start") for e in q.get("evidence") or []}
        conflict = any(f.get("kind") in clarify.CONFLICT_KINDS for f in linked)
        opts = q.get("options") or []
        text_all = " ".join([q.get("question", ""), q.get("why", ""), *opts])
        gold = sorted({g for f in linked for g in gold_of.get(f["id"], ())})
        rows.append({
            "id": q["id"], "topic": q.get("topic", ""), "blocking": bool(q.get("blocking")), "severity": sev[:1] or ["?"],
            "findings": [f["id"] for f in linked], "gold": gold,
            "useful": any(g[0] in "КС" for g in gold),
            "conflict": conflict, "both_sides": (len(lines) >= 2) if conflict else None,
            "options": len(opts), "options_with_numbers": sum(1 for o in opts if _NUM.search(o)),
            "codes": sorted(set(_CODE.findall(text_all))), "latin": sorted(set(latin_invented(text_all, vocab))),
            "q_words": len(q.get("question", "").split()),
        })
    n = len(rows)
    out = {
        "questions": n, "blocking": sum(r["blocking"] for r in rows),
        "on_critical": sum(1 for r in rows if r["severity"][0] == "critical"),
        "on_major": sum(1 for r in rows if r["severity"][0] == "major"),
        "conflicts_both_sides": f"{sum(1 for r in rows if r['both_sides'])}/{sum(1 for r in rows if r['conflict'])}",
        "options_ok": sum(1 for r in rows if 2 <= r["options"] <= 4),
        "options_with_numbers": f"{sum(r['options_with_numbers'] for r in rows)}/{sum(r['options'] for r in rows)}",
        "with_codes": sum(1 for r in rows if r["codes"]), "with_latin": sum(1 for r in rows if r["latin"]),
        "q_words_max": max((r["q_words"] for r in rows), default=0),
        "rows": rows,
    }
    if score:
        k_found = sorted(set(score.get("recall", {}).get("critical", {}).get("found") or []))
        s_found = sorted(set(score.get("recall", {}).get("major", {}).get("found") or []))
        covered = {g for r in rows for g in r["gold"]}
        out.update({
            "useful": sum(r["useful"] for r in rows),
            "precision": round(sum(r["useful"] for r in rows) / n, 2) if n else None,
            "K_found": k_found, "K_covered": sorted(set(k_found) & covered),
            "S_found": len(s_found), "S_covered": len(set(s_found) & covered),
        })
        # блокирующий вопрос без пункта К эталона — лишняя тревога для владельца
        out["blocking_not_K"] = sum(1 for r in rows if r["blocking"] and not any(g.startswith("К") for g in r["gold"]))
    return out


def summary_line(name: str, a: dict) -> str:
    s = (f"{name}: вопросов {a['questions']} (блок. {a['blocking']}, на critical {a['on_critical']}, major {a['on_major']}); "
         f"обе стороны {a['conflicts_both_sides']}; варианты 2–4: {a['options_ok']}/{a['questions']}; с числами "
         f"{a['options_with_numbers']}; с кодами {a['with_codes']}; с латиницей {a['with_latin']}")
    if "precision" in a:
        s += (f"; полезных {a['useful']}/{a['questions']}; К закрыто {len(a['K_covered'])}/{len(a['K_found'])} "
              f"{a['K_covered']}; С закрыто {a['S_covered']}/{a['S_found']}; блок. не по К {a['blocking_not_K']}")
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--score")
    ap.add_argument("--json")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
    sc = json.loads(Path(a.score).read_text(encoding="utf-8")) if a.score else None
    res = audit(rep, sc)
    print(summary_line(Path(a.report).name, res))
    if a.v:
        for r in res["rows"]:
            print(f"  {r['id']} {'Б' if r['blocking'] else ' '} {r['severity'][0]:8} {','.join(r['gold']) or '—':12} "
                  f"вар {r['options']} чис {r['options_with_numbers']} {'коды ' + str(r['codes']) if r['codes'] else ''}"
                  f"{' лат ' + str(r['latin']) if r['latin'] else ''} | {r['topic']}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
