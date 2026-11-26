"""№06 · четыре вида межраздельных дефектов × (конфликт / два совместимых правила).

Новые предметные области: комиссия за перевод (единицы), возврат покупки (событие), резерв суммы (граница),
дата валютирования (статус). Совместимый документ отличается от конфликтного только тем, что у второго правила
разведены субъект или область применения (`fixtures/pairs4x2/*_compatible.md`).

Путь каждого документа: факты → отбор пары → вид дефекта → две дословные опоры → результат проверки.
Два режима разделены явно:

* **правила** (`ask=None`) — что модуль находит сам, без модели;
* **записанный транспорт** — настоящий Asker движка и кассета `fixtures/pairs4x2/cassette_pairs4x2.json`
  с имитированными ответами: доходит ли ответ модели до модуля (отбор пар) и что модуль с ним делает
  (опоры, предусловия, совместимость). Найдёт ли дефект сама модель, этот тест не измеряет: ответы кассеты
  написаны человеком. Для конфликтов в кассете верный ответ, для совместимых пар — «наивный» конфликт
  с честными предусловиями.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("bcc_review.runtime.asker")

from p06_helpers import FIXTURES, RecordedTransport, evidence_ok, make_asker, read_pipeline  # noqa: E402

from bcc_review import contracts as C  # noqa: E402
from bcc_review.analysis.cross import CrossReview, review_set  # noqa: E402
from bcc_review.analysis.facts import _quantity, extract_facts  # noqa: E402
from bcc_review.runtime.modules import Modules  # noqa: E402

PAIRS = FIXTURES / "pairs4x2"
CASSETTE = json.loads((PAIRS / "cassette_pairs4x2.json").read_text(encoding="utf-8"))
CATEGORIES = ("unit", "event", "boundary", "status")
CASES = [f"{c}_{v}" for c in CATEGORIES for v in ("conflict", "compatible")]

# Две стороны пары в каждом документе: для конфликта — опоры дефекта, для совместимого — «соблазнительная» пара.
SIDES = {
    "unit_conflict": ("не меньше 200 ₸ и не больше 5 000 ₸", "Комиссия за перевод в тиынах"),
    "unit_compatible": ("не меньше 200 ₸ и не больше 5 000 ₸", "Та же комиссия в тиынах"),
    "event_conflict": ("банк зачисляет сумму возврата на карту", "зачисляется на бонусный счёт клиента"),
    "event_compatible": ("банк зачисляет сумму возврата на карту", "Если покупка оплачена бонусами"),
    "boundary_conflict": ("Банк резервирует на карте сумму", "строго меньше 2 000 000 ₸"),
    "boundary_compatible": ("Банк резервирует на карте сумму", "Сумма частичного снятия"),
    "status_conflict": ("раньше текущего операционного дня, вернуть 422", "400 | Дата валютирования раньше"),
    "status_compatible": ("новая дата валютирования раньше", "createPayment: дата валютирования раньше"),
}

# Ожидаемая матрица: вид дефекта по правилам; дошёл ли ответ кассеты до модуля; конфликт после ответа.
EXPECTED = {
    "unit_conflict": {"rules": "unit_mismatch", "delivered": False, "recorded": 1},
    "unit_compatible": {"rules": None, "delivered": False, "recorded": 0},
    "event_conflict": {"rules": None, "delivered": True, "recorded": 1},
    "event_compatible": {"rules": None, "delivered": True, "recorded": 0},
    "boundary_conflict": {"rules": "boundary_conflict", "delivered": True, "recorded": 1},
    "boundary_compatible": {"rules": None, "delivered": False, "recorded": 0},
    "status_conflict": {"rules": None, "delivered": True, "recorded": 1},
    "status_compatible": {"rules": None, "delivered": True, "recorded": 0},
}


def _line(doc: dict, ev: dict) -> int:
    b = next(x for x in doc["blocks"] if x["id"] == ev["block_id"])
    return b["loc"].get("line_start")


def trace(case: str) -> dict:
    """Путь документа в обоих режимах (используется и демо-скриптом)."""
    doc, inv = read_pipeline(PAIRS / f"{case}.md")
    sa, sb = SIDES[case]
    out: dict = {"case": case, "doc": doc}
    cr = CrossReview(doc, inv["requirements"], None, inv["fact_hints"], None, 60, 30)
    blocks = {b["id"]: b["text"] for b in doc["blocks"]}
    side_blocks = [next(b for b, t in blocks.items() if s in t) for s in (sa, sb)]
    out["facts"] = [f for f in cr.fs.facts if (f.evidence or {}).get("block_id") in side_blocks and (f.range or f.unit)]
    units = cr.units()
    ua = [u for u in units if sa in u.text or sa in u.hint["quote"]]
    ub = [u for u in units if sb in u.text or sb in u.hint["quote"]]
    pairs = cr.select_pairs(units)
    hit = [(how, sc) for a, b, sc, how in pairs if (a in ua and b in ub) or (a in ub and b in ua)]
    scores = [cr.link_score(x.keys, y.keys)[0] for x in ua for y in ub]
    out["pair"] = {"selected": bool(hit), "how": hit[0][0] if hit else None,
                   "score": round(hit[0][1] if hit else max(scores or [0.0]), 2),
                   "sent": len(pairs), "considered": cr.stats["pairs_considered"]}
    out["rules"] = review_set(doc, inv["requirements"], None, fact_hints=inv["fact_hints"])
    rec = [r for r in CASSETTE["cross#pairs"] if r["case"] == case]
    transport = RecordedTransport({**CASSETTE, "cross#pairs": rec})
    asker, stats, budget = make_asker(doc, inv["requirements"], transport)
    out["recorded"] = review_set(doc, inv["requirements"], asker, fact_hints=inv["fact_hints"])
    w = rec[0]["when"]
    out["delivered"] = any((w["a"] in p["a"]["text"] and w["b"] in p["b"]["text"]) or
                           (w["b"] in p["a"]["text"] and w["a"] in p["b"]["text"])
                           for r in transport.requests if r["stage"] == "cross#pairs" for p in r["input"]["pairs"])
    out["calls"] = [r["stage"] for r in transport.requests]
    out["sides"] = side_blocks
    return out


def conflicts(res: dict) -> list[dict]:
    return [c for c in res["candidates"] if c["kind"] == "conflict"]


def touches_pair(c: dict, blocks: list[str]) -> bool:
    evs = [e for e in ((c.get("witness") or {}).get("evidence_a"), (c.get("witness") or {}).get("evidence_b")) if e]
    hit = {e["block_id"] for e in evs} | {h["block_id"] for h in c.get("hints", [])}
    return set(blocks) <= hit


@pytest.fixture(scope="module")
def traces() -> dict:
    return {case: trace(case) for case in CASES}


@pytest.mark.parametrize("case", CASES)
def test_matrix_cell(traces, case):
    t, exp = traces[case], EXPECTED[case]
    # режим правил: только детерминированные выводы модуля
    rc = conflicts(t["rules"])
    if exp["rules"]:
        assert len(rc) == 1 and rc[0]["conflict_type"] == exp["rules"], [c["title"] for c in rc]
        assert touches_pair(rc[0], t["sides"])
    else:
        assert rc == [], [c["title"] for c in rc]
    # записанный транспорт: способность модуля обработать ответ, а не способность модели найти дефект
    assert t["delivered"] is exp["delivered"]
    assert t["calls"][-1] == "cross#coverage" and set(t["calls"][:-1]) == {"cross#pairs"}
    lc = conflicts(t["recorded"])
    assert len(lc) == exp["recorded"], [c["title"] for c in lc]
    for c in lc:
        C.validate(c, "Candidate")
        w = c["witness"]
        assert touches_pair(c, t["sides"])
        assert evidence_ok(t["doc"], w["evidence_a"]) and evidence_ok(t["doc"], w["evidence_b"])
        assert c["checks"]["preconditions"] == "program"
    if case.endswith("_compatible"):
        # ни одного кандидата любого вида на «соблазнительной» паре
        for res in (t["rules"], t["recorded"]):
            assert not [c for c in res["candidates"] if touches_pair(c, t["sides"])]


def test_false_positives_on_four_compatible_pairs_is_zero(traces):
    fp = {mode: sum(len(conflicts(traces[f"{c}_compatible"][mode])) for c in CATEGORIES) for mode in ("rules", "recorded")}
    assert fp == {"rules": 0, "recorded": 0}
    # там, где «наивный» ответ дошёл, модуль отклонил его по предусловиям, а не просто не увидел
    for case in ("event_compatible", "status_compatible"):
        sem = [x for x in traces[case]["recorded"]["comparisons"] if x["aspect"] == "semantic"]
        assert sem and sem[0]["verdict"] == "compatible" and "не пересекаются" in sem[0]["explanation"]


def test_unit_conflict_two_exact_anchors(traces):
    """Две опоры одного настоящего конфликта: правило в тенге и поле ответа в тиынах с теми же числами."""
    t = traces["unit_conflict"]
    c = conflicts(t["rules"])[0]
    w = c["witness"]
    assert (w["evidence_a"]["quote"], _line(t["doc"], w["evidence_a"])) == ("не меньше 200 ₸ и не больше 5 000 ₸", 18)
    assert (w["evidence_b"]["quote"], _line(t["doc"], w["evidence_b"])) == (
        "fee | integer | Да | от 200 до 5 000 включительно | Комиссия за перевод в тиынах", 56)
    assert (w["outcome_a_value"], w["outcome_b_value"]) == ("20\u00a0000 тиын", "200 тиын")
    assert c["cause"]["object"] == "Комиссия за перевод" and c["severity"] == "critical"
    assert [x["aspect"] for x in t["rules"]["comparisons"] if x["verdict"] == "mismatch"] == ["unit"]
    assert Modules().get("resolve_candidate").func(t["doc"], c)["anchor_status"] == "supported"


def test_boundary_conflict_names_quantity_and_boundary(traces):
    t = traces["boundary_conflict"]
    c = conflicts(t["rules"])[0]
    assert c["title"] == "«Сумма резерва»: граница 2 000 000 ₸ включена в одном месте и исключена в другом"
    w = c["witness"]
    assert (_line(t["doc"], w["evidence_a"]), _line(t["doc"], w["evidence_b"])) == (17, 50)
    assert "включительно" in w["evidence_a"]["quote"] and "строго меньше" in w["evidence_b"]["quote"]
    # тот же конфликт пришёл от модели через Asker — подтверждение без дубля
    lc = conflicts(t["recorded"])
    assert len(lc) == 1 and lc[0]["origin"] == "facts" and lc[0].get("confirmed_by") == ["llm"]


@pytest.mark.parametrize("case", ["unit_conflict", "boundary_conflict"])
def test_engine_offline_report_keeps_conflict(tmp_path, case):
    from bcc_review import engine

    src = tmp_path / f"{case}.md"
    src.write_text((PAIRS / f"{case}.md").read_text(encoding="utf-8"), encoding="utf-8")
    rep = engine.run_review(src, tmp_path / "report.md", options=C.RunOptions.coerce(
        {"offline_lint": True, "cache_dir": str(tmp_path / "c"), "artifacts_dir": str(tmp_path / "a")}))
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    f = [x for x in rep["findings"] if x["kind"] == "conflict" and x.get("witness")]
    assert len(f) == 1 and f[0]["anchor_status"] == "supported" and f[0]["status"] == "confirmed"


@pytest.mark.parametrize("prefix,name", [
    ("Порог уведомления задаётся целым числом ", "Порог уведомления"),          # возвратный глагол → подлежащее
    ("Оператор вводит лимит целым числом ", "лимит"),                           # переходный → дополнение
    ("Система блокирует на счёте сумму ", "сумму"),                             # предложная группа — не величина
    ("Плата за выпуск составляет 2 % от суммы, но ", "Плата за выпуск"),        # связка → подлежащее
    ("Срок хранения должен быть ", "Срок хранения"),
    ("Поле term вне диапазона ", "term"),
    ("Т-7. Ставка задаётся ", "Ставка"),
])
def test_quantity_name_of_a_bound(prefix, name):
    assert _quantity(prefix)[0] == name


def test_word_bounds_and_names_on_neutral_text():
    doc = {"id": "x", "title": "t", "warnings": [], "blocks": [
        {"id": "b0001", "kind": "heading", "section": ["Т"], "text": "Т", "loc": {"line_start": 1, "line_end": 1}},
        {"id": "b0002", "kind": "list_item", "section": ["Т", "Функциональные требования"],
         "text": "Плата за выпуск составляет 2 % от суммы, но не меньше 300 ₸ и не больше 9 000 ₸.",
         "loc": {"line_start": 2, "line_end": 2}},
        {"id": "b0003", "kind": "list_item", "section": ["Т", "Функциональные требования"],
         "text": "Срок хранения должен быть больше 1 и строго меньше 7 суток.", "loc": {"line_start": 3, "line_end": 3}},
    ]}
    got = {f.field: f.range for f in extract_facts(doc).facts if f.range}
    assert (got["Плата за выпуск"]["min_minor"], got["Плата за выпуск"]["max_minor"]) == (30000, 900000)
    assert (got["Плата за выпуск"]["min_inclusive"], got["Плата за выпуск"]["max_inclusive"]) == (True, True)
    assert (got["Срок хранения"]["min_inclusive"], got["Срок хранения"]["max_inclusive"]) == (False, False)


CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "dev" / "corpus"


@pytest.mark.skipif(not (CORPUS / "labels.jsonl").exists(), reason="открытого dev-корпуса нет в ветке")
def test_open_corpus_clean_documents_have_no_rule_conflicts():
    """Охрана точности: на чистых базах и перефразах открытого корпуса правила не дают конфликтов.

    Раньше имя текстового факта бралось из слов перед числом («целым числом»), и два разных диапазона
    одного документа сравнивались как одно поле.
    """
    rows = [json.loads(x) for x in (CORPUS / "labels.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    clean = sorted({r["case_id"] for r in rows} - {r["case_id"] for r in rows if r["expected_outcome"] == "present"})
    clean = [c for c in clean if (CORPUS / "cases" / c / "source.md").stat().st_size]
    assert len(clean) >= 8
    for cid in clean:
        doc, inv = read_pipeline(CORPUS / "cases" / cid / "source.md")
        res = review_set(doc, inv["requirements"], None, fact_hints=inv["fact_hints"])
        assert conflicts(res) == [], (cid, [c["title"] for c in conflicts(res)])


def test_cassette_document_inputs_follow_prompt_contract():
    """Входные данные `source: document` в кассете указывают block_id, как требует промпт cross.pairs.

    Без него цитата, встречающаяся в двух строках приёмки, неоднозначна, и верный ответ уходит вопросом:
    так первая версия кассеты дала ложную «потерю» на событии и границе.
    """
    for r in CASSETTE["cross#pairs"]:
        for it in r["answer"]["witness"]["input"]:
            if it["source"] == "document":
                assert re.fullmatch(r"b\d{4}", it["block_id"]), (r["case"], it)
