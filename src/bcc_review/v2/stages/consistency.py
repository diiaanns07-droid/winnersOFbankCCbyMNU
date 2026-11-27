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

def _ask(ctx: Any, system: str, user: str, schema: dict) -> dict:
    try:
        return ctx.llm.ask(STAGE, system, user, schema, max_output_tokens=MAX_OUTPUT_TOKENS)
    except Exception as exc:  # noqa: BLE001 — повторяем только обрезанный ответ
        if type(exc).__name__ != "Truncated":
            raise
        if hasattr(ctx, "warn"):
            ctx.warn("Проверка набора: ответ модели обрезан, повтор в кратком режиме.")
        return ctx.llm.ask(STAGE, system, user + SHORT_MODE, schema, max_output_tokens=MAX_OUTPUT_TOKENS)


# Деление этапа на два параллельных вызова (опция `consistency_split`, по умолчанию выключено): время этапа задаёт
# рассуждение модели (≈ 80 % токенов вывода), а оно растёт с числом шагов. (А) предметы и попарная сверка с граничными
# строками, (Б) глоссарий, трассировка и дефекты набора. Цена — +1 вызов на прогон.
SPLIT_OPTION = "consistency_split"
PART_A = ("subjects", "pair_checks")
PART_B = ("glossary", "trace", "candidates")
_PART_NOTE = {
    PART_A: ("\n\n### Твоя часть\nВыполни только шаги 1, 2 и 2б: ответ — `subjects` и `pair_checks`. Глоссарий, "
             "трассировку и дефекты набора проверяет другой ревьюер: обещанную, но не описанную операцию (метод, поле, "
             "экран без источника данных), цель и схемы в pair_checks не пиши."),
    PART_B: ("\n\n### Твоя часть\nВыполни только шаги 3, 4 и 5: ответ — `glossary`, `trace` и `candidates`. Предметы и "
             "попарную сверку (шаги 1, 2, 2б) выполняет другой ревьюер: противоречия пар в candidates не пиши."),
}


def _split_wanted(ctx: Any) -> bool:
    opts = getattr(ctx, "options", None) or {}
    return bool(opts.get(SPLIT_OPTION))


def _part_task(user: str, part: tuple) -> str:
    """Задание одной части: общий вход (документ, таблица требований), вводный абзац и только свои шаги."""
    i = user.rfind("## Задача: проверка набора")
    if i < 0:
        return user + _PART_NOTE[part]
    head, task = user[:i], user[i:]
    blocks = re.split(r"(?m)^(?=### Шаг )", task)
    keep = ("### Шаг 1", "### Шаг 2") if part == PART_A else ("### Шаг 3", "### Шаг 4", "### Шаг 5")
    body = [blocks[0]] + [b for b in blocks[1:] if b.startswith(keep)]
    return head + "".join(body).rstrip() + _PART_NOTE[part]


def _run_split(ctx: Any, system: str, user: str) -> dict:
    import concurrent.futures as cf
    schemas = {part: _obj({k: SCHEMA["properties"][k] for k in part}) for part in (PART_A, PART_B)}
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {part: ex.submit(_ask, ctx, system, _part_task(user, part), schemas[part]) for part in schemas}
    data: dict = {}
    errors = []
    for part, fut in futs.items():
        try:
            data.update(fut.result() or {})
        except Exception as exc:  # noqa: BLE001 — одна часть не роняет другую
            errors.append(exc)
            if hasattr(ctx, "warn"):
                what = "попарная сверка" if part == PART_A else "глоссарий, трассировка и дефекты набора"
                ctx.warn(f"Проверка набора: часть «{what}» не получена ({type(exc).__name__}).")
    if len(errors) == 2:
        raise errors[0]
    return data


def run(ctx: Any) -> dict:
    """Этап набора: один вызов модели (или два параллельных — опция) и разбор ответа кодом (CONTRACT 3)."""
    system, user = ctx.prompt(STAGE)
    data = _run_split(ctx, system, user) if _split_wanted(ctx) else _ask(ctx, system, user, SCHEMA)
    reqs = getattr(ctx, "requirements", None) or []
    if _degenerate(data, reqs) and hasattr(ctx, "warn"):
        ctx.warn("Проверка набора: ответ модели неполный — нет трассировки, глоссария и дефектов набора; "
                 "противоречия набора могут быть пропущены.")
    return postprocess(data, ctx.view, reqs)


def _degenerate(data: dict, requirements: list[dict]) -> bool:
    """Ответ прошёл схему, но пуст по всем частям, кроме пар (сбой модели: оборванный разбор), — на документе,
    где есть что трассировать."""
    targets = sum(1 for r in requirements if r.get("kind") in TRACE_KINDS)
    return (targets >= 3 and not (data or {}).get("trace") and not (data or {}).get("glossary")
            and not (data or {}).get("candidates") and len((data or {}).get("pair_checks") or []) <= 1)


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
    if isinstance(ids, str):  # «R-04» строкой, а не списком — не перебирать буквы
        ids = [x for x in re.split(r"[\s,;]+", ids) if x]
    for x in ids if isinstance(ids, list) else []:
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
    pair["_extra_ev"] = []
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
    # Явное правило документа снимает противоречие (сначала ищем его, потом спорим об исходах):
    # (1) повтор с тем же ключом возвращает сохранённый результат первого запроса — это ответ из памяти, а не новая
    #     проверка: шаги логики к нему не применяются, двух исходов нет;
    # (2) строка приёмки — пример с конкретным входом: «момент» или «единица», которых в самой строке нет, добавил
    #     сценарий модели, а не документ (дата и время для момента, отображаемые ₸ для единицы — норма приёмки).
    if pair["verdict"] in ("conflict", "undefined") and pair["same_subject"]:
        acc_texts = [_line_text(view, ev) for ev in (ev_a, ev_b) if _in_acceptance(ev, known)]
        if _replay_only(pair["quote_a"], pair["quote_b"]):
            pair.update(verdict="compatible", basis="none", resolved_by="replay")
        elif acc_texts and pair["kind"] == "unit_mismatch" and _display_currency(pair, ev_a, ev_b, known):
            pair.update(verdict="compatible", basis="none", resolved_by="acceptance_units")
        elif (acc_texts and pair["kind"] == "event_conflict"
              and not any(_MOMENT.search(t) for t in acc_texts)):
            pair.update(verdict="compatible", basis="none", resolved_by="acceptance_no_moment")
    if pair["verdict"] == "conflict":
        reason = conflict_gate(pair, ev_a, ev_b, view, known)
        if reason:
            pair["gate"] = reason
            if reason in GATE_DROP:  # разные предметы или условие права — исходы совместимы
                pair.update(verdict="compatible", basis="none")
            else:  # пример, экран, граница без значения — расхождение не доказано цитатами: неопределённость
                pair.update(verdict="undefined", basis="none", kind="ambiguity")
    if pair["verdict"] == "conflict" and pair["kind"] == "status_conflict":
        ex = status_example_evidence(view, pair)
        if ex:
            pair["_extra_ev"] = [ex]
            pair["example_line"] = ex["line"]
        # «Один вход — два кода» держится на цитатах: каждая сторона называет код или значение статуса (или найдена
        # строка примера второго кода). Иначе второй исход вывела модель по соседним местам — не доказанный конфликт.
        elif not all(_CODE.search(q) or _TOKEN.search(q) for q in (pair["quote_a"], pair["quote_b"])):
            pair.update(verdict="undefined", basis="none", kind="ambiguity", gate="no_value")
    return pair


