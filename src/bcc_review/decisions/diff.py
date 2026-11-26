"""Сравнение двух отчётов ревью (редакций ТЗ) без ложных закрытий.

    compare_reports(previous, current) -> {
        resolved, persisting, introduced, unassessed, warnings, basis
    }

Каждое замечание прошлого отчёта попадает ровно в одну из трёх групп:
resolved («исправлено в тексте»), persisting («сохранилось»),
unassessed («нужно подтверждение»). Находки нового отчёта без пары
прошлого попадают в introduced («новое замечание»). Каждый id нового
отчёта тоже встречается ровно один раз.

Правило закрытия (resolved) проверяет по порядку:
  1. второй прогон завершён (run.status == complete);
  2. редакция действительно другая (source_sha256 различается);
  3. затронутое обязательство найдено в новой редакции, то есть не исчезло
     из извлечения и не сопоставлено неоднозначно;
  4. текст в месте опоры изменился;
  5. в новом отчёте есть явная перепроверка этого обязательства по тому же
     критерию. Для противоречия нужен сценарий witness с единым исходом и
     опорой в новом тексте. Для пропуска нужна опора на появившийся текст.
Если хотя бы одно условие не выполнено, замечание получает статус
unassessed с причиной. Тишина второго вызова модели, принятое по --answers
решение или удаление источника сами по себе замечание не закрывают.

Номера строк, порядковые id требований, замечаний и блоков зависят от
версии и в сопоставлении не участвуют. Используются текст обязательства,
source_id и раздел (как надбавки), подтверждённые цитаты и их положение.
Пороги подобраны на примере из кейса: tests/p09/test_p09_measures.py.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import functools
import hashlib
import json
import re
import sys
import unicodedata
from typing import Any
from collections.abc import Callable, Iterable

DIFF_VERSION = "p09-2"

STATUS_RU = {
    "resolved": "исправлено в тексте",
    "persisting": "сохранилось",
    "unassessed": "нужно подтверждение",
    "introduced": "новое замечание",
}
ENTRY_PREFIX = {"resolved": "RES", "persisting": "PER", "unassessed": "CHK", "introduced": "NEW"}
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}
SEVERITY_RU = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}

# Пороги текстового сходства. Обоснование: tests/p09/test_p09_false_positive.py.
REQ_CONFIDENT = 0.55  # уверенная пара 1:1 без опор
REQ_CANDIDATE = 0.40  # ниже порога пара не рассматривается
REQ_MARGIN = 0.08  # отрыв от второго кандидата
PART_CONTAINMENT = 0.75  # доля шинглов части, вложенная в целое (split/merge)
UNION_COVERAGE = 0.75  # доля целого, покрытая частями
FIND_CONFIDENT = 0.62  # уверенная пара замечаний
FIND_CANDIDATE = 0.45  # кандидат для ручной проверки
FUZZY_ANCHOR = 0.60  # нечёткое перемещение опоры
SCENARIO_MATCH = 0.80  # сценарий перепроверки совпадает с witness.input
TIE_EPS = 0.02  # кандидаты с разницей оценок меньше порога равноправны

# Check.status по контракту v1: pass | issue | unknown | na. Прочие значения — для совместимости.
_POSITIVE = {"pass", "passed", "ok", "consistent"}
_NEGATIVE = {"issue", "failed", "fail", "violated", "inconsistent"}
# Критерий набора проявляется в проверках требований своим «индивидуальным» критерием
# (пример контракта: конфликт set_consistent → checks correct: issue).
_CRITERION_FAMILY = {
    "set_consistent": "correct",
    "set_complete": "complete",
    "set_feasible": "feasible",
    "set_comprehensible": "unambiguous",
    "set_validatable": "verifiable",
    "traceable": "conforming",
    "ranked": "conforming",
    "modifiable": "conforming",
}
_PARTIAL_READ = {"partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input"}
_LABEL = re.compile(
    r"^\s*(?:[A-Za-zА-Яа-яЁё]{1,6}(?:[-‑–][A-Za-zА-Яа-яЁё]{1,6})*\s?[-‑–.]\s?\d+(?:\.\d+)*|\d+(?:\.\d+)*[.)])[.):]?\s+"
)
_CONFLICT_KINDS = {"conflict", "contradiction", "inconsistency", "противоречие"}
_OMISSION_KINDS = {"omission", "missing", "gap", "incomplete_set", "пропуск"}

AskFn = Callable[[str, dict, dict], dict]

# ---------------------------------------------------------------------------
# Текст
# ---------------------------------------------------------------------------

_STOP = frozenset(
    "и в во не на с со по к ко а о об от до для за из у же ли или что это как при "
    "его ее её их то так также который которая которое которые если когда она он оно "
    "они бы был была было были быть есть the a of".split()
)
_TRANSLATE = str.maketrans(
    {"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "’": "'", "‘": "'", "–": "-", "—": "-", "−": "-", "ё": "е"}
)


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Нормализованный текст и позиция каждого его символа в исходной строке."""
    out: list[str] = []
    pos: list[int] = []
    n = len(text)
    space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if space:
                continue
            nxt = text[i + 1 : i + 4]
            if (
                out
                and out[-1].isdigit()
                and len(nxt) == 3
                and nxt.isdigit()
                and (i + 4 >= n or not text[i + 4].isdigit())
            ):
                continue  # «1 000 000» == «1000000»
            out.append(" ")
            pos.append(i)
            space = True
            continue
        for c in unicodedata.normalize("NFKC", ch).lower().translate(_TRANSLATE):
            out.append(c)
            pos.append(i)
        space = False
    while out and out[-1] == " ":
        out.pop()
        pos.pop()
    return "".join(out), pos


@functools.lru_cache(maxsize=8192)
def _norm(text: str) -> str:
    return _norm_map(text or "")[0]


@functools.lru_cache(maxsize=8192)
def _words(text: str) -> tuple[str, ...]:
    return tuple(w for w in re.findall(r"\w+", _norm(text)) if w not in _STOP)


@functools.lru_cache(maxsize=8192)
def _stems(text: str) -> frozenset[str]:
    return frozenset(w if w.isdigit() else w[:5] for w in _words(text))


@functools.lru_cache(maxsize=8192)
def _shingles(text: str, size: int = 4) -> frozenset[str]:
    s = " ".join(_words(text))
    if not s:
        return frozenset()
    return frozenset(s[i : i + size] for i in range(max(1, len(s) - size + 1)))


def _dice(a: frozenset, b: frozenset) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


@functools.lru_cache(maxsize=16384)
def _seq(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, " ".join(_words(a)), " ".join(_words(b)), autojunk=False).ratio()


def text_similarity(a: str, b: str) -> float:
    """Смесь Dice по основам (порядок слов не важен) и SequenceMatcher (важен)."""
    if not a or not b:
        return 0.0
    return 0.5 * _dice(_stems(a), _stems(b)) + 0.5 * _seq(a, b)


def containment(part: str, whole: str) -> float:
    """Доля шинглов `part`, найденных в `whole`."""
    p = _shingles(part)
    return len(p & _shingles(whole)) / len(p) if p else 0.0


def _stem_containment(part: str, whole: str) -> float:
    p = _stems(part)
    return len(p & _stems(whole)) / len(p) if p else 0.0


def _short(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _natural(value: Any) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(value)))


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _sentences(text: str) -> Iterable[tuple[int, int]]:
    start = 0
    for m in re.finditer(r"[.!?;](?=\s|$)", text):
        end = m.end()
        if text[start:end].strip():
            yield start, end
        start = end
    if text[start:].strip():
        yield start, len(text)


def strip_label(text: str) -> str:
    """Текст пункта без ведущего номера («Ф-1.», «Д-КП-1.», «п. 3», «2)»): номер зависит от версии."""
    text = text or ""
    m = _LABEL.match(text)
    return text[m.end() :] if m else text


def req_body(r: dict) -> str:
    """Текст требования без его номера: сначала по source_id, затем по шаблону метки."""
    text = str(r.get("text") or "")
    sid = str(r.get("source_id") or "").strip()
    head = text.lstrip()
    if sid and head.startswith(sid):
        rest = head[len(sid) :]
        m = re.match(r"^[.):]?\s+", rest)
        if m and not rest[m.end() : m.end() + 1].isdigit():
            return rest[m.end() :]
    return strip_label(text)


# ---------------------------------------------------------------------------
# Редакция = отчёт + документ
# ---------------------------------------------------------------------------


