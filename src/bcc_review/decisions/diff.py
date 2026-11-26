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
import difflib
import functools
import hashlib
import json
import re
import sys
import unicodedata
from typing import Any
from collections.abc import Callable, Iterable

DIFF_VERSION = "p09-1"

STATUS_RU = {
    "resolved": "исправлено в тексте",
    "persisting": "сохранилось",
    "unassessed": "нужно подтверждение",
    "introduced": "новое замечание",
}
ENTRY_PREFIX = {"resolved": "RES", "persisting": "PER", "unassessed": "CHK", "introduced": "NEW"}
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}
SEVERITY_RU = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}

# Пороги текстового сходства. Обоснование: tests/p09/test_p09_measures.py.
REQ_CONFIDENT = 0.55  # уверенная пара 1:1 без опор
REQ_CANDIDATE = 0.40  # ниже порога пара не рассматривается
REQ_MARGIN = 0.08  # отрыв от второго кандидата
PART_CONTAINMENT = 0.75  # доля шинглов части, вложенная в целое (split/merge)
UNION_COVERAGE = 0.75  # доля целого, покрытая частями
FIND_CONFIDENT = 0.62  # уверенная пара замечаний
FIND_CANDIDATE = 0.45  # кандидат для ручной проверки
FUZZY_ANCHOR = 0.60  # нечёткое перемещение опоры
SCENARIO_MATCH = 0.80  # сценарий перепроверки совпадает с witness.input

_POSITIVE = {"passed", "pass", "ok", "clean", "compliant", "consistent", "resolved", "no_defect"}
_NEGATIVE = {"failed", "fail", "violated", "defect", "finding", "inconsistent", "conflict"}
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
        self.reqs = [r for r in _as_list(report.get("requirements")) if isinstance(r, dict) and r.get("id") is not None]
        self.req_by_id = {r["id"]: r for r in self.reqs}
        self.findings = [f for f in _as_list(report.get("findings")) if isinstance(f, dict) and f.get("id") is not None]
        self.checks = [c for c in _as_list(report.get("checks")) if isinstance(c, dict)]
        self.coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
        self.decisions = [d for d in _as_list(report.get("decisions")) if isinstance(d, dict)]
        self.doc_warnings = [
            str(w) if not isinstance(w, dict) else str(w.get("message") or w)
            for w in _as_list(self.document.get("warnings"))
        ]
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
        nq = _norm(quote or "")
        return bool(nq) and nq in self.full_norm

    def locate(self, quote: str, prefer: Iterable[str] = ()) -> dict | None:
        """Ищет цитату: точно, после нормализации, затем нечётко по предложениям."""
        if not quote or not quote.strip():
            return None
        prefer = [b for b in prefer if b in self.block_by_id]
        order = prefer + [b["id"] for b in self.blocks if b["id"] not in prefer]
        for bid in order:
            text = str(self.block_by_id[bid].get("text") or "")
            p = text.find(quote)
            if p >= 0:
                return self._anchor(bid, p, p + len(quote), "exact")
        nq = _norm(quote)
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
    if _norm(str(o.get("text") or "")) != _norm(str(n.get("text") or "")):
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
        return str(r.get("text") or "")

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
    heading = str(section[-1]) if section else ""
    if heading and _norm(heading) not in cur.headings:
        detail = f"Раздел «{heading}» с требованием {label} отсутствует в извлечении новой редакции"
        if cur.doc_warnings:
            detail += "; предупреждения извлечения: " + "; ".join(_short(w, 120) for w in cur.doc_warnings)
        return "section_missing", detail + ". Удаление источника не доказывает исправления."
    return "removed", (
        f"Формулировка требования {label} не найдена в новой редакции. Удаление не доказывает исправления: "
        "нужно подтвердить, что обязательство снято намеренно."
    )


_IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "match_id": {"type": ["string", "null"]},
        "old_quote": {"type": "string"},
        "new_quote": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["match_id", "old_quote", "new_quote", "reason"],
}