_STATUS_LINE = re.compile(r"^\W*([1-5]\d\d)\.(?:\s|$)")
_TOKEN = re.compile(r"(?<![A-Za-z_])[A-Z][A-Z_]{2,}(?![A-Za-z_])")
STATUS_BLOCK_LINES = 15


def _status_of_line(lines: list[dict], idx: int) -> str | None:
    """Код статуса, в блоке которого стоит строка: ближайшая строка выше вида «200. …» (не дальше 15 строк)."""
    for j in range(idx, max(-1, idx - STATUS_BLOCK_LINES), -1):
        m = _STATUS_LINE.match(_s(lines[j].get("text")))
        if m:
            return m.group(1)
    return None


def status_example_evidence(view: Any, pair: dict) -> dict | None:
    """«Один вход — два кода», где одна сторона — шаг логики без кода («вернуть результат ERROR»), а второй код виден
    только по примеру ответа в блоке другого статуса. Ищем строку примера с тем же значением (ERROR, REJECTED …) в
    блоке статуса, которого нет во второй цитате, — это цитата второго кода. Без неё пара держится на догадке."""
    qa, qb = pair["quote_a"], pair["quote_b"]
    ca, cb = set(_CODE.findall(qa)), set(_CODE.findall(qb))
    if bool(ca) == bool(cb):
        return None
    bare, coded, out_bare = (qb, ca, pair["outcome_b"]) if ca else (qa, cb, pair["outcome_a"])
    tokens = set(_TOKEN.findall(bare))
    if not tokens:
        return None
    hint = set(_CODE.findall(out_bare)) - coded
    lines = _lines(view)
    bare_n = {pair["line_a"], pair["line_b"]}
    for i, x in enumerate(lines):
        text = _s(x.get("text"))
        if x.get("n") in bare_n or not any(re.search(rf"(?<![A-Za-z_]){t}(?![A-Za-z_])", text) for t in tokens):
            continue
        if _STATUS_LINE.match(text):
            continue  # сама строка статуса — не пример
        code = _status_of_line(lines, i)
        if not code or code in coded or (hint and code not in hint):
            continue
        ev = _evidence(view, text, x.get("n"))
        if _found(ev):
            return ev
    return None


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


_REPLAY = re.compile(r"повтор\w*[^.;]{0,60}?(?:с\s+(?:тем|таким)\s+же|с\s+одинаков\w*)[^.;]{0,60}?"
                     r"(?:возвраща\w*|верн\w*|отда\w*|получа\w*)[^.;]{0,30}?(?:результат|ответ)\w*[^.;]{0,20}?"
                     r"(?:перв|исходн|предыдущ|прежн)", re.I)
_REPEAT = re.compile(r"повтор|с\s+тем\s+же|с\s+таким\s+же|дубл", re.I)


def _replay_only(qa: str, qb: str) -> bool:
    """Одна сторона — правило идемпотентности («повторный запрос с тем же ключом возвращает результат первого»),
    другая — проверка, которая о повторе не говорит."""
    return any(_REPLAY.search(x) and not _REPEAT.search(y) for x, y in ((qa, qb), (qb, qa)))


_MONTHS = r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
# Момент или порядок событий в строке приёмки: дата, время, число месяца, «на следующий день», «сразу после».
_MOMENT = re.compile(rf"\d{{1,2}}[:.]\d{{2}}|\d{{1,2}}\s*(?:{_MONTHS})|\d{{1,2}}-?(?:го|е)\b|\d{{4}}-\d{{2}}-\d{{2}}|"
                     r"(?<![а-яё])(?:сразу|немедленно|после|через|следующ\w*|накануне|в\s+тот\s+же|полноч\w*|"
                     r"последн\w*\s+(?:день|дн|минут|секунд|час)|перв\w*\s+(?:день|числ)|"
                     r"за\s+(?:[\wё]+\s+){0,2}(?:час|сутк|сутки|день|дня|дней|недел|месяц|квартал|год))", re.I)


def _in_acceptance(ev: dict, known: dict[str, dict] | None) -> bool:
    """Цитата стоит в строке критериев приёмки (по строкам нарезки, а не по ID, который назвала модель)."""
    if not _found(ev):
        return False
    a, b = _span(ev)
    return any(r.get("kind") == "acceptance" and (r.get("line_start") or 0) <= a
               and b <= (r.get("line_end") or r.get("line_start") or 0) for r in (known or {}).values())


_MINOR_UNIT = re.compile(r"тиын", re.I)
_MAJOR_UNIT = re.compile(r"₸|тенге|(?<![A-Za-z])KZT(?![A-Za-z])", re.I)
# Тиыны — целые: «в тиынах с двумя знаками после точки» или «100.00» в тиынах — это путаница единиц, а не показ.
_DECIMAL = re.compile(r"знак\w*\s+после\s+(?:точки|запятой)|дробн|(?<![\d.,])\d+[.,]\d{2}(?![\d])", re.I)


