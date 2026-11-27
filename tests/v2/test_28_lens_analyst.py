"""№28 — линза «Аналитик»: critical с цитатой из раздела описания API понижается до major.

Без сети: записанные ответы haiku (tests/v2/fixtures/28_analyst — промпт v28a, отклонённый по замеру вариант с обходом
тем; для проверки постобработки важны только кандидаты) и настоящие документы (docview).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from bcc_review.v2 import docview  # noqa: E402
from bcc_review.v2.stages import lens_analyst as A  # noqa: E402

FIX = ROOT / "tests" / "v2" / "fixtures" / "28_analyst"
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OPEN2 = ROOT / "evaluation" / "v2" / "open2"


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _run(view: dict, answer: dict) -> list[dict]:
    """Как `lens_analyst.run`: постобработка с флагами API по документу."""
    cands = answer["candidates"]
    return A.postprocess(cands, mature=A.maturity(view)["mature"],
                         api_flags=A.touches_api(view, cands, A.api_lines(view)))


def test_api_lines_are_rest_part():
    view = docview.load(OFFICIAL)
    api = A.api_lines(view)
    assert 118 in api and 163 in api  # логика метода, статусы
    assert not ({23, 38, 39, 40, 46, 49, 64} & api)  # цели, правила, НФТ, данные, приёмка


def test_api_side_critical_is_major_on_clean_doc():
    """grace_clean (чистое ТЗ №18): «шаг 3 метода берёт платежи после даты выписки ↔ платёж уменьшает сумму» —
    ложный critical haiku (тот же шаблон у №05 на v23). Цитата шага логики метода → major с подсказкой судье."""
    view = docview.load(OPEN2 / "grace_clean" / "source.md")
    out = _run(view, _json(FIX / "grace_clean.haiku-v28a.json"))
    assert not [c for c in out if c["severity"] == "critical"]
    hinted = [c for c in out if c.get("severity_hint") == "critical"]
    assert len(hinted) == 1 and hinted[0]["severity"] == "major"


@pytest.mark.parametrize("name", ["official", "official_r2"])
def test_official_month_conflict_stays_critical(name):
    """Официальный: «по дате совершения или проведения» (правило ↔ критерий приёмки, без API) — critical (К1)."""
    view = docview.load(OFFICIAL)
    out = _run(view, _json(FIX / f"{name}.haiku-v28a.json"))
    crit = [c for c in out if c["severity"] == "critical"]
    assert crit and all(64 in [e.get("line") for e in c["evidence"]] or 40 in [e.get("line") for e in c["evidence"]]
                        for c in crit)
    assert any(64 in [e.get("line") for e in c["evidence"]] for c in crit)


def test_no_document_means_old_behaviour():
    d = _json(FIX / "grace_clean.haiku-v28a.json")
    old = A.postprocess(d["candidates"], mature=False)
    assert [c["severity"] for c in old].count("critical") == 1


def test_touches_api_uses_verified_line():
    """Строка модели сбита (999) — раздел берётся по найденной цитате."""
    view = docview.load(OFFICIAL)
    quote = view["lines"][117]["text"][:60]
    flags = A.touches_api(view, [{"evidence": [{"quote": quote, "line": 999}]},
                                 {"evidence": [{"quote": view["lines"][37]["text"][:60], "line": 120}]}],
                          A.api_lines(view))
    assert flags == [True, False]
