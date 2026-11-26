"""Доказательство 4: отсутствие Prod URL само по себе не critical; правила и промпт читают одну версию TOML."""
from importlib import resources

from bcc_review.analysis.individual import build_prompt, review_individual
from bcc_review.criteria import load_criteria
from tests.p05.docfix import requirement
from tests.p05.helpers import FakeAsk, cands_of, doc_from_lines, issue

ROW = "| **Request URL** | Dev: `/alerts/saveLimit` . Prod: — |"


def _doc(*extra: str):
    return doc_from_lines(
        "# Уведомление",
        "## Часть B. REST API",
        "### Общие параметры",
        "| Поле | Значение |",
        "| :--- | :--- |",
        ROW,
        *extra,
    )


def test_missing_prod_url_is_minor_by_default():
    doc = _doc()
    res = review_individual(doc, [requirement(doc, "R1", "Request URL")])
    (cand,) = res["candidates"]
    assert cand["severity"] == "minor" and cand["kind"] == "placeholder"
    assert cand["severity_rule"] == "placeholder.release-field"
    assert cand["hints"][0]["quote"] == "Prod: —"
    assert "тестовом контуре" in cand["impact"]
    assert cand["blocks"] == []


def test_scenario_in_document_raises_to_major_but_not_critical():
    doc = _doc("## Критерии приемки", "Приёмочное тестирование проводится на Prod с реальной картой.")
    res = review_individual(doc, [requirement(doc, "R1", "Request URL")])
    (cand,) = res["candidates"]
    assert cand["severity"] == "major"
    assert cand["severity_rule"] == "placeholder.release-field.needed"


def test_model_critical_is_calibrated():
    doc = _doc()
    answer = {"results": [{"req_id": "R1", "checks": [issue(
        "complete", "Нет адреса Prod.", "Prod: —", kind="placeholder", impact="Нельзя выпустить.",
        question="Какой адрес Prod?", severity="critical", blocks="verify",
        blocked_decision="Куда направлять приёмочные запросы",
        scenario="Приёмка на промышленном контуре невозможна без адреса.")]}]}
    res = review_individual(doc, [requirement(doc, "R1", "Request URL")], ask=FakeAsk(answer))
    (cand,) = res["candidates"]
    assert cand["severity"] == "major"
    assert any("cap.release-field" in n for n in cand["calibration"])
    assert cand["source"] == "llm+rules"


def test_changed_rule_in_test_toml_is_used_by_rules_and_prompt(tmp_path):
    text = resources.files("bcc_review").joinpath("criteria.toml").read_text("utf-8")
    old = 'severity = "minor"\nwhy = "Значение нужно к выпуску, но не мешает реализовать и проверить логику на тестовом контуре."'
    assert old in text
    new = 'severity = "major"\nwhy = "ТЕСТ-ПРАВИЛО-42: адрес промышленного контура нужен уже для нагрузочного теста."'
    path = tmp_path / "criteria.toml"
    path.write_text(text.replace(old, new), "utf-8")

    default = load_criteria()
    crit = load_criteria(path)
    assert crit.fingerprint != default.fingerprint

    doc = _doc()
    reqs = [requirement(doc, "R1", "Request URL")]
    ask = FakeAsk({"results": []})
    res = review_individual(doc, reqs, ask=ask, criteria=crit)

    # правило
    (cand,) = cands_of(res, "R1")
    assert cand["severity"] == "major" and cand["severity_rule"] == "placeholder.release-field"
    assert cand["impact"].startswith("ТЕСТ-ПРАВИЛО-42")

    # подсказка модели собрана из той же версии
    _, payload, _ = ask.calls[0]
    assert payload["input"]["criteria_tag"] == crit.tag == res["meta"]["criteria_tag"]
    assert payload["input"]["criteria_fingerprint"] == crit.fingerprint
    assert "ТЕСТ-ПРАВИЛО-42" in payload["task"] and crit.tag in payload["task"]

    prompt = build_prompt(doc, reqs, criteria=crit)
    assert "ТЕСТ-ПРАВИЛО-42" in prompt["task"] and prompt["input"]["criteria_tag"] == crit.tag
    assert "ТЕСТ-ПРАВИЛО-42" not in build_prompt(doc, reqs)["task"]
