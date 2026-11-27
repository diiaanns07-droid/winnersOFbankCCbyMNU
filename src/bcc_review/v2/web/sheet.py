"""№39: лист ТЗ на тёмном столе — строки с номерами, правка по листу, заметки на полях, печать, карта листа.

Своей логики качества нет: всё берётся из готового report.json (findings → evidence → quote, line_start, verified)
и из исходного текста документа. Вид — классы `.b-*` из `assets/tokens.css`.

    sheet = build_sheet(report, source_lines, file_name="requirements.md")
    sheet.html   — <article class="b-sheet">… с печатью, строками и заметками
    sheet.map    — засечки для карты листа (<i class="crit" style="--y:.19" data-line="39">)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

TEXT_EXT = {".md", ".markdown", ".txt"}
SEV = {"critical": "crit", "major": "major", "minor": "minor"}
SEV_RANK = {"crit": 3, "major": 2, "minor": 1}
STAMP = {"no": ("crit", "Нельзя в разработку"), "conditional": ("cond", "С условиями"), "yes": ("ok", "Можно в разработку")}

_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_SEP_ROW = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LI = re.compile(r"^(\s*)([*+-]|\d+[.)])\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPH = re.compile(r"(\*\*|__|`)")


def e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def _clean(t: str) -> str:
    """Строка Markdown → текст, как его читает человек (цитаты агента — тоже текст без разметки)."""
    t = _LINK.sub(r"\1", t)
    t = _EMPH.sub("", t)
    return t.replace("\\|", "|").rstrip()


@dataclass
class Line:
    no: int
    kind: str  # blank, h1..h4, rule, row, th, sep, li, bq, p
    text: str
    cells: list[str] = field(default_factory=list)


def parse_lines(raw: list[str]) -> list[Line]:
    out: list[Line] = []
    table_head = False
    for i, src in enumerate(raw, 1):
        s = src.rstrip("\r")
        if not s.strip():
            out.append(Line(i, "blank", ""))
            table_head = False
            continue
        if _SEP_ROW.match(s) and "|" in s:
            out.append(Line(i, "sep", ""))
            continue
        m = _ROW.match(s)
        if m:
            cells = [_clean(c.strip()) for c in re.split(r"(?<!\\)\|", m.group(1))]
            kind = "row" if table_head else "th"
            table_head = True
            out.append(Line(i, kind, "  ".join(cells), cells))
            continue
        table_head = False
        if _RULE.match(s):
            out.append(Line(i, "rule", ""))
            continue
        m = _HEAD.match(s)
        if m:
            out.append(Line(i, f"h{min(len(m.group(1)), 4)}", _clean(m.group(2))))
            continue
        m = _LI.match(s)
        if m:
            mark = "•" if m.group(2) in "*+-" else m.group(2)
            out.append(Line(i, "li", f"{mark} {_clean(m.group(3))}"))
            continue
        m = _QUOTE.match(s)
        if m:
            out.append(Line(i, "bq", _clean(m.group(1))))
            continue
        out.append(Line(i, "p", _clean(s.strip())))
    return out


def read_source(path: Path | str | None) -> list[str] | None:
    """Строки исходного документа, если он текстовый (номера строк отчёта считаются по ним)."""
    if not path:
        return None
    p = Path(path)
    if p.suffix.lower() not in TEXT_EXT or not p.is_file():
        return None
    try:
        text = p.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(raw) > 1 and raw[-1] == "":  # перевод строки в конце файла — не строка документа
        raw.pop()
    return raw


def load_report(path: Path | str | None) -> dict[str, Any] | None:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("findings"), list) else None


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("ё", "е").replace("Ё", "Е")).strip().casefold()


def _find(hay: str, needle: str) -> tuple[int, int] | None:
    """Позиция цитаты в строке: точно, затем без учёта пробелов, регистра и «ё»."""
    if not needle:
        return None
    k = hay.find(needle)
    if k >= 0:
        return k, k + len(needle)
    n = _norm(_clean(needle))
    if not n:
        return None
    # карта позиций нормализованной строки → исходной
    idx, buf, prev_space = [], [], False
    for j, ch in enumerate(hay.replace("ё", "е").replace("Ё", "Е")):
        if ch.isspace():
            if prev_space or not buf:
                continue
            buf.append(" ")
            idx.append(j)
            prev_space = True
        else:
            buf.append(ch.casefold())
            idx.append(j)
            prev_space = False
    k = "".join(buf).find(n)
    if k < 0:
        return None
    return idx[k], idx[min(k + len(n), len(idx)) - 1] + 1


@dataclass
class Sheet:
    html: str
    map: str
    notes: int
    blockers: int
    questions: int
    lines: int


def _spans(lines: list[Line], findings: list[dict[str, Any]]):
    """Отметки: {номер строки: [(начало, конец, класс, id)]}; конец None — вся строка. И сверенные строки."""
    by_no = {ln.no: ln for ln in lines}
    marks: dict[int, list[tuple[int, int | None, str, str]]] = {}
    ok: set[int] = set()
    anchors: list[tuple[int, dict[str, Any]]] = []
    for f in findings:
        sev = SEV.get(str(f.get("severity")), "minor")
        first = None
        for ev in f.get("evidence") or []:
            try:
                a = int(ev.get("line_start") or 0)
                b = int(ev.get("line_end") or a)
            except (TypeError, ValueError):
                continue
            if a <= 0 or a not in by_no:
                continue
            first = a if first is None else min(first, a)
            if str(ev.get("verified") or "") in ("exact", "normalized", "fuzzy", "ok", "true", "True"):
                ok.update(range(a, b + 1))
            if a == b:
                pos = _find(by_no[a].text, str(ev.get("quote") or ""))
                marks.setdefault(a, []).append((pos[0], pos[1], sev, str(f.get("id") or "")) if pos
                                               else (0, None, sev, str(f.get("id") or "")))
            else:
                for n in range(a, b + 1):
                    if n in by_no and by_no[n].text:
                        marks.setdefault(n, []).append((0, None, sev, str(f.get("id") or "")))
        if first is not None:
            anchors.append((first, f))
    return marks, ok, anchors


def _paint(text: str, spans: list[tuple[int, int | None, str, str]], counter: list[int]) -> str:
    """Текст строки с отметками: перекрытия режутся на куски, у куска — самая тяжёлая критичность."""
    if not spans:
        return e(text)
    cuts = {0, len(text)}
    norm = []
    for a, b, sev, fid in spans:
        b = len(text) if b is None else b
        a, b = max(0, min(a, len(text))), max(0, min(b, len(text)))
        if b > a:
            norm.append((a, b, sev, fid))
            cuts.update((a, b))
    pts = sorted(cuts)
    out = []
    for a, b in zip(pts, pts[1:]):
        seg = text[a:b]
        cover = [s for s in norm if s[0] <= a and s[1] >= b]
        if not cover:
            out.append(e(seg))
            continue
        sev = max(cover, key=lambda s: SEV_RANK[s[2]])[2]
        ids = " ".join(dict.fromkeys(s[3] for s in cover))
        out.append(f'<span class="b-hl {sev}" data-f="{e(ids)}" style="--i:{counter[0]}">{e(seg)}</span>')
        counter[0] += 1
    return "".join(out)


def _duration(s: Any) -> str:
    try:
        s = float(s)
    except (TypeError, ValueError):
        return ""
    if s < 60:
        return f"{round(s)} с"
    return f"{s / 60:.1f} мин".replace(".", ",")


def stamp_html(report: dict[str, Any]) -> str:
    """Печать вердикта и строка под ней (цитаты сверены · модель · время)."""
    v = (report.get("verdict") or {}).get("development") or ""
    cls, word = STAMP.get(v, ("cond", "Вердикт не вынесен"))
    crit = sum(1 for f in report.get("findings") or [] if f.get("severity") == "critical")
    sub = f"{crit} {plural(crit, 'блокер', 'блокера', 'блокеров')}" if crit else "блокеров нет"
    evs = [ev for f in report.get("findings") or [] for ev in f.get("evidence") or []]
    ver = sum(1 for ev in evs if str(ev.get("verified") or "") in ("exact", "normalized", "fuzzy", "ok"))
    run = report.get("run") or {}
    model = next(iter(run.get("models_used") or []), "") or run.get("provider") or ""
    meta = [f"цитат сверено {ver} из {len(evs)}" if evs else "", " · ".join(x for x in (e(model), _duration(run.get("duration_s"))) if x)]
    return (f'<div class="b-stamp {cls}" role="img" aria-label="{e(word)}, {e(sub)}">{e(word)}<small>{e(sub)}</small></div>'
            f'<div class="b-stamp-meta">{"<br>".join(m for m in meta if m)}</div>')


def build_sheet(report: dict[str, Any] | None, raw: list[str] | None, *, file_name: str = "",
                animate: bool = True) -> Sheet:
    report = report or {}
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    if raw is None:  # исходник не текстовый: лист из цитат отчёта, пропуски — многоточием
        quoted: dict[int, str] = {}
        for f in findings:
            for ev in f.get("evidence") or []:
                try:
                    quoted.setdefault(int(ev.get("line_start") or 0), str(ev.get("quote") or ""))
                except (TypeError, ValueError):
                    pass
        total = int((report.get("document") or {}).get("lines") or max(quoted or {0: ""}))
        raw = [quoted.get(i, "") for i in range(1, total + 1)]
    lines = parse_lines(raw)
    marks, ok, anchors = _spans(lines, findings)
    notes_at: dict[int, list[dict[str, Any]]] = {}
    for no, f in sorted(anchors, key=lambda x: x[0]):
        notes_at.setdefault(no, []).append(f)
    counter = [0]
    rows = []
    note_i = 0
    for ln in lines:
        cls = ["b-line", ln.kind]
        if ln.no in ok:
            cls.append("ok")
        if ln.kind in ("row", "th"):
            cls.append("cell")
            n = max(len(ln.cells), 1)
            grid = "minmax(0,34%) minmax(0,1fr)" if n == 2 else f"repeat({n},minmax(0,1fr))"
            body = "".join(f'<span class="c">{e(c)}</span>' for c in ln.cells)
            if marks.get(ln.no):  # строка таблицы с замечанием — отметка на каждой ячейке строки
                sev = max((m[2] for m in marks[ln.no]), key=lambda s: SEV_RANK[s])
                ids = " ".join(dict.fromkeys(m[3] for m in marks[ln.no]))
                body = "".join(f'<span class="c"><span class="b-hl {sev}" data-f="{e(ids)}" style="--i:{counter[0]}">'
                               f'{e(c)}</span></span>' for c in ln.cells if c) or body
                counter[0] += 1
        elif ln.kind in ("blank", "sep", "rule"):
            body = ""
            grid = ""
        else:
            body = _paint(ln.text, marks.get(ln.no, []), counter)
            grid = ""
        notes = ""
        for f in notes_at.get(ln.no, []):
            sev = SEV.get(str(f.get("severity")), "minor")
            title = str(f.get("title") or f.get("problem") or "")
            notes += (f'<button type="button" class="b-note {sev}" data-f="{e(f.get("id"))}" style="--i:{note_i}">'
                      f'<b>{e(f.get("id"))}</b><span class="t">{e(title)}</span></button>')
            note_i += 1
        if notes:
            cls.append("has-note")
        ids = " ".join(dict.fromkeys(m[3] for m in marks.get(ln.no, [])))
        rows.append(f'<div class="{" ".join(cls)}" id="L{ln.no}"{f" data-f={chr(34)}{e(ids)}{chr(34)}" if ids else ""}>'
                    f'<span class="b-ln">{ln.no}</span><span class="b-tx"{f" style={chr(34)}grid-template-columns:{grid}{chr(34)}" if grid else ""}>'
                    f'{body}</span>{notes}</div>')
    total = max(len(lines), 1)
    ticks = "".join(
        f'<i class="{SEV.get(str(f.get("severity")), "minor")}" style="--y:{(no - 1) / total:.4f}" data-line="{no}" '
        f'title="{e(f.get("id"))} · строка {no}"></i>' for no, f in sorted(anchors, key=lambda x: x[0]))
    stamp = stamp_html(report) if report.get("verdict") else ""
    reqs = len(report.get("requirements") or [])
    head = " · ".join(x for x in (e(file_name), f"{len(raw)} {plural(len(raw), 'строка', 'строки', 'строк')}",
                                  f"{reqs} {plural(reqs, 'требование', 'требования', 'требований')}" if reqs else "") if x)
    html = (f'<article class="b-sheet{" has-stamp" if stamp else ""}{" b-rise" if animate else ""}" id="sheet" '
            f'data-lines="{len(raw)}" aria-label="Документ {e(file_name)}">'
            f'<div class="b-sheet-head">{head}</div>{stamp}{"".join(rows)}</article>')
    crit = sum(1 for f in findings if f.get("severity") == "critical")
    return Sheet(html=html, map=ticks, notes=note_i, blockers=crit, questions=len(report.get("questions") or []),
                 lines=len(raw))
