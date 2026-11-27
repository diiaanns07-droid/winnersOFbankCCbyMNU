"""№11-Б: «было → стало» заново на сохранённом отчёте — те же дефекты, требования и ответы владельца, только этап
revise (2 вызова модели). Так «до» и «после» правки revise сравниваются на одних и тех же входах.

    python tests/v2/fixtures/11b_revise/bench.py ДОКУМЕНТ ОТЧЁТ.json КАТАЛОГ --provider claude_cli --model sonnet

В КАТАЛОГ: ``revised.md`` (редакция), ``rewrites.json`` (все правки, в том числе не применённые с причиной),
``edits.tsv`` (разметка каждой правки: место относительно дефекта, вид дефекта, решение страховки).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import pipeline  # noqa: E402
from bcc_review.v2.context import Context  # noqa: E402
from bcc_review.v2.stages import revise  # noqa: E402


def label(report: dict, rewrites: list[dict], doc_lines: list[str]) -> list[dict]:
    """Каждая правка: дефект, вид дефекта, действие, строка, чья строка (цитата дефекта / чужая), итог."""
    findings = report.get("findings_before") or report.get("findings") or []
    guard = revise.Guard(findings, report.get("requirements") or [])
    by = {f["id"]: f for f in findings}
    out = []
    for r in rewrites:
        f = by.get(r["finding_id"], {})
        for e in r.get("edits") or []:
            ln = int((e.get("src_line") if r.get("pass") == 2 else e.get("line")) or 0)  # строка исходника
            owners = guard.owners(r["finding_id"], ln) if e.get("action") == "replace" else []
            out.append({"finding_id": r["finding_id"], "severity": f.get("severity", ""),
                        "class": revise.defect_class(f), "action": e.get("action"), "line": ln,
                        "place": ("чужая: " + ", ".join(owners[:3])) if owners else "своя",
                        "applied": bool(e.get("applied")), "reason": e.get("reason", ""),
                        "was": e.get("was", ""), "became": e.get("became", ""), "pass": r.get("pass", 1)})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("doc")
    p.add_argument("report")
    p.add_argument("out")
    p.add_argument("--provider", default="claude_cli")
    p.add_argument("--model", default="sonnet")
    a = p.parse_args(argv)
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    view = pipeline.load_view(a.doc)
    opts = {**pipeline.DEFAULTS, "provider": a.provider, "model": a.model, "cache": False, "input": a.doc}
    llm, _ = pipeline.make_llm(opts, None, a.doc)
    ctx = Context(view=view, llm=llm, options={**opts, "input": str(a.doc)},
                  requirements=report.get("requirements") or [])
    findings = report.get("findings_before") or report.get("findings") or []
    res = revise.run(ctx, findings, report.get("clarification"), requirements=report.get("requirements"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "revised.md").write_text(res.get("revised_markdown", ""), encoding="utf-8")
    fixes = [{"finding_id": f["finding_id"], "summary": f.get("problem", ""), "edits": f["edits"], "pass": 2}
             for f in res.get("check_fixes") or []]
    rows = label(report, list(res.get("rewrites") or []) + fixes,
                 Path(a.doc).read_text(encoding="utf-8").splitlines())
    (out / "rewrites.json").write_text(json.dumps({"stats": res.get("stats"), "rewrites": res.get("rewrites"),
                                                   "check_fixes": res.get("check_fixes"), "edits": rows,
                                                   "warnings": ctx.warnings}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    with (out / "edits.tsv").open("w", encoding="utf-8") as fh:
        fh.write("№\tпроход\tдефект\tвид\tдействие\tстрока\tместо\tприменена\tпричина\tбыло\tстало\n")
        for i, r in enumerate(rows, 1):
            fh.write("\t".join(str(x).replace("\t", " ").replace("\n", " / ") for x in (
                i, r["pass"], r["finding_id"], r["class"], r["action"], r["line"], r["place"],
                "да" if r["applied"] else "нет", r["reason"], r["was"][:200], r["became"][:300])) + "\n")
    print(json.dumps(res.get("stats"), ensure_ascii=False))
    print("calls:", (llm.summary() if llm else {}).get("calls"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
