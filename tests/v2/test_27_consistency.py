"""№27: проверка конфликта кодом и серьёзность этапа набора (без сети).

Конфликт — две цитаты из разных нормативных мест про один предмет с несовместимым исходом на одном входе
(`consistency.conflict_gate`); иначе пара снимается (разные предметы, условие права) или становится
неопределённостью (minor). Неопределённость и мнение модели без проверки кодом — minor.

Синтетические случаи повторяют ложные конфликты слабой модели на чистых ТЗ (замер h0, haiku), у каждого —
контрольный настоящий конфликт. Записанные ответы — `tests/v2/fixtures/27_runs/` (`bench.py`).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bcc_review.v2.stages import consistency as C

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).resolve().parent / "fixtures" / "27_runs"

DOC = [
    "# Услуга",                                                                                    # 1
    "* **У-1.** Клиент может отказаться от услуги в течение 14 календарных дней с даты подключения.",  # 2
    "| 3. Отказ | POST /refusal | 409 — прошло больше 14 дней или отказ уже оформлен |",             # 3
    "Ответ 200: `{\"refund\":3600,\"refundUntil\":\"2026-03-19\"}`.",                              # 4
    "* **У-2.** Подключение 1 марта — отказ возможен по 15 марта включительно.",                   # 5
    "Операция (хранится 5 лет): идентификатор, ключ идемпотентности, сумма.",                      # 6
    "Ключ идемпотентности действует 30 дней.",                                                     # 7
    "Требования проверены по чек-листу; граничные значения 9 999 / 10 000 ₸.",                     # 8
    "* **У-3.** Сумма — от 10 000 ₸ до «остаток − 10 000 ₸» включительно.",                        # 9
    "* **У-4.** Ссылка действует 15 минут с момента выдачи.",                                      # 10
    "| Ссылка выдана в 12:00 | Скачать в 12:14 и в 12:15 | В 12:14 — файл; в 12:15 — ответ 410 |",  # 11
    "Экран: таймер на срок котировки (У-5), запускаемый при получении ответа.",                    # 12
    "* **У-5.** Котировка действует 60 секунд от времени получения запроса.",                      # 13
    "3. Если выписка не сформирована, возвращаются сведения по предыдущему периоду.",              # 14
    "| daysLeft | integer | ≥ 0 | Дней до окончания периода |",                                    # 15
    "При ответе 422 операция получает статус REJECTED.",                                           # 16
    "Если статус «проведена» — ответ 200 с результатом этой операции.",                            # 17
    "Если лимит вне диапазона, метод возвращает 200 и тело `{\"result\":\"ERROR\"}`.",             # 18
    "| 400 | Лимит вне диапазона | `{\"message\":\"Проверьте лимит\"}` |",                         # 19
    "* **У-6.** Сумма бонуса за месяц меньше 10 000 ₸.",                                           # 20
    "| Бонус месяца 9 900 ₸ | Покупка на 4 000 ₸ | Бонус месяца 10 000 ₸ |",                        # 21
    "* **У-7.** Вклад можно пополнять не более трёх раз в квартал.",                               # 22
    "* **У-8.** Пополнение через кассу доступно всегда, независимо от числа пополнений.",          # 23
    "Цель: клиент узнаёт о списании в момент покупки.",                                            # 24
    "Цель: клиенту удобно управлять услугой.",                                                     # 25
    "Отправитель: экран подтверждения с именем получателя, суммой и картой списания.",             # 26
    "* **У-9.** Ссылка действует 15 минут включительно.",                                          # 27
    "Экран: кнопка «Подтвердить» доступна 90 секунд после получения ответа.",                      # 28
    "* **У-10.** При выключении настройки сохраняются и показываются при повторном включении.",    # 29
    "2. При `enabled` = false поля `step` и `limit` не проверяются и не сохраняются; ответ содержит ранее сохранённые значения.",  # 30
    "* **У-11.** Если сумма погашена до конца периода, проценты по покупкам не начисляются, иначе проценты начисляются.",  # 31
    "| Сумма погашена 20-го | Закрыть период 25-го | Проценты за покупки начислены |",            # 32
    "Приложение получает сведения и включает или выключает напоминание через дочерний документ.",  # 33
    "Приложение → API: подключить услугу; подписание договора → выдача кредита → выпуск полиса.",  # 34
    "* **У-12.** После выполненного обмена клиент получает одно уведомление.",                      # 35
    "Сервис повторяет отправку уведомления три раза, после чего уведомление не отправляется.",      # 36
    "2. Счёт не найден среди счетов клиента — 404 `ACCOUNT_NOT_FOUND`.",                           # 37
    "| 404 | Метод 1: котировка не найдена | `{\"errorCode\":\"QUOTE_NOT_FOUND\"}` |",             # 38
    "Пока экран заказа открыт, приложение запрашивает статус каждые 5 секунд.",                    # 39
    "Приложение → сервис: статус заказа (метод 3) каждые 5 секунд, пока IN_PROGRESS.",             # 40
    "При кодах 400, 404 и 422 погашение по этому запросу не проведено.",                           # 41
    "Повтор с тем же ключом: если операция проведена — 200 с результатом этой операции.",          # 42
    "| 404 | Карта не найдена | `{\"errorCode\":\"CARD_NOT_FOUND\"}` |",                           # 43
    "Если карта не найдена, метод возвращает 200 и `{\"errorCode\":\"CARD_NOT_FOUND\"}`.",         # 44
    "Приложение запрашивает статус каждые 10 секунд.",                                             # 45
    "| Authorization | Bearer, сессия клиента — держателя карты |",                                 # 46
]
SECTIONS = {8: "Требования к тестированию › Тестирование требований", 11: "Критерии приемки"}
VIEW = {"lines": [{"n": i, "text": t, "page": None, "section": SECTIONS.get(i, "Требования")}
                  for i, t in enumerate(DOC, 1)]}
KINDS = {2: "functional", 3: "api", 4: "api", 5: "functional", 6: "data", 7: "constraint", 8: "functional",
         9: "functional", 10: "functional", 11: "acceptance", 12: "ui", 13: "functional", 14: "constraint", 15: "api",
         16: "constraint", 17: "constraint", 18: "api", 19: "api", 20: "functional", 21: "acceptance",
         22: "functional", 23: "functional", 24: "goal", 25: "goal", 26: "ui", 27: "functional", 28: "ui",
         29: "functional", 30: "api", 31: "functional", 32: "acceptance", 33: "integration", 34: "process",
         35: "functional", 36: "integration", 37: "api", 38: "api", 39: "ui", 40: "architecture", 41: "api",
         42: "constraint", 43: "api", 44: "api", 45: "functional", 46: "api"}
REQS = [{"id": f"R-{n:02d}", "source_id": "", "kind": k, "line_start": n, "line_end": n,
         "section": SECTIONS.get(n, "Требования")} for n, k in KINDS.items()]


def pair(la: int, lb: int, kind: str = "event_conflict", basis: str = "value_mismatch", qa: str = "", qb: str = "",
         **kw) -> dict:
    p = {"a": f"R-{la:02d}", "b": f"R-{lb:02d}", "subject": "предмет", "same_subject": True,
         "quote_a": qa or DOC[la - 1].lstrip("* "), "line_a": la, "quote_b": qb or DOC[lb - 1].lstrip("* "),
         "line_b": lb, "scenario": "сценарий", "one_condition": True, "outcome_a": "исход A", "outcome_b": "исход B",
         "verdict": "conflict", "basis": basis, "kind": kind, "title": "", "impact": "", "recommendation": "",
         "question": ""}
    p.update(kw)
    return p


def run(*pairs, candidates=()) -> dict:
    data = {"subjects": [], "pair_checks": list(pairs), "glossary": [], "trace": [], "candidates": list(candidates)}
    return C.postprocess(data, VIEW, REQS)


def one(p: dict) -> tuple[dict, list[dict]]:
    out = run(p)
    return out["pair_checks"][0], out["candidates"]


# ---------------------------------------------------------------- проверка конфликта кодом

@pytest.mark.parametrize("p, gate, verdict", [
    # пример ответа с другим входом против правила
    (pair(5, 4, qa="Подключение 1 марта — отказ возможен по 15 марта включительно", qb='"refundUntil":"2026-03-19"'),
     "example_value", "undefined"),
    # условие права против ошибки для другого состояния
    (pair(2, 3, kind="event_conflict", basis="same_condition"), "right_condition", "compatible"),
    # хранение записи и срок действия ключа
    (pair(6, 7, qa="Операция (хранится 5 лет): идентификатор, ключ идемпотентности"), "storage_vs_validity",
     "compatible"),
    # методика тестирования документа — не правило системы
    (pair(9, 8, kind="boundary_conflict", qb="граничные значения 9 999 / 10 000 ₸"), "non_normative", "compatible"),
    # строка приёмки задаёт конец срока «действует 15 минут»
    (pair(10, 11, kind="boundary_conflict"), "acceptance_duration", "compatible"),
    # таймер экрана против правила сервера
    (pair(12, 13, qa="таймер на срок котировки (У-5), запускаемый при получении ответа"), "ui_display", "undefined"),
    # «граница» без значения у одной стороны
    (pair(14, 15, kind="boundary_conflict"), "no_value", "undefined"),
    # следствие ответа другой системы против ответа на запрос
    (pair(16, 17, kind="status_conflict", basis="same_condition"), "two_phase", "undefined"),
    # две цитаты из одной строки — не два места
    (pair(22, 22, qa="Вклад можно пополнять", qb="не более трёх раз в квартал"), "same_place", "undefined"),
    # отрицание о другом объекте: поля запроса не сохраняются, сохранённые настройки остаются
    (pair(29, 30, basis="same_condition", qb="При enabled = false поля step и limit не проверяются и не сохраняются"),
     "other_object", "compatible"),
    # условие цитаты — в предыдущей фразе (исчерпанные попытки), а не вход другой стороны
    (pair(35, 36, qb="после чего уведомление не отправляется"), "condition_elsewhere", "undefined"),
    # коды ошибок про разные объекты
    (pair(37, 38, kind="status_conflict", basis="same_condition", qa="404 ACCOUNT_NOT_FOUND",
          qb='"errorCode":"QUOTE_NOT_FOUND"'), "different_condition", "compatible"),
    # одно и то же действие с теми же значениями при разных условиях
    (pair(39, 40, basis="same_condition", qb="статус заказа (метод 3) каждые 5 секунд, пока IN_PROGRESS"),
     "same_outcome", "compatible"),
    # список кодов — условие («при кодах 400, 404 и 422 …»), а не исход
    (pair(41, 42, kind="status_conflict", basis="same_condition",
          qb="если операция проведена — 200 с результатом этой операции"), "two_phase", "undefined"),
])
def test_false_conflicts_of_clean_documents_are_not_critical(p, gate, verdict):
    pc, cands = one(p)
    assert (pc.get("gate"), pc["verdict"]) == (gate, verdict)
    assert all(c["severity"] == "minor" for c in cands)
    assert gate in C.GATE_RU and C.GATE_RU[gate]


@pytest.mark.parametrize("p, kind", [
    (pair(18, 19, kind="status_conflict", basis="same_condition"), "status_conflict"),       # 200 + ERROR ↔ 400
    (pair(20, 21, kind="boundary_conflict"), "boundary_conflict"),                           # «меньше» ↔ строка
    (pair(22, 23, basis="limit_removed"), "event_conflict"),                                  # предел ↔ «всегда»
    (pair(22, 23, basis="same_condition"), "event_conflict"),                                 # право с пределом
    (pair(27, 11, kind="boundary_conflict"), "boundary_conflict"),                            # «включительно»
    (pair(28, 13), "event_conflict"),                                                         # экран со своим числом
    (pair(31, 32, qa="проценты по покупкам не начисляются"), "event_conflict"),                 # общий предмет
    (pair(43, 44, kind="status_conflict", basis="same_condition",                             # тот же объект кода
          qa="404 | Карта не найдена", qb="Если карта не найдена, метод возвращает 200"), "status_conflict"),
    (pair(39, 45), "event_conflict"),                                                         # 5 и 10 секунд
])
def test_real_conflicts_stay_critical(p, kind):
    pc, cands = one(p)
    assert pc["verdict"] == "conflict" and not pc.get("gate")
    assert [(c["severity"], c["kind"]) for c in cands] == [("critical", kind)]


def test_status_conflict_needs_code_or_status_on_both_sides():
    pc, cands = one(pair(14, 19, kind="status_conflict", basis="same_condition"))
    assert pc["gate"] == "no_value" and [c["severity"] for c in cands] == ["minor"]


def test_undefined_pair_is_minor():
    _, cands = one(pair(22, 13, verdict="undefined", basis="none", kind="incomplete"))
    assert [c["severity"] for c in cands] == ["minor"]


# ---------------------------------------------------------------- кандидаты модели

def cand(lines: list[int], kind: str = "incomplete", severity: str = "major", quotes: list[str] | None = None) -> dict:
    return {"title": "Дефект набора", "kind": kind, "criterion": "set_complete", "severity": severity,
            "requirement_ids": [], "problem": "п", "scenario": "с", "impact": "и", "recommendation": "р",
            "rewrite": "", "question": "", "blocks": "development",
            "evidence": [{"quote": q, "line": n} for q, n in zip(quotes or [DOC[n - 1] for n in lines], lines)]}


@pytest.mark.parametrize("c, severity", [
    (cand([22, 23]), "minor"),                                         # полнота набора — мнение модели
    (cand([22], kind="duplicate"), "minor"),                           # дубль правила
    (cand([12, 13], kind="contradiction"), "minor"),                   # расхождение схем
    (cand([25, 13], kind="contradiction"), "minor"),                   # цель без момента
    (cand([24, 13], kind="contradiction"), "major"),                   # цель «в момент» против срока
    (cand([24, 13], kind="contradiction", severity="critical"), "major"),  # critical — только обещанное
    (cand([26], kind="missing_element"), "minor"),                     # «получатель» — не обещание действия
    # обещание стоит в строке, но не в цитате (другой шаг процесса)
    (cand([34], kind="missing_element", quotes=["подписание договора → выдача кредита → выпуск полиса"]), "minor"),
    # второй глагол фразы — в цитате: «получает … и включает или выключает …»
    (cand([33], kind="missing_element", severity="critical",
          quotes=["включает или выключает напоминание через дочерний документ"]), "critical"),
])
def test_model_candidates_keep_major_only_when_checked(c, severity):
    out = run(candidates=[c])
    assert [x["severity"] for x in out["candidates"]] == [severity]


def test_glossary_other_person_and_qualified_name_are_not_major():
    def g(*terms):
        return {"concept": "участник", "terms": [{"term": t, "line": n} for t, n in terms],
                "problem": "Неясно, одно ли это.", "severity": "major"}
    doc = ["Bearer, сессия клиента — держателя карты.", "Карта принадлежит другому клиенту — 404.",
           "Страховая компания-партнёр рассчитывает премию.", "Страховая компания не ответила — 502.",
           "Владелец карты настраивает услугу."]
    view = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(doc, 1)]}
    view_eq = {"lines": [{"n": 1, "text": DOC[45], "page": None, "section": ""},
                         {"n": 2, "text": "Клиент настраивает услугу.", "page": None, "section": ""}]}
    out = C.postprocess({"glossary": [g(("клиента", 1), ("держателя карты", 1))]}, view_eq, [])
    assert [x["severity"] for x in out["glossary"]] == ["none"]  # документ приравнивает через тире
    data = {"glossary": [g(("держателя карты", 1), ("другому клиенту", 2)),
                         g(("Страховая компания-партнёр", 3), ("Страховая компания", 4)),
                         g(("держателя карты", 1), ("Владелец карты", 5))]}
    out = C.postprocess(data, view, [])
    assert [x["severity"] for x in out["glossary"]] == ["minor", "major"]  # «другой клиент» — не название
    assert [c["severity"] for c in out["candidates"] if c["kind"] == "terminology"] == ["major", "minor"]


def test_agent_nouns_are_not_promise_verbs():
    assert not C._PROMISE_SUBJ.search("экран подтверждения с именем получателя и картой")
    assert not C._PROMISE_SUBJ.search("клиент-отправитель и хранилище")
    assert C._PROMISE_SUBJ.search("Приложение получает номер договора")
    assert C._PROMISE_SUBJ.search("экран показывает сумму")


# ---------------------------------------------------------------- записанные ответы haiku (без сети)

def _bench():
    spec = importlib.util.spec_from_file_location("bench27", Path(__file__).parent / "fixtures" / "27_tools" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _repost(label: str) -> list[dict]:
    from bcc_review.v2.pipeline import load_view
    out = []
    for p in sorted((RUNS / label).glob("*.json")):
        res = json.loads(p.read_text(encoding="utf-8"))
        res["output"] = C.postprocess(res["raw"], load_view(ROOT / res["doc"]), res["requirements"])
        out.append(res)
    return out


@pytest.mark.parametrize("label", ["h0", "h2", "h3"])
def test_clean_documents_give_no_critical_and_at_most_one_major(label):
    """20 чистых ТЗ (корпус, open2, №20), два прогона haiku: h0 было critical 8, major 58 (17 документов с
    major > 1); h2 (свежие ответы после правок) — проверка, что правила держатся на новых ответах."""
    if not (RUNS / label).exists():
        pytest.skip(f"нет записанных ответов {label}")
    rows = _repost(label)
    assert len(rows) == 20
    for res in rows:
        sev = [c["severity"] for c in res["output"]["candidates"]]
        assert sev.count("critical") == 0, res["case"]
        assert sev.count("major") <= 1, res["case"]


@pytest.mark.skipif(not (RUNS / "c0").exists(), reason="нет записанных ответов c0")
def test_seeded_conflicts_of_corpus_are_kept_as_critical():
    """Мутанты корпуса с заложенным противоречием (ответы haiku c0): найдено столько же, сколько старым кодом."""
    bench = _bench()
    labels = bench.SB.corpus_labels()
    found, crit = 0, 0
    for res in _repost("c0"):
        if res["case"].startswith("open2.") or res["case"] == "official":
            continue
        row = bench.SB.score_file(res, labels)
        for t in row["found"]:
            if t.rstrip("!") in bench.CONF_TYPES:
                found += 1
                crit += t.endswith("!")
    assert found >= 21
    assert crit >= 14  # event, boundary и status — critical; unit_mismatch — major по шкале этапа


def test_official_recorded_answers_keep_k():
    """22 записанных ответа по официальному ТЗ (фикстуры №09): К найдено 95, критичными 82 — как до №27."""
    bench = _bench()
    from bcc_review.v2.pipeline import load_view
    view = load_view(bench.OFFICIAL)
    k = kcr = 0
    for _name, raw, reqs in bench.official_recorded():
        row = bench.SB.score_file({"case": "official", "seconds": 0, "error": "",
                                   "output": C.postprocess(raw, view, reqs)}, {})
        k += int(row["k"].split("/")[0])
        kcr += int(row["k"].split("cr ")[1].rstrip(")"))
    assert (k, kcr) >= (95, 82)


# ---------------------------------------------------------------- ответ не по схеме (повтор из кэша, mock)

@pytest.mark.parametrize("data", [
    None, [], "текст",
    {"pair_checks": ["x", None, 3], "glossary": ["g"], "candidates": ["y"], "trace": ["z"], "subjects": ["s"]},
    {"glossary": [{"concept": "к", "terms": ["a", {"term": "Клиент", "line": 2}], "severity": "major"}]},
    {"candidates": [{"title": "t", "kind": "incomplete", "evidence": ["строка", {"quote": "Клиент может", "line": 2}],
                     "requirement_ids": "R-02, R-03"}]},
    {"pair_checks": [{"quote_a": None, "line_a": "abc", "quote_b": 5, "verdict": "conflict", "same_subject": "да"}],
     "trace": [{"requirement_id": None, "verified_by": "R-11"}]},
])
def test_malformed_answer_does_not_crash_stage(data):
    out = C.postprocess(data, VIEW, REQS)
    assert set(out) >= {"candidates", "pair_checks", "trace", "glossary"}
    for c in out["candidates"]:
        assert all(isinstance(x, str) and x.startswith("R-") for x in c["requirement_ids"])


def test_gated_pair_text_says_why_it_is_not_two_outcomes():
    _, [c] = one(pair(5, 4, qa="Подключение 1 марта — отказ возможен по 15 марта включительно",
                      qb='"refundUntil":"2026-03-19"', subject="последний день отказа"))
    assert "пример" in c["problem"] and "не второй исход" in c["problem"]
    assert c["question"] and len(c["title"].split()) <= C.MAX_TITLE_WORDS
    assert set(C.GATE_TEXT) <= set(C.GATE_RU)
