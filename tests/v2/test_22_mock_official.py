"""№22 — записанный ответ mock-судьи (``tests/v2/fixtures/official/judge.json``) сходится с кандидатами текущего кода.

Ответ судьи ссылается на кандидатов по номерам (C-001…). Новое правило, линза или нарезка сдвигают номера — и в
mock-демо под заголовком дефекта оказываются чужие цитаты, а предупреждений «несуществующего кандидата» нет.
Упал — перенумеруйте ответ судьи на новых кандидатах (по источнику и заголовку, новых — в их дефекты) и обновите
``tests/v2/fixtures/22_mock_judge_candidates.json`` (номер → [источник, заголовок])."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
JUDGE = ROOT / "tests" / "v2" / "fixtures" / "official" / "judge.json"
PRINTS = ROOT / "tests" / "v2" / "fixtures" / "22_mock_judge_candidates.json"


def test_mock_judge_matches_current_candidates(tmp_path):
    from bcc_review.v2.__main__ import main
    out = tmp_path / "m.md"
    assert main([str(OFFICIAL), str(out), "--provider", "mock", "--runs-dir", str(tmp_path / "runs"), "--no-html",
                 "--no-cache", "-q"]) in (0, 1)
    run = next((tmp_path / "runs").iterdir())
    cands = json.loads((run / "stages" / "quotes.json").read_text(encoding="utf-8"))["output"]["candidates"]
    now = {c["id"]: [c.get("source"), c.get("title")] for c in cands}
    recorded = json.loads(PRINTS.read_text(encoding="utf-8"))
    moved = {i: (recorded.get(i), now.get(i)) for i in set(recorded) | set(now) if recorded.get(i) != now.get(i)}
    assert not moved, f"кандидаты официального mock изменились — перенумеруйте ответ судьи: {sorted(moved.items())[:5]}"
    fx = json.loads(JUDGE.read_text(encoding="utf-8"))[0]
    used = {c for f in fx["findings"] for c in f["candidate_ids"]} | {r["candidate_id"] for r in fx.get("rejected") or []}
    assert used == set(now), (sorted(used - set(now)), sorted(set(now) - used))
    rep = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert not [w for w in rep["run"].get("warnings") or [] if "судья пропустил" in w or "несуществующ" in w]
