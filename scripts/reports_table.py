"""Собрать таблицу прогонов для reports/README.md из паспортов отчётов (report.json, схема bcc-review/2).

    python scripts/reports_table.py reports            # печать таблицы
    python scripts/reports_table.py reports --write    # вписать таблицу в reports/README.md между маркерами

Для каждого отчёта заново запускается `python -m bcc_review verify ОТЧЁТ.json ИСХОДНИК`: исходник берётся из
паспорта (document.file) и ищется в release/input/, рядом с отчётом и по пути из паспорта.
Сами отчёты скрипт не меняет.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- таблица прогонов: начало (scripts/reports_table.py) -->"
END = "<!-- таблица прогонов: конец -->"

STATUS_RU = {"complete": "полный", "partial": "частичный", "failed": "ошибка"}
VERDICT_RU = {"no": "нельзя", "conditional": "условно", "yes": "можно"}


def _get(d: dict, *path, default=None):
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


def _find_source(report: Path, data: dict) -> Path | None:
    name = _get(data, "document", "file", default="") or ""
    candidates = [Path(name), ROOT / name, ROOT / "release" / "input" / Path(name).name, report.parent / Path(name).name]
    for c in candidates:
        if name and c.is_file():
            return c
    return None


def _verify(report: Path, source: Path | None) -> str:
    if source is None:
        return "нет исходника"
    r = subprocess.run([sys.executable, "-m", "bcc_review", "verify", str(report), str(source)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return "OK" if r.returncode == 0 else f"ошибка (код {r.returncode})"


def _minutes(seconds) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    return f"{s / 60:.1f} мин" if s >= 60 else f"{s:.0f} с"


def rows(reports_dir: Path) -> list[dict]:
    out = []
    for path in sorted(reports_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not str(data.get("schema", "")).startswith("bcc-review/"):
            continue
        run = data.get("run", {})
        findings = _get(data, "summary", "findings", default={}) or {}
        source = _find_source(path, data)
        models = run.get("models_used") or [run.get("model_requested") or "—"]
        commit = str(run.get("commit") or "—")[:7] + ("-dirty" if run.get("dirty") else "")
        out.append({
            "report": path.with_suffix(".md").name,
            "input": _get(data, "document", "file", default="—"),
            "format": _get(data, "document", "format", default="—"),
            "provider": run.get("provider", "—"),
            "model": ", ".join(str(m) for m in models),
            "status": STATUS_RU.get(run.get("status"), run.get("status", "—")),
            "duration": _minutes(run.get("duration_s")),
            "calls": _get(run, "calls", "total", default="—"),
            "cached": _get(run, "calls", "cached", default="—"),
            "requirements": _get(data, "summary", "requirements", default="—"),
            "findings": f"{findings.get('critical', 0)}/{findings.get('major', 0)}/{findings.get('minor', 0)}",
            "verdict": "{} / {}".format(VERDICT_RU.get(_get(data, "verdict", "development"), "—"),
                                        VERDICT_RU.get(_get(data, "verdict", "testing"), "—")),
            "commit": commit,
            "version": run.get("version", "—"),
            "verify": _verify(path, source),
        })
    return out


def table(items: list[dict]) -> str:
    head = ("| Отчёт | Вход | Провайдер | Модель | Статус | Время | Вызовов (из кэша) | Требований | "
            "Замечаний крит./сущ./незн. | Разработка / тестирование | Коммит | verify |\n"
            "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- | :--- | :--- |")
    lines = [head]
    for r in items:
        lines.append(f"| [{r['report']}]({r['report']}) | `{r['input']}` | {r['provider']} | {r['model']} | {r['status']} | "
                     f"{r['duration']} | {r['calls']} ({r['cached']}) | {r['requirements']} | {r['findings']} | "
                     f"{r['verdict']} | `{r['commit']}` | {r['verify']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="таблица прогонов из паспортов отчётов")
    p.add_argument("reports_dir", nargs="?", default=str(ROOT / "reports"))
    p.add_argument("--write", action="store_true", help="вписать таблицу в README.md каталога отчётов")
    args = p.parse_args(argv)
    d = Path(args.reports_dir)
    items = rows(d)
    text = table(items)
    if not args.write:
        print(text)
        return 0 if all(r["verify"] == "OK" for r in items) else 4
    readme = d / "README.md"
    body = readme.read_text(encoding="utf-8") if readme.exists() else f"# Отчёты агента\n\n{BEGIN}\n{END}\n"
    if BEGIN not in body or END not in body:
        body = body.rstrip() + f"\n\n{BEGIN}\n{END}\n"
    before, rest = body.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    readme.write_text(f"{before}{BEGIN}\n{text}\n{END}{after}", encoding="utf-8")
    print(f"таблица из {len(items)} прогонов записана в {readme}")
    return 0 if all(r["verify"] == "OK" for r in items) else 4


if __name__ == "__main__":
    raise SystemExit(main())
