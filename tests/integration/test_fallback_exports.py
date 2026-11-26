"""Резервные экспорты отчёта: Markdown, HTML, Jira CSV (src/bcc_review/runtime/fallback)."""

from __future__ import annotations

import copy
import csv
import html as html_lib
import json
import re
from pathlib import Path

import pytest

from bcc_review import contracts as C
from bcc_review.runtime.fallback import report_common as rc
from bcc_review.runtime.fallback.html import render_html, write_html
from bcc_review.runtime.fallback.jira import write_jira_csv
from bcc_review.runtime.fallback.markdown import write_markdown

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"

LINE7 = "Уведомление о расходах отправляется быстро."
LINE8 = "Формат суммы в уведомлении определяется позже."
TEXT5 = LINE7 + "\n" + LINE8
SECTION = ["Пример: два связанных требования", "Функциональные требования"]


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def ev(rep: dict, block_id: str, quote: str) -> dict:
    text = next(b["text"] for b in rep["document"]["blocks"] if b["id"] == block_id)
    start = text.index(quote)
    return {"block_id": block_id, "start": start, "end": start + len(quote), "quote": quote}


def finding(**kw) -> dict:
    base = {"scope": "requirement", "hints": [], "evidence": [], "status": "confirmed", "anchor_status": "supported",
            "meaning_status": "confirmed", "blocks": [], "witness": None, "inspected_block_ids": [],
            "merged_from": [], "cause": None, "source": "llm", "stage": "individual", "notes": []}
    base.update(kw)
    return base


