"""Объединённая шапка: единица «за сутки» на два столбца, исключение в одной ячейке.

Вход -- ``p03_fixtures.limits_doc``: шапка в две строки («Лимит за сутки» на 2 столбца над
«Сумма, ₸» | «Операций», «Правило» и «Условие» объединены по вертикали), Л-1 и Л-2 с
похожими значениями и разными условиями. Редакция (``monthly=True``) меняет только
единицу Л-2: «300 000» → «300 000 за месяц».

Проверяется:
* связь шапка → строка → ячейка в ридере: заголовок каждой ячейки данных собран из обеих
  строк шапки, ``header_refs`` -- ячейки шапки, из которых он взят (с ``tblHeader`` и без);
* редакция отличается от чистого документа ровно одной ячейкой;
* фиксированное замечание: комментарий в изменённой ячейке, проверка по OOXML без кода
  экспортёра (``p03_ooxml``) и повторное открытие копии: та же связь, те же объединения;
* тот же путь через штатный вход движка (``bcc_review.cli.main``, если движок влит) и
  повторное открытие копии в LibreOffice (если установлен).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile

import p03_ooxml as ox
import pytest
from p03_fixtures import (DAILY, EXCEPTION, LIMIT_ROWS, LIMIT_SUM, LIMITS_COLUMNS, LIMITS_CONFLICT, LIMITS_EXCEPTION,
                          MONTHLY, evidence, finding, limits_doc, limits_mock_script, make_report, ref_id)

from bcc_review.contracts import validate
from bcc_review.exports.word import annotate_docx, write_docx
from bcc_review.readers.docx import locate, read_docx

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


def cell_path(row: int, col: int) -> str:
    return f"/w:document/w:body/w:tbl[1]/w:tr[{row}]/w:tc[{col}]"


SUM_HEAD, OPS_HEAD = LIMITS_COLUMNS[1], LIMITS_COLUMNS[2]
HEADER_REFS = {1: ("t1.r1.c1",), 2: ("t1.r1.c2", "t1.r2.c2"), 3: ("t1.r1.c2", "t1.r2.c3"), 4: ("t1.r1.c4",)}


def expected_cells(monthly: bool) -> dict[str, tuple[str, tuple[str, ...], str]]:
    """Ячейка данных -> (заголовок столбца, ячейки шапки, текст ячейки)."""
    out = {}
    for ri, row in enumerate(LIMIT_ROWS, start=3):
        for col, value in enumerate(row, start=1):
            if monthly and (ri, col) == (4, 2):
                value = f"{value} {MONTHLY}"
            out[f"t1.r{ri}.c{col}"] = (LIMITS_COLUMNS[col - 1], HEADER_REFS[col], value)
    return out


def cell_map(doc) -> dict[str, tuple[str, tuple[str, ...], str]]:
    """Фактическая связь из ``loc.cells`` строк данных (Document ридера или dict из report.json)."""
    out = {}
    for b in doc.blocks if hasattr(doc, "blocks") else doc["blocks"]:
        b = b.to_dict() if hasattr(b, "to_dict") else b
        if b["kind"] != "table_row":
            continue
        for c in b["loc"]["cells"]:
            out[c["ref"]] = (c["column_header"], tuple(c["header_refs"]), b["text"][c["start"]:c["end"]])
    return out


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ ридер


@pytest.mark.parametrize("repeat_header", [False, True], ids=["merged_only", "tblHeader"])
@pytest.mark.parametrize("monthly", [False, True], ids=["clean", "monthly"])
def test_two_row_header_reaches_every_data_cell(tmp_path, monthly, repeat_header):
    doc = read_docx(limits_doc(tmp_path / "limits.docx", monthly=monthly, repeat_header=repeat_header))
    validate(doc.to_dict(), "Document")
    assert [(b.loc["ref"], b.kind) for b in doc.blocks] == [
        ("p1", "heading"), ("p2", "paragraph"), ("t1.r1", "table_header"), ("t1.r2", "table_header"),
        ("t1.r3", "table_row"), ("t1.r4", "table_row"), ("p3", "paragraph")]
    source = "tblHeader" if repeat_header else None
    assert [b.loc["table"]["header_row_source"] for b in doc.blocks if b.loc["table"]] == \
        [source or "first_row", source or "merged_cells", None, None]
    for b in doc.blocks:
        if b.loc["table"]:
            assert (b.loc["table"]["columns"], b.loc["table"]["header_rows"]) == (LIMITS_COLUMNS, 2)
    assert cell_map(doc) == expected_cells(monthly)
    # объединённая ячейка шапки -- одна ячейка на столбцы 2–3, в ней единица «за сутки»
    head = doc.by_ref("t1.r1")
    merged = head.loc["cells"][1]
    assert (merged["ref"], merged["col_span"], head.text[merged["start"]:merged["end"]]) == \
        ("t1.r1.c2", 2, "Лимит " + DAILY)
    assert merged["label"] == "Таблица 1, строка 1, столбцы 2–3"
    # исключение -- в одной ячейке Л-1, со своей строкой и заголовком «Условие»
    r3 = doc.by_ref("t1.r3")
    s = r3.text.index(EXCEPTION)
    place = locate(r3, s, s + len(EXCEPTION))
    assert (place["ref"], place["path"], place["label"]) == (
        "t1.r3.c4", cell_path(3, 4), "Таблица 1, строка 3, столбец 4 «Условие»")
    r4 = doc.by_ref("t1.r4")
    s = r4.text.index(LIMIT_SUM)
    assert locate(r4, s, s + len(LIMIT_SUM))["label"] == f"Таблица 1, строка 4, столбец 2 «{SUM_HEAD}»"


def test_revision_differs_by_one_cell_only(tmp_path):
    clean = read_docx(limits_doc(tmp_path / "limits.docx"))
    month = read_docx(limits_doc(tmp_path / "limits_month.docx", monthly=True))
    assert [(b.id, b.kind, b.loc["ref"]) for b in clean.blocks] == [(b.id, b.kind, b.loc["ref"]) for b in month.blocks]
    changed = [b.loc["ref"] for b, m in zip(clean.blocks, month.blocks) if b.text != m.text]
    assert changed == ["t1.r4"]
    a, b = cell_map(clean), cell_map(month)
    assert [ref for ref in a if a[ref] != b[ref]] == ["t1.r4.c2"]
    assert (a["t1.r4.c2"][2], b["t1.r4.c2"][2]) == (LIMIT_SUM, f"{LIMIT_SUM} {MONTHLY}")
    assert a["t1.r4.c2"][:2] == b["t1.r4.c2"][:2] == (SUM_HEAD, HEADER_REFS[2])  # шапка у ячейки та же


# ------------------------------------------------------- прямой путь экспорта


def build_report(tmp_path, monthly: bool):
    src = limits_doc(tmp_path / ("limits_month.docx" if monthly else "limits.docx"), monthly=monthly)
    doc = read_docx(src)
    h1, r3, r4 = ref_id(doc, "t1.r1"), ref_id(doc, "t1.r3"), ref_id(doc, "t1.r4")
    findings = [finding("F-EXC", [evidence(doc, r3, EXCEPTION)], severity="major", title=LIMITS_EXCEPTION,
                        recommendation="Написать, уменьшает ли возврат использованный лимит.")]
    if monthly:
        ev_cell, ev_head = evidence(doc, r4, MONTHLY), evidence(doc, h1, DAILY)
        witness = {"input": "покупки в интернете по 300 000 ₸ 1 и 2 числа", "outcome_a": "2 числа покупка проходит",
                   "outcome_b": "2 числа покупка отклонена", "evidence_a": ev_head, "evidence_b": ev_cell}
        findings.insert(0, finding(
            "F-UNIT", [ev_cell, ev_head], scope="set", kind="conflict", criterion="set_consistent",
            title=LIMITS_CONFLICT, recommendation="Указать период Л-2 в шапке.", witness=witness))
    return src, doc, make_report(doc, findings)


@pytest.mark.parametrize("monthly", [False, True], ids=["clean", "monthly"])
def test_fixed_finding_comment_in_changed_cell_and_reopen(tmp_path, monthly):
    src, doc, report = build_report(tmp_path, monthly)
    src_sha = sha(src)
    out = tmp_path / "report.annotated.docx"
    assert write_docx(report, src, out) == out
    assert sha(src) == src_sha
    new = sorted(set(ox.comments(out)) - set(ox.comments(src)))
    rmap = ox.range_map(out, new, read_docx(out))
    placed = {(r["head"].split("]")[0] + "]", r["start_node"]): r for r in rmap.values() if r["head"].startswith("[F-")}
    expected = {("[F-EXC]", cell_path(3, 4)): EXCEPTION}
    if monthly:
        expected |= {("[F-UNIT]", cell_path(4, 2)): MONTHLY, ("[F-UNIT]", cell_path(1, 2)): DAILY}
    assert {k: r["covered"] for k, r in placed.items()} == expected
    for (fid, node), r in placed.items():
        assert r["end_node"] == node, fid  # обе границы в одной ячейке
        assert ox.marker_counts(out, [c for c, x in rmap.items() if x is r][0]) == {"start": 1, "end": 1, "ref": 1}
    # соседние ячейки с похожими значениями и условием «включая возвраты» не выделены
    for cid, r in rmap.items():
        assert r["start_node"] not in (cell_path(3, 2), cell_path(4, 4)) or not r["covered"], cid
    body_exc = placed[("[F-EXC]", cell_path(3, 4))]["body"]
    assert "Место: Таблица 1, строка 3, столбец 4 «Условие»; строка «Л-1. Переводы на карты других банков»" in body_exc
    if monthly:
        body = placed[("[F-UNIT]", cell_path(4, 2))]["body"]
        assert body.splitlines()[:2] == ["[F-UNIT] Критичный · подтверждено", LIMITS_CONFLICT]
        assert f"Место: Таблица 1, строка 4, столбец 2 «{SUM_HEAD}»; строка «Л-2. Покупки в интернете»" in body
        assert "Связанное место: Таблица 1, строка 1, столбцы 2–3" in body
        head_body = placed[("[F-UNIT]", cell_path(1, 2))]["body"]
        assert "Место:" not in head_body  # ячейка шапки: место -- сама шапка
        assert f"Связанное место: Таблица 1, строка 4, столбец 2 «{SUM_HEAD}»" in head_body
    # повторное открытие: блоки, тексты и связь шапка → строка → ячейка те же
    again = read_docx(out)
    assert [(b.id, b.kind, b.text) for b in again.blocks] == [(b.id, b.kind, b.text) for b in doc.blocks]
    assert cell_map(again) == cell_map(doc) == expected_cells(monthly)
    assert [b.loc["table"]["columns"] for b in again.blocks if b.loc["table"]] == [LIMITS_COLUMNS] * 4
    # объединения в XML копии те же, что во входе
    for path in (src, out):
        root = ox.part(path)
        tc12 = root.xpath("w:body/w:tbl[1]/w:tr[1]/w:tc[2]/w:tcPr/w:gridSpan/@w:val", namespaces={"w": ox.W})
        vm = root.xpath("w:body/w:tbl[1]/w:tr[position()<=2]/w:tc[1]/w:tcPr/w:vMerge", namespaces={"w": ox.W})
        assert tc12 == ["2"] and [v.get(ox.w("val")) for v in vm] == ["restart", None]


def test_annotation_result_names_header_in_cell_label(tmp_path):
    src, doc, report = build_report(tmp_path, monthly=True)
    res = annotate_docx(report, src, tmp_path / "copy.annotated.docx")
    assert res.status == "written" and res.complete
    got = {(a.finding_id, a.ref): (a.label, a.precision, (a.covered or {}).get("text")) for a in res.anchors}
    assert got == {
        ("F-UNIT", "t1.r1.c2"): ("Таблица 1, строка 1, столбцы 2–3", "exact", DAILY),
        ("F-EXC", "t1.r3.c4"): ("Таблица 1, строка 3, столбец 4 «Условие»", "exact", EXCEPTION),
        ("F-UNIT", "t1.r4.c2"): (f"Таблица 1, строка 4, столбец 2 «{SUM_HEAD}»", "exact", MONTHLY),
    }


# ------------------------------------------------------- штатный вход движка


def _run_cli(engine, cli, monkeypatch, src, out_md, script_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    code = cli.main([str(src), str(out_md), "--provider", "mock", "--mock-script", str(script_path),
                     "--export", "docx", "--no-cache", "--cache-dir", str(out_md.parent / "cache"), "-q"])
    assert code == 0
    return json.loads(out_md.with_suffix(".json").read_text(encoding="utf-8"))


def test_engine_cli_both_versions_keep_header_row_cell_link(tmp_path, monkeypatch):
    """``python -m bcc_review IN OUT --provider mock --mock-script … --export docx`` для обеих версий."""
    engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration ещё не влит в эту ветку")
    cli = pytest.importorskip("bcc_review.cli")
    reports = {}
    for name, monthly in (("limits", False), ("limits_month", True)):
        src = limits_doc(tmp_path / f"{name}.docx", monthly=monthly)
        script = tmp_path / f"{name}.mock.json"
        script.write_text(json.dumps(limits_mock_script(read_docx(src)), ensure_ascii=False), encoding="utf-8")
        rep = _run_cli(engine, cli, monkeypatch, src, tmp_path / name / "report.md", script)
        out = tmp_path / name / "report.annotated.docx"
        assert rep["exports"]["docx"] == str(out) and rep["document"]["id"] == sha(src)
        assert rep["run"]["modules"]["read_docx"].startswith("team:bcc_review.readers.docx")
        assert rep["run"]["modules"]["provider"].endswith("MockAdapter")
        # связь в report.json (после normalize_document движка) и в повторно открытой копии
        assert cell_map(rep["document"]) == cell_map(read_docx(out)) == expected_cells(monthly)
        assert all(b["loc"]["columns"] == LIMITS_COLUMNS for b in rep["document"]["blocks"] if b["loc"].get("table"))
        reports[name] = (src, out, rep)

    for name, (src, out, rep) in reports.items():
        blocks = {b["id"]: b for b in rep["document"]["blocks"]}
        new = sorted(set(ox.comments(out)) - set(ox.comments(src)))
        rmap = ox.range_map(out, new, read_docx(out))
        by_title = {f["title"]: f for f in rep["findings"]}
        wanted = [(LIMITS_EXCEPTION, "t1.r3.c4", EXCEPTION)]
        if name == "limits_month":
            wanted += [(LIMITS_CONFLICT, "t1.r1.c2", DAILY), (LIMITS_CONFLICT, "t1.r4.c2", MONTHLY)]
        else:
            assert LIMITS_CONFLICT not in by_title
        for title, cref, quote in wanted:
            f = by_title[title]
            ev = [e for e in f["evidence"] if locate(blocks[e["block_id"]], e["start"], e["end"])["ref"] == cref]
            assert len(ev) == 1 and ev[0]["quote"] == quote, (title, cref, f["evidence"])
            ev = ev[0]
            hits = [r for r in rmap.values() if r["head"].startswith(f"[{f['id']}]")
                    and (r["block_id"], r["start"], r["end"]) == (ev["block_id"], ev["start"], ev["end"])]
            assert len(hits) == 1, (title, cref)
            row, col = int(cref.split(".r")[1].split(".c")[0]), int(cref.rsplit(".c", 1)[1])
            assert hits[0]["start_node"] == hits[0]["end_node"] == cell_path(row, col)
            assert hits[0]["covered"] == quote
        if name == "limits_month":
            changed = [r for r in rmap.values() if r["start_node"] == cell_path(4, 2)]
            assert len(changed) == 1
            assert f"Место: Таблица 1, строка 4, столбец 2 «{SUM_HEAD}»; строка «Л-2. Покупки в интернете»" \
                in changed[0]["body"]


# ------------------------------------------------------------ LibreOffice


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) не установлен")
def test_libreoffice_reopens_copy_comment_stays_in_changed_cell(tmp_path):
    from lxml import etree
    from test_p03_case import _odt_annotations, _soffice

    src, doc, report = build_report(tmp_path, monthly=True)
    out = tmp_path / "limits_month.annotated.docx"
    annotate_docx(report, src, out)
    odt = _soffice(out, tmp_path, "odt")
    ns = {"office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
          "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
          "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
    root = etree.fromstring(zipfile.ZipFile(odt).read("content.xml"))
    tables = root.xpath("//table:table", namespaces=ns)
    assert len(tables) == 1
    rows = tables[0].xpath(".//table:table-row", namespaces=ns)
    found = {}
    for ri, tr in enumerate(rows, start=1):
        for ci, tc in enumerate(tr.xpath("table:table-cell|table:covered-table-cell", namespaces=ns), start=1):
            for ann in tc.xpath(".//office:annotation", namespaces=ns):
                first = ann.xpath("string(text:p[1])", namespaces=ns)  # без dc:creator / dc:date
                found[(ri, ci)] = first.split("]")[0] + "]"
    assert found == {(1, 2): "[F-UNIT]", (3, 4): "[F-EXC]", (4, 2): "[F-UNIT]"}
    # объединения LibreOffice видит те же: «Лимит за сутки» на 2 столбца, «Правило» на 2 строки
    def cell_text(c):  # текст ячейки без встроенного office:annotation
        return "".join(t for t in c.xpath(".//text()[not(ancestor::office:annotation)]", namespaces=ns))

    first = rows[0].xpath("table:table-cell", namespaces=ns)
    span = [(cell_text(c), c.get("{%s}number-columns-spanned" % ns["table"]),
             c.get("{%s}number-rows-spanned" % ns["table"])) for c in first]
    assert span == [("Правило", None, "2"), ("Лимит " + DAILY, "2", None), ("Условие", None, "2")]
    # диапазоны: три опоры и сводка на заголовке (первый блок -- заголовок)
    assert sorted(_odt_annotations(odt).values()) == sorted([doc.blocks[0].text, DAILY, EXCEPTION, MONTHLY])
