"""Тесты судьи (№10) на синтетических кандидатах, без сети: модель заменена заранее заданными ответами."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bcc_review.v2.stages import judge  # noqa: E402

OFFICIAL = ROOT / "release" / "input" / "requirements.md"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"


# --- окружение без каркаса ----------------------------------------------------------------------


def simple_view(path: Path) -> dict:
    """Минимальный docview: строки файла, ячейки таблиц через « | », без markdown-разметки."""
    lines = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        t = re.sub(r"\*\*|`", "", raw).rstrip()
        t = re.sub(r"^\s*[*-]\s+", "", t)
        t = re.sub(r"^#+\s*", "", t)
        if t.strip().startswith("|") and t.strip().endswith("|"):
            cells = [c.strip() for c in t.strip().strip("|").split("|")]
            t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
        lines.append({"n": i, "text": t, "page": None, "section": ""})
    return {"title": path.stem, "file": path.name, "format": "md", "lines": lines}


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def ask(self, stage, system, user, schema, *, max_output_tokens=16000):
        self.calls.append({"stage": stage, "system": system, "user": user, "schema": schema})
        if not self.responses:
            raise RuntimeError("нет заготовленного ответа")
        r = self.responses.pop(0)
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return r(user, schema)
        return r


class Ctx:
    def __init__(self, llm=None, view=None, requirements=None, options=None):
        self.llm = llm
        self.options = {"judge_check": False} if options is None else options
        self.view = view if view is not None else simple_view(OFFICIAL)
        self.requirements = requirements if requirements is not None else json.loads(
            SEGMENT.read_text(encoding="utf-8"))["requirements"]
        self.warnings: list[str] = []

    def warn(self, msg):
        self.warnings.append(msg)


class Truncated(Exception):
    kind = "truncated"


def cand(cid, line, quote, *, kind="ambiguity", criterion="unambiguous", severity="major", reqs=("R-06",),
         source="lens:analyst", title=None, scenario="Вход X даёт два исхода.", impact="Спор при приёмке.",
         blocks="both", extra=()):
    ev = [{"quote": quote, "line": line, "line_start": line, "line_end": line, "page": None,
           "section": "Раздел", "verified": "exact"}]
    for ln, q in extra:
        ev.append({"quote": q, "line": ln, "line_start": ln, "line_end": ln, "page": None, "section": "Раздел",
                   "verified": "exact"})
    return {"id": cid, "title": title or f"Кандидат {cid}", "kind": kind, "criterion": criterion,
            "severity": severity, "requirement_ids": list(reqs), "evidence": ev,
            "problem": f"Проблема {cid}.", "scenario": scenario, "impact": impact,
            "recommendation": f"Исправить {cid}.", "rewrite": "", "question": "", "blocks": blocks,
            "source": source}


def finding(key, ids, *, severity="major", kind="ambiguity", criterion="unambiguous", priority=0,
            blocks="both", title=None, scenario="", impact="", reqs=()):
    return {"key": key, "candidate_ids": list(ids), "base": ids[0], "title": title or f"Дефект {key}",
            "kind": kind, "criterion": criterion, "requirement_ids": list(reqs), "problem": f"Суть {key}.",
            "scenario": scenario, "impact": impact, "severity_basis": "", "severity": severity,
            "blocks": blocks, "priority": priority, "recommendation": ""}


def response(findings, rejected=(), checklist=None, summary="Разработку начинать нельзя: F01."):
    if checklist is None:
        checklist = [{"n": n, "answer": "Частично", "comment": "Есть замечания F01.", "finding_keys": ["F01"]}
                     for n in range(1, 15)]
    return {"findings": list(findings), "rejected": list(rejected), "checklist": checklist,
            "verdict_summary": summary}


def all_placed(result, ids):
    in_f = [c for f in result["findings"] for c in f["candidate_ids"]]
    in_r = [r["candidate_id"] for r in result["rejected"]]
    assert len(in_f) == len(set(in_f)), "кандидат в двух дефектах"
    assert not set(in_f) & set(in_r), "кандидат и в дефекте, и в отклонённых"
    assert set(in_f) | set(in_r) == set(ids), "кандидат потерян"


# --- синтетический набор: 70 кандидатов --------------------------------------------------------


def seventy():
    """70 кандидатов: дубли одной первопричины от трёх линз, ложные, сигналы правил и фон."""
    cs = [
        # одна первопричина «операция обещана, но не описана» — три линзы, три раздела
        cand("C-001", 52, "Приложение читает и сохраняет настройки", kind="missing_element",
             criterion="set_complete", severity="critical", reqs=("R-12",), source="lens:architect"),
        cand("C-002", 103, "Функциональные требования: чтение порога", kind="missing_element",
             criterion="set_complete", severity="critical", reqs=("R-16",), source="lens:analyst"),
        cand("C-003", 29, "сумма за месяц и кнопка «Сохранить»", kind="missing_element",
             criterion="set_complete", severity="major", reqs=("R-03",), source="lens:qa"),
        # конфликт двух мест — две линзы, те же строки
        cand("C-004", 39, "максимум один такой push за календарный месяц", kind="contradiction",
             criterion="set_consistent", severity="critical", reqs=("R-07", "R-08"), source="consistency",
             extra=[(40, "следующее достижение вызывает push независимо от истории")]),
        cand("C-005", 40, "следующее достижение вызывает push независимо от истории", kind="contradiction",
             criterion="set_consistent", severity="critical", reqs=("R-07", "R-08"), source="lens:qa",
             extra=[(39, "максимум один такой push за календарный месяц")]),
        # ложный: слово использовано в точном смысле
        cand("C-006", 37, "от 1 000 до 1 000 000 ₸ включительно", kind="ambiguity", severity="major",
             reqs=("R-05",), source="lens:analyst"),
        # ИБ, завышенный до critical
        cand("C-007", 104, "GET", kind="security", criterion="risk", severity="critical", reqs=("R-17",),
             source="lens:risk"),
        # critical без сценария
        cand("C-008", 46, "в течение минуты после получения события", kind="unverifiable",
             criterion="verifiable", severity="critical", reqs=("R-10",), source="lens:qa", scenario=""),
    ]
    # сигналы правил: нет ID у пунктов (12 мест) — одна проблема документа
    for i, ln in enumerate([23, 26, 29, 34, 43, 46, 49, 52, 117, 118, 119, 120]):
        cs.append(cand(f"C-{9 + i:03d}", ln, "", kind="other", criterion="conforming", severity="minor",
                       reqs=(), source="rules:no_id", title="Пункт без ID"))
    # фон: разные проблемы в разных местах
    lines = [37, 38, 39, 40, 43, 46, 49, 52, 63, 64, 65, 103, 104, 105, 108, 109, 117, 118, 119, 120, 121, 124,
             125, 126, 130, 142, 143, 144, 147, 148, 151, 155, 156, 157, 158, 162, 163, 165, 167, 171, 174, 175,
             176, 180, 185, 189, 192, 197, 198, 23]
    n = 21
    view = simple_view(OFFICIAL)
    text = {x["n"]: x["text"] for x in view["lines"]}
    for i, ln in enumerate(lines):
        if n > 70:
            break
        q = text[ln][:40] or "Ф-1"
        kind = ["ambiguity", "incomplete", "api_contract", "unverifiable", "terminology"][i % 5]
        cs.append(cand(f"C-{n:03d}", ln, q, kind=kind, criterion="complete", severity="major",
                       reqs=(f"R-{(i % 40) + 1:02d}",), source="lens:qa" if i % 2 else "lens:architect"))
        n += 1
    # у правил цитата должна быть: берём текст строки
    for c in cs:
        for e in c["evidence"]:
            if not e["quote"]:
                e["quote"] = text[e["line"]][:30]
    return cs


# --- тесты ------------------------------------------------------------------------------------


def test_70_candidates_all_placed_dups_merged_false_rejected():
    cs = seventy()
    assert len(cs) == 70
    ids = [c["id"] for c in cs]
    bg = [c for c in ids if int(c[2:]) >= 21]
    findings = [
        finding("F01", ["C-001", "C-002", "C-003"], severity="critical", kind="missing_element",
                criterion="set_complete", priority=2, scenario="Экран открыт: прочитать нечем.",
                impact="Нельзя реализовать экран.", reqs=("R-12", "R-16", "R-03")),
        finding("F02", ["C-004", "C-005"], severity="critical", kind="contradiction",
                criterion="set_consistent", priority=1, scenario="Уже было: да или нет.",
                impact="Две реализации.", reqs=("R-07", "R-08")),
        finding("F03", ["C-007"], severity="critical", kind="security", criterion="risk", priority=3,
                scenario="Параметры в URL.", impact="Утечка в логи."),
        finding("F04", ["C-008"], severity="critical", kind="unverifiable", criterion="verifiable",
                priority=4, scenario=""),
        finding("F05", [f"C-{i:03d}" for i in range(9, 21)], severity="major", kind="other",
                criterion="conforming", title="Пункты без ID в разделах документа"),
    ] + [finding(f"F{6 + i:02d}", [c], severity="minor", blocks="none") for i, c in enumerate(bg)]
    rejected = [{"candidate_id": "C-006", "reason_code": "exact_sense",
                 "reason": "L037: диапазон задан числами и словом «включительно».", "line": 37}]
    llm = FakeLLM(response(findings, rejected))
    ctx = Ctx(llm)
    res = judge.run(ctx, cs)

    all_placed(res, ids)
    assert len(llm.calls) == 1
    # компактная подача: > 60 кандидатов
    assert "  + C-" in llm.calls[0]["user"]
    by_title = {f["title"]: f for f in res["findings"]}
    f1 = next(f for f in res["findings"] if f["candidate_ids"] == ["C-001", "C-002", "C-003"])
    assert f1["severity"] == "critical"
    assert [e["line_start"] for e in f1["evidence"]] == [29, 52, 103]       # все места, по порядку строк
    assert f1["sources"] == ["lens:architect", "lens:analyst", "lens:qa"] or set(f1["sources"]) == {
        "lens:architect", "lens:analyst", "lens:qa"}
    assert f1["standard_refs"] == ["ISO/IEC/IEEE 29148:2018 п. 5.2.6", "IEEE 830-1998 п. 4.3.3"]
    # ИБ и critical без сценария — понижены
    sec = next(f for f in res["findings"] if f["candidate_ids"] == ["C-007"])
    assert sec["severity"] == "major"
    nfr = next(f for f in res["findings"] if f["candidate_ids"] == ["C-008"])
    assert nfr["severity"] == "major"
    # «нет ID» — одно minor
    noid = next(f for f in res["findings"] if "C-009" in f["candidate_ids"])
    assert noid["severity"] == "minor" and len(noid["candidate_ids"]) == 12
    assert len(noid["evidence"]) <= 5
    # ложный — в отклонённых с причиной
    rej = {r["candidate_id"]: r for r in res["rejected"]}
    assert rej["C-006"]["reason_code"] == "exact_sense" and rej["C-006"]["line"] == 37
    # D-xx: critical первыми, приоритеты 1…k без повторов
    assert [f["id"] for f in res["findings"][:2]] == ["D-01", "D-02"]
    assert res["findings"][0]["candidate_ids"] == ["C-004", "C-005"]
    prios = [f["priority"] for f in res["findings"] if f["priority"] > 0]
    assert sorted(prios) == list(range(1, len(prios) + 1)) and len(prios) <= 7
    assert res["fix_first"][0] == "D-01"
    # F-ключи в тексте вердикта заменены на D-xx
    assert "F01" not in res["verdict_summary"] and "D-0" in res["verdict_summary"]
    assert by_title  # реестр не пуст


def test_lost_candidates_repair_call_then_not_reviewed():
    cs = [cand("C-001", 38, "Месяц определяется по дате совершения покупки", reqs=("R-06",)),
          cand("C-002", 64, "Февральский счётчик вырос на 4 000", kind="incomplete", reqs=("R-14",)),
          cand("C-003", 46, "в течение минуты", kind="unverifiable", reqs=("R-10",)),
          cand("C-004", 105, "Bearer, сессия владельца карты", kind="terminology", reqs=("R-18",))]
    first = response([finding("F01", ["C-001"])])
    repair = {"assignments": [
        {"candidate_id": "C-002", "decision": "merge", "finding_key": "F01", "reason_code": "", "reason": "",
         "title": "", "severity": "major"},
        {"candidate_id": "C-003", "decision": "new", "finding_key": "", "reason_code": "", "reason": "",
         "title": "Время доставки не измеримо", "severity": "major"},
    ]}  # C-004 модель снова пропустила
    llm = FakeLLM(first, repair)
    ctx = Ctx(llm)
    res = judge.run(ctx, cs)
    all_placed(res, [c["id"] for c in cs])
    assert len(llm.calls) == 2
    f1 = next(f for f in res["findings"] if "C-001" in f["candidate_ids"])
    assert f1["candidate_ids"] == ["C-001", "C-002"]
    assert any(f["title"] == "Время доставки не измеримо" for f in res["findings"])
    rej = {r["candidate_id"]: r for r in res["rejected"]}
    assert rej["C-004"]["reason_code"] == "not_reviewed"
    assert rej["C-004"]["reason"] == "не рассмотрен судьёй"
    assert any("не рассмотрел" in w for w in res["warnings"])
    assert ctx.warnings  # предупреждения доходят до контекста


def test_cluster_mate_follows_representative_without_extra_call():
    cs = [cand("C-001", 39, "максимум один такой push", kind="contradiction", reqs=("R-07", "R-08")),
          cand("C-002", 39, "максимум один такой push за календарный месяц", kind="contradiction",
               reqs=("R-07", "R-08"))]
    clusters = judge.precluster(cs)
    assert clusters == [["C-001", "C-002"]]
    llm = FakeLLM(response([finding("F01", ["C-001"], kind="contradiction")]))
    res = judge.run(Ctx(llm), cs)
    assert len(llm.calls) == 1
    assert res["findings"][0]["candidate_ids"] == ["C-001", "C-002"]
    all_placed(res, ["C-001", "C-002"])


def test_duplicate_and_unknown_ids_and_double_placement():
    cs = [cand("C-001", 38, "Месяц определяется", reqs=("R-06",)),
          cand("C-002", 46, "в течение минуты", kind="unverifiable", reqs=("R-10",))]
    resp = response([finding("F01", ["C-001", "C-999"]), finding("F02", ["C-001", "C-002"])],
                    rejected=[{"candidate_id": "C-002", "reason_code": "misread", "reason": "x", "line": 0}])
    res = judge.run(Ctx(FakeLLM(resp)), cs)
    all_placed(res, ["C-001", "C-002"])
    assert res["findings"][0]["candidate_ids"] == ["C-001"]
    assert res["findings"][1]["candidate_ids"] == ["C-002"]        # в дефекте важнее, чем в отклонённых
    assert any("C-999" in w for w in res["warnings"])


def test_no_quote_candidates_rejected_before_model():
    cs = [cand("C-001", 38, "Месяц определяется"),
          {**cand("C-002", 40, "нет такой цитаты"), "evidence": [{"quote": "нет", "line": 40, "verified": "missing"}]}]
    llm = FakeLLM(response([finding("F01", ["C-001"])]))
    res = judge.run(Ctx(llm), cs)
    assert "C-002" not in llm.calls[0]["user"]
    rej = {r["candidate_id"]: r for r in res["rejected"]}
    assert rej["C-002"]["reason_code"] == "no_quote"
    all_placed(res, ["C-001", "C-002"])


def test_critical_cap_and_priorities():
    cs = [cand(f"C-{i:03d}", 30 + i * 3, f"q{i}", kind="contradiction", criterion="set_consistent",
               reqs=(f"R-{i:02d}",), extra=[(100 + i, f"p{i}")]) for i in range(1, 11)]
    view = {"lines": [{"n": 30 + i * 3, "text": f"q{i}"} for i in range(1, 11)]}
    fs = [finding(f"F{i:02d}", [f"C-{i:03d}"], severity="critical", kind="contradiction",
                  criterion="set_consistent", priority=i if i <= 3 else 0, scenario="Вход: два исхода.",
                  impact="Две реализации.") for i in range(1, 11)]
    res = judge.run(Ctx(FakeLLM(response(fs)), view=view, requirements=[]), cs)
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    assert len(crit) == 7
    assert all(f["priority"] > 0 for f in crit)
    prios = sorted(f["priority"] for f in res["findings"] if f["priority"])
    assert prios == list(range(1, 8))
    assert any("понижены до major" in w for w in res["warnings"])


def test_conflict_with_single_place_is_not_critical():
    cs = [cand("C-001", 39, "максимум один такой push", kind="contradiction", criterion="set_consistent")]
    f = finding("F01", ["C-001"], severity="critical", kind="contradiction", criterion="set_consistent",
                scenario="Вход: два исхода.", impact="Две реализации.", priority=1)
    res = judge.run(Ctx(FakeLLM(response([f]))), cs)
    assert res["findings"][0]["severity"] == "major"
    assert any("только одного места" in w for w in res["warnings"])


def test_truncation_splits_batch():
    cs = [cand(f"C-{i:03d}", 20 + i * 4, f"q{i}", kind=["ambiguity", "incomplete"][i % 2],
               reqs=(f"R-{i:02d}",)) for i in range(1, 9)]
    view = {"lines": [{"n": 20 + i * 4, "text": f"q{i}"} for i in range(1, 9)]}

    def answer(user, schema):
        ids = sorted(set(re.findall(r"^(C-\d{3}) ·", user, re.M)))
        return response([finding("F01", ids[:2]), finding("F02", ids[2:])],
                        checklist=[{"n": 1, "answer": "Да", "comment": "ок", "finding_keys": []}])

    llm = FakeLLM(Truncated("ответ обрезан (max_tokens)"), answer, answer)
    res = judge.run(Ctx(llm, view=view, requirements=[]), cs)
    assert len(llm.calls) == 3
    all_placed(res, [c["id"] for c in cs])
    assert len(res["findings"]) == 4
    assert len({f["id"] for f in res["findings"]}) == 4
    assert any("делится" in w for w in res["warnings"])


def test_model_failure_falls_back_to_code_registry():
    cs = [cand("C-001", 39, "максимум один такой push", kind="contradiction", reqs=("R-07",)),
          cand("C-002", 39, "максимум один такой push за календарный месяц", kind="contradiction",
               reqs=("R-07",)),
          cand("C-003", 46, "в течение минуты", kind="unverifiable", reqs=("R-10",), severity="critical",
               criterion="verifiable")]
    res = judge.run(Ctx(FakeLLM(RuntimeError("503 overloaded"))), cs)
    all_placed(res, ["C-001", "C-002", "C-003"])
    assert len(res["findings"]) == 2
    assert any("судья недоступен" in w for w in res["warnings"])
    assert len(res["checklist"]) == 14 and res["verdict_summary"]


def test_checklist_from_document_table():
    items = judge.find_checklist(simple_view(OFFICIAL))
    assert len(items) == 14
    assert items[0]["line"] == 72 and items[-1]["line"] == 85
    _, source = judge.checklist_items(simple_view(OFFICIAL))
    assert source == "document"


def test_checklist_bank_default_and_autofill():
    base = ROOT / "evaluation" / "dev" / "corpus" / "cases" / "autopay.base" / "source.md"
    view = simple_view(base)
    items, source = judge.checklist_items(view)
    assert source == "bank" and len(items) == 14
    cs = [cand("C-001", 33, "не позднее 5 минут", kind="unverifiable", criterion="verifiable", reqs=())]
    long_comment = " ".join(["слово"] * 50)
    check = [{"n": 1, "answer": "Да", "comment": long_comment, "finding_keys": ["F01", "F77"]},
             {"n": 99, "answer": "Да", "comment": "лишний", "finding_keys": []}]
    res = judge.run(Ctx(FakeLLM(response([finding("F01", ["C-001"], criterion="verifiable",
                                                  kind="unverifiable")], checklist=check)),
                        view=view, requirements=[]), cs)
    assert len(res["checklist"]) == 14
    assert res["checklist_source"] == "bank"
    first = res["checklist"][0]
    assert len(first["comment"].split()) <= 30 and first["finding_ids"] == ["D-01"]
    testable = next(c for c in res["checklist"] if c["item"] == "Требование может быть протестировано")
    assert testable["finding_ids"] == ["D-01"] and testable["answer"] == "Нет"   # заполнено кодом
    assert all(c["answer"] in judge.CHECK_ANSWERS for c in res["checklist"])


def test_evidence_limit_and_order():
    extra = [(30 + i, f"q{i}") for i in range(1, 9)]
    cs = [cand("C-001", 30, "q0", extra=extra[:4]), cand("C-002", 40, "q9", extra=extra[4:])]
    view = {"lines": [{"n": n, "text": "x"} for n in range(1, 60)]}
    res = judge.run(Ctx(FakeLLM(response([finding("F01", ["C-001", "C-002"])])), view=view,
                        requirements=[]), cs)
    ev = res["findings"][0]["evidence"]
    assert len(ev) == 5
    assert [e["line_start"] for e in ev] == sorted(e["line_start"] for e in ev)
    allowed = {(e["line_start"], e["quote"]) for c in cs for e in c["evidence"]}
    assert all((e["line_start"], e["quote"]) in allowed for e in ev)   # цитаты только из кандидатов


def test_texts_fall_back_to_base_candidate():
    cs = [cand("C-001", 38, "Месяц определяется", title="Заголовок кандидата")]
    f = finding("F01", ["C-001"], title="")
    f["title"] = ""
    res = judge.run(Ctx(FakeLLM(response([f]))), cs)
    d = res["findings"][0]
    assert d["title"] == "Заголовок кандидата"
    assert d["recommendation"] == "Исправить C-001." and d["scenario"] == "Вход X даёт два исхода."


def test_compute_verdict_rule():
    crit_dev = {"id": "D-01", "severity": "critical", "blocks": "development", "priority": 1}
    crit_test = {"id": "D-02", "severity": "critical", "blocks": "testing", "priority": 2}
    majors = [{"id": f"D-1{i}", "severity": "major", "blocks": "both", "priority": 0} for i in range(3)]
    assert judge.compute_verdict([crit_dev]) == {"development": "no", "testing": "yes", "fix_first": ["D-01"]}
    v = judge.compute_verdict([crit_test] + majors)
    assert v["development"] == "conditional" and v["testing"] == "no"
    assert judge.compute_verdict(majors[:2]) == {"development": "yes", "testing": "yes", "fix_first": []}
    assert judge.compute_verdict(majors[:2], "partial")["development"] == "conditional"
    assert judge.compute_verdict([], "failed")["development"] == ""


def test_empty_input():
    res = judge.run(Ctx(FakeLLM()), [])
    assert res["findings"] == [] and res["rejected"] == []
    assert len(res["checklist"]) == 14 and res["verdict_summary"]


def test_schema_is_strict_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = judge.response_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(response([finding("F01", ["C-001"])]), schema)


FORBIDDEN = ["push", "savelimit", "тиын", "порог", "алмат", "ф-1", "ф-2", "ф-3", "ф-4", "держател", "kzt", "₸"]


def test_prompt_has_no_official_document_words():
    text = (SRC / "bcc_review" / "v2" / "prompts" / "judge.md").read_text(encoding="utf-8").lower()
    assert "{{candidates}}" in text and "{{checklist}}" in text
    check = (SRC / "bcc_review" / "v2" / "prompts" / "judge_check.md").read_text(encoding="utf-8").lower()
    assert "{{findings}}" in check and "{{summary}}" in check
    for w in FORBIDDEN:
        assert w not in text, w
        assert w not in check, w


def test_severity_check_only_lowers_and_rewrites_summary():
    cs = [cand("C-001", 39, "максимум один такой push", kind="contradiction", criterion="set_consistent",
               extra=[(40, "следующее достижение вызывает push")]),
          cand("C-002", 21, "сообщение оператора связи", kind="missing_element", criterion="set_complete"),
          cand("C-003", 46, "в течение минуты", kind="unverifiable", criterion="verifiable"),
          cand("C-004", 49, "сумму покупки в тиынах", kind="unit_mismatch", criterion="correct")]
    fs = [finding("F01", ["C-001"], severity="critical", kind="contradiction", criterion="set_consistent",
                  scenario="Вход: два исхода.", impact="Две реализации.", priority=1),
          finding("F02", ["C-002"], severity="critical", kind="missing_element", criterion="set_complete",
                  scenario="Нет интерфейса.", impact="Не реализовать.", priority=2),
          finding("F03", ["C-003"], severity="major", kind="unverifiable", criterion="verifiable"),
          finding("F04", ["C-004"], severity="minor", kind="unit_mismatch", criterion="correct")]
    check = {"checks": [
        {"key": "F01", "basis": "(а) L039 и L040", "severity": "critical", "reason": ""},
        {"key": "F02", "basis": "нет обещания", "severity": "minor", "reason": "Документ не обещал интерфейс."},
        {"key": "F03", "basis": "нет основания", "severity": "minor", "reason": "Второстепенный показатель."},
        {"key": "F04", "basis": "м1", "severity": "critical", "reason": ""},   # повышать нельзя
    ], "verdict_summary": "Нельзя начинать: F01 — противоречие."}
    llm = FakeLLM(response(fs, summary="Нельзя: F01 и F02."), check)
    res = judge.run(Ctx(llm, options={}), cs)
    assert len(llm.calls) == 2
    assert "<дефекты>" in llm.calls[1]["user"] and "F04" not in llm.calls[1]["user"]   # minor не проверяется
    sev = {f["candidate_ids"][0]: f["severity"] for f in res["findings"]}
    assert sev == {"C-001": "critical", "C-002": "major", "C-003": "minor", "C-004": "minor"}
    assert res["verdict_summary"] == "Нельзя начинать: D-01 — противоречие."
    ch = {c["from"] + ">" + c["to"] for c in res["severity_changes"]}
    assert ch == {"critical>major", "major>minor"}
    assert any("проверка серьёзности" in w for w in res["warnings"])


def test_severity_check_failure_keeps_judge_levels():
    cs = [cand("C-001", 39, "максимум один такой push", kind="contradiction", criterion="set_consistent",
               extra=[(40, "следующее достижение вызывает push")])]
    fs = [finding("F01", ["C-001"], severity="critical", kind="contradiction", criterion="set_consistent",
                  scenario="Вход: два исхода.", impact="Две реализации.", priority=1)]
    res = judge.run(Ctx(FakeLLM(response(fs), RuntimeError("503")), options={}), cs)
    assert res["findings"][0]["severity"] == "critical"
    assert any("вторая проверка" in w for w in res["warnings"])


def test_repeated_keys_are_not_glued():
    cs = [cand("C-001", 38, "Месяц определяется"), cand("C-002", 46, "в течение минуты", kind="unverifiable")]
    res = judge.run(Ctx(FakeLLM(response([finding("F01", ["C-001"]), finding("F01", ["C-002"])]))), cs)
    assert len(res["findings"]) == 2
    all_placed(res, ["C-001", "C-002"])


def test_split_parts_keep_key_references():
    cs = [cand(f"C-{i:03d}", 20 + i * 4, f"q{i}", kind=["ambiguity", "incomplete"][i % 2],
               reqs=(f"R-{i:02d}",)) for i in range(1, 7)]
    view = {"lines": [{"n": 20 + i * 4, "text": f"q{i}"} for i in range(1, 7)]}

    def answer(user, schema):
        ids = sorted(set(re.findall(r"^(C-\d{3}) ·", user, re.M)))
        return response([finding("F01", ids)], summary="Главное — F01.",
                        checklist=[{"n": 1, "answer": "Нет", "comment": "См. F01.", "finding_keys": ["F01"]}])

    res = judge.run(Ctx(FakeLLM(Truncated("max_tokens"), answer, answer), view=view, requirements=[]), cs)
    assert "F01" not in res["verdict_summary"] and "D-0" in res["verdict_summary"]
    assert "F01" not in res["checklist"][0]["comment"]
    assert len(res["checklist"][0]["finding_ids"]) == 2


def test_missing_element_critical_needs_two_reviewers():
    def mk(cid, line, q, src, kind="missing_element"):
        return cand(cid, line, q, kind=kind, criterion="set_complete", source=src)
    cs = [mk("C-001", 52, "Приложение читает и сохраняет настройки", "lens:architect"),
          mk("C-002", 103, "Функциональные требования: чтение порога", "rules:promises.read_operation"),
          mk("C-003", 21, "сообщение оператора связи", "consistency"),
          cand("C-004", 46, "в течение минуты", kind="unverifiable", source="lens:qa")]
    fs = [finding("F01", ["C-001", "C-002"], severity="critical", kind="missing_element",
                  criterion="set_complete", scenario="Нечем прочитать.", impact="Экран не сделать.", priority=1),
          finding("F02", ["C-003"], severity="critical", kind="missing_element", criterion="set_complete",
                  scenario="Нет интерфейса.", impact="Не реализовать.", priority=2),
          finding("F03", ["C-004"], kind="unverifiable", criterion="verifiable")]
    res = judge.run(Ctx(FakeLLM(response(fs))), cs)
    sev = {f["candidate_ids"][0]: f["severity"] for f in res["findings"]}
    assert sev["C-001"] == "critical" and sev["C-003"] == "major"
    assert any("один ревьюер" in w for w in res["warnings"])
    # мало источников в прогоне (например, повторная проверка №11) — правило не действует
    res2 = judge.run(Ctx(FakeLLM(response([fs[1]]))), [cs[2]])
    assert res2["findings"][0]["severity"] == "critical"
