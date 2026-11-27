"""W4-07: финальные цифры релиза по коду одного коммита (тег `v2.0.0` или голова заморозки `bcc/v2`).

    python -m evaluation.v2.final --commit c6aa9b5            # таблицы в stdout
    python -m evaluation.v2.final --commit c6aa9b5 --write    # + блок «Финальные цифры» в RESULTS.md
    python -m evaluation.v2.final --commit v2.0.0 --write     # по тегу: код тега сверяется с кодом замеров

Ничего не запускает: собирает готовые замеры, в метке которых есть этот коммит (метки `round … --label-commit`):
официальный документ (`history.jsonl` и `score.json` — каждый прогон и разброс по моделям), корпус
(`corpus_results`), новые ТЗ №18 и чистые наборы (`newtz_results`). Если задан тег, проверяет, что `src/` и
`pyproject.toml` тега совпадают с кодом коммита замеров — иначе цифры не про этот релиз.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .common import ROOT, put_results_block

V2 = ROOT / "evaluation" / "v2"
RESULTS = V2 / "RESULTS.md"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def resolve(ref: str) -> tuple[str, str]:
    """(короткий SHA для поиска в метках, пояснение). Для тега — SHA его коммита."""
    r = _git("rev-parse", "--short=7", f"{ref}^{{commit}}")
    sha = r.stdout.strip() if r.returncode == 0 else ref
    note = "" if sha.startswith(ref[:7]) else f"`{ref}` → `{sha}`"
    return sha, note


def same_code(a: str, b: str) -> bool | None:
    """Код (src/ и pyproject.toml) двух коммитов совпадает? None — git их не знает."""
    r = _git("diff", "--quiet", a, b, "--", "src", "pyproject.toml")
    return {0: True, 1: False}.get(r.returncode)


def _span(vals: list, digits: int = 1) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "—"
    lo, hi = min(vals), max(vals)
    fmt = (lambda v: f"{v:.{digits}f}") if any(isinstance(v, float) for v in vals) else str
    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"


def official(sha: str) -> list[dict]:
    rows = []
    hist = V2 / "history.jsonl"
    for line in hist.read_text(encoding="utf-8").splitlines() if hist.exists() else []:
        r = json.loads(line) if line.strip() else {}
        if sha in str(r.get("label", "")):
            sp = ROOT / str(r.get("dir", "")) / "score.json"
            sc = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
            r["clarity"] = sc.get("clarity") or {}
            rows.append(r)
    return rows


def _summaries(folder: Path, sha: str) -> list[dict]:
    out = []
    for p in sorted(folder.glob("*/summary.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if sha in str(d.get("label", "")):
            out.append({**d, "_dir": p.parent.name})
    return out


def render(ref: str, sha: str, note: str) -> str:
    L = [f"Код: `{sha}`" + (f" ({note})" if note else "") + ". Все числа — из готовых замеров с этим коммитом в "
         "метке; пересчитать — `python -m evaluation.v2.final --commit " + ref + " --write`.", ""]
    off = official(sha)
    L += ["**Официальный документ** (каждая модель — все прогоны на этом коде, разброс min–max):", "",
          "| Модель | Прогонов | complete | К найдено | К критичными | С из 20 | Замечаний | Дубли | Ложных critical "
          "| Время, мин | Вызовов | Рубрика | $ за прогон |",
          "| :--- | ---: | ---: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for m in sorted({r.get("model") for r in off}, key=lambda x: ("sonnet", "haiku", "opus").index(x)
                    if x in ("sonnet", "haiku", "opus") else 9):
        rs = [r for r in off if r.get("model") == m]
        cl = [round(100 * r["clarity"]["passed"] / r["clarity"]["n"]) for r in rs if (r["clarity"] or {}).get("n")]
        L.append(f"| {m} | {len(rs)} | {sum(1 for r in rs if r.get('status') == 'complete')} | "
                 f"{_span([r.get('K') for r in rs])}/5 | {_span([r.get('K_as_critical') for r in rs])} | "
                 f"{_span([r.get('C') for r in rs])} | {_span([r.get('findings') for r in rs])} | "
                 f"{_span([r.get('duplicates') for r in rs])} | {_span([r.get('critical_false') for r in rs])} | "
                 f"{_span([round(r['duration_s'] / 60, 1) for r in rs if r.get('duration_s')])} | "
                 f"{_span([r.get('calls') for r in rs])} | {_span(cl)} % | "
                 f"{_span([round(r['cost_usd'], 2) for r in rs if r.get('cost_usd') is not None], 2)} |")
    if not off:
        L.append("| — | 0 | | | | | | | | | | | |")
    parts = []
    for m in sorted({r.get("model") for r in off}):
        rs = [r for r in off if r.get("model") == m]
        missed = sorted({g for r in rs for g in r.get("C_missed") or []},
                        key=lambda g: int(g[1:]) if g[1:].isdigit() else 99)
        if missed:
            parts.append(f"{m} — " + ", ".join(
                f"{g} ({sum(1 for r in rs if g in (r.get('C_missed') or []))} из {len(rs)})" for g in missed))
    if parts:
        L += ["", "Промахи С (в скольких прогонах модели): " + "; ".join(parts) + "."]
    corp = _summaries(V2 / "corpus_results", sha)
    if corp:
        L += ["", "**Корпус `evaluation/dev`** (строгий счётчик `evaluation/harness`):", "",
              "| Прогон | Модель | Кейсов (не измерено) | TP | FP | FN | Precision | Recall | F1 | critical на чистых | "
              "«нельзя» на чистых |", "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for d in corp:
            h, c = d.get("harness") or {}, d.get("clean") or {}
            f = (lambda v: "—" if v is None else f"{v:.2f}")
            L.append(f"| {d.get('label')} | {d.get('model')} | {d.get('cases')} ({d.get('failed') or 0}) | "
                     f"{h.get('tp')} | {h.get('fp')} | {h.get('fn')} | {f(h.get('precision'))} | {f(h.get('recall'))} | "
                     f"{f(h.get('f1'))} | {c.get('critical')} | {c.get('verdict_no')} из {c.get('measured')} |")
    nz = _summaries(V2 / "newtz_results", sha)
    if nz:
        L += ["", "**Новые ТЗ №18 и чистые наборы:**", "",
              "| Прогон | Модель | Документов (сбоев) | Recall по эталону | Precision | Чистых: critical / major / «нельзя» "
              "| Вставка для модели замечена |",
              "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
        for d in nz:
            h, c, inj = d.get("harness") or {}, d.get("clean") or {}, d.get("injection") or {}
            tp, fp = h.get("tp") or 0, h.get("fp") or 0
            rec = f"{100 * h['recall']:.0f} % ({tp}/{h.get('support')})" if h.get("support") else "—"
            prec = f"{100 * tp / (tp + fp):.0f} %" if h.get("support") and tp + fp else "—"
            cl = (f"{c.get('critical')} / {c.get('major')} / {c.get('verdict_no')} из {c.get('n')}"
                  if c.get("n") else "—")
            ij = f"{inj.get('flagged')} из {inj.get('n')}" if inj.get("n") else "—"
            L.append(f"| {d.get('label')} | {d.get('model')} | {d.get('runs', d.get('cases'))} ({d.get('failed') or 0}) | "
                     f"{rec} | {prec} | {cl} | {ij} |")
    if not (off or corp or nz):
        L += ["", f"Замеров с `{sha}` в метке нет — `python -m evaluation.v2.round … --label-commit {sha}`."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.final", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", required=True, help="коммит замеров или тег релиза (v2.0.0)")
    ap.add_argument("--code", help="коммит, на котором мерили, если --commit — тег (по умолчанию — сам тег)")
    ap.add_argument("--write", action="store_true", help="записать блок «Финальные цифры» в RESULTS.md")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sha, note = resolve(a.code or a.commit)
    if a.code:
        tag_sha, _ = resolve(a.commit)
        same = same_code(tag_sha, sha)
        note = (f"тег `{a.commit}` = `{tag_sha}`, код " + {True: "совпадает", False: "**не совпадает**",
                                                         None: "не сверен"}[same] + f" с `{sha}`")
    text = render(a.commit, sha, note)
    print(text)
    if a.write:
        put_results_block(RESULTS, "final", text, "Финальные цифры релиза (W4-07)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
