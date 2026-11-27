"""«Было → стало» исправлениями Word: правки ``--revise`` в копии DOCX режимом рецензирования.

Аналитик открывает ``<отчёт>.annotated.docx`` и видит каждую правку агента так, как её внёс бы коллега:
зачёркнутое «было», вставленное «стало», автор «BCC Review», рядом — комментарий с дефектом. Вкладка
«Рецензирование» → «Принять» / «Отклонить» по одной или все сразу.

Источник — ``report["rewrites"]`` (этап revise №11): ``replace`` — заменить фрагмент ``before`` на ``after``,
``insert_after`` — вставить абзацы после строки. Место ищется в тексте абзацев DOCX дословно (тот же текст,
что сверил агент), при нескольких совпадениях — абзац, текст которого совпадает со строкой view ``line_start``.
Фрагмент, который не найден однозначно, не трогается и попадает в счётчик «не внесено» — документ не портится.
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from pathlib import Path
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

AUTHOR = "BCC Review"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_TEXT_CHILD = {"t": None, "tab": "\t", "br": "\n", "cr": "\n", "noBreakHyphen": "-"}
_SIMPLE = {"rPr", "t", "tab", "br", "cr", "noBreakHyphen", "lastRenderedPageBreak"}
_DELETED = ("фрагмент удалён", "удалить", "")
_MD_INLINE = re.compile(r"\*\*|__|`")


def _local(el: Any) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _norm(s: str) -> str:
    """Та же длина, что у исходной строки: смещения в нормализованном тексте = смещения в абзаце."""
    return s.replace(" ", " ").replace(" ", " ").replace("ё", "е").replace("Ё", "Е")


def _md_plain(s: str) -> str:
    return _MD_INLINE.sub("", str(s or "")).strip()


def _ancestor(el: Any, names: tuple[str, ...]) -> bool:
    p = el.getparent()
    while p is not None:
        if _local(p) in names:
            return True
        if _local(p) == "p":
            return False
        p = p.getparent()
    return False


def _runs(p: Any) -> list[Any]:
    """Текущие run абзаца в порядке документа: без удалённых (w:del) и без вложенных абзацев надписей."""
    out = []
    for r in p.iter(qn("w:r")):
        if _ancestor(r, ("del", "txbxContent", "moveFrom")):
            continue
        out.append(r)
    return out


def _run_text(r: Any) -> str:
    parts = []
    for c in r:
        name = _local(c)
        if name == "t":
            parts.append(c.text or "")
        elif name in _TEXT_CHILD:
            parts.append(_TEXT_CHILD[name])
    return "".join(parts)


def _para_text(p: Any) -> str:
    return "".join(_run_text(r) for r in _runs(p))


def _split(r: Any, k: int) -> Any:
    """Разрезать run после k символов (как exports/word.split_run), вернуть правую часть."""
    new = OxmlElement("w:r")
    for attr, val in r.attrib.items():
        new.set(attr, val)
    rpr = r.find(qn("w:rPr"))
    if rpr is not None:
        new.append(copy.deepcopy(rpr))
    acc, moving = 0, False
    for child in [c for c in r if c is not rpr]:
        if moving:
            new.append(child)
            continue
        name = _local(child)
        n = len(child.text or "") if name == "t" else (1 if name in _TEXT_CHILD else 0)
        if acc + n <= k:
            acc += n
            continue
        if acc >= k:
            moving = True
            new.append(child)
            continue
        cut = k - acc
        txt = child.text or ""
        child.text = txt[:cut]
        child.set(_XML_SPACE, "preserve")
        nt = OxmlElement("w:t")
        nt.text = txt[cut:]
        nt.set(_XML_SPACE, "preserve")
        new.append(nt)
        moving = True
        acc += n
    r.addnext(new)
    return new


class _Ids:
    def __init__(self, root: Any) -> None:
        used = [int(v) for el in root.iter() for k, v in el.attrib.items()
                if k == qn("w:id") and str(v).lstrip("-").isdigit()]
        self.n = max(used + [0]) + 1000
        self.date = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    def mark(self, tag: str, author: str) -> Any:
        self.n += 1
        el = OxmlElement(tag)
        el.set(qn("w:id"), str(self.n))
        el.set(qn("w:author"), author)
        el.set(qn("w:date"), self.date)
        return el


def _text_run(text: str, rpr: Any | None) -> Any:
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = OxmlElement("w:t")
    t.text = text
    t.set(_XML_SPACE, "preserve")
    r.append(t)
    return r


def _find(paras: list[Any], before: str, line_text: str | None) -> tuple[Any, int] | None:
    """Абзац и смещение, где ``before`` встречается ровно один раз; при нескольких абзацах — подсказка строкой."""
    needle = _norm(before)
    hits = []
    for p in paras:
        text = _norm(_para_text(p))
        i = text.find(needle)
        if i >= 0 and text.find(needle, i + 1) < 0:
            hits.append((p, i, text))
        elif i >= 0:
            hits.append((p, -1, text))  # в абзаце несколько совпадений — не угадываем
    if line_text and len(hits) > 1:
        want = " ".join(_norm(_md_plain(line_text)).split())
        hits = [h for h in hits if want and (want in " ".join(h[2].split()) or " ".join(h[2].split()) in want)]
    if len(hits) != 1 or hits[0][1] < 0:
        return None
    return hits[0][0], hits[0][1]


def _replace(p: Any, start: int, before: str, after: str, ids: _Ids, author: str) -> bool:
    end = start + len(before)
    runs, off, inside = _runs(p), 0, []
    for r in runs:
        n = len(_run_text(r))
        a, b = off, off + n
        off = b
        if b <= start or a >= end or n == 0:
            continue
        if any(_local(c) not in _SIMPLE for c in r):
            return False  # поле, рисунок, сноска внутри фрагмента — не трогаем
        inside.append((r, a, b))
    if not inside:
        return False
    # границы: резать первый и последний run
    r0, a0, b0 = inside[0]
    if start > a0:
        right = _split(r0, start - a0)
        inside[0] = (right, start, b0)
        if len(inside) == 1:
            r0, a0, b0 = inside[0]
    rl, al, bl = inside[-1]
    if end < bl:
        _split(rl, end - al)
        inside[-1] = (rl, al, end)
    rpr = inside[0][0].find(qn("w:rPr"))
    last = None
    for r, _, _ in inside:
        d = ids.mark("w:del", author)
        r.addprevious(d)
        d.append(r)
        for c in r:
            if _local(c) == "t":
                c.tag = qn("w:delText")
                c.set(_XML_SPACE, "preserve")
        last = d
    if after:
        ins = ids.mark("w:ins", author)
        ins.append(_text_run(after, rpr))
        last.addnext(ins)
    return True


def _md_lines(after: str) -> list[str]:
    """Вставляемые абзацы из Markdown правки: без заголовочных «#», выделения и разделителей таблиц."""
    out = []
    for raw in str(after or "").splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s):
            continue
        s = re.sub(r"^#{1,6}\s+", "", s)
        if s.startswith("|") and s.endswith("|"):
            s = " · ".join(c.strip() for c in s.strip("|").split("|"))
        out.append(_md_plain(s))
    return [s for s in out if s]


