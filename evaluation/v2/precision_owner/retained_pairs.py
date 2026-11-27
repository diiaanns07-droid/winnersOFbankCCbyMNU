"""Проверка сохранённых сравнений двух цитат из 12 прогонов №31."""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import subprocess
import sys

SNAPSHOT = "05306ab55f5d08b0306e62ae283277e527881202"
BATCH = "evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()
    sys.path.insert(0, str(tree / "src"))
    from bcc_review.v2.pipeline import load_view
    from bcc_review.v2.stages import consistency

    def git(*parts):
        return subprocess.check_output(["git", *parts], cwd=tree)

    def saved(path):
        return json.loads(git("show", f"{SNAPSHOT}:{path}"))

    folders = git("ls-tree", "-r", "--name-only", SNAPSHOT, BATCH).decode().splitlines()
    results = []
    for stage in (s for s in folders if s.endswith("/stages/consistency.json")):
        document = stage.split("/")[-3].removesuffix("__clean")
        sample = "open2" if document.endswith("_clean") else "clean"
        source = f"evaluation/v2/{sample}/{document}/source.md"
        before = saved(stage)["output"]
        segment = saved(stage.replace("consistency.json", "segment.json"))["output"]
        # На Windows checkout преобразует окончания строк. Проверяем содержимое Git.
        report = saved(stage.removesuffix("stages/consistency.json") + "report.json")
        original = git("show", f"{SNAPSHOT}:{source}")
        if sha256(original).hexdigest() != report["document"]["sha256"]:
            raise ValueError(f"SHA-256 исходника паспорта не совпал для {document}")
        if original.decode("utf-8-sig").splitlines() != (tree / source).read_text(encoding="utf-8-sig").splitlines():
            raise ValueError(f"Другая редакция документа {document}")
        view = load_view(tree / source)
        known = consistency._req_index(segment["requirements"])
        for raw in before["pair_checks"]:
            pair = consistency.normalize_pair(raw, view, known)
            candidate = consistency.pair_to_candidate(pair, known)
            results.append({"case": document, "pair": raw["id"], "source": source,
                            "lines": [raw["line_a"], raw["line_b"]], "published": raw["verdict"],
                            "verdict": pair["verdict"], "severity": candidate["severity"] if candidate else None})
    out = {"code": git("rev-parse", "HEAD").decode().strip(), "recorded": SNAPSHOT, "pairs": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
