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

Загруженный файл ответов читает :func:`read_import`. Он понимает веб-формат,
экспорт автономного HTML №13 (``format: bcc-review-answers/1``, ``### Ответ``) и
файл вопросов №08 (``<!-- bcc-review:answers v1 -->``, ``## Q-01. …``). Опубликованные
парсеры №13 (``exports.html.parse_answers_markdown``) и №08
(``decisions.answers.parse_answers``) вызываются, если они установлены, иначе работает
встроенный разбор. Какая реализация отработала, записывается в ``Imported.parser``.
Версию, к которой относятся ответы, даёт заявленный ``source_sha256``.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEADER = "<!-- bcc-review answers v1"
ANALYST = "аналитик (веб-форма)"


_EDIT_RE = re.compile(r"^\s*(?:Правка|Edit)\s*:\s*«(.+?)»\s*(?:→|->)\s*«(.*?)»\s*$", re.I)
# «Формулировка: …» — правка в понимании №08: заменяет предложение с целевой цитатой вопроса.
_WORDING_RE = re.compile(r"^\s*(?:\*\*)?(?:новая\s+формулировка|формулировка)(?:\*\*)?\s*[:：]\s*(.*)$", re.I)


@dataclass
class Answer:
    qid: str
    text: str
    provenance: str = ANALYST
    question: str = ""
    edits: list[tuple[str, str]] = field(default_factory=list)
    wording: str = ""


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


def report_version(report: dict[str, Any]) -> str:
    """SHA-256 документа, о котором заданы вопросы отчёта (document.id; иначе run.source_sha256)."""
    return str((report.get("document") or {}).get("id") or (report.get("run") or {}).get("source_sha256") or "")


def render_questions(report: dict[str, Any], run_id: str, answers: dict[str, Answer] | None = None) -> str:
    lines = [
        "# Уточняющие вопросы к документу",
        f"{HEADER}; run_id={run_id} -->",
        f"source_sha256: {report_version(report)}",
        "",
        "Впишите ответ после «Ответ:» и загрузите файл обратно на странице запуска.",
        "Чтобы исправить текст ТЗ, добавьте строку: Правка: «старый фрагмент» → «новый текст».",
        "Пустой ответ означает, что вопрос остаётся открытым.",
        "Файл относится только к этой версии документа (source_sha256): к другой версии его не применить.",
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
    return "\n".join(lines).rstrip() + "\n"


def _answer_lines(a: Answer) -> list[str]:
    first, *rest = (a.text.strip() or "").split("\n")
    # Строки ответа, начинающиеся с # или \, экранируются ведущим \ (как в экспорте №13):
    # иначе «## …» внутри ответа разорвал бы раздел вопроса.
    rest = [("\\" + ln if ln.startswith(("#", "\\")) else ln) for ln in rest]
    lines = [f"Ответ: {first}".rstrip(), *rest, *(f"Правка: «{old}» → «{new}»" for old, new in a.edits)]
    if a.wording.strip():
        lines.append("Формулировка: " + " ".join(a.wording.split()))
    return lines


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
        qid = head.strip().split()[0].rstrip(".:)") if head.strip() else ""
        if not re.fullmatch(r"[\w\-]+", qid):
            continue
        head_question = head.strip()[len(qid):].lstrip(".:) ").strip()  # «## Q-01. вопрос» у №08
        provenance, question, answer_lines, in_answer, edits, wording = ANALYST, head_question, [], False, [], ""
        for line in body.splitlines():
            em = _EDIT_RE.match(line)
            if em:
                edits.append((em.group(1), em.group(2)))
                continue
            wm = _WORDING_RE.match(line)
            if wm and in_answer:
                wording = wm.group(1).strip()
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
                    break  # заголовок верхнего уровня закрывает ответ
                answer_lines.append(line[1:] if line.startswith("\\") else line)
        text_ = "\n".join(answer_lines).strip()
        if text_ or edits or wording:
            result.answers.append(Answer(qid, text_, provenance, question, edits, wording))
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
        out.append({"keys": keys, "text": a.text, "edits": a.edits, "wording": a.wording, "provenance": a.provenance if a.provenance != ANALYST else f"демонстрационный ответ команды ({path.name})"})
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


# --------------------------------------------------------------------------- импорт файла ответов
SHA_RE = re.compile(r"source_sha256[ \t]*[:=][ \t]*`?([0-9a-fA-F]{64})`?")
HTML13_FORMAT = "bcc-review-answers/1"
P08_MARKER = "<!-- bcc-review:answers v1 -->"
P08_PARSER_ENV = "BCC_WEB_ANSWERS_PARSER"
P08_PARSER_DEFAULT = "bcc_review.decisions.answers:parse_answers"  # contracts/HANDOFF.md, №08
HTML13_PARSER = "bcc_review.exports.html:parse_answers_markdown"  # tests/p13/README.md, №13
FORMAT_LABELS = {
    "web": "веб-формат (Ответ: …)",
    "html13": "экспорт автономного HTML №13 (### Ответ)",
    "p08": "файл вопросов №08",
    "legacy": "файл без заголовка формата",
}


@dataclass
class Imported:
    """Разобранный файл ответов. Сам по себе ничего не применяет: версию сверяет сервис."""

    format: str
    parser: str
    declared_sha256: str | None
    sha_values: list[str]
    answers: list[Answer]
    questions: dict[str, str]
    warnings: list[str]
    file_sha256: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def format_label(self) -> str:
        return FORMAT_LABELS.get(self.format, self.format)

    @property
    def sha_conflict(self) -> bool:
        return len(set(self.sha_values)) > 1


def _load(target: str):
    mod_name, _, attr = target.partition(":")
    try:
        return getattr(importlib.import_module(mod_name), attr)
    except Exception:
        return None


def _normalize(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")


def detect_format(text: str) -> str:
    head = text.lstrip()[:2000]
    if head.startswith("---") and re.search(rf"(?m)^format:[ \t]*{re.escape(HTML13_FORMAT)}[ \t]*$", head):
        return "html13"
    if P08_MARKER in head:
        return "p08"
    if HEADER in head:
        return "web"
    return "legacy"


def declared_shas(text: str) -> list[str]:
    """Все source_sha256 в шапке (до первого раздела вопроса); без шапки — во всём файле."""
    first = re.search(r"(?m)^##[ \t]", text)
    header = text[: first.start()] if first else text
    found = [x.lower() for x in SHA_RE.findall(header)] or [x.lower() for x in SHA_RE.findall(text)]
    return list(dict.fromkeys(found))


def _html13_builtin(text: str) -> dict[str, Any]:
    """Тот же разбор, что ``parse_answers_markdown`` №13 (540c310): шапка ---, ## ID, ### Ответ, «\\»."""
    lines = text.split("\n")
    meta: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            key, sep, value = lines[i].partition(":")
            if sep:
                meta[key.strip()] = value.strip()
            i += 1
        i += 1
    answers: dict[str, str] = {}
    current, buf = None, None

    def flush() -> None:
        if current is not None and buf is not None:
            while buf and not buf[0].strip():
                buf.pop(0)
            while buf and not buf[-1].strip():
                buf.pop()
            if buf:
                answers[current] = "\n".join(buf)

    for line in lines[i:]:
        if line.startswith("## "):
            flush()
            current, buf = line[3:].strip().split(" ")[0], None
        elif current is not None and buf is None and line.strip() == "### Ответ":
            buf = []
        elif buf is not None:
            buf.append(line[1:] if line.startswith("\\") else line)
    flush()
    return {"meta": meta, "answers": answers}


def _html13_questions(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for sec in re.split(r"(?m)^## ", text)[1:]:
        head, _, body = sec.partition("\n")
        quoted = [ln[1:].strip() for ln in body.split("\n### Ответ")[0].split("\n") if ln.startswith(">")]
        out[head.strip().split(" ")[0]] = " ".join(x for x in quoted if x)
    return out


def _split_edits(text: str, *, unescape: bool = False) -> tuple[str, list[tuple[str, str]]]:
    body, edits, _ = _split_answer(text, unescape=unescape)
    return body, edits


def _split_answer(text: str, *, unescape: bool = False) -> tuple[str, list[tuple[str, str]], str]:
    """Текст ответа → (ответ, правки «было → стало», «Формулировка» №08)."""
    keep, edits, wording = [], [], ""
    for line in text.split("\n"):
        m = _EDIT_RE.match(line)
        w = _WORDING_RE.match(line)
        if m:
            edits.append((m.group(1), m.group(2)))
        elif w:
            wording = w.group(1).strip()
        else:
            # №08 (ea5d65d) не снимает экранирование «\#» / «\\» веб-формата и №13 — снимаем здесь.
            keep.append(line[1:] if unescape and line.startswith(("\\#", "\\\\")) else line)
    return "\n".join(keep).strip(), edits, wording


def read_import(data: bytes, *, filename: str = "answers.md") -> Imported:
    """Разобрать загруженный файл ответов любым поддерживаемым форматом (без применения)."""
    text = _normalize(data)
    fmt = detect_format(text)
    shas = declared_shas(text)
    warnings: list[str] = []
    own = parse_answers(text)
    own_by_id = own.by_id()
    questions = {a.qid: a.question for a in own.answers if a.question}

    if fmt == "html13":
        published = _load(HTML13_PARSER)
        if published is not None:
            parsed, parser = published(text), f"№13 {HTML13_PARSER.replace(':', '.')}"
        else:
            parsed, parser = _html13_builtin(text), "веб: встроенный разбор формата №13 (по 540c310)"
        stamp = parsed.get("meta", {}).get("exported_at", "")
        prov = f"черновик аналитика из HTML-отчёта №13 ({filename}{', ' + stamp if stamp else ''})"
        questions = _html13_questions(text)
        answers = []
        for qid, raw in parsed.get("answers", {}).items():
            body, edits, wording = _split_answer(raw)
            answers.append(Answer(qid, body, prov, questions.get(qid, ""), edits, wording))
        meta = dict(parsed.get("meta", {}))
    else:
        target = os.environ.get(P08_PARSER_ENV) or P08_PARSER_DEFAULT
        p08 = _load(target)
        meta = dict(own.meta)
        answers = []
        if p08 is not None:
            try:
                aset = p08(text)
                parser = f"№08 {target.replace(':', '.')}"
                warnings += [str(w) for w in getattr(aset, "warnings", [])]
                for d in aset:
                    qid = str(getattr(d, "question_id", "") or (d.get("question_id") if isinstance(d, dict) else ""))
                    raw = str(getattr(d, "answer", "") or (d.get("answer") if isinstance(d, dict) else "") or "")
                    body, edits, wording = _split_answer(raw, unescape=True)
                    wording = wording or str(getattr(d, "wording", "") or (d.get("wording") if isinstance(d, dict) else "") or "")
                    mine = own_by_id.get(qid)
                    prov = mine.provenance if mine and mine.provenance != ANALYST else f"аналитик (файл {filename})"
                    answers.append(Answer(qid, body, prov, questions.get(qid, ""), edits or (mine.edits if mine else []), wording))
            except Exception as exc:  # №08 не принял файл — встроенный разбор, с пометкой
                p08 = None
                warnings.append(f"№08 не разобрал файл ({type(exc).__name__}: {exc}); использован встроенный разбор")
        if p08 is None:
            parser = "веб: встроенный разбор (bcc_review.web.answers.parse_answers)"
            for a in own.answers:
                prov = a.provenance if a.provenance != ANALYST else f"аналитик (файл {filename})"
                answers.append(Answer(a.qid, a.text, prov, a.question, a.edits, a.wording))
    return Imported(
        format=fmt, parser=parser, declared_sha256=shas[0] if len(shas) == 1 else None, sha_values=shas,
        answers=answers, questions=questions, warnings=warnings,
        file_sha256=hashlib.sha256(data).hexdigest(), meta=meta,
    )
