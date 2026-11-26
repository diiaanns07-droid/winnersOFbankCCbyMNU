"""Резервное чтение Markdown и TXT (пока не влит модуль №01 ``bcc_review.readers.text``).

Видимый текст блока очищен от разметки (``**``, ``__``, обратные кавычки, маркеры списков, ``|``),
а ``loc.map = [[text_start, line, col], ...]`` обратимо переводит позицию в исходник.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...contracts import sha256_bytes

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)([*+-])\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d{1,3}[.)])\s+(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


class _Seg:
    """Построитель видимого текста с картой позиций в исходник."""

    def __init__(self) -> None:
        self.text = ""
        self.map: list[list[int]] = []
        self._expect: tuple[int, int] | None = None  # (line, col) следующего символа без новой записи

    def add(self, chunk: str, line: int, col: int) -> None:
        if not chunk:
            return
        if self._expect != (line, col):
            self.map.append([len(self.text), line, col])
        self.text += chunk
        self._expect = (line, col + len(chunk))

    def add_synthetic(self, chunk: str) -> None:
        """Разделитель, которого нет в исходнике (перевод строки, « | »): отрезок ``[start, 0, 0]`` — без позиции."""
        if not chunk:
            return
        self.map.append([len(self.text), 0, 0])
        self.text += chunk
        self._expect = None


def _strip_inline(seg: _Seg, s: str, line: int, col0: int) -> None:
    """Убрать ``**``, ``__`` и обратные кавычки; остальное — как есть."""
    i, start = 0, 0
    n = len(s)
    while i < n:
        if s.startswith("**", i) or s.startswith("__", i):
            seg.add(s[start:i], line, col0 + start)
            i += 2
            start = i
        elif s[i] == "`":
            seg.add(s[start:i], line, col0 + start)
            i += 1
            start = i
        elif s[i] == "\\" and i + 1 < n and s[i + 1] in "|*_`\\":
            seg.add(s[start:i], line, col0 + start)
            i += 1
            start = i
            i += 1
        else:
            i += 1
    seg.add(s[start:n], line, col0 + start)


def _split_cells(line: str) -> list[tuple[str, int]]:
    """Ячейки строки таблицы: (сырой текст без крайних пробелов, колонка начала)."""
    cells: list[tuple[str, int]] = []
    s = line.rstrip()
    i = 0
    if s.lstrip().startswith("|"):
        i = s.index("|") + 1
    cur_start = i
    j = i
    while j <= len(s):
        if j == len(s) or (s[j] == "|" and (j == 0 or s[j - 1] != "\\")):
            raw = s[cur_start:j]
            if j == len(s) and not raw.strip() and cells:
                break
            lead = len(raw) - len(raw.lstrip())
            cells.append((raw.strip(), cur_start + lead))
            cur_start = j + 1
        j += 1
    return cells


def _decode(data: bytes) -> tuple[str, list[dict[str, Any]]]:
    """UTF-8; при единичных битых байтах — замена и предупреждение о неполном чтении;
    если файл целиком в cp1251 — чтение как cp1251 с предупреждением."""
    warnings: list[dict[str, Any]] = []
    if data[:3] == bytes((0xEF, 0xBB, 0xBF)):
        data = data[3:]
    try:
        return data.decode("utf-8"), warnings
    except UnicodeDecodeError as exc:
        replaced = data.decode("utf-8", errors="replace")
        bad = replaced.count(chr(0xFFFD))
        if bad > max(8, len(replaced) // 50):
            try:
                text = data.decode("cp1251")
                warnings.append({"code": "encoding_guess", "message": "файл не в UTF-8, прочитан как cp1251"})
                return text, warnings
            except UnicodeDecodeError:
                pass
        warnings.append({"code": "decode_error",
                         "message": f"{bad} байт(а) не декодированы как UTF-8 (первая позиция {exc.start}); "
                                    "заменены символом U+FFFD — документ прочитан не полностью"})
        return replaced, warnings


def parse_markdown(text: str, *, fmt: str = "markdown") -> tuple[list[dict[str, Any]], str | None]:
    lines = text.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    blocks: list[dict[str, Any]] = []
    sections: list[tuple[int, str]] = []  # (уровень, текст)
    title: str | None = None
    para: list[int] = []
    table_header: list[str] | None = None

    def section() -> list[str]:
        return [t for _, t in sections]

    def emit(kind: str, seg: _Seg, l0: int, l1: int, **extra: Any) -> None:
        text_ = seg.text.rstrip()
        if not text_.strip():
            return
        loc: dict[str, Any] = {"line_start": l0, "line_end": l1, "map": seg.map}
        loc.update(extra)
        blocks.append({"id": f"b{len(blocks) + 1:04d}", "kind": kind, "section": section(), "text": text_, "loc": loc})

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        seg = _Seg()
        for k, ln_no in enumerate(para):
            raw = lines[ln_no - 1]
            lead = len(raw) - len(raw.lstrip())
            body = raw.strip()
            if k:
                seg.add_synthetic("\n")
            _strip_inline(seg, body, ln_no, lead)
        emit("paragraph", seg, para[0], para[-1])
        para = []

    i = 0
    n = len(lines)
    while i < n:
        ln_no = i + 1
        raw = lines[i]
        stripped = raw.strip()
        if _FENCE.match(raw):
            flush_para()
            table_header = None
            fence = _FENCE.match(raw).group(1)
            j = i + 1
            seg = _Seg()
            first = True
            while j < n and not lines[j].strip().startswith(fence):
                if not first:
                    seg.add_synthetic("\n")
                seg.add(lines[j], j + 1, 0)
                first = False
                j += 1
            if j > i + 1:
                emit("code", seg, i + 2, j, lang=raw.strip()[3:].strip() or None)
            i = j + 1
            continue
        if not stripped:
            flush_para()
            table_header = None
            i += 1
            continue
        if fmt == "markdown" and _HR.match(raw):
            flush_para()
            table_header = None
            i += 1
            continue
        m = _HEADING.match(raw) if fmt == "markdown" else None
        if m:
            flush_para()
            table_header = None
            level = len(m.group(1))
            seg = _Seg()
            body = m.group(2)
            _strip_inline(seg, body, ln_no, raw.index(body) if body else 0)
            while sections and sections[-1][0] >= level:
                sections.pop()
            emit("heading", seg, ln_no, ln_no, level=level)
            sections.append((level, seg.text.strip()))
            if title is None:
                title = seg.text.strip()
            i += 1
            continue
        if stripped.startswith("|"):
            flush_para()
            if _TABLE_SEP.match(raw):
                i += 1
                continue
            cells = _split_cells(raw)
            seg = _Seg()
            for k, (cell, col) in enumerate(cells):
                if k:
                    seg.add_synthetic(" | ")
                _strip_inline(seg, cell, ln_no, col)
            is_header = (i + 1 < n and _TABLE_SEP.match(lines[i + 1]) is not None)
            if is_header:
                table_header = [_plain(c) for c, _ in cells]
                emit("table_header", seg, ln_no, ln_no, columns=table_header)
            else:
                if seg.text.replace("|", "").strip():
                    emit("table_row", seg, ln_no, ln_no, columns=table_header or [])
                else:
                    blocks.append({"id": f"b{len(blocks) + 1:04d}", "kind": "table_row", "section": section(),
                                   "text": "", "loc": {"line_start": ln_no, "line_end": ln_no, "map": [],
                                                       "columns": table_header or [], "empty": True}})
            i += 1
            continue
        mb = _BULLET.match(raw)
        mo = _ORDERED.match(raw)
        if mb or mo:
            flush_para()
            table_header = None
            seg = _Seg()
            if mb:
                body = mb.group(3)
                col = raw.index(body, len(mb.group(1)) + 1)
            else:
                col = len(mo.group(1))
                _strip_inline(seg, mo.group(2), ln_no, col)
                seg.add(" ", ln_no, col + len(mo.group(2)))
                body = mo.group(3)
                col = raw.index(body, col + len(mo.group(2)))
            _strip_inline(seg, body.rstrip(), ln_no, col)
            j = i + 1
            # продолжение пункта списка: строки с отступом
            while j < n and lines[j].strip() and lines[j].startswith(("  ", "\t")) and not (
                    _BULLET.match(lines[j]) or _ORDERED.match(lines[j])):
                seg.add_synthetic("\n")
                lead = len(lines[j]) - len(lines[j].lstrip())
                _strip_inline(seg, lines[j].strip(), j + 1, lead)
                j += 1
            emit("list_item", seg, ln_no, j)
            i = j
            continue
        if fmt == "markdown" and stripped.startswith(">"):
            flush_para()
            body = stripped[1:].lstrip()
            seg = _Seg()
            _strip_inline(seg, body, ln_no, raw.index(body) if body else 0)
            emit("quote", seg, ln_no, ln_no)
            i += 1
            continue
        table_header = None
        para.append(ln_no)
        i += 1
    flush_para()
    return blocks, title


def _plain(s: str) -> str:
    return s.replace("**", "").replace("__", "").replace("`", "").strip()


def read_text(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    data = path.read_bytes()
    text, warnings = _decode(data)
    fmt = "markdown" if path.suffix.lower() in (".md", ".markdown") else "text"
    blocks, title = parse_markdown(text, fmt=fmt)
    if not blocks:
        warnings.append({"code": "partial_read", "message": "в файле не найдено ни одного текстового блока"})
    return {
        "id": sha256_bytes(data),
        "title": title or path.stem,
        "format": fmt,
        "source_name": path.name,
        "blocks": blocks,
        "warnings": warnings,
    }


def source_position(block: dict[str, Any], offset: int) -> tuple[int, int] | None:
    """Обратное отображение: позиция в ``block.text`` → (строка с 1, колонка с 0) в исходнике."""
    seg = None
    for entry in block.get("loc", {}).get("map", []):
        if entry[0] <= offset:
            seg = entry
        else:
            break
    if seg is None or seg[1] == 0:
        return None
    return seg[1], seg[2] + (offset - seg[0])
