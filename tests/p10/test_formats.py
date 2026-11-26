"""Другие загрузчики: ячейки DOCX как блоки, страницы PDF без разметки Markdown."""

from __future__ import annotations

from . import fixture as fx
from bcc_review.bank import build_bank_pack, render_markdown
from bcc_review.bank.checklist import Doc


def _docx_doc() -> dict:
    blocks = [
        {"id": "p1", "kind": "heading", "section": [], "text": "Ревью требований", "loc": {"path": "body/p[10]"}},
        {"id": "p2", "kind": "heading", "section": ["Ревью требований"], "text": "Архитектура решения", "loc": {"path": "body/p[11]"}},
        {"id": "p3", "kind": "paragraph", "section": ["Ревью требований", "Архитектура решения"],
         "text": "Шлюз → сервис лимитов → хранилище.", "loc": {"path": "body/p[12]"}},
    ]
    cells = [
        ["Проверка", "Создано или доступно", "Проверено", "Примечания"],
        ["Требование содержит архитектуру и согласовано с архитекторами", "Да / Нет / Не требуется", "Да / Нет / Не требуется", "Для архитектуры — чек-лист"],
        ["Требование может быть протестировано", "Да / Нет", "Да / Нет", ""],
        ["Поддерживается версионность документа / зафиксирована", "Да / Нет", "Да / Нет", ""],
    ]
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            blocks.append({"id": f"t0r{r}c{c}", "kind": "table_cell", "section": ["Ревью требований"], "text": text,
                           "loc": {"path": f"body/tbl[0]/tr[{r}]/tc[{c}]"}})
    blocks.append({"id": "p4", "kind": "paragraph", "section": ["Ревью требований"], "text": "Версия документа 1.2 от 20.11.2026.", "loc": {"path": "body/p[20]"}})
    return {"id": "docx-sha", "title": "ТЗ", "format": "docx", "blocks": blocks, "warnings": []}


def test_docx_cell_blocks_form_the_checklist():
    doc = _docx_doc()
    pack = build_bank_pack(doc, [], [], [], None)
    rows = pack["checklist"]
    assert [r["text"] for r in rows] == [
        "Требование содержит архитектуру и согласовано с архитекторами",
        "Требование может быть протестировано",
        "Поддерживается версионность документа / зафиксирована",
    ]
    arch = rows[0]
    assert arch["cells"]["available"] == "Да" and arch["checked"] == "unknown" and arch["approval"]["status"] == "requires_confirmation"
    assert arch["source"]["location"] == "body/tbl[0]/tr[1]/tc[0]"
    assert "блока согласующих в документе нет" in arch["note"]
    ver = rows[2]
    assert ver["available"] == "yes" and "1.2" in ver["presence"]["evidence"][0]["quote"]
    d = Doc(doc)
    assert all(d.ev_valid(e) for r in rows for e in r["evidence"])


def test_pdf_pages_without_markdown_and_headings():
    sec_a = ["Требования", "Функциональные требования"]
    sec_b = ["Требования", "REST API", "Статусы"]
    blocks = [
        {"id": "pg2-1", "kind": "paragraph", "section": sec_a, "text": "Ф-1. Клиент задаёт лимит от 10 до 500 ₸ включительно, только целое число.", "loc": {"page": 2}},
        {"id": "pg3-1", "kind": "paragraph", "section": sec_b, "text": "401. Ответ в случае, если токен не передан.", "loc": {"page": 3}},
        {"id": "pg3-2", "kind": "paragraph", "section": sec_b, "text": "400. Ответ в случае, если параметры заполнены неверно.", "loc": {"page": 3}},
    ]
    doc = {"id": "pdf-sha", "title": "ТЗ", "format": "pdf", "blocks": blocks, "warnings": []}
    req = {"id": "R-1", "source_id": "Ф-1", "text": "Клиент задаёт лимит от 10 до 500 ₸ включительно, только целое число.",
           "block_ids": ["pg2-1"], "evidence": []}
    pack = build_bank_pack(doc, [req], [], [], None)
    assert pack["checklist"] == [] and pack["warnings"][0]["code"] in {"bank.criteria_missing", "bank.checklist_absent"}
    vals = sorted(t["values"]["input"] for t in pack["test_cases"] if t["kind"] == "boundary")
    assert vals == [9, 10, 10.5, 500, 501]
    t9 = next(t for t in pack["test_cases"] if t["values"].get("input") == 9)
    assert t9["req_ids"] == ["R-1"] and t9["obligation"]["quote"].startswith("Клиент задаёт лимит")
    st = next(t for t in pack["test_cases"] if t["key"] == "api:status:401")
    assert "токен не передан" in st["action"]
    md = render_markdown(pack)
    assert "нет исходного банковского чек-листа" in md and "Лимит 9 ₸" in md


def test_render_markdown_for_case_contains_all_rows_and_open_questions():
    c = fx.case()
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], [], None, questions=fx.questions(), criteria=fx.CRITERIA)
    md = render_markdown(pack)
    assert md.count("\n| ") >= 15  # заголовок + 14 строк
    assert "требует подтверждения" in md and "Q-01" in md and "Дано:" in md
