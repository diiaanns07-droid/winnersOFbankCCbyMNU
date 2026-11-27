"""№26, релиз: судья не падает на кривом ответе модели и даёт один и тот же реестр на одном и том же входе.

Без сети: ответы модели — сохранённые ответы судьи sonnet (фикстуры №10) или заготовки.
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, cand, finding, response, simple_view  # noqa: E402

FX = ROOT / "tests" / "v2" / "fixtures" / "10_judge"
DOC = ROOT / "release" / "input" / "requirements.md"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"


def _load(case: str):
    cands = json.loads((FX / f"{case}.candidates.json").read_text(encoding="utf-8"))["candidates"]
    resp = json.loads((FX / f"{case}.judge_sonnet.json").read_text(encoding="utf-8"))
    check = FX / f"{case}.check_sonnet.json"
    check = json.loads(check.read_text(encoding="utf-8")) if check.exists() else None
    reqs = json.loads(SEGMENT.read_text(encoding="utf-8"))["requirements"]
    return cands, resp, check, reqs


def _run(cands, resp, check, reqs):
    llm = FakeLLM(resp, check) if check is not None else FakeLLM(resp)
    ctx = Ctx(llm, view=simple_view(DOC), requirements=reqs, options={} if check is not None else None)
    return judge.run(ctx, cands)


def _fingerprint(res: dict) -> str:
    return json.dumps({"f": res["findings"], "r": res["rejected"], "c": res["checklist"],
                       "v": res["verdict_summary"], "x": res["fix_first"]}, ensure_ascii=False, sort_keys=True)


# --- одинаковый вход → одинаковый реестр ---------------------------------------------------------


def test_same_input_any_order_same_registry():
    """Порядок кандидатов на входе и порядок дефектов в ответе модели не меняют ни ID D-xx, ни порядок, ни тексты."""
    cands, resp, check, reqs = _load("official.full")
    base = _fingerprint(_run(copy.deepcopy(cands), copy.deepcopy(resp), copy.deepcopy(check), reqs))
    for seed in (1, 2, 3):
        c2, r2 = copy.deepcopy(cands), copy.deepcopy(resp)
        random.Random(seed).shuffle(c2)
        random.Random(seed).shuffle(r2["findings"])
        random.Random(seed).shuffle(r2["rejected"])
        random.Random(seed).shuffle(r2["checklist"])
        assert _fingerprint(_run(c2, r2, copy.deepcopy(check), reqs)) == base, seed


_SCRIPT = """
import json, sys, hashlib
sys.path.insert(0, {tests!r}); sys.path.insert(0, {src!r})
from test_26_judge_release import _load, _run, _fingerprint
print(hashlib.sha256(_fingerprint(_run(*_load("official.full"))).encode()).hexdigest())
"""


def test_same_input_any_hash_seed_same_registry():
    """Порядок обхода множеств в Python меняется от запуска к запуску (PYTHONHASHSEED) — реестр не должен."""
    code = _SCRIPT.format(tests=str(ROOT / "tests" / "v2"), src=str(ROOT / "src"))
    out = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120,
                           cwd=str(ROOT))
        assert r.returncode == 0, r.stderr[-2000:]
        out.add(r.stdout.strip().splitlines()[-1])
    assert len(out) == 1


# --- кривой ответ модели не роняет этап ---------------------------------------------------------


def _three():
    return [cand("C-001", 38, "Месяц определяется по дате совершения покупки", kind="contradiction",
                 criterion="set_consistent", severity="major"),
            cand("C-002", 64, "Февральский счётчик вырос", kind="contradiction", criterion="set_consistent"),
            cand("C-003", 90, "Удобный интерфейс", kind="ambiguity")]


def test_malformed_response_fields_do_not_crash():
    """Строка вместо списка ID, строка в списке дефектов, bool в приоритете, число в finding_keys, строка
    в чек-листе и в отклонённых — этап не падает, верные решения сохраняются."""
    bad = response([
        "не объект",
        {**finding("F01", ["C-001"]), "candidate_ids": "C-001, C-002", "priority": True,
         "requirement_ids": "R-06", "wish": "да", "title": 42},
        {**finding("F02", ["C-003"]), "severity": None, "blocks": ["both"], "problem": {"x": 1}},
    ], rejected=["C-003", 7], checklist=["Да", {"n": "1", "answer": "Частично", "comment": None,
                                               "finding_keys": 5}], summary=["Разработку начинать нельзя"])
    res = judge.run(Ctx(FakeLLM(bad)), _three())
    all_placed(res, ["C-001", "C-002", "C-003"])
    f01 = next(f for f in res["findings"] if "C-001" in f["candidate_ids"])
    assert f01["candidate_ids"] == ["C-001", "C-002"]  # строка ID разобрана по запятой
    assert f01["priority"] in range(0, 8) and f01["title"]
    assert all(isinstance(f["problem"], str) for f in res["findings"])
    assert res["checklist"][0]["answer"] == "Частично"  # n строкой «1» → 1
    assert isinstance(res["verdict_summary"], str) and res["verdict_summary"]
    assert not any("судья недоступен" in w for w in res["warnings"])  # не запасной реестр кода


def test_malformed_check_and_repair_responses_do_not_crash():
    """Кривые ответы второй проверки и повторного вызова — тоже без падения; уровни не повышаются."""
    first = response([finding("F01", ["C-001", "C-002"], severity="critical", scenario="Вход 1 — два исхода.",
                              impact="Спор.")])
    repair = {"assignments": ["C-003", {"candidate_id": ["C-003"], "decision": 1}]}
    check = {"checks": "critical", "verdict_summary": 3}
    res = judge.run(Ctx(FakeLLM(first, repair, check), options={}), _three())
    all_placed(res, ["C-001", "C-002", "C-003"])
    assert any(f["severity"] == "critical" for f in res["findings"])


def test_candidate_requirement_ids_string_and_bad_evidence():
    """ID требований строкой — как список; цитаты не объектами — отброшены, а не падение."""
    c = _three()
    c[0]["requirement_ids"] = "R-06, R-07"
    c[1]["evidence"] = c[1]["evidence"] + ["лишняя строка", 5]
    c[2]["evidence"] = c[2]["evidence"][0]  # объект вместо списка
    junk = ["не кандидат", None]
    res = judge.run(Ctx(FakeLLM(response([finding("F01", ["C-001", "C-002"]), finding("F02", ["C-003"])]))),
                    c + junk)
    all_placed(res, ["C-001", "C-002", "C-003"])
    f = next(f for f in res["findings"] if "C-001" in f["candidate_ids"])
    assert set(f["requirement_ids"]) <= {"R-06", "R-07"} and f["requirement_ids"]
    assert any("не объект" in w for w in res["warnings"])


def test_conform_keeps_valid_response_unchanged():
    """На ответе по схеме приведение — тождество (повтор сохранённого ответа sonnet)."""
    _, resp, check, _ = _load("official.full")
    assert judge._conform(copy.deepcopy(resp), judge.response_schema()) == resp
    assert judge._conform(copy.deepcopy(check), judge.check_schema()) == check


# --- ключи модели (F01…) не попадают в отчёт -------------------------------------------------------


_KEY_RE = re.compile(r"(?<![\w-])(?:P\d)?[FR]\d{2}(?![\w-])")


def _texts(res: dict) -> list[str]:
    out = [res["verdict_summary"]] + [r.get("reason", "") for r in res["rejected"]]
    out += [c["comment"] for c in res["checklist"]]
    out += [f[k] for f in res["findings"] for k in ("title", "problem", "scenario", "impact", "recommendation",
                                                    "question")]
    return out


def test_rejected_reason_key_becomes_finding_id():
    """«Конфликт покрыт F01» в причине отклонения → номер дефекта из отчёта (D-xx), а не ключ модели."""
    resp = response([finding("F01", ["C-001", "C-002"], kind="contradiction")],
                    rejected=[{"candidate_id": "C-003", "reason_code": "resolved_elsewhere",
                               "reason": "Конфликт уже покрыт F01.", "line": 0}],
                    summary="Есть существенные замечания F01.")
    res = judge.run(Ctx(FakeLLM(resp)), _three())
    rej = next(r for r in res["rejected"] if r["candidate_id"] == "C-003")
    d = next(f["id"] for f in res["findings"] if "C-001" in f["candidate_ids"])
    assert rej["reason"] == f"Конфликт уже покрыт {d}."
    assert not any(_KEY_RE.search(t) for t in _texts(res))


def test_dangling_key_of_dropped_finding_removed():
    """Дефект модели F02 отпал (ссылается на несуществующего кандидата): ссылки на F02 убираются, обоснование
    вердикта со ссылкой на F02 собирает код."""
    resp = response([finding("F01", ["C-001", "C-002"], kind="contradiction"), finding("F02", ["C-999"])],
                    rejected=[{"candidate_id": "C-003", "reason_code": "resolved_elsewhere",
                               "reason": "Вопрос учтён в F02.", "line": 0}],
                    checklist=[{"n": 1, "answer": "Частично", "comment": "См. F02 и F01.", "finding_keys": ["F02"]}],
                    summary="Разработку можно начинать с условиями: F01 и F02.")
    res = judge.run(Ctx(FakeLLM(resp)), _three())
    assert not any(_KEY_RE.search(t) for t in _texts(res)), _texts(res)
    rej = next(r for r in res["rejected"] if r["candidate_id"] == "C-003")
    assert rej["reason"] == "Вопрос учтён."


def test_empty_register_summary_follows_code_verdict():
    """Все дефекты модели отпали, реестр пуст, вердикт «можно» — текст модели «нельзя: F01» заменяет код."""
    resp = response([], rejected=[{"candidate_id": c, "reason_code": "misread", "reason": "Неверно прочитано.",
                                   "line": 0} for c in ("C-001", "C-002", "C-003")],
                    summary="Разработку начинать нельзя: F01.")
    res = judge.run(Ctx(FakeLLM(resp)), _three())
    assert res["findings"] == []
    v = judge.compute_verdict(res["findings"])
    assert (v["development"], v["testing"]) == ("yes", "yes")
    assert "нельзя" not in res["verdict_summary"] and "F01" not in res["verdict_summary"]
    assert res["verdict_summary"].startswith("Разработку и тестирование можно начинать")


def test_checklist_link_to_consolidated_finding_kept():
    """Пункт чек-листа ссылался на мелочь, которую код свёл в одно замечание: ссылка ведёт к сводному, а не теряется."""
    cs = [cand("C-001", 38, "Месяц определяется по дате совершения покупки", kind="terminology", severity="minor"),
          cand("C-002", 64, "Февральский счётчик вырос", kind="terminology", severity="minor"),
          cand("C-003", 90, "Удобный интерфейс", kind="ambiguity")]
    resp = response([finding("F01", ["C-001"], kind="terminology", severity="minor"),
                     finding("F02", ["C-002"], kind="terminology", severity="minor"),
                     finding("F03", ["C-003"])],
                    checklist=[{"n": 1, "answer": "Частично", "comment": "Термины: F02.", "finding_keys": ["F02"]}])
    res = judge.run(Ctx(FakeLLM(resp)), cs)
    merged = next(f for f in res["findings"] if {"C-001", "C-002"} <= set(f["candidate_ids"]))
    assert res["checklist"][0]["finding_ids"] == [merged["id"]]
    assert res["checklist"][0]["comment"] == f"Термины: {merged['id']}."


def test_document_ids_like_model_keys_untouched():
    """Если в самом документе есть ID вида F02, он не «висячий ключ» и остаётся в тексте."""
    view = {"title": "t", "file": "t.md", "format": "md",
            "lines": [{"n": i, "text": t, "page": None, "section": ""} for i, t in enumerate(
                ["Требования"] + ["Строка"] * 36 + ["F02. Месяц определяется по дате совершения покупки"]
                + ["Строка"] * 25 + ["Февральский счётчик вырос"] + ["Строка"] * 30, 1)]}
    resp = response([finding("F01", ["C-001", "C-002"], kind="contradiction")],
                    rejected=[{"candidate_id": "C-003", "reason_code": "resolved_elsewhere",
                               "reason": "Требование F02 уже задаёт это.", "line": 0}])
    res = judge.run(Ctx(FakeLLM(resp), view=view, requirements=[]), _three())
    rej = next(r for r in res["rejected"] if r["candidate_id"] == "C-003")
    assert rej["reason"] == "Требование F02 уже задаёт это."
