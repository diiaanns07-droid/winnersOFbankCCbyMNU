"""Форма результата и стыковка с contracts/v1.json (если bootstrap уже в checkout)."""
import json
from pathlib import Path

import pytest

from bcc_review.analysis.individual import review_individual
from tests.p05.docfix import bcc_case

ROOT = Path(__file__).resolve().parents[2]

LOCAL_SCHEMA = {
    "type": "object",
    "required": ["checks", "candidates", "warnings"],
    "properties": {
        "checks": {"type": "array", "items": {
            "type": "object",
            "required": ["req_id", "criterion", "status", "reason"],
            "properties": {
                "req_id": {"type": "string"},
                "criterion": {"type": "string"},
                "status": {"enum": ["pass", "issue", "unknown", "na"]},
                "reason": {"type": "string", "minLength": 10},
            },
        }},
        "candidates": {"type": "array", "items": {
            "type": "object",
            "required": ["scope", "kind", "criterion", "severity", "title", "impact", "req_ids", "hints"],
            "properties": {
                "scope": {"enum": ["requirement", "set"]},
                "severity": {"enum": ["critical", "major", "minor"]},
                "req_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "hints": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "required": ["block_id", "quote"],
                    "properties": {"block_id": {"type": "string"}, "quote": {"type": "string", "minLength": 1}},
                }},
            },
        }},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def test_result_matches_interface_and_hints_are_literal():
    jsonschema = pytest.importorskip("jsonschema")
    doc, reqs = bcc_case()
    res = review_individual(doc, reqs)
    jsonschema.validate(res, LOCAL_SCHEMA)
    json.dumps(res, ensure_ascii=False)  # сериализуется без доп. кодировщиков
    blocks = {b["id"]: b["text"] for b in doc["blocks"]}
    for c in res["candidates"]:
        for h in c["hints"]:
            assert h["quote"] in blocks[h["block_id"]]
            if "context" in h:
                assert h["context"] in blocks[h["block_id"]]
    refs = {c["ref"] for c in res["candidates"]}
    for chk in res["checks"]:
        assert set(chk.get("refs", [])) <= refs


def test_stitch_with_bootstrap_contract():
    """Стыковой тест: включается сам, когда в checkout появится contracts/v1.json."""
    jsonschema = pytest.importorskip("jsonschema")
    path = ROOT / "contracts" / "v1.json"
    if not path.exists():
        pytest.skip("contracts/v1.json ещё не опубликован (bootstrap bcc/integration)")
    schema = json.loads(path.read_text("utf-8"))
    defs = schema.get("$defs") or schema.get("definitions") or {}
    doc, reqs = bcc_case()
    res = review_individual(doc, reqs)
    for name, items in (("Candidate", res["candidates"]), ("Check", res["checks"])):
        if name in defs:
            sub = dict(defs[name])
            sub["$defs"] = defs
            for item in items:
                jsonschema.validate(item, sub)
    if "Document" in defs:
        jsonschema.validate(doc, dict(defs["Document"], **{"$defs": defs}))


def test_edge_inputs():
    from types import SimpleNamespace

    from tests.p05.helpers import FakeAsk, doc_from_lines

    doc = doc_from_lines("# ТЗ", "## Функциональные требования", "- **Ф-1.** Отчёт формируется быстро.")
    ask = FakeAsk({"results": []})
    empty = review_individual(doc, [], ask=ask)
    assert empty["checks"] == [] and empty["candidates"] == [] and ask.calls == []

    # требование без блоков: оценка есть, цитаты не привязаны, есть предупреждение
    orphan = review_individual(doc, [{"id": "R1", "source_id": None, "text": "Отчёт формируется быстро.", "block_ids": [], "evidence": []}])
    assert len(orphan["checks"]) == 9
    assert any(w.startswith("individual.no_blocks: R1") for w in orphan["warnings"])
    assert all(c["hints"] == [] for c in orphan["candidates"])

    # объекты с атрибутами вместо dict (pydantic / dataclass)
    blocks = [SimpleNamespace(**b) for b in doc["blocks"]]
    obj_doc = SimpleNamespace(id=doc["id"], title="ТЗ", format="md", blocks=blocks, warnings=[])
    bid = next(b.id for b in blocks if "Ф-1" in b.text)
    obj_req = SimpleNamespace(id="R1", source_id="Ф-1", text=blocks[-1].text, block_ids=[bid], evidence=[])
    res = review_individual(obj_doc, [obj_req])
    assert res["candidates"][0]["hints"][0] == {"block_id": bid, "quote": "быстро", "context": "**Ф-1.** Отчёт формируется быстро."}
