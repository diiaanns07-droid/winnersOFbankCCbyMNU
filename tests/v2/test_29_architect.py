"""№29 — линза «Архитектор»: доказательства замечаний о хранимых данных.

Замечание «атрибута нет в хранимых данных» доказывает отсутствие цитатой места, где атрибут должен быть
(системный промпт, правило 2). haiku пишет его по строке параметра и правилу, без строки перечня данных
(официальный ТЗ, замер №29 17:08) — код дописывает первую строку раздела требований к данным.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from bcc_review.v2 import docview, quotes
from bcc_review.v2.stages import lens_architect as A

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
DOCS = [str(OFFICIAL)] + sorted(glob.glob(str(ROOT / "evaluation/v2/open2/*/source.md"))) + \
    sorted(glob.glob(str(ROOT / "evaluation/v2/clean/*/source.md")))


def _c(title: str, ev: list[tuple[int, str]], kind: str = "missing_element") -> dict:
    return {"title": title, "kind": kind, "criterion": "complete", "severity": "major", "requirement_ids": [],
            "evidence": [{"quote": q, "line": n} for n, q in ev], "problem": "п", "scenario": "с", "impact": "и",
            "recommendation": "р", "rewrite": "", "question": "", "blocks": "both"}


@pytest.mark.parametrize("path", DOCS, ids=lambda p: Path(p).parent.name)
def test_data_section_found(path):
    lines = A.data_section_lines(docview.load(path))
    assert lines and all(x["text"].strip() for x in lines)


def test_data_gap_gets_data_list_quote():
    view = docview.load(OFFICIAL)
    row = next(x for x in view["lines"] if x["n"] == 144)
    c = _c("Признак enabled и атрибуты возврата не перечислены в данных", [(144, row["text"])])
    assert A.add_data_list_evidence([c], view) == 1
    data_n = A.data_section_lines(view)[0]["n"]
    assert [e["line"] for e in c["evidence"]] == [144, data_n]
    ev = dict(c["evidence"][1])
    quotes.verify_evidence(view, ev, [])
    assert ev["verified"] in ("exact", "normalized")


def test_already_cited_or_not_about_data_untouched():
    view = docview.load(OFFICIAL)
    data = A.data_section_lines(view)[0]
    cited = _c("Хранимые данные не содержат признака включения", [(data["n"], data["text"])])
    other = _c("Чтение порога обещано, но метода нет", [(52, "Приложение читает и сохраняет настройки")])
    contract = _c("Тип поля в хранимых данных и в ответе различается", [(144, "enabled")], kind="api_contract")
    full = _c("Нет атрибута в хранимых данных", [(1, "а"), (2, "б"), (3, "в")])
    assert A.add_data_list_evidence([cited, other, contract, full], view) == 0
    assert len(cited["evidence"]) == 1 and len(other["evidence"]) == 1 and len(full["evidence"]) == 3


def test_no_data_section_no_change():
    view = {"lines": [{"n": 1, "text": "Метод возвращает остаток.", "section": "API", "heading": False}]}
    c = _c("Остаток не хранится в данных", [(1, "Метод возвращает остаток.")])
    assert A.add_data_list_evidence([c], view) == 0
