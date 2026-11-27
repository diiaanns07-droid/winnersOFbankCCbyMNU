"""Корпус `evaluation/dev`: прогон агента v2, адаптер report.json → predictions.jsonl, строгий счётчик.

    # прогон агента по всем кейсам (MD), подсчёт и сводка
    python -m evaluation.v2.corpus run --out out/corpus_v2 --provider claude_cli --model haiku --jobs 3
    # только пересчёт по готовым отчётам
    python -m evaluation.v2.corpus score --out out/corpus_v2
    # отдельно: адаптер v2 → предсказания
    python -m evaluation.v2.corpus adapt REPORT.json SOURCE_FILE >> predictions.jsonl

Подсчёт делает `evaluation/harness` (строгий: обе стороны противоречия, паросочетание один к одному, дубли
отдельно, ложные тревоги на чистых кейсах). Поверх него — сводка №15: вердикты и серьёзность замечаний на чистых
документах (ворота плана: на чистом ТЗ ≤ 1 major, 0 critical, вердикт не «нельзя»).
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

from .common import ROOT, run_shell, sha256_file, shell_quote, source_owner

CORPUS = ROOT / "evaluation" / "dev" / "corpus"
HARNESS_KINDS = {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
                 "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
                 "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect",
                 "duplicate", "other"}
DEFAULT_CMD = "{python} -m bcc_review {input} {output} --provider {provider} --model {model}"


# ─────────────────────────── адаптер ───────────────────────────

def adapt_report(rep: dict, source_sha256: str, mode: str = "rules_plus_llm") -> list[dict]:
    """report.json v2 → строки predictions.jsonl протокола bcc-eval (finding + run)."""
    rows = []
    for i, f in enumerate(rep.get("findings") or [], 1):
        kind = str(f.get("kind") or "other")
        issue = kind if kind in HARNESS_KINDS else "other"
        anchors = []
        for e in f.get("evidence") or []:
            q = str(e.get("quote") or "").strip()
            if not q:
                continue
            a = {"quote": q}
            ls = e.get("line_start", e.get("line"))
            if isinstance(ls, int):
                a["locator"] = f"line_end={e.get('line_end', ls)},line_start={ls}"
            anchors.append(a)
        rows.append({"record": "finding", "schema": "bcc-eval-pred/1", "source_sha256": source_sha256,
                     "mode": mode, "defect_id": f.get("id") or f"D-{i:02d}", "issue_type": issue, "kind": kind,
                     "criterion": f.get("criterion"), "severity": f.get("severity"), "status": "confirmed",
                     "anchors": anchors, "explanation": str(f.get("title") or "")[:300]})
    run = rep.get("run") or {}
    calls = run.get("calls") or {}
    tokens = run.get("tokens") or {}
    status = run.get("status") if run.get("status") in ("complete", "partial", "failed") else "failed"
    rows.append({"record": "run", "schema": "bcc-eval-pred/1", "source_sha256": source_sha256, "mode": mode,
                 "status": status, "physical_calls": calls.get("total"), "cache_hits": calls.get("cached"),
                 "tokens_in": tokens.get("input"), "tokens_out": tokens.get("output"),
                 "duration_s": run.get("duration_s"), "provider": run.get("provider"),
                 "model": run.get("model_requested"), "agent_version": run.get("version")})
    return rows


def failed_run_row(source_sha256: str, reason: str, mode: str = "rules_plus_llm") -> dict:
    return {"record": "run", "schema": "bcc-eval-pred/1", "source_sha256": source_sha256, "mode": mode,
            "status": "failed", "status_reasons": [reason[:300]]}


# ─────────────────────────── прогон ───────────────────────────

def select_cases(fmt: str, cases: list[str] | None) -> list[dict]:
    man = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for c in man["cases"]:
        if cases and not any(c["case_id"] == x or c["case_id"].startswith(x) for x in cases):
            continue
        for r in c["renders"]:
            if r["format"] == fmt:
                out.append({"case_id": c["case_id"], "expected": c["expected_outcome"], "kind": c["kind"],
                            "render_id": r["render_id"], "path": CORPUS / r["path"], "sha256": r["sha256"]})
    return out


def _dir_name(render_id: str) -> str:
    return hashlib.sha256(render_id.encode("utf-8")).hexdigest()[:12]


def run_one(case: dict, out: Path, cmd_tpl: str, provider: str, model: str, timeout: int,
            reuse: bool) -> dict:
    d = out / "reports" / _dir_name(case["render_id"])
    d.mkdir(parents=True, exist_ok=True)
    report_md = d / "report.md"
    report_json = d / "report.json"
    meta = {"case_id": case["case_id"], "render_id": case["render_id"], "dir": d.name}
    if reuse and report_json.exists():
        return {**meta, "rc": 0, "seconds": None, "reused": True}
    cmd = cmd_tpl.format(python=shell_quote(sys.executable), input=shell_quote(str(case["path"])),
                         output=shell_quote(str(report_md)), provider=provider, model=model)
    t0 = time.monotonic()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    try:
        r = run_shell(cmd, timeout, env)
        rc, tail = r.returncode, (r.stderr or r.stdout)[-800:]
    except subprocess.TimeoutExpired:
        rc, tail = -9, f"таймаут {timeout} с"
    (d / "agent.log").write_text(f"$ {cmd}\nrc={rc}\n{tail}\n", encoding="utf-8")
    return {**meta, "rc": rc, "seconds": round(time.monotonic() - t0, 1), "tail": tail[-300:]}


def find_report_json(d: Path) -> Path | None:
    for name in ("report.json",):
        if (d / name).exists():
            return d / name
    js = sorted(d.glob("*.json"))
    return js[0] if js else None


def build_predictions(out: Path, cases: list[dict], mode: str) -> tuple[Path, list[dict]]:
    rows: list[dict] = []
    per_case = []
    for c in cases:
        d = out / "reports" / _dir_name(c["render_id"])
        rj = find_report_json(d) if d.exists() else None
        if not rj:
            rows.append(failed_run_row(c["sha256"], "нет report.json", mode))
            per_case.append({**_case_meta(c), "status": "failed", "findings": None})
            continue
        try:
            rep = json.loads(rj.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rows.append(failed_run_row(c["sha256"], f"report.json не читается: {exc}", mode))
            per_case.append({**_case_meta(c), "status": "failed", "findings": None})
            continue
        rows += adapt_report(rep, c["sha256"], mode)
        fs = rep.get("findings") or []
        v = rep.get("verdict") or {}
        run = rep.get("run") or {}
        per_case.append({**_case_meta(c), "status": run.get("status"), "run_id": run.get("run_id"),
                         "commit": run.get("commit"), "findings": len(fs),
                         "items": [{"id": f.get("id"), "severity": f.get("severity"), "kind": f.get("kind"),
                                    "title": str(f.get("title") or "")[:140], "sources": list(f.get("sources") or [])}
                                   for f in fs],
                         "by_severity": {s: sum(1 for f in fs if f.get("severity") == s)
                                         for s in ("critical", "major", "minor")},
                         "verdict": {"development": v.get("development"), "testing": v.get("testing")},
                         "duration_s": run.get("duration_s"), "calls": (run.get("calls") or {}).get("total"),
                         "cost_usd": run.get("cost_usd")})
    p = out / "predictions.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return p, per_case


# Кто отвечает за пропуск дефекта данного типа (заложенные дефекты корпуса), если ни один этап его не нашёл.
TYPE_OWNERS = {"boundary_conflict": "№12, №06", "event_conflict": "№12, №09", "missing_element": "№05, №12",
               "status_conflict": "№09, №07", "unit_mismatch": "№09, №12"}


def details(per_case: list[dict], matrix: list[dict]) -> dict:
    """Разбор по находкам: ложные (с источниками и владельцами), пропуски по типам, вклад источников."""
    items = {(pc["case_id"], it["id"]): it for pc in per_case for it in pc.get("items") or []}
    expected = {pc["case_id"]: pc["expected"] for pc in per_case}
    by_source: dict[str, dict[str, int]] = {}
    fp, fn, dup = [], [], 0

    def bump(srcs: list[str], key: str) -> None:
        for sname in {s.split(":", 1)[0] if s.startswith("rules") else s for s in srcs or ["?"]}:
            by_source.setdefault(sname, {"tp": 0, "fp": 0, "fp_clean": 0})[key] += 1

    for m in matrix:
        it = items.get((m["case_id"], m.get("defect_id"))) or {}
        if m["outcome"] == "TP":
            bump(it.get("sources") or [], "tp")
        elif m["outcome"] == "DUP":
            dup += 1
        elif m["outcome"] == "FP":
            clean = expected.get(m["case_id"]) == "clean"
            bump(it.get("sources") or [], "fp")
            if clean:
                bump(it.get("sources") or [], "fp_clean")
            fp.append({"case_id": m["case_id"], "clean": clean, "id": m.get("defect_id"),
                       "severity": it.get("severity"), "kind": it.get("kind"), "title": it.get("title"),
                       "sources": it.get("sources") or [], "reasons": m.get("reasons") or m.get("disputed_reasons"),
                       "owners": sorted({source_owner(x) for x in it.get("sources") or []})})
        elif m["outcome"] == "FN":
            near = [items.get((m["case_id"], d)) or {"id": d} for d in m.get("near_miss_defect_ids") or []]
            fn.append({"case_id": m["case_id"], "label_id": m["label_id"], "type": m.get("gold_type"),
                       "near": [{"id": x.get("id"), "title": x.get("title"), "sources": x.get("sources")} for x in near],
                       "owners": TYPE_OWNERS.get(m.get("gold_type"), "?")})
    return {"fp": fp, "fn": fn, "dup": dup, "by_source": dict(sorted(by_source.items()))}


def candidate_predictions(out: Path, cases: list[dict], mode: str) -> Path | None:
    """Предсказания из кандидатов этапов (линзы, набор, правила) до судьи — верхняя граница recall."""
    from .score import CANDIDATE_STAGES

    rows: list[dict] = []
    seen = 0
    runs_root = out / "runs"
    for c in cases:
        d = out / "reports" / _dir_name(c["render_id"])
        rj = find_report_json(d) if d.exists() else None
        rid = None
        if rj:
            try:
                rid = (json.loads(rj.read_text(encoding="utf-8")).get("run") or {}).get("run_id")
            except json.JSONDecodeError:
                rid = None
        sd = runs_root / str(rid) / "stages" if rid else None
        if not sd or not sd.is_dir():
            rows.append(failed_run_row(c["sha256"], "нет этапов прогона", mode))
            continue
        cands = []
        for f in sorted(sd.glob("*.json")):
            if not f.stem.startswith(CANDIDATE_STAGES):
                continue
            seen += 1
            try:
                out_ = json.loads(f.read_text(encoding="utf-8")).get("output") or {}
            except json.JSONDecodeError:
                continue
            for i, cand in enumerate(out_.get("candidates") or [], 1):
                if isinstance(cand, dict):
                    cands.append({**cand, "id": f"{f.stem}#{i}", "sources": [cand.get("source") or f.stem]})
        rows += adapt_report({"findings": cands, "run": {"status": "complete"}}, c["sha256"], mode)
    if not seen:
        return None
    p = out / "candidates" / "predictions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return p


def _case_meta(c: dict) -> dict:
    return {"case_id": c["case_id"], "expected": c["expected"], "kind": c["kind"]}


def harness_score(out: Path, preds: Path, fmt: str, sub: str = "harness") -> dict:
    hd = out / sub
    cmd = [sys.executable, "-m", "evaluation.harness", "--gold", str(CORPUS / "labels.jsonl"), "--pred", str(preds),
           "--manifest", str(CORPUS / "manifest.json"), "--out-dir", str(hd), "--render-format", fmt]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    (out / f"{sub.replace('/', '_')}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    mp = hd / "metrics.json"
    if r.returncode != 0 or not mp.exists():
        raise SystemExit(f"счётчик harness: rc={r.returncode}\n{(r.stderr or r.stdout)[-1500:]}")
    return json.loads(mp.read_text(encoding="utf-8"))


def summarize(metrics: dict, per_case: list[dict]) -> dict:
    ov = metrics.get("micro") or {}
    clean = [c for c in per_case if c["expected"] == "clean" and c["case_id"] != "edge.empty"]
    measured_clean = [c for c in clean if c.get("findings") is not None and c.get("status") not in (None, "failed")]
    s = {
        "harness": {k: ov.get(k) for k in ("tp", "fp", "fn", "duplicates", "precision", "recall", "f1",
                                             "precision_strict", "support", "predicted", "clean_false_alarms",
                                             "fp_background", "tp_parent_level", "pending_adjudication")
                    if k in ov},
        "per_issue_type": {k: {kk: v.get(kk) for kk in ("tp", "fn", "fp", "recall") if kk in v}
                           for k, v in (metrics.get("per_issue_type") or {}).items() if isinstance(v, dict)},
        "missing_measurements": len([m for m in metrics.get("missing_measurements") or []
                                     if m.get("reason") != "нет прогона"]),
        "not_run": len([m for m in metrics.get("missing_measurements") or [] if m.get("reason") == "нет прогона"]),
        "cases": len(per_case), "failed": sum(1 for c in per_case if c.get("status") in (None, "failed")),
        "clean": {
            "n": len(clean), "measured": len(measured_clean),
            "findings": sum(c["findings"] for c in measured_clean),
            "critical": sum(c["by_severity"]["critical"] for c in measured_clean),
            "major": sum(c["by_severity"]["major"] for c in measured_clean),
            "docs_with_critical": sum(1 for c in measured_clean if c["by_severity"]["critical"] > 0),
            "docs_over_1_major": sum(1 for c in measured_clean if c["by_severity"]["major"] > 1),
            "docs_over_1_finding": sum(1 for c in measured_clean if c["findings"] > 1),
            "max_findings": max((c["findings"] for c in measured_clean), default=0),
            "verdict_no": sum(1 for c in measured_clean
                              if "no" in (c["verdict"].get("development"), c["verdict"].get("testing"))),
        },
        "time": {"total_s": round(sum(c.get("duration_s") or 0 for c in per_case), 1),
                 "calls": sum(c.get("calls") or 0 for c in per_case),
                 "cost_usd": round(sum(c.get("cost_usd") or 0 for c in per_case), 3)},
    }
    return s


def render_summary(s: dict, per_case: list[dict], label: str) -> str:
    h = s["harness"]
    c = s["clean"]
    L = [f"# Корпус evaluation/dev — {label}", "",
         f"Кейсов {s['cases']} (не запускались {s['not_run']}), не измерено {s['failed']} "
         f"(пропусков в счётчике {s['missing_measurements']}).", "",
         "| TP | FP | FN | Дубли | Precision | Recall | F1 |", "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
         f"| {h.get('tp')} | {h.get('fp')} | {h.get('fn')} | {h.get('duplicates')} | {_f(h.get('precision'))} | "
         f"{_f(h.get('recall'))} | {_f(h.get('f1'))} |", "",
         f"Чистые документы ({c['measured']}/{c['n']} измерено): замечаний {c['findings']}, critical {c['critical']}, "
         f"major {c['major']}; документов с critical {c['docs_with_critical']}, с > 1 major {c['docs_over_1_major']}, "
         f"вердикт «нельзя» {c['verdict_no']}; документов с > 1 замечанием {c.get('docs_over_1_finding', '—')}, "
         f"максимум на одном {c.get('max_findings', '—')}. Ложных тревог по счётчику: {h.get('clean_false_alarms')}.", "",
         "Recall по типам: " + ", ".join(f"{k} {v.get('tp', 0)}/{(v.get('tp') or 0) + (v.get('fn') or 0)}"
                                         for k, v in sorted(s.get("per_issue_type", {}).items())
                                         if (v.get('tp') or 0) + (v.get('fn') or 0)) + ".", "",
         f"Время {s['time']['total_s'] / 60:.1f} мин суммарно, вызовов {s['time']['calls']}, ${s['time']['cost_usd']}.",
         ""]
    if s.get("candidates"):
        cd = s["candidates"]
        L += [f"Кандидаты этапов до судьи (верхняя граница): TP {cd.get('tp')}/{(cd.get('tp') or 0) + (cd.get('fn') or 0)}, "
              f"recall {_f(cd.get('recall'))}; по типам: " + ", ".join(
                  f"{k} {v.get('tp', 0)}/{(v.get('tp') or 0) + (v.get('fn') or 0)}"
                  for k, v in sorted(cd.get("per_issue_type", {}).items()) if (v.get('tp') or 0) + (v.get('fn') or 0)) + ".", ""]
    dt = s.get("details") or {}
    if dt.get("by_source"):
        L += ["Вклад источников (замечание с несколькими источниками считается каждому):", "",
              "| Источник | TP | FP | из них на чистых |", "| :--- | ---: | ---: | ---: |"]
        L += [f"| {k} ({source_owner(k)}) | {v['tp']} | {v['fp']} | {v['fp_clean']} |" for k, v in dt["by_source"].items()]
        L.append("")
    if dt.get("fp"):
        L += ["Ложные находки:", "", "| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |",
              "| :--- | :---: | :--- | :--- | :--- | :--- | :--- |"]
        for x in sorted(dt["fp"], key=lambda x: (not x["clean"], x["case_id"])):
            L.append(f"| {x['case_id']} | {'да' if x['clean'] else ''} | {x.get('severity')} | {x.get('kind')} | "
                     f"{str(x.get('title') or '').replace('|', '/')[:90]} | {', '.join(x['sources'])} | {', '.join(x['owners'])} |")
        L.append("")
    if dt.get("fn"):
        L += ["Пропуски:", "", "| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |", "| :--- | :--- | :--- | :--- |"]
        for x in dt["fn"]:
            near = "; ".join(f"{n.get('id')} {str(n.get('title') or '')[:60]} ({', '.join(n.get('sources') or [])})"
                             for n in x["near"]) or "—"
            L.append(f"| {x['case_id']} | {x['type']} | {near.replace('|', '/')} | {x['owners']} |")
        L.append("")
    L += ["| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |", "| :--- | :--- | :--- | :--- | :--- |"]
    for pc in per_case:
        bs = pc.get("by_severity") or {}
        v = pc.get("verdict") or {}
        L.append(f"| {pc['case_id']} | {pc['expected']} | {pc.get('status')} | {pc.get('findings')}"
                 f" ({bs.get('critical', '-')}/{bs.get('major', '-')}/{bs.get('minor', '-')}) | "
                 f"{v.get('development', '—')}/{v.get('testing', '—')} |")
    return "\n".join(L) + "\n"


def corpus_table() -> str:
    """Таблица всех сохранённых прогонов корпуса (evaluation/v2/corpus_results/*/summary.json)."""
    rows = []
    for p in sorted((ROOT / "evaluation" / "v2" / "corpus_results").glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append(d)
    rows.sort(key=lambda d: d.get("at", ""))
    L = ["| Прогон | Кейсов (не изм.) | TP | FP | FN | Дубли | Precision | Recall | F1 | Recall кандидатов | "
         "Тревог на 8 чистых | Чистых с > 1 замечанием | critical / major на чистых | Вердикт «нельзя» на чистых | "
         "Recall по типам | Мин на кейс | Вызовов на кейс |",
         "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- | ---: | ---: |"]
    for d in rows:
        h, c = d["harness"], d["clean"]
        types = ", ".join(f"{k} {v.get('tp', 0)}/{(v.get('tp') or 0) + (v.get('fn') or 0)}"
                          for k, v in sorted(d.get("per_issue_type", {}).items()) if (v.get('tp') or 0) + (v.get('fn') or 0))
        n = max(1, d["cases"] - d["failed"])
        cand = (d.get("candidates") or {}).get("recall")
        L.append(f"| {d['label']} | {d['cases']} ({d['failed']}) | {h.get('tp')} | {h.get('fp')} | {h.get('fn')} | "
                 f"{h.get('duplicates')} | {_f(h.get('precision'))} | {_f(h.get('recall'))} | {_f(h.get('f1'))} | "
                 f"{_f(cand)} | {h.get('clean_false_alarms')} | {c.get('docs_over_1_finding', '—')} | "
                 f"{c['critical']} / {c['major']} | {c['verdict_no']} | {types} | "
                 f"{d['time']['total_s'] / 60 / n:.1f} | {d['time']['calls'] / n:.1f} |")
    return "\n".join(L)


def update_results() -> None:
    import re as _re

    res = ROOT / "evaluation" / "v2" / "RESULTS.md"
    text = res.read_text(encoding="utf-8")
    st, en = "<!-- corpus:start -->", "<!-- corpus:end -->"
    table = corpus_table()
    if st in text and en in text:
        text = _re.sub(_re.escape(st) + r".*?" + _re.escape(en), lambda m: st + "\n" + table + "\n" + en, text, flags=_re.S)
        res.write_text(text, encoding="utf-8")


def _f(x) -> str:
    return "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.corpus", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("run", "score"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--format", default="md")
        p.add_argument("--cases", nargs="*", help="id кейсов или префиксы (по умолчанию все)")
        p.add_argument("--mode", default="rules_plus_llm")
        p.add_argument("--label", default="")
        p.add_argument("--save", action="store_true",
                       help="сохранить сводку, метрики и предсказания в evaluation/v2/corpus_results/<метка>")
        if name == "run":
            p.add_argument("--provider", default="claude_cli")
            p.add_argument("--model", default="haiku")
            p.add_argument("--cmd", dest="cmd_tpl", default=DEFAULT_CMD, help="шаблон команды агента: {python} {input} {output} "
                                                              "{provider} {model}")
            p.add_argument("--jobs", type=int, default=3)
            p.add_argument("--timeout", type=int, default=1800)
            p.add_argument("--reuse", action="store_true", help="не перезапускать кейсы с готовым report.json")
    p = sub.add_parser("adapt")
    p.add_argument("report")
    p.add_argument("source")
    p.add_argument("--mode", default="rules_plus_llm")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if a.action == "adapt":
        rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
        for r in adapt_report(rep, sha256_file(a.source), a.mode):
            print(json.dumps(r, ensure_ascii=False))
        return 0

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = select_cases(a.format, a.cases)
    if a.action == "run":
        t0 = time.monotonic()
        log = []
        with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            futs = [ex.submit(run_one, c, out, a.cmd_tpl, a.provider, a.model, a.timeout, a.reuse) for c in cases]
            for fu in cf.as_completed(futs):
                r = fu.result()
                log.append(r)
                print(f"{r['case_id']}: rc={r['rc']} {r.get('seconds')} с", flush=True)
        (out / "run_log.json").write_text(json.dumps({"cases": sorted(log, key=lambda x: x["case_id"]),
                                                      "wall_s": round(time.monotonic() - t0, 1),
                                                      "provider": a.provider, "model": a.model, "cmd": a.cmd_tpl},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    preds, per_case = build_predictions(out, cases, a.mode)
    metrics = harness_score(out, preds, a.format)
    s = summarize(metrics, per_case)
    matrix_p = out / "harness" / "matrix.jsonl"
    matrix = [json.loads(x) for x in matrix_p.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if matrix_p.exists() else []
    s["details"] = details(per_case, matrix)
    run_log = out / "run_log.json"
    if run_log.exists():
        rl = json.loads(run_log.read_text(encoding="utf-8"))
        s.update({"provider": rl.get("provider"), "model": rl.get("model"), "wall_s": rl.get("wall_s")})
    s["commit"] = sorted({pc.get("commit") for pc in per_case if pc.get("commit")})
    cand_preds = candidate_predictions(out, cases, a.mode) if (out / "runs").is_dir() else None
    if cand_preds:
        cm = harness_score(out, cand_preds, a.format, sub="candidates/harness")
        cmi = cm.get("micro") or {}
        s["candidates"] = {"tp": cmi.get("tp"), "fn": cmi.get("fn"), "recall": cmi.get("recall"),
                           "per_issue_type": {k: {kk: v.get(kk) for kk in ("tp", "fn", "recall")}
                                              for k, v in (cm.get("per_issue_type") or {}).items() if isinstance(v, dict)}}
    label = a.label or out.name
    from .measure import slugify
    from .score import astana_now

    (out / "summary.json").write_text(json.dumps({"label": label, "at": astana_now(), **s, "per_case": per_case},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    text = render_summary(s, per_case, label)
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)
    if a.save:
        import shutil

        dest = ROOT / "evaluation" / "v2" / "corpus_results" / slugify(label)
        dest.mkdir(parents=True, exist_ok=True)
        for f in ("summary.md", "summary.json", "predictions.jsonl", "harness/matrix.jsonl"):  # metrics.json — из predictions
            if (out / f).exists():
                shutil.copy(out / f, dest / Path(f).name)
        print(f"сохранено: {dest.relative_to(ROOT)}")
        update_results()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
