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
    try:
        from bcc_review.engine import read_document
        doc = read_document(p)
    except Exception as exc:  # noqa: BLE001 — читатель v1 не должен ронять v2 на MD/TXT
        if fmt in ("pdf", "docx"):
            raise
        warnings.append(f"Читатель разметки не сработал ({type(exc).__name__}: {exc}); "
                        "строки взяты из файла как есть.")
    if fmt in ("md", "txt"):
        lines = _text_lines(_decode_text(data), doc)
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
    if not any(ln["text"].strip() for ln in lines) and not warnings:
        warnings.append("В документе нет текста: проверять нечего.")
    return {"title": title, "file": p.name, "format": fmt, "sha256": sha, "lines": lines,
            "pages": pages, "warnings": _dedup(warnings)}


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
    """Человекочитаемое место: «строки 38–40», для PDF «с. 2, строка 25»."""
    end = start if end is None else end
    rng = f"строка {start}" if end == start else f"строки {start}–{end}"
    p1, p2 = page_of(view, start), page_of(view, end)
    if p1:
        pg = f"с. {p1}" if not p2 or p2 == p1 else f"с. {p1}–{p2}"
        return f"{pg}, {rng}"
    return rng


def nonempty(view: dict) -> list[dict]:
    return [ln for ln in view.get("lines") or [] if ln["text"].strip()]


# --------------------------------------------------------------------------- MD / TXT
def _text_lines(text: str, doc: dict | None) -> list[dict]:
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
        t = _clean(t)
        if sections[k]:
            cur_section = sections[k]
        kind = kinds[k] if t else ""
        if not doc and t:
            kind = "heading" if _MD_HEADING.match(src) else ("table_row" if " | " in t else "paragraph")
        out.append({"n": k, "text": t, "page": None, "section": sections[k] or cur_section,
                    "src_line": k, "block_id": block_ids[k], "kind": kind,
                    "level": levels[k] if kind == "heading" else 0, "heading": kind == "heading"})
    return out


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


def _tight_text(b: dict) -> str:
    """Текст блока PDF без лишних пробелов: читатель ставит пробел между соседними фрагментами строки, даже если
    зазора между ними нет («ВК -1», «приложении .»). Пробел убирается, если зазор < 8 % высоты строки."""
    text = str(b.get("text") or "")
    frags = sorted((f for f in (b.get("loc") or {}).get("fragments") or []
                    if isinstance(f.get("start"), int) and isinstance(f.get("end"), int) and f.get("rect")),
                   key=lambda f: f["start"])
    cut: list[int] = []
    for f1, f2 in zip(frags, frags[1:]):
        if f1.get("line") != f2.get("line") or text[f1["end"]:f2["start"]] != " ":
            continue
        h = max(f1["rect"][3] - f1["rect"][1], 1.0)
        if f2["rect"][0] - f1["rect"][2] < 0.08 * h:
            cut.append(f1["end"])
    if not cut:
        return text
    out, prev = [], 0
    for pos in cut:
        out.append(text[prev:pos])
        prev = pos + 1
    out.append(text[prev:])
    return "".join(out)


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
        if not first or not second or not (abs(h0 - h1) > 0.4 or right0 < width * 0.45):
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
