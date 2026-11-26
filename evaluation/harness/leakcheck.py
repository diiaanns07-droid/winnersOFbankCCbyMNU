"""Проверка, что закрытые ответы не попали в открытый dev-набор.

GPT Pro может не раскрывать закрытые метки: команда fingerprint строит только хеши
(SHA-256 исходных файлов, case_id, n-грамм цитат). leakcheck сравнивает их с dev-корпусом
и печатает лишь количества совпадений. Текст закрытых цитат не выводится.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .normalize import tokens
from .schema import read_jsonl

MIN_QUOTE_TOKENS = 5
SHINGLE = 8


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ngrams(toks: list[str], n: int) -> set[str]:
    return {_h(" ".join(toks[i:i + n])) for i in range(len(toks) - n + 1)} if len(toks) >= n else set()


def quote_hashes(quote: str) -> set[str]:
    t = tokens(quote)
    if len(t) < MIN_QUOTE_TOKENS:
        return set()
    return _ngrams(t, SHINGLE) if len(t) >= SHINGLE else {_h(" ".join(t))}


def fingerprint(labels_path: str, docs_dir: str | None = None) -> dict:
    rows = read_jsonl(labels_path)
    quotes: set[str] = set()
    for r in rows:
        for a in r.get("anchors") or []:
            q = a.get("quote") if isinstance(a, dict) else a
            if isinstance(q, str):
                quotes |= quote_hashes(q)
        for k in ("quote", "related_quote"):
            if isinstance(r.get(k), str):
                quotes |= quote_hashes(r[k])
    docs: set[str] = set()
    doc_sha: set[str] = {r["source_sha256"] for r in rows if isinstance(r.get("source_sha256"), str)}
    if docs_dir:
        for p in sorted(Path(docs_dir).rglob("*")):
            if p.is_file():
                doc_sha.add(hashlib.sha256(p.read_bytes()).hexdigest())
                if p.suffix.lower() in (".md", ".txt"):
                    docs |= _ngrams(tokens(p.read_text(encoding="utf-8", errors="replace")), SHINGLE)
    return {"schema": "bcc-eval-fingerprint/1", "quote_min_tokens": MIN_QUOTE_TOKENS, "shingle": SHINGLE,
            "source_sha256": sorted(doc_sha), "case_id_sha256": sorted({_h(r["case_id"]) for r in rows if "case_id" in r}),
            "quote_ngrams": sorted(quotes), "doc_shingles": sorted(docs)}


def dev_index(corpus_dir: str) -> dict:
    root = Path(corpus_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    shas, cids, grams, shingles = set(), set(), set(), set()
    for case in manifest["cases"]:
        cids.add(_h(case["case_id"]))
        for r in case["renders"]:
            shas.add(r["sha256"])
            if r["format"] in ("md", "txt"):
                toks = tokens((root / r["path"]).read_text(encoding="utf-8"))
                shingles |= _ngrams(toks, SHINGLE)
                for n in range(MIN_QUOTE_TOKENS, SHINGLE + 1):
                    grams |= _ngrams(toks, n)
    return {"source_sha256": shas, "case_id_sha256": cids, "ngrams": grams, "doc_shingles": shingles}


def leakcheck(corpus_dir: str, fp: dict, doc_overlap_warn: float = 0.05) -> dict:
    dev = dev_index(corpus_dir)
    sha_hits = len(dev["source_sha256"] & set(fp["source_sha256"]))
    cid_hits = len(dev["case_id_sha256"] & set(fp["case_id_sha256"]))
    quote_hits = len(dev["ngrams"] & set(fp["quote_ngrams"]))
    closed_docs = set(fp.get("doc_shingles") or [])
    doc_overlap = len(dev["doc_shingles"] & closed_docs) / len(closed_docs) if closed_docs else None
    leaked = bool(sha_hits or cid_hits or quote_hits)
    return {
        "schema": "bcc-eval-leakcheck/1", "leak": leaked,
        "source_sha256_overlap": sha_hits, "case_id_overlap": cid_hits, "closed_quote_ngrams_in_dev_text": quote_hits,
        "closed_doc_shingle_share_in_dev": None if doc_overlap is None else round(doc_overlap, 4),
        "doc_overlap_warning": doc_overlap is not None and doc_overlap > doc_overlap_warn,
        "note": "Выводятся только количества; закрытые тексты и цитаты не печатаются.",
    }
