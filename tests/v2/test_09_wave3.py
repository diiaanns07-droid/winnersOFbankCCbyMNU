"""№09, волна 3: явное правило документа снимает противоречие; разные системы — не одно понятие (без сети)."""
from __future__ import annotations

from bcc_review.v2.stages import consistency as C

DOC = [
    "# Перевод",                                                                          # 1
    "* **П-1.** Перевод по коду можно оплатить один раз.",                                # 2
    "6. Проверить, что код ещё не оплачен; если оплачен, вернуть 410.",                   # 3
    "2. Повторный запрос с тем же requestId возвращает результат первого запроса.",       # 4
    "Повторная блокировка карты в статусе BLOCKED возвращает 200 без изменений.",        # 5
    "409 | Блокировка не из ACTIVE",                                                     # 6
    "* **П-2.** Выбор действует с первого дня следующего месяца.",                        # 7
    "| Категория «Такси», кэшбэк 0 ₸ | Провести покупку на 2 000 ₸ | Кэшбэк месяца 100 ₸ |",  # 8
    "| Покупка 31 января в 23:58 | Провести 1 февраля в 00:03 | Февральский счётчик вырос |",  # 9
    "| Долг 120 000 ₸ | Внести 120 000 ₸ | Льготный период сохранён |",                   # 10
    "amount | integer | Сумма в тиынах",                                                  # 11
    "5. Если в коде задана сумма, использовать её, а поле amount запроса не учитывать.",  # 12
    '{"status":"DONE","amount":5000}',                                                   # 13
    "Банк пополняет счёт, приложение показывает итог, сервис отправляет push.",          # 14
    "Клиент открывает счёт, держатель счёта пополняет его.",                             # 15
    "Сервис настроек хранит порог, хранилище настроек отдаёт его.",                      # 16
]
VIEW = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(DOC, 1)]}
REQS = [
    {"id": "R-01", "source_id": "П-1", "kind": "functional", "line_start": 2, "line_end": 2},
    {"id": "R-02", "source_id": "", "kind": "api", "line_start": 3, "line_end": 3},
    {"id": "R-03", "source_id": "", "kind": "constraint", "line_start": 4, "line_end": 4},
    {"id": "R-04", "source_id": "", "kind": "api", "line_start": 5, "line_end": 5},
    {"id": "R-05", "source_id": "Статус 409", "kind": "api", "line_start": 6, "line_end": 6},
    {"id": "R-06", "source_id": "П-2", "kind": "functional", "line_start": 7, "line_end": 7},
    {"id": "R-07", "source_id": "Критерии приёмки, строка 1", "kind": "acceptance", "line_start": 8, "line_end": 8},
    {"id": "R-08", "source_id": "Критерии приёмки, строка 2", "kind": "acceptance", "line_start": 9, "line_end": 9},
    {"id": "R-09", "source_id": "Критерии приёмки, строка 3", "kind": "acceptance", "line_start": 10, "line_end": 10},
    {"id": "R-10", "source_id": "", "kind": "api", "line_start": 11, "line_end": 13},
]


def pair(**kw):
    base = {"a": "R-03", "b": "R-02", "subject": "повтор оплаченного запроса", "same_subject": True,
            "quote_a": DOC[3][3:], "line_a": 4, "quote_b": DOC[2][3:], "line_b": 3,
            "scenario": "Код оплачен первым запросом, тот же запрос приходит повторно.", "one_condition": True,
            "outcome_a": "вернуть результат первого запроса: 200 DONE", "outcome_b": "вернуть 410",
            "verdict": "conflict", "basis": "same_condition", "kind": "status_conflict", "title": "", "impact": "",
            "recommendation": "", "question": ""}
    base.update(kw)
    return base


def answer(**kw):
    base = {"subjects": [], "pair_checks": [], "glossary": [], "trace": [], "candidates": []}
    base.update(kw)
    return base


def run(*pairs, glossary=()):
    return C.postprocess(answer(pair_checks=list(pairs), glossary=list(glossary)), VIEW, REQS)


def test_idempotent_replay_rule_resolves_conflict_with_check_step():
    out = run(pair())
    assert out["pair_checks"][0]["verdict"] == "compatible"
    assert out["pair_checks"][0]["resolved_by"] == "replay"
    assert out["candidates"] == []
    out = run(pair(verdict="undefined", basis="none"))
    assert out["candidates"] == []


def test_repeat_rule_against_status_row_about_same_repeat_stays_conflict():
    # «Повторная блокировка → 200» против «409 — блокировка не из ACTIVE»: один вход, результата первого запроса
    # правило не возвращает — это настоящий конфликт.
    p = pair(a="R-04", b="R-05", quote_a=DOC[4], line_a=5, quote_b=DOC[5], line_b=6,
             outcome_a="200 без изменений", outcome_b="409")
    [c] = run(p)["candidates"]
    assert c["severity"] == "critical" and c["kind"] == "status_conflict"


