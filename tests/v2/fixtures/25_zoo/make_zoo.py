"""Генератор «зоопарка» трудных входов №25: документы банка, какими их приносят на финал.

    python tests/v2/fixtures/25_zoo/make_zoo.py        # пересоздать все файлы рядом со скриптом

Тексты — вымышленное ТЗ «Перевыпуск карты» и его варианты, без данных банка и без слов официального документа.
Рядом пишется ``truth.json``: для каждого файла — фразы, которые читатель обязан отдать целиком на одной строке,
с ожидаемым разделом и страницей, и фразы, которых в тексте быть не должно (колонтитулы, удалённые исправления).

Файлы:

* ``pdf_two_col_running.pdf`` — две колонки, верхний и нижний колонтитул с номером страницы на каждой из 3 страниц,
  нумерованные списки «1.», «2)», «а)»;
* ``pdf_long_table.pdf`` — таблица на 3 страницы с повтором шапки, перенос текста в ячейках;
* ``pdf_typo.pdf`` — лигатуры (ﬁ, ﬂ, ﬀ), мягкие переносы, неразрывные пробелы, «ё», «ёлочки» и прямые кавычки;
* ``docx_autonum.docx`` + ``pdf_from_word.pdf`` — многоуровневая автонумерация (1., 1.1., а)), сноски, таблица,
  колонтитулы; PDF — тот же документ через LibreOffice;
* ``docx_notes.docx`` — сноски, концевые сноски, примечания рецензента, гиперссылки;
* ``docx_revisions.docx`` — принятые и непринятые исправления: вставка, удаление, перенос (moveFrom/moveTo);
* ``docx_controls.docx`` — поля формы (элементы управления содержимым w:sdt), простое поле w:fldSimple;
* ``confluence_macros.html`` — экспорт Confluence: раскрывающиеся блоки, статусы, задачи, панели, таблица
  с заголовками строк и объединёнными ячейками;
* ``txt_cp1251.txt`` (Windows-1251, CRLF), ``txt_utf16.txt`` (UTF-16 LE с BOM, «Юникод» Блокнота),
  ``txt_utf16be.txt`` (UTF-16 BE без BOM);
* ``md_tables.md`` — таблицы с экранированной чертой, кодом с чертой, без крайних черт, <br> в ячейках, сноски.

Нужны python-docx, reportlab, pandoc, LibreOffice (``soffice``), шрифт DejaVu Sans.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TRUTH: dict[str, dict] = {}


def _truth(name: str, *, keep: list[tuple[str, str, int | None]], absent: list[str] = (), warn: list[str] = ()):
    """keep — (фраза, часть раздела, страница или None); absent — чего в тексте быть не должно."""
    TRUTH[name] = {"keep": [{"text": t, "section": s, "page": p} for t, s, p in keep],
                   "absent": list(absent), "warn": list(warn)}


def _fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))


# --------------------------------------------------------------------------- PDF: две колонки + колонтитулы
TWO_COL = [
    ("h", "1. Назначение"),
    ("p", "Сервис позволяет клиенту заказать перевыпуск карты в мобильном приложении без визита в отделение."),
    ("p", "Перевыпуск доступен для дебетовых и кредитных карт, кроме корпоративных."),
    ("h", "2. Сценарий заказа"),
    ("p", "1. Клиент выбирает карту и причину перевыпуска: утеря, повреждение или смена фамилии."),
    ("p", "2. Система показывает стоимость перевыпуска по тарифу карты до подтверждения."),
    ("p", "3. Клиент подтверждает заказ кодом из СМС; после трёх неверных кодов заказ отменяется."),
    ("h", "3. Доставка"),
    ("p", "1) Курьер доставляет карту в течение пяти рабочих дней после выпуска."),
    ("p", "2) Самовывоз возможен в любом отделении города, указанного в заказе."),
    ("p", "а) При утере старая карта блокируется сразу после подтверждения заказа."),
    ("p", "б) При повреждении старая карта действует до активации новой."),
    ("h", "4. Уведомления"),
    ("p", "Клиент получает уведомление о каждом статусе заказа: принят, выпущен, передан курьеру, вручён."),
    ("p", "Если доставка не состоялась дважды, заказ переводится в самовывоз автоматически."),
    ("h", "5. Нефункциональные требования"),
    ("p", "Экран заказа открывается не дольше двух секунд при нагрузке до 300 запросов в секунду."),
    ("p", "Журнал заказов хранится не менее пяти лет и недоступен для изменения сотрудниками отделений."),
]
FILLER = ("Поле заполняется автоматически из профиля клиента и может быть изменено до подтверждения заказа. "
          "Изменение фиксируется в журнале с указанием времени и канала.")


def make_two_col_running(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph
    _fonts()
    w, h = A4
    gap, margin = 20, 56
    colw = (w - 2 * margin - gap) / 2

    def running(canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 8)
        canvas.drawString(margin, h - 34, "АО «Учебный банк» · Для служебного пользования")
        canvas.drawRightString(w - margin, h - 34, "ТЗ «Перевыпуск карты», ред. 3")
        canvas.drawCentredString(w / 2, 30, f"Страница {doc.page} из 3")
        canvas.restoreState()

    frames = [Frame(margin, margin, colw, h - 2 * margin, id="l"),
              Frame(margin + colw + gap, margin, colw, h - 2 * margin, id="r")]
    doc = BaseDocTemplate(str(path), pagesize=A4, title="Перевыпуск карты",
                          pageTemplates=[PageTemplate(id="two", frames=frames, onPage=running)])
    hs = ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=12, leading=15, spaceBefore=8, spaceAfter=4)
    ps = ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=13, spaceAfter=5)
    story = []
    for kind, text in TWO_COL:
        story.append(Paragraph(text, hs if kind == "h" else ps))
        if kind == "p":
            for _ in range(3):
                story.append(Paragraph(FILLER, ps))
    doc.build(story)
    # куда попала каждая фраза — по самому PDF (страница), раздел — по заголовку выше
    import pymupdf
    pdf = pymupdf.open(str(path))
    pages = len(pdf)
    keep, sec = [], ""
    for kind, text in TWO_COL:
        if kind == "h":
            sec = text
            continue
        probe = text[:40]
        pg = next((i + 1 for i, p in enumerate(pdf) if probe in " ".join(p.get_text().split())), None)
        keep.append((text, sec, pg))
    pdf.close()
    assert pages == 3, pages
    _truth(path.name, keep=keep, absent=["Для служебного пользования", "Страница 1 из 3", "Страница 2 из 3",
                                          "ред. 3"])


# --------------------------------------------------------------------------- PDF: таблица на несколько страниц
TARIFFS = [(f"Причина {i:02d}", f"{'Утеря' if i % 3 == 0 else 'Повреждение' if i % 3 == 1 else 'Смена данных'}",
            f"{(i % 5 + 1) * 500} ₸",
            f"Карта перевыпускается за {i % 7 + 3} рабочих дней; условие {i:02d} действует для всех тарифов, "
            f"кроме премиальных пакетов с бесплатным обслуживанием")
           for i in range(1, 61)]


def make_long_table(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle
    _fonts()
    hs = ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=13, leading=16, spaceAfter=8)
    ps = ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=13, spaceAfter=6)
    cs = ParagraphStyle("c", fontName="DejaVu", fontSize=9, leading=11)
    rows = [["Код", "Причина", "Стоимость", "Условие"]] + [list(r) for r in TARIFFS]
    t = LongTable([[Paragraph(c, cs) for c in r] for r in rows], colWidths=[60, 80, 60, 290], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph("Тарифы перевыпуска", hs),
             Paragraph("Стоимость перевыпуска зависит от причины; таблица действует с первого числа месяца.", ps),
             t, Paragraph("Итоги", hs),
             Paragraph("Стоимость списывается со счёта карты в день выпуска новой карты.", ps)]
    SimpleDocTemplate(str(path), pagesize=A4, title="Тарифы перевыпуска").build(story)
    import pymupdf
    pdf = pymupdf.open(str(path))
    assert len(pdf) >= 3, len(pdf)
    keep = []
    for code, why, cost, cond in TARIFFS[::7] + [TARIFFS[-1]]:
        pg = next(i + 1 for i, p in enumerate(pdf) if f"условие {code[-2:]} " in " ".join(p.get_text().split()))
        # «Тарифы перевыпуска» — заголовок-название документа (как в свойствах PDF): из раздела вырезается
        keep.append((f"{code} | {why} | {cost} |", "", pg))
        keep.append((cond, "", pg))
    keep.append(("Стоимость списывается со счёта карты в день выпуска новой карты.", "Итоги", len(pdf)))
    pdf.close()
    _truth(path.name, keep=keep)


# --------------------------------------------------------------------------- PDF: типографика
TYPO = [
    ("h", "Профиль клиента"),
    ("p", "Сервис проверяет ﬁнальный статус заявки и показывает ﬂаг «Заказ оплачен» в профиле."),
    ("p", "Поле \"Причина\" обязательно; значение по умолчанию — «Утеря»."),
    ("p", "Стоимость перевыпуска — 1 500 ₸, срок — 5 рабочих дней."),
    ("p", "Клиент ещё раз подтверждает адрес доставки, если он изменён за последние 30 дней."),
    ("p", "Оператор контакт-центра не может от­менить заказ после пере­дачи курьеру."),
    ("p", "Эﬀективная дата блокировки — дата подтверждения заказа, а не дата выпуска."),
]


def make_typo(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Типографика")
    w, h = A4
    y = h - 72
    for kind, text in TYPO:
        c.setFont("DejaVu-Bold" if kind == "h" else "DejaVu", 13 if kind == "h" else 10)
        c.drawString(56, y, text)
        y -= 26 if kind == "h" else 18
    c.save()
    plain = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "­": ""}
    keep = []
    for kind, text in TYPO[1:]:
        t = text
        for a, b in plain.items():
            t = t.replace(a, b)
        keep.append((t, "", 1))  # единственный заголовок наверху — название документа
    _truth(path.name, keep=keep, absent=["­", "ﬁ", "ﬂ", "ﬀ"])


# --------------------------------------------------------------------------- DOCX через pandoc
AUTONUM_MD = """---
title: Перевыпуск карты в приложении
---

