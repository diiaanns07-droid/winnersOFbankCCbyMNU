"""Подставной движок для режима разработки (``--engine dev``).

Это НЕ движок качества и не замена работе Max. Он нужен, чтобы веб-слой можно
было закончить и проверить параллельно: пишет настоящие файлы по контракту v1
(report.md + report.json из одного Report, report.html при ``exports=["html"]``),
принимает те же параметры, что ``RunOptions`` (лишние ключи — ошибка, как у
``RunOptions.coerce``), сообщает этапы через ``progress`` и умеет имитировать сбои.

Report проходит ``bcc_review.contracts.validate`` и ``evidence_errors`` (см.
tests/p15/test_contract_junction.py). Всё помечено ``run.mode = "mock"`` (или
``rules_only``), ``run.provider = "mock"``, ``run.model = "dev-mock"``.

Сценарии (``dev_scenario``, переменная ``BCC_WEB_DEV_SCENARIO`` или суффикс в
имени файла ``*__<сценарий>.md``): ``ok``, ``slow`` (1,5 с на этап),
``no_key`` (без offline_lint падает как движок без ключа), ``network`` (LLM
недоступна → rules_only, partial), ``parse_partial`` (часть таблицы не прочитана
→ partial), ``crash`` (исключение на этапе проверки набора).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

AGENT_VERSION = "dev-mock-1"
RUN_OPTION_KEYS = {
    "provider", "model", "offline_lint", "answers_path", "compare_path", "exports", "cache_dir", "use_cache",
    "max_calls", "max_seconds", "max_tokens", "max_retries", "timeout_s", "trace", "fail_on", "mock_script",
    "allow_partial_ready", "full_context_chars", "run_id", "parent_run_id", "artifacts_dir",
}
DEV_KEYS = {"progress", "tmp_dir", "dev_scenario", "dev_delay"}


class DevEngineError(RuntimeError):
    pass


class MissingApiKey(DevEngineError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- чтение
_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")


def _block(blocks: list[dict], kind: str, section: list[str], text: str, loc: dict) -> None:
    blocks.append({"id": f"b{len(blocks) + 1:04d}", "kind": kind, "section": list(section), "text": text, "loc": loc})


def _parse_markdown(text: str) -> tuple[list[dict], list[dict]]:
    blocks: list[dict] = []
    section: list[str] = []
    in_code, code_start, code_lines = False, 0, []
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                _block(blocks, "code", section, "\n".join(code_lines), {"line_start": code_start + 1, "line_end": no - 1 if no - 1 > code_start else code_start + 1})
                in_code, code_lines = False, []
            else:
                in_code, code_start = True, no
            continue
        if in_code:
            code_lines.append(line)
            continue
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if _SEP_RE.match(stripped):
            if blocks and blocks[-1]["kind"] == "table_row":
                blocks[-1]["kind"] = "table_header"
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            title = m.group(2).strip()
            level = len(m.group(1))
            section = section[: level - 1]
            _block(blocks, "heading", section, title, {"line_start": no, "line_end": no})
            section = section + [title]
            continue
        if stripped.startswith("|"):
            kind, body = "table_row", stripped
        elif re.match(r"^([*\-+]|\d+\.)\s+", stripped):
            kind, body = "list_item", re.sub(r"^([*\-+]|\d+\.)\s+", "", stripped)
        else:
            kind, body = "paragraph", stripped
        _block(blocks, kind, section, body, {"line_start": no, "line_end": no})
    return blocks, []


def _parse_pdf(path: Path) -> tuple[list[dict], list[dict]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return [], [{"code": "partial_read", "message": "PDF не разобран: в окружении dev-движка нет pypdf"}]
    blocks: list[dict] = []
    warnings: list[dict] = []
    for page_no, page in enumerate(PdfReader(str(path)).pages, start=1):
        lines = [ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip()]
        if not lines:
            warnings.append({"code": "unreadable_page", "message": f"Страница {page_no}: текст не извлечён (скан или пустая страница)"})
        for ln in lines:
            _block(blocks, "paragraph", [], ln, {"page": page_no})
    return blocks, warnings


def _parse_docx(path: Path) -> tuple[list[dict], list[dict]]:
    try:
        import docx  # type: ignore
    except ImportError:
        return [], [{"code": "partial_read", "message": "DOCX не разобран: в окружении dev-движка нет python-docx"}]
    d = docx.Document(str(path))
    blocks: list[dict] = []
    section: list[str] = []
    for i, p in enumerate(d.paragraphs):
        t = p.text.strip()
        if not t:
            continue
        if p.style is not None and p.style.name.lower().startswith("heading"):
            _block(blocks, "heading", [], t, {"part": "word/document.xml", "path": f"body/p[{i}]"})
            section = [t]
        else:
            _block(blocks, "paragraph", section, t, {"part": "word/document.xml", "path": f"body/p[{i}]"})
    for ti, table in enumerate(d.tables):
        for ri, row in enumerate(table.rows):
            t = " | ".join(c.text.strip() for c in row.cells)
            _block(blocks, "table_header" if ri == 0 else "table_row", section, t, {"part": "word/document.xml", "path": f"body/tbl[{ti}]/tr[{ri}]"})
    return blocks, []


def parse_document(path: Path, data: bytes) -> dict:
    ext = path.suffix.lower()
    if ext == ".pdf":
        (blocks, warnings), fmt = _parse_pdf(path), "pdf"
    elif ext == ".docx":
        (blocks, warnings), fmt = _parse_docx(path), "docx"
    else:
        blocks, warnings = _parse_markdown(data.decode("utf-8", errors="replace"))
        fmt = {".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html"}.get(ext, "text")
    title = next((b["text"] for b in blocks if b["kind"] == "heading"), path.stem)
    return {"id": hashlib.sha256(data).hexdigest(), "title": title, "format": fmt, "source_name": path.name, "blocks": blocks, "warnings": warnings}


# --------------------------------------------------------------------------- опоры
def _find(blocks: list[dict], quote: str) -> dict | None:
    for b in blocks:
        start = b["text"].find(quote)
        if start >= 0:
            return {"block_id": b["id"], "start": start, "end": start + len(quote), "quote": quote}
    return None


def _find_all(blocks: list[dict], quotes: list[str]) -> list[dict] | None:
    out = []
    for q in quotes:
        ev = _find(blocks, q)
        if ev is None:
            return None
        out.append(ev)
    return out


# --------------------------------------------------------------------------- «проверки» (фикстура кейса)
_RULES = [
    {"key": "get", "kind": "design_in_requirement", "criterion": "appropriate", "severity": "major",
     "title": "Метод сохранения объявлен как GET",
     "impact": "GET не должен менять данные; cardId и порог попадают в URL и журналы прокси.",
     "recommendation": "Заменить на POST или PUT с телом запроса.", "quotes": ["GET", "/alerts/saveLimit"]},
    {"key": "moment", "kind": "ambiguity", "criterion": "unambiguous", "severity": "minor",
     "title": "Размытая формулировка «в момент покупки»",
     "impact": "Неясно, от какого события и с какой задержкой считать момент уведомления.",
     "recommendation": "Указать событие процессинга и допустимую задержку.", "quotes": ["в момент покупки"]},
    {"key": "etc", "kind": "incomplete", "criterion": "complete", "severity": "minor",
     "title": "Открытый перечень кодов ответа «и далее»",
     "impact": "Набор неуспешных кодов не определён, тестировщик не знает, что проверять.",
     "recommendation": "Перечислить все коды ответа.", "quotes": ["400, 401 и далее"]},
    {"key": "tests", "kind": "placeholder", "criterion": "complete", "severity": "major",
     "title": "Раздел требований к тестированию не заполнен",
     "impact": "Нет критериев для приёмочного тестирования.",
     "recommendation": "Заполнить раздел или сослаться на критерии приёмки.", "quotes": ["заполняются тестировщиками"]},
]

_SEMANTIC = [
    {"key": "f3f4", "kind": "conflict", "criterion": "set_consistent", "severity": "critical",
     "title": "Ф-3 и Ф-4 дают разный исход после смены порога",
     "impact": "Разработчик и тестировщик выберут разные правила отправки push.",
     "blocked_decision": "Отправлять ли второй push в месяце после смены порога",
     "recommendation": "Явно указать, сбрасывает ли смена порога месячный лимит push.",
     "quotes": ["максимум один такой push за календарный месяц", "следующее достижение вызывает push независимо от истории предыдущей настройки"],
     "witness": {"input": "В январе push уже отправлен; клиент меняет порог с 50 000 на 60 000 ₸; расходы доходят до 60 000 ₸.",
                 "outcome_a": "Ф-3: второй push в январе не отправляется.", "outcome_b": "Ф-4: push отправляется независимо от истории."},
     "question": "Какое правило приоритетнее после изменения порога: «не более одного push за календарный месяц» (Ф-3) или «push независимо от истории предыдущей настройки» (Ф-4)?",
     "options": ["Приоритет Ф-3: не более одного push за месяц даже после смены порога.", "Приоритет Ф-4: смена порога открывает право на новый push в том же месяце."]},
    {"key": "ac2", "kind": "conflict", "criterion": "set_consistent", "severity": "critical",
     "title": "Критерий приёмки №2 противоречит Ф-2",
     "impact": "Тест по критерию №2 провалит реализацию, выполненную строго по Ф-2.",
     "blocked_decision": "К какому месяцу относить покупку на стыке месяцев",
     "recommendation": "Согласовать критерий №2 с Ф-2 и указать часовой пояс.",
     "quotes": ["Месяц определяется по дате совершения покупки в Алматы", "Февральский счётчик вырос на 4 000 ₸"],
     "witness": {"input": "Покупка совершена 31 января в 23:58, проведена 1 февраля в 00:03 по Алматы.",
                 "outcome_a": "Ф-2: покупка относится к январю.", "outcome_b": "Критерий №2: вырос февральский счётчик."},
     "question": "К какому месяцу относится покупка, совершённая 31 января в 23:58 и проведённая 1 февраля: по дате совершения (Ф-2) или по дате проведения (критерий №2)? В каком часовом поясе указано время совершения?",
     "options": ["По дате совершения в Asia/Almaty (UTC+5); критерий №2 исправить на январский счётчик.", "По дате проведения; исправить формулировку Ф-2."]},
    {"key": "api200", "kind": "conflict", "criterion": "set_consistent", "severity": "critical",
     "title": "Неверная сумма описана и как 400, и как 200 с ERROR",
     "impact": "Клиент API не знает, по какому признаку обрабатывать отказ.",
     "blocked_decision": "Как мобильное приложение распознаёт отказ в сохранении порога",
     "recommendation": "Оставить один способ сообщать об отказе.",
     "quotes": ["параметры запроса заполнены неверно", "{\"result\":\"ERROR\",\"message\":\"Проверьте сумму\"}"],
     "witness": {"input": "Запрос saveLimit с amount=999.", "outcome_a": "Статус 400 «параметры заполнены неверно».",
                 "outcome_b": "Статус 200 с result=ERROR «Проверьте сумму»."},
     "question": "Каким статусом отвечать на сумму вне диапазона 1 000–1 000 000: 400 или 200 с result=ERROR?",
     "options": ["400 Bad Request с полем message; пример 200 с ERROR удалить.", "200 с result=ERROR; описание 400 сузить до синтаксических ошибок."]},
    {"key": "read", "kind": "omission", "criterion": "set_complete", "severity": "major",
     "title": "Нет метода чтения порога и суммы за месяц",
     "impact": "Экран не сможет показать текущий порог и накопленную сумму.",
     "recommendation": "Описать метод чтения настроек и суммы за месяц.",
     "quotes": ["Приложение читает и сохраняет настройки", "Функциональные требования: чтение порога"],
     "question": "Нужен ли отдельный метод чтения порога и суммы за месяц, и где он описан?", "options": []},
]


def question_keys(blocks: list[dict]) -> list[str]:
    """Порядок вопросов документа: Q-01 — первый найденный, как нумерует настоящий движок.

    Номер зависит от документа: в другой версии Q-01 может означать другое."""
    return [sem["key"] for sem in _SEMANTIC if _find_all(blocks, sem["quotes"]) is not None]


def _apply_answers(path: Path, data: bytes, opts: dict, out: Path) -> tuple[Path, bytes, dict, list, dict | None]:
    """Как движок Max: ответы к другой версии не применяются; правки пишут редакцию отдельным файлом."""
    from .answers import parse_answers

    if not opts.get("answers_path"):
        return path, data, {}, [], None
    parsed = parse_answers(Path(opts["answers_path"]).read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(data).hexdigest()
    declared = parsed.meta.get("source_sha256")
    if declared and declared != source_sha:
        warn = {"code": "stale_answers", "message": f"ответы к версии {declared[:12]}…, документ {source_sha[:12]}…: не применены"}
        return path, data, {}, [warn], {"name": "answers", "status": "partial", "reason": warn["message"]}
    answers = {a.qid: (a.text, a.provenance) for a in parsed.answers}
    text = data.decode("utf-8", errors="replace")
    applied = 0
    for a in parsed.answers:
        for old, new in a.edits:
            if old and old in text:
                text = text.replace(old, new, 1)
                applied += 1
    if not applied:
        return path, data, answers, [], {"name": "answers", "status": "ok" if answers else "partial", "reason": "правок текста нет: проверяется исходная редакция"}
    rev = out.parent / f"{path.stem}.rev-{str(opts.get('run_id') or 'dev')[:16]}{path.suffix}"
    rev.write_bytes(text.encode("utf-8"))
    return rev, rev.read_bytes(), answers, [], {"name": "answers", "status": "ok", "reason": f"применено правок: {applied}; редакция: {rev.name}"}


# --------------------------------------------------------------------------- Report
def _build_report(path: Path, data: bytes, opts: dict, progress: Callable, scenario: str, delay: float, *,
                  source_sha: str | None = None, answers: dict | None = None, answer_stage: dict | None = None,
                  answer_warnings: list | None = None, answered_keys: dict | None = None) -> dict:
    stages: list[dict] = []
    if answer_stage:
        stages.append({**answer_stage, "calls": 0, "cache_hits": 0, "duration_s": 0.0, "implementation": "web.devengine"})
    t_run = time.monotonic()

    def stage(name: str):
        progress(name, "start")
        t0 = time.monotonic()
        if delay:
            time.sleep(delay)

        def done(status: str = "ok", reason: str | None = None, detail: str | None = None) -> None:
            stages.append({"name": name, "status": status, "calls": 0, "cache_hits": 0, "reason": reason,
                           "duration_s": round(time.monotonic() - t0, 3), "implementation": "web.devengine"})
            progress(name, "skip" if status == "skipped" else ("fail" if status == "failed" else "done"), detail or reason)

        return done

    started = _now()
    offline = bool(opts.get("offline_lint"))
    warnings: list[Any] = [{"code": "dev_mock", "message": "Отчёт создан подставным dev-движком веб-слоя (mock), а не общим движком bcc_review."}]
    warnings += answer_warnings or []

    done = stage("read")
    doc = parse_document(path, data)
    if scenario == "parse_partial":
        doc["warnings"].append({"code": "partial_read", "message": "Таблица на строках 140–158 не распознана: блоки пропущены"})
        doc["blocks"] = [b for b in doc["blocks"] if not (b["kind"] == "table_row" and 140 <= b["loc"].get("line_start", 0) <= 158)]
        for i, b in enumerate(doc["blocks"], start=1):
            b["id"] = f"b{i:04d}"
    done("partial" if doc["warnings"] else "ok", doc["warnings"][0]["message"] if doc["warnings"] else None, f"блоков: {len(doc['blocks'])}")
    blocks = doc["blocks"]

    if scenario == "no_key" and not offline:
        raise MissingApiKey("Не задан ключ ANTHROPIC_API_KEY: семантические проверки невозможны")

    done = stage("lint")
    raw_findings: list[dict] = []
    for rule in _RULES:
        ev = _find_all(blocks, rule["quotes"])
        if ev is not None:
            raw_findings.append({**{k: rule[k] for k in ("key", "kind", "criterion", "severity", "title", "impact", "recommendation")},
                                 "scope": "requirement", "source": "rules", "stage": "lint", "evidence": ev, "meaning_status": "deterministic"})
    done(detail=f"сигналов правил: {len(raw_findings)}")

    llm_down = scenario == "network"
    mode = "rules_only" if (offline or llm_down) else "mock"
    status_reasons: list[str] = []
    if llm_down:
        warnings.append({"code": "provider_unavailable", "message": "LLM недоступна (ConnectionError, имитация сети): выполнены только проверки по правилам; отчёт неполный."})
        status_reasons.append("провайдер LLM недоступен")
    if offline:
        warnings.append({"code": "offline_lint", "message": "Режим rules_only (--offline-lint): семантические проверки не выполнялись; отчёт неполный."})
        status_reasons.append("выполнены только детерминированные правила")

    done = stage("inventory")
    requirements: list[dict] = []
    for b in blocks:
        m = re.match(r"^\*\*(Ф-\d+)\.\*\*\s*(.*)$", b["text"])
        sec = b["section"][-1] if b["section"] else ""
        if m or (b["kind"] in ("list_item", "paragraph") and sec in ("Нефункциональные требования", "Требования к данным", "Требования к интеграции", "Особые правила", "Логика работы метода")):
            requirements.append({"id": f"R-{len(requirements) + 1:02d}", "source_id": m.group(1) if m else None, "text": b["text"],
                                 "block_ids": [b["id"]], "evidence": [{"block_id": b["id"], "start": 0, "end": len(b["text"]), "quote": b["text"]}],
                                 "kind": "functional" if m else "other", "section": b["section"], "review_status": "reviewed", "review_reason": None})
    done(detail=f"требований: {len(requirements)}")

    answers = answers or {}
    source_sha = source_sha or hashlib.sha256(data).hexdigest()

    questions: list[dict] = []
    decisions: list[dict] = []
    done = stage("cross")
    if mode == "mock":
        for sem in _SEMANTIC:
            ev = _find_all(blocks, sem["quotes"])
            if ev is None and sem["key"] not in (answered_keys or {}):
                continue
            if sem["key"] in (answered_keys or {}):
                qid = answered_keys[sem["key"]]
                text, prov = answers[qid]
                decisions.append({"question_id": qid, "source_sha256": source_sha, "answer": text, "edits": [], "note": f"происхождение: {prov}"})
                continue  # в mock-логике ответ аналитика снимает замечание
            qid = f"Q-{len(questions) + 1:02d}"
            f = {**{k: sem[k] for k in ("key", "kind", "criterion", "severity", "title", "impact", "recommendation")},
                 "scope": "set", "source": "mock-llm", "stage": "cross", "evidence": ev, "meaning_status": "confirmed"}
            if sem.get("blocked_decision"):
                f["blocked_decision"] = sem["blocked_decision"]
            if "witness" in sem:
                f["witness"] = dict(sem["witness"], evidence_a=ev[0], evidence_b=ev[1])
            if sem["kind"] == "omission":
                f["inspected_block_ids"] = [b["id"] for b in blocks if b["section"][1:2] == ["Часть B. REST API"]]
            raw_findings.append(f)
            questions.append({"id": qid, "_key": sem["key"], "prompt": sem["question"], "options": list(sem["options"])})
        done(detail=f"вопросов: {len(questions)}")
    else:
        done("skipped", "семантические проверки не выполнялись")

    done = stage("verify_meaning")
    if scenario == "crash":
        raise DevEngineError("Внутренняя ошибка движка на этапе проверки смысла (имитация)")
    done()

    done = stage("evidence")
    by_id = {b["id"]: b for b in blocks}
    order = {"critical": 0, "major": 1, "minor": 2}
    raw_findings.sort(key=lambda f: order[f["severity"]])
    audit = {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0, "note": "dev-движок: опоры найдены точным поиском подстроки"}
    findings: list[dict] = []
    for i, f in enumerate(raw_findings, start=1):
        evs = f.pop("evidence")
        ok = all(by_id[e["block_id"]]["text"][e["start"]:e["end"]] == e["quote"] for e in evs)
        audit["checked"] += len(evs)
        audit["confirmed"] += len(evs) if ok else 0
        ev_blocks = {e["block_id"] for e in evs}
        sev = f["severity"]
        finding = {
            "id": f"F-{i:03d}", "scope": f["scope"], "kind": f["kind"], "criterion": f["criterion"], "severity": sev,
            "title": f["title"], "impact": f["impact"], "req_ids": [r["id"] for r in requirements if set(r["block_ids"]) & ev_blocks],
            "hints": [{"block_id": e["block_id"], "quote": e["quote"]} for e in evs], "evidence": evs,
            "status": "confirmed" if ok else "needs_review", "anchor_status": "supported" if ok else "incomplete",
            "meaning_status": f["meaning_status"], "recommendation": f["recommendation"],
            "blocks": ["development", "testing"] if sev == "critical" else (["development"] if sev == "major" else []),
            "witness": f.get("witness"), "inspected_block_ids": f.get("inspected_block_ids", []), "merged_from": [],
            "cause": None, "source": f["source"], "stage": f["stage"], "notes": [], "match_key": f["key"],
        }
        if f.get("blocked_decision"):
            finding["blocked_decision"] = f["blocked_decision"]
        findings.append(finding)
    for q in questions:
        key = q.pop("_key")
        q["finding_ids"] = [f["id"] for f in findings if f["match_key"] == key]
        q["affected_req_ids"] = sorted({r for f in findings if f["match_key"] == key for r in f["req_ids"]})
    done(detail=f"опор подтверждено: {audit['confirmed']} из {audit['checked']}")

    checks = []
    for r in requirements:
        hit = [f["id"] for f in findings if r["id"] in f["req_ids"]]
        checks.append({"req_id": r["id"], "criterion": "correct", "status": "issue" if hit else ("pass" if mode == "mock" else "unknown"),
                       "reason": "Есть замечания" if hit else ("Замечаний нет" if mode == "mock" else "Семантическая проверка не выполнялась"),
                       "finding_ids": hit, "source": "dev-mock"})

    done = stage("verdict")
    critical = [f for f in findings if f["severity"] == "critical" and f["status"] == "confirmed"]
    partial_read = any(isinstance(w, dict) and w.get("code") in ("partial_read", "unreadable_page", "decode_error", "ocr_required", "truncated_input") for w in doc["warnings"])
    if partial_read:
        status_reasons.append("документ прочитан не полностью")
    if mode != "mock" or partial_read:
        dev = {"status": "unknown", "reasons": status_reasons or ["Проверка неполная"], "finding_ids": []}
        test = dict(dev)
    else:
        tests_empty = any(f["match_key"] == "tests" for f in findings)
        dev = {"status": "not_ready" if critical else "ready",
               "reasons": [f"Подтверждено критичных замечаний: {len(critical)}"] if critical else ["Критичных замечаний нет"],
               "finding_ids": [f["id"] for f in critical]}
        test_block = critical or [f for f in findings if f["match_key"] == "tests"]
        test = {"status": "not_ready" if (critical or tests_empty) else "ready",
                "reasons": (["Ожидаемые результаты противоречат требованиям"] if critical else []) + (["Раздел требований к тестированию пуст"] if tests_empty else []) or ["Блокирующих замечаний нет"],
                "finding_ids": [f["id"] for f in test_block]}
    first_actions = [{"order": i, "action": f"{f['id']}: {f['title']}", "finding_ids": [f["id"]]} for i, f in enumerate((critical or findings)[:3], start=1)]
    if questions:
        first_actions.append({"order": len(first_actions) + 1, "action": "Ответить на вопросы: " + ", ".join(q["id"] for q in questions), "finding_ids": []})
    done()

    diff = None
    if opts.get("compare_path"):
        done = stage("diff")
        base = json.loads(Path(opts["compare_path"]).read_text(encoding="utf-8"))
        base_by_key = {f.get("match_key"): f for f in base.get("findings", [])}
        cur_by_key = {f["match_key"]: f for f in findings}

        def entry(old: dict | None, new: dict | None, reason: str) -> dict:
            return {"old_ids": [old["id"]] if old else [], "new_ids": [new["id"]] if new else [], "reason": reason, "evidence": (new or {}).get("evidence", [])}

        diff = {
            "previous": {"source_sha256": (base.get("run") or {}).get("source_sha256", ""), "run_id": (base.get("run") or {}).get("run_id")},
            "current": {"source_sha256": doc["id"], "run_id": opts.get("run_id")},
            "resolved": [entry(f, None, "замечание не воспроизводится") for k, f in base_by_key.items() if k not in cur_by_key],
            "persisting": [entry(base_by_key[k], f, "та же проблема") for k, f in cur_by_key.items() if k in base_by_key],
            "introduced": [entry(None, f, "новое замечание") for k, f in cur_by_key.items() if k not in base_by_key],
            "unassessed": [], "impacted_req_ids": [], "warnings": [],
        }
        done()

    status = "partial" if (mode == "rules_only" or partial_read) else "complete"
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "major", "minor")}
    return {
        "schema_version": "1.0",
        "run": {
            "run_id": opts.get("run_id") or "dev-" + hashlib.sha1(started.encode()).hexdigest()[:8],
            "parent_run_id": opts.get("parent_run_id"),
            "source_sha256": source_sha, "source_name": path.name,
            "agent_version": AGENT_VERSION, "agent_commit": None,
            "provider": "mock", "model": "dev-mock", "requested_model": None, "models_seen": [],
            "mode": mode, "status": status, "status_reasons": status_reasons,
            "started_at": started, "finished_at": _now(), "duration_s": round(time.monotonic() - t_run, 3),
            "calls": {"physical": 0, "cache_hits": 0, "failed": 0, "retries": 0},
            "tokens": {"input": 0, "output": 0, "cache_read": 0},
            "budget": {"max_calls": int(opts.get("max_calls", 40)), "max_seconds": float(opts.get("max_seconds", 1500.0)), "max_tokens": None, "exhausted": False, "reason": None},
            "stages": stages,
            "incomplete_stages": [s["name"] for s in stages if s["status"] in ("partial", "failed", "skipped")],
            "modules": {"engine": "bcc_review.web.devengine"},
            "evidence_audit": audit,
            "options": {k: v for k, v in opts.items() if k in RUN_OPTION_KEYS},
        },
        "document": doc,
        "requirements": requirements,
        "checks": checks,
        "findings": findings,
        "facts": [], "coverage": [],
        "questions": questions,
        "checklist": [], "test_cases": [],
        "decisions": decisions,
        "diff": diff,
        "verdict": {"development": dev, "testing": test, "first_actions": first_actions, "basis": "dev-mock: правило «подтверждённый критичный дефект блокирует»"},
        "summary": {
            "requirements": len(requirements), "reviewed_requirements": len(requirements), "findings": len(findings),
            "by_severity": by_sev,
            "by_status": {s: sum(1 for f in findings if f["status"] == s) for s in ("confirmed", "needs_review")},
            "critical_ids": [f["id"] for f in findings if f["severity"] == "critical"],
            "checks": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "issue", "unknown", "na")},
        },
        "warnings": warnings + doc["warnings"],
        "excluded": [], "rejected": [],
    }


def _render_md(r: dict) -> str:
    run, v = r["run"], r["verdict"]
    lines = [
        f"# Отчёт о проверке требований (MOCK) — {r['document']['title']}", "",
        "> Сформирован подставным dev-движком веб-слоя. Не является отчётом общего движка.", "",
        "## Паспорт прогона",
        f"- Документ: {r['document']['source_name']} (SHA-256 `{run['source_sha256'][:16]}…`), run_id `{run['run_id']}`",
        f"- Режим: {run['mode']}; провайдер: {run['provider']}; модель: {run['model']}; вызовов: {run['calls']['physical']}",
        f"- Статус: {run['status']}; версия агента: {run['agent_version']}", "",
        "## Итог",
        f"- Разработка: {v['development']['status']} — {'; '.join(v['development']['reasons'])}",
        f"- Тестирование: {v['testing']['status']} — {'; '.join(v['testing']['reasons'])}",
        *[f"- {a['order']}. {a['action']}" for a in v["first_actions"]], "",
        "## Замечания",
    ]
    for f in r["findings"]:
        lines.append(f"### {f['id']}. {f['title']} ({f['severity']}, {f['criterion']}, {f['status']})")
        lines += [f"- `{e['block_id']}`: «{e['quote']}»" for e in f["evidence"]]
    lines += ["", "## Вопросы", *[f"- {q['id']}: {q['prompt']}" for q in r["questions"]]]
    if r["decisions"]:
        lines += ["", "## Решения", *[f"- {d['question_id']}: {d['answer']} ({d.get('note', '')})" for d in r["decisions"]]]
    lines += ["", "## Предупреждения", *[f"- {w['message'] if isinstance(w, dict) else w}" for w in r["warnings"]]]
    return "\n".join(lines) + "\n"


def _render_html(r: dict) -> str:
    import html as _h

    rows = "".join(f"<tr><td>{_h.escape(f['id'])}</td><td>{_h.escape(f['severity'])}</td><td>{_h.escape(f['title'])}</td></tr>" for f in r["findings"])
    return ("<!doctype html><meta charset='utf-8'><title>Отчёт (mock)</title><p><b>MOCK HTML</b> — заглушка вместо артефакта №13.</p>"
            f"<h1>{_h.escape(r['document']['title'])}</h1><table border=1>{rows}</table>")


def run_review(input_path: str | os.PathLike, report_md: str | os.PathLike, *, options: dict | None = None) -> dict:
    opts = dict(options or {})
    unknown = set(opts) - RUN_OPTION_KEYS - DEV_KEYS
    if unknown:  # как RunOptions.coerce: веб не должен слать движку лишнего
        raise ValueError(f"неизвестные параметры run_review: {sorted(unknown)}")
    progress: Callable = opts.pop("progress", None) or (lambda *a, **k: None)
    path, out = Path(input_path), Path(report_md)
    m = re.search(r"__([a-z_]+)$", path.stem)
    scenario = opts.pop("dev_scenario", None) or os.environ.get("BCC_WEB_DEV_SCENARIO") or (m.group(1) if m else "ok")
    delay = float(opts.pop("dev_delay", os.environ.get("BCC_WEB_DEV_DELAY", "0.3")))
    opts.pop("tmp_dir", None)
    if scenario == "slow":
        delay = max(delay, 1.5)
    original = path.read_bytes()
    reviewed, data, answers, answer_warnings, answer_stage = _apply_answers(path, original, opts, out)
    # Номера вопросов в answers.md — это нумерация проверенной версии (вход), а не редакции после правок.
    keys = question_keys(parse_document(path, original)["blocks"]) if answers else []
    answered_keys = {keys[int(q[2:]) - 1]: q for q in answers if re.fullmatch(r"Q-\d+", q) and 0 < int(q[2:]) <= len(keys)}
    report = _build_report(reviewed, data, opts, progress, scenario, delay, source_sha=hashlib.sha256(original).hexdigest(),
                           answers=answers, answer_stage=answer_stage, answer_warnings=answer_warnings, answered_keys=answered_keys)
    progress("render", "start")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_md(report), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if "html" in (opts.get("exports") or ()):
        out.with_suffix(".html").write_text(_render_html(report), encoding="utf-8")
    progress("render", "done")
    return report
