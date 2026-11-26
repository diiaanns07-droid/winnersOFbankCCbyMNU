"""Резервные семантические этапы (пока не влиты №05, №06): промпты, схемы ответа, разбор.

Схемы строгие (все поля обязательны, ``additionalProperties: false``) — совместимы со structured outputs
Anthropic и с ``responseJsonSchema`` Gemini. Модель отвечает подсказками ``{block_id, quote}``;
координаты и подтверждение цитат считает проверка доказательств.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ...contracts import FINDING_KINDS, INDIVIDUAL_CRITERIA, SET_CRITERIA, AskError, SEVERITIES


def S(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": STR}
QUOTE = S({"block_id": STR, "quote": STR})
QUOTES = {"type": "array", "items": QUOTE}
CAUSE = S({"object": STR, "condition": STR, "outcomes": STRS})
ISSUE_FIELDS = {
    "kind": {"type": "string", "enum": list(FINDING_KINDS)},
    "criterion": {"type": "string", "enum": list(INDIVIDUAL_CRITERIA + SET_CRITERIA)},
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "title": STR, "impact": STR, "blocked_decision": STR, "recommendation": STR,
    "quotes": QUOTES, "cause": CAUSE,
}

INDIVIDUAL_SCHEMA = S({"requirements": {"type": "array", "items": S({
    "req_id": STR,
    "checks": {"type": "array", "items": S({
        "criterion": {"type": "string", "enum": list(INDIVIDUAL_CRITERIA)},
        "status": {"type": "string", "enum": ["pass", "issue", "unknown", "na"]},
        "reason": STR,
    })},
    "issues": {"type": "array", "items": S(dict(ISSUE_FIELDS))},
})}})

CROSS_SCHEMA = S({
    "conflicts": {"type": "array", "items": S({
        "title": STR, "severity": {"type": "string", "enum": list(SEVERITIES)},
        "criterion": {"type": "string", "enum": list(SET_CRITERIA + ("correct", "verifiable"))},
        "impact": STR, "blocked_decision": STR, "recommendation": STR, "req_ids": STRS,
        "input": STR, "outcome_a": STR, "outcome_b": STR, "quote_a": QUOTE, "quote_b": QUOTE, "cause": CAUSE,
    })},
    "issues": {"type": "array", "items": S({**ISSUE_FIELDS, "req_ids": STRS, "inspected_block_ids": STRS})},
    "coverage": {"type": "array", "items": S({
        "req_id": STR, "obligation": STR, "acceptance_ids": STRS,
        "status": {"type": "string", "enum": ["covered", "partial", "conflict", "uncovered", "unknown"]},
        "explanation": STR, "quotes": QUOTES,
    })},
    "facts": {"type": "array", "items": S({
        "subject": STR, "field": STR, "value": STR, "unit": STR, "req_ids": STRS, "quotes": QUOTES,
    })},
})

MEANING_SCHEMA = S({"verdicts": {"type": "array", "items": S({
    "cid": STR,
    "verdict": {"type": "string", "enum": ["confirmed", "rejected", "uncertain"]},
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "reason": STR,
})}})

CRITERIA_TEXT = """Критерии отдельного требования (ISO/IEC/IEEE 29148:2018, п. 5.2.5):
- necessary — без него будет пробел, не дубль;
- appropriate — говорит «что», а не «как», без лишних решений реализации;
- unambiguous — одно толкование: термины, единицы, часовые пояса, события определены;
- complete — есть субъект, условие, действие, ограничения, обработка ошибок и границы;
- singular — одно обязательство в пункте;
- feasible — реализуемо при описанной архитектуре и данных;
- verifiable — выполнение можно объективно доказать тестом, анализом или инспекцией;
- correct — соответствует предметной области и не противоречит другим пунктам и критериям приёмки;
- conforming — есть ID, модальность, единая терминология."""

TASK_INDIVIDUAL = f"""Проверь каждое требование из входных данных по всем девяти критериям. Учитывай весь документ: части и разделы, на которые требование ссылается, видны в контексте.

{CRITERIA_TEXT}

Для каждого требования верни ровно 9 проверок (по одной на критерий). status: pass — критерий выполнен; issue — нарушен (тогда в issues должно быть замечание); unknown — нельзя решить по тексту; na — критерий неприменим (например, к таблице с примером ответа). reason: для pass — до 12 слов, для остальных — конкретная причина.

