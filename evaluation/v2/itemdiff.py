"""Что изменилось по пунктам эталона между двумя кодами — по всем прогонам официального документа на каждом.

    python -m evaluation.v2.itemdiff 3e7133c d013c12 [--models sonnet haiku] [--focus С12 С15 С6 С17] [--write]

Зачем: голова чинит конкретные пункты (судья — С12, С15; линзы — С6, С17), а итог «С 18/20» этого не показывает:
один пункт нашёлся, другой потерялся — число то же. Здесь по каждому пункту К1–К5 и С1–С20 — в скольких прогонах
он найден в итоге на A и на B и в скольких его видели кандидаты до судьи (`stage_recall` в `score.json`), а у
промаха на B — почему (линза нашла, судья не взял; близкое замечание; никто не нашёл).

Прогоны — из `history.jsonl` (v2, complete, с вызовами модели: повтор ответов из кэша не новая выборка); к коду
прогон относится по git — деревья `src/` и `pyproject.toml` его коммита равны деревьям A (или B), как в воротах.
Шум не прячется: «2/3 → 1/1» — «в шуме», изменением считается «ни разу → найден» и «во всех → потерян».
В таблице — пункты, у которых изменилась доля в итоге или у кандидатов, и пункты из `--focus` (даже без изменений).
`--write` — блок в `RESULTS.md` после финальных цифр.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from . import gate
from .common import ROOT, put_results_block

V2 = Path(__file__).resolve().parent
RESULTS = V2 / "RESULTS.md"
KEYS = [f"К{i}" for i in range(1, 6)] + [f"С{i}" for i in range(1, 21)]
KINDS = ("opus", "sonnet", "haiku", "gemini")


def _key(gid: str) -> tuple[int, int]:
    return (0 if gid.startswith("К") else 1, int(gid[1:]))


def history_rows(path: Path | None = None) -> list[dict]:
    """Замеры официального документа с вызовами модели (без повторов ответов из кэша)."""
    rows = gate._read_jsonl(path or gate.HISTORY)
    return [r for r in rows if r.get("version") == "v2" and r.get("status") == "complete"
            and str(r.get("calls")) not in ("0", "None")]


def runs_on(rows: list[dict], ref: str, kind: str, tree: Callable[[str | None], str | None] | None = None) -> list[dict]:
    """Прогоны модели `kind` на коде коммита `ref` (по деревьям git), по времени."""
    tree = tree or gate.code_tree
    want = tree(ref)
    if not want:
        return []
    return sorted((r for r in rows if gate.model_kind(r.get("provider"), r.get("model")) == kind
                   and tree(r.get("commit")) == want), key=lambda r: r.get("at", ""))


def load_score(row: dict) -> dict | None:
    d = row.get("dir")
    if not d:
        return None
    p = ROOT / d / "score.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def found(row: dict, score: dict | None) -> set[str] | None:
    """Пункты К и С, найденные в итоге (по `K_missed`/`C_missed` истории, иначе по промахам `score.json`)."""
    if row.get("K_missed") is not None and row.get("C_missed") is not None:
        return set(KEYS) - set(row["K_missed"]) - set(row["C_missed"])
    if score and score.get("misses") is not None:
        return set(KEYS) - {m.get("gold") for m in score["misses"]}
    return None


def seen(score: dict | None) -> dict[str, set[str]] | None:
    """Пункт → этапы, чьи кандидаты его видели до судьи (линзы, сверка, правила — `stage_recall` в `score.json`)."""
    if not score or not isinstance(score.get("stage_recall"), dict):
        return None
    out: dict[str, set[str]] = {}
    for stage, st in score["stage_recall"].items():
        for gid in list(st.get("K") or []) + list(st.get("C") or []):
            out.setdefault(gid, set()).add(stage.removeprefix("lens:"))
    return out


def why(where: str) -> str:
    """Причина промаха из `score.json` → коротко, с владельцем."""
    if "судья" in where:
        return "линза нашла, судья не взял → №10"
    if "сверкой цитат" in where:
        return "отсеяно сверкой цитат → №03"
    if "близкое" in where:
        return "есть близкое, не та проблема или строки"
    if "ни одним" in where:
        return "никто не нашёл"
    return where[:60]


def _frac(k: int, n: int) -> str:
    return f"{k}/{n}"


def verdict(ka: int, na: int, kb: int, nb: int) -> str:
    """Изменение доли «найден» A → B словами; шум прогонов не выдаётся за изменение."""
    if ka == 0 and kb == nb:
        return f"**найден** (на A ни разу из {na})"
    if ka == na and kb == 0:
        return f"**потерян** (на A во всех {na})"
    if ka == 0 and kb:
        return "стал находиться иногда"
    if ka == na and kb < nb:
        return "стал теряться иногда"
    if ka * nb == kb * na:
        return "без изменений"
    return f"в шуме (на A {ka} из {na})"


def compare(rows: list[dict], a: str, b: str, kinds: list[str] | None = None, focus: list[str] | None = None,
            tree: Callable[[str | None], str | None] | None = None,
            score_of: Callable[[dict], dict | None] = load_score) -> dict:
    """{a, b, models: [{kind, n_a, n_b, totals, items: [...]}]} — только модели с прогонами на обоих кодах."""
    focus = [f for f in (focus or []) if f in KEYS]
    out = {"a": a, "b": b, "models": []}
    for kind in kinds or list(KINDS):
        ra, rb = runs_on(rows, a, kind, tree), runs_on(rows, b, kind, tree)
        if not ra or not rb:
            continue
        sa = [score_of(r) for r in ra]
        sb = [score_of(r) for r in rb]
        fa = [found(r, s) for r, s in zip(ra, sa)]
        fb = [found(r, s) for r, s in zip(rb, sb)]
        if any(x is None for x in fa + fb):
            keep_a = [i for i, x in enumerate(fa) if x is not None]
            keep_b = [i for i, x in enumerate(fb) if x is not None]
            ra, sa, fa = [ra[i] for i in keep_a], [sa[i] for i in keep_a], [fa[i] for i in keep_a]
            rb, sb, fb = [rb[i] for i in keep_b], [sb[i] for i in keep_b], [fb[i] for i in keep_b]
            if not ra or not rb:
                continue
        va, vb = [seen(s) for s in sa], [seen(s) for s in sb]
        va_ok, vb_ok = [v for v in va if v is not None], [v for v in vb if v is not None]
        items = []
        for gid in KEYS:
            ka, kb = sum(gid in x for x in fa), sum(gid in x for x in fb)
            ca = sum(gid in v for v in va_ok) if va_ok else None
            cb = sum(gid in v for v in vb_ok) if vb_ok else None
            changed = ka * len(fb) != kb * len(fa)
            # у кандидатов изменение — тоже «ни разу → видели» или «всегда → не всегда», а не любая другая доля
            cand_changed = (ca is not None and cb is not None and bool(va_ok) and bool(vb_ok)
                            and ((ca == 0 and cb > 0) or (ca == len(va_ok) and cb < len(vb_ok))))
            if not (changed or cand_changed or gid in focus):
                continue
            stages_b = Counter(st for v in vb_ok for st in v.get(gid, ()))
            reasons = Counter()
            for s, f in zip(sb, fb):
                if gid in f or not s:
                    continue
                m = next((m for m in s.get("misses") or [] if m.get("gold") == gid), None)
                if m:
                    reasons[why(m.get("where", ""))] += 1
            v = verdict(ka, len(fa), kb, len(fb))
            items.append({"id": gid, "found_a": ka, "found_b": kb, "seen_a": ca, "seen_b": cb,
                          "n_seen_a": len(va_ok), "n_seen_b": len(vb_ok), "stages_b": sorted(stages_b),
                          "verdict": v, "noise": v.startswith("в шуме") and not cand_changed and gid not in focus,
                          "miss_b": "; ".join(f"{w}{f' ({c})' if len(fb) > 1 else ''}" for w, c in reasons.most_common())})
        items.sort(key=lambda x: _key(x["id"]))

        def vals(rs: list[dict], key: str) -> list:
            return [r.get(key) for r in rs]

        out["models"].append({
            "kind": kind, "n_a": len(fa), "n_b": len(fb),
            "C_a": [sum(g.startswith("С") for g in x) for x in fa], "C_b": [sum(g.startswith("С") for g in x) for x in fb],
            "K_a": [sum(g.startswith("К") for g in x) for x in fa], "K_b": [sum(g.startswith("К") for g in x) for x in fb],
            "Kc_a": vals(ra, "K_as_critical"), "Kc_b": vals(rb, "K_as_critical"),
            "findings_a": vals(ra, "findings"), "findings_b": vals(rb, "findings"),
            "dups_a": vals(ra, "duplicates"), "dups_b": vals(rb, "duplicates"),
            "labels_b": [f"{r.get('label')} ({str(r.get('at', ''))[11:16]})" for r in rb],
            "items": items,
        })
    return out


def _seq(xs: list) -> str:
    xs = [x for x in xs if x is not None]
    if not xs:
        return "—"
    return ", ".join(str(x) for x in xs)


def _mean(xs: list) -> str:
    xs = [float(x) for x in xs if x is not None]
    return f"{sum(xs) / len(xs):.1f}".replace(".", ",") if xs else "—"


def render(d: dict, titles: dict[str, str] | None = None) -> str:
    a, b = f"`{d['a']}`", f"`{d['b']}`"
    if not d["models"]:
        return (f"Нет прогонов официального документа (без кэша) на обоих кодах {a} и {b} — сравнивать нечего; "
                f"замер: `python -m evaluation.v2.round --official sonnet haiku --no-corpus --no-newtz --no-cache`.\n")
    lines = [f"**{a} → {b}, официальный документ по пунктам эталона** — прогоны без повторов из кэша, код сверен "
             "по git (деревья `src/` и `pyproject.toml`). «Найден» — в итоговом отчёте; «видели кандидаты» — хоть "
             "один этап до судьи (линзы, сверка, правила). Изменение — «ни разу → найден» или «во всех → потерян»; "
             "остальное — шум прогонов.", ""]
    for m in d["models"]:
        lines.append(f"* **{m['kind']}** (прогонов {m['n_a']} → {m['n_b']}): С1–С20 {_seq(m['C_a'])} → {_seq(m['C_b'])} "
                     f"(среднее {_mean(m['C_a'])} → {_mean(m['C_b'])}); К1–К5 {_seq(m['K_a'])} → {_seq(m['K_b'])}, "
                     f"критичными {_seq(m['Kc_a'])} → {_seq(m['Kc_b'])}; замечаний {_seq(m['findings_a'])} → "
                     f"{_seq(m['findings_b'])}; дублей {_seq(m['dups_a'])} → {_seq(m['dups_b'])}.")
    lines += ["", "| Пункт | Модель | Найден, A → B | Видели кандидаты, A → B | Что изменилось | Промах на B — почему |",
              "| :--- | :--- | :---: | :---: | :--- | :--- |"]
    rows = [(it, m) for m in d["models"] for it in m["items"] if not it.get("noise")]
    rows.sort(key=lambda x: (_key(x[0]["id"]), KINDS.index(x[1]["kind"])))
    for it, m in rows:
        t = (titles or {}).get(it["id"], "")
        name = f"{it['id']} {t[:60]}".strip()
        cand = (f"{_frac(it['seen_a'], it['n_seen_a'])} → {_frac(it['seen_b'], it['n_seen_b'])}"
                if it["seen_a"] is not None and it["seen_b"] is not None else "—")
        if it.get("stages_b"):
            cand += f" ({', '.join(it['stages_b'])})"
        lines.append(f"| {name} | {m['kind']} | {_frac(it['found_a'], m['n_a'])} → {_frac(it['found_b'], m['n_b'])} "
                     f"| {cand} | {it['verdict']} | {it['miss_b'] or '—'} |")
    if not rows:
        lines.append("| — | — | — | — | ни один пункт не изменился | — |")
    for m in d["models"]:
        noise = [it for it in m["items"] if it.get("noise")]
        if noise:
            lines.append("")
            lines.append(f"В шуме у {m['kind']} (на A пункт то находился, то нет): " + ", ".join(
                f"{it['id']} {_frac(it['found_a'], m['n_a'])} → {_frac(it['found_b'], m['n_b'])}" for it in noise) + ".")
    return "\n".join(lines) + "\n"


def _titles() -> dict[str, str]:
    try:
        from .score import DEFAULT_GOLD, load_gold
        return {it["id"]: it["title"] for it in load_gold(DEFAULT_GOLD)["items"]}
    except Exception:  # noqa: BLE001 — заголовки только для читателя
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.itemdiff", description=__doc__.split("\n")[0])
    ap.add_argument("a", help="коммит (или тег) кода «до»")
    ap.add_argument("b", help="коммит (или тег) кода «после»")
    ap.add_argument("--models", nargs="*", default=None, choices=list(KINDS))
    ap.add_argument("--focus", nargs="*", default=[], help="пункты, которые показать всегда (цели правки)")
    ap.add_argument("--write", action="store_true", help="блок в RESULTS.md (после финальных цифр)")
    a = ap.parse_args(argv)
    for ref in (a.a, a.b):
        if not gate.code_tree(ref):
            print(f"git не знает `{ref}` (нет `src/` или `pyproject.toml` у коммита)", file=sys.stderr)
            return 2
    d = compare(history_rows(), a.a, a.b, a.models, a.focus)
    md = render(d, _titles())
    sys.stdout.write(md)
    if a.write:
        put_results_block(RESULTS, "itemdiff", md, "Головы по пунктам эталона (официальный документ)", after="final")
        print(f"\nзаписано: {RESULTS.relative_to(ROOT)} (блок itemdiff)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
