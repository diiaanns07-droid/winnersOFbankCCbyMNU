"""№13: report.json (схема, сводка, вердикт) и Markdown-отчёт."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.render import console, jsonout, markdown  # noqa: E402

SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"

REQUIRED_HEADINGS = [
    "## Кратко", "></a>1. Паспорт прогона", "></a>2. Нарезка требований", "></a>3. Проверка каждого требования",
    "></a>4. Проверка набора требований", "></a>5. Сводка", "></a>6. Итог", "></a>Приложение А. Вопросы владельцу",
    "></a>Приложение Б. Черновик тест-кейсов", "></a>Приложение В. Чек-лист", "></a>Приложение Г. Было → стало",
    "></a>Приложение Д. Как работал агент", "></a>Приложение Е. Методика",
]
# латиница, допустимая в тексте отчёта вне `кода` и «кавычек» (так же считает счётчик №15)
LATIN_OK = {"ISO", "IEC", "IEEE", "UTC", "API", "JSON", "PDF", "DOCX", "HTML"}
_LATIN = re.compile(r"(?<![A-Za-z0-9_$./-])[A-Za-z][A-Za-z]{2,}(?![A-Za-z0-9_])")


def latin_in_prose(md: str) -> set[str]:
    prose = re.sub(r"`[^`]*`|«[^»]*»", "", md)
    prose = re.sub(r'<a id="[\w-]+"></a>|\(#[\w-]+\)', "", prose)
    return set(_LATIN.findall(prose))


@pytest.fixture()
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def minimal(**run) -> dict:
    report = {
        "schema": "bcc-review/2",
        "run": {"agent": "BCC Review", "version": "2.0.0", "commit": "abcdef1", "started_at": "2026-11-27T01:00:00Z",
                "provider": "offline", "status": "complete", "stages": {"docview": "ok", "rules": "ok"},
                "models_used": [], **run},
        "document": {"title": "Пустое ТЗ", "file": "x.md", "format": "md", "sha256": "0" * 64, "lines": 3},
        "requirements": [], "findings": [], "verdict": {},
    }
    return jsonout.finalize(report)


# ------------------------------------------------------------------ схема и сводка

def test_sample_matches_schema(sample):
    assert jsonout.validate(sample) == []


def test_schema_rejects_bad_severity(sample):
    bad = copy.deepcopy(sample)
    bad["findings"][0]["severity"] = "high"
    errors = jsonout.validate(bad)
    assert errors and "findings/0/severity" in errors[0]
    with pytest.raises(jsonout.SchemaError):
        jsonout.write(bad, Path("/nonexistent/never.json"), strict=True)


def test_schema_critical_needs_blocks(sample):
    bad = copy.deepcopy(sample)
    bad["findings"][0]["blocks"] = "none"
    assert any("findings/0" in e for e in jsonout.validate(bad))


def test_write_records_schema_errors_as_warning(tmp_path, sample):
    bad = copy.deepcopy(sample)
    bad["document"]["sha256"] = "нет"
    errors = jsonout.write(bad, tmp_path / "r.json")
    assert errors and (tmp_path / "r.json").is_file()
    assert any("contracts/v2.json" in w for w in bad["run"]["warnings"])


def test_summary_counts(sample):
    s = jsonout.compute_summary(sample)
    assert s["findings"] == {"critical": 5, "major": 20, "minor": 7}
    assert s["requirements"] == 48
    assert s["quotes_verified"] == s["quotes_total"] == 67
    assert sample["summary"]["requirements_without_findings"] == s["requirements_without_findings"]


def test_resolved_findings_do_not_count(sample):
    r = copy.deepcopy(sample)
    for f in r["findings"]:
        if f["severity"] == "critical":
            f["status"] = "resolved"
    assert jsonout.compute_summary(r)["findings"]["critical"] == 0
    assert jsonout.rule_verdict(r) == {"development": "conditional", "testing": "conditional"}


@pytest.mark.parametrize("findings,status,expected", [
    ([{"severity": "critical", "blocks": "both"}], "complete", ("no", "no")),
    ([{"severity": "critical", "blocks": "testing"}], "complete", ("yes", "no")),
    ([{"severity": "major", "blocks": "development"}] * 3, "complete", ("conditional", "yes")),
    ([{"severity": "major", "blocks": "both"}] * 2, "complete", ("yes", "yes")),
    ([], "partial", ("conditional", "conditional")),
    ([{"severity": "critical", "blocks": "both"}], "failed", ("none", "none")),
])
def test_rule_verdict(findings, status, expected):
    r = {"run": {"status": status}, "findings": findings}
    v = jsonout.rule_verdict(r)
    assert (v["development"], v["testing"]) == expected


def test_finalize_keeps_existing_verdict_and_fills_lists():
    r = {"run": {"status": "complete"}, "findings": [], "requirements": [], "verdict": {"development": "no"}}
    jsonout.finalize(r)
    assert r["verdict"]["development"] == "no" and r["verdict"]["testing"] == "yes"
    assert r["questions"] == [] and r["schema"] == "bcc-review/2"


# ------------------------------------------------------------------ Markdown

def test_sections_in_order_and_budget(sample):
    md = markdown.render(sample)
    pos = [md.find(h) for h in REQUIRED_HEADINGS]
    assert all(p >= 0 for p in pos), [h for h, p in zip(REQUIRED_HEADINGS, pos) if p < 0]
    assert pos == sorted(pos)
    assert md.count("\n") <= 900


def test_header_says_generated_and_verified(sample):
    first = markdown.render(sample).split("\n")[2]
    assert "без ручных правок" in first and "коммит `c0b8368`" in first and "все 67 цитат сверены" in first


def test_first_screen(sample):
    md = markdown.render(sample)
    brief = md[md.find("## Кратко"):md.find("></a>1. Паспорт")]
    assert "⛔ нельзя начинать" in brief
    assert "🔴 **5** критичных" in brief and "**8** вопросов владельцу" in brief
    assert brief.count("| 🔴 [D-") == 5  # таблица блокеров
    assert "**Исправить первым**" in brief
    assert len(brief.split("\n")) <= 40


def test_every_link_has_anchor(sample):
    md = markdown.render(sample)
    links = set(re.findall(r"\]\(#([\w-]+)\)", md))
    anchors = set(re.findall(r'<a id="([\w-]+)"></a>', md))
    assert links and links <= anchors, links - anchors


def test_tables_have_consistent_columns(sample):
    md = markdown.render(sample)
    for block in re.split(r"\n\s*\n", md):
        rows = [ln for ln in block.split("\n") if ln.startswith("|")]
        if len(rows) < 2:
            continue
        widths = {len(re.findall(r"(?<!\\)\|", ln)) for ln in rows}
        assert len(widths) == 1, rows[:3]


def test_card_quotes_are_short_and_located(sample):
    md = markdown.render(sample)
    cards = md[md.find("### 3.2."):md.find("### 3.3.")]
    quotes = re.findall(r"^- (.+?), строк[аи] [\d–]+: «(.+)»$", cards, re.M)
    assert len(quotes) >= 40
    assert all(len(q) <= 161 for _, q in quotes)
    assert all("Часть" in where for where, _ in quotes)


def test_ids_of_document_shown_next_to_report_ids(sample):
    md = markdown.render(sample)
    assert "[R-07 / Ф-3](#r-07)" in md and "[R-30](#r-30)" in md  # «Query-параметры: cardId» — не ID


def test_no_internal_jargon(sample):
    md = markdown.render(sample)
    for bad in ("lens:", "rules:", "None", "null", "{{", "rules_only", "team:", "candidate_ids", "requirement_ids"):
        assert bad not in md, bad


def test_templates_are_russian(sample):
    for r in (minimal(), minimal(provider="claude_cli", models_used=["claude-opus-5-5"], model_requested="opus",
                                 status="partial", stages={"judge": "failed"})):
        assert latin_in_prose(markdown.render(r)) <= LATIN_OK
    doc_words = {w.lower() for w in re.findall(r"[A-Za-z]+", (ROOT / "release" / "input" / "requirements.md")
                                                .read_text(encoding="utf-8"))}
    extra = {w for w in latin_in_prose(markdown.render(sample)) if w.lower() not in doc_words}
    assert extra <= LATIN_OK | {"RFC", "PUT", "POST", "HTTP"}, extra


def test_minimal_offline_report_has_all_sections():
    md = markdown.render(minimal())
    for h in REQUIRED_HEADINGS:
        assert h in md, h
    assert "Режим без модели" in md and "Дефектов не найдено" in md
    assert "❔ не определено" in md and "✅ можно начинать" not in md


def test_partial_and_failed_status_banners():
    md = markdown.render(minimal(status="partial", stages={"segment": "ok", "judge": "failed"}, provider="gemini",
                                 models_used=["gemini-x"]))
    assert "Прогон завершён частично" in md and "Судья" in md
    r = minimal(status="failed")
    jsonout.finalize(r)
    assert "вердикт не вынесен" in markdown.render(r)


def test_before_after_block(sample):
    r = copy.deepcopy(sample)
    r["findings"][0]["status_after_answers"] = "resolved"
    r["findings"][1]["status_after_answers"] = "changed"
    r["clarification"] = {
        "answers": [{"question_id": "Q-01", "topic": "лимит", "question": "?", "choice": "B", "answer": "Нет",
                     "finding_ids": ["D-01"]}],
        "decisions": ["Событие — авторизация"], "unanswered": ["Q-02"],
        "changes": [{"finding_id": "D-01", "title": "Ф-3 и Ф-4", "severity_before": "critical", "status": "resolved",
                     "severity_after": None, "reason": "лимит действует всегда", "question_ids": ["Q-01"]},
                    {"finding_id": "D-02", "title": "Событие", "severity_before": "critical", "status": "changed",
                     "severity_after": "major", "reason": "уточнено", "question_ids": []}],
        "new_findings": [], "before": {"verdict": {"development": "no", "testing": "no"},
                                       "findings": {"critical": 5, "major": 20, "minor": 7}},
        "after": {"verdict": {"development": "no", "testing": "no"}, "findings": {"critical": 4, "major": 20, "minor": 7}},
        "resolved": 1, "changed": 1, "open": 0}
    del r["summary"]
    jsonout.finalize(r)
    assert jsonout.validate(r) == []
    md = markdown.render(r)
    assert "**До и после ответов владельца** — ответов 1, общих решений 1, без ответа 1" in md
    assert "**Ответ владельца:** B — Нет" in md and "### Что изменили ответы" in md
    assert "D-01 (снят)" in md
    assert '<a id="d-01">' not in md  # снятый дефект не показывается карточкой
    assert "· уточнён после ответов" in md
    assert r["summary"]["findings"]["critical"] == 4


def test_offline_report_of_rules():
    r = minimal()
    r["title"] = "Предварительная проверка без модели"
    r["signals"] = [{"kind": "vague", "line": 2, "quote": "быстро", "message": "размытое слово"},
                    {"kind": "inventory", "line": 1, "quote": "x", "message": "служебное"}]
    r["not_checked"] = ["противоречия по смыслу"]
    r["verdict"] = {"development": "undetermined", "testing": "undetermined", "summary": "Смысл не проверялся."}
    assert jsonout.validate(r) == []
    md = markdown.render(r)
    assert md.startswith("# Предварительная проверка без модели: «Пустое ТЗ»")
    assert "3.4. Подсказки для ручной проверки" in md and "«быстро» — размытое слово" in md and "служебное" not in md
    assert "**Что не проверялось в этом прогоне**" in md and "❔ не определено" in md
    assert jsonout.rule_verdict(r) == {"development": "undetermined", "testing": "undetermined"}
    r["findings"] = [{"id": "D-01", "severity": "major", "rule_conflict": True, "blocks": "testing",
                      "evidence": [{"quote": "a"}, {"quote": "b"}]}]
    assert jsonout.rule_verdict(r) == {"development": "undetermined", "testing": "no"}


def test_markdown_escapes_document_markup():
    r = minimal()
    r["requirements"] = [{"id": "R-01", "kind": "functional", "summary": "a | b <script>", "line_start": 1,
                          "line_end": 1, "section": "Раздел"}]
    r["findings"] = [{"id": "D-01", "title": "Заголовок <b>", "kind": "ambiguity", "criterion": "unambiguous",
                      "severity": "major", "requirement_ids": ["R-01"], "blocks": "development",
                      "evidence": [{"quote": "**жирный** `код` | ячейка", "line_start": 1, "verified": "exact"}],
                      "problem": "п", "recommendation": "р", "rewrite": "<уточнить: срок>"}]
    jsonout.finalize(r)
    md = markdown.render(r)
    assert not re.search(r"(?<!\\)<(script|b)>", md)
    assert "<уточнить: срок>" in md  # кириллический «тег» GitHub показывает как текст


def test_compaction_reduces_length(sample):
    big = copy.deepcopy(sample)
    big["rejected"] = big["rejected"] * 10
    full = markdown.render(big, max_lines=None)
    short = markdown.render(big, max_lines=700)
    assert short.count("\n") < full.count("\n")
    for h in REQUIRED_HEADINGS:
        assert h in short


def test_console_summary(sample):
    text = console.summary(sample, md_path="reports/x.md", json_path="reports/x.json")
    assert "Разработка: нельзя" in text and "D-01" in text and "reports/x.md" in text
    assert len(text.split("\n")) <= 8


def _mutations(report: dict):
    for key in list(report):
        for bad in (None, [], {}, "строка", 7):
            r = copy.deepcopy(report)
            r[key] = bad
            yield f"{key}={bad!r}", r
    for field in ("evidence", "requirement_ids", "severity", "title", "blocks", "id", "criterion", "kind"):
        for bad in (None, "x", [None, 3], {}):
            r = copy.deepcopy(report)
            for f in r["findings"]:
                f[field] = bad
            yield f"findings.{field}={bad!r}", r
    r = copy.deepcopy(report)
    for f in r["findings"]:
        for ev in f["evidence"]:
            ev.pop("line_start")
            ev["section"] = None
    yield "evidence без строк", r


def test_render_never_crashes_on_broken_data(sample):
    for name, r in _mutations(sample):
        md = markdown.render(r)
        assert "## Кратко" in md and ("></a>6. Итог" in md or "## 6. Итог" in md), name
        assert "BCC Review" in console.summary(r), name
