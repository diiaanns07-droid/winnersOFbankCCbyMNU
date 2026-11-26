"""Детерминированный линтер требований: всегда включённый первый проход и режим ``--offline-lint``.

``lint(document, requirements)`` применяет общие правила к документу (контракт v1, ``Document``)
и возвращает ``{"candidates": [Candidate], "checks": [Check], "warnings": [str]}``.

Правила не привязаны к конкретному ТЗ: они ищут типовые дефекты банковских и ИТ-спецификаций
по ISO/IEC/IEEE 29148:2018 (5.2.5–5.2.7), IEEE 830-1998 (4.3) и RFC 9110. Тексты для человека —
на русском, английские ключевые слова распознаются там, где они естественны (API, таблицы).

Инварианты результата:

* у каждой подсказки ``{block_id, quote}`` цитата — точная подстрока ``block.text`` длиной 3–120
  символов, по возможности уникальная внутри блока (координаты считает модуль опор);
* противоречие (``kind = conflict``) несёт ``witness`` с двумя подсказками ``hint_a``/``hint_b``;
* правила не выносят ``critical``: ``major`` — риск неверной реализации, ``minor`` — стиль и шаблон;
* ``cause = {object, condition, outcomes}`` описывает первопричину — по ней движок склеивает дубли;
* ``checks`` содержат только ``issue`` по требованиям: доказать ``pass`` правила не могут.

Сбой одного правила не роняет линтер: правило пропускается, причина попадает в ``warnings``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Iterable, Optional

from ...contracts import FINDING_KINDS, INDIVIDUAL_CRITERIA, SET_CRITERIA

__all__ = ["lint", "RULE_IDS"]

SOURCE = "rules"
STAGE = "rules"
MIN_QUOTE = 3
MAX_QUOTE = 120
MAX_HINTS = 6

_PROSE_KINDS = frozenset({"paragraph", "list_item", "table_row", "quote", "other"})

# Разделы-шаблоны (чек-лист ревью, согласующие, история версий): не требования, но заглушки в них важны.
_TEMPLATE_SEC = re.compile(
    r"ревью\s+требовани|requirements?\s+review|чек-?\s?лист|check-?\s?list|согласующ|лист\s+согласовани"
    r"|approv(?:al|ers?)|sign-?off|история\s+(?:изменени|верси)|change\s*log|revision\s+history"
    r"|^содержание$|table\s+of\s+contents", re.I)
# Паспорт документа и глоссарий: служебные поля, термины там определяются, а не используются.
_META_SEC = re.compile(
    r"общие\s+сведения|паспорт\s+документа|сведения\s+о\s+документе|general\s+information"
    r"|document\s+info|глоссарий|glossary|термины\s+и\s+определения|^definitions$", re.I)

# Идентификатор требования в начале пункта: «Ф-1.», «НФТ-2», «FR-3», «REQ-12», «[UC-4]».
_ID_AT_START = re.compile(r"^\W{0,3}([A-Za-zА-Яа-яЁё]{1,8}[-‑–_.]?\d+(?:\.\d+)*)(?![\w-])")
_ID_STRIP = re.compile(r"^\W{0,3}[A-Za-zА-Яа-яЁё]{1,8}[-‑–_.]?\d+(?:\.\d+)*[.):]?\s+")
_LIST_NUM = re.compile(r"^\s*\d{1,3}[.)]\s+")

_NUMBER_WORD = (r"(?:\d|один|одна|одно|одного|одной|одну|два|две|двух|двум|три|трёх|трех|четыре|четырёх|"
                r"четырех|пять|пяти|шесть|шести|семь|семи|восемь|восьми|девять|девяти|десять|десяти|сто|ста|"
                r"тысяч[аиу]?|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)")
_NUMBER_AHEAD = re.compile(rf"^[\s:—–-]*(?:[^\s.;!?]+\s+){{0,2}}?{_NUMBER_WORD}", re.I)


# =========================================================================== утилиты
def _text(b: dict) -> str:
    return b.get("text") or ""


def _kind(b: dict) -> str:
    return b.get("kind") or "other"


def _section(b: dict) -> list[str]:
    return [s for s in (b.get("section") or []) if isinstance(s, str)]


def _sec_name(b: dict) -> str:
    sec = _section(b)
    return sec[-1] if sec else "документ"


def _is_template(section: Iterable[str]) -> bool:
    return any(_TEMPLATE_SEC.search(s.strip()) for s in section)


def _is_meta(section: Iterable[str]) -> bool:
    return any(_META_SEC.search(s.strip()) for s in section)


def _eligible(b: dict) -> bool:
    """Блок с текстом требований: не заголовок, не код, не шапка таблицы, не шаблон и не паспорт."""
    sec = _section(b)
    return (_kind(b) in _PROSE_KINDS and bool(_text(b).strip())
            and not _is_template(sec) and not _is_meta(sec))


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold().strip()


def _q(s: str) -> str:
    return f"«{s}»"


def _join_q(items: Iterable[str], limit: int = 3) -> str:
    items = list(dict.fromkeys(items))
    head = ", ".join(_q(i) for i in items[:limit])
    return head + (f" и ещё {len(items) - limit}" if len(items) > limit else "")


# ----------------------------------------------------------------- цитаты
_EDGE_L = " \t\r\n|"
_EDGE_R = " \t\r\n|,;"


def _trim(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s] in _EDGE_L:
        s += 1
    while e > s and text[e - 1] in _EDGE_R:
        e -= 1
    return s, e


def _word_end(text: str, pos: int) -> int:
    n = len(text)
    i = pos
    while i < n and text[i].isspace():
        i += 1
    while i < n and not text[i].isspace():
        i += 1
    return i


def _word_start(text: str, pos: int) -> int:
    i = pos
    while i > 0 and text[i - 1].isspace():
        i -= 1
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return i


def _cut(text: str, s: int, limit: int) -> int:
    if limit >= len(text):
        return len(text)
    idx = text.rfind(" ", s + MIN_QUOTE, limit + 1)
    return idx if idx > s else limit


def _repeats(text: str, q: str) -> bool:
    i = text.find(q)
    return i != -1 and text.find(q, i + 1) != -1


def _hint(block: dict, start: int, end: int) -> Optional[dict]:
    """Подсказка на ``block.text[start:end]``: обрезка краёв, 3–120 символов, расширение до уникальности."""
    text = _text(block)
    n = len(text)
    s = max(0, min(start, n))
    e = max(s, min(end, n))
    s, e = _trim(text, s, e)
    guard = 0
    while e - s < MIN_QUOTE and guard < 8:
        if e < n:
            e = _word_end(text, e)
        elif s > 0:
            s = _word_start(text, s)
        else:
            break
        s, e = _trim(text, s, e)
        guard += 1
    if e - s > MAX_QUOTE:
        e = _cut(text, s, s + MAX_QUOTE)
        s, e = _trim(text, s, e)
    guard = 0
    while _repeats(text, text[s:e]) and guard < 30:
        ne = _word_end(text, e)
        if e < ne and ne - s <= MAX_QUOTE:
            e = ne
        else:
            ns = _word_start(text, s)
            if ns < s and e - ns <= MAX_QUOTE:
                s = ns
            else:
                break
        s, e = _trim(text, s, e)
        guard += 1
    quote = text[s:e]
    if not (MIN_QUOTE <= len(quote) <= MAX_QUOTE):
        return None
    return {"block_id": block["id"], "quote": quote}


def _whole(block: dict) -> Optional[dict]:
    """Подсказка на начало блока (весь текст, если он короче 120 символов)."""
    return _hint(block, 0, len(_text(block)))


# ----------------------------------------------------------------- предложения
_ABBREV = frozenset(
    "т д п е др пр см напр г гг руб коп тыс млн млрд стр рис ст ч мин сек им ул кв вкл искл ср прим эл тел "
    "max min no vs etc eg ie".split())


def _push(spans: list, text: str, s: int, e: int) -> None:
    s, e = _trim(text, s, e)
    if e > s:
        spans.append((s, e))


def _is_abbrev(text: str, start: int, dot: int) -> bool:
    m = re.search(r"(\w+)$", text[start:dot])
    if not m:
        return False
    w = m.group(1).lower()
    return w in _ABBREV or (len(w) == 1 and w.isalpha())


def _starts_sentence(text: str, j: int) -> bool:
    n = len(text)
    while j < n and text[j] in " \t":
        j += 1
    if j >= n:
        return False
    c = text[j]
    return c.isupper() or c.isdigit() or c in "«\"(“"


def _sentences(text: str) -> list[tuple[int, int]]:
    """Границы предложений: точка/!/? перед заглавной буквой и перевод строки; сокращения не режут."""
    spans: list[tuple[int, int]] = []
    n = len(text)
    start = 0
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            _push(spans, text, start, i)
            start = i + 1
            i += 1
            continue
        if ch in ".!?…":
            j = i + 1
            while j < n and text[j] in ".!?…»\"')":
                j += 1
            if j < n and text[j] in " \t" and _starts_sentence(text, j):
                if not (ch == "." and _is_abbrev(text, start, i)):
                    _push(spans, text, start, j)
                    start = j
            i = j
            continue
        i += 1
    _push(spans, text, start, n)
    return spans


def _sentence_at(text: str, pos: int) -> tuple[int, int]:
    for s, e in _sentences(text):
        if s <= pos < e:
            return s, e
    return 0, len(text)


def _clause_start(text: str, pos: int, max_back: int = 70) -> int:
    """Начало фрагмента предложения перед ``pos`` (после «,», «;», «:»), не дальше ``max_back`` символов."""
    s, _ = _sentence_at(text, pos)
    i = pos
    while i > s and text[i - 1] not in ",;:" and pos - i < max_back:
        i -= 1
    return i if pos - i < max_back else _word_start(text, i)


def _back_words(text: str, pos: int, words: int, floor: int = 0) -> int:
    i = pos
    for _ in range(words):
        j = _word_start(text, i)
        if j < floor or j == i:
            break
        i = j
    return i


def _in_quotes(text: str, pos: int) -> bool:
    before = text[:pos]
    if before.count("«") > before.count("»"):
        return True
    line = before[before.rfind("\n") + 1:]
    return line.count('"') % 2 == 1


# ----------------------------------------------------------------- таблицы
def _cells(text: str) -> list[tuple[int, int]]:
    """Ячейки строки таблицы (текст блока склеен через « | »): список (начало, конец) без краевых пробелов."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in re.finditer(r" \| ", text):
        spans.append((pos, m.start()))
        pos = m.end()
    if text.endswith(" |") and pos <= len(text) - 2:
        spans.append((pos, len(text) - 2))
        spans.append((len(text), len(text)))
    else:
        spans.append((pos, len(text)))
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        out.append((s, e))
    return out


def _cell_texts(b: dict) -> list[str]:
    t = _text(b)
    return [t[s:e] for s, e in _cells(t)]


# =========================================================================== контекст
class _Ctx:
    def __init__(self, document: dict, requirements: Optional[list]):
        doc = document or {}
        self.blocks: list[dict] = [b for b in doc.get("blocks", []) or []
                                   if isinstance(b, dict) and isinstance(b.get("id"), str)]
        self.by_id = {b["id"]: b for b in self.blocks}
        self.pos = {b["id"]: i for i, b in enumerate(self.blocks)}
        self.requirements = [r for r in (requirements or []) if isinstance(r, dict) and r.get("id")]
        self.req_by_id = {r["id"]: r for r in self.requirements}
        self.req_of: dict[str, list[str]] = {}
        for r in self.requirements:
            for bid in r.get("block_ids") or []:
                lst = self.req_of.setdefault(bid, [])
                if r["id"] not in lst:
                    lst.append(r["id"])
        self.warnings: list[str] = []
        self.extra_checks: list[dict] = []
        self.placeholder_done: set[str] = set()   # блоки, уже описанные правилом пустых разделов
        self._tables: Optional[list[dict]] = None
        self._endpoints: Optional[list[dict]] = None

    def reqs(self, block_ids: Iterable[str]) -> list[str]:
        out: list[str] = []
        for bid in block_ids:
            for rid in self.req_of.get(bid, []):
                if rid not in out:
                    out.append(rid)
        return out

    def req_text(self, rid: str) -> str:
        r = self.req_by_id.get(rid) or {}
        parts = [_text(self.by_id[b]) for b in r.get("block_ids") or [] if b in self.by_id]
        return "\n".join(parts) or (r.get("text") or "")

    def source_id(self, b: dict) -> Optional[str]:
        for rid in self.req_of.get(b["id"], []):
            sid = self.req_by_id[rid].get("source_id")
            if sid:
                return str(sid)
        m = _ID_AT_START.match(_text(b))
        return m.group(1) if m and _kind(b) in ("list_item", "paragraph") else None

    def where(self, b: dict) -> str:
        sid = self.source_id(b)
        return f"требовании {sid}" if sid else f"разделе {_q(_sec_name(b))}"

    def heading_for(self, b: dict) -> Optional[dict]:
        """Ближайший предшествующий заголовок блока."""
        for i in range(self.pos[b["id"]] - 1, -1, -1):
            if _kind(self.blocks[i]) == "heading":
                return self.blocks[i]
        return None

    def tables(self) -> list[dict]:
        """Таблицы: шапка и идущие подряд строки. ``columns`` — тексты ячеек шапки."""
        if self._tables is not None:
            return self._tables
        tables: list[dict] = []
        cur: Optional[dict] = None
        prev = -2
        for i, b in enumerate(self.blocks):
            k = _kind(b)
            if k == "table_header":
                cur = {"header": b, "rows": [], "section": tuple(_section(b)), "columns": _cell_texts(b)}
                tables.append(cur)
            elif k == "table_row":
                if cur is None or prev != i - 1:
                    cols = [str(c) for c in (b.get("loc") or {}).get("columns") or []]
                    cur = {"header": None, "rows": [], "section": tuple(_section(b)), "columns": cols}
                    tables.append(cur)
                cur["rows"].append(b)
            else:
                cur = None
                continue
            prev = i
        self._tables = tables
        return tables


