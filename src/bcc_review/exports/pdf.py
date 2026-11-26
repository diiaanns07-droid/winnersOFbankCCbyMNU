"""PDF-экспорт отчёта BCC Review с нативными выделениями и записками (исполнитель №14).

Публичный интерфейс (общий контракт v1)::

    write_pdf(report, input_path, output_path) -> Path

* Вход — PDF. Аннотируется отдельная копия. Исходные байты копируются как есть, аннотации
  дописываются инкрементальным сохранением, поэтому оригинал остаётся префиксом выходного файла.
  Добавляются выделения (Highlight) со всплывающей заметкой, видимые подписи (FreeText,
  набранные встроенным Noto Sans), заметки (Text) для сканов и опор без координат, ссылки между
  сторонами противоречия и сводная заметка. Исходный файл открывается только на чтение, его
  хеш перепроверяется в конце.
* Вход — Markdown (или TXT). Строится производная постраничная PDF-версия на Noto Sans с
  поддержкой кириллицы и ₸, картой размещённых строк и блоков, подписями «страница экспорта»
  и теми же аннотациями. Знаки, которых нет в Noto Sans (стрелки `→`), набираются
  закреплённым Noto Sans Math. О знаках, которых нет ни в одном шрифте, экспорт сообщает. Ссылкой на источник остаются номера строк Markdown: они напечатаны
  слева от текста.

Привязка Evidence → страница и прямоугольники:
  1. Для Evidence заново проверяется ``block.text[start:end] == quote``. Без этого опора не
     размещается.
  2. SHA-256 входного файла должен совпасть с ``report.document.id`` и
     ``run.source_sha256``.
  3. PDF: каждый fragment блока (``loc.fragments``: start, end, rect, а у наклонного текста
     №02 ещё ``quad``) сужает поиск до своей страницы и своей рамки. Если есть ``quad``, область
     поиска — четырёхугольник, а не осевая рамка. Символы области выравниваются с
     ``block.text[start:end]``. Знаки всех fragments цитаты собираются по строкам: горизонтальная
     строка даёт объединённый прямоугольник, наклонная — четырёхугольник от первого до последнего
     знака (``recover_char_quad``). Соседняя строка внутри осевой рамки не закрашивается.
     Похожая фраза в другом месте документа не используется никогда.
  4. Markdown: если у блока есть ``loc.map`` контракта, позиция в block.text переводится в
     (строку, колонку) исходника, и берётся знак, который наша вёрстка поставила для этой
     колонки. Без ``loc.map`` текст блока выравнивается с размещёнными знаками его строк
     (``loc.line_start..line_end``).
  5. Если координат нет (скан, нет fragments, неоднозначность), на подтверждённой странице
     ставится явно подписанная заметка. Если неизвестна и страница, причина записывается в
     сводку и в манифест.

Координаты (проверено на PyMuPDF 2.2 / MuPDF 1.28 с поворотами 0/90/180/270 и смещённым
CropBox, сверено с poppler и PDFium, см. ``tests/p14``):
  * ``page.get_text()`` и ``page.add_*_annot()`` работают в неповёрнутом пространстве страницы:
    начало в левом верхнем углу CropBox, ось y направлена вниз, /Rotate не учитывается;
  * экранное пространство = неповёрнутое × ``page.rotation_matrix``;
  * ``page.transformation_matrix`` неверна для страницы с /Rotate и смещённым CropBox,
    поэтому матрица «страница → пространство PDF» снимается пробной аннотацией
    (:func:`_unrot_to_pdf`).
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pymupdf

__all__ = [
    "write_pdf",
    "export_pdf",
    "ExportResult",
    "Placement",
    "read_annotations",
    "verify_export",
    "render_page_png",
    "page_label",
    "missing_glyphs",
    "glyph_report",
    "SourceMismatchError",
    "UnsupportedFormatError",
    "MissingGlyphError",
    "FontAssetError",
]

EXPORT_SCHEMA = "bcc_review.pdf_export/1"
MANIFEST_NAME = "bcc_review_pdf_export.json"
PAGE_LABEL_PREFIX = "Экспорт-"
ASSETS_DIR = Path(__file__).with_name("pdf_assets")
FONT_FILE = ASSETS_DIR / "NotoSans[wdth,wght].ttf"
FALLBACK_FILE = ASSETS_DIR / "NotoSansMath-Regular.ttf"
FONT_LOCK = ASSETS_DIR / "font.lock.json"
LABEL_FONT_RES = "BCCNoto"
NM_PREFIX = "bcc-review:"

# Цвет только дублирует серьёзность. В каждой подписи и заметке она названа словом и
# текстовым маркером, а в видимой подписи ещё и векторной фигурой своей формы.
SEVERITY: dict[str, dict[str, Any]] = {
    "critical": {
        "word": "КРИТИЧНО",
        "mark": "[!!!]",
        "shape": "triangle",
        "highlight": (1.0, 0.52, 0.52),
        "strong": (0.80, 0.07, 0.07),
        "fill": (1.0, 0.90, 0.90),
    },
    "major": {
        "word": "СУЩЕСТВЕННО",
        "mark": "[!!]",
        "shape": "diamond",
        "highlight": (1.0, 0.74, 0.36),
        "strong": (0.80, 0.40, 0.0),
        "fill": (1.0, 0.94, 0.84),
    },
    "minor": {
        "word": "НЕЗНАЧИТЕЛЬНО",
        "mark": "[!]",
        "shape": "circle",
        "highlight": (1.0, 0.93, 0.40),
        "strong": (0.55, 0.47, 0.0),
        "fill": (1.0, 0.98, 0.84),
    },
}
STATUS_WORD = {"confirmed": "подтверждено", "needs_review": "требует проверки"}
ROLE_WORD = {"a": "сторона A", "b": "сторона B"}


# ---------------------------------------------------------------------------- ошибки


class SourceMismatchError(ValueError):
    """Входной файл не тот, по которому построен отчёт (SHA-256 не совпадает)."""


class UnsupportedFormatError(ValueError):
    """PDF-экспорт поддерживает входы PDF и Markdown/TXT."""


class FontAssetError(RuntimeError):
    """Файл шрифта отсутствует или не совпадает с pdf_assets/font.lock.json."""


class MissingGlyphError(ValueError):
    """В выбранном шрифте нет глифов для части символов (strict_glyphs=True)."""

    def __init__(self, missing: Sequence[str], where: str) -> None:
        self.missing = list(missing)
        codes = ", ".join(f"{c!r} U+{ord(c):04X}" for c in self.missing)
        super().__init__(f"В шрифте Noto Sans нет глифов ({where}): {codes}")


# ---------------------------------------------------------------------------- результат


@dataclass
class Placement:
    """Одна размещённая (или не размещённая) опора замечания в выходном PDF."""

    finding_id: str
    part: int
    parts: int
    role: str  # evidence | a | b | inspected | none
    severity: str
    status: str  # highlight | note | skipped
    method: str
    block_id: str | None = None
    start: int | None = None
    end: int | None = None
    quote: str | None = None
    page: int | None = None  # 1-based, страница выходного PDF
    rects: list[list[float]] = field(default_factory=list)  # неповёрнутые координаты (охватывающие)
    quads: list[list[list[float]]] = field(default_factory=list)  # [ul, ur, ll, lr] каждого выделения
    reason: str | None = None
    source_ref: str | None = None
    annot_names: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    output_path: Path
    mode: str  # annotated_copy | derived_from_markdown
    source_path: str
    source_sha256: str
    output_sha256: str
    page_count: int
    saved_incrementally: bool
    placements: list[Placement]
    warnings: list[str]
    missing_glyphs: list[str]
    existing_annotations: int
    line_map: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    block_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    fallback_glyphs: list[str] = field(default_factory=list)  # набраны Noto Sans Math
    unrendered_glyphs: list[str] = field(default_factory=list)  # нет ни в одном шрифте pdf_assets

    def summary(self) -> dict[str, Any]:
        st = defaultdict(int)
        for p in self.placements:
            st[p.status] += 1
        return {
            "output": str(self.output_path),
            "mode": self.mode,
            "pages": self.page_count,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "saved_incrementally": self.saved_incrementally,
            "highlights": st["highlight"],
            "notes": st["note"],
            "skipped": st["skipped"],
            "existing_annotations": self.existing_annotations,
            "missing_glyphs": self.missing_glyphs,
            "fallback_glyphs": self.fallback_glyphs,
            "unrendered_glyphs": self.unrendered_glyphs,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------- шрифт


@functools.lru_cache(maxsize=1)
def _font_lock() -> dict[str, Any]:
    return json.loads(FONT_LOCK.read_text(encoding="utf-8"))


def _pinned(path: Path, want: str) -> bytes:
    if not path.is_file():
        raise FontAssetError(f"Нет файла шрифта {path}")
    data = path.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise FontAssetError(f"SHA-256 {path.name} = {got} не совпадает с font.lock.json ({want})")
    return data


@functools.lru_cache(maxsize=1)
def _font_raw() -> bytes:
    return _pinned(FONT_FILE, _font_lock()["sha256"])


@functools.lru_cache(maxsize=1)
def _fallback_raw() -> bytes:
    return _pinned(FALLBACK_FILE, _font_lock()["fallback"]["sha256"])


@functools.lru_cache(maxsize=1)
def _fallback_font() -> pymupdf.Font:
    return pymupdf.Font(fontbuffer=_fallback_raw())


@functools.lru_cache(maxsize=8)
def _build_fallback(chars: str) -> bytes:
    """Noto Sans Math, урезанный до ``chars`` (статический шрифт, инстанцирование не нужно)."""
    raw = _fallback_raw()
    if not _fonttools_available():
        return raw
    from fontTools import subset
    from fontTools.ttLib import TTFont

    tt = TTFont(io.BytesIO(raw))
    opts = subset.Options()
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.layout_features = []
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(tt)
    buf = io.BytesIO()
    tt.save(buf)
    return buf.getvalue()


def _fonttools_available() -> bool:
    try:
        import fontTools  # noqa: F401
    except ImportError:
        return False
    return True


BASE_CHARS = (
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    + "ӘәІіҢңҒғҮүҰұҚқӨөҺһ₸«»—–…№•·"
)


@functools.lru_cache(maxsize=1)
def _raw_font() -> pymupdf.Font:
    """Вариативный файл как есть. Экземпляр по умолчанию — Regular (wght=400, wdth=100),
    поэтому его метрики и cmap годятся для замеров Regular и проверки глифов."""
    return pymupdf.Font(fontbuffer=_font_raw())


@functools.lru_cache(maxsize=16)
def _build_font(chars: str, weight: int) -> bytes:
    """Статический Noto Sans (wght=weight, wdth=100), урезанный до ``chars`` + BASE_CHARS.

    Сначала строится подмножество, потом экземпляр: так быстрее в десятки раз, чем
    инстанцировать весь вариативный файл. Без fontTools возвращается исходный вариативный файл,
    MuPDF рисует его экземпляр по умолчанию, и полужирный совпадает с обычным.
    """
    raw = _font_raw()
    if not _fonttools_available():
        return raw
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    tt = TTFont(io.BytesIO(raw))
    opts = subset.Options()
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(sorted(set(chars) | set(BASE_CHARS))))
    sub.subset(tt)
    inst = instancer.instantiateVariableFont(tt, {"wght": weight, "wdth": 100})
    if weight >= 600:
        style = "Bold"
        for rec in inst["name"].names:
            if rec.nameID in (2, 17):
                rec.string = style
            elif rec.nameID == 4:
                rec.string = f"Noto Sans {style}"
            elif rec.nameID == 6:
                rec.string = f"NotoSans-{style}"
        inst["OS/2"].usWeightClass = 700
        inst["OS/2"].fsSelection = (inst["OS/2"].fsSelection | 0x20) & ~0x40
        inst["head"].macStyle |= 0x01
    buf = io.BytesIO()
    inst.save(buf)
    return buf.getvalue()


def missing_glyphs(text: str) -> list[str]:
    """Знаки из ``text``, которых нет во встроенном Noto Sans (без пробелов и управляющих).

    cmap у всех экземпляров вариативного шрифта общий, поэтому проверка одна на оба начертания.
    """
    font = _raw_font()
    out: list[str] = []
    for ch in dict.fromkeys(text):
        if ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf"):
            continue
        if font.has_glyph(ord(ch)) == 0:
            out.append(ch)
    return out


def glyph_report(text: str) -> dict[str, list[str]]:
    """Покрытие текста шрифтами: ``missing`` — нет в Noto Sans; ``fallback`` — из них есть
    в резервном Noto Sans Math; ``unrendered`` — нет ни в одном шрифте из pdf_assets."""
    missing = missing_glyphs(text)
    fb = _fallback_font()
    fallback = [c for c in missing if fb.has_glyph(ord(c))]
    return {"missing": missing, "fallback": fallback, "unrendered": [c for c in missing if c not in fallback]}


# ---------------------------------------------------------------------------- отчёт


def _as_report_dict(report: Any) -> dict[str, Any]:
    if isinstance(report, (str, os.PathLike)):
        return json.loads(Path(report).read_text(encoding="utf-8"))
    if hasattr(report, "model_dump"):
        return report.model_dump(mode="json")
    if dataclasses.is_dataclass(report) and not isinstance(report, type):
        return dataclasses.asdict(report)
    if isinstance(report, dict):
        return report
    raise TypeError(f"Неизвестный тип отчёта: {type(report)!r}")


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _ev_list(v: Any) -> list[dict[str, Any]]:
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, dict)]
    return []


def _severity(f: dict[str, Any]) -> str:
    s = str(f.get("severity") or "").lower()
    return s if s in SEVERITY else "minor"


def _block_lines(block: dict[str, Any]) -> tuple[int, int] | None:
    loc = block.get("loc")
    a = b = None
    if isinstance(loc, dict):
        # контрактные line_start/line_end важнее; у №01 рядом лежит lines = [[строка, col0, col1], ...]
        a = _int(loc.get("line_start", loc.get("start_line", loc.get("line"))))
        b = _int(loc.get("line_end", loc.get("end_line", a)))
        lines = loc.get("lines")
        if a is None and isinstance(lines, (list, tuple)) and lines:
            first, last = lines[0], lines[-1]
            a = _int(first[0] if isinstance(first, (list, tuple)) and first else first)
            b = _int(last[0] if isinstance(last, (list, tuple)) and last else last)
        elif a is None and isinstance(lines, str):
            return _parse_line_range(lines)
    elif isinstance(loc, str):
        return _parse_line_range(loc)
    elif _int(loc) is not None:
        a = b = _int(loc)
    if a is None:
        return None
    return (a, b if b is not None and b >= a else a)


def _parse_line_range(s: str) -> tuple[int, int] | None:
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if not nums:
        return None
    return (nums[0], nums[-1] if nums[-1] >= nums[0] else nums[0])


def _block_pages(block: dict[str, Any]) -> list[int]:
    loc = block.get("loc")
    if not isinstance(loc, dict):
        return []
    pages = loc.get("pages")
    if isinstance(pages, (list, tuple)):
        out = [p for p in (_int(x) for x in pages) if p is not None]
        if len(out) == 2 and out[1] > out[0] + 1:
            out = list(range(out[0], out[1] + 1))
        return out
    a = _int(loc.get("page_start", loc.get("page")))
    b = _int(loc.get("page_end", a))
    if a is None:
        return []
    return list(range(a, (b if b and b >= a else a) + 1))


@dataclass
class _Frag:
    start: int
    end: int
    pages: tuple[int, ...]
    bbox: tuple[float, float, float, float] | None
    space: str
    sha256: str | None
    quad: tuple[tuple[float, float], ...] | None = None  # ul, ur, ll, lr — наклонный текст №02


def _parse_quad(q: Any) -> tuple[tuple[float, float], ...] | None:
    """quad fragment: ``[[x,y]×4]`` (ul, ur, ll, lr, как у №02) или 8 чисел подряд."""
    if not isinstance(q, (list, tuple)):
        return None
    flat = [v for p in q for v in p] if q and isinstance(q[0], (list, tuple)) else list(q)
    if len(flat) != 8 or not all(isinstance(v, (int, float)) for v in flat):
        return None
    return tuple((float(flat[i]), float(flat[i + 1])) for i in range(0, 8, 2))


def _fragments(block: dict[str, Any]) -> list[_Frag]:
    """fragments блока по контракту №02 (block.loc.fragments) с терпимостью к написанию ключей."""
    loc = block.get("loc") if isinstance(block.get("loc"), dict) else {}
    raw = loc.get("fragments") or block.get("fragments") or []
    n = len(block.get("text") or "")
    out: list[_Frag] = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        st = _int(f.get("start", f.get("char_start", 0)))
        en = _int(f.get("end", f.get("char_end", n)))
        pg = _int(f.get("page", f.get("page_number")))
        bb = f.get("bbox", f.get("rect"))
        if isinstance(bb, dict):
            bb = (bb.get("x0"), bb.get("y0"), bb.get("x1"), bb.get("y1"))
        bbox = None
        if isinstance(bb, (list, tuple)) and len(bb) == 4 and all(isinstance(v, (int, float)) for v in bb):
            bbox = tuple(float(v) for v in bb)  # type: ignore[assignment]
        quad = _parse_quad(f.get("quad"))
        out.append(
            _Frag(
                start=st if st is not None else 0,
                end=en if en is not None else n,
                pages=(pg,) if pg is not None else tuple(_block_pages(block)[:1]),
                bbox=bbox,
                space=str(f.get("space") or f.get("coords") or loc.get("space") or "pymupdf").lower(),
                sha256=f.get("source_sha256") or f.get("sha256"),
                quad=quad,
            )
        )
    if not out:
        pages = _block_pages(block)
        if pages:
            out.append(_Frag(0, n, tuple(pages), None, "pymupdf", None))
    return out


def _question_for(rep: dict[str, Any], f: dict[str, Any], fid: str) -> str | None:
    q = f.get("question")
    if isinstance(q, dict):
        q = q.get("text") or q.get("question")
    if isinstance(q, str) and q.strip():
        return q.strip()
    for qq in rep.get("questions") or []:
        if not isinstance(qq, dict):
            continue
        ids = list(qq.get("finding_ids") or [])
        if qq.get("finding_id"):
            ids.append(qq["finding_id"])
        if fid in ids:
            t = qq.get("prompt") or qq.get("text") or qq.get("question")
            if t:
                opts = [str(o) for o in qq.get("options") or [] if str(o).strip()]
                return str(t).strip() + (" Варианты: " + "; ".join(opts) + "." if opts else "")
    return None


@dataclass
class _Anchor:
    finding: dict[str, Any]
    fid: str
    role: str
    ev: dict[str, Any] | None
    part: int
    parts: int


def _collect_anchors(rep: dict[str, Any]) -> list[_Anchor]:
    anchors: list[_Anchor] = []
    for i, f in enumerate(rep.get("findings") or []):
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or f"F-{i + 1:02d}")
        items: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[Any, Any, Any]] = set()
        w = f.get("witness") if isinstance(f.get("witness"), dict) else {}
        candidates = (
            [("a", ev) for ev in _ev_list(w.get("evidence_a"))]
            + [("b", ev) for ev in _ev_list(w.get("evidence_b"))]
            + [("evidence", ev) for ev in _ev_list(f.get("evidence"))]
        )
        for role, ev in candidates:  # сторона противоречия важнее дубля в evidence
            key = (ev.get("block_id"), ev.get("start"), ev.get("end"))
            if key not in seen:
                seen.add(key)
                items.append((role, ev))
        if not items:
            for bid in list(f.get("inspected_block_ids") or [])[:1]:
                items.append(("inspected", {"block_id": bid}))
        if not items:
            anchors.append(_Anchor(f, fid, "none", None, 1, 1))
            continue
        for k, (role, ev) in enumerate(items):
            anchors.append(_Anchor(f, fid, role, ev, k + 1, len(items)))
    return anchors


# ---------------------------------------------------------------------------- выравнивание

_DROP = set("*_`|#>[]\\­​‌‍⁠﻿")
_FOLD = {
    **{c: "-" for c in "‐‑‒–—―−"},
    **{c: '"' for c in "«»“”„‟″"},
    **{c: "'" for c in "‘’‚‛′"},
}
_HYPHENS = set("-‐‑­")


def _norm(chars: Sequence[str], drop: Sequence[bool] | None = None) -> tuple[str, list[int]]:
    """Сравнимая форма: NFKC, без пробелов и разметки, с унифицированными тире и кавычками.

    Возвращает строку и для каждой её позиции индекс исходного символа.
    """
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(chars):
        if drop is not None and drop[i]:
            continue
        for c in unicodedata.normalize("NFKC", ch):
            if c.isspace() or c in _DROP:
                continue
            out.append(_FOLD.get(c, c))
            idx.append(i)
    return "".join(out), idx


def _find_all(hay: str, needle: str) -> list[int]:
    res: list[int] = []
    if not needle:
        return res
    i = hay.find(needle)
    while i != -1:
        res.append(i)
        i = hay.find(needle, i + 1)
    return res


def _align(
    target: str,
    s: int,
    e: int,
    cand: Sequence[str],
    eol_hyphen: Sequence[bool] | None = None,
    score: Callable[[int, int], float] | None = None,
) -> tuple[tuple[int, int] | None, str | None]:
    """Найти в ``cand`` символы, соответствующие ``target[s:e]``.

    ``target`` целиком (текст блока или фрагмента) должен встретиться в ``cand`` ровно один
    раз. Несколько вхождений допустимы, только если ``score`` однозначно выбирает лучшее.
    Похожая фраза в другом месте не подставляется: ``cand`` уже ограничен подтверждённой
    страницей и областью.
    """
    t_norm, t_map = _norm(list(target))
    sel = [k for k, i in enumerate(t_map) if s <= i < e]
    if not sel:
        return None, "в диапазоне цитаты нет значимых символов"
    occ: list[int] = []
    c_map: list[int] = []
    for attempt in range(2):
        drop = eol_hyphen if attempt == 1 else None
        if attempt == 1 and not (eol_hyphen and any(eol_hyphen)):
            break
        c_norm, c_map = _norm(cand, drop)
        occ = _find_all(c_norm, t_norm)
        if occ:
            break
    if not occ:
        return None, "текст блока не найден в подтверждённой области страницы"
    if len(occ) > 1:
        if score is None:
            return None, f"текст блока встречается {len(occ)} раза в подтверждённой области — без координат не выбрать"
        ranked = sorted(((score(c_map[o], c_map[o + len(t_norm) - 1]), o) for o in occ), reverse=True)
        if ranked[0][0] <= 0 or abs(ranked[0][0] - ranked[1][0]) < 1e-6:
            return None, f"текст блока встречается {len(occ)} раза в области fragment — неоднозначно"
        occ = [ranked[0][1]]
    base = occ[0]
    return (c_map[base + sel[0]], c_map[base + sel[-1]]), None


def _line_rects(items: Iterable[tuple[str, pymupdf.Rect | None, Any]]) -> list[pymupdf.Rect]:
    """Объединить прямоугольники символов по строкам (ключ строки — третий элемент)."""
    groups: list[tuple[Any, list[tuple[str, pymupdf.Rect]]]] = []
    for c, r, key in items:
        if r is None or r.is_empty:
            continue
        if groups and groups[-1][0] == key:
            groups[-1][1].append((c, r))
        else:
            groups.append((key, [(c, r)]))
    out: list[pymupdf.Rect] = []
    for _, chars in groups:
        while chars and chars[0][0].isspace():
            chars = chars[1:]
        while chars and chars[-1][0].isspace():
            chars = chars[:-1]
        if not chars:
            continue
        u = pymupdf.Rect(chars[0][1])
        for _, r in chars[1:]:
            u |= r
        out.append(u)
    return out


@dataclass
class _Loc:
    page: int | None  # 0-based страница выходного PDF
    rects: list[pymupdf.Rect]
    method: str
    reason: str | None = None


# ---------------------------------------------------------------------------- локаторы


@dataclass
class _Ch:
    c: str
    rect: pymupdf.Rect
    key: tuple[int, int, int]
    eol: bool
    quad: pymupdf.Quad | None = None  # точная форма знака (наклонная строка — не прямоугольник)


def _char_quad(line: dict[str, Any], span: dict[str, Any], ch: dict[str, Any]) -> pymupdf.Quad:
    try:
        return pymupdf.recover_char_quad(line["dir"], span, ch)
    except Exception:  # noqa: BLE001 — без метрик шрифта остаётся рамка знака
        return pymupdf.Rect(ch["bbox"]).quad


def _in_quad(pt: pymupdf.Point, q: pymupdf.Quad, tol: float = 1.5) -> bool:
    """Точка внутри выпуклого четырёхугольника ul→ur→lr→ll с допуском tol (pt)."""
    ring = [q.ul, q.ur, q.lr, q.ll]
    area = sum(a.x * b.y - b.x * a.y for a, b in zip(ring, ring[1:] + ring[:1]))
    sign = 1.0 if area >= 0 else -1.0
    for a, b in zip(ring, ring[1:] + ring[:1]):
        edge = abs(b - a)
        if edge == 0:
            continue
        cross = (b.x - a.x) * (pt.y - a.y) - (b.y - a.y) * (pt.x - a.x)
        if sign * cross / edge < -tol:
            return False
    return True


def _line_quads(items: Iterable[_Ch]) -> list[pymupdf.Quad]:
    """Знаки цитаты → одна фигура на строку. Горизонтальная строка — объединение рамок знаков
    (как раньше). Наклонная — четырёхугольник от первого до последнего знака по направлению строки,
    поэтому соседняя строка внутри осевого прямоугольника не попадает под выделение."""
    groups: list[list[_Ch]] = []
    for c in items:
        if groups and groups[-1][0].key == c.key:
            groups[-1].append(c)
        else:
            groups.append([c])
    out: list[pymupdf.Quad] = []
    for g in groups:
        while g and g[0].c.isspace():
            g = g[1:]
        while g and g[-1].c.isspace():
            g = g[:-1]
        if not g:
            continue
        first, last = g[0].quad or g[0].rect.quad, g[-1].quad or g[-1].rect.quad
        base = first.ur - first.ul
        if abs(base.y) <= 0.02 * abs(base.x) + 1e-6:
            u = pymupdf.Rect(g[0].rect)
            for c in g[1:]:
                u |= c.rect
            out.append(u.quad)
        else:
            out.append(pymupdf.Quad(first.ul, last.ur, first.ll, last.lr))
    return out


class _PdfLocator:
    """Опора → прямоугольники в исходном PDF по fragments №02 (страница + bbox)."""

    kind = "pdf"

    def __init__(self, doc: pymupdf.Document, source_sha: str) -> None:
        self.doc = doc
        self.sha = source_sha
        self._chars: dict[int, list[_Ch]] = {}
        self._p2pdf: dict[int, pymupdf.Matrix] = {}

    def chars(self, pno: int) -> list[_Ch]:
        if pno not in self._chars:
            page = self.doc[pno]
            flags = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
            data = page.get_text("rawdict", flags=flags)
            out: list[_Ch] = []
            for b in data.get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                for li, line in enumerate(b.get("lines", [])):
                    lc = [
                        _Ch(ch["c"], pymupdf.Rect(ch["bbox"]), (pno, b.get("number", 0), li), False,
                            _char_quad(line, span, ch))
                        for span in line.get("spans", [])
                        for ch in span.get("chars", [])
                    ]
                    for k in range(len(lc) - 1, -1, -1):
                        if not lc[k].c.isspace():
                            lc[k].eol = lc[k].c in _HYPHENS
                            break
                    out.extend(lc)
            self._chars[pno] = out
        return self._chars[pno]

    def empty_reason(self, pno: int) -> str | None:
        if any(not c.c.isspace() for c in self.chars(pno)):
            return None
        if self.doc[pno].get_images():
            return "страница без текстового слоя (скан) — координаты слов недоступны"
        return "на странице нет извлекаемого текста"

    def to_unrot(self, pno: int, bbox: tuple[float, ...], space: str) -> pymupdf.Rect:
        r = pymupdf.Rect(bbox)
        page = self.doc[pno]
        if space in ("pymupdf", "mupdf", "unrotated", "fitz"):
            return r
        if space in ("display", "rotated", "viewer"):
            return r * page.derotation_matrix
        if space in ("pdf", "user", "pdf_user"):
            return r * ~_unrot_to_pdf(page, self._p2pdf)
        raise ValueError(f"неизвестное пространство координат fragment: {space}")

    def to_unrot_quad(self, pno: int, quad: tuple[tuple[float, float], ...], space: str) -> pymupdf.Quad:
        page = self.doc[pno]
        if space in ("pymupdf", "mupdf", "unrotated", "fitz"):
            m = pymupdf.Identity
        elif space in ("display", "rotated", "viewer"):
            m = page.derotation_matrix
        elif space in ("pdf", "user", "pdf_user"):
            m = ~_unrot_to_pdf(page, self._p2pdf)
        else:
            raise ValueError(f"неизвестное пространство координат fragment: {space}")
        return pymupdf.Quad(*(pymupdf.Point(p) * m for p in quad))

    def describe(self, loc: _Loc, block: dict[str, Any]) -> str:
        return f"исходный PDF, стр. {loc.page + 1}" if loc.page is not None else "исходный PDF"

    def locate(self, block: dict[str, Any], s: int, e: int) -> list[_Loc]:
        text = block.get("text") or ""
        frags = _fragments(block)
        n = self.doc.page_count
        if not frags:
            return [_Loc(None, [], "none", "у блока нет страницы и fragments (loc)")]
        locs: list[_Loc] = []
        picked: dict[int, dict[int, _Ch]] = defaultdict(dict)  # страница → {номер знака: знак}
        methods: dict[int, set[str]] = defaultdict(set)
        covered = False
        for f in frags:
            lo, hi = max(s, f.start), min(e, f.end)
            if lo >= hi:
                continue
            covered = True
            if f.sha256 and f.sha256 != self.sha:
                locs.append(_Loc(None, [], "fragment", "fragment относится к другому файлу (sha256 не совпадает)"))
                continue
            bad = [p for p in f.pages if not 1 <= p <= n]
            if not f.pages or bad:
                locs.append(_Loc(None, [], "fragment", f"страница {bad or '?'} вне документа ({n} стр.)"))
                continue
            pnos = [p - 1 for p in f.pages]
            if f.quad is not None:
                # наклонный текст: только знаки внутри четырёхугольника fragment, а не его осевой рамки
                qd = self.to_unrot_quad(pnos[0], f.quad, f.space)
                clip = qd.rect
                pool = [(i, c) for i, c in enumerate(self.chars(pnos[0])) if _in_quad((c.rect.tl + c.rect.br) / 2, qd)]
                method = "fragment_quad"
            elif f.bbox is not None:
                clip = self.to_unrot(pnos[0], f.bbox, f.space)
                grow = clip + (-2.0, -2.0, 2.0, 2.0)
                pool = [(i, c) for i, c in enumerate(self.chars(pnos[0])) if grow.contains((c.rect.tl + c.rect.br) / 2)]
                method = "fragment_bbox"
            else:
                pool = [(i + 100000 * k, c) for k, p in enumerate(pnos) for i, c in enumerate(self.chars(p))]
                method = "page_text"
            cand = [c for _, c in pool]
            score = None
            if method != "page_text":

                def score(i0: int, i1: int, cand: list[_Ch] = cand, clip: pymupdf.Rect = clip) -> float:
                    return sum((c.rect & clip).get_area() for c in cand[i0 : i1 + 1])

            span, reason = _align(
                text[f.start : f.end], lo - f.start, hi - f.start, [c.c for c in cand], [c.eol for c in cand], score
            )
            if span is None:
                why = self.empty_reason(pnos[0]) or reason
                if method == "page_text":
                    why = "нет координат слов от ридера (у блока только loc.page); " + why
                locs.append(_Loc(pnos[0], [], method, why))
                continue
            for idx, c in pool[span[0] : span[1] + 1]:
                picked[c.key[0]][idx] = c
                methods[c.key[0]].add(method)
        if not covered:
            return [_Loc(None, [], "fragment", "диапазон цитаты не покрыт fragments блока")]
        found = [
            _Loc(pno, _line_quads(c for _, c in sorted(picked[pno].items())), "+".join(sorted(methods[pno])))
            for pno in sorted(picked)
        ]
        return [lc for lc in found if lc.rects] + locs


def _unrot_to_pdf(page: pymupdf.Page, cache: dict[int, pymupdf.Matrix] | None = None) -> pymupdf.Matrix:
    """Матрица из неповёрнутых координат страницы в пространство PDF.

    Её снимает сам MuPDF: пробный Highlight на известных точках, чтение /QuadPoints,
    удаление пробы. ``page.transformation_matrix`` для этого не годится: на странице с
    /Rotate и смещённым CropBox она неверна (PyMuPDF 2.2).
    """
    if cache is not None and page.number in cache:
        return cache[page.number]
    doc = page.parent
    probe = page.add_highlight_annot(pymupdf.Rect(0, 0, 10, 10))
    raw = doc.xref_get_key(probe.xref, "QuadPoints")[1]
    page.delete_annot(probe)
    v = [float(x) for x in raw.strip("[]").split()]
    ulx, uly, urx, ury, llx, lly = v[:6]
    m = pymupdf.Matrix((urx - ulx) / 10, (ury - uly) / 10, (llx - ulx) / 10, (lly - uly) / 10, ulx, uly)
    if cache is not None:
        cache[page.number] = m
    return m


# ---------------------------------------------------------------------------- аннотации


@dataclass
class _Label:
    xref: int
    pno: int
    disp: pymupdf.Rect
    lines: list[str]
    sev: str
    review: bool


class _Annotator:
    """Нативные аннотации: Highlight + Popup, FreeText-подпись нашим шрифтом, Text, Link."""

    FS = 6.4
    LEAD = 7.7
    PAD = 2.2
    ICON = 5.6

    def __init__(self, doc: pymupdf.Document, extent: dict[int, tuple[float, float]] | None = None) -> None:
        self.doc = doc
        self.measure = _raw_font()
        self.labels: list[_Label] = []
        self.occupied: dict[int, list[pymupdf.Rect]] = defaultdict(list)
        self.notes_on_page: dict[int, int] = defaultdict(int)
        self.extent_override = extent or {}
        self._p2pdf: dict[int, pymupdf.Matrix] = {}
        self.label_chars: set[str] = set()
        self.overlaps_text = 0  # подписи, которым не нашлось свободного места рядом с текстом
        # Строки текста запоминаются до первой нашей аннотации: MuPDF включает текст
        # FreeText-подписей в get_text(), и иначе каждая подпись занимала бы место следующей.
        self._rows: dict[int, list[pymupdf.Rect]] = {}
        for pno in range(doc.page_count):
            if pno not in self.extent_override:
                self.text_rows(pno)

    # -- геометрия
    def text_rows(self, pno: int) -> list[pymupdf.Rect]:
        """Прямоугольники строк текста в экранных координатах (с учётом /Rotate)."""
        if pno not in self._rows:
            page = self.doc[pno]
            rows: list[pymupdf.Rect] = []
            for b in page.get_text("dict").get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                for line in b.get("lines", []):
                    if "".join(s.get("text", "") for s in line.get("spans", [])).strip():
                        rows.append(pymupdf.Rect(line["bbox"]) * page.rotation_matrix)
            self._rows[pno] = rows
        return self._rows[pno]

    def _label_size(self, lines: list[str]) -> tuple[float, float]:
        tw = max(self.measure.text_length(t, self.FS) for t in lines)
        return (self.PAD * 2 + self.ICON + 2.6 + tw, self.PAD * 2 + self.LEAD * len(lines))

    def _place(self, pno: int, anchor: pymupdf.Rect, lines: list[str]) -> tuple[pymupdf.Rect, list[str]]:
        """Место для подписи в экранных координатах: рядом с выделением и без наложения на
        текст и другие подписи. Сначала справа от строк в той же полосе, потом слева.
        Если места нет, подпись в одну строку ставится над выделением (учитывается в overlaps_text)."""
        page = self.doc[pno]
        dw, dh = page.rect.width, page.rect.height
        w, h = self._label_size(lines)
        occupied = self.occupied[pno]
        if pno in self.extent_override:  # своя вёрстка: отдельная колонка для подписей
            x = self.extent_override[pno][1] + 3.0
            y = min(max(1.0, anchor.y0 - 1.0), dh - h - 1.0)
            r = pymupdf.Rect(x, y, x + w, y + h)
            for _ in range(400):
                hit = [o for o in occupied if o.intersects(r)]
                if not hit:
                    break
                r = pymupdf.Rect(x, max(o.y1 for o in hit) + 1.5, x + w, max(o.y1 for o in hit) + 1.5 + h)
            if r.y1 > dh - 1:
                r = pymupdf.Rect(x, dh - h - 1, x + w, dh - 1)
            occupied.append(r)
            return r, lines
        rows = self.text_rows(pno)

        def free(r: pymupdf.Rect) -> bool:
            inside = r.x0 >= 1 and r.y0 >= 1 and r.x1 <= dw - 1 and r.y1 <= dh - 1
            return inside and not any(o.intersects(r) for o in occupied) and not any(t.intersects(r) for t in rows)

        for dy in [0.0] + [s * 2.5 for s in range(1, 80)]:
            y = anchor.y0 - 1.0 + dy
            band = [t for t in rows if t.y1 > y and t.y0 < y + h] + [anchor]
            for x in (max(t.x1 for t in band) + 3.0, min(t.x0 for t in band) - 3.0 - w):
                r = pymupdf.Rect(x, y, x + w, y + h)
                if free(r):
                    occupied.append(r)
                    return r, lines
        lines = [" · ".join(lines)]
        w, h = self._label_size(lines)
        # компактная подпись в одну строку: ближайший свободный промежуток над или под выделением
        xs = [min(max(2.0, anchor.x0), dw - w - 2.0), min(max(2.0, anchor.x1 - w), dw - w - 2.0)]
        for dy in [k * 2.0 for k in range(40)]:
            for y in (anchor.y0 - h - 0.8 - dy, anchor.y1 + 0.8 + dy):
                for x in xs:
                    r = pymupdf.Rect(x, y, x + w, y + h)
                    if free(r):
                        occupied.append(r)
                        return r, lines
        x = xs[0]
        r = pymupdf.Rect(x, max(1.0, anchor.y0 - h - 0.8), x + w, max(1.0, anchor.y0 - h - 0.8) + h)
        self.overlaps_text += 1
        occupied.append(r)
        return r, lines

    # -- примитивы
    def _nm(self, xref: int, name: str) -> None:
        self.doc.xref_set_key(xref, "NM", pymupdf.get_pdf_str(NM_PREFIX + name))

    def highlight(
        self, pno: int, rects: list[pymupdf.Rect], sev: str, title: str, subject: str, content: str, name: str
    ) -> int:
        page = self.doc[pno]
        quads = [q if isinstance(q, pymupdf.Quad) else pymupdf.Rect(q).quad for q in rects]
        a = page.add_highlight_annot(quads=quads)
        a.set_colors(stroke=SEVERITY[sev]["highlight"])
        a.set_info(title=title, subject=subject, content=content)
        a.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
        a.update()
        disp = quads[0].rect * page.rotation_matrix
        dw = page.rect.width
        pw, ph = 230.0, 150.0
        px = min(max(2.0, disp.x1 + 8), dw - pw - 2)
        py = min(max(2.0, disp.y0), page.rect.height - ph - 2)
        a.set_popup(pymupdf.Rect(px, py, px + pw, py + ph) * page.derotation_matrix)
        a.set_open(False)
        self._nm(a.xref, name)
        return a.xref

    def note(self, pno: int, sev: str, title: str, subject: str, content: str, name: str) -> pymupdf.Rect:
        page = self.doc[pno]
        k = self.notes_on_page[pno]
        self.notes_on_page[pno] += 1
        disp_pt = pymupdf.Point(page.rect.width - 20, 6 + 26 * k)
        a = page.add_text_annot(disp_pt * page.derotation_matrix, content, icon="Note")
        a.set_colors(stroke=SEVERITY[sev]["strong"])
        a.set_info(title=title, subject=subject, content=content)
        a.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
        a.update()
        self._nm(a.xref, name)
        return pymupdf.Rect(disp_pt.x - 2, disp_pt.y, disp_pt.x + 18, disp_pt.y + 18)

    def label(
        self, pno: int, anchor_disp: pymupdf.Rect, lines: list[str], sev: str, review: bool, contents: str, name: str
    ) -> pymupdf.Rect:
        page = self.doc[pno]
        disp, lines = self._place(pno, anchor_disp, lines)
        a = page.add_freetext_annot(
            disp * page.derotation_matrix,
            contents,
            fontsize=self.FS,
            fontname="helv",
            text_color=(0.1, 0.1, 0.1),
            fill_color=SEVERITY[sev]["fill"],
        )
        a.set_info(title="BCC Review", subject=f"подпись · {SEVERITY[sev]['word']}", content=contents)
        a.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
        self._nm(a.xref, name)
        for t in lines:
            self.label_chars.update(t)
        self.labels.append(_Label(a.xref, pno, disp, lines, sev, review))
        return disp

    def link(self, pno: int, from_disp: pymupdf.Rect, to_pno: int, to_disp: pymupdf.Rect) -> None:
        """Ссылка-переход с подписи одной стороны противоречия на подпись другой.

        insert_link считает /Rect через ту же неверную transformation_matrix, поэтому /Rect и
        /Dest после вставки переписываются по матрице, снятой пробой.
        """
        page = self.doc[pno]
        target = self.doc[to_pno]
        to_unrot = pymupdf.Point(to_disp.x0, max(0.0, to_disp.y0 - 20)) * target.derotation_matrix
        # get_links() сразу после insert_link возвращает устаревший список, а /Annots
        # (annot_xrefs) уже содержит новую ссылку. Поэтому ищем её по /Annots.
        before = {x[0] for x in page.annot_xrefs()}
        page.insert_link(
            {"kind": pymupdf.LINK_GOTO, "from": from_disp * page.derotation_matrix, "page": to_pno, "to": to_unrot, "zoom": 0}
        )
        page = self.doc[pno]
        target = self.doc[to_pno]
        new = [x[0] for x in page.annot_xrefs() if x[0] not in before and x[1] == pymupdf.PDF_ANNOT_LINK]
        if len(new) != 1:
            raise RuntimeError(f"не удалось найти созданную ссылку на стр. {pno + 1}")
        box = from_disp * page.derotation_matrix * _unrot_to_pdf(page, self._p2pdf)
        dest = to_unrot * _unrot_to_pdf(target, self._p2pdf)
        lx = new[0]
        self.doc.xref_set_key(lx, "Rect", f"[{box.x0:.3f} {box.y0:.3f} {box.x1:.3f} {box.y1:.3f}]")
        self.doc.xref_set_key(lx, "A", "null")
        self.doc.xref_set_key(lx, "Dest", f"[{target.xref} 0 R /XYZ {dest.x:.2f} {dest.y:.2f} 0]")
        self.doc.xref_set_key(lx, "NM", pymupdf.get_pdf_str(f"{NM_PREFIX}link:{pno + 1}->{to_pno + 1}"))

    # -- собственный вид подписей
    def _embed_label_font(self, buf: bytes) -> int:
        n = self.doc.page_count
        tmp = self.doc.new_page(-1, width=20, height=20)
        xref = tmp.insert_font(fontname=LABEL_FONT_RES, fontbuffer=buf)
        self.doc.delete_page(n)
        return xref

    def finalize_labels(self) -> None:
        """Заменить вид FreeText-подписей на поток с встроенным Noto Sans (Type0, glyph id).

        Вызывается после всех остальных изменений страницы, чтобы MuPDF больше не перестраивал
        вид этих аннотаций.
        """
        if not self.labels:
            return
        buf = _build_font("".join(sorted(self.label_chars)), 400)
        font = pymupdf.Font(fontbuffer=buf)
        fx = self._embed_label_font(buf)
        for lb in self.labels:
            page = self.doc[lb.pno]
            to_pdf = _unrot_to_pdf(page, self._p2pdf)
            m = pymupdf.Matrix(1, 0, 0, -1, lb.disp.x0, lb.disp.y1) * page.derotation_matrix * to_pdf
            box = lb.disp * page.derotation_matrix * to_pdf
            stream = self._label_stream(lb, font, m)
            ap = int(self.doc.xref_get_key(lb.xref, "AP/N")[1].split()[0])
            self.doc.update_stream(ap, stream)
            bb = f"[{box.x0:.3f} {box.y0:.3f} {box.x1:.3f} {box.y1:.3f}]"
            self.doc.xref_set_key(ap, "Resources", f"<</Font<</{LABEL_FONT_RES} {fx} 0 R>>>>")
            self.doc.xref_set_key(ap, "BBox", bb)
            self.doc.xref_set_key(ap, "Matrix", "[1 0 0 1 0 0]")
            self.doc.xref_set_key(lb.xref, "Rect", bb)

    def _label_stream(self, lb: _Label, font: pymupdf.Font, m: pymupdf.Matrix) -> bytes:
        sev = SEVERITY[lb.sev]
        w, h = lb.disp.width, lb.disp.height
        p, fs, lead, s = self.PAD, self.FS, self.LEAD, self.ICON

        def rgb(c: tuple[float, float, float]) -> str:
            return " ".join(f"{v:.3f}" for v in c)

        ops = [f"q {m.a:.5f} {m.b:.5f} {m.c:.5f} {m.d:.5f} {m.e:.3f} {m.f:.3f} cm"]
        ops.append(f"{rgb(sev['fill'])} rg 0 0 {w:.2f} {h:.2f} re f")
        ops.append(f"{rgb(sev['strong'])} RG 0.6 w 0.3 0.3 {w - 0.6:.2f} {h - 0.6:.2f} re S")
        cx, cy = p + s / 2, h - p - lead / 2
        paint = "S" if lb.review else "f"
        ops.append(f"{rgb(sev['strong'])} rg {rgb(sev['strong'])} RG 0.7 w")
        if sev["shape"] == "triangle":
            ops.append(f"{cx - s / 2:.2f} {cy - s * 0.43:.2f} m {cx + s / 2:.2f} {cy - s * 0.43:.2f} l {cx:.2f} {cy + s * 0.5:.2f} l h {paint}")
        elif sev["shape"] == "diamond":
            ops.append(
                f"{cx:.2f} {cy + s / 2:.2f} m {cx + s / 2:.2f} {cy:.2f} l {cx:.2f} {cy - s / 2:.2f} l {cx - s / 2:.2f} {cy:.2f} l h {paint}"
            )
        else:
            r = s * 0.45
            k = 0.5523 * r
            ops.append(
                f"{cx + r:.2f} {cy:.2f} m {cx + r:.2f} {cy + k:.2f} {cx + k:.2f} {cy + r:.2f} {cx:.2f} {cy + r:.2f} c "
                f"{cx - k:.2f} {cy + r:.2f} {cx - r:.2f} {cy + k:.2f} {cx - r:.2f} {cy:.2f} c "
                f"{cx - r:.2f} {cy - k:.2f} {cx - k:.2f} {cy - r:.2f} {cx:.2f} {cy - r:.2f} c "
                f"{cx + k:.2f} {cy - r:.2f} {cx + r:.2f} {cy - k:.2f} {cx + r:.2f} {cy:.2f} c h {paint}"
            )
        ops.append("0.08 0.08 0.10 rg BT")
        for i, t in enumerate(lb.lines):
            gids = "".join(f"{font.has_glyph(ord(c)):04x}" for c in t)
            y = h - p - i * lead - fs * 0.93
            ops.append(f"/{LABEL_FONT_RES} {fs} Tf 1 0 0 1 {p + s + 2.6:.2f} {y:.2f} Tm <{gids}> Tj")
        ops.append("ET Q")
        return "\n".join(ops).encode("latin-1")


# ---------------------------------------------------------------------------- размещение


def _note_text(
    rep: dict[str, Any],
    an: _Anchor,
    sev: str,
    where: str,
    other: str | None,
    part_of: str | None,
    req_names: dict[str, str],
) -> str:
    f = an.finding
    status = str(f.get("status") or "")
    lines = [f"{an.fid} · {SEVERITY[sev]['mark']} {SEVERITY[sev]['word']} · {STATUS_WORD.get(status, status or 'статус не указан')}"]
    if f.get("title"):
        lines.append(f"Суть: {f['title']}")
    crit = f.get("criterion")
    kind = f.get("kind")
    if crit or kind:
        lines.append("Критерий: " + " / ".join(dict.fromkeys(str(x) for x in (crit, kind) if x)))
    reqs = [req_names.get(str(r), str(r)) for r in f.get("req_ids") or []]
    if reqs:
        lines.append("Требования: " + ", ".join(reqs))
    lines.append(f"Последствие: {f.get('impact') or 'не указано в отчёте'}")
    if f.get("blocked_decision"):
        lines.append(f"Блокирует решение: {f['blocked_decision']}")
    targets = [{"development": "разработку", "testing": "тестирование"}.get(str(x), str(x)) for x in f.get("blocks") or []]
    if targets:
        lines.append("Мешает начать: " + " и ".join(targets))
    if f.get("anchor_status") == "incomplete":
        lines.append("Опора неполная (anchor_status=incomplete): цитата подтверждена не для всех мест.")
    if f.get("meaning_status") in ("uncertain", "unchecked"):
        lines.append(f"Смысл замечания не подтверждён (meaning_status={f['meaning_status']}).")
    if f.get("recommendation"):
        lines.append(f"Рекомендация: {f['recommendation']}")
    q = _question_for(rep, f, an.fid)
    lines.append(f"Вопрос: {q or 'в отчёте не сформулирован'}")
    w = f.get("witness") if isinstance(f.get("witness"), dict) else None
    if an.role in ("a", "b") and w:
        lines.append(
            f"Противоречие, {ROLE_WORD[an.role]}. Сценарий: {w.get('input', '—')}. "
            f"Исход A: {w.get('outcome_a', '—')}. Исход B: {w.get('outcome_b', '—')}."
        )
        if other:
            lines.append(f"Вторая сторона: {other}")
    elif an.role == "inspected":
        lines.append("Пропуск: заметка поставлена у осмотренного блока, цитаты нет.")
    if an.ev and an.role != "inspected":
        quote = str(an.ev.get("quote") or "")
        if len(quote) > 400:
            quote = quote[:400] + "…"
        tag = f" (часть {an.part} из {an.parts})" if an.parts > 1 else ""
        lines.append(f"Цитата{tag}: «{quote}»")
        lines.append(f"Опора: блок {an.ev.get('block_id')}, символы {an.ev.get('start')}–{an.ev.get('end')}; {where}")
    else:
        lines.append(f"Место: {where}")
    if part_of:
        lines.append(part_of)
    return "\n".join(lines)


def _place_all(
    rep: dict[str, Any],
    blocks: dict[str, dict[str, Any]],
    locator: Any,
    ann: _Annotator,
) -> list[Placement]:
    req_names: dict[str, str] = {}
    for r in rep.get("requirements") or []:
        if isinstance(r, dict) and r.get("id"):
            sid = r.get("source_id")
            req_names[str(r["id"])] = f"{r['id']} ({sid})" if sid else str(r["id"])

    located: list[tuple[_Anchor, list[_Loc], Placement]] = []
    for an in _collect_anchors(rep):
        f = an.finding
        sev = _severity(f)
        base = Placement(an.fid, an.part, an.parts, an.role, sev, "skipped", "none")
        status = str(f.get("status") or "")
        if status and status not in STATUS_WORD:
            base.reason = f"статус замечания «{status}» не экспортируется"
            located.append((an, [], base))
            continue
        if an.ev is None:
            base.reason = "у замечания нет текстовой опоры и inspected_block_ids"
            located.append((an, [], base))
            continue
        bid = str(an.ev.get("block_id"))
        base.block_id = bid
        block = blocks.get(bid)
        if block is None:
            base.reason = f"блок {bid} отсутствует в report.document.blocks"
            located.append((an, [], base))
            continue
        text = str(block.get("text") or "")
        if an.role == "inspected":
            s, e = 0, len(text)
        else:
            s, e, q = _int(an.ev.get("start")), _int(an.ev.get("end")), an.ev.get("quote")
            base.start, base.end, base.quote = s, e, q
            if s is None or e is None or not 0 <= s < e <= len(text) or text[s:e] != q:
                base.reason = "опора не подтверждена: block.text[start:end] не равно quote"
                located.append((an, [], base))
                continue
        locs = locator.locate(block, s, e)
        if an.role == "inspected":
            locs = [_Loc(lc.page, [], "inspected_block", "пропуск: заметка у осмотренного блока") for lc in locs[:1]]
        located.append((an, locs, base))

    # Где оказались стороны противоречий: нужно для перекрёстных ссылок в заметках.
    first_loc: dict[tuple[str, str], tuple[_Loc, _Anchor]] = {}
    for an, locs, _ in located:
        for lc in locs:
            if lc.page is not None and (an.fid, an.role) not in first_loc:
                first_loc[(an.fid, an.role)] = (lc, an)

    # Одна видимая подпись на замечание и страницу: у F-014 восемь опор подряд, и восемь подписей
    # выталкивали подписи соседних замечаний далеко от их выделений. Каждое выделение по-прежнему
    # несёт свою полную заметку «часть k из n». Стороны противоречия подписываются отдельно.
    grouped: dict[tuple[str, int], list[int]] = defaultdict(list)
    for an, locs, _ in located:
        if an.role == "evidence":
            for lc in locs:
                if lc.page is not None and lc.rects:
                    grouped[(an.fid, lc.page)].append(an.part)
    labelled: set[tuple[str, int]] = set()

    placements: list[Placement] = []
    label_rects: dict[tuple[str, str], tuple[int, pymupdf.Rect]] = {}
    for an, locs, base in located:
        if not locs:
            placements.append(base)
            continue
        f = an.finding
        sev = base.severity
        review = str(f.get("status") or "") == "needs_review"
        other = None
        if an.role in ("a", "b"):
            o = first_loc.get((an.fid, "b" if an.role == "a" else "a"))
            if o:
                oq = str((o[1].ev or {}).get("quote") or "")
                other = f"{locator.describe(o[0], blocks.get(str((o[1].ev or {}).get('block_id')), {}))}, «{oq[:160]}»"
            else:
                other = "вторая сторона не размещена (см. сводку)"
        block = blocks.get(base.block_id or "", {})
        n_loc = len(locs)
        for li, lc in enumerate(locs):
            pl = dataclasses.replace(base, rects=[], annot_names=[])
            pl.method = lc.method
            pl.page = lc.page + 1 if lc.page is not None else None
            pl.source_ref = locator.describe(lc, block)
            part_of = f"Фрагмент цитаты {li + 1} из {n_loc} (цитата переходит на другую страницу или строку)." if n_loc > 1 else None
            content = _note_text(rep, an, sev, pl.source_ref, other, part_of, req_names)
            title = f"BCC Review · {an.fid}"
            subject = f"{SEVERITY[sev]['word']} · {f.get('criterion') or f.get('kind') or 'замечание'}"
            tag = f"{an.fid}:{an.role}:{an.part}:{li + 1}"
            extra = []
            if an.role in ("a", "b"):
                extra.append(ROLE_WORD[an.role])
            elif an.parts > 1:
                extra.append(f"часть {an.part}/{an.parts}")
            if review:
                extra.append("на проверке")
            if lc.page is None:
                pl.status = "skipped"
                pl.reason = lc.reason
                placements.append(pl)
                continue
            if lc.rects:
                pl.status = "highlight"
                shapes = [q if isinstance(q, pymupdf.Quad) else pymupdf.Rect(q).quad for q in lc.rects]
                pl.rects = [list(map(float, q.rect)) for q in shapes]
                pl.quads = [[[round(p.x, 3), round(p.y, 3)] for p in (q.ul, q.ur, q.ll, q.lr)] for q in shapes]
                ann.highlight(lc.page, shapes, sev, title, subject, content, tag)
                pl.annot_names.append(NM_PREFIX + tag)
                anchor = shapes[0].rect * ann.doc[lc.page].rotation_matrix
            else:
                pl.status = "note"
                pl.reason = lc.reason
                note_content = f"БЕЗ ТОЧНОЙ ПРИВЯЗКИ: {lc.reason}\n" + content
                anchor = ann.note(lc.page, sev, title, subject + " · без координат", note_content, tag + ":note")
                pl.annot_names.append(NM_PREFIX + tag + ":note")
                extra.append("без координат")
            group = sorted(set(grouped.get((an.fid, lc.page), []))) if pl.status == "highlight" else []
            if len(group) > 1:
                if (an.fid, lc.page) in labelled:
                    placements.append(pl)  # подпись уже стоит у первой части на этой странице
                    continue
                labelled.add((an.fid, lc.page))
                extra = [f"части {_ranges(group)} из {an.parts}"] + (["на проверке"] if review else [])
            lines = [an.fid + (f" · {extra[0]}" if extra and an.role in ("a", "b") else ""), SEVERITY[sev]["word"]]
            rest = extra[1:] if an.role in ("a", "b") else extra
            if len(group) > 1:
                lines += rest
            elif rest:
                lines.append(" · ".join(rest))
            label_text = f"{an.fid} · {SEVERITY[sev]['mark']} {SEVERITY[sev]['word']}" + (
                f" · {' · '.join(extra)}" if extra else ""
            )
            disp = ann.label(lc.page, anchor, lines, sev, review, label_text, tag + ":label")
            pl.annot_names.append(NM_PREFIX + tag + ":label")
            if (an.fid, an.role) not in label_rects:
                label_rects[(an.fid, an.role)] = (lc.page, disp)
            placements.append(pl)

    for (fid, role), (pno, rect) in list(label_rects.items()):
        if role == "a" and (fid, "b") in label_rects:
            bp, br = label_rects[(fid, "b")]
            ann.link(pno, rect, bp, br)
            ann.link(bp, br, pno, rect)
    return placements


def _ranges(nums: list[int]) -> str:
    """[1, 2, 3, 5] → «1–3, 5»."""
    out: list[tuple[int, int]] = []
    for n in nums:
        if out and out[-1][1] == n - 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return ", ".join(f"{a}–{b}" if b > a else str(a) for a, b in out)


def _summary_text(
    rep: dict[str, Any], placements: list[Placement], source_name: str, sha: str, mode: str
) -> str:
    run = rep.get("run") if isinstance(rep.get("run"), dict) else {}
    findings = [f for f in rep.get("findings") or [] if isinstance(f, dict)]
    by_status = defaultdict(int)
    for f in findings:
        by_status[str(f.get("status") or "")] += 1
    cnt = defaultdict(int)
    for p in placements:
        cnt[p.status] += 1
    head = "аннотированная копия исходного PDF" if mode == "annotated_copy" else "производная PDF-копия Markdown"
    lines = [
        f"BCC Review — {head}",
        f"Исходный файл: {source_name} (не изменён), SHA-256: {sha}",
        f"Отчёт: schema {rep.get('schema_version', '?')}, запуск {run.get('status', '?')}, "
        f"модель {run.get('model') or run.get('provider') or '?'}, агент {run.get('agent_version', '?')}",
        f"Замечаний: {len(findings)} (подтверждено {by_status['confirmed']}, требует проверки {by_status['needs_review']})",
        f"Выделений: {cnt['highlight']}; заметок без точных координат: {cnt['note']}; не размещено: {cnt['skipped']}",
        "Серьёзность продублирована словом и маркером: [!!!] КРИТИЧНО, [!!] СУЩЕСТВЕННО, [!] НЕЗНАЧИТЕЛЬНО.",
    ]
    skipped = [p for p in placements if p.status == "skipped"]
    if skipped:
        lines.append("Не размещены:")
        lines += [f" - {p.finding_id} (часть {p.part}): {p.reason}" for p in skipped[:30]]
    lines.append(f"Полный список размещений — во вложении {MANIFEST_NAME}.")
    return "\n".join(lines)


def _manifest(
    rep: dict[str, Any], placements: list[Placement], mode: str, source: Path, sha: str, extra: dict[str, Any]
) -> bytes:
    lock = _font_lock()
    data = {
        "schema": EXPORT_SCHEMA,
        "mode": mode,
        "source": {"name": source.name, "sha256": sha, "format": (rep.get("document") or {}).get("format")},
        "report": {
            "schema_version": rep.get("schema_version"),
            "run": {k: (rep.get("run") or {}).get(k) for k in ("agent_version", "provider", "model", "status", "started_at")},
        },
        "font": {"file": lock["file"], "sha256": lock["sha256"], "version": lock["font_version"], "license": "OFL-1.1"},
        "placements": [_placement_json(p) for p in placements],
        **extra,
    }
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def _placement_json(p: Placement) -> dict[str, Any]:
    d = dataclasses.asdict(p)
    d["rects"] = [[round(v, 2) for v in r] for r in p.rects]
    return d


# ---------------------------------------------------------------------------- режим PDF


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _export_annotated_copy(
    rep: dict[str, Any], src: Path, out: Path, sha: str, warnings: list[str]
) -> ExportResult:
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_bytes(src.read_bytes())
    try:
        doc = pymupdf.open(tmp)
        if not doc.is_pdf:
            raise UnsupportedFormatError("входной файл не является PDF")
        if doc.needs_pass:
            raise UnsupportedFormatError("PDF зашифрован паролем — аннотирование невозможно")
        existing = sum(1 for p in doc for _ in p.annots())
        blocks = {str(b.get("id")): b for b in (rep.get("document") or {}).get("blocks") or [] if isinstance(b, dict)}
        locator = _PdfLocator(doc, sha)
        ann = _Annotator(doc)
        placements = _place_all(rep, blocks, locator, ann)
        if ann.overlaps_text:
            warnings.append(f"{ann.overlaps_text} подпис(ей) стоят над выделением поверх текста: рядом нет свободного поля")
        summary = _summary_text(rep, placements, src.name, sha, "annotated_copy")
        p0 = doc[0]
        s = p0.add_text_annot(pymupdf.Point(8, 8) * p0.derotation_matrix, summary, icon="Comment")
        s.set_info(title="BCC Review · сводка экспорта", subject="сводка, не привязана к тексту", content=summary)
        s.set_colors(stroke=(0.2, 0.35, 0.7))
        s.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
        s.update()
        doc.xref_set_key(s.xref, "NM", pymupdf.get_pdf_str(NM_PREFIX + "summary"))
        doc.embfile_add(
            MANIFEST_NAME,
            _manifest(rep, placements, "annotated_copy", src, sha, {"existing_annotations": existing}),
            filename=MANIFEST_NAME,
            ufilename=MANIFEST_NAME,
            desc="BCC Review: размещение замечаний (страницы, прямоугольники, причины)",
        )
        ann.finalize_labels()
        incremental = bool(doc.can_save_incrementally())
        if incremental:
            doc.saveIncr()
            doc.close()
        else:
            warnings.append("PDF нельзя сохранить инкрементально (повреждённая таблица xref) — выполнено полное сохранение")
            full = out.with_name(f".{out.name}.{os.getpid()}.full")
            doc.save(full, garbage=0, deflate=True)
            doc.close()
            os.replace(full, tmp)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    with pymupdf.open(out) as d:
        pages = d.page_count
    return ExportResult(
        output_path=out,
        mode="annotated_copy",
        source_path=str(src),
        source_sha256=sha,
        output_sha256=_sha256(out),
        page_count=pages,
        saved_incrementally=incremental,
        placements=placements,
        warnings=warnings,
        missing_glyphs=missing_glyphs("".join(ann.label_chars)),
        existing_annotations=existing,
    )


# ---------------------------------------------------------------------------- режим Markdown


@dataclass
class _S:
    c: str
    line: int  # строка источника (1-based); 0 — служебный текст экспорта
    col: int
    style: str  # r | b | code | codeblock


@dataclass
class _P:
    c: str
    page: int
    rect: pymupdf.Rect
    vline: int
    line: int = 0  # строка и колонка источника (кодовые точки с 0)
    col: int = -1


_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]*)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_LIST = re.compile(r"^(\s*)([*+-]|\d{1,9}[.)])\s+(.*)$")
_QUOTE = re.compile(r"^(\s*>\s?)(.*)$")
_FENCE = re.compile(r"^\s*(```+|~~~+)")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_cells(s: str) -> list[tuple[str, int]]:
    """Ячейки строки таблицы с начальной колонкой; учитываются \\| и `код`."""
    cells: list[tuple[str, int]] = []
    i = 0
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i < n and s[i] == "|":
        i += 1
    start = i
    code = False
    while i <= n:
        ch = s[i] if i < n else "|"
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "`":
            code = not code
        elif ch == "|" and not code:
            raw = s[start:i]
            lead = len(raw) - len(raw.lstrip())
            cells.append((raw.strip(), start + lead))
            start = i + 1
        i += 1
    if cells and not cells[-1][0] and s.rstrip().endswith("|"):
        cells.pop()
    return cells


class _MdRenderer:
    W, H = 595.28, 841.89
    TOP, BOTTOM = 54.0, 841.89 - 52.0
    GUT_R = 50.0
    X0, X1 = 58.0, 595.28 - 98.0
    BODY = 9.4
    SMALL = 8.2
    GREY = (0.50, 0.50, 0.56)

    def __init__(self, doc: pymupdf.Document, chars: str, plain: bool = False, fallback: Iterable[str] = ()) -> None:
        self.doc = doc
        self.plain = plain
        key = "".join(sorted(set(chars)))
        self.fr = pymupdf.Font(fontbuffer=_build_font(key, 400))
        self.fb = pymupdf.Font(fontbuffer=_build_font(key, 700))
        self.sym = set(fallback)
        self.fs = pymupdf.Font(fontbuffer=_build_fallback("".join(sorted(self.sym)))) if self.sym else None
        self.pages = 0
        self.y = self.TOP
        self.canon: dict[int, list[_P]] = defaultdict(list)
        self.vis: dict[int, list[tuple[int, pymupdf.Rect, bool]]] = defaultdict(list)
        self.unplaced: dict[int, str] = {}
        self.ops: list[list[tuple[Any, ...]]] = []
        self.tws: list[dict[tuple[float, float, float], pymupdf.TextWriter]] = []
        self.page_lines: list[set[int]] = []
        self.vline = 0
        self._w: dict[tuple[str, str, float], float] = {}
        self.new_page()

    # -- страницы
    @property
    def pno(self) -> int:
        return self.pages - 1

    def new_page(self) -> None:
        self.doc.new_page(width=self.W, height=self.H)
        self.pages += 1
        self.ops.append([])
        self.tws.append({})
        self.page_lines.append(set())
        self.y = self.TOP

    def ensure(self, h: float) -> None:
        if self.y + h > self.BOTTOM and self.y > self.TOP + 0.5:
            self.new_page()

    def tw(self, color: tuple[float, float, float]) -> pymupdf.TextWriter:
        d = self.tws[self.pno]
        if color not in d:
            d[color] = pymupdf.TextWriter(pymupdf.Rect(0, 0, self.W, self.H), color=color)
        return d[color]

    def font(self, style: str) -> pymupdf.Font:
        if style == "sym" and self.fs is not None:
            return self.fs
        return self.fb if style == "b" else self.fr

    def eff(self, sp: _S) -> str:
        """Каким шрифтом набирать знак: резервным, если в Noto Sans его нет."""
        return "sym" if sp.c in self.sym else sp.style

    def width(self, sp: _S, size: float) -> float:
        k = (self.eff(sp), sp.c, size)
        if k not in self._w:
            self._w[k] = self.font(k[0]).text_length(sp.c, size)
        return self._w[k]

    # -- текст
    def inline(self, text: str, ln: int, col0: int, bold: bool = False) -> list[_S]:
        if self.plain:
            return [_S(c, ln, col0 + i, "b" if bold else "r") for i, c in enumerate(text)]
        out: list[_S] = []
        i, n, b, code = 0, len(text), bold, False
        while i < n:
            ch = text[i]
            st = "b" if b else "r"
            if code:
                if ch == "`":
                    code = False
                else:
                    out.append(_S(ch, ln, col0 + i, "code"))
                i += 1
                continue
            if ch == "\\" and i + 1 < n and text[i + 1] in "\\`*_{}[]()#+-.!|>~<":
                out.append(_S(text[i + 1], ln, col0 + i + 1, st))
                i += 2
                continue
            if ch == "`":
                code = True
                i += 1
                continue
            if text.startswith("**", i) or text.startswith("__", i):
                b = not b
                i += 2
                continue
            if ch == "[":
                m = _LINK.match(text, i)
                if m:
                    out += [_S(c, ln, col0 + m.start(1) + k, st) for k, c in enumerate(m.group(1))]
                    if m.group(2):
                        u0 = m.start(2)
                        out += [_S(" ", ln, col0 + u0 - 1, "r"), _S("(", ln, col0 + u0 - 1, "r")]
                        out += [_S(c, ln, col0 + u0 + k, "r") for k, c in enumerate(m.group(2))]
                        out.append(_S(")", ln, col0 + m.end(2), "r"))
                    i = m.end()
                    continue
            if ch == "*" and not text.startswith("**", i):
                opening = i + 1 < n and not text[i + 1].isspace() and "*" in text[i + 1 :]
                closing = i > 0 and not text[i - 1].isspace()
                if opening or closing:
                    i += 1
                    continue
            out.append(_S(ch, ln, col0 + i, st))
            i += 1
        return out

    @staticmethod
    def _rstrip(spans: list[_S]) -> list[_S]:
        while spans and spans[-1].c.isspace():
            spans = spans[:-1]
        return spans

    def wrap(self, spans: list[_S], width: float, size: float, keep_space: bool = False) -> list[list[_S]]:
        toks: list[list[_S]] = []
        for sp in spans:
            if toks and toks[-1][0].c.isspace() == sp.c.isspace():
                toks[-1].append(sp)
            else:
                toks.append([sp])
        lines: list[list[_S]] = []
        cur: list[_S] = []
        w = 0.0

        def has_ink(xs: list[_S]) -> bool:
            return any(not x.c.isspace() for x in xs)

        for tok in toks:
            tw_ = sum(self.width(s, size) for s in tok)
            if tok[0].c.isspace():
                if not cur and lines and not keep_space:
                    continue
                cur.extend(tok)
                w += tw_
                continue
            if w + tw_ <= width:
                cur.extend(tok)
                w += tw_
                continue
            if has_ink(cur):
                lines.append(self._rstrip(cur))
                cur, w = [], 0.0
            elif cur and not keep_space:
                cur, w = [], 0.0
            for s in tok:  # слово длиннее строки: перенос по символам
                sw = self.width(s, size)
                if w + sw > width and has_ink(cur):
                    lines.append(self._rstrip(cur))
                    cur, w = [], 0.0
                cur.append(s)
                w += sw
        if cur or not lines:
            lines.append(self._rstrip(cur))
        return lines

    def draw_line(
        self,
        spans: list[_S],
        x: float,
        baseline: float,
        size: float,
        color: tuple[float, float, float] = (0.05, 0.05, 0.07),
        repeated: bool = False,
        box_w: float | None = None,
        align: str = "left",
        ln_hint: int | None = None,
    ) -> None:
        if box_w is not None and align in ("center", "right") and spans:
            tw_ = sum(self.width(s, size) for s in spans)
            x += (box_w - tw_) * (0.5 if align == "center" else 1.0)
        self.vline += 1
        vl = self.vline
        asc, desc = self.fr.ascender, self.fr.descender
        top, bot = baseline - asc * size, baseline - desc * size
        pos = x
        per_line: dict[int, pymupdf.Rect] = {}
        i = 0
        while i < len(spans):
            j = i
            key = (self.eff(spans[i]), spans[i].style)
            while j < len(spans) and (self.eff(spans[j]), spans[j].style) == key:
                j += 1
            run = spans[i:j]
            text = "".join(s.c for s in run)
            font = self.font(key[0])
            st = key[1]
            lens = font.char_lengths(text, size)
            if st == "code":
                self.ops[self.pno].append(("rect", pymupdf.Rect(pos - 0.8, top + 0.6, pos + sum(lens) + 0.8, bot - 0.2), (0.93, 0.93, 0.95), None, 0))
            col = (0.15, 0.15, 0.30) if st in ("code", "codeblock") else color
            self.tw(col).append((pos, baseline), text, font=font, fontsize=size)
            for s, ln in zip(run, lens):
                r = pymupdf.Rect(pos, top, pos + ln, bot)
                if s.line > 0:
                    if not repeated:
                        self.canon[s.line].append(_P(s.c, self.pno, r, vl, s.line, s.col))
                    if s.line in per_line:
                        per_line[s.line] |= r
                    else:
                        per_line[s.line] = pymupdf.Rect(r)
                pos += ln
            i = j
        if not per_line and ln_hint:
            per_line[ln_hint] = pymupdf.Rect(x, top, x + 1, bot)
        for line, r in per_line.items():
            self.vis[line].append((self.pno, r, repeated))
            if not repeated:
                self.page_lines[self.pno].add(line)

    def gutter(self, ln: int, baseline: float, repeated: bool = False) -> None:
        txt = f"({ln})" if repeated else str(ln)
        size = 6.2
        w = self.fr.text_length(txt, size)
        self.tw(self.GREY).append((self.GUT_R - w, baseline), txt, font=self.fr, fontsize=size)

    def text_block(
        self,
        ln: int,
        spans: list[_S],
        size: float,
        x: float | None = None,
        color: tuple[float, float, float] = (0.05, 0.05, 0.07),
        lead_k: float = 1.38,
        marker: list[_S] | None = None,
        marker_x: float | None = None,
        bar: bool = False,
    ) -> None:
        x0 = self.X0 if x is None else x
        lead = size * lead_k
        vls = self.wrap(spans, self.X1 - x0, size)
        page_of_label = -1
        for k, vl in enumerate(vls):
            self.ensure(lead)
            baseline = self.y + size * 1.02
            if k == 0 and marker:
                self.draw_line(marker, marker_x if marker_x is not None else self.X0, baseline, size, color)
            self.draw_line(vl, x0, baseline, size, color, ln_hint=ln)
            if bar:
                self.ops[self.pno].append(("line", (self.X0 + 2, self.y), (self.X0 + 2, self.y + lead), (0.7, 0.72, 0.8), 1.6))
            if k == 0 or page_of_label != self.pno:
                # продолжение строки после разрыва страницы помечается «(ln)», как повтор шапки
                self.gutter(ln, baseline, repeated=k > 0)
                page_of_label = self.pno
            self.y += lead

    # -- блоки Markdown
    def render(self, lines: list[str], banner: list[tuple[str, bool]]) -> None:
        self.banner(banner)
        i = 0
        n = len(lines)
        while i < n:
            ln = i + 1
            s = lines[i].rstrip("\r\n")
            if self.plain:
                if s.strip():
                    self.text_block(ln, self.inline(s, ln, 0), self.BODY)
                else:
                    self.unplaced[ln] = "blank"
                    self.y += self.BODY * 0.5
                i += 1
                continue
            fence = _FENCE.match(s)
            if fence:
                mark = fence.group(1)
                body: list[tuple[int, str]] = []
                j = i + 1
                while j < n and not lines[j].strip().startswith(mark[:3]):
                    body.append((j + 1, lines[j].rstrip("\r\n")))
                    j += 1
                self.unplaced[ln] = "fence"
                if j < n:
                    self.unplaced[j + 1] = "fence"
                self.code(body)
                i = j + 1
                continue
            if not s.strip():
                self.unplaced[ln] = "blank"
                if self.y > self.TOP + 0.5:
                    self.y += self.BODY * 0.55
                i += 1
                continue
            m = _HEADING.match(s)
            if m:
                level = len(m.group(1))
                size = {1: 15.0, 2: 12.6, 3: 11.0, 4: 10.2}.get(level, 9.8)
                if self.y > self.TOP + 0.5:
                    self.y += size * 0.55
                self.ensure(size * 1.4 + self.BODY * 1.38 * 2)
                self.text_block(ln, self.inline(m.group(2), ln, m.start(2), bold=True), size, lead_k=1.3)
                if level <= 2:
                    self.ops[self.pno].append(("line", (self.X0, self.y), (self.X1, self.y), (0.75, 0.77, 0.85), 0.6))
                self.y += size * 0.25
                i += 1
                continue
            if _HR.match(s):
                self.ensure(10)
                self.ops[self.pno].append(("line", (self.X0, self.y + 5), (self.X1, self.y + 5), (0.6, 0.6, 0.65), 0.7))
                self.vis[ln].append((self.pno, pymupdf.Rect(self.X0, self.y + 4, self.X1, self.y + 6), False))
                self.page_lines[self.pno].add(ln)
                self.y += 10
                i += 1
                continue
            if s.lstrip().startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
                header = (ln, _split_cells(s))
                sep_cells = _split_cells(lines[i + 1])
                aligns = []
                for c, _ in sep_cells:
                    aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left")
                rows: list[tuple[int, list[tuple[str, int]]]] = []
                j = i + 2
                while j < n and lines[j].strip().startswith("|"):
                    rows.append((j + 1, _split_cells(lines[j].rstrip("\r\n"))))
                    j += 1
                self.table(header, i + 2, aligns, rows)
                i = j
                continue
            m = _LIST.match(s)
            if m:
                depth = len(m.group(1).expandtabs(4)) // 2
                mk = m.group(2)
                mx = self.X0 + 4 + depth * 12
                if mk in "*+-":
                    marker = [_S("•", ln, m.start(2), "r")]
                    tx = mx + 9
                else:
                    marker = [_S(c, ln, m.start(2) + k, "r") for k, c in enumerate(mk)]
                    tx = mx + self.fr.text_length(mk, self.BODY) + 4
                self.text_block(ln, self.inline(m.group(3), ln, m.start(3)), self.BODY, x=tx, marker=marker, marker_x=mx)
                i += 1
                continue
            m = _QUOTE.match(s)
            if m:
                self.text_block(ln, self.inline(m.group(2), ln, m.end(1)), self.BODY, x=self.X0 + 10, color=(0.25, 0.25, 0.32), bar=True)
                i += 1
                continue
            lead_ws = len(s) - len(s.lstrip())
            self.text_block(ln, self.inline(s.strip(), ln, lead_ws), self.BODY)
            i += 1

    def banner(self, items: list[tuple[str, bool]]) -> None:
        size = 7.5
        lead = size * 1.42
        pad = 6.0
        width = self.X1 - self.X0 - 2 * pad
        wrapped: list[tuple[list[_S], bool]] = []
        for text, bold in items:
            sp = [_S(c, 0, i, "b" if bold else "r") for i, c in enumerate(text)]
            wrapped += [(vl, bold) for vl in self.wrap(sp, width, size)]
        h = len(wrapped) * lead + 2 * pad
        self.ops[self.pno].append(("rect", pymupdf.Rect(self.X0, self.y, self.X1, self.y + h), (0.95, 0.96, 1.0), (0.45, 0.52, 0.72), 0.8))
        y = self.y + pad
        for vl, _ in wrapped:
            self.draw_line(vl, self.X0 + pad, y + size * 1.0, size, (0.12, 0.16, 0.32))
            y += lead
        self.y += h + 10

    def code(self, body: list[tuple[int, str]]) -> None:
        size = self.SMALL
        lead = size * 1.36
        self.y += 2
        for ln, text in body:
            spans = [_S(" " if c == "\t" else c, ln, k, "codeblock") for k, c in enumerate(text)]
            page_of_label = -1
            for k, vl in enumerate(self.wrap(spans, self.X1 - self.X0 - 8, size, keep_space=True)):
                self.ensure(lead)
                self.ops[self.pno].append(("rect", pymupdf.Rect(self.X0, self.y, self.X1, self.y + lead), (0.95, 0.95, 0.97), None, 0))
                baseline = self.y + size * 1.02
                self.draw_line(vl, self.X0 + 4, baseline, size, ln_hint=ln)
                if k == 0 or page_of_label != self.pno:
                    self.gutter(ln, baseline, repeated=k > 0)
                    page_of_label = self.pno
                self.y += lead
        self.y += 3

    def table(
        self,
        header: tuple[int, list[tuple[str, int]]],
        sep_ln: int,
        aligns: list[str],
        rows: list[tuple[int, list[tuple[str, int]]]],
    ) -> None:
        size = self.SMALL
        lead = size * 1.3
        pad = 3.0
        ncol = max([len(header[1])] + [len(r) for _, r in rows]) or 1
        aligns = (aligns + ["left"] * ncol)[:ncol]

        def spans_of(ln: int, cells: list[tuple[str, int]], bold: bool) -> list[list[_S]]:
            out = [self.inline(t, ln, c, bold) for t, c in cells]
            return (out + [[] for _ in range(ncol)])[:ncol]

        hsp = spans_of(header[0], header[1], True)
        rsp = [(ln, spans_of(ln, cells, False)) for ln, cells in rows]
        total_w = self.X1 - self.X0
        nat = [2 * pad + 6] * ncol
        mn = [2 * pad + 6] * ncol
        for cells in [hsp] + [c for _, c in rsp]:
            for c, sp in enumerate(cells):
                nat[c] = max(nat[c], 2 * pad + sum(self.width(s, size) for s in sp))
                word = 0.0
                for s in sp + [_S(" ", 0, 0, "r")]:
                    if s.c.isspace():
                        mn[c] = max(mn[c], min(2 * pad + word, total_w * 0.42))
                        word = 0.0
                    else:
                        word += self.width(s, size)
        if sum(nat) <= total_w:
            widths = [v * total_w / sum(nat) for v in nat]
        elif sum(mn) < total_w:
            flex = [max(0.0, a - b) for a, b in zip(nat, mn)]
            extra = total_w - sum(mn)
            tot = sum(flex) or 1.0
            widths = [b + extra * f / tot for b, f in zip(mn, flex)]
        else:
            widths = [total_w / ncol] * ncol
        xs = [self.X0]
        for w_ in widths[:-1]:
            xs.append(xs[-1] + w_)

        def wrap_row(cells: list[list[_S]]) -> list[list[list[_S]]]:
            return [self.wrap(sp, widths[c] - 2 * pad, size) if sp else [[]] for c, sp in enumerate(cells)]

        hlines = wrap_row(hsp)
        hh = max(len(x) for x in hlines) * lead + 2 * pad

        def draw_row(ln: int, cl: list[list[list[_S]]], start: int, count: int, head: bool, repeated: bool) -> None:
            h = count * lead + 2 * pad
            y0 = self.y
            if head:
                self.ops[self.pno].append(("rect", pymupdf.Rect(self.X0, y0, self.X1, y0 + h), (0.92, 0.93, 0.96), None, 0))
            for c in range(ncol):
                self.ops[self.pno].append(("rect", pymupdf.Rect(xs[c], y0, xs[c] + widths[c], y0 + h), None, (0.62, 0.64, 0.7), 0.5))
            first_base = y0 + pad + size * 1.0
            for c in range(ncol):
                for k in range(start, min(start + count, len(cl[c]))):
                    base = y0 + pad + (k - start) * lead + size * 1.0
                    self.draw_line(
                        cl[c][k], xs[c] + pad, base, size, repeated=repeated, box_w=widths[c] - 2 * pad, align=aligns[c], ln_hint=ln
                    )
            if start == 0 or repeated:
                self.gutter(ln, first_base, repeated=repeated)
            else:  # кусок строки таблицы, перенесённый на новую страницу
                self.gutter(ln, first_base, repeated=True)
            self.y = y0 + h

        def new_page_with_header() -> None:
            self.new_page()
            draw_row(header[0], hlines, 0, max(len(x) for x in hlines), True, True)

        self.y += 2
        self.ensure(hh + lead + 2 * pad)
        draw_row(header[0], hlines, 0, max(len(x) for x in hlines), True, False)
        self.unplaced[sep_ln] = "table_separator"
        cap = int((self.BOTTOM - self.TOP - hh - 2 * pad) // lead)
        for ln, cells in rsp:
            cl = wrap_row(cells)
            total = max(len(x) for x in cl) or 1
            start = 0
            while start < total:
                avail = int((self.BOTTOM - self.y - 2 * pad) // lead)
                left = total - start
                if left <= avail:
                    draw_row(ln, cl, start, left, False, False)
                    start = total
                elif left <= cap or avail < 2:
                    new_page_with_header()
                else:
                    draw_row(ln, cl, start, avail, False, False)
                    start += avail
                    new_page_with_header()
        self.y += 6

    # -- завершение
    def finalize(self) -> None:
        for pno in range(self.pages):
            page = self.doc[pno]
            shape = page.new_shape()
            for op in self.ops[pno]:
                if op[0] == "rect":
                    _, r, fill, stroke, w = op
                    shape.draw_rect(r)
                    shape.finish(color=stroke, fill=fill, width=w)
                else:
                    _, p1, p2, color, w = op
                    shape.draw_line(p1, p2)
                    shape.finish(color=color, width=w)
            shape.commit()
            for tw in self.tws[pno].values():
                tw.write_text(page)

    def furniture(self, source_name: str, sha: str) -> None:
        total = self.pages
        for pno in range(total):
            page = self.doc[pno]
            tw = pymupdf.TextWriter(page.rect, color=self.GREY)
            lines_here = sorted(self.page_lines[pno])
            rng = f"строки источника {lines_here[0]}–{lines_here[-1]}" if lines_here else "строки источника —"
            head_l = f"Производная PDF-копия · источник: {source_name} (Markdown)"
            head_r = "BCC Review · экспорт"
            foot_l = f"Страница экспорта {pno + 1} из {total}"
            foot_r = f"SHA-256 источника {sha[:16]}…"
            fs = 6.8
            tw.append((self.X0, 30), head_l, font=self.fr, fontsize=fs)
            tw.append((self.W - 24 - self.fr.text_length(head_r, fs), 30), head_r, font=self.fr, fontsize=fs)
            yb = self.H - 28
            tw.append((self.X0, yb), foot_l, font=self.fb, fontsize=fs)
            tw.append(((self.W - self.fr.text_length(rng, fs)) / 2, yb), rng, font=self.fr, fontsize=fs)
            tw.append((self.W - 24 - self.fr.text_length(foot_r, fs), yb), foot_r, font=self.fr, fontsize=fs)
            tw.write_text(page)
            shape = page.new_shape()
            shape.draw_line((self.X0, 36), (self.W - 24, 36))
            shape.draw_line((self.X0, self.H - 40), (self.W - 24, self.H - 40))
            shape.finish(color=(0.8, 0.8, 0.84), width=0.4)
            shape.commit()


class _MdLocator:
    """Опора → прямоугольники производной копии по карте вёрстки (строки Markdown)."""

    kind = "markdown"

    def __init__(self, r: _MdRenderer) -> None:
        self.r = r

    def describe(self, loc: _Loc, block: dict[str, Any]) -> str:
        rng = _block_lines(block) if block else None
        src = f"строки Markdown {rng[0]}–{rng[1]}" if rng else "строки Markdown не указаны"
        return f"{src} (стр. экспорта {loc.page + 1})" if loc.page is not None else src

    def locate(self, block: dict[str, Any], s: int, e: int) -> list[_Loc]:
        rng = _block_lines(block)
        if not rng:
            return [_Loc(None, [], "layout_map", "у блока нет номеров строк Markdown (loc)")]
        chars = [p for ln in range(rng[0], rng[1] + 1) for p in self.r.canon.get(ln, [])]
        first_page = next((v[0] for ln in range(rng[0], rng[1] + 1) for v in self.r.vis.get(ln, [])), None)
        if not chars:
            return [_Loc(first_page, [], "layout_map", f"строки {rng[0]}–{rng[1]} не содержат размещённого текста")]
        text = str(block.get("text") or "")
        chosen = self._by_loc_map(block, text, s, e, chars)
        method = "loc_map"
        if chosen is None:
            span, reason = _align(text, s, e, [p.c for p in chars])
            if span is None:
                return [_Loc(chars[0].page, [], "layout_map", reason)]
            chosen = chars[span[0] : span[1] + 1]
            method = "layout_map"
        by_page: dict[int, list[_P]] = defaultdict(list)
        for p in chosen:
            by_page[p.page].append(p)
        return [
            _Loc(pno, _line_rects((p.c, p.rect, p.vline) for p in by_page[pno]), method)
            for pno in sorted(by_page)
        ]

    @staticmethod
    def _by_loc_map(block: dict[str, Any], text: str, s: int, e: int, chars: list[_P]) -> list[_P] | None:
        """Точная привязка по ``loc.map`` контракта: позиция в block.text → (строка, колонка) исходника
        → знак, который вёрстка поставила для этой колонки. Результат принимается, только если
        выбранные знаки совпадают с цитатой; иначе — выравнивание текста в строках блока."""
        loc = block.get("loc") if isinstance(block.get("loc"), dict) else {}
        mp = loc.get("map") or []
        if not mp:
            return None
        want: dict[tuple[int, int], int] = {}
        j = 0
        for k in range(s, e):
            while j + 1 < len(mp) and mp[j + 1][0] <= k:
                j += 1
            if text[k].isspace() or mp[j][0] > k:
                continue
            want[(int(mp[j][1]), int(mp[j][2]) + k - int(mp[j][0]))] = k
        picked = [(want[(p.line, p.col)], i) for i, p in enumerate(chars) if (p.line, p.col) in want]
        if not picked:
            return None
        lo, hi = min(i for _, i in picked), max(i for _, i in picked)
        chosen = chars[lo : hi + 1]
        if _norm([p.c for p in chosen])[0] != _norm(list(text[s:e]))[0]:
            return None
        return chosen


def _export_markdown(
    rep: dict[str, Any],
    src: Path,
    out: Path,
    sha: str,
    warnings: list[str],
    plain: bool,
    strict_glyphs: bool,
) -> ExportResult:
    raw = src.read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    docmeta = rep.get("document") or {}
    run = rep.get("run") if isinstance(rep.get("run"), dict) else {}
    title = str(docmeta.get("title") or src.stem)
    n_find = len([f for f in rep.get("findings") or [] if isinstance(f, dict)])
    stamp = run.get("finished_at") or run.get("started_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    banner = [
        ("Производная PDF-версия для чтения — это не исходный документ", True),
        (f"Источник: {src.name} · {'Markdown' if not plain else 'текст'} · {len(lines)} строк · {len(raw)} байт · «{title}»", False),
        (f"SHA-256 источника: {sha}", False),
        ("Числа слева — номера строк исходного Markdown, они остаются ссылкой на место в документе. "
         "Номера внизу — страницы этого экспорта.", False),
        (f"Создано: bcc_review {run.get('agent_version', '?')} · {stamp} · замечаний в отчёте: {n_find}. "
         "Цветные выделения — нативные аннотации PDF: заметка открывается щелчком или наведением.", False),
    ]
    probe_text = (
        text
        + "".join(t for t, _ in banner)
        + f"Производная PDF-копия · источник: {src.name} (Markdown) BCC Review · экспорт Страница экспорта из "
        + f"строки источника –— SHA-256 источника {sha}…()•"
    )
    glyphs = glyph_report(probe_text)
    miss = glyphs["missing"]

    def codes(cs: list[str]) -> str:
        return ", ".join(f"{c!r} U+{ord(c):04X}" for c in cs)

    if glyphs["fallback"]:
        warnings.append(
            f"В Noto Sans нет знаков {codes(glyphs['fallback'])}: они набраны резервным Noto Sans Math из pdf_assets"
        )
    if glyphs["unrendered"]:
        if strict_glyphs:
            raise MissingGlyphError(glyphs["unrendered"], src.name)
        warnings.append(
            f"Ни в Noto Sans, ни в Noto Sans Math нет знаков {codes(glyphs['unrendered'])}: "
            "MuPDF возьмёт их из своего встроенного резервного шрифта, если найдёт"
        )
    if not _fonttools_available():
        warnings.append("fontTools не установлен: полужирный не выделен, шрифт встроен целиком без подмножества")

    doc = pymupdf.open()
    r = _MdRenderer(doc, probe_text, plain=plain, fallback=glyphs["fallback"])
    r.render(lines, banner)
    r.finalize()
    r.furniture(src.name, sha)
    # /PageLabels пишется напрямую: PyMuPDF 1.24 кодирует кириллический префикс как UTF-8 без BOM,
    # и просмотрщики показывают мусор. get_pdf_str даёт UTF-16BE с BOM в любой версии.
    doc.xref_set_key(
        doc.pdf_catalog(), "PageLabels", f"<</Nums[0<</S/D/P{pymupdf.get_pdf_str(PAGE_LABEL_PREFIX)}/St 1>>]>>"
    )
    doc.set_metadata(
        {
            "title": f"{title} — производная PDF-копия (BCC Review)",
            "author": "bcc_review",
            "subject": f"Производная копия {src.name}; sha256 источника {sha}",
            "keywords": f"bcc_review; derived-from-markdown; source={src.name}; source-sha256={sha}",
            "creator": "bcc_review.exports.pdf",
        }
    )
    blocks ={str(b.get("id")): b for b in docmeta.get("blocks") or [] if isinstance(b, dict)}
    extent = {p: (_MdRenderer.X0, _MdRenderer.X1) for p in range(r.pages)}
    ann = _Annotator(doc, extent=extent)
    placements = _place_all(rep, blocks, _MdLocator(r), ann)

    line_map: dict[str, list[dict[str, Any]]] = {}
    for ln in sorted(r.vis):
        line_map[str(ln)] = [
            {"page": p + 1, "rect": [round(v, 2) for v in rect], **({"repeated": True} if rep_ else {})}
            for p, rect, rep_ in r.vis[ln]
        ]
    for ln, kind in sorted(r.unplaced.items()):
        line_map.setdefault(str(ln), []).append({"page": None, "kind": kind})
    block_map: dict[str, dict[str, Any]] = {}
    for bid, b in blocks.items():
        rng = _block_lines(b)
        if not rng:
            continue
        pages = sorted({p for ln in range(rng[0], rng[1] + 1) for p, _, rp in r.vis.get(ln, []) if not rp})
        block_map[bid] = {"lines": list(rng), "pages": [p + 1 for p in pages]}

    summary = _summary_text(rep, placements, src.name, sha, "derived_from_markdown")
    p0 = doc[0]
    s = p0.add_text_annot(pymupdf.Point(_MdRenderer.X1 + 8, 40), summary, icon="Comment")
    s.set_info(title="BCC Review · сводка экспорта", subject="сводка, не привязана к тексту", content=summary)
    s.set_colors(stroke=(0.2, 0.35, 0.7))
    s.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
    s.update()
    doc.xref_set_key(s.xref, "NM", pymupdf.get_pdf_str(NM_PREFIX + "summary"))
    doc.embfile_add(
        MANIFEST_NAME,
        _manifest(
            rep,
            placements,
            "derived_from_markdown",
            src,
            sha,
            {"page_label_prefix": PAGE_LABEL_PREFIX, "line_map": line_map, "block_map": block_map},
        ),
        filename=MANIFEST_NAME,
        ufilename=MANIFEST_NAME,
        desc="BCC Review: карта строк Markdown → страницы экспорта и размещение замечаний",
    )
    ann.finalize_labels()
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        doc.save(tmp, garbage=3, deflate=True)
        doc.close()
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return ExportResult(
        output_path=out,
        mode="derived_from_markdown",
        source_path=str(src),
        source_sha256=sha,
        output_sha256=_sha256(out),
        page_count=r.pages,
        saved_incrementally=False,
        placements=placements,
        warnings=warnings,
        missing_glyphs=miss,
        existing_annotations=0,
        line_map=line_map,
        block_map=block_map,
        fallback_glyphs=glyphs["fallback"],
        unrendered_glyphs=glyphs["unrendered"],
    )


# ---------------------------------------------------------------------------- вход


def _detect_format(declared: Any, path: Path, head: bytes) -> str:
    d = str(declared or "").lower().lstrip(".")
    if head.startswith(b"%PDF-") or d == "pdf":
        return "pdf"
    if d in ("md", "markdown") or path.suffix.lower() in (".md", ".markdown"):
        return "md"
    if d in ("txt", "text", "plain") or path.suffix.lower() == ".txt":
        return "txt"
    return d or path.suffix.lower().lstrip(".")


def export_pdf(
    report: Any,
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    strict_glyphs: bool = False,
) -> ExportResult:
    """Построить PDF-экспорт и вернуть подробный результат (размещения, карта строк, хеши)."""
    rep = _as_report_dict(report)
    src = Path(input_path)
    out = Path(output_path)
    if out.resolve() == src.resolve():
        raise ValueError("output_path совпадает с input_path: исходный файл не перезаписывается")
    out.parent.mkdir(parents=True, exist_ok=True)
    sha = _sha256(src)
    docmeta = rep.get("document") or {}
    run = rep.get("run") if isinstance(rep.get("run"), dict) else {}
    expected = [x for x in (docmeta.get("id"), run.get("source_sha256")) if x]
    if not expected:
        raise SourceMismatchError("в отчёте нет document.id / run.source_sha256 — нельзя убедиться, что это тот же файл")
    for x in expected:
        if str(x).lower() != sha:
            raise SourceMismatchError(f"SHA-256 входного файла {sha} не совпадает с отчётом ({x})")
    with src.open("rb") as fh:
        head = fh.read(8)
    fmt = _detect_format(docmeta.get("format"), src, head)
    warnings: list[str] = []
    if fmt == "pdf":
        result = _export_annotated_copy(rep, src, out, sha, warnings)
    elif fmt in ("md", "txt"):
        result = _export_markdown(rep, src, out, sha, warnings, plain=fmt == "txt", strict_glyphs=strict_glyphs)
    else:
        raise UnsupportedFormatError(f"PDF-экспорт поддерживает PDF и Markdown/TXT, получено: {fmt or 'неизвестно'}")
    if _sha256(src) != sha:  # pragma: no cover - защитная проверка
        raise RuntimeError("исходный файл изменился во время экспорта")
    return result


def write_pdf(report: Any, input_path: str | os.PathLike[str], output_path: str | os.PathLike[str]) -> Path:
    """Контрактная точка входа: аннотированная копия PDF или производный PDF из Markdown."""
    return export_pdf(report, input_path, output_path).output_path


# ---------------------------------------------------------------------------- проверка


def read_annotations(pdf_path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Повторно открыть PDF и вернуть все аннотации: страница, тип, NM, тексты, quads."""
    out: list[dict[str, Any]] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            for a in page.annots():
                info = a.info
                rec: dict[str, Any] = {
                    "page": page.number + 1,
                    "type": a.type[1],
                    "name": info.get("id") or "",
                    "title": info.get("title") or "",
                    "subject": info.get("subject") or "",
                    "content": info.get("content") or "",
                    "rect": [round(v, 2) for v in a.rect],
                    "xref": a.xref,
                }
                if a.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT:
                    v = a.vertices or []
                    rec["quads"] = [
                        [round(c, 2) for c in pymupdf.Quad(v[i : i + 4]).rect] for i in range(0, len(v) - 3, 4)
                    ]
                    # вершины как есть (ul, ur, ll, lr): у наклонного текста это не прямоугольник
                    rec["quad_points"] = [[[round(c, 3) for c in pt] for pt in v[i : i + 4]] for i in range(0, len(v) - 3, 4)]
                    rec["color"] = list(a.colors.get("stroke") or [])
                    rec["has_popup"] = bool(a.has_popup)
                out.append(rec)
            for lk in page.get_links():
                out.append({"page": page.number + 1, "type": "Link", "name": "", "to_page": lk.get("page", -1) + 1,
                            "rect": [round(v, 2) for v in lk["from"]]})
    return out


