"""Документ с номерами строк — основа доказательности v2 (владелец №03).

``load(path)`` читает файл читателями v1 (``bcc_review.engine.read_document``: MD/TXT/PDF/DOCX) или
``readers_html`` (HTML) и превращает его в ``DocView`` (CONTRACT.md, раздел 2.1):

* MD/TXT — одна строка view = одна строка исходного файла (номера совпадают с GitHub). Текст — видимый,
  без разметки: без ``**``, обратных кавычек, маркеров списка ``* ``/``- ``, решёток заголовков; ячейки
  таблицы через « | »; строка-разделитель таблицы, ограждения блока кода и ``---`` — пустые строки.
  Пустые строки сохраняются для нумерации.
* PDF/DOCX/HTML — по строке на блок читателя (абзац, пункт, строка таблицы, заголовок); многострочный
  блок даёт несколько строк. Для PDF у каждой строки есть страница.

``numbered(view)`` — текст для модели: «L038| …», для PDF «L045| [с.3] …».
Номер строки, страницу и раздел считает код, а не модель.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

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
def load(path: str | Path) -> dict:
    """Прочитать файл и вернуть DocView. Неподдерживаемый формат — ``ValueError``."""
    p = Path(path)
    fmt = FORMATS.get(p.suffix.lower())
    if fmt is None:
        raise ValueError(f"формат {p.suffix or '(без расширения)'} не поддерживается: "
                         f"{', '.join(sorted(set(FORMATS)))}")
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
        text = data.decode("utf-8-sig", errors="replace")
        lines = _text_lines(text, doc)
    else:
        lines = _block_lines(doc or {})
    title = _title(doc, lines, p)
    _strip_title_from_sections(lines, title)
    pages = None
    if fmt == "pdf":
        ext = (doc or {}).get("extraction") or {}
        pages = ext.get("pages") or max((ln["page"] or 0 for ln in lines), default=0) or None
    warnings += _doc_warnings(doc)
    if not any(ln["text"].strip() for ln in lines):
        warnings.append("В документе нет текста: проверять нечего.")
    return {"title": title, "file": p.name, "format": fmt, "sha256": sha, "lines": lines,
            "pages": pages, "warnings": _dedup(warnings)}


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
        out.append({"n": k, "text": t, "page": None, "section": sections[k] or cur_section,
                    "src_line": k, "block_id": block_ids[k]})
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
def _block_lines(doc: dict) -> list[dict]:
    """По строке на блок читателя; многострочный блок — несколько строк с одним block_id."""
    out: list[dict] = []
    for b in doc.get("blocks") or []:
        loc = b.get("loc") or {}
        page = loc.get("page")
        page = int(page) if isinstance(page, int) or (isinstance(page, str) and page.isdigit()) else None
        sec = _section(b)
        parts = str(b.get("text") or "").splitlines() or [""]
        for i, part in enumerate(parts):
            t = part
            if b.get("kind") == "list_item" and i == 0:
                t = _BULLET_GLYPH.sub("", t.lstrip())
            out.append({"n": len(out) + 1, "text": _clean(t), "page": page, "section": sec,
                        "src_line": None, "block_id": b.get("id", "")})
    return out


# --------------------------------------------------------------------------- общее
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
    if unread:
        out.append("Не прочитаны страницы: " + ", ".join(str(p) for p in unread) + " (скан или нечитаемый шрифт).")
    ocr = ext.get("pages_ocr") or []
    if ocr:
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