def _display_currency(pair: dict, ev_a: dict, ev_b: dict, known: dict[str, dict] | None) -> bool:
    """Строка приёмки пишет сумму в тенге, другое место хранит или отдаёт её в тиынах: это единица отображения
    теста, а не расхождение (расхождение периода «за час» ↔ «за сутки» сюда не попадает)."""
    for ev, q, other_q in ((ev_a, pair["quote_a"], pair["quote_b"]), (ev_b, pair["quote_b"], pair["quote_a"])):
        if _in_acceptance(ev, known) and _MAJOR_UNIT.search(q) and not _MINOR_UNIT.search(q) \
                and _MINOR_UNIT.search(other_q) and not _DECIMAL.search(other_q):
            return True
    return False


def _line_text(view: Any, ev: dict) -> str:
    """Полный текст строк, где найдена цитата."""
    a, b = _span(ev)
    return " ".join(_s(x.get("text")) for x in _lines(view) if a <= (x.get("n") or 0) <= b)


def _removes_limit(qa: str, qb: str) -> bool:
    """Одна цитата снимает ограничение, другая его задаёт (без слов снятия)."""
    return any(_LIMIT_REMOVED.search(x) and _LIMIT.search(y) and not _LIMIT_REMOVED.search(y)
               for x, y in ((qa, qb), (qb, qa)))


# ---------------------------------------------------------------- проверка конфликта кодом (№27)
# Конфликт — две цитаты из разных нормативных мест про один предмет (поле, событие, правило) с несовместимым исходом
# на одном входе. Ложные конфликты слабой модели на чистых ТЗ (замер h0, haiku, 20 документов) — каждый из видов ниже:
# пример ответа против правила, условие права против запрета для другого состояния, хранение записи против срока
# действия ключа, текст методики тестирования, «граница» без значения, экран против правила сервера, строка приёмки,
# которая задаёт конец срока «действует N минут».

# Пример тела или ответа: значение в примере зависит от входа примера, а не задаёт правило.
_EXAMPLE = re.compile(r'"[\w.$-]+"\s*:|^\s*[{\[]')
# Право («может», «можно», «вправе») — необходимое, а не достаточное условие: запрет или ошибка для другого состояния
# с ним не спорит (контрпример 7 промпта, в том числе без «если»: «может отказаться в течение 14 дней»).
_RIGHT = re.compile(r"(?<![а-яё])(?:может|могут|можно|вправе|разрешается|разрешено)(?![а-яё])", re.I)
_ALWAYS = re.compile(r"(?<![а-яё])(?:всегда|каждый\s+раз|любой|любом)(?![а-яё])", re.I)
# Запрет или ошибка: «не …», «нельзя», «отклоняется», «отказ», код 4xx.
_REFUSAL = re.compile(r"(?<![а-яё])(?:не|нельзя|запрещ\w*|отклон\w*|отказ\w*|недоступ\w*|ошибк\w*)(?![а-яё])|"
                      r"(?<!\d)4\d\d(?!\d)", re.I)
# Хранение записи и срок действия — разные предметы: «запись хранится 5 лет», «ключ действует 30 дней».
_STORE = re.compile(r"(?<![а-яё])хран(?:ит|ят|ится|ятся|ени|ен)\w*", re.I)
_VALID = re.compile(r"(?<![а-яё])(?:действ(?:ует|уют|ителен|ительн|ия)|истека\w*|истеч\w*)", re.I)
# Значение или слово границы: число, «включительно», «не более», «меньше», «достигнет», «≥» …
_BOUND = re.compile(r"\d|включительно|(?<![а-яё])(?:не\s+)?(?:более|больше|менее|меньше|выше|ниже|позднее|позже|"
                    r"раньше|ранее|дольше|превыша\w*|превыс\w*|достиг\w*|максимум|минимум|предел\w*|лимит\w*|"
                    r"порог\w*)(?![а-яё])|[≥≤<>]", re.I)
# Номер пункта списка в начале цитаты («3. Если …») — не значение.
_ITEM_NO = re.compile(r"^\W*\d{1,2}[.)]\s+")
# Срок действия в строке правила: «действует 15 минут», «в течение 14 дней» (без «включительно» конец срока задаёт
# строка приёмки — это уточнение, а не другой исход).
_DURATION = re.compile(r"(?:действ\w*|в\s+течение)[^.;|]{0,40}?\d+\s*(?:секунд|сек|минут|мин|час|сут|дн|дня|дней|"
                       r"недел|месяц|мес)", re.I)
# Разделы, которые описывают проверку документа или методику тестирования, а не поведение системы.
_NON_NORMATIVE_SECTION = re.compile(r"тестирование\s+требований|методик\w*\s+тестир|история\s+изменени|"
                                    r"согласовани|глоссари", re.I)

# Причины, по которым пара не конфликт, а совместима (разные предметы, условие права, уточнение границы приёмкой).
GATE_DROP = ("right_condition", "storage_vs_validity", "non_normative", "acceptance_duration")
GATE_RU = {
    "right_condition": "одно место задаёт условие права, другое — запрет для другого состояния",
    "storage_vs_validity": "срок хранения записи и срок действия — разные предметы",
    "non_normative": "одна сторона — описание проверки документа, а не правило системы",
    "acceptance_duration": "строка приёмки задаёт конец срока, правило его не уточняет",
    "example_value": "одна сторона — пример с другим входом",
    "ui_display": "одна сторона — показ на экране, а не исход правила",
    "no_value": "у одной стороны нет ни значения, ни слова границы (ни кода, ни статуса)",
    "two_phase": "одна сторона — следствие ответа другой системы, а не ответ на тот же запрос",
    "same_place": "цитаты не найдены в двух разных местах документа",
}


_COND_CODE = re.compile(r"(?<![а-яё])(?:при|после|на)\s+(?:ответ\w*|код\w*|статус\w*)\s+([1-5]\d\d)(?!\d)|"
                        r"(?<![а-яё])(?:если|когда)[^.;]{0,40}?(?:вернул\w*|ответил\w*|получ\w*\s+ответ\w*)\s+([1-5]\d\d)(?!\d)",
                        re.I)


def _cond_codes(q: str) -> set[str]:
    """Коды ответа, которые стоят в цитате условием («при ответе 422», «если АБС вернула 500»), а не исходом."""
    return {a or b for a, b in _COND_CODE.findall(q)}


