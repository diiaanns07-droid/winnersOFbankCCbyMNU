"""№29 — страховка линзы «Риски»: возврат в закрытый период после совершённого действия (раздел 4 промпта).

Возврат относится к периоду исходной операции, по итогу периода документ совершает действие или ограничивает их
число, а что делать с уже совершённым действием, нигде не сказано. Модель пишет это не всегда (замер №29: 1 из 3,
прогоны №31 18:45: 3 из 5) — код добавляет major с цитатами обоих правил. На чистых документах молчит.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview, quotes
from bcc_review.v2.stages import lens_risk as R

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OTHER = sorted(glob.glob(str(ROOT / "evaluation/v2/open2/*/source.md"))) + \
    sorted(glob.glob(str(ROOT / "evaluation/v2/clean/*/source.md"))) + \
    sorted(glob.glob(str(ROOT / "evaluation/dev/corpus/cases/*/source.md")))


def test_official_rules_found_and_quotes_verify():
    view = docview.load(OFFICIAL)
    out = R.refund_candidates([], view)
    assert len(out) == 1 and out[0]["severity"] == "major" and out[0]["kind"] == "incomplete"
    for e in out[0]["evidence"]:
        ev = dict(e)
        quotes.verify_evidence(view, ev, [])
        assert ev["verified"] in ("exact", "normalized")
    assert "Возврат" in out[0]["evidence"][0]["quote"] and " за " in out[0]["evidence"][1]["quote"]


def test_model_refund_remark_prevents_fallback():
    view = docview.load(OFFICIAL)
    model = [{"title": "Возврат после отправленного уведомления: исход не описан"}]
    assert R.refund_candidates(model, view) == []


@pytest.mark.parametrize("path", OTHER, ids=lambda p: Path(p).parent.name)
def test_silent_on_other_documents(path):
    assert R.refund_closed_period_lines(docview.load(path)) is None


def test_outcome_described_or_period_bounded():
    base = [{"n": 1, "text": "Возврат уменьшает итог месяца исходной покупки.", "section": "Ф"},
            {"n": 2, "text": "Клиенту приходит не более одного сообщения за календарный месяц.", "section": "Ф"}]
    assert R.refund_closed_period_lines({"lines": base}) is not None
    told = base + [{"n": 3, "text": "Возврат не отменяет уже отправленное сообщение.", "section": "Ф"}]
    assert R.refund_closed_period_lines({"lines": told}) is None
    bounded = [{"n": 1, "text": "Возврат, отражённый позже окончания периода, уменьшает итог исходной операции.",
                "section": "Ф"}, base[1]]
    assert R.refund_closed_period_lines({"lines": bounded}) is None


def test_saved_n08_answers_recover_c10():
    """32 сохранённых ответа линзы по официальному ТЗ (фикстуры №08): С10 у линзы 26 → 30 (в двух модель пишет своё
    замечание о возврате не о закрытом периоде — страховка его не дублирует)."""
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "v2" / "fixtures" / "29_measure"))
    import measure as M
    view = docview.load(OFFICIAL)
    n = got = 0
    for p in sorted(glob.glob(str(ROOT / "tests/v2/fixtures/08_risk/official_*.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        d = d[0] if isinstance(d, list) else d
        cands = d.get("candidates") or (d.get("output") or {}).get("candidates")
        if cands is None:
            continue
        first, _ = R.postprocess(cands, view)
        kept, _ = R.postprocess(R.refund_candidates(first, view) + cands, view)
        ver = quotes.verify_candidates(view, json.loads(json.dumps(kept)), [])["candidates"]
        got += "С10" in M.lens_matches("official", ver)
        n += 1
    assert n >= 30 and got >= n - 2
