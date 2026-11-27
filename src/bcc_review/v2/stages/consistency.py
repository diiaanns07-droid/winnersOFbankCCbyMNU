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

# Ответ этапа ≈ 8–9 тыс. токенов JSON, но модели с рассуждением (haiku через claude -p) тратят ещё
# 25–40 тыс. на рассуждение: при 16 000 ответ обрезался. Как у судьи — 32 000.
MAX_OUTPUT_TOKENS = 32000
# Повтор при обрезке: тот же запрос с просьбой отвечать короче.
SHORT_MODE = ("\n\n### Краткий режим\nПредыдущий ответ не поместился. Отвечай короче: subjects — до 8, pair_checks — "
              "до 8 самых рискованных, glossary — до 4, trace — только для функциональных требований с пустой note, "
              "если всего хватает, candidates — до 5; каждое текстовое поле — одна фраза.")

MAX_PAIRS = 15
MAX_UNDEFINED_CANDIDATES = 2
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
# У пары вид конфликта всегда конкретный: общий «contradiction» счётчик засчитывает только уровнем родителя.
PAIR_CONFLICT_KINDS = ("event_conflict", "status_conflict", "boundary_conflict", "unit_mismatch")
PAIR_KINDS = list(PAIR_CONFLICT_KINDS) + ["ambiguity", "incomplete"]
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
    "scenario": _S, "outcome_a": _S, "outcome_b": _S, "one_condition": {"type": "boolean"},
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
    try:
        data = ctx.llm.ask(STAGE, system, user, SCHEMA, max_output_tokens=MAX_OUTPUT_TOKENS)
    except Exception as exc:  # noqa: BLE001 — повторяем только обрезанный ответ
        if type(exc).__name__ != "Truncated":
            raise
        if hasattr(ctx, "warn"):
            ctx.warn("Проверка набора: ответ модели обрезан, повтор в кратком режиме.")
        data = ctx.llm.ask(STAGE, system, user + SHORT_MODE, SCHEMA, max_output_tokens=MAX_OUTPUT_TOKENS)
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
        "one_condition": p.get("one_condition") is not False,  # нет поля (старые ответы) — одно условие
        "verdict": p.get("verdict") if p.get("verdict") in VERDICTS else "undefined",
        "basis": p.get("basis") if p.get("basis") in BASES else "",
        "kind": p.get("kind") if p.get("kind") in PAIR_KINDS else "event_conflict",
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
    # Цель и НФТ о сроке не задают поведение в событии (контрпример 2 промпта) — пара о событии с ними совместима.
    side_kinds = [(known or {}).get(x, {}).get("kind") for x in (pair["a"], pair["b"])]
    if any(k in SOFT_KINDS for k in side_kinds) and pair["kind"] not in ("unit_mismatch", "boundary_conflict"):
        pair["verdict"], pair["basis"] = "compatible", "none"
    # Исходы вызваны двумя разными условиями, соединёнными в один сценарий, — это порядок проверок, не конфликт.
    if pair["verdict"] == "conflict" and not pair["one_condition"]:
        pair["basis"] = "none"
    # Условное право («может …, если нет X») — необходимое, а не достаточное условие: запрет для другого состояния
    # с ним не спорит (контрпример 7 промпта, который слабая модель пропускает).
    if (pair["verdict"] == "conflict" and pair["kind"] in ("event_conflict", "status_conflict")
            and (_PERMISSION.search(pair["quote_a"]) or _PERMISSION.search(pair["quote_b"]))):
        pair["basis"] = "none"
    # Конфликт без названного основания (модель сама не нашла ни одного из трёх) — неопределённость.
    if pair["verdict"] == "conflict" and pair["basis"] == "none":
        pair["verdict"] = "undefined"
        if pair["kind"] in ("event_conflict", "status_conflict", "boundary_conflict", "contradiction"):
            pair["kind"] = "ambiguity"
    # Обратная ошибка слабой модели: одна сторона ограничивает действие («максимум», «не более»), другая прямо
    # снимает ограничение («независимо от», «без ограничения»), а вердикт — «не определено». Это limit_removed.
    elif (pair["verdict"] == "undefined" and pair["same_subject"] and pair["one_condition"] and _found(ev_a) and _found(ev_b)
          and not _overlap(ev_a, ev_b) and _removes_limit(pair["quote_a"], pair["quote_b"])):
        pair.update(verdict="conflict", basis="limit_removed", kind="event_conflict")
    return pair


