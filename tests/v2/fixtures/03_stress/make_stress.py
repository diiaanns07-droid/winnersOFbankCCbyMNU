"""Генератор стресс-набора №03: документы «как на финале» в разных форматах.

    python tests/v2/fixtures/03_stress/make_stress.py            # пересоздать все файлы рядом со скриптом

Файлы (тексты — вымышленные банковские ТЗ, не официальный документ хакатона):

* ``docx_merged.docx`` — Word: колонтитулы, автонумерация (List Number), таблица с объединёнными ячейками
  по горизонтали и вертикали, маркированный список;
* ``docx_tracked.docx`` — Word с непринятыми исправлениями (вставка и удаление);
* ``toc.docx`` + ``toc.pdf`` — оглавление с точками и номерами страниц; в PDF из LibreOffice «-1.» и точки —
  отдельные фрагменты без зазора;
* ``word_export.docx`` + ``word_export.pdf`` — PDF «из Word» (LibreOffice): колонтитулы на каждой странице
  с номером страницы, переносы слов (мягкие переносы), 3+ страницы, таблица;
* ``two_columns.pdf`` — PDF в две колонки (reportlab), 2 страницы;
* ``scan_page.pdf`` — 2 страницы: текст и страница-скан (картинка без текстового слоя);
* ``api_narrow.pdf`` — узкая таблица API (слова режутся без дефиса) и страница статусов почти целиком латиницей;
* ``no_part_b.md`` — Markdown только с бизнес-частью, без спецификации API;
* ``long_tz.md`` — длинное ТЗ на 600+ строк, с повторяющимися фразами в разных разделах; ``long_tz.docx`` и
  ``long_tz.pdf`` — оно же в Word и PDF из Word (многостраничные таблицы);
* ``word_saved.html`` — официальный документ (``release/input/requirements.docx``), сохранённый как веб-страница;
* ``confluence.html`` — HTML-экспорт страницы Confluence: хлебные крошки, метаданные, оглавление, панели, код,
  таблицы confluenceTable, вложения и подвал.

Нужны python-docx, reportlab, LibreOffice (``soffice``) для PDF из Word, шрифт DejaVu Sans.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# --------------------------------------------------------------------------- DOCX: объединённые ячейки, колонтитулы
def _field(par, instr: str) -> None:
    """Поле Word (PAGE, NUMPAGES) в абзаце колонтитула."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = par.add_run()
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
            run._r.append(el)
        elif text == instr:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = f" {instr} "
            run._r.append(el)
        else:
            t = OxmlElement("w:t")
            t.text = text
            run._r.append(t)


def _headers(doc, head: str, foot: str) -> None:
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = head
    p = sec.footer.paragraphs[0]
    p.text = foot + " · стр. "
    _field(p, "PAGE")
    p.add_run(" из ")
    _field(p, "NUMPAGES")