def _req_of(ev: dict, known: dict[str, dict] | None) -> dict:
    """Требование нарезки, в строки которого попала цитата (по строкам, а не по ID, который назвала модель)."""
    if not _found(ev):
        return {}
    a, b = _span(ev)
    best: dict = {}
    for r in (known or {}).values():
        rs, re_ = r.get("line_start") or 0, r.get("line_end") or r.get("line_start") or 0
        if rs and rs <= a and b <= re_ and (not best or re_ - rs < (best.get("line_end") or 0) - (best.get("line_start") or 0)):
            best = r
    return best


def _section(ev: dict, view: Any) -> str:
    a, _ = _span(ev)
    for x in _lines(view):
        if x.get("n") == a:
            return _s(x.get("section"))
    return _s(ev.get("section"))


def conflict_gate(pair: dict, ev_a: dict, ev_b: dict, view: Any, known: dict[str, dict] | None) -> str:
    """Проверка конфликта кодом: пустая строка — конфликт держится на цитатах; иначе — причина (ключ ``GATE_RU``)."""
    kind, qa, qb = pair["kind"], pair["quote_a"], pair["quote_b"]
    quotes = (qa, qb)
    # Две цитаты из разных мест: обе найдены в документе и не на одних строках.
    if not (_found(ev_a) and _found(ev_b)) or _overlap(ev_a, ev_b):
        return "same_place"
    sides = [(ev, q, _req_of(ev, known) or (known or {}).get(rid, {})) for ev, q, rid in
             ((ev_a, qa, pair["a"]), (ev_b, qb, pair["b"]))]
    # Нормативные места: методика тестирования и согласование документа поведение системы не задают.
    for ev, _q, r in sides:
        if r.get("kind") != "acceptance" and _NON_NORMATIVE_SECTION.search(_section(ev, view) or r.get("section") or ""):
            return "non_normative"
    # Один предмет: хранение записи и срок действия ключа (кода, ссылки) — разные величины.
    if kind in ("event_conflict", "unit_mismatch", "boundary_conflict") and any(
            _STORE.search(x) and not _STORE.search(y) and _VALID.search(y) for x, y in ((qa, qb), (qb, qa))):
        return "storage_vs_validity"
    # Несовместимый исход: право с условием («может отказаться в течение 14 дней») не спорит с запретом или ошибкой
    # для другого состояния. Право с пределом («можно не более трёх раз») против снятия предела — конфликт.
    if kind in ("event_conflict", "status_conflict") and pair["basis"] != "limit_removed" and not any(
            _LIMIT_REMOVED.search(q) or _ALWAYS.search(q) for q in quotes) and any(
            _RIGHT.search(x) and not _LIMIT.search(x) and not _RIGHT.search(y) and _REFUSAL.search(y)
            for x, y in ((qa, qb), (qb, qa))):
        return "right_condition"
    # Два шага процесса: в одной цитате код ответа — условие («при ответе 422 операция получает статус REJECTED»),
    # а не исход запроса; другая цитата — ответ на запрос. Это следствие ответа, а не второй исход того же входа.
    if kind == "status_conflict" and any(_CODE.search(q) and not (set(_CODE.findall(q)) - _cond_codes(q)) for q in quotes):
        return "two_phase"
    # Граница срока: строка приёмки с конкретным временем против «действует N минут» без «включительно».
    if kind == "boundary_conflict":
        for (ev, q, r), (_ev2, q2, _r2) in ((sides[0], sides[1]), (sides[1], sides[0])):
            if _in_acceptance(ev, known) and _DURATION.search(q2) and not re.search(r"включительно", q2, re.I):
                return "acceptance_duration"
    # Пример: значение примера (дата, сумма) зависит от его входа; коды и форматы примера сверяет status/unit.
    if kind in ("event_conflict", "boundary_conflict") and any(_EXAMPLE.search(q) for q in quotes):
        return "example_value"
    # Экран показывает (таймер, подпись), правило сервера решает: момент показа — не второй исход правила.
    if kind == "event_conflict" and any(r.get("kind") == "ui" for _ev, _q, r in sides):
        return "ui_display"
    # Граница — значение у обеих сторон: без числа и без слова границы расхождение вывела модель, а не документ.
    if kind == "boundary_conflict" and not all(_BOUND.search(_ITEM_NO.sub("", q)) for q in quotes):
        return "no_value"
    return ""


# Виды требований, конфликт с которыми не блокирует сам по себе: цель — намерение, а не правило;
# нефункциональное требование о сроке редко противоречит правилу поведения напрямую.
SOFT_KINDS = ("goal", "nonfunctional")
SCHEMA_KINDS = ("architecture", "process")
MAJOR_CONFLICT_KINDS = ("unit_mismatch",)


# ---------------------------------------------------------------- тексты для читателя

MAX_TITLE_WORDS = 12  # рубрика понятности WAVE3: заголовок до 12 слов
# Место без номера пункта в документе называем по виду требования и строке.
_KIND_PLACE = {"goal": "цель", "architecture": "схема архитектуры", "process": "описание процесса",
               "ui": "описание экрана", "nonfunctional": "нефункциональное требование", "data": "требования к данным",
               "integration": "описание интеграции", "api": "описание API", "acceptance": "критерий приёмки",
               "constraint": "особое правило API", "functional": "требование"}
_RID = re.compile(r"\bR-\d{1,3}\b")


def place_label(rid: str, line: int | None, known: dict[str, dict] | None) -> str:
    """Как назвать место читателю: номер пункта документа («Ф-3», «Статус 400»), иначе вид и строка
    («схема архитектуры, строка 26»). Внутренние ID нарезки (R-07) читателю ничего не говорят."""
    r = (known or {}).get(rid) or {}
    src = _s(r.get("source_id"))
    if src and len(src) <= 40:
        src = re.sub(r"^Критерии при[её]мки", "критерий приёмки", src)
        return src
    n = line or r.get("line_start") or 0
    what = _KIND_PLACE.get(_s(r.get("kind")), "")
    if what and n:
        return f"{what}, строка {n}"
    return f"строка {n}" if n else (rid or "место документа")


_BARE_ID = re.compile(r"[A-ZА-ЯЁ]{1,4}-\d+(?:\.\d+)?")


