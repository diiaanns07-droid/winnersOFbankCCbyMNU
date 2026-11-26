"""Происхождение замечания: подпись ``source / stage`` по производящему этапу.

Три независимых пути (происхождение / кэш / физические вызовы / подпись после правки):

* чистое правило — тип ``limit`` у getTransferLimit (ответ, string) и setTransferLimit (запрос, integer),
  transfer_limit.base, ``--offline-lint``: сверка фактов №06 (``origin="facts"``) в этапах cross и facts /
  попаданий в кэш 0 / вызовов 0 / ``rules / cross+facts`` (на 82c0904: ``llm / ""``);
* ответ модели из тёплого кэша — конфликт Ф-3 ↔ Ф-4, второй прогон mock с тем же кэшем: модель в этапе
  cross / попаданий 8 (cross: 1) / вызовов 0 / ``llm / cross`` (так же и на 82c0904);
* смешанный вывод — «Чтение настроек обещано, но метод чтения не описан»: правило C-019 + ответ модели
  cross C-028 / попаданий 8 / вызовов 0 / ``mixed / rules+cross`` (на 82c0904: ``mixed / rules``).

Подпись собирает ``engine.build_findings``. Без правки ``tests/p07/fixes/engine_provenance.diff`` движок
подставляет ``c.get("source", "llm")`` и ``c.get("stage", "")``: кандидаты №06 несут ``origin``, а не
``source`` и ``stage``, поэтому правило получает «llm» и пустой этап; у смешанного замечания этап берётся
только у первого кандидата («rules»). Проверки подписи отмечены ``xfail(strict=True)``, пока движок не
исправлен; признак исправления берётся из поведения ``build_findings``, а не из текста кода.

Модель не вызывается: офлайн-режим и тестовый двойник ``mock`` со сценарием из tests/integration.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from bcc_review import engine
from bcc_review.contracts import RunOptions
from bcc_review.verification import verify_report

ROOT = Path(__file__).resolve().parents[2]
LIMIT_CASE = ROOT / "evaluation" / "dev" / "corpus" / "cases" / "transfer_limit.base" / "source.md"
BCC = ROOT / "tests" / "integration" / "fixtures" / "bcc_requirements.md"
MOCK_SCRIPT = ROOT / "tests" / "integration" / "fixtures" / "mock_bcc.json"
RELEASE = ROOT / "release"
# резервные модули этапов, под схемы которых написан сценарий mock_bcc.json (как в tests/integration)
FALLBACK = ("build_inventory,review_individual,review_set,reconcile_facts,load_criteria,resolve_hint,resolve_candidate,"
            "build_questions,parse_answers,propose_patch,write_revision,compare_reports,read_pdf")
ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_MODEL",
            "GEMINI_MODEL", "BCC_FORCE_FALLBACK", "BCC_CACHE_DIR")
PROVENANCE_WARNINGS = ("finding_source_without_model", "finding_stage_without_model")


# ---------------------------------------------------------------- признак правки движка
class _EngineStub:
    """Минимум, который ``Engine.build_findings`` берёт у движка."""

    criteria_codes: set = set()

    def __init__(self, asked: bool) -> None:
        self.asker = object() if asked else None

    def mark(self, *args: Any, **kwargs: Any) -> None:
        pass


def _verified(cid: str, *, block: str = "b1", start: int = 0, **marks: Any) -> dict:
    return {"cid": cid, "scope": "set", "kind": "ambiguity", "criterion": "set_consistent", "severity": "minor",
            "title": f"кандидат {cid}", "impact": "i", "req_ids": [], "hints": [],
            "evidence": [{"block_id": block, "start": start, "end": start + 5, "quote": "xxxxx"}],
            "anchor_status": "supported", "meaning_status": "unchecked", "witness": None, **marks}


def _label(items: list[dict], *, asked: bool = False) -> tuple[str, str]:
    findings = engine.Engine.build_findings(_EngineStub(asked), items, [])
    assert len(findings) == 1, [f["title"] for f in findings]
    return findings[0]["source"], findings[0]["stage"]


def _engine_labels_by_producer() -> bool:
    return _label([_verified("C-1", origin="facts", stage="cross")])[0] == "rules"


ENGINE_FIXED = _engine_labels_by_producer()
needs_engine_fix = pytest.mark.xfail(
    not ENGINE_FIXED, strict=True,
    reason="подпись Finding собирает engine.build_findings: нужна правка tests/p07/fixes/engine_provenance.diff")


# ---------------------------------------------------------------- прогоны
def _run(src: Path, out: Path, **opts: Any) -> dict:
    base = {"cache_dir": str(out.parent / "cache"), "artifacts_dir": str(out.with_suffix(".artifacts"))}
    base.update(opts)
    return engine.run_review(src, out, options=RunOptions.coerce(base))


@pytest.fixture(scope="module")
def isolated():
    with pytest.MonkeyPatch.context() as mp:
        for key in ENV_KEYS:
            mp.delenv(key, raising=False)
        mp.setattr(engine, "load_dotenv", lambda *a, **k: None)
        mp.setattr(engine, "SLEEP", lambda s: None)
        yield mp


@pytest.fixture(scope="module")
def offline_limit(isolated, tmp_path_factory) -> dict:
    """Чистое правило: transfer_limit.base без модели."""
    out = tmp_path_factory.mktemp("offline") / "report.md"
    report = _run(LIMIT_CASE, out, offline_lint=True)
    return {"report": report, "json": out.with_suffix(".json"), "artifacts": out.with_suffix(".artifacts")}


@pytest.fixture(scope="module")
def mock_runs(isolated, tmp_path_factory) -> dict:
    """Один и тот же сценарий модели дважды с общим кэшем: холодный и тёплый прогон."""
    isolated.setenv("BCC_FORCE_FALLBACK", FALLBACK)
    tmp = tmp_path_factory.mktemp("mock")
    runs = {}
    for name in ("cold", "warm"):
        out = tmp / f"{name}.md"
        report = _run(BCC, out, provider="mock", mock_script=str(MOCK_SCRIPT))
        runs[name] = {"report": report, "json": out.with_suffix(".json")}
    isolated.delenv("BCC_FORCE_FALLBACK")
    return runs


def _limit_finding(report: dict) -> dict:
    found = [f for f in report["findings"] if f["title"].startswith("Тип «limit» различается")]
    assert len(found) == 1, [f["title"] for f in report["findings"]]
    return found[0]


def _one(report: dict, fragment: str) -> dict:
    found = [f for f in report["findings"] if fragment in f["title"]]
    assert len(found) == 1, (fragment, [f["title"] for f in report["findings"]])
    return found[0]


def _stage(report: dict, name: str) -> dict:
    return next(s for s in report["run"]["stages"] if s["name"] == name)


def _provenance_warnings(result: dict) -> list[dict]:
    return [w for w in result["warnings"] if w["code"] in PROVENANCE_WARNINGS]


# ---------------------------------------------------------------- 1. трасса записи limit
def test_trace_limit_candidate_reaches_engine_without_source(offline_limit):
    """Кандидат → этап → Finding: откуда берётся «llm» у правила при нуле вызовов модели."""
    report = offline_limit["report"]
    run = report["run"]
    assert run["mode"] == "rules_only" and run["model"] is None
    assert run["calls"]["physical"] == 0 and run["calls"]["cache_hits"] == 0
    for name in ("cross", "facts"):
        assert _stage(report, name)["calls"] == 0 and _stage(report, name)["cache_hits"] == 0

    # этап cross сохранил кандидата №06 как есть: отметка производителя — origin, source и stage нет
    cross_out = json.loads((offline_limit["artifacts"] / "stages" / "04-cross.json").read_text(encoding="utf-8"))
    raw = [c for c in cross_out["candidates"] if c["title"].startswith("Тип «limit» различается")]
    assert len(raw) == 1
    assert raw[0]["origin"] == "facts" and "source" not in raw[0] and "stage" not in raw[0]

    # тот же расчёт №06 вызывается движком ещё раз в этапе facts (C-facts-*), оба кандидата сводятся в одно замечание
    finding = _limit_finding(report)
    members = finding["merged_from"]
    assert len(members) == 2 and members[0].startswith("C-0") and members[1].startswith("C-facts-")
    # смысл не проверялся (rules_only), статус от подписи не зависит
    assert finding["meaning_status"] == "unchecked" and finding["status"] == "needs_review"


@needs_engine_fix
def test_rule_path_signed_rules_by_producing_stages(offline_limit):
    finding = _limit_finding(offline_limit["report"])
    assert (finding["source"], finding["stage"]) == ("rules", "cross+facts")
    # в прогоне без единого ответа модели ни одно замечание не подписано моделью
    assert {f["source"] for f in offline_limit["report"]["findings"]} == {"rules"}
    assert all(f["stage"] for f in offline_limit["report"]["findings"])
    result = verify_report(offline_limit["json"], LIMIT_CASE)
    assert result["ok"] and _provenance_warnings(result) == []


# ---------------------------------------------------------------- 2. ответ модели из тёплого кэша
def test_cached_model_answer_keeps_llm_label(mock_runs):
    cold, warm = mock_runs["cold"]["report"], mock_runs["warm"]["report"]
    assert cold["run"]["calls"]["physical"] > 0 and cold["run"]["calls"]["cache_hits"] == 0
    assert warm["run"]["calls"]["physical"] == 0
    assert warm["run"]["calls"]["cache_hits"] == cold["run"]["calls"]["physical"]
    assert _stage(warm, "cross")["calls"] == 0 and _stage(warm, "cross")["cache_hits"] >= 1

    for report in (cold, warm):
        f = _one(report, "(Ф-4)")
        assert (f["source"], f["stage"]) == ("llm", "cross")
        assert f["meaning_status"] == "confirmed" and f["status"] == "confirmed"
    # подпись не зависит от того, физический это вызов или попадание в кэш
    assert [(f["title"], f["source"], f["stage"]) for f in cold["findings"]] == \
           [(f["title"], f["source"], f["stage"]) for f in warm["findings"]]

    result = verify_report(mock_runs["warm"]["json"], BCC)
    i = next(i for i, f in enumerate(warm["findings"]) if "(Ф-4)" in f["title"])
    assert result["ok"] and [w for w in _provenance_warnings(result) if w["path"].startswith(f"findings[{i}].")] == []


# ---------------------------------------------------------------- 3. смешанный вывод
@needs_engine_fix
def test_mixed_finding_names_both_producing_stages(mock_runs):
    for name in ("cold", "warm"):
        f = _one(mock_runs[name]["report"], "метод чтения не описан")
        assert len(f["merged_from"]) == 2
        assert (f["source"], f["stage"]) == ("mixed", "rules+cross")
        result = verify_report(mock_runs[name]["json"], BCC)
        assert result["ok"] and _provenance_warnings(result) == []


# ---------------------------------------------------------------- подпись на границе build_findings
def _case(items: list[dict], asked: bool, expected: tuple[str, str], case_id: str, fixed_only: bool = True):
    return pytest.param(items, asked, expected, id=case_id, marks=[needs_engine_fix] if fixed_only else [])


@pytest.mark.parametrize(("items", "asked", "expected"), [
    _case([_verified("C-1", origin="facts", stage="cross")], False, ("rules", "cross"), "facts-offline"),
    _case([_verified("C-1", origin="facts", stage="cross")], True, ("rules", "cross"), "facts-with-model"),
    _case([_verified("C-1", origin="rules", stage="cross")], True, ("rules", "cross"), "cross-rule"),
    # ответ модели №06 подписан верно и сейчас: подстановка по умолчанию «llm» совпадает с отметкой origin
    _case([_verified("C-1", origin="llm", stage="cross")], True, ("llm", "cross"), "cross-llm", fixed_only=False),
    _case([_verified("C-1", origin="facts", confirmed_by=["llm"], stage="cross")], True, ("mixed", "cross"),
          "facts-confirmed-by-model"),
    _case([_verified("C-1", source="llm+rules", stage="individual")], True, ("mixed", "individual"),
          "individual-llm+rules"),
    _case([_verified("C-1", source="rules", stage="rules"), _verified("C-facts-1", origin="facts", stage="facts")],
          False, ("rules", "rules+facts"), "rules+facts-merged"),
    _case([_verified("C-1", source="rules", stage="rules"), _verified("C-2", source="llm", stage="individual")],
          True, ("mixed", "rules+individual"), "rules+llm-merged"),
    _case([_verified("C-1")], False, ("rules", ""), "unmarked-no-model"),
    _case([_verified("C-1")], True, ("unknown", ""), "unmarked-model-asked"),
])
def test_build_findings_signs_by_producer(items, asked, expected):
    assert _label(copy.deepcopy(items), asked=asked) == expected


# ---------------------------------------------------------------- verify: старые отчёты и кэш
RELEASE_FLAGGED = {
    "other_topic_cashback": ("other_topic_cashback.md", {"F-010", "F-011", "F-019"}),
    "requirements": ("requirements.md", {"F-011", "F-012"}),
    "requirements_pdf": ("requirements.pdf", {"F-010", "F-011"}),
}


@pytest.mark.parametrize("name", sorted(RELEASE_FLAGGED))
def test_verify_flags_llm_label_in_frozen_release_reports(name):
    """Отчёты 2821989 проходят verify (совместимость), а подпись llm без ответа модели видна предупреждением."""
    source, expected = RELEASE_FLAGGED[name]
    if source.endswith(".pdf") and importlib.util.find_spec("pymupdf") is None:
        pytest.skip("reader №02 PDF требует pymupdf")
    report = RELEASE / "reports" / "offline" / f"{name}.json"
    result = verify_report(report, RELEASE / "input" / source)
    assert result["ok"] and result["exit_code"] == 0
    flagged = _provenance_warnings(result)
    assert {w["code"] for w in flagged} == {"finding_source_without_model"}
    data = json.loads(report.read_text(encoding="utf-8"))
    ids = {data["findings"][int(w["path"].split("[")[1].split("]")[0])]["id"] for w in flagged}
    assert ids == expected
    assert result["counts"]["provenance"]["unsupported"] == len(expected)


def test_verify_tells_cache_hits_from_no_model_and_skips_unknown(mock_runs, tmp_path):
    warm = json.loads(mock_runs["warm"]["json"].read_text(encoding="utf-8"))
    model_signed = {f["id"] for f in warm["findings"] if f["source"] in ("llm", "mixed")}
    assert model_signed

    # тот же отчёт, но без попаданий в кэш: подпись модели больше нечем подтвердить
    no_model = copy.deepcopy(warm)
    no_model["run"]["calls"]["cache_hits"] = 0
    for st in no_model["run"]["stages"]:
        st["cache_hits"] = 0
    path = tmp_path / "no_model.json"
    path.write_text(json.dumps(no_model, ensure_ascii=False), encoding="utf-8")
    result = verify_report(path, BCC)
    assert result["ok"]
    flagged = {no_model["findings"][int(w["path"].split("[")[1].split("]")[0])]["id"]
               for w in _provenance_warnings(result)}
    assert flagged == model_signed

    # старый отчёт без подписи или с unknown: источник неизвестен, проверка подписи не применяется
    legacy = copy.deepcopy(no_model)
    for i, f in enumerate(legacy["findings"]):
        if i % 2:
            f.pop("source", None)
        else:
            f["source"] = "unknown"
        f.pop("stage", None)
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    result = verify_report(path, BCC)
    assert result["ok"] and _provenance_warnings(result) == []
    assert result["counts"]["provenance"]["unlabeled"] == len(legacy["findings"])


def test_verify_flags_mixed_label_whose_stage_had_no_model_answer(mock_runs, tmp_path):
    """Подпись старого движка «mixed / rules» называет этап, который модель не спрашивал."""
    warm = json.loads(mock_runs["warm"]["json"].read_text(encoding="utf-8"))
    i, f = next((i, f) for i, f in enumerate(warm["findings"]) if "метод чтения не описан" in f["title"])
    f["source"], f["stage"] = "mixed", "rules"
    path = tmp_path / "old_mixed.json"
    path.write_text(json.dumps(warm, ensure_ascii=False), encoding="utf-8")
    result = verify_report(path, BCC)
    assert result["ok"]
    assert [(w["code"], w["path"]) for w in _provenance_warnings(result)] == \
           [("finding_stage_without_model", f"findings[{i}].stage")]
