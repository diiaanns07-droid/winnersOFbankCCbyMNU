"""Резервные вопросы, ответы аналитика и редакция ТЗ (пока не влит модуль №08).

Файл ответов ``answers.md``::

    source_sha256: <SHA-256 проверенной редакции>

    ## Q-001
    Ответ: Смена порога сбрасывает месячный лимит push.
    Правка: «старый фрагмент» → «новый текст»

Правка заменяет фрагмент видимого текста блока; ``write_revision`` переносит её в исходный файл
по карте позиций ``loc.map``. Исходный файл не меняется: редакция пишется рядом отдельным файлом.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from ...contracts import AskError
from .evidence import resolve_hint
from .llm_stages import S, STR, STRS

_SHA = re.compile(r"source_sha256\s*:\s*([0-9a-f]{64})", re.I)
_Q = re.compile(r"^#{1,4}\s*(Q-\d+)\s*$", re.M)
_ANS = re.compile(r"^\s*(?:Ответ|Answer)\s*:\s*(.+)$", re.M | re.I)
_EDIT = re.compile(r"^\s*(?:Правка|Edit)\s*:\s*«(.+?)»\s*(?:→|->)\s*«(.*?)»\s*$", re.M | re.I)

QUESTIONS_SCHEMA = S({"questions": {"type": "array", "items": S({
    "finding_ids": STRS, "prompt": STR, "options": STRS, "affected_req_ids": STRS})}})

TASK_QUESTIONS = """Сформулируй уточняющие вопросы аналитику по замечаниям, которые нельзя исправить без решения бизнеса (противоречия, пропуски, неопределённые термины и события). Один вопрос закрывает одну первопричину; объединяй замечания с общей причиной. prompt — конкретный вопрос с упоминанием объекта и сценария; options — 2–4 взаимоисключающих варианта ответа (последний может быть «Другое: …»); finding_ids — ID замечаний из входа; affected_req_ids — затронутые требования. Не задавай вопросов, на которые документ уже отвечает."""


def build_questions(document: dict[str, Any], findings: list[dict[str, Any]], ask: Optional[Callable] = None
                    ) -> list[dict[str, Any]]:
    relevant = [f for f in findings if f["severity"] in ("critical", "major")
                and f["kind"] in ("conflict", "omission", "incomplete", "ambiguity", "incorrect", "infeasible")]
    questions: list[dict[str, Any]] = []
    if ask is not None and relevant:
        try:
            data = ask("questions", {"task": TASK_QUESTIONS, "input": {"findings": [
                {"id": f["id"], "severity": f["severity"], "kind": f["kind"], "title": f["title"],
                 "impact": f["impact"], "req_ids": f["req_ids"],
                 "witness": ({k: f["witness"][k] for k in ("input", "outcome_a", "outcome_b")} if f.get("witness") else None)}
                for f in relevant]}, "context": {"mode": "auto", "block_ids": [
                    e["block_id"] for f in relevant for e in f["evidence"]]}}, QUESTIONS_SCHEMA)
            ids = {f["id"] for f in relevant}
            for q in data["questions"]:
                fids = [x for x in q["finding_ids"] if x in ids]
                if fids:
                    questions.append({"id": f"Q-{len(questions) + 1:03d}", "finding_ids": fids, "prompt": q["prompt"],
                                      "options": q["options"], "affected_req_ids": q["affected_req_ids"]})
            return questions
        except AskError:
            questions = []
    for f in relevant:
        if f["kind"] == "conflict" and f.get("witness"):
            w = f["witness"]
            prompt = f"Какой исход верен в сценарии «{w['input']}»?"
            options = [w["outcome_a"], w["outcome_b"], "Другое: опишите правило"]
        elif f["severity"] == "critical":
            prompt = f"Как закрыть пробел: {f['title']}?"
            options = ["Дополнить требование (укажите текст)", "Вне рамок задачи (зафиксировать явно)"]
        else:
            continue
        questions.append({"id": f"Q-{len(questions) + 1:03d}", "finding_ids": [f["id"]], "prompt": prompt,
                          "options": options, "affected_req_ids": list(f["req_ids"])})
    return questions


def parse_answers(path: str | Path, document: dict[str, Any]) -> dict[str, Any]:
    """Возвращает ``{"decisions": [...], "warnings": [...]}``; правки привязаны к блокам документа."""
    text = Path(path).read_text(encoding="utf-8")
    warnings: list[str] = []
    m = _SHA.search(text)
    sha = m.group(1).lower() if m else None
    if sha and sha != document["id"]:
        return {"decisions": [], "warnings": [
            f"ответы относятся к другой редакции (source_sha256 {sha[:12]}…, документ {document['id'][:12]}…): не применены"]}
    if not sha:
        warnings.append("в ответах нет source_sha256: привязка к редакции не подтверждена, принято для текущего файла")
    decisions = []
    parts = _Q.split(text)
    for i in range(1, len(parts), 2):
        qid, body = parts[i], parts[i + 1]
        am = _ANS.search(body)
        edits = []
        for old, new in _EDIT.findall(body):
            r = resolve_hint(document, {"quote": old})
            if r["status"] != "matched":
                warnings.append(f"{qid}: правка «{old[:50]}» не привязана: {r['reason']}")
                continue
            ev = r["evidence"]
            edits.append({"block_id": ev["block_id"], "start": ev["start"], "end": ev["end"], "old": ev["quote"], "new": new})
        decisions.append({"question_id": qid, "source_sha256": document["id"],
                          "answer": am.group(1).strip() if am else "", "edits": edits})
    if not decisions:
        warnings.append("в файле ответов не найдено ни одного раздела «## Q-…»")
    return {"decisions": decisions, "warnings": warnings}


def propose_patch(document: dict[str, Any], finding: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if decision.get("edits"):
        return {"state": "explicit", "edits": decision["edits"], "warnings": []}
    return {"state": "needs_manual", "edits": [],
            "warnings": [f"{decision['question_id']}: ответ без явной правки — редакцию текста делает аналитик"]}


def _source_pos(block: dict[str, Any], offset: int) -> Optional[tuple[int, int]]:
    seg = None
    for entry in block.get("loc", {}).get("map", []):
        if entry[0] <= offset:
            seg = entry
        else:
            break
    return None if seg is None else (seg[1], seg[2] + offset - seg[0])


def write_revision(document: dict[str, Any], edits: list[dict[str, Any]], output_md: str | Path, *,
                   source_path: str | Path) -> Path:
    """Применить правки к исходному тексту (Markdown/TXT) и записать новую редакцию отдельным файлом."""
    raw = Path(source_path).read_bytes().decode("utf-8-sig")
    lines = raw.split("\n")
    by_id = {b["id"]: b for b in document["blocks"]}
    planned = []
    for e in edits:
        b = by_id[e["block_id"]]
        if b["text"][e["start"]:e["end"]] != e["old"]:
            raise ValueError(f"правка не совпадает с текстом блока {b['id']}")
        s = _source_pos(b, e["start"])
        last = _source_pos(b, e["end"] - 1)
        if s is None or last is None or s[0] != last[0] or last[1] - s[1] != e["end"] - 1 - e["start"]:
            raise ValueError(f"правка в блоке {b['id']} пересекает разметку: укажите фрагмент внутри одной строки")
        line = lines[s[0] - 1]
        if line[s[1]:last[1] + 1] != e["old"]:
            raise ValueError(f"правка в блоке {b['id']}: исходная строка не совпадает с видимым текстом")
        planned.append((s[0], s[1], last[1] + 1, e["new"]))
    for ln, cs, ce, new in sorted(planned, reverse=True):
        lines[ln - 1] = lines[ln - 1][:cs] + new + lines[ln - 1][ce:]
    out = Path(output_md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes("\n".join(lines).encode("utf-8"))
    return out
