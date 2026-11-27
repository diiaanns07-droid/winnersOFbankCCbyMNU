"""№25, v2.1: выгрузки привязаны к месту цитаты — проверка открытием результата, а не по коду выгрузки.

Прогон mock на официальном ТЗ (DOCX и PDF), затем:

* Word с примечаниями: у каждого сверенного доказательства есть примечание этого дефекта, чей диапазон в документе
  содержит слова цитаты (номер пункта автонумерации — не текст абзаца, его не считаем). До исправления цитаты
  пунктов автонумерации («5. При отклонении суммы…») оставались без примечания: 92 из 109 → 109 из 109;
* PDF с выделениями: выделение дефекта на странице доказательства покрывает слова цитаты;
* Jira CSV: UTF-8 с BOM, читается модулем csv, одна строка на дефект, кириллица на месте.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "release/input/requirements"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _toks(s: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", s).replace("ё", "е").lower())


def _quote_toks(q: str) -> set[str]:
    q = re.sub(r"^\s*(?:\d{1,2}(?:\.\d{1,2})*[.)]|[a-zа-я][.)])\s+", "", q, flags=re.I)  # номер автонумерации
    return set(_toks(q))


def _run(tmp_path: Path, ext: str) -> tuple[dict, dict]:
    from bcc_review.v2 import pipeline
    out = tmp_path / f"r_{ext}.md"
    report, written = pipeline.review(SRC.with_suffix("." + ext), out, {
        "provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False, "cache": False,
        "export": ["jira", "docx", "pdf"]})
    return report, written


def _evidence(report: dict) -> list[tuple[str, dict]]:
    return [(f["id"], e) for f in report.get("findings") or [] for e in f.get("evidence") or []
            if e.get("verified") in ("exact", "normalized", "fuzzy")]


@pytest.mark.skipif(not _has("docx"), reason="нет python-docx")
def test_docx_comments_cover_every_quote(tmp_path):
    report, written = _run(tmp_path, "docx")
    z = zipfile.ZipFile(written["docx"])
    doc, com = z.read("word/document.xml").decode(), z.read("word/comments.xml").decode()
    ranges: list[tuple[str, set[str]]] = []
    for m in re.finditer(r'<w:comment w:id="(\d+)"[^>]*>(.*?)</w:comment>', com, re.S):
        head = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", m.group(2)))[:8]
        r = re.search(r'<w:commentRangeStart w:id="%s"/>(.*?)<w:commentRangeEnd w:id="%s"/>' % (m.group(1), m.group(1)),
                      doc, re.S)
        if r:
            text = " ".join("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in r.group(1).split("</w:p>"))
            ranges.append((head, set(_toks(text))))
    evs = _evidence(report)
    assert len(evs) > 50
    missed = [(fid, e["quote"][:60]) for fid, e in evs
              if not any(fid in h and _quote_toks(e["quote"]) <= toks for h, toks in ranges)]
    assert missed == [], missed[:5]


@pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
def test_pdf_highlights_on_quote_page(tmp_path):
    import pymupdf
    report, written = _run(tmp_path, "pdf")
    pdf = pymupdf.open(written["pdf"])
    marks: list[tuple[int, str, set[str]]] = []
    for page in pdf:
        words = page.get_text("words")
        for a in page.annots() or []:
            if a.type[1] != "Highlight":
                continue
            v = a.vertices
            rects = [pymupdf.Quad(v[k:k + 4]).rect for k in range(0, len(v), 4)]
            ws = [w[4] for w in words if any(r.contains(pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
                                             for r in rects)]
            marks.append((page.number + 1, a.info.get("content", "")[:8], set(_toks(" ".join(ws)))))
    evs = _evidence(report)
    assert len(evs) > 20
    score = []
    for fid, e in evs:
        q = _quote_toks(e["quote"])
        best = max((len(q & t) / max(len(q), 1) for pg, h, t in marks if pg == e["page"] and fid in h), default=0)
        score.append(best)
    assert all(s >= 0.5 for s in score), score  # на своей странице и на своих словах
    assert sum(s >= 0.999 for s in score) >= 0.9 * len(score)  # строка таблицы с переносом — выделена первая ячейка


def test_jira_csv_opens(tmp_path):
    report, written = _run(tmp_path, "md")
    raw = Path(written["jira"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # Excel на Windows открывает кириллицу без мастера импорта
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines(keepends=True)))
    assert len(rows) == len(report["findings"]) and rows
    assert all(r["Summary"].startswith("[D-") and re.search("[а-я]", r["Description"]) for r in rows)
