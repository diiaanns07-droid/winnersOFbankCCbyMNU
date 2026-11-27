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
    for n in range(1, 15):
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
