"""Серьёзность на пограничных формулировках: четыре пары банковских правил в одном документе.

Вход: tests/p05/fixtures/borderline_bank.md (SHA-256 d4ea97ad…), записанные ответы модели в схеме №05:
tests/p05/fixtures/borderline_bank.answers.json. В каждой паре один вариант пригоден для проверки.

| Пара | Пригоден | Не пригоден |
| 1 срок | ЗП-1 «не позднее 30 секунд после подтверждения» | ЗП-2 «оперативно уведомляет» |
| 2 единицы | ЛМ-1 сумма под заголовком «Лимиты переводов, ₸» | ЛМ-2 сумма без единиц в соседнем разделе |
| 3 термины | ВЗ-1 «рабочих дней» (определение Т-1) | МН-1 «подозрительная операция», «крупный клиент» |
| 4 модальность | БК-1 «Банк блокирует карту» | БК-2 «Желательно отправлять push» |
"""
import json
import re

import pytest

from bcc_review.analysis.individual import response_schema, review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import FIXTURES, load_fixture, requirement
from tests.p05.helpers import FakeAsk, cands_of, checks_of, wcodes

IDS = ["ЗП-1", "ЗП-2", "ЛМ-1", "ЛМ-2", "ВЗ-1", "МН-1", "БК-1", "БК-2"]
CRIT = load_criteria()

# (пригодный, непригодный, критерий, исход с записанными ответами, исход только по правилам)
PAIRS = [
    ("ЗП-1", "ЗП-2", "verifiable", ("pass", "issue"), ("pass", "issue")),
    ("ЛМ-1", "ЛМ-2", "unambiguous", ("pass", "issue"), ("pass", "issue")),
    ("ВЗ-1", "МН-1", "unambiguous", ("pass", "issue"), ("unknown", "unknown")),   # термины решает модель
    ("БК-1", "БК-2", "unambiguous", ("pass", "issue"), ("unknown", "unknown")),   # модальность — решение владельца
]
# первопричины непригодных вариантов: цитата → серьёзность
EXPECTED_CANDS = {
    "ЗП-2": {"оперативно": "major"},
    "ЛМ-2": {"200 000": "major"},
    "МН-1": {"Подозрительная операция": "critical", "крупного клиента": "major"},
    "БК-2": {"Желательно": "major"},
}


def _doc():
    doc = load_fixture("borderline_bank.md")
    return doc, [requirement(doc, rid, rid + ".", rid) for rid in IDS]


def _recorded():
    return json.loads((FIXTURES / "borderline_bank.answers.json").read_text("utf-8"))


def _block_text(doc, block_id):
    return next(b["text"] for b in doc["blocks"] if b["id"] == block_id)


def test_recorded_answers_match_strict_schema():
    import jsonschema

    jsonschema.validate(_recorded(), response_schema(CRIT))


