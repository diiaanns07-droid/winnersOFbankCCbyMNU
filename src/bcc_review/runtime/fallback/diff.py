"""Резервное сравнение редакций без ложных закрытий (пока не влит модуль №09).

Замечания сопоставляются по семейству дефекта и тексту опор (нормализованные цитаты), а не по
номерам строк: перемещение строк само по себе не создаёт и не закрывает дефект.

* persisting — найдено в обеих редакциях;
* resolved — опоры старого замечания исчезли или изменились, и в новой редакции оно не найдено;
  доказательство — новый текст на месте старой опоры;
* unassessed — старая опора не изменилась, но новый прогон замечание не повторил (например, этап
  не завершился): закрытием не считается;
* introduced — новое замечание.
"""

from __future__ import annotations

import difflib
from typing import Any

from ..merge import cause_key, family
from .evidence import _normalize


def _norm(text: str) -> str:
    return _normalize(text)[0].strip()


def _quotes(f: dict[str, Any]) -> set[str]:
    return {_norm(e["quote"]) for e in f.get("evidence") or [] if len(e.get("quote", "")) >= 3}


def _matches(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if family(old["kind"]) != family(new["kind"]):
        return False
    qo, qn = _quotes(old), _quotes(new)
    if qo & qn:
        return True
    for a in qo:
        for b in qn:
            if len(a) >= 12 and len(b) >= 12 and (a in b or b in a):
                return True
    ko, kn = cause_key(old), cause_key(new)
    return bool(ko[1]) and ko == kn


def _changed_blocks(prev_doc: dict[str, Any], cur_doc: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(блоки новой редакции, которых не было; тексты старой редакции, которые исчезли)."""
    old_texts = {_norm(b["text"]) for b in prev_doc.get("blocks", [])}
    new_texts = {_norm(b["text"]) for b in cur_doc.get("blocks", [])}
    changed_new = {b["id"] for b in cur_doc.get("blocks", []) if _norm(b["text"]) not in old_texts}
    gone_old = {t for t in old_texts if t not in new_texts}
    return changed_new, gone_old


def _replacement_evidence(old_f: dict[str, Any], prev_doc: dict[str, Any], cur_doc: dict[str, Any],
                          changed_new: set[str]) -> list[dict[str, Any]]:
    prev_blocks = {b["id"]: b for b in prev_doc.get("blocks", [])}
    out = []
    for e in old_f.get("evidence") or []:
        ob = prev_blocks.get(e["block_id"])
        if ob is None:
            continue
        best, score = None, 0.0
        for b in cur_doc["blocks"]:
            if b["id"] not in changed_new:
                continue
            s = difflib.SequenceMatcher(None, ob["text"], b["text"]).ratio() + (0.2 if b["section"] == ob["section"] else 0)
            if s > score:
                best, score = b, s
        if best is not None and score >= 0.5:
            ev = {"block_id": best["id"], "start": 0, "end": len(best["text"]), "quote": best["text"]}
            if ev not in out:
                out.append(ev)
    return out


def compare_reports(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_doc, cur_doc = previous["document"], current["document"]
    changed_new, gone_old = _changed_blocks(prev_doc, cur_doc)
    cur_texts = [_norm(b["text"]) for b in cur_doc["blocks"]]
    incomplete = set(current.get("run", {}).get("incomplete_stages") or [])
    resolved, persisting, introduced, unassessed, warnings = [], [], [], [], []
    used_new: set[str] = set()
    for of in previous.get("findings", []):
        match = next((nf for nf in current.get("findings", []) if nf["id"] not in used_new and _matches(of, nf)), None)
        if match is not None:
            used_new.add(match["id"])
            persisting.append({"old_ids": [of["id"]], "new_ids": [match["id"]],
                               "reason": "замечание найдено в обеих редакциях по тексту опор",
                               "evidence": match["evidence"][:3]})
            continue
        quotes = _quotes(of)
        still_there = quotes and all(any(q in t for t in cur_texts) for q in quotes)
        stage = (of.get("stage") or "").split("#")[0]
        if still_there or (stage and stage in incomplete):
            why = ("текст опоры не изменился, но новый прогон замечание не повторил" if still_there
                   else f"этап {stage} в новом прогоне не завершился")
            unassessed.append({"old_ids": [of["id"]], "new_ids": [], "reason": why + ": закрытием не считается",
                               "evidence": []})
            continue
        ev = _replacement_evidence(of, prev_doc, cur_doc, changed_new)
        resolved.append({"old_ids": [of["id"]], "new_ids": [],
                         "reason": "текст опоры изменён в новой редакции, дефект не найден повторно",
                         "evidence": ev})
        if not ev:
            warnings.append(f"{of['id']}: опора удалена, нового текста на её месте не найдено")
    for nf in current.get("findings", []):
        if nf["id"] in used_new:
            continue
        in_changed = any(e["block_id"] in changed_new for e in nf.get("evidence") or [])
        introduced.append({"old_ids": [], "new_ids": [nf["id"]],
                           "reason": "новое замечание в изменённом тексте" if in_changed
                           else "новое замечание в неизменённом тексте (в прошлом прогоне не было найдено)",
                           "evidence": nf["evidence"][:3]})
    req_by_block = {}
    for r in current.get("requirements", []):
        for bid in r["block_ids"]:
            req_by_block[bid] = r["id"]
    impacted = sorted({req_by_block[b] for b in changed_new if b in req_by_block})
    return {
        "previous": {"source_sha256": prev_doc["id"], "run_id": previous.get("run", {}).get("run_id")},
        "current": {"source_sha256": cur_doc["id"], "run_id": current.get("run", {}).get("run_id")},
        "resolved": resolved, "persisting": persisting, "introduced": introduced, "unassessed": unassessed,
        "impacted_req_ids": impacted, "warnings": warnings,
    }
