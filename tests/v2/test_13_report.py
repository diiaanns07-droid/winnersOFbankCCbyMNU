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
    "></a>Кратко", "></a>1. Паспорт прогона", "></a>2. Нарезка: как агент нарезал требования", "></a>3. Проверка каждого требования",
    "></a>4. Проверка всего набора требований", "></a>5. Сводка", "></a>6. Итог", "></a>Приложение А. Вопросы владельцу",
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


def test_finalize_enforces_rule_verdict_and_fills_lists():
    r = {"run": {"status": "complete"}, "findings": [], "requirements": [], "verdict": {"development": "no"}}
    jsonout.finalize(r)
    assert r["verdict"]["development"] == "yes" and r["verdict"]["testing"] == "yes"
    assert any("пересчитан по правилу" in w for w in r["run"]["warnings"])
    assert r["questions"] == [] and r["schema"] == "bcc-review/2"


def test_finalize_answers_mode_keeps_references_valid(sample):
    """Конвейер в режиме --answers кладёт в findings только оставшиеся дефекты (№11 findings_after)."""
    r = copy.deepcopy(sample)
    r["findings_before"] = copy.deepcopy(r["findings"])
    r["findings"] = [f for f in r["findings"] if f["severity"] != "critical"]
    r["clarification"] = {"answers": [], "decisions": [], "unanswered": [], "changes": [], "new_findings": [],
                          "before": {"verdict": {"development": "no", "testing": "no"},
                                     "findings": {"critical": 5, "major": 20, "minor": 7}},
                          "after": {"verdict": {"development": "conditional", "testing": "conditional"},
                                    "findings": {"critical": 0, "major": 20, "minor": 7}},
                          "resolved": 5, "changed": 0, "open": 0}
    jsonout.finalize(r)
    assert r["verdict"]["development"] == "conditional"
    assert r["verdict"]["summary"].startswith("После ответов владельца разработка — с условиями")
    assert "D-01" not in r["verdict"]["fix_first"] and r["verdict"]["fix_first"]
    assert sum(1 for f in r["findings"] if f.get("status_after_answers") == "resolved") == 5
    from bcc_review.v2 import verify
    res = verify.verify_report(r, ROOT / "release" / "input" / "requirements.md")
    assert res["ok"], res["errors"][:3]
    md = markdown.render(r)
    assert "[D-01](#d-01)" not in md and "D-01 (снят)" in md


# ------------------------------------------------------------------ Markdown

def test_sections_in_order_and_budget(sample):
    md = markdown.render(sample)
    pos = [md.find(h) for h in REQUIRED_HEADINGS]
    assert all(p >= 0 for p in pos), [h for h, p in zip(REQUIRED_HEADINGS, pos) if p < 0]
    assert pos == sorted(pos)
    assert md.count("\n") <= 900


def test_header_says_generated_and_verified(sample):
    md = markdown.render(sample)
    first = md.split("\n")[2]
    assert "без ручных правок" in first and "все 67 цитат найдены в документе" in first
    assert "коммит" not in first and "verify" not in first  # технические подробности — в паспорте
    passport = md[md.find("></a>1. Паспорт"):md.find("></a>2. Нарезка")]
    assert "коммит `c0b8368`" in passport and "python -m bcc_review verify" in passport


def test_first_screen(sample):
    md = markdown.render(sample)
    brief = md[md.find("></a>Кратко"):md.find("></a>1. Паспорт")]
    assert "⛔ нельзя начинать" in brief
    assert "🔴 **5** критичных" in brief and "**8** вопросов владельцу" in brief
    blockers = re.findall(r"^\d\. 🔴 \[D-\d+\]\(#d-\d+\) \*\*.+\*\* — (.+); блокирует (.+)\.$", brief, re.M)
    assert len(blockers) == 5  # блокер — одна строка: что, где, что блокирует
    assert all("строк" in where for where, _ in blockers) and blockers[0][0] == "Ф-3 (строка 39), Ф-4 (строка 40)"
    assert "**Почему.**" in brief and "**Исправить первым**" in brief
    fix = brief[brief.find("**Исправить первым**"):]
    assert fix.count(" → ") >= 7  # у каждого пункта — что сделать
    assert len(brief.split("\n")) <= 40
    text = re.sub(r"\]\(#[^)]*\)", "]", brief)
    assert not re.search(r"\bR-\d", text) and "коммит" not in text and "кандидат" not in text


