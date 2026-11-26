"""Сборка корректного Report v1 из синтетических фикстур через API p07.

Показывает, как интеграция собирает требования, замечания, свидетелей и факты
из hint/candidate, и даёт эталонную пару отчёт/источник для тестов verify.
Модель не вызывается: кандидаты заданы вручную (подставной семантический этап).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import synthetic_reader
from p07_helpers import block_with

from bcc_review.analysis.evidence import (
    DocumentIndex,
    EvidenceAudit,
    RepairBudget,
    locate,
    resolve_candidate,
    resolve_hint,
)

LOC_KEYS = ("line", "line_end", "page", "page_end", "path")


class Builder:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.doc = synthetic_reader.read(source)
        self.idx = DocumentIndex(self.doc)
        self.budget = RepairBudget(limit=10)
        self.audit = EvidenceAudit(budget=self.budget)

    def bid(self, fragment: str) -> str:
        return block_with(self.doc, fragment)

    def with_loc(self, ev: dict | None) -> dict | None:
        """Опора с вычисленным местом (расширение Evidence: ключ ``loc``)."""
        if ev is None:
            return None
        loc = locate(self.doc, ev, index=self.idx)
        return {**ev, "loc": {k: loc[k] for k in LOC_KEYS if k in loc}}

    def ev(self, fragment: str, quote: str, **context: str) -> dict:
        res = resolve_hint(self.doc, {"block_id": self.bid(fragment), "quote": quote, **context},
                           index=self.idx, budget=self.budget, audit=self.audit)
        assert res["status"] == "matched", res
        return res["evidence"]

    def requirement(self, rid: str, source_id: str | None, fragment: str, quote: str) -> dict:
        ev = self.ev(fragment, quote)
        return {"id": rid, "source_id": source_id, "text": quote, "block_ids": [ev["block_id"]],
                "evidence": [ev], "kind": "functional", "section": self.idx.section(ev["block_id"]),
                "review_status": "reviewed", "review_reason": None}

    def finding(self, fid: str, cand: dict, requirements: list[dict]) -> dict:
        res = resolve_candidate(self.doc, cand, index=self.idx, budget=self.budget,
                                audit=self.audit, requirements=requirements)
        supported = res["anchor_status"] == "supported"
        out = {k: cand.get(k) for k in ("scope", "kind", "criterion", "severity", "title", "impact", "req_ids")}
        witness = res["witness"]
        if witness is not None:
            witness = {**witness, "evidence_a": self.with_loc(witness["evidence_a"]),
                       "evidence_b": self.with_loc(witness["evidence_b"])}
        out.update({
            "id": fid,
            "hints": cand["hints"],
            "evidence": [self.with_loc(e) for e in res["evidence"]],
            "status": "confirmed" if supported else "needs_review",
            "anchor_status": res["anchor_status"],
            "meaning_status": "unchecked",
            "blocked_decision": cand.get("blocked_decision", ""),
            "blocks": ["development", "testing"] if cand["severity"] == "critical" else [],
            "witness": witness,
            "notes": res["warnings"],
        })
        if "inspected_block_ids" in res:
            out["inspected_block_ids"] = res["inspected_block_ids"]
        return out

    def report(self, requirements: list[dict], findings: list[dict], facts: list[dict],
               extra: dict[str, Any] | None = None) -> dict:
        critical = [f["id"] for f in findings if f["status"] == "confirmed" and f["severity"] == "critical"]
        checks = [{"req_id": r["id"], "criterion": "verifiable", "status": "pass",
                   "reason": "Исход наблюдаем.", "finding_ids": []} for r in requirements]
        readiness = {"status": "not_ready" if critical else "ready",
                     "reasons": ["Есть подтверждённые критичные замечания"] if critical else [],
                     "finding_ids": critical}
        report = {
            "schema_version": "1.0",
            "run": {
                "run_id": "p07-fixture", "parent_run_id": None,
                "source_sha256": self.doc["id"], "source_name": self.source.name,
                "agent_version": "0.1.0", "agent_commit": None,
                "provider": "mock", "model": "mock", "requested_model": "mock", "models_seen": ["mock"],
                "mode": "mock", "status": "complete", "status_reasons": [],
                "started_at": "2026-11-26T12:00:00Z", "finished_at": "2026-11-26T12:00:01Z", "duration_s": 1.0,
                "calls": {"physical": 0, "cache_hits": 0, "failed": 0, "retries": 0},
                "tokens": {"input": 0, "output": 0, "cache_read": 0},
                "stages": [], "incomplete_stages": [], "modules": {"evidence": "p07"},
                "evidence_audit": self.audit.to_dict(), "options": {},
            },
            "document": {k: copy.deepcopy(self.doc[k]) for k in ("id", "title", "format", "blocks", "warnings")},
            "requirements": requirements,
            "checks": checks,
            "findings": findings,
            "facts": facts,
            "coverage": [],
            "questions": [{"id": "Q-1", "finding_ids": critical, "prompt": "Как разрешить противоречие?",
                           "options": ["Вариант A", "Вариант B"],
                           "affected_req_ids": [requirements[0]["id"]]}] if critical else [],
            "checklist": [],
            "test_cases": [{"id": "TC-1", "precondition": "Порог задан", "action": "Провести покупку",
                            "expected": "Push отправлен", "req_ids": [requirements[0]["id"]],
                            "open_question_id": "Q-1" if critical else None}],
            "decisions": [],
            "diff": None,
            "verdict": {"development": readiness, "testing": copy.deepcopy(readiness),
                        "first_actions": [{"order": 1, "action": "Устранить критичные замечания",
                                           "finding_ids": critical}] if critical else [],
                        "basis": "Подтверждённое критичное замечание блокирует готовность."},
            "summary": {
                "requirements": len(requirements),
                "reviewed_requirements": sum(r["review_status"] == "reviewed" for r in requirements),
                "findings": len(findings),
                "by_severity": {s: sum(f["severity"] == s for f in findings) for s in ("critical", "major", "minor")},
                "by_status": {s: sum(f["status"] == s for f in findings) for s in ("confirmed", "needs_review")},
                "critical_ids": critical,
                "checks": {"pass": len(checks), "issue": 0, "unknown": 0, "na": 0},
            },
            "warnings": [],
            "excluded": [],
            "rejected": [],
        }
        report.update(extra or {})
        return report


def build_case_md(source: Path) -> dict:
    b = Builder(source)
    reqs = [
        b.requirement("R-1", "Ф-1", "Ф-1.", "Держатель задаёт порог от 1 000 до 1 000 000 ₸ включительно."),
        b.requirement("R-3", "Ф-3", "Ф-3.", "На карту приходится максимум один push за календарный месяц."),
        b.requirement("R-4", "Ф-4", "Ф-4.", "следующее достижение вызывает push независимо от истории"),
        b.requirement("R-5", None, "читает и сохраняет", "Приложение читает и сохраняет настройки через REST API."),
    ]
    witness = {"input": "push в этом месяце уже был, порог изменён, сумма снова достигла порога",
               "outcome_a": "push не отправляется", "outcome_b": "push отправляется",
               "hint_a": {"block_id": b.bid("Ф-3."), "quote": "максимум один push за календарный месяц"},
               "hint_b": {"block_id": b.bid("Ф-4."), "quote": "вызывает push независимо от истории"}}
    candidates: list[dict[str, Any]] = [
        {"scope": "set", "kind": "conflict", "criterion": "set_consistent", "severity": "critical",
         "title": "Ф-3 противоречит Ф-4", "impact": "Нельзя реализовать оба правила", "req_ids": ["R-3", "R-4"],
         "blocked_decision": "Отправлять ли второй push после смены порога", "hints": [], "witness": witness},
        {"scope": "set", "kind": "omission", "criterion": "set_complete", "severity": "major",
         "title": "Нет метода чтения настроек", "impact": "Экран не покажет порог", "req_ids": ["R-5"],
         "hints": [{"block_id": b.bid("читает и сохраняет"), "quote": "читает и сохраняет настройки"}],
         "inspected_block_ids": [b.bid("Метод"), b.bid("GET")], "absent_terms": ["getLimit"]},
        {"scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "minor",
         "title": "Не сказано, за что берётся комиссия", "impact": "", "req_ids": ["R-1"],
         "hints": [{"block_id": b.bid("более 100"), "quote": "Комиссия составляет более 100 ₸ за операцию"}]},
        {"scope": "requirement", "kind": "ambiguity", "criterion": "verifiable", "severity": "major",
         "title": "Цитата модели с неверной суммой", "impact": "", "req_ids": ["R-1"],
         "hints": [{"block_id": b.bid("SMS"), "quote": "не более 100 ₸"}]},
        {"scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "minor",
         "title": "Повтор фразы", "impact": "", "req_ids": ["R-3"],
         "hints": [{"block_id": b.bid("Сумма в push"), "quote": "Клиент получает push",
                    "context": "не более 10 ₸. Клиент получает push."}]},
    ]
    findings = [b.finding(f"D-{n}", cand, reqs) for n, cand in enumerate(candidates, start=1)]
    facts = [
        {"id": "FACT-1", "subject": "порог", "field": "максимум", "value": 1000000, "unit": "₸",
         "req_ids": ["R-1"], "evidence": [b.ev("Ф-1.", "1 000 000 ₸")]},
        {"id": "FACT-2", "subject": "комиссия за SMS", "field": "максимум", "value": "10", "unit": "₸",
         "req_ids": [], "evidence": [b.ev("SMS", "не более 10 ₸")]},
    ]
    sms = b.ev("SMS", "не более 10 ₸")
    decision = {"question_id": "Q-1", "source_sha256": b.doc["id"], "answer": "Вариант A",
                "edits": [{"block_id": sms["block_id"], "start": sms["start"], "end": sms["end"],
                           "old": sms["quote"], "new": "не более 15 ₸"}], "note": ""}
    return b.report(reqs, findings, facts, {"decisions": [decision]})


def build_simple(source: Path, fragment: str, quote: str) -> dict:
    """Минимальный отчёт для PDF/DOCX: одно требование и одно подтверждённое замечание."""
    b = Builder(source)
    req = b.requirement("R-1", None, fragment, quote)
    cand = {"scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "minor",
            "title": "Пример", "impact": "", "req_ids": ["R-1"],
            "hints": [{"block_id": b.bid(fragment), "quote": quote}]}
    return b.report([req], [b.finding("D-1", cand, [req])], [])
