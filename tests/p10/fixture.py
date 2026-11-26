"""Входы по контракту v1 (bcc/integration, contracts/HANDOFF.md) для тестов №10.

Документ по умолчанию читает настоящий загрузчик движка (модуль №01, иначе резервный
``runtime.fallback.text_reader``): блоки ``table_header``/``table_row`` с ячейками через « | »,
``loc.line_start``. Режимы ``rows`` и ``table`` — синтетические загрузчики другого стиля
(сырые строки Markdown с «|», таблица одним блоком) для проверки устойчивости разбора.
Нарезка, замечания, покрытие (№06), вопросы и решения (№08) собраны по учебному кейсу
в форме объектов контракта.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import re
import tempfile
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
CASE_MD = FIX / "case_requirements.md"
CRITERIA = FIX / "criteria.toml"


def _reader():
    for mod in ("bcc_review.readers.text", "bcc_review.runtime.fallback.text_reader"):
        try:
            return importlib.import_module(mod).read_text
        except (ImportError, AttributeError):
            continue
    return None


def read_real(text: str) -> dict:
    """Документ через загрузчик движка (как в ``python -m bcc_review``)."""
    read = _reader()
    if read is None:
        return load_markdown(text)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "requirements.md"
        path.write_bytes(text.encode("utf-8"))
        return read(path)


def load_markdown(text: str | bytes, *, title: str | None = None, table_mode: str = "rows") -> dict:
    """Синтетический Markdown → Document. rows: строка таблицы с «|» = блок; table: таблица = блок."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    lines = raw.decode("utf-8").split("\n")
    blocks: list[dict] = []
    stack: list[tuple[int, str]] = []

    def sec() -> list[str]:
        return [t for _, t in stack]

    def add(kind: str, txt: str, line: int, end: int | None = None, section: list[str] | None = None) -> None:
        loc = {"line_start": line, "line_end": end or line}
        blocks.append({"id": f"b{len(blocks) + 1:04d}", "kind": kind, "section": sec() if section is None else section, "text": txt, "loc": loc})

    i, n = 0, len(lines)
    item = re.compile(r"^\s*(?:[*-]|\d+\.)\s+(.*)$")
    while i < n:
        line, ln = lines[i], i + 1
        st = line.strip()
        if not st or re.fullmatch(r"-{3,}|\*{3,}", st):
            i += 1
            continue
        if st.startswith("```"):
            j = i + 1
            while j < n and not lines[j].strip().startswith("```"):
                j += 1
            add("code", "\n".join(lines[i + 1 : j]), ln + 1, j)
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level, head = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            add("heading", head, ln, section=sec())
            stack.append((level, head))
            i += 1
            continue
        if st.startswith("|"):
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            if table_mode == "table":
                add("other", "\n".join(x.rstrip() for x in lines[i:j]), ln, j)
            else:
                for k in range(i, j):
                    if "-" in lines[k] and set(lines[k].strip()) <= set("|:- "):
                        continue
                    add("table_row", lines[k].rstrip(), k + 1)
            i = j
            continue
        lm = item.match(line)
        if lm:
            add("list_item", lm.group(1).rstrip(), ln)
            i += 1
            continue
        j = i
        while j < n and lines[j].strip() and not lines[j].strip().startswith(("|", "```", "#")) and not item.match(lines[j]):
            j += 1
        add("paragraph", "\n".join(x.rstrip() for x in lines[i:j]), ln, j)
        i = j
    head = next((b["text"] for b in blocks if b["kind"] == "heading"), title or "Документ")
    return {"id": hashlib.sha256(raw).hexdigest(), "title": title or head, "format": "markdown", "blocks": blocks, "warnings": []}


def case_text() -> str:
    return CASE_MD.read_text("utf-8")


def document(mode: str = "reader", text: str | None = None) -> dict:
    text = case_text() if text is None else text
    if mode == "reader":
        return read_real(text)
    return load_markdown(text, table_mode=mode)


