"""Резервный читатель PDF: кириллица, фрагменты и их прямоугольники, разделы, таблицы, списки,
страница-скан, неполное чтение, пароль и официальный документ хакатона, сконвертированный в PDF."""

from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from bcc_review import contracts  # noqa: E402
from bcc_review.runtime.fallback.pdf_reader import read_pdf  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "bcc_requirements.md"
CSS = "table {border-collapse: collapse;} th, td {border: 1px solid black; padding: 2px 4px;}"
JOINERS = set("\n |")

SAMPLE_PAGE_1 = """
<h1>Уведомление о расходах по карте</h1>
<p>Комплект требований для проверки чтения PDF. Текст на русском языке с суммой 50 000 ₸
и достаточно длинной строкой, чтобы она переносилась на следующую строку страницы.</p>
<h2>Функциональные требования</h2>
<ul>
<li>Ф-1. Держатель активной карты задаёт целый порог от 1 000 до 1 000 000 ₸.</li>
<li>Ф-2. Месяц определяется по дате совершения покупки в Алматы.</li>
</ul>
<h3>Общие параметры</h3>
<table>
<tr><th>Поле</th><th>Значение</th></tr>
<tr><td>Продукт</td><td>Мобильный банк</td></tr>
<tr><td>Тип работы</td><td>Новый функционал</td></tr>
</table>
<p>Текст после таблицы.</p>
<pre>curl -G "$BASE/alerts/saveLimit"</pre>
"""

SAMPLE_PAGE_3 = """
<h2>Нефункциональные требования</h2>
<p>Сервис передаёт push на отправку в течение минуты после получения события.</p>
<ol><li>Проверить пользовательскую сессию.</li><li>Проверить принадлежность карты клиенту.</li></ol>
"""


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).split())


def _html_page(doc, body: str):
    page = doc.new_page()
    page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 800), body, css=CSS)
    return page


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    doc = pymupdf.open()
    _html_page(doc, SAMPLE_PAGE_1)
    scan = doc.new_page()  # страница-скан: только изображение
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
    pix.clear_with(180)
    scan.insert_image(pymupdf.Rect(100, 100, 400, 400), pixmap=pix)
    rotated = _html_page(doc, SAMPLE_PAGE_3)
    rotated.set_rotation(90)
    doc.save(path)
    doc.close()
    return path, read_pdf(path)


def _by_text(doc, needle: str) -> dict:
    hits = [b for b in doc["blocks"] if needle in b["text"]]
    assert hits, f"нет блока с {needle!r}"
    return hits[0]


# --------------------------------------------------------------------------- документ
def test_document_contract_and_identity(sample):
    path, doc = sample
    contracts.validate(doc, "Document")
    assert doc["id"] == contracts.sha256_bytes(path.read_bytes())
    assert doc["format"] == "pdf"
    assert doc["source_name"] == "sample.pdf"
    assert doc["title"] == "Уведомление о расходах по карте"
    ids = [b["id"] for b in doc["blocks"]]
    assert len(ids) == len(set(ids))
    assert ids == [f"b{i:04d}" for i in range(1, len(ids) + 1)]


def test_cyrillic_round_trip_and_kinds(sample):
    _, doc = sample
    texts = [b["text"] for b in doc["blocks"]]
    assert "Уведомление о расходах по карте" in texts
    assert _by_text(doc, "Уведомление о расходах")["kind"] == "heading"
    assert _by_text(doc, "Функциональные требования")["kind"] == "heading"
    para = _by_text(doc, "Комплект требований")
    assert para["kind"] == "paragraph"
    assert "50 000 ₸" in _norm(para["text"])

    items = [b for b in doc["blocks"] if b["kind"] == "list_item"]
    assert [b["text"] for b in items[:2]] == [
        "Ф-1. Держатель активной карты задаёт целый порог от 1 000 до 1 000 000 ₸.",
        "Ф-2. Месяц определяется по дате совершения покупки в Алматы.",
    ]
    assert all("•" not in b["text"] for b in items)
    ordered = [b["text"] for b in items if b["text"].startswith(("1.", "2."))]
    assert ordered == ["1. Проверить пользовательскую сессию.", "2. Проверить принадлежность карты клиенту."]

    header = next(b for b in doc["blocks"] if b["kind"] == "table_header")
    assert header["text"] == "Поле | Значение"
    rows = [b for b in doc["blocks"] if b["kind"] == "table_row"]
    assert [r["text"] for r in rows] == ["Продукт | Мобильный банк", "Тип работы | Новый функционал"]
    assert all(r["loc"]["columns"] == ["Поле", "Значение"] for r in rows)
    # область таблицы не дублируется обычными абзацами
    assert not [b for b in doc["blocks"] if b["kind"] == "paragraph" and "Продукт" in b["text"]]

    code = _by_text(doc, "saveLimit")
    assert code["kind"] == "code"
    assert code["text"] == 'curl -G "$BASE/alerts/saveLimit"'