_PERMISSION = re.compile(r"(?<![а-яё])(?:может|могут|можно|вправе|разрешен\w*|доступн\w*)(?![а-яё])[^.;]{0,80}?"
                         r"(?<![а-яё])если(?![а-яё])", re.I)
_CODE = re.compile(r"(?<!\d)[1-5]\d\d(?!\d)")


def _same_codes(qa: str, qb: str) -> bool:
    """Обе цитаты называют коды ответа, и коды одной входят в коды другой (второго кода для входа нет)."""
    a, b = set(_CODE.findall(qa)), set(_CODE.findall(qb))
    return bool(a and b and (a <= b or b <= a))


_LIMIT_REMOVED = re.compile(r"независимо от|вне зависимости от|без ограничени|в любом случае", re.I)
_LIMIT = re.compile(r"\b(не более|не больше|не чаще|максимум|не свыше|только один|только одн|один раз|"
                    r"не превыша\w*|не может превышать)\b", re.I)


def _removes_limit(qa: str, qb: str) -> bool:
    """Одна цитата снимает ограничение, другая его задаёт (без слов снятия)."""
    return any(_LIMIT_REMOVED.search(x) and _LIMIT.search(y) and not _LIMIT_REMOVED.search(y)
               for x, y in ((qa, qb), (qb, qa)))


# Виды требований, конфликт с которыми не блокирует сам по себе: цель — намерение, а не правило;
# нефункциональное требование о сроке редко противоречит правилу поведения напрямую.
SOFT_KINDS = ("goal", "nonfunctional")
SCHEMA_KINDS = ("architecture", "process")
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
    # Цель и НФТ о сроке не задают поведение в событии: «пополнение за 5 минут ↔ после отключения не пополнять»
    # — не два исхода. Цель ↔ требования проверяет п. 1 шага 5; пара с ними — только о значении или единице.
    side_kinds = [(known or {}).get(x, {}).get("kind") for x in (pair["a"], pair["b"])]
    if any(k in SOFT_KINDS for k in side_kinds) and kind not in ("unit_mismatch", "boundary_conflict"):
        return None
    if pair["verdict"] == "conflict":
        if kind not in PAIR_CONFLICT_KINDS:
            kind = "event_conflict"
        kinds = [(known or {}).get(x, {}).get("kind") for x in (pair["a"], pair["b"])]
        # Цель и НФТ — не правило поведения; две схемы (архитектура ↔ процесс/последовательность) расходятся
        # в связях — это согласованность схем, существенный дефект, а не «один вход — два исхода».
        soft = any(k in SOFT_KINDS for k in kinds) or all(k in SCHEMA_KINDS for k in kinds)
        # Разные единицы одной величины обычно снимаются правилом пересчёта — major; судья может поднять.
        severity = "critical" if two_places and not soft and kind not in MAJOR_CONFLICT_KINDS else "major"
        # «Один вход — два кода»: если цитаты не называют двух разных кодов (обе о коде 200, одна шире другой),
        # спор о смысле кода, а не два исхода — major.
        if kind == "status_conflict" and _same_codes(pair["quote_a"], pair["quote_b"]):
            severity = "major"
    else:  # undefined
        # Строка приёмки сверяется только на противоречие (шаг 2б); её неполноту проверяет линза тестировщика.
        if any((known or {}).get(x, {}).get("kind") == "acceptance" for x in (pair["a"], pair["b"])):
            return None
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
        "source": SOURCE, "origin": "pair_check", "pair_ids": [pair["id"]] if pair.get("id") else [],
        "_subject": pair["subject"],
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
        "source": SOURCE, "origin": "glossary", "glossary_ids": [g["id"]] if g.get("id") else [],
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
        "glossary_ids": [g["id"] for g, _ in found if g.get("id")],
    }


def _blocks(c: dict, requirements: list[dict]) -> set:
    """Места кандидата: строки цитат и многострочные блоки требований, в которые они попали
    (пример тела ответа на несколько строк — одно место)."""
    out: set = set()
    for e in c["evidence"]:
        if not _found(e):
            continue
        a, b = _span(e)
        out.update(("L", n) for n in range(a, b + 1))
        for r in requirements:
            rs, re_ = r.get("line_start") or 0, r.get("line_end") or 0
            if rs and re_ > rs and rs <= b and a <= re_:
                out.add(("R", r.get("id")))
    return out


