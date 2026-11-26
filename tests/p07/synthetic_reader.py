"""Синтетический reader по контракту v1 — заглушка до вливания штатных reader №01/02/03.

Document = {id, title, format, blocks, warnings}; id — SHA-256 исходных байтов.
Block = {id, kind, section, text, loc}; ID ``b0001``, ``b0002``… в порядке чтения.

* Markdown/TXT: абзац, пункт списка, строка таблицы или код. Маркер списка, ``**`` и `````
  в тексте блока снимаются; ``loc = {line_start, line_end, map}``, где
  ``map = [[text_start, line, col], ...]`` (строки с 1, колонки с 0).
* PDF: абзац страницы (строки, сгруппированные по вертикальному промежутку);
  ``loc = {page, fragments: [{start, end, rect}]}`` — по фрагменту на строку,
  ``rect`` в пунктах от левого верхнего угла.
* DOCX: абзац тела или ячейка таблицы; ``loc = {part, path}``.

Используется только в tests/p07. После вливания №01/02/03 тесты стыка запускаются
со штатным reader (см. HANDOFF.md).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+")
_LIST = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")


def read(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    raw = path.read_bytes()
    suffix = path.suffix.casefold()
    if suffix in {".md", ".markdown", ".txt"}:
        fmt, blocks = ("markdown" if suffix != ".txt" else "text"), _read_md(raw.decode("utf-8"))
    elif suffix == ".pdf":
        fmt, blocks = "pdf", _read_pdf(path)
    elif suffix == ".docx":
        fmt, blocks = "docx", _read_docx(path)
    else:
        raise ValueError(f"формат не поддерживается: {suffix}")
    for n, block in enumerate(blocks, start=1):
        block["id"] = f"b{n:04d}"
    title = next((b["text"] for b in blocks if b["kind"] == "heading"), path.stem)
    return {"id": hashlib.sha256(raw).hexdigest(), "title": title, "format": fmt,
            "blocks": blocks, "warnings": []}


def _block(kind: str, section: list[str], text: str, loc: dict) -> dict[str, Any]:
    return {"id": "", "kind": kind, "section": list(section), "text": text, "loc": loc}


def _visible(line: str, line_no: int, offset: int, col: int) -> tuple[str, list[list[int]]]:
    """Видимый текст строки без ``**`` и ````` и карта разрывов относительно исходника."""
    out: list[str] = []
    entries: list[list[int]] = []
    expect = None
    while col < len(line):
        if line.startswith("**", col):
            col += 2
            continue
        if line[col] == "`":
            col += 1
            continue
        if expect != col:
            entries.append([offset + len(out), line_no, col])
        out.append(line[col])
        col += 1
        expect = col
    return "".join(out), entries


def _read_md(text: str) -> list[dict[str, Any]]:
    lines = text.split("\n")
    blocks: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    buf: list[tuple[int, str, int]] = []  # (номер строки, строка, начальная колонка)
    kind = "paragraph"
    in_code = False
    table_open = False

    def section() -> list[str]:
        return [h for _, h in stack]

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        parts: list[str] = []
        entries: list[list[int]] = []
        offset = 0
        for k, (no, line, col) in enumerate(buf):
            if k:
                parts.append("\n")
                offset += 1
            if kind == "code":
                visible, ent = line[col:], [[offset, no, col]]
            else:
                visible, ent = _visible(line, no, offset, col)
            parts.append(visible)
            entries.extend(ent)
            offset += len(visible)
        blocks.append(_block(kind, section(), "".join(parts),
                             {"line_start": buf[0][0], "line_end": buf[-1][0], "map": entries}))
        buf = []

    for no, line in enumerate(lines, start=1):
        line = line.rstrip("\r")
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            kind = "code"
            continue
        if in_code:
            buf.append((no, line, 0))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group().strip())
            name, _ = _visible(line.rstrip(), no, 0, heading.end())
            stack = [(lv, h) for lv, h in stack if lv < level]  # раздел заголовка — его родители
            kind = "heading"
            buf = [(no, line.rstrip(), heading.end())]
            flush()
            stack.append((level, name))
            continue
        if not line.strip() or line.strip() == "---":
            flush()
            table_open = False
            continue
        if line.lstrip().startswith("|"):
            flush()
            if not _TABLE_SEP.match(line):
                blocks.append(_block("table_row" if table_open else "table_header", section(), line,
                                     {"line_start": no, "line_end": no, "map": [[0, no, 0]]}))
            table_open = True
            continue
        bullet = _LIST.match(line)
        if bullet:
            flush()
            kind = "list_item"
            buf = [(no, line, bullet.end())]
            continue
        if not buf:
            kind = "paragraph"
        buf.append((no, line, 0))
    flush()
    return blocks


def _read_pdf(path: Path) -> list[dict[str, Any]]:
    import pdfplumber

    blocks: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            paragraphs: list[list[dict]] = []
            prev_bottom = None
            for line in page.extract_text_lines(keep_blank_chars=True):
                height = line["bottom"] - line["top"]
                if prev_bottom is None or line["top"] - prev_bottom > 0.8 * height:
                    paragraphs.append([])
                paragraphs[-1].append(line)
                prev_bottom = line["bottom"]
            for para in paragraphs:
                fragments, offset = [], 0
                for k, line in enumerate(para):
                    offset += 1 if k else 0
                    rect = [round(line[key], 2) for key in ("x0", "top", "x1", "bottom")]
                    fragments.append({"start": offset, "end": offset + len(line["text"]), "rect": rect})
                    offset += len(line["text"])
                blocks.append(_block("paragraph", [], "\n".join(line["text"] for line in para),
                                     {"page": page_no, "fragments": fragments}))
    return blocks


def _read_docx(path: Path) -> list[dict[str, Any]]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    blocks: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    p_no = t_no = 0
    part = "word/document.xml"
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p_no += 1
            para = Paragraph(child, document)
            text = para.text
            if not text.strip():
                continue
            style = para.style.name if para.style is not None else ""
            m = re.match(r"Heading (\d)", style)
            if m:
                level = int(m.group(1))
                stack = [(lv, h) for lv, h in stack if lv < level]
            blocks.append(_block("heading" if m else "paragraph", [h for _, h in stack], text,
                                 {"part": part, "path": f"body/p[{p_no}]"}))
            if m:
                stack.append((level, text))
        elif tag == "tbl":
            t_no += 1
            table = Table(child, document)
            for r, row in enumerate(table.rows, start=1):
                for c, cell in enumerate(row.cells, start=1):
                    if cell.text.strip():
                        blocks.append(_block("table_header" if r == 1 else "table_row",
                                             [h for _, h in stack], cell.text,
                                             {"part": part, "path": f"body/tbl[{t_no}]/tr[{r}]/tc[{c}]"}))
    return blocks
