"""№03, вторая волна: цитаты эталонов на своих строках во всех трёх форматах, без чужих вхождений.

Берутся все эталоны формата bcc-v2-gold/1: официальный (`evaluation/v2/official/gold.yaml`) и новые ТЗ №18
(`evaluation/v2/open2/<кейс>/gold.yaml` + `source.md`, `source.pdf`, `source.docx`). Для каждой группы опор с цитатой:

* MD: цитата находится на строках группы (подсказка — первая строка группы); если фраза встречается в документе
  несколько раз, выбрано вхождение группы, а не чужое;
* PDF и DOCX: место строки MD находится в другом формате (k-е вхождение той же строки), цитата находится там же,
  раздел совпадает (верхние два уровня).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
yaml = pytest.importorskip("yaml")


def _parse_lines(spec) -> list[int]:
    out: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def _cases() -> list[tuple[str, Path, Path]]:
    cases = [("official", ROOT / "evaluation/v2/official/gold.yaml", ROOT / "release/input/requirements.md")]
    for g in sorted((ROOT / "evaluation/v2/open2").glob("*/gold.yaml")):
        src = g.parent / "source.md"
        if src.exists():
            cases.append((g.parent.name, g, src))
    return [c for c in cases if c[1].exists() and c[2].exists()]


CASES = _cases()


def _groups(gold_path: Path) -> list[tuple[str, list[int], str]]:
    g = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    out = []
    for it in g.get("items") or []:
        for gr in (it.get("anchors") or {}).get("groups") or []:
            q = str(gr.get("quote") or "").strip()
            if q and gr.get("lines"):
                out.append((str(it.get("id")), _parse_lines(gr["lines"]), q))
    return out


def _find_prefix(view: dict, text: str, hint: int | None, near=()) -> dict | None:
    """Цитата целиком, иначе самое длинное её начало (≥ 60 % слов): исходный PDF может обрезать строку кода."""
    m = Q.verify_quote(view, text, hint, near)
    if m:
        return m
    words = text.split()
    for k in range(len(words) - 1, max(2, int(len(words) * 0.6)) - 1, -1):
        m = Q.verify_quote(view, " ".join(words[:k]), hint, near)
        if m:
            m["verified"] = "prefix"
            return m
    return None


def _locate(other: dict, md: dict, lines: list[int]) -> tuple[int, int] | None:
    """Где строки MD (группа) в другом формате: k-е вхождение той же строки, иначе ближайшее по доле документа."""
    found = []
    for n in lines:
        ln = dv.line(md, n)
        if not ln or not ln["text"].strip():
            continue
        key = Q.normalize(ln["text"])
        k = sum(1 for x in md["lines"][: n - 1] if Q.normalize(x["text"]) == key)
        same = [x["n"] for x in other["lines"] if key and key in Q.normalize(x["text"])]
        if len(same) > k:
            found.append(same[k])
            continue
        hint = max(1, round(n / max(1, len(md["lines"])) * len(other["lines"])))
        m = _find_prefix(other, ln["text"], hint)
        if m:
            found += [m["line_start"], m["line_end"]]
    return (min(found), max(found)) if found else None


@pytest.mark.parametrize("name,gold,src", CASES, ids=[c[0] for c in CASES])
def test_gold_quotes_in_md(name, gold, src):
    md = dv.load(src)
    groups = _groups(gold)
    assert groups, f"{name}: в эталоне нет цитат"
    bad = []
    for item, lines, quote in groups:
        m = Q.verify_quote(md, quote, lines[0], [(lines[0], lines[-1])])
        if not m or not (m["line_start"] <= lines[-1] and m["line_end"] >= lines[0]):
            bad.append((item, lines, quote[:60], m and (m["line_start"], m["line_end"])))
            continue
        # без чужих вхождений: если фраза повторяется, подсказка выбирает своё, а не первое вхождение
        others = [x["n"] for x in md["lines"] if Q.normalize(quote).strip(" .") in Q.normalize(x["text"])
                  and not lines[0] <= x["n"] <= lines[-1]]
        if others:
            m2 = Q.verify_quote(md, quote, lines[-1])
            if not (m2 and lines[0] <= m2["line_start"] <= lines[-1]):
                bad.append((item, lines, quote[:60], "чужое вхождение", others[:3]))
    assert not bad, bad


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
@pytest.mark.parametrize("name,gold,src", CASES, ids=[c[0] for c in CASES])
def test_gold_quotes_in_pdf_docx(name, gold, src, fmt):
    other_path = src.with_suffix(f".{fmt}")
    if not other_path.exists():
        pytest.skip(f"{name}: нет {other_path.name}")
    pytest.importorskip("pymupdf" if fmt == "pdf" else "docx")
    md = dv.load(src)
    other = dv.load(other_path)
    bad = []
    for item, lines, quote in _groups(gold):
        mm = Q.verify_quote(md, quote, lines[0], [(lines[0], lines[-1])])
        loc = _locate(other, md, lines)
        if not mm or not loc:
            bad.append((item, lines, "место строки не найдено в " + fmt))
            continue
        m = _find_prefix(other, quote, loc[0], [loc])
        if not m or not (m["line_start"] <= loc[1] + 1 and m["line_end"] >= loc[0] - 1):
            bad.append((item, lines, quote[:60], loc, m and (m["line_start"], m["line_end"])))
            continue
        a, b = mm["section"].split(" › ")[:2], m["section"].split(" › ")[:2]
        if a != b and not (re.sub(r"\W", "", "".join(a)) == re.sub(r"\W", "", "".join(b))):
            bad.append((item, lines, "раздел", mm["section"], m["section"]))
        if fmt == "pdf" and not m["page"]:
            bad.append((item, lines, "нет страницы"))
    assert not bad, bad