def _valid_hint(ctx: _Ctx, h: Any) -> bool:
    if not isinstance(h, dict):
        return False
    b = ctx.by_id.get(h.get("block_id"))
    q = h.get("quote")
    return (b is not None and isinstance(q, str) and MIN_QUOTE <= len(q) <= MAX_QUOTE and q in _text(b))


_ALL_CRITERIA = INDIVIDUAL_CRITERIA + SET_CRITERIA


def _make(ctx: _Ctx, *, rule_id: str, kind: str, criterion: str | tuple[str, str], severity: str,
          title: str, impact: str, hints: Iterable[Optional[dict]], recommendation: str,
          cause: dict, witness: Optional[dict] = None) -> Optional[dict]:
    """Собрать Candidate. ``criterion`` — строка или пара (для одного требования, для набора)."""
    clean: list[dict] = []
    seen: set[tuple[str, str]] = set()
    pool: list[Optional[dict]] = []
    if witness is not None:
        if not (_valid_hint(ctx, witness.get("hint_a")) and _valid_hint(ctx, witness.get("hint_b"))):
            ctx.warnings.append(f"{rule_id}: кандидат «{title}» отброшен: witness без точных цитат")
            return None
        pool += [witness["hint_a"], witness["hint_b"]]
    pool += list(hints)
    for h in pool:
        if h is None:
            continue
        key = (h.get("block_id"), h.get("quote"))
        if key in seen:
            continue
        if not _valid_hint(ctx, h):
            ctx.warnings.append(f"{rule_id}: отброшена подсказка без точной цитаты в блоке {h.get('block_id')}")
            continue
        seen.add(key)
        clean.append({"block_id": h["block_id"], "quote": h["quote"]})
    if not clean:
        ctx.warnings.append(f"{rule_id}: кандидат «{title}» отброшен: нет ни одной точной цитаты")
        return None
    clean = clean[:MAX_HINTS]
    req_ids = ctx.reqs(h["block_id"] for h in clean)
    scope = "requirement" if len(req_ids) == 1 else "set"
    if isinstance(criterion, tuple):
        criterion = criterion[0] if scope == "requirement" else criterion[1]
    if kind not in FINDING_KINDS or criterion not in _ALL_CRITERIA or severity not in ("major", "minor"):
        raise ValueError(f"{rule_id}: недопустимые kind/criterion/severity: {kind}/{criterion}/{severity}")
    cand: dict[str, Any] = {
        "scope": scope, "kind": kind, "criterion": criterion, "severity": severity,
        "title": title, "impact": impact, "req_ids": req_ids, "hints": clean,
        "recommendation": recommendation,
        "cause": {"object": cause.get("object", title), "condition": cause.get("condition", ""),
                  "outcomes": list(cause.get("outcomes") or [])},
    }
    if witness is not None:
        cand["witness"] = {
            "input": witness["input"], "outcome_a": witness["outcome_a"], "outcome_b": witness["outcome_b"],
            "hint_a": {"block_id": witness["hint_a"]["block_id"], "quote": witness["hint_a"]["quote"]},
            "hint_b": {"block_id": witness["hint_b"]["block_id"], "quote": witness["hint_b"]["quote"]},
        }
    cand.update({"source": SOURCE, "stage": STAGE, "rule_id": rule_id})
    return cand


def _conflict_criterion() -> tuple[str, str]:
    return ("correct", "set_consistent")


# =========================================================================== 1. RULE-VAGUE
# (категория, регулярное выражение, нужна ли проверка «за словом идёт число»)
_VAGUE_SPECS: tuple[tuple[str, str, bool], ...] = (
    ("time", r"быстр(?!одейств)\w*(?!\s+(?:платеж|платёж|перевод|оплат))", False),
    ("time", r"своевременн\w*", False),
    ("time", r"в\s+момент(?:\s+(?!времени)[\w-]+)?", False),
    ("time", r"мгновенн\w*", False),
    ("time", r"оперативн\w*(?!\s+(?:памят|данн|учёт|учет|отч[её]т))", False),
    ("time", r"незамедлительн\w*|немедленн\w*", False),
    ("time", r"в\s+кратчайш\w+\s+срок\w*|в\s+разумн\w+\s+срок\w*|в\s+реальном\s+времени", False),
    ("time", r"asap|as\s+soon\s+as\s+possible|quickly|fast|timely|real[- ]time|instant(?:ly)?", False),
    ("quality", r"удобн\w*|интуитивн\w*|оптимальн\w*|гибк\w*|современн\w*|дружелюбн\w*|понятн\w*", False),
    ("quality", r"эффективн\w*(?!\s+(?:процентн|ставк))", False),
    ("quality", r"над[её]жн\w*", False),
    ("quality", r"высок\w+\s+(?:производительн|качеств|скорост|надёжн|надежн|доступн)\w*", False),
    ("quality", r"user[- ]friendly|intuitive|easy\s+to\s+use|efficient(?:ly)?|flexible|robust|seamless(?:ly)?",
     False),
    ("loophole", r"по\s+(?:мере\s+)?возможности|при\s+необходимости|в\s+случае\s+необходимости"
                 r"|если\s+(?:это\s+)?возможно|при\s+наличии\s+возможности", False),
    ("loophole", r"if\s+possible|as\s+(?:needed|appropriate|required)|where\s+(?:possible|applicable)", False),
    ("hedge", r"как\s+правило|обычно|около|примерно|приблизительн\w*|в\s+основном|почти", False),
    ("hedge", r"достаточн\w*(?!\s+(?:средств|денег|баланс|остат))", False),
    ("hedge", r"usually|normally|typically|approximately|sufficient(?:ly)?", False),
    ("hedge", r"максимум|минимум|максимально|минимально|не\s+более|не\s+менее", True),
)
_VAGUE_RES = tuple((cat, re.compile(rf"(?<!\w)(?:{rx})(?!\w)", re.I), num) for cat, rx, num in _VAGUE_SPECS)

_VAGUE_CAT = {
    "time": ("unverifiable", "verifiable", "Размытый срок",
             "Срок нельзя проверить тестом: разработчик сам выберет синхронную или отложенную обработку, "
             "тестировщик не сможет зафиксировать ожидаемое время.",
             "заменить {q} измеримым условием: «не позднее <уточнить: N с/мин> после <уточнить: событие-отсчёт>», "
             "указать перцентиль и точку измерения"),
    "quality": ("unverifiable", "verifiable", "Субъективная характеристика",
                "Качество нельзя принять или отклонить объективно: приёмка превратится в спор о вкусах, "
                "реализация будет произвольной.",
                "заменить {q} проверяемым критерием: <уточнить: метрика, порог и способ измерения>"),
    "loophole": ("ambiguity", "unambiguous", "Лазейка",
                 "Обязательство становится необязательным: исполнитель вправе не реализовать поведение, "
                 "а тест не может требовать его выполнения.",
                 "убрать {q} или перечислить условия явно: «если <уточнить: условие>, то <уточнить: действие>»"),
    "hedge": ("ambiguity", "unambiguous", "Неточная оговорка",
              "Норма допускает исключения и приблизительные значения без границ: разработчик и тестировщик "
              "трактуют её по-разному.",
              "заменить {q} точным значением или диапазоном (<уточнить: значение и допуск>), исключения перечислить"),
}


def _rule_vague(ctx: _Ctx) -> list[dict]:
    """RULE-VAGUE: размытые, субъективные слова и лазейки (ISO/IEC/IEEE 29148, 5.2.7).

    Ищет по основам с учётом границ слова (русская морфология: «быстр…», «удобн…»), пропускает
    заголовки, код, шапки таблиц, шаблоны, паспорт и текст в кавычках «…» (названия кнопок и продуктов).
    «Максимум N», «не более N» с числом — точная норма, не замечание. Один кандидат на блок.
    """
    out: list[dict] = []
    for b in ctx.blocks:
        if not _eligible(b):
            continue
        text = _text(b)
        hits: list[tuple[int, int, str]] = []
        for cat, rx, need_num in _VAGUE_RES:
            for m in rx.finditer(text):
                if need_num and _NUMBER_AHEAD.match(text[m.end():m.end() + 40]):
                    continue
                if _in_quotes(text, m.start()):
                    continue
                hits.append((m.start(), m.end(), cat))
        if not hits:
            continue
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        kept: list[tuple[int, int, str]] = []
        for h in hits:
            if kept and h[0] < kept[-1][1]:
                continue
            kept.append(h)
        hints = [_hint(b, s, e) for s, e, _ in kept]
        quotes = [text[s:e] for s, e, _ in kept]
        cats = list(dict.fromkeys(c for _, _, c in kept))
        kind, crit, label, impact, _ = _VAGUE_CAT[cats[0]]
        where = ctx.where(b)
        if len(kept) == 1:
            title = f"{label} {_q(quotes[0])} в {where}"
        else:
            title = f"Размытые формулировки {_join_q(quotes)} в {where}"
        recs = []
        for c in cats:
            qs = ", ".join(_q(q) for (s, e, cc), q in zip(kept, quotes) if cc == c)
            recs.append(_VAGUE_CAT[c][4].format(q=qs))
        rec = "; ".join(recs)
        rec = rec[0].upper() + rec[1:] + "."
        severity = "major" if ctx.req_of.get(b["id"]) else "minor"
        c = _make(ctx, rule_id="RULE-VAGUE", kind=kind, criterion=crit, severity=severity, title=title,
                  impact=impact, hints=hints, recommendation=rec,
                  cause={"object": f"{where}: {', '.join(_q(q) for q in quotes)}",
                         "condition": "размытая формулировка без измеримого критерия (ISO/IEC/IEEE 29148, 5.2.7)"})
        if c:
            out.append(c)
    return out


# =========================================================================== 2. RULE-OPEN-LIST
_OPEN_LIST = re.compile(
    r"(?<!\w)(?:и\s+т\.\s?д\.?|и\s+т\.\s?п\.?|и\s+др\.|и\s+пр\.|и\s+так\s+далее|и\s+тому\s+подобное"
    r"|и\s+далее|и\s+прочее|и\s+прочие|etc\.?|and\s+so\s+on)(?!\w)", re.I)


def _rule_open_list(ctx: _Ctx) -> list[dict]:
    """RULE-OPEN-LIST: открытые перечни «и т. д.», «и т. п.», «и др.», «и далее», «и прочее», «etc.».

    Цитата захватывает до трёх предшествующих элементов перечня. Один кандидат на блок.
    """
    out: list[dict] = []
    for b in ctx.blocks:
        if not _eligible(b):
            continue
        text = _text(b)
        ms = list(_OPEN_LIST.finditer(text))
        if not ms:
            continue
        hints, quotes, markers = [], [], []
        for m in ms:
            s0, _ = _sentence_at(text, m.start())
            floor = max(s0, max(text.rfind(ch, s0, m.start()) for ch in ";:—–") + 1)
            s = _back_words(text, m.start(), 3, floor)
            h = _hint(b, s, m.end())
            if h:
                hints.append(h)
                quotes.append(h["quote"])
                markers.append(m.group(0))
        if not hints:
            continue
        where = ctx.where(b)
        severity = "major" if ctx.req_of.get(b["id"]) else "minor"
        c = _make(ctx, rule_id="RULE-OPEN-LIST", kind="incomplete", criterion=("complete", "set_complete"),
                  severity=severity, title=f"Открытый перечень {_join_q(quotes)} в {where}",
                  impact="Перечень не закрыт: разработчик реализует только названные элементы, тестировщик не знает, "
                         "какие ещё случаи проверять, а приёмка не может доказать полноту.",
                  hints=hints,
                  recommendation=f"Вместо {_join_q(markers)} перечислить все элементы явно: "
                                 f"<уточнить: полный список> — "
                                 f"или задать правило, по которому элемент входит в перечень.",
                  cause={"object": f"{where}: перечень {_join_q(quotes)}", "condition": "открытый перечень"})
        if c:
            out.append(c)
    return out


# =========================================================================== 3. RULE-EMPTY-SECTION
_PLACEHOLDER_ONLY = re.compile(
    r"^\s*(?:[—–-]{1,3}|tbd|tba|todo|\?+|…|\.{3}|<[^<>]*>|заполня(?:ет|ют)ся\b.*|будет\s+\w+.*|будут\s+\w+.*"
    r"|не\s+заполнен\w*|в\s+разработке)\s*\.?\s*$", re.I | re.S)


