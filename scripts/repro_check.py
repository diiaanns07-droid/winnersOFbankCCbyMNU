"""Совпадают ли два отчёта агента, кроме времени: повторяемость прогона.

    python scripts/repro_check.py out/a/report.json out/b/report.json            # JSON и рядом лежащие .md
    python scripts/repro_check.py a.json b.json --content                         # только содержимое: без паспорта

Сравнивает JSON по полям (время, номер прогона и длительности этапов не считаются), Markdown и HTML построчно
(даты, длительности и номер прогона заменены на «<время>»). С --content паспорт прогона (вызовы, токены, кэш) не
сравнивается: так проверяют прогон без кэша против прогона из кэша. Код выхода 0 — совпадают, 1 — нет.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

TIME_KEYS = {"run_id", "started_at", "finished_at", "duration_s", "seconds"}
# в --content: поля паспорта, которые честно различаются у прогона без кэша и из кэша
PASSPORT_KEYS = {"calls", "tokens", "cost_usd", "stage_stats", "models_used", "commit", "dirty", "warnings"}
MD_TIME = [
    re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?"),  # ISO (HTML, JSON внутри)
    re.compile(r'"(?:duration_s|seconds)": ?[0-9.]+'),
    re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?:–\d{2}:\d{2})?(?: \(UTC[+-]\d+\))?"),
    re.compile(r"\b\d+ мин(?: \d+ с)?\b|\b\d+(?:[.,]\d+)? с\b"),
    re.compile(r"\b\d{8}-\d{6}-[0-9a-f]{4}\b"),
]


def mask_md(text: str) -> str:
    for rx in MD_TIME:
        text = rx.sub("<время>", text)
    return text


def diff_json(a, b, path: str = "", skip: frozenset = frozenset()) -> list[str]:
    out: list[str] = []
    if type(a) is not type(b):
        return [f"{path}: {str(a)[:80]!r} ≠ {str(b)[:80]!r}"]
    if isinstance(a, dict):
        if [k for k in a if k not in skip] != [k for k in b if k not in skip]:
            out.append(f"{path}: другой порядок или состав ключей")
        for k in a:
            if k in TIME_KEYS or k in skip or k not in b:
                continue
            out += diff_json(a[k], b[k], f"{path}.{k}", skip)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: {len(a)} ≠ {len(b)} элементов")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_json(x, y, f"{path}[{i}]", skip)
    elif a != b:
        out.append(f"{path}: {str(a)[:80]!r} ≠ {str(b)[:80]!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--content", action="store_true", help="не сравнивать паспорт прогона (вызовы, токены, кэш)")
    args = ap.parse_args(argv)
    for path in (args.a, args.b):
        if not path.is_file():
            print(f"Нет файла отчёта: {path}", file=sys.stderr)
            return 2
    ja = json.loads(args.a.read_text(encoding="utf-8"))
    jb = json.loads(args.b.read_text(encoding="utf-8"))
    if args.content:
        for j in (ja, jb):
            run = j.get("run") or {}
            for k in PASSPORT_KEYS:
                run.pop(k, None)
    problems = diff_json(ja, jb)
    md_diff: list[str] = []
    for suffix in (".md", ".html"):
        fa, fb = args.a.with_suffix(suffix), args.b.with_suffix(suffix)
        if not (fa.exists() and fb.exists()) or args.content:
            continue
        la = mask_md(fa.read_text(encoding="utf-8")).splitlines()
        lb = mask_md(fb.read_text(encoding="utf-8")).splitlines()
        md_diff += [f"{suffix[1:]}: {ln}" for ln in difflib.unified_diff(la, lb, str(fa), str(fb), n=0, lineterm="")
                    if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    if not problems and not md_diff:
        print("Совпадают, кроме времени" + (" (содержимое, без паспорта)" if args.content else "") + ".")
        return 0
    if problems:
        print(f"JSON: {len(problems)} различий")
        for p in problems[:30]:
            print("  " + p)
    if md_diff:
        print(f"Markdown/HTML: {len(md_diff)} различных строк")
        for ln in md_diff[:30]:
            print("  " + ln[:200])
    return 1


if __name__ == "__main__":
    sys.exit(main())
