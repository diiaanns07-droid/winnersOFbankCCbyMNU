"""Стыковой тест №06 с bcc/integration: штатные читатель и нарезка, контракт v1, движок run_review."""

import json
import shutil

import pytest

pytest.importorskip("bcc_review.contracts")

from p06_helpers import FIXTURES, ScriptedAsk, evidence_ok, fill, sub  # noqa: E402

from bcc_review import engine  # noqa: E402
from bcc_review.analysis.cross import CrossReview, _load_schema, review_set  # noqa: E402
from bcc_review.contracts import AskError, RunOptions, evidence_errors, validate  # noqa: E402
from bcc_review.runtime.modules import Modules  # noqa: E402

CASE = FIXTURES / "case_ab.md"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(engine, "SLEEP", lambda s: None)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_MODEL",
                "GEMINI_MODEL", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)


def pipeline(path=CASE, slot="read_text"):
    """Как движок: чтение → normalize_document → нарезка №04 (или резерв)."""
    from bcc_review.contracts import as_plain, normalize_document

    m = Modules()
    doc = normalize_document(m.get(slot).func(str(path)))
    inv = as_plain(m.get("build_inventory").func(doc))
    return doc, inv


def run(tmp_path, **opts):
    src = tmp_path / "requirements.md"
    shutil.copyfile(CASE, src)
    base = {"cache_dir": str(tmp_path / "cache"), "artifacts_dir": str(tmp_path / "artifacts")}
    base.update(opts)
    return engine.run_review(src, tmp_path / "report.md", options=RunOptions.coerce(base))


def test_module_output_validates_against_contract_v1():
    doc, inv = pipeline()
    validate(doc, "Document")
    res = review_set(doc, inv["requirements"], None, fact_hints=inv["fact_hints"])
    for c in res["candidates"]:
        validate(c, "Candidate")
        if c.get("witness"):
            assert evidence_ok(doc, c["witness"]["evidence_a"]) and evidence_ok(doc, c["witness"]["evidence_b"])
        if c["severity"] == "critical":
            assert c["impact"] and c["blocked_decision"]
    for f in res["facts"]:
        validate(f, "Fact")
        assert f["evidence"] and all(evidence_ok(doc, e) for e in f["evidence"])
    for cv in res["coverage"]:
        validate(cv, "Coverage")
        assert all(evidence_ok(doc, e) for e in cv["evidence"])
    assert {k: v for k, v in res["evidence_audit"].items() if k in ("checked", "confirmed", "ambiguous", "rejected")}
    validate({k: res["evidence_audit"][k] for k in ("checked", "confirmed", "ambiguous", "rejected", "note")}, "EvidenceAudit")

    # нарезка Max: строки приёмки — требования R-…, их id становятся acceptance_ids
    reqs = {r["id"]: r for r in inv["requirements"]}
    by_text = lambda needle: [r for r, x in reqs.items() if needle in x["text"]]  # noqa: E731
    k1 = [c for c in sub(res, "conflict") if "периода" in c["title"]]
    assert len(k1) == 1
    acc2 = by_text("Покупка 31 января")
    f2 = by_text("Месяц определяется по дате совершения")
    assert len(acc2) == 1 and len(f2) == 1
    assert k1[0]["acceptance_ids"] == acc2
    assert k1[0]["req_ids"] == f2 + acc2  # строка приёмки — тоже требование нарезки
    gap = sub(res, "missing_contract")
    assert len(gap) == 1 and gap[0]["kind"] == "omission" and gap[0]["criterion"] == "set_complete"
    # знаменатель покрытия — обязательства правил; контракт API и примеры исключены с причиной
    s = res["coverage_summary"]
    excluded = {e["req_id"] for e in s["excluded"]}
    amount_block = next(b["id"] for b in doc["blocks"] if b["kind"] == "table_row" and b["text"].startswith("amount"))
    query_row = next(r for r, x in reqs.items() if amount_block in x["block_ids"])
    logic5 = by_text("При отклонении суммы")[0]
    assert query_row in excluded and logic5 not in excluded
    assert s["denominator"] == len(res["coverage"]) and s["covered"] == 0 and s["conflict"] >= 1


def test_07_resolves_module_candidates_as_supported():
    doc, inv = pipeline()
    res = review_set(doc, inv["requirements"], None)
    rc = Modules().get("resolve_candidate").func
    for c in sub(res, "conflict") + sub(res, "missing_contract"):
        r = rc(doc, c)
        assert r["anchor_status"] == "supported", (c["title"], r.get("reasons"))


def test_engine_offline_run_uses_team_module_and_report_is_valid(tmp_path):
    rep = run(tmp_path, offline_lint=True)
    validate(rep)
    assert evidence_errors(rep) == []
    assert rep["run"]["modules"]["review_set"] == "team:bcc_review.analysis.cross:review_set"
    assert rep["facts"] and rep["coverage"]
    conf = [f for f in rep["findings"] if f["kind"] == "conflict" and f.get("witness")]
    assert any("периода" in f["title"] for f in conf)
    assert any(f["kind"] == "omission" and f["inspected_block_ids"] for f in rep["findings"])


