"""Комментарий на точном вхождении, а не на соседней копии той же фразы.

Фраза ``TWIN`` стоит в обычном абзаце (там уже комментарий автора) и в ячейке
таблицы, где она разрезана между жирным run и внешней гиперссылкой, а перед ней
удалённый при рецензировании текст «порог от 500 ». Аннотируется только копия в
ячейке. Проверка идёт по OOXML повторно открытой копии (p03_ooxml), без доверия
к результату экспортёра.
"""

from __future__ import annotations

import hashlib

import p03_ooxml as ox
from p03_fixtures import TWIN, TWIN_URL, evidence, finding, make_report, ref_id, twin_phrase_doc

from bcc_review.exports.word import annotate_docx, write_docx
from bcc_review.readers.docx import locate, read_docx

CELL = "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]"
CELL_P = CELL + "/w:p[1]"
PARA = "/w:document/w:body/w:p[1]"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annotate_cell_copy(tmp_path, **fixture):
    src = twin_phrase_doc(tmp_path / "twin.docx", **fixture)
    src_sha = sha(src)
    doc = read_docx(src)
    row = ref_id(doc, "t1.r2")
    ev = evidence(doc, row, TWIN)
    f = finding("F-201", [ev], severity="major", title="Валюта и граница порога в таблице не совпадают с Ф-1",
                recommendation="Указать «целое число тенге (KZT), обе границы включены».")
    out = tmp_path / "twin.annotated.docx"
    assert write_docx(make_report(doc, [f]), src, out) == out  # вызов как в engine.export
    return src, src_sha, doc, row, ev, out


def new_comment_id(src, out, prefix="[F-201]"):
    before, after = ox.comments(src), ox.comments(out)
    new = [cid for cid, (_, text) in after.items() if cid not in before and text.startswith(prefix)]
    assert len(new) == 1, f"новых комментариев {prefix}: {new}"
    return new[0]


def test_comment_lands_on_cell_copy_not_on_paragraph_copy(tmp_path):
    src, src_sha, doc, row, ev, out = annotate_cell_copy(tmp_path)
    cid = new_comment_id(src, out)

    # ровно одна пара границ и одна ссылка во всём пакете
    assert ox.marker_counts(out, cid) == {"start": 1, "end": 1, "ref": 1}
    # видимый текст диапазона = цитата Evidence (удалённое «порог от 500 » не входит)
    assert ox.covered_text(out, cid) == ev["quote"] == TWIN
    # структурный путь: обе границы в той ячейке, которую называет Evidence
    root = ox.part(out)
    place = locate(doc.block(row), ev["start"], ev["end"])
    assert place["path"] == CELL and place["ref"] == "t1.r2.c2"
    for kind in ("start", "end", "ref"):
        assert ox.full_path(ox.ancestor(ox.marker(root, cid, kind), "tc")) == CELL, kind
    # координаты в тексте блока совпадают с Evidence до символа
    assert ox.block_span(out, cid, read_docx(out)) == (row, ev["start"], ev["end"], CELL_P)
    # ни один новый комментарий не охватывает ни одного символа абзаца с той же фразой
    para_ids = {int(el.get(ox.w("id"))) for el in root.iter(*ox._MARK.values())
                if ox.ancestor(el, "p") is not None and ox.full_path(ox.ancestor(el, "p")) == PARA}
    new_ids = set(ox.comments(out)) - set(ox.comments(src))
    for other in para_ids & new_ids:
        assert ox.covered_text(out, other) == "", f"комментарий {other} выделяет слова абзаца {PARA}"
    # сводка по умолчанию -- точка в начале документа (пустой диапазон), а не выделение копии
    summary = [i for i in new_ids if ox.comments(out)[i][1].startswith("Сводка ревью ТЗ")]
    assert len(summary) == 1 and ox.covered_text(out, summary[0]) == ""