def test_sections_follow_heading_levels(sample):
    _, doc = sample
    item = _by_text(doc, "Ф-1.")
    assert item["section"] == ["Уведомление о расходах по карте", "Функциональные требования"]
    row = _by_text(doc, "Продукт")
    assert row["section"] == ["Уведомление о расходах по карте", "Функциональные требования", "Общие параметры"]
    nfr = _by_text(doc, "Сервис передаёт push")
    assert nfr["section"] == ["Уведомление о расходах по карте", "Нефункциональные требования"]
    levels = {b["text"]: b["loc"]["level"] for b in doc["blocks"] if b["kind"] == "heading"}
    assert levels["Уведомление о расходах по карте"] < levels["Функциональные требования"] < levels["Общие параметры"]


# --------------------------------------------------------------------------- координаты
def test_fragments_cover_every_source_character(sample):
    _, doc = sample
    for b in doc["blocks"]:
        text = b["text"]
        frags = b["loc"]["fragments"]
        covered = [False] * len(text)
        prev_end = 0
        for f in frags:
            assert 0 <= f["start"] < f["end"] <= len(text), (b["id"], f)
            assert f["start"] >= prev_end, f"фрагменты {b['id']} пересекаются"
            prev_end = f["end"]
            x0, y0, x1, y1 = f["rect"]
            assert x0 <= x1 and y0 <= y1
            for k in range(f["start"], f["end"]):
                covered[k] = True
        gaps = {text[k] for k in range(len(text)) if not covered[k]}
        assert gaps <= JOINERS, (b["id"], gaps)


def test_fragment_rect_contains_its_text(sample):
    path, doc = sample
    pdf = pymupdf.open(path)
    try:
        checked = 0
        for b in doc["blocks"]:
            page = pdf[b["loc"]["page"] - 1]
            for f in b["loc"]["fragments"]:
                r = pymupdf.Rect(f["rect"])
                # середина строки: соседние строки не задеваются краями своих глифов
                probe = pymupdf.Rect(r.x0 + 0.5, r.y0 + 0.3 * r.height, r.x1 - 0.5, r.y1 - 0.3 * r.height)
                assert _norm(page.get_textbox(probe)) == _norm(b["text"][f["start"]:f["end"]]), (b["id"], f)
                checked += 1
        assert checked >= 15
    finally:
        pdf.close()


def test_pages_are_one_based_and_rotation_keeps_unrotated_space(sample):
    path, doc = sample
    pages = {b["loc"]["page"] for b in doc["blocks"]}
    assert pages == {1, 3}
    nfr = _by_text(doc, "Нефункциональные требования")
    pdf = pymupdf.open(path)
    try:
        page = pdf[2]
        assert page.rotation == 90
        unrotated = pymupdf.Rect(0, 0, page.cropbox.width, page.cropbox.height)
        assert unrotated.contains(pymupdf.Rect(nfr["loc"]["fragments"][0]["rect"]))
    finally:
        pdf.close()


def test_image_only_page_reports_ocr_required(sample):
    _, doc = sample
    ocr = [w for w in doc["warnings"] if w["code"] == "ocr_required"]
    assert [w["page"] for w in ocr] == [2]
    assert "ocr_required" in contracts.PARTIAL_READ_CODES
    assert not [b for b in doc["blocks"] if b["loc"]["page"] == 2]


# --------------------------------------------------------------------------- неполное чтение и защита
def test_font_without_unicode_map_is_partial_read(tmp_path):
    path = tmp_path / "nounicode.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="F0", fontbuffer=pymupdf.Font("helv").buffer)
    page.insert_text((72, 100), "Держатель карты задаёт порог уведомления", fontname="F0", fontsize=12)
    for xref, *_ in page.get_fonts():
        pdf.xref_set_key(xref, "ToUnicode", "null")
    pdf.save(path)
    pdf.close()
    doc = read_pdf(path)
    contracts.validate(doc, "Document")
    assert [(w["code"], w["page"]) for w in doc["warnings"]] == [("partial_read", 1)]


def test_password_protected_pdf_raises(tmp_path):
    path = tmp_path / "locked.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "секрет")
    pdf.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="user", owner_pw="owner")
    pdf.close()
    with pytest.raises(ValueError, match="паролем"):
        read_pdf(path)


def test_scan_with_page_number_stamp_reports_ocr_required(tmp_path):
    path = tmp_path / "scan.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32))
    pix.clear_with(230)
    page.insert_image(page.rect, pixmap=pix)
    page.insert_text((290, 830), "- 1 -", fontsize=9)
    pdf.save(path)
    pdf.close()
    doc = read_pdf(path)
    assert [(w["code"], w["page"]) for w in doc["warnings"]] == [("ocr_required", 1)]


def test_empty_page_is_reported_not_dropped(tmp_path):
    path = tmp_path / "blank.pdf"
    pdf = pymupdf.open()
    _html_page(pdf, "<p>Единственный абзац.</p>")
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    doc = read_pdf(path)
    assert [(w["code"], w["page"]) for w in doc["warnings"]] == [("empty_page", 2)]


