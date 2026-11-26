"""Пересобирает образцы №13: HTML и JSON синтетической фикстуры, снимки экрана.

    python tests/p13/make_samples.py

Результат лежит в ``tests/p13/samples/``. Снимки делает Node Playwright, без
него собираются только HTML и JSON.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from bcc_review.exports.html import write_html  # noqa: E402
from fixture_builder import build_report  # noqa: E402
from test_html_browser import _node_env, prepare  # noqa: E402

SAMPLES = HERE / "samples"


def main() -> int:
    SAMPLES.mkdir(exist_ok=True)
    report = build_report()
    (HERE / "fixtures" / "synthetic_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(write_html(report, SAMPLES / "synthetic_report.html"))
    env = _node_env()
    if env is None:
        print("node/playwright не найдены: снимки не обновлены")
        return 0
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shots = work / "shots"
        shots.mkdir()
        prepare(work)
        proc = subprocess.run(["node", str(HERE / "browser" / "check_report.cjs"), str(work), str(shots)], env=env, text=True)
        for name in ("laptop-two-quotes.png", "narrow-quote.png"):
            if (shots / name).exists():
                shutil.copy(shots / name, SAMPLES / name)
                print(SAMPLES / name)
        shutil.copy(work / "results.json", SAMPLES / "browser-results.json")
        return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
