"""Экспорт результата v2 для банка (владелец №03): Jira CSV, Word, PDF.

``export(report, view, input_path, out_base, formats)`` — одна точка вызова для ``--export jira,docx,pdf``:

* **jira** — ``<out_base>.jira.csv``: строка на дефект (Summary, Description с цитатами и местом, Issue Type,
  Priority по серьёзности, Labels). UTF-8 с BOM (открывается в Excel), все поля в кавычках, RFC 4180.
* **docx** — вход DOCX: ``<out_base>.annotated.docx`` — копия исходного файла с комментариями Word на местах цитат
  (проверенный экспорт v1 ``exports/word.annotate_docx`` через адаптер координат). Вход MD/TXT/PDF/HTML:
  ``<out_base>.docx`` — Word-версия отчёта (из Markdown-отчёта, если он передан, иначе из ``report``).
* **pdf** — вход PDF: ``<out_base>.annotated.pdf`` — копия исходного файла с выделениями цитат и всплывающими
  примечаниями (PyMuPDF ``add_highlight_annot``), плюс сводная заметка на первой странице. Вход MD/TXT: производная
  PDF-версия документа с теми же выделениями (экспорт v1 ``exports/pdf``), если он доступен.

Каждый экспорт возвращает ``{"format", "status": written|skipped|failed, "path", "message", "anchored", "total"}``
и никогда не роняет прогон: ошибка одного формата — запись ``failed`` с объяснением по-русски.
"""

from __future__ import annotations

import csv
import io
import os
import re
import traceback
from pathlib import Path
from typing import Any, Iterable

SEVERITY_RU = {"critical": "Критичный", "major": "Существенный", "minor": "Незначительный"}
PRIORITY = {"critical": "Highest", "major": "High", "minor": "Low"}
SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}
BLOCKS_RU = {"development": "разработку", "testing": "тестирование", "both": "разработку и тестирование",
             "none": ""}
