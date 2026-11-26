"""Отладка правил: `python -m bcc_review.v2.rules ФАЙЛ [--segment segment.json] [--json]`."""
from __future__ import annotations

import argparse
import json
import sys

from . import format_signals, run
from ._view import load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.rules")
    ap.add_argument("file")
    ap.add_argument("--segment", help="выход нарезки (segment.json)")
    ap.add_argument("--json", action="store_true", help="вывести JSON целиком")
    ap.add_argument("--signals", action="store_true", help="показать блок сигналов")
    ap.add_argument("--block", metavar="ЛИНЗА", help="напечатать только блок <сигналы> для линзы "
                    "(analyst, qa, architect, risk, consistency, all) — для try_prompt --extra")
    a = ap.parse_args(argv)
    view = load(a.file)
    reqs = json.load(open(a.segment, encoding="utf-8")) if a.segment else None
    out = run(view, reqs)
    if a.block:
        aud = None if a.block == "all" else a.block
        print("<сигналы>\n" + format_signals(out["signals"], audience=aud) + "\n</сигналы>")
        return 0
    if a.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    print(f"Кандидатов: {len(out['candidates'])}, сигналов: {len(out['signals'])}")
    for c in out["candidates"]:
        lines = ",".join(str(e["line"]) for e in c["evidence"])
        print(f"  [{c['severity']}] {c['source']}: {c['title']}  (L{lines})")
    if a.signals:
        print(format_signals(out["signals"]))
    for w in out.get("warnings", []):
        print("!", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
