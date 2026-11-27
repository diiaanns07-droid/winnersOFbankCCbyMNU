"""Re-run the nine public new-conflict candidates through the checked-out duplicate filter."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expect", choices=("old", "patched"), required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "src"))
    from bcc_review.v2.stages.recheck import duplicate_of

    data = Path(__file__).resolve().parent
    rows = json.loads((data / "owner-conflicts-replay.json").read_text(encoding="utf-8"))
    forwarded = 0
    for row in rows:
        series = "" if row["series"] == "first" else row["series"]
        source = data.parent / "answers_exam" / series / row["document"] / "answered.json"
        findings = json.loads(source.read_text(encoding="utf-8"))["findings_before"]
        actual = duplicate_of(row["evidence"], findings, row["title"])
        expected = row[args.expect + "_duplicate"]
        if actual != expected:
            raise ValueError(f"{row['series']}/{row['document']}: expected {expected!r}, got {actual!r}")
        forwarded += not actual
    print(f"Passed to subsequent checks: {forwarded}/{len(rows)}")


if __name__ == "__main__":
    main()
