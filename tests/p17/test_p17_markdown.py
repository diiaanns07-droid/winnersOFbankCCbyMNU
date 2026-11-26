"""Обязательные разделы, прослеживаемость и вид отчёта Markdown."""

from __future__ import annotations

import json
import re

import pytest
from p17_fixtures import build_report
from p17_helpers import section, split_row, tables

from bcc_review.exports.markdown import check_markdown, render_markdown, write_markdown

REQUIRED_HEADINGS = [
    "## Решение",
    "## 1. Паспорт прогона",
    "## 2. Нарезка требований",
    "## 3. Проверка каждого требования",
    "## 4. Проверка всего набора требований",
    "## 5. Сводка",
    "## 6. Итог и приоритетные правки",
]


@pytest.mark.parametrize("numbered", [True, False], ids=["с-нумерацией", "без-нумерации"])
@pytest.mark.parametrize("variant", ["complete", "partial", "failed"])
def test_required_sections_in_order(variant, numbered):
    md = render_markdown(build_report(variant, numbered))
    positions = [md.find(h + "\n") for h in REQUIRED_HEADINGS]
    assert all(p >= 0 for p in positions), [h for h, p in zip(REQUIRED_HEADINGS, positions, strict=True) if p < 0]
    assert positions == sorted(positions), "разделы идут не в порядке п. 6 ТЗ"
    first_screen = md[: positions[1]]
    assert "Разработка" in first_screen and "Тестирование" in first_screen
    assert "Критичные проблемы" in first_screen
    assert "Первое действие" in first_screen


def test_passport_fields():
    report = build_report("complete")
    passport = section(render_markdown(report), "## 1. Паспорт прогона")
    for label in (
        "SHA-256 байтов входа", "Физических вызовов модели", "Модель (фактическая)", "Токены", "Длительность",
        "Статус поставщика", "Режим", "Версия агента", "Статус прогона", "Этапы", "Идентификатор прогона",
    ):
        assert f"| {label} |" in passport, label
    assert report["run"]["source_sha256"] in passport
    assert "| Токены | вход 12 450, выход 3 210; всего 15 660 токенов |" in passport
    assert "| Длительность | 1 мин 24 с |" in passport
    assert "| Статус поставщика | ответы получены |" in passport


def test_first_action_follows_order_field():
    md = render_markdown(build_report("complete"))
    assert "**Первое действие:** Решить вопрос Q-001 и исправить ТР-3 или ТР-4 ([F-001](#f-f-001))" in md


def test_slicing_table_numbered_and_unnumbered():
    md_num = section(render_markdown(build_report("complete", True)), "## 2. Нарезка требований")
    md_un = section(render_markdown(build_report("complete", False)), "## 2. Нарезка требований")
    assert "| [R-01](#r-r-01) | ТР-1 |" in md_num
    assert "| [R-06](#r-r-06) | — (присвоен агентом) |" in md_num
    assert md_un.count("— (присвоен агентом)") == 9
    assert "с ID документа — 0, с ID, присвоенным агентом, — 9" in md_un
    assert "- Заголовки, не требования: строки 1, 5, 13, 17, 23" in md_num


def test_unnumbered_requirement_keeps_quote():
    md = render_markdown(build_report("complete", numbered=False))
    block = section(md, '### <a id="r-r-03"></a>R-03')
    assert "R-03 · без ID в документе · функциональное" in block
    assert "> Автор отменяет бронь только до начала встречи. После отмены комната становится свободной." in block


def test_clean_requirement_visible_in_individual_check():
    block = section(render_markdown(build_report("complete")), '### <a id="r-r-02"></a>R-02')
    assert "**Проверка:** ✅ проверено полностью: 9 критериев · **Итог:** замечаний нет" in block
    assert "✖" not in block
    assert "####" not in block


