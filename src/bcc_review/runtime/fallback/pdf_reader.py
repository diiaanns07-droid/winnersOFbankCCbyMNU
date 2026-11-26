"""Резервное чтение PDF (пока не влит модуль №02 ``bcc_review.readers.pdf``).

Выход — ``Document`` контракта v1 той же формы, что у ``text_reader.read_text``.

* Порядок чтения — ``page.get_text("rawdict", sort=True)``; из этой же выборки берутся и текст,
  и координаты, поэтому они не расходятся.
* ``loc = {"page": n, "fragments": [{"start", "end", "rect"}], "bbox": [...]}``; ``page`` с 1.
  Фрагмент — одна строка PDF (в таблице — строка внутри ячейки): ``block.text[start:end]`` —
  её символы, ``rect`` — их общий прямоугольник в пунктах неповёрнутой страницы PyMuPDF.
  Разделители, которые вставляет читатель (``"\\n"`` между строками абзаца, ``" "`` между
  строками заголовка или ячейки, ``" | "`` между ячейками), фрагментами не покрыты.
* Блок не пересекает границу страницы.
* Неполное чтение — предупреждения из ``PARTIAL_READ_CODES`` с номером страницы; страница
  без текста никогда не пропускается молча.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ...contracts import sha256_bytes

__all__ = ["read_pdf"]

Rect = tuple[float, float, float, float]

# Маркеры списка, которые убираются из текста (номера «1.» и «а)» остаются).
_GLYPH_BULLETS = frozenset("•◦▪▫‣⁃●○■□►▸▶➢✓✔·\uf0b7\uf0a7\uf076\uf0d8\uf0fc\uf06c\uf06e\uf075")
_DASH_BULLETS = frozenset("-–—*")
_ORDERED = re.compile(r"^(?:\d{1,2}[.)]|[a-zа-яё]\))\s+\S", re.IGNORECASE)
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_MONO_FONT = re.compile(r"mono|courier|consol|menlo|typewriter|code", re.IGNORECASE)

_SPAN_BOLD = 16          # бит «жирный» в span["flags"]
_SPAN_MONO = 8           # бит «моноширинный»
_HEADING_RATIO = 1.15    # заголовок по размеру: не меньше 115 % основного шрифта ...
_HEADING_DELTA = 1.0     # ... и минимум на 1 pt крупнее
_HEADING_MAX_CHARS = 200
_HEADING_MAX_LINES = 3
_MONO_SHARE = 0.9
_BOLD_SHARE = 0.9
_MARGIN_SHARE = 0.08     # верхнее и нижнее поле страницы — зона колонтитулов
_BAD_SHARE = 0.05        # доля нераспознанных символов, после которой страница читается частично
_BAD_MIN = 3
_SMALL_IMAGE = 0.1       # изображения меньше 10 % площади (логотипы, иконки) не считаются содержанием
_SCAN_IMAGE = 0.8        # изображение на 80 % страницы и больше — скан страницы
_SCAN_MAX_INK = 30       # столько непробельных символов на скане — это номер страницы или штамп, не текст


@dataclass
class _Line:
    block: int                     # номер блока MuPDF на странице
    text: str
    rect: Rect
    size: float = 0.0
    bold: float = 0.0              # доля жирных непробельных символов
    mono: float = 0.0              # доля моноширинных непробельных символов
    bullet: Optional[str] = None   # "glyph" | "ordered"
    bullet_only: bool = False      # строка состоит из одного маркера списка
    furniture: bool = False        # повторяющийся колонтитул
    heading: bool = False
    level: int = 0


@dataclass
class _Cell:
    text: str
    frags: list[tuple[int, int, Rect]]


@dataclass
class _Table:
    bbox: Rect
    rows: list[list[Optional[_Cell]]]
    row_rects: list[Rect]


@dataclass
class _Page:
    number: int
    height: float
    lines: list[_Line] = field(default_factory=list)
    tables: list[_Table] = field(default_factory=list)


# --------------------------------------------------------------------------- геометрия
def _union(rects) -> Optional[Rect]:
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for r in rects:
        x0, y0 = min(x0, r[0]), min(y0, r[1])
        x1, y1 = max(x1, r[2]), max(y1, r[3])
    if x0 == math.inf:
        return None
    return (x0, y0, x1, y1)


def _out(r: Rect) -> list[float]:
    """Округление наружу до 0,01 pt: прямоугольник не теряет края символов."""
    return [math.floor(r[0] * 100) / 100, math.floor(r[1] * 100) / 100,
            math.ceil(r[2] * 100) / 100, math.ceil(r[3] * 100) / 100]


def _center_in(bbox, r) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]


# --------------------------------------------------------------------------- строки
def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[len(s) // 2]


def _bullet_cut(text: str) -> tuple[Optional[str], int]:
    """Вид маркера и сколько символов срезать с начала строки."""
    if not text:
        return None, 0
    c = text[0]
    glyph = c in _GLYPH_BULLETS
    dash = c in _DASH_BULLETS and len(text) > 1 and text[1].isspace()
    if glyph or dash:
        k = 1
        while k < len(text) and text[k].isspace():
            k += 1
        return "glyph", k
    if _ORDERED.match(text):
        return "ordered", 0
    return None, 0


def _make_line(block: int, chars: list[tuple], *, bullets: bool = True) -> Optional[_Line]:
    """Строка из символов ``(c, bbox, size, bold, mono)``: обрезка пробелов, маркер списка, свойства шрифта."""
    ink = [ch for ch in chars if not ch[0].isspace()]
    if not ink:
        return None
    mono = sum(1 for ch in ink if ch[4]) / len(ink)
    i, j = 0, len(chars)
    while j > i and chars[j - 1][0].isspace():
        j -= 1
    if mono < _MONO_SHARE:  # у кода отступ — часть текста
        while i < j and chars[i][0].isspace():
            i += 1
    chars = chars[i:j]
    bullet = None
    if bullets and mono < _MONO_SHARE:
        bullet, cut = _bullet_cut("".join(ch[0] for ch in chars[:40]))
        chars = chars[cut:]
    ink = [ch for ch in chars if not ch[0].isspace()]
    if not ink:
        return _Line(block, "", (0.0, 0.0, 0.0, 0.0), bullet=bullet, bullet_only=True)
    return _Line(
        block=block,
        text="".join(ch[0] for ch in chars),
        rect=_union(ch[1] for ch in ink) or (0.0, 0.0, 0.0, 0.0),
        size=_median([ch[2] for ch in ink]),
        bold=sum(1 for ch in ink if ch[3]) / len(ink),
        mono=mono,
        bullet=bullet,
    )


# --------------------------------------------------------------------------- таблицы
def _table_grids(page) -> list[tuple[Rect, list[list[Optional[Rect]]]]]:
    """Сетки таблиц ``page.find_tables()``: (bbox, строки ячеек). Первая строка — шапка."""
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return []
    try:
        try:
            # Без фильтра по модели разметки (PyMuPDF >= 1.27): быстрее и не теряет таблицы из одной строки.
            found = finder(use_layout=False)
        except TypeError:
            found = finder()
    except Exception:  # noqa: BLE001 - поиск таблиц не должен ронять чтение страницы
        return []
    grids = []
    for t in getattr(found, "tables", []) or []:
        try:
            if t.col_count < 2:
                continue
            # Шапка — всегда первая строка сетки. «Внешнюю» шапку PyMuPDF (текст над таблицей) не берём:
            # так в таблицу попадал заголовок раздела, стоящий прямо над ней.
            rows = [[tuple(c) if c else None for c in r.cells] for r in t.rows]
            if rows:
                grids.append((tuple(t.bbox), rows))
        except Exception:  # noqa: BLE001
            continue
    return grids


def _cell_text(groups: dict[tuple[int, int], list[tuple]]) -> _Cell:
    text = ""
    frags: list[tuple[int, int, Rect]] = []
    for key, chars in groups.items():
        ln = _make_line(key[0], chars, bullets=False)
        if ln is None or not ln.text:
            continue
        if text:
            text += " "
        frags.append((len(text), len(text) + len(ln.text), ln.rect))
        text += ln.text
    return _Cell(text, frags)


# --------------------------------------------------------------------------- проход 1: страница
def _read_page(page, number: int, flags: int, warnings: list[dict[str, Any]]) -> _Page:
    crop = page.cropbox
    out = _Page(number=number, height=float(crop.height) or float(page.rect.height))
    raw = page.get_text("rawdict", sort=True, flags=flags)
    grids = _table_grids(page)
    cells: dict[tuple[int, int, int], dict[tuple[int, int], list[tuple]]] = {}
    total = bad = 0
    for bi, block in enumerate(raw.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        for li, line in enumerate(block.get("lines", [])):
            kept: list[tuple] = []
            for span in line.get("spans", []):
                font = span.get("font", "") or ""
                sflags = int(span.get("flags", 0) or 0)
                bold = bool(sflags & _SPAN_BOLD) or bool(_BOLD_FONT.search(font))
                mono = bool(sflags & _SPAN_MONO) or bool(_MONO_FONT.search(font))
                size = float(span.get("size", 0.0) or 0.0)
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c:
                        continue
                    if not c.isspace():
                        total += 1
                        if c == "\ufffd" or ord(c) < 32:
                            bad += 1
                    item = (c, tuple(ch["bbox"]), size, bold, mono)
                    owner = None
                    for ti, (tb, rows) in enumerate(grids):
                        if not _center_in(item[1], tb):
                            continue
                        for ri, row in enumerate(rows):
                            for ci, rect in enumerate(row):
                                if rect is not None and _center_in(item[1], rect):
                                    owner = (ti, ri, ci)
                                    break
                            if owner:
                                break
                        if owner:
                            break
                    if owner is None:
                        kept.append(item)
                    else:
                        cells.setdefault(owner, {}).setdefault((bi, li), []).append(item)
            ln = _make_line(bi, kept)
            if ln is not None:
                out.lines.append(ln)

    for ti, (tb, rows) in enumerate(grids):
        table_rows: list[list[Optional[_Cell]]] = []
        row_rects: list[Rect] = []
        for ri, row in enumerate(rows):
            table_rows.append([None if rect is None else _cell_text(cells.get((ti, ri, ci), {}))
                               for ci, rect in enumerate(row)])
            row_rects.append(_union(r for r in row if r is not None) or tb)
        if any(c is not None and c.text for row in table_rows for c in row):
            out.tables.append(_Table(tb, table_rows, row_rects))

    ink = sum(len(ln.text) - ln.text.count(" ") for ln in out.lines)
    ink += sum(len(c.text) for t in out.tables for row in t.rows for c in row if c is not None)
    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    try:
        images = page.get_image_info()
    except Exception:  # noqa: BLE001
        images = []
    areas = [_area(im.get("bbox")) for im in images]
    coverage = min(1.0, sum(areas) / page_area)
    big_images = [a for a in areas if _SMALL_IMAGE * page_area <= a < _SCAN_IMAGE * page_area]
    if not ink:
        try:
            drawings = len(page.get_drawings()) if not images else 0
        except Exception:  # noqa: BLE001
            drawings = 0
        if images or drawings:
            what = f"изображения ({len(images)})" if images else f"векторная графика ({drawings} объектов)"
            warnings.append({"code": "ocr_required", "page": number,
                             "message": f"страница {number}: нет текстового слоя, есть {what}; "
                                        f"содержимое не прочитано, нужен OCR"})
        else:
            warnings.append({"code": "empty_page", "page": number,
                             "message": f"страница {number}: пустая, текста и изображений нет"})
    elif ink < _SCAN_MAX_INK and coverage >= 0.5:
        # скан с наложенным номером страницы или штампом: текстовый слой есть, но содержания в нём нет
        warnings.append({"code": "ocr_required", "page": number,
                         "message": f"страница {number}: почти нет текста ({ink} символов), страницу занимает "
                                    f"изображение; содержимое не прочитано, нужен OCR"})
    elif big_images:
        warnings.append({"code": "images_not_read", "page": number,
                         "message": f"страница {number}: изображения ({len(big_images)}) не распознаются, "
                                    f"текст внутри них не прочитан"})
    if total and bad >= _BAD_MIN and bad / total >= _BAD_SHARE:
        warnings.append({"code": "partial_read", "page": number,
                         "message": f"страница {number}: {bad} из {total} символов без соответствия Unicode "
                                    f"(U+FFFD или управляющие); шрифт без ToUnicode, текст прочитан частично"})
    return out


def _area(bbox) -> float:
    if not bbox:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


# --------------------------------------------------------------------------- проход 2: разметка
def _norm_furniture(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text)).strip().lower()


def _mark_furniture(pages: list[_Page]) -> None:
    """Колонтитулы: строка в верхнем/нижнем поле, повторяющаяся (с точностью до цифр) на половине страниц."""
    if len(pages) < 3:
        return

    def in_margin(ln: _Line, p: _Page) -> bool:
        return ln.rect[3] <= p.height * _MARGIN_SHARE or ln.rect[1] >= p.height * (1 - _MARGIN_SHARE)

    seen = Counter()
    for p in pages:
        seen.update({_norm_furniture(ln.text) for ln in p.lines if ln.text and in_margin(ln, p)})
    need = max(3, math.ceil(len(pages) / 2))
    for p in pages:
        for ln in p.lines:
            if ln.text and in_margin(ln, p) and seen[_norm_furniture(ln.text)] >= need:
                ln.furniture = True


def _body_size(pages: list[_Page]) -> float:
    weights: Counter = Counter()
    for p in pages:
        for ln in p.lines:
            if ln.text and not ln.furniture:
                weights[round(ln.size * 2) / 2] += len(ln.text)
    if not weights:
        return 0.0
    half = sum(weights.values()) / 2
    acc = 0
    for size in sorted(weights):
        acc += weights[size]
        if acc >= half:
            return size
    return 0.0


def _mark_headings(pages: list[_Page], body: float) -> None:
    if body <= 0:
        return
    sizes = set()
    for p in pages:
        groups: dict[int, list[_Line]] = {}
        for ln in p.lines:
            if ln.text and not ln.furniture:
                groups.setdefault(ln.block, []).append(ln)
        for group in groups.values():
            plain = all(not ln.bullet and ln.mono < 0.5 for ln in group)
            big = [ln for ln in group
                   if not ln.bullet and ln.mono < 0.5 and len(ln.text) <= _HEADING_MAX_CHARS
                   and ln.size >= body * _HEADING_RATIO and ln.size - body >= _HEADING_DELTA]
            if 0 < len(big) <= _HEADING_MAX_LINES:
                for ln in big:
                    ln.heading = True
            elif (plain and len(group) <= _HEADING_MAX_LINES
                  and sum(len(ln.text) for ln in group) <= _HEADING_MAX_CHARS
                  and all(ln.bold >= _BOLD_SHARE for ln in group)):
                for ln in group:
                    ln.heading = True
        sizes.update(round(ln.size * 2) / 2 for ln in p.lines if ln.heading)
    rank = {s: i + 1 for i, s in enumerate(sorted(sizes, reverse=True))}
    for p in pages:
        for ln in p.lines:
            if ln.heading:
                ln.level = rank[round(ln.size * 2) / 2]


class _Builder:
    """Сборка блоков документа: нумерация, стек разделов, склейка строк с фрагментами."""

    def __init__(self) -> None:
        self.blocks: list[dict[str, Any]] = []
        self.sections: list[tuple[int, str]] = []
        self.title: Optional[str] = None
        self.tables = 0
        self.last_table: Optional[dict[str, Any]] = None  # для продолжения таблицы на следующей странице

    def section(self) -> list[str]:
        return [t for _, t in self.sections]

    def add(self, kind: str, text: str, page: int, frags: list[tuple[int, int, Rect]],
            bbox: Optional[Rect], **extra: Any) -> None:
        loc: dict[str, Any] = {"page": page,
                               "fragments": [{"start": s, "end": e, "rect": _out(r)} for s, e, r in frags]}
        if bbox is not None:
            loc["bbox"] = _out(bbox)
        loc.update(extra)
        self.blocks.append({"id": f"b{len(self.blocks) + 1:04d}", "kind": kind, "section": self.section(),
                            "text": text, "loc": loc})

    def add_lines(self, kind: str, lines: list[_Line], page: int, joiner: str, **extra: Any) -> None:
        text = ""
        frags: list[tuple[int, int, Rect]] = []
        for ln in lines:
            if text:
                text += joiner
            frags.append((len(text), len(text) + len(ln.text), ln.rect))
            text += ln.text
        if not text.strip():
            return
        if kind == "heading":
            level = extra["level"]
            while self.sections and self.sections[-1][0] >= level:
                self.sections.pop()
            self.add(kind, text, page, frags, _union(ln.rect for ln in lines), **extra)
            self.sections.append((level, text.strip()))
            if self.title is None:
                self.title = text.strip()
        else:
            self.add(kind, text, page, frags, _union(ln.rect for ln in lines), **extra)
        if kind != "other":
            self.last_table = None

    def add_table(self, table: _Table, page: int, page_has_content: bool) -> None:
        """Шапка — первая строка сетки. Таблица, которая открывает страницу сразу после таблицы той же
        ширины в конце предыдущей страницы и не повторяет её шапку, считается продолжением:
        её строки — ``table_row`` с прежними ``columns`` и тем же номером ``loc.table``."""
        rows = table.rows
        width = len(rows[0])
        first = _row_text(rows[0])[0]
        prev = self.last_table
        continuation = (prev is not None and prev["page"] == page - 1 and not page_has_content
                        and prev["width"] == width and first != prev["header_text"])
        if continuation:
            number, columns, header_text, row_no = prev["table"], prev["columns"], prev["header_text"], prev["rows"]
            start = 0
        else:
            self.tables += 1
            number, header_text, row_no = self.tables, first, 1
            columns = [c.text if c else "" for c in rows[0]]
            text, frags = _row_text(rows[0])
            self.add("table_header", text, page, frags, table.row_rects[0], columns=columns, table=number, row=0)
            start = 1
        for ri in range(start, len(rows)):
            text, frags = _row_text(rows[ri])
            extra: dict[str, Any] = {"columns": columns, "table": number, "row": row_no}
            if not text:
                extra["empty"] = True
            self.add("table_row", text, page, frags, table.row_rects[ri], **extra)
            row_no += 1
        self.last_table = {"page": page, "width": width, "columns": columns, "header_text": header_text,
                           "table": number, "rows": row_no}


def _row_text(row: list[Optional[_Cell]]) -> tuple[str, list[tuple[int, int, Rect]]]:
    cells = [c for c in row if c is not None]
    if not any(c.text for c in cells):
        return "", []
    text = ""
    frags: list[tuple[int, int, Rect]] = []
    for k, c in enumerate(cells):
        if k:
            text += " | "
        frags.extend((len(text) + s, len(text) + e, r) for s, e, r in c.frags)
        text += c.text
    return text.rstrip(), frags


def _close(prev: _Line, ln: _Line, share: float = 0.8) -> bool:
    """Следующая строка идёт сразу под предыдущей: зазор меньше ``share`` высоты строки."""
    height = max(prev.rect[3] - prev.rect[1], 1.0)
    gap = ln.rect[1] - prev.rect[3]
    return -0.3 * height < gap < share * height


def _build_page(b: _Builder, p: _Page) -> None:
    cur: Optional[dict[str, Any]] = None  # {"kind", "lines", "level"}
    pending_bullet = False
    has_content = False
    tables = sorted(p.tables, key=lambda t: (t.bbox[1], t.bbox[0]))

    def flush() -> None:
        nonlocal cur, has_content
        if cur is None:
            return
        joiner = " " if cur["kind"] == "heading" else "\n"
        extra = {"level": cur["level"]} if cur["kind"] == "heading" else {}
        b.add_lines(cur["kind"], cur["lines"], p.number, joiner, **extra)
        has_content = True
        cur = None

    def start(kind: str, ln: _Line) -> None:
        nonlocal cur
        flush()
        cur = {"kind": kind, "lines": [ln], "level": ln.level, "block": ln.block}

    for ln in p.lines:
        while tables and tables[0].bbox[1] <= ln.rect[1] + 1 and not ln.furniture:
            flush()
            b.add_table(tables.pop(0), p.number, has_content)
            has_content = True
        if ln.furniture:
            flush()
            b.add_lines("other", [ln], p.number, "\n", furniture=True)
            continue
        if ln.bullet_only:
            flush()
            pending_bullet = True
            continue
        if ln.heading:
            if cur and cur["kind"] == "heading" and cur["block"] == ln.block and cur["level"] == ln.level:
                cur["lines"].append(ln)
            else:
                start("heading", ln)
            pending_bullet = False
            continue
        if ln.bullet or pending_bullet:
            start("list_item", ln)
            pending_bullet = False
            continue
        if ln.mono >= _MONO_SHARE:
            if cur and cur["kind"] == "code" and (cur["block"] == ln.block or _close(cur["lines"][-1], ln)):
                cur["lines"].append(ln)
                cur["block"] = ln.block
            else:
                start("code", ln)
            continue
        if cur and cur["kind"] in ("paragraph", "list_item") and cur["block"] == ln.block:
            cur["lines"].append(ln)
        elif (cur and cur["kind"] == "list_item" and ln.rect[0] >= cur["lines"][0].rect[0] - 2
              and _close(cur["lines"][-1], ln, 0.35)):
            cur["lines"].append(ln)  # продолжение пункта списка (выровнено по тексту пункта) в соседнем блоке MuPDF
            cur["block"] = ln.block
        else:
            start("paragraph", ln)
    flush()
    for t in tables:
        b.add_table(t, p.number, has_content)
        has_content = True


# --------------------------------------------------------------------------- точка входа
def read_pdf(path: str | Path) -> dict[str, Any]:
    """Прочитать PDF в ``Document`` контракта v1."""
    try:
        import pymupdf  # noqa: PLC0415 - необязательная зависимость
    except ImportError as exc:
        raise RuntimeError("для чтения PDF нужен пакет pymupdf: pip install pymupdf") from exc

    path = Path(path)
    data = path.read_bytes()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"не удалось открыть PDF «{path.name}»: файл повреждён или это не PDF ({exc})") from exc
    try:
        if doc.needs_pass:
            raise ValueError(f"PDF «{path.name}» защищён паролем; снимите защиту и загрузите файл снова")
        if doc.page_count == 0:
            raise ValueError(f"в PDF «{path.name}» нет ни одной страницы")
        warnings: list[dict[str, Any]] = []
        if getattr(doc, "is_repaired", False):
            warnings.append({"code": "pdf_repaired",
                             "message": "структура PDF была повреждена и восстановлена при открытии"})
        flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
        pages: list[_Page] = []
        for i in range(doc.page_count):
            try:
                pages.append(_read_page(doc[i], i + 1, flags, warnings))
            except Exception as exc:  # noqa: BLE001 - страница не теряется молча
                warnings.append({"code": "unreadable_page", "page": i + 1,
                                 "message": f"страница {i + 1}: не удалось извлечь текст ({type(exc).__name__}: "
                                            f"{str(exc)[:200]})"})
        meta_title = ((doc.metadata or {}).get("title") or "").strip()
    finally:
        doc.close()

    _mark_furniture(pages)
    _mark_headings(pages, _body_size(pages))
    builder = _Builder()
    for p in pages:
        _build_page(builder, p)
    if not builder.blocks:
        warnings.append({"code": "partial_read", "message": "в PDF не найдено ни одного текстового блока"})
    warnings.sort(key=lambda w: w.get("page", 0))
    return {
        "id": sha256_bytes(data),
        "title": meta_title or builder.title or path.stem,
        "format": "pdf",
        "source_name": path.name,
        "blocks": builder.blocks,
        "warnings": warnings,
    }