VERDICT_RU = {"no": "нельзя начинать", "conditional": "можно с условиями", "yes": "можно начинать"}
CRITERIA = {
    "necessary": ("Необходимость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5"),
    "appropriate": ("Уместность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5"),
    "unambiguous": ("Однозначность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.2"),
    "complete": ("Полнота требования", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.3"),
    "singular": ("Единичность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5"),
    "feasible": ("Осуществимость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5"),
    "verifiable": ("Проверяемость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.6"),
    "correct": ("Корректность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.1"),
    "conforming": ("Соответствие шаблону", "ISO/IEC/IEEE 29148:2018 п. 5.2.5"),
    "language": ("Язык требований", "ISO/IEC/IEEE 29148:2018 п. 5.2.7"),
    "set_complete": ("Полнота набора", "ISO/IEC/IEEE 29148:2018 п. 5.2.6; IEEE 830-1998 п. 4.3.3"),
    "set_consistent": ("Согласованность", "ISO/IEC/IEEE 29148:2018 п. 5.2.6; IEEE 830-1998 п. 4.3.4"),
    "set_feasible": ("Осуществимость набора", "ISO/IEC/IEEE 29148:2018 п. 5.2.6"),
    "set_comprehensible": ("Понятность", "ISO/IEC/IEEE 29148:2018 п. 5.2.6"),
    "set_validatable": ("Возможность валидации", "ISO/IEC/IEEE 29148:2018 п. 5.2.6"),
    "ranked": ("Ранжирование", "IEEE 830-1998 п. 4.3.5"),
    "modifiable": ("Модифицируемость", "IEEE 830-1998 п. 4.3.7"),
    "traceable": ("Прослеживаемость", "IEEE 830-1998 п. 4.3.8"),
    "risk": ("ИБ и операционные риски", "чек-лист ревью банка"),
}
JIRA_COLUMNS = ["Summary", "Description", "Issue Type", "Priority", "Labels"]
AUTHOR = "BCC Review"
SUFFIX = {"jira": ".jira.csv", "docx_annotated": ".annotated.docx", "docx": ".docx", "pdf_annotated": ".annotated.pdf",
          "pdf": ".pdf"}
FORMATS = ("jira", "docx", "pdf")
os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")  # без совета про pymupdf_layout в stdout (№16)


# --------------------------------------------------------------------------- общая точка вызова
def export(report: dict, view: dict, input_path: str | Path, out_base: str | Path,
           formats: Iterable[str] = FORMATS, *, markdown: str | None = None) -> list[dict]:
    """Выполнить запрошенные экспорты. ``out_base`` — путь отчёта без расширения (``out/report``)."""
    base = Path(out_base)
    if base.suffix.lower() in (".md", ".json", ".html"):
        base = base.with_suffix("")
    report = reader_report(report)
    results = []
    for fmt in _formats(formats):
        try:
            if fmt == "jira":
                res = write_jira_csv(report, base.with_name(base.name + SUFFIX["jira"]))
            elif fmt == "docx":
                res = write_docx(report, view, input_path, base, markdown=markdown)
            elif fmt == "pdf":
                res = write_pdf(report, view, input_path, base)
            else:
                res = _res(fmt, "skipped", None, f"формат экспорта «{fmt}» не поддерживается: jira, docx, pdf")
        except Exception as exc:  # noqa: BLE001 — экспорт не должен ронять прогон
            res = _res(fmt, "failed", None, f"экспорт {fmt} не выполнен: {type(exc).__name__}: {exc}")
            res["traceback"] = traceback.format_exc(limit=5)
        results.append(res)
    return results


_LREF = re.compile(r"(?:(?<![\w-])([А-Яа-яЁё]{1,7})\s+)?\bL0*(\d{1,5})(?:\s*[–-]\s*L?0*(\d{1,5}))?\b")
_FINDING_TEXT = ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question")


def reader_text(text: Any) -> str:
    """Текст для читателя Jira/Word/PDF: «L038», «L38–L40» из нумерованного документа → «строка 38», «строки 38–40»
    (с падежом после предлога, как в отчёте №13)."""
    s = str(text or "")
    if "L" not in s:
        return s
    try:
        from .markdown import _lref  # падеж «строке/строках…» — как в Markdown-отчёте
    except Exception:  # noqa: BLE001
        def _lref(m: re.Match) -> str:
            word = f"строки {m.group(2)}–{m.group(3)}" if m.group(3) else f"строка {m.group(2)}"
            return f"{m.group(1)} {word}" if m.group(1) else word
    return _LREF.sub(_lref, s)


def reader_report(report: dict) -> dict:
    """Копия отчёта с текстами дефектов и вопросов без внутренних кодов строк («L042» → «строка 42»)."""
    out = dict(report)
    out["findings"] = [{**f, **{k: reader_text(f[k]) for k in _FINDING_TEXT if isinstance(f.get(k), str)}}
                       if isinstance(f, dict) else f for f in report.get("findings") or []]
    qs = []
    for q in report.get("questions") or []:
        if isinstance(q, dict):
            q = {**q, "question": reader_text(q.get("question")), "why": reader_text(q.get("why")),
                 "options": [reader_text(o) for o in q.get("options") or []]}
        qs.append(q)
    out["questions"] = qs
    return out


def _formats(formats: Iterable[str] | str) -> list[str]:
    if isinstance(formats, str):
        formats = formats.split(",")
    out = []
    for f in formats:
        f = f.strip().lower()
        if f in ("word",):
            f = "docx"
        if f and f not in ("html", "md", "json") and f not in out:
            out.append(f)
    return out


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 дефект», «3 дефекта», «5 дефектов»."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _n(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def _res(fmt: str, status: str, path: Path | None, message: str, **extra: Any) -> dict:
    return {"format": fmt, "status": status, "path": str(path) if path else "", "message": message, **extra}


# --------------------------------------------------------------------------- данные отчёта
def findings_of(report: dict) -> list[dict]:
    fs = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    return sorted(fs, key=lambda f: (0 if f.get("priority") else 1, f.get("priority") or 0,
                                     SEV_ORDER.get(str(f.get("severity")), 3), _natural(f.get("id"))))


def _natural(x: Any) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(x or "")))


def criterion_label(code: Any) -> str:
    name, ref = CRITERIA.get(str(code or ""), (str(code or ""), ""))
    return f"{name} ({ref})" if ref else name


def _short_section(section: str) -> str:
    """Раздел как в отчёте №13: «Часть A › Функциональные требования» вместо полного пути."""
    try:
        from .markdown import short_section
        return short_section(section)
    except Exception:  # noqa: BLE001 — отчёт №13 недоступен: полный путь
        return str(section or "")


def place_of(ev: dict) -> str:
    """Место как в отчёте: «Часть A › Функциональные требования, строка 38, стр. 2» (страница — для PDF)."""
    a, b = ev.get("line_start") or ev.get("line"), ev.get("line_end") or ev.get("line_start") or ev.get("line")
    parts = []
    if ev.get("section"):
        parts.append(_short_section(str(ev["section"])))
    if a:
        parts.append(f"строка {a}" if not b or b == a else f"строки {a}–{b}")
    if ev.get("page"):
        parts.append(f"стр. {ev['page']}")
    return ", ".join(p for p in parts if p)


def _questions_for(report: dict, fid: str) -> list[dict]:
    return [q for q in report.get("questions") or [] if isinstance(q, dict) and fid in (q.get("finding_ids") or [])]


def _one_line(s: Any) -> str:
    return " ".join(str(s or "").split())


def _verified(ev: dict) -> bool:
    return ev.get("verified", "exact") != "missing"