def _quoted(label: str) -> str:
    """Короткий номер пункта («Ф-3») — как есть, составное название места — в кавычках: так оно читается
    в любом падеже («как в «Статус 400»», «по-разному решают Ф-2 и «критерий приёмки, строка 2»»)."""
    return label if _BARE_ID.fullmatch(label) else f"«{label}»"


def _humanizer(known: dict[str, dict] | None, labels: dict[str, str]):
    """Замена внутренних ID нарезки в тексте модели номерами пунктов документа."""
    def sub(m: re.Match) -> str:
        rid = m.group(0)
        return labels.get(rid) or _quoted(place_label(rid, None, known))

    def human(text: Any) -> str:
        if not text:
            return ""
        t = _RID.sub(sub, _s(text))
        return re.sub(r"(?<![A-Za-z])L0*(\d{1,4})\b", r"строка \1", t)  # «L038» — внутренняя запись строки

    return human


def _phrase(s: str) -> str:
    """Фраза для вставки внутрь предложения: без завершающей точки и с малой буквы, если это не аббревиатура."""
    s = re.sub(r"[\s.;,]+$", "", _s(s))
    if len(s) > 1 and s[0].isupper() and s[1].islower() and not re.match(r"[A-ZА-ЯЁ][а-яё]?-\d", s):
        s = s[0].lower() + s[1:]
    return s


def _sentence(s: str) -> str:
    """Законченное предложение: с большой буквы и одной точкой в конце (без «..»)."""
    s = re.sub(r"\s+", " ", _s(s)).strip()
    if not s:
        return ""
    s = re.sub(r"\.{2,}$", ".", s)
    if s[-1] not in ".?!»)":
        s += "."
    return _cap(s)


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def _words(s: str) -> int:
    return len(_s(s).split())


def _short(s: str, n: int) -> str:
    w = _s(s).split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


_LINE_REF = re.compile(r"\s*\((?:L\d{1,4}|строк[аи]?\s*\d|стр\.?\s*\d)[^)]*\)|\s*\(L\d{1,4}\s*(?:и|,|–|-)\s*L?\d{1,4}\)")


