"""Стыковой тест №13 с контрактом v1 (``contracts/v1.json``, ``bcc_review.contracts``).

* синтетическая фикстура №13 во всех вариантах проходит ``validate`` и ``evidence_errors``;
* эталонный ``contracts/examples/minimal_report.json`` (Max) превращается в HTML: каждая
  опора подсвечена, текст блоков и якоря на месте;
* если в checkout появятся реальные ``report.json`` прогонов, они тоже собираются.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bcc_review.exports import html as H
from fixture_builder import VARIANTS
from test_html_unit import parse, view_model

C = pytest.importorskip("bcc_review.contracts", reason="контракт v1 ещё не в checkout (bcc/integration)")

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_fixture_variants_satisfy_contract(name):
    report = VARIANTS[name]()
    C.validate(report)
    assert C.evidence_errors(report) == []


def test_schema_file_matches_contract_module():
    assert (ROOT / "contracts" / "v1.json").read_text(encoding="utf-8") == C.schema_json()


def test_enums_have_russian_labels():
    for kind in C.FINDING_KINDS:
        assert kind in H.KIND
    for crit in C.INDIVIDUAL_CRITERIA + C.SET_CRITERIA:
        assert crit in H.CRITERIA_DEFAULT
    for s in C.READINESS:
        assert s in H.READINESS
    for s in C.MEANING_STATUSES:
        assert s in H.MEANING
    for s in C.CHECK_MARKS + C.CHECK_STATUSES + C.COVERAGE_STATUSES + C.STAGE_STATUSES + C.REVIEW_STATUSES:
        assert s in H.VALUE_LABELS or s == "partial"


def test_contract_example_renders():
    if not EXAMPLE.is_file():
        pytest.skip("нет contracts/examples/minimal_report.json")
    report = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    text = H.render_html(report)
    c = parse(text)
    vm = view_model(text)
    for b in report["document"]["blocks"]:
        assert c.texts[b["id"]] == b["text"]
        assert f'id="{H.block_anchor(b["id"])}"' in text
    assert all(ev["ok"] for ev in vm["ev"].values())
    for ev_id, ev in vm["ev"].items():
        assert c.ev_text[ev_id] == ev["q"]
    conflict = next(f for f in report["findings"] if f.get("witness"))
    card = text[text.index(f'id="{H.finding_anchor(conflict["id"])}"') :]
    card = card[: card.index("</article>")]
    assert 'data-side="a"' in card and 'data-side="b"' in card
    # Точная строка источника берётся из loc.map.
    line = report["document"]["blocks"][2]["loc"]["line_start"]
    assert re.search(rf"строка {line}\b", card)


def test_real_reports_if_present(tmp_path):
    """Реальные report.json прогонов (Max, №18), если они лежат в checkout, собираются без ошибок."""
    candidates = (sorted(ROOT.glob("release/reports/**/*.json")) + sorted(ROOT.glob("reports/**/*.json"))
                  + sorted(ROOT.glob("runs/**/report.json")))
    candidates = [p for p in candidates if ".artifacts" not in p.parts[-2] and "stages" not in p.parts]
    reports = [p for p in candidates if '"schema_version"' in p.read_text(encoding="utf-8", errors="ignore")[:4000]]
    if not reports:
        pytest.skip("реальных report.json в checkout нет")
    for path in reports[:6]:
        rep = json.loads(path.read_text(encoding="utf-8"))
        text = H.write_html(path, tmp_path / (path.stem + ".html")).read_text(encoding="utf-8")
        c = parse(text)
        assert all(c.texts[b["id"]] == b["text"] for b in rep["document"]["blocks"]), path
        vm = view_model(text)
        assert all(c.ev_text[k] == ev["q"] for k, ev in vm["ev"].items() if ev["ok"]), path