def page_label(doc: pymupdf.Document, pno: int) -> str:
    """Метка страницы. PyMuPDF 1.24 возвращает UTF-16 префикс как «<FEFF…>», здесь он декодируется."""
    label = doc[pno].get_label()
    m = re.fullmatch(r"<[fF][eE][fF][fF]([0-9a-fA-F]*)>(.*)", label, re.S)
    return bytes.fromhex(m.group(1)).decode("utf-16-be") + m.group(2) if m else label


def _annot_key(a: dict[str, Any]) -> tuple[Any, ...]:
    return (a["page"], a["type"], tuple(round(v) for v in a["rect"]), a.get("content", ""))


def verify_export(
    output_path: str | os.PathLike[str], source_path: str | os.PathLike[str], report: Any
) -> dict[str, Any]:
    """Независимая перепроверка готового экспорта: годится для приёмки №18 и CI."""
    rep = _as_report_dict(report)
    out, src = Path(output_path), Path(source_path)
    errors: list[str] = []
    checks: dict[str, Any] = {}
    sha = _sha256(src)
    checks["source_sha256"] = sha
    checks["source_matches_report"] = sha == str((rep.get("document") or {}).get("id", "")).lower()
    if not checks["source_matches_report"]:
        errors.append("SHA-256 исходника не совпадает с report.document.id")
    with pymupdf.open(out) as d:
        files = d.embfile_names()
        manifest = json.loads(d.embfile_get(MANIFEST_NAME)) if MANIFEST_NAME in files else None
        checks["manifest"] = manifest is not None
        if manifest is None:
            errors.append(f"нет вложения {MANIFEST_NAME}")
        mode = (manifest or {}).get("mode")
        checks["mode"] = mode
        if mode == "annotated_copy":
            with pymupdf.open(src) as s:
                checks["page_count_equal"] = s.page_count == d.page_count
                n = min(s.page_count, d.page_count)
                # 1) content stream каждой страницы совпадает байт в байт;
                # 2) каждое исходное слово стоит на прежнем месте. MuPDF добавляет к get_text()
                #    текст FreeText-подписей, поэтому проверяется вложение, а не равенство.
                same_streams = all(s[i].read_contents() == d[i].read_contents() for i in range(n))
                words_kept = True
                for i in range(n):
                    have = {(w[4], tuple(round(v, 1) for v in w[:4])) for w in d[i].get_text("words")}
                    if any((w[4], tuple(round(v, 1) for v in w[:4])) not in have for w in s[i].get_text("words")):
                        words_kept = False
                        break
                checks["content_streams_identical"] = same_streams
                checks["source_words_preserved"] = words_kept
                if not (same_streams and words_kept and checks["page_count_equal"]):
                    errors.append("содержимое страниц копии отличается от исходника")
            src_bytes = src.read_bytes()
            with out.open("rb") as fh:
                checks["source_bytes_prefix"] = fh.read(len(src_bytes)) == src_bytes
        else:
            labels = [page_label(d, i) for i in range(d.page_count)]
            checks["page_labels"] = labels
            if not all(lb.startswith(PAGE_LABEL_PREFIX) for lb in labels):
                errors.append("страницы производной копии не подписаны как страницы экспорта")
    annots = read_annotations(out)
    names = {a["name"]: a for a in annots if a.get("name")}
    if mode == "annotated_copy":
        before = {_annot_key(a) for a in read_annotations(src) if a["type"] != "Link"}
        after = {_annot_key(a) for a in annots if a["type"] != "Link"}
        checks["existing_annotations_preserved"] = before <= after
        if not before <= after:
            errors.append("часть исходных аннотаций пропала или изменилась")
    missing: list[str] = []
    for p in (manifest or {}).get("placements", []):
        for nm in p.get("annot_names") or []:
            a = names.get(nm)
            if a is None or a["page"] != p.get("page"):
                missing.append(nm)
                continue
            if p.get("status") == "highlight" and nm.count(":") == 4:
                # вершины Highlight против записанных четырёхугольников (или рамок у старых манифестов)
                if p.get("quads"):
                    got = [[c for pt in q for c in pt] for q in a.get("quad_points") or []]
                    want = [[c for pt in q for c in pt] for q in p["quads"]]
                else:
                    got, want = a.get("quads") or [], p.get("rects") or []
                if len(got) != len(want) or any(
                    max(abs(x - y) for x, y in zip(g, w)) > 1.0 for g, w in zip(got, want)
                ):
                    missing.append(nm + " (quads)")
    checks["placed_annotations_found"] = not missing
    if missing:
        errors.append("не найдены или сдвинуты аннотации: " + ", ".join(missing[:10]))
    checks["highlights"] = sum(1 for a in annots if a["type"] == "Highlight" and a["name"].startswith(NM_PREFIX))
    return {"ok": not errors, "checks": checks, "errors": errors}


