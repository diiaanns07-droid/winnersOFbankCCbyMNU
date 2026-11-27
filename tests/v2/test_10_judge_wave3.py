"""Волна 3 (F2 за №10): проверка critical кодом после судьи — на синтетике, без сети.

critical остаётся critical, только если: основание не уровня major и не «нет основания»; для противоречия (а) —
цитаты двух разных мест (не только цель документа) об одном предмете; есть признак основной функции (цитата
или требование функционального вида, а не только НФТ, цель, ограничения). Иначе — major с предупреждением,
и вердикт «нельзя» не выставляется.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, cand, finding, response  # noqa: E402

REQS = [
    {"id": "R-01", "kind": "goal", "line_start": 5, "line_end": 5, "quote": "Цель"},
    {"id": "R-02", "kind": "functional", "line_start": 10, "line_end": 12, "quote": "Правило"},
    {"id": "R-03", "kind": "acceptance", "line_start": 20, "line_end": 20, "quote": "Приёмка"},
    {"id": "R-04", "kind": "nonfunctional", "line_start": 30, "line_end": 31, "quote": "НФТ"},
    {"id": "R-05", "kind": "constraint", "line_start": 40, "line_end": 40, "quote": "Ограничение"},
]

RULE = (10, "Начисление выполняется по дате зачисления платежа на счёт")
ACCEPT = (20, "Платёж от 31-го числа начисляется в следующем периоде по дате создания платежа")
NFR = (30, "Ответ сервиса не дольше двух секунд в 95 процентах запросов")
NFR2 = (31, "Данные обновляются раз в сутки ночью")
GOAL = (5, "Клиент видит начисление сразу после зачисления платежа")
LIMIT = (40, "Решение использует существующую шину событий банка")


def pair(cid, a, b, *, source, kind="event_conflict", criterion="set_consistent", reqs=("R-02", "R-03"), **kw):
    return cand(cid, a[0], a[1], kind=kind, criterion=criterion, severity="critical", reqs=reqs, source=source,
                extra=[b], **kw)


def crit(key, ids, basis, *, kind="event_conflict", criterion="set_consistent", reqs=(), title=None):
    f = finding(key, ids, severity="critical", kind=kind, criterion=criterion, priority=1, blocks="both",
                scenario="Платёж создан 31-го, зачислен 1-го: по правилу — один период, по приёмке — другой.",
                impact="Начисление уйдёт не в тот период.", reqs=reqs, title=title)
    f["severity_basis"] = basis
    return f


def run(findings, cands, checklist=None):
    ctx = Ctx(None, requirements=REQS)
    clusters = [[c["id"]] for c in cands]
    res = judge.assemble(response(findings), cands, clusters, requirements=REQS, ctx=ctx, warnings=[],
                         checklist=checklist)
    return res, ctx


def sev(res):
    return [f["severity"] for f in res["findings"]]


def test_conflict_with_two_sides_of_one_subject_stays_critical():
    cs = [pair("C-001", RULE, ACCEPT, source="lens:qa"), pair("C-002", RULE, ACCEPT, source="consistency")]
    res, _ = run([crit("F01", ["C-001", "C-002"], "(а) период начисления: L010 ↔ L020",
                       title="Приёмка относит платёж к другому периоду, чем правило начисления")], cs)
    assert sev(res) == ["critical"]
    assert judge.compute_verdict(res["findings"])["development"] == "no"


def test_conflict_quotes_of_different_subjects_demoted():
    cs = [pair("C-001", RULE, NFR, source="lens:qa", reqs=("R-02", "R-04")),
          pair("C-002", RULE, NFR, source="consistency", reqs=("R-02", "R-04"))]
    f = crit("F01", ["C-001", "C-002"], "(а) разный исход", title="Два места расходятся")
    f["problem"] = "Места расходятся."
    f["scenario"] = "Вход X: по одному месту так, по другому иначе."
    res, ctx = run([f], cs)
    assert sev(res) == ["major"]
    assert any("двух мест об одном предмете" in w for w in ctx.warnings)
    assert judge.compute_verdict(res["findings"])["development"] != "no"


def test_conflict_where_one_side_is_only_the_goal_demoted():
    cs = [pair("C-001", GOAL, RULE, source="lens:risk", reqs=("R-01", "R-02")),
          pair("C-002", GOAL, RULE, source="consistency", reqs=("R-01", "R-02"))]
    res, ctx = run([crit("F01", ["C-001", "C-002"], "(а) цель против правила: L005 ↔ L010",
                         title="Зачисление платежа: цель обещает сразу, правило — по дате зачисления")], cs)
    assert sev(res) == ["major"]
    assert any("двух мест" in w for w in ctx.warnings)


def test_critical_only_about_nonfunctional_requirements_demoted():
    cs = [cand("C-001", NFR[0], NFR[1], kind="ambiguity", severity="critical", reqs=("R-04",),
               source="lens:qa", extra=[NFR2]),
          cand("C-002", NFR2[0], NFR2[1], kind="ambiguity", severity="critical", reqs=("R-04",),
               source="lens:risk", extra=[LIMIT])]
    res, ctx = run([crit("F01", ["C-001", "C-002"], "(б) срок обновления данных толкуется двояко",
                         kind="ambiguity", criterion="unambiguous", reqs=["R-04", "R-05"])], cs)
    assert sev(res) == ["major"]
    assert any("не касается основной функции" in w for w in ctx.warnings)


def test_critical_with_major_level_basis_demoted():
    cs = [pair("C-001", RULE, ACCEPT, source="lens:qa"), pair("C-002", RULE, ACCEPT, source="consistency")]
    res, ctx = run([crit("F01", ["C-001", "C-002"], "м2: фраза о дате допускает два толкования")], cs)
    assert sev(res) == ["major"]
    assert any("уровня major" in w for w in ctx.warnings)


def test_critical_without_basis_named_by_judge_demoted():
    cs = [pair("C-001", RULE, ACCEPT, source="lens:qa"), pair("C-002", RULE, ACCEPT, source="consistency")]
    res, ctx = run([crit("F01", ["C-001", "C-002"], "нет основания по шкале, но важно")], cs)
    assert sev(res) == ["major"]
    v = judge.compute_verdict(res["findings"])
    assert v["development"] == "yes" and v["testing"] == "yes"


def test_promised_operation_of_main_function_stays_critical():
    promise = (11, "Настройки клиент получает методом чтения, описанным в разделе API")
    cs = [cand("C-001", promise[0], promise[1], kind="missing_element", criterion="set_complete",
               severity="critical", reqs=("R-02",), source="lens:architect"),
          cand("C-002", promise[0], promise[1], kind="missing_element", criterion="set_complete",
               severity="critical", reqs=("R-02",), source="rules:promises.read_operation")]
    res, _ = run([crit("F01", ["C-001", "C-002"], "(в) обещан метод чтения в L011, в API его нет",
                       kind="missing_element", criterion="set_complete", reqs=["R-02"])], cs)
    assert sev(res) == ["critical"]


def test_check_basis_without_ground_demotes_kept_critical():
    """Вторая проверка оставила critical, но сама написала «нет основания» — код понижает."""
    cs = [pair("C-001", RULE, ACCEPT, source="lens:qa"), pair("C-002", RULE, ACCEPT, source="consistency")]
    judged = response([crit("F01", ["C-001", "C-002"], "(а) период: L010 ↔ L020",
                            title="Приёмка относит платёж к другому периоду, чем правило начисления")])
    check = {"checks": [{"key": "F01", "basis": "нет основания: документ сам задаёт порядок",
                         "severity": "critical", "reason": ""}], "verdict_summary": ""}
    ctx = Ctx(FakeLLM(judged, check), requirements=REQS, options={})
    res = judge.run(ctx, cs)
    assert sev(res) == ["major"]
    assert any("не назвали основание" in w for w in res["warnings"])
    assert judge.compute_verdict(res["findings"])["development"] != "no"


def test_unknown_requirement_kinds_do_not_block_critical():
    """Нарезки нет (требования не известны) — признак основной функции не проверяется, critical остаётся."""
    cs = [pair("C-001", RULE, ACCEPT, source="lens:qa", reqs=()),
          pair("C-002", RULE, ACCEPT, source="consistency", reqs=())]
    f = crit("F01", ["C-001", "C-002"], "(а) период начисления: L010 ↔ L020",
             title="Приёмка относит платёж к другому периоду, чем правило начисления")
    ctx = Ctx(None, requirements=[])
    res = judge.assemble(response([f]), cs, [["C-001"], ["C-002"]], requirements=[], ctx=ctx, warnings=[])
    assert sev(res) == ["critical"]


def test_basis_letter_parsing():
    assert judge.critical_basis({"_basis": "(а) один вход — два исхода"}) == "а"
    assert judge.critical_basis({"_basis": "б) событие не определено"}) == "б"
    assert judge.critical_basis({"_basis": "", "_check_basis": "(в) обещано в L052"}) == "в"
    assert judge.critical_basis({"_basis": "", "kind": "status_conflict"}) == "а"
    assert judge.critical_basis({"_basis": "", "kind": "missing_element"}) == "в"
