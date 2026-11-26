"""Решение принято ≠ замечание закрыто: закрытие только по повторному анализу
реально записанной редакции. Второй независимый конфликт остаётся для №09."""
from __future__ import annotations

import json
from pathlib import Path

from bcc_review.decisions import accept_user_revision, apply_answers, closure_status, parse_answers
from bcc_review.decisions._demo import EXAMPLES_DIR, recheck
from bcc_review.decisions._doc import load_markdown
from bcc_review.decisions.__main__ import run_demo


def _apply(doc, questions, findings, src_path, out, answers):
    res = apply_answers(doc, questions, answers, findings=findings, output_md=out, source=src_path)
    return res, load_markdown(res["revision"])  # повторное чтение файла с диска


def test_baseline_recheck_sees_all_four_issues(doc):
    assert [f["id"] for f in recheck(doc)] == ["N-01", "N-02", "N-03", "N-04"]


def test_only_chosen_ambiguity_disappears_and_second_conflict_stays(doc, findings, questions, src_path, tmp_path):
    res, rev = _apply(doc, questions, findings, src_path, tmp_path / "rev_B.md", EXAMPLES_DIR / "answers_team_B.md")
    after = recheck(rev)
    assert [f["id"] for f in after] == ["N-02", "N-03", "N-04"]  # пропала только комиссия
    sched = after[0]
    assert {e["quote"] for e in sched["evidence"]} == {
        "платёж списывается в следующий рабочий день", "Платёж списан 14 марта, в пятницу"}
    c = closure_status(res["manifest"], rev, after)
    assert c["verified_on_revision"] is True
    rows = {r["question_id"]: r for r in c["questions"]}
    assert rows["Q-01"]["fix_status"] == "closed_after_reanalysis"
    assert rows["Q-02"]["fix_status"] == "open_still_present" and rows["Q-02"]["matched_finding_ids"] == ["N-02"]
    assert rows["Q-03"]["decision_status"] == "accepted_needs_wording"
    assert rows["Q-03"]["fix_status"] == "open_still_present"


def test_decision_accepted_is_not_closure(doc, findings, questions, src_path, tmp_path):
    res, rev = _apply(doc, questions, findings, src_path, tmp_path / "rev_A.md", EXAMPLES_DIR / "answers_team_A.md")
    st = {s["question_id"]: s for s in res["statuses"]}
    assert st["Q-01"]["decision_status"] == "accepted" and st["Q-01"]["fix_status"] == "applied_not_verified"
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["status"] == "applied_not_verified"
    # «повторный анализ» не той версии (исходник) — закрытие не присваивается
    wrong = closure_status(manifest, doc, recheck(doc))
    assert wrong["verified_on_revision"] is False
    assert {r["fix_status"] for r in wrong["questions"] if r["decision_status"] == "accepted"} == {"applied_unverified"}
    assert wrong["warnings"][0].startswith("[not_reanalyzed]")
    # анализ реально изменённой версии
    good = closure_status(manifest, rev, recheck(rev))
    rows = {r["question_id"]: r["fix_status"] for r in good["questions"]}
    assert rows == {"Q-01": "closed_after_reanalysis", "Q-02": "open_still_present",
                    "Q-03": "closed_after_reanalysis", "Q-04": "closed_after_reanalysis"}


def test_owner_wording_that_keeps_conflict_is_not_closed(doc, findings, questions, src_path, tmp_path):
    text = (f"source_sha256: {doc['id']}\n## Q-01\nОтвет: берём тариф\n"
            "Формулировка: При досрочном погашении в первые 6 месяцев взимается комиссия 1% от суммы "
            "досрочного погашения.\n")
    res, rev = _apply(doc, questions, findings, src_path, tmp_path / "r.md",
                      parse_answers(text, questions=questions))
    assert res["results"]["Q-01"]["state"] == "proposed"
    c = closure_status(res["manifest"], rev, recheck(rev))
    q1 = next(r for r in c["questions"] if r["question_id"] == "Q-01")
    assert q1["fix_status"] == "still_present" and q1["matched_finding_ids"] == ["N-01"]


def test_user_supplied_new_version(doc, findings, questions, src_path, tmp_path):
    user = tmp_path / "loan_v2.md"
    user.write_text(src_path.read_text(encoding="utf-8").replace(
        "ближайший банковский день", "ближайший рабочий день"), encoding="utf-8")
    aset = parse_answers(f"source_sha256: {doc['id']}\n## Q-04\nОтвет: A\n", questions=questions)
    res = apply_answers(doc, questions, aset, findings=findings)  # без output_md: только решения
    mp = accept_user_revision(doc, user, questions=questions, results=res["results"], decisions=aset.decisions)
    m = json.loads(mp.read_text(encoding="utf-8"))
    assert m["revision"]["mode"] == "user_supplied"
    new = load_markdown(user)
    rows = {r["question_id"]: r["fix_status"] for r in closure_status(m, new, recheck(new))["questions"]}
    assert rows["Q-04"] == "closed_after_reanalysis" and rows["Q-01"] == "open_still_present"


def test_committed_examples_are_reproducible(tmp_path):
    """№18 повторяет: python -m bcc_review.decisions demo --out DIR даёт те же файлы."""
    run_demo(tmp_path)
    gen = EXAMPLES_DIR / "generated"
    for name in ("questions.md", "revision_A.md", "revision_B.md", "revision_A.revision.json",
                 "revision_B.revision.json", "revision_A.apply.md", "revision_B.apply.md",
                 "revision_A.closure.json", "revision_B.closure.json", "report_before.json"):
        assert (tmp_path / name).read_bytes() == (gen / name).read_bytes(), name