def test_old_comment_hyperlink_format_deletion_and_source_are_intact(tmp_path):
    src, src_sha, doc, row, ev, out = annotate_cell_copy(tmp_path)
    cid = new_comment_id(src, out)
    # прежний комментарий автора: тот же id, автор, текст и диапазон на копии в абзаце
    before, after = ox.comments(src), ox.comments(out)
    assert before[0] == after[0] == ("Автор ТЗ", "Автор: границы согласованы с бизнесом.")
    assert ox.marker_counts(out, 0) == {"start": 1, "end": 1, "ref": 1}
    assert ox.covered_text(out, 0) == TWIN
    assert ox.full_path(ox.ancestor(ox.marker(ox.part(out), 0, "start"), "p")) == PARA
    # гиперссылка: тот же r:id, тот же адрес, тот же видимый текст
    assert ox.hyperlinks(out) == ox.hyperlinks(src) == [(ox.hyperlinks(src)[0][0], TWIN_URL, " до 1 000 000 ₸")]
    # форматирование run в ячейке: жирный кусок и кусок-ссылка не изменились
    root_out = ox.part(out)
    cell_p_src = ox.part(src).xpath(CELL_P[1:].replace("w:document/", "", 1), namespaces={"w": ox.W})[0]
    cell_p_out = root_out.xpath(CELL_P[1:].replace("w:document/", "", 1), namespaces={"w": ox.W})[0]
    assert ox.runs_with_format(cell_p_out) == ox.runs_with_format(cell_p_src) == [
        ("порог от 1 000", True, False), (" до 1 000 000 ₸", False, True), (" включительно.", False, False)]
    # удалённый текст на месте и вне диапазона нового комментария
    dels = [t.text for t in cell_p_out.iter(ox.w("delText"))]
    assert dels == ["порог от 500 "]
    start = ox.marker(root_out, cid, "start")
    deleted = next(cell_p_out.iter(ox.w("del")))
    order = list(cell_p_out.iter())  # полный порядок документа, включая w:del
    assert order.index(deleted) < order.index(start)
    # исходный файл не тронут
    assert sha(src) == src_sha
    # текст документа после аннотирования тот же
    assert [(b.id, b.text) for b in read_docx(out).blocks] == [(b.id, b.text) for b in doc.blocks]


def test_orphan_markers_with_next_free_id_do_not_capture_new_comment(tmp_path):
    """В абзаце остались маркеры w:id=1 без записи в comments.xml. python-docx выдаёт
    новому комментарию id = max(comments.xml) + 1 = 1, и Word привязал бы его к
    первой паре маркеров -- к копии фразы в абзаце."""
    src, src_sha, doc, row, ev, out = annotate_cell_copy(tmp_path, orphan_markers=True)
    cid = new_comment_id(src, out)
    assert ox.marker_counts(out, cid) == {"start": 1, "end": 1, "ref": 1}
    assert ox.covered_text(out, cid) == TWIN
    assert ox.block_span(out, cid, read_docx(out)) == (row, ev["start"], ev["end"], CELL_P)
    assert ox.marker_counts(out, 1) == {"start": 1, "end": 1, "ref": 0}  # чужие маркеры не тронуты


# ------------------------------------------------- защита от «внешне правильного» результата


