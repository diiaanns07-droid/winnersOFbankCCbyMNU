"""№11: вопросы владельцу (clarify) — проверки кода без сети."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import clarify  # noqa: E402

DOC = ROOT / "release" / "input" / "requirements.md"
FIX = ROOT / "tests" / "v2" / "fixtures" / "11_official"


def load_view(path: Path = DOC) -> dict:
    """Простая нумерация MD, как в docview: строка файла = строка view, без разметки."""
    out = []
    for i, s in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        t = re.sub(r"\*\*|__|`", "", s).rstrip()
        t = re.sub(r"^\s*[*-]\s+", "", t)
        t = re.sub(r"^#+\s*", "", t)
        if t.strip().startswith("|") and t.strip().endswith("|"):
            cells = [c.strip() for c in t.strip().strip("|").split("|")]
            t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
        out.append({"n": i, "text": t, "page": None, "section": ""})
    return {"title": "Документ", "file": str(path), "format": "md", "lines": out}


class FakeLLM:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response, self.exc, self.calls = response, exc, []

    def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
        self.calls.append({"stage": stage, "system": system, "user": user, "schema": schema})
        if self.exc:
            raise self.exc
        return json.loads(json.dumps(self.response))


class FakeCtx:
    def __init__(self, llm, view=None):
        self.llm, self.view, self.warnings, self.options = llm, view or load_view(), [], {}

    def prompt(self, name, **vars):
        tmpl = (ROOT / "src" / "bcc_review" / "v2" / "prompts" / f"{name}.md").read_text(encoding="utf-8")
        for k, v in vars.items():
            tmpl = tmpl.replace("{{" + k + "}}", str(v))
        return "system", "<документ>…</документ>\n\n" + tmpl


@pytest.fixture(scope="module")
def findings() -> list[dict]:
    return json.loads((FIX / "findings.json").read_text(encoding="utf-8"))["findings"]


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads((FIX / "clarify.json").read_text(encoding="utf-8"))


def test_fixture_questions_have_quotes_and_options(findings, raw):
    ctx = FakeCtx(FakeLLM(raw))
    res = clarify.run(ctx, findings)
    qs = res["questions"]
    assert 1 <= len(qs) <= clarify.MAX_QUESTIONS
    for i, q in enumerate(qs, 1):
        assert q["id"] == f"Q-{i:02d}"
        assert q["evidence"], q
        assert all(e["verified"] != "missing" and e["line_start"] > 0 for e in q["evidence"])
        assert 2 <= len(q["options"]) <= 4
        assert q["to"] in clarify.ROLES
        assert q["finding_ids"] and all(f.startswith("D-") for f in q["finding_ids"])
        assert all("<уточнить" not in o for o in q["options"])
    blocking = [q["blocking"] for q in qs]
    assert blocking == sorted(blocking, reverse=True), "блокирующие вопросы — первыми"
    # в промпт ушли дефекты с цитатами
    user = ctx.llm.calls[0]["user"]
    assert "D-01 | critical" in user and "{{findings}}" not in user


def test_conflict_question_quotes_both_sides(findings, raw):
    qs = clarify.run(FakeCtx(FakeLLM(raw)), findings)["questions"]
    two_sided = [q for q in qs if len({e["line_start"] for e in q["evidence"]}) >= 2]
    assert two_sided, "у конфликтных вопросов цитаты обеих сторон"


def test_postprocess_filters(findings):
    view = load_view()
    raw = {"questions": [
        {"topic": "Неизвестный дефект", "finding_ids": ["D-99"], "to": "Аналитик", "blocking": True,
         "question": "Вопрос без дефекта?", "evidence": [{"quote": "Возврат уменьшает расходы", "line": 38}],
         "options": ["Вариант один", "Вариант два"], "why": "…"},
        {"topic": "Плохие варианты", "finding_ids": ["D-08"], "to": "бизнес", "blocking": True,
         "question": "Как учитывать возвраты?", "evidence": [{"quote": "Возврат уменьшает расходы", "line": 38}],
         "options": ["A) Оставить как есть", "B) На усмотрение разработчика", "C) Возврат уменьшает месяц покупки"],
         "why": "…"},
        {"topic": "Цитата выдумана", "finding_ids": ["D-17"], "to": "Аналитик", "blocking": True,
         "question": "Когда ставить признак отправки?", "evidence": [{"quote": "этого текста нет в документе", "line": 5}],
         "options": ["1. После подтверждения приёма", "2. До отправки", "2. До отправки"],
         "why": "…"},
        {"topic": "Только minor", "finding_ids": ["D-28"], "to": "Аналитик", "blocking": True,
         "question": "Нужна ли схема отката?", "evidence": [{"quote": "Реализация задачи/проекта предусматривает схему отката решений", "line": 76}],
         "options": ["Да, через выключатель функции", "Нет, откат не нужен"], "why": "…"},
        {"topic": "Критичный", "finding_ids": ["D-01", "D-01"], "to": "Владелец", "blocking": False,
         "question": "Сколько уведомлений в месяц?", "evidence": [{"quote": "максимум один такой push", "line": 39}],
         "options": ["Один на карту", "Один на каждое значение порога"], "why": "…"},
    ]}
    warnings: list[str] = []
    qs = clarify.postprocess(raw, findings, view, warnings)
    topics = [q["topic"] for q in qs]
    assert "Неизвестный дефект" not in topics
    assert "Плохие варианты" not in topics  # остался один вариант
    crit = next(q for q in qs if q["topic"] == "Критичный")
    assert crit["blocking"] is True and crit["finding_ids"] == ["D-01"] and crit["to"] == "Владелец продукта"
    assert crit["id"] == "Q-01"
    fake = next(q for q in qs if q["topic"] == "Цитата выдумана")
    assert fake["options"] == ["После подтверждения приёма", "До отправки"]
    findings_by_id = {f["id"]: f for f in findings}
    assert fake["evidence"][0]["line_start"] == findings_by_id["D-17"]["evidence"][0]["line_start"]  # цитата дефекта
    assert fake["blocking"] is False  # major без critical не блокирует
    assert "Только minor" not in topics  # вопрос только по незначительному дефекту при наличии critical/major
    assert any("D-99" in w or "нет связи" in w for w in warnings)


def test_duplicate_topic_dropped(findings):
    q = {"topic": "Тема", "finding_ids": ["D-02"], "to": "Аналитик", "blocking": True, "question": "Какой месяц?",
         "evidence": [{"quote": "Месяц определяется по дате совершения покупки", "line": 38}],
         "options": ["По дате покупки", "По дате проведения"], "why": "…"}
    qs = clarify.postprocess({"questions": [q, dict(q, question="Другая формулировка?")]}, findings, load_view())
    assert len(qs) == 1


def test_cap_and_order(findings):
    base = {"to": "Аналитик", "why": "…", "options": ["Первый вариант", "Второй вариант"],
            "evidence": [{"quote": "Возврат уменьшает расходы", "line": 38}]}
    raw = {"questions": [dict(base, topic=f"Тема {i}", question=f"Вопрос {i}?", finding_ids=[f"D-{(i % 20) + 5:02d}"],
                              blocking=i % 2 == 0) for i in range(14)]}
    raw["questions"].append(dict(base, topic="Критичная тема", question="Критичный вопрос?", finding_ids=["D-02"],
                                 blocking=False))
    qs = clarify.postprocess(raw, findings, load_view())
    assert len(qs) == clarify.MAX_QUESTIONS == 8
    assert qs[0]["topic"] == "Критичная тема"
    seen_nonblocking = False
    for q in qs:
        if not q["blocking"]:
            seen_nonblocking = True
        assert not (seen_nonblocking and q["blocking"])


def test_llm_failure_is_not_fatal(findings):
    ctx = FakeCtx(FakeLLM(exc=RuntimeError("503")))
    res = clarify.run(ctx, findings)
    assert res["questions"] == [] and any("clarify" in w for w in ctx.warnings)


def test_no_findings_no_call():
    llm = FakeLLM({"questions": []})
    assert clarify.run(FakeCtx(llm), []) == {"questions": []}
    assert llm.calls == []


def test_schema_options_bounds():
    item = clarify.SCHEMA["properties"]["questions"]["items"]
    assert item["properties"]["options"]["minItems"] == 2 and item["properties"]["options"]["maxItems"] == 4
    assert set(item["required"]) >= {"finding_ids", "to", "blocking", "question", "evidence", "options", "why"}


@pytest.mark.parametrize("name", ["clarify", "recheck", "revise", "revise_check"])
def test_prompts_have_no_official_words(name):
    text = (ROOT / "src" / "bcc_review" / "v2" / "prompts" / f"{name}.md").read_text(encoding="utf-8").lower()
    for word in ("push", "savelimit", "тиын", "порог", "алматы", "ф-1", "ф-2", "кэшбэк", "₸", "alerts"):
        assert word not in text, f"{name}.md содержит слово официального документа: {word}"


def test_no_formatting_questions_and_both_sides(findings):
    view = load_view()
    raw = {"questions": [
        {"topic": "Оформление", "finding_ids": ["D-25"], "to": "Аналитик", "blocking": False,
         "question": "Нужны ли ID у требований?", "evidence": [{"quote": "Сервис передаёт push на отправку", "line": 46}],
         "options": ["Да, сквозные ID", "Нет"], "why": "…"},
        {"topic": "Конфликт", "finding_ids": ["D-02"], "to": "Аналитик", "blocking": True,
         "question": "Какой месяц?", "evidence": [{"quote": "Месяц определяется по дате совершения покупки", "line": 38}],
         "options": ["По дате покупки", "По дате проведения"], "why": "…"},
    ]}
    qs = clarify.postprocess(raw, findings, view)
    assert [q["topic"] for q in qs] == ["Конфликт"]
    assert len({e["line_start"] for e in qs[0]["evidence"]}) >= 2  # вторая сторона — из цитат дефекта (строка 64)
    assert 64 in {e["line_start"] for e in qs[0]["evidence"]}


def test_only_formatting_findings_no_call():
    llm = FakeLLM({"questions": []})
    only_minor = [{"id": "D-01", "severity": "minor", "kind": "placeholder", "criterion": "conforming", "evidence": []},
                  {"id": "D-02", "severity": "minor", "kind": "traceability", "criterion": "traceable", "evidence": []}]
    assert clarify.run(FakeCtx(llm), only_minor) == {"questions": []}
    assert llm.calls == []


# --------------------------------------------------------------------------- третья волна: меньше, но точнее
def _q(topic, ids, **kw):
    base = {"topic": topic, "finding_ids": ids, "to": "Аналитик", "blocking": True, "question": f"{topic}?",
            "evidence": [{"quote": "Возврат уменьшает расходы", "line": 38}],
            "options": ["Первый вариант с числом 1", "Второй вариант с числом 2"], "why": "…"}
    base.update(kw)
    return base


def test_blocking_only_for_critical(findings):
    raw = {"questions": [_q("Мажор из исправить первым", ["D-05"]), _q("Критичный", ["D-01"], blocking=False)]}
    qs = {q["topic"]: q for q in clarify.postprocess(raw, findings, load_view())}
    assert qs["Критичный"]["blocking"] is True
    assert qs["Мажор из исправить первым"]["blocking"] is False  # D-05 major с priority 5: вердикт «нельзя» не держит


def test_cap_five_without_critical(findings):
    majors = [f for f in findings if f["severity"] != "critical"]
    raw = {"questions": [_q(f"Тема {i}", [f["id"]]) for i, f in enumerate(majors[:12])]}
    qs = clarify.postprocess(raw, majors, load_view())
    assert len(qs) == clarify.MAX_QUESTIONS_NO_CRITICAL == 5
    assert all(not q["blocking"] for q in qs)


def test_plain_text_removes_internal_codes():
    s = "Кнопка «Отменить» (L028) не имеет вызова; см. D-03 и требование R-12, строка L067, источник lens:qa."
    out = clarify.plain_text(s)
    for code in ("L028", "D-03", "R-12", "L067", "lens:qa"):
        assert code not in out
    assert "строка 67" in out and "строка строка" not in out and "(" not in out
    assert clarify.plain_text("Сколько уведомлений (D-01, D-02) по L039?") == "Сколько уведомлений по стр. 39?"
    assert clarify.plain_text("Один — как в D-01") == "Один"
    assert not clarify.plain_text("Один, как в D-01.").endswith("в.")
    assert clarify.plain_text("Правило R-12 документа", keep={"R-12"}) == "Правило R-12 документа"


def test_postprocess_cleans_codes_in_texts(findings):
    raw = {"questions": [_q("Коды", ["D-01"], question="Сколько уведомлений (D-01, D-02) по L039?",
                            why="Тест R-04 нельзя написать (L064).",
                            options=["Один — как в D-01", "Два, строка L040"])]}
    q = clarify.postprocess(raw, findings, load_view())[0]
    text = " ".join([q["question"], q["why"], *q["options"]])
    assert not re.search(r"\b(?:[DRC]-\d|L\d{2,})", text), text


def test_select_findings_orders_critical_first(findings):
    sel = clarify.select_findings(list(reversed(findings)))
    sev = [f["severity"] for f in sel]
    assert sev == sorted(sev, key=lambda s: clarify._SEV_RANK[s]) and "minor" not in sev
    assert [f["id"] for f in sel[:4]] == ["D-01", "D-02", "D-03", "D-04"]


# --------------------------------------------------------------------------- ранний запуск (параллельно с судьёй)
def _candidates(findings):
    """Кандидаты C-… из дефектов фикстуры: у каждого дефекта по два кандидата-дубля."""
    out = []
    for n, f in enumerate(findings, 1):
        for k in (0, 1):
            out.append({"id": f"C-{2 * n - 1 + k:03d}", "title": f["title"], "kind": f.get("kind"),
                        "criterion": f.get("criterion"), "severity": f["severity"],
                        "requirement_ids": f.get("requirement_ids", []), "evidence": f.get("evidence", []),
                        "problem": f.get("problem", ""), "question": f.get("question", ""),
                        "blocks": f.get("blocks", "both")})
    return out


def _with_candidate_ids(findings):
    return [dict(f, candidate_ids=[f"C-{2 * n - 1:03d}", f"C-{2 * n:03d}"]) for n, f in enumerate(findings, 1)]


def test_select_candidates_groups_and_filters(findings):
    groups = clarify.select_candidates(_candidates(findings))
    flat = [c for g in groups for c in g]
    assert flat and all(c["severity"] in ("critical", "major") for c in flat)
    assert groups[0][0]["severity"] == "critical"
    block = clarify.format_candidates(groups)
    assert "C-001" in block and "цитаты:" in block


def test_remap_candidates_to_findings(findings):
    fs = _with_candidate_ids(findings)
    raw = {"questions": [_q("Ранний", ["C-002", "C-003", "C-999", "D-05"])]}
    out = clarify.remap(raw, fs)
    assert out["questions"][0]["finding_ids"] == ["D-01", "D-02", "D-05"]


def test_early_finish_uses_early_answer(findings):
    fs = _with_candidate_ids(findings)
    early_raw = {"questions": [_q("Уведомления в месяц", ["C-001"]), _q("Ложный кандидат", ["C-999"])]}
    llm = FakeLLM(early_raw)
    ctx = FakeCtx(llm)
    handle = clarify.start(ctx, _candidates(findings))
    res = clarify.finish(ctx, fs, handle)
    assert len(llm.calls) == 1  # один вызов — ранний, повторного нет
    assert "C-001" in llm.calls[0]["user"]
    assert [q["finding_ids"] for q in res["questions"]] == [["D-01"]]
    assert res["questions"][0]["blocking"] is True


def test_early_failure_falls_back_to_late_call(findings):
    fs = _with_candidate_ids(findings)

    class Flaky(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"user": user})
            if len(self.calls) == 1:
                raise RuntimeError("503")
            return {"questions": [_q("Поздний", ["D-02"])]}

    llm = Flaky()
    ctx = FakeCtx(llm)
    res = clarify.finish(ctx, fs, clarify.start(ctx, _candidates(findings)))
    assert len(llm.calls) == 2 and res["questions"][0]["finding_ids"] == ["D-02"]
    assert any("ранний вызов" in w for w in ctx.warnings)


def test_early_off_target_reasks(findings):
    fs = _with_candidate_ids(findings)

    class Two(FakeLLM):
        def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
            self.calls.append({"user": user})
            if len(self.calls) == 1:  # ранний ответ только про кандидатов, которых судья отклонил
                return {"questions": [_q("Отклонённый", ["C-998"])]}
            return {"questions": [_q("По итогу", ["D-03"])]}

    llm = Two()
    ctx = FakeCtx(llm)
    res = clarify.finish(ctx, fs, clarify.start(ctx, _candidates(findings)))
    assert len(llm.calls) == 2 and res["questions"][0]["topic"] == "По итогу"


def test_finish_without_early_is_plain_run(findings):
    llm = FakeLLM({"questions": [_q("Поздний", ["D-02"])]})
    res = clarify.finish(FakeCtx(llm), findings, None)
    assert len(llm.calls) == 1 and res["questions"][0]["finding_ids"] == ["D-02"]


def test_start_without_llm_returns_none():
    ctx = FakeCtx(None)
    assert clarify.start(ctx, []) is None


def test_sides_inside_one_line():
    a = {"line_start": 36, "quote": "срок 25-го числа включительно"}
    b = {"line_start": 36, "quote": "проценты начисляются с 26-го"}
    c = {"line_start": 36, "quote": "25-го числа"}
    assert clarify.count_sides([a, b]) == 2  # две разные цитаты одной строки — две стороны
    assert clarify.count_sides([a, c]) == 1  # вложенная цитата — та же сторона
    assert clarify.is_new_side({"line_start": 40, "quote": "x"}, [a])


def test_reviewers_rank_majors(findings):
    a = dict(findings[6], id="D-90", priority=0, sources=["lens:qa"])
    b = dict(findings[6], id="D-91", priority=0, sources=["lens:qa", "consistency", "rules:api.status", "rules:api.x"])
    assert clarify.reviewers(a) == 1 and clarify.reviewers(b) == 3  # правила одного вида — один ревьюер
    sel = clarify.select_findings([a, b])
    assert [f["id"] for f in sel] == ["D-91", "D-90"]
    raw = {"questions": [_q("Один ревьюер", ["D-90"]), _q("Три ревьюера", ["D-91"])]}
    qs = clarify.postprocess(raw, [a, b], load_view())
    assert [q["topic"] for q in qs] == ["Три ревьюера", "Один ревьюер"]
    assert "ревьюеров: 3" in clarify.format_findings([b])


def test_placeholder_options_softened_only_when_needed():
    opts = ["Все QR действуют 15 минут", "Без суммы — до 23:59:59 по <уточнить: часовой пояс банка>",
            "Без суммы — 15 минут, но не дольше 23:59:59 по <уточнить: часовой пояс>"]
    out = clarify.clean_options(opts)
    assert len(out) == 3 and not any("<уточнить" in o for o in out)
    assert "(часовой пояс банка — укажите)" in out[1]
    # хватает двух конкретных — вариант с заглушкой отбрасывается
    out2 = clarify.clean_options(["Первый вариант", "Второй вариант", "Третий <уточнить: срок>"])
    assert out2 == ["Первый вариант", "Второй вариант"]


# --------------------------------------------------------------------------- каждый блокирующий critical — в вопросе
def _ttl_finding() -> dict:
    return {"id": "D-02", "severity": "critical", "blocks": "both", "kind": "unit_mismatch",
            "title": "Единица ttl: минуты в данных и секунды в проверке срока",
            "evidence": [{"quote": "срок действия ttl в минутах", "line_start": 51, "verified": "exact",
                          "section": "Часть A › Требования к данным"},
                         {"quote": "не позже времени создания QR-кода + ttl секунд", "line_start": 124,
                          "verified": "exact", "section": "Часть B › Логика работы метода"}],
            "scenario": "QR создан в 10:00 с ttl=15: по минутам действует до 10:15, по секундам — до 10:00:15.",
            "rewrite": "Проверить, что текущее время не позже времени создания QR-кода + ttl минут."}


def test_uncovered_critical_unit_conflict_gets_code_question():
    """Судья поднял major до critical, а ранний вызов о нём не спросил: вопрос кодом, без нового вызова."""
    f = _ttl_finding()
    other = {"id": "D-01", "severity": "critical", "blocks": "both", "kind": "contradiction", "title": "x",
             "evidence": []}
    qs = [{"id": "Q-01", "finding_ids": ["D-01"], "blocking": True, "topic": "t", "question": "q",
           "options": ["a", "b"], "evidence": [], "why": "", "to": "Аналитик"},
          {"id": "Q-02", "finding_ids": ["D-09"], "blocking": False, "topic": "t2", "question": "q2",
           "options": ["a", "b"], "evidence": [], "why": "", "to": "Аналитик"}]
    w: list[str] = []
    out = clarify.cover_critical(qs, [other, f], w)
    assert [q["id"] for q in out] == ["Q-01", "Q-02", "Q-03"]
    code = out[1]
    assert code["finding_ids"] == ["D-02"] and code["blocking"] and code.get("origin") == "code"
    # первым — сторона, которую сохраняет готовая формулировка «стало» (она переписывает секунды на минуты)
    assert code["options"][0].startswith("Верно «срок действия ttl в минутах» (Требования к данным)")
    assert "«Требования к данным»" in code["question"] and "«Логика работы метода»" in code["question"]
    assert len(code["evidence"]) == 2 and "10:00:15" in code["why"]
    assert not re.search(r"\bL\d{3}\b|\b[DR]-\d", code["question"] + " ".join(code["options"]))


def test_code_question_only_for_units_and_boundaries():
    """«Какое место верно» без модели — только когда стороны сами варианты (единицы, границы), не заголовки."""
    f = _ttl_finding()
    assert clarify.conflict_question(dict(f, kind="status_conflict")) is None
    heading = dict(f, evidence=[{"quote": "200. Successful — Created", "line_start": 160, "verified": "exact",
                                 "section": "Часть B › 200. Successful — Created"}, f["evidence"][1]])
    assert clarify.conflict_question(heading) is None
    w: list[str] = []
    q = clarify.cover_critical([], [dict(f, kind="missing_element")], w)
    assert q == [] and any("остался без вопроса" in x for x in w)


def test_early_call_gets_room_for_judge_upgrades():
    """Ранний вызов видит серьёзность линз: ему — запас до 10 вопросов, кап 8 — по итоговой серьёзности судьи."""
    assert "до 10 вопросов" in clarify.EARLY_NOTE
    from bcc_review.v2 import prompts
    _, task = prompts.task("clarify", findings="—")
    assert "до 10, если в конце блока <дефекты>" in task


def test_keep_as_is_inside_a_decision_is_not_banned():
    """«Пример оставить как есть» внутри решения — часть правки; запрещён только вариант «оставить как есть».
    На официальном (haiku, P3) так пропадал вопрос по критичному противоречию: вариантов оставалось меньше двух."""
    real = "По дате проведения покупки в часовом поясе Алматы; правило переписать под дату проведения, пример оставить как есть"
    assert clarify.clean_options(["По дате совершения покупки; пример переписать", real]) == \
        ["По дате совершения покупки; пример переписать", real]
    for bad in ("Оставить как есть", "Оставить всё без изменений", "Ничего не менять, оставить как есть",
                "Документ оставить как есть", "На усмотрение разработчика", "Решить позже"):
        assert clarify.banned_option(bad), bad


def test_self_correction_tail_is_cut_from_option():
    """Обрывок самопроверки модели («... no») в конце варианта владельцу не показываем."""
    out = clarify.clean_options(['Чужая карта даёт HTTP 403 с телом {"message":"Доступ запрещён"}... no',
                                 "Чужая и отсутствующая карта дают 404", "Сумма до 1 000 ₸… wait"])
    assert out == ['Чужая карта даёт HTTP 403 с телом {"message":"Доступ запрещён"}',
                   "Чужая и отсутствующая карта дают 404", "Сумма до 1 000 ₸"]
    # русское «нет» после многоточия — часть правила, не хвост
    assert clarify.clean_options(["Ответ 410 … нет ответа 400", "Ответ 400"]) == ["Ответ 410 … нет ответа 400", "Ответ 400"]
