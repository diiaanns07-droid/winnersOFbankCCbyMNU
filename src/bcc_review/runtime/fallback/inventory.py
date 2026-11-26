"""Резервная нарезка и реестр требований (пока не влит модуль №04).

Детерминированно: нумерованные пункты, пункты списков, строки многоколоночных таблиц, таблицы
«поле — значение» целиком, короткие разделы из абзацев и кода — одним требованием.
Служебные разделы (ревью, согласующие, оглавление) и заглушки исключаются с причиной.
"""

from __future__ import annotations

import re
from typing import Any, Optional

EXCLUDE_SECTION = re.compile(r"ревью\s+требований|согласующ|лист\s+согласования|история\s+изменени|оглавлени|"
                             r"содержание|approv|revision\s+history|table\s+of\s+contents", re.I)
PLACEHOLDER = re.compile(r"^\s*(заполня\w*|будет\s+уточнено|tbd|todo|—|-|n/?a|нет данных)\b.{0,60}$", re.I)
SOURCE_ID = re.compile(r"^\s*([A-ZА-ЯЁ]{1,6}[-‑–]\d+(?:\.\d+)*|[A-Z]{2,6}\d+(?:\.\d+)*)[.):]?\s")
ORDERED = re.compile(r"^\s*(\d{1,3})[.)]\s")
MODAL = re.compile(r"\b(должн|обязан|необходимо|требуется|shall|must)\w*", re.I)

KIND_RULES = [
    (re.compile(r"нефункцион|non-?functional|производительн|надёжн|надежн", re.I), "nonfunctional"),
    (re.compile(r"функциональн|functional", re.I), "functional"),
    (re.compile(r"данн|data", re.I), "data"),
    (re.compile(r"интеграц|integration", re.I), "integration"),
    (re.compile(r"приемк|приёмк|acceptance", re.I), "acceptance"),
    (re.compile(r"тестирован|testing", re.I), "testing"),
    (re.compile(r"\bui\b|дизайн|экран|интерфейс", re.I), "ui"),
    (re.compile(r"архитектур|sequence|bpmn|схем", re.I), "architecture"),
    (re.compile(r"\bapi\b|rest|параметр|ответ|статус|запрос|request|response", re.I), "api"),
    (re.compile(r"цел[иь]|goal", re.I), "goal"),
    (re.compile(r"общие\s+сведения|general", re.I), "meta"),
]


def _kind(section: list[str]) -> str:
    for title in reversed(section):
        for rx, kind in KIND_RULES:
            if rx.search(title):
                return kind
    return "other"


def _excluded_section(section: list[str]) -> Optional[str]:
    for title in section:
        if EXCLUDE_SECTION.search(title):
            return f"служебный раздел шаблона «{title}»: не требование, проверяется как чек-лист"
    return None


def _ev(block: dict[str, Any]) -> dict[str, Any]:
    return {"block_id": block["id"], "start": 0, "end": len(block["text"]), "quote": block["text"]}


def build_inventory(document: dict[str, Any], ask: Any = None) -> dict[str, Any]:
    blocks = document["blocks"]
    requirements: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    warnings: list[str] = []
    fact_hints: list[dict[str, Any]] = []

    # группировка содержимого по разделу (полный путь заголовков)
    groups: list[tuple[tuple[str, ...], list[dict[str, Any]]]] = []
    first_h2_seen = False
    preamble: list[dict[str, Any]] = []
    for b in blocks:
        if b["kind"] == "heading":
            if int(b.get("loc", {}).get("level") or 1) >= 2:
                first_h2_seen = True
            continue
        if not first_h2_seen and len(b["section"]) <= 1:
            preamble.append(b)
            continue
        key = tuple(b["section"])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(b)
        else:
            groups.append((key, [b]))

    pre_keep = [b for b in preamble if MODAL.search(b["text"])]
    pre_drop = [b for b in preamble if b not in pre_keep]
    if pre_drop:
        excluded.append({"block_ids": [b["id"] for b in pre_drop],
                         "reason": "вводная часть документа без обязательств"})
    if pre_keep:
        groups.insert(0, (tuple(pre_keep[0]["section"]), pre_keep))

    def add(blocks_: list[dict[str, Any]], section: list[str], source_id: Optional[str], kind: str) -> None:
        text = "\n".join(b["text"] for b in blocks_ if b["text"])
        requirements.append({
            "id": f"R-{len(requirements) + 1:02d}", "source_id": source_id, "text": text,
            "block_ids": [b["id"] for b in blocks_], "evidence": [_ev(b) for b in blocks_ if b["text"]],
            "hints": [], "kind": kind, "section": section,
            "review_status": "not_reviewed", "review_reason": "проверка ещё не выполнялась",
        })

    for key, items in groups:
        section = list(key)
        reason = _excluded_section(section)
        if reason:
            excluded.append({"block_ids": [b["id"] for b in items], "reason": reason})
            continue
        leaf = section[-1] if section else ""
        kind = _kind(section)
        content = [b for b in items if b["kind"] != "table_header"]
        placeholders = [b for b in content if b["kind"] in ("paragraph", "list_item") and PLACEHOLDER.match(b["text"])]
        if placeholders:
            excluded.append({"block_ids": [b["id"] for b in placeholders],
                             "reason": "заглушка вместо содержания раздела (замечание выдаётся отдельно)"})
            content = [b for b in content if b not in placeholders]
        if not content:
            continue
        headers = [b for b in items if b["kind"] == "table_header"]
        rows = [b for b in content if b["kind"] == "table_row" and b["text"]]
        empty_rows = [b for b in content if b["kind"] == "table_row" and not b["text"]]
        if empty_rows:
            excluded.append({"block_ids": [b["id"] for b in empty_rows], "reason": "пустая строка таблицы"})
        ncols = max((len(b.get("loc", {}).get("columns") or []) for b in rows), default=0)
        if rows and ncols <= 2:
            # таблица «поле — значение»: одно требование-паспорт, ячейки не дробим
            add(headers + rows, section, f"{leaf}: таблица", kind)
        else:
            for n, r in enumerate(rows, 1):
                add([r], section, f"{leaf}, строка {n}", kind)
        rest = [b for b in content if b["kind"] != "table_row"]
        lists = [b for b in rest if b["kind"] == "list_item"]
        others = [b for b in rest if b["kind"] != "list_item"]
        for b in lists:
            m = SOURCE_ID.match(b["text"])
            mo = ORDERED.match(b["text"])
            sid = m.group(1) if m else (f"{leaf}, п. {mo.group(1)}" if mo else None)
            add([b], section, sid, kind)
        if others:
            total = sum(len(b["text"]) for b in others)
            if total <= 700 or len(others) <= 3:
                m = SOURCE_ID.match(others[0]["text"])
                add(others, section, m.group(1) if m else None, kind)
            else:
                for b in others:
                    m = SOURCE_ID.match(b["text"])
                    add([b], section, m.group(1) if m else None, kind)

    covered = {bid for r in requirements for bid in r["block_ids"]} | {bid for e in excluded for bid in e["block_ids"]}
    unprocessed = [b["id"] for b in blocks if b["kind"] not in ("heading", "table_header") and b["id"] not in covered]
    if unprocessed:
        warnings.append(f"блоки без требования и без причины исключения: {', '.join(unprocessed[:20])}")
    if ask is not None:
        warnings.append("резервная нарезка детерминированная: семантическая нарезка (№04) не подключена")
    return {"requirements": requirements, "fact_hints": fact_hints, "excluded": excluded,
            "unprocessed_block_ids": unprocessed, "warnings": warnings}
