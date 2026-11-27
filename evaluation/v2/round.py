"""Замер по расписанию одной командой: официальный документ (sonnet, haiku, по желанию Opus), корпус (haiku),
новые ТЗ №18 (sonnet), затем ворота. Части идут параллельно, каждая — своим процессом с логом.

    python -m evaluation.v2.round --name "замер 07:00"                        # всё по умолчанию
    python -m evaluation.v2.round --name "замер 11:00" --official sonnet haiku opus --no-corpus
    python -m evaluation.v2.round --name "стабильность sonnet" --official sonnet sonnet sonnet --no-cache \\
        --no-corpus --no-newtz                                                 # 3 прогона без кэша + сводка
    python -m evaluation.v2.round --name "свежие чистые" --official --no-corpus --no-newtz --clean20 haiku \
        --no-cache-sets                                                        # чистые наборы мимо кэша

Без `--no-cache-sets` корпус, новые ТЗ и чистые наборы берут ответы модели из кэша: если промпты не менялись,
это повтор старых ответов через новый код (0 вызовов), а не новая выборка — `final` помечает такие строки.

Сначала — официальный документ (его прогоны параллельно между собой), потом наборы: время официального — цель ворот
(sonnet ≤ 3 мин), а 12 одновременных процессов `claude` того же аккаунта растягивают его (кандидат 868787d в 18:00:
2,9 и 3,3 мин против 2,4 мин в 17:46). `--together` — всё сразу, как раньше. Агент упёрся в лимит подписки на
официальном — наборы не запускаются (они упрутся в тот же лимит и только сожгут его остаток у других сессий).

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

from .common import ROOT, shell_quote
from .measure import MEAS, slugify


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          cwd=str(ROOT)).stdout.strip() or "?"


def _agent_tpl(runs: Path, no_cache: bool = False) -> str:
    """Шаблон команды агента для corpus/newtz: свой --runs-dir, по желанию мимо кэша ответов модели."""
    return ("{python} -m bcc_review {input} {output} --provider {provider} --model {model} -q "
            f"--runs-dir {shell_quote(runs)}" + (" --no-cache" if no_cache else ""))


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
        cmd_tpl = _agent_tpl(o / "runs", getattr(a, "no_cache_sets", False))
        out.append((name, [py, "-m", "evaluation.v2.newtz", "run", "--out", str(o), "--root", str(root),
                           "--cases", *cases, "--provider", "claude_cli", "--model", model, "--cmd", cmd_tpl,
                           "--jobs", str(getattr(a, "clean_jobs", 2)), "--label", f"{a.name}: {title}, {sha}, {model}",
                           "--save"]))
    return out


def run_waves(jobs: list[tuple[str, list[str]]], logs: Path, together: bool = False) -> dict[str, int]:
    """Запустить части раунда: сначала официальный документ (его прогоны — параллельно), затем наборы; с
    ``together`` — всё сразу. Официальный упёрся в лимит подписки — наборы не запускаются (код 3)."""
    t0 = time.monotonic()
    first = [j for j in jobs if j[0].startswith("official_")]
    waves = [jobs] if together or not first else [first, [j for j in jobs if j not in first]]
    rcs: dict[str, int] = {}
    for i, wave in enumerate(waves):
        if not wave:
            continue
        if i and quota_in_logs(logs, [n for n, _ in waves[0]]):
            print("агент упёрся в лимит подписки на официальном документе — наборы не запускаю: "
                  + ", ".join(n for n, _ in wave), flush=True)
            rcs.update({n: 3 for n, _ in wave})
            break
        procs = {name: subprocess.Popen(cmd, cwd=str(ROOT), stdout=(logs / f"{name}.log").open("w", encoding="utf-8"),
                                        stderr=subprocess.STDOUT) for name, cmd in wave}
        for name, proc in procs.items():
            rcs[name] = proc.wait()
            print(f"[{name}] rc={rcs[name]} ({(time.monotonic() - t0) / 60:.1f} мин)", flush=True)
    return rcs


def quota_in_logs(logs: Path, names: list[str]) -> bool:
    """В логе части раунда — отказ `measure` из-за лимита провайдера или сама ошибка лимита подписки агента."""
    for n in names:
        try:
            text = (logs / f"{n}.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "упёрся в лимит провайдера" in text or "Исчерпан лимит подписки" in text:
            return True
    return False


def same_code_scores(model: str, labels: list[str]) -> list[str]:
    """score.json прошлых прогонов модели на том же коде, что прогоны этого раунда с метками ``labels``."""
    from .gate import HISTORY, _read_jsonl, model_kind, same_code_rows

    rows = [r for r in _read_jsonl(HISTORY) if r.get("version") == "v2"]
    last = next((r for r in reversed(rows) if r.get("label") in labels), None)
    if not last:
        return []
    out = []
    for r in same_code_rows(rows, model_kind(last.get("provider"), last.get("model")), last):
        p = ROOT / str(r.get("dir") or "") / "score.json"
        if r.get("dir") and r.get("label") not in labels and p.exists() and str(p) not in out:
            out.append(str(p))
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
    ap.add_argument("--clean-jobs", type=int, default=2, help="параллельных документов в чистых наборах")
    ap.add_argument("--label-commit", help="коммит в метках вместо HEAD (замер на коммите интеграции)")
    ap.add_argument("--no-cache", action="store_true", help="официальный документ мимо кэша (стабильность)")
    ap.add_argument("--no-cache-sets", action="store_true",
                    help="корпус, новые ТЗ и чистые наборы мимо кэша — новая выборка ответов, а не повтор")
    ap.add_argument("--arbiter", default="sonnet")
    ap.add_argument("--together", action="store_true",
                    help="официальный документ и наборы одновременно (быстрее, но время официального — под нагрузкой)")
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
        cmd_tpl = _agent_tpl(out / "runs", a.no_cache_sets)
        jobs.append(("corpus", [py, "-m", "evaluation.v2.corpus", "run", "--out", str(out), "--provider", "claude_cli",
                                "--model", a.corpus_model, "--cmd", cmd_tpl, "--jobs", str(a.corpus_jobs),
                                "--label", f"{a.name}: {sha}, {a.corpus_model}", "--save"]))
    if not a.no_newtz:
        from .newtz import OPEN2, discover

        if [c for c in discover(OPEN2) if c["variant"] != "error"]:
            out = logs / "newtz"
            cmd_tpl = _agent_tpl(out / "runs", a.no_cache_sets)
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
    rcs = run_waves(jobs, logs, a.together)
    # стабильность: прогоны модели в этом раунде и раньше на том же коде (деревья src/ по git, без повторов из кэша)
    for m in sorted({m for m, _ in labels}):
        paths = [str(MEAS / slugify(lb) / "score.json") for mm, lb in labels if mm == m]
        paths = [p for p in paths if Path(p).exists()]
        earlier = [p for p in same_code_scores(m, [lb for mm, lb in labels if mm == m]) if p not in paths]
        paths = earlier + paths
        if len(paths) >= 2:
            dest = ROOT / "evaluation" / "v2" / "stability" / f"{slugify(a.name)}_{m}.json"
            note = f" (с прошлыми на этом коде: {len(earlier)})" if earlier else ""
            subprocess.run([py, "-m", "evaluation.v2.aggregate", "stability", *paths, "--json", str(dest),
                            "--label", f"{a.name}: {sha}, {m} ×{len(paths)}{note}"], cwd=str(ROOT))
    subprocess.run([py, "-m", "evaluation.v2.aggregate", "models", "--auto", "--write"], cwd=str(ROOT))
    subprocess.run([py, "-m", "evaluation.v2.gate", "--save"], cwd=str(ROOT))
    (logs / "round.json").write_text(json.dumps({"name": a.name, "commit": sha, "rc": rcs,
                                                 "minutes": round((time.monotonic() - t0) / 60, 1)},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(v == 0 for v in rcs.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
