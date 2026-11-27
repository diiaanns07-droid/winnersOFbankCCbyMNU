"""Один документ в нескольких форматах — одинаковое чтение и одинаковый результат кода (№53), без вызовов модели.

    python -m evaluation.v2.formats release/input/requirements.md release/input/requirements.pdf \
        release/input/requirements.docx [--replay tests/v2/fixtures/official]

1. Чтение: непустые строки DocView каждого формата сравниваются с первым (эталонным) по нормализованному тексту,
   виду блока (код, заголовок) и последнему разделу; печатается построчный diff.
2. ``--replay DIR``: записанные ответы модели для первого формата (mock-каталог, номера строк первого формата)
   переводятся на номера строк каждого другого формата по совпадению текста строк, и конвейер прогоняется mock-ом
   на всех форматах. Одинаковые ответы модели должны дать те же требования, замечания и цитаты.
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import ROOT

sys.path.insert(0, str(ROOT / "src"))
from bcc_review.v2 import docview  # noqa: E402

LINE_KEYS = {"line_start", "line_end", "line", "row_line", "stated_line", "line_a", "line_b", "line_from", "line_to"}
LIST_KEYS = {"lines", "line_numbers", "source_lines"}


def _norm(t: str) -> str:
    return " ".join(str(t).split()).casefold()


def _rows(view: dict) -> list[dict]:
    return [ln for ln in view["lines"] if ln["text"].strip()]


def _sig(ln: dict) -> str:
    kind = "code" if ln.get("kind") == "code" else ("heading" if ln.get("heading") else "text")
    last = str(ln.get("section") or "").split(docview.SECTION_SEP)[-1]
    return f"{kind:7s} [{last[:40]}] {' '.join(ln['text'].split())}"


def line_map(src: dict, dst: dict) -> dict[int, int]:
    """Номер строки ``src`` → номер строки ``dst`` по совпадению текста непустых строк; пустая — к следующей."""
    a, b = _rows(src), _rows(dst)
    sm = difflib.SequenceMatcher(None, [_norm(x["text"]) for x in a], [_norm(x["text"]) for x in b], autojunk=False)
    m: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                m[a[i1 + k]["n"]] = b[j1 + k]["n"]
    nxt = None
    for ln in reversed(src["lines"]):
        if ln["n"] in m:
            nxt = m[ln["n"]]
        elif nxt is not None:
            m[ln["n"]] = nxt
    return m


def _translate(o, m: dict[int, int]):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in LINE_KEYS and isinstance(v, int) and not isinstance(v, bool):
                out[k] = m.get(v, v)
            elif k in LIST_KEYS and isinstance(v, list) and v and all(isinstance(x, int) and not isinstance(x, bool)
                                                                       for x in v):
                out[k] = [m.get(x, x) for x in v]
            else:
                out[k] = _translate(v, m)
        return out
    if isinstance(o, list):
        return [_translate(x, m) for x in o]
    return o


def reading_diff(paths: list[Path]) -> int:
    views = [docview.load(p) for p in paths]
    base = [_sig(x) for x in _rows(views[0])]
    total = 0
    for p, v in zip(paths[1:], views[1:]):
        other = [_sig(x) for x in _rows(v)]
        diff = [d for d in difflib.unified_diff(base, other, paths[0].name, p.name, n=0, lineterm="")
                if d[:1] in "+-" and not d.startswith(("+++", "---"))]
        total += len(diff)
        print(f"## {paths[0].name} → {p.name}: строк {len(base)} / {len(other)}, расхождений {len(diff)}")
        for d in diff:
            print("  " + d)
    return total


def replay(paths: list[Path], fixtures: Path, out: Path) -> dict:
    views = [docview.load(p) for p in paths]
    res = {}
    for p, v in zip(paths, views):
        fx = fixtures
        if p is not paths[0]:
            fx = out / f"fx_{p.suffix.lstrip('.')}"
            fx.mkdir(parents=True, exist_ok=True)
            m = line_map(views[0], v)
            for f in fixtures.glob("*.json"):
                data = _translate(json.loads(f.read_text(encoding="utf-8")), m)
                (fx / f.name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rep = out / f"replay_{p.suffix.lstrip('.')}.md"
        subprocess.run([sys.executable, "-m", "bcc_review", str(p), str(rep), "--provider", "mock", "--mock-dir",
                        str(fx), "--runs-dir", str(out / "runs")], cwd=str(ROOT), capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, check=False)
        r = json.loads(rep.with_suffix(".json").read_text(encoding="utf-8"))
        res[p.name] = {
            "requirements": [_norm(x.get("text", "")) for x in r.get("requirements") or []],
            "findings": [(f.get("severity"), f.get("title")) for f in r.get("findings") or []],
            "quotes": [_norm(q.get("quote", "")) for f in r.get("findings") or [] for q in f.get("evidence") or []]}
    first = res[paths[0].name]
    for p in paths[1:]:
        cur = res[p.name]
        same = {k: cur[k] == first[k] for k in first}
        print(f"## replay {paths[0].name} → {p.name}: требований {len(cur['requirements'])}, замечаний "
              f"{len(cur['findings'])}, цитат {len(cur['quotes'])}; совпадают: "
              + ", ".join(f"{k} {'да' if ok else 'НЕТ'}" for k, ok in same.items()))
        for x in sorted(set(first["findings"]) ^ set(cur["findings"]), key=str):
            print(f"  {'-' if x in first['findings'] else '+'} {x[0]}: {x[1]}")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path, help="эталонный формат первым")
    ap.add_argument("--replay", type=Path, help="mock-каталог ответов модели для первого файла")
    ap.add_argument("--out", type=Path, help="каталог для replay (по умолчанию временный)")
    a = ap.parse_args(argv)
    n = reading_diff(a.files)
    if a.replay:
        if a.out:
            a.out.mkdir(parents=True, exist_ok=True)
            replay(a.files, a.replay, a.out)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                replay(a.files, a.replay, Path(tmp))
    return 0 if n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
