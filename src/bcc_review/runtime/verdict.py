"""Решение о готовности к разработке и тестированию — отдельно, только из данных Report.

* ``not_ready`` — есть подтверждённое критичное замечание, блокирующее эту работу.
* ``unknown`` — прогон неполный (усечённый ответ, недоступная модель, частично прочитанный документ,
  исчерпанный бюджет) или критичное замечание ждёт проверки. По умолчанию неполный прогон не может
  дать «ready»: молчание модели не означает отсутствие дефектов.
* ``ready`` — полный прогон без блокирующих критичных замечаний.
"""

from __future__ import annotations

from typing import Any

from ..contracts import SEVERITIES

DEFAULT_BLOCKS = {
    "conflict": ["development", "testing"], "incorrect": ["development", "testing"],
    "infeasible": ["development", "testing"], "incomplete": ["development", "testing"],
    "omission": ["development", "testing"], "ambiguity": ["development", "testing"],
    "unverifiable": ["testing"], "placeholder": ["development"], "traceability": ["testing"],
}
ACTION_ORDER = {"conflict": 0, "incorrect": 1, "omission": 2, "incomplete": 3, "ambiguity": 4, "unverifiable": 5}


def default_blocks(finding: dict[str, Any]) -> list[str]:
    if finding["severity"] != "critical":
        return []
    return list(DEFAULT_BLOCKS.get(finding["kind"], ["development"]))


def _readiness(target: str, findings: list[dict[str, Any]], run: dict[str, Any], allow_partial: bool) -> dict:
    crit = [f for f in findings if f["severity"] == "critical" and target in f.get("blocks", [])]
    confirmed = [f for f in crit if f["status"] == "confirmed"]
    review = [f for f in crit if f["status"] != "confirmed"]
    what = "разработку" if target == "development" else "тестирование"
    if confirmed:
        reasons = [f"{f['id']}: {f['title']}" for f in confirmed]
        if run["status"] != "complete":
            reasons.append("Прогон неполный: возможны и другие блокирующие дефекты.")
        return {"status": "not_ready", "reasons": reasons, "finding_ids": [f["id"] for f in confirmed]}
    if run["status"] != "complete" and not allow_partial:
        reasons = [f"Прогон {run['status']}: " + "; ".join(run.get("status_reasons") or ["часть этапов не завершена"])]
        reasons.append(f"Без полной проверки нельзя утверждать, что {what} можно начинать.")
        reasons += [f"{f['id']} ждёт проверки: {f['title']}" for f in review]
        return {"status": "unknown", "reasons": reasons, "finding_ids": [f["id"] for f in review]}
    if review:
        return {"status": "unknown",
                "reasons": [f"{f['id']}: критичное замечание требует проверки аналитиком — {f['title']}" for f in review],
                "finding_ids": [f["id"] for f in review]}
    return {"status": "ready", "reasons": [f"Подтверждённых критичных замечаний, блокирующих {what}, нет."],
            "finding_ids": []}


def build_verdict(findings: list[dict[str, Any]], run: dict[str, Any], *, allow_partial_ready: bool = False,
                  max_actions: int = 7) -> dict[str, Any]:
    dev = _readiness("development", findings, run, allow_partial_ready)
    test = _readiness("testing", findings, run, allow_partial_ready)
    sev_rank = {s: i for i, s in enumerate(SEVERITIES)}
    ranked = sorted(
        (f for f in findings if f["severity"] in ("critical", "major")),
        key=lambda f: (sev_rank[f["severity"]], 0 if f["status"] == "confirmed" else 1,
                       -len(f.get("blocks", [])), ACTION_ORDER.get(f["kind"], 9), f["id"]))
    actions = []
    for f in ranked[:max_actions]:
        rec = (f.get("recommendation") or "").strip()
        text = f"{f['title']}" + (f" — {rec}" if rec else "")
        actions.append({"order": len(actions) + 1, "action": text[:400], "finding_ids": [f["id"]]})
    if run["status"] != "complete":
        actions.append({"order": len(actions) + 1, "finding_ids": [],
                        "action": "Повторить прогон с доступной моделью для этапов: "
                                  + ", ".join(run.get("incomplete_stages") or ["—"])})
    basis = ("Готовность считается отдельно для разработки и тестирования: блокирует только подтверждённое "
             "критичное замечание с указанным бизнес-последствием и блокируемым решением; неполный прогон "
             "даёт «не определено», а не «можно начинать».")
    return {"development": dev, "testing": test, "first_actions": actions, "basis": basis}


def build_summary(report: dict[str, Any]) -> dict[str, Any]:
    findings = report["findings"]
    checks = report["checks"]
    return {
        "requirements": len(report["requirements"]),
        "reviewed_requirements": sum(1 for r in report["requirements"] if r["review_status"] == "reviewed"),
        "findings": len(findings),
        "by_severity": {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES},
        "by_status": {s: sum(1 for f in findings if f["status"] == s) for s in ("confirmed", "needs_review")},
        "critical_ids": [f["id"] for f in findings if f["severity"] == "critical"],
        "checks": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "issue", "unknown", "na")},
    }
