"""Валидный ответ этапа individual через настоящий Asker движка: два запуска, один кэш.

Участвуют реальные runtime.asker.Asker, runtime.mock.MockAdapter, runtime.core.Cache/Budget/StageStats/Tracer
и runtime.context.ContextBuilder из bcc/integration. Внешний ответ — сценарий MockAdapter в схеме №05.
"""
import json

import pytest

from bcc_review.analysis.individual import response_schema, review_individual
from tests.p05.docfix import load_fixture, requirement
from tests.p05.helpers import checks_of, issue, passes

asker_mod = pytest.importorskip("bcc_review.runtime.asker")
core = pytest.importorskip("bcc_review.runtime.core")
context_mod = pytest.importorskip("bcc_review.runtime.context")
mock_mod = pytest.importorskip("bcc_review.runtime.mock")


def _script():
    """Ответ в схеме №05: ПР-1 — дефект с буквальной цитатой, ПР-2 (кнопка) — содержательный pass."""
    pr1 = {"req_id": "ПР-1", "checks": [issue(
        "verifiable", "Срок подтверждения перевода в области пункта не определён.", "в установленный срок",
        kind="unverifiable", condition="Код отправлен, клиент вводит его через 200 секунд.",
        outcomes=["перевод проходит", "перевод отклоняется"], impact="Тест не может выбрать ожидаемый исход.",
        fix="Клиент подтверждает перевод не позднее <уточнить у владельца: N с> после отправки кода.",
        question="Какой срок подтверждения перевода?", blocks="both",
        blocked_decision="Тайм-аут подтверждения перевода и ожидаемый исход приёмочного теста",
        scenario="Код отправлен, ввод через 200 секунд: успех или отказ?", root_cause="transfer_confirm_timeout")]}
    pr2 = passes("ПР-2", {"verifiable": "Наблюдаемо: нажатие кнопки отправляет одноразовый код на номер телефона клиента."})
    return {"individual": {"results": [pr1, pr2]}}


def _asker(doc, reqs, cache_dir):
    adapter = mock_mod.MockAdapter(_script())
    ctx = context_mod.ContextBuilder(doc, reqs)
    stats = core.StageStats()
    asker = asker_mod.Asker(adapter=adapter, provider="mock", model="mock-1", budget=core.Budget(40, 1500.0),
                            cache=core.Cache(cache_dir), stats=stats, tracer=core.Tracer(None, "p05"), context=ctx,
                            max_retries=0, sleep=lambda s: None)
    return asker, adapter, stats


def test_valid_answer_through_real_asker_twice_with_one_cache(tmp_path):
    doc = load_fixture("transfer_other_product.md")
    reqs = [requirement(doc, "ПР-1", "ПР-1.", "ПР-1"), requirement(doc, "ПР-2", "ПР-2.", "ПР-2")]
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_script()["individual"], response_schema())

    runs = []
    for _ in range(2):
        asker, adapter, stats = _asker(doc, reqs, tmp_path / "cache")
        res = review_individual(doc, reqs, ask=asker)
        runs.append((res, adapter.calls, stats.totals()))

    (first, calls1, tot1), (second, calls2, tot2) = runs
    assert calls1 == ["individual#1"] and tot1["physical"] == 1 and tot1["cache_hits"] == 0
    assert calls2 == [] and tot2["physical"] == 0 and tot2["cache_hits"] == 1
    assert first["failed"] == second["failed"] == {}
    assert json.dumps(first["checks"], ensure_ascii=False) == json.dumps(second["checks"], ensure_ascii=False)
    assert [c["ref"] for c in first["candidates"]] == [c["ref"] for c in second["candidates"]]
    for res in (first, second):
        assert {c["source"] for c in checks_of(res, "ПР-2").values()} == {"llm"}  # модель оценила все 9 критериев
        assert checks_of(res, "ПР-1")["verifiable"]["source"] == "llm"           # у ПР-1 — один критерий
        assert checks_of(res, "ПР-1")["verifiable"]["status"] == "issue"
        assert checks_of(res, "ПР-2")["verifiable"]["status"] == "pass"
