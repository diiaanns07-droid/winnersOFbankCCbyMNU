"""Нормализованная таблица фактов и детерминированные сравнения (направление №06).

Факт — одно утверждение текущего документа о поле или величине, сведённое к слотам:
``subject, field, scope, direction, type, value | range, unit, condition, evidence``.

Модуль работает без LLM. Он разбирает таблицы и шаблонные фразы входа, обогащает их
подсказками №04 (``fact_hints``), проверяет цитаты (локально или резолвером №07) и
сравнивает факты по границам, размерностям, типам и условиям HTTP-исходов. Одни и те же
функции вызываются в онлайн- и офлайн-режимах, поэтому вычислимые выводы не зависят
от модели.

Денежные величины точные: ``Decimal`` внутри, целые тиыны (``*_minor``) в JSON.
Совместимые случаи (1 ₸ и 100 тиын, строковое представление числа в ответе, разные
условия ошибок) попадают в ``comparisons`` с вердиктом ``compatible`` и не порождают
кандидатов.

Документ и блоки принимаются как dict или как объект с атрибутами (контракт v1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

__all__ = [
    "reconcile_facts",
    "extract_facts",
    "DocView",
    "Resolver",
    "Audit",
    "Fact",
    "Stamp",
    "find_stamps",
    "month_mentions",
    "tz_offset",
    "keys_of",
    "key_set",
    "norm",
    "strip_md",
    "parse_money",
    "find_money",
    "to_minor",
    "fmt_money",
    "make_candidate",
    "criteria_for",
]

Evidence = dict  # {block_id, start, end, quote}

# =============================================================== 1. доступ к данным


def get(obj: Any, key: str, default: Any = None) -> Any:
    """Читает поле у dict или атрибут у объекта (dataclass, pydantic)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for name in ("model_dump", "dict", "_asdict"):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return out
            except TypeError:
                pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


# =============================================================== 2. текст и основы слов

_TRANS = str.maketrans(
    {
        "ё": "е", "Ё": "Е", "«": '"', "»": '"', "“": '"', "”": '"', "„": '"',
        "’": "'", "‘": "'", "–": "-", "—": "-", "−": "-",
        " ": " ", " ": " ", " ": " ", " ": " ",
    }
)
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]+")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

STOPWORDS = frozenset(
    """
    и а но или либо не ни же ли бы что чтобы как так то это этот эта эти этого этой
    в во на по с со к ко о об обо у за из от до для при без над под через после перед между
    его ее её их он она оно они мы вы я ты свой своя свое свои который которая которое которые
    также уже еще ещё только весь вся все всех всё каждый каждая любой любая такой такая такие
    должен должна должно должны может могут быть является являются следует необходимо нужно
    если когда где там тут здесь есть нет да
    the a an of to and or in for is are be with on by at as from this that
    """.split()
)

_ENDINGS = sorted(
    """
    иями ями ами ией иям ием ого его ому ему ыми ими ыми ость ости ется ится ются ятся ает яет
    ует ают яют уют ешь ишь ете ите ть ти ых их ую юю ая яя ое ее ые ие ой ей ий ый ом ем ам
    ям ах ях ов ев ия ья ье ью ию ит ет ют ут ят ат а я о е ы и у ю ь й
    """.split(),
    key=len,
    reverse=True,
)


def norm(text: Any) -> str:
    """Нижний регистр, ё→е, кавычки и тире к ASCII, пробелы схлопнуты."""
    return _WS.sub(" ", str(text or "").translate(_TRANS)).strip().lower()


def strip_md(text: Any) -> str:
    """Снимает маркеры Markdown (**, `, __) и крайние пробелы."""
    s = str(text or "")
    s = s.replace("**", "").replace("__", "").replace("`", "")
    return s.strip()


def _stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if not re.search("[а-я]", w):
        return w
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            w = w[: -len(e)]
            break
    return w[:5]


def keys_of(text: Any) -> list[str]:
    """Ключи-основы содержательных слов (без стоп-слов и чисел), в порядке появления."""
    out: list[str] = []
    for raw in _WORD.findall(str(text or "")):
        parts = [raw]
        if re.fullmatch(r"[A-Za-z_]+", raw):
            parts = [p for p in re.split(r"_+", raw) if p]
            parts = [q for p in parts for q in (_CAMEL.findall(p) or [p])]
        for p in parts:
            pl = p.lower().replace("ё", "е")
            if pl.isdigit() or len(pl) < 3 or pl in STOPWORDS:
                continue
            out.append(_stem(pl))
    return out


def key_set(text: Any) -> set[str]:
    return set(keys_of(text))


_VERB_END = re.compile(r"(ть|ти|ет|ёт|ит|ют|ут|ят|ат|ется|ится|ются|ятся|ал|ил|ел|ла|ло)$")
_ADJ_END = re.compile(r"(ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ым|им|ую|юю|ых|их)$")
_PREP = frozenset("в во на по с со к о об у за из от до для при без над под через".split())


def _is_verb(w: str) -> bool:
    w = w.lower().replace("ё", "е")
    return bool(re.search("[а-я]", w)) and bool(_VERB_END.search(w)) and len(w) > 3


def _is_adj(w: str) -> bool:
    w = w.lower().replace("ё", "е")
    return bool(re.search("[а-я]", w)) and bool(_ADJ_END.search(w)) and len(w) > 3


def _head_phrase(prefix: str, max_tokens: int = 2) -> tuple[Optional[str], Optional[str]]:
    """Последняя именная группа перед позицией: (фраза, прилагательное перед ней)."""
    clause = re.split(r"[.;|,()\n]|:(?=\s|$)|\s(?:и|или)\s", prefix)[-1]
    toks = [t for t in _WORD.findall(strip_md(clause))]
    while toks and (toks[-1].lower() in _PREP or toks[-1].isdigit() or re.fullmatch(_MONTH_WORDS, toks[-1].lower())):
        toks.pop()
    if not toks:
        return None, None
    head = [toks[-1]]
    adj = None
    if len(toks) >= 2:
        prev = toks[-2]
        if _is_adj(prev) and norm_type(prev) == "integer":
            adj = prev  # «целый порог»: прилагательное задаёт тип, а не имя поля
        elif _is_adj(prev) and max_tokens > 1:
            head = [prev, toks[-1]]  # «минимальная комиссия» ≠ «максимальная комиссия»
        elif not _is_verb(prev) and prev.lower() not in STOPWORDS and not prev.isdigit() and max_tokens > 1:
            head = [prev, toks[-1]]
            if len(toks) >= 3 and _is_adj(toks[-3]):
                adj = toks[-3]
    if _is_verb(head[-1]) and len(head) == 1:
        return head[0], adj
    return " ".join(head), adj


def _actor(sentence: str) -> Optional[str]:
    """Субъект действия: слова от начала предложения до первого глагола."""
    s = re.sub(r"^\W*(?:[A-Za-zА-Яа-яЁё]{1,4}-\d+(?:\.\d+)*)\.?\W*", "", strip_md(sentence))
    toks = _WORD.findall(s)
    out: list[str] = []
    for t in toks:
        if _is_verb(t):
            break
        out.append(t)
        if len(out) >= 6:
            return None
    return " ".join(out) or None


# =============================================================== 3. числа, деньги, единицы

NUM = r"\d{1,3}(?:[    ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
CUR = r"₸|тенге|тг\.?(?![а-я])|kzt\b|тиын\w*|тиин\w*"
_MONTH_WORDS = (
    r"январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|августа?|"
    r"сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь]"
)
_MONEY_RE = re.compile(rf"(?P<num>{NUM})\s*(?P<cur>{CUR})", re.I)
_RANGE_TEXT_RE = re.compile(
    rf"\bот\s+(?P<a>{NUM})\s*(?P<cura>{CUR})?\s+(?:до|по)\s+(?P<b>{NUM})\s*(?P<curb>{CUR})?"
    rf"(?P<incl>\s+включительно)?",
    re.I,
)
_RANGE_DASH_RE = re.compile(rf"(?P<a>{NUM})\s*(?P<cura>{CUR})?\s*[–—-]\s*(?P<b>{NUM})\s*(?P<curb>{CUR})?", re.I)
_UNIT_STMT_RE = re.compile(r"\s(?:в|во)\s+(?P<u>тиын\w*|тиин\w*|тенге|kzt)\b", re.I)
_MONEY_DEF_RE = re.compile(
    rf"(?P<conn>\s+(?:—|-|–|составляет|равн[аоы]|равен|в размере|хранится как|хранится в виде|=)\s+|\s*:\s*)"
    rf"(?P<num>{NUM})\s*(?P<cur>{CUR})",
    re.I,
)

MONEY_UNITS = {"KZT": 100, "tiyn": 1}  # тиынов в одной единице
UNIT_LABEL = {"KZT": "₸", "tiyn": "тиын"}


