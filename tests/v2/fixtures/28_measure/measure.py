"""Замер линз «Аналитик» и «Тестировщик» (№28) до судьи: официальный, 4 чистых ТЗ №18, корпус `evaluation/dev`.

    python tests/v2/fixtures/28_measure/measure.py run   --lens qa --label base --rep r1 --sets official,open2c,corpusc
    python tests/v2/fixtures/28_measure/measure.py score --lens qa --label base --rep r1
    python tests/v2/fixtures/28_measure/measure.py union --labels qa:base:r1,analyst:base:r1

Документ: mock-прогон каркаса (нарезка — фикстура официального или эвристика кода, бесплатно) → `stage lens_<линза>`
с настоящей моделью. Ответы модели кэшируются в `out/28/cache/<rep>`: тот же промпт и та же реплика — ответ из кэша,
поэтому правка постобработки пересчитывается повтором `run` без вызовов, а правка промпта даёт новый вызов.
Результаты — `out/28/<линза>/<метка>_<реплика>/<кейс>.json`, сводка — `summary.md` там же.

Наборы: `official`; `open2c` — 4 чистых ТЗ №18 (`*_clean`); `open2d` — 4 дефектных ТЗ №18; `corpusc` — 8 чистых
корпуса; `corpus` — весь корпус (32 документа, без `edge.empty`).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "out" / "28"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
OWNER = {"qa": "qa", "analyst": "analyst"}


def cases(sets: list[str], only: list[str] | None = None) -> list[dict]:
    out: list[dict] = []
    if "official" in sets:
        out.append({"set": "official", "id": "official", "path": ROOT / "release/input/requirements.md",
                    "mock": ROOT / "tests/v2/fixtures/official", "expected": "defects", "gold": None})
    for tag, names in (("open2c", ("grace_clean", "qr_clean", "capital_clean", "insurance_clean")),
                       ("open2d", ("grace", "qr", "capital", "insurance"))):
        if tag in sets:
            for k in names:
                out.append({"set": "open2", "id": k, "path": OPEN2 / k / "source.md", "gold": OPEN2 / k / "gold.yaml",
                            "expected": "clean" if k.endswith("_clean") else "defects", "mock": None})
    if "corpus" in sets or "corpusc" in sets:
        from evaluation.v2 import corpus as cp
        for c in cp.select_cases("md", None):
            if c["case_id"] == "edge.empty" or ("corpus" not in sets and c["expected"] != "clean"):
                continue
            out.append({"set": "corpus", "id": c["case_id"], "path": Path(c["path"]), "sha256": c["sha256"],
                        "expected": c["expected"], "mock": None, "gold": None})
    if only:
        out = [c for c in out if any(c["id"] == x or c["id"].startswith(x) for x in only)]
    return out


def _py(*args: str, timeout: int = 900, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-m", "bcc_review", *args], cwd=str(ROOT), capture_output=True,
                          text=True, timeout=timeout, env=env)





def segmentation(c: dict) -> tuple[str, dict | None]:
    """Нарезка для базового прогона: официальный — фикстура mock (модель); остальное — эвристика кода (так мерил
    №06: строки приёмки она размечает так же, как модель). Без этого mock для чужого документа отдаёт нарезку
    официального ТЗ (каталог фикстур по умолчанию)."""
    if c["set"] == "official":
        return "fixture", None
    from bcc_review.v2 import docview
    from bcc_review.v2.stages import segment
    h = segment.heuristic_segment(docview.load(c["path"]))
    return "heuristic", {"requirements": h.get("requirements") or [], "excluded": h.get("excluded") or []}


def base_run(c: dict) -> Path:
    runs = OUT / "runs"
    tag, seg = segmentation(c)
    base_id = f"base_{c['id']}_{hashlib.sha256(Path(c['path']).read_bytes()).hexdigest()[:8]}_{tag}"
    if not (runs / base_id / "stages").is_dir():
        args = [str(c["path"]), str(OUT / "base" / f"{c['id']}.md"), "--provider", "mock", "--runs-dir", str(runs),
                "--run-id", base_id, "--no-html", "-q"]
        if c.get("mock"):
            args += ["--mock-dir", str(c["mock"])]
        _py(*args)
        if seg is not None:
            sf = runs / base_id / "stages" / "segment.json"
            rec = json.loads(sf.read_text(encoding="utf-8"))
            rec["output"] = {**(rec.get("output") or {}), **seg}
            rec["status"] = "ok"
            rec["segmentation"] = tag
            sf.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return runs / base_id


def run_case(c: dict, lens: str, label: str, rep: str, model: str, effort: str | None, views: str = "") -> dict:
    stage = f"lens_{lens}"
    base = base_run(c)
    rid = f"{lens}_{label}_{rep}_{c['id']}"
    args = ["stage", stage, "--doc", str(c["path"]), "--from", str(base), "--provider", "claude_cli",
            "--model", model, "--runs-dir", str(OUT / "runs"), "--run-id", rid, "--no-html", "-q",
            "--cache-dir", str(OUT / "cache" / rep), "--out", str(OUT / "reports" / f"{rid}.md")]
    if effort:
        args += ["--effort", effort]
    t0 = time.monotonic()
    r = _py(*args, extra_env={"BCC_ANALYST_VIEWS": views} if views else None)
    sf = OUT / "runs" / rid / "stages" / f"{stage}.json"
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    out = st.get("output") or {}
    res = {"id": c["id"], "set": c["set"], "rc": r.returncode, "seconds": st.get("seconds"),
           "wall": round(time.monotonic() - t0, 1), "calls": st.get("calls"), "status": st.get("status"),
           "error": st.get("error"), "warnings": st.get("warnings"), "candidates": out.get("candidates") or [],
           "dropped": out.get("dropped") or [], "acceptance_checks": out.get("acceptance_checks") or [],
           "views": out.get("views"), "view_candidates": out.get("view_candidates"),
           "tail": (r.stderr or "")[-600:] if r.returncode else ""}
    w = OUT / lens / f"{label}_{rep}"
    w.mkdir(parents=True, exist_ok=True)
    (w / f"{c['id']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _sev(cands: list[dict]) -> str:
    return "/".join(str(sum(1 for x in cands if x.get("severity") == s)) for s in ("critical", "major", "minor"))


def _load(lens: str, label: str, rep: str) -> dict[str, dict]:
    w = OUT / lens / f"{label}_{rep}"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(w.glob("*.json"))} if w.is_dir() else {}


def official_found(cands: list[dict]) -> dict:
    from evaluation.v2 import score as sc
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    res = sc.score_report(sc.as_report({"candidates": cands}, gold), gold, arbiter="off", cache_path=sc.DEFAULT_CACHE)
    found = sorted({a["gold"] for a in res["assignment"]}, key=lambda g: (g[0], int("".join(ch for ch in g if ch.isdigit()) or 0), g))
    return {"found": found, "K": [g for g in found if g.startswith("К")], "C": [g for g in found if g.startswith("С")],
            "outside": res["counts"]["outside_gold"]["total"], "critical_false": len(res["severity"]["critical_false"])}


def corpus_fp(data: dict[str, dict]) -> dict:
    """Строгий harness корпуса: кандидаты линзы как замечания."""
    from evaluation.v2 import corpus as cp
    allc = {c["case_id"]: c for c in cp.select_cases("md", None)}
    measured = [k for k in data if k in allc]
    if not measured:
        return {}
    rows = []
    for k in measured:
        fs = []
        for i, x in enumerate(data[k]["candidates"], 1):
            f = dict(x, id=f"C-{i:03d}")
            f["evidence"] = [{**e, "line_start": e.get("line_start", e.get("line")),
                              "line_end": e.get("line_end", e.get("line"))} for e in x.get("evidence") or []]
            fs.append(f)
        rep = {"findings": fs, "run": {"status": "complete" if data[k].get("status") == "ok" else "partial"}}
        rows += cp.adapt_report(rep, allc[k]["sha256"])
    have = {allc[k]["sha256"] for k in measured}
    for c in allc.values():
        if c["sha256"] not in have:
            rows.append({"record": "run", "schema": "bcc-eval-pred/1", "source_sha256": c["sha256"],
                         "mode": "rules_plus_llm", "status": "failed", "status_reasons": ["не мерили"]})
    tmp = OUT / "harness_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    pp = tmp / "pred.jsonl"
    pp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(cp.CORPUS / "labels.jsonl"), "--pred",
                    str(pp), "--manifest", str(cp.CORPUS / "manifest.json"), "--out-dir", str(tmp / "h"),
                    "--render-format", "md"], cwd=str(ROOT), capture_output=True, text=True)
    mf = tmp / "h" / "matrix.jsonl"
    matrix = [json.loads(x) for x in mf.read_text(encoding="utf-8").splitlines() if x.strip()] if mf.exists() else []
    m = [x for x in matrix if x["case_id"] in measured]
    clean = [k for k in measured if allc[k]["expected"] == "clean"]
    return {"tp": sum(x["outcome"] == "TP" for x in m), "fn": sum(x["outcome"] == "FN" for x in m),
            "fp": sum(x["outcome"] == "FP" for x in m), "dup": sum(x["outcome"] == "DUP" for x in m),
            "fp_clean": sum(len(data[k]["candidates"]) for k in clean), "clean_docs": len(clean)}


def score(lens: str, label: str, rep: str) -> str:
    data = _load(lens, label, rep)
    L = [f"# Линза `{lens}`, `{label}` / `{rep}`", ""]
    secs = [d["seconds"] for d in data.values() if d.get("seconds")]
    L.append(f"Документов {len(data)}; вызовов {sum(d.get('calls') or 0 for d in data.values())}; время "
             f"{min(secs or [0]):.0f}–{max(secs or [0]):.0f} с; не ok: "
             f"{', '.join(k for k, d in data.items() if d.get('status') != 'ok') or '—'}")
    if "official" in data:
        o = official_found(data["official"]["candidates"])
        L.append(f"* официальный: кандидатов {len(data['official']['candidates'])} ({_sev(data['official']['candidates'])}), "
                 f"К {', '.join(o['K']) or '—'}; С {len(o['C'])}: {', '.join(o['C']) or '—'}; вне эталона {o['outside']}; "
                 f"крит. ложных {o['critical_false']}; всё найденное: {', '.join(o['found'])}")
    for k, d in data.items():
        if k.endswith("_clean"):
            L.append(f"* {k}: {len(d['candidates'])} ({_sev(d['candidates'])})")
        elif k in ("grace", "qr", "capital", "insurance"):
            from evaluation.v2 import score as sc
            gold = sc.load_gold(OPEN2 / k / "gold.yaml")
            res = sc.score_report(sc.as_report({"candidates": d["candidates"]}, gold), gold, arbiter="off",
                                  cache_path=OPEN2 / k / "arbiter_cache.jsonl")
            found = sorted({a["gold"] for a in res["assignment"]})
            acc = [f"{c.get('row_line')}:{c.get('verdict')}" for c in d.get("acceptance_checks") or []]
            L.append(f"* {k}: {len(d['candidates'])} ({_sev(d['candidates'])}); в эталоне: {', '.join(found) or '—'}; "
                     f"строки приёмки: {', '.join(acc) or '—'}")
    cf_ = corpus_fp(data)
    if cf_:
        L.append(f"* корпус: чистых {cf_['clean_docs']}, замечаний на чистых {cf_['fp_clean']}; TP {cf_['tp']}, "
                 f"FN {cf_['fn']}, FP {cf_['fp']} (с чистыми), дублей {cf_['dup']}")
    L += ["", "## Кандидаты", ""]
    for k, d in data.items():
        L.append(f"### {k} ({len(d['candidates'])}, {d.get('seconds')} с, вызовов {d.get('calls')})")
        for x in d["candidates"]:
            ev = "; ".join(f"L{e.get('line_start', e.get('line'))}" for e in x.get("evidence") or [])
            L.append(f"* [{x.get('severity')}/{x.get('kind')}] {x.get('title')} ({ev})")
        for x in d.get("dropped") or []:
            L.append(f"  * снято: [{x.get('kind')}] {x.get('title')} — {str(x.get('reason', ''))[:90]}")
        L.append("")
    text = "\n".join(L) + "\n"
    w = OUT / lens / f"{label}_{rep}"
    w.mkdir(parents=True, exist_ok=True)
    (w / "summary.md").write_text(text, encoding="utf-8")
    return text


def union(specs: list[str]) -> str:
    cands = []
    for s in specs:
        lens, label, rep = s.split(":")
        d = _load(lens, label, rep).get("official")
        if d:
            cands += d["candidates"]
    o = official_found(cands)
    return f"объединение {', '.join(specs)}: К {', '.join(o['K'])}; С {len(o['C'])}: {', '.join(o['C'])}; вне {o['outside']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score", "union"])
    ap.add_argument("--lens", choices=["qa", "analyst"], default="qa")
    ap.add_argument("--label", default="base")
    ap.add_argument("--rep", default="r1")
    ap.add_argument("--labels", default="")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--effort")
    ap.add_argument("--sets", default="official,open2c")
    ap.add_argument("--cases", default="")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--views", default="", help="аналитик: 1 или 2 просмотра (переменная BCC_ANALYST_VIEWS)")
    a = ap.parse_args(argv)
    if a.cmd == "union":
        print(union([x for x in a.labels.split(",") if x]))
        return 0
    if a.cmd == "run":
        cs = cases(a.sets.split(","), [x for x in a.cases.split(",") if x] or None)
        for c in cs:  # базовые mock-прогоны — последовательно (быстро, без модели)
            base_run(c)
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            futs = {ex.submit(run_case, c, a.lens, a.label, a.rep, a.model, a.effort, a.views): c["id"] for c in cs}
            for f in cf.as_completed(futs):
                r = f.result()
                print(f"{r['id']}: {r['status']} вызовов {r['calls']} {r['seconds']} с, кандидатов "
                      f"{len(r['candidates'])} ({_sev(r['candidates'])}) {r['tail'][-200:]}", flush=True)
    print(score(a.lens, a.label, a.rep).split("## Кандидаты")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