# --------------------------------------------------------------------------- Jira CSV
def jira_rows(report: dict, *, issue_type: str = "Task") -> list[dict[str, str]]:
    doc = report.get("document") or {}
    rows = []
    for f in findings_of(report):
        sev = str(f.get("severity") or "").lower()
        labels = ["bcc-review", f"severity-{sev or 'none'}"]
        for key in ("criterion", "kind"):
            if f.get(key):
                labels.append(f"{key}-{f[key]}")
        if f.get("blocks") and f["blocks"] != "none":
            labels.append(f"blocks-{f['blocks']}")
        if f.get("priority"):
            labels.append("fix-first")
        summary = f"[{f.get('id', '')}] {_one_line(f.get('title'))}"
        if len(summary) > 255:
            summary = summary[:254].rstrip() + "…"
        rows.append({"Summary": summary, "Description": jira_description(f, report, doc),
                     "Issue Type": issue_type, "Priority": PRIORITY.get(sev, "Medium"),
                     "Labels": " ".join(dict.fromkeys(re.sub(r"[^\w\-.]+", "_", x) for x in labels))})
    return rows


def jira_description(f: dict, report: dict, doc: dict | None = None) -> str:
    """Описание задачи в разметке Jira: суть, места с цитатами, сценарий, последствия, действие, вопрос."""
    doc = doc or {}
    out: list[str] = []

    def sec(title: str, body: Any) -> None:
        body = str(body or "").strip()
        if body:
            out.extend([f"h3. {title}", body, ""])

    sec("Проблема", f.get("problem"))
    evs = [e for e in f.get("evidence") or [] if isinstance(e, dict) and _verified(e)]
    if evs:
        out.append("h3. Где в документе")
        for e in evs:
            out.append(f"* «{_one_line(e.get('quote'))}» — {place_of(e) or 'место не указано'}")
        out.append("")
    sec("Сценарий", f.get("scenario"))
    sec("Последствия", f.get("impact"))
    sec("Что сделать", f.get("recommendation"))
    if str(f.get("rewrite") or "").strip():
        out.extend(["h3. Предлагаемая формулировка", "{quote}", str(f["rewrite"]).strip(), "{quote}", ""])
    qs = _questions_for(report, str(f.get("id") or ""))
    if qs:
        out.append("h3. Вопрос владельцу")
        for q in qs:
            line = f"* {_one_line(q.get('question'))}"
            if q.get("to"):
                line += f" (кому: {q['to']})"
            out.append(line)
            for o in q.get("options") or []:
                out.append(f"** {_one_line(o)}")
        out.append("")
    elif str(f.get("question") or "").strip():
        sec("Вопрос владельцу", f.get("question"))
    meta = []
    sev = str(f.get("severity") or "")
    if sev:
        meta.append(f"Серьёзность: {SEVERITY_RU.get(sev, sev).lower()}")
    if BLOCKS_RU.get(str(f.get("blocks") or "")):
        meta.append(f"Блокирует: {BLOCKS_RU[str(f['blocks'])]}")
    if f.get("criterion"):
        meta.append(f"Критерий: {criterion_label(f['criterion'])}")
    if f.get("standard_refs"):
        meta.append("Стандарты: " + "; ".join(str(x) for x in f["standard_refs"]))
    if f.get("requirement_ids"):
        meta.append("Требования: " + ", ".join(str(x) for x in f["requirement_ids"]))
    src = f"Документ: {doc.get('file') or doc.get('title') or '—'}"
    if doc.get("sha256"):
        src += f" (SHA-256 {str(doc['sha256'])[:12]}…)"
    out.extend(["----", " · ".join(meta), src + " · BCC Review"])
    return "\n".join(x for x in out).strip()


def render_jira_csv(report: dict, **options: Any) -> str:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=JIRA_COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writeheader()
    for row in jira_rows(report, **options):
        w.writerow(row)
    return buf.getvalue()


def write_jira_csv(report: dict, path: str | Path, **options: Any) -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = render_jira_csv(report, **options)
    p.write_bytes(("﻿" + text).encode("utf-8"))
    n = len(findings_of(report))
    return _res("jira", "written", p, f"Jira CSV: {_n(n, 'задача', 'задачи', 'задач')}", anchored=n, total=n)


# --------------------------------------------------------------------------- координаты для экспорта v1
def _v1_document(input_path: Path) -> dict:
    from bcc_review.engine import read_document

    from .. import docview
    if Path(input_path).suffix.lower() == ".pdf":
        docview.pdf_fast_mode()  # без нейросетевого анализа вёрстки PyMuPDF 2.x — в 10 раз быстрее (как в docview)
    return read_document(input_path)


def _block_offset(block: dict, view_line: dict, view: dict) -> int:
    """Смещение строки view внутри текста блока v1."""
    text = str(block.get("text") or "")
    fmt = view.get("format")
    if fmt in ("md", "txt"):
        for item in (block.get("loc") or {}).get("lines") or []:
            try:
                if int(item[0]) == view_line.get("src_line"):
                    return int(item[1])
            except (TypeError, ValueError, IndexError):
                continue
        return 0
    same = [ln for ln in view.get("lines") or [] if ln.get("block_id") == view_line.get("block_id")]
    k = next((i for i, ln in enumerate(same) if ln["n"] == view_line["n"]), 0)
    parts = text.splitlines(keepends=True)
    return sum(len(p) for p in parts[:k])


