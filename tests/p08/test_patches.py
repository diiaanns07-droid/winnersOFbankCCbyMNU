"""Правки «было → стало»: предусловия, отложить, повтор, устаревший хеш, коллизии,
вымышленные значения, бинарный исходник."""
from __future__ import annotations

import json

import pytest

from bcc_review.decisions import (
    AlreadyAppliedError, Decision, EditCollisionError, PatchError, StaleSourceError, apply_answers,
    find_collisions, parse_answers, propose_patch, write_revision,
)
from bcc_review.decisions._demo import EXAMPLES_DIR
from bcc_review.decisions._doc import DocView, invented_values, load_markdown, sha256_file
from bcc_review.decisions.clarify import Option, Question


def _dec(doc, qid, answer):
    return Decision.from_answer(qid, doc["id"], answer)


# --- доказательство 1: два ответа -> два результата и две разные правки ------------------


def test_two_answers_give_two_results_and_two_patches(doc, findings, questions):
    q = questions[0]  # комиссия
    d = DocView(doc)
    pa = propose_patch(doc, findings[0], _dec(doc, q.id, "A"), question=q)
    pb = propose_patch(doc, findings[0], _dec(doc, q.id, "B"), question=q)
    assert pa["state"] == pb["state"] == "proposed"
    assert pa["expected_result"] != pb["expected_result"]
    assert "комиссия 0 ₸" in pa["expected_result"] and "1%" in pb["expected_result"]
    sig = lambda p: {(e["block_id"], e["start"], e["end"], e["new"]) for e in p["edits"]}
    assert sig(pa) and sig(pb) and sig(pa).isdisjoint(sig(pb))
    for e in pa["edits"] + pb["edits"]:
        assert d.block(e["block_id"]).text[e["start"]:e["end"]] == e["old"]  # точная старая подстрока
        assert e["source_sha256"] == doc["id"] and e["question_id"] == q.id
    assert [e["old"] for e in pb["edits"]] == ["Комиссия за досрочное погашение не взимается.", "комиссия 0 ₸"]


def test_two_answers_give_two_different_revisions(doc, findings, questions, src_path, tmp_path):
    outs = {}
    for v in ("A", "B"):
        res = apply_answers(doc, questions, EXAMPLES_DIR / f"answers_team_{v}.md", findings=findings,
                            output_md=tmp_path / f"rev_{v}.md", source=src_path)
        outs[v] = (tmp_path / f"rev_{v}.md").read_text(encoding="utf-8")
        assert res["statuses"][0]["fix_status"] == "applied_not_verified"
    assert outs["A"] != outs["B"]
    assert "комиссия 0 ₸" in outs["A"] and "Тарифы\n\nКомиссия за досрочное погашение не взимается." in outs["A"]
    assert "комиссия 1% от суммы досрочного погашения |" in outs["B"]


# --- доказательство 2: отложить, повтор, смена хеша -------------------------------------


def test_defer_keeps_document_and_question_open(doc, findings, questions, src_path, tmp_path):
    before = src_path.read_bytes()
    text = f"source_sha256: {doc['id']}\n## Q-01\nОтвет: отложить\n## Q-02\nОтвет:\n"
    out = tmp_path / "rev.md"
    res = apply_answers(doc, questions, parse_answers(text, questions=questions), findings=findings,
                        output_md=out, source=src_path)
    assert res["results"]["Q-01"]["state"] == "deferred" and res["results"]["Q-01"]["edits"] == []
    assert res["results"]["Q-02"]["state"] == "open"
    assert res["revision"] is None and not out.exists()
    assert any(w.startswith("[no_revision]") for w in res["warnings"])
    assert src_path.read_bytes() == before
    st = {s["question_id"]: s for s in res["statuses"]}
    assert st["Q-01"]["decision_status"] == "deferred" and st["Q-01"]["fix_status"] == "not_applied"
    assert st["Q-02"]["decision_status"] == "open"