def make_docx_tracked(path: Path) -> None:
    """DOCX с непринятыми исправлениями: удалено «100 000», вставлено «200 000»."""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    d = docx.Document()
    d.add_heading("Лимит снятия наличных", level=1)
    d.add_paragraph("СН-1. Клиент снимает наличные в банкоматах банка без комиссии.")
    p = d.add_paragraph()
    p.add_run("СН-2. Лимит снятия составляет ")
    for tag, text, rid in (("w:del", "100 000", "1"), ("w:ins", "200 000", "2")):
        el = OxmlElement(tag)
        el.set(qn("w:id"), rid)
        el.set(qn("w:author"), "Аналитик")
        el.set(qn("w:date"), "2026-11-20T10:00:00Z")
        r = OxmlElement("w:r")
        t = OxmlElement("w:delText" if tag == "w:del" else "w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
        el.append(r)
        p._p.append(el)
    p.add_run(" тенге в сутки.")
    d.save(path)


def make_docx_toc(path: Path) -> None:
    """Word с оглавлением (табуляция с точками и номером страницы) перед разделами; PDF из него — через LibreOffice
    со шрифтом по умолчанию (подстановка Calibri даёт отдельные фрагменты для «-1.» и точек)."""
    import docx
    from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.shared import Pt
    d = docx.Document()
    d.add_heading("Выпуск виртуальной карты", level=1)
    d.add_paragraph("Содержание").runs[0].bold = True
    for t, pg in (("1. Общие сведения", 2), ("2. Цели", 2), ("3. Функциональные требования", 3),
                  ("4. Критерии приёмки", 4)):
        p = d.add_paragraph()
        p.paragraph_format.tab_stops.add_tab_stop(Pt(450), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        p.add_run(f"{t}\t{pg}")
    for head, body in (("1. Общие сведения", "Клиент выпускает виртуальную карту в приложении."),
                       ("2. Цели", "Карта доступна для оплаты сразу после выпуска."),
                       ("3. Функциональные требования", "ВК-1. Выпуск бесплатный."),
                       ("4. Критерии приёмки", "Карта выпущена за 10 секунд.")):
        d.add_heading(head, level=2)
        d.add_paragraph(body)
    d.save(path)


def make_docx_merged(path: Path) -> None:
    import docx
    d = docx.Document()
    _headers(d, "АО «Учебный банк» · Конфиденциально · ТЗ-214 v1.3", "Внутренний документ")
    d.add_heading("Блокировка карты по сроку", level=1)
    d.add_paragraph("Документ описывает временную блокировку карты клиентом в мобильном банке.")
    d.add_heading("Общие сведения", level=2)
    t = d.add_table(rows=5, cols=3)
    t.style = "Table Grid"
    t.cell(0, 0).text = "Поле"
    head = t.cell(0, 1).merge(t.cell(0, 2))          # объединение по горизонтали
    head.text = "Значение"
    t.cell(1, 0).text = "Продукт"
    t.cell(1, 1).text = "Мобильный банк"
    t.cell(1, 2).text = "iOS и Android"
    owner = t.cell(2, 0).merge(t.cell(3, 0))         # объединение по вертикали
    owner.text = "Ответственные"
    t.cell(2, 1).text = "Владелец продукта"
    t.cell(2, 2).text = "Отдел карточных продуктов"
    t.cell(3, 1).text = "Аналитик"
    t.cell(3, 2).text = "Команда платёжных сервисов"
    t.cell(4, 0).text = "Задача"
    t.cell(4, 1).merge(t.cell(4, 2)).text = "CARD-1402"
    d.add_heading("Функциональные требования", level=2)
    for item in ("Клиент блокирует карту на срок от 1 до 30 суток.",
                 "Во время блокировки процессинг отклоняет новые авторизации.",
                 "По окончании срока карта разблокируется автоматически.",
                 "Клиент может досрочно разблокировать карту в приложении."):
        d.add_paragraph(item, style="List Number")
    d.add_paragraph("Уточнения к пункту 2:")
    for item in ("Авторизации, одобренные до блокировки, проводятся.",
                 "Возвраты на заблокированную карту зачисляются."):
        d.add_paragraph(item, style="List Number 2")
    d.add_heading("Нефункциональные требования", level=2)
    for item in ("Блокировка вступает в силу не позднее 10 секунд после ответа сервиса.",
                 "Журнал изменений статуса хранится 5 лет."):
        d.add_paragraph(item, style="List Bullet")
    d.add_heading("Критерии приёмки", level=2)
    t2 = d.add_table(rows=3, cols=3)
    t2.style = "Table Grid"
    for i, row in enumerate([("Исходные условия", "Действие", "Ожидаемый результат"),
                             ("Карта активна", "Заблокировать на 7 суток", "Статус BLOCKED, срок 7 суток"),
                             ("Карта заблокирована", "Авторизация на 1 000 ₸", "Отказ с причиной «Карта заблокирована»")]):
        for j, v in enumerate(row):
            t2.cell(i, j).text = v
    d.save(path)


# --------------------------------------------------------------------------- PDF из Word: колонтитулы и переносы
_SHY = "­"


def _soft_hyphens(text: str) -> str:
    """Мягкие переносы в длинных словах: Word/LibreOffice переносят по ним в конце строки."""
    def cut(m: re.Match) -> str:
        w = m.group(0)
        if len(w) < 9:
            return w
        parts, i = [], 0
        while len(w) - i > 6:
            parts.append(w[i:i + 4])
            i += 4
        parts.append(w[i:])
        return _SHY.join(parts)
    return re.sub(r"[А-Яа-яЁё]{9,}", cut, text)


WORD_EXPORT_PARAS = [
    ("h1", "Лимит переводов между своими счетами"),
    ("p", "Документ описывает суточный лимит переводов между счетами одного клиента в мобильном и интернет-банке."),
    ("h2", "Цели"),
    ("p", "Снизить риск мошеннических переводов после компрометации учётной записи, не мешая клиенту распоряжаться "
          "собственными средствами, и дать службе мониторинга инструмент для оперативного ограничения операций."),
    ("h2", "Функциональные требования"),
    ("p", "ЛП-1. Клиент устанавливает суточный лимит переводов между своими счетами в диапазоне от 10 000 до "
          "5 000 000 тенге включительно; по умолчанию лимит равен 1 000 000 тенге."),
    ("p", "ЛП-2. Сумма переводов за сутки считается по времени Астаны с 00:00 до 23:59 включительно; переводы, "
          "отменённые банком, в сумму не включаются, а возвраты уменьшают использованную часть лимита."),
    ("p", "ЛП-3. Перевод, после которого сумма за сутки превысит лимит, отклоняется с сообщением о превышении "
          "лимита и предложением изменить лимит в настройках безопасности."),
    ("p", "ЛП-4. Увеличение лимита вступает в силу через 24 часа после подтверждения одноразовым паролем, "
          "уменьшение — немедленно; о каждом изменении клиент получает уведомление."),
    ("h2", "Нефункциональные требования"),
    ("p", "Проверка лимита выполняется не дольше 300 миллисекунд для 95 процентов запросов; журнал изменений "
          "лимита хранится не менее пяти лет и доступен службе информационной безопасности."),
    ("h2", "Требования к данным"),
    ("p", "Хранить идентификатор клиента, текущий лимит в тиынах, дату вступления в силу нового лимита, "
          "использованную сумму за текущие сутки и историю изменений с указанием канала подтверждения."),
    ("table", [("Поле", "Тип", "Описание"),
               ("client_id", "string", "Идентификатор клиента"),
               ("limit", "integer", "Лимит в тиынах"),
               ("effective_at", "datetime", "Дата вступления в силу")]),
    ("h2", "Требования к интеграции"),
    ("p", "Приложение читает лимит методом getTransferLimit и изменяет его методом setTransferLimit; "
          "процессинг переводов запрашивает остаток лимита перед каждой операцией."),
    ("h2", "Критерии приёмки"),
    ("p", "Лимит 100 000 тенге, использовано 90 000 тенге: перевод на 15 000 тенге отклоняется с сообщением "
          "о превышении лимита, а перевод на 10 000 тенге проходит успешно."),
    ("p", "Клиент увеличивает лимит в 10:00: до 10:00 следующих суток действует прежний лимит, после — новый."),
]


def make_word_export(docx_path: Path, pdf_path: Path) -> bool:
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "DejaVu Sans"
    st.font.size = Pt(11)
    _headers(d, "АО «Учебный банк» · ТЗ-301 · Конфиденциально", "Лимит переводов v2.1")
    for _ in range(2):  # повтор блока — чтобы вышло 3+ страницы с колонтитулами
        for kind, val in WORD_EXPORT_PARAS:
            if kind == "h1":
                if _ == 0:
                    d.add_heading(val, level=1)
            elif kind == "h2":
                d.add_heading(val if _ == 0 else f"{val} (продолжение)", level=2)
            elif kind == "p":
                d.add_paragraph(_soft_hyphens(val if _ == 0 else val.replace("ЛП-", "ЛП-1")))
            elif kind == "table":
                t = d.add_table(rows=len(val), cols=len(val[0]))
                t.style = "Table Grid"
                for i, row in enumerate(val):
                    for j, v in enumerate(row):
                        t.cell(i, j).text = v
    d.save(docx_path)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("нет LibreOffice: word_export.pdf не пересоздан", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(docx_path)],
                       check=True, capture_output=True, timeout=180)
        shutil.copy(Path(tmp) / (docx_path.stem + ".pdf"), pdf_path)
    return True


# --------------------------------------------------------------------------- PDF в две колонки, скан
def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))