class _Edition:
    def __init__(self, report: dict, label: str):
        if not isinstance(report, dict):
            raise TypeError(f"{label}: ожидается Report (dict), получено {type(report).__name__}")
        self.label = label
        self.report = report
        self.run = report.get("run") or {}
        self.document = report.get("document") or {}
        self.doc_id = self.document.get("id")
        self.sha = self.run.get("source_sha256") or self.doc_id
        self.status = str(self.run.get("status") or "unknown").lower()
        self.blocks = [
            b for b in _as_list(self.document.get("blocks")) if isinstance(b, dict) and b.get("id") is not None
        ]
        self.block_by_id = {b["id"]: b for b in self.blocks}
        self.block_order = {b["id"]: i for i, b in enumerate(self.blocks)}
        self.block_norm = {b["id"]: _norm_map(str(b.get("text") or "")) for b in self.blocks}
        self.full_norm = "\n".join(self.block_norm[b["id"]][0] for b in self.blocks)
        self.headings = {_norm(h) for b in self.blocks for h in _as_list(b.get("section")) if h}
        self.headings |= {_norm(str(b.get("text") or "")) for b in self.blocks if b.get("kind") == "heading"}
        # полные пути разделов: «Корпоративные карты › Функциональные требования» ≠ «Дебетовые карты › …»
        self.section_paths = {tuple(_norm(str(h)) for h in _as_list(b.get("section"))) for b in self.blocks}
        self.reqs = [r for r in _as_list(report.get("requirements")) if isinstance(r, dict) and r.get("id") is not None]
        self.req_by_id = {r["id"]: r for r in self.reqs}
        self.findings = [f for f in _as_list(report.get("findings")) if isinstance(f, dict) and f.get("id") is not None]
        self.checks = [c for c in _as_list(report.get("checks")) if isinstance(c, dict)]
        self.decisions = [d for d in _as_list(report.get("decisions")) if isinstance(d, dict)]
        self.coverage = [c for c in _as_list(report.get("coverage")) if isinstance(c, dict) and c.get("req_id")]
        self.stages = [st for st in _as_list(self.run.get("stages")) if isinstance(st, dict)]
        self.incomplete_stages = {str(x).split("#")[0] for x in _as_list(self.run.get("incomplete_stages"))}
        self.questions = {
            q["id"]: q for q in _as_list(report.get("questions")) if isinstance(q, dict) and q.get("id") is not None
        }
        raw_warnings = _as_list(self.document.get("warnings"))
        self.doc_warnings = [str(w) if not isinstance(w, dict) else str(w.get("message") or w) for w in raw_warnings]
        self.partial_read = [
            str(w.get("message") or w.get("code"))
            for w in raw_warnings
            if isinstance(w, dict) and w.get("code") in _PARTIAL_READ
        ]
        # неполное чтение с указанием места (Warning.block_ids) задевает только эти блоки;
        # без указания места неизвестно, что потеряно, — задето всё
        self.partial_read_blocks: set = set()
        self.partial_read_global: list = []
        for w in raw_warnings:
            if isinstance(w, dict) and w.get("code") in _PARTIAL_READ:
                ids = [b for b in _as_list(w.get("block_ids")) if b]
                if ids:
                    self.partial_read_blocks.update(ids)
                else:
                    self.partial_read_global.append(str(w.get("message") or w.get("code")))
        self.digest = _report_digest(report)

    # --- опоры ---------------------------------------------------------
    def verify(self, ev: dict) -> dict:
        out = {k: ev.get(k) for k in ("block_id", "start", "end", "quote")}
        block = self.block_by_id.get(ev.get("block_id"))
        start, end, quote = ev.get("start"), ev.get("end"), ev.get("quote")
        ok = (
            block is not None
            and isinstance(start, int)
            and isinstance(end, int)
            and isinstance(quote, str)
            and 0 <= start <= end
            and str(block.get("text") or "")[start:end] == quote
        )
        out["verified"] = bool(ok)
        if block is not None:
            out["loc"] = block.get("loc")
            out["section"] = _as_list(block.get("section"))
        return out

    def sentence_of(self, block_id: str, offset: int) -> int:
        cache = self.__dict__.setdefault("_sent_cache", {})
        if block_id not in cache:
            cache[block_id] = list(_sentences(str(self.block_by_id[block_id].get("text") or "")))
        for k, (_s, e) in enumerate(cache[block_id]):
            if offset < e:
                return k
        return len(cache[block_id])

    def contains(self, quote: str) -> bool:
        """Есть ли цитата в редакции (номер пункта в начале цитаты не учитывается)."""
        for q in dict.fromkeys((quote or "", strip_label(quote or ""))):
            nq = _norm(q)
            if nq and nq in self.full_norm:
                return True
        return False

    def locate(self, quote: str, prefer: Iterable[str] = (), *, only: bool = False) -> dict | None:
        """Ищет цитату: точно, после нормализации, затем нечётко по предложениям.

        only=True — только в блоках prefer (источник опоры известен: цитату нельзя «найти»
        в чужом разделе, где лежит такой же текст)."""
        if not quote or not quote.strip():
            return None
        prefer = [b for b in prefer if b in self.block_by_id]
        order = prefer if only else prefer + [b["id"] for b in self.blocks if b["id"] not in prefer]
        variants = list(dict.fromkeys(q for q in (quote, strip_label(quote)) if q.strip()))
        for q in variants:  # номер пункта в цитате мог смениться при перенумерации
            for bid in order:
                text = str(self.block_by_id[bid].get("text") or "")
                p = text.find(q)
                if p >= 0:
                    return self._anchor(bid, p, p + len(q), "exact")
        for q in variants:
            nq = _norm(q)
            for bid in order:
                nt, idx = self.block_norm[bid]
                p = nt.find(nq) if nq else -1
                if p >= 0:
                    return self._anchor(bid, idx[p], idx[p + len(nq) - 1] + 1, "normalized")
        best: tuple[float, int, str, int, int] | None = None
        for rank, bid in enumerate(order):
            text = str(self.block_by_id[bid].get("text") or "")
            for s, e in _sentences(text):
                sent = text[s:e]
                score = 0.6 * _stem_containment(quote, sent) + 0.4 * _seq(quote, sent)
                key = (score, -rank, bid, s, e)
                if score >= FUZZY_ANCHOR and (best is None or key[:2] > best[:2]):
                    best = key
        if best is None:
            return None
        score, _, bid, s, e = best
        text = str(self.block_by_id[bid].get("text") or "")
        while s < e and text[s].isspace():
            s += 1
        anchor = self._anchor(bid, s, e, "fuzzy")
        anchor["similarity"] = round(score, 3)
        return anchor

    def _anchor(self, bid: str, start: int, end: int, match: str) -> dict:
        block = self.block_by_id[bid]
        return {
            "block_id": bid,
            "start": start,
            "end": end,
            "quote": str(block.get("text") or "")[start:end],
            "verified": True,
            "match": match,
            "loc": block.get("loc"),
            "section": _as_list(block.get("section")),
        }

    # --- требования ----------------------------------------------------
    def req_text(self, rid: str) -> str:
        r = self.req_by_id.get(rid) or {}
        return str(r.get("text") or "")

    def req_body(self, rid: str) -> str:
        return req_body(self.req_by_id.get(rid) or {})

    def req_section(self, rid: str) -> list:
        r = self.req_by_id.get(rid) or {}
        for bid in _as_list(r.get("block_ids")) + [
            e.get("block_id") for e in _as_list(r.get("evidence")) if isinstance(e, dict)
        ]:
            b = self.block_by_id.get(bid)
            if b is not None:
                return _as_list(b.get("section"))
        return []

    def req_blocks(self, rid: str) -> list:
        r = self.req_by_id.get(rid) or {}
        out = [b for b in _as_list(r.get("block_ids")) if b in self.block_by_id]
        for e in _as_list(r.get("evidence")):
            if isinstance(e, dict) and e.get("block_id") in self.block_by_id and e["block_id"] not in out:
                out.append(e["block_id"])
        return out

    def block_reqs(self, block_id: str) -> list:
        """Требования, которым принадлежит блок (источник опоры)."""
        cache = self.__dict__.setdefault("_block_reqs", None)
        if cache is None:
            cache = {}
            for r in self.reqs:
                for b in self.req_blocks(r["id"]):
                    cache.setdefault(b, []).append(r["id"])
            self.__dict__["_block_reqs"] = cache
        return cache.get(block_id, [])

    def req_pos(self, rid: str) -> tuple:
        blocks = self.req_blocks(rid)
        return min((self.block_order[b], 0) for b in blocks) if blocks else (10**9, 0)

    def req_label(self, rid: str) -> str:
        r = self.req_by_id.get(rid) or {}
        sid = r.get("source_id")
        return f"{sid} ({rid})" if sid else str(rid)

    def req_evidence(self, rid: str) -> list:
        r = self.req_by_id.get(rid) or {}
        evs = [self.verify(e) for e in _as_list(r.get("evidence")) if isinstance(e, dict)]
        if evs:
            return evs
        text = self.req_text(rid)
        loc = self.locate(text, self.req_blocks(rid)) if text else None
        return [loc] if loc and loc["match"] != "fuzzy" else []


def _report_digest(report: dict) -> str:
    body = {k: v for k, v in report.items() if k != "diff"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Сопоставление требований
# ---------------------------------------------------------------------------


def _same_sid(a: Any, b: Any) -> bool:
    return bool(a) and bool(b) and _norm(str(a)) == _norm(str(b))


def _last_heading(section: list) -> str:
    return _norm(str(section[-1])) if section else ""


def _changes(prev: _Edition, cur: _Edition, oid: str, nid: str) -> list[str]:
    o, n = prev.req_by_id[oid], cur.req_by_id[nid]
    out = []
    if _norm(req_body(o)) != _norm(req_body(n)):
        out.append("reworded")
    if (o.get("source_id") or None) != (n.get("source_id") or None):
        out.append("renumbered")
    if [_norm(str(s)) for s in prev.req_section(oid)] != [_norm(str(s)) for s in cur.req_section(nid)]:
        out.append("moved")
    return out


def _align_requirements(prev: _Edition, cur: _Edition, ask: AskFn | None, warnings: list) -> dict:
    """Возвращает {old_id: link}. Связь: same | split | merge | ambiguous | missing."""
    links: dict[str, dict] = {}
    olds = sorted(prev.reqs, key=lambda r: (prev.req_pos(r["id"]), _natural(r["id"])))
    news = sorted(cur.reqs, key=lambda r: (cur.req_pos(r["id"]), _natural(r["id"])))
    used: set = set()

    def text(r: dict) -> str:
        return req_body(r)

    def link(oid: str, nids: list, relation: str, score: float, via: str, **extra: Any) -> None:
        changes: list[str] = []
        for nid in nids:
            for c in _changes(prev, cur, oid, nid):
                if c not in changes:
                    changes.append(c)
        if relation in ("split", "merge") and "reworded" not in changes:
            changes.append("reworded")
        links[oid] = {
            "old_ids": [oid],
            "new_ids": list(nids),
            "relation": relation,
            "changes": changes,
            "score": round(score, 3),
            "via": via,
            **extra,
        }

    # 0. тот же текст после нормализации (перенос, перенумерация, новые id)
    for o in olds:
        nt = _norm(text(o))
        for n in news:
            if n["id"] not in used and nt and _norm(text(n)) == nt:
                link(o["id"], [n["id"]], "same", 1.0, "text")
                used.add(n["id"])
                break

    def rem_old() -> list:
        return [o for o in olds if o["id"] not in links]

    def rem_new() -> list:
        return [n for n in news if n["id"] not in used]

    # 1. разделение одного пункта на несколько
    for o in rem_old():
        olds_left = rem_old()
        parts = []
        for n in rem_new():
            c = containment(text(n), text(o))
            if c < PART_CONTAINMENT or len(_shingles(text(n))) >= len(_shingles(text(o))):
                continue
            best = max(olds_left, key=lambda x: (containment(text(n), text(x)), -olds.index(x)))
            if best["id"] == o["id"]:
                parts.append(n)
        if len(parts) >= 2 and containment(text(o), " ".join(text(p) for p in parts)) >= UNION_COVERAGE:
            link(
                o["id"],
                [p["id"] for p in parts],
                "split",
                containment(text(o), " ".join(text(p) for p in parts)),
                "text",
            )
            used.update(p["id"] for p in parts)

    # 2. слияние нескольких пунктов в один
    for n in rem_new():
        news_left = rem_new()
        srcs = []
        for o in rem_old():
            c = containment(text(o), text(n))
            if c < PART_CONTAINMENT or len(_shingles(text(o))) >= len(_shingles(text(n))):
                continue
            best = max(news_left, key=lambda x: (containment(text(o), text(x)), -news.index(x)))
            if best["id"] == n["id"]:
                srcs.append(o)
        if len(srcs) >= 2 and containment(text(n), " ".join(text(s) for s in srcs)) >= UNION_COVERAGE:
            group = [s["id"] for s in srcs]
            for s in srcs:
                link(s["id"], [n["id"]], "merge", containment(text(s), text(n)), "text", merged_with=group)
            used.add(n["id"])

    # 3. пары 1:1 по сходству текста с надбавками за source_id и раздел
    def scored(o: dict, n: dict) -> tuple[float, float, list]:
        base = text_similarity(text(o), text(n))
        why = [f"сходство текста {base:.2f}"]
        bonus = 0.0
        if _same_sid(o.get("source_id"), n.get("source_id")):
            bonus += 0.10
            why.append(f"тот же номер {o.get('source_id')}")
        if _last_heading(prev.req_section(o["id"])) and _last_heading(prev.req_section(o["id"])) == _last_heading(
            cur.req_section(n["id"])
        ):
            bonus += 0.05
            why.append("тот же раздел")
        return base + bonus, base, why

    pairs = []
    by_old: dict[int, list] = {}
    by_new: dict[int, list] = {}
    for o in rem_old():
        for n in rem_new():
            score, base, why = scored(o, n)
            if base >= REQ_CANDIDATE:
                oi, ni = olds.index(o), news.index(n)
                pairs.append((score, base, oi, ni, why))
                by_old.setdefault(oi, []).append((score, ni))
                by_new.setdefault(ni, []).append((score, oi))
    pairs.sort(key=lambda p: (-p[0], p[2], p[3]))
    for score, base, oi, ni, why in pairs:
        o, n = olds[oi], news[ni]
        if o["id"] in links or n["id"] in used:
            continue
        rivals = [s for s, nj in by_old[oi] if nj != ni and news[nj]["id"] not in used]
        rivals += [s for s, oj in by_new[ni] if oj != oi and olds[oj]["id"] not in links]
        margin_ok = all(score - r >= REQ_MARGIN for r in rivals)
        supported = len(why) > 1
        if margin_ok and (base >= REQ_CONFIDENT or supported):
            link(o["id"], [n["id"]], "same", score, "text", why=why)
            used.add(n["id"])

    # 4. неоднозначные: кандидаты есть, уверенности нет
    for o in rem_old():
        cands = []
        for n in rem_new():
            score, base, why = scored(o, n)
            if base >= REQ_CANDIDATE:
                cands.append(
                    {"new_id": n["id"], "score": round(score, 3), "why": why, "new_quote": _short(text(n), 160)}
                )
        cands.sort(key=lambda c: (-c["score"], _natural(c["new_id"])))
        if not cands:
            continue
        if ask is not None:
            verdict = _ask_identity(ask, prev, cur, o, cands, warnings)
            if verdict is not None:
                link(
                    o["id"],
                    [verdict["new_id"]],
                    "same",
                    verdict["score"],
                    "model",
                    why=[verdict["reason"]],
                    model_quotes=verdict["quotes"],
                )
                used.add(verdict["new_id"])
                continue
        links[o["id"]] = {
            "old_ids": [o["id"]],
            "new_ids": [],
            "relation": "ambiguous",
            "changes": [],
            "score": cands[0]["score"],
            "via": "text",
            "candidates": cands,
            "detail": f"Для {prev.req_label(o['id'])} нет однозначной пары в новой редакции: "
            f"{len(cands)} кандидат(а) со сходством ниже уверенного.",
        }

    # 5. исчезнувшие: объясняем, почему
    for o in rem_old():
        code, detail = _explain_missing(prev, cur, o)
        links[o["id"]] = {
            "old_ids": [o["id"]],
            "new_ids": [],
            "relation": "missing",
            "changes": [],
            "score": 0.0,
            "via": "text",
            "missing": code,
            "detail": detail,
        }
    return links


def _explain_missing(prev: _Edition, cur: _Edition, o: dict) -> tuple[str, str]:
    label = prev.req_label(o["id"])
    quotes = [e.get("quote") for e in _as_list(o.get("evidence")) if isinstance(e, dict) and e.get("quote")]
    quotes = quotes or [str(o.get("text") or "")]
    hits = [cur.locate(q) for q in quotes]
    if hits and all(h is not None and h["match"] != "fuzzy" for h in hits):
        bid = hits[0]["block_id"]
        return "extraction_gap", (
            f"Текст требования {label} есть в новой редакции (блок {bid}), но требование не извлечено. "
            "Это пробел извлечения, а не правка."
        )
    section = prev.req_section(o["id"])
    path = tuple(_norm(str(h)) for h in section)
    heading = " › ".join(str(h) for h in (section[1:] or section)) if section else ""
    if heading and (path not in cur.section_paths or _norm(str(section[-1])) not in cur.headings):
        detail = f"Раздел «{heading}» с требованием {label} отсутствует в извлечении новой редакции"
        if cur.partial_read:
            detail += "; вероятно, потерян при чтении: " + "; ".join(_short(w, 120) for w in cur.partial_read)
        elif cur.doc_warnings:
            detail += "; предупреждения чтения: " + "; ".join(_short(w, 120) for w in cur.doc_warnings)
        else:
            detail += " (удалён автором или не прочитан)"
        return "section_missing", detail + ". Удаление источника не доказывает исправления."
    return "removed", (
        f"Формулировка требования {label} не найдена в новой редакции. Удаление не доказывает исправления: "
        "нужно подтвердить, что обязательство снято намеренно."
    )


_IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "match_id": {"type": "string"},
        "old_quote": {"type": "string"},
        "new_quote": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["match_id", "old_quote", "new_quote", "reason"],
    "additionalProperties": False,
}


