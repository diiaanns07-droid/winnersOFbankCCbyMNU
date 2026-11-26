"""Приёмочные сценарии: границы из текста, переход месяца, возврат, дубль, статусы API, решения."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import fixture as fx
from bcc_review.bank import build_bank_pack, collect_questions
from bcc_review.bank.checklist import Doc

SRC = Path(__file__).resolve().parents[2] / "src" / "bcc_review" / "bank"


def run(text: str | None = None, mode: str = "reader", **kw):
    c = fx.case(mode, text)
    findings = kw.pop("findings", c["findings"])
    decisions = kw.pop("decisions", [])
    args = dict(coverage=fx.coverage() if text is None else [], questions=fx.questions(), criteria=fx.CRITERIA, complete=True)
    args.update(kw)
    return c, build_bank_pack(c["document"], c["requirements"], findings, decisions, None, **args)


def by_kind(pack, kind, level=None):
    return [t for t in pack["test_cases"] if t["kind"] == kind and (level is None or t["level"] == level)]


def boundary_values(pack, level):
    return {(t["values"]["boundary"], t["values"]["input"]) for t in pack["test_cases"]
            if t["values"].get("boundary") and t["level"] == level}


def test_case_boundaries_999_1000_1000000_1000001():
    _, pack = run()
    biz = {t["values"]["input"]: t for t in pack["test_cases"] if t["level"] == "business" and t["kind"] == "boundary"}
    assert set(biz) == {999, 1000, 1000000, 1000001, 1000.5}
    assert "отклоняется" in biz[999]["expected"] and "отклоняется" in biz[1000001]["expected"]
    assert "принимается" in biz[1000]["expected"] and "принимается" in biz[1000000]["expected"]
    assert "под полем" in biz[999]["expected"]  # реакция UI взята из текста документа
    assert all("R-01" in t["req_ids"] and t["obligation"]["source_id"] == "Ф-1" for t in biz.values())
    assert biz[999]["obligation"]["quote"] == "Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно."
    api = {t["values"]["input"]: t for t in pack["test_cases"] if t["level"] == "api" and t["values"].get("boundary")}
    assert set(api) == {999, 1000, 1000000, 1000001, 1000.5}
    assert "amount=999" in api[999]["action"] and "HTTP 200" in api[1000]["expected"]
    # Включённость границ у API выведена из «Особых правил», а не из таблицы.
    assert any("обе границы включены" in e["quote"] for e in api[1000]["evidence"])
    for v in (999, 1000001, 1000.5):
        t = api[v]
        assert t["status"] == "open" and t["open_question_id"] == "Q-03"
        assert [o["label"] for o in t["options"]] == ["HTTP 400", "HTTP 200 + ERROR"]
        assert "F-K3" in t["finding_ids"]


def test_changed_range_5_9_moves_boundary_pairs_to_4_5_and_9_10():
    text = fx.replace_all([("от 1 000 до 1 000 000 ₸ включительно", "от 5 до 9 ₸ включительно"), ("| 1 000–1 000 000 |", "| 5–9 |")])
    _, pack = run(text)
    pairs = {(b, v) for b, v in boundary_values(pack, "business") | boundary_values(pack, "api")}
    assert pairs == {("lo-1", 4), ("lo", 5), ("hi", 9), ("hi+1", 10), ("fraction", 5.5)}
    assert {v for _, v in boundary_values(pack, "business")} == {4, 5, 9, 10, 5.5}
    assert {v for _, v in boundary_values(pack, "api")} == {4, 5, 9, 10, 5.5}
    blob = json.dumps(pack["test_cases"], ensure_ascii=False)
    assert "999" not in blob and "1 000 001" not in blob and "1000001" not in blob
    four = next(t for t in pack["test_cases"] if t["level"] == "business" and t["values"].get("input") == 4)
    assert four["title"].startswith("Порог 4 ₸") and "5–9 ₸" in four["precondition"]
    # Критерии приёмки с порогом 50 000 ₸ теперь вне диапазона: это видно в сценарии.
    ac1 = next(t for t in pack["test_cases"] if t["key"].endswith("acceptance:1:1"))
    assert any("вне допустимого диапазона 5–9 ₸" in n for n in ac1["notes"])


def test_range_without_inclusivity_keeps_boundaries_open():
    text = fx.replace_all([("от 1 000 до 1 000 000 ₸ включительно", "от 5 до 9 ₸")])
    _, pack = run(text)
    biz = {t["values"]["boundary"]: t for t in pack["test_cases"] if t["level"] == "business" and t["kind"] == "boundary"}
    assert set(biz) == {"lo-1", "lo", "hi", "hi+1", "fraction"}  # «целый» в Ф-1 остался → есть и дробное значение
    assert biz["lo"]["status"] == "open" and biz["hi"]["status"] == "open"
    assert biz["lo"]["open_question_id"] == biz["hi"]["open_question_id"]
    assert biz["lo-1"]["status"] == "draft" and "отклоняется" in biz["lo-1"]["expected"]
    assert biz["lo-1"]["values"]["input"] == 4 and biz["hi+1"]["values"]["input"] == 10


def test_exclusive_bounds_shift_inner_values():
    text = fx.replace_all([("задаёт целый порог от 1 000 до 1 000 000 ₸ включительно", "задаёт порог больше 5 ₸ и меньше 9 ₸")])
    _, pack = run(text)
    biz = {t["values"]["boundary"]: t["values"]["input"] for t in pack["test_cases"] if t["level"] == "business" and t["kind"] == "boundary"}
    assert biz == {"lo": 5, "lo+1": 6, "hi-1": 8, "hi": 9}


def test_dates_and_identifiers_are_not_ranges():
    text = fx.replace_all([("Дать клиенту возможность узнать", "Акция 01-02 марта, релиз 2024-03-01, карта demo-42. Дать клиенту возможность узнать")])
    _, pack = run(text)
    assert all(t["values"].get("input") not in (1, 2, 3, 42) for t in pack["test_cases"] if t["kind"] == "boundary")


def test_ambiguous_settlement_month_open_then_agreed_with_reference():
    _, before = run()
    ac2 = next(t for t in before["test_cases"] if t["key"] == "acceptance:1:2")
    assert ac2["status"] == "open" and ac2["open_question_id"] == "Q-01" and "F-K1" in ac2["finding_ids"]
    a, b = ac2["options"]
    assert "января" in a["expected"] and "4 000 ₸" in a["expected"] and "Ф-2" in a["basis"]
    assert b["expected"] == "Февральский счётчик вырос на 4 000 ₸"
    assert ac2["expected"].startswith("ОТКРЫТО до решения Q-01")
    assert any("не указан часовой пояс" in n for n in ac2["notes"])
    assert "Q-01" in {q["id"] for q in collect_questions(before)}
    _, after = run(decisions=fx.decisions(), previous=before)
    ac2 = next(t for t in after["test_cases"] if t["key"] == "acceptance:1:2")
    assert ac2["status"] == "agreed" and ac2["open_question_id"] is None and ac2["resolved_question_id"] == "Q-01"
    assert ac2["decision_id"] == "answer:Q-01" and ac2["expected"] == a["expected"]
    ch = next(c for c in ac2["changes"] if c["field"] == "expected")
    assert ch["before"].startswith("открыт:") and "по вопросу Q-01" in ch["reason"] and "вариант A" in ch["reason"]
    assert "по дате совершения" in ch["reason"]  # текст ответа владельца сохранён в причине
    assert ac2["gherkin"].endswith(a["expected"])
    # Одно решение по Q-03 закрывает все три сценария недопустимой суммы в API.
    api_rej = [t for t in after["test_cases"] if t.get("resolved_question_id") == "Q-03"]
    assert len(api_rej) == 3 and all("HTTP 400" in t["expected"] and t["decision_id"] == "answer:Q-03" for t in api_rej)


def test_month_boundary_and_timezone_from_text():
    _, pack = run()
    months = {t["key"]: t for t in by_kind(pack, "month")}
    last = months["month:last_minute"]
    assert "31 января в 23:59 по Алматы" in last["action"] and "января" in last["expected"]
    tz = months["month:tz_boundary"]
    assert "31 января 19:00 UTC" in tz["action"] and "февраля" in tz["expected"]
    assert any("UTC+5" in n for n in tz["notes"])
    assert "month:cross_posting" not in months  # этот случай уже задан критерием приёмки 2
    moscow = fx.replace_all([("в Алматы.", "по Москве."), ("по Алматы", "по Москве")])
    _, pack2 = run(moscow, findings=[])
    tz2 = next(t for t in pack2["test_cases"] if t["key"] == "month:tz_boundary")
    assert "21:00 UTC" in tz2["action"]


def test_refund_duplicate_event_and_excluded_operations():
    _, pack = run()
    keys = {t["key"]: t for t in pack["test_cases"]}
    refund = keys["refund:cross_month"]
    assert "расходы января уменьшились" in refund["expected"] and "февраля не изменились" in refund["expected"]
    dup = keys["idempotency:redelivery"]
    assert "повторно" in dup["action"] and "повторный push не отправляется" in dup["expected"]
    assert any("идентификатор операции" in e["quote"] for e in dup["evidence"])
    assert "event:exclude:снятие наличных" in keys
    assert not any(k.startswith("event:exclude:перевод") for k in keys)  # переводы уже покрыты критерием 3
    ac3 = keys["acceptance:1:3"]
    assert ac3["status"] == "draft" and any("push не отправлен" in n for n in ac3["notes"])
    step = keys["trigger:just_below"]
    assert "1 499,99 ₸" in step["action"] and "49 999,99 ₸" in step["expected"]


def test_api_statuses_from_text():
    _, pack = run()
    st = {t["key"]: t for t in by_kind(pack, "api_status")}
    assert "Требуется вход" in st["api:status:401"]["expected"] and "R-11" in st["api:status:401"]["req_ids"]
    assert "Ошибка сервиса" in st["api:status:500"]["expected"]
    missing = next(t for k, t in st.items() if "отсутствующей" in k)
    assert "HTTP 404" in missing["expected"] and "Карта не найдена" in missing["expected"]
    assert any("не входит в перечень статусов" in n for n in missing["notes"])
    foreign = next(t for k, t in st.items() if "чужой" in k)
    assert foreign["status"] == "open" and [o["label"] for o in foreign["options"]] == ["HTTP 403", "HTTP 404"]
    assert "api:status:403" not in st  # 403 разобран как расхождение, а не как отдельный исход
    enum = next(t for t in pack["test_cases"] if t["key"] == "api:enum:enabled")
    assert "enabled=2" in enum["action"] and "HTTP 400" in enum["expected"] and enum["status"] == "draft"
    ok = next(t for t in pack["test_cases"] if t["key"] == "api:success")
    assert "amount=50000" in ok["action"] and "`result` = OK" in ok["expected"]


def test_rule_conflict_cap_vs_override_uses_witness_question():
    _, pack = run()
    t = next(t for t in pack["test_cases"] if t["key"] == "cap:override_conflict")
    assert t["status"] == "open" and t["open_question_id"] == "Q-02" and "F-K2" in t["finding_ids"]
    assert {"R-03", "R-04"} <= set(t["req_ids"])
    assert "push не отправляется" in t["options"][0]["expected"] and "отправлен push" in t["options"][1]["expected"]


def test_witness_without_rule_match_becomes_own_conflict_case():
    c = fx.case()
    doc = c["document"]
    e1 = fx.ev(doc, "Если результат 200 или 201 — успешный.")
    e2 = fx.ev(doc, "Если результат 400, 401 и далее — неуспешный.")
    f = {"id": "F-W", "kind": "conflict", "severity": "major", "status": "confirmed", "title": "201 не описан", "evidence": [e1],
         "witness": {"input": {"precondition": "метод вызван", "action": "создана новая настройка"}, "outcome_a": "HTTP 200",
                     "outcome_b": "HTTP 201", "evidence_a": e1, "evidence_b": e2}}
    pack = build_bank_pack(doc, c["requirements"], [f], [], None, criteria=fx.CRITERIA)
    t = next(t for t in pack["test_cases"] if t["key"] == "witness:F-W")
    assert t["status"] == "open" and t["source"] == "witness" and t["precondition"] == "метод вызван"
    assert [o["expected"] for o in t["options"]] == ["HTTP 200", "HTTP 201"]


def test_coverage_gaps_become_addressed_drafts():
    _, pack = run()
    gaps = [(g["req_id"], g["gap"], t["key"]) for t in pack["test_cases"] for g in t["covers_gaps"]]
    by_gap = {}
    for _rid, gap, key in gaps:
        by_gap.setdefault(gap, set()).add(key)
    boundary = by_gap["граница 999 / 1 000 / 1 000 000 / 1 000 001 ₸"]
    assert len(boundary) == 4 and all(k.startswith("range:") for k in boundary)
    assert any(k.startswith("default:") for k in by_gap["значение по умолчанию: уведомление выключено"])
    assert by_gap["повторная доставка события"] == {"idempotency:redelivery"}
    new = next(t for t in pack["test_cases"] if t["kind"] == "coverage_gap")
    assert new["req_ids"] == ["R-04"] and new["needs_clarification"] and "Ф-4" in new["title"]


def test_llm_scenarios_are_verified_by_code():
    c = fx.case()
    doc = c["document"]
    integ = fx.ev(doc, "Приложение читает и сохраняет настройки")
    descr = fx.ev(doc, "Сохранение порога. Функциональные требования: чтение порога")

    def ask(stage, payload, schema):
        assert stage == "bank#scenarios" and set(payload) == {"task", "input", "context"}
        assert schema["additionalProperties"] is False
        assert "R-07" in {r["id"] for r in payload["input"]["requirements"]}
        assert "R-01" not in {r["id"] for r in payload["input"]["requirements"]}  # уже покрыто правилами
        return {"scenarios": [
            {"req_id": "R-07", "title": "Чтение порога", "precondition": "сохранён порог 77 777 ₸", "action": "открыть экран",
             "expected": "виден порог 77 777 ₸", "hints": [{"block_id": integ["block_id"], "quote": "читает и сохраняет настройки"}]},
            {"req_id": "R-07", "title": "Выдуманная цитата", "precondition": "", "action": "", "expected": "",
             "hints": [{"block_id": integ["block_id"], "quote": "читает настройки из кэша"}]},
            {"req_id": "R-07", "title": "Чтение сохранённого порога", "precondition": "сохранён порог 50 000 ₸",
             "action": "открыть настройки уведомления", "expected": "приложение показывает порог 50 000 ₸",
             "hints": [{"block_id": integ["block_id"], "quote": "читает и сохраняет настройки"}],
             "alternatives": [{"expected": "метода чтения нет: порог не показывается", "hints": [descr]}]},
            {"req_id": "R-01", "title": "Чужое требование", "precondition": "", "action": "", "expected": "", "hints": [integ]},
        ]}

    pack = build_bank_pack(doc, c["requirements"], [], [], ask, criteria=fx.CRITERIA)
    llm = [t for t in pack["test_cases"] if t["source"] == "llm"]
    assert [t["title"] for t in llm] == ["Чтение сохранённого порога"]
    assert llm[0]["status"] == "open" and len(llm[0]["options"]) == 2 and llm[0]["req_ids"][0] == "R-07"
    msgs = [w["message"] for w in pack["warnings"] if w["code"] == "bank.llm_rejected"]
    assert any("числа не выводятся" in m for m in msgs) and any("нет проверяемой цитаты" in m for m in msgs)
    assert any("неизвестное требование" in m for m in msgs)


def test_llm_failure_is_a_warning_not_a_crash():
    c = fx.case()

    def ask(stage, payload, schema):
        raise TimeoutError("503 overloaded")

    pack = build_bank_pack(c["document"], c["requirements"], [], [], ask, criteria=fx.CRITERIA)
    assert pack["test_cases"] and any(w["code"] == "bank.llm_failed" for w in pack["warnings"])


@pytest.mark.parametrize("mode", ["reader", "rows", "table"])
def test_every_test_case_is_grounded_and_valid(mode):
    c, pack = run(mode=mode)
    d = Doc(c["document"])
    ids = [t["id"] for t in pack["test_cases"]]
    assert ids == [f"TC-{i:02d}" for i in range(1, len(ids) + 1)]
    assert len({t["key"] for t in pack["test_cases"]}) == len(ids)
    for t in pack["test_cases"]:
        assert t["evidence"] and all(d.ev_valid(e) for e in t["evidence"]), t["key"]
        assert d.ev_valid(t["obligation"]["evidence"])
        for o in t["options"]:
            assert all(d.ev_valid(e) for e in o.get("evidence", []))
        assert t["gherkin"].startswith("Дано ") and "\nКогда " in t["gherkin"] and "\nТогда" in t["gherkin"]
        assert (t["status"] == "open") == bool(t["open_question_id"])
        assert t["expected"]


@pytest.mark.parametrize("other", ["rows", "table"])
def test_same_input_same_output_across_loader_modes(other):
    _, a = run(mode="reader")
    _, b = run(mode=other)
    strip = lambda p: [(t["key"], t["title"], t["expected"], t["req_ids"]) for t in p["test_cases"]]
    assert strip(a) == strip(b)
    assert [(r["available"], r["checked"]) for r in a["checklist"]] == [(r["available"], r["checked"]) for r in b["checklist"]]


def test_no_case_numbers_hardcoded_in_source():
    """Числа кейса (999, 1 000 000, 50 000, 48 500, 4 000) не зашиты в код модуля."""
    for path in SRC.glob("*.py"):
        code = path.read_text("utf-8")
        for literal in ("999", "1 000 000", "1000000", "1000001", "50 000", "50000", "48 500", "19 900", "4 000", "saveLimit", "demo-42"):
            assert literal not in code, f"{literal!r} в {path.name}"


def test_pack_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parent / "bank_schema.json").read_text("utf-8"))
    _, pack = run(decisions=fx.decisions())
    jsonschema.validate(json.loads(json.dumps(pack, ensure_ascii=False)), schema)
    doc = fx.read_real("# Пусто\n\nНичего нет.\n")
    empty = build_bank_pack(doc, [], [], [], None)
    jsonschema.validate(empty, schema)
    assert empty["checklist"] == [] and empty["test_cases"] == []
    assert {w["code"] for w in empty["warnings"]} >= {"bank.checklist_absent", "bank.no_test_cases"}


@pytest.mark.parametrize("answer,chosen", [("A", "A"), ("вариант B", "B"), ("Б) по критерию", "B"), ("b — так", "B"), ("а", "A"),
                                           ("в феврале (критерий приёмки 2)", "B"), ("в январе", "A"), ("вариант а", "A")])
def test_owner_answer_forms_select_option(answer, chosen):
    c = fx.case()
    dec = [{"question_id": "Q-01", "source_sha256": c["document"]["id"], "answer": answer, "edits": [], "note": ""}]
    pack = build_bank_pack(c["document"], c["requirements"], c["findings"], dec, None, questions=fx.questions(), criteria=fx.CRITERIA)
    ac2 = next(t for t in pack["test_cases"] if t["key"] == "acceptance:1:2")
    assert ac2["status"] == "agreed" and [o["id"] for o in ac2["options"] if o.get("chosen")] == [chosen]
    assert sum(1 for ch in ac2["changes"] if ch["field"] == "expected") == 1
