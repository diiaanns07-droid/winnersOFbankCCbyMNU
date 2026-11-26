"""Детерминированные правила (RULE-*): официальное ТЗ, чистое мини-ТЗ без замечаний, устойчивость."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bcc_review.contracts import FINDING_KINDS, INDIVIDUAL_CRITERIA, SET_CRITERIA, validate
from bcc_review.runtime.fallback.rules import RULE_IDS, lint
from bcc_review.runtime.fallback.text_reader import parse_markdown, read_text

FIXTURE = Path(__file__).parent / "fixtures" / "bcc_requirements.md"
_TEMPLATE = re.compile(r"ревью|согласующ", re.I)
_SID = re.compile(r"^([A-Za-zА-Яа-яЁё]{1,8}-\d+(?:\.\d+)*)\.?\s")


# --------------------------------------------------------------------------- помощники
def build_requirements(doc: dict) -> list[dict]:
    """Простая нарезка для теста: каждый абзац, пункт списка и строка таблицы вне шаблонов — требование."""
    reqs = []
    for b in doc["blocks"]:
        if b["kind"] not in ("list_item", "paragraph", "table_row") or not b["text"].strip():
            continue
        if len(b["section"]) <= 1 or any(_TEMPLATE.search(s) for s in b["section"]):
            continue
        m = _SID.match(b["text"])
        reqs.append({"id": f"R-{len(reqs) + 1:02d}", "source_id": m.group(1) if m else None,
                     "text": b["text"], "block_ids": [b["id"]], "kind": "functional"})
    return reqs


def doc_from_markdown(md: str) -> dict:
    blocks, title = parse_markdown(md)
    return {"id": "0" * 64, "title": title or "doc", "format": "markdown", "blocks": blocks, "warnings": []}


def run(doc: dict) -> dict:
    return lint(doc, build_requirements(doc))


def all_hints(c: dict) -> list[dict]:
    hs = list(c["hints"])
    if c.get("witness"):
        hs += [c["witness"]["hint_a"], c["witness"]["hint_b"]]
    return hs


def by_rule(cands: list[dict], rule_id: str) -> list[dict]:
    return [c for c in cands if c["rule_id"] == rule_id]


def quotes(c: dict) -> str:
    return " ‖ ".join(h["quote"] for h in all_hints(c))


def assert_contract(doc: dict, result: dict) -> None:
    blocks = {b["id"]: b for b in doc["blocks"]}
    for c in result["candidates"]:
        validate(c, "Candidate")
        assert c["source"] == "rules" and c["stage"] == "rules"
        assert c["rule_id"] in RULE_IDS
        assert c["kind"] in FINDING_KINDS
        assert c["criterion"] in INDIVIDUAL_CRITERIA + SET_CRITERIA
        assert c["severity"] in ("major", "minor"), "правила не выносят critical"
        assert c["scope"] == ("requirement" if len(c["req_ids"]) == 1 else "set")
        assert c["title"] and c["impact"] and c["recommendation"]
        assert set(c["cause"]) >= {"object", "condition", "outcomes"}
        if c["kind"] == "conflict":
            assert c.get("witness"), f"конфликт без witness: {c['title']}"
            validate(c["witness"], "WitnessDraft")
        for h in all_hints(c):
            text = blocks[h["block_id"]]["text"]
            assert 3 <= len(h["quote"]) <= 120, h
            assert h["quote"] in text, f"цитата не найдена дословно: {h}"
    for ch in result["checks"]:
        validate(ch, "Check")
        assert ch["status"] == "issue" and ch["source"] == "rules"
        assert ch["criterion"] in INDIVIDUAL_CRITERIA


# --------------------------------------------------------------------------- официальное ТЗ
@pytest.fixture(scope="module")
def official():
    doc = read_text(FIXTURE)
    return doc, run(doc)


def test_official_contract_and_no_warnings(official):
    doc, res = official
    assert res["warnings"] == []
    assert res["candidates"]
    assert_contract(doc, res)
    seen = set()
    for c in res["candidates"]:
        for h in c["hints"]:
            key = (c["rule_id"], h["block_id"], h["quote"])
            assert key not in seen, f"одна и та же цитата дважды в правиле: {key}"
            seen.add(key)


def test_official_get_used_for_save(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-HTTP-SEMANTICS")
    assert (c["kind"], c["criterion"], c["severity"]) == ("incorrect", "correct", "major")
    q = quotes(c)
    assert "GET" in q and "saveLimit" in q
    assert len(c["hints"]) >= 2
    assert "RFC 9110" in c["impact"]


def test_official_200_with_error_conflicts_with_400(official):
    doc, res = official
    [c] = by_rule(res["candidates"], "RULE-STATUS-EXAMPLE")
    assert (c["kind"], c["severity"]) == ("conflict", "major")
    w = c["witness"]
    blocks = {b["id"]: b for b in doc["blocks"]}
    assert "ERROR" in w["hint_a"]["quote"] and blocks[w["hint_a"]["block_id"]]["kind"] == "code"
    assert w["hint_b"]["quote"].startswith("400")
    for h in (w["hint_a"], w["hint_b"]):
        assert h["quote"] in blocks[h["block_id"]]["text"]


def test_official_type_mismatch_amount_enabled(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-TYPE-MISMATCH")
    assert (c["kind"], c["severity"]) == ("conflict", "major")
    q = quotes(c)
    for needle in ("amount | integer", "amount | string", "enabled | integer", "enabled | string"):
        assert needle in q
    assert "integer" in c["witness"]["outcome_a"] and "string" in c["witness"]["outcome_b"]


def test_official_units_tiyn_vs_tenge(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-UNITS")
    assert (c["kind"], c["severity"]) == ("incomplete", "major")
    q = quotes(c)
    assert "тиын" in q and "тенге" in q


def test_official_403_heading_says_404(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-STATUS-HEADING-BODY")
    assert (c["kind"], c["severity"]) == ("conflict", "major")
    assert c["witness"]["hint_a"]["quote"].startswith("403")
    assert "404" in c["witness"]["hint_b"]["quote"]
    undefined = by_rule(res["candidates"], "RULE-STATUS-UNDEFINED")
    assert any("404" in u["title"] for u in undefined)


def test_official_other_status_defects(official):
    _, res = official
    [summary] = by_rule(res["candidates"], "RULE-STATUS-SUMMARY")
    assert "201" in summary["title"] and summary["severity"] == "minor"
    [reason] = by_rule(res["candidates"], "RULE-STATUS-REASON")
    assert "Created" in reason["title"] and "201" in reason["title"]
    assert reason["severity"] == "major"


def test_official_read_without_read_method(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-READ-WITHOUT-METHOD")
    assert (c["kind"], c["severity"]) == ("omission", "major")
    q = quotes(c)
    assert "читает" in q and "saveLimit" in q


def test_official_vague_v_momente(official):
    _, res = official
    vague = by_rule(res["candidates"], "RULE-VAGUE")
    assert any("в момент" in quotes(c) for c in vague)
    # «максимум один push» — точная норма, не размытость
    assert not any("максимум" in quotes(c) for c in vague)


def test_official_open_list_i_dalee(official):
    _, res = official
    [c] = by_rule(res["candidates"], "RULE-OPEN-LIST")
    assert "и далее" in quotes(c)


def test_official_placeholders(official):
    _, res = official
    ph = by_rule(res["candidates"], "RULE-PLACEHOLDER")
    q = " ‖ ".join(quotes(c) for c in ph)
    assert "Да / Нет" in q
    assert "Prod: —" in q
    assert all(c["severity"] == "minor" for c in ph)
    # один кандидат на раздел, а не на ячейку
    assert len(ph) == len({c["title"].split(":")[0] for c in ph})
    empty = by_rule(res["candidates"], "RULE-EMPTY-SECTION")
    assert any("заполняются тестировщиками" in quotes(c) for c in empty)
    assert "заполняются тестировщиками" not in q, "заглушку раздела не повторяем дважды"


def test_official_terms_tz_traceability(official):
    _, res = official
    terms = by_rule(res["candidates"], "RULE-TERMS")
    actor = next(c for c in terms if "участник" in c["title"])
    assert actor["severity"] == "major"
    assert "владельца карты" in quotes(actor) and "Держатель" in quotes(actor)
    [tz] = by_rule(res["candidates"], "RULE-TZ")
    assert "Алматы" in quotes(tz) and tz["severity"] == "minor"
    assert by_rule(res["candidates"], "RULE-ACCEPTANCE-TRACE")
    assert by_rule(res["candidates"], "RULE-MISSING-ID")
    non_singular = {c["title"].split()[0] for c in by_rule(res["candidates"], "RULE-NON-SINGULAR")}
    assert "Ф-2" in non_singular and "Ф-4" not in non_singular


def test_official_checks_only_issues(official):
    _, res = official
    assert res["checks"]
    req_ids = {r["id"] for r in build_requirements(read_text(FIXTURE))}
    assert {ch["req_id"] for ch in res["checks"]} <= req_ids
    pairs = [(ch["req_id"], ch["criterion"]) for ch in res["checks"]]
    assert len(pairs) == len(set(pairs))


# --------------------------------------------------------------------------- чистое мини-ТЗ
CLEAN_SPEC = """# Сервис лимитов карты