def _level(b: dict) -> int:
    try:
        return int((b.get("loc") or {}).get("level") or 1)
    except (TypeError, ValueError):
        return 1


def _rule_empty_section(ctx: _Ctx) -> list[dict]:
    """RULE-EMPTY-SECTION: заголовок без содержания или с одной заглушкой («заполняются …», «TBD», «—»).

    Пусто — если сразу за заголовком идёт заголовок того же или более высокого уровня (или конец
    документа). Заглушки такого раздела помечаются, чтобы RULE-PLACEHOLDER не повторял их.
    """
    out: list[dict] = []
    n = len(ctx.blocks)
    for i, h in enumerate(ctx.blocks):
        if _kind(h) != "heading" or len(_text(h).strip()) < MIN_QUOTE:
            continue
        lvl = _level(h)
        j = i + 1
        content: list[dict] = []
        while j < n and _kind(ctx.blocks[j]) != "heading":
            content.append(ctx.blocks[j])
            j += 1
        has_sub = j < n and _level(ctx.blocks[j]) > lvl
        if has_sub:
            continue
        name = _text(h).strip()
        texts = [b for b in content if _text(b).strip()]
        if not texts and not content:
            c = _make(ctx, rule_id="RULE-EMPTY-SECTION", kind="incomplete", criterion=("complete", "set_complete"),
                      severity="minor", title=f"Пустой раздел {_q(name)}",
                      impact="Раздел есть в структуре, но без содержания: соответствующую часть нельзя реализовать "
                             "и проверить, а пробел легко принять за осознанное «не требуется».",
                      hints=[_whole(h)],
                      recommendation=f"Заполнить раздел {_q(name)}: <уточнить: содержание> — или удалить его и явно "
                                     f"указать «не применяется» с причиной.",
                      cause={"object": f"раздел {_q(name)}", "condition": "раздел без содержания"})
            if c:
                out.append(c)
            continue
        if texts and len(texts) == len(content) and all(
                _kind(b) in _PROSE_KINDS and _PLACEHOLDER_ONLY.match(_text(b)) for b in texts):
            hints = [_whole(b) for b in texts[:3]]
            quote = hints[0]["quote"] if hints and hints[0] else _text(texts[0])
            c = _make(ctx, rule_id="RULE-EMPTY-SECTION", kind="incomplete", criterion=("complete", "set_complete"),
                      severity="minor", title=f"Раздел {_q(name)} не заполнен: {_q(quote)}",
                      impact="Вместо содержания стоит заглушка: часть документа, на которую опираются разработка "
                             "и тестирование, отсутствует, а ответственность за её заполнение не зафиксирована.",
                      hints=hints,
                      recommendation=f"Заполнить раздел {_q(name)} до передачи в разработку: <уточнить: содержание "
                                     f"и ответственный>; если раздел не нужен — указать «не применяется» с причиной.",
                      cause={"object": f"раздел {_q(name)}", "condition": "вместо содержания заглушка"})
            if c:
                out.append(c)
                ctx.placeholder_done.update(b["id"] for b in texts)
    return out


# =========================================================================== 4. RULE-PLACEHOLDER
_PH_TOKEN = re.compile(r"(?<!\w)(?:TBD|TBA|TODO|FIXME|XXX)(?!\w)|\?{3,}|<\s*(?:\.{3}|…|[А-Яа-яЁё][^<>\n]{0,40})>"
                       r"|\[(?:TBD|TODO|уточнить|заполнить)[^\]\n]{0,40}\]")
_PH_LABEL_DASH = re.compile(r"(?<![\w-])([A-Za-zА-Яа-яЁё][\w./-]{0,30})\s*:\s*[—–](?=\s*(?:$|[.;,)|\n]))")
_PH_PHRASE = re.compile(
    r"(?<!\w)(?:будет|будут)\s+(?:уточн|заполн|определ|добавл|описан|согласова|предоставл)\w*"
    r"|(?<!\w)уточня(?:ет|ют)ся(?!\w)"
    r"|(?<!\w)заполня(?:ет|ют)ся\s+(?:позже|потом|тестировщик\w*|аналитик\w*|разработчик\w*|архитектор\w*"
    r"|ответственн\w*|на\s+этапе|в\s+процессе|после)"
    r"|(?<!\w)не\s+(?:заполнен|проставлен)\w*"
    r"|(?<!\w)to\s+be\s+(?:defined|determined|confirmed|added|specified)(?!\w)", re.I)
_PH_CONDITIONAL = re.compile(r"(?<!\w)(?:если|когда|при|в\s+случае|if|when|unless|иначе|либо)(?!\w)", re.I)
_PH_OPTIONS = re.compile(r"^(?:да|нет|yes|no)(?:\s*/\s*(?:да|нет|не\s+требуется|не\s+применимо|yes|no|n/?a))+$",
                         re.I)
_PH_CELL = re.compile(r"^(?:TBD|TBA|TODO|FIXME|XXX|\?+|\.{3}|…|<[^<>]*>)$")
_PH_DASH_CELL = re.compile(r"^[—–-]{1,3}$")


def _rule_placeholder(ctx: _Ctx) -> list[dict]:
    """RULE-PLACEHOLDER: заглушки и незаполненный шаблон, один кандидат на раздел (до 6 подсказок).

    Ищет «TBD/TODO/???/XXX/<…>», «Поле: —», прочерк в значении таблицы «ключ | значение»,
    «заполняются …», «будет уточнено», «не заполнен/не проставлены» (кроме условий «если … не заполнено»),
    неотмеченные варианты «Да / Нет / Не требуется» и полностью пустые строки таблиц (подсказка — шапка
    таблицы или заголовок раздела). Прочерки в многоколоночных таблицах считаются «не применяется».
    """
    hits: dict[tuple, list[dict]] = {}   # раздел -> [{block, s, e, label, strong}]
    order: list[tuple] = []

    def add(b: dict, s: int, e: int, label: str, strong: bool = False) -> None:
        key = tuple(_section(b))
        if key not in hits:
            hits[key] = []
            order.append(key)
        hits[key].append({"block": b, "s": s, "e": e, "label": label, "strong": strong})

    for t in ctx.tables():
        ncols = len(t["columns"]) or max((len(_cells(_text(r))) for r in t["rows"] if _text(r)), default=0)
        empty_rows = []
        for r in t["rows"]:
            if r["id"] in ctx.placeholder_done:
                continue
            text = _text(r)
            if not text.strip() or (r.get("loc") or {}).get("empty"):
                empty_rows.append(r)
                continue
            spans = _cells(text)
            opt = [(s, e) for s, e in spans if e > s and _PH_OPTIONS.match(text[s:e])]
            if opt:
                add(r, opt[0][0], opt[-1][1], "options")
            for k, (s, e) in enumerate(spans):
                cell = text[s:e]
                if _PH_CELL.match(cell) or (k >= 1 and ncols == 2 and _PH_DASH_CELL.match(cell)):
                    s0 = spans[0][0] if k >= 1 and e - spans[0][0] <= MAX_QUOTE else s
                    add(r, s0, e, "cell")
        if empty_rows:
            anchor = t["header"] or ctx.heading_for(t["rows"][0])
            if anchor is not None:
                key = tuple(_section(t["rows"][0]))
                if key not in hits:
                    hits[key] = []
                    order.append(key)
                hits[key].append({"block": anchor, "s": 0, "e": len(_text(anchor)), "label": "empty",
                                  "strong": False, "count": len(empty_rows)})

    for b in ctx.blocks:
        if _kind(b) not in _PROSE_KINDS or b["id"] in ctx.placeholder_done:
            continue
        text = _text(b)
        if not text.strip():
            continue
        strong_ctx = _kind(b) in ("list_item", "paragraph") and bool(ctx.req_of.get(b["id"]))
        for m in _PH_TOKEN.finditer(text):
            add(b, _back_words(text, m.start(), 2, _clause_start(text, m.start())), m.end(), "token", strong_ctx)
        if _kind(b) != "table_row":
            for m in _PH_LABEL_DASH.finditer(text):
                add(b, m.start(), m.end(), "token")
        else:
            for m in _PH_LABEL_DASH.finditer(text):
                spans = _cells(text)
                if not any(s <= m.start() and m.end() <= e and _PH_DASH_CELL.match(text[s:e]) for s, e in spans):
                    add(b, m.start(), m.end(), "token")
        for m in _PH_PHRASE.finditer(text):
            low = m.group(0).lower()
            s0, _ = _sentence_at(text, m.start())
            if low.startswith("не") and _PH_CONDITIONAL.search(text[s0:m.start()]):
                continue
            start = _clause_start(text, m.start())
            if m.start() - start > 60:
                start = _back_words(text, m.start(), 3, start)
            strong = strong_ctx and (low.startswith("будет") or low.startswith("будут") or low.startswith("уточня"))
            add(b, start, m.end(), "phrase", strong)

    out: list[dict] = []
    for key in order:
        items = sorted(hits[key], key=lambda x: (ctx.pos[x["block"]["id"]], x["s"]))
        # по одному на тип в начале, затем по порядку документа
        picked: list[dict] = []
        seen_labels: set[str] = set()
        for it in items:
            if it["label"] not in seen_labels:
                picked.append(it)
                seen_labels.add(it["label"])
        for it in items:
            if len(picked) >= MAX_HINTS:
                break
            if it not in picked:
                picked.append(it)
        picked.sort(key=lambda x: (ctx.pos[x["block"]["id"]], x["s"]))
        hints = [_hint(it["block"], it["s"], it["e"]) for it in picked[:MAX_HINTS]]
        n_opts = sum(1 for it in items if it["label"] == "options")
        n_empty = sum(it.get("count", 0) for it in items if it["label"] == "empty")
        labels: list[str] = []
        for it, h in zip(picked, hints):
            if it["label"] == "options":
                lab = f"варианты «Да / Нет» без выбора ({n_opts} строк)"
            elif it["label"] == "empty":
                lab = f"пустые строки таблицы ({n_empty})"
            else:
                lab = _q(h["quote"]) if h else ""
            if lab and lab not in labels:
                labels.append(lab)
        sec = key[-1] if key else "документ"
        template = _is_template(key)
        if template:
            title = f"Шаблон {_q(sec)} не заполнен: " + ", ".join(labels[:3])
            impact = ("Обязательная часть шаблона пуста: нельзя подтвердить, что документ прошёл ревью и "
                      "согласование, ответственность за решения не зафиксирована.")
            rec = ("Заполнить шаблон: проставить отметки с обоснованием и ссылками на замечания, указать версию, "
                   "дату и согласующих (<уточнить: ФИО, подразделение>).")
        else:
            title = f"Незаполненные поля в разделе {_q(sec)}: " + ", ".join(labels[:3])
            impact = ("Значения, нужные для реализации и проверки, не указаны: их придётся выяснять вне документа, "
                      "а разные команды заполнят пробел по-своему.")
            rec = ("Указать значения вместо заглушек (" + ", ".join(labels[:3]) + "): <уточнить: значение> — или явно "
                   "написать «не применяется» с причиной.")
        severity = "major" if any(it["strong"] for it in items) else "minor"
        c = _make(ctx, rule_id="RULE-PLACEHOLDER", kind="placeholder", criterion=("complete", "set_complete"),
                  severity=severity, title=title, impact=impact, hints=hints, recommendation=rec,
                  cause={"object": f"раздел {_q(sec)}", "condition": "заглушки и незаполненные поля"})
        if c:
            out.append(c)
    return out


# =========================================================================== 5. RULE-TZ
_TOD = re.compile(r"(?<![\d:.,])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:])")
_DATE_BOUND = re.compile(
    r"(?<!\w)(?:календарн\w*\s+(?:месяц|д[ен]\w*|недел\w*|год\w*|сут\w*|квартал\w*)"
    r"|(?:конец|конца|концу|начало|начала|началу)\s+(?:дня|суток|месяца|года)"
    r"|полноч\w*|операционн\w*\s+д(?:ень|ня|ню)|по\s+дате\s+\w+"
    r"|дат[аеуы]\s+(?:совершения|проведения|операции|покупки|списания|платежа)"
    r"|end\s+of\s+(?:day|month)|calendar\s+(?:day|month|week)|midnight)(?!\w)", re.I)
_ZONE_EXPLICIT = re.compile(
    r"(?<!\w)(?:UTC|GMT)\s*[+−-]\s*\d{1,2}(?::?\d{2})?|(?<!\w)UTC(?!\w)"
    r"|(?<!\w)(?:Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific|Etc)/[A-Z][A-Za-z_+-]+"
    r"|(?<![\d:])[+−]\d{2}:\d{2}(?!\d)")
_ZONE_LOCAL = re.compile(
    r"(?<!\w)(?:по|в)\s+(?:Алматы|Алма-Ат\w+|Астан\w+|Нур-Султан\w*|Москв\w+|Ташкент\w*|Бишкек\w*|Минск\w*"
    r"|Шымкент\w*|Караганд\w+|Актоб\w+|Атырау|Актау|Павлодар\w*|Костана\w+|Киев\w*|Лондон\w*|Нью-Йорк\w*)(?!\w)"
    r"|(?<!\w)(?:московск|местн|серверн)\w*\s+времен\w*|(?<!\w)времен\w*\s+сервера"
    r"|(?<!\w)по\s+времени\s+[А-ЯЁ][\w-]+|(?<!\w)(?:local|server)\s+time(?!\w)", re.I)
