"""Отчёт v2 для CI: дефекты требований — пометками на строках ТЗ в pull/merge request.

Три формата из одного ``report.json``, без модели и без сети:

* **sarif** — ``<out_base>.sarif`` (SARIF 2.1.0, OASIS). GitHub Code Scanning (``upload-sarif``), Azure DevOps,
  SonarQube, GitLab (через конвертер) и IDE (VS Code SARIF Viewer) показывают каждый дефект на строке документа:
  правило — критерий стандарта, уровень — серьёзность, связанные места — остальные цитаты.
* **gitlab** — ``<out_base>.codequality.json`` (GitLab Code Quality): виджет MR и пометки в diff.
* **github** — команды GitHub Actions ``::error file=…,line=…::`` в stdout: пометки в «Files changed» без
  Advanced Security (работает и в приватном репозитории). ``python -m bcc_review.v2.render.ci report.json``.

Места берутся только из сверенных цитат (``verified != "missing"``); номер строки — строка исходного файла
(для MD/TXT колонки уточняются поиском цитаты в строке файла). Путь файла — относительно корня репозитория
(``BCC_CI_ROOT``, иначе ``GITHUB_WORKSPACE`` / ``CI_PROJECT_DIR``, иначе текущий каталог).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .exports import (BLOCKS_RU, CRITERIA, SEVERITY_RU, _one_line, _res, _verified, criterion_label,
                      findings_of, place_of, reader_report)

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFO_URI = "https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU"
LEVEL = {"critical": "error", "major": "warning", "minor": "note"}
GITLAB_SEVERITY = {"critical": "blocker", "major": "major", "minor": "minor"}
GITHUB_COMMAND = {"critical": "error", "major": "warning", "minor": "notice"}
# «security-severity» GitHub сортирует и фильтрует по нему (0–10); для требований — «насколько больно»
SCORE = {"critical": "9.0", "major": "6.0", "minor": "3.0"}
TEXT_FORMATS = {"md", "txt"}


# --------------------------------------------------------------------------- общие части
def repo_path(input_path: str | Path, root: str | Path | None = None) -> str:
    """Путь документа для CI: относительно корня репозитория, через «/»."""
    p = Path(input_path).resolve()
    roots = [root] if root else [os.environ.get(k) for k in ("BCC_CI_ROOT", "GITHUB_WORKSPACE", "CI_PROJECT_DIR")]
    roots = [r for r in roots if r] + [os.getcwd()]
    for r in roots:
        try:
            return p.relative_to(Path(r).resolve()).as_posix()
        except ValueError:
            continue
    return p.name


def _source_lines(input_path: str | Path, fmt: str) -> list[str] | None:
    if fmt not in TEXT_FORMATS:
        return None
    try:
        return Path(input_path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None


def _region(ev: dict, lines: list[str] | None) -> dict | None:
    a = ev.get("line_start") or ev.get("line")
    if not a:
        return None
    b = ev.get("line_end") or a
    region: dict[str, Any] = {"startLine": int(a)}
    if int(b) != int(a):
        region["endLine"] = int(b)
    if lines and 0 < int(a) <= len(lines):
        quote = " ".join(str(ev.get("quote") or "").split())
        line = lines[int(a) - 1]
        col = line.find(quote) if quote else -1
        if col >= 0 and int(b) == int(a):
            region["startColumn"], region["endColumn"] = col + 1, col + 1 + len(quote)
        region["snippet"] = {"text": line if int(b) == int(a) else "\n".join(lines[int(a) - 1:int(b)])}
    return region


def _evidence(f: dict) -> list[dict]:
    return [e for e in f.get("evidence") or [] if isinstance(e, dict) and _verified(e)
            and (e.get("line_start") or e.get("line"))]


def fingerprint(f: dict) -> str:
    """Стабилен между прогонами при той же цитате и критерии — CI не плодит «новые» дефекты."""
    ev = _evidence(f)
    key = "|".join([str(f.get("criterion") or ""), str(f.get("kind") or "")]
                   + sorted(" ".join(str(e.get("quote") or "").split()) for e in ev))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def finding_text(f: dict, *, short: bool = False) -> str:
    """Текст пометки: что не так, почему важно, как исправить, что спросить у владельца."""
    sev = str(f.get("severity") or "")
    head = f"[{f.get('id', '')}] {SEVERITY_RU.get(sev, sev)}: {_one_line(f.get('title'))}"
    blocks = BLOCKS_RU.get(str(f.get("blocks") or "none"), "")
    parts = [head + (f" — блокирует {blocks}" if blocks else "")]
    if f.get("criterion"):
        parts.append(f"Критерий: {criterion_label(f.get('criterion'))}.")
    for label, key in (("Проблема", "problem"), ("Сценарий", "scenario"), ("Последствия", "impact"),
                       ("Как исправить", "recommendation"), ("Было → стало", "rewrite"),
                       ("Вопрос владельцу", "question")):
        if short and key in ("scenario", "impact"):
            continue
        if f.get(key):
            parts.append(f"{label}: {_one_line(f[key])}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- SARIF 2.1.0
def _rule(code: str, findings: list[dict]) -> dict:
    name, ref = CRITERIA.get(code, (code or "Прочее", ""))
    worst = min((str(f.get("severity")) for f in findings), key=lambda s: list(LEVEL).index(s) if s in LEVEL else 9)
    return {"id": f"BCC/{code or 'other'}", "name": "".join(w.capitalize() for w in (code or "other").split("_")),
            "shortDescription": {"text": name},
            "fullDescription": {"text": f"{name} — {ref}" if ref else name},
            "help": {"text": f"Критерий качества требований «{name}»" + (f" ({ref})." if ref else "."),
                     "markdown": f"**{name}**" + (f" — {ref}" if ref else "")},
            "defaultConfiguration": {"level": LEVEL.get(worst, "warning")},
            "properties": {"tags": ["requirements", "iso-29148"] + (["ieee-830"] if "830" in ref else []),
                           "precision": "high"}}


def build_sarif(report: dict, input_path: str | Path, *, root: str | Path | None = None) -> dict:
    report = reader_report(report)
    doc = report.get("document") or {}
    run = report.get("run") or {}
    uri = repo_path(input_path, root)
    lines = _source_lines(input_path, str(doc.get("format") or Path(input_path).suffix.lstrip(".")))
    fs = [f for f in findings_of(report) if _evidence(f)]
    by_rule: dict[str, list[dict]] = {}
    for f in fs:
        by_rule.setdefault(str(f.get("criterion") or ""), []).append(f)
    rules = [_rule(code, items) for code, items in by_rule.items()]
    index = {r["id"]: i for i, r in enumerate(rules)}
    results = []
    for f in fs:
        sev = str(f.get("severity") or "")
        locs = []
        for ev in _evidence(f):
            phys: dict[str, Any] = {"artifactLocation": {"uri": uri, "uriBaseId": "SRCROOT", "index": 0}}
            region = _region(ev, lines)
            if region:
                phys["region"] = region
            loc: dict[str, Any] = {"physicalLocation": phys,
                                   "message": {"text": f"«{_one_line(ev.get('quote'))}» — {place_of(ev)}"}}
            if ev.get("section"):
                loc["logicalLocations"] = [{"name": str(ev["section"]).split(" › ")[-1],
                                            "fullyQualifiedName": str(ev["section"]), "kind": "section"}]
            locs.append(loc)
        rid = f"BCC/{f.get('criterion') or 'other'}"
        res: dict[str, Any] = {
            "ruleId": rid, "ruleIndex": index[rid], "level": LEVEL.get(sev, "warning"),
            "message": {"text": finding_text(f)},
            "locations": locs[:1],
            "partialFingerprints": {"bccFinding/v1": fingerprint(f)},
            "properties": {"bccId": f.get("id"), "severity": sev, "kind": f.get("kind"),
                           "blocks": f.get("blocks"), "requirementIds": f.get("requirement_ids") or [],
                           "standardRefs": f.get("standard_refs") or [], "security-severity": SCORE.get(sev, "5.0"),
                           "fixFirst": bool(f.get("priority"))}}
        if len(locs) > 1:
            res["relatedLocations"] = [{**loc, "id": i} for i, loc in enumerate(locs[1:], 1)]
        if f.get("rewrite"):  # подсказка человеку, не автопатч: SARIF «fixes» требует точных замен
            res["properties"]["suggestedRewrite"] = _one_line(f["rewrite"])
        results.append(res)
    verdict = report.get("verdict") or {}
    return {
        "$schema": SARIF_SCHEMA, "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "BCC Review", "informationUri": INFO_URI,
                                "version": str(run.get("version") or ""),
                                "semanticVersion": str(run.get("version") or "").split("-")[0] or None,
                                "rules": rules}},
            "automationDetails": {"id": f"bcc-review/{uri}/"},
            "columnKind": "unicodeCodePoints",
            "originalUriBaseIds": {"SRCROOT": {"description": {"text": "корень репозитория"}}},
            "artifacts": [{"location": {"uri": uri, "uriBaseId": "SRCROOT"},
                           "hashes": {"sha-256": doc.get("sha256")} if doc.get("sha256") else {},
                           "description": {"text": str(doc.get("title") or "")}}],
            "invocations": [{"executionSuccessful": run.get("status") in ("complete", "partial", None),
                             "startTimeUtc": run.get("started_at"), "endTimeUtc": run.get("finished_at"),
                             "properties": {"provider": run.get("provider"), "models": run.get("models_used"),
                                            "commit": run.get("commit"), "runStatus": run.get("status")}}],
            "results": results,
            "properties": {"verdict": {"development": verdict.get("development"),
                                       "testing": verdict.get("testing"), "summary": verdict.get("summary")},
                           "quoteStats": report.get("quote_stats")},
        }],
    }


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if v is not None and v != {}}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def write_sarif(report: dict, input_path: str | Path, path: str | Path) -> dict:
    data = _clean(build_sarif(report, input_path))
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data["runs"][0]["results"])
    total = len(findings_of(report))
    return _res("sarif", "written", Path(path), f"SARIF: {n} из {total} дефектов на строках документа",
                anchored=n, total=total)


# --------------------------------------------------------------------------- GitLab Code Quality
def build_gitlab(report: dict, input_path: str | Path, *, root: str | Path | None = None) -> list[dict]:
    report = reader_report(report)
    uri = repo_path(input_path, root)
    out = []
    for f in findings_of(report):
        ev = _evidence(f)
        if not ev:
            continue
        a = int(ev[0].get("line_start") or ev[0].get("line"))
        b = int(ev[0].get("line_end") or a)
        sev = str(f.get("severity") or "")
        out.append({"description": f"[{f.get('id')}] {_one_line(f.get('title'))}",
                    "check_name": f"BCC/{f.get('criterion') or 'other'}",
                    "content": {"body": finding_text(f)},
                    "categories": ["Clarity" if f.get("criterion") in ("unambiguous", "language") else "Bug Risk"],
                    "fingerprint": fingerprint(f), "severity": GITLAB_SEVERITY.get(sev, "info"),
                    "location": {"path": uri, "lines": {"begin": a, "end": b}}})
    return out


def write_gitlab(report: dict, input_path: str | Path, path: str | Path) -> dict:
    data = build_gitlab(report, input_path)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(findings_of(report))
    return _res("gitlab", "written", Path(path), f"GitLab Code Quality: {len(data)} из {total} дефектов",
                anchored=len(data), total=total)


# --------------------------------------------------------------------------- GitHub Actions
def _escape_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(s: str) -> str:
    return _escape_data(s).replace(":", "%3A").replace(",", "%2C")


def github_commands(report: dict, input_path: str | Path, *, root: str | Path | None = None) -> list[str]:
    """Команды ``::error|warning|notice file=…,line=…,title=…::текст``. GitHub показывает до 10 пометок
    каждого вида на шаг — порядок «исправить первым», затем серьёзность, поэтому важное видно всегда."""
    report = reader_report(report)
    uri = repo_path(input_path, root)
    out = []
    for f in findings_of(report):
        ev = _evidence(f)
        if not ev:
            continue
        a = int(ev[0].get("line_start") or ev[0].get("line"))
        b = int(ev[0].get("line_end") or a)
        sev = str(f.get("severity") or "")
        title = f"{f.get('id')} {SEVERITY_RU.get(sev, sev)}: {_one_line(f.get('title'))}"[:200]
        props = f"file={_escape_prop(uri)},line={a}" + (f",endLine={b}" if b != a else "") + \
                f",title={_escape_prop(title)}"
        out.append(f"::{GITHUB_COMMAND.get(sev, 'warning')} {props}::{_escape_data(finding_text(f, short=True))}")
    return out


def step_summary(report: dict, input_path: str | Path, *, report_md: str | None = None,
                 root: str | Path | None = None) -> str:
    """Markdown для ``$GITHUB_STEP_SUMMARY`` / комментария к PR: вердикт и таблица «исправить первым»."""
    report = reader_report(report)
    doc, v, run = report.get("document") or {}, report.get("verdict") or {}, report.get("run") or {}
    uri = repo_path(input_path, root)
    ru = {"no": "нельзя", "conditional": "с условиями", "yes": "можно"}
    icon = "🔴" if "no" in (v.get("development"), v.get("testing")) else (
        "🟡" if "conditional" in (v.get("development"), v.get("testing")) else "🟢")
    fs = findings_of(report)
    cnt = {s: sum(1 for f in fs if f.get("severity") == s) for s in ("critical", "major", "minor")}
    qs = report.get("quote_stats") or {}
    lines = [f"### {icon} BCC Review: {doc.get('title') or uri}",
             "",
             f"**Разработка: {ru.get(v.get('development'), v.get('development'))} · "
             f"тестирование: {ru.get(v.get('testing'), v.get('testing'))}** — `{uri}`, "
             f"дефектов {len(fs)} (критичных {cnt['critical']}, существенных {cnt['major']}, "
             f"незначительных {cnt['minor']})",
             ""]
    if v.get("summary"):
        lines += [f"> {_one_line(v['summary'])}", ""]
    lines += ["| ID | Серьёзность | Где | Что не так |", "| :-- | :-- | :-- | :-- |"]
    for f in fs[:15]:
        ev = _evidence(f)
        where = ""
        if ev:
            a = int(ev[0].get("line_start") or ev[0].get("line"))
            where = f"строка {a}"
        title = _one_line(f.get("title")).replace("|", "\\|")
        lines.append(f"| {f.get('id')} | {SEVERITY_RU.get(str(f.get('severity')), '')} | {where} | {title} |")
    if len(fs) > 15:
        lines.append(f"| … | | | ещё {len(fs) - 15} — в артефакте отчёта |")
    checked, total = qs.get("verified"), qs.get("quotes")
    lines += ["", f"<sub>Провайдер {run.get('provider')}, вызовов модели "
                  f"{(run.get('calls') or {}).get('total')}, {run.get('duration_s')} с"
              + (f"; цитат сверено {checked} из {total}" if total else "")
              + f"; коммит агента `{run.get('commit')}`.</sub>"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m bcc_review.v2.render.ci",
                                description="Отчёт BCC Review → пометки в CI (GitHub Actions, SARIF, GitLab).")
    p.add_argument("report", help="report.json агента")
    p.add_argument("input", nargs="?", help="файл требований (по умолчанию — document.file рядом с отчётом)")
    p.add_argument("--format", choices=["github", "sarif", "gitlab", "summary"], default="github")
    p.add_argument("--output", help="куда писать (по умолчанию stdout)")
    a = p.parse_args(argv)
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    inp = a.input or (report.get("document") or {}).get("file") or "requirements.md"
    if a.format == "github":
        text = "\n".join(github_commands(report, inp)) + "\n"
    elif a.format == "summary":
        text = step_summary(report, inp)
    elif a.format == "sarif":
        text = json.dumps(_clean(build_sarif(report, inp)), ensure_ascii=False, indent=2)
    else:
        text = json.dumps(build_gitlab(report, inp), ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
