"""write_docx: нативные комментарии Word на диапазонах из Evidence (Report по контракту v1)."""

from __future__ import annotations

import hashlib
import json

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from p03_fixtures import (
    CYR_TEXT,
    PHRASE,
    block_id,
    bold_quote_doc,
    comments,
    cyrillic_doc,
    evidence,
    finding,
    make_report,
    markers,
    range_text,
    ref_id,
    repeated_phrase_doc,
    rich_doc,
    start_marker_ancestors,
    zip_names,
    zip_text,
)

from bcc_review.exports.word import (
    SourceMismatchError,
    UnsupportedSourceError,
    WordExportError,
    annotate_docx,
    build_comment_text,
    default_output_path,
    write_docx,
)
from bcc_review.readers.docx import read_docx


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------- доказательство 1


def test_proof1_quote_through_bold_and_normal_run(tmp_path):
    src = bold_quote_doc(tmp_path / "spec.docx")
    doc = read_docx(src)
    quote = "Ф-2. Месяц определяется"
    bid = ref_id(doc, "p2")
    f = finding("F-001", [evidence(doc, bid, quote)], title="Месяц покупки не привязан к часовому поясу")
    rep = make_report(doc, [f], questions=[{
        "id": "Q-001", "finding_ids": ["F-001"], "prompt": "В каком часовом поясе считать дату покупки?",
        "options": ["UTC+5 (Asia/Almaty)", "часовой пояс клиента"], "affected_req_ids": []}])
    out = tmp_path / "report.annotated.docx"
    assert write_docx(rep, src, out, summary=False) == out
    assert out.stat().st_mode & 0o044  # копия читается не только владельцем (umask пользователя)

    # comments part, связь и тип содержимого на месте
    assert "word/comments.xml" in zip_names(out)
    assert "comments.xml" in zip_text(out, "word/_rels/document.xml.rels")
    assert "wordprocessingml.comments+xml" in zip_text(out, "[Content_Types].xml")
    # ровно одна пара границ и ссылка, в правильном порядке
    assert markers(out) == {0: {"start": 1, "end": 1, "ref": 1}}
    xml = zip_text(out, "word/document.xml")
    assert xml.index('commentRangeStart w:id="0"') < xml.index('commentRangeEnd w:id="0"') \
        < xml.index('commentReference w:id="0"')
    assert range_text(out, 0) == quote
    # документ открывается повторно, текст тот же, жирный сохранился на разрезанной части
    d2 = docx.Document(str(out))
    p = d2.paragraphs[1]
    assert p.text == doc.block(bid).text
    assert [(r.text, bool(r.bold)) for r in p.runs if r.text] == [
        ("Ф-2. ", True), ("Месяц определяется", False), (" по дате совершения покупки в Алматы.", False)]
    c = list(d2.comments)[0]
    assert (c.author, c.initials) == ("BCC Review", "BCC")
    for part in ("[F-001] Критичный · подтверждено", "Последствие:", "Блокирует решение:",
                 "Критерий: Однозначность (ISO/IEC/IEEE 29148:2018, 5.2.5)",
                 "Вопрос автору: В каком часовом поясе считать дату покупки? Варианты: UTC+5 (Asia/Almaty)",
                 "Привязка: точная, по цитате"):
        assert part in c.text
    assert [(b.id, b.text) for b in read_docx(out).blocks] == [(b.id, b.text) for b in doc.blocks]


# ------------------------------------------------- доказательство 2


def test_proof2_repeated_phrase_comment_goes_to_selected_cell(tmp_path):
    src = repeated_phrase_doc(tmp_path / "spec.docx")
    src_sha = sha(src)
    old_comments = comments(src)
    doc = read_docx(src)
    row = block_id(doc, lambda b: b.kind == "table_row" and PHRASE in b.text)
    para = block_id(doc, lambda b: b.kind == "paragraph" and PHRASE in b.text)
    f = finding("F-002", [evidence(doc, row, PHRASE)], severity="major",
                title="Валюта порога не названа в таблице", recommendation="Указать «тенге (KZT), целое число».")
    out = tmp_path / "report.annotated.docx"
    res = annotate_docx(make_report(doc, [f]), src, out, summary=False)

    assert res.status == "written" and res.complete
    assert sha(src) == src_sha == res.source_sha256  # исходник не тронут
    a = res.anchors[0]
    assert a.comment_id == max(old_comments) + 1
    assert (a.block_id, a.precision, a.ref, a.path) == (
        row, "exact", "t1.r2.c2", "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]")
    assert a.label == "Таблица 1, строка 2, столбец 2 «Правило»"
    # маркер начала внутри выбранной ячейки, а не в абзаце с той же фразой
    assert start_marker_ancestors(out, a.comment_id)[:3] == ["p", "tc", "tr"]
    assert range_text(out, a.comment_id) == PHRASE
    # старый комментарий и его границы сохранены
    after = comments(out)
    assert all(after[cid] == value for cid, value in old_comments.items())
    assert markers(out)[0] == {"start": 1, "end": 1, "ref": 1}
    assert start_marker_ancestors(out, 0)[:2] == ["p", "body"]
    # текст обеих фраз цел
    out_doc = read_docx(out)
    assert PHRASE in out_doc.block(para).text and PHRASE in out_doc.block(row).text
    for key in ("reopened", "text_unchanged", "existing_comments_preserved", "existing_markers_preserved",
                "new_ranges_paired", "comments_part", "source_unchanged"):
        assert res.checks[key] is True, key
    assert "Исправление: Указать «тенге (KZT), целое число»." in after[a.comment_id][1]


