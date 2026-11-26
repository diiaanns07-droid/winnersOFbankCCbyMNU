"""Набор 3. Программная проверка ответа модели.

Несуществующий блок или номер, пропущенный блок, пустая цитата, дубль, обрезанный ответ и сбой
вызова приводят к исправлению с реальной цитатой либо к явной неполноте. Повтор предъявляет
модели только необработанные блоки, один раз и в рамках бюджета. Окна связываются по координатам.
"""

from __future__ import annotations

import copy

from bcc_review.analysis.inventory import PROMPT, RESPONSE_SCHEMA, STAGE, build_inventory, build_payload
from p04_support import QuoteModel, ScriptedModel, assert_invariants, fates, md_document, process_ids, warned
from test_p04_atomic import ATOMIC_MD, ATOMIC_SPEC

DOC = md_document(ATOMIC_MD, "atomic.md")
P1 = next(b["id"] for b in DOC["blocks"] if "**П-1.**" in b["text"])
P2 = next(b["id"] for b in DOC["blocks"] if "**П-2.**" in b["text"])
R1 = next(b["id"] for b in DOC["blocks"] if b["text"].startswith("1. Сумма"))
R2 = next(b["id"] for b in DOC["blocks"] if b["text"].startswith("2. Повторный"))
V1 = next(b["id"] for b in DOC["blocks"] if b["text"].startswith("1. Лимит"))
DESIGN = next(b["id"] for b in DOC["blocks"] if "→" in b["text"])
EMPTY = {"items": [], "excluded": [], "facts": [], "done": True}


def good() -> dict:
    return copy.deepcopy(QuoteModel(ATOMIC_SPEC, DOC).respond(build_payload(DOC)[0]))


def drop(resp: dict, block_id: str) -> dict:
    resp["items"] = [i for i in resp["items"] if i["evidence"][0]["block_id"] != block_id]
    for g in resp["excluded"]:
        g["block_ids"] = [b for b in g["block_ids"] if b != block_id]
    resp["excluded"] = [g for g in resp["excluded"] if g["block_ids"]]
    return resp


def item_for(resp: dict, block_id: str) -> dict:
    return next(i for i in resp["items"] if i["evidence"][0]["block_id"] == block_id)


def test_call_contract_stage_schema_and_whole_short_document():
    model = ScriptedModel([good()])
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    (call,) = model.calls
    assert call["stage"] == STAGE == "inventory"
    assert call["schema"] is RESPONSE_SCHEMA
    assert call["payload"]["task"] == PROMPT
    # короткий вход идёт одним окном целиком: заголовки — только в section, остальное обрабатывается
    heading_ids = {b["id"] for b in DOC["blocks"] if b["kind"] == "heading"}
    assert set(process_ids(call)) == {b["id"] for b in DOC["blocks"]} - heading_ids
    assert call["payload"]["input"]["window"] == {"index": 0, "count": 1, "mode": "full",
                                                  "process_block_ids": process_ids(call)}
    assert call["payload"]["context"] == {"mode": "full"}
    assert next(b for b in call["payload"]["input"]["blocks"] if b["id"] == P1)["label"] == "П-1"
    assert inv["block_coverage"]["llm_status"] == "complete" and inv["block_coverage"]["calls"]["used"] == 1
    assert inv["warnings"] == []


def test_unknown_block_with_real_quote_is_repaired():
    resp = good()
    item_for(resp, P2)["evidence"][0]["block_id"] = "L999"
    inv = build_inventory(DOC, ScriptedModel([resp]))
    assert_invariants(DOC, inv)
    req = next(r for r in inv["requirements"] if r["source_id"] == "П-2")
    assert req["block_ids"] == [P2] and req["hints"][0]["quote"] == "Изменение лимита вступает в силу сразу"
    assert inv["block_coverage"]["evidence"]["repaired"] == 1
    assert warned(inv, "hint_relocated", "L999")


