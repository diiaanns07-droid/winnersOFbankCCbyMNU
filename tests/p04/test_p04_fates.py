"""Набор 2. Судьба каждого блока: таблица приёмки, незаполненный чек-лист, поле подписи.

Критерии приёмки остаются доступными сквозной проверке (kind=acceptance). Чек-лист ревью
и блок согласования исключаются с причиной и ID блоков. Подпись никогда не становится
функциональным требованием — ни по правилам, ни когда модель пытается её так назвать.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bcc_review.analysis.inventory import build_inventory
from p04_support import QuoteModel, ScriptedModel, assert_invariants, block_by_text, fates, md_document

MACRO_MD = """# Заявка на отпуск

## Цели

Сократить время согласования отпуска.

## Требования

1. Сотрудник подаёт заявку не позднее чем за 14 дней до начала отпуска.
2. Руководитель согласует заявку в течение 3 дней.

## Критерии приёмки

| Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| До отпуска 20 дней | Подать заявку | Заявка принята |
| До отпуска 10 дней | Подать заявку | Заявка отклонена |

## Ревью требований

| Проверка | Выполнено | Примечания |
| :--- | :--- | :--- |
| Требование может быть протестировано | Да / Нет | |
| Требование не имеет противоречий | Да / Нет | |

## Согласование