def rich_report() -> dict:
    """Частичный прогон: 4 замечания (одно требует проверки), чек-лист, тест-кейсы, вопросы, сравнение."""
    rep = load_example()
    rep["run"].update({
        "run_id": "rich-0002", "parent_run_id": "example-0001", "agent_commit": "3e6b569",
        "provider": "gemini", "model": "gemini-2.5-flash", "requested_model": "gemini-2.5-flash",
        "models_seen": ["gemini-2.5-flash"], "mode": "rules_plus_llm", "status": "partial",
        "status_reasons": ["этап individual прерван: исчерпан бюджет вызовов"],
        "calls": {"physical": 7, "cache_hits": 2, "failed": 1, "retries": 2},
        "tokens": {"input": 12345, "output": 2345, "cache_read": 0},
        "budget": {"max_calls": 7, "max_seconds": 1500.0, "max_tokens": None, "exhausted": True,
                   "reason": "max_calls"},
        "incomplete_stages": ["individual"],
        "modules": {"inventory": "fallback", "markdown": "fallback"},
    })
    rep["run"]["stages"].insert(1, {"name": "individual", "status": "failed", "calls": 3, "cache_hits": 0,
                                    "retries": 2, "model": "gemini-2.5-flash", "reason": "budget_exhausted"})
    rep["document"]["blocks"].append({
        "id": "b0005", "kind": "paragraph", "section": SECTION, "text": TEXT5,
        "loc": {"line_start": 7, "line_end": 8, "map": [[0, 7, 0], [len(LINE7) + 1, 8, 0]]},
    })
    rep["document"]["warnings"] = ["Таблица в конце документа прочитана без объединённых ячеек"]
    rep["requirements"].append({
        "id": "R-03", "source_id": None, "text": TEXT5, "block_ids": ["b0005"],
        "evidence": [ev(rep, "b0005", TEXT5)], "kind": "functional", "review_status": "partial",
        "review_reason": "этап individual прерван до проверки по всем критериям",
    })
    rep["findings"] += [
        finding(id="F-002", kind="ambiguity", criterion="unambiguous", severity="major",
                title="Не задано, что значит «быстро» для отправки уведомления",
                impact="Тестировщик не может выбрать порог времени доставки push.",
                req_ids=["R-03"], hints=[{"block_id": "b0005", "quote": "быстро"}],
                status="needs_review", anchor_status="incomplete", meaning_status="unchecked",
                recommendation="Указать максимальное время доставки push в секундах от авторизации операции."),
        finding(id="F-003", kind="placeholder", criterion="complete", severity="critical",
                title="Формат суммы в уведомлении отложен",
                impact="Разработчик не знает, как округлять и форматировать сумму в тексте push.",
                blocked_decision="Шаблон текста push и правила округления суммы",
                req_ids=["R-03"], evidence=[ev(rep, "b0005", "определяется позже")],
                blocks=["development", "testing"],
                recommendation="Задать формат суммы: валюта ₸, разделитель тысяч, два знака после запятой."),
        finding(id="F-004", kind="format", criterion="conforming", severity="minor",
                title="Номер «Ф-2.» оформлен не как <ID> из шаблона & реестра",
                impact="Ссылки на требование в Jira будут неоднородными.",
                req_ids=["R-02"], evidence=[ev(rep, "b0004", "Ф-2.")], meaning_status="deterministic",
                source="rules", recommendation="Оформить ID по шаблону банка: FR-002."),
    ]
    rep["checks"] += [
        {"req_id": "R-01", "criterion": "unambiguous", "status": "pass", "reason": "Лимит задан числом.",
         "finding_ids": [], "source": "llm"},
        {"req_id": "R-02", "criterion": "conforming", "status": "issue", "reason": "ID не по шаблону.",
         "finding_ids": ["F-004"], "source": "rules"},
        {"req_id": "R-03", "criterion": "verifiable", "status": "unknown", "reason": "Этап прерван.",
         "finding_ids": [], "source": "engine"},
        {"req_id": "R-03", "criterion": "complete", "status": "issue", "reason": "Формат суммы отложен.",
         "finding_ids": ["F-003"], "source": "llm"},
    ]
    rep["coverage"] = [{"req_id": "R-01", "obligation": "не более одного push в месяц", "acceptance_ids": [],
                        "status": "uncovered", "explanation": "Нет критерия приёмки для повторного push",
                        "evidence": [ev(rep, "b0003", "максимум один push")]}]
    rep["facts"] = [{"id": "FX-01", "subject": "push", "field": "лимит в месяц", "value": 1, "unit": "шт.",
                     "req_ids": ["R-01"], "evidence": [ev(rep, "b0003", "максимум один push")]}]
    rep["questions"].append({"id": "Q-002", "finding_ids": ["F-003"], "prompt": "Какой формат суммы в push?",
                             "options": ["12 345 ₸", "12 345,00 ₸"], "affected_req_ids": ["R-03"]})
    rep["checklist"] = [
        {"id": "CL-01", "text": "Указан канал уведомления", "available": "yes", "checked": "yes",
         "note": "push", "finding_ids": [], "evidence": [ev(rep, "b0003", "push")]},
        {"text": "Определён формат суммы", "available": "no", "checked": "no", "note": "формат отложен",
         "finding_ids": ["F-003"], "evidence": []},
    ]
    rep["test_cases"] = [
        {"id": "TC-01", "precondition": "Push в этом месяце уже отправлен",
         "action": "Снизить порог и совершить покупку сверх порога",
         "expected": "Зависит от ответа на Q-001", "req_ids": ["R-01", "R-02"], "open_question_id": "Q-001"},
        {"id": "TC-02", "precondition": "Push в этом месяце не отправлялся",
         "action": "Совершить покупку сверх порога", "expected": "Push отправлен один раз",
         "req_ids": ["R-01"], "open_question_id": None},
    ]
    rep["diff"] = {
        "previous": {"source_sha256": "0" * 64, "run_id": "example-0000"},
        "current": {"source_sha256": rep["run"]["source_sha256"], "run_id": "rich-0002"},
        "resolved": [{"old_ids": ["F-009"], "new_ids": [], "reason": "Часовой пояс указан", "evidence": []}],
        "persisting": [{"old_ids": ["F-001"], "new_ids": ["F-001"], "reason": "Ф-1 и Ф-2 не изменились",
                        "evidence": [ev(rep, "b0003", "максимум один push")]}],
        "introduced": [{"old_ids": [], "new_ids": ["F-003"], "reason": "Добавлен абзац с отложенным форматом",
                        "evidence": [ev(rep, "b0005", "определяется позже")]}],
        "unassessed": [], "impacted_req_ids": ["R-03"], "warnings": [],
    }
    rep["warnings"] = [{"code": "budget_exhausted", "message": "Исчерпан бюджет вызовов модели",
                        "stage": "individual", "block_ids": ["b0005"]}]
    rep["rejected"] = [{"candidate": {"scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous",
                                      "severity": "minor", "title": "Слово «календарный» неоднозначно",
                                      "impact": "нет", "req_ids": ["R-01"],
                                      "hints": [{"block_id": "b0003", "quote": "календарный"}]},
                        "reason": "критик: термин общепринят", "stage": "critic"}]
    rep["verdict"] = {
        "development": {"status": "not_ready", "reasons": ["Критичные F-001 и F-003"],
                        "finding_ids": ["F-001", "F-003"]},
        "testing": {"status": "unknown", "reasons": ["Проверка R-03 по критериям не завершена"], "finding_ids": []},
        "first_actions": [
            {"order": 1, "action": "Решить вопрос Q-001 и исправить Ф-1 или Ф-2", "finding_ids": ["F-001"]},
            {"order": 2, "action": "Задать формат суммы в push", "finding_ids": ["F-003"]},
        ],
        "basis": "Критичные замечания блокируют разработку; прогон неполный.",
    }
    rep["summary"] = {
        "requirements": 3, "reviewed_requirements": 2, "findings": 4,
        "by_severity": {"critical": 2, "major": 1, "minor": 1},
        "by_status": {"confirmed": 3, "needs_review": 1},
        "critical_ids": ["F-001", "F-003"],
        "checks": {"pass": 3, "issue": 4, "unknown": 1, "na": 0},
    }
    return rep


