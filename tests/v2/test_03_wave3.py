"""№03, третья волна: скорость чтения PDF, цитаты строк таблиц с другим разделителем ячеек, аудит привязки отчёта."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MD = ROOT / "release/input/requirements.md"
OFFICIAL_PDF = ROOT / "release/input/requirements.pdf"

TABLE_DOC = """# ТЗ

## Общие параметры

| Поле | Значение |
|---|---|
| REST type | GET |
| Authorization | Bearer, сессия владельца карты |
| Request URL | Dev: /alerts/saveLimit . Prod: — |
| Swagger | — |
| Product owner | Иванов |

## Swagger-документация

Описание Swagger — в приложении.
"""


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def table():
    return dv.from_text(TABLE_DOC)


def _line(view, text):
    return next(ln["n"] for ln in view["lines"] if ln["text"].startswith(text))


# --------------------------------------------------------------------------- скорость чтения PDF
@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_pdf_fast_mode_turns_off_layout_model():
    """PyMuPDF 2.x с pymupdf_layout гонял нейросеть на каждой странице (0,55 с/стр.); docview её выключает."""
    import pymupdf
    view = dv.load(OFFICIAL_PDF)
    assert len(view["lines"]) == 128 and view["pages"] == 6
    if hasattr(pymupdf, "_layout_enabled"):
        assert pymupdf._layout_enabled is False
    dv.pdf_fast_mode()  # повторный вызов безопасен


# --------------------------------------------------------------------------- строки таблиц
@pytest.mark.parametrize("quote, start", [
    ("REST type: GET", "REST type"),
    ("REST type GET", "REST type"),
    ("Authorization — Bearer, сессия владельца карты", "Authorization"),
    ("Request URL: Dev: /alerts/saveLimit . Prod: —", "Request URL"),
    ("Swagger: —", "Swagger |"),
    ("Swagger: «—»", "Swagger |"),
])
def test_table_row_with_other_cell_separator(table, quote, start):
    # одно слово «Swagger» есть и в абзаце внизу — такой цитате нужна строка модели
    m = Q.verify_quote(table, quote, _line(table, start) if quote.startswith("Swagger") else None)
    assert m, quote
    assert m["line_start"] == _line(table, start)
    assert m["verified"] == "normalized"
    # в отчёт идёт текст документа: verify №13 найдёт его подстрокой строки
    assert " | " in m["text"] and Q.normalize(m["text"]) in Q.normalize(table["lines"][m["line_start"] - 1]["text"])


def test_same_words_do_not_match_inside_word_or_short(table):
    assert Q.verify_quote(table, "type GET") is None            # меньше 10 букв и цифр
    assert Q.verify_quote(table, "Prod —") is None               # одно короткое слово
    assert Q.verify_quote(table, "Product: Иванов") is None      # в документе «Product owner | Иванов»


def test_single_word_with_dash_prefers_hint(table):
    swagger_row = _line(table, "Swagger |")
    m = Q.verify_quote(table, "Swagger —", swagger_row)
    assert m and m["line_start"] == swagger_row
    # «Swagger —» дословно есть в абзаце внизу: рядом с подсказкой — своё место, без подсказки — дословное
    assert Q.verify_quote(table, "Swagger: —") is None  # одно слово без подсказки, два места — не угадываем
    tail = _line(table, "Описание Swagger")
    m2 = Q.verify_quote(table, "Swagger —", tail)
    assert m2 and m2["line_start"] == tail


@pytest.mark.parametrize("quote", ["Месяц определяется [...] покупки", "Месяц определяется (…) покупки",
                                   "Месяц определяется … покупки"])
def test_ellipsis_in_brackets(quote):
    view = dv.load(OFFICIAL_MD)
    m = Q.verify_quote(view, quote)
    assert m and m["line_start"] == 38 and m["text"].startswith("Месяц определяется по дате совершения покупки")


def test_exact_quotes_unchanged_by_new_step():
    """Новый шаг идёт после точного поиска: дословные цитаты остаются exact на своих строках."""
    view = dv.load(OFFICIAL_MD)
    m = Q.verify_quote(view, "REST type | GET", 104)
    assert m == {**m, "line_start": 104, "verified": "exact", "text": "REST type | GET"}


# --------------------------------------------------------------------------- аудит привязки
def _report(view, evidence, req_lines=(38, 38)):
    return {"requirements": [{"id": "R-01", "quote": "Месяц определяется по дате совершения покупки",
                              "line_start": req_lines[0], "line_end": req_lines[1]}],
            "findings": [{"id": "D-01", "requirement_ids": ["R-01"], "evidence": evidence}]}


def _ev(view, quote, line):
    m = Q.verify_quote(view, quote, line)
    return {"quote": m["text"], "line_start": m["line_start"], "line_end": m["line_end"], "page": m["page"],
            "section": m["section"], "verified": m["verified"]}


def test_audit_clean_report():
    view = dv.load(OFFICIAL_MD)
    res = Q.audit_report(_report(view, [_ev(view, "Месяц определяется по дате совершения покупки", 38)]), view)
    assert res["ok"] and res["evidence"] == 1 and res["by_verified"] == {"exact": 1}
    assert res["requirements"]["outside"] == []


def test_audit_finds_wrong_line_page_section_and_missing():
    view = dv.load(OFFICIAL_PDF)
    good = _ev(view, "Месяц определяется по дате совершения покупки", 25)
    wrong_line = {**good, "line_start": 30, "line_end": 30}
    wrong_page = {**good, "page": 5}
    wrong_section = {**good, "section": "Часть B. REST API"}
    missing = {**good, "verified": "missing"}
    rep = _report(view, [good, wrong_line, wrong_page, wrong_section, missing], req_lines=(25, 25))
    res = Q.audit_report(rep, view)
    what = " ".join(p["what"] for p in res["problems"])
    assert not res["ok"] and len(res["problems"]) == 4
    assert "нет в строках 30–30" in what and "страница 5" in what and "раздел «Часть B. REST API»" in what
    assert "не сверена" in what


def test_audit_repeated_phrase_outside_requirement():
    """Фраза встречается дважды: взятое вхождение вне строк требований дефекта, хотя внутри есть своё."""
    view = dv.from_text("# ТЗ\n\nФ-1. Сумма в тенге.\n\nТекст.\n\nФ-2. Сумма в тенге.\n")
    first, second = [ln["n"] for ln in view["lines"] if "Сумма в тенге" in ln["text"]]
    ev = _ev(view, "Сумма в тенге", first)
    rep = {"requirements": [{"id": "R-02", "quote": "Ф-2. Сумма в тенге.", "line_start": second, "line_end": second}],
           "findings": [{"id": "D-01", "requirement_ids": ["R-02"], "evidence": [ev]}]}
    res = Q.audit_report(rep, view)
    assert not res["ok"] and "фраза встречается" in res["problems"][0]["what"]
    # эту строку указала сама модель — её выбор, не ошибка сверки
    stages = {"consistency": {"candidates": [{"requirement_ids": ["R-02"],
                                              "evidence": [{"quote": "Сумма в тенге", "line": first}]}]}}
    assert Q.audit_report(rep, view, stages)["ok"]
    ok = Q.audit_report({**rep, "findings": [{"id": "D-01", "requirement_ids": ["R-02"],
                                              "evidence": [_ev(view, "Сумма в тенге", second)]}]}, view)
    assert ok["ok"]


def test_audit_stage_hints_and_lost_candidates():
    view = dv.load(OFFICIAL_MD)
    rep = _report(view, [_ev(view, "Месяц определяется по дате совершения покупки", 38)])
    stages = {
        "lens_qa": {"candidates": [{"requirement_ids": ["R-01"], "evidence": [
            {"quote": "Месяц определяется по дате совершения покупки", "line": 38},
            {"quote": "Месяц определяется по дате совершения покупки", "line": 39},
            {"quote": "Февральский счётчик вырос на 4 000", "line": 10}]}]},
        "quotes": {"rejected": [{"source": "lens:analyst", "title": "Выдуманное",
                                 "evidence": [{"quote": "такого текста нет", "line": 5}]}]},
    }
    res = Q.audit_report(rep, view, stages)
    h = res["hints"]
    assert (h["total"], h["same_line"], h["within_2"], h["far"]) == (3, 1, 1, 1)
    assert h["far_list"][0]["hint"] == 10 and h["far_list"][0]["found"] == 64
    assert res["lost"] and res["lost"][0]["source"] == "lens:analyst" and not res["ok"]


def test_audit_cli_on_run_dir(tmp_path, capsys):
    view = dv.load(OFFICIAL_MD)
    run = tmp_path / "run"
    (run / "stages").mkdir(parents=True)
    rep = _report(view, [_ev(view, "Месяц определяется по дате совершения покупки", 38)])
    (run / "report.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    (run / "stages" / "lens_qa.json").write_text(json.dumps({"output": {"candidates": [{"evidence": [
        {"quote": "Месяц определяется по дате совершения покупки", "line": 38}]}]}}, ensure_ascii=False),
        encoding="utf-8")
    assert Q.main(["audit", str(run), "--doc", str(OFFICIAL_MD)]) == 0
    out = capsys.readouterr().out
    assert "Доказательств: 1" in out and "та же 1" in out
    bad = copy.deepcopy(rep)
    bad["findings"][0]["evidence"][0]["line_start"] = 40
    bad["findings"][0]["evidence"][0]["line_end"] = 40
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert Q.main(["audit", str(p), "--doc", str(OFFICIAL_MD)]) == 4


# --------------------------------------------------------------------------- экспорт для читателя
def test_export_text_has_no_internal_line_codes(tmp_path):
    """В Jira, Word и PDF текст модели «L025 … (L022)» читается как «строка 25 … (строка 22)», как в отчёте №13."""
    import csv

    from bcc_review.v2.render import exports as E
    view = dv.load(OFFICIAL_MD)
    ev = _ev(view, "Месяц определяется по дате совершения покупки", 38)
    report = {"document": {"title": "ТЗ"}, "questions": [{"id": "Q-01", "finding_ids": ["D-01"],
                                                          "question": "Что верно в L038?", "options": ["как в L64"]}],
              "findings": [{"id": "D-01", "title": "Критерий L064 против L038", "severity": "critical",
                            "problem": "L038 относит покупку к январю, а учёт (L022) — к февралю; в L38–L40 то же.",
                            "evidence": [ev]}]}
    res = E.export(report, view, OFFICIAL_MD, tmp_path / "r.md", ["jira"])[0]
    rows = list(csv.DictReader(open(res["path"], encoding="utf-8-sig")))
    text = rows[0]["Summary"] + rows[0]["Description"]
    assert "L038" not in text and "L022" not in text and "L064" not in text
    assert "строка 38 относит покупку" in text and "(строка 22)" in text and "в строках 38–40" in text
    assert "Часть A › Функциональные требования, строка 38" in text  # место — как в отчёте
    assert report["findings"][0]["problem"].startswith("L038")  # исходный отчёт не меняется


# --------------------------------------------------------------------------- PDF: таблица без линеек, знаки другим шрифтом
BORDERLESS_PDF = ROOT / "tests/v2/fixtures/03_stress/borderless.pdf"


@pytest.fixture(scope="module")
def borderless():
    return dv.load(BORDERLESS_PDF)


@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_borderless_key_value_table_rows(borderless):
    """Таблица без линеек (PDF из Word, PyMuPDF как у жюри): «поле | значение» в одной строке, а не колонками."""
    texts = [ln["text"] for ln in borderless["lines"]]
    for row in ("Поле | Значение", "Наименование задачи | Кредитные каникулы по кредитной карте",
                "Продукт | Мобильный банк, кредитные карты",
                "Бизнес-процесс | Обслуживание держателя кредитной карты с просроченной задолженностью",
                "Владелец | Управление розничного кредитования"):
        assert row in texts, row
    assert any("собрана по строкам" in w for w in borderless["warnings"])


@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_borderless_acceptance_table_three_columns(borderless):
    texts = [ln["text"] for ln in borderless["lines"]]
    assert "Исходные условия | Действие | Ожидаемый результат" in texts
    assert ("Каникулы уже брались 10 марта | Оформить повторно 1 июня того же года | "
            "Отказ с текстом «Каникулы доступны раз в год»") in texts
    assert "Просрочка 5 дней | Оформить каникулы | Отказ, кнопка недоступна" in texts
    row = next(ln for ln in borderless["lines"] if ln["text"].startswith("Просрочки нет"))
    assert row["kind"] == "table_row" and row["page"] == 1 and row["section"].endswith("Критерии приемки")


@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_punctuation_in_other_font_stays_in_place(borderless):
    """Знаки, набранные другим шрифтом, читатель уносил в конец строки: «нулю проценты; начисляются»."""
    texts = [ln["text"] for ln in borderless["lines"]]
    assert "К-2. На время каникул минимальный платёж равен нулю; проценты начисляются по ставке договора." in texts
    assert "Документ подготовлен для проверки чтения PDF. Таблицы в нём — без линеек." in texts


@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_borderless_bullets_become_list_items(borderless):
    items = [ln for ln in borderless["lines"] if ln["section"].endswith("Логика метода") and not ln["heading"]]
    assert [ln["text"] for ln in items] == ["Проверить сессию клиента.", "Проверить отсутствие просрочки.",
                                            "Сохранить срок каникул и вернуть дату окончания."]
    assert all(ln["kind"] == "list_item" for ln in items)


@pytest.mark.skipif(not _has("pymupdf"), reason="нет PyMuPDF")
def test_borderless_quotes_and_two_columns_untouched(borderless):
    m = Q.verify_quote(borderless, "Продукт: Мобильный банк, кредитные карты")
    assert m and m["text"] == "Продукт | Мобильный банк, кредитные карты"
    # вёрстка в две колонки — не таблица: порядок по колонкам, как раньше
    two = dv.load(ROOT / "tests/v2/fixtures/03_stress/two_columns.pdf")
    assert not any(" | " in ln["text"] for ln in two["lines"])
    assert not any("собрана по строкам" in w for w in two["warnings"])
