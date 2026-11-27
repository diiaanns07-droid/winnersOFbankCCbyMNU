"""Банковский чек-лист «Ревью требований» (направление №10).

Строки берутся из таблицы входного документа. Исходный порядок, исходный текст
проверки и допустимые отметки каждой ячейки сохраняются. Для каждой строки
раздельно определяются три состояния:

* ``presence`` — описано ли в документе то, о чём спрашивает строка (с опорой);
* ``machine`` — машинная проверка свойства по подтверждённым замечаниям;
* ``approval`` — согласование человеком. Без записи о согласовании оно остаётся
  неопределённым с примечанием «требует подтверждения».

Публичный вход: :func:`build_bank_pack` (чек-лист и приёмочные сценарии вместе).
Все объекты контракта принимаются и как ``dict``, и как объекты с атрибутами.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

AskFn = Callable[[str, dict, dict], dict]

PACK_VERSION = "p10-bank/1"

# ---------------------------------------------------------------- доступ к данным


def g(obj: Any, key: str, default: Any = None) -> Any:
    """Поле объекта контракта: dict или объект с атрибутами."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


class BankWarning(str):
    """Предупреждение пакета: строка контракта Warning (русское сообщение) с кодом и данными.

    Движок нормализует выход модуля ``contracts.as_plain`` и пишет ``str(w)`` в Report.warnings;
    строка переживает обе операции. Префикс «bank:» получают только отказы модели — по нему
    движок помечает этап ``bank`` частичным. Код и данные доступны как ``w.code``, ``w["code"]``,
    ``w.get("level")``.
    """

    DEGRADING = frozenset({"bank.llm_failed"})
    code: str
    level: str
    data: dict[str, Any]

    def __new__(cls, code: str, message: str, level: str = "warning", **data: Any) -> "BankWarning":
        text = f"bank: {message}" if code in cls.DEGRADING else message
        obj = super().__new__(cls, text)
        obj.code, obj.level, obj.data = code, level, {k: v for k, v in data.items() if v is not None}
        return obj

    @property
    def message(self) -> str:
        return str.__str__(self)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "level": self.level, "message": self.message, "stage": "bank", **self.data}

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            return self.as_dict()[key]
        return str.__getitem__(self, key)


def W(code: str, message: str, level: str = "warning", **extra: Any) -> BankWarning:
    """Предупреждение пакета: код, уровень, русское сообщение и данные."""
    return BankWarning(code, message, level, **extra)


