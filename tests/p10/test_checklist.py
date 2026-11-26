"""Чек-лист банка: строки шаблона, допустимые отметки, наличие ≠ проверка ≠ согласование."""

from __future__ import annotations

import pytest

from . import fixture as fx
from bcc_review.bank import build_bank_pack, collect_questions
from bcc_review.bank.checklist import Doc, parse_options

SOURCE_ROWS = [
    ("Техническое требование зафиксировано и покрывает бизнес-требование", ["Да", "Нет"], ""),
    ("Функциональная спецификация имеет структурированное описание (по стандарту, шаблону)", ["Да", "Нет"], ""),
    ("Sequence-диаграммы, предусмотрены взаимодействия систем, компонентов и решений", ["Да", "Нет", "Не требуется"], ""),
    ("Требование покрывает спецификацию UX/UI дизайна", ["Да", "Нет", "Не требуется"], ""),
    ("Реализация задачи/проекта предусматривает схему отката решений", ["Да", "Нет", "Не требуется"],
     "При невозможности отката — варианты скрытия функционала"),
    ("Требование может быть протестировано", ["Да", "Нет"], ""),
    ("Требование предусматривает модель данных или поток, содержит описание", ["Да", "Нет", "Не требуется"], ""),
    ("Требование не имеет противоречий или явных показателей операционных рисков", ["Да", "Нет"], ""),
    ("Требование содержит архитектуру и согласовано с архитекторами", ["Да", "Нет", "Не требуется"], "Для архитектуры — чек-лист"),
    ("Все изменения, влияющие на иные продукты/системы в требовании, согласованы с ответственными лицами", ["Да", "Нет", "Не требуется"], ""),
    ("Структура требований не несёт изменений и рисков информационной безопасности", ["Да", "Нет"], "По информационной безопасности — чек-лист"),
    ("В требовании присутствует схема полного бизнес-процесса и часть реализуемой доработки", ["Да", "Нет"], ""),
    ("Требование носит интеграционный характер и имеет четкую постановку реализации интеграционного взаимодействия",
     ["Да", "Нет", "Не требуется"], ""),
    ("Поддерживается версионность документа / зафиксирована", ["Да", "Нет"], ""),
]
MARKS = {"Да": "yes", "Нет": "no", "Не требуется": "na", None: "unknown"}


def pack_for(mode: str = "reader", **kw):
    c = fx.case(mode)
    args = dict(coverage=fx.coverage(), questions=fx.questions(), criteria=fx.CRITERIA, complete=True)
    args.update(kw.pop("extra", {}))
    findings, decisions, ask = kw.pop("findings", c["findings"]), kw.pop("decisions", []), kw.pop("ask", None)
    args.update(kw)
    return c, build_bank_pack(c["document"], c["requirements"], findings, decisions, ask, **args)


def assert_evidence(doc: dict, evs):
    d = Doc(doc)
    for e in evs:
        assert d.ev_valid(e), e


@pytest.mark.parametrize("mode", ["reader", "rows", "table"])
def test_all_14_template_rows_in_source_order_with_allowed_marks(mode):
    _, pack = pack_for(mode)
    rows = pack["checklist"]
    assert len(rows) == 14
    for i, (row, (text, allowed, note)) in enumerate(zip(rows, SOURCE_ROWS, strict=True), 1):
        assert row["position"] == i and row["id"] == f"CHK-{i:02d}"
        assert row["text"] == text
        assert row["allowed"]["available"] == allowed and row["allowed"]["checked"] == allowed
        assert row["source_note"] == note
        for key in ("available", "checked"):
            tok = row["cells"][key]
            assert tok is None or tok in row["allowed"][key]
            assert row[key] == MARKS[tok]  # отметка контракта соответствует исходному токену
        assert row["source"]["columns"] == {"text": "Проверка", "available": "Создано или доступно", "checked": "Проверено", "note": "Примечания"}


def test_rows_validate_against_contract_v1():
    contracts = pytest.importorskip("bcc_review.contracts")
    _, pack = pack_for(decisions=fx.decisions())
    for row in pack["checklist"]:
        contracts.validate(row, "ChecklistRow")
    for q in collect_questions(pack):
        contracts.validate(q, "Question")
    for w in pack["warnings"]:
        contracts.validate(w, "Warning")


def test_parse_options_keeps_source_spelling_and_rejects_prose():
    assert parse_options("Да / Нет / Не требуется") == ["Да", "Нет", "Не требуется"]
    assert parse_options("Да / Нет / N/A") == ["Да", "Нет", "N/A"]
    assert parse_options("Да") == ["Да"]
    assert parse_options("Данные клиента") is None
    assert parse_options("Нет данных") is None
    assert parse_options("") is None