def parse_num(s: str) -> Optional[Decimal]:
    try:
        return Decimal(re.sub(r"[\s   ]", "", s).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def unit_of(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    t = norm(token)
    if t.startswith("тиын") or t.startswith("тиин"):
        return "tiyn"
    if t in ("₸", "тенге", "kzt", "тг", "тг.") or t.startswith("тенге"):
        return "KZT"
    return None


def to_minor(value: Optional[Decimal], unit: Optional[str]) -> Optional[int]:
    """Точный перевод в тиыны; None, если величина не денежная или дробный тиын."""
    if value is None or unit not in MONEY_UNITS:
        return None
    v = value * MONEY_UNITS[unit]
    if v != v.to_integral_value():
        return None
    return int(v)


def find_money(text: str) -> Optional[tuple[int, int, int, str]]:
    """Первая денежная сумма в тексте: (start, end, тиыны, единица)."""
    for m in _MONEY_RE.finditer(text or ""):
        v, u = parse_num(m.group("num")), unit_of(m.group("cur"))
        mi = to_minor(v, u)
        if mi is not None:
            return m.start(), m.end(), mi, u
    return None


def parse_money(text: str) -> Optional[tuple[Decimal, str, int]]:
    m = _MONEY_RE.search(text or "")
    if not m:
        return None
    v, u = parse_num(m.group("num")), unit_of(m.group("cur"))
    mi = to_minor(v, u)
    if v is None or u is None or mi is None:
        return None
    return v, u, mi


def fmt_num(v: Decimal) -> str:
    q = v.normalize() if v == v.to_integral_value() else v
    if q == q.to_integral_value():
        s = f"{int(q):,}".replace(",", " ")
    else:
        s = format(q, "f").replace(".", ",")
    return s


def fmt_money(minor: int, unit: Optional[str] = "KZT") -> str:
    """Человекочитаемая сумма по тиынам: 100000 → «1 000 ₸»."""
    if unit == "tiyn":
        return f"{fmt_num(Decimal(minor))} тиын"
    return f"{fmt_num(Decimal(minor) / 100)} ₸"


# =============================================================== 4. даты и пояса

_MONTH_NUM = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
MONTH_NAMES = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}
TZ_OFFSETS = {
    "алмат": 5, "астан": 5, "нур-султан": 5, "казахстан": 5, "asia/almaty": 5,
    "москв": 3, "мск": 3, "utc": 0, "gmt": 0,
}
_TZ_TAIL = r"(?:\s+(?:по|в)\s+(?:времени\s+|поясу\s+)?(?P<tz>[A-Za-zА-Яа-яЁё][\w\-/]*(?:\s*[+\-−]\s*\d{1,2})?))?"
_DATE_RE = re.compile(
    rf"(?<!\d)(?P<day>\d{{1,2}})\s+(?P<mon>{_MONTH_WORDS})(?![а-я])"
    rf"(?:\s+(?P<year>\d{{4}})(?:\s*(?:г\.|года?))?)?"
    rf"(?:\s*(?:в|,)?\s*(?P<h>\d{{1,2}})[:.](?P<mi>\d{{2}}))?" + _TZ_TAIL,
    re.I,
)
_NUMDATE_RE = re.compile(
    r"(?<![\d.])(?P<day>\d{1,2})\.(?P<mon>\d{1,2})(?:\.(?P<year>\d{4}))?"
    r"(?:\s*(?:в|,)?\s*(?P<h>\d{1,2}):(?P<mi>\d{2}))" + _TZ_TAIL,
    re.I,
)
_MONTH_MENTION_RE = re.compile(
    r"\b(январ|феврал|март|апрел|ма[йяе](?![а-я]{2})|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*", re.I
)


def tz_offset(name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    n = norm(name)
    m = re.match(r"(?:utc|gmt)\s*([+\-])\s*(\d{1,2})", n)
    if m:
        return int(m.group(2)) * (1 if m.group(1) == "+" else -1)
    for k, v in TZ_OFFSETS.items():
        if n.startswith(k):
            return v
    return None


def _month_of(word: str) -> Optional[int]:
    w = norm(word)
    for stem, num in _MONTH_NUM.items():
        if stem == "ма":
            if re.match(r"ма[йяе]", w):
                return 5
            continue
        if w.startswith(stem):
            return num
    return None


@dataclass
class Stamp:
    """Момент времени из текста: день, месяц, (год), (время), (пояс) и его позиция."""

    day: int
    month: int
    year: Optional[int]
    hour: Optional[int]
    minute: Optional[int]
    tz: Optional[str]
    offset: Optional[int]
    start: int
    end: int
    text: str

    def in_offset(self, target: Optional[int]) -> datetime:
        """Время в заданном поясе. Без явного пояса метка считается уже в целевом поясе."""
        year = self.year or (2028 if (self.month, self.day) == (2, 29) else 2026)
        dt = datetime(year, self.month, self.day, self.hour or 0, self.minute or 0)
        if self.offset is not None and target is not None and self.offset != target:
            dt += timedelta(hours=target - self.offset)
        return dt


def find_stamps(text: str) -> list[Stamp]:
    out: list[Stamp] = []
    for rx, numeric in ((_DATE_RE, False), (_NUMDATE_RE, True)):
        for m in rx.finditer(text or ""):
            try:
                day = int(m.group("day"))
                month = int(m.group("mon")) if numeric else _month_of(m.group("mon"))
            except (TypeError, ValueError):
                continue
            if not month or not (1 <= month <= 12) or not (1 <= day <= 31):
                continue
            tz = m.group("tz")
            off = tz_offset(tz)
            end = m.end()
            if tz and off is None:
                tz = None
                end = max(x for x in (m.end("mon"), m.end("year") if m.group("year") else -1,
                                       m.end("mi") if m.group("mi") else -1) if x is not None)
            h = int(m.group("h")) if m.group("h") else None
            mi = int(m.group("mi")) if m.group("mi") else None
            if h is not None and not (0 <= h <= 23):
                continue
            if any(s.start <= m.start() < s.end for s in out):
                continue
            out.append(
                Stamp(day, month, int(m.group("year")) if m.group("year") else None, h, mi, tz, off,
                      m.start(), end, text[m.start():end])
            )
    return sorted(out, key=lambda s: s.start)


def month_mentions(text: str) -> list[tuple[int, int, int]]:
    """Упоминания месяцев (существительные и прилагательные): (номер, start, end)."""
    out = []
    for m in _MONTH_MENTION_RE.finditer(text or ""):
        # «31 января» — часть даты, а не название периода
        before = text[max(0, m.start() - 4): m.start()]
        if re.search(r"\d\s*$", before):
            continue
        mon = _month_of(m.group(0))
        if mon:
            out.append((mon, m.start(), m.end()))
    return out


# =============================================================== 5. проверка опор


@dataclass
class Audit:
    """Учёт проверенных опор: подтверждённые, неоднозначные, перенесённые, отклонённые."""

    checked: int = 0
    confirmed: int = 0
    ambiguous: int = 0
    relocated: int = 0
    rejected: int = 0
    notes: list = dc_field(default_factory=list)
    via_07: bool = False

    def as_dict(self) -> dict:
        return {
            "checked": self.checked,
            "confirmed": self.confirmed,
            "ambiguous": self.ambiguous,
            "relocated": self.relocated,
            "rejected": self.rejected,
            "note": (
                "Подсказки {block_id, quote} модулей №04 и LLM-стадий №06. confirmed — точное "
                "совпадение block.text[start:end] == quote (включая нормализацию пробелов, ё и "
                "Markdown с пересчётом координат); ambiguous — цитата встречается в блоке "
                "несколько раз, выбрано первое вхождение или по контексту; relocated — цитата "
                "найдена ровно в одном другом блоке; rejected — не найдена, опора не используется. "
                "Детерминированные опоры, вычисленные из таблиц, сюда не входят. "
                + ("Цитаты проверены резолвером №07." if self.via_07 else "Цитаты проверены локальным резолвером №06.")
            ),
            "notes": list(self.notes[:50]),
        }


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        c = ch.translate(_TRANS).lower()
        if c in "*`":
            continue
        if c.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        for cc in c:
            out.append(cc)
            idx.append(i)
        prev_space = False
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def auto_resolver() -> Optional[Callable]:
    """resolve_hint №07 (bcc_review.analysis.evidence), иначе резерв движка; None — только локально."""
    for mod_name in ("bcc_review.analysis.evidence", "bcc_review.runtime.fallback.evidence"):
        try:
            import importlib

            fn = getattr(importlib.import_module(mod_name), "resolve_hint")
            fn.__p06_source__ = mod_name  # type: ignore[attr-defined]
            return fn
        except Exception:  # noqa: BLE001 — модуля может не быть в ветке
            continue
    return None


class Resolver:
    """Превращает подсказку {block_id, quote} в Evidence текущего документа.

    ``external`` — резолвер №07: ``resolve_hint(document, hint[, index=…, relocate=…])`` с ответом
    ``{status: matched|missing|ambiguous, evidence}`` либо функция, возвращающая Evidence | None.
    ``None`` — найти №07 автоматически; ``False`` — только локальный путь с тем же инвариантом
    ``block.text[start:end] == quote``.
    """

    def __init__(self, view: "DocView", external: Any = None, audit: Optional[Audit] = None):
        self.view = view
        self.external = auto_resolver() if external is None else (external or None)
        self.audit = audit or Audit()
        self.audit.via_07 = self.external is not None
        self._ext_kwargs: dict = {}
        self._ext_relocate = False
        if self.external is not None:
            import inspect

            try:
                params = inspect.signature(self.external).parameters
            except (TypeError, ValueError):
                params = {}
            self._ext_relocate = "relocate" in params
            if "index" in params:
                try:
                    import importlib

                    mod = importlib.import_module(self.external.__module__)
                    idx_cls = getattr(mod, "DocumentIndex", None)
                    if idx_cls is not None and hasattr(idx_cls, "of"):
                        self._ext_kwargs["index"] = idx_cls.of(view.document)
                except Exception:  # noqa: BLE001
                    pass

    def _external(self, hint: dict) -> tuple[Optional[Evidence], str]:
        """(Evidence | None, matched|relocated|ambiguous|missing)."""
        res = self.external(self.view.document, hint, **self._ext_kwargs)
        if isinstance(res, dict) and "status" in res:
            st = res.get("status")
            if st == "missing" and self._ext_relocate and hint.get("block_id"):
                res2 = self.external(self.view.document, hint, relocate=True, **self._ext_kwargs)
                if isinstance(res2, dict) and res2.get("status") == "matched":
                    return as_dict(res2.get("evidence")), "relocated"
            if st == "matched":
                ev = as_dict(res.get("evidence"))
                return ev, ("relocated" if hint.get("block_id") and ev.get("block_id") != hint.get("block_id") else "matched")
            return None, str(st or "missing")
        ev = as_dict(res) if res is not None else None
        return (ev, "matched") if ev else (None, "missing")

    def __call__(self, hint: Any, *, relocate: bool = True) -> Optional[Evidence]:
        a = self.audit
        a.checked += 1
        bid = str(get(hint, "block_id") or "")
        quote = str(get(hint, "quote") or "")
        if not quote.strip():
            a.rejected += 1
            a.notes.append(f"пустая цитата (block {bid or '—'})")
            return None
        if self.external is not None:
            h = {"block_id": bid or None, "quote": quote}
            if get(hint, "context"):
                h["context"] = get(hint, "context")
            try:
                ev, how = self._external(h)
            except Exception as exc:  # noqa: BLE001 — внешний модуль не должен ронять анализ
                a.notes.append(f"резолвер №07 упал: {exc!r}; использован локальный")
            else:
                if ev and self.check(ev):
                    if how == "relocated":
                        a.relocated += 1
                        a.notes.append(f"№07: цитата найдена в {ev['block_id']} (подсказка {bid or '—'})")
                    else:
                        a.confirmed += 1
                    return {k: ev[k] for k in ("block_id", "start", "end", "quote")}
                if how == "ambiguous":
                    a.ambiguous += 1
                    a.notes.append(f"№07: цитата неоднозначна ({quote[:60]!r}) — нужен контекст")
                else:
                    a.rejected += 1
                    a.notes.append(f"№07 не нашёл цитату: {quote[:60]!r}")
                return None
        ev = self._local(bid, quote, get(hint, "context"))
        if ev is not None:
            return ev
        if relocate:
            found = []
            for other in self.view.ids:
                if other == bid:
                    continue
                e2 = self._match(other, quote, None)
                if e2 is not None:
                    found.append(e2)
                    if len(found) > 1:
                        break
            if len(found) == 1:
                a.relocated += 1
                a.notes.append(f"цитата перенесена {bid or '—'} → {found[0]['block_id']}: {quote[:60]!r}")
                return found[0]
        a.rejected += 1
        a.notes.append(f"не найдено в документе: {quote[:80]!r} (block {bid or '—'})")
        return None

    def check(self, ev: Any) -> bool:
        bid = str(get(ev, "block_id") or "")
        if bid not in self.view.by_id:
            return False
        t = self.view.text(bid)
        try:
            s, e = int(get(ev, "start")), int(get(ev, "end"))
        except (TypeError, ValueError):
            return False
        return 0 <= s < e <= len(t) and t[s:e] == get(ev, "quote")

    def _local(self, bid: str, quote: str, context: Any) -> Optional[Evidence]:
        if bid not in self.view.by_id:
            return None
        text = self.view.text(bid)
        positions = [m.start() for m in re.finditer(re.escape(quote), text)]
        if positions:
            pos = positions[0]
            if len(positions) > 1:
                ctx = str(context or "")
                chosen = None
                if ctx:
                    for p in positions:
                        window = text[max(0, p - len(ctx) - 20): p + len(quote) + len(ctx) + 20]
                        if ctx in window:
                            chosen = p
                            break
                if chosen is None:
                    self.audit.ambiguous += 1
                    self.audit.notes.append(f"цитата встречается {len(positions)} раз(а) в {bid}: {quote[:60]!r}")
                else:
                    pos = chosen
                    self.audit.confirmed += 1
            else:
                self.audit.confirmed += 1
            return {"block_id": bid, "start": pos, "end": pos + len(quote), "quote": quote}
        ev = self._match(bid, quote, None, exact=False)
        if ev is not None:
            self.audit.confirmed += 1
        return ev

    def _match(self, bid: str, quote: str, _ctx: Any, exact: bool = True) -> Optional[Evidence]:
        text = self.view.text(bid)
        if exact:
            p = text.find(quote)
            if p >= 0:
                return {"block_id": bid, "start": p, "end": p + len(quote), "quote": quote}
        nt, idx = _norm_with_map(text)
        nq, _ = _norm_with_map(quote)
        nq = nq.strip()
        if not nq:
            return None
        p = nt.find(nq)
        if p < 0:
            return None
        s, e = idx[p], idx[p + len(nq) - 1] + 1
        return {"block_id": bid, "start": s, "end": e, "quote": text[s:e]}


def evidence_of(bid: str, text: str, start: int, end: int) -> Evidence:
    return {"block_id": bid, "start": start, "end": end, "quote": text[start:end]}


# =============================================================== 6. роли разделов

_ROLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (r, re.compile(p, re.I))
    for r, p in [
        ("template", r"ревью требований|блок согласующ|лист согласовани|согласующие"),
        ("acceptance", r"критери\w* при[её]м|acceptance|при[её]мочн"),
        ("testing", r"требования к тестировани|тестирование требований|тест-кейс"),
        ("api_request", r"параметры запроса|query|path-параметр|request|тело запроса|заголовки запроса"),
        ("api_response", r"^ответ|ответ метода|response|статус|коды ответ|\b[1-5]\d\d\b"),
        ("api_logic", r"логика работы|логика метода|особые правила|валидаци"),
        ("nfr", r"нефункциональн|производительност|надежност|доступност"),
        ("process", r"bpmn|sequence|архитектур|схема процесса|диаграмм"),
        ("business_rules", r"функциональн\w* требовани|бизнес[- ]правил|бизнес-требовани|^правила"),
        ("ui", r"\bui\b|\bux\b|интерфейс|экран|макет|дизайн"),
        ("integration", r"интеграц"),
        ("data", r"требования к данным|модель данных|^данные|структура данных"),
        ("goals", r"^цел[иь]"),
        ("general", r"общие сведения|общие параметры"),
    ]
]
_API_PART = re.compile(r"\bapi\b|\brest\b|swagger|endpoint|эндпоинт", re.I)
ROLE_GROUP = {"api_request": "api", "api_response": "api", "api_logic": "api"}


def block_role(section: list[str], kind: str = "") -> str:
    if "heading" in (kind or "") or (kind or "") in ("title", "h1", "h2", "h3", "h4"):
        return "heading"
    heads = [norm(strip_md(h)) for h in section]
    in_api = any(_API_PART.search(h) for h in heads)
    role = None
    for h in reversed(heads):
        for r, rx in _ROLE_PATTERNS:
            if rx.search(h):
                role = r
                break
        if role:
            break
    if in_api and role not in ("api_request", "api_response", "api_logic", "template", "acceptance", "testing"):
        role = "api"
    return role or "other"


def part_key(section: list[str]) -> tuple:
    for i, h in enumerate(section):
        if _API_PART.search(norm(h)):
            return tuple(section[: i + 1])
    return tuple(section[:2]) if len(section) >= 2 else tuple(section)


class DocView:
    """Только чтение: блоки по id, порядок, роли разделов, страницы."""

    def __init__(self, document: Any):
        self.document = document
        self.blocks = list(get(document, "blocks", None) or [])
        self.ids: list[str] = []
        self.by_id: dict[str, Any] = {}
        for b in self.blocks:
            bid = str(get(b, "id"))
            if bid in self.by_id:
                continue
            self.ids.append(bid)
            self.by_id[bid] = b
        self.pos = {bid: i for i, bid in enumerate(self.ids)}
        self.role = {bid: block_role(self.section(bid), self.kind(bid)) for bid in self.ids}
        self.part = {bid: part_key(self.own_section(bid)) for bid in self.ids}

    def own_section(self, bid: str) -> list[str]:
        """Раздел блока; заголовок относится к собственному разделу (читатели расходятся в этом)."""
        sec = self.section(bid)
        if self.role.get(bid) == "heading":
            t = strip_md(self.text(bid))
            if not sec or strip_md(sec[-1]) != t:
                sec = sec + [t]
        return sec

    def text(self, bid: str) -> str:
        return str(get(self.by_id.get(bid), "text", "") or "")

    def section(self, bid: str) -> list[str]:
        s = get(self.by_id.get(bid), "section", None) or []
        if isinstance(s, str):
            s = [s]
        return [str(x) for x in s]

    def kind(self, bid: str) -> str:
        return str(get(self.by_id.get(bid), "kind", "") or "").lower()

    def loc(self, bid: str) -> Any:
        return get(self.by_id.get(bid), "loc", None)

    def group(self, bid: str) -> str:
        r = self.role.get(bid, "other")
        return ROLE_GROUP.get(r, r)

    def scope(self, bid: str) -> str:
        return " / ".join(strip_md(s) for s in self.section(bid)[1:] or self.section(bid))

    def lines(self, bid: str) -> Optional[tuple[str, int, int]]:
        """('line'|'page'|'path', начало, конец) из loc, если удаётся прочитать."""
        return loc_span(self.loc(bid))

    def warnings(self) -> list:
        return list(get(self.document, "warnings", None) or [])


def loc_span(loc: Any) -> Optional[tuple[str, int, int]]:
    if loc is None:
        return None
    if isinstance(loc, (int, float)):
        return ("line", int(loc), int(loc))
    if isinstance(loc, str):
        m = re.search(r"(?:^|[^a-z])(l|line|стр|p|page)\D*(\d+)(?:\D+(\d+))?", loc.lower())
        if m:
            k = "page" if m.group(1) in ("p", "page", "стр") else "line"
            return (k, int(m.group(2)), int(m.group(3) or m.group(2)))
        return None
    d = as_dict(loc)
    for kind, a_keys, b_keys in (
        ("line", ("line_start", "start_line", "line", "lines"), ("line_end", "end_line", "line", "lines")),
        ("page", ("page_start", "page", "pages"), ("page_end", "page", "pages")),
    ):
        a = next((d[k] for k in a_keys if k in d and d[k] is not None), None)
        b = next((d[k] for k in b_keys if k in d and d[k] is not None), None)
        if isinstance(a, (list, tuple)) and a:
            a, b = a[0], a[-1]
        if isinstance(b, (list, tuple)) and b:
            b = b[-1]
        if a is not None:
            try:
                return (kind, int(a), int(b if b is not None else a))
            except (TypeError, ValueError):
                continue
    return None


# =============================================================== 7. таблицы

_SEP_LINE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


@dataclass
class Cell:
    text: str
    block_id: str
    start: int
    end: int

    @property
    def clean(self) -> str:
        return strip_md(self.text)

    def ev(self) -> Evidence:
        return {"block_id": self.block_id, "start": self.start, "end": self.end, "quote": self.text}


@dataclass
class Table:
    header: list[Cell]
    rows: list[list[Cell]]
    section: list[str]
    block_ids: list[str]

    @property
    def names(self) -> list[str]:
        return [norm(c.clean) for c in self.header]

    def col(self, kind: str) -> Optional[int]:
        rx = _COLS[kind]
        for i, n in enumerate(self.names):
            if rx.search(n):
                return i
        return None


_COLS = {
    "name": re.compile(r"^(parameter|параметр|поле|field|name|имя|атрибут)\b"),
    "type": re.compile(r"^(format|формат|тип|type)\b"),
    "size": re.compile(r"^(size|размер|длина|length)\b"),
    "mandatory": re.compile(r"^(mandatory|обязат|required)"),
    "logic": re.compile(r"^(logic|логика|значени[яе] допуст|допустим|диапазон|range|ограничени|constraint|values)"),
    "description": re.compile(r"^(description|описание)"),
    "db": re.compile(r"^(db\s*field|поле\s*бд|db\b|column|колонка|столбец)"),
    "value": re.compile(r"^(значение|value)$"),
    "pre": re.compile(r"^(исходн|предуслов|дано|given|услови)"),
    "action": re.compile(r"^(действи|когда|when|шаг)"),
    "expected": re.compile(r"^(ожидаем|результат|тогда|then|expected)"),
}


def _pipe_cells(line: str, base: int, bid: str) -> list[Cell]:
    if "|" not in line:
        return []
    pipes = [i for i, ch in enumerate(line) if ch == "|" and (i == 0 or line[i - 1] != "\\")]
    if not pipes:
        return []
    stripped = line.strip()
    starts = stripped.startswith("|")
    ends = stripped.endswith("|") and len(stripped) > 1
    segs: list[tuple[int, int]] = []
    prev = pipes[0] if starts else -1
    rest = pipes[1:] if starts else pipes
    for p in rest:
        segs.append((prev + 1, p))
        prev = p
    if not ends:
        segs.append((prev + 1, len(line)))
    cells = []
    for a, b in segs:
        seg = line[a:b]
        lpad = len(seg) - len(seg.lstrip())
        rlen = len(seg.rstrip())
        s, e = a + lpad, a + max(rlen, lpad)
        cells.append(Cell(line[s:e], bid, base + s, base + e))
    return cells


def iter_tables(view: DocView) -> list[Table]:
    """Таблицы из блоков: целая pipe-таблица, строки-блоки или ячейки DOCX с loc.row/col."""
    tables: list[Table] = []
    cur: Optional[Table] = None
    last_pos = -10
    cell_groups: dict[tuple, dict] = {}
    for bid in view.ids:
        kind = view.kind(bid)
        text = view.text(bid)
        loc = as_dict(view.loc(bid))
        if "cell" in kind and isinstance(loc.get("row"), int) and isinstance(loc.get("col", loc.get("column")), int):
            key = (loc.get("table", ""), tuple(view.section(bid)))
            g = cell_groups.setdefault(key, {"cells": {}, "section": view.section(bid), "ids": []})
            g["cells"][(loc["row"], loc.get("col", loc.get("column")))] = Cell(text.strip(), bid, 0, len(text.rstrip()))
            g["ids"].append(bid)
            cur = None
            continue
        lines = text.split("\n")
        content = [ln for ln in lines if ln.strip()]
        is_tab = bool(content) and all("|" in ln for ln in content) and (
            "table" in kind or "row" in kind or all(ln.strip().startswith("|") for ln in content)
        )
        if not is_tab:
            if kind not in ("separator",):
                cur = None
            continue
        rows: list[list[Cell]] = []
        header_from_sep: Optional[list[Cell]] = None
        off = 0
        for ln in lines:
            if ln.strip() and _SEP_LINE.match(ln):
                if rows:
                    header_from_sep = rows.pop()
                    if cur is not None and cur.block_ids and cur.block_ids[-1] == bid:
                        pass
                    cur = Table(header_from_sep, [], view.section(bid), [bid])
                    tables.append(cur)
                elif cur is not None and not cur.rows:
                    pass  # отдельный блок-разделитель после строки заголовка
            elif ln.strip():
                cells = _pipe_cells(ln, off, bid)
                if cells:
                    if header_from_sep is not None and cur is not None:
                        cur.rows.append(cells)
                    else:
                        rows.append(cells)
            off += len(ln) + 1
        if header_from_sep is not None:
            last_pos = view.pos[bid]
            continue
        for cells in rows:
            contiguous = cur is not None and view.pos[bid] - last_pos <= 1 and cur.section == view.section(bid)
            if "header" in kind or not contiguous:
                cur = Table(cells, [], view.section(bid), [bid])
                tables.append(cur)
            else:
                cur.rows.append(cells)
                if bid not in cur.block_ids:
                    cur.block_ids.append(bid)
        last_pos = view.pos[bid]
    for g in cell_groups.values():
        grid = g["cells"]
        nrows = max(r for r, _ in grid) + 1
        ncols = max(c for _, c in grid) + 1
        mat = [[grid.get((r, c), Cell("", "", 0, 0)) for c in range(ncols)] for r in range(nrows)]
        tables.append(Table(mat[0], mat[1:], g["section"], g["ids"]))
    return tables


def _row_ev(row: list[Cell]) -> Evidence:
    cells = [c for c in row if c.block_id]
    if not cells:
        return {}
    same = [c for c in cells if c.block_id == cells[0].block_id]
    a, b = same[0], same[-1]
    return {"block_id": a.block_id, "start": a.start, "end": b.end, "quote": None}


# =============================================================== 8. факты


@dataclass
class Fact:
    id: str = ""
    subject: Optional[str] = None
    field: Optional[str] = None
    scope: str = ""
    direction: Optional[str] = None
    type: Optional[str] = None
    value: Any = None
    value_minor: Optional[int] = None
    range: Optional[dict] = None
    unit: Optional[str] = None
    condition: Optional[str] = None
    evidence: Optional[Evidence] = None
    aliases: list = dc_field(default_factory=list)
    binding: Optional[str] = None
    size: Optional[dict] = None
    mandatory: Optional[bool] = None
    enum: Optional[list] = None
    representation: Optional[str] = None
    source: str = "table"
    role: str = "other"
    part: tuple = ()
    cells: dict = dc_field(default_factory=dict)
    notes: list = dc_field(default_factory=list)
    enriched_by: list = dc_field(default_factory=list)

    def alias_keys(self) -> set[tuple]:
        out = set()
        for a in [self.field, *self.aliases]:
            if a:
                k = tuple(keys_of(a))
                if k:
                    out.add(k)
        return out

    def ev_for(self, slot: str) -> Optional[Evidence]:
        return self.cells.get(slot) or self.evidence

    req_ids: list = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        """Форма Fact контракта v1: subject/field — строки, evidence — массив Evidence."""
        subject = self.subject or (self.scope.split(" / ")[-1] if self.scope else "") or "документ"
        d = {
            "id": self.id,
            "subject": subject,
            "field": self.field or "",
            "scope": self.scope,
            "direction": self.direction,
            "type": self.type,
            "value": self.value,
            "range": self.range,
            "unit": self.unit,
            "condition": self.condition,
            "evidence": [self.evidence] if self.evidence else [],
            "req_ids": list(self.req_ids),
            "binding": self.binding,
            "aliases": list(self.aliases),
            "source": self.source,
            "role": self.role,
        }
        if self.value_minor is not None:
            d["value_minor"] = self.value_minor
        for k in ("size", "mandatory", "enum", "representation"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.cells:
            d["cells"] = dict(self.cells)
        if self.notes:
            d["notes"] = list(self.notes)
        if self.enriched_by:
            d["enriched_by"] = list(self.enriched_by)
        return d


def norm_type(s: Any) -> Optional[str]:
    n = norm(strip_md(s))
    if not n or n in ("-", "—"):
        return None
    rules = [
        (r"^(integer|int\d*|long|bigint|short|целое|целый|целого|целым)", "integer"),
        (r"^(string|str\b|text|строк|varchar|char)", "string"),
        (r"^(bool|boolean|логическ)", "boolean"),
        (r"^(decimal|number|float|double|numeric|money|число|дробн)", "number"),
        (r"^(date|datetime|timestamp|дата)", "datetime"),
        (r"^(object|json|объект)", "object"),
        (r"^(array|list|массив|список)", "array"),
    ]
    for rx, t in rules:
        if re.match(rx, n):
            return t
    return n


def dec_str(d: Decimal) -> str:
    """Десятичная запись без экспоненты: Decimal('1E+3') → '1000'."""
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def make_range(a: Decimal, b: Decimal, unit: Optional[str], lo_incl: Optional[bool], hi_incl: Optional[bool]) -> dict:
    lo, hi = (a, b) if a <= b else (b, a)
    return {
        "min": dec_str(lo),
        "max": dec_str(hi),
        "min_inclusive": lo_incl,
        "max_inclusive": hi_incl,
        "min_minor": to_minor(lo, unit),
        "max_minor": to_minor(hi, unit),
    }


def parse_logic(text: str) -> dict:
    t = strip_md(text)
    out: dict = {}
    m = _RANGE_DASH_RE.search(t)
    if m and not re.match(rf"\s*(?:{_MONTH_WORDS})", t[m.end():], re.I):
        a, b = parse_num(m.group("a")), parse_num(m.group("b"))
        if a is not None and b is not None:
            out["range"] = (a, b, unit_of(m.group("cura") or m.group("curb")))
    m2 = _RANGE_TEXT_RE.search(t)
    if m2 and "range" not in out:
        a, b = parse_num(m2.group("a")), parse_num(m2.group("b"))
        if a is not None and b is not None:
            out["range"] = (a, b, unit_of(m2.group("cura") or m2.group("curb")))
            if m2.group("incl"):
                out["inclusive"] = True
    quoted = re.findall(r"[«\"']([^»\"']{1,24})[»\"']", t)
    if quoted:
        out["enum"] = quoted
        out["representation"] = "string"
    elif "range" not in out and re.fullmatch(r"\s*[\wА-Яа-я+\-]{1,12}(?:\s*(?:/|или|,)\s*[\wА-Яа-я+\-]{1,12})+\s*", t):
        out["enum"] = [x.strip() for x in re.split(r"\s*(?:/|или|,)\s*", t) if x.strip()]
    if re.match(r"^(при|если|когда|в случае|только при)\b", norm(t)):
        out["condition"] = t
    if re.search(r"включительно|обе границы включ", norm(t)):
        out["inclusive"] = True
    return out


def parse_size(text: str) -> Optional[dict]:
    t = norm(strip_md(text))
    if not t or t in ("-", "—"):
        return None
    m = re.search(r"(\d+)\s*(?:bit|бит)", t)
    if m:
        return {"bits": int(m.group(1))}
    m = re.search(r"(\d+)\s*-\s*(\d+)", t)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2)), "unit": "char"}
    m = re.search(r"(\d+)\s*(?:знак|символ|char)", t)
    if m:
        return {"max": int(m.group(1)), "unit": "char"}
    return {"raw": strip_md(text)}