| Подразделение | ФИО | Подпись |
| :--- | :--- | :--- |
| | | |
"""

MACRO_SPEC = {
    "items": [
        {"kind": "functional", "source_id": "1", "text": "Заявка подаётся не позднее чем за 14 дней до отпуска",
         "quotes": ["Сотрудник подаёт заявку не позднее чем за 14 дней до начала отпуска"]},
        {"kind": "functional", "source_id": "2", "text": "Руководитель согласует заявку не дольше 3 дней",
         "quotes": ["Руководитель согласует заявку в течение 3 дней"]},
        {"kind": "acceptance", "source_id": None, "text": "За 20 дней до отпуска заявка принимается",
         "quotes": ["До отпуска 20 дней", "Заявка принята"]},
        {"kind": "acceptance", "source_id": None, "text": "За 10 дней до отпуска заявка отклоняется",
         "quotes": ["До отпуска 10 дней", "Заявка отклонена"]},
    ],
    "excluded": [{"category": "goal", "reason": "Цель", "contains": ["Сократить время согласования"]}],
    "facts": [],
}


def _doc():
    return md_document(MACRO_MD, "macro.md")


def _approval_ids(doc):
    return {block_by_text(doc, "| Подразделение")["id"], block_by_text(doc, "| | | |")["id"]}


def _checklist_ids(doc):
    return {b["id"] for b in doc["blocks"] if "Да / Нет" in b["text"] or b["text"].startswith("| Проверка")}


def test_every_block_has_clear_fate_rules_only():
    doc = _doc()
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    assert inv["unprocessed_block_ids"] == []
    assert inv["block_coverage"]["level"] == "complete" and inv["block_coverage"]["accounted_ratio"] == 1.0
    f = fates(inv)
    for b in doc["blocks"]:
        if b["kind"] == "heading":
            assert f[b["id"]] == "excluded"
    groups = {g["category"]: g for g in inv["excluded"]}
    assert set(groups["approval"]["block_ids"]) == _approval_ids(doc)
    assert set(groups["review_checklist"]["block_ids"]) == _checklist_ids(doc)
    assert "не выбраны" in groups["review_checklist"]["reason"]
    assert "подпис" in groups["approval"]["reason"].lower()
    assert groups["goal"]["block_ids"] == [block_by_text(doc, "Сократить время")["id"]]
    for g in inv["excluded"]:
        assert g["reason"] and g["block_ids"]
    assert groups["review_checklist"]["cross_check"] is True  # незаполненный чек-лист нужен проверке набора


def test_acceptance_rows_stay_available_for_cross_check():
    doc = _doc()
    for inv in (build_inventory(doc), build_inventory(doc, QuoteModel(MACRO_SPEC, doc))):
        acc = [r for r in inv["requirements"] if r["kind"] == "acceptance"]
        assert len(acc) == 2
        assert [r["source_ref"] for r in acc] == ["Критерии приёмки › строка 1", "Критерии приёмки › строка 2"]
        header = block_by_text(doc, "| Исходные условия")["id"]
        assert fates(inv)[header] == "excluded"
        assert all(header not in r["block_ids"] for r in acc)
        functional = [r for r in inv["requirements"] if r["kind"] == "functional"]
        assert [r["source_id"] for r in functional] == ["1", "2"]


def test_signature_never_becomes_functional_requirement():
    doc = _doc()
    sign_row = block_by_text(doc, "| | | |")["id"]
    header = block_by_text(doc, "| Подразделение")["id"]
    checklist_row = block_by_text(doc, "Требование может быть протестировано")["id"]
    bad = {
        "items": [
            {"source_id": None, "kind": "functional", "text": "Ответственный ставит подпись",
             "evidence": [{"block_id": header, "quote": "Подпись"}]},
            {"source_id": None, "kind": "functional", "text": "Требование тестируемо",
             "evidence": [{"block_id": checklist_row, "quote": "Требование может быть протестировано"}]},
        ],
        "excluded": [],
        "facts": [],
        "done": True,
    }
    model = ScriptedModel([bad, {"items": [], "excluded": [], "facts": [], "done": True}])
    inv = build_inventory(doc, model)
    assert_invariants(doc, inv)
    # шаблонные блоки не отдаются модели как обрабатываемые
    sent = {b["id"] for b in model.calls[0]["payload"]["input"]["blocks"] if b["process"]}
    assert not (sent & (_approval_ids(doc) | _checklist_ids(doc)))
    assert all(sign_row not in r["block_ids"] and header not in r["block_ids"] for r in inv["requirements"])
    assert not any(r["text"] == "Ответственный ставит подпись" for r in inv["requirements"])
    assert inv["block_coverage"]["evidence"]["items_rejected"] == 2
    assert any("шаблон" in w["message"] for w in inv["warnings"])
    assert fates(inv)[sign_row] == "excluded"


def test_template_tables_detected_by_header_without_section_name():
    md = ("# Док\n\n## Раздел X\n\n| Роль | Имя | Дата | Подпись |\n| --- | --- | --- | --- |\n"
          "| Руководитель | | | |\n\n## Раздел Y\n\n| Пункт | Статус |\n| --- | --- |\n"
          "| Описание полное | Да / Нет / Не требуется |\n")
    doc = md_document(md)
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    cats = {g["category"] for g in inv["excluded"]}
    assert {"approval", "review_checklist"} <= cats
    assert inv["requirements"] == []


@dataclass
class _Blk:
    id: str
    kind: str
    section: list[str]
    text: str
    loc: dict = field(default_factory=dict)


@dataclass
class _Doc:
    id: str
    title: str
    format: str
    blocks: list[_Blk]
    warnings: list[str] = field(default_factory=list)


def test_docx_cells_and_attribute_objects_are_supported():
    """Document как объект с атрибутами; DOCX-ячейки собираются в строки по loc.row."""
    sec = ["Критерии приёмки"]
    cells = []
    rows = [["Исходные условия", "Действие", "Ожидаемый результат"],
            ["Баланс 0 ₸", "Списать 10 ₸", "Отказ"],
            ["Баланс 50 ₸", "Списать 10 ₸", "Остаток 40 ₸"]]
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            cells.append(_Blk(f"t0/r{r}/c{c}", "table_cell", sec, text, {"table": 0, "row": r, "col": c}))
    doc = _Doc("sha", "Кейс DOCX", "docx", [_Blk("p0", "heading", sec, "Критерии приёмки")] + cells)
    inv = build_inventory(doc)
    acc = [r for r in inv["requirements"] if r["kind"] == "acceptance"]
    assert len(acc) == 2
    assert acc[0]["block_ids"] == ["t0/r1/c0", "t0/r1/c1", "t0/r1/c2"]
    assert [h["quote"] for h in acc[1]["hints"]] == ["Баланс 50 ₸", "Списать 10 ₸", "Остаток 40 ₸"]
    assert {b["block_id"] for b in inv["block_coverage"]["blocks"] if b["fate"] == "excluded"} == {
        "p0", "t0/r0/c0", "t0/r0/c1", "t0/r0/c2"}
