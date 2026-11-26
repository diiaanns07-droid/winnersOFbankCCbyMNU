"""Контрольная арифметика счётчика: ручной ответ против счётчика.

    python -m evaluation.harness selfcheck [--out selfcheck.md] [--json selfcheck.json]

Ручные ответы лежат в controls/*/expected.json и записаны до запуска. Команда считает
контроли действующим кодом, проверяет все перестановки входных строк и повтор формата и
печатает таблицу. Код выхода 1, если хоть одна строка расходится.
"""
from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

from . import POLICY_VERSION, __version__, harness_sha256
from .schema import Manifest, parse_gold, parse_predictions, read_jsonl
from .score import matrix_rows, score
from .taxonomy import Taxonomy

CONTROLS = Path(__file__).resolve().parent / "controls"
OPEN_CONTROLS = Path(__file__).resolve().parents[1] / "dev" / "controls"


class Ratio(tuple):
    """Дробь как в ручном ответе, без сокращения (2/4 остаётся 2/4)."""

    @property
    def value(self) -> float:
        return self[0] / self[1]


def _f(v):
    if v is None:
        return None
    a, b = str(v).split("/")
    return Ratio((int(a), int(b)))


def _show(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, Ratio):
        return f"{v[0]}/{v[1]} = {v.value:.4f}"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _same(expected, got) -> bool:
    if isinstance(expected, Ratio):
        return got is not None and abs(expected.value - got) < 1e-12
    return expected == got


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k != "where"}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def _canon(m) -> str:
    return json.dumps(_strip(m), ensure_ascii=False, sort_keys=True)


def _run(tax, gold_rows, pred_rows, type_match="hierarchy", manifest=None):
    g = parse_gold(copy.deepcopy(gold_rows), tax)
    p, r = parse_predictions(copy.deepcopy(pred_rows), tax)
    return score(g, p, r, tax, type_match=type_match, manifest=manifest)


