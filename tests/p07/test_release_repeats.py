"""Повторы цитат в выпущенных офлайн-отчётах ``release/``: что доказывает verify, а что нет.

Одинаковое написание в источнике само по себе не доказывает выбор нужной ячейки. verify
пересчитывает место по координатам reader (страница, блок, таблица, строка, столбец) и считает
повтор подтверждённым, только если отчёт выделяет вхождение собственным признаком: опорой
требования или подписью факта (``field``) в ячейке. Иначе — «неоднозначно» с указанием ячейки.

Вход: ``release/reports/offline/requirements_pdf.json`` + ``release/input/requirements.pdf`` (reader №02,
нужен pymupdf) и та же проверка для ``requirements.json`` + ``requirements.md`` (reader №01).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bcc_review import contracts as C
from bcc_review.verification import verify_report

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release"
PDF = pytest.param(("requirements_pdf.json", "requirements.pdf", 323), id="pdf",
                   marks=pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None,
                                            reason="reader №02 PDF требует pymupdf"))
MD = pytest.param(("requirements.json", "requirements.md", 333), id="md")

pytestmark = pytest.mark.skipif(not (RELEASE / "reports/offline/requirements_pdf.json").exists(),
                                reason="в ветке нет release/ (bcc/integration до 2821989)")


def load(report: str) -> dict:
    return json.loads((RELEASE / "reports/offline" / report).read_text(encoding="utf-8"))


def fact(report: dict, fid: str) -> dict:
    return next(f for f in report["facts"] if f["id"] == fid)


def check(tmp_path: Path, report: dict, source: str, name: str = "report.json") -> dict:
    path = tmp_path / name
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return verify_report(path, RELEASE / "input" / source)


@pytest.fixture(scope="module", params=[PDF, MD])
def pair(request: pytest.FixtureRequest) -> tuple[str, str, int, dict]:
    report_name, source, checked = request.param
    result = verify_report(RELEASE / "reports/offline" / report_name, RELEASE / "input" / source)
    return report_name, source, checked, result


def test_counts_and_repeats_grouped_into_places(pair: tuple) -> None:
    _, _, checked, result = pair
    assert result["ok"], result["errors"][:3]
    c = result["counts"]
    # до правки: 14 «неоднозначно» (каждое повторное написание в блоке); после — только не выделенные отчётом
    assert {k: c[k] for k in ("checked", "confirmed", "ambiguous", "rejected")} == \
        {"checked": checked, "confirmed": checked - 2, "ambiguous": 2, "rejected": 0}
    assert c["repeats"] == {"objects": 14, "places": 8, "places_distinguished": 6, "places_undistinguished": 2}
    places = {(p["quote"], p.get("cell"), p.get("header")): p["status"] for p in result["repeats"]}
    assert places[("50 000 ₸", 0, "Исходные условия")] == "distinguished"
    assert places[("50 000 ₸", 2, "Ожидаемый результат")] == "distinguished"
    assert places[("enabled", 0, "Parameter")] == "undistinguished"
    assert all(len(p["refs"]) in (1, 2) for p in result["repeats"])


def test_place_is_recomputed_from_reader(pair: tuple) -> None:
    report_name, _, _, result = pair
    porog = next(p for p in result["repeats"] if p["quote"] == "50 000 ₸" and p.get("cell") == 0)
    assert porog["row"] == 1 and sorted(porog["refs"]) == ["facts[4].cells.value", "facts[4].evidence[0]"]
    if report_name.endswith("_pdf.json"):
        assert porog["page"] == 2 and porog["table"] == "T2"
    else:  # строка исходника, найденная независимо от reader
        raw = (RELEASE / "input/requirements.md").read_text(encoding="utf-8").split("\n")
        assert porog["line"] == next(n for n, line in enumerate(raw, 1) if "порог 50 000 ₸" in line) == 63
    assert "подпись «порог» есть только в этой ячейке" in porog["verdicts"][0]["detail"]


def test_control_other_occurrence_is_rejected(tmp_path: Path, pair: tuple) -> None:
    """C1: обе опоры факта «порог» переставлены на «50 000 ₸» ячейки «Итог …» — написание то же."""
    report_name, source, _, _ = pair
    report = load(report_name)
    f = fact(report, "FX-005")
    twin = f["cells"]["value"]["start"] + 46  # второе «50 000 ₸» той же строки таблицы
    for ev in (f["evidence"][0], f["cells"]["value"]):
        ev.update(start=twin, end=twin + 8)
    result = check(tmp_path, report, source)
    assert not result["ok"] and result["exit_code"] == C.EXIT_VERIFY_FAILED
    errors = [e for e in result["errors"] if e["code"] == "fact_wrong_cell"]
    assert sorted(e["path"] for e in errors) == ["facts[4].cells.value", "facts[4].evidence[0]"]
    assert "столбец 3 «Ожидаемый результат»" in errors[0]["message"]
    assert "столбец 1 «Исходные условия»" in errors[0]["message"]


def test_control_wrong_quote_is_rejected(tmp_path: Path, pair: tuple) -> None:
    """C2: цитата значения «порог» заменена на «500 000 ₸», координаты прежние."""
    report_name, source, _, _ = pair
    report = load(report_name)
    fact(report, "FX-005")["cells"]["value"]["quote"] = "500 000 ₸"
    result = check(tmp_path, report, source)
    assert [(e["code"], e["path"]) for e in result["errors"]] == \
        [("evidence_quote_mismatch", "facts[4].cells.value")]
    assert "по координатам «50 000 ₸», в отчёте «500 000 ₸»" in result["errors"][0]["message"]


def test_limit_same_label_in_both_cells(tmp_path: Path, pair: tuple) -> None:
    """C1b: «enabled» перенесено в столбец DB field. Подпись факта есть в обоих столбцах — доказать нечем.

    verify не подтверждает и не отклоняет: «неоднозначно» с вычисленной ячейкой. Как только отчёт
    заявляет столбец (``loc.header``), verify сверяет его с ячейкой reader и отклоняет подмену.
    """
    report_name, source, _, _ = pair
    report = load(report_name)
    field = fact(report, "FX-016")["cells"]["field"]
    field.update(start=64, end=71)
    result = check(tmp_path, report, source)
    assert result["ok"]
    warn = next(w for w in result["warnings"] if w["path"] == "facts[15].cells.field")
    assert "столбец 7 «DB field»" in warn["message"] and "нет признака" in warn["message"]
    field["loc"] = {"header": "Parameter"}
    claimed = check(tmp_path, report, source, "claimed.json")
    assert [(e["code"], e["path"]) for e in claimed["errors"]] == [("evidence_loc_mismatch", "facts[15].cells.field")]
    assert "header: в отчёте 'Parameter', по reader 'DB field'" in claimed["errors"][0]["message"]


def test_cli_defense_example(tmp_path: Path) -> None:
    """Пример для защиты через штатную команду: верная пара → 0, «порог» на чужом «50 000 ₸» → 4."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])}
    source = RELEASE / "input/requirements.md"
    ok = subprocess.run([sys.executable, "-m", "bcc_review", "verify",
                         RELEASE / "reports/offline/requirements.json", source],
                        capture_output=True, text=True, encoding="utf-8", env=env, timeout=180)
    assert ok.returncode == 0 and ok.stdout.startswith("verify: OK")
    report = load("requirements.json")
    f = fact(report, "FX-005")
    for ev in (f["evidence"][0], f["cells"]["value"]):
        ev.update(start=70, end=78)
    path = tmp_path / "moved.json"
    path.write_text(json.dumps(copy.deepcopy(report), ensure_ascii=False), encoding="utf-8")
    bad = subprocess.run([sys.executable, "-m", "bcc_review", "verify", path, source],
                         capture_output=True, text=True, encoding="utf-8", env=env, timeout=180)
    assert bad.returncode == C.EXIT_VERIFY_FAILED
    assert "fact_wrong_cell facts[4].cells.value" in bad.stderr and "«порог»" in bad.stderr
