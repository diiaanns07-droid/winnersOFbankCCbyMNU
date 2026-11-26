"""Перепроверка report.json v2 без модели (владелец №13).

    python -m bcc_review verify отчёт.json исходник        # код 0 — OK, 4 — расхождение
    python -m bcc_review.v2.verify отчёт.json исходник     # то же напрямую

Что проверяется:
1. report.json соответствует схеме ``contracts/v2.json``;
2. SHA-256 исходника совпадает с ``document.sha256``;
3. каждая цитата дефекта есть в исходнике на указанных строках (та же нормализация, что у сверки цитат);
4. счётчики ``summary`` сходятся с перечнями, ссылки на D-/R-/Q- существуют;
5. вердикт совпадает с правилом кода (CONTRACT.md, раздел 5);
6. коммит агента записан.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from .render import jsonout

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VERIFY_FAILED = 4
FUZZY_MIN = 0.92

# ---------------------------------------------------------------- нормализация (CONTRACT.md, раздел 7)

_QUOTES = dict.fromkeys(map(ord, "«»“”„‟\"'’‘‚`´"), '"')
_DASHES = dict.fromkeys(map(ord, "—–‑‒―−"), "-")
_SPACES = dict.fromkeys(map(ord, "            　"), " ")


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace("**", "").replace("`", "")
    s = s.translate(_SPACES).translate(_QUOTES).translate(_DASHES)
    s = re.sub(r"^\s*(?:#{1,6}\s+|[*+-]\s+)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


# ---------------------------------------------------------------- чтение исходника

def _md_line(raw: str) -> str:
    """Строка Markdown без разметки — как в DocView (CONTRACT.md, 2.1), если модуль №03 недоступен."""
    s = raw.rstrip("\n")
    st = s.strip()
    if st.startswith("|") and st.endswith("|") and len(st) > 1:
        cells = [c.strip() for c in st.strip("|").split("|")]
        s = " | ".join(cells)
    s = re.sub(r"^\s*#{1,6}\s+", "", s)
    s = re.sub(r"^\s*[*+-]\s+", "", s)
    return s.replace("**", "").replace("`", "")


def load_lines(source: Path) -> tuple[list[str], list]:
    """Текст строк документа (номер строки = индекс + 1) и страницы, если есть."""
    try:
        from . import docview  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — модуль №03 может ещё не существовать
        docview = None
    if docview is not None and hasattr(docview, "load"):
        view = docview.load(str(source))
        lines = view["lines"]
        return [ln.get("text", "") for ln in lines], [ln.get("page") for ln in lines]
    suffix = source.suffix.lower()
    if suffix not in (".md", ".markdown", ".txt"):
        raise ValueError(f"для формата {suffix} нужен модуль чтения документа (bcc_review.v2.docview)")
    raw = source.read_text(encoding="utf-8-sig").splitlines()
    text = [_md_line(r) for r in raw] if suffix != ".txt" else raw
    return text, [None] * len(text)


# ---------------------------------------------------------------- проверки

def _fuzzy_in(quote: str, text: str) -> float:
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return 0.0
    if q in t:
        return 1.0
    n = len(q)
    best = 0.0
    for i in range(0, max(1, len(t) - n + 1)):
        sm = difflib.SequenceMatcher(None, q, t[i:i + n])
        if sm.real_quick_ratio() < FUZZY_MIN or sm.quick_ratio() < FUZZY_MIN:
            continue
        best = max(best, sm.ratio())
        if best >= 0.999:
            break
    return best


def _where_else(quote: str, lines: list[str]) -> list[int]:
    q = normalize(quote)
    return [i + 1 for i, ln in enumerate(lines) if q and q in normalize(ln)][:3]


def check_quote(quote: str, line_start: int, line_end: int, lines: list[str], verified: str) -> str | None:
    """None — цитата на месте; иначе текст расхождения."""
    if line_start < 1 or line_end > len(lines) or line_end < line_start:
        return f"строки {line_start}–{line_end} вне документа (в нём {len(lines)} строк)"
    text = " ".join(lines[line_start - 1:line_end])
    if normalize(quote) in normalize(text):
        return None
    if verified == "fuzzy" and _fuzzy_in(quote, text) >= FUZZY_MIN:
        return None
    other = _where_else(quote, lines)
    hint = f"; найдена в строке {', '.join(map(str, other))}" if other else "; в документе не найдена"
    span = f"строке {line_start}" if line_start == line_end else f"строках {line_start}–{line_end}"
    return f"нет в {span}{hint}"


def _short(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def verify_report(report: dict | str | Path, source: str | Path) -> dict:
    """Результат: {"ok", "errors": [{"code", "where", "message"}], "warnings": [...], "counts": {...}}."""
    if not isinstance(report, dict):
        report = jsonout.read(report)
    src = Path(source)
    errors: list[dict] = []
    warnings: list[str] = []

    def err(code: str, where: str, message: str) -> None:
        errors.append({"code": code, "where": where, "message": message})

    # 1. схема
    if report.get("schema") != jsonout.SCHEMA_ID:
        err("schema", "schema", f"ожидалась схема {jsonout.SCHEMA_ID}, в файле «{report.get('schema')}»")
    for e in jsonout.validate(report)[:20]:
        err("schema", "report.json", e)

    doc = report.get("document", {})
    run = report.get("run", {})

    # 2. исходник
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if doc.get("sha256") != sha:
        err("sha256", "document.sha256",
            f"SHA-256 исходника {sha[:12]}… не совпадает с записанным {str(doc.get('sha256'))[:12]}…")
    if doc.get("file") and Path(doc["file"]).name != src.name:
        warnings.append(f"имя файла в отчёте «{doc['file']}», проверяется «{src.name}»")
    lines, _pages = load_lines(src)
    if doc.get("lines") not in (None, len(lines)):
        warnings.append(f"в отчёте {doc.get('lines')} строк документа, при чтении — {len(lines)}")

    # 3. цитаты
    checked = verified = 0
    for f in report.get("findings", []):
        for i, ev in enumerate(f.get("evidence", []), 1):
            if ev.get("verified", "missing") == "missing":
                warnings.append(f"{f.get('id')}: цитата №{i} помечена как несверенная")
                continue
            checked += 1
            ls = int(ev.get("line_start") or 0)
            le = int(ev.get("line_end") or ls)
            problem = check_quote(ev.get("quote", ""), ls, le, lines, ev.get("verified", ""))
            if problem:
                err("quote", f"{f.get('id')} цитата №{i}", f"«{_short(ev.get('quote', ''))}» {problem}")
            else:
                verified += 1
    req_ids = set()
    for r in report.get("requirements", []):
        req_ids.add(r.get("id"))
        q = r.get("quote", "")
        if q:
            problem = check_quote(q, int(r.get("line_start") or 0), int(r.get("line_end") or 0), lines, "fuzzy")
            if problem:
                warnings.append(f"{r.get('id')}: цитата нарезки «{_short(q)}» {problem}")

    # 4. счётчики и ссылки
    expected = jsonout.compute_summary(report)
    got = report.get("summary", {})
    for key in ("requirements", "requirements_without_findings", "quotes_verified"):
        if got.get(key) != expected[key]:
            err("summary", f"summary.{key}", f"записано {got.get(key)}, по перечням {expected[key]}")
    for sev in jsonout.SEVERITIES:
        if (got.get("findings") or {}).get(sev) != expected["findings"][sev]:
            err("summary", f"summary.findings.{sev}",
                f"записано {(got.get('findings') or {}).get(sev)}, по перечню {expected['findings'][sev]}")
    find_ids = [f.get("id") for f in report.get("findings", [])]
    dup = sorted({x for x in find_ids if find_ids.count(x) > 1})
    if dup:
        err("refs", "findings", f"повторяются ID дефектов: {', '.join(dup)}")
    known_f = set(find_ids)
    for f in report.get("findings", []):
        missing = [r for r in f.get("requirement_ids", []) if r not in req_ids]
        if missing:
            err("refs", f.get("id", "?"), f"ссылки на несуществующие требования: {', '.join(missing)}")
    holders = [("verdict.fix_first", report.get("verdict", {}).get("fix_first", []))]
    holders += [(q.get("id", "вопрос"), q.get("finding_ids", [])) for q in report.get("questions", [])]
    holders += [("чек-лист", c.get("finding_ids", [])) for c in report.get("checklist", [])]
    for where, ids in holders:
        missing = [x for x in ids if x not in known_f]
        if missing:
            err("refs", where, f"ссылки на несуществующие дефекты: {', '.join(missing)}")

    # 5. вердикт
    rule = jsonout.rule_verdict(report)
    verdict = report.get("verdict", {})
    for k in ("development", "testing"):
        if verdict.get(k) != rule[k]:
            err("verdict", f"verdict.{k}", f"записано «{verdict.get(k)}», по правилу кода «{rule[k]}»")

    # 6. коммит
    commit = str(run.get("commit") or "")
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        err("commit", "run.commit", f"коммит агента не записан или некорректен: «{commit}»")
    if run.get("dirty"):
        warnings.append("отчёт построен на рабочей копии с незакоммиченными изменениями")
    if run.get("status") != "complete":
        warnings.append(f"статус прогона: {run.get('status')}")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"quotes_checked": checked, "quotes_verified": verified,
                       "findings": len(find_ids), "requirements": len(req_ids)},
            "sha256": sha, "commit": commit}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review verify",
                                description="Перепроверка report.json без модели: исходник, цитаты, счётчики, "
                                            "вердикт, коммит. Код 0 — всё сходится, 4 — есть расхождения.")
    p.add_argument("report", help="report.json, записанный агентом")
    p.add_argument("source", help="исходный документ, по которому строился отчёт")
    p.add_argument("--json", action="store_true", help="вывести результат в JSON")
    args = p.parse_args(argv)
    try:
        result = verify_report(Path(args.report), Path(args.source))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify: не удалось прочитать вход: {exc}", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        c = result["counts"]
        print(f"verify: OK — исходник совпадает (SHA-256 {result['sha256'][:12]}…), цитат на своих строках "
              f"{c['quotes_verified']} из {c['quotes_checked']}, счётчики и вердикт сходятся, "
              f"коммит {result['commit']}")
        for w in result["warnings"][:10]:
            print(f"  ! {w}")
    else:
        print(f"verify: расхождений — {len(result['errors'])}", file=sys.stderr)
        for e in result["errors"][:50]:
            print(f"  - {e['where']}: {e['message']}", file=sys.stderr)
    return EXIT_OK if result["ok"] else EXIT_VERIFY_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