def _desc_alias_unit(desc: str) -> tuple[Optional[str], Optional[str]]:
    d = strip_md(desc)
    u = None
    m = _UNIT_STMT_RE.search(" " + d)
    if m:
        u = unit_of(m.group("u"))
    head = re.split(r"\s(?:в|во|для|по)\s|[,(;.]", d)[0].strip()
    return (head or None), u


class _FactBuilder:
    def __init__(self, view: DocView):
        self.view = view
        self.facts: list[Fact] = []
        self.tables = iter_tables(view)
        self.table_blocks = {bid for t in self.tables for bid in t.block_ids}
        self.endpoints: list[dict] = []

    # ---------- конечные точки API
    def collect_endpoints(self) -> None:
        seen = set()
        for t in self.tables:
            if self.view.group(t.block_ids[0]) != "api" and not any(_API_PART.search(norm(h)) for h in t.section):
                continue
            if len(t.header) != 2 and t.col("value") is None:
                continue
            method = None
            paths: list[tuple[str, Cell]] = []
            desc = None
            for row in [t.header, *t.rows]:
                if len(row) < 2:
                    continue
                k, v = norm(row[0].clean), row[1]
                if re.search(r"rest type|http method|^method|^метод", k):
                    mm = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", v.clean, re.I)
                    if mm:
                        method = (mm.group(1).upper(), v)
                elif re.search(r"(?:^|\s)(?:request\s+)?url\b|endpoint|путь|адрес", k) and "type" not in k:
                    for pm in re.finditer(r"`(/[^`\s]+)`|(?<![\w`])(/[A-Za-z][\w{}\-./]*)", v.text):
                        p = pm.group(1) or pm.group(2)
                        s = v.start + (pm.start(1) if pm.group(1) else pm.start(2))
                        paths.append((p, Cell(p, v.block_id, s, s + len(p))))
                elif re.search(r"^description|^описание|^назначение", k):
                    desc = v
            for p, cell in paths:
                if p in seen:
                    continue
                seen.add(p)
                name = [s for s in p.split("/") if s][-1] if p.strip("/") else p
                op = op_of_name(name) or (op_of_method(method[0]) if method else None)
                self.endpoints.append(
                    {
                        "path": p,
                        "name": name,
                        "method": method[0] if method else None,
                        "op": op,
                        "part": self.view.part.get(cell.block_id, ()),
                        "evidence": cell.ev(),
                        "method_evidence": method[1].ev() if method else None,
                        "description_evidence": desc.ev() if desc else None,
                    }
                )
        for bid in self.view.ids:
            if bid in self.table_blocks:
                continue
            for m in re.finditer(r"\b(GET|POST|PUT|PATCH|DELETE)\s+`?(/[A-Za-z][\w{}\-./]*)", self.view.text(bid)):
                p = m.group(2)
                if p in seen:
                    continue
                seen.add(p)
                name = [s for s in p.split("/") if s][-1]
                text = self.view.text(bid)
                self.endpoints.append(
                    {
                        "path": p, "name": name, "method": m.group(1),
                        "op": op_of_name(name) or op_of_method(m.group(1)),
                        "part": self.view.part.get(bid, ()),
                        "evidence": evidence_of(bid, text, m.start(2), m.end(2)),
                        "method_evidence": evidence_of(bid, text, m.start(1), m.end(1)),
                        "description_evidence": None,
                    }
                )

    def subject_for(self, part: tuple) -> Optional[str]:
        eps = [e for e in self.endpoints if e["part"] == part]
        if len(eps) == 1:
            return eps[0]["name"]
        return strip_md(part[-1]) if part else None

    def add(self, f: Fact) -> Fact:
        bid = (f.evidence or {}).get("block_id")
        if bid:
            f.role = self.view.role.get(bid, f.role)
            f.part = self.view.part.get(bid, ())
            if not f.scope:
                f.scope = self.view.scope(bid)
        ev = f.evidence
        if ev and ev.get("quote") is None and bid:
            ev["quote"] = self.view.text(bid)[ev["start"]: ev["end"]]
        self.facts.append(f)
        return f

    # ---------- таблицы полей
    def table_facts(self) -> None:
        for t in self.tables:
            first = t.block_ids[0]
            role = self.view.role.get(first, "other")
            if role == "template":
                continue
            c_name, c_type, c_logic = t.col("name"), t.col("type"), t.col("logic")
            if c_name is None or (c_type is None and c_logic is None):
                continue
            direction = {"api_request": "request", "api_response": "response"}.get(role)
            if direction is None:
                h = norm(" ".join(t.section[-2:]))
                direction = "request" if re.search(r"запрос|request|query", h) else (
                    "response" if re.search(r"ответ|response", h) else None)
            part = self.view.part.get(first, ())
            subject = self.subject_for(part)
            c_size, c_mand, c_desc, c_db = t.col("size"), t.col("mandatory"), t.col("description"), t.col("db")
            for row in t.rows:
                if c_name >= len(row) or not row[c_name].clean:
                    continue
                cell = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
                name = row[c_name].clean
                f = Fact(subject=subject, field=name, direction=direction, source="table")
                f.evidence = _row_ev(row)
                f.cells["field"] = row[c_name].ev()
                if cell(c_type) and cell(c_type).clean:
                    f.type = norm_type(cell(c_type).clean)
                    f.cells["type"] = cell(c_type).ev()
                if cell(c_size) and cell(c_size).clean:
                    f.size = parse_size(cell(c_size).clean)
                    f.cells["size"] = cell(c_size).ev()
                if cell(c_mand) and cell(c_mand).clean:
                    mv = norm(cell(c_mand).clean)
                    f.mandatory = True if mv.startswith(("да", "yes", "y", "+", "обяз")) else (
                        False if mv.startswith(("нет", "no", "n", "-")) else None)
                if cell(c_desc) and cell(c_desc).clean:
                    alias, unit = _desc_alias_unit(cell(c_desc).clean)
                    if alias:
                        f.aliases.append(alias)
                    if unit:
                        f.unit = unit
                        f.cells["unit"] = cell(c_desc).ev()
                if cell(c_db) and cell(c_db).clean and cell(c_db).clean not in ("-", "—"):
                    f.binding = cell(c_db).clean
                if cell(c_logic) and cell(c_logic).clean:
                    lg = parse_logic(cell(c_logic).clean)
                    lc = cell(c_logic).ev()
                    if "range" in lg:
                        a, b, u = lg["range"]
                        unit = u or f.unit
                        if u and not f.unit:
                            f.unit = u
                        incl = True if lg.get("inclusive") else None
                        f.range = make_range(a, b, unit, incl, incl)
                        f.cells["range"] = lc
                    if "enum" in lg:
                        f.enum = lg["enum"]
                        f.cells["enum"] = lc
                    if lg.get("representation"):
                        f.representation = lg["representation"]
                        f.cells["representation"] = lc
                    if "condition" in lg:
                        f.condition = lg["condition"]
                        f.cells["condition"] = lc
                    if not lg:
                        f.notes.append(f"логика: {cell(c_logic).clean}")
                self.add(f)

    # ---------- текстовые факты
    def text_facts(self) -> None:
        for bid in self.view.ids:
            role = self.view.role.get(bid, "other")
            if role in ("heading", "template"):
                continue
            kind = self.view.kind(bid)
            text = self.view.text(bid)
            if "code" in kind or text.lstrip().startswith(("{", "[", "```")):
                continue
            if bid in self.table_blocks:
                for t in self.tables:
                    if bid not in t.block_ids:
                        continue
                    is_field_table = t.col("name") is not None and (t.col("type") is not None or t.col("logic") is not None)
                    is_kv = len(t.header) == 2 or t.col("value") is not None
                    if is_field_table or (is_kv and role in ("api", "api_request", "api_response", "general")):
                        continue
                    for row in t.rows:
                        for c in row:
                            if c.block_id == bid and c.clean:
                                self._scan(bid, c.text, c.start, role, label=None)
                continue
            self._scan(bid, text, 0, role, label=None)

    def _scan(self, bid: str, text: str, base: int, role: str, label: Optional[str]) -> None:
        full = self.view.text(bid)
        taken: list[tuple[int, int]] = []
        for m in _RANGE_TEXT_RE.finditer(text):
            if re.match(rf"\s*(?:{_MONTH_WORDS})", text[m.end("b"):], re.I):
                continue
            a, b = parse_num(m.group("a")), parse_num(m.group("b"))
            if a is None or b is None:
                continue
            unit = unit_of(m.group("cura") or m.group("curb"))
            phrase, adj = _head_phrase(text[: m.start()])
            incl = True if m.group("incl") else None
            f = Fact(field=phrase, source="text", unit=unit)
            f.subject = _actor(text[: m.start()])
            if adj and norm_type(adj) == "integer":
                f.type = "integer"
            f.range = make_range(a, b, unit, incl, incl)
            f.evidence = evidence_of(bid, full, base + m.start(), base + m.end())
            f.cells["range"] = f.evidence
            self.add(f)
            taken.append((m.start(), m.end()))
        for m in _MONEY_DEF_RE.finditer(text):
            if any(s <= m.start("num") < e for s, e in taken):
                continue
            phrase, _ = _head_phrase(text[: m.start()])
            if not phrase:
                continue
            v, u = parse_num(m.group("num")), unit_of(m.group("cur"))
            mi = to_minor(v, u)
            if v is None or u is None:
                continue
            f = Fact(field=phrase, source="text", unit=u, value=dec_str(v), value_minor=mi, type="money")
            sent_start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
            f.evidence = evidence_of(bid, full, base + sent_start + (len(text[sent_start:]) - len(text[sent_start:].lstrip())),
                                     base + m.end())
            f.cells["value"] = evidence_of(bid, full, base + m.start("num"), base + m.end())
            self.add(f)
            taken.append((m.start("num"), m.end()))
        for m in _UNIT_STMT_RE.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            phrase, _ = _head_phrase(text[: m.start()])
            if not phrase:
                continue
            unit = unit_of(m.group("u"))
            ps = text.rfind(phrase, 0, m.start())
            ps = ps if ps >= 0 else m.start()
            f = Fact(field=phrase, source="text", unit=unit)
            f.evidence = evidence_of(bid, full, base + ps, base + m.end())
            f.cells["unit"] = f.evidence
            self.add(f)
        if role == "acceptance":
            for m in _MONEY_RE.finditer(text):
                if any(s <= m.start() < e for s, e in taken):
                    continue
                phrase, _ = _head_phrase(text[: m.start()])
                v, u = parse_num(m.group("num")), unit_of(m.group("cur"))
                if v is None or u is None:
                    continue
                f = Fact(field=phrase, source="acceptance", unit=u, value=dec_str(v), value_minor=to_minor(v, u), type="money")
                f.evidence = evidence_of(bid, full, base + m.start(), base + m.end())
                f.cells["value"] = f.evidence
                self.add(f)
        # уточнения раздела без явного поля: «Целое число тенге, обе границы включены»
        nt = norm(text)
        if role in ("api", "api_logic") and re.search(r"обе границы включ|границы включительно|включительно", nt):
            self._qualifiers.append((bid, base, text, "inclusive"))
        if role in ("api", "api_logic") and re.search(r"цел\w+ числ\w*", nt):
            self._qualifiers.append((bid, base, text, "integer"))

    _qualifiers: list

    def apply_qualifiers(self) -> None:
        """«Целое число тенге, обе границы включены» уточняет единственный денежный диапазон той же части."""
        for bid, base, text, what in self._qualifiers:
            part = self.view.part.get(bid, ())
            targets = [f for f in self.facts if f.part == part and f.range and f.source == "table"]
            mu = re.search(r"(тенге|тиын\w*|₸)", norm(text))
            unit = unit_of(mu.group(1)) if mu else None
            if unit:
                targets = [f for f in targets if f.unit in (None, unit)]
            if len(targets) != 1:
                continue
            f = targets[0]
            ev = evidence_of(bid, self.view.text(bid), base, base + len(text.rstrip()))
            if what == "inclusive" and f.range.get("min_inclusive") is None:
                f.range["min_inclusive"] = True
                f.range["max_inclusive"] = True
                f.cells["inclusive"] = ev
                f.enriched_by.append(f"включённость границ из {bid}")
            if what == "integer" and f.type in (None, "number"):
                f.type = "integer"
                f.enriched_by.append(f"целочисленность из {bid}")

    # ---------- статусы и примеры ответов
    def status_facts(self) -> None:
        part_subject = {}
        for bid in self.view.ids:
            role = self.view.role.get(bid)
            if role not in ("api_response", "api") or bid in self.table_blocks:
                continue
            text = self.view.text(bid)
            part = self.view.part.get(bid, ())
            subject = part_subject.setdefault(part, self.subject_for(part))
            if self.view.kind(bid).startswith("heading") or role == "heading":
                continue
            if "code" in self.view.kind(bid) or text.lstrip().startswith(("{", "[", "```")):
                self._example_facts(bid, subject)
                continue
            off = 0
            for ln in text.split("\n"):
                m = re.match(r"^\s*\**\s*(?P<code>[1-5]\d\d)\s*\.?\s*\**\s*(?P<cond>\S.*)?$", ln)
                if m and m.group("cond") and re.search(r"[а-яa-z]{3}", m.group("cond"), re.I):
                    code = int(m.group("code"))
                    cond = strip_md(m.group("cond")).rstrip()
                    cond = re.sub(r"^(?:ответ\s+)?в случае,?\s*(?:если\s+)?", "", cond, flags=re.I).rstrip(" .")
                    f = Fact(subject=subject, field=f"HTTP {code}", direction="response", type="http_status",
                             value=code, condition=cond, source="status")
                    f.evidence = evidence_of(bid, text, off + len(ln) - len(ln.lstrip()), off + len(ln.rstrip()))
                    self.add(f)
                off += len(ln) + 1
        for bid in self.view.ids:
            if self.view.role.get(bid) != "heading":
                continue
            sec = self.view.section(bid)
            if self.view.part.get(bid, ()) and not any(_API_PART.search(norm(h)) for h in sec):
                continue
            text = self.view.text(bid)
            m = re.search(r"\b([1-5]\d\d)\b\.?\s*(.*)", strip_md(text))
            if m and any(_API_PART.search(norm(h)) for h in sec):
                part = self.view.part.get(bid, ())
                f = Fact(subject=part_subject.get(part) or self.subject_for(part), field=f"HTTP {m.group(1)}",
                         direction="response", type="http_status", value=int(m.group(1)), source="status_heading")
                if m.group(2):
                    f.notes.append(f"заголовок: {m.group(2).strip()}")
                q = text.rstrip()
                lead = len(text) - len(text.lstrip())
                f.evidence = evidence_of(bid, text, lead, len(q))
                self.add(f)

    def _status_of_code_block(self, bid: str) -> Optional[int]:
        i = self.view.pos[bid]
        if i > 0:
            prev = self.view.ids[i - 1]
            if self.view.section(prev) == self.view.section(bid) and self.view.role.get(prev) != "heading":
                last = [ln for ln in self.view.text(prev).split("\n") if ln.strip()]
                if last:
                    m = re.fullmatch(r"\s*\**\s*([1-5]\d\d)\s*\**\s*", last[-1])
                    if m:
                        return int(m.group(1))
        for h in reversed(self.view.section(bid)):
            m = re.search(r"\b([1-5]\d\d)\b", strip_md(h))
            if m:
                return int(m.group(1))
        return None

    def _example_facts(self, bid: str, subject: Optional[str]) -> None:
        text = self.view.text(bid)
        body = "\n".join(ln for ln in text.split("\n") if not ln.strip().startswith("```"))
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        code = self._status_of_code_block(bid)
        for k, v in data.items():
            m = re.search(r'"' + re.escape(str(k)) + r'"\s*:\s*("(?:[^"\\]|\\.)*"|[^,}\]\s]+)', text)
            jt = {str: "string", bool: "boolean", int: "integer", float: "number"}.get(type(v), "object")
            f = Fact(subject=subject, field=str(k), direction="response", type=jt, value=v,
                     condition=f"HTTP {code}" if code else None, source="example")
            f.evidence = evidence_of(bid, text, m.start(), m.end()) if m else evidence_of(bid, text, 0, len(text.rstrip()))
            f.cells["value"] = f.evidence
            if code:
                f.notes.append(f"пример тела ответа для HTTP {code}")
            self.add(f)

    def run(self) -> list[Fact]:
        self._qualifiers = []
        self.collect_endpoints()
        self.table_facts()
        self.text_facts()
        self.apply_qualifiers()
        self.status_facts()
        for f in self.facts:
            if f.range and f.unit and f.range.get("min_minor") is None:
                lo, hi = Decimal(f.range["min"]), Decimal(f.range["max"])
                f.range["min_minor"], f.range["max_minor"] = to_minor(lo, f.unit), to_minor(hi, f.unit)
        self.facts.sort(key=lambda f: (self.view.pos.get((f.evidence or {}).get("block_id"), 10**9),
                                       (f.evidence or {}).get("start", 0)))
        for i, f in enumerate(self.facts, 1):
            f.id = f"FX-{i:03d}"
        return self.facts


