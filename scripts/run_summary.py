"""Короткая сводка прогона агента по report.json — для scripts/run_official.* и scripts/jury_check.*.

    python scripts/run_summary.py ОТЧЁТ.json [--score SCORE.json] [--max-minutes N] [--max-calls N]
        [--verify-code N] [--seconds N] [--check]

Печатает статус, фактическую модель, вызовы, время, токены, вердикт и число замечаний; со `--score` — К1–К5 и
С1–С20 по эталону официального документа (`python -m evaluation.v2.score … --out SCORE.json`).
С `--check` код выхода 1, если прогон не `complete`, verify не прошёл или превышены время и число вызовов.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERDICT = {"yes": "можно", "conditional": "условно", "no": "нельзя"}
STATUS = {"complete": "полностью", "partial": "частично", "failed": "не удался"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mark(ok: bool) -> str:
    return "да " if ok else "НЕТ"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report")
    ap.add_argument("--score", help="score.json счётчика evaluation.v2.score")
    ap.add_argument("--max-minutes", type=float, default=0, help="предел времени прогона, мин (0 — не проверять)")
    ap.add_argument("--max-calls", type=int, default=0, help="предел обращений к модели (0 — не проверять)")
    ap.add_argument("--verify-code", type=int, default=None, help="код выхода verify")
    ap.add_argument("--seconds", type=float, default=None, help="время прогона по часам скрипта, с")
    ap.add_argument("--check", action="store_true", help="ненулевой код, если ворота не пройдены")
    args = ap.parse_args(argv)

    path = Path(args.report)
    if not path.is_file():
        print(f"Отчёт не найден: {path}. Прогон не записал JSON — смотрите сообщения выше.", file=sys.stderr)
        return 1
    rep = _load(path)
    run = rep.get("run", {})
    summary = rep.get("summary", {})
    verdict = rep.get("verdict", {})
    calls = run.get("calls", {}) if isinstance(run.get("calls"), dict) else {"total": run.get("calls", 0)}
    tokens = run.get("tokens", {}) or {}
    status = run.get("status", "?")
    seconds = float(run.get("duration_s") or 0)
    if args.seconds is not None:
        seconds = max(seconds, args.seconds)
    models = ", ".join(run.get("models_used") or []) or "—"
    fnd = summary.get("findings", {})

    rows: list[tuple[str, str, bool | None]] = []
    rows.append(("статус прогона", f"{status} ({STATUS.get(status, status)})", status == "complete"))
    rows.append(("провайдер / фактическая модель", f"{run.get('provider', '?')} / {models}", None))
    ok_time = None if not args.max_minutes else seconds <= args.max_minutes * 60
    limit = f" (предел {args.max_minutes:g} мин)" if args.max_minutes else ""
    rows.append(("время", f"{seconds / 60:.1f} мин{limit}", ok_time))
    total = int(calls.get("total") or 0)
    ok_calls = None if not args.max_calls else total <= args.max_calls
    extra = []
    for key, label in (("cached", "из кэша"), ("failed", "неудачных"), ("split", "делений")):
        if calls.get(key):
            extra.append(f"{label} {calls[key]}")
    limit = f", предел {args.max_calls}" if args.max_calls else ""
    rows.append(("обращений к модели", f"{total}{' (' + ', '.join(extra) + ')' if extra else ''}{limit}", ok_calls))
    cost = float(run.get("cost_usd") or 0)
    rows.append(("токены вход / выход", f"{tokens.get('input', 0):,} / {tokens.get('output', 0):,}".replace(",", " ")
                 + (f"; стоимость ${cost:.2f}" if cost else ""), None))
    rows.append(("вердикт", f"разработка — {VERDICT.get(verdict.get('development'), '?')}, "
                            f"тестирование — {VERDICT.get(verdict.get('testing'), '?')}", None))
    rows.append(("требований / замечаний", f"{summary.get('requirements', 0)} / "
                 f"{sum(fnd.values()) if fnd else 0} (критичных {fnd.get('critical', 0)}, "
                 f"существенных {fnd.get('major', 0)}, незначительных {fnd.get('minor', 0)})", None))
    qv, qt = summary.get("quotes_verified", 0), summary.get("quotes_total", 0)
    rows.append(("цитаты сверены программой", f"{qv} из {qt}", qv == qt))
    if args.verify_code is not None:
        rows.append(("verify (цитаты и паспорт заново)", "ОК" if args.verify_code == 0 else f"код {args.verify_code}",
                     args.verify_code == 0))

    if args.score and Path(args.score).is_file():
        score = _load(Path(args.score))
        for gate in score.get("gates", []):
            if gate.get("metric") in ("К1–К5 найдены", "из них критичными", "С1–С20 найдены", "критичных ложных"):
                rows.append((f"эталон: {gate['metric']}", str(gate.get("value")), None))

    width = max(len(r[0]) for r in rows)
    print()
    print("Сводка прогона")
    for label, value, ok in rows:
        mark = "   " if ok is None else _mark(ok)
        print(f"  {mark} {label.ljust(width)}  {value}")
    for warning in (run.get("warnings") or [])[:5]:
        print(f"  !   {warning}")
    print(f"  Отчёт: {path.with_suffix('.md')}  (HTML: {path.with_suffix('.html')})")

    failed = [label for label, _, ok in rows if ok is False]
    if failed:
        print("Не пройдено: " + "; ".join(failed))
    elif args.check:
        print("Все проверки пройдены.")
    return 1 if (args.check and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
