"""№11: исправленная редакция (revise) — применение правок кодом, без сети."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import revise  # noqa: E402
from test_11_clarify import DOC, FIX, FakeCtx, FakeLLM, load_view  # noqa: E402

LINES = DOC.read_text(encoding="utf-8").splitlines()


def rw(fid, *edits):
    return {"finding_id": fid, "summary": "", "edits": [dict(zip(("action", "line", "old", "new"), e)) for e in edits]}


def test_find_span_exact_and_normalized():
    raw = '* **Ф-2.** Месяц определяется по дате — совершения «покупки».'
    assert revise.find_span(raw, "Месяц определяется") == (11, 29)
    a, b = revise.find_span(raw, 'дате - совершения "покупки"')
    assert raw[a:b] == "дате — совершения «покупки»"
    a, b = revise.find_span(raw, "Ф-2. Месяц")
    assert raw[a:b].startswith("Ф-2.") and raw[a:b].endswith("Месяц")
    assert revise.find_span(raw, "нет такого текста") is None


def test_find_span_table_cells():
    raw = "| Расходы 19 900 ₸, порог 20 000 ₸ | Перевести 500 ₸ | Счётчик показывает 19 900 ₸ |"
    a, b = revise.find_span(raw, "Перевести 500 ₸ | Счётчик показывает 19 900 ₸")
    assert raw[a:b] == "Перевести 500 ₸ | Счётчик показывает 19 900 ₸"


def test_replace_marks_line_and_table_cell():
    res = revise.apply_edits(LINES, [
        rw("D-01", ("replace", 39, "максимум один такой push за календарный месяц", "максимум один такой push за месяц")),
        rw("D-02", ("replace", 64, "Февральский счётчик вырос на 4 000 ₸", "Январский счётчик вырос на 4 000 ₸")),
    ])
    out = res["markdown"].splitlines()
    assert out[38].endswith("[изменено: D-01]") and "за месяц." in out[38]
    assert out[63].endswith("Январский счётчик вырос на 4 000 ₸ [изменено: D-02] |")
    assert res["stats"]["replaced"] == 2 and res["stats"]["not_applied"] == 0
    assert all(e["applied"] for r in res["rewrites"] for e in r["edits"])
    assert res["rewrites"][1]["edits"][0]["was"] == "Февральский счётчик вырос на 4 000 ₸"


def test_insert_rows_and_requirements_in_document_style():
    res = revise.apply_edits(LINES, [
        rw("D-19", ("insert_after", 65, "", "Расходы 0 ₸ | Провести покупку | Итог 100 ₸\n| A | B | C |")),
        rw("D-07", ("insert_after", 40, "", "Ф-5. Новое правило.")),
        rw("D-05", ("insert_after", 61, "", "| X | Y | Z |")),  # после заголовка таблицы — в конец таблицы
    ])
    out = res["markdown"].splitlines()
    i = out.index(next(s for s in out if "Итог 100 ₸" in s))
    assert out[i] == "| Расходы 0 ₸ | Провести покупку | Итог 100 ₸ [добавлено: D-19] |"
    assert out[i - 1].startswith("| Расходы 19 900")
    req = next(s for s in out if "Ф-5." in s)
    assert req.startswith("* Ф-5. Новое правило.") and req.endswith("[добавлено: D-07]")
    assert res["stats"]["inserted"] == 4


def test_not_found_and_overlap_not_applied():
    w: list[str] = []
    res = revise.apply_edits(LINES, [
        rw("D-01", ("replace", 39, "выдуманный фрагмент", "что-то")),
        rw("D-02", ("replace", 38, "Месяц определяется по дате совершения покупки", "Месяц определяется по дате A")),
        rw("D-03", ("replace", 38, "по дате совершения покупки в Алматы", "по дате B")),
    ], w)
    assert res["stats"]["not_applied"] == 2 and res["stats"]["replaced"] == 1
    assert len(w) == 2
    assert "[изменено: D-02]" in res["markdown"] and "D-03" not in res["markdown"]


def test_code_block_edit_and_full_deletion():
    res = revise.apply_edits(LINES, [
        rw("D-14", ("replace", 167, '"amount":"50000"', '"amount":50000')),
        rw("D-04", ("replace", 169, "или", ""), ("replace", 171, '{"result":"ERROR","message":"Проверьте сумму"}', "")),
    ])
    md = res["markdown"]
    assert '{"result":"OK","amount":50000,"enabled":"1"}' in md
    assert "[изменено: D-14 — пример выше]" in md
    assert "Проверьте сумму" not in md.split("#### 200.")[1].split("**401.**")[0]
    assert "[удалено: D-04" in md
    # блоки кода остаются парными
    assert md.count("```") % 2 == 0


def test_run_with_fake_llm_writes_revised(tmp_path):
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    resp = {"rewrites": [
        {"finding_id": "D-02", "summary": "Месяц — по дате совершения покупки",
         "edits": [{"action": "replace", "line": 64, "old": "Февральский счётчик вырос на 4 000 ₸",
                    "new": "Январский счётчик вырос на 4 000 ₸"}]},
        {"finding_id": "D-99", "summary": "неизвестный дефект", "edits": [
            {"action": "replace", "line": 1, "old": "Уведомление", "new": "X"}]},
        {"finding_id": "D-28", "summary": "minor не правим", "edits": [
            {"action": "replace", "line": 1, "old": "Уведомление", "new": "X"}]},
    ]}
    ctx = FakeCtx(FakeLLM(resp))
    ctx.options = {"input": str(DOC)}
    res = revise.run(ctx, findings)
    md = res["revised_markdown"]
    assert md.splitlines()[0] == "# Уведомление о расходах по карте"
    assert "Исправленная редакция" in md and "<уточнить: …>" in md
    assert "Январский счётчик вырос на 4 000 ₸ [изменено: D-02]" in md
    assert [r["finding_id"] for r in res["rewrites"]] == ["D-02"]
    assert "D-01" in res["stats"]["without_rewrite"]
    user = ctx.llm.calls[0]["user"]
    assert "D-28 |" not in user, "minor в revise не идут"
    out = revise.write(tmp_path / "report.md", res)
    assert out == tmp_path / "report.revised.md" and out.read_text(encoding="utf-8") == md
    section = revise.render_markdown(res, out.name)
    assert "было: «Февральский счётчик вырос на 4 000 ₸»" in section


def test_answers_go_to_prompt():
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    ctx = FakeCtx(FakeLLM({"rewrites": []}))
    answers = {"answered": [{"question_id": "Q-02", "topic": "Месяц", "finding_ids": ["D-02"],
                             "answer": "По дате совершения покупки, UTC+5"}], "decisions": ["Холды не учитываются"]}
    res = revise.run(ctx, findings, answers)
    user = ctx.llm.calls[0]["user"]
    assert "По дате совершения покупки, UTC+5" in user and "Холды не учитываются" in user
    assert res["rewrites"] == []


def test_revised_path():
    assert revise.revised_path("reports/requirements.md").as_posix() == "reports/requirements.revised.md"
    assert revise.revised_path("out").as_posix() == "out.revised.md"


def test_non_markdown_source_uses_view_lines():
    view = load_view()
    lines, raw = revise._source_lines(type("C", (), {"options": {}})(), {"lines": view["lines"], "file": "x.pdf"})
    assert not raw and lines[36].startswith("Ф-1.")


def test_real_sonnet_edits_apply_cleanly():
    """Ответ sonnet на официальном документе: все правки применены, разметка не сломана."""
    raw = json.loads((FIX / "revise.json").read_text(encoding="utf-8"))
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    ctx = FakeCtx(FakeLLM(raw))
    ctx.options = {"input": str(DOC)}
    res = revise.run(ctx, findings)
    st = res["stats"]
    assert st["not_applied"] == 0 and st["replaced"] >= 20 and st["inserted"] >= 10
    md = res["revised_markdown"]
    assert md.count("```") % 2 == 0
    for line in md.splitlines():
        if line.startswith("|"):
            assert line.rstrip().endswith("|"), line
        if not line.startswith("```"):
            assert line.count("`") % 2 == 0, line
    assert "[изменено: D-01]" in md and "[добавлено: D-19]" in md
    # каждый critical получил правку
    crit = {f["id"] for f in findings if f["severity"] == "critical"}
    assert crit <= {r["finding_id"] for r in res["rewrites"]}


def test_run_modes_answers_and_revise(tmp_path):
    from bcc_review.v2.stages import clarify as cl

    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    questions = cl.run(FakeCtx(FakeLLM(json.loads((FIX / "clarify.json").read_text(encoding="utf-8")))),
                       findings)["questions"]

    class SeqLLM(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"stage": stage, "user": user})
            if stage == "revise_check":
                return {"fixes": []}
            if stage == "recheck":
                return {"decisions": [{"finding_id": "D-02", "status": "resolved", "reason": "ответ Q-02",
                                       "severity": "minor", "title": "", "problem": ""}], "candidates": []}
            return {"rewrites": [{"finding_id": "D-02", "summary": "месяц по дате покупки", "edits": [
                {"action": "replace", "line": 64, "old": "Февральский счётчик вырос на 4 000 ₸",
                 "new": "Январский счётчик вырос на 4 000 ₸"}]}]}

    ctx = FakeCtx(SeqLLM())
    ctx.options = {"input": str(DOC)}
    q2 = next(q for q in questions if "D-02" in q["finding_ids"])
    report = {"findings": findings, "questions": questions, "verdict": {}, "run": {"status": "complete"}}
    out = revise.run_modes(ctx, report, answers=f"{q2['id']}: A", do_revise=True, report_path=tmp_path / "r.md")
    assert [c["stage"] for c in ctx.llm.calls] == ["recheck", "revise", "revise_check"]
    assert out["clarification"]["resolved"] == 1
    assert q2["options"][0] in ctx.llm.calls[1]["user"], "ответ владельца подставляется в revise"
    assert Path(out["revised_file"]).name == "r.revised.md"
    assert len(out["markdown_sections"]) == 2 and "было → стало" in out["markdown_sections"][1]
    rw = out["rewrites"]
    assert rw == [{"finding_id": "D-02", "title": next(f["title"] for f in findings if f["id"] == "D-02"),
                   "severity": "critical", "summary": "месяц по дате покупки", "action": "replace",
                   "line_start": 64, "line_end": 64, "before": "Февральский счётчик вырос на 4 000 ₸",
                   "after": "Январский счётчик вырос на 4 000 ₸", "answer_ids": [q2["id"]]}]


def test_inserted_block_gets_markdown_shape():
    new = ("#### Метод чтения\nПоле | Значение\nREST type | GET\nRequest URL | /x\n"
           '{"result":"OK","amount":50000}\nСтатус 404 — карта не найдена.')
    res = revise.apply_edits(LINES, [rw("D-03", ("insert_after", 198, "", new))])
    out = res["markdown"].splitlines()
    i = out.index("#### Метод чтения [добавлено: D-03]")
    assert out[i + 1] == ""
    assert out[i + 2] == "| Поле | Значение [добавлено: D-03] |"
    assert out[i + 3] == "| :--- | :--- |"
    assert out[i + 4] == "| REST type | GET [добавлено: D-03] |"
    assert out[i + 6:i + 10] == ["```json", '{"result":"OK","amount":50000}', "```", "[добавлено: D-03 — пример выше]"]
    assert out[i + 10] == "Статус 404 — карта не найдена. [добавлено: D-03]"


def test_check_pass_fixes_conflict_introduced_by_edit():
    """Второй проход: исправление на строках редакции, пометка объединяется, а не дублируется."""
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]

    class SeqLLM(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"stage": stage, "user": user})
            if stage == "revise":
                return {"rewrites": [{"finding_id": "D-02", "summary": "январь", "edits": [
                    {"action": "replace", "line": 64, "old": "Февральский счётчик вырос на 4 000 ₸",
                     "new": "Январский счётчик вырос на 4 000 ₸"}]}]}
            # самопроверка идёт до шапки редакции: номера строк совпадают с исходными
            return {"fixes": [{"finding_id": "D-02", "problem": "время без пояса", "edits": [
                {"action": "replace", "line": 64, "old": "Покупка 31 января в 23:58",
                 "new": "Покупка 31 января в 23:58 по UTC+5"}]}]}

    ctx = FakeCtx(SeqLLM())
    ctx.options = {"input": str(DOC)}
    res = revise.run(ctx, findings)
    md = res["revised_markdown"]
    row = next(s for s in md.splitlines() if "Январский" in s)
    assert row.startswith("| Покупка 31 января в 23:58 по UTC+5 на 4 000 ₸")
    assert row.count("[изменено:") == 1 and row.endswith("[изменено: D-02] |")
    check_user = ctx.llm.calls[1]["user"]
    assert "[изменено: D-02]" in check_user and "<правки>" in check_user
    assert res["stats"]["check_fixes"] == 1 and res["stats"]["check_edits"] == 1


def test_check_pass_can_be_disabled():
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    ctx = FakeCtx(FakeLLM({"rewrites": [{"finding_id": "D-02", "summary": "", "edits": [
        {"action": "replace", "line": 64, "old": "Февральский", "new": "Январский"}]}]}))
    ctx.options = {"input": str(DOC), "revise_check": False}
    revise.run(ctx, findings)
    assert [c["stage"] for c in ctx.llm.calls] == ["revise"]
