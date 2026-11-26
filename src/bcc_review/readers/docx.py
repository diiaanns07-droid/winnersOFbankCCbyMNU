"""Чтение DOCX в ``Document`` контракта v1 (№03).

Опора для ссылок -- абзац или ячейка таблицы. Номер страницы в Word зависит от
вёрстки, поэтому он идёт только подсказкой ``page_hint``, если Word сохранил
``w:lastRenderedPageBreak``.

Блоки (``kind`` из ``contracts.BLOCK_KINDS``)
------------------------------------------------
* непустой абзац тела: ``heading`` | ``paragraph`` | ``list_item``;
* строка таблицы: ``table_header`` | ``table_row``. Текст строки -- тексты ячеек
  через ``" | "``, абзацы внутри ячейки через ``"\\n"``. Каждая ячейка видна в
  ``loc.cells`` со своим путём, диапазоном в ``block.text`` и заголовком
  столбца. Так одна строка критериев приёмки или параметр API становится одним
  блоком, а комментарий всё равно ставится внутрь выбранной ячейки;
* текст сноски и текстового поля -- отдельный ``paragraph`` сразу после блока,
  где стоит знак сноски или рамка (``loc.anchor`` = ``note`` | ``textbox``).

Абзацы и таблицы идут в реальном порядке ``w:body``, включая элементы управления
содержимым (``w:sdt``). Строки вложенной таблицы идут после строки-родителя.

ID блока -- ``b0001``, ``b0002``… в порядке чтения (правило контракта).
Структурная ссылка на узел -- ``loc.ref``: ``p17`` (17-й ``w:p`` тела, считая
пустые), ``t2.r3`` (таблица 2, строка 3), ячейка ``t2.r3.c1`` (столбец сетки с 1),
вложенная ``t2.r3.c1.t1.r1``, сноска ``fn2``/``en1`` (``w:id``), рамка ``p17.tb1``.

``loc`` (индексы строк, столбцов и абзацев -- с 1; символы -- кодовые точки
Unicode с 0, правая граница не входит)::

    {
      "format": "docx",
      "part": "word/document.xml",                     # часть OOXML
      "anchor": "paragraph" | "row" | "note" | "textbox",
      "ref": "t2.r3",
      "path": "/w:document/w:body/w:tbl[2]/w:tr[3]",   # XPath с 1 к абзацу или строке
      "order": 41, "label": "Таблица 2, строка 3",
      "style": "Heading 2" | null, "heading_level": 2 | null,
      "heading_source": "style" | "outline" | "bold_numbered" | null,
      "list": {"num_id": 3, "level": 0, "label": "1.", "label_source": "computed"} | null,
      "page_hint": 3 | null,
      "paragraphs": [{"path": ".../w:tc[3]/w:p[1]", "start": 40, "end": 75, "cell": 3}],
      "runs": [{"path": ".../w:tc[3]/w:p[1]/w:r[1]", "start": 40, "end": 75,
                "fmt": ["b"], "field": true, "atomic": true, "math": true}],
      "cells": [{"ref": "t2.r3.c3", "col": 3, "col_span": 1, "row_span": 1, "vmerge": null,
                 "merged_into": null, "path": ".../w:tr[3]/w:tc[3]", "start": 40, "end": 75,
                 "column_header": "Ожидаемый результат", "label": "Таблица 2, строка 3, столбец 3 «…»",
                 "column_path": ["Ожидаемый результат"], "header_refs": ["t2.r1.c3"]}],
      "table": {"ref": "t2", "row": 3, "rows": 4, "cols": 3, "header_row": false,
                "header_row_source": "tblHeader" | "first_row" | "merged_cells" | null,
                "header_rows": 1,
                "columns": ["Исходные условия", "Действие", "Ожидаемый результат"],
                "nesting": 1, "parent_ref": null} | null,
      "host": {"block_id": "b0012", "ref": "p12", "path": "..."} | null   # для note/textbox
    }

Шапка таблицы -- строки ``tblHeader``; без них первая строка, а если в ней есть
заголовок группы на несколько столбцов и ячейка, объединённая по вертикали со
строками ниже, -- и эти строки (``header_row_source = "merged_cells"``). Заголовок
столбца собирается из всех строк шапки сверху вниз через ``" / "``:
``"Лимит за сутки / Сумма, ₸"``; ``column_path`` -- те же части списком,
``header_refs`` -- ячейки шапки, из которых они взяты (связь шапка → строка → ячейка).
Ячейка на несколько столбцов подписана «столбцы 2–3».

:func:`locate` переводит ``(block, start, end)`` в самый узкий узел (ячейку или
абзац) с ``ref``, ``path`` и подписью на русском -- для отчётов и веба.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

import docx as _pydocx
from docx.opc.constants import RELATIONSHIP_TYPE as RT

__all__ = [
    "READER_VERSION",
    "MAIN_PART",
    "ROW_SEPARATOR",
    "COLUMN_PATH_SEPARATOR",
    "Block",
    "Document",
    "DocxReadError",
    "read_docx",
    "read_docx_bytes",
    "locate",
]

READER_VERSION = "docx-reader/1"
MAIN_PART = "word/document.xml"
ROW_SEPARATOR = " | "
# Заголовок столбца из нескольких строк шапки: «Лимит за сутки / Сумма, ₸».
COLUMN_PATH_SEPARATOR = " / "

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_W = "{" + W_NS + "}"
_M = "{" + M_NS + "}"
_MC = "{" + MC_NS + "}"

# Дочерние элементы w:r, которые можно разрезать без потери смысла.
SPLITTABLE_RUN_CHILDREN = frozenset(
    {"rPr", "t", "tab", "br", "cr", "noBreakHyphen", "softHyphen", "lastRenderedPageBreak"}
)
# Контейнеры уровня абзаца, текст которых входит в абзац.
_INLINE_CONTAINERS = frozenset(
    {"hyperlink", "smartTag", "customXml", "ins", "moveTo", "fldSimple", "dir", "bdo"}
)
# Контейнеры удалённого текста (рецензирование): текст не входит в текущую версию.
_DELETED_CONTAINERS = frozenset({"del", "moveFrom"})

_HEADING_NAME_RE = re.compile(r"^(?:heading|заголовок)\s*([1-9])$", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,5})\.?\s+\S")


class DocxReadError(ValueError):
    """Файл нельзя прочитать как DOCX. Сообщение -- на русском, для отчёта."""


# --------------------------------------------------------------------------- модель


@dataclass
class Block:
    id: str
    kind: str
    section: list[str]
    text: str
    loc: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "section": list(self.section), "text": self.text, "loc": self.loc}


@dataclass
class Document:
    """Документ контракта v1. ``to_dict()`` проходит ``contracts.validate(..., "Document")``."""

    id: str
    title: str
    format: str
    blocks: list[Block]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "format": self.format,
            "source_name": self.source_name,
            "blocks": [b.to_dict() for b in self.blocks],
            "warnings": [dict(w) for w in self.warnings],
        }

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)

    def by_ref(self, ref: str) -> Block:
        for b in self.blocks:
            if b.loc.get("ref") == ref:
                return b
        raise KeyError(ref)


# ----------------------------------------------------------------------- утилиты XML


def _q(name: str) -> str:
    return _W + name


def _is_w(el: Any) -> bool:
    tag = el.tag
    return isinstance(tag, str) and tag.startswith(_W)


def _local(el: Any) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _ns(el: Any) -> str:
    tag = el.tag
    if not isinstance(tag, str) or not tag.startswith("{"):
        return ""
    return tag[1:].split("}", 1)[0]


def _on(el: Any | None) -> bool:
    """Значение переключателя w:b, w:i и т. п. (отсутствие w:val -- «включено»)."""
    if el is None:
        return False
    val = el.get(_q("val"))
    return val is None or val.lower() not in ("0", "false", "off", "none")


def _val(el: Any | None, default: str | None = None) -> str | None:
    if el is None:
        return default
    return el.get(_q("val"), default)


def _int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _truncate(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _under_fallback(el: Any, stop: Any) -> bool:
    """Лежит ли элемент внутри ``mc:Fallback`` (дубль содержимого ``mc:Choice``)."""
    a = el.getparent()
    while a is not None and a is not stop:
        if a.tag == _MC + "Fallback":
            return True
        a = a.getparent()
    return False


# ------------------------------------------------------------------- сканер абзаца


@dataclass
class RunSpan:
    """Один ``w:r`` (или формула ``m:oMath``) внутри абзаца и его участок текста."""

    el: Any
    rel: str  # путь относительно w:p, например "w:hyperlink[1]/w:r[2]"
    start: int
    end: int
    splittable: bool
    in_field: bool
    fmt: tuple[str, ...]
    kind: str = "run"  # run | math

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class ParagraphScan:
    text: str
    runs: list[RunSpan]
    features: set[str]
    page_breaks: int  # w:lastRenderedPageBreak + w:br type=page
    leading_page_breaks: int = 0  # из них до первого символа абзаца
    notes: list[tuple[str, str]] = field(default_factory=list)  # ("footnote"|"endnote", w:id)
    textboxes: list[Any] = field(default_factory=list)  # w:txbxContent


def _run_fmt(r: Any) -> tuple[str, ...]:
    rpr = r.find(_q("rPr"))
    if rpr is None:
        return ()
    out = []
    if _on(rpr.find(_q("b"))):
        out.append("b")
    if _on(rpr.find(_q("i"))):
        out.append("i")
    u = rpr.find(_q("u"))
    if u is not None and (_val(u) or "single") != "none":
        out.append("u")
    if _on(rpr.find(_q("strike"))) or _on(rpr.find(_q("dstrike"))):
        out.append("s")
    return tuple(out)


class _ParagraphScanner:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.pos = 0
        self.runs: list[RunSpan] = []
        self.fields: list[str] = []  # стек сложных полей: "instr" | "result"
        self.features: set[str] = set()
        self.page_breaks = 0
        self.leading_page_breaks = 0
        self.notes: list[tuple[str, str]] = []
        self.textboxes: list[Any] = []

    def _emit(self, piece: str) -> None:
        if piece:
            self.parts.append(piece)
            self.pos += len(piece)

    def visit(self, el: Any, prefix: str, in_simple_field: bool) -> None:
        counts: dict[str, int] = {}
        for child in el:
            if not isinstance(child.tag, str):
                continue
            ns = _ns(child)
            name = _local(child)
            if ns == M_NS and name in ("oMath", "oMathPara"):
                counts["m:" + name] = counts.get("m:" + name, 0) + 1
                self._math(child, f"{prefix}m:{name}[{counts['m:' + name]}]")
                continue
            if ns != W_NS:
                if ns == MC_NS:
                    self.features.add("alternate_content")
                continue
            counts[name] = counts.get(name, 0) + 1
            rel = f"{prefix}w:{name}[{counts[name]}]"
            if name == "r":
                self._run(child, rel, in_simple_field)
            elif name in _INLINE_CONTAINERS:
                if name in ("ins", "moveTo"):
                    self.features.add("tracked_insert")
                if name == "fldSimple":
                    self.features.add("field")
                self.visit(child, rel + "/", in_simple_field or name == "fldSimple")
            elif name == "sdt":
                content = child.find(_q("sdtContent"))
                if content is not None:
                    self.features.add("content_control")
                    self.visit(content, rel + "/w:sdtContent/", in_simple_field)
            elif name in _DELETED_CONTAINERS:
                self.features.add("tracked_delete")
            # pPr, закладки, маркеры комментариев, proofErr и т. п. текста не дают

    def _math(self, el: Any, rel: str) -> None:
        start = self.pos
        self._emit("".join(t.text or "" for t in el.iter(_M + "t")))
        self.features.add("math")
        self.runs.append(RunSpan(el=el, rel=rel, start=start, end=self.pos, splittable=False,
                                 in_field=False, fmt=(), kind="math"))

    def _run(self, r: Any, rel: str, in_simple_field: bool) -> None:
        start = self.pos
        in_field = in_simple_field or bool(self.fields)
        splittable = True
        for c in r:
            if not isinstance(c.tag, str):
                continue
            if _ns(c) != W_NS:
                splittable = False
                if _ns(c) == MC_NS:
                    self._drawing(c)
                continue
            name = _local(c)
            if name not in SPLITTABLE_RUN_CHILDREN:
                splittable = False
            if name == "fldChar":
                kind = c.get(_q("fldCharType"))
                self.features.add("field")
                if kind == "begin":
                    self.fields.append("instr")
                elif kind == "separate" and self.fields:
                    self.fields[-1] = "result"
                elif kind == "end" and self.fields:
                    self.fields.pop()
                in_field = True
                continue
            if name == "lastRenderedPageBreak" or (name == "br" and c.get(_q("type")) == "page"):
                self.page_breaks += 1
                if self.pos == 0:
                    self.leading_page_breaks += 1
                if name == "lastRenderedPageBreak":
                    continue
            if "instr" in self.fields:
                continue  # код поля не виден читателю
            if self.fields:
                in_field = True
            if name == "t":
                self._emit(c.text or "")
            elif name == "tab":
                self._emit("\t")
            elif name in ("br", "cr"):
                self._emit("\n")
            elif name == "noBreakHyphen":
                self._emit("-")
            elif name == "sym":
                self.features.add("symbol")
            elif name in ("drawing", "pict", "object"):
                self._drawing(c)
            elif name in ("footnoteReference", "endnoteReference"):
                self.notes.append((name[: -len("Reference")], c.get(_q("id")) or ""))
        self.runs.append(RunSpan(el=r, rel=rel, start=start, end=self.pos, splittable=splittable,
                                 in_field=in_field, fmt=_run_fmt(r)))

    def _drawing(self, el: Any) -> None:
        self.features.add("drawing")
        for tb in el.iter(_q("txbxContent")):
            if not _under_fallback(tb, el):
                self.textboxes.append(tb)


def scan_paragraph(p: Any) -> ParagraphScan:
    """Текст абзаца и карта ``w:r`` -> участок текста.

    Правила текста: ``w:t`` как есть, ``w:tab`` -> ``\\t``, ``w:br``/``w:cr`` ->
    ``\\n``, ``w:noBreakHyphen`` -> ``-``, формула OMML -> её ``m:t``. Код сложного
    поля (``w:instrText``) и удалённый при рецензировании текст (``w:del``) не
    входят, результат поля и вставленный текст (``w:ins``) входят. Маркеры
    комментариев и ссылки на них текста не дают, поэтому скан после аннотирования
    даёт тот же текст.
    """
    sc = _ParagraphScanner()
    sc.visit(p, "", False)
    return ParagraphScan(
        text="".join(sc.parts), runs=sc.runs, features=sc.features, page_breaks=sc.page_breaks,
        leading_page_breaks=sc.leading_page_breaks, notes=sc.notes, textboxes=sc.textboxes,
    )


# ----------------------------------------------------------------- стили и списки


class _Styles:
    def __init__(self, doc: Any) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self.default_paragraph: str | None = None
        try:
            root = doc.styles.element
        except Exception:  # pragma: no cover - битая часть стилей
            return
        for s in root.findall(_q("style")):
            sid = s.get(_q("styleId"))
            if not sid:
                continue
            ppr = s.find(_q("pPr"))
            rpr = s.find(_q("rPr"))
            num = None
            outline = None
            if ppr is not None:
                outline = _int(_val(ppr.find(_q("outlineLvl"))))
                numpr = ppr.find(_q("numPr"))
                if numpr is not None:
                    num = (_val(numpr.find(_q("numId"))), _int(_val(numpr.find(_q("ilvl"))), 0))
            self.by_id[sid] = {
                "name": _val(s.find(_q("name")), sid),
                "based_on": _val(s.find(_q("basedOn"))),
                "outline": outline,
                "num": num,
                "bold": _on(rpr.find(_q("b"))) if rpr is not None else False,
            }
            if s.get(_q("type")) == "paragraph" and s.get(_q("default")) in ("1", "true"):
                self.default_paragraph = sid

    def chain(self, sid: str | None) -> Iterator[dict[str, Any]]:
        seen = set()
        while sid and sid in self.by_id and sid not in seen and len(seen) < 16:
            seen.add(sid)
            st = self.by_id[sid]
            yield st
            sid = st["based_on"]

    def name(self, sid: str | None) -> str | None:
        st = self.by_id.get(sid or "")
        if st is None:
            return None
        name = st["name"]
        m = _HEADING_NAME_RE.match(name)
        if m and name.lower().startswith("heading"):
            return f"Heading {m.group(1)}"
        return {"title": "Title", "normal": "Normal"}.get(name.lower(), name)

    def heading_level(self, sid: str | None) -> tuple[int | None, str | None]:
        for st in self.chain(sid):
            name = (st["name"] or "").strip()
            m = _HEADING_NAME_RE.match(name)
            if m:
                return int(m.group(1)), "style"
            if name.lower() == "title":
                return 0, "style"
            if st["outline"] is not None and 0 <= st["outline"] <= 8:
                return st["outline"] + 1, "outline"
        return None, None

    def num(self, sid: str | None) -> tuple[str | None, int] | None:
        for st in self.chain(sid):
            if st["num"] is not None:
                return st["num"]
        return None

    def bold(self, sid: str | None) -> bool:
        return any(st["bold"] for st in self.chain(sid))


_ROMAN = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]
_RU_LETTERS = "абвгдежзиклмнопрстуфхцчшщэюя"


def _fmt_number(n: int, fmt: str) -> str:
    k = max(n, 1)
    if fmt in ("lowerLetter", "upperLetter"):
        s = chr(ord("a") + (k - 1) % 26) * ((k - 1) // 26 + 1)  # a..z, aa..zz, как в Word
        return s.upper() if fmt == "upperLetter" else s
    if fmt in ("lowerRoman", "upperRoman"):
        out = ""
        for v, sym in _ROMAN:
            while k >= v:
                out += sym
                k -= v
        return out.upper() if fmt == "upperRoman" else out
    if fmt in ("russianLower", "russianUpper"):
        s = _RU_LETTERS[(k - 1) % len(_RU_LETTERS)] * ((k - 1) // len(_RU_LETTERS) + 1)
        return s.upper() if fmt == "russianUpper" else s
    if fmt == "decimalZero":
        return f"{n:02d}"
    return str(n)


class _Numbering:
    """Приближённое вычисление меток автонумерации (``1.``, ``2.3``, ``а)``)."""

    def __init__(self, root: Any | None) -> None:
        self.abstract: dict[str, dict[int, dict[str, Any]]] = {}
        self.nums: dict[str, tuple[str, dict[int, int]]] = {}
        self.counters: dict[str, list[int | None]] = {}
        self.seen_nums: set[str] = set()
        if root is None:
            return
        for an in root.findall(_q("abstractNum")):
            aid = an.get(_q("abstractNumId"))
            levels: dict[int, dict[str, Any]] = {}
            for lvl in an.findall(_q("lvl")):
                ilvl = _int(lvl.get(_q("ilvl")), 0) or 0
                levels[ilvl] = {
                    "start": _int(_val(lvl.find(_q("start"))), 1),
                    "fmt": _val(lvl.find(_q("numFmt")), "decimal"),
                    "text": _val(lvl.find(_q("lvlText")), ""),
                }
            if aid is not None:
                self.abstract[aid] = levels
        for num in root.findall(_q("num")):
            nid = num.get(_q("numId"))
            aid = _val(num.find(_q("abstractNumId")))
            overrides: dict[int, int] = {}
            for ov in num.findall(_q("lvlOverride")):
                so = _int(_val(ov.find(_q("startOverride"))))
                if so is not None:
                    overrides[_int(ov.get(_q("ilvl")), 0) or 0] = so
            if nid is not None and aid is not None:
                self.nums[nid] = (aid, overrides)

    def label(self, num_id: str, ilvl: int) -> str | None:
        """Метка очередного пункта. Счётчик общий для всех ``w:num`` одного
        ``w:abstractNum`` (как в Word). ``startOverride`` перезапускает уровень при
        первом абзаце с этим ``w:num``."""
        if num_id not in self.nums:
            return None
        aid, overrides = self.nums[num_id]
        levels = self.abstract.get(aid, {})
        lvl = levels.get(ilvl)
        if lvl is None:
            return None
        counters = self.counters.setdefault(aid, [None] * 9)
        if num_id not in self.seen_nums:
            self.seen_nums.add(num_id)
            for k, v in overrides.items():
                if 0 <= k < 9:
                    counters[k] = v - 1
        counters[ilvl] = lvl["start"] if counters[ilvl] is None else counters[ilvl] + 1
        for deeper in range(ilvl + 1, 9):
            counters[deeper] = None
        if lvl["fmt"] == "bullet":
            return "•"
        if lvl["fmt"] == "none":
            return ""

        def repl(m: re.Match[str]) -> str:
            k = int(m.group(1)) - 1
            lv = levels.get(k, {"start": 1, "fmt": "decimal"})
            value = counters[k] if 0 <= k < 9 and counters[k] is not None else lv["start"]
            return _fmt_number(value, lv["fmt"])

        return re.sub(r"%([1-9])", repl, lvl["text"] or "")


# ------------------------------------------------------------------- обход тела


def _iter_content(container: Any, path: str, names: frozenset[str]) -> Iterator[tuple[str, Any, str]]:
    """Дочерние элементы с именами ``names`` по порядку, сквозь ``w:sdt``/``w:customXml``.

    Возвращает ``(имя, элемент, XPath)``; позиции в XPath считаются по каждому
    имени отдельно и начинаются с 1, как в XPath. Также возвращает
    ``altChunk`` и ``alternate_content``, чтобы вызывающий отметил неполное чтение.
    """
    counts: dict[str, int] = {}
    for child in container:
        if not _is_w(child):
            if _ns(child) == MC_NS:
                yield "alternate_content", child, ""
            continue
        name = _local(child)
        counts[name] = counts.get(name, 0) + 1
        cpath = f"{path}/w:{name}[{counts[name]}]"
        if name in names:
            yield name, child, cpath
        elif name == "sdt":
            content = child.find(_q("sdtContent"))
            if content is not None:
                yield from _iter_content(content, cpath + "/w:sdtContent", names)
        elif name == "customXml":
            yield from _iter_content(child, cpath, names)
        elif name == "altChunk":
            yield "altChunk", child, cpath


_STORY = frozenset({"p", "tbl"})


@dataclass
class ParagraphRef:
    """Абзац блока: живой элемент ``w:p``, его участок в ``block.text`` и ячейка."""

    el: Any
    path: str
    start: int
    end: int
    scan: ParagraphScan
    cell: int | None = None  # индекс в loc.cells (с 0) для строк таблицы


@dataclass
class BlockSpec:
    """Блок вместе с живыми элементами XML (нужен экспорту в Word)."""

    id: str
    kind: str
    section: list[str]
    text: str
    loc: dict[str, Any]
    paragraphs: list[ParagraphRef]
    host: "BlockSpec | None" = None  # для сноски и рамки: блок с её знаком
    host_paragraph: "ParagraphRef | None" = None  # абзац хозяина, где стоит знак или рамка

    def to_block(self) -> Block:
        return Block(id=self.id, kind=self.kind, section=list(self.section), text=self.text, loc=self.loc)


def _loc_paragraphs_and_runs(refs: list[ParagraphRef]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paragraphs, runs = [], []
    for ref in refs:
        entry: dict[str, Any] = {"path": ref.path, "start": ref.start, "end": ref.end}
        if ref.cell is not None:
            entry["cell"] = ref.cell + 1
        paragraphs.append(entry)
        for rs in ref.scan.runs:
            if rs.length <= 0:
                continue
            run: dict[str, Any] = {"path": f"{ref.path}/{rs.rel}", "start": ref.start + rs.start,
                                   "end": ref.start + rs.end}
            if rs.fmt:
                run["fmt"] = list(rs.fmt)
            if rs.in_field:
                run["field"] = True
            if not rs.splittable:
                run["atomic"] = True
            if rs.kind == "math":
                run["math"] = True
            runs.append(run)
    return paragraphs, runs


def _merged_header_depth(rows: list[dict[str, Any]]) -> int:
    """Сколько строк сверху занимает шапка без ``tblHeader`` (не меньше 1).

    Шапка в несколько строк узнаётся по объединению: в первой строке есть
    заголовок группы на несколько столбцов (``gridSpan``, без ``vMerge``) и ячейка,
    объединённая по вертикали (``vMerge restart``) со строками ниже. Тогда строки
    до конца этого объединения -- тоже шапка: в них подписи столбцов группы
    («Лимит за сутки» → «Сумма, ₸» | «Операций»). Хотя бы одна строка остаётся
    строкой данных. Шапка из двух строк без объединения по вертикали неотличима
    от строки данных -- для неё нужна явная пометка ``tblHeader`` в Word.
    """
    if len(rows) < 2:
        return 1
    first = rows[0]["cells"]
    if not any(c["span"] > 1 and c["vmerge"] is None for c in first):
        return 1
    depth = 1
    for c in first:
        if c["vmerge"] != "restart":
            continue
        span = 1
        for nxt in rows[1:]:
            if not any(x["col"] == c["col"] and x["vmerge"] == "continue" for x in nxt["cells"]):
                break
            span += 1
        depth = max(depth, span)
    return depth if depth < len(rows) else 1


class DocxLayout:
    """Обход документа python-docx: блоки, их ``loc`` и предупреждения.

    Один и тот же обход используют ``read_docx`` и экспорт в Word, поэтому ID
    блоков совпадают для одинаковых байтов.
    """

    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self.styles = _Styles(doc)
        self.numbering = _Numbering(self._part_root(RT.NUMBERING))
        self.notes = {"footnote": self._notes(RT.FOOTNOTES, "footnote"),
                      "endnote": self._notes(RT.ENDNOTES, "endnote")}
        self.specs: list[BlockSpec] = []
        self.warnings: list[dict[str, Any]] = []
        self.features: dict[str, int] = {}
        self._section: list[tuple[int, str]] = []
        self._body_p = 0
        self._body_tbl = 0
        self._page = 1
        self._emitted_notes: set[tuple[str, str]] = set()
        body_xml = doc.element.body
        self._track_pages = any(True for _ in body_xml.iter(_q("lastRenderedPageBreak")))
        self._story(body_xml, "/w:document/w:body")
        self._finish_warnings()
        self.by_id = {s.id: s for s in self.specs}

    # -- части пакета без побочных эффектов (python-docx создаёт части при обращении)
    def _related_parts(self, reltype: str) -> list[Any]:
        return [rel.target_part for rel in self.doc.part.rels.values()
                if rel.reltype == reltype and not rel.is_external]

    def _part_root(self, reltype: str) -> Any | None:
        parts = self._related_parts(reltype)
        if not parts:
            return None
        root = getattr(parts[0], "element", None)
        if root is None:
            from lxml import etree

            root = etree.fromstring(parts[0].blob)
        return root

    def _part_name(self, reltype: str) -> str | None:
        parts = self._related_parts(reltype)
        return str(parts[0].partname).lstrip("/") if parts else None

    def _notes(self, reltype: str, tag: str) -> dict[str, tuple[str, Any, str]]:
        root = self._part_root(reltype)
        if root is None:
            return {}
        part = self._part_name(reltype) or f"word/{tag}s.xml"
        out = {}
        for i, note in enumerate(root.findall(_q(tag)), start=1):
            if note.get(_q("type")) not in (None, "normal"):
                continue
            out[note.get(_q("id")) or ""] = (part, note, f"/w:{tag}s/w:{tag}[{i}]")
        return out

    def _count(self, feature: str, n: int = 1) -> None:
        self.features[feature] = self.features.get(feature, 0) + n

    def _section_names(self) -> list[str]:
        return [t for _, t in self._section]

    def _new_spec(self, kind: str, text: str, loc: dict[str, Any], refs: list[ParagraphRef],
                  host: BlockSpec | None = None, section: list[str] | None = None,
                  host_paragraph: ParagraphRef | None = None) -> BlockSpec:
        block_id = f"b{len(self.specs) + 1:04d}"
        loc["order"] = len(self.specs) + 1
        paragraphs, runs = _loc_paragraphs_and_runs(refs)
        loc["paragraphs"] = paragraphs
        loc["runs"] = runs
        spec = BlockSpec(block_id, kind, section if section is not None else self._section_names(),
                         text, loc, refs, host, host_paragraph)
        self.specs.append(spec)
        return spec

    @staticmethod
    def _base_loc(anchor: str, ref: str, path: str, label: str, part: str = MAIN_PART) -> dict[str, Any]:
        return {
            "format": "docx", "part": part, "anchor": anchor, "ref": ref, "path": path, "order": 0,
            "label": label, "style": None, "heading_level": None, "heading_source": None, "list": None,
            "page_hint": None, "paragraphs": [], "runs": [], "cells": [], "table": None, "host": None,
        }

    # -- обход
    def _story(self, container: Any, path: str) -> None:
        for name, el, epath in _iter_content(container, path, _STORY):
            if name == "p":
                self._body_p += 1
                self._body_paragraph(el, epath, f"p{self._body_p}")
            elif name == "tbl":
                self._body_tbl += 1
                self._table(el, epath, f"t{self._body_tbl}", label=f"Таблица {self._body_tbl}", nesting=1)
            else:
                self._count(name)

    def _paragraph_props(self, p: Any) -> dict[str, Any]:
        ppr = p.find(_q("pPr"))
        sid = _val(ppr.find(_q("pStyle"))) if ppr is not None else None
        sid = sid or self.styles.default_paragraph
        level, source = self.styles.heading_level(sid)
        num = None
        if ppr is not None:
            ol = _int(_val(ppr.find(_q("outlineLvl"))))
            if ol is not None:
                level, source = (ol + 1, "outline") if 0 <= ol <= 8 else (None, None)
            numpr = ppr.find(_q("numPr"))
            if numpr is not None:
                num = (_val(numpr.find(_q("numId"))), _int(_val(numpr.find(_q("ilvl"))), 0) or 0)
            if _on(ppr.find(_q("pageBreakBefore"))) and self._track_pages:
                self._page += 1
        if num is None:
            num = self.styles.num(sid)
        lst = None
        if num is not None and num[0] not in (None, "0"):
            label = self.numbering.label(num[0], num[1] or 0)
            lst = {"num_id": _int(num[0], None), "level": num[1] or 0, "label": label, "label_source": "computed"}
        return {"style_id": sid, "style": self.styles.name(sid), "heading_level": level,
                "heading_source": source, "list": lst}

    def _note_features(self, scan: ParagraphScan) -> None:
        for f in scan.features:
            self._count(f)

    def _is_all_bold(self, scan: ParagraphScan, style_id: str | None) -> bool:
        style_bold = self.styles.bold(style_id)
        text_runs = [r for r in scan.runs if r.length > 0 and scan.text[r.start:r.end].strip()]
        return bool(text_runs) and all(style_bold or "b" in r.fmt for r in text_runs)

    def _body_paragraph(self, p: Any, path: str, ref: str) -> None:
        props = self._paragraph_props(p)
        scan = scan_paragraph(p)
        self._note_features(scan)
        page = self._page + (scan.leading_page_breaks if self._track_pages else 0)
        self._page += scan.page_breaks if self._track_pages else 0
        text = scan.text
        if not text.strip():
            return
        level, source = props["heading_level"], props["heading_source"]
        if level is None and props["list"] is None:
            m = _NUMBERED_HEADING_RE.match(text)
            if m and len(text) <= 100 and not text.rstrip().endswith((".", ";", ":")) \
                    and self._is_all_bold(scan, props["style_id"]):
                level, source = m.group(1).count(".") + 1, "bold_numbered"
        if level is not None:
            kind = "heading"
            while self._section and self._section[-1][0] >= level:
                self._section.pop()
            self._section.append((level, " ".join(text.split())))
        elif props["list"] is not None:
            kind = "list_item"
        else:
            kind = "paragraph"
        label = f"Абзац {ref[1:]}"
        if kind == "heading":
            label += " (заголовок)"
        elif kind == "list_item":
            mark = props["list"].get("label")
            label += f" (пункт «{mark}»)" if mark and mark != "•" else " (пункт списка)"
        loc = self._base_loc("paragraph", ref, path, label)
        loc.update(style=props["style"], heading_level=level, heading_source=source, list=props["list"],
                   page_hint=page if self._track_pages else None)
        spec = self._new_spec(kind, text, loc, [ParagraphRef(el=p, path=path, start=0, end=len(text), scan=scan)])
        self._attachments(spec)

    # -- сноски и текстовые поля: отдельные блоки сразу после блока-хозяина
    def _attachments(self, host: BlockSpec) -> None:
        tb_index = 0
        for hp in host.paragraphs:
            scan = hp.scan
            for tb in scan.textboxes:
                tb_index += 1
                i = tb_index
                refs, texts, pos = [], [], 0
                for j, p in enumerate(tb.findall(_q("p")), start=1):
                    sc = scan_paragraph(p)
                    if not sc.text.strip():
                        continue
                    if texts:
                        pos += 1
                    ppath = p.getroottree().getpath(p)
                    refs.append(ParagraphRef(el=p, path=ppath, start=pos, end=pos + len(sc.text), scan=sc))
                    texts.append(sc.text)
                    pos += len(sc.text)
                if tb.find(_q("tbl")) is not None:
                    self._count("textbox_table")
                if refs:
                    ref = f"{host.loc['ref']}.tb{i}"
                    loc = self._base_loc("textbox", ref, tb.getroottree().getpath(tb),
                                         f"{host.loc['label']} → текстовое поле {i}")
                    loc["host"] = {"block_id": host.id, "ref": host.loc["ref"], "path": host.loc["path"]}
                    self._new_spec("paragraph", "\n".join(texts), loc, refs, host=host, section=host.section,
                                   host_paragraph=hp)
            for kind, nid in scan.notes:
                key = (kind, nid)
                if key in self._emitted_notes or nid not in self.notes[kind]:
                    continue
                self._emitted_notes.add(key)
                part, note, npath = self.notes[kind][nid]
                refs, texts, pos = [], [], 0
                for j, p in enumerate(note.findall(_q("p")), start=1):
                    sc = scan_paragraph(p)
                    if not sc.text.strip():
                        continue
                    if texts:
                        pos += 1
                    refs.append(ParagraphRef(el=p, path=f"{npath}/w:p[{j}]", start=pos, end=pos + len(sc.text), scan=sc))
                    texts.append(sc.text)
                    pos += len(sc.text)
                if refs:
                    word = "сноска" if kind == "footnote" else "концевая сноска"
                    ref = f"{'fn' if kind == 'footnote' else 'en'}{nid}"
                    loc = self._base_loc("note", ref, npath, f"{host.loc['label']} → {word} {nid}", part=part)
                    loc["host"] = {"block_id": host.id, "ref": host.loc["ref"], "path": host.loc["path"]}
                    self._new_spec("paragraph", "\n".join(texts), loc, refs, host=host, section=host.section,
                                   host_paragraph=hp)

    # -- таблицы
    def _table(self, tbl: Any, path: str, table_ref: str, label: str, nesting: int,
               parent_ref: str | None = None) -> None:
        self._count("table")
        grid_cols = len(tbl.findall(f"{_q('tblGrid')}/{_q('gridCol')}"))
        rows: list[dict[str, Any]] = []
        for kind, tr, tr_path in _iter_content(tbl, path, frozenset({"tr"})):
            if kind != "tr":
                self._count(kind)
                continue
            trpr = tr.find(_q("trPr"))
            header = trpr is not None and _on(trpr.find(_q("tblHeader")))
            col = 1 + ((_int(_val(trpr.find(_q("gridBefore"))), 0) or 0) if trpr is not None else 0)
            cells = []
            for ckind, tc, tc_path in _iter_content(tr, tr_path, frozenset({"tc"})):
                if ckind != "tc":
                    self._count(ckind)
                    continue
                tcpr = tc.find(_q("tcPr"))
                span = (_int(_val(tcpr.find(_q("gridSpan"))), 1) or 1) if tcpr is not None else 1
                vm_el = tcpr.find(_q("vMerge")) if tcpr is not None else None
                vmerge = None if vm_el is None else ("restart" if _val(vm_el) == "restart" else "continue")
                cells.append({"tc": tc, "path": tc_path, "col": col, "span": span, "vmerge": vmerge})
                col += span
            rows.append({"tr": tr, "path": tr_path, "header": header, "cells": cells})
        n_rows = len(rows)
        n_cols = max([grid_cols] + [c["col"] + c["span"] - 1 for r in rows for c in r["cells"]] or [0])
        explicit = [i for i, r in enumerate(rows) if r["header"]]
        # Строки шапки (индексы с 0): явные tblHeader; без них -- первая строка и строки
        # под объединённым заголовком группы (см. _merged_header_depth).
        if explicit:
            head_rows = explicit
        else:
            head_rows = list(range(_merged_header_depth(rows))) if n_rows > 1 else []

        def plain(tc: Any, tc_path: str) -> str:
            return " ".join(scan_paragraph(p).text.strip()
                            for name, p, _ in _iter_content(tc, tc_path, frozenset({"p"})) if name == "p").strip()

        # Заголовок столбца сетки -- тексты ячеек шапки сверху вниз: объединённая по
        # горизонтали ячейка («Лимит за сутки» на 2 столбца) входит в каждый свой столбец,
        # продолжение вертикального объединения берёт текст начала. Так единица из
        # объединённого заголовка доходит до ячейки данных: «Лимит за сутки / Сумма, ₸».
        col_path: list[list[str]] = [[] for _ in range(n_cols)]
        col_refs: list[list[str]] = [[] for _ in range(n_cols)]
        for hi in head_rows:
            for c in rows[hi]["cells"]:
                if c["vmerge"] == "continue":
                    continue
                t = _truncate(plain(c["tc"], c["path"]), 120)
                if not t:
                    continue
                for g in range(c["col"], min(c["col"] + c["span"], n_cols + 1)):
                    col_refs[g - 1].append(f"{table_ref}.r{hi + 1}.c{c['col']}")
                    if not col_path[g - 1] or col_path[g - 1][-1] != t:
                        col_path[g - 1].append(t)
        columns = [COLUMN_PATH_SEPARATOR.join(p) for p in col_path]

        restart_at: dict[int, str] = {}  # столбец сетки -> ref ячейки, начавшей вертикальное объединение
        for ri, row in enumerate(rows, start=1):
            is_header = (ri - 1) in head_rows
            if row["header"]:
                header_source = "tblHeader"
            elif is_header:
                header_source = "first_row" if ri == 1 else "merged_cells"
            else:
                header_source = None
            row_ref = f"{table_ref}.r{ri}"
            row_label = f"{label}, строка {ri}"
            refs: list[ParagraphRef] = []
            cells_loc: list[dict[str, Any]] = []
            texts: list[str] = []
            nested: list[tuple[Any, str, str, str]] = []
            pos = 0
            row_page: int | None = None
            for ci, cell in enumerate(row["cells"]):
                if ci:
                    pos += len(ROW_SEPARATOR)
                cell_ref = f"{row_ref}.c{cell['col']}"
                row_span = 1
                if cell["vmerge"] == "restart":
                    restart_at[cell["col"]] = cell_ref
                    for nxt in rows[ri:]:
                        if not any(c["col"] == cell["col"] and c["vmerge"] == "continue" for c in nxt["cells"]):
                            break
                        row_span += 1
                elif cell["vmerge"] is None:
                    restart_at.pop(cell["col"], None)
                in_grid = not is_header and cell["col"] <= n_cols
                header_text = columns[cell["col"] - 1] if in_grid else ""
                last_col = cell["col"] + cell["span"] - 1
                cell_label = (f"{label}, строка {ri}, столбец {cell['col']}" if cell["span"] == 1
                              else f"{label}, строка {ri}, столбцы {cell['col']}–{last_col}")
                if header_text:
                    cell_label += f" «{_truncate(header_text, 40)}»"
                start = pos
                parts: list[str] = []
                for name, el, epath in _iter_content(cell["tc"], cell["path"], _STORY):
                    if name == "tbl":
                        nested.append((el, epath, cell_ref, cell_label))
                        continue
                    if name != "p":
                        self._count(name)
                        continue
                    self._paragraph_props(el)  # счётчики нумерации идут по всем абзацам
                    scan = scan_paragraph(el)
                    self._note_features(scan)
                    start_page = self._page + scan.leading_page_breaks
                    self._page += scan.page_breaks if self._track_pages else 0
                    if not scan.text.strip():
                        continue
                    if row_page is None:
                        row_page = start_page
                    if parts:
                        pos += 1  # "\n" между абзацами ячейки
                    refs.append(ParagraphRef(el=el, path=epath, start=pos, end=pos + len(scan.text), scan=scan, cell=ci))
                    parts.append(scan.text)
                    pos += len(scan.text)
                texts.append("\n".join(parts))
                cells_loc.append({
                    "ref": cell_ref, "col": cell["col"], "col_span": cell["span"], "row_span": row_span,
                    "vmerge": cell["vmerge"],
                    "merged_into": restart_at.get(cell["col"]) if cell["vmerge"] == "continue" else None,
                    "path": cell["path"], "start": start, "end": pos,
                    "column_header": header_text or None, "label": cell_label,
                    # связь «шапка → ячейка»: части заголовка и ячейки шапки, из которых он собран
                    "column_path": list(col_path[cell["col"] - 1]) if in_grid else [],
                    "header_refs": list(col_refs[cell["col"] - 1]) if in_grid else [],
                })
            text = ROW_SEPARATOR.join(texts)
            if refs:
                loc = self._base_loc("row", row_ref, row["path"], row_label)
                loc.update(page_hint=row_page if self._track_pages else None, cells=cells_loc, table={
                    "ref": table_ref, "row": ri, "rows": n_rows, "cols": n_cols, "header_row": is_header,
                    "header_row_source": header_source, "header_rows": len(head_rows), "columns": columns,
                    "nesting": nesting, "parent_ref": parent_ref,
                })
                spec = self._new_spec("table_header" if is_header else "table_row", text, loc, refs)
                self._attachments(spec)
            for i, (ntbl, npath, cref, clabel) in enumerate(nested, start=1):
                self._table(ntbl, npath, f"{cref}.t{i}", label=f"{clabel} → вложенная таблица {i}",
                            nesting=nesting + 1, parent_ref=cref)

    # -- предупреждения (контракт: {code, message, stage})
    def _warn(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message, "stage": "read"})

    def _story_text_count(self, reltype: str) -> int:
        n = 0
        for part in self._related_parts(reltype):
            root = getattr(part, "element", None)
            if root is None:
                from lxml import etree

                root = etree.fromstring(part.blob)
            n += sum(1 for p in root.iter(_q("p")) if scan_paragraph(p).text.strip())
        return n

    def _finish_warnings(self) -> None:
        f = self.features
        unread = []
        if f.get("altChunk"):
            unread.append(f"встроенные фрагменты altChunk ({f['altChunk']})")
        if f.get("alternate_content"):
            unread.append(f"блоки mc:AlternateContent вне рисунков ({f['alternate_content']})")
        if f.get("textbox_table"):
            unread.append(f"таблицы внутри текстовых полей ({f['textbox_table']})")
        diagrams = len(self._related_parts(RT.DIAGRAM_DATA))
        if diagrams:
            unread.append(f"схемы SmartArt ({diagrams})")
        if unread:
            self._warn("partial_read", "Часть содержимого DOCX не прочитана: " + "; ".join(unread) + ".")
        hf = self._story_text_count(RT.HEADER) + self._story_text_count(RT.FOOTER)
        if hf:
            self._warn("docx_header_footer", f"В колонтитулах {hf} непустых абзацев; они не входят в блоки, "
                       "Word не даёт комментировать колонтитулы.")
        if f.get("drawing"):
            self._warn("docx_images", f"Рисунки и фигуры ({f['drawing']}): текст их надписей читается, "
                       "содержимое картинок (например, схемы BPMN) не проверяется.")
        if f.get("math"):
            self._warn("docx_math", f"Формулы OMML ({f['math']}) читаются как текст; комментарий к формуле "
                       "ставится на абзац целиком.")
        if f.get("tracked_insert") or f.get("tracked_delete"):
            self._warn("docx_tracked_changes", "В документе есть непринятые исправления: удалённый текст (w:del) "
                       "исключён, вставленный (w:ins) учтён как текущая версия.")
        if f.get("field"):
            self._warn("docx_fields", f"Поля Word в {f['field']} абзацах: в текст входит результат поля; "
                       "комментарий, граница которого попадает в поле, ставится на абзац целиком.")
        comments = self._part_root(RT.COMMENTS)
        if comments is not None:
            n = len(comments.findall(_q("comment")))
            if n:
                self._warn("docx_existing_comments", f"В документе уже {n} комментариев; при аннотировании "
                           "они сохраняются.")


# ------------------------------------------------------------------- ссылки на место


def locate(block: Mapping[str, Any] | Block, start: int, end: int) -> dict[str, Any]:
    """Самый узкий узел DOCX для диапазона ``block.text[start:end]``.

    Возвращает ``{"ref", "path", "part", "label", "anchor", "cell"}``: для строки
    таблицы -- ячейку, если диапазон в одной ячейке, иначе строку; для абзаца --
    абзац. Работает и с ``Block``, и с dict из ``report.json``.
    """
    b = block.to_dict() if isinstance(block, Block) else dict(block)
    loc = b.get("loc") or {}
    out = {"ref": loc.get("ref"), "path": loc.get("path"), "part": loc.get("part", MAIN_PART),
           "label": loc.get("label"), "anchor": loc.get("anchor"), "cell": None}
    cells = [c for c in loc.get("cells") or [] if c["start"] <= start and end <= c["end"]]
    if len(cells) == 1:
        c = cells[0]
        out.update(ref=c["ref"], path=c["path"], label=c["label"], anchor="cell", cell=c)
    return out


# ------------------------------------------------------------------- точка входа


def _check_container(data: bytes, name: str) -> None:
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise DocxReadError(
            f"{name}: это файл формата OLE (старый .doc или DOCX под паролем). "
            "Сохраните документ как .docx без пароля и запустите проверку снова."
        )
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise DocxReadError(f"{name}: файл не является DOCX (это не ZIP-пакет OOXML).")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
    if "[Content_Types].xml" not in names:
        raise DocxReadError(f"{name}: в пакете нет [Content_Types].xml, это не документ Word.")


def open_docx_bytes(data: bytes, name: str = "document.docx") -> Any:
    """Открыть байты DOCX в python-docx с понятной ошибкой на русском."""
    _check_container(data, name)
    try:
        return _pydocx.Document(io.BytesIO(data))
    except Exception as exc:  # ValueError для .docm/.dotx, KeyError для битого пакета
        raise DocxReadError(f"{name}: Word-пакет не открывается python-docx ({type(exc).__name__}: {exc}).") from exc


def _title(doc: Any, specs: list[BlockSpec], fallback: str) -> str:
    try:
        t = (doc.core_properties.title or "").strip()
    except Exception:  # pragma: no cover
        t = ""
    if t:
        return t
    for lvl in (0, 1):
        for s in specs:
            if s.kind == "heading" and s.loc.get("heading_level") == lvl:
                return _truncate(s.text, 200)
    return _truncate(specs[0].text, 200) if specs else fallback


def read_docx_bytes(data: bytes, name: str = "document.docx") -> Document:
    doc = open_docx_bytes(data, name)
    layout = DocxLayout(doc)
    warnings = list(layout.warnings)
    if not layout.specs:
        warnings.append({"code": "docx_empty", "message": "В теле документа нет непустых абзацев и строк таблиц.",
                         "stage": "read"})
    return Document(
        id=hashlib.sha256(data).hexdigest(),
        title=_title(doc, layout.specs, Path(name).stem),
        format="docx",
        blocks=[s.to_block() for s in layout.specs],
        warnings=warnings,
        source_name=name,
    )


def read_docx(path: Path | str) -> Document:
    """Прочитать DOCX в ``Document`` контракта v1 (см. описание модуля)."""
    path = Path(path)
    return read_docx_bytes(path.read_bytes(), name=path.name)
