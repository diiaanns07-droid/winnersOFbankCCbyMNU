"""Экзамен ответов владельца v3 (№56): пересмотр по ответам на тех вопросах, которые видел владелец.

Владелец отвечает на вопросы конкретного отчёта (`<кейс>/baseline.md`). Чтобы номера Q и D не менялись, этапы
этого отчёта (`<кейс>/baseline_run/stages`) берутся готовыми, а живьём выполняются только пересмотр по ответам,
суд над новыми кандидатами и редакция ТЗ — тот же `pipeline.review`, что у `python -m bcc_review … --answers
--revise`, с `reuse=` как у команды `stage`.

    python docs/plan-v2/f4/answers_exam_v3/run_exam.py <кейс> <ответы.md> <каталог_выхода> [--model sonnet]

Затем повторное чтение исправленной редакции — обычной командой (полный прогон без кэша), см. README.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import __main__ as cli  # noqa: E402
from bcc_review.v2 import pipeline  # noqa: E402
from bcc_review.v2.runs import RunDir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run_exam.py")
    p.add_argument("case")
    p.add_argument("answers")
    p.add_argument("out_dir")
    cli._common(p)
    a = p.parse_args(argv)
    a.answers, a.revise = str(Path(a.answers).resolve()), True
    case = HERE / a.case
    src = RunDir(case / "baseline_run", create=False)
    if not src.stages.is_dir():
        print(f"нет сохранённых этапов: {src.stages}", file=sys.stderr)
        return 2
    opts = cli._opts(a)
    run = RunDir(opts["runs_dir"], opts.get("run_id"))
    opts["run_id"] = run.run_id
    out = Path(a.out_dir) / "answered.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    report, written = pipeline.review(case / "source.md", out, opts, reuse=src, rerun=set(), log=cli._log(a.quiet))
    cli._print_summary(report, written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
