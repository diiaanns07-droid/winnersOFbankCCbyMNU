"""Открытые контроли проверки состава: настоящий продукт и раннер, по одному нарушению на копию прогона.

    python -m evaluation.dev composition --stand ../stand --python ../venv/bin/python --out out/composition

--stand — checkout продукта (для серии — 2821989): из него берутся src/ продукта, раннер и счётчик
evaluation/harness (раскладка каталогов прогона та же, что у Max) и записи транспорта tests/p11/fixtures.
--python — интерпретатор с пакетом anthropic==2.14.0 (нужен адаптеру команды; сеть не используется).

Что делается (открытый dev-корпус, 33 кейса, MD):
1. базовые прогоны rules_only (песочница сети) и rules_plus_llm (replay_product.py: записанный транспорт);
2. сценарии из composition_controls/expected.json: каждый меняет один кейс LLM-прогона;
3. аудит пары (rules_only базы, rules_plus_llm сценария) кодом этой ветки и сверка с ручным ответом;
4. для сравнения — вердикт существующей compare/comparable() счётчика стенда (метрики не публикуются).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from evaluation.harness.audit import audit, write_outputs

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
EXPECTED = ROOT / "composition_controls" / "expected.json"
REPLAY = ROOT / "replay_product.py"
SCENARIO_CASE = {
    "same_name_changed": "cashback.unit_change.accrued_in_tiyn",
    "run_twice": "autopay.two_statuses.range_422",
    "clean_without_report": "cardblock.base",
    "requested_llm_got_rules_only": "transfer_limit.range_boundary.reaching_rejects",
    "valid_partial": "cashback.two_statuses.bad_category_200",
    "old_report_fields": "autopay.paraphrase.nfr",
    "hidden_llm_failure": "cardblock.unit_change.blocked_at_utc",
}
EDIT_LINE = "\nДополнение после разметки: формулировка уточнена.\n"


class Stand:
    def __init__(self, stand: str, python: str):
        self.root = Path(stand).resolve()
        self.python = str(Path(python).absolute())
        self.env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(self.root), str(self.root / "src")]),
                        BCC_REPLAY_FIXTURES=str(self.root / "tests" / "p11" / "fixtures"))

    def harness(self, *args: str, plan: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(self.env, BCC_REPLAY_PLAN=json.dumps(plan or {}))
        # cwd = стенд: python -m берёт evaluation.harness стенда, а не этой ветки
        return subprocess.run([self.python, "-m", "evaluation.harness", *args], cwd=self.root, env=env,
                              capture_output=True, text=True)

    def run(self, manifest: Path, mode: str, out: Path, plan: dict | None = None, cases: str | None = None) -> None:
        args = ["run", "--manifest", str(manifest), "--mode", mode, "--out", str(out)]
        if mode == "rules_plus_llm":
            args += ["--provider", "anthropic", "--product-cmd", f"{self.python} {REPLAY} {{input}} {{output}}"]
        else:
            args += ["--product-cmd", f"{self.python} -m bcc_review {{input}} {{output}}"]
        if cases:
            args += ["--cases", cases]
        p = self.harness(*args, plan=plan)
        if p.returncode != 0:
            raise RuntimeError(f"run {mode} → {out}: {p.stderr[-2000:]}")

    def comparable(self, gold: Path, manifest: Path, ro: Path, llm: Path, out: Path) -> dict:
        for d in (ro, llm):
            p = self.harness("--gold", str(gold), "--pred", str(d / "predictions.jsonl"), "--manifest", str(manifest),
                             "--out", str(out / f"{d.name}.metrics.json"), "--quiet")
            if p.returncode != 0:
                return {"comparable": None, "error": p.stderr[-500:]}
        p = self.harness("compare", "--metrics", f"rules_only={out / 'ro.metrics.json'}",
                         "--metrics", f"rules_plus_llm={out / 'llm.metrics.json'}", "--json", str(out / "compare.json"))
        data = json.loads((out / "compare.json").read_text(encoding="utf-8"))
        return {"comparable": data["comparable"], "reasons": data["reasons"], "exit_code": p.returncode}


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_sha(case_id: str) -> str:
    m = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    case = next(c for c in m["cases"] if c["case_id"] == case_id)
    return next(r["sha256"] for r in case["renders"] if r["format"] == case["primary_render"])


def build_scenario(name: str, st: Stand, base_llm: Path, out: Path) -> Path:
    """Каталог rules_plus_llm сценария; ровно одно отличие от базы."""
    cid = SCENARIO_CASE[name]
    llm = out / "llm"
    if name == "same_name_changed":
        corpus = out / "corpus"
        shutil.copytree(CORPUS, corpus, ignore=shutil.ignore_patterns("*.pdf", "*.docx"))
        src = corpus / "cases" / cid / "source.md"
        src.write_bytes(src.read_bytes() + EDIT_LINE.encode("utf-8"))  # имя то же, манифест прежний
        st.run(corpus / "manifest.json", "rules_plus_llm", llm)
    elif name == "run_twice":
        shutil.copytree(base_llm, llm)
        st.run(CORPUS / "manifest.json", "rules_plus_llm", llm / "rerun", cases=cid)
        merged = (llm / "predictions.jsonl").read_text(encoding="utf-8") + \
            (llm / "rerun" / "predictions.jsonl").read_text(encoding="utf-8")
        (llm / "predictions.jsonl").write_text(merged, encoding="utf-8")  # как объединяет open_run
    elif name == "old_report_fields":
        shutil.copytree(base_llm, llm)
        sha = _corpus_sha(cid)
        rep = next(p for p in sorted(llm.glob("reports/*/report.json"))
                   if json.loads(p.read_text(encoding="utf-8"))["run"].get("source_sha256") == sha)
        data = json.loads(rep.read_text(encoding="utf-8"))
        for k in ("mode", "calls", "stages"):
            data["run"].pop(k, None)
        rep.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        plan = {"clean_without_report": "fail:bank", "requested_llm_got_rules_only": "no_key",
                "valid_partial": "fail:individual", "hidden_llm_failure": "fail:cross.pairs"}[name]
        st.run(CORPUS / "manifest.json", "rules_plus_llm", llm, plan={_corpus_sha(cid): plan})
    return llm


def _triples(res: dict) -> tuple[list, list]:
    matrix = sorted([m["code"], m["run"], m["case_id"]] for m in res["matrix"])
    partial = sorted([i["run"], i["case_id"]] for i in res["info"] if i["code"] == "partial")
    return matrix, partial


def run_controls(stand: str, python: str, out: str, only: list[str] | None = None) -> dict:
    st = Stand(stand, python)
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))["scenarios"]
    out_dir = Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    gold, manifest = CORPUS / "labels.jsonl", CORPUS / "manifest.json"
    base = out_dir / "base"
    if not (base / "ro" / "run_config.json").exists():
        st.run(manifest, "rules_only", base / "ro")
    if not (base / "llm" / "run_config.json").exists():
        st.run(manifest, "rules_plus_llm", base / "llm")
    head = st.harness("--version")
    summary = {"schema": "bcc-eval-audit-controls/1", "stand_harness": head.stdout.strip(),
               "audit_sha256": None, "scenarios": {}, "ok": True}
    for name, exp in expected.items():
        if only and name not in only:
            continue
        d = out_dir / name
        llm = base / "llm" if name == "base" else d / "llm"
        if name != "base" and not (llm / "predictions.jsonl").exists():
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True)
            build_scenario(name, st, base / "llm", d)
        res = audit(gold, [f"rules_only={base / 'ro'}", f"rules_plus_llm={llm}"], expect_agent_commit="2821989")
        write_outputs(res, d / "audit")
        summary["audit_sha256"] = res["audit_sha256"]
        matrix, partial = _triples(res)
        got = {"exit_code": res["verdict"]["exit_code"], "matrix": matrix, "partial": partial,
               "excluded_symmetric": res["verdict"]["excluded_symmetric"], "admissible": res["verdict"]["admissible"]}
        want = {k: (sorted(v) if isinstance(v, list) else v) for k, v in exp.items() if k != "change"}
        problems = [f"{k}: ожидалось {want[k]!r}, получено {got[k]!r}" for k in want if want[k] != got[k]]
        cmp_dir = d / "compare"
        cmp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(base / "ro", cmp_dir / "ro", dirs_exist_ok=True, ignore=shutil.ignore_patterns("reports"))
        shutil.copytree(llm, cmp_dir / "llm", dirs_exist_ok=True, ignore=shutil.ignore_patterns("reports", "rerun"))
        man = d / "corpus" / "manifest.json" if (d / "corpus").exists() else manifest
        summary["scenarios"][name] = {
            "change": exp["change"], "ok": not problems, "problems": problems, **got,
            "matrix_reasons": [{"code": m["code"], "run": m["run"], "case_id": m["case_id"], "reason": m["reason"]}
                               for m in res["matrix"]],
            "partial_reasons": [{"run": i["run"], "case_id": i["case_id"], "reason": i["reason"]}
                                for i in res["info"] if i["code"] == "partial"],
            "llm_coverage": res["llm_coverage"]["rules_plus_llm"],
            "existing_compare": st.comparable(gold, man, cmp_dir / "ro", cmp_dir / "llm", cmp_dir),
        }
        summary["ok"] = summary["ok"] and not problems
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m evaluation.dev composition")
    ap.add_argument("--stand", required=True, help="checkout продукта (серия: 2821989)")
    ap.add_argument("--python", default=sys.executable, help="интерпретатор с anthropic==2.14.0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="только эти сценарии через запятую")
    a = ap.parse_args(argv)
    s = run_controls(a.stand, a.python, a.out, a.only.split(",") if a.only else None)
    for name, sc in s["scenarios"].items():
        cmp = sc["existing_compare"].get("comparable")
        print(f"{'OK ' if sc['ok'] else 'FAIL'} {name:<30} аудит: код {sc['exit_code']}, "
              f"{', '.join(f'{m[0]}:{m[2]}' for m in sc['matrix']) or 'нарушений нет'}"
              f"{'; partial: ' + ', '.join(p[1] for p in sc['partial']) if sc['partial'] else ''}"
              f" | существующий compare: сопоставимо={cmp}")
        for p in sc["problems"]:
            print(f"     {p}")
    print(f"итог: {'все сценарии совпали с ручным ответом' if s['ok'] else 'есть расхождения'} → {a.out}/summary.json")
    return 0 if s["ok"] else 1
