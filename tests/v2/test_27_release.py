"""№27, исправление в релиз: существительное-деятель («получатель», «отправитель», «хранилище») не обещание действия.

Основа глагола «получ…» совпадала с «получателя»: строка экрана «… с именем получателя …» считалась обещанием
операции интерфейса, и ложный critical «обещано, но не описано» не понижался (чистое ТЗ №20 `qr_v2`, haiku).
"""
from __future__ import annotations

from bcc_review.v2.stages import consistency as C

DOC = ["Отправитель: экран подтверждения с именем получателя, суммой и картой списания.",
       "Методы сервиса описаны в конце документа."]
VIEW = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(DOC, 1)]}


def _missing(quotes):
    return {"title": "Операция не описана", "kind": "missing_element", "criterion": "set_complete",
            "severity": "critical", "requirement_ids": [], "problem": "п", "scenario": "с", "impact": "и",
            "recommendation": "р", "rewrite": "", "question": "", "blocks": "development",
            "evidence": [{"quote": q, "line": n} for q, n in quotes]}


def test_agent_noun_is_not_a_promise_verb():
    assert not C._PROMISE_SUBJ.search("экран подтверждения с именем получателя и картой")
    assert not C._PROMISE_SUBJ.search("клиент-отправитель и хранилище")
    assert C._PROMISE_SUBJ.search("Приложение получает номер договора")
    assert C._PROMISE_SUBJ.search("экран показывает сумму и отправляет заявку")


def test_screen_with_recipient_name_does_not_keep_false_critical():
    out = C.postprocess({"candidates": [_missing([("экран подтверждения с именем получателя", 1),
                                                  ("Методы сервиса описаны в конце документа.", 2)])]}, VIEW, [])
    assert out["candidates"][0]["severity"] != "critical"


def test_real_promise_keeps_critical():
    doc = ["Приложение получает номер договора через дочерний документ.", "Методы описаны в части B."]
    view = {"lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(doc, 1)]}
    out = C.postprocess({"candidates": [_missing([("получает номер договора через дочерний документ", 1)])]}, view, [])
    assert out["candidates"][0]["severity"] == "critical"
