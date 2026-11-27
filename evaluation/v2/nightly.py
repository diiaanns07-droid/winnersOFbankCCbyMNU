"""Ночной живой замер (ворота регрессии, №31): официальный ТЗ в md/pdf/docx × модели × N прогонов без кэша,
стабильность k/N по каждому К и С, чистые наборы на haiku, затем ворота.

    python -m evaluation.v2.nightly --commit $(git rev-parse --short HEAD)               # всё по умолчанию
    python -m evaluation.v2.nightly --models sonnet --fmts md --runs 3 --no-clean --dry-run

По умолчанию: sonnet и haiku, md/pdf/docx, по 3 прогона, 3 параллельно (≈ 25–35 мин, ≈ $12 по ценам API);
Opus не берём (общий лимит подписки). Метки — «ночной <дата> <fmt>: <коммит>, <модель> #k»; сводки стабильности —
`evaluation/v2/stability/nightly_<fmt>_<модель>.json`; логи — `out/nightly/`.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import subprocess
import sys
from pathlib import Path

from .common import ROOT

V2 = ROOT / "evaluation" / "v2"
MEAS = V2 / "measurements"


def slug(label: str) -> str:
    from .measure import slugify

    return slugify(label)


def plan(commit: str, models: list[str], fmts: list[str], runs: int, day: str) -> list[dict]:
    return [{"fmt": f, "model": m, "k": k, "label": f"ночной {day} {f}: {commit}, {m} #{k}"}
            for k in range(1, runs + 1) for m in models for f in fmts]


def measure_cmd(j: dict, timeout: int) -> list[str]:
    return [sys.executable, "-m", "evaluation.v2.measure", "--label", j["label"],
            "--input", f"release/input/requirements.{j['fmt']}", "--provider", "claude_cli",
            "--model", j["model"], "--no-cache", "--timeout", str(timeout)]


def run(cmd: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        return subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.nightly", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--models", nargs="+", default=["sonnet", "haiku"])
    ap.add_argument("--fmts", nargs="+", default=["md", "pdf", "docx"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--no-clean", action="store_true", help="без чистых №20 и open2 на haiku")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if any(m.lower().startswith("opus") for m in a.models):
        print("Opus в ночном замере не берём — общий лимит подписки")
        return 2
    day = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%d.%m")
    jobs = plan(a.commit, a.models, a.fmts, a.runs, day)
    logs = ROOT / "out" / "nightly"
    extra = []
    if not a.no_clean:
        extra.append([sys.executable, "-m", "evaluation.v2.round", "--name", f"ночной {day} чистые", "--official",
                      "--no-corpus", "--no-newtz", "--clean20", "haiku", "--clean-open2", "haiku",
                      "--no-cache-sets", "--label-commit", a.commit])
    if a.dry_run:
        for j in jobs:
            print(" ".join(measure_cmd(j, a.timeout)))
        for c in extra:
            print(" ".join(c))
        return 0
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(run, measure_cmd(j, a.timeout), logs / f"{j['fmt']}_{j['model']}_{j['k']}.log"): j
                for j in jobs}
        for f in cf.as_completed(futs):
            j = futs[f]
            print(f"{j['label']}: rc={f.result()}", flush=True)
    for m in a.models:
        for f in a.fmts:
            scores = [str(MEAS / slug(j["label"]) / "score.json") for j in jobs if j["model"] == m and j["fmt"] == f]
            scores = [s for s in scores if Path(s).exists()]
            if len(scores) >= 2:
                run([sys.executable, "-m", "evaluation.v2.aggregate", "stability", *scores, "--json",
                     str(V2 / "stability" / f"nightly_{f}_{m}.json"), "--label", f"ночной {day} {f}, {m}, {a.commit}"],
                    logs / f"stability_{f}_{m}.log")
    for c in extra:
        run(c, logs / "clean.log")
    return run([sys.executable, "-m", "evaluation.v2.gate", "--save"], logs / "gate.log")


if __name__ == "__main__":
    raise SystemExit(main())