def _ask_identity(ask: AskFn, prev: _Edition, cur: _Edition, o: dict, cands: list, warnings: list) -> dict | None:
    """Просит движок подтвердить смысловую идентичность и принимает ответ только с проверяемыми цитатами."""

    def item(ed: _Edition, rid: str) -> dict:
        r = ed.req_by_id[rid]
        return {"id": rid, "source_id": r.get("source_id"), "text": ed.req_text(rid), "section": ed.req_section(rid)}

    payload = {
        "task": (
            "Сравни две редакции ТЗ. Определи, какой пункт новой редакции (candidates) выражает то же "
            "обязательство, что и пункт прошлой редакции (old): тот же субъект, условие и действие, даже если "
            "формулировка, номер или раздел изменились. Если ни один — верни match_id пустой строкой. "
            "Иначе процитируй дословно общий по смыслу фрагмент: old_quote из old.text и new_quote из текста "
            "выбранного кандидата, не короче двух слов."
        ),
        "input": {"old": item(prev, o["id"]), "candidates": [item(cur, c["new_id"]) for c in cands]},
        "context": {"mode": "none"},
    }
    try:
        answer = ask("diff_identity", payload, _IDENTITY_SCHEMA)
    except Exception as exc:  # транспорт движка: сбой не должен ломать сравнение
        warnings.append(
            _warn("identity_ask_failed", f"Уточнение идентичности {o['id']} не выполнено: {type(exc).__name__}.")
        )
        return None
    if not isinstance(answer, dict) or not answer.get("match_id"):
        return None
    mid = answer["match_id"]
    if mid not in {c["new_id"] for c in cands}:
        warnings.append(
            _warn(
                "identity_unverified",
                f"Модель указала {mid}, которого нет среди кандидатов для {o['id']}; ответ отброшен.",
            )
        )
        return None
    oq, nq = str(answer.get("old_quote") or ""), str(answer.get("new_quote") or "")
    ok = (
        len(_words(oq)) >= 2
        and len(_words(nq)) >= 2
        and _norm(oq) in _norm(prev.req_text(o["id"]))
        and _norm(nq) in _norm(cur.req_text(mid))
    )
    if not ok:
        warnings.append(
            _warn(
                "identity_unverified", f"Цитаты модели для пары {o['id']}→{mid} не найдены в текстах; ответ отброшен."
            )
        )
        return None
    score = next(c["score"] for c in cands if c["new_id"] == mid)
    return {
        "new_id": mid,
        "score": score,
        "reason": _short(str(answer.get("reason") or "подтверждено движком"), 200),
        "quotes": {"old": oq, "new": nq},
    }


# ---------------------------------------------------------------------------
# Замечания
# ---------------------------------------------------------------------------


class _Finding:
    def __init__(self, ed: _Edition, raw: dict):
        self.ed = ed
        self.raw = raw
        self.id = raw["id"]
        self.kind = _norm(str(raw.get("kind") or ""))
        self.criterion = _norm(str(raw.get("criterion") or ""))
        self.severity = str(raw.get("severity") or "").lower()
        self.title = str(raw.get("title") or "")
        self.impact = str(raw.get("impact") or "")
        self.status = raw.get("status")
        self.scope = raw.get("scope")
        # порядок внутри находки — по месту в документе: перестановка входных списков ничего не меняет
        self.req_ids = sorted(
            dict.fromkeys(r for r in _as_list(raw.get("req_ids")) if r in ed.req_by_id),
            key=lambda r: (ed.req_pos(r), _natural(r)),
        )
        self.unknown_reqs = [r for r in _as_list(raw.get("req_ids")) if r not in ed.req_by_id]
        self.evidence = sorted(
            (ed.verify(e) for e in _as_list(raw.get("evidence")) if isinstance(e, dict)),
            key=lambda e: (
                ed.block_order.get(e.get("block_id"), 10**9),
                e.get("start") or 0,
                e.get("end") or 0,
                str(e.get("quote")),
            ),
        )
        hints = [h for h in _as_list(raw.get("hints")) if isinstance(h, dict) and h.get("quote")]
        self.quotes = [e["quote"] for e in self.evidence if e.get("quote")]
        self.quotes += [h["quote"] for h in hints if h["quote"] not in self.quotes]
        self.witness = raw.get("witness") if isinstance(raw.get("witness"), dict) else None
        for key in ("evidence_a", "evidence_b"):  # опоры сторон противоречия тоже опоры замечания
            w = (self.witness or {}).get(key)
            if isinstance(w, dict) and w.get("quote") and w["quote"] not in self.quotes:
                self.quotes.append(w["quote"])
        # (цитата, блок прошлой редакции) — источник опоры для поиска в новой редакции
        self.anchor_src: list[tuple[str, str | None]] = []
        for x in self.evidence + hints + [(self.witness or {}).get(k) for k in ("evidence_a", "evidence_b")]:
            if isinstance(x, dict) and x.get("quote"):
                item = (x["quote"], x.get("block_id"))
                if item not in self.anchor_src:
                    self.anchor_src.append(item)
        self.inspected = [b for b in _as_list(raw.get("inspected_block_ids"))]
        self.key = self.id  # у части сгруппированной находки: «F-001@R-002»
        self.part: str | None = None  # пункт прошлой редакции, к которому относится часть
        self.whole_req_ids: list = list(self.req_ids)
        self.is_conflict = self.witness is not None or self.kind in _CONFLICT_KINDS
        self.is_omission = bool(self.inspected) or self.kind in _OMISSION_KINDS
        self.pos = self._pos()

    def _pos(self) -> tuple:
        spots = [
            (self.ed.block_order[e["block_id"]], e.get("start") or 0)
            for e in self.evidence
            if e.get("block_id") in self.ed.block_order
        ]
        spots += [self.ed.req_pos(r) for r in self.req_ids]
        return min(spots) if spots else (10**9, 0)

    def sev_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 3)


def _split_by_source(fo: _Finding, prev: _Edition, cur: _Edition, links: dict) -> list:
    """Части находки одного пункта, сгруппированной по нескольким пунктам (правила объединяют одинаковый
    дефект похожих формулировок). Делится, только если судьбы источников в новой редакции расходятся:
    один пункт правили, а другой нет. Иначе находка сравнивается целиком, как раньше."""
    if fo.is_conflict or fo.is_omission or fo.kind == "duplicate" or fo.criterion.startswith("set_"):
        return [fo]
    if len(fo.req_ids) < 2:
        return [fo]
    parts = []
    for r in fo.req_ids:
        blocks = set(prev.req_blocks(r))
        ev = [e for e in _as_list(fo.raw.get("evidence")) if isinstance(e, dict) and e.get("block_id") in blocks]
        if not ev:
            return [fo]  # опору части не отделить — делить нельзя
        hints = [h for h in _as_list(fo.raw.get("hints")) if isinstance(h, dict) and h.get("block_id") in blocks]
        part = _Finding(prev, dict(fo.raw, req_ids=[r], evidence=ev, hints=hints))
        part.key, part.part, part.whole_req_ids = f"{fo.id}@{r}", r, list(fo.req_ids)
        parts.append(part)

    def unchanged(part: _Finding) -> bool:
        lk = links.get(part.part) or {}
        if lk.get("relation") != "same" or "reworded" in lk.get("changes", []):
            return False
        own = [b for n in lk["new_ids"] for b in cur.req_blocks(n)]
        return all((a := cur.locate(q, own, only=True)) is not None and a["match"] != "fuzzy" for q in part.quotes)

    return parts if len({unchanged(p) for p in parts}) > 1 else [fo]


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _numbers(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:[.,]\d+)?", _norm(text or "")))


def witness_condition(w: dict | None) -> str:
    """Условие сценария из witness.input: строка, объект №06 {description, assignments, …} или его str().

    Координаты и id блоков из document_data в условие не входят: они зависят от редакции."""
    inp = (w or {}).get("input")
    if isinstance(inp, str) and inp.lstrip().startswith("{"):
        try:
            inp = ast.literal_eval(inp)
        except (ValueError, SyntaxError):
            try:
                inp = json.loads(inp)
            except ValueError:
                pass
    if isinstance(inp, dict):
        desc = str(inp.get("description") or "")
        assign = inp.get("assignments") if isinstance(inp.get("assignments"), dict) else {}
        tail = "; ".join(f"{k} = {v}" for k, v in assign.items() if f"{k} = {v}" not in desc)
        return "; ".join(x for x in (desc, tail) if x)
    return str(inp or "")


def _condition_outcome(fo: _Finding, fn: _Finding) -> dict:
    """Условие (witness.input) и исход (outcome_a/b) двух противоречий: совпадают ли сценарии."""
    wi_o, wi_n = witness_condition(fo.witness), witness_condition(fn.witness)
    out_o = " ".join(str(fo.witness.get(k) or "") for k in ("outcome_a", "outcome_b"))
    out_n = " ".join(str(fn.witness.get(k) or "") for k in ("outcome_a", "outcome_b"))
    sim = text_similarity(wi_o, wi_n) if wi_o and wi_n else None
    no, nn = _numbers(wi_o), _numbers(wi_n)
    num = len(no & nn) / len(no | nn) if no and nn else None
    same = None
    if sim is not None:
        same = _norm(wi_o) == _norm(wi_n) or (sim >= 0.8 and (num is None or num >= 0.5))
    return {
        "condition": round(sim, 2) if sim is not None else None,
        "condition_numbers": round(num, 2) if num is not None else None,
        "outcome": round(text_similarity(out_o, out_n), 2) if out_o.strip() and out_n.strip() else None,
        "same_condition": same,
    }


def _finding_score(
    fo: _Finding, fn: _Finding, mapped: set, anchors: list, cur: _Edition, source_blocks: set
) -> tuple[float, dict]:
    """Тождество первопричины: источник, условие и исход, затем место, тип дефекта и предмет."""
    detail: dict[str, Any] = {}
    if mapped and fn.req_ids and not (mapped & set(fn.req_ids)):
        # пункты прежней находки в новой редакции и пункты новой находки не пересекаются:
        # одинаковое название и одинаковые цитаты не делают их одной первопричиной
        detail["source"] = "другой источник"
        return 0.0, detail
    req_ov = _overlap(mapped, set(fn.req_ids)) if mapped and fn.req_ids else None
    if req_ov is not None:
        detail["requirements"] = round(req_ov, 2)
    anc: float | None = None
    if anchors and fn.evidence:
        anc = 0.0
        for a in anchors:
            exact = a["match"] not in ("fuzzy",) and not a.get("ambiguous")
            for e in fn.evidence:
                bid = e.get("block_id")
                if e.get("verified") and a["block_id"] == bid:
                    s2, e2 = e.get("start") or 0, e.get("end") or 0
                    if a["start"] < e2 and s2 < a["end"]:
                        anc = max(anc, 1.0 if exact else 0.75)  # то же место
                    elif cur.sentence_of(bid, a["start"]) == cur.sentence_of(bid, s2):
                        anc = max(anc, 0.6)  # то же предложение, соседний фрагмент
                    else:
                        anc = max(anc, 0.2 if exact else 0.4)  # другое предложение того же пункта
                # похожая цитата засчитывается только в блоках своего источника
                if bid in source_blocks and text_similarity(a["quote"], e.get("quote") or "") >= 0.6:
                    anc = max(anc, 1.0 if exact else 0.8)
        detail["anchors"] = round(anc, 2)
    elif fo.quotes and fn.quotes and not mapped:
        q = max(text_similarity(a, b) for a in fo.quotes for b in fn.quotes)
        anc = 0.8 if q >= 0.6 else 0.0
        detail["quotes"] = round(q, 2)
    if anc is not None:
        place = max(anc, 0.4 * (req_ov or 0.0))  # общий пункт — только нижняя граница
    else:
        place = 0.8 * (req_ov or 0.0)
    kind_eq = bool(fo.kind) and fo.kind == fn.kind
    crit_eq = bool(fo.criterion) and fo.criterion == fn.criterion
    typ = 1.0 if kind_eq and crit_eq else 0.6 if kind_eq or crit_eq else 0.0
    content = text_similarity(fo.title, fn.title)  # impact часто шаблонный, в тождество не входит
    detail.update(place=round(place, 2), type=typ, content=round(content, 2))
    if fo.witness and fn.witness:
        detail.update(_condition_outcome(fo, fn))
    if place == 0.0 and not (fo.scope == "set" and fn.scope == "set" and content >= 0.5 and not mapped):
        return 0.0, detail
    score = 0.5 * place + 0.2 * typ + 0.3 * content
    if anc is not None and anc <= 0.2:
        # точные опоры указывают в разные предложения: похожий заголовок не делает их одной первопричиной
        score = min(score, FIND_CONFIDENT - 0.01)
        detail["capped"] = "опоры в разных предложениях"
    if detail.get("same_condition") is False:
        score = min(score, FIND_CONFIDENT - 0.01)
        detail["capped"] = "другое условие сценария"
    if typ == 0.0:
        # другой и тип дефекта, и критерий (конфликт ≠ неоднозначность): не первопричина и не кандидат
        score = min(score, FIND_CANDIDATE - 0.01)
        detail["capped"] = "другой тип дефекта и критерий"
    return score, detail