def evidence_offsets(ev: dict, view: dict, blocks: dict[str, dict]) -> dict | None:
    """``{block_id, start, end, quote}`` для доказательства v2: цитата внутри текста блока читателя v1."""
    from bcc_review.v2 import docview
    n = ev.get("line_start") or ev.get("line")
    ln = docview.line(view, int(n)) if n else None
    if not ln or not ln.get("block_id") or ln["block_id"] not in blocks:
        return None
    block = blocks[ln["block_id"]]
    text = str(block.get("text") or "")
    off = _block_offset(block, ln, view)
    quote = str(ev.get("quote") or "").strip()
    if not text.startswith(quote[:3]):
        # номер пункта автонумерации Word («5. При отклонении…») — в строке view, но не в тексте абзаца v1
        quote = re.sub(r"^(?:\d{1,2}(?:\.\d{1,2})*[.)]|[a-zа-я][.)]|•)\s+", "", quote, flags=re.I) \
            if text.find(quote) < 0 else quote
    pieces = [p.strip() for p in quote.split(" … ")] if " … " in quote else [quote]
    for piece in pieces:
        if not piece:
            continue
        i = text.find(piece, off)
        if i < 0:
            i = text.find(piece)
        if i >= 0:
            return {"block_id": ln["block_id"], "start": i, "end": i + len(piece), "quote": piece}
        # цитата через несколько строк: берём её часть, которая лежит в первой строке
        for cut in range(len(piece) - 1, 7, -1):
            j = text.find(piece[:cut], off)
            if j >= 0 and (cut > 20 or cut == len(piece)):
                return {"block_id": ln["block_id"], "start": j, "end": j + cut, "quote": piece[:cut]}
    part = ln.get("text") or ""
    i = text.find(part, off) if part else -1
    if i >= 0 and part.strip():
        return {"block_id": ln["block_id"], "start": i, "end": i + len(part), "quote": part}
    return None


def to_v1_report(report: dict, view: dict, input_path: Path, doc1: dict | None = None) -> dict:
    """Минимальный отчёт формы v1 для проверенных экспортов Word/PDF v1 (координаты — смещения в блоках)."""
    doc1 = doc1 or _v1_document(input_path)
    blocks = {b["id"]: b for b in doc1.get("blocks") or []}
    findings = []
    for f in findings_of(report):
        evs = []
        for ev in f.get("evidence") or []:
            if isinstance(ev, dict) and _verified(ev):
                o = evidence_offsets(ev, view, blocks)
                if o:
                    evs.append(o)
        title = _one_line(f.get("title"))
        if f.get("problem"):
            title += "\n" + str(f["problem"]).strip()
        impact = str(f.get("impact") or "").strip()
        if f.get("scenario"):
            impact = (impact + "\nСценарий: " if impact else "Сценарий: ") + str(f["scenario"]).strip()
        fix = str(f.get("recommendation") or "").strip()
        if f.get("rewrite"):
            fix = (fix + "\n" if fix else "") + "Формулировка: " + str(f["rewrite"]).strip()
        # status None: в v2 все дефекты прошли судью, пометка «подтверждено» в комментарии лишняя
        findings.append({"id": f.get("id"), "status": None, "severity": f.get("severity"), "title": title,
                         "criterion": criterion_label(f.get("criterion")) if f.get("criterion") else None,
                         "kind": f.get("kind"), "impact": impact, "question": f.get("question") or None,
                         "recommendation": fix or None, "req_ids": list(f.get("requirement_ids") or []),
                         "evidence": evs})
    v = report.get("verdict") or {}
    titles = {f.get("id"): _one_line(f.get("title")) for f in report.get("findings") or [] if isinstance(f, dict)}
    verdict = {"development": VERDICT_RU.get(str(v.get("development")), v.get("development")),
               "testing": VERDICT_RU.get(str(v.get("testing")), v.get("testing")),
               "first_actions": [f"{i}: {titles.get(i, '')}".strip(": ") for i in v.get("fix_first") or []]}
    questions = [{"finding_ids": q.get("finding_ids") or [], "prompt": q.get("question"),
                  "options": q.get("options") or []} for q in report.get("questions") or [] if isinstance(q, dict)]
    sha = doc1.get("id")
    document = dict(doc1)
    document["format"] = {"md": "markdown", "txt": "text"}.get(view.get("format"), view.get("format"))
    return {"document": document, "run": {"source_sha256": sha}, "findings": findings, "questions": questions,
            "verdict": verdict, "requirements": [], "rejected": [], "warnings": []}


# --------------------------------------------------------------------------- Word
def write_docx(report: dict, view: dict, input_path: str | Path, out_base: str | Path, *,
               markdown: str | None = None) -> dict:
    inp = Path(input_path)
    base = Path(out_base)
    if inp.suffix.lower() == ".docx":
        out = base.with_name(base.name + SUFFIX["docx_annotated"])
        return annotate_docx(report, view, inp, out)
    out = base.with_name(base.name + SUFFIX["docx"])
    return report_docx(report, out, markdown=markdown)