def test_reapply_and_stale_hash_are_deterministic(doc, findings, questions, src_path, tmp_path):
    q = questions[0]
    first = propose_patch(doc, findings[0], _dec(doc, q.id, "A"), question=q)
    out = write_revision(doc, first["edits"], tmp_path / "rev.md", source=src_path)
    rev = load_markdown(out)
    assert rev["id"] == sha256_file(out) != doc["id"]

    # тот же answers.md (старый хеш) к новой редакции -> stale
    stale = propose_patch(rev, findings[0], _dec(doc, q.id, "A"), question=q)
    assert stale["state"] == "stale" and stale["edits"] == []
    assert stale["warnings"][0].startswith("[stale_source]")

    # хеш в ответе «подогнали» под новую версию -> правка уже в тексте
    q_rev = Question.from_dict(q.to_dict())
    for o in q_rev.options:
        for e in o.edits:
            e["source_sha256"] = rev["id"]
            e["block_id"] = next(b["id"] for b in rev["blocks"] if b["id"] == e["block_id"])
    again = propose_patch(rev, findings[0], Decision.from_answer(q.id, rev["id"], "A"), question=q_rev)
    assert again["state"] == "already_applied" and again["edits"] == []

    # прямой повтор write_revision: на редакции -> StaleSourceError; без хеша -> AlreadyAppliedError
    with pytest.raises(StaleSourceError):
        write_revision(rev, first["edits"], tmp_path / "rev2.md")
    no_sha = [{k: v for k, v in e.items() if k != "source_sha256"} for e in first["edits"]]
    with pytest.raises(AlreadyAppliedError):
        write_revision(rev, no_sha, tmp_path / "rev2.md")
    assert not (tmp_path / "rev2.md").exists()


def test_stale_answers_file_changes_nothing(doc, findings, questions, src_path, tmp_path):
    text = f"source_sha256: {'0' * 64}\n## Q-01\nОтвет: A\n"
    res = apply_answers(doc, questions, text, findings=findings, output_md=tmp_path / "r.md", source=src_path)
    assert res["results"]["Q-01"]["state"] == "stale" and res["revision"] is None
    assert any(w.startswith("[stale_answers]") for w in res["warnings"])


def test_source_file_changed_after_analysis_is_rejected(doc, findings, questions, src_path, tmp_path):
    p = propose_patch(doc, findings[0], _dec(doc, "Q-01", "A"), question=questions[0])
    src_path.write_text(src_path.read_text(encoding="utf-8") + "\nдописано\n", encoding="utf-8")
    with pytest.raises(StaleSourceError):
        write_revision(doc, p["edits"], tmp_path / "r.md", source=src_path)


# --- коллизии ---------------------------------------------------------------------------


def _rival_question(doc, questions):
    """Второй вопрос, вариант которого переписывает тот же фрагмент ДП-2."""
    d = DocView(doc)
    b = next(b for b in d.blocks if "не взимается" in b.text and b.kind == "list_item")
    s = b.text.index("Комиссия за досрочное")
    old = b.text[s:s + len("Комиссия за досрочное погашение не взимается.")]
    edit = {"block_id": b.id, "start": s, "end": s + len(old), "old": old,
            "new": "Комиссия за досрочное погашение взимается по договору.",
            "source_sha256": doc["id"], "question_id": "Q-05"}
    return Question(id="Q-05", finding_ids=["F-99"], prompt="Тестовый конкурирующий вопрос",
                    options=[Option("A", "x", "x", "исход 1", edits=[edit]), Option("B", "y", "y", "исход 2")],
                    affected_req_ids=["R-02"], source_sha256=doc["id"])


def test_collision_is_reported_with_fragments_and_rest_is_applied(doc, findings, questions, src_path, tmp_path):
    qs = questions + [_rival_question(doc, questions)]
    text = f"source_sha256: {doc['id']}\n## Q-01\nОтвет: B\n## Q-04\nОтвет: A\n## Q-05\nОтвет: A\n"
    res = apply_answers(doc, qs, text, findings=findings, output_md=tmp_path / "r.md", source=src_path)
    assert res["results"]["Q-01"]["state"] == res["results"]["Q-05"]["state"] == "collision"
    assert len(res["collision_messages"]) == 1
    msg = res["collision_messages"][0]
    assert "Q-01" in msg and "Q-05" in msg and "«Комиссия за досрочное погашение не взимается.»" in msg
    assert "строка 19" in msg
    assert res["results"]["Q-04"]["state"] == "proposed"  # независимая правка применена
    rev = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "ближайший рабочий день" in rev and "не взимается." in rev and "по договору" not in rev


