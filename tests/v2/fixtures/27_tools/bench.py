"""Замер этапа набора (№27) отдельно, на чистых ТЗ и на документах с заложенными конфликтами.

    python tests/v2/fixtures/27_tools/bench.py run --set clean|conf|official|all --model haiku --label h0 [--jobs 5]
    python tests/v2/fixtures/27_tools/bench.py repost --from h0 --label h0r     # пересчёт ответов текущим кодом
    python tests/v2/fixtures/27_tools/bench.py score --label h0 [--list]          # сводка (и список замечаний)

Наборы:
* ``clean`` — 20 чистых документов: корпус (`evaluation/dev/corpus`, 8 без пустого), open2 (`*_clean`, 4),
  чистые ТЗ №20 (`evaluation/v2/clean`, 8). Любое замечание этапа на них — ложное;
* ``conf`` — мутанты корпуса с заложенным противоречием (20) и дефектные open2 (4);
* ``official`` — официальный документ (К1–К5 эталона).

Нарезка — эвристика кода (как у №09 `stage_bench.py`), один вызов модели на документ. Каталог прогона —
`tests/v2/fixtures/27_runs/<label>/<кейс>.json`: сырой ответ модели (`raw`), требования нарезки и выход этапа;
`repost` пересчитывает выход текущим кодом без модели. Счёт противоречий и К — функциями `stage_bench.py` №09.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("stage_bench09", ROOT / "tests/v2/fixtures/09_tools/stage_bench.py")
SB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SB)  # type: ignore[union-attr]

from bcc_review.v2.pipeline import DEFAULTS, load_view  # noqa: E402
from bcc_review.v2.stages import consistency  # noqa: E402

CORPUS = ROOT / "evaluation" / "dev" / "corpus"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
CLEAN20 = ROOT / "evaluation" / "v2" / "clean"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OUT = ROOT / "tests" / "v2" / "fixtures" / "27_runs"
CONF_TYPES = ("range_boundary", "boundary_conflict", "event_conflict", "status_conflict", "unit_mismatch")


def _corpus_kinds() -> dict[str, set]:
    out: dict[str, set] = {}
    for line in (CORPUS / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            lab = json.loads(line)
            out.setdefault(lab["case_id"], set()).add((lab["expected_outcome"], lab["issue_type"]))
    return out


def cases(which: str) -> list[tuple[str, Path]]:
    labs = _corpus_kinds()
    out: list[tuple[str, Path]] = []
    if which in ("clean", "all"):
        for name, kinds in sorted(labs.items()):
            if name != "edge.empty" and any(o == "clean" for o, _ in kinds):
                out.append((name, CORPUS / "cases" / name / "source.md"))
        for d in sorted(OPEN2.iterdir()):
            if d.is_dir() and d.name.endswith("_clean"):
                out.append(("open2." + d.name, d / "source.md"))
        for d in sorted(CLEAN20.iterdir()):
            if d.is_dir() and (d / "source.md").exists():
                out.append(("clean20." + d.name, d / "source.md"))
    if which in ("conf", "all"):
        for name, kinds in sorted(labs.items()):
            if any(o == "present" and t in CONF_TYPES for o, t in kinds):
                out.append((name, CORPUS / "cases" / name / "source.md"))
        for d in sorted(OPEN2.iterdir()):
            if d.is_dir() and (d / "source.md").exists() and not d.name.endswith("_clean") \
                    and d.name not in ("insurance_inject", "results"):
                out.append(("open2." + d.name, d / "source.md"))
    if which in ("official", "all"):
        out.append(("official", OFFICIAL))
    return out


def is_clean(name: str) -> bool:
    return name.startswith("clean20.") or name.endswith("_clean") or name in {
        n for n, k in _corpus_kinds().items() if any(o == "clean" for o, _ in k)}


def cmd_run(a) -> int:
    opts = {**DEFAULTS, "provider": a.provider, "model": a.model, "cache": not a.no_cache, "effort": a.effort,
            "max_calls": 4, "stage_timeout": 600.0}
    todo = cases(a.set)
    if a.cases:
        want = set(a.cases.split(","))
        todo = [c for c in todo if c[0] in want or any(w in c[0] for w in want)]
    dest = OUT / a.label
    dest.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(SB.run_case, name, path, opts, dest / f"{name}.json") for name, path in todo]
        for f in cf.as_completed(futs):
            res = f.result()
            o = res["output"]
            print(f"{res['case']}: {res['seconds']} с, кандидатов {len(o['candidates'])}"
                  + (f", ОШИБКА {res['error']}" if res["error"] else ""), flush=True)
    return cmd_score(a)


def cmd_repost(a) -> int:
    src, dest = OUT / a.src, OUT / a.label
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.glob("*.json")):
        res = json.loads(p.read_text(encoding="utf-8"))
        if not res.get("raw"):
            continue
        view = load_view(ROOT / res["doc"])
        res["output"] = consistency.postprocess(res["raw"], view, res["requirements"])
        (dest / p.name).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return cmd_score(a)


def _quotes(c: dict) -> str:
    return " ↔ ".join(f"L{e.get('line_start') or e.get('line')}«{(e.get('quote') or '')[:60]}»" for e in c["evidence"])


def score_rows(label: str) -> list[dict]:
    labels = SB.corpus_labels()
    rows = []
    for p in sorted((OUT / label).glob("*.json")):
        res = json.loads(p.read_text(encoding="utf-8"))
        name = res["case"]
        if name.startswith("clean20."):  # эталон пустой: всё — ложное
            cands = res["output"]["candidates"]
            sev = {s: sum(1 for c in cands if c["severity"] == s) for s in ("critical", "major", "minor")}
            conflicts = [c for c in cands if c.get("origin") == "pair_check" and c["kind"] in SB.CONFLICT]
            row = {"case": name, "seconds": res["seconds"], "n": len(cands), "sev": sev, "conflicts": len(conflicts),
                   "error": res["error"], "found": [], "missed": [], "clean": True}
        else:
            row = SB.score_file(res, labels)
        row["clean"] = is_clean(name)
        row["cands"] = res["output"]["candidates"]
        row["file"] = p.stem
        rows.append(row)
    return rows


def cmd_score(a) -> int:
    rows = score_rows(a.label)
    lines = ["| Кейс | с | cr/maj/min | конфл. | найдено (! — critical) | промах |", "| :--- | ---: | :--- | ---: | :--- | :--- |"]
    agg = {"clean_n": 0, "clean_cr": 0, "clean_maj": 0, "clean_over1": 0, "conf_found": 0, "conf_total": 0}
    for r in rows:
        s = r["sev"]
        lines.append(f"| {r['file']} | {r['seconds']} | {s['critical']}/{s['major']}/{s['minor']} | {r['conflicts']} | "
                     f"{', '.join(r['found'])} | {', '.join(r['missed'])} |" + (f" ОШИБКА {r['error']}" if r["error"] else ""))
        if r["clean"]:
            agg["clean_n"] += 1
            agg["clean_cr"] += s["critical"]
            agg["clean_maj"] += s["major"]
            agg["clean_over1"] += s["major"] > 1
        for t in r["found"] + r["missed"]:
            if t.rstrip("!") in CONF_TYPES:
                agg["conf_total"] += 1
                agg["conf_found"] += t in r["found"]
    lines.append("")
    for r in rows:
        if r.get("k"):
            lines.append(f"* {r['file']}: К {r['k']}, С {r['c']}, найдено: {', '.join(r['found'])}")
    lines.append(f"Чистых {agg['clean_n']}: critical {agg['clean_cr']}, major {agg['clean_maj']}, документов с major > 1: "
                 f"{agg['clean_over1']}. Противоречия корпуса и open2: {agg['conf_found']}/{agg['conf_total']}.")
    if getattr(a, "list", False):
        lines.append("\n## Замечания critical и major на чистых\n")
        for r in rows:
            if not r["clean"]:
                continue
            for c in r["cands"]:
                if c["severity"] in ("critical", "major"):
                    lines.append(f"* **{r['file']}** {c['severity']} {c['kind']} [{c.get('origin')}"
                                 f"{'/' + c.get('resolved_by', '') if c.get('resolved_by') else ''}] {c['title']} — {_quotes(c)}")
    text = "\n".join(lines)
    print(text)
    (OUT / a.label / "_score.md").write_text(text + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", default="clean")
    r.add_argument("--model", default="haiku")
    r.add_argument("--provider", default="claude_cli")
    r.add_argument("--label", required=True)
    r.add_argument("--jobs", type=int, default=5)
    r.add_argument("--no-cache", action="store_true")
    r.add_argument("--effort", default=None)  # как в продукте (DEFAULTS)
    r.add_argument("--cases", default="")
    r.add_argument("--list", action="store_true")
    rp = sub.add_parser("repost")
    rp.add_argument("--from", dest="src", required=True)
    rp.add_argument("--label", required=True)
    rp.add_argument("--list", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--label", required=True)
    s.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "repost": cmd_repost, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
