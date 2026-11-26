"""CLI генератора открытого корпуса.

    python -m evaluation.dev generate --out evaluation/dev/corpus --seeds 1
    python -m evaluation.dev check --corpus evaluation/dev/corpus
    python -m evaluation.dev hash --seeds 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from .generator import GENERATOR_VERSION, corpus_semantic_sha256, generate_cases, write_corpus


def _seeds(s: str) -> list[int]:
    return sorted({int(x) for x in s.split(",") if x.strip()})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.dev")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="сгенерировать корпус")
    g.add_argument("--out", required=True)
    g.add_argument("--seeds", default="1")
    g.add_argument("--all-variants", action="store_true")
    g.add_argument("--formats", default="md,pdf,docx")
    g.add_argument("--binary-kinds", default="base,combo,edge",
                   help="для каких видов кейсов строить PDF/DOCX: base,mutant,combo,edge")
    c = sub.add_parser("check", help="перегенерировать и сверить смысловые хеши с корпусом")
    c.add_argument("--corpus", default="evaluation/dev/corpus")
    c.add_argument("--with-binaries", action="store_true", help="сверить и байты PDF/DOCX")
    o = sub.add_parser("open-run", help="один воспроизводимый прогон dev-набора через CLI продукта (rules_only)")
    o.add_argument("--out", required=True)
    o.add_argument("--product-src", help="каталог src checkout bcc/integration (добавляется в PYTHONPATH)")
    o.add_argument("--product-cmd", help="шаблон команды продукта с {input} и {output}")
    k = sub.add_parser("controls", help="собрать или сверить три контрольных случая на открытом корпусе")
    k.add_argument("--out", default=None, help="каталог (по умолчанию evaluation/dev/controls)")
    k.add_argument("--check", action="store_true", help="только сверить закоммиченные файлы с генератором")
    h = sub.add_parser("hash", help="напечатать смысловой хеш корпуса без записи файлов")
    h.add_argument("--seeds", default="1")
    h.add_argument("--all-variants", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "generate":
        m = write_corpus(a.out, _seeds(a.seeds), a.all_variants, tuple(a.formats.split(",")),
                         tuple(a.binary_kinds.split(",")))
        bad = [(c["case_id"], r["format"], r["render_check"]) for c in m["cases"] for r in c["renders"]
               if not r["render_check"]["ok"]]
        print(f"генератор {GENERATOR_VERSION}: кейсов {len(m['cases'])}, "
              f"меток {sum(1 for _ in open(Path(a.out) / 'labels.jsonl', encoding='utf-8'))}, "
              f"корпус {m['corpus_semantic_sha256']}")
        for cid, fmt, chk in bad:
            print(f"  ВНИМАНИЕ: {cid}@{fmt}: текст после рендера неполный: {chk}")
        return 1 if bad else 0
    if a.cmd == "open-run":
        from .open_run import open_run
        s = open_run(a.out, a.product_src, a.product_cmd)
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "controls":
        from . import controls
        out = Path(a.out) if a.out else controls.OUT
        if a.check:
            problems = controls.check(out)
            print("OK: контроли воспроизводятся" if not problems else "\n".join(problems))
            return 0 if not problems else 1
        print("\n".join(controls.write(out)))
        return 0
    if a.cmd == "hash":
        seeds = _seeds(a.seeds)
        cases = generate_cases(seeds, a.all_variants)
        print(corpus_semantic_sha256(cases, seeds, a.all_variants))
        return 0
    if a.cmd == "check":
        root = Path(a.corpus)
        m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        cases = generate_cases(m["seeds"], m["all_variants"])
        problems = []
        if m["generator_version"] != GENERATOR_VERSION:
            problems.append(f"версия генератора {m['generator_version']} ≠ {GENERATOR_VERSION}")
        got = corpus_semantic_sha256(cases, m["seeds"], m["all_variants"])
        if got != m["corpus_semantic_sha256"]:
            problems.append(f"смысловой хеш корпуса {got} ≠ {m['corpus_semantic_sha256']}")
        by_id = {c["case_id"]: c for c in m["cases"]}
        for c in cases:
            rec = by_id.get(c.case_id)
            if rec is None:
                problems.append(f"{c.case_id}: нет в манифесте")
                continue
            if rec["semantic_sha256"] != c.semantic_sha256:
                problems.append(f"{c.case_id}: смысловой хеш отличается")
            md = root / "cases" / c.case_id / "source.md"
            if hashlib.sha256(md.read_bytes()).hexdigest() != c.source_sha256:
                problems.append(f"{c.case_id}: source.md отличается от генератора")
        labels = [json.loads(l) for l in open(root / "labels.jsonl", encoding="utf-8") if l.strip()]
        if any(l.get("visibility") != "public" for l in labels):
            problems.append("в dev-эталоне есть строки не с visibility=public")
        if a.with_binaries:
            with tempfile.TemporaryDirectory() as tmp:
                m2 = write_corpus(tmp, m["seeds"], m["all_variants"], tuple(m["formats"]),
                                  tuple(m.get("binary_kinds", ("base", "combo", "edge"))))
                for c2 in m2["cases"]:
                    for r2 in c2["renders"]:
                        r1 = next(r for r in by_id[c2["case_id"]]["renders"] if r["format"] == r2["format"])
                        if r1["sha256"] != r2["sha256"]:
                            problems.append(f"{c2['case_id']}@{r2['format']}: байты рендера отличаются "
                                            "(другие версии шрифтов или библиотек)")
        print("OK: корпус воспроизводится" if not problems else "\n".join(problems))
        return 0 if not problems else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
