"""W4-07: финальные цифры релиза по коду одного коммита (тег `v2.0.0` или голова заморозки `bcc/v2`).

    python -m evaluation.v2.final --commit c6aa9b5            # таблицы в stdout
    python -m evaluation.v2.final --commit c6aa9b5 --write    # + блок «Финальные цифры» в RESULTS.md
    python -m evaluation.v2.final --commit v2.0.0 --write     # по тегу: код тега сверяется с кодом замеров
    python -m evaluation.v2.final --commit v2.0.0 --code auto --sets-from 28fe64f --write   # код замеров — по git

Ничего не запускает: собирает готовые замеры, в метке которых есть этот коммит (метки `round … --label-commit`):
официальный документ (`history.jsonl` и `score.json` — каждый прогон и разброс по моделям), корпус
(`corpus_results`), новые ТЗ №18 и чистые наборы (`newtz_results`). Если задан тег, проверяет, что `src/` и
`pyproject.toml` тега совпадают с кодом коммита замеров — иначе цифры не про этот релиз.
"""
from __future__ import annotations

import argparse
import json
import re
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


def code_diff(a: str, b: str, limit: int = 8) -> str:
    """Чем код двух коммитов отличается: файлы `src/` и `pyproject.toml` с числом строк (+/−) — чтобы читатель
    видел, задевает ли разница основной прогон (линзы, судья) или, например, только режим `--answers`."""
    r = _git("diff", "--numstat", a, b, "--", "src", "pyproject.toml")
    rows = [x.split("\t") for x in r.stdout.splitlines() if x.count("\t") >= 2] if r.returncode == 0 else []
    if not rows:
        return ""
    short = [f"`{path.removeprefix('src/bcc_review/v2/')}` (+{add}/−{rem})" for add, rem, path in rows[:limit]]
    return ", ".join(short) + (f" и ещё {len(rows) - limit}" if len(rows) > limit else "")


def code_note(sha: str, groups: list[list[dict]]) -> str:
    """Метка говорит «на `sha`» — сверить, что у каждого прогона (`commit` в истории и сводках) тот же `src/`."""
    commits = sorted({c for rows in groups for r in rows
                      for c in (r.get("commit") if isinstance(r.get("commit"), list) else [r.get("commit")]) if c})
    if not commits:
        return ""
    verdict = {c: same_code(c, sha) for c in commits}
    bad = [c for c, v in verdict.items() if v is False]
    unknown = [c for c, v in verdict.items() if v is None]
    if bad:
        return (f"⚠ **Код прогонов не совпадает с `{sha}`:** " + ", ".join(f"`{c}`" for c in bad)
                + " — метка говорит одно, а `src/` у прогона другой; эти цифры не про этот код.")
    return (f"Код прогонов сверен по git (коммитов прогонов: {len(commits)}, сверено {len(commits) - len(unknown)}) — "
            f"`src/` и `pyproject.toml` как у `{sha}`" + (f"; git не знает: {', '.join(unknown)}" if unknown else "") + ".")


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


def _set_key(d: dict) -> tuple[str, str]:
    """Вид набора сводки: корпус — модель или правила без модели; `newtz` — новые ТЗ с эталоном, чистые №20 или чистые
    open2. По нему у кода релиза и кода `--sets-from` выбирается, какой набор откуда (свой код — в приоритете)."""
    if "per_case" in d:
        return ("corpus", "rules" if d.get("provider") == "offline" else "model")
    if (d.get("harness") or {}).get("support"):
        return ("newtz", "defects")
    docs = [str(r.get("doc") or "").replace("\\", "/") for r in d.get("rows") or []]
    return ("newtz", "clean20" if docs and all("v2/clean/" in x for x in docs) else "open2")


_SHA_RE = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,8}\b")


