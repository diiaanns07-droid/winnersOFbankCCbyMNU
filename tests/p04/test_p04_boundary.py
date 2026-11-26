"""Второй проход. Реестр на границе двух фрагментов (окна с перекрытием).

Нейтральное ТЗ ``fixtures/card_turnover.md``: в «Дебетовых» и «Корпоративных картах» один и тот же
К-1 дословно; только дебетовый раздел следующей строкой исключает возвраты; таблица согласования
со строкой-шапкой и пустой подписью.

Участвуют опубликованные реализации bcc/integration: читатель через слот ``read_text`` (№01),
транспорт ``runtime.asker.Asker`` с ``runtime.context.ContextBuilder`` и ``runtime.core.Budget``;
«модель» — детерминированный адаптер, который отвечает по содержимому переданного окна.
"""

from __future__ import annotations

import json

import pytest

from bcc_review.analysis.inventory import build_inventory, build_payload
from p04_support import FIXTURES, WindowContentAdapter, assert_invariants, engine_ask, fates, published_document

pytest.importorskip("bcc_review.runtime.asker", reason="рантайм движка bcc/integration не в checkout")

SRC = FIXTURES / "card_turnover.md"
RULE = "Операция включается в оборот месяца по дате её проведения."
EXCEPTION = "возвраты в оборот не включаются."
EXAMPLE = FIXTURES / "same_number_two_sections.inventory.json"


def _doc():
    doc, reader = published_document(SRC)
    return doc, reader


def _ids(doc):
    by = {}
    for b in doc["blocks"]:
        t = b["text"]
        if t.startswith("К-1.") and "Дебет" in b["section"][-1]:
            by["debit"] = b["id"]
        elif t.startswith("К-1."):
            by["corp"] = b["id"]
        elif t.startswith("Исключение:"):
            by["exception"] = b["id"]
        elif "→" in t:
            by["scheme"] = b["id"]
        elif t.startswith("Документ"):
            by["preamble"] = b["id"]
        elif b["kind"] == "table_header":
            by["header"] = b["id"]
        elif b["kind"] == "table_row":
            by["signature"] = b["id"]
    return by


def boundary_window(doc) -> int:
    """Наименьшее окно, при котором ровно три окна и стык проходит между К-1 и строкой исключения."""
    ids = _ids(doc)
    for width in range(40, 2000, 5):
        plan = [p["input"]["window"]["process_block_ids"] for p in build_payload(doc, window_chars=width,
                                                                                  overlap_blocks=1, attach_text=False)]
        for left, right in zip(plan, plan[1:]):
            if len(plan) == 3 and left[-1] == ids["debit"] and right[0] == ids["exception"]:
                return width
    raise AssertionError("не нашлось окна со стыком между К-1 и исключением")


def semantic(inv):
    """Смысловой перечень: раздел, номер в документе, цитата, группа исходного пункта."""
    return [(r["section"][-1], r["source_id"], r["hints"][0]["quote"], r["group"], r["id"]) for r in inv["requirements"]]


def test_big_and_small_window_give_same_obligations():
    doc, reader = _doc()
    ids = _ids(doc)
    big_adapter = WindowContentAdapter(overeager=True)
    big_ask, _ = engine_ask(doc, big_adapter)
    big = build_inventory(doc, big_ask)
    width = boundary_window(doc)
    small_adapter = WindowContentAdapter(overeager=True)  # повторяет и блоки перекрытия
    small_ask, _ = engine_ask(doc, small_adapter)
    small = build_inventory(doc, small_ask, window_chars=width, overlap_blocks=1)
    for inv in (big, small):
        assert_invariants(doc, inv)
    # транспорт: одно окно целиком против трёх окон; исключение — первым в окне 2, К-1 — в перекрытии
    assert len(big_adapter.calls) == 1 and len(small_adapter.calls) == 3
    w1, w2 = small_adapter.calls[0]["input"], small_adapter.calls[1]["input"]
    assert w1["window"]["process_block_ids"][-1] == ids["debit"]
    assert w2["window"]["process_block_ids"][0] == ids["exception"]
    assert {b["id"]: b["process"] for b in w2["blocks"]}[ids["debit"]] is False  # повтор блока в перекрытии
    assert {b["id"]: b["process"] for b in w1["blocks"]}[ids["exception"]] is False
    # один и тот же смысловой перечень с разделами, номерами, цитатами и ID
    expected = [
        ("1. Дебетовые карты", "К-1", RULE, "R-001", "R-001.1"),
        ("1. Дебетовые карты", "К-1", EXCEPTION, "R-001", "R-001.2"),
        ("2. Корпоративные карты", "К-1", RULE, "R-002", "R-002"),
    ]
    assert semantic(big) == semantic(small) == expected
    # исключение связано с дебетовым правилом, оба К-1 различимы по источнику
    for inv in (big, small):
        debit, exc, corp = inv["requirements"]
        assert exc["group"] == debit["group"] != corp["group"]
        assert debit["source_ref"] == exc["source_ref"] == "1. Дебетовые карты › К-1"
        assert corp["source_ref"] == "2. Корпоративные карты › К-1"
        assert debit["block_ids"] == [ids["debit"]] and corp["block_ids"] == [ids["corp"]]
        assert debit["hints"][0]["quote"] == corp["hints"][0]["quote"]  # дословно одинаковы
        assert not [w for w in inv["warnings"] if w["code"] == "source_id_cleared"]
    # повтор блока в перекрытии не дал лишнего обязательства: он связан по координатам
    assert small["block_coverage"]["evidence"]["context_linked"] >= 2
    assert reader.startswith(("team:", "fallback:"))


