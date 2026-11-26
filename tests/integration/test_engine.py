"""Сквозные проверки движка на тестовых двойниках провайдера (без сети и ключей)."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bcc_review import contracts as C
from bcc_review import engine
from bcc_review.contracts import ProviderError

from .conftest import BCC, FIX, run, write_script

ROOT = Path(__file__).resolve().parents[2]


def by_kind(report, kind):
    return [f for f in report["findings"] if f["kind"] == kind]


# ---------------------------------------------------------------- базовый вертикальный срез
def test_mock_run_report_and_json_consistent(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert on_disk["summary"] == rep["summary"] and on_disk["run"]["run_id"] == rep["run"]["run_id"]
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Паспорт прогона" in md and rep["run"]["run_id"] in md or rep["document"]["id"] in md
    assert rep["run"]["mode"] == "mock" and rep["run"]["model"] == "mock-1"
    assert rep["document"]["id"] == C.sha256_file(BCC)


def test_passport_counts_real_calls(tmp_path, mock_script, monkeypatch):
    from bcc_review.runtime import mock as mock_mod

    calls = []
    orig = mock_mod.MockAdapter.invoke

    def spy(self, **kw):
        calls.append(1)
        return orig(self, **kw)

    monkeypatch.setattr(mock_mod.MockAdapter, "invoke", spy)
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert rep["run"]["calls"]["physical"] == len(calls) > 0
    assert sum(s["calls"] for s in rep["run"]["stages"]) == len(calls)


def test_conflict_with_two_bindings(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    conflicts = [f for f in by_kind(rep, "conflict") if f["source"] != "rules" or f.get("witness")]
    llm = [f for f in conflicts if "Ф-4" in f["title"]]
    assert llm, [f["title"] for f in rep["findings"]]
    f = llm[0]
    assert f["status"] == "confirmed" and f["severity"] == "critical"
    w = f["witness"]
    assert w["evidence_a"]["block_id"] != w["evidence_b"]["block_id"]
    blocks = {b["id"]: b["text"] for b in rep["document"]["blocks"]}
    for ev in (w["evidence_a"], w["evidence_b"]):
        assert blocks[ev["block_id"]][ev["start"]:ev["end"]] == ev["quote"]
    assert f["anchor_status"] == "supported" and f["meaning_status"] == "confirmed"
    assert rep["verdict"]["development"]["status"] == "not_ready"
    assert f["id"] in rep["verdict"]["development"]["finding_ids"]


def test_missing_promised_contract_confirmed(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    om = [f for f in by_kind(rep, "omission") if "метод чтения" in f["title"].lower()]
    assert om and om[0]["status"] == "confirmed"
    assert any(e["quote"].startswith("Приложение читает и сохраняет настройки") for e in om[0]["evidence"])


def test_fabricated_quote_rejected_not_reported(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert not [f for f in rep["findings"] if "Выдуманная" in f["title"]]
    assert any("не найдена" in r["reason"] for r in rep["rejected"])
    audit = rep["run"]["evidence_audit"]
    assert audit["rejected"] >= 1 and audit["checked"] == audit["confirmed"] + audit["ambiguous"] + audit["rejected"]


def test_critic_rejects_false_positive(tmp_path, mock_script):
    mock_script["verify_meaning"] = {"__verdicts__": "confirmed", "reject": ["метод чтения"]}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert not [f for f in rep["findings"] if "метод чтения" in f["title"].lower() and f["source"] == "llm"]
    assert any(r["stage"] == "verify_meaning" for r in rep["rejected"])


def test_quote_and_meaning_are_separate_results(tmp_path, mock_script):
    mock_script["verify_meaning"] = {"__verdicts__": "uncertain"}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    f = [f for f in by_kind(rep, "conflict") if "Ф-4" in f["title"]][0]
    assert f["anchor_status"] == "supported" and f["meaning_status"] == "uncertain"
    assert f["status"] == "needs_review"
    assert rep["verdict"]["development"]["status"] in ("unknown", "not_ready")


def test_correct_rule_without_defect(tmp_path):
    pytest.importorskip("bcc_review.runtime.fallback.rules")
    clean = tmp_path / "clean.md"
    clean.write_text(
        "# Сервис уведомлений\n\n## Функциональные требования\n"
        "* **ФТ-1.** Система должна отправлять push не позднее 60 секунд после события проведения покупки.\n\n"
        "## Критерии приемки\n\n| ID | Исходные условия | Действие | Ожидаемый результат |\n| :--- | :--- | :--- | :--- |\n"
        "| ФТ-1 | Событие проведения покупки получено в 12:00:00 UTC+5 | Подождать 60 секунд | Push отправлен не позднее 12:01:00 UTC+5 |\n",
        encoding="utf-8")
    script = {"individual": {"requirements": [{"req_id": "R-01", "checks": [
        {"criterion": c, "status": "pass", "reason": "выполнено"} for c in C.INDIVIDUAL_CRITERIA], "issues": []},
        {"req_id": "R-02", "checks": [{"criterion": c, "status": "pass", "reason": "выполнено"}
                                      for c in C.INDIVIDUAL_CRITERIA], "issues": []}]},
              "verify_meaning": {"__verdicts__": "confirmed"}}
    rep = run(tmp_path, clean, provider="mock", mock_script=write_script(tmp_path, script))
    assert rep["findings"] == [], [f["title"] for f in rep["findings"]]
    assert rep["run"]["status"] == "complete", rep["run"]["status_reasons"]
    assert rep["verdict"]["development"]["status"] == "ready"
    assert all(r["review_status"] == "reviewed" for r in rep["requirements"])


# ---------------------------------------------------------------- неполные прогоны
def test_truncated_provider_response_not_ready(tmp_path, mock_script):
    mock_script["cross"] = {"error": "truncated", "message": "ответ усечён"}
    mock_script["individual"] = {"requirements": []}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert rep["run"]["status"] == "partial"
    assert "cross" in rep["run"]["incomplete_stages"]
    assert any("truncated" in r for r in rep["run"]["status_reasons"])
    for t in ("development", "testing"):
        assert rep["verdict"][t]["status"] != "ready"


def test_partially_read_document_not_ready(tmp_path):
    bad = tmp_path / "broken.md"
    bad.write_bytes("# ТЗ\n\n## Функциональные требования\n* **Ф-1.** Система должна хранить порог.\n".encode("utf-8")
                    + b"\n\xff\xfe\xfa broken tail\n")
    script = {"individual": {"requirements": [{"req_id": "R-01", "checks": [
        {"criterion": c, "status": "pass", "reason": "ok"} for c in C.INDIVIDUAL_CRITERIA], "issues": []}]}}
    rep = run(tmp_path, bad, provider="mock", mock_script=write_script(tmp_path, script))
    assert any(w["code"] in C.PARTIAL_READ_CODES for w in rep["document"]["warnings"])
    assert rep["run"]["status"] == "partial"
    assert rep["verdict"]["development"]["status"] == "unknown"
    assert rep["verdict"]["testing"]["status"] == "unknown"


def test_model_unavailable_gives_rules_only(tmp_path):
    rep = run(tmp_path, BCC, provider="anthropic")  # ключа нет
    assert rep["run"]["mode"] == "rules_only" and rep["run"]["status"] == "partial"
    assert rep["run"]["model"] is None and rep["run"]["calls"]["physical"] == 0
    assert any("not_configured" in r or "ANTHROPIC_API_KEY" in r for r in rep["run"]["status_reasons"])
    assert {"individual", "cross"} <= set(rep["run"]["incomplete_stages"])
    for r in rep["requirements"]:
        assert r["review_status"] != "reviewed" and r["review_reason"]
    assert rep["verdict"]["development"]["status"] != "ready"


class LiveLikeAdapter:
    """Двойник «живого» провайдера: тот же интерфейс, что у №11, с фактической моделью в ответе."""
    name = "anthropic"
    params = {"live_like": True}

    def __init__(self, *a, **k):
        from bcc_review.runtime.mock import MockAdapter
        self._m = MockAdapter(json.loads((FIX / "mock_bcc.json").read_text(encoding="utf-8")), model="claude-opus-5-5")

    def invoke(self, **kw):
        return self._m.invoke(**kw)


def test_live_like_provider_gives_rules_plus_llm(tmp_path, monkeypatch):
    from bcc_review.runtime import modules

    monkeypatch.setitem(modules.SLOTS, "anthropic", ("tests.nonexistent:X", "tests.integration.test_engine:LiveLikeAdapter"))
    rep = run(tmp_path, BCC, provider="anthropic")
    assert rep["run"]["mode"] == "rules_plus_llm"
    assert rep["run"]["model"] == "claude-opus-5-5" and rep["run"]["requested_model"] == "claude-opus-5-5"
    assert rep["run"]["calls"]["physical"] > 0
    ok_llm = [s for s in rep["run"]["stages"] if s["name"] in ("cross", "verify_meaning") and s["status"] == "ok"]
    assert len(ok_llm) == 2


# ---------------------------------------------------------------- бюджет, повторы, кэш
def test_retry_after_respected(tmp_path, mock_script, sleeps):
    good = mock_script["cross"]
    mock_script["cross"] = [{"error": "rate_limit", "retry_after_s": 7}, good]
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert 7 in sleeps
    cross = next(s for s in rep["run"]["stages"] if s["name"] == "cross")
    assert cross["status"] == "ok" and cross["retries"] == 1 and cross["calls"] == 2
    assert rep["run"]["calls"]["retries"] >= 1


def test_retry_after_beyond_budget_stops(tmp_path, mock_script, sleeps):
    mock_script["individual"] = {"error": "overloaded", "retry_after_s": 10_000}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script), max_seconds=600)
    assert 10_000 not in sleeps
    assert rep["run"]["budget"]["exhausted"] is True
    assert rep["run"]["status"] == "partial"


def test_finite_retries(tmp_path, mock_script, sleeps):
    mock_script["cross"] = {"error": "server"}
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script), max_retries=2)
    cross = next(s for s in rep["run"]["stages"] if s["name"] == "cross")
    assert cross["status"] == "failed" and cross["calls"] == 3


def test_call_budget_exhausted_partial_report(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script), max_calls=2)
    assert rep["run"]["calls"]["physical"] == 2
    assert rep["run"]["budget"]["exhausted"] and "вызовов" in rep["run"]["budget"]["reason"]
    assert rep["run"]["status"] == "partial" and rep["run"]["incomplete_stages"]
    C.validate(rep)


def test_cache_hit_on_rerun_and_miss_on_model_change(tmp_path, mock_script):
    script = write_script(tmp_path, mock_script)
    first = run(tmp_path, BCC, "r1.md", provider="mock", mock_script=script)
    second = run(tmp_path, BCC, "r2.md", provider="mock", mock_script=script)
    assert first["run"]["calls"]["physical"] > 0
    assert second["run"]["calls"]["physical"] == 0
    assert second["run"]["calls"]["cache_hits"] == first["run"]["calls"]["physical"]
    assert [f["title"] for f in second["findings"]] == [f["title"] for f in first["findings"]]
    third = run(tmp_path, BCC, "r3.md", provider="mock", mock_script=script, model="mock-2")
    assert third["run"]["calls"]["physical"] > 0


# ---------------------------------------------------------------- решение аналитика и редакции
def test_analyst_decision_closes_conflict_keeps_independent_defect(tmp_path, bcc_copy, mock_script):
    script1 = write_script(tmp_path, mock_script, "s1.json")
    r1 = run(tmp_path, bcc_copy, "r1.md", provider="mock", mock_script=script1)
    conflict = [f for f in by_kind(r1, "conflict") if "Ф-4" in f["title"]][0]
    omission = [f for f in by_kind(r1, "omission") if "метод чтения" in f["title"].lower()][0]
    original_sha = C.sha256_file(bcc_copy)

    answers = tmp_path / "answers.md"
    answers.write_text(
        f"source_sha256: {r1['document']['id']}\n\n## Q-001\n"
        "Ответ: смена порога не сбрасывает лимит, второй push в месяце не отправляется.\n"
        "Правка: «следующее достижение вызывает push независимо от истории предыдущей настройки» → "
        "«следующее достижение вызывает push, если в этом календарном месяце push ещё не отправлялся»\n",
        encoding="utf-8")
    script2 = copy.deepcopy(mock_script)
    script2["cross"]["conflicts"] = []  # в новой редакции конфликта нет
    r2 = run(tmp_path, bcc_copy, "r2.md", provider="mock", mock_script=write_script(tmp_path, script2, "s2.json"),
             answers_path=str(answers), compare_path=str(tmp_path / "r1.json"))

    assert C.sha256_file(bcc_copy) == original_sha                     # исходник сохранён
    assert r2["run"]["revision_of"] == original_sha                     # прочитана именно редакция B
    assert r2["document"]["id"] != original_sha
    assert any("если в этом календарном месяце push ещё не отправлялся" in b["text"] for b in r2["document"]["blocks"])
    assert r2["decisions"] and r2["decisions"][0]["edits"]
    diff = r2["diff"]
    resolved = [e for e in diff["resolved"] if conflict["id"] in e["old_ids"]]
    assert resolved, diff
    assert any("ещё не отправлялся" in ev["quote"] for ev in resolved[0]["evidence"])  # новое доказательство
    assert any(omission["id"] in e["old_ids"] for e in diff["persisting"])             # независимый дефект остался
    assert not any(omission["id"] in e["old_ids"] for e in diff["resolved"])
    assert diff["impacted_req_ids"]


def test_moving_lines_creates_no_new_defect(tmp_path, bcc_copy, mock_script):
    script = write_script(tmp_path, mock_script)
    r1 = run(tmp_path, bcc_copy, "r1.md", provider="mock", mock_script=script)
    moved = tmp_path / "moved.md"
    text = bcc_copy.read_text(encoding="utf-8")
    moved.write_text("\n\n\n" + text.replace("### Цели\n", "\n\n### Цели\n"), encoding="utf-8")
    r2 = run(tmp_path, moved, "r2.md", provider="mock", mock_script=script, compare_path=str(tmp_path / "r1.json"))
    diff = r2["diff"]
    assert diff["introduced"] == [] and diff["resolved"] == [], diff
    assert len(diff["persisting"]) == len(r1["findings"])


def test_unrepeated_finding_on_unchanged_text_is_unassessed(tmp_path, bcc_copy, mock_script):
    r1 = run(tmp_path, bcc_copy, "r1.md", provider="mock", mock_script=write_script(tmp_path, mock_script, "a.json"))
    s2 = copy.deepcopy(mock_script)
    s2["cross"] = {"error": "truncated"}
    r2 = run(tmp_path, bcc_copy, "r2.md", provider="mock", mock_script=write_script(tmp_path, s2, "b.json"),
             compare_path=str(tmp_path / "r1.json"), use_cache=False)
    llm_ids = {f["id"] for f in r1["findings"] if f["source"] == "llm"}
    assert llm_ids and not any(set(e["old_ids"]) & llm_ids for e in r2["diff"]["resolved"])
    assert any(set(e["old_ids"]) & llm_ids for e in r2["diff"]["unassessed"])


def test_answers_for_other_revision_ignored(tmp_path, bcc_copy, mock_script):
    answers = tmp_path / "answers.md"
    answers.write_text("source_sha256: " + "0" * 64 + "\n\n## Q-001\nОтвет: да\nПравка: «Ф-1» → «Ф-01»\n", encoding="utf-8")
    rep = run(tmp_path, bcc_copy, provider="mock", mock_script=write_script(tmp_path, mock_script),
              answers_path=str(answers))
    assert rep["document"]["id"] == C.sha256_file(bcc_copy)
    assert any("другой редакции" in w["message"] for w in rep["warnings"] if isinstance(w, dict))


# ---------------------------------------------------------------- verify
def test_verify_ok_and_tamper_detection(tmp_path, mock_script):
    from bcc_review.cli import main

    run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    rj = tmp_path / "report.json"
    assert main(["verify", str(rj), str(BCC)]) == C.EXIT_OK

    rep = json.loads(rj.read_text(encoding="utf-8"))
    f = next(f for f in rep["findings"] if f["evidence"])
    f["evidence"][0]["quote"] = f["evidence"][0]["quote"] + " (изменено)"
    bad_quote = tmp_path / "bad_quote.json"
    bad_quote.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    assert main(["verify", str(bad_quote), str(BCC)]) == C.EXIT_VERIFY_FAILED

    rep = json.loads(rj.read_text(encoding="utf-8"))
    rep["summary"]["findings"] += 1
    bad_count = tmp_path / "bad_count.json"
    bad_count.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    assert main(["verify", str(bad_count), str(BCC)]) == C.EXIT_VERIFY_FAILED

    changed_src = tmp_path / "changed.md"
    changed_src.write_text(BCC.read_text(encoding="utf-8").replace("Ф-3.", "Ф-33."), encoding="utf-8")
    assert main(["verify", str(rj), str(changed_src)]) == C.EXIT_VERIFY_FAILED


# ---------------------------------------------------------------- объединение по первопричине
def _cand(title, quote, block, obj, cond="", outcomes=(), kind="ambiguity", source="llm"):
    return {"cid": title, "scope": "requirement", "kind": kind, "criterion": "unambiguous", "severity": "major",
            "title": title, "impact": "i", "req_ids": ["R-01"], "hints": [],
            "evidence": [{"block_id": block, "start": quote[0], "end": quote[1], "quote": "x"}],
            "anchor_status": "supported", "meaning_status": "confirmed", "witness": None, "source": source,
            "cause": {"object": obj, "condition": cond, "outcomes": list(outcomes)}}


def test_merge_same_root_cause_and_keep_lookalikes_apart():
    from bcc_review.runtime.merge import merge_candidates

    a = _cand("Не указан часовой пояс месяца покупки", (0, 20), "b1", "часовой пояс месяца покупки", source="rules")
    b = _cand("Месяц покупки без часового пояса", (5, 25), "b1", "месяц покупки часовой пояс")
    c = _cand("Не указан часовой пояс лимита push", (0, 20), "b2", "часовой пояс календарного месяца лимита push")
    merged = merge_candidates([a, b, c])
    assert len(merged) == 2
    assert merged[0]["source"] == "mixed" and "Месяц покупки без часового пояса" in merged[0]["merged_from"]
    # одинаковая первопричина в разных местах — одно замечание с несколькими местами
    d = _cand("Нет метода чтения", (0, 5), "b7", "метод чтения настроек", "открытие экрана", ["нет метода"], kind="omission")
    e = _cand("Нет чтения порога", (0, 5), "b9", "метод чтения настроек", "открытие экрана", ["нет метода"], kind="omission")
    merged = merge_candidates([d, e])
    assert len(merged) == 1 and len(merged[0]["evidence"]) == 2


def test_critical_without_business_impact_downgraded(tmp_path, mock_script):
    mock_script["cross"]["conflicts"][0]["blocked_decision"] = ""
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    f = [f for f in by_kind(rep, "conflict") if "Ф-4" in f["title"]][0]
    assert f["severity"] == "major" and any("понижено" in n for n in f["notes"])


# ---------------------------------------------------------------- CLI, трасса, контекст
def test_cli_exit_codes_and_routing(tmp_path, mock_script):
    from bcc_review.cli import main

    script = write_script(tmp_path, mock_script)
    out = tmp_path / "cli.md"
    assert main([str(BCC), str(out), "--provider", "mock", "--mock-script", script, "--cache-dir",
                 str(tmp_path / "c"), "-q"]) == C.EXIT_OK
    assert main([str(BCC), str(out), "--provider", "mock", "--mock-script", script, "--cache-dir",
                 str(tmp_path / "c"), "-q", "--fail-on", "blocker"]) == C.EXIT_BLOCKER
    assert main(["review", str(BCC), str(out), "--offline-lint", "-q", "--fail-on", "partial"]) == C.EXIT_PARTIAL
    assert main([str(tmp_path / "nope.md"), str(out)]) == C.EXIT_USAGE
    assert main([str(BCC)]) == C.EXIT_USAGE


def test_cli_module_entry_point(tmp_path):
    out = tmp_path / "e.md"
    res = subprocess.run([sys.executable, "-m", "bcc_review", str(BCC), str(out), "--offline-lint"],
                         capture_output=True, text=True, encoding="utf-8", cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert out.exists() and out.with_suffix(".json").exists()
    assert "Отчёт:" in res.stdout


def test_trace_is_safe(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script))
    trace = (tmp_path / "report.md.artifacts" / "trace.jsonl").read_text(encoding="utf-8")
    events = [json.loads(x) for x in trace.splitlines()]
    assert {"run_start", "call_ok", "stage_end", "run_end"} <= {e["event"] for e in events}
    assert "Держатель активной карты" not in trace and "максимум один такой push" not in trace
    stages_dir = tmp_path / "report.md.artifacts" / "stages"
    assert any(p.name.endswith("inventory.json") for p in stages_dir.iterdir())


def test_large_document_uses_index_and_cross_links(tmp_path, mock_script):
    from bcc_review.runtime.context import ContextBuilder
    from bcc_review.runtime.fallback.inventory import build_inventory
    from bcc_review.runtime.fallback.text_reader import read_text

    doc = read_text(BCC)
    reqs = build_inventory(doc)["requirements"]
    ctx = ContextBuilder(doc, reqs, full_context_chars=500)
    text, policy = ctx.render({"mode": "auto", "block_ids": ["b0034"]})  # интеграция → дочерний документ
    assert policy == "index+linked"
    assert "ИНДЕКС ВСЕХ ТРЕБОВАНИЙ" in text and all(r["id"] in text for r in reqs)
    assert "[b0064]" in text  # блок части B, связанный именем документа в «ёлочках»
    small = ContextBuilder(doc, reqs)
    full, pol = small.render({"mode": "auto", "block_ids": ["b0034"]})
    assert pol == "full" and "[b0025]" in full and "[b0098]" in full  # части A и B вместе


# ---------------------------------------------------------------- PDF и экспорты
def test_pdf_input_end_to_end(tmp_path, mock_script):
    from bcc_review.cli import main

    pdf = FIX / "bcc_requirements.pdf"
    rep = run(tmp_path, pdf, provider="mock", mock_script=write_script(tmp_path, mock_script))
    assert rep["document"]["format"] == "pdf" and rep["document"]["id"] == C.sha256_file(pdf)
    f = [f for f in by_kind(rep, "conflict") if "Ф-4" in f["title"]][0]
    assert f["status"] == "confirmed"
    assert all(b["loc"].get("page", 0) >= 1 for b in rep["document"]["blocks"])
    assert main(["verify", str(tmp_path / "report.json"), str(pdf)]) == C.EXIT_OK


def test_exports_html_and_jira(tmp_path, mock_script):
    rep = run(tmp_path, BCC, provider="mock", mock_script=write_script(tmp_path, mock_script), exports=("html", "jira", "pdf"))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert 'id="finding-F-001"' in html and "<mark" in html
    assert (tmp_path / "report.jira.csv").exists()
    assert any("экспорт pdf недоступен" in w["message"] for w in rep["warnings"] if isinstance(w, dict))


# ---------------------------------------------------------------- факты №04 → №06 через движок
def fake_inventory(document, ask=None):
    from bcc_review.runtime.fallback.inventory import build_inventory

    out = build_inventory(document, None)
    out["fact_hints"] = [{"subject": "порог", "field": "единица", "direction": None, "type": "money", "value": "тенге",
                          "unit": "KZT", "range": None, "hints": [{"block_id": None, "quote": "порог в тенге"}]},
                         {"subject": "сумма покупки", "field": "единица", "direction": None, "type": "money",
                          "value": "тиын", "unit": "KZT/100", "range": None,
                          "hints": [{"block_id": None, "quote": "сумму покупки в тиынах"}]}]
    return out


def fake_reconcile(document, fact_hints):
    facts = [{"id": f"FACT-T{i}", "subject": h["subject"], "field": h["field"], "value": h["value"], "unit": h["unit"],
              "evidence": []} for i, h in enumerate(fact_hints, 1)]
    cand = {"scope": "set", "kind": "incomplete", "criterion": "set_consistent", "severity": "major",
            "title": "Сумма покупки в тиынах, порог в тенге: нет правила пересчёта", "impact": "Ошибка сравнения с порогом",
            "req_ids": ["R-12"], "hints": [h["hints"][0] for h in fact_hints], "source": "rules", "stage": "facts",
            "cause": {"object": "единицы суммы и порога", "condition": "сравнение с порогом", "outcomes": []}}
    return {"facts": facts, "candidates": [cand]}


def test_fact_hints_flow_through_reconcile(tmp_path, monkeypatch):
    from bcc_review.runtime import modules

    monkeypatch.setitem(modules.SLOTS, "build_inventory", ("tests.integration.test_engine:fake_inventory", None))
    monkeypatch.setitem(modules.SLOTS, "reconcile_facts", ("tests.integration.test_engine:fake_reconcile", None))
    rep = run(tmp_path, BCC, offline_lint=True)
    assert {"FACT-T1", "FACT-T2"} <= {f["id"] for f in rep["facts"]}
    units = [f for f in rep["findings"] if "тиын" in f["title"].lower() or "тиын" in " ".join(e["quote"] for e in f["evidence"])]
    assert units and units[0]["anchor_status"] == "supported"
    assert rep["run"]["modules"]["reconcile_facts"].startswith("team:")
