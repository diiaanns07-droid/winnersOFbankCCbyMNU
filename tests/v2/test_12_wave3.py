"""Тесты №12, волна 3: обещанные операции без метода, единицы поля API ↔ требования, размытые НФТ,
скорость правил. Документы — свои фикстуры другого стиля (не из открытого набора №18), чтобы проверить
обобщение, а не подгонку."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import rules  # noqa: E402
from bcc_review.v2.rules._text import norm  # noqa: E402
from bcc_review.v2.rules._view import fallback_load  # noqa: E402

STYLES = ROOT / "tests" / "v2" / "fixtures" / "12_styles"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
CORPUS = ROOT / "evaluation" / "dev" / "corpus" / "cases"


def _run(path: Path) -> dict:
    return rules.run(fallback_load(path))


def _by_rule(out: dict, prefix: str) -> list[dict]:
    return [c for c in out["candidates"] if c["source"].startswith("rules:" + prefix)]


def _quotes_ok(path: Path, out: dict) -> None:
    raw = path.read_text(encoding="utf-8").splitlines()
    for c in out["candidates"]:
        for e in c["evidence"]:
            assert norm(e["quote"]) in norm(raw[e["line"] - 1]), (c["title"], e)


@pytest.fixture(scope="module")
def defects() -> dict:
    return _run(STYLES / "wave3_defects.md")


@pytest.fixture(scope="module")
def clean() -> dict:
    return _run(STYLES / "wave3_clean.md")


def test_promised_operation_without_method(defects: dict) -> None:
    got = _by_rule(defects, "promises.promised_ops")
    assert len(got) == 1
    c = got[0]
    assert c["severity"] == "critical" and c["kind"] == "missing_element" and c["blocks"] == "development"
    assert "переносит дату доставки" in c["title"]
    # описанные операции (создание, статус) не попадают в список отсутствующих
    assert "создаёт" not in c["title"] and "получает" not in c["title"]
    assert {e["line"] for e in c["evidence"]} >= {18}
    _quotes_ok(STYLES / "wave3_defects.md", defects)


def test_promised_operation_silent_when_spare_method_exists(clean: dict) -> None:
    # PATCH «Изменение заявки» назван другими словами, но свободный метод изменения есть — не гадаем
    assert not _by_rule(clean, "promises.")


def test_field_units_duration_and_rate(defects: dict) -> None:
    got = {c["source"]: c for c in _by_rule(defects, "units.field_unit")}
    assert set(got) == {"rules:units.field_unit.storagePeriod", "rules:units.field_unit.penaltyRate"}
    term = got["rules:units.field_unit.storagePeriod"]
    assert "недели" in term["title"] and "дни" in term["title"]
    assert term["rule_conflict"] and len(term["evidence"]) == 2
    assert term["rewrite"] == "Срок хранения карты в отделении в днях"
    rate = got["rules:units.field_unit.penaltyRate"]
    assert "% годовых" in rate["title"] and "% в день" in rate["title"]
    for c in got.values():
        assert c["severity"] == "major" and c["kind"] == "unit_mismatch"


def test_field_units_silent_on_clean(clean: dict) -> None:
    assert not _by_rule(clean, "units.")


def test_nfr_vague_reliability_words(defects: dict, clean: dict) -> None:
    got = _by_rule(defects, "language.nfr_unverifiable")
    assert len(got) == 1 and "бесперебойно" in got[0]["title"]
    assert not _by_rule(clean, "language.")


def test_clean_style_has_no_candidates(clean: dict) -> None:
    assert clean["candidates"] == []


def test_new_rules_silent_on_corpus_clean_documents() -> None:
    bases = sorted(p for p in CORPUS.glob("*") if p.name.endswith(".base") or ".paraphrase" in p.name)
    assert len(bases) == 8
    for case in bases:
        out = _run(case / "source.md")
        new = [c for c in out["candidates"]
               if c["source"].startswith(("rules:promises.promised_ops", "rules:units.field_unit",
                                          "rules:language.nfr_unverifiable"))]
        assert new == [], (case.name, [c["title"] for c in new])


def test_official_document_unchanged_by_new_rules() -> None:
    out = _run(OFFICIAL)
    assert not _by_rule(out, "promises.promised_ops")
    assert not _by_rule(out, "units.field_unit")
    # обещанное чтение по-прежнему отдельным кандидатом (К4 официального эталона)
    assert len(_by_rule(out, "promises.read_operation")) == 1


def test_rules_fast_on_long_document(tmp_path: Path) -> None:
    """Правила — доли секунды на документе 600+ строк (официальный документ четыре раза подряд)."""
    text = OFFICIAL.read_text(encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_text("\n".join([text] * 4), encoding="utf-8")
    view = fallback_load(big)
    assert len(view["lines"]) > 600
    t0 = time.perf_counter()
    rules.run(view)
    assert time.perf_counter() - t0 < 1.5
