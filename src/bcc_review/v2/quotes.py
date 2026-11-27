"""Сверка цитат с документом (владелец №03, CONTRACT.md, раздел 7).

Модель пишет цитату и номер строки; код ищет цитату в DocView и сам ставит строку, страницу и раздел.
Так в отчёт попадает только текст, который действительно есть в документе, на своём месте.

``verify_quote(view, quote, line_hint=None, near_lines=())`` → ``Match | None``::

    {"line_start": 38, "line_end": 38, "page": None, "section": "…", "verified": "exact|normalized|fuzzy",
     "text": "дословный текст документа"}

Порядок поиска:

1. нормализация обеих сторон: NFKC; кавычки «»“”„"' → "; тире —–‑ → -; неразрывные и тонкие пробелы →
   пробел; пробелы схлопываются; ``**``, обратные кавычки, ведущие ``* ``, ``#``, ``|`` снимаются;
   ё → е; пробел внутри числа («1 000») не учитывается; сравнение без регистра;
2. вхождение в строках ``line_hint`` ±2, иначе во всём документе — ближайшее к ``line_hint`` / ``near_lines``;
3. цитата через соседние строки (склейка до 3 непустых строк); затем то же без учёта пробелов — слово,
   разорванное переносом в узкой ячейке таблицы PDF («integ er»);
4. цитата с многоточием внутри — части ищутся по порядку в пределах 3 строк (``normalized``), ``text`` — сплошной
   отрезок документа от первой части до последней;
5. нечёткое совпадение ≥ 0,92 (difflib) только в пределах ±5 строк от подсказки → ``fuzzy``;
6. иначе ``None``.

``verify_candidates(view, candidates, requirements)`` — пакетная сверка кандидатов: проставляет
``evidence[i].verified`` и точные ``line_start/line_end/page/section``, кандидатов без единой найденной
цитаты переносит в ``rejected`` с причиной «цитата не найдена».
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

FUZZY_MIN = 0.92
FUZZY_RADIUS = 5
HINT_RADIUS = 2
MAX_GLUE = 3
MIN_QUOTE = 3          # короче (после нормализации) — не цитата
MIN_FUZZY_QUOTE = 12   # нечёткий поиск только для достаточно длинных цитат
SKELETON_MIN = 10      # «те же слова, другие знаки между ними» — для цитат не короче 10 букв и цифр
REASON_MISSING = "цитата не найдена"

_QUOTES = set("«»“”„‟\"'‘’‚‛`´ʹʺ〝〞＂")
_DASHES = set("—–‑‐‒―−⁃﹘﹣－")  # ‐ (U+2010): в него NFKC превращает неразрывный дефис Word (U+2011)
_ZERO = set("\u200b\u200c\u200d\u2060\ufeff\u00ad")
_ELLIPSIS = re.compile(r"\.{3,}")
_LEAD = re.compile(r"^(?:\s|[#*•|>]|-(?=\s))+")
_LEAD_NUM = re.compile(r"^\d{1,3}[.)]\s+")
_EDGE = " \"'.,;!?|*"


# --------------------------------------------------------------------------- нормализация с картой позиций
def normalize(s: str) -> str:
    """Нормализованная строка для сравнения (без регистра)."""
    return _norm_map(s)[0]


def _norm_map(s: str) -> tuple[str, list[int]]:
    """Нормализовать строку и вернуть карту: позиция нормализованного символа → позиция в исходной строке."""
    chars: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        # снять **, __ и обратные кавычки (разметка Markdown)
        if c == "`" or (c in "*_" and i + 1 < n and s[i + 1] == c):
            i += 2 if c != "`" else 1
            continue
        for ch in unicodedata.normalize("NFKC", c):
            if ch in _ZERO:
                continue
            if ch in _QUOTES:
                ch = '"'
            elif ch in _DASHES:
                ch = "-"
            elif ch.isspace():
                ch = " "
            for low in ch.lower():
                if low == "ё":
                    low = "е"
                chars.append(low)
                idx.append(i)
        i += 1
    # схлопнуть пробелы; убрать пробел внутри числа «1 000» → «1000»
    out_c: list[str] = []
    out_i: list[int] = []
    m = len(chars)
    for k, ch in enumerate(chars):
        if ch == " ":
            if not out_c or out_c[-1] == " ":
                continue
            if (out_c[-1].isdigit() and k + 3 < m + 1 and "".join(chars[k + 1:k + 4]).isdigit()
                    and (k + 4 >= m or not chars[k + 4].isdigit())):
                continue
        out_c.append(ch)
        out_i.append(idx[k])
    while out_c and out_c[-1] == " ":
        out_c.pop()
        out_i.pop()
    return "".join(out_c), out_i


_LINE_PREFIX = re.compile(r"(?:(?<=\s)|^)L\d{1,5}\s?\|\s?|\[с\.\s?\d{1,4}\]\s?", re.IGNORECASE)


def _clean_quote(q: str) -> str:
    """Нормализованная цитата без обрамления: ведущие маркеры, кавычки и точки по краям не нужны для поиска.
    Префиксы нумерованного вида «L038| » и «[с.2] », скопированные моделью вместе с текстом, снимаются."""
    t = normalize(_LINE_PREFIX.sub(" ", q))
    t = _LEAD.sub("", t)
    return t.strip(_EDGE + "…").strip()


# --------------------------------------------------------------------------- индекс документа
class _Index:
    """Нормализованный текст всех непустых строк через пробел и границы строк в нём."""

    def __init__(self, view: dict):
        self.view = view
        self.lines = view.get("lines") or []
        parts: list[str] = []
        self.starts: list[int] = []   # начало строки в self.full
        self.ends: list[int] = []
        self.nos: list[int] = []      # номер строки view
        self.maps: list[list[int]] = []
        pos = 0
        for ln in self.lines:
            norm, mp = _norm_map(ln.get("text") or "")
            if not norm.strip():
                continue
            if parts:
                parts.append(" ")
                pos += 1
            self.starts.append(pos)
            parts.append(norm)
            pos += len(norm)
            self.ends.append(pos)
            self.nos.append(ln["n"])
            self.maps.append(mp)
        self.full = "".join(parts)
        self.by_no = {no: k for k, no in enumerate(self.nos)}

    def compact(self) -> tuple[str, list[int]]:
        """Текст без пробелов и карта позиций в self.full — для слов, разорванных в узкой ячейке PDF («integ er»)."""
        if not hasattr(self, "_compact"):
            keep = [i for i, ch in enumerate(self.full) if ch != " "]
            self._compact = ("".join(self.full[i] for i in keep), keep)
        return self._compact

    def slot(self, pos: int) -> int:
        """Индекс непустой строки, которой принадлежит позиция в self.full (разделитель — к предыдущей)."""
        return max(0, bisect.bisect_right(self.starts, pos) - 1)

    def occurrences(self, needle: str) -> list[tuple[int, int]]:
        out = []
        start = 0
        while True:
            a = self.full.find(needle, start)
            if a < 0:
                return out
            out.append((a, a + len(needle)))
            start = a + 1

    def span_lines(self, a: int, b: int) -> tuple[int, int]:
        return self.slot(a), self.slot(max(a, b - 1))

    def original(self, a: int, b: int) -> str:
        """Исходный текст документа, соответствующий отрезку [a, b) нормализованного текста."""
        s1, s2 = self.span_lines(a, b)
        pieces = []
        for k in range(s1, s2 + 1):
            text = self.lines_text(k)
            mp = self.maps[k]
            lo = max(a, self.starts[k]) - self.starts[k]
            hi = min(b, self.ends[k]) - self.starts[k]
            if hi <= lo or not mp:
                continue
            o1 = mp[lo]
            o2 = mp[hi - 1] + 1
            # дотянуть до конца составного символа (например, «**» после текста не нужен — карта его пропускает)
            pieces.append(text[o1:o2].strip())
        return " ".join(p for p in pieces if p)

    def lines_text(self, k: int) -> str:
        return self.line_of_slot(k).get("text") or ""

    def line_of_slot(self, k: int) -> dict:
        no = self.nos[k]
        if 1 <= no <= len(self.lines) and self.lines[no - 1]["n"] == no:
            return self.lines[no - 1]
        return next(ln for ln in self.lines if ln["n"] == no)


_CACHE: dict[int, tuple[Any, _Index]] = {}


def _index(view: dict) -> _Index:
    key = id(view)
    hit = _CACHE.get(key)
    lines = view.get("lines")
    if hit and hit[0] is lines and hit[1].view is view and len(hit[1].lines) == len(lines or []):
        return hit[1]
    idx = _Index(view)
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[key] = (lines, idx)
    return idx


# --------------------------------------------------------------------------- выбор вхождения
def _anchors(line_hint: Any, near_lines: Iterable[Any]) -> tuple[int | None, list[int]]:
    hint = _as_int(line_hint)
    near: list[int] = []
    for x in near_lines or ():
        if isinstance(x, (list, tuple)) and x:
            a, b = _as_int(x[0]), _as_int(x[-1])
            if a is not None and b is not None:
                near.extend(range(min(a, b), max(a, b) + 1))
        else:
            v = _as_int(x)
            if v is not None:
                near.append(v)
    return hint, near


def _as_int(x: Any) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if x > 0 else None
    if isinstance(x, float) and x > 0:
        return int(x)
    if isinstance(x, str):
        m = re.search(r"\d+", x)
        return int(m.group()) if m else None
    return None


def _dist(ls: int, le: int, points: list[int]) -> int:
    best = 10 ** 9
    for p in points:
        d = 0 if ls <= p <= le else min(abs(ls - p), abs(le - p))
        if d < best:
            best = d
    return best


def _pick(idx: _Index, spans: list[tuple[int, int]], hint: int | None, near: list[int]):
    """Выбрать вхождение: сначала в окне подсказки ±2, потом ближайшее; одна строка лучше склейки."""
    best = None
    points = ([hint] if hint else []) + near
    for a, b in spans:
        s1, s2 = idx.span_lines(a, b)
        if s2 - s1 + 1 > MAX_GLUE:
            continue
        ls, le = idx.nos[s1], idx.nos[s2]
        multi = le > ls
        in_win = hint is not None and ls <= hint + HINT_RADIUS and le >= hint - HINT_RADIUS
        tier = (0 if in_win else 2) + (1 if multi else 0)
        d = _dist(ls, le, points) if points else 0
        dh = _dist(ls, le, [hint]) if hint else 0
        # вхождение по границам слов лучше куска слова («Prod» не должен найтись в «Product»)
        cut = int((a > 0 and idx.full[a - 1].isalnum() and idx.full[a].isalnum())
                  or (b < len(idx.full) and idx.full[b].isalnum() and idx.full[b - 1].isalnum()))
        key = (tier, cut, d, dh, ls)
        if best is None or key < best[0]:
            best = (key, a, b, ls, le)
    return best


def _match(idx: _Index, a: int, b: int, ls: int, le: int, verified: str, text: str | None = None) -> dict:
    first = idx.line_of_slot(idx.by_no[ls])
    return {"line_start": ls, "line_end": le, "page": first.get("page"), "section": first.get("section", ""),
            "verified": verified, "text": text if text is not None else idx.original(a, b)}


# --------------------------------------------------------------------------- основная функция
def verify_quote(view: dict, quote: Any, line_hint: Any = None, near_lines: Iterable[Any] = ()) -> dict | None:
    """Найти цитату в документе. Возвращает Match или None (см. описание модуля)."""
    if not isinstance(quote, str):
        return None
    raw = _LINE_PREFIX.sub(" ", quote).strip() if _LINE_PREFIX.search(quote) else quote.strip()
    raw = re.sub(r"\s{2,}", " ", raw) if raw != quote.strip() else raw
    needle = _clean_quote(raw)
    if len(needle) < MIN_QUOTE:
        return None
    idx = _index(view)
    if not idx.full:
        return None
    hint, near = _anchors(line_hint, near_lines)

    # 1–3: точное (после нормализации) вхождение, в том числе через соседние строки;
    # если не нашлось — та же цитата без ведущего номера пункта («5. …»: в DOCX нумерация не в тексте)
    best = _pick(idx, idx.occurrences(needle), hint, near)
    if not best and _LEAD_NUM.match(needle) and len(_LEAD_NUM.sub("", needle)) >= MIN_QUOTE:
        needle = _LEAD_NUM.sub("", needle)
        best = _pick(idx, idx.occurrences(needle), hint, near)
    if best and hint is not None and best[0][0] >= 2:
        # дословно — только далеко от строки модели; если у её строки те же слова с другим разделителем ячеек
        # («Swagger: —» при строке таблицы «Swagger | —»), модель цитировала именно это место
        m = _same_words(idx, needle, hint, [])
        if m and m["line_start"] <= hint + HINT_RADIUS and m["line_end"] >= hint - HINT_RADIUS:
            return m
    if best:
        _, a, b, ls, le = best
        text = idx.original(a, b)
        joined = " ".join(idx.line_of_slot(k).get("text", "") for k in range(idx.by_no[ls], idx.by_no[le] + 1))
        verified = "exact" if raw and (raw in joined or raw.strip("«»\"' ") in joined) else "normalized"
        return _match(idx, a, b, ls, le, verified, text)

    # 3а: без учёта пробелов — слово, разорванное переносом в узкой ячейке таблицы PDF («integ er» = «integer»)
    squeezed = needle.replace(" ", "")
    if len(squeezed) >= 6:
        ctext, cmap = idx.compact()
        spans = []
        start = 0
        while True:
            a = ctext.find(squeezed, start)
            if a < 0:
                break
            spans.append((cmap[a], cmap[a + len(squeezed) - 1] + 1))
            start = a + 1
        best = _pick(idx, spans, hint, near)
        if best:
            _, a, b, ls, le = best
            return _match(idx, a, b, ls, le, "normalized")

    # 3б: те же слова документа подряд, другие знаки между ними — разделитель ячеек таблицы « | » модель пишет как
    # «:» или «—» («REST type: GET», «Swagger: —»); слова не меняются, поэтому это та же цитата, а в отчёт идёт
    # текст документа
    m = _same_words(idx, needle, hint, near)
    if m:
        return m

    # 4: многоточие внутри цитаты — части по порядку в пределах 3 строк; «[…]» и «(…)» — тоже пропуск
    parts = [p.strip(_EDGE + "…").strip("[](){} ").strip(_EDGE) for p in _ELLIPSIS.split(needle)]
    parts = [p for p in parts if len(p) >= MIN_QUOTE]
    if len(parts) >= 2:
        m = _match_parts(idx, parts, hint, near)
        if m:
            return m

    # 5: нечёткое совпадение только рядом с подсказкой
    points = ([hint] if hint else []) + near
    if points and len(needle) >= MIN_FUZZY_QUOTE:
        m = _fuzzy(idx, needle, hint, points)
        if m:
            return m
    # 6: модель экранировала разметку («limit\_kzt», «\*\*Ф-2.\*\*»), записала HTML-сущности («&laquo;») или
    # «тенге» вместо «₸»
    plain = _unescape(quote)
    if plain != quote:
        m = verify_quote(view, plain, line_hint, near_lines)
        if m and m["verified"] == "exact":
            m["verified"] = "normalized"  # модель писала не дословно — в документе другой текст
        return m
    return None


_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~\"'])")


_TENGE_WORD = re.compile(r"(\d)\s*(?:тенге|тг\.?)(?![а-яё])", re.IGNORECASE)


def _unescape(q: str) -> str:
    """Цитата без экранирования Markdown и HTML-сущностей, «50 000 тенге» / «50 000 тг» → «50 000 ₸» (так в
    документах банка); если менять нечего — та же строка."""
    out = _MD_ESCAPE.sub(r"\1", q) if "\\" in q else q
    if "&" in out and ";" in out:
        import html
        out = html.unescape(out)
    return _TENGE_WORD.sub(r"\1 ₸", out)


def _same_words(idx: _Index, needle: str, hint: int | None, near: list[int]) -> dict | None:
    """Слова цитаты подряд, между ними — любые знаки (не буквы и не цифры). Краевые знаки цитаты («—» в
    «Swagger: —») тоже должны быть в документе. Одно слово с краевым знаком — только рядом с подсказкой или если
    такое место в документе одно."""
    if _ELLIPSIS.search(needle):
        return None
    words = re.findall(r"\w+", needle)
    alnum = sum(len(w) for w in words)
    # краевые знаки без разделителей («:», «|», «;», «,»): «Swagger: —» ищется как «Swagger», затем «—»
    lead = re.sub(r"[\s:;,|\"]", "", re.match(r"^\W*", needle).group())
    tail = re.sub(r"[\s:;,|\"]", "", re.search(r"\W*$", needle).group())
    if not words or (len(words) == 1 and not (lead or tail)) or alnum < (SKELETON_MIN if len(words) > 1 else 5):
        return None
    body = r"\W+".join(re.escape(w) for w in words)
    pat = ((re.escape(lead) + r"\W*" if lead else r"(?<!\w)") + body + (r"\W*" + re.escape(tail) if tail else r"(?!\w)"))
    spans = [(x.start(), x.end()) for x in re.finditer(pat, idx.full)]
    best = _pick(idx, spans, hint, near)
    if not best:
        return None
    (tier, *_), a, b, ls, le = best
    if len(words) == 1 and tier > 1 and len(spans) > 1:
        return None
    return _match(idx, a, b, ls, le, "normalized")


def _match_parts(idx: _Index, parts: list[str], hint: int | None, near: list[int]) -> dict | None:
    spans = []
    texts: dict[tuple[int, int], str] = {}
    for a0, b0 in idx.occurrences(parts[0]):
        s0 = idx.slot(a0)
        limit = idx.ends[min(len(idx.ends) - 1, s0 + MAX_GLUE - 1)]
        pos, pieces, ok = b0, [idx.original(a0, b0)], True
        for p in parts[1:]:
            a = idx.full.find(p, pos)
            if a < 0 or a + len(p) > limit:
                ok = False
                break
            pieces.append(idx.original(a, a + len(p)))
            pos = a + len(p)
        if ok:
            spans.append((a0, pos))
            # в отчёт — сплошной отрезок документа: его подстрокой проверяет verify (№13)
            texts[(a0, pos)] = idx.original(a0, pos)
    best = _pick(idx, spans, hint, near)
    if not best:
        return None
    _, a, b, ls, le = best
    return _match(idx, a, b, ls, le, "normalized", texts[(a, b)])


def _partial(needle: str, hay: str) -> tuple[float, int, int]:
    """Лучшее совпадение needle с отрезком hay: (оценка 0..1, начало, конец)."""
    if not hay:
        return 0.0, 0, 0
    if len(hay) <= len(needle):
        return SequenceMatcher(None, needle, hay, autojunk=False).ratio(), 0, len(hay)
    sm = SequenceMatcher(None, needle, hay, autojunk=False)
    best = (0.0, 0, 0)
    seen = set()
    for blk in sm.get_matching_blocks():
        if blk.size == 0:
            continue
        start = max(0, blk.b - blk.a)
        end = min(len(hay), start + len(needle))
        start = max(0, end - len(needle))
        if start in seen:
            continue
        seen.add(start)
        r = SequenceMatcher(None, needle, hay[start:end], autojunk=False).ratio()
        if r > best[0]:
            best = (r, start, end)
    return best


def _fuzzy(idx: _Index, needle: str, hint: int | None, points: list[int]) -> dict | None:
    cand_slots = sorted({k for k, no in enumerate(idx.nos)
                         if any(abs(no - p) <= FUZZY_RADIUS for p in points)})
    best = None
    for k in cand_slots:
        for width in range(1, MAX_GLUE + 1):
            k2 = k + width - 1
            if k2 >= len(idx.nos):
                break
            lo, hi = idx.starts[k], idx.ends[k2]
            hay = idx.full[lo:hi]
            r, s, e = _partial(needle, hay)
            if r < FUZZY_MIN:
                continue
            a, b = _widen(idx.full, lo + s, lo + e, lo, hi)
            s1, s2 = idx.span_lines(a, b)
            ls, le = idx.nos[s1], idx.nos[s2]
            d = _dist(ls, le, points)
            key = (-round(r, 4), le - ls, d, ls)
            if best is None or key < best[0]:
                best = (key, a, b, ls, le)
    if not best:
        return None
    _, a, b, ls, le = best
    return _match(idx, a, b, ls, le, "fuzzy")


def _widen(full: str, a: int, b: int, lo: int, hi: int) -> tuple[int, int]:
    """Расширить отрезок до границ слов, не выходя за [lo, hi)."""
    while a > lo and full[a - 1] != " ":
        a -= 1
    while b < hi and full[b] != " " and full[b - 1] != " ":
        b += 1
    while a < b and full[a] == " ":
        a += 1
    while b > a and full[b - 1] == " ":
        b -= 1
    return a, b


# --------------------------------------------------------------------------- пакетная сверка
def requirement_lines(requirements: Iterable[dict] | None) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for r in requirements or []:
        rid = str(r.get("id") or "")
        a, b = _as_int(r.get("line_start")), _as_int(r.get("line_end"))
        if rid and a:
            out[rid] = (a, b or a)
    return out


def verify_evidence(view: dict, ev: dict, near: Iterable[Any] = ()) -> dict:
    """Сверить одно доказательство (in place) и вернуть его: verified, line_start/line_end/page/section, quote."""
    quote = ev.get("quote")
    hint = ev.get("line") if ev.get("line") not in (None, "", 0) else ev.get("line_start")
    m = verify_quote(view, quote, hint, near)
    if m:
        ev["quote"] = m["text"]  # всегда дословный текст документа (без префиксов и обрамления модели)
        ev["line"] = m["line_start"]
        ev.update({k: m[k] for k in ("line_start", "line_end", "page", "section", "verified")})
    else:
        h = _as_int(hint) or 0
        ev.update({"verified": "missing", "line_start": h, "line_end": h, "page": None, "section": ""})
    return ev


def verify_candidates(view: dict, candidates: Iterable[dict], requirements: Iterable[dict] | None = None,
                      *, keep_missing_evidence: bool = False) -> dict:
    """Сверить цитаты всех кандидатов.

    Возвращает ``{"candidates": [...], "rejected": [...], "stats": {...}}``. У оставленных кандидатов
    доказательства с ``verified=missing`` убираются (если не ``keep_missing_evidence``), а на уровне
    кандидата ставятся ``line_start/line_end/page/section`` первого найденного доказательства.
    Кандидат без единой найденной цитаты попадает в ``rejected`` с ``reason = "цитата не найдена"``.
    """
    req_lines = requirement_lines(requirements)
    kept: list[dict] = []
    rejected: list[dict] = []
    stats = {"quotes": 0, "verified": 0, "exact": 0, "normalized": 0, "fuzzy": 0, "missing": 0,
             "candidates_in": 0, "candidates_kept": 0, "candidates_rejected": 0}
    for cand in candidates or []:
        stats["candidates_in"] += 1
        near = [req_lines[r] for r in cand.get("requirement_ids") or [] if r in req_lines]
        evidence = [e for e in (cand.get("evidence") or []) if isinstance(e, dict)]
        seen: set[tuple] = set()
        checked: list[dict] = []
        for ev in evidence:
            verify_evidence(view, ev, near)
            stats["quotes"] += 1
            stats[ev["verified"]] += 1
            if ev["verified"] != "missing":
                stats["verified"] += 1
            key = (ev.get("line_start"), ev.get("line_end"), normalize(str(ev.get("quote") or "")))
            if ev["verified"] != "missing" and key in seen:
                continue
            seen.add(key)
            checked.append(ev)
        found = [e for e in checked if e["verified"] != "missing"]
        if not found:
            cand["evidence"] = checked
            cand["reason"] = REASON_MISSING
            rejected.append(cand)
            stats["candidates_rejected"] += 1
            continue
        cand["evidence"] = checked if keep_missing_evidence else found
        first = found[0]
        cand.update({k: first[k] for k in ("line_start", "line_end", "page", "section")})
        kept.append(cand)
        stats["candidates_kept"] += 1
    stats["share_verified"] = round(stats["verified"] / stats["quotes"], 4) if stats["quotes"] else 1.0
    return {"candidates": kept, "rejected": rejected, "stats": stats}


def verify_requirements(view: dict, requirements: Iterable[dict]) -> dict:
    """Уточнить строки требований по их цитатам (выход segment): line_start/line_end/page, раздел — если пуст.
    Диапазон, внутри которого лежит цитата, сохраняется целиком; исправляется только диапазон, не содержащий цитату.

    Возвращает ``{"requirements": [...], "missing": [ID…]}``; требования без найденной цитаты остаются как есть.
    """
    reqs = list(requirements or [])
    missing = []
    for r in reqs:
        m = verify_quote(view, r.get("quote"), r.get("line_start"), [(r.get("line_start"), r.get("line_end"))]
                         if r.get("line_start") else ())
        if not m:
            missing.append(r.get("id", ""))
            continue
        ls, le = m["line_start"], m["line_end"]
        old_s, old_e = _as_int(r.get("line_start")), _as_int(r.get("line_end"))
        # цитата — часть требования: если она внутри диапазона требования, диапазон не сужаем (просьба №04:
        # «Общие параметры» 103–114 не должны стать 103); диапазон меняется, только если цитата вне его
        if old_s and old_e and old_s <= ls and le <= old_e:
            ls, le = old_s, old_e
        r["line_start"], r["line_end"], r["page"] = ls, le, m["page"]
        if not r.get("section"):
            r["section"] = m["section"]
    return {"requirements": reqs, "missing": missing}


# --------------------------------------------------------------------------- аудит привязки готового отчёта
_HINT_STAGES = ("lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency", "rules")


def _line_hits(view: dict, quote: str) -> list[int]:
    """Номера строк, в которых цитата встречается (после нормализации) — для поиска повторяющихся фраз."""
    idx = _index(view)
    needle = _clean_quote(quote or "")
    if len(needle) < MIN_QUOTE:
        return []
    out = []
    for a, b in idx.occurrences(needle):
        s1, s2 = idx.span_lines(a, b)
        if s2 - s1 + 1 <= MAX_GLUE:
            out.append(idx.nos[s1])
    return sorted(set(out))


def audit_report(report: dict, view: dict, stages: dict | None = None) -> dict:
    """Проверить привязку цитат готового отчёта к документу — независимо от того, как их ставил прогон.

    * каждое доказательство дефекта: сверено (не ``missing``), текст есть на указанных строках, страница и раздел
      совпадают со строкой документа;
    * повторяющаяся фраза: если цитата встречается в документе несколько раз, взятое вхождение должно лежать в
      строках требований дефекта (или рядом), когда такое вхождение есть, — если только эту строку не указала сама
      модель (видно по ``stages``);
    * цитаты нарезки — в пределах строк требования (±2);
    * ``stages`` (выходы этапов из ``runs/<id>/stages``): номер строки, который написала модель, против найденного
      кодом, и кандидаты, потерянные сверкой («цитата не найдена»).

    Возвращает ``{"ok", "evidence", "by_verified", "problems": [{"where", "what"}], "requirements", "hints",
    "lost"}``.
    """
    lines = view.get("lines") or []
    by_no = {ln["n"]: ln for ln in lines}
    reqs = {r.get("id"): r for r in report.get("requirements") or []}
    # строки, на которые указала сама модель (выходы этапов): повтор фразы там — её выбор, а не ошибка сверки
    pointed: set[tuple[str, int]] = set()
    hints = {"total": 0, "same_line": 0, "within_2": 0, "far": 0, "far_list": []}
    lost: list[dict] = []
    req_lines = requirement_lines(report.get("requirements"))
    for name, out in (stages or {}).items():
        if name == "quotes":
            for c in (out or {}).get("rejected") or []:
                lost.append({"source": c.get("source", ""), "title": str(c.get("title") or "")[:90],
                             "quotes": [str(e.get("quote") or "")[:90] for e in c.get("evidence") or []]})
            continue
        if name not in _HINT_STAGES:
            continue
        for c in (out or {}).get("candidates") or []:
            near = [req_lines[r] for r in c.get("requirement_ids") or [] if r in req_lines]
            for ev in c.get("evidence") or []:
                h = _as_int(ev.get("line"))
                if h is None:
                    continue
                m = verify_quote(view, ev.get("quote"), h, near)
                if not m:
                    continue
                hints["total"] += 1
                if m["line_start"] - HINT_RADIUS <= h <= m["line_end"] + HINT_RADIUS:
                    pointed.add((_clean_quote(m["text"]), m["line_start"]))
                d = 0 if m["line_start"] <= h <= m["line_end"] else min(abs(h - m["line_start"]), abs(h - m["line_end"]))
                if d == 0:
                    hints["same_line"] += 1
                elif d <= HINT_RADIUS:
                    hints["within_2"] += 1
                else:
                    hints["far"] += 1
                    hints["far_list"].append({"stage": name, "hint": h, "found": m["line_start"],
                                              "repeats": _line_hits(view, ev.get("quote") or "")[:6],
                                              "quote": str(ev.get("quote") or "")[:80]})
    problems: list[dict] = []
    by_verified: dict[str, int] = {}
    n_ev = 0
    for f in report.get("findings") or []:
        fid = f.get("id", "?")
        ranges = [(int(reqs[r].get("line_start") or 0), int(reqs[r].get("line_end") or reqs[r].get("line_start") or 0))
                  for r in f.get("requirement_ids") or [] if r in reqs and reqs[r].get("line_start")]
        for i, ev in enumerate(f.get("evidence") or [], 1):
            n_ev += 1
            where = f"{fid} цитата №{i}"
            ver = ev.get("verified") or "missing"
            by_verified[ver] = by_verified.get(ver, 0) + 1
            q = str(ev.get("quote") or "")
            ls, le = _as_int(ev.get("line_start")) or 0, _as_int(ev.get("line_end")) or 0
            if ver == "missing":
                problems.append({"where": where, "what": f"цитата не сверена: «{q[:80]}»"})
                continue
            le = max(le, ls)
            text = " ".join(str(by_no.get(k, {}).get("text") or "") for k in range(ls, le + 1))
            if not ls or ls not in by_no:
                problems.append({"where": where, "what": f"строка {ls} вне документа"})
                continue
            if _clean_quote(q) not in normalize(text) and ver != "fuzzy":
                problems.append({"where": where, "what": f"«{q[:80]}» нет в строках {ls}–{le}"})
                continue
            ln = by_no[ls]
            if ev.get("page") not in (None, "", 0) and ln.get("page") and int(ev["page"]) != int(ln["page"]):
                problems.append({"where": where, "what": f"страница {ev['page']}, а строка {ls} — на странице {ln['page']}"})
            if (ev.get("section") or "") != (ln.get("section") or "") and ln.get("section"):
                problems.append({"where": where, "what": f"раздел «{ev.get('section')}», у строки {ls} — «{ln.get('section')}»"})
            hits = _line_hits(view, q)
            if len(hits) > 1 and ranges and (_clean_quote(q), ls) not in pointed:
                inside = [h for h in hits if any(a - HINT_RADIUS <= h <= b + HINT_RADIUS for a, b in ranges)]
                if inside and not any(a - HINT_RADIUS <= ls <= b + HINT_RADIUS for a, b in ranges):
                    problems.append({"where": where, "what": f"фраза встречается в строках {hits[:6]}; взята {ls}, "
                                                             f"а в строках требований дефекта — {inside[:3]}"})
    req_bad = []
    for r in report.get("requirements") or []:
        q = r.get("quote") or ""
        if not q:
            continue
        a, b = _as_int(r.get("line_start")), _as_int(r.get("line_end"))
        m = verify_quote(view, q, a, [(a, b or a)] if a else ())
        if not m or not a or not (a - HINT_RADIUS <= m["line_start"] <= (b or a) + HINT_RADIUS):
            req_bad.append({"id": r.get("id"), "quote": q[:80], "lines": f"{a}–{b}",
                            "found": m["line_start"] if m else None})
    return {"ok": not problems and not lost, "evidence": n_ev, "by_verified": by_verified, "problems": problems,
            "requirements": {"total": sum(1 for r in report.get("requirements") or [] if r.get("quote")),
                             "outside": req_bad},
            "hints": hints, "lost": lost}


def _audit_main(argv: list[str]) -> int:
    """``python -m bcc_review.v2.quotes audit runs/<id>|report.json --doc ФАЙЛ [--json]``."""
    import argparse
    import json
    from pathlib import Path

    from . import docview

    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.quotes audit",
                                 description="Аудит привязки цитат готового отчёта к документу")
    ap.add_argument("target", help="каталог прогона runs/<id> или report.json")
    ap.add_argument("--doc", required=True, help="файл требований, по которому строился отчёт")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    t = Path(a.target)
    stages: dict[str, Any] = {}
    if t.is_dir():
        for p in sorted((t / "stages").glob("*.json")):
            try:
                stages[p.stem] = json.loads(p.read_text(encoding="utf-8")).get("output") or {}
            except (OSError, ValueError):
                continue
        rp = t / "report.json"
        report = json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}
        if not report:  # прогон ещё идёт или упал: проверяем то, что есть в этапах
            seg = stages.get("segment") or {}
            report = {"requirements": seg.get("requirements") or [],
                      "findings": (stages.get("quotes") or {}).get("candidates") or []}
    else:
        report = json.loads(t.read_text(encoding="utf-8"))
    view = docview.load(a.doc)
    res = audit_report(report, view, stages)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 4
    h = res["hints"]
    print(f"Доказательств: {res['evidence']} {res['by_verified']}; расхождений: {len(res['problems'])}; "
          f"цитат нарезки вне строк требования: {len(res['requirements']['outside'])}/{res['requirements']['total']}; "
          f"потеряно кандидатов: {len(res['lost'])}")
    if h["total"]:
        print(f"Строка модели ↔ найденная: та же {h['same_line']}, ±2 {h['within_2']}, дальше {h['far']} из {h['total']}")
    for p in res["problems"]:
        print(f"  ! {p['where']}: {p['what']}")
    for r in res["requirements"]["outside"]:
        print(f"  ~ {r['id']} ({r['lines']}): «{r['quote']}» → {r['found']}")
    for x in h["far_list"][:20]:
        print(f"  > {x['stage']}: модель L{x['hint']}, найдено L{x['found']}, повторы {x['repeats']}: «{x['quote']}»")
    for x in res["lost"]:
        print(f"  ✗ {x['source']}: {x['title']} — {x['quotes']}")
    return 0 if res["ok"] else 4


def main(argv: list[str] | None = None) -> int:
    """``python -m bcc_review.v2.quotes ФАЙЛ "цитата" [--line N] [--near A-B]`` или ``--candidates out.json``;
    ``python -m bcc_review.v2.quotes audit runs/<id> --doc ФАЙЛ`` — аудит привязки готового отчёта."""
    import argparse
    import json
    import sys

    from . import docview

    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if argv and argv[0] == "audit":
        return _audit_main(argv[1:])

    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.quotes", description="Сверка цитат с документом")
    ap.add_argument("file")
    ap.add_argument("quote", nargs="?", default="")
    ap.add_argument("--line", type=int, default=None)
    ap.add_argument("--near", default="", help="строки требования, например 38-40")
    ap.add_argument("--candidates", help="JSON с полем candidates (ответ линзы) — сверить все цитаты")
    ap.add_argument("--requirements", help="segment.json — строки требований как подсказки")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    view = docview.load(a.file)
    if a.candidates:
        data = json.loads(open(a.candidates, encoding="utf-8").read())
        reqs = None
        if a.requirements:
            reqs = json.loads(open(a.requirements, encoding="utf-8").read()).get("requirements")
        cands = data.get("candidates", data if isinstance(data, list) else [])
        hints = [[(e.get("line"), e.get("quote")) for e in c.get("evidence") or []] for c in cands]
        res = verify_candidates(view, cands, reqs, keep_missing_evidence=True)
        for c, hs in zip(res["candidates"] + res["rejected"], hints):
            for e in c.get("evidence") or []:
                mark = e["verified"] if e["verified"] != "missing" else "НЕТ"
                print(f"{c.get('id') or '—':<6} L{e.get('line_start')}–{e.get('line_end')} {mark:<10} "
                      f"«{str(e.get('quote'))[:90]}»")
        print(json.dumps(res["stats"], ensure_ascii=False))
        return 0
    near = []
    if a.near:
        x, _, y = a.near.partition("-")
        near = [(int(x), int(y or x))]
    m = verify_quote(view, a.quote, a.line, near)
    print(json.dumps(m, ensure_ascii=False, indent=1) if m else "цитата не найдена")
    return 0 if m else 1


if __name__ == "__main__":
    raise SystemExit(main())
