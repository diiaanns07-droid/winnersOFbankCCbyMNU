"""Замер этапа набора (№09) отдельно: корпус `evaluation/dev`, новые ТЗ `evaluation/v2/open2`, официальный документ.

    python tests/v2/fixtures/09_tools/stage_bench.py run --set corpus|open2|official|all --model haiku \
        --label h1 [--jobs 4] [--repeat 3] [--no-cache] [--cases a,b]
    python tests/v2/fixtures/09_tools/stage_bench.py score --label h1

Нарезка — эвристика кода (без модели), один вызов модели на документ, разбор — `consistency.postprocess`.
Ответы модели и выход этапа пишутся в `out/09_bench/<label>/<кейс>[.<повтор>].json` (сырой ответ можно записать
в фикстуры тестов). Счёт — по строкам-опорам меток (±1 строка): корпус — `labels.jsonl`, новые ТЗ — `gold.yaml`
кейса, официальный — `evaluation/v2/official/gold.yaml`. Это счёт этапа до судьи, без арбитра.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from bcc_review.v2.context import Context  # noqa: E402
from bcc_review.v2.pipeline import DEFAULTS, load_view, make_llm  # noqa: E402
from bcc_review.v2.stages import consistency, segment  # noqa: E402

CORPUS = ROOT / "evaluation" / "dev" / "corpus"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OUT = ROOT / "out" / "09_bench"
CONFLICT = ("event_conflict", "status_conflict", "boundary_conflict", "unit_mismatch", "contradiction")


def cases(which: str) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if which in ("corpus", "all"):
        for d in sorted((CORPUS / "cases").iterdir()):
            if d.name != "edge.empty" and (d / "source.md").exists():
                out.append((d.name, d / "source.md"))
    if which in ("open2", "all"):
        for d in sorted(OPEN2.iterdir()):
            if d.is_dir() and (d / "source.md").exists() and d.name != "insurance_inject":
                out.append(("open2." + d.name, d / "source.md"))
    if which in ("official", "all"):
        out.append(("official", OFFICIAL))
    return out


class Recorder:
    def __init__(self, llm):
        self.llm, self.raw = llm, []

    def ask(self, stage, system, user, schema, **kw):
        data = self.llm.ask(stage, system, user, schema, **kw)
        self.raw.append(data)
        return data


def run_case(name: str, path: Path, opts: dict, dest: Path) -> dict:
    view = load_view(path)
    seg = segment.heuristic_segment(view)
    llm, _ = make_llm(opts, None, path)
    rec = Recorder(llm)
    ctx = Context(view=view, llm=rec, options=opts, requirements=seg["requirements"], excluded=seg.get("excluded", []))
    t0 = time.monotonic()
    err = ""
    try:
        out = consistency.run(ctx)
    except Exception as exc:  # noqa: BLE001
        out, err = {"candidates": [], "pair_checks": [], "trace": [], "glossary": []}, f"{type(exc).__name__}: {exc}"
    sec = round(time.monotonic() - t0, 1)
    raw = rec.raw[-1] if rec.raw else {}
    res = {"case": name, "doc": str(path.relative_to(ROOT)), "seconds": sec, "error": err, "warnings": ctx.warnings,
           "stats": dict(getattr(llm, "stats", {}) or {}), "raw": raw, "requirements": seg["requirements"], "output": out}
    dest.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def cmd_run(a) -> int:
    opts = {**DEFAULTS, "provider": a.provider, "model": a.model, "cache": not a.no_cache, "effort": a.effort,
            "max_calls": 4, "stage_timeout": 600.0}
    todo = cases(a.set)
    if a.cases:
        want = set(a.cases.split(","))
        todo = [c for c in todo if c[0] in want or c[0].split(".", 1)[-1] in want or any(w in c[0] for w in want)]
    dest = OUT / a.label
    dest.mkdir(parents=True, exist_ok=True)
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for name, path in todo:
            for r in range(a.repeat):
                suffix = f".{r + 1}" if a.repeat > 1 else ""
                jobs.append(ex.submit(run_case, name, path, opts, dest / f"{name}{suffix}.json"))
        for f in cf.as_completed(jobs):
            res = f.result()
            o = res["output"]
            print(f"{res['case']}: {res['seconds']} с, кандидатов {len(o['candidates'])}, пар {len(o['pair_checks'])}"
                  + (f", ОШИБКА {res['error']}" if res["error"] else ""), flush=True)
    return 0


# ---------------------------------------------------------------- счёт

def _ev_lines(c: dict) -> set[int]:
    s: set[int] = set()
    for e in c.get("evidence") or []:
        if e.get("verified") in (None, "", "missing"):
            continue
        a = int(e.get("line_start") or e.get("line") or 0)
        b = int(e.get("line_end") or a)
        s.update(range(a, b + 1))
    return s


def _hit(lines: set[int], group_lines: set[int], slack: int = 1) -> bool:
    return any(abs(x - y) <= slack for x in lines for y in group_lines)


def _parse_lines(spec) -> set[int]:
    out: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return out


def corpus_labels() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in (CORPUS / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            lab = json.loads(line)
            out.setdefault(lab["case_id"], []).append(lab)
    return out


def gold_items(path: Path) -> list[dict]:
    import yaml
    g = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = []
    for it in g.get("items") or []:
        anc = it.get("anchors") or {}
        groups = [_parse_lines(gr.get("lines")) for gr in anc.get("groups") or [] if gr.get("lines")]
        items.append({"id": it["id"], "level": it.get("level"), "policy": anc.get("policy", "all"), "groups": groups,
                      "title": it.get("title", ""), "kinds": it.get("kinds") or []})
    return items


def _covers(c: dict, policy: str, groups: list[set[int]]) -> bool:
    lines = _ev_lines(c)
    if not groups:
        return False
    hits = [_hit(lines, g) for g in groups]
    return all(hits) if policy == "all" else any(hits)


def score_file(res: dict, labels: dict[str, list[dict]]) -> dict:
    name = res["case"]
    cands = res["output"]["candidates"]
    sev = {s: sum(1 for c in cands if c["severity"] == s) for s in ("critical", "major", "minor")}
    conflicts = [c for c in cands if c.get("origin") == "pair_check" and c["kind"] in CONFLICT]
    row = {"case": name, "seconds": res["seconds"], "n": len(cands), "sev": sev, "conflicts": len(conflicts),
           "pairs": len(res["output"]["pair_checks"]), "error": res["error"], "found": [], "missed": [], "false_crit": []}
    out_tok = (res.get("stats") or {}).get("tokens_out")
    row["out_tokens"] = out_tok
    if name.startswith("open2.") or name == "official":
        from evaluation.v2 import score as sc
        gpath = (OPEN2 / name.split(".", 1)[1] / "gold.yaml") if name != "official" else sc.DEFAULT_GOLD
        gold = sc.load_gold(gpath)
        rep = sc.as_report({"candidates": cands}, gold)
        res = sc.score_report(rep, gold, arbiter="off")
        row["clean"] = name.endswith("_clean")
        crit = res["recall"]["critical"]
        row["found"] = [k + ("!" if k in crit["as_critical"] else "") for k in crit["found"]] + list(res["recall"]["major"]["found"])
        row["missed"] = [g["id"] for g in gold["items"] if g.get("level") in ("critical", "major")
                         and g["id"] not in crit["found"] and g["id"] not in res["recall"]["major"]["found"]]
        row["false_crit"] = [x["title"][:80] for x in res["severity"]["critical_false"]]
        if row["clean"]:
            row["false_crit"] = [c["title"][:80] for c in cands if c["severity"] == "critical"]
        row["k"] = f"{crit['n']}/{crit['of']} (cr {len(crit['as_critical'])})"
        row["c"] = f"{res['recall']['major']['n']}/{res['recall']['major']['of']}"
    else:
        labs = labels.get(name, [])
        row["clean"] = any(l["expected_outcome"] == "clean" for l in labs)
        for l in labs:
            if l["expected_outcome"] != "present":
                continue
            groups = [{int(a["locator"].split(":L")[1])} for a in l["anchors"] if ":L" in a.get("locator", "")]
            hit = next((c for c in cands if _covers(c, l.get("anchor_policy", "all"), groups)), None)
            tag = f"{l['issue_type']}"
            if hit is not None:
                row["found"].append(tag + ("!" if hit["severity"] == "critical" else ""))
            else:
                row["missed"].append(tag)
        if row["clean"]:
            row["false_crit"] = [c["title"][:90] for c in cands if c["severity"] == "critical"]
    return row


def cmd_score(a) -> int:
    labels = corpus_labels()
    rows = []
    for p in sorted((OUT / a.label).glob("*.json")):
        rows.append(score_file(json.loads(p.read_text(encoding="utf-8")), labels) | {"file": p.stem})
    lines = ["| Кейс | с | ток. | пар | конфл. | cr/maj/min | найдено (! — critical) | промах | ложные critical |",
             "| :--- | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |"]
    agg = {"conf_found": 0, "conf_total": 0, "clean_conf": 0, "clean_crit": 0, "clean_n": 0, "clean_major": 0,
           "secs": [], "all_found": 0, "all_total": 0}
    for r in rows:
        s = r["sev"]
        lines.append(f"| {r['file']} | {r['seconds']} | {r['out_tokens'] or ''} | {r['pairs']} | {r['conflicts']} | "
                     f"{s['critical']}/{s['major']}/{s['minor']} | {', '.join(r['found'])} | {', '.join(r['missed'])} | "
                     f"{'; '.join(r['false_crit'])} |" + (f" ОШИБКА {r['error']}" if r["error"] else ""))
        agg["secs"].append(r["seconds"])
        if r["clean"]:
            agg["clean_n"] += 1
            agg["clean_conf"] += r["conflicts"]
            agg["clean_crit"] += s["critical"]
            agg["clean_major"] += s["major"]
        agg["all_found"] += len(r["found"])
        agg["all_total"] += len(r["found"]) + len(r["missed"])
        for t in r["found"] + r["missed"]:
            base = t.rstrip("!")
            if base in ("range_boundary", "boundary_conflict", "event_conflict", "status_conflict", "unit_mismatch"):
                agg["conf_total"] += 1
                agg["conf_found"] += t in r["found"]
    secs = sorted(agg["secs"])
    lines.append("")
    for r in rows:
        if r.get("k"):
            lines.append(f"* {r['file']}: К {r['k']}, С {r['c']}, ложных critical {len(r['false_crit'])}")
    lines.append(f"Метки корпуса-противоречия: {agg['conf_found']}/{agg['conf_total']}; все пункты: "
                 f"{agg['all_found']}/{agg['all_total']}; чистых {agg['clean_n']}: конфликтов {agg['clean_conf']}, "
                 f"critical {agg['clean_crit']}, major {agg['clean_major']}; время медиана "
                 f"{secs[len(secs) // 2] if secs else 0} с, макс {secs[-1] if secs else 0} с.")
    text = "\n".join(lines)
    print(text)
    (OUT / a.label / "_score.md").write_text(text + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", default="all")
    r.add_argument("--cases", default="")
    r.add_argument("--provider", default="claude_cli")
    r.add_argument("--model", default="haiku")
    r.add_argument("--effort", default=None)
    r.add_argument("--label", required=True)
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--no-cache", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--label", required=True)
    a = ap.parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_score(a)


if __name__ == "__main__":
    raise SystemExit(main())
