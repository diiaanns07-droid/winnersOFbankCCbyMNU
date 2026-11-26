"""Стыковой тест с bootstrap bcc/integration (contracts v1 @431f76d, HANDOFF @3e6b569).

* Requirement, Hint, Evidence, Warning, Document и Report.excluded проходят ``bcc_review.contracts``;
  опоры требований проходят ``evidence_errors`` в скелете Report.
* RESPONSE_SCHEMA соблюдает ограничения structured outputs из HANDOFF: у объектов
  ``additionalProperties: false`` и полный ``required``, без числовых ограничений и рекурсии.
* Payload — ``{task, input, context}``; короткий вход идёт с ``context.mode = full``.
* Парсер, убирающий разметку из ``block.text`` (``visible=True``), даёт ту же нарезку.
* ``BCC_P04_DOCUMENT_JSON=путь`` — Document от реального парсера (№01/02/03): инварианты и эталон кейса.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bcc_review.analysis.inventory import RESPONSE_SCHEMA, build_inventory, build_payload
from p04_support import QuoteModel, ScriptedModel, assert_invariants, fixture_document, load_spec

C = pytest.importorskip("bcc_review.contracts", reason="bootstrap bcc/integration не в checkout")


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def test_response_schema_fits_structured_outputs():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(RESPONSE_SCHEMA)
    for path, node in _walk(RESPONSE_SCHEMA):
        assert "$ref" not in node, path
        for banned in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"):
            assert banned not in node, (path, banned)
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert sorted(node["required"]) == sorted(node["properties"]), path


def test_model_answers_conform_to_response_schema():
    jsonschema = pytest.importorskip("jsonschema")
    doc = fixture_document("case_requirements.md")
    model = QuoteModel(load_spec("case_model_spec.json"), doc)
    build_inventory(doc, model)
    for call in model.calls:
        jsonschema.validate(model.respond(call["payload"]), call["schema"])


def test_payload_follows_handoff_format():
    doc = fixture_document("case_requirements.md")
    model = ScriptedModel([{"items": [], "excluded": [], "facts": [], "done": True}] * 2)
    build_inventory(doc, model)
    first = model.calls[0]["payload"]
    assert set(first) == set(C.ASK_PAYLOAD_KEYS)
    assert first["context"] == {"mode": "full"}  # части A и B вместе в контексте
    assert all("text" not in b for b in first["input"]["blocks"])  # текст прикладывает движок
    retry = model.calls[1]["payload"]
    assert retry["context"] == {"mode": "full"} and retry["input"]["window"]["mode"] == "retry"
    # окна большого документа: контекст — их блоки
    windowed = ScriptedModel([{"items": [], "excluded": [], "facts": [], "done": True}] * 20)
    build_inventory(doc, windowed, window_chars=3000, retry=False)
    assert len(windowed.calls) > 1
    for call in windowed.calls:
        ctx = call["payload"]["context"]
        assert ctx["mode"] == "blocks" and ctx["block_ids"] == [b["id"] for b in call["payload"]["input"]["blocks"]]
    # ручной прогон промпта: payload самодостаточен
    (manual,) = build_payload(doc)
    assert manual["context"] == {"mode": "none"} and all("text" in b for b in manual["input"]["blocks"])


def test_contract_types_on_case_rules_and_model():
    doc = fixture_document("case_requirements.md")
    C.validate(doc, "Document")
    for inv in (build_inventory(doc), build_inventory(doc, QuoteModel(load_spec("case_model_spec.json"), doc))):
        assert_invariants(doc, inv)  # включает validate(...) и evidence_errors(...)
        assert all(r["review_status"] == "not_reviewed" for r in inv["requirements"])
        audit = inv["block_coverage"]["evidence_audit"]
        C.validate(audit, "EvidenceAudit")


def test_budget_exhausted_stops_calls():
    doc = fixture_document("case_requirements.md")
    model = ScriptedModel([C.BudgetExhausted("inventory", "max_calls")])
    inv = build_inventory(doc, model)
    assert len(model.calls) == 1
    assert inv["mode"] == "rules_only" and inv["block_coverage"]["llm_status"] == "failed"
    assert inv["block_coverage"]["fallback_block_ids"]  # правила закрыли пропущенное
    assert any(w["code"] == "llm_call_failed" and "BudgetExhausted" in w["message"] for w in inv["warnings"])


def test_visible_text_parser_gives_same_slicing():
    """Парсер №01 может убрать **, `, «* » и внешние | из block.text — нарезка от этого не меняется."""
    raw = fixture_document("case_requirements.md")
    vis = fixture_document("case_requirements.md", visible=True)
    a, b = build_inventory(raw), build_inventory(vis)
    assert_invariants(vis, b)
    pick = lambda inv: [(r["id"], r["source_id"], r["kind"], r["block_ids"]) for r in inv["requirements"]]
    assert pick(a) == pick(b)
    assert [g["category"] for g in a["excluded"]] == [g["category"] for g in b["excluded"]]
    model = QuoteModel(load_spec("case_model_spec.json"), vis)
    m = build_inventory(vis, model)
    assert_invariants(vis, m)
    assert len(model.calls) == 1 and len(m["requirements"]) == 58
    assert [r["id"] for r in m["requirements"] if r["source_id"] == "Ф-1"] == [
        "R-002.1", "R-002.2", "R-002.3", "R-002.4", "R-002.5"]


@pytest.mark.skipif(not os.environ.get("BCC_P04_DOCUMENT_JSON"), reason="нет Document от реального парсера")
def test_real_parser_document_keeps_invariants():
    doc = json.loads(Path(os.environ["BCC_P04_DOCUMENT_JSON"]).read_text(encoding="utf-8"))
    rules = build_inventory(doc)
    assert_invariants(doc, rules)
    model = QuoteModel(load_spec("case_model_spec.json"), doc)
    inv = build_inventory(doc, model)
    assert_invariants(doc, inv)
    if doc.get("id") == fixture_document("case_requirements.md")["id"]:
        f1 = [r for r in inv["requirements"] if r["source_id"] == "Ф-1"]
        assert len(f1) == 5, "Ф-1 должен дать пять атомов и на реальном парсере"


def test_engine_runs_this_module_and_reads_warnings(tmp_path):
    """Движок bcc/integration подхватывает №04 из слота команды; str(warning) читается как «код: сообщение»."""
    engine = pytest.importorskip("bcc_review.engine", reason="движок ещё не влит")
    src = Path(__file__).resolve().parents[1] / "p04" / "fixtures" / "case_requirements.md"
    out = tmp_path / "report.md"
    engine.run_review(src, out, options={"offline_lint": True, "use_cache": False})
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["modules"]["build_inventory"] == "team:bcc_review.analysis.inventory:build_inventory"
    assert len(report["requirements"]) == 49
    inv_warnings = [w for w in report["warnings"] if w.get("stage") == "inventory"]
    assert not any(w["message"].startswith("{") for w in inv_warnings)
    assert sum(1 for w in inv_warnings if "b0" in w["message"] and "не попали" in w["message"]) == 1
    C.validate(report)
    assert C.evidence_errors(report) == []



def test_engine_model_branch_with_mock_provider(tmp_path):
    """Ветка с моделью через движок: payload → asker (схема, контекст) → mock → проверка №04."""
    engine = pytest.importorskip("bcc_review.engine", reason="движок ещё не влит")
    from bcc_review.runtime.modules import Modules

    src = Path(__file__).resolve().parent / "fixtures" / "case_requirements.md"
    doc = Modules().get("read_text").func(src)  # Document читателя движка: его ID блоков
    entry = QuoteModel(load_spec("case_model_spec.json"), doc).respond(build_payload(doc, attach_text=False)[0])
    base = Path(__file__).resolve().parents[1] / "integration" / "fixtures" / "mock_bcc.json"
    script = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {}
    script["inventory"] = entry
    script_path = tmp_path / "mock.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "report.md"
    engine.run_review(src, out, options={"provider": "mock", "mock_script": str(script_path), "use_cache": False})
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["modules"]["build_inventory"] == "team:bcc_review.analysis.inventory:build_inventory"
    stage = next(s for s in report["run"]["stages"] if s["name"] == "inventory")
    assert stage["status"] == "ok" and stage["calls"] == 1  # короткий вход — один вызов, повтор не нужен
    assert len(report["requirements"]) == 58
    f1 = [r for r in report["requirements"] if r["source_id"] == "Ф-1"]
    assert [r["id"] for r in f1] == ["R-002.1", "R-002.2", "R-002.3", "R-002.4", "R-002.5"]
    assert not any("не попали" in w["message"] for w in report["warnings"] if w.get("stage") == "inventory")
    C.validate(report)
    assert C.evidence_errors(report) == []