_ZONE_GLOBAL = re.compile(r"(?<!\w)(?:вс[её]\s+(?:врем|дат|значени|срок)|времена|часов\w*\s+пояс|time\s*zone|"
                          r"all\s+times)", re.I)
_TIME_PREP = frozenset("в во за до с со после к по на около at by before after until".split())


def _rule_tz(ctx: _Ctx) -> list[dict]:
    """RULE-TZ: время суток и границы периода без явного пояса (UTC±hh:mm или IANA-зона).

    Время «23:58», «календарный месяц», «в течение суток», «по дате совершения» с названием города
    («по Алматы») или без пояса — неоднозначность. Явный пояс в том же требовании или общее правило
    «все времена в UTC+…» снимают замечание. Один кандидат на документ, несколько подсказок.
    """
    for b in ctx.blocks:
        # явный пояс где-либо в тексте требований задаёт базу времени документа: остаточная неоднозначность
        # слишком слаба для правила (её оценивает модель)
        if _kind(b) in _PROSE_KINDS and _ZONE_EXPLICIT.search(_text(b)):
            return []
    spans: list[tuple[dict, int, int]] = []
    for b in ctx.blocks:
        if not _eligible(b):
            continue
        text = _text(b)
        rids = ctx.req_of.get(b["id"], [])
        scope_text = "\n".join(ctx.req_text(r) for r in rids) if rids else text
        if _ZONE_EXPLICIT.search(scope_text):
            continue
        bounds = [(m.start(), m.end()) for m in _TOD.finditer(text)] + \
                 [(m.start(), m.end()) for m in _DATE_BOUND.finditer(text)
                  # в строках таблиц «Дата операции» — обычно описание поля, а не правило границы периода
                  if not (_kind(b) == "table_row" and re.match(r"по\s+дате|дат", m.group(0), re.I))
                  # «30 календарных дней» — длительность, а не граница периода
                  and not re.search(r"\d\s*$", text[:m.start()].rstrip()[-8:] + " ")]
        locals_ = [(m.start(), m.end()) for m in _ZONE_LOCAL.finditer(text)]
        if not bounds and not locals_:
            continue
        if not bounds:
            continue  # город без времени и без границы периода — не про пояс
        bounds.sort()
        used: set[int] = set()
        found: list[tuple[int, int]] = []
        for ls, le in locals_:
            best = None
            for k, (bs, be) in enumerate(bounds):
                if be <= ls and ls - be <= 40 and _sentence_at(text, bs) == _sentence_at(text, ls):
                    best = k
            if best is not None:
                used.add(best)
                found.append((bounds[best][0], le))
            elif any(bs <= ls <= be + 40 for bs, be in bounds):
                found.append((ls, le))
        for k, (bs, be) in enumerate(bounds):
            if k in used:
                continue
            prev = _word_start(text, bs)
            if prev < bs and text[prev:bs].strip().lower() in _TIME_PREP:
                bs = prev
            found.append((bs, be))
        found.sort()
        last_end = -1
        for s, e in found:
            if s < last_end:
                continue
            spans.append((b, s, e))
            last_end = e
    if not spans:
        return []
    hints = [_hint(b, s, e) for b, s, e in spans[:MAX_HINTS]]
    quotes = [h["quote"] for h in hints if h]
    c = _make(ctx, rule_id="RULE-TZ", kind="ambiguity", criterion="unambiguous", severity="minor",
              title=f"Время и границы периода без явного часового пояса: {_join_q(quotes)}",
              impact="Граница суток или месяца зависит от пояса: операции около полуночи попадут в разные периоды "
                     "у разных сервисов, а тест на стыке периодов нельзя однозначно оценить.",
              hints=hints,
              recommendation="Для каждого времени и границы периода указать смещение и IANA-зону (<уточнить: "
                             "UTC+hh:mm, Region/City>) вместо названия города или умолчания; определить, по какой "
                             "отметке времени события считается период.",
              cause={"object": "часовой пояс времени и границ периода",
                     "condition": "пояс не указан или задан городом"})
    return [c] if c else []


# =========================================================================== API: методы и пути
_METHOD_KEY = re.compile(r"^(?:rest\s*type|http[\s-]*method|request\s+method|method|метод(?:\s+http)?|http[\s-]*метод"
                         r"|тип\s+запроса|verb)$", re.I)
_URL_KEY = re.compile(r"^(?:request\s+url|url|uri|endpoint|end-?point|path|адрес(?:\s+метода)?|ресурс|маршрут|route"
                      r"|эндпоинт)$", re.I)
_DESC_KEY = re.compile(r"^(?:description|описание|назначение|summary|operation|операция)$", re.I)
_HTTP_METHOD = re.compile(r"(?<![A-Za-z])(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)(?![A-Za-z])")
_PATH_RE = re.compile(r"(?<![\w$}/.])(/[A-Za-z0-9_{}.:-]*[A-Za-z0-9_}](?:/[A-Za-z0-9_{}.:-]*[A-Za-z0-9_}])*)")
_URL_RE = re.compile(r"(?:https?://[^\s/\"'|]+|\$\{?\w+\}?)(/[^\s\"'?#|]*[A-Za-z0-9_}])")
_INLINE_EP = re.compile(r"(?<![A-Za-z])(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?:https?://[^\s/\"']+|\$\{?\w+\}?)?"
                        r"(/[^\s\"'?#),;|]*[A-Za-z0-9_}])")
_CURL = re.compile(r"curl\b[^\n]*")

_EN_WRITE = frozenset("save create update set add delete remove insert edit change modify put patch upsert reset "
                      "enable disable cancel block unblock activate deactivate register submit send transfer pay "
                      "write store assign approve reject confirm".split())
_EN_READ = frozenset("get read list fetch find search load show view query retrieve lookup".split())
_RU_WRITE = re.compile(r"(?<!\w)(?:сохран|изменени|измен(?:ить|яет|ять)|создани|созда(?:ть|ёт|ет)|удалени"
                       r"|удал(?:ить|яет)"
                       r"|добавлени|добав(?:ить|ляет)|обновлени|обнов(?:ить|ляет)|установк|установ(?:ить|ливает)"
                       r"|редактирован|отмен[аияу])\w*", re.I)


