"""Стык с контрактом v1 (bcc/integration, contracts.py от Max).

Фикстуры p17 проходят ``contracts.validate`` и ``contracts.evidence_errors``;
экспорт работает на минимальном примере контракта и на файле contracts/v1.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from p17_fixtures import build_all

from bcc_review import contracts as C
from bcc_review.exports.jira import jira_rows
from bcc_review.exports.markdown import check_markdown, render_markdown

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"


@pytest.mark.parametrize("name", sorted(build_all()))
def test_fixtures_valid_against_contract(name):
    report = build_all()[name]
    C.validate(report)
    assert C.evidence_errors(report) == []


@pytest.mark.parametrize("name", sorted(build_all()))
def test_fixtures_valid_against_schema_file(name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts" / "v1.json").read_text(encoding="utf-8"))
    jsonschema.validate(build_all()[name], schema)


def test_contract_minimal_example_exports():
    report = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    md = render_markdown(report)
    assert check_markdown(md, report) == []
    assert "Сверка `summary`" not in md
    assert "**Исход А по [R-01](#r-r-01)\u00a0(Ф-1):**" in md
    assert "**Первое действие:** Решить вопрос Q-001 и исправить Ф-1 или Ф-2" in md
    rows = jira_rows(report)
    assert len(rows) == 1 and rows[0]["Priority"] == "Highest"


def test_cyrillic_agent_ids_get_unique_working_anchors():
    import re

    text = json.dumps(build_all()["complete-numbered"], ensure_ascii=False)
    text = text.replace('"R-0', '"Т-0').replace('"F-0', '"З-0')
    report = json.loads(text)
    md = render_markdown(report)
    anchors = re.findall(r'<a id="([^"]+)"></a>', md)
    assert len(anchors) == len(set(anchors))
    assert set(re.findall(r"\]\(#([^)]+)\)", md)) <= set(anchors)
    assert check_markdown(md, report) == []
