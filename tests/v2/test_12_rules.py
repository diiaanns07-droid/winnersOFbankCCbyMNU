"""Тесты №12: детерминированные правила v2 (без сети и без модели)."""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import rules  # noqa: E402
from bcc_review.v2.rules._text import norm  # noqa: E402
from bcc_review.v2.rules._view import fallback_load  # noqa: E402

OFFICIAL = ROOT / "release" / "input" / "requirements.md"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"
CORPUS = ROOT / "evaluation" / "dev" / "corpus" / "cases"

KINDS = {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"}
CRITERIA = {"necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"}


def _raw_view(path: Path) -> dict:
    """View с сырым Markdown в тексте строк: правила должны понимать и такой вид."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {"title": "", "file": path.name, "format": "md", "sha256": "", "pages": None, "warnings": [],
            "lines": [{"n": i, "text": s, "page": None, "section": ""} for i, s in enumerate(lines, 1)]}


def _quote_found(raw_lines: list[str], e: dict) -> bool:
    n = e["line"]
    q = norm(e["quote"])
    return bool(q) and 1 <= n <= len(raw_lines) and q in norm(raw_lines[n - 1])


@pytest.fixture(scope="module")
def official() -> dict:
    return rules.run(fallback_load(OFFICIAL))


def _sources(out: dict) -> set[str]:
    """Правила без уточнения предмета: «rules:api.get_mutation.saveLimit» → «rules:api.get_mutation»."""
    res = set()
    for c in out["candidates"]:
        src = c["source"]
        for base in ("rules:api.get_mutation", "rules:api.field_types", "rules:promises.named_method",
                     "rules:api.result_field_missing"):
            if src.startswith(base + "."):
                src = base
        res.add(src)
    return res


def test_official_expected_detectors(official):
    src = _sources(official)
    for need in ("rules:api.get_mutation", "rules:api.content_type_without_body", "rules:api.status_404",
                 "rules:api.status_201", "rules:api.field_types", "rules:units.currency_mix",
                 "rules:language.open_list", "rules:api.success_with_error", "rules:promises.read_operation",
                 "rules:placeholder.dash", "rules:placeholder.tbd", "rules:placeholder.checklist",
                 "rules:placeholder.approvals", "rules:placeholder.version", "rules:api.result_field_missing"):
        assert need in src, need
    assert len(official["candidates"]) <= 16


def test_official_key_evidence(official):
    by = {c["source"]: c for c in official["candidates"]}
    by.update({b: c for c in official["candidates"] for b in ("rules:api.get_mutation", "rules:api.field_types")
               if c["source"].startswith(b + ".")})
    lines = lambda s: {e["line"] for e in by[s]["evidence"]}  # noqa: E731
    assert {104, 108} <= lines("rules:api.get_mutation")           # GET + путь изменения
    assert {147, 148} <= lines("rules:api.content_type_without_body")
    assert {188, 189} <= lines("rules:api.status_404")             # 403 → «возвращается 404»
    assert {151, 165} <= lines("rules:api.status_201")             # 201 без описания, «Created» у 200
    assert {143, 156} <= lines("rules:api.field_types")            # integer ↔ string
    assert 49 in lines("rules:units.currency_mix")                 # минорные и основные единицы
    assert 151 in lines("rules:language.open_list")
    assert 171 in lines("rules:api.success_with_error")
    assert 52 in lines("rules:promises.read_operation")
    assert by["rules:api.field_types"]["title"].count("amount") == 1


def test_official_quotes_verified(official):
    raw = OFFICIAL.read_text(encoding="utf-8").splitlines()
    for c in official["candidates"]:
        assert c["evidence"], c["title"]
        for e in c["evidence"]:
            assert _quote_found(raw, e), (c["source"], e)
            assert len(e["quote"]) <= 200
    for s in official["signals"]:
        assert _quote_found(raw, s), s


def test_candidate_schema(official):
    keys = {"title", "kind", "criterion", "severity", "requirement_ids", "evidence", "problem", "scenario",
            "impact", "recommendation", "rewrite", "question", "blocks", "source"}
    for c in official["candidates"]:
        assert keys <= set(c), c["title"]
        assert c["kind"] in KINDS and c["criterion"] in CRITERIA
        assert c["severity"] in ("critical", "major", "minor")
        assert c["blocks"] in ("development", "testing", "both", "none")
        assert c["source"].startswith("rules:")
        if c["severity"] == "critical":
            assert c["scenario"] and c["impact"] and c["blocks"] != "none"
        for field in ("title", "problem", "impact", "recommendation"):
            assert c[field] and not re.search(r"[A-Za-z]{4,} [a-z]{4,} [a-z]{4,}", c[field].replace("Internal server error", "")), field
        for e in c["evidence"]:
            assert set(e) == {"quote", "line"}


def test_raw_and_clean_views_agree():
    a = rules.run(fallback_load(OFFICIAL))
    b = rules.run(_raw_view(OFFICIAL))
    assert _sources(a) == _sources(b)
    raw = OFFICIAL.read_text(encoding="utf-8").splitlines()
    for c in b["candidates"]:
        for e in c["evidence"]:
            assert _quote_found(raw, e), (c["source"], e)


def test_requirements_mapping():
    seg = json.loads(SEGMENT.read_text(encoding="utf-8"))
    out = rules.run(fallback_load(OFFICIAL), seg)
    by = {c["source"].split(".saveLimit")[0]: c for c in out["candidates"]}
    assert by["rules:api.get_mutation"]["requirement_ids"], "требования по строкам цитат"
    assert all(r.startswith("R-") for c in out["candidates"] for r in c["requirement_ids"])
    # со списком требований тоже работает
    out2 = rules.run(fallback_load(OFFICIAL), seg["requirements"])
    assert _sources(out2) == _sources(out)


def _clean_cases() -> list[str]:
    res = []
    for d in sorted(glob.glob(str(CORPUS / "*"))):
        cid = os.path.basename(d)
        if (cid.endswith(".base") or ".paraphrase" in cid) and os.path.exists(os.path.join(d, "source.md")):
            res.append(cid)
    return res


@pytest.mark.parametrize("case_id", _clean_cases())
def test_clean_documents_at_most_one(case_id):
    out = rules.run(fallback_load(CORPUS / case_id / "source.md"))
    assert len(out["candidates"]) <= 1, [c["title"] for c in out["candidates"]]
    assert not [c for c in out["candidates"] if c["severity"] == "critical"]


MUTANTS = {
    "autopay.drop_promised.no_409_status": ("rules:api.status_409", 73),
    "autopay.two_statuses.range_422": ("rules:api.status_422", 76),
    "autopay.unit_change.limit_per_hour": ("rules:units.period_mix", 28),
    "autopay.event_conflict.insufficient_funds_credit": ("rules:conflicts.event_condition", 31),
    "autopay.range_boundary.trigger_at_threshold": ("rules:conflicts.boundary_acceptance", 46),
    "cardblock.event_conflict.unblock_daily_limit": ("rules:conflicts.event_quantity", 31),
    "cardblock.range_boundary.days_400_at_30": ("rules:conflicts.boundary_range", 86),
    "cashback.event_conflict.category_effective_now": ("rules:conflicts.event_effective", 32),
    "cashback.range_boundary.cap_strict": ("rules:conflicts.boundary_acceptance", 48),
    "transfer_limit.event_conflict.cancel_no_restore": ("rules:conflicts.event_negation", 30),
    "transfer_limit.range_boundary.reaching_rejects": ("rules:conflicts.boundary_reach", 26),
    "cardblock.unit_change.blocked_at_utc": ("rules:units.timezone_mix", 79),
    "cashback.drop_promised.no_read_method": ("rules:promises.named_method", 40),
    "cashback.two_statuses.bad_category_200": ("rules:api.success_with_error", 85),
    "cashback.unit_change.accrued_in_tiyn": ("rules:units.minor_fraction", 66),
    "transfer_limit.drop_promised.no_read_method": ("rules:promises.named_method", 35),
    "transfer_limit.two_statuses.range_200_error": ("rules:api.success_with_error", 79),
    "transfer_limit.unit_change.api_limit_in_tiyn": ("rules:units.currency_mix", 77),
}


@pytest.mark.parametrize("case_id", sorted(MUTANTS))
def test_mutants_detected(case_id):
    path = CORPUS / case_id / "source.md"
    if not path.exists():
        pytest.skip("нет мутанта в корпусе")
    src, line = MUTANTS[case_id]
    out = rules.run(fallback_load(path))
    hit = [c for c in out["candidates"] if c["source"] == src or c["source"].startswith(src + ".")]
    assert hit, [c["source"] for c in out["candidates"]]
    assert line in {e["line"] for e in hit[0]["evidence"]}


def test_signals_format(official):
    sig = official["signals"]
    assert sig and all(re.fullmatch(r"S-\d{2,}", s["id"]) for s in sig)
    text = rules.format_signals(sig, audience="architect")
    assert "L104" in text and "это не готовые дефекты" in text
    assert rules.format_signals([], "qa") == "Сигналов правил нет."
    assert all(s["audience"] for s in sig)


def test_empty_and_odd_views():
    assert rules.run({"lines": []}) == {"signals": [], "candidates": []}
    out = rules.run({"lines": [{"n": 1, "text": "| | |"}, {"n": 2, "text": "```"}, {"n": 3, "text": "200."}]})
    assert "candidates" in out


BANNED = ["saveLimit", "Алматы", "push", "порог", "Ф-1", "Ф-2", "AlertsController", "limit_kzt", "cardId",
          "50 000", "Проверьте сумму", "сумму покупки"]


def test_no_document_words_in_rules_code():
    for p in (ROOT / "src" / "bcc_review" / "v2" / "rules").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for w in BANNED:
            assert w not in text, (p.name, w)


STYLES = ROOT / "tests" / "v2" / "fixtures" / "12_styles"


def test_other_style_document_detected():
    """Другой стиль ТЗ: метод «GET /path», статусы «404 Not Found — …», таблицы «Поле | Тип»."""
    out = rules.run(fallback_load(STYLES / "alt_defects.md"))
    src = _sources(out)
    for need in ("rules:api.get_mutation", "rules:api.field_types", "rules:api.status_409", "rules:api.status_403",
                 "rules:api.content_type_without_body", "rules:units.currency_mix", "rules:promises.read_operation"):
        assert need in src, need
    raw = (STYLES / "alt_defects.md").read_text(encoding="utf-8").splitlines()
    assert all(_quote_found(raw, e) for c in out["candidates"] for e in c["evidence"])


def test_other_style_clean_document():
    out = rules.run(fallback_load(STYLES / "alt_clean.md"))
    assert out["candidates"] == [], [c["title"] for c in out["candidates"]]


PAIRS = ROOT / "tests" / "p06" / "fixtures" / "pairs4x2"


@pytest.mark.parametrize("name", ["boundary", "unit", "status", "event"])
def test_compatible_pairs_have_no_conflict(name):
    """Фикстуры №06 «совместимо»: правила не должны видеть конфликт (разные величины, согласованный пересчёт,
    строка перечня другого метода)."""
    path = PAIRS / f"{name}_compatible.md"
    if not path.exists():
        pytest.skip("нет фикстуры")
    out = rules.run(fallback_load(path))
    assert not [c for c in out["candidates"] if c.get("rule_conflict")], [c["title"] for c in out["candidates"]]


@pytest.mark.parametrize("name,src", [("boundary", "rules:conflicts.boundary_range"),
                                      ("unit", "rules:units.currency_mix"), ("status", "rules:api.status_422")])
def test_conflict_pairs_detected(name, src):
    path = PAIRS / f"{name}_conflict.md"
    if not path.exists():
        pytest.skip("нет фикстуры")
    out = rules.run(fallback_load(path))
    assert any(c["source"] == src or c["source"].startswith(src + ".") for c in out["candidates"])


def test_control_case_two_boundaries():
    case = ROOT / "evaluation" / "dev" / "controls" / "cases"
    paths = list(case.glob("*/source.md"))
    if not paths:
        pytest.skip("нет контрольного кейса")
    out = rules.run(fallback_load(paths[0]))
    lines = [{e["line"] for e in c["evidence"]} for c in out["candidates"] if "boundary" in c["source"]]
    assert {61, 25} in [x & {61, 25} for x in lines] and any({86, 25} <= x for x in lines)