def test_pairs_with_recorded_answers_document_level():
    doc, reqs = _doc()
    res = review_individual(doc, reqs, ask=FakeAsk(_recorded()), criteria=CRIT)
    assert res["failed"] == {} and not {"individual.out_of_scope_basis", "individual.quote_not_found"} & set(wcodes(res))

    for fit, unfit, code, (want_fit, want_unfit), _ in PAIRS:
        assert checks_of(res, fit)[code]["status"] == want_fit, fit
        assert checks_of(res, unfit)[code]["status"] == want_unfit, unfit
        assert cands_of(res, fit) == [], fit  # пригодный вариант без выдуманного дефекта

    # на уровне документа: одна кандидатура на первопричину, никаких лишних
    got = {(rid, c["hints"][0]["quote"]): c["severity"] for c in res["candidates"] for rid in c["req_ids"]}
    want = {(rid, q): sev for rid, d in EXPECTED_CANDS.items() for q, sev in d.items()}
    assert got == want
    assert len(res["candidates"]) == 5

    for c in res["candidates"]:
        # одна дословная опора
        h = c["hints"][0]
        assert h["quote"] in _block_text(doc, h["block_id"])
        # причина серьёзности: блокируемое решение и последствие; у critical — сценарий
        assert c["blocked_decision"] and c["impact"]
        if c["severity"] == "critical":
            assert c["scenario"] and set(c["blocks"]) == {"development", "testing"}
        # решение владельца — в штатном поле question
        assert c["question"]
        # в правке нет чисел, кроме чисел самого пункта или маркера <уточнить у владельца: …>
        bare = re.sub(r"<уточнить[^<>]*>", "", c["recommendation"])
        req_text = next(r["text"] for r in reqs if r["id"] == c["req_ids"][0])
        assert all(n in req_text for n in re.findall(r"\d[\d ]*\d|\d", bare)), c["recommendation"]

    # действующая область определения сохранена в основании
    assert "Лимиты переводов, ₸" in checks_of(res, "ЛМ-1")["unambiguous"]["reason"]
    assert "[b0007]" in checks_of(res, "ЛМ-1")["unambiguous"]["reason"]
    assert "действует только на свой раздел" in checks_of(res, "ЛМ-2")["unambiguous"]["reason"]
    assert "Т-1 [b0003]" in checks_of(res, "ВЗ-1")["unambiguous"]["reason"]


def test_pairs_rules_only_document_level():
    """Что решается без модели. Пары 3 и 4 различает только модель (или владелец)."""
    doc, reqs = _doc()
    res = review_individual(doc, reqs, criteria=CRIT)
    for fit, unfit, code, _, (want_fit, want_unfit) in PAIRS:
        assert checks_of(res, fit)[code]["status"] == want_fit, fit
        assert checks_of(res, unfit)[code]["status"] == want_unfit, unfit
    assert {(c["req_ids"][0], c["severity"]) for c in res["candidates"]} == {("ЗП-2", "major"), ("ЛМ-2", "major")}
    # контекст для модели и владельца есть и без модели
    assert "Т-1 [b0003]" in checks_of(res, "ВЗ-1")["unambiguous"]["reason"]
    bk2 = checks_of(res, "БК-2")["unambiguous"]
    assert "обязательное или рекомендательное" in bk2["question"] and "severity" not in bk2


# ------------------------------------------------------------------ регрессии на доказанные ошибки (39254ae)

def test_regression_coincidental_number_does_not_reject_correct_pass():
    """Было: pass БК-1 «тест вводит 2 и 3 неверных ПИН-кода» отклонялся, потому что «3» стоит в ВЗ-1 другого раздела."""
    doc, reqs = _doc()
    res = review_individual(doc, reqs, ask=FakeAsk(_recorded()), criteria=CRIT)
    chk = checks_of(res, "БК-1")["verifiable"]
    assert chk["status"] == "pass" and chk["source"] == "llm"
    assert "individual.out_of_scope_basis" not in wcodes(res)


def test_regression_two_root_causes_under_one_criterion():
    """Было: вторая запись модели по unambiguous МН-1 («крупного клиента») отбрасывалась."""
    doc, reqs = _doc()
    res = review_individual(doc, reqs, ask=FakeAsk(_recorded()), criteria=CRIT)
    mn = cands_of(res, "МН-1")
    assert sorted(c["hints"][0]["quote"] for c in mn) == ["Подозрительная операция", "крупного клиента"]
    chk = checks_of(res, "МН-1")["unambiguous"]
    assert chk["severity"] == "critical" and set(chk["candidate_refs"]) == {c["ref"] for c in mn}


def test_regression_recommendation_word_alone_sets_no_severity():
    """Было: «Желательно» без модели давало major по словарю лазеек и неверный текст про условие."""
    doc, reqs = _doc()
    res = review_individual(doc, reqs, criteria=CRIT)
    assert cands_of(res, "БК-2") == []
    chk = checks_of(res, "БК-2")["unambiguous"]
    assert chk["status"] == "unknown" and "решение владельца" in chk["reason"]


