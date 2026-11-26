"""Загрузка документа для правил: docview №03, а пока его нет — простой запасной читатель.

Запасной читатель повторяет договорённость CONTRACT 2.1 для MD/TXT: строка view = строка файла,
без markdown-разметки, ячейки таблицы через « | », разделители таблиц — пустые строки,
раздел — путь заголовков через « › ». PDF и DOCX читает читатель v1 (`bcc_review.engine`).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ._text import MD_DECOR


def load(path: str | Path) -> dict:
    try:  # основной путь — docview №03
        from bcc_review.v2 import docview  # type: ignore

        return docview.load(str(path))
    except Exception:  # noqa: BLE001 — docview ещё нет или он упал: правила не должны падать
        return fallback_load(path)


def _clean_md(s: str) -> str:
    t = MD_DECOR.sub("", s).rstrip()
    t = re.sub(r"^\s*[*-]\s+", "", t)
    t = re.sub(r"^#+\s*", "", t)
    if t.strip().startswith("|") and t.strip().endswith("|"):
        cells = [c.strip() for c in t.strip().strip("|").split("|")]
        t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
    return t


def fallback_load(path: str | Path) -> dict:
    p = Path(path)
    data = p.read_bytes()
    fmt = p.suffix.lower().lstrip(".") or "txt"
    lines: list[dict] = []
    if fmt in ("md", "markdown", "txt"):
        stack: list[tuple[int, str]] = []
        in_fence = False
        for i, s in enumerate(data.decode("utf-8-sig").splitlines(), 1):
            if s.strip().startswith("```"):
                in_fence = not in_fence
            m = None if in_fence else re.match(r"^(#{1,6})\s+(.*)$", s)
            if m:
                level = len(m.group(1))
                title = MD_DECOR.sub("", m.group(2)).strip()
                stack = [x for x in stack if x[0] < level] + [(level, title)]
            section = " › ".join(t for lv, t in stack if lv > 1) or (stack[0][1] if stack else "")
            text = s if in_fence or s.strip().startswith("```") else _clean_md(s)
            if s.strip().startswith("```"):
                text = MD_DECOR.sub("", s).strip()
            lines.append({"n": i, "text": text, "page": None, "section": section, "src_line": i,
                          "block_id": ""})
        fmt = "md" if fmt == "markdown" else fmt
    else:
        from bcc_review.engine import read_document  # читатели v1: PDF, DOCX

        doc = read_document(str(p))
        for b in doc["blocks"]:
            page = (b.get("loc") or {}).get("page")
            for part in str(b.get("text", "")).splitlines() or [""]:
                lines.append({"n": len(lines) + 1, "text": part, "page": page, "section": "",
                              "src_line": None, "block_id": str(b.get("id", ""))})
    title = next((x["text"] for x in lines if x["text"].strip()), p.name)
    return {"title": title, "file": p.name, "format": fmt, "sha256": hashlib.sha256(data).hexdigest(),
            "lines": lines, "pages": None, "warnings": []}
