"""Читалка PDF для bcc_review (направление №02): текст, ячейки таблиц и координаты.

    read_pdf(path) -> Document          # dict по контракту v1 (bcc_review.contracts.Document)

Зависимость: PyMuPDF (``pip install -e ".[pdf]"``, то есть ``pymupdf>=1.24``), работает на CPU.
Проверено на PyMuPDF 1.26.5 (без зависимостей) и 2.2. Локальный OCR необязателен: включается сам,
только если PyMuPDF находит tessdata с языком rus или eng (``read_pdf(path, ocr="off")`` отключает).

Контракт координат (общий для №07 привязки и №14 аннотированный PDF)
--------------------------------------------------------------------
* ``block["loc"]["page"]`` — номер страницы с 1; ID блоков ``b0001…`` в порядке чтения.
* ``block["loc"]["fragments"]`` — список ``{start, end, rect, line}``: диапазон
  ``block["text"][start:end]`` (кодовые точки Unicode, правая граница исключена) и
  прямоугольник ``[x0, y0, x1, y1]`` в пунктах в системе НЕповёрнутой страницы
  PyMuPDF: начало в левом верхнем углу CropBox, ось y вниз. Это ровно те числа,
  которые принимают ``page.add_highlight_annot(rect)`` и ``page.get_text(clip=rect)``
  без пересчёта. Для показа повёрнутой страницы: ``Rect(rect) * page.rotation_matrix``.
* Фрагмент — это слово или знак препинания (``«тиынах»`` и ``«,»`` — разные
  фрагменты), поэтому цитата, обрезанная по границе слова или пунктуации,
  переводится в прямоугольники точно. ``line`` — номер визуальной строки внутри блока.
  У наклонного текста есть ``quad`` (4 точки ul, ur, ll, lr), у текста не слева
  направо — ``dir``.
* Для переноса «согла-/сования» в тексте стоит «согласования», а фрагменты
  «согла» (рамка с дефисом) и «сования» лежат на своих строках: прямоугольники покрывают исходные слова.
* Порядок чтения один для текста и координат: всё строится из одних и тех же
  символов, упорядоченных в системе основного направления строк страницы.

Перевод диапазона в прямоугольники — ``locate_span(block, start, end)``.
Неполное чтение помечается кодами ``PARTIAL_READ_CODES`` контракта: прогон ``partial``,
готовность не может быть ``ready``. Исключение ``PdfReadError`` — только для входа,
который вообще не открыть: не PDF, повреждён, пароль.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import pymupdf

from bcc_review.contracts import Block, Document

READER_VERSION = 'p02-pdf-1.0'
STAGE = 'read_pdf'

# Флаги извлечения: пробелы сохраняются, лигатуры раскладываются на буквы (ﬁ → fi),
# текст за пределами страницы отбрасывается, неизвестные глифы дают U+FFFD.
TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP

MARKER = re.compile(r'^(?:[•·▪◦‣∙●○■□➢►✓–—\-*]|\(?\d{1,3}(?:\.\d{1,3})*[.)]|[A-Za-zА-ЯЁа-яё]{1,4}[-‑]\d{1,3}(?:\.\d{1,3})*\.?)\s')
PAGE_NUMBER = re.compile(r'^(?:(?:стр\.?|страница|page|бет)\s*)?\d{1,4}(?:\s*(?:из|of|/)\s*\d{1,4})?$', re.IGNORECASE)
COMMON_EN = frozenset({'the', 'and', 'of', 'to', 'in', 'for', 'is', 'with', 'on', 'by', 'be', 'are', 'this', 'that',
                       'from', 'or', 'as', 'at', 'an', 'it', 'shall', 'will', 'must', 'should'})
# Маркеры списков Word из шрифтов Symbol/Wingdings приходят в частной области Unicode.
PUA_SYMBOLS = {'\uf0b7': '•', '\uf0a7': '▪', '\uf076': '❖', '\uf0d8': '➢', '\uf0fc': '✓', '\uf0a8': '□',
               '\uf06f': '○', '\uf0e0': '→'}
HYPHENS = {'-', '\u00ad', '\u2010', '\u2011'}
KEEP_HYPHEN_TAILS = {'то', 'либо', 'нибудь', 'ка', 'таки', 'де', 'тка'}
MONO_FONTS = ('mono', 'courier', 'consolas', 'menlo', 'monaco')


class PdfReadError(ValueError):
    """PDF нельзя открыть вовсе (не PDF, повреждён, пароль). ``diagnostic`` готов к показу (№18)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.diagnostic = {'ok': False, 'code': code, 'message': message, 'pages': [], 'extraction': {}}


# --------------------------------------------------------------------------- геометрия
@dataclass
class Char:
    c: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    dir: tuple[float, float]
    span: dict | None = None   # для quad наклонного текста
    raw: dict | None = None
    mono: bool = False


@dataclass
class Line:
    chars: list[Char]
    dir: tuple[float, float]
    bbox: tuple[float, float, float, float]
    vbox: tuple[float, float, float, float]   # в системе страницы, которую видит читатель


@dataclass
class Unit:
    """Единица порядка чтения: абзац (визуальные строки) или таблица."""
    kind: str                       # text | table
    page: int
    vbox: tuple[float, float, float, float]
    rows: list[list[Line]] = field(default_factory=list)
    table: dict | None = None
    furniture: bool = False
    role: str = 'paragraph'
    level: int = 0
    ocr: bool = False

    @property
    def size(self) -> float:
        sizes = Counter()
        for row in self.rows:
            for line in row:
                for ch in line.chars:
                    if not ch.c.isspace():
                        sizes[round(ch.size * 2) / 2] += 1
        return sizes.most_common(1)[0][0] if sizes else 0.0

    @property
    def bold(self) -> float:
        chars = [ch for row in self.rows for line in row for ch in line.chars if not ch.c.isspace()]
        return sum(ch.bold for ch in chars) / len(chars) if chars else 0.0

    @property
    def mono(self) -> float:
        chars = [ch for row in self.rows for line in row for ch in line.chars if not ch.c.isspace()]
        return sum(ch.mono for ch in chars) / len(chars) if chars else 0.0

    @property
    def plain(self) -> str:
        return ' '.join(''.join(ch.c for line in row for ch in line.chars) for row in self.rows).strip()


def _r(values: Iterable[float]) -> list[float]:
    return [round(float(v), 2) for v in values]


