"""№25: исправления чтения по находкам зоопарка — по тесту на каждое, и весь зоопарк через конвейер без модели.

1. MD: «<br>» в ячейке таблицы давал перевод строки внутри строки вида — нумерованный текст «L008| …» рвался
   (следующая строка без «L…|», модель видела строку без номера).
2. MD: «\\|» внутри ячейки (и в коде внутри ячейки) оставался с обратной косой — цитата «LOST | DAMAGED» не была
   дословной.
3. TXT/MD в UTF-16 без метки порядка байт — текст из нулевых байт и «�» вместо документа.
4. PDF: первый нумерованный раздел («1. Назначение») считался названием документа и вырезался из разделов — у
   строк раздела 1 раздел пустой.
5. PDF из Word: номер пункта списка («1.» — два фрагмента «1» и «.») не узнавался как маркер, список читался как
   таблица без линеек «1. | Клиент выбирает…»; продолжение пункта на следующей строке — отдельной строкой.
6. Нарезка: проверка «текст есть в документе» нормализовала весь документ на каждое требование — O(n²)
   (см. test_25_big.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

Z = Path(__file__).resolve().parent / "fixtures/25_zoo"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def test_md_br_in_cell_keeps_one_line_per_view_line(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# Т\n\n| Поле | Описание |\n|---|---|\n| delivery | Адрес<br>или код отделения |\n", encoding="utf-8")
    v = dv.load(p)
    assert all("\n" not in ln["text"] for ln in v["lines"])
    num = dv.numbered(v).splitlines()
    assert len(num) == len(v["lines"]) and all(x.startswith("L") for x in num)
    assert any("delivery | Адрес или код отделения" in ln["text"] for ln in v["lines"])
    assert Q.verify_quote(v, "Адрес или код отделения")["verified"] == "exact"


def test_md_escaped_pipe_in_cell(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# Т\n\n| Поле | Значения |\n|---|---|\n| reason | `LOST \\| DAMAGED` |\n| note | знак \\| запрещён |\n",
                 encoding="utf-8")
    t = [ln["text"] for ln in dv.load(p)["lines"]]
    assert "reason | LOST | DAMAGED" in t and "note | знак | запрещён" in t


@pytest.mark.parametrize("enc", ["utf-16-be", "utf-16-le"])
@pytest.mark.parametrize("ext", [".txt", ".md"])
def test_utf16_without_bom(tmp_path, enc, ext):
    body = "# Перевыпуск\n\nКарта с причиной «утеря» блокируется сразу.\n\nСтоимость — 1 500 ₸.\n"
    p = tmp_path / f"t{ext}"
    p.write_bytes(body.encode(enc))
    v = dv.load(p)
    joined = "\n".join(ln["text"] for ln in v["lines"])
    assert "Карта с причиной «утеря» блокируется сразу." in joined
    assert "\x00" not in joined and "�" not in joined


def test_utf16_detector_leaves_other_bytes_alone():
    assert dv._utf16_without_bom("Обычный текст".encode("utf-8")) is None
    assert dv._utf16_without_bom("Обычный текст".encode("cp1251")) is None
    assert dv._utf16_without_bom(b"\x00\x01\x02\x03" * 8) is None  # двоичный мусор — не текст


@pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
def test_pdf_first_numbered_heading_is_a_section_not_title():
    v = dv.load(Z / "pdf_two_col_running.pdf")
    assert v["title"] == "Перевыпуск карты"  # из свойств PDF, а не «1. Назначение»
    ln = next(x for x in v["lines"] if x["text"].startswith("Сервис позволяет клиенту"))
    assert ln["section"] == "1. Назначение"


def test_numbered_heading_pattern():
    for t in ("1. Назначение", "2.3 Параметры", "IV. Риски", "Раздел 2. Доставка", "3) Сроки"):
        assert dv._NUMBERED_HEAD.match(t), t
    for t in ("Перевыпуск карты", "ТЗ 2026", "2026 год: план", "Ф-1. Настройка"):
        assert not dv._NUMBERED_HEAD.match(t), t


@pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
def test_pdf_word_numbered_list_is_list_not_table():
    v = dv.load(Z / "pdf_from_word.pdf")
    t = [ln["text"] for ln in v["lines"]]
    assert not any(x.startswith(("1. |", "2. |", "a. |")) for x in t), t
    assert "1. Клиент выбирает карту из списка активных карт." in t
    assert "a. Для причины «утеря» старая карта блокируется сразу." in t
    # продолжение пункта на следующей строке — в той же строке вида
    assert "2. При нехватке средств заказ ожидает пополнения не более трёх суток." in t
    # настоящая таблица того же документа — по-прежнему таблица
    assert "Срок выпуска | 5 рабочих дней | Без учёта доставки" in t


ZOO = sorted(p.name for p in Z.iterdir() if p.suffix in (".pdf", ".docx", ".html", ".txt", ".md"))


@pytest.mark.parametrize("name", ZOO)
def test_zoo_full_offline_review_with_exports(tmp_path, name):
    """Каждый файл зоопарка — весь конвейер без модели: отчёт, verify OK, выгрузки Jira/Word/PDF пишутся."""
    if name.endswith(".pdf") and not _has("pymupdf") or name.endswith(".docx") and not _has("docx"):
        pytest.skip("нет читателя формата")
    from bcc_review.v2 import pipeline, verify
    out = tmp_path / f"{name}.md"
    report, written = pipeline.review(Z / name, out, {"provider": "offline", "runs_dir": str(tmp_path / "runs"),
                                                      "html": False, "cache": False,
                                                      "export": ["jira", "docx", "pdf"]})
    res = verify.verify_report(report, Z / name)
    assert res["ok"], res["errors"][:3]
    assert out.is_file() and Path(written["jira"]).is_file()
    for fmt in ("docx", "pdf"):  # Word с примечаниями — для DOCX, PDF с выделениями — для PDF
        if name.endswith("." + fmt):
            assert Path(written[fmt]).is_file(), written
