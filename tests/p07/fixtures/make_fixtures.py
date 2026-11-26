"""Пересоздать синтетические фикстуры tests/p07/fixtures/case.{md,pdf,docx}.

Запуск: ``python tests/p07/fixtures/make_fixtures.py``. Нужны reportlab,
python-docx и шрифт DejaVuSans (кириллица, ₸, NBSP). Готовые файлы лежат в
репозитории, поэтому тестам эти зависимости не нужны (кроме чтения PDF/DOCX).
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

HERE = Path(__file__).resolve().parent
NB = " "
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

MD = f"""# Синтетическое ТЗ: порог расходов

## Функциональные требования

* **Ф-1.** Держатель задаёт порог от 1{NB}000 до 1{NB}000{NB}000 ₸ включительно.
* **Ф-3.** На карту приходится максимум один push за календарный месяц.
* **Ф-4.** Если накопленная сумма ниже нового порога, следующее достижение вызывает push независимо от истории.

## Повторы

Клиент получает push. Сумма в push не более 10 ₸. Клиент получает push.

Клиент получает push при достижении порога.

## Комиссии

Комиссия составляет более 100 ₸ за операцию.

Комиссия за SMS составляет не более 10{NB}₸.

## Символы

Знак 𝟙 обозначает первичный лимит 50{NB}000{NB}₸; про-
верка выполняется по времени UTC+5.

## REST API

| Метод | URL |
| :--- | :--- |
| GET | `/alerts/saveLimit` |

Приложение читает и сохраняет настройки через REST API.
"""

PDF_PAGES = [
    [
        ["Синтетическое ТЗ (PDF)"],
        [f"Комиссия за SMS составляет не более 10{NB}₸."],
        ["Система выполняет про-", "верку порога по времени UTC+5."],
    ],
    [
        ["Клиент получает push при достижении порога."],
        ["Комиссия составляет более 100 ₸ за операцию."],
    ],
]


def make_md() -> None:
    (HERE / "case.md").write_bytes(MD.encode("utf-8"))


def make_pdf() -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    c = canvas.Canvas(str(HERE / "case.pdf"), pagesize=A4, invariant=1)
    for page in PDF_PAGES:
        y = 780
        for paragraph in page:
            for line in paragraph:
                c.setFont("DejaVu", 12)
                c.drawString(72, y, line)
                y -= 16
            y -= 20
        c.showPage()
    c.save()


def make_docx() -> None:
    from datetime import datetime

    import docx

    d = docx.Document()
    d.core_properties.created = datetime(2026, 11, 1, tzinfo=UTC)
    d.add_heading("Синтетическое ТЗ (DOCX)", level=1)
    d.add_heading("Функциональные требования", level=2)
    d.add_paragraph(f"Ф-1. Держатель задаёт порог от 1{NB}000 до 1{NB}000{NB}000 ₸ включительно.")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Код"
    table.cell(0, 1).text = "Правило"
    table.cell(1, 0).text = "Ф-3"
    table.cell(1, 1).text = "На карту приходится максимум один push за календарный месяц."
    d.add_paragraph("Комиссия за SMS составляет не более 10 ₸.")
    d.save(str(HERE / "case.docx"))


if __name__ == "__main__":
    make_md()
    make_pdf()
    make_docx()
    print("ok:", ", ".join(p.name for p in sorted(HERE.glob("case.*"))))
