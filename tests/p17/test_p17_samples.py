"""Образцы в tests/p17/samples совпадают с тем, что генерирует текущий код."""

from __future__ import annotations

import csv
import json

from p17_make_samples import SAMPLES, VARIANTS, build_files

from bcc_review import contracts as C
from bcc_review.exports.markdown import check_markdown


def test_samples_are_up_to_date():
    files = build_files()
    stale = [n for n, data in files.items() if not (SAMPLES / n).exists() or (SAMPLES / n).read_bytes() != data]
    assert not stale, f"перегенерируйте: python tests/p17/p17_make_samples.py ({stale})"


def test_each_sample_valid_and_reconciles_from_disk():
    for key, *_ in VARIANTS:
        report = json.loads((SAMPLES / key / "report.json").read_text(encoding="utf-8"))
        C.validate(report)
        assert C.evidence_errors(report) == []
        assert check_markdown(SAMPLES / key / "report.md", report) == []
        with open(SAMPLES / key / "report.jira.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        md = (SAMPLES / key / "report.md").read_text(encoding="utf-8")
        marker = json.loads(md.split("bcc-review:summary ", 1)[1].split(" -->")[0])
        assert len(rows) == marker["defects_unique"]
