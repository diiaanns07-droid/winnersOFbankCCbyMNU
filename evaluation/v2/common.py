"""Общие функции оценки: документ построчно, поиск цитат, приведение отчётов v1/v2 к одному виду."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

MD_DECOR = re.compile(r"\*\*|__|`")
_QUOTES = re.compile(r"[«»“”„\"'‘’]")
_DASHES = re.compile(r"[—–‑−]")
_SPACES = re.compile(r"\s+")
TOKEN = re.compile(r"[0-9a-zа-я₸$%+/.:-]+", re.I)


def norm(s: str) -> str:
    """Нормализация для сравнения цитат: NFKC, кавычки, тире, пробелы, без разметки, нижний регистр, ё → е."""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _QUOTES.sub('"', s)
    s = _DASHES.sub("-", s)
    s = MD_DECOR.sub("", s)
    s = s.replace("ё", "е").replace("Ё", "Е")
    return _SPACES.sub(" ", s).strip().lower()


def tokens(s: str) -> list[str]:
    return [t.strip(".:") for t in TOKEN.findall(norm(s)) if t.strip(".:")]


def md_line_text(raw: str) -> str:
    """Видимый текст строки Markdown, как в docview: без `**`, обратных кавычек, маркеров списка и заголовков."""
    t = MD_DECOR.sub("", raw).rstrip()
    t = re.sub(r"^\s*[*-]\s+", "", t)
    t = re.sub(r"^#+\s*", "", t)
    st = t.strip()
    if st.startswith("|") and st.endswith("|"):
        cells = [c.strip() for c in st.strip("|").split("|")]
        t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
    return t


def load_doc(path: str | Path) -> list[dict]:
    """Строки документа (1-based) с нормализованным текстом."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8-sig").splitlines()
    out = []
    for i, s in enumerate(raw, 1):
        t = md_line_text(s)
        out.append({"n": i, "text": t, "norm": norm(t)})
    return out


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locate(lines: list[dict], quote: str, hint: int | None = None) -> dict | None:
    """Найти цитату в документе: точное вхождение → склейка 2–3 строк → нечёткий отрезок токенов.

    Возвращает {"line_start", "line_end", "how": exact|joined|fuzzy}; при нескольких вхождениях —
    ближайшее к подсказке.
    """
    q = norm(quote)
    if len(q) < 3:
        return None
    hits = [x["n"] for x in lines if q in x["norm"]]
    if hits:
        n = min(hits, key=lambda k: abs(k - (hint or k)))
        return {"line_start": n, "line_end": n, "how": "exact"}
    for width in (2, 3):
        joined_hits = []
        for i in range(len(lines) - width + 1):
            win = lines[i:i + width]
            if q in " ".join(x["norm"] for x in win if x["norm"]):
                joined_hits.append((win[0]["n"], win[-1]["n"]))
        if joined_hits:
            a, b = min(joined_hits, key=lambda ab: abs(ab[0] - (hint or ab[0])))
            return {"line_start": a, "line_end": b, "how": "joined"}
    qt = tokens(q)
    if len(qt) < 3:
        return None
    best = (0, None)
    for x in lines:
        lt = tokens(x["norm"])
        run = _longest_run(qt, lt)
        if run > best[0] or (run == best[0] and best[1] is not None and hint
                             and abs(x["n"] - hint) < abs(best[1] - hint)):
            best = (run, x["n"])
    if best[1] is not None and best[0] >= max(3, int(0.8 * len(qt) + 0.999)):
        return {"line_start": best[1], "line_end": best[1], "how": "fuzzy"}
    return None


def _longest_run(a: list[str], b: list[str]) -> int:
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def parse_lines(spec: str) -> set[int]:
    """«38», «40,126», «165-171» → множество номеров строк."""
    out: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


# ─────────────────────── приведение отчётов к одному виду ───────────────────────

TEXT_FIELDS = ("title", "problem", "scenario", "impact", "recommendation", "question")


