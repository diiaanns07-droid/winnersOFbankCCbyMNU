"""Повтор открытых измерений №27 и проверки дублей F4 на выбранной рабочей копии."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

STAGE_DATA = '6585fe935ba7b0107320881e28791719aa118996'
OWNER_DATA = '91f8b812c5fa2111f9f06caf2588352ed3dfd87d'
CASES = ("official", "qr", "car-loan")
AUDIT = "docs/plan-v2/f4/answers_exam/merged"


def git(tree: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(tree), *arguments]).decode("utf-8")


def object_json(tree: Path, revision: str, path: str):
    return json.loads(git(tree, "show", f"{revision}:{path}"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, default=Path.cwd(), help="Рабочая копия проверяемой версии")
    parser.add_argument("--out", type=Path, help="Файл результата JSON. По умолчанию — stdout.")
    args = parser.parse_args()
    tree = args.tree.resolve()
    sys.path[:0] = [str(tree / "src"), str(tree)]
    from bcc_review.v2.pipeline import load_view
    from bcc_review.v2.stages import consistency, recheck

    tool = tree / "tests/v2/fixtures/09_tools/stage_bench.py"
    spec = importlib.util.spec_from_file_location("score_09", tool)
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    labels = bench.corpus_labels()
    result = {"commit": git(tree, "rev-parse", "HEAD").strip(), "stage": {}, "owner": {}}
    for sample in ("h5", "c0"):
        folder = f"tests/v2/fixtures/27_runs/{sample}"
        paths = git(tree, "ls-tree", "-r", "--name-only", STAGE_DATA, folder).splitlines()
        rows = []
        for path in paths:
            if not path.endswith(".json"):
                continue
            saved = object_json(tree, STAGE_DATA, path)
            stage = consistency.postprocess(saved["raw"], load_view(tree / saved["doc"]), saved["requirements"])
            grades = [item["severity"] for item in stage["candidates"]]
            row = {"case": saved["case"], "critical": grades.count("critical"), "major": grades.count("major")}
            if sample == "c0":
                row["found"] = bench.score_file({**saved, "output": stage}, labels)["found"]
            rows.append(row)
        if not rows:
            raise ValueError(f"Нет сохранённых ответов в {folder}")
        result["stage"][sample] = rows

    proposed = object_json(tree, OWNER_DATA, f"{AUDIT}/candidates.json")
    for case in CASES:
        report = object_json(tree, OWNER_DATA, f"{AUDIT}/{case}/answered.json")
        rows = []
        for candidate in proposed[case]["кандидаты"]:
            evidence = [{"quote": ev["quote"], "line_start": ev["line"]} for ev in candidate["evidence"]]
            twin = recheck.duplicate_of(evidence, report["findings_before"], candidate["title"])
            rows.append({"title": candidate["title"], "duplicate_of": twin})
        result["owner"][case] = rows
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
