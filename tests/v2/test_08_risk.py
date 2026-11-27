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
                  "limit_kzt", "проверьте сумму", "карта не найдена", "требуется вход", "demo-42", "19 900",
                  "00:03", "1 февраля", "февральск", "уведомление о расходах", "месячный порог", "учёт расходов",
                  "учет расходов", "сервис расходов", "практикум", "учебный контур", "проведённые покупки",
                  "проведенные покупки", "независимо от истории", "повторная доставка одного события"]


def _sev(title, kept, dropped):
    """Итог для заголовка: уровень, если оставлен, иначе «снято»."""
    for c in kept:
        if c["title"] == title:
            return c["severity"]
    assert any(d["title"] == title for d in dropped), title
    return "снято"


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


def test_role_terminology_becomes_security():
    c = lens_risk.calibrate(_cand("Роль названа тремя терминами: держатель, владелец карты, клиент", "major",
                                  "terminology", "conforming"))
    assert (c["kind"], c["criterion"], c["severity"]) == ("security", "risk", "major")
    c = lens_risk.calibrate(_cand("Компонент назван по-разному: учёт и сервис", "minor", "terminology", "conforming"))
    assert c["kind"] == "terminology"


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


def test_personal_data_transfer_is_security_not_compliance():
    t = "Персональные данные и анкета передаются партнёру без согласия клиента"
    kept, dropped = lens_risk.postprocess([_cand(t, "major", "security", "risk")], "Банк передаёт анкету партнёру.")
    assert _sev(t, kept, dropped) == "major"


def test_hook_in_document_keeps_topic():
    doc = "Реализация предусматривает схему отката решений. Хранить инициатора изменения."
    kept, _ = lens_risk.postprocess([_cand("Схема отката не описана", "minor", "ops_risk", "risk"),
                                     _cand("Нет аудита смены настроек", "major", "ops_risk", "risk")], doc)
    assert len(kept) == 2


def test_postprocess_sorts_dedups_and_caps():
    cands = [_cand(f"Риск {i}", "major") for i in range(14)]
    cands.insert(5, _cand("Ключевое событие", "critical"))
    cands.append(_cand("Риск 0", "major"))
    kept, dropped = lens_risk.postprocess(cands, "документ")
    assert len(kept) == lens_risk.MAX_CANDIDATES
    assert kept[0]["title"] == "Ключевое событие"
    reasons = {d["reject_reason"] for d in dropped}
    assert "дубль заголовка" in reasons and any("сверх лимита" in r for r in reasons)


def test_terms_section_caps_severity_to_minor():
    doc = "# Документ\n\n### Термины\n* **Месяц** — календарный месяц по UTC+5.\n\n### Требования\n* Правило.\n"
    assert lens_risk.terms_lines(doc) == {3, 4, 5}
    c_terms = _cand("Месяц не привязан к дате операции", "critical", evidence=[{"quote": "Месяц", "line": 4}])
    c_mixed = _cand("Правило против определения", "critical", "contradiction", "set_consistent",
                    evidence=[{"quote": "Месяц", "line": 4}, {"quote": "Правило", "line": 7}])
    kept, dropped = lens_risk.postprocess([c_terms, c_mixed], doc)
    # тонкость определения → minor, а minor без зацепки — вопрос, не замечание линзы
    assert _sev("Месяц не привязан к дате операции", kept, dropped) == "снято"
    assert _sev("Правило против определения", kept, dropped) == "critical"
    c_vague = _cand("Месяц: дата авторизации или проведения", "major",
                    evidence=[{"quote": "Месяц", "line": 4}, {"quote": "Правило", "line": 7}])
    kept, dropped = lens_risk.postprocess([c_vague], doc)
    assert _sev(c_vague["title"], kept, dropped) == "снято"
    c_tz = _cand("Пояс суток назван городом, а не смещением UTC", "major",
                 evidence=[{"quote": "Месяц", "line": 4}, {"quote": "Правило", "line": 7}])
    kept, dropped = lens_risk.postprocess([c_tz], doc)
    assert _sev(c_tz["title"], kept, dropped) == "minor", "minor с зацепкой (пояс) остаётся"


