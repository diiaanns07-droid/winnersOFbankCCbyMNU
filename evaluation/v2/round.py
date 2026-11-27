"""Замер по расписанию одной командой: официальный документ (sonnet, haiku, по желанию Opus), корпус (haiku),
новые ТЗ №18 (sonnet), затем ворота. Части идут параллельно, каждая — своим процессом с логом.

    python -m evaluation.v2.round --name "замер 07:00"                        # всё по умолчанию
    python -m evaluation.v2.round --name "замер 11:00" --official sonnet haiku opus --no-corpus
    python -m evaluation.v2.round --name "стабильность sonnet" --official sonnet sonnet sonnet --no-cache \\
        --no-corpus --no-newtz                                                 # 3 прогона без кэша + сводка

Метки замеров: «<name>: <коммит>, <модель>» (повтор модели — «… #2»). Логи — `out/round/<slug>/*.log`.
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import time
from pathlib import Path

from .common import ROOT
from .measure import MEAS, slugify


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          cwd=str(ROOT)).stdout.strip() or "?"


def _clean_jobs(a, py: str, logs: Path, sha: str) -> list[tuple[str, list[str]]]:
    """Чистые наборы отдельными частями: open2 (только `variant: clean`) и №20 (`evaluation/v2/clean`)."""
    from .newtz import OPEN2, discover

    out = []
    sets = []
    if a.clean_open2:
        found = discover(OPEN2)
        # только кейсы, где все варианты чистые (иначе --cases запустил бы и дефектную версию)
        cases = sorted({c["case"] for c in found if c["variant"] == "clean"}
                       - {c["case"] for c in found if c["variant"] != "clean"})
        if cases:
            sets.append(("clean_open2", a.clean_open2, OPEN2, cases, "чистые open2"))
        else:
            print("чистых версий в evaluation/v2/open2 нет — пропускаю")
    if a.clean20:
        root = ROOT / "evaluation" / "v2" / "clean"
        cases = sorted({c["case"] for c in discover(root) if c["variant"] != "error"})
        if cases:
            sets.append(("clean20", a.clean20, root, cases, "чистые №20"))
        else:
            print("набора evaluation/v2/clean нет (№20 не влит?) — пропускаю")
    for name, model, root, cases, title in sets:
        o = logs / name
        cmd_tpl = ("{python} -m bcc_review {input} {output} --provider {provider} --model {model} -q "
                   f"--runs-dir {o / 'runs'}")
        out.append((name, [py, "-m", "evaluation.v2.newtz", "run", "--out", str(o), "--root", str(root),
                           "--cases", *cases, "--provider", "claude_cli", "--model", model, "--cmd", cmd_tpl,
                           "--jobs", "2", "--label", f"{a.name}: {title}, {sha}, {model}", "--save"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.round", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--official", nargs="*", default=["sonnet", "haiku"], help="модели для официального документа")
    ap.add_argument("--corpus-model", default="haiku")
    ap.add_argument("--corpus-jobs", type=int, default=3)
    ap.add_argument("--no-corpus", action="store_true")
    ap.add_argument("--newtz-model", default="sonnet")
    ap.add_argument("--no-newtz", action="store_true")
    ap.add_argument("--clean-open2", metavar="MODEL",
                    help="отдельно — только чистые версии open2 (№18) этой моделью, например haiku")
    ap.add_argument("--clean20", metavar="MODEL",
                    help="отдельно — 8 чистых ТЗ №20 (evaluation/v2/clean) этой моделью, например haiku")
    ap.add_argument("--label-commit", help="коммит в метках вместо HEAD (замер на коммите интеграции)")
    ap.add_argument("--no-cache", action="store_true", help="официальный документ мимо кэша (стабильность)")
    ap.add_argument("--arbiter", default="sonnet")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sha = a.label_commit or _commit()
    slug = slugify(a.name)
    logs = ROOT / "out" / "round" / slug
    logs.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    jobs: list[tuple[str, list[str]]] = []
    seen: collections.Counter = collections.Counter()
    labels = []
    for m in a.official:
        seen[m] += 1
        label = f"{a.name}: {sha}, {m}" + (f" #{seen[m]}" if a.official.count(m) > 1 else "")
        labels.append((m, label))
        runs_dir = logs / "runs"
        cmd = [py, "-m", "evaluation.v2.measure", "--label", label, "--provider", "claude_cli", "--model", m,
               "--arbiter", a.arbiter, f"--extra=--runs-dir {runs_dir}"]
        if a.no_cache:
            cmd.append("--no-cache")
        jobs.append((f"official_{m}_{seen[m]}", cmd))
    if not a.no_corpus:
        out = logs / "corpus"
        cmd_tpl = ("{python} -m bcc_review {input} {output} --provider {provider} --model {model} -q "
                   f"--runs-dir {out / 'runs'}")
        jobs.append(("corpus", [py, "-m", "evaluation.v2.corpus", "run", "--out", str(out), "--provider", "claude_cli",
                                "--model", a.corpus_model, "--cmd", cmd_tpl, "--jobs", str(a.corpus_jobs),
                                "--label", f"{a.name}: {sha}, {a.corpus_model}", "--save"]))
    if not a.no_newtz:
        from .newtz import OPEN2, discover

        if [c for c in discover(OPEN2) if c["variant"] != "error"]:
            out = logs / "newtz"
            cmd_tpl = ("{python} -m bcc_review {input} {output} --provider {provider} --model {model} -q "
                       f"--runs-dir {out / 'runs'}")
            jobs.append(("newtz", [py, "-m", "evaluation.v2.newtz", "run", "--out", str(out), "--provider", "claude_cli",
                                   "--model", a.newtz_model, "--cmd", cmd_tpl, "--jobs", "2",
                                   "--label", f"{a.name}: {sha}, {a.newtz_model}", "--save"]))
        else:
            print("новых ТЗ в evaluation/v2/open2 нет — пропускаю")
    jobs += _clean_jobs(a, py, logs, sha)
    for name, cmd in jobs:
        print(f"[{name}] {' '.join(cmd)}")
    if a.dry_run:
        return 0
    t0 = time.monotonic()
    procs = {name: subprocess.Popen(cmd, cwd=str(ROOT), stdout=(logs / f"{name}.log").open("w", encoding="utf-8"),
                                    stderr=subprocess.STDOUT) for name, cmd in jobs}
    rcs = {}
    for name, p in procs.items():
        rcs[name] = p.wait()
        print(f"[{name}] rc={rcs[name]} ({(time.monotonic() - t0) / 60:.1f} мин)", flush=True)
    # несколько прогонов одной модели — сводка стабильности
    for m in sorted({m for m, _ in labels if a.official.count(m) > 1}):
        paths = [str(MEAS / slugify(lb) / "score.json") for mm, lb in labels if mm == m]
        paths = [p for p in paths if Path(p).exists()]
        if len(paths) >= 2:
            dest = ROOT / "evaluation" / "v2" / "stability" / f"{slugify(a.name)}_{m}.json"
            subprocess.run([py, "-m", "evaluation.v2.aggregate", "stability", *paths, "--json", str(dest),
                            "--label", f"{a.name}: {sha}, {m} ×{len(paths)}"], cwd=str(ROOT))
    subprocess.run([py, "-m", "evaluation.v2.aggregate", "models", "--auto", "--write"], cwd=str(ROOT))
    subprocess.run([py, "-m", "evaluation.v2.gate", "--save"], cwd=str(ROOT))
    (logs / "round.json").write_text(json.dumps({"name": a.name, "commit": sha, "rc": rcs,
                                                 "minutes": round((time.monotonic() - t0) / 60, 1)},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(v == 0 for v in rcs.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