def test_write_revision_refuses_colliding_edits(doc, questions, tmp_path):
    rival = _rival_question(doc, questions).options[0].edits[0]
    mine = questions[0].option("B").edits[0]
    assert find_collisions([mine, rival])
    with pytest.raises(EditCollisionError) as exc:
        write_revision(doc, [mine, rival], tmp_path / "r.md")
    assert exc.value.collisions and "Нужно решение владельца" in str(exc.value)
    assert not (tmp_path / "r.md").exists()


# --- вымышленные значения и свои ответы --------------------------------------------------


def test_invented_limit_rejected_owner_value_accepted(doc, findings, questions):
    gap = next(q for q in questions if "F-05" in q.finding_ids)
    invented = propose_patch(doc, findings[4], _dec(doc, gap.id, "B"), question=gap)
    assert invented["state"] == "needs_wording" and invented["edits"] == []
    assert "50 000 ₸" in invented["warnings"][0]
    owner = propose_patch(doc, findings[4], _dec(
        doc, gap.id, "Минимум 10 000 ₸.\nФормулировка: Минимальная сумма частичного досрочного погашения — "
                     "10 000 ₸."), question=gap)
    assert owner["state"] == "proposed"
    e = owner["edits"][0]
    assert e["old"].startswith("Заёмщик подаёт заявку") and e["new"].endswith("— 10 000 ₸.")
    assert e["new"].startswith(e["old"])  # пропуск: формулировка добавляется после предложения
    # значение, которое вписал сам владелец, — его решение, а не вымысел
    own_sla = propose_patch(doc, findings[4], _dec(
        doc, gap.id, "Формулировка: Заявка исполняется за 2 рабочих дня."), question=gap)
    assert own_sla["state"] == "proposed"
    # тот же SLA в варианте модели при ответе «A» — вымысел, в редакцию не попадает
    q_llm = Question.from_dict(gap.to_dict())
    q_llm.option("A").edits[0]["new"] = q_llm.option("A").edits[0]["old"] + " Заявка исполняется за 2 рабочих дня."
    sla = propose_patch(doc, findings[4], _dec(doc, gap.id, "A"), question=q_llm)
    assert sla["state"] == "needs_wording" and "2 рабочих дня" in sla["warnings"][-1]


def test_custom_without_wording_records_decision_only(doc, findings, questions):
    p = propose_patch(doc, findings[0], _dec(doc, "Q-01", "Комиссия только для кредитов до 2025 года"),
                      question=questions[0])
    assert p["state"] == "needs_wording" and p["edits"] == []
    assert p["expected_result"] == "Комиссия только для кредитов до 2025 года"


def test_custom_wording_replaces_whole_sentence(doc, findings, questions):
    bank = next(q for q in questions if "F-04" in q.finding_ids)
    p = propose_patch(doc, findings[3], _dec(
        doc, bank.id, "Формулировка: Списание по заявке выполняется на следующий рабочий день."), question=bank)
    assert p["state"] == "proposed"
    assert p["edits"][0]["old"] == "Списание по заявке выполняется в ближайший банковский день после подачи заявки."


def test_invalid_choice_and_missing_sha(doc, findings, questions):
    bad = propose_patch(doc, findings[0], _dec(doc, "Q-01", "D"), question=questions[0])
    assert bad["state"] == "invalid_choice"
    unbound = propose_patch(doc, findings[0], Decision.from_answer("Q-01", None, "A"), question=questions[0])
    assert unbound["state"] == "stale"


@pytest.mark.parametrize("new, old, allowed, bad", [
    ("в течение 6 рабочих дней", "", ["первые 6 месяцев"], ["6 рабочих дней"]),
    ("не более 1 000 000 ₸", "", ["до 1000000 ₸"], []),
    ("доступность 99,9%", "", ["документ без чисел"], ["99,9%"]),
    ("комиссия 1% от суммы", "", ["комиссия 1 %"], []),
    ("ДП-3 и ДП-5", "", ["ДП-3, ДП-5"], []),
    ("ответ за 500 мс", "ответ за 500 мс", [], []),
])
def test_invented_values(new, old, allowed, bad):
    assert invented_values(new, old, allowed) == bad


