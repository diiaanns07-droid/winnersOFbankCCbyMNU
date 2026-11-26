"""Чтение HTML для v2 (владелец №03): п. 1 ТЗ «остальные форматы в плюс».

Стандартный ``html.parser``, без внешних зависимостей. Заголовки ``h1–h6``, абзацы, пункты списков (нумерованные —
с номером), строки таблиц (ячейки через « | »), блоки ``pre`` (построчно), ``br`` — перенос строки. Скрипты, стили,
``head``, ``nav``, ``template``, ``svg`` пропускаются. Каждый блок — строка DocView (многострочный — несколько строк);
``src_line`` — строка HTML-файла, где начинается блок; раздел — путь заголовков через « › ».
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

SECTION_SEP = " › "
_SKIP = {"script", "style", "head", "noscript", "template", "svg", "nav", "iframe", "object", "button", "select",
         "option", "textarea", "form"}
_BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "aside", "blockquote", "figure",
          "figcaption", "caption", "dt", "dd", "address", "details", "summary", "center", "body", "html", "dl",
          "fieldset", "legend"}
_HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_VOID = {"br", "hr", "img", "input", "meta", "link", "wbr", "col", "area", "base", "source", "track", "embed"}
_WS = re.compile(r"[ \t\r\n\f\v    ]+")


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._pre = 0
        self._cur: dict | None = None      # текущий блок: kind, parts, src_line, level
        self._lists: list[dict] = []       # {"ordered": bool, "n": int}
        self._row: list[str] | None = None
        self._row_line = 0
        self._row_head = False
        self._cell: list[str] | None = None

    # ------------------------------------------------------------------ блоки
    def _start(self, kind: str, level: int | None = None, prefix: str = "") -> None:
        if self._cur is not None and not "".join(self._cur["parts"]).strip() and kind == "paragraph":
            return  # обёртка без текста (div → p, li → p): продолжаем текущий блок
        self._flush()
        self._cur = {"kind": kind, "parts": [prefix] if prefix else [], "src_line": self.getpos()[0], "level": level}

    def _flush(self) -> None:
        cur, self._cur = self._cur, None
        if cur is None:
            return
        raw = "".join(cur["parts"])
        if cur["kind"] == "code":
            lines = [ln.rstrip() for ln in raw.strip("\n").split("\n")]
        else:
            lines = [_WS.sub(" ", ln).strip() for ln in raw.split("\n")]
        lines = [ln for ln in lines if ln.strip()] if cur["kind"] != "code" else lines
        if not any(ln.strip() for ln in lines):
            return
        self.blocks.append({"kind": cur["kind"], "lines": lines, "src_line": cur["src_line"], "level": cur["level"]})

    def _text(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
            return
        if self._cur is None:
            if not data.strip():
                return
            lead = data[:len(data) - len(data.lstrip())].count("\n")
            self._cur = {"kind": "paragraph", "parts": [], "src_line": self.getpos()[0] + lead, "level": None}
        self._cur["parts"].append(data)

    # ------------------------------------------------------------------ события парсера
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if self._skip:
            return
        if tag in ("tr",):
            self._flush()
            self._row, self._row_line, self._row_head = [], self.getpos()[0], False
            return
        if tag in ("td", "th"):
            if self._row is None:  # ячейка без строки — считаем строкой
                self._flush()
                self._row, self._row_line = [], self.getpos()[0]
            self._cell = []
            self._row_head = self._row_head or tag == "th"
            return
        if self._cell is not None:
            if tag in ("br", "p", "div", "li"):
                self._cell.append(" ")
            return
        if tag in _HEAD:
            self._start("heading", _HEAD[tag])
            return
        if tag == "pre":
            self._flush()
            self._pre += 1
            self._cur = {"kind": "code", "parts": [], "src_line": self.getpos()[0], "level": None}
            return
        if tag in ("ul", "ol"):
            self._flush()
            start = 1
            for k, v in attrs:
                if k == "start" and v and v.strip().lstrip("-").isdigit():
                    start = int(v)
            self._lists.append({"ordered": tag == "ol", "n": start - 1})
            return
        if tag == "li":
            prefix = ""
            if self._lists and self._lists[-1]["ordered"]:
                self._lists[-1]["n"] += 1
                prefix = f"{self._lists[-1]['n']}. "
            self._flush()
            self._cur = {"kind": "list_item", "parts": [prefix] if prefix else [], "src_line": self.getpos()[0],
                         "level": len(self._lists)}
            return
        if tag == "br":
            if self._cur is not None:
                self._cur["parts"].append("\n")
            return
        if tag == "hr":
            self._flush()
            return
        if tag in _BLOCK:
            self._start("paragraph")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if self._skip:
            return
        if tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append(_WS.sub(" ", "".join(self._cell)).strip())
            self._cell = None
            return
        if tag == "tr":
            self._end_row()
            return
        if tag in ("table", "thead", "tbody", "tfoot"):
            self._end_row()
            return
        if self._cell is not None:
            return
        if tag == "pre":
            self._pre = max(0, self._pre - 1)
            self._flush()
            return
        if tag in ("ul", "ol"):
            self._flush()
            if self._lists:
                self._lists.pop()
            return
        if tag in _HEAD or tag == "li" or tag in _BLOCK:
            self._flush()

    def _end_row(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(_WS.sub(" ", "".join(self._cell)).strip())
            self._cell = None
        if self._row is not None:
            cells = self._row
            self._row = None
            if any(c for c in cells):
                self.blocks.append({"kind": "table_header" if self._row_head else "table_row",
                                    "lines": [" | ".join(cells)], "src_line": self._row_line, "level": None})

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        self._text(data)

    def close(self) -> None:
        super().close()
        self._end_row()
        self._flush()


def parse_html(text: str) -> tuple[str, list[dict]]:
    """Разобрать HTML: (title, blocks), где block = {kind, lines, src_line, level}."""
    p = _Parser()
    p.feed(text)
    p.close()
    return _WS.sub(" ", p.title).strip(), p.blocks


def view_from_html(text: str, *, file: str = "document.html") -> dict:
    """DocView из строки HTML."""
    title, blocks = parse_html(text)
    lines: list[dict] = []
    heads: list[tuple[int, str]] = []
    for i, b in enumerate(blocks, 1):
        if b["kind"] == "heading":
            lvl = b["level"] or 1
            heads = [h for h in heads if h[0] < lvl] + [(lvl, " ".join(b["lines"]).strip())]
        section = SECTION_SEP.join(h[1] for h in heads)
        bid = f"h{i:04d}"
        for part in b["lines"]:
            lines.append({"n": len(lines) + 1, "text": part, "page": None, "section": section,
                          "src_line": b["src_line"], "block_id": bid, "kind": b["kind"],
                          "level": (b["level"] or 1) if b["kind"] == "heading" else 0,
                          "heading": b["kind"] == "heading"})
    h1 = next((" ".join(b["lines"]).strip() for b in blocks if b["kind"] == "heading" and b["level"] == 1), "")
    doc_title = h1 or title or next((ln["text"] for ln in lines if ln["text"].strip()), "") or Path(file).stem
    if h1:  # заголовок документа в разделах не повторяем
        pref = h1 + SECTION_SEP
        for ln in lines:
            if ln["section"] == h1:
                ln["section"] = ""
            elif ln["section"].startswith(pref):
                ln["section"] = ln["section"][len(pref):]
    warnings = [] if lines else ["В HTML нет видимого текста: проверять нечего."]
    return {"title": doc_title[:200], "file": file, "format": "html",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "lines": lines, "pages": None,
            "warnings": warnings}


def load_html(path: str | Path) -> dict:
    p = Path(path)
    data = p.read_bytes()
    text = _decode(data)
    view = view_from_html(text, file=p.name)
    view["sha256"] = hashlib.sha256(data).hexdigest()
    return view


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    head = data[:2048].decode("ascii", errors="ignore").lower()
    m = re.search(r"charset=[\"']?([a-z0-9_\-]+)", head)
    enc = m.group(1) if m else "utf-8"
    try:
        return data.decode(enc)
    except (LookupError, UnicodeDecodeError):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("cp1251", errors="replace")
