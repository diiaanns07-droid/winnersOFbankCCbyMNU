"""Сквозной сценарий №14 на комплекте релиза: release/input/requirements.pdf и его offline-отчёт.

Проверяется настоящий write_pdf, а результат перечитывается без MuPDF (pypdf + PDFium, см.
release_check.py). Тест пропускается, если в checkout нет release/ (он появляется в bcc/integration).
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from release_check import ROOT, check

pytest.importorskip("pypdf")
pytest.importorskip("pypdfium2")

REL = ROOT / "release"
PDF_IN, PDF_REP = REL / "input" / "requirements.pdf", REL / "reports" / "offline" / "requirements_pdf.json"
MD_IN, MD_REP = REL / "input" / "requirements.md", REL / "reports" / "offline" / "requirements.json"
pytestmark = pytest.mark.skipif(not (PDF_IN.exists() and PDF_REP.exists()), reason="в этом checkout нет release/")


def _all_ok(res: dict) -> None:
    c = res["coverage"]
    assert c["anchors_in_report"] == c["anchors_in_export"] == c["highlighted_anchors"], c
    assert c["content_ok"] == c["position_ok"] == c["highlights"], c
    assert res["verify_export"]["ok"], res["verify_export"]["errors"]
    assert res["source_sha256"] == res["source_sha256_after"]


@pytest.fixture(scope="module")
def pdf_result(tmp_path_factory):
    return check(PDF_IN, PDF_REP, tmp_path_factory.mktemp("rel") / "requirements.annotated.pdf")


def test_release_pdf_every_anchor_highlighted_and_verified(pdf_result):
    res = pdf_result
    _all_ok(res)
    c = res["coverage"]
    assert (c["findings"], c["anchors_in_report"], c["notes"], c["skipped"]) == (25, 63, 0, 0)
    assert res["pages_source"] == res["pages_output"] == 6, "число страниц исходника сохраняется"
    assert not [w for w in res["warnings"] if "поверх текста" in w], res["warnings"]


def test_release_pdf_two_line_quotes(pdf_result):
    """Двухстрочные опоры: под каждой из двух полос — своя часть цитаты, вместе — вся цитата."""
    two = [r for r in pdf_result["rows"] if r["status"] == "highlight" and " ⏎ " in r["under"]
           and "|" not in (r["quote"] or "")]
    assert len(two) >= 5, len(two)
    for r in two:
        assert r["content_ok"] and r["position_ok"], r
    f002 = [r for r in two if r["id"] == "F-002" and r["quote"] == "сумму покупки в тиынах"]
    assert f002 and f002[0]["under"] == "сумму покупки в ⏎ тиынах"


def test_release_pdf_repeated_table_text_lands_in_own_row(pdf_result):
    """«Да / Нет | Да / Нет» стоит в шести строках чек-листа: каждая опора — в своей строке."""
    rows = [r for r in pdf_result["rows"] if r["id"] == "F-020" and "Да / Нет" in (r["quote"] or "")]
    assert len(rows) == 4 and all(r["content_ok"] and r["position_ok"] for r in rows)
    url = [r for r in pdf_result["rows"] if (r["quote"] or "") in ("/alerts/saveLimit", "saveLimit")]
    assert len(url) == 3 and all(r["position_ok"] for r in url)


def _second(text: str, quote: str) -> int:
    i = text.index(quote)
    return text.index(quote, i + 1)


def test_repeated_sum_and_imprecise_location_controls(tmp_path):
    """Контроль на настоящем Document: второе вхождение суммы в строке таблицы и блок без координат."""
    rep = copy.deepcopy(json.loads(PDF_REP.read_text(encoding="utf-8")))
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    base = copy.deepcopy(rep["findings"][-1])
    controls = []
    for n, quote in enumerate(("50 000 ₸", "4 000 ₸", "19 900 ₸"), 1):
        b = next(x for x in rep["document"]["blocks"] if x["kind"] == "table_row" and x["text"].count(quote) == 2)
        s = _second(b["text"], quote)
        controls.append((f"C-0{n}", b, {"block_id": b["id"], "start": s, "end": s + len(quote), "quote": quote}))
    # ридер дал бы только страницу (без координат слов), а сумма на странице встречается дважды
    page2 = blocks[controls[0][1]["id"]]["loc"]["page"]
    blind = {"id": "b9001", "kind": "table_row", "section": [], "text": "50 000 ₸", "loc": {"page": page2}}
    rep["document"]["blocks"].append(blind)
    controls.append(("C-04", blind, {"block_id": "b9001", "start": 0, "end": 8, "quote": "50 000 ₸"}))
    for fid, _, ev in controls:
        f = copy.deepcopy(base)
        f.update({"id": fid, "evidence": [ev], "witness": None, "title": f"Контроль {fid}", "req_ids": []})
        rep["findings"].append(f)
    res = check(PDF_IN, PDF_REP, tmp_path / "controls.pdf", rep=rep)
    by = {r["id"]: r for r in res["rows"] if r["id"].startswith("C-")}
    for fid, b, ev in controls[:3]:
        r = by[fid]
        assert r["status"] == "highlight" and r["content_ok"] and r["position_ok"], r
        # выделено именно второе вхождение: знаки не лежат в рамках слов первого вхождения
        first = b["text"].index(ev["quote"])
        frs = [f for f in b["loc"]["fragments"] if f["start"] < first + len(ev["quote"]) and f["end"] > first]
        assert frs and not any(f["start"] < ev["end"] and f["end"] > ev["start"] for f in frs)
    note = by["C-04"]
    assert note["status"] == "note" and note["page"] == page2 and note["content_ok"], note
    assert "нет координат слов от ридера" in note["reason"] and re.search(r"встречается \d+ раза", note["reason"])


@pytest.mark.skipif(not (MD_IN.exists() and MD_REP.exists()), reason="нет Markdown-входа релиза")
def test_release_markdown_fallback_input(tmp_path):
    """Запасной вход: Markdown, который экспорт сам переводит в постраничный PDF."""
    res = check(MD_IN, MD_REP, tmp_path / "requirements.md.pdf")
    _all_ok(res)
    c = res["coverage"]
    assert (c["findings"], c["anchors_in_report"], c["notes"], c["skipped"]) == (26, 64, 0, 0)
    assert c["anchors_split_across_pages"] == 1 and c["highlights"] == 65
    import pymupdf

    with pymupdf.open(res["output"]) as d:
        from bcc_review.exports.pdf import page_label

        assert [page_label(d, i) for i in range(d.page_count)] == [f"Экспорт-{i + 1}" for i in range(d.page_count)]
        assert "(39)" in d[1].get_textbox(pymupdf.Rect(0, 40, 56, 80)), "продолжение строки 39 помечено на полях"
