"""Независимые от экспортёра подсчёты и разбор Markdown для тестов p17.

Здесь нарочно не используется bcc_review.exports._common: числа считаются
заново прямо из JSON контракта v1, чтобы сверка не повторяла код рендера.
"""

from __future__ import annotations

import re
from typing import Any

NBSP = " "
SEV_RANK = {"critical": 0, "major": 1, "minor": 2}


FAMILY = {"conflict": "conflict", "incorrect": "conflict", "incomplete": "gap", "omission": "gap",
          "placeholder": "gap", "non_singular": "structure", "duplicate": "structure"}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").split()).strip(" .,;:!?«»\"'")


def independent_groups(findings: list[dict[str, Any]]) -> list[set[str]]:
    """Первопричины без кода экспорта: явные связи или совпадение причины вместе с исходами."""
    ids = [f["id"] for f in findings]
    group = {i: {i} for i in ids}

    def join(a: str, b: str) -> None:
        merged = group[a] | group[b]
        for x in merged:
            group[x] = merged

    for f in findings:
        for target in [f.get("duplicate_of"), *(f.get("merged_from") or [])]:
            if target in group and target != f["id"]:
                join(f["id"], target)
    for a in findings:
        for b in findings:
            if a["id"] >= b["id"]:
                continue
            if a.get("root_cause_id") and a.get("root_cause_id") == b.get("root_cause_id"):
                join(a["id"], b["id"])
            ca, cb = a.get("cause") or {}, b.get("cause") or {}
            oa = {_norm(o) for o in ca.get("outcomes") or [] if _norm(o)}
            ob = {_norm(o) for o in cb.get("outcomes") or [] if _norm(o)}
            if (oa and oa == ob and _norm(ca.get("object")) and _norm(ca.get("object")) == _norm(cb.get("object"))
                    and _norm(ca.get("condition")) and _norm(ca.get("condition")) == _norm(cb.get("condition"))
                    and FAMILY.get(a["kind"], a["kind"]) == FAMILY.get(b["kind"], b["kind"])):
                join(a["id"], b["id"])
    out: list[set[str]] = []
    for i in ids:
        if group[i] not in out:
            out.append(group[i])
    return out


def independent_counts(report: dict[str, Any]) -> dict[str, int]:
    reqs = report["requirements"]
    findings = report["findings"]
    confirmed = [f for f in findings if f["status"] == "confirmed"]
    by_id = {f["id"]: f for f in confirmed}
    groups = independent_groups(confirmed)
    sev = {"critical": 0, "major": 0, "minor": 0}
    for members in groups:
        sev[min((by_id[m] for m in members), key=lambda m: SEV_RANK[m["severity"]])["severity"]] += 1
    touched = {r for f in confirmed for r in f["req_ids"]}
    reviewed = [r["id"] for r in reqs if r["review_status"] == "reviewed"]
    checks = report["checks"]
    return {
        "requirements_total": len(reqs),
        "requirements_reviewed": len(reviewed),
        "requirements_partial": sum(1 for r in reqs if r["review_status"] == "partial"),
        "requirements_not_reviewed": sum(1 for r in reqs if r["review_status"] == "not_reviewed"),
        "requirements_clean": sum(1 for r in reviewed if r not in touched),
        "findings_total": len(findings),
        "findings_critical": sum(1 for f in findings if f["severity"] == "critical"),
        "findings_major": sum(1 for f in findings if f["severity"] == "major"),
        "findings_minor": sum(1 for f in findings if f["severity"] == "minor"),
        "findings_confirmed": len(confirmed),
        "findings_needs_review": sum(1 for f in findings if f["status"] == "needs_review"),
        # Движок пишет merged_from = [собственный cid, поглощённые…].
        "merged_candidates": sum(max(0, len(f.get("merged_from") or []) - 1) for f in findings),
        "defects_unique": len(groups),
        "same_cause_merged": len(confirmed) - len(groups),
        "defects_critical": sev["critical"],
        "defects_major": sev["major"],
        "defects_minor": sev["minor"],
        "rejected": len(report.get("rejected") or []),
        "checks_pass": sum(1 for c in checks if c["status"] == "pass"),
        "checks_issue": sum(1 for c in checks if c["status"] == "issue"),
        "checks_unknown": sum(1 for c in checks if c["status"] == "unknown"),
        "checks_na": sum(1 for c in checks if c["status"] == "na"),
    }


def section(md: str, heading: str) -> str:
    """Текст раздела от заголовка ``heading`` до следующего заголовка того же или старшего уровня."""
    lines = md.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#+) ", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def split_row(line: str) -> list[str]:
    """Ячейки строки таблицы GFM с учётом экранированного ``\\|``."""
    inner = line.strip()[1:-1]
    cells, buf, i = [], [], 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            buf.append(inner[i : i + 2])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def row_numbers(md: str, label: str) -> list[int]:
    for line in md.splitlines():
        if line.startswith(f"| {label} |"):
            cell = split_row(line)[1]
            return [int(x.replace(NBSP, "")) for x in re.findall(r"\d+(?: \d{3})*", cell)]
    raise AssertionError(f"нет строки «{label}»")


def tables(md: str) -> list[list[str]]:
    out, cur = [], []
    for line in md.splitlines():
        if line.startswith("|"):
            cur.append(line)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out