def measured_code(ref: str) -> str | None:
    """`--code auto`: коммит из меток замеров официального документа с тем же кодом (`src/` и `pyproject.toml` по git),
    что у `ref` (тег релиза), — с самым поздним прогоном. None — на этом коде официальный документ не мерили."""
    tag_sha, _ = resolve(ref)
    hist = V2 / "history.jsonl"
    best: tuple[str, str] | None = None
    seen: dict[str, bool | None] = {}
    for line in hist.read_text(encoding="utf-8").splitlines() if hist.exists() else []:
        r = json.loads(line) if line.strip() else {}
        if r.get("version") != "v2" or str(r.get("calls")) in ("0", "None"):
            continue
        for c in _SHA_RE.findall(str(r.get("label") or "")):
            if c not in seen:
                seen[c] = same_code(c, tag_sha)
            if seen[c] and (best is None or str(r.get("at", "")) >= best[1]):
                best = (c, str(r.get("at", "")))
    return best[0] if best else None


def _rows(n: int) -> str:
    """«1 строка», «3 строки», «53 строки», «11 строк»."""
    form = "строк" if n % 100 in range(11, 15) else {1: "строка", 2: "строки", 3: "строки", 4: "строки"}.get(n % 10, "строк")
    return f"{n} {form}"


def _calls(d: dict) -> str:
    """Вызовы модели и цена набора; 0 вызовов при прогнанных документах — ответы взяты из кэша (повтор, не выборка)."""
    t = d.get("time") or {}
    if "calls" not in t:
        return "—"
    if d.get("provider") == "offline":
        return "0 — без модели (правила)"
    if not t["calls"] and (d.get("runs") or d.get("cases")):
        return "0 — повтор из кэша"
    return f"{t['calls']}, ${t.get('cost_usd') or 0:.2f}"


def gate_lines(sha: str, checks: list[dict] | None = None) -> list[str]:
    """Ворота сейчас: сколько строк измерено на этом коде и что в них красное; строки на другом коде — по источникам."""
    if checks is None:
        try:
            from . import gate

            checks = gate.collect()
        except Exception as e:  # noqa: BLE001 — ворота дополняют цифры выше, а не заменяют их
            return ["", f"Ворота не собрались: {type(e).__name__}: {e}."]
    checks = [c for c in checks if not c.get("info")]
    on = [c for c in checks if sha in str(c.get("source") or "")]
    other = [c for c in checks if c.get("source") and sha not in str(c["source"])]

    def score(cs: list[dict]) -> str:
        return (f"✅ {sum(1 for c in cs if c['ok'])}, ❌ {sum(1 for c in cs if c['ok'] is False)}, "
                f"⏳ {sum(1 for c in cs if c['ok'] is None)}")

    L = ["", f"**Ворота WAVE3 сейчас** ({_rows(len(checks))}, `python -m evaluation.v2.gate`): на этом коде "
         f"{len(on)} — {score(on)}; " + (f"на другом коде {len(other)} — {score(other)}; " if other else
                                          "на другом коде — ни одной; ")
         + f"без замера {len(checks) - len(on) - len(other)}."]
    red = [c for c in on if c["ok"] is False]
    if red:
        L += ["", "| Красное на этом коде | Факт (цель) | Кому |", "| :--- | :--- | :--- |"]
        for c in red:
            owners = str(c.get("owners") or "").replace("|", "/")
            L.append(f"| {c['name']} | {c['fact']} ({c['target']}) | "
                     f"{owners if len(owners) <= 160 else owners[:157] + '…'} |")
    if other:
        srcs: dict[str, list[dict]] = {}
        for c in other:
            srcs.setdefault(str(c["source"]), []).append(c)
        L += ["", "Не на этом коде (последний замер другого коммита): " + "; ".join(
            f"{s} — {len(cs)} ({score(cs)})" for s, cs in srcs.items()) + "."]
    return L


_ORDER = ("sonnet", "haiku", "opus")