_OPS = {
    "read": ("get", "read", "list", "fetch", "load", "show", "find", "search", "query", "view", "retrieve", "info", "status"),
    "write": ("save", "set", "update", "create", "add", "put", "post", "edit", "change", "upsert", "store", "register", "enable", "disable"),
    "delete": ("delete", "remove", "del", "clear", "drop"),
}


def op_of_name(name: str) -> Optional[str]:
    toks = [t.lower() for t in (_CAMEL.findall(name) or [name])]
    toks = [p for t in toks for p in re.split(r"[_\-.]", t) if p]
    if not toks:
        return None
    for op, verbs in _OPS.items():
        if toks[0] in verbs:
            return op
    return None


def op_of_method(method: Optional[str]) -> Optional[str]:
    return {"GET": "read", "HEAD": "read", "POST": "write", "PUT": "write", "PATCH": "write", "DELETE": "delete"}.get(
        (method or "").upper())


# =============================================================== 9. подсказки №04


def _iter_hints(fact_hints: Any) -> list[dict]:
    if not fact_hints:
        return []
    if isinstance(fact_hints, dict):
        for k in ("facts", "fields", "items", "inventory"):
            if isinstance(fact_hints.get(k), list):
                return [as_dict(x) for x in fact_hints[k]]
        return [fact_hints]
    return [as_dict(x) for x in fact_hints]


