"""Командная строка.

    python -m bcc_review INPUT OUTPUT.md [опции]          — ревью (обычный вызов)
    python -m bcc_review review INPUT OUTPUT.md [опции]   — то же явно
    python -m bcc_review verify REPORT.json SOURCE         — перепроверка отчёта без модели
    python -m bcc_review contract                          — JSON Schema контракта v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from . import contracts as C

SEV_RU = {"critical": "критичных", "major": "существенных", "minor": "незначительных"}
READY_RU = {"ready": "можно начинать", "not_ready": "нельзя начинать", "unknown": "не определено"}


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _review_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m bcc_review",
        description="Статическое ревью ТЗ: требования, противоречия с доказательствами, готовность к разработке и тестированию.",
        epilog="Другие команды: verify REPORT.json SOURCE — перепроверка отчёта; contract — схема Report v1.")
    p.add_argument("input", help="файл требований (.md, .txt, .pdf, .docx)")
    p.add_argument("output", help="путь отчёта .md; рядом пишется .json из того же Report")
    p.add_argument("--provider", choices=["anthropic", "gemini", "mock"], default="anthropic",
                   help="anthropic (основной профиль), gemini (воспроизводимый запасной), mock (синтетика для тестов)")
    p.add_argument("--model", help="модель (по умолчанию ANTHROPIC_MODEL / GEMINI_MODEL или встроенная)")
    p.add_argument("--offline-lint", action="store_true", help="только детерминированные правила, без модели")
    p.add_argument("--answers", metavar="ANSWERS.md", help="ответы аналитика: применить правки и проверить новую редакцию")
    p.add_argument("--compare", metavar="OLD.json", help="сравнить с отчётом по предыдущей редакции")
    p.add_argument("--export", default="", help="доп. форматы через запятую: html,jira,pdf,docx")
    p.add_argument("--fail-on", choices=["blocker", "partial"],
                   help=f"код {C.EXIT_BLOCKER}, если готовность не «ready»; код {C.EXIT_PARTIAL}, если прогон неполный")
    p.add_argument("--no-cache", action="store_true", help="не использовать кэш ответов модели")
    p.add_argument("--cache-dir", help="каталог кэша (по умолчанию .bcc_cache или BCC_CACHE_DIR)")
    p.add_argument("--max-calls", type=int, default=40, help="бюджет физических вызовов модели (с повторами)")
    p.add_argument("--max-seconds", type=float, default=1500.0, help="бюджет времени прогона, с")
    p.add_argument("--max-tokens", type=int, help="бюджет токенов (вход+выход)")
    p.add_argument("--max-retries", type=int, default=3, help="повторы временных ошибок (429/5xx/таймаут)")
    p.add_argument("--timeout", type=float, default=300.0, help="таймаут одного вызова, с")
    p.add_argument("--mock-script", help="JSON со сценарием ответов mock-провайдера")
    p.add_argument("--no-trace", action="store_true", help="не писать JSONL-трассу этапов")
    p.add_argument("--allow-partial-ready", action="store_true",
                   help="разрешить «можно начинать» при неполном прогоне (по умолчанию запрещено)")
    p.add_argument("--run-id")
    p.add_argument("--parent-run-id")
    p.add_argument("--artifacts-dir", help="каталог артефактов прогона (по умолчанию OUTPUT.artifacts)")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def _print_summary(report: dict, out_md: Path) -> None:
    run, s, v = report["run"], report["summary"], report["verdict"]
    model = run["model"] or "модель не вызывалась"
    print(f"Отчёт: {out_md}  (+ {out_md.with_suffix('.json').name})")
    print(f"Прогон: {run['status']}, режим {run['mode']}, провайдер {run['provider']}, модель {model}")
    print(f"Вызовы модели: {run['calls']['physical']} физических, {run['calls']['cache_hits']} из кэша, "
          f"токены {run['tokens']['input']}/{run['tokens']['output']}, {run['duration_s']:.1f} с")
    if run["incomplete_stages"]:
        print("Незавершённые этапы: " + ", ".join(run["incomplete_stages"]))
    sev = ", ".join(f"{s['by_severity'][k]} {SEV_RU[k]}" for k in ("critical", "major", "minor"))
    print(f"Требований: {s['requirements']}; замечаний: {s['findings']} ({sev}); "
          f"подтверждено {s['by_status']['confirmed']}, на проверку {s['by_status']['needs_review']}")
    print(f"Разработка: {READY_RU[v['development']['status']]}; тестирование: {READY_RU[v['testing']['status']]}")


def cmd_review(argv: list[str]) -> int:
    args = _review_parser().parse_args(argv)
    from .engine import UsageError, run_review

    exports = tuple(x.strip().lower() for x in args.export.split(",") if x.strip())
    options = C.RunOptions(
        provider=args.provider, model=args.model, offline_lint=args.offline_lint, answers_path=args.answers,
        compare_path=args.compare, exports=exports, cache_dir=args.cache_dir, use_cache=not args.no_cache,
        max_calls=args.max_calls, max_seconds=args.max_seconds, max_tokens=args.max_tokens,
        max_retries=args.max_retries, timeout_s=args.timeout, trace=not args.no_trace, fail_on=args.fail_on,
        mock_script=args.mock_script, allow_partial_ready=args.allow_partial_ready, run_id=args.run_id,
        parent_run_id=args.parent_run_id, artifacts_dir=args.artifacts_dir)
    try:
        report = run_review(args.input, args.output, options=options)
    except UsageError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except C.ContractError as exc:
        print(f"Ошибка контракта: {exc}", file=sys.stderr)
        return C.EXIT_ERROR
    if not args.quiet:
        _print_summary(report, Path(args.output))
    if args.fail_on == "partial" and report["run"]["status"] != "complete":
        return C.EXIT_PARTIAL
    if args.fail_on == "blocker" and any(report["verdict"][t]["status"] != "ready" for t in ("development", "testing")):
        return C.EXIT_BLOCKER
    return C.EXIT_OK


def cmd_verify(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review verify",
                                description="Перепроверка отчёта без модели: источник, цитаты, счётчики, паспорт.")
    p.add_argument("report", help="REPORT.json")
    p.add_argument("source", help="исходный файл, по которому строился отчёт")
    p.add_argument("--json", action="store_true", help="вывести результат JSON")
    args = p.parse_args(argv)
    from .engine import READERS
    from .runtime.modules import Modules

    mods = Modules()
    verifier = mods.get("verify_report")
    suffix = Path(args.source).suffix.lower()
    reader = mods.get(READERS[suffix]).func if suffix in READERS else None
    try:
        try:
            result = verifier.func(args.report, args.source, reader=reader)
        except TypeError:
            result = verifier.func(args.report, args.source)
    except (OSError, ValueError) as exc:
        print(f"verify: не удалось прочитать вход: {exc}", file=sys.stderr)
        return C.EXIT_VERIFY_FAILED
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        c = result.get("counts", {})
        print(f"verify: OK — источник, {c.get('evidence', 0)} опор, счётчики и паспорт согласованы "
              f"({verifier.label})")
    else:
        print(f"verify: найдено расхождений: {len(result['errors'])}", file=sys.stderr)
        for e in result["errors"][:50]:
            print(f"  - {e}", file=sys.stderr)
    return C.EXIT_OK if result["ok"] else C.EXIT_VERIFY_FAILED


def main(argv: Optional[list[str]] = None) -> int:
    _utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        _review_parser().print_help()
        return C.EXIT_OK if argv else C.EXIT_USAGE
    if argv[0] in ("--version", "-V"):
        print(f"bcc-review {__version__} (contract {C.SCHEMA_VERSION})")
        return C.EXIT_OK
    head = argv[0]
    # подкоманды не ломают обычный вызов INPUT OUTPUT.md: файл с именем подкоманды остаётся входом
    looks_like_file = Path(head).is_file() and len(argv) >= 2 and argv[1].lower().endswith((".md", ".markdown"))
    if head == "verify" and not looks_like_file:
        return cmd_verify(argv[1:])
    if head == "contract" and not looks_like_file:
        sys.stdout.write(C.schema_json())
        return C.EXIT_OK
    if head == "review" and not looks_like_file:
        argv = argv[1:]
    try:
        return cmd_review(argv)
    except SystemExit as exc:  # argparse
        return int(exc.code or 0) if isinstance(exc.code, int) else C.EXIT_USAGE
