"""Неоднозначная граница лимита операции → тест банка (№10).

Пункт Л-1 «Сумма одной операции перевода — до 500 000 ₸» не говорит, проводится ли перевод ровно на лимит.
Проверяется по настоящему интерфейсу ``build_bank_pack`` (и движку ``run_review`` на записи mock-транспорта):

* до решения владельца проверяемы 499 999 ₸ (проводится) и 500 001 ₸ (отклоняется); 500 000 ₸ открыт;
* замечание, вопрос №08, решение владельца, строка «Требование может быть протестировано» и три теста
  связаны ссылками;
* после ответа владельца у всех трёх точек конкретный исход в тенге с шагом 1 ₸;
* на чистом примере с уже включительной границей нет ни открытого вопроса, ни блокера строки.
"""

from __future__ import annotations

import json
import shutil

import pytest

from bcc_review.bank import collect_questions

from . import limit_case as lc

ACCEPT = {v: f"операция на {s} ₸ проводится" for v, s in ((499_999, "499 999"), (500_000, "500 000"))}
REJECT = {v: f"операция на {s} ₸ отклоняется с сообщением «Превышен лимит операции»" for v, s in ((500_000, "500 000"), (500_001, "500 001"))}
INCLUSIVE = {"hi-1": ACCEPT[499_999], "hi": ACCEPT[500_000], "hi+1": REJECT[500_001]}
EXCLUSIVE = {"hi-1": ACCEPT[499_999], "hi": REJECT[500_000], "hi+1": REJECT[500_001]}


def chain(decisions_for=None, **kw):
    doc = lc.document()
    reqs = lc.requirements(doc)
    f = lc.finding(doc)
    qs = lc.questions(doc, [f])
    decs = decisions_for(doc, qs[0]["id"]) if decisions_for else []
    return doc, qs, lc.pack(doc, reqs, [f], decs, qs, **kw)


def assert_units(cases: dict) -> None:
    assert {pos: (t["values"]["input"], t["values"]["unit"], t["values"]["step"]) for pos, t in cases.items()} == {
        pos: (v, lc.UNIT, lc.STEP) for pos, v in lc.POINTS.items()}
    assert all(t["values"]["range"] == [None, lc.LIMIT] for t in cases.values())


def test_before_decision_verifiable_expectations_are_separated_from_undecided():
    _, qs, before = chain()
    cases = lc.boundary(before)
    assert set(cases) == {"hi-1", "hi", "hi+1"}
    assert_units(cases)
    # Проверяемо при любом ответе владельца.
    for pos in ("hi-1", "hi+1"):
        t = cases[pos]
        assert t["status"] == "draft" and t["open_question_id"] is None and t["expected"] == INCLUSIVE[pos]
        assert t["req_ids"][0] == "R-01" and t["obligation"]["source_id"] == "Л-1"
    assert any("Превышен лимит операции" in e["quote"] for e in cases["hi+1"]["evidence"])  # сообщение — из Л-2
    assert "R-02" in cases["hi+1"]["req_ids"]
    # Решения банка ещё нет: исход на самой границе открыт, варианты — оба исхода.
    hi = cases["hi"]
    assert hi["status"] == "open" and hi["expected"].startswith(f"ОТКРЫТО до решения {qs[0]['id']}")
    assert [(o["label"], o["expected"]) for o in hi["options"]] == [("граница включена", ACCEPT[500_000]),
                                                                  ("граница не включена", REJECT[500_000])]
    # Вопрос — тот, что №08 задал по замечанию F-LIM: второго вопроса о том же банк не заводит.
    assert qs[0]["finding_ids"] == ["F-LIM"]
    assert hi["open_question_id"] == qs[0]["id"] and hi["open_question"]["existing"] is True
    assert hi["open_question"]["finding_ids"] == ["F-LIM"] and "F-LIM" in hi["finding_ids"]
    assert [q["id"] for q in collect_questions(before)] == [qs[0]["id"]]
    # Строка чек-листа: блокер — F-LIM, со ссылкой на открытый сценарий.
    row = lc.testability(before)
    assert row["text"] == "Требование может быть протестировано"
    assert row["cells"] == {"available": "Да", "checked": "Нет"} and row["checked"] == "no"
    assert row["machine"]["blocking_finding_ids"] == ["F-LIM"] and row["machine"]["resolved"] == []
    assert f"F-LIM: исход на границе не выводится — {hi['id']} открыт до решения {qs[0]['id']}" in row["note"]
    assert any(e["quote"] == "до 500 000 ₸" for e in row["evidence"])


