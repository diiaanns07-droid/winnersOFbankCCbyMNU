"""Полный прогон с опциями этапа набора (№09), которых нет в командной строке, — для замера «до/после».

    python tests/v2/fixtures/09_tools/full_run.py ДОКУМЕНТ ОТЧЁТ.md --model haiku [--split] [--fast-start] [--no-cache]

Пишет отчёт и печатает время, вызовы и время этапов (по ``runs/<id>/stages/*.json``).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import pipeline  # noqa: E402
from bcc_review.v2.stages import consistency  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--provider", default="claude_cli")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--fast-start", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    opts = {"provider": a.provider, "model": a.model, "cache": not a.no_cache, "fast_start": a.fast_start,
            consistency.SPLIT_OPTION: a.split, "quiet": True, "run_id": a.run_id}
    t0 = time.monotonic()
    report, _ = pipeline.review(a.input, a.output, opts)
    run = report.get("run") or {}
    print(json.dumps({"seconds": round(time.monotonic() - t0, 1), "status": run.get("status"),
                      "calls": (run.get("llm") or {}).get("calls", run.get("calls")),
                      "run_dir": run.get("run_dir") or run.get("id"),
                      "findings": len(report.get("findings") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
