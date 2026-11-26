"""Общие помощники тестов №05: подставной транспорт модели и выборки из результата."""
from __future__ import annotations

import copy
from typing import Any, Callable

from bcc_review.criteria import load_criteria

REQ_CODES = load_criteria().codes("requirement")


class FakeAsk:
    """Подставной ask(stage, payload, schema): отвечает по сценарию и запоминает вызовы."""

    def __init__(self, answer: Callable[[dict], dict] | dict | str | None = None, raises: Exception | None = None):
        self.answer = answer
        self.raises = raises
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, stage: str, payload: dict, schema: dict) -> Any:
        self.calls.append((stage, copy.deepcopy(payload), copy.deepcopy(schema)))
        if self.raises:
            raise self.raises
        if callable(self.answer):
            return self.answer(payload)
        return copy.deepcopy(self.answer)


def blank(criterion: str, status: str, reason: str, **fields: Any) -> dict:
    """Запись ответа модели по строгой схеме: все поля есть, неиспользуемые пусты."""
    rec = {"criterion": criterion, "status": status, "reason": reason, "quote": "", "condition": "", "outcomes": [],
           "impact": "", "fix": "", "question": "", "severity": "none", "kind": "none", "blocks": "none",
           "blocked_decision": "", "scenario": "", "root_cause": ""}
    rec.update(fields)
    return rec


def issue(criterion: str, reason: str, quote: str, **fields: Any) -> dict:
    base = {"kind": "ambiguity", "severity": "major", "blocks": "both", "impact": "Реализации разойдутся.",
            "blocked_decision": "Как реализовать пункт", "condition": reason}
    base.update(fields)
    return blank(criterion, "issue", reason, quote=quote, **base)


def passes(req_id: str, reasons: dict[str, str] | None = None, skip: tuple[str, ...] = ()) -> dict:
    """Содержательный pass по всем кодам (кроме skip)."""
    reasons = reasons or {}
    return {
        "req_id": req_id,
        "checks": [
            blank(code, "pass", reasons.get(code, f"По «{code}»: границы, субъект и наблюдаемый результат пункта заданы явно."))
            for code in REQ_CODES if code not in skip
        ],
    }


def checks_of(result: dict, req_id: str) -> dict[str, dict]:
    return {c["criterion"]: c for c in result["checks"] if c["req_id"] == req_id}


def cands_of(result: dict, req_id: str) -> list[dict]:
    return [c for c in result["candidates"] if req_id in c["req_ids"]]


def wcodes(result: dict) -> list[str]:
    return [w["code"] for w in result["warnings"]]


def doc_from_lines(*lines: str, title: str = "Тест", keep_markup: bool = False) -> dict:
    from tests.p05.docfix import markdown_document

    return markdown_document("\n".join(lines) + "\n", title=title, keep_markup=keep_markup)