def test_unknown_block_with_fake_quote_is_rejected_and_block_retried_once():
    first = good()
    item_for(first, P2)["evidence"] = [{"block_id": "L999", "quote": "Лимит действует бессрочно"}]
    retry = {"items": [{"source_id": "П-2", "kind": "functional", "text": "Лимит действует сразу",
                        "evidence": [{"block_id": P2, "quote": "вступает в силу сразу"}]}],
             "excluded": [], "facts": [], "done": True}
    model = ScriptedModel([first, retry])
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    assert len(model.calls) == 2
    assert process_ids(model.calls[1]) == [P2]  # повтор — только необработанный блок
    assert model.calls[1]["payload"]["input"]["window"]["mode"] == "retry"
    assert not any("бессрочно" in r["text"] for r in inv["requirements"])
    p2 = next(r for r in inv["requirements"] if r["source_id"] == "П-2")
    assert p2["origin"] == "llm_retry" and p2["hints"][0]["quote"] == "вступает в силу сразу"
    assert inv["block_coverage"]["evidence"]["items_rejected"] == 1
    assert inv["block_coverage"]["level"] == "complete"


def test_missed_block_after_single_retry_is_explicit_residue():
    first = drop(good(), DESIGN)
    model = ScriptedModel([first, EMPTY])
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    assert len(model.calls) == 2 and process_ids(model.calls[1]) == [DESIGN]
    assert inv["unprocessed_block_ids"] == [DESIGN]
    assert inv["block_coverage"]["level"] == "partial" and inv["block_coverage"]["llm_status"] == "partial"
    assert inv["block_coverage"]["model_missed_block_ids"] == [DESIGN]
    assert DESIGN in inv["block_coverage"]["explanation"]
    # остаток — в unprocessed_block_ids и объяснении; предупреждение о нём выдаёт движок, дубля нет
    assert not warned(inv, "unprocessed_blocks")
    assert next(b for b in inv["block_coverage"]["blocks"] if b["block_id"] == DESIGN)["fate"] == "unprocessed"


def test_missed_numbered_block_falls_back_to_rules_with_mark():
    first = drop(good(), R2)
    inv = build_inventory(DOC, ScriptedModel([first]), retry=False)
    assert_invariants(DOC, inv)
    r2 = next(r for r in inv["requirements"] if r["block_ids"] == [R2])
    assert r2["origin"] == "rules_fallback" and r2["source_id"] == "2"
    assert inv["block_coverage"]["fallback_block_ids"] == [R2]
    assert warned(inv, "rules_fallback", R2)
    # без отката по правилам остаток виден явно
    inv2 = build_inventory(DOC, ScriptedModel([drop(good(), R2)]), retry=False, fallback=False)
    assert inv2["unprocessed_block_ids"] == [R2] and inv2["block_coverage"]["level"] == "partial"


def test_nonexistent_source_id_is_cleared_and_restored_from_text():
    resp = good()
    item_for(resp, P2)["source_id"] = "П-9"
    item_for(resp, R1)["source_id"] = None
    inv = build_inventory(DOC, ScriptedModel([resp]))
    p2 = next(r for r in inv["requirements"] if r["block_ids"] == [P2])
    assert p2["source_id"] == "П-2"
    r1 = next(r for r in inv["requirements"] if r["block_ids"] == [R1])
    assert r1["source_id"] == "1"
    ev = inv["block_coverage"]["evidence"]
    assert ev["source_ids_cleared"] == 1 and ev["source_ids_filled"] >= 2
    assert warned(inv, "source_id_cleared", "П-9")


def test_empty_quote_rejected_and_normalized_quote_replaced_by_source_text():
    resp = good()
    item_for(resp, P2)["evidence"] = [{"block_id": P2, "quote": "   "}]
    item_for(resp, R1)["evidence"][0]["quote"] = "Сумма  округляется  до целого тенге"  # дрейф пробелов
    model = ScriptedModel([resp, EMPTY])
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    assert inv["block_coverage"]["evidence"]["empty"] == 1
    r1 = next(r for r in inv["requirements"] if r["block_ids"] == [R1])
    assert r1["hints"][0]["quote"] == "Сумма округляется до целого тенге"
    # пустая цитата не подтверждает пункт: блок ушёл в повтор, затем закрыт правилами
    assert process_ids(model.calls[1]) == [P2]
    assert next(r for r in inv["requirements"] if r["block_ids"] == [P2])["origin"] == "rules_fallback"


