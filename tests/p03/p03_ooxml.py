"""Независимая проверка аннотированного DOCX прямо по OOXML (zipfile + lxml).

Хелперы не используют код экспортёра и python-docx: что видит Word, считается по
WordprocessingML. Видимый текст -- ``w:t``, ``m:t``, ``w:tab``/``w:br``/``w:cr`` в
run, ``w:noBreakHyphen``. Не входят: ``w:delText``, ``w:instrText``, поддеревья
``w:del``/``w:moveFrom`` (удалено при рецензировании) и ``w:txbxContent`` (рамка
вне потока абзаца). Пути -- XPath с индексом у каждого шага, как ``loc.path`` ридера.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Iterator

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
PREFIX = {W: "w", M: "m"}
STORY_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
_SKIP = {f"{{{W}}}del", f"{{{W}}}moveFrom", f"{{{W}}}txbxContent"}
_MARK = {"start": f"{{{W}}}commentRangeStart", "end": f"{{{W}}}commentRangeEnd", "ref": f"{{{W}}}commentReference"}


def w(name: str) -> str:
    return f"{{{W}}}{name}"


def part(path: Path, name: str = "word/document.xml") -> Any:
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(name))


def has_part(path: Path, name: str) -> bool:
    with zipfile.ZipFile(path) as z:
        return name in z.namelist()


def walk(el: Any) -> Iterator[Any]:
    """Порядок документа без удалённого текста и рамок."""
    yield el
    for child in el:
        if isinstance(child.tag, str) and child.tag not in _SKIP:
            yield from walk(child)


def visible(el: Any) -> str:
    tag = el.tag
    if tag in (w("t"), f"{{{M}}}t"):
        return el.text or ""
    parent = el.getparent()
    if parent is not None and parent.tag == w("r"):
        if tag == w("tab"):
            return "\t"
        if tag in (w("br"), w("cr")):
            return "\n"
        if tag == w("noBreakHyphen"):
            return "-"
    return ""


def comments(path: Path) -> dict[int, tuple[str, str]]:
    """``w:id`` -> (автор, текст) из word/comments.xml."""
    if not has_part(path, "word/comments.xml"):
        return {}
    root = part(path, "word/comments.xml")
    out = {}
    for c in root.findall(w("comment")):
        text = "\n".join("".join(t.text or "" for t in p.iter(w("t"))) for p in c.iter(w("p")))
        out[int(c.get(w("id")))] = (c.get(w("author")) or "", text)
    return out


def marker_counts(path: Path, cid: int) -> dict[str, int]:
    """Сколько маркеров комментария ``cid`` во всех частях-историях пакета."""
    counts = {"start": 0, "end": 0, "ref": 0}
    for name in STORY_PARTS:
        if not has_part(path, name):
            continue
        for kind, tag in _MARK.items():
            counts[kind] += sum(1 for el in part(path, name).iter(tag) if el.get(w("id")) == str(cid))
    return counts


def marker(root: Any, cid: int, kind: str) -> Any:
    found = [el for el in root.iter(_MARK[kind]) if el.get(w("id")) == str(cid)]
    assert len(found) == 1, f"маркер {kind} комментария {cid}: {len(found)} шт."
    return found[0]


def full_path(el: Any) -> str:
    """XPath как ``loc.path`` ридера: /w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]."""
    steps = []
    while el is not None and el.getparent() is not None:
        parent = el.getparent()
        same = [c for c in parent if c.tag == el.tag]
        ns, local = el.tag[1:].split("}")
        index = "" if local in ("body", "sdtContent") else f"[{same.index(el) + 1}]"  # как у ридера
        steps.append(f"{PREFIX.get(ns, ns)}:{local}{index}")
        el = parent
    ns, local = el.tag[1:].split("}")
    return "/" + "/".join([f"{PREFIX.get(ns, ns)}:{local}"] + steps[::-1])


def ancestor(el: Any, local: str) -> Any:
    a = el.getparent()
    while a is not None and a.tag != w(local):
        a = a.getparent()
    return a


def covered_text(path: Path, cid: int, name: str = "word/document.xml") -> str:
    """Видимый текст между commentRangeStart и commentRangeEnd (абзацы через ``\\n``)."""
    root = part(path, name)
    start, end = marker(root, cid, "start"), marker(root, cid, "end")
    out: list[str] = []
    inside = False
    for el in walk(root):
        if el is start:
            inside = True
            continue
        if el is end:
            break
        if inside:
            if el.tag == w("p") and out:
                out.append("\n")
            out.append(visible(el))
    return "".join(out)


def offset_in_paragraph(p: Any, target: Any) -> int:
    """Число видимых символов абзаца ``p`` перед элементом ``target``."""
    n = 0
    for el in walk(p):
        if el is target:
            return n
        n += len(visible(el))
    raise AssertionError("маркер не лежит в этом абзаце")


def block_span(path: Path, cid: int, document: Any) -> tuple[str, int, int, str]:
    """(block_id, start, end, путь абзаца начала) диапазона комментария в координатах block.text.

    ``document`` -- результат read_docx той же копии: из ``loc.paragraphs`` берётся
    только начало абзаца в тексте блока, позиции маркеров считаются здесь по XML.
    """
    root = part(path)
    res = []
    for kind in ("start", "end"):
        mk = marker(root, cid, kind)
        p = ancestor(mk, "p")
        ppath = full_path(p)
        hits = [(b.id, para["start"]) for b in document.blocks for para in b.loc["paragraphs"]
                if para["path"] == ppath]
        assert len(hits) == 1, f"абзац {ppath} не найден среди блоков"
        res.append((hits[0][0], hits[0][1] + offset_in_paragraph(p, mk), ppath))
    (b1, s, p1), (b2, e, _) = res
    assert b1 == b2, f"диапазон начинается в {b1}, а кончается в {b2}"
    return b1, s, e, p1


def hyperlinks(path: Path) -> list[tuple[str, str, str]]:
    """(r:id, Target, видимый текст) всех w:hyperlink с внешней связью."""
    rels = part(path, "word/_rels/document.xml.rels")
    targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{{{PR}}}Relationship")}
    out = []
    for h in part(path).iter(w("hyperlink")):
        rid = h.get(f"{{{R}}}id")
        if rid:
            out.append((rid, targets.get(rid, ""), "".join(visible(el) for el in walk(h))))
    return out


def runs_with_format(p: Any) -> list[tuple[str, bool, bool]]:
    """(текст, жирный, внутри гиперссылки) для run с видимым текстом."""
    out = []
    for r in p.iter(w("r")):
        if ancestor(r, "del") is not None:
            continue
        text = "".join(visible(el) for el in walk(r))
        if not text:
            continue
        b = r.find(f"{w('rPr')}/{w('b')}")
        bold = b is not None and b.get(w("val"), "1") not in ("0", "false", "off")
        out.append((text, bold, ancestor(r, "hyperlink") is not None))
    return out


def runs_bold_italic(p: Any) -> list[tuple[str, bool, bool]]:
    """(текст, жирный, курсив) для run с видимым текстом (прямое оформление run)."""
    def on(r: Any, tag: str) -> bool:
        el = r.find(f"{w('rPr')}/{w(tag)}")
        return el is not None and el.get(w("val"), "1") not in ("0", "false", "off")

    out = []
    for r in p.iter(w("r")):
        text = "".join(visible(el) for el in walk(r))
        if text and ancestor(r, "del") is None:
            out.append((text, on(r, "b"), on(r, "i")))
    return out


def range_map(path: Path, ids: Any, document: Any) -> dict[int, dict[str, Any]]:
    """Карта диапазонов: id -> ячейка/абзац границ, координаты в блоке, охват, первая строка тела."""
    root = part(path)
    bodies = comments(path)
    out = {}
    for cid in ids:
        start, end = marker(root, cid, "start"), marker(root, cid, "end")
        nodes = []
        for mk in (start, end):
            tc = ancestor(mk, "tc")
            nodes.append(full_path(tc) if tc is not None else full_path(ancestor(mk, "p")))
        block, s, e, _ = block_span(path, cid, document)
        out[cid] = {"start_node": nodes[0], "end_node": nodes[1], "block_id": block, "start": s, "end": e,
                    "covered": covered_text(path, cid), "author": bodies[cid][0],
                    "head": bodies[cid][1].splitlines()[0], "body": bodies[cid][1]}
    return out
