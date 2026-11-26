"""Сквозной сценарий №06: review_set → настоящий Asker движка → записанный транспорт (двойник провайдера).

Независимый сюжет — граница месяца для начисления кэшбэка. Одна точка входа, три документа:
1. два явно несовместимых определения расчётной даты — конфликт с двумя точными местами;
2. почти одинаковые тексты для разных типов операций — этого конфликта нет (и «наивный» ответ модели отклонён);
3. правила привязки к дате нет — пропуск с перечнем просмотренных разделов и вопросом без выдуманной цитаты.
Ответы модели в кассете имитированы (tests/p06/fixtures/cassette_cashback.json).
"""

import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("bcc_review.runtime.asker")

from p06_helpers import FIXTURES, RecordedTransport, evidence_ok, make_asker, read_pipeline  # noqa: E402

from bcc_review import contracts as C  # noqa: E402
from bcc_review.analysis.cross import review_set  # noqa: E402
from bcc_review.runtime.modules import Modules  # noqa: E402

CASSETTE = FIXTURES / "cassette_cashback.json"
CRITERIA = Path(C.__file__).resolve().parent / "criteria.toml"
SENT_A = "Расчётный месяц кэшбэка определяется по дате совершения покупки по времени Астаны."
SENT_B = "Расчётный месяц кэшбэка определяется по дате проведения операции по времени Астаны."
FABRICATED = "Дата, по которой выбирается ставка кэшбэка, не определена."


def run_scenario(name: str, cache_dir=None):
    """Единая точка входа: документ → нарезка движка → review_set(ask = настоящий Asker на двойнике)."""
    doc, inv = read_pipeline(FIXTURES / f"{name}.md")
    transport = RecordedTransport(CASSETTE)
    asker, stats, budget = make_asker(doc, inv["requirements"], transport, cache_dir)
    res = review_set(doc, inv["requirements"], asker, fact_hints=inv["fact_hints"])
    return doc, inv, res, transport, stats, budget


def line_of(doc, block_id):
    return next(b for b in doc["blocks"] if b["id"] == block_id)["loc"]["line_start"]


def assert_stage_contract(transport, stats, budget, res):
    """Формат этапов как в интеграции: cross#pairs и cross#coverage, payload {task, input, context}, документ — от Asker."""
    assert [r["stage"] for r in transport.requests] == ["cross#pairs", "cross#coverage"]
    for r in transport.requests:
        msgs = r["messages"]
        assert msgs[0]["role"] == "system"
        assert any(m["content"].startswith("ДОКУМЕНТ ЦЕЛИКОМ") and "[b0001]" in m["content"] for m in msgs[1:-1])
        assert "ЗАДАЧА ЭТАПА:" in msgs[-1]["content"] and "document" not in r["input"]
    assert set(transport.requests[0]["input"]) == {"document_title", "facts", "pairs", "blocks"}
    assert set(transport.requests[1]["input"]) >= {"obligations", "acceptance", "known_conflicts"}
    # учёт фактических вызовов: подэтапы сведены в этап «cross»
    rec = stats.stages["cross"]
    assert rec.calls == len(transport.requests) == budget.calls == res["stats"]["llm_calls"] == 2
    assert rec.failed_calls == 0 and rec.retries == 0 and rec.cache_hits == 0
    assert res["stats"]["mode"] == "rules_plus_llm" and res["stats"]["status"] == "complete"


def assert_codes(cands):
    codes = {c["code"] for c in tomllib.loads(CRITERIA.read_text(encoding="utf-8"))["criterion"]}
    for c in cands:
        C.validate(c, "Candidate")
        assert c["kind"] in C.FINDING_KINDS and c["criterion"] in C.SET_CRITERIA and c["criterion"] in codes


def test_1_two_incompatible_settlement_dates_conflict_with_two_exact_places():
    doc, inv, res, transport, stats, budget = run_scenario("cashback_two_dates")
    assert_stage_contract(transport, stats, budget, res)
    assert_codes(res["candidates"])
    conf = [c for c in res["candidates"] if c["subkind"] == "conflict"]
    assert len(conf) == 1, [c["title"] for c in res["candidates"]]
    c = conf[0]
    # правило нашла программа, модель через Asker подтвердила тот же конфликт — без дубля
    assert c["origin"] == "rules" and c.get("confirmed_by") == ["llm"]
    # обе исходные цитаты и два точных места
    w = c["witness"]
    assert (w["hint_a"]["quote"], w["hint_b"]["quote"]) == (SENT_A, SENT_B)
    for ev in (w["evidence_a"], w["evidence_b"]):
        assert evidence_ok(doc, ev)
    assert (line_of(doc, w["evidence_a"]["block_id"]), line_of(doc, w["evidence_b"]["block_id"])) == (7, 10)
    assert [p["where"] for p in c["places"]] == ["КЭШ-2 (Функциональные требования, строка 7)",
                                                  f"{c['req_ids'][1]} (Требования к интеграции, строка 10)"]
    # общий объект и влияние на решение
    assert c["cause"]["object"] == "Расчётный месяц кэшбэка"
    assert c["severity"] == "critical" and c["criterion"] == "set_consistent"
    assert "«совершения покупки»" in c["blocked_decision"] and "«проведения операции»" in c["blocked_decision"]
    assert "к январю" in c["impact"] and "к февралю" in c["impact"]
    assert (w["outcome_a_value"], w["outcome_b_value"]) == ("январь", "февраль")
    assert Modules().get("resolve_candidate").func(doc, c)["anchor_status"] == "supported"


