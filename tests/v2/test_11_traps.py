"""№11: пересмотр по ответам-ловушкам на реальных ответах модели (haiku, три документа, без сети).

Ответы владельца (`fixtures/11_traps/<кейс>.answers.md`) — прямые, частичные, расплывчатые, не по теме, общие
решения и пары противоречащих ответов. Ответ модели этапа recheck записан (`<кейс>.recheck.json`); тест проверяет,
что правила кода держат честность: закрывает только названный ответ, противоречащие ответы оставляют дефект
открытым, частичный ответ не понижает critical-противоречие, «новый» конфликт-дубль прежнего дефекта отклоняется.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcc_review.v2 import docview  # noqa: E402
from bcc_review.v2.stages import recheck  # noqa: E402
from test_11_clarify import FakeCtx, FakeLLM  # noqa: E402

TRAPS = ROOT / "tests" / "v2" / "fixtures" / "11_traps"
DOCS = {"official": ROOT / "release" / "input" / "requirements.md",
        "qr": ROOT / "evaluation" / "v2" / "open2" / "qr" / "source.md",
        "grace": ROOT / "evaluation" / "v2" / "open2" / "grace" / "source.md"}

# ожидания: дефект → (допустимые статусы, закрывший ответ или None); "conflict" — открыт и в списке
# противоречащих ответов. Частичный ответ: «изменён» или «открыт», но не «закрыт»; прямой — «закрыт»
# (у grace вариант A сам оказался двусмысленным — «изменён» тоже честно).
EXPECT = {
    "official": {"D-03": (("resolved",), "Q-03"), "D-25": (("resolved",), "Решение-1"),
                 "D-02": (("changed", "open"), None), "D-01": (("open",), None), "D-04": (("conflict",), None),
                 "D-05": (("open",), None)},
    "qr": {"D-01": (("resolved",), "Q-01"), "D-14": (("resolved",), "Решение-1"), "D-03": (("conflict",), None),
           "D-05": (("changed", "open"), None), "D-06": (("open",), None), "D-10": (("open", "changed"), None),
           "D-11": (("open",), None)},
    "grace": {"D-03": (("resolved",), "Q-02"), "D-02": (("resolved", "changed"), "Q-01"),
              "D-07": (("conflict",), None), "D-04": (("open",), None), "D-05": (("open", "changed"), None),
              "D-10": (("open",), None), "D-17": (("open",), None)},
}


def check(case: str, clar: dict) -> list[str]:
    """Расхождения пересмотра с ожиданиями по ловушкам (пустой список — всё честно)."""
    ch = {c["finding_id"]: c for c in clar["changes"]}
    conflicts = {c["finding_id"] for c in clar.get("answer_conflicts") or []}
    errors = []
    for fid, (ok, by) in EXPECT[case].items():
        c = ch.get(fid)
        status = c["status"] if c else "open"
        if "conflict" in ok:
            if status != "open" or fid not in conflicts:
                errors.append(f"{fid}: ждали «открыт» и противоречие ответов, получили {status}")
            continue
        if status not in ok:
            errors.append(f"{fid}: {status} ∉ {ok}: {(c or {}).get('reason', '')[:120]}")
        elif by and status == "resolved" and by not in (c.get("answer_ids") or []):
            errors.append(f"{fid}: закрыт не тем ответом: {c.get('answer_ids')}")
    allowed = {fid for fid, (ok, _) in EXPECT[case].items() if "resolved" in ok}
    extra = [c["finding_id"] for c in clar["changes"] if c["status"] == "resolved" and c["finding_id"] not in allowed]
    if extra:
        errors.append(f"лишние закрытия: {extra}")
    return errors


def _stub_judge(ctx, candidates):
    return {"findings": [{"id": "", "candidate_ids": [c["id"]], "title": c["title"], "kind": c.get("kind", "other"),
                          "criterion": c.get("criterion", "set_consistent"), "severity": c.get("severity", "major"),
                          "requirement_ids": c.get("requirement_ids", []), "evidence": c["evidence"],
                          "problem": c.get("problem", ""), "blocks": c.get("blocks", "both"), "priority": 0,
                          "sources": ["recheck"]} for c in candidates], "rejected": []}


@pytest.mark.parametrize("case", sorted(EXPECT))
def test_traps_on_recorded_model_answers(case, monkeypatch):
    from bcc_review.v2.stages import judge
    monkeypatch.setattr(judge, "run", _stub_judge)
    report = json.loads((TRAPS / f"{case}.report.json").read_text(encoding="utf-8"))
    response = json.loads((TRAPS / f"{case}.recheck.json").read_text(encoding="utf-8"))
    ctx = FakeCtx(FakeLLM(response), view=docview.load(str(DOCS[case])))
    out = recheck.apply_answers(ctx, report, str(TRAPS / f"{case}.answers.md"))
    clar = out["clarification"]
    assert check(case, clar) == []
    # частичный ответ на critical-противоречие не понижает серьёзность
    for c in clar["changes"]:
        f = next(x for x in report["findings"] if x["id"] == c["finding_id"])
        if c["status"] == "changed" and f["severity"] == "critical" and f["kind"] in recheck._cl.CONFLICT_KINDS:
            assert c["severity_after"] == "critical", c
    # «новый» конфликт не повторяет прежний дефект: дубли отклоняет код (на qr модель описала заново прежний)
    for f in out["findings_after"]:
        if f.get("status_after_answers") == "new":
            assert recheck.duplicate_of(f["evidence"], report["findings"], f["title"]) == "", f["title"]
    if case == "qr":
        assert any(r.get("reason", "").startswith("повторяет дефект") for r in out["rejected_after"])
    # причины — без номеров строк L…
    assert not any("L0" in c["reason"] or "L1" in c["reason"] for c in clar["changes"])
