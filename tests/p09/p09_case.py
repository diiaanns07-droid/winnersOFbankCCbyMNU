"""Синтетические отчёты по контракту v1 на текстах учебного кейса (части A и B).

Опоры (Evidence) вычисляются из текста блока, поэтому
block.text[start:end] == quote выполняется по построению. Id блоков,
требований и замечаний задаются на каждую редакцию отдельно, как в
реальном движке: они зависят от версии.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable

# --- разделы -------------------------------------------------------------
A = "Часть A. Новый функционал"
B = "Часть B. REST API"
S_UI = (A, "Дизайн процесса UI")
S_FT = (A, "Функциональные требования")
S_NFR = (A, "Нефункциональные требования")
S_DATA = (A, "Требования к данным")
S_INT = (A, "Требования к интеграции")
S_RULES = (B, "Особые правила")

# --- тексты кейса (docs/requirements.md @ 928c1aa) ----------------------
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

# --- правки -------------------------------------------------------------
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

WITNESS_INPUT = (
    "Push за январь уже отправлен при пороге 50 000 ₸; 15 января клиент меняет порог на 60 000 ₸; "
    "расходы достигают 60 000 ₸"
)

Para = tuple  # (section, source_id | None, text, req_id | None)


def document(paras: Iterable[Para], *, prefix: str = "b", warnings: Iterable[str] = ()) -> dict:
    """Markdown-документ: заголовок раздела при смене, абзац = блок. Строки с 1."""
    lines = ["# Уведомление о расходах по карте", ""]
    blocks = []
    last: tuple | None = None
    for i, (section, sid, text, _rid) in enumerate(paras, 1):
        if section != last:
            for depth, head in enumerate(section, 2):
                if last is None or depth - 2 >= len(last) or last[depth - 2] != head:
                    lines += ["#" * depth + " " + head, ""]
            last = section
        body = f"{sid}. {text}" if sid else text
        blocks.append(
            {
                "id": f"{prefix}{i:02d}",
                "kind": "paragraph",
                "section": ["Уведомление о расходах по карте", *section],
                "text": body,
                "loc": {"line": len(lines) + 1},
            }
        )
        lines += [body, ""]
    raw = "\n".join(lines).encode("utf-8")
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": "Уведомление о расходах по карте",
        "format": "md",
        "blocks": blocks,
        "warnings": list(warnings),
    }


def ev(doc: dict, quote: str, nth: int = 0) -> dict:
    seen = 0
    for b in doc["blocks"]:
        p = b["text"].find(quote)
        while p >= 0:
            if seen == nth:
                return {"block_id": b["id"], "start": p, "end": p + len(quote), "quote": quote}
            seen += 1
            p = b["text"].find(quote, p + 1)
    raise AssertionError(f"цитата не найдена: {quote!r}")


def requirements(doc: dict, paras: Iterable[Para]) -> list:
    out = []
    for _section, sid, text, rid in paras:
        if rid is None:
            continue
        e = ev(doc, text)
        out.append({"id": rid, "source_id": sid, "text": text, "block_ids": [e["block_id"]], "evidence": [e]})
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
        "status": status,
        "scope": scope,
        "kind": kind,
        "criterion": criterion,
        "severity": severity,
        "title": title,
        "impact": impact,
        "req_ids": list(req_ids),
        "hints": [{"block_id": ev(doc, q)["block_id"], "quote": q} for q in quotes],
        "evidence": [ev(doc, q) for q in quotes],
    }
    if witness is not None:
        f["witness"] = witness
    if inspected is not None:
        f["inspected_block_ids"] = inspected
    return f


def check(
    cid: str,
    req_ids: list,
    criterion: str,
    status: str,
    *,
    doc: dict | None = None,
    quotes: Iterable[str] = (),
    scenario: str | None = None,
    reason: str = "",
    scope: str = "requirement",
) -> dict:
    c = {
        "id": cid,
        "scope": scope,
        "req_ids": list(req_ids),
        "criterion": criterion,
        "status": status,
        "reason": reason,
        "evidence": [ev(doc, q) for q in quotes] if doc else [],
    }
    if scenario is not None:
        c["scenario"] = scenario
    return c


def report(
    doc: dict,
    reqs: list,
    findings: list,
    *,
    checks: Iterable[dict] = (),
    status: str = "complete",
    decisions: Iterable[dict] = (),
    coverage: dict | None = None,
    calls: int = 6,
) -> dict:
    return {
        "schema_version": "1.0",
        "run": {
            "source_sha256": doc["id"],
            "agent_version": "test",
            "provider": "mock",
            "model": "stub",
            "started_at": "2026-11-26T10:00:00Z",
            "calls": calls,
            "status": status,
            "mode": "mock",
            "evidence_audit": {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": "фикстура"},
        },
        "document": doc,
        "requirements": reqs,
        "checks": list(checks),
        "findings": findings,
        "coverage": coverage or {},
        "questions": [],
        "checklist": [],
        "test_cases": [],
        "decisions": list(decisions),
        "diff": None,
        "verdict": {"development": "blocked", "testing": "blocked", "first_actions": []},
        "warnings": [],
    }


# --- базовая редакция v1 -------------------------------------------------


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


def witness(
    doc: dict,
    a: str = "максимум один такой push за календарный месяц",
    b: str = "следующее достижение вызывает push независимо от истории предыдущей настройки",
) -> dict:
    return {
        "input": WITNESS_INPUT,
        "outcome_a": "push не отправляется (лимит месяца, Ф-3)",
        "outcome_b": "push отправляется (Ф-4)",
        "evidence_a": ev(doc, a),
        "evidence_b": ev(doc, b),
    }


CONFLICT_QUOTES = [
    "максимум один такой push за календарный месяц",
    "следующее достижение вызывает push независимо от истории предыдущей настройки",
]

SPECS = {
    "conflict": dict(
        reqs=("F3", "F4"),
        kind="conflict",
        criterion="И8",
        severity="critical",
        scope="set",
        title="Ф-3 и Ф-4 дают разные исходы при смене порога после push",
        quotes=CONFLICT_QUOTES,
        impact="Разработчик и тестировщик получат противоположные ожидания.",
    ),
    "tz": dict(
        reqs=("F2",),
        kind="ambiguity",
        criterion="И3",
        severity="major",
        title="Не указан часовой пояс «в Алматы» для границы месяца",
        quotes=["по дате совершения покупки в Алматы"],
    ),
    "nfr": dict(
        reqs=("NFR",),
        kind="unverifiable",
        criterion="И7",
        severity="major",
        title="НФТ «в течение минуты» без точки отсчёта и перцентиля",
        quotes=["в течение минуты после получения события"],
    ),
    "read": dict(
        reqs=("INT",),
        kind="omission",
        criterion="Н1",
        severity="critical",
        scope="set",
        title="Нет метода чтения настроек, хотя приложение их читает",
        quotes=["Приложение читает и сохраняет настройки"],
    ),
    "units": dict(
        reqs=("DATA",),
        kind="ambiguity",
        criterion="И3",
        severity="major",
        title="Сумма в тиынах, порог в тенге: нет правила пересчёта",
        quotes=["сумму покупки в тиынах", "порог в тенге"],
    ),
    "dup": dict(
        reqs=("F4", "RULE3"),
        kind="duplicate",
        criterion="И1",
        severity="minor",
        scope="set",
        title="Ф-4 дублирует п. 3 «Особых правил»",
        quotes=["При изменении порога накопленная сумма сохраняется", RULE3],
    ),
    "single": dict(
        reqs=("F4",),
        kind="non_singular",
        criterion="И5",
        severity="minor",
        title="Ф-4 объединяет два обязательства в одном пункте",
        quotes=[F4],
    ),
}
V1_NAMES = ("conflict", "tz", "nfr", "read", "units")


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
        reqs = [ids[r] if r in ids else r for r in spec.pop("reqs")]
        extra = {}
        if spec["kind"] == "conflict" and "witness" not in spec:
            extra["witness"] = witness(doc, *spec["quotes"])
        if spec["kind"] == "omission":
            extra["inspected"] = [b["id"] for b in doc["blocks"]]
        if "witness" in spec:
            extra["witness"] = spec.pop("witness")
        out.append(finding(fid, doc, req_ids=reqs, **spec, **extra))
    return out


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


def v1_report(*, rules: bool = False, names: Iterable[str] = V1_NAMES) -> dict:
    paras = v1_paras(rules=rules)
    doc = document(paras)
    return report(doc, requirements(doc, paras), make_findings(doc, V1_IDS, names))


def assert_partition(diff: dict, prev: dict, cur: dict) -> None:
    """Каждое старое и каждое новое замечание встречается ровно в одной записи."""
    olds = [i for k in ("resolved", "persisting", "unassessed") for e in diff[k] for i in e["old_ids"]]
    news = [i for k in ("persisting", "introduced", "unassessed") for e in diff[k] for i in e["new_ids"]]
    assert sorted(olds) == sorted(f["id"] for f in prev["findings"]), olds
    assert sorted(news) == sorted(f["id"] for f in cur["findings"]), news
    assert all(not e["old_ids"] for e in diff["introduced"])
    assert all(not e["new_ids"] for e in diff["resolved"])
    for k in ("resolved", "persisting", "introduced", "unassessed"):
        for e in diff[k]:
            assert e["status"] == k and e["reason"] and e["reason_code"]
            assert "old_evidence" in e and "new_evidence" in e and "view" in e


def by_old(diff: dict) -> dict:
    """old_id -> (status, entry)."""
    out = {}
    for k in ("resolved", "persisting", "unassessed"):
        for e in diff[k]:
            for i in e["old_ids"]:
                out[i] = (k, e)
    return out


def clone(obj):
    return copy.deepcopy(obj)


# --- демо-пара для №13/№15: все четыре статуса в одном сравнении ---------
DATA_FIXED = (
    "Хранить идентификатор карты, месяц, идентификатор операции, сумму покупки в тиынах, признак отправки "
    "и порог в тенге; при сравнении порог переводится в тиыны умножением на 100."
)
NFR_LOST = "Раздел «Нефункциональные требования» не распознан: текст набран картинкой на странице 2"


def demo_pair() -> tuple[dict, dict]:
    """Прошлая редакция v1 и новая: Ф-4 исправлен по решению D-1, данные дополнены без перепроверки,
    НФТ выпали из извлечения, тиражирован Ф-2 с повышенной серьёзностью, добавлен Ф-5 с дефектом."""
    prev = v1_report()
    prev["decisions"] = []
    paras = []
    for s, sid, t, rid in v1_paras():
        if t == NFR:
            continue
        t = {F4: F4_FIXED, DATA: DATA_FIXED}.get(t, t)
        paras.append((s, sid, t, rid.replace("R", "S")))
        if sid == "Ф-4":
            paras.append((S_FT, "Ф-5", F5_NEW, "S-8"))
    doc = document(paras, prefix="c", warnings=[NFR_LOST])
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
            criterion="И3",
            severity="major",
            title="«Остаток бюджета» не определён",
            quotes=["остаток бюджета на месяц"],
        )
    )
    c1 = check(
        "C-1",
        ["S-3", "S-4"],
        "И8",
        "passed",
        doc=doc,
        scope="set",
        quotes=["в текущем календарном месяце push по карте ещё не отправлялся", CONFLICT_QUOTES[0]],
        scenario=WITNESS_INPUT,
        reason="Ф-3 и новый Ф-4 дают один исход: повторного push в месяце нет",
    )
    decisions = [
        {
            "id": "D-1",
            "question_id": "Q-1",
            "finding_ids": ["F-1"],
            "status": "accepted",
            "answer": "Лимит одного push за календарный месяц главнее смены порога",
            "edit": "Ф-4",
        }
    ]
    cur = report(doc, requirements(doc, paras), fs, checks=[c1], decisions=decisions)
    return prev, cur
