"""report.json ядра v2: сводка, вердикт по правилу, проверка схемы, запись (владелец №13).

Схема — ``contracts/v2.json`` (CONTRACT.md, раздел 2.6). Отчёт собирает конвейер; этот модуль
досчитывает то, что обязан считать код, а не модель: ``summary`` и вердикт по правилу из раздела 5.

    from bcc_review.v2.render import jsonout
    jsonout.finalize(report)            # summary (+ verdict, если его нет) считает код
    errors = jsonout.write(report, "reports/x.json")   # схема проверяется при записи
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

SCHEMA_ID = "bcc-review/2"
SEVERITIES = ("critical", "major", "minor")
_SCHEMA_CACHE: dict | None = None


class SchemaError(ValueError):
    """report.json не соответствует contracts/v2.json."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


# ---------------------------------------------------------------- схема

def schema_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "contracts" / "v2.json"
        if cand.is_file():
            return cand
    return None


def load_schema() -> dict | None:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        p = schema_path()
        if p is None:
            return None
        _SCHEMA_CACHE = json.loads(p.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def validate(report: dict) -> list[str]:
    """Ошибки схемы человеческим языком: «findings/3/severity: 'high' is not one of …»."""
    schema = load_schema()
    if schema is None:
        return []
    try:
        import jsonschema
    except ImportError:  # зависимость обязательна в pyproject, но отчёт не должен падать из-за неё
        return []
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(report), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(корень)"
        out.append(f"{where}: {err.message}")
    return out


# ---------------------------------------------------------------- счётчики

def is_resolved(f: dict) -> bool:
    return f.get("status") == "resolved" or f.get("status_after_answers") == "resolved"


def open_findings(report: dict) -> list[dict]:
    """Действующие дефекты: снятые ответами владельца (resolved) не считаются."""
    return [f for f in report.get("findings", []) or [] if isinstance(f, dict) and not is_resolved(f)]


def count_quotes(findings: Iterable[dict]) -> tuple[int, int]:
    """(сверено, всего) по цитатам дефектов. «missing» — не сверена."""
    ok = total = 0
    for f in findings:
        for ev in f.get("evidence", []):
            total += 1
            if ev.get("verified", "missing") != "missing":
                ok += 1
    return ok, total


def compute_summary(report: dict) -> dict:
    findings = open_findings(report)
    by_sev = {s: 0 for s in SEVERITIES}
    for f in findings:
        if f.get("severity") in by_sev:
            by_sev[f["severity"]] += 1
    touched = {rid for f in findings for rid in f.get("requirement_ids", [])}
    reqs = report.get("requirements", [])
    ok, total = count_quotes(findings)
    return {
        "requirements": len(reqs),
        "findings": by_sev,
        "requirements_without_findings": sum(1 for r in reqs if r.get("id") not in touched),
        "quotes_verified": ok,
        "quotes_total": total,
        "questions": len(report.get("questions", [])),
    }


def rule_verdict(report: dict) -> dict:
    """Вердикт по правилу кода (CONTRACT.md, раздел 5): {"development", "testing"}.

    Прогон без модели (provider = offline, №12): «нельзя» только при блокирующем критичном дефекте или
    противоречии двух мест, найденном правилом (rule_conflict); иначе «не определено» — смысл не проверялся."""
    run = report.get("run", {}) or {}
    status = run.get("status", "complete")
    if status == "failed":
        return {"development": "none", "testing": "none"}
    findings = open_findings(report)
    out = {}
    if run.get("provider") == "offline":
        for target, blockers in (("development", {"development", "both"}), ("testing", {"testing", "both"})):
            hit = any((f.get("severity") == "critical" or (f.get("rule_conflict") and len(f.get("evidence") or []) >= 2))
                      and f.get("blocks") in blockers for f in findings)
            out[target] = "no" if hit else "undetermined"
        return out
    for target, blockers in (("development", {"development", "both"}), ("testing", {"testing", "both"})):
        crit = any(f.get("severity") == "critical" and f.get("blocks") in blockers for f in findings)
        majors = sum(1 for f in findings if f.get("severity") == "major" and f.get("blocks") in blockers)
        if crit:
            value = "no"
        elif majors >= 3:
            value = "conditional"
        else:
            value = "yes"
        if status == "partial" and value == "yes":
            value = "conditional"
        out[target] = value
    return out


def finalize(report: dict) -> dict:
    """Досчитать поля, которые считает код. Вердикт не перезаписывается, если его уже поставил конвейер."""
    report.setdefault("schema", SCHEMA_ID)
    for key in ("excluded", "rejected", "acceptance_checks", "pair_checks", "trace", "glossary",
                "test_cases", "questions", "checklist"):
        report.setdefault(key, [])
    report["summary"] = compute_summary(report)
    verdict = report.setdefault("verdict", {})
    rule = rule_verdict(report)
    for k in ("development", "testing"):
        verdict.setdefault(k, rule[k])
    verdict.setdefault("summary", "")
    verdict.setdefault("fix_first", [f["id"] for f in sorted(
        (f for f in open_findings(report) if f.get("priority")), key=lambda f: f["priority"])][:7])
    return report


# ---------------------------------------------------------------- запись

def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def write(report: dict, path: str | Path, *, strict: bool = False) -> list[str]:
    """Записать report.json. Ошибки схемы возвращаются и попадают в run.warnings;
    при ``strict=True`` — исключение SchemaError и файл не пишется."""
    errors = validate(report)
    if errors:
        if strict:
            raise SchemaError(errors)
        warnings = report.setdefault("run", {}).setdefault("warnings", [])
        note = f"report.json не прошёл схему contracts/v2.json: {len(errors)} расхождений, первое — {errors[0]}"
        if note not in warnings:
            warnings.append(note)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_json(report), encoding="utf-8")
    return errors


def read(path: str | Path) -> dict:
    data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("report.json: ожидался объект")
    return data
