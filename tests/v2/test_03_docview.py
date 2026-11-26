"""№03: документ с номерами строк (docview) — MD/TXT/PDF/DOCX, корпус без потерь."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MD = ROOT / "release/input/requirements.md"
OFFICIAL_PDF = ROOT / "release/input/requirements.pdf"
CORPUS = ROOT / "evaluation/dev/corpus/cases"
BASES = ["autopay", "cardblock", "cashback", "transfer_limit"]


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


needs_pdf = pytest.mark.skipif(not _has("pymupdf") and not _has("fitz"), reason="нет pymupdf")
needs_docx = pytest.mark.skipif(not _has("docx"), reason="нет python-docx")


@pytest.fixture(scope="module")
def md():
    return dv.load(OFFICIAL_MD)


def test_md_line_numbers_match_file(md):
    raw = OFFICIAL_MD.read_text(encoding="utf-8").splitlines()
    assert len(md["lines"]) == len(raw) == 198
    assert [ln["n"] for ln in md["lines"]] == list(range(1, 199))
    assert all(ln["src_line"] == ln["n"] and ln["page"] is None for ln in md["lines"])
    # пустые строки сохранены
    for i, s in enumerate(raw, 1):
        if not s.strip():
            assert md["lines"][i - 1]["text"] == ""


def test_md_visible_text_without_markup(md):
    t37 = dv.line(md, 37)["text"]
    assert t37.startswith("Ф-1. Держатель активной карты KZT")
    assert "**" not in t37 and not t37.startswith("*")
    assert dv.line(md, 8)["text"] == "Часть A. Новый функционал"        # без «## »
    assert dv.line(md, 108)["text"] == "Request URL | Dev: /alerts/saveLimit . Prod: —"   # без обратных кавычек
    assert dv.line(md, 64)["text"] == ("Покупка 31 января в 23:58 на 4 000 ₸ | Провести 1 февраля в 00:03 по Алматы"
                                       " | Февральский счётчик вырос на 4 000 ₸")
    assert dv.line(md, 13)["text"] == ""          # разделитель таблицы
    assert dv.line(md, 166)["text"] == ""         # ограждение блока кода
    assert dv.line(md, 167)["text"] == '{"result":"OK","amount":"50000","enabled":"1"}'
    assert dv.line(md, 121)["text"] == "5. При отклонении суммы вернуть прежнее состояние и результат ERROR."
    full = "\n".join(ln["text"] for ln in md["lines"])
    assert "**" not in full and "`" not in full and "\n#" not in full


def test_md_meta_and_sections(md):
    assert md["title"] == "Уведомление о расходах по карте"
    assert md["format"] == "md" and md["file"] == "requirements.md" and md["pages"] is None
    assert re.fullmatch(r"[0-9a-f]{64}", md["sha256"])
    assert md["warnings"] == []
    assert dv.line(md, 38)["section"] == "Часть A. Новый функционал › Требования к изменениям › Функциональные требования"
    assert dv.line(md, 103)["section"] == "Часть B. REST API › Общие параметры"
    assert dv.line(md, 23)["section"].endswith("Цели")
    assert dv.line(md, 38)["block_id"]
    assert dv.summary(md)["lines"] == 198


def test_numbered_format(md):
    out = dv.numbered(md, 36, 38).splitlines()
    assert out[0] == "L036| Функциональные требования"
    assert out[2].startswith("L038| Ф-2. Месяц определяется")
    assert dv.numbered(md).count("\n") == 197
    assert dv.place(md, 38) == "строка 38" and dv.place(md, 38, 40) == "строки 38–40"


def test_txt_and_fallback(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("Заголовок\n\nПервая строка текста.\n  Вторая строка.\n\n1. пункт\n", encoding="utf-8")
    v = dv.load(p)
    assert v["format"] == "txt" and len(v["lines"]) == 6
    assert v["lines"][2]["text"] == "Первая строка текста."
    assert v["lines"][3]["text"].strip() == "Вторая строка."
    assert v["lines"][1]["text"] == ""
    # запасной разбор Markdown без читателя v1
    assert dv._strip_md("* **Ф-1.** Текст `code`") == "Ф-1. Текст code"
    assert dv._strip_md("| a | b |") == "a | b"
    assert dv._strip_md("| :--- | :--- |") == ""
    assert dv._strip_md("### Заголовок") == "Заголовок"


def test_from_text():
    v = dv.from_text("# Док\n\n* **R-1.** Первое\n")
    assert v["title"] == "Док" and v["lines"][2]["text"] == "R-1. Первое"


def test_unsupported_format(tmp_path):
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"x")
    with pytest.raises(ValueError):
        dv.load(p)


@needs_pdf
def test_pdf_view_pages_and_numbering(md):
    v = dv.load(OFFICIAL_PDF)
    assert v["format"] == "pdf" and v["pages"] == 6 and len(v["lines"]) == 128
    assert v["title"] == md["title"]
    assert all(isinstance(ln["page"], int) and 1 <= ln["page"] <= 6 for ln in v["lines"])
    pages = [ln["page"] for ln in v["lines"]]
    assert pages == sorted(pages)
    # нумерация совпадает с фикстурой нарезки PDF (tests/v2/fixtures/official_pdf): «Цели» — L015
    assert dv.line(v, 15)["text"].startswith("Дать клиенту возможность")
    assert dv.numbered(v, 25, 25).startswith("L025| [с.2] Ф-2. Месяц определяется")
    assert not dv.line(v, 24)["text"].startswith("•")
    assert dv.place(v, 25) == "с. 2, строка 25"


@needs_pdf
def test_pdf_has_every_md_line(md):
    """Каждая непустая строка MD находится в PDF (тот же документ) — чтение без потерь."""
    v = dv.load(OFFICIAL_PDF)
    missing = [ln["n"] for ln in dv.nonempty(md) if not Q.verify_quote(v, ln["text"])]
    # единственная известная потеря: строка блока кода обрезана в самом PDF (L130 «→ приложение.»)
    assert missing in ([], [130])


@pytest.mark.parametrize("case", BASES)
def test_corpus_md_reads(case):
    v = dv.load(CORPUS / f"{case}.base/source.md")
    raw = (CORPUS / f"{case}.base/source.md").read_text(encoding="utf-8").splitlines()
    assert len(v["lines"]) == len(raw)
    assert len(dv.nonempty(v)) >= 40


@needs_pdf
@needs_docx
@pytest.mark.parametrize("case", BASES)
def test_corpus_formats_without_loss(case):
    md = dv.load(CORPUS / f"{case}.base/source.md")
    pdf = dv.load(CORPUS / f"{case}.base/source.pdf")
    docx = dv.load(CORPUS / f"{case}.base/source.docx")
    n = len(dv.nonempty(md))
    assert md["title"] == pdf["title"] == docx["title"]
    assert pdf["pages"] and pdf["pages"] >= 1 and docx["format"] == "docx"
    for other in (pdf, docx):
        assert abs(len(dv.nonempty(other)) - n) <= max(3, n // 10)
        missing = [ln for ln in dv.nonempty(md) if not Q.verify_quote(other, ln["text"])]
        assert len(missing) <= max(2, n // 25), [m["text"][:80] for m in missing]
        # ключевые фразы: все ID требований и заголовки частей
        text = " ".join(ln["text"] for ln in other["lines"])
        ids = set(re.findall(r"\b[А-ЯA-Z]{1,4}-\d+\b", " ".join(ln["text"] for ln in md["lines"])))
        assert ids and all(i in text for i in ids)
        assert "Часть A" in text and "Часть B" in text


@pytest.mark.parametrize("ext", ["md", "pdf", "docx"])
def test_empty_document_warns_once(ext):
    p = CORPUS / f"edge.empty/source.{ext}"
    if ext == "pdf" and not (_has("pymupdf") or _has("fitz")) or ext == "docx" and not _has("docx"):
        pytest.skip("нет читателя")
    v = dv.load(p)
    assert dv.nonempty(v) == [] and len(v["warnings"]) == 1
