"""Этап recheck (№11): ответы владельца → пересмотр дефектов → второй вердикт «до / после».

Формат ответов (``--answers answers.md|json``):

* Markdown: строки ``Q-01: B``, ``Q-01: B — комментарий``, ``Q-01: свой текст``,
  ``Q-02 [тема вопроса]: свой текст``; строки без номера в разделе «Решения» (``- …``) — общие решения
  владельца. Буквы вариантов — латинские A–D; кириллические А, В, С читаются как A, B, C, Б как B, Г как D;
  цифры 1–4 — номер варианта. ``Q-03: ?`` или пустое значение — «нет ответа». Строки ``#`` и ``>`` — комментарии.
* JSON: ``{"Q-01": "B"}``, ``{"answers": {"Q-01": "B"}}``, ``[{"id": "Q-01", "answer": "B"}]``,
  ``{"Q-01": {"choice": "B", "comment": "…"}}``, ``{"decisions": ["…"]}``.

Номера вопросов от прогона к прогону могут меняться, поэтому ответ можно привязать к теме: если тема в
скобках не совпадает с темой вопроса под этим номером, программа ищет вопрос с подходящей темой.

Честность кода: дефект может стать ``resolved`` только если на связанный вопрос дан содержательный ответ
(или есть общее решение владельца). Новые конфликты, порождённые ответами, идут кандидатами через судью.
Вердикт до и после считает одно и то же правило кода (контракт, раздел 5).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from bcc_review.v2.stages import clarify as _cl

STAGE = "recheck"
STATUSES = ("resolved", "open", "changed")
SEVERITIES = ("critical", "major", "minor")

_KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
          "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
          "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
          "security", "ops_risk", "other"]
_CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
             "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
             "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]


def _candidate_schema() -> dict:
    try:  # общая схема кандидата из каркаса (№01), если есть
        from bcc_review.v2 import types as _t  # type: ignore
        for name in ("CANDIDATE_SCHEMA", "CANDIDATE"):
            sch = getattr(_t, name, None)
            if isinstance(sch, dict) and sch.get("properties", {}).get("evidence"):
                return sch
    except Exception:  # noqa: BLE001
        pass
    s = {"type": "string"}
    return {"type": "object", "additionalProperties": False, "properties": {
        "title": s, "kind": {"type": "string", "enum": _KINDS}, "criterion": {"type": "string", "enum": _CRITERIA},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "requirement_ids": {"type": "array", "items": s},
        "evidence": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": ["quote", "line"],
                                                "properties": {"quote": s, "line": {"type": "integer"}}}},
        "problem": s, "scenario": s, "impact": s, "recommendation": s, "rewrite": s, "question": s,
        "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]}},
        "required": ["title", "kind", "criterion", "severity", "requirement_ids", "evidence", "problem", "scenario",
                     "impact", "recommendation", "rewrite", "question", "blocks"]}


SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["decisions", "candidates"],
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["finding_id", "status", "by", "conflicting_answers", "reason", "severity", "title",
                         "problem"],
            "properties": {
                "finding_id": {"type": "string"},
                "status": {"type": "string", "enum": list(STATUSES)},
                "by": {"type": "array", "items": {"type": "string"}},
                "conflicting_answers": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "severity": {"type": "string", "enum": list(SEVERITIES)},
                "title": {"type": "string"},
                "problem": {"type": "string"},
            }}},
        "candidates": {"type": "array", "maxItems": 8, "items": _candidate_schema()},
    },
}

# --------------------------------------------------------------------------- разбор ответов
_LETTER = {"A": 0, "B": 1, "C": 2, "D": 3, "А": 0, "В": 1, "С": 2, "Б": 1, "Г": 3,
           "1": 0, "2": 1, "3": 2, "4": 3}
_QLINE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*(Q\s*-?\s*\d{1,3})\s*(?:\*\*|__)?\s*"
    r"(?:[\[(]([^\])]{1,120})[\])])?\s*(?:\*\*|__)?\s*[:：=—–-]\s*(.*)$", re.I)
_CHOICE = re.compile(r"^\s*(?:\*\*)?([A-DА-ГABCDС1-4])(?:\*\*)?\s*(?:$|[).,;:—–-]\s*(.*)$|\s+[—–-]\s*(.*)$)", re.I)
_NO_ANSWER = re.compile(r"^\s*(?:\?+|-+|—|нет ответа|не знаю|tbd|todo|позже|потом|обсудим\b.*)\s*$", re.I)
_VAGUE = re.compile(r"\b(как обычно|по ситуации|на усмотрение|решим позже|обсудим позже|уточним позже)\b", re.I)
_DECISION_HEAD = re.compile(r"^\s*#{1,6}\s*(решени|общие решени|дополнительн)", re.I)


def _qid(raw: str) -> str:
    num = re.sub(r"\D", "", raw)
    return f"Q-{int(num):02d}" if num else ""


def _parse_value(value: str) -> dict:
    value = str(value or "").strip()
    if not value or _NO_ANSWER.match(value):
        return {"choice": None, "text": "", "comment": ""}
    m = _CHOICE.match(value)
    if m:
        letter = m.group(1).upper()
        rest = (m.group(2) or m.group(3) or "").strip()
        return {"choice": _LETTER.get(letter), "text": "", "comment": rest}
    return {"choice": None, "text": value, "comment": ""}


def parse_answers_text(text: str) -> dict:
    """Markdown/текст → ``{"answers": [{"id","topic_hint","choice","text","comment"}], "decisions": [str]}``."""
    answers: list[dict] = []
    decisions: list[str] = []
    in_decisions = False
    current: dict | None = None
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        if line.lstrip().startswith("#"):
            in_decisions = bool(_DECISION_HEAD.match(line))
            current = None
            continue
        if line.lstrip().startswith(">") or line.lstrip().startswith("<!--"):
            continue
        m = _QLINE.match(line)
        if m and _qid(m.group(1)):
            entry = {"id": _qid(m.group(1)), "topic_hint": (m.group(2) or "").strip(), **_parse_value(m.group(3))}
            answers.append(entry)
            current = entry if entry["choice"] is None and entry["text"] else None
            continue
        stripped = re.sub(r"^\s*[-*+]\s+", "", line).strip()
        if in_decisions and stripped:
            decisions.append(stripped)
            continue
        if current is not None and raw[:1].isspace():  # продолжение своего ответа с отступом
            current["text"] = (current["text"] + " " + stripped).strip()
    return {"answers": answers, "decisions": decisions}


def parse_answers_json(data: Any) -> dict:
    answers: list[dict] = []
    decisions: list[str] = []

    def add(qid: str, val: Any) -> None:
        if isinstance(val, dict):
            choice = val.get("choice", val.get("option"))
            text = str(val.get("text") or val.get("answer") or "")
            comment = str(val.get("comment") or "")
            topic = str(val.get("topic") or "")
            parsed = _parse_value(str(choice)) if choice not in (None, "") else _parse_value(text)
            if choice not in (None, "") and text and parsed["choice"] is not None:
                comment = (comment + " " + text).strip()
            answers.append({"id": _qid(qid), "topic_hint": topic, "choice": parsed["choice"],
                            "text": parsed["text"], "comment": (parsed["comment"] + " " + comment).strip()})
        else:
            answers.append({"id": _qid(qid), "topic_hint": "", **_parse_value(str(val))})

    if isinstance(data, dict):
        decisions = [str(x) for x in data.get("decisions") or [] if str(x).strip()]
        body = data.get("answers", data)
        if isinstance(body, dict):
            for k, v in body.items():
                if _qid(str(k)) and str(k).upper().startswith("Q"):
                    add(str(k), v)
        elif isinstance(body, list):
            data = body
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (item.get("id") or item.get("question_id")):
                add(str(item.get("id") or item.get("question_id")), item)
    return {"answers": [a for a in answers if a["id"]], "decisions": decisions}


def load_answers(source: Any) -> dict:
    """Путь к ``answers.md|json``, строка с текстом ответов или уже разобранный объект."""
    if isinstance(source, (dict, list)):
        return parse_answers_json(source)
    s = str(source or "")
    p = Path(s) if len(s) < 4096 and "\n" not in s else None
    if p is not None and p.exists():
        text = p.read_text(encoding="utf-8-sig")
        if p.suffix.lower() == ".json":
            return parse_answers_json(json.loads(text))
    else:
        text = s
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            return parse_answers_json(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    return parse_answers_text(text)


_STOP = {"при", "для", "или", "как", "что", "это", "его", "она", "они", "все", "без", "над", "под", "про", "чем",
         "так", "уже", "ещё", "еще", "тот", "эти", "той", "том", "кто", "где", "the", "and", "какие", "какой", "каком",
         "какая", "есть", "быть", "если", "либо", "также"}


def _tokens(s: str) -> set[str]:
    """Грубые основы слов: окончания русских падежей не мешают совпадению («сумме» ~ «суммы»)."""
    words = [w for w in re.findall(r"[a-zа-яё0-9]{3,}", _cl._norm(s)) if w not in _STOP]
    return {w if len(w) <= 4 else w[:min(6, max(4, len(w) - 2))] for w in words}


def _text_score(text: str, q: dict) -> float:
    """Доля слов темы и вопроса, встречающихся в самом ответе."""
    a = _tokens(text)
    b = _tokens(f"{q.get('topic', '')} {q.get('question', '')}")
    return len(a & b) / max(1, len(b)) if a and b else 0.0


def _topic_score(hint: str, q: dict) -> float:
    """Доля слов подсказки в теме (вес 2) и в тексте вопроса (вес 1)."""
    h = _tokens(hint)
    if not h:
        return 0.0
    topic, text = _tokens(q.get("topic", "")), _tokens(q.get("question", ""))
    return (2 * len(h & topic) + len((h & text) - topic)) / (2 * len(h))


def resolve_answers(questions: list[dict], parsed: dict, warnings: list[str] | None = None) -> dict:
    """Ответы → решения по вопросам этого прогона. Возвращает ``answered``, ``unanswered``, ``decisions``."""
    warnings = warnings if warnings is not None else []
    by_id = {q["id"]: q for q in questions}
    answered: dict[str, dict] = {}
    extra: list[str] = list(parsed.get("decisions") or [])
    entries = list(parsed.get("answers") or [])
    # номера вопросов от прогона к прогону меняются: ответ с темой в скобках привязывается по теме.
    # Сопоставление глобальное: сначала самые уверенные пары «ответ — вопрос», каждый вопрос — одному ответу.
    bound: dict[int, dict | None] = {}
    pairs = []
    for k, a in enumerate(entries):
        hint = a.get("topic_hint") or ""
        if not hint:
            continue
        for x in questions:
            sc = _topic_score(hint, x) + 0.25 * _text_score(a.get("text", ""), x) + (0.01 if x["id"] == a["id"] else 0)
            pairs.append((sc, k, x["id"]))
    taken: set[str] = set()
    for sc, k, qid in sorted(pairs, key=lambda t: -t[0]):
        if sc < 0.4 or k in bound or qid in taken:
            continue
        bound[k] = by_id[qid]
        taken.add(qid)
    for k, a in enumerate(entries):
        hint = a.get("topic_hint") or ""
        q = by_id.get(a["id"])
        if hint:
            if k in bound:
                if q is None or bound[k]["id"] != q["id"]:
                    warnings.append(f"recheck: ответ {a['id']} [{hint}] отнесён к {bound[k]['id']} по теме")
                q = bound[k]
            elif a.get("choice") is None and a.get("text"):
                q = None  # тема не совпала однозначно ни с одним вопросом — это общее решение
            elif q is not None and q["id"] in taken:
                q = None
        if q is None:
            if a.get("text"):
                extra.append(a["text"] + (f" ({hint})" if hint else ""))
                why = "тема не совпала ни с одним вопросом прогона" if hint else "такого вопроса нет в прогоне"
                warnings.append(f"recheck: {a['id']}: {why} — ответ учтён как общее решение")
            else:
                warnings.append(f"recheck: {a['id']} нет среди вопросов прогона — ответ пропущен")
            continue
        if a.get("choice") is not None:
            opts = q.get("options") or []
            if a["choice"] >= len(opts):
                warnings.append(f"recheck: у {q['id']} нет варианта {_cl.option_label(a['choice'])} — ответ пропущен")
                continue
            text = opts[a["choice"]]
            label = _cl.option_label(a["choice"])
        else:
            text, label = a.get("text", ""), ""
        if not text or _VAGUE.search(text) or len(text) < 3:
            warnings.append(f"recheck: ответ на {q['id']} не задаёт правила — вопрос остаётся открытым")
            continue
        comment = a.get("comment") or ""
        if q["id"] in answered:  # второй ответ на тот же вопрос дополняет первый
            prev = answered[q["id"]]
            prev["answer"] = prev["answer"] + "; " + text + (f" ({comment})" if comment else "")
            prev["choice"] = prev["choice"] if prev["choice"] == label else ""
            continue
        answered[q["id"]] = {"question_id": q["id"], "topic": q.get("topic", ""), "question": q.get("question", ""),
                             "choice": label, "answer": text + (f" ({comment})" if comment else ""),
                             "finding_ids": list(q.get("finding_ids") or [])}
    unanswered = [q["id"] for q in questions if q["id"] not in answered]
    return {"answered": list(answered.values()), "unanswered": unanswered, "decisions": extra}


# --------------------------------------------------------------------------- вердикт
def severity_counts(findings: Iterable[dict]) -> dict:
    out = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        if f.get("severity") in out:
            out[f["severity"]] += 1
    return out


def verdict_rule(findings: list[dict], run_status: str = "complete") -> dict:
    """Правило вердикта из контракта (раздел 5). Используется и для «до», и для «после»."""
    if run_status == "failed":
        return {"development": "", "testing": "", "fix_first": []}

    def direction(d: str) -> str:
        crit = [f for f in findings if f.get("severity") == "critical" and f.get("blocks") in (d, "both")]
        if crit:
            return "no"
        majors = [f for f in findings if f.get("severity") == "major" and f.get("blocks") in (d, "both")]
        res = "conditional" if len(majors) >= 3 else "yes"
        if run_status == "partial" and res == "yes":
            res = "conditional"
        return res

    order = sorted((f for f in findings if f.get("severity") in ("critical", "major")),
                   key=lambda f: (int(f.get("priority") or 0) or 99, SEVERITIES.index(f.get("severity", "minor"))))
    return {"development": direction("development"), "testing": direction("testing"),
            "fix_first": [f["id"] for f in order[:7] if f.get("id")]}


def shared_verdict(findings: list[dict], run_status: str = "complete") -> dict:
    """Вердикт по общему правилу каркаса, если оно есть; иначе по ``verdict_rule``."""
    for mod_name, fn_name in (("bcc_review.v2.verdict", "compute"), ("bcc_review.v2.pipeline", "compute_verdict"),
                              ("bcc_review.v2.pipeline", "verdict_rule")):
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                v = fn(findings, run_status)
                if isinstance(v, dict) and "development" in v:
                    return v
        except Exception:  # noqa: BLE001
            continue
    return verdict_rule(findings, run_status)


# --------------------------------------------------------------------------- этап
def _format_answers(resolved: dict) -> str:
    rows = []
    for a in resolved["answered"]:
        label = f"вариант {a['choice']}: " if a["choice"] else "свой ответ: "
        rows.append(f"{a['question_id']} ({a['topic']}) → дефекты {', '.join(a['finding_ids'])}\n"
                    f"  вопрос: {a['question']}\n  ответ, {label}{a['answer']}")
    for i, d in enumerate(resolved["decisions"], 1):
        rows.append(f"Решение-{i} (общее решение владельца, без номера вопроса): {d}")
    return "\n".join(rows) or "—"


def answer_labels(resolved: dict) -> set[str]:
    """ID ответов, на которые модель может сослаться в ``by``: Q-… с ответом и Решение-1…N."""
    return {a["question_id"] for a in resolved["answered"]} | \
        {f"Решение-{i}" for i in range(1, len(resolved["decisions"]) + 1)}


_LABEL = re.compile(r"(Q\s*-?\s*\d{1,3})|(Решени\w*\s*-?\s*\d{1,3})", re.I)


def norm_labels(items: Iterable[str], valid: set[str]) -> list[str]:
    """«q-3», «Q-03», «решение 2» → «Q-03», «Решение-2»; только существующие ответы."""
    out: list[str] = []
    for raw in items or []:
        for m in _LABEL.finditer(str(raw)):
            num = re.sub(r"\D", "", m.group(2) or "")
            lab = _qid(m.group(1)) if m.group(1) else ("Решение-" + str(int(num)) if num else "")
            if lab in valid and lab not in out:
                out.append(lab)
    return out


def _next_candidate_number(report: dict | None, findings: list[dict]) -> int:
    nums = [0]
    pools = list(findings) + list((report or {}).get("rejected") or [])
    for item in pools:
        for cid in list(item.get("candidate_ids") or []) + [item.get("candidate_id") or "", item.get("id") or ""]:
            m = re.match(r"C-(\d+)$", str(cid))
            if m:
                nums.append(int(m.group(1)))
    return max(nums) + 1


def run(ctx: Any, findings: list[dict], answers: Any, questions: list[dict] | None = None,
        report: dict | None = None) -> dict:
    """Пересмотр дефектов по ответам (контракт: ``{"findings": [...], "new_candidates": [...]}``).

    ``findings`` в ответе — все дефекты «до» с полем ``recheck`` (status, reason, severity_after…);
    ``new_candidates`` — сверенные кодом кандидаты новых конфликтов (их судит ``judge``).
    """
    questions = list(questions if questions is not None else (report or {}).get("questions") or [])
    warnings: list[str] = []
    parsed = answers if isinstance(answers, dict) and "answers" in answers and isinstance(answers.get("answers"), list) \
        else load_answers(answers)
    resolved = resolve_answers(questions, parsed, warnings)
    q_by_finding: dict[str, list[str]] = {}
    for a in resolved["answered"]:
        for fid in a["finding_ids"]:
            q_by_finding.setdefault(fid, []).append(a["question_id"])
    affected_ids = set(q_by_finding)
    if resolved["decisions"]:  # общее решение может касаться любого существенного дефекта
        affected_ids |= {f["id"] for f in findings if f.get("severity") in ("critical", "major")}
    affected = [f for f in findings if f.get("id") in affected_ids]
    others = [f for f in findings if f.get("id") not in affected_ids]

    out_findings = []
    for f in findings:
        g = dict(f)
        g["recheck"] = {"status": "open", "reason": "", "question_ids": q_by_finding.get(f.get("id"), []),
                        "severity_before": f.get("severity"), "severity_after": f.get("severity"),
                        "affected": f.get("id") in affected_ids}
        out_findings.append(g)
    result = {"findings": out_findings, "new_candidates": [], "rejected": [], "answers": resolved, "warnings": warnings}
    if not affected:
        for g in out_findings:
            g["recheck"]["reason"] = "ответа на связанный вопрос нет" if not resolved["answered"] else ""
        return _finish(ctx, result)

    block = _format_answers(resolved)
    others_block = _cl.format_findings(others, full=False) or "—"

    def build(items: list) -> tuple[str, str]:
        fb = _cl.format_findings(items)
        system, user = ctx.prompt(STAGE, answers=block, findings=fb, others=others_block)
        if block[:200] not in user:  # шаблон не подставил переменные — вставляем блоки сами
            extra = (f"<ответы>\n{block}\n</ответы>\n\n<затронутые_дефекты>\n{fb}\n</затронутые_дефекты>\n\n"
                     f"<остальные_дефекты>\n{others_block}\n</остальные_дефекты>")
            idx = user.find("Задание: пересмотр")
            user = (user[:idx] + extra + "\n\n" + user[idx:]) if idx >= 0 else (user + "\n\n" + extra)
        return system, user

    try:
        raw = _cl.ask_items(ctx, STAGE, affected, build, SCHEMA, max_output_tokens=32000)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"recheck: модель не ответила ({type(exc).__name__}: {str(exc)[:200]}); дефекты оставлены открытыми")
        for g in out_findings:
            if g["recheck"]["affected"]:
                g["recheck"]["reason"] = "пересмотр не выполнен: модель не ответила"
        result["status"] = "failed"
        return _finish(ctx, result)

    by_id = {g["id"]: g for g in out_findings}
    valid = answer_labels(resolved)
    for d in raw.get("decisions") or []:
        g = by_id.get(str(d.get("finding_id", "")).strip())
        if g is None or not g["recheck"]["affected"]:
            continue
        status = d.get("status") if d.get("status") in STATUSES else "open"
        rc = g["recheck"]
        rc["status"], rc["reason"] = status, str(d.get("reason", "")).strip()
        # два ответа противоречат друг другу — дефект остаётся открытым, владелец выбирает один ответ
        clash = norm_labels(list(d.get("conflicting_answers") or []), valid)
        if len(clash) >= 2:
            rc["answer_conflict"] = clash
            if status != "open":
                rc["status"], status = "open", "open"
                rc["reason"] = (f"ответы {' и '.join(clash)} противоречат друг другу: " + rc["reason"]).strip(": ")
        # дефект снимает только ответ, который модель назвала прямо (в by или в тексте причины)
        by = norm_labels(list(d.get("by") or []), valid) if status != "open" else []
        if status != "open" and not by:
            by = norm_labels([rc["reason"]], valid)
        if status != "open" and not by:
            rc["status"], status = "open", "open"
            rc["reason"] = ("не назван ответ, который снимает дефект: " + rc["reason"]).strip(": ")
        if by:
            rc["answer_ids"] = by
            closing = [x for x in by if x.startswith("Q-")]
            rc["linked_question_ids"] = list(rc["question_ids"])
            rc["question_ids"] = closing
        if status == "changed":
            sev = d.get("severity") if d.get("severity") in SEVERITIES else g.get("severity")
            rc["severity_after"] = sev
            if str(d.get("title", "")).strip():
                rc["title_after"] = str(d["title"]).strip()
            if str(d.get("problem", "")).strip():
                rc["problem_after"] = str(d["problem"]).strip()
        elif status == "resolved":
            rc["severity_after"] = ""
    for g in out_findings:
        if g["recheck"]["affected"] and not g["recheck"]["reason"]:
            g["recheck"]["reason"] = "модель не оценила дефект — оставлен открытым"

    n = _next_candidate_number(report, findings)
    for c in raw.get("candidates") or []:
        lines = [x for f in affected for x in _cl.finding_lines(f)]
        ev = _cl.verified_evidence(ctx.view, c.get("evidence") or [], lines)
        cand = dict(c)
        cand["id"] = f"C-{n:03d}"
        cand["source"] = "recheck"
        n += 1
        if not ev:
            result["rejected"].append({"candidate_id": cand["id"], "title": cand.get("title", ""),
                                       "reason": "цитата не найдена", "source": "recheck"})
            continue
        twin = duplicate_of(ev, findings, str(cand.get("title", "")))
        if twin:  # прежний дефект модель описала заново — это не новый конфликт от ответа
            result["rejected"].append({"candidate_id": cand["id"], "title": cand.get("title", ""),
                                       "reason": f"повторяет дефект {twin}", "source": "recheck"})
            continue
        cand["evidence"] = ev
        cand["line_start"], cand["line_end"] = ev[0]["line_start"], ev[0]["line_end"]
        result["new_candidates"].append(cand)
    return _finish(ctx, result)


def duplicate_of(evidence: list[dict], findings: list[dict], title: str = "", slack: int = 1) -> str:
    """ID прежнего дефекта, который новый кандидат описывает заново, иначе пустая строка.

    Новый конфликт от ответа цитирует место, которое теперь противоречит ответу. Если все его цитаты —
    строки одного прежнего дефекта (±``slack``), это тот же дефект (закрытый ответом или оставшийся открытым):
    для двух и более строк хватает совпадения строк, для одной строки нужна ещё та же суть в заголовке."""
    cand = {int(e["line_start"]) for e in evidence if e.get("line_start")}
    if not cand:
        return ""
    words = _tokens(_cl.plain_text(title))
    for f in findings:
        own = {int(x) for x in _cl.finding_lines(f)}
        if not own or not all(any(abs(c - o) <= slack for o in own) for c in cand):
            continue
        if len(cand) >= 2:
            return str(f.get("id", ""))
        theirs = _tokens(f"{f.get('title', '')} {f.get('problem', '')}")
        if words and len(words & theirs) / len(words) >= 0.4:
            return str(f.get("id", ""))
    return ""


def _finish(ctx: Any, result: dict) -> dict:
    for w in result.get("warnings", []):
        _cl._warn(ctx, w)
    return result


def findings_after(rechecked: list[dict]) -> list[dict]:
    """Дефекты, которые остаются после ответов: без resolved, changed — с новой серьёзностью и текстом."""
    out = []
    for g in rechecked:
        rc = g.get("recheck") or {}
        if rc.get("status") == "resolved":
            continue
        h = {k: v for k, v in g.items() if k != "recheck"}
        if rc.get("status") == "changed":
            h["severity"] = rc.get("severity_after") or h.get("severity")
            h["title"] = rc.get("title_after") or h.get("title")
            h["problem"] = rc.get("problem_after") or h.get("problem")
        h["status_after_answers"] = rc.get("status", "open")
        out.append(h)
    return out


def _judge_new(ctx: Any, candidates: list[dict], start_n: int, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    """Новые кандидаты → судья (№10). Без судьи — кандидат становится дефектом как есть."""
    if not candidates:
        return [], []
    try:
        from bcc_review.v2.stages import judge  # type: ignore
        res = judge.run(ctx, candidates) or {}
        found, rejected = list(res.get("findings") or []), list(res.get("rejected") or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"recheck: судья недоступен для новых кандидатов ({type(exc).__name__}); приняты как есть")
        found = [{"id": "", "candidate_ids": [c["id"]], "title": c.get("title", ""), "kind": c.get("kind", "other"),
                  "criterion": c.get("criterion", "set_consistent"), "standard_refs": [],
                  "severity": c.get("severity", "major"), "requirement_ids": c.get("requirement_ids", []),
                  "evidence": c.get("evidence", []), "problem": c.get("problem", ""), "scenario": c.get("scenario", ""),
                  "impact": c.get("impact", ""), "recommendation": c.get("recommendation", ""),
                  "rewrite": c.get("rewrite", ""), "question": c.get("question", ""), "blocks": c.get("blocks", "both"),
                  "priority": 0, "sources": ["recheck"]} for c in candidates]
        rejected = []
    keep = _cl.doc_codes(getattr(ctx, "view", None))
    for i, f in enumerate(found):
        for key in ("title", "problem", "scenario", "impact", "recommendation", "question"):
            if isinstance(f.get(key), str):
                f[key] = _cl.plain_text(f[key], keep)
        f["id"] = f"D-{start_n + i:02d}"
        f.setdefault("sources", ["recheck"])
        if "recheck" not in f["sources"]:
            f["sources"] = list(f["sources"]) + ["recheck"]
        f["status_after_answers"] = "new"
    return found, rejected


def apply_answers(ctx: Any, report: dict, answers: Any) -> dict:
    """Весь режим ``--answers`` одним вызовом для pipeline (№01).

    Принимает собранный отчёт (``findings``, ``questions``, ``verdict``, ``run.status``) и ответы.
    Возвращает ``{"clarification": {...}, "findings_after": [...], "rejected_after": [...]}``;
    ``clarification`` кладётся в ``report.json`` как есть и рендерится таблицей «до / после».
    """
    findings = list(report.get("findings") or [])
    status = (report.get("run") or {}).get("status", "complete")
    rc = run(ctx, findings, answers, report.get("questions") or [], report)
    warnings = rc.get("warnings", [])
    remaining = findings_after(rc["findings"])
    max_d = max([int(m.group(1)) for f in findings for m in [re.match(r"D-(\d+)$", str(f.get("id", "")))] if m] or [0])
    new_found, new_rejected = _judge_new(ctx, rc["new_candidates"], max_d + 1, warnings)
    after = remaining + new_found
    before_v = report.get("verdict") or {}
    before_rule = shared_verdict(findings, status)
    v_before = {"development": before_v.get("development") or before_rule["development"],
                "testing": before_v.get("testing") or before_rule["testing"]}
    after_rule = shared_verdict(after, "partial" if rc.get("status") == "failed" and status == "complete" else status)
    changes = []
    for g in rc["findings"]:
        r = g["recheck"]
        if not r.get("affected"):
            continue
        changes.append({"finding_id": g["id"], "title": g.get("title", ""), "severity_before": r["severity_before"],
                        "status": r["status"], "severity_after": r["severity_after"], "reason": r["reason"],
                        "question_ids": r["question_ids"], "answer_ids": r.get("answer_ids", []),
                        "answer_conflict": r.get("answer_conflict", []),
                        "title_after": r.get("title_after", "")})
    order = {"resolved": 0, "changed": 1, "open": 2}
    changes.sort(key=lambda c: (order.get(c["status"], 3), SEVERITIES.index(c["severity_before"] or "minor")))
    # вопрос без прямого ответа, все дефекты которого сняты общими решениями, — не «без ответа»
    status_by_id = {c["finding_id"]: c["status"] for c in changes}
    q_by_id = {q.get("id"): q for q in report.get("questions") or []}
    closed = [qid for qid in rc["answers"]["unanswered"]
              if rc["answers"]["decisions"] and q_by_id.get(qid, {}).get("finding_ids")
              and all(status_by_id.get(fid) == "resolved" for fid in q_by_id[qid]["finding_ids"])]
    clar = {
        "answers": rc["answers"]["answered"],
        "decisions": rc["answers"]["decisions"],
        "unanswered": [q for q in rc["answers"]["unanswered"] if q not in closed],
        "closed_by_decisions": closed,
        "changes": changes,
        "new_findings": [f["id"] for f in new_found],
        "answer_conflicts": [{"finding_id": c["finding_id"], "answers": c["answer_conflict"], "reason": c["reason"]}
                             for c in changes if c.get("answer_conflict")],
        "before": {"verdict": v_before, "findings": severity_counts(findings)},
        "after": {"verdict": {"development": after_rule["development"], "testing": after_rule["testing"],
                              "fix_first": after_rule.get("fix_first", [])},
                  "findings": severity_counts(after)},
        "resolved": sum(1 for c in changes if c["status"] == "resolved"),
        "changed": sum(1 for c in changes if c["status"] == "changed"),
        "open": sum(1 for c in changes if c["status"] == "open"),
        "warnings": warnings,
        "status": rc.get("status", "ok"),
    }
    return {"clarification": clar, "findings_after": after,
            "rejected_after": list(rc.get("rejected") or []) + new_rejected}


# --------------------------------------------------------------------------- Markdown-раздел (для №13)
_V = {"no": "нельзя", "conditional": "можно с условиями", "yes": "можно", "": "—"}
_S = {"critical": "критичный", "major": "существенный", "minor": "незначительный", "": "—"}
_ST = {"resolved": "закрыт", "changed": "изменён", "open": "открыт", "new": "новый"}


def render_markdown(clar: dict, findings_after: list[dict] | None = None) -> str:
    """Раздел отчёта «Уточнение: до и после» (№13 может вставить как есть или нарисовать сам)."""
    b, a = clar["before"], clar["after"]
    lines = ["## Уточнение: до и после ответов владельца", "",
             f"Ответов на вопросы: {len(clar['answers'])}, общих решений: {len(clar['decisions'])}, "
             f"закрыто общими решениями: {len(clar.get('closed_by_decisions') or [])}, "
             f"без ответа: {len(clar['unanswered'])}. Оценка «после» предполагает, что ответы внесены в документ "
             f"(см. исправленную редакцию).", "",
             "| Показатель | До уточнения | После уточнения |", "| :--- | :--- | :--- |",
             f"| Начинать разработку | {_V.get(b['verdict'].get('development', ''), '—')} | "
             f"{_V.get(a['verdict'].get('development', ''), '—')} |",
             f"| Начинать тестирование | {_V.get(b['verdict'].get('testing', ''), '—')} | "
             f"{_V.get(a['verdict'].get('testing', ''), '—')} |"]
    for sev in SEVERITIES:
        lines.append(f"| Дефекты: {_S[sev]} | {b['findings'][sev]} | {a['findings'][sev]} |")
    lines += ["", f"Закрыто: {clar['resolved']}, изменено: {clar['changed']}, осталось открытыми: {clar['open']}, "
                  f"новых конфликтов из-за ответов: {len(clar['new_findings'])}.", ""]
    if clar["changes"]:
        lines += ["| Дефект | Было | Статус | Стало | Почему | Ответ |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
        for c in clar["changes"]:
            reason = c["reason"].replace("|", "/").replace("\n", " ")
            lines.append(f"| {c['finding_id']} {c['title'].replace('|', '/')} | {_S.get(c['severity_before'], '—')} | "
                         f"{_ST.get(c['status'], c['status'])} | {_S.get(c['severity_after'] or '', '—')} | {reason} | "
                         f"{', '.join(c['question_ids']) or 'общее решение'} |")
        lines.append("")
    if clar.get("answer_conflicts"):
        lines.append("Ответы, которые противоречат друг другу (выберите один):")
        for c in clar["answer_conflicts"]:
            lines.append(f"* {' ↔ '.join(c['answers'])} — {c['finding_id']}: {c['reason']}")
        lines.append("")
    if clar["new_findings"] and findings_after:
        by_id = {f["id"]: f for f in findings_after}
        lines.append("Новые конфликты, которые порождают ответы:")
        for fid in clar["new_findings"]:
            f = by_id.get(fid, {})
            ev = "; ".join(f"строка {e['line_start']}: «{e['quote']}»" for e in f.get("evidence", []))
            lines.append(f"* **{fid}** ({_S.get(f.get('severity', ''), '—')}) {f.get('title', '')}. {ev}")
        lines.append("")
    return "\n".join(lines)
