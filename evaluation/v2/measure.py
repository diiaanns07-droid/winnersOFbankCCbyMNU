"""Замер одной командой: прогон агента на официальном документе → оценка с арбитром → история → RESULTS.md.

    python -m evaluation.v2.measure --label "замер 1" --provider claude_cli --model sonnet
    python -m evaluation.v2.measure --label "замер 1" --from-report runs/<id>/report.json   # без прогона
    python -m evaluation.v2.measure --table                                                  # только таблица

Результат: `evaluation/v2/measurements/<slug>/{report.json, report.md, score.json, score.md, agent.log}`,
строка в `evaluation/v2/history.jsonl`, таблица истории в `evaluation/v2/RESULTS.md` между метками.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import score as sc
from .common import ROOT

MEAS = ROOT / "evaluation" / "v2" / "measurements"
HISTORY = ROOT / "evaluation" / "v2" / "history.jsonl"
RESULTS = ROOT / "evaluation" / "v2" / "RESULTS.md"
DEFAULT_INPUT = ROOT / "release" / "input" / "requirements.md"
DEFAULT_CMD = "{python} -m bcc_review {input} {output} --provider {provider} --model {model}"
START, END = "<!-- history:start -->", "<!-- history:end -->"


def slugify(label: str) -> str:
    tr = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeejzijklmnoprstufhccss_y_eua")
    s = label.lower().translate(tr)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:60] or "run"


def run_agent(inp: Path, out_dir: Path, cmd_tpl: str, provider: str, model: str, timeout: int) -> tuple[int, str, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = cmd_tpl.format(python=shlex.quote(sys.executable), input=shlex.quote(str(inp)),
                         output=shlex.quote(str(out_dir / "report.md")), provider=provider, model=model)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT), env=env)
        rc, log = r.returncode, f"$ {cmd}\nrc={r.returncode}\n--- stdout\n{r.stdout[-6000:]}\n--- stderr\n{r.stderr[-6000:]}"
    except subprocess.TimeoutExpired:
        rc, log = -9, f"$ {cmd}\nтаймаут {timeout} с"
    dt = time.monotonic() - t0
    (out_dir / "agent.log").write_text(log, encoding="utf-8")
    return rc, log, dt


def find_run_dir(report_json: Path, log: str) -> Path | None:
    """Каталог runs/<id> прогона: из отчёта (run.run_dir / run.id) или из лога агента."""
    try:
        rep = json.loads(report_json.read_text(encoding="utf-8"))
        run = rep.get("run") or {}
        for k in ("run_dir", "dir"):
            if run.get(k) and Path(run[k]).exists():
                return Path(run[k])
        rid = run.get("run_id") or run.get("id")
        if rid and (ROOT / "runs" / str(rid)).exists():
            return ROOT / "runs" / str(rid)
    except (OSError, json.JSONDecodeError):
        pass
    m = re.findall(r"(runs/[\w\-.:]+)", log or "")
    for cand in reversed(m):
        p = ROOT / cand
        if p.is_dir():
            return p
    return None


def results_table(history: Path = HISTORY) -> str:
    rows = []
    if history.exists():
        rows = [json.loads(x) for x in history.read_text(encoding="utf-8").splitlines() if x.strip()]
    L = ["| Время | Замер | Движок / модель | Статус | К | К крит. | С | Ключевые 25 | М | Замечаний (к/с/н) | Дубли | "
         "Вне эталона верно/ложно | Полезных | Крит. ложных | Цитаты не найдены | Англ. | Общие фразы | Строк MD | Мин | Вызовов |",
         "| :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        bs = r.get("by_severity") or {}
        eng = f"{r['version']}, {r.get('provider') or '—'}" + (f" / {r['model']}" if r.get("model") else "")
        dur = r.get("duration_s")
        pu = r.get("precision_useful")
        at = r.get("at") or ""
        at = f"{at[8:10]}.{at[5:7]} {at[11:16]}" if len(at) >= 16 else at
        L.append(f"| {at} | {r['label']} | {eng} | {r.get('status')} | "
                 f"{r['K']}/5 | {r['K_as_critical']} | {r['C']}/20 | {r['key25']}/25 | {r['M']}/8 | "
                 f"{r['findings']} ({bs.get('critical', 0)}/{bs.get('major', 0)}/{bs.get('minor', 0)}) | {r['duplicates']} | "
                 f"{r['outside_real']}/{r['outside_false']} | {'—' if pu is None else f'{100 * pu:.0f} %'} | "
                 f"{r['critical_false']} | {r['quotes_missing']}/{r['quotes_total']} | {r['english']} | {r['generic']} | "
                 f"{r.get('report_md_lines') if r.get('report_md_lines') is not None else '—'} | "
                 f"{'—' if dur is None else f'{dur / 60:.1f}'} | {r.get('calls') if r.get('calls') is not None else '—'} |")
    return "\n".join(L)


def update_results(history: Path = HISTORY, results: Path = RESULTS) -> None:
    text = results.read_text(encoding="utf-8")
    table = results_table(history)
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), START + "\n" + table + "\n" + END, text, flags=re.S)
    else:
        text += f"\n{START}\n{table}\n{END}\n"
    results.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.measure", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label")
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--provider", default="claude_cli")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--cmd", default=DEFAULT_CMD)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--from-report", help="готовый report.json (без прогона агента)")
    ap.add_argument("--run-dir", help="каталог runs/<id> для разбора промахов")
    ap.add_argument("--arbiter", default="sonnet")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--table", action="store_true", help="только пересобрать таблицу истории в RESULTS.md")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.table:
        update_results()
        print(results_table())
        return 0
    if not a.label:
        ap.error("нужен --label")
    dest = MEAS / slugify(a.label)
    dest.mkdir(parents=True, exist_ok=True)
    log = ""
    if a.from_report:
        src = Path(a.from_report)
        shutil.copy(src, dest / "report.json")
        for md in (src.with_suffix(".md"), src.parent / "report.md"):
            if md.exists():
                shutil.copy(md, dest / "report.md")
                break
        run_dir = Path(a.run_dir) if a.run_dir else find_run_dir(src, "")
    else:
        rc, log, dt = run_agent(Path(a.input), dest, a.cmd, a.provider, a.model, a.timeout)
        print(f"агент: rc={rc}, {dt / 60:.1f} мин")
        if not (dest / "report.json").exists():
            js = sorted(dest.glob("*.json"))
            if js:
                shutil.copy(js[0], dest / "report.json")
        if not (dest / "report.json").exists():
            print(log[-3000:])
            print("report.json не найден — замер не записан")
            return 1
        run_dir = Path(a.run_dir) if a.run_dir else find_run_dir(dest / "report.json", log)
    for extra in ("report.html",):  # HTML большой и не нужен для оценки
        (dest / extra).unlink(missing_ok=True)
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    report = sc.as_report(json.loads((dest / "report.json").read_text(encoding="utf-8")), gold)
    md = dest / "report.md"
    res = sc.score_report(report, gold, report_md=str(md) if md.exists() else None,
                          run_dir=str(run_dir) if run_dir else None, arbiter=a.arbiter)
    res["run_dir"] = str(run_dir) if run_dir else None
    (dest / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    text = sc.render_md(res, a.label)
    (dest / "score.md").write_text(text, encoding="utf-8")
    print(text)
    if not a.no_history:
        with HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(sc.history_row(res, a.label), ensure_ascii=False) + "\n")
        update_results()
    print(f"сохранено: {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