def _ask_identity(ask: AskFn, prev: _Edition, cur: _Edition, o: dict, cands: list, warnings: list) -> dict | None:
    """Просит движок подтвердить смысловую идентичность и принимает ответ только с проверяемыми цитатами."""
    payload = {
        "task": "Определи, какой пункт новой редакции выражает то же обязательство, что и старый пункт. "
        "Если ни один, верни match_id = null. Процитируй дословно общий смысловой фрагмент из обоих.",
        "old": {
            "id": o["id"],
            "source_id": o.get("source_id"),
            "text": o.get("text"),
            "section": prev.req_section(o["id"]),
        },
        "candidates": [
            {
                "id": c["new_id"],
                "source_id": cur.req_by_id[c["new_id"]].get("source_id"),
                "text": cur.req_text(c["new_id"]),
                "section": cur.req_section(c["new_id"]),
            }
            for c in cands
        ],
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
        and _norm(oq) in _norm(str(o.get("text") or ""))
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
        self.req_ids = [r for r in _as_list(raw.get("req_ids")) if r in ed.req_by_id]
        self.unknown_reqs = [r for r in _as_list(raw.get("req_ids")) if r not in ed.req_by_id]
        self.evidence = [ed.verify(e) for e in _as_list(raw.get("evidence")) if isinstance(e, dict)]
        hints = [h for h in _as_list(raw.get("hints")) if isinstance(h, dict) and h.get("quote")]
        self.quotes = [e["quote"] for e in self.evidence if e.get("quote")]
        self.quotes += [h["quote"] for h in hints if h["quote"] not in self.quotes]
        self.witness = raw.get("witness") if isinstance(raw.get("witness"), dict) else None
        self.inspected = [b for b in _as_list(raw.get("inspected_block_ids"))]
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


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _finding_score(fo: _Finding, fn: _Finding, mapped: set, anchors: list, cur: _Edition) -> tuple[float, dict]:
    """Тождество первопричины: место (опоры важнее требования), тип дефекта, предмет (заголовок)."""
    detail: dict[str, Any] = {}
    req_ov = _overlap(mapped, set(fn.req_ids)) if mapped and fn.req_ids else None
    if req_ov is not None:
        detail["requirements"] = round(req_ov, 2)
    anc: float | None = None
    if anchors and fn.evidence:
        anc = 0.0
        for a in anchors:
            exact = a["match"] != "fuzzy"
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
                if text_similarity(a["quote"], e.get("quote") or "") >= 0.6:
                    anc = max(anc, 1.0 if exact else 0.8)
        detail["anchors"] = round(anc, 2)
    elif fo.quotes and fn.quotes:
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
    content = text_similarity(fo.title, fn.title)
    if fo.impact and fn.impact:
        content = max(content, text_similarity(fo.impact, fn.impact))
    detail.update(place=round(place, 2), type=typ, content=round(content, 2))
    if place == 0.0 and not (fo.scope == "set" and fn.scope == "set" and content >= 0.5):
        return 0.0, detail
    return 0.5 * place + 0.2 * typ + 0.3 * content, detail


def _match_findings(prev: _Edition, cur: _Edition, olds: list, news: list, links: dict) -> tuple[list, dict]:
    """Группы {old: [...], new: [...]} и слабые кандидаты для неоднозначных."""
    mapped: dict[str, set] = {}
    anchors: dict[str, list] = {}
    for fo in olds:
        m: set = set()
        for rid in fo.req_ids:
            m.update(links.get(rid, {}).get("new_ids", []))
        mapped[fo.id] = m
        prefer = [b for nid in m for b in cur.req_blocks(nid)]
        found: list = []
        for a in (cur.locate(q, prefer) for q in fo.quotes):
            if a is None or any(
                b["block_id"] == a["block_id"]
                and a["start"] < b["end"]
                and b["start"] < a["end"]
                and (a["match"] == "fuzzy" or (a["start"], a["end"]) == (b["start"], b["end"]))
                for b in found
            ):
                continue  # та же точка новой редакции уже найдена (например, нечёткий двойник дубля)
            found.append(a)
        anchors[fo.id] = found

    scores: dict[tuple[int, int], tuple[float, dict]] = {}
    for i, fo in enumerate(olds):
        for j, fn in enumerate(news):
            s, d = _finding_score(fo, fn, mapped[fo.id], anchors[fo.id], cur)
            if s >= FIND_CANDIDATE:
                scores[(i, j)] = (s, d)

    def best_new(i: int) -> int | None:
        opts = [(s, -j) for (a, j), (s, _) in scores.items() if a == i and s >= FIND_CONFIDENT]
        return -max(opts)[1] if opts else None

    def best_old(j: int) -> int | None:
        opts = [(s, -i) for (i, b), (s, _) in scores.items() if b == j and s >= FIND_CONFIDENT]
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
            f"{olds[i].id}->{news[j].id}": scores[(i, j)] for i in g["old"] for j in g["new"] if (i, j) in scores
        }
    return groups, {"weak": weak, "mapped": mapped, "anchors": anchors}


