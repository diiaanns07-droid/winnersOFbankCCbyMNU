"""Стенд №29: этапы `lens_architect` и `lens_risk` на сохранённых входах, без судьи.

    PYTHONPATH=src python tests/v2/fixtures/29_measure/measure.py prep                    # mock-прогоны (нарезка, правила)
    PYTHONPATH=src python tests/v2/fixtures/29_measure/measure.py run --lens architect --doc official --model haiku --tag v0a
    PYTHONPATH=src python tests/v2/fixtures/29_measure/measure.py score                   # все сохранённые ответы
    PYTHONPATH=src python tests/v2/fixtures/29_measure/measure.py replay --tag v0a        # тот же ответ модели, код ветки

`run` — один живой вызов этапа (`python -m bcc_review stage …`, провайдер `claude_cli`); сырой ответ модели
сохраняется в `answers/<док>.<линза>.<модель>.<метка>.json`, поэтому правки постобработки пересчитываются без
модели (`replay`: mock-провайдер с этим ответом → тот же этап кода ветки).

Счёт (`score`):
* официальный — для каждого пункта эталона «есть кандидат линзы со статусом match» (строки-опоры + ключевые
  слова, `evaluation.v2.score.pair_info`), отдельно С7 и С14; и паросочетание счётчика №15 (как у судьи);
* чистые (`*_clean` open2) — critical / major / minor и заголовки critical и major;
* дефектные open2 — пункты своего эталона «match».
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ANSWERS = HERE / "answers"
RUNS = ROOT / "runs"
OUT = ROOT / "out" / "29"
PY = sys.executable
OPEN2 = ROOT / "evaluation" / "v2" / "open2"
DOCS = {"official": ROOT / "release" / "input" / "requirements.md"}
for case in ("capital", "grace", "insurance", "insurance_inject", "qr",
             "capital_clean", "grace_clean", "insurance_clean", "qr_clean"):
    DOCS[case] = OPEN2 / case / "source.md"
GOLD = {"official": ROOT / "evaluation" / "v2" / "official" / "gold.yaml"}
GOLD.update({c: OPEN2 / c / "gold.yaml" for c in DOCS if c != "official" and not c.endswith("_clean")})
FOCUS = ("С7", "С14")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    env = {"PYTHONPATH": str(ROOT / "src")}
    import os
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, env={**os.environ, **env})


def mock_id(doc: str) -> str:
    return f"29m-{doc}"


def prep(docs: list[str]) -> None:
    for d in docs:
        rid = mock_id(d)
        if (RUNS / rid / "stages" / "segment.json").exists():
            continue
        cmd = [PY, "-m", "bcc_review", str(DOCS[d]), str(OUT / "tmp" / f"{rid}.md"), "--provider", "mock",
               "--run-id", rid, "--no-html", "-q"]
        if d != "official":
            empty = OUT / "empty_mock"
            empty.mkdir(parents=True, exist_ok=True)
            cmd += ["--mock-dir", str(empty)]  # нарезка — кодом (запасной путь №04), сигналы — правила №12
        r = sh(cmd)
        print(d, "mock rc", r.returncode, (r.stderr or "")[-300:])


def answer_path(doc: str, lens: str, model: str, tag: str) -> Path:
    return ANSWERS / f"{doc}.{lens}.{model}.{tag}.json"


def run_stage(doc: str, lens: str, model: str, tag: str, provider: str = "claude_cli",
              mock_dir: Path | None = None) -> dict:
    prep([doc])
    rid = f"29s-{doc}-{lens}-{model}-{tag}" + ("-replay" if mock_dir else "")
    cmd = [PY, "-m", "bcc_review", "stage", f"lens_{lens}", "--doc", str(DOCS[doc]), "--from",
           str(RUNS / mock_id(doc)), "--provider", provider, "--run-id", rid, "--no-html", "-q", "--no-cache"]
    if provider != "mock":
        cmd += ["--model", model]
    if mock_dir:
        cmd += ["--mock-dir", str(mock_dir)]
    r = sh(cmd)
    st = json.loads((RUNS / rid / "stages" / f"lens_{lens}.json").read_text(encoding="utf-8"))
    q = json.loads((RUNS / rid / "stages" / "quotes.json").read_text(encoding="utf-8"))
    kept = [c for c in (q.get("output") or {}).get("candidates") or [] if c.get("source") == f"lens:{lens}"]
    raw = None
    rp = RUNS / rid / "responses" / f"lens_{lens}.json"
    if rp.exists():
        raw = json.loads(rp.read_text(encoding="utf-8"))
    return {"rc": r.returncode, "status": st.get("status"), "seconds": st.get("seconds"), "calls": st.get("calls"),
            "error": st.get("error"), "raw": raw, "stage": (st.get("output") or {}), "kept": kept,
            "stderr": (r.stderr or "")[-500:]}


def cmd_run(a: argparse.Namespace) -> None:
    res = run_stage(a.doc, a.lens, a.model, a.tag)
    ANSWERS.mkdir(parents=True, exist_ok=True)
    p = answer_path(a.doc, a.lens, a.model, a.tag)
    p.write_text(json.dumps({"doc": a.doc, "lens": a.lens, "model": a.model, "tag": a.tag,
                             "seconds": res["seconds"], "status": res["status"], "raw": res["raw"],
                             "kept": res["kept"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p.name, res["status"], res["seconds"], "с;", "кандидатов после сверки:", len(res["kept"]), res["error"] or "")
    print(summary_line(a.doc, res["kept"]))


def cmd_replay(a: argparse.Namespace) -> None:
    """Сохранённый сырой ответ модели → этап кода ветки (mock-провайдер), без живого вызова."""
    for p in sorted(ANSWERS.glob(f"*.{a.tag}.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if not d.get("raw"):
            continue
        md = OUT / "replay" / p.stem
        md.mkdir(parents=True, exist_ok=True)
        (md / f"lens_{d['lens']}.json").write_text(json.dumps(d["raw"], ensure_ascii=False), encoding="utf-8")
        res = run_stage(d["doc"], d["lens"], d["model"], d["tag"], provider="mock", mock_dir=md)
        print(p.stem, "→", summary_line(d["doc"], res["kept"]))


# ─────────────────────────── счёт ───────────────────────────

def _gold(doc: str):
    from evaluation.v2 import score as sc
    return sc.load_gold(GOLD[doc]) if doc in GOLD else None


def lens_matches(doc: str, kept: list[dict]) -> dict[str, list[str]]:
    """Пункт эталона → заголовки кандидатов со статусом match (без паросочетания: «линза нашла»)."""
    from evaluation.v2 import score as sc
    g = _gold(doc)
    if not g:
        return {}
    lines = sc.load_doc(ROOT / g["document"])
    rep = sc.as_report({"candidates": kept}, g)
    out: dict[str, list[str]] = {}
    for f in sc.normalize_findings(rep):
        f["_lines"], _ = sc.finding_lines(f, lines, True)
        f["_text"] = (f["title"] + " " + f["text"]).replace("ё", "е").replace("Ё", "Е")
        f["_title"] = f["title"].replace("ё", "е").replace("Ё", "Е")
        for it in g["items"]:
            if sc.pair_info(it, f)["status"] == "match":
                out.setdefault(it["id"], []).append(f["title"])
    return out


def assigned(doc: str, kept: list[dict]) -> set[str]:
    """Паросочетание счётчика №15 без арбитра (строгий счёт): какие пункты засчитаны."""
    from evaluation.v2 import score as sc
    g = _gold(doc)
    if not g:
        return set()
    res = sc.score_report(sc.as_report({"candidates": kept}, g), g, report_md=None, run_dir=None, arbiter="off",
                          cache_path=Path(str(GOLD[doc]).replace("gold.yaml", "arbiter_cache.jsonl")))
    return {x["gold"] for x in res["assignment"]}


def sev_counts(kept: list[dict]) -> dict[str, int]:
    out = {"critical": 0, "major": 0, "minor": 0}
    for c in kept:
        out[c.get("severity", "major")] = out.get(c.get("severity", "major"), 0) + 1
    return out


def summary_line(doc: str, kept: list[dict]) -> str:
    s = sev_counts(kept)
    head = f"{doc}: {s['critical']}/{s['major']}/{s['minor']} (c/M/m)"
    if doc.endswith("_clean"):
        cm = [f"[{c['severity']}] {c.get('title', '')}" for c in kept if c.get("severity") in ("critical", "major")]
        return head + ("\n    " + "\n    ".join(cm) if cm else "")
    m = lens_matches(doc, kept)
    own = sorted(m)
    if doc == "official":
        foc = " ".join(f"{k}={'да' if k in m else 'нет'}" for k in FOCUS)
        try:
            asg = assigned(doc, kept)
            foc += " | паросочетание: " + " ".join(f"{k}={'да' if k in asg else 'нет'}" for k in FOCUS)
        except Exception as exc:  # noqa: BLE001 — счёт без арбитра не должен ронять стенд
            foc += f" | паросочетание: ошибка {type(exc).__name__}"
        return f"{head}; {foc}; match: {', '.join(own)}"
    return f"{head}; match: {', '.join(own)}"


def cmd_score(a: argparse.Namespace) -> None:
    for p in sorted(ANSWERS.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if a.tag and d.get("tag") != a.tag:
            continue
        print(p.stem, d.get("seconds"), "с →", summary_line(d["doc"], d.get("kept") or []))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("prep")
    pp.add_argument("--docs", nargs="*", default=list(DOCS))
    pr = sub.add_parser("run")
    pr.add_argument("--lens", required=True, choices=["architect", "risk"])
    pr.add_argument("--doc", required=True, choices=list(DOCS))
    pr.add_argument("--model", default="haiku")
    pr.add_argument("--tag", required=True)
    ps = sub.add_parser("score")
    ps.add_argument("--tag", default="")
    pl = sub.add_parser("replay")
    pl.add_argument("--tag", required=True)
    a = ap.parse_args()
    if a.cmd == "prep":
        prep(a.docs)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "score":
        cmd_score(a)
    else:
        cmd_replay(a)


if __name__ == "__main__":
    main()