def test_every_link_has_anchor(sample):
    md = markdown.render(sample)
    links = set(re.findall(r"\]\(#([\w-]+)(?: \"[^\"]*\")?\)", md))
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
    quotes = re.findall(r"^(?:- |\*\*Где:\*\* )(.+?), (?:с\. \d+, )?строк[аи] [\d–]+: «(.+?)»(?:;|$)", cards, re.M)
    assert len(quotes) >= 25
    assert all(len(q) <= markdown.CARD_QUOTE + 1 for _, q in quotes)
    # место — ID требования в документе («Ф-3»), пункт или раздел, но не внутренний R-…
    assert all(re.match(r"(Ф-\d|Часть|критерий приёмки №|[^,]+, п\. \d)", where) for where, _ in quotes), quotes[:5]
    assert any(where.startswith("Ф-3") for where, _ in quotes)


def test_card_follows_clarity_rubric(sample):
    """Порядок полей карточки: где → проблема → сценарий → последствия → как исправить → справка."""
    md = markdown.render(sample)
    card = md[md.find('<a id="d-01"></a>'):md.find('<a id="d-02"></a>')]
    order = [card.find(x) for x in ("- Ф-3, строка 39: «", "**Проблема.**", "**Сценарий.**", "**Последствия.**",
                                    "**Как исправить.**", "*Критичный, блокирует разработку и тестирование · критерий")]
    assert all(p >= 0 for p in order) and order == sorted(order), order
    assert "**Требования:**" not in card and "R-07 / Ф-3" in card  # требования — в справочной строке


def test_model_text_names_requirements_by_document_ids():
    r = {"requirements": [{"id": "R-06", "source_id": "Ф-2", "kind": "functional"},
                          {"id": "R-14", "source_id": "Критерии приемки, строка 2", "kind": "acceptance"},
                          {"id": "R-21", "source_id": "Логика работы метода, п. 5", "kind": "functional"},
                          {"id": "R-30", "source_id": "Query-параметры: cardId", "kind": "api"}],
         "findings": [{"id": "D-01", "severity": "major", "title": "т",
                       "problem": "R-06 (Ф-2) против R-14 (Критерии приемки, строка 2); Ф-2 (R-06); ожидаемый результат "
                                  "критерия R-14; R-21 и R-30",
                       "evidence": [{"quote": "q", "line_start": 3, "line_end": 3}]}]}
    md = markdown.render(r)
    assert ("[Ф-2](#r-06) против [критерий приёмки №2](#r-14); [Ф-2](#r-06); ожидаемый результат критерия "
            "[№2](#r-14); [Логика работы метода, п. 5](#r-21) и [R-30](#r-30)") in md


def test_ids_of_document_shown_next_to_report_ids(sample):
    md = markdown.render(sample)
    assert "[R-07 / Ф-3](#r-07 " in md and "[R-30](#r-30 " in md  # «Query-параметры: cardId» — не ID


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
    r = minimal(status="failed", stages={"segment": "ok", "lens_qa": "failed"}, provider="gemini",
                models_used=["gemini-x"])
    jsonout.finalize(r)
    md = markdown.render(r)
    assert "вердикт не вынесен" in md and "Проверка не завершена: сбой этапов Тестировщик" in md
    assert "Блокирующих дефектов не найдено" not in md


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
    assert "Снято 1, уточнено 1, осталось открытыми 0" in md
    assert "**Ответ владельца:** B — Нет" in md and "### Что изменили ответы" in md
    assert "D-01 (снят)" in md
    assert '<a id="d-01">' not in md  # снятый дефект не показывается карточкой
    assert "· уточнён после ответов" in md
    assert "**Сняты ответами блокеры (1):**" in md and "D-01 (снят) Ф-3 и Ф-4 — [Q-01](#q-01): лимит действует всегда" in md
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
        assert "></a>Кратко" in md and ("></a>6. Итог" in md or "## 6. Итог" in md), name
        assert "BCC Review" in console.summary(r), name


def test_line_refs_from_model_text_become_russian():
    assert markdown.prose("см. L038 и L39–L40") == "см. строка 38 и строки 39–40"
    assert markdown.prose("по L151 и в L38-L40, из L7–L9; Сервер по L121") == \
        "по строке 151 и в строках 38–40, из строк 7–9; Сервер по строке 121"
    assert markdown.cell("a | L7") == "a \\| строка 7"
    assert markdown.source_name("lens:что-то") == "проверка ролью"
    assert markdown.source_name("rules:units") == "правило «units»"


