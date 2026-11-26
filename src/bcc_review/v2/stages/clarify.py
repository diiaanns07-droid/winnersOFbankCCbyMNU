"""Этап clarify (№11): вопросы владельцу документа с вариантами ответа.

Один вызов модели после судьи. Код проверяет то, что нельзя доверить модели:
каждая цитата найдена в документе, у вопроса 2–4 различных варианта без «оставить как есть»,
вопрос ссылается на существующие дефекты, блокирующие идут первыми, вопросов не больше 10.

Вход: ``findings`` (итоговые дефекты судьи, контракт 2.4). Выход: ``{"questions": [...]}``
(контракт 2.5) плюс поля ``topic`` и ``evidence`` (цитаты обеих сторон, сверенные кодом).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

STAGE = "clarify"
MAX_QUESTIONS = 10
OPTION_LETTERS = "ABCD"

ROLES = ("Владелец продукта", "Аналитик", "Архитектор", "ИБ", "Тестирование")
_ROLE_ALIASES = {
    "владелец": "Владелец продукта", "бизнес": "Владелец продукта", "product": "Владелец продукта",
    "продукт": "Владелец продукта", "аналит": "Аналитик", "архитект": "Архитектор", "иб": "ИБ",
    "безопас": "ИБ", "security": "ИБ", "тест": "Тестирование", "qa": "Тестирование",
}
_SEV_RANK = {"critical": 0, "major": 1, "minor": 2}

# Варианты, которые не являются решением: их программа выбрасывает.
_BANNED_OPTION = re.compile(
    r"остав\w*\s+(как\s+есть|без\s+изменени)|на\s+усмотрени|как\s+сочт|по\s+ситуации|решить\s+позже|"
    r"реши\w*\s+(позже|потом)|отлож\w*\s+решени|^друго[ей]\b|^иное\b|^прочее\b|не\s+знаю",
    re.I,
)
_LEADING_LABEL = re.compile(r"^\s*(?:[A-DА-Г]|[1-4])\s*[).:\-—–]\s+", re.I)


def _evidence_schema() -> dict:
    return {"type": "array", "minItems": 1, "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False, "required": ["quote", "line"],
        "properties": {"quote": {"type": "string"}, "line": {"type": "integer"}}}}


SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "maxItems": 14, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "finding_ids", "to", "blocking", "question", "evidence", "options", "why"],
        "properties": {
            "topic": {"type": "string"},
            "finding_ids": {"type": "array", "items": {"type": "string"}},
            "to": {"type": "string", "enum": list(ROLES)},
            "blocking": {"type": "boolean"},
            "question": {"type": "string"},
            "evidence": _evidence_schema(),
            "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
            "why": {"type": "string"},
        }}}},
}


# --------------------------------------------------------------------------- общие помощники (№11)
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"[«»“”„\"'`]", '"', s)
    s = re.sub(r"[—–‑−]", "-", s)
    s = s.replace("**", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _lines(view: Any) -> list[dict]:
    if isinstance(view, dict):
        return list(view.get("lines") or [])
    return list(getattr(view, "lines", None) or [])


def _fallback_verify(view: Any, quote: str, line_hint: int | None) -> dict | None:
    """Запасная сверка цитаты, пока нет ``v2/quotes.py`` (№03): точное и склеенное вхождение."""
    q = _norm(quote)
    if len(q) < 3:
        return None
    lines = _lines(view)
    hits: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        if q in _norm(ln.get("text", "")):
            hits.append((i, i))
    if not hits:
        for i in range(len(lines)):
            for span in (2, 3):
                chunk = lines[i:i + span]
                if len(chunk) == span and q in _norm(" ".join(x.get("text", "") for x in chunk)):
                    hits.append((i, i + span - 1))
                    break
    if not hits:
        return None
    hint = line_hint or 0
    a, b = min(hits, key=lambda h: abs(int(lines[h[0]].get("n", h[0] + 1)) - hint) if hint else 0)
    first, last = lines[a], lines[b]
    return {"line_start": int(first.get("n", a + 1)), "line_end": int(last.get("n", b + 1)),
            "page": first.get("page"), "section": first.get("section", ""), "verified": "exact",
            "text": first.get("text", "")}


def verify_quote(view: Any, quote: str, line_hint: int | None = None, near_lines: Iterable[int] = ()) -> dict | None:
    """Сверка цитаты: общая ``quotes.verify_quote`` (№03), если есть, иначе запасная."""
    try:
        from bcc_review.v2 import quotes  # type: ignore
        m = quotes.verify_quote(view, quote, line_hint=line_hint, near_lines=tuple(near_lines))
        if m is not None:
            return dict(m)
        return None
    except ImportError:
        return _fallback_verify(view, quote, line_hint)
    except Exception:  # noqa: BLE001 — сбой чужого модуля не должен ронять этап
        return _fallback_verify(view, quote, line_hint)


def verified_evidence(view: Any, items: Iterable[dict], near_lines: Iterable[int] = ()) -> list[dict]:
    """Цитаты модели → сверенные кодом (номер строки считает программа); ненайденные отбрасываются."""
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    near = tuple(near_lines)
    for ev in items or []:
        quote = str(ev.get("quote", "")).strip()
        hint = ev.get("line") or ev.get("line_start")
        m = verify_quote(view, quote, line_hint=int(hint) if hint else None, near_lines=near)
        if not m or m.get("verified") == "missing":
            continue
        key = (int(m["line_start"]), _norm(quote))
        if key in seen:
            continue
        seen.add(key)
        out.append({"quote": quote, "line_start": int(m["line_start"]), "line_end": int(m.get("line_end") or m["line_start"]),
                    "page": m.get("page"), "section": m.get("section", ""), "verified": m.get("verified", "exact")})
    return out


def finding_lines(finding: dict) -> list[int]:
    return [int(e["line_start"]) for e in finding.get("evidence", []) if e.get("line_start")]


def format_findings(findings: list[dict], *, full: bool = True) -> str:
    """Компактная таблица дефектов для промпта (цитаты уже сверены кодом)."""
    rows: list[str] = []
    for f in findings:
        head = (f"{f.get('id', '')} | {f.get('severity', '')} | блокирует: {f.get('blocks', 'none')} | "
                f"{', '.join(f.get('requirement_ids', [])) or '—'} | {f.get('title', '')}")
        rows.append(head)
        quotes = "; ".join(f"L{int(e.get('line_start') or e.get('line') or 0):03d} «{e.get('quote', '')}»"
                           for e in f.get("evidence", []))
        if quotes:
            rows.append(f"  цитаты: {quotes}")
        if full:
            for key, label in (("problem", "проблема"), ("scenario", "сценарий"), ("question", "вопрос ревьюера"),
                               ("recommendation", "рекомендация")):
                val = str(f.get(key) or "").strip()
                if val:
                    rows.append(f"  {label}: {val}")
    return "\n".join(rows)


def build_messages(ctx: Any, stage: str, var: str, block: str, marker: str) -> tuple[str, str]:
    """Сообщение к модели через ``ctx.prompt``; если шаблон не подставил блок — вставляем его сами."""
    system, user = ctx.prompt(stage, **{var: block})
    if block and block[:200] not in user:
        idx = user.find(marker)
        user = (user[:idx] + block + "\n\n" + user[idx:]) if idx >= 0 else (user + "\n\n" + block)
    return system, user


def _merge(parts: list) -> dict:
    out: dict = {}
    for part in parts:
        for k, v in (part or {}).items():
            if isinstance(v, list):
                out.setdefault(k, []).extend(v)
            elif k not in out:
                out[k] = v
    return out


def ask_items(ctx: Any, stage: str, items: list, build, schema: dict, max_output_tokens: int = 16000) -> dict:
    """Вызов модели по пакету ``items``: ``ask_split`` каркаса (делит пакет при обрезке), иначе ``ask``."""
    llm = ctx.llm
    if hasattr(llm, "ask_split") and len(items) > 1:
        return llm.ask_split(stage, build, items, schema, _merge, max_output_tokens=max_output_tokens) or {}
    system, user = build(items)
    return llm.ask(stage, system, user, schema, max_output_tokens=max_output_tokens) or {}


def _role(value: str) -> str:
    v = str(value or "").strip()
    if v in ROLES:
        return v
    low = v.lower()
    for key, role in _ROLE_ALIASES.items():
        if key in low:
            return role
    return "Аналитик"


def clean_options(options: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for opt in options or []:
        text = _LEADING_LABEL.sub("", str(opt or "")).strip().rstrip(";")
        if len(text) < 3 or _BANNED_OPTION.search(text) or "<уточнить" in text.lower():
            continue
        key = _norm(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[:4]


def _warn(ctx: Any, msg: str) -> None:
    for target in (getattr(ctx, "warnings", None), getattr(getattr(ctx, "run", None), "warnings", None)):
        if isinstance(target, list):
            target.append(msg)
            return
    w = getattr(ctx, "warn", None)
    if callable(w):
        try:
            w(msg)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- постобработка
def postprocess(raw: dict, findings: list[dict], view: Any, warnings: list[str] | None = None) -> list[dict]:
    """Ответ модели → вопросы контракта: проверки кодом, сортировка, ID Q-01…"""
    warnings = warnings if warnings is not None else []
    by_id = {f.get("id"): f for f in findings}
    kept: list[dict] = []
    seen_keys: list[tuple[str, str]] = []
    for i, q in enumerate(raw.get("questions") or [], 1):
        ids = [x for x in dict.fromkeys(str(x).strip() for x in q.get("finding_ids") or []) if x in by_id]
        text = str(q.get("question", "")).strip()
        if not ids or not text:
            warnings.append(f"clarify: вопрос {i} отброшен — нет связи с дефектами отчёта")
            continue
        near = [n for fid in ids for n in finding_lines(by_id[fid])]
        evidence = verified_evidence(view, q.get("evidence") or [], near)
        if not evidence:  # цитаты модели не найдены — берём цитаты самих дефектов (они уже сверены)
            evidence = [dict(e) for fid in ids for e in by_id[fid].get("evidence", [])
                        if e.get("verified", "exact") != "missing"][:3]
        if not evidence:
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — цитата не найдена в документе")
            continue
        options = clean_options(q.get("options") or [])
        if len(options) < 2:
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — меньше двух проверяемых вариантов")
            continue
        key = (_norm(q.get("topic") or ""), _norm(text))
        if any((key[0] and key[0] == k[0]) or key[1] == k[1] for k in seen_keys):
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — повтор того же решения")
            continue
        seen_keys.append(key)
        sev = [by_id[fid].get("severity", "minor") for fid in ids]
        # блокирующий — только вопрос по critical или по major из «исправить первым» (priority 1–7 судьи)
        if "critical" in sev:
            blocking = True
        else:
            blocking = bool(q.get("blocking")) and any(
                by_id[fid].get("severity") == "major" and 1 <= int(by_id[fid].get("priority") or 0) <= 7
                and by_id[fid].get("blocks", "both") != "none" for fid in ids)
        prio = min((int(by_id[fid].get("priority") or 0) or 99) for fid in ids)
        kept.append({
            "id": "", "topic": str(q.get("topic", "")).strip()[:80], "finding_ids": ids, "to": _role(q.get("to")),
            "blocking": blocking, "question": text, "evidence": evidence[:3], "options": options,
            "why": str(q.get("why", "")).strip(),
            "_rank": (0 if blocking else 1, min(_SEV_RANK.get(s, 2) for s in sev), prio, i),
        })
    kept.sort(key=lambda x: x["_rank"])
    if len(kept) > MAX_QUESTIONS:
        warnings.append(f"clarify: оставлено {MAX_QUESTIONS} вопросов из {len(kept)}")
        kept = kept[:MAX_QUESTIONS]
    for n, q in enumerate(kept, 1):
        q.pop("_rank", None)
        q["id"] = f"Q-{n:02d}"
    return kept


def option_label(index: int) -> str:
    return OPTION_LETTERS[index] if 0 <= index < len(OPTION_LETTERS) else str(index + 1)


# --------------------------------------------------------------------------- этап
def run(ctx: Any, findings: list[dict]) -> dict:
    """Вопросы владельцу по итоговым дефектам. Один вызов модели; без дефектов — без вызова."""
    relevant = [f for f in findings if f.get("severity") in ("critical", "major")] or list(findings)
    if not relevant:
        return {"questions": []}
    def build(items: list) -> tuple[str, str]:
        return build_messages(ctx, STAGE, "findings", format_findings(items), "Задание: вопросы владельцу")

    warnings: list[str] = []
    try:
        raw = ask_items(ctx, STAGE, relevant, build, SCHEMA, max_output_tokens=12000)
    except Exception as exc:  # noqa: BLE001 — вопросы не должны ронять весь прогон
        _warn(ctx, f"clarify: модель не ответила ({type(exc).__name__}: {str(exc)[:200]}); вопросы не сформированы")
        return {"questions": [], "status": "failed"}
    questions = postprocess(raw or {}, findings, ctx.view, warnings)
    for w in warnings:
        _warn(ctx, w)
    return {"questions": questions}
