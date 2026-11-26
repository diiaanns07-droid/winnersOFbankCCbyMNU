"""Рендер Markdown-кейса в PDF и DOCX и проверка, что текст реально попал в файл.

PDF и DOCX одного case_id проверяют парсер и экспорт продукта. Это не новые независимые
кейсы для семантического алгоритма: в манифесте у них общий case_id и разные render_id.

Проверка после рендера: текст извлекается обратно (pdfplumber, python-docx), и для
каждой опоры эталона считается:
  tokens_present — все токены опоры есть в извлечённом тексте (текст не потерян);
  exact_sequence — токены идут подряд (порядок не нарушен; таблицы PDF его часто ломают).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

from evaluation.harness.normalize import tokens

FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/Library/Fonts",
             str(Path.home() / "Library/Fonts"), "C:/Windows/Fonts")
FIXED_TIME = datetime(2026, 11, 1, 0, 0, 0)
_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


# ------------------------------------------------------------------ разбор Markdown
def md_blocks(text: str) -> list[tuple]:
    blocks: list[tuple] = []
    lines = text.split("\n")
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            j = i + 1
            code = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                code.append(lines[j])
                j += 1
            blocks.append(("code", "\n".join(code)))
            i = j + 1
            continue
        if not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            blocks.append(("h", level, s[level:].strip()))
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        elif re.match(r"^[*\-] ", s):
            flush()
            blocks.append(("li", s[2:].strip()))
        elif re.match(r"^\d+\. ", s):
            flush()
            blocks.append(("ol", s))
        else:
            para.append(s)
        i += 1
    flush()
    return blocks


def inline_runs(text: str) -> list[tuple[str, str]]:
    """[(стиль, текст)], стиль: plain | bold | code."""
    out = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(("bold", part[2:-2]))
        elif part.startswith("`") and part.endswith("`"):
            out.append(("code", part[1:-1]))
        else:
            out.append(("plain", part))
    return out


# ------------------------------------------------------------------------------ PDF
def _find_font(name: str) -> str:
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"шрифт {name} не найден; установите DejaVu (fonts-dejavu)")


def _register_fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "DejaVu" in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont("DejaVu", _find_font("DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", _find_font("DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuMono", _find_font("DejaVuSansMono.ttf")))


def _rl(text: str) -> str:
    from xml.sax.saxutils import escape
    parts = []
    for style, t in inline_runs(text):
        t = escape(t)
        parts.append(f"<b>{t}</b>" if style == "bold" else f'<font face="DejaVuMono">{t}</font>' if style == "code" else t)
    return "".join(parts)


def to_pdf(text: str, path: Path, title: str) -> None:
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

    rl_config.invariant = 1
    _register_fonts()
    base = ParagraphStyle("b", fontName="DejaVu", fontSize=9.5, leading=12.5)
    styles = {1: ParagraphStyle("h1", parent=base, fontName="DejaVu-Bold", fontSize=15, leading=19, spaceAfter=6),
              2: ParagraphStyle("h2", parent=base, fontName="DejaVu-Bold", fontSize=12.5, leading=16, spaceBefore=6),
              3: ParagraphStyle("h3", parent=base, fontName="DejaVu-Bold", fontSize=11, leading=14, spaceBefore=4),
              4: ParagraphStyle("h4", parent=base, fontName="DejaVu-Bold", fontSize=10, leading=13)}
    cell = ParagraphStyle("c", parent=base, fontSize=8.5, leading=10.5)
    width = A4[0] - 36 * mm
    story = []
    for b in md_blocks(text):
        if b[0] == "h":
            story.append(Paragraph(_rl(b[2]), styles.get(b[1], styles[4])))
        elif b[0] == "p":
            story.append(Paragraph(_rl(b[1]), base))
            story.append(Spacer(1, 3))
        elif b[0] == "li":
            story.append(Paragraph("• " + _rl(b[1]), ParagraphStyle("li", parent=base, leftIndent=10)))
        elif b[0] == "ol":
            story.append(Paragraph(_rl(b[1]), ParagraphStyle("ol", parent=base, leftIndent=10)))
        elif b[0] == "code":
            story.append(Preformatted(b[1], ParagraphStyle("pre", parent=base, fontName="DejaVuMono", fontSize=8)))
        elif b[0] == "table":
            rows = b[1]
            ncol = max(len(r) for r in rows)
            lens = [max(len(r[j]) if j < len(r) else 0 for r in rows) + 4 for j in range(ncol)]
            lens = [min(max(x, 8), 60) for x in lens]
            widths = [width * x / sum(lens) for x in lens]
            data = [[Paragraph(_rl(r[j]) if j < len(r) else "", cell) for j in range(ncol)] for r in rows]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)]))
            story.append(t)
            story.append(Spacer(1, 4))
    if not story:
        story.append(Spacer(1, 1))  # пустой документ: одна пустая страница
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="bcc-eval generator",
                            creator="bcc-eval", producer="bcc-eval", invariant=1)
    doc.build(story)


# ----------------------------------------------------------------------------- DOCX
def _docx_runs(par, text: str) -> None:
    for style, t in inline_runs(text):
        run = par.add_run(t)
        if style == "bold":
            run.bold = True
        elif style == "code":
            run.font.name = "Consolas"


def to_docx(text: str, path: Path, title: str) -> None:
    import docx

    d = docx.Document()
    cp = d.core_properties
    cp.title, cp.author, cp.last_modified_by = title, "bcc-eval generator", "bcc-eval generator"
    cp.created = cp.modified = FIXED_TIME
    cp.revision = 1
    for b in md_blocks(text):
        if b[0] == "h":
            _docx_runs(d.add_heading(level=min(b[1], 4)), b[2])
        elif b[0] == "p":
            _docx_runs(d.add_paragraph(), b[1])
        elif b[0] == "li":
            _docx_runs(d.add_paragraph(style="List Bullet"), b[1])
        elif b[0] == "ol":
            _docx_runs(d.add_paragraph(), b[1])
        elif b[0] == "code":
            _docx_runs(d.add_paragraph(), "`" + b[1] + "`")
        elif b[0] == "table":
            rows = b[1]
            ncol = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=ncol)
            t.style = "Table Grid"
            for i, r in enumerate(rows):
                for j in range(ncol):
                    c = t.cell(i, j)
                    c.text = ""
                    _docx_runs(c.paragraphs[0], r[j] if j < len(r) else "")
    buf = io.BytesIO()
    d.save(buf)
    # детерминированный ZIP: фиксированные время и порядок записей
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 11, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            out.writestr(zi, src.read(info.filename))


def render(text: str, fmt: str, path: Path, title: str) -> None:
    if fmt == "pdf":
        to_pdf(text, path, title)
    elif fmt == "docx":
        to_docx(text, path, title)
    else:
        raise ValueError(f"формат {fmt} не поддерживается генератором")


# ------------------------------------------------------------------------ извлечение
def extract(path: Path, fmt: str) -> str:
    if fmt == "pdf":
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if fmt == "docx":
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        d = docx.Document(str(path))
        out = []
        for el in d.element.body.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                out.append(Paragraph(el, d).text)
            elif tag == "tbl":
                for row in Table(el, d).rows:
                    out.append(" | ".join(c.text for c in row.cells))
        return "\n".join(out)
    return path.read_text(encoding="utf-8")


def check_text(extracted: str, quotes: list[str], source_md: str) -> dict:
    toks = tokens(extracted)
    tok_set = set(toks)
    joined = " " + " ".join(toks) + " "
    src = tokens(source_md)
    src_set = set(src)
    present = seq = 0
    missing = []
    for q in quotes:
        qt = tokens(q)
        if qt and all(t in tok_set for t in qt):
            present += 1
        else:
            missing.append(q)
        if qt and (" " + " ".join(qt) + " ") in joined:
            seq += 1
    coverage = (sum(1 for t in src_set if t in tok_set) / len(src_set)) if src_set else None
    return {"anchors_total": len(quotes), "tokens_present": present, "exact_sequence": seq,
            "missing_anchor_quotes": missing,
            "source_token_coverage": None if coverage is None else round(coverage, 4),
            "ok": present == len(quotes) and (coverage is None or coverage >= 0.98)}


def tool_versions() -> dict:
    out = {}
    for mod, name in (("reportlab", "reportlab"), ("docx", "python-docx"), ("pdfplumber", "pdfplumber")):
        try:
            m = __import__(mod)
            out[name] = getattr(m, "Version", None) or getattr(m, "__version__", None)
        except ImportError:
            out[name] = None
    return out
