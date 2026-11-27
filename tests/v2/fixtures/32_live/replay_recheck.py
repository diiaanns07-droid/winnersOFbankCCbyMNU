"""Повтор режима ``--answers`` на записанном живом прогоне — без вызовов модели.

Записи: живые прогоны sonnet 27.11 (код `d28d593b`) с ответами экзамена F4 — ``official`` (уведомления о расходах) и
``qr`` (перевод по QR): ``report_before.json`` — отчёт до ответов (вопросы, дефекты), ``recheck_response.json`` и
``revise_response.json`` — что ответила модель. Ответы — из ветки ``codex/f4-precision-audit`` (в репозиторий
не копируются):

    git archive origin/codex/f4-precision-audit docs/plan-v2/f4/answers_exam | tar -x -C /tmp/f4
    python tests/v2/fixtures/32_live/replay_recheck.py tests/v2/fixtures/32_live/qr /tmp/f4/docs/plan-v2/f4/answers_exam/qr/answers.md

Печатает конфликты ответов, следующий круг, цели и проверки редакции — после правки кода пересмотра видно, что
изменилось на тех же ответах модели.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "v2"))

from bcc_review.v2.stages import recheck, revise  # noqa: E402
from test_11_clarify import FakeCtx, FakeLLM  # noqa: E402


def main(rec: Path, answers: str) -> None:
    before = json.loads((rec / "report_before.json").read_text(encoding="utf-8"))
    resp = json.loads((rec / "recheck_response.json").read_text(encoding="utf-8"))[0]
    c = recheck.apply_answers(FakeCtx(FakeLLM(resp)), before, answers)["clarification"]
    print("конфликты ответов:", [(x["finding_id"] or x.get("question_id", ""), x["answers"]) for x in c["answer_conflicts"]])
    print("следующий круг:", [(n["kind"], n["question_id"]) for n in c["next_round"]])
    print("закрыто / изменено / открыто:", c["resolved"], c["changed"], c["open"])
    print("без ответа:", c["unanswered"], "отложено:", [p["question_id"] for p in c["postponed"]])
    print("решения — цели редакции:", [t["id"] for t in revise.decision_targets(c)])
    raw = json.loads((rec / "revise_response.json").read_text(encoding="utf-8"))
    raw = raw[0] if isinstance(raw, list) else raw
    rws = [{"finding_id": x["finding_id"], "answer_ids": [], "edits": x.get("edits") or []}
           for x in raw.get("rewrites") or []]
    w: list[str] = []
    kept = revise.check_values(rws, c, [], {}, w)
    print("правок модели:", sum(len(x["edits"]) for x in rws), "→ после проверки спорных значений:",
          sum(len(x["edits"]) for x in kept))
    for x in w:
        if "расходятся" in x:
            print("  -", x[:200])


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
