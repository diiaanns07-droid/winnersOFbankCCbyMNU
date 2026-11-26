"""Синтетический Report контракта v1 для HTML-отчёта (№13).

Документ — текст кейса A+B (``fixtures/case_ab.md``) плюс синтетический раздел с
пограничными случаями: emoji перед цитатой, HTML-подобный текст, CRLF и длинная
таблица. Нарезка повторяет правила HANDOFF: ID ``b0001…``, ``kind`` из перечня
контракта, ``loc.line_start/line_end`` и ``loc.map``. Координаты опор вычисляются
здесь же в кодовых точках, поэтому ``block.text[start:end] == quote`` выполняется
по построению. Отчёт проходит ``contracts.validate`` и ``contracts.evidence_errors``.

Запуск: ``python tests/p13/fixture_builder.py`` перезаписывает
``fixtures/synthetic_report.json``.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASE_MD = HERE / "fixtures" / "case_ab.md"

EMOJI_TEXT = "🔔👨‍👩‍👧 Текст push: «Порог 50 000 ₸ достигнут» — карта •• 4242 ✅"
HTML_TEXT = 'Шаблон push из макета: <b>Порог</b> {amount} ₸ <script>alert("xss")</script> &amp; &lt;i&gt; </div>'
CRLF_TEXT = "Выгрузка из DOCX сохранила CRLF\r\nвторая строка\tс табуляцией и неразрывным пробелом"
SYNTH_TITLE = "Синтетические проверки (не из ТЗ)"


def long_table(rows: int) -> str:
    head = "| № | Parameter | Format | Mandatory | Description |\n| :--- | :--- | :--- | :--- | :--- |"
    body = [
        f"| {i} | `field_{i:03d}` | string | Да / Нет | Поле журнала {i}: значение хранится в тиынах, "
        f"описание {'очень длинное ' * 3}без единиц измерения |"
        for i in range(1, rows + 1)
    ]
    return head + "\n" + "\n".join(body)


def source_text(table_rows: int) -> str:
    case = CASE_MD.read_text(encoding="utf-8").rstrip("\n")
    synth = "\n\n".join(
        [f"## {SYNTH_TITLE}", EMOJI_TEXT, HTML_TEXT, CRLF_TEXT, long_table(table_rows)]
    )
    return case + "\n\n" + synth + "\n"


# --------------------------------------------------------------------------- #
# Простейший «читатель» Markdown, только для фикстуры
# --------------------------------------------------------------------------- #


def split_markdown(md: str) -> list[dict[str, Any]]:
    lines = md.split("\n")
    blocks: list[dict[str, Any]] = []
    section: list[str] = []

    def add(kind: str, text: str, a: int, b: int, col: int = 0, sec: list[str] | None = None) -> None:
        blocks.append(
            {
                "id": f"b{len(blocks) + 1:04d}",
                "kind": kind,
                "section": list(section if sec is None else sec),
                "text": text,
                "loc": {"line_start": a, "line_end": b, "map": [[0, a, col]]},
            }
        )

    i = 0
    while i < len(lines):
        line, n = lines[i], i + 1
        if not line.strip() or line.strip() == "---":
            i += 1
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            parent = (section + [""] * level)[: level - 1]
            add("heading", title, n, n, col=level + 1, sec=[s for s in parent if s])
            section = [s for s in parent if s] + [title]
            i += 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                if j == i:
                    add("table_header", lines[j], j + 1, j + 1)
                elif not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", lines[j].strip()):
                    add("table_row", lines[j], j + 1, j + 1)
                j += 1
            i = j
        elif line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            add("code", "\n".join(lines[i + 1 : j]), i + 2, j)
            i = j + 1
        elif re.match(r"(\* |- |\d+\. )", line):
            add("list_item", line, n, n)
            i += 1
        else:
            j = i
            while (
                j < len(lines)
                and lines[j].strip()
                and not lines[j].startswith(("#", "|", "```", "* ", "- "))
                and not re.match(r"\d+\. ", lines[j])
            ):
                j += 1
            add("paragraph", "\n".join(lines[i:j]), n, j)
            i = j
    return blocks


def build_document(*, table_rows: int = 300) -> dict[str, Any]:
    src = source_text(table_rows)
    return {
        "id": hashlib.sha256(src.encode("utf-8")).hexdigest(),
        "title": "Уведомление о расходах по карте (синтетическая фикстура №13)",
        "format": "markdown",
        "source_name": "case_ab_synthetic.md",
        "blocks": split_markdown(src),
        "warnings": [],
    }


# --------------------------------------------------------------------------- #
# Опоры
# --------------------------------------------------------------------------- #


class Doc:
    def __init__(self, document: dict[str, Any]):
        self.blocks = document["blocks"]

    def find(self, needle: str, *, kind: str | None = None, nth: int = 1) -> dict[str, Any]:
        seen = 0
        for b in self.blocks:
            if needle in b["text"] and (kind is None or b["kind"] == kind):
                seen += 1
                if seen == nth:
                    return b
        raise KeyError(needle)

    def ev(self, quote: str, *, block: dict[str, Any] | None = None, occurrence: int = 1, kind: str | None = None) -> dict[str, Any]:
        b = block or self.find(quote, kind=kind)
        start = -1
        for _ in range(occurrence):
            start = b["text"].index(quote, start + 1)
        ev = {"block_id": b["id"], "start": start, "end": start + len(quote), "quote": quote}
        assert b["text"][ev["start"] : ev["end"]] == quote
        return ev


def finding(fid: str, **kw: Any) -> dict[str, Any]:
    base = {
        "id": fid,
        "scope": "requirement",
        "kind": "other",
        "criterion": "unambiguous",
        "severity": "minor",
        "title": "",
        "impact": "",
        "req_ids": [],
        "hints": [],
        "evidence": [],
        "status": "confirmed",
        "anchor_status": "supported",
        "meaning_status": "confirmed",
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


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def build_report(*, table_rows: int = 300) -> dict[str, Any]:
    document = build_document(table_rows=table_rows)
    doc_id = document["id"]
    d = Doc(document)
    f1, f2, f3, f4 = (d.find(f"**Ф-{i}.**") for i in range(1, 5))
    accept2 = d.find("Февральский счётчик", kind="table_row")
    checklist_row = d.find("Техническое требование зафиксировано", kind="table_row")
    rest_type = d.find("**REST type**", kind="table_row")
    descr = d.find("**Description**", kind="table_row")
    amount_q = d.find("`amount` | integer", kind="table_row")
    amount_r = d.find("`amount` | string", kind="table_row")
    nfr = d.find("в течение минуты")
    emoji = d.find("🔔")
    html_b = d.find("<script>")
    crlf = d.find("CRLF")
    long_row5 = d.find("`field_005`", kind="table_row")

    a1 = d.ev("На карту приходится максимум один такой push за календарный месяц", block=f3)
    b1 = d.ev("следующее достижение вызывает push независимо от истории предыдущей настройки", block=f4)
    a2 = d.ev("Месяц определяется по дате совершения покупки в Алматы", block=f2)
    b2 = d.ev("Февральский счётчик вырос на 4 000 ₸", block=accept2)

    findings = [
        finding(
            "F-001", scope="set", kind="conflict", criterion="set_consistent", severity="critical", stage="cross",
            title="Ф-3 и Ф-4 по-разному решают повторный push в месяце",
            impact="Разработчик выберет одно из правил сам. Тест на повторный push после смены порога даст разный результат.",
            blocked_decision="Реализовать отправку push после изменения порога.",
            blocks=["development", "testing"], req_ids=["R-03", "R-04"], evidence=[a1, b1],
            cause={"object": "Повторный push в месяце", "condition": "push уже был, порог изменён", "outcomes": ["не отправлять", "отправить"]},
            witness={
                "input": "В марте push уже отправлен (расходы 50 000 ₸ при пороге 50 000 ₸). Клиент поднимает порог до 80 000 ₸, расходы растут до 80 000 ₸.",
                "outcome_a": "Push не отправляется: на карту максимум один push за календарный месяц (Ф-3).",
                "outcome_b": "Push отправляется: достижение нового порога вызывает push независимо от истории (Ф-4).",
                "evidence_a": a1, "evidence_b": b1,
            },
            recommendation="Выбрать одно правило и записать его в Ф-3 и Ф-4 одинаково.",
        ),
        finding(
            "F-002", scope="set", kind="conflict", criterion="correct", severity="critical", stage="cross",
            title="Критерий приёмки №2 противоречит правилу месяца в Ф-2",
            impact="Тест по критерию приёмки упадёт на корректной реализации Ф-2 или примет неверную.",
            blocked_decision="Зафиксировать ожидаемый результат теста на стыке месяцев.",
            blocks=["testing"], req_ids=["R-02"], evidence=[a2, b2],
            witness={
                "input": "Покупка на 4 000 ₸ совершена 31 января в 23:58 и проведена 1 февраля в 00:03 по Алматы.",
                "outcome_a": "По Ф-2 сумма относится к январю: месяц определяется по дате совершения покупки.",
                "outcome_b": "По критерию приёмки №2 растёт февральский счётчик.",
                "evidence_a": a2, "evidence_b": b2,
            },
        ),
        finding(
            "F-003", kind="ambiguity", criterion="unambiguous", severity="critical", stage="api",
            title="Неверная сумма описана и как 200 с ERROR, и как 400",
            impact="Клиент приложения не знает, по какому признаку показывать ошибку под полем.",
            blocked_decision="Реализовать обработку ответа saveLimit в приложении.",
            blocks=["development"], req_ids=["R-08"],
            evidence=[
                d.ev('{"result":"ERROR","message":"Проверьте сумму"}', kind="code"),
                d.ev("Ответ в случае, если параметры запроса заполнены неверно"),
            ],
            cause={"object": "Ответ на неверную сумму", "outcomes": ["200 + result=ERROR", "400 Bad Request"]},
        ),
        finding(
            "F-004", kind="design_in_requirement", criterion="feasible", severity="major", source="rules",
            stage="lint", meaning_status="deterministic",
            title="Изменение настройки через GET",
            impact="GET считается безопасным методом: прокси и кэш могут повторить запрос, cardId попадает в логи.",
            req_ids=["R-08"], evidence=[d.ev("**REST type** | GET", block=rest_type)],
            recommendation="Заменить метод на PUT или POST, параметры передать в теле запроса.",
        ),
        finding(
            "F-005", kind="incorrect", criterion="correct", severity="major", source="rules", stage="lint",
            meaning_status="deterministic",
            title="Тип amount: integer в запросе, string в ответе",
            impact="Клиент и сервер по-разному сериализуют порог, автотесты контракта расходятся.",
            req_ids=["R-08"], evidence=[d.ev("`amount` | integer", block=amount_q), d.ev("`amount` | string", block=amount_r)],
        ),
        finding(
            "F-006", scope="set", kind="placeholder", criterion="conforming", severity="minor", source="rules",
            stage="lint", meaning_status="deterministic",
            title="Шаблонные значения «Да / Нет» не выбраны",
            impact="Чек-лист ревью и таблица параметров не дают решения: требование не прослеживается до согласования.",
            evidence=[
                d.ev("Да / Нет", block=checklist_row, occurrence=2),
                d.ev("Да / Нет", block=long_row5),
                d.ev("Документ (версия/дата) в источнике не заполнен"),
            ],
        ),
        finding(
            "F-007", kind="incomplete", criterion="complete", severity="major",
            title="Возврат в другом месяце и после push не описан",
            impact="Неясно, пересчитывать ли закрытый месяц и возвращать ли право на push.",
            req_ids=["R-02"], evidence=[d.ev("Возврат уменьшает расходы месяца исходной покупки", block=f2)],
        ),
        finding(
            "F-008", kind="ambiguity", criterion="unambiguous", severity="critical",
            title="«Проведённая покупка» не определена: авторизация или клиринг",
            impact="Цель «в момент покупки» и НФТ «в течение минуты» несовместимы с подсчётом только по клирингу.",
            blocked_decision="Выбрать событие процессинга, по которому считаются расходы.",
            blocks=["development", "testing"], req_ids=["R-02", "R-05"],
            evidence=[
                d.ev("покупки в Алматы. В расходы входят проведённые покупки", block=f2),
                d.ev("Дать клиенту возможность узнать о достижении личного бюджета в момент покупки"),
            ],
        ),
        finding(
            "F-009", kind="unverifiable", criterion="verifiable", severity="minor",
            status="needs_review", anchor_status="incomplete", meaning_status="uncertain",
            meaning_reason="Модель процитировала формулировку, которой нет в документе; координаты не найдены.",
            title="НФТ: не указано, от какого события считать минуту",
            impact="Требование нельзя проверить нагрузочным тестом без перцентиля и точки отсчёта.",
            req_ids=["R-05"], evidence=[],
            hints=[{"block_id": nfr["id"], "quote": "Сервис передаёт push в течение 60 секунд"}],
        ),
        finding(
            "F-010", scope="set", kind="incomplete", criterion="set_complete", severity="major", stage="cross",
            title="Порог в тенге, покупка в тиынах: правило пересчёта не задано",
            impact="Сравнение суммы с порогом зависит от округления, граничные тесты 49 999,99 ₸ неоднозначны.",
            req_ids=["R-06", "R-08"],
            evidence=[
                d.ev("integer | 32 bit | Да | 1 000–1 000 000 | Порог в тенге", block=amount_q),
                d.ev("сумму покупки в тиынах"),
            ],
        ),
        finding(
            "F-011", scope="set", kind="omission", criterion="set_complete", severity="critical", stage="cross",
            title="Нет метода чтения порога и суммы за месяц",
            impact="Экран не сможет показать текущий порог и «сумму за месяц»: в части B описан только saveLimit.",
            blocked_decision="Сверстать экран «Уведомления» с текущими значениями.",
            blocks=["development"], req_ids=["R-07", "R-08"],
            inspected_block_ids=[b["id"] for b in document["blocks"] if b["section"][:2] == ["Уведомление о расходах по карте", "Часть B. REST API"]][:12],
            evidence=[d.ev("Приложение читает и сохраняет настройки"), d.ev("Функциональные требования: чтение порога", block=descr)],
            merged_from=["C-17", "C-23"],
        ),
        finding(
            "F-012", kind="incomplete", criterion="complete", severity="minor",
            title="Текст push с emoji: формат суммы и маски карты не задан",
            impact="Синтетическая проверка: цитата стоит после emoji, координаты в кодовых точках.",
            evidence=[d.ev("Порог 50 000 ₸ достигнут", block=emoji), d.ev("•• 4242 ✅", block=emoji)],
        ),
        finding(
            "F-013", kind="design_in_requirement", criterion="appropriate", severity="minor",
            title="В шаблоне push HTML-разметка, способ экранирования не описан",
            impact="Синтетическая проверка: HTML-подобный текст источника выводится как текст.",
            evidence=[d.ev('<script>alert("xss")</script>', block=html_b), d.ev("<b>Порог</b>", block=html_b)],
        ),
        finding(
            "F-014", kind="format", criterion="conforming", severity="minor", source="rules", stage="lint",
            meaning_status="deterministic",
            title="Перевод строки CRLF внутри требования",
            impact="Синтетическая проверка: символ CR в тексте блока сохраняется в DOM.",
            evidence=[d.ev("CRLF\r\nвторая", block=crlf)],
        ),
    ]

    requirements = []
    for rid, src_id, blk in [
        ("R-01", "Ф-1", f1), ("R-02", "Ф-2", f2), ("R-03", "Ф-3", f3), ("R-04", "Ф-4", f4),
        ("R-05", None, nfr), ("R-06", None, d.find("Хранить идентификатор карты")),
        ("R-07", None, d.find("Приложение читает и сохраняет")),
    ]:
        text = blk["text"].split("** ", 1)[-1] if src_id else blk["text"]
        requirements.append(
            {
                "id": rid, "source_id": src_id, "text": text, "block_ids": [blk["id"]],
                "evidence": [d.ev(text, block=blk)], "hints": [], "kind": "functional" if src_id else "other",
                "section": blk["section"], "review_status": "reviewed", "review_reason": None,
            }
        )
    requirements.append(
        {
            "id": "R-08", "source_id": None, "text": "Метод saveLimit сохраняет порог и признак включения уведомления.",
            "block_ids": [descr["id"], rest_type["id"], amount_q["id"], amount_r["id"]],
            "evidence": [d.ev("Сохранение порога", block=descr)], "hints": [], "kind": "interface",
            "review_status": "partial", "review_reason": "Таблицы статусов проверены только правилами.",
        }
    )

    questions = [
        {"id": "Q-01", "finding_ids": ["F-001"], "prompt": "Нужен ли повторный push в месяце после изменения порога, если push в этом месяце уже был?",
         "options": ["Да, после изменения порога", "Нет, не более одного push в месяц"], "affected_req_ids": ["R-03", "R-04"]},
        {"id": "Q-02", "finding_ids": ["F-002"], "prompt": "К какому месяцу относится покупка 31.01 23:58, проведённая 01.02 00:03?\nВ каком часовом поясе указано время совершения?",
         "options": ["К январю (дата совершения)", "К февралю (дата проведения)"], "affected_req_ids": ["R-02"]},
        {"id": "Q-03", "finding_ids": ["F-008"], "prompt": "Какое событие процессинга считается «проведённой покупкой»: авторизация или клиринг?",
         "options": ["Авторизация", "Клиринг"], "affected_req_ids": ["R-02", "R-05"]},
        {"id": "Q-04", "finding_ids": ["F-011"], "prompt": "Каким методом приложение читает порог и сумму за месяц?",
         "options": [], "affected_req_ids": ["R-07"]},
        {"id": "Q-05", "finding_ids": ["F-003"], "prompt": "Какой код ответа возвращать при неверной сумме: 400 или 200 с result=ERROR?",
         "options": ["400", "200 с result=ERROR"], "affected_req_ids": ["R-08"]},
    ]
    code_err = d.ev('{"result":"ERROR","message":"Проверьте сумму"}', kind="code")
    decisions = [
        {"question_id": "Q-05", "source_sha256": doc_id,
         "answer": "400 Bad Request с телом {\"result\":\"ERROR\",\"message\":\"Проверьте сумму\"}.",
         "edits": [{"block_id": code_err["block_id"], "start": code_err["start"], "end": code_err["end"],
                    "old": code_err["quote"], "new": '{"result":"OK","amount":"50000","enabled":"1"}'}],
         "note": "Ответ аналитика из answers.md"},
    ]

    checklist = []
    for i, (text, avail, checked, fids) in enumerate(
        [
            ("Техническое требование зафиксировано и покрывает бизнес-требование", "yes", "no", ["F-011"]),
            ("Функциональная спецификация имеет структурированное описание", "yes", "yes", []),
            ("Sequence-диаграммы, предусмотрены взаимодействия систем", "yes", "no", []),
            ("Реализация предусматривает схему отката решений", "no", "no", []),
            ("Требование может быть протестировано", "yes", "no", ["F-002", "F-009"]),
            ("Требование не имеет противоречий", "no", "no", ["F-001", "F-002", "F-003"]),
            ("Структура требований не несёт рисков ИБ", "unknown", "unknown", ["F-004"]),
            ("Поддерживается версионность документа", "na", "no", ["F-006"]),
        ]
    ):
        checklist.append(
            {"id": f"CL-{i + 1:02d}", "text": text, "available": avail, "checked": checked,
             "note": "Отметка проставлена агентом по замечаниям." if fids else "",
             "finding_ids": fids, "evidence": [d.ev(text[:30], block=d.find(text[:30], kind="table_row"))] if i < 2 else []}
        )

    ev_count = sum(len(f["evidence"]) for f in findings)
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")}
    by_status = {s: sum(1 for f in findings if f["status"] == s) for s in ("confirmed", "needs_review")}
    checks = [
        {"req_id": "R-03", "criterion": "verifiable", "status": "pass", "reason": "Исход наблюдаем: push отправлен или нет.", "finding_ids": [], "source": "llm"},
        {"req_id": "R-03", "criterion": "correct", "status": "issue", "reason": "Противоречит Ф-4.", "finding_ids": ["F-001"], "source": "llm"},
        {"req_id": "R-05", "criterion": "verifiable", "status": "issue", "reason": "Нет точки отсчёта.", "finding_ids": ["F-009"], "source": "llm"},
        {"req_id": "R-06", "criterion": "complete", "status": "unknown", "reason": "Этап не вернул ответ.", "finding_ids": [], "source": "llm"},
        {"req_id": "R-08", "criterion": "singular", "status": "na", "reason": "Контракт метода.", "finding_ids": [], "source": "rules"},
    ]
    report = {
        "schema_version": "1.0",
        "run": {
            "run_id": "p13-fixture-0001", "parent_run_id": None, "source_sha256": doc_id,
            "source_name": "case_ab_synthetic.md", "agent_version": "0.1.0+p13-fixture", "agent_commit": None,
            "provider": "mock", "model": "mock-fixture", "requested_model": "mock-fixture", "models_seen": ["mock-fixture"],
            "mode": "mock", "status": "complete", "status_reasons": [],
            "started_at": "2026-11-26T09:00:00Z", "finished_at": "2026-11-26T09:00:04Z", "duration_s": 4.0,
            "calls": {"physical": 0, "cache_hits": 0, "failed": 0, "retries": 0},
            "tokens": {"input": 0, "output": 0, "cache_read": 0},
            "budget": {"max_calls": 40, "max_seconds": 1500.0, "max_tokens": None, "exhausted": False, "reason": None},
            "stages": [
                {"name": "read", "status": "ok", "calls": 0, "cache_hits": 0, "reason": None, "implementation": "fixture"},
                {"name": "individual", "status": "ok", "calls": 0, "cache_hits": 0, "reason": None, "model": "mock-fixture"},
                {"name": "cross", "status": "ok", "calls": 0, "cache_hits": 0, "reason": None, "model": "mock-fixture"},
            ],
            "incomplete_stages": [], "modules": {"html": "bcc_review.exports.html"}, "context_policy": "full",
            "evidence_audit": {"checked": ev_count + 1, "confirmed": ev_count, "ambiguous": 0, "rejected": 1,
                               "note": "Подсказка F-009 не найдена в тексте блока: замечание оставлено как needs_review."},
            "options": {},
        },
        "document": document,
        "requirements": requirements,
        "checks": checks,
        "findings": findings,
        "facts": [
            {"id": "FA-1", "subject": "Порог уведомления", "field": "диапазон", "value": [1000, 1000000], "unit": "KZT",
             "type": "integer", "direction": None, "range": {"min": 1000, "max": 1000000, "inclusive": True},
             "req_ids": ["R-01"], "evidence": [d.ev("от 1 000 до 1 000 000 ₸", block=f1)]},
            {"id": "FA-2", "subject": "Сумма покупки", "field": "единица хранения", "value": "тиын", "unit": "KZT/100",
             "type": None, "direction": None, "range": None, "req_ids": ["R-06"], "evidence": [d.ev("сумму покупки в тиынах")]},
        ],
        "coverage": [
            {"req_id": "R-01", "obligation": "Порог от 1 000 до 1 000 000 ₸", "acceptance_ids": [], "status": "uncovered",
             "explanation": "Нет критерия приёмки на границы 999 / 1 000 / 1 000 000 / 1 000 001.", "hints": [], "evidence": []},
            {"req_id": "R-02", "obligation": "Месяц по дате совершения покупки", "acceptance_ids": ["AC-2"], "status": "conflict",
             "explanation": "Критерий №2 ожидает другой месяц.", "hints": [], "evidence": [b2]},
            {"req_id": "R-03", "obligation": "Push при переходе через порог", "acceptance_ids": ["AC-1"], "status": "covered",
             "explanation": "Критерий №1 проверяет переход 48 500 → 50 000.", "hints": [], "evidence": []},
            {"req_id": "R-04", "obligation": "Push после смены порога", "acceptance_ids": [], "status": "partial",
             "explanation": "Нет критерия на повторный push.", "hints": [], "evidence": []},
        ],
        "questions": questions,
        "checklist": checklist,
        "test_cases": [
            {"id": "TC-01", "precondition": "Расходы 49 999 ₸, порог 50 000 ₸, уведомление включено, push в месяце не было",
             "action": "Провести покупку на 1 ₸", "expected": "Итог 50 000 ₸, отправлен ровно один push", "req_ids": ["R-03"], "open_question_id": None},
            {"id": "TC-02", "precondition": "Push в месяце уже был, порог 50 000 ₸", "action": "Поднять порог до 80 000 ₸ и провести покупки до 80 000 ₸",
             "expected": "Зависит от ответа на Q-01", "req_ids": ["R-03", "R-04"], "open_question_id": "Q-01"},
        ],
        "decisions": decisions,
        "diff": {
            "previous": {"source_sha256": "0" * 64, "run_id": "p13-fixture-0000"},
            "current": {"source_sha256": doc_id, "run_id": "p13-fixture-0001"},
            "resolved": [{"old_ids": ["F-015"], "new_ids": [], "reason": "Код 404 добавлен в список статусов.", "evidence": []}],
            "persisting": [
                {"old_ids": ["F-001"], "new_ids": ["F-001"], "reason": "Ф-3 и Ф-4 не изменились.", "evidence": [a1]},
                {"old_ids": ["F-004", "F-006"], "new_ids": ["F-005"], "reason": "Расхождение типов осталось только у amount.", "evidence": []},
            ],
            "introduced": [
                {"old_ids": [], "new_ids": ["F-012"], "reason": "Новый текст push.", "evidence": []},
                {"old_ids": [], "new_ids": ["F-013"], "reason": "", "evidence": []},
            ],
            "unassessed": [{"old_ids": ["F-020"], "new_ids": [], "reason": "Блок удалён, сопоставить нельзя.", "evidence": []}],
            "impacted_req_ids": ["R-03", "R-04"],
            "warnings": [],
        },
        "verdict": {
            "development": {"status": "not_ready", "reasons": ["Ключевые правила push противоречат друг другу.", "Контракт API saveLimit не определён."],
                            "finding_ids": ["F-001", "F-003", "F-008", "F-011"]},
            "testing": {"status": "not_ready", "reasons": ["Критерий приёмки №2 противоречит Ф-2."], "finding_ids": ["F-002"]},
            "first_actions": [
                {"order": 2, "action": "Определить событие «проведённая покупка» и время его фиксации.", "finding_ids": ["F-008"]},
                {"order": 1, "action": "Решить, допускается ли второй push в месяце после смены порога.", "finding_ids": ["F-001"]},
                {"order": 3, "action": "Добавить метод чтения настроек и закрепить коды ответов saveLimit.", "finding_ids": ["F-011", "F-003"]},
            ],
            "basis": "Начинать разработку и тестирование нельзя: 5 критичных замечаний.",
        },
        "summary": {
            "requirements": len(requirements), "reviewed_requirements": len(requirements) - 1, "findings": len(findings),
            "by_severity": by_sev, "by_status": by_status,
            "critical_ids": [f["id"] for f in findings if f["severity"] == "critical"],
            "checks": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "issue", "unknown", "na")},
        },
        "warnings": [],
        "excluded": [{"block_ids": [d.find("Подразделение", kind="table_header")["id"]], "reason": "Блок согласующих — шаблон, не требование"}],
        "rejected": [{"candidate": {"title": "Слово «быстро» в цели"}, "reason": "Цитата не найдена в документе", "stage": "evidence"}],
    }
    return report


def _resummarize(rep: dict[str, Any]) -> dict[str, Any]:
    f = rep["findings"]
    rep["summary"]["findings"] = len(f)
    rep["summary"]["by_severity"] = {s: sum(1 for x in f if x["severity"] == s) for s in ("critical", "major", "minor")}
    rep["summary"]["by_status"] = {s: sum(1 for x in f if x["status"] == s) for s in ("confirmed", "needs_review")}
    rep["summary"]["critical_ids"] = [x["id"] for x in f if x["severity"] == "critical"]
    return rep


def build_empty_report() -> dict[str, Any]:
    rep = build_report(table_rows=20)
    for key in ("findings", "questions", "checklist", "test_cases", "decisions", "facts", "checks", "coverage", "rejected"):
        rep[key] = []
    rep["diff"] = None
    rep["verdict"] = {
        "development": {"status": "ready", "reasons": ["Замечаний нет."], "finding_ids": []},
        "testing": {"status": "ready", "reasons": ["Замечаний нет."], "finding_ids": []},
        "first_actions": [],
        "basis": "",
    }
    rep["run"]["evidence_audit"] = {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": ""}
    rep["summary"]["checks"] = {s: 0 for s in ("pass", "issue", "unknown", "na")}
    return _resummarize(rep)


def build_partial_report() -> dict[str, Any]:
    rep = build_report(table_rows=20)
    rep["run"]["status"] = "partial"
    rep["run"]["status_reasons"] = ["Модель не ответила на этапе проверки набора."]
    rep["run"]["incomplete_stages"] = ["cross"]
    rep["run"]["stages"][2] = {"name": "cross", "status": "failed", "calls": 3, "cache_hits": 0, "retries": 2, "reason": "overloaded"}
    rep["warnings"] = [{"code": "stage_failed", "message": "Проверка согласованности не выполнена.", "stage": "cross"}]
    tail = [b["id"] for b in rep["document"]["blocks"][-5:]]
    rep["document"]["warnings"] = [{"code": "partial_read", "message": "Хвост таблицы не прочитан.", "block_ids": tail}]
    rep["findings"] = [f for f in rep["findings"] if f["scope"] == "requirement"]
    kept = {f["id"] for f in rep["findings"]}
    rep["questions"] = [q for q in rep["questions"] if set(q["finding_ids"]) <= kept]
    rep["verdict"]["development"] = {"status": "unknown", "reasons": ["Прогон неполный."], "finding_ids": ["F-003", "F-008"]}
    rep["verdict"]["testing"] = {"status": "unknown", "reasons": ["Прогон неполный."], "finding_ids": []}
    rep["verdict"]["first_actions"] = [a for a in rep["verdict"]["first_actions"] if set(a["finding_ids"]) <= kept]
    rep["diff"] = None
    for c in rep["checklist"]:
        c["finding_ids"] = [x for x in c["finding_ids"] if x in kept]
    for c in rep["checks"]:
        c["finding_ids"] = [x for x in c["finding_ids"] if x in kept]
    return _resummarize(rep)


def build_partial_empty_report() -> dict[str, Any]:
    rep = build_empty_report()
    rep["run"]["status"] = "partial"
    rep["run"]["status_reasons"] = ["Прогон прерван по лимиту запросов."]
    rep["run"]["incomplete_stages"] = ["individual", "cross"]
    rep["verdict"]["development"]["status"] = "unknown"
    rep["verdict"]["testing"]["status"] = "unknown"
    return rep


def build_long_report(n_copies: int = 8) -> dict[str, Any]:
    """Длинный документ: текст кейса повторён ``n_copies`` раз, замечания размножены."""
    base = build_report(table_rows=300)
    blocks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for c in range(n_copies):
        mapping = {}
        for b in base["document"]["blocks"]:
            nb = json.loads(json.dumps(b))
            nb["id"] = f"c{c + 1}-{b['id']}"
            nb["section"] = [f"Копия {c + 1}"] + b["section"]
            mapping[b["id"]] = nb["id"]
            blocks.append(nb)
        for f in base["findings"]:
            nf = json.loads(json.dumps(f))  # без общих ссылок между evidence и witness
            nf["id"] = f"{f['id']}-C{c + 1}"
            for ev in nf["evidence"] + nf["hints"]:
                ev["block_id"] = mapping[ev["block_id"]]
            if nf["witness"]:
                for side in ("evidence_a", "evidence_b"):
                    nf["witness"][side]["block_id"] = mapping[nf["witness"][side]["block_id"]]
            nf["inspected_block_ids"] = [mapping[x] for x in nf["inspected_block_ids"]]
            nf["req_ids"] = []
            findings.append(nf)
    rep = base
    rep["document"] = {**base["document"], "blocks": blocks, "title": "Длинный документ (синтетика)"}
    rep["findings"] = findings
    for key in ("requirements", "questions", "facts", "checklist", "decisions", "coverage", "checks", "test_cases", "excluded"):
        rep[key] = []
    rep["diff"] = None
    rep["verdict"]["first_actions"] = []
    rep["verdict"]["development"]["finding_ids"] = []
    rep["verdict"]["testing"]["finding_ids"] = []
    rep["summary"]["requirements"] = rep["summary"]["reviewed_requirements"] = 0
    return _resummarize(rep)


Q_MONTH = {
    "id": "Q-01", "finding_ids": ["F-002"],
    "prompt": "К какому месяцу относится покупка 31.01 23:58, проведённая 01.02 00:03: к месяцу совершения или к месяцу проведения?",
    "options": ["К январю (дата совершения)", "К февралю (дата проведения)"], "affected_req_ids": ["R-02"],
}
Q_EVENT = {
    "id": "Q-02", "finding_ids": ["F-008"],
    "prompt": "Какое событие процессинга считается «проведённой покупкой»: авторизация или клиринг?",
    "options": ["Авторизация", "Клиринг"], "affected_req_ids": ["R-02", "R-05"],
}
Q_PUSH = {
    "id": "Q-01", "finding_ids": ["F-001"],
    "prompt": "Нужен ли повторный push в месяце после изменения порога, если push в этом месяце уже был?",
    "options": ["Да, после изменения порога", "Нет, не более одного push в месяц"], "affected_req_ids": ["R-03", "R-04"],
}
Q_READ = {
    "id": "Q-02", "finding_ids": ["F-011"],
    "prompt": "Каким методом приложение читает порог и сумму за месяц?",
    "options": [], "affected_req_ids": ["R-07"],
}


def build_answers_reports() -> dict[str, dict[str, Any]]:
    """Три прогона одного документа (один SHA) с разными вопросами под одинаковыми Q-ID.

    * ``r1``: Q-01 — месяц учёта покупки, Q-02 — событие «проведённой покупки»;
    * ``r2``: Q-01 — повторный push (другой смысл под тем же ID), Q-02 — тот же вопрос
      о событии с той же привязкой (F-008 и его опоры);
    * ``r3``: тот же вопрос о событии перенумерован в Q-03, Q-02 — новый вопрос.
    """
    base = build_report(table_rows=20)
    base["decisions"] = []
    out = {}
    for name, run_id, questions in (
        ("r1", "p13-answers-run-1", [Q_MONTH, Q_EVENT]),
        ("r2", "p13-answers-run-2", [Q_PUSH, Q_EVENT]),
        ("r3", "p13-answers-run-3", [Q_PUSH, Q_READ, {**Q_EVENT, "id": "Q-03"}]),
    ):
        rep = json.loads(json.dumps(base))
        rep["run"]["run_id"] = run_id
        rep["questions"] = json.loads(json.dumps(questions))
        rep["test_cases"] = [t for t in rep["test_cases"] if t["open_question_id"] is None]
        out[name] = rep
    return out


VARIANTS = {
    "synthetic": build_report,
    "empty": build_empty_report,
    "partial": build_partial_report,
    "partial_empty": build_partial_empty_report,
    "long": build_long_report,
}


if __name__ == "__main__":
    out = HERE / "fixtures" / "synthetic_report.json"
    out.write_text(json.dumps(build_report(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)
