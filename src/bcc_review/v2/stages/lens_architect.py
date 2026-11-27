"""Линза «Архитектор» (№07): контракт API, полнота операций, стык со спецификацией, данные, события.

Промпт — `prompts/lens_architect.md`. Ответ модели: `candidates` (общая схема кандидатов, CONTRACT 2.3)
плюс `inventory` — опись операций, обещаний, кодов ответа и полей. Опись нужна модели как черновик для
сверки (слабые модели без неё пропускают «нет операции чтения» и расхождения кодов), а отчёту и судье —
как доказательная база.

Постобработка кодом (без модели):
* critical без сценария, последствий или с `blocks = none` понижается до major (CONTRACT, раздел 5);
* точные дубли (тот же вид и тот же набор строк цитат) схлопываются;
* порядок critical → major → minor, не больше MAX_CANDIDATES;
* `requirement_ids`, которых нет в нарезке, убираются (модель иногда ставит ID из документа).
"""
from __future__ import annotations

import copy
import re
from typing import Any

NAME = "architect"
PROMPT = "lens_architect"
SOURCE = "lens:architect"
MAX_CANDIDATES = 12

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": list(props) if required is None else required}


_S = {"type": "string"}
_INT = {"type": "integer"}

CANDIDATE_SCHEMA = _obj({
    "title": _S, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
    "requirement_ids": {"type": "array", "items": _S},
    "evidence": {"type": "array", "items": _obj({"quote": _S, "line": _INT})},
    "problem": _S, "scenario": _S, "impact": _S, "recommendation": _S, "rewrite": _S, "question": _S,
    "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]},
})

INVENTORY_SCHEMA = _obj({
    "operations": {"type": "array", "items": _obj({"name": _S, "method": _S, "purpose": _S, "line": _INT})},
    "promises": {"type": "array", "items": _obj({"what": _S, "line": _INT, "operation": _S})},
    "codes": {"type": "array", "items": _obj({
        "code": _S, "lines": {"type": "array", "items": _INT}, "described": {"type": "boolean"}, "note": _S})},
    "fields": {"type": "array", "items": _obj({"name": _S, "places": _S})},
    "branches": {"type": "array", "items": _obj({"operation": _S, "step": _S, "line": _INT, "outcome": _S})},
})


def schema(candidate_schema: dict | None = None) -> dict:
    """Схема ответа линзы: опись + кандидаты (по умолчанию — локальная копия схемы кандидатов)."""
    return _obj({"inventory": INVENTORY_SCHEMA,
                 "candidates": {"type": "array", "items": candidate_schema or CANDIDATE_SCHEMA}})


SCHEMA = schema()


def empty_inventory() -> dict:
    return {"operations": [], "promises": [], "codes": [], "fields": [], "branches": []}


def _evidence_key(c: dict) -> tuple:
    lines = sorted({int(e.get("line") or 0) for e in c.get("evidence") or []})
    return (c.get("kind", ""), tuple(lines))


def undefined_branches(inventory: dict) -> list[dict]:
    """Ветки логики, для которых документ не задаёт ответа (для отчёта и проверки полноты)."""
    return [b for b in (inventory or {}).get("branches") or [] if not str(b.get("outcome") or "").strip()]


def unfulfilled_promises(inventory: dict) -> list[dict]:
    """Обещания описи, для которых модель не нашла операции (для отчёта и проверки полноты)."""
    return [p for p in (inventory or {}).get("promises") or [] if not str(p.get("operation") or "").strip()]


