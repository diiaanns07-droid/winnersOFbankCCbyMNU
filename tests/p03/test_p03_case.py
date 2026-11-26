"""Сквозной путь на DOCX-версии кейса BCC-HUB и повторное открытие в LibreOffice.

Тест с LibreOffice пропускается, если ``soffice`` не установлен.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from p03_fixtures import CASE_DOCX, block_id, comments, evidence, finding, make_report, range_text

from bcc_review.exports.word import annotate_docx
from bcc_review.readers.docx import read_docx

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


def case_report():
    doc = read_docx(CASE_DOCX)
    f2 = block_id(doc, lambda b: b.text.startswith("Ф-2."))
    crit = block_id(doc, lambda b: b.kind == "table_row" and "Февральский счётчик" in b.text)
    get = block_id(doc, lambda b: b.kind == "table_row" and b.text == "REST type | GET")
    h200 = block_id(doc, lambda b: b.kind == "heading" and b.text.startswith("200. Successful"))
    err = block_id(doc, lambda b: b.text.startswith('{"result":"ERROR"'))
    k1_a = evidence(doc, f2, "Ф-2. Месяц определяется по дате совершения покупки")
    k1_b = evidence(doc, crit, "Февральский счётчик вырос на 4 000 ₸")
    findings = [
        finding("K1", [k1_a, k1_b], kind="conflict", criterion="set_consistent", scope="set",
                title="Критерий приёмки №2 противоречит Ф-2", req_ids=["R-F2", "R-AC2"],
                impact="Покупка 31.01 по Ф-2 относится к январю, а критерий ждёт февраль: тест упадёт при верной реализации.",
                witness={"input": "покупка 31.01 23:58, проведение 01.02 00:03", "outcome_a": "январь",
                         "outcome_b": "февраль", "evidence_a": k1_a, "evidence_b": k1_b}),
        finding("K3", [evidence(doc, h200, "200. Successful — Created"), evidence(doc, err, '"result":"ERROR"')],
                kind="conflict", scope="set", title="Ошибка суммы описана и как 200, и как 400",
                impact="Клиент API не знает, по какому признаку распознать отказ.", status="needs_review"),
        finding("C1", [evidence(doc, get, "GET")], severity="major", kind="design_in_requirement",
                title="GET меняет данные", impact="Порог и cardId попадают в URL и журналы прокси.",
                recommendation="Использовать POST или PUT с телом JSON."),
    ]
    questions = [{"id": "Q-1", "finding_ids": ["K1"], "prompt": "Месяц считается по дате совершения или проведения?",
                  "options": ["совершения", "проведения"], "affected_req_ids": ["R-F2", "R-AC2"]}]
    return doc, make_report(doc, findings, questions=questions)


def test_case_docx_blocks_have_table_locations():
    doc = read_docx(CASE_DOCX)
    row = doc.block(block_id(doc, lambda b: "Февральский счётчик" in b.text))
    assert (row.kind, row.loc["ref"]) == ("table_row", "t2.r3")
    assert row.loc["table"]["columns"] == ["Исходные условия", "Действие", "Ожидаемый результат"]
    c3 = row.loc["cells"][2]
    assert (c3["ref"], c3["column_header"]) == ("t2.r3.c3", "Ожидаемый результат")
    assert row.text[c3["start"]:c3["end"]] == "Февральский счётчик вырос на 4 000 ₸"
    assert doc.by_ref("t2.r1").kind == "table_header"
    assert doc.by_ref("t2.r1").loc["table"]["header_row_source"] == "tblHeader"
    assert row.section[-2:] == ["Часть A. Новый функционал", "Критерии приемки"]
    f2 = doc.block(block_id(doc, lambda b: b.text.startswith("Ф-2.")))
    assert f2.loc["runs"][0]["fmt"] == ["b"] and f2.loc["runs"][0]["end"] == 4
    steps = [b for b in doc.blocks if b.section and b.section[-1] == "Логика работы метода" and b.kind == "list_item"]
    assert [b.loc["list"]["label"] for b in steps] == ["1.", "2.", "3.", "4.", "5."]
    statuses = doc.block(block_id(doc, lambda b: b.text.startswith("200. Ответ")))
    assert statuses.text.split("\n")[1].startswith("400. Ответ")  # w:br внутри абзаца
    assert not doc.warnings


def test_case_annotation_end_to_end(tmp_path):
    doc, report = case_report()
    out = tmp_path / "report.annotated.docx"
    res = annotate_docx(report, CASE_DOCX, out)
    assert res.status == "written" and res.complete
    assert len(res.anchors) == 5 and {a.precision for a in res.anchors} == {"exact"}
    for a in res.anchors:
        assert range_text(out, a.comment_id) == a.quote
    k1 = [a for a in res.anchors if a.finding_id == "K1"]
    assert [a.ref for a in k1] == ["p16", "t2.r3.c3"]
    assert k1[1].label == "Таблица 2, строка 3, столбец 3 «Ожидаемый результат»"
    cell_comment = comments(out)[k1[1].comment_id][1]
    assert "Связанное место: Абзац 16 (пункт списка)" in cell_comment
    assert "Сценарий: покупка 31.01 23:58" in cell_comment
    assert "Вопрос автору: Месяц считается по дате совершения или проведения? Варианты: совершения / проведения." \
        in cell_comment
    assert [a.ref for a in res.anchors if a.finding_id == "C1"] == ["t5.r3.c2"]
    assert all(res.checks[k] for k in ("reopened", "text_unchanged", "new_ranges_paired", "source_unchanged"))


def _soffice(src: Path, outdir: Path, target: str) -> Path:
    env = dict(os.environ, HOME=str(outdir))
    subprocess.run(
        [SOFFICE, f"-env:UserInstallation=file://{outdir / 'lo-profile'}", "--headless",
         "--convert-to", target, "--outdir", str(outdir), str(src)],
        check=True, capture_output=True, timeout=240, env=env,
    )
    produced = outdir / (src.stem + "." + target.split(":", 1)[0])
    assert produced.exists(), f"LibreOffice не создал {produced.name}"
    return produced


def _odt_annotations(odt: Path) -> dict[str, str]:
    """office:name -> текст, к которому LibreOffice привязал комментарий."""
    xml = zipfile.ZipFile(odt).read("content.xml").decode("utf-8")
    out = {}
    for m in re.finditer(r'<office:annotation\b[^>]*office:name="([^"]+)"[^>]*>.*?</office:annotation>(.*?)'
                         r'<office:annotation-end\b[^>]*office:name="\1"', xml, re.S):
        body = re.sub(r"<office:annotation\b.*?</office:annotation>", "", m.group(2), flags=re.S)
        body = re.sub(r"</text:p>\s*<text:p\b[^>]*>", "\n", body)
        body = re.sub(r'<text:s text:c="(\d+)"/>', lambda k: " " * int(k.group(1)), body)
        body = body.replace("<text:s/>", " ").replace("<text:tab/>", "\t").replace("<text:line-break/>", "\n")
        text = re.sub(r"<[^>]+>", "", body)
        out[m.group(1)] = text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return out


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) не установлен")
def test_libreoffice_reopens_annotated_case_and_shows_comments(tmp_path):
    doc, report = case_report()
    out = tmp_path / "report.annotated.docx"
    res = annotate_docx(report, CASE_DOCX, out)
    # 1) LibreOffice открывает копию и видит каждый комментарий с тем же диапазоном
    odt = _soffice(out, tmp_path, "odt")
    anchored = sorted(_odt_annotations(odt).values())
    expected = sorted([a.quote for a in res.anchors] + [doc.by_ref("p1").text])  # + общий комментарий
    assert anchored == expected
    # 2) PDF с комментариями на полях: текст комментариев попадает на страницу
    pdf = _soffice(out, tmp_path, 'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}')
    if shutil.which("pdftotext"):
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        for fid in ("[K1]", "[K3]", "[C1]"):
            assert fid in text
        assert "BCC Review" in text


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) не установлен")
def test_libreoffice_puts_twin_comment_into_the_cell(tmp_path):
    """Фраза в абзаце и в ячейке: LibreOffice ставит новый комментарий в ячейку,
    комментарий автора остаётся в абзаце, сводка -- точкой без выделения."""
    from lxml import etree
    from p03_fixtures import TWIN, ref_id, twin_phrase_doc

    for orphan in (False, True):
        src = twin_phrase_doc(tmp_path / f"twin{int(orphan)}.docx", orphan_markers=orphan)
        doc = read_docx(src)
        rep = make_report(doc, [finding("F-201", [evidence(doc, ref_id(doc, "t1.r2"), TWIN)], severity="major")])
        out = tmp_path / f"twin{int(orphan)}.annotated.docx"
        annotate_docx(rep, src, out)
        odt = _soffice(out, tmp_path / f"lo{int(orphan)}", "odt")
        ns = {"office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
              "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0", "dc": "http://purl.org/dc/elements/1.1/"}
        root = etree.fromstring(zipfile.ZipFile(odt).read("content.xml"))
        where = {}
        for ann in root.iter("{%s}annotation" % ns["office"]):
            body = "".join(t for t in ann.itertext())
            kind = "F-201" if "[F-201]" in body else ("summary" if "Сводка ревью" in body else "author")
            where[kind] = "cell" if ann.xpath("ancestor::table:table-cell", namespaces=ns) else "paragraph"
        assert where == {"F-201": "cell", "author": "paragraph", "summary": "paragraph"}, (orphan, where)
        ranges = _odt_annotations(odt)
        assert sorted(ranges.values()) == ["", TWIN, TWIN]  # сводка -- пустой диапазон