def _path_words(path: str) -> list[str]:
    words: list[str] = []
    for seg in path.split("/"):
        if not seg or seg.startswith(("{", ":")):
            continue
        for part in re.split(r"[_\-.{}:]+", seg):
            words += [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", part)]
    return words


def _endpoints(ctx: _Ctx) -> list[dict]:
    """Методы API: таблицы «ключ | значение» (REST type/Method + Request URL), таблицы с колонками
    «Метод/URL», строки «GET /path» и вызовы curl. Подсказки — (блок, начало, конец)."""
    if ctx._endpoints is not None:
        return ctx._endpoints
    eps: list[dict] = []

    def add(path: str, method: Optional[str], ph: tuple, mh: Optional[tuple], dh: Optional[tuple], src: str):
        eps.append({"path": path, "method": method, "path_hint": ph, "method_hint": mh, "desc_hint": dh,
                    "src": src})

    for t in ctx.tables():
        cols = [c.strip() for c in t["columns"]]
        mcol = next((i for i, c in enumerate(cols) if _METHOD_KEY.match(c)), None)
        ucol = next((i for i, c in enumerate(cols) if _URL_KEY.match(c)), None)
        dcol = next((i for i, c in enumerate(cols) if _DESC_KEY.match(c)), None)
        if mcol is not None and ucol is not None:
            for r in t["rows"]:
                text = _text(r)
                spans = _cells(text)
                if len(spans) <= max(mcol, ucol):
                    continue
                ms, me = spans[mcol]
                mm = _HTTP_METHOD.search(text, ms, me)
                us, ue = spans[ucol]
                for pm in _PATH_RE.finditer(text, us, ue):
                    dh = (r, *spans[dcol]) if dcol is not None and dcol < len(spans) else None
                    add(pm.group(1), mm.group(1) if mm else None, (r, pm.start(1), pm.end(1)),
                        (r, mm.start(1), mm.end(1)) if mm else None, dh, "table")
            continue
        method, mh, dh = None, None, None
        paths: list[tuple[str, tuple]] = []
        for r in t["rows"]:
            text = _text(r)
            spans = _cells(text)
            if len(spans) < 2:
                continue
            key = text[spans[0][0]:spans[0][1]].strip()
            vs, ve = spans[1][0], spans[-1][1]
            if _METHOD_KEY.match(key):
                mm = _HTTP_METHOD.search(text, vs, ve)
                if mm and method is None:
                    method, mh = mm.group(1), (r, spans[0][0], mm.end(1))
            elif _URL_KEY.match(key):
                for pm in list(_URL_RE.finditer(text, vs, ve)) + list(_PATH_RE.finditer(text, vs, ve)):
                    paths.append((pm.group(1), (r, pm.start(1), pm.end(1))))
            elif _DESC_KEY.match(key) and dh is None:
                dh = (r, vs, ve)
        seen: set[str] = set()
        for p, ph in paths:
            if p in seen:
                continue
            seen.add(p)
            add(p, method, ph, mh, dh, "table")

    for b in ctx.blocks:
        if _kind(b) == "table_header":
            continue
        text = _text(b)
        for m in _INLINE_EP.finditer(text):
            s0, e0 = _sentence_at(text, m.start())
            add(m.group(2), m.group(1), (b, m.start(2), m.end(2)), (b, m.start(1), m.end(2)), (b, s0, e0), "inline")
        for m in _CURL.finditer(text):
            line, base = m.group(0), m.start()
            x = re.search(r"\s(?:-X|--request)\s*([A-Za-z]+)", line)
            g = re.search(r"\s(?:-G|--get)(?!\S)", line)
            if x:
                method, mh = x.group(1).upper(), (b, base, base + x.end())
            elif g:
                method, mh = "GET", (b, base, base + g.end())
            elif re.search(r"\s(?:-d|--data[\w-]*|-F|--form)(?!\S)", line):
                method, mh = "POST", None
            else:
                method, mh = "GET", None
            u = _URL_RE.search(line) or re.search(r"\s[\"']?(/[^\s\"'?#]*[A-Za-z0-9_}])", line)
            if u:
                add(u.group(1), method, (b, base + u.start(1), base + u.end(1)), mh, None, "curl")
    ctx._endpoints = eps
    return eps


def _span_hint(span: Optional[tuple]) -> Optional[dict]:
    return _hint(span[0], span[1], span[2]) if span else None


# =========================================================================== 6. RULE-HTTP-SEMANTICS
def _rule_http_semantics(ctx: _Ctx) -> list[dict]:
    """RULE-HTTP-SEMANTICS: изменяющая операция (save/create/update/delete…, «сохранение», «изменение»)
    объявлена через безопасный метод GET/HEAD (RFC 9110, 9.2.1). Одна находка на путь, подсказки —
    метод и путь."""
    out: list[dict] = []
    by_path: dict[str, list[dict]] = {}
    for ep in _endpoints(ctx):
        by_path.setdefault(ep["path"], []).append(ep)
    for path, eps in by_path.items():
        safe = [e for e in eps if e["method"] in ("GET", "HEAD")]
        if not safe:
            continue
        words = _path_words(path)
        write = [w for w in words if w in _EN_WRITE]
        read = [w for w in words if w in _EN_READ]
        # Глагол изменения в описании: ячейка Description таблицы или сказуемое сразу после «GET /path»
        # (до первой запятой — чтобы «…, сохранённый методом POST» не считался описанием этого метода).
        desc_hit: Optional[tuple[dict, int, int]] = None
        for e in safe:
            if not e["desc_hint"]:
                continue
            blk, ds, de = e["desc_hint"]
            if e["src"] == "inline":
                ds = e["path_hint"][2]
                stop = re.search(r"[,;(]", _text(blk)[ds:de])
                de = ds + stop.start() if stop else de
            m = _RU_WRITE.search(_text(blk), ds, de)
            if m:
                desc_hit = (blk, m.start(), m.end())
                break
        if read and not write:
            continue
        if not write and not desc_hit:
            continue
        method = safe[0]["method"]
        first = sorted(safe, key=lambda e: {"table": 0, "curl": 1, "inline": 2}[e["src"]])[0]
        mh = _span_hint(first["method_hint"]) or _span_hint(next((e["method_hint"] for e in safe
                                                                   if e["method_hint"]), None))
        ph = _span_hint(first["path_hint"])
        hints = [mh, ph]
        if not write and desc_hit:
            hints.append(_hint(*desc_hit))
        what = ", ".join(dict.fromkeys(write)) or _text(desc_hit[0])[desc_hit[1]:desc_hit[2]].lower()
        c = _make(ctx, rule_id="RULE-HTTP-SEMANTICS", kind="incorrect", criterion="correct", severity="major",
                  title=f"Метод {method} для изменяющей операции {_q(path)}",
                  impact=f"{method} по RFC 9110 — безопасный метод: прокси, кэши, предзагрузка и повторы могут "
                         f"выполнить "
                         f"изменение повторно или без ведома клиента; параметры уходят в строку запроса и оседают "
                         f"в логах веб-серверов и прокси (риск ИБ для идентификаторов и персональных данных).",
                  hints=hints,
                  recommendation=f"Заменить {method} на POST (или PUT/PATCH для идемпотентной замены), параметры "
                                 f"передавать в теле запроса; для чтения выделить отдельный GET-метод. "
                                 f"<уточнить: итоговый метод и URL для {path}>.",
                  cause={"object": f"HTTP-метод {path}", "condition": f"операция «{what}» через {method}"})
        if c:
            out.append(c)
    return out


# =========================================================================== 7. RULE-BODY-CONTENT-TYPE
_CT_DECL = re.compile(r"Content-Type\s*[:=]?\s*([A-Za-z]+/[\w.+-]+)", re.I)
_BODY_NONE = re.compile(
    r"(?<!\w)(?:тело(?:\s+запроса)?\s+(?:не\s+(?:используется|передаётся|передается|требуется|предусмотрено"
    r"|заполняется)|отсутствует|пустое)|без\s+тела(?:\s+запроса)?"
    r"|(?:request\s+)?body\s+(?:is\s+)?(?:not\s+(?:used|required|sent)|empty|absent)|no\s+(?:request\s+)?body)(?!\w)",
    re.I)


def _rule_body_content_type(ctx: _Ctx) -> list[dict]:
    """RULE-BODY-CONTENT-TYPE: объявлен Content-Type, а рядом сказано, что тело запроса не используется."""
    out: list[dict] = []
    decls = [(b, m) for b in ctx.blocks if _kind(b) != "heading" for m in _CT_DECL.finditer(_text(b))]
    for b in ctx.blocks:
        if _kind(b) not in _PROSE_KINDS:
            continue
        m = _BODY_NONE.search(_text(b))
        if not m:
            continue
        sec = _section(b)
        near = [(db, dm) for db, dm in decls if _section(db) == sec] or \
               [(db, dm) for db, dm in decls if abs(ctx.pos[db["id"]] - ctx.pos[b["id"]]) <= 3]
        if not near:
            continue
        db, dm = near[0]
        ct = dm.group(1)
        wa = {"input": f"Клиент формирует запрос по описанию раздела {_q(_sec_name(b))}",
              "outcome_a": f"передаёт тело с заголовком Content-Type: {ct}",
              "outcome_b": "отправляет запрос без тела",
              "hint_a": _hint(db, dm.start(), dm.end()), "hint_b": _hint(b, m.start(), m.end())}
        c = _make(ctx, rule_id="RULE-BODY-CONTENT-TYPE", kind="conflict", criterion=_conflict_criterion(),
                  severity="minor", title=f"Content-Type {_q(ct)} указан, хотя тело запроса не используется",
                  impact="Клиент и сервер по-разному поймут формат запроса: одни отправят JSON в теле, другие — "
                         "параметры в строке запроса; сервер может отвергнуть запрос из-за заголовка "
                         "или игнорировать тело.",
                  hints=[], witness=wa,
                  recommendation="Оставить один вариант: описать тело запроса (схема JSON) вместе с Content-Type — или "
                                 "убрать Content-Type и указать, что параметры передаются <уточнить: в строке запроса "
                                 "или в теле>.",
                  cause={"object": f"тело запроса ({_sec_name(b)})", "condition": "Content-Type при отсутствии тела",
                         "outcomes": [wa["outcome_a"], wa["outcome_b"]]})
        if c:
            out.append(c)
    return out


# =========================================================================== 8. RULE-STATUS-*
_STD_PHRASE = {
    "200": "OK", "201": "Created", "202": "Accepted", "204": "No Content", "400": "Bad Request",
    "401": "Unauthorized", "403": "Forbidden", "404": "Not Found", "405": "Method Not Allowed", "409": "Conflict",
    "422": "Unprocessable Content", "429": "Too Many Requests", "500": "Internal Server Error", "502": "Bad Gateway",
    "503": "Service Unavailable", "504": "Gateway Timeout",
}
_REASON_RES = tuple((code, re.compile(rx, flags)) for code, rx, flags in (
    ("200", r"(?<![A-Za-z])OK(?![A-Za-z])", 0), ("201", r"\bcreated\b", re.I), ("202", r"\baccepted\b", re.I),
    ("204", r"\bno\s+content\b", re.I), ("400", r"\bbad\s+request\b", re.I),
    ("401", r"\bunauthori[sz]ed\b", re.I), ("403", r"\bforbidden\b", re.I), ("404", r"\bnot\s+found\b", re.I),
    ("405", r"\bmethod\s+not\s+allowed\b", re.I), ("409", r"\bconflict\b", re.I),
    ("422", r"\bunprocessable\b", re.I), ("429", r"\btoo\s+many\s+requests\b", re.I),
    ("500", r"\binternal\s+server\s+error\b", re.I), ("502", r"\bbad\s+gateway\b", re.I),
    ("503", r"\bservice\s+unavailable\b", re.I), ("504", r"\bgateway\s+time-?out\b", re.I),
))
_STATUS_CTX = re.compile(r"статус|status|код\w*\s+ответ|ответ|response|ошибк|error|http", re.I)
_STATUS_DESC = re.compile(r"ответ|response|ошибк|error|успешн|success|запрос|request|доступ|авториз|найден|found|"
                          r"forbidden|unauthori|ok\b|created", re.I)
_HEAD_CODE = re.compile(r"^\s*(?:HTTP\s*|код\s+|code\s+|status\s+|статус\s+|ответ\s+|response\s+)?([1-5]\d\d)(?!\d)"
                        r"\s*(?:[.:)\]—–-]\s*)?(.*)$", re.I)
# Зарегистрированные HTTP-коды (RFC 9110 и распространённые расширения): бизнес-коды вроде «код 105» не трогаем.
_HTTP_KNOWN = frozenset(
    "100 101 102 103 200 201 202 203 204 205 206 207 208 226 300 301 302 303 304 305 307 308 400 401 402 403 404 405 "
    "406 407 408 409 410 411 412 413 414 415 416 417 418 421 422 423 424 425 426 428 429 431 451 500 501 502 503 504 "
    "505 506 507 508 510 511".split())
_LINE_DEF = re.compile(r"^\s*(?:[A-Za-zА-Яа-яЁё]{1,8}-\d+[.:)]?\s+)?(?:HTTP\s*|код\s+|code\s+)?([1-5]\d\d)(?!\d)"
                       r"(?:\s+[A-Za-z][A-Za-z ]{1,30}?)?\s*[.:)—–-]\s*(\S.*)$", re.I)
_RETURNED = re.compile(r"(?<!\w)(?:возвра\w*|вернуть|верн[её]т\w*|return\w*|respond\w*|отда[её]т\w*|ответ(?:ом|а)?"
                       r"|код(?:ом|а)?(?:\s+ответа)?|статус(?:ом|а)?|HTTP)[\s:]*"
                       r"(?:код(?:ом)?\s+|статус(?:ом)?\s+|HTTP[\s-]*)?"
                       r"([1-5]\d\d)(?![\d\w])", re.I)
_CODE = re.compile(r"(?<![\d\w.,])(?<!\d )([1-5]\d\d)(?![\d\w])(?! \d{3})")
_UNIT_AFTER = re.compile(r"^\s*(?:₸|тг|тенге|тиын|руб|₽|\$|€|%|мс|ms|сек|с\b|мин|час|KZT|USD|EUR|RUB|тыс|млн|бит|bit|"
                         r"байт|byte|символ|знак|шт|раз)", re.I)
_SUMMARY_WORD = re.compile(r"(?<!\w)(?:успешн|неуспешн|success|fail|ошибочн|error)", re.I)
_ERR_VALUE = re.compile(r"\"[^\"\n]{1,40}\"\s*:\s*\"[^\"\n]*(?:ERROR|Error|error|FAIL|Fail|fail|ошибк)[^\"\n]*\""
                        r"|\"(?:status|code|httpStatus|statusCode)\"\s*:\s*\"?[45]\d\d")
_INVALID_INPUT = re.compile(r"неверн|некоррект|невалид|недопустим|ошибк\w*\s+(?:валидац|ввода|параметр)|invalid|"
                            r"bad\s+request|validation|не\s+прош\w*\s+проверк|unprocessable", re.I)


def _status_model(ctx: _Ctx) -> dict:
    """Определения статусов (заголовки, строки «NNN. описание», строки таблиц) и разделы-заголовки кодов."""
    defs: dict[str, list[dict]] = {}
    headings: list[dict] = []
    for i, b in enumerate(ctx.blocks):
        text = _text(b)
        k = _kind(b)
        sec = " / ".join(_section(b))
        if k == "heading":
            m = _HEAD_CODE.match(text)
            if m and (_STATUS_CTX.search(sec) or _STATUS_CTX.search(m.group(2) or "")
                      or any(rx.search(m.group(2) or "") for _, rx in _REASON_RES)
                      or re.search(r"success|успешн", m.group(2) or "", re.I)):
                d = {"code": m.group(1), "block": b, "s": 0, "e": len(text), "desc": m.group(2) or "",
                     "kind": "heading", "index": i}
                defs.setdefault(m.group(1), []).append(d)
                headings.append(d)
            continue
        if k in ("paragraph", "list_item", "quote"):
            pos = 0
            for line in text.split("\n"):
                m = _LINE_DEF.match(line)
                if m and len(m.group(2).split()) >= 2 and not _UNIT_AFTER.match(line[m.end(1):]) and (
                        _STATUS_CTX.search(sec) or _STATUS_DESC.search(m.group(2))):
                    s = pos + len(line) - len(line.lstrip())
                    defs.setdefault(m.group(1), []).append(
                        {"code": m.group(1), "block": b, "s": s, "e": pos + len(line.rstrip()),
                         "desc": m.group(2), "kind": "line", "index": i})
                pos += len(line) + 1
        elif k == "table_row":
            spans = _cells(text)
            cols = " ".join(str(c) for c in (b.get("loc") or {}).get("columns") or [])
            if spans:
                first = text[spans[0][0]:spans[0][1]]
                m = re.match(r"^(?:HTTP\s*)?([1-5]\d\d)$", first)
                if m and (re.search(r"код|code|status|статус|http", cols, re.I) or _STATUS_CTX.search(sec)):
                    defs.setdefault(m.group(1), []).append(
                        {"code": m.group(1), "block": b, "s": spans[0][0], "e": spans[-1][1],
                         "desc": text[spans[-1][0]:spans[-1][1]], "kind": "row", "index": i})
    return {"defs": defs, "headings": headings}


def _heading_body(ctx: _Ctx, index: int) -> list[dict]:
    out = []
    for b in ctx.blocks[index + 1:]:
        if _kind(b) == "heading":
            break
        out.append(b)
    return out


def _rule_status(ctx: _Ctx) -> list[dict]:
    """RULE-STATUS-*: согласованность HTTP-статусов (100–599) в заголовках, списках и тексте.

    * UNDEFINED — код упомянут как возвращаемый («возвращается 404»), но нигде не описан;
    * SUMMARY — код назван в сводке («200 или 201 — успешный»), но не описан;
    * REASON — фраза в заголовке принадлежит другому коду («200 … Created») или другому классу;
    * EXAMPLE — пример тела под 2xx содержит ошибку, хотя для неверных данных описан 4xx;
    * HEADING-BODY — под заголовком кода X текст говорит, что возвращается Y.
    """
    model = _status_model(ctx)
    defs, headings = model["defs"], model["headings"]
    if not defs:
        return []
    out: list[dict] = []
    flagged_codes: set[str] = set()

    # --- HEADING-BODY (e)
    body_conflicts: list[tuple[dict, dict, re.Match]] = []
    for h in headings:
        for b in _heading_body(ctx, h["index"]):
            if _kind(b) not in _PROSE_KINDS:
                continue
            for m in _RETURNED.finditer(_text(b)):
                y = m.group(1)
                if y != h["code"] and y in _HTTP_KNOWN and not _UNIT_AFTER.match(_text(b)[m.end():]):
                    body_conflicts.append((h, b, m))
                    break
    # --- UNDEFINED (a)
    for b in ctx.blocks:
        if _kind(b) not in _PROSE_KINDS:
            continue
        text = _text(b)
        for m in _RETURNED.finditer(text):
            y = m.group(1)
            if y in defs or y in flagged_codes or y not in _HTTP_KNOWN or _UNIT_AFTER.match(text[m.end():]):
                continue
            flagged_codes.add(y)
            more = [(bb, mm) for bb in ctx.blocks if _kind(bb) in _PROSE_KINDS
                    for mm in _RETURNED.finditer(_text(bb)) if mm.group(1) == y]
            hints = [_hint(bb, mm.start(), mm.end()) for bb, mm in more[:3]]
            c = _make(ctx, rule_id="RULE-STATUS-UNDEFINED", kind="incomplete", criterion=("complete", "set_complete"),
                      severity="major", title=f"Код {y} возвращается по тексту, но не описан среди статусов",
                      impact="Клиент не знает смысл и формат ответа: обработка кода будет реализована по догадке "
                             "или не будет реализована, у теста нет ожидаемого результата.",
                      hints=hints,
                      recommendation=f"Добавить в список статусов код {y}: условие, тело ответа и пример "
                                     f"(<уточнить: формат тела>) — или заменить упоминание на уже описанный код.",
                      cause={"object": f"HTTP-статус {y}", "condition": "упомянут как ответ, но не описан"})
            if c:
                out.append(c)
    # --- SUMMARY (b)
    for b in ctx.blocks:
        if _kind(b) not in _PROSE_KINDS:
            continue
        text = _text(b)
        for s, e in _sentences(text):
            sent = text[s:e]
            if not _SUMMARY_WORD.search(sent):
                continue
            codes = [(m.group(1), s + m.start(1), s + m.end(1)) for m in _CODE.finditer(sent)
                     if m.group(1) in _HTTP_KNOWN and not _UNIT_AFTER.match(sent[m.end():])]
            if not codes or (len(codes) < 2 and not re.search(r"результат|result|код|code|статус|status|ответ",
                                                              sent, re.I)):
                continue
            missing = [c for c in codes if c[0] not in defs and c[0] not in flagged_codes]
            if not missing:
                continue
            for c0 in missing:
                flagged_codes.add(c0[0])
            names = list(dict.fromkeys(c[0] for c in missing))
            hs = _hint(b, s, missing[-1][2])
            word = "Коды" if len(names) > 1 else "Код"
            c = _make(ctx, rule_id="RULE-STATUS-SUMMARY", kind="incomplete", criterion=("complete", "set_complete"),
                      severity="minor",
                      title=f"{word} {', '.join(names)} назван{'ы' if len(names) > 1 else ''} в сводке результатов, "
                            f"но нигде не описан{'ы' if len(names) > 1 else ''}",
                      impact="Неясно, может ли сервер вернуть этот код: клиент либо не обработает его, либо будет "
                             "ждать ответ, которого не бывает; тесты не знают, что проверять.",
                      hints=[hs],
                      recommendation=f"Описать {', '.join(names)}: когда возвращается, тело и пример "
                                     f"(<уточнить: условие и формат>) — или убрать из сводки.",
                      cause={"object": f"HTTP-статус {', '.join(names)}", "condition": "назван в сводке, но не описан"})
            if c:
                out.append(c)
    # --- REASON (c)
    for h in headings:
        code, rest = h["code"], h["desc"]
        found = [c for c, rx in _REASON_RES if rx.search(rest)]
        bad_class = None
        if code.startswith("2") and re.search(r"\bunsuccessful\b|\berror\b|\bfail\w*|ошибк|неуспеш", rest, re.I):
            bad_class = "неуспешный"
        elif code[0] in "45" and re.search(r"\bsuccessful\b|\bsuccess\b|(?<!\w)успешн", rest, re.I):
            bad_class = "успешный"
        heading_text = _text(h["block"]).strip()
        if found and code not in found:
            other = found[0]
            phrase = _REASON_RES[[c for c, _ in _REASON_RES].index(other)][1].search(rest).group(0)
            title = (f"Заголовок {_q(heading_text)}: фраза {_q(phrase)} относится к коду {other}, "
                     f"а не к {code}")
        elif bad_class:
            other, phrase = code, ""
            title = f"Заголовок {_q(heading_text)}: код {code} помечен как {bad_class}"
        else:
            continue
        std = _STD_PHRASE.get(code, "<стандартная фраза>")
        c = _make(ctx, rule_id="RULE-STATUS-REASON", kind="incorrect", criterion="correct", severity="major",
                  title=title,
                  impact="Неясно, какой код возвращается на самом деле: сервер и клиент выберут разные значения, "
                         "контрактные тесты и обработка ответа разойдутся.",
                  hints=[_whole(h["block"])],
                  recommendation=f"Привести заголовок к фразе RFC 9110 «{code} {std}»" +
                                 (f" — или, если ответ действительно {other} {_STD_PHRASE.get(other, '')}, "
                                  f"исправить код "
                                  f"и список статусов" if other != code else "") + ".",
                  cause={"object": f"заголовок статуса {code}", "condition": "фраза или класс не соответствует коду"})
        if c:
            out.append(c)
    # --- EXAMPLE (d)
    invalid_4xx = next((d for code in sorted(defs) if code.startswith("4") for d in defs[code]
                        if _INVALID_INPUT.search(d["desc"]) and d["kind"] != "heading"), None) or \
        next((d for code in sorted(defs) if code.startswith("4") for d in defs[code]
              if _INVALID_INPUT.search(d["desc"])), None)
    status_blocks = {b["id"] for h in headings for b in _heading_body(ctx, h["index"])} | \
                    {h["block"]["id"] for h in headings}
    if invalid_4xx is not None:
        for h in headings:
            if not h["code"].startswith("2"):
                continue
            for b in _heading_body(ctx, h["index"]):
                text = _text(b)
                if _kind(b) != "code" and not text.lstrip().startswith("{"):
                    continue
                m = _ERR_VALUE.search(text)
                if not m:
                    continue
                token = re.search(r"ERROR|Error|error|FAIL|Fail|fail|ошибк\w*|[45]\d\d", m.group(0)).group(0)
                extra = None
                for bb in ctx.blocks:
                    if bb["id"] in status_blocks or _kind(bb) not in ("paragraph", "list_item", "quote"):
                        continue
                    tm = re.search(rf"(?<!\w){re.escape(token)}(?!\w)", _text(bb))
                    if tm:
                        tt = _text(bb)
                        extra = _hint(bb, _back_words(tt, tm.start(), 5, _sentence_at(tt, tm.start())[0]), tm.end())
                        break
                code4 = invalid_4xx["code"]
                wa = {"input": "Запрос с неверно заполненными параметрами",
                      "outcome_a": f"HTTP {h['code']} с признаком ошибки в теле (пример в разделе "
                                   f"{_q(_text(h['block']).strip())})",
                      "outcome_b": f"HTTP {code4} по описанию статусов",
                      "hint_a": _hint(b, m.start(), m.end()),
                      "hint_b": _hint(invalid_4xx["block"], invalid_4xx["s"], invalid_4xx["e"])}
                c = _make(ctx, rule_id="RULE-STATUS-EXAMPLE", kind="conflict", criterion=_conflict_criterion(),
                          severity="major",
                          title=f"Пример ответа {h['code']} содержит ошибку {_q(m.group(0))}, хотя для неверных "
                                f"данных описан код {code4}",
                          impact="Неуспех нельзя определить по коду ответа: при 200 с ошибкой в теле приложение "
                                 "покажет успех или потеряет причину отказа, мониторинг не увидит ошибок, тесты ждут "
                                 "разный код.",
                          hints=[extra], witness=wa,
                          recommendation=f"Убрать пример с ошибкой из ответа {h['code']}: для неверных данных "
                                         f"возвращать {code4} с телом <уточнить: формат ошибки>; согласовать с логикой "
                                         f"метода, где упоминается результат с ошибкой.",
                          cause={"object": "ответ на неверно заполненный запрос",
                                 "condition": f"пример {h['code']} с ошибкой против описания {code4}",
                                 "outcomes": [f"HTTP {h['code']}", f"HTTP {code4}"]})
                if c:
                    out.append(c)
                break
    # --- HEADING-BODY (e)
    for h, b, m in body_conflicts:
        x, y = h["code"], m.group(1)
        text = _text(b)
        ss, se = _sentence_at(text, m.start())
        sentence = text[ss:se].strip()
        heading_text = _text(h["block"]).strip()
        note = ", которого нет в списке статусов" if y not in defs else ""
        wa = {"input": f"Ситуация из раздела {_q(heading_text)}: {sentence[:150]}",
              "outcome_a": f"по заголовку раздела — ответ {x}",
              "outcome_b": f"по тексту раздела — ответ {y}",
              "hint_a": _whole(h["block"]), "hint_b": _hint(b, m.start(), m.end())}
        c = _make(ctx, rule_id="RULE-STATUS-HEADING-BODY", kind="conflict", criterion=_conflict_criterion(),
                  severity="major", title=f"Под заголовком {_q(heading_text)} указан ответ {y}{note}",
                  impact="Клиент и тесты не знают, какой код ждать в этой ситуации: обработка ошибок в приложении "
                         "и автотесты разойдутся с сервером.",
                  hints=[], witness=wa,
                  recommendation=f"Выбрать один код для ситуации (<уточнить: {x} или {y}>) и привести к нему "
                                 f"заголовок, "
                                 f"текст и пример; если нужен {y} — добавить его в список статусов с описанием.",
                  cause={"object": f"ответ раздела {x}", "condition": "заголовок и текст называют разные коды",
                         "outcomes": [x, y]})
        if c:
            out.append(c)
    return out


# =========================================================================== 9. RULE-TYPE-MISMATCH
_NAME_COL = re.compile(r"^(?:parameter|param|параметр|поле|field|name|имя(?:\s+поля)?|атрибут|attribute|property"
                       r"|свойство|key|ключ)s?$", re.I)
_TYPE_COL = re.compile(r"^(?:format|type|data\s*type|тип(?:\s+данных)?|формат)$", re.I)
_TYPE_SYN = {
    "integer": ("int", "integer", "int32", "int64", "long", "short", "bigint", "целое", "целое число", "целый"),
    "string": ("string", "str", "text", "varchar", "char", "строка", "строковый", "текст"),
    "boolean": ("bool", "boolean", "логический", "булев", "булевый"),
    "number": ("number", "decimal", "float", "double", "numeric", "число", "дробное", "вещественный"),
    "object": ("object", "json", "объект"),
    "array": ("array", "list", "массив", "список"),
}
_TYPE_MAP = {alias: canon for canon, aliases in _TYPE_SYN.items() for alias in aliases}


def _norm_type(raw: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]|<.*?>|\d+", " ", _norm(raw))
    t = re.sub(r"\s+", " ", t).strip(" .,;")
    return _TYPE_MAP.get(t, t)


def _rule_type_mismatch(ctx: _Ctx) -> list[dict]:
    """RULE-TYPE-MISMATCH: одно поле в двух таблицах (Parameter/Параметр/Поле × Format/Type/Тип) с разными типами.

    Типы нормализуются (int/int32/integer → integer, str/varchar → string …). Одна находка на пару таблиц,
    witness — первое расхождение.
    """
    tables = []
    for ti, t in enumerate(ctx.tables()):
        cols = [c.strip() for c in t["columns"]]
        ncol = next((i for i, c in enumerate(cols) if _NAME_COL.match(c)), None)
        tcol = next((i for i, c in enumerate(cols) if _TYPE_COL.match(c)), None)
        if ncol is None or tcol is None:
            continue
        fields: dict[str, dict] = {}
        for r in t["rows"]:
            text = _text(r)
            spans = _cells(text)
            if len(spans) <= max(ncol, tcol):
                continue
            name = text[spans[ncol][0]:spans[ncol][1]].strip()
            typ = text[spans[tcol][0]:spans[tcol][1]].strip()
            if not name or not typ or _PH_DASH_CELL.match(typ):
                continue
            s, e = (spans[ncol][0], spans[tcol][1]) if ncol < tcol and spans[tcol][1] - spans[ncol][0] <= 60 \
                else spans[tcol]
            fields.setdefault(_norm(name), {"name": name, "type": typ, "norm": _norm_type(typ), "row": r,
                                            "span": (s, e)})
        if fields:
            tables.append((ti, t, fields))
    out: list[dict] = []
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            _, t1, f1 = tables[i]
            _, t2, f2 = tables[j]
            diffs = [(f1[k], f2[k]) for k in f1 if k in f2 and f1[k]["norm"] != f2[k]["norm"]]
            if not diffs:
                continue
            sec1 = t1["section"][-1] if t1["section"] else "таблица 1"
            sec2 = t2["section"][-1] if t2["section"] else "таблица 2"
            names = [a["name"] for a, _ in diffs]
            pairs = {(a["type"], b["type"]) for a, b in diffs}
            if len(pairs) == 1:
                ta, tb = next(iter(pairs))
                detail = f"{', '.join(names)} ({ta} ↔ {tb})"
            else:
                detail = ", ".join(f"{a['name']}: {a['type']} ↔ {b['type']}" for a, b in diffs)
            a0, b0 = diffs[0]
            hints = []
            for a, b in diffs[1:]:
                hints += [_hint(a["row"], *a["span"]), _hint(b["row"], *b["span"])]
            wa = {"input": f"Поле «{a0['name']}» передаётся по описанию обеих таблиц",
                  "outcome_a": f"тип {a0['type']} (таблица {_q(sec1)})",
                  "outcome_b": f"тип {b0['type']} (таблица {_q(sec2)})",
                  "hint_a": _hint(a0["row"], *a0["span"]), "hint_b": _hint(b0["row"], *b0["span"])}
            c = _make(ctx, rule_id="RULE-TYPE-MISMATCH", kind="conflict", criterion=_conflict_criterion(),
                      severity="major",
                      title=f"Типы полей расходятся между таблицами {_q(sec1)} и {_q(sec2)}: {detail}",
                      impact="Клиент и сервер сериализуют поле по-разному: строгий парсер отвергнет сообщение, "
                             "сравнение строки с числом даст ошибку, контрактный тест нельзя написать однозначно.",
                      hints=hints, witness=wa,
                      recommendation=f"Задать один тип для {', '.join(names)} во всех таблицах (<уточнить: тип>) и "
                                     f"формат значения (диапазон, единицы, представление в JSON).",
                      cause={"object": f"тип полей {', '.join(names)}", "condition": "разные типы в двух таблицах",
                             "outcomes": [a0["type"], b0["type"]]})
            if c:
                out.append(c)
    return out


# =========================================================================== 10. RULE-UNITS
_CURRENCIES = (
    ("тенге", "тиын", "1 тенге = 100 тиын",
     re.compile(r"(?<!\w)(?:тенге|KZT|тг\.?)(?!\w)|₸"), re.compile(r"(?<!\w)ти[йи]?ын\w*|(?<!\w)tiyn\w*", re.I)),
    ("рубль", "копейка", "1 рубль = 100 копеек",
     re.compile(r"(?<!\w)(?:рубл\w*|RUB|руб\.?)(?!\w)|₽", re.I), re.compile(r"(?<!\w)копе(?:йк|ек)\w*", re.I)),
    ("доллар", "цент", "1 доллар = 100 центов",
     re.compile(r"(?<!\w)(?:доллар\w*|USD)(?!\w)|\$(?=\s?\d)|(?<=\d)\s?\$", re.I),
     re.compile(r"(?<!\w)(?:цент(?:ов|ы|а|ах|ам|ами)?|cents?)(?!\w)", re.I)),
    ("евро", "евроцент", "1 евро = 100 евроцентов",
     re.compile(r"(?<!\w)(?:евро|EUR)(?!\w)|€", re.I), re.compile(r"(?<!\w)евроцент\w*", re.I)),
)
_CONVERSION = re.compile(r"(?<!\d)100(?!\d)|пересч[её]т|пересчит|конверт|умнож|дел[ие]т|округл|convert|round|multipl|"
                         r"divid|=", re.I)


def _unit_span(text: str, m: re.Match) -> tuple[int, int]:
    """Цитата единицы с предшествующими словами («сумму покупки в тиынах», «Порог в тенге»)."""
    floor = _clause_start(text, m.start())
    s = _back_words(text, m.start(), 3, floor)
    first = re.match(r"(?:и|а|или|но|and|or)\s+", text[s:m.start()], re.I)
    return (s + first.end() if first else s), m.end()


def _rule_units(ctx: _Ctx) -> list[dict]:
    """RULE-UNITS: денежные величины в основной и дробной единице одной валюты (тенге/тиын, рубль/копейка,
    доллар/цент) без явного правила пересчёта и округления."""
    out: list[dict] = []
    blocks = [b for b in ctx.blocks if _eligible(b)]
    for major, minor, rule, rx_major, rx_minor in _CURRENCIES:
        minor_hits = [(b, m) for b in blocks for m in rx_minor.finditer(_text(b))]
        major_hits = [(b, m) for b in blocks for m in rx_major.finditer(_text(b))]
        if not minor_hits or not major_hits:
            continue
        if any(_CONVERSION.search(_text(b)) for b, _ in minor_hits):
            continue
        b1, m1 = minor_hits[0]
        hints = [_hint(b1, *_unit_span(_text(b1), m1))]
        same = [(b, m) for b, m in major_hits if b["id"] == b1["id"]]
        words = [(b, m) for b, m in major_hits if re.match(r"[а-яё]", m.group(0), re.I)]
        if same:
            hints.append(_hint(same[0][0], *_unit_span(_text(same[0][0]), same[0][1])))
        other = next(((b, m) for b, m in words if b["id"] != b1["id"]), None) or \
            next(((b, m) for b, m in major_hits if b["id"] != b1["id"]), None)
        if other:
            hints.append(_hint(other[0], *_unit_span(_text(other[0]), other[1])))
        c = _make(ctx, rule_id="RULE-UNITS", kind="incomplete", criterion=("complete", "set_complete"),
                  severity="major",
                  title=f"Суммы в единицах «{minor}» и «{major}» без правила пересчёта",
                  impact="Сравнение сумм в разных единицах даст ошибку в 100 раз или ошибки округления; сервисы "
                         "выберут пересчёт по-разному, граничные тесты будут неоднозначны.",
                  hints=hints,
                  recommendation=f"Зафиксировать единую единицу хранения и сравнения "
                                 f"(<уточнить: {minor} или {major}>), "
                                 f"правило пересчёта ({rule}) и округления (<уточнить: правило>) для всех сумм.",
                  cause={"object": f"денежные суммы ({major}/{minor})", "condition": "нет правила пересчёта единиц"})
        if c:
            out.append(c)
    return out


# =========================================================================== 11. RULE-TERMS
_TERM_GROUPS = (
    ("участник", True, (
        ("держатель карты", re.compile(r"(?<!\w)держател[ьяюеи]\w*(?:\s+(?:[\w-]+\s+){0,2}?карт\w*)?", re.I)),
        ("владелец карты", re.compile(r"(?<!\w)владел\w*\s+(?:[\w-]+\s+){0,2}?карт\w*", re.I)),
        ("клиент", re.compile(r"(?<!\w)клиент(?!ск)\w*", re.I)),
        ("пользователь", re.compile(r"(?<!\w)(?:пользовател(?!ьск)\w*|пользовательск\w*\s+сесси\w*)", re.I)),
    )),
    ("порог", False, (
        ("порог", re.compile(r"(?<!\w)порог\w*", re.I)),
        ("лимит", re.compile(r"(?<!\w)[Лл]имит\w*|(?<![A-Za-z])[Ll]imit\w*|(?<=[a-z])Limit\w*")),
        ("бюджет", re.compile(r"(?<!\w)бюджет\w*", re.I)),
    )),
    ("уведомление", False, (
        ("уведомление", re.compile(r"(?<!\w)уведомлени\w*", re.I)),
        ("оповещение", re.compile(r"(?<!\w)оповещени\w*", re.I)),
        ("нотификация", re.compile(r"(?<!\w)нотификаци\w*", re.I)),
    )),
)
_AUTH_CTX = re.compile(r"авториз|authori[sz]|аутентиф|authent|(?<!\w)прав[оа](?!\w)|доступ|разреш|permission|access|"
                       r"принадлежност|сесси|session|bearer|токен|token|(?<!\w)рол[ьи]", re.I)


def _token_span(text: str, s: int, e: int) -> tuple[int, int]:
    while s > 0 and (text[s - 1].isalnum() or text[s - 1] == "_"):
        s -= 1
    while e < len(text) and (text[e].isalnum() or text[e] == "_"):
        e += 1
    return s, e


def _rule_terms(ctx: _Ctx) -> list[dict]:
    """RULE-TERMS: дрейф синонимов для одного участника или объекта в тексте требований.

    Группы: {держатель карты, владелец карты/счёта, клиент, пользователь}, {порог, лимит/limit, бюджет},
    {уведомление, оповещение, нотификация}. Два и более варианта одной группы — замечание; «major»,
    если вариант участника стоит в утверждении об авторизации или правах доступа.
    """
    out: list[dict] = []
    blocks = [b for b in ctx.blocks if _eligible(b)]
    for group, actor, variants in _TERM_GROUPS:
        first: dict[str, tuple[dict, int, int]] = {}
        auth: Optional[tuple[dict, int, int]] = None
        for b in blocks:
            text = _text(b)
            for label, rx in variants:
                for m in rx.finditer(text):
                    s, e = _token_span(text, m.start(), m.end())
                    if label not in first:
                        first[label] = (b, s, e)
                    if actor and auth is None and _AUTH_CTX.search(text):
                        auth = (b, s, e)
        if len(first) < 2:
            continue
        # «клиент», «пользователь», «владелец счёта» часто законно обозначают одно лицо; дефект — только когда
        # разведены держатель и владелец карты (у дополнительной карты это разные люди)
        if actor and not {"держатель карты", "владелец карты"} <= set(first):
            continue
        labels = sorted(first, key=lambda lb: (ctx.pos[first[lb][0]["id"]], first[lb][1]))
        hints = [_hint(*first[lb]) for lb in labels]
        if auth is not None and auth not in first.values():
            hints.append(_hint(*auth))
        major = actor and auth is not None
        if actor:
            title = f"Один участник назван по-разному: {_join_q(labels, 4)}"
            impact = ("Неясно, кому разрешено действие: разные названия участника в функциональных требованиях и "
                      "в проверке доступа приведут к разной реализации авторизации" +
                      (" — в API права проверяются по другому участнику, чем в требованиях." if major else "."))
            rec = (f"Ввести глоссарий и один термин (<уточнить: какой из {', '.join(_q(x) for x in labels)}>) во всех "
                   f"требованиях и в описании авторизации; если роли разные — описать, чем они отличаются и кому что "
                   f"разрешено.")
        else:
            title = f"Одно понятие названо по-разному: {_join_q(labels, 4)}"
            impact = ("Читатель не уверен, что речь об одном и том же объекте: разработчики разных частей системы "
                      "могут реализовать разные сущности или поля.")
            rec = (f"Выбрать один термин (<уточнить: {' / '.join(labels)}>), закрепить его в глоссарии и заменить "
                   f"остальные варианты, включая имена полей и методов API.")
        c = _make(ctx, rule_id="RULE-TERMS", kind="terminology", criterion="set_consistent",
                  severity="major" if major else "minor", title=title, impact=impact, hints=hints,
                  recommendation=rec,
                  cause={"object": f"термин «{group}»", "condition": "синонимы: " + ", ".join(labels)})
        if c:
            out.append(c)
    return out


# =========================================================================== 12. RULE-READ-WITHOUT-METHOD
_READ_SUBJECT = (r"(?:приложени\w*|клиент(?!ск)\w*|фронт\w*|интерфейс\w*|экран\w*|пользовател\w*"
                 r"|UI|app|client|frontend|screen)")
# «получает» и «загружает» не входят: получение поля в ответе на изменяющий запрос не обещает метод чтения
_READ_VERB = r"(?:чита\w*|прочита\w*|запрашива\w*|отобража\w*|показыва\w*|выводит\w*|видит\w*" \
             r"|reads?|retriev\w*|display\w*|shows?)"
# Сильные утверждения (клиент читает/запрашивает, «чтение …», «на экране видны») идут в подсказки первыми,
# слабые («показывает», «shall display») — только если сильных не хватило.
_READ_CLAIM = re.compile(
    rf"(?<!\w){_READ_SUBJECT}\s+(?:[\w-]+\s+){{0,2}}?{_READ_VERB}(?!\w)"
    r"|(?<!\w)на\s+экран\w*\s+(?:видн|отобража|показыва|выводит)\w*"
    r"|(?<!\w)(?:чтени[еяю]|просмотр\w*)(?:\s+[\w-]+)?", re.I)
_READ_CLAIM_WEAK = re.compile(
    r"(?<!\w)(?:отобража|показыва)\w*(?:\s+[\w-]+)?"
    r"|(?<!\w)(?:shall|must|will|should|can)\s+(?:\w+\s+)?(?:display|show|view|see|retrieve|fetch|read)(?!\w)"
    r"(?:\s+(?:the\s+)?[\w-]+)?", re.I)
_READ_EXCLUDE = re.compile(r"push|пуш|уведомлен|sms|смс|сообщени|письм|notification|ответ|ошибк|код|статус|response|"
                           r"error", re.I)


def _ep_class(ep: dict) -> str:
    words = _path_words(ep["path"])
    w = any(x in _EN_WRITE for x in words)
    r = any(x in _EN_READ for x in words)
    if w and not r:
        return "write"
    if r and not w:
        return "read"
    if ep["method"] in ("GET", "HEAD"):
        return "read"
    if ep["method"] in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    return "unknown"


def _rule_read_without_method(ctx: _Ctx) -> list[dict]:
    """RULE-READ-WITHOUT-METHOD: текст обещает чтение/отображение данных клиентом, а API описывает
    только изменяющие методы (CRUD-полнота). Подсказки — утверждения о чтении и единственный метод."""
    eps = _endpoints(ctx)
    if not eps:
        return []
    classes: dict[str, str] = {}
    for ep in eps:
        cl = _ep_class(ep)
        prev = classes.get(ep["path"])
        if prev in (None, "unknown") or cl == "read":
            classes[ep["path"]] = cl
    if any(c in ("read", "unknown") for c in classes.values()) or "write" not in classes.values():
        return []
    found: list[tuple[int, int, dict]] = []   # (приоритет, позиция блока, подсказка)
    for b in ctx.blocks:
        if not _eligible(b):
            continue
        text = _text(b)
        for prio, rx in ((0, _READ_CLAIM), (1, _READ_CLAIM_WEAK)):
            hit = None
            for m in rx.finditer(text):
                if _READ_EXCLUDE.search(text[m.end():m.end() + 30]) or _READ_EXCLUDE.search(m.group(0)):
                    continue
                hit = _hint(b, m.start(), m.end())
                if hit:
                    break
            if hit:
                found.append((prio, ctx.pos[b["id"]], hit))
                break
    claims = [h for _, _, h in sorted(sorted(found)[:3], key=lambda x: x[1])]
    if not claims:
        return []
    write_paths = list(dict.fromkeys(p for p, c in classes.items() if c == "write"))
    ep0 = next(e for e in eps if e["path"] == write_paths[0])
    methods = "изменяющие методы" if len(write_paths) > 1 else "изменяющий метод"
    c = _make(ctx, rule_id="RULE-READ-WITHOUT-METHOD", kind="omission", criterion="set_complete", severity="major",
              title=f"Описано чтение данных, но в API только {methods} {_join_q(write_paths)}",
              impact="Экран или клиент не сможет получить текущие данные: метод чтения придётся придумывать при "
                     "разработке, контракт и тесты для него отсутствуют.",
              hints=claims + [_span_hint(ep0["path_hint"])],
              recommendation="Добавить метод чтения (например, GET <уточнить: путь>) с параметрами, телом ответа и "
                             "статусами — или убрать из требований утверждения о чтении и отображении данных.",
              cause={"object": "метод чтения API", "condition": "чтение заявлено, но не описано"})
    return [c] if c else []


# =========================================================================== 13. RULE-MISSING-ID
_REQ_SECTION = re.compile(r"требовани|requirement", re.I)
_NOT_REQ_SECTION = re.compile(r"ревью|review|тестировани\w*\s+требовани|проверк\w*\s+требовани|согласован", re.I)


def _req_items(ctx: _Ctx) -> list[tuple[str, dict]]:
    out = []
    for b in ctx.blocks:
        sec = _section(b)
        if not sec or _kind(b) not in ("list_item", "paragraph", "table_row") or not _text(b).strip():
            continue
        if not _REQ_SECTION.search(sec[-1]) or _NOT_REQ_SECTION.search(sec[-1]) or _is_template(sec):
            continue
        if b["id"] in ctx.placeholder_done or _PLACEHOLDER_ONLY.match(_text(b)) or _text(b).rstrip().endswith(":"):
            continue
        out.append((sec[-1], b))
    return out


def _rule_missing_id(ctx: _Ctx) -> list[dict]:
    """RULE-MISSING-ID: пункты разделов «… требования» без идентификатора (Ф-1, НФТ-2, FR-3, REQ-12).

    Один кандидат на раздел; для каждого требования без ID — проверка ``conforming`` со статусом issue.
    """
    items = _req_items(ctx)
    with_id = {sec for sec, b in items if _ID_AT_START.match(_text(b)) or ctx.source_id(b)}
    by_sec: dict[str, list[dict]] = {}
    for sec, b in items:
        if _kind(b) == "table_row":
            continue  # строки таблиц в разделах требований — обычно словарь данных, а не пункты
        if _kind(b) == "paragraph" and sec in with_id:
            continue  # вводный абзац раздела, где пункты уже пронумерованы
        if not _ID_AT_START.match(_text(b)) and not ctx.source_id(b):
            by_sec.setdefault(sec, []).append(b)
    out: list[dict] = []
    for sec, blocks in by_sec.items():
        hints = [_hint(b, 0, _cut(_text(b), 0, 60)) for b in blocks[:3]]
        c = _make(ctx, rule_id="RULE-MISSING-ID", kind="traceability", criterion=("conforming", "traceable"),
                  severity="minor",
                  title=f"Требования раздела {_q(sec)} без идентификаторов ({len(blocks)})",
                  impact="На требования нельзя сослаться из критериев приёмки, тестов, задач и замечаний: "
                         "прослеживаемость и анализ влияния изменений теряются.",
                  hints=hints,
                  recommendation=f"Присвоить пунктам раздела {_q(sec)} уникальные ID по схеме документа "
                                 f"(<уточнить: префикс>-1, -2 …) и ссылаться на них из критериев приёмки.",
                  cause={"object": f"раздел {_q(sec)}", "condition": "требования без идентификаторов"})
        if c:
            out.append(c)
            if c["criterion"] in INDIVIDUAL_CRITERIA:
                continue
            for rid in ctx.reqs(b["id"] for b in blocks):
                ctx.extra_checks.append({"req_id": rid, "criterion": "conforming", "status": "issue",
                                         "reason": "Нет идентификатора требования", "source": SOURCE})
    return out


# =========================================================================== 14. RULE-NON-SINGULAR
_DEPENDENT_START = re.compile(
    r"^(?:если|при\s+этом|это|этот|эта|эти|он|она|оно|они|его|её|ее|их|так(?:ой|ая|ое|ие)|данн\w+|в\s+этом\s+случае"
    r"|в\s+противном\s+случае|иначе|тогда|например|кроме\s+случаев|then|otherwise|this|it|if|in\s+this\s+case|e\.g\.)"
    r"(?!\w)", re.I)
_MODAL = re.compile(r"(?<!\w)(?:долж(?:ен|на|но|ны)|обязан\w*|необходимо|требуется|shall|must)(?!\w)", re.I)


def _rule_non_singular(ctx: _Ctx) -> list[dict]:
    """RULE-NON-SINGULAR: несколько обязательств в одном требовании (ISO/IEC/IEEE 29148, 5.2.5 singular).

    Три и более предложения — замечание; два независимых предложения (второе не начинается с «Если»,
    «Это», «При этом»…) — замечание для пунктов с ID; два модальных глагола в одном предложении —
    тоже. Предложения-схемы со стрелками «→» и строки-перечни («200. …») не считаются.
    """
    out: list[dict] = []
    for r in ctx.requirements:
        blocks = [ctx.by_id[x] for x in r.get("block_ids") or [] if x in ctx.by_id]
        blocks = [b for b in blocks if _kind(b) in ("list_item", "paragraph", "quote")]
        if not blocks:
            continue
        b = blocks[0]
        if _is_template(_section(b)) or _is_meta(_section(b)):
            continue
        text = _text(b)
        lines = [ln for ln in text.split("\n") if ln.strip()]
        if len(lines) >= 2 and sum(bool(re.match(r"^\s*(?:\d{1,3}[.)]|[-*•]|[1-5]\d\d\b)", ln)) for ln in lines) * 2 \
                >= len(lines):
            continue
        offset = 0
        m = _ID_STRIP.match(text) or _LIST_NUM.match(text)
        if m:
            offset = m.end()
        sents = [(s + offset, e + offset) for s, e in _sentences(text[offset:])]
        sents = [(s, e) for s, e in sents if "→" not in text[s:e] and "->" not in text[s:e]
                 and len(text[s:e].split()) >= 3]
        sid = r.get("source_id") or (_ID_AT_START.match(text).group(1) if _ID_AT_START.match(text) else None)
        label = sid or r["id"]
        n = len(sents)
        flagged = False
        if n >= 3:
            flagged = True
        elif n == 2 and sid and not _DEPENDENT_START.match(text[sents[1][0]:sents[1][1]]):
            flagged = True
        elif n == 1 and len(_MODAL.findall(text[sents[0][0]:sents[0][1]])) >= 2:
            flagged = True
        if not flagged:
            continue
        hints = [_hint(b, s, e) for s, e in sents[:4]]
        count = max(n, 2)
        title = (f"{label} объединяет {count} правил{'а' if count < 5 else ''} в одном пункте" if n != 2 else
                 f"{label} объединяет 2 независимых правила в одном пункте")
        c = _make(ctx, rule_id="RULE-NON-SINGULAR", kind="non_singular", criterion="singular", severity="minor",
                  title=title,
                  impact="Правила одного пункта нельзя проверить, проследить и изменить по отдельности: тест-кейс и "
                         "статус выполнения относятся сразу ко всем, правка одного задевает остальные.",
                  hints=hints,
                  recommendation=f"Разделить {label} на отдельные требования с собственными ID (<уточнить: "
                                 f"{label}.1, {label}.2 …>): по одному проверяемому правилу в каждом.",
                  cause={"object": f"требование {label}", "condition": f"{count} обязательств в одном пункте"})
        if c:
            out.append(c)
    return out


# =========================================================================== 15. RULE-ACCEPTANCE-TRACE
_ACCEPT_SEC = re.compile(r"при[её]мк|acceptance|критери\w*\s+готовност", re.I)


def _rule_acceptance_trace(ctx: _Ctx) -> list[dict]:
    """RULE-ACCEPTANCE-TRACE: критерии приёмки (таблица или список под заголовком «приёмка»/«acceptance»)
    не ссылаются ни на один ID требования."""
    known: list[str] = [str(r["source_id"]) for r in ctx.requirements if r.get("source_id")]
    for _, b in _req_items(ctx):
        m = _ID_AT_START.match(_text(b))
        if m:
            known.append(m.group(1))
    known = list(dict.fromkeys(known))
    out: list[dict] = []
    groups: dict[tuple, list[dict]] = {}
    for b in ctx.blocks:
        sec = _section(b)
        if not sec or not _ACCEPT_SEC.search(sec[-1]) or _kind(b) not in ("table_row", "list_item"):
            continue
        if _text(b).strip():
            groups.setdefault(tuple(sec), []).append(b)
    for sec, rows in groups.items():
        refs = [k for k in known for r in rows
                if re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-]|\.\d)", _text(r))]
        if refs:
            continue
        header = next((t["header"] for t in ctx.tables() if t["rows"] and t["rows"][0]["id"] == rows[0]["id"]
                       and t["header"] is not None), None)
        hints = [_whole(header) if header else None]
        for r in rows[:2]:
            first = _cells(_text(r))[0] if _kind(r) == "table_row" else (0, len(_text(r)))
            hints.append(_hint(r, first[0], _cut(_text(r), first[0], first[1])))
        c = _make(ctx, rule_id="RULE-ACCEPTANCE-TRACE", kind="traceability", criterion="traceable", severity="minor",
                  title=f"Критерии приёмки в разделе {_q(sec[-1])} не ссылаются на ID требований ({len(rows)})",
                  impact="Нельзя проверить покрытие: неизвестно, какое требование подтверждает каждый критерий и какие "
                         "требования остались без приёмки.",
                  hints=hints,
                  recommendation="Добавить в каждый критерий ссылку на проверяемые требования (колонка «Требование»: "
                                 "<уточнить: ID>) и убедиться, что каждое требование покрыто хотя бы одним критерием.",
                  cause={"object": f"критерии приёмки ({sec[-1]})", "condition": "нет ссылок на ID требований"})
        if c:
            out.append(c)
    return out