def postprocess(data: dict, requirement_ids: set[str] | None = None,
                max_candidates: int = MAX_CANDIDATES) -> dict:
    """Нормализует ответ модели. Не меняет вход; возвращает {"candidates": [...], "inventory": {...}}."""
    data = copy.deepcopy(data or {})
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in data.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        c["evidence"] = [e for e in c.get("evidence") or []
                         if isinstance(e, dict) and str(e.get("quote") or "").strip()]
        if not c["evidence"]:
            continue  # нет цитаты — нет утверждения (системный промпт, правило 2)
        if c.get("severity") not in SEVERITY_ORDER:
            c["severity"] = "major"
        if c["severity"] == "critical" and (not str(c.get("scenario") or "").strip()
                                            or not str(c.get("impact") or "").strip()
                                            or c.get("blocks") in (None, "", "none")):
            c["severity"] = "major"
        if requirement_ids is not None:
            c["requirement_ids"] = [r for r in c.get("requirement_ids") or [] if r in requirement_ids]
        key = _evidence_key(c)
        if key in seen:
            continue
        seen.add(key)
        c.setdefault("source", SOURCE)
        out.append(c)
    out.sort(key=lambda c: SEVERITY_ORDER[c["severity"]])  # sort устойчивый: порядок модели внутри уровня
    inv = data.get("inventory") if isinstance(data.get("inventory"), dict) else {}
    inventory = empty_inventory()
    inventory.update({k: v for k, v in inv.items() if k in inventory and isinstance(v, list)})
    return {"candidates": out[:max_candidates], "inventory": inventory}


OUTPUT_LIMIT = re.compile(r"output token|max_tokens|max output tokens|обрезан|лимит\w* выход", re.I)
API_KINDS = {"api", "integration", "data", "architecture"}
# Провайдеры, у которых лимит ответа 32 000 безопасен (их собственный лимит по умолчанию — 32 000, №02).
# У слабых моделей в лимит входит рассуждение: haiku на этой линзе тратит 24–45 тыс. токенов, и запрос
# с 16 000 впустую падает через ~5 минут. Для локальных моделей (openai) остаётся общий лимит линз.
WIDE_OUTPUT_PROVIDERS = {"claude_cli", "gemini", "anthropic", "mock"}
WIDE_OUTPUT_TOKENS = 32000


BRANCH_TITLE = "Ветка логики без ответа"
# Условная ветка, которая сама велит что-то вернуть: «при отклонении … вернуть …», «если …, вернуть …».
# Нужны оба признака: шаг основного пути («выполнить … и вернуть результат») описан ответом 200, а ветка,
# которая задаёт исход словами («если …, возвращаются сведения …»), — с ответом (ложные на №18, волна 3).
BRANCH_RETURN = re.compile(r"верн", re.I)
BRANCH_CONDITION = re.compile(r"\bпри\b|\bесли\b|в случае|иначе|отклон|отказ", re.I)
MAX_BRANCH_CANDIDATES = 2
HTTP_CODE = re.compile(r"(?<!\d)[1-5]\d\d(?!\d)")  # шаг сам называет код ответа — исход задан


def _line_text(view: Any, n: int) -> str:
    for ln in (view or {}).get("lines") or []:
        if int(ln.get("n") or 0) == n:
            return str(ln.get("text") or "").strip()
    return ""


