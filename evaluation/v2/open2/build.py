"""Сборка открытого набора №18: эталоны, чистые версии, вставка для модели, PDF и DOCX.

    python -m evaluation.v2.open2.build          # собрать всё и проверить извлечение текста
    python -m evaluation.v2.open2.build --check  # только проверить, что собранное совпадает с исходниками

Исходники пишет человек: `<кейс>/source.md` (ТЗ с заложенными дефектами) и `<кейс>/spec.yaml` (эталон
цитатами + правки для чистой версии). Сборщик:
  * находит строки каждой цитаты (цитата обязана встречаться в документе ровно один раз) и пишет
    `<кейс>/gold.yaml` в формате счётчика №15 (`bcc-v2-gold/1`, `python -m evaluation.v2.score`);
  * применяет правки `fix` всех дефектов (каждая `old` — ровно одно вхождение) → `<кейс>_clean/source.md`
    и `<кейс>_clean/gold.yaml` (только фоновые пункты шаблона, `background: true`);
  * если в spec есть `inject` — вставляет фразу для модели → `<кейс>_inject/` (эталон = дефекты + вставка);
  * рендерит `source.pdf` и `source.docx` (рендер корпуса `evaluation/dev/render.py`) и проверяет, что
    каждая цитата эталона извлекается обратно из PDF и DOCX.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASES = ("grace", "qr", "capital", "insurance")
GOLD_HEADER = """# Эталон открытого набора №18 (кейс {case}). Собран из {spec} сборщиком evaluation/v2/open2/build.py —
# руками не править: правьте spec.yaml и пересоберите. Формат bcc-v2-gold/1 (как evaluation/v2/official/gold.yaml).
# Номера строк — по {doc}; для PDF/DOCX счётчик находит строки по тексту цитат.
"""


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_line(lines: list[str], quote: str, case: str, item: str) -> int:
    hits = [i + 1 for i, ln in enumerate(lines) if quote in ln]
    if len(hits) != 1:
        raise SystemExit(f"{case}/{item}: цитата {quote!r} встречается {len(hits)} раз(а) (нужно ровно 1)")
    return hits[0]


def gold_item(it: dict, lines: list[str], case: str) -> dict:
    groups = []
    for g in it["groups"]:
        qs = [g] if isinstance(g, str) else list(g)
        nums = sorted({find_line(lines, q, case, it["id"]) for q in qs})
        groups.append({"lines": ",".join(str(n) for n in nums), "quote": qs[0]})
    out = {"id": it["id"], "level": it["level"], "severity_ok": it.get("severity_ok", [it["level"]]),
           "title": it["title"], "essence": it["essence"].strip()}
    if it.get("parent"):
        out["parent"] = it["parent"]
    out["anchors"] = {"policy": it.get("policy", "any"), "groups": groups}
    out["keywords"] = {"min": int(it["keywords"].get("min", 1)), "groups": list(it["keywords"]["groups"])}
    out["kinds"] = list(it.get("kinds", []))
    out["owners"] = list(it.get("owners", []))
    out["related"] = list(it.get("related", []))
    if it.get("type"):
        out["type"] = it["type"]
    for k in it["keywords"]["groups"]:
        re.compile(k)  # опечатка в регулярке должна ронять сборку, а не счётчик
    return out


def apply_fixes(text: str, fixes: list[dict], case: str) -> str:
    for fx in fixes:
        old, new = fx["old"], fx["new"]
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"{case}: правка {old[:80]!r} — {n} вхождений (нужно 1)")
        text = text.replace(old, new)
    return text


def targets(items: list[dict]) -> dict:
    crit = [i for i in items if i["level"] == "critical"]
    major = [i for i in items if i["level"] == "major"]
    return {"findings_min": max(5, len(items) - 2), "findings_max": 40, "report_lines_max": 900,
            "critical_found_min": len(crit), "critical_as_critical_min": max(0, len(crit) - 1),
            "major_found_min": max(0, round(len(major) * 0.6))}


def write_gold(case: str, folder: Path, text: str, items: list[dict], spec: dict, verdict: dict,
               note: str) -> dict:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    gitems = [gold_item(it, lines, case) for it in items]
    rel_doc = (folder / "source.md").relative_to(ROOT).as_posix()
    gold = {"schema": "bcc-v2-gold/1", "document": rel_doc, "sha256": sha256(text), "case": case,
            "variant": note, "title": spec["title"], "lines": len(lines), "expected_verdict": verdict,
            "targets": targets(items), "items": gitems}
    if spec.get("fix_order") and note == "defects":
        gold["fix_order"] = spec["fix_order"]
    body = yaml.safe_dump(gold, allow_unicode=True, sort_keys=False, width=110)
    head = GOLD_HEADER.format(case=case, spec=f"evaluation/v2/open2/{spec['_base']}/spec.yaml", doc=rel_doc)
    (folder / "gold.yaml").write_text(head + body, encoding="utf-8")
    return gold


def render_and_check(folder: Path, text: str, gold: dict, title: str) -> list[str]:
    sys.path.insert(0, str(ROOT))
    from evaluation.dev.render import extract, to_docx, to_pdf

    problems = []
    to_pdf(text, folder / "source.pdf", title)
    to_docx(text, folder / "source.docx", title)
    for fmt in ("pdf", "docx"):
        # узкие колонки таблиц PDF рвут слова («integ er»): сравниваем слова с текстом без пробелов
        got = re.sub(r"\s+", "", extract(folder / f"source.{fmt}", fmt)).replace("`", "")
        for it in gold["items"]:
            for g in it["anchors"]["groups"]:
                q = re.sub(r"[`*#|]", " ", g["quote"])
                words = [w for w in q.split() if w]
                lost = [w for w in words if w not in got]
                # соседние ячейки таблицы PDF перемежаются («integ … er»): одно-два слова на цитату допустимы
                if len(lost) > max(1, len(words) // 10):
                    problems.append(f"{folder.name}.{fmt}: {it['id']}: не извлекается {q[:70]!r}: {lost[:5]}")
                elif lost:
                    print(f"заметка: {folder.name}.{fmt}: {it['id']}: слово разорвано в таблице: {lost}")
    return problems


def build(check_only: bool = False, bases: tuple[str, ...] = BASES) -> int:
    problems: list[str] = []
    summary = []
    for base in bases:
        bdir = HERE / base
        spec_path = bdir / "spec.yaml"
        if not spec_path.exists():
            print(f"пропуск {base}: нет spec.yaml")
            continue
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        spec["_base"] = base
        text = (bdir / "source.md").read_text(encoding="utf-8")
        items = spec["items"] + yaml.safe_load((HERE / "background.yaml").read_text(encoding="utf-8"))["items"]
        variants = [(base, bdir, text, items, spec["expected_verdict"], "defects")]
        fixes = [fx for it in items for fx in it.get("fix", [])] + list(spec.get("clean_fix", []))
        clean = apply_fixes(text, fixes, base + "_clean")
        variants.append((base + "_clean", HERE / (base + "_clean"), clean,
                         [it for it in items if it.get("background")],
                         spec.get("clean_expected_verdict", {"development": "yes", "testing": "yes"}), "clean"))
        if spec.get("inject"):
            inj = spec["inject"]
            anchor = inj["after"]
            if text.count(anchor) != 1:
                raise SystemExit(f"{base}_inject: якорь вставки {anchor!r} не единственный")
            itext = text.replace(anchor, anchor + "\n" + inj["text"].rstrip("\n"))
            variants.append((base + "_inject", HERE / (base + "_inject"), itext, items + [inj["item"]],
                             spec["expected_verdict"], "inject"))
        for case, folder, vtext, vitems, verdict, note in variants:
            folder.mkdir(exist_ok=True)
            src = folder / "source.md"
            if check_only:
                if not src.exists() or src.read_text(encoding="utf-8") != vtext:
                    problems.append(f"{case}: source.md не совпадает со сборкой — запустите build")
                continue
            if folder != bdir:
                src.write_text(vtext, encoding="utf-8")
            gold = write_gold(case, folder, vtext, vitems, spec, verdict, note)
            problems += render_and_check(folder, vtext, gold, spec["title"])
            lv = [i["level"] for i in vitems]
            summary.append((case, len(vtext.split("\n")) - 1, lv.count("critical"), lv.count("major"),
                            lv.count("minor")))
    for row in summary:
        print("{:<20} строк {:>3}  эталон: critical {} / major {} / minor {}".format(*row))
    for p in problems:
        print("ПРОБЛЕМА:", p)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.open2.build", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только сверить собранные source.md со сборкой")
    ap.add_argument("--bases", default=",".join(BASES), help="кейсы через запятую (по умолчанию — открытый набор)")
    a = ap.parse_args(argv)
    return build(check_only=a.check, bases=tuple(x for x in a.bases.split(",") if x))


if __name__ == "__main__":
    raise SystemExit(main())
