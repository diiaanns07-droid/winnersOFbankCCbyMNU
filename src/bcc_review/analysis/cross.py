"""Межраздельные противоречия и покрытие приёмкой (направление №06).

Публичный протокол::

    review_set(document, requirements, ask=None, *, fact_hints=None)
        -> {facts, coverage, candidates, warnings,
            coverage_summary, comparisons, evidence_audit, stats}

Как принимается решение
-----------------------
* Лексическое сходство и программные подсказки только **отбирают** пары (проход по
  сущностям + отдельный проход между секциями бизнес-правил, UI, интеграции, API и приёмки).
* Противоречие подтверждается **witness** = {input, outcome_a, outcome_b, evidence_a, evidence_b}:
  один вход удовлетворяет обоим предусловиям, исходы несовместимы, обе опоры найдены в тексте.
  Предусловия проверяются программой по ограничениям ``{var, op, value}`` и фактам
  (``range:FX-…``). Если общий вход построить нельзя, кандидат уходит №08 как вопрос.
  Непересекающиеся условия (подтверждён/отменён) — совместимость, а не конфликт.
* Детерминированные проверки работают и без модели: границы/единицы/типы/HTTP по фактам
  (facts.py), граница расчётного периода, обещанный, но не описанный метод контракта.
* Покрытие считается по обязательствам (предложениям требования) с сохранением
  знаменателя. Связь с приёмкой не равна covered: нужен проверенный набор ветвей без
  противоречия; при пропущенных страницах отсутствие связи — unknown.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from .facts import (
    MONTH_NAMES,
    _is_adj,
    Audit,
    DocView,
    FactSet,
    Stamp,
    as_dict,
    extract_facts,
    find_stamps,
    get,
    key_set,
    keys_of,
    make_candidate,
    month_mentions,
    norm,
    find_money,
    parse_money,
    parse_num,
    strip_md,
    tz_offset,
)

__all__ = ["review_set", "reconcile_facts", "summarize_coverage", "STAGE_PAIRS", "STAGE_COVERAGE"]

from .facts import reconcile_facts  # noqa: E402 — реэкспорт по протоколу

# «#» — подэтап: учёт движка (StageStats.base) сводит их в этап «cross» паспорта
STAGE_PAIRS = "cross#pairs"
STAGE_COVERAGE = "cross#coverage"
PARTIAL_READ_CODES = ("partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input")
# Покрытие приёмкой считается по обязательствам этих разделов; контракт API, примеры, схемы и цели — вне знаменателя.
COVERAGE_GROUPS = {"business_rules", "integration", "data", "nfr", "ui", "other"}
COVERAGE_ROLES = {"api_logic"}
COVERAGE_STATUSES = ("covered", "partial", "conflict", "uncovered", "unknown")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# =============================================================== требования и обязательства

_ID_PREFIX = re.compile(r"^\s*(?:[*\-+]\s+|\d+\.\s+)?\**\s*(?:[A-Za-zА-Яа-яЁё]{1,5}-?\d+(?:\.\d+)*)\.?\s*\**\s*")
_BULLET = re.compile(r"^\s*(?:[*\-+]|\d+\.)\s+")


@dataclass
class Req:
    id: str
    source_id: Optional[str]
    text: str
    block_ids: list
    evidence: list

    unique_label: bool = True

    def _sid(self) -> str:
        sid = (self.source_id or "").strip()
        return sid if re.fullmatch(r"[A-Za-zА-Яа-яЁё]{1,6}[-‑–]?\d+(?:\.\d+)*", sid) else ""

    @property
    def key(self) -> str:
        """Ключ обязательств: ID документа («Ф-1»), если он уникален, иначе ID нарезки."""
        sid = self._sid()
        return sid if sid and self.unique_label else self.id

    @property
    def label(self) -> str:
        """Подпись для людей: «Ф-1», а при атомарной нарезке — «Ф-2, R-003.1»."""
        sid = self._sid()
        if sid and not self.unique_label:
            return f"{sid}, {self.id}"
        return sid or self.id


@dataclass
class Obligation:
    oid: str
    req_id: str
    label: str
    text: str
    hint: dict
    branches: list
    role: str


@dataclass
class Acc:
    aid: str
    label: str
    block_id: str
    text: str
    base: int
    cells: dict
    hint: dict
    req_id: Optional[str] = None


def sentence_spans(text: str, start: int = 0, end: Optional[int] = None) -> list[tuple[int, int]]:
    """Предложения с координатами.

    Не режет «1 000.» внутри чисел, «т. д.», время 23:58 и мягкие переносы строк PDF: перевод строки
    завершает предложение только после знака конца предложения или перед маркером пункта списка.
    """
    end = len(text) if end is None else end
    out = []
    s = start
    i = start
    while i < end:
        ch = text[i]
        boundary = False
        j = i + 1
        if ch in ".!?;":
            while j < end and text[j] in ".!?;":
                j += 1
            k = j
            while k < end and text[k] in " \t*\n":
                k += 1
            boundary = k >= end or text[k].isupper() or text[k] in "«\"(•*-" or text[k].isdigit() and "\n" in text[j:k]
            if ch == "." and i > 0 and text[i - 1].isdigit() and k < end and text[k].isdigit() and "\n" not in text[j:k]:
                boundary = False
        elif ch == "\n":
            k = j
            while k < end and text[k] in " \t":
                k += 1
            prev = text[s:i].rstrip()
            boundary = bool(prev) and (prev[-1] in ".!?;:" or bool(re.match(r"[*\-•]\s|\d{1,3}[.)]\s", text[k:k + 4])))
        else:
            k = j
        if boundary:
            out.append((s, j))
            s = k
            i = k
            continue
        i += 1
    if s < end and text[s:end].strip():
        out.append((s, end))
    res = []
    for a, b in out:
        while a < b and text[a] in " \t*\n":
            a += 1
        while b > a and text[b - 1] in " \t*\n":
            b -= 1
        if b > a and re.search(r"[A-Za-zА-Яа-яЁё]{2}", text[a:b]):
            res.append((a, b))
    return res


def _strip_prefix(text: str) -> int:
    m = _ID_PREFIX.match(text)
    if m and re.search(r"\d", m.group(0)):
        return m.end()
    m = _BULLET.match(text)
    return m.end() if m else 0


def branches_of(text: str) -> list[str]:
    """Эвристика ветвей обязательства: границы, альтернативы, ограничение повторов, условие."""
    t = norm(text)
    br: list[str] = []
    if re.search(r"\bот\s+\d[\d\s]*\s*\S*\s+до\s+\d", t) or re.search(r"\d\s*-\s*\d", t):
        br += ["нижняя граница", "верхняя граница", "значение ниже нижней границы", "значение выше верхней границы"]
    m = re.search(r"([^,.;]+?)\s+(исключа\w+|не учитыва\w+|не входят)", t)
    if m:
        items = [x for x in re.split(r",|\s+и\s+|\s+или\s+", m.group(1)) if x.strip()]
        if len(items) > 1:
            br += [f"исключение: {x.strip()}" for x in items]
    if re.search(r"\bили\b", t) and not br:
        alts = [x.strip() for x in re.split(r"\bили\b", t)]
        br += [f"вариант: {a[-40:]}" for a in alts if a]
    if re.search(r"максимум|не более|только один|не чаще|однократн", t):
        br += ["первое срабатывание", "повторное срабатывание не происходит"]
    if re.match(r"^(когда|если|при)\b", t) or re.search(r",\s*(если|когда)\b", t):
        br += ["условие выполнено", "условие не выполнено"]
    return list(dict.fromkeys(br)) or ["основной сценарий"]


def _norm_requirements(view: DocView, requirements: Any, warnings: list) -> list[Req]:
    out: list[Req] = []
    for i, r in enumerate(list(requirements or []), 1):
        d = as_dict(r)
        rid = str(d.get("id") or f"REQ-{i:03d}")
        bids = [str(b) for b in (d.get("block_ids") or []) if str(b) in view.by_id]
        evs = [as_dict(e) for e in (d.get("evidence") or [])]
        for e in evs:
            if e.get("block_id") and str(e["block_id"]) not in bids and str(e["block_id"]) in view.by_id:
                bids.append(str(e["block_id"]))
        if not bids:
            warnings.append(f"{rid}: нет block_ids текущего документа — требование не участвует в покрытии.")
        out.append(Req(rid, d.get("source_id"), str(d.get("text") or ""), bids, evs))
    if out:
        counts: dict[str, int] = {}
        for r in out:
            counts[r.source_id or ""] = counts.get(r.source_id or "", 0) + 1
        for r in out:
            r.unique_label = counts.get(r.source_id or "", 0) == 1
        return out
    # Запасной путь: требования из разделов бизнес-правил.
    n = 0
    for bid in view.ids:
        if view.group(bid) != "business_rules" or view.kind(bid).startswith("heading"):
            continue
        n += 1
        text = view.text(bid)
        m = re.search(r"\b([A-Za-zА-Яа-яЁё]{1,5}-\d+(?:\.\d+)*)\b", text[:30])
        out.append(Req(f"AUTO-{n:03d}", m.group(1) if m else None, strip_md(text), [bid], []))
    if out:
        warnings.append("Список требований не передан: обязательства взяты из разделов бизнес-правил.")
    return out


def _coverable(view: DocView, bid: str) -> bool:
    if "code" in view.kind(bid):
        return False
    return view.group(bid) in COVERAGE_GROUPS or view.role.get(bid) in COVERAGE_ROLES


def _obligations(view: DocView, reqs: list[Req], acc_blocks: set, excluded: Optional[list] = None) -> list[Obligation]:
    obls: list[Obligation] = []
    for r in reqs:
        n = 0
        bids = [b for b in r.block_ids if b not in acc_blocks]
        if excluded is not None and bids and not any(_coverable(view, b) for b in bids):
            groups = sorted({ROLE_RU.get(view.group(b), view.group(b)) for b in bids})
            excluded.append({"req_id": r.id, "label": r.label,
                             "reason": f"раздел «{', '.join(groups)}»: контракт, пример, схема или паспорт — "
                                       f"проверяется сравнением фактов, а не приёмкой"})
        for bid in bids:
            if view.role.get(bid) in ("template", "heading") or not _coverable(view, bid):
                continue
            text = view.text(bid)
            spans = [(int(e["start"]), int(e["end"])) for e in r.evidence
                     if str(e.get("block_id")) == bid and isinstance(e.get("start"), int) and isinstance(e.get("end"), int)]
            if not spans:
                spans = [(0, len(text))]
            for s0, e0 in spans:
                s0 = s0 + _strip_prefix(text[s0:e0])
                for a, b in sentence_spans(text, s0, e0):
                    n += 1
                    q = text[a:b]
                    obls.append(Obligation(f"{r.key}#{n}", r.id, r.label, " ".join(strip_md(q).split()),
                                           {"block_id": bid, "start": a, "end": b, "quote": q},
                                           branches_of(q), view.group(bid)))
    return obls


def _acceptance(view: DocView, fs: FactSet, reqs: list[Req]) -> list[Acc]:
    by_block = {}
    for r in reqs:
        for b in r.block_ids:
            by_block.setdefault(b, r)
    items: list[Acc] = []
    table_blocks = set()
    n = 0
    rows_in_block: dict[str, int] = {}
    for t in fs.tables:
        if view.role.get(t.block_ids[0]) == "acceptance":
            for row in t.rows:
                if row and any(c.clean for c in row):
                    rows_in_block[row[0].block_id] = rows_in_block.get(row[0].block_id, 0) + 1
    for t in fs.tables:
        if view.role.get(t.block_ids[0]) != "acceptance":
            continue
        cp, ca, ce = t.col("pre"), t.col("action"), t.col("expected")
        for row in t.rows:
            if not row or not any(c.clean for c in row):
                continue
            n += 1
            bid = row[0].block_id
            a, b = row[0].start, row[-1].end
            text = view.text(bid)
            cells = {}
            for name, ci in (("pre", cp), ("action", ca), ("expected", ce)):
                if ci is not None and ci < len(row):
                    cells[name] = row[ci].ev()
            r = by_block.get(bid)
            aid = r.id if r and r.block_ids == [bid] and rows_in_block.get(bid) == 1 else f"AC-{n}"
            items.append(Acc(aid, f"Приёмка №{n}" + ("" if aid.startswith("AC-") else f" ({aid})"), bid,
                             text[a:b], a, cells, {"block_id": bid, "start": a, "end": b, "quote": text[a:b]},
                             r.id if r else None))
            table_blocks.add(bid)
    for bid in view.ids:
        if view.role.get(bid) != "acceptance" or bid in table_blocks or view.kind(bid).startswith("heading"):
            continue
        if any(bid in t.block_ids for t in fs.tables):
            continue
        text = view.text(bid)
        if not text.strip():
            continue
        n += 1
        r = by_block.get(bid)
        aid = r.id if r else f"AC-{n}"
        ev = {"block_id": bid, "start": 0, "end": len(text.rstrip()), "quote": text.rstrip()}
        items.append(Acc(aid, r.label if r else f"Приёмка №{n}", bid, text.rstrip(), 0, {"expected": ev}, ev, r.id if r else None))
    return items


# =============================================================== пропущенные страницы

_MISSING_RX = re.compile(r"(?:страниц\w*|page|стр\.)\s*№?\s*(\d+)", re.I)
_MISSING_WORDS = re.compile(r"пропущ|не извлеч|не распозн|не прочит|ошибк|missing|failed|skipp|unreadable|empty", re.I)


def partial_read(view: DocView) -> list[str]:
    """Предупреждения документа с кодами неполного чтения (контракт v1, PARTIAL_READ_CODES)."""
    out = []
    for w in view.warnings():
        d = as_dict(w) if not isinstance(w, str) else {}
        if d.get("code") in PARTIAL_READ_CODES:
            out.append(f"{d['code']}: {d.get('message', '')}".strip(": "))
    return out


def missing_pages(view: DocView) -> list[int]:
    pages: set[int] = set()
    for w in view.warnings():
        d = as_dict(w) if not isinstance(w, str) else {}
        if d:
            code = str(d.get("code") or d.get("kind") or "")
            pg = d.get("page") or d.get("pages")
            if pg is not None and (code in PARTIAL_READ_CODES or
                                   re.search(r"page|страниц|missing|пропуск", code + " " + str(d.get("message", "")), re.I)):
                for p in (pg if isinstance(pg, (list, tuple)) else [pg]):
                    try:
                        pages.add(int(p))
                    except (TypeError, ValueError):
                        pass
            continue
        s = str(w)
        if _MISSING_WORDS.search(s):
            for m in _MISSING_RX.finditer(s):
                pages.add(int(m.group(1)))
    seen = sorted({sp[1] for bid in view.ids if (sp := view.lines(bid)) and sp[0] == "page"}
                  | {sp[2] for bid in view.ids if (sp := view.lines(bid)) and sp[0] == "page"})
    if seen:
        full = set(range(seen[0], seen[-1] + 1))
        pages |= full - set(seen)
    return sorted(pages)


# =============================================================== проверка witness

_NEG = re.compile(r"(?<![а-яa-z])(не|нет|без|ни|никогда|отсутств\w*)(?![а-яa-z])", re.I)
_ANTONYMS = [("приня", "откло"), ("успеш", "ошиб"), ("разре", "запре"), ("включ", "выклю"), ("допус", "недоп"),
             ("отпра", "подав"), ("увели", "умень"), ("ok", "error")]


def _same_value(a: Any, b: Any) -> bool:
    ma, mb = parse_money(str(a)), parse_money(str(b))
    if ma and mb:
        return ma[2] == mb[2]
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na == nb
    mma, mmb = month_mentions(str(a)), month_mentions(str(b))
    if mma and mmb:
        return {m[0] for m in mma} == {m[0] for m in mmb}
    return norm(strip_md(a)).strip(' ."«»') == norm(strip_md(b)).strip(' ."«»')


def _num(x: Any) -> Optional[Decimal]:
    s = norm(strip_md(x))
    m = re.fullmatch(r"-?\d[\d ]*(?:[.,]\d+)?", s)
    return parse_num(s) if m else None


def outcomes_incompatible(w: dict) -> tuple[bool, str]:
    va, vb = w.get("outcome_a_value"), w.get("outcome_b_value")
    if va not in (None, "") and vb not in (None, ""):
        if _same_value(va, vb):
            return False, f"значения исходов совпадают ({va} = {vb})"
        return True, f"разные значения одного исхода: {va} ≠ {vb}"
    ta, tb = str(w.get("outcome_a") or ""), str(w.get("outcome_b") or "")
    if not ta.strip() or not tb.strip():
        return False, "исход не указан"
    if _same_value(ta, tb):
        return False, "исходы совпадают"
    ka, kb = key_set(_NEG.sub(" ", ta)), key_set(_NEG.sub(" ", tb))
    jac = len(ka & kb) / max(1, len(ka | kb))
    na, nb = len(_NEG.findall(ta)), len(_NEG.findall(tb))
    if jac >= 0.5 and (na % 2) != (nb % 2):
        return True, "исходы противоположны по полярности"
    ka_all, kb_all = keys_of(ta), keys_of(tb)
    for x, y in _ANTONYMS:
        if (any(k.startswith(x) for k in ka_all) and any(k.startswith(y) for k in kb_all)) or \
                (any(k.startswith(y) for k in ka_all) and any(k.startswith(x) for k in kb_all)):
            return True, f"исходы-антонимы ({x}… / {y}…)"
    ma, mb = {m[0] for m in month_mentions(ta)}, {m[0] for m in month_mentions(tb)}
    if ma and mb and ma.isdisjoint(mb):
        return True, "исходы относят событие к разным периодам"
    return False, "несовместимость исходов не установлена механически"


def _var(s: Any) -> str:
    return re.sub(r"[^\w]+", " ", norm(s)).strip()


def _scalar(v: Any) -> tuple[str, Any]:
    m = parse_money(str(v))
    if m:
        return "money", m[2]
    n = _num(v)
    if n is not None:
        return "num", n
    return "str", norm(strip_md(v)).strip(' ."«»')


def eval_constraint(c: dict, assign: dict, fs: FactSet) -> Optional[bool]:
    """Одно ограничение предусловия на witness-входе: True/False или None (не вычислимо)."""
    var = _var(c.get("var"))
    op = norm(c.get("op") or "eq")
    val = c.get("value")
    if var not in assign:
        cand = [k for k in assign if key_set(k) and key_set(k) == key_set(var)]
        if len(cand) != 1:
            return None
        var = cand[0]
    x = assign[var]
    if isinstance(val, str) and val.startswith("$"):
        ref = _var(val[1:])
        if ref not in assign:
            return None
        val = assign[ref]
    if isinstance(val, str) and val.startswith("range:"):
        fid = val.split(":", 1)[1].strip()
        f = fs.by_id().get(fid)
        if f is None or not f.range:
            return None
        kind, xv = _scalar(x)
        if kind == "num" and f.unit in ("KZT", "tiyn"):
            xv = xv * (100 if f.unit == "KZT" else 1)
            kind = "money"
        if kind not in ("num", "money"):
            return None
        money = f.unit in ("KZT", "tiyn")
        lo = Decimal(f.range["min_minor"]) if money and f.range.get("min_minor") is not None else Decimal(f.range["min"])
        hi = Decimal(f.range["max_minor"]) if money and f.range.get("max_minor") is not None else Decimal(f.range["max"])
        xv = Decimal(xv)
        inside = (xv >= lo if f.range.get("min_inclusive") is not False else xv > lo) and \
                 (xv <= hi if f.range.get("max_inclusive") is not False else xv < hi)
        if op in ("in", "inside", "between", "within"):
            return inside
        if op in ("outside", "not_in", "not_between"):
            return not inside
        return None
    if op in ("true", "is_true"):
        return _scalar(x)[1] in ("да", "true", "1", "yes", "истина")
    if op in ("false", "is_false"):
        return _scalar(x)[1] in ("нет", "false", "0", "no", "ложь")
    if op in ("in", "not_in"):
        items = val if isinstance(val, list) else re.split(r"\s*[|,;]\s*", str(val))
        hit = any(_same_value(x, it) for it in items)
        return hit if op == "in" else not hit
    if op in ("between", "outside"):
        m = re.match(r"\s*(.+?)\s*\.\.\s*(.+)\s*$", str(val))
        if not m:
            return None
        k1, lo = _scalar(m.group(1))
        k2, hi = _scalar(m.group(2))
        kx, xv = _scalar(x)
        if not (k1 == k2 == kx and kx in ("num", "money")):
            return None
        inside = lo <= xv <= hi
        return inside if op == "between" else not inside
    kx, xv = _scalar(x)
    kv, vv = _scalar(val)
    if op in ("eq", "=", "==", "ne", "!=", "neq"):
        same = (xv == vv) if kx == kv else _same_value(x, val)
        return same if op in ("eq", "=", "==") else not same
    if op in ("lt", "le", "gt", "ge", "<", "<=", ">", ">="):
        if kx != kv or kx not in ("num", "money"):
            return None
        return {"lt": xv < vv, "<": xv < vv, "le": xv <= vv, "<=": xv <= vv,
                "gt": xv > vv, ">": xv > vv, "ge": xv >= vv, ">=": xv >= vv}[op]
    if op == "contains":
        return norm(val) in norm(x)
    return None


# =============================================================== основной анализ

ROLE_RU = {
    "business_rules": "бизнес-правила", "acceptance": "приёмка", "ui": "UI", "integration": "интеграция",
    "api": "API", "data": "данные", "nfr": "НФТ", "process": "процесс", "goals": "цели", "general": "общие сведения",
    "testing": "тестирование", "other": "прочее",
}
CROSS_PASS = [
    ("business_rules", "acceptance"), ("business_rules", "business_rules"), ("business_rules", "ui"),
    ("business_rules", "integration"), ("business_rules", "api"), ("business_rules", "data"),
    ("business_rules", "nfr"), ("ui", "api"), ("integration", "api"), ("ui", "integration"),
    ("acceptance", "api"), ("acceptance", "ui"), ("data", "api"), ("api", "api"),
    ("goals", "nfr"), ("goals", "business_rules"), ("process", "business_rules"), ("process", "api"),
]
_EXCLUDED_UNIT_ROLES = {"heading", "template", "general", "testing"}


@dataclass
class Unit:
    uid: str
    group: str
    block_id: str
    text: str
    hint: dict
    req_id: Optional[str]
    label: str
    keys: set = dc_field(default_factory=set)
    nums: set = dc_field(default_factory=set)
    timey: bool = False


def _load_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _load_schema(stage: str) -> dict:
    p = PROMPTS_DIR / "cross.schema.json"
    stage = stage.replace(".", "#")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get(stage, {"type": "object"})
        except ValueError:
            pass
    return {"type": "object"}


class CrossReview:
    def __init__(self, document: Any, requirements: Any, ask: Optional[Callable], fact_hints: Any,
                 resolve: Optional[Callable], max_pairs: int, pairs_per_call: int):
        self.view = DocView(document)
        self.ask = ask
        self.warnings: list[str] = []
        self.audit = Audit()
        self.fs = extract_facts(document, fact_hints, resolve=resolve, view=self.view, audit=self.audit)
        self.resolver = self.fs.resolver
        self.warnings += self.fs.warnings
        self.reqs = _norm_requirements(self.view, requirements, self.warnings)
        self.acc = _acceptance(self.view, self.fs, self.reqs)
        acc_blocks = {a.block_id for a in self.acc}
        self.cov_excluded: list[dict] = []
        self.obls = _obligations(self.view, self.reqs, acc_blocks, self.cov_excluded)
        self.block_reqs: dict[str, list[str]] = {}
        for r in self.reqs:
            for b in r.block_ids:
                if b not in acc_blocks or len(r.block_ids) == 1:
                    self.block_reqs.setdefault(b, []).append(r.id)
        self.candidates: list[dict] = []
        self.comparisons: list[dict] = list(self.fs.comparisons)
        self.missing = missing_pages(self.view)
        self.partial = partial_read(self.view)
        self.ask_ok = 0
        self.ask_error: Optional[BaseException] = None
        self.max_pairs = max_pairs
        self.pairs_per_call = pairs_per_call
        self.stats: dict = {"mode": "rules_plus_llm" if ask else "rules_only", "llm_calls": 0, "llm_failed": []}
        self.llm_links: Optional[list] = None
        self.llm_branches: dict[str, list] = {}
        df: dict[str, int] = {}
        for bid in self.view.ids:
            for k in key_set(self.view.text(bid)):
                df[k] = df.get(k, 0) + 1
        n_blocks = max(2, len(self.view.ids))
        self.idf = {k: math.log(n_blocks / v) for k, v in df.items()}

    def idf_of(self, k: str) -> float:
        return self.idf.get(k, math.log(max(2, len(self.view.ids))))

    def link_score(self, ka: set, kb: set) -> tuple[float, set]:
        shared = ka & kb
        return sum(self.idf_of(k) for k in shared), shared

    # ----------------------------------------------------------- вспомогательное
    def req_ids_for(self, *evs: Optional[dict]) -> list[str]:
        """Требования, чьи обязательства или опоры перекрывают фрагмент; иначе — все требования блока."""
        out: list[str] = []
        for e in evs:
            sp = self._span(e)
            if not sp:
                continue
            bid, s0, e0 = sp
            hit = [o.req_id for o in self.obls if o.hint["block_id"] == bid and s0 < o.hint["end"] and o.hint["start"] < e0]
            if not hit:
                hit = [r.id for r in self.reqs for ev in r.evidence
                       if str(ev.get("block_id")) == bid and isinstance(ev.get("start"), int)
                       and s0 < ev.get("end", 0) and ev["start"] < e0]
            out += hit or self.block_reqs.get(bid, [])
        return list(dict.fromkeys(out))

    def acc_ids_for(self, *evs: Optional[dict]) -> list[str]:
        out = []
        for e in evs:
            if not e:
                continue
            for a in self.acc:
                if a.block_id == e.get("block_id") and e.get("start", 0) < a.hint["end"] and a.hint["start"] < e.get("end", 10**9):
                    out.append(a.aid)
        return list(dict.fromkeys(out))

    def log(self, aspect: str, verdict: str, explanation: str, **extra: Any) -> dict:
        c = {"id": f"CMP-{len(self.comparisons) + 1:03d}", "aspect": aspect, "verdict": verdict,
             "fact_ids": [], "explanation": explanation}
        c.update(extra)
        self.comparisons.append(c)
        return c

    def add(self, cand: dict) -> None:
        hints = [h for h in cand.get("hints", []) if h]
        if cand.get("witness"):
            sides = [cand["witness"].get("evidence_a"), cand["witness"].get("evidence_b")] + list(cand.get("binds", []))
        else:
            sides = hints
        sides = [e for e in sides if e]
        if not cand.get("req_ids"):
            cand["req_ids"] = self.req_ids_for(*sides)
        acc = self.acc_ids_for(*sides)
        if acc:
            cand.setdefault("acceptance_ids", acc)
        key = (cand.get("subkind"), tuple(sorted({(h["block_id"]) for h in hints})))
        for c in self.candidates:
            if (c.get("subkind"), tuple(sorted({h["block_id"] for h in c.get("hints", [])}))) == key:
                if cand.get("origin", "?") not in c.setdefault("confirmed_by", []):
                    c["confirmed_by"].append(cand.get("origin", "?"))
                if cand.get("slots") and not c.get("slots"):
                    c["slots"] = cand["slots"]
                return
        cand.setdefault("ref", f"X-{len(self.candidates) + 1:02d}")
        self.candidates.append(cand)

    # ----------------------------------------------------------- граница периода
    _ANCHOR = re.compile(
        r"(?P<unit>расч[её]тн\w*\s+период\w*|период\w*|месяц\w*|квартал\w*|дат[аы]|день|сутк\w*|год\w*|"
        r"ставк\w*|тариф\w*|курс\w*|комисси\w*|цен[аы])"
        r"(?P<qual>[^.;]{0,80}?)\s+определя\w*\s+по\s+(?:дате|дню|времени|моменту)\s+(?P<rest>[^.;]+)",
        re.I,
    )
    _TZ_TAIL = re.compile(r"\s+(?:в|по)\s+(?:времени\s+|поясу\s+)?(?P<tz>[A-Za-zА-Яа-яЁё][\w\-/]*(?:\s*[+\-−]\s*\d{1,2})?)\s*$")

    def anchors(self) -> list[dict]:
        out = []
        for bid in self.view.ids:
            if self.view.group(bid) in ("acceptance", "template", "heading", "testing"):
                continue
            text = self.view.text(bid)
            for m in self._ANCHOR.finditer(text):
                rest = m.group("rest").rstrip()
                tz = None
                mt = self._TZ_TAIL.search(rest)
                event = rest
                if mt and tz_offset(mt.group("tz")) is not None:
                    tz = mt.group("tz")
                    event = rest[: mt.start()]
                unit = norm(m.group("unit"))
                gran = ("month" if unit.startswith(("месяц", "период", "расч")) else "quarter" if unit.startswith("квартал")
                        else "year" if unit.startswith("год") else "day" if unit.startswith(("дат", "день", "сутк")) else "value")
                sent = next(((a, b) for a, b in sentence_spans(text) if a <= m.start() < b), (m.start(), m.end()))
                prefix = text[sent[0]: m.start()]
                prefix = prefix[_strip_prefix(prefix):]
                cond = set()
                if re.match(r"^\s*(для|при|у|в случае|если)\b", norm(prefix)):
                    cond |= key_set(prefix)
                cond |= key_set(m.group("qual"))
                lead = re.findall(r"[A-Za-zА-Яа-яЁё]+", prefix)
                obj = text[m.start("unit"): m.end("qual")].strip(" ,")
                if lead and _is_adj(lead[-1]):
                    obj = f"{lead[-1]} {obj}"
                out.append({
                    "block_id": bid, "unit": unit, "gran": gran, "cond": cond, "event": event.strip(),
                    "event_keys": key_set(event), "tz": tz, "offset": tz_offset(tz),
                    "ev": {"block_id": bid, "start": sent[0], "end": sent[1], "quote": text[sent[0]:sent[1]]},
                    "unit_key": keys_of(m.group("unit"))[:1],
                    "object": obj[:1].upper() + obj[1:],
                })
        return out

    def dated_rules(self) -> list[dict]:
        """«до 30 июня включительно — 1 %», «с 1 июля — 2 %»: интервалы со значением."""
        out = []
        mon = r"\d{1,2}\s+(?:январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])(?:\s+\d{4})?"
        for bid in self.view.ids:
            if self.view.group(bid) in ("acceptance", "template", "heading", "testing"):
                continue
            text = self.view.text(bid)
            for a, b in sentence_spans(text):
                s = text[a:b]
                since = re.search(rf"(?:^|\s)(?:с|со|начиная\s+с)\s+({mon})", s, re.I)
                until = re.search(rf"(?:^|\s)(?:до|по)\s+({mon})(\s+включительно)?", s, re.I)
                val = re.search(r"(\d+(?:[.,]\d+)?)\s*%", s) or re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(₸|тенге|тиын\w*)", s)
                if not (since or until) or not val:
                    continue
                lo = find_stamps(since.group(1))[0] if since else None
                hi = find_stamps(until.group(1))[0] if until else None
                out.append({
                    "block_id": bid, "lo": lo, "hi": hi, "hi_incl": bool(until and until.group(2)) if until else None,
                    "value": val.group(0).strip(), "keys": key_set(s),
                    "ev": {"block_id": bid, "start": a, "end": b, "quote": s},
                })
        return out

    @staticmethod
    def _in_interval(dt, rule: dict) -> Optional[bool]:
        lo, hi = rule["lo"], rule["hi"]
        if lo is not None:
            l_dt = lo.in_offset(None).replace(year=dt.year)
            if dt < l_dt:
                return False
        if hi is not None:
            h_dt = hi.in_offset(None).replace(year=dt.year)
            if dt.date() > h_dt.date():
                return False
            if dt.date() == h_dt.date() and rule["hi_incl"] is not True:
                return None if rule["hi_incl"] is None else False
        return True

    @staticmethod
    def _clause(text: str, st: Stamp) -> str:
        before = text[: st.start]
        cut = max(before.rfind(ch) for ch in "|:;,.\n")
        return before[cut + 1:]

    _EVENTISH = re.compile(r"(ть|ти|ен|ена|ено|ены|ан|ана|ано|аны|ён|ёна|ит|ет|ют|ут|ят|ал|ил|ел|ла|ло|ли)$")

    def _event_score(self, anc: dict, text: str, st: Stamp) -> int:
        """Сколько клауза метки говорит о событии правила: главное слово ×2, прочие ×1, чужое событие −1."""
        ek = keys_of(anc["event"])
        if not ek:
            return 0
        clause = self._clause(text, st)
        ck = set(keys_of(clause))
        primary = ek[0]
        score = (2 if primary in ck else 0) + len(set(ek[1:]) & ck)
        if primary not in ck and any(self._EVENTISH.search(w.lower()) for w in re.findall(r"[А-Яа-яЁё]{4,}", clause)):
            score -= 1
        return score

    def period_checks(self) -> None:
        anchors = self.anchors()
        dated = self.dated_rules()
        self._missing_anchor(anchors, dated)
        if not anchors:
            return
        # P2: два правила привязки к разным событиям для одного объекта
        for i, a in enumerate(anchors):
            for b in anchors[i + 1:]:
                if a["gran"] != b["gran"] or a["unit_key"] != b["unit_key"]:
                    continue
                if a["event_keys"] == b["event_keys"] or not (a["event_keys"] and b["event_keys"]):
                    continue
                if a["cond"] != b["cond"]:
                    self.log("period_anchor", "compatible",
                             f"«{a['ev']['quote']}» и «{b['ev']['quote']}» привязаны к разным событиям, но при разных "
                             f"условиях ({', '.join(sorted(a['cond'] - b['cond'])) or '—'} / "
                             f"{', '.join(sorted(b['cond'] - a['cond'])) or '—'}): общего входа нет.",
                             evidence=[a["ev"], b["ev"]])
                    continue
                self._p2_conflict(a, b)
        # P1: правило привязки против примера приёмки
        for anc in anchors:
            siblings = [x for x in anchors if x is not anc and x["gran"] == anc["gran"] and x["unit_key"] == anc["unit_key"]]
            for acc in self.acc:
                if not self._applies(anc, siblings, acc):
                    continue
                self._p1(anc, acc, dated)

    def _applies(self, anc: dict, siblings: list, acc: Acc) -> bool:
        pre = acc.cells.get("pre", acc.hint)["quote"]
        subject = re.split(r"[:,\d]", strip_md(pre), maxsplit=1)[0]
        subj_keys = key_set(subject)
        head = (keys_of(subject) or [None])[0]
        own = anc["cond"] - set().union(*[s["cond"] for s in siblings]) if siblings else set()
        others = set().union(*[s["cond"] - anc["cond"] for s in siblings]) if siblings else set()
        if head and head in own | others:
            return head in own  # «Возврат покупки»: тип операции задаёт главное слово, а не дополнение
        if not anc["cond"]:
            return not any((s["cond"] - anc["cond"]) & subj_keys for s in siblings)
        disc = anc["cond"] - set().union(*[s["cond"] for s in siblings]) if siblings else set()
        if disc:
            return bool(disc & subj_keys)
        return anc["cond"] <= key_set(acc.text)

    def _p1(self, anc: dict, acc: Acc, dated: list) -> None:
        text = acc.text
        stamps = find_stamps(text)
        if len(stamps) < 2:
            return
        scored = [(self._event_score(anc, text, st), st) for st in stamps]
        best = max(s for s, _ in scored)
        tops = [st for s, st in scored if s == best]
        if best <= 0 or len(tops) != 1:
            if best <= 0:
                return
            self.log("period", "undetermined", f"{acc.label}: несколько моментов подходят под «{anc['event']}».")
            return
        a_st = tops[0]
        others = [st for _, st in scored if st is not a_st]
        off = anc["offset"] if anc["offset"] is not None else a_st.offset
        a_dt = a_st.in_offset(off)
        o_dts = [(o, o.in_offset(off)) for o in others]
        exp_ev = acc.cells.get("expected") or acc.hint
        exp_text = exp_ev["quote"]
        bid = acc.block_id
        mk = lambda st: {"block_id": bid, "start": acc.base + st.start, "end": acc.base + st.end,  # noqa: E731
                         "quote": self.view.text(bid)[acc.base + st.start: acc.base + st.end]}
        if anc["gran"] == "month":
            ms = {m[0] for m in month_mentions(exp_text)}
            if len(ms) != 1:
                return
            exp_m = ms.pop()
            if exp_m == a_dt.month:
                self.log("period", "compatible", f"{acc.label}: «{exp_text}» соответствует правилу «{anc['ev']['quote']}» "
                         f"(момент «{anc['event']}» — {a_st.text} → {MONTH_NAMES[a_dt.month]}).")
                return
            if not any(dt.month == exp_m for _, dt in o_dts):
                return
            outcome_a = (f"событие относится к периоду «{MONTH_NAMES[a_dt.month]}»: момент «{anc['event']}» — {a_st.text}")
            outcome_b = f"событие учтено в периоде «{MONTH_NAMES[exp_m]}»: «{strip_md(exp_text)}»"
            self._period_conflict(anc, acc, a_st, others, off, outcome_a, outcome_b, anc["ev"], exp_ev, mk,
                                  values=(MONTH_NAMES[a_dt.month], MONTH_NAMES[exp_m]), support=[])
            return
        # ставка/тариф: значение по датированным правилам
        rel = [r for r in dated if (set(anc["unit_key"]) & r["keys"]) or (anc["cond"] & r["keys"])]
        if not rel:
            return
        exp_val = re.search(r"(\d+(?:[.,]\d+)?)\s*%", exp_text) or re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(₸|тенге)", exp_text)
        if not exp_val:
            return
        a_rules = [r for r in rel if self._in_interval(a_dt, r) is True]
        if len(a_rules) != 1 or any(self._in_interval(a_dt, r) is None for r in rel):
            return
        v_a = a_rules[0]["value"]
        if _same_value(v_a, exp_val.group(0)):
            self.log("period", "compatible", f"{acc.label}: значение {exp_val.group(0)} соответствует «{a_rules[0]['ev']['quote']}».")
            return
        b_rules = [r for r in rel if _same_value(r["value"], exp_val.group(0)) and any(self._in_interval(dt, r) for _, dt in o_dts)]
        if not b_rules:
            return
        outcome_a = (f"{v_a} — по правилу для момента «{anc['event']}» ({a_st.text})")
        outcome_b = f"{exp_val.group(0)} — «{strip_md(exp_text)}»"
        self._period_conflict(anc, acc, a_st, others, off, outcome_a, outcome_b, a_rules[0]["ev"], exp_ev, mk,
                              values=(v_a, exp_val.group(0)), support=[anc["ev"], b_rules[0]["ev"]])

    def _period_conflict(self, anc, acc, a_st, others, off, outcome_a, outcome_b, ev_a, ev_b, mk, values, support) -> None:
        doc = [{"name": f"момент «{anc['event']}»", "value": a_st.text, "evidence": mk(a_st)}]
        doc += [{"name": "другой момент того же события", "value": o.text, "evidence": mk(o)} for o in others]
        pre = acc.cells.get("pre")
        if pre:
            ms = find_money(pre["quote"])
            if ms:
                s0, e0 = pre["start"] + ms[0], pre["start"] + ms[1]
                doc.append({"name": "сумма", "value": pre["quote"][ms[0]:ms[1]],
                            "evidence": {"block_id": pre["block_id"], "start": s0, "end": e0, "quote": pre["quote"][ms[0]:ms[1]]}})
        illus = []
        if a_st.offset is None and off is not None:
            illus.append({"name": "пояс времени момента", "value": f"{anc['tz']} (UTC{off:+d})",
                          "why": f"у «{a_st.text}» пояс не указан; правило считает по «{anc['tz']}», и формулировка "
                                 f"примера допускает это прочтение — значит, такой вход удовлетворяет обоим текстам"})
        witness = {
            "input": {"description": f"Событие из {acc.label}: " + "; ".join(x["value"] for x in doc[: 1 + len(others)]),
                      "document_data": doc, "illustrative": illus},
            "outcome_a": outcome_a, "outcome_b": outcome_b,
            "outcome_a_value": values[0], "outcome_b_value": values[1],
            "evidence_a": ev_a, "evidence_b": ev_b,
        }
        cmp = self.log("period", "mismatch", f"{acc.label} противоречит правилу «{anc['ev']['quote']}» на границе периода.")
        labels = {r.id: r.label for r in self.reqs}
        a_label = "; ".join(labels.get(x, x) for x in self.req_ids_for(ev_a, anc["ev"])) or "правило"
        note = ""
        if a_st.offset is None:
            note = (f" Без пояса у «{a_st.text}» пример можно прочитать иначе (например, в UTC), но и тогда "
                    f"текст не фиксирует пояс — исправление требует явной зоны.")
        self.add(make_candidate(
            "conflict",
            f"{acc.label} противоречит правилу периода ({a_label}): событие на стыке периодов",
            f"Для одного события ({a_st.text} и {', '.join(o.text for o in others)}) правило и приёмка дают разные "
            f"исходы: {values[0]} и {values[1]}. Разработчик и тестировщик реализуют разное поведение.{note}",
            [ev_a, ev_b] + support, witness=witness, origin="rules", comparison_id=cmp["id"],
            binds=[anc["ev"]], support=support,
            checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
            slots={
                "a": {"object": anc["unit"], "owner": None, "condition": "; ".join(sorted(anc["cond"])) or "все события",
                      "moment": f"момент «{anc['event']}»", "units": anc["tz"], "expected": values[0]},
                "b": {"object": strip_md(acc.cells.get("expected", acc.hint)["quote"]), "owner": None,
                      "condition": strip_md((acc.cells.get("pre") or acc.hint)["quote"]),
                      "moment": "; ".join(s.text for s in [a_st, *others]), "units": None, "expected": values[1]},
            },
        ))

    def _p2_conflict(self, a: dict, b: dict) -> None:
        illus = [
            {"name": f"момент «{a['event']}»", "value": "31 января в 23:58", "why": "последняя минута периода"},
            {"name": f"момент «{b['event']}»", "value": "1 февраля в 00:03", "why": "первая минута следующего периода"},
        ]
        witness = {
            "input": {"description": "Одно событие, у которого моменты приходятся на разные периоды",
                      "document_data": [], "illustrative": illus},
            "outcome_a": f"период «январь» по «{a['ev']['quote']}»",
            "outcome_b": f"период «февраль» по «{b['ev']['quote']}»",
            "outcome_a_value": "январь", "outcome_b_value": "февраль",
            "evidence_a": a["ev"], "evidence_b": b["ev"],
        }
        obj = a["object"]
        wa, wb = self._where(a["ev"]), self._where(b["ev"])
        cmp = self.log("period_anchor", "mismatch",
                       f"«{obj}» привязан к разным событиям при одинаковых условиях: «{a['event']}» ({wa}) и «{b['event']}» ({wb}).")
        self.add(make_candidate(
            "conflict", f"{obj} определяется по разным датам: «{a['event']}» и «{b['event']}»",
            f"Операция с моментом «{a['event']}» 31 января в 23:58 и моментом «{b['event']}» 1 февраля в 00:03 "
            f"по {wa} относится к январю, по {wb} — к февралю. От выбора зависят месяц начисления и правило, "
            f"которое к ней применяется; тест на стык месяцев нельзя написать однозначно.",
            [a["ev"], b["ev"]], witness=witness, origin="rules", comparison_id=cmp["id"], cause_object=obj,
            blocked_decision=(f"по какой дате относить операцию к периоду «{obj.lower()}» — «{a['event']}» или "
                              f"«{b['event']}» — и какой месяц ожидать в тесте на стыке"),
            recommendation=f"Оставить одно правило для «{obj.lower()}» (одну дату и часовой пояс) и исправить второе место.",
            places=[{"where": wa, **a["ev"]}, {"where": wb, **b["ev"]}],
            checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
        ))

    def _where(self, ev: dict) -> str:
        """«КЭШ-2 (Функциональные требования, строка 7)»: требование, раздел и место в исходнике."""
        labels = {r.id: r.label for r in self.reqs}
        rids = [labels.get(x, x) for x in self.req_ids_for(ev)]
        sec = self.view.section(ev["block_id"])
        sp = self.view.lines(ev["block_id"])
        loc = ""
        if sp:
            loc = (f"строка {sp[1]}" if sp[1] == sp[2] else f"строки {sp[1]}–{sp[2]}") if sp[0] == "line" else f"стр. {sp[1]}"
        place = ", ".join(x for x in (strip_md(sec[-1]) if sec else "", loc) if x)
        return f"{', '.join(rids)} ({place})" if rids else place

    # ----------------------------------------------------------- нет правила привязки при смене правила на границе
    _GOVERNED = re.compile(r"(ставк\w*|тариф\w*|комисси\w*|кэшб[эе]к\w*|кешб[эе]к\w*|лимит\w*|цен[аы]\w*)(\s+[а-яё]+)?", re.I)
    _DATE_KINDS = re.compile(r"дат\w*\s+(совершени\w*|проведени\w*|списани\w*|авторизаци\w*|клиринг\w*|зачислени\w*)", re.I)

    def _missing_anchor(self, anchors: list, dated: list) -> None:
        """Значение меняется на границе дат («до 31 марта — 1 %», «с 1 апреля — 2 %»), но правила, по какой
        дате относить событие к периоду, нет, а событие в документе имеет моменты по разные стороны границы."""
        if len(dated) < 2 or len({norm(r["value"]) for r in dated}) < 2:
            return
        if any(a["gran"] in ("month", "value") for a in anchors):
            return
        straddle = None
        for acc in self.acc:
            stamps = find_stamps(acc.text)
            sides = []
            for st in stamps:
                hits = [r for r in dated if self._in_interval(st.in_offset(st.offset), r) is True]
                sides.append(tuple(sorted({norm(r["value"]) for r in hits})))
            if len(stamps) >= 2 and all(sides) and len(set(sides)) > 1:
                straddle = (acc, stamps, sides)
                break
        kinds_ev = []
        for bid in self.view.ids:
            if self.view.group(bid) in ("template", "heading", "testing"):
                continue
            t = self.view.text(bid)
            for m in self._DATE_KINDS.finditer(t):
                kinds_ev.append((norm(m.group(1))[:6], {"block_id": bid, "start": m.start(), "end": m.end(), "quote": t[m.start():m.end()]}))
        if straddle is None and len({k for k, _ in kinds_ev}) < 2:
            return
        gm = self._GOVERNED.search(dated[0]["ev"]["quote"])
        obj = (gm.group(0).strip() if gm else "значение правила").lower()
        rule_hints = [r["ev"] for r in dated]
        inspected = [b for b in self.view.ids if self.view.role.get(b) not in ("heading", "template")
                     and self.view.group(b) not in ("acceptance", "testing")]
        sections = list(dict.fromkeys(" / ".join(strip_md(x) for x in self.view.section(b)[1:]) or self.view.scope(b)
                                      for b in inspected))
        spans = [s for s in (self.view.lines(b) for b in inspected) if s]
        span = None
        if spans:
            kind = "строки" if spans[0][0] == "line" else "страницы"
            span = f"{kind} {min(s[1] for s in spans)}–{max(s[2] for s in spans)}"
        values = " и ".join(dict.fromkeys(r["value"] for r in dated))
        if straddle:
            acc, stamps, sides = straddle
            ev_st = [{"block_id": acc.block_id, "start": acc.base + st.start, "end": acc.base + st.end,
                      "quote": self.view.text(acc.block_id)[acc.base + st.start: acc.base + st.end]} for st in stamps]
            moments = " и ".join(f"«{st.text}»" for st in stamps)
            question = (f"По какой дате определяется {obj} на границе периода? В примере «{acc.label}» моменты {moments} "
                        f"попадают под разные значения ({values}). Какое значение применить и в каком часовом поясе "
                        f"считать границу?")
            hints = rule_hints + ev_st
            impact = (f"Для события из примера «{acc.label}» ({moments}) документ допускает оба значения: {values}. "
                      f"Разработчик и тестировщик выберут дату сами, и результаты разойдутся.")
        else:
            kinds = " и ".join(dict.fromkeys(f"«{e['quote']}»" for _, e in kinds_ev))
            question = (f"По какой дате определяется {obj} на границе периода: документ упоминает {kinds}, "
                        f"а значения разные ({values}). Какую дату брать и в каком часовом поясе?")
            hints = rule_hints + [e for _, e in kinds_ev][:2]
            impact = f"Значение «{obj}» меняется на границе дат ({values}), но не сказано, по какой дате это решать."
        self.log("period_anchor", "undetermined", f"Нет правила, по какой дате применять «{obj}»: {question}")
        self.add(make_candidate(
            "missing_rule", f"Нет правила, по какой дате определяется «{obj}» на границе периода", impact, hints,
            origin="rules", question=question, inspected_block_ids=inspected,
            inspected_scope={"sections": sections, "span": span},
            searched_for=[f"правило вида «… определяется по дате …» для «{obj}», расчётного месяца или периода",
                          "указание, к какой дате (совершения, проведения, списания) относится граница «до …» / «с …»",
                          "часовой пояс границы периода"],
            found=[f"«{r['ev']['quote']}»" for r in dated],
            blocked_decision=f"какое значение «{obj}» применить к событию на границе периода и что ожидать в тесте",
        ))

    # ----------------------------------------------------------- обещанный метод без контракта
    _OPV = {
        "read": re.compile(r"\b(чита\w*|получа\w*|запрашива\w*|загружа\w*|просматрива\w*|отобража\w*|показыва\w*|чтени\w*)", re.I),
        "write": re.compile(r"\b(сохраня\w*|изменя\w*|обновля\w*|зада[её]\w*|записыва\w*|созда[её]\w*|устанавлива\w*|сохранени\w*)", re.I),
        "delete": re.compile(r"\b(удаля\w*|удалени\w*)", re.I),
    }
    _OP_RU = {"read": "чтение", "write": "сохранение", "delete": "удаление"}
    _SEARCHED = {
        "read": ["URL или имя метода с глаголом чтения (get/read/list/fetch/load/show/find)",
                 "REST type GET у метода без глагола записи в имени",
                 "таблица параметров ответа, отдающая сохранённые данные без записи"],
        "write": ["URL или имя метода с глаголом записи (save/set/update/create)", "REST type POST/PUT/PATCH"],
        "delete": ["URL или имя метода с глаголом удаления (delete/remove)", "REST type DELETE"],
    }

    def contract_gaps(self) -> None:
        api_parts = {self.view.part[b] for b in self.view.ids if self.view.group(b) == "api"}
        api_blocks = [b for b in self.view.ids if self.view.part.get(b) in api_parts]
        eps = self.fs.endpoints
        provided = {e["op"] for e in eps if e["op"]}
        for bid in self.view.ids:
            if self.view.group(bid) not in ("integration", "business_rules", "ui"):
                continue
            text = self.view.text(bid)
            for a, b in sentence_spans(text):
                s = text[a:b]
                if not re.search(r"\bapi\b|\brest\b|метод\w* api|дочерн\w* (?:документ|спецификац)|контракт|эндпоинт|endpoint", s, re.I):
                    continue
                ops = [op for op, rx in self._OPV.items() if rx.search(s)]
                if not ops:
                    continue
                promise = {"block_id": bid, "start": a, "end": b, "quote": s}
                if not eps:
                    self.add(make_candidate(
                        "question", "Обещанный контракт не найден во входе",
                        "Требование ссылается на внешний контракт, но его описания нет в проверяемом документе.",
                        [promise], origin="rules", question=f"Где описан контракт для «{strip_md(s)}»? Он входит в состав ТЗ?",
                        inspected_block_ids=list(self.view.ids)))
                    continue
                for op in ops:
                    if op in provided:
                        continue
                    self._gap(op, promise, api_blocks, eps)

    def _gap(self, op: str, promise: dict, api_blocks: list, eps: list) -> None:
        mentions = []
        for b in api_blocks:
            t = self.view.text(b)
            m = self._OPV[op].search(t)
            if m:
                mentions.append({"block_id": b, "start": m.start(), "end": m.end(), "quote": t[m.start():m.end()]})
        ui_hints = []
        if op == "read":
            for b in self.view.ids:
                if self.view.group(b) == "ui":
                    t = self.view.text(b)
                    for a2, b2 in sentence_spans(t):
                        if re.search(r"видн|отобража|показыва|выводит", t[a2:b2], re.I):
                            ui_hints.append({"block_id": b, "start": a2, "end": b2, "quote": t[a2:b2]})
        spans = [self.view.lines(b) for b in api_blocks]
        spans = [s for s in spans if s]
        span = None
        if spans:
            kinds = {s[0] for s in spans}
            lo, hi = min(s[1] for s in spans), max(s[2] for s in spans)
            span = f"{'строки' if 'line' in kinds else 'страницы'} {lo}–{hi}"
        sections = list(dict.fromkeys(" / ".join(self.view.section(b)[1:]) for b in api_blocks if self.view.section(b)))
        found = [f"{e['method'] or '—'} {e['path']} — {self._OP_RU.get(e['op'] or '', 'операция не определена')}" for e in eps]
        if self.missing or self.partial:
            where = f"страницах {', '.join(map(str, self.missing))}" if self.missing else "непрочитанной части документа"
            self.add(make_candidate(
                "question", f"Обещано {self._OP_RU[op]}, метод не найден — но документ прочитан не полностью",
                "Нельзя утверждать отсутствие метода, пока не прочитан весь документ.",
                [promise], origin="rules", inspected_block_ids=api_blocks, missing_pages=self.missing,
                question=f"Есть ли на {where} метод для операции «{self._OP_RU[op]}»?"))
            return
        self.add(make_candidate(
            "missing_contract",
            f"Обещано {self._OP_RU[op]} через контракт, но метода для этой операции в API нет",
            f"«{strip_md(promise['quote'])}» — в описании API {('(' + span + ') ') if span else ''}найдено только: "
            f"{'; '.join(found)}. Клиент не сможет выполнить обещанную операцию, тест на неё не из чего написать.",
            [promise] + ui_hints[:2] + mentions[:2], origin="rules",
            inspected_block_ids=api_blocks,
            inspected_scope={"sections": sections, "span": span},
            searched_for=self._SEARCHED[op], found=found,
            promise=promise,
        ))

    # ----------------------------------------------------------- отбор пар
    def units(self) -> list[Unit]:
        """Единицы сравнения: требование целиком, строка приёмки, прочие блоки разделов."""
        us: list[Unit] = []
        acc_blocks = {a.block_id for a in self.acc}
        used = set(acc_blocks)
        seen_units: set = set()
        for r in self.reqs:
            bids = [b for b in r.block_ids if b not in acc_blocks and self.view.role.get(b) not in ("template", "heading")]
            if not bids:
                continue
            b0 = bids[0]
            g = self.view.group(b0)
            # атомарная нарезка: своё предложение (evidence-спан), а не весь блок, иначе пары дублируются
            spans = [e for e in r.evidence if str(e.get("block_id")) in bids and isinstance(e.get("start"), int)
                     and isinstance(e.get("end"), int)]
            if spans:
                text = "\n".join(self.view.text(str(e["block_id"]))[e["start"]:e["end"]] for e in spans)
                e0 = spans[0]
                hint = {"block_id": str(e0["block_id"]), "start": e0["start"], "end": e0["end"],
                        "quote": self.view.text(str(e0["block_id"]))[e0["start"]:e0["end"]]}
            else:
                q = self.view.text(b0).rstrip()
                text = "\n".join(self.view.text(b).rstrip() for b in bids)
                hint = {"block_id": b0, "start": 0, "end": len(q), "quote": q}
            if (b0, text) in seen_units:
                continue
            seen_units.add((b0, text))
            us.append(Unit(r.label, g if g not in ("other",) else "business_rules", b0, text, hint, r.id, r.label))
            used |= set(bids)
        for a in self.acc:
            us.append(Unit(a.aid, "acceptance", a.block_id, a.text, a.hint, a.req_id, a.label))
        n = 0
        for bid in self.view.ids:
            g = self.view.group(bid)
            if bid in used or g in _EXCLUDED_UNIT_ROLES or self.view.role.get(bid) in _EXCLUDED_UNIT_ROLES:
                continue
            text = self.view.text(bid)
            if not re.search(r"[A-Za-zА-Яа-яЁё]{3}", text):
                continue
            n += 1
            q = text.rstrip()
            us.append(Unit(f"B-{bid}", g, bid, strip_md(q), {"block_id": bid, "start": 0, "end": len(q), "quote": q},
                           (self.block_reqs.get(bid) or [None])[0], f"{ROLE_RU.get(g, g)}: {self.view.scope(bid)}"))
        for u in us:
            u.keys = key_set(u.text)
            u.nums = set(re.findall(r"\d[\d\s]{2,}\d", u.text))
            u.timey = bool(find_stamps(u.text) or month_mentions(u.text))
        return us

    def select_pairs(self, us: list[Unit]) -> list[tuple[Unit, Unit, float, str]]:
        def score(a: Unit, b: Unit) -> float:
            sc = self.link_score(a.keys, b.keys)[0]
            if a.nums & b.nums:
                sc += 1.0
            if a.timey and b.timey:
                sc += 1.0
            return sc

        def eligible(a: Unit, b: Unit) -> bool:
            if a.block_id == b.block_id:
                return False
            if a.group != b.group:
                return True
            if a.group == "business_rules":
                return a.req_id != b.req_id
            if a.group == "api":
                return self.view.section(a.block_id) != self.view.section(b.block_id)
            return False

        allp = []
        for i, a in enumerate(us):
            for b in us[i + 1:]:
                if eligible(a, b):
                    allp.append((a, b, score(a, b)))
        self.stats["pairs_considered"] = len(allp)
        chosen: dict[tuple, tuple] = {}
        # отдельный межсекционный проход: представитель каждой пары ролей
        per_role = {}
        for a, b, sc in allp:
            rp = tuple(sorted((a.group, b.group)))
            per_role.setdefault(rp, []).append((a, b, sc))
        role_set = {tuple(sorted(x)) for x in CROSS_PASS}
        for rp, lst in per_role.items():
            if rp not in role_set:
                continue
            lst.sort(key=lambda x: -x[2])
            full = (rp == ("acceptance", "business_rules") and len(lst) <= 40) or \
                (rp == ("business_rules", "business_rules") and len(lst) <= 66)
            k = len(lst) if full else 3
            for a, b, sc in lst[:k]:
                if sc > 0:
                    chosen[(a.uid, b.uid)] = (a, b, sc, "cross_section")
        # затравки из программных подсказок: вопросы фактов/правил с опорами в разных блоках
        by_block = {}
        for u in us:
            by_block.setdefault(u.block_id, u)
        for c in self.candidates:
            if c.get("subkind") != "question":
                continue
            bids = list(dict.fromkeys(h["block_id"] for h in c.get("hints", [])))
            for i, x in enumerate(bids):
                for y in bids[i + 1:]:
                    ux, uy = by_block.get(x), by_block.get(y)
                    if ux and uy and (ux.uid, uy.uid) not in chosen and (uy.uid, ux.uid) not in chosen:
                        chosen[(ux.uid, uy.uid)] = (ux, uy, self.link_score(ux.keys, uy.keys)[0], "facts_hint")
        # проход по сущностям
        T = 5.0
        for a, b, sc in sorted(allp, key=lambda x: -x[2]):
            if sc >= T and (a.uid, b.uid) not in chosen:
                chosen[(a.uid, b.uid)] = (a, b, sc, "entities")
        order = {"facts_hint": 0, "cross_section": 1, "entities": 2}
        out = sorted(chosen.values(), key=lambda x: (order[x[3]], -x[2]))
        if len(out) > self.max_pairs:
            self.warnings.append(f"Отобрано {len(out)} пар, к модели отправлено {self.max_pairs} с наибольшим весом.")
            out = out[: self.max_pairs]
        self.stats["pairs_selected"] = len(out)
        self.stats["pairs_by_role"] = {}
        for a, b, _, how in out:
            k = f"{a.group}×{b.group}"
            self.stats["pairs_by_role"][k] = self.stats["pairs_by_role"].get(k, 0) + 1
        return out

    # ----------------------------------------------------------- LLM: пары
    def _facts_brief(self) -> list[dict]:
        out = []
        for f in self.fs.facts:
            if f.source in ("status_heading",):
                continue
            out.append({k: v for k, v in {
                "id": f.id, "subject": f.subject, "field": f.field, "direction": f.direction, "type": f.type,
                "value": f.value, "range": f.range and {k2: f.range[k2] for k2 in ("min", "max", "min_inclusive", "max_inclusive")},
                "unit": f.unit, "condition": f.condition, "quote": (f.evidence or {}).get("quote"),
            }.items() if v not in (None, [], "")})
        return out

    def _call(self, stage: str, payload: dict) -> Optional[dict]:
        self.stats["llm_calls"] += 1
        try:
            res = self.ask(stage, payload, _load_schema(stage))
        except Exception as exc:  # noqa: BLE001 — сбой модели не должен ронять детерминированный анализ
            if type(exc).__name__ in ("AskError", "BudgetExhausted") or any(
                    c.__name__ == "AskError" for c in type(exc).__mro__):
                self.ask_error = exc
            self.stats["llm_failed"].append(stage)
            self.warnings.append(f"{stage}: обращение к модели не удалось ({type(exc).__name__}: {exc}); "
                                 f"результат построен по правилам.")
            return None
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except ValueError:
                res = None
        if not isinstance(res, dict):
            self.stats["llm_failed"].append(stage)
            self.warnings.append(f"{stage}: ответ модели не является объектом JSON.")
            return None
        self.ask_ok += 1
        return res

    def llm_pairs(self, pairs: list) -> None:
        if not self.ask or not pairs:
            return
        doc_blocks = [{"block_id": b, "section": " / ".join(self.view.section(b)), "text": self.view.text(b)}
                      for b in self.view.ids if self.view.role.get(b) not in ("template",)]
        small = sum(len(x["text"]) for x in doc_blocks) <= 60_000
        index = {}
        for start in range(0, len(pairs), self.pairs_per_call):
            batch = pairs[start: start + self.pairs_per_call]
            items = []
            for j, (a, b, sc, how) in enumerate(batch, start + 1):
                pid = f"P-{j:03d}"
                index[pid] = (a, b)
                items.append({"pair_id": pid, "selected_by": how,
                              "a": {"block_id": a.block_id, "label": a.label, "role": ROLE_RU.get(a.group, a.group), "text": a.text},
                              "b": {"block_id": b.block_id, "label": b.label, "role": ROLE_RU.get(b.group, b.group), "text": b.text}})
            block_ids = list(dict.fromkeys(x for it in items for x in (it["a"]["block_id"], it["b"]["block_id"])))
            payload = {
                "task": _load_prompt("cross.pairs.md"),
                "input": {"document_title": get(self.view.document, "title"), "facts": self._facts_brief(),
                          "pairs": items, "blocks": None if small else
                          [x for x in doc_blocks if x["block_id"] in set(block_ids)]},
                "context": {"mode": "auto", "block_ids": block_ids},
            }
            res = self._call(STAGE_PAIRS, payload)
            if not res:
                continue
            for r in res.get("pairs") or []:
                r = as_dict(r)
                pr = index.get(str(r.get("pair_id")))
                if pr is None:
                    self.warnings.append(f"{STAGE_PAIRS}: неизвестный pair_id {r.get('pair_id')!r} пропущен.")
                    continue
                self.handle_pair(r, *pr)

    def handle_pair(self, r: dict, a: Unit, b: Unit) -> None:
        verdict = norm(r.get("verdict"))
        slots = {"a": _slots(r.get("a")), "b": _slots(r.get("b"))}
        if verdict in ("unrelated", ""):
            return
        if verdict == "compatible":
            self.log("semantic", "compatible", f"{a.label} ↔ {b.label}: {r.get('reason') or 'модель: совместимо'}",
                     units=[a.uid, b.uid])
            return
        if verdict == "gap":
            promise = self.resolver(self._hint_or(r.get("promise"), a.block_id, as_dict(r.get("a")).get("quote") or a.hint["quote"]))
            if promise is None:
                return
            sub = "missing_contract" if b.group == "api" else "missing_rule"
            inspected = [x for x in self.view.ids if self.view.group(x) == b.group and self.view.role.get(x) != "heading"]
            self.add(make_candidate(
                sub, str(r.get("title") or f"Обещание без опоры в разделе «{ROLE_RU.get(b.group, b.group)}»: {a.label}"),
                str(r.get("impact") or "Обещанное не описано в просмотренном разделе."), [promise], origin="llm",
                inspected_block_ids=inspected, searched_for=[x for x in (r.get("searched_for") or []) if x],
                promise=promise, slots=slots, question=str(r.get("question") or "") or None))
            return
        status, details = self.verify(r, a, b)
        if status == "verified":
            w = details["witness"]
            self.add(make_candidate(
                "conflict", str(r.get("title") or f"{a.label} ↔ {b.label}: несовместимые исходы"),
                str(r.get("impact") or f"Для одного входа {a.label} и {b.label} требуют разного."),
                [w["evidence_a"], w["evidence_b"]], witness=w, origin="llm", slots=slots, checks=details["checks"]))
        elif status == "disjoint":
            self.log("semantic", "compatible",
                     f"{a.label} ↔ {b.label}: модель предложила конфликт, но условия не пересекаются ({details['reason']}).",
                     units=[a.uid, b.uid])
        else:
            hints = [h for h in (details.get("evidence_a"), details.get("evidence_b")) if h] or [a.hint, b.hint]
            q = r.get("question") or (
                f"Возможна ли ситуация, где одновременно «{slots['a'].get('condition') or a.text}» и "
                f"«{slots['b'].get('condition') or b.text}»? Если да, какой исход верен: "
                f"«{as_dict(r.get('witness')).get('outcome_a') or slots['a'].get('expected')}» или "
                f"«{as_dict(r.get('witness')).get('outcome_b') or slots['b'].get('expected')}»?")
            self.add(make_candidate(
                "question", str(r.get("title") or f"{a.label} ↔ {b.label}: требуется уточнение"),
                str(r.get("impact") or "Без уточнения реализация и тест могут выбрать разные исходы."),
                hints, origin="llm", question=q, reason=details.get("reason"), slots=slots,
                condition_a=slots["a"].get("condition"), condition_b=slots["b"].get("condition")))

    @staticmethod
    def _hint_or(h: Any, block_id: str, quote: Any) -> dict:
        d = as_dict(h)
        if d.get("quote"):
            return {"block_id": d.get("block_id") or block_id, "quote": d["quote"]}
        return {"block_id": block_id, "quote": str(quote or "")}

    def verify(self, r: dict, a: Unit, b: Unit) -> tuple[str, dict]:
        w = as_dict(r.get("witness"))
        sa, sb = as_dict(r.get("a")), as_dict(r.get("b"))
        if not (w.get("input") or w.get("outcome_a") or w.get("outcome_b")):
            return "unverified", {"evidence_a": None, "evidence_b": None, "reason": "модель не построила witness"}
        ha = self._hint_or(w.get("evidence_a"), a.block_id, sa.get("quote"))
        hb = self._hint_or(w.get("evidence_b"), b.block_id, sb.get("quote"))
        ev_a = self.resolver(ha) if ha["quote"] else None
        ev_b = self.resolver(hb) if hb["quote"] else None
        out: dict = {"evidence_a": ev_a, "evidence_b": ev_b}
        if ev_a is None or ev_b is None:
            return "unverified", {**out, "reason": "одна из опор не найдена в тексте текущего входа"}
        if (ev_a["block_id"], ev_a["start"], ev_a["end"]) == (ev_b["block_id"], ev_b["start"], ev_b["end"]):
            return "unverified", {**out, "reason": "обе стороны опираются на один и тот же фрагмент"}
        doc_items, illus, assign = [], [], {}
        for it in w.get("input") or []:
            it = as_dict(it)
            var, val = it.get("var"), it.get("value")
            if not var:
                continue
            assign[_var(var)] = val
            if norm(it.get("source")) == "document":
                ev = self.resolver({"block_id": it.get("block_id") or "", "quote": it.get("quote") or str(val)})
                if ev is None:
                    return "unverified", {**out, "reason": f"данные документа «{var} = {val}» не найдены в тексте"}
                doc_items.append({"name": var, "value": val, "evidence": ev})
            else:
                illus.append({"name": var, "value": val, "why": it.get("why") or "выбрано моделью для иллюстрации"})
        if not assign:
            return "unverified", {**out, "reason": "witness без входа"}
        results = {}
        for side, s in (("a", sa), ("b", sb)):
            s = {**s, "constraints": [c for c in (s.get("constraints") or []) if as_dict(c).get("var")]}
            if side == "a":
                sa = s
            else:
                sb = s
            cons = [as_dict(c) for c in (s.get("constraints") or []) if as_dict(c).get("var")]
            results[side] = [eval_constraint(c, assign, self.fs) for c in cons]
        if any(x is False for x in results["a"] + results["b"]):
            bad = [f"{side}: {as_dict(c).get('var')} {as_dict(c).get('op')} {as_dict(c).get('value')}"
                   for side, s in (("a", sa), ("b", sb)) for c, res in zip(s.get("constraints") or [], results[side]) if res is False]
            return "disjoint", {**out, "reason": "вход не удовлетворяет предусловию: " + "; ".join(bad)}
        both = results["a"] and results["b"] and all(x is True for x in results["a"] + results["b"])
        pre = "program" if both else "model"
        ok, how = outcomes_incompatible(w)
        if not ok:
            return "unverified", {**out, "reason": how}
        witness = {
            "input": {"description": str(w.get("description") or "; ".join(f"{k} = {v}" for k, v in assign.items())),
                      "document_data": doc_items, "illustrative": illus, "assignments": dict(assign)},
            "outcome_a": str(w.get("outcome_a") or ""), "outcome_b": str(w.get("outcome_b") or ""),
            "evidence_a": ev_a, "evidence_b": ev_b,
        }
        for k in ("outcome_a_value", "outcome_b_value", "outcome_target"):
            if w.get(k) not in (None, ""):
                witness[k] = w[k]
        return "verified", {"witness": witness,
                            "checks": {"evidence": "program", "input": "program", "preconditions": pre, "outcomes": how}}

    # ----------------------------------------------------------- LLM: покрытие
    def llm_coverage(self) -> None:
        if not self.ask or not self.obls or not self.acc:
            return
        payload = {"task": _load_prompt("cross.coverage.md"), "context": {
            "mode": "auto", "block_ids": list(dict.fromkeys([o.hint["block_id"] for o in self.obls] + [a.block_id for a in self.acc]))},
            "input": {}}
        payload["input"] = {
            "obligations": [{"obligation_id": o.oid, "requirement": o.label, "text": o.hint["quote"], "branches": o.branches}
                            for o in self.obls],
            "acceptance": [{"acceptance_id": a.aid, "label": a.label, "block_id": a.block_id, "text": a.text,
                            **{k: v["quote"] for k, v in a.cells.items()}} for a in self.acc],
            "known_conflicts": [{"title": c["title"], "acceptance_ids": c.get("acceptance_ids", []), "req_ids": c.get("req_ids", [])}
                                for c in self.candidates if c.get("subkind") == "conflict"],
            "facts": self._facts_brief(),
        }
        res = self._call(STAGE_COVERAGE, payload)
        if not res:
            return
        oids = {o.oid for o in self.obls}
        aids = {a.aid for a in self.acc}
        for ob in res.get("obligations") or []:
            ob = as_dict(ob)
            if ob.get("obligation_id") in oids and ob.get("branches"):
                self.llm_branches[ob["obligation_id"]] = [str(x) for x in ob["branches"]]
        links = []
        for ln in res.get("links") or []:
            ln = as_dict(ln)
            if ln.get("obligation_id") not in oids or ln.get("acceptance_id") not in aids:
                self.warnings.append(f"{STAGE_COVERAGE}: связь {ln.get('obligation_id')!r} ↔ {ln.get('acceptance_id')!r} "
                                     f"не относится к текущему входу и пропущена.")
                continue
            links.append(ln)
        self.llm_links = links

    # ----------------------------------------------------------- покрытие
    def _span(self, h: Optional[dict]) -> Optional[tuple[str, int, int]]:
        if not h or not h.get("block_id"):
            return None
        if isinstance(h.get("start"), int) and isinstance(h.get("end"), int):
            return h["block_id"], h["start"], h["end"]
        p = self.view.text(h["block_id"]).find(h.get("quote") or "\0")
        return (h["block_id"], p, p + len(h["quote"])) if p >= 0 else None

    def _conflict_for(self, o: Obligation, a: Acc) -> Optional[dict]:
        """Конфликт, в котором участвуют именно эта приёмка и это предложение требования."""
        for c in self.candidates:
            if c["kind"] != "conflict" or not c.get("witness") or a.aid not in c.get("acceptance_ids", []):
                continue
            for e in [c["witness"].get("evidence_a"), c["witness"].get("evidence_b")] + list(c.get("binds", [])):
                sp = self._span(e)
                if sp and sp[0] == o.hint["block_id"] and sp[1] < o.hint["end"] and o.hint["start"] < sp[2]:
                    return c
        return None

    def _conflict_any(self, a: Acc) -> Optional[dict]:
        for c in self.candidates:
            if c["kind"] == "conflict" and a.aid in c.get("acceptance_ids", []):
                return c
        return None

    def lexical_links(self) -> dict[str, list[tuple[Acc, float]]]:
        """Связь по сущностям (IDF по документу): ≥ 2 общих ключа с весом ≥ 2 или один редкий (idf ≥ 3)."""
        out: dict[str, list] = {}
        for o in self.obls:
            ko = key_set(o.text)
            for a in self.acc:
                sc, shared = self.link_score(ko, key_set(a.text))
                if shared and ((len(shared) >= 2 and sc >= 2.0) or max(self.idf_of(k) for k in shared) >= 3.0):
                    out.setdefault(o.oid, []).append((a, sc))
        return out

    def coverage(self) -> list[dict]:
        cov = []
        lex = self.lexical_links()
        llm_by_o: dict[str, list[dict]] = {}
        for ln in self.llm_links or []:
            llm_by_o.setdefault(ln["obligation_id"], []).append(ln)
        acc_by_id = {a.aid: a for a in self.acc}
        acc_section_present = bool(self.acc)
        for o in self.obls:
            branches = self.llm_branches.get(o.oid) or o.branches
            links, hints = [], [{"block_id": o.hint["block_id"], "quote": o.hint["quote"]}]
            status, expl = None, []
            conflicts = [(a, self._conflict_for(o, a)) for a in self.acc]
            conflicts = [(a, c) for a, c in conflicts if c]
            for a, c in conflicts:
                links.append({"acceptance_id": a.aid, "relation": "contradicts", "source": c.get("origin", "rules"), "ref": c.get("ref")})
                hints.append({"block_id": a.block_id, "quote": a.hint["quote"]})
                expl.append(f"{a.label} противоречит обязательству — см. {c.get('ref')} «{c['title']}».")
            checked: set = set()
            if self.llm_links is not None:
                for ln in llm_by_o.get(o.oid, []):
                    a = acc_by_id[ln["acceptance_id"]]
                    rel = norm(ln.get("relation"))
                    if rel in ("unrelated", ""):
                        continue
                    if any(x["acceptance_id"] == a.aid for x in links):
                        continue
                    if rel == "contradicts":
                        verified = None
                        lw = as_dict(ln.get("witness"))
                        if lw.get("input") or lw.get("outcome_a"):
                            st, det = self.verify({"witness": ln["witness"], "a": ln.get("a") or {}, "b": ln.get("b") or {}},
                                                  _unit_of_obl(o), _unit_of_acc(a))
                            if st == "verified":
                                cand = make_candidate("conflict", f"{a.label} противоречит {o.label}",
                                                      str(ln.get("explanation") or "Приёмка ожидает исход, противоположный обязательству."),
                                                      [det["witness"]["evidence_a"], det["witness"]["evidence_b"]],
                                                      witness=det["witness"], origin="llm", checks=det["checks"])
                                self.add(cand)
                                verified = self._conflict_for(o, a) or cand
                        if verified:
                            links.append({"acceptance_id": a.aid, "relation": "contradicts", "source": "llm", "ref": verified.get("ref")})
                            expl.append(f"{a.label} противоречит обязательству — {verified.get('ref')}.")
                        else:
                            links.append({"acceptance_id": a.aid, "relation": "contradicts_unverified", "source": "llm"})
                            expl.append(f"{a.label}, по оценке модели, спорит с обязательством, но общий вход не подтверждён — "
                                        f"вопрос передан №08.")
                            self.add(make_candidate(
                                "question", f"{a.label} и {o.label}: возможное противоречие без подтверждённого входа",
                                "Нельзя засчитать приёмку как проверку обязательства, пока исход не уточнён.",
                                [o.hint, a.hint], origin="llm",
                                question=str(ln.get("explanation") or f"Какой исход ожидается в {a.label} по {o.label}?")))
                        hints.append({"block_id": a.block_id, "quote": a.hint["quote"]})
                        continue
                    bc = [str(x) for x in (ln.get("branches_checked") or [])]
                    links.append({"acceptance_id": a.aid, "relation": "checks" if rel == "checks" else "checks_branch",
                                  "source": "llm", "branches_checked": bc})
                    hints.append({"block_id": a.block_id, "quote": a.hint["quote"]})
                    if rel == "checks" and (not bc or len(bc) >= len(branches)):
                        checked |= {norm(x) for x in branches}
                    else:
                        checked |= {norm(x) for x in bc}
                    if ln.get("explanation"):
                        expl.append(f"{a.label}: {ln['explanation']}")
            else:
                for a, sc in lex.get(o.oid, []):
                    if any(x["acceptance_id"] == a.aid for x in links):
                        continue
                    links.append({"acceptance_id": a.aid, "relation": "lexical", "source": "rules", "score": round(sc, 2)})
                    hints.append({"block_id": a.block_id, "quote": a.hint["quote"]})
            br_norm = [norm(x) for x in branches]
            done = [b for b in br_norm if b in checked]
            if any(x["relation"] == "contradicts" for x in links):
                status = "conflict"
            elif any(x["relation"] in ("checks", "checks_branch") for x in links):
                tainted = [x["acceptance_id"] for x in links if x["relation"] in ("checks", "checks_branch")
                           and self._conflict_any(acc_by_id[x["acceptance_id"]])]
                if len(done) == len(br_norm) and not tainted and \
                        not any(x["relation"] == "contradicts_unverified" for x in links):
                    status = "covered"
                    expl.insert(0, f"Проверены все ветви ({len(br_norm)}).")
                else:
                    status = "partial"
                    expl.insert(0, f"Проверено ветвей: {len(done)} из {len(br_norm)}"
                                   + (f"; не проверены: {', '.join(b for b in branches if norm(b) not in checked)}" if len(done) < len(br_norm) else "")
                                   + (f"; приёмка {', '.join(tainted)} сама участвует в противоречии" if tainted else "") + ".")
            elif any(x["relation"] == "contradicts_unverified" for x in links):
                status = "partial"
            elif any(x["relation"] == "lexical" for x in links):
                status = "partial"
                expl.insert(0, "Связь найдена только по общим сущностям (режим без модели); что приёмка проверяет все "
                               f"ветви ({len(br_norm)}), не установлено — covered не присваивается.")
            elif self.missing or self.partial:
                status = "unknown"
                where = (f"страницы {', '.join(map(str, self.missing))} не извлечены" if self.missing
                         else "документ прочитан не полностью (" + "; ".join(self.partial[:2]) + ")")
                expl.insert(0, f"Связанной приёмки не найдено, но {where} — отсутствие проверки не доказано.")
            elif self.llm_links is None and "cross.coverage" in self.stats["llm_failed"] and not lex.get(o.oid):
                status = "uncovered"
                expl.insert(0, "Модель недоступна; по сущностям ни одна строка приёмки не связана с обязательством.")
            else:
                status = "uncovered"
                expl.insert(0, "Ни одна строка приёмки не проверяет обязательство." if acc_section_present
                            else "В документе нет критериев приёмки.")
            evs = [dict(o.hint)] + [dict(acc_by_id[x["acceptance_id"]].hint) for x in links if x["acceptance_id"] in acc_by_id]
            cov.append({
                "req_id": o.req_id,
                "obligation_id": o.oid,
                "obligation": o.text,
                "acceptance_ids": list(dict.fromkeys(x["acceptance_id"] for x in links)),
                "status": status,
                "explanation": " ".join(expl),
                "hints": _dedupe_hints(hints),
                "evidence": [e for i, e in enumerate(evs) if e not in evs[:i]],
                "branches": branches,
                "branches_checked": [b for b in branches if norm(b) in checked],
                "links": links,
            })
        return cov

    def _drop_resolved_questions(self) -> None:
        conflicts = [c for c in self.candidates if c["kind"] == "conflict"]
        keep = []
        for c in self.candidates:
            if c.get("subkind") == "question":
                qb = {h["block_id"] for h in c.get("hints", [])}
                hit = next((x for x in conflicts if qb and qb <= {h["block_id"] for h in x.get("hints", [])}), None)
                if hit:
                    self.log("question", "resolved", f"Вопрос «{c['title']}» снят: на тех же опорах подтверждён конфликт "
                             f"{hit.get('ref')} «{hit['title']}».")
                    continue
            keep.append(c)
        self.candidates = keep

    # ----------------------------------------------------------- сборка
    def run(self) -> dict:
        for c in self.fs.candidates:
            self.add(dict(c))
        self.period_checks()
        self.contract_gaps()
        if self.ask:
            self.llm_pairs(self.select_pairs(self.units()))
            self.llm_coverage()
        else:
            self.stats["pairs_selected"] = len(self.select_pairs(self.units()))
        if self.missing:
            self.warnings.append(f"Страницы {', '.join(map(str, self.missing))} не извлечены: выводы об отсутствии помечены unknown.")
        self._drop_resolved_questions()
        cov = self.coverage()
        if self.ask and self.stats["llm_failed"]:
            self.stats["status"] = "partial"
            if self.ask_ok == 0 and self.ask_error is not None:
                # Ни один вызов не удался: отдаём AskError движку — он отметит этап failed и
                # перезапустит модуль с ask=None (тот же результат правил, честный статус прогона).
                raise self.ask_error
        else:
            self.stats["status"] = "complete"
        for f in self.fs.facts:
            f.req_ids = list(dict.fromkeys(f.req_ids + self.block_reqs.get((f.evidence or {}).get("block_id"), [])))
        summary = summarize_coverage(cov, self.reqs)
        summary["excluded"] = self.cov_excluded
        return {
            "facts": [f.to_dict() for f in self.fs.facts],
            "coverage": cov,
            "candidates": self.candidates,
            "warnings": list(dict.fromkeys(self.warnings)),
            "coverage_summary": summary,
            "comparisons": self.comparisons,
            "evidence_audit": self.audit.as_dict(),
            "stats": self.stats,
            "acceptance": [{"acceptance_id": a.aid, "label": a.label, "block_id": a.block_id, "quote": a.hint["quote"]}
                           for a in self.acc],
        }


def _unit_of_obl(o: Obligation) -> Unit:
    return Unit(o.oid, "business_rules", o.hint["block_id"], o.text, o.hint, o.req_id, o.label)


def _unit_of_acc(a: Acc) -> Unit:
    return Unit(a.aid, "acceptance", a.block_id, a.text, a.hint, a.req_id, a.label)


def _slots(s: Any) -> dict:
    d = as_dict(s)
    return {k: d.get(k) for k in ("object", "owner", "condition", "moment", "units", "expected") if d.get(k) not in (None, "")}


def _dedupe_hints(hints: list) -> list:
    seen, out = set(), []
    for h in hints:
        k = (h["block_id"], h["quote"])
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


def summarize_coverage(coverage: list[dict], reqs: Optional[list] = None) -> dict:
    """Сводка с сохранённым знаменателем: covered/partial/conflict/uncovered/unknown из N обязательств."""
    n = len(coverage)
    counts = {s: sum(1 for c in coverage if c["status"] == s) for s in COVERAGE_STATUSES}
    linked = sum(1 for c in coverage if c["acceptance_ids"])
    by_req: dict[str, list] = {}
    for c in coverage:
        by_req.setdefault(c["req_id"], []).append(c["status"])
    labels = {r.id: r.label for r in (reqs or [])}

    def agg(st: list) -> str:
        if "conflict" in st:
            return "conflict"
        if all(s == "covered" for s in st):
            return "covered"
        if all(s == "uncovered" for s in st):
            return "uncovered"
        if "unknown" in st and not any(s in ("covered", "partial") for s in st):
            return "unknown"
        return "partial"

    return {
        "denominator": n,
        **counts,
        "covered_ratio": round(counts["covered"] / n, 3) if n else None,
        "linked": linked,
        "linked_ratio": round(linked / n, 3) if n else None,
        "by_requirement": [{"req_id": rid, "label": labels.get(rid, rid), "obligations": len(st),
                            "covered": sum(1 for s in st if s == "covered"), "status": agg(st)} for rid, st in by_req.items()],
        "note": "Знаменатель — число обязательств. linked (есть связанная приёмка) не равен covered: covered требует "
                "проверки всех ветвей без противоречия; conflict — приёмка спорит с обязательством.",
    }


def review_set(document: Any, requirements: Any, ask: Optional[Callable] = None, *, fact_hints: Any = None,
               resolve: Optional[Callable] = None, max_pairs: int = 60, pairs_per_call: int = 30) -> dict:
    """Проверка набора: межраздельные противоречия, пропуски контракта, покрытие приёмкой.

    ``ask(stage, payload, schema) -> dict`` — транспорт к LLM от движка (None → только правила).
    ``fact_hints`` — инвентарь №04; ``resolve(document, hint) -> Evidence | None`` — резолвер №07.
    """
    return CrossReview(document, requirements, ask, fact_hints, resolve, max_pairs, pairs_per_call).run()