def branch_candidates(inventory: dict, view: Any, candidates: list[dict]) -> list[dict]:
    """Кандидаты на ветки логики без ответа, которые модель внесла в опись, но не оформила замечанием.

    Слабая модель (haiku с effort=low) верно отмечает ветку без ответа в `inventory.branches`, но потом
    сливает её с соседним замечанием. Код добавляет замечание, только если шаг — условная ветка, которая
    велит что-то вернуть без кода («при отклонении … вернуть …»), и ни один кандидат не цитирует эту строку
    как ветку логики
    (заголовок со словом «ветка» — модель пишет и «Ветка «вернуть …» без поля …»).
    Цитата — дословный текст строки документа, поэтому сверка цитат пройдёт.
    """
    covered = {int(e.get("line") or 0) for c in candidates
               if "ветк" in str(c.get("title") or "").lower() for e in c.get("evidence") or []}
    out: list[dict] = []
    for b in undefined_branches(inventory):
        try:
            n = int(b.get("line") or 0)
        except (TypeError, ValueError):
            continue
        text = _line_text(view, n)
        if (not n or n in covered or not text or not BRANCH_RETURN.search(text)
                or not BRANCH_CONDITION.search(text) or HTTP_CODE.search(text)):
            continue
        covered.add(n)
        step = str(b.get("step") or "").strip().rstrip(".") or text
        out.append({
            "title": f"{BRANCH_TITLE}: {step}"[:120],
            "kind": "api_contract", "criterion": "complete", "severity": "major", "requirement_ids": [],
            "evidence": [{"quote": text[:200], "line": n}],
            "problem": f"Шаг логики «{text[:160]}» требует ответа, но документ не задаёт для этой ветки код и "
                       "состав тела: в перечне кодов и в примерах тел её нет.",
            "scenario": "Запрос попадает в эту ветку логики: по документу неизвестно, какой код и какие поля "
                        "вернёт метод.",
            "impact": "Сервер и клиент реализуют ответ по-разному; тест этой ветки нельзя написать однозначно.",
            "recommendation": "Описать для ветки код ответа и тело: какие поля и с какими значениями возвращаются.",
            "rewrite": "<уточнить: код и тело ответа для этой ветки>", "question": "", "blocks": "both",
            "source": SOURCE, "origin": "inventory",
        })
        if len(out) >= MAX_BRANCH_CANDIDATES:
            break
    return out


def _is_output_limit(exc: BaseException) -> bool:
    return getattr(exc, "kind", "") == "truncated" or bool(OUTPUT_LIMIT.search(str(exc)))