# =========================================================================== сборка
_RULES: tuple[tuple[str, Callable[[_Ctx], list[dict]]], ...] = (
    ("RULE-VAGUE", _rule_vague),
    ("RULE-OPEN-LIST", _rule_open_list),
    ("RULE-EMPTY-SECTION", _rule_empty_section),
    ("RULE-PLACEHOLDER", _rule_placeholder),
    ("RULE-TZ", _rule_tz),
    ("RULE-HTTP-SEMANTICS", _rule_http_semantics),
    ("RULE-BODY-CONTENT-TYPE", _rule_body_content_type),
    ("RULE-STATUS", _rule_status),
    ("RULE-TYPE-MISMATCH", _rule_type_mismatch),
    ("RULE-UNITS", _rule_units),
    ("RULE-TERMS", _rule_terms),
    ("RULE-READ-WITHOUT-METHOD", _rule_read_without_method),
    ("RULE-MISSING-ID", _rule_missing_id),
    ("RULE-NON-SINGULAR", _rule_non_singular),
    ("RULE-ACCEPTANCE-TRACE", _rule_acceptance_trace),
)
RULE_IDS = tuple(r for r, _ in _RULES if r != "RULE-STATUS") + (
    "RULE-STATUS-UNDEFINED", "RULE-STATUS-SUMMARY", "RULE-STATUS-REASON", "RULE-STATUS-EXAMPLE",
    "RULE-STATUS-HEADING-BODY")