def without_findings(rep: dict, status: str) -> dict:
    rep = copy.deepcopy(rep)
    rep["run"]["status"] = status
    if status == "complete":
        rep["run"]["status_reasons"], rep["run"]["incomplete_stages"] = [], []
    rep["findings"], rep["questions"], rep["test_cases"], rep["checklist"], rep["diff"] = [], [], [], [], None
    for check in rep["checks"]:
        check["finding_ids"] = []
    for key in ("development", "testing"):
        rep["verdict"][key]["finding_ids"] = []
    rep["verdict"]["first_actions"] = []
    rep["summary"].update(findings=0, critical_ids=[], by_severity={"critical": 0, "major": 0, "minor": 0},
                          by_status={"confirmed": 0, "needs_review": 0})
    return rep


@pytest.fixture(params=["example", "rich"])
def report(request) -> dict:
    return load_example() if request.param == "example" else rich_report()


def md_section(md: str, heading: str) -> str:
    start = md.index(heading)
    nxt = md.find("\n## ", start + len(heading))
    return md[start: nxt if nxt != -1 else len(md)]


# --------------------------------------------------------------------------- данные тестов
@pytest.mark.parametrize("rep", [rich_report(), without_findings(rich_report(), "partial"),
                                 without_findings(load_example(), "complete")])
def test_fixtures_follow_contract(rep):
    C.validate(rep)
    assert C.evidence_errors(rep) == []


# --------------------------------------------------------------------------- общие помощники
def test_criteria_cover_contract():
    assert set(rc.CRITERIA) == set(C.INDIVIDUAL_CRITERIA) | set(C.SET_CRITERIA)
    assert rc.criterion_label("unambiguous") == "Однозначность (ISO/IEC/IEEE 29148 5.2.5; IEEE 830 4.3.2)"
    assert rc.criterion_label("set_consistent") == "Согласованность набора (ISO/IEC/IEEE 29148 5.2.6; IEEE 830 4.3.4)"
    assert rc.severity_label("critical") == "критичное"
    assert rc.label(rc.READINESS_LABELS, "not_ready") == "нельзя начинать"