TWO_COL = [
    ("h", "Кэшбэк за оплату коммунальных услуг"),
    ("p", "Клиент получает кэшбэк за оплату коммунальных услуг картой в мобильном банке."),
    ("h", "Функциональные требования"),
    ("p", "КУ-1. Кэшбэк составляет 1 % от суммы платежа, но не более 2 000 ₸ за месяц."),
    ("p", "КУ-2. Кэшбэк начисляется за платежи поставщикам из справочника категорий «Коммунальные услуги»."),
    ("p", "КУ-3. Кэшбэк зачисляется на карту до 10-го числа следующего месяца."),
    ("p", "КУ-4. Платёж, отменённый поставщиком, исключается из расчёта кэшбэка."),
    ("h", "Нефункциональные требования"),
    ("p", "Расчёт кэшбэка за месяц выполняется пакетно и занимает не более 2 часов."),
    ("h", "Требования к данным"),
    ("p", "Хранить идентификатор платежа, поставщика, сумму в тиынах, месяц и сумму кэшбэка."),
    ("h", "Критерии приёмки"),
    ("p", "Платёж 50 000 ₸ поставщику электроэнергии: кэшбэк 500 ₸ зачислен до 10-го числа."),
    ("p", "Платежи на 300 000 ₸ за месяц: кэшбэк ограничен суммой 2 000 ₸."),
]