def test_running_header_and_page_numbers_do_not_become_sections(tmp_path):
    path = tmp_path / "furniture.pdf"
    pdf = pymupdf.open()
    for n in range(1, 5):
        page = _html_page(pdf, f"<h2>Раздел {n}</h2><p>Текст раздела номер {n}.</p>")
        page.insert_htmlbox(pymupdf.Rect(50, 10, 545, 40), "<b>ТЗ: уведомление о расходах</b>")
        page.insert_text((280, 825), f"Страница {n} из 4", fontsize=9)
    pdf.save(path)
    pdf.close()
    doc = read_pdf(path)
    furniture = [b for b in doc["blocks"] if b["loc"].get("furniture")]
    assert len(furniture) == 8 and all(b["kind"] == "other" for b in furniture)
    para = _by_text(doc, "Текст раздела номер 3.")
    assert para["section"] == ["Раздел 3"]


def test_table_continued_on_next_page_keeps_header(tmp_path):
    path = tmp_path / "long_table.pdf"
    rows = "".join(f"<tr><td>Параметр {i}</td><td>Значение {i}</td></tr>" for i in range(1, 61))
    _story_pdf(path, f"<h2>Параметры запроса</h2><table><tr><th>Поле</th><th>Описание</th></tr>{rows}</table>")
    doc = read_pdf(path)
    contracts.validate(doc, "Document")
    headers = [b for b in doc["blocks"] if b["kind"] == "table_header"]
    rows_ = [b for b in doc["blocks"] if b["kind"] == "table_row"]
    assert [h["text"] for h in headers] == ["Поле | Описание"]
    assert {r["loc"]["page"] for r in rows_} == {1, 2}
    assert [r["text"] for r in rows_] == [f"Параметр {i} | Значение {i}" for i in range(1, 61)]
    assert all(r["loc"]["columns"] == ["Поле", "Описание"] and r["loc"]["table"] == 1 for r in rows_)
    assert [r["loc"]["row"] for r in rows_] == list(range(1, 61))
    assert all(r["section"] == ["Параметры запроса"] for r in rows_)


# --------------------------------------------------------------------------- официальный документ
def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def _markdown_to_html(md: str) -> str:
    """Минимальная конвертация фикстуры: заголовки, списки, таблицы, код, абзацы."""
    out: list[str] = []
    mode = None  # "ul" | "ol" | "table" | "pre"

    def close() -> None:
        nonlocal mode
        if mode in ("ul", "ol", "table"):
            out.append(f"</{mode}>")
        mode = None

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            if mode == "pre":
                out.append("</pre>")
                mode = None
            else:
                close()
                out.append("<pre>")
                mode = "pre"
            continue
        if mode == "pre":
            out.append(html.escape(line, quote=False) + "\n")
            continue
        if s.startswith("|"):
            if re.fullmatch(r"[|:\-\s]+", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            tag = "td"
            if mode != "table":
                close()
                out.append("<table>")
                mode = "table"
                tag = "th"
            out.append("<tr>" + "".join(f"<{tag}>{_inline(c) or '&nbsp;'}</{tag}>" for c in cells) + "</tr>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
            continue
        m = re.match(r"^([*-]|\d+\.)\s+(.*)$", s)
        if m and s != "---":
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if mode != kind:
                close()
                out.append(f"<{kind}>")
                mode = kind
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        close()
        if s and s != "---":
            out.append(f"<p>{_inline(s)}</p>")
    close()
    return "\n".join(out)


def _story_pdf(path: Path, body: str) -> None:
    story = pymupdf.Story(html=body, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (40, 40, -40, -40)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()


def test_official_fixture_converted_to_pdf(tmp_path):
    path = tmp_path / "bcc_requirements.pdf"
    _story_pdf(path, _markdown_to_html(FIXTURE.read_text(encoding="utf-8")))
    doc = read_pdf(path)
    contracts.validate(doc, "Document")
    assert doc["title"] == "Уведомление о расходах по карте"
    assert max(b["loc"]["page"] for b in doc["blocks"]) >= 2
    assert not [w for w in doc["warnings"] if w["code"] in contracts.PARTIAL_READ_CODES]

    texts = [_norm(b["text"]) for b in doc["blocks"]]
    for phrase in ("Ф-3", "максимум один такой push", "saveLimit"):
        assert any(phrase in t for t in texts), phrase

    f3 = next(b for b in doc["blocks"] if "Ф-3" in b["text"])
    assert f3["kind"] == "list_item"
    assert "Функциональные требования" in f3["section"]
    headers = [b for b in doc["blocks"] if b["kind"] == "table_header"]
    assert any(b["loc"]["columns"][:2] == ["Поле", "Значение"] for b in headers)
    assert any(b["kind"] == "code" and '"result":"OK"' in b["text"] for b in doc["blocks"])
    for b in doc["blocks"]:
        for f in b["loc"]["fragments"]:
            assert 0 <= f["start"] < f["end"] <= len(b["text"])