def test_approval_row_has_separate_presence_and_confirmation():
    c, pack = pack_for()
    row = pack["checklist"][8]
    assert row["topic"] == "architecture"
    assert row["available"] == "yes" and row["cells"]["available"] == "Да"
    assert row["presence"]["evidence"][0]["quote"].startswith("Мобильное приложение → сервис настроек")
    assert row["checked"] == "unknown" and row["cells"]["checked"] is None
    assert row["approval"]["required"] and row["approval"]["status"] == "requires_confirmation"
    assert "требует подтверждения" in row["note"]
    assert row["approval"]["role"] == "архитекторами"
    # Машинная проверка архитектуры отделена от согласования: дефект виден, но «Проверено» не заполняет.
    assert row["machine"]["value"] == "no" and "F-S16" in row["machine"]["blocking_finding_ids"]
    assert row["status"] == "needs_confirmation"
    assert row["question"]["id"] == "Q-CHK-09" and row["question"]["options"] == ["Да", "Нет", "Не требуется"]
    assert "строка 91" in row["note"]  # пустой блок согласующих
    assert_evidence(c["document"], row["evidence"])
    impact = pack["checklist"][9]
    assert impact["available"] == "yes" and impact["checked"] == "unknown"
    assert "Влияние на ИС" in impact["presence"]["evidence"][0]["quote"]
    assert {q["id"] for q in collect_questions(pack)} >= {"Q-CHK-09", "Q-CHK-10"}


def test_case_row_values_follow_evidence_and_findings():
    c, pack = pack_for()
    r = {row["position"]: row for row in pack["checklist"]}
    assert (r[5]["cells"]["available"], r[5]["cells"]["checked"]) == ("Нет", "Нет")  # отката нет нигде
    assert r[5]["presence"]["inspected_block_ids"], "основание «нет» — перечень проверенных блоков"
    assert r[14]["available"] == "no" and "версия/дата" in r[14]["evidence"][0]["quote"]
    assert r[8]["checked"] == "no" and {"F-K1", "F-K2", "F-K3"} <= set(r[8]["machine"]["blocking_finding_ids"])
    assert r[6]["available"] == "yes" and "48 500" in r[6]["presence"]["evidence"][0]["quote"]
    assert r[6]["checked"] == "no" and "F-S13" in r[6]["finding_ids"]
    assert r[11]["checked"] == "no" and "F-S1" in r[11]["finding_ids"] and "чек-лист" in r[11]["note"]
    assert (r[2]["available"], r[2]["checked"]) == ("yes", "yes") and "F-M1" in r[2]["note"]
    assert r[13]["checked"] == "no" and "F-K4" in r[13]["finding_ids"]
    for row in pack["checklist"]:
        assert_evidence(c["document"], row["evidence"] + [row["source"]["evidence"]])


def test_presence_is_not_taken_from_checklist_row_itself():
    """Ложное срабатывание: строка шаблона «Sequence-диаграммы…» не доказывает наличие раздела."""
    text = fx.variant(**{
        "### Sequence Diagram\nПроцессинг → сервис расходов: проведена покупка. Сервис расходов → настройки: получить порог карты. "
        "Сервис расходов → push: передать последние четыре цифры карты и сумму при достижении порога.\n\n": ""})
    doc = fx.read_real(text)
    pack = build_bank_pack(doc, fx.requirements(doc), [], [], None, criteria=fx.CRITERIA)
    seq = pack["checklist"][2]
    assert seq["topic"] == "sequence" and seq["cells"]["available"] == "Нет" and seq["cells"]["checked"] == "Нет"


def test_without_bank_table_absence_is_explicit_and_api_tables_are_not_mistaken():
    text = fx.case_text()
    start = text.index("### Ревью требований")
    end = text.index("### Блок согласующих")
    doc = fx.read_real(text[:start] + text[end:])
    pack = build_bank_pack(doc, fx.requirements(doc), [], [], None, criteria=fx.CRITERIA)
    assert pack["checklist"] == []
    codes = [w["code"] for w in pack["warnings"]]
    assert "bank.checklist_absent" in codes
    assert any("нет исходного банковского чек-листа" in str(w) for w in pack["warnings"])
    assert pack["test_cases"], "сценарии строятся и без чек-листа"


