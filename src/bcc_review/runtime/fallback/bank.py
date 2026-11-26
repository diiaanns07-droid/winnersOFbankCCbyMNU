"""Резервный чек-лист банка и черновик тест-кейсов (пока не влит модуль №10)."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ...contracts import AskError
from .llm_stages import S, STR, STRS

CHECK_HEADER = re.compile(r"провер", re.I)
MARK = {"yes", "no", "na", "unknown"}

# детерминированная разметка строк чек-листа по виду замечаний (без модели)
KEYWORDS = [
    (re.compile(r"противореч|операционн", re.I), {"conflict", "incorrect"}),
    (re.compile(r"протестирован|тестирован", re.I), {"unverifiable", "ambiguity"}),
    (re.compile(r"модель данных|поток", re.I), {"omission", "incomplete"}),
    (re.compile(r"интеграц", re.I), {"omission", "conflict", "incorrect"}),
    (re.compile(r"версионност", re.I), {"placeholder", "traceability"}),
    (re.compile(r"безопасност", re.I), {"incorrect"}),
]

BANK_SCHEMA = S({
    "rows": {"type": "array", "items": S({
        "row": {"type": "integer"},
        "available": {"type": "string", "enum": sorted(MARK)}, "checked": {"type": "string", "enum": sorted(MARK)},
        "note": STR, "finding_ids": STRS})},
    "test_cases": {"type": "array", "items": S({
        "precondition": STR, "action": STR, "expected": STR, "req_ids": STRS, "open_question": STR})},
})

TASK_BANK = """1. Заполни чек-лист ревью банка (rows): для каждой строки (row — её номер из входа) поставь available и checked: yes — пункт выполнен в документе, no — не выполнен, na — неприменимо, unknown — по тексту нельзя решить. note — конкретное обоснование со ссылкой на место документа или на ID замечаний; finding_ids — ID замечаний из входа, из-за которых пункт не выполнен.
2. Предложи черновик тест-кейсов для раздела тестирования (test_cases): границы значений, переходы периодов, повторы и отмены событий, ошибки API, правила из требований. Формат «Дано / Когда / Тогда» в полях precondition, action, expected; req_ids — проверяемые требования; open_question — если ожидаемый результат зависит от неразрешённого замечания, кратко назови вопрос (иначе пустая строка). Ожидаемый результат выводи только из текста требований; где требования противоречат друг другу, не выбирай сторону, а укажи open_question."""


def find_checklist(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = document["blocks"]
    for i, b in enumerate(blocks):
        cols = b.get("loc", {}).get("columns") or []
        if b["kind"] == "table_header" and len(cols) >= 3 and CHECK_HEADER.search(cols[0]) and any(
                CHECK_HEADER.search(c) for c in cols[1:]):
            for r in blocks[i + 1:]:
                if r["kind"] != "table_row" or r["section"] != b["section"]:
                    break
                if r["text"]:
                    rows.append(r)
    return rows


def _row_text(block: dict[str, Any]) -> str:
    return block["text"].split(" | ")[0].strip()


def build_bank_pack(document: dict[str, Any], requirements: list[dict[str, Any]], findings: list[dict[str, Any]],
                    decisions: list[dict[str, Any]], ask: Optional[Callable] = None) -> dict[str, Any]:
    rows = find_checklist(document)
    checklist = []
    for n, r in enumerate(rows, 1):
        text = _row_text(r)
        checklist.append({"id": f"CL-{n:02d}", "text": text, "available": "unknown", "checked": "unknown",
                          "note": "", "finding_ids": [],
                          "evidence": [{"block_id": r["id"], "start": 0, "end": len(text), "quote": text}]})
    warnings: list[str] = []
    test_cases: list[dict[str, Any]] = []
    confirmed = [f for f in findings if f["status"] == "confirmed"]
    if ask is not None and (checklist or requirements):
        payload = {"task": TASK_BANK, "input": {
            "checklist": [{"row": n, "text": c["text"]} for n, c in enumerate(checklist, 1)],
            "findings": [{"id": f["id"], "severity": f["severity"], "kind": f["kind"], "title": f["title"],
                          "req_ids": f["req_ids"]} for f in findings],
            "requirements": [{"req_id": r["id"], "source_id": r.get("source_id"), "kind": r.get("kind"),
                              "text": r["text"][:400]} for r in requirements]},
            "context": {"mode": "auto", "block_ids": [b for r in requirements for b in r["block_ids"]]}}
        try:
            data = ask("bank", payload, BANK_SCHEMA)
            ids = {f["id"] for f in findings}
            for row in data["rows"]:
                if 1 <= row["row"] <= len(checklist):
                    c = checklist[row["row"] - 1]
                    c.update(available=row["available"], checked=row["checked"], note=row["note"],
                             finding_ids=[x for x in row["finding_ids"] if x in ids])
            known = {r["id"] for r in requirements}
            for n, t in enumerate(data["test_cases"], 1):
                test_cases.append({"id": f"TC-{n:02d}", "precondition": t["precondition"], "action": t["action"],
                                   "expected": t["expected"], "req_ids": [x for x in t["req_ids"] if x in known],
                                   "open_question_id": None, "open_question": t["open_question"] or None})
            return {"checklist": checklist, "test_cases": test_cases, "warnings": warnings}
        except AskError as exc:
            warnings.append(f"bank: {exc.kind}: чек-лист размечен по правилам без модели")
    for c in checklist:
        kinds = set()
        for rx, ks in KEYWORDS:
            if rx.search(c["text"]):
                kinds |= ks
        hits = [f["id"] for f in confirmed if f["kind"] in kinds and f["severity"] in ("critical", "major")]
        if hits:
            c.update(checked="no", finding_ids=hits[:8],
                     note="Не выполнено: подтверждённые замечания " + ", ".join(hits[:8]))
        else:
            c["note"] = "Разметка без модели: подтверждённых замечаний по пункту нет, решение за аналитиком"
    return {"checklist": checklist, "test_cases": test_cases, "warnings": warnings}
