"""Скрытый текст в исходном файле (№30): то, чего человек при чтении документа не видит, а модель получает.

    from bcc_review.v2.rules import hidden
    view["hidden"] = hidden.scan_file(path)      # [{"how": "скрытый шрифт Word", "text": "…"}, …]

Правило `injection` (и офлайн-отчёт) берёт `view["hidden"]`: фрагмент находит в строках документа и сообщает
как риск — указание для модели в скрытом тексте (major) или просто скрытый текст (major с числом или требованием,
иначе minor). Без `view["hidden"]` работают текстовые признаки (инлайн-HTML в Markdown, символы нулевой ширины,
символы-теги Unicode) — их видно и по строкам документа.

Что ищем:
* DOCX — прогоны со скрытым шрифтом (`w:vanish`), белым цветом, кеглем ≤ 2 пт; во всём теле, таблицах, сносках,
  колонтитулах. Служебное (`w:webHidden` номеров страниц оглавления, коды полей) — не текст документа.
* HTML — `display:none`, `visibility:hidden`, атрибут `hidden`, нулевой кегль или прозрачность, белый цвет;
  комментарии `<!-- … -->` с текстом.
* Markdown/TXT — комментарии `<!-- … -->`, инлайн-HTML со скрывающим стилем, подсказки в title ссылок и картинок.
* PDF — белый текст и текст кеглем меньше 2 пт (нужен pymupdf).
Сканер не падает: на любом сбое возвращает то, что успел найти.
"""
from __future__ import annotations

import html
import re
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

MAX_ITEMS = 50
MIN_LETTERS = 3

HIDING_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:\.0*)?(?:px|pt|em|rem|%)?\s*(?:;|$)|"
    r"opacity\s*:\s*0(?:\.0*)?\s*(?:;|$)|(?<![-\w])color\s*:\s*(?:#fff(?:fff)?\b|white\b|"
    r"rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,\s*1(?:\.0*)?\s*)?\))", re.I)
MD_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
MD_TITLE = re.compile(r"!?\[([^\]]*)\]\(\s*[^)\s]+\s+(?:\"([^\"]+)\"|'([^']+)')\s*\)")
MD_HIDDEN_TAG = re.compile(r"<(\w+)\b([^>]*)>(.*?)</\1\s*>", re.S)


def _letters(s: str) -> int:
    return sum(ch.isalpha() for ch in s)


def _add(found: list[dict], how: str, text: str, plain: bool = True) -> None:
    """`plain` — скрыто маскировкой (белый текст, скрытый шрифт): риск и без указания для модели. False — заметка
    автора или свёрнутый элемент интерфейса (комментарий, title, display:none в HTML): риск, только если там
    указание для модели."""
    t = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    if _letters(t) < MIN_LETTERS or len(found) >= MAX_ITEMS:
        return
    if any(f["text"] == t and f["how"] == how for f in found):
        return
    found.append({"how": how, "text": t[:300], "plain": plain})


# --- DOCX -----------------------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _on(el) -> bool:
    if el is None:
        return False
    v = el.get(f"{_W}val")
    return v is None or v.lower() not in ("0", "false", "off")


def _white(color: str | None) -> bool:
    if not color or color.lower() == "auto":
        return False
    try:
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    except ValueError:
        return False
    return min(r, g, b) >= 0xF5


def _dark_fill(rpr, ppr) -> bool:
    """Белый текст на тёмной заливке виден — не скрытый."""
    for holder in (rpr, ppr):
        if holder is None:
            continue
        shd = holder.find(f"{_W}shd")
        if shd is not None:
            fill = shd.get(f"{_W}fill") or ""
            if fill and fill.lower() != "auto" and not _white(fill):
                return True
        hl = holder.find(f"{_W}highlight")
        if hl is not None and (hl.get(f"{_W}val") or "none") not in ("none", "white"):
            return True
    return False


def _run_hidden(r, ppr) -> str:
    rpr = r.find(f"{_W}rPr")
    if rpr is None:
        return ""
    if _on(rpr.find(f"{_W}vanish")):
        return "скрытый шрифт Word"
    c = rpr.find(f"{_W}color")
    if c is not None and _white(c.get(f"{_W}val")) and not _dark_fill(rpr, ppr):
        return "белый текст на белом фоне"
    sz = rpr.find(f"{_W}sz")
    if sz is not None:
        try:
            if int(sz.get(f"{_W}val") or 99) <= 4:  # полупункты: 4 = 2 пт
                return "текст кеглем 2 пт и меньше"
        except ValueError:
            pass
    return ""


def _scan_docx(data: bytes, found: list[dict]) -> None:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(BytesIO(data)) as z:
        parts = [n for n in z.namelist() if re.match(r"word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml$", n)]
        for name in parts:
            root = ET.fromstring(z.read(name))
            for p in root.iter(f"{_W}p"):
                ppr = p.find(f"{_W}pPr")
                cur_how, buf = "", []
                for r in p.iter(f"{_W}r"):
                    if r.find(f"{_W}instrText") is not None:
                        continue  # код поля (оглавление, ссылки) — служебный
                    text = "".join(t.text or "" for t in r.iter(f"{_W}t"))
                    if not text:
                        continue
                    how = _run_hidden(r, ppr)
                    if how and how == cur_how:
                        buf.append(text)
                        continue
                    if cur_how:
                        _add(found, cur_how, "".join(buf))
                    cur_how, buf = how, [text] if how else []
                if cur_how:
                    _add(found, cur_how, "".join(buf))


