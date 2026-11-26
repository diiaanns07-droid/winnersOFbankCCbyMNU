"""Этап consistency (№09): проверка набора требований целиком.

Один вызов модели. Модель делает разбор (предметы, попарная сверка по сценарию, глоссарий,
трассировка) и пишет дефекты набора, которые не следуют из разбора напрямую. Код:

* ``pair_checks`` с вердиктом ``conflict`` по одному и тому же предмету и двумя найденными
  цитатами в разных местах превращает в critical-кандидата, ``undefined`` — в major;
* пары по разным предметам (``same_subject = false``) не сравниваются и кандидатов не дают;
* ``glossary`` с серьёзностью major/minor превращает в кандидата ``terminology``;
* ``trace`` чистит (только известные ID, проверка — только строками приёмки) и дополняет
  пропущенные требования; ``coverage()`` и ``coverage_table_md()`` строят матрицу покрытия.

Выход: ``{"candidates", "pair_checks", "trace", "glossary"}`` по CONTRACT 2.3/2.5.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

STAGE = "consistency"
SOURCE = "consistency"

MAX_PAIRS = 15
MAX_UNDEFINED_CANDIDATES = 3
MAX_MODEL_CANDIDATES = 8
MAX_GLOSSARY = 8

# Требования, для которых строится трассировка (CONTRACT 2.2, поле kind).
TRACE_KINDS = ("functional", "nonfunctional", "data", "integration", "constraint")
# Что может «реализовывать» требование.
IMPLEMENT_KINDS = ("api", "data", "integration", "architecture", "functional", "constraint", "process", "ui")

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
SEVERITIES = ["critical", "major", "minor"]
BLOCKS = ["development", "testing", "both", "none"]

CONFLICT_KINDS = ("event_conflict", "status_conflict", "boundary_conflict", "unit_mismatch", "contradiction")
PAIR_KINDS = list(CONFLICT_KINDS) + ["ambiguity", "incomplete"]
VERDICTS = ["conflict", "compatible", "undefined"]
BASES = ["same_condition", "limit_removed", "value_mismatch", "none"]
GLOSSARY_SEVERITIES = ["major", "minor", "none"]


# ---------------------------------------------------------------- схема ответа модели

def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else list(props)}


_S = {"type": "string"}
_I = {"type": "integer"}
_IDS = {"type": "array", "items": _S}

CANDIDATE_SCHEMA = _obj({
    "title": _S, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": SEVERITIES},
    "requirement_ids": _IDS,
    "evidence": {"type": "array", "items": _obj({"quote": _S, "line": _I})},
    "problem": _S, "scenario": _S, "impact": _S, "recommendation": _S, "rewrite": _S, "question": _S,
    "blocks": {"type": "string", "enum": BLOCKS},
})

PAIR_SCHEMA = _obj({
    "a": _S, "b": _S, "subject": _S, "same_subject": {"type": "boolean"},
    "quote_a": _S, "line_a": _I, "quote_b": _S, "line_b": _I,
    "scenario": _S, "outcome_a": _S, "outcome_b": _S,
    "verdict": {"type": "string", "enum": VERDICTS},
    "basis": {"type": "string", "enum": BASES},
    "kind": {"type": "string", "enum": PAIR_KINDS},
    "title": _S, "impact": _S, "recommendation": _S, "question": _S,
})

SCHEMA: dict = _obj({
    "subjects": {"type": "array", "items": _obj({"subject": _S, "places": _IDS})},
    "pair_checks": {"type": "array", "items": PAIR_SCHEMA},
    "glossary": {"type": "array", "items": _obj({
        "concept": _S, "terms": {"type": "array", "items": _obj({"term": _S, "line": _I})},
        "problem": _S, "severity": {"type": "string", "enum": GLOSSARY_SEVERITIES}})},
    "trace": {"type": "array", "items": _obj({
        "requirement_id": _S, "verified_by": _IDS, "implemented_by": _IDS, "note": _S})},
    "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
})


# ---------------------------------------------------------------- запуск этапа

def run(ctx: Any) -> dict:
    """Этап набора: один вызов модели и разбор ответа кодом (CONTRACT 3)."""
    system, user = ctx.prompt(STAGE)
    data = ctx.llm.ask(STAGE, system, user, SCHEMA)
    return postprocess(data, ctx.view, getattr(ctx, "requirements", None) or [])


# ---------------------------------------------------------------- сверка цитат

_MD = re.compile(r"\*\*|__|`")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"[«»“”„\"']", '"', s)
    s = re.sub(r"[—–‑−]", "-", s)
    s = _MD.sub("", s)
    s = re.sub(r"^\s*(?:[*#]+\s*)", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _lines(view: Any) -> list[dict]:
    if isinstance(view, dict):
        return list(view.get("lines") or [])
    return list(getattr(view, "lines", None) or [])


def _fallback_verify(view: Any, quote: str, line_hint: int | None) -> dict | None:
    """Упрощённая сверка на случай, если quotes.py №03 недоступен: точное вхождение
    после нормализации, ближайшее к подсказке; затем склейка до трёх соседних строк."""
    q = _norm(quote)
    lines = _lines(view)
    if not q or not lines:
        return None
    hits = [(x["n"], x["n"]) for x in lines if q in _norm(x.get("text", ""))]
    if not hits:
        for i in range(len(lines)):
            for k in (2, 3):
                chunk = lines[i:i + k]
                if len(chunk) == k and q in _norm(" ".join(x.get("text", "") for x in chunk)):
                    hits.append((chunk[0]["n"], chunk[-1]["n"]))
                    break
    verified = "normalized"
    if not hits and line_hint:
        best = _fuzzy_line(q, [x for x in lines if abs(x["n"] - line_hint) <= 5])
        if best is not None:
            hits, verified = [(best, best)], "fuzzy"
    if not hits:
        return None
    hint = line_hint or hits[0][0]
    start, end = min(hits, key=lambda h: (abs(h[0] - hint), h[0]))
    by_n = {x["n"]: x for x in lines}
    first = by_n.get(start, {})
    return {"line_start": start, "line_end": end, "page": first.get("page"),
            "section": first.get("section", ""), "verified": verified, "text": first.get("text", "")}


def _fuzzy_line(q: str, lines: list[dict], threshold: float = 0.92) -> int | None:
    """Строка, в которой есть фрагмент длины цитаты с похожестью ≥ threshold (CONTRACT §7, п. 4)."""
    from difflib import SequenceMatcher

    best_n, best_r = None, threshold
    for x in lines:
        t = _norm(x.get("text", ""))
        if not t:
            continue
        L = len(q)
        windows = [t] if len(t) <= L else [t[i:i + L] for i in range(0, len(t) - L + 1)]
        for w in windows:
            sm = SequenceMatcher(None, q, w)
            if sm.quick_ratio() < best_r:
                continue
            r = sm.ratio()
            if r >= best_r:
                best_n, best_r = x["n"], r
    return best_n


def verify(view: Any, quote: str, line_hint: int | None = None) -> dict | None:
    """Сверка цитаты: quotes.verify_quote (№03), при его отсутствии — упрощённая."""
    try:
        from bcc_review.v2 import quotes  # type: ignore
        m = quotes.verify_quote(view, quote, line_hint=line_hint)
        if m is None:
            return None
        return dict(m)
    except (ImportError, AttributeError):
        return _fallback_verify(view, quote, line_hint)


# ---------------------------------------------------------------- разбор ответа

def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _req_index(requirements: Iterable[dict]) -> dict[str, dict]:
    return {str(r.get("id")): r for r in requirements if r.get("id")}


def _clean_ids(ids: Any, known: dict[str, dict]) -> list[str]:
    out: list[str] = []
    for x in ids or []:
        x = _s(x)
        if x and (not known or x in known) and x not in out:
            out.append(x)
    return out


def _evidence(view: Any, quote: str, line: int | None) -> dict:
    ev = {"quote": _s(quote), "line": line if line is not None else 0}
    m = verify(view, ev["quote"], line) if ev["quote"] else None
    if m:
        ev.update({"line": m.get("line_start", ev["line"]), "line_start": m.get("line_start"),
                   "line_end": m.get("line_end"), "page": m.get("page"), "section": m.get("section", ""),
                   "verified": m.get("verified", "exact")})
    else:
        ev["verified"] = "missing"
    return ev


def _found(ev: dict) -> bool:
    return ev.get("verified") not in (None, "", "missing")


def _span(ev: dict) -> tuple[int, int]:
    a = ev.get("line_start") or ev.get("line") or 0
    b = ev.get("line_end") or a
    return int(a), int(b)


def _overlap(e1: dict, e2: dict, slack: int = 0) -> bool:
    a1, b1 = _span(e1)
    a2, b2 = _span(e2)
    return a1 - slack <= b2 and a2 - slack <= b1


def normalize_pair(p: dict, view: Any, known: dict[str, dict]) -> dict:
    """Пара в формате CONTRACT 2.5 плюс служебные поля разбора (kind, title …)."""
    pair = {
        "a": _s(p.get("a")), "b": _s(p.get("b")), "subject": _s(p.get("subject")),
        "same_subject": bool(p.get("same_subject")),
        "quote_a": _s(p.get("quote_a")), "line_a": _int(p.get("line_a")) or 0,
        "quote_b": _s(p.get("quote_b")), "line_b": _int(p.get("line_b")) or 0,
        "scenario": _s(p.get("scenario")), "outcome_a": _s(p.get("outcome_a")), "outcome_b": _s(p.get("outcome_b")),
        "verdict": p.get("verdict") if p.get("verdict") in VERDICTS else "undefined",
        "basis": p.get("basis") if p.get("basis") in BASES else "",
        "kind": p.get("kind") if p.get("kind") in PAIR_KINDS else "contradiction",
        "title": _s(p.get("title")), "impact": _s(p.get("impact")),
        "recommendation": _s(p.get("recommendation")), "question": _s(p.get("question")),
    }
    ev_a = _evidence(view, pair["quote_a"], pair["line_a"] or None)
    ev_b = _evidence(view, pair["quote_b"], pair["line_b"] or None)
    if _found(ev_a):
        pair["line_a"] = ev_a["line"]
    if _found(ev_b):
        pair["line_b"] = ev_b["line"]
    pair["verified_a"], pair["verified_b"] = ev_a["verified"], ev_b["verified"]
    pair["_ev"] = (ev_a, ev_b)
    # Разные предметы не сравниваются: конфликта между ними быть не может.
    if not pair["same_subject"]:
        pair["verdict"] = "compatible"
    # Конфликт без названного основания (модель сама не нашла ни одного из трёх) — неопределённость.
    if pair["verdict"] == "conflict" and pair["basis"] == "none":
        pair["verdict"] = "undefined"
        if pair["kind"] in ("event_conflict", "status_conflict", "boundary_conflict", "contradiction"):
            pair["kind"] = "ambiguity"
    return pair


# Виды требований, конфликт с которыми не блокирует сам по себе: цель — намерение, а не правило;
# нефункциональное требование о сроке редко противоречит правилу поведения напрямую.
SOFT_KINDS = ("goal", "nonfunctional")
MAJOR_CONFLICT_KINDS = ("unit_mismatch",)


def pair_to_candidate(pair: dict, known: dict[str, dict] | None = None) -> dict | None:
    """conflict → critical с двумя цитатами в разных местах; undefined → major."""
    if not pair["same_subject"] or pair["verdict"] == "compatible":
        return None
    ev_a, ev_b = pair["_ev"]
    evidence = [e for e in (ev_a, ev_b) if e.get("quote")]
    if not any(_found(e) for e in evidence):
        return None  # ни одной найденной цитаты: судье нечего показать
    two_places = _found(ev_a) and _found(ev_b) and not _overlap(ev_a, ev_b)
    kind = pair["kind"]
    if pair["verdict"] == "conflict":
        if kind not in CONFLICT_KINDS:
            kind = "contradiction"
        soft = any((known or {}).get(x, {}).get("kind") in SOFT_KINDS for x in (pair["a"], pair["b"]))
        # Разные единицы одной величины обычно снимаются правилом пересчёта — major; судья может поднять.
        severity = "critical" if two_places and not soft and kind not in MAJOR_CONFLICT_KINDS else "major"
    else:  # undefined
        if kind in ("event_conflict", "status_conflict", "boundary_conflict", "contradiction"):
            kind = "ambiguity"
        severity = "major"
    criterion = "unambiguous" if kind in ("boundary_conflict", "unit_mismatch", "ambiguity") else "set_consistent"
    if pair["verdict"] == "undefined" and kind == "incomplete":
        criterion = "set_complete"
    ids = [x for x in (pair["a"], pair["b"]) if x]
    a_lbl = pair["a"] or f"строка {pair['line_a']}"
    b_lbl = pair["b"] or f"строка {pair['line_b']}"
    if pair["verdict"] == "conflict":
        title = pair["title"] or f"{a_lbl} и {b_lbl} дают несовместимые результаты: {pair['subject']}"
        problem = (f"{a_lbl} и {b_lbl} регулируют один предмет — {pair['subject']} — и в одном сценарии "
                   f"требуют несовместимого: по {a_lbl} — {pair['outcome_a']}; по {b_lbl} — {pair['outcome_b']}. "
                   f"Ни одно место не объявлено исключением из другого.")
    else:
        title = pair["title"] or f"{a_lbl} и {b_lbl} не определяют исход: {pair['subject']}"
        problem = (f"{a_lbl} и {b_lbl} регулируют один предмет — {pair['subject']}, — но исход сценария по ним "
                   f"не определить: по {a_lbl} — {pair['outcome_a']}; по {b_lbl} — {pair['outcome_b']}.")
    scenario = pair["scenario"]
    if scenario and pair["outcome_a"] and pair["outcome_b"]:
        scenario = f"{scenario} Исход по {a_lbl}: {pair['outcome_a']}. Исход по {b_lbl}: {pair['outcome_b']}."
    impact = pair["impact"] or ("Разработчик и тестировщик выберут разные правила: реализация и приёмка "
                                "разойдутся, клиент получит результат, который противоречит одному из пунктов.")
    rec = pair["recommendation"] or f"Выбрать одно правило для этого сценария и записать его в {a_lbl} и {b_lbl} одинаково."
    return {
        "title": title, "kind": kind, "criterion": criterion, "severity": severity,
        "requirement_ids": ids, "evidence": [{k: v for k, v in e.items()} for e in evidence],
        "problem": problem, "scenario": scenario, "impact": impact, "recommendation": rec,
        "rewrite": "", "question": pair["question"], "blocks": "both",
        "source": SOURCE, "origin": "pair_check",
    }


_WORD = re.compile(r"[\wё]+", re.I)


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    return w if len(w) <= 4 else w[:max(4, len(w) - 2)]


def _same_stem(tok: str, word: str) -> bool:
    if tok.startswith(word):
        return True
    return word.startswith(tok) and len(tok) >= max(3, len(word) - 2)


def find_term(view: Any, term: str, line_hint: int | None, radius: int = 2) -> tuple[str, int] | None:
    """Термин в другом падеже или числе («владелец карты» в строке «сессия владельца карты»):
    ищем подряд идущие слова строки с теми же основами рядом с подсказкой и возвращаем
    дословный фрагмент строки, чтобы цитата прошла общую сверку."""
    words = [_stem(w) for w in _WORD.findall(term)]
    if not words:
        return None
    lines = _lines(view)
    if line_hint:
        cand = sorted((x for x in lines if abs(x["n"] - line_hint) <= radius), key=lambda x: abs(x["n"] - line_hint))
    else:
        cand = lines
    for x in cand:
        text = str(x.get("text", ""))
        toks = [(m.start(), m.end(), _stem(m.group())) for m in _WORD.finditer(text)]
        for i in range(len(toks) - len(words) + 1):
            if all(_same_stem(toks[i + k][2], words[k]) for k in range(len(words))):
                return text[toks[i][0]:toks[i + len(words) - 1][1]], x["n"]
    return None


def normalize_glossary(g: dict, view: Any) -> dict | None:
    terms = []
    seen: set[str] = set()
    for t in g.get("terms") or []:
        term = _s(t.get("term"))
        if not term or _norm(term) in seen:
            continue
        seen.add(_norm(term))
        line = _int(t.get("line")) or 0
        verified = "missing"
        # Сначала целыми словами рядом с подсказкой (термин мог стоять в другом падеже),
        # затем обычная сверка цитаты по всему документу, затем словами по всему документу.
        hit = find_term(view, term, line or None) if line else None
        if hit:
            term, line, verified = hit[0], hit[1], "normalized"
        else:
            m = verify(view, term, line or None)
            if m:
                line, verified = m.get("line_start") or line, m.get("verified", "exact")
            else:
                hit = find_term(view, term, None)
                if hit:
                    term, line, verified = hit[0], hit[1], "normalized"
        if verified != "missing" and _norm(term) != _norm(_s(t.get("term"))):
            if _norm(term) in seen:
                continue
            seen.add(_norm(term))
        terms.append({"term": term, "line": line, "verified": verified})
    if len(terms) < 2:
        return None
    sev = g.get("severity") if g.get("severity") in GLOSSARY_SEVERITIES else "minor"
    return {"concept": _s(g.get("concept")), "terms": terms, "problem": _s(g.get("problem")), "severity": sev}


def glossary_to_candidate(g: dict) -> dict | None:
    if g["severity"] == "none":
        return None
    found = [t for t in g["terms"] if t["verified"] != "missing"]
    if len(found) < 2:
        return None
    names = ", ".join(f"«{t['term']}» (L{t['line']:03d})" for t in found)
    first = found[0]["term"]
    severity = "major" if g["severity"] == "major" else "minor"
    problem = g["problem"] or "Одно понятие названо в документе по-разному, и по тексту не понять, одно ли это."
    return {
        "title": f"Одно понятие «{g['concept']}» названо по-разному: " + ", ".join(f"«{t['term']}»" for t in found[:4]),
        "kind": "terminology", "criterion": "conforming", "severity": severity, "requirement_ids": [],
        "evidence": [{"quote": t["term"], "line": t["line"], "verified": t["verified"]} for t in found[:4]],
        "problem": f"{problem} Названия: {names}.",
        "scenario": "",
        "impact": ("Разработчики разных компонентов и тестировщик могут понять названия как разные сущности: "
                   "появятся лишние связи, проверки прав или полей." if severity == "major" else
                   "Документ труднее читать и искать по нему; растёт риск ошибки при изменениях."),
        "recommendation": (f"Выбрать одно название (например, «{first}»), заменить им остальные во всех частях "
                           f"документа и добавить его в глоссарий с определением."),
        "rewrite": "", "question": "", "blocks": "development" if severity == "major" else "none",
        "source": SOURCE, "origin": "glossary",
    }


def minor_glossary_candidate(entries: list[dict]) -> dict | None:
    """Все синонимы без влияния на реализацию — одно замечание minor на документ."""
    found = [(g, [t for t in g["terms"] if t["verified"] != "missing"]) for g in entries if g["severity"] == "minor"]
    found = [(g, ts) for g, ts in found if len(ts) >= 2]
    if not found:
        return None
    evidence, parts = [], []
    for g, ts in found:
        parts.append(f"{g['concept']}: " + ", ".join(f"«{t['term']}» (L{t['line']:03d})" for t in ts[:4]))
        for t in ts[:2]:
            if len(evidence) < 6:
                evidence.append({"quote": t["term"], "line": t["line"], "verified": t["verified"]})
    concepts = ", ".join(f"«{g['concept']}»" for g, _ in found[:3])
    return {
        "title": f"Терминология не едина, глоссария нет: {concepts}" + (" и др." if len(found) > 3 else ""),
        "kind": "terminology", "criterion": "conforming", "severity": "minor", "requirement_ids": [],
        "evidence": evidence,
        "problem": "Одни и те же понятия названы в разных частях документа по-разному. " + "; ".join(parts) + ".",
        "scenario": "", "impact": "Документ труднее читать и искать по нему; при изменениях легко поправить одно "
                                  "название и пропустить другое.",
        "recommendation": "Добавить в документ глоссарий и использовать в каждой части одно название для каждого "
                          "понятия.",
        "rewrite": "", "question": "", "blocks": "none", "source": SOURCE, "origin": "glossary",
    }


def merge_conflicts(cands: list[dict]) -> list[dict]:
    """Конфликты одного вида, у которых общая строка (одно правило против нескольких мест), — одно замечание."""
    out: list[dict] = []
    for c in cands:
        host = None
        if c["kind"] in CONFLICT_KINDS:
            for o in out:
                if o["kind"] == c["kind"] and o["severity"] == c["severity"] and any(
                        _overlap(e1, e2) for e1 in o["evidence"] for e2 in c["evidence"] if _found(e1) and _found(e2)):
                    host = o
                    break
        if host is None:
            out.append(c)
            continue
        for e in c["evidence"]:
            if not any(_overlap(e, h) and _norm(e["quote"]) == _norm(h["quote"]) for h in host["evidence"]):
                host["evidence"].append(e)
        for rid in c["requirement_ids"]:
            if rid not in host["requirement_ids"]:
                host["requirement_ids"].append(rid)
        host["problem"] += f" Также: {c['title']}."
        host.setdefault("merged_titles", []).append(c["title"])
    return out


def _requirement_ids_for_lines(ev_list: list[dict], requirements: list[dict]) -> list[str]:
    out: list[str] = []
    for ev in ev_list:
        a, b = _span(ev)
        for r in requirements:
            rs, re_ = r.get("line_start") or 0, r.get("line_end") or r.get("line_start") or 0
            if rs and rs <= b and a <= re_ and r["id"] not in out:
                out.append(r["id"])
    return out


def normalize_candidate(c: dict, view: Any, known: dict[str, dict], requirements: list[dict]) -> dict | None:
    evidence = [_evidence(view, _s(e.get("quote")), _int(e.get("line"))) for e in c.get("evidence") or []
                if _s(e.get("quote"))]
    if not evidence:
        return None
    cand = {
        "title": _s(c.get("title")),
        "kind": c.get("kind") if c.get("kind") in KINDS else "other",
        "criterion": c.get("criterion") if c.get("criterion") in CRITERIA else "set_consistent",
        "severity": c.get("severity") if c.get("severity") in SEVERITIES else "major",
        "requirement_ids": _clean_ids(c.get("requirement_ids"), known),
        "evidence": evidence,
        "problem": _s(c.get("problem")), "scenario": _s(c.get("scenario")), "impact": _s(c.get("impact")),
        "recommendation": _s(c.get("recommendation")), "rewrite": _s(c.get("rewrite")),
        "question": _s(c.get("question")),
        "blocks": c.get("blocks") if c.get("blocks") in BLOCKS else "none",
        "source": SOURCE, "origin": "model",
    }
    if not cand["requirement_ids"]:
        cand["requirement_ids"] = _requirement_ids_for_lines(evidence, requirements)
    # critical без сценария, последствий или блокировки по шкале не бывает.
    if cand["severity"] == "critical" and (not cand["scenario"] or not cand["impact"] or cand["blocks"] == "none"):
        cand["severity"] = "major"
    if cand["severity"] == "critical" and cand["blocks"] == "none":
        cand["blocks"] = "both"
    return cand


def _duplicates_pair(cand: dict, pair_cands: list[dict]) -> bool:
    """Кандидат модели повторяет конфликт из pair_checks: тот же тип семейства противоречий
    и пересечение по строкам с обеими цитатами пары."""
    if cand["kind"] not in CONFLICT_KINDS and cand["kind"] not in ("ambiguity", "incomplete"):
        return False
    for pc in pair_cands:
        hits = sum(1 for pe in pc["evidence"] if any(_overlap(pe, ce, 1) for ce in cand["evidence"]))
        if hits >= min(2, len(pc["evidence"])):
            return True
    return False


def normalize_trace(raw: list[dict], requirements: list[dict]) -> list[dict]:
    known = _req_index(requirements)
    acceptance = {rid for rid, r in known.items() if r.get("kind") == "acceptance"}
    implementers = {rid for rid, r in known.items() if r.get("kind") in IMPLEMENT_KINDS}
    targets = [r["id"] for r in requirements if r.get("kind") in TRACE_KINDS and r.get("id")]
    by_id: dict[str, dict] = {}
    for t in raw or []:
        rid = _s(t.get("requirement_id"))
        if not rid or (known and rid not in known) or rid in by_id:
            continue
        verified = [x for x in _clean_ids(t.get("verified_by"), known) if not acceptance or x in acceptance]
        implemented = [x for x in _clean_ids(t.get("implemented_by"), known)
                       if x != rid and (not implementers or x in implementers)]
        note = _s(t.get("note"))
        if not verified and not note:
            note = "нет критерия приёмки"
        by_id[rid] = {"requirement_id": rid, "verified_by": verified, "implemented_by": implemented, "note": note}
    for rid in targets:
        if rid not in by_id:
            by_id[rid] = {"requirement_id": rid, "verified_by": [], "implemented_by": [],
                          "note": "трассировка не построена"}
    order = {r.get("id"): i for i, r in enumerate(requirements)}
    return sorted(by_id.values(), key=lambda t: order.get(t["requirement_id"], 10 ** 6))


def postprocess(data: dict, view: Any, requirements: list[dict]) -> dict:
    """Ответ модели → выход этапа по CONTRACT 2.3/2.5 (чистая функция, тестируется на записанных ответах)."""
    data = data or {}
    known = _req_index(requirements)

    pairs = [normalize_pair(p, view, known) for p in (data.get("pair_checks") or [])[:MAX_PAIRS * 2]]
    # Дубли пар (те же две строки) и пары «место само с собой» убираем.
    uniq: list[dict] = []
    seen: set[tuple] = set()
    for p in pairs:
        ev_a, ev_b = p["_ev"]
        if _found(ev_a) and _found(ev_b) and _overlap(ev_a, ev_b) and _norm(p["quote_a"]) == _norm(p["quote_b"]):
            continue
        key = tuple(sorted([(p["line_a"], _norm(p["quote_a"])[:40]), (p["line_b"], _norm(p["quote_b"])[:40])]))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    pairs = uniq[:MAX_PAIRS]

    candidates: list[dict] = []
    pair_cands: list[dict] = []
    undefined = 0
    for p in pairs:
        c = pair_to_candidate(p, known)
        if not c:
            continue
        if p["verdict"] == "undefined":
            undefined += 1
            if undefined > MAX_UNDEFINED_CANDIDATES:
                continue
        pair_cands.append(c)
    pair_cands = merge_conflicts(pair_cands)
    candidates.extend(pair_cands)

    glossary = [g for g in (normalize_glossary(g, view) for g in (data.get("glossary") or [])[:MAX_GLOSSARY]) if g]
    for g in glossary:
        if g["severity"] == "major":
            c = glossary_to_candidate(g)
            if c:
                candidates.append(c)
    c = minor_glossary_candidate(glossary)
    if c:
        candidates.append(c)

    for raw in (data.get("candidates") or [])[:MAX_MODEL_CANDIDATES]:
        c = normalize_candidate(raw, view, known, requirements)
        if c and not _duplicates_pair(c, pair_cands):
            candidates.append(c)

    trace = normalize_trace(data.get("trace") or [], requirements)

    out_pairs = []
    for p in pairs:
        q = {k: v for k, v in p.items() if not k.startswith("_")}
        out_pairs.append(q)
    out_glossary = [{"concept": g["concept"], "terms": [{"term": t["term"], "line": t["line"]} for t in g["terms"]],
                     "problem": g["problem"], "severity": g["severity"]} for g in glossary]
    return {"candidates": candidates, "pair_checks": out_pairs, "trace": trace, "glossary": out_glossary,
            "subjects": list(data.get("subjects") or [])}


# ---------------------------------------------------------------- матрица покрытия

def coverage(trace: list[dict]) -> dict:
    """Сводка покрытия: сколько требований проверено приёмкой и реализовано в API/данных."""
    total = len(trace)
    verified = [t["requirement_id"] for t in trace if t.get("verified_by")]
    implemented = [t["requirement_id"] for t in trace if t.get("implemented_by")]
    return {"total": total, "verified": len(verified), "implemented": len(implemented),
            "not_verified": [t["requirement_id"] for t in trace if not t.get("verified_by")],
            "not_implemented": [t["requirement_id"] for t in trace if not t.get("implemented_by")]}


def coverage_table_md(trace: list[dict], requirements: list[dict]) -> str:
    """Матрица покрытия Markdown: требование → проверка приёмкой → реализация → чего не хватает."""
    known = _req_index(requirements)

    def label(rid: str) -> str:
        r = known.get(rid) or {}
        src = r.get("source_id") or ""
        return f"{rid} ({src})" if src and len(src) <= 24 else rid

    rows = ["| Требование | Проверяется приёмкой | Реализуется в | Чего не хватает |",
            "| :--- | :--- | :--- | :--- |"]
    for t in trace:
        rows.append("| {} | {} | {} | {} |".format(
            label(t["requirement_id"]),
            ", ".join(t.get("verified_by") or []) or "—",
            ", ".join(t.get("implemented_by") or []) or "—",
            (t.get("note") or "").replace("|", "/") or "—"))
    cov = coverage(trace)
    rows.append("")
    rows.append(f"Проверены приёмкой: {cov['verified']} из {cov['total']}; "
                f"реализация указана: {cov['implemented']} из {cov['total']}.")
    return "\n".join(rows)
