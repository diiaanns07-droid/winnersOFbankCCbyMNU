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


@needs_docx
def test_official_docx_parity():
    """release/input/requirements.docx (из MD, make_official_docx.py): все строки MD и все цитаты эталона на месте;
    нумерация DOCX совпадает с PDF построчно — фикстура нарезки official_pdf годится и для DOCX."""
    import json
    md = dv.load(ROOT / "release/input/requirements.md")
    dx = dv.load(ROOT / "release/input/requirements.docx")
    assert dx["title"] == md["title"] and dx["warnings"] == [] and len(dx["lines"]) == 128
    assert [ln["n"] for ln in dv.nonempty(md) if not Q.verify_quote(dx, ln["text"])] == []
    assert "1. Проверить пользовательскую сессию." in _texts(dx) and "3. Изменение порога сохраняет накопленные расходы." in _texts(dx)
    ref = json.loads((ROOT / "tests/v2/fixtures/03_reference_quotes.json").read_text(encoding="utf-8"))["quotes"]
    for r in ref:
        mm = Q.verify_quote(md, r["quote"], r["line"])
        loc = Q.verify_quote(dx, dv.line(md, r["line"])["text"])
        m = Q.verify_quote(dx, r["quote"], loc["line_start"])
        assert m and m["section"] == mm["section"] and loc["line_start"] <= m["line_start"] <= loc["line_end"], r
    if _has("pymupdf"):
        pdf = dv.load(ROOT / "release/input/requirements.pdf")
        same = sum(Q.normalize(a["text"]) == Q.normalize(b["text"]) for a, b in zip(dx["lines"], pdf["lines"]))
        assert same >= 127
    seg = json.loads((ROOT / "tests/v2/fixtures/official_pdf/segment.json").read_text(encoding="utf-8"))
    for r in seg["requirements"]:
        m = Q.verify_quote(dx, r["quote"], r["line_start"])
        assert m and r["line_start"] - 2 <= m["line_start"] <= r["line_end"] + 2, r["id"]


@needs_pdf
@needs_docx
def test_long_document_docx_and_pdf_from_word():
    """Длинное ТЗ в DOCX и PDF из Word (19 страниц): все строки MD на месте, повторяющаяся фраза — в своём разделе
    (k-е вхождение), строки таблиц, разорванные переносом страницы, склеены, маркеров «•» в тексте нет."""
    md = dv.load(S / "long_tz.md")
    pdf = dv.load(S / "long_tz.pdf")
    dx = dv.load(S / "long_tz.docx")
    assert pdf["pages"] >= 15 and any("разорванные переходом" in w for w in pdf["warnings"])
    for v in (pdf, dx):
        assert [x["n"] for x in dv.nonempty(md) if not Q.verify_quote(v, x["text"])] == []
        assert not any(x["text"].startswith("•") for x in v["lines"])
        occ_md = [x for x in md["lines"] if x["text"] == "Журнал операций хранится 5 лет."]
        occ = [x for x in v["lines"] if x["text"].strip() == "Журнал операций хранится 5 лет."]
        assert len(occ) == 17
        assert all(a["section"].split(" › ")[0] == b["section"].split(" › ")[0] for a, b in zip(occ_md, occ))
        for a, b in zip(occ_md, occ):     # цитата с подсказкой — своё вхождение, не соседнее
            m = Q.verify_quote(v, "Журнал операций хранится 5 лет", b["n"] + 1)
            assert m["line_start"] == b["n"]
    assert "Пользователь вошёл в «Профиль» | Операция 2 | Результат за 4 с" in _texts(pdf)


