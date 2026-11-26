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
