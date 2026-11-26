"""Общие проверки для тестов №14: поиск слов, сравнение прямоугольников, выбор аннотаций."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from bcc_review.exports.pdf import NM_PREFIX


def phrase_rects(pdf: Path, page: int, phrase: str, nth: int = 0) -> list[pymupdf.Rect]:
    """Прямоугольники фразы на странице (1-based), по строкам, в неповёрнутых координатах."""
    toks = phrase.split()
    with pymupdf.open(pdf) as d:
        words = d[page - 1].get_text("words")
    hits = []
    for i in range(len(words) - len(toks) + 1):
        if [w[4] for w in words[i : i + len(toks)]] == toks:
            hits.append(words[i : i + len(toks)])
    seq = hits[nth]
    lines: dict[tuple[int, int], pymupdf.Rect] = {}
    for w in seq:
        key = (w[5], w[6])
        r = pymupdf.Rect(w[:4])
        lines[key] = lines[key] | r if key in lines else r
    return list(lines.values())


def close(a: Any, b: Any, tol: float = 0.75) -> bool:
    return max(abs(x - y) for x, y in zip(pymupdf.Rect(a), pymupdf.Rect(b))) <= tol


def by_finding(annots: list[dict[str, Any]], fid: str, kind: str | None = "Highlight") -> list[dict[str, Any]]:
    return [
        a
        for a in annots
        if a.get("name", "").startswith(f"{NM_PREFIX}{fid}:") and (kind is None or a["type"] == kind)
    ]