def render_page_png(
    pdf_path: str | os.PathLike[str], page_number: int, out_png: str | os.PathLike[str], dpi: int = 110
) -> Path:
    """Отрисовать страницу (1-based) вместе с аннотациями в PNG."""
    with pymupdf.open(pdf_path) as d:
        d[page_number - 1].get_pixmap(dpi=dpi, annots=True).save(str(out_png))
    return Path(out_png)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.exports.pdf", description="PDF-экспорт отчёта BCC Review")
    ap.add_argument("report", help="report.json (Report v1)")
    ap.add_argument("source", help="исходный PDF или Markdown, по которому построен отчёт")
    ap.add_argument("output", help="путь выходного PDF")
    ap.add_argument("--render", type=int, metavar="PAGE", help="отрисовать страницу в PNG рядом с PDF")
    ap.add_argument("--strict-glyphs", action="store_true", help="ошибка, если в шрифте нет нужного знака")
    a = ap.parse_args(argv)
    res = export_pdf(a.report, a.source, a.output, strict_glyphs=a.strict_glyphs)
    summary = res.summary()
    summary["verify"] = verify_export(res.output_path, a.source, a.report)
    if a.render:
        summary["png"] = str(render_page_png(res.output_path, a.render, Path(a.output).with_suffix(f".p{a.render}.png")))
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return 0 if summary["verify"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
