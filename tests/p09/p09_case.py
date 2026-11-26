"""Синтетические отчёты по контракту v1 (431f76d) на текстах учебного кейса (части A и B).

Каждый отчёт проходит ``contracts.validate(report)`` и ``contracts.evidence_errors(report) == []``.
Опоры вычисляются из текста блока, поэтому ``block.text[start:end] == quote`` выполняется по
построению. Id блоков (b0001…), требований и замечаний назначаются в каждой редакции заново, как в
движке: одинаковый id в двух редакциях может означать разный текст.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable

ROOT = "Уведомление о расходах по карте"
A = "Часть A. Новый функционал"
B = "Часть B. REST API"
S_FT = (A, "Функциональные требования")
S_NFR = (A, "Нефункциональные требования")
S_DATA = (A, "Требования к данным")
S_INT = (A, "Требования к интеграции")
S_RULES = (B, "Особые правила")

# --- тексты кейса (BCC-HUB/ai-requirements-validator-task @ 928c1aa, docs/requirements.md) ---
F1 = (
    "Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно. "
    "По умолчанию уведомление выключено."
)
F2 = (
    "Месяц определяется по дате совершения покупки в Алматы. В расходы входят проведённые покупки. "
    "Возврат уменьшает расходы месяца исходной покупки. Переводы и снятие наличных исключаются."
)
F3 = (
    "Когда расходы переходят от суммы ниже порога к сумме, равной порогу или выше, клиент получает push. "
    "На карту приходится максимум один такой push за календарный месяц."
)
F4 = (
    "При изменении порога накопленная сумма сохраняется. Если она ниже нового порога, следующее достижение "
    "вызывает push независимо от истории предыдущей настройки."
)
NFR = "Сервис передаёт push на отправку в течение минуты после получения события."
DATA = (
    "Хранить идентификатор карты, месяц, идентификатор операции, сумму покупки в тиынах, "
    "признак отправки и порог в тенге."
)
INT = (
    "Приложение читает и сохраняет настройки через дочерний документ «Уведомление о расходах по карте — REST API». "
    "Повторная доставка одного события процессинга сохраняет исходный итог."
)
RULE1 = "Целое число тенге, обе границы включены."
RULE2 = "Повторное сохранение заменяет действующую настройку."
RULE3 = "Изменение порога сохраняет накопленные расходы."

# --- правки ---------------------------------------------------------------------------------
F4_FIXED = (
    "При изменении порога накопленная сумма сохраняется. Если она ниже нового порога и в текущем календарном "
    "месяце push по карте ещё не отправлялся, следующее достижение вызывает push."
)
F4_PART1 = "При изменении порога накопленная сумма сохраняется."
F4_PART2 = (
    "Если накопленная сумма ниже нового порога, следующее достижение вызывает push независимо от истории "
    "предыдущей настройки."
)
F2_FIXED = (
    "Месяц определяется по дате совершения покупки по времени Алматы (UTC+5). В расходы входят проведённые "
    "покупки. Возврат уменьшает расходы месяца исходной покупки. Переводы и снятие наличных исключаются."
)
F5_NEW = "Push содержит сумму покупки и остаток бюджета на месяц."
FIX_QUOTE = "в текущем календарном месяце push по карте ещё не отправлялся"
WITNESS_INPUT = (
    "Push за январь уже отправлен при пороге 50 000 ₸; 15 января клиент меняет порог на 60 000 ₸; "
    "расходы достигают 60 000 ₸"
)
CONFLICT_QUOTES = [
    "максимум один такой push за календарный месяц",
    "следующее достижение вызывает push независимо от истории предыдущей настройки",
]

Para = tuple  # (section, source_id | None, text, req_id | None)


def body(sid, text: str) -> str:
    return f"{sid}. {text}" if sid else text


def _build(paras: Iterable[Para]) -> tuple[list, list]:
    lines = [f"# {ROOT}", ""]
    blocks = [{"id": "b0001", "kind": "heading", "section": [], "text": ROOT, "loc": {"line_start": 1, "line_end": 1}}]
    last: tuple = ()
    for section, sid, text, _rid in paras:
        for depth in range(len(section)):
            if tuple(last[: depth + 1]) != tuple(section[: depth + 1]):
                lines += ["#" * (depth + 2) + " " + section[depth], ""]
                blocks.append(
                    {
                        "id": f"b{len(blocks) + 1:04d}",
                        "kind": "heading",
                        "section": [ROOT, *section[:depth]],
                        "text": section[depth],
                        "loc": {"line_start": len(lines) - 1, "line_end": len(lines) - 1},
                    }
                )
        last = tuple(section)
        blocks.append(
            {
                "id": f"b{len(blocks) + 1:04d}",
                "kind": "list_item" if sid else "paragraph",
                "section": [ROOT, *section],
                "text": body(sid, text),
                "loc": {"line_start": len(lines) + 1, "line_end": len(lines) + 1},
            }
        )
        lines += [body(sid, text), ""]
    return lines, blocks


def markdown(paras: Iterable[Para]) -> str:
    """Исходный Markdown той же редакции (SHA-256 его байтов равен document(paras)["id"])."""
    return "\n".join(_build(paras)[0])


def document(paras: Iterable[Para], *, warnings: Iterable = ()) -> dict:
    """Markdown: заголовки — блоки heading, абзац — paragraph/list_item; строки с 1."""
    lines, blocks = _build(paras)
    raw = "\n".join(lines).encode("utf-8")
    warns = [w if isinstance(w, dict) else {"code": "partial_read", "message": w} for w in warnings]
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": ROOT,
        "format": "markdown",
        "source_name": "tz.md",
        "blocks": blocks,
        "warnings": warns,
    }


def ev(doc: dict, quote: str, nth: int = 0) -> dict:
    seen = 0
    for b in doc["blocks"]:
        if b["kind"] == "heading":
            continue
        p = b["text"].find(quote)
        while p >= 0:
            if seen == nth:
                return {"block_id": b["id"], "start": p, "end": p + len(quote), "quote": quote}
            seen += 1
            p = b["text"].find(quote, p + 1)
    raise AssertionError(f"цитата не найдена: {quote!r}")


def requirements(doc: dict, paras: Iterable[Para], *, review: dict | None = None) -> list:
    """Как у движка: текст требования — весь абзац вместе с номером («Ф-1. …»)."""
    out = []
    for section, sid, text, rid in paras:
        if rid is None:
            continue
        e = ev(doc, body(sid, text))
        status, reason = (review or {}).get(rid, ("reviewed", None))
        out.append(
            {
                "id": rid,
                "source_id": sid,
                "text": body(sid, text),
                "block_ids": [e["block_id"]],
                "evidence": [e],
                "kind": "functional",
                "section": [ROOT, *section],
                "review_status": status,
                "review_reason": reason,
            }
        )
    return out


def finding(
    fid: str,
    doc: dict,
    *,
    req_ids: list,
    kind: str,
    criterion: str,
    severity: str,
    title: str,
    quotes: list,
    scope: str = "requirement",
    impact: str = "",
    witness: dict | None = None,
    inspected: list | None = None,
    status: str = "confirmed",
) -> dict:
    f = {
        "id": fid,
        "scope": scope,
        "kind": kind,
        "criterion": criterion,
        "severity": severity,
        "title": title,
        "impact": impact or f"Риск неверной реализации: {title.lower()}",
        "req_ids": list(req_ids),
        "hints": [{"block_id": ev(doc, q)["block_id"], "quote": q} for q in quotes],
        "evidence": [ev(doc, q) for q in quotes],
        "status": status,
        "anchor_status": "supported",
        "meaning_status": "confirmed",
        "recommendation": "Уточнить формулировку.",
        "blocks": ["development", "testing"],
        "witness": witness,
        "inspected_block_ids": inspected or [],
    }
    if severity == "critical":
        f["blocked_decision"] = "Ожидаемое поведение в сценарии"
    return f


def check(
    req_id: str,
    criterion: str,
    status: str,
    *,
    finding_ids=(),
    reason: str = "",
    source: str = "llm",
    doc: dict | None = None,
    quotes: Iterable[str] = (),
    scenario: str | None = None,
) -> dict:
    """Check по контракту; scenario и evidence — расширение для перепроверки (additionalProperties)."""
    c = {
        "req_id": req_id,
        "criterion": criterion,
        "status": status,
        "reason": reason or f"{criterion}: {status}",
        "finding_ids": list(finding_ids),
        "source": source,
    }
    if scenario is not None:
        c["scenario"] = scenario
    if doc is not None and quotes:
        c["evidence"] = [ev(doc, q) for q in quotes]
    return c


# Критерий проверки требования, в которой проявляется замечание набора (как в contracts/examples).
CHECK_CRITERION = {"set_consistent": "correct", "set_complete": "complete"}


def issue_checks(findings: list) -> list:
    """Проверки «issue», как их пишет движок: требование × критерий → finding_ids."""
    out: dict = {}
    for f in findings:
        crit = CHECK_CRITERION.get(f["criterion"], f["criterion"])
        for rid in f["req_ids"]:
            c = out.setdefault((rid, crit), check(rid, crit, "issue", reason=f["title"]))
            c["finding_ids"].append(f["id"])
    return list(out.values())


def run(doc: dict, *, status: str = "complete", run_id: str = "run-1", mode: str = "mock") -> dict:
    ok = status == "complete"
    return {
        "run_id": run_id,
        "parent_run_id": None,
        "source_sha256": doc["id"],
        "source_name": "tz.md",
        "agent_version": "0.1.0",
        "agent_commit": None,
        "provider": "mock",
        "model": "mock-1",
        "mode": mode,
        "status": status,
        "status_reasons": [] if ok else ["сбой этапа cross"],
        "started_at": "2026-11-26T10:00:00Z",
        "finished_at": "2026-11-26T10:00:05Z",
        "duration_s": 5.0,
        "calls": {"physical": 6, "cache_hits": 0, "failed": 0 if ok else 1, "retries": 0},
        "tokens": {"input": 0, "output": 0},
        "stages": [{"name": "cross", "status": "ok" if ok else "failed", "calls": 1, "cache_hits": 0, "reason": None}],
        "incomplete_stages": [] if ok else ["cross"],
        "evidence_audit": {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": "фикстура p09"},
    }


def report(
    doc: dict,
    reqs: list,
    findings: list,
    *,
    checks: Iterable[dict] | None = None,
    status: str = "complete",
    run_id: str = "run-1",
    questions: Iterable[dict] = (),
    decisions: Iterable[dict] = (),
) -> dict:
    checks = list(issue_checks(findings) if checks is None else checks)
    sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")}
    blocked = [f["id"] for f in findings if f["severity"] == "critical"]
    ready = {"status": "not_ready" if blocked else "ready", "reasons": [], "finding_ids": blocked}
    return {
        "schema_version": "1.0",
        "run": run(doc, status=status, run_id=run_id),
        "document": doc,
        "requirements": reqs,
        "checks": checks,
        "findings": findings,
        "facts": [],
        "coverage": [],
        "questions": list(questions),
        "checklist": [],
        "test_cases": [],
        "decisions": list(decisions),
        "diff": None,
        "verdict": {"development": dict(ready), "testing": dict(ready), "first_actions": []},
        "summary": {
            "requirements": len(reqs),
            "reviewed_requirements": len(reqs),
            "findings": len(findings),
            "by_severity": sev,
            "by_status": {s: sum(1 for f in findings if f["status"] == s) for s in ("confirmed", "needs_review")},
            "critical_ids": blocked,
            "checks": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "issue", "unknown", "na")},
        },
        "warnings": [],
        "excluded": [],
        "rejected": [],
    }


# --- замечания кейса ------------------------------------------------------------------------
SPECS = {
    "conflict": dict(
        reqs=("F3", "F4"),
        kind="conflict",
        criterion="set_consistent",
        severity="critical",
        scope="set",
        title="Ф-3 и Ф-4 дают разные исходы при смене порога после push",
        quotes=CONFLICT_QUOTES,
        impact="Разработчик и тестировщик получат противоположные ожидания.",
    ),
    "tz": dict(
        reqs=("F2",),
        kind="ambiguity",
        criterion="unambiguous",
        severity="major",
        title="Не указан часовой пояс «в Алматы» для границы месяца",
        quotes=["по дате совершения покупки в Алматы"],
    ),
    "nfr": dict(
        reqs=("NFR",),
        kind="unverifiable",
        criterion="verifiable",
        severity="major",
        title="НФТ «в течение минуты» без точки отсчёта и перцентиля",
        quotes=["в течение минуты после получения события"],
    ),
    "read": dict(
        reqs=("INT",),
        kind="omission",
        criterion="set_complete",
        severity="critical",
        scope="set",
        title="Нет метода чтения настроек, хотя приложение их читает",
        quotes=["Приложение читает и сохраняет настройки"],
    ),
    "units": dict(
        reqs=("DATA",),
        kind="ambiguity",
        criterion="unambiguous",
        severity="major",
        title="Сумма в тиынах, порог в тенге: нет правила пересчёта",
        quotes=["сумму покупки в тиынах", "порог в тенге"],
    ),
    "dup": dict(
        reqs=("F4", "RULE3"),
        kind="duplicate",
        criterion="necessary",
        severity="minor",
        scope="set",
        title="Ф-4 дублирует п. 3 «Особых правил»",
        quotes=["При изменении порога накопленная сумма сохраняется", RULE3],
    ),
    "single": dict(
        reqs=("F4",),
        kind="non_singular",
        criterion="singular",
        severity="minor",
        title="Ф-4 объединяет два обязательства в одном пункте",
        quotes=[F4],
    ),
}
V1_NAMES = ("conflict", "tz", "nfr", "read", "units")
QUESTION_Q1 = {
    "id": "Q-001",
    "finding_ids": ["F-1"],
    "prompt": "Сбрасывает ли смена порога месячный лимит push?",
    "options": ["Да", "Нет, лимит один push в месяц сохраняется"],
    "affected_req_ids": ["R-3", "R-4"],
}


def witness(doc: dict, a: str = CONFLICT_QUOTES[0], b: str = CONFLICT_QUOTES[1], inp: str = WITNESS_INPUT) -> dict:
    return {
        "input": inp,
        "outcome_a": "push не отправляется (лимит месяца, Ф-3)",
        "outcome_b": "push отправляется (Ф-4)",
        "evidence_a": ev(doc, a),
        "evidence_b": ev(doc, b),
    }


def make_findings(
    doc: dict,
    ids: dict,
    names: Iterable[str] = V1_NAMES,
    *,
    prefix: str = "F",
    numbering: dict | None = None,
    **overrides: dict,
) -> list:
    """ids: логическое имя требования -> id в этой редакции; overrides: имя -> поля замечания."""
    out = []
    for k, name in enumerate(names, 1):
        spec = dict(SPECS[name])
        spec.update(overrides.get(name, {}))
        fid = (numbering or {}).get(name, f"{prefix}-{k}")
        reqs = [ids.get(r, r) for r in spec.pop("reqs")]
        if spec["kind"] == "conflict" and "witness" not in spec:
            spec["witness"] = witness(doc, *spec["quotes"][:2])
        if spec["kind"] == "omission":
            spec["inspected"] = [b["id"] for b in doc["blocks"]]
        out.append(finding(fid, doc, req_ids=reqs, **spec))
    return out


def v1_paras(*, rules: bool = False) -> list:
    p = [
        (S_FT, "Ф-1", F1, "R-1"),
        (S_FT, "Ф-2", F2, "R-2"),
        (S_FT, "Ф-3", F3, "R-3"),
        (S_FT, "Ф-4", F4, "R-4"),
        (S_NFR, None, NFR, "R-5"),
        (S_DATA, None, DATA, "R-6"),
        (S_INT, None, INT, "R-7"),
    ]
    if rules:
        p += [(S_RULES, "1", RULE1, "R-8"), (S_RULES, "2", RULE2, "R-9"), (S_RULES, "3", RULE3, "R-10")]
    return p


V1_IDS = {
    "F1": "R-1",
    "F2": "R-2",
    "F3": "R-3",
    "F4": "R-4",
    "NFR": "R-5",
    "DATA": "R-6",
    "INT": "R-7",
    "RULE1": "R-8",
    "RULE2": "R-9",
    "RULE3": "R-10",
}


def v1_report(*, rules: bool = False, names: Iterable[str] = V1_NAMES, questions=()) -> dict:
    paras = v1_paras(rules=rules)
    doc = document(paras)
    return report(doc, requirements(doc, paras), make_findings(doc, V1_IDS, names), run_id="run-1", questions=questions)


def replace(paras: list, mapping: dict) -> list:
    """Заменить тексты абзацев: {старый текст: новый текст | None (удалить)}."""
    out = []
    for s, sid, t, rid in paras:
        if t in mapping and mapping[t] is None:
            continue
        out.append((s, sid, mapping.get(t, t), rid))
    return out


def clone(obj):
    return copy.deepcopy(obj)


def assert_valid_report(rep: dict) -> None:
    from bcc_review.contracts import evidence_errors, validate

    validate(rep)
    assert evidence_errors(rep) == []


def assert_partition(diff: dict, prev: dict, cur: dict) -> None:
    """Каждое старое и каждое новое замечание — ровно в одной записи; Diff валиден по контракту."""
    from bcc_review.contracts import validate

    validate(diff, "Diff")
    olds = [i for k in ("resolved", "persisting", "unassessed") for e in diff[k] for i in e["old_ids"]]
    news = [i for k in ("persisting", "introduced", "unassessed") for e in diff[k] for i in e["new_ids"]]
    assert sorted(olds) == sorted(f["id"] for f in prev["findings"]), olds
    assert sorted(news) == sorted(f["id"] for f in cur["findings"]), news
    assert all(not e["old_ids"] for e in diff["introduced"])
    assert all(not e["new_ids"] for e in diff["resolved"])
    blocks = {b["id"]: b["text"] for b in cur["document"]["blocks"]}
    for k in ("resolved", "persisting", "introduced", "unassessed"):
        for e in diff[k]:
            assert e["status"] == k and e["reason"] and e["reason_code"]
            assert "old_evidence" in e and "new_evidence" in e and "view" in e
            for x in e["evidence"]:  # Evidence записи — из текущей редакции и проверяемы по её блокам
                assert blocks[x["block_id"]][x["start"] : x["end"]] == x["quote"]


def by_old(diff: dict) -> dict:
    """old_id -> (status, entry)."""
    out = {}
    for k in ("resolved", "persisting", "unassessed"):
        for e in diff[k]:
            for i in e["old_ids"]:
                out[i] = (k, e)
    return out


# --- демо-пара для №13/№15: все четыре статуса в одном сравнении -----------------------------
DATA_FIXED = (
    "Хранить идентификатор карты, месяц, идентификатор операции, сумму покупки в тиынах, признак отправки "
    "и порог в тенге; при сравнении порог переводится в тиыны умножением на 100."
)


def demo_pair() -> tuple[dict, dict]:
    """Прошлая редакция v1 и новая: Ф-4 исправлен по ответу на Q-001 (сценарий перепроверен),
    данные дополнены без перепроверки, раздел НФТ удалён, у Ф-2 выросла серьёзность,
    добавлен Ф-5 с новым дефектом."""
    q = {
        "id": "Q-001",
        "finding_ids": ["F-1"],
        "prompt": "Сбрасывает ли смена порога месячный лимит push?",
        "options": ["Да", "Нет, лимит один push в месяц сохраняется"],
        "affected_req_ids": ["R-3", "R-4"],
    }
    prev = v1_report(questions=[q])
    paras = []
    for s, sid, t, rid in replace(v1_paras(), {F4: F4_FIXED, DATA: DATA_FIXED, NFR: None}):
        paras.append((s, sid, t, rid.replace("R", "S")))
        if sid == "Ф-4":
            paras.append((S_FT, "Ф-5", F5_NEW, "S-8"))
    doc = document(paras)
    ids = {"F1": "S-1", "F2": "S-2", "F3": "S-3", "F4": "S-4", "DATA": "S-6", "INT": "S-7"}
    fs = make_findings(
        doc,
        ids,
        ("tz", "read"),
        prefix="G",
        tz={"severity": "critical", "title": "Граница месяца без часового пояса ломает критерий приёмки №2"},
    )
    fs.append(
        finding(
            "G-3",
            doc,
            req_ids=["S-8"],
            kind="ambiguity",
            criterion="unambiguous",
            severity="major",
            title="«Остаток бюджета» не определён",
            quotes=["остаток бюджета на месяц"],
        )
    )
    checks = issue_checks(fs) + [
        check(
            "S-3",
            "correct",
            "pass",
            reason="Ф-3 и новый Ф-4 дают один исход: повторного push нет",
            source="diff_recheck",
            scenario=WITNESS_INPUT,
            doc=doc,
            quotes=[CONFLICT_QUOTES[0]],
        ),
        check(
            "S-4",
            "correct",
            "pass",
            reason="Ф-4 ограничен месячным лимитом push",
            source="diff_recheck",
            scenario=WITNESS_INPUT,
            doc=doc,
            quotes=[FIX_QUOTE],
        ),
    ]
    f4_block = ev(prev["document"], F4)
    decision = {
        "question_id": "Q-001",
        "source_sha256": prev["document"]["id"],
        "answer": "Лимит одного push за календарный месяц главнее смены порога",
        "edits": [
            {
                "block_id": f4_block["block_id"],
                "start": f4_block["start"],
                "end": f4_block["end"],
                "old": F4,
                "new": F4_FIXED,
            }
        ],
    }
    cur = report(doc, requirements(doc, paras), fs, checks=checks, run_id="run-2", decisions=[decision])
    return prev, cur