def test_acceptance_row_without_moment_cannot_conflict_on_moment():
    p = pair(a="R-06", b="R-07", quote_a=DOC[6][10:], line_a=7, quote_b="Провести покупку на 2 000 ₸ | Кэшбэк месяца 100 ₸",
             line_b=8, kind="event_conflict", basis="value_mismatch",
             scenario="10-го клиент выбрал «Такси», 12-го провёл покупку.", outcome_a="кэшбэк 0", outcome_b="кэшбэк 100")
    out = run(p)
    assert out["pair_checks"][0]["verdict"] == "compatible" and out["candidates"] == []
    # строка приёмки с датой и временем — момент в самой строке, конфликт остаётся
    p2 = dict(p, b="R-08", quote_b="Провести 1 февраля в 00:03 | Февральский счётчик вырос", line_b=9)
    [c] = run(p2)["candidates"]
    assert c["severity"] == "critical"


def test_units_of_acceptance_row_are_display_units_not_mismatch():
    p = pair(a="R-09", b="R-10", quote_a="Долг 120 000 ₸", line_a=10, quote_b=DOC[10], line_b=11, kind="unit_mismatch",
             basis="value_mismatch", outcome_a="120 000 ₸", outcome_b="12 000 000 тиынов")
    assert run(p)["candidates"] == []
    # модель назвала ID строки приёмки, а цитата — из описания API: решает строка, а не ID
    p2 = pair(a="R-10", b="R-07", quote_a=DOC[10], line_a=11, quote_b=DOC[12], line_b=13, kind="unit_mismatch",
              basis="value_mismatch", outcome_a="тиыны", outcome_b="тенге")
    assert len(run(p2)["candidates"]) == 1


def test_status_conflict_without_codes_on_both_sides_is_not_conflict():
    p = pair(a="R-10", b="R-10", quote_a=DOC[11][3:], line_a=12, quote_b=DOC[12], line_b=13,
             outcome_a="перевод на 3 000", outcome_b="пример показывает 5 000")
    out = run(p)
    [c] = out["candidates"]
    # №27: второй исход вывела модель, цитаты его не называют — неопределённость, minor
    assert c["severity"] == "minor" and out["pair_checks"][0]["gate"] == "no_value"


def test_different_systems_are_not_major_glossary_but_roles_and_shared_names_are():
    g = lambda *terms: {"concept": "исполнитель", "terms": [{"term": t, "line": n} for t, n in terms],
                        "problem": "Неясно, одно ли это.", "severity": "major"}
    systems = g(("Банк", 14), ("приложение", 14), ("сервис", 14))
    roles = g(("Клиент", 15), ("держатель счёта", 15))
    shared = g(("Сервис настроек", 16), ("хранилище настроек", 16))
    out = run(glossary=[systems, roles, shared])
    sev = {x["terms"][0]["term"]: x["severity"] for x in out["glossary"]}
    assert sev == {"Банк": "minor", "Клиент": "major", "Сервис настроек": "major"}


# ---------------------------------------------------------------- деление этапа на два вызова (опция)

class _FakeLLM:
    def __init__(self, fail_part=None):
        self.calls, self.fail_part = [], fail_part

    def ask(self, stage, system, user, schema, **kw):
        props = set(schema["properties"])
        self.calls.append((user, props))
        if self.fail_part and self.fail_part <= props:
            raise RuntimeError("сбой")
        out = {k: [] for k in props}
        if "pair_checks" in props:
            out["pair_checks"] = [pair(a="R-04", b="R-05", quote_a=DOC[4], line_a=5, quote_b=DOC[5], line_b=6)]
        return out


class _Ctx:
    def __init__(self, llm, split=True):
        self.llm, self.view, self.requirements = llm, VIEW, REQS
        self.options = {C.SPLIT_OPTION: split}
        self.warnings = []

    def warn(self, msg):
        self.warnings.append(msg)

    def prompt(self, name):
        task = (ROOT_PROMPT.read_text(encoding="utf-8"))
        return "система", "<документ>…</документ>\n\n" + task


from pathlib import Path  # noqa: E402

ROOT_PROMPT = Path(__file__).resolve().parents[2] / "src" / "bcc_review" / "v2" / "prompts" / "consistency.md"


def test_split_mode_two_calls_each_with_own_steps_and_merged_output():
    llm = _FakeLLM()
    out = C.run(_Ctx(llm))
    assert len(llm.calls) == 2
    by_props = {frozenset(p): u for u, p in llm.calls}
    a = by_props[frozenset(C.PART_A)]
    b = by_props[frozenset(C.PART_B)]
    assert "### Шаг 2б" in a and "### Шаг 3" not in a and "### Шаг 5" not in a
    assert "### Шаг 3" in b and "### Шаг 5" in b and "### Шаг 2." not in b
    assert a.startswith("<документ>") and b.startswith("<документ>")  # общий вход — тот же префикс
    assert [c["kind"] for c in out["candidates"]] == ["status_conflict"]
    assert out["trace"]  # трассировка достроена кодом и при пустом ответе части Б


def test_split_mode_one_part_fails_other_is_kept_with_warning():
    ctx = _Ctx(_FakeLLM(fail_part=set(C.PART_B)))
    out = C.run(ctx)
    assert len(out["candidates"]) == 1 and ctx.warnings