def make_two_columns(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer
    _fonts()
    w, h = A4
    gap, margin = 18, 50
    colw = (w - 2 * margin - gap) / 2
    frames = [Frame(margin, margin, colw, h - 2 * margin, id="left"),
              Frame(margin + colw + gap, margin, colw, h - 2 * margin, id="right")]
    doc = BaseDocTemplate(str(path), pagesize=A4, pageTemplates=[PageTemplate(id="two", frames=frames)],
                          title="Кэшбэк за коммунальные услуги")
    hs = ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=13, leading=16, spaceBefore=8, spaceAfter=4)
    ps = ParagraphStyle("p", fontName="DejaVu", fontSize=10.5, leading=14, spaceAfter=6)
    story = []
    for rep in range(3):
        for kind, text in TWO_COL:
            if kind == "h":
                story.append(Paragraph(text if rep == 0 else f"{text} — раздел {rep + 1}", hs))
            else:
                story.append(Paragraph(text if rep == 0 else text.replace("КУ-", f"КУ-{rep + 1}"), ps))
        story.append(Spacer(1, 10))
    doc.build(story)


def make_api_pdf(path: Path) -> None:
    """Спецификация API: узкая таблица (длинные слова режутся без дефиса — «strin g», «Mandator y») и последняя
    страница со статусами почти целиком латиницей (читатель v1 принимает её за «нечитаемый шрифт»)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
    _fonts()
    hs = ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=13, leading=16, spaceBefore=8, spaceAfter=6)
    ps = ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=13, spaceAfter=5)
    cs = ParagraphStyle("c", fontName="DejaVu", fontSize=9, leading=11)
    story = [Paragraph("Метод getStatement", hs),
             Paragraph("Метод возвращает выписку по счёту за период. Даты передаются в формате ГГГГ-ММ-ДД.", ps),
             Paragraph("Параметры запроса", hs)]
    rows = [["Parameter", "Format", "Mandatory", "Description"],
            ["accountId", "string", "Да", "Идентификатор счёта"],
            ["dateFrom", "string", "Да", "Начало периода"],
            ["pageSize", "integer", "Нет", "Число операций на странице"],
            ["includeHolds", "boolean", "Нет", "Показывать заблокированные суммы"]]
    t = Table([[Paragraph(c, cs) for c in r] for r in rows], colWidths=[52, 34, 40, 170])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, PageBreak(), Paragraph("Статусы", hs)]
    for code, title, body in (("200", "Successful", '{"items":[],"total":0}'),
                              ("400", "Unsuccessful — Bad request", '{"message":"Invalid date range"}'),
                              ("401", "Unsuccessful — Unauthorized", '{"message":"Authorization required"}'),
                              ("404", "Unsuccessful — Not found", '{"message":"Account not found"}'),
                              ("410", "Unsuccessful — Gone", '{"message":"Счёт закрыт"}'),
                              ("500", "Unsuccessful — Internal server error", '{"message":"Internal error"}')):
        story += [Paragraph(f"{code}. {title}", hs), Paragraph(body, ps)]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def make_scan(path: Path) -> None:
    """Страница 1 — текст, страница 2 — картинка с текстом (скан без текстового слоя)."""
    import io
    import pymupdf
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("DejaVu-Bold", 14)
    c.drawString(60, 780, "Перевыпуск карты")
    c.setFont("DejaVu", 11)
    c.drawString(60, 750, "ПК-1. Клиент заказывает перевыпуск карты в приложении.")
    c.drawString(60, 732, "ПК-2. Перевыпуск бесплатен при истечении срока действия.")
    c.showPage()
    c.setFont("DejaVu", 11)
    c.drawString(60, 780, "ПК-3. Старая карта блокируется после активации новой.")
    c.showPage()
    c.save()
    # вторую страницу превращаем в картинку: рендер → новая страница только с изображением
    src = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    out = pymupdf.open()
    out.insert_pdf(src, from_page=0, to_page=0)
    pix = src[1].get_pixmap(dpi=80)
    page = out.new_page(width=src[1].rect.width, height=src[1].rect.height)
    page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=60))
    out.save(str(path))


# --------------------------------------------------------------------------- Markdown
NO_PART_B = """# Автоплатёж за мобильную связь

