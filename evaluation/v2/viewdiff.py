"""Вид документа на двух коммитах: меняет ли новый код то, что получает модель.

    python -m evaluation.v2.viewdiff 747364c 868787d               # все документы, которые читает оценка
    python -m evaluation.v2.viewdiff 28fe64f HEAD --all-formats    # и их DOCX/PDF рядом с MD
    python -m evaluation.v2.viewdiff A B --docs release/input/requirements.md --json out/viewdiff.json
    python -m evaluation.v2.viewdiff 868787d 3e7133c --rules          # + правила без модели на чистых документах

Зачем: после заморозки в код вливают правки (чтение, этапы), и каждую голову приходилось перемерять моделью —
5–10 минут и разброс С ±1 между прогонами. Если вид документа (строки, разделы, название) и промпты этапов не
изменились, первые этапы (сегментация, линзы, сверка) получают тот же вход: разница в цифрах — разброс выборки,
а не правка. Сверка детерминированная и без вызовов модели.

`src/` каждого коммита выгружается (`git archive`) во временный каталог; вид строит `bcc_review.v2.docview.load`
того же коммита в отдельном процессе (`python -I`, в пути — только выгруженный `src`; процесс проверяет, что
модуль загружен оттуда, а не из установленного пакета). Сравниваются название, формат, предупреждения, страницы и у
каждой строки — номер, текст, страница, раздел, строка источника, блок, вид, уровень и признак заголовка.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from .common import ROOT

LINE_FIELDS = ("n", "text", "page", "section", "src_line", "block_id", "kind", "level", "heading")
PROMPTS = "src/bcc_review/v2/prompts"
STAGES = "src/bcc_review/v2/stages"
# Этапы основного прогона (без `--answers`), если нет готового отчёта официального документа, откуда их взять
MAIN_STAGES = ("segment", "rules", "lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency", "quotes",
               "judge", "clarify")
# Общий код, через который проходит вход каждого этапа основного прогона
SHARED_CODE = ("src/bcc_review/v2/stages/lens.py", "src/bcc_review/v2/stages/__init__.py", "src/bcc_review/v2/llm.py",
               "src/bcc_review/v2/context.py", "src/bcc_review/v2/pipeline.py")
# Этапы без модели, чей код лежит вне stages/: их кандидаты и цитаты идут судье — это тоже вход модели
STAGE_CODE = {"rules": "src/bcc_review/v2/rules", "quotes": "src/bcc_review/v2/quotes.py"}

# Код дочернего процесса: argv — каталог выгруженного src, затем пути документов; печатает JSON {путь: вид}.
_CHILD = r"""
import json, sys
src = sys.argv[1]
sys.path.insert(0, src)
from bcc_review.v2 import docview
if not str(docview.__file__).startswith(src):
    raise SystemExit("docview загружен не из выгруженного кода: " + str(docview.__file__))
FIELDS = %r
out = {}
for f in sys.argv[2:]:
    try:
        v = docview.load(f)
    except Exception as exc:
        out[f] = {"error": repr(exc)[:300]}
        continue
    pages = v.get("pages")
    out[f] = {"title": v.get("title"), "format": v.get("format"), "warnings": list(v.get("warnings") or []),
              "pages": len(pages) if isinstance(pages, (list, dict)) else pages,
              "lines": [[ln.get(k) for k in FIELDS] for ln in v.get("lines") or []]}
sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
""" % (LINE_FIELDS,)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def resolve(ref: str) -> str:
    """Полный SHA коммита (тег, ветка, короткий SHA)."""
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def export_src(sha: str, dest: Path) -> Path:
    """`src/` коммита в каталог ``dest`` (без рабочей копии и без worktree)."""
    data = subprocess.run(["git", "archive", "--format=tar", sha, "src"], cwd=str(ROOT), capture_output=True,
                          check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:  # Python < 3.12: нет параметра filter
            tf.extractall(dest)
    return dest / "src"


def views_at(sha: str, docs: list[str], timeout: int = 900) -> dict:
    """Вид каждого документа кодом коммита ``sha``: {путь: {title, format, warnings, pages, lines} | {error}}."""
    with tempfile.TemporaryDirectory(prefix="viewdiff-") as tmp:
        src = export_src(sha, Path(tmp))
        r = subprocess.run([sys.executable, "-I", "-c", _CHILD, str(src), *docs], cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"вид документов на {sha[:7]}: rc={r.returncode}\n{(r.stderr or r.stdout)[-1500:]}")
    return json.loads(r.stdout)


def _digest(view: dict) -> str:
    return hashlib.sha256(json.dumps(view, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


def first_difference(a: dict, b: dict) -> str:
    """Где виды расходятся впервые — одной строкой для таблицы."""
    if "error" in a or "error" in b:
        return f"не прочитан: было {a.get('error', 'ok')}, стало {b.get('error', 'ok')}"[:200]
    for k in ("title", "format", "pages", "warnings"):
        if a.get(k) != b.get(k):
            return f"{k}: {str(a.get(k))[:60]!r} → {str(b.get(k))[:60]!r}"
    la, lb = a.get("lines") or [], b.get("lines") or []
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            fields = [LINE_FIELDS[j] for j in range(len(LINE_FIELDS)) if j < len(x) and j < len(y) and x[j] != y[j]]
            k = LINE_FIELDS.index(fields[0]) if fields else 1
            sx, sy = _window(str(x[k]), str(y[k]))
            return f"строка {x[0] if x else i + 1}, {', '.join(fields) or 'поля'}: {sx!r} → {sy!r}"
    return f"строк {len(la)} → {len(lb)}"


def _window(x: str, y: str, before: int = 15, width: int = 45) -> tuple[str, str]:
    """Кусок двух строк вокруг первого отличающегося символа (общее начало длинной строки — «…»)."""
    i = next((j for j, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
    s = max(0, i - before)
    cut = (lambda v: ("…" if s else "") + v[s:s + width] + ("…" if len(v) > s + width else ""))
    return cut(x), cut(y)


def compare(va: dict, vb: dict) -> dict:
    """Сравнение видов двух коммитов: совпавшие, отличающиеся (с первым отличием), не прочитанные."""
    same, diff, errors = [], [], []
    for doc in sorted(set(va) | set(vb)):
        a, b = va.get(doc) or {"error": "нет вида"}, vb.get(doc) or {"error": "нет вида"}
        if "error" in a or "error" in b:
            errors.append({"doc": doc, "a": a.get("error"), "b": b.get("error")})
            if "error" in a and "error" in b:
                continue
        if a == b:
            same.append(doc)
        elif not ("error" in a or "error" in b):
            diff.append({"doc": doc, "lines": [len(a.get("lines") or []), len(b.get("lines") or [])],
                         "where": first_difference(a, b), "digest": [_digest(a), _digest(b)]})
    return {"docs": len(set(va) | set(vb)), "same": same, "diff": diff, "errors": errors}


def prompts_changed(a: str, b: str) -> list[str]:
    """Файлы промптов этапов, которые отличаются между коммитами."""
    out = _git("diff", "--name-only", a, b, "--", PROMPTS)
    return [p[len(PROMPTS) + 1:] for p in out.splitlines() if p.strip()]


def main_stages() -> tuple[str, ...]:
    """Этапы основного прогона — из последнего отчёта официального документа (`run.stages`), иначе `MAIN_STAGES`."""
    reps = sorted((ROOT / "evaluation" / "v2" / "measurements").glob("*/report.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for rp in reps[:5]:
        try:
            st = (json.loads(rp.read_text(encoding="utf-8")).get("run") or {}).get("stages") or {}
        except (OSError, ValueError):
            continue
        if st:
            return tuple(st)
    return MAIN_STAGES


def _in_main(name: str, stages: tuple[str, ...]) -> bool:
    stem = Path(name).stem
    return stem == "_system" or any(stem == s or stem.startswith(s + "_") for s in stages)


def stage_code_changed(a: str, b: str, stages: tuple[str, ...]) -> list[str]:
    """Код этапов основного прогона (в т. ч. правил и сверки цитат) и общий код их входа, который отличается между
    коммитами. Правила целиком — одной строкой «rules/ (N файлов)»."""
    extra = [v for k, v in STAGE_CODE.items() if k in stages]
    out = _git("diff", "--name-only", a, b, "--", STAGES, *SHARED_CODE, *extra)
    files = [p for p in out.splitlines() if p.strip()]
    keep, rules = [], 0
    for p in files:
        if p.startswith(STAGE_CODE["rules"] + "/"):
            rules += 1
        elif p in SHARED_CODE or p == STAGE_CODE["quotes"] or _in_main(p, stages):
            keep.append(p[len("src/bcc_review/v2/"):])
    return keep + ([f"rules/ ({rules} {'файл' if rules == 1 else 'файла' if rules in (2, 3, 4) else 'файлов'})"]
                   if rules else [])


def evaluation_docs(all_formats: bool = False) -> list[str]:
    """Документы, которые читает оценка: официальный, корпус (основной вид кейса), open2, чистые №20 (MD).
    С ``all_formats`` — ещё DOCX/PDF тех же документов (корпус — все виды из манифеста)."""
    import yaml

    out: list[str] = []
    gold = yaml.safe_load((ROOT / "evaluation" / "v2" / "official" / "gold.yaml").read_text(encoding="utf-8"))
    if gold.get("document"):
        out.append(str(gold["document"]))
    man = ROOT / "evaluation" / "dev" / "corpus" / "manifest.json"
    if man.exists():
        for c in json.loads(man.read_text(encoding="utf-8")).get("cases") or []:
            for r in c.get("renders") or []:
                if all_formats or r.get("format") == c.get("primary_render"):
                    out.append(str(Path("evaluation/dev/corpus") / r["path"]))
    for sub in ("open2", "clean"):
        for d in sorted((ROOT / "evaluation" / "v2" / sub).glob("*/")):
            for name in (("source.md", "source.docx", "source.pdf") if all_formats else ("source.md",)):
                if (d / name).exists():
                    out.append(str((d / name).relative_to(ROOT)))
    seen: set[str] = set()
    return [p for p in out if (ROOT / p).exists() and not (p in seen or seen.add(p))]


def check(a: str, b: str, docs: list[str] | None = None, all_formats: bool = False) -> dict:
    """Сверка коммитов ``a`` и ``b``: вид документов оценки и промпты этапов."""
    sa, sb = resolve(a), resolve(b)
    docs = docs or evaluation_docs(all_formats)
    paths = [str(ROOT / d) if not Path(d).is_absolute() else d for d in docs]
    rel = {p: (str(Path(p).relative_to(ROOT)) if str(p).startswith(str(ROOT)) else p) for p in paths}
    if sa == sb:
        va = vb = views_at(sa, paths)
    else:
        va, vb = views_at(sa, paths), views_at(sb, paths)
    res = compare({rel[k]: v for k, v in va.items()}, {rel[k]: v for k, v in vb.items()})
    stages = main_stages()
    pr = prompts_changed(sa, sb)
    res.update({"a": sa, "b": sb, "main_stages": list(stages), "prompts_changed": pr,
                "prompts_main": [p for p in pr if _in_main(p, stages)],
                "prompts_other": [p for p in pr if not _in_main(p, stages)],
                "stage_code_changed": stage_code_changed(sa, sb, stages),
                "docview_changed": bool(_git("diff", "--name-only", sa, sb, "--", "src/bcc_review/v2/docview.py",
                                             "src/bcc_review/v2/readers_html.py").strip())})
    return res


def same_input(res: dict) -> bool:
    """Вид документов, промпты и код этапов основного прогона — те же: модель получает тот же вход."""
    return not (res["diff"] or res["errors"] or res.get("prompts_main") or res.get("stage_code_changed"))


def summary_line(res: dict) -> str:
    """Одна строка для `final` и статуса: «вид N документов оценки тот же, промпты этапов не менялись»."""
    n, same, diff, errs = res["docs"], len(res["same"]), res["diff"], res["errors"]
    if not diff and not errs:
        view = f"вид документов оценки не изменился ({n} из {n})"
    else:
        view = f"вид документов оценки: тот же у {same} из {n}, отличается у {len(diff)}" + (
            f", не прочитан у {len(errs)}" if errs else "")
        if diff:
            view += " (" + "; ".join(f"{Path(d['doc']).parent.name or d['doc']}: {d['where']}" for d in diff[:3]) + (
                "; …" if len(diff) > 3 else "") + ")"
    main, other = res.get("prompts_main"), res.get("prompts_other")
    if main is None:  # результат без разбора по этапам
        main, other = res.get("prompts_changed") or [], []
    prompts = ("промпты основного прогона не менялись" if not main else "промпты основного прогона изменены: "
               + ", ".join(main))
    if other:
        prompts += " (вне его — " + ", ".join(other) + ")"
    code = res.get("stage_code_changed")
    if code is not None:
        prompts += "; код этапов основного прогона " + ("тот же" if not code else "изменён: " + ", ".join(code))
    return f"{view}; {prompts}"


def render(res: dict) -> str:
    L = [f"# Вид документов оценки: `{res['a'][:7]}` → `{res['b'][:7]}`", "",
         f"Документов {res['docs']}: вид совпал у {len(res['same'])}, отличается у {len(res['diff'])}, "
         f"не прочитан у {len(res['errors'])}. Чтение документа (`docview.py`, `readers_html.py`) в коде "
         f"{'изменено' if res.get('docview_changed') else 'не менялось'}.", "",
         summary_line(res)[:1].upper() + summary_line(res)[1:] + ".", ""]
    if res["diff"]:
        L += ["| Документ | Строк было → стало | Первое отличие |", "| :--- | :--- | :--- |"]
        L += [f"| {d['doc']} | {d['lines'][0]} → {d['lines'][1]} | {d['where'].replace('|', '/')} |"
              for d in res["diff"]]
        L.append("")
    if res["errors"]:
        L += ["Не прочитаны:", ""] + [f"* {e['doc']}: было {e['a'] or 'ok'}, стало {e['b'] or 'ok'}"
                                      for e in res["errors"]] + [""]
    return "\n".join(L)


def clean_docs() -> list[str]:
    """Чистые документы оценки: 8 чистых №20, чистые версии open2, чистые кейсы корпуса (без пустого)."""
    from .newtz import OPEN2, discover

    out = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "evaluation" / "v2" / "clean").glob("*/source.md"))]
    for c in discover(OPEN2):
        if c["variant"] == "clean" and c.get("doc"):
            out.append(str(Path(c["doc"]).resolve().relative_to(ROOT)))
    man = ROOT / "evaluation" / "dev" / "corpus" / "manifest.json"
    if man.exists():
        for c in json.loads(man.read_text(encoding="utf-8")).get("cases") or []:
            if c.get("expected_outcome") == "clean" and c.get("case_id") != "edge.empty":
                r = next((r for r in c.get("renders") or [] if r.get("format") == c.get("primary_render")), None)
                if r:
                    out.append(str(Path("evaluation/dev/corpus") / r["path"]))
    return [p for p in dict.fromkeys(out) if (ROOT / p).exists()]


def rules_at(sha: str, docs: list[str], timeout: int = 300, keep: bool = False) -> dict:
    """Находки правил без модели (`--provider offline`) кодом коммита: {документ: {severity: n, "top": [...]}};
    с ``keep`` — и весь report.json (для счёта по эталону)."""
    import os

    out: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="viewdiff-rules-") as tmp:
        src = export_src(sha, Path(tmp))
        env = {**os.environ, "PYTHONPATH": str(src), "PYTHONIOENCODING": "utf-8"}
        chk = subprocess.run([sys.executable, "-c", "import bcc_review; print(bcc_review.__file__)"], cwd=tmp, env=env,
                             capture_output=True, text=True)
        if not chk.stdout.strip().startswith(str(src)):
            raise RuntimeError(f"bcc_review загружен не из выгруженного кода {sha[:7]}: {chk.stdout or chk.stderr}")
        for i, doc in enumerate(docs):
            md = Path(tmp) / "out" / f"{i:02d}.md"
            md.parent.mkdir(exist_ok=True)
            r = subprocess.run([sys.executable, "-m", "bcc_review", str(ROOT / doc), str(md), "--provider", "offline",
                                "-q", "--runs-dir", str(Path(tmp) / "runs")], cwd=tmp, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rj = md.with_suffix(".json")
            if not rj.exists():
                out[doc] = {"error": f"rc={r.returncode}: {(r.stderr or r.stdout)[-200:]}"}
                continue
            rep = json.loads(rj.read_text(encoding="utf-8"))
            fs = rep.get("findings") or []
            sev = {s: sum(1 for f in fs if f.get("severity") == s) for s in ("critical", "major", "minor")}
            out[doc] = {**sev, "top": [f"{f.get('severity')}: {str(f.get('title') or '')[:80]}" for f in fs
                                       if f.get("severity") in ("critical", "major")][:5]}
            if keep:
                out[doc]["report"] = rep
    return out


def official_rules_recall(sha: str) -> dict:
    """Правила без модели на официальном документе, счёт по эталону (текущий счётчик, арбитр выключен): что
    правила находят сами — К и С, которые не зависят от модели."""
    from . import score as sc

    gold = sc.load_gold(sc.DEFAULT_GOLD)
    doc = str(gold.get("document") or "release/input/requirements.md")
    r = rules_at(sha, [doc], keep=True).get(doc) or {}
    if "report" not in r:
        return {"error": r.get("error", "нет отчёта")}
    res = sc.score_report(sc.as_report(r["report"], gold), gold, arbiter="off")
    return {"findings": len(r["report"].get("findings") or []), "K": res["recall"]["critical"]["found"],
            "C": sorted(res["recall"]["major"]["found"], key=lambda x: int(x[1:]))}


def rules_summary(ra: dict, rb: dict) -> dict:
    """Сумма critical/major правил на чистых документах до и после, документы, где стало хуже или лучше."""
    tot = {k: [sum(int(x.get(k) or 0) for x in r.values() if "error" not in x) for r in (ra, rb)]
           for k in ("critical", "major", "minor")}
    worse = [d for d in rb if "error" not in rb[d] and "error" not in (ra.get(d) or {"error": 1})
             and (rb[d]["critical"], rb[d]["major"]) > (ra[d]["critical"], ra[d]["major"])]
    better = [d for d in rb if "error" not in rb[d] and "error" not in (ra.get(d) or {"error": 1})
              and (rb[d]["critical"], rb[d]["major"]) < (ra[d]["critical"], ra[d]["major"])]
    errors = [d for d in set(ra) | set(rb) if "error" in (ra.get(d) or {}) or "error" in (rb.get(d) or {})]
    return {"docs": len(set(ra) | set(rb)), "total": tot, "worse": worse, "better": better, "errors": errors}


def rules_line(s: dict) -> str:
    t = s["total"]
    name = (lambda d: Path(d).parent.name or d)
    line = (f"Правила без модели на {s['docs']} чистых документах: critical {t['critical'][0]} → {t['critical'][1]}, "
            f"major {t['major'][0]} → {t['major'][1]}, minor {t['minor'][0]} → {t['minor'][1]}")
    if s["better"]:
        line += "; лучше — " + ", ".join(name(d) for d in s["better"])
    if s["worse"]:
        line += "; **хуже — " + ", ".join(name(d) for d in s["worse"]) + "**"
    if s["errors"]:
        line += f"; не прогнались — {len(s['errors'])}"
    return line + "."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.viewdiff", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", help="коммит «было» (SHA, тег, ветка)")
    ap.add_argument("b", help="коммит «стало»")
    ap.add_argument("--docs", nargs="+", help="только эти документы (по умолчанию — все документы оценки)")
    ap.add_argument("--all-formats", action="store_true", help="и DOCX/PDF тех же документов, не только MD")
    ap.add_argument("--json", metavar="PATH", help="полный результат в JSON")
    ap.add_argument("--rules", action="store_true",
                    help="и правила без модели (--provider offline) на чистых документах оценки на обоих коммитах")
    a = ap.parse_args(argv)
    res = check(a.a, a.b, a.docs, a.all_formats)
    if a.rules:
        docs = clean_docs()
        ra, rb = rules_at(res["a"], docs), rules_at(res["b"], docs)
        res["rules"] = {"a": ra, "b": rb, **rules_summary(ra, rb),
                        "official": [official_rules_recall(res["a"]), official_rules_recall(res["b"])]}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.write(render(res))
    if res.get("rules"):
        rs = res["rules"]
        sys.stdout.write("\n" + rules_line(rs) + "\n")
        oa, ob = rs.get("official") or [{}, {}]
        if "error" not in oa and "error" not in ob:
            lost = [x for x in oa["K"] + oa["C"] if x not in ob["K"] + ob["C"]]
            new = [x for x in ob["K"] + ob["C"] if x not in oa["K"] + oa["C"]]
            sys.stdout.write(f"На официальном правила без модели находят: {', '.join(oa['K'] + oa['C']) or '—'} → "
                             f"{', '.join(ob['K'] + ob['C']) or '—'} (замечаний {oa['findings']} → {ob['findings']})"
                             + (f"; **потеряны: {', '.join(lost)}**" if lost else "; ничего не потеряно")
                             + (f"; новые: {', '.join(new)}" if new else "") + ".\n")
        for d in sorted(set(rs["a"]) | set(rs["b"])):
            x, y = rs["a"].get(d) or {}, rs["b"].get(d) or {}
            if (x.get("critical"), x.get("major")) != (y.get("critical"), y.get("major")):
                sys.stdout.write(f"* {d}: {x.get('critical')}/{x.get('major')} → {y.get('critical')}/{y.get('major')} "
                                 f"(critical/major); было: {'; '.join(x.get('top') or []) or '—'}\n")
    return 0 if not res["diff"] and not res["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
