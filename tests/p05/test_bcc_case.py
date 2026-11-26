"""Регрессия на учебном кейсе BCC (docs/requirements.md @ 928c1aa, SHA-256 e7dae55e…).

Идентификаторы и суммы из задания используются только в этом файле.
"""
from bcc_review.analysis.individual import build_prompt, review_individual
from tests.p05.docfix import BCC_REQS, bcc_case
from tests.p05.helpers import REQ_CODES, FakeAsk, cands_of, checks_of


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
    _, _, res = _run()
    got = {(c["criterion"], c["severity"], tuple(c["req_ids"]), c["hints"][0]["quote"]) for c in res["candidates"]}
    assert got == {
        ("И5", "minor", ("R06",), next(b for b in bcc_case()[0]["blocks"] if "**Ф-2.**" in b["text"])["text"][2:]),
        ("И4", "minor", ("R13",), "заполняются тестировщиками"),
        ("И4", "minor", ("R18",), "Prod: —"),
        ("И4", "minor", ("R19",), "**Swagger** | —"),
        ("И4", "major", ("R25",), "и далее"),
    }
    assert all(c["severity"] != "critical" for c in res["candidates"])


def test_correct_items_get_substantive_positive_result():
    _, _, res = _run()
    f1 = checks_of(res, "R05")["И7"]
    assert f1["status"] == "pass" and "999 / 1 000 / 1 000 000 / 1 000 001" in f1["reason"]
    nfr = checks_of(res, "R10")["И7"]
    assert nfr["status"] == "pass" and "в течение минуты" in nfr["reason"] and "после получения события" in nfr["reason"]
    amount = checks_of(res, "R23")["И7"]
    assert amount["status"] == "pass" and "Ф-1" in amount["reason"]
    for rid in ("R05", "R10", "R14", "R15", "R16", "R22", "R23", "R24", "R26"):
        assert cands_of(res, rid) == [], rid


def test_goal_template_and_interface_context():
    _, _, res = _run()
    goal = checks_of(res, "R01")
    assert goal["И7"]["status"] == "na" and goal["И3"]["status"] == "unknown" and "в момент" in goal["И3"]["reason"]
    assert {c["status"] for c in checks_of(res, "R27").values()} == {"na"}
    assert checks_of(res, "R17")["И4"]["status"] != "issue"  # «REST type | GET» — заполненное поле


def test_prompt_contains_whole_document_and_all_requirements():
    doc, reqs = bcc_case()
    p = build_prompt(doc, reqs)
    for b in doc["blocks"]:
        assert f"[{b['id']}]" in p["user"]
    for rid, _, _ in BCC_REQS:
        assert f"req_id: {rid};" in p["user"]
    assert "Часть B. REST API › Общие параметры" in p["user"]
    assert len(p["system"]) + len(p["user"]) < 60000


def test_model_round_trip_on_case():
    doc, reqs = bcc_case()

    def answer(payload):
        out = []
        for rid in payload["req_ids"]:
            if rid == "R07":
                out.append({"req_id": rid, "checks": [{
                    "criterion": "И8", "status": "issue",
                    "reason": "«максимум один такой push за календарный месяц» конфликтует с Ф-4 после смены порога.",
                    "quote": "максимум один такой push за календарный месяц",
                    "condition": "Push уже был в этом месяце, порог повышен, расходы снова достигли порога.",
                    "impact": "Ф-3 запрещает второй push, Ф-4 его требует: реализации разойдутся.",
                    "question": "Сбрасывает ли изменение порога месячный лимит push?",
                    "severity": "critical", "blocks": "both",
                    "scenario": "Порог 50 000, push 10-го, порог → 80 000, расходы 80 000 20-го: push или нет?",
                    "root_cause": "push_limit_vs_threshold_change"}]})
            elif rid != "R12":
                out.append({"req_id": rid, "checks": []})
        return {"results": out}

    res = review_individual(doc, reqs, ask=FakeAsk(answer))
    (crit,) = [c for c in res["candidates"] if c["criterion"] == "И8"]
    assert crit["severity"] == "critical" and crit["req_ids"] == ["R07"]
    assert crit["hints"][0]["quote"] == "максимум один такой push за календарный месяц"
    assert all(c["status"] == "unknown" for c in checks_of(res, "R12").values() if c["status"] != "na")
