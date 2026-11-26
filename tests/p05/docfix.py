"""Синтетические Document и Requirement по контракту v1 для тестов №05.

Это не парсер №01/№04: он нужен, чтобы тесты №05 шли автономно и одинаково с контрактом.
Document = {id, title, format, blocks, warnings}; Block = {id, kind, section, text, loc}.
Как и читатель контракта, по умолчанию снимает разметку (``**``, маркер списка, внешние ``|``);
``keep_markup=True`` оставляет строку исходника как есть (проверка устойчивости к разметке).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+")
_BULLET = re.compile(r"^\s*[*+-]\s+")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")


def _visible(line: str, kind: str) -> str:
    text = line.strip()
    if kind == "table_row" or kind == "table_header":
        cells = [c.strip() for c in text.strip("|").split("|")]
        text = " | ".join(cells)
    elif kind == "list_item":
        text = _BULLET.sub("", text)
    return text.replace("**", "")


def markdown_document(text: str, title: str | None = None, *, keep_markup: bool = False) -> dict:
    """Markdown → Document: заголовки дают section, строки — блоки b0001… с loc.line_start/line_end."""
    raw = text.encode("utf-8")
    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []
    in_code = False
    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not line.strip() or (not in_code and (_TABLE_SEP.match(line) or line.strip() == "---")):
            continue
        section = [h for _, h in stack]
        bid = f"b{len(blocks) + 1:04d}"
        if not in_code:
            m = _HEADING.match(line)
            if m:
                level = len(m.group(1))
                stack = [(lv, h) for lv, h in stack if lv < level]
                blocks.append({"id": bid, "kind": "heading", "section": [h for _, h in stack],
                               "text": m.group(2), "loc": {"line_start": n, "line_end": n}})
                stack.append((level, m.group(2)))
                continue
        if in_code:
            kind = "code"
        elif line.lstrip().startswith("|"):
            nxt = lines[n] if n < len(lines) else ""
            kind = "table_header" if _TABLE_SEP.match(nxt) else "table_row"
        elif _LIST.match(line):
            kind = "list_item"
        else:
            kind = "paragraph"
        body = line.strip() if keep_markup or kind == "code" else _visible(line, kind)
        blocks.append({"id": bid, "kind": kind, "section": section, "text": body,
                       "loc": {"line_start": n, "line_end": n}})
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": title or next((b["text"] for b in blocks if b["kind"] == "heading"), "Документ"),
        "format": "markdown",
        "blocks": blocks,
        "warnings": [],
    }


def requirement(doc: dict, rid: str, contains: str, source_id: str | None = None, **extra) -> dict:
    """Требование из первого блока (не заголовка), где встречается подстрока ``contains``."""
    for b in doc["blocks"]:
        if b["kind"] not in ("heading", "table_header") and contains in b["text"]:
            req = {
                "id": rid,
                "source_id": source_id,
                "text": b["text"],
                "block_ids": [b["id"]],
                "evidence": [{"block_id": b["id"], "start": 0, "end": len(b["text"]), "quote": b["text"]}],
                "review_status": "reviewed",
                "review_reason": None,
            }
            req.update(extra)
            return req
    raise AssertionError(f"нет блока с текстом {contains!r}")


def block_of(doc: dict, contains: str) -> dict:
    return next(b for b in doc["blocks"] if contains in b["text"])


def load_fixture(name: str, **kw) -> dict:
    return markdown_document((FIXTURES / name).read_text("utf-8"), **kw)


# Нарезка кейса BCC (часть A и B), как её мог бы отдать №04: (req_id, source_id, подстрока блока)
BCC_REQS = [
    ("R01", None, "Дать клиенту возможность узнать"),
    ("R02", None, "Мобильное приложение → сервис настроек"),
    ("R03", None, "Карты → Расходы → Уведомления"),
    ("R04", None, "Проведение покупки → пересчёт"),
    ("R05", "Ф-1", "Ф-1."),
    ("R06", "Ф-2", "Ф-2."),
    ("R07", "Ф-3", "Ф-3."),
    ("R08", "Ф-4", "Ф-4."),
    ("R09", None, "Процессинг → сервис расходов"),
    ("R10", None, "Сервис передаёт push на отправку"),
    ("R11", None, "Хранить идентификатор карты"),
    ("R12", None, "Приложение читает и сохраняет настройки"),
    ("R13", None, "заполняются тестировщиками"),
    ("R14", None, "Расходы 48 500 ₸"),
    ("R15", None, "Покупка 31 января"),
    ("R16", None, "Расходы 19 900 ₸"),
    ("R17", None, "REST type | GET"),
    ("R18", None, "Request URL |"),
    ("R19", None, "Swagger |"),
    ("R20", None, "1. Проверить пользовательскую сессию."),
    ("R21", None, "5. При отклонении суммы"),
    ("R22", None, "1. Целое число тенге"),
    ("R23", None, "`amount` | integer"),
    ("R24", None, "`result` | string"),
    ("R25", None, "Если результат 200 или 201"),
    ("R26", None, "Для чужой карты возвращается 404"),
    ("R27", None, "Требование может быть протестировано |"),
]


def bcc_case(**kw) -> tuple[dict, list[dict]]:
    doc = load_fixture("bcc_case.md", **kw)
    return doc, [requirement(doc, rid, needle, sid) for rid, sid, needle in BCC_REQS]