# Общие положения

Документ описывает заказ перевыпуска карты в мобильном приложении.[^1]

# Функциональные требования

1. Заказ перевыпуска
    1. Клиент выбирает карту из списка активных карт.
    2. Клиент указывает причину перевыпуска из справочника.
        a. Для причины «утеря» старая карта блокируется сразу.
        b. Для причины «повреждение» старая карта действует до активации новой.
2. Оплата
    1. Стоимость списывается со счёта карты в день выпуска.
    2. При нехватке средств заказ ожидает пополнения не более трёх суток.

# Параметры

| Параметр | Значение | Примечание |
|----------|----------|------------|
| Срок выпуска | 5 рабочих дней | Без учёта доставки |
| Стоимость | 1 500 ₸ | Для премиальных карт бесплатно |
| Попыток кода | 3 | Затем заказ отменяется |

# Критерии приемки

1. Заказ с причиной «утеря» блокирует старую карту не позднее 10 секунд.
2. После трёх неверных кодов заказ отменяется, клиент видит причину отмены.

[^1]: Корпоративные карты в документ не входят и перевыпускаются через отделение.
"""

NOTES_MD = """---
title: Уведомления о перевыпуске
---

# Каналы

Уведомления отправляются в приложение и по СМС, если приложение не установлено.[^a]

