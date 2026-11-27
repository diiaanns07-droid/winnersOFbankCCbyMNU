"""№12, полнота существенных: опись вопросов полноты у аналитика, судья не сводит разные пожелания и не прячет
параметры спецификации в поля шаблона. Без сети."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "v2")]

from bcc_review.v2.stages import judge, lens_analyst  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, cand, finding, response  # noqa: E402


def test_analyst_schema_asks_for_coverage_before_candidates():
    props = list(lens_analyst.SCHEMA["properties"])
    assert props == ["coverage", "candidates"]
    item = lens_analyst.SCHEMA["properties"]["coverage"]["items"]
    assert set(item["required"]) == {"topic", "line", "question", "answer"}
    text = (ROOT / "src/bcc_review/v2/prompts/lens_analyst.md").read_text(encoding="utf-8")
    for n in range(1, 16):
        assert f"**Т{n}." in text
    assert '{"coverage": [...], "candidates": [...]}' in text


def test_analyst_coverage_is_cleaned_and_capped():
    rows = [{"topic": "Т7", "line": 43, "question": "Какая сумма?", "answer": ""},
            {"topic": "", "line": 1, "question": "без темы", "answer": ""}, "мусор",
            {"topic": "Т1", "line": "x", "question": "q", "answer": "L010: «…»"}]
    out = lens_analyst.coverage(rows * 30)
    assert len(out) == lens_analyst.MAX_COVERAGE
    assert out[0] == {"topic": "Т7", "line": 43, "question": "Какая сумма?", "answer": ""}
    assert out[1]["line"] == 0


def test_analyst_run_keeps_coverage_in_stage_output():
    def fake(ctx, name):
        return {"coverage": [{"topic": "Т10", "line": 29, "question": "Как выбрать объект?", "answer": ""}],
                "candidates": [{"title": "Экран не говорит, как выбрать объект", "kind": "incomplete",
                                "severity": "major", "evidence": [{"quote": "q", "line": 29}], "problem": "p"}]}
    out = lens_analyst.run(type("C", (), {"view": None})(), lens_run=fake)
    assert out["coverage"][0]["topic"] == "Т10" and len(out["candidates"]) == 1


def test_wishes_are_merged_per_place_not_per_document():
    cs = [cand("C-001", 29, "При ошибке ввода сообщение появляется под полем", kind="incomplete", reqs=("R-03",)),
          cand("C-002", 38, "исключаются", kind="incomplete", reqs=("R-06",), source="lens:risk"),
          cand("C-003", 38, "входят", kind="incomplete", reqs=("R-06",)),
          cand("C-004", 40, "при изменении", kind="incomplete", reqs=("R-07",))]
    fs = [dict(finding("F01", ["C-001"], severity="minor", title="Экран: начальное состояние и тексты ошибок"),
               wish=True),
          dict(finding("F02", ["C-002"], severity="minor", title="Перечень исключённых операций открыт"), wish=True),
          dict(finding("F03", ["C-003"], severity="minor", title="Операции в другой валюте не описаны"), wish=True),
          dict(finding("F04", ["C-004"], severity="minor", title="Смена настройки посреди периода"), wish=True)]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_ids = {tuple(f["candidate_ids"]): f for f in res["findings"]}
    assert set(by_ids) == {("C-001",), ("C-002", "C-003"), ("C-004",)}
    assert by_ids[("C-001",)]["title"] == "Экран: начальное состояние и тексты ошибок"
    assert by_ids[("C-002", "C-003")]["title"].startswith("Документ не рассматривает ряд случаев (строка 38")
    assert all(f["severity"] == "minor" for f in res["findings"])


def test_spec_parameters_leave_template_placeholders():
    cs = [cand("C-001", 12, "Версия: —", kind="placeholder", source="rules:placeholder.version"),
          cand("C-002", 15, "Согласующие: —", kind="placeholder", source="rules:placeholder.approvals"),
          cand("C-003", 108, "Prod: —", kind="placeholder", source="rules:placeholder.dash",
               extra=[(109, "Swagger | —")])]
    fs = [finding("F01", ["C-001", "C-003"], severity="minor", kind="placeholder", title="Поля шаблона не заполнены"),
          finding("F02", ["C-002"], severity="minor", kind="placeholder", title="Согласующие не указаны")]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_title = {f["title"]: f for f in res["findings"]}
    spec = by_title["Не заданы параметры спецификации: адрес вызова, окружение, описание API"]
    assert spec["candidate_ids"] == ["C-003"] and spec["kind"] == "api_contract" and spec["severity"] == "major"
    assert "«Prod: —»" in spec["problem"]
    tpl = by_title["Не заполнены поля и разделы шаблона документа"]
    assert tpl["candidate_ids"] == ["C-001", "C-002"] and tpl["severity"] == "minor"


def test_spec_parameter_regex_is_not_template_field():
    yes = ["Prod: —", "Swagger | —", "curl $BASE/limits", "адрес вызова не указан", "Окружение: —"]
    no = ["Версия: —", "Дата: —", "Согласующие: —", "Jira: —", "Автор: —"]
    assert all(judge._SPEC_PARAM_RE.search(x) for x in yes)
    assert not any(judge._SPEC_PARAM_RE.search(x) for x in no)


def _view(lines: dict[int, str]) -> dict:
    return {"lines": [{"n": n, "text": t} for n, t in sorted(lines.items())]}


def test_unanswered_coverage_rows_become_code_candidates():
    view = _view({29: "На экране видны переключатель и поле ввода. При ошибке ввода сообщение появляется под полем.",
                  38: "Учитываются покупки. Переводы и снятие наличных исключаются.",
                  40: "После смены значения следующее срабатывание вызывает реакцию."})
    cov = [{"topic": "Т10", "line": 29, "question": "Какое сообщение видит клиент при ошибке сервера?", "answer": ""},
           {"topic": "Т9", "line": 38, "question": "Закрыт ли перечень исключённых операций?", "answer": ""},
           {"topic": "Т2", "line": 40, "question": "Запрещает ли ограничение реакцию после смены значения?",
            "answer": ""},
           {"topic": "Т5", "line": 37, "question": "Определено ли активное состояние?", "answer": "L037: «…»"}]
    have = [{"title": "Перечень исключённых операций открыт", "problem": "", "evidence": [{"line": 38, "quote": "x"}]}]
    gaps = lens_analyst.coverage_gaps(cov, have, view)
    assert [g["evidence"][0]["line"] for g in gaps] == [29]     # Т9 уже есть кандидат, Т2 — расхождение, Т5 — ответ
    g = gaps[0]
    assert g["title"] == "Какое сообщение видит клиент при ошибке сервера?" and g["severity"] == "minor"
    assert g["evidence"][0]["quote"] == "При ошибке ввода сообщение появляется под полем."
    assert g["origin"] == "coverage" and g["question"].startswith("Какое сообщение")


def test_mature_document_gets_no_coverage_gaps():
    def fake(ctx, name):
        return {"coverage": [{"topic": "Т10", "line": 2, "question": "Какое сообщение при ошибке?", "answer": ""}],
                "candidates": []}
    lines = ["Термины", "Экран: сообщение при ошибке ввода.", "Версия 1.2", "Время — UTC+5."]
    view = {"lines": [{"n": i, "text": t} for i, t in enumerate(lines, 1)]}
    mature = lens_analyst.run(type("C", (), {"view": view})(), lens_run=fake)
    assert lens_analyst.maturity(view)["mature"] and mature["candidates"] == []
    raw = {"lines": [{"n": 2, "text": "Экран: сообщение при ошибке ввода."}]}
    out = lens_analyst.run(type("C", (), {"view": raw})(), lens_run=fake)
    assert len(out["candidates"]) == 1 and out["coverage_gaps"] == 1


# ─────────── проверка состояния кодом и несколько проходов на слабой модели ───────────

_DOC = {37: "Ф. Владелец активной карты KZT задаёт значение от 1 до 9. По умолчанию функция выключена.",
        117: "1. Проверить пользовательскую сессию.",
        118: "2. Проверить принадлежность карты клиенту.",
        119: "3. Проверить значение и переключатель."}
_REQS = [{"id": "R-01", "kind": "functional", "section": "Часть A › Функциональные требования",
          "line_start": 37, "line_end": 37},
         *[{"id": f"R-{n}", "kind": "functional", "section": "Часть B. REST API › Логика работы метода",
            "line_start": n, "line_end": n} for n in (117, 118, 119)]]


def test_state_from_requirement_missing_in_method_logic_becomes_candidate():
    view = _view(_DOC)
    out = lens_analyst.state_probes(view, _REQS, [])
    assert len(out) == 1
    c = out[0]
    assert c["title"] == "Условие «активной карты KZT» не определено и не проверяется в логике метода"
    assert [e["line"] for e in c["evidence"]] == [37, 118]          # требование и шаг логики о том же объекте
    assert c["evidence"][1]["quote"] == "Проверить принадлежность карты клиенту."
    assert "валюта" in c["problem"] and c["origin"] == "state_check" and c["severity"] == "major"


def test_state_check_is_silent_when_logic_checks_it_or_model_has_it():
    checked = {**_DOC, 118: "2. Проверить, что карта принадлежит клиенту, активна и открыта в тенге."}
    assert lens_analyst.state_probes(_view(checked), _REQS, []) == []
    assert lens_analyst.state_probes(_view(_DOC), _REQS[:1], []) == []      # нет логики метода — сверять не с чем
    have = [{"title": "Не определено, что такое активная карта", "evidence": [{"line": 37, "quote": "x"}]}]
    assert lens_analyst.state_probes(_view(_DOC), _REQS, have) == []


def test_passes_by_model_family_and_override(monkeypatch):
    monkeypatch.delenv("BCC_ANALYST_PASSES", raising=False)
    def ctx(provider, model, options=None):
        llm = type("L", (), {"provider_name": provider, "model": model})()
        return type("C", (), {"llm": llm, "options": options or {}})()
    assert lens_analyst.passes_for(ctx("gemini", "gemini-3.6-flash")) == 2
    assert lens_analyst.passes_for(ctx("gemini", "gemini-3.5-flash-lite")) == 2
    assert lens_analyst.passes_for(ctx("claude_cli", "haiku")) == 1
    assert lens_analyst.passes_for(ctx("mock", None)) == 1
    assert lens_analyst.passes_for(ctx("claude_cli", "haiku", {"analyst_passes": 2})) == 2
    monkeypatch.setenv("BCC_ANALYST_PASSES", "1")
    assert lens_analyst.passes_for(ctx("gemini", "gemini-3.6-flash")) == 1


def _pass(cands, cov):
    return {"candidates": cands, "coverage": cov}


def test_two_passes_are_merged_without_repeats(monkeypatch):
    monkeypatch.setenv("BCC_ANALYST_PASSES", "2")
    a = _pass([{"title": "Не определено событие учёта операции", "kind": "ambiguity", "severity": "major",
                "evidence": [{"quote": "Учитываются покупки.", "line": 38}], "problem": "p"}],
              [{"topic": "Т3", "line": 38, "question": "Какое событие включает операцию в учёт?", "answer": ""}])
    b = _pass([{"title": "Событие учёта операции не определено", "kind": "incomplete", "severity": "major",
                "evidence": [{"quote": "Учитываются покупки.", "line": 38}], "problem": "p"},
               {"title": "Перечень исключённых операций открыт", "kind": "incomplete", "severity": "major",
                "evidence": [{"quote": "Переводы исключаются.", "line": 38}], "problem": "p"}],
              [{"topic": "Т3", "line": 38, "question": "Какое событие включает операцию в учёт?", "answer": ""},
               {"topic": "Т11", "line": 29, "question": "Какое сообщение видит клиент при ошибке сервера?",
                "answer": ""}])
    seen = []

    def fake(ctx, name):
        noted = isinstance(ctx, lens_analyst._NotedContext)
        seen.append(noted)
        return b if noted else a
    view = _view({29: "При ошибке ввода сообщение появляется под полем.", 38: "Учитываются покупки. Переводы исключаются."})
    out = lens_analyst.run(type("C", (), {"view": view, "requirements": []})(), lens_run=fake)
    assert sorted(seen) == [False, True] and out["passes"] == 2
    titles = [c["title"] for c in out["candidates"]]
    assert titles[:2] == ["Не определено событие учёта операции", "Перечень исключённых операций открыт"]
    assert len(out["coverage"]) == 2                                   # одинаковая строка описи — один раз
    assert "Какое сообщение видит клиент при ошибке сервера?" in titles   # пробел описи второго прохода


def test_failed_second_pass_keeps_first(monkeypatch):
    monkeypatch.setenv("BCC_ANALYST_PASSES", "2")
    warnings = []

    def fake(ctx, name):
        if isinstance(ctx, lens_analyst._NotedContext):
            raise TimeoutError("медленно")
        return _pass([{"title": "Перечень исключённых операций открыт", "kind": "incomplete", "severity": "major",
                       "evidence": [{"quote": "q", "line": 38}], "problem": "p"}], [])
    ctx = type("C", (), {"view": None, "requirements": [], "warn": lambda self, m: warnings.append(m)})()
    out = lens_analyst.run(ctx, lens_run=fake)
    assert out["passes"] == 1 and len(out["candidates"]) == 1
    assert warnings and "проход 2 из 2 не удался" in warnings[0]


def test_noted_context_appends_pass_note_to_task():
    base = type("C", (), {"prompt": lambda self, name, **kw: ("sys", "задание"), "llm": "L"})()
    noted = lens_analyst._NotedContext(base, lens_analyst.SECOND_PASS_NOTE)
    system, user = noted.prompt("lens_analyst")
    assert system == "sys" and user.startswith("задание") and "Т15 → Т1" in user and noted.llm == "L"


def test_code_question_rejected_as_exact_sense_stays_minor_finding():
    cs = [cand("C-001", 37, "Держатель активной карты задаёт значение", kind="incomplete", criterion="complete",
               severity="minor", title="Определено ли состояние активной карты для доступа к функции?",
               origin="coverage"),
          cand("C-002", 46, "быстро", kind="ambiguity"),
          cand("C-003", 29, "При ошибке ввода сообщение появляется под полем", kind="incomplete",
               criterion="complete", origin="")]
    rej = [{"candidate_id": "C-001", "reason_code": "exact_sense", "reason": "общепринятое понятие", "line": 37},
           {"candidate_id": "C-002", "reason_code": "exact_sense", "reason": "есть число", "line": 46},
           {"candidate_id": "C-003", "reason_code": "exact_sense", "reason": "понятно", "line": 29}]
    res = judge.run(Ctx(FakeLLM(response([], rejected=rej))), cs)
    all_placed(res, [c["id"] for c in cs])
    kept = [f for f in res["findings"] if f["candidate_ids"] == ["C-001"]]
    assert len(kept) == 1 and kept[0]["severity"] == "minor"
    assert kept[0]["title"] == "Определено ли состояние активной карты для доступа к функции?"
    # кандидат о размытом слове и вопрос модели (не кода) снимаются, как раньше
    assert {r["candidate_id"] for r in res["rejected"]} == {"C-002", "C-003"}


def test_count_limit_per_period_without_boundaries_becomes_candidate():
    doc = {38: "Ф. Период определяется по дате операции. Учитываются покупки.",
           39: "Ф. Когда сумма доходит до значения, клиент получает сообщение. Не больше одного сообщения за календарный месяц."}
    reqs = [{"id": f"R-{n}", "kind": "functional", "section": "Часть A › Функциональные требования",
             "line_start": n, "line_end": n} for n in (38, 39)]
    out = lens_analyst.period_probes(_view(doc), reqs, [])
    assert len(out) == 1
    c = out[0]
    assert c["title"] == "Не определено, как считается период ограничения «за календарный месяц»"
    assert c["evidence"] == [{"quote": "Не больше одного сообщения за календарный месяц.", "line": 39}]
    assert "часовом поясе" in c["problem"] and "(строка 38)" in c["problem"] and c["origin"] == "period_check"
    # граница названа в той же фразе — молчит; у модели уже есть кандидат о границе периода — молчит
    told = {**doc, 39: "Не больше одного сообщения за календарный месяц по времени UTC+5."}
    assert lens_analyst.period_probes(_view(told), reqs, []) == []
    have = [{"title": "Не задан часовой пояс месяца ограничения", "evidence": [{"line": 39, "quote": "x"}]}]
    assert lens_analyst.period_probes(_view(doc), reqs, have) == []
    k2 = [{"title": "Противоречие ограничения в месяц и повторной реакции", "evidence": [{"line": 39, "quote": "x"}]}]
    assert len(lens_analyst.period_probes(_view(doc), reqs, k2)) == 1   # «в месяц» в заголовке — не о границе


def test_wish_grouped_by_judge_is_not_merged_with_other_wishes_of_same_place():
    cs = [cand("C-001", 38, "исключаются", kind="incomplete", reqs=("R-06",)),
          cand("C-002", 38, "исключаются", kind="incomplete", reqs=("R-06",), source="lens:risk"),
          cand("C-003", 39, "за календарный месяц", kind="ambiguity", reqs=("R-06", "R-07")),
          cand("C-004", 38, "в Алматы", kind="ambiguity", reqs=("R-06",), source="lens:risk"),
          cand("C-005", 38, "входят", kind="incomplete", reqs=("R-06",)),
          cand("C-006", 38, "Возврат уменьшает", kind="incomplete", reqs=("R-06",))]
    fs = [dict(finding("F01", ["C-001", "C-002"], severity="minor", title="Перечень исключённых операций открыт",
                       reqs=("R-06",)), wish=True),
          dict(finding("F02", ["C-003", "C-004"], severity="minor", title="Пояс и граница календарного месяца",
                       reqs=("R-06", "R-07")), wish=True),
          dict(finding("F03", ["C-005"], severity="minor", title="Операции в другой валюте", reqs=("R-06",)), wish=True),
          dict(finding("F04", ["C-006"], severity="minor", title="Частичный возврат", reqs=("R-06",)), wish=True)]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_ids = {tuple(f["candidate_ids"]): f["title"] for f in res["findings"]}
    assert by_ids[("C-001", "C-002")] == "Перечень исключённых операций открыт"     # темы, собранные судьёй, — как есть
    assert by_ids[("C-003", "C-004")] == "Пояс и граница календарного месяца"
    assert by_ids[("C-005", "C-006")].startswith("Документ не рассматривает ряд случаев")  # мелочи к месту — сводятся


def test_undefined_term_is_not_folded_into_different_names_summary():
    cs = [cand("C-001", 37, "Держатель активной карты", kind="terminology", severity="minor", reqs=("R-05",)),
          cand("C-002", 26, "сервис настроек", kind="terminology", severity="minor", reqs=(), source="lens:architect"),
          cand("C-003", 43, "сервис уведомлений", kind="terminology", severity="minor", reqs=(),
               source="consistency")]
    fs = [finding("F01", ["C-001"], severity="minor", kind="terminology",
                  title="Неопределён бизнес-термин «активная карта» в условии требования"),
          finding("F02", ["C-002"], severity="minor", kind="terminology", title="Компонент назван по-разному"),
          finding("F03", ["C-003"], severity="minor", kind="terminology", title="Сервис назван двумя словами")]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_ids = {tuple(f["candidate_ids"]): f["title"] for f in res["findings"]}
    assert by_ids[("C-001",)].startswith("Неопределён бизнес-термин")          # неоднозначность правила — отдельно
    assert by_ids[("C-002", "C-003")] == "Одни и те же понятия названы разными терминами"
    assert all(judge._UNDEFINED_TERM_RE.search(t) for t in (
        "Термин «X» не определён", "Не определено понятие", "Нет определения статуса", "Неопределённый термин"))
    assert not judge._UNDEFINED_TERM_RE.search("Компонент назван по-разному в схеме и тексте")


def test_missing_field_rule_folded_into_other_defect_is_kept_apart():
    cs = [cand("C-001", 171, '{"result":"ERROR"}', kind="status_conflict", reqs=(), source="lens:architect",
               title="Ошибка валидации возвращается с кодом 200"),
          cand("C-002", 151, "и далее", kind="api_contract", reqs=(), source="rules:language.open_list",
               title="Открытый перечень кодов ответа"),
          cand("C-003", 180, '{"message":"Некорректный запрос"}', kind="api_contract", reqs=(),
               source="rules:api.result_field_missing.result", title="Ответы 400 и 500 без поля result из таблицы")]
    fs = [finding("F01", ["C-001", "C-002", "C-003"], kind="status_conflict",
                  title="Противоречивое описание кодов ответа и ошибка под кодом 200")]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_ids = {tuple(f["candidate_ids"]): f for f in res["findings"]}
    assert set(by_ids) == {("C-001", "C-002"), ("C-003",)}
    apart = by_ids[("C-003",)]
    assert apart["title"] == "Ответы 400 и 500 без поля result из таблицы" and apart["severity"] in ("major", "minor")
    # судья сам назвал поле в заголовке — сигнал остаётся в его дефекте
    fs2 = [finding("F01", ["C-001", "C-003"], kind="api_contract", title="Ответы об ошибках: поле result и код 200")]
    res2 = judge.run(Ctx(FakeLLM(response(fs2))), cs[:1] + cs[2:])
    assert [tuple(f["candidate_ids"]) for f in res2["findings"]] == [("C-001", "C-003")]


def test_period_check_folded_into_other_defect_is_kept_apart():
    cs = [cand("C-001", 38, "Возврат уменьшает расходы", kind="incomplete", reqs=("R-06",)),
          cand("C-002", 38, "Возврат уменьшает расходы", kind="incomplete", reqs=("R-06",), source="lens:risk",
               title="Не определено поведение при возврате за прошлый закрытый период"),
          cand("C-003", 39, "не больше одного сообщения за календарный месяц", reqs=("R-07",), origin="period_check",
               title="Не определено, как считается период ограничения «за календарный месяц»")]
    fs = [finding("F01", ["C-001", "C-002", "C-003"], kind="incomplete",
                  title="Не определено влияние возвратов на признак отправки в прошедших месяцах")]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    all_placed(res, [c["id"] for c in cs])
    by_ids = {tuple(f["candidate_ids"]): f["title"] for f in res["findings"]}
    assert by_ids == {("C-001", "C-002"): "Не определено влияние возвратов на признак отправки в прошедших месяцах",
                      ("C-003",): "Не определено, как считается период ограничения «за календарный месяц»"}
    # судья назвал пояс и границу периода — проверка остаётся в его дефекте
    fs2 = [finding("F01", ["C-002", "C-003"], title="Не определены часовой пояс и граница календарного месяца")]
    res2 = judge.run(Ctx(FakeLLM(response(fs2))), cs[1:])
    assert [tuple(f["candidate_ids"]) for f in res2["findings"]] == [("C-002", "C-003")]


def test_pass_answers_are_recorded_in_pass_order_and_replayed_in_order(monkeypatch):
    import threading
    import time

    class _LLM:
        provider_name, model = "gemini", "gemini-3.6-flash"

        def __init__(self):
            self.responses, self.lock = {}, threading.Lock()

    class _Ctx:
        def __init__(self, llm):
            self.llm, self.options = llm, {}

        def prompt(self, stage):
            return "s", "u"

    def live(ctx, name):  # второй проход отвечает раньше первого
        second = isinstance(ctx, lens_analyst._NotedContext)
        time.sleep(0.01 if second else 0.2)
        with ctx.llm.lock:
            ctx.llm.responses.setdefault("lens_analyst", []).append({"pass": 2 if second else 1})
        return {"candidates": [], "coverage": [], "pass": 2 if second else 1}

    llm = _LLM()
    outs, _ = lens_analyst._run_passes(_Ctx(llm), live, 2)
    assert [o["pass"] for o in outs] == [1, 2]
    assert llm.responses["lens_analyst"] == [{"pass": 1}, {"pass": 2}]  # порядок проходов, не прихода

    replay = iter(llm.responses["lens_analyst"])
    mock = _LLM()
    mock.provider_name = "mock"
    order = []

    def mocked(ctx, name):  # mock: k-й ответ на k-й вызов
        order.append("2" if isinstance(ctx, lens_analyst._NotedContext) else "1")
        return {"candidates": [], "coverage": [], **next(replay)}

    outs2, _ = lens_analyst._run_passes(_Ctx(mock), mocked, 2)
    assert order == ["1", "2"] and [o["pass"] for o in outs2] == [1, 2]
