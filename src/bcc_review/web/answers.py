"""questions.md / answers.md: единый формат для скачивания, заполнения и повтора.

Совместим с разбором движка (``bcc_review.runtime.fallback.decisions.parse_answers``,
слот №08): строка ``source_sha256:``, раздел ``## Q-…`` на вопрос, ответ на строке
``Ответ:`` (продолжение — следующими строками), правки текста ``Правка: «было» → «стало»``::

    # Ответы на уточняющие вопросы
    <!-- bcc-review answers v1; run_id=… -->
    source_sha256: <SHA-256 документа, к которому относятся ответы>

    ## Q-001
    Вопрос: …
    Замечания: F-001
    Источник ответа: аналитик (веб-форма)
    Ответ: первая строка ответа
    продолжение ответа
    Правка: «старый фрагмент» → «новый текст»

Веб формирует questions.md из Report.questions только если движок не записал
свой questions.md. Строка «Источник ответа» хранит происхождение ответа:
аналитик, демонстрационный ответ команды или вариант решения №08.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEADER = "<!-- bcc-review answers v1"
ANALYST = "аналитик (веб-форма)"


_EDIT_RE = re.compile(r"^\s*(?:Правка|Edit)\s*:\s*«(.+?)»\s*(?:→|->)\s*«(.*?)»\s*$", re.I)


@dataclass
class Answer:
    qid: str
    text: str
    provenance: str = ANALYST
    question: str = ""
    edits: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class AnswerSet:
    answers: list[Answer] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def by_id(self) -> dict[str, Answer]:
        return {a.qid: a for a in self.answers}

    def provenance_summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.answers:
            out[a.provenance] = out.get(a.provenance, 0) + 1
        return out


def _q_text(q: dict[str, Any]) -> str:
    return str(q.get("prompt") or q.get("text") or q.get("question") or q.get("title") or "")


def render_questions(report: dict[str, Any], run_id: str, answers: dict[str, Answer] | None = None) -> str:
    run = report.get("run") or {}
    lines = [
        "# Уточняющие вопросы к документу",
        f"{HEADER}; run_id={run_id} -->",
        f"source_sha256: {run.get('source_sha256', '')}",
        "",
        "Впишите ответ после «Ответ:» и загрузите файл обратно на странице запуска.",
        "Чтобы исправить текст ТЗ, добавьте строку: Правка: «старый фрагмент» → «новый текст».",
        "Пустой ответ означает, что вопрос остаётся открытым.",
        "",
    ]
    asked = set()
    for q in report.get("questions") or []:
        qid = str(q.get("id") or "")
        if not qid:
            continue
        asked.add(qid)
        given = (answers or {}).get(qid)
        refs = q.get("finding_ids") or q.get("req_ids") or []
        lines += [f"## {qid}", f"Вопрос: {_q_text(q)}"]
        if refs:
            lines.append("Замечания: " + ", ".join(map(str, refs)))
        lines.append(f"Источник ответа: {given.provenance if given else ANALYST}")
        lines += _answer_lines(given) if given else ["Ответ:"]
        lines.append("")
    carried = [a for qid, a in (answers or {}).items() if qid not in asked]
    if carried:
        lines += ["# Действующие ответы прошлых редакций", "", "Перенесутся в следующую редакцию; измените текст, чтобы заменить ответ.", ""]
        for a in carried:
            lines += [f"## {a.qid}"]
            if a.question:
                lines.append(f"Вопрос: {a.question}")
            lines += [f"Источник ответа: {a.provenance}", *_answer_lines(a), ""]
    return "\n".join(lines).rstrip() + "\n"


def _answer_lines(a: Answer) -> list[str]:
    first, *rest = (a.text.strip() or "").split("\n")
    return [f"Ответ: {first}".rstrip(), *rest, *(f"Правка: «{old}» → «{new}»" for old, new in a.edits)]


def compose_answers(answers: list[Answer], *, run_id: str, source_sha256: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Ответы на уточняющие вопросы",
        f"{HEADER}; run_id={run_id}; created={stamp} -->",
        f"source_sha256: {source_sha256}",
        "",
    ]
    for a in answers:
        lines += [f"## {a.qid}"]
        if a.question:
            lines.append(f"Вопрос: {a.question}")
        lines += [f"Источник ответа: {a.provenance}", *_answer_lines(a), ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_answers(text: str) -> AnswerSet:
    result = AnswerSet()
    m = re.search(r"<!--\s*bcc-review answers v1;([^>]*)-->", text)
    if m:
        for part in m.group(1).split(";"):
            k, _, v = part.strip().partition("=")
            if k:
                result.meta[k.strip()] = v.strip()
    sha = re.search(r"(?mi)^\s*source_sha256\s*:\s*([0-9a-f]{64})", text)
    if sha:
        result.meta["source_sha256"] = sha.group(1).lower()
    sections = re.split(r"(?m)^##\s+", text)
    for sec in sections[1:]:
        head, _, body = sec.partition("\n")
        qid = head.strip().split()[0] if head.strip() else ""
        if not re.fullmatch(r"[\w\-]+", qid):
            continue
        provenance, question, answer_lines, in_answer, edits = ANALYST, "", [], False, []
        for line in body.splitlines():
            em = _EDIT_RE.match(line)
            if em:
                edits.append((em.group(1), em.group(2)))
                continue
            if not in_answer:
                if line.startswith("Источник ответа:"):
                    provenance = line.split(":", 1)[1].strip() or ANALYST
                elif line.startswith("Вопрос:"):
                    question = line.split(":", 1)[1].strip()
                elif re.match(r"^\s*Ответ\s*:", line):
                    in_answer = True
                    rest = line.split(":", 1)[1].strip()
                    if rest:
                        answer_lines.append(rest)
            else:
                if re.match(r"^#\s", line):
                    break  # заголовок верхнего уровня закрывает ответ (раздел «Действующие ответы» и т. п.)
                answer_lines.append(line)
        text_ = "\n".join(answer_lines).strip()
        if text_ or edits:
            result.answers.append(Answer(qid, text_, provenance, question, edits))
    return result


def load_demo_answers(path: Path | None) -> list[dict[str, Any]]:
    """Демонстрационные ответы команды: answers.md-подобный файл.

    Раздел ``## <ID или ключевые слова через запятую>``; ответ подставляется
    в вопрос с тем же ID или в вопрос, где встречаются все ключевые слова.
    Происхождение берётся из строки «Источник ответа:» файла.
    """
    if not path or not path.is_file():
        return []
    out = []
    text = path.read_text(encoding="utf-8")
    for sec in re.split(r"(?m)^##\s+", text)[1:]:
        head, _, body = sec.partition("\n")
        parsed = parse_answers("## X\n" + body)
        if not parsed.answers:
            continue
        a = parsed.answers[0]
        keys = [k.strip().lower() for k in head.split(",") if k.strip()]
        out.append({"keys": keys, "text": a.text, "edits": a.edits, "provenance": a.provenance if a.provenance != ANALYST else f"демонстрационный ответ команды ({path.name})"})
    return out


def match_demo_answer(demo: list[dict[str, Any]], question: dict[str, Any]) -> dict[str, Any] | None:
    qid = str(question.get("id") or "").lower()
    text = _q_text(question).lower()
    for item in demo:
        if qid and item["keys"] == [qid]:
            return item
    for item in demo:
        if item["keys"] and all(k in text for k in item["keys"]):
            return item
    return None
