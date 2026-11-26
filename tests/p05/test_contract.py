"""Стык с контрактом v1 (bcc/integration @ 3e6b569): типы, схема ответа модели, граничные входы."""
import json
from types import SimpleNamespace

import pytest

from bcc_review import contracts as C
from bcc_review.analysis.individual import response_schema, review_individual
from tests.p05.docfix import bcc_case
from tests.p05.helpers import FakeAsk, doc_from_lines, issue, passes


def _model(payload):
    out = []
    for rid in payload["input"]["req_ids"]:
        if rid == "R07":
            out.append({"req_id": rid, "checks": [issue(
                "correct", "Лимит одного push конфликтует с Ф-4.", "максимум один такой push за календарный месяц",
                kind="conflict", severity="critical", blocks="both", blocked_decision="Отправлять ли второй push",
                scenario="Push уже был, порог изменён, расходы снова достигли порога.", outcomes=["нет", "да"])]})
        else:
            out.append(passes(rid))
    return {"results": out}


@pytest.mark.parametrize("mode", ["rules_only", "rules_plus_llm"])
def test_stitch_with_contract_v1(mode):
    doc, reqs = bcc_case()
    C.validate(doc, "Document")
    for r in reqs:
        C.validate(r, "Requirement")
    res = review_individual(doc, reqs, ask=FakeAsk(_model) if mode == "rules_plus_llm" else None)
    assert set(res) == {"checks", "candidates", "warnings", "failed", "meta"}
    # движок считает требование проверенным моделью, только если все 9 записей пришли с source=llm
    sources = {c["source"] for c in res["checks"] if c["req_id"] != "R07"}
    assert sources == ({"rules"} if mode == "rules_only" else {"llm"})
    assert res["failed"] == ({r["id"]: res["failed"][r["id"]] for r in reqs} if mode == "rules_only" else {})
    for chk in res["checks"]:
        C.validate(chk, "Check")
        assert chk["criterion"] in C.INDIVIDUAL_CRITERIA
    for cand in res["candidates"]:
        C.validate(cand, "Candidate")
        assert cand["kind"] in C.FINDING_KINDS and cand["criterion"] in C.INDIVIDUAL_CRITERIA
        assert cand["stage"] == "individual" and cand["source"] in ("rules", "llm", "llm+rules")
        assert set(cand["blocks"]) <= set(C.BLOCKS_TARGETS)
        if cand["severity"] == "critical":  # то, что движок требует от критичного замечания
            assert cand["impact"] and cand["blocked_decision"]
    for w in res["warnings"]:
        C.validate(w, "Warning")
    assert res["meta"]["mode"] in C.RUN_MODES
    json.dumps(res, ensure_ascii=False)

    # опоры буквальные: №07 найдёт координаты без нечёткого поиска
    blocks = {b["id"]: b["text"] for b in doc["blocks"]}
    for c in res["candidates"]:
        for h in c["hints"]:
            assert h["quote"] in blocks[h["block_id"]]
            if "context" in h:
                assert h["context"] in blocks[h["block_id"]]
    refs = {c["ref"] for c in res["candidates"]}
    for chk in res["checks"]:
        assert set(chk.get("candidate_refs", [])) <= refs


def test_response_schema_fits_structured_outputs():
    schema = response_schema()

    def walk(node, path="$"):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, path
                assert sorted(node["required"]) == sorted(node["properties"]), path
            for bad in ("minLength", "maxLength", "minimum", "maximum", "$ref"):
                assert bad not in node, f"{path}: {bad}"
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(schema)
    item = schema["properties"]["results"]["items"]["properties"]["checks"]["items"]["properties"]
    assert item["criterion"]["enum"] == list(C.INDIVIDUAL_CRITERIA)
    assert set(C.FINDING_KINDS) <= set(item["kind"]["enum"])
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_model({"input": {"req_ids": ["R07", "R01"]}}), schema)


def test_edge_inputs():
    doc = doc_from_lines("# ТЗ", "## Функциональные требования", "- **Ф-1.** Отчёт формируется быстро.")
    ask = FakeAsk({"results": []})
    empty = review_individual(doc, [], ask=ask)
    assert empty["checks"] == [] and empty["candidates"] == [] and ask.calls == []

    # требование без блоков: оценка есть, подсказка без block_id, есть предупреждение
    orphan = review_individual(doc, [{"id": "R1", "source_id": None, "text": "Отчёт формируется быстро.", "block_ids": [],
                                      "evidence": [], "review_status": "reviewed", "review_reason": None}])
    assert len(orphan["checks"]) == 9
    assert any(w["code"] == "individual.no_blocks" for w in orphan["warnings"])
    assert orphan["candidates"][0]["hints"][0]["block_id"] is None
    C.validate(orphan["candidates"][0], "Candidate")

    # объекты с атрибутами вместо dict (pydantic / dataclass)
    blocks = [SimpleNamespace(**b) for b in doc["blocks"]]
    obj_doc = SimpleNamespace(id=doc["id"], title="ТЗ", format="markdown", blocks=blocks, warnings=[])
    bid = next(b.id for b in blocks if "Ф-1" in b.text)
    obj_req = SimpleNamespace(id="R1", source_id="Ф-1", text=blocks[-1].text, block_ids=[bid], evidence=[])
    res = review_individual(obj_doc, [obj_req])
    assert res["candidates"][0]["hints"][0] == {"block_id": bid, "quote": "быстро", "context": "Ф-1. Отчёт формируется быстро."}