def load_report(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def report_version(rep: dict) -> str:
    if str(rep.get("schema", "")).startswith("bcc-review/2"):
        return "v2"
    if "schema_version" in rep:
        return "v1"
    return "v2" if "findings" in rep else "unknown"


def normalize_findings(rep: dict) -> list[dict]:
    """Замечания отчёта v1 или v2 → [{id, title, severity, kind, text, evidence:[{quote, line_start, line_end,
    verified}], sources, blocks, raw}]."""
    ver = report_version(rep)
    out = []
    for i, f in enumerate(rep.get("findings") or [], 1):
        if ver == "v1":
            text = " ".join(str(f.get(k) or "") for k in ("title", "impact", "recommendation", "blocked_decision"))
            w = f.get("witness") or {}
            if isinstance(w, dict):
                text += " " + " ".join(str(v) for v in w.values() if isinstance(v, str))
            evs = []
            for e in (f.get("evidence") or f.get("hints") or []):
                evs.append({"quote": e.get("quote", ""), "line_start": None, "line_end": None,
                            "verified": "" if f.get("anchor_status") != "supported" else "exact"})
            out.append({"id": f.get("id") or f"F-{i:03d}", "title": f.get("title", ""),
                        "severity": f.get("severity", ""), "kind": f.get("kind", ""), "text": text,
                        "evidence": evs, "sources": [f.get("source", "")], "blocks": f.get("blocks"),
                        "fields": {k: f.get(k, "") for k in ("title", "impact", "recommendation")}, "raw": f})
        else:
            text = " ".join(str(f.get(k) or "") for k in TEXT_FIELDS)
            evs = []
            for e in f.get("evidence") or []:
                ls = e.get("line_start", e.get("line"))
                evs.append({"quote": e.get("quote", ""), "line_start": ls, "line_end": e.get("line_end", ls),
                            "verified": e.get("verified", "")})
            out.append({"id": f.get("id") or f"D-{i:02d}", "title": f.get("title", ""),
                        "severity": f.get("severity", ""), "kind": f.get("kind", ""), "text": text,
                        "evidence": evs, "sources": list(f.get("sources") or ([f["source"]] if f.get("source") else [])),
                        "blocks": f.get("blocks"),
                        "fields": {k: f.get(k, "") for k in TEXT_FIELDS + ("rewrite",)}, "raw": f})
    return out


def normalize_candidates(cands: list[dict], stage: str) -> list[dict]:
    """Кандидаты этапов (линзы, набор, правила, rejected) → тот же вид, что у замечаний."""
    out = []
    for i, c in enumerate(cands or [], 1):
        if not isinstance(c, dict):
            continue
        text = " ".join(str(c.get(k) or "") for k in TEXT_FIELDS + ("reason",))
        evs = []
        for e in c.get("evidence") or []:
            if not isinstance(e, dict):
                continue
            ls = e.get("line_start", e.get("line"))
            evs.append({"quote": e.get("quote", ""), "line_start": ls, "line_end": e.get("line_end", ls),
                        "verified": e.get("verified", "")})
        src = c.get("source") or stage
        out.append({"id": c.get("id") or f"{stage}#{i}", "title": c.get("title", ""),
                    "severity": c.get("severity", ""), "kind": c.get("kind", ""), "text": text, "evidence": evs,
                    "sources": [src], "blocks": c.get("blocks"), "fields": {}, "raw": c,
                    "reason": c.get("reason", "") or c.get("reject_reason", "")})
    return out


# ─────────────────────── язык и «общие фразы» ───────────────────────

GENERIC_PHRASES = [
    r"недостаточно детализ", r"недостаточно подробн", r"недостаточно четк", r"рекомендуется уточнить",
    r"повысить качество", r"улучшить качество", r"требует доработки", r"требует дополнительной проработки",
    r"нуждается в доработке", r"нуждается в уточнении", r"необходимо доработать", r"следует доработать",
    r"может привести к проблемам", r"может вызвать проблемы", r"возможны проблемы", r"по возможности",
    r"при необходимости", r"и т\. ?д\.", r"и т\. ?п\.", r"и прочее", r"в целом", r"соответствующ\w+ образом",
    r"надлежащ\w+ образом", r"оптимальн\w+ образом", r"best practice", r"лучши\w+ практик",
]
_GENERIC_RE = [re.compile(p, re.I) for p in GENERIC_PHRASES]

LATIN_ALLOW = {
    "iso", "iec", "ieee", "rfc", "http", "https", "api", "rest", "json", "url", "uri", "ui", "ux", "sla", "bpmn",
    "kzt", "utc", "gmt", "get", "post", "put", "patch", "delete", "head", "pdf", "docx", "md", "html", "jira",
    "swagger", "openapi", "id", "ids", "sms", "push", "jwt", "bearer", "oauth", "tls", "pci", "dss", "gdpr",
    "asia", "almaty", "content", "type", "true", "false", "null", "ok", "error", "nfr", "crud", "csv", "uuid",
    "idempotency", "key", "sequence", "diagram", "query", "body", "header", "mandatory", "string", "integer",
    "boolean", "int", "bit", "db", "sql", "cvv", "pan", "otp", "pin", "kyc", "aml", "p95", "p99",
}
_LATIN_WORD = re.compile(r"(?<![A-Za-z0-9_$./-])[A-Za-z][A-Za-z]{2,}(?![A-Za-z0-9_])")


def generic_hits(text: str) -> list[str]:
    return [m.group(0) for r in _GENERIC_RE for m in [r.search(text or "")] if m]


def latin_words(text: str, allowed: set[str]) -> list[str]:
    out = []
    for m in _LATIN_WORD.finditer(text or ""):
        w = m.group(0)
        if w.lower() in LATIN_ALLOW or w.lower() in allowed:
            continue
        out.append(w)
    return out


def doc_latin_vocab(lines: list[dict]) -> set[str]:
    vocab: set[str] = set()
    for x in lines:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9_]*", x["text"]):
            vocab.add(w.lower())
            for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", w):
                vocab.add(part.lower())
    return vocab