def _insert_after(p: Any, after: str, ids: _Ids, author: str) -> bool:
    lines = _md_lines(after)
    if not lines:
        return False
    if any(_local(a) == "tc" for a in p.iterancestors()):
        return False  # строка таблицы: вставка абзаца в ячейку исказила бы таблицу
    ppr = p.find(qn("w:pPr"))
    runs = _runs(p)
    rpr = runs[0].find(qn("w:rPr")) if runs else None
    anchor = p
    for text in lines:
        np_ = OxmlElement("w:p")
        if ppr is not None:
            npr = copy.deepcopy(ppr)
            for x in npr.findall(qn("w:sectPr")):
                npr.remove(x)
        else:
            npr = OxmlElement("w:pPr")
        mark_rpr = npr.find(qn("w:rPr"))
        if mark_rpr is None:
            mark_rpr = OxmlElement("w:rPr")
            npr.append(mark_rpr)
        mark_rpr.append(ids.mark("w:ins", author))  # знак абзаца — тоже вставка: «Отклонить» убирает абзац целиком
        np_.append(npr)
        ins = ids.mark("w:ins", author)
        ins.append(_text_run(text, rpr))
        np_.append(ins)
        anchor.addnext(np_)
        anchor = np_
    return True


_LIST_MARK = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*•])\s+")


