"""Оценка сырых ответов линзы (bench.py) текущей постобработкой stages/lens_risk.py.

python evalb.py TAG[,TAG2] [--model sonnet] [-v]
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path("/home/user/winnersOFbankCCbyMNU")
S = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from bcc_review.v2 import docview  # noqa: E402
import bcc_review.v2.stages.lens_risk as LR  # noqa: E402
from evaluation.v2 import score as sc  # noqa: E402
from bench import doc_path, OPEN2, OPEN2_CLEAN, CLEAN_CORPUS, MUT_CORPUS, CORPUS, CLEAN2  # noqa: E402

SEV = ("critical", "major", "minor")


def counts(cands):
    return "/".join(str(sum(1 for c in cands if c.get("severity") == s)) for s in SEV)


def gold_for(name):
    if name == "official":
        g = sc.load_gold(sc.DEFAULT_GOLD)
        cache = sc.DEFAULT_CACHE
    else:
        p = S / "open2" / name / "gold.yaml"
        g = sc.load_gold(p)
        g["document"] = str(S / "open2" / name / "source.md")
        cache = ROOT / "evaluation/v2/open2" / name / "arbiter_cache.jsonl"
    return g, cache


def score(name, kept):
    g, cache = gold_for(name)
    rep = sc.as_report({"candidates": kept}, g)
    with redirect_stdout(io.StringIO()):
        res = sc.score_report(rep, g, arbiter="off", cache_path=Path(cache))
    # «свои» — по эталону без чужих critical: в счёте только по линзе замечание линзы с общей строкой уходит чужому
    # critical (паросочетание берёт critical первыми), хотя в полном прогоне его даёт владелец
    g2 = dict(g, items=[it for it in g["items"] if it["level"] != "critical" or "risk" in it.get("owners", [])])
    with redirect_stdout(io.StringIO()):
        res2 = sc.score_report(sc.as_report({"candidates": kept}, g2), g2, arbiter="off", cache_path=Path(cache))
    found_own = {a["gold"] for a in res2["assignment"]}
    found = {a["gold"]: a for a in res["assignment"]}
    mine = [it for it in g["items"] if "risk" in it.get("owners", [])]
    crit_items = [it["id"] for it in g["items"] if it["level"] == "critical"]
    as_crit = res["recall"]["critical"]["as_critical"]
    return {
        "mine": f"{sum(1 for it in mine if it['id'] in found_own)}/{len(mine)}",
        "mine_missing": [it["id"] for it in mine if it["id"] not in found_own],
        "found_all": sorted(found),
        "crit_found": [i for i in crit_items if i in found],
        "as_crit": as_crit,
        "crit_false": [x.get("finding") or x for x in res["severity"]["critical_false"]],
        "assign": {a["gold"]: a.get("finding") for a in res["assignment"]},
    }


def mut_hit(name, kept, view):
    mj = json.loads((CORPUS / name / "mutation.json").read_text(encoding="utf-8"))
    lines = sc.load_doc(doc_path(name))
    hits = []
    for lab in mj["labels"]:
        need = []
        for an in lab["anchors"]:
            loc = sc.locate(lines, an["quote"])
            need.append(set(range(loc["line_start"], loc["line_end"] + 1)) if loc else {int(an["locator"].split("L")[-1])})
        for c in kept:
            got = set()
            for e in c.get("evidence") or []:
                loc = sc.locate(lines, e.get("quote", ""), e.get("line"))
                if loc:
                    got |= set(range(loc["line_start"], loc["line_end"] + 1))
            if all(n & got for n in need):
                hits.append((c.get("severity"), c.get("title", "")[:90]))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    importlib.reload(LR)
    for tag in a.tags.split(","):
        print(f"\n===== {tag} / {a.model}")
        tot = {"time": 0.0, "calls": 0}
        clean_sum = []
        for f in sorted((S / "bench" / tag).glob(f"*.{a.model}.raw.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            name = rec["doc"]
            view = docview.load(str(doc_path(name)))
            reqs = rec["requirements"]
            known = [r["id"] for r in reqs]
            accept = [r["id"] for r in reqs if r.get("kind") == "acceptance"]
            kept, dropped = LR.postprocess(rec["candidates"], view, known, accept)
            st = rec["stats"]
            head = (f"{name:42s} {rec['seconds']:6.1f}s c={st.get('calls')}{'/cache' if st.get('cached') else ''} "
                    f"out={st.get('tokens_out')} raw={len(rec['candidates'])} kept={counts(kept)}")
            if name == "official" or name in OPEN2:
                r = score(name, kept)
                head += f"  mine={r['mine']} miss={r['mine_missing']} K={r['crit_found']} Kcrit={r['as_crit']} crit_false={r['crit_false']}"
            elif name in MUT_CORPUS:
                head += f"  hit={mut_hit(name, kept, view)}"
            else:
                clean_sum.append(kept)
            print(head + (f"  ERR {rec['error'][:60]}" if rec["error"] else ""))
            if a.v or name in OPEN2_CLEAN + CLEAN_CORPUS + CLEAN2:
                for c in kept:
                    print(f"     + {c.get('severity'):8s} {c.get('kind',''):16s} {c.get('title','')[:120]}")
            if a.v:
                for c in dropped:
                    print(f"     - {c.get('severity'):8s} {c.get('title','')[:100]}  [{c.get('reject_reason')}]")
        if clean_sum:
            n = [len(k) for k in clean_sum]
            cr = sum(1 for k in clean_sum for c in k if c.get("severity") == "critical")
            print(f"  CLEAN: docs={len(n)} total={sum(n)} per-doc={n} critical={cr} docs>1={sum(1 for x in n if x > 1)}")


if __name__ == "__main__":
    main()
