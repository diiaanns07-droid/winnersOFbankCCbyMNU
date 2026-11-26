"""Общие помощники тестов №05: подставной транспорт модели и выборки из результата."""
from __future__ import annotations

import copy
from typing import Any, Callable

from bcc_review.criteria import load_criteria

REQ_CODES = load_criteria().codes("requirement")


class FakeAsk:
    """Подставной ask(stage, payload, schema): отвечает по сценарию и запоминает вызовы."""

    def __init__(self, answer: Callable[[dict], dict] | dict | None = None, raises: Exception | None = None):
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


def passes(req_id: str, reasons: dict[str, str] | None = None, skip: tuple[str, ...] = ()) -> dict:
    """Содержательный pass по всем кодам (кроме skip)."""
    reasons = reasons or {}
    return {
        "req_id": req_id,
        "checks": [
            {"criterion": code, "status": "pass",
             "reason": reasons.get(code, f"По {code}: границы, субъект и наблюдаемый результат пункта заданы явно.")}
            for code in REQ_CODES if code not in skip
        ],
    }


def checks_of(result: dict, req_id: str) -> dict[str, dict]:
    return {c["criterion"]: c for c in result["checks"] if c["req_id"] == req_id}


def cands_of(result: dict, req_id: str) -> list[dict]:
    return [c for c in result["candidates"] if req_id in c["req_ids"]]


def doc_from_lines(*lines: str, title: str = "Тест") -> dict:
    from tests.p05.docfix import markdown_document

    return markdown_document("\n".join(lines) + "\n", title=title)
