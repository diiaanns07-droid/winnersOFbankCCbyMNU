"""Случай «лимит одной операции» для тестов №10: граница «до N ₸» без указания включённости.

Цепочка: пункт Л-1 → замечание-неоднозначность на цитате «до 500 000 ₸» → вопрос владельцу от настоящего
модуля №08 (``build_questions`` без модели) → решение владельца (Decision контракта v1) → строка
«Требование может быть протестировано» банковского чек-листа → три граничных сценария.

Контроль — тот же документ с уже включительной границей («… включительно»): замечания нет.
"""

from __future__ import annotations

from typing import Any

from bcc_review.bank import build_bank_pack

from . import fixture as fx

LIMIT_MD = fx.FIX / "operation_limit.md"
MOCK = fx.FIX / "mock_operation_limit.json"
MOCK_REVISED = fx.FIX / "mock_operation_limit.revised.json"

AMBIGUOUS = "— до 500 000 ₸."
L1 = "Сумма одной операции перевода {bound} Сумма задаётся целым числом тенге."
L2 = "Перевод сверх лимита отклоняется с сообщением «Превышен лимит операции»."

# Порог лимита и шаг — в тенге: «целым числом тенге» → шаг 1 ₸.
UNIT, STEP, LIMIT = "₸", 1, 500_000
POINTS = {"hi-1": LIMIT - STEP, "hi": LIMIT, "hi+1": LIMIT + STEP}

INCLUSIVE_WORDING = "Сумма одной операции перевода — до 500 000 ₸ включительно."
EXCLUSIVE_WORDING = "Сумма одной операции перевода — меньше 500 000 ₸."


def text(bound: str = AMBIGUOUS) -> str:
    raw = LIMIT_MD.read_text("utf-8")
    assert AMBIGUOUS in raw
    return raw.replace(AMBIGUOUS, bound)


def document(bound: str = AMBIGUOUS) -> dict:
    return fx.read_real(text(bound))


def requirements(doc: dict, bound: str = AMBIGUOUS) -> list[dict]:
    out = []
    for rid, src, body in (("R-01", "Л-1", L1.format(bound=bound.lstrip())), ("R-02", "Л-2", L2)):
        e = fx.ev(doc, body)
        out.append({"id": rid, "source_id": src, "text": body, "block_ids": [e["block_id"]], "evidence": [e],
                    "review_status": "reviewed", "review_reason": None})
    return out


def finding(doc: dict) -> dict:
    """Finding контракта v1, как его даёт проверка требования: неоднозначность на цитате границы."""
    return {"id": "F-LIM", "scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "major",
            "title": "Не указано, входит ли 500 000 ₸ в лимит одной операции",
            "impact": "перевод ровно на лимит разработка может провести, а тестирование — ожидать отказа",
            "req_ids": ["R-01"], "hints": [], "evidence": [fx.ev(doc, "до 500 000 ₸")], "status": "confirmed",
            "anchor_status": "supported", "meaning_status": "confirmed", "blocks": ["development", "testing"],
            "witness": None, "blocked_decision": "проводить ли перевод на сумму, равную лимиту"}


def questions(doc: dict, findings: list[dict]) -> list[dict]:
    """Вопросы владельцу от модуля №08 (без модели — варианты правил) в форме Report.questions."""
    from bcc_review.decisions.clarify import build_questions

    qs = [q.to_dict() for q in build_questions(doc, findings, None)]
    for i, q in enumerate(qs, 1):
        q["id"] = q["id"] or f"Q-{i:02d}"  # id вопросам присваивает движок по порядку важности
    return qs


def decision(doc: dict, qid: str, answer: str, note: str = "", edits: list | None = None) -> dict:
    return {"question_id": qid, "source_sha256": doc["id"], "answer": answer, "edits": list(edits or []), "note": note}


def pack(doc: dict, reqs: list[dict], findings: list[dict], decisions: list[dict], qs: list[dict] | None,
         **kw: Any) -> dict:
    kw.setdefault("complete", True)
    return build_bank_pack(doc, reqs, findings, decisions, None, questions=qs, criteria=fx.CRITERIA, **kw)


def boundary(p: dict) -> dict[str, dict]:
    return {t["values"]["boundary"]: t for t in p["test_cases"] if t["kind"] == "boundary"}


def testability(p: dict) -> dict:
    return next(r for r in p["checklist"] if r["topic"] == "testability")
