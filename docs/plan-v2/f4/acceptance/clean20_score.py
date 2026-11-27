"""Summarize the eight public clean20 reports against their empty published answer keys."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml


def summarize(repo: Path, reports: Path):
    sources = sorted((repo / "evaluation/v2/clean").glob("*/source.md"))
    if len(sources) != 8:
        raise ValueError(f"Expected eight clean20 cases, found {len(sources)}")
    sys.path.insert(0, str(repo / "src"))
    from bcc_review.v2.verify import verify_report

    rows = []
    for source in sources:
        case = source.parent.name
        gold = yaml.safe_load((source.parent / "gold.yaml").read_text(encoding="utf-8"))
        digest = sha256(source.read_bytes()).hexdigest()
        if gold["variant"] != "clean" or gold["items"] or gold["sha256"] != digest:
            raise ValueError(f"{case}: source does not match its empty answer key")
        path = reports / (case + ".json")
        report = json.loads(path.read_bytes())
        run = report["run"]
        if (run["status"], run["models_used"], run["dirty"], run["calls"]["cached"], run["calls"]["failed"]) != (
            "complete", ["claude-haiku-5-5"], False, 0, 0
        ):
            raise ValueError(f"{case}: incomplete or incomparable model run")
        rev = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{7,40}", run["commit"]) or not rev.startswith(run["commit"]):
            raise ValueError(f"{case}: report commit does not match the supplied checkout")
        check = verify_report(path, source, markdown=path.with_suffix(".md") if path.with_suffix(".md").exists() else None)
        if not check["ok"]:
            raise ValueError(f"{case}: report verification failed")
        findings = report["findings"]
        verdict = {key: report["verdict"][key] for key in ("development", "testing")}
        counts = Counter(f["severity"] for f in findings)
        rows.append({"case": case, "run_id": run["run_id"], "code": run["commit"], "source_sha256": digest,
                     "model": run["models_used"][0], "findings_outside_empty_gold": len(findings),
                     "critical": counts["critical"], "major": counts["major"], "minor": counts["minor"],
                     "verdict": verdict, "expected": gold["expected_verdict"],
                     "model_calls": run["calls"]["total"], "seconds": run["duration_s"]})
    return {"cases": rows, "total_findings": sum(r["findings_outside_empty_gold"] for r in rows),
            "total_critical": sum(r["critical"] for r in rows), "total_major": sum(r["major"] for r in rows),
            "total_minor": sum(r["minor"] for r in rows),
            "documents_without_findings": sum(r["findings_outside_empty_gold"] == 0 for r in rows),
            "documents_over_one": sum(r["findings_outside_empty_gold"] > 1 for r in rows),
            "both_verdicts_match": sum(r["verdict"] == r["expected"] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.repo.resolve(), args.reports.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
