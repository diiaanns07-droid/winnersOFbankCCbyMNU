"""Фикстура «две разные проблемы с одинаковой причиной» для проверки группировки.

Документ — выдержка из учебного кейса банка (Ф-2…Ф-4, НФТ, критерии приёмки).
Все четыре находки относятся к объекту «операция по карте» при условии
«покупка проведена», но это не одна проблема:

* **F-1** — месяц учёта: Ф-2 относит покупку 31.01 к январю, критерий
  приёмки №2 ждёт рост февральского счётчика. Исходы: «учтена в январе» /
  «учтена в феврале».
* **F-2** — правила отправки push: Ф-3 ограничивает один push в месяц, Ф-4
  требует push после смены порога. Исходы: «push не отправлен» /
  «push отправлен».
* **F-3** — настоящий дубль F-1 от этапа правил: та же пара опор, те же исходы,
  явная ссылка ``duplicate_of: "F-1"``.
* **F-4** — неподтверждённая находка (``needs_review``) к НФТ: та же пара
  «объект / условие», исходы не определены.

Ожидание: уникальных подтверждённых дефектов 2 (F-1 с повтором F-3 и F-2),
в Jira CSV по умолчанию 2 записи, F-4 виден в отчёте со своим статусом.
"""

from __future__ import annotations

import copy
from typing import Any

from p17_fixtures import (
    INDIVIDUAL_CRITERIA,
    _Doc,
    _finding,
    _stage,
    _summary,
    parse_markdown,
)

TITLE = "Уведомление о расходах по карте (выдержка для проверки группировки)"

SOURCE = """\
# Уведомление о расходах по карте (выдержка для проверки группировки)

## Функциональные требования

* **Ф-2.** Месяц определяется по дате совершения покупки в Алматы. В расходы входят проведённые покупки.
* **Ф-3.** Когда расходы переходят от суммы ниже порога к сумме, равной порогу или выше, клиент получает push. На карту приходится максимум один такой push за календарный месяц.
* **Ф-4.** При изменении порога накопленная сумма сохраняется. Если она ниже нового порога, следующее достижение вызывает push независимо от истории предыдущей настройки.

## Нефункциональные требования

Сервис передаёт push на отправку в течение минуты после получения события.

## Критерии приемки

| Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| Расходы 48 500 ₸, порог 50 000 ₸ | Провести покупку на 1 500 ₸ | Итог 50 000 ₸ и один push |
| Покупка 31 января в 23:58 на 4 000 ₸ | Провести 1 февраля в 00:03 по Алматы | Февральский счётчик вырос на 4 000 ₸ |
"""

OBJECT = "операция по карте"
CONDITION = "покупка проведена"


def _req(doc: _Doc, rid: str, source_id: str | None, line: int, kind: str) -> dict[str, Any]:
    ev = doc.ev(line)
    return {"id": rid, "source_id": source_id, "text": ev["quote"], "block_ids": [ev["block_id"]], "evidence": [ev],
            "hints": [], "kind": kind, "review_status": "reviewed", "review_reason": None}


