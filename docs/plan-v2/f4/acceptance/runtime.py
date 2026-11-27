"""Measure CLI gates, judge replay and real annotations on the jury example (mock provider)."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from xml.etree import ElementTree
from zipfile import ZipFile


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(repo / "src"))
    source = repo / "release/input/requirements.md"

    def cli(label, *options, expect=None):
        with (out / (label + ".log")).open("wb") as log:
            run = subprocess.run([sys.executable, "-m", "bcc_review", *map(str, options)], cwd=repo, env=env,
                                 stdout=log, stderr=subprocess.STDOUT)
        if expect is not None and run.returncode != expect:
            raise RuntimeError(f"{label}: expected {expect}, got {run.returncode}; see {label}.log")
        return run.returncode

    cli("run", source, out / "report.md", "--provider", "mock", "--no-cache", "--no-html", expect=0)
    report_file = out / "report.json"
    report = read(report_file)
    run = report["run"]
    if run["provider"] != "mock" or run["dirty"] or run["status"] != "complete":
        raise ValueError("Expected a complete mock run of a clean working tree")
    codes = {"original": cli("original", "verify", report_file, source, expect=0)}
    alterations = {
        "quote": ("findings", 0, "evidence", 0, "quote"),
        "fingerprint": ("document", "sha256"),
        "counter": ("summary", "quotes_verified"),
    }
    for case, keys in alterations.items():
        changed = deepcopy(report)
        node = changed
        for key in keys[:-1]:
            node = node[key]
        replacement = {"quote": "Контрольная цитата для испытания отсутствует в исходном документе.",
                       "fingerprint": "0" * 64, "counter": -1}
        node[keys[-1]] = replacement[case]
        target = out / (case + ".json")
        target.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        codes[case] = cli("verify-" + case, "verify", target, source, expect=4)

    journal = repo / "runs" / run["run_id"]
    cli("replay", "stage", "judge", "--doc", source, "--from", journal, "--out", out / "replay.md",
        "--provider", "mock", "--no-cache", "--no-html", expect=0)
    replay = read(out / "replay.json")
    same = {field: report[field] == replay[field] for field in ("findings", "rejected", "verdict")}
    if not all(same.values()):
        raise ValueError("A saved judge input produced a different result on mock")

    export = {}
    for extension in ("docx", "pdf"):
        binary = source.with_suffix("." + extension)
        original_digest = sha256(binary.read_bytes()).hexdigest()
        md = out / ("export-" + extension + ".md")
        cli("export-" + extension, binary, md, "--provider", "mock", "--no-cache", "--no-html", "--export",
            extension, expect=0)
        doc = read(md.with_suffix(".json"))
        cli("verify-" + extension, "verify", md.with_suffix(".json"), binary, expect=0)
        annotated = md.with_suffix(".annotated." + extension)
        if extension == "docx":
            with ZipFile(annotated) as archive:
                comments = ElementTree.fromstring(archive.read("word/comments.xml"))
            labels = ["".join(c.itertext()) for c in comments]
            types = {"Word comment": len(labels)}
        else:
            import pymupdf
            with pymupdf.open(annotated) as pdf:
                annotations = [(a.type[1], a.info.get("subject", "") + " " + a.info.get("content", ""))
                               for page in pdf for a in page.annots()]
            labels = [text for _, text in annotations]
            types = dict(Counter(t for t, _ in annotations))
        identified = {m[0] for label in labels if (m := re.search(r"D-\d+", label))}
        confirmed = {f["id"] for f in doc["findings"]}
        if not identified or not identified.issubset(confirmed) or original_digest != sha256(binary.read_bytes()).hexdigest():
            raise ValueError("Invalid annotation identifiers or input changed: " + extension)
        export[extension] = dict(status=doc["run"]["status"], annotation_types=types, annotated_ids=len(identified),
                                 findings=len(confirmed), verified=True, source_unchanged=True)

    codes["blocker_gate"] = cli("blocker", source, out / "blocker.md", "--provider", "mock", "--no-cache",
                                "--no-html", "--fail-on", "blocker")
    result = dict(commit=run["commit"], provider=run["provider"], verify_exit=codes, judge_replay=same,
                  journal_stages=sorted(path.stem for path in (journal / "stages").glob("*.json")),
                  requirements=len(report["requirements"]), findings=len(report["findings"]),
                  verified_quotes=report["summary"]["quotes_verified"], exports=export)
    (out / "runtime-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