def _match_findings(prev: _Edition, cur: _Edition, olds: list, news: list, links: dict) -> tuple[list, dict]:
    """Группы {old: [...], new: [...]} и слабые кандидаты для неоднозначных."""
    mapped: dict[str, set] = {}
    anchors: dict[str, list] = {}
    source_blocks: dict[str, set] = {}
    present: dict[str, list] = {}  # цитаты, дословно сохранившиеся в своём источнике
    for fo in olds:
        m: set = set()
        for rid in fo.req_ids:
            m.update(links.get(rid, {}).get("new_ids", []))
        mapped[fo.key] = m
        prefer = [b for nid in sorted(m, key=_natural) for b in cur.req_blocks(nid)]
        source_blocks[fo.key] = set(prefer)
        found: list = []
        for q, old_bid in fo.anchor_src:
            # источник опоры: пункты прошлой редакции, которым принадлежал её блок, и их пары в новой
            src_old = prev.block_reqs(old_bid) if old_bid else []
            src_new = [n for o in src_old for n in links.get(o, {}).get("new_ids", [])]
            own = [b for n in src_new for b in cur.req_blocks(n)]
            if own:
                a = cur.locate(q, own, only=True)
                if a is not None and a["match"] != "fuzzy":
                    present.setdefault(fo.key, []).append(q)
            elif src_old or m:
                a = cur.locate(q, prefer, only=True) if prefer else None  # пункт исчез — опоры нет
                if a is not None and a["match"] != "fuzzy":
                    present.setdefault(fo.key, []).append(q)
            else:
                a = cur.locate(q, prefer)
                if a is not None and a["match"] != "fuzzy":
                    hits = sum(1 for b in cur.blocks if _norm(q) in cur.block_norm[b["id"]][0])
                    a["ambiguous"] = hits > 1  # одинаковый текст в нескольких местах: место не доказано
                    present.setdefault(fo.key, []).append(q)
            if a is None or any(
                b["block_id"] == a["block_id"]
                and a["start"] < b["end"]
                and b["start"] < a["end"]
                and (a["match"] == "fuzzy" or (a["start"], a["end"]) == (b["start"], b["end"]))
                for b in found
            ):
                continue  # та же точка новой редакции уже найдена (например, нечёткий двойник дубля)
            found.append(a)
        anchors[fo.key] = found

    scores: dict[tuple[int, int], tuple[float, dict]] = {}
    lookalikes: dict[int, list] = {}  # похожие по названию находки из другого источника — для объяснения
    for i, fo in enumerate(olds):
        for j, fn in enumerate(news):
            s, d = _finding_score(fo, fn, mapped[fo.key], anchors[fo.key], cur, source_blocks[fo.key])
            if s >= FIND_CANDIDATE:
                scores[(i, j)] = (s, d)
            elif fo.kind == fn.kind and text_similarity(fo.title, fn.title) >= 0.8:
                lookalikes.setdefault(i, []).append((j, d.get("source") or d.get("capped") or "место другое"))

    # честная неопределённость: источник прежней находки не определён, а два новых кандидата равноправны —
    # выбирать по порядку нельзя (иначе «сохранилось» или «исправлено» зависит от того, кто первый в списке)
    ties: dict[int, list[int]] = {}
    for i, fo in enumerate(olds):
        opts = sorted(
            ((s, j) for (a, j), (s, _) in scores.items() if a == i and s >= FIND_CONFIDENT), key=lambda x: (-x[0], x[1])
        )
        if len(opts) >= 2 and not mapped[fo.key] and opts[0][0] - opts[1][0] < TIE_EPS:
            ties[i] = [j for s, j in opts if opts[0][0] - s < TIE_EPS]

    def best_new(i: int) -> int | None:
        if i in ties:
            return None
        opts = [(s, -j) for (a, j), (s, _) in scores.items() if a == i and s >= FIND_CONFIDENT]
        return -max(opts)[1] if opts else None

    def best_old(j: int) -> int | None:
        opts = [(s, -i) for (i, b), (s, _) in scores.items() if b == j and s >= FIND_CONFIDENT and i not in ties]
        return -max(opts)[1] if opts else None

    group_of_old: dict[int, int] = {}
    group_of_new: dict[int, int] = {}
    groups: list[dict] = []
    for i in range(len(olds)):
        j = best_new(i)
        if j is not None and best_old(j) == i:
            group_of_old[i] = group_of_new[j] = len(groups)
            groups.append({"old": [i], "new": [j]})
    for j in range(len(news)):  # разделение первопричины: новая находка тянется к уже сопоставленной старой
        i = best_old(j)
        if j not in group_of_new and i is not None and i in group_of_old:
            g = group_of_old[i]
            groups[g]["new"].append(j)
            group_of_new[j] = g
    for i in range(len(olds)):  # слияние дублей: старая тянется к уже сопоставленной новой
        j = best_new(i)
        if i not in group_of_old and j is not None and j in group_of_new:
            g = group_of_new[j]
            groups[g]["old"].append(i)
            group_of_old[i] = g

    weak: dict[int, list] = {}
    for (i, j), (s, d) in scores.items():
        if i in group_of_old or j in group_of_new:
            continue
        weak.setdefault(i, []).append((s, j, d))
    for i in weak:
        weak[i].sort(key=lambda x: (-x[0], x[1]))
    for g in groups:
        g["scores"] = {
            f"{olds[i].key}->{news[j].id}": scores[(i, j)] for i in g["old"] for j in g["new"] if (i, j) in scores
        }
    return groups, {
        "weak": weak,
        "mapped": mapped,
        "anchors": anchors,
        "lookalikes": lookalikes,
        "present": present,
        "source_blocks": source_blocks,
        "ties": ties,
        "scores": scores,
    }


# ---------------------------------------------------------------------------
# Доказательство закрытия
# ---------------------------------------------------------------------------


def _check_reqs(check: dict) -> set:
    out = set(_as_list(check.get("req_ids")))
    if check.get("req_id") is not None:
        out.add(check["req_id"])
    return out


def _check_status(check: dict) -> str:
    raw = _norm(str(check.get("status") or check.get("result") or ""))
    if raw in _POSITIVE:
        return "positive"
    if raw in _NEGATIVE:
        return "negative"
    return "skipped"  # unknown, na и всё прочее: результата нет


def _family(criterion: Any) -> str:
    c = _norm(str(criterion or ""))
    return _CRITERION_FAMILY.get(c, c)


def _check_ref(c: dict) -> str:
    who = c.get("req_id") or "/".join(sorted(map(str, _check_reqs(c))))
    return f"{who}/{c.get('criterion') or '—'}"


def _check_brief(c: dict) -> dict:
    return {k: c.get(k) for k in ("req_id", "criterion", "status", "reason", "source") if c.get(k) is not None}


def old_input_of(fo: _Finding) -> str:
    return witness_condition(fo.witness)


def _affected(prev: _Edition, fo: _Finding) -> list[tuple[str, str]]:
    """Пары (требование прошлой редакции, критерий), в которых проявлялось замечание.

    Берутся из прошлых проверок «issue» с finding_ids (как пишет движок); иначе — требования
    замечания с его критерием."""
    pairs: list[tuple[str, str]] = []
    for c in prev.checks:
        if fo.id in _as_list(c.get("finding_ids")) and _check_status(c) == "negative":
            pairs += [(rid, _family(c.get("criterion"))) for rid in sorted(_check_reqs(c), key=_natural)]
    if fo.part is not None:
        pairs = [p for p in pairs if p[0] == fo.part]
    if not pairs:
        pairs = [(rid, _family(fo.criterion)) for rid in fo.req_ids]
    return sorted(set(pairs), key=lambda p: (prev.req_pos(p[0]), _natural(p[0]), p[1]))


def _pair_coverage(fo: _Finding, cur: _Edition, links: dict, status: str) -> list[dict]:
    """Покрытие новой редакции для пары «правило ↔ критерий» из сторон прежнего противоречия."""
    side_of = {n: o for o in fo.req_ids for n in links.get(o, {}).get("new_ids", [])}
    out = []
    for c in sorted(cur.coverage, key=lambda c: (cur.req_pos(c["req_id"]), _natural(c["req_id"]))):
        rule = c["req_id"]
        if rule not in side_of or str(c.get("status")) != status:
            continue
        accs = [a for a in _as_list(c.get("acceptance_ids")) if a in side_of and side_of[a] != side_of[rule]]
        if accs:
            out.append({"req_id": rule, "acceptance_ids": sorted(accs, key=_natural), "coverage": c})
    return out


def _coverage_text(cur: _Edition, items: list[dict], status: str) -> str:
    return "; ".join(
        f"покрытие {cur.req_label(x['req_id'])} критерием {', '.join(cur.req_label(a) for a in x['acceptance_ids'])}"
        f" — {status}"
        for x in items
    )


def _coverage_proof(fo: _Finding, prev: _Edition, cur: _Edition, links: dict) -> dict | None:
    """Покрытие приёмкой (№06) как доказательство: правило и его критерий приёмки — стороны прежнего
    противоречия — в новой редакции согласованы (coverage.status = covered) и опоры покрытия проверяемы."""
    side_of = {n: o for o in fo.req_ids for n in links.get(o, {}).get("new_ids", [])}
    if len(set(side_of.values())) < 2:
        return None
    for c in sorted(cur.coverage, key=lambda c: (cur.req_pos(c["req_id"]), _natural(c["req_id"]))):
        rule = c["req_id"]
        if rule not in side_of or str(c.get("status")) != "covered":
            continue
        accs = sorted(
            (a for a in _as_list(c.get("acceptance_ids")) if a in side_of and side_of[a] != side_of[rule]), key=_natural
        )
        evs = [cur.verify(x) for x in _as_list(c.get("evidence")) if isinstance(x, dict)]
        if not accs or not evs or not all(e["verified"] for e in evs):
            continue
        old_rule, old_accs = side_of[rule], {side_of[a] for a in accs}
        before = [
            str(p.get("status"))
            for p in prev.coverage
            if p["req_id"] == old_rule and set(_as_list(p.get("acceptance_ids"))) & old_accs
        ]
        ref = f"coverage {rule}↔{','.join(accs)}"
        return {
            "kind": "coverage_reconciled",
            "checks": [],
            "check_refs": [ref],
            "coverage": {
                "req_id": rule,
                "acceptance_ids": accs,
                "status": "covered",
                "previous_status": before[0] if before else None,
                "explanation": c.get("explanation"),
            },
            "outcome": c.get("explanation") or None,
            "evidence": evs,
        }
    return None