# --- HTML -----------------------------------------------------------------------------------------

class _HiddenHTML(HTMLParser):
    VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "source", "wbr"}

    def __init__(self, found: list[dict]) -> None:
        super().__init__(convert_charrefs=True)
        self.found = found
        self.stack: list[tuple[str, str]] = []  # (тег, причина скрытия или "")
        self.buf: list[str] = []
        self.skip = 0

    def _hidden(self) -> str:
        return next((h for _, h in reversed(self.stack) if h), "")

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template", "noscript"):
            self.skip += 1
        if tag in self.VOID:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        how = ""
        if "hidden" in a:
            how = "свёрнутый элемент HTML (атрибут hidden)"
        else:
            m = HIDING_STYLE.search(a.get("style", ""))
            if m:
                folded = re.match(r"display|visibility", m.group(0), re.I)
                how = f"{'свёрнутый элемент' if folded else 'скрытый стиль'} HTML ({m.group(0).strip(' ;')})"
        if how and not self._hidden():
            self.buf = []
        self.stack.append((tag, how))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag in self.VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                was = self._hidden()
                del self.stack[i:]
                if was and not self._hidden():
                    # display:none и hidden — обычные свёрнутые блоки страницы (раскрывающиеся разделы Confluence)
                    _add(self.found, was, " ".join(self.buf), plain=not was.startswith("свёрнутый"))
                    self.buf = []
                return

    def handle_data(self, data):
        if not self.skip and self._hidden():
            self.buf.append(data)

    def handle_comment(self, data):
        _add(self.found, "комментарий HTML", data, plain=False)


def _scan_html(text: str, found: list[dict]) -> None:
    p = _HiddenHTML(found)
    p.feed(text)
    p.close()


# --- Markdown / TXT ---------------------------------------------------------------------------------

def _scan_md(text: str, found: list[dict]) -> None:
    for m in MD_COMMENT.finditer(text):
        _add(found, "комментарий в разметке (не виден при просмотре)", m.group(1), plain=False)
    for m in MD_HIDDEN_TAG.finditer(text):
        attrs = m.group(2)
        h = HIDING_STYLE.search(attrs) or re.search(r"\shidden\b", attrs)
        if h:
            _add(found, "скрытый инлайн-HTML в разметке", re.sub(r"<[^>]+>", " ", m.group(3)))
    for m in MD_TITLE.finditer(text):
        title = m.group(2) or m.group(3) or ""
        _add(found, "подсказка (title) ссылки или картинки", title, plain=False)


# --- PDF ------------------------------------------------------------------------------------------

def _scan_pdf(data: bytes, found: list[dict]) -> None:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore
        except ImportError:
            return
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page in doc:
            rect = page.rect
            for b in page.get_text("dict").get("blocks", []):
                for ln in b.get("lines", []):
                    for sp in ln.get("spans", []):
                        t = sp.get("text") or ""
                        how = ""
                        if (sp.get("color") or 0) >= 0xF5F5F5 and all(((sp.get("color") or 0) >> s) & 0xFF >= 0xF5
                                                                      for s in (0, 8, 16)):
                            how = "белый текст в PDF"
                        elif (sp.get("size") or 99) < 2:
                            how = "текст кеглем меньше 2 пт в PDF"
                        else:
                            x0, y0, x1, y1 = sp.get("bbox") or (0, 0, 0, 0)
                            if x1 < rect.x0 or x0 > rect.x1 or y1 < rect.y0 or y0 > rect.y1:
                                how = "текст за границей страницы PDF"
                        if how:
                            _add(found, how, t)
    finally:
        doc.close()


# --- вход -----------------------------------------------------------------------------------------

def scan_bytes(data: bytes, fmt: str) -> list[dict]:
    """Скрытые фрагменты файла: [{"how", "text"}], не больше 50. Никогда не бросает исключение."""
    found: list[dict] = []
    fmt = (fmt or "").lower().lstrip(".")
    try:
        if fmt == "docx":
            _scan_docx(data, found)
        elif fmt in ("html", "htm"):
            _scan_html(data.decode("utf-8", errors="replace"), found)
        elif fmt == "pdf":
            _scan_pdf(data, found)
        elif fmt in ("md", "markdown", "txt", "text", ""):
            text = data.decode("utf-8-sig", errors="replace")
            _scan_md(text, found)
    except Exception:  # noqa: BLE001 — сканер скрытого не должен ронять чтение документа
        pass
    return found


def scan_file(path: str | Path) -> list[dict]:
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError:
        return []
    return scan_bytes(data, p.suffix)