def _clean_title(t: str) -> str:
    """Заголовок без номеров строк в скобках («(L038)», «(строки 39–40)»): место показывает цитата."""
    t = _LINE_REF.sub("", _s(t))
    t = re.sub(r"\bL0*(\d{1,4})\b", r"строка \1", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,;")


def _fit_title(t: str, n: int = MAX_TITLE_WORDS) -> str:
    """Заголовок до n слов: лишнее отрезается по слову, без «…» (суть — в тексте проблемы)."""
    w = _s(t).split()
    return " ".join(w[:n]).rstrip(" ,;:—-") if len(w) > n else _s(t)


_IMPERATIVE = re.compile(r"^(?:добавить|указать|зафиксировать|определить|уточнить|описать|задать|выбрать|"
                         r"записать|установить)(?:\s+(?:правило|явно|одно правило|в документе))?\s*[:,—-]?\s*", re.I)


def question_from_recommendation(rec: str) -> str:
    """Рекомендация с вариантами («… сразу или не отправляется до следующего месяца») — готовый вопрос владельцу:
    «Push отправляется сразу или не отправляется до следующего месяца?». Без «или» вопроса из неё нет."""
    r = _s(rec).strip().rstrip(".")
    if not _has_variants(r):
        return ""
    r = _IMPERATIVE.sub("", r).strip()
    if len(r.split()) < 4:
        return ""
    return _cap(r) + "?"


def _has_variants(q: str) -> bool:
    """Вопрос уже предлагает варианты («… или …»)."""
    return bool(re.search(r"(?<![а-яё])или(?![а-яё])", q or "", re.I))


def _check_order(pair: dict, kind: str) -> bool:
    """Две заданные проверки для двух разных условий, а запрос нарушает обе: вопрос порядка проверок.
    Молчание одного места о правиле другого (``incomplete``) — не порядок проверок, а неполнота."""
    return pair["verdict"] == "undefined" and not pair["one_condition"] and kind == "ambiguity"


def pair_to_candidate(pair: dict, known: dict[str, dict] | None = None) -> dict | None:
    """conflict → critical с двумя цитатами в разных местах; undefined → major."""
    if not pair["same_subject"] or pair["verdict"] == "compatible":
        return None
    ev_a, ev_b = pair["_ev"]
    evidence = [e for e in (ev_a, ev_b) if e.get("quote")] + list(pair.get("_extra_ev") or [])
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
        # «Один вход — два кода» держится на цитатах: каждая сторона называет код или значение статуса (или найдена
        # строка примера второго кода). Иначе второй исход — догадка модели по соседним примерам — major.
        if kind == "status_conflict" and not pair.get("example_line") and not all(
                _CODE.search(q) or _TOKEN.search(q) for q in (pair["quote_a"], pair["quote_b"])):
            severity = "major"
    else:  # undefined
        # Строка приёмки сверяется только на противоречие (шаг 2б); её неполноту проверяет линза тестировщика.
        if any((known or {}).get(x, {}).get("kind") == "acceptance" for x in (pair["a"], pair["b"])):
            return None
        if kind in ("event_conflict", "status_conflict", "boundary_conflict", "contradiction"):
            kind = "ambiguity"
        # Два разных условия в одном запросе (неверный параметр и неподходящее состояние) — вопрос порядка
        # проверок: реализации разойдутся только кодом ошибки, основной процесс не страдает — minor.
        # Неопределённость — не конфликт: ни одно место не даёт исхода, который спорит с другим (молчание, два прочтения,
        # пример, экран). На чистых ТЗ это догадки модели о сценарии (замер h0: 26 major из 58), поэтому minor;
        # счётчик и судья видят её, а major делают линзы, если дефект подтверждён ими.
        severity = "minor"
    criterion = "unambiguous" if kind in ("boundary_conflict", "unit_mismatch", "ambiguity") else "set_consistent"
    if pair["verdict"] == "undefined" and kind == "incomplete":
        criterion = "set_complete"
    ids = [x for x in (pair["a"], pair["b"]) if x]
    a_lbl = place_label(pair["a"], pair["line_a"], known)
    b_lbl = place_label(pair["b"], pair["line_b"], known)
    if a_lbl == b_lbl:  # два пункта одного раздела без своих номеров — различаем по строке
        a_lbl, b_lbl = f"{a_lbl} (строка {pair['line_a']})", f"{b_lbl} (строка {pair['line_b']})"
    qa_, qb_ = _quoted(a_lbl), _quoted(b_lbl)
    human = _humanizer(known, {pair["a"]: qa_, pair["b"]: qb_})
    subject = _phrase(human(pair["subject"]))
    oa, ob = _phrase(human(pair["outcome_a"])), _phrase(human(pair["outcome_b"]))
    model_title = _clean_title(human(pair["title"]))
    if pair["verdict"] == "conflict":
        fallback = f"{qa_} и {qb_} дают разный результат: {_short(subject, 8)}"
        problem = (f"{_cap(qa_)} и {qb_} по-разному решают один случай — {subject}. "
                   f"Ни одно из мест не объявлено исключением из другого.")
    elif _check_order(pair, kind):
        fallback = f"Порядок проверок не задан: {qa_} или {qb_} — {_short(subject, 6)}"
        problem = (f"{_cap(qa_)} и {qb_} задают разные проверки, а один запрос может нарушить обе — {subject}. "
                   f"Порядок проверок не задан, поэтому неясно, какой результат вернуть.")
    else:
        fallback = f"{qa_} и {qb_} не определяют результат: {_short(subject, 8)}"
        problem = (f"{_cap(qa_)} и {qb_} касаются одного случая — {subject}, — но результат по ним "
                   f"не определить: документ не говорит, что делать.")
    title = model_title if model_title and _words(model_title) <= MAX_TITLE_WORDS else _fit_title(fallback)
    scenario = _sentence(human(pair["scenario"]))
    if oa and ob:
        scenario = " ".join(x for x in (scenario, f"{_cap(a_lbl)}: {oa}.", f"{_cap(b_lbl)}: {ob}.") if x)
    impact = _sentence(human(pair["impact"])) or (
        "Разработчик и тестировщик выберут разные правила: реализация и приёмка разойдутся, клиент получит "
        "результат, который противоречит одному из пунктов.")
    rec = _sentence(human(pair["recommendation"])) or (
        f"Выбрать одно правило для этого случая и записать его в {qa_} и {qb_} одинаково.")
    question = _sentence(human(pair["question"]))
    if pair["verdict"] == "conflict" and oa and ob and not _has_variants(question):
        # Вопрос владельцу с двумя вариантами: какой из двух исходов сценария верный.
        # Предмет уже назван в заголовке — вопрос только о выборе между двумя исходами.
        question = f"Что верно: «{oa}» (как в {qa_}) или «{ob}» (как в {qb_})?"
    elif pair["verdict"] == "undefined" and _check_order(pair, kind) and oa and ob and not _has_variants(question):
        question = f"Какая проверка идёт первой: по {qa_} («{oa}») или по {qb_} («{ob}»)?"
    if not question:
        question = question_from_recommendation(rec) or f"Какое правило верно в этом случае: {_short(subject, 10)}?"
    return {
        "title": title, "kind": kind, "criterion": criterion, "severity": severity,
        "requirement_ids": ids, "evidence": [{k: v for k, v in e.items()} for e in evidence],
        "problem": problem, "scenario": scenario, "impact": impact, "recommendation": rec,
        "rewrite": "", "question": question, "blocks": "both",
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
        if not isinstance(t, dict):
            continue
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
    # Бизнес-имя компонента и его техническое имя (контроллер, путь, поле) — норма шаблона, а не разночтение:
    # major только если разных названий словами (не идентификаторов) хотя бы два.
    if sev == "major" and len({_norm(t["term"]) for t in terms if _CYR.search(t["term"])}) < 2:
        sev = "minor"
    # Разные системы и участники («банк», «приложение», «сервис переводов» и «сервис QR-кодов») — не одно понятие
    # под разными именами. Major — только если хотя бы два русских названия делят значимую основу
    # («сервис настроек» / «хранилище настроек», «держатель карты» / «владелец карты»).
    if sev == "major" and not _names_share_stem([t["term"] for t in terms]):
        sev = "minor"
    return {"concept": _s(g.get("concept")), "terms": terms, "problem": _s(g.get("problem")), "severity": sev}


_CYR = re.compile(r"[а-яё]", re.I)
# Родовые слова названий компонентов и участников: общая основа «сервис» или «банк» не делает две системы одной.
_GENERIC_ROOTS = ("серв", "систем", "модул", "компонент", "банк", "приложен", "контрол", "платформ", "интерфейс",
                  "метод")


def _generic(stem: str) -> bool:
    return any(stem.startswith(r) or r.startswith(stem) for r in _GENERIC_ROOTS)


# Роли людей: «клиент» и «держатель счёта» без общей основы — всё равно возможная путаница прав (кто вправе и кого
# проверяют), это major по шкале глоссария.
_PERSON = re.compile(r"(?<![а-яё])(?:клиент|держател|владел|пользовател|заявител|заёмщик|заемщик|получател|"
                     r"отправител|плательщик|доверенн|представител|вкладчик|абонент|сотрудник|оператор)", re.I)


def _names_share_stem(terms: list[str]) -> bool:
    """Два русских названия делят значимую основу или оба называют роль человека."""
    cyr = [t for t in terms if _CYR.search(t)]
    if sum(1 for t in cyr if _PERSON.search(t)) >= 2:
        return True
    stems = [{st for w in _WORD.findall(t) if len(w) >= 4 and _CYR.search(w) and not _generic(st := _stem(w))}
             for t in cyr]
    return any(stems[i] & stems[j] for i in range(len(stems)) for j in range(i + 1, len(stems)))


def glossary_to_candidate(g: dict) -> dict | None:
    if g["severity"] == "none":
        return None
    found = [t for t in g["terms"] if t["verified"] != "missing"]
    if len(found) < 2:
        return None
    names = ", ".join(f"«{t['term']}» (строка {t['line']})" for t in found)
    first = found[0]["term"]
    severity = "major" if g["severity"] == "major" else "minor"
    problem = g["problem"] or "Одно понятие названо в документе по-разному, и по тексту не понять, одно ли это."
    terms = [t["term"] for t in found]
    person = sum(1 for t in terms if _PERSON.search(t)) >= 2
    what = "участника" if person else ("компонента" if any(_generic(_stem(w)) for t in terms for w in _WORD.findall(t)
                                                          if _CYR.search(w)) else "понятия")
    if severity == "major":
        impact = ("Права проверят не у того человека: разработчик проверит одно лицо, тестировщик — другое, клиент "
                  "получит отказ или чужой доступ." if person else
                  "Разработчики сделают лишний компонент или связь, тестировщик не поймёт, какой компонент проверять.")
    else:
        impact = "Документ труднее читать и искать по нему; растёт риск ошибки при изменениях."
    return {
        "title": _names_title(f"Разные названия {what}:", terms),
        "kind": "terminology", "criterion": "conforming", "severity": severity, "requirement_ids": [],
        "evidence": [{"quote": t["term"], "line": t["line"], "verified": t["verified"]} for t in found[:4]],
        "problem": f"{problem} Названия: {names}.",
        "scenario": "",
        "impact": impact,
        "recommendation": (f"Выбрать одно название (например, «{first}»), заменить им остальные во всех частях "
                           f"документа и добавить его в глоссарий с определением."),
        "rewrite": "",
        "question": (f"«{terms[0]}» и «{terms[1]}» — одно лицо или разные? Если разные, кому дано право и чью "
                     f"сессию проверять?") if person and len(terms) >= 2 else _names_question(terms),
        "blocks": "development" if severity == "major" else "none",
        "source": SOURCE, "origin": "glossary", "glossary_ids": [g["id"]] if g.get("id") else [],
    }


def _names_title(head: str, names: list[str], n: int = MAX_TITLE_WORDS) -> str:
    """«Разные названия компонента: «A», «B» и др.» — столько названий, сколько помещается в n слов (не меньше двух)."""
    shown: list[str] = []
    for name in names:
        cand = shown + [name]
        if len(shown) >= 2 and _words(head) + sum(_words(x) for x in cand) + (2 if len(cand) < len(names) else 0) > n:
            break
        shown = cand
    rest = len(names) > len(shown)
    return f"{head} " + ", ".join(f"«{x}»" for x in shown) + (" и др." if rest else "")


def _names_question(names: list[str]) -> str:
    uniq = list(dict.fromkeys(names))[:3]
    if len(uniq) < 2:
        return ""
    return "Какое название оставить во всём документе: " + ", ".join(f"«{x}»" for x in uniq[:-1]) + \
        f" или «{uniq[-1]}»?"


def merge_glossary(cands: list[dict]) -> list[dict]:
    """Понятия major, названия которых стоят в двух одних и тех же строках (например, компоненты в описании
    архитектуры и последовательности), — одно замечание: это одно место документа, исправляется одной правкой."""
    out: list[dict] = []
    for c in cands:
        lines = {e["line"] for e in c["evidence"]}
        host = next((o for o in out if len(lines & {e["line"] for e in o["evidence"]}) >= 2), None)
        if host is None:
            out.append(c)
            continue
        host["evidence"].extend(e for e in c["evidence"]
                                if not any(e["line"] == h["line"] and e["quote"] == h["quote"] for h in host["evidence"]))
        host["glossary_ids"] = host.get("glossary_ids", []) + [x for x in c.get("glossary_ids", [])
                                                               if x not in host.get("glossary_ids", [])]
        host.setdefault("merged_titles", []).append(c["title"])
        host.setdefault("_groups", [[e["quote"] for e in host["evidence"]][:3]]).append(
            [e["quote"] for e in c["evidence"]][:3])
    for c in out:
        groups = c.pop("_groups", None)
        if c.get("merged_titles"):
            c["problem"] += " Также: " + "; ".join(c["merged_titles"]) + "."
            # в заголовке — сначала по одному названию каждого понятия, чтобы были видны все
            firsts = [g[0] for g in groups or [] if g]
            names = list(dict.fromkeys(firsts + [e["quote"] for e in c["evidence"]]))
            c["title"] = _names_title("Компоненты и участники названы по-разному:", names)
            parts = ["«" + "» или «".join(list(dict.fromkeys(g))[:2]) + "»" for g in groups or [] if len(set(g)) >= 2]
            c["question"] = ("Какое одно название оставить для каждого: " + "; ".join(parts) + "?") if parts else \
                _names_question(names)
    return out


def minor_glossary_candidate(entries: list[dict]) -> dict | None:
    """Все синонимы без влияния на реализацию — одно замечание minor на документ."""
    found = [(g, [t for t in g["terms"] if t["verified"] != "missing"]) for g in entries if g["severity"] == "minor"]
    found = [(g, ts) for g, ts in found if len(ts) >= 2]
    if not found:
        return None
    evidence, parts = [], []
    for g, ts in found:
        parts.append(f"{g['concept']}: " + ", ".join(f"«{t['term']}» (строка {t['line']})" for t in ts[:4]))
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
                if isinstance(e, dict) and _s(e.get("quote"))]
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
    if not cand["question"] and not cand["rewrite"]:
        cand["question"] = question_from_recommendation(cand["recommendation"])
    # critical без сценария, последствий или блокировки по шкале не бывает.
    if cand["severity"] == "critical" and (not cand["scenario"] or not cand["impact"] or cand["blocks"] == "none"):
        cand["severity"] = "major"
    if cand["severity"] == "critical" and cand["blocks"] == "none":
        cand["blocks"] = "both"
    # «Обещано, но не описано»: если все названные в цитатах методы и поля описаны в заголовках документа,
    # обещанное на месте — это не critical (модель приняла соседний процесс за обещанную операцию).
    # Если ни одна цитируемая строка не обещает действие словами (экран с элементом, перечень систем, пример ответа),
    # обещания нет, есть только догадка модели — тоже не critical.
    promised = (_promises(" ".join(_s(e.get("quote")) for e in evidence))
                or bool(_PROMISE_SUBJ.search(" ".join(_cited_texts(evidence, view)))))
    if cand["severity"] == "critical" and cand["kind"] == "missing_element" and (
            _all_named_described(evidence, view) or not promised):
        cand["severity"] = "major"
    cand["severity"] = model_severity(cand, promised, known)
    return cand


# Цель с конкретным моментом, сроком или результатом: «в момент покупки», «сразу», «в течение 5 минут».
_GOAL_MOMENT = re.compile(r"(?<![а-яё])(?:в\s+момент|сразу|мгновенн\w*|немедленн\w*|в\s+реальном\s+времени|"
                          r"не\s+позднее|в\s+течение\s+\d|за\s+\d|\d+\s*(?:секунд|сек|минут|мин|час))", re.I)
# Виды дефектов набора, у которых модель может поставить major без проверки кодом нет: такой major — мнение одного
# ревьюера о сценарии или схеме (полнота набора, расхождение схем, дубль), на чистых ТЗ — ложная тревога
# (замер h0, haiku: 24 major из 58 — кандидаты модели). Счётчик и судья видят их и как minor.
MODEL_MAJOR_KINDS = ("missing_element", "terminology")


def model_severity(cand: dict, promised: bool, known: dict[str, dict] | None) -> str:
    """Серьёзность кандидата модели после проверки кодом: major остаётся только у обещанного, но не описанного
    (обещание есть в цитатах) и у цели, которая называет конкретный момент или срок; остальное — minor."""
    sev = cand["severity"]
    if sev == "minor":
        return sev
    if sev == "critical" and cand["kind"] != "missing_element":  # по шкале промпта critical — только обещанное
        sev = "major"
    goal = [e for e in cand["evidence"] if _req_of(e, known).get("kind") == "goal"]
    if goal:  # цель против требований (п. 1 шага 5): major — только если цель называет момент, срок или результат
        return sev if any(_GOAL_MOMENT.search(_s(e.get("quote"))) for e in goal) else "minor"
    if cand["kind"] == "missing_element":
        return sev if promised else "minor"
    return sev if cand["kind"] in MODEL_MAJOR_KINDS else "minor"


_IDENT = re.compile(r"\b[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+\b|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
# Глаголы обещанного действия (основы, с начала слова): читает, получает, отдаёт, возвращает, сохраняет, показывает…
_VERB = (r"(?<![а-яё])(?:чита|получа|получ|отда|возвра|верн|сохран|показ|отобра|вызыв|отправ|запраш|"
         r"переда|хран|меня|измен|удал|созда|отмен|отзыв|включ|выключ|рассчит|подключ|оформл|"
         r"выполн|формир|загруж|обновл|блокир|разблокир|приходит|присыла)"
         # существительные-деятели и места — не обещание действия: «получатель», «отправитель», «хранилище»
         r"(?![а-яё]*тел(?:ь|я|ю|ем|е|и|ей|ям|ями|ях)(?![а-яё])|[а-яё]*илищ)")
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


def _covered_by_promise(pc: dict, model_cands: list[dict]) -> bool:
    """Кандидат пары, все найденные цитаты которого стоят на строках critical-кандидата «обещано, но не описано»
    (±1 строка): «назначение метода: чтение или сохранение» — тот же дефект, что «чтение обещано, но не описано»."""
    mine = [e for e in pc["evidence"] if _found(e)]
    return bool(mine) and any(
        mc["severity"] == "critical" and mc["kind"] == "missing_element"
        and all(any(_overlap(e, me, 1) for me in mc["evidence"] if _found(me)) for e in mine)
        for mc in model_cands)


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


MAX_NOTE_CHARS = 120


def mark_trace_conflicts(trace: list[dict], pairs: list[dict], known: dict[str, dict]) -> None:
    """Строка матрицы покрытия знает о противоречии своего требования: ``conflicts_with`` — ID второй стороны,
    в ``note`` первым — «противоречит Ф-4» / «противоречит критерию приёмки, строка 2». Так матрица ведёт к дефекту,
    а не только к пропущенной приёмке. Меняет список на месте."""
    rows = {t["requirement_id"]: t for t in trace or []}
    for p in pairs or []:
        if p.get("verdict") != "conflict" or not p.get("same_subject"):
            continue
        for me, other, line in ((p["a"], p["b"], p["line_b"]), (p["b"], p["a"], p["line_a"])):
            t = rows.get(me)
            if not t or not other or other == me:
                continue
            if other in t.setdefault("conflicts_with", []):
                continue
            t["conflicts_with"].append(other)
            mark = f"противоречие: {place_label(other, line, known)}"
            # своя пометка модели о том же противоречии (часто с внутренним ID) — заменяется нашей
            old = "; ".join(x.strip() for x in _s(t.get("note")).split(";")
                            if x.strip() and "противореч" not in x.lower())
            if old in ("нет критерия приёмки", "трассировка не построена") and (known.get(other) or {}).get(
                    "kind") == "acceptance":
                old = ""  # строка приёмки к правилу есть — она ему противоречит
            note = f"{mark}; {old}" if old and mark not in old else (old if mark in old else mark)
            t["note"] = note[:MAX_NOTE_CHARS]


def postprocess(data: dict, view: Any, requirements: list[dict]) -> dict:
    """Ответ модели → выход этапа по CONTRACT 2.3/2.5 (чистая функция, тестируется на записанных ответах)."""
    data = data if isinstance(data, dict) else {}
    # Схему держат провайдер и llm.py; без неё (повтор из чужого кэша, mock) элемент не того типа пропускается,
    # а не роняет этап (и с ним все противоречия набора).
    data = {k: [x for x in v if isinstance(x, dict)] if isinstance(v, list) else [] for k, v in data.items()
            if k in SCHEMA["properties"]}
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
    model_cands = []
    for raw in (data.get("candidates") or [])[:MAX_MODEL_CANDIDATES]:
        c = normalize_candidate(raw, view, known, requirements)
        if c and not _duplicates_pair(c, pair_cands):
            model_cands.append(c)
    # Пара, которая повторяет critical «обещано, но не описано» (те же строки), — тот же дефект в другой форме:
    # остаётся одно замечание, «обещано, но не описано».
    pair_cands = [c for c in pair_cands if not _covered_by_promise(c, model_cands)]
    candidates.extend(pair_cands)

    glossary = [g for g in (normalize_glossary(g, view) for g in (data.get("glossary") or [])[:MAX_GLOSSARY]) if g]
    for i, g in enumerate(glossary, 1):
        g["id"] = f"G-{i:02d}"
    candidates.extend(merge_glossary([c for c in (glossary_to_candidate(g) for g in glossary
                                                  if g["severity"] == "major") if c]))
    c = minor_glossary_candidate(glossary)
    if c:
        candidates.append(c)

    candidates.extend(model_cands)

    trace = normalize_trace(data.get("trace") or [], requirements)
    mark_trace_conflicts(trace, pairs, known)

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
