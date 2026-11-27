"""Стенд линзы «Архитектор» (№07): этап `lens_architect` на трёх наборах без судьи.

    python tests/v2/fixtures/07_bench/lens_bench.py run  --set official --model haiku --reps 3 --label before
    python tests/v2/fixtures/07_bench/lens_bench.py run  --set corpus   --model haiku --label before --jobs 4
    python tests/v2/fixtures/07_bench/lens_bench.py run  --set open2    --model haiku --label before --jobs 4
    python tests/v2/fixtures/07_bench/lens_bench.py score --set corpus --label before   # пересчёт без модели

Каждый документ: mock-прогон (нарезка — фикстура или код, сигналы правил №12) → `stage lens_architect` с моделью →
кандидаты линзы после сверки цитат (`stages/quotes.json`, источник `lens:architect`) → счётчик:
* official — `evaluation.v2.score --lens architect` (эталон К/С/М, свои пункты);
* corpus — строгий счётчик `evaluation/harness` через `evaluation.v2.corpus score` (только семейства зоны и чистые);
* open2 — `evaluation.v2.score --gold open2/<кейс>/gold.yaml --lens architect`, на чистых — critical/major и
  ложные «операция не описана».
Результаты — `out/07bench/<набор>/<метка>/summary.json` и `summary.md`.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PY = sys.executable
OUT = ROOT / "out" / "07bench"
RUNS = ROOT / "runs"
CORPUS = ROOT / "evaluation" / "dev" / "corpus"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
# Семейства корпуса в зоне линзы и комбинации, где они есть.
CORPUS_FAMILIES = ("two_statuses", "drop_promised", "unit_change")
NO_OP = re.compile(r"нет (метода|операци)|не описан\w* (метод|операци)|операци\w* .{0,40}не (описан|предусмотр)|"
                   r"метод\w* .{0,30}(отсутству|нет)", re.I)


def sh(cmd: list[str], log: Path) -> int:
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(" ".join(cmd) + f"\nrc={r.returncode}\n" + (r.stdout or "")[-3000:] + (r.stderr or "")[-3000:],
                   encoding="utf-8")
    return r.returncode


def lens_candidates(run_dir: Path) -> tuple[list[dict], dict]:
    """Кандидаты линзы после сверки цитат и сведения этапа (секунды, вызовы, статус)."""
    st = json.loads((run_dir / "stages" / "lens_architect.json").read_text(encoding="utf-8"))
    q = json.loads((run_dir / "stages" / "quotes.json").read_text(encoding="utf-8"))
    cands = [c for c in (q.get("output") or {}).get("candidates") or [] if c.get("source") == "lens:architect"]
    raw = (st.get("output") or {}).get("candidates") or []
    meta = {"status": st.get("status"), "seconds": st.get("seconds"), "calls": st.get("calls"),
            "raw": len(raw), "kept": len(cands), "error": st.get("error"), "warnings": st.get("warnings")}
    return cands, meta


def one_doc(doc: Path, rid: str, model: str, no_cache: bool) -> dict:
    """Mock-прогон + этап линзы с моделью. Возвращает каталог прогона этапа и сведения.

    Официальный документ — нарезка из фикстуры `tests/v2/fixtures/official`; остальные — пустой каталог
    mock-ответов: нарезку делает код (запасной путь №04), сигналы — правила №12."""
    logd = OUT / "logs"
    mock = f"{rid}-mock"
    if not (RUNS / mock / "stages" / "segment.json").exists():
        cmd = [PY, "-m", "bcc_review", str(doc), str(OUT / "tmp" / f"{mock}.md"), "--provider", "mock",
               "--run-id", mock, "--no-html", "-q"]
        if doc.resolve() not in (OFFICIAL.resolve(), (ROOT / "release" / "input" / "requirements.pdf").resolve()):
            empty = OUT / "empty_mock"
            empty.mkdir(parents=True, exist_ok=True)
            cmd += ["--mock-dir", str(empty)]
        sh(cmd, logd / f"{mock}.log")
    cmd = [PY, "-m", "bcc_review", "stage", "lens_architect", "--doc", str(doc), "--from", str(RUNS / mock),
           "--provider", "claude_cli", "--model", model, "--run-id", rid, "--no-html", "-q"]
    if no_cache:
        cmd.append("--no-cache")
    t0 = time.monotonic()
    rc = sh(cmd, logd / f"{rid}.log")
    wall = round(time.monotonic() - t0, 1)
    if rc != 0 or not (RUNS / rid / "stages" / "quotes.json").exists():
        return {"rid": rid, "rc": rc, "wall": wall, "cands": [], "meta": {"status": "failed"}}
    cands, meta = lens_candidates(RUNS / rid)
    return {"rid": rid, "rc": rc, "wall": wall, "cands": cands, "meta": meta}


def as_report(cands: list[dict], meta: dict) -> dict:
    fs = []
    for i, c in enumerate(cands, 1):
        f = dict(c)
        f["id"] = f"C-{i:03d}"
        f["sources"] = ["lens:architect"]
        fs.append(f)
    return {"schema": "bcc-review/2", "findings": fs, "verdict": {},
            "run": {"status": "complete", "duration_s": meta.get("seconds"), "calls": {"total": meta.get("calls")}}}


# ─────────────────────────── наборы ───────────────────────────

def docs_for(set_name: str) -> list[tuple[str, Path, dict]]:
    if set_name == "official":
        return [("official", OFFICIAL, {})]
    if set_name == "official_pdf":
        return [("official_pdf", ROOT / "release" / "input" / "requirements.pdf", {})]
    if set_name == "corpus":
        man = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
        out = []
        for c in man["cases"]:
            cid = c["case_id"]
            if cid == "edge.empty":
                continue
            clean = c["expected_outcome"] == "clean"
            fams = cid.split(".")[1:]
            mine = any(f in ".".join(fams) for f in CORPUS_FAMILIES)
            if not clean and not mine:
                continue
            r = next(r for r in c["renders"] if r["format"] == "md")
            out.append((cid, CORPUS / r["path"], {"clean": clean, "render_id": r["render_id"]}))
        return out
    if set_name == "open2":
        out = []
        for d in sorted(p for p in OPEN2.iterdir() if (p / "source.md").exists()):
            out.append((d.name, d / "source.md", {"clean": d.name.endswith("_clean"), "gold": d / "gold.yaml"}))
        return out
    raise SystemExit(f"неизвестный набор {set_name}")


def _own_cache(cache: Path) -> Path:
    """Копия кэша арбитра №15 в out/07bench: стенд дописывает решения в копию, а не в файл №15."""
    mine = OUT / "arbiter" / (cache.parent.name + ".jsonl")
    if not mine.exists():
        mine.parent.mkdir(parents=True, exist_ok=True)
        mine.write_text(cache.read_text(encoding="utf-8") if cache.exists() else "", encoding="utf-8")
    return mine


ARBITER = "off"


def score_official(rep_path: Path, gold: Path | None = None, cache: Path | None = None) -> dict:
    sys.path.insert(0, str(ROOT))
    from evaluation.v2 import score as sc  # noqa: WPS433

    g = sc.load_gold(str(gold) if gold else str(sc.DEFAULT_GOLD))
    g["_path"] = str(gold or sc.DEFAULT_GOLD)
    report = sc.as_report(sc.load_report(str(rep_path)), g)
    res = sc.score_report(report, g, report_md=None, run_dir=None, arbiter=ARBITER,
                          cache_path=_own_cache(Path(cache) if cache else Path(sc.DEFAULT_CACHE)))
    mine = [it for it in g["items"] if "architect" in it.get("owners", [])]
    found = {a["gold"]: a for a in res["assignment"]}
    sev = {a["gold"]: a.get("severity") for a in res["assignment"]}
    return {"mine_found": [it["id"] for it in mine if it["id"] in found],
            "mine_missing": [it["id"] for it in mine if it["id"] not in found],
            "all_found": sorted(found), "severity": sev,
            "critical_false": len(res["severity"]["critical_false"]),
            "duplicates": res["precision"]["duplicates"],
            "outside": res["precision"].get("outside_unknown"),
            "outside_real": res["precision"].get("outside_real"),
            "outside_false": res["precision"].get("outside_false"),
            "matched": len(res["assignment"]), "findings": res["counts"]["findings"],
            "quotes": f"{res['quotes']['total'] - res['quotes']['missing']}/{res['quotes']['total']}"}


def run_set(a: argparse.Namespace) -> None:
    docs = docs_for(a.set)
    base = OUT / a.set / a.label
    base.mkdir(parents=True, exist_ok=True)
    jobs = []
    for name, path, meta in docs:
        for k in range(1, a.reps + 1):
            rid = f"b7-{a.label}-{a.model}-{name}-{k}".replace("/", "_")
            jobs.append((name, path, meta, k, rid))
    results = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(one_doc, p, rid, a.model, not a.cache): (n, p, m, k, rid) for n, p, m, k, rid in jobs}
        for fu in cf.as_completed(futs):
            n, p, m, k, rid = futs[fu]
            r = fu.result()
            print(f"{n} #{k}: rc={r['rc']} {r['meta'].get('seconds')} с, кандидатов {r['meta'].get('kept')}", flush=True)
            results.append({"name": n, "rep": k, "path": str(p), **{kk: vv for kk, vv in m.items() if kk != "gold"},
                            "rid": rid, "meta": r["meta"], "wall": r["wall"]})
    (base / "runs.json").write_text(json.dumps({"model": a.model, "set": a.set, "label": a.label,
                                                "runs": sorted(results, key=lambda x: (x["name"], x["rep"]))},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    score_set(a)


def _cands_of(rid: str) -> tuple[list[dict], dict]:
    if not (RUNS / rid / "stages" / "quotes.json").exists():
        return [], {"status": "failed"}
    return lens_candidates(RUNS / rid)


def _brief(c: dict) -> dict:
    return {"severity": c.get("severity"), "kind": c.get("kind"), "title": str(c.get("title") or "")[:140],
            "lines": sorted({e.get("line_start") or e.get("line") for e in c.get("evidence") or []} - {None}),
            "no_op": bool(NO_OP.search(str(c.get("title") or "")))}


def score_set(a: argparse.Namespace) -> None:
    base = OUT / a.set / a.label
    info = json.loads((base / "runs.json").read_text(encoding="utf-8"))
    rows = info["runs"]
    summary: dict = {"set": a.set, "label": a.label, "model": info["model"], "docs": []}
    L = [f"# Стенд №07 — {a.set}, {a.label}, {info['model']}", ""]
    if a.set in ("official", "official_pdf"):
        L += ["| Прогон | Статус | с | Кандидатов | Свои пункты | Нет | К3 / К4 | Крит. ложных | Дубли | Цитаты |",
              "| :--- | :--- | ---: | ---: | :--- | :--- | :--- | ---: | ---: | :--- |"]
        for r in rows:
            cands, meta = _cands_of(r["rid"])
            rp = base / f"{r['rid']}.report.json"
            rp.write_text(json.dumps(as_report(cands, meta), ensure_ascii=False), encoding="utf-8")
            s = score_official(rp)
            sev = s["severity"]
            k34 = f"{sev.get('К3', '—')} / {sev.get('К4', '—')}"
            n_mine = len(s["mine_found"]) + len(s["mine_missing"])
            L.append(f"| {r['rid']} | {meta.get('status')} | {meta.get('seconds')} | {len(cands)} | "
                     f"{len(s['mine_found'])}/{n_mine} | {', '.join(s['mine_missing']) or '—'} | {k34} | "
                     f"{s['critical_false']} | {s['duplicates']} | {s['quotes']} |")
            summary["docs"].append({"rid": r["rid"], "meta": meta, **s, "cands": [_brief(c) for c in cands]})
    elif a.set == "corpus":
        out = base / "corpus"
        sys.path.insert(0, str(ROOT))
        from evaluation.v2 import corpus as cp  # noqa: WPS433

        for r in rows:
            if r["rep"] != 1:
                continue
            cands, meta = _cands_of(r["rid"])
            d = out / "reports" / cp._dir_name(r["render_id"])
            d.mkdir(parents=True, exist_ok=True)
            (d / "report.json").write_text(json.dumps(as_report(cands, meta), ensure_ascii=False), encoding="utf-8")
            summary["docs"].append({"name": r["name"], "clean": r["clean"], "meta": meta,
                                    "cands": [_brief(c) for c in cands]})
        names = [r["name"] for r in rows if r["rep"] == 1]
        subprocess.run([PY, "-m", "evaluation.v2.corpus", "score", "--out", str(out), "--cases", *names,
                        "--label", f"07 {a.label}"], cwd=str(ROOT), capture_output=True, text=True)
        cs = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        h = cs["harness"]
        fn = cs.get("details", {}).get("fn") or []
        clean = [d for d in summary["docs"] if d["clean"]]
        cl = {s: sum(1 for d in clean for c in d["cands"] if c["severity"] == s) for s in ("critical", "major", "minor")}
        noop = sum(1 for d in clean for c in d["cands"] if c["no_op"])
        mut_tp = h.get("tp")
        summary.update({"tp": mut_tp, "fn": len(fn), "fn_list": [(x["case_id"], x["type"]) for x in fn],
                        "clean": cl, "clean_noop": noop,
                        "clean_docs_with_major": sum(1 for d in clean if any(c["severity"] != "minor" for c in d["cands"]))})
        L += [f"Recall по заложенным (строгий): **{mut_tp}/{(mut_tp or 0) + len(fn)}**; "
              f"пропуски: {', '.join(f'{c} ({t})' for c, t in summary['fn_list']) or '—'}.", "",
              f"Чистые ({len(clean)}): critical {cl['critical']}, major {cl['major']}, minor {cl['minor']}; "
              f"документов с critical/major {summary['clean_docs_with_major']}; «операция не описана» — {noop}.", "",
              "| Документ | Чистый | с | Кандидатов (к/с/н) | Замечания |", "| :--- | :---: | ---: | :--- | :--- |"]
        for d in sorted(summary["docs"], key=lambda x: (not x["clean"], x["name"])):
            bs = {s: sum(1 for c in d["cands"] if c["severity"] == s) for s in ("critical", "major", "minor")}
            titles = "; ".join(f"[{c['severity'][:3]}] {c['title'][:70]}" for c in d["cands"]
                               if d["clean"] and c["severity"] != "minor")
            L.append(f"| {d['name']} | {'да' if d['clean'] else ''} | {d['meta'].get('seconds')} | "
                     f"{len(d['cands'])} ({bs['critical']}/{bs['major']}/{bs['minor']}) | {titles.replace('|', '/')} |")
    elif a.set == "open2":
        L += ["| Документ | с | Кандидатов (к/с/н) | Свои пункты | Нет | «операция не описана» | Critical/major на чистой |",
              "| :--- | ---: | :--- | :--- | :--- | ---: | :--- |"]
        for r in rows:
            cands, meta = _cands_of(r["rid"])
            bs = {s: sum(1 for c in cands if c.get("severity") == s) for s in ("critical", "major", "minor")}
            entry = {"name": r["name"], "clean": r["clean"], "meta": meta, "by_severity": bs,
                     "cands": [_brief(c) for c in cands]}
            mine = "—"
            miss = "—"
            if not r["clean"]:
                rp = base / f"{r['rid']}.report.json"
                rp.write_text(json.dumps(as_report(cands, meta), ensure_ascii=False), encoding="utf-8")
                gd = OPEN2 / r["name"]
                s = score_official(rp, gd / "gold.yaml", gd / "arbiter_cache.jsonl")
                entry.update(s)
                mine = f"{len(s['mine_found'])}/{len(s['mine_found']) + len(s['mine_missing'])}"
                miss = ", ".join(s["mine_missing"]) or "—"
            noop = sum(1 for c in entry["cands"] if c["no_op"])
            crit = "; ".join(f"[{c['severity'][:3]}] {c['title'][:60]}" for c in entry["cands"]
                             if r["clean"] and c["severity"] != "minor")
            L.append(f"| {r['name']} #{r['rep']} | {meta.get('seconds')} | {len(cands)} ({bs['critical']}/{bs['major']}/"
                     f"{bs['minor']}) | {mine} | {miss} | {noop} | {crit.replace('|', '/') or '—'} |")
            summary["docs"].append(entry)
        mine_f = sum(len(d.get("mine_found", [])) for d in summary["docs"] if not d["clean"])
        mine_t = sum(len(d.get("mine_found", [])) + len(d.get("mine_missing", [])) for d in summary["docs"] if not d["clean"])
        cl = {s: sum(d["by_severity"][s] for d in summary["docs"] if d["clean"]) for s in ("critical", "major", "minor")}
        defect = [d for d in summary["docs"] if not d["clean"]]
        pr = {k: sum(d.get(k) or 0 for d in defect) for k in ("findings", "matched", "duplicates", "outside_real",
                                                                "outside_false", "outside")}
        summary.update({"mine": f"{mine_f}/{mine_t}", "clean": cl, "precision": pr})
        L += ["", f"Итого свои пункты {mine_f}/{mine_t}; чистые: critical {cl['critical']}, major {cl['major']}, "
                  f"minor {cl['minor']}.", "",
              f"Дефектные версии: кандидатов {pr['findings']}, в эталоне {pr['matched']}, дублей {pr['duplicates']}, "
              f"вне эталона: настоящих {pr['outside_real']}, ложных {pr['outside_false']}, без решения {pr['outside']}."]
    secs = [d["meta"].get("seconds") or 0 for d in summary["docs"]]
    L += ["", f"Время этапа: среднее {sum(secs) / max(1, len(secs)):.0f} с, максимум {max(secs or [0]):.0f} с; "
              f"вызовов {sum((d['meta'].get('calls') or 0) for d in summary['docs'])} на {len(secs)} прогонов."]
    (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (base / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["run", "score"])
    ap.add_argument("--set", required=True, choices=["official", "official_pdf", "corpus", "open2"])
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--label", required=True)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--cache", action="store_true", help="через кэш ответов (по умолчанию --no-cache)")
    ap.add_argument("--arbiter", default="off", help="off | sonnet: спорные пары размечает арбитр №15 (копия кэша)")
    a = ap.parse_args()
    global ARBITER
    ARBITER = a.arbiter
    sys.stdout.reconfigure(encoding="utf-8")
    if a.action == "run":
        run_set(a)
    else:
        score_set(a)


if __name__ == "__main__":
    main()