def test_truncated_response_marks_partial_and_retries_only_uncovered():
    first = good()
    del first["done"]
    first["items"] = first["items"][:3]  # дошли только пункты П-1
    first["excluded"] = []
    model = QuoteModel(ATOMIC_SPEC, DOC, mutate=lambda r, n, p: first if n == 0 else r)
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    assert len(model.calls) == 2
    assert P1 not in process_ids(model.calls[1])
    assert set(process_ids(model.calls[1])) == {P2, R1, R2, V1, DESIGN}
    assert inv["block_coverage"]["calls"]["truncated"] == 1 and inv["block_coverage"]["llm_status"] == "partial"
    assert inv["block_coverage"]["level"] == "complete"
    assert warned(inv, "llm_truncated")


def test_provider_failure_is_recorded_and_budget_respected():
    model = ScriptedModel([TimeoutError("503 overloaded"), good()])
    inv = build_inventory(DOC, model)
    assert_invariants(DOC, inv)
    assert inv["block_coverage"]["calls"]["failed"] == 1 and len(model.calls) == 2
    assert warned(inv, "llm_call_failed", "TimeoutError")
    assert inv["block_coverage"]["level"] == "complete"
    # бюджет в один вызов: повтора нет, остаток закрыт правилами и показан
    model1 = ScriptedModel([drop(good(), DESIGN)])
    inv1 = build_inventory(DOC, model1, max_calls=1)
    assert len(model1.calls) == 1
    assert warned(inv1, "llm_budget")
    assert inv1["unprocessed_block_ids"] == [DESIGN]
    # все вызовы упали: режим честно rules_only
    inv2 = build_inventory(DOC, ScriptedModel([RuntimeError("no key"), RuntimeError("no key")]))
    assert inv2["mode"] == "rules_only" and inv2["block_coverage"]["llm_status"] == "failed"


def test_duplicates_conflicts_and_unknown_exclusions():
    resp = good()
    resp["items"].append(copy.deepcopy(item_for(resp, P2)))
    resp["excluded"].append({"category": "preamble", "reason": "ошибочно", "block_ids": [R1, "L777"]})
    inv = build_inventory(DOC, ScriptedModel([resp]))
    assert_invariants(DOC, inv)
    assert sum(1 for r in inv["requirements"] if r["block_ids"] == [P2]) == 1
    ev = inv["block_coverage"]["evidence"]
    assert ev["duplicates_merged"] == 1 and ev["conflicts_resolved"] == 1 and ev["excluded_unknown_ids"] == 1
    assert fates(inv)[R1] == "requirement"


def test_overlapping_windows_are_linked_by_coordinates():
    single = build_inventory(DOC, QuoteModel(ATOMIC_SPEC, DOC))
    model = QuoteModel(ATOMIC_SPEC, DOC, overeager=True)  # отвечает и по блокам контекста соседних окон
    windowed = build_inventory(DOC, model, window_chars=200, overlap_blocks=1)
    assert_invariants(DOC, windowed)
    assert len(model.calls) == windowed["block_coverage"]["calls"]["windows"] > 1
    assert windowed["block_coverage"]["evidence"]["context_linked"] > 0
    pick = lambda inv: [(r["id"], r["source_id"], r["text"], r["hints"]) for r in inv["requirements"]]
    assert pick(windowed) == pick(single)
    # блоки окна делятся на обрабатываемые и контекст, ядро окон не пересекается
    cores = [set(c["payload"]["input"]["window"]["process_block_ids"]) for c in model.calls]
    assert sum(len(c) for c in cores) == len(set().union(*cores))
    assert any(not b["process"] for c in model.calls for b in c["payload"]["input"]["blocks"])
