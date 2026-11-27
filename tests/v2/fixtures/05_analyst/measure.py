"""Замер линзы «Аналитик» (№05) до судьи на трёх наборах: официальный, корпус `evaluation/dev`, новые ТЗ №18.

    python tests/v2/fixtures/05_analyst/measure.py run --label v18_haiku --model haiku --sets official,corpus,open2 --jobs 4
    python tests/v2/fixtures/05_analyst/measure.py score --label v18_haiku

Каждый документ: mock-прогон каркаса (нарезка — фикстура или эвристика кода, бесплатно) → `stage lens_analyst`
с настоящей моделью (1 вызов, через `lens_analyst.run` с постобработкой). Ответы — в `out/05/<метка>/<кейс>.json`.
Счёт: официальный и №18 — `evaluation.v2.score` (строгий, арбитр только из кэша); корпус — `evaluation.harness`
(строгий, кандидаты линзы как замечания). Сводка — `out/05/<метка>/summary.md`.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "out" / "05"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
# Чистые версии второй редакции №18 (без настоящих дефектов, `4d108e4`), если выгружены:
#   mkdir -p out/05/open2src && git archive origin/v2/18-open-set evaluation/v2/open2 | tar -x -C out/05/open2src
OPEN2_CLEAN2 = ROOT / "out" / "05" / "open2src" / "evaluation" / "v2" / "open2"
OPEN2_CASES = ("grace", "qr", "capital", "insurance", "insurance_inject",
               "grace_clean", "qr_clean", "capital_clean", "insurance_clean")


def cases(sets: list[str], only: list[str] | None) -> list[dict]:
    out = []
    if "official" in sets:
        out.append({"set": "official", "id": "official", "path": ROOT / "release/input/requirements.md",
                    "mock": ROOT / "tests/v2/fixtures/official", "expected": "defects"})
    if "corpus" in sets:
        from evaluation.v2 import corpus as cp
        for c in cp.select_cases("md", None):
            if c["case_id"] == "edge.empty":
                continue
            out.append({"set": "corpus", "id": c["case_id"], "path": Path(c["path"]), "sha256": c["sha256"],
                        "expected": c["expected"], "mock": None})
    if "open2" in sets:
        for k in OPEN2_CASES:
            src = OPEN2_CLEAN2 / k / "source.md" if k.endswith("_clean") else OPEN2 / k / "source.md"
            if not src.exists():
                src = OPEN2 / k / "source.md"
            out.append({"set": "open2", "id": k, "path": src, "gold": OPEN2 / k / "gold.yaml",
                        "expected": "clean" if k.endswith("_clean") else "defects", "mock": None})
    if only:
        out = [c for c in out if any(c["id"] == x or c["id"].startswith(x) for x in only)]
    return out


def _py(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    # код и промпты — из этого каталога (для сравнения версий можно запустить копию скрипта в git worktree)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return subprocess.run([sys.executable, "-m", "bcc_review", *args], cwd=str(ROOT), capture_output=True,
                          text=True, timeout=timeout, env=env)


def run_case(c: dict, label: str, model: str, effort: str | None, no_cache: bool) -> dict:
    w = OUT / label
    runs = OUT / "runs"
    import hashlib
    base_id = f"base_{c['id']}_{hashlib.sha256(Path(c['path']).read_bytes()).hexdigest()[:8]}"
    if not (runs / base_id / "stages").is_dir():
        args = [str(c["path"]), str(OUT / "base" / f"{c['id']}.md"), "--provider", "mock", "--runs-dir", str(runs),
                "--run-id", base_id, "--no-html", "-q"]
        if c.get("mock"):
            args += ["--mock-dir", str(c["mock"])]
        _py(*args)
    rid = f"{label}_{c['id']}"
    args = ["stage", "lens_analyst", "--doc", str(c["path"]), "--from", str(runs / base_id), "--provider",
            "claude_cli", "--model", model, "--runs-dir", str(runs), "--run-id", rid, "--no-html", "-q",
            "--out", str(OUT / "reports" / f"{rid}.md")]
    if effort:
        args += ["--effort", effort]
    if no_cache:
        args += ["--no-cache"]
    t0 = time.monotonic()
    r = _py(*args)
    sf = runs / rid / "stages" / "lens_analyst.json"
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    res = {"id": c["id"], "set": c["set"], "rc": r.returncode, "seconds": st.get("seconds"),
           "wall": round(time.monotonic() - t0, 1), "calls": st.get("calls"), "status": st.get("status"),
           "error": st.get("error"), "warnings": st.get("warnings"),
           "candidates": (st.get("output") or {}).get("candidates") or [],
           "maturity": (st.get("output") or {}).get("document_maturity"),
           "tail": (r.stderr or "")[-400:] if r.returncode else ""}
    w.mkdir(parents=True, exist_ok=True)
    (w / f"{c['id']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


_SENT = re.compile(r"[.!?](?:\s|$)")
_CODES = re.compile(r"\b(?:R|C|D|Q|F)-\d{2,3}\b|\blens:|\bsame_subject\b|\b(?:ambiguity|incomplete|missing_element|"
                    r"unit_mismatch|boundary_conflict|event_conflict|non_singular|unverifiable|terminology)\b")
_GENERIC = re.compile(r"при необходимости|по возможности|соответствующим образом|в целом|и т\.\s?д\.|"
                      r"недостаточно детализ|рекомендуется уточнить|требует уточнения", re.I)


def rubric(cands: list[dict]) -> dict:
    """Проверяемая кодом часть рубрики понятности: заголовок ≤ 12 слов, проблема ≤ 2 предложений, в сценарии
    есть числа, есть исправление (rewrite) или вопрос с вариантами, нет внутренних кодов и общих фраз."""
    fails = {"заголовок > 12 слов": 0, "проблема > 2 предложений": 0, "сценарий без чисел": 0,
             "нет исправления": 0, "внутренние коды": 0, "общие фразы": 0, "многоточие в правке": 0}
    ok, ex = 0, []
    for c in cands:
        bad = []
        if len(str(c.get("title", "")).split()) > 12:
            bad.append("заголовок > 12 слов")
        if len(_SENT.findall(str(c.get("problem", "")).strip() + " ")) > 2:
            bad.append("проблема > 2 предложений")
        if c.get("severity") != "minor" and not re.search(r"\d", str(c.get("scenario", ""))):
            bad.append("сценарий без чисел")
        if not str(c.get("rewrite", "")).strip() and not str(c.get("question", "")).strip():
            bad.append("нет исправления")
        text = " ".join(str(c.get(k, "")) for k in ("title", "problem", "scenario", "impact", "recommendation",
                                                     "rewrite", "question"))
        if _CODES.search(text):
            bad.append("внутренние коды")
        if _GENERIC.search(text):
            bad.append("общие фразы")
        if "..." in str(c.get("rewrite", "")) or "…" in str(c.get("rewrite", "")):
            bad.append("многоточие в правке")
        for b in bad:
            fails[b] += 1
        if not bad:
            ok += 1
        else:
            ex.append(f"{', '.join(bad)}: {str(c.get('title', ''))[:90]}")
    return {"ok": ok, "fails": fails, "examples": ex}


def score(label: str, sets: list[str], only: list[str] | None) -> str:
    from evaluation.v2 import score as sc
    from evaluation.v2 import corpus as cp
    w = OUT / label
    L = [f"# Линза «Аналитик», замер `{label}`", ""]
    cs = cases(sets, only)
    data = {}
    for c in cs:
        p = w / f"{c['id']}.json"
        if p.exists():
            data[c["id"]] = json.loads(p.read_text(encoding="utf-8"))
    secs = [d["seconds"] for d in data.values() if d.get("seconds")]
    calls = [d.get("calls") or 0 for d in data.values()]
    bad = [k for k, d in data.items() if d.get("status") != "ok"]
    L.append(f"Документов {len(data)}; время вызова {min(secs or [0]):.0f}–{max(secs or [0]):.0f} с "
             f"(среднее {sum(secs) / max(len(secs), 1):.0f}); вызовов {sum(calls)}; не ok: {', '.join(bad) or '—'}.")
    L.append("")

    def sev(cands):
        return "/".join(str(sum(1 for x in cands if x.get("severity") == s)) for s in ("critical", "major", "minor"))

    # официальный и №18 — счётчик №15
    rows = []
    for c in cs:
        d = data.get(c["id"])
        if not d or c["set"] not in ("official", "open2"):
            continue
        cands = d["candidates"]
        if c["expected"] == "clean":
            rows.append((c, d, None))
            continue
        gold = sc.load_gold(c["gold"]) if c.get("gold") else sc.load_gold(sc.DEFAULT_GOLD)
        cache = (c["gold"].parent / "arbiter_cache.jsonl") if c.get("gold") else sc.DEFAULT_CACHE
        rep = sc.as_report({"candidates": cands}, gold)
        res = sc.score_report(rep, gold, arbiter="off", cache_path=cache)
        mine = [g["id"] for g in gold["items"] if "analyst" in g.get("owners", [])]
        found = {a["gold"] for a in res["assignment"]}
        rows.append((c, d, {"res": res, "mine": mine, "found": found}))
    if rows:
        L += ["## Официальный и новые ТЗ (счётчик №15, строгий)", "",
              "| Документ | Кандидатов (к/с/н) | В эталоне | Вне эталона | Дубли | К | С | Свои найдено | Свои пропущено | Крит. ложных | Время, с |",
              "| :--- | :--- | ---: | ---: | ---: | :--- | ---: | :--- | :--- | ---: | ---: |"]
        for c, d, s in rows:
            n = len(d["candidates"])
            if s is None:
                L.append(f"| {c['id']} (чистый) | {n} ({sev(d['candidates'])}) | — | — | — | — | — | — | — | "
                         f"{sum(1 for x in d['candidates'] if x.get('severity') == 'critical')} | {d.get('seconds')} |")
                continue
            res = s["res"]
            rc = res["recall"]
            ing = len(res["assignment"])
            outside = res["counts"]["outside_gold"]["total"]
            L.append(f"| {c['id']} | {n} ({sev(d['candidates'])}) | {ing} | {outside} | {res['precision']['duplicates']} | "
                     f"{', '.join(rc['critical']['found']) or '—'} | {rc['major']['n']} | "
                     f"{', '.join(x for x in s['mine'] if x in s['found']) or '—'} | "
                     f"{', '.join(x for x in s['mine'] if x not in s['found']) or '—'} | "
                     f"{len(res['severity']['critical_false'])} | {d.get('seconds')} |")
        L.append("")

    # корпус — строгий harness
    cc = [c for c in cs if c["set"] == "corpus" and c["id"] in data]
    if cc:
        rows_p = []
        for c in cc:
            d = data[c["id"]]
            fs = []
            for i, x in enumerate(d["candidates"], 1):
                f = dict(x)
                f["id"] = f"C-{i:03d}"
                f["evidence"] = [{**e, "line_start": e.get("line_start", e.get("line")),
                                  "line_end": e.get("line_end", e.get("line"))} for e in x.get("evidence") or []]
                fs.append(f)
            rep = {"findings": fs, "run": {"status": "complete" if d.get("status") == "ok" else "partial"}}
            rows_p += cp.adapt_report(rep, c["sha256"])
        # кейсы без замера — как пустые (чтобы счётчик не падал), но в сводку не идут
        man = {x["sha256"] for x in cp.select_cases("md", None)}
        have = {c["sha256"] for c in cc}
        for sha in man - have:
            rows_p.append({"record": "run", "schema": "bcc-eval-pred/1", "source_sha256": sha,
                           "mode": "rules_plus_llm", "status": "failed", "status_reasons": ["не мерили"]})
        pp = w / "corpus_predictions.jsonl"
        pp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows_p), encoding="utf-8")
        hd = w / "harness"
        r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold",
                            str(cp.CORPUS / "labels.jsonl"), "--pred", str(pp), "--manifest",
                            str(cp.CORPUS / "manifest.json"), "--out-dir", str(hd), "--render-format", "md"],
                           cwd=str(ROOT), capture_output=True, text=True)
        mt = json.loads((hd / "metrics.json").read_text(encoding="utf-8")) if (hd / "metrics.json").exists() else {}
        matrix = [json.loads(x) for x in (hd / "matrix.jsonl").read_text(encoding="utf-8").splitlines()
                  if x.strip()] if (hd / "matrix.jsonl").exists() else []
        clean = [c for c in cc if c["expected"] == "clean"]
        mut = [c for c in cc if c["expected"] != "clean"]
        cln = [x for c in clean for x in data[c["id"]]["candidates"]]
        measured = {c["id"] for c in cc}
        tp = sum(1 for m in matrix if m["outcome"] == "TP" and m["case_id"] in measured)
        fn = sum(1 for m in matrix if m["outcome"] == "FN" and m["case_id"] in measured)
        fp_mut = sum(1 for m in matrix if m["outcome"] == "FP" and m["case_id"] in {c["id"] for c in mut})
        dup = sum(1 for m in matrix if m["outcome"] == "DUP" and m["case_id"] in measured)
        L += ["## Корпус `evaluation/dev` (строгий harness, кандидаты линзы как замечания)", "",
              f"* чистых {len(clean)}: кандидатов {len(cln)} ({sev(cln)}); документов с > 1 кандидатом: "
              f"{sum(1 for c in clean if len(data[c['id']]['candidates']) > 1)}",
              f"* мутантов {len(mut)}: заложенных поймано {tp} из {tp + fn}; лишних {fp_mut}; дублей {dup}"
              + (f"; precision {tp / (tp + fp_mut):.2f}" if tp + fp_mut else ""),
              f"* rc счётчика {r.returncode}", ""]
        typ: dict = {}
        for m in matrix:
            if m["case_id"] in measured and m["outcome"] in ("TP", "FN"):
                t = typ.setdefault(m.get("gold_type") or "?", [0, 0])
                t[1] += 1
                t[0] += m["outcome"] == "TP"
        L.append("Пойманные по типам: " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(typ.items())))
        L += ["", "Кандидаты на чистых:", ""]
        for c in clean:
            for x in data[c["id"]]["candidates"]:
                L.append(f"* {c['id']}: [{x.get('severity')}/{x.get('kind')}] {x.get('title')}")
        L += ["", "Пропуски и лишние на мутантах:", ""]
        for m in matrix:
            if m["case_id"] in {c["id"] for c in mut} and m["outcome"] in ("FN", "FP"):
                L.append(f"* {m['outcome']} {m['case_id']}: {m.get('gold_type') or ''} {m.get('defect_id') or m.get('label_id')}")
        L.append("")

    # понятность (рубрика WAVE3.md, проверяемая кодом часть)
    allc = [x for d in data.values() for x in d["candidates"]]
    if allc:
        rub = rubric(allc)
        L += ["## Понятность (рубрика WAVE3, код)", "",
              f"Кандидатов {len(allc)}: проходят всё — {rub['ok']} ({100 * rub['ok'] // len(allc)} %); "
              + "; ".join(f"{k} — {v}" for k, v in rub["fails"].items() if v), ""]
        for t in rub["examples"][:12]:
            L.append(f"* {t}")
        L.append("")

    # тексты кандидатов
    L += ["## Кандидаты", ""]
    for k, d in data.items():
        L.append(f"### {k} ({len(d['candidates'])}, {d.get('seconds')} с, зрелость "
                 f"{(d.get('maturity') or {}).get('score')})")
        for x in d["candidates"]:
            ev = "; ".join(f"L{e.get('line_start', e.get('line'))}" for e in x.get("evidence") or [])
            L.append(f"* **[{x.get('severity')}/{x.get('kind')}] {x.get('title')}** ({ev})")
        L.append("")
    text = "\n".join(L) + "\n"
    (w / "summary.md").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--effort")
    ap.add_argument("--sets", default="official,corpus,open2")
    ap.add_argument("--cases", default="")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)
    sets = a.sets.split(",")
    only = [x for x in a.cases.split(",") if x] or None
    if a.cmd == "run":
        cs = cases(sets, only)
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            futs = {ex.submit(run_case, c, a.label, a.model, a.effort, a.no_cache): c for c in cs}
            for f in cf.as_completed(futs):
                try:
                    r = f.result()
                    print(f"{r['id']}: {r['status']} {len(r['candidates'])} канд., {r['seconds']} с", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"{futs[f]['id']}: ошибка {type(exc).__name__}: {exc}", flush=True)
    print(score(a.label, sets, only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
