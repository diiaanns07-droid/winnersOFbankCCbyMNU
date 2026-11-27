"""№26, промпт 45: неописанная ветка логики ревьюера и существенный сигнал правила кода о другом предмете —
два дефекта, даже если судья склеил их в один («состав полей ответа»). Незначительный сигнал правила и сигнал
о том же предмете остаются местом дефекта. Без сети."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from test_10_judge import finding, response  # noqa: E402
from test_26_judge_merge import API, STATUS, _by, _c, _run  # noqa: E402

BRANCH = "Ветка логики без ответа: прежнее состояние при отклонении значения"
RULE = "Ответы 400 и 500 без поля result из таблицы ответа"


def _cands(rule_severity="major", rule_title=RULE, branch_kind="api_contract", branch_severity="major"):
    return [
        _c("C-001", 121, "при отклонении вернуть прежнее состояние настройки", API, kind=branch_kind,
           severity=branch_severity, title=BRANCH, reqs=("R-16",)),
        _c("C-002", 180, "ошибка 400 без поля result в примере ответа", STATUS, source="rules:api.result_field_missing",
           severity=rule_severity, kind="api_contract", title=rule_title, reqs=("R-29",)),
        _c("C-003", 104, "Метод изменяет данные запросом чтения", API, kind="api_contract", reqs=("R-16",)),
    ]


def _glued(severity="minor", base="C-001"):
    f = finding("F01", ["C-001", "C-002"], severity=severity, kind="api_contract",
                title="Состав полей ответа при ошибках не определён", reqs=("R-16", "R-29"))
    f["base"], f["problem"] = base, "Шаг 5 требует прежнее состояние (L121), а ответы 400 (L180) без поля result."
    return response([f, finding("F02", ["C-003"], kind="api_contract", reqs=("R-16",))])


def test_branch_and_major_rule_signal_become_two_findings():
    res = _run(_glued(), _cands())
    branch, rule = _by(res, "C-001"), _by(res, "C-002")
    assert branch is not rule
    assert branch["candidate_ids"] == ["C-001"] and rule["candidate_ids"] == ["C-002"]
    assert not any(f["severity"] == "critical" for f in res["findings"])


def test_split_whichever_part_is_judge_base():
    res = _run(_glued(base="C-002"), _cands())
    assert _by(res, "C-001") is not _by(res, "C-002")


def test_minor_rule_signal_stays_place_of_finding():
    res = _run(_glued(), _cands(rule_severity="minor"))
    assert _by(res, "C-001") is _by(res, "C-002")


def test_same_subject_rule_signal_stays_place_of_finding():
    res = _run(_glued(), _cands(rule_title="Ветка логики без ответа: в ответе нет прежнего состояния"))
    assert _by(res, "C-001") is _by(res, "C-002")


def test_minor_or_other_kind_lens_part_not_split():
    res = _run(_glued(), _cands(branch_severity="minor"))
    assert _by(res, "C-001") is _by(res, "C-002")
    res = _run(_glued(), _cands(branch_kind="ambiguity"))
    assert _by(res, "C-001") is _by(res, "C-002")


def test_off_switch():
    res = _run(_glued(), _cands(), judge_split_rule_branch=False)
    assert _by(res, "C-001") is _by(res, "C-002")