def _closure_proof(
    fo: _Finding, prev: _Edition, cur: _Edition, links: dict, *, stage_covered: bool = False
) -> tuple[dict | None, str, str]:
    """(proof | None, reason_code, explanation). Нужна явная проверка «pass» в новой редакции.

    stage_covered: этап, нашедший замечание, во втором прогоне завершён — тогда охват берётся по этапу,
    а Requirement.review_status (сводный по всем этапам) не учитывается."""
    pairs = _affected(prev, fo)
    targets = [(o, fam, n) for o, fam in pairs for n in links.get(o, {}).get("new_ids", [])]

    partial = []
    for _o, _fam, n in [] if stage_covered else dict.fromkeys(targets):
        r = cur.req_by_id.get(n) or {}
        if r.get("review_status") in ("partial", "not_reviewed"):
            partial.append(f"{cur.req_label(n)} — {r.get('review_reason') or r.get('review_status')}")
    if partial:
        return (
            None,
            "recheck_skipped",
            "Обязательство в новой редакции проверено не полностью: " + "; ".join(dict.fromkeys(partial)) + ".",
        )

    negative: list[dict] = []
    positive: dict[tuple[str, str], list[dict]] = {}
    missing: list[str] = []
    for o, fam, n in targets:
        cs = sorted(
            (c for c in cur.checks if n in _check_reqs(c) and _family(c.get("criterion")) == fam),
            key=lambda c: (_check_ref(c), str(c.get("status")), str(c.get("reason"))),
        )
        neg = [c for c in cs if _check_status(c) == "negative"]
        pos = [c for c in cs if _check_status(c) == "positive"]
        if neg:
            negative += neg
        elif pos:
            positive.setdefault((o, n), []).extend(pos)
        else:
            missing.append(f"{n}/{fam}")
    still = _pair_coverage(fo, cur, links, "conflict") if fo.is_conflict else []
    if still and not negative:
        return (
            None,
            "recheck_failed",
            ("Профильный этап по-прежнему отмечает противоречие: " + _coverage_text(cur, still, "conflict") + "."),
        )
    if negative:
        refs = ", ".join(dict.fromkeys(_check_ref(c) for c in negative))
        fids = sorted({f for c in negative for f in _as_list(c.get("finding_ids"))}, key=_natural)
        tail = f" (замечания {', '.join(map(str, fids))})" if fids else ""
        return (
            None,
            "recheck_failed",
            (f"Перепроверка {refs} в новой редакции сообщает нарушение{tail}, но пара прежнего замечания не найдена."),
        )
    # противоречие правила и критерия приёмки: результат профильного этапа — покрытие этой пары
    cov = _coverage_proof(fo, prev, cur, links) if fo.is_conflict else None
    if missing:
        if cov is not None:
            return cov, "rechecked_coverage", ""
        return (
            None,
            "recheck_missing",
            (f"В новом отчёте нет результата проверки {', '.join(dict.fromkeys(missing))} (нужен статус pass)."),
        )
    pos_checks = [c for cs in positive.values() for c in cs]

    def verified(c: dict) -> tuple[list, bool]:
        evs = [cur.verify(x) for x in _as_list(c.get("evidence")) if isinstance(x, dict)]
        return [e for e in evs if e["verified"]], all(e["verified"] for e in evs)

    if fo.is_conflict:
        if not targets:
            return None, "recheck_missing", "Стороны противоречия не сопоставлены с новой редакцией."
        broken = [c for c in pos_checks if not verified(c)[1]]
        if broken:
            return (
                None,
                "recheck_missing",
                (
                    "Опоры перепроверки не совпадают с текстом новой редакции: "
                    + ", ".join(_check_ref(c) for c in broken)
                    + "."
                ),
            )
        old_input = old_input_of(fo)

        def scenario(c: dict) -> str:
            return str(c.get("scenario") or c.get("witness_input") or (c.get("witness") or {}).get("input") or "")

        matched = [
            c
            for c in pos_checks
            if scenario(c)
            and (_norm(scenario(c)) == _norm(old_input) or text_similarity(scenario(c), old_input) >= SCENARIO_MATCH)
        ]
        if old_input and not matched and cov is not None:
            return cov, "rechecked_coverage", ""
        if old_input and not matched:
            return (
                None,
                "recheck_missing",
                (
                    f"Стороны проверены без замечаний, но нет перепроверки сценария «{_short(old_input, 120)}» "
                    "с единым исходом; закрыть противоречие нельзя."
                ),
            )
        evidence: list = []
        for o in dict.fromkeys(o for o, _f, _n in targets):  # опора каждой стороны в новом тексте
            side = [c for (oo, _n), cs in positive.items() if oo == o for c in cs]
            evs = [e for c in side for e in verified(c)[0]]
            if not evs:
                evs = [e for (oo, n) in positive if oo == o for e in cur.req_evidence(n) if e.get("verified")]
            evidence += evs
        used = matched or pos_checks
        return (
            {
                "kind": "conflict_reconciled",
                "checks": [_check_brief(c) for c in used],
                "check_refs": list(dict.fromkeys(_check_ref(c) for c in used)),
                "scenario": scenario(matched[0]) if matched else None,
                "outcome": "; ".join(dict.fromkeys(str(c.get("reason")) for c in used if c.get("reason"))) or None,
                "evidence": evidence,
            },
            "rechecked_conflict",
            "",
        )

    if fo.is_omission:
        fresh = [e for c in pos_checks for e in verified(c)[0] if not prev.contains(e.get("quote") or "")]
        mapped_new = {n for lk in links.values() for n in lk["new_ids"]}
        added = {r["id"] for r in cur.reqs} - mapped_new
        fams = {fam for _o, fam in pairs} or {_family(fo.criterion)}
        added_checks = sorted(
            (
                c
                for c in cur.checks
                if _check_reqs(c) & added and _family(c.get("criterion")) in fams and _check_status(c) == "positive"
            ),
            key=lambda c: (min(cur.req_pos(r) for r in _check_reqs(c) & added), _check_ref(c)),
        )
        for c in added_checks:
            for rid in sorted(_check_reqs(c) & added, key=_natural):
                fresh += [e for e in cur.req_evidence(rid) if e.get("verified") and not prev.contains(e["quote"])]
        if not fresh:
            return (
                None,
                "recheck_missing",
                (
                    "Нет опоры на появившийся в новой редакции текст; отсутствие замечания не доказывает, "
                    "что обещанный контракт появился."
                ),
            )
        used = pos_checks + added_checks
        return (
            {
                "kind": "contract_appeared",
                "checks": [_check_brief(c) for c in used],
                "check_refs": list(dict.fromkeys(_check_ref(c) for c in used)),
                "outcome": "; ".join(dict.fromkeys(str(c.get("reason")) for c in used if c.get("reason"))) or None,
                "evidence": fresh,
            },
            "rechecked_contract",
            "",
        )

    if not targets:
        return None, "recheck_missing", "Замечание не привязано к требованиям новой редакции; перепроверять нечего."
    return (
        {
            "kind": "requirement_rechecked",
            "checks": [_check_brief(c) for c in pos_checks],
            "check_refs": list(dict.fromkeys(_check_ref(c) for c in pos_checks)),
            "outcome": "; ".join(dict.fromkeys(str(c.get("reason")) for c in pos_checks if c.get("reason"))) or None,
            "evidence": [e for c in pos_checks for e in verified(c)[0]],
        },
        "rechecked",
        "",
    )


# ---------------------------------------------------------------------------
# Решения (--answers), представление
# ---------------------------------------------------------------------------


def _edit_touches(ed: _Edition, edit: dict, finding: dict) -> bool:
    """Правка из решения заменяет опорный фрагмент замечания (по координатам или по тексту)."""
    old = str(edit.get("old") or "")
    for e in _as_list(finding.get("evidence")):
        if not isinstance(e, dict):
            continue
        if (
            e.get("block_id") == edit.get("block_id")
            and isinstance(e.get("start"), int)
            and isinstance(edit.get("start"), int)
            and e["start"] < (edit.get("end") or 0)
            and edit["start"] < (e.get("end") or 0)
        ):
            return True
        q = _norm(str(e.get("quote") or ""))
        if q and old and (q in _norm(old) or _norm(old) in q):
            return True
    return False


def _decision_refs(prev: _Edition, cur: _Edition, old_ids: list, new_ids: list) -> list[dict]:
    """Решения (--answers), связанные с записью: через Question.finding_ids или правкой опорного фрагмента."""
    old_set, new_set = set(old_ids), set(new_ids)
    old_f = {f["id"]: f for f in prev.findings if f["id"] in old_set}
    new_f = {f["id"]: f for f in cur.findings if f["id"] in new_set}
    refs: dict[str, dict] = {}
    for label, ed in (("current", cur), ("previous", prev)):
        for d in ed.decisions:
            qid = d.get("question_id")
            sha = d.get("source_sha256")
            edits = [e for e in _as_list(d.get("edits")) if isinstance(e, dict)]
            linked = set(_as_list(d.get("finding_ids"))) | set(_as_list(d.get("finding_id")))
            hit = bool(linked & (old_set | new_set))
            hit |= bool(set(_as_list((prev.questions.get(qid) or {}).get("finding_ids"))) & old_set)
            hit |= bool(set(_as_list((cur.questions.get(qid) or {}).get("finding_ids"))) & new_set)
            touches = sorted(
                {
                    fid
                    for fid, f in old_f.items()
                    if (not sha or sha == prev.sha) and any(_edit_touches(prev, e, f) for e in edits)
                }
                | {
                    fid
                    for fid, f in new_f.items()
                    if sha and sha == cur.sha and any(_edit_touches(cur, e, f) for e in edits)
                },
                key=_natural,
            )
            key = str(qid or d.get("id") or len(refs))
            if not (hit or touches) or key in refs:
                continue
            applied = None
            if edits:
                applied = all(cur.contains(str(e.get("new") or "")) for e in edits if e.get("new")) and not any(
                    cur.contains(str(e.get("old") or ""))
                    for e in edits
                    if e.get("old") and _norm(str(e["old"])) not in _norm(str(e.get("new") or ""))
                )
            refs[key] = {
                "id": key,
                "question_id": qid,
                "report": label,
                "summary": _short(str(d.get("answer") or d.get("note") or ""), 200),
                "source_sha256": sha,
                "answered_on": "previous" if sha and sha == prev.sha else "current" if sha and sha == cur.sha else None,
                "edits": len(edits),
                "edits_applied": applied,
                "touches_anchor_of": touches,
                "_edits": edits,
            }
    return sorted(refs.values(), key=lambda r: _natural(r["id"]))


