"""Устойчивость на незнакомых документах: находки независимой проверки GPT Pro на сборке 8e8e95f.

* описательные требования без «должен» под заголовками с ID не теряются (было: 0 требований → failed);
* эвристические правила проходят через критика, когда модель доступна;
* правила не поднимают ложных тревог на типовых чистых формулировках;
* .env с BOM (Windows PowerShell 5.1) читается.
"""

import json
import os

import pytest

from bcc_review import contracts as C
from bcc_review import engine
from bcc_review.runtime.fallback.rules import lint

from .conftest import BCC, write_script, run

DESCRIPTIVE = """# Квитанция о закрытии вклада

## Часть A. Обслуживание в отделении

### А-1. Срок выдачи

Квитанция выдаётся после регистрации заявления.

## Часть B. Контроль выдачи

### Б-1. Начало и конец измерения

Начало отсчёта совпадает с регистрацией заявления. Конец отсчёта совпадает с появлением квитанции на экране оператора.

### Б-2. Повторная выдача

Повторная печать квитанции возможна в течение 30 календарных дней.
"""


def test_descriptive_requirements_under_id_headings_are_reviewed(tmp_path):
    src = tmp_path / "descriptive.md"
    src.write_text(DESCRIPTIVE, encoding="utf-8")
    rep = run(tmp_path, src, offline_lint=True)
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    texts = " ".join(r["text"] for r in rep["requirements"])
    assert "Начало отсчёта совпадает" in texts and "Повторная печать" in texts
    by_sid = {r["source_id"] for r in rep["requirements"]}
    assert {"Б-1", "Б-2"} <= by_sid
    assert rep["run"]["status"] != "failed"
    inv = next(s for s in rep["run"]["stages"] if s["name"] == "inventory")
    assert inv["status"] == "ok"
    every_block = {b for r in rep["requirements"] for b in r["block_ids"]} | {b for e in rep["excluded"] for b in e["block_ids"]}
    content = [b["id"] for b in rep["document"]["blocks"] if b["kind"] not in ("heading", "table_header")]
    assert set(content) <= every_block


def test_heuristic_rule_findings_go_to_critic_factual_do_not(tmp_path, monkeypatch, mock_script):
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")
    mock_script["verify_meaning"] = {"__verdicts__": "confirmed", "reject": ["Один участник назван по-разному"]}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script), use_cache=False)
    assert not [f for f in rep["findings"] if f.get("rule_id") == "RULE-TERMS" and "участник" in f["title"]]
    assert any("Один участник" in (r["candidate"].get("title") or "") and r["stage"] == "verify_meaning"
               for r in rep["rejected"])
    get_save = [f for f in rep["findings"] if f.get("rule_id") == "RULE-HTTP-SEMANTICS"]
    assert get_save and get_save[0]["meaning_status"] == "deterministic"
    terms_limit = [f for f in rep["findings"] if f.get("rule_id") == "RULE-TERMS"]
    assert all(f["meaning_status"] == "confirmed" for f in terms_limit)


def _doc(tmp_path, text):
    from bcc_review.engine import read_document

    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return read_document(p)


def _rule_ids(doc):
    return {c.get("rule_id") for c in lint(doc, [])["candidates"]}


def test_no_terms_alarm_for_account_owner_and_client(tmp_path):
    doc = _doc(tmp_path, "# ТЗ\n\n## Функциональные требования\n\n"
                         "* **Ф-1.** Владелец счёта подписывает заявление.\n"
                         "* **Ф-2.** Клиент получает квитанцию после подписи.\n")
    assert "RULE-TERMS" not in _rule_ids(doc)


def test_terms_alarm_for_card_holder_vs_owner(tmp_path):
    doc = _doc(tmp_path, "# ТЗ\n\n## Функциональные требования\n\n"
                         "* **Ф-1.** Держатель карты задаёт порог.\n"
                         "* **Ф-2.** Доступ проверяется по сессии владельца карты.\n")
    assert "RULE-TERMS" in _rule_ids(doc)


def test_no_read_alarm_when_client_receives_field_in_post_response(tmp_path):
    doc = _doc(tmp_path, "# ТЗ\n\n## Функциональные требования\n\n"
                         "* **Ф-1.** Клиент получает номер заявки в ответе на создание заявки.\n\n"
                         "## REST API\n\n| Поле | Значение |\n| :--- | :--- |\n| **Method** | POST |\n"
                         "| **URL** | `/requests/create` |\n")
    assert "RULE-READ-WITHOUT-METHOD" not in _rule_ids(doc)


def test_no_tz_alarm_when_zone_explicit_or_duration(tmp_path):
    doc = _doc(tmp_path, "# ТЗ\n\n## Функциональные требования\n\n"
                         "* **Ф-1.** Все времена указаны в UTC+5 (Asia/Almaty).\n"
                         "* **Ф-2.** Заявки после 18:00 обрабатываются следующим операционным днём.\n")
    assert "RULE-TZ" not in _rule_ids(doc)
    doc2 = _doc(tmp_path, "# ТЗ\n\n## Функциональные требования\n\n"
                          "* **Ф-1.** Повторная печать возможна в течение 30 календарных дней.\n")
    assert "RULE-TZ" not in _rule_ids(doc2)


def test_tz_alarm_kept_for_city_without_offset():
    doc = engine.read_document(BCC)
    assert "RULE-TZ" in _rule_ids(doc)


def test_dotenv_with_bom(tmp_path, monkeypatch):
    monkeypatch.undo()  # conftest подменяет load_dotenv заглушкой; здесь нужна настоящая функция
    env = tmp_path / ".env"
    env.write_bytes("﻿BCC_TEST_KEY=abc123\n# комментарий\nBCC_TEST_QUOTED=\"x y\"\n".encode("utf-8"))
    os.environ.pop("BCC_TEST_KEY", None)
    os.environ.pop("BCC_TEST_QUOTED", None)
    try:
        engine.load_dotenv(env)
        assert os.environ.get("BCC_TEST_KEY") == "abc123"
        assert os.environ.get("BCC_TEST_QUOTED") == "x y"
    finally:
        os.environ.pop("BCC_TEST_KEY", None)
        os.environ.pop("BCC_TEST_QUOTED", None)