issues — только реальные дефекты этого требования. Для каждого: kind, criterion, severity, title (конкретно: что и где), impact (бизнес-последствие для банка или клиента), blocked_decision (какое решение разработчика или тестировщика блокируется; пустая строка, если не блокирует), recommendation (как переписать; неизвестные значения — маркером <уточнить: …>), quotes (1–3 дословные цитаты с block_id), cause (object — объект дефекта, condition — условие или сценарий, outcomes — несовместимые или неопределённые исходы).
Не дублируй одно и то же замечание в разных требованиях: укажи его у требования, где дефект возникает. Не выдавай стилистику за существенный дефект."""

TASK_CROSS = """Проверь набор требований целиком (ISO/IEC/IEEE 29148 5.2.6, IEEE 830 4.3): согласованность, полноту, покрытие приёмкой, прослеживаемость. Все части документа видны вместе — ищи связи между ними.

1. conflicts — противоречия. Найди пары мест, которые для ОДНОГО и того же входного сценария дают НЕСОВМЕСТИМЫЕ исходы. «Исполни» каждую строку критериев приёмки только по правилам требований и сравни с ожидаемым результатом; попарно сопоставь правила и ограничения (лимиты, сроки, часовые пояса, коды ответов, типы полей, единицы). Для каждого: input — конкретный сценарий, outcome_a и outcome_b — исходы по месту A и месту B, quote_a и quote_b — дословные цитаты A и B с block_id, req_ids — затронутые требования (id из индекса R-…). Если исходы совместимы при разумном прочтении — это не конфликт.
2. issues — пропуски и дефекты набора: обещанные, но не описанные методы, контракты, поля, ошибки (если данные читаются — есть ли метод чтения; если хранятся — есть ли поле; если событие упомянуто — описано ли оно), неопределённые термины, расхождение терминов, отсутствие прослеживаемости. Для пропуска quotes — места, где пропущенное обещано или требуется, inspected_block_ids — блоки, в которых ты искал и не нашёл.
3. coverage — для каждого обязательства функциональных требований: какие строки критериев приёмки его проверяют (acceptance_ids — id требований-строк приёмки), status covered|partial|conflict|uncovered|unknown, explanation, quotes.
4. facts — нормализованные параметры: границы, единицы, часовые пояса, коды статусов, типы полей, лимиты; value строкой, unit — единица или пустая строка, quotes — откуда взято.

