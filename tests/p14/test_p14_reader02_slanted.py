"""Стык с настоящим ридером №02 (claude/youthful-mayer-67swfl @ 288d727).

Фикстура `fixtures/slanted_case.pdf` (генератор `fixtures/make_slanted_case.py`) содержит две
страницы. На стр. 1 и стр. 2 стоит одна и та же фраза о пороге с разными суммами. Стр. 2 имеет
CropBox и /Rotate 90, на ней две близкие наклонные строки (15°). Соседняя строка B лежит внутри
осевого прямоугольника цитаты из строки A.

Document — вывод `read_pdf` ридера №02 @ 288d727 (`fixtures/slanted_case.document.json`), поэтому
тест повторяется без нового коммита №02. Если ридер установлен, PDF перечитывается и сверяется
с закреплённым выводом.

Эталон местоположения — только генератор (`slanted_case.geometry.json`, вершины из матрицы Tm
и ширин шрифта) и независимая отрисовка (PDFium, poppler). Координаты экспорта эталоном не служат.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

import p14_fixtures as fx
from bcc_review.exports.pdf import NM_PREFIX, export_pdf, verify_export

FIX = Path(__file__).resolve().parent / "fixtures"
PDF = FIX / "slanted_case.pdf"
GEO = json.loads((FIX / "slanted_case.geometry.json").read_text(encoding="utf-8"))
PINNED = json.loads((FIX / "slanted_case.document.json").read_text(encoding="utf-8"))
MOCK = FIX / "slanted_mock_script.json"
QA, QB, QN = GEO["quads"]["a"], GEO["quads"]["b"], GEO["quads"]["neighbour"]
TOL = 1.0  # pt


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reader():
    try:
        from bcc_review.readers import pdf as reader
    except ImportError:
        return None
    return reader


@pytest.fixture(scope="module")
def reader_used() -> dict:
    meta = PINNED["_reader"]
    r = _reader()
    used = {"pinned": meta, "loaded_module": getattr(r, "__file__", None), "loaded_version": getattr(r, "READER_VERSION", None)}
    print("\n[p14] ридер №02:", json.dumps(used, ensure_ascii=False))
    return used


def _document() -> dict:
    return {k: v for k, v in PINNED.items() if not k.startswith("_")}


def _block(doc: dict, quote: str, page: int) -> dict:
    hits = [b for b in doc["blocks"] if quote in b["text"] and b["loc"]["page"] == page]
    assert len(hits) == 1, (quote, page, len(hits))
    return hits[0]


CONTROL = {"id": "b9001", "kind": "paragraph", "section": [], "text": "Порог уведомления:", "loc": {"page": 2}}


def _report(doc: dict) -> dict:
    """Одна находка с двумя опорами из реального Document и контроль «страница без координат»."""
    ba, bb = _block(doc, QA["quote"], 1), _block(doc, QB["quote"], 2)
    ea, eb = fx.ev(ba, QA["quote"]), fx.ev(bb, QB["quote"])
    rep = fx._skeleton(doc["id"], doc["title"], "pdf", doc["blocks"] + [dict(CONTROL)])
    rep["document"]["warnings"] = doc["warnings"]
    rep["findings"] = [
        fx._finding(
            "F-01", "critical", "Порог 50 000 ₸ на стр. 1 противоречит 70 000 ₸ на стр. 2", [ea, eb],
            scope="set", kind="conflict", criterion="set_consistent", req_ids=[],
            witness={"input": "расходы 60 000 ₸ за месяц", "outcome_a": "push отправлен (порог 50 000 ₸)",
                     "outcome_b": "push не отправлен (порог 70 000 ₸)", "evidence_a": ea, "evidence_b": eb},
        ),
        # контроль: у блока есть только страница (ридер не дал координаты слов), а фраза на стр. 2
        # встречается дважды — точного места нет, нужна заметка с причиной
        fx._finding("F-02", "major", "Контроль: опора без координат", [fx.ev(CONTROL, "Порог уведомления")],
                    req_ids=[]),
    ]
    rep["questions"] = [{"id": "Q-1", "finding_ids": ["F-01"], "prompt": "Какой порог уведомления верный?",
                         "options": ["50 000 ₸", "70 000 ₸"], "affected_req_ids": []}]
    return rep


@pytest.fixture(scope="module")
def case(tmp_path_factory, reader_used):
    tmp = tmp_path_factory.mktemp("p14slanted")
    src = tmp / "slanted_case.pdf"
    shutil.copyfile(PDF, src)
    doc = _document()
    rep = _report(doc)
    before = _sha(src)
    out = tmp / "slanted_case.annotated.pdf"
    res = export_pdf(rep, src, out)
    return {"src": src, "out": out, "report": rep, "result": res, "sha_before": before, "doc": doc}


def _highlights(path: Path, fid: str) -> list[dict]:
    """Highlight-аннотации находки после повторного открытия: страница, роль, вершины, тексты."""
    out = []
    with pymupdf.open(path) as d:
        for page in d:
            for a in page.annots():
                name = a.info.get("id") or ""
                if a.type[1] == "Highlight" and name.startswith(f"{NM_PREFIX}{fid}:"):
                    v = [list(p) for p in a.vertices]
                    out.append({"page": page.number + 1, "role": name.split(":")[2], "vertices": v,
                                "quads": [v[i : i + 4] for i in range(0, len(v), 4)], "content": a.info["content"],
                                "xref": a.xref})
    return out


def _near(p, q) -> bool:
    return abs(p[0] - q[0]) <= TOL and abs(p[1] - q[1]) <= TOL


def _same_quad(vertices: list, ref: dict) -> bool:
    return all(_near(v, ref[k]) for v, k in zip(vertices, ("ul", "ur", "ll", "lr")))


# ---------------------------------------------------------------- ридер и Document


def test_document_comes_from_real_reader_02(reader_used):
    meta = PINNED["_reader"]
    assert meta["module"] == "bcc_review.readers.pdf" and meta["commit"].startswith("288d727")
    assert PINNED["id"] == GEO["pdf_sha256"] == _sha(PDF)
    b = _block(_document(), QB["quote"], 2)
    assert b["loc"]["rotation"] == 90 and all("quad" in f and "line" in f for f in b["loc"]["fragments"])
    contracts = pytest.importorskip("bcc_review.contracts")
    contracts.validate(_document(), "Document")


def test_installed_reader_reproduces_pinned_document(reader_used):
    r = _reader()
    if r is None:
        pytest.skip("bcc_review.readers.pdf не установлен: используется закреплённый вывод read_pdf @ 288d727")
    if r.READER_VERSION != PINNED["_reader"]["version"]:
        pytest.skip(f"установлен ридер {r.READER_VERSION}: перегенерируйте фикстуру make_slanted_case.py --document")
    fresh = r.read_pdf(PDF, ocr="off")
    assert fresh["id"] == PINNED["id"]
    assert [(b["id"], b["text"], b["loc"]["page"]) for b in fresh["blocks"]] == [
        (b["id"], b["text"], b["loc"]["page"]) for b in PINNED["blocks"]]
    for fb, pb in zip(fresh["blocks"], PINNED["blocks"]):
        assert len(fb["loc"]["fragments"]) == len(pb["loc"]["fragments"])
        for ff, pf in zip(fb["loc"]["fragments"], pb["loc"]["fragments"]):
            assert (ff["start"], ff["end"]) == (pf["start"], pf["end"])
            assert max(abs(x - y) for x, y in zip(ff["rect"], pf["rect"])) < 0.05


def test_reader_quad_agrees_with_generator():
    """Генератор и ридер согласны в системе координат (CropBox + /Rotate 90)."""
    b = _block(_document(), QB["quote"], 2)
    s = b["text"].index(QB["quote"])
    frs = [f for f in b["loc"]["fragments"] if s <= f["start"] and f["end"] <= s + len(QB["quote"])]
    first, last = frs[0]["quad"], frs[-1]["quad"]
    got = {"ul": first[0], "ur": last[1], "ll": first[2], "lr": last[3]}
    assert all(_near(got[k], QB[k]) for k in got), (got, QB)


# ---------------------------------------------------------------- геометрия выделений


def test_highlight_vertices_match_generator(case):
    hs = _highlights(case["out"], "F-01")
    by_role = {h["role"]: h for h in hs}
    assert set(by_role) == {"a", "b"}
    a, b = by_role["a"], by_role["b"]
    assert a["page"] == 1 and b["page"] == 2
    assert len(a["quads"]) == 1 and _same_quad(a["quads"][0], QA), a["quads"]
    # наклонная цитата: один четырёхугольник по строке, а не осевой прямоугольник
    assert len(b["quads"]) == 1, b["quads"]
    assert _same_quad(b["quads"][0], QB), {"got": b["quads"][0], "want": QB}


def _display(pt, page: int):
    """Экранные координаты из параметров генератора (а не из матрицы MuPDF)."""
    if page == 2:
        x0, y0, x1, y1 = GEO["crop_box"]
        return (y1 - y0 - pt[1], pt[0])  # /Rotate 90: x' = h - y, y' = x
    return tuple(pt)


def _samples(ref: dict, page: int, scale: float, nu: int = 80, nv: int = 7):
    ul, ur, ll = (_display(ref[k], page) for k in ("ul", "ur", "ll"))
    pts = []
    for i in range(nu):
        u = 0.02 + 0.96 * i / (nu - 1)
        for j in range(nv):
            v = 0.12 + 0.76 * j / (nv - 1)
            x = ul[0] + u * (ur[0] - ul[0]) + v * (ll[0] - ul[0])
            y = ul[1] + u * (ur[1] - ul[1]) + v * (ll[1] - ul[1])
            pts.append((int(x * scale), int(y * scale)))
    return pts


def _tinted(px) -> bool:
    """Розовый фон критичного выделения (≈255,133,133 при multiply), а не серое сглаживание букв."""
    r, g, b = px[:3]
    return r > 200 and r - g > 45 and r - b > 45


def _dark(px) -> bool:
    return sum(px[:3]) < 250


def _render(engine: str, path: Path, page: int, scale: float, tmp: Path):
    if engine == "mupdf":
        with pymupdf.open(path) as d:
            pix = d[page - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), annots=True)
            return lambda xy: pix.pixel(*xy)
    if engine == "pdfium":
        pdfium = pytest.importorskip("pypdfium2")
        img = pdfium.PdfDocument(str(path))[page - 1].render(scale=scale, draw_annots=True).to_pil().convert("RGB")
        return img.getpixel
    if shutil.which("pdftoppm") is None:
        pytest.skip("poppler (pdftoppm) не установлен")
    Image = pytest.importorskip("PIL.Image")
    stem = tmp / f"pp{page}"
    subprocess.run(["pdftoppm", "-cropbox", "-r", str(int(72 * scale)), "-f", str(page), "-l", str(page), "-png",
                    "-singlefile", str(path), str(stem)], check=True, capture_output=True)
    return Image.open(f"{stem}.png").convert("RGB").getpixel


def test_neighbour_is_inside_axis_box_of_quote():
    """Ловушка настоящая: соседняя строка B лежит в осевом прямоугольнике цитаты A."""
    box = pymupdf.Quad(QB["ul"], QB["ur"], QB["ll"], QB["lr"]).rect
    inside = sum(1 for x, y in _samples(QN, 1, 1.0) if box.contains(pymupdf.Point(x, y)))
    assert inside / len(_samples(QN, 1, 1.0)) > 0.3


@pytest.mark.parametrize("engine", ["mupdf", "pdfium", "poppler"])
def test_independent_render_highlights_quote_not_neighbour(case, engine, tmp_path):
    scale = 2.0
    px = _render(engine, case["out"], 2, scale, tmp_path)
    src = _render(engine, case["src"], 2, scale, tmp_path / "src") if engine != "poppler" else None
    target = [px(p) for p in _samples(QB, 2, scale)]
    neigh = [px(p) for p in _samples(QN, 2, scale)]
    t_frac = sum(map(_tinted, target)) / len(target)
    n_frac = sum(map(_tinted, neigh)) / len(neigh)
    n_dark = sum(map(_dark, neigh))
    print(f"\n[p14] {engine}: цитата подсвечена {t_frac:.0%}, соседняя строка подсвечена {n_frac:.1%}, "
          f"тёмных пикселей соседней строки {n_dark}")
    assert t_frac > 0.5, "цитата на наклонной строке не подсвечена"
    assert n_frac < 0.02, "подсветка задевает соседнюю наклонную строку"
    assert n_dark > 40, "соседняя строка не читается"
    if src is not None:
        assert not any(_tinted(src(p)) for p in _samples(QB, 2, scale)), "в исходнике подсветки быть не должно"


# ---------------------------------------------------------------- примечания, переход, контроль


def test_targets_notes_and_link(case):
    by_role = {h["role"]: h for h in _highlights(case["out"], "F-01")}
    a, b = by_role["a"], by_role["b"]
    assert "сторона A" in a["content"] and "Вторая сторона: исходный PDF, стр. 2" in a["content"]
    assert "«Порог уведомления: 70 000 ₸»" in a["content"] and "«Порог уведомления: 50 000 ₸»" in a["content"]
    assert "сторона B" in b["content"] and "Вторая сторона: исходный PDF, стр. 1" in b["content"]
    for c in (a["content"], b["content"]):
        assert c.startswith("F-01 · [!!!] КРИТИЧНО") and "Вопрос: Какой порог уведомления верный?" in c
    with pymupdf.open(case["out"]) as d:
        for pno, target in ((0, 1), (1, 0)):
            links = [x for x in d[pno].annot_xrefs() if x[1] == pymupdf.PDF_ANNOT_LINK]
            assert len(links) == 1, f"стр. {pno + 1}: ожидается одна ссылка на вторую сторону"
            lx = links[0][0]
            dest = d.xref_get_key(lx, "Dest")[1]
            m = re.fullmatch(r"\[(\d+) 0 R\s*/XYZ\s+(\S+)\s+(\S+)\s+\S+\]", dest)
            assert m and int(m.group(1)) == d[target].xref, dest
            label = [a for a in d[pno].annots() if a.type[1] == "FreeText" and "F-01" in a.info["content"]][0]
            lr = [float(v) for v in d.xref_get_key(label.xref, "Rect")[1].strip("[]").split()]
            kr = [float(v) for v in d.xref_get_key(lx, "Rect")[1].strip("[]").split()]
            assert max(abs(x - y) for x, y in zip(lr, kr)) < 0.01
            # точка перехода внутри CropBox целевой страницы (в пространстве PDF)
            x, y = float(m.group(2)), float(m.group(3))
            cb = d.xref_get_key(d[target].xref, "CropBox")[1]
            if cb != "null":
                bx0, by0, bx1, by1 = (float(v) for v in cb.strip("[]").split())
                assert bx0 <= x <= bx1 and by0 <= y <= by1, (x, y, cb)


def test_page_without_coordinates_gets_explicit_note(case):
    assert not _highlights(case["out"], "F-02")
    with pymupdf.open(case["out"]) as d:
        notes = [(p.number + 1, a.info["content"]) for p in d for a in p.annots()
                 if a.type[1] == "Text" and (a.info.get("id") or "").startswith(f"{NM_PREFIX}F-02:")]
    assert [n[0] for n in notes] == [2]
    text = notes[0][1]
    assert text.startswith("БЕЗ ТОЧНОЙ ПРИВЯЗКИ:") and "2 раза" in text, text
    assert "нет координат" in text, text
    pl = [p for p in case["result"].placements if p.finding_id == "F-02"][0]
    assert pl.status == "note" and pl.page == 2


def test_verify_export_old_comment_and_source_sha(case):
    res = verify_export(case["out"], case["src"], case["report"])
    print("\n[p14] verify_export:", json.dumps(res, ensure_ascii=False))
    assert res["ok"], res["errors"]
    assert _sha(case["src"]) == case["sha_before"] == case["report"]["document"]["id"]
    with pymupdf.open(case["src"]) as s, pymupdf.open(case["out"]) as d:
        old = [(a.info["content"], tuple(round(v, 2) for v in a.rect)) for a in s[0].annots()]
        new = [(a.info["content"], tuple(round(v, 2) for v in a.rect)) for a in d[0].annots()]
    assert old == [(GEO["old_comment"], old[0][1])] and old[0] in new


# ---------------------------------------------------------------- штатный путь --export pdf


@pytest.mark.skipif(_reader() is None, reason="в этой копии нет ридера №02 (bcc_review.readers.pdf)")
def test_cli_export_pdf_with_real_reader(tmp_path):
    pytest.importorskip("bcc_review.engine")
    src = tmp_path / "slanted_case.pdf"
    shutil.copyfile(PDF, src)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
    # Ридер №02, привязка №07 и экспорт №14 — командные. Этапы анализа — резервные: их формат
    # понимает mock-сценарий (командные №04–06 ждут другой схемы ответов). Внешних вызовов нет.
    env["BCC_FORCE_FALLBACK"] = "build_inventory,review_individual,review_set,reconcile_facts"
    cmd = [sys.executable, "-m", "bcc_review", "--engine", "v1", str(src), str(tmp_path / "report.md"), "--provider", "mock",
           "--mock-script", str(MOCK), "--export", "pdf", "--no-cache", "--cache-dir", str(tmp_path / "cache"),
           "--artifacts-dir", str(tmp_path / "art"), "-q"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    mods = rep["run"].get("modules") or {}
    print("\n[p14] run.modules:", json.dumps(mods, ensure_ascii=False))
    assert mods.get("read_pdf") == "team:bcc_review.readers.pdf:read_pdf"
    assert mods.get("resolve_candidate", "").startswith("team:") and mods.get("provider") == "runtime.mock:MockAdapter"
    out = Path(rep["exports"]["pdf"])
    assert out.name == "report.annotated.pdf"
    conflict = [f for f in rep["findings"] if f.get("witness")]
    assert len(conflict) == 1
    w = conflict[0]["witness"]
    assert (w["evidence_a"]["block_id"], w["evidence_b"]["block_id"]) == ("b0001", "b0004")
    res = verify_export(out, src, rep)
    assert res["ok"], res["errors"]
    hs = {h["role"]: h for h in _highlights(out, conflict[0]["id"])}
    assert hs["a"]["page"] == 1 and _same_quad(hs["a"]["quads"][0], QA)
    assert hs["b"]["page"] == 2 and len(hs["b"]["quads"]) == 1 and _same_quad(hs["b"]["quads"][0], QB)
