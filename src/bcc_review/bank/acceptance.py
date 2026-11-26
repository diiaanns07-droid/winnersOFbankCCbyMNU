"""Черновые приёмочные сценарии «Дано / Когда / Тогда» из текущего входа (№10).

Из требований извлекаются диапазоны (границы, включённость, целочисленность,
единицы), часовой пояс и правило расчётного месяца, включаемые и исключаемые
типы операций, возвраты, порог срабатывания и лимит уведомлений, повторная
доставка события и контракт API (метод, параметры, статусы, примеры ответов).
Каждый сценарий привязан к атомарному обязательству: предложению или строке
таблицы с проверенной опорой. Когда правила дают два исхода, сценарий открыт:
хранит вопрос и варианты, а после решения владельца получает конкретный
ожидаемый результат со ссылкой на решение.

Все числа выводятся из текста документа; конкретные значения учебного кейса
встречаются только в тестах кейса (tests/p10).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from .checklist import (
    _S,
    AskFn,
    Block,
    Cell,
    Doc,
    Scan,
    Table,
    W,
    _dedupe_ev,
    as_list,
    decision_id,
    decision_text,
    decision_value,
    decisions_by_question,
    g,
    norm,
    sentences,
    short,
)

# ---------------------------------------------------------------- числа и единицы

NUM_CORE = r"(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,]\d+)?(?!\d)"
NUM = r"(?<![\w.,:/\-])" + NUM_CORE
UNIT = (
    r"(?:₸|тенге|тг\b\.?|kzt\b|тиын\w*|%|процент\w*|руб\w*|₽|usd\b|\$|eur\b|€|секунд\w*|сек\b\.?|"
    r"минут\w*|мин\b\.?|час\w*|суток|сутки|дн[яейи]\w*|символ\w*|знак\w*|шт\b\.?)"
)
_NUM_RE = re.compile(NUM)
_UNIT_RE = re.compile(UNIT, re.I)
_RANGE_FROM_TO = re.compile(
    rf"(?<!\w)от\s+(?P<a>{NUM_CORE})\s*(?P<ua>{UNIT})?(?P<ainc>\s+включительно)?\s+до\s+(?P<b>{NUM_CORE})\s*(?P<ub>{UNIT})?(?P<binc>\s+включительно)?",
    re.I,
)
_RANGE_DASH = re.compile(
    rf"(?P<a>{NUM})\s*(?P<ua>{UNIT})?\s*[–—−-]\s*(?P<b>{NUM_CORE})\s*(?P<ub>{UNIT})?(?![\d\-:/.,])", re.I
)
_BOUND = re.compile(
    rf"(?<!\w)(?P<op>не\s+менее|не\s+меньше|не\s+ниже|не\s+более|не\s+больше|не\s+выше|не\s+превыша\w*|"
    rf"минимум|максимум|более|больше|свыше|выше|менее|меньше|ниже|до|≥|≤|>=|<=|>|<)\s*(?P<v>{NUM_CORE})\s*(?P<u>{UNIT})?(?P<inc>\s+включительно)?",
    re.I,
)
_LOW_INC = {"не менее", "не меньше", "не ниже", "минимум", "≥", ">="}
_HIGH_INC = {"не более", "не больше", "не выше", "максимум", "≤", "<="}
_LOW_EXC = {"более", "больше", "свыше", "выше", ">"}
_HIGH_EXC = {"менее", "меньше", "ниже", "<"}
_SUBJECT = re.compile(
    r"порог|сумм|лимит|значени|размер|количеств|длин|диапазон|amount|limit|возраст|срок|ставк|процент|комисси|балл"
)
_INC_HINT = re.compile(r"обе\s+границ\w*\s+включ\w*|границ\w*\s+(?:диапазона\s+)?включ\w*|включая\s+границ\w*")
_EXC_HINT = re.compile(r"границ\w*\s+не\s+включ\w*|не\s+включая\s+границ|исключая\s+границ")
_INT_HINT = re.compile(r"цел\w+\s+(?:числ|значени|сумм)|целочислен|(?<!\w)цел(?:ый|ое|ая|ые|ого|ым)\b|\binteger\b|\bint(?:32|64)?\b")
_MONTHS_AFTER = re.compile(r"^\s*(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр|:)", re.I)

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_PREP = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"]
MONTHS_ADJ = ["январск", "февральск", "мартовск", "апрельск", "майск", "июньск", "июльск", "августовск", "сентябрьск", "октябрьск", "ноябрьск", "декабрьск"]
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_DATE = re.compile(
    r"(?P<d>\d{1,2})\s+(?P<m>января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"(?:\s+\d{4}(?:\s*г\.?)?)?(?:\s+(?:в\s+)?(?P<hh>\d{1,2}):(?P<mm>\d{2}))?",
    re.I,
)
_TZ_RE = re.compile(
    r"(?:\bв|\bпо)\s+(?:времени\s+)?(?P<city>алмат\w*|астан\w*|москв\w*|ташкент\w*)|(?P<utc>utc|gmt)\s*(?P<sign>[+-])\s*(?P<off>\d{1,2})|(?P<iana>asia/\w+|europe/\w+)",
    re.I,
)
_TZ_CITIES = {
    "алмат": ("Asia/Almaty", 5, "по Алматы", "с 1 марта 2024 г. в Казахстане единый часовой пояс UTC+5"),
    "астан": ("Asia/Almaty", 5, "по Астане", "с 1 марта 2024 г. в Казахстане единый часовой пояс UTC+5"),
    "москв": ("Europe/Moscow", 3, "по Москве", None),
    "ташкент": ("Asia/Tashkent", 5, "по Ташкенту", None),
}
_IANA_OFFSET = {"asia/almaty": 5, "asia/qostanay": 5, "asia/aqtobe": 5, "europe/moscow": 3, "asia/tashkent": 5}


def dec(text: str) -> Decimal:
    return Decimal(re.sub(r"[\s  ]", "", text).replace(",", "."))


def _plain(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt(d: Decimal) -> str:
    """Число по-русски: группы разрядов через пробел, десятичная запятая."""
    s = _plain(d)
    neg = s.startswith("-")
    s = s.lstrip("-")
    ip, _, fp = s.partition(".")
    if len(ip) > 3:
        ip = f"{int(ip):,}".replace(",", " ")
    return ("-" if neg else "") + ip + ("," + fp if fp else "")


def jnum(d: Decimal) -> int | float:
    return int(d) if d == d.to_integral_value() else float(d)


def unit_canon(u: str | None) -> str:
    if not u:
        return ""
    t = norm(u).rstrip(".")
    if t in {"₸", "тенге", "тг", "kzt"}:
        return "₸"
    for prefix, canon in (("тиын", "тиын"), ("процент", "%"), ("руб", "₽"), ("секунд", "с"), ("сек", "с"), ("минут", "мин"),
                          ("мин", "мин"), ("час", "ч"), ("сут", "дн."), ("дн", "дн."), ("символ", "симв."), ("знак", "симв."), ("шт", "шт.")):
        if t.startswith(prefix):
            return canon
    return {"%": "%", "₽": "₽", "usd": "$", "$": "$", "eur": "€", "€": "€"}.get(t, t)


def with_unit(d: Decimal, unit: str) -> str:
    return f"{fmt(d)} {unit}".strip()


def _nice(x: Decimal) -> Decimal:
    """Округление вниз до одной значащей цифры: 5 → 5, 47 → 40, 3 210 → 3 000."""
    if x <= 0:
        return Decimal(0)
    s = _plain(x.to_integral_value(rounding="ROUND_FLOOR"))
    if s in {"", "0"}:
        return Decimal(0)
    return Decimal(s[0] + "0" * (len(s) - 1))


# ---------------------------------------------------------------- требования


@dataclass
class Req:
    id: str
    source_id: str | None
    text: str
    spans: list[tuple[str, int, int]]


class ReqIndex:
    def __init__(self, doc: Doc, requirements: Iterable[Any]):
        self.items: list[Req] = []
        for i, r in enumerate(requirements):
            rid = str(g(r, "id") or f"R-{i + 1}")
            text = str(g(r, "text") or "")
            spans = [(e["block_id"], e["start"], e["end"]) for e in doc.evidence_of(r)]
            if not spans and text:
                ids = [str(b) for b in as_list(g(r, "block_ids"))]
                ev = doc.locate(text, ids)
                if ev:
                    spans.append((ev["block_id"], ev["start"], ev["end"]))
                else:
                    spans += [(b, 0, len(doc.by_id[b].text)) for b in ids if b in doc.by_id]
            src = g(r, "source_id")
            self.items.append(Req(rid, str(src) if src else None, text, spans))
        self.by_id = {r.id: r for r in self.items}

    def at(self, block_id: str, start: int, end: int) -> list[Req]:
        out = []
        for r in self.items:
            if any(b == block_id and s < end and start < e for b, s, e in r.spans):
                out.append(r)
        return out

    def label(self, rid: str | None) -> str:
        r = self.by_id.get(rid or "")
        return (r.source_id or r.id) if r else (rid or "")


# ---------------------------------------------------------------- факты


@dataclass
class Rule:
    kind: str
    block: Block
    span: tuple[int, int]
    data: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.block.text[self.span[0] : self.span[1]]


@dataclass
class Param:
    name: str
    fmt: str
    mandatory: bool | None
    logic: str
    desc: str
    location: str
    block: Block
    span: tuple[int, int]
    logic_cell: Cell | None


@dataclass
class Range:
    key: str
    level: str
    subject: str
    lo: Decimal | None
    hi: Decimal | None
    lo_inc: bool | None
    hi_inc: bool | None
    integer: bool | None
    unit: str
    block: Block
    span: tuple[int, int]
    evidence: list[dict]
    notes: list[str]
    param: Param | None = None

    @property
    def step(self) -> Decimal:
        if self.integer:
            return Decimal(1)
        places = max((-v.as_tuple().exponent for v in (self.lo, self.hi) if v is not None), default=0)
        return Decimal(1).scaleb(-places) if places > 0 else Decimal(1)

    def contains(self, v: Decimal) -> bool:
        if self.lo is not None and (v < self.lo or (v == self.lo and self.lo_inc is False)):
            return False
        if self.hi is not None and (v > self.hi or (v == self.hi and self.hi_inc is False)):
            return False
        return True

    def describe(self) -> str:
        if self.lo is not None and self.hi is not None:
            core = f"{fmt(self.lo)}–{with_unit(self.hi, self.unit)}"
        elif self.lo is not None:
            core = f"от {with_unit(self.lo, self.unit)}"
        else:
            core = f"до {with_unit(self.hi or Decimal(0), self.unit)}"
        inc = {(True, True): "обе границы включены", (False, False): "границы не включены"}.get((self.lo_inc, self.hi_inc))
        if inc is None:
            parts = []
            for name, flag, present in (("нижняя", self.lo_inc, self.lo is not None), ("верхняя", self.hi_inc, self.hi is not None)):
                if present:
                    parts.append(f"{name} граница {'включена' if flag else 'не включена' if flag is False else '— включённость не указана'}")
            inc = ", ".join(parts)
        tail = ", только целые значения" if self.integer else ""
        return f"{core} ({inc}{tail})"


@dataclass
class Status:
    code: int
    descs: list[tuple[str, dict]] = field(default_factory=list)
    titles: list[tuple[str, dict]] = field(default_factory=list)
    examples: list[tuple[str, dict]] = field(default_factory=list)


@dataclass
class Api:
    method: str | None = None
    method_ev: dict | None = None
    path: str | None = None
    path_ev: dict | None = None
    auth: str | None = None
    auth_ev: dict | None = None
    params: list[Param] = field(default_factory=list)
    statuses: dict[int, Status] = field(default_factory=dict)
    mentions: list[dict] = field(default_factory=list)
    rejections: list[tuple[str, dict]] = field(default_factory=list)
    logic: list[tuple[str, dict]] = field(default_factory=list)
    curl: dict[str, str] = field(default_factory=dict)

    def logic_ev(self, pattern: str, exclude: str | None = None) -> list[dict]:
        out = []
        for seg, ev in self.logic:
            t = norm(seg)
            if re.search(pattern, t) and not (exclude and re.search(exclude, t)):
                out.append(ev)
        return out

    def st(self, code: int) -> Status:
        return self.statuses.setdefault(code, Status(code))

    @property
    def call(self) -> str:
        return f"{self.method or 'метод'} {self.path or 'API'}".strip()


_REJECT = r"отклонен|неверн|некоррект|ошибк|\berror\b"
_STATUS_LOGIC = {401: r"сесси|авториз|токен|аутентиф", 403: r"принадлежн|доступ|чуж|прав\w* доступ", 404: r"принадлежн|найден|существ|отсутств"}
_API_SEC = re.compile(r"\brest\b|\bapi\b|endpoint|эндпоинт|swagger|openapi")
_STATUS_LINE = re.compile(r"^\s*\**\s*(?P<code>[1-5]\d\d)(?:\s*\.\s*\**|\s*\**\s*$|\s*\**\s*[—–-])\s*(?P<rest>.*?)\s*$")
_MENTION = re.compile(
    r"(?:для\s+(?P<cond>[^,.;]+?)\s+)?возвраща\w+\s+(?P<code>[1-5]\d\d)(?:\s*,?\s*как\s+и\s+для\s+(?P<cond2>[^,.;]+))?", re.I
)
_COND_PREFIX = re.compile(r"^(?:ответ\s+)?(?:в\s+случае,?\s*)?(?:если\s+)?", re.I)
_GLOSS = {
    "amount": ("сумм", "порог", "лимит"), "limit": ("порог", "лимит"), "sum": ("сумм",), "enabled": ("переключат", "включ"),
    "card": ("карт",), "phone": ("телефон",), "date": ("дат",),
}


def _is_api_block(b: Block) -> bool:
    return any(_API_SEC.search(norm(s)) for s in b.section)


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _code_text(b: Block) -> tuple[int, int]:
    text = b.text
    s, e = 0, len(text)
    if text.lstrip().startswith("```"):
        nl = text.find("\n")
        s = nl + 1 if nl >= 0 else len(text)
        close = text.rfind("```")
        e = close if close > s else len(text)
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _is_error_example(text: str) -> bool:
    data = _json(text)
    if isinstance(data, Mapping) and "result" in data:
        return norm(data.get("result")) in {"error", "fail", "failed", "ошибка"}
    return bool(re.search(r'"result"\s*:\s*"error"', norm(text)))


def _is_ok_example(text: str) -> bool:
    data = _json(text)
    if isinstance(data, Mapping) and "result" in data:
        return norm(data.get("result")) in {"ok", "success", "успех"}
    return not _is_error_example(text)


def param_stems(p: Param) -> set[str]:
    name = p.name.lower()
    stems = {name}
    for k, v in _GLOSS.items():
        if k in name:
            stems |= set(v)
    for w in re.findall(r"[а-яё]{5,}", norm(p.desc)):
        stems.add(w[:5])
    return stems


# ---------------------------------------------------------------- контекст генерации


_KIND_ORDER = {k: i for i, k in enumerate(
    ["default", "boundary", "month", "event_type", "refund", "trigger", "cap", "conflict", "preserve", "idempotency",
     "timing", "api_success", "api_validation", "api_status", "api_replace", "acceptance", "coverage_gap", "llm"]
)}


class Ctx:
    def __init__(self, doc: Doc, scan: Scan, reqs: ReqIndex, warnings: list[dict]):
        self.doc = doc
        self.scan = scan
        self.reqs = reqs
        self.warnings = warnings
        self.rules: dict[str, list[Rule]] = {}
        self.ranges: list[Range] = []
        self.api: Api | None = None
        self.tcs: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.questions: dict[str, dict] = {}
        self.rows: list[dict] = []  # разобранные критерии приёмки
        self.ui_error: tuple[str, dict] | None = None
        self.spend_step: tuple[Decimal, dict | None] = (Decimal(1), None)
        self.T = self.S = Decimal(0)
        self.unit = ""
        self.month = 0
        self.range_main: Range | None = None

    # --- обязательство и опоры
    def ev(self, block: Block, span: tuple[int, int]) -> dict:
        return self.doc.ev(block, *span)

    def rule_ev(self, rule: Rule) -> dict:
        return self.doc.ev(rule.block, *rule.span)

    def obligation(self, block: Block, span: tuple[int, int]) -> dict:
        found = self.reqs.at(block.id, *span)
        if found:
            r = found[0]
            rs = [(s, e) for b, s, e in r.spans if b == block.id and s < span[1] and span[0] < e]
            s, e = (max(span[0], rs[0][0]), min(span[1], rs[0][1])) if rs else span
            if e <= s:
                s, e = span
            return {"req_id": r.id, "source_id": r.source_id, "quote": block.text[s:e], "evidence": self.doc.ev(block, s, e)}
        return {"req_id": None, "source_id": None, "quote": block.text[span[0] : span[1]], "evidence": self.doc.ev(block, *span)}

    def src(self, rule: Rule | None) -> str:
        if rule is None:
            return "требование"
        found = self.reqs.at(rule.block.id, *rule.span)
        if found:
            return found[0].source_id or found[0].id
        return self.doc.label(self.rule_ev(rule))

    def quote(self, rule: Rule, limit: int = 160) -> str:
        return short(re.sub(r"^\W*(?:[А-ЯA-Z]{1,3}-\d+\.?\**\s*)", "", rule.text).strip("* "), limit).rstrip(".")

    def first(self, kind: str) -> Rule | None:
        items = self.rules.get(kind) or []
        return items[0] if items else None

    # --- регистрация сценария
    def add(self, key: str, *, kind: str, level: str, title: str, precondition: str, action: str,
            expected: str | None = None, options: list[dict] | None = None, question: tuple[str, str] | None = None,
            anchor: tuple[Block, tuple[int, int]], evidence: Iterable[dict] = (), values: dict | None = None,
            notes: Iterable[str] = (), source: str = "rules", needs_clarification: bool = False) -> dict:
        if key in self.by_key:
            tc = self.by_key[key]
            tc["evidence"] = _dedupe_ev(tc["evidence"] + [e for e in evidence if e])
            return tc
        obl = self.obligation(*anchor)
        evs = _dedupe_ev([obl["evidence"]] + [e for e in evidence if e])
        for o in options or []:
            evs = _dedupe_ev(evs + o.get("evidence", []))
        tc = {
            "id": None,
            "key": key,
            "kind": kind,
            "level": level,
            "title": title,
            "precondition": precondition,
            "action": action,
            "expected": expected,
            "gherkin": "",
            "req_ids": [],
            "source_ids": [],
            "obligation": obl,
            "evidence": evs,
            "values": values or {},
            "status": "draft",
            "open_question_id": None,
            "open_question": None,
            "options": [],
            "decision_id": None,
            "resolved_question_id": None,
            "finding_ids": [],
            "covers_gaps": [],
            "needs_clarification": needs_clarification,
            "source": source,
            "notes": list(dict.fromkeys(notes)),
            "changes": [],
            "draft": True,
            "_anchor": (anchor[0].order, anchor[1][0], _KIND_ORDER.get(kind, 99), len(self.tcs)),
            "_qkey": None,
        }
        if options and len(options) >= 2:
            for i, o in enumerate(options):
                o["id"] = "ABCDEFGH"[i]
            tc["options"] = options
            tc["status"] = "open"
            qkey, qtext = question or (f"tc:{key}", f"Какой исход верен: {title}?")
            tc["_qkey"] = qkey
            q = self.questions.setdefault(
                qkey,
                {"id": "Q-BANK-" + hashlib.sha1(qkey.encode("utf-8")).hexdigest()[:6].upper(), "key": qkey, "kind": "outcome",
                 "prompt": qtext, "options": [f"{o['id']}) {o['label']}: {short(o['expected'], 160)}" for o in options],
                 "affected_req_ids": [], "finding_ids": [], "existing": False},
            )
            tc["open_question_id"] = q["id"]
        elif options:
            tc["expected"] = options[0]["expected"]
        self.tcs.append(tc)
        self.by_key[key] = tc
        return tc


# ---------------------------------------------------------------- извлечение фактов

_RULES: dict[str, re.Pattern[str]] = {
    "month": re.compile(r"месяц\w*\s+(?:определя\w+|счита\w+|рассчитыва\w+|опреде\w+)\s+по\s+(?:дате|времени|моменту)\s+(?P<basis>\w+)(?:\s+(?P<obj>\w+))?"),
    "include": re.compile(r"(?:в\s+(?:расход\w*|сумм\w*|расч[её]т\w*|сч[её]тчик\w*|итог\w*)\s+)(?:входят|включаются|учитываются)\s+(?P<items>[^.;]+)"),
    "exclude": re.compile(r"(?P<items>[^.;]+?)\s+(?:исключаются|не\s+учитываются|не\s+входят)|(?:кроме|за\s+исключением)\s+(?P<items2>[^.;]+)"),
    "refund": re.compile(r"возврат\w*\s+(?:уменьша\w+|снижа\w+|вычита\w+)\s+(?P<what>[^.;]+)"),
    "trigger": re.compile(r"(?:ниже|меньше)\s+порог\w*.*?(?:равн\w*\s+порогу|не\s+ниже\s+порога|не\s+менее\s+порога|выше|превыш\w*)|достиж\w*\s+порог\w*|превыш\w*\s+порог\w*"),
    "cap": re.compile(r"(?:максимум|не\s+более|не\s+больше|только)\s+(?P<n>один|одн\w*|\d+)\s+(?:так\w+\s+)?(?P<what>[\w-]+)\s+(?:в|за)\s+(?P<period>(?:календарн\w+\s+)?(?:месяц|день|сутки|недел\w+))"),
    "override": re.compile(r"независимо\s+от\s+(?:истори\w*|предыдущ\w*|прошл\w*)"),
    "preserve": re.compile(r"(?:изменени\w+|смен\w+)\s+(?P<what>порог\w*|лимит\w*|настро\w+)[^.]*?(?:накопленн\w+\s+(?:сумм\w+|расход\w+)\s+сохраня\w+|сохраня\w+\s+накопленн\w+\s+(?:сумм\w+|расход\w+))"),
    "idempotency": re.compile(r"повторн\w+\s+(?:доставк\w+|получени\w+|отправк\w+)\s+(?:одного\s+)?(?:того\s+же\s+)?(?:событи\w+|сообщени\w+|запрос\w+)|идемпотентн\w*|дубл\w+\s+событи\w+"),
    "replace": re.compile(r"повторн\w+\s+сохранени\w+\s+заменя\w+|заменя\w+\s+действующ\w+\s+настройк\w+"),
    "default": re.compile(r"по\s+умолчани\w+\s+(?P<what>[^.;]+)"),
    "timing": re.compile(r"в\s+течение\s+(?P<n>\d+\s+)?(?P<unit>секунд\w*|минут\w*|час\w*|суток|сутки|дн\w*)(?P<rest>[^.;]*)"),
    "ui_error": re.compile(r"при\s+ошибке\s+ввода|ошибк\w*\s+ввода|сообщени\w+\s+об\s+ошибке"),
    "tiyn": re.compile(r"тиын"),
}
_PUSH = re.compile(r"push|пуш|уведомлен|оповещен|sms|смс")


def _skip_ids(scan: Scan) -> set[str]:
    ids = set(scan.excluded)
    for t in scan.acceptance:
        ids |= t.block_ids
    return ids


def _units(ctx: Ctx) -> Iterable[tuple[Block, int, int, str]]:
    skip = _skip_ids(ctx.scan)
    for b in ctx.doc.blocks:
        if b.id in skip or b.is_heading or b.is_code or b.id in ctx.scan.row_of:
            continue
        for s, e in sentences(b.text):
            seg = b.text[s:e]
            if _STATUS_LINE.match(seg):
                continue
            yield b, s, e, norm(seg)


def extract_rules(ctx: Ctx) -> None:
    for b, s, e, t in _units(ctx):
        for kind, rx in _RULES.items():
            m = rx.search(t)
            if not m:
                continue
            if kind == "include" and not re.search(r"расход|сумм|сч[её]тчик|итог|лимит", t):
                continue
            if kind == "trigger" and not _PUSH.search(t):
                continue
            if kind == "override" and not (_PUSH.search(t) or "достиж" in t):
                continue
            if kind == "exclude" and not re.search(r"расход|сумм|сч[её]тчик|итог|операци|перевод|наличн|покупк", t):
                continue
            data = {k: v for k, v in m.groupdict().items() if v}
            data["norm"] = t
            ctx.rules.setdefault(kind, []).append(Rule(kind, b, (s, e), data))
    if ctx.rules.get("ui_error"):
        r = ctx.rules["ui_error"][0]
        ctx.ui_error = (r.text, ctx.rule_ev(r))
    # Месячное правило: база расчёта и часовой пояс.
    for r in ctx.rules.get("month", []):
        basis = r.data.get("basis", "")
        r.data["basis_kind"] = (
            "transaction" if re.match(r"соверш|покупк|операци|транзакц", basis)
            else "posting" if re.match(r"провед|списан|клиринг|обработ|зачислен", basis)
            else "send" if re.match(r"отправ", basis) else None
        )
        r.data["basis_word"] = {"transaction": "совершения", "posting": "проведения", "send": "отправки"}.get(r.data["basis_kind"] or "", basis)
        r.data["tz"] = _tz_of(r.data["norm"])


def _tz_of(t: str) -> dict | None:
    m = _TZ_RE.search(t)
    if not m:
        return None
    if m.group("city"):
        for stem, (iana, off, phrase, note) in _TZ_CITIES.items():
            if m.group("city").startswith(stem):
                return {"iana": iana, "offset": off, "phrase": phrase, "note": note}
    if m.group("utc"):
        off = int(m.group("off")) * (1 if m.group("sign") == "+" else -1)
        return {"iana": None, "offset": off, "phrase": f"по UTC{m.group('sign')}{m.group('off')}", "note": None}
    iana = m.group("iana")
    return {"iana": iana, "offset": _IANA_OFFSET.get(iana.lower()), "phrase": f"по {iana}", "note": None}


def _hint_scope(a: Block, b: Block) -> bool:
    return a.id == b.id or (len(a.section) >= 2 and a.section[:2] == b.section[:2])


def extract_ranges(ctx: Ctx) -> None:
    hints: list[tuple[str, Block, tuple[int, int], str]] = []
    for b, s, e, t in _units(ctx):
        for rx, kind in ((_INC_HINT, "inc"), (_EXC_HINT, "exc"), (_INT_HINT, "int")):
            if rx.search(t) and not _NUM_RE.search(t):
                um = _UNIT_RE.search(t)
                hints.append((kind, b, (s, e), unit_canon(um.group(0)) if um else ""))
    for b, s, e, t in _units(ctx):
        seg = b.text[s:e]
        level = "api" if _is_api_block(b) else "business"
        taken: list[tuple[int, int]] = []
        for m in _RANGE_FROM_TO.finditer(seg):
            lo, hi = dec(m.group("a")), dec(m.group("b"))
            if hi <= lo:
                continue
            unit = unit_canon(m.group("ub") or m.group("ua"))
            inc = True if m.group("binc") else (True if m.group("ainc") else None)
            rng = _make_range(ctx, b, (s, e), (s + m.start(), s + m.end()), level, _subject(seg[: m.start()]) , lo, hi, inc, inc, unit, t)
            ctx.ranges.append(rng)
            taken.append((m.start(), m.end()))
        for m in _RANGE_DASH.finditer(seg):
            if any(a <= m.start() < z for a, z in taken):
                continue
            lo, hi = dec(m.group("a")), dec(m.group("b"))
            if hi <= lo or _MONTHS_AFTER.match(seg[m.end():]) or not (m.group("ua") or m.group("ub") or re.search(r"диапазон|допустим|значени|порог|лимит|сумм", t)):
                continue
            unit = unit_canon(m.group("ub") or m.group("ua"))
            ctx.ranges.append(_make_range(ctx, b, (s, e), (s + m.start(), s + m.end()), level, _subject(seg[: m.start()]), lo, hi, None, None, unit, t))
            taken.append((m.start(), m.end()))
        lows: list[tuple[Decimal, bool | None, str, tuple[int, int]]] = []
        highs: list[tuple[Decimal, bool | None, str, tuple[int, int]]] = []
        for m in _BOUND.finditer(seg):
            if any(a <= m.start() < z for a, z in taken) or _MONTHS_AFTER.match(seg[m.end("v"):]):
                continue
            if not (m.group("u") or _SUBJECT.search(t)):
                continue
            op = re.sub(r"\s+", " ", m.group("op").lower())
            v = dec(m.group("v"))
            u = unit_canon(m.group("u"))
            sp = (s + m.start(), s + m.end())
            if op in _LOW_INC or op in _LOW_EXC:
                lows.append((v, op in _LOW_INC, u, sp))
            elif op in _HIGH_INC or op in _HIGH_EXC:
                highs.append((v, op in _HIGH_INC, u, sp))
            elif op == "до":
                highs.append((v, True if m.group("inc") else None, u, sp))
        if lows or highs:
            lo = lows[0] if lows else None
            hi = highs[0] if highs else None
            unit = (hi[2] if hi else "") or (lo[2] if lo else "")
            sm = _SUBJECT.search(t)
            subj = re.findall(r"[\wё]+", t[sm.start():])[0] if sm else "значение"
            qs = min(x[3][0] for x in (lo, hi) if x)
            qe = max(x[3][1] for x in (lo, hi) if x)
            ctx.ranges.append(_make_range(ctx, b, (s, e), (qs, qe), level, subj, lo[0] if lo else None, hi[0] if hi else None,
                                          lo[1] if lo else None, hi[1] if hi else None, unit, t))
    for t in ctx.scan.params:
        for p in _params_of(ctx, t):
            if p.location == "response" or p.logic_cell is None:
                continue
            m = _RANGE_DASH.search(p.logic) or _RANGE_FROM_TO.search(p.logic)
            if not m:
                continue
            lo, hi = dec(m.group("a")), dec(m.group("b"))
            if hi <= lo:
                continue
            um = _UNIT_RE.search(p.desc) or _UNIT_RE.search(p.logic)
            unit = unit_canon(um.group(0)) if um else ""
            cell = p.logic_cell
            rng = _make_range(ctx, p.block, p.span, (cell.start + m.start(), cell.start + m.end()), "api", p.name, lo, hi, None, None, unit,
                              norm(p.fmt + " " + p.logic + " " + p.desc), integer_hint=bool(re.search(r"\binteger\b|\bint\b|int32|int64|цел", norm(p.fmt))))
            rng.param = p
            ctx.ranges.append(rng)
    # Подсказки о границах и целочисленности в том же разделе (например, «обе границы включены»).
    for rng in ctx.ranges:
        for kind, hb, hsp, hunit in hints:
            if not _hint_scope(rng.block, hb) or (hunit and rng.unit and hunit != rng.unit):
                continue
            ev = ctx.doc.ev(hb, *hsp)
            if kind in ("inc", "exc") and (rng.lo_inc is None or rng.hi_inc is None):
                flag = kind == "inc"
                rng.lo_inc = flag if rng.lo_inc is None and rng.lo is not None else rng.lo_inc
                rng.hi_inc = flag if rng.hi_inc is None and rng.hi is not None else rng.hi_inc
                rng.evidence.append(ev)
                rng.notes.append(f"включённость границ — по «{short(ev['quote'], 80)}» ({ctx.doc.label(ev)})")
            elif kind == "int" and rng.integer is None:
                rng.integer = True
                rng.evidence.append(ev)
    for rng in ctx.ranges:
        if rng.integer is None and all(v is None or v == v.to_integral_value() for v in (rng.lo, rng.hi)):
            rng.notes.append("целочисленность в тексте не указана: шаг 1 принят по виду границ")


def _subject(prefix: str) -> str:
    """Предмет диапазона: ближайшее к нему слово-предмет («порог», «лимит», «сумма»…), иначе «значение»."""
    for w in reversed(re.findall(r"[\wё]+", norm(prefix))):
        if _SUBJECT.match(w):
            return w
    return "значение"


def _make_range(ctx: Ctx, block: Block, span: tuple[int, int], qspan: tuple[int, int], level: str, subject: str,
                lo: Decimal | None, hi: Decimal | None, lo_inc: bool | None, hi_inc: bool | None, unit: str, t: str,
                integer_hint: bool | None = None) -> Range:
    integer = True if (integer_hint or _INT_HINT.search(t)) else None
    bounds = ":".join(_plain(v) if v is not None else "" for v in (lo, hi))
    key = f"range:{level}:{norm(subject)}:{bounds}"
    n = sum(1 for r in ctx.ranges if r.key == key or r.key.startswith(key + "#"))
    if n:
        key += f"#{n + 1}"
    return Range(key, level, subject, lo, hi, lo_inc, hi_inc, integer, unit, block, span, [ctx.doc.ev(block, *qspan)], [])


def _params_of(ctx: Ctx, t: Table) -> list[Param]:
    hdr = [c.ntext for c in t.header]

    def col(rx: str) -> int | None:
        return next((i for i, h in enumerate(hdr) if re.search(rx, h)), None)

    ci = {
        "name": col(r"parameter|параметр|^поле|name"), "fmt": col(r"format|формат|\bтип\b|type"),
        "mand": col(r"mandatory|обязат|required"), "logic": col(r"logic|логик|допустим|правил|values|значени"),
        "desc": col(r"description|описани"),
    }
    sec = " ".join(norm(s) for s in t.section[-2:])
    location = "response" if re.search(r"ответ|response", sec) else "path" if "path" in sec else "body" if re.search(r"body|тело", sec) else "query" if "query" in sec else "request"
    out = []
    for r in t.body:
        def cell(k: str, r: list[Cell] = r) -> Cell | None:
            i = ci[k]
            return r[i] if i is not None and i < len(r) else None
        name_c = cell("name") or r[0]
        name = name_c.text.strip().strip("`* ")
        if not name:
            continue
        mand_c = cell("mand")
        mand = None if mand_c is None else (True if re.match(r"да|yes|обязат|required|true", mand_c.ntext) else False)
        cells = [c for c in r if c.block is r[0].block]
        span = (cells[0].start, cells[-1].end) if cells else (0, len(r[0].block.text))
        out.append(Param(name, (cell("fmt").text if cell("fmt") else ""), mand, (cell("logic").text if cell("logic") else ""),
                         (cell("desc").text if cell("desc") else ""), location, r[0].block, span, cell("logic")))
    return out


def extract_api(ctx: Ctx) -> None:
    doc, scan = ctx.doc, ctx.scan
    api = Api()
    for t in scan.kv:
        for r in t.body:
            if len(r) < 2:
                continue
            key, val = r[0].ntext, r[1]
            ev = doc.ev(val.block, val.start, val.end)
            if re.search(r"rest type|http method|\bmethod\b|метод|тип запроса", key):
                m = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", val.text)
                if m and api.method is None:
                    api.method, api.method_ev = m.group(1), ev
            elif re.search(r"request url|\burl\b|endpoint|путь|адрес", key) and "type" not in key:
                m = re.search(r"(/[\w\-./{}]+)", val.text)
                if m and api.path is None:
                    api.path, api.path_ev = m.group(1).rstrip("."), ev
            elif re.search(r"authoriz|авторизац", key) and api.auth is None:
                api.auth, api.auth_ev = val.text.strip(), ev
            elif "curl" in key:
                m = re.search(r"(?:--data(?:-urlencode)?|-d)\s+['\"]([^'\"]+)['\"]", val.text) or re.search(r"\?([^\"'\s]+)", val.text)
                if m:
                    for pair in m.group(1).split("&"):
                        k, _, v = pair.partition("=")
                        if k:
                            api.curl[k.strip()] = v.strip()
    for t in scan.params:
        api.params += [p for p in _params_of(ctx, t) if p.location != "response"]
    cur: int | None = None
    blocks = [b for b in doc.blocks if _is_api_block(b) and b.id not in scan.excluded]
    for b in blocks:
        if b.is_heading:
            title = b.text.strip().lstrip("#").strip()
            m = re.match(r"^\W*([1-5]\d\d)\b\.?\s*(.*)$", title)
            cur = int(m.group(1)) if m else None
            if m:
                api.st(cur).titles.append((m.group(2), doc.ev(b, 0, len(b.text))))
            continue
        if b.is_code or b.text.strip().startswith("{"):
            if cur is not None:
                s, e = _code_text(b)
                api.st(cur).examples.append((b.text[s:e], doc.ev(b, s, e)))
            continue
        if b.id in scan.row_of:
            continue
        pos = 0
        for line in b.text.split("\n"):
            ls, le = pos, pos + len(line)
            pos = le + 1
            m = _STATUS_LINE.match(line)
            if m:
                code = int(m.group("code"))
                rest = m.group("rest")
                if rest.strip():
                    rs = ls + m.start("rest")
                    re_ = ls + m.end("rest")
                    api.st(code).descs.append((_COND_PREFIX.sub("", rest).rstrip(". "), doc.ev(b, rs, re_)))
                else:
                    cur = code
                continue
            for s, e in sentences(line):
                seg = line[s:e]
                mm = _MENTION.search(seg)
                if mm:
                    api.mentions.append({
                        "code": int(mm.group("code")), "under": cur, "cond": mm.group("cond"), "cond2": mm.group("cond2"),
                        "ev": doc.ev(b, ls + s, ls + e),
                    })
                    continue
                api.logic.append((seg, doc.ev(b, ls + s, ls + e)))
                if re.search(r"отклонен|неверн|некоррект|ошибк|\berror\b", norm(seg)):
                    api.rejections.append((seg, doc.ev(b, ls + s, ls + e)))
    if api.method or api.path or api.statuses or api.params:
        ctx.api = api


def _examples(ctx: Ctx) -> None:
    rng = next((r for r in ctx.ranges if r.level == "business" and re.search(r"порог|лимит|бюджет", norm(r.subject))), None)
    rng = rng or next((r for r in ctx.ranges if r.level == "business"), None) or next(iter(ctx.ranges), None)
    T = S = None
    for row in ctx.rows:
        t, s = row.get("T"), row.get("S")
        if t is not None and (rng is None or rng.contains(t)):
            T, S = t, (s if s is not None and 0 < s < t else None)
            break
    if T is None:
        T = rng.lo if rng and rng.lo and rng.lo > 0 else (rng.hi if rng and rng.hi else Decimal(10000))
    if S is None:
        S = max(_nice(T / 10), Decimal(1))
    ctx.T, ctx.S = T, S
    ctx.unit = rng.unit if rng and rng.unit else ("₸" if any("₸" in b.text for b in ctx.doc.blocks) else "")
    ctx.range_main = rng
    tiyn = ctx.first("tiyn")
    if tiyn and ctx.unit == "₸":
        ctx.spend_step = (Decimal("0.01"), ctx.rule_ev(tiyn))
    else:
        ctx.spend_step = (rng.step if rng else Decimal(1), None)
    for row in ctx.rows:
        if row.get("dates"):
            ctx.month = row["dates"][0]["month"]
            break


def _u(ctx: Ctx, d: Decimal) -> str:
    return with_unit(d, ctx.unit)


def _second_threshold(ctx: Ctx) -> Decimal:
    rng = ctx.range_main
    t2 = ctx.T * 2
    if rng is None or rng.contains(t2):
        return t2
    if rng.hi is not None and rng.hi > ctx.T:
        return rng.hi if rng.hi_inc is not False else rng.hi - rng.step
    return ctx.T + ctx.S


# ---------------------------------------------------------------- генераторы сценариев


def gen_ranges(ctx: Ctx) -> None:
    for rng in ctx.ranges:
        step = rng.step
        pts: list[tuple[str, Decimal, str]] = []
        if rng.lo is not None:
            if rng.lo_inc is True:
                pts += [("lo-1", rng.lo - step, "reject"), ("lo", rng.lo, "accept")]
            elif rng.lo_inc is False:
                pts += [("lo", rng.lo, "reject"), ("lo+1", rng.lo + step, "accept")]
            else:
                pts += [("lo-1", rng.lo - step, "reject"), ("lo", rng.lo, "open")]
        if rng.hi is not None:
            if rng.hi_inc is True:
                pts += [("hi", rng.hi, "accept"), ("hi+1", rng.hi + step, "reject")]
            elif rng.hi_inc is False:
                pts += [("hi-1", rng.hi - step, "accept"), ("hi", rng.hi, "reject")]
            else:
                pts += [("hi", rng.hi, "open"), ("hi+1", rng.hi + step, "reject")]
        if rng.integer and rng.lo is not None and rng.hi is not None and rng.hi - rng.lo >= 1:
            pts.append(("fraction", rng.lo + Decimal("0.5"), "reject"))
        for pos, val, outcome in pts:
            _range_case(ctx, rng, pos, val, outcome)


_POS_LABEL = {
    "lo-1": "на {step} ниже нижней границы", "lo": "нижняя граница", "lo+1": "на {step} выше нижней границы",
    "hi": "верхняя граница", "hi-1": "на {step} ниже верхней границы", "hi+1": "на {step} выше верхней границы",
    "fraction": "нецелое значение внутри диапазона",
}


def _range_case(ctx: Ctx, rng: Range, pos: str, val: Decimal, outcome: str) -> None:
    label = _POS_LABEL[pos].format(step=with_unit(rng.step, rng.unit))
    shown = with_unit(val, rng.unit)
    subject = rng.subject
    values = {"input": jnum(val), "unit": rng.unit, "boundary": pos, "range": [jnum(rng.lo) if rng.lo is not None else None, jnum(rng.hi) if rng.hi is not None else None]}
    key = f"{rng.key}:{pos}"
    notes = list(rng.notes)
    anchor = (rng.block, rng.span)
    if rng.level == "api" and ctx.api is not None and rng.param is not None:
        api, p = ctx.api, rng.param
        query = _query(ctx, p.name, _plain(val))
        pre = f"Метод {api.call}; параметр `{p.name}` ({p.fmt.strip() or 'тип не указан'}): допустимо {rng.describe()}; остальные параметры корректны"
        if api.auth:
            pre += f"; авторизация: {api.auth}"
        act = f"вызвать `{api.method or ''} {api.path or ''}?{query}`".replace("` ", "`").replace(" ?", "?")
        ok = _success_text(ctx, f"{p.name}={_plain(val)}")
        rej = _api_rejection(ctx, p)
        evid = [e for e in (api.method_ev, api.path_ev) if e] + rng.evidence + _param_logic(api, p)
        title_core = f"`{p.name}`={_plain(val)}"
        if outcome == "accept":
            ctx.add(key, kind="boundary", level="api", title=f"{title_core}: {label} — принимается", precondition=pre, action=act,
                    expected=ok[0], anchor=anchor, evidence=evid + ok[1], values=values, notes=notes)
        elif outcome == "reject":
            _api_reject_case(ctx, key, f"{title_core}: {label} — отклоняется", pre, act, rej, anchor, evid, values, notes, p)
        else:
            opts = [
                {"label": "граница включена", "expected": ok[0], "basis": "граница входит в диапазон", "evidence": ok[1]},
                {"label": "граница не включена", "expected": _rej_text(rej), "basis": "граница не входит в диапазон", "evidence": [e for o in rej for e in o["evidence"]]},
            ]
            ctx.add(key, kind="boundary", level="api", title=f"{title_core}: {label} — включена ли граница", precondition=pre, action=act,
                    options=opts, question=(f"{rng.key}:inclusive", f"Включены ли границы диапазона `{p.name}` {rng.describe()}?"),
                    anchor=anchor, evidence=evid, values=values, notes=notes)
        return
    src = ctx.src(Rule("range", rng.block, rng.span))
    pre = f"Правило {src}: «{ctx.quote(Rule('range', rng.block, rng.span))}». Допустимо {rng.describe()}"
    act = f"задать {subject} {shown} ({label})"
    accept = f"значение {shown} принимается и сохраняется"
    reject = f"значение {shown} отклоняется, {subject} не сохраняется"
    evid = list(rng.evidence)
    if ctx.ui_error:
        reject += f"; {ctx.ui_error[0].rstrip('.').strip()[0].lower()}{ctx.ui_error[0].rstrip('.').strip()[1:]}"
        if outcome != "accept":
            evid.append(ctx.ui_error[1])
    title_core = f"{subject.capitalize()} {shown}"
    if outcome == "accept":
        ctx.add(key, kind="boundary", level=rng.level, title=f"{title_core}: {label} — принимается", precondition=pre, action=act,
                expected=accept, anchor=anchor, evidence=evid, values=values, notes=notes)
    elif outcome == "reject":
        ctx.add(key, kind="boundary", level=rng.level, title=f"{title_core}: {label} — отклоняется", precondition=pre, action=act,
                expected=reject, anchor=anchor, evidence=evid, values=values, notes=notes)
    else:
        opts = [
            {"label": "граница включена", "expected": accept, "basis": "граница входит в диапазон", "evidence": []},
            {"label": "граница не включена", "expected": reject, "basis": "граница не входит в диапазон", "evidence": []},
        ]
        ctx.add(key, kind="boundary", level=rng.level, title=f"{title_core}: {label} — включена ли граница", precondition=pre, action=act,
                options=opts, question=(f"{rng.key}:inclusive", f"Включены ли границы диапазона {rng.describe()} в правиле {src}?"),
                anchor=anchor, evidence=evid, values=values, notes=notes)


def _query(ctx: Ctx, name: str, value: str) -> str:
    api = ctx.api
    assert api is not None
    pairs = []
    for p in api.params:
        if p.location not in ("query", "request"):
            continue
        v = value if p.name == name else _valid_value(ctx, p)
        pairs.append(f"{p.name}={v}")
    if not any(pp.startswith(name + "=") for pp in pairs):
        pairs.append(f"{name}={value}")
    return "&".join(pairs)


def _valid_value(ctx: Ctx, p: Param) -> str:
    api = ctx.api
    assert api is not None
    rng = next((r for r in ctx.ranges if r.param is p), None)
    cv = api.curl.get(p.name)
    if rng is not None:
        try:
            if cv is not None and rng.contains(dec(cv)):
                return cv
        except InvalidOperation:
            pass
        v = rng.lo if rng.lo is not None and rng.lo_inc is not False else (rng.lo + rng.step if rng.lo is not None else rng.hi)
        return _plain(v or Decimal(0))
    enum = _enum_values(p)
    if enum:
        return cv if cv in enum else enum[-1]
    return cv or f"<{p.name}>"


def _enum_values(p: Param) -> list[str]:
    logic = norm(p.logic).replace("«", "").replace("»", "").replace('"', "")
    if not logic or _RANGE_DASH.search(p.logic):
        return []
    parts = [x.strip() for x in re.split(r"\s*(?:,|/|\bили\b)\s*", logic) if x.strip()]
    if len(parts) >= 2 and all(re.fullmatch(r"[\w.-]{1,20}", x) for x in parts):
        return parts
    return []


def _success_text(ctx: Ctx, saved: str) -> tuple[str, list[dict]]:
    api = ctx.api
    assert api is not None
    codes = sorted(c for c in api.statuses if 200 <= c < 300)
    for c in codes:
        st = api.statuses[c]
        ok = next(((x, e) for x, e in st.examples if _is_ok_example(x)), None)
        if ok:
            res = _json(ok[0])
            has_result = isinstance(res, Mapping) and "result" in res
            text = f"успешный ответ HTTP {c}{', `result` = ' + str(res['result']) if has_result else ''}; сохранено {saved}"
            return text, [ok[1]] + [e for _, e in st.descs[:1]]
    if codes:
        st = api.statuses[codes[0]]
        return f"успешный ответ HTTP {codes[0]}; сохранено {saved}", [e for _, e in st.descs[:1]]
    return f"запрос выполнен успешно; сохранено {saved}", []


def _api_rejection(ctx: Ctx, p: Param) -> list[dict]:
    api = ctx.api
    assert api is not None
    opts: list[dict] = []
    for code in sorted(api.statuses):
        if not 400 <= code < 500:
            continue
        st = api.statuses[code]
        hit = next(((d, e) for d, e in st.descs + st.titles if re.search(r"неверн|некоррект|невалид|invalid|bad request|не прош\w* проверк|валидац", norm(d))), None)
        if hit:
            body = st.examples[0] if st.examples else None
            text = f"ответ HTTP {code}" + (f" с телом `{body[0]}`" if body else "") + "; сохранённая настройка не меняется"
            opts.append({"label": f"HTTP {code}", "expected": text, "basis": f"статус {code}: «{short(hit[0], 80)}»",
                         "evidence": [hit[1]] + ([body[1]] if body else [])})
            break
    stems = param_stems(p)
    related = [(s, e) for s, e in api.rejections if any(st in norm(s) for st in stems)]
    for code in sorted(c for c in api.statuses if 200 <= c < 300):
        st = api.statuses[code]
        for ex, eev in st.examples:
            if not _is_error_example(ex):
                continue
            if not (any(st_ in norm(ex) for st_ in stems) or related):
                continue
            text = f"ответ HTTP {code} с телом `{ex}`"
            prev = next(((s, e) for s, e in related if re.search(r"прежн", norm(s))), None)
            if prev:
                text += "; возвращается прежнее состояние настройки"
            basis = f"пример ответа {code} с ошибкой" + (f" и «{short(related[0][0], 70)}»" if related else "")
            opts.append({"label": f"HTTP {code} + ERROR", "expected": text, "basis": basis, "evidence": [eev] + [e for _, e in related[:1]]})
            break
        if len(opts) >= 2:
            break
    return opts


def _param_logic(api: Api, p: Param) -> list[dict]:
    stems = param_stems(p)
    return [ev for seg, ev in api.logic
            if any(st in norm(seg) for st in stems) and re.search(r"провер|валид|контрол", norm(seg)) and not re.search(_REJECT, norm(seg))]


def _rej_text(opts: list[dict]) -> str:
    if not opts:
        return "запрос отклоняется (код ответа в документе не определён)"
    return " или ".join(o["expected"] for o in opts)


def _api_reject_case(ctx: Ctx, key: str, title: str, pre: str, act: str, rej: list[dict], anchor: tuple[Block, tuple[int, int]],
                     evid: list[dict], values: dict, notes: list[str], p: Param) -> None:
    if len(rej) >= 2:
        q = (f"api-reject:{p.name}",
             f"Как {ctx.api.call if ctx.api else 'метод'} отвечает на недопустимое значение `{p.name}`: "
             + " или ".join(f"{o['label']} ({o['basis']})" for o in rej) + "?")
        ctx.add(key, kind="api_validation", level="api", title=title, precondition=pre, action=act, options=[dict(o) for o in rej],
                question=q, anchor=anchor, evidence=evid, values=values, notes=notes)
    elif rej:
        ctx.add(key, kind="api_validation", level="api", title=title, precondition=pre, action=act, expected=rej[0]["expected"],
                anchor=anchor, evidence=evid + rej[0]["evidence"], values=values, notes=notes)
    else:
        ctx.add(key, kind="api_validation", level="api", title=title, precondition=pre, action=act,
                expected="запрос отклоняется; код ответа и тело в документе не определены — уточнить", anchor=anchor, evidence=evid,
                values=values, notes=notes + ["ответ на недопустимое значение в документе не описан"], needs_clarification=True)


def gen_api(ctx: Ctx) -> None:
    api = ctx.api
    if api is None:
        return
    call = api.call
    base_ev = [e for e in (api.method_ev, api.path_ev) if e]
    anchor_ev = api.path_ev or api.method_ev
    # Успешный вызов с корректными параметрами.
    if api.params and anchor_ev:
        query = "&".join(f"{p.name}={_valid_value(ctx, p)}" for p in api.params if p.location in ("query", "request"))
        ok = _success_text(ctx, query.replace("&", ", "))
        ok = (ok[0], ok[1] + api.logic_ev(r"вернуть\s+результат|сохранить\s+настройк|записать\s+настройк|заменить\s+настройк", _REJECT))
        b = ctx.doc.by_id[anchor_ev["block_id"]]
        ctx.add("api:success", kind="api_success", level="api", title=f"{call}: корректный запрос сохраняет настройку",
                precondition=f"Метод {call}" + (f"; авторизация: {api.auth}" if api.auth else "") + "; все параметры корректны",
                action=f"вызвать `{api.method or ''} {api.path or ''}?{query}`".replace("` ", "`").replace(" ?", "?"),
                expected=ok[0], anchor=(b, (anchor_ev["start"], anchor_ev["end"])), evidence=base_ev + ok[1] + ([api.auth_ev] if api.auth_ev else []))
    # Допустимый список значений (например, «0 или 1»).
    for p in api.params:
        enum = _enum_values(p)
        if not enum or not all(re.fullmatch(r"-?\d+", v) for v in enum):
            continue
        bad = str(max(int(v) for v in enum) + 1)
        rej = _api_rejection(ctx, p)
        pre = f"Метод {call}; параметр `{p.name}`: допустимо {', '.join(enum)}; остальные параметры корректны"
        act = f"вызвать `{api.method or ''} {api.path or ''}?{_query(ctx, p.name, bad)}`".replace("` ", "`").replace(" ?", "?")
        ev = ([ctx.doc.ev(p.logic_cell.block, p.logic_cell.start, p.logic_cell.end)] if p.logic_cell else []) + _param_logic(api, p)
        _api_reject_case(ctx, f"api:enum:{p.name}", f"`{p.name}`={bad}: значение вне списка {', '.join(enum)} — отклоняется", pre, act, rej,
                         (p.block, p.span), base_ev + ev, {"input": int(bad), "allowed": enum}, [], p)
    # Статусы: условия из описаний, расхождение заголовка и текста.
    conflict_under = {m["under"] for m in api.mentions if m["under"] and m["under"] != m["code"]}
    validation_codes = {code for code, st in api.statuses.items()
                        if any(re.search(r"неверн|некоррект|невалид|invalid|bad request|валидац", norm(d)) for d, _ in st.descs + st.titles)}
    for code in sorted(api.statuses):
        st = api.statuses[code]
        if 200 <= code < 300 or code in validation_codes or code in conflict_under or not st.descs:
            continue
        cond, cev = st.descs[0]
        body = st.examples[0] if st.examples else None
        b = ctx.doc.by_id[cev["block_id"]]
        ctx.add(f"api:status:{code}", kind="api_status", level="api", title=f"{call}: статус {code} — {short(cond, 60)}",
                precondition=f"Метод {call}" + (f"; авторизация: {api.auth}" if api.auth else ""),
                action=f"вызвать {call}, когда {cond}",
                expected=f"ответ HTTP {code}" + (f" с телом `{body[0]}`" if body else " (тело ответа в документе не приведено)"),
                anchor=(b, (cev["start"], cev["end"])),
                evidence=base_ev + [cev] + ([body[1]] if body else []) + (api.logic_ev(_STATUS_LOGIC[code]) if code in _STATUS_LOGIC else []),
                needs_clarification=body is None)
    for m in api.mentions:
        code, under = m["code"], m["under"]
        body = api.statuses.get(code).examples[0] if api.statuses.get(code) and api.statuses[code].examples else None
        b = ctx.doc.by_id[m["ev"]["block_id"]]
        anchor = (b, (m["ev"]["start"], m["ev"]["end"]))
        exp_code = f"ответ HTTP {code}" + (f" с телом `{body[0]}`" if body else "")
        if m["cond"] and under and under != code:
            ust = api.statuses.get(under)
            udesc = ust.descs[0] if ust and ust.descs else None
            utitle = ust.titles[0] if ust and ust.titles else None
            opts = [
                {"label": f"HTTP {under}", "expected": f"ответ HTTP {under}",
                 "basis": "заголовок раздела «" + short(utitle[0] if utitle else str(under), 50) + "»" + (f" и описание статуса «{short(udesc[0], 60)}»" if udesc else ""),
                 "evidence": [e for e in ((utitle[1] if utitle else None), (udesc[1] if udesc else None)) if e]},
                {"label": f"HTTP {code}", "expected": exp_code, "basis": f"фраза «{short(m['ev']['quote'], 70)}»",
                 "evidence": [m["ev"]] + ([body[1]] if body else [])},
            ]
            ctx.add(f"api:mention:{code}:{norm(m['cond'])}", kind="api_status", level="api", title=f"{call}: для {m['cond'].strip()} — статус {under} или {code}",
                    precondition=f"Метод {call}" + (f"; авторизация: {api.auth}" if api.auth else ""), action=f"вызвать {call} для {m['cond'].strip()}",
                    options=opts, question=(f"api-status:{under}:{code}", f"Какой статус возвращает {call} для {m['cond'].strip()}: {under} (как в заголовке раздела) или {code} (как в тексте)?"),
                    anchor=anchor, evidence=base_ev + api.logic_ev(_STATUS_LOGIC.get(under, r"(?!)")))
            conds = [m["cond2"]] if m["cond2"] else []
        else:
            conds = [c for c in (m["cond"], m["cond2"]) if c]
        for c in conds:
            ctx.add(f"api:mention:{code}:{norm(c)}", kind="api_status", level="api", title=f"{call}: для {c.strip()} — статус {code}",
                    precondition=f"Метод {call}" + (f"; авторизация: {api.auth}" if api.auth else ""), action=f"вызвать {call} для {c.strip()}",
                    expected=exp_code, anchor=anchor, evidence=base_ev + ([body[1]] if body else []) + api.logic_ev(_STATUS_LOGIC.get(code, r"(?!)")),
                    notes=[] if code in api.statuses and api.statuses[code].descs else [f"статус {code} не входит в перечень статусов метода"])
    replace = ctx.first("replace")
    rng = next((r for r in ctx.ranges if r.param is not None), None)
    if replace and rng and rng.lo is not None and rng.hi is not None and _is_api_block(replace.block):
        a1 = _valid_value(ctx, rng.param)
        a2 = _plain(rng.hi if rng.hi_inc is not False else rng.hi - rng.step)
        if a2 == a1:
            a2 = _plain(rng.lo if rng.lo_inc is not False else rng.lo + rng.step)
        ctx.add("api:replace", kind="api_replace", level="api", title=f"{call}: повторное сохранение заменяет настройку",
                precondition=f"Сохранена настройка `{rng.param.name}`={a1}", action=f"повторно вызвать {call} с `{rng.param.name}`={a2}",
                expected=f"действует одна настройка с `{rng.param.name}`={a2}, прежняя заменена",
                anchor=(replace.block, replace.span), evidence=base_ev)


def gen_default(ctx: Ctx) -> None:
    for r in ctx.rules.get("default", []):
        what = r.data.get("what", "").strip()
        if not what:
            continue
        ctx.add(f"default:{norm(what)}", kind="default", level="api" if _is_api_block(r.block) else "business",
                title=f"Значение по умолчанию: {what}", precondition="Настройка ещё не сохранялась (новое состояние)",
                action="открыть настройку или запросить её текущее состояние", expected=f"{what} (значение по умолчанию)",
                anchor=(r.block, r.span))


def gen_month(ctx: Ctx) -> None:
    r = ctx.first("month")
    if r is None:
        return
    src, q = ctx.src(r), ctx.quote(r)
    tz = r.data.get("tz")
    M, N = ctx.month, (ctx.month + 1) % 12
    last = MONTH_DAYS[M]
    phrase = tz["phrase"] if tz else ""
    notes = [tz["note"]] if tz and tz.get("note") else []
    pre = f"Правило {src}: «{q}»"
    S = _u(ctx, ctx.S)
    if tz is None:
        notes.append("часовой пояс расчётного месяца не указан — уточнить у владельца")
    ctx.add("month:last_minute", kind="month", level="business", title=f"Последняя минута месяца: покупка {last} {MONTHS_GEN[M]} в 23:59",
            precondition=pre, action=f"совершить покупку на {S} {last} {MONTHS_GEN[M]} в 23:59 {phrase} и провести её в тот же день".replace("  ", " "),
            expected=f"покупка учтена в расходах {MONTHS_GEN[M]}", anchor=(r.block, r.span), notes=notes, needs_clarification=tz is None,
            values={"date": f"{last:02d}.{M + 1:02d}", "time": "23:59", "tz": tz["iana"] if tz else None})
    if tz and tz.get("offset"):
        off = int(tz["offset"])
        if off > 0:
            ctx.add("month:tz_boundary", kind="month", level="business", title=f"Часовой пояс: 00:00 1 {MONTHS_GEN[N]} {phrase} — уже в {MONTHS_PREP[N]}",
                    precondition=pre,
                    action=f"совершить покупку на {S} 1 {MONTHS_GEN[N]} в 00:00 {phrase} (это {last} {MONTHS_GEN[M]} {24 - off:02d}:00 UTC) и провести её",
                    expected=f"покупка учтена в расходах {MONTHS_GEN[N]}, а не {MONTHS_GEN[M]}: месяц считается по местному времени, а не по UTC",
                    anchor=(r.block, r.span), notes=notes, values={"local": f"01.{N + 1:02d} 00:00", "utc": f"{last:02d}.{M + 1:02d} {24 - off:02d}:00", "offset": off})
    if not any(row.get("cross_month") for row in ctx.rows) and r.data.get("basis_kind") in ("transaction", "posting"):
        target = M if r.data["basis_kind"] == "transaction" else N
        ctx.add("month:cross_posting", kind="month", level="business", title="Покупка в конце месяца проведена в следующем",
                precondition=pre, action=f"совершить покупку на {S} {last} {MONTHS_GEN[M]} в 23:59 {phrase}, провести её 1 {MONTHS_GEN[N]} в 00:05 {phrase}".replace("  ", " "),
                expected=f"покупка учтена в расходах {MONTHS_GEN[target]} (по дате {r.data['basis_word']})", anchor=(r.block, r.span), notes=notes)


def _short_participle(word: str) -> str:
    w = norm(word)
    for end, rep in (("енные", "ена"), ("анные", "ана"), ("ные", "на"), ("тые", "та")):
        if w.endswith(end):
            return w[: -len(end)] + rep
    return f"в состоянии «{word}»"


def _items(text: str) -> list[str]:
    return [x.strip(" ,") for x in re.split(r",|\s+и\s+|\s+или\s+", text) if x.strip(" ,")]


def _stem_match(a: str, b: str) -> bool:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n >= 5 or (n >= 4 and a[:4] not in {"пере", "пред", "прои", "пров", "пото", "посл"})


def gen_events(ctx: Ctx) -> None:
    T, S = ctx.T, ctx.S
    R = T - S
    for r in ctx.rules.get("include", []):
        items = _items(r.data.get("items", ""))
        if not items:
            continue
        words = items[0].split()
        if len(words) >= 2 and re.search(r"(?:нные|анные|енные|тые|ные)$", norm(words[0])):
            done = _short_participle(words[0])
            ctx.add(f"event:not_final:{norm(items[0])}", kind="event_type", level="business",
                    title=f"Операция ещё не {done} — в расходы не входит",
                    precondition=f"Расходы месяца {_u(ctx, R)}, порог {_u(ctx, T)}; правило {ctx.src(r)}: «{ctx.quote(r)}»",
                    action=f"поступает покупка на {_u(ctx, S)}, которая ещё не {done} (например, только авторизована)",
                    expected=f"расходы остаются {_u(ctx, R)}, push не отправляется; сумма учитывается после того, как покупка {done}",
                    anchor=(r.block, r.span), notes=["момент, когда покупка считается проведённой, требует определения в документе"])
    covered = {norm(w) for row in ctx.rows for w in re.findall(r"[\wё]+", row["act"])}
    for r in ctx.rules.get("exclude", []):
        for item in _items(r.data.get("items") or r.data.get("items2") or ""):
            stem = norm(item).split()[0] if norm(item) else ""
            if not stem or any(_stem_match(stem, w) for w in covered):
                continue
            ctx.add(f"event:exclude:{norm(item)}", kind="event_type", level="business", title=f"Исключённая операция «{item}» не входит в расходы",
                    precondition=f"Расходы месяца {_u(ctx, R)}, порог {_u(ctx, T)}; правило {ctx.src(r)}: «{ctx.quote(r)}»",
                    action=f"выполнить операцию «{item}» на {_u(ctx, S)}",
                    expected=f"расходы месяца остаются {_u(ctx, R)}; push не отправляется", anchor=(r.block, r.span))


def gen_refund(ctx: Ctx) -> None:
    r = ctx.first("refund")
    if r is None:
        return
    M, N = ctx.month, (ctx.month + 1) % 12
    T, S = ctx.T, ctx.S
    R = T - S
    what = norm(r.data.get("what", ""))
    pre = (f"Правило {ctx.src(r)}: «{ctx.quote(r)}». Расходы {MONTHS_GEN[M]}: {_u(ctx, R)}, в том числе покупка на {_u(ctx, S)} "
           f"от 15 {MONTHS_GEN[M]}; расходы {MONTHS_GEN[N]}: 0")
    act = f"3 {MONTHS_GEN[N]} провести полный возврат этой покупки на {_u(ctx, S)}"
    orig = f"расходы {MONTHS_GEN[M]} уменьшились на {_u(ctx, S)} (до {_u(ctx, R - S)}); расходы {MONTHS_GEN[N]} не изменились"
    own = f"расходы {MONTHS_GEN[N]} уменьшились на {_u(ctx, S)}; расходы {MONTHS_GEN[M]} не изменились ({_u(ctx, R)})"
    if "исходн" in what or "первоначальн" in what:
        ctx.add("refund:cross_month", kind="refund", level="business", title="Возврат в следующем месяце уменьшает месяц исходной покупки",
                precondition=pre, action=act, expected=orig, anchor=(r.block, r.span))
    elif "возврат" in what or "текущ" in what:
        ctx.add("refund:cross_month", kind="refund", level="business", title="Возврат уменьшает расходы месяца возврата",
                precondition=pre, action=act, expected=own, anchor=(r.block, r.span))
    else:
        ctx.add("refund:cross_month", kind="refund", level="business", title="Возврат в следующем месяце: какой месяц уменьшается",
                precondition=pre, action=act, anchor=(r.block, r.span),
                options=[{"label": "месяц исходной покупки", "expected": orig, "basis": "толкование правила", "evidence": []},
                         {"label": "месяц возврата", "expected": own, "basis": "толкование правила", "evidence": []}],
                question=("refund:month", f"Расходы какого месяца уменьшает возврат по правилу {ctx.src(r)}: месяца исходной покупки или месяца возврата?"))


def gen_trigger(ctx: Ctx) -> None:
    r = ctx.first("trigger")
    if r is None:
        return
    t = r.data["norm"]
    inclusive = bool(re.search(r"равн\w*\s+порогу|не\s+ниже\s+порога|не\s+менее\s+порога|достиг", t)) or not re.search(r"превыш", t)
    T, S = ctx.T, ctx.S
    step, step_ev = ctx.spend_step
    R = T - S
    pre = f"Правило {ctx.src(r)}: «{ctx.quote(r)}». Порог {_u(ctx, T)}, в этом месяце push ещё не было, расходы {_u(ctx, R)}"
    notes = [f"шаг {_u(ctx, step)}: суммы покупок хранятся в тиынах ({ctx.doc.label(step_ev)})"] if step_ev else []
    ev = [step_ev] if step_ev else []
    below = S - step
    ctx.add("trigger:just_below", kind="trigger", level="business", title=f"Расходы на {_u(ctx, step)} ниже порога — push нет",
            precondition=pre, action=f"провести покупку на {_u(ctx, below)}",
            expected=f"расходы {_u(ctx, R + below)} (ниже порога), push не отправляется", anchor=(r.block, r.span), evidence=ev, notes=notes,
            values={"before": jnum(R), "purchase": jnum(below), "threshold": jnum(T)})
    if not any(row.get("equal_threshold") for row in ctx.rows):
        ctx.add("trigger:equal", kind="trigger", level="business", title="Расходы ровно на пороге",
                precondition=pre, action=f"провести покупку на {_u(ctx, S)}",
                expected=f"расходы {_u(ctx, T)}; " + ("отправлен один push" if inclusive else "push не отправляется: порог нужно превысить"),
                anchor=(r.block, r.span), values={"before": jnum(R), "purchase": jnum(S), "threshold": jnum(T)})
    cap = ctx.first("cap")
    ctx.add("trigger:already_above", kind="trigger", level="business", title="Порог уже достигнут — новая покупка не даёт второго push",
            precondition=f"Правило {ctx.src(r)}: «{ctx.quote(r)}». Порог {_u(ctx, T)}; в этом месяце push уже отправлен, расходы {_u(ctx, T + S)}",
            action=f"провести ещё одну покупку на {_u(ctx, S)}",
            expected=f"расходы {_u(ctx, T + S + S)}; повторный push не отправляется: перехода «ниже порога → порог и выше» не было",
            anchor=(r.block, r.span), evidence=[ctx.rule_ev(cap)] if cap else [])


def gen_cap(ctx: Ctx) -> None:
    cap = ctx.first("cap")
    if cap is None:
        return
    M, N = ctx.month, (ctx.month + 1) % 12
    T, S = ctx.T, ctx.S
    period = cap.data.get("period", "месяц")
    n = cap.data.get("n", "один")
    src = ctx.src(cap)
    if "месяц" in period:
        ctx.add("cap:next_period", kind="cap", level="business", title="Лимит push обнуляется в новом календарном месяце",
                precondition=f"Правило {src}: «{ctx.quote(cap)}». В {MONTHS_PREP[M]} push уже отправлен при пороге {_u(ctx, T)}",
                action=f"в {MONTHS_PREP[N]} расходы впервые за месяц достигают порога {_u(ctx, T)}",
                expected=f"push отправляется: лимит «{n} за {period}» считается отдельно для {MONTHS_GEN[N]}",
                anchor=(cap.block, cap.span))
        refund = ctx.first("refund")
        if refund is not None:
            ctx.add("cap:recross_same_period", kind="cap", level="business", title="Повторное достижение порога в том же месяце после возврата",
                    precondition=f"Правило {src}: «{ctx.quote(cap)}». В {MONTHS_PREP[M]} push отправлен при расходах {_u(ctx, T)}; затем возврат на {_u(ctx, S)} снизил расходы до {_u(ctx, T - S)}",
                    action=f"новая покупка на {_u(ctx, S)} снова доводит расходы до {_u(ctx, T)}",
                    expected=f"push не отправляется: не больше чем {n} за {period}", anchor=(cap.block, cap.span), evidence=[ctx.rule_ev(refund)])
    override = ctx.first("override")
    if override is not None:
        T2 = _second_threshold(ctx)
        ov_src = ctx.src(override)
        opts = [
            {"label": f"лимит {src}", "expected": f"push не отправляется: в {MONTHS_PREP[M]} push уже был ({src}: «{short(ctx.quote(cap), 70)}»)",
             "basis": src, "evidence": [ctx.rule_ev(cap)]},
            {"label": f"сброс {ov_src}", "expected": f"отправлен push о достижении нового порога {_u(ctx, T2)} ({ov_src}: «{short(ctx.quote(override), 70)}»)",
             "basis": ov_src, "evidence": [ctx.rule_ev(override)]},
        ]
        ctx.add("cap:override_conflict", kind="conflict", level="business", title=f"Смена порога после push в том же месяце: {src} или {ov_src}",
                precondition=f"В {MONTHS_PREP[M]} расходы достигли порога {_u(ctx, T)}, push отправлен",
                action=f"порог изменён на {_u(ctx, T2)}; затем покупка на {_u(ctx, T2 - T)} доводит расходы до {_u(ctx, T2)}",
                options=opts, question=("rules:cap_vs_override",
                                        f"Отправлять ли второй push в том же месяце после смены порога: по {src} — нет (не больше чем {n} за {period}), по {ov_src} — да (независимо от истории)?"),
                anchor=(override.block, override.span), values={"threshold": jnum(T), "new_threshold": jnum(T2)})


def gen_preserve(ctx: Ctx) -> None:
    items = ctx.rules.get("preserve", [])
    if not items:
        return
    r = items[0]
    T, S = ctx.T, ctx.S
    T2 = _second_threshold(ctx)
    R = T - S
    ctx.add("preserve:on_change", kind="preserve", level="business", title="Смена порога сохраняет накопленные расходы",
            precondition=f"Правило {ctx.src(r)}: «{ctx.quote(r)}». Расходы месяца {_u(ctx, R)}, порог {_u(ctx, T)}",
            action=f"изменить порог на {_u(ctx, T2)}", expected=f"накопленные расходы остаются {_u(ctx, R)}; порог {_u(ctx, T2)}",
            anchor=(r.block, r.span), evidence=[ctx.rule_ev(x) for x in items[1:]])
    override = ctx.first("override")
    if override is not None and ctx.first("cap") is None:
        ctx.add("preserve:override", kind="preserve", level="business", title="После смены порога достижение нового порога даёт push",
                precondition=f"Правило {ctx.src(override)}: «{ctx.quote(override)}». Расходы {_u(ctx, R)}, новый порог {_u(ctx, T2)}",
                action=f"провести покупку на {_u(ctx, T2 - R)}", expected="отправлен push о достижении нового порога",
                anchor=(override.block, override.span))


def gen_idempotency(ctx: Ctx) -> None:
    r = ctx.first("idempotency")
    if r is None:
        return
    T, S = ctx.T, ctx.S
    R = T - S
    key_ev = None
    for b, s, e, t in _units(ctx):
        if re.search(r"идентификатор\w*\s+операци", t):
            sp = re.search(r"идентификатор\w*\s+операци\w*", t)
            key_ev = ctx.doc.ev(b, s, e) if sp else None
            break
    key = "идентификатор операции" if key_ev else "ключ события"
    ctx.add("idempotency:redelivery", kind="idempotency", level="business", title="Повторная доставка того же события процессинга",
            precondition=(f"Правило {ctx.src(r)}: «{ctx.quote(r)}». Порог {_u(ctx, T)}; событие о покупке на {_u(ctx, S)} "
                          f"({key} OP-1) обработано: расходы выросли с {_u(ctx, R)} до {_u(ctx, T)}, отправлен один push"),
            action=f"то же событие ({key} OP-1) доставлено повторно",
            expected=f"расходы остаются {_u(ctx, T)}; повторный push не отправляется",
            anchor=(r.block, r.span), evidence=[key_ev] if key_ev else [],
            notes=[] if key_ev else ["ключ дедупликации события в документе не определён — уточнить"], needs_clarification=key_ev is None)


def gen_timing(ctx: Ctx) -> None:
    for r in ctx.rules.get("timing", []):
        n = int(r.data.get("n") or 1)
        unit = unit_canon(r.data.get("unit"))
        seconds = n * {"с": 1, "мин": 60, "ч": 3600, "дн.": 86400}.get(unit, 0)
        rest = r.data.get("rest", "").strip()
        trig = ctx.first("trigger")
        ctx.add(f"timing:{n}{unit}:{norm(rest)}", kind="timing", level="business", title=f"Срок: не позднее {n} {unit} {rest}".strip(),
                precondition=f"Правило {ctx.src(r)}: «{ctx.quote(r)}»",
                action="подать событие в момент t0" + (", по которому расходы достигают порога" if trig else "") + " и зафиксировать время по журналу",
                expected=f"действие выполнено не позднее t0 + {n} {unit}" + (f" ({seconds} с)" if seconds else ""),
                anchor=(r.block, r.span), values={"limit_seconds": seconds} if seconds else {},
                notes=["точка отсчёта и перцентиль измерения в требовании не указаны"])


# ---------------------------------------------------------------- критерии приёмки


def _num_after(rx: str, text: str) -> Decimal | None:
    m = re.search(rx + r"\s*(?:на\s+)?(?P<n>" + NUM_CORE + ")", text)
    return dec(m.group("n")) if m else None


_AMOUNT_NA = re.compile(rf"(?<!\w)на\s+(?P<n>{NUM_CORE})(?!\s*(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр|:))")
_AMOUNT_UNIT = re.compile(rf"(?P<n>{NUM})\s*(?:₸|тенге|тг\b|kzt\b|тиын)")


def _amount(text: str) -> Decimal | None:
    """Сумма операции в ячейке критерия: «на 1 500 ₸» или «500 ₸»; число перед месяцем — дата."""
    m = _AMOUNT_NA.search(text) or _AMOUNT_UNIT.search(text)
    return dec(m.group("n")) if m else None


def _dates(cell_text: str) -> list[dict]:
    out = []
    t = norm(cell_text)
    for m in _DATE.finditer(t):
        month = MONTHS_GEN.index(m.group("m").lower())
        out.append({"day": int(m.group("d")), "month": month, "time": f"{m.group('hh')}:{m.group('mm')}" if m.group("hh") else None,
                    "text": m.group(0), "tz": bool(_TZ_RE.search(t))})
    return out


def parse_acceptance(ctx: Ctx) -> None:
    for ti, t in enumerate(ctx.scan.acceptance, 1):
        hdr = [c.ntext for c in t.header]
        pi = next((i for i, h in enumerate(hdr) if re.search(r"исходн|предуслов|дано|given", h)), 0)
        ai = next((i for i, h in enumerate(hdr) if re.search(r"действи|шаг|when|когда", h)), 1)
        ei = next((i for i, h in enumerate(hdr) if re.search(r"ожидаем|результат|then|тогда", h)), 2)
        for i, r in enumerate(t.body, 1):
            if max(pi, ai, ei) >= len(r):
                continue
            pre, act, exp = r[pi], r[ai], r[ei]
            np_, na, ne = pre.ntext, act.ntext, exp.ntext
            row = {"table": ti, "index": i, "pre": pre.text.strip(), "act": act.text.strip(), "exp": exp.text.strip(), "cells": (pre, act, exp),
                   "R": _num_after(r"расход\w*", np_), "T": _num_after(r"порог\w*", np_ + " " + na),
                   "S": _amount(na) if _amount(na) is not None else _amount(np_),
                   "total": _num_after(r"(?:итог\w*|показыва\w*|расход\w*\s+состав\w*)", ne),
                   "delta": _num_after(r"(?:вырос\w*|увелич\w*|уменьш\w*)\s+на", ne)}
            push = re.search(r"push|пуш|уведомлен", ne)
            row["push"] = None if not push else not re.search(r"(?:\bне\b|\bбез\b|\bнет\b)[^.;]{0,20}(?:push|пуш|уведомлен)", ne)
            dates = []
            for cell, nt in ((pre, np_), (act, na)):
                for d in _dates(cell.text):
                    d["role"] = "posting" if re.search(r"провед|провест|списан|клиринг", nt) and not re.search(r"покупк\w*\s+\d", nt) else "transaction"
                    if re.search(r"покупк|соверш", nt) and cell is pre:
                        d["role"] = "transaction"
                    dates.append(d)
            row["dates"] = dates
            row["exp_month"] = next((k for k, adj in enumerate(MONTHS_ADJ) if adj in ne), None)
            if row["exp_month"] is None:
                row["exp_month"] = next((k for k, p in enumerate(MONTHS_PREP) if p in ne), None)
            tx = next((d for d in dates if d["role"] == "transaction"), None)
            post = next((d for d in dates if d["role"] == "posting"), None)
            row["cross_month"] = bool(tx and post and tx["month"] != post["month"])
            if row["R"] is not None and row["S"] is not None and row["T"] is not None:
                row["equal_threshold"] = row["R"] + row["S"] == row["T"]
            ctx.rows.append(row)


def gen_acceptance(ctx: Ctx) -> None:
    month = ctx.first("month")
    trig = ctx.first("trigger")
    excl = ctx.rules.get("exclude", [])
    for row in ctx.rows:
        pre, act, exp = row["cells"]
        i = row["index"]
        anchor_b = pre.block
        span = (pre.start, exp.end) if exp.block is pre.block else (pre.start, pre.end)
        evid = [ctx.doc.ev(c.block, c.start, c.end) for c in row["cells"]]
        key = f"acceptance:{row['table']}:{i}"
        title = f"Критерий приёмки {i}: {short(row['exp'], 60)}"
        notes: list[str] = []
        rng = getattr(ctx, "range_main", None)
        if row["T"] is not None and rng is not None and not rng.contains(row["T"]):
            notes.append(f"порог {_u(ctx, row['T'])} вне допустимого диапазона {rng.describe()} ({ctx.src(Rule('range', rng.block, rng.span))})")
        tx = next((d for d in row["dates"] if d["role"] == "transaction"), None)
        post = next((d for d in row["dates"] if d["role"] == "posting"), None)
        if month is not None and tx and post and row["cross_month"] and month.data.get("basis_kind") in ("transaction", "posting"):
            rule_m = tx["month"] if month.data["basis_kind"] == "transaction" else post["month"]
            if any(d["tz"] for d in row["dates"]) and not all(d["tz"] for d in row["dates"]):
                bare = next(d for d in row["dates"] if not d["tz"])
                notes.append(f"у времени «{bare['text']}» не указан часовой пояс")
            amount = row["S"]
            amt = f"{_u(ctx, amount)} " if amount is not None else ""
            rule_exp = f"{amt}учтены в расходах {MONTHS_GEN[rule_m]} (месяц по дате {month.data['basis_word']}); счётчик {MONTHS_GEN[post['month'] if rule_m == tx['month'] else tx['month']]} не изменился"
            if row["exp_month"] is not None and row["exp_month"] != rule_m:
                src = ctx.src(month)
                opts = [
                    {"label": f"в {MONTHS_PREP[rule_m]} ({src})", "expected": rule_exp, "basis": f"{src}: «{ctx.quote(month, 90)}»", "evidence": [ctx.rule_ev(month)]},
                    {"label": f"в {MONTHS_PREP[row['exp_month']]} (критерий приёмки {i})", "expected": row["exp"], "basis": f"критерий приёмки {i}",
                     "evidence": [ctx.doc.ev(exp.block, exp.start, exp.end)]},
                ]
                ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], options=opts,
                        question=(f"month:{key}", f"Покупка {tx['text']}, проведённая {post['text']}: учитывать её в {MONTHS_PREP[rule_m]} ({src}, месяц по дате {month.data['basis_word']}) или в {MONTHS_PREP[row['exp_month']]} (критерий приёмки {i})?"),
                        anchor=(anchor_b, span), evidence=evid, notes=notes, source="acceptance_table")
                continue
            ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], expected=row["exp"],
                    anchor=(anchor_b, span), evidence=evid + [ctx.rule_ev(month)], notes=notes + [f"согласуется с {ctx.src(month)}"], source="acceptance_table")
            continue
        ex_rule = None
        for r in excl:
            for item in _items(r.data.get("items") or r.data.get("items2") or ""):
                stem = norm(item).split()[0] if norm(item) else ""
                if stem and any(_stem_match(stem, w) for w in re.findall(r"[\wё]+", norm(row["act"]))):
                    ex_rule = r
        if ex_rule is not None and row["R"] is not None:
            extra = []
            if row["T"] is not None and row["R"] < row["T"] and row["push"] is None:
                extra = ["дополнительно проверить: push не отправлен"]
            if row["total"] is not None and row["total"] != row["R"]:
                opts = [
                    {"label": f"по {ctx.src(ex_rule)}", "expected": f"расходы остаются {_u(ctx, row['R'])}", "basis": f"{ctx.src(ex_rule)}: «{ctx.quote(ex_rule, 80)}»", "evidence": [ctx.rule_ev(ex_rule)]},
                    {"label": f"по критерию {i}", "expected": row["exp"], "basis": f"критерий приёмки {i}", "evidence": [evid[2]]},
                ]
                ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], options=opts,
                        question=(f"exclude:{key}", f"Критерий приёмки {i} расходится с {ctx.src(ex_rule)}: какой итог верен?"),
                        anchor=(anchor_b, span), evidence=evid, notes=notes, source="acceptance_table")
            else:
                ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], expected=row["exp"],
                        anchor=(anchor_b, span), evidence=evid + [ctx.rule_ev(ex_rule)], notes=notes + [f"согласуется с {ctx.src(ex_rule)}"] + extra,
                        source="acceptance_table")
            continue
        if trig is not None and None not in (row["R"], row["T"], row["S"]):
            total = row["R"] + row["S"]
            t = trig.data["norm"]
            inclusive = bool(re.search(r"равн\w*\s+порогу|не\s+ниже|не\s+менее|достиг", t)) or not re.search(r"превыш", t)
            push = row["R"] < row["T"] and (total >= row["T"] if inclusive else total > row["T"])
            ok_total = row["total"] is None or row["total"] == total
            ok_push = row["push"] is None or row["push"] == push
            if ok_total and ok_push:
                ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], expected=row["exp"],
                        anchor=(anchor_b, span), evidence=evid + [ctx.rule_ev(trig)], notes=notes + [f"согласуется с {ctx.src(trig)}"], source="acceptance_table")
            else:
                rule_exp = f"итог {_u(ctx, total)}; " + ("отправлен один push" if push else "push не отправляется")
                opts = [
                    {"label": f"по {ctx.src(trig)}", "expected": rule_exp, "basis": f"{ctx.src(trig)}: «{ctx.quote(trig, 80)}»", "evidence": [ctx.rule_ev(trig)]},
                    {"label": f"по критерию {i}", "expected": row["exp"], "basis": f"критерий приёмки {i}", "evidence": [evid[2]]},
                ]
                ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], options=opts,
                        question=(f"trigger:{key}", f"Критерий приёмки {i} расходится с {ctx.src(trig)}: какой результат верен?"),
                        anchor=(anchor_b, span), evidence=evid, notes=notes, source="acceptance_table")
            continue
        ctx.add(key, kind="acceptance", level="business", title=title, precondition=row["pre"], action=row["act"], expected=row["exp"],
                anchor=(anchor_b, span), evidence=evid, notes=notes + ["автоматическая сверка с правилами не выполнена"], source="acceptance_table")


# ---------------------------------------------------------------- замечания, вопросы, покрытие


def _spans(evs: Iterable[dict]) -> set[tuple[str, int, int]]:
    return {(e["block_id"], e["start"], e["end"]) for e in evs if e}


def _overlap(a: set[tuple[str, int, int]], b: set[tuple[str, int, int]]) -> bool:
    return any(x[0] == y[0] and x[1] < y[2] and y[1] < x[2] for x in a for y in b)


def _tc_spans(tc: dict) -> set[tuple[str, int, int]]:
    spans = _spans(tc["evidence"])
    for o in tc["options"]:
        spans |= _spans(o.get("evidence", []))
    return spans


def link_findings(ctx: Ctx, findings: list[Any], questions: list[Any]) -> None:
    by_finding_q: dict[str, str] = {}
    for q in questions:
        for fid in as_list(g(q, "finding_ids")) + as_list(g(q, "finding_id")):
            by_finding_q.setdefault(str(fid), str(g(q, "id")))
    for i, f in enumerate(findings):
        fid = str(g(f, "id") or f"F-{i + 1}")
        if norm(g(f, "status") or "confirmed") not in {"confirmed", "needs_review"}:
            continue
        fsp = _spans(ctx.doc.evidence_of(f))
        w = g(f, "witness")
        if w:
            ea = _spans(_ev_list(ctx, g(w, "evidence_a")))
            eb = _spans(_ev_list(ctx, g(w, "evidence_b")))
            targets = [tc for tc in ctx.tcs if tc["status"] == "open" and ea and eb and _overlap(_tc_spans(tc), ea) and _overlap(_tc_spans(tc), eb)]
            qid = by_finding_q.get(fid) or (str(g(f, "question_id")) if g(f, "question_id") else None)
            if targets:
                for tc in targets:
                    if fid not in tc["finding_ids"]:
                        tc["finding_ids"].append(fid)
                    q = ctx.questions.get(tc["_qkey"])
                    if q is not None:
                        if fid not in q["finding_ids"]:
                            q["finding_ids"].append(fid)
                        if qid:
                            q.update(id=qid, existing=True)
            else:
                _witness_case(ctx, f, fid, w, qid)
            continue
        if not fsp:
            continue
        for tc in ctx.tcs:
            if _overlap(_tc_spans(tc), fsp) and fid not in tc["finding_ids"]:
                tc["finding_ids"].append(fid)


def _ev_list(ctx: Ctx, value: Any) -> list[dict]:
    out = []
    for e in as_list(value):
        if ctx.doc.ev_valid(e):
            out.append({"block_id": str(g(e, "block_id")), "start": g(e, "start"), "end": g(e, "end"), "quote": g(e, "quote")})
        else:
            fixed = ctx.doc.from_hint(e)
            if fixed:
                out.append(fixed)
    return out


def _witness_case(ctx: Ctx, f: Any, fid: str, w: Any, qid: str | None) -> None:
    ea, eb = _ev_list(ctx, g(w, "evidence_a")), _ev_list(ctx, g(w, "evidence_b"))
    if not ea:
        return
    inp = g(w, "input")
    if isinstance(inp, Mapping):
        pre = str(inp.get("precondition") or inp.get("given") or inp.get("state") or json.dumps(inp, ensure_ascii=False))
        act = str(inp.get("action") or inp.get("when") or "выполнить сценарий из условия")
    else:
        pre, act = str(inp or g(f, "title") or ""), "выполнить сценарий из условия конфликта"
    b = ctx.doc.by_id[ea[0]["block_id"]]
    opts = [
        {"label": "исход A", "expected": str(g(w, "outcome_a") or ""), "basis": short(ea[0]["quote"], 80), "evidence": ea},
        {"label": "исход B", "expected": str(g(w, "outcome_b") or ""), "basis": short(eb[0]["quote"], 80) if eb else "", "evidence": eb},
    ]
    tc = ctx.add(f"witness:{fid}", kind="conflict", level="business", title=f"Конфликт {fid}: {short(str(g(f, 'title') or ''), 70)}",
                 precondition=pre, action=act, options=opts,
                 question=(f"witness:{fid}", f"Конфликт {fid}: какой исход верен — «{short(opts[0]['expected'], 60)}» или «{short(opts[1]['expected'], 60)}»?"),
                 anchor=(b, (ea[0]["start"], ea[0]["end"])), source="witness")
    tc["finding_ids"].append(fid)
    q = ctx.questions[tc["_qkey"]]
    q["finding_ids"].append(fid)
    if qid:
        q.update(id=qid, existing=True)


_STOP = {"требов", "значен", "сценар", "провер", "случае", "котор", "через", "после", "чтобы", "также"}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яёa-z]{4,}", norm(text)) if w[:5] not in _STOP and w[:6] not in _STOP}


def _nums(text: str) -> set[Decimal]:
    out = set()
    for m in _NUM_RE.finditer(norm(text)):
        try:
            out.add(dec(m.group(0)))
        except InvalidOperation:
            pass
    return out


def apply_coverage(ctx: Ctx, coverage: list[Any]) -> None:
    for c in coverage:
        rid = str(g(c, "req_id") or g(c, "requirement_id") or "")
        gaps = g(c, "not_covered") or g(c, "uncovered") or g(c, "gaps") or g(c, "missing") or []
        if not gaps and norm(g(c, "status")) in {"uncovered", "partial"} and g(c, "obligation"):
            # Coverage контракта v1: непокрытое обязательство — obligation со статусом uncovered|partial.
            gaps = [str(g(c, "obligation"))]
        if isinstance(gaps, str):
            gaps = [x.strip() for x in re.split(r"[;\n]", gaps) if x.strip()]
        for gap in as_list(gaps):
            text = str(gap if isinstance(gap, str) else (g(gap, "text") or g(gap, "description") or ""))
            if not text:
                continue
            gs, gn = _stems(text), _nums(text)
            hits = []
            for tc in ctx.tcs:
                if rid and rid not in tc["req_ids"]:
                    continue
                body = " ".join([tc["title"], tc["action"], tc["precondition"]])
                vals = {Decimal(str(v)) for v in (tc["values"].get("input"),) if isinstance(v, (int, float))}
                if gn:  # пробел с числами сопоставляется только по числам
                    if gn & (vals | _nums(tc["title"])):
                        hits.append(tc)
                elif gs and len(gs & _stems(body)) >= 0.75 * len(gs):
                    hits.append(tc)
            gap_rec = {"req_id": rid or None, "gap": text, "status": g(c, "status"), "explanation": g(c, "explanation")}
            if hits:
                for tc in hits:
                    tc["covers_gaps"].append(gap_rec)
                continue
            req = ctx.reqs.by_id.get(rid)
            anchor = None
            if req and req.spans:
                bid, s, e = req.spans[0]
                if bid in ctx.doc.by_id:
                    anchor = (ctx.doc.by_id[bid], (s, e))
            if anchor is None:
                ctx.warnings.append(W("bank.coverage_unanchored", f"Пробел покрытия «{short(text, 60)}» без опоры на требование {rid or '—'}: черновик не создан.", "info"))
                continue
            src = req.source_id or req.id
            tc = ctx.add(f"gap:{rid}:{norm(text)}", kind="coverage_gap", level="business", title=f"Не покрыто ({src}): {short(text, 70)}",
                         precondition=f"Требование {src}: «{short(req.text, 140)}»", action=text,
                         expected=f"ожидаемый результат вывести из {src}; если правило допускает несколько исходов — вопрос владельцу",
                         anchor=anchor, notes=["черновик по колонке покрытия «что не покрыто»"], source="coverage", needs_clarification=True)
            tc["covers_gaps"].append(gap_rec)


# ---------------------------------------------------------------- LLM: дополнительные сценарии

_HINTS = {"type": "array", "items": _S({"block_id": {"type": "string"}, "quote": {"type": "string"}})}
_SCEN_SCHEMA = _S({
    "scenarios": {"type": "array", "items": _S({
        "req_id": {"type": "string"}, "title": {"type": "string"}, "precondition": {"type": "string"},
        "action": {"type": "string"}, "expected": {"type": "string"}, "hints": _HINTS,
        "alternatives": {"type": "array", "items": _S({"expected": {"type": "string"}, "hints": _HINTS})},
    })},
})
STAGE_SCENARIOS = "bank#scenarios"
_SCEN_TASK = (
    "Составь черновые приёмочные сценарии на русском (предусловие, действие, ожидаемый результат) для требований без "
    "сценариев. Один сценарий — одно атомарное обязательство требования. Числа бери только из текста документа или "
    "соседние к границам. Каждый сценарий подкрепи дословными цитатами (hints: block_id, quote). Если правила документа "
    "дают два разных исхода, укажи второй в alternatives со своей цитатой. Не повторяй уже существующие сценарии (existing)."
)


def llm_scenarios(ctx: Ctx, ask: AskFn) -> None:
    covered = {rid for tc in ctx.tcs for rid in tc["req_ids"]}
    todo = [r for r in ctx.reqs.items if r.id not in covered and r.text.strip()]
    if not todo:
        return
    payload = {
        "task": _SCEN_TASK,
        "input": {
            "requirements": [{"id": r.id, "source_id": r.source_id or "", "text": r.text, "block_ids": sorted({b for b, _, _ in r.spans})} for r in todo],
            "existing": [{"key": tc["key"], "title": tc["title"], "req_ids": tc["req_ids"]} for tc in ctx.tcs],
        },
        "context": {"mode": "auto", "block_ids": sorted({b for r in todo for b, _, _ in r.spans})},
    }
    try:
        answer = ask(STAGE_SCENARIOS, payload, _SCEN_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        ctx.warnings.append(W("bank.llm_failed", f"Дополнительные сценарии моделью не получены: {exc}"))
        return
    doc_nums = set()
    for b in ctx.doc.blocks:
        doc_nums |= _nums(b.text)
    allowed = doc_nums | {n + d for n in doc_nums for d in (Decimal(1), Decimal(-1), Decimal("0.01"), Decimal("-0.01"))}
    todo_ids = {r.id for r in todo}
    for n, s in enumerate(as_list(g(answer, "scenarios"))):
        rid = str(g(s, "req_id") or "")
        req = ctx.reqs.by_id.get(rid)
        evs = [e for e in (ctx.doc.from_hint(h) for h in as_list(g(s, "hints"))) if e]
        texts = [str(g(s, k) or "") for k in ("title", "precondition", "action", "expected")]
        reason = None
        if rid not in todo_ids or req is None:
            reason = "неизвестное требование"
        elif not evs:
            reason = "нет проверяемой цитаты"
        elif any(not all(x in allowed for x in _nums(t)) for t in texts):
            reason = "числа не выводятся из текста документа"
        if reason:
            ctx.warnings.append(W("bank.llm_rejected", f"Сценарий модели «{short(texts[0], 60)}» отклонён: {reason}.", req_id=rid or None))
            continue
        alts = []
        for a in as_list(g(s, "alternatives")):
            aev = [e for e in (ctx.doc.from_hint(h) for h in as_list(g(a, "hints"))) if e]
            if aev and str(g(a, "expected") or "").strip():
                alts.append({"label": "альтернатива", "expected": str(g(a, "expected")), "basis": short(aev[0]["quote"], 80), "evidence": aev})
        b = ctx.doc.by_id[evs[0]["block_id"]]
        bid, rs, re_ = req.spans[0] if req.spans else (b.id, evs[0]["start"], evs[0]["end"])
        anchor = (ctx.doc.by_id.get(bid, b), (rs, re_))
        opts = [{"label": "основной исход", "expected": texts[3], "basis": short(evs[0]["quote"], 80), "evidence": evs}] + alts if alts else None
        ctx.add(f"llm:{rid}:{norm(texts[0])}", kind="llm", level="business", title=texts[0], precondition=texts[1], action=texts[2],
                expected=None if opts else texts[3], options=opts,
                question=(f"llm:{rid}:{n}", f"Какой исход верен для «{short(texts[0], 70)}»?") if opts else None,
                anchor=anchor, evidence=evs, source="llm", notes=["черновик модели: цитаты и числа проверены кодом"])


# ---------------------------------------------------------------- решения и итог


_LETTER = {"а": "a", "б": "b", "в": "b", "с": "c", "д": "d", "е": "e"}


def _choose(dec_: Any, options: list[dict]) -> dict | None:
    """Вариант по ответу владельца: «A», «вариант B», «Б)», «b — …» или подпись варианта («в январе»)."""
    s = norm(decision_value(dec_))

    def by_letter(ch: str) -> dict | None:
        letter = _LETTER.get(ch, ch)
        return next((o for o in options if norm(o["id"]) == letter), None)

    m = re.fullmatch(r"(?:вариант\s+)?([a-hа-е])[).]?", s)
    if m:
        return by_letter(m.group(1))
    for o in options:
        lab = norm(o.get("label"))
        if lab and (lab in s or (len(s) >= 4 and s in lab)):
            return o
    m = re.match(r"^(?:вариант\s+([a-hа-е])\b|([a-hа-е])\s*[).:-])", s)
    if m:
        return by_letter(m.group(1) or m.group(2))
    return None


def apply_decisions(ctx: Ctx, decisions: Iterable[Any]) -> None:
    decs = decisions_by_question(decisions)
    for tc in ctx.tcs:
        if tc["status"] != "open":
            continue
        qid = tc["open_question_id"]
        d = decs.get(qid) or decs.get(tc["key"])
        if d is None:
            continue
        before = tc["expected"]
        chosen = _choose(d, tc["options"])
        did = decision_id(d)
        text = decision_text(d)
        if chosen is not None:
            tc["expected"] = chosen["expected"]
            for o in tc["options"]:
                o["chosen"] = o is chosen
            why = f"вариант {chosen['id']} — {chosen['label']}"
        else:
            tc["expected"] = f"по решению владельца: {text}"
            why = "ответ вне предложенных вариантов"
        tc.update(status="agreed", decision_id=did, resolved_question_id=qid, open_question_id=None)
        ev = ctx.doc.evidence_of(d)
        tc["evidence"] = _dedupe_ev(tc["evidence"] + ev)
        tc["changes"].append({"field": "expected", "before": before, "after": tc["expected"],
                              "reason": f"решение владельца ({did}) по вопросу {qid}: {why} — «{short(text, 90)}»", "decision_id": did})
        tc["notes"].append(f"ожидаемый результат согласован решением владельца по вопросу {qid}")


def _gherkin(tc: dict) -> str:
    if tc["status"] == "open":
        then = f"Тогда (открыто до решения {tc['open_question_id']}): " + "; ".join(f"{o['id']}) {o['expected']}" for o in tc["options"])
    else:
        then = f"Тогда {tc['expected']}"
    return f"Дано {tc['precondition']}\nКогда {tc['action']}\n{then}"


def finalize(ctx: Ctx) -> list[dict]:
    ctx.tcs.sort(key=lambda tc: tc["_anchor"])
    for n, tc in enumerate(ctx.tcs, 1):
        tc["id"] = f"TC-{n:02d}"
    for tc in ctx.tcs:
        rids = [tc["obligation"]["req_id"]] if tc["obligation"]["req_id"] else []
        for b, s, e in sorted(_tc_spans(tc), key=lambda x: (ctx.doc.by_id[x[0]].order if x[0] in ctx.doc.by_id else 1 << 30, x[1], x[2])):
            for r in ctx.reqs.at(b, s, e):
                rids.append(r.id)
        tc["req_ids"] = list(dict.fromkeys(rids))
        tc["source_ids"] = list(dict.fromkeys(ctx.reqs.label(r) for r in tc["req_ids"]))
    return ctx.tcs


def _publish(ctx: Ctx) -> list[dict]:
    for tc in ctx.tcs:
        q = ctx.questions.get(tc["_qkey"]) if tc["_qkey"] else None
        if q is not None:
            if tc["status"] == "open":
                tc["open_question_id"] = q["id"]
            q["affected_req_ids"] = list(dict.fromkeys(q["affected_req_ids"] + tc["req_ids"]))
            tc["open_question"] = {k: q[k] for k in ("id", "kind", "prompt", "options", "affected_req_ids", "finding_ids", "existing", "key")}
        if tc["status"] == "open":
            tc["expected"] = f"ОТКРЫТО до решения {tc['open_question_id']}: " + "; ".join(f"{o['id']}) {o['expected']}" for o in tc["options"])
        tc["gherkin"] = _gherkin(tc)
        tc.pop("_anchor", None)
        tc.pop("_qkey", None)
    return ctx.tcs


def build_test_cases(doc: Doc, scan: Scan, requirements: list[Any], findings: Iterable[Any], decisions: Iterable[Any],
                     ask: AskFn | None, *, coverage: list[Any], questions: list[Any], warnings: list[dict]) -> list[dict]:
    ctx = Ctx(doc, scan, ReqIndex(doc, requirements), warnings)
    findings = as_list(findings)
    extract_rules(ctx)
    extract_ranges(ctx)
    extract_api(ctx)
    parse_acceptance(ctx)
    _examples(ctx)
    for gen in (gen_ranges, gen_default, gen_month, gen_events, gen_refund, gen_trigger, gen_cap, gen_preserve, gen_idempotency,
                gen_timing, gen_api, gen_acceptance):
        gen(ctx)
    finalize(ctx)
    link_findings(ctx, findings, questions)
    apply_coverage(ctx, coverage)
    if ask is not None:
        llm_scenarios(ctx, ask)
    finalize(ctx)
    # До решения вопросы получают окончательные id (с учётом совпавших вопросов №08).
    for tc in ctx.tcs:
        q = ctx.questions.get(tc["_qkey"]) if tc["_qkey"] else None
        if q is not None and tc["status"] == "open":
            tc["open_question_id"] = q["id"]
    for tc in ctx.tcs:
        if tc["status"] == "open":
            tc["expected"] = None
    apply_decisions(ctx, decisions)
    for tc in ctx.tcs:
        for ch in tc["changes"]:
            if ch["field"] == "expected" and ch["before"] is None and tc["options"]:
                ch["before"] = "открыт: " + "; ".join(f"{o['id']}) {short(o['expected'], 60)}" for o in tc["options"])
    if not ctx.tcs:
        warnings.append(W("bank.no_test_cases", "Из текущего документа не выведено ни одного приёмочного сценария.", "info"))
    return _publish(ctx)
