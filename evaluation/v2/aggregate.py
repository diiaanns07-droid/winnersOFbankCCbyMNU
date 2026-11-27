"""Сводки по нескольким оценкам официального документа: стабильность и сравнение моделей.

    # стабильность: какие К и С находятся в 3/3, 2/3, 1/3 прогонов; разброс числа замечаний и времени
    python -m evaluation.v2.aggregate stability m/opus_1/score.json m/opus_2/score.json m/opus_3/score.json \\
        [--json evaluation/v2/stability/opus.json] [--label "Opus, 1a2b3c4"]
    # сравнение моделей: метка=score.json
    python -m evaluation.v2.aggregate models opus=m/opus_1/score.json sonnet=m/sonnet/score.json haiku=m/haiku/score.json
    # то же по последним замерам каждой модели из history.jsonl; --write — в RESULTS.md
    python -m evaluation.v2.aggregate models --auto [--write]

Вход — score.json от `python -m evaluation.v2.score` / `measure`. Вывод — Markdown (для RESULTS.md) в stdout;
`--json` — то же для `python -m evaluation.v2.gate` (ворота «К1–К5 в 3 прогонах из 3»).
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from .score import DEFAULT_GOLD, astana_now, load_gold

STABILITY_DIR = Path(__file__).resolve().parent / "stability"


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def stability_data(paths: list[str], label: str = "") -> dict:
    gold = load_gold(DEFAULT_GOLD)
    runs = [_load(p) for p in paths]
    n = len(runs)
    found = [{a["gold"] for a in r["assignment"]} for r in runs]
    crit = [{a["gold"] for a in r["assignment"] if a["severity"] == "critical"} for r in runs]
    key = [it for it in gold["items"] if it["level"] in ("critical", "major")]
    per_item = {it["id"]: {"found": sum(it["id"] in f for f in found),
                           "as_critical": sum(it["id"] in c for c in crit) if it["level"] == "critical" else None,
                           "title": it["title"], "owners": it.get("owners") or []} for it in key}
    models = sorted({str(r["report"].get("model")) for r in runs})
    durs = [r["report"].get("duration_s") for r in runs if r["report"].get("duration_s") is not None]
    nf = [r["counts"]["findings"] for r in runs]
    return {
        "label": label or ", ".join(models), "at": astana_now(), "n": n, "models": models,
        "commits": sorted({str(r["report"].get("commit")) for r in runs}),
        "sources": [str(p) for p in paths],
        "runs": [{"source": str(p), "status": r["report"].get("status"), "commit": r["report"].get("commit"),
                  "K": sorted(g for g in f if g.startswith("К")), "K_as_critical": sorted(g for g in c if g.startswith("К")),
                  "C": sorted((g for g in f if g.startswith("С")), key=lambda x: int(x[1:])),
                  "findings": r["counts"]["findings"], "duration_s": r["report"].get("duration_s"),
                  "calls": (r["report"].get("calls") or {}).get("total"), "cost_usd": r["report"].get("cost_usd")}
                 for p, r, f, c in zip(paths, runs, found, crit)],
        "per_item": per_item,
        "K_all_runs": [i for i, v in per_item.items() if i.startswith("К") and v["found"] == n],
        "C_all_runs": [i for i, v in per_item.items() if i.startswith("С") and v["found"] == n],
        "findings": {"min": min(nf, default=None), "max": max(nf, default=None),
                     "mean": round(statistics.mean(nf), 1) if nf else None},
        "duration_s": {"min": min(durs, default=None), "max": max(durs, default=None),
                       "mean": round(statistics.mean(durs), 1) if durs else None},
    }


def stability_md(d: dict) -> str:
    n = d["n"]
    L = [f"**{d['label']}** — прогонов {n}, коммиты {', '.join(d['commits'])}.", "",
         "| Пункт | " + " | ".join(f"прогон {i + 1}" for i in range(n)) + " | Итого |",
         "| :--- | " + " | ".join(":---:" for _ in range(n)) + " | ---: |"]
    for gid, v in d["per_item"].items():
        cells = []
        for r in d["runs"]:
            if gid in r["K_as_critical"]:
                cells.append("да, критичный")
            else:
                cells.append("да" if gid in r["K"] or gid in r["C"] else "—")
        L.append(f"| {gid} {v['title'][:60]} | " + " | ".join(cells) + f" | {v['found']}/{n} |")
    L += ["", "| Найдено в | Пункты |", "| :--- | :--- |"]
    for k in range(n, -1, -1):
        ids = [i for i, v in d["per_item"].items() if v["found"] == k]
        L.append(f"| {k}/{n} | {', '.join(ids) or '—'} |")
    ks = [len(r["K"]) for r in d["runs"]]
    kc = [len(r["K_as_critical"]) for r in d["runs"]]
    cs = [len(r["C"]) for r in d["runs"]]
    f, t = d["findings"], d["duration_s"]
    L += ["", f"К1–К5 по прогонам: {', '.join(map(str, ks))} (критичными {', '.join(map(str, kc))}); "
              f"во всех {n}: {', '.join(d['K_all_runs']) or '—'}.",
          f"С1–С20 по прогонам: {', '.join(map(str, cs))}; среднее {sum(cs) / max(1, n):.1f}; во всех {n}: "
          f"{len(d['C_all_runs'])}.",
          f"Замечаний: {', '.join(str(r['findings']) for r in d['runs'])} (от {f['min']} до {f['max']}).",
          "Время, мин: " + ", ".join("—" if r["duration_s"] is None else f"{r['duration_s'] / 60:.1f}" for r in d["runs"])
          + (f" (от {t['min'] / 60:.1f} до {t['max'] / 60:.1f})" if t["min"] is not None else "") + "; вызовов: "
          + ", ".join(str(r["calls"]) for r in d["runs"]) + "."]
    return "\n".join(L) + "\n"


def stability(paths: list[str]) -> str:
    return stability_md(stability_data(paths))


def models(pairs: list[str]) -> str:
    L = ["| Модель | Статус | К | К крит. | С | Ключевые 25 | Замечаний | Дубли | Вне эталона верно/ложно | "
         "Полезных | Серьёзность верна | Крит. ложных | Цитаты не найдены | Мин | Вызовов | $ |",
         "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for pair in pairs:
        label, path = pair.split("=", 1)
        r = _load(path)
        rc, p, rep = r["recall"], r["precision"], r["report"]
        calls = rep.get("calls") or {}
        dur = rep.get("duration_s")
        L.append(f"| {label} | {rep.get('status')} | {rc['critical']['n']}/5 | {len(rc['critical']['as_critical'])} | "
                 f"{rc['major']['n']}/20 | {rc['key_25']['n']}/25 | {r['counts']['findings']} | {p['duplicates']} | "
                 f"{p['outside_real']}/{p['outside_false']} | {_pct(p['precision_useful'])} | "
                 f"{_pct(r['severity']['accuracy_ok'])} | {len(r['severity']['critical_false'])} | "
                 f"{r['quotes']['missing']}/{r['quotes']['total']} | {'—' if dur is None else f'{dur / 60:.1f}'} | "
                 f"{calls.get('total', '—')} | {'—' if rep.get('cost_usd') is None else format(rep['cost_usd'], '.2f')} |")
    return "\n".join(L) + "\n"


def models_auto() -> str:
    """Последний замер официального документа каждой модели (история measure) → таблица сравнения."""
    from .common import other_format
    from .gate import HISTORY, _read_jsonl, _score_for, model_kind

    latest: dict[str, tuple[dict, str]] = {}
    for r in _read_jsonl(HISTORY):
        if r.get("version") != "v2" or other_format(r.get("label")):
            continue
        k = model_kind(r.get("provider"), r.get("model"))
        sj = _score_for(r)
        if sj is not None:
            from .measure import slugify

            d = Path(r["dir"]) if r.get("dir") else Path("evaluation/v2/measurements") / slugify(r["label"])
            latest[k] = (r, str(d / "score.json"))
    order = [k for k in ("opus", "sonnet", "haiku", "gemini", "other") if k in latest]
    pairs = [f"{k} — {latest[k][0]['label']}={latest[k][1]}" for k in order]
    return models(pairs) if pairs else "Замеров нет.\n"


def write_models_section(results: Path | None = None) -> None:
    import re

    results = results or Path(__file__).resolve().parent / "RESULTS.md"
    text = results.read_text(encoding="utf-8")
    st, en = "<!-- models:start -->", "<!-- models:end -->"
    if st in text and en in text:
        table = models_auto()
        text = re.sub(re.escape(st) + r".*?" + re.escape(en), lambda m: f"{st}\n{table}{en}", text, flags=re.S)
        results.write_text(text, encoding="utf-8")


def write_stability_section(results: Path | None = None) -> None:
    """Все сводки `stability/*.json` (новые сверху) → RESULTS.md между метками stability."""
    import re

    results = results or Path(__file__).resolve().parent / "RESULTS.md"
    text = results.read_text(encoding="utf-8")
    st, en = "<!-- stability:start -->", "<!-- stability:end -->"
    if st not in text or en not in text:
        return
    ds = sorted((json.loads(p.read_text(encoding="utf-8")) for p in STABILITY_DIR.glob("*.json")),
                key=lambda d: d.get("at", ""), reverse=True)
    L = ["| Прогоны | n | К1–К5 во всех | К критичными по прогонам | С по прогонам | С во всех | Замечаний | Мин | $ за прогон |",
         "| :--- | ---: | :--- | :--- | :--- | ---: | :--- | :--- | ---: |"]
    for d in ds:
        runs = d["runs"]
        cost = [r["cost_usd"] for r in runs if r.get("cost_usd") is not None]
        L.append(f"| {d['label']} ({d['at'][11:16]}) | {d['n']} | {len(d['K_all_runs'])}/5 | "
                 f"{', '.join(str(len(r['K_as_critical'])) for r in runs)} | {', '.join(str(len(r['C'])) for r in runs)} | "
                 f"{len(d['C_all_runs'])}/20 | {d['findings']['min']}–{d['findings']['max']} | "
                 f"{d['duration_s']['min'] / 60:.1f}–{d['duration_s']['max'] / 60:.1f} | "
                 f"{'—' if not cost else f'{sum(cost) / len(cost):.2f}'} |")
    body = "\n".join(L) + "\n\n" + "\n".join(
        f"<details><summary>{d['label']}: по пунктам</summary>\n\n{d.get('markdown', '')}\n</details>\n" for d in ds)
    text = re.sub(re.escape(st) + r".*?" + re.escape(en), lambda m: f"{st}\n{body}{en}", text, flags=re.S)
    results.write_text(text, encoding="utf-8")


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f} %"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if not args or args[0] not in ("stability", "models") or any(x in ("-h", "--help") for x in args):
        print(__doc__)
        return 0 if args and any(x in ("-h", "--help") for x in args) else 2
    if args[0] == "models":
        if args[1:] in (["--auto"], ["--auto", "--write"], ["--write", "--auto"]):
            if "--write" in args:
                write_models_section()
            print(models_auto())
        else:
            print(models(args[1:]))
        return 0
    js, label, paths = None, "", []
    it = iter(args[1:])
    for x in it:
        if x == "--json":
            js = next(it)
        elif x == "--label":
            label = next(it)
        else:
            paths.append(x)
    d = stability_data(paths, label)
    text = stability_md(d)
    d["markdown"] = text
    if js:
        Path(js).parent.mkdir(parents=True, exist_ok=True)
        Path(js).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        write_stability_section()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
