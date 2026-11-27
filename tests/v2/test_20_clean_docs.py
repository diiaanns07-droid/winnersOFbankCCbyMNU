"""№20: набор действительно чистых ТЗ `evaluation/v2/clean/` — эталон пустой и совпадает с документом,
заглушек шаблона нет, PDF и DOCX собраны, счётчик и раннер новых ТЗ видят кейсы как чистые."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
CLEAN = ROOT / "evaluation" / "v2" / "clean"
CASES = sorted(p for p in CLEAN.iterdir() if p.is_dir() and (p / "source.md").is_file()) if CLEAN.is_dir() else []


def test_clean_set_has_v2_editions_and_new_domains():
    names = {p.name for p in CASES}
    assert {f"{b}_v2" for b in ("grace", "qr", "capital", "insurance")} <= names, names
    assert len([n for n in names if not n.endswith("_v2")]) >= 4, names


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_gold_is_empty_and_matches_source(case):
    from evaluation.v2.clean import build

    text = (case / "source.md").read_text(encoding="utf-8")
    gold = yaml.safe_load((case / "gold.yaml").read_text(encoding="utf-8"))
    assert gold == build.gold_for(case, text), "gold.yaml устарел: python -m evaluation.v2.clean.build"
    assert gold["items"] == [] and gold["variant"] == "clean"
    assert gold["expected_verdict"] == {"development": "yes", "testing": "yes"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_source_is_a_filled_template_of_the_right_size(case):
    from evaluation.v2.clean import build

    text = (case / "source.md").read_text(encoding="utf-8")
    assert build.placeholder_hits(text) == []
    n = len(build.doc_lines(text))
    assert 120 <= n <= 240, n
    for heading in ("## Часть A. Новый функционал", "### Критерии приемки", "## Часть B. REST API", "### Статусы"):
        assert heading in text, heading
    assert re.search(r"\*\*Ф-1\.\*\*", text)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_pdf_and_docx_are_built(case):
    for fmt in ("pdf", "docx"):
        p = case / f"source.{fmt}"
        assert p.is_file() and p.stat().st_size > 5000, p


def test_score_and_newtz_runner_see_clean_cases():
    from evaluation.v2 import newtz, score

    found = {c["case"]: c for c in newtz.discover(CLEAN)}
    for case in CASES:
        assert found[case.name]["variant"] == "clean"
        g = score.load_gold(case / "gold.yaml")
        assert g["items"] == []
