"""№03: экспорт для банка — Jira CSV, Word (комментарии в копии DOCX / Word-версия отчёта), PDF с выделениями.

Каждый экспорт проверяется чтением результата: csv, python-docx, PyMuPDF.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q
from bcc_review.v2.render import exports as E

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MD = ROOT / "release/input/requirements.md"
OFFICIAL_PDF = ROOT / "release/input/requirements.pdf"
CASHBACK_DOCX = ROOT / "evaluation/dev/corpus/cases/cashback.base/source.docx"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


needs_pdf = pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
needs_docx = pytest.mark.skipif(not _has("docx"), reason="нет python-docx")

OFFICIAL_SPECS = [
    ("critical", "Критерий приёмки №2 противоречит правилу месяца",
     [("Месяц определяется по дате совершения покупки в Алматы", None), ("Февральский счётчик вырос на 4 000 ₸", None)]),
    ("critical", "Лимит одного уведомления противоречит правилу смены порога",
     [("максимум один такой push за календарный месяц", None),
      ("следующее достижение вызывает push независимо от истории", None)]),
    ("major", "Типы полей запроса и ответа расходятся", [("amount | integer", 143), ("amount | string", 156)]),
    ("major", "Ответ 200 содержит ошибку", [('{"result":"ERROR","message":"Проверьте сумму"}', None),
                                            ("200. Successful — Created", None)]),
    ("minor", "Цитата через две строки", [("Ответ в случае успешного выполнения метода. 400. Ответ в случае", 162)]),
    ("minor", "Галлюцинация", [("Этой фразы в документе нет совсем", 10)]),
]


def _report(path: Path, specs) -> tuple[dict, dict]:
    view = dv.load(path)
    cands = []
    for i, (sev, title, evs) in enumerate(specs, 1):
        cands.append({
            "id": f"D-{i:02d}", "title": title, "kind": "contradiction", "criterion": "set_consistent",
            "severity": sev, "requirement_ids": ["R-04"],
            "evidence": [{"quote": q, "line": ln} for q, ln in evs],
            "problem": "Два места документа дают разные результаты для одного входа.",
            "scenario": "Покупка 31.01 в 23:58, проведение 01.02 в 00:03.",
            "impact": "Разработка и приёмка выберут разные правила.",
            "recommendation": "Оставить одно правило и поправить критерий.",
            "rewrite": "Месяц определяется по <уточнить: дате совершения или проведения>.",
            "question": "", "blocks": "both", "priority": i if sev == "critical" else 0,
            "standard_refs": ["ISO/IEC/IEEE 29148:2018 п. 5.2.6"]})
    if path.suffix == ".pdf":  # строки PDF другие: подсказки только для MD
        for c in cands:
            for e in c["evidence"]:
                e["line"] = None
    res = Q.verify_candidates(view, cands)
    report = {
        "document": dv.summary(view), "findings": res["candidates"], "rejected": res["rejected"],
        "questions": [{"id": "Q-01", "finding_ids": ["D-01"], "to": "Владелец продукта", "blocking": True,
                       "question": "По какой дате относить покупку к месяцу?",
                       "options": ["по дате совершения", "по дате проведения"], "why": "Критерий №2"}],
        "verdict": {"development": "no", "testing": "no", "summary": "Есть противоречия.", "fix_first": ["D-01"]},
    }
    return report, view


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_jira_csv(tmp_path):
    report, view = _report(OFFICIAL_MD, OFFICIAL_SPECS)
    assert len(report["findings"]) == 5 and report["rejected"][0]["id"] == "D-06"
    res = E.export(report, view, OFFICIAL_MD, tmp_path / "report", ["jira"])[0]
    assert res["status"] == "written" and res["path"].endswith("report.jira.csv")
    raw = Path(res["path"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(Path(res["path"]).open(encoding="utf-8-sig", newline="")))
    assert len(rows) == 5 and list(rows[0]) == E.JIRA_COLUMNS
    assert rows[0]["Summary"].startswith("[D-01] Критерий приёмки №2")
    assert [r["Priority"] for r in rows] == ["Highest", "Highest", "High", "High", "Low"]
    assert "severity-critical" in rows[0]["Labels"] and "fix-first" in rows[0]["Labels"] and " " in rows[0]["Labels"]
    d = rows[0]["Description"]
    assert "«Месяц определяется по дате совершения покупки в Алматы»" in d
    assert "строка 38" in d and "строка 64" in d and "Функциональные требования" in d
    assert "h3. Сценарий" in d and "По какой дате относить покупку к месяцу?" in d and "** по дате проведения" in d
    assert "Согласованность" in d and "R-04" in d
    assert "Этой фразы" not in Path(res["path"]).read_text(encoding="utf-8-sig")   # отклонённые не экспортируются


@needs_docx
def test_word_report_for_markdown_input(tmp_path):
    import docx
    report, view = _report(OFFICIAL_MD, OFFICIAL_SPECS)
    res = E.export(report, view, OFFICIAL_MD, tmp_path / "report.md", ["docx"])[0]
    assert res["status"] == "written" and res["path"].endswith("report.docx")
    d = docx.Document(res["path"])
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Ревью требований: Уведомление о расходах по карте" in text
    assert "нельзя начинать" in text and "D-01. Критерий приёмки №2" in text
    assert "«Февральский счётчик вырос на 4 000 ₸» — Часть A. Новый функционал › Критерии приемки, строка 64" in text
    # из Markdown-отчёта, если он передан
    md = "# Отчёт\n\n**Вердикт:** нельзя\n\n| ID | Суть |\n| :--- | :--- |\n| D-01 | Конфликт `месяца` |\n\n* пункт\n"
    res2 = E.write_docx(report, view, OFFICIAL_MD, tmp_path / "r2", markdown=md)
    d2 = docx.Document(res2["path"])
    assert d2.paragraphs[0].text == "Отчёт" and len(d2.tables) == 1
    assert d2.tables[0].cell(1, 1).text == "Конфликт месяца"


@needs_docx
def test_word_comments_in_docx_copy(tmp_path):
    import docx
    specs = [("critical", "Выбор категории действует не сразу",
              [("Выбор действует с первого дня следующего месяца", None),
               ("Клиент выбирает категорию до конца текущего месяца", None)]),
             ("major", "Поле категории", [("category | string | Да", None)]),
             ("minor", "Ставка", [("Ставка кэшбэка составляет 5 % от суммы покупки", None)])]
    report, view = _report(CASHBACK_DOCX, specs)
    before = _sha(CASHBACK_DOCX)
    res = E.export(report, view, CASHBACK_DOCX, tmp_path / "report", ["docx"])[0]
    assert res["status"] == "written", res["message"]
    assert res["path"].endswith("report.annotated.docx") and res["anchored"] == 3 and res["comments"] == 4
    assert _sha(CASHBACK_DOCX) == before
    d = docx.Document(res["path"])
    comments = list(d.comments)
    assert len(comments) == 5                       # 4 места + сводный комментарий
    texts = [c.text for c in comments]
    assert sum(t.startswith("[D-01] Критичный") for t in texts) == 2
    assert any(t.startswith("Сводка ревью ТЗ") for t in texts)
    assert any("Исправление: Оставить одно правило" in t for t in texts)
    # исходный текст на месте
    body = "\n".join(p.text for p in d.paragraphs)
    assert "Выбор действует с первого дня следующего месяца" in body


@needs_pdf
def test_pdf_highlights_in_copy(tmp_path):
    import pymupdf
    report, view = _report(OFFICIAL_PDF, OFFICIAL_SPECS)
    before = _sha(OFFICIAL_PDF)
    res = E.export(report, view, OFFICIAL_PDF, tmp_path / "report", ["pdf"])[0]
    assert res["status"] == "written", res["message"]
    assert res["path"].endswith("report.annotated.pdf") and res["anchored"] == 5
    assert _sha(OFFICIAL_PDF) == before
    got: dict[str, list[str]] = {}
    notes = []
    with pymupdf.open(res["path"]) as d:
        assert d.page_count == 6
        for page in d:
            for a in page.annots():
                if a.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT:
                    fid = a.info["subject"].split(" · ")[0]
                    v = a.vertices
                    words = " ".join(page.get_textbox(pymupdf.Quad(v[i:i + 4]).rect) for i in range(0, len(v), 4))
                    got.setdefault(fid, []).append(" ".join(words.split()))
                    assert a.info["content"].startswith(f"[{fid}]")
                else:
                    notes.append(a.info.get("content", ""))
    assert set(got) == {"D-01", "D-02", "D-03", "D-04", "D-05"}
    assert any("Февральский счётчик вырос на 4 000" in t for t in got["D-01"])
    assert any("Месяц определяется по дате совершения покупки в Алматы" in t for t in got["D-01"])
    assert any("Проверьте сумму" in t for t in got["D-04"])
    assert any("400. Ответ в случае" in t for t in got["D-05"])        # цитата через две строки
    assert any(t.startswith("Сводка ревью требований") for t in notes)


@needs_pdf
def test_pdf_for_markdown_input_and_skips(tmp_path):
    import pymupdf
    report, view = _report(OFFICIAL_MD, OFFICIAL_SPECS)
    res = E.export(report, view, OFFICIAL_MD, tmp_path / "report", ["pdf", "html", "xlsx"])
    by = {r["format"]: r for r in res}
    assert "html" not in by                      # HTML рисует №14, здесь пропускается
    assert by["xlsx"]["status"] == "skipped"
    if by["pdf"]["status"] == "written":         # производная PDF-версия Markdown (экспорт v1)
        with pymupdf.open(by["pdf"]["path"]) as d:
            assert sum(1 for p in d for a in p.annots() if a.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT) >= 5
    else:
        assert by["pdf"]["status"] == "failed" and by["pdf"]["message"]


def test_export_never_raises(tmp_path):
    report = {"document": {"file": "x.md"}, "findings": [{"id": "D-01", "severity": "major", "title": "T",
                                                          "evidence": [{"quote": "q", "line_start": 999}]}]}
    view = dv.from_text("# Док\n\nтекст\n")
    res = E.export(report, view, tmp_path / "missing.docx", tmp_path / "r", "jira,docx,pdf")
    assert [r["format"] for r in res] == ["jira", "docx", "pdf"]
    assert res[0]["status"] == "written"
    assert res[1]["status"] == "failed" and res[2]["status"] == "skipped"
    assert E.plural(1, "а", "б", "в") == "а" and E.plural(3, "а", "б", "в") == "б" and E.plural(11, "а", "б", "в") == "в"


SAMPLES = ROOT / "tests/v2/fixtures/03_export_samples"


@needs_docx
@needs_pdf
def test_demo_samples_open():
    """Образцы для демо (make_samples.py) открываются и содержат комментарии, выделения и задачи."""
    import docx
    import pymupdf
    d = docx.Document(str(SAMPLES / "official.annotated.docx"))
    comments = list(d.comments)
    assert len(comments) >= 30 and any(c.text.startswith("Сводка ревью ТЗ") for c in comments)
    assert all("подтверждено" not in c.text.splitlines()[0] for c in comments)
    with pymupdf.open(str(SAMPLES / "official.annotated.pdf")) as p:
        hl = [a for pg in p for a in pg.annots() if a.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT]
        assert len(hl) >= 30 and all(a.info["content"].startswith("[D-") for a in hl)
        assert all(abs(a.opacity - 0.45) < 0.01 for a in hl)
    rows = list(csv.DictReader((SAMPLES / "official.jira.csv").open(encoding="utf-8-sig", newline="")))
    assert len(rows) >= 20 and rows[0]["Priority"] == "Highest"
    assert len(list((SAMPLES / "png").glob("*.png"))) >= 3