def _hint_range(r: Any, unit: Optional[str]) -> Optional[dict]:
    if r is None:
        return None
    if isinstance(r, str):
        lg = parse_logic(r)
        if "range" in lg:
            a, b, u = lg["range"]
            incl = True if lg.get("inclusive") else None
            return make_range(a, b, u or unit, incl, incl)
        return None
    if isinstance(r, (list, tuple)) and len(r) == 2:
        a, b = parse_num(str(r[0])), parse_num(str(r[1]))
        return make_range(a, b, unit, None, None) if a is not None and b is not None else None
    d = as_dict(r)
    a, b = parse_num(str(d.get("min", ""))), parse_num(str(d.get("max", "")))
    if a is None or b is None:
        return None
    return make_range(a, b, unit, d.get("min_inclusive"), d.get("max_inclusive"))


def merge_hints(facts: list[Fact], fact_hints: Any, resolver: Resolver, warnings: list[str]) -> list[Fact]:
    """Обогащает детерминированные факты подсказками №04; новые факты — только с опорой."""
    added: list[Fact] = []
    for h in _iter_hints(fact_hints):
        hint = as_dict(h.get("hint")) or {k: h.get(k) for k in ("block_id", "quote", "context") if h.get(k) is not None}
        ev = resolver(hint) if hint else None
        if ev is None:
            warnings.append(f"Подсказка №04 отклонена: цитата не найдена ({str(hint.get('quote', ''))[:60]!r}).")
            continue
        unit = unit_of(h.get("unit")) or (str(h.get("unit")) if h.get("unit") else None)
        slots = {
            "subject": h.get("subject"),
            "field": h.get("field") or h.get("name"),
            "direction": (h.get("direction") or None),
            "type": norm_type(h.get("type")) if h.get("type") else None,
            "unit": unit,
            "condition": h.get("condition"),
            "range": _hint_range(h.get("range"), unit),
        }
        val = h.get("value")
        target = None
        for f in facts:
            fe = f.evidence or {}
            if fe.get("block_id") != ev["block_id"]:
                continue
            overlap = fe.get("start", 0) < ev["end"] and ev["start"] < fe.get("end", 0)
            same_field = not slots["field"] or (tuple(keys_of(slots["field"])) in f.alias_keys())
            if overlap and same_field:
                target = f
                break
        if target is None:
            f = Fact(source="hint", evidence=ev)
            for k, v in slots.items():
                if v is not None:
                    setattr(f, k, v)
            if val is not None:
                pv = parse_money(str(val)) if unit in MONEY_UNITS or parse_money(str(val)) else None
                if pv:
                    f.value, f.unit, f.value_minor = dec_str(pv[0]), pv[1], pv[2]
                else:
                    f.value = val
            f.enriched_by.append("№04")
            added.append(f)
            continue
        for k, v in slots.items():
            if v is None:
                continue
            cur = getattr(target, k)
            if cur in (None, "", []):
                setattr(target, k, v)
                target.enriched_by.append(f"№04:{k}")
            elif k == "range":
                if (cur.get("min"), cur.get("max")) != (v.get("min"), v.get("max")):
                    warnings.append(f"{target.id or target.field}: диапазон из подсказки №04 расходится с разбором, оставлен разбор.")
                for inc in ("min_inclusive", "max_inclusive"):
                    if cur.get(inc) is None and v.get(inc) is not None:
                        cur[inc] = v[inc]
                        target.enriched_by.append(f"№04:{inc}")
            elif norm(cur) != norm(v):
                warnings.append(f"{target.field}: «{k}» из подсказки №04 ({v}) расходится с разбором ({cur}), оставлен разбор.")
    return added


