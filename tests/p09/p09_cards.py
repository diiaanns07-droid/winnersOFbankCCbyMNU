"""Канонические Report: дебетовые и корпоративные карты (два похожих дефекта, исправлен один).

Редакция 1: оба раздела независимо противоречат своим критериям приёмки. Обе находки названы
одинаково, их цитаты дословно совпадают (общие фрагменты правил и критериев). Различаются они только
источником (правило Д-1 или К-1), условием (тип карты и суммы) и исходом.

Редакция 2: разделы переставлены, требования перенумерованы (1.1, 1.2, 2.1, 2.2), id назначены заново
в порядке чтения: «R-1» теперь корпоративное правило, а не дебетовое. Исправлено только правило по
корпоративной карте («достигают» → «превышают»). У сохранившейся дебетовой находки изменена только
severity.

Результаты профильного этапа (cross, №06) сохранены в форме контракта: конфликт с witness, проверки
`correct` (issue/pass) с finding_ids и покрытие приёмкой (`coverage`: conflict/covered) с опорами.
"""

from __future__ import annotations

import copy

from p09_case import document, report, requirements

DEBIT = ("Дебетовые карты", "Функциональные требования")
DEBIT_ACC = ("Дебетовые карты", "Критерии приёмки")
CORP = ("Корпоративные карты", "Функциональные требования")
CORP_ACC = ("Корпоративные карты", "Критерии приёмки")

D_RULE = "По дебетовой карте push отправляется, когда расходы за календарный месяц достигают порога 50 000 ₸."
D_ACC = "Дебетовая карта: расходы 49 000 ₸, порог 50 000 ₸, покупка 1 000 ₸ — push не отправляется."
K_RULE = "По корпоративной карте push отправляется, когда расходы за календарный месяц достигают порога 500 000 ₸."
K_RULE_FIXED = "По корпоративной карте push отправляется, когда расходы за календарный месяц превышают порог 500 000 ₸."
K_ACC = "Корпоративная карта: расходы 499 000 ₸, порог 500 000 ₸, покупка 1 000 ₸ — push не отправляется."

TITLE = "Критерий приёмки противоречит правилу отправки push"  # одинаково у обеих находок
Q_RULE = "push отправляется, когда расходы за календарный месяц достигают порога"  # есть в обоих правилах
Q_ACC = "push не отправляется"  # есть в обоих критериях
Q_FIX = "превышают порог 500 000 ₸"

D_INPUT = "Дебетовая карта: расходы 49 000 ₸, порог 50 000 ₸, покупка 1 000 ₸"
K_INPUT = "Корпоративная карта: расходы 499 000 ₸, порог 500 000 ₸, покупка 1 000 ₸"

V1_PARAS = [
    (DEBIT, "Д-1", D_RULE, "R-1"),
    (DEBIT_ACC, "Д-КП-1", D_ACC, "R-2"),
    (CORP, "К-1", K_RULE, "R-3"),
    (CORP_ACC, "К-КП-1", K_ACC, "R-4"),
]
# переставлены разделы, новая нумерация и новые id в порядке чтения; исправлено только К-1
V2_PARAS = [
    (CORP, "1.1", K_RULE_FIXED, "R-1"),
    (CORP_ACC, "1.2", K_ACC, "R-2"),
    (DEBIT, "2.1", D_RULE, "R-3"),
    (DEBIT_ACC, "2.2", D_ACC, "R-4"),
]


def ev_in(doc: dict, near: str, quote: str) -> dict:
    """Опора quote внутри блока, содержащего near (общая цитата встречается в нескольких блоках)."""
    for b in doc["blocks"]:
        if near in b["text"] and quote in b["text"]:
            p = b["text"].find(quote)
            return {"block_id": b["id"], "start": p, "end": p + len(quote), "quote": quote}
    raise AssertionError(f"нет блока с {near!r} и {quote!r}")


def conflict(doc: dict, fid: str, rule_req: str, acc_req: str, *, debit: bool, severity: str = "critical") -> dict:
    rule, acc = (D_RULE, D_ACC) if debit else (K_RULE, K_ACC)
    who = "Д" if debit else "К"
    ev_a, ev_b = ev_in(doc, rule, Q_RULE), ev_in(doc, acc, Q_ACC)
    return {
        "id": fid,
        "scope": "set",
        "kind": "conflict",
        "criterion": "set_consistent",
        "severity": severity,
        "title": TITLE,
        "impact": "Разработчик и тестировщик получат противоположные ожидания на границе порога.",
        "blocked_decision": "Отправлять ли push, когда расходы ровно равны порогу",
        "req_ids": [rule_req, acc_req],
        "hints": [{"block_id": ev_a["block_id"], "quote": Q_RULE}, {"block_id": ev_b["block_id"], "quote": Q_ACC}],
        "evidence": [ev_a, ev_b],
        "status": "confirmed",
        "anchor_status": "supported",
        "meaning_status": "confirmed",
        "recommendation": "Согласовать правило и критерий приёмки на границе порога.",
        "blocks": ["development", "testing"],
        "witness": {
            "input": D_INPUT if debit else K_INPUT,
            "outcome_a": f"push отправляется: расходы достигли порога ({who}-1)",
            "outcome_b": f"push не отправляется (критерий приёмки {who}-КП-1)",
            "evidence_a": ev_a,
            "evidence_b": ev_b,
        },
        "inspected_block_ids": [],
        "stage": "cross",
        "source": "llm",
    }