@pytest.mark.parametrize("wording,expected", [(lc.INCLUSIVE_WORDING, INCLUSIVE), (lc.EXCLUSIVE_WORDING, EXCLUSIVE)],
                         ids=["включительно", "строго меньше"])
def test_owner_decision_gives_concrete_expectations_for_three_points(wording, expected):
    _, qs, before = chain()
    qid = qs[0]["id"]
    # Буква «A» — вариант №08 «Уточнить формулировку»; включённость задаёт формулировка владельца.
    _, _, after = chain(lambda doc, q: [lc.decision(doc, q, "A", note=f"Формулировка: {wording}")], previous=before)
    cases = lc.boundary(after)
    assert_units(cases)
    assert {pos: t["expected"] for pos, t in cases.items()} == expected
    assert all(t["status"] != "open" for t in after["test_cases"]) and collect_questions(after) == []
    hi = cases["hi"]
    assert hi["status"] == "agreed" and hi["decision_id"] == f"answer:{qid}" and hi["resolved_question_id"] == qid
    ch = next(c for c in hi["changes"] if c["field"] == "expected")
    assert ch["decision_id"] == f"answer:{qid}" and ch["before"].startswith("открыт:") and wording in ch["reason"]
    assert hi["gherkin"].endswith(expected["hi"])
    # Строка чек-листа после решения: F-LIM снято решением, «Нет» → «Да» с причиной.
    row = lc.testability(after)
    assert row["cells"]["checked"] == "Да" and row["machine"]["blocking_finding_ids"] == []
    assert row["finding_ids"] == ["F-LIM"]
    res = row["machine"]["resolved"]
    assert [(r["finding_id"], r["test_case_id"], r["decision_id"]) for r in res] == [("F-LIM", hi["id"], f"answer:{qid}")]
    assert res[0]["option"] == ("граница включена" if expected is INCLUSIVE else "граница не включена")
    assert [(c["field"], c["before"], c["after"], c["decision_id"]) for c in row["changes"]] == [
        ("checked", "Нет", "Да", f"answer:{qid}")]
    assert "формулировка в документе не изменена" in row["note"]  # правка — дело редакции №08
    assert not any(w.code in {"bank.decision_unmatched", "bank.decision_unmapped"} for w in after["warnings"])


@pytest.mark.parametrize("wording,expected", [(lc.INCLUSIVE_WORDING, INCLUSIVE), (lc.EXCLUSIVE_WORDING, EXCLUSIVE)],
                         ids=["включительно", "строго меньше"])
def test_answers_md_parsed_by_module_08_reaches_the_boundary(wording, expected):
    """Ответ из answers.md, разобранный настоящим parse_answers №08: буква — в choice, формулировка — в wording."""
    from bcc_review.decisions.answers import parse_answers, render_questions_md

    doc = lc.document()
    f = lc.finding(doc)
    qs = lc.questions(doc, [f])
    md = render_questions_md(doc, qs).replace("Ответ:\n", f"Ответ:\nA\nФормулировка: {wording}\n", 1)
    decs = list(parse_answers(md, doc, questions=qs))
    assert [(d.question_id, d.choice, d.wording) for d in decs] == [(qs[0]["id"], "A", wording)]
    p = lc.pack(doc, lc.requirements(doc), [f], decs, qs)
    assert {pos: t["expected"] for pos, t in lc.boundary(p).items()} == expected
    assert lc.testability(p)["cells"]["checked"] == "Да"