def test_dictionary_rule_does_not_raise_model_severity():
    """«Оперативно» есть в словаре (правило: major), модель откалибровала minor — итог minor с пометкой."""
    doc, reqs = _doc()
    rec = _recorded()
    zp2 = next(r for r in rec["results"] if r["req_id"] == "ЗП-2")
    v = next(c for c in zp2["checks"] if c["criterion"] == "verifiable")
    v.update(severity="minor", blocks="none")
    res = review_individual(doc, reqs, ask=FakeAsk(rec), criteria=CRIT)
    (cand,) = cands_of(res, "ЗП-2")
    assert cand["severity"] == "minor" == checks_of(res, "ЗП-2")["verifiable"]["severity"]
    assert any("основано на словаре" in n for n in cand["calibration"])


def test_heading_units_apply_only_to_own_section():
    doc, reqs = _doc()
    res = review_individual(doc, reqs, criteria=CRIT)
    (cand,) = cands_of(res, "ЛМ-2")
    assert cand["hints"][0]["quote"] == "200 000" and "<уточнить у владельца" in cand["recommendation"]
    assert "Лимиты переводов, ₸" in checks_of(res, "ЛМ-2")["unambiguous"]["reason"]


# ------------------------------------------------------------------ сквозной сценарий через движок

def test_engine_end_to_end_with_recorded_answers(tmp_path, monkeypatch):
    engine = pytest.importorskip("bcc_review.engine")
    C = pytest.importorskip("bcc_review.contracts")
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    src = FIXTURES / "borderline_bank.md"

    off = engine.run_review(src, tmp_path / "off.md", options=C.RunOptions.coerce(
        {"offline_lint": True, "use_cache": False, "artifacts_dir": str(tmp_path / "off.art")}))
    assert off["run"]["modules"]["review_individual"].startswith("team:")
    ids = {r["source_id"]: r["id"] for r in off["requirements"]}
    assert set(IDS) <= set(ids)
    # офлайн: «оперативно» правила движка и №05 — одна находка; единицы ЛМ-2 — вторая
    assert sorted((f["criterion"], f["evidence"][0]["quote"]) for f in off["findings"]) == [
        ("unambiguous", "200 000"), ("verifiable", "оперативно")]

    rec = _recorded()
    for r in rec["results"]:
        r["req_id"] = ids[r["req_id"]]
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"individual": rec}, ensure_ascii=False), "utf-8")
    runs = []
    for n in (1, 2):
        rep = engine.run_review(src, tmp_path / f"m{n}.md", options=C.RunOptions.coerce(
            {"provider": "mock", "mock_script": str(script), "cache_dir": str(tmp_path / "cache"),
             "artifacts_dir": str(tmp_path / f"m{n}.art")}))
        C.validate(rep)
        assert C.evidence_errors(rep) == []
        runs.append(rep)
    first, second = runs
    stage = {s["name"]: s for s in first["run"]["stages"]}["individual"]
    assert stage["status"] == "ok" and stage["implementation"].startswith("team:")
    assert {r["review_status"] for r in first["requirements"]} == {"reviewed"}
    assert second["run"]["calls"]["physical"] == 0 and second["run"]["calls"]["cache_hits"] > 0

    by_src = {r["id"]: r["source_id"] for r in first["requirements"]}
    got = sorted((by_src[f["req_ids"][0]], f["evidence"][0]["quote"], f["severity"]) for f in first["findings"])
    assert got == sorted((rid, q, sev) for rid, d in EXPECTED_CANDS.items() for q, sev in d.items())
    fit = {"ЗП-1", "ЛМ-1", "ВЗ-1", "БК-1"}
    assert not any(by_src[r] in fit for f in first["findings"] for r in f["req_ids"])
