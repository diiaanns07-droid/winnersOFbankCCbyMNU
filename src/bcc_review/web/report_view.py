"""Чтение Report (contracts/v1.json) для показа. Только представление: никакой оценки качества.

Читатель терпим к необязательным полям: если движок не заполнил раздел, интерфейс так и
пишет, а не додумывает. Несовпадения со схемой собираются в ``contract_notes``: если
доступен ``bcc_review.contracts``, это ошибки ``validate`` и ``evidence_errors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY = {"critical": ("критичное", 0), "major": ("существенное", 1), "minor": ("незначительное", 2)}
FINDING_STATUS = {"confirmed": "подтверждено", "needs_review": "требует проверки"}
MODE = {
    "rules_plus_llm": "правила + LLM",
    "rules_only": "только правила (без LLM)",
    "mock": "mock: ответы модели из сценария, живая модель не вызывалась",
}
CRITERIA = {
    "necessary": "необходимость", "appropriate": "уместность", "unambiguous": "однозначность",
    "complete": "полнота", "singular": "единичность", "feasible": "осуществимость",
    "verifiable": "проверяемость", "correct": "корректность", "conforming": "соответствие шаблону",
    "set_complete": "полнота набора", "set_consistent": "согласованность набора",
    "set_feasible": "осуществимость набора", "set_comprehensible": "понятность набора",
    "set_validatable": "валидируемость набора", "ranked": "ранжирование", "modifiable": "модифицируемость",
    "traceable": "прослеживаемость",
}
READINESS = {
    "ready": "можно начинать",
    "not_ready": "нельзя начинать",
    "unknown": "не определено: проверка неполная",
    # совместимость с ранними черновиками
    "blocked": "нельзя начинать",
    "conditional": "можно с условиями",
    "insufficient": "не определено: проверка неполная",
}
READINESS_TONE = {"ready": "ready", "not_ready": "blocked", "blocked": "blocked", "conditional": "conditional"}
BLOCKS = {"development": "разработку", "testing": "тестирование"}
PARTIAL_READ_CODES = ("partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input")
STAGES = {
    "engine": "движок",
    "read": "чтение документа", "parse": "чтение документа",
    "lint": "проверка по правилам", "rules": "проверка по правилам",
    "inventory": "нарезка требований", "requirements": "нарезка требований", "segment": "нарезка требований",
    "individual": "проверка требований", "checks": "проверка требований",
    "cross": "проверка набора", "set_checks": "проверка набора", "set": "проверка набора", "facts": "сверка фактов",
    "evidence": "сверка опор", "verify": "сверка опор", "verify_meaning": "проверка смысла", "merge": "объединение замечаний",
    "questions": "уточняющие вопросы",
    "decisions": "вопросы и решения", "clarify": "формулировка вопросов", "answers": "учёт ответов",
    "cross.pairs": "противоречия пар требований", "cross.coverage": "покрытие приёмкой",
    "bank": "чек-лист банка", "verdict": "вердикт",
    "diff": "сравнение редакций", "compare": "сравнение редакций",
    "render": "запись отчёта", "markdown": "запись отчёта", "export": "экспорт", "html": "экспорт HTML",
    "pdf": "экспорт PDF", "docx": "экспорт DOCX", "jira": "экспорт Jira",
}


def stage_label(stage: str | None) -> str:
    return STAGES.get(stage or "", stage or "")


def warning_text(w: Any) -> str:
    if isinstance(w, dict):
        msg = str(w.get("message") or "")
        code = w.get("code")
        return f"{msg} [{code}]" if code and code not in msg else msg
    return str(w)


def loc_text(loc: Any) -> str:
    if not isinstance(loc, dict):
        return str(loc or "")
    parts = []
    if "page" in loc:
        parts.append(f"стр. {loc['page']}")
    line = loc.get("line_start", loc.get("line"))
    end = loc.get("line_end")
    if line is not None:
        parts.append(f"строка {line}" if not end or end == line else f"строки {line}–{end}")
    if "path" in loc:
        parts.append(str(loc["path"]))
    return ", ".join(parts)


@dataclass
class Fragment:
    label: str
    block_id: str
    section: str
    where: str
    before: str
    quote: str
    after: str
    verified: bool


@dataclass
class FindingView:
    id: str
    title: str
    severity: str
    severity_label: str
    status: str
    status_label: str
    criterion: str
    criterion_label: str
    kind: str
    scope: str
    impact: str
    recommendation: str
    blocked_decision: str
    blocks: list[str]
    req_ids: list[str]
    fragments: list[Fragment]
    witness: dict[str, Any] | None
    raw: dict[str, Any]


@dataclass
class ReportView:
    raw: dict[str, Any]
    run: dict[str, Any]
    mode: str
    mode_label: str
    development: dict[str, Any]
    testing: dict[str, Any]
    first_actions: list[dict[str, Any]]
    basis: str
    findings: list[FindingView]
    questions: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    diff: dict[str, list[dict[str, Any]]] | None
    warnings: list[str]
    doc_warnings: list[str]
    doc_partial: bool
    counts: dict[str, int]
    calls: dict[str, Any]
    stages: list[dict[str, Any]]
    contract_notes: list[str] = field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        return self.mode != "rules_plus_llm" or self.run.get("status") != "complete" or self.doc_partial

    def finding(self, fid: str) -> FindingView | None:
        return next((f for f in self.findings if f.id == fid), None)


def _readiness(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        return {"state": "unknown", "tone": "insufficient", "label": READINESS["unknown"], "reason": "движок не заполнил", "finding_ids": []}
    state = v.get("status") or v.get("state")
    if state not in READINESS:
        ready = v.get("ready")
        state = "ready" if ready is True else "not_ready" if ready is False else "unknown"
    reasons = v.get("reasons")
    reason = "; ".join(map(str, reasons)) if isinstance(reasons, list) else str(v.get("reason") or "")
    return {
        "state": state,
        "tone": READINESS_TONE.get(state, "insufficient"),
        "label": READINESS[state],
        "reason": reason,
        "finding_ids": [str(x) for x in v.get("finding_ids") or []],
    }


def _crop(text: str, start: int, end: int, width: int = 220) -> tuple[str, str, str]:
    before = ("…" if start - width > 0 else "") + text[max(0, start - width):start]
    after = text[end:end + width] + ("…" if end + width < len(text) else "")
    return before, text[start:end], after


def _fragments(evidence: list[Any], blocks: dict[str, dict], labels: list[str] | None = None) -> list[Fragment]:
    out = []
    for i, ev in enumerate(evidence or []):
        if not isinstance(ev, dict):
            continue
        bid = str(ev.get("block_id") or "")
        block = blocks.get(bid) or {}
        text = str(block.get("text") or "")
        quote = str(ev.get("quote") or "")
        start, end = ev.get("start"), ev.get("end")
        verified = isinstance(start, int) and isinstance(end, int) and bool(quote) and text[start:end] == quote
        before, q, after = _crop(text, start, end) if verified else ("", quote, "")
        label = labels[i] if labels and i < len(labels) else ""
        out.append(Fragment(label, bid, " › ".join(map(str, block.get("section") or [])), loc_text(block.get("loc")), before, q, after, verified))
    return out


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _contract_notes(report: dict[str, Any]) -> list[str]:
    try:
        from bcc_review.contracts import REPORT_SCHEMA, evidence_errors, validation_errors  # type: ignore
    except Exception:
        notes = [f"нет поля {k}" for k in ("schema_version", "run", "document", "findings", "verdict") if k not in report]
        return notes
    try:
        return validation_errors(report, REPORT_SCHEMA, limit=10) + evidence_errors(report)[:10]
    except Exception as exc:  # pragma: no cover
        return [f"проверка контракта не выполнена: {exc}"]


def _diff(raw: Any, current: list[FindingView], previous: "ReportView | None") -> dict[str, list[dict[str, Any]]] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    names = {
        "resolved": ("resolved", "fixed", "closed"),
        "introduced": ("introduced", "new", "added"),
        "persisting": ("persisting", "remaining", "unchanged"),
        "unassessed": ("unassessed",),
    }
    cur = {f.id: f for f in current}
    prev = {f.id: f for f in previous.findings} if previous else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key, aliases in names.items():
        items = next((raw[a] for a in aliases if isinstance(raw.get(a), list)), [])
        norm = []
        for x in items:
            x = x if isinstance(x, dict) else {"reason": str(x)}
            old_ids = [str(i) for i in x.get("old_ids") or ([x["base_finding_id"]] if x.get("base_finding_id") else [])]
            new_ids = [str(i) for i in x.get("new_ids") or ([x["finding_id"]] if x.get("finding_id") and key != "resolved" else [])]
            if key == "resolved" and not old_ids and x.get("finding_id"):
                old_ids = [str(x["finding_id"])]
            ref = next((cur[i] for i in new_ids if i in cur), None) or next((prev[i] for i in old_ids if i in prev), None)
            norm.append({
                "old_ids": old_ids, "new_ids": new_ids, "reason": str(x.get("reason") or ""),
                "title": ref.title if ref else str(x.get("title") or ""),
                "severity": ref.severity if ref else str(x.get("severity") or ""),
                "id": (new_ids or old_ids or [""])[0],
            })
        out[key] = norm
    return out


def build(report: dict[str, Any], previous: dict[str, Any] | None = None) -> ReportView:
    run = report.get("run") or {}
    doc = report.get("document") or {}
    blocks = {str(b.get("id")): b for b in _as_list(doc.get("blocks")) if isinstance(b, dict)}

    findings = []
    for f in _as_list(report.get("findings")):
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity") or "minor")
        witness = f.get("witness") if isinstance(f.get("witness"), dict) else None
        if witness and (witness.get("evidence_a") or witness.get("evidence_b")):
            frags = _fragments([witness.get("evidence_a"), witness.get("evidence_b")], blocks, ["А", "Б"])
        else:
            frags = _fragments(_as_list(f.get("evidence")), blocks)
        crit = str(f.get("criterion") or "")
        findings.append(FindingView(
            id=str(f.get("id") or ""), title=str(f.get("title") or f.get("kind") or "без названия"),
            severity=sev, severity_label=SEVERITY.get(sev, (sev, 9))[0],
            status=str(f.get("status") or ""), status_label=FINDING_STATUS.get(str(f.get("status")), str(f.get("status") or "")),
            criterion=crit, criterion_label=CRITERIA.get(crit, crit), kind=str(f.get("kind") or ""), scope=str(f.get("scope") or ""),
            impact=str(f.get("impact") or ""), recommendation=str(f.get("recommendation") or ""),
            blocked_decision=str(f.get("blocked_decision") or ""),
            blocks=[BLOCKS.get(str(b), str(b)) for b in _as_list(f.get("blocks"))],
            req_ids=[str(x) for x in _as_list(f.get("req_ids"))], fragments=frags, witness=witness, raw=f,
        ))
    findings.sort(key=lambda fv: (SEVERITY.get(fv.severity, ("", 9))[1], fv.status != "confirmed", fv.id))

    decisions = [d for d in _as_list(report.get("decisions")) if isinstance(d, dict)]
    version = str(doc.get("id") or run.get("source_sha256") or "")
    # Номер вопроса однозначен только внутри версии документа: решение относится к вопросу
    # этого отчёта, лишь если оно дано к этой же версии (как в HTML №13).
    by_q = {str(d.get("question_id")): d for d in decisions if str(d.get("source_sha256") or "") == version}
    questions = []
    for q in _as_list(report.get("questions")):
        if not isinstance(q, dict) or not q.get("id"):
            continue
        qq = dict(q)
        qq["id"] = str(q["id"])
        qq["text"] = str(q.get("prompt") or q.get("text") or q.get("question") or "")
        opts = []
        for i, o in enumerate(_as_list(q.get("options")), start=1):
            if isinstance(o, dict):
                opts.append({"id": str(o.get("id") or i), "text": str(o.get("text") or o.get("label") or "")})
            else:
                opts.append({"id": str(i), "text": str(o)})
        qq["options_norm"] = opts
        qq["decision"] = by_q.get(qq["id"])
        questions.append(qq)

    counts = {"total": len(findings), "critical": 0, "major": 0, "minor": 0, "needs_review": 0}
    for fv in findings:
        if fv.severity in counts:
            counts[fv.severity] += 1
        if fv.status == "needs_review":
            counts["needs_review"] += 1
    answered = set(by_q)
    counts["questions_open"] = sum(1 for q in questions if q["id"] not in answered)
    counts["requirements"] = len(_as_list(report.get("requirements")))

    verdict = report.get("verdict") or {}
    actions = []
    for a in _as_list(verdict.get("first_actions") or verdict.get("actions")):
        if isinstance(a, dict):
            actions.append({"order": a.get("order"), "text": str(a.get("action") or a.get("text") or ""), "finding_ids": [str(x) for x in a.get("finding_ids") or []]})
        else:
            actions.append({"order": None, "text": str(a), "finding_ids": []})

    doc_warnings_raw = _as_list(doc.get("warnings"))
    doc_partial = any(isinstance(w, dict) and w.get("code") in PARTIAL_READ_CODES for w in doc_warnings_raw) or any(
        isinstance(w, str) for w in doc_warnings_raw
    )
    calls = run.get("calls")
    calls = calls if isinstance(calls, dict) else {"physical": calls}
    mode = str(run.get("mode") or "")
    prev_view = build(previous) if previous else None
    return ReportView(
        raw=report, run=run, mode=mode, mode_label=MODE.get(mode, mode or "не указан"),
        development=_readiness(verdict.get("development", verdict.get("dev"))),
        testing=_readiness(verdict.get("testing", verdict.get("test"))),
        first_actions=actions, basis=str(verdict.get("basis") or ""),
        findings=findings, questions=questions, decisions=decisions,
        diff=_diff(report.get("diff"), findings, prev_view),
        warnings=[warning_text(w) for w in _as_list(report.get("warnings"))],
        doc_warnings=[warning_text(w) for w in doc_warnings_raw],
        doc_partial=doc_partial, counts=counts, calls=calls,
        stages=[s for s in _as_list(run.get("stages")) if isinstance(s, dict)],
        contract_notes=_contract_notes(report),
    )


def attention_items(view: ReportView) -> list[dict[str, str]]:
    """Что ещё требует внимания: только из полей отчёта, без собственной оценки."""
    items: list[dict[str, str]] = []
    if view.diff is not None:
        for d in view.diff.get("persisting", []) + view.diff.get("introduced", []):
            if d["severity"] in ("critical", "major"):
                tag = " (новое)" if d in view.diff.get("introduced", []) else ""
                items.append({"kind": "finding", "text": f"{d['id']} {d['title']}{tag}".strip(), "severity": d["severity"]})
        for d in view.diff.get("unassessed", []):
            items.append({"kind": "review", "text": f"Не удалось сопоставить с прошлой редакцией: {d['id']} {d['title'] or d['reason']}", "severity": d["severity"]})
    else:
        for fv in view.findings:
            if fv.severity in ("critical", "major"):
                items.append({"kind": "finding", "text": f"{fv.id} {fv.title}", "severity": fv.severity})
    for fv in view.findings:
        if fv.status == "needs_review":
            items.append({"kind": "review", "text": f"{fv.id}: опора не подтверждена, проверьте вручную", "severity": fv.severity})
    for q in view.questions:
        if not q.get("decision"):
            items.append({"kind": "question", "text": f"{q['id']}: {q['text']}", "severity": ""})
    if view.incomplete:
        reasons = [*map(str, view.run.get("status_reasons") or [])]
        items.append({"kind": "incomplete", "text": f"Отчёт неполный: режим «{view.mode_label}», статус {view.run.get('status')}" + (f" ({'; '.join(reasons)})" if reasons else ""), "severity": ""})
    return items
