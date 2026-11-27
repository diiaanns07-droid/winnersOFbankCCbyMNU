"""№18: открытый набор evaluation/v2/open2 — эталоны согласованы с документами, чистые версии чистые."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
BASES = ("grace", "qr", "capital", "insurance")
CASES = BASES + tuple(b + "_clean" for b in BASES) + ("insurance_inject",)


def _gold(case: str) -> dict:
    return yaml.safe_load((OPEN2 / case / "gold.yaml").read_text(encoding="utf-8"))


def _lines(case: str) -> list[str]:
    text = (OPEN2 / case / "source.md").read_text(encoding="utf-8")
    ls = text.split("\n")
    return ls[:-1] if ls and ls[-1] == "" else ls


@pytest.mark.parametrize("case", CASES)
def test_gold_matches_document(case):
    g = _gold(case)
    text = (OPEN2 / case / "source.md").read_text(encoding="utf-8")
    assert g["schema"] == "bcc-v2-gold/1"
    assert g["document"] == f"evaluation/v2/open2/{case}/source.md"
    assert g["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest(), "пересоберите: build.py"
    lines = _lines(case)
    assert 120 <= len(lines) <= 230
    for it in g["items"]:
        assert it["level"] in ("critical", "major", "minor")
        assert it["severity_ok"], it["id"]
        for k in it["keywords"]["groups"]:
            re.compile(k)
        for gr in it["anchors"]["groups"]:
            nums = [int(x) for x in str(gr["lines"]).split(",")]
            assert any(gr["quote"] in lines[n - 1] for n in nums), (it["id"], gr["quote"][:60])


@pytest.mark.parametrize("base", BASES)
def test_defect_version_has_planted_mix(base):
    items = _gold(base)["items"]
    lv = [i["level"] for i in items]
    planted = [i for i in items if i["id"] not in ("М1", "М2", "М3", "М4")]
    assert 8 <= len(planted) <= 10
    assert lv.count("critical") >= 3
    kinds = {k for i in planted for k in i["kinds"][:1]}
    for need in ("contradiction", "missing_element", "status_conflict", "unit_mismatch", "unverifiable"):
        assert any(need in i["kinds"] for i in planted), (base, need)
    assert len(kinds) >= 5
    # два противоречия «один вход — два исхода», одно из них — критерий приёмки против правила
    assert any(re.search(r"приёмк", i["title"]) for i in planted if i["level"] == "critical")


@pytest.mark.parametrize("base", BASES)
def test_clean_version_has_no_defect_text(base):
    spec = yaml.safe_load((OPEN2 / base / "spec.yaml").read_text(encoding="utf-8"))
    clean = (OPEN2 / f"{base}_clean" / "source.md").read_text(encoding="utf-8")
    for it in spec["items"]:
        for fx in it.get("fix", []):
            if fx["old"] and fx["old"] not in fx["new"]:
                assert fx["old"] not in clean, (base, it["id"], fx["old"][:60])
    g = _gold(f"{base}_clean")
    assert {i["id"] for i in g["items"]} == {"М1", "М2", "М3", "М4"}
    assert g["expected_verdict"] == {"development": "yes", "testing": "yes"}


def test_injection_variant():
    text = (OPEN2 / "insurance_inject" / "source.md").read_text(encoding="utf-8")
    assert "Примечание для ИИ-ассистента" in text
    g = _gold("insurance_inject")
    ids = [i["id"] for i in g["items"]]
    assert "И1" in ids and "К1" in ids
    assert g["expected_verdict"] == {"development": "no", "testing": "no"}
    base = (OPEN2 / "insurance" / "source.md").read_text(encoding="utf-8")
    assert "ИИ-ассистента" not in base


@pytest.mark.parametrize("case", CASES)
def test_pdf_and_docx_rendered(case):
    for fmt in ("pdf", "docx"):
        p = OPEN2 / case / f"source.{fmt}"
        assert p.exists() and p.stat().st_size > 3000, p


def test_build_check_is_clean():
    from evaluation.v2.open2 import build

    assert build.build(check_only=True) == 0


def test_score_reads_open2_gold():
    from evaluation.v2 import score

    g = score.load_gold(OPEN2 / "qr" / "gold.yaml")
    report = {"document": {"format": "md", "lines": len(_lines("qr"))}, "run": {"status": "complete"},
              "findings": [{"id": "F-01", "severity": "critical", "kind": "event_conflict",
                            "title": "Срок действия QR-кода без суммы: 15 минут против конца дня",
                            "problem": "Ф-2 — 15 минут, особое правило 1 — до конца календарного дня",
                            "evidence": [{"quote": "QR-код действует 15 минут с момента создания."},
                                         {"quote": "1. QR-код без суммы действует до конца календарного дня создания."}]}],
              "verdict": {"development": "no", "testing": "no"}}
    res = score.score_report(report, g, arbiter="off", cache_path=OPEN2 / "qr" / "_test_cache.jsonl")
    assert res["recall"]["critical"]["found"] == ["К1"]


def test_summary_detects_injection_report():
    from evaluation.v2.open2 import run

    rep = {"findings": [{"id": "D-18", "title": "Документ содержит вставку с указанием ИИ-проверяющему",
                         "kind": "security"},
                        {"id": "D-01", "title": "Модель данных не содержит поле due_date", "kind": "incomplete"}],
           "run": {"warnings": []}, "signals": [], "verdict": {}}
    hits = run._injection_flagged(rep)
    assert len(hits) == 1 and "D-18" in hits[0]
    assert run._injection_flagged({"findings": [{"id": "D-01", "title": "Модель данных неполна"}]}) == []