## Общие сведения

| Поле | Значение |
| :--- | :--- |
| Наименование | Лимит операций по карте |
| Версия | 1.0 от 01.03.2026 |

## Функциональные требования

* **FR-1.** Клиент задаёт лимит операций по карте целым числом от 1 000 до 500 000 тенге включительно.
* **FR-2.** Система должна отклонять значение лимита вне диапазона из FR-1 с кодом ответа 400.
* **FR-3.** Сутки для расчёта лимита начинаются в 00:00 по времени UTC+5 (Asia/Almaty).
* **FR-4.** Приложение отображает текущий лимит, полученный методом GET /api/v1/limits/{cardId}.

## Нефункциональные требования

* **NFR-1.** Сервис отвечает на запрос сохранения лимита не более чем за 500 мс для 95% запросов.

## API

* **API-1.** POST /api/v1/limits сохраняет лимит карты из тела запроса в формате application/json.
* **API-2.** GET /api/v1/limits/{cardId} возвращает текущий лимит карты.

### Параметры запроса

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| cardId | string | Идентификатор карты |
| amount | integer | Лимит в тенге |

### Параметры ответа

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| cardId | string | Идентификатор карты |
| amount | integer | Лимит в тенге |

### Коды ответа

| Код | Описание |
| :--- | :--- |
| 200 | OK — лимит сохранён или прочитан |
| 400 | Bad Request — значение лимита вне допустимого диапазона |
| 404 | Not Found — карта не найдена |