def ev(doc: dict, quote: str, near: str | None = None) -> dict:
    """Опора по дословной цитате (при near — в блоке, где есть near)."""
    for b in doc["blocks"]:
        if near and near not in b["text"]:
            continue
        i = b["text"].find(quote)
        if i >= 0:
            return {"block_id": b["id"], "start": i, "end": i + len(quote), "quote": quote}
    raise AssertionError(f"цитата не найдена: {quote!r}")


_REQS = [
    ("R-01", "Ф-1", "Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно. По умолчанию уведомление выключено."),
    ("R-02", "Ф-2", "Месяц определяется по дате совершения покупки в Алматы. В расходы входят проведённые покупки. Возврат уменьшает расходы месяца исходной покупки. Переводы и снятие наличных исключаются."),
    ("R-03", "Ф-3", "Когда расходы переходят от суммы ниже порога к сумме, равной порогу или выше, клиент получает push. На карту приходится максимум один такой push за календарный месяц."),
    ("R-04", "Ф-4", "При изменении порога накопленная сумма сохраняется. Если она ниже нового порога, следующее достижение вызывает push независимо от истории предыдущей настройки."),
    ("R-05", None, "Сервис передаёт push на отправку в течение минуты после получения события."),
    ("R-06", None, "Хранить идентификатор карты, месяц, идентификатор операции, сумму покупки в тиынах, признак отправки и порог в тенге."),
    ("R-07", None, "Приложение читает и сохраняет настройки через дочерний документ «Уведомление о расходах по карте — REST API»."),
    ("R-08", None, "Повторная доставка одного события процессинга сохраняет исходный итог."),
    ("R-09", None, "На экране видны переключатель, поле «Порог, ₸», сумма за месяц и кнопка «Сохранить». При ошибке ввода сообщение появляется под полем."),
    ("R-10", None, "Дать клиенту возможность узнать о достижении личного бюджета в момент покупки."),
    ("R-11", None, "Проверить пользовательскую сессию."),
    ("R-12", None, "Проверить принадлежность карты клиенту."),
    ("R-13", None, "Проверить сумму и переключатель."),
    ("R-14", None, "Заменить настройку и вернуть результат сохранения."),
    ("R-15", None, "При отклонении суммы вернуть прежнее состояние и результат ERROR."),
    ("R-16", None, "Целое число тенге, обе границы включены."),
    ("R-17", None, "Повторное сохранение заменяет действующую настройку."),
    ("R-18", None, "Изменение порога сохраняет накопленные расходы."),
]


def requirements(doc: dict) -> list[dict]:
    """Requirement контракта: id, source_id, text, block_ids, evidence, review_status, review_reason."""
    out = []
    for rid, src, text in _REQS:
        try:
            e = ev(doc, text)
        except AssertionError:
            continue  # в изменённом документе требования может не быть
        out.append({"id": rid, "source_id": src, "text": text, "block_ids": [e["block_id"]], "evidence": [e],
                    "review_status": "reviewed", "review_reason": None})
    return out


def _finding(fid: str, kind: str, criterion: str, severity: str, title: str, evidence: list[dict], *, scope: str = "set",
             req_ids=(), status: str = "confirmed", witness: dict | None = None, impact: str = "", hints=()) -> dict:
    return {"id": fid, "scope": scope, "kind": kind, "criterion": criterion, "severity": severity, "title": title,
            "impact": impact or title, "req_ids": list(req_ids), "hints": list(hints), "evidence": evidence, "status": status,
            "anchor_status": "supported", "meaning_status": "confirmed" if status == "confirmed" else "uncertain",
            "blocks": ["development", "testing"] if severity == "critical" else [], "witness": witness,
            "blocked_decision": "какой результат реализовать и проверять" if severity == "critical" else ""}


