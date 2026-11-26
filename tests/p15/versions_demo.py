"""Сценарий A/B на обычной точке входа: два запуска сервера, браузер, настоящий движок.

«Вчера» сервер работает с mock-сценарием версии A, «сегодня» — с mock-сценарием версии B
(разные ответы модели для разных документов). Данные запусков общие. Браузерные шаги —
tests/p15/e2e_versions.js.

    python tests/p15/versions_demo.py --out out/p15-versions

Нужны node + playwright и движок bcc_review с модулем правил (bcc/integration 6be9e97+).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSIONS = HERE / "fixtures" / "versions"


def node_env() -> dict[str, str]:
    env = dict(os.environ)
    npm = shutil.which("npm")
    if npm:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
        env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"), root]))
    return env


def serve(day: str, script: Path, args: argparse.Namespace, out: Path) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "bcc_review.web", "--provider", "mock", "--mock-script", str(script),
           "--data-dir", str(out / "data"), "--cache-dir", str(out / "cache"), "--port", str(args.port)]
    (out / f"server-{day}.cmd").write_text(" ".join(cmd) + "\n", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=open(out / f"server-{day}.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/healthz", timeout=1) as r:
                health = json.load(r)
                if not health["engine_available"]:
                    proc.terminate()
                    raise SystemExit(f"движок не найден: {health}")
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit("сервер не поднялся, см. " + str(out / f"server-{day}.log"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8017)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    results = {}
    for day, phase, doc, script in (("yesterday", "a", "A", "mock_A.json"), ("today", "b", "B", "mock_B.json")):
        proc = serve(day, VERSIONS / script, args, out)
        try:
            run = subprocess.run(["node", str(HERE / "e2e_versions.js"), phase, base, str(VERSIONS / doc / "tz.md"), str(out)],
                                 env=node_env(), capture_output=True, text=True, timeout=600)
            results[phase] = json.loads((run.stdout.strip().splitlines() or ["{}"])[-1])
            if run.returncode != 0:
                print(json.dumps(results[phase], ensure_ascii=False, indent=1))
                return 1
        finally:
            proc.terminate()
            proc.wait(10)
    b = results["b"]
    summary = {
        "run_a": b["run_a"], "run_b": b["run_b"], "child": b["child"],
        "foreign": b["foreign"], "own": b["own"], "repeat": b["repeat"], "html13": b["html13"],
        "commands": [(out / f"server-{d}.cmd").read_text(encoding="utf-8").strip() for d in ("yesterday", "today")],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