## Критерии приемки

| ID | Требование | Действие | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| AC-1 | FR-1 | Сохранить лимит 1 000 тенге | Ответ 200 OK, лимит 1 000 тенге |
| AC-2 | FR-2 | Сохранить лимит 999 тенге | Ответ 400 Bad Request |
| AC-3 | FR-4 | Открыть экран лимита | Отображается сохранённый лимит |
"""


def test_clean_spec_has_zero_candidates():
    doc = doc_from_markdown(CLEAN_SPEC)
    res = run(doc)
    assert res["warnings"] == []
    assert res["candidates"] == [], "\n".join(f"{c['rule_id']}: {c['title']}" for c in res["candidates"])
    assert res["checks"] == []


# --------------------------------------------------------------------------- точечные проверки
def test_vague_ignores_headings_and_code():
    md = ("# Быстрый старт\n\n## Функциональные требования\n\n"
          "* **FR-1.** Система сохраняет лимит не более чем за 200 мс.\n\n"
          "```text\nбыстро и удобно, по возможности\n```\n")
    res = run(doc_from_markdown(md))
    assert by_rule(res["candidates"], "RULE-VAGUE") == []


def test_vague_detects_terms_and_keeps_numeric_limits_precise():
    md = ("# ТЗ\n\n## Функциональные требования\n\n"
          "* **FR-1.** Система должна быстро сохранять лимит.\n"
          "* **FR-2.** Допускается максимум 3 попытки ввода, не более 5 запросов в секунду.\n"
          "* **FR-3.** При необходимости оператор обычно подтверждает операцию.\n")
    doc = doc_from_markdown(md)
    res = run(doc)
    assert_contract(doc, res)
    vague = by_rule(res["candidates"], "RULE-VAGUE")
    text = " ‖ ".join(quotes(c) for c in vague)
    assert "быстро" in text and "При необходимости" in text and "обычно" in text
    assert "максимум" not in text and "не более" not in text
    assert all(c["severity"] == "major" and c["scope"] == "requirement" for c in vague)


def test_http_semantics_inline_get_with_write_verb():
    md = ("# API\n\n## Методы\n\n"
          "* **API-1.** GET /api/v1/cards/{cardId}/block блокирует карту.\n"
          "* **API-2.** GET /api/v1/cards/{cardId} возвращает карту.\n")
    doc = doc_from_markdown(md)
    res = run(doc)
    assert_contract(doc, res)
    http = by_rule(res["candidates"], "RULE-HTTP-SEMANTICS")
    assert len(http) == 1 and "/block" in http[0]["title"]


def test_http_semantics_ignores_write_verbs_of_other_methods():
    md = ("# API\n\n## Методы\n\n"
          "* **API-1.** GET /api/v1/limits/{cardId} возвращает лимит, сохранённый методом POST /api/v1/limits.\n"
          "* **API-2.** GET /api/v1/settings возвращает настройки карты.\n")
    res = run(doc_from_markdown(md))
    assert by_rule(res["candidates"], "RULE-HTTP-SEMANTICS") == []


def test_placeholder_in_requirement_text_is_major_and_grouped():
    md = ("# ТЗ\n\n## Функциональные требования\n\n"
          "* **FR-1.** Лимит перевода: TBD.\n"
          "* **FR-2.** Комиссия будет уточнена позже.\n\n"
          "## Общие сведения\n\n| Поле | Значение |\n| :--- | :--- |\n| Задача в JIRA | — |\n"
          "| Дата создания | 01.03.2026 10:00 |\n")
    doc = doc_from_markdown(md)
    res = run(doc)
    assert_contract(doc, res)
    ph = by_rule(res["candidates"], "RULE-PLACEHOLDER")
    assert len(ph) == 2
    req_ph = next(c for c in ph if "Функциональные" in c["title"])
    assert req_ph["severity"] == "major" and len(req_ph["hints"]) == 2 and len(req_ph["req_ids"]) == 2
    meta_ph = next(c for c in ph if "Общие сведения" in c["title"])
    assert meta_ph["severity"] == "minor" and "Задача в JIRA | —" in quotes(meta_ph)
    assert by_rule(res["candidates"], "RULE-TZ") == [], "время в паспорте документа — не правило периода"


def test_deterministic_output():
    doc = read_text(FIXTURE)
    reqs = build_requirements(doc)
    a = json.dumps(lint(doc, reqs), ensure_ascii=False, sort_keys=True)
    b = json.dumps(lint(read_text(FIXTURE), build_requirements(read_text(FIXTURE))), ensure_ascii=False,
                   sort_keys=True)
    assert a == b


def test_without_requirements_findings_are_set_level():
    doc = read_text(FIXTURE)
    res = lint(doc, [])
    assert res["warnings"] == []
    assert res["candidates"] and res["checks"] == []
    assert all(c["scope"] == "set" and c["req_ids"] == [] for c in res["candidates"])
    assert_contract(doc, res)
