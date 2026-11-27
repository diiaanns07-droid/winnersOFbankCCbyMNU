"""Командная строка v2.

    python -m bcc_review ВХОД ОТЧЁТ.md [--provider P] [--model M] [--export html,jira,docx,pdf]
    python -m bcc_review ВХОД ОТЧЁТ.md --replay runs/<id>     (отчёт из сохранённых ответов, без модели)
    python -m bcc_review stage ЭТАП --doc ВХОД --from runs/<id> [--provider P --model M] [--out ОТЧЁТ.md]
    python -m bcc_review verify ОТЧЁТ.json ВХОД
    python -m bcc_review doctor [--live] [--provider P] [--model M]

Этапы для ``stage``: segment, lens_analyst, lens_qa, lens_architect, lens_risk, consistency, judge, clarify.
Остальные этапы берутся из ``--from`` как есть; код (правила, сверка цитат, вердикт, отчёт) пересчитывается.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .types import LENSES

STAGE_NAMES = ["segment"] + [f"lens_{x}" for x in LENSES] + ["consistency", "judge", "clarify"]
PROVIDERS = ["auto", "claude_cli", "gemini", "anthropic", "openai", "mock", "offline"]


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load_env() -> None:
    try:
        from .providers import doctor
        if not doctor.load_dotenv(".env"):
            # запуск не из корня репозитория: .env в корне (src/bcc_review/v2/__main__.py → четыре уровня вверх)
            doctor.load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    except Exception:  # noqa: BLE001
        pass


# Сообщения argparse по-русски: argparse берёт их через gettext (``argparse._``) в момент вызова.
_ARGPARSE_RU = {
    "usage: ": "использование: ",
    "positional arguments": "аргументы",
    "options": "параметры",
    "optional arguments": "параметры",
    "show this help message and exit": "показать эту справку и выйти",
    "the following arguments are required: %s": "не хватает аргументов: %s",
    "unrecognized arguments: %s": "неизвестные параметры: %s",
    "invalid %(type)s value: %(value)r": "недопустимое значение %(value)r",
    "invalid choice: %(value)r (choose from %(choices)s)": "недопустимое значение %(value)r (допустимо: %(choices)s)",
    "invalid choice: %(value)r, maybe you meant %(closest)r?": "недопустимое значение %(value)r — может быть, %(closest)r?",
    "argument %(argument_name)s: %(message)s": "параметр %(argument_name)s: %(message)s",
    "%(prog)s: error: %(message)s\n": "%(prog)s: ошибка: %(message)s\n",
    "expected one argument": "нужно одно значение",
    "ambiguous option: %(option)s could match %(matches)s": "неоднозначный параметр %(option)s: подходит %(matches)s",
    "not allowed with argument %s": "нельзя вместе с %s",
}


def _russian_argparse() -> None:
    orig = getattr(argparse, "_", None)
    if getattr(orig, "_bcc_ru", False) or orig is None:
        return

    def ru(message: str) -> str:
        return _ARGPARSE_RU.get(message) or orig(message)

    ru._bcc_ru = True  # type: ignore[attr-defined]
    argparse._ = ru  # type: ignore[attr-defined]


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", default="auto",
                   help="auto (по ключам в .env), claude_cli, gemini, anthropic, openai, mock, offline")
    p.add_argument("--model", help="модель провайдера (по умолчанию — из .env или встроенная)")
    p.add_argument("--fallback-models", default="", help="запасные модели через запятую")
    p.add_argument("--max-calls", type=int, default=16, help="бюджет вызовов модели на прогон (по умолчанию 16)")
    p.add_argument("--max-seconds", type=float, default=1500.0, help="бюджет времени прогона, с")
    p.add_argument("--timeout", type=float, default=600.0, help="таймаут одного вызова модели, с")
    p.add_argument("--stage-timeout", type=float, default=480.0,
                   help="лимит времени одного этапа, с (0 — без лимита); по умолчанию 480")
    p.add_argument("--rpm", type=float, help="не больше стольких запросов к модели в минуту (Gemini по умолчанию 10; 0 — без паузы)")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"],
                   help="глубина рассуждений модели для claude_cli")
    p.add_argument("--no-cache", action="store_true", help="не брать ответы модели из кэша .bcc_cache/v2")
    p.add_argument("--cache-dir", help="каталог кэша ответов модели")
    p.add_argument("--runs-dir", default="runs", help="каталог артефактов прогонов (по умолчанию runs)")
    p.add_argument("--run-id", help="имя каталога прогона")
    p.add_argument("--mock-dir", help="каталог ответов mock-провайдера")
    p.add_argument("--export", default="", help="доп. форматы через запятую: html,jira,docx,pdf")
    p.add_argument("--no-html", action="store_true", help="не писать HTML-отчёт рядом с .md")
    p.add_argument("--passes", type=int, default=1, help="сколько раз запускать линзы (2 — для стабильности)")
    p.add_argument("--lenses", default=",".join(LENSES), help="какие линзы запускать, через запятую")
    p.add_argument("--no-consistency", action="store_true", help="без проверки набора целиком")
    p.add_argument("--no-clarify", action="store_true", help="без вопросов владельцу")
    p.add_argument("--fast-start", dest="fast_start", action="store_true", default=None,
                   help="рецензенты не ждут нарезку моделью: стартуют по таблице эвристики (по умолчанию — да)")
    p.add_argument("--no-fast-start", dest="fast_start", action="store_false",
                   help="рецензенты ждут нарезку моделью")
    p.add_argument("--max-cost", metavar="ПОТОЛОК",
                   help="потолок на прогон: «0.5» — доллары, «200k» — токены; при превышении — частичный отчёт")
    p.add_argument("-q", "--quiet", action="store_true", help="без хода выполнения в консоли")


def _opts(a: argparse.Namespace) -> dict:
    return {
        "provider": a.provider, "model": a.model,
        "fallback_models": [x.strip() for x in (a.fallback_models or "").split(",") if x.strip()],
        "max_calls": a.max_calls, "max_seconds": a.max_seconds, "timeout": a.timeout, "cache": not a.no_cache,
        "stage_timeout": a.stage_timeout, "rpm": a.rpm, "effort": a.effort,
        "cache_dir": a.cache_dir, "runs_dir": a.runs_dir, "run_id": a.run_id, "mock_dir": a.mock_dir,
        "export": [x.strip().lower() for x in (a.export or "").split(",") if x.strip()], "html": not a.no_html,
        "passes": a.passes, "lenses": [x.strip() for x in a.lenses.split(",") if x.strip()],
        "consistency": not a.no_consistency, "clarify": not a.no_clarify, "quiet": a.quiet,
        "fast_start": getattr(a, "fast_start", None),
        "answers": getattr(a, "answers", None), "revise": getattr(a, "revise", False),
        "replay": getattr(a, "replay", None), "runs": getattr(a, "runs", 1) or 1,
        **parse_cost(getattr(a, "max_cost", None)),
    }


def parse_cost(value: str | None) -> dict:
    """``--max-cost``: «0.5» или «$0.5» — доллары; «200k», «1.5m», «300000t», «200к» — токены (вход + выход)."""
    if not value:
        return {}
    v = str(value).strip().lower().replace(",", ".").replace(" ", "")
    import re
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k|к|m|м|t|т|tok|ток|токенов)", v)
    if m:
        mult = {"k": 1e3, "к": 1e3, "m": 1e6, "м": 1e6}.get(m.group(2), 1)
        return {"max_tokens": int(float(m.group(1)) * mult)}
    m = re.fullmatch(r"\$?(\d+(?:\.\d+)?)\$?(usd)?", v)
    if m and float(m.group(1)) > 0:
        return {"max_cost_usd": float(m.group(1))}
    raise ValueError(value)


def _log(quiet: bool):
    import threading
    lock = threading.Lock()

    def log(msg: str) -> None:
        if not quiet:
            with lock:
                print(msg, file=sys.stderr, flush=True)
    return log


def _print_summary(report: dict, written: dict) -> None:
    try:
        from .render import console
        print(console.summary(report, md_path=written.get("md"), json_path=written.get("json")))
        if written.get("html"):
            print(f"HTML: {written['html']}")
        return
    except Exception:  # noqa: BLE001
        pass
    run, v = report.get("run", {}), report.get("verdict", {})
    sev = (report.get("summary") or {}).get("findings") or {}
    print(f"Отчёт: {written.get('md')} (+ {', '.join(k for k in written if k != 'md')})")
    print(f"Прогон: {run.get('status')}, провайдер {run.get('provider')}, вызовов {run.get('calls', {}).get('total')}, "
          f"{run.get('duration_s')} с")
    print(f"Дефектов: критичных {sev.get('critical', 0)}, существенных {sev.get('major', 0)}, "
          f"незначительных {sev.get('minor', 0)}")
    print(f"Разработка: {v.get('development')}; тестирование: {v.get('testing')}")


def _exit_code(report: dict, fail_on: str | None) -> int:
    status = report.get("run", {}).get("status")
    if status == "failed" or report.get("run", {}).get("model_error"):
        return 3
    if fail_on == "partial" and status == "partial":
        return 3
    v = report.get("verdict", {})
    if fail_on == "blocker" and "no" in (v.get("development"), v.get("testing")):
        return 2
    return 0


def _output_path(input_path: str, output: str) -> Path | None:
    """Путь отчёта: папка → отчёт в ней под именем входа; путь входа и недоступный каталог — понятная ошибка."""
    out = Path(output)
    if out.is_dir() or output.endswith(("/", "\\")):
        out = out / (Path(input_path).stem + ".md")
    src = Path(input_path).resolve()
    if src in {out.resolve(), out.with_suffix(".json").resolve(), out.with_suffix(".html").resolve()}:
        print(f"Путь отчёта совпадает с файлом требований: {input_path}. Укажите другой, например "
              f"reports/my/{Path(input_path).stem}.md", file=sys.stderr)
        return None
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        probe = out.parent / f".bcc_write_check_{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        import errno
        why = {errno.EACCES: "нет прав на запись", errno.EPERM: "нет прав на запись",
               errno.EROFS: "диск только для чтения", errno.ENOSPC: "нет места на диске",
               errno.ENOENT: "такой папки нет, и создать её нельзя",
               errno.ENOTDIR: "в пути есть файл там, где должна быть папка",
               errno.EEXIST: "в пути есть файл там, где должна быть папка"}.get(exc.errno, "ошибка записи")
        print(f"Не удаётся записать отчёт в «{out.parent}»: {why}. Укажите другой путь, например "
              f"reports/my/{Path(input_path).stem}.md", file=sys.stderr)
        return None
    return out


def cmd_review(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review",
                                description="Статическое ревью требований: дефекты с цитатами, вопросы, готовность "
                                            "к разработке и тестированию.",
                                epilog="Другие команды: stage ЭТАП --doc ВХОД --from runs/<id> — перезапуск этапа; "
                                       "verify ОТЧЁТ.json ВХОД — перепроверка цитат; doctor [--live] — проверка "
                                       "настроек модели. Старый движок: --engine v1.")
    p.add_argument("input", metavar="ВХОД", help="файл требований: .md, .txt, .pdf, .docx, .html")
    p.add_argument("output", metavar="ОТЧЁТ.md", help="путь отчёта .md; рядом пишутся .json и .html")
    _common(p)
    p.add_argument("--answers", metavar="ФАЙЛ", help="ответы на вопросы отчёта: пересмотр дефектов «до/после»")
    p.add_argument("--revise", action="store_true", help="исправленная редакция ТЗ «было → стало»")
    p.add_argument("--fail-on", choices=["blocker", "partial"], help="ненулевой код выхода при блокере/неполном прогоне")
    p.add_argument("--replay", metavar="runs/<id>",
                   help="собрать отчёт заново из сохранённых ответов этапов прогона: без ключа, сети и вызовов модели")
    p.add_argument("--runs", type=int, default=1, metavar="N",
                   help="N независимых проходов рецензентов и судьи: у каждого дефекта устойчивость k/N; в реестр "
                        "идут найденные не меньше чем в половине проходов, остальные — в приложение")
    a = p.parse_args(argv)
    try:
        parse_cost(a.max_cost)
    except ValueError:
        print(f"--max-cost: не понял «{a.max_cost}»; примеры: 0.5 (доллары), 200k (токены)", file=sys.stderr)
        return 2
    if a.runs < 1 or a.runs > 9:
        print("--runs: от 1 до 9", file=sys.stderr)
        return 2
    if a.runs > 1 and (a.answers or a.revise or a.replay):
        print("--runs нельзя вместе с --answers, --revise и --replay: сначала соберите отчёт с устойчивостью, "
              "затем ответы — отдельным запуском", file=sys.stderr)
        return 2
    if not Path(a.input).is_file():
        print(f"Файл не найден: {a.input}", file=sys.stderr)
        return 2
    if a.answers and not Path(a.answers).is_file():
        print(f"Файл ответов не найден: {a.answers}", file=sys.stderr)
        return 2
    unknown = [x for x in (y.strip() for y in (a.lenses or "").split(",")) if x and x not in LENSES]
    if unknown:
        print(f"Неизвестная линза: {', '.join(unknown)}; допустимо: {', '.join(LENSES)}", file=sys.stderr)
        return 2
    if a.replay:
        from .runs import RunDir
        src = RunDir(a.replay, create=False)
        if not src.stages.is_dir() or not any(src.stages.glob("*.json")):
            print(f"Нет сохранённых этапов в «{a.replay}»: укажите каталог прогона runs/<id> (в нём папка stages)",
                  file=sys.stderr)
            return 2
        a.replay = str(src.path)
    out = _output_path(a.input, a.output)
    if out is None:
        return 2
    a.output = str(out)
    from . import pipeline
    report, written = pipeline.review(a.input, a.output, _opts(a), log=_log(a.quiet))
    _print_summary(report, written)
    if (report.get("run") or {}).get("model_error"):
        called = int(((report.get("run") or {}).get("calls") or {}).get("total") or 0)
        lead = ("Модель перестала отвечать во время прогона, отчёт неполный. " if called
                else "Модель не вызывалась, отчёт построен только правилами. ")
        print("\n" + lead + report["run"]["model_error"], file=sys.stderr)
    return _exit_code(report, a.fail_on)


def cmd_stage(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review stage",
                                description="Перезапуск одного этапа на сохранённых входах прогона.")
    p.add_argument("stage", choices=STAGE_NAMES)
    p.add_argument("--doc", required=True, help="файл требований")
    p.add_argument("--from", dest="from_run", required=True, help="каталог прогона runs/<id> с файлами этапов")
    p.add_argument("--out", help="куда записать отчёт .md (по умолчанию runs/<новый id>/report.md)")
    p.add_argument("--downstream", action="store_true",
                   help="перезапустить и следующие этапы модели (для segment — всё; для линз — судью и вопросы)")
    _common(p)
    a = p.parse_args(argv)
    from . import pipeline
    from .runs import RunDir
    src = RunDir(a.from_run, create=False)
    if not src.stages.is_dir():
        print(f"Нет каталога этапов: {src.stages}", file=sys.stderr)
        return 2
    rerun = {a.stage}
    if a.downstream:
        idx = STAGE_NAMES.index(a.stage)
        tail = STAGE_NAMES[idx + 1:]
        if a.stage.startswith("lens_") or a.stage == "consistency":
            tail = ["judge", "clarify"]
        rerun |= set(tail)
    opts = _opts(a)
    run = RunDir(opts["runs_dir"], opts.get("run_id"))
    opts["run_id"] = run.run_id
    out = Path(a.out) if a.out else run.path / "report.md"
    report, written = pipeline.review(a.doc, out, opts, reuse=src, rerun=rerun, log=_log(a.quiet))
    st = (report.get("run") or {}).get("stage_stats", {}).get(a.stage, {})
    print(f"Этап {a.stage}: {report['run']['stages'].get(a.stage)}, вызовов {st.get('calls', 0)}, "
          f"{st.get('seconds', 0)} с, кандидатов {st.get('candidates', 0)}")
    print(f"Выход этапа: {run.path / 'stages' / (a.stage + '.json')}")
    _print_summary(report, written)
    return 0


def cmd_verify(argv: list[str]) -> int:
    from . import verify
    return verify.main(argv)


def cmd_doctor(argv: list[str]) -> int:
    from .providers import doctor
    return doctor.main(argv)


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    _russian_argparse()
    argv = list(sys.argv[1:] if argv is None else argv)
    _load_env()
    if argv and argv[0] in ("--version", "version"):
        print(f"BCC Review {__version__}")
        return 0
    if argv and argv[0] == "stage":
        return cmd_stage(argv[1:])
    if argv and argv[0] == "verify":
        return cmd_verify(argv[1:])
    if argv and argv[0] == "doctor":
        return cmd_doctor(argv[1:])
    if argv and argv[0] == "review":
        argv = argv[1:]
    return cmd_review(argv)


if __name__ == "__main__":
    raise SystemExit(main())
