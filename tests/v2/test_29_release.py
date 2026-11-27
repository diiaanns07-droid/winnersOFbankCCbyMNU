"""№29 — исправления постобработки линз «Архитектор» и «Риски» для релиза.

Кандидат без цитаты (пустые или пробельные `quote` проходят схему) не должен занимать место в лимите линзы:
иначе он вытесняет настоящее замечание («сверх лимита»), а потом его всё равно снимает сверка цитат.
"""
from __future__ import annotations

import random

from bcc_review.v2.stages import lens_architect as A
from bcc_review.v2.stages import lens_risk as R

VIEW = {"lines": [
    {"n": 1, "text": "# Требования", "section": "Требования"},
    {"n": 2, "text": "Ф-1. Клиент включает уведомление о переводе.", "section": "Требования"},
    {"n": 3, "text": "Ф-2. Повторная доставка события сохраняет исходный итог.", "section": "Требования"},
    {"n": 4, "text": "Метод GET /settings?cardId=…&amount=… сохраняет настройку.", "section": "API"},
]}


def _cand(title: str, quote: str, line: int = 2, severity: str = "major", kind: str = "security") -> dict:
    return {"title": title, "kind": kind, "criterion": "risk", "severity": severity, "requirement_ids": [],
            "evidence": [{"quote": quote, "line": line}], "problem": "п", "scenario": "с", "impact": "и",
            "recommendation": "р", "rewrite": "", "question": "", "blocks": "development"}


def test_risk_empty_quote_dropped_with_reason():
    kept, dropped = R.postprocess([_cand("Сумма в строке запроса GET", ""), _cand("Сумма в строке запроса", "   ")],
                                  VIEW)
    assert kept == []
    assert [d["reject_reason"] for d in dropped] == ["нет цитаты-зацепки"] * 2


def test_risk_empty_quote_does_not_take_a_slot():
    # 12 мест: пустышка первой не должна вытеснить двенадцатое настоящее замечание
    real = [_cand(f"Номер карты в строке запроса, случай {i}", VIEW["lines"][3]["text"], 4) for i in range(12)]
    kept, dropped = R.postprocess([_cand("Данные в строке запроса GET", "")] + real, VIEW)
    assert len(kept) == 12
    assert {c["title"] for c in kept} == {c["title"] for c in real}
    assert all(any(e["quote"].strip() for e in c["evidence"]) for c in kept)
    assert not [d for d in dropped if "сверх лимита" in d["reject_reason"]]


def test_risk_mixed_evidence_keeps_only_real_quotes():
    c = _cand("Повтор события: не назван признак повтора", VIEW["lines"][2]["text"], 3, kind="ops_risk")
    c["evidence"] = [{"quote": "", "line": 1}] + c["evidence"] + [{"quote": " ", "line": 4}]
    kept, _ = R.postprocess([c], VIEW)
    assert len(kept) == 1 and [e["line"] for e in kept[0]["evidence"]] == [3]


def test_architect_empty_quote_dropped():
    out = A.postprocess({"candidates": [_cand("Поле без типа", "", kind="api_contract"),
                                        _cand("Поле без типа", " \t", kind="api_contract")]})
    assert out["candidates"] == []


def _random_answer(rnd: random.Random) -> list[dict]:
    words = ["", " ", "повтор события", "GET строка запроса", "откат", "пояс Алматы", "возврат", "держатель карты",
             "Ветка логики без ответа", "L052", "критерий приёмки", "PCI", "ИИ-ассистенту"]
    out = []
    for _ in range(rnd.randint(0, 15)):
        ev = [{"quote": rnd.choice(["", " ", rnd.choice(VIEW["lines"])["text"], rnd.choice(words)]),
               "line": rnd.choice([0, -1, 2, 3, 10 ** 9])} for _ in range(rnd.randint(0, 3))]
        out.append({**_cand(" ".join(rnd.choice(words) for _ in range(3)), "", kind=rnd.choice(A.KINDS),
                            severity=rnd.choice(["critical", "major", "minor"])),
                    "evidence": ev, "blocks": rnd.choice(["development", "testing", "both", "none"])})
    return out


def test_fuzz_no_crash_and_no_candidate_without_quote():
    rnd = random.Random(29)
    for _ in range(1500):
        cands = _random_answer(rnd)
        kept, dropped = R.postprocess(cands, VIEW, known_ids=["R-01"], acceptance_ids=[])
        assert len(kept) <= R.MAX_CANDIDATES
        assert all(any(str(e.get("quote") or "").strip() for e in c["evidence"]) for c in kept)
        arch = A.postprocess({"candidates": cands, "inventory": {}}, requirement_ids={"R-01"})
        assert all(any(str(e.get("quote") or "").strip() for e in c["evidence"]) for c in arch["candidates"])