def test_partial_requirement_shows_reason_and_skipped_criteria():
    md = render_markdown(build_report("partial"))
    block = section(md, '### <a id="r-r-06"></a>R-06')
    assert "◐ проверено частично: 2 из 9 критериев" in block
    assert "**Причина неполной проверки:** Этап individual: тайм-аут поставщика после 2 из 9 критериев." in block
    assert "⏸" in block
    unchecked = section(md, '### <a id="r-r-07"></a>R-07')
    assert "✖ не проверено" in unchecked
    # R-07 не проверено индивидуально, но его затрагивает подтверждённая находка набора F-005.
    assert "**Итог:** подтверждённых замечаний — 1" in unchecked
    clean_partial = build_report("partial")
    clean_partial["findings"] = [f for f in clean_partial["findings"] if "R-07" not in f["req_ids"]]
    block = section(render_markdown(clean_partial), '### <a id="r-r-07"></a>R-07')
    assert "подтверждённых замечаний нет (проверка неполная)" in block


def test_issue_checks_listed_with_reason_and_link():
    block = section(render_markdown(build_report("complete")), '### <a id="r-r-05"></a>R-05')
    assert "- ✖ Проверяемость: «Быстро» не задаёт измеримого времени показа статуса → [F-002](#f-f-002)" in block


def test_contradiction_shows_both_places_and_witness():
    card = section(render_markdown(build_report("complete")), '#### <a id="f-f-001"></a>F-001')
    assert "Место А: Функциональные требования, строка 9" in card
    assert "Место Б: Функциональные требования, строка 10" in card
    assert "Карточка-свидетель F-001" in card
    assert "**Сценарий:** Встреча началась в 10:00" in card
    assert "**Исход А по [R-03](#r-r-03)" in card and "**Исход Б по [R-04](#r-r-04)" in card
    assert "**Что блокирует:** блокирует разработку, тестирование; решение: Разрешать ли отмену брони" in card
    assert "**Вопрос заказчику:** [Q-001](#q-q-001)" in card


def test_omission_shows_promise_line_from_map_and_inspected_sections():
    card = section(render_markdown(build_report("complete")), '#### <a id="f-f-005"></a>F-005')
    # Цитата в третьей строке многострочного блока 19–21: строка считается по loc.map.
    assert "Обещание в тексте: Требования к уведомлениям, строка 21" in card
    assert (
        "**Проверено, где описание должно быть:** Функциональные требования (строки 7–11); "
        "Критерии приемки (строки 27–28)"
    ) in card


def test_coverage_table_and_card():
    block = section(render_markdown(build_report("complete")), "### 4.4. Покрытие критериями приёмки")
    assert "| [R-01](#r-r-01)\u00a0(ТР-1) | Бронь от 15 до 240 минут с шагом 15 минут | [R-08](#r-r-08):" in block
    assert "| ◐ частично | Проверен только интервал 30 минут" in block
    assert "Покрыто полностью: 1 из 7 обязательств (14,3 %)" in block
    assert '#### <a id="f-f-007"></a>F-007' in block
    assert "Обещание в тексте" not in block


def test_same_cause_linked_both_ways_and_merged_from_shown():
    md = render_markdown(build_report("complete"))
    primary = section(md, '#### <a id="f-f-003"></a>F-003')
    dup = section(md, '#### <a id="f-f-004"></a>F-004')
    assert "**Та же первопричина:** [F-004](#f-f-004)" in primary
    assert "**Та же первопричина, что у [F-003](#f-f-003)**" in dup
    assert "**Объединено при подготовке:** C-014" in section(md, '#### <a id="f-f-002"></a>F-002')


def test_customer_decision_vs_model_proposal():
    md = render_markdown(build_report("complete"))
    questions = section(md, "### Б. Уточняющие вопросы заказчику")
    assert "Варианты (предложение модели)" in questions and "Решение заказчика" in questions
    assert "| нет решения |" in questions
    assert "**Кнопкой «Подтвердить» в напоминании, до начала встречи.**" in questions
    assert "Решено заказчиком: 1 из 2 вопросов." in questions
    assert "**предложение модели**" in section(md, "### А. Чек-лист ревью требований")
    tests = section(md, "### В. Приёмка и черновик тест-кейсов")
    assert "Критерии приёмки **из документа**" in tests and "**черновик агента**" in tests
    assert "[Q-001](#q-q-001) — ждёт решения" in tests
    decisions = section(md, "### Г. Решения заказчика и версии документа")
    assert "| [Q-002](#q-q-002) | **Кнопкой «Подтвердить» в напоминании, до начала встречи.** | нет | текущая редакция |" in decisions