CUSTOM = """# Сервис выписок

## Общие сведения
| Поле | Значение |
| :--- | :--- |
| **Влияние на ИС** | нет |

## Требования к интеграции
Сервис выписок отдаёт выписку через REST API `GET /statements`.

## Нефункциональные требования
Ответ не более 2 секунд.

## Чек-лист
| Пункт | Выполнено | Комментарий |
| :--- | :--- | :--- |
| Требование покрывает спецификацию UX/UI дизайна | Да / Нет / Н/П | |
| Изменения, влияющие на иные продукты, согласованы с ответственными | Да / Нет / Н/П | |
| Учтены требования регулятора к хранению выписок | Да / Нет | |
| Схема отката описана | Да | |
"""


@pytest.mark.parametrize("mode", ["reader", "rows"])
def test_other_template_rows_marks_and_not_required_basis(mode):
    doc = fx.document(mode, CUSTOM)
    calls = []

    def ask(stage, payload, schema):
        calls.append(stage)
        assert set(payload) <= {"task", "input", "context"} and payload["task"]
        assert [r["position"] for r in payload["input"]["rows"]] == [3]
        assert schema["additionalProperties"] is False
        return {"rows": [{"position": 3, "topic": "none", "requires_approval": False, "available": "Да", "basis": "есть",
                          "hints": [{"block_id": "b9999", "quote": "хранение выписок"}]}]}

    pack = build_bank_pack(doc, [], [], [], ask, criteria=fx.CRITERIA)
    rows = pack["checklist"]
    assert [r["text"] for r in rows] == [
        "Требование покрывает спецификацию UX/UI дизайна",
        "Изменения, влияющие на иные продукты, согласованы с ответственными",
        "Учтены требования регулятора к хранению выписок",
        "Схема отката описана",
    ]
    # В шаблоне одна колонка отметок: она становится «checked», колонки наличия нет.
    assert rows[0]["allowed"] == {"available": [], "checked": ["Да", "Нет", "Н/П"]}
    assert rows[2]["allowed"]["checked"] == ["Да", "Нет"]
    ui = rows[0]
    assert ui["cells"]["checked"] == "Н/П" and ui["checked"] == "na"
    assert ui["not_required_basis"] and "не затрагивается" in ui["not_required_basis"]
    impact = rows[1]
    assert impact["approval"]["status"] == "not_required" and impact["cells"]["checked"] == "Н/П"
    assert "«нет»" in impact["not_required_basis"]
    assert calls == ["bank#checklist"]
    # Цитата модели не нашлась в документе — отметка снята, строка помечена нераспознанной.
    assert rows[2]["checked"] == "unknown" and rows[2]["topic"] is None
    codes = [w["code"] for w in pack["warnings"]]
    assert "bank.llm_rejected" in codes and "bank.row_unclassified" in codes
    # Автор отметил «Да» там, где описания нет: исходная отметка сохранена, расхождение в примечании.
    rb = rows[3]
    assert rb["source_value"]["checked"] == "Да" and rb["cells"]["checked"] == "Нет"
    assert "Автор отметил «Да»" in rb["note"]


def test_llm_row_classification_with_verified_quote():
    doc = fx.read_real(CUSTOM)
    target = next(b for b in doc["blocks"] if "REST API" in b["text"])

    def ask(stage, payload, schema):
        return {"rows": [{"position": 3, "topic": "integration", "requires_approval": False, "available": "Да",
                          "basis": "интеграция описана", "hints": [{"block_id": target["id"], "quote": "через REST API"}]}]}

    pack = build_bank_pack(doc, [], [], [], ask, criteria=fx.CRITERIA)
    row = pack["checklist"][2]
    assert row["method"] == "llm" and row["topic"] == "integration"
    assert row["presence"]["evidence"][0]["quote"] == "через REST API"


def test_owner_decision_confirms_approval_with_reason():
    c, before = pack_for()
    _, after = pack_for(decisions=fx.decisions(c["document"]), previous=before)
    row = after["checklist"][8]
    assert row["checked"] == "yes" and row["cells"]["checked"] == "Да"
    assert row["approval"]["status"] == "confirmed" and row["approval"]["decision_id"] == "answer:Q-CHK-09"
    ch = [c for c in row["changes"] if c["field"] == "checked"]
    assert ch and ch[0]["before"] is None and ch[0]["after"] == "Да" and "согласована архитектором" in ch[0]["reason"]
    assert row["status"] == "filled" and "Q-CHK-09" not in {q["id"] for q in collect_questions(after)}


