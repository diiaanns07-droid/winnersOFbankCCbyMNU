"""Попарная проверка судьи на сохранённых кандидатах и действительных ответах владельца."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from replay import AUDIT, CASES, OWNER_DATA, git, object_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, default=Path.cwd())
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--model", choices=("sonnet", "haiku"), default="sonnet")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", help="Сохранить вход судьи без обращения к модели")
    args = parser.parse_args()
    tree = args.tree.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(tree / "src"), str(tree)]
    from bcc_review.v2 import pipeline
    from bcc_review.v2.context import Context
    from bcc_review.v2.runs import RunDir
    from bcc_review.v2.stages import recheck

    report = object_json(tree, OWNER_DATA, f"{AUDIT}/{args.case}/answered.json")
    old = report["findings_before"]
    fixture = Path(__file__).with_name("judge_inputs.json")
    proposals = json.loads(fixture.read_text(encoding="utf-8"))[args.case]
    candidates = [p for p in proposals if not recheck.duplicate_of(p["evidence"], old, p["title"])]
    (out / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.prepare_only:
        print(f"Передано судье {len(candidates)} из {len(proposals)}")
        return 0

    sources = {"official": "release/input/requirements.md", "qr": "evaluation/v2/open2/qr/source.md",
               "car-loan": "docs/plan-v2/f4/answers_exam/car-loan/source.md"}
    data = subprocess.check_output(["git", "-C", str(tree), "show", f"{OWNER_DATA}:{sources[args.case]}"])
    if hashlib.sha256(data).hexdigest() != report["document"]["sha256"]:
        raise ValueError("Исходник отличается от документа из паспорта")
    source = out / "source.md"
    source.write_bytes(data)
    os.environ["CLAUDE_CLI_FALLBACK_MODEL"] = "off"
    opts = dict(pipeline.DEFAULTS, provider="claude_cli", model=args.model, cache=False, fallback_models=[], effort="low")
    rd = RunDir(out / "runs", "owner-judge")
    llm, _ = pipeline.make_llm(opts, rd, source)
    ctx = Context(view=pipeline.load_view(source), llm=llm, requirements=report["requirements"],
                  options={**opts, "input": str(source)}, run_dir=rd.path, trace=rd.trace)
    warnings = []
    next_id = 1 + max(int(f["id"].split("-")[1]) for f in old)
    found, rejected = recheck._judge_new(ctx, candidates, next_id, warnings, old)
    warnings.extend(ctx.warnings)
    fallback = any("судья недоступен" in w or "не рассмотрел" in w for w in warnings)
    stats = llm.stats
    models = stats.get("models_used") or []
    measured = (not fallback and stats["calls"] and not stats["failed"] and not stats["cached"]
                and models and all(args.model in m for m in models))
    status = "no_candidates" if not candidates else "complete" if measured else "partial"
    result = {"commit": git(tree, "rev-parse", "HEAD").strip(), "model_requested": args.model,
              "status": status, "input_sha256": report["document"]["sha256"],
              "candidate_ids": [c["id"] for c in candidates], "findings": found,
              "rejected": rejected, "warnings": warnings, "stats": stats}
    (out / "judge.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(status, models, len(found), len(rejected))
    return 3 if status == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
