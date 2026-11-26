"""№13: verify — перепроверка report.json по исходнику без модели."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import verify  # noqa: E402

SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"
SOURCE = ROOT / "release" / "input" / "requirements.md"


@pytest.fixture()
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def run_cli(tmp_path, report, source=SOURCE, capsys=None):
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return verify.main([str(p), str(source)])


def test_sample_ok(tmp_path, sample, capsys):
    assert run_cli(tmp_path, sample) == 0
    out = capsys.readouterr().out
    assert "verify: OK" in out and "67 из 67" in out


def test_wrong_line_is_reported_with_hint(tmp_path, sample, capsys):
    bad = copy.deepcopy(sample)
    bad["findings"][0]["evidence"][0]["line_start"] = bad["findings"][0]["evidence"][0]["line_end"] = 41
    assert run_cli(tmp_path, bad) == 4
    err = capsys.readouterr().err
    assert "D-01 цитата №1" in err and "найдена в строке 39" in err


def test_invented_quote_fails(sample):
    bad = copy.deepcopy(sample)
    bad["findings"][3]["evidence"][0]["quote"] = "Такой фразы в документе нет"
    res = verify.verify_report(bad, SOURCE)
    assert not res["ok"] and res["errors"][0]["code"] == "quote"
    assert "в документе не найдена" in res["errors"][0]["message"]


def test_fuzzy_quote_near_line_passes(sample):
    r = copy.deepcopy(sample)
    ev = r["findings"][0]["evidence"][0]
    ev["quote"] = ev["quote"].replace("приходится", "приходиться")
    ev["verified"] = "fuzzy"
    assert verify.verify_report(r, SOURCE)["ok"]
    ev["verified"] = "exact"
    assert not verify.verify_report(r, SOURCE)["ok"]


def test_other_source_fails_sha(tmp_path, sample):
    other = tmp_path / "requirements.md"
    other.write_text(SOURCE.read_text(encoding="utf-8").replace("Ф-3.", "Ф-3 "), encoding="utf-8")
    res = verify.verify_report(sample, other)
    assert any(e["code"] == "sha256" for e in res["errors"])


def test_counters_must_match(sample):
    bad = copy.deepcopy(sample)
    bad["summary"]["findings"]["critical"] = 4
    res = verify.verify_report(bad, SOURCE)
    assert [e["code"] for e in res["errors"]] == ["summary"]


def test_verdict_must_follow_rule(sample):
    bad = copy.deepcopy(sample)
    bad["verdict"]["development"] = "yes"
    res = verify.verify_report(bad, SOURCE)
    assert any(e["code"] == "verdict" for e in res["errors"])


def test_commit_required(sample):
    bad = copy.deepcopy(sample)
    bad["run"]["commit"] = ""
    res = verify.verify_report(bad, SOURCE)
    assert any(e["code"] == "commit" for e in res["errors"])


def test_dangling_references(sample):
    bad = copy.deepcopy(sample)
    bad["questions"][0]["finding_ids"] = ["D-99"]
    bad["findings"][1]["requirement_ids"].append("R-77")
    codes = [e["code"] for e in verify.verify_report(bad, SOURCE)["errors"]]
    assert codes.count("refs") == 2


def test_unreadable_input_is_exit_4(tmp_path, capsys):
    p = tmp_path / "broken.json"
    p.write_text("{", encoding="utf-8")
    assert verify.main([str(p), str(SOURCE)]) == 4


def test_normalize_matches_contract():
    assert verify.normalize("«Порог» — **5 000** ₸") == verify.normalize('"порог" - 5 000 ₸')
    assert verify.normalize("* пункт списка") == "пункт списка"