def test_terms_lines_from_docview_sections():
    view = {"lines": [{"n": 1, "text": "Термины", "section": "Часть A › Термины"},
                      {"n": 2, "text": "Сутки — с 00:00", "section": "Часть A › Термины"},
                      {"n": 3, "text": "ЛП-1", "section": "Часть A › Функциональные требования"}]}
    assert lens_risk.terms_lines(view) == {1, 2}


def test_ops_major_without_hook_is_minor():
    doc = "Клиент задаёт лимит. Сервис начисляет кэшбэк."
    titles = ["Нет ключа дедупликации событий", "Параллельные покупки у границы лимита", "Сбой зачисления: итог не описан"]
    kept, dropped = lens_risk.postprocess([_cand(t, "major", "ops_risk", "risk") for t in titles], doc)
    assert not kept and {_sev(t, kept, dropped) for t in titles} == {"снято"}
    kept, _ = lens_risk.postprocess([_cand("Возврат при лимите 10 000 ₸ и пороге 500 ₸ даёт неопределённый итог")], doc)
    assert kept[0]["severity"] == "major", "сумма 500 ₸ — не код ответа 5xx"
    doc2 = "Повторная доставка одного события сохраняет исходный итог."
    kept, _ = lens_risk.postprocess([_cand("Нет ключа дедупликации событий", "major", "ops_risk", "risk")], doc2)
    assert kept[0]["severity"] == "major"


def test_security_major_needs_interface_anchor():
    kept, dropped = lens_risk.postprocess([
        _cand("Источник уведомления не описан: подложное уведомление запускает списание", "major", "security", "risk"),
        _cand("Изменение настройки методом GET с суммой в строке запроса", "major", "security", "risk"),
        _cand("Для чужой карты обещаны 403 и 404", "major", "security", "risk")], "документ")
    assert [c["severity"] for c in kept] == ["major", "major"]
    assert _sev("Источник уведомления не описан: подложное уведомление запускает списание", kept, dropped) == "снято"
    kept, _ = lens_risk.postprocess([_cand("Для чужой карты одновременно обещаны 403 и 404", "major", "security",
                                           "risk")], "документ")
    assert kept[0]["severity"] == "major", "«одновременно обещаны» — не гонка событий"
    doc = "Повторная доставка одного события сохраняет исходный итог."
    kept, _ = lens_risk.postprocess([_cand("Идемпотентность без ключа дедупликации; гонки у границы не описаны",
                                           "major", "ops_risk", "risk")], doc)
    assert kept[0]["severity"] == "major", "одна из тем (повторы) имеет зацепку"


def test_refund_rollback_wording_not_dropped():
    t = "Списание без отката денег, если пополнение не прошло"
    kept, dropped = lens_risk.postprocess([_cand(t)], "текст")
    # не снят фильтром темы «откат функции» (это возврат денег), но как сбой без зацепки — вопрос, не замечание
    assert _sev(t, kept, dropped) == "снято" and "тема" not in dropped[0]["reject_reason"]
    doc = "Операция недоступна"  # «недоступна» в тексте ответа — не зацепка для темы сбоев
    t = "При ответе 500 неизвестно, применена ли блокировка"
    kept, dropped = lens_risk.postprocess([_cand(t)], doc)
    assert _sev(t, kept, dropped) == "снято"


def test_critical_cap():
    kept, _ = lens_risk.postprocess([_cand(f"Событие {i}", "critical") for i in range(4)], "текст")
    assert [c["severity"] for c in kept] == ["critical", "critical", "major", "major"]


def test_minor_only_with_text_hook_and_capped():
    cands = [_cand("Ключевое событие", "critical")] + [_cand(f"Пояс назван городом {i}", "minor") for i in range(4)]
    kept, dropped = lens_risk.postprocess(cands, "документ")
    assert [c["severity"] for c in kept].count("minor") == lens_risk.MAX_MINOR
    assert sum("лимита minor" in d["reject_reason"] for d in dropped) == 2
    cands = [_cand("Валюта операции не определена", "minor"), _cand("Гонка у границы", "minor"),
             _cand("Пункт шаблона ревью про схему отката не заполнен", "minor")]
    kept, dropped = lens_risk.postprocess(cands, "схема отката решений")
    assert [c["title"] for c in kept] == ["Пункт шаблона ревью про схему отката не заполнен"]
    assert all("без текстовой зацепки" in d["reject_reason"] for d in dropped)


