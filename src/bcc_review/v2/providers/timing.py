"""Разбор трассы прогона (№02): секунды, токены, попытки и паузы каждого вызова модели и критический путь.

    python -m bcc_review.v2.providers.timing                # последний прогон в runs/
    python -m bcc_review.v2.providers.timing runs/<id>      # конкретный прогон
    python -m bcc_review.v2.providers.timing runs/<id> --json

Для оператора с живым Gemini: после ``scripts/jury_check`` пришлите вывод этой команды целиком — по нему
видно, сколько думала модель на каждом этапе, были ли 429/503, ожидания окна запросов и откат модели.
Ключ в трассе не пишется.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# этапы, которые идут параллельно (pipeline._parallel_reviewers)
PARALLEL = ("lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency")
ORDER = ("segment", "parallel", "judge", "clarify", "recheck", "revise")


def latest_run(runs_dir: str | Path = "runs") -> Path | None:
    base = Path(runs_dir)
    dirs = [p for p in base.iterdir() if (p / "trace.jsonl").is_file()] if base.is_dir() else []
    return max(dirs, key=lambda p: (p / "trace.jsonl").stat().st_mtime) if dirs else None


def load(run_dir: str | Path) -> list[dict[str, Any]]:
    rows = []
    for line in (Path(run_dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def calls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Вызовы модели (успешные и ошибки) в порядке трассы; события (split, rpm_wait, fallback) — отдельно."""
    out = []
    for r in rows:
        if r.get("cached"):
            out.append({"stage": r.get("stage"), "cached": True, "seconds": 0.0, "model": r.get("model") or ""})
            continue
        if r.get("event") or "seconds" not in r:
            continue
        u = r.get("usage") or {}
        out.append({
            "stage": r.get("stage") or "", "model": r.get("model") or "", "seconds": float(r.get("seconds") or 0),
            "error": r.get("error") or "", "message": (r.get("message") or "")[:160],
            "in": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
            "thinking": int(u.get("thinking_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0),
            "turns": int(u.get("num_turns") or 0), "attempts": list(u.get("attempts") or []),
            "rpm_wait_s": float(u.get("rpm_wait_s") or 0), "level": u.get("thinking") or "",
            "repair": bool(r.get("repair")), "schema_errors": list(r.get("schema_errors") or []),
        })
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cs = calls(rows)
    by_stage: dict[str, dict[str, Any]] = {}
    for c in cs:
        st = by_stage.setdefault(c["stage"], {"calls": 0, "seconds": 0.0, "out": 0, "thinking": 0, "errors": 0})
        st["calls"] += 0 if c.get("cached") else 1
        st["seconds"] = round(st["seconds"] + c["seconds"], 1)
        st["out"] += c.get("out", 0)
        st["thinking"] += c.get("thinking", 0)
        st["errors"] += 1 if c.get("error") else 0
    par = max((by_stage[s]["seconds"] for s in PARALLEL if s in by_stage), default=0.0)
    crit = {"segment": by_stage.get("segment", {}).get("seconds", 0.0), "parallel": par,
            "judge": by_stage.get("judge", {}).get("seconds", 0.0), "clarify": by_stage.get("clarify", {}).get("seconds", 0.0)}
    events = [r for r in rows if r.get("event")]
    return {"calls": cs, "stages": by_stage, "critical_path_s": round(sum(crit.values()), 1), "critical": crit,
            "events": [{k: v for k, v in e.items() if k != "t"} for e in events],
            "tokens_out": sum(c.get("out", 0) for c in cs), "thinking": sum(c.get("thinking", 0) for c in cs),
            "errors": sum(1 for c in cs if c.get("error"))}


def render(run_dir: Path, s: dict[str, Any]) -> str:
    lines = [f"Прогон: {run_dir}", "", "Вызовы модели:",
             f"  {'этап':15} {'модель':24} {'с':>6} {'вход':>7} {'выход':>7} {'рассужд.':>8} {'кэш':>7}  примечания"]
    for c in s["calls"]:
        if c.get("cached"):
            lines.append(f"  {c['stage']:15} {c['model'][:24]:24} {'кэш':>6}")
            continue
        notes = []
        if c["error"]:
            notes.append(f"ОШИБКА {c['error']}: {c['message']}")
        if c["level"]:
            notes.append(f"рассуждение {c['level']}")
        if c["turns"] > 2:
            notes.append(f"ходов CLI {c['turns']}")
        if c["rpm_wait_s"]:
            notes.append(f"ждал окно {c['rpm_wait_s']:.0f} с")
        if c["attempts"]:
            notes.append("попытки: " + "; ".join(c["attempts"]))
        if c["repair"]:
            notes.append("починка по схеме")
        if c["schema_errors"]:
            notes.append("не по схеме: " + "; ".join(c["schema_errors"])[:120])
        lines.append(f"  {c['stage']:15} {c['model'][:24]:24} {c['seconds']:6.1f} {c['in']:7} {c['out']:7} "
                     f"{c['thinking']:8} {c['cache_read']:7}  {', '.join(notes)}")
    cr = s["critical"]
    lines += ["", f"Критический путь: {s['critical_path_s']:.0f} с = нарезка {cr['segment']:.0f} + параллельные "
                  f"(самый долгий) {cr['parallel']:.0f} + судья {cr['judge']:.0f} + вопросы {cr['clarify']:.0f}",
              f"Выход всего: {s['tokens_out']} ток., из них рассуждения {s['thinking']}; ошибок вызова: {s['errors']}"]
    shown = [e for e in s["events"] if e.get("event") in ("split", "expand_output", "fallback_model", "rpm_wait")]
    if shown:
        lines.append("События: " + "; ".join(
            f"{e.get('stage')} {e.get('event')}" + (f" {e.get('seconds')} с" if e.get("seconds") else "")
            for e in shown[:20]))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.providers.timing",
                                 description="Секунды и токены каждого вызова модели по trace.jsonl прогона")
    ap.add_argument("run", nargs="?", help="каталог runs/<id> (по умолчанию — последний прогон)")
    ap.add_argument("--json", action="store_true", help="вывести JSON")
    a = ap.parse_args(argv)
    run = Path(a.run) if a.run else latest_run()
    if run is None or not (run / "trace.jsonl").is_file():
        print("Нет trace.jsonl: укажите каталог прогона runs/<id>.", file=sys.stderr)
        return 1
    s = summary(load(run))
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(render(run, s))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