def split_requirements(requirements: list) -> list[list[str]]:
    """Две части для повтора при переполнении вывода: контракт и данные — отдельно от остального."""
    ids = [r.get("id") for r in requirements or [] if isinstance(r, dict) and r.get("id")]
    api = [r.get("id") for r in requirements or [] if isinstance(r, dict) and r.get("id")
           and r.get("kind") in API_KINDS]
    rest = [i for i in ids if i not in set(api)]
    if not api or not rest:
        half = max(1, len(ids) // 2)
        api, rest = ids[:half], ids[half:]
    return [part for part in (api, rest) if part]


def _run_parts(ctx: Any) -> dict:
    from . import lens  # каркас №01
    from ..llm import merge_lists

    system, user = ctx.prompt(f"lens_{NAME}")
    schema = lens.schema_for(NAME)
    parts, failed = [], []
    for ids in split_requirements(getattr(ctx, "requirements", None) or []):
        try:
            parts.append(ctx.llm.ask(f"lens_{NAME}", system, user + lens.FOCUS.format(ids=", ".join(ids)),
                                     schema, max_output_tokens=output_limit(ctx)))
        except Exception as exc:  # noqa: BLE001 — одна часть не должна ронять другую
            failed.append(f"{ids[0]}…{ids[-1]}: {exc}")
            if not parts and _is_output_limit(exc):
                break  # и половина не уместилась: дело в рассуждении модели, вторая часть не поможет
    if not parts:
        raise RuntimeError("Линза «Архитектор»: обе части не выполнены — " + "; ".join(failed))
    if failed and hasattr(ctx, "warn"):
        ctx.warn("Линза «Архитектор»: часть требований не проверена — " + "; ".join(failed)[:300])
    return merge_lists(parts)


EMPTY_RETRY = ("\n\nПредыдущий ответ на этот запрос пришёл пустым: ни одного элемента описи и ни одного кандидата. "
               "Документ описывает интерфейс: заполни опись по тексту (операции, коды ответа, поля, шаги логики) "
               "и выполни проверки шага 2.")
# Признаки интерфейса в тексте документа: HTTP-метод, код ответа рядом со словом «код/статус/ответ», API.
INTERFACE_HINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b|\bAPI\b|\bREST\b|endpoint|эндпоинт", re.I)


def is_empty_answer(raw: Any) -> bool:
    """Пустой ответ: ни кандидатов, ни одного элемента описи (схема пройдена, но модель ничего не проверила)."""
    if not isinstance(raw, dict):
        return True
    if raw.get("candidates"):
        return False
    inv = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    return not any(inv.get(k) for k in ("operations", "promises", "codes", "fields", "branches"))


def has_interface(ctx: Any) -> bool:
    reqs = getattr(ctx, "requirements", None) or []
    if any(isinstance(r, dict) and r.get("kind") in API_KINDS for r in reqs):
        return True
    lines = (getattr(ctx, "view", None) or {}).get("lines") or []
    return any(INTERFACE_HINT.search(str(ln.get("text") or "")) for ln in lines)


def _ask_whole(ctx: Any) -> dict:
    """Один запрос на весь документ. При обрезке `LLMClient.ask` (№01) сам повторяет с удвоенным лимитом.

    Пустой ответ (ни описи, ни кандидатов) на документе с интерфейсом — сбой модели, а не «дефектов нет»:
    sonnet так ответил в 1 из 3 прогонов на официальном документе (13 с, 2 тыс. токенов). Тогда один повтор
    с пометкой в запросе (другой ключ кэша, поэтому пустой ответ из кэша не вернётся).
    """
    from . import lens  # каркас №01

    stage = f"lens_{NAME}"
    if hasattr(lens, "prompts") and not lens.prompts.exists(stage):
        ctx.warn(f"Линза «{NAME}»: нет промпта {stage}.md — этап пропущен")
        return {"candidates": []}
    system, user = ctx.prompt(stage)
    schema = lens.schema_for(NAME)
    raw = ctx.llm.ask(stage, system, user, schema, max_output_tokens=output_limit(ctx))
    if is_empty_answer(raw) and has_interface(ctx):
        if hasattr(ctx, "warn"):
            ctx.warn("Линза «Архитектор»: модель вернула пустой ответ — один повтор")
        raw = ctx.llm.ask(stage, system, user + EMPTY_RETRY, schema, max_output_tokens=output_limit(ctx))
    return raw


def output_limit(ctx: Any) -> int:
    from . import lens  # каркас №01

    base = int(getattr(lens, "MAX_OUTPUT_TOKENS", 16000))
    name = str(getattr(getattr(ctx, "llm", None), "provider_name", "") or "")
    return max(base, WIDE_OUTPUT_TOKENS) if name in WIDE_OUTPUT_PROVIDERS else base


def run(ctx: Any) -> dict:
    """Запуск линзы с собственной схемой (`SCHEMA`) и постобработкой.

    Линза сверяет места по всему документу (обещание в одной части, операция — в другой), поэтому пакет
    требований сначала не делится: один запрос, при обрезке — повтор с удвоенным лимитом ответа (`llm.ask`).
    Если и так не уместилось — два запроса: требования контракта, данных и интеграции отдельно от остальных
    (документ модель видит целиком). Деление глубже не помогает: у слабых моделей лимит съедает рассуждение,
    а не объём ответа (замер haiku, статус №07).
    """
    try:
        raw = _ask_whole(ctx)
    except Exception as exc:  # noqa: BLE001
        if not _is_output_limit(exc) or len(getattr(ctx, "requirements", None) or []) < 2:
            raise
        if hasattr(ctx, "warn"):
            ctx.warn("Линза «Архитектор»: ответ не уместился в лимит вывода — повтор двумя частями")
        raw = _run_parts(ctx)
    raw = dict(raw or {})
    inv = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    extra = branch_candidates(inv, getattr(ctx, "view", None), list(raw.get("candidates") or []))
    if extra:
        raw["candidates"] = list(raw.get("candidates") or []) + extra
    reqs = {r.get("id") for r in getattr(ctx, "requirements", None) or [] if isinstance(r, dict)}
    result = postprocess(raw, requirement_ids=reqs or None)
    extras = {k: v for k, v in raw.items() if k not in ("candidates", "inventory")}
    return {**extras, **result}