def test_key_event_critical_is_ambiguity():
    c = lens_risk.calibrate(_cand("Цель «в момент покупки» несовместима: не определено, какое событие запускает правило",
                                  "critical", "event_conflict", "set_consistent"))
    assert (c["kind"], c["criterion"], c["severity"]) == ("ambiguity", "unambiguous", "critical")
    c = lens_risk.calibrate(_cand("Не определён этап операции: авторизация или проведение", "critical",
                                  "missing_element", "complete"))
    assert c["kind"] == "ambiguity"
    # противоречие критерия приёмки с правилом — основание (а), вид не трогаем
    c = lens_risk.calibrate(_cand("Критерий приёмки и правило: событие проведения относит к другому месяцу",
                                  "critical", "contradiction", "set_consistent"))
    assert c["kind"] == "contradiction"


def test_acceptance_conflicts_left_to_qa():
    k1 = _cand("Месяц покупки: правило и проведение в строке приёмки расходятся", "critical", "contradiction",
               "set_consistent", requirement_ids=["R-06", "R-14"])
    k1_title = _cand("Критерий приёмки относит покупку к февралю, правило — к январю", "critical",
                     "event_conflict", "set_consistent", requirement_ids=["R-06"])
    rule_vs_rule = _cand("Два правила по-разному решают, уменьшает ли отмена сумму", "critical", "contradiction",
                         "set_consistent", requirement_ids=["R-07", "R-09"])
    period = _cand("Период ограничения без пояса: строка приёмки на границе месяца", "major", "ambiguity",
                   requirement_ids=["R-07", "R-14"])
    kept, dropped = lens_risk.postprocess([k1, k1_title, rule_vs_rule, period], "документ",
                                          acceptance_ids=["R-13", "R-14"])
    assert [c["title"] for c in kept] == [rule_vs_rule["title"], period["title"]]
    assert all("тестировщика" in d["reject_reason"] for d in dropped)


def test_cancel_during_operation_is_major_when_cancel_allowed():
    t = "Отмена объекта и перевод могут выполниться одновременно: исход не определён"
    kept, dropped = lens_risk.postprocess([_cand(t, "minor", "ops_risk", "risk")], "Получатель может отменить код.")
    assert _sev(t, kept, dropped) == "major"
    kept, dropped = lens_risk.postprocess([_cand(t, "minor", "ops_risk", "risk")], "Документ без этой темы.")
    assert _sev(t, kept, dropped) == "снято"


def test_rollback_is_always_minor():
    c = lens_risk.calibrate(_cand("Схема отката и выключения функции перевода не описана", "major", "ops_risk", "risk"))
    assert c["severity"] == "minor"


def test_key_event_minor_is_not_a_question():
    t = "Не определено, когда объект с суммой считается оплаченным и доступен ли он после отказа"
    kept, dropped = lens_risk.postprocess([_cand(t, "minor")], "документ")
    assert _sev(t, kept, dropped) == "major"
    t = "Не определено, когда объект считается оплаченным и доступен ли он снова после отказа или сбоя"
    kept, dropped = lens_risk.postprocess([_cand(t, "minor")], "документ без этой темы")
    assert _sev(t, kept, dropped) == "major", "слово «сбоя» не понижает ключевое событие"


def test_lens_output_limit_for_reasoning_models():
    assert lens_risk.MAX_OUTPUT_TOKENS == 32000


def test_candidate_without_evidence_dropped():
    kept, dropped = lens_risk.postprocess([_cand("Без цитаты", evidence=[])], "текст")
    assert not kept and dropped[0]["reject_reason"] == "нет цитаты-зацепки"