def test_revise_edits_rendered(sample):
    r = copy.deepcopy(sample)
    r["rewrites"] = [{"finding_id": "D-01", "title": "т", "severity": "critical", "summary": "с",
                      "edits": [{"action": "replace", "line": 39, "old": "максимум один", "new": "не более <уточнить: N>",
                                 "applied": True, "was": "максимум один", "became": "не более <уточнить: N>"},
                                {"action": "insert", "line": 40, "old": "", "new": "Ф-5. Новое правило.",
                                 "applied": True, "was": "", "became": "Ф-5. Новое правило."},
                                {"action": "replace", "line": 41, "old": "x", "new": "y", "applied": False}]}]
    r["revise_stats"] = {"replaced": 1, "inserted": 1, "not_applied": 1, "pending": 1}
    r["revised_file"] = "/tmp/out/report.revised.md"
    md = markdown.render(r)
    card = md[md.find('id="d-01"'):md.find('id="d-02"')]
    assert "**Было → стало.** Строка 39: «максимум один» → «не более <уточнить: N>»" in card
    assert "**Добавить после строки 40.** «Ф-5. Новое правило.»" in card
    app = md[md.find('id="pg"'):md.find('id="pd"')]
    assert "| после 40 | — | Ф-5. Новое правило. |" in app and "не применено 1" in app
    assert "`report.revised.md`" in app and "/tmp/out" not in app


def test_stage_warnings_in_russian():
    assert markdown.warn_text("проверка серьёзности понизила 2 дефект(ов): critical→major 0, major→minor 2") == \
        "проверка серьёзности понизила 2 дефект(ов): критичный→существенный 0, существенный→незначительный 2"
    assert markdown.warn_text("clarify: оставлено 10 вопросов из 11") == "Вопросы: оставлено 10 вопросов из 11"
    assert markdown.prose("push при floor(расходы/100) ≥ порог") == "push при `floor(расходы/100)` ≥ порог"


def test_links_inferred_for_set_checks_and_ids_in_text(sample):
    r = copy.deepcopy(sample)
    for p in r["pair_checks"]:
        p["finding_ids"] = []
    for a in r["acceptance_checks"]:
        a["finding_ids"] = []
    md = markdown.render(r)
    pairs = md[md.find("### 4.2."):md.find("### 4.3.")]
    assert "| ⛔ противоречат | [D-01](#d-01)" in pairs  # Ф-3 ↔ Ф-4 — оба требования в D-01
    acc = md[md.find("### 4.3."):md.find("### 4.4.")]
    assert "| ⛔ противоречит | [D-05](#d-05)" in acc
    tests = md[md.find('id="pb"'):md.find('id="pv"')]
    assert "(D-01)" not in tests and "([D-01](#d-01))" in tests  # упоминание в тексте — ссылка


def test_candidate_count_excludes_non_proposing_stages(sample):
    r = copy.deepcopy(sample)
    r["run"]["stage_stats"]["quotes"]["candidates"] = 45
    md = markdown.render(r)
    assert "Кандидатов в дефекты: 45;" in md and "нашли 45 возможных дефектов" in md
    assert "в таблице этапов" not in md


def test_identifiers_in_model_text_become_code():
    assert markdown.prose("Клиент читает response.result и поле monthSpent") == \
        "Клиент читает `response.result` и поле `monthSpent`"
    assert markdown.prose("Добавить GET /alerts/limit?cardId=... с ответом") == \
        "Добавить GET `/alerts/limit?cardId=...` с ответом"
    assert markdown.prose("поле limit_kzt и `уже код` и 1.5 и т.е.") == "поле `limit_kzt` и `уже код` и 1.5 и т.е."
    assert markdown.prose("путь /alerts/saveLimit. Дальше") == "путь `/alerts/saveLimit`. Дальше"
    assert markdown.prose("сумма 50 000 ₸, Ф-2, push, API") == "сумма 50 000 ₸, Ф-2, push, API"