_STOP = {"между", "против", "значение", "значения", "требование", "требования", "правило", "правила", "пункт",
          "строка", "строки", "место", "места", "одного", "одной", "одном", "разные", "разный", "разных", "также"}


def _subject_stems(s: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(s or "") if len(w) >= 4 and w.lower() not in _STOP and not w.isdigit()}


def same_subject_text(a: str, b: str) -> bool:
    """Предметы двух пар об одном: не меньше половины значимых основ короткого предмета есть в другом.
    Пустой предмет не мешает склейке (старые ответы без предмета)."""
    sa, sb = _subject_stems(a), _subject_stems(b)
    if not sa or not sb:
        return True
    return len(sa & sb) / min(len(sa), len(sb)) >= 0.5


def merge_conflicts(cands: list[dict], requirements: list[dict] | None = None) -> list[dict]:
    """Конфликты одного вида, у которых общее место (одно правило против нескольких мест) и один предмет, —
    одно замечание. Разные предметы при общей строке (в одном пункте два правила) — разные замечания."""
    out: list[dict] = []
    reqs = requirements or []
    for c in cands:
        host = None
        if c["kind"] in CONFLICT_KINDS:
            mine = _blocks(c, reqs)
            for o in out:
                if (o["kind"] == c["kind"] and o["severity"] == c["severity"] and mine & _blocks(o, reqs)
                        and same_subject_text(o.get("_subject", ""), c.get("_subject", ""))):
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
        for pid in c.get("pair_ids") or []:
            if pid not in host.setdefault("pair_ids", []):
                host["pair_ids"].append(pid)
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
    # «Обещано, но не описано»: если все названные в цитатах методы и поля описаны в заголовках документа,
    # обещанное на месте — это не critical (модель приняла соседний процесс за обещанную операцию).
    # Если ни одна цитируемая строка не обещает действие словами (экран с элементом, перечень систем, пример ответа),
    # обещания нет, есть только догадка модели — тоже не critical.
    if cand["severity"] == "critical" and cand["kind"] == "missing_element" and (
            _all_named_described(evidence, view) or not _promises(" ".join(_s(e.get("quote")) for e in evidence))
            and not _PROMISE_SUBJ.search(" ".join(_cited_texts(evidence, view)))):
        cand["severity"] = "major"
    return cand