def test_truncated_then_budget_exhausted_partition():
    doc, _ = _doc()
    ids = _ids(doc)
    adapter = WindowContentAdapter(faults={1: "truncated"})  # второй ответ усечён
    ask, budget = engine_ask(doc, adapter, max_calls=2)     # третьему вызову бюджета нет
    inv = build_inventory(doc, ask, window_chars=boundary_window(doc), overlap_blocks=1)
    assert_invariants(doc, inv)
    calls = inv["block_coverage"]["calls"]
    assert len(adapter.calls) == budget.calls == 2  # физические вызовы адаптера
    assert calls["used"] == 3 and calls["failed"] == 2 and calls["truncated"] == 1 and calls["retry_calls"] == 0
    reqs = {r["block_ids"][0]: r for r in inv["requirements"]}
    assert set(reqs) == {ids["debit"], ids["exception"], ids["corp"]}
    assert reqs[ids["debit"]]["origin"] == "llm"
    # восстановленные резервными правилами записи помечены и сохранили связь с дебетовым К-1
    assert reqs[ids["exception"]]["origin"] == reqs[ids["corp"]]["origin"] == "rules_fallback"
    assert reqs[ids["exception"]]["source_id"] == "К-1"
    assert reqs[ids["exception"]]["group"] == reqs[ids["debit"]]["group"] != reqs[ids["corp"]]["group"]
    cov = inv["block_coverage"]
    assert cov["model_missed_block_ids"] == [ids["exception"], ids["corp"], ids["scheme"]]
    assert cov["fallback_block_ids"] == [ids["exception"], ids["corp"]]
    assert inv["unprocessed_block_ids"] == [ids["scheme"]]  # схему правила не решают — явный остаток
    excl = {bid: g for g in inv["excluded"] for bid in g["block_ids"]}
    assert excl[ids["preamble"]]["category"] == "preamble"
    for key in ("header", "signature"):
        assert excl[ids[key]]["category"] == "approval" and "подпис" in excl[ids[key]]["reason"].lower()
    f = fates(inv)
    assert [f[b["id"]] for b in doc["blocks"]].count("unprocessed") == 1
    codes = [w["code"] for w in inv["warnings"]]
    assert codes.count("llm_call_failed") == 2 and "rules_fallback" in codes and "llm_budget" in codes
    assert "unprocessed_blocks" not in codes  # об остатке предупреждает движок, модуль не дублирует
    assert any("truncated" in w["message"] for w in inv["warnings"] if w["code"] == "llm_call_failed")
    assert any("BudgetExhausted" in w["message"] for w in inv["warnings"] if w["code"] == "llm_call_failed")
    assert inv["block_coverage"]["llm_status"] == "partial" and inv["block_coverage"]["level"] == "partial"


def test_rules_only_links_exception_to_parent_item():
    doc, _ = _doc()
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    assert [(r["id"], r["source_id"], r["source_ref"]) for r in inv["requirements"]] == [
        ("R-001.1", "К-1", "1. Дебетовые карты › К-1"),
        ("R-001.2", "К-1", "1. Дебетовые карты › К-1"),
        ("R-002", "К-1", "2. Корпоративные карты › К-1"),
    ]


def test_example_for_p06_is_current():
    """Пример для №06: два одноимённых К-1 и исключение — файл совпадает с текущим выходом."""
    doc, _ = _doc()
    inv = build_inventory(doc, engine_ask(doc, WindowContentAdapter())[0])
    current = {
        "about": "Нейтральное ТЗ: одинаковый К-1 в двух разделах, исключение только у дебетового. "
                 "Различайте пункты по section/source_ref/group, а не по source_id и тексту.",
        "source": "tests/p04/fixtures/card_turnover.md",
        "document_id": doc["id"],
        "requirements": [{k: r[k] for k in ("id", "group", "source_id", "source_ref", "section", "text", "block_ids",
                                             "evidence")} for r in inv["requirements"]],
        "excluded": inv["excluded"],
        "unprocessed_block_ids": inv["unprocessed_block_ids"],
    }
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == current


def test_engine_entry_point_truncated_then_budget(tmp_path):
    """Действующая точка входа run_review: MockAdapter движка, первый ответ усечён, бюджет — 1 вызов."""
    engine = pytest.importorskip("bcc_review.engine", reason="движок не в checkout")
    script = tmp_path / "mock.json"
    script.write_text(json.dumps({"inventory": [{"error": "truncated", "message": "mock: max_tokens"}]}), encoding="utf-8")
    out = tmp_path / "report.md"
    engine.run_review(SRC, out, options={"provider": "mock", "mock_script": str(script), "max_calls": 1,
                                         "use_cache": False})
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    doc, _ = _doc()
    ids = _ids(doc)
    assert report["run"]["modules"]["build_inventory"] == "team:bcc_review.analysis.inventory:build_inventory"
    assert report["run"]["calls"]["physical"] == 1
    got = [(r["source_id"], r["section"][-1], r["block_ids"]) for r in report["requirements"]]
    assert got == [("К-1", "1. Дебетовые карты", [ids["debit"]]), ("К-1", "1. Дебетовые карты", [ids["exception"]]),
                   ("К-1", "2. Корпоративные карты", [ids["corp"]])]
    excl = {bid for g in report["excluded"] for bid in g["block_ids"]}
    assert {ids["header"], ids["signature"], ids["preamble"]} <= excl
    msgs = [w["message"] for w in report["warnings"] if w.get("stage") == "inventory"]
    assert any("truncated" in m for m in msgs) and any("BudgetExhausted" in m for m in msgs)
    assert any("rules_fallback" in m for m in msgs) and any(ids["scheme"] in m for m in msgs)
    from bcc_review import contracts as C

    C.validate(report)
    assert C.evidence_errors(report) == []