# ---------------------------------------------------------------------------
# Доказательство закрытия
# ---------------------------------------------------------------------------


def _check_reqs(check: dict) -> set:
    out = set(_as_list(check.get("req_ids")))
    if check.get("req_id") is not None:
        out.add(check["req_id"])
    return out


def _check_status(check: dict) -> str:
    raw = _norm(str(check.get("status") or check.get("result") or check.get("outcome") or ""))
    if raw in _POSITIVE:
        return "positive"
    if raw in _NEGATIVE:
        return "negative"
    return "skipped"


def _criterion_ok(check: dict, criterion: str) -> bool:
    c = _norm(str(check.get("criterion") or ""))
    return not criterion or c in ("", "*", "all") or c == criterion


def _coverage_skips(cur: _Edition, req_ids: set) -> list[str]:
    reasons = []
    for key in ("unassessed", "skipped", "not_assessed"):
        for item in _as_list(cur.coverage.get(key)):
            if isinstance(item, dict):
                ids = set(_as_list(item.get("req_ids"))) | ({item["req_id"]} if item.get("req_id") else set())
                if ids & req_ids:
                    reasons.append(str(item.get("reason") or "без причины"))
            elif item in req_ids:
                reasons.append("отмечено в coverage как непроверенное")
    return reasons


def _coverage_lists(cur: _Edition, rid: str, criterion: str) -> bool:
    reqs = cur.coverage.get("requirements")
    if isinstance(reqs, dict) and rid in reqs:
        entry = reqs[rid]
        crits = entry.get("criteria") if isinstance(entry, dict) else entry
        return any(_norm(str(c)) in (criterion, "*", "all") for c in _as_list(crits)) or not criterion
    return False


def _closure_proof(
    fo: _Finding, cur: _Edition, prev: _Edition, new_reqs: set, side_reqs: list[set]
) -> tuple[dict | None, str, str]:
    """(proof | None, reason_code, explanation)."""
    relevant = [c for c in cur.checks if _criterion_ok(c, fo.criterion)]
    if new_reqs:
        relevant = [c for c in relevant if _check_reqs(c) & new_reqs]
    else:
        relevant = [c for c in relevant if c.get("scope") == "set" or not _check_reqs(c)]
    negative = [c for c in relevant if _check_status(c) == "negative"]
    if negative:
        ids = ", ".join(str(c.get("id")) for c in negative)
        return (
            None,
            "recheck_failed",
            f"Перепроверка {ids} в новой редакции сообщает нарушение, но пара замечания не найдена.",
        )
    positive = [c for c in relevant if _check_status(c) == "positive"]

    def verified(c: dict) -> list:
        return [e for e in (cur.verify(x) for x in _as_list(c.get("evidence")) if isinstance(x, dict)) if e["verified"]]

    if fo.is_conflict:
        # каждая сторона противоречия (у разделённой — хотя бы одна её часть) охвачена проверкой
        # и имеет проверенную опору в своём тексте новой редакции
        sides = [side for side in side_reqs if side]
        side_blocks = [{b for r in side for b in cur.req_blocks(r)} for side in sides]
        old_input = old_input_of(fo)
        for c in positive:
            if any(not (_check_reqs(c) & side) for side in sides):
                continue
            evs = verified(c)
            if not evs or any(blocks and not any(e["block_id"] in blocks for e in evs) for blocks in side_blocks):
                continue
            scenario = str(c.get("scenario") or c.get("witness_input") or (c.get("witness") or {}).get("input") or "")
            if (
                old_input
                and _norm(old_input) != _norm(scenario)
                and text_similarity(old_input, scenario) < SCENARIO_MATCH
            ):
                continue
            return (
                {
                    "check_ids": [c.get("id")],
                    "kind": "conflict_reconciled",
                    "scenario": scenario or None,
                    "outcome": c.get("outcome") if c.get("outcome") not in (None, c.get("status")) else c.get("reason"),
                    "evidence": evs,
                },
                "rechecked_conflict",
                "",
            )
        if old_input:
            return (
                None,
                "recheck_missing",
                (
                    f"Нет перепроверки сценария «{_short(old_input, 120)}» на новой редакции с единым исходом и "
                    "опорой в тексте обеих сторон; закрыть противоречие нельзя."
                ),
            )
        return None, "recheck_missing", "Нет перепроверки обеих сторон противоречия в новой редакции с опорой в тексте."

    if fo.is_omission:
        for c in positive:
            fresh = [e for e in verified(c) if not prev.contains(e.get("quote") or "")]
            if fresh:
                return (
                    {
                        "check_ids": [c.get("id")],
                        "kind": "contract_appeared",
                        "evidence": fresh,
                        "outcome": c.get("reason"),
                    },
                    "rechecked_contract",
                    "",
                )
        return (
            None,
            "recheck_missing",
            (
                "Нет перепроверки с опорой на появившийся в новой редакции текст; отсутствие замечания не доказывает, "
                "что обещанный контракт появился."
            ),
        )

    covered: set = set()
    for c in positive:
        covered |= _check_reqs(c)
    if positive and new_reqs <= covered:
        return (
            {
                "check_ids": [c.get("id") for c in positive],
                "kind": "requirement_rechecked",
                "evidence": [e for c in positive for e in verified(c)],
                "outcome": "; ".join(str(c.get("reason")) for c in positive if c.get("reason")) or None,
            },
            "rechecked",
            "",
        )
    if new_reqs and all(_coverage_lists(cur, r, fo.criterion) for r in new_reqs):
        return (
            {
                "check_ids": [],
                "kind": "coverage",
                "evidence": [],
                "outcome": "coverage нового отчёта фиксирует проверку по критерию",
            },
            "rechecked_coverage",
            "",
        )
    skips = _coverage_skips(cur, new_reqs)
    if skips:
        return (
            None,
            "recheck_skipped",
            "Обязательство в новой редакции не проверено: " + "; ".join(_short(s, 100) for s in skips) + ".",
        )
    crit = fo.raw.get("criterion") or "—"
    return (
        None,
        "recheck_missing",
        f"В новом отчёте нет явной перепроверки затронутого обязательства по критерию {crit}.",
    )


