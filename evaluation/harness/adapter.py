"""Адаптеры: канонический Report (контракт v1) → строки предсказаний; плоские метки → эталон.

Контракт v1 (contracts/v1.json, коммит 431f76d; src/bcc_review/contracts.py):
  Report.run: source_sha256, agent_version, provider, model, время, число физических вызовов,
              status complete|partial|failed, mode rules_plus_llm|rules_only|mock.
  Report.document: {id (= SHA-256 исходных байтов), title, format, blocks, warnings}.
  Finding: scope, kind, criterion, severity, title, impact, req_ids, hints, id, status,
           evidence [{block_id, start, end, quote}], для конфликта witness
           {input, outcome_a, outcome_b, evidence_a, evidence_b}.
По контракту: run.calls = {physical, cache_hits, failed, retries}, run.tokens = {input, output,
cache_read}, run.duration_s, run.mode, document.format ∈ markdown|text|pdf|docx|html,
Finding.kind ∈ FINDING_KINDS. Синонимы (CALL_FIELDS, TOKEN_FIELDS) оставлены для отчётов
сторонних инструментов в плоском виде.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import PRED_SCHEMA, GOLD_SCHEMA, Manifest, ProtocolError, sha256_file
from .taxonomy import Taxonomy

CALL_FIELDS = ("physical_calls", "llm_calls", "calls", "requests", "physical_requests")
TOKEN_FIELDS_IN = ("input_tokens", "prompt_tokens", "tokens_in", "input")
TOKEN_FIELDS_OUT = ("output_tokens", "completion_tokens", "tokens_out", "output")
DOC_FORMAT_TO_RENDER = {"markdown": "md", "text": "txt", "pdf": "pdf", "docx": "docx", "html": "html"}


def _calls(run: dict) -> tuple[int | None, int | None]:
    """(physical, cache_hits) из run.calls контракта v1 или из плоских синонимов."""
    c = run.get("calls")
    if isinstance(c, dict):
        phys = c.get("physical")
        hits = c.get("cache_hits")
        return (phys if isinstance(phys, int) else None), (hits if isinstance(hits, int) else None)
    return _first_int(run, CALL_FIELDS), None


def _loc_str(loc: Any) -> str | None:
    if loc is None:
        return None
    if isinstance(loc, dict):
        return ",".join(f"{k}={loc[k]}" for k in sorted(loc))
    if isinstance(loc, list):
        return "/".join(str(x) for x in loc)
    return str(loc)


def _first_int(obj: dict, names: tuple[str, ...]) -> int | None:
    for n in names:
        v = obj.get(n)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _tokens(run: dict) -> tuple[int | None, int | None]:
    for key in ("tokens", "usage", "token_usage"):
        v = run.get(key)
        if isinstance(v, dict):
            return _first_int(v, TOKEN_FIELDS_IN), _first_int(v, TOKEN_FIELDS_OUT)
        if isinstance(v, int) and not isinstance(v, bool):
            return v, None
    return _first_int(run, TOKEN_FIELDS_IN), _first_int(run, TOKEN_FIELDS_OUT)


def _duration(run: dict) -> float | None:
    for key in ("duration_s", "duration_sec", "elapsed_s"):
        if isinstance(run.get(key), (int, float)):
            return float(run[key])
    a, b = run.get("started_at"), run.get("finished_at")
    if isinstance(a, str) and isinstance(b, str):
        try:
            return (datetime.fromisoformat(b.replace("Z", "+00:00"))
                    - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            return None
    return None


def _evidence_quote(ev: dict, blocks: dict[str, dict]) -> str | None:
    q = ev.get("quote")
    if isinstance(q, str) and q.strip():
        return q
    blk = blocks.get(ev.get("block_id"))
    if blk and isinstance(ev.get("start"), int) and isinstance(ev.get("end"), int):
        return blk.get("text", "")[ev["start"]:ev["end"]] or None
    return None


def finding_anchors(f: dict, blocks: dict[str, dict]) -> list[dict]:
    anchors: list[dict] = []
    seen: set[str] = set()

    def add(ev: dict | None, role: str) -> None:
        if not isinstance(ev, dict):
            return
        q = _evidence_quote(ev, blocks)
        if not q or q in seen:
            return
        seen.add(q)
        blk = blocks.get(ev.get("block_id"), {})
        anchors.append({"role": role, "quote": q,
                        "locator": _loc_str(blk.get("loc")) or ev.get("block_id")})

    for i, ev in enumerate(f.get("evidence") or []):
        add(ev, f"e{i + 1}")
    w = f.get("witness")
    if isinstance(w, dict):
        add(w.get("evidence_a"), "a")
        add(w.get("evidence_b"), "b")
    if not anchors:  # черновик семантического этапа: только hints
        for i, h in enumerate(f.get("hints") or []):
            add(h, f"h{i + 1}")
    return anchors


def report_to_rows(report: dict, taxonomy: Taxonomy, *, render_id: str | None = None,
                   case_id: str | None = None, fmt: str | None = None, duration_s: float | None = None,
                   extra_run: dict | None = None) -> list[dict]:
    if not isinstance(report, dict):
        raise ProtocolError("Report должен быть объектом JSON")
    run = report.get("run") or {}
    doc = report.get("document") or {}
    sha = run.get("source_sha256") or doc.get("id")
    mode = run.get("mode")
    fmt = fmt or DOC_FORMAT_TO_RENDER.get(doc.get("format"), doc.get("format"))
    blocks = {b.get("id"): b for b in doc.get("blocks") or [] if isinstance(b, dict)}
    ident = {"source_sha256": sha, "render_id": render_id, "case_id": case_id, "format": fmt, "mode": mode}
    ident = {k: v for k, v in ident.items() if v is not None}
    rows: list[dict] = []
    for f in report.get("findings") or []:
        if not isinstance(f, dict):
            continue
        explicit = f.get("issue_type")
        kind = f.get("kind")
        it, mapped = taxonomy.map_kind(explicit) if explicit else taxonomy.map_kind(kind)
        title, impact = f.get("title") or "", f.get("impact") or ""
        rows.append({
            "schema": PRED_SCHEMA, "record": "finding", **ident,
            # неотображённый kind оставляем без issue_type: счётчик сам даст "other" и учтёт его в unmapped_kinds
            "defect_id": f.get("id"), "issue_type": it if mapped else None, "kind": kind or explicit,
            "criterion": f.get("criterion"), "severity": f.get("severity"), "status": f.get("status"),
            "scope": f.get("scope"), "req_ids": f.get("req_ids") or [],
            "anchors": finding_anchors(f, blocks),
            "explanation": (title + (". " + impact if impact else "")).strip() or None,
            "scenario": (f.get("witness") or {}).get("input") if isinstance(f.get("witness"), dict) else None,
            "anchor_status": f.get("anchor_status"), "meaning_status": f.get("meaning_status"),
            "merged_from": f.get("merged_from") or [],
        })
    calls, cache_hits = _calls(run)
    t_in, t_out = _tokens(run)
    empty_warning = None
    if not doc.get("blocks"):
        empty_warning = bool(doc.get("warnings") or report.get("warnings"))
    run_row = {
        "schema": PRED_SCHEMA, "record": "run", **ident,
        "status": run.get("status", "complete"), "physical_calls": calls, "cache_hits": cache_hits,
        "tokens_in": t_in, "tokens_out": t_out,
        "duration_s": duration_s if duration_s is not None else _duration(run),
        "provider": run.get("provider"), "model": run.get("model") or run.get("actual_model"),
        "agent_version": run.get("agent_version"), "agent_commit": run.get("agent_commit"),
        "run_id": run.get("run_id"), "status_reasons": run.get("status_reasons") or [],
        "incomplete_stages": run.get("incomplete_stages") or [], "findings": len(rows),
        "modules": run.get("modules") or {},
        "empty_input_warning": empty_warning,
    }
    if extra_run:
        run_row.update(extra_run)
    return rows + [run_row]


def adapt_report_files(paths: list[str], taxonomy: Taxonomy, manifest: Manifest | None = None) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        sha = (report.get("run") or {}).get("source_sha256") or (report.get("document") or {}).get("id")
        render_id = fmt = case_id = None
        if manifest is not None and sha in manifest.renders_by_sha:
            r = manifest.renders_by_sha[sha]
            render_id, fmt, case_id = r.render_id, r.format, r.case_id
        rows.extend(report_to_rows(report, taxonomy, render_id=render_id, case_id=case_id, fmt=fmt,
                                   extra_run={"report_path": str(path)}))
    return rows


def flat_labels_to_gold(rows: list[dict], taxonomy: Taxonomy) -> list[dict]:
    """defect_id, type, criterion, severity, quote, line/locator, related_quote, explanation → эталон."""
    out = []
    for row in rows:
        r = {k: v for k, v in row.items() if not k.startswith("_")}
        it = r.pop("type", None) if "issue_type" not in r else r["issue_type"]
        if it is not None and not taxonomy.known(it):
            mapped, ok = taxonomy.map_kind(it)
            if not ok:
                raise ProtocolError(f"{row.get('_file')}:{row.get('_line')}: тип {it!r} не отображается "
                                    "в таксономию; добавьте его в product_kind_map")
            it = mapped
        anchors = r.pop("anchors", None)
        if anchors is None:
            anchors = []
            loc = r.pop("locator", None) or (f"line:{r['line']}" if r.get("line") is not None else None)
            r.pop("line", None)
            if r.get("quote"):
                anchors.append({"role": "primary", "quote": r.pop("quote"), "locator": loc})
            if r.get("related_quote"):
                rl = r.pop("related_locator", None) or (f"line:{r['related_line']}" if r.get("related_line") else None)
                r.pop("related_line", None)
                anchors.append({"role": "related", "quote": r.pop("related_quote"), "locator": rl})
        r.pop("quote", None)
        r.pop("related_quote", None)
        outcome = r.get("expected_outcome") or ("present" if it else "clean")
        g = {"schema": GOLD_SCHEMA, **r, "issue_type": it, "anchors": anchors, "expected_outcome": outcome}
        if "defect_id" in g and "label_id" not in g:
            g["label_id"] = g.pop("defect_id")
        if len([a for a in anchors if a.get("role") != "control"]) > 1 and "anchor_policy" not in g:
            g["anchor_policy"] = "all"
        out.append(g)
    return out


def file_info(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    p = Path(path)
    return {"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size}