Клиент может отключить СМС в [настройках профиля](https://example.org/profile), кроме кодов подтверждения.

# Тексты

Текст уведомления о выпуске содержит последние четыре цифры новой карты.[^b]

Текст уведомления о вручении содержит дату и адрес вручения.
"""


def _pandoc(md: str, out: Path, extra: list[str] = ()) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.md"
        src.write_text(md, encoding="utf-8")
        subprocess.run(["pandoc", str(src), "-o", str(out), *extra], check=True)


def _zip_edit(path: Path, edits: dict[str, callable]) -> None:
    """Переписать части DOCX (имя части → функция над её XML)."""
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    for name, fn in edits.items():
        parts[name] = fn(parts.get(name, b"").decode("utf-8")).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in parts.items():
            z.writestr(n, data)
    path.write_bytes(buf.getvalue())


def _add_header_footer(path: Path, head: str, foot: str) -> None:
    import docx
    d = docx.Document(str(path))
    sec = d.sections[0]
    sec.header.paragraphs[0].text = head
    sec.footer.paragraphs[0].text = foot
    d.save(str(path))


def make_autonum(path: Path, pdf: Path) -> None:
    _pandoc(AUTONUM_MD, path)
    _add_header_footer(path, "АО «Учебный банк» · ТЗ на перевыпуск", "Внутреннее · версия 3")
    keep = [
        ("Клиент выбирает карту из списка активных карт.", "Функциональные требования", None),
        ("Для причины «утеря» старая карта блокируется сразу.", "Функциональные требования", None),
        ("При нехватке средств заказ ожидает пополнения не более трёх суток.", "Функциональные требования", None),
        ("Срок выпуска | 5 рабочих дней | Без учёта доставки", "Параметры", None),
        ("Стоимость | 1 500 ₸ | Для премиальных карт бесплатно", "Параметры", None),
        ("Заказ с причиной «утеря» блокирует старую карту не позднее 10 секунд.", "Критерии приемки", None),
        ("Корпоративные карты в документ не входят и перевыпускаются через отделение.", "", None),
    ]
    _truth(path.name, keep=keep, absent=["ТЗ на перевыпуск", "версия 3"])
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(path)],
                       check=True, capture_output=True, timeout=180)
        shutil.copy(Path(tmp) / (path.stem + ".pdf"), pdf)
    _truth(pdf.name, keep=[(t, s, 1 if "Корпоративные" not in t else None) for t, s, _ in keep],
           absent=["ТЗ на перевыпуск", "версия 3"])


def make_notes(path: Path) -> None:
    md = NOTES_MD + ("\n[^a]: СМС отправляется только на номер, подтверждённый в отделении.\n"
                     "[^b]: Полный номер карты в уведомлениях не показывается никогда.\n")
    _pandoc(md, path)
    import docx
    d = docx.Document(str(path))
    target = next(p for p in d.paragraphs if p.text.startswith("Текст уведомления о вручении"))
    d.add_comment(target.runs, text="Уточнить формат адреса для самовывоза", author="Рецензент", initials="Р")
    d.save(str(path))
    _truth(path.name, keep=[
        ("Уведомления отправляются в приложение и по СМС, если приложение не установлено.", "Каналы", None),
        ("Клиент может отключить СМС в настройках профиля, кроме кодов подтверждения.", "Каналы", None),
        ("Текст уведомления о вручении содержит дату и адрес вручения.", "Тексты", None),
        ("СМС отправляется только на номер, подтверждённый в отделении.", "", None),
        ("Полный номер карты в уведомлениях не показывается никогда.", "", None),
    ], absent=["Уточнить формат адреса для самовывоза", "example.org"])


REV_MD = """---
title: Отмена заказа перевыпуска
---

# Отмена

Клиент может отменить заказ до передачи карты курьеру.

Оператор отменяет заказ по звонку клиента после проверки личности.

Срок возврата стоимости — STUB_DEL рабочих дней.

Отмена после выпуска карты не возвращает стоимость.

# Журнал

Каждая отмена записывается в журнал с причиной и каналом.

STUB_MOVE
"""


def make_revisions(path: Path) -> None:
    _pandoc(REV_MD, path)
    A = 'w:id="{id}" w:author="Рецензент" w:date="2026-11-20T10:00:00Z"'

    def run(t: str) -> str:
        return f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'

    def deleted(t: str) -> str:
        return f'<w:r><w:delText xml:space="preserve">{t}</w:delText></w:r>'

    def edit(xml: str) -> str:
        # «Срок возврата … — <del>десять</del><ins>три</ins> рабочих дней.»
        xml = re.sub(r'<w:r>(?:(?!<w:r>).)*?STUB_DEL(?:(?!</w:r>).)*</w:r>',
                     run("Срок возврата стоимости — ")
                     + f'<w:del {A.format(id=901)}>{deleted("десять")}</w:del>'
                     + f'<w:ins {A.format(id=902)}>{run("три")}</w:ins>'
                     + run(" рабочих дней."), xml, count=1, flags=re.S)
        # непринятая вставка целого абзаца и удаление целого абзаца
        xml = re.sub(r'(<w:p>(?:(?!<w:p>).)*?Оператор отменяет заказ)',
                     '<w:p>' + f'<w:ins {A.format(id=903)}>'
                     + run("Отмена доступна в приложении и в контакт-центре.") + '</w:ins></w:p>' + r'\1',
                     xml, count=1, flags=re.S)
        xml = re.sub(r'<w:r>((?:(?!<w:r>).)*?)<w:t xml:space="preserve">Отмена после выпуска карты не возвращает '
                     r'стоимость\.</w:t></w:r>',
                     f'<w:del {A.format(id=904)}>' + deleted("Отмена после выпуска карты не возвращает стоимость.")
                     + '</w:del>', xml, count=1, flags=re.S)
        xml = re.sub(r'<w:r>((?:(?!<w:r>).)*?)<w:t[^>]*>Отмена после выпуска карты не возвращает стоимость\.'
                     r'</w:t></w:r>',
                     f'<w:del {A.format(id=904)}>' + deleted("Отмена после выпуска карты не возвращает стоимость.")
                     + '</w:del>', xml, count=1, flags=re.S)
        # перенос абзаца: старое место (moveFrom) и новое (moveTo)
        moved = "Отмена фиксируется в журнале в течение одной минуты."
        xml = re.sub(r'(<w:p>(?:(?!<w:p>).)*?Клиент может отменить заказ)',
                     '<w:p>' + f'<w:moveFrom {A.format(id=905)}>'
                     + f'<w:r><w:t xml:space="preserve">{moved}</w:t></w:r></w:moveFrom></w:p>' + r'\1',
                     xml, count=1, flags=re.S)
        xml = re.sub(r'<w:r>(?:(?!<w:r>).)*?STUB_MOVE(?:(?!</w:r>).)*</w:r>',
                     f'<w:moveTo {A.format(id=906)}>' + run(moved) + '</w:moveTo>', xml, count=1, flags=re.S)
        assert "STUB_" not in xml, "заготовка не заменена"
        return xml

    _zip_edit(path, {"word/document.xml": edit})
    _truth(path.name, keep=[
        ("Клиент может отменить заказ до передачи карты курьеру.", "Отмена", None),
        ("Отмена доступна в приложении и в контакт-центре.", "Отмена", None),
        ("Срок возврата стоимости — три рабочих дней.", "Отмена", None),
        ("Отмена фиксируется в журнале в течение одной минуты.", "Журнал", None),
    ], absent=["десять", "Отмена после выпуска карты не возвращает стоимость."],
        warn=["непринятые исправления"])


CTRL_MD = """---
title: Заявка на перевыпуск
---

# Реквизиты заявки

Номер заявки: STUB_SDT1

Канал подачи: STUB_SDT2

Дата документа: STUB_FLD

# Правила

Заявка без номера не принимается в обработку.
"""


def make_controls(path: Path) -> None:
    _pandoc(CTRL_MD, path)

    def sdt_run(tag: str, text: str) -> str:
        return (f'<w:sdt><w:sdtPr><w:alias w:val="{tag}"/><w:tag w:val="{tag}"/></w:sdtPr><w:sdtContent>'
                f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:sdtContent></w:sdt>')

    def edit(xml: str) -> str:
        xml = re.sub(r'<w:r>(?:(?!<w:r>).)*?STUB_SDT1(?:(?!</w:r>).)*</w:r>',
                     '<w:r><w:t xml:space="preserve">Номер заявки: </w:t></w:r>' + sdt_run("num", "RX-2048"),
                     xml, count=1, flags=re.S)
        xml = re.sub(r'<w:r>(?:(?!<w:r>).)*?STUB_SDT2(?:(?!</w:r>).)*</w:r>',
                     '<w:r><w:t xml:space="preserve">Канал подачи: </w:t></w:r>' + sdt_run("chan", "мобильное приложение"),
                     xml, count=1, flags=re.S)
        xml = re.sub(r'<w:r>(?:(?!<w:r>).)*?STUB_FLD(?:(?!</w:r>).)*</w:r>',
                     '<w:r><w:t xml:space="preserve">Дата документа: </w:t></w:r>'
                     '<w:fldSimple w:instr=" DATE \\@ &quot;dd.MM.yyyy&quot; "><w:r><w:t>20.11.2026</w:t></w:r>'
                     '</w:fldSimple>', xml, count=1, flags=re.S)
        # абзац целиком в элементе управления (блочный w:sdt)
        block = ('<w:sdt><w:sdtPr><w:tag w:val="rule"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t xml:space="preserve">'
                 'Заявка с истёкшим сроком действия карты обрабатывается вне очереди.</w:t></w:r></w:p>'
                 '</w:sdtContent></w:sdt>')
        xml = xml.replace("<w:sectPr", block + "<w:sectPr", 1)
        assert "STUB_" not in xml
        return xml

    _zip_edit(path, {"word/document.xml": edit})
    _truth(path.name, keep=[
        ("Номер заявки: RX-2048", "Реквизиты заявки", None),
        ("Канал подачи: мобильное приложение", "Реквизиты заявки", None),
        ("Дата документа: 20.11.2026", "Реквизиты заявки", None),
        ("Заявка без номера не принимается в обработку.", "Правила", None),
        ("Заявка с истёкшим сроком действия карты обрабатывается вне очереди.", "Правила", None),
    ])


# --------------------------------------------------------------------------- HTML: Confluence с макросами
CONFLUENCE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Перевыпуск карты : Требования</title></head>
<body class="theme-default aui-theme-default">
<div id="page"><div id="main" class="aui-page-panel">
<div id="main-header"><div id="breadcrumb-section"><ol id="breadcrumbs">
<li><a href="index.html">Карточные продукты</a></li><li><a href="r.html">Требования</a></li></ol></div>
<h1 id="title-heading" class="pagetitle"><span id="title-text">Перевыпуск карты : Требования</span></h1></div>
<div id="content" class="view"><div class="page-metadata">Создано Аналитик, последнее изменение 20.11.2026</div>
<div id="main-content" class="wiki-content group">
<p><span class="status-macro aui-lozenge aui-lozenge-current">В РАБОТЕ</span> Статус документа.</p>
<h2 id="id-req-1">1. Сценарий</h2>
<ol><li>Клиент открывает карту и нажимает «Перевыпустить».</li>
<li>Клиент выбирает причину; для причины «утеря» карта блокируется сразу.</li></ol>
<div class="expand-container"><div class="expand-control"><span class="expand-control-text">Подробности проверки</span></div>
<div class="expand-content expand-hidden"><p>Повторный заказ по той же карте запрещён, пока предыдущий не завершён.</p></div></div>
<div class="confluence-information-macro confluence-information-macro-warning"><span class="aui-icon"></span>
<div class="confluence-information-macro-body"><p>Перевыпуск корпоративных карт в приложении не поддерживается.</p></div></div>
<h2 id="id-req-2">2. Задачи релиза</h2>
<ul class="inline-task-list"><li class="checked">Согласовать тарифы перевыпуска с казначейством</li>
<li>Подготовить тексты уведомлений для курьерской доставки</li></ul>
<h2 id="id-req-3">3. Параметры</h2>
<div class="table-wrap"><table class="confluenceTable"><tbody>
<tr><th class="confluenceTh">Параметр</th><th class="confluenceTh">Значение</th><th class="confluenceTh">Комментарий</th></tr>
<tr><th class="confluenceTh">Срок выпуска</th><td class="confluenceTd">5 рабочих дней</td><td class="confluenceTd" rowspan="2">Для всех типов карт</td></tr>
<tr><th class="confluenceTh">Срок доставки</th><td class="confluenceTd">до 3 дней</td></tr>
<tr><th class="confluenceTh">Стоимость</th><td class="confluenceTd" colspan="2">по тарифу карты</td></tr>
</tbody></table></div>
<div class="code panel pdl"><div class="codeContent panelContent pdl"><pre class="syntaxhighlighter-pre">POST /cards/{id}/reissue
{"reason": "LOST"}</pre></div></div>
</div></div></div>
<div id="footer"><section class="footer-body"><p>Документ сгенерирован Confluence</p></section></div>
</div></body></html>
"""


def make_confluence(path: Path) -> None:
    path.write_text(CONFLUENCE, encoding="utf-8")
    _truth(path.name, keep=[
        ("Клиент открывает карту и нажимает «Перевыпустить».", "Сценарий", None),
        ("Клиент выбирает причину; для причины «утеря» карта блокируется сразу.", "Сценарий", None),
        ("Повторный заказ по той же карте запрещён, пока предыдущий не завершён.", "Сценарий", None),
        ("Перевыпуск корпоративных карт в приложении не поддерживается.", "Сценарий", None),
        ("Подготовить тексты уведомлений для курьерской доставки", "Задачи релиза", None),
        ("Срок выпуска | 5 рабочих дней | Для всех типов карт", "Параметры", None),
        ("Стоимость | по тарифу карты", "Параметры", None),
        ("POST /cards/{id}/reissue", "Параметры", None),
    ], absent=["Документ сгенерирован Confluence", "Создано Аналитик", "Карточные продукты"])


# --------------------------------------------------------------------------- TXT в разных кодировках
TXT = """ПЕРЕВЫПУСК КАРТЫ

1. Назначение
Клиент заказывает перевыпуск карты в приложении.

2. Требования
2.1. Стоимость перевыпуска показывается до подтверждения заказа.
2.2. Ещё одна попытка ввода кода даётся через 60 секунд.
2.3. Карта с причиной «утеря» блокируется сразу.

3. Параметры
Срок выпуска\t5 рабочих дней
Стоимость\t1 500 ₸
"""


def make_txt(cp1251: Path, utf16: Path, utf16be: Path) -> None:
    body = TXT.replace("₸", "тг")  # знака тенге нет в Windows-1251
    cp1251.write_bytes(body.replace("\n", "\r\n").encode("cp1251"))
    utf16.write_bytes(b"\xff\xfe" + TXT.replace("\n", "\r\n").encode("utf-16-le"))
    utf16be.write_bytes(TXT.encode("utf-16-be"))
    for p, b in ((cp1251, body), (utf16, TXT), (utf16be, TXT)):
        cost = "1 500 тг" if b is body else "1 500 ₸"
        _truth(p.name, keep=[
            ("Клиент заказывает перевыпуск карты в приложении.", "", None),
            ("2.2. Ещё одна попытка ввода кода даётся через 60 секунд.", "", None),
            ("2.3. Карта с причиной «утеря» блокируется сразу.", "", None),
            (f"Стоимость | {cost}", "", None),
        ], absent=["�", "\x00", "\r"])


# --------------------------------------------------------------------------- Markdown с трудными таблицами
MD_TABLES = """# Перевыпуск карты: поля API

## Запрос

| Поле | Тип | Описание |
|:-----|:---:|---------:|
| reason | enum | `LOST \\| DAMAGED \\| RENAMED` — причина |
| delivery | object | Адрес доставки<br>или код отделения |
| comment | string | Не более 200 знаков; символ \\| запрещён |

Поле | Обязательность
--- | ---
cardId | да
reason | да

## Ответ

Ответ содержит номер заказа и плановую дату выпуска.[^1]

1) Статус «принят» возвращается сразу.
2) Статус «выпущен» приходит событием.

[^1]: Плановая дата считается в рабочих днях банка.
"""


def make_md_tables(path: Path) -> None:
    path.write_text(MD_TABLES, encoding="utf-8")
    _truth(path.name, keep=[
        ("reason | enum | LOST | DAMAGED | RENAMED — причина", "Запрос", None),
        ("Адрес доставки", "Запрос", None),
        ("Не более 200 знаков; символ | запрещён", "Запрос", None),
        ("cardId | да", "Запрос", None),
        ("Ответ содержит номер заказа и плановую дату выпуска.", "Ответ", None),
        ("Статус «выпущен» приходит событием.", "Ответ", None),
        ("Плановая дата считается в рабочих днях банка.", "Ответ", None),
    ], absent=["<br>", "\\|"])


def main() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    make_two_col_running(HERE / "pdf_two_col_running.pdf")
    make_long_table(HERE / "pdf_long_table.pdf")
    make_typo(HERE / "pdf_typo.pdf")
    make_autonum(HERE / "docx_autonum.docx", HERE / "pdf_from_word.pdf")
    make_notes(HERE / "docx_notes.docx")
    make_revisions(HERE / "docx_revisions.docx")
    make_controls(HERE / "docx_controls.docx")
    make_confluence(HERE / "confluence_macros.html")
    make_txt(HERE / "txt_cp1251.txt", HERE / "txt_utf16.txt", HERE / "txt_utf16be.txt")
    make_md_tables(HERE / "md_tables.md")
    (HERE / "truth.json").write_text(json.dumps(TRUTH, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"файлов: {len(TRUTH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
