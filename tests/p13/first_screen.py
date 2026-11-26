"""Первый экран аналитика: два локальных HTML из одной версии генератора №13.

    python tests/p13/first_screen.py OUTDIR [--record]

* ``OUTDIR/requirements_pdf.html`` — реальный офлайн-отчёт релиза
  ``release/reports/offline/requirements_pdf.json`` (run.status = partial);
* ``OUTDIR/conflict_same_amount.html`` — записанный пример ``fixtures/conflict_same_amount.report.json``:
  вход ``fixtures/conflict_same_amount.md``, прогон движка с записанным ответом модели
  ``fixtures/conflict_same_amount.mock.json``. Критичный конфликт F-001: обе цитаты начинаются
  с одинаковых сумм «Порог 50 000 ₸, расходы 50 000 ₸», первое вхождение этого текста — в другой таблице.

``--record`` заново записывает ``conflict_same_amount.report.json`` прогоном
``python -m bcc_review … --provider mock --mock-script …`` (этапы individual/cross — записанный
ответ, остальное — модули команды). Без флага берётся сохранённая запись: результат не зависит
от сети и ключей.

Пишет ``OUTDIR/first-screen.json``: пути, SHA-256 входов, отпечаток генератора и якоря.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src")]

from bcc_review.exports import html as H  # noqa: E402

RELEASE_JSON = ROOT / "release" / "reports" / "offline" / "requirements_pdf.json"
EXAMPLE_MD = HERE / "fixtures" / "conflict_same_amount.md"
EXAMPLE_MOCK = HERE / "fixtures" / "conflict_same_amount.mock.json"
EXAMPLE_JSON = HERE / "fixtures" / "conflict_same_amount.report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_example() -> Path:
    """Прогон движка на записанном ответе модели; результат — fixtures/conflict_same_amount.report.json."""
    env = dict(os.environ, BCC_FORCE_FALLBACK="review_individual,review_set")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src")] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "conflict_same_amount.md"
        subprocess.run(
            [sys.executable, "-m", "bcc_review", str(EXAMPLE_MD), str(out), "--provider", "mock",
             "--mock-script", str(EXAMPLE_MOCK), "--no-cache", "-q"],
            env=env, check=True, cwd=str(ROOT),
        )
        shutil.copyfile(out.with_suffix(".json"), EXAMPLE_JSON)
    return EXAMPLE_JSON


def conflict_anchors(report: dict) -> dict:
    crit = next(f for f in report["findings"] if f["severity"] == "critical" and f.get("witness"))
    w = crit["witness"]
    return {
        "finding": "#" + H.finding_anchor(crit["id"]),
        "quote_a_block": "#" + H.block_anchor(w["evidence_a"]["block_id"]),
        "quote_b_block": "#" + H.block_anchor(w["evidence_b"]["block_id"]),
    }


def build(outdir: Path, *, record: bool = False) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    if record or not EXAMPLE_JSON.is_file():
        record_example()
    if not RELEASE_JSON.is_file():
        raise SystemExit(f"нет {RELEASE_JSON.relative_to(ROOT)}: нужна ветка с release/ (bcc/integration @ 2821989 или новее)")
    first = H.write_html(RELEASE_JSON, outdir / "requirements_pdf.html")
    second = H.write_html(EXAMPLE_JSON, outdir / "conflict_same_amount.html")
    example = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    common = ["#summary", "#verdict-development", "#verdict-testing", "#first-actions", "#workspace", "#run"]
    manifest = {
        "generator": H.GENERATOR,
        "generator_sha256": H.generator_fingerprint(),
        "outputs": {
            "requirements_pdf": {
                "html": str(first), "input": str(RELEASE_JSON.relative_to(ROOT)), "input_sha256": sha256(RELEASE_JSON),
                "anchors": common[:3] + ["#run-state"] + common[3:],
            },
            "conflict_same_amount": {
                "html": str(second), "input": str(EXAMPLE_JSON.relative_to(ROOT)), "input_sha256": sha256(EXAMPLE_JSON),
                "source": str(EXAMPLE_MD.relative_to(ROOT)), "source_sha256": sha256(EXAMPLE_MD),
                "anchors": common + list(conflict_anchors(example).values()),
                "conflict": conflict_anchors(example),
            },
        },
    }
    (outdir / "first-screen.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--record", action="store_true", help="перезаписать report.json примера прогоном движка")
    args = ap.parse_args()
    manifest = build(Path(args.outdir).resolve(), record=args.record)
    for name, item in manifest["outputs"].items():
        print(f"{name}: {item['html']}")
        print("  якоря: " + " ".join(item["anchors"]))
    print(f"генератор: {manifest['generator']} sha256 {manifest['generator_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
