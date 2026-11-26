"""Синтетический загрузчик Markdown → Document (контракт v1) для тестов №06.

Заменяет загрузчик Max, пока bootstrap ``bcc/integration`` не опубликован.
Document = {id, title, format, blocks, warnings}; Block = {id, kind, section, text, loc};
строки нумеруются с 1, id документа — SHA-256 исходных байтов.

table_mode="row"   — каждая строка таблицы отдельным блоком (kind table_header/table_row);
table_mode="table" — вся таблица одним блоком kind="table" (разделитель сохраняется).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def load_markdown(source, *, table_mode: str = "row", title: str | None = None) -> dict:
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and source.endswith(".md")):
        raw = Path(source).read_bytes()
    else:
        raw = str(source).encode("utf-8")
    text = raw.decode("utf-8")
    lines = text.split("\n")
    blocks: list[dict] = []
    heads: list[tuple[int, str]] = []
    doc_title = title

    def section() -> list[str]:
        return [h for _, h in heads]

    def add(kind: str, start: int, end: int, body: str) -> None:
        blocks.append({
            "id": f"L{start}",
            "kind": kind,
            "section": section(),
            "text": body,
            "loc": {"line_start": start, "line_end": end},
        })

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        ln = i + 1
        if not line.strip() or re.fullmatch(r"\s*-{3,}\s*", line):
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            while heads and heads[-1][0] >= level:
                heads.pop()
            heads.append((level, m.group(2).strip()))
            if doc_title is None and level == 1:
                doc_title = m.group(2).strip()
            add("heading", ln, ln, m.group(2).strip())
            i += 1
            continue
        if line.strip().startswith("```"):
            j = i + 1
            while j < n and not lines[j].strip().startswith("```"):
                j += 1
            body = "\n".join(lines[i + 1:j])
            add("code", ln + 1, j, body)
            i = j + 1
            continue
        if line.lstrip().startswith("|"):
            j = i
            while j < n and lines[j].lstrip().startswith("|"):
                j += 1
            if table_mode == "table":
                add("table", ln, j, "\n".join(lines[i:j]))
            else:
                header_done = False
                for k in range(i, j):
                    if re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", lines[k]) and "-" in lines[k]:
                        header_done = True
                        continue
                    kind = "table_row" if header_done else "table_header"
                    add(kind, k + 1, k + 1, lines[k])
            i = j
            continue
        if re.match(r"^\s*(?:[*\-+]|\d+\.)\s+", line):
            j = i + 1
            while j < n and lines[j].strip() and not re.match(r"^\s*(?:[*\-+]|\d+\.)\s+|^#|^\s*\|", lines[j]):
                j += 1
            body = "\n".join(x.rstrip() for x in lines[i:j])
            add("list_item", ln, j, body)
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip() and not re.match(r"^(#{1,6}\s|```|\s*\||\s*(?:[*\-+]|\d+\.)\s+)", lines[j]):
            j += 1
        body = "\n".join(x.rstrip() for x in lines[i:j])
        add("paragraph", ln, j, body)
        i = j
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": doc_title or "",
        "format": "md",
        "blocks": blocks,
        "warnings": [],
    }