@pytest.mark.parametrize("answer,note", [("B", ""), ("A", "Формулировка: Сумма одной операции перевода — до 500 000 ₸.")],
                         ids=["риск принят", "та же неоднозначность"])
def test_decision_that_does_not_fix_the_boundary_keeps_it_open(answer, note):
    _, qs, after = chain(lambda doc, q: [lc.decision(doc, q, answer, note=note)])
    hi = lc.boundary(after)["hi"]
    assert hi["status"] == "open" and hi["open_question_id"] == qs[0]["id"]
    assert any("не говорит, входит ли граница" in n for n in hi["notes"])
    assert "bank.decision_unmapped" in {w.code for w in after["warnings"]}
    row = lc.testability(after)
    assert row["cells"]["checked"] == "Нет" and row["machine"]["blocking_finding_ids"] == ["F-LIM"] and row["changes"] == []


@pytest.mark.parametrize("bound", ["— до 500 000 ₸ включительно.", "— до 500 000 ₸ (включительно).", "— не более 500 000 ₸.",
                                   "— не превышает 500 000 ₸."])
@pytest.mark.parametrize("complete", [True, False], ids=["с моделью", "без модели"])
def test_clean_inclusive_boundary_has_no_extra_blocker(bound, complete):
    doc = lc.document(bound)
    clean = lc.pack(doc, lc.requirements(doc, bound), [], [], [], complete=complete)
    cases = lc.boundary(clean)
    assert_units(cases)
    # Те же три исхода, что и после решения «включительно», но без вопроса и без решения.
    assert {pos: t["expected"] for pos, t in cases.items()} == INCLUSIVE
    assert all(t["status"] == "draft" and not t["decision_id"] for t in cases.values())
    assert collect_questions(clean) == [] and all(t["status"] != "open" for t in clean["test_cases"])
    row = lc.testability(clean)
    assert row["machine"]["blocking_finding_ids"] == [] and row["finding_ids"] == [] and row["changes"] == []
    # С моделью — «Да»; без модели положительный вывод не делается, но и «Нет» не ставится.
    assert row["cells"]["checked"] == ("Да" if complete else None) and "исход на границе" not in row["note"]
    assert all(r["cells"]["checked"] != "Нет" for r in clean["checklist"])


def test_open_boundary_without_finding_is_not_reported_as_testable():
    """Без замечания «Нет» не ставится, но и «Да» — нет: свой сценарий пакета не выводит исход на границе."""
    doc = lc.document()
    p = lc.pack(doc, lc.requirements(doc), [], [], [])
    hi = lc.boundary(p)["hi"]
    row = lc.testability(p)
    assert hi["status"] == "open" and row["cells"]["checked"] is None and row["machine"]["blocking_finding_ids"] == []
    assert f"{hi['id']} открыт до решения {hi['open_question_id']}" in row["machine"]["basis"]


# ---------------------------------------------------------------- движок на записи mock-транспорта


@pytest.fixture
def engine_env(monkeypatch):
    from bcc_review import engine

    monkeypatch.setattr(engine, "SLEEP", lambda s: None)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    return engine


def _run(engine, tmp_path, name, src, mock, **extra):
    from bcc_review.contracts import RunOptions

    opts = {"provider": "mock", "mock_script": str(mock), "use_cache": False, "artifacts_dir": str(tmp_path / f"{name}.art"), **extra}
    return engine.run_review(src, tmp_path / f"{name}.md", options=RunOptions.coerce(opts))


