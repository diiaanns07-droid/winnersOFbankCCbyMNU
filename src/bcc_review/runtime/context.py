"""Что видит модель: текст документа с метками блоков и политика контекста.

Малый документ (≤ ``full_context_chars``) уходит целиком: части A и B видны вместе в каждом запросе,
поэтому межсекционные противоречия ловятся без индекса. Большой документ: индекс всех требований,
запрошенные блоки и блоки, связанные с ними межсекционными ссылками (общие идентификаторы,
имена в «кавычках», `код`, пути API, коды статусов).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

_ID_RE = re.compile(
    r"«[^»]{3,80}»"                                  # имена в ёлочках
    r"|\b[A-ZА-ЯЁ]{1,6}-\d+(?:\.\d+)*\b"             # Ф-1, НФТ-2, REQ-12
    r"|/[A-Za-z][\w/{}-]{2,}"                       # пути API
    r"|\b[a-z]+[A-Z]\w*\b"                           # camelCase поля
    r"|\b[a-z]+_[a-z_]+\b"                           # snake_case поля БД
    r"|\b[1-5]\d\d\b"                                # коды статусов
)


def render_block(b: dict[str, Any]) -> str:
    kind, text, bid = b["kind"], b["text"], b["id"]
    if kind == "heading":
        level = int(b.get("loc", {}).get("level") or 2)
        return f"[{bid}] {'#' * level} {text}"
    if kind == "table_header":
        return f"[{bid}] (заголовок таблицы) | {text} |"
    if kind == "table_row":
        return f"[{bid}] | {text} |" if text else f"[{bid}] | (пустая строка таблицы) |"
    if kind == "list_item":
        return f"[{bid}] • {text}"
    if kind == "code":
        return f"[{bid}] ```\n{text}\n```"
    if kind == "quote":
        return f"[{bid}] > {text}"
    return f"[{bid}] {text}"


def render_document(document: dict[str, Any], block_ids: Optional[Iterable[str]] = None) -> str:
    wanted = set(block_ids) if block_ids is not None else None
    out = []
    for b in document["blocks"]:
        if wanted is None or b["id"] in wanted:
            out.append(render_block(b))
    return "\n".join(out)


def identifiers(text: str) -> set[str]:
    return {m.group(0).strip("«»").lower() for m in _ID_RE.finditer(text)}


class ContextBuilder:
    def __init__(self, document: dict[str, Any], requirements: Optional[list[dict[str, Any]]] = None,
                 full_context_chars: int = 120_000):
        self.document = document
        self.requirements = requirements or []
        self.full_text = render_document(document)
        self.small = len(self.full_text) <= full_context_chars
        self.policy = "full" if self.small else "index+linked"
        self._ids_by_block = {b["id"]: identifiers(b["text"]) for b in document["blocks"]}
        self._order = {b["id"]: i for i, b in enumerate(document["blocks"])}

    def set_requirements(self, requirements: list[dict[str, Any]]) -> None:
        self.requirements = requirements

    def linked_blocks(self, block_ids: Iterable[str], depth: int = 1) -> set[str]:
        """Блоки, связанные межсекционными ссылками (общие идентификаторы), плюс заголовки их разделов."""
        selected = set(block_ids)
        frontier = set(selected)
        for _ in range(depth):
            ids: set[str] = set()
            for bid in frontier:
                ids |= self._ids_by_block.get(bid, set())
            if not ids:
                break
            new = {bid for bid, own in self._ids_by_block.items() if own & ids} - selected
            selected |= new
            frontier = new
        # заголовки разделов выбранных блоков — для понимания места
        heads = set()
        by_id = {b["id"]: b for b in self.document["blocks"]}
        for b in self.document["blocks"]:
            if b["kind"] == "heading":
                for bid in selected:
                    sec = by_id[bid]["section"] if bid in by_id else []
                    if b["text"] in sec:
                        heads.add(b["id"])
        return selected | heads

    def requirement_index(self) -> str:
        lines = ["ИНДЕКС ВСЕХ ТРЕБОВАНИЙ (id | id в документе | вид | блоки | начало текста):"]
        for r in self.requirements:
            text = r["text"].replace("\n", " ")
            lines.append(f"{r['id']} | {r.get('source_id') or '—'} | {r.get('kind', '')} | "
                         f"{','.join(r['block_ids'])} | {text[:160]}")
        return "\n".join(lines)

    def render(self, spec: Optional[dict[str, Any]]) -> tuple[str, str]:
        """Возвращает (текст контекста, описание политики) для ``payload["context"]``."""
        spec = spec or {}
        mode = spec.get("mode", "auto")
        if mode == "none":
            return "", "none"
        if mode == "full" or (mode == "auto" and self.small):
            return ("ДОКУМЕНТ ЦЕЛИКОМ (каждый блок помечен [id]):\n" + self.full_text, "full")
        wanted = spec.get("block_ids") or []
        blocks = self.linked_blocks(wanted) if wanted else set()
        ordered = sorted(blocks, key=lambda x: self._order.get(x, 0))
        text = (self.requirement_index() + "\n\nФРАГМЕНТЫ ДОКУМЕНТА (запрошенные и связанные ссылками блоки):\n"
                + render_document(self.document, ordered))
        return text, "index+linked"