def _variants(before: str, after: str) -> list[tuple[str, str]]:
    """Как искать фрагмент в Word: дословно; без номера пункта списка (в Word нумерация — автоматическая)."""
    out = [(before, after)]
    if _LIST_MARK.match(before):
        out.append((_LIST_MARK.sub("", before, 1), _LIST_MARK.sub("", after, 1)))
    return out


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _line_text(view: dict | None, n: Any) -> str | None:
    if not view or not n:
        return None
    for ln in view.get("lines") or []:
        if ln.get("n") == n:
            return str(ln.get("text") or "")
    return None


def apply_rewrites(doc: Any, rewrites: list[dict], view: dict | None = None, *, author: str = AUTHOR) -> dict:
    """Внести правки в открытый ``docx.Document``. Возвращает счётчики ``{"applied", "skipped", "total", ...}``."""
    root = doc.element.body
    ids = _Ids(doc.element)
    paras = [p for p in root.iter(qn("w:p")) if not _ancestor(p, ("txbxContent",))]
    applied, skipped, by_finding = 0, [], {}
    for rw in rewrites or []:
        if not isinstance(rw, dict) or rw.get("applied") is False:
            continue
        action = rw.get("action")
        before = _md_plain(rw.get("before"))
        after = str(rw.get("after") or "")
        after_plain = "" if after.strip() in _DELETED else _md_plain(" ".join(after.split()))
        line_text = _line_text(view, rw.get("line_start"))
        ok = False
        if action == "replace" and before:
            for b, a in _variants(before, after_plain):
                pairs = [(b, a)]
                if "|" in b:  # строка таблицы Markdown — в Word каждая ячейка отдельным абзацем
                    bc, ac = _cells(b), _cells(a)
                    if len(bc) != len(ac):
                        continue
                    pairs = [(x, y) for x, y in zip(bc, ac) if x != y and x]
                done = 0
                for b1, a1 in pairs:
                    hit = _find(paras, b1, line_text if len(pairs) == 1 else None)
                    if hit and _replace(hit[0], hit[1], b1, a1, ids, author):
                        done += 1
                if pairs and done:
                    ok = True
                    break
        elif action == "insert_after":
            anchor_text = before or (_md_plain(line_text) if line_text else "")
            hit = _find(paras, anchor_text, None) if anchor_text else None
            if hit:
                ok = _insert_after(hit[0], after, ids, author)
                if ok:  # новые абзацы — тоже кандидаты для следующих вставок «после»
                    paras = [p for p in root.iter(qn("w:p")) if not _ancestor(p, ("txbxContent",))]
        if ok:
            applied += 1
            by_finding[rw.get("finding_id")] = by_finding.get(rw.get("finding_id"), 0) + 1
        else:
            skipped.append({"finding_id": rw.get("finding_id"), "action": action, "before": before[:80]})
    return {"applied": applied, "skipped": skipped, "total": applied + len(skipped), "findings": len(by_finding)}


def write_revisions(docx_path: str | Path, rewrites: list[dict], view: dict | None = None,
                    output_path: str | Path | None = None, *, author: str = AUTHOR) -> dict:
    """Открыть DOCX, внести правки исправлениями Word и сохранить (по умолчанию — поверх ``docx_path``)."""
    import docx
    d = docx.Document(str(docx_path))
    stats = apply_rewrites(d, rewrites, view, author=author)
    if stats["applied"]:
        d.save(str(output_path or docx_path))
    return stats
