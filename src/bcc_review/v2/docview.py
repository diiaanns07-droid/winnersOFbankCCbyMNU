"""Документ с номерами строк — основа доказательности v2 (владелец №03).

``load(path)`` читает файл читателями v1 (``bcc_review.engine.read_document``: MD/TXT/PDF/DOCX) или
``readers_html`` (HTML) и превращает его в ``DocView`` (CONTRACT.md, раздел 2.1):

* MD/TXT — одна строка view = одна строка исходного файла (номера совпадают с GitHub). Текст — видимый,
  без разметки: без ``**``, обратных кавычек, маркеров списка ``* ``/``- ``, решёток заголовков; ячейки
  таблицы через « | »; строка-разделитель таблицы, ограждения блока кода и ``---`` — пустые строки.
  Пустые строки сохраняются для нумерации.
* PDF/DOCX/HTML — по строке на блок читателя (абзац, пункт, строка таблицы, заголовок); многострочный
  блок даёт несколько строк. Для PDF у каждой строки есть страница.

Сверх контракта у строки есть ``kind`` (вид блока читателя: heading, paragraph, list_item, table_header, table_row,
code; пусто у пустой строки), ``level`` (уровень заголовка, у остальных 0) и ``heading`` (строка — заголовок) —
для нарезки, правил и HTML (CONTRACT, раздел 9).

``numbered(view)`` — текст для модели: «L038| …», для PDF «L045| [с.3] …».
Номер строки, страницу и раздел считает код, а не модель.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Iterable

# PyMuPDF без пакета pymupdf_layout печатает в stdout совет его поставить — это засоряет вывод агента
# (просьба №16). Переменная проверяется в момент разбора страницы, поэтому достаточно задать её здесь.
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")


def pdf_fast_mode() -> None:
    """Выключить нейросетевой анализ вёрстки PyMuPDF 2.x (пакет ``pymupdf_layout``, ONNX).

    ``pip install -e .`` ставит свежий PyMuPDF 2.x вместе с ``pymupdf_layout``; тогда ``page.find_tables()`` в
    читателе v1 гоняет модель на каждой странице: 0,55 с на страницу (официальный PDF — 4 с, 19 страниц — 10 с) и
    результат зависит от установки. Без модели поиск таблиц — по линейкам, как в зафиксированном PyMuPDF 1.28:
    текст строк, страницы и разделы те же, чтение в 10 раз быстрее. Повторный вызов безопасен; PyMuPDF 1.x не
    затрагивается (флага нет)."""
    try:
        import pymupdf
    except Exception:  # noqa: BLE001 — без PyMuPDF PDF не читается вовсе, ошибку даст читатель
        return
    if hasattr(pymupdf, "_layout_enabled"):
        pymupdf._layout_enabled = False


SECTION_SEP = " › "
FORMATS = {".md": "md", ".markdown": "md", ".txt": "txt", ".pdf": "pdf", ".docx": "docx",
           ".html": "html", ".htm": "html"}

_MD_DECOR = re.compile(r"\*\*|__|`")
_MD_BULLET = re.compile(r"^\s*(?:[*+\-]|\d{1,3}[.)])\s+")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_MD_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_TABLE_DELIM = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BULLET_GLYPH = re.compile(r"^[•◦▪▫‣●○■□·∙*]\s+")
_PAGE_WARN_CODES = {"partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input",
                    "images_not_read", "table_unreliable", "layout_grid_unreliable", "docx_empty"}


# --------------------------------------------------------------------------- публичный интерфейс
CONVERTIBLE = {".doc", ".rtf", ".odt", ".docm", ".dotx", ".dot", ".wps"}
SUPPORTED_RU = "DOCX, PDF, Markdown, TXT, HTML"


def load(path: str | Path) -> dict:
    """Прочитать файл и вернуть DocView. Неподдерживаемый формат — ``ValueError`` с объяснением по-русски.

    DOC, RTF, ODT читаются через преобразование в DOCX (LibreOffice ``soffice``), если он установлен."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"файл не найден: {p}")
    suffix = p.suffix.lower()
    if suffix in CONVERTIBLE:
        return _load_converted(p)
    fmt = FORMATS.get(suffix)
    if fmt is None:
        raise ValueError(f"формат {p.suffix or '(без расширения)'} не поддерживается; сохраните документ как "
                         f"{SUPPORTED_RU}")
    data = p.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if fmt == "html":
        from . import readers_html
        view = readers_html.load_html(p)
        view["sha256"] = sha
        return view
    warnings: list[str] = []
    doc: dict | None = None
    if fmt == "pdf":
        pdf_fast_mode()
    try:
        from bcc_review.engine import read_document
        doc = None
        if fmt == "txt" and _looks_markdown(_decode_text(data)):
            try:
                doc = _read_as_markdown(p, data, read_document)
            except Exception:  # noqa: BLE001 — не вышло как Markdown: читаем как простой текст
                doc = None
        if doc is None:
            doc = read_document(p)
    except Exception as exc:  # noqa: BLE001 — читатель v1 не должен ронять v2 на MD/TXT
        if fmt in ("pdf", "docx"):
            raise
        warnings.append(f"Читатель разметки не сработал ({type(exc).__name__}: {exc}); "
                        "строки взяты из файла как есть.")
    if fmt == "pdf" and doc:
        recovered = _recover_garbled_pages(doc, p)
        if recovered:
            what = f"Страница {recovered[0]}" if len(recovered) == 1 else f"Страницы {_pages_list(recovered)}"
            warnings.append(f"{what}: читатель счёл текстовый слой нечитаемым, текст восстановлен напрямую из PDF "
                            "(проверьте в исходнике).")
    if fmt in ("md", "txt"):
        text = _decode_text(data)
        lines = _text_lines(text, doc, tab_cells=fmt == "txt" and not _looks_markdown(text))
    else:
        sizes = _page_sizes(p) if fmt == "pdf" else {}
        lines = _block_lines(doc or {}, sizes, warnings)
    title = _title(doc, lines, p)
    _strip_title_from_sections(lines, title)
    pages = None
    if fmt == "pdf":
        ext = (doc or {}).get("extraction") or {}
        pages = ext.get("pages") or max((ln["page"] or 0 for ln in lines), default=0) or None
    warnings += _doc_warnings(doc)
    if fmt == "docx":
        warnings += _docx_revisions(data)
        try:
            lines, boxes = _docx_textboxes(data, lines)
        except Exception:  # noqa: BLE001 — надписи необязательны
            boxes = 0
        if boxes:
            warnings.append(f"Текст из надписей Word (текстовых полей) добавлен после абзаца, к которому они "
                            f"привязаны: {boxes} абз.")
    if not any(ln["text"].strip() for ln in lines) and not warnings:
        warnings.append("В документе нет текста: проверять нечего.")
    return {"title": title, "file": p.name, "format": fmt, "sha256": sha, "lines": lines,
            "pages": pages, "warnings": _dedup(warnings)}


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


_MD_HEAD_LINE = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.M)
_MD_BOLD = re.compile(r"\*\*[^*\n]+\*\*")


def _looks_markdown(text: str) -> bool:
    """TXT, внутри которого Markdown (переименованный .md, выгрузка из Confluence/GitLab): заголовки «## …»,
    разделители таблиц «|---|», «**жирный**». Обычный текст с одним «#» или парой звёздочек — не Markdown."""
    heads = len(_MD_HEAD_LINE.findall(text))
    delims = sum(1 for ln in text.splitlines() if "|" in ln and _TABLE_DELIM.match(ln))
    bold = len(_MD_BOLD.findall(text))
    return heads >= 2 or delims >= 2 or (heads >= 1 and (delims >= 1 or bold >= 2))


