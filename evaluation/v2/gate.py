"""Ворота второй волны (`docs/plan-v2/WAVE2.md`) одной командой — по последним замерам каждого вида.

    python -m evaluation.v2.gate                       # таблица ворот в stdout; код выхода 1, если есть красное
    python -m evaluation.v2.gate --save                # + evaluation/v2/GATE.md и строка в gate_history.jsonl
    python -m evaluation.v2.gate --run runs/<id>       # сначала оценить этот прогон (официальный документ) и
                                                       # считать его последним для своей модели
    python -m evaluation.v2.gate --strict              # «нет замера» тоже красное

Откуда берутся числа:
* официальный документ — `evaluation/v2/history.jsonl` (пишет `measure`), разбор — `measurements/<метка>/score.json`;
* корпус — `evaluation/v2/corpus_results/*/summary.json` (пишет `corpus run … --save`);
* новые ТЗ №18 — `evaluation/v2/newtz_results/*/summary.json` (пишет `newtz run … --save`);
* стабильность — `evaluation/v2/stability/*.json` (пишет `aggregate stability … --json`).

У каждого красного пункта — владелец: по эталону (кто должен находить пункт), по этапу (кто упал или делился)
или по источнику ложной находки.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import score as sc
from .common import ROOT, STAGE_OWNER, source_owner

V2 = ROOT / "evaluation" / "v2"
HISTORY = V2 / "history.jsonl"
MEAS = V2 / "measurements"

# Цели второй волны (WAVE2.md, «Цели второй волны (ворота к 14:00)»)
OFFICIAL = {
    "opus": {"status": "complete", "K": 5, "K_crit": 4, "C": 18, "crit_false": 0, "findings": (25, 40), "md_lines": 900},
    "sonnet": {"status": "complete", "K": 5, "K_crit": 4, "C": 18, "crit_false": 0, "findings": (25, 40), "md_lines": 900,
               "minutes": 15, "calls": 12},
    "haiku": {"status": "complete", "minutes": 8, "calls": 12, "K": 4},
    "gemini": {"status": "complete", "minutes": 6, "K": 4},
}
CORPUS = {"recall": 0.60, "clean_max_findings": 1, "clean_critical": 0, "clean_verdict_no": 0}
NEWTZ = {"recall": 0.60, "clean_critical": 0}
STABILITY_MODELS = ("sonnet", "opus")
WAVE2_ONLY = {"sonnet"}  # справочно: не входит в ворота WAVE2, но это основной цикл разработки


def model_kind(provider: str | None, model: str | None) -> str:
    s = f"{provider or ''} {model or ''}".lower()
    for k in ("gemini", "opus", "haiku", "sonnet"):
        if k in s:
            return k
    return "other"


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _score_for(row: dict) -> dict | None:
    from .measure import slugify

    for d in ([ROOT / row["dir"]] if row.get("dir") else []) + [MEAS / slugify(row.get("label", ""))]:
        p = d / "score.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _owners_of(gold_ids: list[str], score: dict | None, gold: dict) -> str:
    """«С14 (№06; линза нашла, судья не взял → №10)» по разбору промахов score.json."""
    by_id = {it["id"]: it for it in gold["items"]}
    misses = {m["gold"]: m for m in (score or {}).get("misses") or []}
    out = []
    for gid in gold_ids:
        own = [sc.OWNER_NO.get(o, o) for o in by_id.get(gid, {}).get("owners") or []]
        m = misses.get(gid)
        note = ""
        if m:
            w = m.get("where", "")
            if "судья" in w:
                note = "; линза нашла, судья не взял → №10"
            elif "сверкой цитат" in w:
                note = "; отсеяно сверкой цитат → №03"
            elif "близкое" in w:
                note = "; есть близкое замечание"
        out.append(f"{gid} ({', '.join(own) or '?'}{note})")
    return "; ".join(out)


def _stage_owners(score: dict | None, *, slow: bool = False, failed: bool = False) -> str:
    """Этапы прогона, которые упали / делились / дольше всех → владельцы."""
    rd = (score or {}).get("run_dir")
    if not rd or not (Path(rd) / "stages").is_dir():
        rd_p = ROOT / str(rd) if rd else None
        if not rd_p or not (rd_p / "stages").is_dir():
            return "№01 (профиль слабой модели)"
        rd = str(rd_p)
    rows = []
    for f in sorted((Path(rd) / "stages").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows.append((f.stem, d.get("status"), d.get("seconds") or 0, d.get("calls") or 0, d.get("error")))
    parts = []
    if failed:
        parts += [f"{s} {st}{': ' + str(e)[:60] if e else ''} ({STAGE_OWNER.get(s, '?')})" for s, st, _, _, e in rows
                  if st not in ("ok", "complete", "done", "skipped", None)]
    truncated: set[str] = set()
    tr = Path(rd) / "trace.jsonl"
    if tr.exists():
        for line in tr.read_text(encoding="utf-8").splitlines():
            if "exceeded" in line or "truncated" in line or "output token maximum" in line:
                try:
                    truncated.add(json.loads(line).get("stage") or "")
                except json.JSONDecodeError:
                    pass
    if slow:
        multi = [f"{s} {c} вызова{' (обрезка ответа)' if s in truncated else ''} ({STAGE_OWNER.get(s, '?')})"
                 for s, _, _, c, _ in rows if c > 1]
        top = sorted(rows, key=lambda r: -r[2])[:2]
        parts += multi + [f"{s} {sec / 60:.1f} мин ({STAGE_OWNER.get(s, '?')})" for s, _, sec, _, _ in top if sec]
    return "; ".join(dict.fromkeys(parts)) or "№01 (профиль слабой модели)"


def _check(name: str, target: str, fact: str, ok: bool | None, owners: str = "") -> dict:
    return {"name": name, "target": target, "fact": fact, "ok": ok, "owners": "" if ok else owners}


def official_gates(kind: str, row: dict | None, gold: dict) -> list[dict]:
    t = OFFICIAL[kind]
    title = {"opus": "Официальный, Opus", "sonnet": "Официальный, sonnet (справочно)",
             "haiku": "Официальный, haiku", "gemini": "Официальный, Gemini"}[kind]
    if not row:
        return [_check(f"{title}: замер", "есть", "нет замера", None, "№15" if kind != "gemini" else "№02, №17")]
    score = _score_for(row)
    src = f"{row.get('label')} ({row.get('at', '')[11:16]})"
    out = []
    if "status" in t:
        out.append(_check(f"{title}: статус", t["status"], row.get("status") or "—", row.get("status") == t["status"],
                          _stage_owners(score, failed=True)))
    k_missed = [g for g in ("К1", "К2", "К3", "К4", "К5")
                if score and g not in score["recall"]["critical"]["found"]]
    if "K" in t:
        out.append(_check(f"{title}: К1–К5", f"≥ {t['K']}/5", f"{row['K']}/5", row["K"] >= t["K"],
                          _owners_of(k_missed, score, gold)))
    if "K_crit" in t:
        not_crit = [g for g in (score or {}).get("recall", {}).get("critical", {}).get("found", [])
                    if g not in score["recall"]["critical"]["as_critical"]]
        out.append(_check(f"{title}: К критичными", f"≥ {t['K_crit']}", str(row["K_as_critical"]),
                          row["K_as_critical"] >= t["K_crit"],
                          "№10 (серьёзность): " + ", ".join(not_crit) if not_crit else "№10"))
    if "C" in t:
        c_missed = [m["gold"] for m in (score or {}).get("misses") or [] if m.get("level") == "major"]
        out.append(_check(f"{title}: С1–С20", f"≥ {t['C']}/20", f"{row['C']}/20", row["C"] >= t["C"],
                          _owners_of(c_missed, score, gold)))
    if "crit_false" in t:
        cf = [x.get("finding") or x.get("id") for x in (score or {}).get("severity", {}).get("critical_false") or []]
        out.append(_check(f"{title}: критичных ложных", "0", str(row["critical_false"]), row["critical_false"] == 0,
                          "№10: " + ", ".join(map(str, cf))))
    if "findings" in t:
        lo, hi = t["findings"]
        n = row["findings"]
        out.append(_check(f"{title}: замечаний", f"{lo}–{hi}", str(n), lo <= n <= hi,
                          "№10 (слияние дублей)" if n > hi else "№10, линзы №05–№09"))
    if "md_lines" in t:
        ml = row.get("report_md_lines")
        out.append(_check(f"{title}: строк отчёта", f"≤ {t['md_lines']}", "—" if ml is None else str(ml),
                          None if ml is None else ml <= t["md_lines"], "№13"))
    if "minutes" in t:
        d = row.get("duration_s")
        out.append(_check(f"{title}: время", f"≤ {t['minutes']} мин", "—" if d is None else f"{d / 60:.1f} мин",
                          None if d is None else d <= t["minutes"] * 60, _stage_owners(score, slow=True)))
    if "calls" in t:
        c = row.get("calls")
        out.append(_check(f"{title}: вызовов", f"≤ {t['calls']}", "—" if c is None else str(c),
                          None if c is None else c <= t["calls"], _stage_owners(score, slow=True)))
    for x in out:
        x["source"] = src
        x["info"] = kind in WAVE2_ONLY
    return out


def report_quality(row: dict | None) -> list[dict]:
    """Общие ворота плана (раздел 4) на последнем полном прогоне: цитаты, язык, общие фразы, разделы."""
    if not row:
        return []
    score = _score_for(row) or {}
    g = {x["metric"]: x for x in score.get("gates") or []}
    src = f"{row.get('label')} ({row.get('at', '')[11:16]})"
    out = []
    for metric, owners in (("цитаты найдены в документе", "№03 (сверка цитат), линзы"),
                           ("разделы п. 6 ТЗ", "№13"), ("английские слова", "№13, источник текста"),
                           ("общие фразы", "линзы №05–№09, №10")):
        if metric in g:
            x = g[metric]
            extra = ""
            if metric == "английские слова":
                words = (score.get("language") or {}).get("english", []) + (score.get("language") or {}).get(
                    "english_report_md", [])
                extra = ": " + ", ".join(sorted({str(w.get("word") if isinstance(w, dict) else w) for w in words}))[:120]
            out.append({**_check(f"Отчёт: {metric}", "100 %" if "цитаты" in metric else (
                "6/6" if "разделы" in metric else "0"), x["value"], x["ok"], owners + extra), "source": src})
    return out


def _latest_summary(folder: Path, kind: str) -> dict | None:
    best = None
    for p in folder.glob("*/summary.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        k = model_kind(d.get("provider"), d.get("model") or d.get("label"))
        if k != kind:
            continue
        if not best or d.get("at", "") > best.get("at", ""):
            best = {**d, "_path": str(p.relative_to(ROOT))}
    return best


def _clean_owners(d: dict, severity: str | None = None) -> str:
    fp = [x for x in (d.get("details") or {}).get("fp") or []
          if x.get("clean") and (severity is None or x.get("severity") == severity)]
    cnt: dict[str, int] = {}
    for x in fp:
        for o in x.get("owners") or ["?"]:
            cnt[o] = cnt.get(o, 0) + 1
    return ", ".join(f"{o} ({n})" for o, n in sorted(cnt.items(), key=lambda kv: -kv[1])) or "линзы №05–№09, №10"


def _recall_owners(d: dict) -> str:
    from .corpus import TYPE_OWNERS

    pt = d.get("per_issue_type") or {}
    weak = [(k, v) for k, v in pt.items() if (v.get("tp") or 0) + (v.get("fn") or 0) and (v.get("recall") or 0) < 0.6]
    cand = (d.get("candidates") or {}).get("per_issue_type") or {}
    parts = []
    for k, v in sorted(weak, key=lambda kv: kv[1].get("recall") or 0):
        tot = (v.get("tp") or 0) + (v.get("fn") or 0)
        c = cand.get(k)
        cn = f", кандидаты {c.get('tp')}/{tot}" if c else ""
        parts.append(f"{k} {v.get('tp') or 0}/{tot}{cn} → {TYPE_OWNERS.get(k, '?')}"
                     + (" и №10 (судья)" if c and (c.get("tp") or 0) > (v.get("tp") or 0) else ""))
    return "; ".join(parts)


def corpus_gates(title: str, d: dict | None, t: dict, missing_owner: str) -> list[dict]:
    if not d:
        return [_check(f"{title}: замер", "есть", "нет замера", None, missing_owner)]
    h, c = d["harness"], d["clean"]
    src = f"{d.get('label')} ({str(d.get('at', ''))[11:16]})"
    rec = h.get("recall")
    out = [_check(f"{title}: recall (строгий)", f"≥ {100 * t['recall']:.0f} %",
                  "—" if rec is None else f"{100 * rec:.0f} % ({h.get('tp')}/{h.get('support')})",
                  None if rec is None else rec >= t["recall"], _recall_owners(d))]
    if "clean_max_findings" in t:
        over = c.get("docs_over_1_finding")
        out.append(_check(f"{title}: на чистом ≤ {t['clean_max_findings']} замечания",
                          "0 документов сверх", "—" if over is None else
                          f"{over} из {c['measured']} (максимум {c.get('max_findings')})",
                          None if over is None else over == 0, _clean_owners(d)))
    out.append(_check(f"{title}: critical на чистых", "0", f"{c['critical']} (документов {c['docs_with_critical']})",
                      c["critical"] == 0, _clean_owners(d, "critical") + "; №10 (серьёзность)"))
    if "clean_verdict_no" in t:
        out.append(_check(f"{title}: вердикт «нельзя» на чистых", "0", str(c["verdict_no"]), c["verdict_no"] == 0,
                          "№10 (вердикт), №13"))
    if d.get("failed"):
        out.append(_check(f"{title}: прогон", "все кейсы измерены", f"не измерено {d['failed']} из {d['cases']}",
                          False, "№01, №02"))
    for x in out:
        x["source"] = src
    return out


def stability_gates(gold: dict) -> list[dict]:
    out = []
    files = list((V2 / "stability").glob("*.json"))
    for kind in STABILITY_MODELS:
        best = None
        for p in files:
            d = json.loads(p.read_text(encoding="utf-8"))
            if model_kind(None, " ".join(d.get("models") or [])) == kind and (not best or d["at"] > best["at"]):
                best = d
        title = f"Стабильность, {'Opus' if kind == 'opus' else kind}"
        if not best:
            out.append(_check(f"{title}: К1–К5 в 3 из 3", "3 прогона", "нет замера", None, "№15"))
            continue
        n = best["n"]
        weak = [i for i, v in best["per_item"].items() if i.startswith("К") and v["found"] < n]
        own = "; ".join(f"{i} {best['per_item'][i]['found']}/{n} ("
                        f"{', '.join(sc.OWNER_NO.get(o, o) for o in best['per_item'][i]['owners'])})" for i in weak)
        out.append({**_check(f"{title}: К1–К5 в {n} из {n}", "5 пунктов, n ≥ 3",
                             f"{len(best['K_all_runs'])} пунктов (n = {n})", n >= 3 and not weak, own or "№15: мало прогонов"),
                    "source": best["label"]})
    return out


def score_run(path: str, gold: dict) -> dict:
    """Оценить прогон (runs/<id> или report.json) без записи в историю — как «последний» для своей модели."""
    p = Path(path)
    rj = p / "report.json" if p.is_dir() else p
    run_dir = p if p.is_dir() else (rj.parent if (rj.parent / "stages").is_dir() else None)
    rep = sc.as_report(json.loads(rj.read_text(encoding="utf-8")), gold)
    md = rj.with_suffix(".md")
    res = sc.score_report(rep, gold, report_md=str(md) if md.exists() else None,
                          run_dir=str(run_dir) if run_dir else None, arbiter="off")
    res["run_dir"] = str(run_dir) if run_dir else None
    tmp = V2 / "gate_runs" / re.sub(r"[^\w.-]+", "_", rj.parent.name)
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    row = sc.history_row(res, f"прогон {rj.parent.name}")
    row["dir"] = str(tmp.relative_to(ROOT))
    return row


def collect(runs: list[str] | None = None) -> list[dict]:
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    rows = [r for r in _read_jsonl(HISTORY) if r.get("version") == "v2"]
    for r in runs or []:
        rows.append(score_run(r, gold))
    latest: dict[str, dict] = {}
    for r in rows:
        k = model_kind(r.get("provider"), r.get("model"))
        if k in OFFICIAL:
            latest[k] = r  # история упорядочена по времени; --run — последними
    checks = []
    for kind in ("opus", "haiku", "gemini"):
        checks += official_gates(kind, latest.get(kind), gold)
    checks += corpus_gates("Корпус, haiku", _latest_summary(V2 / "corpus_results", "haiku"), CORPUS, "№15")
    checks += corpus_gates("Новые ТЗ №18, sonnet", _latest_summary(V2 / "newtz_results", "sonnet"), NEWTZ, "№18, №15")
    checks += stability_gates(gold)
    checks += official_gates("sonnet", latest.get("sonnet"), gold)
    last_full = max(rows, key=lambda r: r.get("at", ""), default=None)
    checks += report_quality(last_full)
    return checks


def render(checks: list[dict]) -> str:
    mark = {True: "✅", False: "❌", None: "⏳"}
    red = [c for c in checks if c["ok"] is False and not c.get("info")]
    wait = [c for c in checks if c["ok"] is None and not c.get("info")]
    L = [f"# Ворота второй волны — {sc.astana_now()} (Астана)", "",
         f"Зелёных {sum(1 for c in checks if c['ok'])}, красных {len(red)}, без замера {len(wait)}. "
         "Цели — `docs/plan-v2/WAVE2.md`; пересчитать: `python -m evaluation.v2.gate`.", "",
         "| | Ворота | Цель | Факт | Замер | Владелец красного |", "| :---: | :--- | :--- | :--- | :--- | :--- |"]
    for c in checks:
        m = "⚠️" if c.get("info") and c["ok"] is False else mark[c["ok"]]
        L.append(f"| {m} | {c['name']} | {c['target']} | {c['fact']} | {c.get('source', '—')} | "
                 f"{str(c.get('owners') or '').replace('|', '/')} |")
    if red:
        L += ["", "## Красное — владельцам", ""]
        L += [f"* **{c['name']}** ({c['fact']}, цель {c['target']}): {c['owners']}" for c in red]
    info = [c for c in checks if c.get("info") and c["ok"] is False]
    if info:
        L += ["", "Справочно (⚠️ — вне ворот WAVE2): "
              + "; ".join(f"{c['name']} {c['fact']}: {c['owners']}" for c in info)]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.gate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", help="runs/<id> или report.json: оценить и считать последним")
    ap.add_argument("--save", action="store_true", help="записать evaluation/v2/GATE.md и gate_history.jsonl")
    ap.add_argument("--strict", action="store_true", help="«нет замера» — тоже красное")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    checks = collect(a.run)
    text = render(checks)
    print(text)
    if a.save:
        (V2 / "GATE.md").write_text(text, encoding="utf-8")
        with (V2 / "gate_history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": sc.astana_now(), "green": sum(1 for c in checks if c["ok"]),
                                 "red": [c["name"] for c in checks if c["ok"] is False and not c.get("info")],
                                 "waiting": [c["name"] for c in checks if c["ok"] is None]}, ensure_ascii=False) + "\n")
    gate_checks = [c for c in checks if not c.get("info")]
    red = any(c["ok"] is False for c in gate_checks) or (a.strict and any(c["ok"] is None for c in gate_checks))
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