def test_windows_text_encodings_and_crlf(tmp_path):
    """Файлы из Windows: TXT в cp1251 и UTF-16 (Блокнот), Markdown с переводами строк CRLF."""
    body = "Требования к сервису\r\n\r\nФ-1. Клиент задаёт лимит.\r\nФ-2. Лимит действует сутки.\r\n"
    for enc in ("cp1251", "utf-16", "utf-8-sig"):
        p = tmp_path / f"win_{enc}.txt"
        p.write_bytes(body.encode(enc))
        v = dv.load(p)
        assert _texts(v) == ["Требования к сервису", "", "Ф-1. Клиент задаёт лимит.", "Ф-2. Лимит действует сутки."], enc
    assert dv._decode_text("Привет".encode("cp1251")) == "Привет"
    p = tmp_path / "crlf.md"
    p.write_bytes("# Заголовок\r\n\r\n* **Ф-1.** Клиент задаёт лимит.\r\n| a | b |\r\n| --- | --- |\r\n| 1 | 2 |\r\n".encode())
    v = dv.load(p)
    assert _texts(v) == ["Заголовок", "", "Ф-1. Клиент задаёт лимит.", "a | b", "", "1 | 2"]


def test_unsupported_format_message(tmp_path):
    p = tmp_path / "table.xlsx"
    p.write_bytes(b"PK")
    with pytest.raises(ValueError, match="не поддерживается; сохраните документ как DOCX, PDF"):
        dv.load(p)
    with pytest.raises(ValueError, match="файл не найден"):
        dv.load(tmp_path / "missing.md")


@pytest.mark.skipif(not __import__("shutil").which("soffice"), reason="нет LibreOffice")
@pytest.mark.parametrize("ext", ["odt", "rtf", "doc"])
def test_doc_rtf_odt_via_libreoffice(tmp_path, ext):
    import subprocess
    subprocess.run(["soffice", "--headless", "--convert-to", ext, "--outdir", str(tmp_path), str(S / "docx_merged.docx")],
                   check=True, capture_output=True, timeout=180)
    src = tmp_path / f"docx_merged.{ext}"
    v = dv.load(src)
    ref = dv.load(S / "docx_merged.docx")
    assert v["file"] == src.name and v["title"] == ref["title"]
    assert v["warnings"][0].startswith(f"Документ {ext.upper()} прочитан через преобразование в DOCX")
    assert [x["n"] for x in dv.nonempty(ref) if not Q.verify_quote(v, x["text"])] == []


@needs_docx
def test_html_saved_from_word_matches_docx():
    """HTML «Сохранить как веб-страницу» (LibreOffice/Word): переносы строк внутри <p> — пробелы, <li><p>…</p></li> —
    один пункт с номером; построчно совпадает с DOCX и содержит все строки MD."""
    h = dv.load(S / "word_saved.html")
    dx = dv.load(ROOT / "release/input/requirements.docx")
    md = dv.load(ROOT / "release/input/requirements.md")
    assert h["title"] == md["title"] and len(h["lines"]) == len(dx["lines"])
    assert all(Q.normalize(a["text"]) == Q.normalize(b["text"]) for a, b in zip(h["lines"], dx["lines"]))
    assert [x["n"] for x in dv.nonempty(md) if not Q.verify_quote(h, x["text"])] == []
    assert "5. При отклонении суммы вернуть прежнее состояние и результат ERROR." in _texts(h)


@needs_docx
def test_docx_tracked_changes_final_text_and_warning():
    v = dv.load(S / "docx_tracked.docx")
    assert "СН-2. Лимит снятия составляет 200 000 тенге в сутки." in _texts(v)
    assert "100 000" not in _joined(v)
    assert any("непринятые исправления (вставок 1, удалений 1)" in w for w in v["warnings"])
    assert dv.load(S / "docx_merged.docx")["warnings"] == []