# ------------------------------------------------- доказательство 3


def test_proof3_cyrillic_existing_comment_and_two_annotations_in_one_paragraph(tmp_path):
    src = cyrillic_doc(tmp_path / "spec.docx")
    doc = read_docx(src)
    bid = ref_id(doc, "p2")
    assert doc.block(bid).text == CYR_TEXT
    q1 = "Месяц определяется по дате совершения покупки в Алматы"
    q2 = "уменьшает расходы месяца"  # пересекается с диапазоном старого комментария
    f1 = finding("F-010", [evidence(doc, bid, q1)], title="Нет часового пояса")
    f2 = finding("F-011", [evidence(doc, bid, q2)], severity="minor", status="needs_review",
                 title="Возврат в другом месяце")
    out = tmp_path / "report.annotated.docx"
    res = annotate_docx(make_report(doc, [f2, f1]), src, out, summary=False)
    assert [a.finding_id for a in res.anchors] == ["F-010", "F-011"]  # порядок документа
    assert {a.precision for a in res.anchors} == {"exact"}
    ids = {a.finding_id: a.comment_id for a in res.anchors}
    assert range_text(out, ids["F-010"]) == q1
    assert range_text(out, ids["F-011"]) == q2
    assert range_text(out, 0) == "возврат уменьшает"  # старый комментарий на месте
    all_comments = comments(out)
    assert len(all_comments) == 3 and all_comments[0][0] == "Заказчик"
    assert "[F-011] Незначительный · требует проверки" in all_comments[ids["F-011"]][1]
    assert read_docx(out).block(bid).text == CYR_TEXT
    p = docx.Document(str(out)).paragraphs[1]
    assert "".join(r.text for r in p.runs if r.italic) == "возврат уменьшает"  # курсив цел после разрезания
    assert res.checks["new_ranges_paired"] and res.checks["existing_markers_preserved"]


# ------------------------------------------------- версия и защита входа


def test_other_version_is_refused_with_explanation(tmp_path):
    src = bold_quote_doc(tmp_path / "v1.docx")
    doc = read_docx(src)
    report = make_report(doc, [finding("F-1", [evidence(doc, ref_id(doc, "p2"), "Месяц")])])
    d = docx.Document(str(src))
    d.add_paragraph("Новая редакция.")
    v2 = tmp_path / "v2.docx"
    d.save(v2)
    out = tmp_path / "v2.annotated.docx"
    with pytest.raises(SourceMismatchError) as exc:
        write_docx(report, v2, out)
    assert "другой версии документа" in str(exc.value)
    assert (exc.value.result.expected_sha256, exc.value.result.source_sha256) == (doc.id, sha(v2))
    assert not out.exists()
    res = annotate_docx(report, v2, out)
    assert res.status == "source_mismatch" and res.output_path is None
    assert res.warnings()[0]["code"] == "docx_export_source_mismatch"


def test_report_without_hash_or_with_conflicting_hashes_is_refused(tmp_path):
    src = bold_quote_doc(tmp_path / "a.docx")
    doc = read_docx(src)
    rep = make_report(doc, [])
    rep["document"]["id"] = None
    rep["run"]["source_sha256"] = None
    assert annotate_docx(rep, src, tmp_path / "o.docx").status == "source_mismatch"
    rep = make_report(doc, [])
    rep["run"]["source_sha256"] = "0" * 64
    res = annotate_docx(rep, src, tmp_path / "o.docx")
    assert res.status == "source_mismatch" and "расходятся" in res.message


