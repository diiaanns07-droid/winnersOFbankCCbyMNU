"""Compare the same public mutations as MD, PDF and DOCX through the real offline CLI."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


FORMATS = ("md", "pdf", "docx")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--font-dir", type=Path, help="Directory containing the DejaVu TTF family")
    parser.add_argument("--corpus", type=Path, help="Previously generated public three-format corpus")
    parser.add_argument("--agent-python", default=sys.executable)
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(repo), str(repo / "src")]
    from evaluation.dev import render
    from evaluation.dev.generator import write_corpus
    from evaluation.v2.corpus import adapt_report
    from bcc_review.v2.verify import verify_report

    corpus = args.corpus.resolve() if args.corpus else out / "corpus"
    if not args.corpus:
        if args.font_dir:
            render.FONT_DIRS = (str(args.font_dir.resolve()), *render.FONT_DIRS)
        write_corpus(corpus, [1], False, FORMATS, ("base", "mutant", "combo", "edge"))
    manifest = read(corpus / "manifest.json")
    if manifest["visibility"] != "public" or manifest["seeds"] != [1]:
        raise ValueError("Expected the public seed-1 development corpus")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(repo / "src") + os.pathsep + str(repo))
    entries = []
    edges = []
    for case in manifest["cases"]:
        if {r["format"] for r in case["renders"]} != set(FORMATS):
            raise ValueError("Incomplete format set for " + case["case_id"])
        for variant in case["renders"]:
            if not variant["render_check"]["ok"]:
                raise ValueError("Rendering lost a source anchor in " + variant["render_id"])
            if case["kind"] == "edge":
                edges.append(variant["render_id"])
            else:
                entries.append((case, variant))

    def one(pair):
        case, variant = pair
        source = corpus / variant["path"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != variant["sha256"]:
            raise ValueError("Source fingerprint mismatch for " + variant["render_id"])
        target = out / "runs" / case["case_id"] / variant["format"]
        target.mkdir(exist_ok=True, parents=True)
        md, raw = target / "report.md", target / "report.json"
        if not raw.is_file():
            with (target / "run.log").open("wb") as log:
                subprocess.run([args.agent_python, "-m", "bcc_review", str(source), str(md),
                                "--provider", "offline", "--no-cache", "--no-html"],
                               cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        report = read(raw)
        run = report["run"]
        if (run["provider"] != "offline" or run["dirty"] or not revision.startswith(run["commit"])
                or run["calls"]["total"] or report["document"]["sha256"] != digest
                or run["status"] != "complete"):
            raise ValueError("Incompatible report at " + str(raw))
        verified = verify_report(raw, source, markdown=md)
        if not verified["ok"]:
            raise ValueError((variant["render_id"], verified["errors"]))
        findings = report["findings"]
        record = dict(case=case["case_id"], format=variant["format"], count=len(findings),
                      severity=dict(Counter(f["severity"] for f in findings)),
                      verdict=[report["verdict"][k] for k in ("development", "testing")],
                      quotes=verified["counts"]["quotes_verified"])
        return record, adapt_report(report, digest, "rules_only")

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        rows = list(pool.map(one, entries))
    predictions = out / "predictions.jsonl"
    predictions.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for _, pp in rows for p in pp),
                           encoding="utf-8")
    metrics = {}
    for fmt in FORMATS:
        output = out / (fmt + ".metrics.json")
        subprocess.run([args.agent_python, "-m", "evaluation.harness", "--gold", str(corpus / "labels.jsonl"),
                        "--pred", str(predictions), "--manifest", str(corpus / "manifest.json"),
                        "--render-format", fmt, "--mode", "rules_only", "--out", str(output), "--quiet"],
                       cwd=repo, env=env, check=True)
        metrics[fmt] = read(output)
    records = [record for record, _ in rows]
    checks = []
    for case_id in sorted({r["case"] for r in records}):
        case_rows = [r for r in records if r["case"] == case_id]
        counts = [r["count"] for r in case_rows]
        roots = [{t["label_id"] for t in metrics[fmt]["true_positives"] if t["case_id"] == case_id}
                 for fmt in FORMATS]
        checks.append(dict(case=case_id, count_range=max(counts) - min(counts),
                           same_detected_roots=all(group == roots[0] for group in roots[1:]),
                           same_verdict=len({tuple(r["verdict"]) for r in case_rows}) == 1))
    result = dict(commit=revision, seed=manifest["seeds"], corpus=manifest["corpus_semantic_sha256"],
                  provider="offline", physical_model_calls=0, controls_excluded=edges,
                  scores={fmt: {k: metrics[fmt]["micro"][k] for k in ("tp", "fp", "fn", "duplicates")}
                          for fmt in FORMATS}, format_checks=checks, verified_reports=records)
    write(out / "result.json", result)
    print(len(records), "verified reports;", len(checks), "source variants")
    print(json.dumps(result["scores"], ensure_ascii=False))


if __name__ == "__main__":
    main()
