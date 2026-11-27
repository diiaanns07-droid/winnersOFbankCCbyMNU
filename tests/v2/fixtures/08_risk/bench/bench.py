"""Стенд линзы «Риски»: сырой ответ модели на наборе документов (без постобработки) + время/вызовы/токены.

python bench.py --model sonnet --tag before --docs all --jobs 4 [--no-cache] [--effort low]
Сырые ответы — bench/<tag>/<doc>.<model>.raw.json; оценку делает evalb.py (постобработка текущим кодом).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path("/home/user/winnersOFbankCCbyMNU")
S = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from bcc_review.v2 import docview, rules  # noqa: E402
from bcc_review.v2.context import Context  # noqa: E402
from bcc_review.v2.pipeline import make_llm  # noqa: E402
from bcc_review.v2.stages import lens, segment  # noqa: E402

CORPUS = ROOT / "evaluation/dev/corpus/cases"
FIX = ROOT / "tests/v2/fixtures"

CLEAN_CORPUS = ["autopay.base", "cardblock.base", "cashback.base", "transfer_limit.base",
                "autopay.paraphrase.nfr", "cardblock.paraphrase.keep_authorizations", "cashback.paraphrase.rate",
                "transfer_limit.paraphrase.new_limit"]
MUT_CORPUS = ["cardblock.unit_change.blocked_at_utc", "transfer_limit.event_conflict.cancel_no_restore",
              "cardblock.event_conflict.unblock_daily_limit", "cashback.event_conflict.category_effective_now"]
OPEN2 = ["grace", "qr", "capital", "insurance", "insurance_inject"]
OPEN2_CLEAN = ["grace_clean", "qr_clean", "capital_clean", "insurance_clean"]
GROUPS = {"official": ["official"], "clean": CLEAN_CORPUS, "mut": MUT_CORPUS, "open2": OPEN2,
          "open2c": OPEN2_CLEAN}
GROUPS["all"] = sum(GROUPS.values(), [])
GROUPS["fast"] = ["official"] + CLEAN_CORPUS[:4] + OPEN2 + OPEN2_CLEAN


def doc_path(name: str) -> Path:
    if name == "official":
        return ROOT / "release/input/requirements.md"
    if name in OPEN2 + OPEN2_CLEAN:
        return S / "open2" / name / "source.md"
    return CORPUS / name / "source.md"


def requirements(name: str, view: dict) -> list[dict]:
    seg = FIX / name / "segment.json"
    if name == "official":
        seg = FIX / "official/segment.json"
    if seg.exists():
        return json.loads(seg.read_text(encoding="utf-8"))["requirements"]
    cache = S / "seg" / f"{name}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    reqs = segment.heuristic_segment(view)["requirements"]
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(reqs, ensure_ascii=False), encoding="utf-8")
    return reqs


def run_one(name: str, a) -> dict:
    out_path = S / "bench" / a.tag / f"{name}.{a.model}.raw.json"
    if out_path.exists() and not a.force:
        return json.loads(out_path.read_text(encoding="utf-8"))
    view = docview.load(str(doc_path(name)))
    reqs = requirements(name, view)
    sig = rules.run(view, reqs).get("signals", [])
    opts = {"provider": "claude_cli", "model": a.model, "cache": not a.no_cache,
            "cache_dir": str(S / "cache"), "max_calls": 4, "max_seconds": 1500, "max_retries": 2,
            "timeout": 600, "stage_timeout": 480, "rpm": 0, "effort": a.effort}
    llm, _ = make_llm(opts, None, None)
    ctx = Context(view=view, llm=llm, options=opts, requirements=reqs, signals=sig)
    t0 = time.monotonic()
    err = ""
    try:
        data = lens.run(ctx, "risk")
    except Exception as exc:  # noqa: BLE001
        data, err = {"candidates": []}, f"{type(exc).__name__}: {exc}"
    rec = {"doc": name, "model": a.model, "seconds": round(time.monotonic() - t0, 1), "error": err,
           "stats": {k: v for k, v in llm.stats.items() if k in ("calls", "cached", "failed", "split", "tokens_in",
                                                                  "tokens_out")},
           "candidates": data.get("candidates", []), "requirements": reqs}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--docs", default="fast")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--effort", default=None)
    a = ap.parse_args()
    names = []
    for part in a.docs.split(","):
        names += GROUPS.get(part, [part])
    with ThreadPoolExecutor(a.jobs) as ex:
        for rec in ex.map(lambda n: run_one(n, a), names):
            st = rec["stats"]
            print(f"{rec['doc']:45s} {rec['seconds']:6.1f}s calls={st.get('calls')} cached={st.get('cached')} "
                  f"split={st.get('split')} out={st.get('tokens_out')} cands={len(rec['candidates'])} {rec['error'][:80]}",
                  flush=True)


if __name__ == "__main__":
    main()
