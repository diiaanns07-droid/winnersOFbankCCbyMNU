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
    противоречии двух мест, найденном правилом (rule_conflict); иначе «не определено» — смысл не проверялся.
    Нет ни требований, ни дефектов (пустой документ) — «не определено»: проверять нечего."""
    run = report.get("run", {}) or {}
    status = run.get("status", "complete")
    if status == "failed":
        return {"development": "none", "testing": "none"}
    findings = open_findings(report)
    out = {}
    if not report.get("requirements") and not findings and run.get("provider") != "offline":
        # пустой документ или в нём нет ни одного требования: проверять нечего — «можно» не выносится (№14, п. 1)
        return {"development": "undetermined", "testing": "undetermined"}
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


_READY_RU = {"no": "нельзя", "conditional": "с условиями", "yes": "можно", "undetermined": "не определено",
             "none": "не вынесен"}


def _restore_resolved(report: dict) -> None:
    """Режим --answers: конвейер кладёт в findings только оставшиеся дефекты, а вопросы, чек-лист и «исправить
    первым» ссылаются и на снятые. Снятые возвращаются в перечень с status_after_answers=resolved — ссылки
    остаются целыми, в счётчики и вердикт снятые не входят."""
    before = report.get("findings_before")
    if not report.get("clarification") or not isinstance(before, list):
        return
    findings = report.setdefault("findings", [])
    have = {f.get("id") for f in findings if isinstance(f, dict)}
    for f in before:
        if isinstance(f, dict) and f.get("id") and f["id"] not in have:
            findings.append({**f, "status_after_answers": "resolved"})
            have.add(f["id"])


def _after_summary(report: dict, rule: dict) -> str:
    cl = report.get("clarification") or {}
    s = compute_summary(report)["findings"]
    bv = (cl.get("before") or {}).get("verdict") or {}
    text = (f"После ответов владельца разработка — {_READY_RU.get(rule['development'], '—')}, тестирование — "
            f"{_READY_RU.get(rule['testing'], '—')}: критичных дефектов {s['critical']}, существенных {s['major']}, "
            f"незначительных {s['minor']}. Снято ответами {cl.get('resolved', 0)}, уточнено {cl.get('changed', 0)}, "
            f"новых конфликтов {len(cl.get('new_findings') or [])}.")
    if bv:
        text += (f" До ответов: разработка — {_READY_RU.get(bv.get('development'), '—')}, тестирование — "
                 f"{_READY_RU.get(bv.get('testing'), '—')}.")
    return text


def finalize(report: dict) -> dict:
    """Досчитать поля, которые считает код: summary и вердикт по правилу (CONTRACT 5).

    Если вердикт конвейера расходится с правилом (например, после ответов владельца), ставится вердикт по правилу,
    иначе отчёт не прошёл бы verify; обоснование при этом пересчитывается."""
    report.setdefault("schema", SCHEMA_ID)
    for key in ("excluded", "rejected", "acceptance_checks", "pair_checks", "trace", "glossary",
                "test_cases", "questions", "checklist"):
        report.setdefault(key, [])
    _restore_resolved(report)
    report["summary"] = compute_summary(report)
    verdict = report.setdefault("verdict", {})
    rule = rule_verdict(report)
    changed = any(verdict.get(k) not in (None, rule[k]) for k in ("development", "testing"))
    for k in ("development", "testing"):
        verdict[k] = rule[k]
    if report.get("clarification"):
        cl = report["clarification"]
        cl.setdefault("before", {}).setdefault("summary", verdict.get("summary", ""))
        if changed or not verdict.get("summary"):
            verdict["summary"] = _after_summary(report, rule)
    elif changed:
        report.setdefault("run", {}).setdefault("warnings", []).append(
            "вердикт конвейера расходился с правилом кода и пересчитан по правилу")
    verdict.setdefault("summary", "")
    open_ids = {f.get("id") for f in open_findings(report)}
    fix = [i for i in verdict.get("fix_first") or [] if i in open_ids]
    if not fix:
        fix = [f["id"] for f in sorted((f for f in open_findings(report) if f.get("priority")),
                                       key=lambda f: f["priority"])][:7]
    if not fix:
        fix = [f["id"] for f in open_findings(report) if f.get("severity") in ("critical", "major")][:5]
    verdict["fix_first"] = fix
    _verdict_texts(report)
    return report


def _verdict_texts(report: dict) -> None:
    """`verdict.why` (первый экран, «Почему») и `verdict.reason` («Итог», обоснование) — тексты кода по финальным
    уровням, те же, что в Markdown: HTML и другие потребители берут их вместо `summary` судьи (в нём судья мог назвать
    блокером дефект, который калибровка понизила). `summary` не меняется."""
    try:
        from . import markdown as _md
        c = _md._Ctx(_md._clean_report(report))
        why, reason = _md._why(c), _md._final_reason(c)
    except Exception:  # noqa: BLE001 — тексты для показа не должны мешать записи отчёта
        return
    report["verdict"]["why"] = str(why or "")
    report["verdict"]["reason"] = str(reason or "")


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
