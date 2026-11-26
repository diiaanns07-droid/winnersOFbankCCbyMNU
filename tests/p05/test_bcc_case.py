"""Регрессия на учебном кейсе BCC (docs/requirements.md @ 928c1aa, SHA-256 e7dae55e…).

Идентификаторы и суммы из задания используются только в этом файле.
"""
from bcc_review.analysis.individual import build_prompt, review_individual
from tests.p05.docfix import BCC_REQS, bcc_case
from tests.p05.helpers import REQ_CODES, FakeAsk, cands_of, checks_of, issue


def _run(**kw):
    doc, reqs = bcc_case()
    return doc, reqs, review_individual(doc, reqs, **kw)


def test_fixture_is_the_issued_document():
    doc, _ = bcc_case()
    assert doc["id"] == "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"


def test_rules_only_matrix_is_complete():
    _, reqs, res = _run()
    assert res["meta"]["mode"] == "rules_only" and res["meta"]["calls"] == 0
    assert len(res["checks"]) == len(reqs) * len(REQ_CODES)
    for c in res["checks"]:
        assert c["status"] in ("pass", "issue", "unknown", "na") and c["reason"]


def test_rules_only_findings_are_calibrated():
    doc, _, res = _run()
    f2 = next(b for b in doc["blocks"] if b["text"].startswith("Ф-2."))["text"]
    got = {(c["criterion"], c["kind"], c["severity"], tuple(c["req_ids"]), c["hints"][0]["quote"]) for c in res["candidates"]}
    assert got == {
        ("singular", "non_singular", "minor", ("R06",), f2),
        ("complete", "placeholder", "minor", ("R13",), "заполняются тестировщиками"),
        ("complete", "placeholder", "minor", ("R18",), "Prod: —"),
        ("complete", "placeholder", "minor", ("R19",), "Swagger | —"),
        ("complete", "incomplete", "major", ("R25",), "и далее"),
    }
    assert all(c["severity"] != "critical" for c in res["candidates"])


def test_correct_items_get_substantive_positive_result():
    _, _, res = _run()
    f1 = checks_of(res, "R05")["verifiable"]
    assert f1["status"] == "pass" and "999 / 1 000 / 1 000 000 / 1 000 001" in f1["reason"]
    nfr = checks_of(res, "R10")["verifiable"]
    assert nfr["status"] == "pass" and "в течение минуты" in nfr["reason"] and "после получения события" in nfr["reason"]
    amount = checks_of(res, "R23")["verifiable"]
    assert amount["status"] == "pass" and "Ф-1" in amount["reason"]
    for rid in ("R05", "R10", "R14", "R15", "R16", "R22", "R23", "R24", "R26"):
        assert cands_of(res, rid) == [], rid


def test_goal_template_and_interface_context():
    _, _, res = _run()
    goal = checks_of(res, "R01")
    assert goal["verifiable"]["status"] == "na" and goal["unambiguous"]["status"] == "unknown"
    assert "в момент" in goal["unambiguous"]["reason"]
    assert {c["status"] for c in checks_of(res, "R27").values()} == {"na"}
    assert checks_of(res, "R17")["complete"]["status"] != "issue"  # «REST type | GET» — заполненное поле


def test_payload_requests_context_and_lists_all_requirements():
    doc, reqs = bcc_case()
    p = build_prompt(doc, reqs)
    assert [r["req_id"] for r in p["input"]["requirements"]] == [rid for rid, _, _ in BCC_REQS]
    for r in reqs:
        assert set(r["block_ids"]) <= set(p["context"]["block_ids"])
    r18 = next(r for r in p["input"]["requirements"] if r["req_id"] == "R18")
    assert r18["role"] == "metadata" and r18["level"] == "interface"
    assert any(s["rule"] == "placeholder" for s in r18["rule_signals"])
    assert len(p["task"]) < 20000


def test_model_round_trip_on_case():
    doc, reqs = bcc_case()

    def answer(payload):
        out = []
        for rid in payload["input"]["req_ids"]:
            if rid == "R07":
                out.append({"req_id": rid, "checks": [issue(
                    "correct", "«максимум один такой push за календарный месяц» конфликтует с Ф-4 после смены порога.",
                    "максимум один такой push за календарный месяц", kind="conflict",
                    condition="Push уже был в этом месяце, порог повышен, расходы снова достигли порога.",
                    outcomes=["push не отправляется", "push отправляется"],
                    impact="Ф-3 запрещает второй push, Ф-4 его требует: реализации разойдутся.",
                    question="Сбрасывает ли изменение порога месячный лимит push?",
                    severity="critical", blocks="both", blocked_decision="Отправлять ли второй push после смены порога",
                    scenario="Порог 50 000, push 10-го, порог → 80 000, расходы 80 000 20-го: push или нет?",
                    root_cause="push_limit_vs_threshold_change")]})
            elif rid != "R12":
                out.append({"req_id": rid, "checks": []})
        return {"results": out}

    ask = FakeAsk(answer)
    res = review_individual(doc, reqs, ask=ask)
    assert len(ask.calls) == 2  # 27 пунктов, batch_size = 15
    (crit,) = [c for c in res["candidates"] if c["criterion"] == "correct"]
    assert crit["severity"] == "critical" and crit["req_ids"] == ["R07"] and crit["kind"] == "conflict"
    assert crit["hints"][0]["quote"] == "максимум один такой push за календарный месяц"
    assert crit["blocks"] == ["development", "testing"]
    assert all(c["status"] == "unknown" for c in checks_of(res, "R12").values() if c["status"] != "na")