def _union(boxes: Iterable[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _intersection(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _center_in(ch: Char, box, pad: float = 0.5) -> bool:
    x, y = (ch.bbox[0] + ch.bbox[2]) / 2, (ch.bbox[1] + ch.bbox[3]) / 2
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def _view(box, matrix) -> tuple[float, float, float, float]:
    rect = pymupdf.Rect(box) * matrix
    return (rect.x0, rect.y0, rect.x1, rect.y1)


# --------------------------------------------------------------------------- символы страницы
def _page_lines(page, textpage=None) -> list[list[Line]]:
    """MuPDF-блоки страницы как списки строк из символов (координаты неповёрнутой страницы).

    ``vbox`` пока равен ``bbox``; систему порядка чтения задаёт ``_reading_frame``.
    """
    raw = page.get_text('rawdict', flags=TEXT_FLAGS, textpage=textpage)
    blocks: list[list[Line]] = []
    for block in raw.get('blocks', []):
        if block.get('type') != 0:
            continue
        lines = []
        for line in block.get('lines', []):
            direction = (round(line['dir'][0], 4), round(line['dir'][1], 4))
            chars: list[Char] = []
            for span in line.get('spans', []):
                font = span.get('font', '').lower()
                bold = bool(span.get('flags', 0) & 16) or 'bold' in font
                mono = bool(span.get('flags', 0) & 8) or any(name in font for name in MONO_FONTS)
                for raw_char in span.get('chars', []):
                    c = raw_char['c']
                    if not c:
                        continue
                    if unicodedata.category(c) == 'Cc' and not c.isspace():
                        c = '\ufffd'               # глиф без кодировки: виден как �, а не исчезает
                    c = PUA_SYMBOLS.get(c, c)
                    if c.isspace() or unicodedata.category(c) == 'Zs':
                        c = ' '
                    box = tuple(raw_char['bbox'])
                    if chars and unicodedata.combining(c) and chars[-1].c != ' ':
                        prev = chars[-1]   # «и» + U+0306 → «й»: одна кодовая точка, общая рамка
                        merged = unicodedata.normalize('NFC', prev.c + c)
                        if len(merged) == 1:
                            prev.c, prev.bbox = merged, _union([prev.bbox, box])
                            continue
                    chars.append(Char(c, box, float(span.get('size', 0)), bold, direction, span, raw_char, mono))
            if any(ch.c != ' ' for ch in chars):
                box = tuple(line['bbox'])
                lines.append(Line(chars, direction, box, box))
        if lines:
            blocks.append(lines)
    return blocks


def _reading_frame(page, blocks: list[list[Line]]) -> tuple[pymupdf.Matrix, float, float]:
    """Система порядка чтения: поворот, при котором основное направление строк идёт слева направо.

    Обычная страница — тождественная матрица. Страница с /Rotate и обычным содержимым читается
    так же, как до поворота; «альбомная» страница, где текст написан вдоль длинной стороны
    (направление (0,-1) в неповёрнутой системе), поворачивается так, как её видит читатель.
    Возвращает матрицу и размеры страницы в этой системе.
    """
    votes: Counter = Counter()
    for lines in blocks:
        for line in lines:
            dx, dy = line.dir
            axis = (round(dx), round(dy)) if max(abs(dx), abs(dy)) > 0.95 else None
            if axis:
                votes[axis] += sum(ch.c != ' ' for ch in line.chars)
    if votes:
        dx, dy = votes.most_common(1)[0][0]
        frame = pymupdf.Matrix(dx, -dy, dy, dx, 0, 0)
    else:
        frame = pymupdf.Matrix(page.rotation_matrix)
    box = pymupdf.Rect(0, 0, page.cropbox.width, page.cropbox.height) * frame
    frame = frame * pymupdf.Matrix(1, 0, 0, 1, -box.x0, -box.y0)
    return frame, box.width, box.height


def _visual_rows(lines: list[Line]) -> list[list[Line]]:
    """Строки блока по вертикали (как видит читатель); строки на одной высоте — слева направо."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda ln: ((ln.vbox[1] + ln.vbox[3]) / 2, ln.vbox[0])):
        if rows:
            last = rows[-1]
            top, bottom = min(ln.vbox[1] for ln in last), max(ln.vbox[3] for ln in last)
            overlap = min(bottom, line.vbox[3]) - max(top, line.vbox[1])
            if overlap > 0.5 * min(bottom - top, line.vbox[3] - line.vbox[1]):
                last.append(line)
                last.sort(key=lambda ln: ln.vbox[0])
                continue
        rows.append([line])
    return rows


def _row_text(row: list[Line]) -> str:
    return ' '.join(''.join(ch.c for ch in line.chars).strip() for line in row).strip()


def _row_box(row: list[Line]):
    return _union(line.vbox for line in row)


def _column_segments(lines: list[Line]) -> list[list[Line]]:
    """Строки одного MuPDF-блока, разделённые просветом шире 1,5 em, — разные колонки.

    MuPDF объединяет в блок строки левой и правой колонки на одной базовой линии,
    если производитель PDF выводит текст построчно через обе колонки.
    """
    segments: list[dict] = []
    for line in sorted(lines, key=lambda ln: ln.vbox[0]):
        em = max((ch.size for ch in line.chars), default=10.0) or 10.0
        if segments and line.vbox[0] <= segments[-1]['x1'] + 1.5 * em:
            segments[-1]['lines'].append(line)
            segments[-1]['x1'] = max(segments[-1]['x1'], line.vbox[2])
        else:
            segments.append({'x1': line.vbox[2], 'lines': [line]})
    return [segment['lines'] for segment in segments]


def _split_block(lines: list[Line], page_no: int) -> list[Unit]:
    """MuPDF-блок → абзацы: колонки, смена кегля/жирности, большой интервал, маркер списка."""
    segments = _column_segments(lines)
    if len(segments) > 1:
        return [unit for segment in segments for unit in _split_block(segment, page_no)]
    units: list[Unit] = []
    current: list[list[Line]] = []
    for row in _visual_rows(lines):
        if current:
            prev = current[-1]
            prev_box, box = _row_box(prev), _row_box(row)
            height = max(1.0, prev_box[3] - prev_box[1])
            probe_prev = Unit('text', page_no, prev_box, rows=[prev])
            probe = Unit('text', page_no, box, rows=[row])
            size_jump = abs(probe.size - probe_prev.size) > 0.12 * max(probe_prev.size, 1)
            bold_jump = (probe.bold > 0.9) != (probe_prev.bold > 0.9)
            gap = box[1] - prev_box[3] > 0.8 * height
            marker = bool(MARKER.match(_row_text(row))) and box[0] <= _row_box(current[0])[0] + 3
            if size_jump or bold_jump or gap or marker:
                units.append(Unit('text', page_no, _union(_row_box(r) for r in current), rows=current))
                current = []
        current.append(row)
    if current:
        units.append(Unit('text', page_no, _union(_row_box(r) for r in current), rows=current))
    return units


def _merge_paragraphs(units: list[Unit]) -> list[Unit]:
    """Склейка строк в абзацы поверх группировки MuPDF.

    MuPDF не объединяет строки текста, идущего поперёк страницы, и строки PDF, выведенного
    построчно. Строка продолжает абзац выше, если стоит сразу под ним (в системе чтения),
    выровнена по его левому краю, того же кегля и жирности, не начинается с маркера списка и
    либо предыдущая строка дошла до края колонки, либо фраза явно продолжается (нет точки,
    следующая строка с маленькой буквы). Край колонки берётся только из многострочных абзацев,
    сгруппированных MuPDF: короткие строки «ключ — значение» без такой опоры не склеиваются.
    """
    text = sorted((u for u in units if u.kind == 'text'), key=lambda u: (u.vbox[1], u.vbox[0]))
    wrapped = [u for u in text if len(u.rows) >= 2]
    merged: list[Unit] = []
    for unit in text:
        target = next((p for p in reversed(merged) if _continues(p, unit, wrapped)), None)
        if target is None:
            merged.append(unit)
        else:
            target.rows.extend(unit.rows)
            target.vbox = _union([target.vbox, unit.vbox])
    return [u for u in units if u.kind != 'text'] + merged


def _continues(prev: Unit, unit: Unit, wrapped: list[Unit]) -> bool:
    last, first = _row_box(prev.rows[-1]), _row_box(unit.rows[0])
    height = max(1.0, last[3] - last[1])
    if not -0.3 * height <= first[1] - last[3] <= 0.7 * height:
        return False
    em = max(prev.size, 1.0)
    left = min(_row_box(r)[0] for r in prev.rows)
    if abs(first[0] - left) > 2 * em:
        return False
    if abs(unit.size - prev.size) > 0.12 * em or (unit.bold > 0.9) != (prev.bold > 0.9):
        return False
    before, after = _row_text(prev.rows[-1]), _row_text(unit.rows[0])
    if MARKER.match(after) or not after:
        return False
    if before.endswith(('.', '!', '?', ':', ';')) and not after[:1].islower():
        return False
    edges = [u.vbox[2] for u in wrapped if abs(u.vbox[0] - left) <= 2 * em and u is not prev]
    full = bool(edges) and (last[2] - left) >= 0.8 * max(1.0, max(edges) - left)
    flowing = after[:1].islower() or before.endswith((',', '-', '\u00ad'))
    return full or flowing


# --------------------------------------------------------------------------- сборка текста и фрагментов
def _is_word(c: str) -> bool:
    return c.isalnum() or unicodedata.combining(c) > 0 or c == '_'


def _keep_hyphen(left: str, right: str) -> bool:
    """Перенос «согла-/сования» склеивается; составное слово «веб-/сервис», «push-/уведомление» — нет."""
    left_word = re.findall(r'\w+$', left)
    right_word = re.findall(r'^\w+', right)
    if not left_word or not right_word:
        return True
    lw, rw = left_word[0], right_word[0]
    cyr = lambda s: bool(re.search('[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]', s))
    return (cyr(lw) != cyr(rw) or len(lw) <= 3 or rw.lower() in KEEP_HYPHEN_TAILS
            or any(ch.isdigit() for ch in lw + rw) or rw[:1].isupper())


class _Composer:
    """Собирает block.text и фрагменты из визуальных строк; одна политика для текста и координат."""

    def __init__(self):
        self.text: list[str] = []
        self.length = 0
        self.fragments: list[dict] = []
        self._token: list[Char] = []
        self._token_start = 0
        self._line = 0
        self.hyphen_dropped: Char | None = None

    def _emit(self, s: str):
        self.text.append(s)
        self.length += len(s)

    def _close(self):
        if self._token:
            self.fragments.append(_fragment(self._token, self._token_start, self.length, self._line))
            self._token = []

    def _push(self, ch: Char):
        if self._token:
            prev = self._token[-1]
            if _is_word(prev.c) != _is_word(ch.c) or not (_is_word(ch.c) or ch.c == prev.c):
                self._close()
        if not self._token:
            self._token_start = self.length
        self._token.append(ch)
        self._emit(ch.c)

    def space(self):
        self._close()
        if self.length and not ''.join(self.text[-1:]).endswith(' '):
            self._emit(' ')

    def add_row(self, row: list[Line], line_index: int, next_row_text: str | None):
        self._line = line_index
        chars = [ch for line in row for ch in (line.chars + [Char(' ', line.bbox, 0, False, line.dir)])]
        while chars and chars[-1].c == ' ':
            chars.pop()
        while chars and chars[0].c == ' ':
            chars.pop(0)
        # Дефис в конце строки. Мягкий перенос и перенос внутри слова («согла-/сования») убираются;
        # составное слово или ключ («push-/уведомление», «--/data») склеивается с дефисом, без пробела.
        joined = False
        if next_row_text and len(chars) >= 2 and chars[-1].c in HYPHENS and chars[-2].c != ' ':
            left = ''.join(ch.c for ch in chars[:-1])
            if chars[-1].c == '\u00ad' or (chars[-2].c.isalpha() and next_row_text[:1].islower()
                                           and not _keep_hyphen(left, next_row_text)):
                self.hyphen_dropped = chars.pop()
            joined = True
        prev: Char | None = None
        for ch in chars:
            if ch.c == '\u00ad':
                continue                    # мягкий перенос внутри строки невидим
            if ch.c == ' ':
                self.space()
                prev = None
                continue
            if prev is not None and _gap(prev, ch) > 0.25 * max(ch.size, prev.size, 1):
                self.space()               # слова без символа пробела в потоке PDF
            self._push(ch)
            prev = ch
        if joined:
            self._close()
            if self.hyphen_dropped is not None and self.fragments:
                # Слово продолжается на следующей строке; рамка покрывает и убранный дефис («согла-»).
                last = self.fragments[-1]
                last['rect'] = _r(_union([tuple(last['rect']), self.hyphen_dropped.bbox]))
                last['hyphen'] = True
            self.hyphen_dropped = None
        else:
            self.space()

    def finish(self) -> tuple[str, list[dict]]:
        self._close()
        text = ''.join(self.text)
        stripped = text.rstrip(' ')
        return stripped, self.fragments


def _gap(a: Char, b: Char) -> float:
    dx, dy = b.dir
    if abs(dx) >= abs(dy):
        return (b.bbox[0] - a.bbox[2]) if dx > 0 else (a.bbox[0] - b.bbox[2])
    return (b.bbox[1] - a.bbox[3]) if dy > 0 else (a.bbox[1] - b.bbox[3])


def _fragment(chars: list[Char], start: int, end: int, line: int) -> dict:
    frag = {'start': start, 'end': end, 'rect': _r(_union(ch.bbox for ch in chars)), 'line': line}
    dx, dy = chars[0].dir
    if (dx, dy) != (1.0, 0.0):
        frag['dir'] = [dx, dy]
        if min(abs(dx), abs(dy)) > 0.02:      # наклонный текст: прямоугольник шире слова, нужен quad
            try:
                first = pymupdf.recover_char_quad(chars[0].dir, chars[0].span, chars[0].raw)
                last = pymupdf.recover_char_quad(chars[-1].dir, chars[-1].span, chars[-1].raw)
                frag['quad'] = [_r(first.ul), _r(last.ur), _r(first.ll), _r(last.lr)]
            except Exception:   # noqa: BLE001, S110 — без quad остаётся охватывающий прямоугольник
                pass
    return frag


def _compose_rows(rows: list[list[Line]]) -> tuple[str, list[dict]]:
    composer = _Composer()
    for index, row in enumerate(rows):
        nxt = _row_text(rows[index + 1]) if index + 1 < len(rows) else None
        composer.add_row(row, index, nxt)
    return composer.finish()


# --------------------------------------------------------------------------- таблицы
def _find_tables(page, page_no: int, lines_blocks: list[list[Line]], warnings: list[dict],
                 upright: bool = True) -> list[dict]:
    """Таблицы с линейками (PyMuPDF find_tables). Связь ячеек проверяется по символам.

    find_tables на странице с /Rotate отдаёт рамки в другой системе (на 90° — со сдвигом,
    на 270° таблица не находится), поэтому поиск идёт на временно неповёрнутой странице:
    там координаты ячеек и символов совпадают.
    """
    rotation = page.rotation
    try:
        if rotation:
            page.set_rotation(0)
        found = page.find_tables().tables
    except Exception as error:  # noqa: BLE001
        warnings.append(_warn('table_detection_failed', 'warning', page_no,
                              f'Страница {page_no}: таблицы не распознаны ({type(error).__name__}); текст сохранён блоками.'))
        return []
    finally:
        if rotation:
            page.set_rotation(rotation)
    chars = [ch for lines in lines_blocks for line in lines for ch in line.chars if ch.c != ' ']
    tables = []
    for table in found:
        rows = [list(row.cells) for row in table.rows]
        cells = [(r, c, box) for r, row in enumerate(rows) for c, box in enumerate(row) if box]
        if table.col_count < 2 or len(cells) < 2:
            continue                                # рамка вокруг абзаца, а не таблица
        bbox = tuple(table.bbox)
        inside = [ch for ch in chars if _center_in(ch, bbox)]
        if inside and bbox[3] - bbox[1] < 0.8 * max(ch.bbox[3] - ch.bbox[1] for ch in inside):
            continue                                # «таблица» ниже собственного текста: подчёркивание, не сетка
        assigned: dict[tuple[int, int], list[Char]] = {}
        problems = 0
        for ch in inside:
            homes = [(r, c, box) for r, c, box in cells if _center_in(ch, box, pad=0.1)]
            if len(homes) != 1:
                problems += 1
                continue
            r, c, box = homes[0]
            if ch.bbox[0] < box[0] - 1.5 or ch.bbox[2] > box[2] + 1.5:
                problems += 1                       # текст пересекает линию ячейки
            assigned.setdefault((r, c), []).append(ch)
        bounds = sorted({round(box[0], 1) for _, _, box in cells} | {round(box[2], 1) for _, _, box in cells})
        record = {'bbox': bbox, 'rows': rows, 'assigned': assigned, 'chars': {id(ch) for ch in inside},
                  'col_count': table.col_count, 'bounds': bounds,
                  'header_external': bool(getattr(table.header, 'external', False))}
        if not upright and inside:
            warnings.append(_warn('table_rotated_text', 'warning', page_no,
                                  f'Страница {page_no}: таблица {_r(bbox)} с текстом поперёк страницы; соответствие строк '
                                  'и колонок не восстановлено, текст сохранён исходными блоками.', bbox=_r(bbox)))
            continue
        if problems:
            warnings.append(_warn('table_unreliable', 'warning', page_no,
                                  f'Страница {page_no}: таблица {_r(bbox)} сохранена исходными блоками — '
                                  f'{problems} символ(ов) не удалось однозначно отнести к ячейке.', bbox=_r(bbox)))
            continue
        tables.append(record)
    return tables


def _table_unit(record: dict, page_no: int, matrix, line_of: dict[int, Line]) -> Unit:
    cells = []
    for r, row in enumerate(record['rows']):
        for c, box in enumerate(row):
            if not box:
                continue
            chars = record['assigned'].get((r, c), [])
            # строки ячейки — по исходным строкам MuPDF (символ знает свою строку)
            by_line: dict[int, list[Char]] = {}
            for ch in chars:
                by_line.setdefault(id(line_of[id(ch)]), []).append(ch)
            lines = []
            for group in by_line.values():
                src = line_of[id(group[0])]
                box_ = _union(ch.bbox for ch in group)
                kept = [ch for ch in src.chars if id(ch) in {id(g) for g in group} or
                        (ch.c == ' ' and box_[0] <= ch.bbox[0] <= box_[2])]
                lines.append(Line(kept, src.dir, box_, _view(box_, matrix)))
            span = sum(1 for x0, x1 in zip(record['bounds'], record['bounds'][1:])
                       if x0 >= box[0] - 1 and x1 <= box[2] + 1)
            cells.append({'row': r, 'col': c, 'colspan': max(1, span), 'box': box, 'rows': _visual_rows(lines)})
    record['cells'] = cells
    return Unit('table', page_no, _view(record['bbox'], matrix), table=record)


# --------------------------------------------------------------------------- порядок чтения
def _order(units: list[Unit], body: float, warnings: list[dict], page_no: int) -> list[Unit]:
    """Рекурсивный XY-разрез в системе чтения: колонки слева направо, внутри — сверху вниз.

    Горизонтальный просвет режет область, только если он не проходит внутри колонок
    (иначе при ровных абзацах в обеих колонках чтение пошло бы строками через обе).
    """
    if len(units) <= 1:
        return list(units)
    gutter = max(8.0, 0.9 * body)
    column = _column_cut(units, gutter)
    for cut in _gaps([(u.vbox[1], u.vbox[3]) for u in units], 0.1, widest=True, all_sorted=True):
        top = [u for u in units if (u.vbox[1] + u.vbox[3]) / 2 < cut]
        bottom = [u for u in units if (u.vbox[1] + u.vbox[3]) / 2 >= cut]
        if top and bottom and (column is None or _section_break(top, bottom)
                               or not _inside_columns(top, bottom, gutter)):
            return _order(top, body, warnings, page_no) + _order(bottom, body, warnings, page_no)
    if column is not None:
        cut, left, right = column
        if _grid_like(left, right):
            box = _union(u.vbox for u in units)
            warnings.append(_warn('layout_grid_unreliable', 'warning', page_no,
                                  f'Страница {page_no}: текст выровнен как таблица без линеек; '
                                  'связь строк и колонок ненадёжна, блоки сохранены построчно.', bbox=_r(box)))
            return sorted(units, key=lambda u: (round(u.vbox[1], 0), u.vbox[0]))
        return _order(left, body, warnings, page_no) + _order(right, body, warnings, page_no)
    return sorted(units, key=lambda u: (u.vbox[1], u.vbox[0]))


def _column_cut(units: list[Unit], gutter: float):
    """Вертикальный просвет через всю область с текстом по обе стороны: (x, левые, правые) или None."""
    x0, y0 = min(u.vbox[0] for u in units), min(u.vbox[1] for u in units)
    x1, y1 = max(u.vbox[2] for u in units), max(u.vbox[3] for u in units)
    width, height = max(1.0, x1 - x0), max(1.0, y1 - y0)
    for cut in _gaps([(u.vbox[0], u.vbox[2]) for u in units], gutter):
        left = [u for u in units if u.vbox[2] <= cut]
        right = [u for u in units if u.vbox[0] >= cut]
        if not left or not right:
            continue
        lw = max(u.vbox[2] for u in left) - min(u.vbox[0] for u in left)
        rw = max(u.vbox[2] for u in right) - min(u.vbox[0] for u in right)
        lh = sum(u.vbox[3] - u.vbox[1] for u in left)
        rh = sum(u.vbox[3] - u.vbox[1] for u in right)
        if min(lw, rw) >= 0.15 * width and min(lh, rh) >= 0.3 * height:
            return cut, left, right
    return None


def _section_break(top: list[Unit], bottom: list[Unit]) -> bool:
    """Просвет перед заголовком или под шапкой из одних заголовков отделяет раздел, а не колонку.

    В настоящих двух колонках рядом с заголовком колонки стоит текст соседней колонки,
    поэтому горизонтального просвета на всю ширину там нет и этот разрез не возникает.
    """
    first = min(bottom, key=lambda u: (u.vbox[1], u.vbox[0]))
    return first.role == 'heading' or all(u.role == 'heading' for u in top)


def _inside_columns(top: list[Unit], bottom: list[Unit], gutter: float) -> bool:
    """Просвет между top и bottom проходит внутри колонок: по одну сторону колонки есть,
    а по другую текст не пересекает их межколонный просвет."""
    for upper, lower in ((top, bottom), (bottom, top)):
        column = _column_cut(upper, gutter) if len(upper) > 1 else None
        if column and not any(u.vbox[0] < column[0] < u.vbox[2] for u in lower):
            return True
    return False


def _gaps(intervals: list[tuple[float, float]], minimum: float, widest: bool = False,
          all_sorted: bool = False) -> list[float]:
    """Середины просветов между проекциями: слева направо; widest — только самый широкий;
    all_sorted — все, от широкого к узкому."""
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps = [(merged[i + 1][0] - merged[i][1], (merged[i][1] + merged[i + 1][0]) / 2)
            for i in range(len(merged) - 1) if merged[i + 1][0] - merged[i][1] >= minimum]
    if widest:
        gaps = sorted(gaps, key=lambda g: -g[0])
        if not all_sorted:
            gaps = gaps[:1]
    return [mid for _, mid in gaps]


def _grid_like(left: list[Unit], right: list[Unit]) -> bool:
    """Ключ-значение без линеек: однострочные единицы слева и справа на одних высотах."""
    small = left if len(left) <= len(right) else right
    other = right if small is left else left
    if len(small) < 2:
        return False
    single = statistics.median(len(u.rows) for u in left + right) <= 1.5
    aligned = sum(any(abs(u.vbox[1] - v.vbox[1]) < 0.5 * max(1.0, u.vbox[3] - u.vbox[1]) for v in other) for u in small)
    return single and aligned >= 0.6 * len(small)


# --------------------------------------------------------------------------- страницы: полнота и OCR
def _garbled(text: str) -> bool:
    """Текстовый слой без карты Unicode: U+FFFD/частная область или «латинская каша» вместо кириллицы."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return False
    bad = sum(c == '�' or '' <= c <= '' for c in letters)
    if bad / len(letters) > 0.1:
        return True
    alpha = [c for c in letters if c.isalpha()]
    if len(alpha) < 60:
        return False
    latin = sum('a' <= c.lower() <= 'z' for c in alpha) / len(alpha)
    words = re.findall(r'[A-Za-z]{2,}', text)
    return latin >= 0.7 and bool(words) and sum(w.lower() in COMMON_EN for w in words) / len(words) < 0.03


def ocr_languages() -> str | None:
    """Языки локального OCR, если PyMuPDF реально видит tessdata; иначе None."""
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception:  # noqa: BLE001
        return None
    if not tessdata or not Path(tessdata).is_dir():
        return None
    langs = [lang for lang in ('rus', 'kaz', 'eng') if (Path(tessdata) / f'{lang}.traineddata').exists()]
    return '+'.join(langs) if langs and ('rus' in langs or 'eng' in langs) else None


def _warn(code: str, severity: str, page: int | None, message: str, **extra) -> dict:
    """Warning контракта v1 ({code, message, stage}) плюс severity и page для показа и подсветки."""
    warning = {'code': code, 'message': message, 'stage': STAGE, 'severity': severity, 'page': page}
    warning.update(extra)
    return warning


# --------------------------------------------------------------------------- главный вход
def read_pdf(path: Path | str, *, ocr: str = 'auto', password: str | None = None) -> Document:
    """PDF → Document (dict контракта v1) с ``extraction`` — сводкой полноты.

    Страницы без текстового слоя не роняют чтение: Document приходит с предупреждениями
    ``ocr_required`` / ``unreadable_page`` / ``decode_error`` / ``partial_read`` и с полнотой < 1
    (при полностью нечитаемом PDF — без блоков и с полнотой 0). PdfReadError — только если файл
    не открыть: не PDF, повреждён или защищён паролем.
    """
    path = Path(path)
    data = path.read_bytes()
    if b'%PDF-' not in data[:1024]:
        raise PdfReadError('not_pdf', f'Файл {path.name} не является PDF.')
    try:
        doc = pymupdf.open(stream=data, filetype='pdf')
    except Exception as error:  # noqa: BLE001
        raise PdfReadError('damaged', f'PDF {path.name} повреждён и не открывается ({type(error).__name__}).') from None
    if doc.needs_pass and not doc.authenticate(password or ''):
        raise PdfReadError('encrypted', f'PDF {path.name} защищён паролем: текст недоступен. '
                                        'Передайте документ без пароля или укажите пароль.')
    if doc.page_count == 0:
        raise PdfReadError('damaged', f'В PDF {path.name} нет страниц.')
    warnings: list[dict] = []
    if doc.is_encrypted or doc.metadata.get('encryption'):
        warnings.append(_warn('pdf_encrypted_owner', 'info', None,
                              'PDF зашифрован ограничениями владельца; текст прочитан без пароля.'))
    if doc.is_repaired:
        warnings.append(_warn('pdf_repaired', 'warning', None,
                              'Структура PDF была повреждена и восстановлена при открытии; сверьте текст с оригиналом.'))

    use_ocr = ocr_languages() if ocr != 'off' else None
    pages = [_scan_page(doc[i], i + 1, warnings) for i in range(doc.page_count)]
    _mark_furniture(pages)
    for page in pages:
        _classify(page, use_ocr, ocr, warnings)

    body = _body_size(pages)
    toc = {(page, _norm(title)): level for level, title, page in doc.get_toc(simple=True)}
    heading_sizes = _heading_levels(pages, body)
    for page in pages:
        for unit in page['units']:
            _role(unit, body, heading_sizes, toc)
        content = [u for u in page['units'] if not u.furniture]
        page['ordered'] = _order(content, body, warnings, page['no'])

    _link_tables(pages, warnings)
    blocks = _emit(pages)
    _link_continuations(blocks)
    extraction = _extraction(pages, blocks)
    if extraction['completeness'] < 1.0:
        lost = extraction['pages_unread']
        if not extraction['content_pages']:
            message = 'В PDF нет текста: все страницы пустые. Проверять требования не по чему.'
        elif not any(b['kind'] != 'other' for b in blocks):
            message = (f'В PDF нет читаемого текста (страницы {_pages_text(lost)}); полнота 0%. '
                       'Проверка требований по такому файлу невозможна: нужен PDF с текстовым слоем, DOCX или Markdown'
                       + (', либо локальный OCR (tessdata rus/eng).' if not use_ocr else '.'))
        else:
            message = (f'Текст извлечён не полностью: оценка полноты {extraction["completeness"]:.0%}; '
                       f'не прочитаны страницы {_pages_text(lost)}. Выводы о готовности по ним невозможны.')
        warnings.append(_warn('partial_read', 'error', None, message, pages=lost,
                              completeness=extraction['completeness']))
    title = (doc.metadata.get('title') or '').strip()
    if not title or title.lower().startswith(('microsoft word', 'untitled')):
        first = next((b for b in blocks if b['kind'] == 'heading'), None)
        title = first['text'] if first else path.stem
    return {'id': hashlib.sha256(data).hexdigest(), 'title': title, 'format': 'pdf', 'source_name': path.name,
            'blocks': blocks, 'warnings': warnings, 'extraction': extraction}


def _pages_text(pages: list[int]) -> str:
    return ', '.join(map(str, pages)) if pages else '—'


def _norm(text: str) -> str:
    return ' '.join(text.lower().split())


def _scan_page(page, page_no: int, warnings: list[dict], textpage=None) -> dict:
    blocks = _page_lines(page, textpage)
    matrix, width, height = _reading_frame(page, blocks)
    upright = abs(matrix.a - 1) < 1e-6 and abs(matrix.b) < 1e-6
    for lines in blocks:
        for line in lines:
            line.vbox = _view(line.bbox, matrix)
    line_of = {id(ch): line for lines in blocks for line in lines for ch in line.chars}
    tables = _find_tables(page, page_no, blocks, warnings, upright) if textpage is None else []
    taken = set().union(*(t['chars'] for t in tables)) if tables else set()
    units: list[Unit] = [_table_unit(t, page_no, matrix, line_of) for t in tables]
    for lines in blocks:
        rest = []
        for line in lines:
            chars = [ch for ch in line.chars if id(ch) not in taken]
            if any(ch.c != ' ' for ch in chars):
                rest.append(line if len(chars) == len(line.chars) else
                            Line(chars, line.dir, line.bbox, line.vbox))
        if rest:
            units.extend(_split_block(rest, page_no))
    units = _merge_paragraphs(units)
    return {'no': page_no, 'page': page, 'units': units, 'rotation': page.rotation,
            'height': height, 'width': width, 'matrix': matrix, 'ocr': textpage is not None}


def _mark_furniture(pages: list[dict]) -> None:
    """Колонтитулы и номера страниц: повторяются в верхних/нижних 9% страницы."""
    seen: Counter = Counter()
    keyed = []
    for page in pages:
        for unit in page['units']:
            if unit.kind != 'text' or len(unit.rows) > 2:
                continue
            band = unit.vbox[3] <= 0.09 * page['height'] or unit.vbox[1] >= 0.91 * page['height']
            if band:
                key = (re.sub(r'\d+', '#', _norm(unit.plain)), round(unit.vbox[1] / 6))
                keyed.append((unit, key))
                seen[key] += 1
    threshold = max(2, (len(pages) + 1) // 2)
    for unit, key in keyed:
        if (len(pages) > 1 and seen[key] >= threshold) or PAGE_NUMBER.match(unit.plain.strip()):
            unit.furniture = True


def _classify(page: dict, ocr_langs: str | None, ocr_mode: str, warnings: list[dict]) -> None:
    """Статус страницы и оценка её полноты (coverage 0…1)."""
    no, pg = page['no'], page['page']
    content = [u for u in page['units'] if not u.furniture]
    text = ' '.join(u.plain if u.kind == 'text' else ' '.join(
        ''.join(ch.c for row in cell['rows'] for line in row for ch in line.chars) for cell in u.table['cells'])
        for u in content)
    letters = sum(1 for c in text if not c.isspace())
    page_area = max(1.0, pg.rect.width * pg.rect.height)
    images = [tuple(info['bbox']) for info in pg.get_image_info() if _area(info['bbox']) >= 0.02 * page_area]
    image_area = sum(_area(b) for b in images)
    text_boxes = [u.vbox for u in content]
    unmapped = sum(c == '\ufffd' or '\ue000' <= c <= '\uf8ff' for c in text)
    garbled = letters > 0 and _garbled(text)
    if unmapped and not garbled:
        warnings.append(_warn('decode_error', 'warning', no,
                              f'Страница {no}: {unmapped} символ(ов) без кодировки Unicode (показаны как �); '
                              'цитаты с ними, например со знаком ₸, не совпадут с оригиналом.', count=unmapped))
    status, coverage = 'text', 1.0
    if letters == 0 or garbled:
        drawings = sum(len(d.get('items', ())) for d in pg.get_drawings()) if not images else 0
        if garbled:
            status = 'garbled'
        elif images:
            status = 'scan'
        elif drawings > 30:
            status = 'vector'
        else:
            status = 'blank'
        coverage = None if status == 'blank' else 0.0
    else:
        # Области изображений без текста поверх них — непрочитанная часть страницы.
        bare_boxes = []
        for box in images:
            view = _view(box, page['matrix'])
            if sum(_intersection(view, t) for t in text_boxes) < 0.1 * _area(view):
                bare_boxes.append(view)
        bare = sum(_area(b) for b in bare_boxes)
        if image_area >= 0.8 * page_area and letters >= 100:
            status = 'text_over_image'
            warnings.append(_warn('page_text_over_image', 'info', no,
                                  f'Страница {no}: текстовый слой лежит поверх скана; точность зависит от распознавания '
                                  'в исходном PDF.'))
        elif bare >= 0.15 * page_area:
            text_area = sum(_area(t) for t in text_boxes)
            coverage = round(max(0.05, min(0.95, text_area / (text_area + bare))), 2)
            status = 'partial'
            found = _ocr_units(pg, no, ocr_langs, bare_boxes, full=False) if ocr_langs else []
            if found:
                page['units'].extend(found)
                status, coverage = 'partial_ocr', 1.0
                warnings.append(_warn('page_ocr', 'warning', no,
                                      f'Страница {no}: {bare / page_area:.0%} площади — изображение без текста, '
                                      f'его текст распознан локальным OCR ({ocr_langs}); сверьте цитаты с оригиналом.'))
            else:
                warnings.append(_warn('partial_read', 'error', no,
                                      f'Страница {no}: {bare / page_area:.0%} площади — изображение без текстового слоя; '
                                      'его содержимое не проверялось.', coverage=coverage))
    if status in ('scan', 'garbled', 'vector') and ocr_langs:
        found = _ocr_units(pg, no, ocr_langs, None, full=True)
        if found:
            page['units'] = [u for u in page['units'] if u.furniture] + found
            warnings.append(_warn('page_ocr', 'warning', no,
                                  f'Страница {no}: {_STATUS[status]}; применён локальный OCR ({ocr_langs}), '
                                  'сверьте цитаты с оригиналом.'))
            status, coverage = 'ocr', 1.0
    if status in ('scan', 'garbled', 'vector'):
        # «Каша» не становится текстом блоков; у скана остаются только текстовые колонтитулы.
        page['units'] = [] if status == 'garbled' else [u for u in page['units'] if u.furniture]
        hint = ('' if ocr_langs else ' OCR отключён параметром.' if ocr_mode == 'off'
                else ' Локальный OCR недоступен (нет tessdata rus/eng).')
        code = {'scan': 'ocr_required', 'vector': 'unreadable_page', 'garbled': 'decode_error'}[status]
        warnings.append(_warn(code, 'error', no,
                              f'Страница {no}: {_STATUS[status]}; текст страницы не извлечён и не проверялся.{hint}',
                              page_status=status))
    if status == 'blank':
        warnings.append(_warn('page_blank', 'info', no, f'Страница {no}: пустая страница.'))
    page['status'], page['coverage'] = status, coverage


def _ocr_units(pg, no: int, langs: str, regions, full: bool) -> list[Unit]:
    """Локальный OCR (Tesseract внутри MuPDF). full=False — только области изображений."""
    try:
        textpage = pg.get_textpage_ocr(language=langs, dpi=300, full=full)
        units = _scan_page(pg, no, [], textpage=textpage)['units']
    except Exception:  # noqa: BLE001 — OCR необязателен: без него остаются предупреждения
        return []
    if regions is not None:
        units = [u for u in units if any(_center_in_box(u.vbox, r) for r in regions)]
    units = [u for u in units if u.plain.strip()]
    for unit in units:
        unit.ocr = True
    return units


def _center_in_box(box, region) -> bool:
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= x <= region[2] and region[1] <= y <= region[3]


_STATUS = {'scan': 'нет текстового слоя, страница — изображение (скан)',
           'garbled': 'текстовый слой нечитаем (шрифт без кодировки Unicode)',
           'vector': 'нет текстового слоя, текст нарисован кривыми'}


def _body_size(pages: list[dict]) -> float:
    sizes: Counter = Counter()
    for page in pages:
        for unit in page['units']:
            if unit.kind == 'text' and not unit.furniture:
                sizes[unit.size] += len(unit.plain)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _heading_levels(pages: list[dict], body: float) -> dict[float, int]:
    sizes = sorted({u.size for p in pages for u in p['units']
                    if u.kind == 'text' and not u.furniture and u.size >= body * 1.12 and len(u.rows) <= 3}, reverse=True)
    return {size: i + 1 for i, size in enumerate(sizes)}


def _role(unit: Unit, body: float, heading_sizes: dict[float, int], toc: dict) -> None:
    if unit.kind != 'text':
        return
    if unit.furniture:
        unit.role = 'furniture'
        return
    text = unit.plain
    toc_level = toc.get((unit.page, _norm(text)))
    short = len(unit.rows) <= 3 and len(text) <= 160
    if toc_level:
        unit.role, unit.level = 'heading', toc_level
    elif short and unit.size in heading_sizes:
        unit.role, unit.level = 'heading', heading_sizes[unit.size]
    elif (short and len(unit.rows) <= 2 and unit.bold > 0.9 and unit.size >= body * 0.95
          and all(len(row) == 1 for row in unit.rows) and not text.rstrip().endswith(('.', ':', ';', ','))):
        unit.role, unit.level = 'heading', len(heading_sizes) + 1
    elif unit.mono > 0.8:
        unit.role = 'code'
    elif MARKER.match(text):
        unit.role = 'list_item'


def _link_tables(pages: list[dict], warnings: list[dict]) -> None:
    """Таблицы: шапка (в том числе из нескольких строк) и продолжение на следующей странице.

    Продолжение — таблица первой на странице, если предыдущая страница кончается таблицей
    с тем же числом колонок и теми же внутренними границами (±3 pt). Повторённая шапка
    узнаётся по тексту; без повтора шапка берётся с предыдущей части (header_source = "page N").
    """
    counter = 0
    previous: dict | None = None        # таблица, которой кончается предыдущая страница
    for page in pages:
        ordered = page['ordered']
        for unit in (u for u in ordered if u.kind == 'table'):
            record = unit.table
            cont = None
            if ordered[0] is unit and previous is not None:
                if record['col_count'] == previous['col_count'] and _same_columns(record, previous):
                    cont = previous
                else:
                    warnings.append(_warn('table_continuation_unmatched', 'warning', page['no'],
                                          f'Страница {page["no"]}: таблица в начале страницы может продолжать таблицу '
                                          f'со страницы {previous["page"]}, но колонки не совпали; шапка не восстановлена.',
                                          pages=[previous['page'], page['no']]))
            if cont:
                record['id'], record['part'] = cont['id'], cont['part'] + 1
                record['header'], record['header_first'] = cont['header'], cont['header_first']
                record['row_base'] = cont['row_base'] + cont['data_rows']
                if cont['header_first'] and [_norm(x) for x in _row_texts(record, 0)] == [_norm(x) for x in cont['header_first']]:
                    depth = max(1, len(cont['header_rows'] or [0]))
                    record['header_rows'], record['header_source'] = list(range(depth)), 'repeated'
                else:
                    record['header_rows'], record['header_source'] = [], f'page {cont["page"]}'
            else:
                counter += 1
                record['id'], record['part'], record['row_base'] = f'T{counter}', 1, 0
                if record['header_external']:
                    record['header_rows'], record['header'], record['header_first'] = [], None, None
                    record['header_source'] = None
                else:
                    record['header_rows'] = _header_rows(record)
                    record['header_first'] = _row_texts(record, 0)
                    record['header'] = _header_names(record)
                    record['header_source'] = 'same_page'
                    if record['header'] is None:
                        warnings.append(_warn('table_header_unmapped', 'warning', page['no'],
                                              f'Страница {page["no"]}: шапку таблицы {record["id"]} не удалось сопоставить '
                                              'с колонками; строки сохранены без имён колонок.'))
            record['data_rows'] = len(record['rows']) - len(record['header_rows'])
            record['page'] = page['no']
        last = ordered[-1] if ordered else None
        previous = last.table if last is not None and last.kind == 'table' else None


def _row_band(record: dict, r: int) -> tuple[float, float]:
    boxes = [box for box in record['rows'][r] if box]
    return min(b[1] for b in boxes), min(b[3] for b in boxes)


def _header_rows(record: dict) -> list[int]:
    """Строка 0 — шапка; следующие жирные строки входят в шапку, пока над ними есть объединённые ячейки."""
    rows, depth = record['rows'], 1
    while depth < min(3, len(rows) - 1):
        bottom = _row_band(record, depth - 1)[1]
        spans_down = any(box and box[3] > bottom + 1 for r in range(depth) for box in rows[r])
        wide = any(cell['colspan'] > 1 for cell in record['cells'] if cell['row'] == depth - 1)
        chars = [ch for cell in record['cells'] if cell['row'] == depth
                 for row in cell['rows'] for line in row for ch in line.chars if ch.c != ' ']
        bold = bool(chars) and sum(ch.bold for ch in chars) / len(chars) > 0.9
        if (spans_down or wide) and bold:
            depth += 1
        else:
            break
    return list(range(depth))


def _header_names(record: dict) -> list[str] | None:
    """Имя каждой колонки из строк шапки; объединённые ячейки дают «Сумма, ₸ / до»."""
    bounds = record['bounds']
    if len(bounds) - 1 != record['col_count']:
        return None
    texts = {(cell['row'], cell['col']): _compose_rows(cell['rows'])[0] for cell in record['cells']}
    names = []
    for j in range(record['col_count']):
        xc = (bounds[j] + bounds[j + 1]) / 2
        parts: list[str] = []
        for r in record['header_rows']:
            yc = sum(_row_band(record, r)) / 2
            for rr in range(r + 1):
                for c, box in enumerate(record['rows'][rr]):
                    if box and box[0] <= xc <= box[2] and box[1] <= yc <= box[3]:
                        text = texts.get((rr, c), '')
                        if text and (not parts or parts[-1] != text):
                            parts.append(text)
        names.append(' / '.join(parts))
    return names


def _same_columns(a: dict, b: dict) -> bool:
    inner_a, inner_b = a['bounds'][1:-1], b['bounds'][1:-1]
    return len(inner_a) == len(inner_b) and all(abs(x - y) <= 3 for x, y in zip(inner_a, inner_b))


def _row_texts(record: dict, row: int) -> list[str]:
    return [_compose_rows(cell['rows'])[0] for cell in sorted(record['cells'], key=lambda c: c['col'])
            if cell['row'] == row]


def _emit(pages: list[dict]) -> list[Block]:
    """Блоки в порядке чтения: колонтитулы страницы, содержимое, нижние колонтитулы; ID b0001…"""
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []

    def add(kind: str, section: list[str], text: str, loc: dict) -> None:
        blocks.append({'id': f'b{len(blocks) + 1:04d}', 'kind': kind, 'section': section, 'text': text, 'loc': loc})

    for page in pages:
        furniture = [u for u in page['units'] if u.furniture]
        head = [u for u in furniture if u.vbox[1] < page['height'] / 2]
        foot = [u for u in furniture if u.vbox[1] >= page['height'] / 2]
        sequence = sorted(head, key=lambda u: (u.vbox[1], u.vbox[0])) + page['ordered'] + \
            sorted(foot, key=lambda u: (u.vbox[1], u.vbox[0]))
        for unit in sequence:
            if unit.kind == 'table':
                for kind, text, loc in _table_rows(unit, page):
                    add(kind, [t for _, t in stack], text, loc)
                continue
            text, fragments = _compose_rows(unit.rows)
            if not text:
                continue
            loc = _loc(page, fragments)
            if unit.role == 'heading':
                while stack and stack[-1][0] >= unit.level:
                    stack.pop()
                stack.append((unit.level, text))
                loc['level'] = unit.level
            if unit.ocr:
                loc['ocr'] = True
            if unit.furniture:
                loc['furniture'] = True       # колонтитул или номер страницы: kind "other"
                add('other', [], text, loc)
            else:
                add(unit.role, [t for _, t in stack], text, loc)
    return blocks


def _link_continuations(blocks: list[Block]) -> None:
    """Абзац, разорванный колонкой или страницей: без точки в конце, следующий начинается с маленькой буквы.

    Блоки не склеиваются (у каждого своя страница и координаты), но получают ссылки
    loc.continues / loc.continued_from — №07 может соединить цитату из двух блоков.
    """
    order = {b['id']: i for i, b in enumerate(blocks)}
    text = [b for b in blocks if b['kind'] in ('paragraph', 'list_item')]
    for a, b in pairwise(text):
        between = blocks[order[a['id']] + 1:order[b['id']]]
        if any(not x['loc'].get('furniture') for x in between):
            continue
        if a['text'] and not a['text'].rstrip().endswith(('.', '!', '?', ':', ';')) and b['text'][:1].islower():
            a['loc']['continues'] = b['id']
            b['loc']['continued_from'] = a['id']


def _loc(page: dict, fragments: list[dict]) -> dict:
    loc: dict[str, Any] = {'page': page['no']}
    if fragments:
        loc['bbox'] = _r(_union(tuple(f['rect']) for f in fragments))
    loc['fragments'] = fragments
    if page['rotation']:
        loc['rotation'] = page['rotation']
    return loc


def _table_rows(unit: Unit, page: dict) -> list[tuple[str, str, dict]]:
    """Строки таблицы: текст «ячейка | ячейка», фрагменты слов и loc.table с ячейками и шапкой."""
    record = unit.table
    out = []
    for r in range(len(record['rows'])):
        cells = [cell for cell in record['cells'] if cell['row'] == r]
        if not any(cell['rows'] for cell in cells):
            continue                                # пустая строка таблицы (например, бланк подписей)
        parts, fragments, meta, offset = [], [], [], 0
        line_base = 0
        for i, cell in enumerate(sorted(cells, key=lambda c: c['col'])):
            if i:
                parts.append(' | ')
                offset += 3
            text, frags = _compose_rows(cell['rows'])
            for frag in frags:
                frag = dict(frag, start=frag['start'] + offset, end=frag['end'] + offset, line=frag['line'] + line_base)
                fragments.append(frag)
            line_base += max(1, len(cell['rows']))
            meta.append({'col': cell['col'], 'colspan': cell['colspan'], 'start': offset, 'end': offset + len(text),
                         'rect': _r(cell['box'])})
            parts.append(text)
            offset += len(text)
        is_header = r in record['header_rows']
        loc = _loc(page, fragments)
        loc['table'] = {
            'id': record['id'], 'part': record['part'], 'header_row': is_header,
            'row': 0 if is_header else record['row_base'] + r - len(record['header_rows']) + 1,
            'header': record['header'], 'header_source': record['header_source'],
            'header_restored': bool(record['header']) and len(record['header']) == record['col_count'],
            'cells': meta,
        }
        if is_header and record['header_source'] == 'repeated':
            loc['table']['repeated_header'] = True
        out.append(('table_header' if is_header else 'table_row', ''.join(parts), loc))
    return out


def _extraction(pages: list[dict], blocks: list[Block]) -> dict:
    """Сводка полноты для run.status и вердикта (поле Document.extraction, вне обязательных полей v1)."""
    content = [p for p in pages if p['status'] != 'blank']
    covered = sum(p['coverage'] or 0.0 for p in content)
    completeness = round(covered / len(content), 2) if content else 0.0
    parts: dict[str, list[tuple[int, dict]]] = {}
    for block in blocks:
        if block['loc'].get('table'):
            parts.setdefault(block['loc']['table']['id'], []).append((block['loc']['page'], block['loc']['table']))
    return {
        'reader': READER_VERSION, 'engine': f'PyMuPDF {pymupdf.VersionBind}',
        'pages': len(pages), 'content_pages': len(content), 'completeness': completeness,
        'pages_status': {str(p['no']): p['status'] for p in pages},
        'pages_unread': [p['no'] for p in content if (p['coverage'] or 0.0) < 1.0],
        'pages_ocr': [p['no'] for p in pages if p['status'] in ('ocr', 'partial_ocr')],
        'pages_blank': [p['no'] for p in pages if p['status'] == 'blank'],
        # Многостраничные таблицы: восстановлено ли соответствие шапки и значений на всех частях.
        'tables': [{'id': tid, 'pages': sorted({page for page, _ in group}), 'parts': max(t['part'] for _, t in group),
                    'header_restored': all(t['header_restored'] for _, t in group)} for tid, group in parts.items()],
        'method': 'среднее по непустым страницам: текст = 1, скан/нечитаемый шрифт/кривые = 0, '
                  'смешанная = площадь текста / (площадь текста + изображений без текста)',
    }


# --------------------------------------------------------------------------- диапазон → прямоугольники
def locate_span(block: Block, start: int, end: int) -> dict:
    """Перевод block["text"][start:end] в прямоугольники страницы (по одному на визуальную строку).

    Возвращает ``{block_id, page, rects: [[x0,y0,x1,y1]...], quads?, precision, warning}``.
    precision: ``exact`` — границы диапазона совпали с границами фрагментов;
    ``approx`` — диапазон режет слово, часть слова отмерена пропорционально числу букв;
    ``page`` — координат нет, известна только страница (``warning`` объясняет).
    """
    block_id, text, loc = block['id'], block['text'], block['loc']
    page = loc.get('page')
    fragments = loc.get('fragments') or []
    hits = [f for f in fragments if f['start'] < end and f['end'] > start]
    if not (0 <= start < end <= len(text)) or not hits:
        return {'block_id': block_id, 'page': page, 'rects': [], 'precision': 'page',
                'warning': page_only_warning(block_id, page, text[start:end] if 0 <= start < end <= len(text) else '')}
    precision = 'exact'
    lines: dict[int, list[list[float]]] = {}
    quads = []
    for frag in hits:
        rect = list(frag['rect'])
        a, b = max(start, frag['start']), min(end, frag['end'])
        if (a, b) != (frag['start'], frag['end']):
            precision = 'approx'
            rect = _cut(rect, frag, a, b)
        lines.setdefault(frag['line'], []).append(rect)
        if 'quad' in frag:
            quads.append(frag['quad'])
    rects = [_r(_union(tuple(r) for r in group)) for _, group in sorted(lines.items())]
    result = {'block_id': block_id, 'page': page, 'rects': rects, 'precision': precision, 'warning': None}
    if quads:
        result['quads'] = quads
    return result


def _cut(rect: list[float], frag: dict, a: int, b: int) -> list[float]:
    n = frag['end'] - frag['start']
    lo, hi = (a - frag['start']) / n, (b - frag['start']) / n
    dx, dy = frag.get('dir', [1.0, 0.0])
    x0, y0, x1, y1 = rect
    if abs(dx) >= abs(dy):
        if dx < 0:
            lo, hi = 1 - hi, 1 - lo
        return [x0 + (x1 - x0) * lo, y0, x0 + (x1 - x0) * hi, y1]
    if dy < 0:
        lo, hi = 1 - hi, 1 - lo
    return [x0, y0 + (y1 - y0) * lo, x1, y0 + (y1 - y0) * hi]


def page_only_warning(block_id: str, page: int | None, quote: str = '') -> dict:
    """Предупреждение, когда для опоры известна только страница (нет координат слов)."""
    shown = f'«{quote[:60]}» ' if quote else ''
    return _warn('locate_page_only', 'warning', page,
                 f'Цитата {shown}из блока {block_id} привязана только к странице {page}: координаты слов недоступны, '
                 'подсветка показывает страницу целиком.', block_id=block_id)


# --------------------------------------------------------------------------- диагностика для запуска (№18)
def diagnose_pdf(path: Path | str, *, ocr: str = 'auto') -> dict:
    """Никогда не бросает: {ok, code, message, pages, extraction, warnings} для показа при запуске (№18).

    code: ``complete`` | ``partial`` | ``no_text`` (ни одного блока с текстом) | ``not_pdf`` | ``damaged`` | ``encrypted``.
    """
    try:
        document = read_pdf(path, ocr=ocr)
    except PdfReadError as error:
        return error.diagnostic | {'warnings': []}
    ext = document['extraction']
    has_text = any(b['kind'] != 'other' for b in document['blocks'])
    pages_note = [w['message'] for w in document['warnings'] if w['severity'] == 'error' and w['page']]
    if ext['completeness'] >= 1.0:
        code = 'complete'
        message = f'PDF прочитан: {ext["content_pages"]} стр. с текстом, полнота 100%.'
        if ext['pages_ocr']:
            message += f' OCR на страницах {_pages_text(ext["pages_ocr"])}: сверьте цитаты.'
    else:
        code = 'partial' if has_text else 'no_text'
        summary = next(w['message'] for w in document['warnings'] if w['code'] == 'partial_read' and w['page'] is None)
        message = ' '.join([summary] + pages_note[:3])
    return {'ok': code == 'complete', 'code': code, 'message': message, 'pages': ext['pages_unread'],
            'extraction': ext, 'warnings': document['warnings']}


def main(argv: list[str] | None = None) -> int:
    """python -m bcc_review.readers.pdf FILE [--diagnose] [--ocr auto|off]: JSON в stdout."""
    import argparse
    parser = argparse.ArgumentParser(description='Читалка PDF bcc_review (№02): блоки, координаты, диагностика.')
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--diagnose', action='store_true', help='только диагностика текстового слоя')
    parser.add_argument('--ocr', choices=['auto', 'off'], default='auto')
    args = parser.parse_args(argv)
    if args.diagnose:
        result = diagnose_pdf(args.pdf, ocr=args.ocr)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result['ok'] else 5 if result['code'] == 'partial' else 1
    try:
        document = read_pdf(args.pdf, ocr=args.ocr)
    except PdfReadError as error:
        print(json.dumps(error.diagnostic, ensure_ascii=False, indent=1))
        return 1
    print(json.dumps(document, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