def test_non_docx_input_and_overwrite_are_refused(tmp_path):
    md = tmp_path / "spec.md"
    md.write_text("# Т\n", encoding="utf-8")
    rep = {"document": {"id": sha(md), "format": "markdown"}, "run": {"source_sha256": sha(md)}, "findings": []}
    with pytest.raises(UnsupportedSourceError, match="только для входа DOCX"):
        write_docx(rep, md, tmp_path / "x.annotated.docx")
    src = bold_quote_doc(tmp_path / "a.docx")
    with pytest.raises(WordExportError, match="перезаписать"):
        write_docx(make_report(read_docx(src), []), src, src)


def test_default_artifact_name():
    assert default_output_path("reports/report.md").as_posix() == "reports/report.annotated.docx"
    assert default_output_path("out/run-1/ОТЧЁТ.md").name == "ОТЧЁТ.annotated.docx"


# ------------------------------------------------- точность и ложные срабатывания


def test_unproven_quotes_are_never_anchored(tmp_path):
    src = repeated_phrase_doc(tmp_path / "spec.docx")
    doc = read_docx(src)
    p2, row, p3 = ref_id(doc, "p2"), ref_id(doc, "t1.r2"), ref_id(doc, "p3")
    good = {"block_id": p2, "start": 0, "end": 5, "quote": "активной карты"}  # координаты неверны, цитата одна
    missing = {"block_id": row, "start": 0, "end": 7, "quote": "Держатель"}  # есть только в абзаце p2
    dup = {"block_id": p3, "start": 0, "end": 3, "quote": "а"}
    unknown = {"block_id": "b9999", "start": 0, "end": 1, "quote": "x"}
    rep = make_report(doc, [
        finding("F-1", [good]), finding("F-2", [missing]), finding("F-3", [dup]),
        finding("F-4", [unknown]), finding("F-5", [], scope="set", kind="omission"),
        finding("F-6", [evidence(doc, p2, "Держатель")], status="rejected"),
        finding("F-7", [{"block_id": p3, "quote": "Конец раздела"}]),  # подсказка без координат
    ], check=False)
    out = tmp_path / "o.annotated.docx"
    res = annotate_docx(rep, src, out)
    assert [(a.finding_id, a.note) for a in res.anchors] == [
        ("F-1", "координаты исправлены по цитате"), ("F-7", "координаты исправлены по цитате")]
    assert range_text(out, res.anchors[0].comment_id) == "активной карты"
    assert {s.finding_id: s.reason for s in res.skipped} == {
        "F-2": "quote_not_found", "F-3": "quote_ambiguous", "F-4": "block_not_found",
        "F-5": "no_evidence", "F-6": "status_not_reportable"}
    assert not res.complete
    assert {w["code"] for w in res.warnings()} == {
        "docx_export_quote_not_found", "docx_export_quote_ambiguous", "docx_export_block_not_found"}
    # в таблицу ничего не поставлено: там цитаты нет
    assert [cid for cid in markers(out) if "tc" in start_marker_ancestors(out, cid)] == []
    summary = comments(out)[res.summary_comment_id][1]
    assert "Разработка: нельзя начинать · Тестирование: нельзя начинать" in summary
    assert "Первые действия: 1) Снять противоречие Ф-3 и Ф-4" in summary
    assert "F-5" in summary and "F-2" in summary
    assert "Замечаний: 6" in summary  # отклонённое F-6 не считается


