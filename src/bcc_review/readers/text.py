"""Чтение Markdown (.md, .markdown) и обычного текста (.txt) в ``Document`` контракта v1.

``read_text(path) -> Document`` (точка входа №01 по ``contracts/HANDOFF.md``).

* ``Document.id`` — SHA-256 исходных байтов, посчитанный до декодирования; ``format`` —
  ``markdown`` или ``text``; ``source_name`` — имя файла без каталога.
* ``Block.id`` — ``b0001``, ``b0002``… в порядке чтения. Каждый блок начинается со своей строки,
  поэтому одинаковые байты дают одинаковые ID. Тот же текст с другими окончаниями строк или BOM даёт
  те же ID блоков, но другой ``Document.id``.
* ``kind`` ∈ ``heading|paragraph|list_item|table_header|table_row|code|quote|other``.
* ``section`` — заголовки от корня. У заголовка путь состоит из его родителей, сам он в путь не входит.

Строки и столбцы
----------------
* Строка завершается CRLF, LF или одиночным CR (как в CommonMark). U+2028, U+2029, NEL, VT и FF
  строку не завершают, иначе номера разошлись бы с GitHub, ``grep -n`` и редакторами.
  ``str.splitlines`` по этой причине не используется.
* Строки нумеруются с 1. Столбец = индекс кодовой точки Unicode с 0 внутри строки без её окончания.
  BOM в столбцы не входит, в байтовые смещения входит.
* Текст в NFC не приводится: столбцы совпадают с файлом. Если файл не в NFC, выдаётся предупреждение.

Видимый текст
-------------
``block.text`` содержит текст, который видит читатель: без ``#``, маркеров списков и чек-боксов,
``**``/``*``/``_``/``~~``, обратных кавычек кода, экранирующих ``\\``, крайних ``|`` таблицы и
хвостовых пробелов жёсткого переноса. Разделители зафиксированы так:

* ``"\\n"`` стоит между физическими строками одного блока (абзац, пункт списка, код, цитата);
* ``" | "`` стоит между ячейками строки таблицы. Если в источнике между ячейками ровно ``" | "``
  (канонический GFM), разделитель считается дословной копией;
* ``<br>`` даёт ``"\\n"``, HTML-сущность даёт её символ;
* ссылка на сноску ``[^1]`` даёт ``[1]`` (снят только ``^``, если в документе есть определение
  ``[^1]:``), определение ``[^1]: текст`` даёт ``[1]: текст``.

Содержимое fenced-блоков и ``код`` в обратных кавычках копируется дословно: не исполняется и не
разбирается, ``|`` и ``#`` внутри него не создают таблиц и заголовков.

Поля ``loc``
------------
Общие для всех блоков:

``line_start``, ``line_end``
    первая и последняя физическая строка блока включительно, вместе с разметкой: ограждения кода,
    строка-разделитель ``| --- |`` у ``table_header``, строка подчёркивания setext-заголовка.
``byte_start``, ``byte_end``
    ``[начало line_start; конец содержимого line_end)`` в исходных байтах, BOM учтён. ``null``,
    если байты пришлось декодировать с заменой.
``lines``
    ``[[строка, t0, t1], ...]``: отрезок ``block.text[t0:t1]``, который дала каждая строка
    содержимого. Синтетический ``"\\n"`` между строками в отрезки не входит.
``map``
    формат контракта: ``[[text_start, строка, столбец], ...]``. С ``text_start`` символы
    ``block.text`` идут подряд с (строка, столбец) источника до следующего якоря.
``spans``
    точная форма той же карты: ``[[t0, t1, строка, c0, c1, "v"|"s"], ...]``, отрезки по порядку и
    без пропусков. У каждого отрезка ``spans`` есть якорь ``map = [t0, строка, c0]``.

    * ``"v"``: дословная копия, ``block.text[t0:t1] == строка_источника[c0:c1]``;
    * ``"s"``: синтетический текст (разделитель или замена) вместо ``строка_источника[c0:c1]``.
      Этот диапазон может быть пустым, например ``"\\n"`` в конце строки без хвостовых пробелов.

    Символы разметки не попадают ни в ``block.text``, ни в карту. Обратное отображение:
    ``to_source``, ``span_to_source``, ``from_source``. Для блока без ``spans`` они строят отрезки
    из ``map``.
``section_ids``
    ID заголовков из ``section`` в том же порядке.

Поля по видам (``kind``):

``heading``
    ``level`` 1–6, ``style`` ``atx``/``setext``, ``section_end`` (последняя строка раздела до
    следующего заголовка того же или более высокого уровня), ``empty`` (в разделе, вместе с
    подразделами, нет ни одного блока, кроме заголовков; дублируется предупреждением
    ``empty_section``).
``paragraph``
    ``parent`` = ID пункта списка, если абзац продолжает пункт после пустой строки.
вложенные блоки
    ``table_header``, каждая ``table_row``, fenced-``code``, ``quote`` и ``other`` (HTML-комментарий)
    с отступом пункта получают ``parent`` = ID пункта; список после такого блока продолжается.
    Так таблица приёмки под «1. Комиссия» остаётся связанной со своим правилом.
``list_item``
    ``list = {id, ordered, marker, number, depth, item}``. ``id`` — номер списка в документе,
    ``item`` — номер пункта в списке с 1, ``depth`` — вложенность с 0. У пункта чек-листа
    (``- [ ]``/``- [x]``) есть ``checklist: true`` и ``checked``, у требования этих полей нет.
``table_header``
    ``table = {index, columns, align, delimiter_line, line_end, rows}``, ``cells``.
``table_row``
    ``table = {index, header_id, columns}`` (колонки повторены, чтобы строку можно было
    интерпретировать отдельно), ``row`` (номер строки данных с 1),
    ``cells = [{index, column, start, end}]``, где ``block.text[start:end]`` — ячейка.
    ``empty``: все ячейки пусты. ``template_choices``: индексы ячеек-шаблонов вида
    «Да / Нет / Не требуется», то есть строки бланка или чек-листа, а не требования.
``code``
    ``fence = {marker, info, open_line, close_line, closed}`` или ``null`` для кода с отступом,
    ``language`` (первое слово info-строки).
``quote``
    абзац внутри ``>``.
``other``
    ``subtype`` ``html_comment`` или ``front_matter``, текст дословный.

Если блок содержит ссылки, добавляется ``links = [{start, end, url}]``. Ссылки на сноски —
``footnotes = [{label, start, end, definition}]`` (``definition`` — ID абзаца-определения или ``null``);
у абзаца-определения ``footnote = {label, refs}``.

В TXT заголовков нет (``section == []``). Абзацы разделены пустой строкой. Строка с маркером
``-``, ``*``, ``•``, ``–``, ``—``, ``1.``, ``1)`` начинает ``list_item``, следующие непустые
строки её продолжают.

Предупреждения
--------------
``Document.warnings`` — объекты ``{code, message, stage: "read", block_ids?}``. Коды неполного
чтения из ``PARTIAL_READ_CODES``: ``decode_error`` (байты заменены на U+FFFD) и ``partial_read``
(строка не попала ни в один блок; это ошибка reader, тестами исключена). Остальные коды
информационные: ``encoding_fallback``, ``mixed_line_endings``, ``line_separator_char``,
``not_nfc``, ``empty_document``, ``empty_section``, ``unclosed_fence``, ``unclosed_comment``,
``table_cells_mismatch``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "Block",
    "Document",
    "Line",
    "Source",
    "block_at_line",
    "decode_source",
    "dumps_document",
    "from_source",
    "parse_bytes",
    "read_text",
    "source_lines",
    "span_to_source",
    "split_lines",
    "table_records",
    "to_source",
    "verify_document",
]

READER = "bcc_review.readers.text"
READER_VERSION = "1"
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
TEXT_SUFFIXES = frozenset({".txt"})


# --------------------------------------------------------------------------- модель (контракт v1)


@dataclass(slots=True)
class Block:
    id: str
    kind: str
    section: list[str]
    text: str
    loc: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "section": list(self.section),
            "text": self.text,
            "loc": json.loads(json.dumps(self.loc, ensure_ascii=False)),
        }


@dataclass(slots=True)
class Document:
    id: str
    title: str
    format: str
    blocks: list[Block]
    warnings: list[dict[str, Any]]
    source_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "format": self.format,
            "source_name": self.source_name,
            "blocks": [b.to_dict() for b in self.blocks],
            "warnings": json.loads(json.dumps(self.warnings, ensure_ascii=False)),
        }

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)


# --------------------------------------------------------------------------- байты → строки


@dataclass(frozen=True, slots=True)
class Source:
    text: str
    encoding: str
    bom: int
    exact: bool
    warnings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Line:
    no: int
    text: str
    eol: str
    byte_start: int | None
    byte_end: int | None


_BOMS = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)
_EOL = re.compile(r"\r\n|\r|\n")


def decode_source(data: bytes) -> Source:
    """Декодирует байты: BOM → UTF-8 → UTF-8 с заменой, если битых мест не больше
    ``max(8, размер / 50)`` (``decode_error``) → cp1251 (``encoding_fallback``) → UTF-8 с заменой."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            body = data[len(bom):]
            try:
                return Source(body.decode(enc), enc, len(bom), True)
            except UnicodeDecodeError as exc:
                note = (
                    f"байт {len(bom) + exc.start}: недопустимая последовательность {enc}, "
                    "заменена на U+FFFD; byte_start/byte_end не выдаются"
                )
                return Source(body.decode(enc, errors="replace"), enc, len(bom), False,
                              (("decode_error", note),))
    try:
        return Source(data.decode("utf-8"), "utf-8", 0, True)
    except UnicodeDecodeError as exc:
        bad = exc.start
    lossy = data.decode("utf-8", errors="replace")
    broken = lossy.count("\ufffd")
    if broken <= max(8, len(data) // 50):  # UTF-8 с единичными битыми байтами — не другая кодировка
        note = (
            f"байт {bad}: недопустимая последовательность UTF-8 (битых мест: {broken}), заменена на U+FFFD; "
            "byte_start/byte_end не выдаются"
        )
        return Source(lossy, "utf-8", 0, False, (("decode_error", note),))
    try:
        note = f"файл не в UTF-8 (байт {bad}); прочитан как cp1251"
        return Source(data.decode("cp1251"), "cp1251", 0, True, (("encoding_fallback", note),))
    except UnicodeDecodeError:
        note = (
            f"файл не в UTF-8 (байт {bad}) и не в cp1251; недопустимые байты заменены на U+FFFD, "
            "byte_start/byte_end не выдаются"
        )
        return Source(data.decode("utf-8", errors="replace"), "utf-8", 0, False, (("decode_error", note),))


def split_lines(source: Source) -> list[Line]:
    """Физические строки: окончания CRLF, LF, CR; последняя пустая строка после EOL не считается."""
    text, enc = source.text, source.encoding
    out: list[Line] = []
    offset: int | None = source.bom if source.exact else None
    pos = 0

    def add(content: str, eol: str) -> None:
        nonlocal offset
        start = offset
        end = None if start is None else start + len(content.encode(enc))
        out.append(Line(len(out) + 1, content, eol, start, end))
        if end is not None:
            offset = end + len(eol.encode(enc))

    for m in _EOL.finditer(text):
        add(text[pos:m.start()], m.group())
        pos = m.end()
    if pos < len(text):
        add(text[pos:], "")
    return out


def source_lines(data: bytes) -> list[str]:
    """Строки источника в той же нумерации, что у reader: ``source_lines(data)[n - 1]`` — строка n."""
    return [ln.text for ln in split_lines(decode_source(data))]


# --------------------------------------------------------------------------- текст с происхождением

_V, _S, _J = "v", "s", "j"  # дословно, синтетика, синтетический перевод строки между строками


class _Buf:
    """Видимый текст, у каждого символа хранится происхождение (строка, c0, c1, флаг)."""

    __slots__ = ("chars", "orig")

    def __init__(self) -> None:
        self.chars: list[str] = []
        self.orig: list[tuple[int, int, int, str]] = []

    def __len__(self) -> int:
        return len(self.chars)

    def text(self) -> str:
        return "".join(self.chars)

    def src(self, line: int, col: int, s: str) -> _Buf:
        for k, ch in enumerate(s):
            self.chars.append(ch)
            self.orig.append((line, col + k, col + k + 1, _V))
        return self

    def syn(self, s: str, line: int, c0: int, c1: int, flag: str = _S) -> _Buf:
        for ch in s:
            self.chars.append(ch)
            self.orig.append((line, c0, c1, flag))
        return self

    def extend(self, other: _Buf) -> None:
        self.chars.extend(other.chars)
        self.orig.extend(other.orig)


def _joiner(buf: _Buf, text: str, line: Line, a: int, b: int) -> None:
    """Добавляет разделитель; если источник между a и b совпадает с ним, это дословная копия."""
    if a <= b and line.text[a:b] == text:
        buf.src(line.no, a, text)
    else:
        buf.syn(text, line.no, min(a, b), max(a, b))


def _segments(buf: _Buf) -> list[list[Any]]:
    segs: list[list[Any]] = []
    for t, (line, c0, c1, flag) in enumerate(buf.orig):
        if segs:
            s = segs[-1]
            if flag == _V and s[6] == _V and s[2] == line and s[4] == c0:
                s[1], s[4] = t + 1, c1
                continue
            if flag != _V and s[6] == flag and (s[2], s[3], s[4]) == (line, c0, c1):
                s[1] = t + 1
                continue
        segs.append([t, t + 1, line, c0, c1, "v" if flag == _V else "s", flag])
    return [s[:6] for s in segs]


# --------------------------------------------------------------------------- инлайн-разметка

_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_LINK_TAIL = re.compile(
    r"\(\s*(<[^<>\n]*>|[^\s()<>]*(?:\([^\s()]*\)[^\s()<>]*)*)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
_AUTOLINK = re.compile(
    r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>]*|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~\-]+@[A-Za-z0-9]"
    r"(?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*)>"
)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_FOOTNOTE_REF = re.compile(r"\[\^([^\]\s]+)\]")
_FOOTNOTE_DEF = re.compile(r"^[ \t]{0,3}\[\^([^\]\s]+)\]:")
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def _ws(ch: str) -> bool:
    return ch.isspace()