def annotate_docx(report: dict, view: dict, input_path: Path, output_path: Path) -> dict:
    """Копия исходного DOCX с комментариями Word на местах цитат (экспорт v1 через адаптер)."""
    from bcc_review.exports import word
    rep1 = to_v1_report(report, view, input_path)
    total = sum(1 for f in rep1["findings"] if f["evidence"])
    res = word.annotate_docx(rep1, input_path, output_path, author=AUTHOR, initials="BCC")
    if res.status != "written":
        return _res("docx", "failed", None, res.message, anchored=0, total=total)
    anchored = len({a.finding_id for a in res.anchors})
    return _res("docx", "written", output_path,
                f"Word с комментариями: отмечено {anchored} из "
                f"{_n(len(rep1['findings']), 'дефекта', 'дефектов', 'дефектов')} "
                f"({_n(len(res.anchors), 'место', 'места', 'мест')} в тексте) и сводный комментарий", anchored=anchored,
                total=len(rep1["findings"]), comments=len(res.anchors))


def report_docx(report: dict, output_path: Path, *, markdown: str | None = None) -> dict:
    """Word-версия отчёта: из Markdown-отчёта (если передан) или напрямую из report."""
    import docx
    from docx.shared import Pt

    d = docx.Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    if markdown and markdown.strip():
        try:  # тот же отчёт без HTML-якорей и экранирования Markdown (№13)
            from .markdown import export_text
            markdown = export_text(markdown)
        except Exception:  # noqa: BLE001
            markdown = re.sub(r"<a id=\"[^\"]*\"></a>", "", markdown).replace("\\|", "∣")
        _md_to_docx(d, markdown)
    else:
        _report_to_docx(d, report)
    _add_toc(d)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(output_path))
    n = len(report.get("findings") or [])
    return _res("docx", "written", output_path, f"Word-версия отчёта: {_n(n, 'дефект', 'дефекта', 'дефектов')}",
                anchored=n, total=n)


