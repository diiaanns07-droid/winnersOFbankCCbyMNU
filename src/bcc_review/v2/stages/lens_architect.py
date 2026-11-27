"""Линза «Архитектор» (№07): контракт API, полнота операций, стык со спецификацией, данные, события.

Промпт — `prompts/lens_architect.md`. Ответ модели: `candidates` (общая схема кандидатов, CONTRACT 2.3)
плюс `inventory` — опись операций, обещаний, кодов ответа и полей. Опись нужна модели как черновик для
сверки (слабые модели без неё пропускают «нет операции чтения» и расхождения кодов), а отчёту и судье —
как доказательная база.

Постобработка кодом (без модели):
* critical без сценария, последствий или с `blocks = none` понижается до major (CONTRACT, раздел 5);
* точные дубли (тот же вид и тот же набор строк цитат) схлопываются;
* порядок critical → major → minor, не больше MAX_CANDIDATES;
* critical «нет операции» без цитаты явного обещания интерфейса (и без кода ответа) понижается до major;
* «поле без условия нет в телах ошибок» (проверка 4а), «поле не перечислено в хранимых данных» без правила,
  которому оно нужно (разбор №18), и «ответ / тело вызова смежной системы не описаны» — minor;
* документ задаёт ключ идемпотентности — замечания о повторах minor (`cap_defined_repeats`);
* страховки по описи и сигналам: ветка без ответа, обещанная операция без описания, «успех против ошибки»
  по сигналу правила `api.success_with_error` (`branch_candidates`, `promise_candidates`,
  `success_error_candidates`);
* `requirement_ids`, которых нет в нарезке, убираются (модель иногда ставит ID из документа);
* метки нумерации «L052» в текстах заменяются на «стр. 52» (рубрика понятности: без внутренних кодов).
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

# Опись строгая (additionalProperties: false). Замер волны 3, сессия 2: со свободной описью (лишние поля разрешены)
# sonnet на официальном писал К3 в 1 из 3 прогонов вместо 3 из 3 и 8–11 кандидатов вместо 10–12, haiku терял К3
# в 4 из 11. Лишние поля модели (заметки в описи) запрещает промпт; claude -p при них переписывает ответ заново.
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


TEXT_FIELDS = ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question")
LINE_MARK = re.compile(r"\bL(\d{2,4})\b")  # метка нумерации «L052», «L52» в тексте для читателя


def plain_line_refs(text: str) -> str:
    """«L052» → «стр. 52»: метки нумерации — внутренний формат запроса, читателю нужен номер строки."""
    return LINE_MARK.sub(lambda m: f"стр. {int(m.group(1))}", text)


HTTP_CODE = re.compile(r"(?<!\d)[1-5]\d\d(?!\d)")  # шаг сам называет код ответа — исход задан
# Явное обещание интерфейса в цитате: «через дочерний документ», «методом …», строка Description, спецификация,
# API/REST, вызов в последовательности «A → B: действие».
PROMISE_MARK = re.compile(r"дочерн\w* документ|метод|description|спецификац|\bapi\b|\brest\b|интерфейс|"
                          r"→[^:.]{1,60}:", re.I)


# Шкала линзы (промпт, «Серьёзность»): critical — только обещанная, но не описанная операция или код ответа
# (missing_element) и успех против ошибки для одного входа (status_conflict). Замер волны 3: critical других видов
# (contradiction, unit_mismatch) из линзы — 7 из 16 на чистых ТЗ №18, остальные — конфликты правил зоны №09.
CRITICAL_KINDS = {"missing_element", "status_conflict"}
# «Поле без условия нет в телах ошибок» (проверка 4а) — minor: клиент разбирает тело по коду ответа, а на чистых
# ТЗ №20 это замечание шло major там, где документ сам задаёт состав тела ошибки (волна 3, сессия 2).
ERROR_BODY_TITLE = re.compile(r"(тел\w*|ответ\w*|пример\w*)\s+(\w+\s+)?(ошиб|неуспеш|[45]\d\d)", re.I)


# «Поле API есть, но нет в перечне хранимых данных» (разбор №18, задача 0а) — minor, если правила на поле не
# опираются: значение приходит в запросе или пишется в колонку БД. Major остаётся, когда заголовок называет правило
# или атрибут, без которого правило не выполнить (тип операции, ссылка на исходную операцию, история).
DATA_LIST_TITLE = re.compile(r"(не входит|не входят|нет|вне|не указан\w*|не перечислен\w*|отсутству\w*)\s.{0,30}"
                             r"перече?н|перече?н\w*\s.{0,40}(нет|не содерж|не указ)|пиш\w+ в (бд|хранилищ)|"
                             r"(хранимы\w*|модел\w*) данн\w*\s.{0,20}не (содерж|включ|перечисл)", re.I)
RULE_NEED = re.compile(r"правил|\bф-\d|требу|нужн|\bдля\b|тип\w* операц|ссылк|возврат|истори|расч[её]т|"
                       r"показ|отправ|сообщени|уведомл", re.I)


def data_list_only(c: dict) -> bool:
    """Замечание только о том, что поле интерфейса не перечислено в хранимых данных (без правила, которому оно нужно)."""
    title = str(c.get("title") or "")
    return c.get("kind") == "missing_element" and bool(DATA_LIST_TITLE.search(title)) and not RULE_NEED.search(title)


# «Ответ / тело … не описаны» для вызовов смежных систем и состояний без примера — minor (в списке промпта «не пиши
# вовсе»; калибровка F4, правила 6 и 8). Тело успешного ответа своего метода, на которое ссылается таблица кодов,
# не трогаем: по калибровке F4 (правило 4) это major. На сохранённых ответах волны ни одно понижаемое замечание —
# не пункт эталона.
BODY_GAP_TITLE = re.compile(r"^([^:]{1,20}:\s*)?(ответ\w*|тел[оа]\w*|формат\w* ответ\w*)\b.{0,80}"
                            r"(не описан\w*|без описания)", re.I)
OWN_SUCCESS = re.compile(r"успешн|\b2\d\d\b|ссыла|отсыла", re.I)


def success_body_ref(c: dict) -> bool:
    """Замечание «ответ / тело … не описаны» о вызове смежной системы или состоянии без примера (не о теле
    успешного ответа своего метода, на которое ссылается таблица кодов)."""
    t = str(c.get("title") or "")
    return c.get("kind") in ("api_contract", "missing_element", "incomplete") and \
        bool(BODY_GAP_TITLE.search(t)) and not OWN_SUCCESS.search(t)


# Раздел требований к данным (по пути раздела DocView): там должен быть атрибут, которого «нет в хранимых данных».
DATA_SECTION = re.compile(r"требовани\w*\s+к\s+(хранени\w*\s+)?данн|модел\w*\s+данн|хранимы\w*\s+данн|^данные$|"
                          r"структур\w*\s+данн", re.I)
DATA_GAP_TITLE = re.compile(r"данн|хранени|хранит|хранимы|хранят|перече?н", re.I)
MAX_EVIDENCE = 3


def data_section_lines(view: Any) -> list[dict]:
    """Непустые строки раздела требований к данным (не заголовки), в порядке документа."""
    out = []
    for ln in (view or {}).get("lines") or []:
        sec = str(ln.get("section") or "").split("›")[-1].strip()
        if sec and DATA_SECTION.search(sec) and not ln.get("heading") and str(ln.get("text") or "").strip():
            out.append(ln)
    return out


def add_data_list_evidence(candidates: list[dict], view: Any) -> int:
    """Замечание «атрибута нет в хранимых данных» без цитаты перечня данных получает первую строку перечня.

    Правило 2 системного промпта: отсутствие доказывается цитатой места, где элемент должен быть. haiku пишет такое
    замечание по строке параметра и по правилу, а сам перечень не цитирует (официальный ТЗ, замер №29) — читатель
    не видит, что именно перечислено. Цитата — дословный текст строки документа. Возвращает число правок."""
    data = data_section_lines(view)
    if not data:
        return 0
    lines = {int(x.get("n") or 0) for x in data}
    first = data[0]
    n = 0
    for c in candidates:
        if not isinstance(c, dict) or c.get("kind") not in ("missing_element", "incomplete"):
            continue
        ev = c.get("evidence") or []
        if not DATA_GAP_TITLE.search(str(c.get("title") or "")) or len(ev) >= MAX_EVIDENCE:
            continue
        if any(int(e.get("line") or 0) in lines for e in ev if isinstance(e, dict)):
            continue
        ev.append({"quote": str(first.get("text") or "").strip()[:200], "line": int(first.get("n") or 0)})
        c["evidence"] = ev
        n += 1
    return n


# «Прямой вызов в одной схеме, путь через промежуточный компонент в другой» — промпт (проверка 8) прямо говорит, что
# путь через промежуточный компонент — это связь, а не расхождение. haiku пишет это major на чистых ТЗ (qr_clean, замер
# №29 и прогоны open2 05:20, 08:35). Нужны обе приметы: заголовок о прямом пути против пути «через», цитаты — схемы со
# стрелками. «Связи нет в архитектуре» (без «через», официальный С16) не трогаем.
VIA_TITLE = re.compile(r"напрям|прям\w*\s+(вызов|путь|связ)|минует|в\s+обход|(вызов|путь|связ)\w*.{0,60}\bчерез\b",
                       re.I)
ARROW = re.compile(r"→|->")


def via_intermediate(c: dict) -> bool:
    """Расхождение схем, которое сводится к пути через промежуточный компонент (не дефект по проверке 8)."""
    if c.get("kind") not in ("contradiction", "terminology", "incomplete"):
        return False
    arrows = [e for e in c.get("evidence") or [] if isinstance(e, dict) and ARROW.search(str(e.get("quote") or ""))]
    return len(arrows) >= 2 and bool(VIA_TITLE.search(str(c.get("title") or "")))


def error_body_gap(c: dict) -> bool:
    """Замечание проверки 4а: поле ответа без условия отсутствует в телах ошибок."""
    return c.get("kind") == "api_contract" and bool(ERROR_BODY_TITLE.search(str(c.get("title") or "")))


def unpromised_critical(c: dict) -> bool:
    """critical «нет операции», ни одна цитата которого не содержит явного обещания интерфейса и кода ответа.

    Такой critical держится только на экране или на обмене со смежной системой (замер №18: «номер полиса от
    страховой компании» на чистом ТЗ). По шкале линзы critical — только явно обещанная операция (п. 1)."""
    if c.get("severity") != "critical" or c.get("kind") != "missing_element":
        return False
    quotes = [str(e.get("quote") or "") for e in c.get("evidence") or []]
    return not any(PROMISE_MARK.search(q) or HTTP_CODE.search(q) for q in quotes)


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
        if c["severity"] == "critical" and c.get("kind") not in CRITICAL_KINDS:
            c["severity"] = "major"  # шкала линзы: противоречия правил и единицы — major (их critical — набор №09)
        if unpromised_critical(c):
            c["severity"] = "major"
        if c["severity"] != "minor" and (error_body_gap(c) or data_list_only(c) or success_body_ref(c)
                                         or via_intermediate(c)):
            c["severity"] = "minor"
        if requirement_ids is not None:
            c["requirement_ids"] = [r for r in c.get("requirement_ids") or [] if r in requirement_ids]
        for k in TEXT_FIELDS:
            if isinstance(c.get(k), str):
                c[k] = plain_line_refs(c[k])
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


# Явное обещание интерфейса в строке обещания (без вызова «A → B:» — его сверяет проверка 8).
EXPLICIT_PROMISE = re.compile(r"дочерн\w* документ|спецификац|\bapi\b|\brest\b|интерфейс|\bметод\w*", re.I)
MAX_PROMISE_CANDIDATES = 2
_STEM = re.compile(r"[а-яёa-z]{5,}", re.I)


def _stems(text: str) -> set[str]:
    return {w[:5].lower().replace("ё", "е") for w in _STEM.findall(text or "")}


def promise_candidates(inventory: dict, view: Any, candidates: list[dict]) -> list[dict]:
    """Кандидаты «обещанная операция не описана», которые модель внесла в опись, но не оформила замечанием.

    Замер волны 3 (haiku, open2): опись верно отмечает обещание без операции («включает … через дочерний
    документ», operation пуст), а кандидата нет — пропадает К3-тип. Код добавляет critical, только если строка
    обещания сама называет интерфейс (дочерний документ, спецификация, API, метод) и ни одно замечание
    «нет элемента» не цитирует эту строку и не говорит о том же действии. Обещания одной строки — одно замечание.
    """
    mine = [c for c in candidates if c.get("kind") == "missing_element"]
    told = [_stems(" ".join(str(c.get(k) or "") for k in ("title", "problem"))) for c in mine]
    # Строка покрыта, только если её цитирует замечание о том же действии: на insurance строку обещания цитировало
    # постороннее замечание о номере полиса, и обещание «оформить отказ» пропадало.
    cited = [({int(e.get("line") or 0) for e in c.get("evidence") or []}, t) for c, t in zip(mine, told)]
    by_line: dict[int, list[str]] = {}
    for p in unfulfilled_promises(inventory):
        try:
            n = int(p.get("line") or 0)
        except (TypeError, ValueError):
            continue
        what = str(p.get("what") or "").strip().rstrip(".")
        text = _line_text(view, n)
        if not n or not what or not text or not EXPLICIT_PROMISE.search(text):
            continue
        if any(len(_stems(what) & t) >= 2 for t in told) or any(n in ls and _stems(what) & t for ls, t in cited):
            continue
        by_line.setdefault(n, []).append(what)
    out: list[dict] = []
    for n, whats in sorted(by_line.items())[:MAX_PROMISE_CANDIDATES]:
        text = _line_text(view, n)
        objs = "; ".join(dict.fromkeys(whats))
        out.append({
            "title": f"Обещанная операция не описана: {objs}"[:120],
            "kind": "missing_element", "criterion": "set_complete", "severity": "critical", "requirement_ids": [],
            "evidence": [{"quote": text[:200], "line": n}],
            "problem": f"Документ обещает через интерфейс: {objs}, — но ни одна описанная операция этого не "
                       "выполняет.",
            "scenario": "Разработчик приложения ищет в спецификации запрос для этого действия и не находит его: "
                        "метод, путь, параметры и ответ не заданы.",
            "impact": "Обещанную функцию нельзя реализовать и проверить по документу.",
            "recommendation": "Описать операцию в спецификации: метод, путь, параметры, коды и тело ответа.",
            "rewrite": "<уточнить: метод, путь и тело ответа операции>", "question": "", "blocks": "both",
            "source": SOURCE, "origin": "inventory",
        })
    return out


# Документ сам задаёт ключ идемпотентности запроса («ключ идемпотентности …», «повторный запрос с тем же requestId не
# создаёт …»). Тогда замечания о повторах (после ошибки, во время первого запроса, гонки) — уровень minor: промпт
# (проверка 9) велит в этом случае о повторах не писать, а haiku пишет (чистые ТЗ №20: fx, repay — 4 major из 16).
IDEMPOTENCY_DEFINED = re.compile(r"ключ\w* идемпотентност|idempotency|повторн\w* (запрос|вызов)\w* с тем же|"
                                 r"с тем же `?[\w-]+`? (не создаёт|возвращ)", re.I)
REPEAT_TITLE = re.compile(r"повтор|идемпотент|дубл", re.I)


def defines_idempotency(view: Any) -> bool:
    return any(IDEMPOTENCY_DEFINED.search(str(ln.get("text") or "")) for ln in (view or {}).get("lines") or [])


def cap_defined_repeats(candidates: list[dict], view: Any) -> int:
    """Понижает до minor замечания о повторах, если документ задаёт ключ идемпотентности. Возвращает число правок."""
    if not defines_idempotency(view):
        return 0
    n = 0
    for c in candidates:
        if isinstance(c, dict) and c.get("severity") in ("critical", "major") and \
                REPEAT_TITLE.search(str(c.get("title") or "")):
            c["severity"] = "minor"
            n += 1
    return n


SUCCESS_ERROR_RULE = "api.success_with_error"
_CODE = re.compile(r"(?<!\d)([1-5]\d\d)(?!\d)")


def success_error_candidates(signals: list, view: Any, candidates: list[dict]) -> list[dict]:
    """Страховка К-типа «успех против ошибки» по сигналу правила №12 `api.success_with_error`.

    Замер волны 3 (haiku): опись линзы отмечает «тело с признаком ошибки у 200», но critical-замечания нет
    (4 из 11 прогонов) или оно major. Правило детерминированно находит то же противоречие (на чистых ТЗ корпуса,
    open2 и №20 не срабатывает). Если status_conflict линзы цитирует строки сигнала — он становится critical
    (шкала линзы: 2xx с ошибкой в теле против 4xx — critical); если такого нет — добавляется замечание с цитатами
    строк документа. Изменяет `candidates` на месте; возвращает добавленные.
    """
    out: list[dict] = []
    for sg in signals or []:
        if not isinstance(sg, dict) or not str(sg.get("rule") or "").startswith(SUCCESS_ERROR_RULE):
            continue
        lines = [int(n) for n in ([sg.get("line")] + list(sg.get("lines") or [])) if str(n or "").isdigit()]
        lines = list(dict.fromkeys(n for n in lines if _line_text(view, n)))
        if not lines:
            continue
        own = [c for c in candidates if c.get("kind") == "status_conflict"
               and {int(e.get("line") or 0) for e in c.get("evidence") or []} & set(lines)]
        if own:
            for c in own:
                if c.get("severity") != "critical":
                    c["severity"] = "critical"
                    c["scenario"] = c.get("scenario") or "Клиент отправляет неверные данные и по одному месту " \
                                                           "документа получает успешный код, по другому — код ошибки."
                    c["impact"] = c.get("impact") or "Клиент, который смотрит на код ответа, сочтёт отказ успехом."
                    c["blocks"] = c.get("blocks") if c.get("blocks") not in (None, "", "none") else "both"
            continue
        codes = _CODE.findall(str(sg.get("note") or sg.get("message") or ""))
        ok = next((x for x in codes if x.startswith("2")), "200")
        err = next((x for x in codes if x.startswith("4")), "400")
        a, b = lines[0], next((n for n in lines[1:]), lines[0])
        out.append({
            "title": f"Неверный ввод: код {ok} с ошибкой в теле и код {err}",
            "kind": "status_conflict", "criterion": "set_consistent", "severity": "critical", "requirement_ids": [],
            "evidence": [{"quote": _line_text(view, n)[:200], "line": n} for n in lines[:3]],
            "problem": f"Для одного и того же неверного ввода документ в одном месте задаёт успешный код {ok} с "
                       f"признаком ошибки в теле, а в другом — код ошибки {err}.",
            "scenario": f"Клиент отправляет запрос с неверным значением: по строке {a} сервер вернёт {ok} с ошибкой "
                        f"в теле, по строке {b} — {err}; приложение, которое смотрит на код, покажет успех.",
            "impact": "Клиент сочтёт отказ успехом; тест не знает, какой код ожидать.",
            "recommendation": f"Оставить для неверного ввода один исход — код {err} с телом ошибки — и исправить "
                              f"пример ответа {ok}.",
            "rewrite": f"{err} — параметры запроса заполнены неверно; тело: <уточнить: поля тела ошибки>",
            "question": "", "blocks": "both", "source": SOURCE, "origin": "signal",
        })
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
    raw = copy.deepcopy(dict(raw or {}))  # страховки правят кандидатов модели на месте — не трогаем кэш ответа
    inv = raw.get("inventory") if isinstance(raw.get("inventory"), dict) else {}
    extra = branch_candidates(inv, getattr(ctx, "view", None), list(raw.get("candidates") or []))
    extra += promise_candidates(inv, getattr(ctx, "view", None), list(raw.get("candidates") or []) + extra)
    model_cands = [c for c in raw.get("candidates") or [] if isinstance(c, dict)]
    extra += success_error_candidates(getattr(ctx, "signals", None) or [], getattr(ctx, "view", None), model_cands)
    raw["candidates"] = model_cands
    if extra:
        raw["candidates"] = list(raw.get("candidates") or []) + extra
    cap_defined_repeats(raw["candidates"], getattr(ctx, "view", None))
    add_data_list_evidence(raw["candidates"], getattr(ctx, "view", None))
    reqs = {r.get("id") for r in getattr(ctx, "requirements", None) or [] if isinstance(r, dict)}
    result = postprocess(raw, requirement_ids=reqs or None)
    extras = {k: v for k, v in raw.items() if k not in ("candidates", "inventory")}
    return {**extras, **result}