def collect() -> list[dict]:
    tax = Taxonomy.load()
    rows: list[dict] = []

    def add(control, metric, expected, got):
        rows.append({"control": control, "metric": metric, "expected": expected, "got": got,
                     "ok": _same(expected, got)})

    # --- 2 TP / 1 FP / 1 FN и повтор находки
    hand = CONTROLS / "hand_2tp"
    he = json.loads((hand / "expected.json").read_text(encoding="utf-8"))["expected"]
    g = read_jsonl(hand / "labels.jsonl")
    for name, pred_file in (("base", "predictions.jsonl"), ("with_duplicate", "predictions_with_duplicate.jsonl")):
        m = _run(tax, g, read_jsonl(hand / pred_file))
        e = he[name]
        label = "hand_2tp" if name == "base" else "hand_2tp + повтор F-2"
        for k in ("tp", "fp", "fn", "duplicates"):
            add(label, k.upper() if k != "duplicates" else "дубли", e[k], m["micro"][k])
        for k in ("precision", "recall", "precision_strict"):
            add(label, k, _f(e[k]), m["micro"][k])

    # --- граф A/B: X → {A, B}, Y и дубль Z → A, W — одна сторона A, V — чистый контроль
    rb = CONTROLS / "robustness"
    re_ = json.loads((rb / "expected.json").read_text(encoding="utf-8"))["expected"]
    g = read_jsonl(rb / "labels.jsonl")
    p = read_jsonl(rb / "predictions.jsonl")
    runs = [r for r in p if r["record"] == "run"]
    finds = [r for r in p if r["record"] == "finding"]
    for policy in ("hierarchy", "exact"):
        e = re_[policy]
        m = _run(tax, g, p, policy)
        label = f"граф A/B, {policy}"
        for k, title in (("tp", "TP"), ("fp", "FP"), ("fn", "FN"), ("duplicates", "дубли"),
                         ("pending_adjudication", "на разборе"), ("clean_false_alarms", "тревоги на чистом"),
                         ("tp_parent_level", "TP уровня parent")):
            add(label, title, e[k], m["micro"][k])
        for k in ("precision", "recall", "f1", "precision_strict"):
            add(label, k, _f(e[k]), m["micro"][k])
        add(label, "пары TP", json.dumps(e["tp_pairs"], ensure_ascii=False, sort_keys=True),
            json.dumps({t["label_id"]: t["defect_id"] for t in m["true_positives"]}, ensure_ascii=False, sort_keys=True))
        add(label, "дубль", json.dumps(e["duplicates_of"], ensure_ascii=False),
            json.dumps({d["defect_id"]: d["duplicate_of"] for d in m["duplicates"]}, ensure_ascii=False))
        disputed = sorted([fp["defect_id"], n["label_id"], n["reason"]] for fp in m["false_positives"] for n in fp["near"])
        add(label, "спорные пары", len(e["disputed_pairs"]), len(disputed) if disputed == sorted(e["disputed_pairs"]) else
            f"{len(disputed)} (другие)")
        outs = {_canon(_run(tax, g, runs + list(perm), policy)) for perm in itertools.permutations(finds)}
        add(label, "разных результатов на 120 перестановках находок", 1, len(outs))
    outs = {_canon(_run(tax, list(perm), p)) for perm in itertools.permutations(g)}
    add("граф A/B, hierarchy", "разных результатов на 24 перестановках эталона", 1, len(outs))
    pc = _run(tax, g, p)["per_case"]
    for cid, exp in re_["hierarchy"]["per_case"].items():
        for k, v in exp.items():
            add(f"граф A/B, кейс {cid}", k, _f(v), pc[cid][k])

    # --- повтор формата: те же находки и run для DOCX того же case_id
    man = Manifest.load(rb / "manifest.json")
    md_only = _run(tax, g, p, manifest=man)
    sha = next(x["source_sha256"] for x in g if x["case_id"] == "rb.conflict")
    docx = [{k: v for k, v in r.items() if k != "source_sha256"} | {"render_id": "rb.conflict@docx"}
            for r in p if r.get("source_sha256") == sha]
    both = _run(tax, g, p + docx, manifest=man)
    fe = re_["format_repeat"]
    add("повтор формата MD+DOCX", "независимых кейсов", fe["independent_cases"], both["counts"]["independent_cases"])
    add("повтор формата MD+DOCX", "micro как у одного MD", fe["micro_equals_md_only"], both["micro"] == md_only["micro"])
    add("повтор формата MD+DOCX", "кейсов в per_format.docx", fe["per_format_docx_cases"],
        both["per_format"]["docx"]["cases_measured"])

    # --- открытый корпус: похожая цитата у двух дефектов, дубль находки, чистый документ с тревогой
    if (OPEN_CONTROLS / "expected.json").exists():
        oe = json.loads((OPEN_CONTROLS / "expected.json").read_text(encoding="utf-8"))["expected"]
        og = read_jsonl(OPEN_CONTROLS / "labels.jsonl")
        op = read_jsonl(OPEN_CONTROLS / "predictions.jsonl")
        om = Manifest.load(OPEN_CONTROLS / "manifest.json")
        oruns = [r for r in op if r["record"] == "run"]
        ofinds = [r for r in op if r["record"] == "finding"]
        for policy in ("hierarchy", "exact"):
            e = oe[policy]
            m = _run(tax, og, op, policy, manifest=om)
            label = f"открытый корпус, {policy}"
            for k, title in (("tp", "TP"), ("fp", "FP"), ("fn", "FN"), ("duplicates", "дубли"),
                             ("pending_adjudication", "на разборе"), ("clean_false_alarms", "тревоги на чистом"),
                             ("tp_parent_level", "TP уровня parent")):
                add(label, title, e[k], m["micro"][k])
            for k in ("precision", "recall", "f1", "precision_strict"):
                add(label, k, _f(e[k]), m["micro"][k])
            if policy == "hierarchy":
                got = sorted([r["outcome"], r["case_id"], r.get("label_id"), r.get("defect_id")] for r in matrix_rows(m))
                add(label, "матрица TP/FP/FN/DUP (строк)", len(e["matrix"]),
                    len(got) if got == sorted(e["matrix"]) else f"{len(got)} (другие)")
                for cid, exp in e["per_case"].items():
                    for k, v in exp.items():
                        add(f"открытый корпус, кейс {cid.split('.')[0]}", k, _f(v), m["per_case"][cid][k])
            outs = {_canon(_run(tax, og, oruns + list(perm), policy, manifest=om))
                    for perm in itertools.permutations(ofinds)}
            add(label, "разных результатов на 120 перестановках находок", 1, len(outs))
        z = _run(tax, og, oruns, manifest=om)
        ze = oe["no_findings"]
        for k, v in ze["micro"].items():
            add("открытый корпус, без находок", k, _f(v), z["micro"][k])
        for cid, exp in ze["per_case"].items():
            for k, v in exp.items():
                add(f"открытый корпус, без находок, {cid.split('.')[0]}", k, _f(v), z["per_case"][cid][k])
    return rows


def render(rows: list[dict]) -> str:
    head = (f"# Контрольная арифметика счётчика\n\nСчётчик {__version__} ({POLICY_VERSION}), "
            f"sha256 `{harness_sha256()}`.\nРучной ответ — `evaluation/harness/controls/*/expected.json`.\n\n"
            "| Контроль | Показатель | Ручной ответ | Счётчик | Совпадает |\n| :--- | :--- | :--- | :--- | :---: |\n")
    body = "".join(f"| {r['control']} | {r['metric']} | {_show(r['expected'])} | {_show(r['got'])} | "
                   f"{'да' if r['ok'] else '**НЕТ**'} |\n" for r in rows)
    bad = sum(1 for r in rows if not r["ok"])
    return head + body + f"\nСтрок: {len(rows)}, расхождений: {bad}.\n"


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m evaluation.harness selfcheck")
    ap.add_argument("--out", help="записать таблицу Markdown")
    ap.add_argument("--json", help="записать строки JSON")
    a = ap.parse_args(argv)
    rows = collect()
    md = render(rows)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps([{**r, "expected": _show(r["expected"]), "got": _show(r["got"])}
                                            for r in rows], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(md)
    return 0 if all(r["ok"] for r in rows) else 1