def findings(doc: dict) -> list[dict]:
    """Подмножество эталонных дефектов кейса (Finding контракта) со свидетелями конфликтов."""
    f2_month = ev(doc, "Месяц определяется по дате совершения покупки в Алматы.")
    ak2_exp = ev(doc, "Февральский счётчик вырос на 4 000 ₸")
    f3_cap = ev(doc, "На карту приходится максимум один такой push за календарный месяц.")
    f4_over = ev(doc, "Если она ниже нового порога, следующее достижение вызывает push независимо от истории предыдущей настройки.")
    st400 = ev(doc, "Ответ в случае, если параметры запроса заполнены неверно.")
    err200 = ev(doc, '{"result":"ERROR","message":"Проверьте сумму"}')
    return [
        _finding("F-K1", "conflict", "set_consistent", "critical", "Критерий приёмки №2 противоречит Ф-2", [f2_month, ak2_exp],
                 req_ids=["R-02"], impact="неверный расчётный месяц покупки",
                 witness={"input": "Покупка 31 января в 23:58 на 4 000 ₸, проведена 1 февраля в 00:03 по Алматы",
                          "outcome_a": "4 000 ₸ учтены в январе (Ф-2)", "outcome_b": "4 000 ₸ учтены в феврале (критерий приёмки 2)",
                          "evidence_a": f2_month, "evidence_b": ak2_exp}),
        _finding("F-K2", "conflict", "set_consistent", "critical", "Ф-3 противоречит Ф-4", [f3_cap, f4_over], req_ids=["R-03", "R-04"],
                 witness={"input": "push уже был, порог изменён и снова достигнут", "outcome_a": "push нет", "outcome_b": "push есть",
                          "evidence_a": f3_cap, "evidence_b": f4_over}),
        _finding("F-K3", "conflict", "set_consistent", "critical", "Неверная сумма в API описана двумя способами", [st400, err200],
                 req_ids=["R-15"], witness={"input": "amount=999", "outcome_a": "HTTP 400", "outcome_b": "HTTP 200 + ERROR",
                                            "evidence_a": st400, "evidence_b": err200}),
        _finding("F-K4", "omission", "set_complete", "critical", "Нет метода чтения настроек",
                 [ev(doc, "Приложение читает и сохраняет настройки"), ev(doc, "Сохранение порога. Функциональные требования: чтение порога")],
                 req_ids=["R-07"]),
        _finding("F-K5", "ambiguity", "unambiguous", "critical", "«Проведённая покупка» не определена",
                 [ev(doc, "В расходы входят проведённые покупки."), ev(doc, "в момент покупки")], scope="requirement", req_ids=["R-02", "R-10"]),
        _finding("F-S1", "design_in_requirement", "appropriate", "major", "GET для изменения данных: cardId и порог в URL",
                 [ev(doc, "GET", near="REST type")], scope="requirement", impact="параметры оседают в логах прокси — риск ИБ"),
        _finding("F-S16", "terminology", "set_consistent", "major", "Архитектура и sequence называют компоненты по-разному",
                 [ev(doc, "Карточный процессинг → учёт расходов → сервис push."), ev(doc, "Процессинг → сервис расходов: проведена покупка.")]),
        _finding("F-S16b", "incomplete", "set_complete", "major", "BPMN линейная, без ветвей",
                 [ev(doc, "Проведение покупки → пересчёт расходов → проверка порога → при достижении отправка push → завершение.")]),
        _finding("F-S17", "incomplete", "complete", "major", "UI: нет выбора карты и текстов ошибок",
                 [ev(doc, "При ошибке ввода сообщение появляется под полем.")], scope="requirement", req_ids=["R-09"]),
        _finding("F-S7", "omission", "complete", "major", "Требования к данным неполны",
                 [ev(doc, "Хранить идентификатор карты, месяц, идентификатор операции, сумму покупки в тиынах, признак отправки и порог в тенге.")],
                 scope="requirement", req_ids=["R-06"]),
        _finding("F-S13", "unverifiable", "verifiable", "major", "НФТ непроверяемо",
                 [ev(doc, "Сервис передаёт push на отправку в течение минуты после получения события.")], scope="requirement", req_ids=["R-05"]),
        _finding("F-M1", "format", "conforming", "minor", "У НФТ нет идентификатора", [ev(doc, "Сервис передаёт push на отправку")],
                 scope="requirement", req_ids=["R-05"]),
        _finding("F-M2", "placeholder", "traceable", "minor", "Версия и дата документа не заполнены",
                 [ev(doc, "Документ (версия/дата) в источнике не заполнен.")]),
        _finding("F-R1", "ambiguity", "unambiguous", "minor", "«в Алматы» вместо UTC+5", [], scope="requirement", req_ids=["R-02"],
                 status="needs_review", hints=[{"block_id": f2_month["block_id"], "quote": "в Алматы"}]),
    ]


