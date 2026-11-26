"""Одна сумма в основном тексте и две такие же в таблице: две разные опоры.

Вход -- ``p03_fixtures.amounts_doc``: заголовок «3. Уведомление о расходах»,
автонумерованный список 1–3 (сумма в пункте 2), таблица с той же суммой в строке 2
(жирный «50 000» + курсивный « ₸») и в строке 3 (один run). Путь как у движка:
read_docx → Report → write_docx(report, src, out) → повторное открытие. Проверка
диапазонов -- независимо от экспортёра, по OOXML (p03_ooxml).
"""

from __future__ import annotations

import hashlib

import p03_ooxml as ox
import pytest
from p03_fixtures import (AMOUNT, AMOUNTS_HEADING, AMOUNTS_USER_COMMENT, amounts_doc, evidence, finding,
                          make_report, ref_id)

from bcc_review.exports.word import annotate_docx, write_docx
from bcc_review.readers.docx import locate, read_docx

CELL_R2 = "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]"
CELL_R3 = "/w:document/w:body/w:tbl[1]/w:tr[3]/w:tc[2]"
MAIN_P = "/w:document/w:body/w:p[3]"  # пункт «2.» списка с той же суммой


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(tmp_path, user_comment=False):
    src = amounts_doc(tmp_path / ("amounts_user.docx" if user_comment else "amounts.docx"), user_comment=user_comment)
    doc = read_docx(src)
    r2, r3 = ref_id(doc, "t1.r2"), ref_id(doc, "t1.r3")
    ev_a, ev_b = evidence(doc, r2, AMOUNT), evidence(doc, r3, AMOUNT)
    findings = [
        finding("F-A", [ev_a], severity="major", title="Порог по умолчанию не связан с Ф-1",
                recommendation="Сослаться на пункт 2 вместо повторения суммы."),
        finding("F-B", [ev_b], severity="minor", title="Лимит суммы push дублирует порог",
                recommendation="Удалить строку или объяснить отличие от порога."),
        finding("F-C", [], scope="set", kind="omission", severity="major", title="Нет правила для суммы ниже 1 000 ₸",
                inspected_block_ids=[r2, r3]),
        finding("F-D", [{"block_id": r3, "start": 19, "end": 27, "quote": "60 000 ₸"}], severity="minor",
                title="Опора, которой нет в документе"),
    ]
    report = make_report(doc, findings, check=False)  # F-D намеренно с неверной опорой
    return src, doc, report, ev_a, ev_b


