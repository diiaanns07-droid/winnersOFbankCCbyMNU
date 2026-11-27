"""№31: адаптеры новых соперников в «Мы и конкуренты» — схема каждого отчёта → отчёт нашего счётчика."""
from evaluation.v2 import competitors as c


def test_reqaudit_skips_dropped_and_keeps_both_sides():
    data = {"readiness": "not_ready", "findings": [
        {"criterion": "set_consistent", "severity": "critical", "quote": "А", "explanation": "Противоречие. Детали",
         "location": {"line_start": 3}, "related_quote": "Б", "related_location": {"line_start": 9},
         "suggestion": "исправить", "dropped_reason": None},
        {"criterion": "x", "severity": "minor", "quote": "В", "explanation": "", "dropped_reason": "duplicate"}]}
    rep = c.adapt("ReqAudit", data, {"sha256": "s"})
    assert len(rep["findings"]) == 1
    f = rep["findings"][0]
    assert f["severity"] == "critical" and f["kind"] == "contradiction"
    assert [e["line_start"] for e in f["evidence"]] == [3, 9]
    assert rep["verdict"]["development"] == "no"


def test_reqcheck_russian_severity_and_unaligned_lines():
    data = {"verdict": {"level": "no"}, "findings": [
        {"title": "Т", "severity": "высокая", "criterion": "неоднозначность", "quotes": ["а", "б"], "lines": [5],
         "problem": "п", "fix": "ф"}]}
    f = c.adapt("reqcheck-agent", data, {})["findings"][0]
    assert f["severity"] == "major" and f["kind"] == "ambiguity"
    assert [e["line_start"] for e in f["evidence"]] == [None, None]


def test_goodgame_takes_requirement_and_set_findings():
    data = {"verdict": {"ready": False},
            "requirement_checks": [{"findings": [{"severity": "major", "criterion": "complete", "quote": "к",
                                                  "related_quotes": ["л"], "explanation": "Нет данных. Ещё"}]}],
            "set_check": {"findings": [{"severity": "critical", "criterion": "consistent", "quote": "м"}]}}
    fs = c.adapt("goodgame", data, {})["findings"]
    assert [f["severity"] for f in fs] == ["major", "critical"]
    assert fs[0]["title"] == "Нет данных" and len(fs[0]["evidence"]) == 2


def test_sources_pinned_to_full_commits():
    import re
    for name, s in c.SOURCES.items():
        assert re.search(r"/[0-9a-f]{40}/", s["path"]), name