# =============================================================== 10. сравнения

# подвид №06 → (kind контракта, criterion из SET_CRITERIA, severity по умолчанию)
_DEFAULT_CRITERIA = {
    "conflict": ("set_consistent", "critical"),
    "missing_contract": ("set_complete", "critical"),
    "question": ("set_consistent", "major"),
    "type_question": ("set_consistent", "minor"),
}
CONTRACT_KIND = {"conflict": "conflict", "missing_contract": "omission", "question": "ambiguity",
                 "type_question": "ambiguity"}
_BLOCKED = {
    "conflict": "какой исход реализовать и какой ожидать в тесте для общего входа",
    "missing_contract": "как клиенту выполнить обещанную операцию и чем её проверить",
    "question": "какой исход заложить в реализацию и в тест",
    "type_question": "как сериализовать поле в контрактных тестах",
}
_RECOMMEND = {
    "conflict": "Выбрать один исход для этого входа, исправить вторую формулировку и добавить пример приёмки на этот вход.",
    "missing_contract": "Описать метод для обещанной операции (URL, REST type, параметры, ответ, статусы) или убрать обещание.",
    "question": "Уточнить условие у автора требования и зафиксировать исход в тексте и в приёмке.",
    "type_question": "Указать формат поля в ответе и правило преобразования из запроса.",
}


CRITERIA_PATH = Path(__file__).resolve().parent.parent / "criteria.toml"
_criteria_cache: dict = {}


