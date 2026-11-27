"""Слепой набор (СЛ-4 от №35): прогон агента и счёт по ключам — только числа.

    python -m evaluation.v2.blind list  --dir evaluation/v2/blind                      # документы и ключи
    python -m evaluation.v2.blind run   --dir evaluation/v2/blind --out out/blind/sonnet_md --fmt md \\
                                         --provider claude_cli --model sonnet --no-cache
    python -m evaluation.v2.blind score --dir evaluation/v2/blind --out out/blind/sonnet_md [--json]

Раскладка (ветка `eval/blind4`): `<ID>.md|pdf|docx` и ключ `<ID>.key.json` (или `<ID>.gold.yaml`). Ключ приводится к
виду эталона официального документа (`score._normalize_gold`): список пунктов в `items`/`defects`/`findings` (или
сам список), у пункта — `id`, `severity`/`level`, `kind`/`type`, опоры — `quotes`/`quote`/`evidence`/`lines`/`anchors`,
ключевые слова — `keywords`. Документ без пунктов (или `expected: clean`) — чистый: любая находка — ложная тревога.

Счёт — тот же, что у новых ТЗ №18 (`newtz.score_case`): полнота по уровням, точность (вне ключа), серьёзность
(critical, которых нет в ключе), цитаты (найдены в документе), дубли, ложные на чистых. Ключи и тексты пунктов в
вывод не попадают: `score` печатает только числа, ID документа и ID пунктов ключа.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

from . import newtz
from .common import ROOT

FMTS = ("md", "pdf", "docx")


def _items(key) -> tuple[list, bool]:
    """Ключ → (пункты, чистый ли документ)."""
    if isinstance(key, list):
        return key, not key
    if str(key.get("expected") or key.get("variant") or "").lower() == "clean" or key.get("clean") is True:
        return [], True
    for k in ("items", "defects", "findings", "issues", "gold"):
        if isinstance(key.get(k), list):
            return key[k], not key[k]
    return [], True


def _anchors(it: dict) -> list[dict]:
    if it.get("anchors"):
        a = it["anchors"]
        return a["groups"] if isinstance(a, dict) else a
    groups = []
    ev = it.get("evidence") or it.get("quotes") or ([it["quote"]] if it.get("quote") else [])
    for e in ev:
        if isinstance(e, dict):
            q = e.get("quote") or e.get("text")
            ln = e.get("lines") or (f"{e['line_start']}-{e.get('line_end', e['line_start'])}"
                                    if e.get("line_start") else None)
            groups.append({k: v for k, v in (("quote", q), ("lines", ln)) if v})
        elif str(e).strip():
            groups.append({"quote": str(e)})
    if not groups and it.get("lines"):
        ls = it["lines"] if isinstance(it["lines"], list) else [it["lines"]]
        groups = [{"lines": str(x)} for x in ls]
    return groups


def key_to_gold(key, doc_md: Path) -> dict:
    """Ключ №35 → словарь эталона (как `gold.yaml`), документ — Markdown-версия (номера строк ключа — по ней)."""
    items, clean = _items(key)
    out = []
    for i, it in enumerate(items, 1):
        it = dict(it)
        g = {"id": str(it.get("id") or f"B{i:02d}"),
             "severity": str(it.get("severity") or it.get("level") or "major").lower(),
             "title": str(it.get("title") or it.get("summary") or it.get("essence") or ""),
             "anchors": {"groups": _anchors(it)}}
        kind = it.get("kind") or it.get("type") or it.get("category")
        if kind:
            g["kind"] = str(kind)
        kw = it.get("keywords")
        if kw:
            g["keywords"] = kw
        if it.get("severity_ok"):
            g["severity_ok"] = it["severity_ok"]
        out.append(g)
    return {"document": str(doc_md.resolve()), "items": out, **({"expected": "clean"} if clean else {})}


def discover(d: Path, fmt: str = "md", out: Path | None = None) -> list[dict]:
    """Кейсы для newtz: документ нужного формата + эталон, собранный из ключа (во временный gold.yaml в out)."""
    import yaml

    cases = []
    for md in sorted(d.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        cid = md.stem
        doc = d / f"{cid}.{fmt}"
        if not doc.exists():
            continue
        gold_path = None
        kj, gy = d / f"{cid}.key.json", d / f"{cid}.gold.yaml"
        if gy.exists():
            gold_path = gy
        elif kj.exists() and out is not None:
            gold = key_to_gold(json.loads(kj.read_text(encoding="utf-8")), md)
            gold_path = out / "gold" / f"{cid}.gold.yaml"
            gold_path.parent.mkdir(parents=True, exist_ok=True)
            gold_path.write_text(yaml.safe_dump(gold, allow_unicode=True, sort_keys=False), encoding="utf-8")
        clean = False
        if gold_path:
            g = yaml.safe_load(gold_path.read_text(encoding="utf-8")) or {}
            clean = g.get("expected") == "clean" or not (g.get("items") or g.get("defects"))
        cases.append({"case": cid, "variant": "clean" if clean else "defects", "doc": str(doc),
                      "gold": str(gold_path) if gold_path else None, "fmt": fmt})
    return cases


def numbers(rows: list[dict]) -> dict:
    """Только числа: полнота, точность, серьёзность, цитаты, дубли, ложные на чистых."""
    s = newtz.summarize([r for r in rows if r.get("variant")])
    defects = [r for r in rows if r.get("variant") == "defects" and r.get("items")]
    findings = sum(r.get("findings") or 0 for r in defects)
    outside = sum(r.get("outside") or 0 for r in defects)
    qt = sum(r.get("quotes_total") or 0 for r in rows)
    qm = sum(r.get("quotes_missing") or 0 for r in rows)
    h = s["harness"]
    return {
        "documents": len(rows), "failed": s["failed"],
        "recall": h["recall"], "found": h["tp"], "support": h["support"], "by_level": s["by_level"],
        "precision": (findings - outside) / findings if findings else None, "findings": findings, "outside": outside,
        "critical_false": h["critical_false"], "duplicates": h["duplicates"],
        "quotes": {"found": qt - qm, "total": qt},
        "clean": {k: s["clean"][k] for k in ("n", "false_alarms", "critical", "major", "verdict_no")},
        "time_s": s["time"]["total_s"], "calls": s["time"]["calls"], "cost_usd": s["time"]["cost_usd"],
        "per_doc": [{"doc": r["case"], "variant": r["variant"], "findings": r.get("findings"),
                     "found": len(r.get("found") or []), "of": r.get("items"),
                     "critical_false": len(r.get("critical_false") or []), "duplicates": r.get("duplicates"),
                     "false_alarms": len(r.get("false_alarms") or []) if r.get("variant") == "clean" else None,
                     "missed": [m["gold"] for m in r.get("misses") or []]} for r in rows],
    }


def keyless(cases: list[dict], out: Path) -> dict:
    """Без ключей: замечания по серьёзности, вердикт, цитаты (сверка агента), сбои, время — по каждому документу."""
    per = []
    for c in cases:
        rj = out / "reports" / newtz._key(c) / "report.json"
        if not rj.exists():
            continue
        rep = json.loads(rj.read_text(encoding="utf-8"))
        run, fs, v = rep.get("run") or {}, rep.get("findings") or [], rep.get("verdict") or {}
        ev = [e for f in fs for e in f.get("evidence") or []]
        per.append({"doc": c["case"], "fmt": c["fmt"], "status": run.get("status"), "findings": len(fs),
                    "by_severity": {s_: sum(1 for f in fs if f.get("severity") == s_)
                                    for s_ in ("critical", "major", "minor")},
                    "verdict": {"development": v.get("development"), "testing": v.get("testing")},
                    "quotes": {"verified": sum(1 for e in ev if str(e.get("verified") or "") in
                                               ("exact", "normalized", "fuzzy", "true", "True")), "total": len(ev)},
                    "duration_s": run.get("duration_s"), "calls": (run.get("calls") or {}).get("total"),
                    "cost_usd": run.get("cost_usd")})
    return {"documents": len(per), "failed": sum(1 for r in per if r["status"] not in ("complete", "ok")),
            "per_doc": per}


def _pct(x) -> str:
    return "—" if x is None else f"{round(100 * x)} %"


def render_numbers(n: dict, label: str) -> str:
    lv = n["by_level"]
    c = n["clean"]
    return "\n".join([
        f"| {label} | {n['documents']} | {n['found']}/{n['support']} ({_pct(n['recall'])}) | "
        f"{lv['critical']['n']}/{lv['critical']['of']} | {_pct(n['precision'])} ({n['outside']} вне ключа из "
        f"{n['findings']}) | {n['critical_false']} | {n['quotes']['found']}/{n['quotes']['total']} | "
        f"{n['duplicates']} | {c['critical']} / {c['false_alarms']} ({c['n']} чист.) | {round(n['time_s'] / 60, 1)} мин |"])


HEADER = ("| Прогон | Док. | Полнота | Critical ключа | Точность | Ложных critical | Цитаты | Дубли | "
          "Чистые: critical / всего ложных | Время |\n| :--- | ---: | :--- | :--- | :--- | ---: | :--- | ---: | :--- | :--- |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.blind", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("list", "run", "score"))
    ap.add_argument("--dir", default=str(ROOT / "evaluation" / "v2" / "blind"))
    ap.add_argument("--out", default=str(ROOT / "out" / "blind" / "run"))
    ap.add_argument("--fmt", choices=FMTS, default="md")
    ap.add_argument("--provider", default="mock")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    d, out = Path(a.dir), Path(a.out)
    cases = discover(d, a.fmt, out)
    if a.cmd == "list":
        for c in cases:
            print(f"{c['case']}\t{c['fmt']}\t{'ключ есть' if c['gold'] else 'ключа нет'}\t{c['variant']}")
        return 0
    if a.cmd == "run":
        cmd = newtz.DEFAULT_CMD + (" --no-cache" if a.no_cache else "")
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            for r in ex.map(lambda c: newtz.run_one(c, out, cmd, a.provider, a.model, a.timeout, True), cases):
                print(f"{r['key']}: rc={r['rc']} {r.get('seconds')} с")
        return 0
    rows = [newtz.score_case(c, out, "off") for c in cases if c["gold"]]
    if not rows:
        k = keyless(cases, out)
        if not k["per_doc"]:
            print("ключей нет и отчётов нет — считать не по чему")
            return 1
        print("ключей нет — только то, что считается без ключа:")
        print(json.dumps(k, ensure_ascii=False, indent=2))
        (out / "keyless.json").write_text(json.dumps(k, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    n = numbers(rows)
    if a.json:
        print(json.dumps(n, ensure_ascii=False, indent=2))
    else:
        print(HEADER)
        print(render_numbers(n, a.label or out.name))
    (out / "numbers.json").write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
