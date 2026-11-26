"""Тесты линзы «Архитектор» (№07): промпт, схема ответа, постобработка, записанные живые ответы.

Сеть не нужна: живые ответы sonnet и haiku на официальном документе записаны в
`tests/v2/fixtures/07_official/` и проверяются по схеме и по цитатам.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import importlib.util

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_lens():
    """Модуль линзы по пути файла: тест не зависит от установки пакета и от каркаса №01."""
    path = ROOT / "src" / "bcc_review" / "v2" / "stages" / "lens_architect.py"
    spec = importlib.util.spec_from_file_location("lens_architect_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


la = _load_lens()
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "lens_architect.md"
DOC = ROOT / "release" / "input" / "requirements.md"
FIX = ROOT / "tests" / "v2" / "fixtures" / "07_official"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"

# Слова и имена официального документа: промпт обязан работать на любом ТЗ (анти-подгонка).
OFFICIAL_WORDS = ["push", "пуш", "savelimit", "тиын", "порог", "алмат", "ф-1", "ф-2", "ф-3", "ф-4",
                  "alertscontroller", "limit_kzt", "cardid", "проверьте сумму", "карта не найдена",
                  "сервис расходов", "учёт расходов", "уведомление о расходах", "demo-42", "₸"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[«»“”„\"']", '"', s)
    s = re.sub(r"[—–‑−]", "-", s)
    s = re.sub(r"\*\*|__|`", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _doc_lines() -> list[str]:
    out = []
    for raw in DOC.read_text(encoding="utf-8").splitlines():
        t = re.sub(r"\*\*|__|`", "", raw).rstrip()
        t = re.sub(r"^\s*[*-]\s+", "", t)
        t = re.sub(r"^#+\s*", "", t)
        if t.strip().startswith("|") and t.strip().endswith("|"):
            cells = [c.strip() for c in t.strip().strip("|").split("|")]
            t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
        out.append(_norm(t))
    return out


def _quote_found(lines: list[str], quote: str) -> bool:
    q = _norm(quote)
    if not q:
        return False
    if any(q in x for x in lines):
        return True
    return any(q in " ".join(lines[i:i + 3]) for i in range(len(lines)))


def _cand(**kw) -> dict:
    base = {"title": "t", "kind": "api_contract", "criterion": "correct", "severity": "major",
            "requirement_ids": ["R-01"], "evidence": [{"quote": "q", "line": 1}], "problem": "p",
            "scenario": "s", "impact": "i", "recommendation": "r", "rewrite": "", "question": "",
            "blocks": "development"}
    base.update(kw)
    return base


# --- промпт ---------------------------------------------------------------------------------------

def test_prompt_exists_and_is_russian():
    text = PROMPT.read_text(encoding="utf-8")
    assert text.startswith("## Задача")
    assert len(re.findall(r"[а-яё]", text, re.I)) > 3000
    for key in ("inventory", "operations", "promises", "codes", "fields", "missing_element", "status_conflict",
                "unit_mismatch", "api_contract", "До 12 кандидатов"):
        assert key in text, key


def test_prompt_has_no_official_document_words():
    text = PROMPT.read_text(encoding="utf-8").lower()
    leaked = [w for w in OFFICIAL_WORDS if w in text]
    assert not leaked, f"слова официального документа в промпте: {leaked}"


def test_prompt_has_no_dev_corpus_method_names():
    text = PROMPT.read_text(encoding="utf-8")
    for name in ("getTransferLimit", "setTransferLimit", "getCashback", "saveCategory", "createAutopay",
                 "getAutopay", "deleteAutopay", "blockCard", "unblockCard", "getCardStatus", "BLOCKED_BY_CLIENT"):
        assert name not in text, name


# --- схема ----------------------------------------------------------------------------------------

def test_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(la.SCHEMA)
    assert set(la.SCHEMA["required"]) == {"inventory", "candidates"}
    assert la.SCHEMA["properties"]["candidates"]["items"]["properties"]["kind"]["enum"] == la.KINDS


def test_schema_accepts_minimal_answer_and_rejects_extra_fields():
    ok = {"inventory": la.empty_inventory(), "candidates": [_cand()]}
    jsonschema.validate(ok, la.SCHEMA)
    bad = {"inventory": la.empty_inventory(), "candidates": [_cand(extra="x")]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, la.SCHEMA)


def test_schema_can_wrap_external_candidate_schema():
    sch = la.schema({"type": "object"})
    assert sch["properties"]["candidates"]["items"] == {"type": "object"}


# --- постобработка --------------------------------------------------------------------------------

def test_critical_without_scenario_or_blocks_is_downgraded():
    out = la.postprocess({"candidates": [
        _cand(severity="critical", scenario="", evidence=[{"quote": "a", "line": 1}]),
        _cand(severity="critical", blocks="none", evidence=[{"quote": "b", "line": 2}]),
        _cand(severity="critical", evidence=[{"quote": "c", "line": 3}]),
    ]})
    assert [c["severity"] for c in out["candidates"]] == ["critical", "major", "major"]


def test_order_dedupe_limit_and_evidence_filter():
    cands = [_cand(severity="minor", evidence=[{"quote": "m", "line": 50}])]
    cands += [_cand(evidence=[{"quote": f"q{i}", "line": i}]) for i in range(1, 17)]
    cands += [_cand(evidence=[{"quote": "dup", "line": 3}])]          # дубль по виду и строкам
    cands += [_cand(evidence=[])]                                      # без цитаты
    cands += [_cand(severity="critical", evidence=[{"quote": "k", "line": 99}])]
    out = la.postprocess({"candidates": cands})["candidates"]
    assert len(out) == la.MAX_CANDIDATES
    assert out[0]["severity"] == "critical"
    assert all(c["evidence"] for c in out)
    assert all(c["source"] == "lens:architect" for c in out)
    assert sum(1 for c in out if [e["line"] for e in c["evidence"]] == [3]) == 1


def test_unknown_requirement_ids_removed_and_input_not_mutated():
    data = {"candidates": [_cand(requirement_ids=["R-01", "Ф-9"])], "inventory": {"promises": [], "junk": 1}}
    snapshot = json.dumps(data, ensure_ascii=False, sort_keys=True)
    out = la.postprocess(data, requirement_ids={"R-01"})
    assert out["candidates"][0]["requirement_ids"] == ["R-01"]
    assert set(out["inventory"]) == {"operations", "promises", "codes", "fields"}
    assert json.dumps(data, ensure_ascii=False, sort_keys=True) == snapshot


def test_postprocess_handles_garbage():
    assert la.postprocess({}) == {"candidates": [], "inventory": la.empty_inventory()}
    assert la.postprocess({"candidates": [None, "x", {"evidence": None}]})["candidates"] == []


def test_unfulfilled_promises():
    inv = {"promises": [{"what": "показать сумму", "line": 3, "operation": ""},
                        {"what": "сохранить", "line": 4, "operation": "save"}]}
    assert [p["line"] for p in la.unfulfilled_promises(inv)] == [3]


# --- записанные живые ответы на официальном документе ---------------------------------------------

@pytest.fixture(scope="module", params=["official_architect_sonnet.json", "official_architect_haiku.json", "official_architect_opus.json"])
def recorded(request):
    return json.loads((FIX / request.param).read_text(encoding="utf-8"))


def test_recorded_answer_matches_schema(recorded):
    jsonschema.validate(recorded, la.SCHEMA)


def test_recorded_quotes_exist_in_document(recorded):
    lines = _doc_lines()
    missing = [e["quote"] for c in recorded["candidates"] for e in c["evidence"] if not _quote_found(lines, e["quote"])]
    assert not missing, missing


def test_recorded_answer_finds_key_api_defects(recorded):
    reqs = {r["id"] for r in json.loads(SEGMENT.read_text(encoding="utf-8"))["requirements"]}
    out = la.postprocess(recorded, requirement_ids=reqs)["candidates"]
    crit = [c for c in out if c["severity"] == "critical"]
    lines = lambda c: {e["line"] for e in c["evidence"]}  # noqa: E731
    # К4: обещано чтение (интеграция L52), а операции чтения нет
    assert any(c["kind"] == "missing_element" and 52 in lines(c) for c in crit)
    # К3: неверная сумма — 400 (L163) против 200 с ERROR (L171 или логика L121)
    assert any(c["kind"] == "status_conflict" and 163 in lines(c) and lines(c) & {121, 171} for c in crit)
    # С1: изменение данных методом GET (L104)
    assert any(104 in lines(c) for c in out)
    # С3: типы одного поля в запросе (L143/L144) и ответе (L156/L157)
    assert any(lines(c) & {143, 144} and lines(c) & {156, 157} for c in out)
    # С4: единицы суммы в данных (L49) и в API/приёмке
    assert any(c["kind"] == "unit_mismatch" and 49 in lines(c) for c in out)
    # 403 ↔ 404 (L175/L188/L189)
    assert any(lines(c) & {188, 189} for c in out)