def test_recheck_after_answers_recalculates_rows_with_reasons():
    c, before = pack_for()
    fixed = [f for f in c["findings"] if f["kind"] != "conflict" and f["id"] != "F-S16"]
    _, after = pack_for(findings=fixed, previous=before)
    row = after["checklist"][7]
    assert before["checklist"][7]["checked"] == "no" and row["checked"] == "yes"
    ch = next(ch for ch in row["changes"] if ch["field"] == "checked")
    assert (ch["before"], ch["after"]) == ("Нет", "Да")
    assert "замечания сняты после перепроверки" in ch["reason"] and "F-K1" in ch["reason"]


def test_incomplete_run_never_claims_positive():
    _, pack = pack_for(findings=[], complete=False)
    for row in pack["checklist"]:
        if row["machine"] and row["machine"]["value"] == "unknown":
            assert "не полностью" in row["machine"]["basis"]
    assert pack["checklist"][1]["checked"] == "unknown"  # структура без замечаний, но проверка неполная


def test_without_model_positive_marks_are_not_claimed_by_default():
    """Без ask семантика не проверялась: «Да» по отсутствию замечаний не ставится, «Нет» по замечаниям — ставится."""
    c = fx.case()
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], [], None, criteria=fx.CRITERIA)
    r = {row["position"]: row for row in pack["checklist"]}
    assert r[2]["checked"] == "unknown" and r[8]["checked"] == "no" and r[5]["checked"] == "no"
    empty = build_bank_pack(c["document"], c["requirements"], [], [], None, criteria=fx.CRITERIA)
    assert all(row["checked"] != "yes" for row in empty["checklist"])


def test_criteria_toml_drives_row_mapping():
    c = fx.case()
    finding = {"id": "F-X", "kind": "omission", "criterion": "flagging", "severity": "major", "status": "confirmed",
               "title": "Нет флага скрытия", "evidence": [fx.ev(c["document"], "По умолчанию уведомление выключено.")]}
    crit = {"criteria": {"flagging": {"code": "X1", "bank_topics": ["rollback"]}}}
    pack = build_bank_pack(c["document"], c["requirements"], [finding], [], None, criteria=crit)
    assert "F-X" in pack["checklist"][4]["finding_ids"]
    pack2 = build_bank_pack(c["document"], c["requirements"], [finding], [], None, criteria={"criteria": {"flagging": {"code": "X1"}}})
    assert "F-X" not in pack2["checklist"][4]["finding_ids"]
    assert "bank.criteria_no_bank_topics" in [w["code"] for w in pack2["warnings"]]


def test_engine_positional_call_and_string_warnings():
    """Движок зовёт модуль позиционно и пишет str(w) в Report.warnings."""
    c = fx.case()
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], fx.decisions(c["document"]), None)
    assert len(pack["checklist"]) == 14 and pack["test_cases"]
    for w in pack["warnings"]:
        assert not str(w).startswith("{") and "bank:" not in str(w)  # без модели этап не «деградировал»

    def broken(stage, payload, schema):
        raise RuntimeError("503")

    doc = fx.read_real(CUSTOM)
    pack2 = build_bank_pack(doc, [], [], [], broken)
    assert any(str(w).startswith("bank: ") for w in pack2["warnings"])  # движок отметит этап partial


def test_team_criteria_toml_checklist_rows_link_criteria():
    """criteria.toml №05: строка шаблона ↔ CL-запись по match; критерии строки отбирают замечания."""
    team = pytest.importorskip("bcc_review.criteria")
    if not getattr(team.load_criteria(), "checklist", None):
        pytest.skip("в criteria.toml №05 нет [[checklist]]")
    c = fx.case()
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], [], None, questions=fx.questions(), complete=True)
    rows = pack["checklist"]
    assert [r["criteria_link"]["checklist_id"] for r in rows] == [f"CL{i:02d}" for i in range(1, 15)]
    r = {row["position"]: row for row in rows}
    assert {"F-K1", "F-K2", "F-K3"} <= set(r[8]["machine"]["blocking_finding_ids"])  # correct, set_consistent
    assert "F-K4" in r[1]["machine"]["blocking_finding_ids"]  # set_complete → покрытие бизнес-требования
    # ИБ (CL11: complete, feasible): замечания о UI и данных по критерию «complete» к ИБ не относятся,
    # а GET с параметрами в URL — относится по сути замечания.
    assert not {"F-S7", "F-S17"} & set(r[11]["finding_ids"]) and "F-S1" in r[11]["finding_ids"]
    # Артефакт (CL04 UX/UI: set_complete): нужна опора в разделе UI, критерий сам по себе не переносит K4.
    assert "F-K4" not in r[4]["finding_ids"] and "F-S17" in r[4]["finding_ids"]