def _read_as_markdown(p: Path, data: bytes, read_document) -> dict:
    """Прочитать TXT читателем Markdown v1 (копия с расширением .md во временном каталоге); строки — те же."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / (p.stem + ".md")
        md.write_text(_decode_text(data), encoding="utf-8")
        return read_document(md)


def _docx_textboxes(data: bytes, lines: list[dict]) -> tuple[list[dict], int]:
    """Надписи Word (текстовые поля, ``w:txbxContent``) читатель v1 не видит — требование в надписи пропадало бы.
    Абзацы надписи вставляются после строки абзаца, к которому надпись привязана (или после предыдущего непустого
    абзаца); запасная копия VML внутри ``mc:Fallback`` не дублируется. Возвращает строки и число добавленных абзацев."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
        if b"txbxContent" not in xml:
            return lines, 0
        body = ET.fromstring(xml).find(f"{_W}body")
    except Exception:  # noqa: BLE001 — повреждённый DOCX уже прочитан читателем v1, надписи не обязательны
        return lines, 0
    if body is None:
        return lines, 0

    def walk(el, in_box: bool, own: list[str], boxes: list[list[str]]) -> None:
        for ch in el:
            if ch.tag == _MC_FALLBACK:
                continue
            if ch.tag == f"{_W}txbxContent":
                paras = ["".join(t.text or "" for t in p.iter(f"{_W}t")).strip() for p in ch.iter(f"{_W}p")]
                boxes.append([x for x in paras if x])
                continue
            if ch.tag == f"{_W}t" and not in_box:
                own.append(ch.text or "")
            walk(ch, in_box, own, boxes)

    plan: list[tuple[str, list[str]]] = []   # (текст абзаца-якоря или предыдущего, абзацы надписи)
    prev = ""
    for el in body:
        own: list[str] = []
        boxes: list[list[str]] = []
        walk(el, False, own, boxes)
        text = " ".join("".join(own).split())
        anchor = text or prev
        for box in boxes:
            if box:
                plan.append((anchor, box))
        if text:
            prev = text
    if not plan:
        return lines, 0
    have = {_norm_key(ln["text"]) for ln in lines if ln["text"].strip()}
    out = list(lines)
    pos = 0
    added = 0
    for anchor, box in plan:
        box = [t for t in box if _norm_key(t) not in have]   # уже есть в тексте (читатель увидел) — не дублируем
        if not box:
            continue
        key = _norm_key(anchor)[:60]
        at = None
        for k in range(pos, len(out)):
            if key and key in _norm_key(out[k]["text"]):
                at = k
                break
        if at is None:
            at = len(out) - 1 if out else -1
        while at + 1 < len(out) and at >= 0 and out[at + 1].get("block_id") == out[at].get("block_id") \
                and out[at].get("block_id"):
            at += 1  # после последней строки того же блока
        base = out[at] if at >= 0 else {"section": "", "page": None}
        new = [{"n": 0, "text": _clean(t), "page": base.get("page"), "section": base.get("section", ""),
                "src_line": None, "block_id": f"txbx{added + i + 1}", "kind": "paragraph", "level": 0,
                "heading": False} for i, t in enumerate(box)]
        out[at + 1:at + 1] = new
        pos = at + 1 + len(new)
        added += len(new)
    for i, ln in enumerate(out, 1):
        ln["n"] = i
    return out, added


def _norm_key(t: str) -> str:
    return " ".join(str(t or "").split()).casefold()


def _docx_revisions(data: bytes) -> list[str]:
    """Непринятые исправления Word (режим рецензирования): текст читается в итоговой редакции — об этом стоит сказать."""
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    ins, dels = len(re.findall(r"<w:ins\b", xml)), len(re.findall(r"<w:del\b", xml))
    if not ins and not dels:
        return []
    return [f"В документе есть непринятые исправления (вставок {ins}, удалений {dels}): проверена итоговая редакция "
            "— вставки учтены, удалённый текст не проверялся."]


