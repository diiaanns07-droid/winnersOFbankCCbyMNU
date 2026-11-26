"""CLI проверки состава прогонов (только файлы, без продукта и сети).

    python -m evaluation.harness.audit --gold labels.jsonl --run rules_only=out/ro --run rules_plus_llm=out/llm \
        --out out/audit [--manifest manifest.json] [--expect-agent-commit 2821989]

Коды выхода: 0 — все пары допустимы; 3 — нарушения; 4 — только неизвестные; 2 — ошибка входа.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import EXIT_INPUT, AuditInputError, audit, write_outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness.audit",
                                 description="Состав прогонов до подсчёта: пары по ID и SHA, пропуски, повторы, "
                                             "режим и фактическое покрытие LLM")
    ap.add_argument("--gold", required=True, help="эталон labels.jsonl")
    ap.add_argument("--run", action="append", required=True,
                    help="каталог прогона (ИМЯ=каталог или каталог); повторяемый")
    ap.add_argument("--manifest", help="манифест, если его нет в каталоге прогона и по пути из run_config.json")
    ap.add_argument("--expect-agent-commit", help="ожидаемый agent_commit продукта (префикс SHA)")
    ap.add_argument("--out", help="каталог: composition.json, composition.md, matrix.jsonl, admissible_case_ids.txt")
    ap.add_argument("--json", action="store_true", help="напечатать composition.json вместо сводки")
    a = ap.parse_args(argv)
    try:
        res = audit(a.gold, a.run, manifest=a.manifest, expect_agent_commit=a.expect_agent_commit)
    except AuditInputError as exc:
        print(f"ошибка входа: {exc}", file=sys.stderr)
        return EXIT_INPUT
    if a.out:
        write_outputs(res, a.out)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return res["verdict"]["exit_code"]
    v = res["verdict"]
    print(f"{v['text']} (код {v['exit_code']}): пар {v['pairs']}, допустимых {v['admissible']}, "
          f"нарушений {len(v['violation_cases'])}, неизвестных {len(v['unknown_cases'])}, "
          f"симметричных пропусков {len(v['excluded_symmetric'])}")
    for m in res["matrix"]:
        print(f"  {m['code']:<15} {m['run']:<16} {m['case_id']}: {m['reason']}")
    for i in res["info"]:
        if i["code"] in ("partial", "missing_all"):
            print(f"  ({i['code']}) {i['run']:<16} {i['case_id']}: {i['reason']}")
    for n, c in res["llm_coverage"].items():
        print(f"  покрытие LLM {n}: модель ответила в {c['llm_ok']} из {c['llm_known']} отчётов, "
              f"complete/partial {c['complete']}/{c['partial']}, физ. вызовов {c['physical_calls']}")
    if a.out:
        print(f"→ {a.out}/composition.md")
    return v["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
