"""Подставной продукт для стыковых тестов счётчика. Это НЕ продукт команды.

CLI как в контракте v1: python fake_bcc_review.py INPUT OUTPUT.md [--offline-lint]
[--provider anthropic|gemini|mock] [--no-cache]. Пишет OUTPUT.md и OUTPUT.json из одного
Report, который проходит bcc_review.contracts.validate и evidence_errors.

Правила намеренно простые: они ищут дефекты по тексту и не читают эталон. Слой «LLM»
в rules_plus_llm и mock — подставной транспорт без сети. Он считает физические вызовы и
токены и добавляет осторожную находку о цели, поэтому на чистых документах видны ложные
тревоги.

FAKE_MISBEHAVE=calls_in_rules_only заставляет rules_only сообщить 1 вызов: так тест
проверяет, что счётчик ловит нарушение режима.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KIND_FORMAT = {".md": "markdown", ".txt": "text", ".pdf": "pdf", ".docx": "docx"}


def _visible(line: str) -> tuple[str, str]:
    s = line.strip()
    if s.startswith("#"):
        return "heading", s.lstrip("#").strip()
    if s.startswith("|"):
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            return "", ""
        return "table_row", " | ".join(c.replace("**", "") for c in cells)
    if re.match(r"^[*\-] ", s):
        return "list_item", s[2:].replace("**", "")
    return "paragraph", s.replace("**", "")


def read_document(path: Path) -> tuple[str, list[dict], list]:
    fmt = KIND_FORMAT.get(path.suffix.lower(), "text")
    raw: list[tuple[str, str, dict]] = []
    if fmt == "pdf":
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for pg, page in enumerate(pdf.pages, 1):
                for line in (page.extract_text() or "").split("\n"):
                    raw.append(("paragraph", line.strip(), {"page": pg}))
    elif fmt == "docx":
        import docx
        d = docx.Document(str(path))
        for i, p in enumerate(d.paragraphs):
            kind = "heading" if p.style.name.startswith("Heading") else "paragraph"
            raw.append((kind, p.text.strip(), {"part": "word/document.xml", "path": f"body/p[{i}]"}))
        for ti, t in enumerate(d.tables):
            for ri, row in enumerate(t.rows):
                raw.append(("table_row", " | ".join(c.text.strip() for c in row.cells),
                            {"part": "word/document.xml", "path": f"body/tbl[{ti}]/tr[{ri}]"}))
    else:
        for n, line in enumerate(path.read_bytes().decode("utf-8").split("\n"), 1):
            kind, text = _visible(line)
            if kind:
                raw.append((kind, text, {"line_start": n, "line_end": n}))
    blocks = [{"id": f"b{i:04d}", "kind": k, "section": [], "text": t, "loc": loc}
              for i, (k, t, loc) in enumerate([r for r in raw if r[1]], 1)]
    warnings = [] if blocks else [{"code": "empty_document", "message": "Документ пуст: требования не найдены."}]
    return fmt, blocks, warnings


def ev(block: dict, quote: str) -> dict:
    start = block["text"].index(quote)
    return {"block_id": block["id"], "start": start, "end": start + len(quote), "quote": quote}


def sentence_at(text: str, start: int) -> str:
    end = text.find(".", start)
    return text[start:end + 1 if end >= 0 else len(text)]


def finding(kind: str, criterion: str, severity: str, title: str, evidence: list[dict], scope="set",
            witness: dict | None = None) -> dict:
    return {"scope": scope, "kind": kind, "criterion": criterion, "severity": severity, "title": title,
            "impact": "Разработчик и тестировщик получают разные ожидания.", "req_ids": [], "hints": [],
            "evidence": evidence, "status": "confirmed", "anchor_status": "supported",
            "meaning_status": "deterministic", "blocks": ["development", "testing"], "witness": witness,
            "blocked_decision": "Реализация и тест этого места", "source": "rules", "stage": "lint"}


def conflict(title: str, criterion: str, e1: dict, e2: dict) -> dict:
    w = {"input": title, "outcome_a": "исход A", "outcome_b": "исход B", "evidence_a": e1, "evidence_b": e2}
    return finding("conflict", criterion, "major", title, [e1, e2], witness=w)


STATUS_KEYS = {"Для карты другого клиента": "не принадлежит", "вне диапазона": "диапазон",
               "не из списка": "не из списка", "уже существует": "уже существует",
               "Повторная блокировка": "Статус карты", "дробной частью": "не целое"}


def rules(blocks: list[dict]) -> list[dict]:
    out = []
    rows = [b for b in blocks if re.match(r"^\d{3} \| ", b["text"])]
    # 1) Один вход — два кода: примечание «… возвращает NNN» против строки таблицы статусов.
    for b in blocks:
        m = re.search(r"(возвращает|вернуть|отклоняет со статусом) (\d{3})", b["text"])
        if not m or b in rows:
            continue
        start = max(b["text"].rfind(". ", 0, m.start()) + 2, 0) if ". " in b["text"][:m.start()] else 0
        sent = sentence_at(b["text"], start).strip()
        for r in rows:
            code, desc = r["text"].split(" | ")[0], r["text"].split(" | ")[1]
            if code != m.group(2) and any(k in sent and v in desc for k, v in STATUS_KEYS.items()):
                out.append(conflict(f"Один вход получает {m.group(2)} и {code}", "set_consistent",
                                    ev(b, sent), ev(r, f"{code} | {desc}")))
                break
    # 2) Величина в тиынах в API при тенге в бизнес-части.
    for b in blocks:
        if b["kind"] == "table_row" and "в тиынах" in b["text"]:
            other = next((o for o in blocks if "₸ включительно" in o["text"] and o["kind"] == "list_item"), None)
            if other:
                cell = next(c for c in b["text"].split(" | ") if "в тиынах" in c)
                m = re.search(r"[^.]*₸ включительно\.", other["text"])
                out.append(conflict("Одна величина в тиынах и в тенге", "unambiguous",
                                    ev(b, cell), ev(other, m.group(0).strip())))
    # 3) Обещанный «методом X» без раздела «Метод X».
    described = {m.group(1) for b in blocks if b["kind"] == "heading" for m in [re.search(r"Метод (\w+)", b["text"])] if m}
    for b in blocks:
        if b["text"].startswith("Приложение") and described:
            missing = [m.group(1) for m in re.finditer(r"методом (\w+)", b["text"]) if m.group(1) not in described]
            if missing:
                f = finding("omission", "set_complete", "critical", f"Метод {missing[0]} обещан, но не описан",
                            [ev(b, sentence_at(b["text"], 0))])
                out.append(f)
    return out


def llm_layer(blocks: list[dict], calls: dict) -> list[dict]:
    out = []
    for _stage in ("inventory", "individual", "cross"):
        calls["physical"] += 1
        calls["input"] += 400 + sum(len(b["text"]) for b in blocks) // 3
        calls["output"] += 150
    goal = next((blocks[i + 1] for i, b in enumerate(blocks[:-1]) if b["kind"] == "heading" and b["text"] == "Цели"), None)
    if goal:
        f = finding("unverifiable", "verifiable", "minor", "Цель не измерима", [ev(goal, goal["text"])], scope="requirement")
        f.update({"meaning_status": "uncertain", "status": "needs_review", "source": "llm", "stage": "individual"})
        out.append(f)
    for b in blocks:
        m = re.search(r"(После отключения автопополнения банк|Отменённый перевод) не ", b["text"])
        if m:
            other = next((o for o in blocks if o is not b and m.group(1) + " " in o["text"]
                          and m.group(1) + " не " not in o["text"]), None)
            if other:
                s1 = sentence_at(b["text"], b["text"].index(m.group(1)))
                s2 = sentence_at(other["text"], other["text"].index(m.group(1)))
                f = conflict("Одно событие, два исхода", "set_consistent", ev(b, s1), ev(other, s2))
                f.update({"severity": "critical", "source": "llm", "stage": "cross", "meaning_status": "confirmed"})
                out.append(f)
    return out


def main(argv: list[str]) -> int:
    inp, out_md = Path(argv[0]), Path(argv[1])
    provider = argv[argv.index("--provider") + 1] if "--provider" in argv else "anthropic"
    mode = "rules_only" if "--offline-lint" in argv else ("mock" if provider == "mock" else "rules_plus_llm")
    t0 = time.time()
    fmt, blocks, warnings = read_document(inp)
    findings = rules(blocks)
    calls = {"physical": 0, "input": 0, "output": 0}
    if mode != "rules_only":
        if os.environ.get("BCC_REVIEW_OFFLINE") == "1":
            print("rules_plus_llm запущен в офлайн-песочнице", file=sys.stderr)
            return 1
        findings += llm_layer(blocks, calls)
    if mode == "rules_only" and os.environ.get("FAKE_MISBEHAVE") == "calls_in_rules_only":
        calls["physical"] = 1
    for i, f in enumerate(findings, 1):
        f["id"] = f"F-{i:03d}"
    sha = hashlib.sha256(inp.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")}
    readiness = {"status": "not_ready" if findings else "ready", "reasons": [], "finding_ids": [f["id"] for f in findings]}
    report = {
        "schema_version": "1.0",
        "run": {"run_id": f"fake-{sha[:8]}", "parent_run_id": None, "source_sha256": sha, "agent_version": "fake-0",
                "agent_commit": None, "provider": "none" if mode == "rules_only" else provider,
                "model": None if mode == "rules_only" else "mock-model", "mode": mode, "status": "complete",
                "status_reasons": [], "started_at": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
                "finished_at": now.isoformat(), "duration_s": round(time.time() - t0, 4),
                "calls": {"physical": calls["physical"], "cache_hits": 0, "failed": 0, "retries": 0},
                "tokens": {"input": calls["input"], "output": calls["output"]},
                "stages": [], "incomplete_stages": [], "modules": {},
                "evidence_audit": {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0,
                                   "note": "подставной продукт"},
                # только для тестов песочницы: что видел дочерний процесс
                "debug_secret_env": sorted(k for k in os.environ if "API_KEY" in k),
                "debug_https_proxy": os.environ.get("HTTPS_PROXY"), "debug_no_cache": "--no-cache" in argv},
        "document": {"id": sha, "title": inp.name, "format": fmt, "blocks": blocks, "warnings": warnings},
        "requirements": [], "checks": [], "findings": findings, "facts": [], "coverage": [], "questions": [],
        "checklist": [], "test_cases": [], "decisions": [], "diff": None,
        "verdict": {"development": readiness, "testing": readiness, "first_actions": []},
        "summary": {"requirements": 0, "reviewed_requirements": 0, "findings": len(findings), "by_severity": by_sev,
                    "by_status": {"confirmed": sum(f["status"] == "confirmed" for f in findings),
                                  "needs_review": sum(f["status"] == "needs_review" for f in findings)},
                    "critical_ids": [f["id"] for f in findings if f["severity"] == "critical"],
                    "checks": {"pass": 0, "issue": 0, "unknown": 0, "na": 0}},
        "warnings": warnings,
    }
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("# Подставной отчёт\n\n" + "".join(f"- {f['id']}: {f['title']}\n" for f in findings), encoding="utf-8")
    out_md.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
