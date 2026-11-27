"""Run the final owner-conflict judge on archived, post-filter candidates from three public documents."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


def read(path: Path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--document", choices=("official", "qr", "car-loan"), required=True)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.out.resolve()
    here = Path(__file__).resolve().parent
    exam = here.parent / "answers_exam"
    sys.path.insert(0, str(repo / "src"))
    from bcc_review.v2 import docview
    from bcc_review.v2.context import Context
    from bcc_review.v2.pipeline import DEFAULTS, make_llm
    from bcc_review.v2.stages.recheck import _judge_new, duplicate_of

    case = args.document
    inputs = read(here / "owner-judge-inputs.json")[case]
    report = read(exam / "merged" / case / "answered.json")
    source = {"official": repo / "release/input/requirements.md",
              "qr": repo / "evaluation/v2/open2/qr/source.md",
              "car-loan": exam / "car-loan/source.md"}[case]
    assert sha256(source.read_bytes()).hexdigest() == report["document"]["sha256"]
    assert all(not duplicate_of(c["evidence"], report["findings_before"], c["title"])
               for c in inputs), "Apply owner-conflicts.patch before judging these archived candidates"
    os.environ["CLAUDE_CLI_FALLBACK_MODEL"] = "off"
    opts = {**DEFAULTS, "provider": "claude_cli", "model": "sonnet", "cache": False}
    llm, provider = make_llm(opts, None, source)
    ctx = Context(view=docview.load(str(source)), llm=llm, options=opts,
                  requirements=report["requirements"], excluded=report["excluded"], signals=report["signals"])
    old = report["findings_before"]
    next_id = max(int(f["id"].split("-")[1]) for f in old) + 1
    warnings = []
    found, rejected = _judge_new(ctx, inputs, next_id, warnings, old)
    stats = llm.stats
    data = {"document": case, "source_sha256": report["document"]["sha256"],
            "archived_run": report["run"]["run_id"],
            "code_base": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
            "recheck_py_sha256": sha256((repo / "src/bcc_review/v2/stages/recheck.py").read_bytes()).hexdigest(),
            "provider": provider, "model_requested": opts["model"], "models_used": stats["models_used"],
            "calls": {k: stats[k] for k in ("calls","cached","failed")}, "inputs": [c["id"] for c in inputs],
            "warnings": warnings + ctx.warnings, "findings": found, "rejected": rejected,
            "judge_responses": llm.responses.get("judge", [])}
    output.mkdir(parents=True, exist_ok=True)
    (output / (case + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert data["models_used"] == ["claude-sonnet-5-5"] and data["judge_responses"]
    assert stats["calls"] and not stats["cached"] and not stats["failed"] and not warnings
    print(case, data["models_used"], data["calls"], "findings", len(found), "rejected", len(rejected))


if __name__ == "__main__":
    main()
