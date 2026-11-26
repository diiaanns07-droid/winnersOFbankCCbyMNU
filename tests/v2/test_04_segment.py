"""Тесты этапа segment (№04): кодовая часть нарезки и фикстуры. Без сети."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bcc_review.v2.stages import segment as sg

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "v2" / "fixtures"
OFFICIAL_MD = ROOT / "release" / "input" / "requirements.md"
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "segment.md"


def _view(lines: list[str], fmt: str = "md", sections: list[str] | None = None) -> dict:
    sections = sections or [""] * len(lines)
    return {"title": "t", "file": "", "format": fmt, "lines": [
        {"n": i, "text": t, "page": None, "section": s, "src_line": i, "block_id": ""}
        for i, (t, s) in enumerate(zip(lines, sections), 1)]}


@pytest.fixture(scope="module")
def official_view() -> dict:
    return sg.load_view(str(OFFICIAL_MD))


# ---- схема и промпт -----------------------------------------------------------------------------------

def test_schema_matches_contract_fields():
    item = sg.SCHEMA["properties"]["requirements"]["items"]
    assert set(item["required"]) == {"source_id", "kind", "section", "summary", "quote", "line_start", "line_end"}
    assert set(item["properties"]["kind"]["enum"]) == set(sg.KINDS)
    ex = sg.SCHEMA["properties"]["excluded"]["items"]
    assert set(ex["required"]) == {"what", "line_start", "line_end", "reason"}


def test_prompt_has_main_and_followup_parts():
    main, follow = sg.load_tasks()
    assert "excluded" in main and "source_id" in main
    assert "{{uncovered}}" in follow


BANNED = ["push", "savelimit", "тиын", "порог", "алмат", "ф-1", "ф-2", "ф-3", "ф-4", "alertscontroller",
          "cardid", "уведомление о расход", "1 000 000", "50 000", "48 500", "kzt", "₸"]


def test_prompt_has_no_words_of_official_document():
    text = PROMPT.read_text(encoding="utf-8").lower()
    found = [w for w in BANNED if w in text]
    assert not found, f"в промпте нарезки слова официального документа: {found}"


# ---- строки и заголовки -------------------------------------------------------------------------------

def test_trivial_lines():
    for t in ["", "   ", "---", " |  | ", "json", "text", "```json", "{", "}"]:
        assert sg.is_trivial(t), t
    for t in ["404", "или", "Тело не используется.", "Цели"]:
        assert not sg.is_trivial(t), t


def test_headings_from_markdown_source(official_view):
    h = sg.heading_lines(official_view)
    by_n = {x["n"]: x["text"] for x in official_view["lines"]}
    assert 36 in h and by_n[36] == "Функциональные требования"
    assert 37 not in h  # пункт списка — не заголовок
    assert 160 in h and 162 not in h


def test_headings_by_section_tail_without_source():
    v = _view(["Цели", "Сделать хорошо.", "Данные", "Хранить X."],
              sections=["Цели", "Цели", "Данные", "Данные"])
    assert sg.heading_lines(v) == {1, 3}


# ---- нормализация ответа ------------------------------------------------------------------------------

def test_quote_moves_range_when_far_from_hint(official_view):
    r = sg.normalize_requirement(official_view, {
        "source_id": "", "kind": "nonfunctional", "section": "x", "summary": "s",
        "quote": "Сервис передаёт push на отправку в течение минуты", "line_start": 10, "line_end": 10})
    assert (r["line_start"], r["line_end"]) == (46, 46)


def test_missing_quote_replaced_by_line_text(official_view):
    r = sg.normalize_requirement(official_view, {
        "source_id": "", "kind": "data", "section": "", "summary": "s",
        "quote": "такой фразы в документе нет совсем", "line_start": 49, "line_end": 49})
    assert r["quote"].startswith("Хранить идентификатор карты")
    assert r["section"].endswith("Требования к данным")


def test_bad_kind_and_reversed_range(official_view):
    r = sg.normalize_requirement(official_view, {
        "source_id": "", "kind": "nonsense", "section": "", "summary": "", "quote": "",
        "line_start": 40, "line_end": 37})
    assert r["kind"] == "other" and (r["line_start"], r["line_end"]) == (37, 40)
    assert r["summary"]


def test_empty_range_dropped(official_view):
    assert sg.normalize_requirement(official_view, {
        "source_id": "", "kind": "api", "section": "", "summary": "", "quote": "",
        "line_start": 2, "line_end": 2}) is None


def test_merge_dedupes_and_trims_excluded():
    reqs = [{"id": "", "source_id": "", "kind": "api", "section": "", "summary": "a", "quote": "a",
             "line_start": 5, "line_end": 5, "page": None},
            {"id": "", "source_id": "Т-1", "kind": "api", "section": "", "summary": "a", "quote": "a",
             "line_start": 5, "line_end": 5, "page": None},
            {"id": "", "source_id": "", "kind": "api", "section": "", "summary": "b", "quote": "b",
             "line_start": 2, "line_end": 3, "page": None}]
    excl = [{"what": "x", "line_start": 3, "line_end": 7, "reason": "r"}]
    r, e = sg.merge_items(reqs, excl)
    assert [(x["line_start"], x["source_id"]) for x in r] == [(2, ""), (5, "Т-1")]
    assert [(x["line_start"], x["line_end"]) for x in e] == [(4, 4), (6, 7)]


def test_ids_in_document_order():
    reqs = [{"line_start": n} for n in (1, 2, 3)]
    assert [x["id"] for x in sg.assign_ids(reqs)] == ["R-01", "R-02", "R-03"]
    assert sg.assign_ids([{"line_start": i} for i in range(120)])[0]["id"] == "R-001"


# ---- покрытие -----------------------------------------------------------------------------------------

def _official_raw() -> dict:
    data = json.loads((FIX / "official" / "segment.json").read_text(encoding="utf-8"))
    return {"requirements": data["requirements"], "excluded": data["excluded"]}


def test_official_fixture_covers_every_line(official_view):
    raw = _official_raw()
    out = sg.segment_from_response(official_view, raw)
    assert out["coverage"]["uncovered_after_model"] == []
    assert out["coverage"]["uncovered"] == []


def test_dropped_requirement_is_detected_and_followup_called(official_view):
    raw = _official_raw()
    raw["requirements"] = [r for r in raw["requirements"] if r["line_start"] != 46]
    calls = []

    def followup(uncovered, done):
        calls.append(list(uncovered))
        return {"requirements": [{"source_id": "", "kind": "nonfunctional", "section": "", "summary": "НФТ",
                                  "quote": "Сервис передаёт push", "line_start": 46, "line_end": 46}],
                "excluded": []}

    out = sg.segment_from_response(official_view, raw, followup)
    assert calls == [[46]]
    assert out["coverage"]["uncovered"] == [] and out["coverage"]["auto_added"] == 0
    assert any(r["line_start"] == 46 and r["kind"] == "nonfunctional" for r in out["requirements"])


def test_gaps_filled_by_code_when_followup_fails(official_view):
    raw = _official_raw()
    raw["requirements"] = [r for r in raw["requirements"] if r["line_start"] not in (46, 142)]

    def followup(uncovered, done):
        raise RuntimeError("модель недоступна")

    out = sg.segment_from_response(official_view, raw, followup)
    assert out["coverage"]["uncovered"] == []
    assert out["coverage"]["auto_added"] == 2
    ids = [r["id"] for r in out["requirements"]]
    assert ids == [f"R-{i:02d}" for i in range(1, len(ids) + 1)]


# ---- деление длинного документа ------------------------------------------------------------------------

def test_short_document_single_chunk(official_view):
    assert sg.plan_chunks(official_view) == [(1, 198)]


def test_long_document_split_by_sections():
    lines, secs = [], []
    for part in range(4):
        for i in range(150):
            lines.append(f"Раздел {part}" if i == 0 else f"Требование {part}.{i} выполняется.")
            secs.append(f"Раздел {part}")
    v = _view(lines, sections=secs)
    chunks = sg.plan_chunks(v)
    assert chunks[0][0] == 1 and chunks[-1][1] == 600
    assert all(b - a + 1 <= sg.CHUNK_MAX_LINES for a, b in chunks)
    starts = {a for a, _ in chunks}
    assert starts <= {1, 151, 301, 451}  # режем по границам разделов
    for (a1, b1), (a2, _) in zip(chunks, chunks[1:]):
        assert a2 == b1 + 1


class _FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
        self.calls.append(user)
        return self.answer(user) if callable(self.answer) else self.answer


class _Ctx:
    def __init__(self, view, llm, options=None):
        self.view, self.llm, self.options, self.warnings = view, llm, options or {}, []


def test_run_with_fake_llm_chunks_and_renumbers():
    lines, secs = [], []
    for part in range(3):
        for i in range(140):
            lines.append(f"Часть {part}" if i == 0 else f"Пункт {part}-{i}: система делает действие {i}.")
            secs.append(f"Часть {part}")
    v = _view(lines, sections=secs)

    def answer(user):
        nums = [int(m) for m in re.findall(r"^L(\d+)\|", user, re.M)]
        reqs = [{"source_id": "", "kind": "functional", "section": "", "summary": "п",
                 "quote": lines[n - 1], "line_start": n, "line_end": n}
                for n in nums if not lines[n - 1].startswith("Часть")]
        return {"requirements": reqs, "excluded": []}

    llm = _FakeLLM(answer)
    out = sg.run(_Ctx(v, llm))
    assert len(llm.calls) >= 2  # 420 строк — несколько частей
    assert len(out["requirements"]) == 3 * 139
    assert out["requirements"][-1]["id"] == "R-417"
    assert out["coverage"]["uncovered"] == []


def test_run_offline_uses_heuristic(official_view):
    out = sg.run(_Ctx(official_view, None))
    assert out["coverage"]["mode"] == "heuristic"
    sids = {r["source_id"] for r in out["requirements"]}
    assert {"Ф-1", "Ф-2", "Ф-3", "Ф-4", "Статус 400"} <= sids
    excl_lines = set()
    for e in out["excluded"]:
        excl_lines.update(range(e["line_start"], e["line_end"] + 1))
    assert {72, 85} <= excl_lines  # чек-лист ревью — не требования


# ---- фикстуры для линз ---------------------------------------------------------------------------------

CASES = ["official", "official_pdf", "autopay.base", "cardblock.base", "cashback.base", "transfer_limit.base"]
FIELDS = {"id", "source_id", "kind", "section", "summary", "quote", "line_start", "line_end", "page"}


@pytest.mark.parametrize("case", CASES)
def test_fixture_shape(case):
    data = json.loads((FIX / case / "segment.json").read_text(encoding="utf-8"))
    reqs = data["requirements"]
    assert reqs, case
    assert [r["id"] for r in reqs] == [f"R-{i:02d}" for i in range(1, len(reqs) + 1)]
    for r in reqs:
        assert FIELDS <= set(r), (case, r)
        assert r["kind"] in sg.KINDS
        assert r["line_start"] <= r["line_end"]
    starts = [r["line_start"] for r in reqs]
    assert starts == sorted(starts)
    for e in data["excluded"]:
        assert {"what", "line_start", "line_end", "reason"} <= set(e)


def test_official_fixture_content():
    data = json.loads((FIX / "official" / "segment.json").read_text(encoding="utf-8"))
    reqs = data["requirements"]
    sids = [r["source_id"] for r in reqs]
    assert 30 <= len(reqs) <= 45
    for s in ["Ф-1", "Ф-2", "Ф-3", "Ф-4", "Статус 200", "Статус 400", "Статус 401", "Статус 403",
              "Статус 404", "Статус 500"]:
        assert s in sids, s
    kinds = [r["kind"] for r in reqs]
    for k in ["goal", "ui", "nonfunctional", "data", "integration", "architecture"]:
        assert k in kinds, k
    assert kinds.count("acceptance") == 3
    assert sum(1 for s in sids if re.search(r"п\. [1-5]$", s or "") and "Логика" in s) == 5
    assert sum(1 for s in sids if re.search(r"п\. [1-3]$", s or "") and "правил" in s) == 3
    # чек-лист ревью и блок согласующих — в excluded, не в требованиях
    req_lines = {n for r in reqs for n in range(r["line_start"], r["line_end"] + 1)}
    assert not req_lines & set(range(70, 92))
    ex_lines = {n for e in data["excluded"] for n in range(e["line_start"], e["line_end"] + 1)}
    assert set(range(72, 86)) <= ex_lines


def test_official_md_and_pdf_fixtures_comparable():
    md = json.loads((FIX / "official" / "segment.json").read_text(encoding="utf-8"))["requirements"]
    pdf = json.loads((FIX / "official_pdf" / "segment.json").read_text(encoding="utf-8"))["requirements"]
    assert abs(len(md) - len(pdf)) <= 2
    a = {r["source_id"] for r in md if r["source_id"]}
    b = {r["source_id"] for r in pdf if r["source_id"]}
    assert len(a ^ b) <= 2, a ^ b


def test_ask_split_used_and_merge_accepts_both_styles():
    lines = [f"Пункт {i}: система делает действие {i}." for i in range(1, 11)]
    v = _view(lines)

    class SplitLLM(_FakeLLM):
        def ask_split(self, stage, build, items, schema, merge):
            halves = [items[: len(items) // 2], items[len(items) // 2:]]
            outs = []
            for h in halves:
                system, user = build(h)
                self.calls.append(user)
                nums = [int(m) for m in re.findall(r"^L(\d+)\|", user, re.M)]
                outs.append({"requirements": [{"source_id": "", "kind": "functional", "section": "", "summary": "п",
                                               "quote": lines[n - 1], "line_start": n, "line_end": n} for n in nums],
                             "excluded": []})
            return merge(outs) if len(outs) != 2 else merge(*outs)

    llm = SplitLLM(None)
    out = sg.run(_Ctx(v, llm))
    assert len(llm.calls) == 2
    assert [r["line_start"] for r in out["requirements"]] == list(range(1, 11))
    assert sg._merge_results([{"requirements": [1], "excluded": []}])["requirements"] == [1]
