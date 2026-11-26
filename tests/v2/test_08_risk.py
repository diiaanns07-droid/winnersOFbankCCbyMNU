"""Линза «Риски» (№08): промпт и постобработка, без сети."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import lens_risk  # noqa: E402

PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "lens_risk.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "08_risk"

# Слова и числа официального документа: промпт должен работать на любом банковском ТЗ.
OFFICIAL_WORDS = ["push", "savelimit", "тиын", "порог", "алмат", "almaty", "ф-1", "ф-2", "ф-3", "ф-4",
                  "cardid", "alertscontroller", "бюджет", "48 500", "50 000", "31 января", "23:58",
                  "limit_kzt", "проверьте сумму", "карта не найдена"]


def _cand(title, severity="major", kind="ambiguity", criterion="unambiguous", **kw):
    c = {"title": title, "kind": kind, "criterion": criterion, "severity": severity,
         "requirement_ids": ["R-01"], "evidence": [{"quote": "цитата", "line": 1}],
         "problem": "п", "scenario": "с", "impact": "и", "recommendation": "р", "rewrite": "",
         "question": "", "blocks": "both"}
    c.update(kw)
    return c


def test_prompt_has_no_official_document_words():
    text = PROMPT.read_text(encoding="utf-8").lower()
    found = [w for w in OFFICIAL_WORDS if w in text]
    assert not found, f"слова официального документа в промпте: {found}"


def test_prompt_covers_risk_topics():
    text = PROMPT.read_text(encoding="utf-8").lower()
    for topic in ["авторизац", "клиринг", "возврат", "квази-кэш", "utc+5", "дополнительной карты",
                  "404", "журнал", "дедупликац", "гонки", "отката", "зацепк", "pci dss"]:
        assert topic in text, topic
    assert "{{" not in text.replace("{{severity_scale}}", ""), "в задании линзы нет подстановок"


def test_security_critical_is_capped_to_major():
    c = lens_risk.calibrate(_cand("Номер карты в строке запроса", "critical", "security", "risk"))
    assert c["severity"] == "major"


def test_critical_without_scenario_is_major():
    c = lens_risk.calibrate(_cand("Событие не определено", "critical", scenario=""))
    assert c["severity"] == "major"
    c = lens_risk.calibrate(_cand("Событие не определено", "critical", blocks="none"))
    assert c["severity"] == "major"


def test_domain_critical_is_kept():
    c = lens_risk.calibrate(_cand("Не определено, что считается проведённой операцией", "critical"))
    assert c["severity"] == "critical"


def test_out_of_scope_topics_dropped_without_hook():
    doc = "Клиент блокирует карту. Логика работы метода: проверить сессию."
    cands = [_cand("Нет требований соответствия PCI DSS"),
             _cand("Не описан аудит изменения настроек"),
             _cand("Нет схемы отката и feature flag"),
             _cand("Не определён часовой пояс границы суток")]
    kept, dropped = lens_risk.postprocess(cands, doc)
    assert [c["title"] for c in kept] == ["Не определён часовой пояс границы суток"]
    assert len(dropped) == 3 and all(d["reject_reason"] for d in dropped)


def test_critical_is_never_dropped_by_topic_filter():
    doc = "Сервис передаёт уведомление в течение минуты. В расходы входят проведённые покупки."
    c = _cand("Цель «в момент покупки» несовместима с учётом проведённых покупок и минутным SLA", "critical")
    kept, dropped = lens_risk.postprocess([c, _cand("Нет мониторинга доступности сервиса")], doc)
    assert [k["severity"] for k in kept] == ["critical"] and len(dropped) == 1


def test_hook_in_document_keeps_topic():
    doc = "Реализация предусматривает схему отката решений. Хранить инициатора изменения."
    kept, _ = lens_risk.postprocess([_cand("Схема отката не описана", "minor", "ops_risk", "risk"),
                                     _cand("Нет аудита смены настроек", "major", "ops_risk", "risk")], doc)
    assert len(kept) == 2


def test_postprocess_sorts_dedups_and_caps():
    cands = [_cand(f"Риск {i}", "minor") for i in range(14)]
    cands.insert(5, _cand("Ключевое событие", "critical"))
    cands.append(_cand("Риск 0", "minor"))
    kept, dropped = lens_risk.postprocess(cands, "документ")
    assert len(kept) == lens_risk.MAX_CANDIDATES
    assert kept[0]["title"] == "Ключевое событие"
    reasons = {d["reject_reason"] for d in dropped}
    assert "дубль заголовка" in reasons and any("сверх лимита" in r for r in reasons)


def test_candidate_without_evidence_dropped():
    kept, dropped = lens_risk.postprocess([_cand("Без цитаты", evidence=[])], "текст")
    assert not kept and dropped[0]["reject_reason"] == "нет цитаты-зацепки"


def test_doc_text_accepts_docview():
    view = {"lines": [{"n": 1, "text": "Схема ОТКАТА"}]}
    assert "отката" in lens_risk._doc_text(view)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("official_*.json")), ids=lambda p: p.stem)
def test_saved_live_answers_keep_key_event(path):
    """Сохранённые живые ответы на официальном документе: ключевое событие (К5) остаётся critical."""
    data = json.loads(path.read_text(encoding="utf-8"))
    view = (ROOT / "release" / "input" / "requirements.md").read_text(encoding="utf-8")
    kept, _ = lens_risk.postprocess(data["candidates"], view)
    assert len(kept) <= lens_risk.MAX_CANDIDATES
    k5 = [c for c in kept if c["severity"] == "critical"
          and re.search(r"проведен|проведён|клиринг|авторизац|событи", c["title"] + c["problem"], re.I)]
    assert k5, "ключевое событие процессинга не найдено как critical"