def _punct(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "PS"


def _inline(raw: _Buf, notes: frozenset[str] = frozenset()) -> tuple[_Buf, list[int], list[list[Any]]]:
    """Снимает инлайн-разметку CommonMark/GFM (упрощённо, без потери символов текста).

    Возвращает видимый текст, ``before`` (длина видимого текста до сырого индекса i; длина n + 1)
    и ссылки ``[[t0, t1, url], ...]``; ссылка на сноску — ``[t0, t1, None, метка]``.
    ``notes`` — метки определённых сносок (casefold): ``[^1]`` даёт видимое ``[1]``, снимается только
    ``^``, остальные символы — дословные копии исходника.
    """
    ch, orig = raw.chars, raw.orig
    n = len(ch)
    s = "".join(ch)
    drop = [False] * n
    lit = [False] * n
    repl: dict[int, tuple[int, str]] = {}
    links: list[tuple[int, int, str]] = []

    # 1. Экранирование и код в обратных кавычках.
    i = 0
    while i < n:
        c = ch[i]
        if c == "\\" and i + 1 < n and ch[i + 1] in _ASCII_PUNCT and orig[i + 1][3] == _V:
            drop[i] = True
            lit[i + 1] = True
            i += 2
            continue
        if c == "`":
            j = i
            while j < n and ch[j] == "`":
                j += 1
            run, k, close = j - i, j, -1
            while k < n:
                if ch[k] == "`":
                    m = k
                    while m < n and ch[m] == "`":
                        m += 1
                    if m - k == run:
                        close = k
                        break
                    k = m
                else:
                    k += 1
            if close < 0:
                for t in range(i, j):
                    lit[t] = True
                i = j
                continue
            for t in (*range(i, j), *range(close, close + run)):
                drop[t] = True
            for t in range(j, close):
                lit[t] = True
            body = s[j:close]
            if len(body) >= 2 and body[0] in " \n" and body[-1] in " \n" and body.strip(" \n"):
                drop[j] = drop[close - 1] = True
            i = close + run
            continue
        i += 1

    def free(a: int, b: int) -> bool:
        return all(not lit[t] and not drop[t] for t in range(a, b))

    def same_line(a: int, b: int) -> bool:
        return all(orig[t][3] != _J for t in range(a, b))

    # 2. Ссылки, автоссылки, <br>, сущности.
    i = 0
    while i < n:
        if lit[i] or drop[i]:
            i += 1
            continue
        c = ch[i]
        if c == "[" and notes and i + 1 < n and ch[i + 1] == "^":
            m = _FOOTNOTE_REF.match(s, i)
            if m and m.group(1).casefold() in notes and free(i, m.end()) and same_line(i, m.end()):
                drop[i + 1] = True
                for t in range(i, m.end()):
                    lit[t] = True
                links.append((i, m.end(), None, m.group(1)))
                i = m.end()
                continue
        if c == "[":
            close = _close_bracket(ch, lit, drop, i)
            if close is not None and close + 1 < n and not lit[close + 1]:
                m = _LINK_TAIL.match(s, close + 1)
                if m and free(close + 1, m.end()):
                    if i > 0 and ch[i - 1] == "!" and not lit[i - 1] and not drop[i - 1]:
                        drop[i - 1] = True
                    drop[i] = True
                    for t in range(close, m.end()):
                        drop[t] = True
                    links.append((i + 1, close, m.group(1).strip("<>")))
            i += 1
            continue
        if c == "<":
            m = _AUTOLINK.match(s, i)
            if m and free(i, m.end()) and same_line(i, m.end()):
                drop[i] = drop[m.end() - 1] = True
                for t in range(i + 1, m.end() - 1):
                    lit[t] = True
                links.append((i + 1, m.end() - 1, m.group(1)))
                i = m.end()
                continue
            m = _BR.match(s, i)
            if m and free(i, m.end()) and same_line(i, m.end()):
                repl[i] = (m.end(), "\n")
                for t in range(i, m.end()):
                    lit[t] = True
                i = m.end()
                continue
        if c == "&":
            m = _ENTITY.match(s, i)
            if m and free(i, m.end()):
                value = html.unescape(m.group())
                if value != m.group():
                    repl[i] = (m.end(), value)
                    for t in range(i, m.end()):
                        lit[t] = True
                    i = m.end()
                    continue
        i += 1

    # 3. Выделение: *, _, ~ (упрощённый алгоритм CommonMark с правилом трёх).
    runs: list[list[Any]] = []
    i = 0
    while i < n:
        c = ch[i]
        if c in "*_~" and not lit[i] and not drop[i]:
            j = i
            while j < n and ch[j] == c and not lit[j] and not drop[j]:
                j += 1
            prev = ch[i - 1] if i > 0 else " "
            nxt = ch[j] if j < n else " "
            left = not _ws(nxt) and (not _punct(nxt) or _ws(prev) or _punct(prev))
            right = not _ws(prev) and (not _punct(prev) or _ws(nxt) or _punct(nxt))
            if c == "_":
                can_open = left and (not right or _punct(prev))
                can_close = right and (not left or _punct(nxt))
            else:
                can_open, can_close = left, right
            runs.append([c, i, j, can_open, can_close, j - i, j - i])
            i = j
        else:
            i += 1
    stack: list[int] = []
    for ri, r in enumerate(runs):
        c = r[0]
        if r[4]:
            while r[5] > 0:
                found = None
                for si in range(len(stack) - 1, -1, -1):
                    o = runs[stack[si]]
                    if o[0] != c or o[5] == 0:
                        continue
                    if c == "~":
                        if o[6] != r[6] or r[6] > 2:
                            continue
                    elif (o[4] or r[3]) and (o[6] + r[6]) % 3 == 0 and (o[6] % 3 or r[6] % 3):
                        continue
                    found = si
                    break
                if found is None:
                    break
                o = runs[stack[found]]
                use = r[6] if c == "~" else (2 if o[5] >= 2 and r[5] >= 2 else 1)
                for t in range(o[1] + o[5] - use, o[1] + o[5]):
                    drop[t] = True
                o[5] -= use
                start = r[2] - r[5]
                for t in range(start, start + use):
                    drop[t] = True
                r[5] -= use
                del stack[found + 1:]
                if o[5] == 0:
                    stack.pop()
        if r[3] and r[5] > 0:
            stack.append(ri)

    # 4. Сборка видимого текста.
    out = _Buf()
    before = [0] * (n + 1)
    i = 0
    while i < n:
        before[i] = len(out)
        if i in repl:
            end, value = repl[i]
            line, c0 = orig[i][0], orig[i][1]
            for t in range(i + 1, end):
                before[t] = len(out)
            out.syn(value, line, c0, orig[end - 1][2])
            i = end
            continue
        if not drop[i]:
            out.chars.append(ch[i])
            out.orig.append(orig[i])
        i += 1
    before[n] = len(out)
    return out, before, [[before[e[0]], before[e[1]], *e[2:]] for e in links]


def _close_bracket(ch: list[str], lit: list[bool], drop: list[bool], i: int) -> int | None:
    depth = 0
    for k in range(i, len(ch)):
        if lit[k] or drop[k]:
            continue
        if ch[k] == "[":
            depth += 1
        elif ch[k] == "]":
            depth -= 1
            if depth == 0:
                return k
    return None


# --------------------------------------------------------------------------- блоки


@dataclass(slots=True)
class _Pending:
    kind: str
    line_start: int
    line_end: int
    buf: _Buf
    lines: list[list[int]]
    loc: dict[str, Any]
    links: list[list[Any]]


def _flow(parts: list[tuple[Line, int, int]], *, inline: bool,
          notes: frozenset[str] = frozenset()) -> tuple[_Buf, list[list[int]], list]:
    """Склеивает части строк через синтетический "\\n" и (для Markdown) снимает инлайн-разметку."""
    raw = _Buf()
    ranges: list[tuple[int, int, int]] = []
    for k, (ln, c0, c1) in enumerate(parts):
        r0 = len(raw)
        raw.src(ln.no, c0, ln.text[c0:c1])
        ranges.append((ln.no, r0, len(raw)))
        if k + 1 < len(parts):
            raw.syn("\n", ln.no, c1, len(ln.text), _J)
    if not inline:
        return raw, [[no, a, b] for no, a, b in ranges], []
    vis, before, links = _inline(raw, notes)
    return vis, [[no, before[a], before[b]] for no, a, b in ranges], links


def _indent(s: str) -> int:
    w = 0
    for c in s:
        if c == " ":
            w += 1
        elif c == "\t":
            w += 4 - w % 4
        else:
            break
    return w


def _skip_cols(s: str, cols: int) -> int:
    """Индекс после снятия не более ``cols`` столбцов ведущих пробелов и табуляций."""
    w = k = 0
    while k < len(s) and w < cols and s[k] in " \t":
        w += 1 if s[k] == " " else 4 - w % 4
        k += 1
    return k


def _lstrip_at(s: str, k: int) -> int:
    while k < len(s) and s[k] in " \t":
        k += 1
    return k


def _rstrip_len(s: str) -> int:
    return len(s.rstrip())


def _unescaped_pipes(s: str) -> list[int]:
    out = []
    for k, c in enumerate(s):
        if c == "|":
            b = k - 1
            while b >= 0 and s[b] == "\\":
                b -= 1
            if (k - 1 - b) % 2 == 0:
                out.append(k)
    return out


def _split_row(s: str) -> list[tuple[int, int]] | None:
    """Ячейки строки GFM-таблицы как диапазоны столбцов без крайних пробелов; None — нет ``|``."""
    pipes = _unescaped_pipes(s)
    if not pipes:
        return None
    left, right = _lstrip_at(s, 0), _rstrip_len(s)
    if pipes[0] == left:
        left += 1
        pipes = pipes[1:]
    if pipes and pipes[-1] == right - 1:
        right -= 1
        pipes = pipes[:-1]
    starts = [left] + [p + 1 for p in pipes]
    ends = pipes + [right]
    cells = []
    for a, b in zip(starts, ends, strict=True):
        a2 = min(_lstrip_at(s, a), b)
        b2 = max(a2, a + len(s[a:b].rstrip()))
        cells.append((a2, b2))
    return cells


_ATX = re.compile(r"^[ \t]*(#{1,6})(?=[ \t]|$)")
_ATX_CLOSE = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_FENCE_OPEN = re.compile(r"^(?P<ind>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_FENCE_CLOSE = re.compile(r"^(?P<ind>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*$")
_THEMATIC = re.compile(r"^[ \t]*(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_SETEXT = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")
_LIST = re.compile(r"^(?P<ind>[ \t]*)(?P<marker>[*+-]|(?P<num>\d{1,9})[.)])(?P<sp>[ \t]+|$)")
_TASK = re.compile(r"\[(?P<mark>[ xX])\](?:[ \t]+|$)")
_QUOTE = re.compile(r"^[ \t]*> ?")
_HTML_COMMENT = re.compile(r"^[ \t]*<!--")
_DELIM_CELL = re.compile(r"^:?-+:?$")
_FRONT_KEY = re.compile(r"^[A-Za-z0-9_][\w\- ]*:")
_CHOICE_WORD = r"(?:да|нет|не требуется|не применимо|yes|no|n/a|na)"
_CHOICE = re.compile(rf"^{_CHOICE_WORD}(?:\s*/\s*{_CHOICE_WORD})+$", re.IGNORECASE)


def _footnote_labels(lines: list[Line]) -> frozenset[str]:
    """Метки определений ``[^метка]:`` вне fenced-блоков (casefold, как метки GFM)."""
    labels: set[str] = set()
    fence: str | None = None
    for ln in lines:
        if fence is not None:
            mc = _FENCE_CLOSE.match(ln.text)
            if mc and mc["fence"][0] == fence[0] and len(mc["fence"]) >= len(fence):
                fence = None
            continue
        mo = _FENCE_OPEN.match(ln.text)
        if mo and not (mo["fence"][0] == "`" and "`" in mo["info"]):
            fence = mo["fence"]
            continue
        m = _FOOTNOTE_DEF.match(ln.text)
        if m:
            labels.add(m.group(1).casefold())
    return frozenset(labels)


class _Markdown:
    def __init__(self, lines: list[Line], warnings: list[tuple[str, str, int | None]]) -> None:
        self.lines = lines
        self.n = len(lines)
        self.warnings = warnings
        self.out: list[_Pending] = []
        self.par: dict[str, Any] | None = None
        self.lists: list[dict[str, Any]] = []
        self.list_count = 0
        self.table_count = 0
        self.structural: set[int] = set()
        self.notes = _footnote_labels(lines)

    # -- управление открытым абзацем и списками

    def run(self) -> list[_Pending]:
        i = self._front_matter()
        blank = True
        while i < self.n:
            if not self.lines[i].text.strip():
                self._flush()
                blank = True
                i += 1
                continue
            i = self._line(i, blank)
            blank = False
        self._flush()
        return self.out

    def _base_for(self, ind: int) -> int:
        base = 0
        for lst in self.lists:
            if lst["content"] <= ind:
                base = lst["content"]
            else:
                break
        return base

    def _pop(self, ind: int) -> None:
        while self.lists and ind < self.lists[-1]["content"]:
            self.lists.pop()

    def _nest(self, first: int) -> None:
        """Блоки ``out[first:]`` лежат внутри открытого пункта списка: ``loc.parent`` = его строка."""
        if self.lists:
            for p in self.out[first:]:
                p.loc["parent"] = self.lists[-1]["last"]  # ID подставит _finish

    def _part(self, ln: Line, c0: int | None = None) -> tuple[Line, int, int]:
        s = ln.text
        a = _lstrip_at(s, 0 if c0 is None else c0)
        return ln, a, max(a, _rstrip_len(s))

    def _flush(self) -> None:
        par, self.par = self.par, None
        if par is None:
            return
        parts = list(par["parts"])
        for k in range(len(parts) - 1):  # обратная косая в конце строки — жёсткий перенос
            ln, c0, c1 = parts[k]
            tail = len(ln.text[c0:c1]) - len(ln.text[c0:c1].rstrip("\\"))
            if tail % 2 == 1:
                parts[k] = (ln, c0, c1 - 1)
        buf, lines, links = _flow(parts, inline=True, notes=self.notes)
        end = parts[-1][0].no if parts else par["start"]
        self.out.append(_Pending(par["kind"], par["start"], end, buf, lines, par["loc"], links))

    # -- разбор одной непустой строки

    def _line(self, i: int, blank: bool) -> int:
        ln = self.lines[i]
        s = ln.text
        ind = _indent(s)
        rel = ind - self._base_for(ind)
        par = self.par
        plain = par is not None and par["kind"] == "paragraph" and "parent" not in par["loc"]

        if plain and not blank and rel <= 3 and _SETEXT.match(s):
            self.par = None
            level = 1 if s.strip()[0] == "=" else 2
            buf, lines, links = _flow(par["parts"], inline=True, notes=self.notes)
            loc = {"level": level, "style": "setext", "empty": False, "section_end": 0}
            self.out.append(_Pending("heading", par["start"], ln.no, buf, lines, loc, links))
            return i + 1
        if rel <= 3 and _THEMATIC.match(s):
            self._flush()
            self.lists.clear()
            self.structural.add(ln.no)
            return i + 1
        m = _ATX.match(s)
        if m and rel <= 3:
            self._flush()
            self.lists.clear()
            self._atx(ln, m)
            return i + 1
        m = _FENCE_OPEN.match(s)
        if m and rel <= 3 and not (m["fence"][0] == "`" and "`" in m["info"]):
            self._flush()
            self._pop(ind)
            first = len(self.out)
            nxt = self._fence(i, m)
            self._nest(first)
            return nxt
        if rel <= 3 and "|" in s:
            head = self._table_head(i)
            if head is not None:
                self._flush()
                self._pop(ind)  # таблица с отступом пункта остаётся в пункте, список не рвётся
                first = len(self.out)
                nxt = self._table(i, *head)
                self._nest(first)
                return nxt
        if rel <= 3 and _HTML_COMMENT.match(s):
            self._flush()
            self._pop(ind)
            first = len(self.out)
            nxt = self._comment(i)
            self._nest(first)
            return nxt
        m = _QUOTE.match(s)
        if m and rel <= 3:
            c0 = _lstrip_at(s, m.end())
            if par is not None and par["kind"] == "quote" and not blank and c0 < len(s):
                par["parts"].append(self._part(ln, c0))
                return i + 1
            self._flush()
            self._pop(ind)
            if c0 < len(s):
                qloc = {"parent": self.lists[-1]["last"]} if self.lists else {}
                self.par = {"kind": "quote", "start": ln.no, "parts": [self._part(ln, c0)], "loc": qloc}
            else:
                self.structural.add(ln.no)  # пустая строка цитаты разделяет абзацы
            return i + 1
        m = _LIST.match(s)
        if m and self._can_start_item(m, s, plain and not blank):
            self._flush()
            self._item(ln, m)
            return i + 1
        if par is not None and not blank:
            par["parts"].append(self._part(ln))
            return i + 1
        self._flush()
        self._pop(ind)
        if not self.lists and ind >= 4:
            return self._indented_code(i)
        loc: dict[str, Any] = {}
        if self.lists:
            loc["parent"] = self.lists[-1]["last"]  # строка пункта; ID подставит _finish
        m = _FOOTNOTE_DEF.match(s)
        if m and m.group(1).casefold() in self.notes:
            loc["footnote"] = m.group(1)  # определение сноски; ссылки подставит _finish
        self.par = {"kind": "paragraph", "start": ln.no, "parts": [self._part(ln)], "loc": loc}
        return i + 1

    def _can_start_item(self, m: re.Match[str], s: str, interrupts_paragraph: bool) -> bool:
        if not interrupts_paragraph:
            return True
        if m["num"] is not None and int(m["num"]) != 1:
            return False
        return bool(s[m.end():].strip())

    # -- конструкции

    def _front_matter(self) -> int:
        if self.n < 3 or self.lines[0].text.strip() != "---":
            return 0
        if not _FRONT_KEY.match(self.lines[1].text):
            return 0
        for k in range(1, self.n):
            if self.lines[k].text.strip() in ("---", "..."):
                parts = [(ln, 0, len(ln.text)) for ln in self.lines[1:k]]
                buf, lines, _ = _flow(parts, inline=False)
                self.out.append(_Pending("other", 1, k + 1, buf, lines, {"subtype": "front_matter"}, []))
                return k + 1
        return 0

    def _atx(self, ln: Line, m: re.Match[str]) -> None:
        s = ln.text
        c0 = _lstrip_at(s, m.end())
        c1 = max(c0, _rstrip_len(s))
        content = s[c0:c1]
        if re.fullmatch(r"#+", content):
            c1 = c0
        else:
            mm = _ATX_CLOSE.search(content)
            if mm:
                c1 = c0 + mm.start()
        buf, lines, links = _flow([(ln, c0, c1)], inline=True, notes=self.notes)
        loc = {"level": len(m.group(1)), "style": "atx", "empty": False, "section_end": 0}
        self.out.append(_Pending("heading", ln.no, ln.no, buf, lines, loc, links))

    def _fence(self, i: int, m: re.Match[str]) -> int:
        open_ln = self.lines[i]
        width, fence, info = _indent(m["ind"]), m["fence"], m["info"].strip()
        close = None
        k = i + 1
        while k < self.n:
            mc = _FENCE_CLOSE.match(self.lines[k].text)
            if mc and mc["fence"][0] == fence[0] and len(mc["fence"]) >= len(fence):
                close = k
                break
            k += 1
        content = self.lines[i + 1:close if close is not None else self.n]
        parts = [(ln, _skip_cols(ln.text, width), len(ln.text)) for ln in content]
        buf, lines, _ = _flow(parts, inline=False)
        last = self.lines[close].no if close is not None else (self.lines[-1].no if content else open_ln.no)
        if close is None:
            self.warnings.append((
                "unclosed_fence",
                f"строка {open_ln.no}: блок кода {fence} не закрыт; строки {open_ln.no + 1}–{last} "
                "прочитаны как код",
                open_ln.no,
            ))
        loc = {
            "fence": {"marker": fence, "info": info, "open_line": open_ln.no,
                      "close_line": self.lines[close].no if close is not None else None,
                      "closed": close is not None},
            "language": info.split()[0] if info else "",
        }
        self.out.append(_Pending("code", open_ln.no, last, buf, lines, loc, []))
        return (close + 1) if close is not None else self.n

    def _indented_code(self, i: int) -> int:
        k, last = i, i
        while k < self.n:
            t = self.lines[k].text
            if t.strip() and _indent(t) < 4:
                break
            if t.strip():
                last = k
            k += 1
        content = self.lines[i:last + 1]
        parts = [(ln, min(_skip_cols(ln.text, 4), len(ln.text)), len(ln.text)) for ln in content]
        buf, lines, _ = _flow(parts, inline=False)
        loc = {"fence": None, "language": ""}
        self.out.append(_Pending("code", content[0].no, content[-1].no, buf, lines, loc, []))
        return last + 1

    def _comment(self, i: int) -> int:
        start = self.lines[i].text.index("<!--")
        k = i
        while k < self.n:
            from_col = start + 4 if k == i else 0
            if "-->" in self.lines[k].text[from_col:]:
                break
            k += 1
        if k == self.n:
            k = self.n - 1
            self.warnings.append(("unclosed_comment",
                                  f"строка {self.lines[i].no}: HTML-комментарий не закрыт до конца файла",
                                  self.lines[i].no))
        parts = [(ln, 0, _rstrip_len(ln.text)) for ln in self.lines[i:k + 1]]
        buf, lines, _ = _flow(parts, inline=False)
        self.out.append(_Pending("other", self.lines[i].no, self.lines[k].no, buf, lines,
                                 {"subtype": "html_comment"}, []))
        return k + 1

    def _table_head(self, i: int) -> tuple[list[tuple[int, int]], list[str]] | None:
        if i + 1 >= self.n:
            return None
        head = _split_row(self.lines[i].text)
        delim_line = self.lines[i + 1].text
        if head is None or "|" not in delim_line or "-" not in delim_line:
            return None
        delim = _split_row(delim_line)
        if delim is None or len(delim) != len(head):
            return None
        align = []
        for a, b in delim:
            cell = delim_line[a:b].replace(" ", "")
            if not _DELIM_CELL.match(cell):
                return None
            left, right = cell.startswith(":"), cell.endswith(":")
            align.append("center" if left and right else "left" if left else "right" if right else "")
        return head, align

    def _row_buf(self, ln: Line, cells: list[tuple[int, int]], columns: list[str | None]):
        buf = _Buf()
        locs: list[dict[str, Any]] = []
        links: list[list[Any]] = []
        prev_end = 0
        for idx, (c0, c1) in enumerate(cells):
            if idx:
                _joiner(buf, " | ", ln, prev_end, c0)
            vis, _, lk = _inline(_Buf().src(ln.no, c0, ln.text[c0:c1]), self.notes)
            start = len(buf)
            buf.extend(vis)
            links.extend([e[0] + start, e[1] + start, *e[2:]] for e in lk)
            column = columns[idx] if idx < len(columns) else None
            locs.append({"index": idx, "column": column, "start": start, "end": len(buf)})
            prev_end = c1
        return buf, locs, links

    def _table(self, i: int, head: list[tuple[int, int]], align: list[str]) -> int:
        self.table_count += 1
        tno = self.table_count
        head_ln = self.lines[i]
        hbuf, hcells, hlinks = self._row_buf(head_ln, head, [None] * len(head))
        htext = hbuf.text()
        columns = [htext[c["start"]:c["end"]] for c in hcells]
        for c in hcells:
            c["column"] = htext[c["start"]:c["end"]]
        rows: list[tuple[Line, list[tuple[int, int]]]] = []
        k = i + 2
        while k < self.n:
            t = self.lines[k].text
            if not t.strip() or _FENCE_OPEN.match(t) or _ATX.match(t) or _QUOTE.match(t):
                break
            cells = _split_row(t)
            if cells is None:
                break
            rows.append((self.lines[k], cells))
            k += 1
        line_end = rows[-1][0].no if rows else self.lines[i + 1].no
        hloc = {
            "table": {"index": tno, "columns": columns, "align": align,
                      "delimiter_line": self.lines[i + 1].no, "line_end": line_end, "rows": len(rows)},
            "cells": hcells,
        }
        self.out.append(_Pending("table_header", head_ln.no, self.lines[i + 1].no, hbuf,
                                 [[head_ln.no, 0, len(hbuf)]], hloc, hlinks))
        for r, (ln, cells) in enumerate(rows, start=1):
            if len(cells) < len(columns):
                self.warnings.append((
                    "table_cells_mismatch",
                    f"строка {ln.no}: в строке таблицы {len(cells)} ячеек из {len(columns)}; "
                    "недостающие добавлены пустыми",
                    ln.no,
                ))
                end = _rstrip_len(ln.text)
                cells = cells + [(end, end)] * (len(columns) - len(cells))
            elif len(cells) > len(columns):
                self.warnings.append((
                    "table_cells_mismatch",
                    f"строка {ln.no}: в строке таблицы {len(cells)} ячеек из {len(columns)}; "
                    "лишние сохранены с column = null",
                    ln.no,
                ))
            buf, locs, links = self._row_buf(ln, cells, columns)
            text = buf.text()
            values = [text[c["start"]:c["end"]] for c in locs]
            loc: dict[str, Any] = {
                "table": {"index": tno, "header_id": head_ln.no, "columns": list(columns)},
                "row": r,
                "cells": locs,
                "empty": not any(v.strip() for v in values),
            }
            choices = [c["index"] for c, v in zip(locs, values, strict=True) if _CHOICE.match(v.strip())]
            if choices:
                loc["template_choices"] = choices
            self.out.append(_Pending("table_row", ln.no, ln.no, buf, [[ln.no, 0, len(buf)]], loc, links))
        return k

    def _item(self, ln: Line, m: re.Match[str]) -> None:
        s = ln.text
        mi = _indent(m["ind"])
        marker, num = m["marker"], m["num"]
        ordered = num is not None
        mtype = marker[-1] if ordered else marker
        sp_width = _indent(m["sp"].replace("\t", "    ")) if m["sp"] else 1
        rest = s[m.end():]
        if sp_width > 4 or not rest.strip():
            sp_width = 1
        content_indent = mi + len(marker) + sp_width
        lst = None
        while self.lists:
            top = self.lists[-1]
            if mi >= top["content"]:
                break
            if mi >= top["indent"] and top["type"] == mtype:
                lst = top
                break
            self.lists.pop()
        if lst is None:
            self.list_count += 1
            lst = {"id": self.list_count, "indent": mi, "type": mtype, "ordered": ordered,
                   "depth": len(self.lists), "items": 0}
            self.lists.append(lst)
        lst["content"] = content_indent
        lst["items"] += 1
        lst["last"] = ln.no
        c0 = _lstrip_at(s, m.end())
        extra: dict[str, Any] = {}
        tm = _TASK.match(s, c0)
        if tm:
            extra = {"checklist": True, "checked": tm["mark"] in "xX"}
            c0 = _lstrip_at(s, tm.end())
        loc = {"list": {"id": lst["id"], "ordered": ordered, "marker": marker,
                        "number": int(num) if ordered else None, "depth": lst["depth"],
                        "item": lst["items"]}}
        loc.update(extra)
        parts = [self._part(ln, c0)] if c0 < _rstrip_len(s) else []
        self.par = {"kind": "list_item", "start": ln.no, "parts": parts, "loc": loc}


_TXT_ITEM = re.compile(r"^[ \t]*(?P<marker>[-*•–—]|(?P<num>\d{1,3})[.)])[ \t]+(?=\S)")


def _parse_txt(lines: list[Line]) -> list[_Pending]:
    out: list[_Pending] = []
    cur: dict[str, Any] | None = None
    list_id = items = 0
    in_list = False

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            buf, lv, _ = _flow(cur["parts"], inline=False)
            out.append(_Pending(cur["kind"], cur["start"], cur["parts"][-1][0].no, buf, lv, cur["loc"], []))
            cur = None

    for ln in lines:
        s = ln.text
        if not s.strip():
            flush()
            in_list = False
            continue
        part = (ln, _lstrip_at(s, 0), _rstrip_len(s))
        m = _TXT_ITEM.match(s)
        if m:
            flush()
            if not in_list:
                list_id += 1
                items = 0
                in_list = True
            items += 1
            num = m["num"]
            loc = {"list": {"id": list_id, "ordered": num is not None, "marker": m["marker"],
                            "number": int(num) if num is not None else None, "depth": 0, "item": items}}
            cur = {"kind": "list_item", "start": ln.no, "parts": [(ln, m.end(), _rstrip_len(s))], "loc": loc}
        elif cur is not None:
            cur["parts"].append(part)
        else:
            cur = {"kind": "paragraph", "start": ln.no, "parts": [part], "loc": {}}
    flush()
    return out


# --------------------------------------------------------------------------- сборка Document


def _ranges(nums: list[int]) -> str:
    out, k = [], 0
    while k < len(nums):
        j = k
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[k]) if j == k else f"{nums[k]}–{nums[j]}")
        k = j + 1
    return ", ".join(out)


def _finish(pendings: list[_Pending], lines: list[Line], structural: set[int],
            raw_warnings: list[tuple[str, str, int | None]]) -> tuple[list[Block], list[dict[str, Any]]]:
    by_line = {p.line_start: f"b{k:04d}" for k, p in enumerate(pendings, start=1)}
    assert len(by_line) == len(pendings), "каждый блок начинается со своей строки"
    warnings: list[dict[str, Any]] = []
    for code, message, line in raw_warnings:
        w: dict[str, Any] = {"code": code, "message": message, "stage": "read"}
        if line is not None and line in by_line:
            w["block_ids"] = [by_line[line]]
        warnings.append(w)

    stack: list[tuple[int, str, str]] = []
    blocks: list[Block] = []
    for p in pendings:
        bid = by_line[p.line_start]
        text = p.buf.text()
        if p.kind == "heading":
            level = p.loc["level"]
            while stack and stack[-1][0] >= level:
                stack.pop()
        first, last = lines[p.line_start - 1], lines[p.line_end - 1]
        loc: dict[str, Any] = {
            "line_start": p.line_start,
            "line_end": p.line_end,
            "byte_start": first.byte_start,
            "byte_end": last.byte_end,
        }
        loc.update(p.loc)
        if "parent" in loc:
            loc["parent"] = by_line[loc["parent"]]
        if "table" in loc and "header_id" in loc["table"]:
            loc["table"] = dict(loc["table"], header_id=by_line[loc["table"]["header_id"]])
        links = [e for e in p.links if e[2] is not None]
        if links:
            loc["links"] = [{"start": a, "end": b, "url": url} for a, b, url in links]
        refs = [e for e in p.links if e[2] is None and not ("footnote" in p.loc and e[0] == 0)]
        if refs:
            loc["footnotes"] = [{"label": lab, "start": a, "end": b, "definition": None}
                                for a, b, _url, lab in refs]
        spans = _segments(p.buf)
        loc["lines"] = p.lines
        loc["map"] = [[t0, line, c0] for t0, _t1, line, c0, _c1, _kind in spans]
        loc["spans"] = spans
        loc["section_ids"] = [h[2] for h in stack]
        blocks.append(Block(bid, p.kind, [h[1] for h in stack], text, loc))
        if p.kind == "heading":
            stack.append((p.loc["level"], text, bid))

    defs: dict[str, Block] = {}
    for b in blocks:
        if "footnote" in b.loc:
            label = b.loc["footnote"]
            b.loc["footnote"] = {"label": label, "refs": []}
            defs.setdefault(label.casefold(), b)
    for b in blocks:
        for ref in b.loc.get("footnotes", []):
            target = defs.get(ref["label"].casefold())
            if target is not None:
                ref["definition"] = target.id
                if b.id not in target.loc["footnote"]["refs"]:
                    target.loc["footnote"]["refs"].append(b.id)

    last_line = lines[-1].no if lines else 0
    for idx, b in enumerate(blocks):
        if b.kind != "heading":
            continue
        level, content, end = b.loc["level"], False, last_line
        for nb in blocks[idx + 1:]:
            if nb.kind == "heading" and nb.loc["level"] <= level:
                end = nb.loc["line_start"] - 1
                break
            content = content or nb.kind != "heading"
        b.loc["section_end"] = end
        b.loc["empty"] = not content
        if not content:
            warnings.append({"code": "empty_section", "stage": "read", "block_ids": [b.id],
                             "message": f"строка {b.loc['line_start']}: раздел «{b.text}» без содержимого"})

    covered = set(structural)
    for b in blocks:
        covered.update(range(b.loc["line_start"], b.loc["line_end"] + 1))
    missing = [ln.no for ln in lines if ln.text.strip() and ln.no not in covered]
    if missing:
        warnings.append({"code": "partial_read", "stage": "read",
                         "message": f"строки не попали ни в один блок (ошибка reader): {_ranges(missing)}"})
    return blocks, warnings


def _title(blocks: list[Block], name: str) -> str:
    heads = [b for b in blocks if b.kind == "heading" and b.text.strip()]
    for b in heads:
        if b.loc["level"] == 1:
            return b.text.strip()
    if heads:
        return heads[0].text.strip()
    for b in blocks:
        first = b.text.strip().split("\n", 1)[0].strip()
        if first:
            return first if len(first) <= 120 else first[:119] + "…"
    return name


_FORMATS = {"md": "markdown", "markdown": "markdown", "txt": "text", "text": "text"}


def parse_bytes(data: bytes, fmt: str, name: str = "") -> Document:
    """Разбирает байты как Markdown (``"markdown"``/``"md"``) или текст (``"text"``/``"txt"``).

    ``name`` — имя исходного файла (``Document.source_name``; его основа — запасной заголовок).
    """
    if fmt not in _FORMATS:
        raise ValueError(f"неизвестный формат {fmt!r}: ожидается 'markdown' или 'text'")
    fmt = _FORMATS[fmt]
    digest = hashlib.sha256(data).hexdigest()
    source = decode_source(data)
    raw: list[tuple[str, str, int | None]] = [(code, msg, None) for code, msg in source.warnings]
    lines = split_lines(source)
    eols = sorted({ln.eol for ln in lines if ln.eol})
    if len(eols) > 1:
        names = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}
        found = ", ".join(names[e] for e in eols)
        raw.append(("mixed_line_endings", f"смешанные окончания строк: {found}", None))
    for ch, label in ((" ", "U+2028"), (" ", "U+2029"), ("\x85", "U+0085")):
        if ch in source.text:
            raw.append(("line_separator_char",
                        f"символ {label} не считается переводом строки; номера строк по CR/LF", None))
    if not unicodedata.is_normalized("NFC", source.text):
        raw.append(("not_nfc", "текст не в NFC: цитаты сравнивать после нормализации, столбцы — по исходнику",
                    None))
    if not lines:
        raw.append(("empty_document", "пустой документ", None))
    if fmt == "markdown":
        parser = _Markdown(lines, raw)
        pendings, structural = parser.run(), parser.structural
    else:
        pendings, structural = _parse_txt(lines), set()
    blocks, warnings = _finish(pendings, lines, structural, raw)
    return Document(digest, _title(blocks, Path(name).stem if name else ""), fmt, blocks, warnings, name)


