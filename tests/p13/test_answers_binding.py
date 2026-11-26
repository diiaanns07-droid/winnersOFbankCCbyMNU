"""Ответ относится к своему вопросу: два прогона одного документа в настоящем браузере.

Сценарий ``browser/answers_scenario.cjs`` пишет отчёты r1, r2, r3 (один SHA документа, разные вопросы
под одинаковыми Q-ID) штатным ``write_html`` в ОДИН путь и открывает их в Chromium с профилем на диске.
Здесь проверяется, куда попадает ответ аналитика: в черновик браузера, в answers.md и в Decision,
который строит опубликованный слот ``parse_answers`` движка (модуль №08 или резерв Max).

Нужны ``node`` и пакет ``playwright`` для Node; без них тесты пропускаются. Опубликованный парсер
есть только в копии с ``bcc_review.runtime`` (ветка bcc/integration); без него соответствующий тест
пропускается, а формат проверяет эталонный ``parse_answers_markdown``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from bcc_review.exports import html as H
from fixture_builder import Q_EVENT, Q_MONTH, Q_PUSH, build_answers_reports
from test_html_browser import _node_env

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "browser" / "answers_scenario.cjs"
SRC = HERE.parents[1] / "src"


def run_scenario(work: Path, src: Path = SRC) -> tuple[dict[str, Any], dict[str, Any]]:
    """Запускает браузерный сценарий с реализацией write_html из ``src``."""
    env = _node_env()
    if env is None:
        pytest.skip("нет node или пакета playwright для Node")
    env = dict(env)
    env["PYTHONPATH"] = os.pathsep.join([str(src)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    env["P13_PYTHON"] = sys.executable
    reports = build_answers_reports()
    for name, rep in reports.items():
        (work / f"{name}.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(["node", str(SCRIPT), str(work)], env=env, capture_output=True, text=True, timeout=600)
    if proc.returncode:
        pytest.fail(f"сценарий упал:\n{proc.stdout}\n{proc.stderr}")
    return reports, json.loads((work / "answers-scenario.json").read_text(encoding="utf-8"))


def published_parse_answers():
    """Опубликованный слот parse_answers движка, если он есть в этой копии."""
    try:
        from bcc_review.runtime.modules import Modules
    except ImportError:
        return None
    res = Modules().get("parse_answers")
    return res if res.func is not None else None


def values(questions: list[dict[str, Any]]) -> dict[str, str]:
    return {q["qid"]: q["value"] for q in questions}


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    work = tmp_path_factory.mktemp("p13-answers")
    reports, obs = run_scenario(work)
    return work, reports, obs


# --------------------------------------------------------------------------- фикстура


def test_three_runs_share_document_and_reuse_q_ids():
    rs = build_answers_reports()
    assert len({r["document"]["id"] for r in rs.values()}) == 1
    fp = {n: {q["id"]: H.question_fingerprint(r, q) for q in r["questions"]} for n, r in rs.items()}
    assert fp["r1"]["Q-01"] != fp["r2"]["Q-01"], "Q-01 в r1 и r2 — разные вопросы"
    assert fp["r1"]["Q-02"] == fp["r2"]["Q-02"] == fp["r3"]["Q-03"], "тот же вопрос о событии — тот же отпечаток"
    assert fp["r2"]["Q-01"] == fp["r3"]["Q-01"]
    contracts = pytest.importorskip("bcc_review.contracts")
    for r in rs.values():
        contracts.validate(r)
        assert contracts.evidence_errors(r) == []


def test_fingerprint_ignores_ids_but_not_text_or_binding():
    r = build_answers_reports()["r2"]
    q = dict(Q_EVENT)
    base = H.question_fingerprint(r, q)
    assert H.question_fingerprint(r, {**q, "id": "Q-77"}) == base
    renamed = json.loads(json.dumps(r))
    for f in renamed["findings"]:
        if f["id"] == "F-008":
            f["id"] = "F-108"
    assert H.question_fingerprint(renamed, {**q, "finding_ids": ["F-108"]}) == base, "перенумерация замечаний"
    assert H.question_fingerprint(r, {**q, "prompt": q["prompt"] + " Уточните."}) != base
    assert H.question_fingerprint(r, {**q, "finding_ids": ["F-007"]}) != base, "другая привязка"


# --------------------------------------------------------------------------- браузер


def test_browser_used_current_write_html(scenario):
    _, _, obs = scenario
    assert Path(obs["implementation"]).resolve() == (SRC / "bcc_review" / "exports" / "html.py").resolve()
    for step in ("step1", "step2", "step3", "legacy", "nostore"):
        assert obs[step]["problems"] == [] and obs[step]["requests"] == [], step


def test_step1_both_answers_saved_by_question_fingerprint(scenario):
    _, rs, obs = scenario
    ans = obs["answers"]
    assert values(obs["step1"]["questions_before_close"]) == {"Q-01": ans["month"], "Q-02": ans["event"]}
    stored = obs["step1"]["storage"][H.answers_storage_key(rs["r1"]["document"]["id"])]
    by_fp = {fp: e["answer"] for fp, e in stored["entries"].items()}
    assert by_fp == {
        H.question_fingerprint(rs["r1"], Q_MONTH): ans["month"],
        H.question_fingerprint(rs["r1"], Q_EVENT): ans["event"],
    }


def test_step2_new_q01_empty_old_answer_kept_identical_restored(scenario):
    _, rs, obs = scenario
    ans = obs["answers"]
    s2 = obs["step2"]
    assert values(s2["questions_loaded"]) == {"Q-01": "", "Q-02": ans["event"]}
    assert [(i["qid"], i["kind"], i["answer"]) for i in s2["panel"]["items"]] == [("Q-01", "other-question", ans["month"])]
    assert Q_MONTH["prompt"] in s2["panel"]["text"]
    assert "не подставлены" in s2["status"]
    key = H.answers_storage_key(rs["r2"]["document"]["id"])
    month_fp = H.question_fingerprint(rs["r1"], Q_MONTH)
    for snap in (s2["storage_on_load"], s2["storage_after_push"]):
        assert snap[key]["entries"][month_fp]["answer"] == ans["month"], "ответ про месяц не должен теряться"
    after = {e["qid"] + "@" + e["run_id"]: e["answer"] for e in s2["storage_after_push"][key]["entries"].values()}
    assert after == {
        "Q-01@p13-answers-run-1": ans["month"],
        "Q-02@p13-answers-run-2": ans["event"],
        "Q-01@p13-answers-run-2": ans["push"],
    }


def test_step3_renumbered_identical_question_restored(scenario):
    _, _, obs = scenario
    ans = obs["answers"]
    assert values(obs["step3"]["questions_loaded"]) == {"Q-01": ans["push"], "Q-02": "", "Q-03": ans["event"]}


def test_legacy_qid_only_draft_is_explicit_and_kept(scenario):
    _, rs, obs = scenario
    lg = obs["legacy"]
    assert values(lg["questions_loaded"]) == {"Q-01": "", "Q-02": ""}
    assert [(i["qid"], i["kind"], i["answer"]) for i in lg["panel"]["items"]] == [("Q-01", "legacy", obs["answers"]["legacy"])]
    assert "старого формата" in lg["status"] and "не подставлен" in lg["status"]
    sha = rs["r2"]["document"]["id"]
    assert lg["storage_after_save"][H.legacy_answers_storage_key(sha)] == lg["injected"], "старый черновик не тронут"
    assert H.answers_storage_key(sha) in lg["storage_after_save"]


def test_no_storage_page_works_keyboard_reaches_both_quotes(scenario):
    _, rs, obs = scenario
    ns = obs["nostore"]
    assert "хранилище недоступно" in ns["status_on_load"]
    kb = ns["keyboard"]
    assert kb["selected"] == "F-001"
    w = next(f for f in rs["r2"]["findings"] if f["id"] == "F-001")["witness"]
    for step, ev in zip(kb["steps"], (w["evidence_a"], w["evidence_b"])):
        assert step["inDoc"]["block"] == ev["block_id"] and int(step["inDoc"]["cp"].split(":")[0]) == ev["start"]
        assert step["inDoc"]["text"] == ev["quote"]
        assert step["back"]["side"] == step["side"] and step["back"]["inF1"]
        assert step["selectedAfter"] == "F-001"


# --------------------------------------------------------------------------- выгрузка


def _expected_exports(rs, ans):
    return {
        "export_as_loaded": ("step2", {"Q-02": ans["event"]}),
        "export": ("step2", {"Q-01": ans["push"], "Q-02": ans["event"]}),
        "nostore": ("nostore", {"Q-01": ans["nostore"]}),
    }


def test_exports_match_python_format_and_reference_parser(scenario):
    _, rs, obs = scenario
    ans = obs["answers"]
    for key, (step, typed) in _expected_exports(rs, ans).items():
        exp = obs[step]["export"] if key == "nostore" else obs[step][key]
        parsed = H.parse_answers_markdown(exp["text"])
        assert exp["text"] == H.answers_markdown(rs["r2"], typed, exported_at=parsed["meta"]["exported_at"]), key
        assert parsed["meta"]["source_sha256"] == rs["r2"]["document"]["id"]
        assert parsed["meta"]["report_run_id"] == "p13-answers-run-2"
        assert parsed["answers"] == {q: H.answer_one_line(a) for q, a in typed.items()}
        for qid in parsed["answers"]:
            q = next(x for x in rs["r2"]["questions"] if x["id"] == qid)
            assert parsed["fingerprints"][qid] == H.question_fingerprint(rs["r2"], q)
        assert ans["month"].split("\n")[0] not in exp["text"], "ответ про месяц не должен уйти в выгрузку r2"


def test_exports_read_by_published_parse_answers(scenario):
    work, rs, obs = scenario
    slot = published_parse_answers()
    if slot is None:
        pytest.skip("опубликованного parse_answers (bcc_review.runtime) нет в этой копии; стык — в копии bcc/integration")
    ans = obs["answers"]
    doc = rs["r2"]["document"]
    report = {"implementation": slot.label}
    for key, (step, typed) in _expected_exports(rs, ans).items():
        exp = obs[step]["export"] if key == "nostore" else obs[step][key]
        out = slot.func(exp["file"], doc)
        out = {"decisions": out, "warnings": []} if isinstance(out, list) else out
        assert out["warnings"] == [], out["warnings"]
        pairs = {d["question_id"]: d["answer"] for d in out["decisions"]}
        assert pairs == {q: H.answer_one_line(a) for q, a in typed.items()}, key
        assert {d["source_sha256"] for d in out["decisions"]} <= {doc["id"]}
        report[key] = out["decisions"]
    (work / "published-parse.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
