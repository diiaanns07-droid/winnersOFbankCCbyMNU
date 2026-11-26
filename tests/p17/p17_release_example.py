"""Полный фиксированный пример на выданном ТЗ: офлайн-отчёт релиза + имитация ответов модели.

Основа — настоящий ``release/reports/offline/requirements.json`` (движок на ``f91d3b6``,
``--offline-lint``): документ, нарезка, проверки правил, факты, покрытие, чек-лист и 26
находок правил берутся как есть. Поверх добавляются ответы семантических этапов, которые в
разработческой проверке **имитированы** (``run.mode = "mock"``, ``run.model = "mock-1"``):

* **F-027** 🔴 Ф-3 «максимум один push в месяц» против Ф-4 «push независимо от истории»;
* **F-028** 🔴 Ф-2 «месяц по дате совершения» против критерия приёмки №2 «февральский счётчик»;
* **F-029** 🟠 «календарный месяц» лимита push не определён — **та же цитата Ф-3**, что у F-027,
  но другая бизнес-проблема (две записи Jira);
* **F-030** 🟠 дубль F-028 от правил (``duplicate_of``) — в Jira одна запись F-028.

В текстах есть кавычки, запятые и переносы строк — проверка CSV-парсером.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from p17_fixtures import _summary

ROOT = Path(__file__).resolve().parents[2]
RELEASE_JSON = ROOT / "release" / "reports" / "offline" / "requirements.json"
MOCK_REASON = "фикстура p17: ответ семантического этапа имитирован (mock)"


def load_offline(path: Path = RELEASE_JSON) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ev(blocks: dict[str, dict[str, Any]], needle_block: str, quote: str) -> dict[str, Any]:
    block = next(b for b in blocks.values() if needle_block in b["text"])
    start = block["text"].index(quote)
    return {"block_id": block["id"], "start": start, "end": start + len(quote), "quote": quote}


def _finding(**kw: Any) -> dict[str, Any]:
    base = {"hints": [], "status": "confirmed", "anchor_status": "supported", "meaning_status": "confirmed",
            "meaning_reason": "", "recommendation": "", "blocked_decision": "", "blocks": [], "witness": None,
            "inspected_block_ids": [], "merged_from": [], "cause": None, "source": "llm", "stage": "cross",
            "notes": [MOCK_REASON]}
    base.update(kw)
    return base


def build_release_example(offline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Полный (``complete``) Report контракта v1 на выданном ТЗ с двумя критичными замечаниями."""
    rep = copy.deepcopy(offline if offline is not None else load_offline())
    rep.pop("exports", None)
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}

    f3_one = _ev(blocks, "Ф-3.", "На карту приходится максимум один такой push за календарный месяц.")
    f4_any = _ev(blocks, "Ф-4.", "следующее достижение вызывает push независимо от истории предыдущей настройки")
    f2_month = _ev(blocks, "Ф-2.", "Месяц определяется по дате совершения покупки в Алматы.")
    ac2_feb = _ev(blocks, "Покупка 31 января в 23:58", "Февральский счётчик вырос на 4 000 ₸")
    month_witness = {
        "input": "Покупка совершена 31 января в 23:58, проведена 1 февраля в 00:03 по Алматы.",
        "outcome_a": "Сумма засчитана в январь: месяц — по дате совершения (Ф-2).",
        "outcome_b": "Сумма засчитана в февраль: так ждёт критерий приёмки №2.",
        "evidence_a": f2_month, "evidence_b": ac2_feb,
    }
    month_cause = {"object": "месяц учёта покупки", "condition": "покупка 31.01 в 23:58 проведена 01.02 в 00:03",
                   "outcomes": ["январь", "февраль"]}

    new = [
        _finding(
            id="F-027", scope="set", kind="conflict", criterion="set_consistent", severity="critical",
            title="Ф-3 разрешает один push в месяц, Ф-4 требует push после смены порога",
            impact='Клиент либо не получит push после смены порога, либо получит второй push в месяце; '
                   'разработчик выберет правило "наугад".',
            blocked_decision="Отправлять ли второй push в месяце после смены порога",
            recommendation='Записать одно правило явно:\n"смена порога сбрасывает месячный лимит" '
                           'или "лимит один push в месяц сохраняется".\nДобавить критерий приёмки на второй push.',
            req_ids=["R-004.2", "R-005.2"], evidence=[f3_one, f4_any],
            hints=[{"block_id": f3_one["block_id"], "quote": f3_one["quote"]},
                   {"block_id": f4_any["block_id"], "quote": f4_any["quote"]}],
            meaning_reason="При одном входе Ф-3 и Ф-4 дают несовместимые исходы отправки.",
            blocks=["development", "testing"],
            witness={"input": "В феврале push уже был; клиент повысил порог, расходы снова достигли порога.",
                     "outcome_a": "Push не отправляется: лимит один в месяц (Ф-3).",
                     "outcome_b": "Push отправляется: независимо от истории (Ф-4).",
                     "evidence_a": f3_one, "evidence_b": f4_any},
            merged_from=["C-m01"],
            cause={"object": "push о достижении порога", "condition": "push в месяце уже был, порог изменён",
                   "outcomes": ["push не отправлен", "push отправлен"]},
        ),
        _finding(
            id="F-028", scope="set", kind="conflict", criterion="set_consistent", severity="critical",
            title="Ф-2 относит покупку 31.01 к январю, критерий приёмки №2 — к февралю",
            impact="Расходы попадут не в тот месяц: push о пороге придёт в другом месяце; тест по критерию №2 "
                   "провалит корректную реализацию Ф-2.",
            blocked_decision="В какой месяц засчитывать покупку, совершённую 31.01 и проведённую 01.02",
            recommendation='Привести критерий приёмки №2 к Ф-2: ожидать "январский счётчик вырос на 4 000 ₸",\n'
                           "или перейти в Ф-2 на дату проведения; указать часовой пояс для 23:58.",
            req_ids=["R-003.1", "R-010"], evidence=[f2_month, ac2_feb],
            hints=[{"block_id": f2_month["block_id"], "quote": f2_month["quote"]},
                   {"block_id": ac2_feb["block_id"], "quote": ac2_feb["quote"]}],
            meaning_reason="Сценарий 31.01/01.02 даёт разные месяцы учёта по Ф-2 и по критерию №2.",
            blocks=["development", "testing"], witness=month_witness, merged_from=["C-m02"], cause=month_cause,
        ),
        _finding(
            id="F-029", scope="requirement", kind="ambiguity", criterion="unambiguous", severity="major",
            title="«Календарный месяц» лимита push не определён: месяц покупки или отправки, в каком поясе",
            impact="Покупка 31.01 с отправкой push 01.02 может съесть лимит января или февраля.",
            recommendation="Определить «календарный месяц» для лимита push: месяц покупки или месяц отправки, "
                           "часовой пояс UTC+5 (Asia/Almaty).",
            req_ids=["R-004.2"], evidence=[copy.deepcopy(f3_one)],
            hints=[{"block_id": f3_one["block_id"], "quote": f3_one["quote"]}],
            meaning_reason="Месяц лимита не привязан ни к дате покупки, ни к дате отправки.",
            blocks=["testing"], merged_from=["C-m03"], stage="individual",
            cause={"object": "календарный месяц лимита push", "condition": "покупка и отправка push в разных месяцах",
                   "outcomes": ["месяц покупки", "месяц отправки"]},
        ),
        _finding(
            id="F-030", scope="requirement", kind="conflict", criterion="correct", severity="major",
            title="Критерий приёмки №2 ожидает февральский счётчик для покупки 31 января",
            impact="Повтор F-028, найденный правилами.",
            recommendation="Исправить ожидаемый результат критерия приёмки №2 по правилу Ф-2.",
            req_ids=["R-010"], evidence=[copy.deepcopy(ac2_feb), copy.deepcopy(f2_month)],
            meaning_status="deterministic", blocks=["testing"], witness=copy.deepcopy(month_witness),
            merged_from=["C-r07"], cause=copy.deepcopy(month_cause), source="rules", stage="rules",
            duplicate_of="F-028",
        ),
    ]
    rep["findings"] = rep["findings"] + new

    issues = {("R-004.2", "correct"): ["F-027"], ("R-005.2", "correct"): ["F-027"],
              ("R-003.1", "correct"): ["F-028"], ("R-010", "correct"): ["F-028", "F-030"],
              ("R-004.2", "unambiguous"): ["F-029"]}
    titles = {f["id"]: f["title"] for f in new}
    for c in rep["checks"]:
        key = (c["req_id"], c["criterion"])
        if key in issues:
            c.update(status="issue", reason=titles[issues[key][0]],
                     finding_ids=list(dict.fromkeys(list(c.get("finding_ids") or []) + issues[key])))
        elif c["status"] == "unknown":
            c.update(status="pass", reason=MOCK_REASON)
    for r in rep["requirements"]:
        r["review_status"], r["review_reason"] = "reviewed", None

    run = rep["run"]
    run.update(
        run_id="p17-release-example", provider="mock", model="mock-1", requested_model="mock-1",
        models_seen=["mock-1"], mode="mock", status="complete", status_reasons=[], incomplete_stages=[],
        agent_commit=None, calls={"physical": 4, "cache_hits": 0, "failed": 0, "retries": 0},
        tokens={"input": 41200, "output": 3900, "cache_read": 0},
    )
    for stage in run["stages"]:
        if stage.get("status") not in ("ok", "cached"):
            stage.update(status="ok", reason=None)
        if stage.get("name") in ("individual", "cross", "verify_meaning", "questions"):
            stage["calls"] = 1
    rep["verdict"] = {
        "development": {"status": "not_ready",
                        "reasons": ["Не определено правило второго push в месяце (F-027)",
                                    "Не определён месяц учёта покупки на границе месяцев (F-028)"],
                        "finding_ids": ["F-027", "F-028"]},
        "testing": {"status": "not_ready",
                    "reasons": ["Ожидаемый результат критерия приёмки №2 противоречит Ф-2 (F-028, F-030)",
                                "Нет критерия приёмки для второго push и границы месяца (F-027, F-029)"],
                    "finding_ids": ["F-027", "F-028", "F-029", "F-030"]},
        "first_actions": [
            {"order": 1, "action": "Решить, сбрасывает ли смена порога лимит push, и исправить Ф-3 или Ф-4",
             "finding_ids": ["F-027"]},
            {"order": 2, "action": "Привести критерий приёмки №2 к Ф-2 и указать часовой пояс",
             "finding_ids": ["F-028", "F-030"]},
        ],
        "basis": "Подтверждённые критичные противоречия блокируют разработку и тестирование.",
    }
    rep["summary"] = _summary(rep)
    return rep