def official_table(off: list[dict]) -> list[str]:
    """Официальный документ по моделям: все прогоны, разброс min–max; промахи С — в скольких прогонах модели."""
    L = ["| Модель | Прогонов | complete | К найдено | К критичными | С из 20 | Замечаний | Дубли | Ложных critical "
         "| Время, мин | Вызовов | Рубрика | $ за прогон |",
         "| :--- | ---: | ---: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    models = sorted({r.get("model") for r in off}, key=lambda x: _ORDER.index(x) if x in _ORDER else 9)
    for m in models:
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
    for m in sorted(models):
        rs = [r for r in off if r.get("model") == m]
        missed = sorted({g for r in rs for g in r.get("C_missed") or []},
                        key=lambda g: int(g[1:]) if g[1:].isdigit() else 99)
        if missed:
            parts.append(f"{m} — " + ", ".join(
                f"{g} ({sum(1 for r in rs if g in (r.get('C_missed') or []))} из {len(rs)})" for g in missed))
    if parts:
        L += ["", "Промахи С (в скольких прогонах модели): " + "; ".join(parts) + "."]
    return L


def newer_lines(sha: str, newer: list[str], view_check: bool = True) -> list[str]:
    """Официальный документ на более новом коде (после замера релиза) — с тем, чем код отличается от `sha`."""
    L: list[str] = []
    for ref in newer:
        nsha, _ = resolve(ref)
        rows = official(nsha)
        if not rows:
            L += ["", f"На `{nsha}` замеров официального документа нет."]
            continue
        diff = code_diff(sha, nsha) if same_code(sha, nsha) is False else ""
        L += ["", f"**Проверка на более новом коде `{nsha}`** — официальный документ"
              + (f"; код отличается от `{sha}`: {diff}" if diff else "; `src/` тот же") + ":", ""]
        L += official_table(rows)
        corp_n, nz_n = _summaries(V2 / "corpus_results", nsha), _summaries(V2 / "newtz_results", nsha)
        L += sets_tables(corp_n, nz_n)
        note_code = code_note(nsha, [rows, corp_n, nz_n])
        L += ["", note_code] if note_code else []
        if view_check and diff:
            L += ["", view_line(sha, nsha)]
    return L


def view_line(sha: str, nsha: str) -> str:
    """Вход модели на новой голове: вид документов оценки и промпты этапов (`viewdiff`, без вызовов модели)."""
    from . import viewdiff

    try:
        res = viewdiff.check(sha, nsha)
    except Exception as exc:  # noqa: BLE001 — сверка вида не роняет итог релиза
        return f"Вход модели не сверен (`viewdiff {sha} {nsha}`): {str(exc).splitlines()[0][:200]}"
    line = (f"Вход модели (`python -m evaluation.v2.viewdiff {sha} {nsha}`): {viewdiff.summary_line(res)}"
            + (" — модель получает тот же вход, разница в цифрах — разброс выборки ответов."
               if viewdiff.same_input(res) else "."))
    if any(str(x).startswith("rules/") for x in res.get("stage_code_changed") or []):
        try:  # правила менялись — что они дают без модели на чистых и на официальном (детерминированно, ~15 с)
            rs = viewdiff.rules_check(res["a"], res["b"])
            line += " " + viewdiff.rules_line(rs) + (" " + viewdiff.official_rules_line(rs)).rstrip()
        except Exception as exc:  # noqa: BLE001 — сверка правил не роняет итог релиза
            line += f" Правила без модели не сверены: {str(exc).splitlines()[0][:160]}."
    return line


def sets_tables(corp: list[dict], nz: list[dict]) -> list[str]:
    """Корпус и новые ТЗ / чистые наборы — таблицами (для кода релиза и для проверки новых голов)."""
    L: list[str] = []
    if corp:
        L += ["", "**Корпус `evaluation/dev`** (строгий счётчик `evaluation/harness`):", "",
              "| Прогон | Модель | Кейсов (не измерено) | TP | FP | FN | Precision | Recall | F1 | critical на чистых | "
              "«нельзя» на чистых | Вызовов, $ |",
              "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
        for d in corp:
            h, c = d.get("harness") or {}, d.get("clean") or {}
            f = (lambda v: "—" if v is None else f"{v:.2f}")
            L.append(f"| {d.get('label')} | {d.get('model')} | {d.get('cases')} ({d.get('failed') or 0}) | "
                     f"{h.get('tp')} | {h.get('fp')} | {h.get('fn')} | {f(h.get('precision'))} | {f(h.get('recall'))} | "
                     f"{f(h.get('f1'))} | {c.get('critical')} | {c.get('verdict_no')} из {c.get('measured')} | "
                     f"{_calls(d)} |")
    if nz:
        L += ["", "**Новые ТЗ №18 и чистые наборы:**", "",
              "| Прогон | Модель | Документов (сбоев) | Recall по эталону | Precision | Чистых: critical / major / «нельзя» "
              "| Вставка для модели замечена | Вызовов, $ |",
              "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
        for d in nz:
            h, c, inj = d.get("harness") or {}, d.get("clean") or {}, d.get("injection") or {}
            tp, fp = h.get("tp") or 0, h.get("fp") or 0
            rec = f"{100 * h['recall']:.0f} % ({tp}/{h.get('support')})" if h.get("support") else "—"
            prec = f"{100 * tp / (tp + fp):.0f} %" if h.get("support") and tp + fp else "—"
            cl = (f"{c.get('critical')} / {c.get('major')} / {c.get('verdict_no')} из {c.get('n')}"
                  if c.get("n") else "—")
            ij = f"{inj.get('flagged')} из {inj.get('n')}" if inj.get("n") else "—"
            L.append(f"| {d.get('label')} | {d.get('model')} | {d.get('runs', d.get('cases'))} ({d.get('failed') or 0}) | "
                     f"{rec} | {prec} | {cl} | {ij} | {_calls(d)} |")
    return L


def render(ref: str, sha: str, note: str, checks: list[dict] | None = None, newer: list[str] | None = None,
           extra: list[str] | None = None, view_check: bool = True, sets_sha: str | None = None) -> str:
    """Блок «Финальные цифры». ``sets_sha`` — корпус, новые ТЗ и чистые наборы с этого кода (на коде релиза их не
    мерили: лимит подписки, нет времени), с пометкой и строкой «вход модели»; официальный — всегда на ``sha``."""
    sets_sha = sets_sha or sha
    L = [f"Код: `{sha}`" + (f" ({note})" if note else "") + ". Все числа — из готовых замеров с этим коммитом в "
         "метке; пересчитать — `python -m evaluation.v2.final --commit " + ref
         + "".join(f" --newer {n}" for n in newer or [])
         + (f" --sets-from {sets_sha}" if sets_sha != sha else "") + " --write`.", ""]
    for x in extra or []:
        L += [x, ""]
    off = official(sha)
    L += ["**Официальный документ** (каждая модель — все прогоны на этом коде, разброс min–max):", ""]
    L += official_table(off)
    corp = _summaries(V2 / "corpus_results", sets_sha)
    nz = _summaries(V2 / "newtz_results", sets_sha)
    own_c: list[dict] = []
    own_n: list[dict] = []
    if sets_sha != sha:
        # набор, который мерили и на коде релиза, — с кода релиза; остальные — с `sets_sha`
        own_c, own_n = _summaries(V2 / "corpus_results", sha), _summaries(V2 / "newtz_results", sha)
        have = {_set_key(d) for d in own_c + own_n}
        corp = own_c + [d for d in corp if _set_key(d) not in have]
        nz = own_n + [d for d in nz if _set_key(d) not in have]
    if sets_sha != sha and (corp or nz):
        own = ", ".join(f"«{x}»" for x in sorted({str(d.get("label")) for d in own_c + own_n}))
        L += ["", f"**Наборы ниже — на коде `{sets_sha}`**, не на `{sha}`"
              + (f", кроме мерившихся и на коде релиза ({own})" if own else "")
              + ": на коде релиза " + ("остальные наборы" if own else "корпус, новые ТЗ и чистые") + " не мерились. "
              + (view_line(sets_sha, sha) if view_check else f"Код отличается: {code_diff(sets_sha, sha)}.")]
    L += sets_tables(corp, nz)
    if not (off or corp or nz):
        L += ["", f"Замеров с `{sha}` в метке нет — `python -m evaluation.v2.round … --label-commit {sha}`."]
    else:
        note_code = code_note(sha, [off, corp, nz] if sets_sha == sha else [off, own_c, own_n])
        if note_code:
            L[1:1] = ["", note_code]
        if sets_sha != sha:
            note_sets = code_note(sets_sha, [[d for d in corp if d not in own_c], [d for d in nz if d not in own_n]]
                                  ).replace("Код прогонов сверен", "Код прогонов наборов сверен", 1)
            if note_sets:
                L[3 if note_code else 1:3 if note_code else 1] = ["", note_sets]
        L += newer_lines(sha, newer or [], view_check)
        L += gate_lines(sha, checks)
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.final", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", required=True, help="коммит замеров или тег релиза (v2.0.0)")
    ap.add_argument("--code", help="коммит, на котором мерили, если --commit — тег (по умолчанию — сам тег); auto — "
                                   "найти по git замер официального документа с тем же кодом, что у тега")
    ap.add_argument("--newer", action="append", default=[], metavar="SHA",
                    help="ещё и официальный документ на более новом коде (исправления после замера), с разницей кода")
    ap.add_argument("--no-view", action="store_true",
                    help="не сверять вход модели (вид документов оценки и промпты) на другом коде — `viewdiff`")
    ap.add_argument("--sets-from", metavar="SHA",
                    help="корпус, новые ТЗ и чистые наборы — с этого кода (на коде релиза не мерили), с пометкой")
    ap.add_argument("--write", action="store_true", help="записать блок «Финальные цифры» в RESULTS.md")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.code == "auto":
        a.code = measured_code(a.commit)
        if not a.code:
            tag_sha, _ = resolve(a.commit)
            print(f"На коде `{a.commit}` (`{tag_sha}`) официальный документ не мерили — сначала замер, например: "
                  f"python -m evaluation.v2.round --name \"W4-07 тег {a.commit}\" --official sonnet haiku --no-corpus "
                  f"--no-newtz --no-cache --label-commit {tag_sha}; вход модели против прошлого кода — "
                  f"python -m evaluation.v2.viewdiff <прошлый код> {tag_sha} --rules.")
            return 2
        print(f"--code auto: код `{a.commit}` совпадает с кодом замеров `{a.code}`", file=sys.stderr)
    sha, note = resolve(a.code or a.commit)
    extra: list[str] = []
    if a.code:
        tag_sha, _ = resolve(a.commit)
        same = same_code(tag_sha, sha)
        note = (f"тег `{a.commit}` = `{tag_sha}`, код " + {True: "совпадает", False: "**не совпадает**",
                                                         None: "не сверен"}[same] + f" с `{sha}`")
        if same is False:
            note += f": отличаются {code_diff(sha, tag_sha)}"
            if not a.no_view:
                extra.append(view_line(sha, tag_sha))
    sets_sha = resolve(a.sets_from)[0] if a.sets_from else None
    ref = a.commit + (f" --code {a.code}" if a.code else "")
    text = render(ref, sha, note, newer=a.newer, extra=extra, view_check=not a.no_view, sets_sha=sets_sha)
    print(text)
    if a.write:
        put_results_block(RESULTS, "final", text, "Финальные цифры релиза (W4-07)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