def build_rootcause_report() -> dict[str, Any]:
    """Валидный Report контракта v1 с находками F-1…F-4 (см. docstring модуля)."""
    document = parse_markdown(SOURCE, TITLE)
    document["source_name"] = "card-spend-excerpt.md"
    doc = _Doc(document)
    requirements = [
        _req(doc, "R-01", "Ф-2", 5, "functional"),
        _req(doc, "R-02", "Ф-3", 6, "functional"),
        _req(doc, "R-03", "Ф-4", 7, "functional"),
        _req(doc, "R-04", None, 11, "nonfunctional"),
        _req(doc, "R-05", None, 17, "acceptance"),
        _req(doc, "R-06", None, 18, "acceptance"),
    ]

    month_a = doc.ev(5, "Месяц определяется по дате совершения покупки в Алматы.")
    month_b = doc.ev(18, "Февральский счётчик вырос на 4 000 ₸")
    month_witness = {
        "input": "Покупка совершена 31 января в 23:58, проведена 1 февраля в 00:03 по Алматы.",
        "outcome_a": "Сумма засчитана в январь: месяц — по дате совершения (Ф-2).",
        "outcome_b": "Сумма засчитана в февраль: так ждёт критерий приёмки №2.",
        "evidence_a": month_a,
        "evidence_b": month_b,
    }
    push_a = doc.ev(6, "На карту приходится максимум один такой push за календарный месяц.")
    push_b = doc.ev(7, "следующее достижение вызывает push независимо от истории предыдущей настройки")

    f1 = _finding(
        id="F-1", scope="set", kind="conflict", criterion="set_consistent", severity="critical",
        title="Месяц учёта покупки: Ф-2 относит покупку 31.01 к январю, критерий приёмки №2 — к февралю",
        impact="Расходы клиента попадут не в тот месяц: push о пороге придёт в другом месяце или не придёт; "
               "тест по критерию №2 провалит корректную реализацию Ф-2.",
        blocked_decision="В какой месяц засчитывать покупку, совершённую 31.01 и проведённую 01.02",
        recommendation="Привести критерий приёмки №2 к Ф-2 (ожидать рост январского счётчика) или явно "
                       "перейти на дату проведения в Ф-2; указать часовой пояс для времени 23:58.",
        req_ids=["R-01", "R-06"],
        hints=[{"block_id": month_a["block_id"], "quote": month_a["quote"]},
               {"block_id": month_b["block_id"], "quote": month_b["quote"]}],
        evidence=[month_a, month_b],
        meaning_reason="Один сценарий 31.01/01.02 даёт разные месяцы учёта по Ф-2 и по критерию №2.",
        blocks=["development", "testing"],
        witness=month_witness,
        merged_from=["C-03"],
        cause={"object": OBJECT, "condition": CONDITION, "outcomes": ["учтена в январе", "учтена в феврале"]},
        stage="cross",
    )
    f2 = _finding(
        id="F-2", scope="set", kind="conflict", criterion="set_consistent", severity="critical",
        title="Правила отправки push: Ф-3 ограничивает один push в месяц, Ф-4 требует push после смены порога",
        impact="Клиент либо не получит уведомление после смены порога, либо получит второй push в месяце; "
               "разработчик выберет правило наугад.",
        blocked_decision="Отправлять ли второй push в месяце после смены порога",
        recommendation="Указать, сбрасывает ли смена порога месячный лимит push, и добавить критерий приёмки "
                       "на второй push в месяце.",
        req_ids=["R-02", "R-03"],
        hints=[{"block_id": push_a["block_id"], "quote": push_a["quote"]},
               {"block_id": push_b["block_id"], "quote": push_b["quote"]}],
        evidence=[push_a, push_b],
        meaning_reason="При одном входе Ф-3 и Ф-4 дают несовместимые исходы отправки.",
        blocks=["development", "testing"],
        witness={
            "input": "В феврале push уже был; клиент повысил порог, после проведённой покупки расходы снова "
                     "достигли порога.",
            "outcome_a": "Push не отправляется: лимит один в месяц (Ф-3).",
            "outcome_b": "Push отправляется: независимо от истории настройки (Ф-4).",
            "evidence_a": push_a,
            "evidence_b": push_b,
        },
        merged_from=["C-01", "C-05"],
        cause={"object": OBJECT, "condition": CONDITION, "outcomes": ["push не отправлен", "push отправлен"]},
        stage="cross",
    )
    f3 = _finding(
        id="F-3", scope="requirement", kind="conflict", criterion="correct", severity="major",
        title="Критерий приёмки №2 ожидает февральский счётчик для покупки 31 января",
        impact="Повтор F-1, найденный правилами: ожидаемый результат строки приёмки противоречит Ф-2.",
        recommendation="Исправить ожидаемый результат критерия приёмки №2 по правилу Ф-2.",
        req_ids=["R-06"],
        evidence=[copy.deepcopy(month_b), copy.deepcopy(month_a)],
        meaning_status="deterministic",
        blocks=["testing"],
        witness=copy.deepcopy(month_witness),
        merged_from=["C-07"],
        cause={"object": OBJECT, "condition": CONDITION, "outcomes": ["учтена в феврале", "учтена в январе"]},
        source="rules", stage="rules",
        duplicate_of="F-1",
    )
    f4 = _finding(
        id="F-4", scope="requirement", kind="ambiguity", criterion="unambiguous", severity="major",
        status="needs_review", meaning_status="uncertain",
        meaning_reason="Событием может быть авторизация или клиринг; модель не уверена, нужен ответ заказчика.",
        title="«В течение минуты после получения события»: не определено, какое событие процессинга считается "
              "проведением покупки",
        impact="Нельзя измерить минуту: неизвестна точка отсчёта.",
        req_ids=["R-04"],
        evidence=[doc.ev(11, "в течение минуты после получения события")],
        blocks=["testing"],
        merged_from=["C-09"],
        cause={"object": OBJECT, "condition": CONDITION, "outcomes": []},
    )
    findings = [f1, f2, f3, f4]

    issues = {("R-01", "correct"): ["F-1"], ("R-02", "correct"): ["F-2"], ("R-03", "correct"): ["F-2"],
              ("R-06", "correct"): ["F-1", "F-3"], ("R-04", "unambiguous"): ["F-4"]}
    titles = {f["id"]: f["title"] for f in findings}
    checks = []
    for req in requirements:
        for code in INDIVIDUAL_CRITERIA:
            ids = issues.get((req["id"], code))
            if ids:
                checks.append({"req_id": req["id"], "criterion": code, "status": "issue", "reason": titles[ids[0]],
                               "finding_ids": ids, "source": "llm"})
            else:
                checks.append({"req_id": req["id"], "criterion": code, "status": "pass", "reason": "",
                               "finding_ids": [], "source": "llm"})

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "run": {
            "run_id": "p17-rootcause", "parent_run_id": None, "source_sha256": document["id"],
            "source_name": document["source_name"], "agent_version": "0.1.0", "agent_commit": None,
            "provider": "mock", "model": "mock-1", "requested_model": "mock-1", "models_seen": ["mock-1"],
            "mode": "mock", "status": "complete", "status_reasons": [],
            "started_at": "2026-11-26T12:00:00+05:00", "finished_at": "2026-11-26T12:00:30+05:00", "duration_s": 30.0,
            "calls": {"physical": 3, "cache_hits": 0, "failed": 0, "retries": 0},
            "tokens": {"input": 9100, "output": 1400, "cache_read": 0},
            "budget": {"max_calls": 40, "max_seconds": 1500.0, "max_tokens": None, "exhausted": False, "reason": None},
            "stages": [_stage("read", calls=0), _stage("rules", calls=0, implementation="rules"),
                       _stage("individual"), _stage("cross"), _stage("verify_meaning")],
            "incomplete_stages": [], "modules": {},
            "evidence_audit": {"checked": 9, "confirmed": 9, "ambiguous": 0, "rejected": 0,
                               "note": "Считаются подсказки кандидатов C-01…C-09."},
            "options": {}, "context_policy": "full",
        },
        "document": document,
        "requirements": requirements,
        "checks": checks,
        "findings": findings,
        "facts": [],
        "coverage": [
            {"req_id": "R-01", "obligation": "Месяц покупки — по дате совершения", "acceptance_ids": ["R-06"],
             "status": "conflict", "explanation": "Критерий №2 ждёт февраль для покупки 31.01 (F-1)."},
            {"req_id": "R-02", "obligation": "Не более одного push в месяц", "acceptance_ids": ["R-05"],
             "status": "partial", "explanation": "Проверен первый push; второй push в месяце не проверяется."},
            {"req_id": "R-03", "obligation": "Push после смены порога", "acceptance_ids": [],
             "status": "uncovered", "explanation": "Нет строки приёмки для смены порога."},
        ],
        "questions": [
            {"id": "Q-1", "finding_ids": ["F-1", "F-3"],
             "prompt": "В какой месяц засчитывать покупку, совершённую 31.01 в 23:58 и проведённую 01.02?",
             "options": ["В январь — по дате совершения (Ф-2)", "В февраль — по дате проведения"],
             "affected_req_ids": ["R-01", "R-06"]},
            {"id": "Q-2", "finding_ids": ["F-2"], "prompt": "Сбрасывает ли смена порога месячный лимит push?",
             "options": ["Да, после смены порога разрешён ещё один push", "Нет, лимит один push в месяц"],
             "affected_req_ids": ["R-02", "R-03"]},
        ],
        "checklist": [],
        "test_cases": [],
        "decisions": [],
        "diff": None,
        "verdict": {
            "development": {"status": "not_ready",
                            "reasons": ["Не определён месяц учёта покупки (F-1)",
                                        "Не определено правило второго push (F-2)"],
                            "finding_ids": ["F-1", "F-2"]},
            "testing": {"status": "not_ready",
                        "reasons": ["Ожидаемый результат критерия приёмки №2 противоречит Ф-2 (F-1, F-3)",
                                    "Нет точки отсчёта для «в течение минуты» (F-4, на проверке)"],
                        "finding_ids": ["F-1", "F-3", "F-4"]},
            "first_actions": [
                {"order": 1, "action": "Ответить на Q-1 и исправить критерий приёмки №2 или Ф-2",
                 "finding_ids": ["F-1", "F-3"]},
                {"order": 2, "action": "Ответить на Q-2 и исправить Ф-3 или Ф-4", "finding_ids": ["F-2"]},
            ],
            "basis": "Подтверждённые критичные противоречия блокируют разработку и тестирование.",
        },
        "summary": {},
        "warnings": [],
        "excluded": [{"block_ids": [b["id"] for b in document["blocks"] if b["kind"] in ("heading", "table_header")],
                      "reason": "Заголовки, не требования"}],
        "rejected": [],
    }
    report["summary"] = _summary(report)
    return report


def strip_optional(report: dict[str, Any]) -> dict[str, Any]:
    """«Старый» Report: у находок только обязательные поля контракта v1, без cause/merged_from/ссылок."""
    required = {"id", "scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "evidence",
                "status", "anchor_status", "meaning_status", "blocks", "witness"}
    out = copy.deepcopy(report)
    out["findings"] = [{k: v for k, v in f.items() if k in required} for f in out["findings"]]
    return out
