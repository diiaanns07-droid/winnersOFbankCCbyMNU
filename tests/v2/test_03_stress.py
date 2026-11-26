"""№03, вторая волна: неизвестный документ на финале — стресс-набор tests/v2/fixtures/03_stress/.

DOCX с объединёнными ячейками, колонтитулами и автонумерацией; PDF из Word с колонтитулами и переносами; PDF в две
колонки; PDF со страницей-сканом; MD без части B; длинное ТЗ на 600+ строк; HTML-экспорт Confluence.
Файлы пересоздаёт tests/v2/fixtures/03_stress/make_stress.py.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / "tests/v2/fixtures/03_stress"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


needs_pdf = pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
needs_docx = pytest.mark.skipif(not _has("docx"), reason="нет python-docx")


def _texts(v: dict) -> list[str]:
    return [ln["text"] for ln in v["lines"]]


def _joined(v: dict) -> str:
    return "\n".join(_texts(v))


@needs_docx
def test_docx_merged_cells_numbering_headers():
    v = dv.load(S / "docx_merged.docx")
    t = _texts(v)
    assert v["format"] == "docx" and v["title"] == "Блокировка карты по сроку" and v["warnings"] == []
    assert [ln["n"] for ln in v["lines"]] == list(range(1, len(t) + 1))
    j = _joined(v)
    # колонтитулы не в тексте
    assert "Конфиденциально" not in j and "Внутренний документ" not in j and "стр." not in j
    # автонумерация Word — номер в начале строки, как в документе; маркеры не добавляются
    assert "1. Клиент блокирует карту на срок от 1 до 30 суток." in t
    assert "4. Клиент может досрочно разблокировать карту в приложении." in t
    assert "1. Авторизации, одобренные до блокировки, проводятся." in t
    assert "Блокировка вступает в силу не позднее 10 секунд после ответа сервиса." in t
    assert not any(x.startswith("•") for x in t)
    # объединённые ячейки: по горизонтали — одна ячейка, по вертикали — строка без потери соседних ячеек
    assert "Поле | Значение" in t and "Задача | CARD-1402" in t
    assert "Ответственные | Владелец продукта | Отдел карточных продуктов" in t
    assert any(x.strip(" |").startswith("Аналитик | Команда платёжных сервисов") for x in t)
    assert dv.line(v, t.index("Задача | CARD-1402") + 1)["kind"] == "table_row"
    m = Q.verify_quote(v, "Клиент блокирует карту на срок от 1 до 30 суток", 10)
    assert m and m["verified"] == "exact"
    assert Q.verify_quote(v, "2. Во время блокировки процессинг отклоняет новые авторизации")["verified"] == "exact"


@needs_pdf
def test_pdf_from_word_headers_footers_and_hyphenation():
    v = dv.load(S / "word_export.pdf")
    t = _texts(v)
    j = _joined(v)
    assert v["format"] == "pdf" and v["pages"] == 3 and v["title"] == "Лимит переводов между своими счетами"
    assert "Конфиденциально" not in j and "стр. 1 из 3" not in j and "Лимит переводов v2.1" not in j
    assert any("Колонтитулы убраны" in w for w in v["warnings"])
    # переносы по слогам склеены: слова целые, без мягкого переноса и дефиса
    for word in ("включаются", "отклоняется", "подтверждения", "процентов", "вступления"):
        assert word in j, word
    assert "­" not in j
    assert "client_id | string | Идентификатор клиента" in t
    assert {ln["page"] for ln in v["lines"]} == {1, 2, 3}
    assert all(ln["page"] for ln in v["lines"])
    # тот же документ в DOCX: каждая строка находится в PDF
    d = dv.load(S / "word_export.docx")
    assert "­" not in _joined(d)
    missing = [x["text"] for x in dv.nonempty(d) if not Q.verify_quote(v, x["text"])]
    assert missing == []


@needs_pdf
def test_pdf_two_columns_reading_order():
    v = dv.load(S / "two_columns.pdf")
    t = _texts(v)
    assert v["pages"] == 2 and any("две колонки" in w for w in v["warnings"])

    def pos(prefix: str) -> int:
        return next(i for i, x in enumerate(t) if x.startswith(prefix))

    order = ["КУ-1.", "КУ-2.", "КУ-3.", "КУ-4.", "КУ-21.", "КУ-22.", "КУ-23.", "КУ-24.", "КУ-31.", "КУ-34."]
    assert [pos(p) for p in order] == sorted(pos(p) for p in order)
    assert pos("Критерии приёмки") < pos("Кэшбэк за оплату коммунальных услуг — раздел 2")


@needs_pdf
def test_pdf_scanned_page_warns_clearly():
    v = dv.load(S / "scan_page.pdf")
    assert v["pages"] == 2 and len(dv.nonempty(v)) == 3
    assert all(ln["page"] == 1 for ln in v["lines"])
    w = " ".join(v["warnings"])
    assert "Страница 2" in w and "скан" in w
    assert len(v["warnings"]) == len(set(v["warnings"])) and len(v["warnings"]) <= 2
    assert all(any("а" <= ch <= "я" for ch in x.lower()) for x in v["warnings"])   # по-русски


def test_md_without_part_b():
    v = dv.load(S / "no_part_b.md")
    raw = (S / "no_part_b.md").read_text(encoding="utf-8").splitlines()
    assert len(v["lines"]) == len(raw) and v["title"] == "Автоплатёж за мобильную связь"
    j = _joined(v)
    assert "Часть B" not in j and "**" not in j
    assert "АМ-4. Не более трёх пополнений одного номера в сутки." in _texts(v)
    assert "Три пополнения за сутки | Баланс ниже порога | Пополнение не выполняется" in _texts(v)


def test_long_document_600_lines():
    v = dv.load(S / "long_tz.md")
    raw = (S / "long_tz.md").read_text(encoding="utf-8").splitlines()
    assert len(raw) >= 600 and len(v["lines"]) == len(raw)
    assert [ln["n"] for ln in v["lines"]] == list(range(1, len(raw) + 1))
    assert dv.numbered(v, 600, 600).startswith("L600|")
    # фраза повторяется в каждом из 17 разделов — цитата привязывается к ближайшему вхождению
    occ = [ln["n"] for ln in v["lines"] if ln["text"] == "Журнал операций хранится 5 лет."]
    assert len(occ) == 17
    t0 = time.time()
    for n in occ:
        m = Q.verify_quote(v, "Журнал операций хранится 5 лет", n + 1)
        assert m["line_start"] == n and "Нефункциональные требования" in m["section"]
    for i in range(1, 9):
        m = Q.verify_quote(v, f"Подсистема «Документы» выполняет операцию {i}")
        assert m and v["lines"][m["line_start"] - 1]["text"].startswith(f"Т17-{i}.")
    assert time.time() - t0 < 3


def test_confluence_html_export():
    v = dv.load(S / "confluence.html")
    t = _texts(v)
    j = _joined(v)
    assert v["format"] == "html" and v["title"] == "ТЗ Пополнение депозита с карты"
    assert t[0] == "ТЗ Пополнение депозита с карты"
    for junk in ("Платёжные сервисы", "Создатель", "Вложения", "sequence.png", "Документ создан Confluence",
                 "Atlassian"):
        assert junk not in j, junk
    # оглавление не дублирует заголовки
    assert t.count("Функциональные требования") == 1 and t.count("API") == 1
    assert "1. Клиент выбирает депозит и карту, вводит сумму от 1 000 до 10 000 000 ₸." in t
    assert "Пополнение депозита «Неснижаемый» запрещено условиями договора." in t   # панель предупреждения
    assert "Параметр | Тип | Описание" in t and "amount | integer | Сумма в тиынах" in t
    assert '{"status":"ACCEPTED",' in t
    assert dv.line(v, t.index("API") + 1)["section"] == "API"
    m = Q.verify_quote(v, "Комиссия за пополнение картой другого банка — 0,5 % от суммы", 8)
    assert m and m["line_start"] == t.index("2. Комиссия за пополнение картой другого банка — 0,5 % от суммы, "
                                             "не менее 200 ₸.") + 1


@needs_pdf
def test_layout_fixes_do_not_touch_official_and_corpus():
    """Колонтитулы и колонки не срабатывают на обычных документах: нумерация фикстур нарезки PDF сохраняется."""
    off = dv.load(ROOT / "release/input/requirements.pdf")
    assert len(off["lines"]) == 128 and off["warnings"] == []
    for case, n in (("autopay", 71), ("cardblock", 62), ("cashback", 62), ("transfer_limit", 56)):
        v = dv.load(ROOT / f"evaluation/dev/corpus/cases/{case}.base/source.pdf")
        assert len(v["lines"]) == n and v["warnings"] == [], case
