"""№09: контроль этапа consistency на записанных ответах живых моделей (без сети).

* положительный контроль — `cardblock.range_boundary.days_400_at_30`: ровно один подтверждённый конфликт
  по одному параметру (срок блокировки, значение 30) с двумя цитатами в разных строках;
* отрицательный контроль — `autopay.base` (чистая база): ни одного конфликта, в том числе между
  разными диапазонами (порог баланса и сумма пополнения);
* официальный документ: противоречие «не более одного уведомления за период» ↔ «уведомление
  независимо от истории» — critical с цитатами строк 39 и 40; глоссарий и трассировка заполнены.

Ответы записаны прогоном `claude -p` (haiku и sonnet) с промптом `prompts/consistency.md`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bcc_review.v2.stages import consistency as C

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
CORPUS = ROOT / "evaluation" / "dev" / "corpus" / "cases"
MD = re.compile(r"\*\*|__|`")


def load_view(path: Path) -> dict:
    """Строки как в docview (№03): markdown-разметка снята, номера строк — как в файле."""
    try:  # каркас v2 с docview №03
        from bcc_review.v2 import docview  # type: ignore
        return docview.load(str(path))
    except Exception:  # noqa: BLE001 — до каркаса или при другой сигнатуре
        pass
    out = []
    for i, s in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        t = MD.sub("", s).rstrip()
        t = re.sub(r"^\s*[*-]\s+", "", t)
        t = re.sub(r"^#+\s*", "", t)
        if t.strip().startswith("|") and t.strip().endswith("|"):
            cells = [c.strip() for c in t.strip().strip("|").split("|")]
            t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
        out.append({"n": i, "text": t, "page": None, "section": ""})
    return {"lines": out}


def run_recorded(doc: Path, fixture_dir: str, model: str) -> dict:
    view = load_view(doc)
    seg = FIX / ("official" if fixture_dir == "09_official" else fixture_dir) / "segment.json"
    for name in (f"segment.{model}.json", f"segment.{model.rsplit('_', 1)[0]}.json"):
        if (FIX / fixture_dir / name).exists():  # ответ получен на другой нарезке
            seg = FIX / fixture_dir / name
            break
    reqs = json.loads(seg.read_text(encoding="utf-8"))["requirements"]
    raw = json.loads((FIX / fixture_dir / f"consistency.{model}.json").read_text(encoding="utf-8"))
    return C.postprocess(raw, view, reqs)


def lines_of(c: dict) -> set[int]:
    return {e["line"] for e in c["evidence"] if e.get("verified") != "missing"}


@pytest.mark.parametrize("model", ["haiku", "sonnet"])
def test_positive_control_one_boundary_conflict_on_one_parameter(model):
    out = run_recorded(CORPUS / "cardblock.range_boundary.days_400_at_30" / "source.md", "09_cardblock_days", model)
    conflicts = [p for p in out["pair_checks"] if p["verdict"] == "conflict"]
    assert len(conflicts) == 1
    p = conflicts[0]
    assert p["same_subject"] and p["kind"] == "boundary_conflict"
    assert 86 in (p["line_a"], p["line_b"])
    assert {p["line_a"], p["line_b"]} & {25, 61}
    crit = [c for c in out["candidates"] if c["severity"] == "critical"]
    assert len(crit) == 1
    c = crit[0]
    assert c["kind"] == "boundary_conflict" and c["origin"] == "pair_check"
    assert 86 in lines_of(c) and lines_of(c) & {25, 61}
    assert len(c["evidence"]) == 2 and all(e["verified"] != "missing" for e in c["evidence"])


@pytest.mark.parametrize("model", ["haiku", "sonnet"])
def test_negative_control_clean_base_has_no_conflicts(model):
    out = run_recorded(CORPUS / "autopay.base" / "source.md", "09_autopay_base", model)
    assert [p for p in out["pair_checks"] if p["verdict"] == "conflict"] == []
    assert [c for c in out["candidates"] if c["origin"] == "pair_check" and c["severity"] == "critical"] == []
    # v1 сравнивал порог баланса (строка 25) с суммой пополнения (строка 26) — здесь такой пары нет
    for c in out["candidates"]:
        if c["kind"] in C.CONFLICT_KINDS:
            assert not ({25, 26} <= lines_of(c)), c["title"]


WAVE2 = [f"haiku_w2_{i}" for i in range(1, 16)]  # шаг 2б, `stage consistency` (effort low), 1 вызов без обрезки


@pytest.mark.parametrize("model", WAVE2)
def test_official_boundary_step_finds_acceptance_row_against_rule(model):
    """К1: критерий приёмки относит покупку на стыке месяцев не к тому месяцу, что правило."""
    out = run_recorded(ROOT / "release" / "input" / "requirements.md", "09_official", model)
    crit = [c for c in out["candidates"] if c["severity"] == "critical"]
    assert any({38, 64} <= lines_of(c) and c["kind"] in ("event_conflict", "boundary_conflict") for c in crit)
    assert not any(c["kind"] == "contradiction" for c in out["candidates"] if c["origin"] == "pair_check")


@pytest.mark.parametrize("model", ["haiku", "sonnet", "opus"] + WAVE2)
def test_official_document_set_level_findings(model):
    out = run_recorded(ROOT / "release" / "input" / "requirements.md", "09_official", model)
    crit = [c for c in out["candidates"] if c["severity"] == "critical"]
    # противоречие двух функциональных требований о числе уведомлений за период
    k2 = [c for c in crit if {39, 40} <= lines_of(c)]
    assert len(k2) == 1 and k2[0]["kind"] == "event_conflict"
    # обещанная, но не описанная операция чтения
    assert any(c["kind"] == "missing_element" and 52 in lines_of(c) for c in crit)
    # компоненты в архитектуре и последовательности названы и связаны по-разному
    assert any({26, 43} <= lines_of(c) for c in out["candidates"])
    assert any(c["kind"] == "terminology" for c in out["candidates"])
    assert len(out["glossary"]) >= 2 and all(len(g["terms"]) >= 2 for g in out["glossary"])
    # трассировка: все функциональные и нефункциональные требования, без чужих ID
    ids = {r["id"] for r in json.loads((FIX / "official" / "segment.json").read_text(encoding="utf-8"))["requirements"]}
    assert {"R-05", "R-06", "R-07", "R-08", "R-10"} <= {t["requirement_id"] for t in out["trace"]}
    for t in out["trace"]:
        assert set(t["verified_by"]) <= {"R-13", "R-14", "R-15"}
        assert set(t["implemented_by"]) <= ids
    cov = C.coverage(out["trace"])
    assert cov["verified"] <= 3 < cov["total"]
    # все кандидаты этапа подтверждены хотя бы одной найденной цитатой
    assert all(lines_of(c) for c in out["candidates"])


@pytest.mark.parametrize("model", [f"haiku_w2_{i}" for i in (7, 8, 9, 10, 11, 12, 13, 14, 15)])
def test_official_all_critical_conflicts_on_weak_model_with_one_condition_field(model):
    """Промпт с полем one_condition, haiku с effort low: К1–К4 critical в каждом прогоне."""
    out = run_recorded(ROOT / "release" / "input" / "requirements.md", "09_official", model)
    crit = [c for c in out["candidates"] if c["severity"] == "critical"]
    assert any({38, 64} <= lines_of(c) for c in crit)                       # К1
    assert any({39, 40} <= lines_of(c) for c in crit)                       # К2
    assert any(c["kind"] == "status_conflict" and lines_of(c) & {121, 163} for c in crit)  # К3
    assert any(c["kind"] == "missing_element" and 52 in lines_of(c) for c in crit)        # К4


@pytest.mark.parametrize("model", ["haiku_w2_13", "haiku_w2_14"])
def test_official_half_specified_condition_is_reported_as_undefined(model):
    """С8: Ф-4 задаёт исход только для «накопленная сумма ниже нового порога»; другая ветвь не определена."""
    out = run_recorded(ROOT / "release" / "input" / "requirements.md", "09_official", model)
    assert any(c["severity"] == "major" and c["origin"] == "pair_check" and 40 in lines_of(c) for c in out["candidates"])


@pytest.mark.parametrize("model", ["haiku_w2_2", "haiku_w2_12", "haiku_w2_13", "haiku_w3_2"])
def test_official_status_pair_gets_example_line_of_second_code(model):
    """К3 строго: модель процитировала шаг логики («вернуть результат ERROR») против статуса 400, а код 200 назвала
    только в исходе. Код добавляет строку примера из блока статуса 200 — у пары две стороны с разными кодами."""
    out = run_recorded(ROOT / "release" / "input" / "requirements.md", "09_official", model)
    crit = [c for c in out["candidates"] if c["severity"] == "critical" and c["kind"] == "status_conflict"]
    assert any(lines_of(c) & set(range(165, 172)) and lines_of(c) & {121, 151, 162, 163} for c in crit)


def test_status_example_is_searched_only_in_block_of_other_code():
    view = {"lines": [{"n": 1, "text": "400. Ответ, если параметры неверны.", "page": None, "section": ""},
                      {"n": 2, "text": "При отказе вернуть результат FAILED.", "page": None, "section": ""},
                      {"n": 3, "text": "400. Unsuccessful", "page": None, "section": ""},
                      {"n": 4, "text": '{"result":"FAILED"}', "page": None, "section": ""},
                      {"n": 5, "text": "200. Successful", "page": None, "section": ""},
                      {"n": 6, "text": '{"result":"FAILED","message":"x"}', "page": None, "section": ""}]}
    pair = {"quote_a": "400. Ответ, если параметры неверны.", "quote_b": "При отказе вернуть результат FAILED.",
            "line_a": 1, "line_b": 2, "outcome_a": "400", "outcome_b": "ответ 200 с FAILED"}
    ev = C.status_example_evidence(view, pair)
    assert ev and ev["line"] == 6  # не строка 4: она в блоке того же кода 400
    pair["quote_b"] = "При отказе вернуть отказ."  # нет значения, по которому искать пример
    assert C.status_example_evidence(view, pair) is None