def check(req_id: str, status: str, finding_ids=(), reason: str = "") -> dict:
    return {
        "req_id": req_id,
        "criterion": "correct",
        "status": status,
        "finding_ids": list(finding_ids),
        "reason": reason or f"correct: {status}",
        "source": "cross",
    }


def coverage(doc: dict, rule_req: str, rule_text: str, acc_req: str, acc_text: str, status: str, rule_q: str) -> dict:
    return {
        "req_id": rule_req,
        "obligation": rule_text,
        "acceptance_ids": [acc_req],
        "status": status,
        "explanation": (
            "Критерий приёмки проверяет границу порога и ожидает тот же исход, что и правило."
            if status == "covered"
            else "При одном входе правило и критерий приёмки дают разные исходы."
        ),
        "evidence": [ev_in(doc, rule_text, rule_q), ev_in(doc, acc_text, Q_ACC)],
    }


def _stamp(rep: dict, run_id: str) -> dict:
    rep["run"]["run_id"] = run_id
    rep["run"]["stages"] = [
        {"name": n, "status": "ok", "calls": 1, "cache_hits": 0, "reason": None}
        for n in ("read", "inventory", "rules", "individual", "cross", "verify_meaning", "questions", "bank")
    ]
    for r in rep["requirements"]:
        if "КП" in str(r["source_id"]) or r["source_id"] in ("1.2", "2.2"):
            r["kind"] = "acceptance"
    return rep


def cards_v1() -> dict:
    doc = document(V1_PARAS)
    fs = [conflict(doc, "F-1", "R-1", "R-2", debit=True), conflict(doc, "F-2", "R-3", "R-4", debit=False)]
    checks = [
        check("R-1", "issue", ["F-1"]),
        check("R-2", "issue", ["F-1"]),
        check("R-3", "issue", ["F-2"]),
        check("R-4", "issue", ["F-2"]),
    ]
    rep = report(doc, requirements(doc, V1_PARAS), fs, checks=checks, run_id="cards-v1")
    rep["coverage"] = [
        coverage(doc, "R-1", D_RULE, "R-2", D_ACC, "conflict", Q_RULE),
        coverage(doc, "R-3", K_RULE, "R-4", K_ACC, "conflict", Q_RULE),
    ]
    return _stamp(rep, "cards-v1")


def cards_v2(*, debit_severity: str = "major") -> dict:
    doc = document(V2_PARAS)
    fs = [conflict(doc, "F-1", "R-3", "R-4", debit=True, severity=debit_severity)]
    checks = [
        check("R-1", "pass", reason="Правило 1.1 и критерий 1.2 согласованы: при 500 000 ₸ push не отправляется"),
        check("R-2", "pass", reason="Критерий 1.2 соответствует правилу 1.1"),
        check("R-3", "issue", ["F-1"]),
        check("R-4", "issue", ["F-1"]),
    ]
    rep = report(doc, requirements(doc, V2_PARAS), fs, checks=checks, run_id="cards-v2")
    rep["coverage"] = [
        coverage(doc, "R-1", K_RULE_FIXED, "R-2", K_ACC, "covered", Q_FIX),
        coverage(doc, "R-3", D_RULE, "R-4", D_ACC, "conflict", Q_RULE),
    ]
    return _stamp(rep, "cards-v2")


def clone(obj):
    return copy.deepcopy(obj)


# --- контроли из той же второй редакции -----------------------------------------------------


def _fail(rep: dict, stages: dict) -> dict:
    """Отметить этапы как неуспешные: {имя: причина}. Прогон становится partial."""
    for st in rep["run"]["stages"]:
        if st["name"] in stages:
            st.update(status="failed", reason=stages[st["name"]])
    rep["run"]["incomplete_stages"] = [st["name"] for st in rep["run"]["stages"] if st["status"] != "ok"]
    rep["run"]["status"] = "partial" if rep["run"]["incomplete_stages"] else "complete"
    rep["run"]["status_reasons"] = [f"{k}: {v}" for k, v in stages.items()]
    return rep


