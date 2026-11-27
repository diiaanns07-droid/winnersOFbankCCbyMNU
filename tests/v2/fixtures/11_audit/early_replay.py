"""№11: ранний вызов вопросов на сохранённом прогоне (без судьи и линз): кандидаты из ``stages/quotes.json``,
итоговые дефекты из ``report.json``; затем ``clarify.finish`` — как в конвейере.

    python tests/v2/fixtures/11_audit/early_replay.py ДОКУМЕНТ runs/<id> ОТЧЁТ.json [--model haiku] [--out q.json]

Печатает вопросы, покрытие critical и время вызова. Сравнение версий — тем же скриптом из копии ветки.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import docview  # noqa: E402
from bcc_review.v2.context import Context  # noqa: E402
from bcc_review.v2.pipeline import DEFAULTS, make_llm  # noqa: E402
from bcc_review.v2.stages import clarify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("run_dir")
    ap.add_argument("report")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--provider", default="claude_cli")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    cands = json.loads((Path(a.run_dir) / "stages" / "quotes.json").read_text(encoding="utf-8"))["output"]["candidates"]
    view = docview.load(a.doc)
    opts = {**DEFAULTS, "provider": a.provider, "model": a.model, "cache": False}
    llm, _ = make_llm(opts, None, a.doc)
    ctx = Context(view=view, llm=llm, options={**opts, "input": a.doc},
                  requirements=list(report.get("requirements") or []))
    findings = report["findings"]
    t0 = time.monotonic()
    raw = clarify.ask_candidates(ctx, cands)
    sec = time.monotonic() - t0
    res = clarify.finish(ctx, findings, raw)
    qs = res["questions"]
    cov = {x for q in qs for x in q["finding_ids"]}
    crit = [f["id"] for f in findings if f.get("severity") == "critical"]
    print(f"ранний вызов {sec:.0f} с; вопросов сырых {len((raw or {}).get('questions') or [])}, итог {len(qs)}; "
          f"critical покрыто {sum(c in cov for c in crit)}/{len(crit)} (без вопроса: {[c for c in crit if c not in cov]})")
    for q in qs:
        print(f"  {q['id']} {'Б' if q['blocking'] else ' '} {q.get('origin', ''):4s} {q['finding_ids']} | {q['topic']}")
    for w in ctx.warnings:
        print("  !", w)
    if a.out:
        Path(a.out).write_text(json.dumps({"raw": raw, "questions": qs, "seconds": sec}, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
