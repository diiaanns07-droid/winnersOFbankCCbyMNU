"""Синтетические детерминированные Report по контракту v1 для тестов экспорта p17.

Это не прогон движка: документ разбирается простым парсером фикстуры,
находки, проверки и вердикт заданы вручную, ``summary`` пересчитывается из
списков. Координаты опор вычисляются из текста блоков, поэтому
``contracts.evidence_errors(report) == []``, а ``contracts.validate(report)``
проходит.

Варианты:
* ``complete`` — полный прогон: две находки одной первопричины (общий
  ``cause``, разные серьёзности), находка с ``merged_from``, критичные
  противоречие и пропуск, требование без замечаний, снятый кандидат
  в ``rejected`` и находка на проверке;
* ``partial`` — частичный прогон: R-06 проверено частично, R-07 не проверено,
  verdict ошибочно заявляет «ready»;
* ``failed`` — прогон упал после нарезки: проверок и находок нет.

Каждый вариант строится для документа с нумерацией (ТР-1…ТР-5) и без неё.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

NEUTRAL_TITLE = "Бронирование переговорных комнат"

_NEUTRAL_NUMBERED = """\
# Бронирование переговорных комнат

Учебный нейтральный документ для проверки экспорта отчёта.

## Функциональные требования

* **ТР-1.** Сотрудник бронирует комнату на интервал от 15 до 240 минут включительно, с шагом 15 минут.
* **ТР-2.** Пересекающиеся брони одной комнаты не допускаются. Бронь 10:00–10:30 не пересекается с бронью, которая начинается в 10:30.
* **ТР-3.** Автор отменяет бронь только до начала встречи. После отмены комната становится свободной.
* **ТР-4.** Автор может отменить бронь в любой момент, в том числе после начала встречи.
* **ТР-5.** Система быстро показывает статус комнаты: «свободно | занято | на обслуживании».

## Нефункциональные требования

Портал должен быть удобным и работать без сбоев.

## Требования к уведомлениям

Сотрудник получает напоминание о встрече:
1. за 15 минут до начала;
2. повторно — в момент начала, если бронь не подтверждена.

## Критерии приемки

| Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| Комната свободна 10:00–11:00 | Забронировать 10:00–10:30 | Бронь создана |
| Бронь 10:00–10:30 | Забронировать 10:30–11:00 | Бронь создана |
"""

_NEUTRAL_UNNUMBERED = re.sub(r"\*\*ТР-\d\.\*\* ", "", _NEUTRAL_NUMBERED)

INDIVIDUAL_CRITERIA = (
    "necessary", "appropriate", "unambiguous", "complete", "singular",
    "feasible", "verifiable", "correct", "conforming",
)


def neutral_source(numbered: bool = True) -> str:
    return _NEUTRAL_NUMBERED if numbered else _NEUTRAL_UNNUMBERED


def _strip_inline(src: str, line: int, col0: int) -> tuple[str, list[list[int]]]:
    """Убрать ``**`` и построить loc.map: [[text_start, line, col], ...]."""
    out: list[str] = []
    mapping: list[list[int]] = []
    prev = None
    i = 0
    while i < len(src):
        if src.startswith("**", i):
            i += 2
            continue
        if prev is None or i != prev + 1:
            mapping.append([len(out), line, col0 + i])
        out.append(src[i])
        prev = i
        i += 1
    return "".join(out), mapping


def parse_markdown(text: str, title: str) -> dict[str, Any]:
    """Простой разбор Markdown в Document контракта v1 (только для фикстур)."""
    raw = text.encode("utf-8")
    lines = text.split("\n")
    blocks: list[dict[str, Any]] = []
    section: list[str] = []

    def add(kind: str, body: str, start: int, end: int, mapping: list[list[int]], sect: list[str]) -> None:
        blocks.append(
            {
                "id": f"b{len(blocks) + 1:04d}",
                "kind": kind,
                "section": list(sect),
                "text": body,
                "loc": {"line_start": start, "line_end": end, "map": mapping},
            }
        )

    header_seen = False
    i = 0
    while i < len(lines):
        line = lines[i]
        n = i + 1
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(#+)\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            add("heading", m.group(2), n, n, [[0, n, level + 1]], section[: level - 1])
            section = section[: level - 1] + [m.group(2)]
            header_seen = False
            i += 1
            continue
        if line.startswith("|"):
            if not re.match(r"^\|\s*:?-{3}", line):
                body = line.strip()[1:-1].strip()
                add("table_row" if header_seen else "table_header", body, n, n, [[0, n, 2]], section)
                header_seen = True
            i += 1
            continue
        if line.startswith("* "):
            body, mapping = _strip_inline(line[2:], n, 2)
            add("list_item", body, n, n, mapping, section)
            i += 1
            continue
        start = i
        buf = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "* ")):
            buf.append(lines[i])
            i += 1
        add("paragraph", "\n".join(buf), start + 1, i, [[0, start + 1, 0]], section)
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": title,
        "format": "markdown",
        "source_name": "booking.md",
        "blocks": blocks,
        "warnings": [],
    }


class _Doc:
    def __init__(self, document: dict[str, Any]):
        self.document = document

    def block_at(self, line: int) -> dict[str, Any]:
        for b in self.document["blocks"]:
            if b["loc"]["line_start"] <= line <= b["loc"]["line_end"]:
                return b
        raise KeyError(line)

    def ev(self, line: int, quote: str | None = None) -> dict[str, Any]:
        block = self.block_at(line)
        text = block["text"]
        quote = text if quote is None else quote
        start = text.index(quote)
        return {"block_id": block["id"], "start": start, "end": start + len(quote), "quote": quote}

    def hint(self, line: int, quote: str) -> dict[str, Any]:
        return {"block_id": self.block_at(line)["id"], "quote": quote}


def _req(doc: _Doc, rid: str, source_id: str | None, line: int, kind: str) -> dict[str, Any]:
    ev = doc.ev(line)
    return {
        "id": rid,
        "source_id": source_id,
        "text": ev["quote"],
        "block_ids": [ev["block_id"]],
        "evidence": [ev],
        "hints": [],
        "kind": kind,
        "review_status": "reviewed",
        "review_reason": None,
    }


def _finding(**kw: Any) -> dict[str, Any]:
    base = {
        "hints": [],
        "status": "confirmed",
        "anchor_status": "supported",
        "meaning_status": "confirmed",
        "meaning_reason": "",
        "recommendation": "",
        "blocked_decision": "",
        "blocks": [],
        "witness": None,
        "inspected_block_ids": [],
        "merged_from": [],
        "cause": None,
        "source": "llm",
        "stage": "individual",
        "notes": [],
    }
    base.update(kw)
    return base


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    findings = report["findings"]
    checks = report["checks"]
    return {
        "requirements": len(report["requirements"]),
        "reviewed_requirements": sum(1 for r in report["requirements"] if r["review_status"] == "reviewed"),
        "findings": len(findings),
        "by_severity": {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")},
        "by_status": {s: sum(1 for f in findings if f["status"] == s) for s in ("confirmed", "needs_review")},
        "critical_ids": [f["id"] for f in findings if f["severity"] == "critical"],
        "checks": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "issue", "unknown", "na")},
    }


def _stage(name: str, status: str = "ok", calls: int = 1, reason: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "calls": calls, "cache_hits": 0, "reason": reason, **kw}


def build_report(variant: str = "complete", numbered: bool = True) -> dict[str, Any]:
    """Синтетический Report контракта v1: variant ∈ {complete, partial, failed}."""
    if variant not in {"complete", "partial", "failed"}:
        raise ValueError(variant)
    source = neutral_source(numbered)
    document = parse_markdown(source, NEUTRAL_TITLE)
    document["source_name"] = "booking-numbered.md" if numbered else "booking-unnumbered.md"
    doc = _Doc(document)
    sid = (lambda n: f"ТР-{n}") if numbered else (lambda n: None)

    requirements = [
        _req(doc, "R-01", sid(1), 7, "functional"),
        _req(doc, "R-02", sid(2), 8, "functional"),
        _req(doc, "R-03", sid(3), 9, "functional"),
        _req(doc, "R-04", sid(4), 10, "functional"),
        _req(doc, "R-05", sid(5), 11, "functional"),
        _req(doc, "R-06", None, 15, "nonfunctional"),
        _req(doc, "R-07", None, 19, "functional"),
        _req(doc, "R-08", None, 27, "acceptance"),
        _req(doc, "R-09", None, 28, "acceptance"),
    ]
    fr_blocks = [doc.block_at(n)["id"] for n in range(7, 12)]
    ac_rows = [doc.block_at(27)["id"], doc.block_at(28)["id"]]

    ev_a = doc.ev(9, "Автор отменяет бронь только до начала встречи.")
    ev_b = doc.ev(10, "Автор может отменить бронь в любой момент, в том числе после начала встречи.")
    f001 = _finding(
        id="F-001", scope="set", kind="conflict", criterion="set_consistent", severity="critical",
        title="Правила отмены брони после начала встречи противоречат друг другу",
        impact="Разработчик и тестировщик получат два несовместимых ожидания: поведение кнопки «Отменить» "
               "после начала встречи не определено.",
        blocked_decision="Разрешать ли отмену брони после начала встречи",
        recommendation="Выбрать одно правило отмены после начала встречи, исправить ТР-3 или ТР-4 и добавить "
                       "критерий приёмки на отмену в 10:10 для встречи с 10:00.",
        req_ids=["R-03", "R-04"],
        hints=[doc.hint(9, ev_a["quote"]), doc.hint(10, ev_b["quote"])],
        evidence=[ev_a, ev_b],
        meaning_reason="Обе цитаты найдены; при одном входе требования дают несовместимые исходы.",
        blocks=["development", "testing"],
        witness={
            "input": "Встреча началась в 10:00; в 10:10 автор нажимает «Отменить бронь».",
            "outcome_a": "Отмена отклонена: встреча уже началась.",
            "outcome_b": "Отмена выполнена: отмена допустима в любой момент.",
            "evidence_a": ev_a,
            "evidence_b": ev_b,
        },
        cause={"object": "отмена брони после начала встречи", "condition": "встреча уже началась",
               "outcomes": ["отмена запрещена", "отмена разрешена"]},
        stage="cross",
    )
    f002 = _finding(
        id="F-002", scope="requirement", kind="unverifiable", criterion="verifiable", severity="major",
        title="«Быстро» не задаёт измеримого времени показа статуса",
        impact="Нельзя написать тест с порогом времени; приёмка зависит от мнения проверяющего.",
        recommendation="Указать предельное время показа статуса (перцентиль и секунды) и точку отсчёта.",
        req_ids=["R-05"],
        evidence=[doc.ev(11, "Система быстро показывает статус комнаты: «свободно | занято | на обслуживании».")],
        blocks=["testing"],
        merged_from=["C-014"],
        source="rules",
        meaning_status="deterministic",
    )
    f003 = _finding(
        id="F-003", scope="requirement", kind="unverifiable", criterion="verifiable", severity="major",
        title="Нефункциональное требование не содержит измеримых показателей",
        impact="Удобство и «без сбоев» нельзя проверить тестом; требования к доступности фактически нет.",
        recommendation="Заменить на измеримые показатели: доступность в процентах за месяц, время ответа, "
                       "сценарии юзабилити-проверки.",
        req_ids=["R-06"],
        evidence=[doc.ev(15, "Портал должен быть удобным и работать без сбоев.")],
        blocks=["testing"],
        cause={"object": "НФТ портала", "condition": "нет измеримых показателей", "outcomes": []},
    )
    f004 = _finding(
        id="F-004", scope="requirement", kind="ambiguity", criterion="unambiguous", severity="minor",
        title="«Без сбоев» допускает разные толкования",
        impact="Та же первопричина, что у F-003: нет измеримого показателя.",
        req_ids=["R-06"],
        evidence=[doc.ev(15, "работать без сбоев")],
        cause={"object": "НФТ портала", "condition": "Нет измеримых  показателей", "outcomes": []},
    )
    f005 = _finding(
        id="F-005", scope="set", kind="omission", criterion="set_complete", severity="critical",
        title="Подтверждение брони упомянуто, но нигде не описано",
        impact="Неясно, как и до какого момента подтверждать бронь и что происходит с неподтверждённой бронью; "
               "повторное напоминание нельзя реализовать.",
        blocked_decision="Как реализовать подтверждение брони и повторное напоминание",
        recommendation="Добавить функциональное требование о подтверждении брони: кто, каким действием, "
                       "до какого момента и что происходит без подтверждения.",
        req_ids=["R-07"],
        evidence=[doc.ev(19, "если бронь не подтверждена")],
        inspected_block_ids=fr_blocks + ac_rows,
        blocks=["development", "testing"],
        cause={"object": "подтверждение брони", "condition": "бронь не подтверждена", "outcomes": []},
        stage="cross",
    )
    f006 = _finding(
        id="F-006", scope="requirement", kind="ambiguity", criterion="unambiguous", severity="major",
        status="needs_review", meaning_status="uncertain",
        meaning_reason="Модель и правила разошлись: неясно, относится ли шаг 15 минут к началу брони "
                       "или только к длительности.",
        title="Шаг 15 минут не уточняет, кратно ли ему начало брони",
        impact="Возможны брони, начинающиеся в 10:07.",
        req_ids=["R-01"],
        evidence=[doc.ev(7, "с шагом 15 минут")],
    )
    f007 = _finding(
        id="F-007", scope="set", kind="incomplete", criterion="set_validatable", severity="minor",
        title="Отмена брони и статус комнаты не покрыты критериями приёмки",
        impact="Тестировщику не на что опереться при приёмке ТР-3…ТР-5.",
        recommendation="Добавить строки приёмки: отмена до и после начала встречи, показ статуса «на обслуживании».",
        req_ids=["R-03", "R-04", "R-05"],
        evidence=[doc.ev(25, "Исходные условия | Действие | Ожидаемый результат")],
        inspected_block_ids=ac_rows,
        blocks=["testing"],
        stage="cross",
    )
    findings = [f001, f002, f003, f004, f005, f006, f007]

    issues = {
        ("R-01", "unambiguous"): ["F-006"],
        ("R-03", "correct"): ["F-001"],
        ("R-04", "correct"): ["F-001"],
        ("R-05", "verifiable"): ["F-002"],
        ("R-06", "verifiable"): ["F-003"],
        ("R-06", "unambiguous"): ["F-004"],
    }
    unknown: dict[str, set[str]] = {}
    review: dict[str, tuple[str, str | None]] = {}
    if variant == "partial":
        unknown = {
            "R-06": set(INDIVIDUAL_CRITERIA) - {"verifiable", "unambiguous"},
            "R-07": set(INDIVIDUAL_CRITERIA),
        }
        review = {
            "R-06": ("partial", "Этап individual: тайм-аут поставщика после 2 из 9 критериев."),
            "R-07": ("not_reviewed", "Этап individual: тайм-аут поставщика, требование не проверено."),
        }
    for req in requirements:
        if req["id"] in review:
            req["review_status"], req["review_reason"] = review[req["id"]]

    checks: list[dict[str, Any]] = []
    if variant != "failed":
        for req in requirements:
            rid = req["id"]
            for code in INDIVIDUAL_CRITERIA:
                if code in unknown.get(rid, set()):
                    checks.append({"req_id": rid, "criterion": code, "status": "unknown",
                                   "reason": "Нет ответа поставщика (тайм-аут).", "finding_ids": [], "source": "llm"})
                elif (rid, code) in issues:
                    ids = issues[(rid, code)]
                    reason = next(f["title"] for f in [f001, f002, f003, f004, f006] if f["id"] == ids[0])
                    checks.append({"req_id": rid, "criterion": code, "status": "issue",
                                   "reason": reason, "finding_ids": ids, "source": "llm"})
                elif code == "singular" and rid in {"R-08", "R-09"}:
                    checks.append({"req_id": rid, "criterion": code, "status": "na",
                                   "reason": "Строка приёмки, а не обязательство.", "finding_ids": [], "source": "rules"})
                else:
                    checks.append({"req_id": rid, "criterion": code, "status": "pass", "reason": "",
                                   "finding_ids": [], "source": "llm"})

    run = {
        "run_id": f"p17-{variant}-{'numbered' if numbered else 'unnumbered'}",
        "parent_run_id": None,
        "source_sha256": document["id"],
        "source_name": document["source_name"],
        "agent_version": "0.1.0",
        "agent_commit": None,
        "provider": "mock",
        "model": "mock-1",
        "requested_model": "mock-1",
        "models_seen": ["mock-1"],
        "mode": "mock",
        "status": "complete",
        "status_reasons": [],
        "started_at": "2026-11-26T10:00:00+05:00",
        "finished_at": "2026-11-26T10:01:23.500000+05:00",
        "duration_s": 83.5,
        "calls": {"physical": 4, "cache_hits": 0, "failed": 0, "retries": 0},
        "tokens": {"input": 12450, "output": 3210, "cache_read": 0},
        "budget": {"max_calls": 40, "max_seconds": 1500.0, "max_tokens": None, "exhausted": False, "reason": None},
        "stages": [
            _stage("read", calls=0),
            _stage("inventory"),
            _stage("individual"),
            _stage("cross"),
            _stage("verify_meaning"),
        ],
        "incomplete_stages": [],
        "modules": {},
        "evidence_audit": {
            "checked": 10, "confirmed": 9, "ambiguous": 0, "rejected": 1,
            "note": "Считаются подсказки кандидатов; одна подсказка снятого кандидата не найдена в тексте.",
        },
        "options": {},
        "context_policy": "full",
    }
    verdict = {
        "development": {
            "status": "not_ready",
            "reasons": ["Противоречие в правилах отмены (F-001)", "Подтверждение брони не описано (F-005)"],
            "finding_ids": ["F-001", "F-005"],
        },
        "testing": {
            "status": "not_ready",
            "reasons": ["Нет измеримых порогов (F-002, F-003)", "Нет критериев приёмки для отмены и статуса (F-007)"],
            "finding_ids": ["F-001", "F-003", "F-007"],
        },
        "first_actions": [
            {"order": 2, "action": "Описать подтверждение брони", "finding_ids": ["F-005"]},
            {"order": 1, "action": "Решить вопрос Q-001 и исправить ТР-3 или ТР-4", "finding_ids": ["F-001"]},
            {"order": 3, "action": "Задать измеримые пороги для статуса и НФТ", "finding_ids": ["F-002", "F-003"]},
        ],
        "basis": "Подтверждённые критичные замечания блокируют разработку и тестирование.",
    }

    if variant == "partial":
        run.update(
            status="partial",
            status_reasons=["Этап individual завершён частично: 2 требования без полной проверки."],
            incomplete_stages=["individual"],
            finished_at="2026-11-26T10:02:05+05:00",
            duration_s=125.0,
            calls={"physical": 6, "cache_hits": 0, "failed": 2, "retries": 2},
        )
        run["stages"][2] = _stage("individual", "partial", calls=3, reason="timeout: 2 из 3 вызовов")
        verdict = copy.deepcopy(verdict)
        # Намеренная ошибка в verdict: неполный прогон не должен показываться как готовность.
        verdict["development"] = {"status": "ready", "reasons": ["Критичных пропусков не найдено"], "finding_ids": []}
        verdict["testing"] = {"status": "ready", "reasons": ["Пороги можно уточнить позже"], "finding_ids": []}
    elif variant == "failed":
        findings = []
        for req in requirements:
            req["review_status"] = "not_reviewed"
            req["review_reason"] = "Прогон прерван до проверки требований."
        run.update(
            status="failed",
            status_reasons=["Поставщик вернул 503 трижды; проверка не выполнена."],
            incomplete_stages=["individual", "cross", "verify_meaning"],
            finished_at="2026-11-26T10:00:41+05:00",
            duration_s=41.0,
            calls={"physical": 3, "cache_hits": 0, "failed": 3, "retries": 2},
            tokens={"input": 0, "output": 0, "cache_read": 0},
            evidence_audit={"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": "Опоры не поступали."},
        )
        run["stages"] = [
            _stage("read", calls=0),
            _stage("inventory", calls=0, implementation="rules"),
            _stage("individual", "failed", calls=3, reason="server: 503"),
            _stage("cross", "skipped", calls=0, reason="предыдущий этап завершился ошибкой"),
            _stage("verify_meaning", "skipped", calls=0, reason="предыдущий этап завершился ошибкой"),
        ]
        verdict = {
            "development": {"status": "unknown", "reasons": ["Проверка не выполнена"], "finding_ids": []},
            "testing": {"status": "unknown", "reasons": ["Проверка не выполнена"], "finding_ids": []},
            "first_actions": [{"order": 1, "action": "Повторить прогон после восстановления поставщика", "finding_ids": []}],
            "basis": "Прогон завершился ошибкой.",
        }

    full = variant != "failed"
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "run": run,
        "document": document,
        "requirements": requirements,
        "checks": checks,
        "findings": findings,
        "facts": [
            {"id": "FACT-01", "subject": "бронь", "field": "длительность", "value": "15–240", "unit": "мин",
             "type": "range", "direction": None, "range": {"min": 15, "max": 240, "inclusive": True},
             "req_ids": ["R-01"], "evidence": [doc.ev(7, "от 15 до 240 минут")]},
            {"id": "FACT-02", "subject": "бронь", "field": "шаг", "value": 15, "unit": "мин", "type": "number",
             "direction": None, "range": None, "req_ids": ["R-01"], "evidence": [doc.ev(7, "с шагом 15 минут")]},
        ] if full else [],
        "coverage": [
            {"req_id": "R-01", "obligation": "Бронь от 15 до 240 минут с шагом 15 минут", "acceptance_ids": ["R-08"],
             "status": "partial", "explanation": "Проверен только интервал 30 минут; границы 15 и 240 минут и шаг не покрыты."},
            {"req_id": "R-02", "obligation": "Смежные брони не пересекаются", "acceptance_ids": ["R-09"],
             "status": "covered", "explanation": "Строка приёмки проверяет смежные брони 10:00–10:30 и 10:30–11:00."},
            {"req_id": "R-03", "obligation": "Отмена до начала встречи", "acceptance_ids": [],
             "status": "uncovered", "explanation": "Нет строки приёмки для отмены."},
            {"req_id": "R-04", "obligation": "Отмена после начала встречи", "acceptance_ids": [],
             "status": "uncovered", "explanation": "Нет строки приёмки; правило противоречит R-03."},
            {"req_id": "R-05", "obligation": "Показ статуса «свободно | занято | на обслуживании»", "acceptance_ids": [],
             "status": "uncovered", "explanation": "Нет времени показа и проверки статуса «на обслуживании»."},
            {"req_id": "R-06", "obligation": "Удобство и работа без сбоев", "acceptance_ids": [],
             "status": "unknown", "explanation": "Нет измеримого показателя, покрытие оценить нельзя."},
            {"req_id": "R-07", "obligation": "Напоминание за 15 минут и повторное", "acceptance_ids": [],
             "status": "uncovered", "explanation": "Нет строк приёмки для напоминаний."},
        ] if full else [],
        "questions": [
            {"id": "Q-001", "finding_ids": ["F-001"], "prompt": "Можно ли отменить бронь после начала встречи?",
             "options": ["Нельзя: действует ТР-3", "Можно: действует ТР-4"], "affected_req_ids": ["R-03", "R-04"]},
            {"id": "Q-002", "finding_ids": ["F-005"], "prompt": "Как и до какого момента сотрудник подтверждает бронь?",
             "options": ["Кнопкой в напоминании до начала встречи", "Подтверждение не требуется"],
             "affected_req_ids": ["R-07"]},
        ] if full else [],
        "checklist": [
            {"id": "CL-06", "text": "Требование может быть протестировано", "available": "yes", "checked": "no",
             "note": "ТР-5 и НФТ без измеримых порогов.", "finding_ids": ["F-002", "F-003"], "evidence": []},
            {"id": "CL-08", "text": "Требование не имеет противоречий или явных показателей операционных рисков",
             "available": "yes", "checked": "no", "note": "Противоречие правил отмены.", "finding_ids": ["F-001"],
             "evidence": [ev_a, ev_b]},
            {"id": "CL-14", "text": "Поддерживается версионность документа / зафиксирована", "available": "no",
             "checked": "unknown", "note": "Версия и дата в документе не указаны.", "finding_ids": [], "evidence": []},
        ] if full else [],
        "test_cases": [
            {"id": "TC-01", "precondition": "Комната свободна 10:00–11:00", "action": "Забронировать 10:00–10:15",
             "expected": "Бронь создана", "req_ids": ["R-01"], "open_question_id": None},
            {"id": "TC-02", "precondition": "Встреча с 10:00 началась", "action": "В 10:10 автор отменяет бронь",
             "expected": "Зависит от ответа на Q-001", "req_ids": ["R-03", "R-04"], "open_question_id": "Q-001"},
        ] if full else [],
        "decisions": [
            {"question_id": "Q-002", "source_sha256": document["id"],
             "answer": "Кнопкой «Подтвердить» в напоминании, до начала встречи.", "edits": [],
             "note": "answers.md, ответ владельца продукта"},
        ] if full else [],
        "diff": None,
        "verdict": verdict,
        "summary": {},
        "warnings": [
            {"code": "no_trace_ids", "message": "Таблица критериев приёмки (строки 25–28) не ссылается на ID требований.",
             "stage": "inventory", "block_ids": ac_rows},
        ],
        "excluded": [
            {"block_ids": [b["id"] for b in document["blocks"] if b["kind"] == "heading"],
             "reason": "Заголовки, не требования"},
            {"block_ids": [doc.block_at(3)["id"]], "reason": "Вводный текст без обязательств"},
            {"block_ids": [doc.block_at(25)["id"]], "reason": "Заголовок таблицы приёмки"},
        ],
        "rejected": [
            {"candidate": {"scope": "requirement", "kind": "conflict", "criterion": "correct", "severity": "major",
                           "title": "Пример 10:00–10:30 противоречит запрету пересечений", "impact": "",
                           "req_ids": ["R-02"], "hints": [doc.hint(8, "Бронь 10:00–10:30 не пересекается")]},
             "reason": "Интервалы полуоткрытые: окончание 10:30 и начало 10:30 не пересекаются, противоречия нет.",
             "stage": "verify_meaning"},
        ] if full else [],
    }
    report["summary"] = _summary(report)
    if not numbered:
        # В документе без нумерации нет «ТР-n»: тексты ссылаются на ID агента.
        text = json.dumps(report, ensure_ascii=False)
        for n in range(1, 6):
            text = text.replace(f"ТР-{n}", f"R-0{n}")
        report = json.loads(text)
    return report


def build_all() -> dict[str, dict[str, Any]]:
    out = {}
    for variant in ("complete", "partial", "failed"):
        for numbered in (True, False):
            out[f"{variant}-{'numbered' if numbered else 'unnumbered'}"] = build_report(variant, numbered)
    return out
