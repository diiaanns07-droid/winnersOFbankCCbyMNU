"""Резервная перепроверка отчёта без модели (пока не влит модуль №07 ``bcc_review.verification``).

Проверяет: схему, SHA-256 источника, совпадение блоков с повторным чтением источника, каждую цитату
(``block.text[start:end] == quote``), сводные числа, учёт опор, согласованность паспорта и вердикта.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ... import contracts as C


def verify_report(report_path: str | Path, source_path: str | Path, *, reader=None) -> dict[str, Any]:
    errors: list[str] = []
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    errors += [f"схема: {e}" for e in C.validation_errors(report, C.REPORT_SCHEMA)]
    if errors:
        return {"ok": False, "errors": errors, "counts": {}}
    sha = C.sha256_file(source_path)
    if sha != report["document"]["id"]:
        errors.append(f"источник: SHA-256 {sha[:12]}… не совпадает с document.id {report['document']['id'][:12]}…")
    if report["run"]["source_sha256"] != report["document"]["id"]:
        errors.append("паспорт: run.source_sha256 не совпадает с document.id")
    errors += [f"опоры: {e}" for e in C.evidence_errors(report)]

    if reader is not None and sha == report["document"]["id"]:
        fresh = reader(source_path)
        fresh_blocks = {b["id"]: b["text"] for b in fresh["blocks"]}
        for b in report["document"]["blocks"]:
            if fresh_blocks.get(b["id"]) != b["text"]:
                errors.append(f"источник: блок {b['id']} при повторном чтении отличается")

    from ..verdict import build_summary
    expected = build_summary(report)
    for key, val in expected.items():
        if report["summary"].get(key) != val:
            errors.append(f"счётчик summary.{key}: в отчёте {report['summary'].get(key)!r}, по спискам {val!r}")

    audit = report["run"]["evidence_audit"]
    if audit["checked"] != audit["confirmed"] + audit["ambiguous"] + audit["rejected"]:
        errors.append("учёт опор: checked ≠ confirmed + ambiguous + rejected")

    run = report["run"]
    stages = run["stages"]
    if sum(s["calls"] for s in stages) != run["calls"]["physical"]:
        errors.append("паспорт: сумма вызовов по этапам не равна run.calls.physical")
    if sum(s["cache_hits"] for s in stages) != run["calls"]["cache_hits"]:
        errors.append("паспорт: сумма попаданий в кэш по этапам не равна run.calls.cache_hits")
    bad = {s["name"] for s in stages if s["status"] in ("failed", "partial", "skipped")}
    if set(run["incomplete_stages"]) != bad:
        errors.append("паспорт: incomplete_stages не совпадает со статусами этапов")
    if run["status"] == "complete" and bad:
        errors.append("паспорт: статус complete при незавершённых этапах")
    if run["mode"] == "rules_plus_llm" and run["calls"]["physical"] + run["calls"]["cache_hits"] == 0:
        errors.append("паспорт: режим rules_plus_llm без единого ответа модели")
    for target in ("development", "testing"):
        if run["status"] != "complete" and report["verdict"][target]["status"] == "ready" and not \
                run.get("options", {}).get("allow_partial_ready"):
            errors.append(f"вердикт: {target} = ready при неполном прогоне")
    for f in report["findings"]:
        if f["status"] == "confirmed" and f["meaning_status"] not in ("confirmed", "deterministic"):
            errors.append(f"{f['id']}: confirmed без подтверждения смысла")

    counts = {"blocks": len(report["document"]["blocks"]), "requirements": len(report["requirements"]),
              "findings": len(report["findings"]),
              "evidence": sum(len(f["evidence"]) for f in report["findings"]) + sum(
                  len(r["evidence"]) for r in report["requirements"])}
    return {"ok": not errors, "errors": errors, "counts": counts}