def read_text(path: Path | str) -> Document:
    """Читает .md/.markdown или .txt. ``Document.id`` = SHA-256 байтов файла."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        fmt = "markdown"
    elif suffix in TEXT_SUFFIXES:
        fmt = "text"
    else:
        raise ValueError(f"read_text: расширение {suffix or '(нет)'} не поддерживается; нужно .md или .txt")
    return parse_bytes(p.read_bytes(), fmt, p.name)


# --------------------------------------------------------------------------- обратная привязка


def _spans(block: Block) -> list[list[Any]]:
    """``loc.spans``; для блока только с контрактным ``loc.map`` отрезки выводятся из якорей."""
    if "spans" in block.loc:
        return block.loc["spans"]
    anchors = block.loc.get("map") or []
    out = []
    for k, (t0, line, col) in enumerate(anchors):
        t1 = anchors[k + 1][0] if k + 1 < len(anchors) else len(block.text)
        out.append([t0, t1, line, col, col + (t1 - t0), "v"])
    return out


def _check_offset(block: Block, offset: int) -> None:
    if not 0 <= offset <= len(block.text):
        raise ValueError(f"{block.id}: смещение {offset} вне 0..{len(block.text)}")


def to_source(block: Block, offset: int, *, end: bool = False) -> tuple[int, int]:
    """Смещение в ``block.text`` → (строка, столбец) источника.

    ``end=False`` даёт позицию символа ``block.text[offset]``, ``end=True`` — позицию сразу после
    символа ``block.text[offset - 1]`` (правая граница). Внутри синтетического отрезка возвращается
    начало (или конец при ``end``) заменённого диапазона.
    """
    _check_offset(block, offset)
    segs = _spans(block)
    if not segs:
        return block.loc["line_start"], 0
    for t0, t1, line, c0, c1, kind in segs:
        if (t0 < offset <= t1) if end else (t0 <= offset < t1):
            if kind == "v":
                return line, c0 + offset - t0
            return line, c1 if end else c0
    first, last = segs[0], segs[-1]
    return (first[2], first[3]) if end else (last[2], last[4])


def span_to_source(block: Block, start: int, end: int) -> list[tuple[int, int, int]]:
    """``block.text[start:end]`` → ``[(строка, c0, c1), ...]`` по одной записи на строку источника.

    Для цитаты внутри одной строки без снятой разметки ``lines[строка - 1][c0:c1] == цитата``.
    Если внутри была разметка (``**``), диапазон источника её включает.
    """
    _check_offset(block, start)
    _check_offset(block, end)
    if start > end:
        raise ValueError(f"{block.id}: start {start} > end {end}")
    if start == end:
        line, col = to_source(block, start)
        return [(line, col, col)]
    pieces: list[list[int]] = []
    for t0, t1, line, c0, c1, kind in _spans(block):
        if t1 <= start or t0 >= end:
            continue
        if kind == "v":
            a, b = c0 + max(start, t0) - t0, c0 + min(end, t1) - t0
        else:
            a, b = c0, c1
        if pieces and pieces[-1][0] == line:
            pieces[-1][1] = min(pieces[-1][1], a)
            pieces[-1][2] = max(pieces[-1][2], b)
        else:
            pieces.append([line, a, b])
    return [(ln, a, b) for ln, a, b in pieces if b > a] or [(pieces[0][0], pieces[0][1], pieces[0][1])]


def from_source(block: Block, line: int, col: int) -> int:
    """(строка, столбец) источника → смещение в ``block.text`` (ближайшее следующее, если символ скрыт)."""
    segs = _spans(block)
    for t0, _t1, ln, c0, c1, kind in segs:
        if ln == line and kind == "v" and c0 <= col < c1:
            return t0 + col - c0
    for t0, _t1, ln, c0, _c1, _kind in segs:
        if (ln, c0) >= (line, col):
            return t0
    return len(block.text)


def block_at_line(document: Document, line: int) -> Block | None:
    """Блок, чьё содержимое занимает строку ``line``; иначе блок, в чьи границы она входит."""
    for b in document.blocks:
        if any(entry[0] == line for entry in b.loc["lines"]):
            return b
    for b in document.blocks:
        if b.loc["line_start"] <= line <= b.loc["line_end"]:
            return b
    return None


def verify_document(document: Document, data: bytes) -> list[str]:
    """Проверяет ``loc`` по исходным байтам без обращения к модели; пустой список — всё сходится."""
    problems: list[str] = []
    if hashlib.sha256(data).hexdigest() != document.id:
        problems.append("SHA-256 источника не совпадает с Document.id")
        return problems
    src = decode_source(data)
    lines = split_lines(src)
    for b in document.blocks:
        segs = _spans(b)
        if b.loc.get("map") != [[t0, line, c0] for t0, _t1, line, c0, _c1, _k in segs]:
            problems.append(f"{b.id}: loc.map не совпадает с loc.spans")
        pos = 0
        for t0, t1, line, c0, c1, kind in segs:
            if t0 != pos or t1 <= t0:
                problems.append(f"{b.id}: spans не покрывают текст подряд на смещении {pos}")
                break
            if not 1 <= line <= len(lines) or not 0 <= c0 <= c1 <= len(lines[line - 1].text):
                problems.append(f"{b.id}: отрезок вне строки {line}")
            elif kind == "v" and b.text[t0:t1] != lines[line - 1].text[c0:c1]:
                problems.append(f"{b.id}: дословный отрезок [{t0}:{t1}] не совпадает со строкой {line}")
            pos = t1
        if pos != len(b.text):
            problems.append(f"{b.id}: spans покрывают {pos} из {len(b.text)} символов")
        if not b.loc["line_start"] <= b.loc["line_end"]:
            problems.append(f"{b.id}: line_start > line_end")
        if src.exact:
            first, last = lines[b.loc["line_start"] - 1], lines[b.loc["line_end"] - 1]
            if (b.loc["byte_start"], b.loc["byte_end"]) != (first.byte_start, last.byte_end):
                problems.append(f"{b.id}: byte_start/byte_end не совпадают со строками")
    return problems


# --------------------------------------------------------------------------- строки таблиц как факты

_REQUEST_WORDS = ("запрос", "request", "query", "path-", "path ", "входн")
_RESPONSE_WORDS = ("ответ", "response", "выходн")
_NUMBER = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,]\d+)?(?!\d)")


def _direction(section: list[str]) -> str | None:
    for title in reversed(section):
        t = title.lower() + " "
        if any(w in t for w in _RESPONSE_WORDS):
            return "response"
        if any(w in t for w in _REQUEST_WORDS):
            return "request"
    return None


def _numbers(value: str, offset: int) -> list[dict[str, Any]]:
    out = []
    for m in _NUMBER.finditer(value):
        raw = m.group()
        norm = re.sub(r"[   ]", "", raw).replace(",", ".")
        num: int | float = float(norm) if "." in norm else int(norm)
        out.append({"text": raw, "value": num, "start": offset + m.start(), "end": offset + m.end()})
    return out


def table_records(document: Document) -> list[dict[str, Any]]:
    """Строки таблиц как записи с опорами.

    Каждая ячейка хранит колонку, значение, смещения в ``block.text``, строку и столбцы источника и
    числа, найденные только внутри этой ячейки. Числа из соседних строк и ячеек в неё не попадают.
    ``direction`` (request/response/None) определяется по ближайшему заголовку раздела.
    """
    records = []
    for b in document.blocks:
        if b.kind != "table_row":
            continue
        cells = []
        for c in b.loc["cells"]:
            line, col0 = to_source(b, c["start"])
            _, col1 = to_source(b, c["end"], end=True) if c["end"] > c["start"] else (line, col0)
            value = b.text[c["start"]:c["end"]]
            cells.append({
                "index": c["index"],
                "column": c["column"],
                "value": value,
                "start": c["start"],
                "end": c["end"],
                "line": line,
                "col_start": col0,
                "col_end": col1,
                "numbers": _numbers(value, c["start"]),
            })
        records.append({
            "block_id": b.id,
            "table": b.loc["table"]["index"],
            "header_id": b.loc["table"]["header_id"],
            "row": b.loc["row"],
            "parent": b.loc.get("parent"),
            "line": b.loc["line_start"],
            "section": list(b.section),
            "direction": _direction(b.section),
            "key": cells[0]["value"] if cells else "",
            "cells": cells,
        })
    return records


# --------------------------------------------------------------------------- CLI для отладки


def dumps_document(document: Document) -> str:
    """JSON документа: поля верхнего уровня с отступом, каждый блок — одна строка (удобно в diff)."""
    d = document.to_dict()

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    head = ",\n".join(f"  {dump(k)}: {dump(d[k])}" for k in ("id", "title", "format", "source_name"))
    blocks = ",\n".join(f"    {dump(b)}" for b in d["blocks"])
    blocks = f"[\n{blocks}\n  ]" if d["blocks"] else "[]"
    return f"{{\n{head},\n  \"blocks\": {blocks},\n  \"warnings\": {dump(d['warnings'])}\n}}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.readers.text",
                                 description="Печатает Document (JSON) для .md/.txt")
    ap.add_argument("path", type=Path)
    ap.add_argument("--records", action="store_true", help="печатать записи строк таблиц")
    args = ap.parse_args(argv)
    doc = read_text(args.path)
    if args.records:
        sys.stdout.write(json.dumps(table_records(doc), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(dumps_document(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