# ---------------------------------------------------------------- нормализация текста

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "«»„“”‟″"), '"')
_SKIP_CHARS = frozenset("*`")


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Нормализованный текст и индекс исходного символа для каждого символа.

    Сравнение без регистра, без ``*`` и обратных кавычек Markdown, с ``ё = е``,
    едиными тире и кавычками и схлопнутыми пробелами. Каждый исходный символ
    даёт не больше одного нормализованного, поэтому координаты восстанавливаются.
    """
    out: list[str] = []
    idx: list[int] = []
    space = True
    for i, ch in enumerate(text):
        if ch in _SKIP_CHARS:
            continue
        if ch.isspace():
            if not space:
                out.append(" ")
                idx.append(i)
                space = True
            continue
        space = False
        c = ch.lower()
        if len(c) != 1:
            c = ch
        if c == "ё":
            c = "е"
        c = c.translate(_DASHES).translate(_QUOTES)
        out.append(c)
        idx.append(i)
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def norm(text: Any) -> str:
    return _norm_map(str(text or ""))[0]


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    """Координаты цитаты в тексте блока: точно, затем по нормализованному тексту."""
    if not quote or not text:
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    stripped = quote.strip()
    if stripped and stripped != quote:
        i = text.find(stripped)
        if i >= 0:
            return i, i + len(stripped)
    nt, idx = _norm_map(text)
    nq = norm(quote)
    if not nq:
        return None
    j = nt.find(nq)
    if j < 0:
        return None
    return idx[j], idx[j + len(nq) - 1] + 1


def norm_search(pattern: re.Pattern[str] | str, text: str) -> tuple[int, int] | None:
    """Поиск регулярного выражения в нормализованном тексте → исходные координаты."""
    nt, idx = _norm_map(text)
    m = re.search(pattern, nt) if isinstance(pattern, str) else pattern.search(nt)
    if not m or m.end() <= m.start():
        return None
    return idx[m.start()], idx[m.end() - 1] + 1


_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[«\"(\[*]*[A-ZА-ЯЁ0-9])|\n+")


def sentences(text: str) -> list[tuple[int, int]]:
    """Предложения (и строки) блока с координатами в кодовых точках."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENT_SPLIT.finditer(text):
        spans.append(_trim(text, pos, m.start()))
        pos = m.end()
    spans.append(_trim(text, pos, len(text)))
    return [s for s in spans if s[1] > s[0]]


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def short(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip(",;:") + "…"


# ---------------------------------------------------------------- документ


class Block:
    __slots__ = ("id", "kind", "section", "text", "loc", "order", "_norm")

    def __init__(self, bid: str, kind: str, section: list[str], text: str, loc: Any, order: int):
        self.id = bid
        self.kind = kind
        self.section = section
        self.text = text
        self.loc = loc
        self.order = order
        self._norm: str | None = None

    @property
    def ntext(self) -> str:
        if self._norm is None:
            self._norm = norm(self.text)
        return self._norm

    @property
    def is_heading(self) -> bool:  # table_header — строка таблицы, не заголовок раздела
        return self.kind.startswith("heading") or self.kind in {"title", "h1", "h2", "h3", "h4", "h5", "h6"}

    @property
    def is_code(self) -> bool:
        return "code" in self.kind or self.text.lstrip().startswith("```")

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"Block({self.id!r}, {self.kind!r}, {self.text[:30]!r})"


class Doc:
    """Индекс документа контракта v1: блоки по порядку, по id, опоры и места."""

    def __init__(self, document: Any):
        self.source = document
        self.id = g(document, "id")
        self.title = str(g(document, "title") or "")
        self.format = str(g(document, "format") or "")
        self.blocks: list[Block] = []
        for i, b in enumerate(as_list(g(document, "blocks"))):
            sec = g(b, "section") or []
            if isinstance(sec, str):
                sec = [sec]
            self.blocks.append(
                Block(
                    str(g(b, "id", f"b{i}")),
                    str(g(b, "kind", "") or "").lower(),
                    [str(s) for s in sec],
                    str(g(b, "text", "") or ""),
                    g(b, "loc"),
                    i,
                )
            )
        self.by_id = {b.id: b for b in self.blocks}

    # --- опоры
    def ev(self, block: Block, start: int, end: int) -> dict:
        return {"block_id": block.id, "start": start, "end": end, "quote": block.text[start:end]}

    def ev_valid(self, ev: Any) -> bool:
        b = self.by_id.get(str(g(ev, "block_id")))
        s, e, q = g(ev, "start"), g(ev, "end"), g(ev, "quote")
        return bool(b) and isinstance(s, int) and isinstance(e, int) and b.text[s:e] == q

    def locate(self, quote: str, block_ids: Iterable[str] | None = None) -> dict | None:
        """Опора по цитате: сначала в указанных блоках, затем во всём документе."""
        ids = [i for i in (block_ids or []) if i in self.by_id]
        pools = [[self.by_id[i] for i in ids]] if ids else []
        pools.append(self.blocks)
        for pool in pools:
            for b in pool:
                sp = find_span(b.text, quote)
                if sp:
                    return self.ev(b, *sp)
        return None

    def from_hint(self, hint: Any) -> dict | None:
        """Hint = {block_id, quote} → проверенная Evidence или None."""
        quote = str(g(hint, "quote") or "")
        bid = g(hint, "block_id")
        if not quote.strip():
            return None
        b = self.by_id.get(str(bid)) if bid is not None else None
        if b is not None:
            sp = find_span(b.text, quote)
            return self.ev(b, *sp) if sp else None
        return None

    def evidence_of(self, obj: Any) -> list[dict]:
        """Проверенные опоры объекта: evidence, затем hints."""
        out: list[dict] = []
        for ev in as_list(g(obj, "evidence")):
            if self.ev_valid(ev):
                out.append(
                    {"block_id": str(g(ev, "block_id")), "start": g(ev, "start"), "end": g(ev, "end"), "quote": g(ev, "quote")}
                )
            else:
                fixed = self.from_hint(ev)
                if fixed:
                    out.append(fixed)
        for h in as_list(g(obj, "hints")):
            fixed = self.from_hint(h)
            if fixed:
                out.append(fixed)
        return out

    # --- места
    def label(self, ev: Any) -> str:
        b = self.by_id.get(str(g(ev, "block_id")))
        if b is None:
            return "место не найдено"
        return loc_label(b, int(g(ev, "start") or 0))


def loc_label(block: Block, start: int = 0) -> str:
    """Человеческое место: «строка N» для Markdown, «с. N» для PDF, путь для DOCX."""
    loc = block.loc
    base: int | None = None
    if isinstance(loc, Mapping):
        for k in ("line", "start_line", "line_start", "first_line"):
            if isinstance(loc.get(k), int):
                base = loc[k]
                break
        if base is None and isinstance(loc.get("lines"), (list, tuple)) and loc["lines"]:
            first = loc["lines"][0]
            base = first if isinstance(first, int) else None
        if base is None and isinstance(loc.get("page"), int):
            return f"с. {loc['page']}"
        if base is None and loc.get("path"):
            return str(loc["path"])
    elif isinstance(loc, int):
        base = loc
    elif isinstance(loc, str) and loc:
        return loc
    if base is None:
        return f"блок {block.id}"
    nl = "\n"
    return f"строка {base + block.text.count(nl, 0, start)}"


# ---------------------------------------------------------------- таблицы


@dataclass
class Cell:
    block: Block
    start: int
    end: int

    @property
    def text(self) -> str:
        return self.block.text[self.start : self.end]

    @property
    def ntext(self) -> str:
        return norm(self.text)


@dataclass
class Table:
    rows: list[list[Cell]]
    blocks: list[Block]

    @property
    def header(self) -> list[Cell]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> list[list[Cell]]:
        return self.rows[1:]

    @property
    def section(self) -> list[str]:
        return self.blocks[0].section if self.blocks else []

    @property
    def block_ids(self) -> set[str]:
        return {b.id for b in self.blocks}

    def col(self, row: list[Cell], index: int | None) -> Cell | None:
        if index is None or index >= len(row):
            return None
        return row[index]


_SEP_LINE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_RC_RE = re.compile(r"(?:tr|row|r)\D{0,3}(\d+)\D+?(?:tc|cell|col|c)\D{0,3}(\d+)", re.I)


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _pipe_cells(block: Block, ls: int, le: int) -> list[Cell] | None:
    line = block.text[ls:le]
    if "|" not in line or _SEP_LINE.match(line):
        return None
    pos = [i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")]
    if not pos:
        return None
    bounds = [-1] + pos + [len(line)]
    segs = [(a + 1, b) for a, b in zip(bounds, bounds[1:], strict=False)]
    st = line.strip()
    if st.startswith("|"):
        segs = segs[1:]
    if st.endswith("|"):
        segs = segs[:-1]
    if len(segs) < 2:
        return None
    cells = []
    for a, b in segs:
        seg = line[a:b]
        lead = len(seg) - len(seg.lstrip())
        tail = len(seg.rstrip())
        s, e = (a + lead, a + tail) if tail > lead else (a + lead, a + lead)
        cells.append(Cell(block, ls + s, ls + e))
    return cells


def _loc_cells(block: Block) -> list[Cell] | None:
    """Ячейки по ``loc.cells`` загрузчика №01: точные координаты каждой ячейки в block.text."""
    cells = block.loc.get("cells") if isinstance(block.loc, Mapping) else None
    if not isinstance(cells, list) or not cells:
        return None
    out = []
    for c in sorted((c for c in cells if isinstance(c, Mapping)), key=lambda c: c.get("index", 0)):
        s, e = c.get("start"), c.get("end")
        if not (isinstance(s, int) and isinstance(e, int) and 0 <= s <= e <= len(block.text)):
            return None
        out.append(Cell(block, *_trim(block.text, s, e)) if e > s else Cell(block, s, s))
    return out or None


def _sep_cells(block: Block) -> list[Cell] | None:
    """Строка таблицы загрузчика контракта: «a | b | c», пустые ячейки сохраняют место."""
    text = block.text
    if text.lstrip().startswith("|"):
        return None
    cols = block.loc.get("columns") if isinstance(block.loc, Mapping) else None
    ncols = len(cols) if isinstance(cols, list) else 0
    if not text.strip():
        return [Cell(block, 0, 0) for _ in range(max(ncols, 1))]
    spans, pos = [], 0
    while True:
        i = text.find(" | ", pos)
        if i < 0:
            spans.append((pos, len(text)))
            break
        spans.append((pos, i))
        pos = i + 3
    s, e = spans[-1]
    tail = text[s:e]
    if tail == "|" or tail.endswith(" |"):
        spans[-1] = (s, s if tail == "|" else e - 2)
        spans.append((len(text), len(text)))
    cells = [Cell(block, *_trim(text, a, z)) for a, z in spans]
    while ncols and len(cells) < ncols:
        cells.append(Cell(block, len(text), len(text)))
    return cells


def _tab_cells(block: Block) -> list[Cell] | None:
    if "\t" not in block.text:
        return None
    cells, pos = [], 0
    for part in block.text.split("\t"):
        s, e = _trim(block.text, pos, pos + len(part))
        cells.append(Cell(block, s, e))
        pos += len(part) + 1
    return cells if len(cells) >= 2 else None


def _row_col(block: Block) -> tuple[int, int] | None:
    loc = block.loc
    if isinstance(loc, Mapping):
        r = loc.get("row")
        c = loc.get("col", loc.get("column", loc.get("cell")))
        if isinstance(r, int) and isinstance(c, int):
            return r, c
        loc = loc.get("path") or ""
    m = _RC_RE.search(str(loc or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def extract_tables(doc: Doc) -> list[Table]:
    """Таблицы из блоков любого загрузчика: таблица целиком, строка или ячейка на блок."""
    tables: list[Table] = []
    rows: list[list[Cell]] = []
    blocks: list[Block] = []
    last: Block | None = None
    cells: dict[int, dict[int, Cell]] = {}
    cell_blocks: list[Block] = []

    def flush_rows() -> None:
        nonlocal rows, blocks
        if rows:
            tables.append(Table(rows, blocks))
        rows, blocks = [], []

    def flush_cells() -> None:
        nonlocal cells, cell_blocks
        if cells:
            ordered = [[cells[r][c] for c in sorted(cells[r])] for r in sorted(cells)]
            tables.append(Table(ordered, cell_blocks))
        cells, cell_blocks = {}, []

    for b in doc.blocks:
        adjacent = last is not None and b.order == last.order + 1 and b.section == last.section
        if "cell" in b.kind:
            rc = _row_col(b)
            if rc is not None:
                flush_rows()
                if cell_blocks and (not adjacent or rc[0] < max(cells)):
                    flush_cells()
                s, e = _trim(b.text, 0, len(b.text))
                cells.setdefault(rc[0], {})[rc[1]] = Cell(b, s, e)
                cell_blocks.append(b)
                last = b
                continue
        flush_cells()
        if b.is_code:
            flush_rows()
            last = b
            continue
        lines = _line_spans(b.text)
        sep = (_loc_cells(b) or _sep_cells(b)) if b.kind in ("table_header", "table_row") else None
        parsed = [sep] if sep else [c for c in (_pipe_cells(b, s, e) for s, e in lines) if c]
        if not parsed and "row" in b.kind:
            tab = _tab_cells(b)
            parsed = [tab] if tab else []
        if len(parsed) >= 2:
            flush_rows()
            tables.append(Table(parsed, [b]))
            last = b
            continue
        if len(parsed) == 1:
            if blocks and not adjacent:
                flush_rows()
            rows.append(parsed[0])
            blocks.append(b)
            last = b
            continue
        if b.text.strip() and _SEP_LINE.match(b.text.strip()) and blocks and adjacent:
            last = b  # строка-разделитель Markdown между заголовком и телом
            continue
        flush_rows()
        last = b
    flush_rows()
    flush_cells()
    return tables


# ---------------------------------------------------------------- отметки ячеек

_OPT_RE = re.compile(
    r"не\s+требуется|не\s+применимо|не\s+применяется|н/п|n/a|да|нет|yes|no|na", re.I
)


def option_sem(token: str) -> str:
    t = norm(token)
    if t in {"да", "yes"}:
        return "yes"
    if t in {"нет", "no"}:
        return "no"
    return "na"


def parse_options(text: str) -> list[str] | None:
    """«Да / Нет / Не требуется» → ['Да', 'Нет', 'Не требуется'] в исходном написании."""
    t = (text or "").strip().strip("*").strip()
    if not t:
        return None
    toks: list[str] = []
    pos = 0
    for m in _OPT_RE.finditer(t):
        if t[pos : m.start()].strip(" /,;|"):
            return None
        if (m.start() > 0 and t[m.start() - 1].isalnum()) or (m.end() < len(t) and t[m.end()].isalnum()):
            return None
        toks.append(re.sub(r"\s+", " ", m.group(0)))
        pos = m.end()
    if t[pos:].strip(" /,;|."):
        return None
    return toks or None


def pick(allowed: list[str], sem: str | None) -> str | None:
    if sem is None:
        return None
    for tok in allowed:
        if option_sem(tok) == sem:
            return tok
    return None


# ---------------------------------------------------------------- темы строк шаблона


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    row: str
    section: str | None = None
    mention: str | None = None
    kind: str = "artifact"  # artifact | property
    section_map: bool = False  # замечание в разделе темы относится к строке
    na_rule: bool = False  # «Не требуется» допустимо при полном отсутствии упоминаний


TOPICS: tuple[Topic, ...] = (
    Topic(
        "security", "Информационная безопасность", r"информационн\w* безопасн|\bиб\b|безопасност",
        section=r"безопасн|\bиб\b|authorization|авторизац|аутентифик",
        mention=r"авторизац|authorization|bearer|токен|аутентифик|шифрован|персональн\w* данн|безопасн",
    ),
    Topic(
        "rollback", "Схема отката", r"откат|rollback|скрыти\w* функционал",
        section=r"откат|rollback",
        mention=r"откат|rollback|feature[ -]?flag|фич\w*[ -]?флаг|скрыти\w* функционал|отключени\w* функционал|выключени\w* функционал|toggle",
        section_map=True,
    ),
    Topic(
        "versioning", "Версионность документа", r"версион|верси\w* документ|история изменени",
        section=r"верси|история изменени|лист регистрации", mention=r"верси", section_map=True,
    ),
    Topic(
        "integration", "Интеграционное взаимодействие", r"интеграц",
        section=r"интеграц|\brest\b|\bapi\b|soap|grpc|kafka|очеред|обмен данными",
        mention=r"интеграц|\bapi\b|\brest\b|soap|grpc|kafka|endpoint|эндпоинт|внешн\w* систем",
        section_map=True, na_rule=True,
    ),
    Topic(
        "sequence", "Sequence-диаграммы", r"sequence|последовательност|взаимодейств",
        section=r"sequence|последовательност|диаграмм\w* взаимодейств",
        mention=r"sequence|взаимодейств|интеграц|\bapi\b|сервис",
        section_map=True, na_rule=True,
    ),
    Topic(
        "ui", "UX/UI", r"\bux\b|\bui\b|дизайн|интерфейс|макет",
        section=r"\bui\b|\bux\b|дизайн|интерфейс|экран|макет",
        mention=r"экран|кнопк|интерфейс|\bui\b|\bux\b|приложени|макет|форм\w* ввода|пользовател",
        section_map=True, na_rule=True,
    ),
    Topic(
        "process", "Схема бизнес-процесса", r"бизнес-процесс|бизнес процесс|bpmn|схем\w* (?:полного )?процесс",
        section=r"bpmn|бизнес-процесс|схем\w* процесс", section_map=True,
    ),
    Topic("architecture", "Архитектура", r"архитектур", section=r"архитектур", section_map=True),
    Topic(
        "impact", "Влияние на иные продукты и системы",
        r"влия\w* на ин\w*|ины\w* продукт|смежн\w* (?:систем|продукт)|затрагива",
        section=r"влияни\w* на (?:ис|информацион|систем|продукт)|затрагиваем\w* систем|смежн\w* систем",
        mention=r"влияни\w* на|затрагива|смежн\w* систем",
        na_rule=True,
    ),
    Topic(
        "data", "Модель данных", r"модел\w* данных|поток\w* данных|\bданн\w*",
        section=r"\bданн|db field|\bdata\b|модел\w* данных|хранени",
        mention=r"хран\w*|\bданн\w*|\bбд\b|db field|таблиц\w* бд|поле\w* бд|запис\w* в бд",
        section_map=True, na_rule=True,
    ),
    Topic(
        "testability", "Тестируемость", r"протестир|тестируем|тестирован|проверяем",
        section=r"критери\w* при[её]мк|тестирован|тест-кейс|acceptance|при[её]мочн",
    ),
    Topic("consistency", "Непротиворечивость и операционные риски", r"противореч|операционн\w* риск", kind="property"),
    Topic(
        "business", "Покрытие бизнес-требования",
        r"бизнес-требован|бизнес требован|покрыва\w* бизнес|техническ\w* требовани\w* зафиксир",
        section=r"^цел|функциональн\w* требован|бизнес-требован",
    ),
    Topic("structure", "Структура по шаблону", r"структурирован|по стандарту|по шаблону|шаблон", kind="property"),
)
TOPIC_BY_ID = {t.id: t for t in TOPICS}

# Ключевые разделы банковского шаблона ТЗ (для строки о структуре).
_TEMPLATE_SECTIONS = re.compile(
    r"общие сведения|^цел|архитектур|дизайн|функциональн\w* требован|нефункциональн|требования к данным|"
    r"требования к интеграц|требования к тестирован|критери\w* при[её]мк|ревью требований|блок согласующ|"
    r"sequence|bpmn|общие параметры|логика работы|параметры запроса|ответ|статус"
)

_APPROVAL_RE = re.compile(r"согласован|утвержд|подписан|одобрен|акцептован", re.I)
_ROLE_RE = re.compile(r"(?:согласован\w*|утвержд\w*)\s+с\s+(?P<role>[^,.;()]+)", re.I)
_GENERIC_ROLE = re.compile(r"ответственн|лиц|заинтересован|владел|участник|сторон")
_EXTERNAL_CHECKLIST = re.compile(r"чек-?лист|checklist", re.I)
_PLACEHOLDER = re.compile(
    r"^\s*(?:[-—–]+|tbd|todo|n/a|н/д|нет данных|\.\.\.|…|не заполнен\w*|будет\s+\w+\s+позже|"
    r"заполня\w+(?:\s+\w+){0,3}|уточня\w+(?:\s+\w+){0,3}|в разработке)\s*\.?\s*$",
    re.I,
)

# Замечания по виду (kind) → темы строк. Только сильные сигналы: остальное — через критерий
# (criteria.toml) и раздел документа, где стоит опора замечания.
_KIND_TOPICS = {
    "conflict": {"consistency"}, "contradiction": {"consistency"}, "inconsistency": {"consistency"},
    "inconsistent": {"consistency"}, "incorrect": {"consistency"}, "operational_risk": {"consistency"},
    "risk": {"consistency"}, "race": {"consistency"}, "idempotency": {"consistency"},
    "security": {"security"}, "ib": {"security"},
    "untestable": {"testability"}, "unverifiable": {"testability"}, "not_verifiable": {"testability"},
    "traceability": {"business"}, "infeasible": {"architecture"},
}

# Встроенная привязка критериев к строкам, если в criteria.toml нет bank_topics.
BUILTIN_CRITERIA_TOPICS: dict[str, set[str]] = {
    "necessary": {"business"}, "и1": {"business"},
    "appropriate": set(), "и2": set(),
    "unambiguous": {"testability"}, "и3": {"testability"},
    "complete": {"business"}, "и4": {"business"},
    "singular": {"structure"}, "и5": {"structure"},
    "feasible": {"architecture"}, "и6": {"architecture"},
    "verifiable": {"testability"}, "и7": {"testability"},
    "correct": {"consistency"}, "и8": {"consistency"},
    "conforming": {"structure"}, "и9": {"structure"},
    "set_complete": {"business"}, "completeness": {"business"}, "н1": {"business"},
    "set_consistent": {"consistency"}, "consistent": {"consistency"}, "consistency": {"consistency"}, "н2": {"consistency"},
    "set_feasible": {"architecture"}, "н3": {"architecture"},
    "set_comprehensible": {"structure"}, "comprehensible": {"structure"}, "н4": {"structure"},
    "set_validatable": {"testability"}, "able_to_be_validated": {"testability"}, "validatable": {"testability"}, "н5": {"testability"},
    "ranked": {"structure"}, "modifiable": {"structure"}, "traceable": {"business"},
    "security": {"security"}, "integration": {"integration"}, "data": {"data"}, "ui": {"ui"},
    "rollback": {"rollback"}, "versioning": {"versioning"}, "architecture": {"architecture"},
}

_SECURITY_TEXT = re.compile(r"информационн\w* безопасн|\bиб\b|утечк|персональн\w* данн|в логах|оседа\w* в лог|токен|секрет|несанкционир")
BLOCKING = {"critical", "major"}
_SEVERITY = {
    "critical": "critical", "критичный": "critical", "критический": "critical", "blocker": "critical",
    "major": "major", "существенный": "major", "high": "major",
    "minor": "minor", "незначительный": "minor", "low": "minor",
}


class CriteriaLink(dict):
    """Привязка критериев к чек-листу: dict «критерий → темы строк» и ``rows`` — строки шаблона №05.

    ``rows`` — записи ``[[checklist]]`` из criteria.toml: ``{id, text, match, criteria}``; строка
    документа связывается с записью по регулярному выражению ``match``.
    """

    def __init__(self, *args: Any, **kw: Any):
        super().__init__(*args, **kw)
        self.rows: list[dict[str, Any]] = []
        self.source = "builtin"

    def row_spec(self, text: str) -> dict[str, Any] | None:
        for spec in self.rows:
            try:
                if re.search(spec["match"], text, re.I | re.U):
                    return spec
            except re.error:
                continue
        return None


def _criteria_data(criteria: Any, warnings: list) -> tuple[Any, str]:
    if isinstance(criteria, Mapping):
        return criteria, "dict"
    if criteria is None:
        try:
            from .. import criteria as team_criteria  # №05: bcc_review.criteria:load_criteria()

            loaded = team_criteria.load_criteria()
            raw = loaded if isinstance(loaded, Mapping) else getattr(loaded, "raw", None)
            if isinstance(raw, Mapping):
                return raw, f"bcc_review.criteria ({getattr(loaded, 'tag', '') or getattr(loaded, 'version', '')})".replace(" ()", "")
        except Exception:  # noqa: BLE001 - модуль №05 не влит или вернул неожиданное: читаем файл
            pass
    path = Path(criteria) if criteria else Path(__file__).resolve().parents[1] / "criteria.toml"
    if path.is_file():
        try:
            return tomllib.loads(path.read_text("utf-8")), str(path.name)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            warnings.append(W("bank.criteria_unreadable", f"criteria.toml не прочитан: {exc}"))
    return None, ""


def load_criteria(criteria: Any = None, warnings: list | None = None) -> CriteriaLink:
    """Привязка «критерий → строки чек-листа» из criteria.toml (№05).

    Строки шаблона берутся из ``[[checklist]]`` (``match`` и ``criteria``), темы — из поля
    ``bank_topics`` у критерия (``[criteria.X]`` или ``[[criterion]]``, сравнение по ключу,
    ``id``, ``code``, ``short`` и ``aliases``). Без файла или без привязок используется
    встроенная таблица и пишется предупреждение.
    """
    warnings = warnings if warnings is not None else []
    link = CriteriaLink({k: set(v) for k, v in BUILTIN_CRITERIA_TOPICS.items()})
    data, source = _criteria_data(criteria, warnings)
    if data is None:
        warnings.append(
            W("bank.criteria_missing", "criteria.toml не найден: строки чек-листа связаны с критериями по встроенной таблице.", "info")
        )
        return link
    link.source = source
    if isinstance(data, Mapping):
        entries = data.get("criteria") or data.get("criterion") or {k: v for k, v in data.items() if k != "checklist"}
    else:
        entries = data
    items = entries.items() if isinstance(entries, Mapping) else [(g(e, "code") or g(e, "id"), e) for e in as_list(entries)]
    found = False
    row_links: dict[str, set[str]] = {}
    for key, entry in items:
        if not isinstance(entry, Mapping):
            continue
        names = {norm(key)} if key else set()
        names |= {norm(entry[k]) for k in ("id", "code", "key", "short") if entry.get(k)}
        names |= {norm(a) for a in as_list(entry.get("aliases"))}
        names.discard("")
        code = norm(entry.get("code") or key or "")
        for cl in as_list(entry.get("checklist")):  # №05: критерий → CL-строки шаблона
            row_links.setdefault(str(cl), set()).add(code)
        topics = entry.get("bank_topics") or entry.get("bank_rows")
        if topics:
            found = True
            known = {t for t in as_list(topics) if t in TOPIC_BY_ID}
            unknown = [t for t in as_list(topics) if t not in TOPIC_BY_ID]
            if unknown:
                warnings.append(W("bank.criteria_unknown_topic", f"Неизвестные темы чек-листа в criteria.toml: {', '.join(map(str, unknown))}", topics=unknown))
            for n in names:
                link[n] = set(known)
        else:
            inherited: set[str] = set()
            for n in names:
                inherited |= BUILTIN_CRITERIA_TOPICS.get(n, set())
            for n in names:
                link.setdefault(n, set()).update(inherited)
    rows = data.get("checklist") if isinstance(data, Mapping) else None
    for spec in as_list(rows):
        if isinstance(spec, Mapping) and spec.get("match"):
            crits = {norm(c) for c in as_list(spec.get("criteria"))} | row_links.get(str(spec.get("id")), set())
            link.rows.append({"id": str(spec.get("id") or ""), "text": str(spec.get("text") or ""), "match": str(spec["match"]),
                              "criteria": crits})
    if not found and not link.rows:
        warnings.append(
            W("bank.criteria_no_bank_topics", "В criteria.toml нет ни bank_topics, ни [[checklist]]: использована встроенная привязка критериев к строкам.", "info")
        )
    return link


# ---------------------------------------------------------------- обзор документа


@dataclass
class Scan:
    tables: list[Table]
    checklist: Table | None
    checklist_extra: list[Table]
    approvers: Table | None
    acceptance: list[Table]
    params: list[Table]
    kv: list[Table]
    headings: list[tuple[str, Block | None]]
    excluded: set[str]
    row_of: dict[str, tuple[Table, int]] = field(default_factory=dict)

    def content_of(self, doc: Doc, title: str) -> list[Block]:
        return [b for b in doc.blocks if title in b.section and not b.is_heading]


def _checklist_score(t: Table) -> int:
    if len(t.rows) < 2 or len(t.header) < 2:
        return 0
    body = t.body
    ncols = len(t.header)
    opt_cols = [
        c for c in range(ncols)
        if sum(1 for r in body if c < len(r) and parse_options(r[c].text)) >= max(1, len(body) / 2)
    ]
    if not opt_cols:
        return 0
    hdr = " ".join(c.ntext for c in t.header)
    score = 1
    if re.search(r"провер|пункт|критери|требовани|вопрос|check|item", hdr):
        score += 2
    if any(re.search(r"ревью|чек-?лист|checklist|контрольн", norm(s)) for s in t.section):
        score += 2
    if any(len(parse_options(r[c].text) or []) >= 2 for r in body for c in opt_cols if c < len(r)):
        score += 1
    return score if score >= 3 else 0


def _is_approvers(t: Table) -> bool:
    hdr = " ".join(c.ntext for c in t.header)
    sec = " ".join(norm(s) for s in t.section)
    return bool(re.search(r"подпис|фио|согласующ|approver|signature", hdr) or re.search(r"согласующ|лист согласован", sec))


def _is_acceptance(t: Table) -> bool:
    hdr = " ".join(c.ntext for c in t.header)
    return bool(
        re.search(r"исходн\w* услови|предуслови|\bдано\b|given", hdr)
        and re.search(r"действи|\bшаг|when|когда", hdr)
        and re.search(r"ожидаем|результат|then|тогда", hdr)
    )


def _is_params(t: Table) -> bool:
    hdr = " ".join(c.ntext for c in t.header)
    return bool(re.search(r"parameter|параметр|поле", hdr) and re.search(r"format|формат|\bтип\b|type", hdr))


def scan_document(doc: Doc) -> Scan:
    tables = extract_tables(doc)
    scored = [(t, _checklist_score(t)) for t in tables]
    candidates = [t for t, s in scored if s]
    best = max(candidates, key=lambda t: (_checklist_score(t), -t.blocks[0].order), default=None)
    approvers = next((t for t in tables if _is_approvers(t) and t is not best), None)
    acceptance = [t for t in tables if _is_acceptance(t) and t is not best]
    params = [t for t in tables if _is_params(t) and t is not best]
    kv = [t for t in tables if len(t.header) == 2 and t not in acceptance and t is not best and t is not approvers]
    headings: list[tuple[str, Block | None]] = []
    seen: set[str] = set()
    for b in doc.blocks:
        if b.is_heading:
            title = b.text.strip().lstrip("#").strip()
            headings.append((title, b))
            seen.add(title)
    for b in doc.blocks:
        for title in b.section:
            if title not in seen:
                headings.append((title, None))
                seen.add(title)
    excluded: set[str] = set()
    for t in (best, approvers):
        if t is not None:
            excluded |= t.block_ids
    row_of: dict[str, tuple[Table, int]] = {}
    for t in tables:
        for i, r in enumerate(t.rows):
            for c in r:
                row_of.setdefault(c.block.id, (t, i))
    return Scan(tables, best, [t for t in candidates if t is not best], approvers, acceptance, params, kv, headings, excluded, row_of)


# ---------------------------------------------------------------- состояния строки


@dataclass
class Facet:
    value: str | None  # yes | no | na | None
    basis: str
    evidence: list[dict] = field(default_factory=list)
    negative: list[dict] = field(default_factory=list)
    inspected: list[str] = field(default_factory=list)


def _cut_span(text: str, s: int, e: int, limit: int = 180) -> tuple[int, int]:
    if e - s <= limit:
        return s, e
    cut = text.rfind(" ", s, s + limit)
    return s, (cut if cut > s + limit // 2 else s + limit)


def snippet(doc: Doc, scan: Scan, block: Block) -> dict:
    """Короткая опора на содержимое блока: первая строка таблицы или первое предложение."""
    hit = scan.row_of.get(block.id)
    if hit:
        table, idx = hit
        row = table.rows[1] if idx == 0 and len(table.rows) > 1 else table.rows[idx]
        blk = row[0].block
        cells = [c for c in row if c.block is blk and c.end > c.start]
        if cells:
            s, e = _cut_span(blk.text, cells[0].start, cells[-1].end)
            return doc.ev(blk, s, e)
    spans = [(s, e) for s, e in sentences(block.text) if norm(block.text[s:e]) and not _SEP_LINE.match(block.text[s:e])]
    meaningful = [(s, e) for s, e in spans if not _ID_LABEL.match(norm(block.text[s:e]))]
    for s, e in meaningful or spans:  # «Ф-1.» — метка требования, опорой служит его текст
        s, e = _cut_span(block.text, s, e)
        return doc.ev(block, s, e)
    return doc.ev(block, 0, min(len(block.text), 180))


_ID_LABEL = re.compile(r"^[\w]{1,6}(?:[-.]\d+)+\.?$|^\d+[.)]?$")


def _is_placeholder(text: str) -> bool:
    t = norm(text)
    return not t or bool(_PLACEHOLDER.match(t))


def _scan_blocks(doc: Doc, scan: Scan) -> list[Block]:
    return [b for b in doc.blocks if b.id not in scan.excluded]


def _mention(doc: Doc, scan: Scan, pattern: str, limit: int = 1) -> tuple[list[dict], list[str]]:
    found: list[dict] = []
    inspected: list[str] = []
    for b in _scan_blocks(doc, scan):
        inspected.append(b.id)
        sp = norm_search(pattern, b.text)
        if sp and len(found) < limit:
            s, e = _sentence_around(b.text, *sp)
            found.append(doc.ev(b, s, e))
    return found, inspected


def _sentence_around(text: str, s: int, e: int) -> tuple[int, int]:
    for a, b in sentences(text):
        if a <= s and e <= b:
            return _cut_span(text, a, b)
    return s, e


def presence(doc: Doc, scan: Scan, topic: Topic) -> Facet:
    """Есть ли описание по теме строки: раздел, строка таблицы «поле — значение», упоминание."""
    pos: list[dict] = []
    neg: list[dict] = []
    inspected: list[str] = []
    titles: list[str] = []
    if topic.id == "versioning":
        return _presence_version(doc, scan)
    if topic.id == "structure":
        return _presence_structure(doc, scan)
    if topic.section:
        for title, hb in scan.headings:
            if not re.search(topic.section, norm(title)):
                continue
            content = [b for b in scan.content_of(doc, title) if b.id not in scan.excluded]
            if hb is not None:
                inspected.append(hb.id)
            inspected += [b.id for b in content]
            good = [b for b in content if not _is_placeholder(b.text)]
            if good:
                pos.append(snippet(doc, scan, good[0]))
                titles.append(title)
            elif content:
                neg.append(snippet(doc, scan, content[0]))
            elif hb is not None:
                neg.append(doc.ev(hb, 0, len(hb.text)))
        for t in scan.kv:
            for r in t.body:
                if len(r) < 2 or not re.search(topic.section, r[0].ntext):
                    continue
                inspected.append(r[0].block.id)
                val = r[1]
                if _is_placeholder(val.text):
                    neg.append(doc.ev(r[0].block, r[0].start, val.end))
                elif r[0].block.id not in scan.excluded:
                    pos.append(doc.ev(r[0].block, r[0].start, val.end))
                    titles.append(r[0].text.strip("* "))
    if not pos and topic.mention and topic.id in {"security", "rollback"}:
        found, insp = _mention(doc, scan, topic.mention)
        inspected += insp
        pos += found
    inspected = list(dict.fromkeys(inspected))
    if pos:
        where = ", ".join(f"«{short(t, 60)}»" for t in dict.fromkeys(titles)) or "упоминание в тексте"
        return Facet("yes", f"описано: {where}", pos[:3], neg[:2], inspected)
    if neg:
        return Facet("no", "раздел есть, но не заполнен", [], neg[:2], inspected)
    if not inspected:
        inspected = [b.id for b in _scan_blocks(doc, scan)]
    return Facet("no", f"в документе нет описания по теме «{topic.title}»", [], [], inspected)


_VERSION_POS = re.compile(r"верси\w*\s*(?:документа\s*)?[:№]?\s*v?\d+(?:\.\d+)*|\bv\d+\.\d+|история изменений|лист регистрации изменений")
_VERSION_NEG = re.compile(r"верси\w*[^.]{0,40}(?:не заполнен|не указан|отсутств|\bнет\b)|(?:не заполнен|не указан|отсутств)\w*[^.]{0,40}верси")


def _presence_version(doc: Doc, scan: Scan) -> Facet:
    pos, neg, inspected = [], [], []
    for b in _scan_blocks(doc, scan):
        inspected.append(b.id)
        for s, e in sentences(b.text):
            seg = b.text[s:e]
            if _VERSION_NEG.search(norm(seg)):
                neg.append(doc.ev(b, *_cut_span(b.text, s, e)))
            elif _VERSION_POS.search(norm(seg)):
                pos.append(doc.ev(b, *_cut_span(b.text, s, e)))
    if neg:
        return Facet("no", "в документе прямо сказано, что версия или дата не заполнены", [], neg[:2], inspected)
    if pos:
        return Facet("yes", "версия документа указана", pos[:2], [], inspected)
    return Facet("no", "номер версии, дата и история изменений в документе не найдены", [], [], inspected)


def _presence_structure(doc: Doc, scan: Scan) -> Facet:
    hits = [(t, b) for t, b in scan.headings if b is not None and _TEMPLATE_SECTIONS.search(norm(t))]
    if not hits:
        hits = [(t, None) for t, _ in scan.headings if _TEMPLATE_SECTIONS.search(norm(t))]
    ev = [doc.ev(b, 0, len(b.text)) for _, b in hits[:4] if b is not None]
    if len(hits) >= 3:
        names = ", ".join(f"«{t}»" for t, _ in hits[:6])
        return Facet("yes", f"документ разбит по разделам шаблона ({len(hits)}): {names}", ev, [], [b.id for _, b in hits if b])
    return Facet("no", "разделы банковского шаблона ТЗ не распознаны", [], [], [b.id for b in doc.blocks])


def _presence_property(doc: Doc, requirements: list[Any]) -> Facet:
    n = len(requirements)
    if n:  # опора строки-свойства — замечания, а не первое попавшееся требование
        return Facet("yes", f"требования для проверки есть: {n}", [], [], [])
    return Facet(None, "нарезка требований не передана", [], [], [])


def not_required(doc: Doc, scan: Scan, topic: Topic) -> Facet | None:
    """«Не требуется» только с основанием: ни одного упоминания темы в документе."""
    if not topic.na_rule or not topic.mention:
        return None
    if topic.id == "impact":
        for t in scan.kv:
            for r in t.body:
                if len(r) >= 2 and topic.section and re.search(topic.section, r[0].ntext):
                    if re.search(r"^(?:нет|не влияет|отсутству\w*|не затрагива\w*)\b", r[1].ntext):
                        return Facet("na", f"в поле «{r[0].text.strip('* ')}» указано «{r[1].text.strip()}»", [doc.ev(r[0].block, r[0].start, r[1].end)])
        return None
    found, inspected = _mention(doc, scan, topic.mention)
    if found:
        return None
    return Facet(
        "na",
        f"тема «{topic.title}» в документе не затрагивается: ни одного упоминания в {len(inspected)} проверенных блоках",
        [], [], inspected,
    )


# ---------------------------------------------------------------- замечания


@dataclass
class NF:
    id: str
    status: str
    severity: str
    title: str
    topics: set[str]  # сигналы и критерии вместе
    blocks: set[str]
    req_ids: set[str]
    raw: Any
    signals: set[str] = field(default_factory=set)  # вид, текст, раздел опоры
    crit_topics: set[str] = field(default_factory=set)  # через критерий (bank_topics / встроенная таблица)
    criteria: set[str] = field(default_factory=set)
    evidence: list[dict] = field(default_factory=list)  # проверенные опоры замечания


# Строки-свойства: замечание по критерию строки относится к ней, где бы ни стояла опора.
# Строки-артефакты (sequence, UI, данные…) требуют опоры в своём разделе; ИБ — явного признака ИБ.
_PROPERTY_ROWS = {"business", "structure", "testability", "consistency", "impact"}


def normalize_findings(doc: Doc, findings: Iterable[Any], crit: Mapping[str, set[str]]) -> list[NF]:
    out: list[NF] = []
    for i, f in enumerate(as_list(findings)):
        status = norm(g(f, "status") or "confirmed")
        if status not in {"confirmed", "needs_review"}:
            continue
        sev = _SEVERITY.get(norm(g(f, "severity") or "minor"), "minor")
        crits = {norm(c) for c in as_list(g(f, "criterion")) + as_list(g(f, "criteria")) if c}
        crit_topics: set[str] = set()
        for c in crits:
            crit_topics |= crit.get(c, set())
        signals = set(_KIND_TOPICS.get(norm(g(f, "kind") or ""), set()))
        if _SECURITY_TEXT.search(norm(f"{g(f, 'title') or ''} {g(f, 'impact') or ''}")):
            signals.add("security")  # в FINDING_KINDS контракта нет вида «ИБ»: распознаём по сути замечания
        evs = doc.evidence_of(f)
        blocks = {e["block_id"] for e in evs} | {str(b) for b in as_list(g(f, "inspected_block_ids")) if str(b) in doc.by_id}
        for bid in {e["block_id"] for e in evs}:
            b = doc.by_id[bid]
            for t in TOPICS:
                if t.section_map and t.section and any(re.search(t.section, norm(x)) for x in b.section):
                    signals.add(t.id)
        out.append(
            NF(str(g(f, "id") or f"F-{i + 1}"), status, sev, str(g(f, "title") or ""), signals | crit_topics, blocks,
               {str(x) for x in as_list(g(f, "req_ids"))}, f, signals, crit_topics, crits, evs)
        )
    return out


# Виды замечаний, которые лучше всего обосновывают «Нет» у строки темы.
_PREFERRED_KINDS = {"consistency": ("conflict", "incorrect"), "testability": ("unverifiable", "ambiguity"),
                    "business": ("omission", "incomplete"), "data": ("omission", "incomplete"),
                    "integration": ("conflict", "omission", "incorrect")}


def _best_ev(f: NF) -> dict:
    """Самая содержательная опора замечания: самая длинная цитата (слово «клиенту» хуже предложения)."""
    return max(f.evidence, key=lambda e: len(e["quote"]))


def _evidence_rank(f: NF, topic: Topic | None) -> tuple:
    kind = norm(g(f.raw, "kind") or "")
    preferred = _PREFERRED_KINDS.get(topic.id if topic else "", ())
    quote = len(_best_ev(f)["quote"]) if f.evidence else 0
    order = preferred.index(kind) if kind in preferred else len(preferred)
    return (0 if f.severity == "critical" else 1, order, 0 if quote >= 15 else 1)


def _maps(f: NF, topic: Topic, row_crit: set[str] | None) -> bool:
    if topic.id in f.signals:
        return True
    if row_crit is None:
        return topic.id in f.crit_topics
    return bool(f.criteria & row_crit) and topic.id in _PROPERTY_ROWS


def _lifted(topic: Topic | None, mapped: list[NF], links: Mapping[str, dict[str, list[dict]]] | None) -> dict[str, list[dict]]:
    """Замечания строки о тестируемости, снятые решением владельца.

    Неоднозначность границы блокирует тестируемость, пока исход на границе открыт. Когда решение владельца
    согласовало все граничные сценарии этого замечания, исход конкретный и проверяемый: замечание остаётся
    в ``finding_ids`` строки, но не блокирует её. Другие строки (противоречия, покрытие…) решение не снимает:
    документ по-прежнему содержит дефект, пока его не исправит редакция.
    """
    if not links or topic is None or topic.id != "testability":
        return {}
    out: dict[str, list[dict]] = {}
    for f in mapped:
        item = links.get(f.id)
        if item and item["agreed"] and not item["open"]:
            out[f.id] = item["agreed"]
    return out


def _machine(topic: Topic, pres: Facet, mapped: list[NF], complete: bool, external: bool) -> tuple[Facet, list[str]]:
    blocking = [f for f in mapped if f.status == "confirmed" and f.severity in BLOCKING]
    minor = [f for f in mapped if f.status == "confirmed" and f.severity not in BLOCKING]
    review = [f for f in mapped if f.status != "confirmed"]
    ids = [f.id for f in blocking + minor + review]
    if pres.value == "no" and topic.kind == "artifact":
        return Facet("no", "проверять нечего: описания нет"), ids
    if pres.value == "na":
        return Facet("na", pres.basis), ids
    if blocking:
        return Facet("no", "блокирующие замечания: " + ", ".join(f.id for f in blocking)), ids
    tail = ""
    if minor:
        tail += "; незначительные: " + ", ".join(f.id for f in minor)
    if review:
        tail += "; на перепроверке: " + ", ".join(f.id for f in review)
    if not complete:
        return Facet(None, "семантическая проверка выполнена не полностью (или без модели) — положительный вывод не делается" + tail), ids
    if external:
        return Facet(None, "автопроверка блокирующих дефектов не нашла, итог за профильным чек-листом" + tail), ids
    return Facet("yes", "блокирующих замечаний нет" + tail), ids


# ---------------------------------------------------------------- решения владельца


def decision_value(dec: Any) -> str:
    for k in ("option", "option_id", "choice", "answer", "value", "text"):
        v = g(dec, k)
        if v not in (None, ""):
            return str(v)
    return ""


def decisions_by_question(decisions: Iterable[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d in as_list(decisions):
        for k in ("question_id", "target", "question"):
            v = g(d, k)
            if v:
                out[str(v)] = d
    return out


def decision_id(dec: Any) -> str:
    """Decision контракта без собственного id: ссылка строится по вопросу («answer:Q-01»)."""
    own = g(dec, "id") or g(dec, "decision_id")
    if own:
        return str(own)
    qid = g(dec, "question_id")
    return f"answer:{qid}" if qid else "answer"


def decision_text(dec: Any) -> str:
    parts = [str(x) for x in (g(dec, "answer") or g(dec, "option") or g(dec, "value"), g(dec, "note") or g(dec, "text")) if x]
    return " — ".join(dict.fromkeys(parts)) or decision_value(dec)


# ---------------------------------------------------------------- строки чек-листа


def _column_roles(t: Table) -> dict[str, int | None]:
    roles: dict[str, int | None] = {"text": None, "available": None, "checked": None, "note": None}
    for i, c in enumerate(t.header):
        h = c.ntext
        if roles["note"] is None and re.search(r"примеч|коммент|обосн|\bnote|comment", h):
            roles["note"] = i
        elif roles["available"] is None and re.search(r"созда|доступ|налич|availab|present|exist", h):
            roles["available"] = i
        elif roles["checked"] is None and re.search(r"проверен|выполнен|подтвержд|согласован|checked|verified|done|статус|соответств", h):
            roles["checked"] = i
        elif roles["text"] is None and re.search(r"проверк|пункт|критери|требовани|вопрос|наименовани|check|item", h):
            roles["text"] = i
    if roles["text"] is None:
        roles["text"] = next(i for i in range(len(t.header)) if i not in roles.values())
    body = t.body
    opt_cols = [
        c for c in range(len(t.header))
        if c not in (roles["text"], roles["note"])
        and sum(1 for r in body if c < len(r) and parse_options(r[c].text)) >= max(1, len(body) / 2)
    ]
    free = [c for c in opt_cols if c not in (roles["available"], roles["checked"])]
    if roles["available"] is None and roles["checked"] is None:
        if len(free) >= 2:
            roles["available"], roles["checked"] = free[0], free[1]
        elif free:
            roles["checked"] = free[0]
    elif roles["available"] is None and free and len(opt_cols) >= 2:
        roles["available"] = free[0]
    elif roles["checked"] is None and free:
        roles["checked"] = free[0]
    if roles["note"] is None:
        rest = [i for i in range(len(t.header)) if i not in roles.values()]
        roles["note"] = rest[-1] if rest else None
    return roles


def _column_allowed(t: Table, col: int | None) -> list[str]:
    if col is None:
        return []
    union: list[str] = []
    for r in t.body:
        for tok in (parse_options(r[col].text) if col < len(r) else None) or []:
            if norm(tok) not in {norm(u) for u in union}:
                union.append(tok)
    return union or ["Да", "Нет"]


def classify_row(text: str) -> Topic | None:
    t = norm(text)
    for topic in TOPICS:
        if re.search(topic.row, t):
            return topic
    return None


def _approvers_state(doc: Doc, scan: Scan, role: str | None) -> tuple[str, str, list[dict]]:
    """Запись о согласовании в блоке согласующих: recorded | empty | absent."""
    t = scan.approvers
    if t is None:
        return "absent", "блока согласующих в документе нет", []
    hdr = [c.ntext for c in t.header]
    dep = next((i for i, h in enumerate(hdr) if re.search(r"подраздел|роль|должн|department|role|служб", h)), 0)
    sign = [i for i, h in enumerate(hdr) if re.search(r"фио|подпис|sign|дата|name|имя", h)]
    signed = []
    for r in t.body:
        if any(i < len(r) and r[i].text.strip() for i in sign):
            signed.append(r)
    if not signed:
        cells = t.body[0] if t.body else t.header
        b = cells[0].block
        ls = b.text.rfind("\n", 0, cells[0].start) + 1
        le = b.text.find("\n", cells[0].start)
        s, e = _trim(b.text, ls, le if le >= 0 else len(b.text))
        evs = [doc.ev(b, s, e)]
        hdr = t.header
        if hdr and hdr[0].block is not b and hdr[-1].end > hdr[0].start:
            evs.append(doc.ev(hdr[0].block, hdr[0].start, hdr[-1].end))
        return "empty", "в блоке согласующих нет ни ФИО, ни подписи", evs
    stem = norm(role or "")[:6]
    for r in signed:
        dep_text = r[dep].ntext if dep < len(r) else ""
        if stem and not _GENERIC_ROLE.search(norm(role or "")) and stem in dep_text:
            b = r[0].block
            return "recorded", f"в блоке согласующих есть запись «{r[dep].text.strip()}»", [doc.ev(b, r[0].start, r[-1].end)]
    names = ", ".join(r[dep].text.strip() for r in signed if dep < len(r))
    return "other", f"в блоке согласующих записаны: {names or 'без подразделения'}", []


def build_checklist(
    doc: Doc,
    scan: Scan,
    requirements: list[Any],
    findings: list[NF],
    decisions: Mapping[str, Any],
    ask: AskFn | None,
    warnings: list[dict],
    complete: bool = True,
    crit: Mapping[str, set[str]] | None = None,
    links: Mapping[str, dict[str, list[dict]]] | None = None,
    open_bounds: list[dict] | None = None,
) -> list[dict]:
    t = scan.checklist
    if t is None:
        warnings.append(
            W(
                "bank.checklist_absent",
                "В документе нет исходного банковского чек-листа «Ревью требований»: строки чек-листа не заполнялись, шаблон не подставлялся.",
            )
        )
        return []
    for extra in scan.checklist_extra:
        warnings.append(
            W("bank.checklist_extra", f"Найдена ещё одна таблица с отметками ({doc.label(snippet(doc, scan, extra.blocks[0]))}); заполнена первая по документу.", "info")
        )
    roles = _column_roles(t)
    allowed_col = {k: _column_allowed(t, roles[k]) for k in ("available", "checked")}
    headers = {k: (t.header[roles[k]].text.strip() if roles[k] is not None and roles[k] < len(t.header) else None) for k in roles}
    rows: list[dict] = []
    pending_llm: list[int] = []
    for pos, r in enumerate(t.body, 1):
        rows.append(_row(doc, scan, t, roles, headers, allowed_col, pos, r, requirements, findings, decisions, warnings, complete, crit=crit,
                         links=links, open_bounds=open_bounds))
        if rows[-1]["topic"] is None:
            pending_llm.append(pos)
    if pending_llm and ask is not None:
        _llm_rows(doc, scan, rows, pending_llm, ask, warnings, requirements, findings, decisions, t, roles, headers, allowed_col, complete, crit)
    for row in rows:
        if row["topic"] is None and not row["changes"]:
            warnings.append(
                W("bank.row_unclassified", f"Строка {row['position']} чек-листа не распознана: «{short(row['text'], 80)}». Отметки оставлены пустыми.", row_id=row["id"])
            )
    return rows


def _row_allowed(t: Table, roles: Mapping[str, int | None], r: list[Cell], key: str, col_allowed: list[str]) -> tuple[list[str], str | None, str | None]:
    """Допустимые отметки ячейки строки, исходная отметка автора и исходный текст."""
    cell = t.col(r, roles[key])
    if cell is None:
        return ([] if roles[key] is None else col_allowed), None, None
    opts = parse_options(cell.text)
    raw = cell.text.strip()
    if opts and len(opts) >= 2:
        return opts, None, raw
    if opts and len(opts) == 1:
        return col_allowed, opts[0], raw
    return col_allowed, None, raw or None


def _row(
    doc: Doc, scan: Scan, t: Table, roles: Mapping[str, int | None], headers: Mapping[str, str | None],
    col_allowed: Mapping[str, list[str]], pos: int, r: list[Cell], requirements: list[Any],
    findings: list[NF], decisions: Mapping[str, Any], warnings: list[dict], complete: bool,
    topic_override: Topic | None = None, approval_override: bool | None = None, llm: dict | None = None,
    crit: Mapping[str, set[str]] | None = None, links: Mapping[str, dict[str, list[dict]]] | None = None,
    open_bounds: list[dict] | None = None,
) -> dict:
    text_cell = t.col(r, roles["text"]) or r[0]
    text = text_cell.text.strip()
    note_cell = t.col(r, roles["note"])
    source_note = note_cell.text.strip() if note_cell is not None else ""
    allowed: dict[str, list[str]] = {}
    source_value: dict[str, str | None] = {}
    raw_cells: dict[str, str | None] = {}
    for key in ("available", "checked"):
        allowed[key], source_value[key], raw_cells[key] = _row_allowed(t, roles, r, key, col_allowed[key])
    topic = topic_override or classify_row(text)
    requires_approval = bool(_APPROVAL_RE.search(text)) if approval_override is None else approval_override
    role_m = _ROLE_RE.search(text)
    role = role_m.group("role").strip() if role_m else None
    external = bool(_EXTERNAL_CHECKLIST.search(source_note))
    row_id = f"CHK-{pos:02d}"
    row: dict = {
        "id": row_id,
        "position": pos,
        "text": text,
        "source_note": source_note,
        "available": "unknown",
        "checked": "unknown",
        "cells": {"available": None, "checked": None},
        "note": "",
        "finding_ids": [],
        "evidence": [],
        "allowed": allowed,
        "source_value": source_value,
        "topic": topic.id if topic else None,
        "presence": None,
        "machine": None,
        "approval": None,
        "not_required_basis": None,
        "status": "undetermined",
        "question": None,
        "changes": [],
        "source": {
            "block_id": text_cell.block.id,
            "evidence": doc.ev(text_cell.block, text_cell.start, text_cell.end),
            "location": loc_label(text_cell.block, text_cell.start),
            "columns": dict(headers),
            "cells": raw_cells,
        },
        "method": "rules",
        "criteria_link": None,
    }
    if topic is None and llm is None:
        row["note"] = "Тема строки не распознана правилами; отметки не проставлены."
        if requires_approval:
            state, basis, aev = _approvers_state(doc, scan, role)
            row["approval"] = {"required": True, "role": role, "status": "requires_confirmation",
                               "basis": f"требует подтверждения: {basis}", "evidence": aev, "decision_id": None}
            row["evidence"] = list(aev)
            row["note"] = (f"Согласование{(' с ' + role) if role else ''}: требует подтверждения — {basis}. "
                           "Наличие описания правилами не определено (тема строки не распознана).")
            row["question"] = {
                "id": f"Q-CHK-{pos:02d}", "kind": "approval",
                "prompt": f"Строка {pos} чек-листа «{short(text, 90)}»: получено ли согласование{(' с ' + role) if role else ''}?",
                "options": allowed["checked"] or ["Да", "Нет"], "finding_ids": [], "affected_req_ids": [],
                "target": f"checklist:{row_id}:checked",
            }
            row["status"] = "needs_confirmation"
        return row

    # --- наличие
    if llm is not None:
        pres = llm["presence"]
        row["method"] = "llm"
    elif topic.kind == "property" and topic.id != "structure":
        pres = _presence_property(doc, requirements)
    else:
        pres = presence(doc, scan, topic)
    na_allowed = any(option_sem(a) == "na" for a in (allowed["available"] or allowed["checked"]))
    if topic is not None and na_allowed and (pres.value == "no" or topic.id == "impact"):
        na = not_required(doc, scan, topic)
        if na is not None:
            pres = na
            row["not_required_basis"] = na.basis
    # --- машинная проверка
    spec = crit.row_spec(text) if isinstance(crit, CriteriaLink) else None
    row_crit = set(spec["criteria"]) if spec else None
    if spec:
        row["criteria_link"] = {"checklist_id": spec["id"], "criteria": sorted(spec["criteria"]), "source": crit.source}
    mapped = [f for f in findings if topic is not None and _maps(f, topic, row_crit)]
    lifted = _lifted(topic, mapped, links)
    active = [f for f in mapped if f.id not in lifted]
    machine, fids = _machine(topic or TOPICS[0], pres, active, complete, external)
    unlifted = None
    if lifted:
        unlifted, _ = _machine(topic or TOPICS[0], pres, mapped, complete, external)
        machine.basis += "; снято решением владельца: " + ", ".join(
            f"{fid} ({a[0]['decision_id']} → {', '.join(x['test_case_id'] for x in a)}: {a[0]['option']})" for fid, a in lifted.items())
        fids = fids + [fid for fid in lifted if fid not in fids]
    if topic is not None and topic.id == "testability" and open_bounds and machine.value == "yes":
        # Свой же сценарий пакета не выводит исход на границе: «может быть протестировано» не ставится.
        machine = Facet(None, "исход на границе не определён: " + ", ".join(
            f"{x['test_case_id']} открыт до решения {x['question_id']}" for x in open_bounds) + " — положительный вывод не делается")
    row["finding_ids"] = fids
    # --- согласование человеком
    approval = None
    if requires_approval:
        state, basis, aev = _approvers_state(doc, scan, role)
        status = "recorded" if state == "recorded" else "requires_confirmation"
        approval = {
            "required": True, "role": role, "status": status,
            "basis": basis if status == "recorded" else f"требует подтверждения: {basis}",
            "evidence": aev, "decision_id": None,
        }
        if pres.value == "na":
            approval.update(status="not_required", basis="согласование не требуется: " + pres.basis)
    # --- значения ячеек
    avail_sem = pres.value
    if approval is not None:
        checked_sem = {"recorded": "yes", "not_required": "na"}.get(approval["status"])
    else:
        checked_sem = machine.value
    notes: list[str] = []
    for key, sem in (("available", avail_sem), ("checked", checked_sem)):
        if not allowed[key]:
            continue
        val = pick(allowed[key], sem)
        if sem == "na" and val is None:
            val = pick(allowed[key], "no")
            notes.append(f"«Не требуется» шаблон в колонке «{headers[key]}» не допускает, отмечено «{val}»")
            warnings.append(W("bank.na_not_allowed", f"Строка {pos}: «Не требуется» не входит в допустимые отметки колонки «{headers[key]}».", row_id=row_id))
        row["cells"][key] = val
    if roles["available"] is None:
        notes.append("в шаблоне нет колонки наличия: наличие указано в примечании")
    # --- решение владельца
    _apply_row_decision(row, decisions, approval)
    # --- отметки контракта (yes|no|na|unknown) из исходных токенов ячеек
    for key, fallback in (("available", avail_sem), ("checked", None)):
        tok = row["cells"][key]
        row[key] = option_sem(tok) if tok else (fallback if (fallback and not allowed[key]) else "unknown")
    # --- примечание
    row["presence"] = {"value": pres.value or "unknown", "basis": pres.basis, "evidence": pres.evidence, "negative_evidence": pres.negative, "inspected_block_ids": pres.inspected[:200]}
    blocking = sorted((f for f in active if f.status == "confirmed" and f.severity in BLOCKING),
                      key=lambda f: _evidence_rank(f, topic))
    row["machine"] = {"value": machine.value or "unknown", "basis": machine.basis, "finding_ids": fids,
                      "blocking_finding_ids": [f.id for f in blocking],
                      "resolved": [{"finding_id": fid, **x} for fid, a in lifted.items() for x in a]}
    row["approval"] = approval
    fevs = [_best_ev(f) for f in blocking if f.evidence][:3]
    row["evidence"] = _dedupe_ev(pres.evidence + pres.negative + (approval["evidence"] if approval else []) + fevs)
    if blocking and blocking[0].evidence:
        e = _best_ev(blocking[0])
        notes.insert(0, f"Ключевое замечание: {blocking[0].id} «{short(blocking[0].title, 80)}» — «{short(e['quote'], 70)}» ({doc.label(e)})")
    for f in blocking:
        waiting = (links or {}).get(f.id, {}).get("open") or []
        if waiting:
            notes.append(f"{f.id}: исход на границе не выводится — {', '.join(x['test_case_id'] for x in waiting)} открыт до решения {waiting[0]['question_id']}")
    for fid, agreed in lifted.items():
        a = agreed[0]
        notes.append(f"{fid} снято решением владельца {a['decision_id']} по вопросу {a['question_id']} ({a['option']}): "
                     f"{', '.join(x['test_case_id'] for x in agreed)} согласован — {short(a['expected'], 90)}"
                     + ("" if a["document_edited"] else "; формулировка в документе не изменена — нужна правка редакции"))
    if lifted and unlifted is not None and approval is None and allowed["checked"]:
        before_cell = pick(allowed["checked"], unlifted.value)
        if before_cell != row["cells"]["checked"]:
            fid, agreed = next(iter(lifted.items()))
            a = agreed[0]
            row["changes"].append({
                "field": "checked", "before": before_cell, "after": row["cells"]["checked"], "decision_id": a["decision_id"],
                "reason": f"решение владельца ({a['decision_id']}) по вопросу {a['question_id']}: "
                          f"{', '.join(lifted)} больше не блокирует — {', '.join(x['test_case_id'] for x in agreed)} согласован ({a['option']})",
            })
    row["note"] = _compose_note(doc, row, pres, machine, approval, source_value, external, source_note, notes)
    if approval is not None and approval["status"] == "requires_confirmation":
        row["question"] = {
            "id": f"Q-CHK-{pos:02d}",
            "kind": "approval",
            "prompt": f"Строка {pos} чек-листа «{short(text, 90)}»: получено ли согласование{(' с ' + role) if role else ''}?",
            "options": allowed["checked"] or ["Да", "Нет"],
            "finding_ids": [],
            "affected_req_ids": [],
            "target": f"checklist:{row_id}:checked",
        }
    cells = row["cells"]
    row["status"] = "needs_confirmation" if (cells["checked"] is None and allowed["checked"]) or (cells["available"] is None and allowed["available"]) else "filled"
    return row


def _apply_row_decision(row: dict, decisions: Mapping[str, Any], approval: dict | None) -> None:
    keys = [f"Q-CHK-{row['position']:02d}", f"checklist:{row['id']}:checked", f"checklist:{row['id']}", row["id"]]
    dec = next((decisions[k] for k in keys if k in decisions), None)
    if dec is None:
        return
    field_name = str(g(dec, "field") or "checked")
    if field_name not in ("available", "checked"):
        field_name = "checked"
    opts = parse_options(decision_value(dec)) or []
    sem = option_sem(opts[0]) if opts else None
    val = pick(row["allowed"][field_name], sem)
    if val is None:
        return
    before = row["cells"][field_name]
    row["cells"][field_name] = val
    did = decision_id(dec)
    said = short(decision_text(dec), 100)
    if approval is not None and field_name == "checked":
        approval["status"] = {"yes": "confirmed", "no": "rejected", "na": "not_required"}[sem]
        approval["decision_id"] = did
        approval["basis"] = f"решение владельца ({did}): {said}"
    row["changes"].append(
        {"field": field_name, "before": before, "after": val, "reason": f"решение владельца ({did}): «{said}»", "decision_id": did}
    )


def _dedupe_ev(evs: Iterable[dict]) -> list[dict]:
    seen, out = set(), []
    for e in evs:
        k = (e["block_id"], e["start"], e["end"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


_SEM_WORD = {"yes": "да", "no": "нет", "na": "не требуется", "unknown": "не определено", None: "не определено"}
_QUOTELESS = {t.id for t in TOPICS if t.kind == "property" and t.id != "structure"}  # наличие = есть что проверять


def _compose_note(doc: Doc, row: dict, pres: Facet, machine: Facet, approval: dict | None,
                  source_value: Mapping[str, str | None], external: bool, source_note: str, extra: list[str]) -> str:
    parts: list[str] = []
    if pres.value == "na":
        parts.append(f"Не требуется: {pres.basis}")
    elif row.get("topic") in _QUOTELESS:
        parts.append(f"Наличие: {_SEM_WORD[pres.value]} — {pres.basis}")
    elif pres.evidence:
        e = pres.evidence[0]
        parts.append(f"Наличие: {_SEM_WORD[pres.value]} — «{short(e['quote'], 110)}» ({doc.label(e)})")
    elif pres.negative:
        e = pres.negative[0]
        parts.append(f"Наличие: {_SEM_WORD[pres.value]} — {pres.basis}: «{short(e['quote'], 90)}» ({doc.label(e)})")
    else:
        parts.append(f"Наличие: {_SEM_WORD[pres.value]} — {pres.basis}")
    if machine.value != "na":
        parts.append(f"Автопроверка: {_SEM_WORD[machine.value]} — {machine.basis}")
    if approval is not None:
        if approval["status"] in ("requires_confirmation",):
            where = f" ({doc.label(approval['evidence'][0])})" if approval["evidence"] else ""
            parts.append(f"Согласование{(' с ' + approval['role']) if approval['role'] else ''}: {approval['basis']}{where}")
        else:
            parts.append(f"Согласование: {approval['basis']}")
    if external:
        parts.append(f"Шаблон: «{source_note}» — итог за профильным чек-листом, требует подтверждения")
    for key, val in source_value.items():
        mine = row["cells"].get(key)
        if val and mine and norm(val) != norm(mine):
            parts.append(f"Автор отметил «{val}» в колонке «{row['source']['columns'].get(key)}», агент — «{mine}»")
    parts += extra
    return ". ".join(p.rstrip(".") for p in parts) + "."


# ---------------------------------------------------------------- LLM для нераспознанных строк

def _S(props: dict[str, Any]) -> dict[str, Any]:
    """Строгая схема объекта для structured outputs: все поля обязательны, лишних нет."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_HINTS = {"type": "array", "items": _S({"block_id": {"type": "string"}, "quote": {"type": "string"}})}
_ROW_SCHEMA = _S({
    "rows": {"type": "array", "items": _S({
        "position": {"type": "integer"},
        "topic": {"type": "string", "enum": [t.id for t in TOPICS] + ["none"]},
        "requires_approval": {"type": "boolean"},
        "available": {"type": "string"},
        "basis": {"type": "string"},
        "hints": _HINTS,
    })},
})
STAGE_CHECKLIST = "bank#checklist"

_ROW_TASK = (
    "Ты заполняешь строки банковского чек-листа «Ревью требований» по тексту ТЗ. Для каждой строки "
    "определи тему из списка topics (или «none», если ни одна не подходит), требует ли строка согласования "
    "человеком, и есть ли в документе описание, о котором спрашивает строка (available — одно из allowed "
    "или пустая строка, если нельзя решить). Обоснуй коротко по-русски (basis) и дай дословные цитаты из блоков документа (hints: "
    "block_id и quote). Не выдумывай: если описания нет, available = «Нет» и пустой hints; «Не требуется» "
    "ставь только с основанием в basis. Согласование человеком сам не подтверждай."
)


def _llm_rows(doc: Doc, scan: Scan, rows: list[dict], positions: list[int], ask: AskFn, warnings: list[dict],
              requirements: list[Any], findings: list[NF], decisions: Mapping[str, Any], t: Table,
              roles: Mapping[str, int | None], headers: Mapping[str, str | None],
              col_allowed: Mapping[str, list[str]], complete: bool, crit: Mapping[str, set[str]] | None = None) -> None:
    payload = {
        "task": _ROW_TASK,
        "input": {
            "topics": {tp.id: tp.title for tp in TOPICS},
            "rows": [{"position": p, "text": rows[p - 1]["text"], "allowed": rows[p - 1]["allowed"]["available"] or rows[p - 1]["allowed"]["checked"] or ["Да", "Нет"],
                      "source_note": rows[p - 1]["source_note"]} for p in positions],
        },
        "context": {"mode": "auto", "block_ids": [b.id for b in _scan_blocks(doc, scan) if b.text.strip()][:300]},
    }
    try:
        answer = ask(STAGE_CHECKLIST, payload, _ROW_SCHEMA)
    except Exception as exc:  # noqa: BLE001 - отказ поставщика не должен ронять отчёт
        warnings.append(W("bank.llm_failed", f"Классификация строк чек-листа моделью не выполнена: {exc}"))
        return
    for item in as_list(g(answer, "rows")):
        p = g(item, "position")
        if p not in positions:
            continue
        topic = TOPIC_BY_ID.get(str(g(item, "topic") or ""))
        allowed = rows[p - 1]["allowed"]["available"] or rows[p - 1]["allowed"]["checked"] or ["Да", "Нет"]
        val = g(item, "available")
        sem = option_sem(val) if val and norm(val) in {norm(a) for a in allowed} else None
        evs = [e for e in (doc.from_hint(h) for h in as_list(g(item, "hints"))) if e and e["block_id"] not in scan.excluded]
        basis = str(g(item, "basis") or "").strip()
        if sem == "yes" and not evs:
            warnings.append(W("bank.llm_rejected", f"Строка {p}: модель отметила наличие без проверяемой цитаты, отметка снята.", row_id=f"CHK-{p:02d}"))
            sem = None
        if sem == "na" and not basis:
            warnings.append(W("bank.llm_rejected", f"Строка {p}: «Не требуется» без основания, отметка снята.", row_id=f"CHK-{p:02d}"))
            sem = None
        if topic is None and sem is None:
            continue
        pres = Facet(sem, f"по оценке модели: {basis}" if basis else "по оценке модели", evs, [], [e["block_id"] for e in evs])
        cells = t.body[p - 1]
        new = _row(doc, scan, t, roles, headers, col_allowed, p, cells, requirements, findings, decisions, warnings, complete,
                   topic_override=topic, approval_override=bool(g(item, "requires_approval")) or None,
                   llm={"presence": pres}, crit=crit)
        if topic is None:
            new["topic"] = None
        rows[p - 1] = new


# ---------------------------------------------------------------- пакет целиком


def build_bank_pack(
    document: Any,
    requirements: Iterable[Any] = (),
    findings: Iterable[Any] = (),
    decisions: Iterable[Any] = (),
    ask: AskFn | None = None,
    *,
    coverage: Iterable[Any] = (),
    questions: Iterable[Any] | None = None,
    criteria: Any = None,
    previous: Mapping[str, Any] | None = None,
    complete: bool | None = None,
) -> dict:
    """Чек-лист банка и черновые приёмочные сценарии по текущему входу.

    ``document``/``requirements``/``findings`` — объекты контракта v1;
    ``decisions`` — принятые решения №08; ``coverage`` — покрытие №06 с колонкой
    «что не покрыто»; ``questions`` — Report.questions, чтобы открытые
    сценарии ссылались на уже заданные вопросы. Переданный ``questions`` (даже пустой)
    означает, что вызывающий добавит ``collect_questions(pack)`` в Report.questions; без него
    ``open_question_id`` ставится только на известные вопросы, иначе ``null`` (вопрос — в
    ``open_question``), чтобы в отчёте не было висячих ссылок; ``previous`` — прежний пакет
    (после ``--answers`` и перепроверки) для причин изменений; ``complete`` —
    все ли проверки прошли. По умолчанию ``complete = ask is not None``: без модели
    семантические проверки не выполнялись, и положительные машинные отметки не ставятся
    (отрицательные по найденным замечаниям остаются).
    Возвращает ``{checklist, test_cases, warnings}``.
    """
    from . import acceptance

    doc = Doc(document)
    warnings: list[dict] = []
    if complete is None:
        complete = ask is not None
    reqs = as_list(requirements)
    crit = load_criteria(criteria, warnings)
    scan = scan_document(doc)
    nfs = normalize_findings(doc, findings, crit)
    decs = decisions_by_question(decisions)
    # Сценарии раньше чек-листа: строке о тестируемости нужно знать, какие граничные исходы открыты
    # и какие согласованы решением владельца. Порядок предупреждений прежний: чек-лист, затем сценарии.
    tc_warnings: list[dict] = []
    test_cases = acceptance.build_test_cases(
        doc, scan, reqs, findings, decisions, ask, coverage=as_list(coverage), questions=as_list(questions), warnings=tc_warnings,
        publish_own_questions=questions is not None,
    )
    links = boundary_links(test_cases, decs)
    for f in nfs:
        if f.id in links:
            f.signals.add("testability")
            f.topics.add("testability")
    checklist = build_checklist(doc, scan, reqs, nfs, decs, ask, warnings, complete, crit, links=links,
                                open_bounds=open_boundaries(test_cases))
    warnings.extend(tc_warnings)
    if previous:
        apply_previous(checklist, test_cases, previous, warnings)
    _check_decisions(decs, checklist, test_cases, warnings)
    return {"checklist": checklist, "test_cases": test_cases, "warnings": warnings}


def _inclusive_question(tc: Mapping[str, Any]) -> Mapping[str, Any] | None:
    q = tc.get("open_question") or {}
    return q if tc.get("kind") == "boundary" and str(q.get("key") or "").endswith(":inclusive") else None


def open_boundaries(test_cases: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Граничные сценарии, исход которых ждёт решения о включённости границы (с замечанием или без)."""
    return [{"test_case_id": tc["id"], "question_id": tc.get("open_question_id") or q.get("id")}
            for tc in test_cases if tc.get("status") == "open" and (q := _inclusive_question(tc)) is not None]


def boundary_links(test_cases: Iterable[Mapping[str, Any]], decisions: Mapping[str, Any]) -> dict[str, dict[str, list[dict]]]:
    """Замечания, из-за которых исход на границе не выводился: ``{finding_id: {"open": […], "agreed": […]}}``.

    Берутся только вопросы о включённости границы (ключ ``…:inclusive``): в их ``finding_ids`` попадает
    неоднозначность, стоящая на цитате самой границы. ``open`` — сценарий ждёт решения; ``agreed`` —
    решение владельца выбрало вариант, и исход теперь конкретный.
    """
    links: dict[str, dict[str, list[dict]]] = {}
    for tc in test_cases:
        q = _inclusive_question(tc)
        if q is None:
            continue
        for fid in q.get("finding_ids") or []:
            item = links.setdefault(str(fid), {"open": [], "agreed": []})
            if tc["status"] == "open":
                item["open"].append({"test_case_id": tc["id"], "question_id": tc.get("open_question_id") or q.get("id")})
            elif tc["status"] == "agreed" and tc.get("decision_id"):
                chosen = next((o for o in tc.get("options") or [] if o.get("chosen")), None)
                dec = decisions.get(str(tc.get("resolved_question_id") or ""))
                item["agreed"].append({
                    "test_case_id": tc["id"], "question_id": tc.get("resolved_question_id"), "decision_id": tc["decision_id"],
                    "option": chosen["label"] if chosen else None, "expected": tc.get("expected"),
                    "document_edited": bool(as_list(g(dec, "edits"))),
                })
    return links


def _check_decisions(decs: Mapping[str, Any], checklist: list[dict], test_cases: list[dict], warnings: list[dict]) -> None:
    used = {c.get("decision_id") for r in checklist for c in r["changes"]} | {tc.get("decision_id") for tc in test_cases}
    for key, dec in decs.items():
        if (key.startswith("Q-CHK-") or key.startswith("Q-BANK-") or key.startswith("checklist:")) and decision_id(dec) not in used:
            warnings.append(W("bank.decision_unmatched", f"Решение {decision_id(dec)} по {key} не применено: строка или вопрос не найдены в текущем пакете.", decision_id=decision_id(dec)))


def apply_previous(checklist: list[dict], test_cases: list[dict], previous: Mapping[str, Any], warnings: list[dict]) -> None:
    """Пересчёт относительно прежнего пакета: что изменилось и почему."""
    old_rows = {(r.get("position"), norm(r.get("text"))): r for r in as_list(g(previous, "checklist"))}
    for row in checklist:
        old = old_rows.get((row["position"], norm(row["text"])))
        if old is None:
            continue
        for key in ("available", "checked"):
            before = (g(old, "cells") or {}).get(key, g(old, key))
            after = row["cells"].get(key)
            if before != after and not any(c["field"] == key for c in row["changes"]):
                row["changes"].append({"field": key, "before": before, "after": after, "reason": _reason(old, row)})
    old_tc = {g(t, "key"): t for t in as_list(g(previous, "test_cases"))}
    new_keys = set()
    for tc in test_cases:
        new_keys.add(tc["key"])
        old = old_tc.get(tc["key"])
        if old is None:
            tc["changes"].append({"field": "test_case", "before": None, "after": tc["id"], "reason": "новый сценарий по текущему входу"})
            continue
        decided = any(c.get("decision_id") for c in tc["changes"])
        for key in ("expected", "status"):
            if key == "status" and decided:
                continue  # переход open → agreed уже объяснён решением владельца
            if g(old, key) != tc[key] and not any(c["field"] == key for c in tc["changes"]):
                tc["changes"].append({"field": key, "before": g(old, key), "after": tc[key], "reason": _reason(old, tc)})
    for key, old in old_tc.items():
        if key not in new_keys:
            warnings.append(W("bank.test_case_removed", f"Сценарий {g(old, 'id')} «{short(str(g(old, 'title')), 80)}» больше не выводится из текущего входа.", "info", key=key))


def _reason(old: Any, new: Mapping[str, Any]) -> str:
    parts = []
    before = set(as_list(g(old, "finding_ids")))
    after = set(new.get("finding_ids") or [])
    if before - after:
        parts.append("замечания сняты после перепроверки: " + ", ".join(sorted(before - after)))
    if after - before:
        parts.append("новые замечания: " + ", ".join(sorted(after - before)))
    if new.get("decision_id") and new.get("decision_id") != g(old, "decision_id"):
        parts.append(f"решение владельца {new['decision_id']}")
    old_ev = {(g(e, "block_id"), g(e, "quote")) for e in as_list(g(old, "evidence"))}
    new_ev = {(e["block_id"], e["quote"]) for e in new.get("evidence") or []}
    if old_ev != new_ev:
        parts.append("изменились опоры в документе")
    return "; ".join(parts) or "пересчитано по текущему входу"


def collect_questions(pack: Mapping[str, Any]) -> list[dict]:
    """Открытые вопросы пакета в форме Question контракта для Report.questions (и answers.md №08).

    ``{id, finding_ids, prompt, options, affected_req_ids}`` плюс ``source``, ``kind`` и ссылки
    на строки чек-листа или сценарии.
    """
    out: dict[str, dict] = {}
    for row in as_list(g(pack, "checklist")):
        q = g(row, "question")
        if q and (g(row, "cells") or {}).get("checked") is None:
            out.setdefault(q["id"], {"id": q["id"], "finding_ids": list(q.get("finding_ids", [])), "prompt": q["prompt"],
                                     "options": list(q["options"]), "affected_req_ids": [], "kind": "approval",
                                     "source": "bank.checklist", "row_id": row["id"]})
    for tc in as_list(g(pack, "test_cases")):
        q = g(tc, "open_question")
        if not q or g(tc, "status") != "open":
            continue
        item = out.setdefault(q["id"], {"id": q["id"], "finding_ids": list(q.get("finding_ids", [])), "prompt": q["prompt"],
                                        "options": list(q["options"]), "affected_req_ids": [], "kind": "outcome",
                                        "source": "bank.test_cases", "test_case_ids": [], "existing": bool(q.get("existing"))})
        item["test_case_ids"].append(tc["id"])
        item["affected_req_ids"] = list(dict.fromkeys(item["affected_req_ids"] + list(tc.get("req_ids", []))))
    return list(out.values())


def dumps(pack: Mapping[str, Any]) -> str:
    return json.dumps(pack, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- превью (для демо и №13)


def _cell(text: Any) -> str:
    return str("—" if text in (None, "") else text).replace("|", "\\|").replace("\n", " ")


def render_markdown(pack: Mapping[str, Any]) -> str:
    """Черновой русский Markdown пакета: чек-лист, сценарии, открытые вопросы, предупреждения."""
    out: list[str] = ["## Чек-лист банка «Ревью требований»", ""]
    rows = as_list(g(pack, "checklist"))
    if not rows:
        msg = next((w["message"] for w in as_list(g(pack, "warnings")) if w.get("code") == "bank.checklist_absent"), "Исходного чек-листа нет.")
        out += [f"> {msg}", ""]
    else:
        cols = rows[0]["source"]["columns"]
        out.append(f"| № | {_cell(cols.get('text') or 'Проверка')} | {_cell(cols.get('available') or 'Наличие')} | "
                   f"{_cell(cols.get('checked') or 'Проверено')} | Обоснование | Замечания |")
        out.append("| ---: | :--- | :---: | :---: | :--- | :--- |")
        for r in rows:
            cells = r.get("cells") or {}
            checked = cells.get("checked") or ("требует подтверждения" if r["approval"] else "не определено")
            avail = cells.get("available") or ("—" if not r["allowed"]["available"] else "не определено")
            out.append(f"| {r['position']} | {_cell(r['text'])} | {_cell(avail)} | {_cell(checked)} | {_cell(r['note'])} | "
                       f"{_cell(', '.join(r['finding_ids']))} |")
        out.append("")
    tcs = as_list(g(pack, "test_cases"))
    out += ["## Черновые приёмочные сценарии", "",
            f"Всего {len(tcs)}: открытых до решения — {sum(1 for t in tcs if t['status'] == 'open')}, "
            f"согласованных решением — {sum(1 for t in tcs if t['status'] == 'agreed')}. Черновик для тестировщика.", ""]
    for t in tcs:
        qid = t["open_question_id"] or (t.get("open_question") or {}).get("id")
        status = {"open": f"открыт до решения {qid}", "agreed": f"согласован решением {t['decision_id']}", "draft": "черновик"}[t["status"]]
        reqs = ", ".join(t["source_ids"]) or "без требования"
        out.append(f"**{t['id']}. {t['title']}** · {reqs} · {status}")
        out.append("")
        out.append(f"- Дано: {t['precondition']}")
        out.append(f"- Когда: {t['action']}")
        if t["status"] == "open":
            out.append("- Тогда: открыто —")
            out += [f"  - вариант {o['id']} ({o['label']}): {o['expected']}" for o in t["options"]]
        else:
            out.append(f"- Тогда: {t['expected']}")
        for ch in t["changes"]:
            out.append(f"- Изменение: {ch['reason']}")
        if t["notes"]:
            out.append(f"- Примечания: {'; '.join(t['notes'])}")
        out.append("")
    qs = collect_questions(pack)
    if qs:
        out += ["## Открытые вопросы пакета", ""]
        out += [f"- **{q['id']}** {q['prompt']}" for q in qs]
        out.append("")
    warns = [w for w in as_list(g(pack, "warnings")) if w.get("level") == "warning"]
    if warns:
        out += ["## Предупреждения", ""] + [f"- {w['message']}" for w in warns] + [""]
    return "\n".join(out)
