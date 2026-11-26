"""Сопоставимость реестра в двух форматах (Markdown и PDF) через публичный вход движка.

Вход — ``bcc_review.engine.read_document`` (тот же путь, что у движка: №01 для .md, №02 для .pdf) и
``build_inventory``; сквозной сценарий — ``bcc_review.engine.run_review`` с mock-провайдером движка.

* Банковский документ ``release/input/requirements.md`` и ``requirements.pdf``: реестры совпадают
  по содержанию опор, исходному обозначению и разделу, группы исключений — те же.
* Компактный пример ``fixtures/close_conditions.md`` (PDF собирается из него в тесте): «Снятие
  наличных» и «Снятие наличных за рубежом» — каждое условие получает собственную опору, в том числе
  когда модель называет их общим именем и путает ID блока.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.analysis.inventory import build_inventory
from p04_support import (FIXTURES, StaticAdapter, assert_invariants, build_pdf_from_md, compare_registries, engine_ask,
                         naming_answer)

engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration не в checkout")
pytest.importorskip("pymupdf", reason="для PDF нужен pymupdf (extra pdf)")

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release" / "input"
CLOSE_MD = FIXTURES / "close_conditions.md"


@pytest.fixture(scope="module")
def close_docs(tmp_path_factory):
    pdf = build_pdf_from_md(CLOSE_MD, tmp_path_factory.mktemp("p04pdf") / "close_conditions.pdf")
    return {"md": engine.read_document(CLOSE_MD), "pdf": engine.read_document(pdf), "pdf_path": pdf}


def _groups(inv):
    return {(g["category"], g["reason"]) for g in inv["excluded"]}


@pytest.mark.skipif(not (RELEASE / "requirements.pdf").exists(), reason="нет release/input")
def test_bank_document_registry_matches_across_formats():
    md = engine.read_document(RELEASE / "requirements.md")
    pdf = engine.read_document(RELEASE / "requirements.pdf")
    a, b = build_inventory(md), build_inventory(pdf)
    assert_invariants(md, a)
    assert_invariants(pdf, b)
    cmp = compare_registries(a["requirements"], b["requirements"])
    assert len(a["requirements"]) == len(b["requirements"]) == 49
    assert cmp["pairs"] == 49 and cmp["issues"] == [], cmp["issues"]
    assert [r["kind"] for r in a["requirements"]] == [r["kind"] for r in b["requirements"]]
    # номера списков дошли до source_id в обоих форматах (№01 — из loc.list, №02 — из текста)
    logic = lambda inv: [r["source_id"] for r in inv["requirements"] if r["section"][-1] == "Логика работы метода"]
    assert logic(a) == logic(b) == list("12345")
    # маркер «• » из PDF не попал в цитаты
    assert not any(e["quote"].startswith("•") for r in b["requirements"] for e in r["evidence"])
    # одинаковые группы исключений: шапка согласования, прочитанная в PDF как заголовок, — тоже approval
    assert sorted(g["category"] for g in a["excluded"]) == sorted(g["category"] for g in b["excluded"])
    # единственная разница причин — известный артефакт №02: строка «**404**» в PDF стала заголовком,
    # и пример ответа оказался в разделе «404», а не «403. Unsuccessful — Forbidden»
    example = "пример запроса или ответа, опора для сверки с контрактом."
    assert _groups(a) - _groups(b) == {("example", f"Раздел «403. Unsuccessful — Forbidden»: {example}")}
    assert _groups(b) - _groups(a) == {("example", f"Раздел «404»: {example}")}
    approval = lambda inv: next(g for g in inv["excluded"] if g["category"] == "approval")
    assert len(approval(a)["block_ids"]) == 2 and len(approval(b)["block_ids"]) == 1  # пустой строки подписи в PDF нет
    assert any(w["code"] == "table_header_as_heading" for w in b["warnings"])
    assert a["unprocessed_block_ids"] and len(a["unprocessed_block_ids"]) == len(b["unprocessed_block_ids"]) == 4


@pytest.mark.parametrize("fmt", ["md", "pdf"])
def test_close_conditions_each_get_own_evidence(close_docs, fmt):
    doc = close_docs[fmt]
    text = {b["id"]: b["text"] for b in doc["blocks"]}
    rules = build_inventory(doc)
    adapter = StaticAdapter(naming_answer(doc))
    model = build_inventory(doc, engine_ask(doc, adapter)[0], retry=False)
    for inv in (rules, model):
        assert_invariants(doc, inv)
        reqs = inv["requirements"]
        assert len(reqs) == 4
        anchors = [r["block_ids"][0] for r in reqs]
        assert len(set(anchors)) == 4, anchors  # у каждого условия собственная опора
        u1, u2, lim1, lim2 = reqs
        assert "без комиссии" in text[u1["block_ids"][0]] and "за рубежом" in text[u2["block_ids"][0]]
        assert "500 000" in text[lim1["block_ids"][0]] and "200 000" in text[lim2["block_ids"][0]]
        assert (u1["source_id"], u2["source_id"]) == ("У-1", "У-2") and u1["group"] != u2["group"]
        for r in reqs:
            for e in r["evidence"]:
                assert text[e["block_id"]][e["start"]:e["end"]] == e["quote"]
    assert {r["origin"] for r in model["requirements"]} == {"llm"} and adapter.calls == 1
    codes = [w["code"] for w in model["warnings"]]
    assert codes.count("hint_relocated") == 2  # У-2 — по номеру пункта, лимит — по формулировке
    approval = [g for g in rules["excluded"] if g["category"] == "approval"]
    assert approval and approval[0]["reason"].startswith("Таблица «3. Согласование»")


def test_close_conditions_registry_same_in_md_and_pdf(close_docs):
    a, b = build_inventory(close_docs["md"]), build_inventory(close_docs["pdf"])
    cmp = compare_registries(a["requirements"], b["requirements"])
    assert cmp == {"pairs": 4, "issues": []}
    assert _groups(a) == _groups(b)


def test_number_of_another_item_is_rejected_not_merged(close_docs):
    """Пункт «У-2», опирающийся только на текст У-1, не сливается с У-1: отказ и откат на правила."""
    doc = close_docs["md"]
    u1 = next(b["id"] for b in doc["blocks"] if b["text"].startswith("У-1."))
    data = naming_answer(doc)
    data["items"][1]["evidence"] = [{"block_id": u1, "quote": "без комиссии"}]
    inv = build_inventory(doc, engine_ask(doc, StaticAdapter(data))[0], retry=False)
    assert_invariants(doc, inv)
    u = {r["source_id"]: r for r in inv["requirements"] if r["source_id"] in ("У-1", "У-2")}
    assert u["У-1"]["origin"] == "llm" and u["У-2"]["origin"] == "rules_fallback"
    assert u["У-1"]["block_ids"] != u["У-2"]["block_ids"]
    assert sum(1 for r in inv["requirements"] if r["block_ids"] == u["У-1"]["block_ids"]) == 1
    assert any(w["code"] == "item_rejected" and "«У-2»" in w["message"] for w in inv["warnings"])


def test_ambiguous_quote_is_not_guessed(close_docs):
    doc = close_docs["md"]
    data = {"items": [{"source_id": None, "kind": "functional", "text": "Снятие",
                       "evidence": [{"block_id": "b9999", "quote": "Снятие наличных"}]}],
            "excluded": [], "facts": [], "done": True}
    inv = build_inventory(doc, engine_ask(doc, StaticAdapter(data))[0], retry=False)
    assert_invariants(doc, inv)
    assert any(w["code"] == "hint_ambiguous" for w in inv["warnings"])
    assert {r["origin"] for r in inv["requirements"]} == {"rules_fallback"}


@pytest.mark.parametrize("fmt", ["md", "pdf"])
def test_run_review_end_to_end_close_conditions(close_docs, tmp_path, fmt):
    """Сквозной сценарий через публичный вход: run_review, MockAdapter движка с записанным ответом модели."""
    src = CLOSE_MD if fmt == "md" else close_docs["pdf_path"]
    doc = close_docs[fmt]
    script = tmp_path / "mock.json"
    script.write_text(json.dumps({"inventory": naming_answer(doc)}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / f"report_{fmt}.md"
    engine.run_review(src, out, options={"provider": "mock", "mock_script": str(script), "use_cache": False})
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["modules"]["build_inventory"] == "team:bcc_review.analysis.inventory:build_inventory"
    assert report["run"]["modules"]["read_pdf" if fmt == "pdf" else "read_text"].startswith("team:")
    reqs = report["requirements"]
    assert len(reqs) == 4 and len({r["block_ids"][0] for r in reqs}) == 4
    assert [r["source_id"] for r in reqs[:2]] == ["У-1", "У-2"]
    text = {b["id"]: b["text"] for b in report["document"]["blocks"]}
    assert "за рубежом" in text[reqs[1]["evidence"][0]["block_id"]]
    from bcc_review import contracts as C

    C.validate(report)
    assert C.evidence_errors(report) == []