def _k2_script(doc, inv):
    """Ответы стадий №06 для mock-провайдера: K2 в том пакете, где программа отправит пару Ф-3/Ф-4."""
    from test_p06_case_ab import _k2

    cr = CrossReview(doc, inv["requirements"], lambda *a: {}, inv["fact_hints"], None, 60, 30)
    for c in cr.fs.candidates:
        cr.add(dict(c))
    cr.period_checks()
    cr.contract_gaps()
    pairs = cr.select_pairs(cr.units())
    qa, qb = "максимум один такой push", "независимо от истории"
    idx = next(i for i, (a, b, _, _) in enumerate(pairs)
               if (qa in a.text and qb in b.text) or (qb in a.text and qa in b.text))
    a, b = pairs[idx][0], pairs[idx][1]
    first = qa in a.text
    pa, pb = ({"block_id": a.block_id}, {"block_id": b.block_id}) if first else ({"block_id": b.block_id}, {"block_id": a.block_id})
    ans = _k2(pa, pb)
    if not first:
        from p06_helpers import _swap
        ans = _swap(ans)
    ans["pair_id"] = f"P-{idx + 1:03d}"
    schema = _load_schema("cross#pairs")
    batches = [fill(schema, {"pairs": [ans] if i == idx // 30 else []}) for i in range((len(pairs) + 29) // 30)]
    return {"cross#pairs": batches + [fill(schema, {"pairs": []})],
            "cross#coverage": fill(_load_schema("cross#coverage"), {"obligations": [], "links": []}),
            "verify_meaning": {"__verdicts__": "confirmed"}}


def test_engine_mock_run_confirms_k2_through_engine(tmp_path):
    doc, inv = pipeline()
    script = tmp_path / "script.json"
    script.write_text(json.dumps(_k2_script(doc, inv), ensure_ascii=False), encoding="utf-8")
    rep = run(tmp_path, provider="mock", mock_script=str(script))
    validate(rep)
    assert evidence_errors(rep) == []
    stage = next(s for s in rep["run"]["stages"] if s["name"] == "cross")
    assert stage["status"] == "ok" and stage["calls"] >= 2, stage
    k2 = [f for f in rep["findings"] if f["kind"] == "conflict" and "Ф-3 и Ф-4" in f["title"]]
    assert len(k2) == 1 and k2[0]["witness"] and k2[0]["anchor_status"] == "supported"
    assert "максимум один такой push" in k2[0]["witness"]["evidence_a"]["quote"]


def test_engine_marks_cross_failed_when_model_never_answers(tmp_path):
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"cross#pairs": {"error": "invalid_output"}, "cross#coverage": {"error": "invalid_output"}}),
                      encoding="utf-8")
    rep = run(tmp_path, provider="mock", mock_script=str(script))
    validate(rep)
    stage = next(s for s in rep["run"]["stages"] if s["name"] == "cross")
    assert stage["status"] == "failed"
    assert rep["run"]["status"] == "partial"
    # правила №06 сохранились после перезапуска с ask=None
    assert any("периода" in f["title"] for f in rep["findings"] if f["kind"] == "conflict")


def test_ask_error_is_reraised_only_when_no_call_succeeded(case_doc):
    from p06_helpers import requirements_from

    err = AskError("cross#pairs", "invalid_output", "схема")
    with pytest.raises(AskError):
        review_set(case_doc, requirements_from(case_doc), ScriptedAsk(fail_stages={"cross#pairs", "cross#coverage"}, error=err))
    res = review_set(case_doc, requirements_from(case_doc), ScriptedAsk(fail_stages={"cross#coverage"}, error=err))
    assert res["stats"]["status"] == "partial" and res["stats"]["llm_failed"] == ["cross#coverage"]


def test_markdown_and_pdf_give_same_cross_results():
    """PDF обязателен по ТЗ: тот же документ в PDF даёт те же кандидаты и тот же знаменатель покрытия."""
    pytest.importorskip("pymupdf")
    out = {}
    for name, slot in (("case_ab.md", "read_text"), ("../../integration/fixtures/bcc_requirements.pdf", "read_pdf")):
        doc, inv = pipeline(FIXTURES / name, slot)
        res = review_set(doc, inv["requirements"], None)
        # лексические partial/uncovered зависят от мелочей текста читателя — сравниваем устойчивые выводы
        out[slot] = ({(c["subkind"], c["severity"], c["title"]) for c in res["candidates"]},
                     {k: res["coverage_summary"][k] for k in ("denominator", "covered", "conflict")},
                     sorted(c["obligation"] for c in res["coverage"]))
        for c in res["candidates"]:
            if c.get("witness"):
                assert evidence_ok(doc, c["witness"]["evidence_a"]) and evidence_ok(doc, c["witness"]["evidence_b"])
    assert out["read_text"] == out["read_pdf"]