@pytest.mark.parametrize("user_comment", [False, True], ids=["clean", "with_user_comment"])
def test_two_amounts_ranges_match_their_comment_bodies(tmp_path, user_comment):
    src, doc, report, ev_a, ev_b = build(tmp_path, user_comment)
    src_sha, before = sha(src), ox.comments(src)
    out = tmp_path / "report.annotated.docx"
    assert write_docx(report, src, out) == out  # вызов как в engine.export
    new = sorted(set(ox.comments(out)) - set(before))
    rmap = ox.range_map(out, new, read_docx(out))
    by_head = {v["head"].split("]")[0] + "]": (cid, v) for cid, v in rmap.items() if v["head"].startswith("[F-")}

    for fid, ev, cell in (("[F-A]", ev_a, CELL_R2), ("[F-B]", ev_b, CELL_R3)):
        cid, r = by_head[fid]
        assert locate(doc.block(ev["block_id"]), ev["start"], ev["end"])["path"] == cell
        assert (r["start_node"], r["end_node"]) == (cell, cell), fid           # обе границы в своей ячейке
        assert (r["block_id"], r["start"], r["end"]) == (ev["block_id"], ev["start"], ev["end"])
        assert r["covered"] == AMOUNT and r["author"] == "BCC Review"
        assert ox.marker_counts(out, cid) == {"start": 1, "end": 1, "ref": 1}
    assert set(by_head) == {"[F-A]", "[F-B]"}  # F-C и F-D без комментария в тексте
    # сумма в основном тексте не выделена ни одним новым комментарием
    for cid, r in rmap.items():
        assert not (r["start_node"] == MAIN_P and r["covered"]), cid
    # оформление разрезанной суммы цело: жирный «50 000», курсивный « ₸»
    root_src, root_out = ox.part(src), ox.part(out)
    q = CELL_R2[len("/w:document/"):] + "/w:p[1]"
    cell_src, cell_out = (r.xpath(q, namespaces={"w": ox.W})[0] for r in (root_src, root_out))
    assert ox.runs_bold_italic(cell_out) == ox.runs_bold_italic(cell_src) == [("50 000", True, False), (" ₸", False, True)]
    # заголовок и нумерация сохранены
    out_doc = read_docx(out)
    assert out_doc.blocks[0].text == AMOUNTS_HEADING and out_doc.blocks[0].loc["style"] == "Heading 1"
    assert [b.loc["list"]["label"] for b in out_doc.blocks if b.kind == "list_item"] == ["1.", "2.", "3."]
    num = "w:body/w:p[{}]/w:pPr/w:numPr"
    for i in (2, 3, 4):
        a, b = (r.xpath(num.format(i), namespaces={"w": ox.W}) for r in (root_src, root_out))
        assert len(a) == len(b) == 1 or (not a and not b)
        if a:
            from lxml import etree
            assert etree.tostring(a[0]) == etree.tostring(b[0])
    assert [(b.id, b.text) for b in out_doc.blocks] == [(b.id, b.text) for b in doc.blocks]
    assert sha(src) == src_sha
    if user_comment:  # комментарий пользователя: тот же id, автор, текст и тот же диапазон в строке 3
        uid = next(i for i, (a, _) in before.items() if a == "Аналитик банка")
        assert ox.comments(out)[uid] == before[uid] == ("Аналитик банка", AMOUNTS_USER_COMMENT)
        assert ox.covered_text(out, uid) == AMOUNT
        root = ox.part(out)
        assert ox.full_path(ox.ancestor(ox.marker(root, uid, "start"), "tc")) == CELL_R3
        assert uid not in new and by_head["[F-B]"][0] != uid


def test_missing_anchor_is_counted_in_result_summary_and_report(tmp_path):
    src, doc, report, ev_a, ev_b = build(tmp_path)
    out = tmp_path / "report.annotated.docx"
    res = annotate_docx(report, src, out)
    assert res.status == "written"
    assert {s.finding_id: s.reason for s in res.skipped} == {"F-C": "no_evidence", "F-D": "quote_not_found"}
    assert res.counts == {"findings": 4, "findings_anchored": 2, "evidence": 3, "evidence_anchored": 2,
                          "comments_added": 2, "skipped": 2}
    summary = ox.comments(out)[res.summary_comment_id][1]
    assert "Отмечено в тексте: 2 из 4 замечаний (опор 2 из 3)." in summary
    assert "F-C — у замечания нет текстовой опоры" in summary and "F-D — цитаты нет в тексте блока" in summary
    # тот же счётчик попадает в report["warnings"] через write_docx (движок пишет его в report.json)
    (tmp_path / "w").mkdir()
    src2, _, rep, _, _ = build(tmp_path / "w")
    before = len(rep["warnings"])
    write_docx(rep, src2, tmp_path / "w" / "report.annotated.docx")
    assert len(rep["warnings"]) == before + 2  # quote_not_found для F-D + общий счётчик
    counters = [w for w in rep["warnings"] if w["code"] == "docx_export_unanchored"]
    assert len(counters) == 1 and counters[0]["stage"] == "export_docx"
    assert "отмечено 2 из 4 замечаний (опор 2 из 3)" in counters[0]["message"]
    assert "F-C" in counters[0]["message"] and "F-D" in counters[0]["message"]