def _checks(ctx: _Ctx, candidates: list[dict]) -> list[dict]:
    """Проверки уровня требования (только issue) из кандидатов с индивидуальным критерием."""
    merged: dict[tuple[str, str], list[str]] = {}
    for c in candidates:
        if c["criterion"] not in INDIVIDUAL_CRITERIA:
            continue
        for rid in c["req_ids"]:
            merged.setdefault((rid, c["criterion"]), []).append(c["title"])
    for ch in ctx.extra_checks:
        merged.setdefault((ch["req_id"], ch["criterion"]), []).append(ch["reason"])
    return [{"req_id": rid, "criterion": crit, "status": "issue",
             "reason": "; ".join(dict.fromkeys(reasons)), "source": SOURCE}
            for (rid, crit), reasons in merged.items()]


def lint(document: dict, requirements: Optional[list[dict]] = None) -> dict[str, Any]:
    """Детерминированный проход правил по документу.

    ``requirements`` — элементы ``{id, source_id, text, block_ids, kind}``; блоки вне требований
    дают находки с ``req_ids = []`` и ``scope = "set"``. Результат —
    ``{"candidates": [Candidate], "checks": [Check], "warnings": [str]}``; два прогона на одном
    входе дают одинаковый результат.
    """
    ctx = _Ctx(document, requirements)
    candidates: list[dict] = []
    for rule_id, fn in _RULES:
        try:
            produced = fn(ctx)
        except Exception as exc:  # noqa: BLE001 — сбой одного правила не должен ронять линтер
            ctx.warnings.append(f"{rule_id}: правило пропущено из-за внутренней ошибки: "
                                f"{exc.__class__.__name__}: {exc}")
            continue
        candidates.extend(c for c in produced if c)
    return {"candidates": candidates, "checks": _checks(ctx, candidates), "warnings": ctx.warnings}