def test_unknown_requirement_ids_removed():
    kept, _ = lens_risk.postprocess([_cand("Риск", requirement_ids=["R-01", "Ф-9", "R-77"])], "текст", ["R-01", "R-02"])
    assert kept[0]["requirement_ids"] == ["R-01"]
    kept, _ = lens_risk.postprocess([_cand("Риск", requirement_ids=["ЛП-4"])], "текст")
    assert kept[0]["requirement_ids"] == ["ЛП-4"], "без нарезки ID не трогаем"


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


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("clean_*.json")), ids=lambda p: p.stem)
def test_saved_live_answers_on_clean_bases(path):
    """Сохранённые живые ответы на чистых базах корпуса после постобработки: 0 critical; major — не больше 2
    у sonnet (цель линзы) и не больше 4 у haiku (слабая модель, остаток отсеивает судья)."""
    case = path.stem.removeprefix("clean_").rsplit("_", 2)[0]
    doc = (ROOT / "evaluation" / "dev" / "corpus" / "cases" / f"{case}.base" / "source.md").read_text(encoding="utf-8")
    kept, _ = lens_risk.postprocess(json.loads(path.read_text(encoding="utf-8"))["candidates"], doc)
    sev = [c["severity"] for c in kept]
    limit = 2 if "sonnet" in path.stem else 4
    assert sev.count("critical") == 0 and sev.count("major") <= limit, sev
    if path.stem.endswith(("_v19",)):  # вторая волна: ≤ 1 замечания линзы на чистый документ
        assert len(kept) <= (1 if "sonnet" in path.stem else 2), [c["title"] for c in kept]


def test_run_uses_common_lens_and_postprocess(monkeypatch):
    """run(ctx): общий запуск линзы (подменён) → постобработка; снятые — в `dropped`."""
    import types

    calls = []
    fake = types.ModuleType("bcc_review.v2.stages.lens")

    def fake_run(ctx, name):
        calls.append(name)
        return {"candidates": [_cand("Ключевое событие не определено", "critical", requirement_ids=["R-01", "Ф-9"]),
                               _cand("Нет требований PCI DSS")]}

    fake.run = fake_run
    monkeypatch.setitem(sys.modules, "bcc_review.v2.stages.lens", fake)
    import bcc_review.v2.stages as stages_pkg
    monkeypatch.setattr(stages_pkg, "lens", fake, raising=False)
    ctx = types.SimpleNamespace(view={"lines": [{"n": 1, "text": "Клиент задаёт лимит.", "section": ""}]},
                                requirements=[{"id": "R-01", "kind": "functional"}])
    out = lens_risk.run(ctx)
    assert calls == ["risk"]
    assert [c["title"] for c in out["candidates"]] == ["Ключевое событие не определено"]
    assert out["candidates"][0]["requirement_ids"] == ["R-01"]
    assert out["dropped"][0]["reject_reason"].startswith("тема")


OPEN2 = FIXTURES / "open2"
OPEN2_KEY_EVENT = {"qr": r"оплачен", "grace": r"внес[её]н|внесени", "insurance": r"14\s+дн|отказ"}


def _open2_kept(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    doc_id = path.name.split(".")[0]
    doc = (ROOT / "evaluation" / "v2" / "open2" / doc_id / "source.md").read_text(encoding="utf-8")
    reqs = data.get("requirements") or []
    return doc_id, lens_risk.postprocess(data["candidates"], doc, [r["id"] for r in reqs],
                                         [r["id"] for r in reqs if r.get("kind") == "acceptance"])[0]


@pytest.mark.parametrize("path", sorted(OPEN2.glob("*.sonnet.json")) if OPEN2.exists() else [], ids=lambda p: p.stem)
def test_open2_sonnet_answers(path):
    """Новые ТЗ №18 (sonnet): ключевое событие в засеянных версиях находится; на чистых нет critical."""
    if not (ROOT / "evaluation" / "v2" / "open2").exists():
        pytest.skip("набор №18 не влит")
    doc_id, kept = _open2_kept(path)
    if doc_id.endswith("_clean"):
        assert not [c for c in kept if c["severity"] == "critical"], [c["title"] for c in kept]
        assert len(kept) <= 4
    elif doc_id in OPEN2_KEY_EVENT:
        rx = OPEN2_KEY_EVENT[doc_id]
        hits = [c for c in kept if lens_risk._is_key_event(c) and re.search(rx, c["title"] + c["problem"], re.I)]
        assert hits and hits[0]["severity"] in ("critical", "major"), [c["title"] for c in kept]
