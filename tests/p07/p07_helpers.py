"""Помощники тестов p07 (импортируются тестами напрямую)."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NB = "\u00a0"


def make_doc(*texts: str, fmt: str = "txt", ids: list[str] | None = None) -> dict:
    """Документ в памяти: по блоку на строку аргумента."""
    ids = ids or [f"b{i}" for i in range(1, len(texts) + 1)]
    blocks = [{"id": bid, "kind": "paragraph", "section": ["Раздел"], "text": text,
               "loc": {"line_start": i}} for i, (bid, text) in enumerate(zip(ids, texts, strict=True), start=1)]
    return {"id": "0" * 64, "title": "t", "format": fmt, "blocks": blocks, "warnings": []}


def block_with(doc: dict, fragment: str) -> str:
    """ID единственного блока, текст которого содержит ``fragment``."""
    found = [b["id"] for b in doc["blocks"] if fragment in b["text"]]
    assert len(found) == 1, (fragment, found)
    return found[0]
