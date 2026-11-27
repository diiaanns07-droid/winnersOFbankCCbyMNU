"""№51: critical по основанию (а) — только если один приёмочный тест получает два ожидаемых результата.

Правило живёт в промптах судьи и второй проверки; код только понижает по ответу проверки. Фикстуры свои:
вымышленная библиотека абонементов, без слов официального ТЗ."""
from __future__ import annotations

from tests.v2.test_10_judge import SRC, FakeLLM, Ctx, cand, finding, response  # noqa: F401
from bcc_review.v2.stages import judge

PROMPTS = SRC / "bcc_review" / "v2" / "prompts"

DOC = [
    "Абонемент читателя",                                                                   # 1
    "Ф-1. При закрытии абонемента выбранные книги сохраняются и показываются при открытии.",  # 2
    "Правило 2. При closed = true поле books не проверяется и не сохраняется; ответ — прежний список.",  # 3
    "Ф-2. Фоновая сверка раз в час: заказ «не найден» → статус CANCELLED.",                   # 4
    "Приёмка: читатель нажал «Повторить» по заказу «не найден» — заказ создаётся заново.",     # 5
    "Ф-3. Бронь действует 3 дня.",                                                             # 6
    "Приёмка: бронь от 1 марта действует 5 марта — книга выдаётся.",                           # 7
]


def view():
    return {"title": "abon", "file": "abon.md", "format": "md",
            "lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(DOC, 1)]}


def ctx(llm):
    return Ctx(llm, view=view(), requirements=[], options={})


def test_prompts_carry_one_test_rule():
    check = (PROMPTS / "judge_check.md").read_text(encoding="utf-8")
    main = (PROMPTS / "judge.md").read_text(encoding="utf-8")
    for text in (check, main):
        assert "одного теста" in text or "одним тестом" in text
        assert "разных запускающих событиях" in text or "разные запускающие события" in text
        assert "прочтение, при котором" in text


def test_rule_reaches_second_check_call():
    cs = [cand("C-001", 6, "Бронь действует 3 дня", kind="contradiction", criterion="set_consistent",
               severity="critical", reqs=(), extra=[(7, "бронь от 1 марта действует 5 марта — книга выдаётся")])]
    fs = [finding("F01", ["C-001"], severity="critical", kind="contradiction", criterion="set_consistent",
                  scenario="Бронь 1 марта, 5 марта: выдать или нет.", impact="Тест падает.", priority=1)]
    check = {"checks": [{"key": "F01", "basis": "(а) L006 ↔ L007: один тест, два результата",
                         "severity": "critical", "reason": ""}], "verdict_summary": ""}
    llm = FakeLLM(response(fs), check)
    res = judge.run(ctx(llm), cs)
    assert "одного теста" in llm.calls[1]["user"] or "одного теста" in llm.calls[1]["system"]
    assert res["findings"][0]["severity"] == "critical"          # настоящий блокер остаётся
    assert judge.compute_verdict(res["findings"])["testing"] == "no"


def _two_false(check_answers):
    cs = [cand("C-001", 2, "книги сохраняются и показываются при открытии", kind="contradiction",
               criterion="set_consistent", severity="critical", reqs=(),
               extra=[(3, "не проверяется и не сохраняется; ответ — прежний список")]),
          cand("C-002", 4, "заказ «не найден» → статус CANCELLED", kind="status_conflict",
               criterion="set_consistent", severity="critical", reqs=(),
               extra=[(5, "нажал «Повторить» по заказу «не найден» — заказ создаётся заново")])]
    fs = [finding("F01", ["C-001"], severity="critical", kind="contradiction", criterion="set_consistent",
                  scenario="Закрыл с новым списком: что покажут.", impact="Разные реализации.", priority=1),
          finding("F02", ["C-002"], severity="critical", kind="status_conflict", criterion="set_consistent",
                  scenario="Сверка и повтор.", impact="Разный статус.", priority=2)]
    llm = FakeLLM(response(fs), {"checks": check_answers, "verdict_summary": ""})
    return judge.run(ctx(llm), cs)


def test_reconcilable_and_different_trigger_conflicts_lose_block():
    res = _two_false([
        {"key": "F01", "basis": "м1: цитаты допускают прочтение, при котором выполняются обе",
         "severity": "major", "reason": "Новые значения не сохраняются, прежние остаются — Ф-1 выполнено."},
        {"key": "F02", "basis": "м1: разные запускающие события — сверка и действие читателя",
         "severity": "major", "reason": "Фоновая сверка и «Повторить» — два разных теста."}])
    assert {f["severity"] for f in res["findings"]} == {"major"}
    v = judge.compute_verdict(res["findings"])
    assert v["development"] != "no" and v["testing"] != "no"


def test_check_cannot_raise_or_skip_two_steps():
    res = _two_false([
        {"key": "F01", "basis": "м1", "severity": "minor", "reason": "Сразу в minor."},
        {"key": "F02", "basis": "(а)", "severity": "critical", "reason": ""}])
    sev = {f["candidate_ids"][0]: f["severity"] for f in res["findings"]}
    assert sev["C-001"] == "major"      # не больше одной ступени за раз
