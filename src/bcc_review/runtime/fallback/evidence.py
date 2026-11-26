"""Резервная проверка цитат (пока не влит модуль №07 ``bcc_review.analysis.evidence``).

Цитата ищется в указанном блоке точно, затем после нормализации (кавычки, тире, пробелы, «ё»,
регистр, разметка); при промахе — во всех блоках. Найдено в одном месте — ``matched`` с координатами
исходного текста; в нескольких блоках — ``ambiguous``; нигде — ``missing``. Нечёткого поиска нет:
лучше потерять опору, чем привязать замечание не к тому месту.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

_TRANS = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "—": "-", "–": "-",
                        "‑": "-", "−": "-", " ": " ", " ": " ", "ё": "е", "Ё": "Е", "*": None, "`": None})


def _normalize(text: str) -> tuple[str, list[int]]:
    """Нормализованная строка и карта: позиция в норм. строке → позиция в исходной."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        ch = unicodedata.normalize("NFKC", ch).translate(_TRANS)
        if not ch:
            continue
        for c in ch:
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            out.append(c.lower())
            idx.append(i)
    return "".join(out), idx


def _find_all(hay: str, needle: str) -> list[int]:
    res, start = [], 0
    while needle:
        p = hay.find(needle, start)
        if p < 0:
            break
        res.append(p)
        start = p + 1
    return res


def _locate(block: dict[str, Any], quote: str, context: Optional[str] = None) -> list[tuple[int, int, str]]:
    text = block["text"]
    hits = [(p, p + len(quote), "exact") for p in _find_all(text, quote)]
    if hits:
        return hits
    ntext, idx = _normalize(text)
    nquote, _ = _normalize(quote.strip())
    if len(nquote) < 3:
        return []
    out = []
    for p in _find_all(ntext, nquote):
        s = idx[p]
        e = idx[p + len(nquote) - 1] + 1
        out.append((s, e, "normalized"))
    return out


def _pick(hits: list[tuple[int, int, str]], block: dict[str, Any], context: Optional[str]):
    if len(hits) == 1 or not context:
        return hits[0]
    for h in hits:
        lo, hi = max(0, h[0] - len(context)), h[1] + len(context)
        if context.strip() and context.strip() in block["text"][lo:hi]:
            return h
    return hits[0]


def resolve_hint(document: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    quote = (hint.get("quote") or "").strip()
    if len(quote) < 2:
        return {"status": "missing", "evidence": None, "reason": "пустая цитата"}
    parts = [quote]
    if "…" in quote or "..." in quote:
        parts = sorted((p.strip() for p in re.split(r"…|\.\.\.", quote) if len(p.strip()) >= 8), key=len, reverse=True) or parts
    blocks = document["blocks"]
    by_id = {b["id"]: b for b in blocks}
    context = hint.get("context")
    for q in parts:
        target = by_id.get(hint.get("block_id") or "")
        if target is not None:
            hits = _locate(target, q, context)
            if hits:
                s, e, how = _pick(hits, target, context)
                reason = "точное совпадение" if how == "exact" else "совпадение после нормализации пробелов, кавычек и тире"
                if len(hits) > 1:
                    reason += f"; в блоке {len(hits)} вхождения, выбрано первое"
                if q is not quote:
                    reason += "; цитата с многоточием, подтверждена самая длинная часть"
                return {"status": "matched", "reason": reason,
                        "evidence": {"block_id": target["id"], "start": s, "end": e, "quote": target["text"][s:e]}}
        found = []
        for b in blocks:
            hits = _locate(b, q, context)
            if hits:
                found.append((b, _pick(hits, b, context)))
        if len(found) == 1:
            b, (s, e, how) = found[0]
            note = f"блок уточнён: {hint.get('block_id')} → {b['id']}" if hint.get("block_id") else "блок найден поиском"
            return {"status": "matched", "reason": note,
                    "evidence": {"block_id": b["id"], "start": s, "end": e, "quote": b["text"][s:e]}}
        if len(found) > 1:
            return {"status": "ambiguous", "evidence": None,
                    "reason": "цитата встречается в нескольких блоках: " + ", ".join(b["id"] for b, _ in found[:8])}
    return {"status": "missing", "evidence": None, "reason": "цитата не найдена в тексте документа"}


def resolve_candidate(document: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    results = []
    ok = True
    for h in candidate.get("hints") or []:
        r = resolve_hint(document, h)
        results.append(r)
        if r["status"] == "matched":
            if r["evidence"] not in evidence:
                evidence.append(r["evidence"])
        else:
            ok = False
            warnings.append(f"цитата «{(h.get('quote') or '')[:60]}»: {r['reason']}")
    witness = None
    wd = candidate.get("witness")
    if wd:
        ra = resolve_hint(document, wd.get("hint_a") or {})
        rb = resolve_hint(document, wd.get("hint_b") or {})
        results.extend([ra, rb])
        if ra["status"] == "matched" and rb["status"] == "matched":
            ea, eb = ra["evidence"], rb["evidence"]
            same_span = ea["block_id"] == eb["block_id"] and not (ea["end"] <= eb["start"] or eb["end"] <= ea["start"])
            if same_span:
                ok = False
                warnings.append("обе опоры конфликта указывают на один и тот же фрагмент")
            else:
                witness = {"input": wd.get("input", ""), "outcome_a": wd.get("outcome_a", ""),
                           "outcome_b": wd.get("outcome_b", ""), "evidence_a": ea, "evidence_b": eb}
                for ev in (ea, eb):
                    if ev not in evidence:
                        evidence.append(ev)
        else:
            ok = False
            for side, r in (("A", ra), ("B", rb)):
                if r["status"] != "matched":
                    warnings.append(f"опора {side} конфликта: {r['reason']}")
    elif candidate.get("kind") == "conflict":
        warnings.append("конфликт без сценария (witness): подтверждается только как требующий проверки")
    if not evidence:
        ok = False
        if not warnings:
            warnings.append("нет ни одной цитаты")
    return {"anchor_status": "supported" if ok else "incomplete", "evidence": evidence, "warnings": warnings,
            "witness": witness, "hint_results": results}
