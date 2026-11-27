"""Генератор стресс-набора №03, третья волна.

    python tests/v2/fixtures/03_stress/make_wave3.py     # пересоздать файлы рядом со скриптом

* ``borderless.md`` → ``borderless.docx`` (pandoc: таблицы без линеек, стили Word по умолчанию) →
  ``borderless.pdf`` (LibreOffice). Шрифты документа подставляются (Calibri → Carlito, Cambria → Caladea): у
  подставленных нет кириллицы, буквы идут запасным шрифтом со сдвигом базовой линии, а пробелы и знаки — основным.
  Читатель v1 (PyMuPDF без нейросети вёрстки, как у жюри по ``requirements.txt``) отдаёт таблицу колонками, а знаки
  препинания уносит в конец строки. Проверяет ``docview``: таблица собирается по строкам, знаки на месте.

Нужны pandoc и LibreOffice (``soffice``). Текст — вымышленное банковское ТЗ, не официальный документ хакатона.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

BORDERLESS = """# Кредитные каникулы по кредитной карте

Документ подготовлен для проверки чтения PDF. Таблицы в нём — без линеек.

## Общие сведения

| Поле | Значение |
|---|---|
| Наименование задачи | Кредитные каникулы по кредитной карте |
| Продукт | Мобильный банк, кредитные карты |
| Бизнес-процесс | Обслуживание держателя кредитной карты с просроченной задолженностью |
| Владелец | Управление розничного кредитования |

## Функциональные требования

К-1. Клиент без просрочки может взять каникулы на срок от 1 до 3 месяцев, один раз в год.

К-2. На время каникул минимальный платёж равен нулю; проценты начисляются по ставке договора.

К-3. Досрочный выход из каникул доступен в приложении в любой день.

## Критерии приемки

| Исходные условия | Действие | Ожидаемый результат |
|---|---|---|
| Просрочки нет, каникулы в этом году не брались | Оформить каникулы на 2 месяца | Минимальный платёж 0 ₸ в течение 2 месяцев |
| Каникулы уже брались 10 марта | Оформить повторно 1 июня того же года | Отказ с текстом «Каникулы доступны раз в год» |
| Просрочка 5 дней | Оформить каникулы | Отказ, кнопка недоступна |

## Логика метода

- Проверить сессию клиента.
- Проверить отсутствие просрочки.
- Сохранить срок каникул и вернуть дату окончания.
"""


def main() -> int:
    md = HERE / "borderless.md"
    md.write_text(BORDERLESS, encoding="utf-8")
    pandoc = shutil.which("pandoc")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not pandoc or not soffice:
        print("нужны pandoc и LibreOffice")
        return 1
    subprocess.run([pandoc, str(md), "-o", str(HERE / "borderless.docx")], check=True, timeout=120)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(HERE / "borderless.docx")],
                       check=True, capture_output=True, timeout=300)
        shutil.copy(Path(tmp) / "borderless.pdf", HERE / "borderless.pdf")
    print(f"готово: {HERE / 'borderless.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