def _add_toc(d: Any) -> None:
    """Оглавление Word после заголовка документа: поле TOC (уровни 1–3) и w:updateFields — Word соберёт его при
    открытии (LibreOffice — по «Обновить»)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    heads = [p for p in d.paragraphs if p.style is not None and p.style.name.startswith(("Heading", "Title"))]
    if len(heads) < 3:
        return
    anchor = heads[0]._p
    title = OxmlElement("w:p")
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rpr.append(OxmlElement("w:b"))
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = "Содержание"
    r.append(t)
    title.append(r)
    field = OxmlElement("w:p")
    parts = [("begin", None), (None, ' TOC \\o "1-3" \\h \\z \\u '), ("separate", None),
             ("text", "Оглавление соберётся при открытии документа (или F9 — «Обновить поле»)."), ("end", None)]
    for kind, val in parts:
        run = OxmlElement("w:r")
        if kind in ("begin", "separate", "end"):
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            run.append(fc)
        elif kind == "text":
            tt = OxmlElement("w:t")
            tt.text = val
            run.append(tt)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = val
            run.append(it)
        field.append(run)
    anchor.addnext(field)
    anchor.addnext(title)
    settings = d.settings.element
    if settings.find(qn("w:updateFields")) is None:
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        settings.append(uf)


_MD_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def _add_inline(par: Any, text: str) -> None:
    for chunk in _MD_INLINE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            par.add_run(chunk[2:-2]).bold = True
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            r = par.add_run(chunk[1:-1])
            r.font.name = "Consolas"
        elif chunk.startswith("["):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", chunk)
            par.add_run(m.group(1) if m else chunk)
        else:
            par.add_run(chunk)


def _md_to_docx(d: Any, md: str) -> None:
    """Простой перенос Markdown-отчёта в Word: заголовки, абзацы, списки, таблицы, цитаты, код."""
    lines = md.splitlines()
    i = 0
    in_code = False
    code: list[str] = []
    while i < len(lines):
        s = lines[i]
        st = s.strip()
        if st.startswith("```"):
            if in_code:
                p = d.add_paragraph()
                r = p.add_run("\n".join(code))
                r.font.name = "Consolas"
                code, in_code = [], False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code.append(s)
            i += 1
            continue
        if not st or re.fullmatch(r"-{3,}|\*{3,}", st) or st.startswith("<!--") or st.startswith("<"):
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            d.add_heading(re.sub(r"[*`]", "", m.group(2)).strip(), level=min(len(m.group(1)), 4))
            i += 1
            continue
        if st.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                t = d.add_table(rows=len(rows), cols=ncol)
                t.style = "Table Grid"
                # t.cell() каждый раз строит сетку всей таблицы — на длинном отчёте это минуты; сетку берём один раз
                # (таблица только что создана, объединённых ячеек нет — индекс ri * ncol + ci точный)
                grid = list(t._cells)
                if len(grid) != len(rows) * ncol:
                    grid = [t.cell(ri, ci) for ri in range(len(rows)) for ci in range(ncol)]
                for ri, row in enumerate(rows):
                    for ci in range(ncol):
                        cell = grid[ri * ncol + ci]
                        cell.text = ""
                        _add_inline(cell.paragraphs[0], row[ci] if ci < len(row) else "")
                        if ri == 0:
                            for r in cell.paragraphs[0].runs:
                                r.bold = True
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            style = "List Number" if m.group(2)[0].isdigit() else "List Bullet"
            p = d.add_paragraph(style=style)
            _add_inline(p, m.group(3))
            i += 1
            continue
        if st.startswith(">"):
            p = d.add_paragraph(style="Intense Quote" if "Intense Quote" in [x.name for x in d.styles] else None)
            _add_inline(p, st.lstrip("> ").strip())
            i += 1
            continue
        p = d.add_paragraph()
        _add_inline(p, st)
        i += 1


def _report_to_docx(d: Any, report: dict) -> None:
    doc = report.get("document") or {}
    d.add_heading(f"Ревью требований: {doc.get('title') or doc.get('file') or ''}".strip(), level=0)
    v = report.get("verdict") or {}
    if v:
        d.add_paragraph(f"Разработка: {VERDICT_RU.get(str(v.get('development')), '—')} · "
                        f"Тестирование: {VERDICT_RU.get(str(v.get('testing')), '—')}")
        if v.get("summary"):
            d.add_paragraph(str(v["summary"]))
    fs = findings_of(report)
    counts = {k: sum(1 for f in fs if f.get("severity") == k) for k in SEV_ORDER}
    d.add_paragraph(f"Дефектов: {len(fs)} (критичных {counts['critical']}, существенных {counts['major']}, "
                    f"незначительных {counts['minor']}).")
    d.add_heading("Дефекты", level=1)
    for f in fs:
        d.add_heading(f"{f.get('id', '')}. {_one_line(f.get('title'))}", level=2)
        meta = [SEVERITY_RU.get(str(f.get("severity")), str(f.get("severity") or ""))]
        if f.get("criterion"):
            meta.append(criterion_label(f["criterion"]))
        if f.get("requirement_ids"):
            meta.append("Требования: " + ", ".join(f["requirement_ids"]))
        d.add_paragraph(" · ".join(m for m in meta if m))
        for e in f.get("evidence") or []:
            if isinstance(e, dict) and _verified(e):
                p = d.add_paragraph(style="List Bullet")
                p.add_run(f"«{_one_line(e.get('quote'))}»").italic = True
                p.add_run(f" — {place_of(e)}")
        for label, key in (("Проблема", "problem"), ("Сценарий", "scenario"), ("Последствия", "impact"),
                           ("Что сделать", "recommendation"), ("Формулировка", "rewrite"), ("Вопрос", "question")):
            if str(f.get(key) or "").strip():
                p = d.add_paragraph()
                p.add_run(f"{label}: ").bold = True
                p.add_run(str(f[key]).strip())
    qs = [q for q in report.get("questions") or [] if isinstance(q, dict)]
    if qs:
        d.add_heading("Вопросы владельцу", level=1)
        for q in qs:
            p = d.add_paragraph(style="List Number")
            p.add_run(f"{q.get('id', '')} ").bold = True
            p.add_run(_one_line(q.get("question")))
            for o in q.get("options") or []:
                d.add_paragraph(_one_line(o), style="List Bullet 2")


# --------------------------------------------------------------------------- PDF
_COLORS = {"critical": (0.96, 0.42, 0.42), "major": (1.0, 0.72, 0.30), "minor": (1.0, 0.93, 0.35)}


def write_pdf(report: dict, view: dict, input_path: str | Path, out_base: str | Path) -> dict:
    inp = Path(input_path)
    base = Path(out_base)
    suf = inp.suffix.lower()
    if suf == ".pdf":
        return annotate_pdf(report, view, inp, base.with_name(base.name + SUFFIX["pdf_annotated"]))
    if suf in (".md", ".markdown", ".txt"):
        out = base.with_name(base.name + SUFFIX["pdf"])
        try:
            from bcc_review.exports import pdf as pdf1
            res = pdf1.export_pdf(to_v1_report(report, view, inp), inp, out)
            placed = getattr(res, "placements", None) or []
            return _res("pdf", "written", Path(res.output_path),
                        f"PDF-версия документа с выделениями: {_n(len(placed), 'место', 'места', 'мест')}",
                        anchored=len(placed),
                        total=len(report.get("findings") or []))
        except Exception as exc:  # noqa: BLE001
            return _res("pdf", "failed", None, f"PDF-версия Markdown не построена: {type(exc).__name__}: {exc}")
    return _res("pdf", "skipped", None, "PDF с выделениями строится для входа PDF или Markdown; "
                "для этого входа используйте HTML- или Word-отчёт")


def _note_text(f: dict, report: dict) -> str:
    sev = SEVERITY_RU.get(str(f.get("severity")), str(f.get("severity") or ""))
    out = [f"[{f.get('id', '')}] {sev}", _one_line(f.get("title"))]
    for label, key in (("Проблема", "problem"), ("Сценарий", "scenario"), ("Последствия", "impact"),
                       ("Что сделать", "recommendation")):
        if str(f.get(key) or "").strip():
            out.append(f"{label}: {str(f[key]).strip()}")
    qs = _questions_for(report, str(f.get("id") or ""))
    q = _one_line(qs[0].get("question")) if qs else _one_line(f.get("question"))
    if q:
        out.append(f"Вопрос: {q}")
    if f.get("criterion"):
        out.append(f"Критерий: {criterion_label(f['criterion'])}")
    return "\n".join(out)


def _search_variants(quote: str) -> list[list[str]]:
    """Варианты поиска цитаты на странице: целиком; части через « … »; ячейки таблицы через « | »."""
    q = quote.strip()
    out = [[q]]
    if " … " in q:
        out.append([p.strip() for p in q.split(" … ") if len(p.strip()) >= 3])
    if " | " in q:
        out.append([p.strip() for p in q.split(" | ") if len(p.strip()) >= 2])
    return out


def _block_rects(doc1: dict) -> dict[str, tuple[int, list[float]]]:
    out = {}
    for b in doc1.get("blocks") or []:
        loc = b.get("loc") or {}
        if loc.get("page") and loc.get("bbox"):
            out[b["id"]] = (int(loc["page"]), list(loc["bbox"]))
    return out


def annotate_pdf(report: dict, view: dict, input_path: Path, output_path: Path) -> dict:
    """Копия исходного PDF с выделениями цитат и всплывающими примечаниями."""
    import pymupdf
    from bcc_review.v2 import docview

    if output_path.resolve() == input_path.resolve():
        raise ValueError("копия не может перезаписать исходный файл")
    try:
        rects = _block_rects(_v1_document(input_path))
    except Exception:  # noqa: BLE001 — без рамок блоков ищем по всей странице
        rects = {}
    doc = pymupdf.open(str(input_path))
    findings = findings_of(report)
    anchored: set[str] = set()
    places = 0
    missed: list[str] = []
    for f in findings:
        fid = str(f.get("id") or "")
        note = _note_text(f, report)
        color = _COLORS.get(str(f.get("severity")), _COLORS["minor"])
        for ev in f.get("evidence") or []:
            if not isinstance(ev, dict) or not _verified(ev):
                continue
            n = ev.get("line_start") or ev.get("line")
            ln = docview.line(view, int(n)) if n else None
            page_no = ev.get("page") or (ln or {}).get("page")
            if not page_no or not 1 <= int(page_no) <= doc.page_count:
                missed.append(fid)
                continue
            page = doc[int(page_no) - 1]
            bbox = _area(view, rects, int(n), int(ev.get("line_end") or n), int(page_no)) if n else None
            quads = _find_quads(page, str(ev.get("quote") or ""), bbox) or \
                _word_quads(page, str(ev.get("quote") or ""), bbox)
            if not quads:
                missed.append(fid)
                continue
            a = page.add_highlight_annot(quads=quads)
            a.set_colors(stroke=color)
            a.set_opacity(0.45)  # полупрозрачно: текст под выделением читается, наложения не чернеют
            a.set_info(title=AUTHOR, subject=f"{fid} · {SEVERITY_RU.get(str(f.get('severity')), '')}", content=note)
            a.set_name(f"bcc-{fid}-{places}")
            a.update()
            anchored.add(fid)
            places += 1
    if doc.page_count:
        _summary_note(doc[0], report, findings, anchored)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path), garbage=1, deflate=True)
    doc.close()
    # проверка: копия открывается, выделений столько, сколько поставили
    with pymupdf.open(str(output_path)) as chk:
        hl = sum(1 for p in chk for x in p.annots() if x.type[0] == pymupdf.PDF_ANNOT_HIGHLIGHT)
    if hl != places:
        return _res("pdf", "failed", None, f"после записи найдено {hl} выделений вместо {places}")
    msg = (f"PDF с выделениями: отмечено {len(anchored)} из {_n(len(findings), 'дефекта', 'дефектов', 'дефектов')}"
           f" ({_n(places, 'место', 'места', 'мест')})")
    if missed:
        msg += f"; без места на странице: {', '.join(sorted(set(missed) - anchored)) or 'нет'}"
    return _res("pdf", "written", output_path, msg, anchored=len(anchored), total=len(findings), places=places)


def _area(view: dict, rects: dict, a: int, b: int, page_no: int) -> list[float] | None:
    """Объединённая рамка блоков строк a..b на странице (цитата может занимать несколько блоков)."""
    from bcc_review.v2 import docview
    box = None
    for n in range(a, max(a, b) + 1):
        ln = docview.line(view, n)
        pr = rects.get((ln or {}).get("block_id", ""))
        if not pr or pr[0] != page_no:
            continue
        r = pr[1]
        box = list(r) if box is None else [min(box[0], r[0]), min(box[1], r[1]), max(box[2], r[2]), max(box[3], r[3])]
    return box


def _find_quads(page: Any, quote: str, bbox: list[float] | None) -> list:
    import pymupdf
    if not quote.strip():
        return []
    area = pymupdf.Rect(bbox) + (-2, -2, 2, 2) if bbox else None

    def inside(h: Any) -> bool:
        r = h.rect
        return area is not None and (r & area).get_area() >= 0.5 * max(r.get_area(), 1e-6)

    for vi, variant in enumerate(_search_variants(quote)):
        found: list = []
        prev_x = None
        for piece in variant:
            hits = page.search_for(piece, quads=True)
            if not hits and len(piece) > 60:
                hits = page.search_for(piece[:60], quads=True)
            if not hits:
                found = []
                break
            ins = [h for h in hits if inside(h)]
            if vi == 0 and ins:
                hits = ins  # цитата целиком: все части переноса внутри блока
            elif ins:
                # часть цитаты (ячейка, фрагмент): одно вхождение внутри блока, ячейки — слева направо;
                # перенос внутри ячейки даёт несколько четырёхугольников — берём их все
                cand = [h for h in ins if prev_x is None or h.rect.x0 >= prev_x - 1] or ins
                first = cand[0]
                hits = [first] + [h for h in cand[1:] if abs(h.rect.x0 - first.rect.x0) < 4
                                  and 0 < h.rect.y0 - first.rect.y0 <= 2.6 * max(first.rect.height, 1)]
                prev_x = first.rect.x1
            elif area is not None:
                hits = sorted(hits, key=lambda h: abs(h.rect.y0 - area.y0))[:1]
            else:
                hits = hits[:1]
            found.extend(hits)
        if found:
            return found
    return []


def _word_quads(page: Any, quote: str, bbox: list[float] | None) -> list:
    """Запасной поиск по словам: фрагменты строки в PDF могут лежать не по порядку (другой шрифт у цифр и точек),
    и search_for не находит фразу. Слова в рамке блока раскладываются по строкам слева направо и сравниваются
    с цитатой без пробелов. Не нашлось — выделяется весь блок (место дефекта всё равно видно)."""
    import pymupdf
    from bcc_review.v2.quotes import normalize
    area = pymupdf.Rect(bbox) + (-2, -2, 2, 2) if bbox else None
    words = page.get_text("words", clip=area) if area is not None else page.get_text("words")
    if not words:
        return []
    words = sorted(words, key=lambda w: (w[1] + w[3]) / 2)
    lines: list[list] = []
    for w in words:
        mid, h = (w[1] + w[3]) / 2, w[3] - w[1]
        if lines and abs(mid - lines[-1][0]) <= max(h, 1) * 0.5:
            lines[-1][1].append(w)
        else:
            lines.append([mid, [w]])
    ordered = [w for _, ws in lines for w in sorted(ws, key=lambda w: w[0])]
    chars, owner = [], []
    for k, w in enumerate(ordered):
        t = normalize(w[4]).replace(" ", "")
        chars.append(t)
        owner += [k] * len(t)
    text = "".join(chars)
    first = quote.split(" … ")[0]
    needle = normalize(first).replace(" ", "").strip('".,;:')
    pos = text.find(needle) if len(needle) >= 4 else -1
    if pos >= 0:
        sel = ordered[owner[pos]:owner[pos + len(needle) - 1] + 1]
    elif area is not None:
        sel = ordered
    else:
        return []
    return [pymupdf.Rect(w[:4]).quad for w in sel]


def _summary_note(page: Any, report: dict, findings: list[dict], anchored: set[str]) -> None:
    import pymupdf
    v = report.get("verdict") or {}
    counts = {k: sum(1 for f in findings if f.get("severity") == k) for k in SEV_ORDER}
    lines = ["Сводка ревью требований (BCC Review)"]
    if v:
        lines.append(f"Разработка: {VERDICT_RU.get(str(v.get('development')), '—')} · "
                     f"Тестирование: {VERDICT_RU.get(str(v.get('testing')), '—')}")
        if v.get("summary"):
            lines.append(str(v["summary"]))
    lines.append(f"Дефектов: {len(findings)} (критичных {counts['critical']}, существенных {counts['major']}, "
                 f"незначительных {counts['minor']}); отмечено в тексте: {len(anchored)}.")
    loose = [str(f.get("id")) for f in findings if str(f.get("id")) not in anchored]
    if loose:
        lines.append("Без места в тексте: " + ", ".join(loose[:30]) + ".")
    lines.append("Подробности, сценарии и вопросы — в отчёте ревью.")
    a = page.add_text_annot(pymupdf.Point(12, 12), "\n".join(lines), icon="Note")
    a.set_info(title=AUTHOR, subject="Сводка ревью")
    a.set_name("bcc-summary")
    a.update()
