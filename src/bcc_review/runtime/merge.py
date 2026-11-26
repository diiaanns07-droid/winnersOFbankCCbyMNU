"""Объединение кандидатов по первопричине.

Два кандидата — одно замечание, только если совпадает семейство дефекта и
(а) их опоры пересекаются (тот же фрагмент или та же пара фрагментов конфликта) и объект дефекта
тот же по смыслу слов, либо (б) совпадает нормализованная первопричина целиком: объект, условие и
набор несовместимых исходов. Похожие слова без общей опоры и без совпадения первопричины не
объединяются: два разных сбоя остаются двумя замечаниями.
"""

from __future__ import annotations

import re
from typing import Any

FAMILY = {"conflict": "conflict", "incorrect": "conflict", "ambiguity": "ambiguity", "unverifiable": "verifiability",
          "incomplete": "gap", "omission": "gap", "placeholder": "gap", "terminology": "terminology",
          "traceability": "traceability", "non_singular": "structure", "duplicate": "structure",
          "design_in_requirement": "design", "infeasible": "feasibility", "format": "format", "other": "other"}
SEV_RANK = {"critical": 3, "major": 2, "minor": 1}
MEANING_RANK = {"confirmed": 3, "deterministic": 3, "uncertain": 1, "unchecked": 0}
_STOP = {"и", "в", "во", "на", "по", "с", "со", "к", "о", "об", "от", "до", "для", "при", "не", "нет", "или", "а",
         "что", "как", "из", "за", "the", "a", "of", "to", "in", "is"}
_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def family(kind: str) -> str:
    return FAMILY.get(kind, kind)


def _stems(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall((text or "").lower().replace("ё", "е")):
        if w in _STOP or len(w) < 2:
            continue
        out.add(w[:6] if len(w) > 6 else w)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cause_key(c: dict[str, Any]) -> tuple:
    cause = c.get("cause") or {}
    obj = " ".join(sorted(_stems(cause.get("object", ""))))
    cond = " ".join(sorted(_stems(cause.get("condition", ""))))
    outs = tuple(sorted(" ".join(sorted(_stems(o))) for o in cause.get("outcomes") or [] if o))
    return family(c["kind"]), obj, cond, outs


def _spans(c: dict[str, Any]) -> list[tuple[str, int, int]]:
    return [(e["block_id"], e["start"], e["end"]) for e in c.get("evidence") or []]


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    wa, wb = a.get("witness"), b.get("witness")
    if wa and wb:
        pa = {wa["evidence_a"]["block_id"], wa["evidence_b"]["block_id"]}
        pb = {wb["evidence_a"]["block_id"], wb["evidence_b"]["block_id"]}
        return pa == pb
    for ba, sa, ea in _spans(a):
        for bb, sb, eb in _spans(b):
            if ba == bb and sa < eb and sb < ea:
                return True
    return False


def same_root_cause(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if family(a["kind"]) != family(b["kind"]):
        return False
    ka, kb = cause_key(a), cause_key(b)
    if ka[1] and ka == kb and (ka[2] or ka[3]):
        return True
    if _overlap(a, b):
        obj_a = _stems((a.get("cause") or {}).get("object", "")) | _stems(a.get("title", ""))
        obj_b = _stems((b.get("cause") or {}).get("object", "")) | _stems(b.get("title", ""))
        if a.get("witness") and b.get("witness"):
            return True  # та же пара опор конфликта — один конфликт
        return _jaccard(obj_a, obj_b) >= 0.25
    return False


def _union(seq_a: list, seq_b: list) -> list:
    out = list(seq_a)
    for x in seq_b:
        if x not in out:
            out.append(x)
    return out


def _absorb(base: dict[str, Any], other: dict[str, Any]) -> None:
    if SEV_RANK[other["severity"]] > SEV_RANK[base["severity"]]:
        for key in ("severity", "title", "impact", "blocked_decision", "criterion"):
            if other.get(key):
                base[key] = other[key]
    for key in ("impact", "blocked_decision", "recommendation"):
        if not base.get(key) and other.get(key):
            base[key] = other[key]
    base["req_ids"] = _union(base["req_ids"], other["req_ids"])
    base["evidence"] = _union(base["evidence"], other["evidence"])
    base["hints"] = _union(base.get("hints", []), other.get("hints", []))
    base["inspected_block_ids"] = _union(base.get("inspected_block_ids", []), other.get("inspected_block_ids", []))
    base["merged_from"] = _union(base.get("merged_from", []), [other["cid"]] + other.get("merged_from", []))
    if not base.get("witness") and other.get("witness"):
        base["witness"] = other["witness"]
    if MEANING_RANK.get(other["meaning_status"], 0) > MEANING_RANK.get(base["meaning_status"], 0):
        base["meaning_status"] = other["meaning_status"]
        base["meaning_reason"] = other.get("meaning_reason", "")
    if other.get("anchor_status") == "supported":
        base["anchor_status"] = "supported"
    if base.get("source") != other.get("source"):
        base["source"] = "mixed"
    base["notes"] = _union(base.get("notes", []), other.get("notes", []))


def merge_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """items — проверенные кандидаты (с evidence, anchor/meaning статусами, cid). Порядок стабилен."""
    clusters: list[dict[str, Any]] = []
    for item in items:
        for cl in clusters:
            if same_root_cause(cl, item):
                _absorb(cl, item)
                break
        else:
            first = dict(item)
            first["merged_from"] = list(item.get("merged_from", []))
            clusters.append(first)
    return clusters