def test_fields_math_notes_textboxes_cells_and_tracked_changes(tmp_path):
    src = rich_doc(tmp_path / "rich.docx")
    doc = read_docx(src)

    def bid(text):
        return block_id(doc, lambda b: b.text == text)

    row = bid("amount, integer | Порог в тенге\nВторая строка ячейки")
    cases = [
        ("F-fld", bid("См. Ф-3 и критерий 2."), "Ф-3 и критерий", "paragraph", "См. Ф-3 и критерий 2."),
        ("F-fld2", bid("См. Ф-3 и критерий 2."), "критерий 2", "exact", "критерий 2"),
        ("F-sym", bid("Галочка  отмечена"), "отмечена", "run", "Галочка  отмечена"),
        ("F-ins", bid("Порог новый сохраняется."), "новый сохраняется", "exact", "новый сохраняется"),
        ("F-cellp", row, "тенге\nВторая", "exact", "тенге\nВторая"),
        ("F-cells", row, "integer | Порог", "exact", "integer\nПорог"),
        ("F-link", bid("Текст до гиперссылки и после."), "до гиперссылки", "exact", "до гиперссылки"),
        ("F-math", bid("Условие 1000≤x≤1000000 проверяется на сервере."), "1000≤x≤1000000", "paragraph",
         "Условие 1000≤x≤1000000 проверяется на сервере."),
        ("F-note", bid(" Курс пересчёта тиынов не определён."), "тиынов", "paragraph",
         "Порог хранится в тенге без копеек."),
        # рамка лежит внутри абзаца-хозяина, поэтому его диапазон включает и её текст
        ("F-box", bid("Текст в рамке"), "в рамке", "paragraph", "Перед рамкой \nТекст в рамке"),
    ]
    rep = make_report(doc, [finding(fid, [evidence(doc, b, q)]) for fid, b, q, _, _ in cases])
    out = tmp_path / "o.annotated.docx"
    res = annotate_docx(rep, src, out, summary=False)
    assert res.complete
    got = {a.finding_id: a for a in res.anchors}
    for fid, _, _, precision, anchored in cases:
        assert got[fid].precision == precision, fid
        assert range_text(out, got[fid].comment_id) == anchored, fid
    assert "поле Word" in got["F-fld"].note and "формулу OMML" in got["F-math"].note
    assert (got["F-note"].ref, got["F-note"].part) == ("fn1", "word/footnotes.xml") and "сноска" in got["F-note"].note
    assert got["F-box"].ref == "p9.tb1" and "текстовое поле" in got["F-box"].note
    assert got["F-cellp"].ref == "t1.r3.c3" and got["F-cells"].ref == "t1.r3"
    assert "Привязка: абзац целиком (граница попадает в поле Word" in comments(out)[got["F-fld"].comment_id][1]
    assert res.checks["text_unchanged"] and res.checks["new_ranges_paired"]
    # повторное аннотирование уже аннотированной копии тоже работает
    doc2 = read_docx(out)
    link = block_id(doc2, lambda b: b.text == "Текст до гиперссылки и после.")
    res2 = annotate_docx(make_report(doc2, [finding("F-again", [evidence(doc2, link, "Текст до")])]), out,
                         tmp_path / "o2.annotated.docx", summary=False)
    assert res2.anchors[0].precision == "exact" and res2.checks["existing_comments_preserved"]


def test_whole_cell_fallback(tmp_path):
    d = docx.Document()
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Поле", "Ссылка"
    t.cell(1, 0).text = "Справка"
    p = t.cell(1, 1).paragraphs[0]._p
    p.append(parse_xml(f'<w:fldSimple {nsdecls("w")} w:instr=" PAGE "><w:r><w:t>12</w:t></w:r></w:fldSimple>'))
    src = tmp_path / "cell.docx"
    d.save(src)
    doc = read_docx(src)
    row = ref_id(doc, "t1.r2")
    res = annotate_docx(make_report(doc, [finding("F-c", [evidence(doc, row, "12")])]), src,
                        tmp_path / "cell.annotated.docx", summary=False)
    a = res.anchors[0]
    assert (a.precision, a.ref, a.label) == ("cell", "t1.r2.c2", "Таблица 1, строка 2, столбец 2 «Ссылка»")
    assert range_text(tmp_path / "cell.annotated.docx", a.comment_id) == "12"


def test_comment_text_contract():
    f = finding("F-7", [], severity="major", title="Конфликт Ф-3 и Ф-4",
                witness={"input": "push уже был, порог изменён", "outcome_a": "второй push запрещён",
                         "outcome_b": "push отправляется"})
    text = build_comment_text(f, quote="Ф-4. При изменении порога", precision="paragraph",
                              reason="граница попадает в поле Word", other_places=["Абзац 17"])
    lines = text.split("\n")
    assert lines[0] == "[F-7] Существенный · подтверждено"
    assert "Последствие: Разработчик и тестировщик поймут правило по-разному." in lines
    assert any(line.startswith("Сценарий: push уже был") for line in lines)
    assert "Вопрос автору: подтвердите или исправьте формулировку «Ф-4. При изменении порога»." in lines
    assert "Связанное место: Абзац 17" in lines
    assert lines[-1] == "Привязка: абзац целиком (граница попадает в поле Word)"


def test_result_is_json_serialisable(tmp_path):
    src = bold_quote_doc(tmp_path / "a.docx")
    doc = read_docx(src)
    res = annotate_docx(make_report(doc, [finding("F-1", [evidence(doc, ref_id(doc, "p2"), "Месяц")])]), src,
                        tmp_path / "a.annotated.docx")
    data = json.loads(json.dumps(res.to_dict(), ensure_ascii=False))
    assert data["artifact"] == "a.annotated.docx"
    assert (data["anchors"][0]["ref"], data["anchors"][0]["path"]) == ("p2", "/w:document/w:body/w:p[2]")
    assert data["complete"] is True and data["comments_after"] == 2