def _criteria_data() -> dict:
    try:
        mtime = CRITERIA_PATH.stat().st_mtime
    except OSError:
        return {}
    if _criteria_cache.get("mtime") != mtime:
        try:
            import tomllib

            _criteria_cache.update(mtime=mtime, data=tomllib.loads(CRITERIA_PATH.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — конфиг соседнего модуля не должен ронять анализ
            _criteria_cache.update(mtime=mtime, data={})
    return _criteria_cache.get("data", {})


def criteria_for(kind: str) -> tuple[str, str]:
    """Критерий и серьёзность: src/bcc_review/criteria.toml ([cross.<kind>] или [kinds.<kind>]) либо дефолт."""
    crit, sev = _DEFAULT_CRITERIA.get(kind, ("consistency", "major"))
    data = _criteria_data()
    for top in ("cross", "kinds"):
        node = data.get(top, {}).get(kind) if isinstance(data.get(top), dict) else None
        if isinstance(node, dict):
            crit = node.get("criterion", crit)
            sev = node.get("severity", sev)
    return crit, sev


def make_candidate(kind: str, title: str, impact: str, hints: list, *, req_ids: Iterable = (),
                   scope: str = "set", severity: Optional[str] = None, criterion: Optional[str] = None,
                   cand_kind: Optional[str] = None, origin: str = "rules", **extra: Any) -> dict:
    """Candidate контракта v1. ``kind`` — подвид №06 (conflict|missing_contract|question),
    в выходе он лежит в ``subkind``, а ``kind`` берётся из словаря контракта (conflict|omission|ambiguity)."""
    sub = cand_kind or kind
    crit, sev = criteria_for(sub)
    c = {
        "scope": scope,
        "kind": CONTRACT_KIND.get(kind, kind),
        "subkind": kind,
        "criterion": criterion or crit,
        "severity": severity or sev,
        "title": title,
        "impact": impact,
        "req_ids": list(dict.fromkeys(req_ids)),
        "hints": [{"block_id": h["block_id"], "quote": h["quote"]} for h in hints if h and h.get("quote")],
        "recommendation": extra.pop("recommendation", None) or _RECOMMEND.get(sub, _RECOMMEND["question"]),
        "blocked_decision": extra.pop("blocked_decision", None) or _BLOCKED.get(sub, _BLOCKED["question"]),
        "source": "llm" if origin == "llm" else "rules",
        "stage": "cross",
        "origin": origin,
    }
    w = extra.pop("witness", None)
    if w:
        c["witness"] = draft_witness(w)
        c["cause"] = {"object": str(extra.pop("cause_object", "") or title),
                      "condition": c["witness"]["input"], "outcomes": [c["witness"]["outcome_a"], c["witness"]["outcome_b"]]}
    c.update(extra)
    return c


def _input_text(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    d = as_dict(detail)
    parts = [str(d.get("description") or "").rstrip(".")]
    doc = [f"{x.get('name')} = «{x.get('value')}»" for x in d.get("document_data") or []]
    ill = [f"{x.get('name')} = {x.get('value')}" + (f" ({x.get('why')})" if x.get("why") else "")
           for x in d.get("illustrative") or []]
    if doc:
        parts.append("данные документа: " + "; ".join(doc))
    if ill:
        parts.append("иллюстративно: " + "; ".join(ill))
    return ". ".join(p for p in parts if p) + "."


def draft_witness(w: dict) -> dict:
    """WitnessDraft контракта (input — строка, hint_a/hint_b) + Evidence и структура входа для отчёта."""
    if "input_detail" in w:
        return w
    ea, eb = w.get("evidence_a"), w.get("evidence_b")
    out = {
        "input": _input_text(w.get("input")),
        "outcome_a": str(w.get("outcome_a") or ""),
        "outcome_b": str(w.get("outcome_b") or ""),
        "hint_a": {"block_id": ea["block_id"], "quote": ea["quote"]} if ea else {"quote": ""},
        "hint_b": {"block_id": eb["block_id"], "quote": eb["quote"]} if eb else {"quote": ""},
        "evidence_a": ea,
        "evidence_b": eb,
        "input_detail": w.get("input") if isinstance(w.get("input"), dict) else {"description": str(w.get("input") or "")},
    }
    for k in ("outcome_a_value", "outcome_b_value", "outcome_target"):
        if w.get(k) not in (None, ""):
            out[k] = w[k]
    return out


def _dim(unit: Optional[str]) -> Optional[str]:
    if unit in MONEY_UNITS:
        return "money"
    return unit


def _range_minor(f: Fact) -> Optional[tuple[Decimal, Decimal, Optional[bool], Optional[bool]]]:
    r = f.range
    if not r:
        return None
    if _dim(f.unit) == "money":
        lo, hi = r.get("min_minor"), r.get("max_minor")
        if lo is None or hi is None:
            return None
        return Decimal(lo), Decimal(hi), r.get("min_inclusive"), r.get("max_inclusive")
    return Decimal(r["min"]), Decimal(r["max"]), r.get("min_inclusive"), r.get("max_inclusive")


def _within(r: tuple, v: Decimal) -> bool:
    lo, hi, li, hi_i = r
    ok_lo = v >= lo if li is not False else v > lo
    ok_hi = v <= hi if hi_i is not False else v < hi
    return ok_lo and ok_hi


def _label(f: Fact, view: DocView) -> str:
    where = view.scope((f.evidence or {}).get("block_id", "")) or f.scope
    d = {"request": "запрос", "response": "ответ"}.get(f.direction or "", "")
    return f"«{f.field}» ({', '.join(x for x in (where, d) if x)})"


def _fmt_val(v: Decimal, f: Fact) -> str:
    if _dim(f.unit) == "money":
        return fmt_money(int(v), f.unit if f.unit == "tiyn" else "KZT")
    return fmt_num(v)


def aligned(a: Fact, b: Fact) -> bool:
    if a.binding and b.binding:
        return norm(a.binding) == norm(b.binding)
    if a.source in ("table", "example") and b.source in ("table", "example") and a.subject and b.subject \
            and a.subject != b.subject:
        return False
    return bool(a.alias_keys() & b.alias_keys())


class Comparator:
    """Сравнивает выровненные факты: границы, значения, единицы, типы, разрядность, HTTP-исходы."""

    def __init__(self, view: DocView, facts: list[Fact]):
        self.view = view
        self.facts = facts
        self.comparisons: list[dict] = []
        self.candidates: list[dict] = []

    def log(self, aspect: str, verdict: str, facts: list[Fact], explanation: str, **extra: Any) -> dict:
        c = {
            "id": f"CMP-{len(self.comparisons) + 1:03d}",
            "aspect": aspect,
            "verdict": verdict,
            "fact_ids": [f.id for f in facts],
            "explanation": explanation,
        }
        c.update(extra)
        self.comparisons.append(c)
        return c

    def run(self) -> None:
        defs = [f for f in self.facts if f.source not in ("status", "status_heading")]
        for i, a in enumerate(defs):
            self._self_check(a)
            for b in defs[i + 1:]:
                ea, eb = a.evidence or {}, b.evidence or {}
                if ea.get("block_id") == eb.get("block_id") and ea.get("start") == eb.get("start"):
                    continue
                if a.source == "example" and b.source == "example":
                    continue
                if not aligned(a, b):
                    continue
                self._ranges(a, b)
                self._value_range(a, b)
                self._value_range(b, a)
                self._values(a, b)
                self._units(a, b)
                self._types(a, b)
        self._statuses()

    # --- границы одного поля
    def _ranges(self, a: Fact, b: Fact) -> None:
        if not (a.range and b.range):
            return
        if _dim(a.unit) != _dim(b.unit) and a.unit and b.unit:
            return
        ra, rb = _range_minor(a), _range_minor(b)
        if ra is None or rb is None:
            return
        if ra[:2] == rb[:2]:
            ia, ib = ra[2:], rb[2:]
            known = all(x is not None for x in ia + ib)
            if known and ia != ib:
                v = ra[0] if ia[0] != ib[0] else ra[1]
                self._range_conflict(a, b, ra, rb, v, from_doc=True)
                return
            note = "" if known else "; включённость границ указана не в обоих местах — принята включительной"
            same_units = (a.unit == b.unit) or not (a.unit and b.unit)
            expl = (f"Границы совпадают: {_fmt_val(ra[0], a)}–{_fmt_val(ra[1], a)}"
                    + ("" if same_units else f" (сравнение в тиынах: {UNIT_LABEL.get(a.unit, a.unit)} и {UNIT_LABEL.get(b.unit, b.unit)})")
                    + note + ".")
            self.log("range", "compatible", [a, b], expl)
            return
        step = Decimal(100) if _dim(a.unit) == "money" and "integer" in (a.type, b.type) else Decimal(1)
        if _dim(a.unit) == "money" and step == 1 and all(x % 100 == 0 for x in (ra[0], ra[1], rb[0], rb[1])):
            step = Decimal(100)
        points = sorted({ra[0], ra[1], rb[0], rb[1]})
        bounds = set(points)
        # минимальный пример: соседнее с границей значение (иллюстративное), затем сами границы
        adjacent = sorted({p + d for p in points for d in (-step, step)} - bounds,
                          key=lambda x: (min(abs(x - p) for p in points), x))
        cand = adjacent + points
        for v in cand:
            if _within(ra, v) != _within(rb, v):
                self._range_conflict(a, b, ra, rb, v, from_doc=v in bounds)
                return

    def _range_conflict(self, a: Fact, b: Fact, ra: tuple, rb: tuple, v: Decimal, from_doc: bool) -> None:
        ina, inb = _within(ra, v), _within(rb, v)
        val = _fmt_val(v, a)
        ok, no = "значение допустимо", "значение отклоняется как выходящее за границы"
        ev_a, evb = a.ev_for("range"), b.ev_for("range")
        doc_items = [
            {"name": f"границы по {_label(a, self.view)}", "value": f"{_fmt_val(ra[0], a)}–{_fmt_val(ra[1], a)}", "evidence": ev_a},
            {"name": f"границы по {_label(b, self.view)}", "value": f"{_fmt_val(rb[0], b)}–{_fmt_val(rb[1], b)}", "evidence": evb},
        ]
        illus = [] if from_doc else [{
            "name": a.field, "value": val,
            "why": "выбрано программой: ближайшее к границе значение, которое попадает ровно в один из диапазонов",
        }]
        witness = {
            "input": {
                "description": f"Задать «{a.field}» = {val}",
                "document_data": doc_items + ([{"name": a.field, "value": val, "evidence": ev_a if ina else evb}] if from_doc else []),
                "illustrative": illus,
            },
            "outcome_a": f"{ok if ina else no} (по {_label(a, self.view)})",
            "outcome_b": f"{ok if inb else no} (по {_label(b, self.view)})",
            "evidence_a": ev_a,
            "evidence_b": evb,
        }
        cmp = self.log("range", "mismatch", [a, b],
                       f"Разные границы одного поля: {doc_items[0]['value']} и {doc_items[1]['value']}; при {val} исходы расходятся.")
        self.candidates.append(make_candidate(
            "conflict",
            f"Разные границы «{a.field}»: {doc_items[0]['value']} и {doc_items[1]['value']}",
            f"Для значения {val} одна часть документа требует принять ввод, другая — отклонить; разработка "
            f"и тесты не смогут выполнить оба утверждения.",
            [ev_a, evb], witness=witness, origin="facts", comparison_id=cmp["id"],
            checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
        ))

    # --- значение примера/приёмки против границ
    def _value_range(self, v: Fact, r: Fact) -> None:
        if v.range or not r.range or v.value is None:
            return
        rr = _range_minor(r)
        if rr is None:
            return
        val: Optional[Decimal] = None
        if _dim(r.unit) == "money":
            if v.value_minor is not None:
                val = Decimal(v.value_minor)
            elif isinstance(v.value, (int, str)) and re.fullmatch(r"-?\d+(?:[.,]\d+)?", str(v.value)):
                val = Decimal(to_minor(Decimal(str(v.value).replace(",", ".")), r.unit or "KZT") or 0)
        elif isinstance(v.value, (int, float, str)) and re.fullmatch(r"-?\d+(?:[.,]\d+)?", str(v.value)):
            val = Decimal(str(v.value).replace(",", "."))
        if val is None:
            return
        inside = _within(rr, val)
        verdict = "compatible" if inside else ("mismatch" if v.source != "acceptance" else "question")
        self.log("value_range", verdict, [v, r],
                 f"Значение {_fmt_val(val, r)} {'внутри' if inside else 'вне'} границ {_fmt_val(rr[0], r)}–{_fmt_val(rr[1], r)}.")
        if not inside and v.source in ("acceptance", "example"):
            self.candidates.append(make_candidate(
                "question",
                f"Пример использует «{v.field}» = {_fmt_val(val, r)} вне допустимых границ",
                "Пример или приёмка опирается на значение, которое правило запрещает: неясно, проверяет ли он "
                "отказ или границы заданы неверно.",
                [v.ev_for("value"), r.ev_for("range")], origin="facts",
                question=f"Пример задаёт «{v.field}» = {_fmt_val(val, r)}, а правило допускает "
                         f"{_fmt_val(rr[0], r)}–{_fmt_val(rr[1], r)}. Какой исход ожидается?",
            ))

    # --- одна величина в разных единицах
    def _values(self, a: Fact, b: Fact) -> None:
        if a.value_minor is None or b.value_minor is None or "acceptance" in (a.source, b.source) \
                or "example" in (a.source, b.source):
            return
        if a.value_minor == b.value_minor:
            self.log("value", "compatible", [a, b],
                     f"Одна сумма: {fmt_money(a.value_minor)} = {fmt_num(Decimal(b.value_minor))} тиын"
                     f" ({a.value} {UNIT_LABEL.get(a.unit)} и {b.value} {UNIT_LABEL.get(b.unit)}).")
            return
        cmp = self.log("value", "mismatch", [a, b],
                       f"Разные значения одной величины: {fmt_money(a.value_minor)} и {fmt_money(b.value_minor)}.")
        ea, eb = a.ev_for("value"), b.ev_for("value")
        self.candidates.append(make_candidate(
            "conflict", f"Разные значения «{a.field}»: {fmt_money(a.value_minor)} и {fmt_money(b.value_minor)}",
            "Реализация и тест получат разные константы для одной величины.", [ea, eb],
            origin="facts", comparison_id=cmp["id"],
            witness={
                "input": {"description": f"Прочитать значение «{a.field}»",
                          "document_data": [{"name": a.field, "value": fmt_money(a.value_minor), "evidence": ea},
                                            {"name": b.field, "value": fmt_money(b.value_minor), "evidence": eb}],
                          "illustrative": []},
                "outcome_a": fmt_money(a.value_minor), "outcome_b": fmt_money(b.value_minor),
                "evidence_a": ea, "evidence_b": eb},
            checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
        ))

    def _units(self, a: Fact, b: Fact) -> None:
        if not (a.unit and b.unit) or a.value is not None or b.value is not None:
            return
        if a.range and b.range:
            return  # единицы уже учтены при сравнении границ в тиынах
        if a.unit == b.unit:
            self.log("unit", "compatible", [a, b], f"Одна единица: {UNIT_LABEL.get(a.unit, a.unit)}.")
        elif _dim(a.unit) == _dim(b.unit):
            self.log("unit", "compatible", [a, b],
                     f"Одна размерность (деньги): {UNIT_LABEL.get(a.unit)} и {UNIT_LABEL.get(b.unit)}, пересчёт 1 ₸ = 100 тиын точный.")
        else:
            self.log("unit", "undetermined", [a, b], f"Разные размерности: {a.unit} и {b.unit}.")

    # --- типы запроса и ответа
    def _representation(self, s: Fact, other_type: str) -> Optional[Evidence]:
        if s.representation == "string":
            return s.cells.get("representation") or s.evidence
        for e in self.facts:
            if e.source != "example" or not aligned(e, s) or e.direction != s.direction:
                continue
            if isinstance(e.value, str) and (other_type != "integer" or re.fullmatch(r"-?\d+", e.value)):
                return e.evidence
        return None

    def _types(self, a: Fact, b: Fact) -> None:
        if not (a.type and b.type) or "example" in (a.source, b.source) or "money" in (a.type, b.type):
            return
        ta, tb = a.type, b.type
        if ta == tb or {ta, tb} == {"integer", "number"}:
            self.log("type", "compatible", [a, b], f"Тип совпадает: {ta}" + ("" if ta == tb else f" / {tb}") + ".")
            return
        if a.direction != b.direction and "string" in (ta, tb):
            s, o = (a, b) if ta == "string" else (b, a)
            rep = self._representation(s, o.type)
            if rep is not None:
                self.log("type", "compatible", [a, b],
                         f"{o.type} в {_label(o, self.view)} и string в {_label(s, self.view)}: строковое представление "
                         f"оговорено («{rep['quote']}»).", evidence=rep)
                return
            cmp = self.log("type", "undetermined", [a, b],
                           f"{ta} и {tb} в разных направлениях; правило преобразования не найдено.")
            self.candidates.append(make_candidate(
                "question", f"Тип «{a.field}» различается: {_label(a, self.view)} {ta}, {_label(b, self.view)} {tb}",
                "Клиент и сервер могут по-разному сериализовать поле; без оговорённого преобразования тесты контракта неоднозначны.",
                [a.ev_for("type"), b.ev_for("type")], origin="facts", comparison_id=cmp["id"], cand_kind="type_question",
                question=f"«{a.field}» в одном месте {ta}, в другом {tb}. Это одно поле с разным представлением? "
                         f"Как значение преобразуется?",
            ))
            return
        if a.direction == b.direction and a.direction is not None:
            v = "12a" if "integer" in (ta, tb) or "number" in (ta, tb) else "abc"
            ea, eb = a.ev_for("type"), b.ev_for("type")
            cmp = self.log("type", "mismatch", [a, b], f"Одно поле одного направления описано как {ta} и {tb}.")
            self.candidates.append(make_candidate(
                "conflict", f"Тип «{a.field}» ({a.direction}) задан двумя способами: {ta} и {tb}",
                "Валидация запроса и контрактные тесты получают несовместимые правила.", [ea, eb],
                origin="facts", comparison_id=cmp["id"], severity="major",
                witness={"input": {"description": f"Передать «{a.field}» = \"{v}\"", "document_data": [],
                                   "illustrative": [{"name": a.field, "value": v, "why": "значение допустимо только для одного из типов"}]},
                         "outcome_a": "принять" if ta == "string" else "отклонить",
                         "outcome_b": "принять" if tb == "string" else "отклонить",
                         "evidence_a": ea, "evidence_b": eb},
                checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
            ))

    def _self_check(self, f: Fact) -> None:
        if not (f.size and f.range and f.size.get("bits")):
            return
        bits = int(f.size["bits"])
        limit = Decimal(2 ** (bits - 1) - 1)
        hi = Decimal(f.range["max"])
        if hi <= limit:
            self.log("size", "compatible", [f], f"Верхняя граница {fmt_num(hi)} помещается в {bits} bit (≤ {fmt_num(limit)}).")
        else:
            self.log("size", "mismatch", [f], f"Верхняя граница {fmt_num(hi)} не помещается в {bits} bit (> {fmt_num(limit)}).")
            self.candidates.append(make_candidate(
                "conflict", f"«{f.field}»: граница {fmt_num(hi)} больше разрядности {bits} bit",
                "Значения у верхней границы нельзя передать в объявленном типе.", [f.ev_for("range"), f.ev_for("size")],
                origin="facts", severity="major",
                witness={"input": {"description": f"Передать «{f.field}» = {fmt_num(hi)}",
                                   "document_data": [{"name": "верхняя граница", "value": fmt_num(hi), "evidence": f.ev_for("range")}],
                                   "illustrative": []},
                         "outcome_a": "значение допустимо по логике", "outcome_b": f"значение не представимо в {bits} bit",
                         "evidence_a": f.ev_for("range"), "evidence_b": f.ev_for("size")},
                checks={"evidence": "program", "preconditions": "program", "outcomes": "program"},
            ))

    # --- HTTP-исходы
    def _statuses(self) -> None:
        err_vals = {"error", "err", "fail", "failed", "failure", "ошибка", "false", "nok"}
        examples = [f for f in self.facts if f.source == "example" and f.condition]
        statuses = [f for f in self.facts if f.source == "status"]
        bad_2xx: dict[str, list[Fact]] = {}
        for e in examples:
            m = re.match(r"HTTP (\d{3})", e.condition or "")
            if not m or not m.group(1).startswith("2"):
                continue
            if (e.field.lower() in ("result", "status", "success") and norm(str(e.value)) in err_vals) or \
                    e.field.lower() in ("error", "errors", "error_code", "errorcode"):
                bad_2xx.setdefault((e.evidence or {}).get("block_id", ""), []).append(e)
        if not bad_2xx:
            return
        param_rx = re.compile(r"параметр|неверн|некоррект|формат|валидац|invalid|bad request|не прош")
        param_4xx = [s for s in statuses if 400 <= int(s.value) < 500 and param_rx.search(norm(s.condition or ""))]
        other_4xx = [s for s in statuses if 400 <= int(s.value) < 500 and s not in param_4xx]
        for bid, items in bad_2xx.items():
            code = re.match(r"HTTP (\d{3})", items[0].condition).group(1)
            body_ev = {"block_id": bid, "start": min(i.evidence["start"] for i in items),
                       "end": max(i.evidence["end"] for i in items)}
            body_ev["quote"] = self.view.text(bid)[body_ev["start"]:body_ev["end"]]
            msg = next((str(f.value) for f in self.facts if f.source == "example" and
                        (f.evidence or {}).get("block_id") == bid and f.field.lower() == "message"), None)
            for s in other_4xx:
                self.log("http_outcome", "compatible", items + [s],
                         f"HTTP {code} с ошибкой в теле и HTTP {s.value} ({s.condition}) описывают разные условия; общий вход не задан.")
            for s in param_4xx:
                cmp = self.log(
                    "http_outcome", "undetermined", items + [s],
                    f"Под HTTP {code} есть тело с ошибкой{f' «{msg}»' if msg else ''}, а HTTP {s.value} — «{s.condition}». "
                    f"Соседство не доказывает противоречие: общий вход нужно построить по фактам запроса.")
                self.candidates.append(make_candidate(
                    "question",
                    f"Один и тот же неверный ввод: HTTP {code} с ошибкой в теле или HTTP {s.value}?",
                    "Клиент не знает, по коду или по полю тела распознавать отказ; контрактные тесты неоднозначны.",
                    [body_ev, s.evidence], origin="facts", comparison_id=cmp["id"],
                    question=(f"Если запрос отклонён из-за значения параметра{f' («{msg}»)' if msg else ''}, какой код возвращается: "
                              f"HTTP {code} с телом {body_ev['quote']} или HTTP {s.value} («{s.condition}»)?"),
                    needs="общий вход: значение параметра, нарушающее его ограничение и одновременно подпадающее под оба описания",
                    status_pair={"success": int(code), "error": int(s.value)},
                ))


# =============================================================== 11. точки входа


@dataclass
class FactSet:
    view: DocView
    facts: list
    tables: list
    endpoints: list
    comparisons: list
    candidates: list
    warnings: list
    audit: Audit
    resolver: Resolver

    def by_id(self) -> dict:
        return {f.id: f for f in self.facts}


def extract_facts(document: Any, fact_hints: Any = None, *, resolve: Optional[Callable] = None,
                  view: Optional[DocView] = None, audit: Optional[Audit] = None) -> FactSet:
    view = view or DocView(document)
    audit = audit or Audit()
    resolver = Resolver(view, resolve, audit)
    warnings: list[str] = []
    fb = _FactBuilder(view)
    facts = fb.run()
    added = merge_hints(facts, fact_hints, resolver, warnings)
    if added:
        for f in added:
            bid = (f.evidence or {}).get("block_id")
            f.role = view.role.get(bid, "other")
            f.part = view.part.get(bid, ())
            f.scope = f.scope or view.scope(bid)
        facts.extend(added)
        for i, f in enumerate(facts, 1):
            f.id = f"FX-{i:03d}"
    for f in facts:
        if f.range and f.unit in MONEY_UNITS:
            f.range["min_minor"] = to_minor(Decimal(f.range["min"]), f.unit)
            f.range["max_minor"] = to_minor(Decimal(f.range["max"]), f.unit)
        if f.evidence and not resolver.check(f.evidence):
            warnings.append(f"{f.id}: опора не совпала с текстом блока и снята.")
            f.evidence = None
    facts = [f for f in facts if f.evidence]
    cmp = Comparator(view, facts)
    cmp.run()
    return FactSet(view, facts, fb.tables, fb.endpoints, cmp.comparisons, cmp.candidates, warnings, audit, resolver)


def reconcile_facts(document: Any, fact_hints: Any = None, *, resolve: Optional[Callable] = None) -> dict:
    """Таблица нормализованных фактов и кандидаты вычислимых расхождений.

    Возвращает ``{facts, candidates, comparisons, endpoints, warnings, evidence_audit}``;
    по контракту обязательны ``facts`` и ``candidates``, остальное — пояснения для отчёта.
    """
    fs = extract_facts(document, fact_hints, resolve=resolve)
    return {
        "facts": [f.to_dict() for f in fs.facts],
        "candidates": fs.candidates,
        "comparisons": fs.comparisons,
        "endpoints": fs.endpoints,
        "warnings": fs.warnings,
        "evidence_audit": fs.audit.as_dict(),
    }
