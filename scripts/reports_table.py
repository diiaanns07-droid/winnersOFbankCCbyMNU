"""Собрать таблицу прогонов для reports/README.md из паспортов отчётов (report.json, схема bcc-review/2).

    python scripts/reports_table.py reports            # печать таблицы
    python scripts/reports_table.py reports --write    # вписать таблицу в reports/README.md между маркерами
    python scripts/reports_table.py reports --src cashback=evaluation/dev/.../source.md   # исходник не из release/input

Для каждого отчёта заново запускается `python -m bcc_review verify ОТЧЁТ.json ИСХОДНИК`: исходник берётся из
паспорта (document.file) и ищется в release/input/, рядом с отчётом и по пути из паспорта. Отчёты по документу
кейса (`release/input/requirements.md` или его PDF, сверка по SHA-256) дополнительно сверяются с эталоном К1–К5,
С1–С20: `python -m evaluation.v2.score` в строгом счёте без арбитра — детерминированно и без модели.
Сами отчёты скрипт не меняет.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
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


def _find_source(report: Path, data: dict, overrides: dict[str, str] | None = None) -> Path | None:
    stem = report.name[: -len(".json")]
    for key in (stem, stem.split(".", 1)[0]):
        if overrides and key in overrides:
            return Path(overrides[key])
    name = _get(data, "document", "file", default="") or ""
    candidates = [Path(name), ROOT / name, ROOT / "release" / "input" / Path(name).name, report.parent / Path(name).name]
    for c in candidates:
        if name and c.is_file():
            return c
    return None


def _rel(path: Path) -> str:
    """Путь исходника от корня репозитория (как его повторить), иначе как есть."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _verify(report: Path, source: Path | None) -> str:
    if source is None:
        return "нет исходника"
    r = subprocess.run([sys.executable, "-m", "bcc_review", "verify", str(report), str(source)], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return "OK" if r.returncode == 0 else f"ошибка (код {r.returncode})"


def _official_hashes() -> set[str]:
    out = set()
    for name in ("requirements.md", "requirements.pdf", "requirements.docx"):
        path = ROOT / "release" / "input" / name
        if path.is_file():
            out.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def _gold_cell(report: Path, data: dict) -> str:
    """Эталон кейса; у прогона с ответами владельца — с пометкой: дефекты после ответов сняты, а сверка считает
    исходные (в той же строке «0 критичных, можно» и «К 5/5 критичными» — без пометки это читалось бы как противоречие)."""
    cell = _score(report, data)
    answered = bool((_get(data, "run", "options", default={}) or {}).get("answers")) or bool(data.get("clarification"))
    return f"до ответов: {cell}" if answered and cell != "—" else cell


def _score(report: Path, data: dict) -> str:
    """К и С по эталону официального документа (строгий счёт без арбитра); для других документов — «—»."""
    if _get(data, "document", "sha256", default="") not in _official_hashes():
        return "—"
    if not (ROOT / "evaluation" / "v2" / "score.py").is_file():
        return "—"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "score.json"
        r = subprocess.run([sys.executable, "-m", "evaluation.v2.score", str(report.resolve()), "--out", str(out)],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0 or not out.is_file():
            return "—"
        gates = {g.get("metric"): g.get("value") for g in json.loads(out.read_text(encoding="utf-8")).get("gates", [])}
    k, kc, s, fp = (gates.get(m) for m in ("К1–К5 найдены", "из них критичными", "С1–С20 найдены", "критичных ложных"))
    if k is None or s is None:
        return "—"
    kc = str(kc).split("/", 1)[0] if kc is not None else "?"
    return f"К {k} (крит. {kc}) · С {s} · ложных крит. {fp if fp is not None else '?'}"


def _minutes(seconds) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    return (f"{s / 60:.1f} мин" if s >= 60 else f"{s:.0f} с").replace(".", ",")


def rows(reports_dir: Path, overrides: dict[str, str] | None = None) -> list[dict]:
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
        source = _find_source(path, data, overrides)
        models = run.get("models_used") or [run.get("model_requested") or "—"]
        commit = str(run.get("commit") or "—")[:7] + ("-dirty" if run.get("dirty") else "")
        out.append({
            "report": path.with_suffix(".md").name,
            "input": _rel(source) if source is not None else _get(data, "document", "file", default="—"),
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
            "gold": _gold_cell(path, data),
        })
    return out


def table(items: list[dict]) -> str:
    head = ("| Отчёт | Вход | Провайдер | Модель | Статус | Время | Вызовов (из кэша) | Требований | "
            "Замечаний крит./сущ./незн. | Разработка / тестирование | Эталон кейса | Коммит | verify |\n"
            "| :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | :--- | :--- | :--- | :--- | :--- |")
    lines = [head]
    for r in items:
        lines.append(f"| [{r['report']}]({r['report']}) | `{r['input']}` | {r['provider']} | {r['model']} | {r['status']} | "
                     f"{r['duration']} | {r['calls']} ({r['cached']}) | {r['requirements']} | {r['findings']} | "
                     f"{r['verdict']} | {r['gold']} | `{r['commit']}` | {r['verify']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="таблица прогонов из паспортов отчётов")
    p.add_argument("reports_dir", nargs="?", default=str(ROOT / "reports"))
    p.add_argument("--write", action="store_true", help="вписать таблицу в README.md каталога отчётов")
    p.add_argument("--src", action="append", default=[], metavar="ОТЧЁТ=ИСХОДНИК",
                   help="исходник для отчёта (имя файла отчёта без .json или его начало до точки)")
    args = p.parse_args(argv)
    d = Path(args.reports_dir)
    overrides = dict(item.split("=", 1) for item in args.src if "=" in item)
    items = rows(d, overrides)
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