_IDENT = re.compile(r"\b[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+\b|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
# Глаголы обещанного действия (основы, с начала слова): читает, получает, отдаёт, возвращает, сохраняет, показывает…
_VERB = (r"(?<![а-яё])(?:чита|получа|получ|отда|возвра|верн|сохран|показ|отобра|вызыв|отправ|запраш|"
         r"переда|хран|меня|измен|удал|созда|отмен|отзыв|включ|выключ|рассчит|подключ|оформл|"
         r"выполн|формир|загруж|обновл|блокир|разблокир|приходит|присыла)")
_PROMISE = re.compile(_VERB, re.I)
# Обещание интерфейса: действие приложения, клиента, экрана — в одной фразе с глаголом; или шаг логики («вернуть 409»).
_PROMISE_SUBJ = re.compile(r"(?<![а-яё])(?:приложени|клиент|экран|интерфейс|пользовател|мобильн)\w*[^.;|]{0,80}?"
                           + _VERB, re.I)
_PROMISE_STEP = re.compile(r"(?<![а-яё])(?:вернуть|возвращать|отдать|отдавать|передать|отправить|показать|"
                           r"сохранить|вызвать)(?![а-яё])", re.I)


def _promises(text: str) -> bool:
    """Цитаты содержат обещание операции интерфейса (а не действие внутреннего сервиса или элемент экрана)."""
    return bool(_PROMISE_SUBJ.search(text) or _PROMISE_STEP.search(text))


def _headings(view: Any) -> list[str]:
    return [_s(x.get("text")) for x in _lines(view) if x.get("heading") or x.get("kind") == "heading"]


def _cited_texts(evidence: list[dict], view: Any) -> list[str]:
    """Цитаты и полный текст найденных строк."""
    by_n = {x.get("n"): _s(x.get("text")) for x in _lines(view)}
    texts = []
    for e in evidence:
        texts.append(_s(e.get("quote")))
        if _found(e):
            a, b = _span(e)
            texts.extend(by_n.get(n, "") for n in range(a, b + 1))
    return texts


def _all_named_described(evidence: list[dict], view: Any) -> bool:
    """Все идентификаторы (camelCase, snake_case) из цитируемых строк встречаются в заголовках документа."""
    texts = _cited_texts(evidence, view)
    names = {m.group(0) for t in texts for m in _IDENT.finditer(t)}
    heads = " ".join(_headings(view))
    return bool(names) and bool(heads) and all(re.search(rf"\b{re.escape(n)}\b", heads) for n in names)


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
    for i, p in enumerate(pairs, 1):
        p["id"] = f"P-{i:02d}"

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
    pair_cands = merge_conflicts(pair_cands, requirements)
    for c in pair_cands:
        c.pop("_subject", None)
    candidates.extend(pair_cands)

    glossary = [g for g in (normalize_glossary(g, view) for g in (data.get("glossary") or [])[:MAX_GLOSSARY]) if g]
    for i, g in enumerate(glossary, 1):
        g["id"] = f"G-{i:02d}"
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
    out_glossary = [{"id": g["id"], "concept": g["concept"],
                     "terms": [{"term": t["term"], "line": t["line"]} for t in g["terms"]],
                     "problem": g["problem"], "severity": g["severity"]} for g in glossary]
    return {"candidates": candidates, "pair_checks": out_pairs, "trace": trace, "glossary": out_glossary,
            "subjects": list(data.get("subjects") or [])}


# ---------------------------------------------------------------- ссылки на итоговые дефекты

MAX_TRACE_LINKS = 3
# Дефект, который касается почти всех требований (нет приоритетов, нет ID), строку матрицы не объясняет.
MAX_TRACE_SPREAD = 6
_SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}


def link_trace(trace: list[dict], findings: list[dict]) -> None:
    """``finding_ids`` строки матрицы покрытия: до трёх итоговых дефектов, которые называют это требование
    (сначала критичные), кроме дефектов «обо всём наборе». Меняет список на месте."""
    ranked = sorted((f for f in findings or [] if f.get("id")),
                    key=lambda f: (_SEV_ORDER.get(f.get("severity"), 3), str(f.get("id"))))
    for t in trace or []:
        rid = t.get("requirement_id")
        ids = [str(f["id"]) for f in ranked
               if rid in (f.get("requirement_ids") or []) and len(f.get("requirement_ids") or []) <= MAX_TRACE_SPREAD]
        if ids:
            t["finding_ids"] = ids[:MAX_TRACE_LINKS]


def link_findings(pair_checks: list[dict], glossary: list[dict], candidates: list[dict],
                  findings: list[dict], trace: list[dict] | None = None) -> None:
    """Проставить ``finding_ids`` парам (P-xx) и понятиям глоссария (G-xx) по цепочке
    пара → кандидат этапа (``pair_ids`` / ``glossary_ids``) → итоговый дефект (``candidate_ids``),
    а если передана трассировка — и строкам матрицы покрытия (``link_trace``).
    Вызывается конвейером после судьи; меняет списки на месте."""
    if trace is not None:
        link_trace(trace, findings)
    by_cand: dict[str, list[str]] = {}
    for f in findings or []:
        for cid in f.get("candidate_ids") or []:
            by_cand.setdefault(str(cid), []).append(str(f.get("id")))
    by_pair: dict[str, list[str]] = {}
    by_term: dict[str, list[str]] = {}
    for c in candidates or []:
        fids = by_cand.get(str(c.get("id")), [])
        if not fids:
            continue
        for pid in c.get("pair_ids") or []:
            by_pair.setdefault(pid, []).extend(fids)
        for gid in c.get("glossary_ids") or []:
            by_term.setdefault(gid, []).extend(fids)
    for p in pair_checks or []:
        if p.get("id") in by_pair:
            p["finding_ids"] = list(dict.fromkeys(by_pair[p["id"]]))
    for g in glossary or []:
        if g.get("id") in by_term:
            g["finding_ids"] = list(dict.fromkeys(by_term[g["id"]]))


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