def coverage() -> list[dict]:
    """Coverage №06 (контракт v1): непокрытое обязательство — obligation со статусом uncovered|partial."""
    return [
        {"req_id": "R-01", "obligation": "граница 999 / 1 000 / 1 000 000 / 1 000 001 ₸", "acceptance_ids": [], "status": "uncovered",
         "explanation": "критерии приёмки не проверяют границы порога"},
        {"req_id": "R-01", "obligation": "значение по умолчанию: уведомление выключено", "acceptance_ids": [], "status": "uncovered",
         "explanation": "нет критерия"},
        {"req_id": "R-03", "obligation": "push при достижении порога", "acceptance_ids": ["AC-1"], "status": "covered",
         "explanation": "критерий 1"},
        {"req_id": "R-04", "obligation": "изменение порога при накопленной сумме выше нового порога", "acceptance_ids": [],
         "status": "partial", "explanation": "случай не описан"},
        {"req_id": "R-08", "obligation": "повторная доставка события", "acceptance_ids": [], "status": "uncovered", "explanation": ""},
    ]


def questions() -> list[dict]:
    """Question №08 (контракт v1) по подтверждённым конфликтам."""
    return [
        {"id": "Q-01", "finding_ids": ["F-K1"], "prompt": "Какой месяц у покупки 31.01 23:58, проведённой 01.02 00:03?",
         "options": ["январь", "февраль"], "affected_req_ids": ["R-02"]},
        {"id": "Q-02", "finding_ids": ["F-K2"], "prompt": "Второй push после смены порога в том же месяце?",
         "options": ["нет", "да"], "affected_req_ids": ["R-03", "R-04"]},
        {"id": "Q-03", "finding_ids": ["F-K3"], "prompt": "Код ответа на неверную сумму: 400 или 200 + ERROR?",
         "options": ["400", "200 + ERROR"], "affected_req_ids": ["R-15"]},
    ]


def decisions(doc: dict | None = None) -> list[dict]:
    """Decision №08 (контракт v1) после --answers: question_id, source_sha256, answer, edits, note."""
    sha = (doc or {}).get("id") or hashlib.sha256(CASE_MD.read_bytes()).hexdigest()
    return [
        {"question_id": "Q-01", "source_sha256": sha, "answer": "A", "edits": [], "note": "Месяц — по дате совершения покупки: январь"},
        {"question_id": "Q-CHK-09", "source_sha256": sha, "answer": "Да", "edits": [], "note": "Архитектура согласована архитектором 20.11.2026"},
        {"question_id": "Q-03", "source_sha256": sha, "answer": "вариант A", "edits": [], "note": "Неверная сумма — HTTP 400"},
    ]


def case(mode: str = "reader", text: str | None = None) -> dict:
    doc = document(mode, text)
    return {"document": doc, "requirements": requirements(doc), "findings": findings(doc) if text is None else []}


def variant(**replacements: str) -> str:
    """Текст кейса с заменами old→new; каждая замена обязана сработать."""
    return replace_all(list(replacements.items()))


def replace_all(pairs: list[tuple[str, str]]) -> str:
    text = case_text()
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    return text


def clone(x):
    return copy.deepcopy(x)
