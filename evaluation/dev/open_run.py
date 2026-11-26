"""Один воспроизводимый прогон открытого dev-набора через действующий CLI продукта.

    python -m evaluation.dev open-run --product-src ../stand/src --out out/open_run

Что делается (режим rules_only, кэш выключен, сеть закрыта песочницей счётчика):
1. MD всех кейсов, кроме INCOMPLETE_CASE;
2. DOCX того же case_id, что и в п. 1 (DOCX_CASE): второе представление одного кейса;
3. отдельный прогон INCOMPLETE_CASE с таймаутом счётчика 0.001 с: процесс прерывается,
   отчёт не пишется, строка run получает status=failed. Это технически незавершённый прогон,
   в итогах он виден как пропуск измерения, а не как ноль находок.
Затем строки объединяются и считаются по эталону dev-набора (политика bcc-eval-policy/1).

results_sha256 — хеш смысловых итогов без длительностей, путей и времени: два прогона на
одинаковых коде продукта и счётчика дают один хеш.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

from evaluation.harness import POLICY_VERSION, __version__, harness_sha256
from evaluation.harness.runner import run_manifest
from evaluation.harness.taxonomy import Taxonomy

CORPUS = Path(__file__).resolve().parent / "corpus"
DOCX_CASE = "cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict"
INCOMPLETE_CASE = "autopay.event_conflict.insufficient_funds_credit"
INCOMPLETE_TIMEOUT_S = 0.001
VOLATILE = {"where", "duration_s", "report_path", "inputs", "run_id", "started_at", "finished_at"}


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def results_sha256(m: dict) -> str:
    keep = {k: m[k] for k in ("counts", "micro", "per_issue_type", "per_family", "per_case", "clean_controls",
                              "per_format", "format_consistency", "missing_measurements", "true_positives",
                              "false_positives", "false_negatives", "duplicates", "policy", "policy_version")}
    r = m.get("runs", {})
    keep["runs"] = {k: r.get(k) for k in ("runs", "modes", "status", "physical_calls", "tokens", "transport",
                                          "implementations", "violations")}
    return hashlib.sha256(json.dumps(_strip(keep), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def open_run(out: str, product_src: str | None = None, product_cmd: str | None = None) -> dict:
    from evaluation.harness.__main__ import cmd_score

    out_dir = Path(out)
    manifest = CORPUS / "manifest.json"
    tax = Taxonomy.load()
    if product_src:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(Path(product_src).resolve()), os.environ.get("PYTHONPATH", "")])
    cmd = product_cmd or f"{shlex.quote(sys.executable)} -m bcc_review {{input}} {{output}}"
    cases = sorted(c["case_id"] for c in json.loads(manifest.read_text(encoding="utf-8"))["cases"])
    parts = {
        "md": dict(fmt="md", cases=[c for c in cases if c != INCOMPLETE_CASE]),
        "docx": dict(fmt="docx", cases=[DOCX_CASE]),
        "incomplete": dict(fmt="md", cases=[INCOMPLETE_CASE], timeout=INCOMPLETE_TIMEOUT_S),
    }
    configs = {}
    for name, kw in parts.items():
        configs[name] = run_manifest(str(manifest), "rules_only", str(out_dir / name), tax, product_cmd=cmd,
                                     cache="off", **kw)
    merged = out_dir / "predictions.jsonl"
    merged.write_text("".join((out_dir / n / "predictions.jsonl").read_text(encoding="utf-8") for n in parts),
                      encoding="utf-8")
    cmd_score(["--gold", str(CORPUS / "labels.jsonl"), "--pred", str(merged), "--manifest", str(manifest),
               "--out", str(out_dir / "metrics.json"), "--adjudication-out", str(out_dir / "adjudication.jsonl"),
               "--quiet"])
    m = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    summary = {
        "harness": f"{__version__} {POLICY_VERSION} {harness_sha256()}",
        "mode": m["policy"]["mode"], "type_match": m["policy"]["type_match"],
        "independent_cases": m["counts"]["independent_cases"], "cases_labeled": m["counts"]["cases_labeled"],
        "missing_measurements": m["missing_measurements"],
        "physical_renders_measured": m["counts"]["physical_renders_measured"],
        "per_format": {k: {"cases": v["cases_measured"], "tp": v["tp"], "fp": v["fp"], "fn": v["fn"]}
                       for k, v in m["per_format"].items()},
        "micro": {k: m["micro"][k] for k in ("tp", "fp", "fn", "duplicates", "precision", "recall", "f1",
                                             "pending_adjudication", "clean_false_alarms")},
        "clean_controls": {k: m["clean_controls"][k] for k in ("cases", "cases_with_alarms", "false_alarms")},
        "run_status": m["runs"]["status"], "physical_calls": m["runs"]["physical_calls"]["total"],
        "transport": m["runs"]["transport"], "implementations": m["runs"]["implementations"],
        "network_sandbox": {n: c["network_sandbox"] for n, c in configs.items()},
        "violations": m["runs"]["violations"],
        "results_sha256": results_sha256(m),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