def test_split_merged_pdf_headings_unit():
    """Читатель PDF склеил два заголовка подряд в один блок (строки разного кегля) — делим и чиним разделы."""
    def frag(s, e, rect, line):
        return {"start": s, "end": e, "rect": rect, "line": line}
    merged = "Требования к изменениям BPMN схема процесса"
    blocks = [
        {"id": "b1", "kind": "heading", "text": merged, "section": ["Док", "Часть A", merged],
         "loc": {"page": 1, "level": 3, "bbox": [57, 509, 224, 533],
                 "fragments": [frag(0, 23, [57, 509.5, 224, 520.5], 0), frag(24, 43, [57, 523.3, 185, 533.3], 1)]}},
        {"id": "b2", "kind": "paragraph", "text": "Схема процесса.", "section": ["Док", "Часть A", merged],
         "loc": {"page": 1, "bbox": [57, 540, 300, 550]}},
        {"id": "b3", "kind": "heading", "text": "Функциональные требования", "section": ["Док", "Часть A", merged],
         "loc": {"page": 1, "level": 4, "bbox": [57, 576, 229, 586]}},
        {"id": "b4", "kind": "list_item", "text": "Ф-1. Текст.", "section": ["Док", "Часть A", merged,
                                                                          "Функциональные требования"],
         "loc": {"page": 1, "bbox": [57, 590, 400, 600]}},
    ]
    out = dv._split_merged_headings(blocks, {1: (595, 842)})
    assert [b["text"] for b in out[:2]] == ["Требования к изменениям", "BPMN схема процесса"]
    assert dv._level(out[1]) == 4
    assert out[2]["section"] == ["Док", "Часть A", "Требования к изменениям", "BPMN схема процесса"]
    assert out[3]["section"] == ["Док", "Часть A", "Требования к изменениям"]
    assert out[4]["section"] == ["Док", "Часть A", "Требования к изменениям", "Функциональные требования"]
    # длинный заголовок, перенесённый на вторую строку тем же кеглем и во всю ширину, не делится
    long = {"id": "x", "kind": "heading", "text": "Очень длинный заголовок раздела " * 3, "section": [],
            "loc": {"page": 1, "level": 2, "fragments": [frag(0, 60, [57, 100, 540, 112], 0),
                                                         frag(61, 96, [57, 114, 300, 126], 1)]}}
    assert len(dv._split_merged_headings([long], {1: (595, 842)})) == 1


def test_quote_matches_word_broken_in_narrow_cell():
    """Узкая ячейка PDF: слово разорвано без дефиса («integ er»); цитата «integer» находится на своей строке."""
    v = dv.from_text("# Док\n\n| Поле | Тип |\n| --- | --- |\n| daysLeft | integ er |\n| reminderEna bled | boole an |\n")
    m = Q.verify_quote(v, "daysLeft | integer", 5)
    assert m and m["line_start"] == 5 and m["verified"] == "normalized" and m["text"] == "daysLeft | integ er"
    assert Q.verify_quote(v, "reminderEnabled | boolean")["line_start"] == 6


@pytest.mark.parametrize("ext", ["docx", "pdf"])
def test_table_of_contents_removed_and_tight_spacing(ext):
    """Оглавление («1. Общие сведения ……… 2») убирается с предупреждением; в PDF нет лишних пробелов между
    фрагментами без зазора («ВК -1», «приложении .»)."""
    pytest.importorskip("docx" if ext == "docx" else "pymupdf")
    v = dv.load(S / f"toc.{ext}")
    t = _texts(v)
    assert t == ["Выпуск виртуальной карты", "1. Общие сведения", "Клиент выпускает виртуальную карту в приложении.",
                 "2. Цели", "Карта доступна для оплаты сразу после выпуска.", "3. Функциональные требования",
                 "ВК-1. Выпуск бесплатный.", "4. Критерии приёмки", "Карта выпущена за 10 секунд."]
    assert any("Оглавление убрано из текста (5 строк)" in w for w in v["warnings"])
    assert [ln["n"] for ln in v["lines"]] == list(range(1, 10))


def test_toc_detector_does_not_eat_normal_lines():
    lines = [{"n": i + 1, "text": t, "kind": k} for i, (t, k) in enumerate([
        ("Статусы", "heading"), ("Статусы 200", "paragraph"), ("Ответ 200 при успехе.", "paragraph"),
        ("Лимит", "heading"), ("Лимит 5", "paragraph")])]
    out, n = dv.drop_toc(lines)
    assert n == 0 and out == lines
