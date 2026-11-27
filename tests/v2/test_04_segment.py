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
    # section и quote модель не пишет: их ставит код по строкам `view`
    assert set(item["required"]) == {"source_id", "kind", "summary", "line_start", "line_end"}
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

CASES = ["official", "official_pdf", "autopay.base", "cardblock.base", "cashback.base", "transfer_limit.base",
         "autopay.drop_promised.no_409_status", "cardblock.two_statuses.reblock_200",
         "cashback.drop_promised.no_read_method", "transfer_limit.event_conflict.cancel_no_restore"]
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
    lines, secs = [], []
    for part in range(2):
        lines.append(f"Раздел {part}")
        secs.append(f"Раздел {part}")
        for i in range(1, 6):
            lines.append(f"Пункт {part}.{i}: система делает действие {i}.")
            secs.append(f"Раздел {part}")
    v = _view(lines, sections=secs)

    class SplitLLM(_FakeLLM):
        def ask_split(self, stage, build, items, schema, merge, *, max_output_tokens=16000):
            assert max_output_tokens == sg.MAX_OUTPUT_TOKENS
            assert items == [(1, 6), (7, 12)]  # блоки по заголовкам — деление по границе раздела
            halves = [items[: len(items) // 2], items[len(items) // 2:]]
            outs = []
            for h in halves:
                system, user = build(h)
                self.calls.append(user)
                nums = [int(m) for m in re.findall(r"^L(\d+)\|", user, re.M)]
                assert "Раздел в начале фрагмента" in user
                outs.append({"requirements": [{"source_id": "", "kind": "functional", "summary": "п",
                                               "quote": lines[n - 1], "line_start": n, "line_end": n}
                                              for n in nums if not lines[n - 1].startswith("Раздел")],
                             "excluded": []})
            return merge(outs) if len(outs) != 2 else merge(*outs)

    llm = SplitLLM(None)
    out = sg.run(_Ctx(v, llm))
    assert len(llm.calls) == 2
    assert [r["line_start"] for r in out["requirements"]] == [2, 3, 4, 5, 6, 8, 9, 10, 11, 12]
    assert out["requirements"][-1]["section"] == "Раздел 1"
    assert sg._merge_results([{"requirements": [1], "excluded": []}])["requirements"] == [1]


def test_empty_document_makes_no_calls():
    llm = _FakeLLM({"requirements": [], "excluded": []})
    out = sg.run(_Ctx(_view(["", "---", "  "]), llm))
    assert out["requirements"] == [] and llm.calls == []


def test_mutant_injected_lines_are_requirements():
    """Внедрённая мутацией строка должна стать отдельным требованием (иначе линзы её не увидят)."""
    m = json.loads((FIX / "transfer_limit.event_conflict.cancel_no_restore" / "segment.json").read_text("utf-8"))
    assert any(r["source_id"] == "ЛП-7" for r in m["requirements"])
    base = json.loads((FIX / "transfer_limit.base" / "segment.json").read_text("utf-8"))
    assert len(m["requirements"]) == len(base["requirements"]) + 1


def test_table_headers_and_json_excluded_without_followup(official_view):
    raw = _official_raw()
    # модель «забыла» шапки таблиц и JSON-пример: дозапрос не нужен, код исключит сам
    raw["excluded"] = [e for e in raw["excluded"] if e["line_start"] not in (140, 153, 61)]
    raw["excluded"] = [e for e in raw["excluded"] if not (e["line_start"] <= 197 <= e["line_end"])]
    calls = []
    out = sg.segment_from_response(official_view, raw, lambda u, d: calls.append(u) or {})
    assert calls == []
    assert out["coverage"]["auto_excluded"] >= 3 and out["coverage"]["uncovered"] == []
    assert {140, 153, 61} <= sg.table_header_lines(official_view)
    assert 142 not in sg.table_header_lines(official_view)


@pytest.mark.parametrize("case,doc", [
    ("official", "release/input/requirements.md"),
    ("autopay.base", "evaluation/dev/corpus/cases/autopay.base/source.md"),
    ("cashback.base", "evaluation/dev/corpus/cases/cashback.base/source.md"),
])
def test_offline_heuristic_close_to_model(case, doc):
    """Без модели нарезка близка к модельной: тот же набор исходных ID, разница в числе ≤ 3."""
    view = sg.load_view(str(ROOT / doc))
    h = sg.heuristic_segment(view)
    fx = json.loads((FIX / case / "segment.json").read_text("utf-8"))["requirements"]
    assert abs(len(h["requirements"]) - len(fx)) <= 3
    a = {r["source_id"] for r in fx if r["source_id"]}
    b = {r["source_id"] for r in h["requirements"] if r["source_id"]}
    assert a <= b, a - b
    assert sg.uncovered_lines(view, h["requirements"], h["excluded"]) == []


def test_placeholder_source_id_cleared(official_view):
    r = sg.normalize_requirement(official_view, {
        "source_id": "<уточнить: название раздела>", "kind": "api", "summary": "s",
        "quote": "REST type | GET", "line_start": 104, "line_end": 104})
    assert r["source_id"] == ""


# ---- документы другой структуры (04_structures) ---------------------------------------------------------

STRUCT = FIX / "04_structures"
NESTED_IDS = {f"ФТ-{x}" for x in ["2.1.1", "2.1.2", "2.1.3", "2.2.1", "2.2.2", "2.2.3", "2.2.3.1", "2.2.3.2",
                                  "2.2.4", "2.3.1", "2.3.2", "2.4.1"]} | {"НФТ-3.1", "НФТ-3.2", "НФТ-3.3"}


@pytest.mark.parametrize("name", ["nested_ids.md", "unnumbered.md", "long.md", "official.docx"])
def test_structures_offline_cover_every_line(name):
    view = sg.load_view(str(STRUCT / name))
    h = sg.heuristic_segment(view)
    assert h["requirements"]
    assert sg.uncovered_lines(view, h["requirements"], h["excluded"]) == []


def test_nested_ids_kept_verbatim_offline():
    view = sg.load_view(str(STRUCT / "nested_ids.md"))
    sids = {r["source_id"] for r in sg.heuristic_segment(view)["requirements"]}
    assert NESTED_IDS <= sids


def test_long_document_chunks_and_ids():
    view = sg.load_view(str(STRUCT / "long.md"))
    assert len(view["lines"]) >= 600
    chunks = sg.plan_chunks(view)
    assert len(chunks) >= 3 and all(b - a + 1 <= sg.CHUNK_MAX_LINES for a, b in chunks)
    h = sg.heuristic_segment(view)
    ids = {r["source_id"] for r in h["requirements"] if r["source_id"].startswith("КИБ-")}
    assert ids == {f"КИБ-{k}.{j}" for k in range(1, 13) for j in range(1, 8)}
    assert len(h["requirements"]) == 242


@pytest.mark.parametrize("docx", ["release/input/requirements.docx", "tests/v2/fixtures/04_structures/official.docx"])
def test_official_docx_matches_md_offline(docx):
    md = sg.heuristic_segment(sg.load_view(str(OFFICIAL_MD)))["requirements"]
    path = ROOT / docx
    if not path.exists():
        pytest.skip(f"нет {docx}")
    dx = sg.heuristic_segment(sg.load_view(str(path)))["requirements"]
    assert [r["source_id"] for r in md] == [r["source_id"] for r in dx]


@pytest.mark.parametrize("other", ["release/input/requirements.pdf", "tests/v2/fixtures/04_structures/official.html"])
def test_official_pdf_html_match_md_offline(other):
    md = sg.heuristic_segment(sg.load_view(str(OFFICIAL_MD)))["requirements"]
    view = sg.load_view(str(ROOT / other))
    h = sg.heuristic_segment(view)
    assert [r["source_id"] for r in md] == [r["source_id"] for r in h["requirements"]]
    assert sg.uncovered_lines(view, h["requirements"], h["excluded"]) == []


def test_caption_line_auto_excluded():
    view = sg.load_view(str(STRUCT / "unnumbered.md"))
    n = next(x["n"] for x in view["lines"] if x["text"].strip() == "Ответ метода списка устройств:")
    excl, rest = sg.auto_exclude(view, [n])
    assert rest == [] and excl[0]["what"].startswith("Подпись")


def test_duplicate_source_ids_qualified_by_section():
    view = sg.load_view(str(STRUCT / "long.md"))
    h = sg.heuristic_segment(view)
    sids = [r["source_id"] for r in h["requirements"] if r["source_id"]]
    assert len(sids) == len(set(sids))
    assert any(s.endswith(": Статус 200") for s in sids)


def test_several_requirements_on_one_line_kept():
    v = _view(["Статусы", "200. Успех. 400. Неверные параметры. 404. Не найдено."], sections=["Статусы", "Статусы"])
    raw = {"requirements": [
        {"source_id": f"Статус {c}", "kind": "api", "summary": "к", "quote": q, "line_start": 2, "line_end": 2}
        for c, q in (("200", "200. Успех."), ("400", "400. Неверные параметры."), ("404", "404. Не найдено."))],
        "excluded": []}
    out = sg.segment_from_response(v, raw)
    assert [r["source_id"] for r in out["requirements"]] == ["Статус 200", "Статус 400", "Статус 404"]


def test_bare_status_code_merged_with_sentence(official_view):
    raw = _official_raw()
    raw["requirements"] = [r for r in raw["requirements"] if r["source_id"] != "Статус 404"] + [
        {"source_id": "", "kind": "api", "summary": "чужая карта", "line_start": 189, "line_end": 189,
         "quote": "Для чужой карты возвращается 404, как и для отсутствующей карты."},
        {"source_id": "Статус 404", "kind": "api", "summary": "404", "line_start": 190, "line_end": 192, "quote": "404"}]
    out = sg.segment_from_response(official_view, raw)
    last = out["requirements"][-1]
    assert (last["source_id"], last["line_start"], last["line_end"]) == ("Статус 404", 189, 192)
    assert len(out["requirements"]) == 40


def test_quote_taken_from_document_when_model_gives_none(official_view):
    raw = {"requirements": [{"source_id": "Ф-1", "kind": "functional", "summary": "п", "line_start": 37,
                             "line_end": 37}], "excluded": []}
    r = next(x for x in sg.segment_from_response(official_view, raw)["requirements"] if x["line_start"] == 37)
    assert r["source_id"] == "Ф-1" and r["quote"].startswith("Ф-1. Держатель активной карты")


def test_garbled_prefix_fixed_from_nearby_caption():
    view = sg.load_view(str(STRUCT / "unnumbered.md"))
    n = next(x["n"] for x in view["lines"] if x["text"].startswith("current |"))
    raw = {"requirements": [{"source_id": "Ответ методаываСписка устройств: current", "kind": "api", "summary": "п",
                             "line_start": n, "line_end": n}], "excluded": []}
    r = next(x for x in sg.segment_from_response(view, raw)["requirements"] if x["line_start"] == n)
    assert r["source_id"] == "Ответ метода списка устройств: current"


def test_requirement_does_not_start_with_heading(official_view):
    raw = _official_raw()
    raw["requirements"] = [r for r in raw["requirements"] if r["source_id"] != "Статус 404"] + [
        {"source_id": "", "kind": "api", "summary": "чужая карта", "line_start": 188, "line_end": 189},
        {"source_id": "Статус 404", "kind": "api", "summary": "404", "line_start": 190, "line_end": 192}]
    out = sg.segment_from_response(official_view, raw)
    last = out["requirements"][-1]
    assert (last["source_id"], last["line_start"], last["line_end"]) == ("Статус 404", 189, 192)
    assert last["quote"].startswith("Для чужой карты")


def test_table_tail_row_joins_passport_without_followup(official_view):
    raw = _official_raw()
    for r in raw["requirements"]:
        if r["source_id"] == "Общие параметры":
            r["line_end"] = 113
    calls = []
    out = sg.segment_from_response(official_view, raw, lambda u, d: calls.append(u) or {})
    assert calls == []
    r = next(x for x in out["requirements"] if x["source_id"] == "Общие параметры")
    assert (r["line_start"], r["line_end"]) == (103, 114)
    assert len(out["requirements"]) == 40


def test_adjacent_same_source_id_merged(official_view):
    raw = _official_raw()
    for r in raw["requirements"]:
        if r["source_id"] == "Общие параметры":
            r["line_end"] = 113
    raw["requirements"].append({"source_id": "Общие параметры", "kind": "api", "summary": "хвост",
                                "line_start": 114, "line_end": 114})
    out = sg.segment_from_response(official_view, raw)
    assert [(x["line_start"], x["line_end"]) for x in out["requirements"] if x["source_id"] == "Общие параметры"] \
        == [(103, 114)]


# ---- волна 3: расхождения ответов haiku с эталонной нарезкой ---------------------------------------------

ANSWERS = FIX / "04_answers"
CORPUS = ROOT / "evaluation" / "dev" / "corpus" / "cases"


def _keys(reqs: list[dict]) -> list[tuple]:
    return [(r["source_id"], r["line_start"], r["line_end"]) for r in reqs]


@pytest.mark.parametrize("case", ["autopay.base", "cardblock.base", "cashback.base"])
def test_haiku_answer_equals_reference_segmentation(case):
    """Ответ haiku с другим оформлением ID («Метод X, Статус 200», «Тело запроса blockCard: days», заголовок
    «Ответ 200» отдельным требованием, паспорт метода с шапки таблицы) код приводит к эталонной нарезке."""
    view = sg.load_view(str(CORPUS / case / "source.md"))
    raw = json.loads((ANSWERS / f"{case}.haiku.json").read_text(encoding="utf-8"))
    out = sg.segment_from_response(view, raw)
    ref = json.loads((FIX / case / "segment.json").read_text(encoding="utf-8"))["requirements"]
    assert _keys(out["requirements"]) == _keys(ref)
    assert out["coverage"]["uncovered"] == []


def test_heading_only_requirement_dropped_and_passport_starts_after_table_header():
    view = sg.load_view(str(CORPUS / "cashback.paraphrase.rate" / "source.md"))
    raw = json.loads((ANSWERS / "cashback.paraphrase.rate.haiku.json").read_text(encoding="utf-8"))
    heads = sg.heading_lines(view)
    out = sg.segment_from_response(view, raw)
    by_n = {x["n"]: x for x in view["lines"]}
    assert not any(r["line_start"] in heads and r["line_end"] == r["line_start"] for r in out["requirements"])
    passports = [r for r in out["requirements"] if r["source_id"].startswith("Метод ")]
    assert [r["source_id"] for r in passports] == ["Метод getCashback", "Метод saveCategory"]
    assert all(by_n[r["line_start"]]["text"].startswith("REST type") for r in passports)
    # «Метод getCashback. Ответ 200: category» — приставка метода через точку снимается
    assert {"Ответ 200: category", "Ответ 200: accrued", "Тело запроса: category"} <= {
        r["source_id"] for r in out["requirements"]}
    assert out["coverage"]["uncovered"] == []


def test_heading_only_keeps_bare_code_and_sentence_headings():
    view = _view(["Ответ 200", "", "404", "Система блокирует карту после трёх неверных попыток ввода кода."])
    heads = {1, 3, 4}
    assert sg._heading_only({"line_start": 1, "line_end": 2}, view, heads)
    assert not sg._heading_only({"line_start": 3, "line_end": 3}, view, heads)
    assert not sg._heading_only({"line_start": 4, "line_end": 4}, view, heads)


def test_status_table_row_and_paragraph_ids_canonical():
    lines = ["Метод A", "Ответ 200: {\"x\":1}. Поле x — время в формате ISO 8601, дата 2026-11-01.", "Статусы",
             "Код | Когда | Тело", "", "200 | Запрос выполнен | —", "409 | Статус не позволяет операцию | —"]
    sections = ["Метод A", "Метод A", "Статусы", "Статусы", "Статусы", "Статусы", "Статусы"]
    view = _view(lines, sections=sections)
    reqs = [{"source_id": "Метод A: ответ 200", "line_start": 2, "line_end": 2},
            {"source_id": "Статусы, строка 1", "line_start": 6, "line_end": 6},
            {"source_id": "Метод A, Статус 409", "line_start": 7, "line_end": 7}]
    out = sg.canonical_source_ids(view, reqs)
    assert [r["source_id"] for r in out] == ["", "Статус 200", "Статус 409"]


def test_duplicate_status_ids_qualified_by_method_not_by_same_tail():
    reqs = [{"source_id": "Статус 200", "section": "Часть B › Метод A › Статусы"},
            {"source_id": "Статус 200", "section": "Часть B › Метод B › Статусы"},
            {"source_id": "Тело запроса: id", "section": "Часть B › Метод A › Тело запроса"},
            {"source_id": "Тело запроса: id", "section": "Часть B › Метод B › Тело запроса"}]
    out = sg.uniquify_source_ids(reqs)
    assert [r["source_id"] for r in out] == ["Метод A: Статус 200", "Метод B: Статус 200",
                                             "Метод A, Тело запроса: id", "Метод B, Тело запроса: id"]


def test_model_suffix_on_heading_prefix_removed():
    lines = ["Метод X", "Тело запроса", "Parameter | Format", "", "days | integer"]
    sections = ["Метод X", "Метод X › Тело запроса", "Метод X › Тело запроса", "Метод X › Тело запроса",
                "Метод X › Тело запроса"]
    view = _view(lines, sections=sections)
    out = sg.canonical_source_ids(view, [{"source_id": "Тело запроса methodX: days", "line_start": 5, "line_end": 5}])
    assert out[0]["source_id"] == "Тело запроса: days"


def test_code_regex_ignores_dates_years_and_thousands():
    assert sg._CODE_RE.findall("2026-11-01T10:15, ISO 8601, 500 000 ₸, 1 500, 1.500") == []
    assert sg._CODE_RE.findall("вернуть 404, если; коды 400, 401; (409); 200/201") == \
        ["404", "400", "401", "409", "200", "201"]


def test_mixed_script_words_fixed_in_summary(official_view):
    assert sg.fix_mixed_script("при порогe 50 000 и push")[0] == "при пороге 50 000 и push"
    fixed, ok = sg.fix_mixed_script("Push-напоминání за 3 дня", {"напоминание", "напоминания", "дня"})
    assert ok and fixed.split()[0] in ("Push-напоминание", "Push-напоминания")
    assert sg.fix_mixed_script("Метод cardId и QR-код")[0] == "Метод cardId и QR-код"
    r = sg.normalize_requirement(official_view, {"source_id": "", "kind": "acceptance", "line_start": 63,
                                                 "line_end": 63, "summary": "Покупка доводит расходы до порогe"})
    words = re.findall(r"[^\W\d_]+", r["summary"])
    assert not any(re.search("[а-яё]", w, re.I) and re.search("[a-zá-ž]", w, re.I) for w in words)
    r = sg.normalize_requirement(official_view, {"source_id": "", "kind": "acceptance", "line_start": 63,
                                                 "line_end": 63, "summary": "Покупка ğxqzщ"})
    assert "ğ" not in r["summary"]


def test_excluded_reason_never_empty(official_view):
    e = sg.normalize_excluded(official_view, {"what": "", "line_start": 57, "line_end": 57, "reason": ""})
    assert e["what"] and e["reason"]


def test_own_id_in_document_wins_over_model_numbering():
    """sonnet однажды дал «Функциональные требования, п. 1» пункту «Ф-1.» — ID документа теряется в отчёте."""
    lines = ["Функциональные требования", "Ф-1. Клиент выбирает срок от 1 до 12 месяцев.",
             "ТР-7 Система хранит журнал три года.", "Параметр | Тип", "", "ФТ-01 | Текст"]
    sec = ["Функциональные требования"] * 6
    view = _view(lines, sections=sec)
    view["lines"][1]["kind"] = view["lines"][2]["kind"] = "list_item"
    reqs = [{"source_id": "Функциональные требования, п. 1", "line_start": 2, "line_end": 2},
            {"source_id": "", "line_start": 3, "line_end": 3},
            {"source_id": "Функциональные требования, строка 1", "line_start": 6, "line_end": 6}]
    assert [r["source_id"] for r in sg.canonical_source_ids(view, reqs)] == ["Ф-1", "ТР-7", "ФТ-01"]
    # «ISO-8601 формат» — не номер пункта
    assert sg._OWN_LEAD.match("ISO-8601 формат даты") is None


def test_paragraph_gets_no_section_prefixed_id():
    """haiku дал абзацу «Устройство считается новым…» ID «Как это должно работать: новое устройство»."""
    lines = ["Как это должно работать", "Устройство считается новым, если его не было 180 дней.",
             "Термины", "Сутки — интервал с 00:00 до 23:59."]
    sec = ["Как это должно работать"] * 2 + ["Термины"] * 2
    view = _view(lines, sections=sec)
    for x in view["lines"]:
        x["kind"] = "paragraph"
    reqs = [{"source_id": "Как это должно работать: новое устройство", "line_start": 2, "line_end": 2},
            {"source_id": "Термины: Сутки", "line_start": 4, "line_end": 4}]
    assert [r["source_id"] for r in sg.canonical_source_ids(view, reqs)] == ["", "Термины: Сутки"]


def test_range_edges_trimmed_and_placeholder_part_cut():
    lines = ["Метод", "", "Подключение настройки.", "", "Path-параметры", "Не используются.", "", "Request body",
             "Content-Type: application/json."]
    view = _view(lines)
    heads = {1, 5, 8}
    assert sg._trim_edges({"line_start": 2, "line_end": 4}, view, heads)["line_start"] == 3
    r = sg._trim_edges({"line_start": 6, "line_end": 9}, view, heads)
    assert (r["line_start"], r["line_end"]) == (9, 9)
    excl, rest = sg.auto_exclude(view, [6])
    assert rest == [] and excl[0]["what"] == "Заглушка"


def test_example_paragraph_with_other_requirements_in_section_is_excluded():
    lines = ["Ответ 200", "category | string | Код", "accrued | string | Сумма",
             "Пример ответа для первого критерия: {\"category\":\"TAXI\"}."]
    view = _view(lines, sections=["Ответ 200"] * 4)
    reqs = [{"source_id": "Ответ 200: category", "line_start": 2, "line_end": 2, "quote": "a"},
            {"source_id": "Ответ 200: accrued", "line_start": 3, "line_end": 3, "quote": "b"},
            {"source_id": "", "line_start": 4, "line_end": 4, "quote": "c"}]
    keep, excl = sg.demote_examples(view, reqs, [])
    assert [r["line_start"] for r in keep] == [2, 3] and excl[0]["line_start"] == 4
    # единственное описание ответа остаётся требованием
    keep, excl = sg.demote_examples(view, reqs[2:], [])
    assert [r["line_start"] for r in keep] == [4] and not excl
