"""CLI счётчика.

Основная форма (подсчёт):
    python -m evaluation.harness --gold labels.jsonl --pred predictions.jsonl --out metrics.json
Подкоманды:
    adapt         Report.json продукта → predictions.jsonl
    adapt-labels  плоские метки (defect_id, type, quote, related_quote, …) → эталон
    run           прогон продукта по манифесту в режиме rules_only | rules_plus_llm
    compare       таблица режимов по нескольким metrics.json
    fingerprint   хеш-отпечаток закрытого набора (без текста)
    leakcheck     проверка, что закрытые ответы не попали в dev-корпус
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adapter import adapt_report_files, file_info, flat_labels_to_gold
from .schema import (Manifest, ProtocolError, parse_decisions, parse_gold, parse_predictions, read_jsonl,
                     write_jsonl)
from .score import adjudication_sheet, score
from .taxonomy import Taxonomy

SUBCOMMANDS = ("adapt", "adapt-labels", "run", "compare", "fingerprint", "leakcheck", "score")


def _fmt(v: float | None, num: int, den: int) -> str:
    return "null (знаменатель 0)" if v is None else f"{v:.4f} = {num}/{den}"


def summary(m: dict) -> str:
    mi = m["micro"]
    lines = [
        f"кейсов: {m['counts']['independent_cases']} независимых (размечено {m['counts']['cases_labeled']}, "
        f"пропусков измерения {m['counts']['missing_measurements']}), семейств: {m['counts']['families']}",
        f"TP={mi['tp']} FP={mi['fp']} FN={mi['fn']} дубли={mi['duplicates']} на разборе={mi['pending_adjudication']}",
        f"precision={_fmt(mi['precision'], mi['tp'], mi['tp'] + mi['fp'])}",
        f"recall={_fmt(mi['recall'], mi['tp'], mi['tp'] + mi['fn'])}",
        f"f1={'null' if mi['f1'] is None else round(mi['f1'], 4)}  "
        f"precision_strict={'null' if mi['precision_strict'] is None else round(mi['precision_strict'], 4)}",
        f"чистые документы: {m['clean_controls']['false_alarms']} ложных тревог на "
        f"{m['clean_controls']['cases_with_alarms']}/{m['clean_controls']['cases']} кейсах",
    ]
    for w in m.get("warnings", []):
        lines.append(f"предупреждение: {w}")
    return "\n".join(lines)


def cmd_score(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness", description="Подсчёт TP/FP/FN и метрик")
    ap.add_argument("--gold", required=True, help="эталон labels.jsonl")
    ap.add_argument("--pred", required=True, help="predictions.jsonl (строки finding и run)")
    ap.add_argument("--out", required=True, help="куда записать metrics.json")
    ap.add_argument("--manifest", help="manifest.json корпуса: связывает представления с case_id")
    ap.add_argument("--adjudication", help="решения разбора (jsonl: pred_key, decision, label_id)")
    ap.add_argument("--adjudication-out", help="записать лист разбора по всем FP")
    ap.add_argument("--review-seed", help="seed воспроизводимой выборки для разбора (фиксируется до просмотра)")
    ap.add_argument("--review-sample", type=int, help="размер выборки для разбора (нужен --review-seed)")
    ap.add_argument("--type-match", choices=("hierarchy", "exact"), default="hierarchy")
    ap.add_argument("--render-format", help="формат для основных метрик (по умолчанию primary_render)")
    ap.add_argument("--mode", help="режим продукта, если в файле их несколько")
    ap.add_argument("--status", help="учитывать только эти Finding.status, через запятую")
    ap.add_argument("--taxonomy", help="другой taxonomy.toml")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    tax = Taxonomy.load(a.taxonomy)
    gold = parse_gold(read_jsonl(a.gold), tax)
    preds, runs = parse_predictions(read_jsonl(a.pred), tax)
    manifest = Manifest.load(a.manifest) if a.manifest else None
    decisions = parse_decisions(read_jsonl(a.adjudication)) if a.adjudication else {}
    statuses = set(a.status.split(",")) if a.status else None
    m = score(gold, preds, runs, tax, manifest=manifest, decisions=decisions, type_match=a.type_match,
              render_format=a.render_format, mode=a.mode, statuses=statuses)
    m["inputs"] = {"gold": file_info(a.gold), "pred": file_info(a.pred), "manifest": file_info(a.manifest),
                   "adjudication": file_info(a.adjudication), "taxonomy": file_info(tax.source)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    if a.adjudication_out:
        write_jsonl(a.adjudication_out, adjudication_sheet(m, a.review_seed, a.review_sample))
    if not a.quiet:
        print(summary(m))
    return 0


def cmd_adapt(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness adapt")
    ap.add_argument("--report", action="append", required=True, help="OUTPUT.json продукта (можно несколько)")
    ap.add_argument("--manifest")
    ap.add_argument("--mode", help="переписать mode (если отчёт его не сообщает)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--taxonomy")
    a = ap.parse_args(argv)
    tax = Taxonomy.load(a.taxonomy)
    rows = adapt_report_files(a.report, tax, Manifest.load(a.manifest) if a.manifest else None)
    if a.mode:
        for r in rows:
            r["mode"] = r.get("mode") or a.mode
    write_jsonl(a.out, rows)
    print(f"записано строк: {len(rows)} ({sum(1 for r in rows if r['record'] == 'finding')} находок) → {a.out}")
    return 0


def cmd_adapt_labels(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness adapt-labels")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--taxonomy")
    a = ap.parse_args(argv)
    tax = Taxonomy.load(a.taxonomy)
    rows = flat_labels_to_gold(read_jsonl(a.inp), tax)
    parse_gold([dict(r, _file=a.inp, _line=i + 1) for i, r in enumerate(rows)], tax)  # проверка
    write_jsonl(a.out, rows)
    print(f"эталон: {len(rows)} строк → {a.out}")
    return 0


def cmd_run(argv: list[str]) -> int:
    from .runner import DEFAULT_PRODUCT_CMD, MODES, run_manifest
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness run")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--mode", required=True, choices=MODES)
    ap.add_argument("--out", required=True, help="каталог прогона")
    ap.add_argument("--format", help="md | pdf | docx (по умолчанию primary_render)")
    ap.add_argument("--product-cmd", default=DEFAULT_PRODUCT_CMD,
                    help="шаблон команды продукта с {input} и {output}")
    ap.add_argument("--provider", help="anthropic | gemini для rules_plus_llm (mock — режим mock)")
    ap.add_argument("--cache", default="off", choices=("off", "on"),
                    help="off → продукт получает --no-cache (по умолчанию: реальные вызовы видны в счётчике)")
    ap.add_argument("--cache-dir")
    ap.add_argument("--cases", help="только эти case_id через запятую")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--extra-arg", action="append", default=[], help="доп. аргумент продукта (повторяемый)")
    ap.add_argument("--gold", help="сразу посчитать метрики по эталону")
    ap.add_argument("--taxonomy")
    a = ap.parse_args(argv)
    tax = Taxonomy.load(a.taxonomy)
    cfg = run_manifest(a.manifest, a.mode, a.out, tax, fmt=a.format, product_cmd=a.product_cmd,
                       provider=a.provider, cache=a.cache, cache_dir=a.cache_dir,
                       cases=a.cases.split(",") if a.cases else None, limit=a.limit, timeout=a.timeout,
                       extra_args=a.extra_arg)
    print(f"прогонов: {cfg['renders']}, режим {cfg['mode']}, песочница сети: {cfg['network_sandbox']} → {a.out}")
    if a.gold:
        return cmd_score(["--gold", a.gold, "--pred", str(Path(a.out) / "predictions.jsonl"),
                          "--manifest", a.manifest, "--out", str(Path(a.out) / "metrics.json"),
                          "--adjudication-out", str(Path(a.out) / "adjudication.jsonl"),
                          *(["--render-format", a.format] if a.format else []),
                          *(["--taxonomy", a.taxonomy] if a.taxonomy else [])])
    return 0


def cmd_compare(argv: list[str]) -> int:
    from .compare import compare_files
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness compare")
    ap.add_argument("--metrics", action="append", required=True, help="ИМЯ=путь/metrics.json")
    ap.add_argument("--out", help="compare.md")
    ap.add_argument("--json", help="compare.json")
    a = ap.parse_args(argv)
    md, data = compare_files(a.metrics, a.out, a.json)
    print(md)
    return 0 if data["comparable"] else 3


def cmd_fingerprint(argv: list[str]) -> int:
    from .leakcheck import fingerprint
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness fingerprint")
    ap.add_argument("--labels", required=True)
    ap.add_argument("--docs", help="каталог закрытых документов (необязательно)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    fp = fingerprint(a.labels, a.docs)
    Path(a.out).write_text(json.dumps(fp, indent=1) + "\n", encoding="utf-8")
    print(f"отпечаток: {len(fp['quote_ngrams'])} хешей цитат, {len(fp['source_sha256'])} файлов → {a.out}")
    return 0


def cmd_leakcheck(argv: list[str]) -> int:
    from .leakcheck import fingerprint, leakcheck
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness leakcheck")
    ap.add_argument("--dev", default="evaluation/dev/corpus")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fingerprint", help="отпечаток от fingerprint")
    g.add_argument("--closed", help="закрытые метки (локально, у владельца)")
    ap.add_argument("--closed-docs")
    a = ap.parse_args(argv)
    fp = json.loads(Path(a.fingerprint).read_text()) if a.fingerprint else fingerprint(a.closed, a.closed_docs)
    res = leakcheck(a.dev, fp)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 1 if res["leak"] else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--version"]:
        print(__version__)
        return 0
    cmd = argv[0] if argv and argv[0] in SUBCOMMANDS else "score"
    if argv and argv[0] in SUBCOMMANDS:
        argv = argv[1:]
    handlers = {"score": cmd_score, "adapt": cmd_adapt, "adapt-labels": cmd_adapt_labels, "run": cmd_run,
                "compare": cmd_compare, "fingerprint": cmd_fingerprint, "leakcheck": cmd_leakcheck}
    try:
        return handlers[cmd](argv)
    except ProtocolError as exc:
        print(f"ошибка формата: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