def old_input_of(fo: _Finding) -> str:
    return str((fo.witness or {}).get("input") or "")


# ---------------------------------------------------------------------------
# Решения (--answers), представление
# ---------------------------------------------------------------------------


def _decision_refs(prev: _Edition, cur: _Edition, old_ids: list, new_ids: list) -> list[dict]:
    refs = []
    for label, ed, ids in (("previous", prev, set(old_ids)), ("current", cur, set(old_ids) | set(new_ids))):
        for d in ed.decisions:
            targets = (
                set(_as_list(d.get("finding_ids")))
                | set(_as_list(d.get("finding_id")))
                | set(_as_list(d.get("targets")))
            )
            if targets & ids:
                refs.append(
                    {
                        "id": d.get("id"),
                        "report": label,
                        "summary": _short(
                            str(d.get("answer") or d.get("summary") or d.get("choice") or d.get("text") or ""), 200
                        ),
                        "status": d.get("status"),
                        "question_id": d.get("question_id"),
                        "edit": d.get("edit"),
                    }
                )
    seen, out = set(), []
    for r in refs:
        key = (r["id"], r["report"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


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
        old_text = prev.req_text(oid)
        new_text = " ".join(cur.req_text(n) for n in lk["new_ids"])
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
        return f"{r.get('source_id') or r['id']} · " + _short(str(r.get("text") or ""), 70)
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
    olds = sorted((_Finding(prev, f) for f in prev.findings), key=lambda f: (f.pos, _natural(f.id)))
    news = sorted((_Finding(cur, f) for f in cur.findings), key=lambda f: (f.pos, _natural(f.id)))
    for f in olds + news:
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
    used_old = {i for g in groups for i in g["old"]}
    used_new = {j for g in groups for j in g["new"]}
    same_source = bool(prev.sha) and prev.sha == cur.sha
    run_ok = cur.status == "complete"

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
            "old_ids": [f.id for f in fo_list],
            "new_ids": [f.id for f in fn_list],
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
            "_rel": rl,
        }
        return entry

    # --- найденные пары: сохранилось ---------------------------------
    for g in groups:
        fo_list = [olds[i] for i in g["old"]]
        fn_list = [news[j] for j in g["new"]]
        e = base_entry("persisting", fo_list, fn_list)
        parts = ["Та же первопричина найдена в новом отчёте"]
        if len(fo_list) > 1:
            parts.append(f"в новой редакции объединены {len(fo_list)} прежних замечания")
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
        e["reason"] = "; ".join(parts) + "."
        e["reason_code"] = "same_root_cause" + ("_severity_changed" if e["severity_change"] else "")
        e["match"] = {k: {"score": round(v[0], 3), **v[1]} for k, v in g["scores"].items()}
        result["persisting"].append(e)

    # --- старые без пары: закрыто или нужно подтверждение ------------
    possible_old: dict[int, list] = {}
    for i, fo in enumerate(olds):
        if i in used_old:
            continue
        rl = rel_links_for([fo])
        e = base_entry("unassessed", [fo], [])
        code, why, proof = _classify_closure(fo, prev, cur, rl, aux, run_ok, same_source, e["decision_refs"])
        weak = [w for w in aux["weak"].get(i, []) if w[1] not in used_new]
        for s, j, _d in weak:
            possible_old.setdefault(j, []).append((s, fo))
        if code == "resolved" and weak:
            code, why = (
                "ambiguous_match",
                "Текст изменён и перепроверен, но в новом отчёте есть похожая находка "
                f"{', '.join(news[j].id for _, j, _ in weak)}; нельзя исключить, что дефект сохранился.",
            )
        if code == "resolved":
            e.update(status="resolved", status_ru=STATUS_RU["resolved"], reason_code="text_changed_rechecked")
            e["proof"] = proof
            e["new_evidence"] = _resolution_evidence(cur, rl, proof)
            e["reason"] = why
        else:
            e["reason_code"] = code
            e["reason"] = why
            e["new_evidence"] = list(aux["anchors"].get(fo.id, []))
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
        if j in used_new:
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
            links_back = sorted(possible_old[j], key=lambda x: (-x[0], x[1].pos, _natural(x[1].id)))
            e["possible_old"] = [{"old_id": fo.id, "score": round(s, 3)} for s, fo in links_back]
            e["reason"] += (
                " Возможно, это продолжение прежнего замечания "
                + ", ".join(f"{fo.id} ({s:.2f})" for s, fo in links_back)
                + ": сверьте вручную."
            )
        if prev.status != "complete":
            e["reason"] += " Прошлый прогон был неполным, поэтому новизна условна."
        result["introduced"].append(e)

    for status, entries in result.items():
        entries.sort(key=lambda x: x["_sort"])
        for k, e in enumerate(entries, 1):
            e["id"] = f"{ENTRY_PREFIX[status]}-{k}"
            e["view"] = _view(prev, cur, e)
            e.pop("_sort", None)
            e.pop("_rel", None)

    return {
        "resolved": result["resolved"],
        "persisting": result["persisting"],
        "introduced": result["introduced"],
        "unassessed": result["unassessed"],
        "warnings": warnings,
        "basis": _basis(prev, cur, links, same_source),
    }


def _sev_change(old: str | None, new: str | None) -> str | None:
    if not old or not new or old == new:
        return None
    ro, rn = SEVERITY_RANK.get(old, 3), SEVERITY_RANK.get(new, 3)
    return "raised" if rn < ro else "lowered"


def _classify_closure(
    fo: _Finding, prev: _Edition, cur: _Edition, rl: list, aux: dict, run_ok: bool, same_source: bool, decisions: list
) -> tuple[str, str, dict | None]:
    label = ", ".join(prev.req_label(r) for r in fo.req_ids) or "набор"
    if not run_ok:
        return (
            "run_incomplete",
            (
                f"Второй прогон завершился со статусом «{cur.status}»: отсутствие замечания не доказывает исправления "
                "(возможен технический сбой или неполный охват)."
            ),
            None,
        )
    if same_source:
        if decisions:
            ids = ", ".join(str(d["id"]) for d in decisions)
            return (
                "answer_only",
                (
                    f"Получен ответ по --answers ({ids}), но формулировка в документе прежняя (SHA-256 совпадает). "
                    "Решение нужно внести в текст и перепроверить."
                ),
                None,
            )
        return (
            "text_unchanged",
            ("Текст документа не изменился (SHA-256 совпадает); исчезновение замечания — тишина модели, а не правка."),
            None,
        )
    missing = [lk for lk in rl if lk["relation"] == "missing"]
    if missing:
        return "obligation_missing", " ".join(lk["detail"] for lk in missing), None
    ambiguous = [lk for lk in rl if lk["relation"] == "ambiguous"]
    if ambiguous:
        return (
            "alignment_ambiguous",
            " ".join(lk["detail"] for lk in ambiguous) + " Нужна ручная сверка кандидатов.",
            None,
        )
    anchors = aux["anchors"].get(fo.id, [])
    if not rl and fo.quotes and not anchors and not fo.is_omission:
        return (
            "obligation_missing",
            ("Опорный фрагмент замечания не найден в новой редакции; удаление источника не доказывает исправления."),
            None,
        )
    quotes_present = [q for q in fo.quotes if cur.contains(q)]
    reworded = any("reworded" in lk["changes"] or lk["relation"] in ("split", "merge") for lk in rl)
    changed = reworded or len(quotes_present) < len(fo.quotes)
    if fo.is_omission and not changed:
        changed = any(not prev.contains(str(b.get("text") or "")) for b in cur.blocks)
    if not changed:
        q = _short(quotes_present[0], 100) if quotes_present else _short(fo.title, 100)
        suffix = (
            f" Есть решение {', '.join(str(d['id']) for d in decisions)}, но в текст оно не внесено."
            if decisions
            else ""
        )
        return (
            "anchor_unchanged",
            (
                f"Опорный фрагмент «{q}» дословно сохранился в новой редакции ({label}); замечание не повторено, "
                "но текст не исправлен." + suffix
            ),
            None,
        )
    new_reqs: set = set()
    side_reqs: list[set] = []
    for rid in fo.req_ids:
        targets = set(next((lk["new_ids"] for lk in rl if rid in lk["old_ids"]), []))
        new_reqs |= targets
        side_reqs.append(targets)
    proof, code, why = _closure_proof(fo, cur, prev, new_reqs, side_reqs)
    moved = [lk for lk in rl if lk["changes"]]
    rel_txt = "; ".join(_link_ru(lk) for lk in moved)
    if proof is None:
        where = f" ({rel_txt})" if rel_txt else ""
        return code, f"Текст в месте опоры изменён{where}, но закрыть нельзя: {why[0].lower()}{why[1:]}", None
    what = {
        "conflict_reconciled": "перепроверка сценария дала единый исход",
        "contract_appeared": "в новой редакции появился обещанный контракт",
        "requirement_rechecked": "обязательство перепроверено по тому же критерию",
        "coverage": "обязательство покрыто проверкой по тому же критерию",
    }[proof["kind"]]
    cid = f" ({', '.join(map(str, proof['check_ids']))})" if proof.get("check_ids") else ""
    text = f"Текст изменён в месте опоры ({label}); {what}{cid}; в новом отчёте замечания нет."
    if rel_txt:
        text += f" Сопоставление: {rel_txt}."
    if decisions:
        text += " Связанное решение: " + ", ".join(str(d["id"]) for d in decisions) + "."
    return "resolved", text, proof


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
        {b for n in new_reqs for b in cur.req_blocks(n)} | {a["block_id"] for a in aux["anchors"].get(fo.id, [])},
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
        warnings.append(
            _warn("current_incomplete", f"Текущий прогон: статус «{cur.status}»; ни одно замечание не закрывается.")
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
        return {"id": e["id"], "status": e["status"], "old_ids": e["old_ids"], "new_ids": e["new_ids"], **e["view"]}

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

    def cell(x: Any) -> str:
        return _short(str(x), 160).replace("|", "\\|") if x else "—"

    for r in v["previous_findings"]:
        ids = f"{', '.join(map(str, r['old_ids'])) or '—'} → {', '.join(map(str, r['new_ids'])) or '—'}"
        lines.append(
            f"| {r['status_ru']} | {ids} | {cell(r['entity'])} | {cell(r['old_quote'])} | "
            f"{cell(r['new_quote'])} | {cell(r['reason'])} |"
        )
    lines += ["", "### Новые замечания", ""]
    if v["new_findings"]:
        lines += ["| ID | Серьёзность | Сущность | Цитата | Причина |", "| :--- | :--- | :--- | :--- | :--- |"]
        for r in v["new_findings"]:
            lines.append(
                f"| {', '.join(map(str, r['new_ids']))} | {r['severity_ru'] or '—'} | {cell(r['entity'])} | "
                f"{cell(r['new_quote'])} | {cell(r['reason'])} |"
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
