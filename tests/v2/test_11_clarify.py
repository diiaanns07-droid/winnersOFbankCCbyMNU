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
        {"topic": "Цитата выдумана", "finding_ids": ["D-28"], "to": "Аналитик", "blocking": True,
         "question": "Нужна ли схема отката?", "evidence": [{"quote": "этого текста нет в документе", "line": 5}],
         "options": ["1. Да, через выключатель функции", "2. Нет, откат не нужен", "2. Нет, откат не нужен"],
         "why": "…"},
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
    assert fake["options"] == ["Да, через выключатель функции", "Нет, откат не нужен"]
    assert fake["evidence"] and fake["evidence"][0]["line_start"] == 76  # цитата дефекта вместо выдуманной
    assert fake["blocking"] is False  # minor-дефект не блокирует
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
    assert len(qs) == 10
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