Серьёзность конфликта critical — только если он блокирует решение разработчика или ожидаемый результат теста; тогда impact и blocked_decision обязательны и конкретны."""

TASK_MEANING = """Ты — независимый критик. Для каждого кандидата в замечания проверь по документу и приведённым цитатам, что дефект действительно есть и цитаты его доказывают.
verdict: confirmed — дефект реален, цитаты по делу; rejected — ложное срабатывание, общая фраза, дефекта нет или цитаты его не подтверждают; uncertain — для решения нужен ответ аналитика.
severity — откалиброванная серьёзность: critical только если дефект блокирует конкретное решение разработки или тестирования и последствие для бизнеса названо; иначе major или minor.
reason — 1–2 предложения: почему так."""


def _hints(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"block_id": q.get("block_id") or None, "quote": q.get("quote", "")} for q in quotes or [] if q.get("quote")]


def _issue_to_candidate(issue: dict[str, Any], scope: str, req_ids: list[str], stage: str) -> dict[str, Any]:
    c = {
        "scope": scope, "kind": issue["kind"], "criterion": issue["criterion"], "severity": issue["severity"],
        "title": issue["title"], "impact": issue["impact"], "req_ids": req_ids, "hints": _hints(issue.get("quotes")),
        "recommendation": issue.get("recommendation", ""), "blocked_decision": issue.get("blocked_decision", ""),
        "cause": issue.get("cause") or {"object": issue["title"], "condition": "", "outcomes": []},
        "source": "llm", "stage": stage,
    }
    if issue.get("inspected_block_ids"):
        c["inspected_block_ids"] = list(issue["inspected_block_ids"])
    return c


def _req_input(r: dict[str, Any]) -> dict[str, Any]:
    return {"req_id": r["id"], "source_id": r.get("source_id"), "kind": r.get("kind"),
            "section": " / ".join(r.get("section") or []), "block_ids": r["block_ids"], "text": r["text"]}


def review_individual(document: dict[str, Any], requirements: list[dict[str, Any]], ask: Optional[Callable] = None,
                      *, batch_size: int = 12) -> dict[str, Any]:
    out: dict[str, Any] = {"checks": [], "candidates": [], "warnings": [], "failed": {}}
    if ask is None:
        out["warnings"].append("LLM-проверка отдельных требований не выполнялась (модель недоступна или --offline-lint)")
        for r in requirements:
            out["failed"][r["id"]] = "LLM-проверка не выполнялась"
        return out
    known = {r["id"] for r in requirements}
    for n, start in enumerate(range(0, len(requirements), batch_size), 1):
        batch = requirements[start:start + batch_size]
        payload = {"task": TASK_INDIVIDUAL, "input": {"requirements": [_req_input(r) for r in batch]},
                   "context": {"mode": "auto", "block_ids": [b for r in batch for b in r["block_ids"]]}}
        try:
            data = ask(f"individual#{n}", payload, INDIVIDUAL_SCHEMA)
        except AskError as exc:
            for r in batch:
                out["failed"][r["id"]] = f"этап individual#{n}: {exc.kind}: {exc.message}"[:300]
            out["warnings"].append(f"individual#{n}: {exc.kind}")
            if exc.kind == "budget_exhausted":
                for r in requirements[start + batch_size:]:
                    out["failed"][r["id"]] = f"этап individual не запускался: {exc.message}"
                break
            continue
        seen = set()
        for item in data["requirements"]:
            rid = item["req_id"]
            if rid not in known or rid not in {r["id"] for r in batch}:
                out["warnings"].append(f"individual#{n}: модель вернула чужой req_id {rid!r}")
                continue
            seen.add(rid)
            for ch in item["checks"]:
                out["checks"].append({"req_id": rid, "criterion": ch["criterion"], "status": ch["status"],
                                      "reason": ch["reason"], "source": "llm"})
            for issue in item["issues"]:
                out["candidates"].append(_issue_to_candidate(issue, "requirement", [rid], "individual"))
        for r in batch:
            if r["id"] not in seen:
                out["failed"][r["id"]] = f"этап individual#{n}: модель не вернула результат по требованию"
    return out


def review_set(document: dict[str, Any], requirements: list[dict[str, Any]], ask: Optional[Callable] = None, *,
               fact_hints: Optional[list] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"facts": [], "coverage": [], "candidates": [], "warnings": []}
    if ask is None:
        out["warnings"].append("LLM-проверка набора не выполнялась (модель недоступна или --offline-lint)")
        out["failed"] = "LLM-проверка набора не выполнялась"
        return out
    payload = {"task": TASK_CROSS,
               "input": {"requirements": [_req_input(r) for r in requirements], "fact_hints": fact_hints or []},
               "context": {"mode": "auto", "block_ids": [b for r in requirements for b in r["block_ids"]]}}
    data = ask("cross", payload, CROSS_SCHEMA)  # AskError обрабатывает движок
    known = {r["id"] for r in requirements}
    for c in data["conflicts"]:
        req_ids = [x for x in c["req_ids"] if x in known]
        out["candidates"].append({
            "scope": "set", "kind": "conflict", "criterion": c["criterion"], "severity": c["severity"],
            "title": c["title"], "impact": c["impact"], "req_ids": req_ids,
            "hints": _hints([c["quote_a"], c["quote_b"]]), "recommendation": c["recommendation"],
            "blocked_decision": c["blocked_decision"], "cause": c["cause"],
            "witness": {"input": c["input"], "outcome_a": c["outcome_a"], "outcome_b": c["outcome_b"],
                        "hint_a": _hints([c["quote_a"]])[0] if c["quote_a"].get("quote") else {"quote": ""},
                        "hint_b": _hints([c["quote_b"]])[0] if c["quote_b"].get("quote") else {"quote": ""}},
            "source": "llm", "stage": "cross"})
    for i in data["issues"]:
        req_ids = [x for x in i["req_ids"] if x in known]
        out["candidates"].append(_issue_to_candidate(i, "set" if len(req_ids) != 1 else "requirement", req_ids, "cross"))
    for cv in data["coverage"]:
        if cv["req_id"] not in known:
            continue
        out["coverage"].append({"req_id": cv["req_id"], "obligation": cv["obligation"],
                                "acceptance_ids": [x for x in cv["acceptance_ids"] if x in known],
                                "status": cv["status"], "explanation": cv["explanation"], "hints": _hints(cv["quotes"])})
    for n, f in enumerate(data["facts"], 1):
        out["facts"].append({"id": f"FACT-{n:02d}", "subject": f["subject"], "field": f["field"], "value": f["value"],
                             "unit": f["unit"] or None, "type": None, "direction": None, "range": None,
                             "req_ids": [x for x in f["req_ids"] if x in known], "hints": _hints(f["quotes"])})
    return out


def verify_meaning(document: dict[str, Any], items: list[dict[str, Any]], ask: Callable) -> dict[str, dict[str, Any]]:
    """items: [{cid, kind, title, impact, claim, quotes: [{block_id, quote, block_text}]}] → {cid: verdict}."""
    if not items:
        return {}
    payload = {"task": TASK_MEANING, "input": {"candidates": items}, "context": {
        "mode": "auto", "block_ids": sorted({q["block_id"] for it in items for q in it["quotes"]})}}
    data = ask("verify_meaning", payload, MEANING_SCHEMA)
    return {v["cid"]: v for v in data["verdicts"]}
