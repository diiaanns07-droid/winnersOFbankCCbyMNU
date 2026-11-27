"""DOCX официального документа из Markdown — для паритета форматов (№03, вторая волна).

    python tests/v2/fixtures/03_stress/make_official_docx.py [вход.md] [выход.docx]
    # по умолчанию release/input/requirements.md → release/input/requirements.docx

Перенос как у аналитика в Word: заголовки — стили Heading 1–4, таблицы — «Table Grid» с жирной шапкой,
маркированные пункты — «List Bullet», нумерованные — автонумерация Word («List Number», каждый список с 1),
**жирный** и `код` — форматирование run, блоки кода — абзацы моноширинным шрифтом, «---» — пропуск.
Текст не меняется: каждая непустая строка Markdown-вида (docview) есть в DOCX-виде.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def _runs(par, text: str, bold_all: bool = False) -> None:
    from docx.shared import Pt
    for chunk in INLINE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            r = par.add_run(chunk[2:-2])
            r.bold = True
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            r = par.add_run(chunk[1:-1])
            r.font.name = "Consolas"
            r.font.size = Pt(10)
            r.bold = bold_all or None
        else:
            r = par.add_run(chunk)
            r.bold = bold_all or None


def _restart_numbering(doc, par) -> None:
    """Новый список с 1: свой w:num на тот же abstractNum со startOverride."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    numbering = doc.part.numbering_part.numbering_definitions._numbering
    style_num = doc.styles["List Number"].element.pPr.numPr.numId.val
    abstract = None
    for num in numbering.findall(qn("w:num")):
        if num.get(qn("w:numId")) == str(style_num):
            abstract = num.find(qn("w:abstractNumId")).get(qn("w:val"))
    ids = [int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))]
    new_id = max(ids) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(new_id))
    an = OxmlElement("w:abstractNumId")
    an.set(qn("w:val"), str(abstract))
    num.append(an)
    ov = OxmlElement("w:lvlOverride")
    ov.set(qn("w:ilvl"), "0")
    so = OxmlElement("w:startOverride")
    so.set(qn("w:val"), "1")
    ov.append(so)
    num.append(ov)
    numbering.append(num)
    ppr = par._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    il = OxmlElement("w:ilvl")
    il.set(qn("w:val"), "0")
    ni = OxmlElement("w:numId")
    ni.set(qn("w:val"), str(new_id))
    numpr.append(il)
    numpr.append(ni)
    ppr.append(numpr)
    return new_id


def _set_num(par, num_id: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = par._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    il = OxmlElement("w:ilvl")
    il.set(qn("w:val"), "0")
    ni = OxmlElement("w:numId")
    ni.set(qn("w:val"), str(num_id))
    numpr.append(il)
    numpr.append(ni)
    ppr.append(numpr)


def convert(md_path: Path, out_path: Path) -> Path:
    import docx
    from docx.shared import Pt

    lines = md_path.read_text(encoding="utf-8").splitlines()
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), md_path.stem)
    d.core_properties.title = title
    i = 0
    para: list[str] = []
    ordered_id: int | None = None

    def flush_para() -> None:
        nonlocal para
        if para:
            p = d.add_paragraph()
            for k, part in enumerate(para):
                if k:
                    p.add_run().add_break()
                _runs(p, part.strip())
            para = []

    while i < len(lines):
        s = lines[i]
        st = s.strip()
        if st.startswith("```"):
            flush_para()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                p = d.add_paragraph()
                r = p.add_run(lines[i])
                r.font.name = "Consolas"
                r.font.size = Pt(10)
                i += 1
            i += 1
            ordered_id = None
            continue
        if not st or re.fullmatch(r"-{3,}", st):
            flush_para()
            ordered_id = None if not st else ordered_id
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            flush_para()
            d.add_heading(re.sub(r"[*`]", "", m.group(2)).strip(), level=min(len(m.group(1)), 4))
            ordered_id = None
            i += 1
            continue
        if st.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip()[1:-1].split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) or not any(cells):
                    rows.append(cells)
                i += 1
            ncol = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=ncol)
            t.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(ncol):
                    cell = t.cell(ri, ci)
                    _runs(cell.paragraphs[0], row[ci] if ci < len(row) else "", bold_all=ri == 0)
            ordered_id = None
            continue
        m = re.match(r"^\s*[*+-]\s+(.*)$", s)
        if m:
            flush_para()
            _runs(d.add_paragraph(style="List Bullet"), m.group(1))
            ordered_id = None
            i += 1
            continue
        m = re.match(r"^\s*(\d+)[.)]\s+(.*)$", s)
        if m:
            flush_para()
            p = d.add_paragraph(style="List Number")
            if ordered_id is None:
                ordered_id = _restart_numbering(d, p)
            else:
                _set_num(p, ordered_id)
            _runs(p, m.group(2))
            i += 1
            continue
        # абзац: строки подряд; «  » в конце строки — перенос строки внутри абзаца
        para.append(s.rstrip())
        if not s.endswith("  "):
            flush_para()
        i += 1
    flush_para()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    d.save(out_path)
    return out_path


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else ROOT / "release/input/requirements.md"
    out = Path(argv[1]) if len(argv) > 1 else src.with_suffix(".docx")
    print(convert(src, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
