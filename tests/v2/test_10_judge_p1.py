"""P1 (ложные critical на чистых ТЗ): подтверждение critical-противоречия вторым ревьюером.

Живой haiku на релизе `d629aa0` (12 чистых ТЗ) дал два ложных critical — оба противоречия одного ревьюера:
grace_v2 (сосед по тем же строкам — пропуск другого предмета) и insurance_v2 (только попарная сверка набора).
Неопределённое ключевое событие (К4 на open2, К5 на официальном) подтверждается соседом по строкам, как раньше.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))

from test_10_judge import Ctx, FakeLLM, cand, finding, response  # noqa: E402

from bcc_review.v2.stages import judge  # noqa: E402

TITLE = "Отказ после погашения: возврат по Ф-4 против 409 в методе"
SCEN = "Кредит погашен 5 марта, отказ 8 марта: по Ф-4 премия возвращается, по методу 3 — 409."


def _background() -> list[dict]:
    """Ещё три источника в прогоне — правило двух ревьюеров действует."""
    return [cand("C-090", 90, "другое место", kind="unverifiable", source="lens:qa", reqs=()),
            cand("C-091", 95, "ещё место", kind="ambiguity", source="lens:risk", reqs=()),
            cand("C-092", 99, "версия", kind="placeholder", source="rules:placeholder.version", reqs=())]


def _main(cid: str = "C-001", *, kind: str = "contradiction", source: str = "consistency", origin: str = "") -> dict:
    return cand(cid, 40, "Клиент может отказаться от страхования в течение 14 дней", kind=kind,
                criterion="set_consistent" if kind != "ambiguity" else "unambiguous", source=source,
                origin=origin, reqs=(), title=TITLE, scenario=SCEN,
                extra=[(124, "409 — отказ невозможен: страхование прекращено погашением отказа")])


def _run(cands: list[dict], kind: str = "contradiction") -> str:
    crit = "unambiguous" if kind == "ambiguity" else "set_consistent"
    fs = [finding("F01", ["C-001"], severity="critical", kind=kind, criterion=crit, priority=1, title=TITLE,
                  scenario=SCEN, impact="Клиент получит отказ вместо возврата премии.")]
    fs += [finding(f"F{i:02d}", [c["id"]], severity="minor", kind=c["kind"], criterion=c["criterion"])
           for i, c in enumerate(cands[1:], 2)]
    res = judge.run(Ctx(FakeLLM(response(fs)), requirements=[]), cands)
    return next(f["severity"] for f in res["findings"] if "C-001" in f["candidate_ids"])


def test_conflict_from_pair_check_alone_is_not_critical():
    assert _run([_main(origin="pair_check")] + _background()) != "critical"


def test_conflict_from_acceptance_line_stays_critical():
    assert _run([_main(source="lens:qa", origin="acceptance_check")] + _background()) == "critical"


def test_conflict_confirmed_by_other_reviewer_conflict_on_same_lines():
    other = cand("C-010", 40, "в течение 14 дней", kind="status_conflict", source="lens:architect", reqs=(),
                 extra=[(124, "409")])
    assert _run([_main(), other] + _background()) == "critical"


def test_conflict_with_neighbour_of_other_kind_is_not_critical():
    """Сосед цитирует те же строки, но про другое (пропуск) — второго мнения о противоречии нет."""
    other = cand("C-010", 40, "в течение 14 дней", kind="incomplete", criterion="set_complete",
                 source="lens:analyst", reqs=(), extra=[(124, "409")])
    assert _run([_main(), other] + _background()) != "critical"


def test_conflict_with_two_reviewers_in_one_finding_stays_critical():
    second = _main("C-002", source="lens:analyst")
    cands = [_main(), second] + _background()
    fs = [finding("F01", ["C-001", "C-002"], severity="critical", kind="contradiction", criterion="set_consistent",
                  priority=1, title=TITLE, scenario=SCEN, impact="Клиент получит отказ вместо возврата премии.")]
    fs += [finding(f"F{i:02d}", [c["id"]], severity="minor", kind=c["kind"], criterion=c["criterion"])
           for i, c in enumerate(cands[2:], 2)]
    res = judge.run(Ctx(FakeLLM(response(fs)), requirements=[]), cands)
    assert res["findings"][0]["severity"] == "critical"


def test_key_event_ambiguity_still_confirmed_by_neighbour_of_other_kind():
    """К4/К5: «событие не определено» одной линзы держится соседом другого вида по тем же строкам."""
    main = _main(kind="ambiguity", source="lens:risk")
    other = cand("C-010", 40, "в течение 14 дней", kind="incomplete", criterion="set_complete",
                 source="lens:qa", reqs=(), extra=[(124, "409")])
    assert _run([main, other] + _background(), kind="ambiguity") == "critical"