# --- перенос в исходник и текстовая редакция ----------------------------------------------


def test_markdown_patch_keeps_untouched_bytes(doc, findings, questions, src_path, tmp_path):
    p = propose_patch(doc, findings[0], _dec(doc, "Q-01", "B"), question=questions[0])
    out = write_revision(doc, p["edits"], tmp_path / "r.md", source=src_path)
    a = src_path.read_text(encoding="utf-8").splitlines()
    b = out.read_text(encoding="utf-8").splitlines()
    changed = [i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y]
    assert len(a) == len(b) and changed == [19, 32]
    assert b[18].startswith("* **ДП-2.** Комиссия за досрочное погашение взимается по разделу «Тарифы».")
    m = json.loads((tmp_path / "r.revision.json").read_text(encoding="utf-8"))
    assert m["status"] == "applied_not_verified" and m["revision"]["mode"] == "markdown_patch"
    assert m["base"]["sha256"] == doc["id"] and m["revision"]["sha256"] == sha256_file(out)
    assert m["base"]["source"] == "loan_tz.md"


@pytest.mark.parametrize("line, text, target, new, expected", [
    # подстрока повторяется в строке: правится именно второе вхождение
    ("| 200 000 ₸ | Исполнить | Списано 200 000 ₸ |", "200 000 ₸ | Исполнить | Списано 200 000 ₸",
     "второе", "199 000 ₸", "| 200 000 ₸ | Исполнить | Списано 199 000 ₸ |"),
    # правка затрагивает текст внутри **…**
    ("* **ДП-2.** Комиссия не взимается.", "ДП-2. Комиссия не взимается.", "ДП-2.", "ДП-7.",
     "* **ДП-7.** Комиссия не взимается."),
])
def test_alignment_maps_edit_to_exact_source_span(tmp_path, line, text, target, new, expected):
    from bcc_review.decisions._doc import sha256_bytes

    data = ("# T\n\n" + line + "\n").encode("utf-8")
    d = {"id": sha256_bytes(data), "title": "T", "format": "markdown", "warnings": [], "blocks": [
        {"id": "b1", "kind": "table_row", "section": ["T"], "text": text, "loc": {"line_start": 3, "line_end": 3}}]}
    start = text.rfind("200 000 ₸") if target == "второе" else text.index(target)
    old = "200 000 ₸" if target == "второе" else target
    e = {"block_id": "b1", "start": start, "end": start + len(old), "old": old, "new": new}
    out = write_revision(d, [e], tmp_path / "r.md", source=data)
    assert out.read_text(encoding="utf-8").splitlines()[2] == expected


def test_binary_source_gets_explicit_text_revision(doc, findings, questions, tmp_path):
    fake_pdf = b"%PDF-1.4 synthetic"
    from bcc_review.decisions._doc import sha256_bytes

    pdf_doc = dict(doc, id=sha256_bytes(fake_pdf), format="pdf")
    q = Question.from_dict(questions[0].to_dict())
    for o in q.options:
        for e in o.edits:
            e["source_sha256"] = pdf_doc["id"]
    p = propose_patch(pdf_doc, findings[0], Decision.from_answer("Q-01", pdf_doc["id"], "A"), question=q)
    (tmp_path / "loan.pdf").write_bytes(fake_pdf)
    out = write_revision(pdf_doc, p["edits"], tmp_path / "loan.revision.md", source=tmp_path / "loan.pdf")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Досрочное погашение потребительского кредита — текстовая редакция")
    assert "Исходный документ: `loan.pdf`" in text and pdf_doc["id"] in text
    assert "## Досрочное погашение потребительского кредита" in text and "### Тарифы" in text
    assert "### Тарифы\n\nКомиссия за досрочное погашение не взимается." in text
    m = json.loads((tmp_path / "loan.revision.revision.json").read_text(encoding="utf-8"))
    assert m["revision"]["mode"] == "text_rendition"


def test_revision_never_overwrites_source(doc, findings, questions, src_path):
    p = propose_patch(doc, findings[0], _dec(doc, "Q-01", "A"), question=questions[0])
    with pytest.raises(PatchError):
        write_revision(doc, p["edits"], src_path, source=src_path)
