"""Воспроизведение: зависит ли результат счётчика от порядка строк предсказаний."""
import itertools, json, sys
sys.path.insert(0, ".")
from evaluation.harness.schema import parse_gold, parse_predictions, read_jsonl
from evaluation.harness.score import score
from evaluation.harness.taxonomy import Taxonomy
from evaluation.harness import __version__
T = Taxonomy.load(); D = "evaluation/harness/controls/robustness/"
g, p = read_jsonl(D + "labels.jsonl"), read_jsonl(D + "predictions.jsonl")
runs = [r for r in p if r["record"] == "run"]; finds = [r for r in p if r["record"] == "finding"]
for policy in ("hierarchy", "exact"):
    micro, pairs, fporder = set(), {}, set()
    for perm in itertools.permutations(finds):
        m = score(parse_gold(g, T), *parse_predictions(runs + list(perm), T), T, type_match=policy)
        micro.add(json.dumps({k: m["micro"][k] for k in ("tp", "fp", "fn", "duplicates", "precision", "recall")}))
        key = (tuple(sorted((t["label_id"], t["defect_id"]) for t in m["true_positives"])),
               tuple(sorted(d["defect_id"] for d in m["duplicates"])))
        pairs[key] = pairs.get(key, 0) + 1
        fporder.add(tuple(f["defect_id"] for f in m["false_positives"]))
    print(f"harness {__version__} | {policy}: перестановок 120, разных micro={len(micro)} {sorted(micro)[0]}")
    for k, n in pairs.items():
        print(f"   TP {dict(k[0])}  дубль {list(k[1])}: {n} перестановок")
    print(f"   разных порядков списка FP: {len(fporder)}")
