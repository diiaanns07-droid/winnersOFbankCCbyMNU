"""Демо пути аналитика на штатном запуске веб-приложения: сервер + браузер + кадры + видео.

    python tests/p15/demo_run.py --out out/p15-demo

Сервер запускается командой из ``DEMO_CMD`` (публичный кейс, записанные ответы модели,
экспорт HTML №13 и PDF №14). Браузерные шаги — tests/p15/e2e_demo.js. Нужны node + playwright,
движок bcc/integration (модули №04–№08) и pymupdf для экспорта PDF.
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
ROOT = HERE.parents[1]
DOC = ROOT / "tests" / "p15" / "fixtures" / "case_ab.md"  # = release/input/requirements.md байт в байт


def demo_cmd(out: Path, port: int) -> list[str]:
    return [sys.executable, "-m", "bcc_review.web",
            "--provider", "mock", "--mock-script", str(HERE / "fixtures" / "mock_case_recorded.json"),
            "--export", "html,pdf", "--demo-answers", str(HERE / "fixtures" / "demo_answers.md"),
            "--data-dir", str(out / "data"), "--cache-dir", str(out / "cache"), "--port", str(port)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=8015)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cmd = demo_cmd(out, args.port)
    (out / "server.cmd").write_text(" ".join(cmd) + "\n", encoding="utf-8")
    server = subprocess.Popen(cmd, stdout=open(out / "server.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/healthz", timeout=1) as r:
                    if not json.load(r)["engine_available"]:
                        raise SystemExit("движок не найден")
                    break
            except OSError:
                time.sleep(0.1)
        env = dict(os.environ)
        npm = shutil.which("npm")
        if npm:
            env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"),
                                                            subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()]))
        run = subprocess.run(["node", str(HERE / "e2e_demo.js"), f"http://127.0.0.1:{args.port}", str(DOC), str(out)],
                             env=env, capture_output=True, text=True, timeout=600)
        result = json.loads((run.stdout.strip().splitlines() or ["{}"])[-1])
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/healthz", timeout=2) as r:
            result["engine_calls"] = json.load(r)["engine_calls"]
    finally:
        server.terminate()
        server.wait(10)
    result["server_cmd"] = " ".join(cmd)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