def _decode_text(data: bytes) -> str:
    """UTF-8 (с BOM или без), иначе Windows-1251 — так сохраняют текст в Блокноте на русской Windows."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _load_converted(p: Path) -> dict:
    """DOC/RTF/ODT → DOCX через LibreOffice во временном каталоге; паспорт (имя, SHA-256) — исходного файла."""
    import shutil
    import subprocess
    import tempfile
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ValueError(f"формат {p.suffix} читается через LibreOffice, а он не установлен; сохраните документ "
                         f"как {SUPPORTED_RU}")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, str(p)],
                           check=True, capture_output=True, timeout=180)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError(f"не удалось преобразовать {p.name} в DOCX ({type(exc).__name__}); сохраните "
                             f"документ как {SUPPORTED_RU}") from exc
        out = Path(tmp) / (p.stem + ".docx")
        if not out.is_file():
            raise ValueError(f"не удалось преобразовать {p.name} в DOCX; сохраните документ как {SUPPORTED_RU}")
        view = load(out)
    view["file"] = p.name
    view["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    view["warnings"] = [f"Документ {p.suffix.upper().lstrip('.')} прочитан через преобразование в DOCX "
                        f"(LibreOffice); номера строк — по преобразованному тексту."] + list(view["warnings"])
    if view.get("title") == p.stem + ".docx" or not view.get("title"):
        view["title"] = p.stem
    return view


def from_text(text: str, *, file: str = "inline.md", fmt: str = "md", title: str = "") -> dict:
    """DocView из строки Markdown/текста (для тестов и веб-демо без файла)."""
    doc = None
    try:
        import tempfile
        from bcc_review.engine import read_document
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ("doc.md" if fmt == "md" else "doc.txt")
            path.write_text(text, encoding="utf-8")
            doc = read_document(path)
    except Exception:  # noqa: BLE001
        doc = None
    lines = _text_lines(text, doc)
    t = title or _title(doc, lines, Path(file))
    _strip_title_from_sections(lines, t)
    return {"title": t, "file": file, "format": fmt,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "lines": lines, "pages": None, "warnings": []}


def numbered(view: dict, start: int = 1, end: int | None = None) -> str:
    """Нумерованный текст «L038| …» (для PDF/DOCX со страницей «L045| [с.3] …»), строки start..end включительно."""
    width = max(3, len(str(len(view.get("lines") or []))))
    out = []
    for ln in view.get("lines") or []:
        n = ln["n"]
        if n < start or (end is not None and n > end):
            continue
        page = f"[с.{ln['page']}] " if ln.get("page") else ""
        out.append(f"L{n:0{width}d}| {page}{ln['text']}".rstrip())
    return "\n".join(out)


def line(view: dict, n: int) -> dict | None:
    """Строка view по номеру (с 1) или None."""
    lines = view.get("lines") or []
    if 1 <= n <= len(lines) and lines[n - 1]["n"] == n:
        return lines[n - 1]
    return next((ln for ln in lines if ln["n"] == n), None)


def text_of(view: dict, start: int, end: int | None = None) -> str:
    """Текст строк start..end, через пробел (пустые строки пропускаются)."""
    end = start if end is None else end
    return " ".join(ln["text"].strip() for ln in view.get("lines") or []
                    if start <= ln["n"] <= end and ln["text"].strip())


def section_of(view: dict, n: int) -> str:
    ln = line(view, n)
    return ln["section"] if ln else ""


def page_of(view: dict, n: int) -> int | None:
    ln = line(view, n)
    return ln["page"] if ln else None


def place(view: dict, start: int, end: int | None = None) -> str:
    """Человекочитаемое место, как в отчёте: «строки 38–40», для PDF «строка 25, стр. 2»."""
    end = start if end is None else end
    rng = f"строка {start}" if end == start else f"строки {start}–{end}"
    p1, p2 = page_of(view, start), page_of(view, end)
    if p1:
        pg = f"стр. {p1}" if not p2 or p2 == p1 else f"стр. {p1}–{p2}"
        return f"{rng}, {pg}"
    return rng


def nonempty(view: dict) -> list[dict]:
    return [ln for ln in view.get("lines") or [] if ln["text"].strip()]


# --------------------------------------------------------------------------- MD / TXT
def _text_lines(text: str, doc: dict | None, tab_cells: bool = False) -> list[dict]:
    """Строка view = строка файла. Текст берётся из блоков читателя v1 (он снимает разметку и экранирование),
    строка, не покрытая блоком, — пустая (разделители таблиц, ограждения кода, ``---``)."""
    raw = text.splitlines()
    n_lines = len(raw)
    texts: list[str | None] = [None] * (n_lines + 1)
    sections: list[str] = [""] * (n_lines + 1)
    block_ids: list[str] = [""] * (n_lines + 1)
    kinds: list[str] = [""] * (n_lines + 1)
    levels: list[int] = [0] * (n_lines + 1)
    covered: list[bool] = [False] * (n_lines + 1)
    if doc:
        for b in doc.get("blocks") or []:
            loc = b.get("loc") or {}
            btext = str(b.get("text") or "")
            sec = _section(b)
            ls, le = loc.get("line_start"), loc.get("line_end")
            if isinstance(ls, int) and isinstance(le, int):
                for k in range(max(1, ls), min(n_lines, le) + 1):
                    covered[k] = True
                    sections[k] = sec
                    block_ids[k] = b.get("id", "")
            prefix = _list_prefix(b)
            for i, item in enumerate(loc.get("lines") or []):
                try:
                    ln_no, ts, te = int(item[0]), int(item[1]), int(item[2])
                except (TypeError, ValueError, IndexError):
                    continue
                if not 1 <= ln_no <= n_lines:
                    continue
                part = btext[ts:te]
                if i == 0 and prefix:
                    part = prefix + part
                texts[ln_no] = part if texts[ln_no] is None else f"{texts[ln_no]} {part}"
                sections[ln_no] = sec
                block_ids[ln_no] = b.get("id", "")
                kinds[ln_no] = str(b.get("kind") or "")
                levels[ln_no] = _level(b)
    out: list[dict] = []
    in_fence = False
    cur_section = ""
    for k in range(1, n_lines + 1):
        src = raw[k - 1]
        if _MD_FENCE.match(src):
            in_fence = not in_fence
            t = ""
        elif texts[k] is not None:
            t = texts[k]
        elif doc and covered[k]:
            t = ""  # строка внутри блока без текста: разделитель таблицы, ограждение кода
        elif doc:
            t = "" if not src.strip() or _MD_RULE.match(src) or _TABLE_DELIM.match(src) else _strip_md(src, in_fence)
        else:
            t = _strip_md(src, in_fence)
        if tab_cells and t and "\t" in src.strip():
            # простой текст из Word («Сохранить как обычный текст»): ячейки таблицы через табуляцию
            cells = [c.strip() for c in src.strip().split("\t")]
            if sum(1 for c in cells if c) >= 2:
                t = " | ".join(c for c in cells if c)
                kinds[k] = "table_row"
        t = _clean(t)
        html_row = None if in_fence or _MD_FENCE.match(src) else _html_table_line(t)
        if html_row is not None:
            t = html_row
        if sections[k]:
            cur_section = sections[k]
        kind = kinds[k] if t else ""
        if not doc and t:
            kind = "heading" if _MD_HEADING.match(src) else ("table_row" if " | " in t else "paragraph")
        if html_row:
            kind = "table_row"
        out.append({"n": k, "text": t, "page": None, "section": sections[k] or cur_section,
                    "src_line": k, "block_id": block_ids[k], "kind": kind,
                    "level": levels[k] if kind == "heading" else 0, "heading": kind == "heading"})
    return out


_HTML_TABLE_TAG = re.compile(r"^\s*(?:</?(?:table|thead|tbody|tfoot|tr|colgroup|col)\b[^>]*>\s*)+$", re.I)
_HTML_CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)(?:</t[dh]>|(?=<t[dh]\b)|$)", re.I | re.S)


def _html_table_line(t: str) -> str | None:
    """Строка HTML-таблицы внутри Markdown («<tr><td>Порог</td><td>100 ₸</td></tr>») → «Порог | 100 ₸»; строка из
    одних тегов таблицы («<table>», «</tr>») → пустая. Не HTML-таблица — ``None``."""
    if "<" not in t:
        return None
    if _HTML_TABLE_TAG.match(t):
        return ""
    if not re.search(r"<t[dh]\b", t, re.I):
        return None
    import html as _html
    cells = [_WS_RE.sub(" ", _html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in _HTML_CELL.findall(t)]
    return " | ".join(cells) if cells else None


_WS_RE = re.compile(r"\s+")


def _strip_md(s: str, in_code: bool = False) -> str:
    """Запасной путь без читателя v1: снять разметку одной строки Markdown."""
    if in_code:
        return s.rstrip()
    if _MD_RULE.match(s) or _TABLE_DELIM.match(s):
        return ""
    t = _MD_DECOR.sub("", s).rstrip()
    t = _MD_HEADING.sub("", t)
    t = re.sub(r"^\s*[*+\-]\s+", "", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    st = t.strip()
    if st.startswith("|") and st.endswith("|") and len(st) > 1:
        t = " | ".join(c.strip() for c in st[1:-1].split("|"))
    return t


def _list_prefix(b: dict) -> str:
    if b.get("kind") != "list_item":
        return ""
    lst = (b.get("loc") or {}).get("list") or {}
    if lst.get("ordered") and lst.get("number") is not None:
        marker = str(lst.get("marker") or "")
        sep = ")" if marker.endswith(")") else "."
        return f"{lst['number']}{sep} "
    return ""


# --------------------------------------------------------------------------- PDF / DOCX
def _block_lines(doc: dict, sizes: dict | None = None, warnings: list | None = None) -> list[dict]:
    """По строке на блок читателя; многострочный блок — несколько строк с одним block_id.

    PDF: порядок чтения на страницах в две колонки восстанавливается по колонкам; повторяющиеся колонтитулы
    (верх/низ страницы, одинаковый текст на большинстве страниц, номер страницы не в счёт) убираются.
    DOCX: у пунктов автонумерации Word в начало строки ставится номер («1.», «2.1.»), как его видит читатель.
    """
    blocks = [b for b in doc.get("blocks") or [] if isinstance(b, dict)]
    warnings = warnings if warnings is not None else []
    if sizes:
        try:
            blocks, tabled = _borderless_tables(blocks, sizes)
        except Exception:  # noqa: BLE001 — сборка таблиц не должна ронять чтение: блоки как прочитал v1
            tabled = []
        if tabled:
            what = f"странице {tabled[0]}" if len(tabled) == 1 else f"страницах {_pages_list(tabled)}"
            warnings.append(f"Таблица без линеек на {what} собрана по строкам (ячейки — по колонкам и рядам текста); "
                            "связь ячеек проверьте в исходнике.")
        blocks, two_col = _reorder_columns(blocks, sizes)
        if two_col:
            what = (f"Страница {two_col[0]} свёрстана" if len(two_col) == 1
                    else f"Страницы {_pages_list(two_col)} свёрстаны")
            warnings.append(f"{what} в две колонки: порядок чтения восстановлен по колонкам "
                            "(сначала левая, затем правая).")
        before = len(blocks)
        blocks, dropped = _drop_running(blocks, sizes)
        blocks = _split_merged_headings(blocks, sizes)
        blocks, glued = _glue_split_rows(blocks)
        if glued:
            warnings.append(f"Строки таблиц, разорванные переходом на новую страницу, склеены: {glued}.")
        if dropped:
            n = before - len(blocks)
            word = "строка" if n % 10 == 1 and n % 100 != 11 else (
                "строки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "строк")
            sample = "; ".join(f"«{t}»" for t in dropped[:3])
            warnings.append(f"Колонтитулы убраны из текста ({n} {word}): {sample}.")
    out: list[dict] = []
    for b in blocks:
        loc = b.get("loc") or {}
        page = loc.get("page")
        page = int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None
        sec = _section(b)
        text = _tight_text(b) if sizes else str(b.get("text") or "")
        if not sizes and b.get("kind") in ("table_row", "table_header") and "\n" in text.strip():
            # DOCX: абзацы внутри ячейки («Итог 50 000 ₸» + пункты списка) — одна строка таблицы, как в PDF;
            # иначе «Один push» стал бы отдельной строкой без колонок и без связи с условиями строки
            text = "; ".join(x.strip() for x in text.strip().splitlines() if x.strip())
        parts = text.splitlines() or [""]
        label = _list_label(b)
        for i, part in enumerate(parts):
            t = part
            if i == 0 and (b.get("kind") == "list_item" or _BULLET_GLYPH.match(t.lstrip())):
                t = _BULLET_GLYPH.sub("", t.lstrip())
                if label and not t.startswith(label):
                    t = f"{label} {t}"
            out.append({"n": len(out) + 1, "text": _clean(t), "page": page, "section": sec,
                        "src_line": None, "block_id": b.get("id", ""), "kind": str(b.get("kind") or ""),
                        "level": _level(b) if b.get("kind") == "heading" else 0,
                        "heading": b.get("kind") == "heading"})
    out, toc = drop_toc(out)
    if toc:
        warnings.append(f"Оглавление убрано из текста ({toc} строк): оно повторяет заголовки разделов.")
    return out


_TOC_ENTRY = re.compile(r"^(?P<title>.*?\S)(?:\s*(?:\.{2,}|…+|_{3,}|·{3,}))?\s*(?P<page>\d{1,4})\s*$")
_TOC_TITLES = {"содержание", "оглавление", "contents", "table of contents", "содержание документа"}


def drop_toc(lines: list[dict]) -> tuple[list[dict], int]:
    """Оглавление: подряд ≥ 2 строки «заголовок … номер страницы», где заголовок совпадает с заголовком раздела
    документа, и строка «Содержание»/«Оглавление» перед ними. Убираются, номера строк пересчитываются."""
    heads = {_toc_key(ln["text"]) for ln in lines if ln.get("kind") == "heading" and ln["text"].strip()}
    if not heads:
        return lines, 0

    def entry(ln: dict) -> bool:
        if ln.get("kind") == "heading":
            return False
        m = _TOC_ENTRY.match(ln["text"])
        return bool(m) and _toc_key(m.group("title")) in heads
    drop: set[int] = set()
    i = 0
    while i < len(lines):
        if entry(lines[i]):
            j = i
            while j < len(lines) and (entry(lines[j]) or not lines[j]["text"].strip()):
                j += 1
            run = [k for k in range(i, j) if lines[k]["text"].strip()]
            if len(run) >= 2:
                drop.update(range(i, j))
                k = i - 1
                while k >= 0 and not lines[k]["text"].strip():
                    k -= 1
                if k >= 0 and lines[k]["text"].strip().casefold().rstrip(":") in _TOC_TITLES:
                    drop.add(k)
            i = max(j, i + 1)
        else:
            i += 1
    if not drop:
        return lines, 0
    kept = [dict(ln) for k, ln in enumerate(lines) if k not in drop]
    for n, ln in enumerate(kept, 1):
        ln["n"] = n
    return kept, sum(1 for k in drop if lines[k]["text"].strip())


def _toc_key(text: str) -> str:
    t = re.sub(r"\s+", " ", text.casefold().replace("ё", "е")).strip(" .:")
    return t


def _cell_word_break(b: dict, frags: list[dict], f1: dict, f2: dict, text: str) -> bool:
    """Слово разорвано переносом внутри узкой ячейки таблицы без дефиса («strin g», «Mandator y»): первая часть —
    последний фрагмент своей строки в ячейке и доходит до правого края ячейки (следующая буква не помещалась),
    продолжение начинается со строчной буквы у левого края ячейки на следующей строке."""
    cells = ((b.get("loc") or {}).get("table") or {}).get("cells") or []
    cell = next((c for c in cells if isinstance(c, dict) and c.get("rect")
                 and c.get("start", 0) <= f1["start"] and f2["end"] <= c.get("end", -1)), None)
    if cell is None or not isinstance(f1.get("line"), int) or f2.get("line") != f1["line"] + 1:
        return False
    w1, w2 = text[f1["start"]:f1["end"]], text[f2["start"]:f2["end"]]
    # только латинские идентификаторы (имена полей, типы, заголовки столбцов API): для кириллицы перенос по слову
    # («Идентификатор / карты») геометрически не отличить от разрыва слова, а цитаты находит поиск без пробелов
    # (и пути/URL: «/savings/{a ccountId}/inter est»)
    if (len(w1) < 3 or not re.fullmatch(r"[\x21-\x7e]*[A-Za-z][A-Za-z0-9]*", w1) or sum(ch.isalpha() for ch in w1) < 2
            or not re.fullmatch(r"[a-z][\x21-\x7e]*", w2)):
        return False
    same_line = [f for f in frags if f.get("line") == f1["line"] and cell["start"] <= f["start"] < cell["end"]]
    if max(f["rect"][2] for f in same_line) > f1["rect"][2] + 0.5:
        return False  # первая часть — последний фрагмент своей строки в ячейке
    in_cell = [f for f in frags if cell["start"] <= f["start"] < cell["end"]]
    pad = max(0.0, min(f["rect"][0] for f in in_cell) - cell["rect"][0])
    inner_right = cell["rect"][2] - pad
    char_w = max((f1["rect"][2] - f1["rect"][0]) / max(len(w1), 1), (f2["rect"][2] - f2["rect"][0]) / max(len(w2), 1))
    left = cell["rect"][0] + pad
    # следующая буква не помещалась в строку ячейки (средняя ширина знака занижает широкие «m», «w» — запас 1,6)
    return inner_right - f1["rect"][2] < 1.6 * char_w + 0.5 and abs(f2["rect"][0] - left) < 2.5


def _rows(frags: list[dict]) -> list[list[dict]]:
    """Фрагменты → визуальные ряды (перекрытие по высоте ≥ половины меньшего фрагмента), ряды сверху вниз, в ряду
    слева направо."""
    rows: list[list[dict]] = []
    for f in sorted(frags, key=lambda f: (f["rect"][1] + f["rect"][3]) / 2):
        y0, y1 = f["rect"][1], f["rect"][3]
        for row in rows:
            r0, r1 = min(g["rect"][1] for g in row), max(g["rect"][3] for g in row)
            if min(y1, r1) - max(y0, r0) >= 0.5 * min(y1 - y0, r1 - r0, *(g["rect"][3] - g["rect"][1] for g in row)):
                row.append(f)
                break
        else:
            rows.append([f])
    rows.sort(key=lambda row: min(g["rect"][1] for g in row))
    return [sorted(row, key=lambda g: g["rect"][0]) for row in rows]


def _reorder_fragments(b: dict) -> dict:
    """Фрагменты строки блока PDF в порядке на странице. Читатель v1 склеивает строку по шрифтам: если кириллица
    набрана одним шрифтом, а точки, запятые и дефисы — другим (подстановка шрифта при сохранении в PDF), знаки
    уходят в конец строки: «документов Текст требований не .» вместо «документов. Текст требований не». Строка
    (одно значение ``line``) пересобирается по рядам и координате x, только если порядок нарушен; между фрагментами —
    один пробел (лишние уберёт ``_tight_text`` по зазору)."""
    text = str(b.get("text") or "")
    raw = (b.get("loc") or {}).get("fragments") or []
    frags = sorted((f for f in (raw if isinstance(raw, list) else [])
                    if isinstance(f, dict) and isinstance(f.get("start"), int) and isinstance(f.get("end"), int)
                    and isinstance(f.get("rect"), (list, tuple)) and len(f["rect"]) == 4), key=lambda f: f["start"])
    if len(frags) < 2:
        return b
    groups: list[list[dict]] = []
    for f in frags:
        if groups and groups[-1][-1].get("line") == f.get("line"):
            groups[-1].append(f)
        else:
            groups.append([f])
    plan: list[tuple[int, int, list[dict]]] = []
    for g in groups:
        if len(g) < 2 or any(text[a["end"]:c["start"]] not in ("", " ") for a, c in zip(g, g[1:])):
            continue
        order = [f for row in _rows(g) for f in row]
        if [id(f) for f in order] != [id(f) for f in g]:
            plan.append((g[0]["start"], g[-1]["end"], order))
    if not plan:
        return b
    out, new_frags, pos, shift = [], [], 0, 0
    replaced = {id(f) for _, _, order in plan for f in order}
    for s, e, order in plan:
        out.append(text[pos:s])
        cur = sum(len(x) for x in out)
        for k, f in enumerate(order):
            piece = text[f["start"]:f["end"]]
            if k:
                out.append(" ")
                cur += 1
            new_frags.append({**f, "start": cur, "end": cur + len(piece)})
            out.append(piece)
            cur += len(piece)
        pos = e
    out.append(text[pos:])
    new_text = "".join(out)
    # фрагменты вне пересобранных строк — со сдвигом по длине вставок до них
    for f in frags:
        if id(f) in replaced:
            continue
        shift = sum(len(" ".join(text[x["start"]:x["end"]] for x in order)) - (e - s)
                    for s, e, order in plan if e <= f["start"])
        new_frags.append({**f, "start": f["start"] + shift, "end": f["end"] + shift})
    loc = {**(b.get("loc") or {}), "fragments": sorted(new_frags, key=lambda f: f["start"])}
    return {**b, "text": new_text, "loc": loc}


def _tight_text(b: dict) -> str:
    """Текст блока PDF без лишних пробелов: читатель ставит пробел между соседними фрагментами строки, даже если
    зазора между ними нет («ВК -1», «приложении .»). Пробел убирается, если зазор < 8 % высоты строки.
    Знаки, которые читатель унёс в конец строки (другой шрифт), возвращаются на место (``_reorder_fragments``)."""
    try:
        b = _reorder_fragments(b)
    except Exception:  # noqa: BLE001 — порядок как у читателя v1
        pass
    text = str(b.get("text") or "")
    frags = sorted((f for f in (b.get("loc") or {}).get("fragments") or []
                    if isinstance(f.get("start"), int) and isinstance(f.get("end"), int) and f.get("rect")),
                   key=lambda f: f["start"])
    cut: list[int] = []
    for f1, f2 in zip(frags, frags[1:]):
        if text[f1["end"]:f2["start"]] != " ":
            continue
        if f1.get("line") == f2.get("line"):
            h = max(f1["rect"][3] - f1["rect"][1], 1.0)
            if f2["rect"][0] - f1["rect"][2] < 0.08 * h:
                cut.append(f1["end"])
        elif _cell_word_break(b, frags, f1, f2, text):
            cut.append(f1["end"])
    if not cut:
        return text
    out, prev = [], 0
    for pos in cut:
        out.append(text[prev:pos])
        prev = pos + 1
    out.append(text[prev:])
    return "".join(out)


_API_EN = {"message", "error", "request", "response", "status", "server", "string", "integer", "boolean", "number",
           "bad", "unauthorized", "forbidden", "found", "conflict", "internal", "gone", "successful", "unsuccessful",
           "created", "result", "true", "false", "null", "parameter", "format", "description", "field", "type",
           "required", "mandatory", "body", "header", "token", "bearer", "json", "get", "post", "put", "delete", "id"}


def _recover_garbled_pages(doc: dict, path: Path) -> list[int]:
    """Страница, которую читатель v1 счёл «нечитаемой» (латиница без английских слов), но PyMuPDF даёт нормальный текст —
    например, страница статусов API: «410. Unsuccessful — Gone», «Internal server error». Строки страницы берутся
    напрямую из PDF и вставляются на её место; предупреждения о нечитаемой странице убираются."""
    ext = doc.get("extraction") or {}
    status = ext.get("pages_status") or {}
    garbled = sorted(int(k) for k, v in status.items() if v == "garbled" and str(k).isdigit())
    if not garbled:
        return []
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return []
    recovered: list[int] = []
    blocks = list(doc.get("blocks") or [])
    with pymupdf.open(str(path)) as pdf:
        for pg in garbled:
            if not 1 <= pg <= pdf.page_count:
                continue
            page = pdf[pg - 1]
            text = page.get_text()
            letters = [c for c in text if not c.isspace()]
            bad = sum(c == "\ufffd" or "\ue000" <= c <= "\uf8ff" for c in letters)
            words = re.findall(r"[A-Za-z]{2,}", text)
            cyr = re.findall(r"[А-Яа-яЁё]{3,}", text)
            api = sum(w.lower() in _API_EN for w in words)
            if not letters or bad > 0.01 * len(letters) or not (cyr or (words and api >= 0.3 * len(words))):
                continue
            new = _page_blocks(page, pg)
            if not new:
                continue
            at = max((i + 1 for i, b in enumerate(blocks) if (_page_of(b) or 0) < pg), default=0)
            sec = list(blocks[at - 1].get("section") or []) if at else []
            for b in new:
                b["section"] = sec + ([b["text"]] if b["kind"] == "heading" else [])
            blocks[at:at] = new
            recovered.append(pg)
    if recovered:
        doc["blocks"] = blocks
        doc["warnings"] = [w for w in doc.get("warnings") or [] if not (
            isinstance(w, dict) and (w.get("page") in recovered or set(w.get("pages") or []) & set(recovered)))]
        ext["pages_unread"] = [x for x in ext.get("pages_unread") or [] if x not in recovered]
        for pg in recovered:
            status[str(pg)] = "text"
    return recovered


def _page_blocks(page, pg: int) -> list[dict]:
    """Строки страницы из PyMuPDF: строка текста — блок; жирная короткая строка — заголовок."""
    out = []
    data = page.get_text("dict")
    sizes = [sp["size"] for bl in data.get("blocks", []) for ln in bl.get("lines", []) for sp in ln.get("spans", [])
             if sp.get("text", "").strip()]
    body = sorted(sizes)[len(sizes) // 2] if sizes else 10
    for bl in data.get("blocks", []):
        for ln in bl.get("lines", []):
            spans = [sp for sp in ln.get("spans", []) if sp.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(sp["text"] for sp in ln["spans"]).strip()
            bold = all("bold" in sp.get("font", "").lower() for sp in spans)
            big = max(sp["size"] for sp in spans) > body * 1.1
            kind = "heading" if (bold or big) and len(text) < 120 and not text.startswith("{") else "paragraph"
            out.append({"id": f"p{pg:02d}l{len(out) + 1:03d}", "kind": kind, "text": text,
                        "loc": {"page": pg, "bbox": list(ln["bbox"]), "level": 4 if kind == "heading" else None}})
    return out


def _list_label(b: dict) -> str:
    """Номер пункта автонумерации DOCX («1.», «2.1.», «а)»), маркеры «•» не ставим."""
    lst = (b.get("loc") or {}).get("list") or {}
    if b.get("kind") != "list_item" or not isinstance(lst, dict) or "num_id" not in lst:
        return ""
    label = str(lst.get("label") or "").strip()
    return label if label and any(ch.isalnum() for ch in label) and len(label) <= 12 else ""


def _page_sizes(path: Path) -> dict[int, tuple[float, float]]:
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return {}
    try:
        with pymupdf.open(str(path)) as d:
            return {i + 1: (pg.rect.width, pg.rect.height) for i, pg in enumerate(d) if pg.rotation == 0}
    except Exception:  # noqa: BLE001
        return {}


def _frags_of(b: dict) -> list[dict]:
    """Фрагменты блока с текстом (по смещениям в тексте блока; знаки, унесённые читателем, уже на месте)."""
    if "_frags" in b:
        return b["_frags"]
    try:
        b = _reorder_fragments(b)
    except Exception:  # noqa: BLE001
        pass
    text = str(b.get("text") or "")
    out = []
    raw = (b.get("loc") or {}).get("fragments") or []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        r = f.get("rect")
        if isinstance(f.get("start"), int) and isinstance(f.get("end"), int) and r and len(r) == 4:
            t = text[f["start"]:f["end"]]
            if t.strip():
                out.append({"rect": [float(x) for x in r], "text": t})
    return out


def _join_frags(frags: list[dict]) -> str:
    """Фрагменты одного ряда слева направо: пробел, если зазор ≥ 8 % высоты (как в ``_tight_text``)."""
    out = ""
    prev = None
    for f in sorted(frags, key=lambda f: f["rect"][0]):
        if prev is not None:
            h = max(prev["rect"][3] - prev["rect"][1], 1.0)
            if f["rect"][0] - prev["rect"][2] >= 0.08 * h:
                out += " "
        out += f["text"].strip()
        prev = f
    return out


_LIST_MARK = re.compile(r"^(?:[•◦▪▫‣●○■□·∙*–—-]|\(?\d{1,3}[.)]|\(?[a-zа-я][.)])$")


def _borderless_tables(blocks: list[dict], sizes: dict) -> tuple[list[dict], list[int]]:
    """Таблица без линеек в PDF: читатель v1 (PyMuPDF без нейросети вёрстки — так у жюри по ``requirements.txt``)
    отдаёт её колонками — «Наименование задачи Продукт Бизнес-процесс», ниже «Месячный порог… Мобильный банк…», и
    связь «поле — значение» теряется. Блоки разных колонок, перекрывающиеся по высоте, собираются в строки таблицы
    по визуальным рядам; продолжение ячейки (ряд без лишнего интервала) приклеивается к своей строке.

    Обычная вёрстка в две колонки (две колонки похожей ширины, строки заполнены почти до края) не трогается — её
    порядок чтения чинит ``_reorder_columns``."""
    orig = blocks
    blocks, parent_of = _split_wide(blocks)
    by_page: dict[int, list[int]] = {}
    for i, b in enumerate(blocks):
        pg = _page_of(b)
        if pg is not None and _bbox(b) and b.get("kind") not in ("table_row", "table_header", "code"):
            by_page.setdefault(pg, []).append(i)
    replace: dict[int, list[dict]] = {}
    drop: set[int] = set()
    pages: list[int] = []
    for pg, idxs in by_page.items():
        # колонки — по левому краю блоков (допуск 6 pt)
        xs: list[float] = []
        col_of: dict[int, int] = {}
        for i in sorted(idxs, key=lambda i: _bbox(blocks[i])[0]):
            x0 = _bbox(blocks[i])[0]
            for k, x in enumerate(xs):
                if abs(x0 - x) <= 6:
                    col_of[i] = k
                    break
            else:
                xs.append(x0)
                col_of[i] = len(xs) - 1
        # связные группы: блоки разных колонок, перекрывающиеся по высоте, и не выходящие за край соседа справа
        parent = {i: i for i in idxs}

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for a in idxs:
            for c in idxs:
                if a >= c or col_of[a] == col_of[c]:
                    continue
                ba, bc = _bbox(blocks[a]), _bbox(blocks[c])
                left, right = (ba, bc) if ba[0] < bc[0] else (bc, ba)
                if left[2] > right[0] + 2:
                    continue  # блоки перекрываются по горизонтали — не колонки
                ov = min(ba[3], bc[3]) - max(ba[1], bc[1])
                if ov > 0.3 * min(ba[3] - ba[1], bc[3] - bc[1]):
                    parent[find(a)] = find(c)
        groups: dict[int, list[int]] = {}
        for i in idxs:
            groups.setdefault(find(i), []).append(i)
        # соседние группы с теми же колонками — одна таблица (строка заголовка «Поле | Значение» отдельно от тела)
        comps: list[list[int]] = []
        for g in sorted(groups.values(), key=lambda g: min(_bbox(blocks[i])[1] for i in g)):
            cols_g = sorted({col_of[i] for i in g})
            if comps and len(cols_g) >= 2 and sorted({col_of[i] for i in comps[-1]}) == cols_g:
                prev_bottom = max(_bbox(blocks[i])[3] for i in comps[-1])
                top = min(_bbox(blocks[i])[1] for i in g)
                h = min(_bbox(blocks[i])[3] - _bbox(blocks[i])[1] for i in g)
                between = [i for i in idxs if i not in g and i not in comps[-1]
                           and prev_bottom - 1 <= _bbox(blocks[i])[1] < top]
                if 0 <= top - prev_bottom <= 2.5 * max(h, 1.0) and not between:
                    comps[-1] = comps[-1] + g
                    continue
            comps.append(list(g))
        pieces: dict[int, set[int]] = {}
        for i, par in parent_of.items():
            pieces.setdefault(par, set()).add(i)
        for comp in comps:
            cols = sorted({col_of[i] for i in comp})
            if len(cols) < 2:
                continue
            if any(not pieces[parent_of[i]] <= set(comp) for i in comp if i in parent_of):
                continue  # блок, разрезанный по колонкам, должен целиком попасть в таблицу
            frags = [dict(f, col=cols.index(col_of[i])) for i in sorted(comp) for f in _frags_of(blocks[i])]
            if len(frags) < 4 or len({f["col"] for f in frags}) < len(cols):
                continue  # мало текста или у колонки нет координат слов — оставляем как прочитал v1
            rows = _rows(frags)
            aligned = sum(1 for r in rows if len({f["col"] for f in r}) >= 2)
            if aligned < 2 or aligned < 0.4 * len(rows):
                continue
            # колонка из одних маркеров списка («•», «1.», «а)») — это список: пункт на каждый маркер
            is_list = len(cols) == 2 and all(_LIST_MARK.match(f["text"].strip()) for f in frags if f["col"] == 0)
            # ячейки одной строки таблицы стоят на одной базовой линии (±1 pt); в вёрстке в две колонки ряды
            # колонок совпадают по высоте лишь местами (заголовки, интервалы абзацев сдвигают их)
            strict = aligned if is_list else 0
            for r in rows if not is_list else []:
                meds = []
                for c in {f["col"] for f in r}:
                    ys = sorted(f["rect"][3] for f in r if f["col"] == c and any(ch.isalnum() for ch in f["text"]))
                    if ys:
                        meds.append(ys[len(ys) // 2])
                strict += len(meds) >= 2 and max(meds) - min(meds) <= 1.0
            if strict < 0.8 * aligned:
                continue

            # вёрстка в две колонки: две колонки похожей ширины, строки заполнены почти до края колонки
            spans = []
            for k in range(len(cols)):
                fs = [f for f in frags if f["col"] == k]
                spans.append((min(f["rect"][0] for f in fs), max(f["rect"][2] for f in fs)))
            if len(cols) == 2 and not is_list:
                w0, w1 = spans[0][1] - spans[0][0], spans[1][1] - spans[1][0]
                fill = []
                for r in rows:
                    lf = [f for f in r if f["col"] == 0]
                    if lf:
                        fill.append((max(f["rect"][2] for f in lf) - spans[0][0]) / max(w0, 1.0))
                fill.sort()
                if 0.75 <= w0 / max(w1, 1.0) <= 1.33 and fill and fill[len(fill) // 2] >= 0.8:
                    continue
            # строки таблицы: перенос текста внутри ячейки идёт с межстрочным интервалом, новая строка таблицы — с
            # интервалом больше (поля ячейки); ряд меряется по медиане нижнего края букв — знаки другим шрифтом
            # сдвинуты на 1–2 pt. Если двух уровней интервала нет — перенос только у ряда с пустой первой колонкой
            def _base(r: list[dict]) -> float:
                ys = sorted(f["rect"][3] for f in r if any(ch.isalnum() for ch in f["text"])) or \
                    sorted(f["rect"][3] for f in r)
                return ys[len(ys) // 2]
            bases = [_base(r) for r in rows]
            gaps = [b - a for a, b in zip(bases, bases[1:])]
            cut = 0.0
            sg = sorted(gaps)
            if len(sg) >= 2 and sg[-1] > 1.12 * max(sg[0], 1.0):
                jump, at = max((b - a, k) for k, (a, b) in enumerate(zip(sg, sg[1:])))
                if jump >= 1.5:
                    cut = (sg[at] + sg[at + 1]) / 2
            table: list[list[list[dict]]] = []
            for k, r in enumerate(rows):
                cells = [[f for f in r if f["col"] == c] for c in range(len(cols))]
                if table and (not cells[0] or (cut and gaps[k - 1] < cut)):
                    for c in range(len(cols)):
                        table[-1][c].extend(cells[c])
                else:
                    table.append(cells)
            first = blocks[min(comp, key=lambda i: (_bbox(blocks[i])[1], _bbox(blocks[i])[0]))]
            new = []
            for k, cells in enumerate(table):
                texts = []
                for cell in cells:
                    lines = _rows(cell) if cell else []
                    texts.append(" ".join(_join_frags(ln) for ln in lines))
                all_f = [f for cell in cells for f in cell]
                bb = [min(f["rect"][0] for f in all_f), min(f["rect"][1] for f in all_f),
                      max(f["rect"][2] for f in all_f), max(f["rect"][3] for f in all_f)]
                if is_list:  # «•» не нужен, номер пункта («1.», «а)») остаётся
                    mark = texts[0].split()[0] if texts[0].split() else ""
                    text = texts[1] if _BULLET_GLYPH.match(mark + " ") or not mark else f"{mark} {texts[1]}"
                    new.append({"id": f"{first.get('id', 'b')}-l{k + 1}", "kind": "list_item",
                                "section": first.get("section"), "text": text, "loc": {"page": pg, "bbox": bb}})
                    continue
                new.append({"id": f"{first.get('id', 'b')}-t{k + 1}", "kind": "table_row",
                            "section": first.get("section"), "text": " | ".join(texts),
                            "loc": {"page": pg, "bbox": bb}})
            order = sorted(comp)
            replace[order[0]] = new
            drop.update(order[1:])
            if not is_list:
                pages.append(pg)
    if not replace:
        return orig, []
    consumed = set(replace) | drop
    out: list[dict] = []
    done_parents: set[int] = set()
    for i, b in enumerate(blocks):
        if i in replace:
            out.extend(replace[i])
        elif i in drop:
            continue
        elif i in parent_of:  # кусок блока, не ставший таблицей, — исходный блок целиком (один раз)
            par = parent_of[i]
            if par not in done_parents and not any(j in consumed for j, q in parent_of.items() if q == par):
                out.append(orig[par])
            done_parents.add(par)
        else:
            out.append(b)
    return out, sorted(set(pages))


def _split_wide(blocks: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """Блок, который читатель v1 склеил поперёк колонок таблицы без линеек («Расходы 48 500 ₸, порог Провести
    покупку на 1 Итог 50 000 ₸…»): в ряду текста между фрагментами зазор больше 0,75 высоты строки. Такой блок
    режется на куски по колонкам (левый край куска), у куска — свои фрагменты. Возвращает новый список и
    ``{индекс куска: индекс исходного блока}``."""
    out: list[dict] = []
    parent_of: dict[int, int] = {}
    for i, b in enumerate(blocks):
        if b.get("kind") in ("table_row", "table_header", "code", "heading") or not _bbox(b):
            out.append(b)
            continue
        frags = _frags_of(b)
        rows = _rows(frags) if len(frags) >= 2 else []
        segs: list[list[dict]] = []
        wide = False
        for r in rows:
            h = sorted(f["rect"][3] - f["rect"][1] for f in r)[len(r) // 2]
            cur = [r[0]]
            for f in r[1:]:
                if f["rect"][0] - cur[-1]["rect"][2] > 0.75 * max(h, 1.0):
                    segs.append(cur)
                    cur = [f]
                    wide = True
                else:
                    cur.append(f)
            segs.append(cur)
        if not wide:
            out.append(b)
            continue
        xs: list[float] = []
        col_segs: dict[int, list[dict]] = {}
        for seg in sorted(segs, key=lambda sg: sg[0]["rect"][0]):
            x0 = seg[0]["rect"][0]
            k = next((j for j, x in enumerate(xs) if abs(x0 - x) <= 8), None)
            if k is None:
                xs.append(x0)
                k = len(xs) - 1
            col_segs.setdefault(k, []).extend(seg)
        if len(col_segs) < 2:
            out.append(b)
            continue
        for k in sorted(col_segs):
            fs = col_segs[k]
            bb = [min(f["rect"][0] for f in fs), min(f["rect"][1] for f in fs),
                  max(f["rect"][2] for f in fs), max(f["rect"][3] for f in fs)]
            parent_of[len(out)] = i
            out.append({"id": f"{b.get('id', 'b')}-c{k + 1}", "kind": "paragraph", "section": b.get("section"),
                        "text": " ".join(f["text"] for f in fs), "_frags": fs,
                        "loc": {"page": (b.get("loc") or {}).get("page"), "bbox": bb}})
    return out, parent_of


def _bbox(b: dict) -> list[float] | None:
    bb = (b.get("loc") or {}).get("bbox")
    if isinstance(bb, (list, tuple)) and len(bb) == 4 and all(isinstance(x, (int, float)) for x in bb):
        return [float(x) for x in bb]
    return None


def _page_of(b: dict) -> int | None:
    pg = (b.get("loc") or {}).get("page")
    return int(pg) if isinstance(pg, int) else None


def _pages_list(pages: list[int]) -> str:
    pages = sorted(set(pages))
    if len(pages) > 2 and pages[-1] - pages[0] == len(pages) - 1:
        return f"{pages[0]}–{pages[-1]}"
    return ", ".join(str(p) for p in pages)


def _reorder_columns(blocks: list[dict], sizes: dict) -> tuple[list[dict], list[int]]:
    """Страница в две колонки: блоки во всю ширину делят страницу на полосы; в полосе — левая колонка сверху вниз,
    затем правая. Страницы в одну колонку не трогаются."""
    by_page: dict[int, list[int]] = {}
    for i, b in enumerate(blocks):
        pg = _page_of(b)
        if pg is not None and _bbox(b) and pg in sizes:
            by_page.setdefault(pg, []).append(i)
    order = list(range(len(blocks)))
    two_col: list[int] = []
    for pg, idxs in by_page.items():
        w = sizes[pg][0]
        left = [i for i in idxs if _bbox(blocks[i])[2] <= w * 0.55]
        right = [i for i in idxs if _bbox(blocks[i])[0] >= w * 0.45]
        if len(left) < 3 or len(right) < 3:
            continue
        if max(_bbox(blocks[i])[2] for i in left) > min(_bbox(blocks[i])[0] for i in right) + 2:
            continue  # колонки перекрываются — это не вёрстка в две колонки
        if any(blocks[i].get("kind") in ("table_row", "table_header") for i in left + right):
            continue
        full = sorted((i for i in idxs if i not in left and i not in right), key=lambda i: _bbox(blocks[i])[1])
        new: list[int] = []
        top = -1e9
        for cut in [*full, None]:
            bottom = _bbox(blocks[cut])[1] if cut is not None else 1e9
            band_l = sorted((i for i in left if top <= _bbox(blocks[i])[1] < bottom), key=lambda i: _bbox(blocks[i])[1])
            band_r = sorted((i for i in right if top <= _bbox(blocks[i])[1] < bottom), key=lambda i: _bbox(blocks[i])[1])
            new += band_l + band_r
            if cut is not None:
                new.append(cut)
                top = _bbox(blocks[cut])[3]
        if sorted(new) != sorted(idxs) or new == idxs:
            continue
        positions = sorted(order.index(i) for i in idxs)
        for pos, i in zip(positions, new):
            order[pos] = i
        two_col.append(pg)
    return [blocks[i] for i in order], sorted(two_col)


def _split_merged_headings(blocks: list[dict], sizes: dict) -> list[dict]:
    """Два заголовка подряд, которые читатель PDF склеил в один блок («Требования к изменениям BPMN схема процесса»):
    строки блока разной высоты (разный кегль) или первая строка короткая — делим на два заголовка и чиним разделы."""
    out: list[dict] = []
    fixes: list[tuple[str, str, str, int]] = []  # (склеенный текст, первый, второй, уровень второго)
    for b in blocks:
        frags = (b.get("loc") or {}).get("fragments") or []
        text = str(b.get("text") or "")
        lines_idx = sorted({f.get("line") for f in frags if isinstance(f.get("line"), int)})
        if b.get("kind") != "heading" or len(lines_idx) != 2 or _page_of(b) not in sizes:
            out.append(b)
            continue
        l0 = [f for f in frags if f.get("line") == lines_idx[0]]
        l1 = [f for f in frags if f.get("line") == lines_idx[1]]
        h0 = max(f["rect"][3] - f["rect"][1] for f in l0)
        h1 = max(f["rect"][3] - f["rect"][1] for f in l1)
        right0 = max(f["rect"][2] for f in l0)
        width = sizes[_page_of(b)][0]
        cut = max(f["end"] for f in l0)
        first, second = text[:cut].strip(), text[cut:].strip()
        # только разный кегль строк: короткая первая строка бывает и у обычного переноса заголовка в узкой колонке
        if not first or not second or abs(h0 - h1) <= 0.4:
            out.append(b)
            continue
        lvl = _level(b)
        lvl2 = lvl + 1 if h1 < h0 - 0.4 else lvl
        b1, b2 = dict(b), dict(b)
        b1["text"], b2["text"] = first, second
        b2["id"] = f"{b.get('id', '')}s"
        b2["loc"] = {**(b.get("loc") or {}), "level": lvl2, "heading_level": lvl2}
        parent = [x for x in (b.get("section") or []) if x != text]
        b1["section"] = parent + [first]
        b2["section"] = parent + ([first] if lvl2 > lvl else []) + [second]
        out += [b1, b2]
        fixes.append((text, first, second, lvl2))
    for merged, first, second, lvl2 in fixes:
        inside = False
        for b in out:
            if b.get("kind") == "heading" and b.get("text") in (first, second) and merged not in (b.get("section") or []):
                inside = inside or b.get("text") == second
                continue
            sec = list(b.get("section") or [])
            if merged not in sec:
                continue
            if inside and b.get("kind") == "heading" and _level(b) <= lvl2:
                inside = False
            i = sec.index(merged)
            b["section"] = sec[:i] + ([first, second] if inside else [first]) + sec[i + 1:]
    return out


def _cells(text: str) -> list[str]:
    return [c.strip() for c in re.split(r" \| ", " " + text + " ")]


def _glue_split_rows(blocks: list[dict]) -> tuple[list[dict], int]:
    """Строка таблицы, которую перенос страницы разорвал на две: последняя строка таблицы на странице и первая
    строка следующей страницы с тем же числом ячеек, часть из которых пуста, склеиваются по ячейкам."""
    out: list[dict] = []
    glued = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        nb = blocks[i + 1] if i + 1 < len(blocks) else None
        if (nb is not None and b.get("kind") in ("table_row", "table_header") and nb.get("kind") == "table_row"
                and _page_of(b) is not None and _page_of(nb) == _page_of(b) + 1):
            a, c = _cells(str(b.get("text") or "")), _cells(str(nb.get("text") or ""))
            first_on_page = not any(_page_of(x) == _page_of(nb) for x in out)
            filled = [k for k, x in enumerate(c) if x]
            if (len(a) == len(c) > 1 and filled and len(filled) * 2 <= len(c) and all(a[k] for k in filled)
                    and first_on_page):
                merged = dict(b)
                merged["text"] = " | ".join(" ".join(p for p in (x, y) if p) for x, y in zip(a, c))
                out.append(merged)
                glued += 1
                i += 2
                continue
        out.append(b)
        i += 1
    return out, glued


def _running_key(text: str) -> str:
    t = re.sub(r"\d+", "#", text.casefold())
    return re.sub(r"\s+", " ", t).strip()


_PAGE_NO = re.compile(r"^\s*(?:стр(?:аница)?\.?\s*|page\s*|[-–—]\s*)?\d{1,4}"
                      r"(?:\s*(?:из|/|of)\s*\d{1,4})?\s*[-–—]?\s*$", re.IGNORECASE)


def _drop_running(blocks: list[dict], sizes: dict) -> tuple[list[dict], list[str]]:
    """Убрать колонтитулы: блок в верхних или нижних 9 % страницы, текст которого (без цифр) повторяется на
    большинстве страниц, или одиночный номер страницы. Строки таблиц не трогаются."""
    pages = sorted({p for p in (_page_of(b) for b in blocks) if p is not None})
    if len(pages) < 2:
        return blocks, []
    edge: dict[int, str] = {}
    for i, b in enumerate(blocks):
        pg, bb = _page_of(b), _bbox(b)
        if pg not in sizes or not bb or b.get("kind") in ("table_row", "table_header"):
            continue
        h = sizes[pg][1]
        if bb[3] <= h * 0.09 or bb[1] >= h * 0.91:
            edge[i] = _running_key(str(b.get("text") or ""))
    seen: dict[str, set[int]] = {}
    for i, key in edge.items():
        if key:
            seen.setdefault(key, set()).add(_page_of(blocks[i]))
    need = max(2, (len(pages) + 1) // 2)
    drop = {i for i, key in edge.items()
            if key and (len(seen[key]) >= need or _PAGE_NO.match(str(blocks[i].get("text") or "")))}
    if not drop:
        return blocks, []
    texts = []
    for i in sorted(drop):
        t = " ".join(str(blocks[i].get("text") or "").split())
        if t not in texts:
            texts.append(t)
    return [b for i, b in enumerate(blocks) if i not in drop], texts


# --------------------------------------------------------------------------- общее
def _level(b: dict) -> int:
    if b.get("kind") != "heading":
        return 0
    loc = b.get("loc") or {}
    for key in ("level", "heading_level"):
        v = loc.get(key)
        if isinstance(v, int) and v > 0:
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 1


def _section(b: dict) -> str:
    sec = [str(s).strip() for s in (b.get("section") or []) if str(s).strip()]
    if b.get("kind") == "heading":
        head = _clean(str(b.get("text") or "")).strip()
        if head and (not sec or sec[-1] != head):
            sec.append(head)
    return SECTION_SEP.join(sec)


def _strip_title_from_sections(lines: list[dict], title: str) -> None:
    """Заголовок документа (корень дерева) в разделе не повторяем: «Часть A › Цели», а не «Документ › Часть A › Цели»."""
    if not title:
        return
    pref = title + SECTION_SEP
    for ln in lines:
        s = ln["section"]
        if s == title:
            ln["section"] = ""
        elif s.startswith(pref):
            ln["section"] = s[len(pref):]


def _title(doc: dict | None, lines: list[dict], path: Path) -> str:
    blocks = (doc or {}).get("blocks") or []
    for b in blocks:
        if b.get("kind") == "heading":
            level = (b.get("loc") or {}).get("level") or (b.get("loc") or {}).get("heading_level")
            if level in (1, "1", None) and str(b.get("text") or "").strip():
                return _clean(str(b["text"])).strip()
            break
    t = str((doc or {}).get("title") or "").strip()
    if t and t != path.stem:
        return t
    first = next((ln["text"].strip() for ln in lines if ln["text"].strip()), "")
    return first[:120] if first else path.stem


def _clean(t: str) -> str:
    t = t.replace("\t", " ").replace("\r", "")
    t = re.sub("[\u00ad\u200b\u200c\u200d\u2060\ufeff]", "", t)
    if t.strip() and not t.strip(" |"):
        return ""  # строка таблицы из пустых ячеек
    return t.rstrip()


def _doc_warnings(doc: dict | None) -> list[str]:
    if not doc:
        return []
    out: list[str] = []
    for w in doc.get("warnings") or []:
        if isinstance(w, str):
            out.append(w)
            continue
        if not isinstance(w, dict):
            continue
        msg = str(w.get("message") or w.get("code") or "").strip()
        if not msg:
            continue
        page = w.get("page")
        if page and f"{page}" not in msg:
            msg = f"{msg} (с. {page})"
        if w.get("code") in _PAGE_WARN_CODES or w.get("severity") in ("warning", "error") or "code" not in w:
            out.append(msg)
    ext = doc.get("extraction") or {}
    unread = ext.get("pages_unread") or []
    said = " ".join(out).casefold()
    if unread and "не прочитаны страниц" not in said and "нет текстового слоя" not in said:
        out.append("Не прочитаны страницы: " + ", ".join(str(p) for p in unread) + " (скан или нечитаемый шрифт).")
    ocr = ext.get("pages_ocr") or []
    if ocr and "ocr" not in said:
        out.append("Страницы распознаны OCR, возможны ошибки текста: " + ", ".join(str(p) for p in ocr) + ".")
    return out


def _dedup(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def summary(view: dict) -> dict[str, Any]:
    """Паспорт документа для report.json: {title, file, format, sha256, lines, pages}."""
    return {"title": view.get("title", ""), "file": view.get("file", ""), "format": view.get("format", ""),
            "sha256": view.get("sha256", ""), "lines": len(view.get("lines") or []), "pages": view.get("pages")}


def main(argv: list[str] | None = None) -> int:
    """``python -m bcc_review.v2.docview ФАЙЛ [--from N] [--to M] [--json]`` — показать нумерованный вид."""
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.docview", description="Документ с номерами строк")
    ap.add_argument("file")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="DocView целиком в JSON")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    view = load(a.file)
    if a.json:
        print(json.dumps(view, ensure_ascii=False, indent=1))
        return 0
    s = summary(view)
    print(f"# {s['title']} · {s['file']} · {s['format']} · строк {s['lines']}"
          + (f" · страниц {s['pages']}" if s["pages"] else "") + f" · sha256 {s['sha256'][:12]}")
    for w in view["warnings"]:
        print(f"# предупреждение: {w}")
    print(numbered(view, a.start, a.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
