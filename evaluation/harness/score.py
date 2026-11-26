"""Подсчёт TP/FP/FN, дублей, ложных тревог на чистых документах и метрик.

Пустые знаменатели (определение):
  precision = TP / (TP + FP),       null при TP + FP = 0 (нет находок);
  recall    = TP / (TP + FN),       null при TP + FN = 0 (в эталоне нет дефектов);
  f1        = 2TP / (2TP + FP + FN), null при 2TP + FP + FN = 0;
  precision_strict = TP / (TP + FP + DUP), дубли считаются ложными находками.
Дубли (повтор уже засчитанной находки) не входят ни в TP, ни в FP основной precision,
показываются отдельно и входят в precision_strict.
Находки, признанные на разборе новыми реальными дефектами, исключаются из FP и TP
и перечислены в new_real_defects; recall по эталону они не меняют.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any

from . import __version__
from .matching import CaseResult, match_case, same_finding
from .normalize import tokens as _tokens
from .schema import Decision, GoldLabel, Manifest, Prediction, ProtocolError, RunRecord
from .taxonomy import Taxonomy

ASSUMPTIONS = [
    "Эталон полностью описывает каждый размеченный кейс: дефект вне эталона считается FP до разбора.",
    "Независимый кейс — case_id. Форматы одного case_id (MD, PDF, DOCX) не увеличивают число кейсов; "
    "основные метрики считаются по одному представлению на кейс (--render-format или primary_render манифеста).",
    "Пустые знаменатели дают null: precision при TP+FP=0, recall при TP+FN=0, f1 при 2TP+FP+FN=0.",
    "Дубли не входят в TP и FP основной precision; precision_strict считает их FP.",
    "Одна находка закрывает не больше одного дефекта эталона (паросочетание один-к-одному).",
    "Пограничные синонимы типов и частичное покрытие опор идут на разбор (pending) и до решения считаются FP.",
]


def prf(tp: int, fp: int, fn: int, dup: int = 0) -> dict[str, Any]:
    return {
        "tp": tp, "fp": fp, "fn": fn, "duplicates": dup,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "precision_strict": tp / (tp + fp + dup) if tp + fp + dup else None,
        "support": tp + fn, "predicted": tp + fp + dup,
    }


class _Resolver:
    """Привязка предсказаний и прогонов к (case_id, render_id, format)."""

    def __init__(self, gold: list[GoldLabel], manifest: Manifest | None):
        self.manifest = manifest
        self.gold_by_sha: dict[str, str] = {}
        for lab in gold:
            self.gold_by_sha.setdefault(lab.source_sha256, lab.case_id)

    def resolve(self, obj: Prediction | RunRecord) -> tuple[str | None, str | None, str | None]:
        m = self.manifest
        if m is not None:
            if obj.render_id and obj.render_id in m.renders_by_id:
                r = m.renders_by_id[obj.render_id]
                return r.case_id, r.render_id, r.format
            if obj.source_sha256 and obj.source_sha256 in m.renders_by_sha:
                r = m.renders_by_sha[obj.source_sha256]
                return r.case_id, r.render_id, r.format
        if obj.source_sha256 and obj.source_sha256 in self.gold_by_sha:
            cid = self.gold_by_sha[obj.source_sha256]
            fmt = obj.format or "labelled"
            return cid, obj.render_id or f"{cid}@{fmt}", fmt
        if obj.case_id:
            fmt = obj.format or "labelled"
            return obj.case_id, obj.render_id or f"{obj.case_id}@{fmt}", fmt
        return None, None, None


def _aggregate(results: list[CaseResult]) -> dict[str, Any]:
    tp = sum(len(r.tp) for r in results)
    fp = sum(len(r.fp) for r in results)
    fn = sum(len(r.fn) for r in results)
    dup = sum(len(r.duplicates) for r in results)
    out = prf(tp, fp, fn, dup)
    out["pending_adjudication"] = sum(1 for r in results for x in r.fp if x["pending"])
    out["new_real_defects"] = sum(len(r.new_real) for r in results)
    out["clean_false_alarms"] = sum(1 for r in results for x in r.fp if "clean_false_alarm" in x["reasons"])
    out["control_hits"] = sum(1 for r in results for x in r.fp if "control_hit" in x["reasons"])
    out["fp_background"] = sum(1 for r in results for x in r.fp if x["background"])
    out["tp_parent_level"] = sum(1 for r in results for x in r.tp if x["match_level"] == "parent")
    out["tp_adjudicated"] = sum(1 for r in results for x in r.tp if x["match_level"] == "adjudicated")
    return out


def _run_stats(runs: list[RunRecord]) -> dict[str, Any]:
    if not runs:
        return {"runs": 0, "note": "строк record=run нет: длительность, вызовы и токены не измерены"}
    durations = [r.duration_s for r in runs if r.duration_s is not None]
    calls = [r.physical_calls for r in runs if r.physical_calls is not None]
    tok = [(r.tokens_in, r.tokens_out) for r in runs if r.tokens_in is not None or r.tokens_out is not None]
    modes = sorted({r.mode or "unknown" for r in runs})
    violations = [{"render_id": r.r_render, "violations": r.violations} for r in runs if r.violations]
    for r in runs:
        if r.mode == "rules_only" and (r.physical_calls or 0) > 0:
            msg = f"rules_only: physical_calls={r.physical_calls} (ожидается 0)"
            if not any(v["render_id"] == r.r_render and msg in v["violations"] for v in violations):
                violations.append({"render_id": r.r_render, "violations": [msg]})
    return {
        "runs": len(runs),
        "modes": modes,
        "status": dict(Counter(r.status for r in runs)),
        "duration_s": {
            "measured_runs": len(durations),
            "total": round(sum(durations), 3) if durations else None,
            "mean": round(statistics.fmean(durations), 3) if durations else None,
            "median": round(statistics.median(durations), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
        },
        "physical_calls": {"measured_runs": len(calls), "total": sum(calls) if calls else None},
        "tokens": {
            "measured_runs": len(tok),
            "input": sum(t[0] or 0 for t in tok) if tok else None,
            "output": sum(t[1] or 0 for t in tok) if tok else None,
            "note": None if len(tok) == len(runs) else
            f"токены сообщены в {len(tok)} из {len(runs)} прогонов",
        },
        "providers": sorted({r.provider for r in runs if r.provider}),
        "models": sorted({r.model for r in runs if r.model}),
        "agent_versions": sorted({r.agent_version for r in runs if r.agent_version}),
        "manifest_sha256": sorted({r.manifest_sha256 for r in runs if r.manifest_sha256}),
        "cache": sorted({repr(r.cache) for r in runs}),
        "violations": violations,
    }


def score(gold: list[GoldLabel], preds: list[Prediction], runs: list[RunRecord], taxonomy: Taxonomy,
          manifest: Manifest | None = None, decisions: dict[str, Decision] | None = None,
          type_match: str = "hierarchy", render_format: str | None = None, mode: str | None = None,
          statuses: set[str] | None = None) -> dict[str, Any]:
    if type_match not in ("hierarchy", "exact"):
        raise ProtocolError("type_match: hierarchy | exact")
    decisions = decisions or {}
    warnings: list[str] = []

    # ---- режим
    modes = sorted({x.mode for x in [*preds, *runs] if x.mode})
    if mode is None and len(modes) > 1:
        raise ProtocolError(f"в предсказаниях несколько режимов {modes}: выберите один через --mode")
    if mode is not None:
        preds = [p for p in preds if p.mode in (None, mode)]
        runs = [r for r in runs if r.mode in (None, mode)]
    if statuses is not None:
        preds = [p for p in preds if (p.status or "confirmed") in statuses]

    gold_by_case: dict[str, list[GoldLabel]] = defaultdict(list)
    for lab in gold:
        gold_by_case[lab.case_id].append(lab)
    closed = sorted({l.visibility for l in gold if l.visibility != "public"})
    family_of = {cid: labs[0].family for cid, labs in gold_by_case.items()}

    # ---- манифест ↔ эталон
    if manifest is not None:
        for cid, labs in gold_by_case.items():
            case = manifest.cases.get(cid)
            if case is None:
                warnings.append(f"кейс {cid} есть в эталоне, но не в манифесте")
                continue
            shas = {r["sha256"] for r in case.get("renders", [])}
            if labs[0].source_sha256 not in shas:
                raise ProtocolError(f"кейс {cid}: source_sha256 эталона не совпадает ни с одним представлением "
                                    "в манифесте (разные версии корпуса?)")

    res = _Resolver(gold, manifest)
    unresolved, unlabeled = [], []
    for obj in [*preds, *runs]:
        obj.r_case, obj.r_render, obj.r_format = res.resolve(obj)
    for p in preds:
        if p.r_case is None:
            unresolved.append({"where": p.where, "source_sha256": p.source_sha256, "render_id": p.render_id})
        elif p.r_case not in gold_by_case:
            unlabeled.append({"where": p.where, "case_id": p.r_case})
    for r in runs:
        if r.r_case is None:
            unresolved.append({"where": r.where, "record": "run", "source_sha256": r.source_sha256})

    preds_by_render: dict[tuple[str, str], list[Prediction]] = defaultdict(list)
    for p in preds:
        if p.r_case in gold_by_case:
            preds_by_render[(p.r_case, p.r_format)].append(p)
    runs_by_render: dict[tuple[str, str], RunRecord] = {}
    for r in runs:
        if r.r_case in gold_by_case:
            if (r.r_case, r.r_format) in runs_by_render:
                warnings.append(f"повтор строки run для {r.r_render}: берётся первая")
                continue
            runs_by_render[(r.r_case, r.r_format)] = r
    have_runs = bool(runs_by_render)
    if not have_runs:
        warnings.append("нет строк record=run: кейс без предсказаний считается прогнанным с нулём находок")

    formats_seen = sorted({f for (_, f) in [*preds_by_render, *runs_by_render] if f})

    def chosen_format(cid: str) -> str | None:
        if render_format:
            return render_format
        if manifest is not None and manifest.primary_format(cid):
            return manifest.primary_format(cid)
        fmts = sorted({f for (c, f) in [*preds_by_render, *runs_by_render] if c == cid})
        return fmts[0] if len(fmts) == 1 else ("labelled" if not fmts else fmts[0])

    def measured(cid: str, fmt: str) -> tuple[bool, str | None]:
        if have_runs:
            run = runs_by_render.get((cid, fmt))
            if run is None:
                return False, "нет прогона"
            if run.status == "failed":
                return False, "прогон завершился со статусом failed"
            return True, None
        if (cid, fmt) in preds_by_render or fmt == chosen_format(cid):
            return True, None
        return False, "нет предсказаний в этом формате"

    def run_cases(fmt_of: dict[str, str]) -> tuple[dict[str, CaseResult], list[dict]]:
        results: dict[str, CaseResult] = {}
        missing: list[dict] = []
        for cid in sorted(gold_by_case):
            fmt = fmt_of[cid]
            ok, why = measured(cid, fmt)
            if not ok:
                missing.append({"case_id": cid, "format": fmt, "reason": why})
                continue
            results[cid] = match_case(cid, gold_by_case[cid], preds_by_render.get((cid, fmt), []),
                                      taxonomy, type_match, decisions, doc_tokens.get(cid))
        # фон: ложная находка мутанта, которая есть и на чистой базе того же семейства
        if manifest is not None:
            for cid, r in results.items():
                base = manifest.cases.get(cid, {}).get("base_case_id")
                if not base or base == cid or base not in results:
                    continue
                base_preds = preds_by_render.get((base, fmt_of[base]), [])
                by_key = {p.key: p for p in preds_by_render.get((cid, fmt_of[cid]), [])}
                for fp in r.fp:
                    p = by_key.get(fp["pred_key"])
                    if p is not None and any(same_finding(p, bp) for bp in base_preds):
                        fp["background"] = True
        return results, missing

    doc_tokens: dict[str, list[str] | None] = {}
    for cid in gold_by_case:
        text = manifest.source_text(cid) if manifest is not None else None
        doc_tokens[cid] = _tokens(text) if text is not None else None

    primary_fmt = {cid: chosen_format(cid) for cid in gold_by_case}
    results, missing = run_cases(primary_fmt)

    # ---- агрегаты
    micro = _aggregate(list(results.values()))
    per_type: dict[str, dict] = {}
    types = sorted({x for r in results.values() for x in
                    [*(t["gold_type"] for t in r.tp), *(f["gold_type"] for f in r.fn),
                     *(f["pred_type"] for f in r.fp)]})
    for t in types:
        tp = sum(1 for r in results.values() for x in r.tp if x["gold_type"] == t)
        fn = sum(1 for r in results.values() for x in r.fn if x["gold_type"] == t)
        fp = sum(1 for r in results.values() for x in r.fp if x["pred_type"] == t)
        dup = sum(1 for r in results.values() for x in r.duplicates if x["pred_type"] == t)
        per_type[t] = prf(tp, fp, fn, dup)
    per_family = {}
    for fam in sorted(set(family_of.values())):
        per_family[fam] = {"cases": sum(1 for c in results if family_of[c] == fam),
                           **_aggregate([r for c, r in results.items() if family_of[c] == fam])}
    per_case = {cid: {"family": family_of[cid], "format": primary_fmt[cid],
                      "clean": any(l.expected_outcome == "clean" for l in gold_by_case[cid]),
                      **prf(len(r.tp), len(r.fp), len(r.fn), len(r.duplicates)),
                      "new_real_defects": len(r.new_real)}
                for cid, r in results.items()}

    clean_cases = [cid for cid in results if per_case[cid]["clean"]]
    clean = {
        "cases": len(clean_cases),
        "cases_with_alarms": sum(1 for c in clean_cases if results[c].fp),
        "false_alarms": sum(len(results[c].fp) for c in clean_cases),
        "per_case": {c: len(results[c].fp) for c in clean_cases},
        "rule": "любая находка на кейсе с expected_outcome=clean — ложная тревога (FP)",
    }

    sev = Counter((x["gold_severity"] or "—", x["pred_severity"] or "—")
                  for r in results.values() for x in r.tp)
    severity_agreement = {
        "pairs": sum(sev.values()),
        "agree": sum(v for (g, p), v in sev.items() if g == p and g != "—"),
        "matrix": {f"{g}->{p}": v for (g, p), v in sorted(sev.items())},
    }

    # ---- форматы: отдельное измерение парсера и экспорта, а не новые кейсы
    per_format: dict[str, Any] = {}
    consistency: list[dict] = []
    for fmt in formats_seen:
        fres, fmissing = run_cases({cid: fmt for cid in gold_by_case})
        per_format[fmt] = {"cases_measured": len(fres), "cases_missing": len(fmissing),
                           **_aggregate(list(fres.values()))}
        for cid, r in fres.items():
            if cid in results and primary_fmt[cid] != fmt:
                a = sorted(x["label_id"] for x in results[cid].tp)
                b = sorted(x["label_id"] for x in r.tp)
                consistency.append({"case_id": cid, "primary": primary_fmt[cid], "format": fmt,
                                    "same_tp_labels": a == b, "primary_tp": a, "format_tp": b,
                                    "fp_delta": len(r.fp) - len(results[cid].fp)})

    run_list = [runs_by_render[(c, primary_fmt[c])] for c in sorted(gold_by_case)
                if (c, primary_fmt[c]) in runs_by_render]
    empty_cases = []
    if manifest is not None:
        for cid in results:
            if manifest.cases.get(cid, {}).get("edge") == "empty":
                run = runs_by_render.get((cid, primary_fmt[cid]))
                empty_cases.append({"case_id": cid, "findings": len(results[cid].fp) + len(results[cid].tp),
                                    "run_status": run.status if run else None,
                                    "empty_input_warning": run.empty_input_warning if run else None})

    unmapped = Counter(p.kind or "<нет kind>" for p in preds if not p.kind_mapped)
    if closed:
        warnings.append(f"в эталоне есть строки с visibility={closed}: не смешивайте закрытый набор с dev")

    return {
        "schema_version": "bcc-eval-metrics/1",
        "harness_version": __version__,
        "policy": {
            "type_match": type_match,
            "render_format": render_format or "primary_render из манифеста",
            "mode": mode or (modes[0] if modes else None),
            "statuses": sorted(statuses) if statuses is not None else "все",
            "anchor_rule": "непрерывный общий отрезок токенов ≥ 0.6 опоры или фрагмент ≥ 4 токенов (≥ 3 с числом "
                           "или единицей) и ≥ 0.3 опоры, либо фрагмент ≥ 3 токенов, единственный в документе (нужен манифест); "
                           "на краю отрезка не должны расходиться числа, отрицания и единицы",
            "taxonomy": taxonomy.source,
        },
        "assumptions": ASSUMPTIONS,
        "counts": {
            "gold_rows": len(gold),
            "present_labels": sum(1 for l in gold if l.expected_outcome == "present"),
            "cases_labeled": len(gold_by_case),
            "independent_cases": len(results),
            "families": len({family_of[c] for c in results}),
            "physical_renders_measured": sum(v["cases_measured"] for v in per_format.values()),
            "prediction_rows": len(preds),
            "run_rows": len(runs),
            "unresolved_predictions": len(unresolved),
            "predictions_for_unlabeled_cases": len(unlabeled),
            "missing_measurements": len(missing),
        },
        "micro": micro,
        "per_issue_type": per_type,
        "per_family": per_family,
        "per_case": per_case,
        "clean_controls": clean,
        "edge_cases": {"empty_input": empty_cases},
        "severity_agreement": severity_agreement,
        "per_format": per_format,
        "format_consistency": consistency,
        "runs": _run_stats(run_list),
        "missing_measurements": missing,
        "unmapped_kinds": dict(unmapped),
        "true_positives": [x for r in results.values() for x in r.tp],
        "false_positives": [x for r in results.values() for x in r.fp],
        "false_negatives": [x for r in results.values() for x in r.fn],
        "duplicates": [x for r in results.values() for x in r.duplicates],
        "new_real_defects": [x for r in results.values() for x in r.new_real],
        "ignored_decisions": [x for r in results.values() for x in r.ignored_decisions],
        "unresolved": unresolved,
        "unlabeled": unlabeled,
        "warnings": warnings,
    }


def adjudication_sheet(metrics: dict[str, Any], seed: str | None = None, sample: int | None = None) -> list[dict]:
    """Лист разбора: все FP с подсказкой. decision заполняет человек.

    seed и sample дают воспроизводимую выборку без возвращения (как sampleForReview в qazaq-loc-qa):
    ранг = sha256(seed, pred_key). Seed фиксируется до просмотра результатов.
    """
    import hashlib
    rows = []
    for fp in metrics["false_positives"]:
        rows.append({
            "pred_key": fp["pred_key"], "case_id": fp["case_id"], "pred_type": fp["pred_type"],
            "defect_id": fp["defect_id"], "quotes": fp["quotes"], "reasons": fp["reasons"],
            "near": fp["near"], "background": fp["background"], "decision": fp.get("decision"),
            "label_id": None, "reviewer": None, "note": "",
            "allowed_decisions": ["match", "false_alarm", "new_real_defect", "duplicate"],
        })
    if seed is not None:
        for r in rows:
            r["review_rank"] = hashlib.sha256(json.dumps([seed, r["pred_key"]]).encode("utf-8")).hexdigest()
        rows.sort(key=lambda r: (r["review_rank"], r["pred_key"]))
        if sample is not None:
            rows = rows[:sample]
    return rows