def test_stage_failure_warnings_readable():
    assert markdown.warn_text("Этап lens_architect не выполнен: исчерпан бюджет вызовов модели (16)") == \
        "Этап «Архитектор» не выполнен: исчерпан бюджет вызовов модели (16)"
    assert markdown.warn_text("судья недоступен (BudgetExceeded: judge: budget: исчерпан бюджет вызовов модели (16)); "
                              "реестр собран кодом") == \
        "судья недоступен (исчерпан бюджет вызовов модели (16)); реестр собран кодом"


def test_sixty_plus_findings_fit_budget(sample):
    r = copy.deepcopy(sample)
    base = list(r["findings"])
    while len(r["findings"]) < 66:
        f = copy.deepcopy(base[len(r["findings"]) % len(base)])
        f["id"] = f"D-{len(r['findings']) + 1:02d}"
        f["severity"] = "major" if f["severity"] == "critical" else f["severity"]
        r["findings"].append(f)
    del r["summary"]
    jsonout.finalize(r)
    md = markdown.render(r)
    assert md.count("\n") <= 900
    for h in REQUIRED_HEADINGS:
        assert h in md, h
    assert md.count('<a id="d-') == 66  # у каждого дефекта есть якорь, даже в сжатом виде


def test_export_text_for_word(sample, tmp_path):
    md = markdown.render(sample)
    ex = markdown.export_text(md)
    assert "<a id=" not in ex and "\\|" not in ex and "\\*" not in ex
    assert "## 1. Паспорт прогона" in ex and "| R-07 / Ф-3 |" not in ex  # ссылки остаются ссылками
    assert ex.count("\n") == md.count("\n")
    exports = pytest.importorskip("bcc_review.v2.render.exports")
    pytest.importorskip("docx")
    import docx
    res = exports.report_docx(sample, tmp_path / "r.docx", markdown=ex)
    assert res["status"] == "written"
    d = docx.Document(str(tmp_path / "r.docx"))
    texts = [p.text for p in d.paragraphs] + [c.text for t in d.tables for row in t.rows for c in row.cells]
    assert not [t for t in texts if "<a id" in t or "\\|" in t]
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    assert "1. Паспорт прогона" in heads and "Кратко" in heads


@pytest.mark.parametrize("n_findings,n_reqs", [(50, 48), (70, 100), (100, 150), (60, 300)])
def test_long_reports_fit_900_lines(sample, n_findings, n_reqs):
    """Любой документ — не длиннее 900 строк: при 70+ дефектах существенные идут строками таблицы,
    критичные остаются полными карточками."""
    r = copy.deepcopy(sample)
    fs, rq = r["findings"], r["requirements"]
    while len(fs) < n_findings:
        f = copy.deepcopy(fs[len(fs) % 32])
        f["id"] = f"D-{len(fs) + 1:02d}"
        if f["severity"] == "critical":
            f["severity"], f["blocks"] = "major", "development"
        fs.append(f)
    while len(rq) < n_reqs:
        q = copy.deepcopy(rq[len(rq) % 48])
        q["id"] = f"R-{len(rq) + 1:02d}"
        rq.append(q)
    jsonout.finalize(r)
    md = markdown.render(r)
    assert md.count("\n") <= 900
    assert md.count('<a id="d-') == n_findings  # у каждого дефекта есть якорь — ссылки не ломаются
    assert md.count("**Проблема.**") >= 5  # критичные — полными карточками


def test_why_names_kind_of_blockers_and_keeps_priority_sentence(sample):
    md = markdown.render(sample)
    why = next(ln for ln in md.split("\n") if ln.startswith("**Почему.**"))
    assert "5 критичных дефектов блокируют разработку и тестирование: " in why and "противореч" in why
    r = copy.deepcopy(sample)
    r["verdict"]["summary"] = ("Нельзя: D-01, D-02, D-03 и D-04 блокируют работу. Первым исправить D-01 и D-02. "
                               "Потом всё остальное.")
    why = next(ln for ln in markdown.render(r).split("\n") if ln.startswith("**Почему.**"))
    assert "Первым исправить [D-01](#d-01) и [D-02](#d-02)." in why and "Потом" not in why and "D-03" not in why


def test_offline_does_not_claim_unchecked_criteria_are_fine():
    r = {"run": {"provider": "offline", "status": "complete", "stages": {"rules": "ok"}},
         "document": {"title": "т", "file": "t.md"}, "requirements": [], "findings": []}
    md = markdown.render(r)
    assert "✅ нарушений не найдено" not in md and "❔ без модели не проверялся" in md
    assert "4.2–4.5." in md and "### 4.3." not in md