Бизнес-требования. Спецификация API будет выпущена отдельным документом.

## Общие сведения

| Поле | Значение |
| :--- | :--- |
| **Наименование задачи** | Автоплатёж за мобильную связь |
| **Продукт** | Мобильный банк |
| **Задача в Jira** | PAY-881 |

## Цели
Клиент не остаётся без связи: баланс телефона пополняется автоматически.

## Функциональные требования
* **АМ-1.** Клиент подключает автоплатёж для номера телефона и выбирает карту списания.
* **АМ-2.** Автоплатёж срабатывает, когда баланс номера опускается ниже порога от 100 до 5 000 ₸.
* **АМ-3.** Сумма пополнения задаётся клиентом от 500 до 20 000 ₸.
* **АМ-4.** Не более трёх пополнений одного номера в сутки.
* **АМ-5.** При недостатке средств на карте автоплатёж повторяется через 6 часов, не более двух раз.

## Нефункциональные требования
Запрос баланса у оператора выполняется не реже одного раза в час.

## Критерии приёмки

| Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- |
| Порог 1 000 ₸, баланс 1 200 ₸ | Баланс снижается до 900 ₸ | Пополнение на сумму автоплатежа |
| Три пополнения за сутки | Баланс ниже порога | Пополнение не выполняется |
"""


def make_long_md(path: Path) -> int:
    """Длинное ТЗ: 17 подсистем × (требования, таблица, критерии). Фраза «Журнал операций хранится 5 лет»
    повторяется в каждом разделе — для проверки привязки цитаты к ближайшему вхождению."""
    subsystems = ["Регистрация", "Вход", "Карты", "Счета", "Переводы", "Платежи", "Кредиты", "Депозиты",
                  "Уведомления", "Профиль", "Безопасность", "Отчёты", "Поддержка", "Тарифы", "Кассы", "Валюта", "Документы"]
    out = ["# Мобильный банк для малого бизнеса: требования к выпуску 3.0", "",
           "Сводное техническое задание на выпуск. Разделы описывают подсистемы приложения.", ""]
    for k, name in enumerate(subsystems, 1):
        code = f"Т{k:02d}"
        out += [f"## {k}. Подсистема «{name}»", "", "### Функциональные требования", ""]
        for i in range(1, 9):
            out.append(f"* **{code}-{i}.** Подсистема «{name}» выполняет операцию {i}: пользователь видит "
                       f"результат не позднее {i * 2} секунд, а ошибка показывается текстом с кодом {code}{i:02d}.")
        out += ["", "### Данные", "", "| Поле | Тип | Описание |", "| :--- | :--- | :--- |"]
        for i in range(1, 7):
            out.append(f"| `{name.lower()}_{i}` | string | Атрибут {i} подсистемы «{name}» |")
        out += ["", "### Нефункциональные требования", "",
                "Журнал операций хранится 5 лет.",
                f"Доступность подсистемы «{name}» — не ниже 99,{k % 10} % в месяц.", "",
                "### Критерии приёмки", "",
                "| Исходные условия | Действие | Ожидаемый результат |", "| :--- | :--- | :--- |"]
        for i in range(1, 4):
            out.append(f"| Пользователь вошёл в «{name}» | Операция {i} | Результат за {i * 2} с |")
        out.append("")
    text = "\n".join(out) + "\n"
    path.write_text(text, encoding="utf-8")
    return text.count("\n")


CONFLUENCE = """<!DOCTYPE html>
<html>
<head>
<title>Платёжные сервисы : ТЗ Пополнение депозита с карты</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<link rel="stylesheet" href="styles/site.css" type="text/css" />
</head>
<body class="theme-default aui-theme-default">
<div id="page">
<div id="main" class="aui-page-panel">
<div id="main-header">
<div id="breadcrumb-section">
<ol id="breadcrumbs">
<li class="first"><span><a href="index.html">Платёжные сервисы</a></span></li>
<li><span><a href="Requirements_12345.html">Требования</a></span></li>
</ol>
</div>
<h1 id="title-heading" class="pagetitle">
<span id="title-text">Платёжные сервисы : ТЗ Пополнение депозита с карты</span>
</h1>
</div>
<div id="content" class="view">
<div class="page-metadata">
Создатель <span class='author'> Иванова А.</span>, последнее изменение <span class='editor'> Петров Б.</span> 12.11.2026
</div>
<div id="main-content" class="wiki-content group">
<p><span class="status-macro aui-lozenge aui-lozenge-current">ЧЕРНОВИК</span></p>
<div class="toc-macro rbtoc1700000000000">
<ul class="toc-indentation">
<li><a href="#id-ТЗ-Цели">Цели</a></li>
<li><a href="#id-ТЗ-Функциональныетребования">Функциональные требования</a></li>
<li><a href="#id-ТЗ-API">API</a></li>
</ul>
</div>
<h2 id="id-ТЗ-Цели">Цели</h2>
<p>Клиент пополняет депозит с карты любого банка Казахстана без визита в отделение.</p>
<div class="confluence-information-macro confluence-information-macro-warning">
<span class="aui-icon aui-icon-small aui-iconfont-error confluence-information-macro-icon"></span>
<div class="confluence-information-macro-body"><p>Пополнение депозита «Неснижаемый» запрещено условиями договора.</p></div>
</div>
<h2 id="id-ТЗ-Функциональныетребования">Функциональные требования</h2>
<ol>
<li>Клиент выбирает депозит и карту, вводит сумму от 1&nbsp;000 до 10&nbsp;000&nbsp;000&nbsp;₸.</li>
<li>Комиссия за пополнение картой другого банка — 0,5&nbsp;% от суммы, не менее 200&nbsp;₸.</li>
<li>Пополнение зачисляется на депозит в течение 5 минут после подтверждения 3-D Secure.</li>
<li>При отказе эквайера сумма не списывается, клиент видит причину отказа.</li>
</ol>
<h2 id="id-ТЗ-API">API</h2>
<div class="table-wrap"><table class="confluenceTable"><colgroup><col/><col/><col/></colgroup>
<tbody>
<tr><th class="confluenceTh">Параметр</th><th class="confluenceTh">Тип</th><th class="confluenceTh">Описание</th></tr>
<tr><td class="confluenceTd"><code>depositId</code></td><td class="confluenceTd">string</td><td class="confluenceTd">Идентификатор депозита</td></tr>
<tr><td class="confluenceTd"><code>amount</code></td><td class="confluenceTd">integer</td><td class="confluenceTd"><p>Сумма в тиынах</p></td></tr>
<tr><td class="confluenceTd" colspan="2">Итого полей</td><td class="confluenceTd">2</td></tr>
</tbody></table></div>
<div class="code panel pdl conf-macro output-block" style="border-width: 1px;">
<div class="codeHeader panelHeader pdl"><b>Пример ответа</b></div>
<div class="codeContent panelContent pdl">
<pre class="syntaxhighlighter-pre" data-syntaxhighlighter-params="brush: java; gutter: false" data-theme="Confluence">{"status":"ACCEPTED",
 "operationId":"op-17"}</pre>