def test_single_call_by_default():
    llm = _FakeLLM()
    C.run(_Ctx(llm, split=False))
    assert len(llm.calls) == 1 and set(C.SCHEMA["properties"]) == llm.calls[0][1]


def test_period_mismatch_with_acceptance_row_stays_conflict():
    # «за один час» в правиле и «за текущие сутки» в строке приёмки — разные периоды одного лимита, не единица показа
    doc = ["* **А-5.** За один час выполняется не больше трёх пополнений.",
           "| Три пополнения за текущие сутки | Баланс ниже порога | Пополнение не выполнено |"]
    view = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(doc, 1)]}
    reqs = [{"id": "R-01", "source_id": "А-5", "kind": "functional", "line_start": 1, "line_end": 1},
            {"id": "R-02", "source_id": "Критерии приёмки, строка 1", "kind": "acceptance", "line_start": 2,
             "line_end": 2}]
    p = pair(a="R-01", b="R-02", quote_a=doc[0][10:], line_a=1, quote_b="Три пополнения за текущие сутки", line_b=2,
             kind="unit_mismatch", basis="value_mismatch", outcome_a="четвёртое в сутки разрешено",
             outcome_b="четвёртое в сутки отклонено")
    out = C.postprocess(answer(pair_checks=[p]), view, reqs)
    assert out["pair_checks"][0]["verdict"] == "conflict" and len(out["candidates"]) == 1


def test_silence_with_two_conditions_is_incompleteness_not_check_order():
    # «шаг логики не проверяет условие правила» — неполнота, даже если модель сказала «два условия»; №27: minor
    p = pair(a="R-01", b="R-02", quote_a=DOC[1][10:], line_a=2, quote_b=DOC[2][3:], line_b=3, verdict="undefined",
             basis="none", kind="incomplete", one_condition=False, outcome_a="второй раз — отказ",
             outcome_b="код не назван")
    [c] = run(p)["candidates"]
    assert c["severity"] == "minor" and c["kind"] == "incomplete"
    p2 = dict(p, kind="ambiguity")
    [c2] = run(p2)["candidates"]
    assert c2["severity"] == "minor" and "Порядок проверок" in c2["problem"]


def test_tiyn_with_decimals_against_tenge_row_stays_conflict():
    # «в тиынах с двумя знаками после точки» — тиыны целые, единица действительно перепутана
    p = pair(a="R-09", b="R-10", quote_a="Долг 120 000 ₸", line_a=10, quote_b="Сумма в тиынах", line_b=11,
             kind="unit_mismatch", basis="value_mismatch", outcome_a="120 000 ₸", outcome_b="12 000 000 тиынов")
    assert run(p)["candidates"] == []
    p2 = dict(p, quote_b="Сумма в тиынах с двумя знаками после точки")
    doc_line = VIEW["lines"][10]
    old = doc_line["text"]
    doc_line["text"] = "amount | integer | Сумма в тиынах с двумя знаками после точки"
    try:
        assert len(run(p2)["candidates"]) == 1
    finally:
        doc_line["text"] = old


def test_degenerate_answer_gives_warning():
    class LLM:
        def ask(self, *a, **kw):
            return {"subjects": [], "pair_checks": [], "glossary": [], "trace": [], "candidates": []}
    reqs = REQS + [{"id": f"R-9{i}", "source_id": "", "kind": "functional", "line_start": 2, "line_end": 2}
                   for i in range(3)]
    ctx = _Ctx(LLM(), split=False)
    ctx.requirements = reqs
    C.run(ctx)
    assert any("неполный" in w for w in ctx.warnings)


def test_texts_pass_clarity_rubric_title_and_fix():
    # заголовок пары ≤ 12 слов, у неопределённости — вопрос; у глоссария — вопрос с вариантами
    p = pair(a="R-01", b="R-02", quote_a=DOC[1][10:], line_a=2, quote_b=DOC[2][3:], line_b=3, verdict="undefined",
             basis="none", kind="incomplete", one_condition=True, outcome_a="второй раз — отказ",
             outcome_b="код не назван", title="", question="",
             subject="повторная оплата кода, который уже оплачен первым переводом, и код ответа для такого случая",
             recommendation="Добавить правило: повторная оплата возвращает 410 или результат первого перевода.")
    [c] = run(p)["candidates"]
    assert len(c["title"].split()) <= 12
    assert c["question"] == "Повторная оплата возвращает 410 или результат первого перевода?"
    g = {"concept": "участник", "terms": [{"term": "Клиент", "line": 15}, {"term": "держатель счёта", "line": 15}],
         "problem": "Неясно, одно ли это лицо.", "severity": "major"}
    [gc] = run(glossary=[g])["candidates"]
    assert "одно лицо или разные" in gc["question"] and gc["title"].startswith("Разные названия участника")
    g2 = {"concept": "компонент", "terms": [{"term": "Сервис настроек", "line": 16},
                                            {"term": "хранилище настроек", "line": 16}],
          "problem": "Неясно, один ли это компонент.", "severity": "major"}
    [gc2] = run(glossary=[g2])["candidates"]
    assert gc2["question"].startswith("Какое название оставить") and "компонента" in gc2["title"]
