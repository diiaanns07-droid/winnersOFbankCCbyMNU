"""Сверка report.json агента с эталоном официального документа.

    python -m evaluation.v2.score report.json [--gold evaluation/v2/official/gold.yaml]
        [--report-md report.md] [--run-dir runs/<id>] [--arbiter off|sonnet|haiku|opus]
        [--out score.json] [--md score.md] [--label "замер 1"] [--history evaluation/v2/history.jsonl]

Сопоставление детерминированное: строки-опоры (по найденным в документе цитатам) + ключевые слова эталона.
Спорные пары и замечания вне эталона решает LLM-арбитр (`--arbiter sonnet`), решения кэшируются
в `evaluation/v2/official/arbiter_cache.jsonl`. Без арбитра спорное считается «не найдено» (строгий счёт),
а в нестрогом счёте — «найдено»; оба числа печатаются.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from . import arbiter as arb
from .common import (ROOT, doc_latin_vocab, generic_hits, latin_words, load_doc, load_report, locate,
                     normalize_candidates, normalize_findings, parse_lines, report_version)

DEFAULT_GOLD = ROOT / "evaluation" / "v2" / "official" / "gold.yaml"
DEFAULT_CACHE = ROOT / "evaluation" / "v2" / "official" / "arbiter_cache.jsonl"
LEVEL_ORDER = {"critical": 0, "major": 1, "minor": 2}
SEV_RU = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}
OWNER_NO = {"analyst": "№05", "qa": "№06", "architect": "№07", "risk": "№08", "consistency": "№09",
            "judge": "№10", "rules": "№12", "segment": "№04", "quotes": "№03"}


def load_gold(path: str | Path) -> dict:
    import yaml  # PyYAML: только для оценки, в зависимостях агента не нужен

    g = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    _normalize_gold(g, Path(path))
    for it in g["items"]:
        it["_groups"] = [parse_lines(gr["lines"]) for gr in it["anchors"]["groups"]]
        it["_kw"] = [re.compile(k.replace("ё", "е"), re.I) for k in it["keywords"]["groups"]]
        it.setdefault("parent", it["id"])
        it.setdefault("owners", [])
        it.setdefault("related", [])
    return g


CONFLICT_KINDS = ("conflict", "contradiction", "mismatch", "inconsisten")


def _normalize_gold(g: dict, path: Path) -> None:
    """Эталоны других ТЗ (№18, `evaluation/v2/open2/*/gold.yaml`) — в вид официального: путь документа от файла
    эталона, `severity` вместо `level`, опоры списком или только цитатами, ключевые слова необязательны."""
    doc = g.get("document") or "source.md"
    if not (ROOT / doc).exists() and (path.parent / doc).exists():
        doc = str((path.parent / doc).resolve().relative_to(ROOT)) if str(path.resolve()).startswith(str(ROOT)) \
            else str((path.parent / doc).resolve())
    g["document"] = doc
    if not g.get("sha256") and (ROOT / doc).exists():
        import hashlib

        g["sha256"] = hashlib.sha256((ROOT / doc).read_bytes()).hexdigest()
    lines = None
    items = g.get("items") or g.get("defects") or []
    g["items"] = items
    for i, it in enumerate(items, 1):
        it.setdefault("id", f"G{i:02d}")
        it["level"] = it.get("level") or it.get("severity") or "major"
        it.setdefault("severity_ok", [it["level"]])
        it.setdefault("title", it.get("essence") or it.get("summary") or it["id"])
        kinds = it.get("kinds") or ([it["kind"]] if it.get("kind") else []) + ([it["type"]] if it.get("type") else [])
        it["kinds"] = kinds
        anc = it.get("anchors") or {}
        if isinstance(anc, list):
            anc = {"groups": anc}
        groups = []
        for gr in anc.get("groups") or []:
            gr = dict(gr) if isinstance(gr, dict) else {"lines": gr}
            if gr.get("lines") in (None, "") and gr.get("quote"):
                if lines is None:
                    lines = load_doc(ROOT / g["document"])
                loc = locate(lines, gr["quote"])
                gr["lines"] = f"{loc['line_start']}-{loc['line_end']}" if loc else "0"
            gr["lines"] = str(gr.get("lines"))
            groups.append(gr)
        conflict = any(c in str(k).lower() for k in kinds for c in CONFLICT_KINDS)
        anc.setdefault("policy", "all" if conflict and len(groups) > 1 else "any")
        anc["groups"] = groups
        it["anchors"] = anc
        kw = it.get("keywords") or {}
        if isinstance(kw, list):
            kw = {"groups": kw}
        kw.setdefault("groups", [])
        kw.setdefault("min", 1 if kw["groups"] else 0)
        it["keywords"] = kw


# ─────────────────────────── пары замечание ↔ эталон ───────────────────────────

def finding_lines(f: dict, lines: list[dict], same_doc: bool) -> tuple[set[int], list[dict]]:
    got: set[int] = set()
    checks = []
    for e in f["evidence"]:
        hint = e.get("line_start") if isinstance(e.get("line_start"), int) else None
        loc = locate(lines, e.get("quote", ""), hint) if e.get("quote") else None
        if loc:
            got.update(range(loc["line_start"], loc["line_end"] + 1))
        elif same_doc and hint:
            le = e.get("line_end") if isinstance(e.get("line_end"), int) else hint
            got.update(range(hint, max(hint, le) + 1))
        line_ok = None
        if loc and hint and same_doc:
            line_ok = loc["line_start"] - 2 <= hint <= loc["line_end"] + 2
        checks.append({"quote": e.get("quote", "")[:160], "reported_line": hint,
                       "found": loc["how"] if loc else "missing",
                       "found_line": loc["line_start"] if loc else None, "line_ok": line_ok,
                       "verified_field": e.get("verified", "")})
    return got, checks


def pair_info(item: dict, f: dict) -> dict:
    groups_hit = [bool(f["_lines"] & g) for g in item["_groups"]]
    text = f["_text"]
    kw_hits = [bool(r.search(text)) for r in item["_kw"]]
    n_kw = sum(kw_hits)
    kw_min = int(item["keywords"].get("min", 1))
    policy = item["anchors"].get("policy", "any")
    lines_ok = all(groups_hit) if policy == "all" else any(groups_hit)
    lines_any = any(groups_hit)
    kind_ok = f.get("kind") in (item.get("kinds") or [])
    if lines_ok and n_kw >= kw_min:
        status = "match"
    elif (lines_any and n_kw >= 1) or (not lines_any and n_kw >= max(2, kw_min) and n_kw == len(kw_hits)):
        status = "disputed"
    else:
        status = "none"
    line_score = 2.0 * sum(groups_hit) / max(1, len(groups_hit)) if policy == "all" else (2.0 if lines_any else 0.0)
    title = f.get("_title", "")
    n_title = sum(1 for r in item["_kw"] if r.search(title)) if title else 0
    # заголовок говорит, о чём замечание: совпадения в нём весят больше (замечание засчитывается за свою тему)
    score = line_score + 0.5 * n_kw + 0.3 * n_title + (0.3 if kind_ok else 0)
    return {"status": status, "score": round(score, 3), "groups_hit": groups_hit, "kw_hits": n_kw,
            "kw_total": len(kw_hits), "kind_ok": kind_ok}


def max_matching(items: list[dict], findings: list[dict], edges: dict[tuple[str, str], float]) -> dict[str, str]:
    """Паросочетание максимальной мощности (Кун): эталон → замечание. Критичные пункты обрабатываются первыми,
    рёбра — по убыванию оценки; при равенстве — по id. Возвращает {gold_id: finding_id}."""
    adj: dict[str, list[str]] = {}
    for (gid, fid), sc in edges.items():
        adj.setdefault(gid, []).append(fid)
    for gid in adj:
        adj[gid].sort(key=lambda fid: (-edges[(gid, fid)], fid))
    match_f: dict[str, str] = {}

    def try_assign(gid: str, seen: set[str]) -> bool:
        for fid in adj.get(gid, []):
            if fid in seen:
                continue
            seen.add(fid)
            if fid not in match_f or try_assign(match_f[fid], seen):
                match_f[fid] = gid
                return True
        return False

    order = sorted(items, key=lambda it: (LEVEL_ORDER.get(it["level"], 3), items.index(it)))
    for it in order:
        if it["id"] in adj:
            try_assign(it["id"], set())
    return {gid: fid for fid, gid in match_f.items()}


# ─────────────────────────── основной подсчёт ───────────────────────────

def score_report(report: dict, gold: dict, *, report_md: str | None = None, run_dir: str | None = None,
                 arbiter: str = "off", cache_path: Path = DEFAULT_CACHE) -> dict:
    t0 = time.monotonic()
    doc_path = ROOT / gold["document"]
    lines = load_doc(doc_path)
    numbered = "\n".join(f"L{x['n']:03d}| {x['text']}" for x in lines)
    items = gold["items"]
    by_id = {it["id"]: it for it in items}
    rep_doc = report.get("document") or {}
    same_doc = (rep_doc.get("sha256") == gold.get("sha256")) or (
        str(rep_doc.get("format", "")).lower() in ("md", "markdown") and int(rep_doc.get("lines") or 0) == len(lines))

    findings = normalize_findings(report)
    quote_checks = []
    for f in findings:
        f["_lines"], qc = finding_lines(f, lines, same_doc)
        f["_text"] = (f["title"] + " " + f["text"]).replace("ё", "е").replace("Ё", "Е")
        f["_title"] = f["title"].replace("ё", "е").replace("Ё", "Е")
        f["_quotes"] = qc
        quote_checks.extend({"finding": f["id"], **q} for q in qc)

    pairs: dict[tuple[str, str], dict] = {}
    for it in items:
        for f in findings:
            p = pair_info(it, f)
            if p["status"] != "none":
                pairs[(it["id"], f["id"])] = p

    fmap = {f["id"]: f for f in findings}
    disputed = [(gid, fmap[fid]) for (gid, fid), p in pairs.items() if p["status"] == "disputed"]
    decisions, arb_stats = arb.resolve(doc_numbered=numbered, gold_items=items, pairs=disputed, extras=[],
                                       cache_path=cache_path, mode=arbiter)
    arb_calls = dict(arb_stats)

    def edges_for(lenient: bool, extra_gold: dict[str, str]) -> dict[tuple[str, str], float]:
        e = {}
        for (gid, fid), p in pairs.items():
            if p["status"] == "match":
                e[(gid, fid)] = p["score"]
            elif p["status"] == "disputed":
                d = decisions.get(arb.cache_key("pair", gid, fmap[fid]))
                if d is not None:
                    p["arbiter"] = {"verdict": d["verdict"], "reason": d.get("reason", ""), "model": d.get("model")}
                    if d["verdict"] == "match":
                        e[(gid, fid)] = p["score"]
                elif lenient:
                    e[(gid, fid)] = p["score"] - 1.0
        for fid, gid in extra_gold.items():
            if gid in by_id:
                e[(gid, fid)] = max(e.get((gid, fid), 0.0), 0.5)
        return e

    def focus(e: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
        """Оставить у каждого замечания только пункты эталона, близкие к лучшему по оценке (не дальше 0,3):
        замечание засчитывается за то, о чём оно, а не за всё, чего касается."""
        best: dict[str, float] = {}
        for (gid, fid), sc in e.items():
            best[fid] = max(best.get(fid, -9.0), sc)
        return {k: sc for k, sc in e.items() if sc >= best[k[1]] - 0.3}

    # 1-й проход: без «вне эталона» → какие замечания остались без пары
    edges = edges_for(False, {})
    with_edge = {fid for (_, fid) in edges}
    extras = [f for f in findings if f["id"] not in with_edge]
    ex_dec, ex_stats = arb.resolve(doc_numbered=numbered, gold_items=items, pairs=[], extras=extras,
                                   cache_path=cache_path, mode=arbiter)
    for k in ("calls", "seconds", "cost_usd"):
        arb_calls[k] = arb_calls.get(k, 0) + ex_stats.get(k, 0)
    arb_calls["pending"] = arb_calls.get("pending", 0) + ex_stats.get("pending", 0)
    extra_gold: dict[str, str] = {}
    extra_verdict: dict[str, dict] = {}
    for f in extras:
        d = ex_dec.get(arb.cache_key("extra", "", f))
        if d:
            d = dict(d)
            if d["verdict"] == "gold" and d.get("gold_id") in by_id:
                pd = decisions.get(arb.cache_key("pair", d["gold_id"], f))
                if pd and pd.get("verdict") == "no_match":
                    # арбитр по паре уже сказал «не та главная проблема» — засчитываем как частичное, без recall
                    d["verdict"] = "partial"
                    d["reason"] = f"касается {d['gold_id']}, но не его главной проблемы: {pd.get('reason', '')}"
                else:
                    extra_gold[f["id"]] = d["gold_id"]
            extra_verdict[f["id"]] = d

    edges_all = edges_for(False, extra_gold)
    edges = focus(edges_all)
    edges_len = focus(edges_for(True, extra_gold))
    assign = max_matching(items, findings, edges)
    assign_len = max_matching(items, findings, edges_len)
    f2g = {fid: gid for gid, fid in assign.items()}

    # дубли: замечание без пары в паросочетании, но с допустимым ребром к уже найденному пункту
    dups: dict[str, str] = {}
    for f in findings:
        if f["id"] in f2g:
            continue
        cand = [(sc, gid) for (gid, fid), sc in edges.items() if fid == f["id"]]
        if cand:
            cand.sort(key=lambda x: (-x[0], x[1]))
            dups[f["id"]] = cand[0][1]
    outside = [f for f in findings if f["id"] not in f2g and f["id"] not in dups]

    # ─── метрики ───
    def found(level: str | None, assignment: dict[str, str]) -> list[str]:
        return [it["id"] for it in items if (level is None or it["level"] == level) and it["id"] in assignment]

    def parents_found(assignment: dict[str, str]) -> set[str]:
        return {by_id[g]["parent"] for g in assignment}

    minor_parents = sorted({it["parent"] for it in items if it["level"] == "minor"})
    loose = {gid for (gid, _) in edges_all}
    sev_rows = []
    for gid, fid in assign.items():
        it, f = by_id[gid], fmap[fid]
        sev_rows.append({"gold": gid, "level": it["level"], "finding": fid, "severity": f["severity"],
                         "ok": f["severity"] in it.get("severity_ok", [it["level"]]),
                         "exact": f["severity"] == it["level"]})
    crit_findings = [f for f in findings if f["severity"] == "critical"]
    crit_false = []
    for f in crit_findings:
        gid = f2g.get(f["id"])
        if gid and "critical" in by_id[gid].get("severity_ok", []):
            continue
        if f["id"] in dups and "critical" in by_id[dups[f["id"]]].get("severity_ok", []):
            continue  # дубль критичного — считаем в дублях, не в ложных
        v = extra_verdict.get(f["id"], {}).get("verdict")
        if gid is None and f["id"] not in dups and v == "real":
            reason = "вне эталона (настоящий дефект), но не критичен по эталону"
        elif gid is None and f["id"] not in dups:
            reason = "вне эталона" + (f", арбитр: {v}" if v else "")
        else:
            reason = f"эталон {gid or dups.get(f['id'])} не критичный"
        crit_false.append({"finding": f["id"], "title": f["title"], "reason": reason})

    out_stats = {"total": len(outside), "real": 0, "partial": 0, "false": 0, "duplicate": 0, "gold": 0, "unknown": 0}
    out_rows = []
    for f in outside:
        d = extra_verdict.get(f["id"])
        v = d["verdict"] if d else "unknown"
        out_stats[v] = out_stats.get(v, 0) + 1
        out_rows.append({"finding": f["id"], "severity": f["severity"], "kind": f["kind"], "title": f["title"],
                         "sources": f["sources"], "verdict": v, "reason": (d or {}).get("reason", "")})

    q_total = len(quote_checks)
    q_missing = sum(1 for q in quote_checks if q["found"] == "missing")
    q_fuzzy = sum(1 for q in quote_checks if q["found"] == "fuzzy")
    q_line_bad = sum(1 for q in quote_checks if q["line_ok"] is False)
    q_field_missing = sum(1 for q in quote_checks if q["verified_field"] == "missing")
    no_evidence = [f["id"] for f in findings if not f["evidence"]]

    vocab = doc_latin_vocab(lines)
    generic, english = [], []
    for f in findings:
        for k, v in (f.get("fields") or {}).items():
            for h in generic_hits(str(v)):
                generic.append({"finding": f["id"], "field": k, "phrase": h})
            if k != "rewrite":
                for w in latin_words(str(v), vocab):
                    english.append({"finding": f["id"], "field": k, "word": w})
    for q in report.get("questions") or []:
        for k in ("question", "why"):
            for w in latin_words(str(q.get(k, "")), vocab):
                english.append({"finding": q.get("id", "Q"), "field": k, "word": w})
        for o in q.get("options") or []:
            for w in latin_words(str(o), vocab):
                english.append({"finding": q.get("id", "Q"), "field": "options", "word": w})
    vsum = (report.get("verdict") or {}).get("summary", "")
    for w in latin_words(str(vsum), vocab):
        english.append({"finding": "verdict", "field": "summary", "word": w})

    md_lines = None
    md_english: list[str] = []
    if report_md and Path(report_md).exists():
        md_text = Path(report_md).read_text(encoding="utf-8")
        md_lines = len(md_text.splitlines())
        prose = re.sub(r"```.*?```", "", md_text, flags=re.S)
        prose = re.sub(r"`[^`]*`|«[^»]*»|\"[^\"]*\"|https?://\S+", "", prose)
        md_english = sorted(set(latin_words(prose, vocab)))
        sections = report_sections(md_text)
    else:
        sections = None

    run = report.get("run") or {}
    calls = run.get("calls") or {}
    verdict = _verdict(report.get("verdict") or {})
    exp = gold.get("expected_verdict") or {}

    # промахи и их владельцы
    cands = normalize_candidates(report.get("rejected") or [], "rejected")
    for c in cands:  # кандидаты, отсеянные сверкой цитат, тоже лежат в rejected — отличаем по причине
        if re.search(r"цитат\w*.{0,30}не найден", str(c.get("reason", "")), re.I):
            c["sources"] = ["quotes:rejected"]
    cands += _stage_candidates(run_dir)
    for c in cands:
        c["_lines"], _ = finding_lines(c, lines, same_doc or bool(run_dir))
        c["_text"] = (c["title"] + " " + c["text"]).replace("ё", "е")
        c["_title"] = c["title"].replace("ё", "е")
    misses = []
    for it in items:
        if it["id"] in assign:
            continue
        near = [{"finding": fid, "status": p["status"], "score": p["score"],
                 "arbiter": (p.get("arbiter") or {}).get("verdict", "")}
                for (gid, fid), p in pairs.items() if gid == it["id"]]
        near.sort(key=lambda x: -x["score"])
        seen_in = []
        for c in cands:
            p = pair_info(it, c)
            if p["status"] == "match":
                seen_in.append({"source": c["sources"][0] if c["sources"] else "?", "id": c["id"],
                                "title": c["title"][:120], "reason": c.get("reason", "")[:160]})
        lens_seen = [x for x in seen_in if x["source"] not in ("rejected", "quotes:rejected")]
        seen_in = [x for x in seen_in if x["source"] != "quotes:rejected" or not lens_seen]
        if any(x["source"] == "rejected" for x in seen_in):
            where = "найден кандидатом, отклонён судьёй"
            owner = ["judge"]
        elif lens_seen:
            where = "найден кандидатом (" + ", ".join(sorted({x["source"] for x in lens_seen})) + "), судья не взял"
            owner = ["judge"]
        elif seen_in:
            where = "найден кандидатом, но отсеян сверкой цитат (цитата не найдена)"
            owner = list(it["owners"]) + ["quotes"]
        elif near:
            where = "есть близкое замечание, но не та проблема или не те строки"
            owner = list(it["owners"]) + ["judge"]
        else:
            where = "не найден ни одним этапом"
            owner = list(it["owners"])
        misses.append({"gold": it["id"], "level": it["level"], "title": it["title"], "where": where,
                       "owners": owner, "near": near[:3], "seen_in": seen_in[:4]})

    # вклад этапов: какие пункты эталона нашли кандидаты каждой линзы/набора/правил до судьи
    stage_recall: dict[str, dict] = {}
    for c in cands:
        src = c["sources"][0] if c["sources"] else "?"
        if src in ("rejected", "quotes:rejected"):
            continue
        key = src.split(":")[0] + ":" + src.split(":")[1] if src.startswith("lens:") else src.split(":")[0]
        st = stage_recall.setdefault(key, {"candidates": 0, "items": set()})
        st["candidates"] += 1
        for it in items:
            if it["level"] != "minor" and pair_info(it, c)["status"] == "match":
                st["items"].add(it["id"])
    stage_recall_out = {}
    for k, v in sorted(stage_recall.items()):
        ids = sorted(v["items"], key=lambda g: _gold_order(items, g))
        stage_recall_out[k] = {"candidates": v["candidates"], "K": [g for g in ids if g.startswith("К")],
                               "C": [g for g in ids if g.startswith("С")],
                               "only_here": []}
    for k, v in stage_recall_out.items():
        others = set().union(*[set(o["K"] + o["C"]) for kk, o in stage_recall_out.items() if kk != k]) \
            if len(stage_recall_out) > 1 else set()
        v["only_here"] = [g for g in v["K"] + v["C"] if g not in others]

    k_found = found("critical", assign)
    k_as_crit = [r["gold"] for r in sev_rows if r["level"] == "critical" and r["severity"] == "critical"]
    c_found = found("major", assign)
    n_findings = len(findings)
    sev_counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")}
    tg = gold.get("targets") or {}
    duration = run.get("duration_s")
    total_calls = calls.get("total", calls.get("physical"))

    gates = [
        _gate("К1–К5 найдены", f"{len(k_found)}/5", len(k_found) >= tg.get("critical_found_min", 5)),
        _gate("из них критичными", f"{len(k_as_crit)}/5", len(k_as_crit) >= tg.get("critical_as_critical_min", 4)),
        _gate("С1–С20 найдены", f"{len(c_found)}/20", len(c_found) >= tg.get("major_found_min", 16)),
        _gate("критичных ложных", str(len(crit_false)), len(crit_false) == 0),
        _gate("всего замечаний", str(n_findings),
              tg.get("findings_min", 25) <= n_findings <= tg.get("findings_max", 45)),
        _gate("цитаты найдены в документе", f"{q_total - q_missing}/{q_total}", q_missing == 0 and q_total > 0),
        _gate("строк отчёта", "—" if md_lines is None else str(md_lines),
              None if md_lines is None else md_lines <= tg.get("report_lines_max", 900)),
        _gate("разделы п. 6 ТЗ", "—" if sections is None else f"{sum(sections.values())}/{len(sections)}",
              None if sections is None else all(sections.values())),
        _gate("общие фразы", str(len(generic)), len(generic) == 0),
        _gate("английские слова", str(len(english) + len(md_english)), len(english) + len(md_english) == 0),
        _gate("вердикт разработка/тестирование",
              f"{verdict.get('development', '—')}/{verdict.get('testing', '—')}",
              verdict.get("development") == exp.get("development") and verdict.get("testing") == exp.get("testing")),
        _gate("время, мин", "—" if duration is None else f"{duration / 60:.1f}",
              None if duration is None else duration <= 15 * 60),
        _gate("вызовов модели", "—" if total_calls is None else str(total_calls),
              None if total_calls is None else total_calls <= 12),
    ]

    res = {
        "schema": "bcc-v2-score/1",
        "gold": {"path": str(Path(gold.get("_path", DEFAULT_GOLD))), "document": gold["document"],
                 "sha256": gold.get("sha256")},
        "report": {"version": report_version(report), "same_doc": same_doc,
                   "document": {k: rep_doc.get(k) for k in ("file", "format", "sha256", "lines")},
                   "status": run.get("status"), "provider": run.get("provider"),
                   "model": run.get("model_requested") or run.get("requested_model") or run.get("model"),
                   "models_used": run.get("models_used") or run.get("models_seen"),
                   "commit": run.get("commit") or run.get("agent_commit"),
                   "duration_s": duration, "calls": calls, "tokens": run.get("tokens"),
                   "cost_usd": run.get("cost_usd")},
        "counts": {"findings": n_findings, "by_severity": sev_counts, "duplicates": len(dups),
                   "outside_gold": out_stats, "report_md_lines": md_lines},
        "recall": {
            "critical": {"found": k_found, "n": len(k_found), "of": 5, "as_critical": k_as_crit,
                         "lenient": found("critical", assign_len)},
            "major": {"found": c_found, "n": len(c_found), "of": 20, "lenient": found("major", assign_len)},
            "minor": {"found_parents": sorted({by_id[g]["parent"] for g in found("minor", assign)}),
                      "of": len(minor_parents), "parts_found": found("minor", assign)},
            "key_25": {"n": len(k_found) + len(c_found), "of": 25,
                       "lenient": len(found("critical", assign_len)) + len(found("major", assign_len)),
                       "loose_any_edge": len([g for g in loose if by_id[g]["level"] != "minor"])},
            "all_items": {"n": len(assign), "of": len(items)},
            "parents": {"n": len(parents_found(assign)), "of": len({it["parent"] for it in items})},
        },
        "precision": {
            "matched": len(assign), "duplicates": len(dups) + out_stats["duplicate"],
            "outside_real": out_stats["real"],
            "outside_false": out_stats["false"], "outside_unknown": out_stats["unknown"],
            "outside_partial": out_stats["partial"],
            "precision_useful": _ratio(len(assign) + out_stats["real"] + out_stats["partial"], n_findings),
            "precision_gold": _ratio(len(assign), n_findings),
        },
        "severity": {"pairs": len(sev_rows), "ok": sum(r["ok"] for r in sev_rows),
                     "exact": sum(r["exact"] for r in sev_rows), "accuracy_ok": _ratio(sum(r["ok"] for r in sev_rows), len(sev_rows)),
                     "accuracy_exact": _ratio(sum(r["exact"] for r in sev_rows), len(sev_rows)),
                     "critical_false": crit_false, "rows": sev_rows},
        "quotes": {"total": q_total, "missing": q_missing, "fuzzy": q_fuzzy, "line_mismatch": q_line_bad,
                   "verified_field_missing": q_field_missing, "findings_without_evidence": no_evidence,
                   "missing_list": [q for q in quote_checks if q["found"] == "missing"][:30]},
        "language": {"generic": generic, "english": english, "english_report_md": md_english},
        "report_sections": sections,
        "verdict": {"got": {k: verdict.get(k) for k in ("development", "testing")}, "expected": exp},
        "assignment": [{"gold": gid, "finding": fid, "title": fmap[fid]["title"], "severity": fmap[fid]["severity"],
                        "sources": fmap[fid]["sources"], "how": _how(pairs.get((gid, fid)), fid in extra_gold)}
                       for gid, fid in sorted(assign.items(), key=lambda x: _gold_order(items, x[0]))],
        "duplicates": [{"finding": fid, "gold": gid, "title": fmap[fid]["title"], "sources": fmap[fid]["sources"]}
                       for fid, gid in sorted(dups.items())],
        "outside": out_rows,
        "misses": misses,
        "stage_recall": stage_recall_out,
        "gates": gates,
        "arbiter": {"mode": arbiter, **arb_calls},
        "seconds": round(time.monotonic() - t0, 2),
    }
    return res


SECTION_PATTERNS = {
    "паспорт прогона": r"паспорт|о прогоне|сведения о (прогоне|проверке)",
    "нарезка требований": r"нарезк|требования документа|перечень требований|список требований|таблица требований|выделенные требования",
    "проверка каждого требования": r"каждого требования|отдельн\w* требовани|по требованиям|замечани|дефект",
    "проверка набора": r"набор|согласованност|целиком|прослеживаемост",
    "сводка": r"сводк|кратко|статистик|итоги проверки",
    "итог": r"итог|вердикт|можно ли начинать|заключени|исправить (в первую очередь|первым)",
}


def report_sections(md_text: str) -> dict[str, bool]:
    """Обязательные разделы отчёта по п. 6 ТЗ: ищутся по заголовкам Markdown."""
    heads = " \n".join(ln.lstrip("#").strip().lower().replace("ё", "е")
                       for ln in md_text.splitlines() if ln.lstrip().startswith("#"))
    return {name: bool(re.search(rx, heads)) for name, rx in SECTION_PATTERNS.items()}


def _verdict(v: dict) -> dict:
    """Вердикт v2 как есть; у v1 — статус готовности → разработка/тестирование."""
    m = {"not_ready": "no", "blocked": "no", "conditional": "conditional", "ready": "yes"}
    out = dict(v)
    for k in ("development", "testing"):
        if isinstance(v.get(k), dict):
            out[k] = m.get(v[k].get("status"), v[k].get("status"))
            out.setdefault("summary", " ".join(v[k].get("reasons") or []))
    if "status" in v and "development" not in v:
        out["development"] = out["testing"] = m.get(v["status"], v["status"])
    return out


def _how(p: dict | None, via_extra: bool) -> str:
    if via_extra:
        return "арбитр (вне эталона → эталон)"
    if not p:
        return "?"
    return "детерминированно" if p["status"] == "match" else "арбитр"


def _gold_order(items: list[dict], gid: str) -> int:
    for i, it in enumerate(items):
        if it["id"] == gid:
            return i
    return 999


def _ratio(a: int, b: int) -> float | None:
    return None if not b else round(a / b, 3)


def _gate(name: str, value: str, ok: bool | None) -> dict:
    return {"metric": name, "value": value, "ok": ok}


CANDIDATE_STAGES = ("lens_", "consistency", "rules")


def _stage_candidates(run_dir: str | None) -> list[dict]:
    """Кандидаты этапов прогона: выход линз, набора и правил; отсеянные сверкой цитат — отдельно."""
    if not run_dir:
        return []
    out = []
    d = Path(run_dir) / "stages"
    if not d.is_dir():
        d = Path(run_dir)
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stage = p.stem
        output = data.get("output") if isinstance(data.get("output"), dict) else data
        if stage.startswith(CANDIDATE_STAGES):
            src = stage.replace("lens_", "lens:")
            for c in normalize_candidates(output.get("candidates") or [], src):
                c["sources"] = [c["raw"].get("source") or src]
                out.append(c)
        elif stage == "quotes":
            out += normalize_candidates(output.get("rejected") or [], "quotes:rejected")
    return out


def _find_candidate_lists(obj: Any, depth: int = 0) -> list[list]:
    if depth > 4:
        return []
    res = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "candidates" and isinstance(v, list):
                res.append(v)
            elif isinstance(v, (dict, list)):
                res += _find_candidate_lists(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:50]:
            if isinstance(v, (dict, list)):
                res += _find_candidate_lists(v, depth + 1)
    return res


# ─────────────────────────── вывод ───────────────────────────

def render_md(res: dict, label: str = "") -> str:
    r, rc = res["report"], res["recall"]
    L = [f"# Оценка по эталону официального документа{(' — ' + label) if label else ''}", ""]
    L.append(f"Отчёт: {r['version']}, статус `{r.get('status')}`, провайдер `{r.get('provider')}`, "
             f"модель `{r.get('model')}`, коммит `{r.get('commit')}`. Арбитр: `{res['arbiter']['mode']}`"
             f" (вызовов {res['arbiter'].get('calls', 0)}, неразрешённых {res['arbiter'].get('pending', 0)}).")
    L += ["", "## Ворота качества", "", "| Метрика | Значение | Цель |", "| :--- | ---: | :---: |"]
    for g in res["gates"]:
        mark = "—" if g["ok"] is None else ("да" if g["ok"] else "**нет**")
        L.append(f"| {g['metric']} | {g['value']} | {mark} |")
    p = res["precision"]
    s = res["severity"]
    c = res["counts"]
    L += ["", "## Сводка", "",
          f"* Критичные К1–К5: **{rc['critical']['n']}/5** ({', '.join(rc['critical']['found']) or '—'}); "
          f"критичными в отчёте: {len(rc['critical']['as_critical'])}; нестрого: {len(rc['critical']['lenient'])}/5.",
          f"* Существенные С1–С20: **{rc['major']['n']}/20**; нестрого (спорные засчитаны): {len(rc['major']['lenient'])}/20.",
          f"* Ключевые 25: **{rc['key_25']['n']}/25** (нестрого {rc['key_25']['lenient']}, любая связь {rc['key_25']['loose_any_edge']}).",
          f"* Незначительные М1–М8: {len(rc['minor']['found_parents'])}/{rc['minor']['of']} ({', '.join(rc['minor']['found_parents']) or '—'}).",
          f"* Замечаний {c['findings']}: критичных {c['by_severity']['critical']}, существенных {c['by_severity']['major']}, "
          f"незначительных {c['by_severity']['minor']}.",
          f"* Точность: в эталоне {p['matched']}, дублей {p['duplicates']}; вне эталона: верных {p['outside_real']}, "
          f"частично по эталону {p['outside_partial']}, ложных {p['outside_false']}, не размечено {p['outside_unknown']}; "
          f"полезных {_pct(p['precision_useful'])}.",
          f"* Серьёзность на парах с эталоном: допустимая {s['ok']}/{s['pairs']} ({_pct(s['accuracy_ok'])}), "
          f"точно как в эталоне {s['exact']}/{s['pairs']}.",
          f"* Цитаты: {res['quotes']['total'] - res['quotes']['missing']}/{res['quotes']['total']} найдены в документе, "
          f"нечётко {res['quotes']['fuzzy']}, строка не совпала {res['quotes']['line_mismatch']}.",
          f"* Общие фразы: {len(res['language']['generic'])}; английские слова: {len(res['language']['english'])}"
          f" в замечаниях, {len(res['language']['english_report_md'])} в Markdown.",
          ]
    if r.get("duration_s") is not None:
        cl = r.get("calls") or {}
        L.append(f"* Время {r['duration_s'] / 60:.1f} мин, вызовов {cl.get('total', cl.get('physical', '—'))}, "
                 f"стоимость ${r.get('cost_usd') if r.get('cost_usd') is not None else '—'}.")
    L += ["", "## Найдено", "", "| Эталон | Замечание | Серьёзность | Источник | Как |", "| :--- | :--- | :--- | :--- | :--- |"]
    for a in res["assignment"]:
        L.append(f"| {a['gold']} | {a['finding']}: {_cut(a['title'])} | {a['severity']} | {', '.join(a['sources'])} | {a['how']} |")
    L += ["", "## Промахи (кто должен был поймать)", ""]
    for m in res["misses"]:
        if m["level"] == "minor":
            continue
        owners = ", ".join(f"{o} {OWNER_NO.get(o, '')}".strip() for o in m["owners"])
        near = "; ".join(f"{n['finding']} ({n['status']}{', ' + n['arbiter'] if n['arbiter'] else ''})" for n in m["near"])
        L.append(f"* **{m['gold']}** {m['title']} — {m['where']}; владельцы: {owners}"
                 + (f"; близкие: {near}" if near else "")
                 + (f"; кандидаты: {', '.join(x['source'] + ' ' + x['id'] for x in m['seen_in'])}" if m["seen_in"] else ""))
    if res.get("stage_recall"):
        L += ["", "## Вклад этапов (кандидаты до судьи, детерминированно)", "",
              "| Этап | Кандидатов | К | С | Только у него |", "| :--- | ---: | :--- | ---: | :--- |"]
        for k, v in res["stage_recall"].items():
            L.append(f"| {k} | {v['candidates']} | {', '.join(v['K']) or '—'} | {len(v['C'])}/20 | "
                     f"{', '.join(v['only_here']) or '—'} |")
    L += ["", "## Дубли", ""]
    L += [f"* {d['finding']} → {d['gold']}: {_cut(d['title'])} ({', '.join(d['sources'])})" for d in res["duplicates"]] or ["* нет"]
    L += ["", "## Вне эталона", ""]
    L += [f"* {o['finding']} [{o['severity']}] {_cut(o['title'])} — **{o['verdict']}** ({', '.join(o['sources'])})"
          + (f": {o['reason']}" if o["reason"] else "") for o in res["outside"]] or ["* нет"]
    if res["severity"]["critical_false"]:
        L += ["", "## Критичные вне К", ""]
        L += [f"* {x['finding']}: {_cut(x['title'])} — {x['reason']}" for x in res["severity"]["critical_false"]]
    if res.get("report_sections") and not all(res["report_sections"].values()):
        L += ["", "## Нет разделов п. 6 ТЗ", "", ", ".join(k for k, v in res["report_sections"].items() if not v)]
    if res["language"]["generic"]:
        L += ["", "## Общие фразы", ""]
        L += [f"* {g['finding']}.{g['field']}: «{g['phrase']}»" for g in res["language"]["generic"][:20]]
    if res["language"]["english"] or res["language"]["english_report_md"]:
        words = sorted({e["word"] for e in res["language"]["english"]} | set(res["language"]["english_report_md"]))
        L += ["", "## Английские слова", "", ", ".join(words[:60])]
    if res["quotes"]["missing_list"]:
        L += ["", "## Цитаты, не найденные в документе", ""]
        L += [f"* {q['finding']}: «{q['quote']}» (L{q['reported_line']})" for q in res["quotes"]["missing_list"]]
    return "\n".join(L) + "\n"


def _cut(s: str, n: int = 110) -> str:
    s = " ".join(str(s).split()).replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f} %"


def astana_now() -> str:
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M")


def as_report(data: dict, gold: dict) -> dict:
    """Выход этапа (`candidates`, например ответ try_prompt.py или runs/<id>/stages/lens_qa.json) → отчёт v2,
    где каждый кандидат — замечание. Так линзы меряют свой recall по эталону до судьи."""
    if "findings" in data or "schema_version" in data:
        return data
    lists = _find_candidate_lists(data)
    cands = [c for lst in lists for c in lst if isinstance(c, dict)]
    fs = []
    for i, c in enumerate(cands, 1):
        f = dict(c)
        f.setdefault("id", f"C-{i:03d}")
        f["evidence"] = [{**e, "line_start": e.get("line_start", e.get("line")),
                          "line_end": e.get("line_end", e.get("line"))} for e in c.get("evidence") or []
                         if isinstance(e, dict)]
        fs.append(f)
    return {"schema": "bcc-review/2", "run": {"status": "candidates"}, "findings": fs,
            "document": {"sha256": gold.get("sha256"), "format": "md"}, "verdict": {}}


def render_lens(res: dict, gold: dict, lens: str) -> str:
    mine = [it for it in gold["items"] if lens in it.get("owners", [])]
    found = {a["gold"]: a for a in res["assignment"]}
    L = ["", f"## Этап «{lens}»: пункты эталона, где он владелец", ""]
    n = sum(1 for it in mine if it["id"] in found)
    L.append(f"Найдено {n}/{len(mine)}: " + ", ".join(it["id"] for it in mine if it["id"] in found) + ".")
    L.append("Не найдено: " + (", ".join(f"{it['id']} ({it['title']})" for it in mine if it["id"] not in found)
                                or "—") + ".")
    return "\n".join(L) + "\n"


def history_row(res: dict, label: str) -> dict:
    rc, p = res["recall"], res["precision"]
    return {"at": astana_now(), "label": label, "version": res["report"]["version"],
            "model": res["report"].get("model"), "provider": res["report"].get("provider"),
            "commit": res["report"].get("commit"), "status": res["report"].get("status"),
            "K": rc["critical"]["n"], "K_as_critical": len(rc["critical"]["as_critical"]), "C": rc["major"]["n"],
            "key25": rc["key_25"]["n"], "key25_lenient": rc["key_25"]["lenient"],
            "M": len(rc["minor"]["found_parents"]), "findings": res["counts"]["findings"],
            "by_severity": res["counts"]["by_severity"], "duplicates": p["duplicates"],
            "outside_real": p["outside_real"], "outside_false": p["outside_false"],
            "outside_unknown": p["outside_unknown"], "precision_useful": p["precision_useful"],
            "severity_ok": res["severity"]["accuracy_ok"], "critical_false": len(res["severity"]["critical_false"]),
            "quotes_missing": res["quotes"]["missing"], "quotes_total": res["quotes"]["total"],
            "generic": len(res["language"]["generic"]),
            "english": len(res["language"]["english"]) + len(res["language"]["english_report_md"]),
            "report_md_lines": res["counts"]["report_md_lines"], "duration_s": res["report"].get("duration_s"),
            "calls": (res["report"].get("calls") or {}).get("total"), "cost_usd": res["report"].get("cost_usd")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.score", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="report.json агента (v2; v1 тоже читается)")
    ap.add_argument("--gold", default=str(DEFAULT_GOLD))
    ap.add_argument("--report-md", help="Markdown-отчёт (длина, английские слова); по умолчанию рядом с JSON")
    ap.add_argument("--run-dir", help="каталог прогона runs/<id>: кандидаты этапов для разбора промахов")
    ap.add_argument("--arbiter", default="off", help="off (только кэш) | sonnet | haiku | opus")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--out", help="score.json")
    ap.add_argument("--md", help="score.md")
    ap.add_argument("--label", default="")
    ap.add_argument("--history", help="дописать строку в history.jsonl")
    ap.add_argument("--lens", help="analyst|qa|architect|risk|consistency|rules: сводка по пунктам, где этап — владелец")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    gold = load_gold(a.gold)
    gold["_path"] = a.gold
    report = as_report(load_report(a.report), gold)
    md = a.report_md
    if not md:
        for cand in (Path(a.report).with_suffix(".md"), Path(a.report).parent / "report.md"):
            if cand.exists():
                md = str(cand)
                break
    res = score_report(report, gold, report_md=md, run_dir=a.run_dir, arbiter=a.arbiter, cache_path=Path(a.cache))
    text = render_md(res, a.label)
    if a.lens:
        text += render_lens(res, gold, a.lens)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(text, encoding="utf-8")
    if a.history:
        with open(a.history, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(history_row(res, a.label or Path(a.report).name), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
