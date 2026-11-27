"""№02 (F3): судья принимает ID кандидатов в записи слабой модели — «C001» вместо «C-001».

Живой прогон 27.11 (Gemini 3.1 Flash-Lite, официальный документ, ``runs/f3_lite31_official``): судья ответил
«C001…C031», ``judge.py`` не нашёл их среди кандидатов и отбросил все решения первого ответа («судья сослался на
несуществующего кандидата» ×31), повторный вызов разложил всех заново: 3 вызова и 84 с вместо одного вызова.
Gemini не принимает ``pattern`` в схеме ответа, формат держит код. Правка — в ``stages/judge.py`` (файл №10), патч
``tests/v2/fixtures/02_providers/patches/10_judge_candidate_ids.patch``; до слияния тесты помечены xfail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, cand, finding, response  # noqa: E402

pytestmark = pytest.mark.xfail(not hasattr(judge, "_canon_ids"), strict=False,
                               reason="ждёт патч №10: tests/v2/fixtures/02_providers/patches/"
                                      "10_judge_candidate_ids.patch")

NB_HYPHEN = chr(0x2011)  # неразрывный дефис


def _cands():
    return [cand("C-001", 38, "Месяц определяется по дате совершения покупки", reqs=("R-06",)),
            cand("C-002", 46, "в течение минуты", kind="unverifiable", reqs=("R-10",)),
            cand("C-003", 64, "Февральский счётчик вырос на 4 000", kind="incomplete", reqs=("R-14",))]


def _bad_id_warnings(res):
    return [w for w in res["warnings"] if "несуществующего" in w or "пропустил" in w or "не рассмотрел" in w]


def test_ids_without_hyphen_kept_in_one_call():
    cs = _cands()
    resp = response([finding("F01", ["C001"]), finding("F02", ["C003"], kind="incomplete")],
                    rejected=[{"candidate_id": "C002", "reason_code": "misread", "reason": "Цитата прочитана неверно.",
                               "line": 46}])
    llm = FakeLLM(resp)
    res = judge.run(Ctx(llm), cs)
    assert len(llm.calls) == 1  # без повторного вызова
    all_placed(res, ["C-001", "C-002", "C-003"])
    assert sorted(f["candidate_ids"][0] for f in res["findings"]) == ["C-001", "C-003"]
    assert [r["candidate_id"] for r in res["rejected"]] == ["C-002"]
    assert not _bad_id_warnings(res), res["warnings"]


def test_mixed_spelling_and_base_in_one_finding():
    cs = _cands()[:2]
    f = finding("F01", ["c-1", f"C{NB_HYPHEN}002"])
    f["base"] = "C 2"
    llm = FakeLLM(response([f]))
    res = judge.run(Ctx(llm), cs)
    assert len(llm.calls) == 1
    assert res["findings"][0]["candidate_ids"] == ["C-001", "C-002"]
    assert not _bad_id_warnings(res), res["warnings"]


def test_repair_call_ids_without_hyphen():
    cs = _cands()[:2]
    first = response([finding("F01", ["C-001"])])  # C-002 судья пропустил
    repair = {"assignments": [{"candidate_id": "C002", "decision": "merge", "finding_key": "F01", "reason_code": "",
                               "reason": "", "title": "", "severity": "major"}]}
    llm = FakeLLM(first, repair)
    res = judge.run(Ctx(llm), cs)
    assert len(llm.calls) == 2
    assert res["findings"][0]["candidate_ids"] == ["C-001", "C-002"]
    assert not any(r["candidate_id"] == "C-002" for r in res["rejected"])


def test_unknown_and_ambiguous_ids_untouched():
    out = judge._canon_ids({"findings": [{"candidate_ids": ["C999", "X001", "C-001"], "base": "C999"}],
                            "rejected": [{"candidate_id": "C1"}]}, ["C-001", "C-1"])
    assert out["findings"][0]["candidate_ids"] == ["C999", "X001", "C-001"]
    assert out["findings"][0]["base"] == "C999"
    assert out["rejected"][0]["candidate_id"] == "C1"  # два входных ID с номером 1 — не угадываем
    src = {"findings": [{"candidate_ids": ["C001"]}]}
    judge._canon_ids(src, ["C-001"])
    assert src["findings"][0]["candidate_ids"] == ["C001"]  # ответ модели не меняется на месте
