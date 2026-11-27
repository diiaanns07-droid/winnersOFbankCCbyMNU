"""Run the public repeated-time example and its one-line control on a clean product checkout."""
import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "protocol"))
from run import call, digest, environment, git, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="A new directory outside the product checkout")
    args = parser.parse_args()
    product, out = args.product.resolve(), args.out.resolve()
    if out.is_relative_to(product) or git(product, "status", "--porcelain"):
        parser.error("Use a clean checkout and an output directory outside it")
    sha = git(product, "rev-parse", "HEAD")
    env = environment(product, "rules_only")
    env.pop("BCC_FORCE_FALLBACK", None)
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for name in ("occurrence", "control"):
        folder = out / name
        folder.mkdir()
        source = HERE / (name + ".md")
        report = folder / "report.json"
        rc, _ = call(["-m", "bcc_review", source, folder / "report.md", "--offline-lint", "--no-cache"], env, product, folder / "run")
        if rc != 0 or not report.is_file():
            raise SystemExit(f"{name}: product failed, see {folder}")
        verified, _ = call(["-m", "bcc_review", "verify", report, source], env, product, folder / "verify")
        data = read(report)
        run = data["run"]
        identity = (run["agent_commit"] == sha and data["document"]["id"] == run["source_sha256"] == digest(source)
                    and run["mode"] == "rules_only" and run["model"] is None and run["calls"]["physical"] == 0
                    and run["calls"]["cache_hits"] == 0)
        rules = [f["rule_id"] for f in data["findings"] if f.get("rule_id")]
        results.append({"input": name, "source_sha256": digest(source), "report_sha256": digest(report), "agent_sha": sha,
                        "rules": rules, "run_status": run["status"], "verify_exit": verified,
                        "usable": identity and run["status"] in ("partial", "complete") and verified == 0})
        print(f"{name}: {sha[:7]}, {run['status']}, verify={verified}, rules={rules}")
    write(out / "comparison.json", results)
    return 0 if all(row["usable"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