def v2_profile_failed() -> dict:
    """Профильный этап cross не завершён: результатов покрытия и проверок «correct» для 1.1/1.2 нет."""
    rep = _fail(cards_v2(), {"cross": "модель не ответила на cross.coverage"})
    rep["coverage"] = [c for c in rep["coverage"] if c["req_id"] != "R-1"]
    for c in rep["checks"]:
        if c["req_id"] in ("R-1", "R-2"):
            c.update(status="unknown", reason="не проверено: этап cross не завершён")
    return rep


def v2_profile_pair_missing() -> dict:
    """Этап cross завершён, но пара 1.1 ↔ 1.2 им не оценена: покрытия нет, проверки unknown."""
    rep = cards_v2()
    rep["coverage"] = [c for c in rep["coverage"] if c["req_id"] != "R-1"]
    for c in rep["checks"]:
        if c["req_id"] in ("R-1", "R-2"):
            c.update(status="unknown", reason="пара не попала в проверку")
    return rep


def v2_corporate_unreadable() -> dict:
    """Раздел «Корпоративные карты» не прочитан (partial_read): его блоков и требований нет."""
    paras = [p for p in V2_PARAS if p[0][0] != "Корпоративные карты"]
    lost = {"code": "partial_read", "message": "Раздел «Корпоративные карты» не прочитан: страница 1 — скан без текста"}
    doc = document(paras, warnings=[lost])
    ids = {"R-3": "R-1", "R-4": "R-2"}  # движок нумерует заново то, что прочитал
    paras = [(s, sid, t, ids[r]) for s, sid, t, r in paras]
    fs = [conflict(doc, "F-1", "R-1", "R-2", debit=True, severity="major")]
    rep = report(
        doc,
        requirements(doc, paras),
        fs,
        checks=[check("R-1", "issue", ["F-1"]), check("R-2", "issue", ["F-1"])],
        run_id="cards-v2-unreadable",
    )
    rep["coverage"] = [coverage(doc, "R-1", D_RULE, "R-2", D_ACC, "conflict", Q_RULE)]
    rep = _stamp(rep, "cards-v2-unreadable")
    return _fail(rep, {"read": "partial_read: раздел «Корпоративные карты» не прочитан"})


def v2_foreign_failure() -> dict:
    """Сбой посторонних этапов (individual, bank) при завершённом профильном этапе cross."""
    return _fail(cards_v2(), {"individual": "модель не ответила", "bank": "таймаут чек-листа"})


# --- имитация ответов модели для настоящего движка (провайдер mock, локальные данные) ------------
# id пар (P-…), обязательств (1.1#1) и приёмок (R-00…) строит сам №06 на второй редакции.


def mock_script_v2() -> dict:
    """Ответы стадий cross.pairs / cross.coverage для второй редакции: К-1 исправлен, Д-1 — нет."""

    def side(bid, quote, expected):
        return {"expected": expected, "quote": quote, "block_id": bid, "constraints": []}

    debit = {
        "pair_id": "P-003",
        "verdict": "conflict",
        "title": TITLE,
        "impact": "Разработчик и тестировщик получат противоположные ожидания на границе порога.",
        "a": side("b0009", Q_RULE, "push отправляется"),
        "b": side("b0011", Q_ACC, "push не отправляется"),
        "witness": {
            "description": D_INPUT,
            "input": [
                {
                    "var": "расходы после покупки",
                    "value": "равны порогу",
                    "source": "illustrative",
                    "why": "граница порога",
                }
            ],
            "outcome_a": "push отправляется",
            "outcome_b": "push не отправляется",
            "evidence_a": {"block_id": "b0009", "quote": Q_RULE},
            "evidence_b": {"block_id": "b0011", "quote": Q_ACC},
        },
    }
    corporate = {
        "pair_id": "P-002",
        "verdict": "compatible",
        "reason": "при 500 000 ₸ расходы не превышают порог: оба пункта дают «push не отправляется»",
        "a": side("b0004", Q_FIX, "push не отправляется"),
        "b": side("b0006", Q_ACC, "push не отправляется"),
    }
    return {
        "individual": {"requirements": []},
        "verify_meaning": {"__verdicts__": "confirmed"},
        "cross.pairs": {"pairs": [corporate, debit]},
        "cross.coverage": {
            "obligations": [],
            "links": [
                {
                    "obligation_id": "1.1#1",
                    "acceptance_id": "R-002",
                    "relation": "checks",
                    "explanation": "критерий 1.2 проверяет границу порога и ожидает тот же исход",
                },
                {
                    "obligation_id": "2.1#1",
                    "acceptance_id": "R-004",
                    "relation": "contradicts",
                    "explanation": "на границе порога исходы разные",
                },
            ],
        },
    }
