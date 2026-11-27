"""Повтор живого ответа судьи (sonnet) на реальных кандидатах линз — без сети.

Фикстуры `tests/v2/fixtures/10_judge/`: кандидаты линз (аналитик sonnet и haiku, набор, риски) с уже сверенными
цитатами и сохранённый ответ модели-судьи. Тест проверяет сборку реестра кодом на реальных данных.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, simple_view  # noqa: E402

FX = ROOT / "tests" / "v2" / "fixtures" / "10_judge"


def replay(case: str, doc: Path, segment: Path):
    cands = json.loads((FX / f"{case}.candidates.json").read_text(encoding="utf-8"))["candidates"]
    resp = json.loads((FX / f"{case}.judge_sonnet.json").read_text(encoding="utf-8"))
    check = FX / f"{case}.check_sonnet.json"
    reqs = json.loads(segment.read_text(encoding="utf-8"))["requirements"]
    for i, r in enumerate(reqs, 1):
        r.setdefault("id", f"R-{i:02d}")
    if check.exists():
        llm = FakeLLM(resp, json.loads(check.read_text(encoding="utf-8")))
        ctx = Ctx(llm, view=simple_view(doc), requirements=reqs, options={})
    else:
        llm = FakeLLM(resp)
        ctx = Ctx(llm, view=simple_view(doc), requirements=reqs)
    res = judge.run(ctx, cands)
    return cands, res, llm


def lines(f):
    return {e["line_start"] for e in f["evidence"]}


def test_official_replay():
    cands, res, llm = replay("official", ROOT / "release/input/requirements.md",
                             ROOT / "tests/v2/fixtures/official/segment.json")
    assert len(llm.calls) == 1
    all_placed(res, [c["id"] for c in cands])
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    assert 2 <= len(crit) <= 7
    # К1 (38↔64), К2 (39↔40) подтверждены двумя-тремя линзами — critical
    for need in ({38, 64}, {39, 40}):
        assert any(need <= lines(f) for f in crit), need
    # К3 и К4 в этом неполном наборе (нет архитектора, тестировщика и правил) нашёл один ревьюер → major;
    # в полном конвейере их подтверждают 3–4 источника (test_official_full_69_candidates_replay)
    for need in ({52, 103}, {121, 163}):
        f = next(f for f in res["findings"] if need <= lines(f))
        assert f["severity"] == "major", need
    assert any("один ревьюер" in w for w in res["warnings"])
    assert 15 <= len(res["findings"]) <= 45
    assert res["checklist_source"] == "document" and len(res["checklist"]) == 14
    v = judge.compute_verdict(res["findings"])
    assert v["development"] == "no" and v["testing"] == "no"
    assert all(f["priority"] == 0 for f in res["findings"] if f["severity"] == "minor")
    for f in res["findings"]:
        assert 1 <= len(f["evidence"]) <= 5 and f["standard_refs"] and f["sources"]
        assert all(e["verified"] != "missing" for e in f["evidence"])


def test_clean_base_replay():
    base = ROOT / "evaluation/dev/corpus/cases/autopay.base/source.md"
    cands, res, _ = replay("autopay.base", base, ROOT / "tests/v2/fixtures/autopay.base/segment.json")
    all_placed(res, [c["id"] for c in cands])
    assert not [f for f in res["findings"] if f["severity"] == "critical"]
    v = judge.compute_verdict(res["findings"])
    assert v["development"] != "no" and v["testing"] != "no"
    assert res["checklist_source"] == "bank" and len(res["checklist"]) == 14


def test_official_full_69_candidates_replay():
    """69 кандидатов (4 линзы, набор, правила) → компактная подача, 25–45 дефектов, К1–К5 critical."""
    cands, res, llm = replay("official.full", ROOT / "release/input/requirements.md",
                             ROOT / "tests/v2/fixtures/official/segment.json")
    assert len(cands) == 69 and len(llm.calls) == 2
    assert "  + C-" in llm.calls[0]["user"]          # компактная подача кластеров
    all_placed(res, [c["id"] for c in cands])
    assert 25 <= len(res["findings"]) <= 45
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    assert 3 <= len(crit) <= 7
    # К1 (38↔64), К2 (39↔40), К4 (52/103), К3 (121/163), К5 (событие: 23/38/46)
    for need in ({38, 64}, {39, 40}, {52, 103}, {121, 163}, {23, 38, 46}):
        assert any(need <= lines(f) for f in crit), need
    assert "severity_changes" in res                 # вторая проверка выполнена (её вызов — второй)
    assert not any(f["severity"] == "critical" and f["kind"] in judge.NEVER_CRITICAL_KINDS for f in res["findings"])


def test_clean_base_full_replay():
    base = ROOT / "evaluation/dev/corpus/cases/autopay.base/source.md"
    cands, res, _ = replay("autopay.base.full", base, ROOT / "tests/v2/fixtures/autopay.base/segment.json")
    all_placed(res, [c["id"] for c in cands])
    assert not [f for f in res["findings"] if f["severity"] == "critical"]
    assert judge.compute_verdict(res["findings"])["development"] != "no"


def test_planted_false_candidates_are_rejected():
    """69 реальных + 4 подмешанных ложных кандидата (C-070…C-073): все ложные — в rejected с причиной."""
    cands, res, _ = replay("official.fakes", ROOT / "release/input/requirements.md",
                           ROOT / "tests/v2/fixtures/official/segment.json")
    all_placed(res, [c["id"] for c in cands])
    rej = {r["candidate_id"]: r for r in res["rejected"]}
    assert set(rej) == {"C-070", "C-071", "C-072", "C-073"}
    assert rej["C-070"]["reason_code"] == "exact_sense"
    assert rej["C-071"]["reason_code"] == "misread"
    assert all(r["reason"] and r["evidence"] and r["problem"] for r in rej.values())
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    for need in ({38, 64}, {39, 40}, {52, 103}, {121, 163}):
        assert any(need <= lines(f) for f in crit), need


def _replay_w2(name: str, doc: Path):
    """Вторая волна: входы судьи из полного конвейера (линзы, набор, правила) и сырые ответы модели."""
    data = json.loads((FX / f"{name}.w2.input.json").read_text(encoding="utf-8"))
    resp = json.loads((FX / f"{name}.w2.responses.json").read_text(encoding="utf-8"))
    from bcc_review.v2 import docview
    llm = FakeLLM(*resp)
    res = judge.run(Ctx(llm, view=docview.load(str(doc)), requirements=data["requirements"], options={}),
                    data["candidates"])
    return data["candidates"], res


def test_wave2_official_k1_k5_critical_with_consensus():
    cands, res = _replay_w2("official", ROOT / "release/input/requirements.md")
    all_placed(res, [c["id"] for c in cands])
    crit = [f for f in res["findings"] if f["severity"] == "critical"]
    for need in ({38, 64}, {39, 40}, {52, 103}, {121, 163}, {23, 38}):
        assert any(need <= lines(f) for f in crit), need
    assert all(len({s.split(":")[0] if s.startswith("rules:") else s for s in f["sources"]}) >= 2 for f in crit)
    assert 25 <= len(res["findings"]) <= 40


def test_wave2_clean_new_tz_has_no_critical():
    cands, res = _replay_w2("grace_clean", ROOT / "evaluation/v2/open2/grace_clean/source.md")
    all_placed(res, [c["id"] for c in cands])
    assert not [f for f in res["findings"] if f["severity"] == "critical"]
    assert judge.compute_verdict(res["findings"])["development"] != "no"
    assert res["checklist_source"] == "document" and len(res["checklist"]) >= 10