def test_engine_team_module_vs_fallback_on_limit(tmp_path, engine_env, monkeypatch):
    import bcc_review.contracts as C
    from bcc_review.cli import main as cli_main

    src = tmp_path / "limit.md"
    shutil.copy(lc.LIMIT_MD, src)
    team = _run(engine_env, tmp_path, "team", src, lc.MOCK)
    C.validate(team)
    assert team["run"]["modules"]["build_bank_pack"] == "team:bcc_review.bank.checklist:build_bank_pack"
    amb = next(f for f in team["findings"] if f["kind"] == "ambiguity")
    assert [e["quote"] for e in amb["evidence"]] == ["до 500 000 ₸"] and amb["severity"] == "major"
    assert any(amb["id"] in q["finding_ids"] for q in team["questions"])  # вопрос №08 по замечанию
    cases = lc.boundary(team)
    assert {p: t["values"]["input"] for p, t in cases.items()} == lc.POINTS
    assert cases["hi-1"]["expected"] == INCLUSIVE["hi-1"] and cases["hi+1"]["expected"] == INCLUSIVE["hi+1"]
    assert cases["hi"]["status"] == "open" and cases["hi"]["open_question"]["finding_ids"] == [amb["id"]]
    row = lc.testability(team)
    assert row["checked"] == "no" and row["machine"]["blocking_finding_ids"] == [amb["id"]]
    assert cli_main(["verify", str(tmp_path / "team.json"), str(src)]) == C.EXIT_OK

    monkeypatch.setenv("BCC_FORCE_FALLBACK", "build_bank_pack")
    reserve = _run(engine_env, tmp_path, "reserve", src, lc.MOCK)
    assert reserve["run"]["modules"]["build_bank_pack"] == "fallback:bcc_review.runtime.fallback.bank:build_bank_pack"
    assert [f["id"] for f in reserve["findings"]] == [f["id"] for f in team["findings"]]  # вход банка тот же
    assert not [t for t in reserve["test_cases"] if t.get("kind") == "boundary"]
    assert all(r.get("checked") == "unknown" for r in reserve["checklist"])


def test_engine_answers_cycle_revision_gives_clean_boundary(tmp_path, engine_env):
    """answers.md с формулировкой владельца → редакция «до 500 000 ₸ включительно» → три исхода без блокера.

    Ответ модели на редакцию — отдельная запись транспорта (``mock_operation_limit.revised.json``):
    по включительной границе неоднозначности нет.
    """
    from bcc_review.decisions.answers import render_questions_md

    src = tmp_path / "limit.md"
    shutil.copy(lc.LIMIT_MD, src)
    first = _run(engine_env, tmp_path, "first", src, lc.MOCK)
    md = render_questions_md(first["document"], first["questions"])
    answer = f"Перевод на сумму, равную лимиту, проводится.\nФормулировка: {lc.INCLUSIVE_WORDING}\n"
    (tmp_path / "answers.md").write_text(md.replace("Ответ:\n", "Ответ:\n" + answer, 1), encoding="utf-8")
    second = _run(engine_env, tmp_path, "second", src, lc.MOCK_REVISED, answers_path=str(tmp_path / "answers.md"),
                  compare_path=str(tmp_path / "first.json"))
    assert next(s for s in second["run"]["stages"] if s["name"] == "answers")["status"] == "ok"
    assert [e["new"] for d in second["decisions"] for e in d["edits"]] == [lc.INCLUSIVE_WORDING]
    assert second["run"]["modules"]["build_bank_pack"].startswith("team:")
    cases = lc.boundary(second)
    assert {p: t["expected"] for p, t in cases.items()} == INCLUSIVE and all(t["status"] == "draft" for t in cases.values())
    row = lc.testability(second)
    assert row["checked"] == "yes" and row["machine"]["blocking_finding_ids"] == []
    assert second["diff"]["resolved"] and not any(f["kind"] == "ambiguity" for f in second["findings"])
    assert json.loads((tmp_path / "second.json").read_text("utf-8"))["checklist"] == second["checklist"]
