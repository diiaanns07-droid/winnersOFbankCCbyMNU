import json, sys, glob
from pathlib import Path
sys.path.insert(0, ".")
from evaluation.v2 import score as sc
g = sc.load_gold("evaluation/v2/official/gold.yaml")
items = {it["id"]: it for it in g["items"]}
lines = sc.load_doc(sc.ROOT / g["document"])
paths = sys.argv[1:] or sorted(glob.glob("evaluation/v2/measurements/*/report.json"))
for p in paths:
    rep = json.load(open(p))
    if rep.get("document", {}).get("sha256") != g["sha256"]:
        continue
    res = sc.score_report(rep, g, report_md=None, run_dir=None, arbiter="off",
                          cache_path=Path("evaluation/v2/official/arbiter_cache.jsonl"))
    got = {x["gold"] for x in res["assignment"]}
    fs = {f["id"]: f for f in sc.normalize_findings(rep)}
    extra = []
    for d in res["duplicates"]:
        f = fs[d["finding"]]
        f["_lines"], _ = sc.finding_lines(f, lines, True)
        f["_text"] = (f["title"] + " " + f["text"]).replace("ё", "е"); f["_title"] = f["title"].replace("ё", "е")
        for gid, it in items.items():
            if gid in got or gid in [e[0] for e in extra]:
                continue
            if sc.pair_info(it, f)["status"] == "match":
                extra.append((gid, d["finding"], d["gold"], f["title"][:70])); break
    S = sorted(x for x in got if x.startswith("С"))
    print(Path(p).parent.name, f"С {len(S)} →", len(S) + sum(1 for e in extra if e[0].startswith("С")), extra)
