"""Стык с bcc/integration: движок вызывает наш write_pdf, ридеры движка дают loc контракта v1."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf
import pytest

import p14_fixtures as fx
from p14_helpers import by_finding, close
from bcc_review.exports.pdf import MANIFEST_NAME, export_pdf, read_annotations, verify_export

engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration не подключён")
from bcc_review.contracts import RunOptions, evidence_errors, validate  # noqa: E402

FIX = fx.ROOT / "tests" / "integration" / "fixtures"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(engine, "SLEEP", lambda s: None)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)


def _manifest(path: Path) -> dict:
    with pymupdf.open(path) as d:
        return json.loads(d.embfile_get(MANIFEST_NAME))


@pytest.mark.skipif(not (FIX / "mock_bcc.json").exists(), reason="нет tests/integration/fixtures/mock_bcc.json")
@pytest.mark.parametrize("name", ["bcc_requirements.md", "bcc_requirements.pdf"])
def test_engine_exports_annotated_pdf(tmp_path, name):
    src = tmp_path / name
    shutil.copyfile(FIX / name, src)
    opts = {"provider": "mock", "mock_script": str(FIX / "mock_bcc.json"), "exports": ["pdf"],
            "cache_dir": str(tmp_path / "cache"), "artifacts_dir": str(tmp_path / "art")}
    rep = engine.run_review(src, tmp_path / "report.md", options=RunOptions.coerce(opts))
    validate(rep)
    assert evidence_errors(rep) == []
    assert not [w for w in rep["warnings"] if "экспорт pdf" in json.dumps(w, ensure_ascii=False)]
    out = Path(rep["exports"]["pdf"])
    assert out.name == "report.annotated.pdf" and out.is_file()
    res = verify_export(out, src, rep)
    assert res["ok"], res["errors"]

    annots = read_annotations(out)
    with_ev = [f for f in rep["findings"] if f["evidence"]]
    assert with_ev, "mock-сценарий должен давать замечания с опорами"
    for f in with_ev:
        assert by_finding(annots, f["id"]), f"{f['id']} не выделено"
        if f.get("witness"):
            roles = {a["name"].split(":")[2] for a in by_finding(annots, f["id"])}
            assert {"a", "b"} <= roles, f"{f['id']}: нет обеих сторон противоречия"

    m = _manifest(out)
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    for p in m["placements"]:
        assert p["status"] == "highlight", p
        if name.endswith(".pdf"):
            assert p["method"].startswith("fragment_")
            b = blocks[p["block_id"]]
            assert p["page"] == b["loc"]["page"]
            # выделение лежит в объединении fragments, которые пересекают цитату: у резервного
            # ридера fragment — строка, у ридера №02 — слово (полоса по строке шире одного слова)
            hit = [pymupdf.Rect(fr["rect"]) for fr in b["loc"]["fragments"]
                   if fr["start"] < p["end"] and fr["end"] > p["start"]]
            assert hit, p
            area = hit[0]
            for r in hit[1:]:
                area |= r
            for q in p["rects"]:
                assert (area + (-2, -2, 2, 2)).contains(pymupdf.Rect(q)), (p["finding_id"], q, list(area))
        else:
            assert p["method"] == "loc_map"


def _reader_blocks(md: Path) -> list[dict]:
    text_reader = pytest.importorskip("bcc_review.runtime.fallback.text_reader")
    return text_reader.read_text(md)["blocks"]


def test_loc_map_gives_exact_columns(tmp_path, case_md):
    blocks = _reader_blocks(case_md)
    lines = case_md.read_text(encoding="utf-8").splitlines()
    l_f1 = next(i for i, s in enumerate(lines, 1) if "**Ф-1.**" in s)
    l_dup = [i for i, s in enumerate(lines, 1) if "Порог задаётся в тенге" in s][1]
    pick = {b["loc"]["line_start"]: b for b in blocks}
    b1, bd = pick[l_f1], pick[l_dup]
    assert b1["loc"]["map"] and "**" not in b1["text"]
    rep = fx._skeleton(fx.sha256(case_md), "map", "markdown", blocks)
    rep["findings"] = [
        fx._finding("F-01", "critical", "t", [fx.ev(b1, "от 1 000 до 1 000 000 ₸")]),
        fx._finding("F-03", "minor", "t", [fx.ev(bd, "Порог задаётся в тенге")]),
    ]
    res = export_pdf(rep, case_md, tmp_path / "map.pdf")
    assert [p.method for p in res.placements] == ["loc_map", "loc_map"]
    ann = read_annotations(res.output_path)
    (h1,) = by_finding(ann, "F-01")
    with pymupdf.open(res.output_path) as d:
        words = d[h1["page"] - 1].get_text("words")
    seq = ["от", "1", "000", "до", "1", "000", "000", "₸"]
    i = next(i for i in range(len(words)) if [w[4] for w in words[i : i + len(seq)]] == seq)
    assert close(h1["quads"][0], pymupdf.Rect(words[i][:4]) | pymupdf.Rect(words[i + len(seq) - 1][:4]))
    (hd,) = by_finding(ann, "F-03")
    dup_page = [e["page"] for e in res.line_map[str(l_dup)] if e.get("page")][0]
    first_page = [e["page"] for e in res.line_map[str(lines.index(next(s for s in lines if "Порог задаётся в тенге" in s)) + 1)] if e.get("page")][0]
    assert hd["page"] == dup_page != first_page
