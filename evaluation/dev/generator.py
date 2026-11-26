"""Детерминированный генератор открытого dev-корпуса.

Одинаковые GENERATOR_VERSION и seed дают одинаковые смысловые хеши: выбор варианта
мутации — sha256(версия|seed|семейство|оператор) mod число вариантов, без random.
case_id зависит только от содержания (семейство, оператор, вариант), поэтому разные seed,
выбравшие один вариант, дают один кейс, а не два «независимых».
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from evaluation.harness.normalize import tokens

from .families import (DEFECT_OPS, FAMILIES, OP_CRITERION, OP_ISSUE_TYPE, OP_SEVERITY, OPS)

GENERATOR_VERSION = "1.0.0"
LABEL_SCHEMA = "bcc-eval-label/1"
MANIFEST_SCHEMA = "bcc-eval-manifest/1"


class GenerationError(RuntimeError):
    pass


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pick(seed: int, *parts: str, n: int) -> int:
    """Детерминированный выбор индекса из n по seed и ключу."""
    return int(_h("|".join([GENERATOR_VERSION, str(seed), *parts])), 16) % n


def _tidy(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).rstrip("\n") + "\n"


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _unique(text: str, needle: str, what: str) -> int:
    n = text.count(needle)
    if n != 1:
        raise GenerationError(f"{what}: фрагмент {needle[:60]!r} встречается {n} раз (нужно 1)")
    return text.index(needle)


def apply_edit(text: str, edit: dict) -> tuple[str, dict]:
    op = edit["op"]
    if op == "replace":
        pos = _unique(text, edit["find"], "replace")
        new = text[:pos] + edit["new"] + text[pos + len(edit["find"]):]
        rec = {"op": op, "base_line": _line_no(text, pos), "removed": edit["find"], "inserted": edit["new"]}
    elif op == "insert_after":
        pos = _unique(text, edit["after"], "insert_after")
        end = text.find("\n", pos)
        end = len(text) if end < 0 else end
        piece = ("\n\n" + edit["text"] + "\n") if edit.get("block") else ("\n" + edit["text"])
        new = text[:end] + piece + text[end:]
        rec = {"op": op, "base_line": _line_no(text, pos), "after": edit["after"], "removed": "",
               "inserted": edit["text"]}
    elif op == "delete_section":
        start = _unique(text, "\n" + edit["start"], "delete_section.start") + 1
        until = text.find("\n" + edit["until"], start)
        if until < 0:
            raise GenerationError(f"delete_section: нет {edit['until']!r} после {edit['start']!r}")
        until += 1
        new = text[:start] + text[until:]
        rec = {"op": op, "base_line": _line_no(text, start), "removed": text[start:until], "inserted": ""}
    elif op == "delete_line":
        pos = _unique(text, edit["find"], "delete_line")
        ls = text.rfind("\n", 0, pos) + 1
        le = text.find("\n", pos)
        le = len(text) if le < 0 else le + 1
        new = text[:ls] + text[le:]
        rec = {"op": op, "base_line": _line_no(text, ls), "removed": text[ls:le], "inserted": ""}
    else:
        raise GenerationError(f"неизвестная правка {op}")
    return _tidy(new), rec


def _occurrences(hay: list[str], needle: list[str]) -> list[int]:
    n = len(needle)
    return [i for i in range(len(hay) - n + 1) if hay[i:i + n] == needle] if n else []


def locate(text: str, quote: str) -> str:
    """Локатор опоры в Markdown: md:L<строка> (вычисляет программа, а не автор метки)."""
    qt = tokens(quote)
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        if _occurrences(tokens(line), qt):
            return f"md:L{i}"
    head = qt[:3]
    for i, line in enumerate(lines, 1):
        if _occurrences(tokens(line), head):
            return f"md:L{i}"
    return "md:?"


def check_anchor(text: str, quote: str, where: str) -> None:
    occ = _occurrences(tokens(text), tokens(quote))
    if len(occ) != 1:
        raise GenerationError(f"{where}: опора {quote[:70]!r} найдена {len(occ)} раз (нужно ровно 1)")


@dataclass
class Case:
    case_id: str
    family: str
    kind: str                      # base | mutant | combo | edge
    text: str
    base_case_id: str | None
    ops: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    seeds: list[int] = field(default_factory=list)
    transformation: list[dict] = field(default_factory=list)
    effect: list[str] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    edge: str | None = None

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def semantic(self) -> dict:
        return {"generator_version": GENERATOR_VERSION, "case_id": self.case_id, "family": self.family,
                "kind": self.kind, "ops": self.ops, "variants": self.variants, "text": self.text,
                "labels": [{k: v for k, v in l.items() if k not in ("source_sha256",)} for l in self.labels]}

    @property
    def semantic_sha256(self) -> str:
        return _h(stable_json(self.semantic()))


def _label_rows(case: Case, op: str, variant: dict, n: int) -> list[dict]:
    lab = variant["label"]
    anchors = [{**a, "locator": locate(case.text, a["quote"])} for a in lab["anchors"]]
    for a in anchors:
        check_anchor(case.text, a["quote"], f"{case.case_id}/{variant['variant']}")
    common = {"schema": LABEL_SCHEMA, "case_id": case.case_id, "family": case.family,
              "source_sha256": case.source_sha256, "visibility": "public"}
    if op == "paraphrase":
        return [{**common, "label_id": f"{case.case_id}#clean", "issue_type": None, "anchors": [],
                 "expected_outcome": "clean", "explanation": variant["effect"]},
                {**common, "label_id": f"{case.case_id}#control", "issue_type": None, "anchors": anchors,
                 "expected_outcome": "absent", "explanation": "Перефразированное место: находка здесь — ложная тревога."}]
    return [{**common, "label_id": f"{case.case_id}#{n}", "issue_type": OP_ISSUE_TYPE[op],
             "anchors": anchors, "anchor_policy": lab["anchor_policy"], "expected_outcome": "present",
             "severity": OP_SEVERITY[op], "criterion": OP_CRITERION[op], "scenario": lab.get("scenario"),
             "explanation": variant["effect"], "mutation": {"op": op, "variant": variant["variant"]}}]


def _finalize_labels(case: Case) -> None:
    sha = case.source_sha256
    for l in case.labels:
        l["source_sha256"] = sha


def build_base(fam: dict) -> Case:
    text = _tidy(fam["base"])
    case = Case(f"{fam['family']}.base", fam["family"], "base", text, None)
    case.labels = [{"schema": LABEL_SCHEMA, "label_id": f"{case.case_id}#clean", "case_id": case.case_id,
                    "family": fam["family"], "source_sha256": case.source_sha256, "issue_type": None,
                    "anchors": [], "expected_outcome": "clean", "visibility": "public",
                    "explanation": "Чистая базовая спецификация: любая находка — ложная тревога."}]
    case.effect = ["Без изменений (чистый контроль)."]
    return case


def build_mutant(fam: dict, base: Case, picks: list[tuple[str, dict]], kind: str) -> Case:
    text = base.text
    trans = []
    for op, variant in picks:
        for e in variant["edits"]:
            text, rec = apply_edit(text, e)
            trans.append({**rec, "mutation_op": op, "variant": variant["variant"]})
    if kind == "combo":
        cid = f"{fam['family']}.combo." + "+".join(f"{op}-{v['variant']}" for op, v in picks)
    else:
        op, v = picks[0]
        cid = f"{fam['family']}.{op}.{v['variant']}"
    case = Case(cid, fam["family"], kind, text, base.case_id, ops=[op for op, _ in picks],
                variants=[v["variant"] for _, v in picks], transformation=trans,
                effect=[v["effect"] for _, v in picks])
    n = 0
    for op, v in picks:
        n += 1
        case.labels.extend(_label_rows(case, op, v, n))
    _finalize_labels(case)
    if text == base.text:
        raise GenerationError(f"{cid}: мутация не изменила текст")
    return case


def build_empty() -> Case:
    case = Case("edge.empty", "edge", "edge", "", None, edge="empty")
    case.labels = [{"schema": LABEL_SCHEMA, "label_id": "edge.empty#clean", "case_id": case.case_id,
                    "family": "edge", "source_sha256": case.source_sha256, "issue_type": None, "anchors": [],
                    "expected_outcome": "clean", "visibility": "public",
                    "explanation": "Пустой файл (0 байт): находок с опорами быть не может, ожидается предупреждение."}]
    case.effect = ["Пустой документ."]
    return case


def generate_cases(seeds: list[int], all_variants: bool = False) -> list[Case]:
    cases: dict[str, Case] = {}

    def add(c: Case, seed: int | None) -> None:
        if c.case_id in cases:
            if cases[c.case_id].semantic_sha256 != c.semantic_sha256:
                raise GenerationError(f"{c.case_id}: одинаковый id, разное содержание")
            c = cases[c.case_id]
        else:
            cases[c.case_id] = c
        if seed is not None and seed not in c.seeds:
            c.seeds.append(seed)
            c.seeds.sort()

    for fam in FAMILIES:
        base = build_base(fam)
        add(base, None)
        for op in OPS:
            variants = fam["ops"][op]
            if all_variants:
                for v in variants:
                    add(build_mutant(fam, base, [(op, v)], "mutant"), None)
            for seed in seeds:
                v = variants[pick(seed, fam["family"], op, n=len(variants))]
                add(build_mutant(fam, base, [(op, v)], "mutant"), seed)
        for seed in seeds:
            chosen = {op: fam["ops"][op][pick(seed, fam["family"], op, n=len(fam["ops"][op]))] for op in DEFECT_OPS}
            pairs = sorted(combinations(DEFECT_OPS, 2),
                           key=lambda p: _h("|".join([GENERATOR_VERSION, str(seed), fam["family"], "combo", *p])))
            for a, b in pairs:
                try:
                    add(build_mutant(fam, base, [(a, chosen[a]), (b, chosen[b])], "combo"), seed)
                    break
                except GenerationError:
                    continue
            else:
                raise GenerationError(f"{fam['family']}: ни одна пара мутаций не совместима для seed={seed}")
    add(build_empty(), None)
    return [cases[k] for k in sorted(cases)]


def corpus_semantic_sha256(cases: list[Case], seeds: list[int], all_variants: bool) -> str:
    return _h(stable_json({"generator_version": GENERATOR_VERSION, "seeds": sorted(seeds),
                           "all_variants": all_variants,
                           "cases": [[c.case_id, c.semantic_sha256] for c in cases]}))


def unified_diff(base: str, new: str, cid: str) -> str:
    return "".join(difflib.unified_diff(base.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile="base/source.md", tofile=f"{cid}/source.md", n=1))


BINARY_KINDS = ("base", "combo", "edge")


def write_corpus(out_dir: str | Path, seeds: list[int], all_variants: bool = False,
                 formats: tuple[str, ...] = ("md", "pdf", "docx"),
                 binary_kinds: tuple[str, ...] = BINARY_KINDS) -> dict:
    """binary_kinds: для каких видов кейсов строить PDF/DOCX (по умолчанию база, комбинация, пустой).

    Форматы проверяют парсер и экспорт; одного представления на кейс достаточно для смысла,
    поэтому PDF/DOCX строятся для подмножества, а не для каждого мутанта.
    """
    from . import render  # отложенный импорт: reportlab/python-docx нужны только для PDF/DOCX

    out = Path(out_dir)
    cases = generate_cases(seeds, all_variants)
    by_id = {c.case_id: c for c in cases}
    (out / "cases").mkdir(parents=True, exist_ok=True)
    manifest_cases, label_rows = [], []
    for c in cases:
        d = out / "cases" / c.case_id
        d.mkdir(parents=True, exist_ok=True)
        md_path = d / "source.md"
        md_path.write_bytes(c.text.encode("utf-8"))
        all_quotes = [a["quote"] for l in c.labels for a in l["anchors"]]
        renders = [{"render_id": f"{c.case_id}@md", "format": "md", "path": f"cases/{c.case_id}/source.md",
                    "sha256": c.source_sha256, "bytes": len(c.text.encode("utf-8")),
                    "render_check": render.check_text(c.text, all_quotes, c.text)}]
        for fmt in formats:
            if fmt == "md" or c.kind not in binary_kinds:
                continue
            p = d / f"source.{fmt}"
            render.render(c.text, fmt, p, title=c.case_id)
            data = p.read_bytes()
            renders.append({"render_id": f"{c.case_id}@{fmt}", "format": fmt, "path": f"cases/{c.case_id}/source.{fmt}",
                            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                            "render_check": render.check_text(render.extract(p, fmt), all_quotes, c.text)})
        mutation = {
            "case_id": c.case_id, "family": c.family, "kind": c.kind, "ops": c.ops, "variants": c.variants,
            "seeds": c.seeds, "generator_version": GENERATOR_VERSION, "base_case_id": c.base_case_id,
            "base_source_sha256": by_id[c.base_case_id].source_sha256 if c.base_case_id else None,
            "source_sha256": c.source_sha256, "semantic_sha256": c.semantic_sha256,
            "transformation": c.transformation, "expected_effect": c.effect,
            "diff": unified_diff(by_id[c.base_case_id].text, c.text, c.case_id) if c.base_case_id else "",
            "labels": c.labels,
        }
        (d / "mutation.json").write_text(json.dumps(mutation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_cases.append({
            "case_id": c.case_id, "family": c.family, "kind": c.kind, "ops": c.ops, "variants": c.variants,
            "seeds": c.seeds, "base_case_id": c.base_case_id, "edge": c.edge,
            "expected_outcome": "defects" if any(l["expected_outcome"] == "present" for l in c.labels) else "clean",
            "n_defects": sum(1 for l in c.labels if l["expected_outcome"] == "present"),
            "semantic_sha256": c.semantic_sha256, "primary_render": "md", "renders": renders,
        })
        label_rows.extend(c.labels)
    manifest = {
        "schema": MANIFEST_SCHEMA, "generator_version": GENERATOR_VERSION, "seeds": sorted(seeds),
        "all_variants": all_variants, "visibility": "public", "formats": list(formats),
        "binary_kinds": list(binary_kinds),
        "corpus_semantic_sha256": corpus_semantic_sha256(cases, seeds, all_variants),
        "render_tools": render.tool_versions(),
        "note": "Открытый dev-корпус. Закрытые ответы сюда не добавляются; проверка — python -m evaluation.harness leakcheck.",
        "cases": manifest_cases,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(out / "labels.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for row in label_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return manifest