def test_misplaced_markers_are_caught_and_copy_is_removed(tmp_path, monkeypatch):
    """Имитация ошибки размещения: границы ставятся на копию фразы в абзаце, а
    текст комментария -- правильный. Экспорт обязан это увидеть после записи."""
    import pytest

    import bcc_review.exports.word as word

    real_apply = word._apply

    def misplaced(doc, plan, text, author, initials, reserved):
        if text.startswith("[F-201]"):
            para_copy = doc.element.body.findall(ox.w("p"))[0].findall(ox.w("r"))[1]  # «порог…» в абзаце
            plan = word._Plan("runs", plan.precision, plan.reason, para_copy, para_copy,
                              plan.block_id, plan.span, plan.bounds)
        return real_apply(doc, plan, text, author, initials, reserved)

    monkeypatch.setattr(word, "_apply", misplaced)
    src = twin_phrase_doc(tmp_path / "twin.docx")
    doc = read_docx(src)
    ev = evidence(doc, ref_id(doc, "t1.r2"), TWIN)
    out = tmp_path / "twin.annotated.docx"
    res = word.annotate_docx(make_report(doc, [finding("F-201", [ev], severity="major")]), src, out)
    assert res.status == "verification_failed" and res.output_path is None and not out.exists()
    assert res.checks["anchors_match_plan"] is False and res.checks["new_ranges_paired"] is True
    assert res.anchors[0].covered["block_id"] == ref_id(doc, "p1")  # охвачена бы копия в абзаце
    assert "соседнем месте" in res.message
    with pytest.raises(word.WordExportError):
        word.write_docx(make_report(doc, [finding("F-201", [ev], severity="major")]), src, out)


# ------------------------------------------------- место только для привязки к абзацу


def test_footnote_copy_is_anchored_to_host_paragraph_with_visible_label(tmp_path):
    src = twin_phrase_doc(tmp_path / "twin_fn.docx", footnote=True)
    doc = read_docx(src)
    note = next(b for b in doc.blocks if b.loc["anchor"] == "note")
    ev = evidence(doc, note.id, TWIN)
    out = tmp_path / "twin_fn.annotated.docx"
    rep = make_report(doc, [finding("F-301", [ev], severity="minor", title="Комиссии не учтены в пороге")])
    res = annotate_docx(rep, src, out, summary=False)
    a = res.anchors[0]
    assert res.status == "written" and (a.precision, a.ref, a.part) == ("paragraph", "fn1", "word/footnotes.xml")
    row = ref_id(doc, "t1.r2")
    cell_text = "порог от 1 000 до 1 000 000 ₸ включительно."
    assert a.covered == {"block_id": row, "start": 9, "end": 9 + len(cell_text), "text": cell_text}
    # независимая сверка по OOXML: границы вокруг абзаца ячейки со знаком сноски
    root = ox.part(out)
    assert ox.full_path(ox.ancestor(ox.marker(root, a.comment_id, "start"), "p")) == CELL_P
    assert ox.covered_text(out, a.comment_id) == cell_text
    text = ox.comments(out)[a.comment_id][1]
    assert "Точные слова: «порог от 1 000 до 1 000 000 ₸»" in text
    assert text.splitlines()[-1] == ("Привязка: абзац целиком (сноска: Word не ставит комментарий внутрь, "
                                     "привязано к абзацу со знаком)")
    assert ox.marker_counts(out, a.comment_id) == {"start": 1, "end": 1, "ref": 1}
    assert not ox.has_part(out, "word/footnotes.xml") or ox.marker_counts(out, a.comment_id)["start"] == 1


# ------------------------------------------------- версия python-docx


def test_comments_need_python_docx_1_2(tmp_path, monkeypatch):
    """Document.add_comment появился в python-docx 1.2.0: без него экспорт отказывает понятно."""
    import pytest

    import bcc_review.exports.word as word

    class OldDocument:  # как docx.document.Document в 1.1.x
        pass

    monkeypatch.setattr(word, "_DocxDocument", OldDocument)
    src = twin_phrase_doc(tmp_path / "twin.docx")
    doc = read_docx(src)  # чтение от версии не зависит
    with pytest.raises(word.WordExportError, match=r"python-docx >= 1\.2"):
        word.write_docx(make_report(doc, []), src, tmp_path / "x.annotated.docx")


def test_installed_python_docx_has_comments_api():
    from importlib.metadata import version

    from docx.document import Document as DocxDocument

    major, minor = (int(x) for x in version("python-docx").split(".")[:2])
    assert (major, minor) >= (1, 2) and hasattr(DocxDocument, "add_comment")
