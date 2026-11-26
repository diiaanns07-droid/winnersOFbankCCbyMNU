"""Общие помощники правил v2: строки документа, таблицы, цитаты, сборка кандидатов и сигналов.

Правила работают поверх DocView (CONTRACT, раздел 2.1). Текст строки может прийти как уже очищенным
от разметки (docview №03), так и сырым Markdown — помощники одинаково понимают оба вида.
Цитата кандидата — всегда подстрока очищенного текста строки, поэтому её находит сверка цитат.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MD_DECOR = re.compile(r"\*\*|__|`")
SEP_CELL = re.compile(r"^:?-{2,}:?$")
CODE_FENCE_WORD = re.compile(r"^(?:```.*|json|text|xml|yaml|yml|bash|sh|http|plain|plaintext)$", re.I)

KIND_ORDER = ("critical", "major", "minor")


def clean(s: str) -> str:
    """Текст строки без markdown-разметки: `**`, обратные кавычки, ведущие `#` и маркеры списка."""
    t = MD_DECOR.sub("", s or "")
    t = re.sub(r"^\s*#+\s*", "", t)
    t = re.sub(r"^\s*[*+\-]\s+", "", t)
    return t.strip()


def norm(s: str) -> str:
    """Нормализация для сравнения (как в сверке цитат, CONTRACT, раздел 7)."""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[«»“”„\"']", '"', s)
    s = re.sub(r"[—–‑−]", "-", s)
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    s = MD_DECOR.sub("", s)
    s = re.sub(r"^\s*#+\s*", "", s)
    s = re.sub(r"^\s*[*+]\s+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def split_cells(t: str) -> list[str] | None:
    s = t.strip()
    if "|" not in s:
        return None
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    parts = [c.strip() for c in s.split("|")]
    if len(parts) < 2:
        return None
    return parts


@dataclass
class Line:
    n: int
    raw: str
    text: str
    section: str = ""
    page: int | None = None
    cells: list[str] | None = None
    is_sep: bool = False
    is_code: bool = False
    is_heading: bool = False

    @property
    def joined(self) -> str:
        """Текст строки; для строки таблицы — ячейки через « | » (как в docview)."""
        if self.cells is not None:
            return " | ".join(self.cells)
        return self.text


@dataclass
class Doc:
    lines: list[Line]
    title: str = ""
    by_n: dict[int, Line] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_n = {x.n: x for x in self.lines}

    def get(self, n: int) -> Line | None:
        return self.by_n.get(n)

    def nonempty(self) -> list[Line]:
        return [x for x in self.lines if x.text]


def build_doc(view: dict) -> Doc:
    """DocView → Doc с распознанными строками таблиц, кода и заголовков."""
    out: list[Line] = []
    in_fence = False
    for i, ln in enumerate(view.get("lines") or [], 1):
        raw = str(ln.get("text", "") if isinstance(ln, dict) else ln)
        n = int(ln.get("n", i)) if isinstance(ln, dict) else i
        section = str((ln.get("section") if isinstance(ln, dict) else "") or "")
        page = ln.get("page") if isinstance(ln, dict) else None
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(Line(n, raw, "", section, page, is_code=True))
            continue
        text = clean(raw)
        line = Line(n, raw, text, section, page)
        if in_fence:
            line.is_code = True
        elif text.startswith(("{", "[")) and (text.endswith(("}", "]", "},", "],")) or '":' in text):
            line.is_code = True
        elif CODE_FENCE_WORD.match(text):
            line.is_code = True
        cells = None if line.is_code else split_cells(text)
        if cells is not None:
            if all(SEP_CELL.match(c) or not c for c in cells) and any(SEP_CELL.match(c) for c in cells):
                line.is_sep = True
                line.text = ""
            else:
                line.cells = cells
        if stripped.startswith("#"):
            line.is_heading = True
        elif section and text and cells is None and not line.is_code:
            last = section.split("›")[-1].strip()
            if last and norm(last) == norm(text):
                line.is_heading = True
        out.append(line)
    return Doc(out, title=str(view.get("title") or ""))


# --- таблицы -------------------------------------------------------------------------------------

@dataclass
class Table:
    header: Line
    rows: list[Line]

    @property
    def cols(self) -> list[str]:
        return [norm(c) for c in (self.header.cells or [])]

    def col(self, *names: str) -> int | None:
        for i, c in enumerate(self.cols):
            for nm in names:
                if c == nm or c.startswith(nm):
                    return i
        return None


def tables(doc: Doc) -> list[Table]:
    """Таблицы: строка-заголовок и следующие строки таблицы (пустые строки и разделители пропускаются)."""
    res: list[Table] = []
    i = 0
    L = doc.lines
    while i < len(L):
        x = L[i]
        if x.cells is None:
            i += 1
            continue
        header = x
        rows: list[Line] = []
        j = i + 1
        while j < len(L):
            y = L[j]
            if y.cells is not None:
                rows.append(y)
            elif y.is_sep:
                pass
            elif not y.text and j + 1 < len(L) and (L[j + 1].cells is not None or L[j + 1].is_sep):
                pass  # пустая строка таблицы («| | |») в очищенном виде
            else:
                break
            j += 1
        res.append(Table(header, rows))
        i = j
    return res


# --- кандидаты и сигналы -------------------------------------------------------------------------

def ev(line: Line, fragment: str | None = None) -> dict:
    """Цитата из строки: фрагмент очищенного текста (или вся строка, обрезанная до 200 символов)."""
    base = line.joined
    frag = (fragment or base).strip()
    if frag not in base:
        frag = base
    if len(frag) > 200:
        frag = frag[:200].rsplit(" ", 1)[0]
    return {"quote": frag, "line": line.n}


def cell_quote(line: Line, i: int, j: int | None = None) -> dict:
    """Цитата из ячеек строки таблицы: ячейки i..j через « | »."""
    cells = line.cells or []
    j = i if j is None else j
    frag = " | ".join(c for c in cells[i:j + 1])
    return ev(line, frag)


def candidate(rule: str, *, title: str, kind: str, criterion: str, severity: str, evidence: list[dict],
              problem: str, impact: str, recommendation: str, scenario: str = "", rewrite: str = "",
              question: str = "", blocks: str = "none", conflict: bool = False) -> dict:
    seen: set[tuple[str, int]] = set()
    evs = []
    for e in evidence:
        key = (e["quote"], e["line"])
        if key in seen or not e["quote"]:
            continue
        seen.add(key)
        evs.append(e)
    return {
        "title": title, "kind": kind, "criterion": criterion, "severity": severity,
        "requirement_ids": [], "evidence": evs, "problem": problem, "scenario": scenario,
        "impact": impact, "recommendation": recommendation, "rewrite": rewrite, "question": question,
        "blocks": blocks, "source": f"rules:{rule}",
        # Признак для офлайн-вердикта: конфликт двух цитат об одном предмете (не поле схемы модели).
        "rule_conflict": bool(conflict and len(evs) >= 2),
    }


def signal(rule: str, line: Line, quote: str, message: str, audience: tuple[str, ...] = (), kind: str = "") -> dict:
    e = ev(line, quote)
    return {"rule": rule, "kind": kind, "line": e["line"], "quote": e["quote"], "message": message,
            "audience": list(audience)}


def fmt_list(items: list[str], conj: str = "и") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def quoted(s: str) -> str:
    """Цитата внутри прозы: «…» без завершающей точки (точку ставит предложение)."""
    return f"«{s.rstrip().rstrip('.')}»"
