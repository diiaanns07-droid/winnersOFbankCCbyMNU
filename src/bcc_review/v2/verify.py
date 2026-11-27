"""Перепроверка report.json v2 без модели (владелец №13).

    python -m bcc_review verify отчёт.json исходник        # код 0 — OK, 4 — расхождение
    python -m bcc_review.v2.verify отчёт.json исходник     # то же напрямую

Что проверяется:
1. report.json соответствует схеме ``contracts/v2.json``;
2. SHA-256 исходника совпадает с ``document.sha256``;
3. каждая цитата дефекта есть в исходнике на указанных строках (та же нормализация, что у сверки цитат);
4. счётчики ``summary`` сходятся с перечнями, ссылки на D-/R-/Q- существуют;
5. вердикт совпадает с правилом кода (CONTRACT.md, раздел 5);
6. коммит агента записан;
7. Markdown-отчёт рядом (тот же путь с ``.md``) говорит те же числа, что JSON: дефекты по серьёзности на первом
   экране и в сводке, по карточке или строке таблицы на каждый открытый дефект, блокеры, вопросы, цитаты.
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


_MD_COUNTS = re.compile(r"\*\*(\d+)\*\* дефект\w*: 🔴 \*\*(\d+)\*\* \w+ · 🟠 \*\*(\d+)\*\* \w+ · 🟡 \*\*(\d+)\*\*")
_MD_SUMMARY = re.compile(r"\| (\d+): 🔴 (\d+) · 🟠 (\d+) · 🟡 (\d+) \|")


def check_markdown(report: dict, md: str) -> tuple[list[str], list[str]]:
    """Сверка чисел Markdown-отчёта с report.json: (ошибки, предупреждения)."""
    errors: list[str] = []
    if 'id="s0"' not in md:
        return [], ["Markdown-отчёт не в формате агента v2 — числа в нём не сверялись"]
    s = jsonout.compute_summary(report)
    fs = s["findings"]
    want = [sum(fs.values()), fs["critical"], fs["major"], fs["minor"]]
    a, b = md.find('id="s0"'), md.find('id="s1"')
    brief = md[a:b] if b > a else md
    m = _MD_COUNTS.search(brief)
    if not m or [int(x) for x in m.groups()] != want:
        errors.append(f"«Кратко»: дефектов {list(m.groups()) if m else 'не найдено'}, в JSON {want}")
    m = _MD_SUMMARY.search(md[md.find('id="s5"'):md.find('id="s6"')] if 'id="s5"' in md else md)
    if not m or [int(x) for x in m.groups()] != want:
        errors.append(f"«Сводка»: дефектов {list(m.groups()) if m else 'не найдено'}, в JSON {want}")
    open_ids = {f.get("id") for f in jsonout.open_findings(report)}
    anchors = re.findall(r'<a id="(d-\d+)"></a>', md)
    shown = {x.upper() for x in anchors}
    if shown != {str(i).upper() for i in open_ids}:
        miss = sorted({str(i).upper() for i in open_ids} - shown)
        extra = sorted(shown - {str(i).upper() for i in open_ids})
        errors.append("дефекты в Markdown и JSON различаются" + (f": нет карточки у {', '.join(miss[:5])}" if miss else "")
                      + (f"; лишние {', '.join(extra[:5])}" if extra else ""))
    dup = sorted({x for x in anchors if anchors.count(x) > 1})
    if dup:
        errors.append(f"дефект показан дважды: {', '.join(dup[:5]).upper()}")
    qn = len(report.get("questions") or [])
    qa = len(set(re.findall(r'<a id="(q-\d+)"></a>', md)))
    if qn and qa != qn:
        errors.append(f"вопросов владельцу в приложении А {qa}, в JSON {qn}")
    ok, total = s["quotes_verified"], s["quotes_total"]
    if total and f"{ok} из {total}" not in md and f"все {total} цитат" not in md:
        errors.append(f"число сверенных цитат ({ok} из {total}) в Markdown не указано")
    errors += _check_markdown_more(report, md, brief, s)
    return errors, []


def _section(md: str, a: str, b: str | None) -> str:
    i = md.find(f'id="{a}"')
    if i < 0:
        return ""
    j = md.find(f'id="{b}"', i) if b else -1
    return md[i:j] if j > i else md[i:]


def _check_markdown_more(report: dict, md: str, brief: str, s: dict) -> list[str]:
    """Вердикт, блокеры, требования и кандидаты — одни и те же в «Кратко», сводке, итоге, приложении Д и JSON."""
    from .render import markdown as M

    errors: list[str] = []
    v = report.get("verdict") or {}
    want = [M.READINESS.get(v.get(k), "—") for k in ("development", "testing")]
    m = re.search(r"\| \*\*(.+?)\*\* \| \*\*(.+?)\*\* \|", brief)
    if m and list(m.groups()) != want:
        errors.append(f"«Кратко»: вердикт {list(m.groups())}, в JSON {want}")
    final = _section(md, "s6", "pa")
    got = re.findall(r"^\| (?:разработку|тестирование) \| \*\*(.+?)\*\* \|", final, re.M)
    if got and got != want:
        errors.append(f"«Итог»: вердикт {got}, в JSON {want}")
    try:
        ctx = M._Ctx(M._clean_report(report))
        n_block = len(M._blockers(ctx))
    except Exception:  # noqa: BLE001 — сверка не должна падать на неполном отчёте
        n_block = None
    m = re.search(r"\*\*Блокер(?:ы \((\d+)\))?\*\*", brief)
    if n_block is not None and m and (int(m.group(1)) if m.group(1) else 1) != n_block:
        errors.append(f"«Кратко»: блокеров {m.group(1) or 1}, по дефектам JSON {n_block}")
    if n_block and not m:
        errors.append(f"«Кратко»: блокеров по JSON {n_block}, а списка блокеров нет")
    summ = _section(md, "s5", "s6")
    for label, key in (("Требований выделено", "requirements"), ("Без замечаний", "requirements_without_findings")):
        m = re.search(rf"^\| {label} \| (\d[\d\s ]*) \|", summ, re.M)
        if m and int(re.sub(r"\D", "", m.group(1))) != s.get(key):
            errors.append(f"«Сводка»: «{label}» {m.group(1).strip()}, в JSON {s.get(key)}")
    m1 = re.search(r"найдено ([\d  ]+) возможн\w+ дефект", brief)
    m2 = re.search(r"Кандидатов в дефекты: ([\d  ]+)", _section(md, "pd", "pe"))
    if m1 and m2 and re.sub(r"\D", "", m1.group(1)) != re.sub(r"\D", "", m2.group(1)):
        errors.append(f"«Как получено»: возможных дефектов {m1.group(1)}, в приложении Д {m2.group(1)}")
    return errors


def verify_report(report: dict | str | Path, source: str | Path, *, markdown: str | Path | None = None) -> dict:
    """Результат: {"ok", "errors": [{"code", "where", "message"}], "warnings": [...], "counts": {...}}.

    ``markdown`` — путь или текст Markdown-отчёта; если не задан, а ``report`` — путь, берётся файл рядом (``.md``)."""
    if markdown is None and not isinstance(report, dict):
        cand = Path(report).with_suffix(".md")
        markdown = cand if cand.is_file() else None
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
    if run.get("status") == "failed" and not doc.get("sha256"):
        warnings.append("прогон завершился сбоем, документ не был прочитан — SHA-256 в отчёте не записан")
    elif doc.get("sha256") != sha:
        err("sha256", "document.sha256",
            f"SHA-256 исходника {sha[:12]}… не совпадает с записанным {str(doc.get('sha256'))[:12]}…")
    if doc.get("file") and Path(doc["file"]).name != src.name:
        warnings.append(f"имя файла в отчёте «{doc['file']}», проверяется «{src.name}»")
    try:
        lines, pages = load_lines(src)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        if run.get("status") != "failed" or jsonout.open_findings(report):
            raise
        # отчёт о сбое на нечитаемом входе: утверждений о документе в нём нет — сверять нечего
        warnings.append(f"документ не читается ({exc}); отчёт сообщает о сбое и не содержит цитат")
        lines, pages = [], []
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
            if not problem and ev.get("page") and 0 < ls <= len(pages) and pages[ls - 1] \
                    and int(ev["page"]) != int(pages[ls - 1]):
                problem = f"указана страница {ev['page']}, а строка {ls} на странице {pages[ls - 1]}"
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
    commit = str(run.get("commit") or "").strip()
    if commit.lower() in ("", "unknown", "none", "—"):
        # запуск из архива без .git (№16): версия есть, коммита нет — это не порча отчёта
        warnings.append(f"коммит агента не записан (запуск не из git-клона); версия агента: "
                        f"{run.get('version') or 'не указана'}")
    elif not re.fullmatch(r"[0-9a-f]{7,40}|v?\d+(?:\.\d+){1,3}(?:[-+.][\w.]+)?", commit):
        err("commit", "run.commit", f"коммит агента некорректен: «{commit}»")
    if run.get("dirty"):
        warnings.append("отчёт построен на рабочей копии с незакоммиченными изменениями")
    if run.get("status") != "complete":
        warnings.append(f"статус прогона: {run.get('status')}")

    # 7. Markdown-отчёт говорит те же числа
    md_checked = False
    if markdown is not None:
        md_text = Path(markdown).read_text(encoding="utf-8") if isinstance(markdown, Path) else str(markdown)
        md_errors, md_warn = check_markdown(report, md_text)
        for e in md_errors:
            err("markdown", "отчёт .md", e)
        warnings += md_warn
        md_checked = not md_warn

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"quotes_checked": checked, "quotes_verified": verified,
                       "findings": len(find_ids), "requirements": len(req_ids)},
            "sha256": sha, "commit": commit, "markdown_checked": md_checked}


def handles(report_path: str | Path) -> bool:
    """True, если файл — report.json ядра v2 (для выбора verify v1/v2 в общем CLI)."""
    try:
        head = Path(report_path).read_text(encoding="utf-8")[:4000]
    except (OSError, UnicodeDecodeError):
        return False
    return '"schema": "bcc-review/2"' in head or '"schema":"bcc-review/2"' in head


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    p = argparse.ArgumentParser(prog="python -m bcc_review verify",
                                description="Перепроверка report.json без модели: исходник, цитаты, счётчики, "
                                            "вердикт, коммит. Код 0 — всё сходится, 4 — есть расхождения.")
    p.add_argument("report", help="report.json, записанный агентом")
    p.add_argument("source", help="исходный документ, по которому строился отчёт")
    p.add_argument("--json", action="store_true", help="вывести результат в JSON")
    args = p.parse_args(argv)
    try:
        result = verify_report(Path(args.report), Path(args.source))
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"verify: не удалось прочитать вход: {exc}", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    except (TypeError, AttributeError, KeyError) as exc:
        print(f"verify: report.json повреждён или не по схеме bcc-review/2 ({type(exc).__name__}: {exc})",
              file=sys.stderr)
        return EXIT_VERIFY_FAILED
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"] and any(w.startswith("прогон завершился сбоем") for w in result["warnings"]):
        print("verify: OK — отчёт о сбое прогона: утверждений о документе в нём нет, числа и вердикт («не вынесен») "
              "сходятся")
        for w in result["warnings"][:10]:
            print(f"  ! {w}")
    elif result["ok"]:
        c = result["counts"]
        print(f"verify: OK — исходник совпадает (SHA-256 {result['sha256'][:12]}…), цитат на своих строках "
              f"{c['quotes_verified']} из {c['quotes_checked']}, счётчики и вердикт сходятся"
              + (", числа в отчёте .md те же" if result.get("markdown_checked") else "")
              + f", коммит {result['commit'] or 'не записан'}")
        for w in result["warnings"][:10]:
            print(f"  ! {w}")
    else:
        print(f"verify: расхождений — {len(result['errors'])}", file=sys.stderr)
        for e in result["errors"][:50]:
            print(f"  - {e['where']}: {e['message']}", file=sys.stderr)
    return EXIT_OK if result["ok"] else EXIT_VERIFY_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
