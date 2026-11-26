"""Привязка цитат к исходному документу: hint → Evidence с координатами.

Контракт v1
-----------
* ``Evidence = {block_id, start, end, quote}``; для подтверждённой опоры строго
  ``block.text[start:end] == quote``. Координаты — кодовые точки Unicode
  (индексы ``str`` в Python), отсчёт с нуля, правая граница исключена.
  Символ вне BMP (например, «𝟙») занимает одну позицию, а не две, как в UTF-16.
* ``Hint = {block_id, quote}`` и необязательный контекст: ``before``/``after``
  (синонимы ``context_before``/``context_after``, ``prefix``/``suffix``)
  или ``context`` — строка, внутри которой стоит цитата.
* Номер строки или страницы, предсказанный моделью, координатой не считается.
  Место вычисляется из ``block.loc`` и смещения внутри блока (:func:`locate`).

Как ищется цитата
-----------------
1. Текст блока и цитата приводятся к сравнимой форме :func:`normalize`.
   Допустимые различия: пробелы любого вида (NBSP, узкий NBSP, тонкий, табы,
   переводы строк) сворачиваются в один пробел; мягкий перенос и пробелы
   нулевой ширины удаляются; перенос слова по слогам («про-\\nверка») и дефис
   между буквами не различаются; графема (буква + диакритика) приводится к NFC.
   Для Markdown дополнительно не различаются маркеры ``*`` и `````.
   Цифры, знаки сравнения, валюта, регистр и отрицания не меняются.
2. Каждый символ нормализованной строки помнит свой диапазон в оригинале,
   поэтому найденное место отображается обратно в ``[start, end)`` оригинала,
   а цитатой в Evidence становится буквальная подстрока ``block.text``.
   Совпадение перепроверяется: нормализация этой подстроки обязана дать ту же
   строку, что и нормализация цитаты.
3. Совпадение отклоняется, если граница режет число («не более 10» внутри
   «не более 100 ₸»), слово («возможно» внутри «невозможно») или оставляет за
   цитатой отрицание («более 10 ₸» после «не»). Знак сравнения или единица
   за пределами цитаты дают предупреждение.
4. Повторы: внутри блока из hint ищутся все вхождения. Одно вхождение →
   ``matched``. Несколько → выбирает контекст; без контекста или при равенстве
   → ``ambiguous``. Без ``block_id`` или с несуществующим ID поиск идёт по всему
   документу. Если существующий блок цитаты не содержит, а другой содержит,
   ответ ``missing/found_in_other_block`` с точными кандидатами: ссылка модели
   на блок не подтверждена. Перенос включается явно (``relocate=True``) и
   помечается предупреждением ``block_relocated``.
5. Если цитата не найдена, нечёткий поиск (difflib) возвращает лишь
   *кандидатов* места с перечнем расхождений (цифра, отрицание, валюта).
   Кандидат никогда не становится Evidence: его показывают модели при повторном
   запросе или человеку. Число таких восстановлений ограничено
   :class:`RepairBudget`, общим на весь прогон.

Модуль не обращается к модели и не зависит от сторонних пакетов.
"""

from __future__ import annotations

import bisect
import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CONFLICT_KINDS",
    "OMISSION_KINDS",
    "REASONS",
    "DocumentIndex",
    "EvidenceAudit",
    "Normalized",
    "RepairBudget",
    "check_evidence",
    "check_finding_support",
    "describe",
    "locate",
    "normalize",
    "table_cell",
    "resolve_candidate",
    "resolve_hint",
]

# ---------------------------------------------------------------------------
# Причины: машинный код → текст для отчёта
# ---------------------------------------------------------------------------

REASONS: dict[str, str] = {
    # resolve_hint: missing
    "empty_quote": "цитата пустая",
    "not_found": "цитата не найдена в документе",
    "number_boundary": "граница цитаты режет число в источнике",
    "partial_word": "граница цитаты режет слово в источнике (в том числе приставку «не-»)",
    "negation_outside_quote": "перед цитатой в источнике стоит отрицание, а в цитату оно не вошло",
    "sign_outside_quote": "перед числом в источнике стоит знак, а в цитату он не вошёл",
    "number_mismatch": "похожее место есть, но числа в цитате и в источнике различаются",
    "negation_mismatch": "похожее место есть, но отрицание в цитате и в источнике различается",
    "currency_mismatch": "похожее место есть, но валюта или единица различаются",
    "comparison_mismatch": "похожее место есть, но знак сравнения различается",
    "wording_mismatch": "похожее место есть, но формулировка отличается от источника",
    "found_in_other_block": "в указанном блоке цитаты нет, она буквально есть в другом блоке",
    # resolve_hint: ambiguous
    "multiple_occurrences": "цитата встречается несколько раз, контекста для выбора нет",
    "context_not_unique": "контекст подходит к нескольким вхождениям",
    "context_mismatch": "контекст не подходит ни к одному вхождению",
    "duplicate_block_id": "в документе несколько блоков с этим идентификатором",
    # resolve_hint: предупреждения при matched
    "normalized_match": "цитата совпала после допустимой нормализации пробелов, переносов или разметки",
    "block_relocated": "в указанном блоке цитаты нет; найдено единственное вхождение в другом блоке",
    "unknown_block_id": "указанного блока нет в документе; поиск выполнен по всему документу",
    "no_block_id": "блок не указан; поиск выполнен по всему документу",
    "context_ignored": "контекст не совпал, но цитата в блоке единственная",
    "context_unusable": "строка контекста не содержит цитату ровно один раз; контекст не использован",
    "outer_quotes_stripped": "внешние кавычки вокруг цитаты отброшены",
    "comparison_outside_quote": "знак или слово сравнения перед числом не вошли в цитату",
    "unit_outside_quote": "единица или валюта после числа не вошла в цитату",
    "repair_budget_exhausted": "бюджет восстановления цитат исчерпан, кандидаты не искались",
    # resolve_candidate / check_finding_support
    "no_hints": "у замечания нет ни одной опоры",
    "hint_failed": "опора не подтверждена",
    "conflict_side_missing": "для конфликта нужна подтверждённая опора с каждой стороны",
    "conflict_sides_unspecified": "не указано, какая опора относится к какой стороне конфликта",
    "conflict_same_anchor": "обе стороны конфликта опираются на одно и то же место",
    "conflict_witness_missing": "нет сценария-свидетеля: входа и двух исходов",
    "conflict_outcomes_equal": "исходы свидетеля совпадают, несовместимости нет",
    "witness_evidence_not_in_finding": "опора свидетеля не входит в опоры замечания",
    "omission_scope_missing": "для пропуска не перечислена область, где искали описание",
    "unknown_inspected_block": "в области поиска пропуска указан несуществующий блок",
    "absent_term_present": "то, что объявлено отсутствующим, буквально есть в области поиска",
    "evidence_outside_requirement": "опора лежит вне блоков требования, к которому относится замечание",
    "anchor_not_supported": "статус confirmed допустим только при anchor_status = supported",
    # check_evidence
    "unknown_block": "блока с таким идентификатором нет в документе",
    "bad_coordinates": "координаты не являются целыми числами",
    "out_of_range": "координаты выходят за границы текста блока",
    "offset_mismatch": "цитата есть в блоке, но не по указанным координатам",
    "quote_mismatch": "текст по координатам не совпадает с цитатой",
    "repeated_in_block": "опора верна по координатам, но та же цитата встречается в блоке несколько раз",
}

