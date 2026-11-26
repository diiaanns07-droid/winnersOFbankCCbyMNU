"""Два вопроса к разным сторонам одного противоречия: ответ на один, второй открыт.

Вход ``fixtures/commission_tz.md``: КП-1 «Перевод … выполняется без комиссии.» (строка 5)
↔ Т-1 «взимается комиссия 0,5% от суммы перевода» (строка 9); критерий приёмки (строка 15)
ожидает «Списано 10 000 ₸, комиссия 0 ₸». Движок (mock-провайдер, резервы Max для этапов
individual/set) объединяет обе опоры в одну находку; №08 задаёт по вопросу на каждую сторону.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("bcc_review.engine", reason="движок bcc/integration не подключён")
pytest.importorskip("jsonschema")

FIX = Path(__file__).parent / "fixtures"
SRC = Path(__file__).resolve().parents[2] / "src"
SOURCE_SHA = "cbbc38cae3615f5482d87d0d77974c2641856623540e3baa2988ed888cac8e91"
KP1 = "Перевод между своими счетами выполняется без комиссии."
T1 = "взимается комиссия 0,5% от суммы перевода"
T1_LINE_BEFORE = "* **Т-1.** За перевод между своими счетами взимается комиссия 0,5% от суммы перевода."
T1_LINE_AFTER = "* **Т-1.** За перевод между своими счетами комиссия не взимается."


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cli(cwd: Path, *args: str, module: str = "bcc_review") -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(SRC), BCC_FORCE_FALLBACK="review_individual,review_set")
    env.pop("ANTHROPIC_API_KEY", None)
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=300)


def review(cwd: Path, src: str, run_id: str, script: str = "mock_commission.json", *extra: str) -> dict:
    r = cli(cwd, src, f"{run_id}.md", "--provider", "mock", "--mock-script", str(FIX / script), "--no-cache",
            "-q", "--run-id", run_id, *extra)
    assert r.returncode == 0, r.stderr
    return json.loads((cwd / f"{run_id}.json").read_text(encoding="utf-8"))


def answers_file(cwd: Path, report: str, answers: dict[str, str], name: str = "answers.md") -> Path:
    from bcc_review.decisions.__main__ import fill_answers

    r = cli(cwd, "questions", "commission_tz.md", report, "-o", "questions.md", module="bcc_review.decisions")
    assert r.returncode == 0, r.stderr
    text = fill_answers((cwd / "questions.md").read_text(encoding="utf-8"), answers, label=None)
    (cwd / name).write_text(text, encoding="utf-8", newline="\n")
    return cwd / name


def revisions(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("commission_tz.rev-*"))


@pytest.fixture
def case(tmp_path):
    shutil.copyfile(FIX / "commission_tz.md", tmp_path / "commission_tz.md")
    assert sha(tmp_path / "commission_tz.md") == SOURCE_SHA
    return tmp_path


# --------------------------------------------------------------------------- вопросы


def test_two_questions_each_name_their_phrase_section_and_acceptance(case):
    rep = review(case, "commission_tz.md", "p08-comm-r1")
    assert [f["id"] for f in rep["findings"] if f["severity"] == "critical"] == ["F-001"]  # одно противоречие
    q1, q2 = rep["questions"]
    assert (q1["side"]["quote"], q2["side"]["quote"]) == (KP1, T1)
    assert q1["finding_ids"] == q2["finding_ids"] == ["F-001"]
    assert (q1["counterpart_ids"], q2["counterpart_ids"]) == (["Q-02"], ["Q-01"])
    assert [o for o in q2["options"]] == [
        "A. Да, тариф 0,5% верен — оставить — Перевод 10 000 ₸: списано 10 000 ₸ и комиссия 0,5% от суммы "
        f"перевода. · текст не меняется: «{T1}» (Тарифы, строка 9)",
        "B. Нет — комиссии нет — Перевод 10 000 ₸: списано 10 000 ₸, комиссия 0 ₸. · Правка [b0005]: "
        f"«{T1}» → «комиссия не взимается» (Тарифы, строка 9)",
    ]
    card = answers_file(case, "p08-comm-r1.json", {}).read_text(encoding="utf-8")
    q2_card = card[card.index("## Q-02"):]
    assert "**Сторона противоречия.** Этот вопрос — только о фразе «взимается комиссия 0,5% от суммы перевода»" in q2_card
    assert "Вторая сторона противоречия — Q-01." in q2_card
    assert f"**Цель правки:** «{T1}» — строка 9 · блок b0005" in q2_card
    assert "— другая сторона противоречия" in q2_card
    assert (f"Что изменится в тексте: ничего — фраза «{T1}» (раздел «Тарифы», строка 9) остаётся как есть"
            in q2_card)
    assert (f"Что изменится в тексте: раздел «Тарифы», строка 9: было «{T1}» → стало «комиссия не взимается»"
            in q2_card)
    assert ("Влияние на приёмку: критерий приёмки (строка 15) ожидает «Списано 10 000 ₸, комиссия 0 ₸» — "
            "с этим вариантом он расходится, его нужно переписать") in q2_card
    assert ("Влияние на приёмку: критерий приёмки (строка 15) «Списано 10 000 ₸, комиссия 0 ₸» совпадает "
            "с результатом варианта — тест не меняется") in q2_card
    q1_card = card[card.index("## Q-01"):card.index("## Q-02")]
    assert ("Что изменится в тексте: раздел «Функциональные требования», строка 5: было «выполняется без "
            "комиссии» → стало «выполняется с комиссией по тарифу Т-1»") in q1_card


# --------------------------------------------------------------------------- ответ на одну сторону


@pytest.mark.parametrize("other_answer, other_status", [("", None), ("нужно уточнить", "needs_clarification")])
def test_answer_one_side_other_stays_open(case, other_answer, other_status):
    review(case, "commission_tz.md", "p08-comm-r1")
    answers_file(case, "p08-comm-r1.json", {"Q-01": other_answer, "Q-02": "B"})
    rep = review(case, "commission_tz.md", "p08-comm-r2", "mock_commission_after.json",
                 "--answers", "answers.md", "--compare", "p08-comm-r1.json")
    rev = case / "commission_tz.rev-p08-comm-r2.md"
    assert revisions(case) == [rev.name, "commission_tz.rev-p08-comm-r2.revision.json"]
    # повторное чтение созданного файла и сравнение с исходником
    a = (case / "commission_tz.md").read_text(encoding="utf-8").split("\n")
    b = rev.read_text(encoding="utf-8").split("\n")
    assert len(a) == len(b) and [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y] == [9]
    assert (a[8], b[8]) == (T1_LINE_BEFORE, T1_LINE_AFTER)
    assert b[4] == f"* **КП-1.** {KP1}"  # вторая сторона не тронута
    assert sha(case / "commission_tz.md") == SOURCE_SHA
    assert rep["document"]["id"] == rep["run"]["source_sha256"] == sha(rev)
    assert rep["run"]["revision_of"] == SOURCE_SHA and rep["run"]["source_name"] == rev.name

    by_q = {d["question_id"]: d for d in rep["decisions"]}
    assert by_q["Q-02"]["answer"] == "B" and by_q["Q-02"]["decision_status"] == "accepted"
    assert [(e["block_id"], e["old"], e["new"]) for e in by_q["Q-02"]["edits"]] == [
        ("b0005", T1, "комиссия не взимается")]
    if other_status is None:
        assert "Q-01" not in by_q  # пустой ответ — решения нет
    else:
        assert by_q["Q-01"]["decision_status"] == other_status and by_q["Q-01"]["edits"] == []
        assert any("[needs_clarification] Q-01" in w["message"] for w in rep["warnings"] if isinstance(w, dict))

    from bcc_review.decisions.patches import question_statuses

    st = {r["question_id"]: r for r in question_statuses(case / "p08-comm-r1.json", case / "p08-comm-r2.json")}
    assert st["Q-02"]["text_state"] == "applied_not_verified"
    assert st["Q-01"]["text_state"] == "unchanged"
    assert st["Q-01"]["decision_status"] == (other_status or "open")
    m = json.loads((case / "commission_tz.rev-p08-comm-r2.revision.json").read_text(encoding="utf-8"))
    mq = {q["id"]: q for q in m["questions"]}
    assert m["status"] == "applied_not_verified" and mq["Q-02"]["patch_state"] == "applied"
    assert mq["Q-01"]["patch_state"] == "open"


# --------------------------------------------------------------------------- повторный импорт


def test_reimport_of_same_answers_does_not_duplicate_replacement(case):
    review(case, "commission_tz.md", "p08-comm-r1")
    answers = answers_file(case, "p08-comm-r1.json", {"Q-01": "нужно уточнить", "Q-02": "B"})
    args = ("--answers", "answers.md", "--compare", "p08-comm-r1.json")
    review(case, "commission_tz.md", "p08-comm-r2", "mock_commission_after.json", *args)
    review(case, "commission_tz.md", "p08-comm-r2b", "mock_commission_after.json", *args)
    rev = case / "commission_tz.rev-p08-comm-r2.md"
    assert rev.read_bytes() == (case / "commission_tz.rev-p08-comm-r2b.md").read_bytes()
    text = rev.read_text(encoding="utf-8")
    assert text.count("комиссия не взимается") == 1 and "0,5%" not in text
    before = {n: sha(case / n) for n in revisions(case)}

    # та же редакция на входе, тот же answers.md — ответы к другой версии
    r3 = review(case, rev.name, "p08-comm-r3", "mock_commission_after.json", "--answers", "answers.md",
                "--compare", "p08-comm-r2.json")
    assert any("другой редакции" in w["message"] for w in r3["warnings"] if isinstance(w, dict))
    # ответы перепривязаны к SHA редакции — защита по тексту, а не по хешу
    rebound = case / "answers_rebound.md"
    rebound.write_text(answers.read_text(encoding="utf-8").replace(SOURCE_SHA, sha(rev)), encoding="utf-8",
                       newline="\n")
    r4 = review(case, rev.name, "p08-comm-r4", "mock_commission_after.json", "--answers", rebound.name,
                "--compare", "p08-comm-r1.json")
    msgs = [w["message"] for w in r4["warnings"] if isinstance(w, dict) and w.get("stage") == "answers"]
    assert any(m.startswith("[already_applied] Q-02") for m in msgs), msgs
    for r in (r3, r4):
        assert next(s for s in r["run"]["stages"] if s["name"] == "answers")["status"] == "partial"
    assert {n: sha(case / n) for n in revisions(case)} == before  # ничего нового не записано
    assert sha(case / "commission_tz.md") == SOURCE_SHA


# --------------------------------------------------------------------------- без модели


def test_side_questions_without_model_and_owner_wording(case):
    script = json.loads((FIX / "mock_commission.json").read_text(encoding="utf-8"))
    script.pop("clarify")
    (case / "no_clarify.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    r = cli(case, "commission_tz.md", "r1.md", "--provider", "mock", "--mock-script", str(case / "no_clarify.json"),
            "--no-cache", "-q", "--run-id", "p08-comm-rules")
    assert r.returncode == 0, r.stderr
    rep = json.loads((case / "r1.json").read_text(encoding="utf-8"))
    q1, q2 = rep["questions"]
    assert q1["origin"] == q2["origin"] == "rule" and (q1["side"]["quote"], q2["side"]["quote"]) == (KP1, T1)
    assert "меняется по «Формулировка:»" in q2["options"][1]
    answers_file(case, "r1.json", {"Q-02": "Комиссии нет.\nФормулировка: За перевод между своими счетами комиссия "
                                           "не взимается."})
    review(case, "commission_tz.md", "p08-comm-r2", "mock_commission_after.json", "--answers", "answers.md",
           "--compare", "r1.json")
    b = (case / "commission_tz.rev-p08-comm-r2.md").read_text(encoding="utf-8").split("\n")
    a = (case / "commission_tz.md").read_text(encoding="utf-8").split("\n")
    assert [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y] == [9]  # «Формулировка» меняет свою сторону
    assert b[8] == T1_LINE_AFTER


# --------------------------------------------------------------------------- модульные случаи


@pytest.mark.parametrize("answer", ["нужно уточнить", "Нужно уточнить у казначейства", "надо уточнить",
                                    "требует уточнения", "уточним позже", "не знаю"])
def test_clarify_answers_keep_question_open(answer):
    from bcc_review.decisions import Decision, interpret, propose_patch

    assert interpret(answer)[0] == "clarify"
    d = Decision.from_answer("Q-01", "a" * 64, answer)
    assert (d.status, d.decision_status) == ("open", "needs_clarification")
    p = propose_patch({"id": "a" * 64, "title": "t", "format": "markdown", "blocks": [], "warnings": []}, None, d)
    assert p["state"] == "open" and p["edits"] == [] and p["warnings"][0].startswith("[needs_clarification]")


def test_appending_edit_is_not_applied_twice():
    from bcc_review.decisions import Decision, propose_patch
    from bcc_review.decisions._doc import markdown_to_document

    sentence = "Заёмщик подаёт заявку в мобильном банке."
    added = sentence + " Минимальная сумма — 10 000 ₸."
    v1 = markdown_to_document(f"# T\n\n* {sentence}\n".encode("utf-8"))
    v2 = markdown_to_document(f"# T\n\n* {added}\n".encode("utf-8"))
    answer = f"Минимум 10 000 ₸.\nПравка: «{sentence}» → «{added}»"
    first = propose_patch(v1, None, Decision.from_answer("Q-01", v1["id"], answer))
    assert first["state"] == "proposed"
    again = propose_patch(v2, None, Decision.from_answer("Q-01", v2["id"], answer))  # те же ответы к новой версии
    assert again["state"] == "already_applied" and again["edits"] == []
    e = dict(first["edits"][0], source_sha256=v2["id"])  # правка с координатами по старой версии
    from bcc_review.decisions.patches import edit_state
    from bcc_review.decisions._doc import DocView

    assert edit_state(DocView(v2), e) == "already_applied"


def test_side_split_only_for_inconsistency():
    from bcc_review.decisions import build_questions
    from bcc_review.decisions._doc import markdown_to_document

    doc = markdown_to_document("# T\n\n## А\n\n* Время после 18:00.\n\n## Б\n\n* Исполнение в 19:00.\n".encode("utf-8"))
    ev = lambda q: next(  # noqa: E731
        {"block_id": b["id"], "start": b["text"].index(q), "end": b["text"].index(q) + len(q), "quote": q}
        for b in doc["blocks"] if q in b["text"])
    base = {"id": "F-1", "scope": "set", "severity": "major", "status": "confirmed", "title": "t", "impact": "i",
            "req_ids": [], "evidence": [ev("после 18:00"), ev("в 19:00")]}
    tz = build_questions(doc, [dict(base, kind="ambiguity", criterion="unambiguous")])
    assert len(tz) == 1 and tz[0].side is None   # неоднозначность в двух местах — один вопрос
    inc = build_questions(doc, [dict(base, kind="incorrect", criterion="set_consistent")])
    assert len(inc) == 2 and {q.side["quote"] for q in inc} == {"после 18:00", "в 19:00"}
    assert re.match(r"Q-0[12]", inc[0].counterpart_ids[0])


# --------------------------------------------------------------------------- пример для команды


def test_committed_two_sided_example_is_reproducible(case):
    """examples/team_answers/two_sided: те же команды дают те же вопросы и ту же редакцию."""
    ex = Path(__file__).resolve().parents[2] / "examples" / "team_answers" / "two_sided"
    out = case / "out"
    out.mkdir()

    def run(name: str, script: str, *extra: str) -> None:  # ровно команды README
        r = cli(case, "commission_tz.md", f"out/{name}.md", "--provider", "mock", "--mock-script", str(FIX / script),
                "--no-cache", "--run-id", name, *extra)
        assert r.returncode == 0, r.stderr

    run("p08-comm-r1", "mock_commission.json")
    r = cli(case, "questions", "commission_tz.md", "out/p08-comm-r1.json", "-o", "out/questions.md",
            module="bcc_review.decisions")
    assert r.returncode == 0, r.stderr
    assert (out / "questions.md").read_bytes() == (ex / "questions.md").read_bytes()
    shutil.copyfile(ex / "answers.md", case / "answers.md")
    assert "Демонстрационные ответы команды" in (case / "answers.md").read_text(encoding="utf-8")
    run("p08-comm-r2", "mock_commission_after.json", "--answers", "answers.md", "--compare", "out/p08-comm-r1.json")
    rev = out / "commission_tz.rev-p08-comm-r2.md"
    assert rev.read_bytes() == (ex / rev.name).read_bytes()
    assert sha(rev) == "cc57fc9e0d0b8dd25ee88b5af879e5728424ada9b737c8340158aed4d7b4fd8b"
    st = cli(case, "status", "out/p08-comm-r1.json", "out/p08-comm-r2.json", module="bcc_review.decisions")
    assert st.stdout == (ex / "status.md").read_text(encoding="utf-8")
