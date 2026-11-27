"""Генератор стресс-набора №03, третья волна.

    python tests/v2/fixtures/03_stress/make_wave3.py     # пересоздать файлы рядом со скриптом

* ``borderless.md`` → ``borderless.docx`` (pandoc: таблицы без линеек, стили Word по умолчанию) →
  ``borderless.pdf`` (LibreOffice). Шрифты документа подставляются (Calibri → Carlito, Cambria → Caladea): у
  подставленных нет кириллицы, буквы идут запасным шрифтом со сдвигом базовой линии, а пробелы и знаки — основным.
  Читатель v1 (PyMuPDF без нейросети вёрстки, как у жюри по ``requirements.txt``) отдаёт таблицу колонками, а знаки
  препинания уносит в конец строки. Проверяет ``docview``: таблица собирается по строкам, знаки на месте.

* ``cell_paragraphs.docx`` — Word: в ячейке критерия приёмки абзац и маркированный список; строка таблицы должна
  остаться одной строкой («Итог 50 000 ₸; Один push; Счётчик не сбрасывается»).
* ``ru_styles.docx`` — Word без заголовка-названия: части A и B — стилем «Заголовок 1» (уровень структуры), свой
  стиль «МойЗаголовок», подзаголовок «Требования к данным» — просто жирным абзацем.
* ``textbox.docx`` — Word: требование в надписи (текстовом поле, ``w:txbxContent`` с запасной копией VML),
  вложенная таблица, комментарий рецензента, гиперссылка. Читатель v1 надписи не видит — ``docview`` их добавляет.

Нужны pandoc и LibreOffice (``soffice``), python-docx. Тексты — вымышленные банковские ТЗ, не официальный документ
хакатона.
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


_TEXTBOX = (
    '<w:p {ns} xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:v="urn:schemas-microsoft-com:vml">'
    '<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" '
    'simplePos="0" relativeHeight="1" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" '
    'y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH><wp:positionV '
    'relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV><wp:extent cx="3000000" cy="500000"/>'
    '<wp:wrapSquare wrapText="bothSides"/><wp:docPr id="1" name="TextBox 1"/><a:graphic><a:graphicData '
    'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp><wps:spPr><a:xfrm><a:off x="0" '
    'y="0"/><a:ext cx="3000000" cy="500000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></wps:spPr>'
    '<wps:txbx><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></wps:txbx><wps:bodyPr/>'
    '</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict><v:shape>'
    '<v:textbox><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict>'
    '</mc:Fallback></mc:AlternateContent></w:r></w:p>')


def make_textbox_docx(path: Path) -> None:
    from docx import Document
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import nsdecls, qn
    d = Document()
    d.add_heading("ТЗ: Перевыпуск карты", 0)
    d.add_heading("1. Часть A. Бизнес-требования", 1)
    p = d.add_paragraph("Ф-1. Клиент заказывает перевыпуск в приложении; стоимость — 1 000 ₸.")
    d.add_comment(p.runs, text="Уточнить стоимость для премиальных карт", author="Рецензент")
    p2 = d.add_paragraph("Ф-2. Срок изготовления — 5 рабочих дней.")
    p2._p.addnext(parse_xml(_TEXTBOX.format(ns=nsdecls("w", "wp", "a"),
                                           text="Ф-3. Старая карта блокируется после активации новой.")))
    d.add_heading("2. Часть B. API", 1)
    t = d.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    t.cell(0, 0).text, t.cell(0, 1).text = "Поле", "Описание"
    t.cell(1, 0).text, t.cell(1, 1).text = "cardId", "Идентификатор карты"
    t.cell(2, 0).text = "delivery"
    inner = t.cell(2, 1).add_table(rows=2, cols=2)
    inner.cell(0, 0).text, inner.cell(0, 1).text = "COURIER", "Курьер, 1–3 дня"
    inner.cell(1, 0).text, inner.cell(1, 1).text = "BRANCH", "Отделение, 5 дней"
    d.add_paragraph("Ответ 200 — заказ принят; 409 — перевыпуск уже заказан.")
    par = d.add_paragraph("Документация: ")
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), d.part.relate_to("https://example.org/api", "http://schemas.openxmlformats.org/"
                                          "officeDocument/2006/relationships/hyperlink", is_external=True))
    run, txt = OxmlElement("w:r"), OxmlElement("w:t")
    txt.text = "описание API"
    run.append(txt)
    link.append(run)
    par._p.append(link)
    d.save(path)


def make_cell_paragraphs(path: Path) -> None:
    from docx import Document
    d = Document()
    d.add_heading("ТЗ: Уведомление о пороге", 0)
    d.add_heading("Критерии приемки", 1)
    t = d.add_table(rows=2, cols=3)
    t.style = "Table Grid"
    for i, h in enumerate(["Исходные условия", "Действие", "Ожидаемый результат"]):
        t.cell(0, i).text = h
    t.cell(1, 0).text = "Расходы 48 500 ₸, порог 50 000 ₸"
    t.cell(1, 1).text = "Покупка на 1 500 ₸"
    c = t.cell(1, 2)
    c.text = "Итог 50 000 ₸"
    c.add_paragraph("Один push", style="List Bullet")
    c.add_paragraph("Счётчик не сбрасывается", style="List Bullet")
    d.add_paragraph("После таблицы.")
    d.save(path)


def make_ru_styles(path: Path) -> None:
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    d = Document()

    def style(name: str, lvl: int):
        st = d.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.font.size, st.font.bold = Pt(16 - 2 * lvl), True
        o = OxmlElement("w:outlineLvl")
        o.set(qn("w:val"), str(lvl))
        st.element.get_or_add_pPr().append(o)
        return st
    h1, h2, own = style("Заголовок 1", 0), style("Заголовок 2", 1), style("МойЗаголовок", 1)
    d.add_paragraph("Часть A. Новый функционал", style=h1)
    d.add_paragraph("Функциональные требования", style=h2)
    d.add_paragraph("Ф-1. Порог от 1 000 до 1 000 000 ₸.")
    d.add_paragraph("Часть B. REST API", style=h1)
    d.add_paragraph("Логика метода", style=own)
    d.add_paragraph("1. Проверить сессию.")
    d.add_paragraph("Требования к данным").runs[0].bold = True
    d.add_paragraph("Хранить идентификатор карты.")
    d.save(path)


def main() -> int:
    make_ru_styles(HERE / "ru_styles.docx")
    make_textbox_docx(HERE / "textbox.docx")
    make_cell_paragraphs(HERE / "cell_paragraphs.docx")
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
