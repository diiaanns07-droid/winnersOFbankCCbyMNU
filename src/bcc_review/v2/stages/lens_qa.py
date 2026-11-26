"""Линза «Тестировщик» (№06): исполнение критериев приёмки, проверяемость, покрытие, тест-кейсы.

Модель отвечает тремя списками (схема :data:`SCHEMA`):

* ``acceptance_checks`` — по записи на каждую строку критериев приёмки: факты строки → правила →
  ожидаемый по правилам результат → заявленный результат → ``verdict``;
* ``candidates`` — дефекты проверяемости и покрытия (общая схема кандидатов, CONTRACT 2.3);
* ``test_cases`` — черновик тест-кейсов «Дано / Когда / Тогда».

Код (:func:`postprocess`) превращает ``conflict`` в critical-кандидата с цитатами правила и строки,
``undefined`` — в major, убирает дубли модели по тем же строкам, нумерует тест-кейсы ``T-01…`` и
отмечает строки приёмки, которые модель пропустила.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

STAGE = "lens_qa"
SOURCE = "lens:qa"
MAX_TEST_CASES = 15
MAX_MODEL_CANDIDATES = 12
UNDEFINED_PREFIX = "Не определено требованиями"

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
CONFLICT_KINDS = ["event_conflict", "boundary_conflict", "status_conflict", "unit_mismatch", "contradiction"]
VERDICTS = ["match", "conflict", "undefined"]


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else list(props)}


_S = {"type": "string"}
_INT = {"type": "integer"}
_IDS = {"type": "array", "items": _S}
_EVIDENCE = {"type": "array", "items": _obj({"quote": _S, "line": _INT})}

CANDIDATE_SCHEMA = _obj({
    "title": _S, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
    "requirement_ids": _IDS, "evidence": _EVIDENCE,
    "problem": _S, "scenario": _S, "impact": _S, "recommendation": _S, "rewrite": _S, "question": _S,
    "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]},
})

# Порядок полей — порядок рассуждения модели: факты → правила → ожидаемое → заявленное → вердикт.
ACCEPTANCE_CHECK_SCHEMA = _obj({
    "row_requirement_id": _S,
    "row_quote": _S,
    "row_line": _INT,
    "row_facts": _S,
    "assumptions": _S,
    "rule_requirement_ids": _IDS,
    "rule_evidence": _EVIDENCE,
    "derivation": _S,
    "expected_by_rules": _S,
    "stated": _S,
    "stated_line": _INT,
    "verdict": {"type": "string", "enum": VERDICTS},
    "conflict_kind": {"type": "string", "enum": CONFLICT_KINDS + ["none"]},
    "explanation": _S,
    "fix": _S,
})

TEST_CASE_SCHEMA = _obj({
    "requirement_ids": _IDS, "title": _S, "given": _S, "when": _S, "then": _S, "gap": _S,
    "expected_defined": {"type": "boolean"},
})

SCHEMA = _obj({
    "acceptance_checks": {"type": "array", "items": ACCEPTANCE_CHECK_SCHEMA},
    "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
    "test_cases": {"type": "array", "items": TEST_CASE_SCHEMA},
})


def schema() -> dict:
    return SCHEMA


# ---------------------------------------------------------------- вспомогательное

def _s(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def _ids(x: Any) -> list[str]:
    out: list[str] = []
    for v in x or []:
        v = _s(v)
        if v and v not in out:
            out.append(v)
    return out


def _int(x: Any) -> int | None:
    try:
        n = int(x)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _norm(s: str) -> str:
    s = re.sub(r"[«»“”„\"']", '"', s or "")
    s = re.sub(r"[—–‑−]", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _sentence(s: str) -> str:
    s = _s(s)
    return s if not s or s[-1] in ".!?…»\"" else s + "."


def _lower_first(s: str) -> str:
    """«Итог 50» → «итог 50» внутри фразы; аббревиатуры («HTTP 400», «ОК») не трогаем."""
    return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and s[1].islower() else s


def _req_index(requirements: Iterable[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    return {str(r.get("id")): r for r in requirements or [] if r.get("id")}


def _label(rid: str, index: Mapping[str, Mapping[str, Any]]) -> str:
    """«R-06 (Ф-2)» — ID нарезки и исходный номер, если он есть."""
    src = _s((index.get(rid) or {}).get("source_id"))
    return f"{rid} ({src})" if src and src != rid else rid


def _labels(ids: list[str], index: Mapping[str, Mapping[str, Any]]) -> str:
    return ", ".join(_label(i, index) for i in ids) if ids else "правила документа"


def acceptance_rows(requirements: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """ID требований вида acceptance — строки критериев приёмки, которые линза обязана исполнить."""
    return [str(r["id"]) for r in requirements or [] if r.get("id") and r.get("kind") == "acceptance"]


def resolve_row_id(check: Mapping[str, Any], requirements: Iterable[Mapping[str, Any]] | None) -> str:
    """ID строки приёмки: как дала модель, если он есть в нарезке; иначе — требование acceptance по номеру строки."""
    reqs = list(requirements or [])
    rid = _s(check.get("row_requirement_id"))
    if any(str(r.get("id")) == rid for r in reqs):
        return rid
    line = _int(check.get("row_line"))
    if line:
        for r in reqs:
            lo, hi = _int(r.get("line_start")), _int(r.get("line_end")) or _int(r.get("line_start"))
            if r.get("kind") == "acceptance" and lo and lo <= line <= (hi or lo):
                return str(r["id"])
    return rid if reqs == [] else ""


def missing_rows(checks: list[Mapping[str, Any]], requirements: Iterable[Mapping[str, Any]] | None) -> list[str]:
    done = {_s(c.get("row_requirement_id")) for c in checks}
    return [rid for rid in acceptance_rows(requirements) if rid not in done]


# ---------------------------------------------------------------- acceptance_checks

def normalize_check(raw: Mapping[str, Any]) -> dict:
    c = {
        "row_requirement_id": _s(raw.get("row_requirement_id")),
        "row_quote": _s(raw.get("row_quote")),
        "row_line": _int(raw.get("row_line")),
        "row_facts": _s(raw.get("row_facts")),
        "assumptions": _s(raw.get("assumptions")),
        "rule_requirement_ids": _ids(raw.get("rule_requirement_ids")),
        "rule_evidence": [{"quote": _s(e.get("quote")), "line": _int(e.get("line"))}
                          for e in raw.get("rule_evidence") or [] if isinstance(e, Mapping) and _s(e.get("quote"))],
        "derivation": _s(raw.get("derivation")),
        "expected_by_rules": _s(raw.get("expected_by_rules")),
        "stated": _s(raw.get("stated")),
        "stated_line": _int(raw.get("stated_line")) or _int(raw.get("row_line")),
        "verdict": raw.get("verdict") if raw.get("verdict") in VERDICTS else "undefined",
        "conflict_kind": raw.get("conflict_kind") if raw.get("conflict_kind") in CONFLICT_KINDS else "none",
        "explanation": _s(raw.get("explanation")),
        "fix": _s(raw.get("fix")),
    }
    if c["verdict"] == "conflict" and c["stated"] and _norm(c["expected_by_rules"]).rstrip(".") == _norm(
            c["stated"]).rstrip("."):
        # Модель сама вывела ровно заявленный результат — это совпадение, а не противоречие.
        c["verdict"] = "match"
    if c["verdict"] == "conflict":
        # Конфликт без цитаты правила не доказан: остаётся вопросом к документу, а не противоречием.
        if not c["rule_evidence"]:
            c["verdict"] = "undefined"
            c["conflict_kind"] = "none"
        elif c["conflict_kind"] == "none":
            c["conflict_kind"] = "contradiction"
    else:
        c["conflict_kind"] = "none"
    if c["verdict"] == "match":
        c["fix"] = ""
    return c


def _row_evidence(c: Mapping[str, Any]) -> list[dict]:
    """Цитаты строки приёмки: заявленный результат и вход (без дублей, если одна цитата содержит другую)."""
    stated, row = c["stated"], c["row_quote"]
    if row and stated and _norm(stated) in _norm(row):
        return [{"quote": row, "line": c["row_line"]}]
    ev: list[dict] = []
    if stated:
        ev.append({"quote": stated, "line": c["stated_line"]})
    if row and _norm(row) not in _norm(stated):
        ev.append({"quote": row, "line": c["row_line"]})
    return ev


def check_to_candidate(c: Mapping[str, Any], index: Mapping[str, Mapping[str, Any]]) -> dict | None:
    """``conflict`` → critical с цитатами правила и строки; ``undefined`` → major; ``match`` → None."""
    verdict = c["verdict"]
    if verdict == "match":
        return None
    row = c["row_requirement_id"]
    if (index and row not in index) or (not index and not _RID.fullmatch(row)):
        row = ""
    rules = [r for r in c["rule_requirement_ids"] if r != row and (not index or r in index)]
    if not row:
        row_label = f"в строке {c['row_line']}" if c["row_line"] else "(строка без ID)"
    else:
        row_label = _label(row, index)
    rules_label = _labels(rules, index)
    facts = _sentence(c["row_facts"])
    assumptions = f" Допущения: {_sentence(c['assumptions'])}" if c["assumptions"] else ""
    expected = _s(c["expected_by_rules"]).rstrip(".")
    stated = _s(c["stated"]).rstrip(".")
    explanation = f" {_sentence(c['explanation'])}" if c["explanation"] else ""
    req_ids = _ids(([row] if row else []) + rules)
    rule_ev = [dict(e) for e in c["rule_evidence"][:2]]

    if verdict == "conflict":
        return {
            "title": f"Ожидаемый результат критерия приёмки {row_label} противоречит {rules_label}",
            "kind": c["conflict_kind"] if c["conflict_kind"] in CONFLICT_KINDS else "contradiction",
            "criterion": "set_consistent",
            "severity": "critical",
            "requirement_ids": req_ids,
            "evidence": rule_ev + _row_evidence(c),
            "problem": (f"По {rules_label} на входе этого критерия результат — {_lower_first(expected) or 'другой'}, "
                        f"а критерий приёмки ожидает «{stated}».{explanation}"),
            "scenario": f"{facts}{assumptions} По {rules_label}: {expected}. По критерию: {stated}.",
            "impact": ("Реализация по правилу не пройдёт этот критерий приёмки, а реализация «под критерий» "
                       "нарушит правило: разработчик и тестировщик получат разный ожидаемый результат, "
                       "приёмка остановится до решения владельца продукта."),
            "recommendation": (f"Выбрать верный исход и исправить второе место: ожидаемый результат критерия "
                               f"{row_label} или текст {rules_label}."),
            "rewrite": c["fix"],
            "question": (f"Какой результат верен для этого входа: «{expected}» (по {rules_label}) "
                         f"или «{stated}» (по критерию приёмки)?"),
            "blocks": "both",
            "source": SOURCE,
            "origin": "acceptance_check",
            "derivation": c["derivation"],
        }
    return {
        "title": f"Ожидаемый результат критерия приёмки {row_label} нельзя вывести из требований",
        "kind": "incomplete",
        "criterion": "verifiable",
        "severity": "major",
        "requirement_ids": req_ids,
        "evidence": rule_ev + _row_evidence(c),
        "problem": (f"Критерий приёмки ожидает «{stated}», но правила документа не определяют результат "
                    f"для этого входа ({expected or 'правило не найдено'}).{explanation}"),
        "scenario": f"{facts}{assumptions} По требованиям исход не определён; по критерию: {stated}.",
        "impact": ("Тестировщик не может обосновать ожидаемый результат требованиями, а разработчик реализует "
                   "своё толкование: при приёмке возникнет спор, чья трактовка верна."),
        "recommendation": "Дописать в требования правило, из которого следует ожидаемый результат этого критерия.",
        "rewrite": c["fix"],
        "question": "",
        "blocks": "testing",
        "source": SOURCE,
        "origin": "acceptance_check",
        "derivation": c["derivation"],
    }


# ---------------------------------------------------------------- кандидаты модели и тест-кейсы

_CONFLICT_FAMILY = set(CONFLICT_KINDS) | {"incorrect"}
_RID = re.compile(r"R-\d+")


def normalize_candidate(raw: Mapping[str, Any]) -> dict:
    c = {k: raw.get(k) for k in CANDIDATE_SCHEMA["properties"]}
    for k in ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question"):
        c[k] = _s(c[k])
    c["kind"] = c["kind"] if c["kind"] in KINDS else "other"
    c["criterion"] = c["criterion"] if c["criterion"] in CRITERIA else "verifiable"
    c["severity"] = c["severity"] if c["severity"] in ("critical", "major", "minor") else "major"
    c["blocks"] = c["blocks"] if c["blocks"] in ("development", "testing", "both", "none") else "testing"
    c["requirement_ids"] = _ids(c["requirement_ids"])
    c["evidence"] = [{"quote": _s(e.get("quote")), "line": _int(e.get("line"))}
                     for e in c["evidence"] or [] if isinstance(e, Mapping) and _s(e.get("quote"))]
    # Шкала: critical без сценария и последствий не бывает; blocks=none у critical недопустим.
    # У линзы тестировщика critical — только противоречие (два места дают разные ожидаемые результаты);
    # непроверяемость и непокрытые ветки на чистых документах давали ложные critical, судья может поднять.
    if c["severity"] == "critical" and (not c["scenario"] or not c["impact"]
                                        or c["kind"] not in _CONFLICT_FAMILY):
        c["severity"] = "major"
    if c["severity"] == "critical" and c["blocks"] == "none":
        c["blocks"] = "testing"
    c["source"] = SOURCE
    return c


def _duplicates_check(cand: Mapping[str, Any], flagged_rows: set[str]) -> bool:
    """Модель всё же написала кандидата о противоречии строки приёмки, уже разобранной в acceptance_checks."""
    if cand["kind"] not in _CONFLICT_FAMILY and cand["criterion"] != "set_consistent":
        return False
    return bool(flagged_rows & set(cand["requirement_ids"]))


def normalize_test_case(raw: Mapping[str, Any]) -> dict:
    t = {"requirement_ids": _ids(raw.get("requirement_ids")), "title": _s(raw.get("title")),
         "given": _s(raw.get("given")), "when": _s(raw.get("when")), "then": _s(raw.get("then")),
         "gap": _s(raw.get("gap")), "expected_defined": raw.get("expected_defined") is not False}
    if UNDEFINED_PREFIX.lower() in t["then"].lower():
        t["expected_defined"] = False
    elif not t["expected_defined"]:
        t["then"] = f"{UNDEFINED_PREFIX}: {t['then']}" if t["then"] else f"{UNDEFINED_PREFIX}."
    return t


# ---------------------------------------------------------------- сборка

def postprocess(data: Mapping[str, Any] | None, requirements: Iterable[Mapping[str, Any]] | None = None) -> dict:
    """Ответ модели → ``{"candidates", "acceptance_checks", "test_cases", "warnings"}``.

    ``requirements`` — выход нарезки (нужны ``id``, ``source_id``, ``kind``). Без него линза работает,
    но не знает исходных номеров и не может проверить, что исполнены все строки приёмки.
    """
    data = data or {}
    reqs = list(requirements or [])
    index = _req_index(reqs)
    warnings: list[str] = []

    checks: list[dict] = []
    seen_rows: set[tuple] = set()
    for raw in data.get("acceptance_checks") or []:
        if not isinstance(raw, Mapping):
            continue
        c = normalize_check(raw)
        c["row_requirement_id"] = resolve_row_id(c, reqs)
        # Ключ — строка документа: без таблицы требований модель даёт всем строкам одинаковый «ID».
        key = (c["row_line"],) if c["row_line"] else (c["row_requirement_id"], _norm(c["row_quote"]))
        if key in seen_rows:
            warnings.append(f"{STAGE}: строка приёмки {c['row_requirement_id'] or key[0]} исполнена дважды, "
                            "оставлена первая запись")
            continue
        seen_rows.add(key)
        checks.append(c)
    order = {rid: i for i, rid in enumerate(acceptance_rows(reqs))}
    checks.sort(key=lambda c: (order.get(c["row_requirement_id"], len(order)), c["row_line"] or 0))
    for rid in missing_rows(checks, reqs):
        warnings.append(f"{STAGE}: строка критериев приёмки {rid} не исполнена моделью")

    candidates: list[dict] = []
    flagged: set[str] = set()
    for c in checks:
        cand = check_to_candidate(c, index)
        if cand:
            candidates.append(cand)
            flagged.add(c["row_requirement_id"])

    model_cands = [normalize_candidate(x) for x in data.get("candidates") or [] if isinstance(x, Mapping)]
    kept = [c for c in model_cands if not _duplicates_check(c, flagged)]
    if len(kept) > MAX_MODEL_CANDIDATES:
        warnings.append(f"{STAGE}: кандидатов модели {len(kept)}, оставлено {MAX_MODEL_CANDIDATES}")
        rank = {"critical": 0, "major": 1, "minor": 2}
        kept = sorted(kept, key=lambda c: rank[c["severity"]])[:MAX_MODEL_CANDIDATES]
    candidates.extend(kept)

    tests = [normalize_test_case(x) for x in data.get("test_cases") or [] if isinstance(x, Mapping)]
    tests = [t for t in tests if t["title"] or t["then"]]
    if len(tests) > MAX_TEST_CASES:
        warnings.append(f"{STAGE}: тест-кейсов {len(tests)}, оставлено {MAX_TEST_CASES}")
        tests = tests[:MAX_TEST_CASES]
    for i, t in enumerate(tests, 1):
        t["id"] = f"T-{i:02d}"
    tests = [{"id": t["id"], **{k: v for k, v in t.items() if k != "id"}} for t in tests]

    return {"candidates": candidates, "acceptance_checks": checks, "test_cases": tests, "warnings": warnings}


def retry_instruction(missing: list[str]) -> str:
    """Добавка к заданию для повторного вызова, если модель пропустила строки приёмки."""
    return ("\n\n### Дополнительно\nВ прошлом ответе не исполнены строки критериев приёмки: "
            + ", ".join(missing) + ". Сделай acceptance_checks только для них; candidates и test_cases — пустые.")


def focus_instruction(rows: list[str], rest: int) -> str:
    """Добавка к первому вызову, если строк приёмки больше :data:`BATCH_ROWS`: остальные идут отдельными вызовами."""
    return ("\n\n### Дополнительно\nВ этом ответе исполни только строки критериев приёмки "
            + ", ".join(rows) + f". Остальные {rest} строк будут исполнены отдельным запросом. "
            "candidates и test_cases — по всему документу, как обычно.")


BATCH_ROWS = 10


def _ask_rows(ctx: Any, system: str, user: str, rows: list[str], stage: str, warnings: list[str]) -> list:
    try:
        extra = ctx.llm.ask(stage, system, user + retry_instruction(rows), SCHEMA) or {}
    except Exception as exc:  # дополнительный вызов — улучшение, а не условие работы линзы
        warnings.append(f"{STAGE}: строки приёмки {', '.join(rows)} не исполнены: {exc}")
        return []
    return [c for c in extra.get("acceptance_checks") or [] if isinstance(c, Mapping)]


def run(ctx: Any) -> dict:
    """Запуск линзы на контексте каркаса v2 (ctx.prompt, ctx.llm, ctx.requirements).

    Вызовы: один основной; если строк приёмки больше BATCH_ROWS — по одному на каждые следующие BATCH_ROWS строк
    (ответ не упирается в лимит вывода); затем не больше одного повтора по строкам, которые модель пропустила.
    """
    system, user = ctx.prompt(STAGE)
    reqs = list(getattr(ctx, "requirements", None) or [])
    rows = acceptance_rows(reqs)
    first, later = rows[:BATCH_ROWS], rows[BATCH_ROWS:]
    warnings: list[str] = []
    main_user = user + focus_instruction(first, len(later)) if later else user
    data = dict(ctx.llm.ask(STAGE, system, main_user, SCHEMA) or {})
    checks = [c for c in data.get("acceptance_checks") or [] if isinstance(c, Mapping)]
    for i in range(0, len(later), BATCH_ROWS):
        checks += _ask_rows(ctx, system, user, later[i:i + BATCH_ROWS], f"{STAGE}_rows", warnings)
    missing = missing_rows([normalize_check(c) for c in checks], reqs)
    if missing:
        checks += _ask_rows(ctx, system, user, missing[:BATCH_ROWS], f"{STAGE}_retry", warnings)
    data["acceptance_checks"] = checks
    out = postprocess(data, reqs)
    out["warnings"] = warnings + out["warnings"]
    return out
