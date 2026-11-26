"""Нормализация текста и правило «цитата находки покрывает опору эталона».

Выбор метода сделан на сравнительном примере (см. README.md, раздел «Почему
непрерывный отрезок токенов»): совпадение ищется как самый длинный непрерывный
общий отрезок токенов. На краю отрезка не должно быть расхождения в числе,
отрицании или единице измерения, иначе «1 000» совпадёт с «10 000», а «в тенге»
с «в тиынах».
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

COVER_THRESHOLD = 0.6        # доля токенов опоры внутри общего отрезка
FRAGMENT_MIN_TOKENS = 4      # короткая цитата-фрагмент опоры засчитывается с этой длины
FRAGMENT_MIN_TOKENS_SPECIFIC = 3  # или с 3 токенов, если в фрагменте есть число или единица (ячейка таблицы)
FRAGMENT_MIN_SHARE = 0.3     # и при этой доле опоры
PARTIAL_SHARE = 0.3          # ниже порога, но выше этого — «частичное» (на разбор)

_DASHES = re.compile(r"[‐‑‒–—−]")
_DIGIT_GROUP = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")
_STRIP = re.compile(r"[^\w\s.,%+\-₸/:]")
_TOKEN = re.compile(r"[+\-]?\d+(?:[.,]\d+)?|\w+|₸|%")
_NEGATIONS = frozenset({"не", "нет", "ни", "без", "кроме", "not", "no", "without"})
_UNIT = re.compile(
    r"^(?:₸|%|тенге|тг|kzt|тиын\w*|мс|ms|сек\w*|с|s|мин\w*|min|час\w*|ч|h|сут\w*|дн\w*|д|"
    r"недел\w*|мес\w*|год\w*|лет|utc|gmt|бит\w*|bit|байт\w*|кб|мб|гб|шт|раз\w*)$"
)


def norm(text: str) -> str:
    """Каноническая форма для сравнения цитат из MD, PDF и DOCX."""
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace("­", "").replace("﻿", "")
    s = s.casefold().replace("ё", "е")
    s = _DASHES.sub("-", s)
    s = re.sub(r"\s+", " ", s)
    s = _DIGIT_GROUP.sub("", s)
    s = _STRIP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(norm(text))


def is_critical(token: str) -> bool:
    """Токены, расхождение в которых меняет смысл: числа, отрицания, единицы."""
    return (
        token in _NEGATIONS
        or token.lstrip("+-")[:1].isdigit()
        or bool(_UNIT.match(token))
    )


def _longest_run(a: list[str], b: list[str]) -> tuple[int, int, int]:
    """Длина и начала самого длинного непрерывного общего отрезка (детерминированно: первый максимум)."""
    best = (0, 0, 0)
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best[0]:
                    best = (cur[j], i - cur[j], j - cur[j])
        prev = cur
    return best


@dataclass(frozen=True)
class Coverage:
    covered: bool
    share: float          # доля токенов опоры в общем отрезке
    partial: bool         # ниже порога покрытия, но заметное пересечение
    reason: str


def count_occurrences(hay: list[str], needle: list[str]) -> int:
    n = len(needle)
    if not n or n > len(hay):
        return 0
    first = needle[0]
    return sum(1 for i in range(len(hay) - n + 1) if hay[i] == first and hay[i:i + n] == needle)


def coverage(gold_quote: str, pred_quote: str, doc_tokens: list[str] | None = None) -> Coverage:
    """Покрывает ли цитата находки опору эталона.

    doc_tokens — токены исходного документа кейса (если известен). Тогда короткий фрагмент
    опоры (от 3 токенов), который встречается в документе ровно один раз, тоже засчитывается:
    продукт по контракту цитирует дословный фрагмент блока, и уникальный фрагмент однозначно
    указывает на место опоры.
    """
    gold, pred = tokens(gold_quote), tokens(pred_quote)
    if not gold or not pred:
        return Coverage(False, 0.0, False, "empty_quote")
    run, gi, pj = _longest_run(gold, pred)
    if run == 0:
        return Coverage(False, 0.0, False, "no_overlap")
    share = run / len(gold)
    for g_idx, p_idx in ((gi - 1, pj - 1), (gi + run, pj + run)):
        if 0 <= g_idx < len(gold) and 0 <= p_idx < len(pred):
            if is_critical(gold[g_idx]) or is_critical(pred[p_idx]):
                return Coverage(False, share, share >= PARTIAL_SHARE, "critical_token_differs")
    if share >= COVER_THRESHOLD:
        return Coverage(True, share, False, "covers")
    if run == len(pred) and share >= FRAGMENT_MIN_SHARE:
        specific = any(t.lstrip("+-")[:1].isdigit() or _UNIT.match(t) for t in pred)
        if run >= FRAGMENT_MIN_TOKENS or (specific and run >= FRAGMENT_MIN_TOKENS_SPECIFIC):
            return Coverage(True, share, False, "fragment_of_anchor")
    if (doc_tokens is not None and run == len(pred) and run >= FRAGMENT_MIN_TOKENS_SPECIFIC
            and count_occurrences(doc_tokens, pred) == 1):
        return Coverage(True, share, False, "unique_fragment_in_document")
    return Coverage(False, share, share >= PARTIAL_SHARE, "below_threshold")


def tokens_present(quote: str, haystack_tokens: set[str]) -> bool:
    """Все токены цитаты присутствуют в извлечённом тексте (проверка рендера)."""
    toks = tokens(quote)
    return bool(toks) and all(t in haystack_tokens for t in toks)