def _word_hunks(old_text: str, new_text: str, glue: int = 2) -> list[tuple[str, str]]:
    """Фрагменты правки (было, стало); соседние правки через ≤ glue слов склеиваются."""
    a, b = old_text.split(), new_text.split()
    strip = lambda w: re.sub(r"^[\s.,;:!?…]+|[\s.,;:!?…]+$", "", w)  # noqa: E731
    sm = difflib.SequenceMatcher(None, [_norm(strip(w)) for w in a], [_norm(strip(w)) for w in b], autojunk=False)
    hunks: list[list[int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if hunks and i1 - hunks[-1][1] <= glue and j1 - hunks[-1][3] <= glue:
            hunks[-1][1], hunks[-1][3] = i2, j2
        else:
            hunks.append([i1, i2, j1, j2])
    out = []
    for i1, i2, j1, j2 in hunks:
        was, now = strip(" ".join(a[i1:i2])), strip(" ".join(b[j1:j2]))
        if was or now:
            out.append((was, now))
    return out


def _behavior_change(prev: _Edition, cur: _Edition, rel_links: list[dict]) -> str:
    if not rel_links:
        return "обязательство не привязано к требованию; см. опоры"
    notes = []
    for lk in rel_links:
        oid = lk["old_ids"][0]
        name = (prev.req_by_id.get(oid) or {}).get("source_id") or oid
        rel = lk["relation"]
        if rel == "missing":
            notes.append(f"{name}: не найдено в новой редакции")
            continue
        if rel == "ambiguous":
            notes.append(f"{name}: пара в новой редакции неоднозначна")
            continue
        head = f"{name}: " + (
            f"разделён на {len(lk['new_ids'])} пункта; "
            if rel == "split"
            else "объединён с другими пунктами; "
            if rel == "merge"
            else ""
        )
        old_text = prev.req_body(oid)
        new_text = " ".join(cur.req_body(n) for n in lk["new_ids"])
        if _norm(old_text) == _norm(new_text):
            moved = [_CHANGES_RU[c] for c in lk["changes"] if c in ("renumbered", "moved")]
            notes.append(head + "формулировка не менялась" + (f" ({', '.join(moved)})" if moved else ""))
            continue
        parts = []
        for was, now in _word_hunks(old_text, new_text)[:3]:
            if was and now:
                parts.append(f"«{_short(was, 70)}» → «{_short(now, 70)}»")
            elif was:
                parts.append(f"убрано «{_short(was, 70)}»")
            else:
                parts.append(f"добавлено «{_short(now, 70)}»")
        notes.append(head + ("; ".join(parts) or "изменена пунктуация"))
    return "; ".join(notes)


def _entity(ed: _Edition, req_ids: list, evidence: list) -> str:
    known = [ed.req_by_id[r] for r in req_ids if r in ed.req_by_id]
    if len(known) > 1:
        return " ↔ ".join(str(r.get("source_id") or r["id"]) for r in known)
    if known:
        r = known[0]
        return f"{r.get('source_id') or r['id']} · " + _short(strip_label(str(r.get("text") or "")), 70)
    for e in evidence:
        if e.get("section"):
            return " › ".join(str(s) for s in e["section"][1:] or e["section"])
    return "весь набор требований"


_CHANGES_RU = {"reworded": "переформулировано", "renumbered": "перенумеровано", "moved": "перенесено"}
_RELATION_RU = {
    "same": "тот же пункт",
    "split": "разделён",
    "merge": "объединён",
    "missing": "не найден",
    "ambiguous": "неоднозначно",
}


def _link_ru(lk: dict) -> str:
    what = [_RELATION_RU.get(lk["relation"], lk["relation"])] if lk["relation"] != "same" else []
    what += [
        _CHANGES_RU.get(c, c) for c in lk["changes"] if not (c == "reworded" and lk["relation"] in ("split", "merge"))
    ]
    old, new = "/".join(map(str, lk["old_ids"])), "/".join(map(str, lk["new_ids"])) or "—"
    return f"{old}→{new} ({', '.join(what) or 'без изменений'})"


def _warn(code: str, message: str) -> dict:
    return {"code": code, "message": message}


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


def compare_reports(previous: dict, current: dict, *, ask: AskFn | None = None) -> dict:
    """Сравнивает отчёт прошлой редакции с отчётом текущей.

    ask(stage, payload, schema) — необязательный транспорт движка для
    неоднозначных пар требований. Ответ принимается только при дословных
    цитатах из обоих текстов и сам по себе ничего не закрывает.
    """
    warnings: list[dict] = []
    prev, cur = _Edition(previous, "previous"), _Edition(current, "current")
    _basis_warnings(prev, cur, warnings)

    links = _align_requirements(prev, cur, ask, warnings)
    # порядок по месту в документе и id: результат не зависит от порядка списков во входе
    olds = sorted(
        (part for f in prev.findings for part in _split_by_source(_Finding(prev, f), prev, cur, links)),
        key=lambda f: (f.pos, _natural(f.id), _natural(f.part or "")),
    )
    news = sorted((_Finding(cur, f) for f in cur.findings), key=lambda f: (f.pos, _natural(f.id)))
    seen_warn: set = set()
    for f in olds + news:
        if (f.ed.label, f.id) in seen_warn:
            continue
        seen_warn.add((f.ed.label, f.id))
        bad = [e for e in f.evidence if not e["verified"]]
        if bad:
            warnings.append(
                _warn(
                    "unverified_evidence",
                    f"{f.ed.label}: у замечания {f.id} {len(bad)} опор(ы) не совпадают с текстом блока.",
                )
            )
        if f.unknown_reqs:
            warnings.append(
                _warn(
                    "unknown_requirement",
                    f"{f.ed.label}: замечание {f.id} ссылается на неизвестные требования "
                    f"{', '.join(map(str, f.unknown_reqs))}.",
                )
            )

    groups, aux = _match_findings(prev, cur, olds, news, links)
    aux["links"] = links
    used_old = {i for g in groups for i in g["old"]}
    used_new = {j for g in groups for j in g["new"]}
    same_source = bool(prev.sha) and prev.sha == cur.sha

    result: dict[str, list] = {"resolved": [], "persisting": [], "introduced": [], "unassessed": []}

    def rel_links_for(fs: list[_Finding]) -> list[dict]:
        out, seen = [], set()
        for f in fs:
            for rid in f.req_ids:
                if rid in links and rid not in seen:
                    seen.add(rid)
                    out.append(links[rid])
        return out

    def base_entry(status: str, fo_list: list[_Finding], fn_list: list[_Finding]) -> dict:
        sev_old = min((f for f in fo_list), key=_Finding.sev_rank).severity if fo_list else None
        sev_new = min((f for f in fn_list), key=_Finding.sev_rank).severity if fn_list else None
        lead = fo_list[0] if fo_list else fn_list[0]
        rl = rel_links_for(fo_list)
        entry = {
            "status": status,
            "status_ru": STATUS_RU[status],
            "old_ids": list(dict.fromkeys(f.id for f in fo_list)),
            "new_ids": list(dict.fromkeys(f.id for f in fn_list)),
            "reason": "",
            "reason_code": "",
            "kind": lead.raw.get("kind"),
            "criterion": lead.raw.get("criterion"),
            "title": {"old": fo_list[0].title if fo_list else None, "new": fn_list[0].title if fn_list else None},
            "severity": {"old": sev_old, "new": sev_new},
            "severity_change": _sev_change(sev_old, sev_new),
            "old_status": [f.status for f in fo_list],
            "new_status": [f.status for f in fn_list],
            "old_evidence": [e for f in fo_list for e in f.evidence],
            "new_evidence": [e for f in fn_list for e in f.evidence],
            "requirements": [
                {k: lk[k] for k in ("old_ids", "new_ids", "relation", "changes", "score", "via")}
                | ({"detail": lk["detail"]} if lk.get("detail") else {})
                for lk in rl
            ],
            "decision_refs": _decision_refs(prev, cur, [f.id for f in fo_list], [f.id for f in fn_list]),
            "_sort": (
                min((f.sev_rank() for f in fo_list + fn_list), default=3),
                min((f.pos for f in fo_list), default=None) or min(f.pos for f in fn_list),
                _natural((fo_list or fn_list)[0].id),
            ),
            "identity": {"old": _identity(prev, fo_list), "new": _identity(cur, fn_list)},
            "_rel": rl,
        }
        part = _part_of(prev, fo_list)
        if part:
            entry["part"] = part
        return entry

    def with_part(e: dict, text: str) -> str:
        if not e.get("part"):
            return text
        p = e["part"]
        return f"Часть прежнего {p['of']} в {', '.join(p['labels'])}: {text[0].lower()}{text[1:]}"

    # --- найденные пары: сохранилось ---------------------------------
    for g in groups:
        fo_list = [olds[i] for i in g["old"]]
        fn_list = [news[j] for j in g["new"]]
        e = base_entry("persisting", fo_list, fn_list)
        first = next(iter(g["scores"].values()), (0.0, {}))[1]
        parts = ["Та же первопричина найдена в новом отчёте: " + _identity_text(prev, cur, e["_rel"], fo_list, first)]
        if len(e["old_ids"]) > 1:
            parts.append(f"в новой редакции объединены {len(e['old_ids'])} прежних замечания")
        if len(fn_list) > 1:
            parts.append(f"первопричина разделена на {len(fn_list)} замечания")
        if e["severity_change"]:
            parts.append(
                f"серьёзность изменилась: {SEVERITY_RU.get(e['severity']['old'], e['severity']['old'])} → "
                f"{SEVERITY_RU.get(e['severity']['new'], e['severity']['new'])} (это не новая первопричина)"
            )
        if {f.kind for f in fo_list} != {f.kind for f in fn_list}:
            parts.append("тип дефекта переименован: " + ", ".join(sorted({f.raw.get("kind") or "—" for f in fn_list})))
        if same_source and e["decision_refs"]:
            parts.append("ответ по --answers получен, но формулировка в документе прежняя")
        e["reason"] = with_part(e, "; ".join(parts) + ".")
        e["reason_code"] = "same_root_cause" + ("_severity_changed" if e["severity_change"] else "")
        e["match"] = {k: {"score": round(v[0], 3), **v[1]} for k, v in g["scores"].items()}
        result["persisting"].append(e)

    # --- старые без пары: закрыто или нужно подтверждение ------------
    possible_old: dict[int, list] = {}
    tie_taken: set = set()
    for i, fo in enumerate(olds):
        if i in used_old:
            continue
        rl = rel_links_for([fo])
        e = base_entry("unassessed", [fo], [])
        if i in aux["ties"]:
            tied = [j for j in aux["ties"][i] if j not in used_new and j not in tie_taken]
            tie_taken.update(tied)
            e.update(reason_code="ambiguous_match", new_ids=[news[j].id for j in tied])
            e["new_evidence"] = [x for j in tied for x in news[j].evidence]
            e["new_status"] = [news[j].status for j in tied]
            e["candidates"] = [
                {
                    "new_id": news[j].id,
                    "score": round(aux["scores"][(i, j)][0], 3),
                    "match": aux["scores"][(i, j)][1],
                    "new_title": news[j].title,
                    "new_severity": news[j].severity,
                    "new_source": [cur.req_label(r) for r in news[j].req_ids],
                }
                for j in tied
            ]
            e["reason"] = with_part(
                e,
                (
                    "Два равноправных кандидата в новом отчёте: "
                    + "; ".join(
                        f"{c['new_id']} ({', '.join(c['new_source']) or 'без пунктов'}, {c['score']:.2f})"
                        for c in e["candidates"]
                    )
                    + ". Источник прежнего замечания в новой редакции не определён однозначно, поэтому выбрать одного "
                    "по порядку нельзя: дефект мог сохраниться в любом из этих мест."
                ),
            )
            e["recheck"] = _recheck_request(fo, cur, rl, aux, "ambiguous_match")
            result["unassessed"].append(e)
            continue
        code, why, proof = _classify_closure(fo, prev, cur, rl, aux, same_source, e["decision_refs"])
        weak = [w for w in aux["weak"].get(i, []) if w[1] not in used_new]
        for s, j, _d in weak:
            possible_old.setdefault(j, []).append((s, fo))
        if code == "resolved" and weak:
            code, why = (
                "ambiguous_match",
                "Текст изменён и перепроверен, но в новом отчёте есть похожая находка "
                f"{', '.join(news[j].id for _, j, _ in weak)}; нельзя исключить, что дефект сохранился.",
            )
        look = _lookalike_text(cur, news, aux["lookalikes"].get(i, []), used_new)
        if code == "resolved":
            e.update(status="resolved", status_ru=STATUS_RU["resolved"], reason_code="text_changed_rechecked")
            e["proof"] = proof
            e["new_evidence"] = _resolution_evidence(cur, rl, proof)
            e["reason"] = with_part(
                e, why + (" " + _identity_text(prev, cur, rl, [fo], {}, resolved=True) if rl else "") + look
            )
        else:
            e["reason_code"] = code
            e["reason"] = with_part(e, why + look)
            e["new_evidence"] = list(aux["anchors"].get(fo.key, []))
            if weak:
                e["candidates"] = [
                    {
                        "new_id": news[j].id,
                        "score": round(s, 3),
                        "match": d,
                        "new_title": news[j].title,
                        "new_severity": news[j].severity,
                        "new_evidence": news[j].evidence,
                    }
                    for s, j, d in weak
                ]
                if code != "ambiguous_match":
                    e["reason"] += (
                        " Похожие новые находки для ручной сверки: "
                        + ", ".join(f"{c['new_id']} ({c['score']:.2f})" for c in e["candidates"])
                        + "."
                    )
            e["recheck"] = _recheck_request(fo, cur, rl, aux, code)
        result[e["status"]].append(e)

    # --- новые без пары --------------------------------------------
    for j, fn in enumerate(news):
        if j in used_new or j in tie_taken:
            continue
        e = base_entry("introduced", [], [fn])
        located_old = [prev.locate(q) for q in fn.quotes]
        old_exact = [a for a in located_old if a is not None and a["match"] != "fuzzy"]
        e["old_evidence"] = old_exact
        if fn.quotes and len(old_exact) == len(fn.quotes):
            e["origin"] = "existing_text"
            e["reason"] = (
                "Новая находка по тексту, который был и в прошлой редакции: прошлый прогон её не отметил "
                "(вариативность модели или расширенный охват), а не дефект правки."
            )
            e["reason_code"] = "new_finding_old_text"
        else:
            e["origin"] = "new_text"
            e["reason"] = "Новая первопричина: опора находится в тексте, которого не было в прошлой редакции."
            e["reason_code"] = "new_root_cause"
        if j in possible_old:
            best: dict = {}
            for s_, fo_ in possible_old[j]:
                if fo_.id not in best or s_ > best[fo_.id][0]:
                    best[fo_.id] = (s_, fo_)
            links_back = sorted(best.values(), key=lambda x: (-x[0], x[1].pos, _natural(x[1].id)))
            e["possible_old"] = [{"old_id": fo.id, "score": round(s, 3)} for s, fo in links_back]
            e["reason"] += (
                " Возможно, это продолжение прежнего замечания "
                + ", ".join(f"{fo.id} ({s:.2f})" for s, fo in links_back)
                + ": сверьте вручную."
            )
        stage = str(fn.raw.get("stage") or "").split("#")[0]
        if prev.status != "complete" and not (stage and _stage_done(prev, stage)):
            e["reason"] += " Прошлый прогон был неполным, поэтому новизна условна."
        result["introduced"].append(e)

    for status, entries in result.items():
        entries.sort(key=lambda x: x["_sort"])
        for k, e in enumerate(entries, 1):
            e["id"] = f"{ENTRY_PREFIX[status]}-{k}"
            e["view"] = _view(prev, cur, e)
            e.pop("_sort", None)
            e.pop("_rel", None)
            for d in e["decision_refs"]:
                d.pop("_edits", None)

    for entries in result.values():
        for e in entries:  # DiffEntry.evidence: проверяемые опоры текущей редакции (контракт v1)
            e["evidence"] = [
                {k: x[k] for k in ("block_id", "start", "end", "quote")}
                for x in e["new_evidence"]
                if x.get("verified") and x.get("block_id") in cur.block_by_id
            ]
    return {
        "previous": {"source_sha256": prev.sha or "", "run_id": prev.run.get("run_id")},
        "current": {"source_sha256": cur.sha or "", "run_id": cur.run.get("run_id")},
        "resolved": result["resolved"],
        "persisting": result["persisting"],
        "introduced": result["introduced"],
        "unassessed": result["unassessed"],
        "impacted_req_ids": _impacted(cur, links),
        "warnings": warnings,
        "basis": _basis(prev, cur, links, same_source),
    }


def _impacted(cur: _Edition, links: dict) -> list[str]:
    """Требования новой редакции, которых коснулась правка: переформулированы, разделены, слиты или добавлены."""
    touched = {n for lk in links.values() if "reworded" in lk["changes"] for n in lk["new_ids"]}
    mapped = {n for lk in links.values() for n in lk["new_ids"]}
    touched |= {r["id"] for r in cur.reqs if r["id"] not in mapped}
    return sorted(touched, key=lambda r: (cur.req_pos(r), _natural(r)))


def _part_of(prev: _Edition, fo_list: list) -> dict | None:
    """Описание части, если запись относится не ко всем пунктам прежней находки."""
    parts = [f for f in fo_list if f.part is not None]
    if not parts or len({f.id for f in fo_list}) != 1:
        return None
    covered = sorted({f.part for f in parts}, key=lambda r: (prev.req_pos(r), _natural(r)))
    whole = parts[0].whole_req_ids
    if set(covered) >= set(whole):
        return None
    return {
        "of": parts[0].id,
        "req_ids": covered,
        "labels": [prev.req_label(r) for r in covered],
        "whole_req_ids": list(whole),
    }


def _stage_done(ed: _Edition, stage: str) -> bool:
    runs = [st for st in ed.stages if str(st.get("name") or "").split("#")[0] == stage]
    return bool(runs) and stage not in ed.incomplete_stages and all(st.get("status") in ("ok", "cached") for st in runs)


def _identity(ed: _Edition, fs: list) -> dict:
    """Тождество находки: источник (пункты), условие и исход сценария (witness)."""
    src: list[str] = []
    for f in fs:
        for r in f.req_ids:
            if ed.req_label(r) not in src:
                src.append(ed.req_label(r))
    w = next((f.witness for f in fs if f.witness), None) or {}
    return {
        "source": src,
        "condition": witness_condition(w) or None,
        "outcome": [w[k] for k in ("outcome_a", "outcome_b") if w.get(k)],
    }


def _identity_text(
    prev: _Edition, cur: _Edition, rl: list, fo_list: list, detail: dict, *, resolved: bool = False
) -> str:
    """«источник Д-1 (R-1) → 2.1 (R-3); условие «…» то же; исход тот же» — основание тождества."""
    pairs = []
    for lk in rl:
        old = "/".join(prev.req_label(o) for o in lk["old_ids"])
        new = "/".join(cur.req_label(n) for n in lk["new_ids"]) or "—"
        pairs.append(f"{old} → {new}")
    parts = [("источник исправления " if resolved else "источник ") + "; ".join(pairs)] if pairs else []
    w = next((f.witness for f in fo_list if f.witness), None) or {}
    cond = witness_condition(w)
    if cond:
        if resolved:
            parts.append(f"условие «{_short(cond, 120)}»")
        elif detail.get("same_condition"):
            parts.append(f"условие «{_short(cond, 120)}» то же")
        if not resolved and detail.get("outcome") is not None:
            parts.append(
                "исход " + ("тот же" if detail["outcome"] >= 0.8 else f"переформулирован ({detail['outcome']:.2f})")
            )
    text = "; ".join(parts)
    return (text[0].upper() + text[1:] + ".") if resolved and text else text


def _lookalike_text(cur: _Edition, news: list, items: list, used_new: set) -> str:
    """Похожие по названию находки нового отчёта из другого источника: почему они не продолжение."""
    notes = []
    for j, why in items:
        fn = news[j]
        src = ", ".join(cur.req_label(r) for r in fn.req_ids) or "без пунктов"
        notes.append(f"{fn.id} («{_short(fn.title, 60)}», {src}) — {why}")
    return (
        (" Похожая по названию находка нового отчёта не считается продолжением: " + "; ".join(notes) + ".")
        if notes
        else ""
    )


def _sev_change(old: str | None, new: str | None) -> str | None:
    if not old or not new or old == new:
        return None
    ro, rn = SEVERITY_RANK.get(old, 3), SEVERITY_RANK.get(new, 3)
    return "raised" if rn < ro else "lowered"


def _classify_closure(
    fo: _Finding,
    prev: _Edition,
    cur: _Edition,
    rl: list,
    aux: dict,
    same_source: bool,
    decisions: list,
) -> tuple[str, str, dict | None]:
    """Код и причина для прежнего замечания без пары: resolved только при всех условиях закрытия."""
    label = ", ".join(prev.req_label(r) for r in fo.req_ids) or "набор"
    dec_ids = ", ".join(str(d["id"]) for d in decisions)
    blockers: list[tuple[str, str]] = []
    covered, why_not = _stage_gate(fo, cur, aux["source_blocks"].get(fo.key))
    if not covered:
        blockers.append(("run_incomplete", why_not))
    if same_source:
        if decisions:
            blockers.append(
                (
                    "answer_only",
                    f"Получен ответ по --answers ({dec_ids}), но формулировка в документе прежняя (SHA-256 "
                    "совпадает). Решение нужно внести в текст и перепроверить.",
                )
            )
        else:
            blockers.append(
                (
                    "text_unchanged",
                    "Текст документа не изменился (SHA-256 совпадает); исчезновение замечания — тишина модели, "
                    "а не правка.",
                )
            )
    for lk in rl:
        if lk["relation"] == "missing":
            blockers.append(("obligation_missing", lk["detail"]))
        elif lk["relation"] == "ambiguous":
            blockers.append(("alignment_ambiguous", lk["detail"] + " Нужна ручная сверка кандидатов."))
    anchors = aux["anchors"].get(fo.key, [])
    if not rl and fo.quotes and not anchors and not fo.is_omission:
        blockers.append(
            (
                "obligation_missing",
                "Опорный фрагмент замечания не найден в новой редакции; удаление источника не доказывает исправления.",
            )
        )
    if blockers:
        return blockers[0][0], " ".join(dict.fromkeys(msg for _c, msg in blockers)), None

    # опора сохранилась, если цитата дословно есть в своём источнике (а не где-то в документе)
    quotes_present = list(dict.fromkeys(aux["present"].get(fo.key, [])))
    all_quotes = list(dict.fromkeys(q for q, _b in fo.anchor_src)) or fo.quotes
    reworded = any("reworded" in lk["changes"] or lk["relation"] in ("split", "merge") for lk in rl)
    changed = reworded or len(quotes_present) < len(all_quotes)
    if fo.is_omission and not changed:
        changed = any(not prev.contains(str(b.get("text") or "")) for b in cur.blocks)
    if not changed:
        q = _short(quotes_present[0], 100) if quotes_present else _short(fo.title, 100)
        suffix = ""
        if decisions:
            suffix = f" Есть решение {dec_ids}, но в текст оно не внесено."
        still = _pair_coverage(fo, cur, aux["links"], "conflict") if fo.is_conflict else []
        if still:
            suffix += (
                " Профильный этап по-прежнему отмечает противоречие: " + _coverage_text(cur, still, "conflict") + "."
            )
        return (
            "anchor_unchanged",
            f"Опорный фрагмент «{q}» дословно сохранился в новой редакции ({label}); замечание не повторено, "
            "но текст не исправлен." + suffix,
            None,
        )
    stage_covered = bool(str(fo.raw.get("stage") or "")) and covered
    proof, code, why = _closure_proof(fo, prev, cur, aux["links"], stage_covered=stage_covered)
    if proof is None and code == "recheck_missing":
        proof = _decision_proof(fo, prev, cur, decisions)
    moved = [lk for lk in rl if lk["changes"]]
    rel_txt = "; ".join(_link_ru(lk) for lk in moved)
    if proof is None:
        where = f" ({rel_txt})" if rel_txt else ""
        return code, f"Текст в месте опоры изменён{where}, но закрыть нельзя: {why[0].lower()}{why[1:]}", None
    stage = str(fo.raw.get("stage") or "").split("#")[0] or "проверки"
    what = {
        "conflict_reconciled": "перепроверка сценария дала единый исход",
        "contract_appeared": "в новой редакции появился обещанный контракт",
        "requirement_rechecked": "обязательство перепроверено по тому же критерию",
        "coverage_reconciled": (
            f"профильный этап {stage}: покрытие "
            + cur.req_label((proof.get("coverage") or {}).get("req_id", ""))
            + " критерием "
            + ", ".join(cur.req_label(a) for a in (proof.get("coverage") or {}).get("acceptance_ids", []))
            + " — covered"
            + (
                f" (было {(proof.get('coverage') or {}).get('previous_status')})"
                if (proof.get("coverage") or {}).get("previous_status")
                else ""
            )
        ),
        "decision_applied": (
            f"внесено решение {proof.get('decision')}: правка заменила опорный фрагмент, этап {stage} новой "
            "редакции завершён и замечание не повторил (отдельной перепроверки сценария не было)"
        ),
    }[proof["kind"]]
    refs = f" ({', '.join(proof['check_refs'])})" if proof.get("check_refs") else ""
    text = f"Текст изменён в месте опоры ({label}); {what}{refs}; в новом отчёте замечания нет."
    if rel_txt:
        text += f" Сопоставление: {rel_txt}."
    if decisions and proof["kind"] != "decision_applied":
        applied = [d for d in decisions if d.get("edits_applied")]
        text += f" Связанное решение: {dec_ids}" + (" (правка внесена)." if applied else ".")
    return "resolved", text, proof


def _stage_gate(fo: _Finding, cur: _Edition, source_blocks: set | None = None) -> tuple[bool, str]:
    """Охват перепроверки: документ прочитан там, где лежит источник, и этап, нашедший замечание, завершён."""
    if cur.partial_read_global:
        return False, (
            "Новая редакция прочитана не полностью ("
            + "; ".join(_short(w, 120) for w in cur.partial_read_global)
            + "): отсутствие замечания не доказывает исправления."
        )
    if cur.partial_read_blocks:
        src = set(source_blocks or ())
        whole_set = fo.scope == "set" or fo.is_conflict or fo.is_omission or not src
        hit = sorted(cur.partial_read_blocks & src, key=lambda b: cur.block_order.get(b, 10**9))
        if whole_set or hit:
            where = ", ".join(hit) if hit else ", ".join(sorted(cur.partial_read_blocks))
            why = "задет источник замечания" if hit else "замечание касается всего набора требований"
            return False, (
                f"Новая редакция прочитана не полностью (блоки {where}; {why}): отсутствие замечания не доказывает "
                "исправления."
            )
    run_reasons = _short("; ".join(map(str, _as_list(cur.run.get("status_reasons")))) or "причина не указана", 300)
    run_msg = (
        f"Второй прогон завершился со статусом «{cur.status}» ({run_reasons}): отсутствие замечания не доказывает "
        "исправления."
    )
    if cur.status not in ("complete", "partial"):
        return False, run_msg
    stage = str(fo.raw.get("stage") or "").split("#")[0]
    if stage:
        runs = [st for st in cur.stages if str(st.get("name") or "").split("#")[0] == stage]
        if runs or stage in cur.incomplete_stages:
            if stage not in cur.incomplete_stages and all(st.get("status") in ("ok", "cached") for st in runs):
                return True, ""
            why = "; ".join(dict.fromkeys(str(st.get("reason")) for st in runs if st.get("reason"))) or "не завершён"
            return False, (
                f"Этап {stage}, который нашёл замечание, во втором прогоне не завершён ({_short(why, 200)}): "
                "отсутствие замечания не доказывает исправления."
            )
    return (True, "") if cur.status == "complete" else (False, run_msg)


def _decision_proof(fo: _Finding, prev: _Edition, cur: _Edition, decisions: list) -> dict | None:
    """Решение по --answers закрывает замечание только вместе с внесённой в опорный фрагмент правкой.

    Ответ без правки или правка в другом месте ничего не доказывают. Для пропуска годится правка,
    добавившая новый текст."""
    for d in decisions:
        if not d.get("edits_applied"):
            continue
        edits = d.get("_edits") or []
        fresh = [e for e in edits if e.get("new") and not prev.contains(str(e["new"]))]
        if fo.id not in d.get("touches_anchor_of", []) and not (fo.is_omission and fresh):
            continue
        evidence = [a for a in (cur.locate(str(e.get("new") or "")) for e in edits if e.get("new")) if a]
        evidence = [a for a in evidence if a["match"] != "fuzzy"]
        if not evidence:
            continue
        return {
            "kind": "decision_applied",
            "decision": d["id"],
            "checks": [],
            "check_refs": [],
            "outcome": d.get("summary") or None,
            "edits": [{"old": e.get("old"), "new": e.get("new")} for e in edits],
            "evidence": evidence,
        }
    return None


def _resolution_evidence(cur: _Edition, rl: list, proof: dict | None) -> list:
    out = list((proof or {}).get("evidence") or [])
    seen = {(e.get("block_id"), e.get("start"), e.get("end")) for e in out}
    for lk in rl:
        for nid in lk["new_ids"]:
            for e in cur.req_evidence(nid):
                key = (e.get("block_id"), e.get("start"), e.get("end"))
                if key not in seen and e.get("verified"):
                    seen.add(key)
                    out.append(e)
    return out


def _recheck_request(fo: _Finding, cur: _Edition, rl: list, aux: dict, code: str) -> dict:
    new_reqs = sorted({n for lk in rl for n in lk["new_ids"]}, key=_natural)
    blocks = sorted(
        {b for n in new_reqs for b in cur.req_blocks(n)} | {a["block_id"] for a in aux["anchors"].get(fo.key, [])},
        key=lambda b: cur.block_order.get(b, 10**9),
    )
    req = {
        "stage": "diff_recheck",
        "old_finding_id": fo.id,
        "kind": fo.raw.get("kind"),
        "criterion": fo.raw.get("criterion"),
        "new_req_ids": new_reqs,
        "new_block_ids": blocks,
        "question_ru": f"Сохраняется ли в новой редакции дефект «{_short(fo.title, 120)}»? Ответ с опорой на текст.",
    }
    req["reason_code"] = code
    if fo.witness:
        req["scenario"] = fo.witness.get("input")
        req["question_ru"] = (
            f"Какой исход даёт новая редакция в сценарии «{_short(str(fo.witness.get('input')), 160)}»? "
            "Если исход один, приведите опоры обеих сторон."
        )
    if code == "obligation_missing":
        gone = [lk["old_ids"][0] for lk in rl if lk["relation"] == "missing"]
        req["missing_old_req_ids"] = gone
        req["question_ru"] = (
            "Повторите извлечение и подтвердите у автора: обязательство "
            f"{', '.join(map(str, gone)) or 'с опорой замечания'} удалено намеренно или потеряно? "
            "Без этого дефект не считается исправленным."
        )
    elif code in ("alignment_ambiguous", "ambiguous_match"):
        req["question_ru"] = "Сверьте кандидатов вручную: та же ли это первопричина в новой редакции?"
    elif code in ("answer_only", "anchor_unchanged", "text_unchanged"):
        req["question_ru"] = "Внесите принятое решение в текст требования и повторите прогон с --compare."
    return req


def _view(prev: _Edition, cur: _Edition, e: dict) -> dict:
    # показываем фрагмент, который изменился: старый, которого нет в новой редакции, и новый, которого не было
    old_ev = next((x for x in e["old_evidence"] if not cur.contains(x.get("quote") or "")), None) or (
        e["old_evidence"][0] if e["old_evidence"] else None
    )
    new_ev = next((x for x in e["new_evidence"] if not prev.contains(x.get("quote") or "")), None) or (
        e["new_evidence"][0] if e["new_evidence"] else None
    )
    old_reqs = [r for lk in e.get("_rel", []) for r in lk["old_ids"]]
    if e["status"] == "introduced":
        nf = next((f for f in cur.findings if f["id"] == e["new_ids"][0]), {})
        entity = _entity(cur, [r for r in _as_list(nf.get("req_ids")) if r in cur.req_by_id], e["new_evidence"])
        behavior = "новый текст" if e.get("origin") == "new_text" else "текст был и раньше; находка новая"
    else:
        entity = _entity(prev, old_reqs, e["old_evidence"])
        behavior = _behavior_change(prev, cur, e.get("_rel", []))
    dec = e["decision_refs"][0] if e["decision_refs"] else None
    sev = e["severity"]["new"] or e["severity"]["old"]
    return {
        "status_ru": e["status_ru"],
        "severity": sev,
        "severity_ru": SEVERITY_RU.get(sev or "", sev),
        "severity_change": e["severity_change"],
        "entity": entity,
        "title": e["title"]["old"] or e["title"]["new"],
        "old_quote": old_ev["quote"] if old_ev else None,
        "old_loc": old_ev.get("loc") if old_ev else None,
        "new_quote": new_ev["quote"] if new_ev else None,
        "new_loc": new_ev.get("loc") if new_ev else None,
        "behavior_change": behavior,
        "decision_ref": {"id": dec["id"], "summary": dec["summary"]} if dec else None,
        "reason": e["reason"],
    }


def _basis_warnings(prev: _Edition, cur: _Edition, warnings: list) -> None:
    for ed in (prev, cur):
        ver = ed.report.get("schema_version")
        if ver not in (None, "1.0"):
            warnings.append(_warn("schema_version", f"{ed.label}: schema_version {ver!r}, ожидалась 1.0."))
        if ed.run.get("source_sha256") and ed.doc_id and ed.run["source_sha256"] != ed.doc_id:
            warnings.append(_warn("hash_mismatch", f"{ed.label}: run.source_sha256 не совпадает с document.id."))
        if not ed.blocks:
            warnings.append(_warn("no_blocks", f"{ed.label}: в отчёте нет document.blocks; опоры не проверяются."))
        if str(ed.run.get("mode") or "") == "mock":
            warnings.append(
                _warn("mock_run", f"{ed.label}: прогон в режиме mock; результат сравнения демонстрационный.")
            )
    if prev.sha and prev.sha == cur.sha:
        warnings.append(
            _warn(
                "same_source",
                "Исходный документ не изменился (SHA-256 совпадает): закрыть замечание можно только правкой текста.",
            )
        )
    if prev.digest == cur.digest:
        warnings.append(_warn("same_report", "Сравнивается один и тот же отчёт."))
    if prev.status != "complete":
        warnings.append(
            _warn(
                "previous_incomplete",
                f"Прошлый прогон: статус «{prev.status}»; часть прежних дефектов могла не попасть в отчёт.",
            )
        )
    if cur.status != "complete":
        stages = ", ".join(sorted(cur.incomplete_stages)) or "без отметки этапа"
        tail = " и все замечания — при неполном чтении документа." if cur.partial_read else "."
        warnings.append(
            _warn(
                "current_incomplete",
                f"Текущий прогон: статус «{cur.status}»; не закрываются замечания этапов {stages}{tail}",
            )
        )
    for w in cur.doc_warnings:
        warnings.append(_warn("extraction", "Текущая редакция: " + _short(w, 200)))


def _basis(prev: _Edition, cur: _Edition, links: dict, same_source: bool) -> dict:
    def side(ed: _Edition) -> dict:
        return {
            "source_sha256": ed.sha,
            "report_sha256": ed.digest,
            "run_status": ed.status,
            "mode": ed.run.get("mode"),
            "agent_version": ed.run.get("agent_version"),
            "provider": ed.run.get("provider"),
            "model": ed.run.get("model"),
            "requirements": len(ed.reqs),
            "findings": len(ed.findings),
        }

    counts: dict[str, int] = {}
    for lk in links.values():
        counts[lk["relation"]] = counts.get(lk["relation"], 0) + 1
        for c in lk["changes"]:
            counts[c] = counts.get(c, 0) + 1
    matched_new = {n for lk in links.values() for n in lk["new_ids"]}
    counts["added"] = sum(1 for r in cur.reqs if r["id"] not in matched_new)
    rows = sorted(links.values(), key=lambda lk: (prev.req_pos(lk["old_ids"][0]), _natural(lk["old_ids"][0])))
    req_map = [
        {k: lk[k] for k in ("old_ids", "new_ids", "relation", "changes", "score", "via") if k in lk}
        | ({"missing": lk["missing"]} if lk.get("missing") else {})
        for lk in rows
    ]
    req_map += [
        {"old_ids": [], "new_ids": [r["id"]], "relation": "added", "changes": [], "score": 0.0, "via": "text"}
        for r in sorted(cur.reqs, key=lambda r: (cur.req_pos(r["id"]), _natural(r["id"])))
        if r["id"] not in matched_new
    ]
    return {
        "diff_version": DIFF_VERSION,
        "previous": side(prev),
        "current": side(cur),
        "same_source": same_source,
        "requirement_counts": dict(sorted(counts.items())),
        "requirement_map": req_map,
    }


# ---------------------------------------------------------------------------
# Компактные данные для HTML/веб-демо и Markdown
# ---------------------------------------------------------------------------


def to_view(diff: dict) -> dict:
    """Плоские строки для №13/№15: прежние замечания отдельно от новых."""

    def row(e: dict) -> dict:
        out = {"id": e["id"], "status": e["status"], "old_ids": e["old_ids"], "new_ids": e["new_ids"], **e["view"]}
        if e.get("part"):  # запись относится к части сгруппированной находки (одному из пунктов)
            out["part"] = e["part"]["labels"]
        return out

    previous = [row(e) for key in ("resolved", "persisting", "unassessed") for e in diff[key]]
    previous.sort(
        key=lambda r: (SEVERITY_RANK.get(r["severity"] or "", 3), _natural(r["old_ids"][0] if r["old_ids"] else ""))
    )
    return {
        "summary": {
            "resolved": len(diff["resolved"]),
            "persisting": len(diff["persisting"]),
            "unassessed": len(diff["unassessed"]),
            "introduced": len(diff["introduced"]),
            "severity_changed": sum(1 for e in diff["persisting"] if e["severity_change"]),
        },
        "basis": {k: diff["basis"][k] for k in ("previous", "current", "same_source")},
        "previous_findings": previous,
        "new_findings": [row(e) for e in diff["introduced"]],
        "warnings": [w["message"] for w in diff["warnings"]],
    }


def render_markdown(diff: dict) -> str:
    v = to_view(diff)
    s = v["summary"]
    lines = [
        "## Сравнение с прошлой редакцией",
        "",
        f"Прошлая редакция `{(v['basis']['previous']['source_sha256'] or '—')[:12]}` → "
        f"текущая `{(v['basis']['current']['source_sha256'] or '—')[:12]}`.",
        f"Исправлено в тексте: {s['resolved']} · сохранилось: {s['persisting']} "
        f"(серьёзность изменилась: {s['severity_changed']}) · нужно подтверждение: {s['unassessed']} · "
        f"новые замечания: {s['introduced']}.",
        "",
        "### Прежние замечания",
        "",
        "| Статус | Было → стало | Сущность | Было | Стало | Причина |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    def cell(x: Any, limit: int = 160) -> str:
        return _short(str(x), limit).replace("|", "\\|") if x else "—"

    for r in v["previous_findings"]:
        old = ", ".join(map(str, r["old_ids"])) or "—"
        if r.get("part"):
            old += f" [{', '.join(r['part'])}]"
        ids = f"{old} → {', '.join(map(str, r['new_ids'])) or '—'}"
        lines.append(
            f"| {r['status_ru']} | {ids} | {cell(r['entity'])} | {cell(r['old_quote'])} | "
            f"{cell(r['new_quote'])} | {cell(r['reason'], 600)} |"
        )
    lines += ["", "### Новые замечания", ""]
    if v["new_findings"]:
        lines += ["| ID | Серьёзность | Сущность | Цитата | Причина |", "| :--- | :--- | :--- | :--- | :--- |"]
        for r in v["new_findings"]:
            lines.append(
                f"| {', '.join(map(str, r['new_ids']))} | {r['severity_ru'] or '—'} | {cell(r['entity'])} | "
                f"{cell(r['new_quote'])} | {cell(r['reason'], 600)} |"
            )
    else:
        lines.append("Новых замечаний нет.")
    if v["warnings"]:
        lines += ["", "### Предупреждения сравнения", ""] + [f"* {w}" for w in v["warnings"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI: python -m bcc_review.decisions.diff PREVIOUS.json CURRENT.json
# ---------------------------------------------------------------------------


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m bcc_review.decisions.diff", description="Сравнение двух report.json без ложных закрытий."
    )
    p.add_argument("previous", help="report.json прошлой редакции")
    p.add_argument("current", help="report.json текущей редакции")
    p.add_argument("-o", "--output", help="куда записать diff.json (по умолчанию stdout)")
    p.add_argument("--view", help="куда записать компактные строки для HTML/веб-демо")
    p.add_argument("--md", help="куда записать раздел отчёта в Markdown")
    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # консоль Windows (cp1251/cp866): вывод всегда UTF-8
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        with open(args.previous, encoding="utf-8") as fh:
            previous = json.load(fh)
        with open(args.current, encoding="utf-8") as fh:
            current = json.load(fh)
        diff = compare_reports(previous, current)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(diff, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    if args.view:
        with open(args.view, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(to_view(diff), ensure_ascii=False, indent=2) + "\n")
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(diff))
    s = to_view(diff)["summary"]
    print(
        f"исправлено в тексте: {s['resolved']}; сохранилось: {s['persisting']}; "
        f"нужно подтверждение: {s['unassessed']}; новые: {s['introduced']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
