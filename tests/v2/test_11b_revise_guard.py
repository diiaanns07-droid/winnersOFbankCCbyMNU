"""№11-Б: правки «было → стало» не портят другие требования — вид правки по виду дефекта и страховка кодом.

Без сети. Случай аудитора F4: на дефекте «нет операции чтения» правка заменяла строку параметра действующей
операции сохранения описанием чтения (отчёт haiku `zamer_08_30_6d03683_haiku`, D-04, строка 143).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2.stages import revise  # noqa: E402
from test_11_clarify import DOC, FIX, FakeCtx, FakeLLM  # noqa: E402

LINES = DOC.read_text(encoding="utf-8").splitlines()
F4_REPORT = ROOT / "evaluation" / "v2" / "measurements" / "zamer_08_30_6d03683_haiku" / "report.json"
BEFORE = ROOT / "tests" / "v2" / "fixtures" / "11b_revise" / "official_before.json"
DEMO = ROOT / "examples" / "v2" / "demo_answers" / "requirements.json"


def rw(fid, *edits):
    return {"finding_id": fid, "summary": "", "edits": [dict(zip(("action", "line", "old", "new"), e)) for e in edits]}


def f4():
    r = json.loads(F4_REPORT.read_text(encoding="utf-8"))
    return r["findings"], r["requirements"]


# ------------------------------------------------------------------ вид дефекта
def test_defect_class():
    assert revise.defect_class({"kind": "missing_element", "criterion": "complete"}) == "missing"
    assert revise.defect_class({"kind": "incomplete", "criterion": "set_complete"}) == "missing"
    assert revise.defect_class({"kind": "incomplete", "criterion": "complete"}) == "other"
    for k in ("contradiction", "status_conflict", "event_conflict", "unit_mismatch", "boundary_conflict"):
        assert revise.defect_class({"kind": k}) == "conflict"
    assert revise.defect_class({"kind": "api_contract", "criterion": "set_consistent"}) == "conflict"
    assert revise.defect_class({"kind": "ambiguity"}) == "ambiguity"
    assert revise.defect_class({"kind": "security"}) == "other"


def test_prompt_block_names_defect_class():
    findings, _ = f4()
    block = revise.format_findings([f for f in findings if f["id"] in ("D-03", "D-04")])
    d4 = block[block.index("D-04 |"):]
    assert d4.splitlines()[1].startswith("  вид: не хватает элемента → только insert_after")
    d3 = block[block.index("D-03 |"):block.index("D-04 |")]
    assert "вид: противоречие" in d3 and "<уточнить" in d3


# ------------------------------------------------------------------ случай F4
def test_f4_missing_read_operation_does_not_replace_save_parameter():
    findings, reqs = f4()
    guard = revise.Guard(findings, reqs)
    old = "amount | integer | 32 bit | Да | 1 000–1 000 000 | Порог в тенге | limit_kzt"
    new = "Метод чтения настроек карты: <уточнить: путь и HTTP-метод>; параметр cardId; ответ result, amount."
    w: list[str] = []
    res = revise.apply_edits(LINES, [rw("D-04", ("replace", 143, old, new),
                                        ("insert_after", 198, "", "#### Метод чтения\nREST type | GET"))],
                             w, guard=guard)
    e_rep, e_ins = res["rewrites"][0]["edits"]
    assert not e_rep["applied"] and e_rep["rejected"]
    assert "не хватает элемента" in e_rep["reason"] and "insert_after" in e_rep["reason"]
    assert e_ins["applied"], "добавление нового элемента вставкой проходит"
    out = res["markdown"].splitlines()
    assert out[142] == LINES[142], "строка параметра сохранения осталась как была"
    assert res["stats"]["rejected"] == 1 and res["stats"]["replaced"] == 0
    assert any("D-04" in x and "не применена" in x for x in w)
    flat = revise.flat_rewrites({"rewrites": res["rewrites"]})
    assert [x["action"] for x in flat] == ["insert_after"], "в таблицу «было → стало» отклонённая замена не идёт"


def test_missing_class_extension_and_deletion():
    findings, reqs = f4()
    guard = revise.Guard(findings, reqs)
    # уточнить фразу-обещание, сохранив текст, — можно
    assert guard.check("D-04", 52, "Приложение читает и сохраняет настройки через дочерний документ",
                       "Приложение читает и сохраняет настройки через дочерний документ: операции сохранения и "
                       "чтения описаны в части B", LINES[51]) == ""
    # удалить строку ради недостающего элемента — нельзя
    assert "не удаляется" in guard.check("D-04", 143, "amount", "", LINES[142])


# ------------------------------------------------------------------ чужие строки
def test_foreign_line_whole_replace_rejected_spot_edit_allowed():
    findings, reqs = f4()
    guard = revise.Guard(findings, reqs)
    # строка 63 — критерий приёмки, её цитирует не D-05 (неоднозначность события)
    assert 63 not in guard.places("D-05") and guard.owners("D-05", 63)
    whole = LINES[62].strip("| ").split(" | ")[0]
    why = guard.check("D-05", 63, LINES[62].strip("| "), "Новый критерий целиком", LINES[62])
    assert "не входит в места D-05" in why and "точечная" in why
    # точечная правка значения в чужой строке допустима (термин, код, обязательность)
    assert guard.check("D-05", 63, whole.split(",")[0], whole.split(",")[0] + " (UTC+5)", LINES[62]) == ""
    # своя строка (цитата дефекта) — заменять можно
    assert guard.check("D-05", 38, "В расходы входят проведённые покупки.",
                       "Расходы увеличиваются по событию <уточнить: событие>.", LINES[37]) == ""


def test_lines_outside_requirements_and_defects_are_free():
    findings, reqs = f4()
    guard = revise.Guard(findings, reqs)
    free = [i for i in range(1, len(LINES) + 1) if not guard.cited.get(i) and not guard.line_reqs.get(i)]
    assert free, "в документе есть строки вне требований и цитат (примеры, заголовки)"
    ln = free[0]
    assert guard.check("D-05", ln, LINES[ln - 1] or "x", "новое", LINES[ln - 1] or "x") == ""


def test_guard_runs_inside_run_with_report_requirements():
    findings, reqs = f4()
    resp = {"rewrites": [{"finding_id": "D-04", "summary": "чтение", "edits": [
        {"action": "replace", "line": 143, "old": "amount | integer | 32 bit | Да | 1 000–1 000 000",
         "new": "Метод чтения: GET, параметр cardId, ответ result и amount"}]}]}
    ctx = FakeCtx(FakeLLM(resp))
    ctx.options = {"input": str(DOC), "revise_check": False}
    res = revise.run(ctx, findings, requirements=reqs)
    assert res["stats"]["rejected"] == 1 and res["stats"]["replaced"] == 0
    assert "| `amount` | integer | 32 bit | Да | 1 000–1 000 000 |" in res["revised_markdown"]
    skipped = res["stats"]["not_applied_edits"]
    assert [(x["finding_id"], x["pass"], x["line"]) for x in skipped] == [("D-04", 1, 143)]
    assert "не хватает элемента" in skipped[0]["reason"], "причина отказа видна в revise_stats отчёта"
    user = ctx.llm.calls[0]["user"]
    assert "вид: не хватает элемента" in user


# ------------------------------------------------------------------ второй проход
def test_check_pass_gets_rejected_edits_and_redoes_them_as_insert():
    findings, reqs = f4()

    class SeqLLM(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"stage": stage, "user": user})
            if stage == "revise":
                return {"rewrites": [{"finding_id": "D-04", "summary": "чтение", "edits": [
                    {"action": "replace", "line": 143, "old": "amount | integer | 32 bit | Да",
                     "new": "Метод чтения: GET, параметр cardId, ответ result и amount"},
                    {"action": "replace", "line": 103, "old": "Функциональные требования: чтение порога",
                     "new": "Функциональные требования: сохранение порога"}]}]}
            # самопроверка: вставка вместо отклонённой замены и попытка заменить чужую строку целиком
            return {"fixes": [
                {"finding_id": "D-04", "problem": "операция добавлена вставкой", "edits": [
                    {"action": "insert_after", "line": 198, "old": "", "new": "#### Метод чтения\nREST type | GET"}]},
                {"finding_id": "D-04", "problem": "критерий", "edits": [
                    {"action": "replace", "line": 63, "old": LINES[62].strip("| "), "new": "Другой критерий"}]}]}

    ctx = FakeCtx(SeqLLM())
    ctx.options = {"input": str(DOC)}
    res = revise.run(ctx, findings, requirements=reqs)
    check_user = ctx.llm.calls[1]["user"]
    assert "Не применённые правки" in check_user and "D-04 | L143" in check_user
    md = res["revised_markdown"]
    assert "#### Метод чтения [добавлено: D-04]" in md
    assert "Другой критерий" not in md, "чужая строка во втором проходе тоже не заменяется целиком"
    assert "| `amount` | integer | 32 bit | Да | 1 000–1 000 000 |" in md
    assert res["stats"]["rejected"] == 2 and res["stats"]["check_edits"] == 2  # две вставленные строки


# ------------------------------------------------------------------ вставка нового раздела
def test_new_section_does_not_split_existing_section():
    # вставка «####» после строки 141 (таблица Query-параметров) уходит в конец подраздела, до «#### Request body»
    res = revise.apply_edits(LINES, [rw("D-01", ("insert_after", 141, "", "#### Новый раздел\nТекст раздела."))])
    out = res["markdown"].splitlines()
    i = out.index("#### Новый раздел [добавлено: D-01]")
    assert out[i - 2].startswith("| `enabled`") and out[i - 1] == "", "после таблицы — пустая строка"
    assert out[i + 1] == "Текст раздела. [добавлено: D-01]" and out[i + 3].startswith("#### Request body")
    # уровень «###» — после всего раздела «Параметры запроса», «Ответ» остаётся своим разделом
    res = revise.apply_edits(LINES, [rw("D-01", ("insert_after", 136, "", "### Новая операция"))])
    out = res["markdown"].splitlines()
    i = out.index("### Новая операция [добавлено: D-01]")
    assert out[i - 2] == "* Тело не используется." and out[i + 2] == "### Ответ"


# ------------------------------------------------------------------ все правки официального
def test_all_sonnet_edits_official_before_guard_rejects_only_foreign_lines():
    """Замер «до» (sonnet, ответы examples/v2/answers.md): из 43 замен страховка не пропускает 2 — обе у D-17
    (активная карта) в строках чужих требований: шаг 3 логики (R-19) и пример ответа 400 (цитата D-19)."""
    r = json.loads(BEFORE.read_text(encoding="utf-8"))
    guard = revise.Guard(r["findings_before"], r["requirements"])
    rejected = []
    replaces = [e for e in r["rewrites"] if e["action"] == "replace"]
    for e in replaces:
        ln = e["line_start"]
        new = "" if e["after"] == "фрагмент удалён" else e["after"]
        if guard.check(e["finding_id"], ln, e["before"], new, LINES[ln - 1]):
            rejected.append((e["finding_id"], ln))
    assert len(replaces) == 43
    assert rejected == [("D-17", 119), ("D-17", 180)]


def test_all_sonnet_edits_demo_answers_guard_rejects_only_foreign_criterion():
    """Демо-прогон с ответами (sonnet, examples/v2/demo_answers): отклоняется одна замена — D-04 (событие)
    переписывает целиком критерий приёмки, который цитирует D-15."""
    r = json.loads(DEMO.read_text(encoding="utf-8"))
    guard = revise.Guard(r["findings_before"], r["requirements"])
    rejected = []
    for e in r["rewrites"]:
        if e["action"] != "replace":
            continue
        ln = e["line_start"]
        new = "" if e["after"] == "фрагмент удалён" else e["after"]
        if guard.check(e["finding_id"], ln, e["before"], new, LINES[ln - 1]):
            rejected.append((e["finding_id"], ln))
    assert rejected == [("D-04", 63)]


def test_fixture_sonnet_edits_guard():
    """Ответ sonnet без ответов владельца (фикстура №11): D-06 без решения переписывает «Тело не используется»
    — строку, которую цитирует D-22; остальные правки применяются."""
    raw = json.loads((FIX / "revise.json").read_text(encoding="utf-8"))
    findings = json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]
    ctx = FakeCtx(FakeLLM(raw))
    ctx.options = {"input": str(DOC), "revise_check": False}
    res = revise.run(ctx, findings)
    bad = [(r["finding_id"], e["line"]) for r in res["rewrites"] for e in r["edits"] if e.get("rejected")]
    assert bad == [("D-06", 148)]


# ------------------------------------------------------------------ анти-подгонка
def test_revise_prompts_have_no_words_of_official_document():
    from evaluation.v2 import antifit

    prompts = ROOT / "src" / "bcc_review" / "v2" / "prompts"
    for name in ("revise.md", "revise_check.md"):
        assert antifit.scan_text((prompts / name).read_text(encoding="utf-8")) == [], name


def test_check_pass_keeps_owner_values():
    """Самопроверка не «примиряет» значения, выбранные владельцем: 60 с из ответа не становятся 120 с."""
    findings, reqs = f4()

    class SeqLLM(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"stage": stage, "user": user})
            if stage == "revise":
                return {"rewrites": [{"finding_id": "D-05", "summary": "повторы", "edits": [
                    {"action": "replace", "line": 46, "old": "в течение минуты",
                     "new": "в течение 60 секунд, до 3 повторов в пределах 60 секунд"}]}]}
            return {"fixes": [{"finding_id": "D-05", "problem": "60 и 120", "edits": [
                {"action": "replace", "line": 46, "old": "до 3 повторов в пределах 60 секунд",
                 "new": "до 3 повторов в пределах 120 секунд"}]}]}

    ctx = FakeCtx(SeqLLM())
    ctx.options = {"input": str(DOC)}
    answers = {"answered": [], "decisions": ["При ошибке до 3 повторов, все в пределах 60 секунд от события."]}
    res = revise.run(ctx, findings, answers, requirements=reqs)
    assert "в пределах 60 секунд" in res["revised_markdown"] and "120 секунд" not in res["revised_markdown"]
    fix = res["check_fixes"][0]["edits"][0]
    assert not fix["applied"] and "ответа владельца" in fix["reason"]
