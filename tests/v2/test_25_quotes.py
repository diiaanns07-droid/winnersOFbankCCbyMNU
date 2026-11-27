"""№25: цитаты официального ТЗ сверяются в MD, PDF и DOCX и при типичных искажениях модели и копирования.

Каждая непустая строка ``release/input/requirements.md`` (не короче 15 знаков) берётся как цитата модели и портится
так, как это делают модели и буфер обмена: «ё» ↔ «е», «ёлочки» ↔ прямые и „лапки“, неразрывные пробелы, мягкие
переносы, лигатуры ﬁ/ﬂ, тире ↔ дефис, двойные пробелы, всё сразу. Цитата должна найтись во всех трёх форматах
(в MD — на своей строке, если фраза в документе одна), если в этом формате найдена исходная строка.
Отдельно — те же знаки внутри документа (зоопарк №25, ``pdf_typo.pdf``) и цитата без них.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "release/input/requirements"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _variants(t: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if re.search("[ёЁ]", t):
        out["ё→е"] = t.replace("ё", "е").replace("Ё", "Е")
    if "е" in t:
        out["е→ё"] = t.replace("е", "ё", 1)
    if "«" in t:
        out["«»→\"\""] = t.replace("«", '"').replace("»", '"')
        out["«»→„“"] = t.replace("«", "„").replace("»", "“")
    if '"' in t:
        out["\"\"→«»"] = re.sub(r'"([^"]*)"', r"«\1»", t)
    out["nbsp"] = t.replace(" ", " ")
    out["двойной пробел"] = t.replace(" ", "  ", 3)
    w = re.search(r"[а-яё]{8,}", t)
    if w:
        out["мягкий перенос"] = t.replace(w.group(0), w.group(0)[:4] + "­" + w.group(0)[4:], 1)
    if "fi" in t or "fl" in t:
        out["лигатуры"] = t.replace("fi", "ﬁ").replace("fl", "ﬂ")
    if " — " in t:
        out["—→-"] = t.replace(" — ", " - ")
    if " - " in t:
        out["-→—"] = t.replace(" - ", " — ")
    mix = t.replace("ё", "е").replace("«", '"').replace("»", '"').replace(" ", " ", 2)
    if mix != t:
        out["всё сразу"] = mix
    return out


@pytest.fixture(scope="module")
def views():
    out = {"md": dv.load(SRC.with_suffix(".md"))}
    if _has("pymupdf"):
        out["pdf"] = dv.load(SRC.with_suffix(".pdf"))
    if _has("docx"):
        out["docx"] = dv.load(SRC.with_suffix(".docx"))
    return out


def test_official_quotes_survive_distortions_in_all_formats(views):
    md = views["md"]
    total, misses = 0, []
    for ln in dv.nonempty(md):
        t = ln["text"].strip()
        if len(t) < 15:
            continue
        unique = len(Q._line_hits(md, t)) <= 1
        for fmt, v in views.items():
            if not Q.verify_quote(v, t):
                continue  # строки нет в этом формате (в PDF длинная строка кода обрезана краем страницы)
            for name, q in _variants(t).items():
                total += 1
                m = Q.verify_quote(v, q)
                ok = bool(m) and (fmt != "md" or not unique or m["line_start"] <= ln["n"] <= m["line_end"])
                if not ok:
                    misses.append((fmt, name, q[:80]))
    assert total > 1000
    assert misses == [], misses[:10]


def test_official_formats_carry_every_md_line(views):
    """Каждая непустая строка MD находится в PDF и DOCX (кроме строки кода, обрезанной в самом PDF)."""
    md = views["md"]
    lost = {}
    for fmt, v in views.items():
        if fmt == "md":
            continue
        lost[fmt] = [ln["text"][:70] for ln in dv.nonempty(md)
                     if len(ln["text"].strip()) >= 3 and not Q.verify_quote(v, ln["text"])]
    if "docx" in lost:
        assert lost["docx"] == []
    if "pdf" in lost:
        # в самом PDF строка схемы обрезана краем страницы: «… → AlertsController» без «→ приложение.»
        assert [x for x in lost["pdf"] if "AlertsController" not in x] == []


@pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
def test_typography_inside_pdf_matches_plain_quote():
    v = dv.load(ROOT / "tests/v2/fixtures/25_zoo/pdf_typo.pdf")
    for q in ('Поле «Причина» обязательно; значение по умолчанию - "Утеря"',
              "Стоимость перевыпуска — 1 500 ₸, срок — 5 рабочих дней",
              "Клиент еще раз подтверждает адрес доставки",
              "Сервис проверяет fiнальный статус заявки",
              "Эﬀективная дата блокировки — дата подтверждения заказа"):
        m = Q.verify_quote(v, q)
        assert m, q
    joined = "\n".join(ln["text"] for ln in v["lines"])
    for bad in ("­", "ﬁ", "ﬂ", "ﬀ", " "):
        assert bad not in joined