def test_describe_location_formats():
    rep = rich_report()
    assert rc.describe_location(rep, rep["findings"][0]["evidence"][0]) == "строка 4"
    assert rc.describe_location(rep, "b0005") == "строки 7–8"
    assert rc.describe_location(rep, ev(rep, "b0005", "определяется позже")) == "строка 8"
    assert rc.describe_location(rep, ev(rep, "b0005", "быстро.\nФормат")) == "строки 7–8"
    assert rc.describe_location(rep, "b9999") == "блок b9999 (нет в документе)"

    pdf = copy.deepcopy(rep)
    pdf["document"]["format"] = "pdf"
    pdf["document"]["blocks"][2]["loc"] = {"page": 2, "fragments": []}
    assert rc.describe_location(pdf, "b0003") == "с. 2"
    docx = copy.deepcopy(rep)
    docx["document"]["format"] = "docx"
    docx["document"]["blocks"][2]["loc"] = {"part": "word/document.xml", "path": "body/tbl[1]/tr[3]/tc[2]"}
    assert rc.describe_location(docx, "b0003") == "body/tbl[1]/tr[3]/tc[2]"


def test_md_cell_escapes_pipes_and_newlines():
    assert rc.md_cell("a | b\nc\r\nd") == "a \\| b<br>c<br>d"
    # похожее на HTML-тег не должно пропасть при просмотре; сравнения и кириллица — как есть
    assert rc.md_inline("<amount> <= 100, <ФИО>") == "&lt;amount> <= 100, <ФИО>"


# --------------------------------------------------------------------------- Markdown
def test_markdown_written_with_sections_in_order(report, tmp_path):
    path = write_markdown(report, tmp_path / "out" / "report.md")
    assert path == tmp_path / "out" / "report.md" and path.exists()
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    md = raw.decode("utf-8")
    order = ["## 1. Итог", "## 2. Паспорт прогона", "## 3. Методика и критерии", "## 4. Нарезка требований",
             "## 5. Проверка каждого требования", "## 6. Проверка набора", "## 7. Замечания", "## 8. Сводка"]
    positions = [md.index(h) for h in order]
    assert positions == sorted(positions)
    assert "Приложение А. Вопросы аналитику" in md


def test_markdown_finding_anchors_and_quotes(report, tmp_path):
    md = write_markdown(report, tmp_path / "r.md").read_text(encoding="utf-8")
    for f in report["findings"]:
        assert f'<a id="finding-{f["id"]}"></a>' in md
        assert f"[{f['id']}](#finding-{f['id']})" in md
        for e in f["evidence"]:
            assert f"«{e['quote']}»" in md
        assert f["impact"] in md and f["recommendation"] in md
    for r in report["requirements"]:
        assert f"| {r['id']} |" in md


