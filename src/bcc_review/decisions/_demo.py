"""Офлайн-демо и фикстуры модуля решений (№08) на синтетическом документе.

Тема — досрочное погашение кредита: комиссия и график платежей. Всё здесь —
ПОДСТАВНОЕ и нужно для детерминированных тестов и повтора №18 без ключа:

* ``synthetic_findings`` — подтверждённые находки по цитатам (координаты
  вычисляет код по фактическому тексту документа);
* ``make_scripted_ask(document)`` — подставной транспорт этапа ``clarify``:
  отвечает заранее записанными вопросами и проверяет ответ по JSON-схеме, как
  это делает движок. Текст документа движок прикладывает сам, поэтому
  подставной транспорт получает документ через замыкание;
* ``recheck`` — подставная перепроверка по правилам для этого документа. Она
  читает реально записанный файл редакции. Настоящую перепроверку делает
  движок Max.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._doc import DocView, as_list, get

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples" / "team_answers"
SYNTHETIC_DOC = EXAMPLES_DIR / "synthetic_loan_tz.md"

FEE_NO = "Комиссия за досрочное погашение не взимается."
FEE_YES = "взимается комиссия 1% от суммы досрочного погашения"
FEE_AC = "комиссия 0 ₸"
SCHED_RULE = "платёж списывается в следующий рабочий день"
SCHED_AC = "Платёж списан 14 марта, в пятницу"
BANKDAY = "ближайший банковский день"
TERM_WORKDAY = ("Рабочий день — день, который не является выходным или праздничным по "
                "производственному календарю Республики Казахстан.")
DP1 = "Заёмщик подаёт заявку на полное или частичное досрочное погашение в мобильном банке."
TARIFF = ("При досрочном погашении в первые 6 месяцев с даты выдачи взимается комиссия 1% от суммы "
          "досрочного погашения.")

REQUIREMENTS = [
    {"id": "R-01", "source_id": "ДП-1", "quote": DP1},
    {"id": "R-02", "source_id": "ДП-2", "quote": FEE_NO},
    {"id": "R-03", "source_id": "ДП-3", "quote": SCHED_RULE},
    {"id": "R-04", "source_id": "ДП-4", "quote": "срок кредита сохраняется"},
    {"id": "R-05", "source_id": "ДП-5", "quote": BANKDAY},
    {"id": "R-06", "source_id": None, "quote": TARIFF},
    {"id": "R-07", "source_id": None, "quote": FEE_AC},
    {"id": "R-08", "source_id": None, "quote": SCHED_AC},
]


def _ev(doc: DocView, quote: str) -> dict:
    ev = doc.evidence(quote)
    if ev is None:
        raise ValueError(f"Цитата не найдена однозначно: {quote!r}")
    return ev


def synthetic_requirements(document: Any) -> list[dict]:
    doc = DocView(document)
    out = []
    for r in REQUIREMENTS:
        ev = _ev(doc, r["quote"])
        b = doc.block(ev["block_id"])
        out.append({"id": r["id"], "source_id": r["source_id"], "text": b.text,
                    "block_ids": [b.id], "evidence": [ev], "review_status": "reviewed",
                    "review_reason": None})
    return out


def finding(fid: str, kind: str, criterion: str, severity: str, title: str, impact: str,
            req_ids: list[str], evidence: list[dict], *, status: str = "confirmed",
            witness: dict | None = None, blocks: tuple[str, ...] = ("development", "testing"),
            blocked_decision: str = "", scope: str = "requirement", stage: str = "individual") -> dict:
    """Finding в форме контракта v1 (contracts.DEFS["Finding"])."""
    return {
        "id": fid, "scope": scope, "kind": kind, "criterion": criterion, "severity": severity,
        "title": title, "impact": impact, "blocked_decision": blocked_decision, "req_ids": req_ids,
        "hints": [{"block_id": e["block_id"], "quote": e["quote"]} for e in evidence],
        "evidence": evidence, "status": status, "anchor_status": "supported",
        "meaning_status": "confirmed" if status == "confirmed" else "uncertain",
        "recommendation": "", "blocks": list(blocks), "witness": witness,
        "inspected_block_ids": [], "merged_from": [], "cause": None,
        "source": "synthetic", "stage": stage, "notes": [],
    }


def synthetic_findings(document: Any) -> list[dict]:
    """Находки «как от Max» для синтетического документа (контракт Finding v1)."""
    doc = DocView(document)
    fee_no, fee_yes, fee_ac = _ev(doc, FEE_NO), _ev(doc, FEE_YES), _ev(doc, FEE_AC)
    s_rule, s_ac = _ev(doc, SCHED_RULE), _ev(doc, SCHED_AC)
    dp2 = doc.block(fee_no["block_id"])
    return [
        finding(
            "F-01", "conflict", "set_consistent", "critical",
            "ДП-2 и раздел «Тарифы» по-разному определяют комиссию за досрочное погашение",
            "Расчёт суммы списания нельзя реализовать: одно правило запрещает комиссию, "
            "другое требует 1% в первые 6 месяцев.",
            ["R-02", "R-06"], [fee_no, fee_yes], scope="set", stage="cross",
            blocked_decision="Сумма списания при досрочном погашении в первые 6 месяцев",
            witness={
                "input": "Кредит выдан 10 января, досрочное погашение 10 марта на 200 000 ₸",
                "outcome_a": "по ДП-2 комиссия 0 ₸",
                "outcome_b": "по разделу «Тарифы» комиссия 1% от суммы досрочного погашения",
                "evidence_a": fee_no, "evidence_b": fee_yes,
            }),
        finding(
            "F-02", "conflict", "set_consistent", "critical",
            "Критерий приёмки №1 ожидает нулевую комиссию вопреки разделу «Тарифы»",
            "Тест по критерию №1 упадёт при реализации тарифа или подтвердит неверный расчёт.",
            ["R-06", "R-07"], [fee_ac, fee_yes], scope="set", stage="cross", blocks=("testing",),
            blocked_decision="Ожидаемый результат критерия приёмки №1",
            witness={
                "input": "Кредит выдан 10 января, заявка 10 марта на 200 000 ₸",
                "outcome_a": "критерий приёмки ожидает комиссию 0 ₸",
                "outcome_b": "по тарифу комиссия 1% от суммы досрочного погашения",
                "evidence_a": fee_ac, "evidence_b": fee_yes,
            }),
        finding(
            "F-03", "conflict", "set_consistent", "critical",
            "ДП-3 переносит платёж вперёд, критерий приёмки №2 — назад",
            "График платежей и тест даты списания дают разные даты для выходного дня.",
            ["R-03", "R-08"], [s_rule, s_ac], scope="set", stage="cross",
            blocked_decision="Дата списания платежа, выпавшего на выходной",
            witness={
                "input": "Дата платежа 15 марта, суббота",
                "outcome_a": "по ДП-3 платёж списан в следующий рабочий день после 15 марта",
                "outcome_b": "по критерию приёмки платёж списан 14 марта, в пятницу",
                "evidence_a": s_rule, "evidence_b": s_ac,
            }),
        finding(
            "F-04", "ambiguity", "unambiguous", "major", "«Банковский день» в ДП-5 не определён",
            "Дата исполнения заявки зависит от того, что считать банковским днём.",
            ["R-05"], [_ev(doc, BANKDAY)], blocked_decision="Календарь исполнения заявки"),
        finding(
            "F-05", "omission", "complete", "major",
            "Не задана минимальная сумма частичного досрочного погашения",
            "Неизвестно, принимать ли заявку на 1 ₸; нет граничных значений для тестов.",
            ["R-01"], [_ev(doc, "полное или частичное досрочное погашение")], blocks=("development",),
            blocked_decision="Проверка суммы заявки"),
        # редакционная: вопрос владельцу не нужен
        finding("F-06", "format", "conforming", "minor", "В «Общих сведениях» нет версии и даты документа",
                "Нельзя сослаться на версию.", [], [_ev(doc, "Досрочное погашение в мобильном банке")],
                blocks=(), scope="set"),
        # не подтверждена — вопрос не строится
        finding("F-07", "ambiguity", "unambiguous", "major",
                "Неясно, может ли заёмщик выбрать уменьшение срока вместо платежа", "",
                ["R-04"], [_ev(doc, "срок кредита сохраняется")], status="needs_review"),
        # подтверждена, но опора не совпадает с текстом — ложное срабатывание отсекается
        finding("F-08", "conflict", "correct", "critical", "Комиссия 2% (выдумка модели)", "", ["R-02"],
                [{"block_id": dp2.id, "start": 0, "end": 11, "quote": "Комиссия 2%"}]),
    ]


# ---------------------------------------------------------------------------
# Подставной транспорт этапа clarify
# ---------------------------------------------------------------------------

_SCRIPT: dict[str, dict] = {
    "F-01": {
        "owner": "PO",
        "situation": "ДП-2 запрещает комиссию за досрочное погашение, раздел «Тарифы» требует 1% "
                     "в первые 6 месяцев, а критерий приёмки №1 ожидает 0 ₸ для заявки на третьем месяце.",
        "prompt": "Взимается ли комиссия за досрочное погашение в первые 6 месяцев после выдачи?",
        "why": "От ответа зависят сумма списания, текст в мобильном банке и ожидаемый результат "
               "критерия приёмки №1.",
        "blocks": ["разработку", "тестирование"],
        "author_intent_hypothesis": "Раздел «Тарифы» мог остаться от прежней версии продукта, "
                                    "а ДП-2 отражает новое решение.",
        "options": [
            {"id": "A", "label": "Комиссии нет",
             "interpretation": "Действует ДП-2; раздел «Тарифы» устарел.",
             "observable_result": "Заявка 10 марта на 200 000 ₸ по кредиту от 10 января: списано "
                                  "200 000 ₸, комиссия 0 ₸.",
             "consequences": "Тариф удаляется из расчёта; критерий приёмки №1 остаётся без изменений.",
             "edits": [{"old": TARIFF, "new": "Комиссия за досрочное погашение не взимается."}]},
            {"id": "B", "label": "Комиссия 1% в первые 6 месяцев",
             "interpretation": "Действует раздел «Тарифы»; ДП-2 нужно уточнить.",
             "observable_result": "Та же заявка: списано 200 000 ₸ и комиссия 1% от суммы "
                                  "досрочного погашения.",
             "consequences": "Нужен расчёт комиссии и показ её до подтверждения; критерий №1 меняется.",
             "edits": [
                 {"old": FEE_NO, "new": "Комиссия за досрочное погашение взимается по разделу «Тарифы»."},
                 {"old": FEE_AC, "new": "комиссия 1% от суммы досрочного погашения"},
             ]},
        ],
    },
    "F-03": {
        "owner": "PO",
        "situation": "ДП-3 переносит платёж с выходного на следующий рабочий день, а критерий "
                     "приёмки №2 ожидает списание в предыдущую пятницу.",
        "prompt": "Куда переносится платёж по графику, если дата приходится на выходной?",
        "why": "Определяет дату списания, начисление процентов за перенос и тест-кейс критерия №2.",
        "blocks": ["разработку", "тестирование"],
        "options": [
            {"id": "A", "label": "На следующий рабочий день",
             "interpretation": "Действует ДП-3; критерий приёмки №2 ошибочен.",
             "observable_result": "Дата платежа 15 марта, суббота: платёж списан в следующий рабочий "
                                  "день после 15 марта.",
             "consequences": "Критерий приёмки №2 переписывается под ДП-3.",
             "edits": [{"old": SCHED_AC, "new": "Платёж списан в следующий рабочий день после 15 марта"}]},
            {"id": "B", "label": "На предыдущий рабочий день",
             "interpretation": "Действует критерий приёмки №2; ДП-3 ошибочен.",
             "observable_result": "Дата платежа 15 марта, суббота: платёж списан 14 марта, в пятницу.",
             "consequences": "Меняется правило ДП-3 и расчёт графика.",
             "edits": [{"old": "в следующий рабочий день", "new": "в предыдущий рабочий день"}]},
        ],
    },
    "F-04": {
        "owner": "PO",
        "situation": "ДП-5 использует «банковский день», а раздел «Термины» определяет только "
                     "«рабочий день».",
        "prompt": "«Банковский день» в ДП-5 — это «рабочий день» из раздела «Термины»?",
        "why": "От ответа зависит дата исполнения заявки и тест на заявку в пятницу вечером.",
        "blocks": ["разработку", "тестирование"],
        "document_answer": {"quote": TERM_WORKDAY},
        "options": [
            {"id": "A", "label": "Да, привести ДП-5 к разделу «Термины»",
             "interpretation": "Банковский день = рабочий день по производственному календарю РК.",
             "observable_result": "Заявка в субботу исполняется в ближайший рабочий день по "
                                  "производственному календарю.",
             "consequences": "Один календарь для ДП-3 и ДП-5.",
             "edits": [{"old": "ближайший банковский день", "new": "ближайший рабочий день"}]},
            {"id": "B", "label": "Нет, это отдельное понятие",
             "interpretation": "Банковский день определяется отдельно (например, операционный день банка).",
             "observable_result": "Дата исполнения считается по отдельному календарю, который даст владелец.",
             "consequences": "Нужно определение банковского дня в разделе «Термины».",
             "edits": []},
        ],
    },
    "F-05": {
        "owner": "PO",
        "situation": "ДП-1 допускает частичное досрочное погашение, но не задаёт минимальную сумму.",
        "prompt": "Есть ли минимальная сумма частичного досрочного погашения?",
        "why": "Без ответа нельзя реализовать проверку заявки и написать граничные тесты.",
        "blocks": ["разработку", "тестирование"],
        "options": [
            {"id": "A", "label": "Минимума нет",
             "interpretation": "Любая положительная сумма принимается.",
             "observable_result": "Заявка на частичное погашение любой положительной суммы принимается.",
             "consequences": "Проверка суммы только на положительность.",
             "edits": [{"old": DP1, "new": DP1 + " Минимальная сумма частичного досрочного погашения "
                                               "не ограничивается."}]},
            {"id": "B", "label": "Минимум задаёт тариф",
             "interpretation": "Ниже минимума заявка отклоняется с сообщением.",
             "observable_result": "Заявка ниже минимальной суммы отклоняется с сообщением.",
             "consequences": "Значение минимума должен дать владелец.",
             # модель «подставила» лимит, которого нет в документе: в редакцию не попадёт
             "edits": [{"old": DP1, "new": DP1 + " Минимальная сумма частичного досрочного погашения "
                                               "— 50 000 ₸."}]},
        ],
    },
}


def _block_for(doc: DocView, quote: str) -> str:
    hits = [b.id for b in doc.blocks if quote in b.text]
    return hits[0] if len(hits) == 1 else "?"


def make_scripted_ask(document: Any):
    """Подставной транспорт ``ask`` для синтетического документа."""
    doc = DocView(document)

    def ask(stage: str, payload: dict, schema: dict) -> dict:
        return scripted_answer(doc, stage, payload, schema)

    return ask


def scripted_answer(doc: DocView, stage: str, payload: dict, schema: dict) -> dict:
    """Заранее записанные ответы этапа clarify, проверенные по schema."""
    if stage != "clarify":
        raise ValueError(f"Подставной транспорт знает только этап clarify, получен {stage!r}")
    assert set(payload) == {"task", "input", "context"}, "payload по contracts/HANDOFF.md"
    out: dict[str, list] = {"questions": [], "skipped": []}
    for g in payload["input"]["groups"]:
        ids = [f["id"] for f in g["findings"]]
        key = next((i for i in ids if i in _SCRIPT), None)
        if key is None:
            out["skipped"].append({"group_id": g["group_id"], "reason": "нет сценария"})
            continue
        spec = _SCRIPT[key]
        entry = {k: v for k, v in spec.items() if k not in ("options", "document_answer")}
        entry["group_ids"] = [g["group_id"]]
        entry.setdefault("author_intent_hypothesis", "")
        q = spec.get("document_answer", {}).get("quote", "")
        entry["document_answer"] = {"block_id": _block_for(doc, q) if q else "", "quote": q}
        entry["options"] = []
        for o in spec["options"]:
            edits = [{"block_id": _block_for(doc, e["old"]), "old": e["old"], "new": e["new"]}
                     for e in o["edits"]]
            entry["options"].append({"consequences": "", **o, "edits": edits})
        out["questions"].append(entry)
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        jsonschema = None
    if jsonschema is not None:
        jsonschema.validate(out, schema)
    return out


# ---------------------------------------------------------------------------
# Подставная перепроверка
# ---------------------------------------------------------------------------


def _find(doc: DocView, pattern: str) -> dict | None:
    rx = re.compile(pattern)
    for b in doc.blocks:
        m = rx.search(b.text)
        if m:
            return {"block_id": b.id, "start": m.start(), "end": m.end(), "quote": m.group(0)}
    return None


def recheck(document: Any) -> list[dict]:
    """Правила для синтетического документа: те же четыре проблемы, что F-01…F-05."""
    doc = DocView(document)
    out: list[dict] = []
    fee_yes = _find(doc, r"взимается комиссия \d+(?:[.,]\d+)?\s?%[^.]*")
    fee_no = _find(doc, r"Комиссия за досрочное погашение не взимается\.?")
    fee_ac = _find(doc, r"комиссия 0 ₸")
    if fee_yes and (fee_no or fee_ac):
        other = fee_no or fee_ac
        out.append(finding("N-01", "conflict", "set_consistent", "critical",
                           "Комиссия за досрочное погашение определена по-разному", "Сумма списания неясна.",
                           [], [other, fee_yes], scope="set", witness={
                               "input": "досрочное погашение в первые 6 месяцев",
                               "outcome_a": "без комиссии", "outcome_b": "с комиссией",
                               "evidence_a": other, "evidence_b": fee_yes}))
    s_rule = _find(doc, r"платёж списывается в следующий рабочий день")
    s_ac = _find(doc, r"Платёж списан \d+ марта, в пятницу")
    if s_rule and s_ac:
        out.append(finding("N-02", "conflict", "set_consistent", "critical",
                           "Перенос платежа с выходного определён по-разному", "Дата списания неясна.",
                           [], [s_rule, s_ac], scope="set", witness={
                               "input": "дата платежа в субботу", "outcome_a": "позже", "outcome_b": "раньше",
                               "evidence_a": s_rule, "evidence_b": s_ac}))
    bank = _find(doc, r"ближайший банковский день")
    if bank and not _find(doc, r"^Банковский день —"):
        out.append(finding("N-03", "ambiguity", "unambiguous", "major", "«Банковский день» не определён",
                           "Дата исполнения неясна.", [], [bank]))
    dp1 = _find(doc, r"полное или частичное досрочное погашение")
    if dp1 and not _find(doc, r"Минимальная сумма частичного досрочного погашения"):
        out.append(finding("N-04", "omission", "complete", "major",
                           "Не задана минимальная сумма частичного погашения", "Нет границ для тестов.",
                           [], [dp1]))
    for f in out:
        assert all(doc.verify_evidence(e) for e in as_list(get(f, "evidence")))
    return out
