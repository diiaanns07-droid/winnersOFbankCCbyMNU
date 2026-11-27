"""Сборка набора действительно чистых ТЗ №20: эталон, PDF и DOCX, проверка извлечения текста.

    python -m evaluation.v2.clean.build          # собрать gold.yaml, source.pdf, source.docx во всех кейсах
    python -m evaluation.v2.clean.build --check  # только проверить, что собранное совпадает с source.md

Исходник каждого кейса пишет человек: `evaluation/v2/clean/<кейс>/source.md` — ТЗ без дефектов (часть A + REST API,
шаблон официального документа, все поля шаблона заполнены). Сборщик:
  * пишет `<кейс>/gold.yaml` в формате счётчика №15 (`bcc-v2-gold/1`, как у чистых версий №18) с пустым эталоном:
    `items: []` — любое замечание агента на этом документе — ложная тревога;
  * рендерит `source.pdf` и `source.docx` рендером корпуса (`evaluation/dev/render.py`) и проверяет, что текст
    извлекается обратно: каждое функциональное требование и ≥ 98 % слов документа.
Кейсы `<кейс>_v2` — вторая редакция чистых версий открытого набора №18 (`evaluation/v2/open2/<кейс>_clean`):
исправлены оставшиеся настоящие дефекты и заполнены поля шаблона. Остальные кейсы — новые домены.
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
GOLD_HEADER = """# Эталон набора действительно чистых ТЗ №20 (кейс {case}). Собран сборщиком evaluation/v2/clean/build.py —
# руками не править: правьте source.md и пересоберите. Формат bcc-v2-gold/1 (как чистые версии №18 в open2).
# Эталон пустой: документ без дефектов, любое замечание агента — ложная тревога.
"""
# Заглушки шаблона, которых в действительно чистом документе быть не должно
PLACEHOLDERS = (r"заполняются тестировщиками", r"Да / Нет", r"в источнике не заполнен", r"\bTBD\b", r"<уточнить",
                r"\|\s*\|\s*\|\s*\|\s*$")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_lines(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def title_of(text: str) -> str:
    for ln in text.split("\n"):
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def cases(root: Path = HERE) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "source.md").is_file())


def placeholder_hits(text: str) -> list[str]:
    hits = []
    for n, ln in enumerate(doc_lines(text), 1):
        for pat in PLACEHOLDERS:
            if re.search(pat, ln):
                hits.append(f"строка {n}: {ln.strip()[:80]}")
    return hits


def gold_for(folder: Path, text: str) -> dict:
    rel_doc = (folder / "source.md").relative_to(ROOT).as_posix()
    base = folder.name[:-3] if folder.name.endswith("_v2") else ""
    gold = {"schema": "bcc-v2-gold/1", "document": rel_doc, "sha256": sha256(text), "case": folder.name,
            "variant": "clean", "title": title_of(text), "lines": len(doc_lines(text)),
            "expected_verdict": {"development": "yes", "testing": "yes"},
            "targets": {"findings_min": 0, "findings_max": 1, "report_lines_max": 900, "critical_found_min": 0,
                        "critical_as_critical_min": 0, "major_found_min": 0},
            "items": []}
    if base:
        gold["derived_from"] = f"evaluation/v2/open2/{base}_clean/source.md"
    return gold


def write_gold(folder: Path, text: str) -> dict:
    gold = gold_for(folder, text)
    body = yaml.safe_dump(gold, allow_unicode=True, sort_keys=False, width=110)
    (folder / "gold.yaml").write_text(GOLD_HEADER.format(case=folder.name) + body, encoding="utf-8", newline="\n")
    return gold


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", re.sub(r"[`*#|]", " ", text)) if w]


def check_extraction(folder: Path, text: str) -> list[str]:
    """Каждое функциональное требование «Ф-N» и ≥ 98 % слов документа извлекаются из PDF и DOCX."""
    sys.path.insert(0, str(ROOT))
    from evaluation.dev.render import extract

    reqs = [ln for ln in doc_lines(text) if re.match(r"\*\s+\*\*Ф-\d+", ln.strip())]
    words = set(_words(text))
    problems = []
    for fmt in ("pdf", "docx"):
        path = folder / f"source.{fmt}"
        if not path.is_file():
            problems.append(f"{folder.name}: нет source.{fmt}")
            continue
        # узкие колонки таблиц PDF рвут слова: сравниваем слова с текстом без пробелов (как сборщик №18)
        got = re.sub(r"\s+", "", extract(path, fmt)).replace("`", "")
        for r in reqs:
            ws = _words(r)
            lost = [w for w in ws if w not in got]
            if len(lost) > max(1, len(ws) // 10):
                problems.append(f"{folder.name}.{fmt}: не извлекается {r.strip()[:70]!r}: {lost[:5]}")
        lost_all = [w for w in words if w not in got]
        if words and len(lost_all) / len(words) > 0.02:
            problems.append(f"{folder.name}.{fmt}: не извлекается {len(lost_all)} из {len(words)} слов: {lost_all[:8]}")
    return problems


def build(check_only: bool = False) -> int:
    sys.path.insert(0, str(ROOT))
    problems: list[str] = []
    for folder in cases():
        text = (folder / "source.md").read_text(encoding="utf-8")
        problems += [f"{folder.name}: заглушка шаблона — {h}" for h in placeholder_hits(text)]
        if check_only:
            gp = folder / "gold.yaml"
            if not gp.is_file():
                problems.append(f"{folder.name}: нет gold.yaml")
                continue
            gold = yaml.safe_load(gp.read_text(encoding="utf-8"))
            if gold != gold_for(folder, text):
                problems.append(f"{folder.name}: gold.yaml не совпадает с source.md (пересоберите)")
        else:
            from evaluation.dev.render import to_docx, to_pdf
            write_gold(folder, text)
            to_pdf(text, folder / "source.pdf", title_of(text))
            to_docx(text, folder / "source.docx", title_of(text))
        problems += check_extraction(folder, text)
        print(f"{folder.name}: {len(doc_lines(text))} строк, «{title_of(text)}»")
    for p in problems:
        print("ПРОБЛЕМА:", p)
    print(f"кейсов: {len(cases())}, проблем: {len(problems)}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.v2.clean.build", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только проверить собранное")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    return build(check_only=a.check)


if __name__ == "__main__":
    raise SystemExit(main())