def test_markdown_example_details(tmp_path):
    rep = load_example()
    md = write_markdown(rep, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "строка 4" in md and "строка 5" in md
    assert "**нельзя начинать**" in md
    assert "1. Решить вопрос Q-001 и исправить Ф-1 или Ф-2 — [F-001](#finding-F-001)" in md
    assert "Согласованность набора (ISO/IEC/IEEE 29148 5.2.6; IEEE 830 4.3.4)" in md
    assert rep["run"]["source_sha256"] in md and "mock-1" in md
    witness = rep["findings"][0]["witness"]
    sets = md_section(md, "## 6. Проверка набора")
    assert witness["input"] in sets and witness["outcome_a"] in sets and witness["outcome_b"] in sets
    assert "Замечаний нет" not in md
    assert "Заголовки, не требования" in md


def test_markdown_summary_numbers_equal_report_summary(report, tmp_path):
    md = write_markdown(report, tmp_path / "r.md").read_text(encoding="utf-8")
    section = md_section(md, "## 8. Сводка")
    s = report["summary"]
    expected = {
        "Требований выделено": s["requirements"], "Требований проверено": s["reviewed_requirements"],
        "Замечаний всего": s["findings"], "— критичных": s["by_severity"]["critical"],
        "— существенных": s["by_severity"]["major"], "— незначительных": s["by_severity"]["minor"],
        "— подтверждённых": s["by_status"]["confirmed"], "— требующих проверки": s["by_status"]["needs_review"],
        "Проверок по критериям: соответствует": s["checks"]["pass"],
        "Проверок по критериям: нарушение": s["checks"]["issue"],
        "Проверок по критериям: не определено": s["checks"]["unknown"],
        "Проверок по критериям: неприменимо": s["checks"]["na"],
    }
    rows = dict(re.findall(r"^\| ([^|]+?) \| (\d+) \|$", section, flags=re.M))
    assert rows == {k: str(v) for k, v in expected.items()}

    # Кроме таблицы, числа в «Сводке» встречаются только в ID замечаний и местах документа.
    rest = re.sub(r"^\|.*\|$", "", section, flags=re.M)
    rest = re.sub(r"\[F-\d+\]\(#finding-F-\d+\)", "", rest)
    rest = re.sub(r"строк[аи] \d+(–\d+)?|с\. \d+|## 8\.", "", rest)
    allowed = {str(v) for v in expected.values()}
    assert set(re.findall(r"\d+", rest)) <= allowed
    for fid in s["critical_ids"]:
        assert f"[{fid}](#finding-{fid})" in section


def test_markdown_summary_is_not_recomputed(tmp_path):
    rep = load_example()
    rep["summary"]["checks"]["pass"] = 41
    rep["summary"]["requirements"] = 17
    md = write_markdown(rep, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "| Проверок по критериям: соответствует | 41 |" in md
    assert "| Требований выделено | 17 |" in md


def test_markdown_rich_report(tmp_path):
    rep = rich_report()
    md = write_markdown(rep, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Проверка неполная" in md and "этап individual прерван" in md
    assert "Незавершённые этапы: individual." in md
    assert "| individual | ошибка | 3 | 0 | gemini-2.5-flash | budget_exhausted |" in md
    assert "3e6b569" in md and "gemini-2.5-flash" in md
    # нарезка: требование без ID в документе, место на двух строках, статус проверки
    assert "| R-03 | нет (ID присвоен агентом) |" in md and "строки 7–8" in md
    assert "проверено частично: этап individual прерван до проверки по всем критериям" in md
    # карточка требующего проверки замечания: подсказка модели с местом, статусы раздельно
    card = md[md.index('<a id="finding-F-002"></a>'):]
    card = card[: card.index("<a id=", 10)]
    assert "требует проверки" in card and "привязка к тексту неполная" in card and "смысл не проверялся" in card
    assert "«быстро» — строки 7–8" in card
    # сводка: группы критичных по типу
    summary = md_section(md, "## 8. Сводка")
    assert summary.index("**Противоречивые:**") < summary.index("[F-001](#finding-F-001)")
    assert summary.index("**Неполные:**") < summary.index("[F-003](#finding-F-003)")
    # приложения
    for title in ("Вопросы аналитику", "Чек-лист ревью банка", "Черновик тест-кейсов",
                  "Сравнение с предыдущей редакцией", "Предупреждения", "Отклонённые кандидаты"):
        assert re.search(rf"^## Приложение [А-Я]\. {title}$", md, flags=re.M), title
    assert "TC-01" in md and "Указан канал уведомления" in md and "Q-002" in md
    assert "критик: термин общепринят" in md and "Часовой пояс указан" in md
    assert "чтение документа: Таблица в конце документа" in md
    # матрица требование × критерий: И4 (complete) — нарушение, И7 (verifiable) — не определено
    matrix = md_section(md, "## 5. Проверка каждого требования")
    row = next(line for line in matrix.splitlines() if line.startswith("| R-03 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[4] == "✗" and cells[7] == "?" and cells[1] == "·"


def test_partial_run_never_says_no_findings(tmp_path):
    rep = without_findings(rich_report(), "partial")
    md = write_markdown(rep, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Замечаний нет" not in md
    assert "Критичных замечаний нет" not in md and "Критичных дефектов нет" not in md
    assert "Замечаний не найдено, но проверка неполная" in md
    html = write_html(rep, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Замечаний нет" not in html


def test_complete_run_without_findings_says_so(tmp_path):
    rep = without_findings(load_example(), "complete")
    md = write_markdown(rep, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Замечаний нет." in md
    assert "Приложение" not in md  # все приложения пусты


# --------------------------------------------------------------------------- Jira CSV
def test_jira_csv_one_row_per_finding(report, tmp_path):
    path = write_jira_csv(report, tmp_path / "jira.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(report["findings"])
    assert list(rows[0]) == ["Summary", "Issue Type", "Priority", "Labels", "Description"]
    by_id = {re.search(r"(F-\d+):", r["Summary"]).group(1): r for r in rows}
    for f in report["findings"]:
        row = by_id[f["id"]]
        assert row["Summary"].startswith(f"[{rc.severity_label(f['severity'])}] {f['id']}: ")
        assert row["Issue Type"] == "Task"
        assert row["Priority"] == {"critical": "Highest", "major": "High", "minor": "Low"}[f["severity"]]
        assert row["Labels"].split() == ["bcc-review", f["kind"], f["criterion"]]
        for e in f["evidence"]:
            assert f"«{e['quote']}»" in row["Description"]
        assert report["run"]["run_id"] in row["Description"]
        assert report["run"]["source_sha256"] in row["Description"]
        if f.get("blocked_decision"):
            assert f["blocked_decision"] in row["Description"]


def test_jira_summary_is_truncated(tmp_path):
    rep = load_example()
    rep["findings"][0]["title"] = "очень длинный заголовок " * 30
    with write_jira_csv(rep, tmp_path / "j.csv").open(encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert len(row["Summary"]) <= 250 and row["Summary"].endswith("…")


# --------------------------------------------------------------------------- HTML
def test_html_written_with_anchors_and_marks(report, tmp_path):
    path = write_html(report, tmp_path / "r.html")
    page = path.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and '<html lang="ru">' in page
    assert "prefers-color-scheme: dark" in page
    assert 'id="block-b0003"' in page and "<mark" in page
    for f in report["findings"]:
        assert f'id="finding-{f["id"]}"' in page
    for b in report["document"]["blocks"]:
        assert f'id="block-{b["id"]}"' in page
    assert 'href="#block-b0003">строка 4</a>' in page


def test_html_has_no_external_resources(report, tmp_path):
    page = write_html(report, tmp_path / "r.html").read_text(encoding="utf-8")
    assert not re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", page, flags=re.I)
    assert not re.search(r"<(?:script|link|img|iframe)\b[^>]*\bsrc=", page, flags=re.I)
    assert "@import" not in page and "url(" not in page


def test_html_escapes_text_and_marks_every_evidence():
    rep = rich_report()
    page = render_html(rep)
    assert "<ID>" not in page and "&lt;ID&gt; из шаблона &amp; реестра" in page
    # опоры в этом отчёте не перекрываются: каждая — ровно один <mark> со ссылкой на своё замечание
    marked = re.findall(r'<mark class="sev-[a-z]+" title="[^"]*"><a href="#finding-([^"]+)">([^<]*)</a></mark>', page)
    for f in rep["findings"]:
        for e in rc.finding_evidence(f):
            assert (f["id"], html_lib.escape(e["quote"], quote=True)) in marked


def test_html_overlapping_evidence_keeps_text_verbatim():
    rep = load_example()
    rep["findings"].append(finding(id="F-002", kind="ambiguity", criterion="unambiguous", severity="minor",
                                   title="Неясно, «максимум один» на карту или на клиента",
                                   impact="Разные ожидания при двух картах.", req_ids=["R-01"],
                                   evidence=[ev(rep, "b0003", "карту приходится максимум один")],
                                   recommendation="Указать, что лимит считается на карту."))
    page = render_html(rep)
    block_html = re.search(r'<div class="block list_item" id="block-b0003">.*?<div class="text">(.*?)</div></div>',
                           page).group(1)
    assert 'href="#finding-F-001"' in block_html and 'href="#finding-F-002"' in block_html
    visible = re.sub(r'<sup class="ref">.*?</sup>|<span class="tag">.*?</span>|<[^>]+>', "", block_html)
    assert html_lib.unescape(visible) == rep["document"]["blocks"][2]["text"]
    # общий отрезок ведёт на более серьёзное замечание
    assert '<mark class="sev-critical" title="F-001, F-002"><a href="#finding-F-001">максимум один</a></mark>' \
        in block_html