def test_2_same_words_different_operation_types_no_conflict():
    doc, inv, res, transport, stats, budget = run_scenario("cashback_by_operation")
    assert_stage_contract(transport, stats, budget, res)
    blocks = {b["id"]: b["text"] for b in doc["blocks"]}
    k1 = next(b for b, t in blocks.items() if t.startswith("КЭШ-1") or "Для покупок расчётный" in t)
    k2 = next(b for b, t in blocks.items() if "Для возвратов расчётный" in t)
    # этого конкретного конфликта нет ни от правил, ни от модели
    assert not [c for c in res["candidates"] if c["kind"] == "conflict" and {h["block_id"] for h in c["hints"]} >= {k1, k2}]
    assert [c for c in res["candidates"] if c["kind"] == "conflict"] == []
    rules = [x for x in res["comparisons"] if x["aspect"] == "period_anchor"]
    assert rules and rules[0]["verdict"] == "compatible" and "при разных условиях" in rules[0]["explanation"]
    model = [x for x in res["comparisons"] if x["aspect"] == "semantic"]
    assert model and model[0]["verdict"] == "compatible" and "тип операции" in model[0]["explanation"]
    # строка приёмки о возврате проверена по правилу для возвратов, а не для покупок
    assert any(x["aspect"] == "period" and x["verdict"] == "compatible" and "Для возвратов" in x["explanation"]
               for x in res["comparisons"])


def test_3_missing_rule_lists_inspected_sections_and_asks_without_fabricated_quote():
    doc, inv, res, transport, stats, budget = run_scenario("cashback_missing_rule")
    assert_stage_contract(transport, stats, budget, res)
    assert_codes(res["candidates"])
    gaps = [c for c in res["candidates"] if c["subkind"] == "missing_rule"]
    assert len(gaps) == 1, [c["title"] for c in res["candidates"]]
    g = gaps[0]
    assert g["kind"] == "omission" and g["criterion"] == "set_complete" and g["severity"] == "critical"
    # перечень просмотренных разделов и границы просмотра
    assert g["inspected_scope"]["sections"] == ["Часть A. Бизнес-требования / Функциональные требования",
                                                "Часть A. Бизнес-требования / Требования к интеграции",
                                                "Часть A. Бизнес-требования / Требования к данным"]
    assert g["inspected_scope"]["span"] == "строки 6–13"
    assert g["inspected_block_ids"] and any("определяется по дате" in s for s in g["searched_for"])
    # вопрос с данными документа
    assert g["question"].startswith("По какой дате определяется ставка кэшбэка на границе периода?")
    assert "«31 марта в 23:58»" in g["question"] and "«1 апреля в 00:03»" in g["question"] and "1 % и 2 %" in g["question"]
    # ни одной выдуманной отрицательной цитаты: все опоры — подстроки текущего документа
    texts = [b["text"] for b in doc["blocks"]]
    for h in g["hints"]:
        assert any(h["quote"] in t for t in texts) and not re.search(r"\bне\s+(определ|указ|задан)", h["quote"])
    flat = str(res["candidates"])
    assert FABRICATED not in flat
    assert res["evidence_audit"]["rejected"] >= 1  # выдуманную цитату модели отклонил №07
    assert Modules().get("resolve_candidate").func(doc, g)["anchor_status"] == "supported"


def test_recorded_answers_are_cached_physical_calls_drop_to_zero(tmp_path):
    """Повторный прогон с тем же кэшем: логически те же этапы, физических вызовов двойника — ноль."""
    *_, t1, s1, b1 = run_scenario("cashback_two_dates", cache_dir=tmp_path)
    *_, res2, t2, s2, b2 = run_scenario("cashback_two_dates", cache_dir=tmp_path)
    assert len(t1.requests) == 2 and len(t2.requests) == 0
    assert s2.stages["cross"].cache_hits == 2 and b2.calls == 0
    assert [c for c in res2["candidates"] if c["subkind"] == "conflict"][0].get("confirmed_by") == ["llm"]


def test_1_through_engine_run_review_reaches_findings(tmp_path, monkeypatch):
    """Тот же сценарий 1 через run_review: Asker движка, записанный транспорт вместо mock-адаптера, отчёт v1."""
    import shutil

    from bcc_review import engine
    from bcc_review.contracts import RunOptions

    monkeypatch.setattr(engine, "SLEEP", lambda s: None)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("BCC_FORCE_FALLBACK", raising=False)
    transports = []

    def adapter(script=None, model=None):
        transports.append(RecordedTransport(CASSETTE))
        return transports[-1]

    monkeypatch.setattr(engine, "MockAdapter", adapter)
    src = tmp_path / "cashback.md"
    shutil.copyfile(FIXTURES / "cashback_two_dates.md", src)
    rep = engine.run_review(src, tmp_path / "report.md", options=RunOptions.coerce(
        {"provider": "mock", "cache_dir": str(tmp_path / "cache"), "artifacts_dir": str(tmp_path / "art")}))
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    assert rep["run"]["modules"]["review_set"] == "team:bcc_review.analysis.cross:review_set"
    cross = next(s for s in rep["run"]["stages"] if s["name"] == "cross")
    cross_calls = [r for r in transports[0].requests if r["stage"].startswith("cross")]
    assert cross["status"] == "ok" and cross["calls"] == len(cross_calls) == 2
    f = next(x for x in rep["findings"] if x["kind"] == "conflict" and "Расчётный месяц кэшбэка" in x["title"])
    assert f["anchor_status"] == "supported" and f["severity"] == "critical" and f["blocked_decision"]
    assert (f["witness"]["evidence_a"]["quote"], f["witness"]["evidence_b"]["quote"]) == (SENT_A, SENT_B)
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    assert (blocks[f["witness"]["evidence_a"]["block_id"]]["loc"]["line_start"],
            blocks[f["witness"]["evidence_b"]["block_id"]]["loc"]["line_start"]) == (7, 10)
