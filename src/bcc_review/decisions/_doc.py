"""Общие помощники модуля решений (№08).

Здесь нет бизнес-логики: только безопасный доступ к объектам контракта v1
(dict, pydantic-модель или dataclass — без жёсткой зависимости от моделей
движка), поиск опор, форматирование координат и защита от вымышленных
значений в редакции.

``load_markdown`` — запасной минимальный загрузчик Markdown по контракту
Document v1. Он нужен, пока bootstrap ``bcc/integration`` не опубликован, и
для офлайн-демо. Основной загрузчик движка имеет приоритет (см. ``load_document``).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# Доступ к полям
# ---------------------------------------------------------------------------


def get(obj: Any, key: str, default: Any = None) -> Any:
    """Поле объекта контракта: dict, pydantic-модель или dataclass."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    return list(value)


def to_plain(obj: Any) -> Any:
    """Рекурсивно превращает объект контракта в JSON-совместимую структуру."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Mapping):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_plain(v) for v in obj]
    if hasattr(obj, "to_dict"):
        return to_plain(obj.to_dict())
    if hasattr(obj, "model_dump"):
        return to_plain(obj.model_dump())
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_plain(getattr(obj, k)) for k in obj.__dataclass_fields__}
    return str(obj)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def short_sha(sha: str | None) -> str:
    return (sha or "—")[:12]


# ---------------------------------------------------------------------------
# Представление документа
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockView:
    id: str
    kind: str
    section: tuple[str, ...]
    text: str
    loc: Any
    index: int

    @classmethod
    def of(cls, block: Any, index: int) -> "BlockView":
        section = get(block, "section") or []
        if isinstance(section, str):
            section = [section]
        return cls(
            id=str(get(block, "id")),
            kind=str(get(block, "kind") or "paragraph"),
            section=tuple(str(s) for s in section),
            text=str(get(block, "text") or ""),
            loc=get(block, "loc"),
            index=index,
        )


class DocView:
    """Только чтение: документ контракта v1 в удобном виде."""

    def __init__(self, document: Any):
        if isinstance(document, DocView):
            document = document.raw
        self.raw = document
        self.id: str | None = get(document, "id")
        self.title: str = str(get(document, "title") or "")
        self.format: str = str(get(document, "format") or "").lower()
        self.blocks: list[BlockView] = [
            BlockView.of(b, i) for i, b in enumerate(as_list(get(document, "blocks")))
        ]
        self._by_id = {b.id: b for b in self.blocks}

    def block(self, block_id: str | None) -> BlockView | None:
        if block_id is None:
            return None
        return self._by_id.get(str(block_id))

    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    def find_quote(self, quote: str, block_id: str | None = None) -> list[tuple[BlockView, int]]:
        """Все точные вхождения цитаты: [(блок, start)]."""
        hits: list[tuple[BlockView, int]] = []
        blocks = [self.block(block_id)] if block_id else self.blocks
        for b in blocks:
            if b is None or not quote:
                continue
            start = b.text.find(quote)
            while start != -1:
                hits.append((b, start))
                start = b.text.find(quote, start + 1)
        return hits

    def evidence(self, quote: str, block_id: str | None = None) -> dict | None:
        """Evidence {block_id, start, end, quote}, если цитата однозначна."""
        hits = self.find_quote(quote, block_id)
        if len(hits) != 1:
            return None
        b, start = hits[0]
        return {"block_id": b.id, "start": start, "end": start + len(quote), "quote": quote}

    def verify_evidence(self, ev: Any) -> bool:
        b = self.block(get(ev, "block_id"))
        if b is None:
            return False
        start, end, quote = get(ev, "start"), get(ev, "end"), get(ev, "quote")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        return b.text[start:end] == quote


# ---------------------------------------------------------------------------
# Координаты
# ---------------------------------------------------------------------------


def loc_lines(loc: Any) -> tuple[int, int] | None:
    """Диапазон строк (с 1) из loc любого вида: dict, строка "L12-L14", число."""
    if loc is None:
        return None
    if isinstance(loc, int):
        return (loc, loc)
    if isinstance(loc, str):
        m = re.match(r"\s*L?(\d+)(?:\s*[-–]\s*L?(\d+))?", loc)
        if m:
            a = int(m.group(1))
            return (a, int(m.group(2) or a))
        return None
    if isinstance(loc, (list, tuple)) and loc and all(isinstance(x, int) for x in loc):
        return (loc[0], loc[-1])
    for a_key, b_key in (("line_start", "line_end"), ("start_line", "end_line"), ("line", "line")):
        a = get(loc, a_key)
        if isinstance(a, int):
            b = get(loc, b_key)
            return (a, b if isinstance(b, int) else a)
    lines = get(loc, "lines")
    if isinstance(lines, (list, tuple)) and lines:
        return (int(lines[0]), int(lines[-1]))
    return None


def format_loc(block: BlockView | None, start: int | None = None, end: int | None = None) -> str:
    """Человекочитаемая координата: «строка 21 · блок b0021 · символы 6–51»."""
    if block is None:
        return "место не найдено"
    parts: list[str] = []
    loc = block.loc
    lines = loc_lines(loc)
    page = get(loc, "page") if isinstance(loc, Mapping) or hasattr(loc, "page") else None
    path = get(loc, "path") if isinstance(loc, Mapping) or hasattr(loc, "path") else None
    if lines:
        parts.append(f"строка {lines[0]}" if lines[0] == lines[1] else f"строки {lines[0]}–{lines[1]}")
    elif page:
        parts.append(f"стр. {page}")
    elif path:
        parts.append(f"путь {path}")
    elif loc is not None:
        parts.append(f"loc {loc}")
    parts.append(f"блок {block.id}")
    if start is not None and end is not None:
        parts.append(f"символы {start}–{end}")
    if block.section:
        parts.append("раздел «" + " / ".join(block.section) + "»")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Защита от вымышленных значений (SLA, лимиты, суммы, сроки)
# ---------------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_UNIT = (
    r"%|‰|₸|\$|€|тенге|тг\b|kzt|usd|eur|тиын\w*|руб\w*|"
    r"рабоч\w*\s+д\w*|календарн\w*\s+д\w*|банковск\w*\s+д\w*|"
    r"дн\w*|день|сут\w*|час\w*|ч\b|мин\w*|сек\w*|мс\b|ms\b|"
    r"недел\w*|месяц\w*|мес\b|год\w*|лет\b|раз\w*|запрос\w*|rps|tps|процент\w*"
)
_NUM_UNIT_RE = re.compile(rf"(?<![\w.,])({_NUM})(?:\s*({_UNIT}))?", re.IGNORECASE)


def _norm_number(raw: str) -> str:
    s = re.sub(r"[   ]", "", raw).replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    s = s.lstrip("0") or "0"
    return s


def _norm_unit(raw: str | None) -> str:
    if not raw:
        return ""
    u = raw.lower()
    for prefix, name in (
        ("рабоч", "workday"), ("календарн", "day"), ("банковск", "bankday"),
        ("дн", "day"), ("день", "day"), ("сут", "day"), ("час", "hour"), ("ч", "hour"),
        ("мин", "min"), ("сек", "sec"), ("мс", "ms"), ("ms", "ms"), ("недел", "week"),
        ("месяц", "month"), ("мес", "month"), ("год", "year"), ("лет", "year"),
        ("раз", "times"), ("запрос", "rps"), ("rps", "rps"), ("tps", "rps"),
        ("процент", "%"), ("%", "%"), ("‰", "‰"), ("₸", "kzt"), ("тенге", "kzt"),
        ("тг", "kzt"), ("kzt", "kzt"), ("тиын", "tiyn"), ("руб", "rub"),
        ("$", "usd"), ("usd", "usd"), ("€", "eur"), ("eur", "eur"),
    ):
        if u.startswith(prefix):
            return name
    return u


def quantities(text: str) -> set[tuple[str, str]]:
    """Числа с единицами: {("1000", "kzt"), ("6", "month"), ("2", "")}."""
    return {(_norm_number(m.group(1)), _norm_unit(m.group(2))) for m in _NUM_UNIT_RE.finditer(text or "")}


def invented_values(new: str, old: str, allowed_texts: Iterable[str]) -> list[str]:
    """Значения из ``new``, которых нет ни в старом фрагменте, ни в разрешённых
    текстах (документ, ответ владельца).

    Число без единицы разрешено, если такое число встречается в источниках.
    Число с единицей разрешено только в паре с той же единицей: «6 месяцев» из
    документа не узаконивает «6 рабочих дней» в редакции.
    """
    allowed: set[tuple[str, str]] = set(quantities(old))
    for t in allowed_texts:
        allowed |= quantities(t)
    allowed_numbers = {n for n, _ in allowed}
    bad: list[str] = []
    for m in _NUM_UNIT_RE.finditer(new or ""):
        num, unit = _norm_number(m.group(1)), _norm_unit(m.group(2))
        ok = (num, unit) in allowed if unit else num in allowed_numbers
        if not ok:
            token = m.group(0).strip()
            if token not in bad:
                bad.append(token)
    return bad


# ---------------------------------------------------------------------------
# Буквы вариантов
# ---------------------------------------------------------------------------

# Варианты обозначаются латиницей A–F. Кириллические двойники (А, В, С, Е)
# читаются по начертанию; «Б» — вторая буква алфавита, читается как B.
_CYR_TO_LAT = {"А": "A", "В": "B", "Б": "B", "С": "C", "Е": "E", "а": "A", "в": "B",
               "б": "B", "с": "C", "е": "E"}


def option_letter(raw: str | None) -> str | None:
    """«A», «a», «А» (кириллица), «Вариант B» → буква варианта; иначе None."""
    if not raw:
        return None
    s = raw.strip()
    m = re.match(r"^(?:вариант|option)\s*", s, re.IGNORECASE)
    if m:
        s = s[m.end():]
    if len(s) != 1:
        return None
    s = _CYR_TO_LAT.get(s, s).upper()
    return s if s in "ABCDEF" else None


# ---------------------------------------------------------------------------
# Нормализация текста для сопоставления
# ---------------------------------------------------------------------------


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace(" ", " ").replace("ё", "е").replace("Ё", "Е")
    s = re.sub(r"[*_`]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------------------
# Запасной загрузчик Markdown (контракт Document v1)
# ---------------------------------------------------------------------------

_LIST_RE = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _strip_inline(s: str) -> str:
    return s.replace("**", "").replace("__", "").strip()


def _loc_map(text: str, lines: list[str], a: int, b: int) -> list[list[int]]:
    """loc.map контракта v1: [[text_start, line, col], ...] — с позиции text_start
    символы block.text идут подряд с (line, col) исходника."""
    pos: list[tuple[int, int]] = [(ln, c) for ln in range(a, b + 1) for c in range(len(lines[ln - 1]) + 1)]
    flat = "\n".join(lines[a - 1: b])
    out: list[list[int]] = []
    j, prev = 0, None
    for i, ch in enumerate(text):
        while j < len(flat) and not (flat[j] == ch or (ch.isspace() and flat[j].isspace())):
            j += 1
        if j >= len(flat):
            return out
        cur = pos[j]
        if prev is None or cur[0] != prev[0] or cur[1] != prev[1] + 1:
            out.append([i, cur[0], cur[1]])
        prev = cur
        j += 1
    return out


def markdown_to_document(data: bytes, title: str | None = None) -> dict:
    """Минимальный разбор Markdown в Document v1: заголовки, абзацы, пункты
    списков, строки таблиц, блоки кода. Строки нумеруются с 1."""
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []
    doc_title = title
    para: list[tuple[int, str]] = []
    in_code: tuple[int, list[str]] | None = None

    def section() -> list[str]:
        return [t for _, t in stack]

    def add(kind: str, text_: str, a: int, b: int) -> None:
        blocks.append({
            "id": "", "kind": kind, "section": section(), "text": text_,
            "loc": {"line_start": a, "line_end": b, "map": _loc_map(text_, lines, a, b)},
        })

    def flush_para() -> None:
        nonlocal para
        if para:
            add("paragraph", " ".join(_strip_inline(t) for _, t in para), para[0][0], para[-1][0])
            para = []

    for no, line in enumerate(lines, start=1):
        if in_code is not None:
            if line.strip().startswith("```"):
                a, body = in_code
                add("code", "\n".join(body), a, no)
                in_code = None
            else:
                in_code[1].append(line)
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            in_code = (no, [])
            continue
        if not stripped or stripped == "---":
            flush_para()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level, heading = len(m.group(1)), _strip_inline(m.group(2))
            while stack and stack[-1][0] >= level:
                stack.pop()
            add("heading", heading, no, no)
            stack.append((level, heading))
            if doc_title is None and level == 1:
                doc_title = heading
            continue
        if stripped.startswith("|"):
            flush_para()
            if _TABLE_SEP_RE.match(stripped):
                continue
            cells = [_strip_inline(c) for c in stripped.strip("|").split("|")]
            header = no < len(lines) and bool(_TABLE_SEP_RE.match(lines[no].strip()))
            add("table_header" if header else "table_row", " | ".join(cells), no, no)
            continue
        if _LIST_RE.match(line):
            flush_para()
            add("list_item", _strip_inline(_LIST_RE.sub("", line, count=1)), no, no)
            continue
        para.append((no, stripped))
    flush_para()
    for n, b in enumerate(blocks, start=1):  # b0001, b0002… в порядке чтения (контракт v1)
        b["id"] = f"b{n:04d}"
    return {
        "id": sha256_bytes(data),
        "title": doc_title or "Без названия",
        "format": "markdown",
        "blocks": blocks,
        "warnings": [],
    }


def load_markdown(path: str | Path) -> dict:
    return markdown_to_document(Path(path).read_bytes())


def load_document(path: str | Path) -> Any:
    """Загрузить документ: сначала загрузчиком движка, иначе запасным для MD/TXT."""
    path = Path(path)
    suffix = path.suffix.lower()
    readers = [("bcc_review.readers.text", "read_text")] if suffix in {".md", ".markdown", ".txt"} else []
    readers += {".pdf": [("bcc_review.readers.pdf", "read_pdf")],
                ".docx": [("bcc_review.readers.docx", "read_docx")]}.get(suffix, [])
    # точки входа читателей №01–03 по contracts/HANDOFF.md
    for mod_name, fn_name in readers:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
        except (ImportError, AttributeError):
            continue
        doc = fn(path)
        try:  # как движок: читатель может вернуть dataclass — приводим к Document v1 (dict)
            from bcc_review.contracts import normalize_document
        except ImportError:
            return doc
        return normalize_document(doc)
    if path.suffix.lower() in {".md", ".markdown", ".txt"}:
        return load_markdown(path)
    raise RuntimeError(
        f"Нет загрузчика для {path.name}: запасной загрузчик модуля решений "
        "читает только Markdown/TXT, остальные форматы читает движок."
    )
