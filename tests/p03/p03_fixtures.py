"""Детерминированные DOCX-фикстуры и отчёты контракта v1 для тестов №03."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

import docx
from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt

from bcc_review.contracts import evidence_errors, validate
from bcc_review.readers.docx import Document

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
FIXTURES = Path(__file__).parent / "fixtures"
CASE_DOCX = FIXTURES / "case_requirements.docx"

PHRASE = "порог от 1 000 до 1 000 000 ₸ включительно"


def _append_block(d: Any, el: Any) -> Any:
    body = d.element.body
    sect = body.find(qn("w:sectPr"))
    if sect is not None:
        sect.addprevious(el)
    else:
        body.append(el)
    return el


def xml_paragraph(d: Any, inner: str) -> Any:
    return _append_block(d, parse_xml(f"<w:p {nsdecls('w')}>{inner}</w:p>"))


def t(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def add_footnotes_part(d: Any, notes: dict[int, str]) -> None:
    """Часть word/footnotes.xml со стандартными разделителями и обычными сносками."""
    body = ('<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r>'
            '</w:p></w:footnote>')
    for nid, text in notes.items():
        body += (f'<w:footnote w:id="{nid}"><w:p><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                 f'<w:footnoteRef/></w:r>{t(" " + text)}</w:p></w:footnote>')
    el = parse_xml(f'<w:footnotes {nsdecls("w")}>{body}</w:footnotes>')
    part = XmlPart(PackURI("/word/footnotes.xml"), CT.WML_FOOTNOTES, el, d.part.package)
    d.part.relate_to(part, RT.FOOTNOTES)


# --------------------------------------------------------------- фикстуры


def bold_quote_doc(path: Path) -> Path:
    """Цитата «Ф-2. Месяц определяется» идёт через жирный и обычный run."""
    d = docx.Document()
    d.add_heading("Функциональные требования", 1)
    p = d.add_paragraph()
    r = p.add_run("Ф-2. ")
    r.bold = True
    p.add_run("Месяц определяется по дате совершения покупки в Алматы.")
    d.add_paragraph("Ф-3. Максимум один push за календарный месяц.")
    d.save(path)
    return path


def repeated_phrase_doc(path: Path) -> Path:
    """Одна и та же фраза в абзаце и в ячейке; на абзаце уже есть комментарий."""
    d = docx.Document()
    d.add_heading("Ф-1. Порог", 1)
    p = d.add_paragraph(f"Держатель активной карты KZT задаёт {PHRASE}.")
    d.add_comment(p.runs, text="Старый комментарий: уточнить валюту.", author="Аналитик", initials="АН")
    table = d.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "Параметр"
    table.cell(0, 1).text = "Правило"
    table.cell(1, 0).text = "amount"
    table.cell(1, 1).text = f"Клиент задаёт {PHRASE}."
    d.add_paragraph("Конец раздела.")
    d.save(path)
    return path


CYR_TEXT = (
    "🙂 Ф-2. Месяц определяется по дате совершения покупки в Алматы; "
    "возврат уменьшает расходы месяца исходной покупки, переводы исключаются."
)


def cyrillic_doc(path: Path) -> Path:
    """Кириллица, символ вне BMP до цитат и существующий комментарий в том же абзаце."""
    d = docx.Document()
    d.add_heading("Учёт расходов", 1)
    p = d.add_paragraph()
    a, b, c = CYR_TEXT.partition("возврат уменьшает")
    p.add_run(a)
    old = p.add_run(b)
    old.italic = True
    p.add_run(c)
    d.add_comment(old, text="Комментарий заказчика: а частичный возврат?", author="Заказчик", initials="ЗК")
    d.save(path)
    return path


def rich_doc(path: Path) -> Path:
    """Сложные элементы: sdt, гиперссылка, поля, исправления, символ, вложенная и
    объединённая таблицы, колонтитул, текстовое поле, ручной разрыв строки."""
    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "Конфиденциально"
    d.add_heading("Документ", 0)
    d.add_heading("1. Общие сведения", 1)
    xml_paragraph(d, t("Текст до ") + '<w:hyperlink w:anchor="x"><w:r><w:t>гиперссылки</w:t></w:r></w:hyperlink>' + t(" и после."))
    _append_block(d, parse_xml(
        f'<w:sdt {nsdecls("w")}><w:sdtPr><w:alias w:val="Поле"/></w:sdtPr><w:sdtContent>'
        f'<w:p>{t("Текст в элементе управления")}</w:p></w:sdtContent></w:sdt>'))
    xml_paragraph(d, t("См. ")
                  + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                  + '<w:r><w:instrText xml:space="preserve"> REF _Ref1 \\h </w:instrText></w:r>'
                  + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                  + t("Ф-3")
                  + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                  + t(" и критерий 2."))
    xml_paragraph(d, t("Порог ")
                  + '<w:del w:id="901" w:author="A" w:date="2026-01-01T00:00:00Z"><w:r><w:delText>старый </w:delText></w:r></w:del>'
                  + '<w:ins w:id="902" w:author="A" w:date="2026-01-01T00:00:00Z"><w:r><w:t>новый</w:t></w:r></w:ins>'
                  + t(" сохраняется."))
    xml_paragraph(d, '<w:r><w:t xml:space="preserve">Галочка </w:t><w:sym w:font="Wingdings" w:char="F0FC"/>'
                     '<w:t xml:space="preserve"> отмечена</w:t></w:r>')
    xml_paragraph(d, '<w:r><w:t>Первая строка</w:t><w:br/><w:t>вторая строка</w:t><w:tab/><w:t>после табуляции</w:t></w:r>')
    xml_paragraph(d, t("Перед рамкой ") + '<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
                     '<v:textbox><w:txbxContent><w:p><w:r><w:t>Текст в рамке</w:t></w:r></w:p></w:txbxContent>'
                     '</v:textbox></v:shape></w:pict></w:r>')
    table = d.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    for i, h in enumerate(["Поле", "Тип", "Описание"]):
        table.cell(0, i).text = h
    table.cell(1, 0).text = "cardId"
    table.cell(1, 1).text = "string"
    table.cell(1, 2).text = "Идентификатор карты"
    merged = table.cell(2, 0).merge(table.cell(2, 1))
    merged.text = "amount, integer"
    table.cell(2, 2).text = "Порог в тенге"
    table.cell(2, 2).add_paragraph("Вторая строка ячейки")
    vt = d.add_table(rows=3, cols=2)
    vt.cell(0, 0).text = "Статус"
    vt.cell(0, 1).text = "Тело"
    top = vt.cell(1, 0).merge(vt.cell(2, 0))
    top.text = "400"
    vt.cell(1, 1).text = "Некорректный запрос"
    vt.cell(2, 1).text = "Проверьте сумму"
    outer = d.add_table(rows=1, cols=2)
    outer.cell(0, 0).text = "Внешняя ячейка"
    inner = outer.cell(0, 1).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Вложенная ячейка"
    d.add_paragraph("Шаг один", style="List Number")
    d.add_paragraph("Шаг два", style="List Number")
    xml_paragraph(d, t("Порог хранится в тенге") + '<w:r><w:footnoteReference w:id="1"/></w:r>' + t(" без копеек."))
    add_footnotes_part(d, {1: "Курс пересчёта тиынов не определён."})
    xml_paragraph(d, t("Условие ") + f'<m:oMath xmlns:m="{M}"><m:r><m:t>1000≤x≤1000000</m:t></m:r></m:oMath>'
                  + t(" проверяется на сервере."))
    xml_paragraph(d, '<w:r><w:lastRenderedPageBreak/><w:t>На второй странице</w:t></w:r>')
    d.save(path)
    return path


TWIN = "порог от 1 000 до 1 000 000 ₸"
TWIN_URL = "https://bank.example/limits"


def twin_phrase_doc(path: Path, *, orphan_markers: bool = False, footnote: bool = False,
                    heading: bool = False) -> Path:
    """Одна фраза ``TWIN`` в обычном абзаце и в ячейке таблицы.

    * в абзаце на фразе уже стоит комментарий автора;
    * в ячейке фраза разрезана между жирным run и внешней гиперссылкой, а перед
      ней стоит удалённый при рецензировании текст «порог от 500 » -- соседняя
      почти-копия, которой нет в текущей версии;
    * ``orphan_markers``: вокруг копии в абзаце остались маркеры commentRange
      с ``w:id`` следующего свободного номера, но без записи в comments.xml
      (так бывает после удаления комментария внешним инструментом);
    * ``footnote``: в ячейке после фразы стоит знак сноски с текстом про ту же фразу;
    * ``heading``: перед абзацем есть заголовок (по умолчанию нет -- первым блоком
      документа идёт абзац с первой копией фразы).
    """
    d = docx.Document()
    if heading:
        d.add_heading("Ф-1. Порог уведомления", 1)
    p = d.add_paragraph("Клиент задаёт ")
    target = p.add_run(TWIN)
    p.add_run(" включительно.")
    d.add_comment(target, text="Автор: границы согласованы с бизнесом.", author="Автор ТЗ", initials="АТ")
    if orphan_markers:
        start = parse_xml(f'<w:commentRangeStart {nsdecls("w")} w:id="1"/>')
        end = parse_xml(f'<w:commentRangeEnd {nsdecls("w")} w:id="1"/>')
        target._r.addprevious(start)
        p._p.append(end)
    table = d.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text, table.cell(0, 1).text = "Параметр", "Правило"
    table.cell(1, 0).text = "amount"
    rid = d.part.relate_to(TWIN_URL, RT.HYPERLINK, is_external=True)
    cell_p = table.cell(1, 1).paragraphs[0]._p
    note = '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteReference w:id="1"/></w:r>' \
        if footnote else ""
    for el in list(parse_xml(  # list(): перенос детей при обходе пропускал бы элементы
        f'<w:p {nsdecls("w", "r")}>'
        '<w:del w:id="901" w:author="Автор ТЗ" w:date="2026-11-01T10:00:00Z"><w:r>'
        '<w:delText xml:space="preserve">порог от 500 </w:delText></w:r></w:del>'
        '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">порог от 1 000</w:t></w:r>'
        f'<w:hyperlink r:id="{rid}" w:history="1"><w:r><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/>'
        '</w:rPr><w:t xml:space="preserve"> до 1 000 000 ₸</w:t></w:r></w:hyperlink>'
        f'{note}<w:r><w:t xml:space="preserve"> включительно.</w:t></w:r></w:p>'
    )):
        cell_p.append(el)
    if footnote:
        add_footnotes_part(d, {1: f"Сумма {TWIN} указана без учёта комиссий."})
    d.add_paragraph("Конец раздела.")
    d.save(path)
    return path


AMOUNT = "50 000 ₸"
AMOUNTS_HEADING = "3. Уведомление о расходах"
AMOUNTS_USER_COMMENT = "Пользователь: лимит push совпадает с порогом? Проверить с бизнесом."


def amounts_doc(path: Path, *, user_comment: bool = False) -> Path:
    """Сумма ``AMOUNT`` один раз в основном тексте и дважды в таблице.

    * заголовок «3. Уведомление о расходах» (Heading 1) и автонумерованный список 1–3;
      сумма стоит в пункте 2;
    * таблица «Параметр | Значение | Примечание» с шапкой ``tblHeader``: в строке 2
      сумма разбита на жирный run «50 000» и курсивный run « ₸», в строке 3 -- один run;
    * ``user_comment``: на сумме в строке 3 уже стоит комментарий пользователя.
    """
    d = docx.Document()
    d.add_heading(AMOUNTS_HEADING, 1)
    d.add_paragraph("Клиент задаёт порог уведомления в приложении.", style="List Number")
    p = d.add_paragraph(style="List Number")
    p.add_run("Push отправляется, когда расходы за месяц достигают ")
    p.add_run(AMOUNT)
    p.add_run(".")
    d.add_paragraph("Порог хранится в тенге без тиынов.", style="List Number")
    table = d.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    for i, h in enumerate(("Параметр", "Значение", "Примечание")):
        table.cell(0, i).text = h
    table.rows[0]._tr.get_or_add_trPr().append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    table.cell(1, 0).text = "Порог по умолчанию"
    split = table.cell(1, 1).paragraphs[0]
    split.add_run("50 000").bold = True
    split.add_run(" ₸").italic = True
    table.cell(1, 2).text = "задаётся при выпуске карты"
    table.cell(2, 0).text = "Лимит суммы push"
    whole = table.cell(2, 1).paragraphs[0].add_run(AMOUNT)
    table.cell(2, 2).text = "один push в месяц"
    d.add_paragraph("Итоговые значения согласует владелец продукта.")
    if user_comment:
        d.add_comment(whole, text=AMOUNTS_USER_COMMENT, author="Аналитик банка", initials="АБ")
    d.save(path)
    return path


def amounts_mock_script(doc: Document) -> dict[str, Any]:
    """Записанные ответы модели для движка (провайдер mock) по ``amounts_doc``.

    Инвентарь: пункты 1–3 и две строки таблицы; набор: замечание на сумму в строке 2,
    замечание на ту же сумму в строке 3, пропуск без цитаты и выдуманная цитата
    «60 000 ₸». Последние два движок отсекает до экспорта (report.rejected).
    """
    ref = {b.loc["ref"]: b.id for b in doc.blocks}
    r2, r3 = ref["t1.r2"], ref["t1.r3"]

    def issue(title, quotes, cause, kind="ambiguity", criterion="unambiguous", severity="major", req=("R-004",)):
        return {"kind": kind, "criterion": criterion, "severity": severity, "title": title,
                "impact": "Разработчик и тестировщик поймут сумму по-разному.", "blocked_decision": "Какую сумму проверять",
                "recommendation": "Сослаться на пункт 2.", "quotes": quotes, "req_ids": list(req),
                "cause": {"object": cause, "condition": "настройка", "outcomes": ["a", "b"]},
                "inspected_block_ids": [r2, r3]}

    script = {
        "inventory": {"items": [
            {"source_id": "1", "kind": "functional", "text": "Клиент задаёт порог",
             "evidence": [{"block_id": ref["p2"], "quote": "Клиент задаёт порог уведомления"}]},
            {"source_id": "2", "kind": "functional", "text": "Push при сумме",
             "evidence": [{"block_id": ref["p3"], "quote": AMOUNT}]},
            {"source_id": "3", "kind": "data", "text": "Порог в тенге",
             "evidence": [{"block_id": ref["p4"], "quote": "Порог хранится в тенге"}]},
            {"source_id": None, "kind": "contract", "text": "Порог по умолчанию", "evidence": [{"block_id": r2, "quote": AMOUNT}]},
            {"source_id": None, "kind": "contract", "text": "Лимит суммы push", "evidence": [{"block_id": r3, "quote": AMOUNT}]}],
            "excluded": [{"category": "structure", "reason": "заголовок и шапка", "block_ids": [ref["p1"], ref["t1.r1"]]},
                         {"category": "other", "reason": "организационная фраза", "block_ids": [ref["p5"]]}],
            "facts": [], "done": True},
        "individual": {"requirements": []},
        "cross": {"conflicts": [], "coverage": [], "facts": [], "issues": [
            issue("Порог по умолчанию повторяет сумму пункта 2", [{"block_id": r2, "quote": AMOUNT}], "порог по умолчанию"),
            issue("Лимит суммы push совпадает с порогом без объяснения", [{"block_id": r3, "quote": AMOUNT}],
                  "лимит суммы push", kind="duplicate", criterion="necessary", severity="minor", req=("R-005",)),
            issue("Нет правила для суммы ниже 1 000 ₸", [], "сумма ниже 1 000 ₸", kind="omission",
                  criterion="set_complete", req=("R-002",)),
            issue("Опора, которой нет в документе", [{"block_id": r3, "quote": "60 000 ₸"}], "лимит 60 000 ₸",
                  severity="minor", req=("R-005",))]},
        "verify_meaning": {"__verdicts__": "confirmed"},
    }
    return script


# --------------------------------------------------------------- отчёт


def block_id(doc: Document, predicate: Callable[[Any], bool]) -> str:
    ids = [b.id for b in doc.blocks if predicate(b)]
    assert len(ids) == 1, f"ожидался один блок, найдено {ids}"
    return ids[0]


def ref_id(doc: Document, ref: str) -> str:
    return doc.by_ref(ref).id


def evidence(doc: Document, bid: str, quote: str, occurrence: int = 0) -> dict[str, Any]:
    text = doc.block(bid).text
    pos = -1
    for _ in range(occurrence + 1):
        pos = text.index(quote, pos + 1)
    return {"block_id": bid, "start": pos, "end": pos + len(quote), "quote": quote}


def finding(fid: str, ev: list[dict[str, Any]], *, severity: str = "critical", status: str = "confirmed",
            title: str = "Замечание", impact: str = "Разработчик и тестировщик поймут правило по-разному.",
            **extra: Any) -> dict[str, Any]:
    """Finding по контракту v1 (все обязательные поля)."""
    f = {
        "id": fid, "scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous",
        "severity": severity, "title": title, "impact": impact, "req_ids": [], "hints": [],
        "evidence": ev, "status": status, "anchor_status": "supported",
        "meaning_status": "confirmed" if status == "confirmed" else "uncertain",
        "blocks": ["development", "testing"] if severity == "critical" else ["testing"],
        "witness": None, "inspected_block_ids": [], "merged_from": [], "cause": None, "notes": [],
    }
    if severity == "critical":
        f["blocked_decision"] = "Реализация правила в коде и ожидаемый результат теста"
    f.update(extra)
    return f


def make_report(doc: Document, findings: list[dict[str, Any]], *, questions: list[dict[str, Any]] | None = None,
                check: bool = True) -> dict[str, Any]:
    """Report по контракту v1. При ``check`` проверяется схемой и ``evidence_errors``."""
    reqs = {}
    for f in findings:
        for rid in f.get("req_ids", []):
            ev = (f.get("evidence") or [{}])[0]
            b = doc.block(ev["block_id"]) if ev.get("block_id") in {x.id for x in doc.blocks} else doc.blocks[0]
            reqs.setdefault(rid, {"id": rid, "source_id": None, "text": b.text, "block_ids": [b.id], "evidence": [],
                                  "review_status": "reviewed", "review_reason": None})
    reportable = [f for f in findings if f["status"] in ("confirmed", "needs_review")]
    crit = [f["id"] for f in reportable if f["severity"] == "critical"]
    readiness = {"status": "not_ready" if crit else "ready", "reasons": ["Есть критичные замечания"] if crit else [],
                 "finding_ids": crit}
    report = {
        "schema_version": "1.0",
        "run": {
            "run_id": "p03-test", "parent_run_id": None, "source_sha256": doc.id, "source_name": doc.source_name,
            "agent_version": "0.1.0", "agent_commit": None, "provider": "mock", "model": "mock-1",
            "mode": "mock", "status": "complete", "status_reasons": [],
            "started_at": "2026-11-26T00:00:00Z", "finished_at": "2026-11-26T00:00:01Z",
            "calls": {"physical": 0, "cache_hits": 0, "failed": 0, "retries": 0},
            "tokens": {"input": 0, "output": 0}, "stages": [], "incomplete_stages": [],
            "evidence_audit": {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": "тест №03"},
        },
        "document": doc.to_dict(),
        "requirements": list(reqs.values()), "checks": [], "findings": findings, "facts": [], "coverage": [],
        "questions": questions or [], "checklist": [], "test_cases": [], "decisions": [], "diff": None,
        "verdict": {"development": readiness, "testing": dict(readiness),
                    "first_actions": [{"order": 1, "action": "Снять противоречие Ф-3 и Ф-4", "finding_ids": crit}]
                    if crit else []},
        "summary": {
            "requirements": len(reqs), "reviewed_requirements": len(reqs), "findings": len(reportable),
            "by_severity": {k: sum(f["severity"] == k for f in reportable) for k in ("critical", "major", "minor")},
            "by_status": {k: sum(f["status"] == k for f in reportable) for k in ("confirmed", "needs_review")},
            "critical_ids": crit, "checks": {"pass": 0, "issue": 0, "unknown": 0, "na": 0},
        },
        "warnings": [],
    }
    if check:
        validate(report)
        assert evidence_errors(report) == []
    return report


# ------------------------------------------------------------- OOXML-проверки


def zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def zip_text(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def range_text(path: Path, cid: int) -> str:
    """Текст между w:commentRangeStart и w:commentRangeEnd с этим id (как видит Word)."""
    d = docx.Document(str(path))
    inside = False
    out: list[str] = []
    seen_p = False
    for el in d.element.body.iter():
        tag = el.tag
        if tag == qn("w:commentRangeStart") and el.get(qn("w:id")) == str(cid):
            inside = True
            continue
        if tag == qn("w:commentRangeEnd") and el.get(qn("w:id")) == str(cid):
            break
        if not inside:
            continue
        if tag == qn("w:p"):
            if seen_p or out:
                out.append("\n")
            seen_p = True
        elif tag in (qn("w:t"), "{%s}t" % M):
            out.append(el.text or "")
        elif tag == qn("w:tab"):
            out.append("\t")
        elif tag in (qn("w:br"), qn("w:cr")):
            out.append("\n")
    return "".join(out)


def markers(path: Path) -> dict[int, dict[str, int]]:
    d = docx.Document(str(path))
    res: dict[int, dict[str, int]] = {}
    tags = {qn("w:commentRangeStart"): "start", qn("w:commentRangeEnd"): "end", qn("w:commentReference"): "ref"}
    for el in d.element.body.iter(*tags):
        cid = int(el.get(qn("w:id")))
        res.setdefault(cid, {"start": 0, "end": 0, "ref": 0})[tags[el.tag]] += 1
    return res


def comments(path: Path) -> dict[int, tuple[str, str]]:
    d = docx.Document(str(path))
    return {c.comment_id: (c.author, c.text) for c in d.comments}


def start_marker_ancestors(path: Path, cid: int) -> list[str]:
    d = docx.Document(str(path))
    for el in d.element.body.iter(qn("w:commentRangeStart")):
        if el.get(qn("w:id")) == str(cid):
            out = []
            a = el.getparent()
            while a is not None:
                out.append(a.tag.rsplit("}", 1)[-1])
                a = a.getparent()
            return out
    raise AssertionError(f"нет commentRangeStart {cid}")


# ---------------------------------------------------- DOCX-версия кейса BCC-HUB


_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def _add_inline(p: Any, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            p.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1])
            r.font.name = "Consolas"
        else:
            p.add_run(part)


def _set_num(p: Any, num_id: str) -> None:
    p._p.get_or_add_pPr().append(parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'))


def _restart_numbering(d: Any) -> str:
    """Новый список «1, 2, 3»: свой w:num со startOverride на базе стиля List Number."""
    numbering = d.part.numbering_part.element
    style = d.styles["List Number"].element
    num_id = style.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}").get(qn("w:val"))
    base = [n for n in numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == num_id][0]
    abstract = base.find(qn("w:abstractNumId")).get(qn("w:val"))
    new_id = str(max(int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))) + 1)
    numbering.append(parse_xml(
        f'<w:num {nsdecls("w")} w:numId="{new_id}"><w:abstractNumId w:val="{abstract}"/>'
        f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'))
    return new_id


def build_case_docx(md_path: Path, out_path: Path) -> Path:
    """Перевести requirements.md кейса в DOCX: заголовки стилями Word, таблицы с
    шапкой (tblHeader), списки с автонумерацией, жирные run, код моноширинным,
    «два пробела в конце строки» -- разрыв w:br внутри абзаца."""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    d = docx.Document()
    d.core_properties.title = "Уведомление о расходах по карте"
    d.core_properties.author = "BCC-HUB (учебный кейс)"
    i = 0
    para: Any = None
    prev_numbered = False
    list_num = None
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                r = d.add_paragraph().add_run(lines[i])
                r.font.name = "Consolas"
                r.font.size = Pt(9)
                i += 1
            i += 1
            para = None
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            table = d.add_table(rows=len(rows), cols=len(rows[0]))
            table.style = "Table Grid"
            for ri, cells in enumerate(rows):
                for ci, c in enumerate(cells):
                    cp = table.cell(ri, ci).paragraphs[0]
                    _add_inline(cp, c)
                    if ri == 0:
                        for run in cp.runs:
                            run.bold = True
            table.rows[0]._tr.get_or_add_trPr().append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
            para = None
            continue
        i += 1
        if not s or s == "---":
            para = None
            prev_numbered = False
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            d.add_heading(m.group(2), 0 if level == 1 else level - 1)
            para = None
            continue
        if s.startswith("* "):
            p = d.add_paragraph(style="List Bullet")
            _add_inline(p, s[2:])
            para = None
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            p = d.add_paragraph(style="List Number")
            if list_num is None or (m.group(1) == "1" and not prev_numbered):
                list_num = _restart_numbering(d)
            _set_num(p, list_num)
            _add_inline(p, m.group(2))
            prev_numbered = True
            para = None
            continue
        prev_numbered = False
        if para is None:
            para = d.add_paragraph()
        else:
            para.runs[-1].add_break()
        _add_inline(para, s)
        if not line.endswith("  "):
            para = None
    buf = io.BytesIO()
    d.save(buf)
    out_path.write_bytes(buf.getvalue())
    return out_path