</div></div>
<p>Ответственный аналитик: <a class="confluence-userlink user-mention" href="/display/~ivanova">Иванова А.</a></p>
</div>
</div>
<div class="pageSection group">
<div class="pageSectionHeader"><h2 id="attachments" class="pageSectionTitle">Вложения:</h2></div>
<div class="greybox" align="left">
<img src="images/icons/bullet_blue.gif" height="8" width="8" alt=""/>
<a href="attachments/12345/sequence.png">sequence.png</a> (image/png)<br/>
</div>
</div>
</div>
<div id="footer" role="contentinfo">
<section class="footer-body">
<p>Документ создан Confluence 12.11.2026 10:15</p>
<div id="footer-logo"><a href="http://www.atlassian.com/">Atlassian</a></div>
</section>
</div>
</div>
</body>
</html>
"""


def main() -> int:
    make_docx_merged(HERE / "docx_merged.docx")
    make_docx_tracked(HERE / "docx_tracked.docx")
    make_docx_toc(HERE / "toc.docx")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(HERE / "toc.docx")],
                           check=True, capture_output=True, timeout=180)
            shutil.copy(Path(tmp) / "toc.pdf", HERE / "toc.pdf")
    make_word_export(HERE / "word_export.docx", HERE / "word_export.pdf")
    make_two_columns(HERE / "two_columns.pdf")
    make_scan(HERE / "scan_page.pdf")
    make_api_pdf(HERE / "api_narrow.pdf")
    (HERE / "no_part_b.md").write_text(NO_PART_B, encoding="utf-8")
    n = make_long_md(HERE / "long_tz.md")
    # то же длинное ТЗ в DOCX (конвертер официального документа) и PDF из Word (LibreOffice)
    sys.path.insert(0, str(HERE))
    from make_official_docx import convert
    convert(HERE / "long_tz.md", HERE / "long_tz.docx")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(HERE / "long_tz.docx")],
                           check=True, capture_output=True, timeout=300)
            shutil.copy(Path(tmp) / "long_tz.pdf", HERE / "long_tz.pdf")
            # официальный документ, сохранённый из Word как веб-страница (LibreOffice: переносы строк внутри <p>,
            # <li><p>…</p></li>, стили)
            subprocess.run([soffice, "--headless", "--convert-to", "html", "--outdir", tmp,
                            str(HERE.parents[3] / "release/input/requirements.docx")],
                           check=True, capture_output=True, timeout=300)
            shutil.copy(Path(tmp) / "requirements.html", HERE / "word_saved.html")
    (HERE / "confluence.html").write_text(CONFLUENCE, encoding="utf-8")
    print(f"готово: {HERE} (long_tz.md — {n} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
