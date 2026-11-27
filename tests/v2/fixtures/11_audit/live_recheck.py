"""№11: живой пересмотр по ответам на готовом отчёте (без полного прогона агента).

    python tests/v2/fixtures/11_audit/live_recheck.py ДОКУМЕНТ ОТЧЁТ.json ОТВЕТЫ.md [--model haiku] [--out out.json]

Берёт документ, ``report.json`` прогона и файл ответов, вызывает ``recheck.apply_answers`` с настоящей моделью
(провайдер claude_cli, профиль слабой модели как у конвейера) и печатает: решения по дефектам, закрывший ответ,
противоречащие ответы, новые конфликты от ответов (принятые судьёй и отклонённые с причиной), время и вызовы.
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
from bcc_review.v2.stages import recheck  # noqa: E402


class _Recorded:
    """Ответ этапа recheck — из файла, остальные этапы (судья новых конфликтов) — живая модель."""

    def __init__(self, llm, recheck_raw: dict):
        self._llm, self._raw = llm, recheck_raw
        self.stats = llm.stats

    def ask(self, stage, system, user, schema, **kw):
        if stage == "recheck":
            return self._raw
        return self._llm.ask(stage, system, user, schema, **kw)

    def ask_split(self, stage, build, items, schema, merge, **kw):
        if stage == "recheck":
            return self._raw
        return self._llm.ask_split(stage, build, items, schema, merge, **kw)

    def __getattr__(self, name):
        return getattr(self._llm, name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("report")
    ap.add_argument("answers")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--provider", default="claude_cli")
    ap.add_argument("--out", default="")
    ap.add_argument("--recheck-json", default="", help="записанный ответ модели этапа recheck (судья — живой)")
    a = ap.parse_args()
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    view = docview.load(a.doc)
    opts = {**DEFAULTS, "provider": a.provider, "model": a.model, "cache": False}
    llm, _ = make_llm(opts, None, a.doc)
    if a.recheck_json:
        llm = _Recorded(llm, json.loads(Path(a.recheck_json).read_text(encoding="utf-8")))
    ctx = Context(view=view, llm=llm, options={**opts, "input": a.doc},
                  requirements=list(report.get("requirements") or []))
    t0 = time.monotonic()
    res = recheck.apply_answers(ctx, report, Path(a.answers).read_text(encoding="utf-8"))
    sec = time.monotonic() - t0
    clar = res["clarification"]
    print(f"время {sec:.0f} с, вызовов {llm.stats.get('calls')}, по этапам "
          f"{ {k: v.get('calls') for k, v in (llm.stats.get('by_stage') or {}).items()} }")
    print("до:", clar["before"], "\nпосле:", clar["after"])
    for c in clar["changes"]:
        print(f"  {c['finding_id']} {c['severity_before']}→{c['severity_after'] or '—'} {c['status']:8s} "
              f"by={c.get('answer_ids')} conflict={c.get('answer_conflict')} | {c['reason'][:150]}")
    new = [f for f in res["findings_after"] if f.get("status_after_answers") == "new"]
    for f in new:
        print(f"  НОВЫЙ {f['id']} {f.get('severity')} | {f.get('title')} | {f.get('problem', '')[:200]}")
    for r in res["rejected_after"]:
        print(f"  ОТКЛОНЁН {r.get('candidate_id')} | {r.get('title', '')[:90]} | {str(r.get('reason', ''))[:160]}")
    for w in clar.get("warnings") or []:
        print("  ! ", w)
    for w in ctx.warnings:
        print("  ctx!", w)
    if a.out:
        Path(a.out).write_text(json.dumps({**res, "seconds": sec}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