_MISSING_PRIORITY = (
    "negation_outside_quote",
    "sign_outside_quote",
    "number_boundary",
    "partial_word",
)
_DIFF_PRIORITY = (
    "number_mismatch",
    "negation_mismatch",
    "currency_mismatch",
    "comparison_mismatch",
    "wording_mismatch",
)

CONFLICT_KINDS = frozenset({"conflict", "contradiction", "inconsistency", "противоречие"})
OMISSION_KINDS = frozenset({"omission", "missing", "gap", "absence", "пропуск"})

# ---------------------------------------------------------------------------
# Нормализация с обратимым отображением
# ---------------------------------------------------------------------------

_IGNORABLE = frozenset("­​⁠﻿")  # мягкий перенос, ZWSP, WJ, BOM
_WRAP_HYPHENS = frozenset("-­‐‑")
_HYPHEN_FOLD = {"‐": "-", "‑": "-"}
_LINE_BREAKS = frozenset("\n\r  \x0b\x0c\x85")
_MD_MARKUP = frozenset("*`")


@dataclass(frozen=True)
class Normalized:
    """Нормализованный текст и карта: символ ``text[i]`` взят из ``orig[starts[i]:ends[i]]``."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    def span(self, a: int, b: int) -> tuple[int, int]:
        """Диапазон ``[a, b)`` нормализованной строки → диапазон оригинала."""
        return self.starts[a], self.ends[b - 1]


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch).startswith("M")


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or _is_mark(ch)


def normalize(text: str, *, ignore: Iterable[str] = ()) -> Normalized:
    """Привести текст к сравнимой форме, сохранив карту до оригинала.

    ``ignore`` — дополнительные символы, которые не участвуют в сравнении
    (для Markdown это маркеры разметки).
    """
    skip = _IGNORABLE | frozenset(ignore)
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        j = i + 1
        while j < n and _is_mark(text[j]):
            j += 1
        if ch in _WRAP_HYPHENS and out and out[-1].isalpha():
            k, saw_break = j, False
            while k < n and (text[k].isspace() or text[k] in skip):
                saw_break = saw_break or text[k] in _LINE_BREAKS
                k += 1
            if k < n and text[k].isalpha() and (k == j or saw_break):
                i = k  # «про-\nверка» ≡ «проверка» ≡ «про-верка»
                continue
        if ch in skip:
            i = j
            continue
        if ch.isspace():
            if out and out[-1] == " ":
                ends[-1] = j
            else:
                out.append(" ")
                starts.append(i)
                ends.append(j)
            i = j
            continue
        piece = unicodedata.normalize("NFC", text[i:j])
        piece = _HYPHEN_FOLD.get(piece, piece)
        for c in piece:
            out.append(c)
            starts.append(i)
            ends.append(j)
        i = j
    return Normalized("".join(out), tuple(starts), tuple(ends))


# ---------------------------------------------------------------------------
# Семантические маркеры: числа, отрицания, сравнения, валюта
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d{1,3}(?: \d{3}(?!\d))+(?:[.,]\d+)?|\d+(?:[.,]\d+)*")
_WORD_RE = re.compile(r"\w+")
_NEGATIONS = frozenset(
    {"не", "ни", "нет", "без", "нельзя", "кроме", "исключая",
     "not", "no", "never", "without", "cannot", "except"}
)
_COMPARATOR_WORDS = frozenset(
    {"более", "менее", "свыше", "больше", "меньше", "выше", "ниже", "до", "от",
     "минимум", "максимум", "превышает", "чем",
     "over", "under", "least", "most", "than", "above", "below", "max", "min"}
)
_COMPARATOR_SIGNS = frozenset("<>≤≥=≠≈")
_SIGNS = frozenset("-−+±")
_UNITS = frozenset(
    {"₸", "тг", "тенге", "kzt", "тиын", "тиынов", "тиына", "$", "€", "₽", "usd", "eur",
     "руб", "%", "мс", "сек", "секунд", "мин", "минут", "минуты", "час", "часа", "часов",
     "дней", "дня", "день", "бит", "bit", "знак", "символов"}
)
_OPENERS = "«\"“„'‘(["


def _numbers(norm: str) -> list[str]:
    return [m.group().replace(" ", "") for m in _NUM_RE.finditer(norm)]


def _words(norm: str) -> list[str]:
    return [w.casefold() for w in _WORD_RE.findall(norm)]


def _units(norm: str) -> set[str]:
    found = {w for w in _words(norm) if w in _UNITS}
    found |= {c for c in norm if c in _UNITS}
    return found


def _preceding_word(norm: str, a: int) -> str:
    if a > 0 and _is_word(norm[a - 1]):
        return ""  # цитата начинается внутри слова: это partial_word, а не отдельное слово
    left = norm[:a].rstrip(" " + _OPENERS)
    m = re.search(r"(\w+)$", left)
    return m.group(1).casefold() if m else ""


def _boundary_issues(norm: str, a: int, b: int) -> tuple[list[str], list[str]]:
    """Проверить границы совпадения ``norm[a:b]``. Возвращает (отказы, предупреждения)."""
    rejects: list[str] = []
    warns: list[str] = []
    for m in _NUM_RE.finditer(norm):
        ts, te = m.span()
        if ts >= b:
            break
        if te > a and not (a <= ts and b >= te):
            rejects.append("number_boundary")
            break
    cuts_word = (a > 0 and _is_word(norm[a - 1]) and _is_word(norm[a])) or (
        b < len(norm) and _is_word(norm[b - 1]) and _is_word(norm[b]))
    if cuts_word and "number_boundary" not in rejects:
        rejects.append("partial_word")
    if _preceding_word(norm, a) in _NEGATIONS:
        rejects.append("negation_outside_quote")
    first = norm[a]
    if first.isdigit():
        if a > 0 and norm[a - 1] in _SIGNS and (a < 2 or not norm[a - 2].isalnum()):
            rejects.append("sign_outside_quote")
        left = norm[:a].rstrip(" ")
        if (left and left[-1] in _COMPARATOR_SIGNS) or _preceding_word(norm, a) in _COMPARATOR_WORDS:
            warns.append("comparison_outside_quote")
    if norm[b - 1].isdigit():
        right = norm[b:].lstrip(" ")
        m = re.match(r"\w+|\S", right)
        if m and m.group().casefold() in _UNITS:
            warns.append("unit_outside_quote")
    return rejects, warns


def _differences(quote: str, place: str) -> list[str]:
    diffs: list[str] = []
    if _numbers(quote) != _numbers(place):
        diffs.append("number_mismatch")
    if {w for w in _words(quote) if w in _NEGATIONS} != {w for w in _words(place) if w in _NEGATIONS}:
        diffs.append("negation_mismatch")
    if _units(quote) != _units(place):
        diffs.append("currency_mismatch")
    q_cmp = {w for w in _words(quote) if w in _COMPARATOR_WORDS} | {c for c in quote if c in _COMPARATOR_SIGNS}
    p_cmp = {w for w in _words(place) if w in _COMPARATOR_WORDS} | {c for c in place if c in _COMPARATOR_SIGNS}
    if q_cmp != p_cmp:
        diffs.append("comparison_mismatch")
    return diffs or ["wording_mismatch"]


# ---------------------------------------------------------------------------
# Доступ к документу (dict или объект с атрибутами)
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class DocumentIndex:
    """Индекс документа: блоки по ID, порядок, нормализованные тексты (лениво)."""

    _cache: list[tuple[Any, DocumentIndex]] = []

    def __init__(self, document: Any) -> None:
        self.document = document
        self.doc_id = _get(document, "id")
        self.format = str(_get(document, "format") or "").casefold()
        self.blocks: dict[str, Any] = {}
        self.order: list[str] = []
        self.duplicates: set[str] = set()
        for block in _get(document, "blocks") or []:
            bid = _get(block, "id")
            if bid in self.blocks:
                self.duplicates.add(bid)
                continue
            self.blocks[bid] = block
            self.order.append(bid)
        self._position = {bid: k for k, bid in enumerate(self.order)}
        self._ignore = _MD_MARKUP if self.format in {"md", "markdown"} else frozenset()
        self._norm: dict[str, Normalized] = {}

    @classmethod
    def of(cls, document: Any) -> DocumentIndex:
        """Индекс для документа; несколько последних индексов переиспользуются."""
        if isinstance(document, DocumentIndex):
            return document
        for doc, idx in cls._cache:
            if doc is document:
                return idx
        idx = cls(document)
        cls._cache = [(document, idx), *cls._cache[:3]]
        return idx

    def text(self, block_id: str) -> str:
        return str(_get(self.blocks[block_id], "text") or "")

    def section(self, block_id: str) -> list[str]:
        return list(_get(self.blocks[block_id], "section") or [])

    def norm(self, block_id: str) -> Normalized:
        if block_id not in self._norm:
            self._norm[block_id] = normalize(self.text(block_id), ignore=self._ignore)
        return self._norm[block_id]

    def normalize(self, text: str) -> str:
        return normalize(text, ignore=self._ignore).text.strip(" ")

    def neighbors(self, block_id: str, radius: int = 1) -> list[str]:
        k = self._position[block_id]
        return self.order[max(0, k - radius): k + radius + 1]

    # -- поиск ---------------------------------------------------------------

    def find(self, nq: str, block_ids: Iterable[str]) -> tuple[list[dict], list[dict]]:
        """Все вхождения нормализованной цитаты. Возвращает (чистые, отклонённые границей)."""
        clean: list[dict] = []
        rejected: list[dict] = []
        for bid in block_ids:
            nb = self.norm(bid)
            text = self.text(bid)
            pos = nb.text.find(nq)
            while pos != -1:
                a, b = pos, pos + len(nq)
                s, e = nb.span(a, b)
                if normalize(text[s:e], ignore=self._ignore).text == nq:
                    rejects, warns = _boundary_issues(nb.text, a, b)
                    occ = {"block_id": bid, "start": s, "end": e, "quote": text[s:e],
                           "_norm": (a, b), "warnings": warns}
                    if rejects:
                        occ["rejects"] = rejects
                        rejected.append(occ)
                    else:
                        clean.append(occ)
                pos = nb.text.find(nq, pos + 1)
        return clean, rejected

    def context_ok(self, occ: dict, before: str, after: str) -> bool:
        norm = self.norm(occ["block_id"]).text
        a, b = occ["_norm"]
        if before:
            left = norm[:a].rstrip(" ")
            if not left.endswith(before):
                return False
            k = len(left) - len(before)
            if k > 0 and _is_word(left[k - 1]) and _is_word(before[0]):
                return False
        if after:
            right = norm[b:].lstrip(" ")
            if not right.startswith(after):
                return False
            k = len(after)
            if k < len(right) and _is_word(right[k]) and _is_word(after[-1]):
                return False
        return True

    def fuzzy(self, nq: str, block_ids: Iterable[str], limit: int = 3,
              min_score: float = 0.6) -> list[dict]:
        """Кандидаты места для исправления. Это НЕ опоры: только подсказка."""
        found: list[dict] = []
        qlen = len(nq)
        sizes = sorted({max(1, qlen - qlen // 5), qlen, qlen + qlen // 5})
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq2(nq)
        for bid in block_ids:
            nb = self.norm(bid)
            t = nb.text
            if not t.strip():
                continue
            word_starts = [0] + [m.end() for m in re.finditer(r"[\s" + re.escape(_OPENERS) + r"]+", t)]
            best: tuple[float, int, int] | None = None
            for s in word_starts:
                if s >= len(t):
                    continue
                for size in sizes:
                    e = min(len(t), s + size)
                    while e < len(t) and _is_word(t[e - 1]) and _is_word(t[e]):
                        e += 1
                    while e > s and (t[e - 1] == " " or (t[e - 1] in ".,;:!?" and not nq.endswith(t[e - 1]))):
                        e -= 1
                    if e <= s:
                        continue
                    matcher.set_seq1(t[s:e])
                    if matcher.real_quick_ratio() < min_score or matcher.quick_ratio() < min_score:
                        continue
                    score = matcher.ratio()
                    if score >= min_score and (best is None or score > best[0]):
                        best = (score, s, e)
            if best:
                score, a, b = best
                s, e = nb.span(a, b)
                found.append({
                    "block_id": bid, "start": s, "end": e,
                    "text": self.text(bid)[s:e], "score": round(score, 3),
                    "differences": _differences(nq, t[a:b]),
                })
        found.sort(key=lambda c: -c["score"])
        return found[:limit]


# ---------------------------------------------------------------------------
# Бюджет восстановления и учёт опор
# ---------------------------------------------------------------------------


@dataclass
class RepairBudget:
    """Общий на прогон бюджет нечётких восстановлений (и повторных запросов модели)."""

    limit: int = 20
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


@dataclass
class EvidenceAudit:
    """Счётчики для ``Report.run.evidence_audit``. Единица учёта — одна опора-подсказка."""

    checked: int = 0
    confirmed: int = 0
    ambiguous: int = 0
    rejected: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    budget: RepairBudget | None = None

    def record(self, result: Mapping[str, Any]) -> None:
        self.checked += 1
        status = result.get("status")
        if status == "matched":
            self.confirmed += 1
            return
        if status == "ambiguous":
            self.ambiguous += 1
        else:
            self.rejected += 1
        reason = result.get("reason") or "unknown"
        self.by_reason[reason] = self.by_reason.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "unit": "hint",
            "note": (
                "Единица учёта — одна опора-подсказка {block_id, quote}, предложенная моделью "
                "или правилом. Проверено = подтверждено + неоднозначно + отклонено. "
                "Подтверждено — найдена буквальная подстрока блока с координатами [start,end); "
                "неоднозначно — несколько равноправных вхождений; отклонено — не найдено или "
                "граница искажает число, слово или отрицание."
            ),
            "checked": self.checked,
            "confirmed": self.confirmed,
            "ambiguous": self.ambiguous,
            "rejected": self.rejected,
            "by_reason": dict(sorted(self.by_reason.items())),
        }
        if self.budget is not None:
            data["repairs_used"] = self.budget.used
            data["repair_budget"] = self.budget.limit
        return data


# ---------------------------------------------------------------------------
# resolve_hint
# ---------------------------------------------------------------------------

_WRAPPERS = (("«", "»"), ("\"", "\""), ("“", "”"), ("„", "“"), ("'", "'"))


def _hint_context(idx: DocumentIndex, hint: Any, nq: str, warnings: list[str]) -> tuple[str, str]:
    before = _get(hint, "before") or _get(hint, "context_before") or _get(hint, "prefix") or ""
    after = _get(hint, "after") or _get(hint, "context_after") or _get(hint, "suffix") or ""
    before, after = idx.normalize(str(before)), idx.normalize(str(after))
    context = _get(hint, "context")
    if context and not (before or after):
        nctx = idx.normalize(str(context))
        k = nctx.find(nq)
        if k != -1 and nctx.find(nq, k + 1) == -1:
            before, after = nctx[:k].strip(" "), nctx[k + len(nq):].strip(" ")
        else:
            warnings.append("context_unusable")
    return before, after


def _public(occ: dict) -> dict:
    return {"block_id": occ["block_id"], "start": occ["start"], "end": occ["end"], "quote": occ["quote"]}


def describe(code: str | None) -> str:
    """Человекочитаемый текст причины."""
    if not code:
        return ""
    return REASONS.get(code, code)


def _result(status: str, *, hint: Any, evidence: dict | None = None, reason: str | None = None,
            warnings: Sequence[str] = (), occurrences: Sequence[dict] = (),
            candidates: Sequence[dict] = ()) -> dict:
    warns = list(dict.fromkeys(warnings))
    message = describe(reason) if reason else "; ".join(describe(w) for w in warns)
    return {
        "status": status,
        "evidence": evidence,
        "reason": reason,
        "message": message,
        "warnings": warns,
        "occurrences": [_public(o) for o in occurrences][:10],
        "candidates": list(candidates),
        "hint": {"block_id": _get(hint, "block_id"), "quote": _get(hint, "quote")},
    }


def resolve_hint(document: Any, hint: Any, *, index: DocumentIndex | None = None,
                 budget: RepairBudget | None = None, audit: EvidenceAudit | None = None,
                 relocate: bool = False) -> dict:
    """Найти точную позицию цитаты из hint.

    Возвращает ``{status: matched|missing|ambiguous, evidence, reason, message,
    warnings, occurrences, candidates, hint}``. ``evidence`` заполнено только при
    ``matched``; ``candidates`` — лишь подсказки места при ``missing``.
    """
    idx = index or DocumentIndex.of(document)
    result = _resolve(idx, hint, budget=budget, relocate=relocate)
    if audit is not None:
        audit.record(result)
    return result


def _resolve(idx: DocumentIndex, hint: Any, *, budget: RepairBudget | None, relocate: bool) -> dict:
    raw_quote = str(_get(hint, "quote") or "")
    block_id = _get(hint, "block_id")
    warnings: list[str] = []
    nq = idx.normalize(raw_quote)
    if not nq:
        return _result("missing", hint=hint, reason="empty_quote")

    if block_id is not None and block_id in idx.duplicates:
        return _result("ambiguous", hint=hint, reason="duplicate_block_id")
    if block_id in idx.blocks:
        scope = [block_id]
    else:
        warnings.append("unknown_block_id" if block_id is not None else "no_block_id")
        scope = list(idx.order)

    clean, rejected = idx.find(nq, scope)
    if not clean and not rejected:
        stripped = raw_quote.strip()
        for left, right in _WRAPPERS:
            if len(stripped) > 2 and stripped.startswith(left) and stripped.endswith(right):
                alt = idx.normalize(stripped[len(left):-len(right)])
                clean, rejected = idx.find(alt, scope)
                if clean or rejected:
                    nq = alt
                    warnings.append("outer_quotes_stripped")
                break
    elsewhere: list[dict] = []
    if not clean and len(scope) == 1:
        elsewhere, _ = idx.find(nq, [bid for bid in idx.order if bid != block_id])
        if elsewhere and relocate:
            clean, elsewhere = elsewhere, []
            warnings.append("block_relocated")

    before, after = _hint_context(idx, hint, nq, warnings)

    if clean:
        if len(clean) == 1:
            occ = clean[0]
            if (before or after) and not idx.context_ok(occ, before, after):
                warnings.append("context_ignored")
            return _matched(hint, occ, raw_quote, warnings)
        if not (before or after):
            return _result("ambiguous", hint=hint, reason="multiple_occurrences",
                           warnings=warnings, occurrences=clean)
        fits = [occ for occ in clean if idx.context_ok(occ, before, after)]
        if len(fits) == 1:
            return _matched(hint, fits[0], raw_quote, warnings)
        reason = "context_not_unique" if fits else "context_mismatch"
        return _result("ambiguous", hint=hint, reason=reason, warnings=warnings,
                       occurrences=fits or clean)

    exact = [{"block_id": o["block_id"], "start": o["start"], "end": o["end"], "text": o["quote"],
              "score": 1.0, "differences": o.get("rejects") or ["found_in_other_block"]}
             for o in rejected + elsewhere][:5]
    if rejected:
        codes = {code for occ in rejected for code in occ["rejects"]}
        reason = next(code for code in _MISSING_PRIORITY if code in codes)
        return _result("missing", hint=hint, reason=reason, warnings=warnings, candidates=exact)
    if elsewhere:
        return _result("missing", hint=hint, reason="found_in_other_block", warnings=warnings,
                       candidates=exact)

    if budget is not None and not budget.take():
        warnings.append("repair_budget_exhausted")
        return _result("missing", hint=hint, reason="not_found", warnings=warnings)
    area = idx.neighbors(block_id) if block_id in idx.blocks else list(idx.order)
    candidates = idx.fuzzy(nq, area)
    if not candidates and block_id in idx.blocks:
        candidates = idx.fuzzy(nq, [bid for bid in idx.order if bid not in area])
    reason = "not_found"
    if candidates:
        diffs = candidates[0]["differences"]
        reason = next(code for code in _DIFF_PRIORITY if code in diffs)
    return _result("missing", hint=hint, reason=reason, warnings=warnings, candidates=candidates)


def _matched(hint: Any, occ: dict, raw_quote: str, warnings: list[str]) -> dict:
    warns = list(warnings) + list(occ.get("warnings", ()))
    if occ["quote"] != raw_quote.strip():
        warns.append("normalized_match")
    return _result("matched", hint=hint, evidence=_public(occ), warnings=warns)


# ---------------------------------------------------------------------------
# resolve_candidate
# ---------------------------------------------------------------------------


def _overlap(x: Mapping[str, Any], y: Mapping[str, Any]) -> bool:
    return x["block_id"] == y["block_id"] and x["start"] < y["end"] and y["start"] < x["end"]


def _same_anchor(idx: DocumentIndex, x: Mapping[str, Any], y: Mapping[str, Any]) -> bool:
    return _overlap(x, y) or idx.normalize(x["quote"]).casefold() == idx.normalize(y["quote"]).casefold()


def _reason(code: str, hint: int | None = None, detail: str | None = None) -> dict:
    item: dict[str, Any] = {"code": code, "message": describe(code)}
    if hint is not None:
        item["hint"] = hint
    if detail:
        item["message"] = f"{item['message']}: {detail}"
    return item


def _side(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if text in {"a", "side_a", "left", "1"}:
        return "a"
    if text in {"b", "side_b", "right", "2"}:
        return "b"
    return None


def _witness_problems(witness: Any) -> list[str]:
    if not witness:
        return ["conflict_witness_missing"]
    parts = [str(_get(witness, key) or "").strip() for key in ("input", "outcome_a", "outcome_b")]
    if not all(parts):
        return ["conflict_witness_missing"]
    if parts[1].casefold() == parts[2].casefold():
        return ["conflict_outcomes_equal"]
    return []


def resolve_candidate(document: Any, candidate: Any, *, index: DocumentIndex | None = None,
                      budget: RepairBudget | None = None, audit: EvidenceAudit | None = None,
                      requirements: Iterable[Any] | None = None) -> dict:
    """Проверить опоры кандидата-замечания.

    Возвращает ``{anchor_status: supported|incomplete, evidence, warnings, reasons,
    hint_results}`` и, по виду замечания, ``witness`` (конфликт) или
    ``inspected_block_ids`` (пропуск). ``supported`` означает: все опоры
    подтверждены и выполнен минимум для вида замечания.
    """
    idx = index or DocumentIndex.of(document)
    kind = str(_get(candidate, "kind") or "").strip().casefold()
    hints = list(_get(candidate, "hints") or [])
    witness = _get(candidate, "witness")
    side_of: list[str | None] = [_side(_get(h, "role")) for h in hints]
    if kind in CONFLICT_KINDS and witness:
        for key, side in (("hint_a", "a"), ("hint_b", "b")):
            extra = _get(witness, key)
            if extra:
                hints.append(extra)
                side_of.append(side)

    results = [resolve_hint(idx.document, h, index=idx, budget=budget, audit=audit) for h in hints]
    reasons: list[dict] = []
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for i, res in enumerate(results):
        if res["status"] == "matched":
            ev = res["evidence"]
            key = (ev["block_id"], ev["start"], ev["end"])
            if key not in seen:
                seen.add(key)
                evidence.append(ev)
        else:
            reasons.append(_reason(res["reason"] or "hint_failed", hint=i,
                                   detail=f"«{_get(hints[i], 'quote')}» → {res['status']}"))

    out: dict[str, Any] = {"witness": None}
    if kind in CONFLICT_KINDS:
        if len(hints) == 2 and not any(side_of):
            side_of = ["a", "b"]
        if not ("a" in side_of and "b" in side_of):
            reasons.append(_reason("conflict_sides_unspecified"))
        sides: dict[str, dict | None] = {}
        for side in ("a", "b"):
            sides[side] = next((r["evidence"] for r, s in zip(results, side_of, strict=True)
                                if s == side and r["status"] == "matched"), None)
        if "a" in side_of and "b" in side_of and not (sides["a"] and sides["b"]):
            reasons.append(_reason("conflict_side_missing"))
        if sides["a"] and sides["b"] and _same_anchor(idx, sides["a"], sides["b"]):
            reasons.append(_reason("conflict_same_anchor"))
        problems = _witness_problems(witness)
        reasons.extend(_reason(code) for code in problems)
        if sides["a"] and sides["b"] and not problems:
            out["witness"] = {
                "input": str(_get(witness, "input")),
                "outcome_a": str(_get(witness, "outcome_a")),
                "outcome_b": str(_get(witness, "outcome_b")),
                "evidence_a": sides["a"],
                "evidence_b": sides["b"],
            }
    elif kind in OMISSION_KINDS:
        inspected = list(_get(candidate, "inspected_block_ids") or [])
        if not inspected:
            reasons.append(_reason("omission_scope_missing"))
        unknown = [bid for bid in inspected if bid not in idx.blocks]
        if unknown:
            reasons.append(_reason("unknown_inspected_block", detail=", ".join(map(str, unknown))))
        known = [bid for bid in inspected if bid in idx.blocks]
        for term in _get(candidate, "absent_terms") or []:
            nterm = idx.normalize(str(term))
            hits, _ = idx.find(nterm, known) if nterm else ([], [])
            if hits:
                reasons.append(_reason("absent_term_present",
                                       detail=f"«{term}» в блоке {hits[0]['block_id']}"))
        out["inspected_block_ids"] = known
    elif not hints:
        reasons.append(_reason("no_hints"))

    warnings_codes: list[str] = []
    for res in results:
        if res["status"] == "matched":
            warnings_codes.extend(res["warnings"])
    if requirements is not None and _get(candidate, "scope") == "requirement" and evidence:
        req_blocks = {bid for req in requirements
                      if _get(req, "id") in set(_get(candidate, "req_ids") or [])
                      for bid in (_get(req, "block_ids") or [])}
        if req_blocks and not any(ev["block_id"] in req_blocks for ev in evidence):
            warnings_codes.append("evidence_outside_requirement")

    status = "incomplete" if reasons else "supported"
    warnings = [f"{r['code']}: {r['message']}" for r in reasons]
    warnings += [f"{code}: {describe(code)}" for code in dict.fromkeys(warnings_codes)]
    out.update({
        "anchor_status": status,
        "evidence": evidence,
        "warnings": warnings,
        "reasons": reasons,
        "hint_results": results,
    })
    return out


# ---------------------------------------------------------------------------
# Проверка готовой опоры и готового замечания (без hint) — для verify и экспортов
# ---------------------------------------------------------------------------


def check_evidence(document: Any, evidence: Mapping[str, Any], *,
                   index: DocumentIndex | None = None) -> dict:
    """Перепроверить готовую опору. ``status``: confirmed | ambiguous | rejected.

    ``ambiguous`` — опора верна по координатам, но та же цитата встречается в
    блоке несколько раз (без координат читатель её не различит).
    """
    idx = index or DocumentIndex.of(document)
    bid = evidence.get("block_id")
    start, end, quote = evidence.get("start"), evidence.get("end"), evidence.get("quote")
    if bid in idx.duplicates:
        return {"status": "rejected", "reason": "duplicate_block_id"}
    if bid not in idx.blocks:
        return {"status": "rejected", "reason": "unknown_block"}
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end)):
        return {"status": "rejected", "reason": "bad_coordinates"}
    if not isinstance(quote, str) or not quote:
        return {"status": "rejected", "reason": "empty_quote"}
    text = idx.text(bid)
    if not 0 <= start < end <= len(text):
        return {"status": "rejected", "reason": "out_of_range"}
    if text[start:end] != quote:
        k = text.find(quote)
        if k != -1:
            return {"status": "rejected", "reason": "offset_mismatch",
                    "expected": {"start": k, "end": k + len(quote)}}
        return {"status": "rejected", "reason": "quote_mismatch", "found": text[start:end]}
    nb = idx.norm(bid)
    a = bisect.bisect_left(nb.starts, start)
    b = bisect.bisect_left(nb.starts, end)
    if a < b:
        rejects, warns = _boundary_issues(nb.text, a, b)
        if rejects:
            reason = next(code for code in _MISSING_PRIORITY if code in rejects)
            return {"status": "rejected", "reason": reason}
    else:
        warns = []
    if text.count(quote) > 1:
        return {"status": "ambiguous", "reason": "repeated_in_block", "warnings": warns}
    return {"status": "confirmed", "reason": None, "warnings": warns}


def check_finding_support(document: Any, finding: Mapping[str, Any], *,
                          index: DocumentIndex | None = None) -> list[dict]:
    """Причины, по которым замечание со статусом confirmed не имеет достаточных опор.

    Пустой список — опор достаточно. Сами координаты проверяет :func:`check_evidence`.
    """
    idx = index or DocumentIndex.of(document)
    kind = str(finding.get("kind") or "").strip().casefold()
    evidence = [ev for ev in finding.get("evidence") or [] if isinstance(ev, Mapping)]
    problems: list[dict] = []
    if "anchor_status" in finding and finding["anchor_status"] != "supported":
        problems.append(_reason("anchor_not_supported", detail=repr(finding["anchor_status"])))
    if kind in CONFLICT_KINDS:
        witness = finding.get("witness") or {}
        problems.extend(_reason(code) for code in _witness_problems(witness))
        ev_a, ev_b = witness.get("evidence_a"), witness.get("evidence_b")
        if not (isinstance(ev_a, Mapping) and isinstance(ev_b, Mapping)):
            problems.append(_reason("conflict_side_missing"))
        else:
            if _same_anchor(idx, ev_a, ev_b):
                problems.append(_reason("conflict_same_anchor"))
            keys = {(e.get("block_id"), e.get("start"), e.get("end")) for e in evidence}
            for ev in (ev_a, ev_b):
                if (ev.get("block_id"), ev.get("start"), ev.get("end")) not in keys:
                    problems.append(_reason("witness_evidence_not_in_finding"))
                    break
    elif kind in OMISSION_KINDS:
        inspected = list(finding.get("inspected_block_ids") or [])
        if not inspected:
            problems.append(_reason("omission_scope_missing"))
        unknown = [bid for bid in inspected if bid not in idx.blocks]
        if unknown:
            problems.append(_reason("unknown_inspected_block", detail=", ".join(map(str, unknown))))
    elif not evidence:
        problems.append(_reason("no_hints"))
    return problems


# ---------------------------------------------------------------------------
# Место в документе по reader-координатам
# ---------------------------------------------------------------------------


def _map_position(entries: list[tuple[int, int, int]], text: str, pos: int) -> tuple[int, int]:
    """(строка, колонка) исходника для позиции ``pos`` в ``block.text`` по ``loc.map``."""
    k = max(0, bisect.bisect_right([e[0] for e in entries], pos) - 1)
    text_start, line, col = entries[k]
    if pos < text_start:
        return line, col
    newline = text.rfind("\n", text_start, pos)
    if newline == -1:
        return line, col + (pos - text_start)
    return line + text.count("\n", text_start, pos), pos - newline - 1


def table_cell(block: Any, start: int, end: int) -> dict | None:
    """Ячейка таблицы, целиком содержащая ``[start, end)`` текста блока, по reader-координатам.

    Понимает обе формы стыка: №02 PDF — ``loc.table = {id, row, header, cells: [{col, start, end}]}``,
    №01 Markdown — ``loc.cells = [{index, column, start, end}]``, ``loc.row``, ``loc.table.index``.
    Возвращает ``{table, row, cell, header, start, end, text}`` (``cell`` с нуля) или ``None``.
    """
    loc = _get(block, "loc") or {}
    table = loc.get("table") if isinstance(loc.get("table"), Mapping) else {}
    cells = [c for c in table.get("cells") or loc.get("cells") or [] if isinstance(c, Mapping)]
    headers = table.get("header") or table.get("columns") or loc.get("columns") or []
    text = str(_get(block, "text") or "")
    for k, cell in enumerate(cells):
        cs, ce = cell.get("start"), cell.get("end")
        if not (isinstance(cs, int) and isinstance(ce, int) and cs <= start and end <= ce):
            continue
        col = cell.get("col", cell.get("index", k))
        header = cell.get("column")
        if header is None and isinstance(col, int) and 0 <= col < len(headers):
            header = headers[col]
        return {"table": table.get("id", table.get("index")), "row": table.get("row", loc.get("row")),
                "cell": col, "header": header, "start": cs, "end": ce, "text": text[cs:ce]}
    return None


def locate(document: Any, evidence: Mapping[str, Any], *, index: DocumentIndex | None = None) -> dict:
    """Строка/страница/путь для опоры, вычисленные из ``block.loc`` и смещений.

    Ключи ``loc`` по контракту v1 (их выдаёт reader):

    * Markdown/TXT: ``line_start``/``line_end`` (с 1) и необязательный
      ``map = [[text_start, line, col], ...]`` — с позиции ``text_start`` в
      ``block.text`` символы идут подряд с (``line``, ``col``) исходника, ``col``
      с нуля. С ``map`` возвращаются и ``col``/``col_end``; без него строки
      считаются по ``\\n`` в ``block.text``.
    * PDF: ``page`` (с 1) и ``fragments = [{start, end, rect}]``; возвращаются
      ``rects`` фрагментов, пересекающих опору (для подсветки).
    * DOCX: ``part`` и ``path`` к абзацу или ячейке.

    Расширения: ``line_starts`` (смещения начала строк в ``block.text``) и
    ``page_breaks`` (смещения, с которых начинается следующая страница).
    """
    idx = index or DocumentIndex.of(document)
    bid = evidence["block_id"]
    block = idx.blocks[bid]
    loc = dict(_get(block, "loc") or {})
    text = idx.text(bid)
    start = int(evidence["start"])
    end = int(evidence["end"])
    last = max(start, end - 1)
    out: dict[str, Any] = {"block_id": bid, "section": idx.section(bid)}
    entries = sorted((int(e[0]), int(e[1]), int(e[2])) for e in loc.get("map") or []
                     if isinstance(e, Sequence) and len(e) >= 3)
    first_line = loc.get("line_start", loc.get("line"))
    if entries:
        (out["line"], out["col"]), (out["line_end"], last_col) = (
            _map_position(entries, text, start), _map_position(entries, text, last))
        out["col_end"] = last_col + 1
    elif first_line is not None:
        starts = loc.get("line_starts")
        if starts:
            out["line"] = first_line + bisect.bisect_right(starts, start) - 1
            out["line_end"] = first_line + bisect.bisect_right(starts, last) - 1
        else:
            out["line"] = first_line + text.count("\n", 0, start)
            out["line_end"] = first_line + text.count("\n", 0, last)
    first_page = loc.get("page_start", loc.get("page"))
    if first_page is not None:
        breaks = loc.get("page_breaks") or []
        out["page"] = first_page + bisect.bisect_right(breaks, start)
        out["page_end"] = first_page + bisect.bisect_right(breaks, last)
    fragments = [f for f in loc.get("fragments") or [] if isinstance(f, Mapping)]
    if fragments:
        out["rects"] = [list(f["rect"]) for f in fragments
                        if "rect" in f and f.get("start", 0) < end and start < f.get("end", 0)]
    for key in ("part", "path"):
        if loc.get(key):
            out[key] = loc[key]
    cell = table_cell(block, start, end)
    if cell:
        out.update({key: cell[key] for key in ("table", "row", "cell", "header")})
    parts = []
    if "page" in out:
        parts.append(f"стр. {out['page']}" if out["page"] == out["page_end"]
                     else f"стр. {out['page']}–{out['page_end']}")
    if "line" in out:
        parts.append(f"строка {out['line']}" if out["line"] == out["line_end"]
                     else f"строки {out['line']}–{out['line_end']}")
    if "path" in out:
        parts.append(f"абзац {out['path']}")
    if "cell" in out:
        column = f"столбец {out['cell'] + 1}" if isinstance(out["cell"], int) else "столбец ?"
        parts.append(f"таблица {out['table']}, строка {out['row']}, {column}"
                     + (f" «{out['header']}»" if out["header"] else ""))
    if out["section"]:
        parts.append(f"раздел «{out['section'][-1]}»")
    out["label"] = ", ".join(parts) or f"блок {bid}"
    return out