def test_answer_to_other_version_flagged():
    report = build_report("complete")
    report["decisions"][0]["source_sha256"] = "a" * 64
    md = render_markdown(report)
    assert "⚠️ ответ дан к другой редакции документа" in md
    assert "редакция `aaaaaaaaaaaa…`" in md


def test_diff_section_rendered():
    report = build_report("complete")
    report["diff"] = {
        "previous": {"source_sha256": "b" * 64, "run_id": "old"},
        "current": {"source_sha256": report["run"]["source_sha256"], "run_id": "new"},
        "resolved": [{"old_ids": ["F-009"], "new_ids": [], "reason": "Порог уточнён", "evidence": []}],
        "persisting": [{"old_ids": ["F-001"], "new_ids": ["F-001"], "reason": "Противоречие осталось", "evidence": []}],
        "introduced": [], "unassessed": [], "impacted_req_ids": ["R-03"], "warnings": [],
    }
    block = section(render_markdown(report), "### Г. Решения заказчика и версии документа")
    assert "было `bbbbbbbbbbbb…`" in block
    assert "| Устранено | 1 | F-009 → —: Порог уточнён |" in block
    assert "| Появилось | 0 | — |" in block
    assert "Затронутые требования: [R-03](#r-r-03)\u00a0(ТР-3)" in block


def test_rejected_collapsible_with_reason():
    block = section(render_markdown(build_report("complete")), "### Е. Снятые замечания")
    assert "<details>" in block and "</details>" in block
    assert "Снято при самопроверке: 1 замечание." in block
    assert "Причина снятия: Интервалы полуоткрытые" in block
    assert "этап verify\\_meaning" in block


def test_every_internal_link_has_anchor():
    for variant in ("complete", "partial", "failed"):
        md = render_markdown(build_report(variant))
        anchors = set(re.findall(r'<a id="([^"]+)"></a>', md))
        links = set(re.findall(r"\]\(#([^)]+)\)", md))
        assert links <= anchors, links - anchors


def test_tables_have_consistent_columns():
    for variant in ("complete", "partial", "failed"):
        for numbered in (True, False):
            for tbl in tables(render_markdown(build_report(variant, numbered))):
                assert len({len(split_row(row)) for row in tbl}) == 1, tbl


def test_pipe_in_quote_does_not_break_tables():
    md = render_markdown(build_report("complete"))
    row = next(line for line in md.splitlines() if line.startswith("| [R-05](#r-r-05)"))
    assert len(split_row(row)) == 6
    assert "«свободно \\| занято \\| на обслуживании»" in row


def test_code_spans_not_escaped():
    md = render_markdown(build_report("complete"))
    assert "| `set_complete` |" in md
    assert "`set\\_" not in md


def test_evidence_mismatch_is_flagged():
    report = build_report("complete")
    report["findings"][1]["evidence"][0]["quote"] = "Система мгновенно показывает статус"
    md = render_markdown(report)
    assert "⚠️ цитата не совпадает с текстом блока" in md
    assert "| Цитаты замечаний, сверенные с документом | 7 из 8 цитат (87,5 %); не совпали или без блока — 1 |" in md


def test_document_id_mismatch_is_flagged():
    report = build_report("complete")
    report["document"]["id"] = "0" * 64
    md = render_markdown(report)
    assert "| ⚠️ Сверка идентификатора | `document.id` не совпадает с `run.source_sha256`" in md


def test_write_markdown_returns_path_and_roundtrips(tmp_path):
    report = build_report("complete")
    path = write_markdown(report, tmp_path / "nested" / "report.md")
    assert path == tmp_path / "nested" / "report.md"
    assert path.read_text(encoding="utf-8") == render_markdown(report)
    assert check_markdown(path, report) == []
    assert not list(path.parent.glob("*.tmp"))


def test_accepts_json_path(tmp_path):
    report = build_report("complete")
    jpath = tmp_path / "report.json"
    jpath.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert render_markdown(jpath) == render_markdown(report)
