"""Этап clarify (№11): вопросы владельцу документа с вариантами ответа.

Один вызов модели: после судьи (``run``) или параллельно с ним по сверенным кандидатам (``start`` →
``finish``). Код проверяет то, что нельзя доверить модели: каждая цитата найдена в документе, у вопроса
2–4 различных варианта без «оставить как есть», вопрос закрывает существующие critical/major-дефекты,
блокирующий — только вопрос по critical, блокирующие идут первыми, вопросов не больше 8 (5 без critical),
в текстах для владельца нет внутренних кодов отчёта.

Вход: ``findings`` (итоговые дефекты судьи, контракт 2.4). Выход: ``{"questions": [...]}``
(контракт 2.5) плюс поля ``topic`` и ``evidence`` (цитаты обеих сторон, сверенные кодом).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

STAGE = "clarify"
# меньше, но точнее: каждый вопрос закрывает critical или major; без critical хватает пяти главных решений
MAX_QUESTIONS = 8
MAX_QUESTIONS_NO_CRITICAL = 5
# лимит вывода с запасом: модели с рассуждением (haiku, Gemini Flash) тратят на него до 3/4 ответа
OUTPUT_TOKENS = 24000
OPTION_LETTERS = "ABCD"

ROLES = ("Владелец продукта", "Аналитик", "Архитектор", "ИБ", "Тестирование")
_ROLE_ALIASES = {
    "владелец": "Владелец продукта", "бизнес": "Владелец продукта", "product": "Владелец продукта",
    "продукт": "Владелец продукта", "аналит": "Аналитик", "архитект": "Архитектор", "иб": "ИБ",
    "безопас": "ИБ", "security": "ИБ", "тест": "Тестирование", "qa": "Тестирование",
}
_SEV_RANK = {"critical": 0, "major": 1, "minor": 2}
# оформление не требует решения владельца: по таким дефектам вопросов нет
FORMAT_KINDS = {"placeholder", "traceability", "terminology", "non_singular", "duplicate"}
FORMAT_CRITERIA = {"conforming", "ranked", "modifiable", "traceable"}
CONFLICT_KINDS = {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
                  "api_contract"}


# внутренние коды отчёта в тексте для владельца: «L038», «(D-03, D-07)», «R-12», «C-014», «lens:qa»
_CODE_PAREN = re.compile(r"\s*\((?:\s*(?:строк[аиеу]\s*)?(?:L\d{1,4}|[DRCQT]-\d{1,3})(?:\s*[-–—]\s*L?\d{1,4})?\s*[,;]?)+\)")
_CODE_LINE = re.compile(r"\b(?:(строк\w*)\s+)?L0*(\d{1,4})\b", re.I)
_CODE_ID = re.compile(r"\s*\b(?:дефект\w*\s+|требовани\w*\s+)?[DRCQT]-\d{1,3}\b")
_CODE_SRC = re.compile(r"\s*\b(?:lens|rules):[\w.]+")


def plain_text(text: str, keep: set[str] | frozenset = frozenset()) -> str:
    """Текст для владельца без внутренних кодов отчёта. ``keep`` — коды, которые есть в самом документе."""
    s = str(text or "")
    if not s:
        return s
    s = _CODE_PAREN.sub(lambda m: m.group(0) if any(k in m.group(0) for k in keep) else "", s)
    s = _CODE_ID.sub(lambda m: m.group(0) if m.group(0).strip().split()[-1] in keep else "", s)
    s = _CODE_LINE.sub(lambda m: m.group(0) if m.group(0).split()[-1] in keep
                       else f"{m.group(1) or 'стр.'} {int(m.group(2))}", s)
    s = _CODE_SRC.sub("", s)
    # хвосты после удалённых кодов: «см. и,», «( )», «, ,»
    for _ in range(2):
        s = re.sub(r"\(\s*(?:см\.?)?\s*\)", "", s)
        s = re.sub(r"\bсм\.\s*(?:и\s*)?(?=[,.;)]|$)", "", s)
        s = re.sub(r"\s+и\s*(?=[,.;)]|$)", "", s)
        s = re.sub(r"\s+(?:как\s+в|в|во|по|из|к|на|у|со?|для)\s*(?=[,.;)]|$)", "", s)
        s = re.sub(r"[,;]\s*(?=[,.;)]|$)", "", s)
        s = re.sub(r"\s+([,.;:!?)])", r"\1", s)
        s = re.sub(r"\s*[—–-]\s*([.;]?)$", r"\1", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def doc_codes(view: Any) -> set[str]:
    """Строки вида «R-12», «L038», которые встречаются в самом документе: их не трогаем."""
    found: set[str] = set()
    for ln in _lines(view):
        found.update(re.findall(r"\b(?:L\d{1,4}|[DRCQT]-\d{1,3})\b", str(ln.get("text", ""))))
    return found


def is_formatting(f: dict) -> bool:
    return f.get("severity") == "minor" and (f.get("kind") in FORMAT_KINDS or f.get("criterion") in FORMAT_CRITERIA)

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
    "properties": {"questions": {"type": "array", "maxItems": 10, "items": {
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


def is_new_side(e: dict, evidence: list[dict]) -> bool:
    """Другая сторона: другая строка или та же строка, но цитата не входит в уже взятую (и наоборот)."""
    q = _norm(e.get("quote", ""))
    for x in evidence:
        if x.get("line_start") != e.get("line_start"):
            continue
        p = _norm(x.get("quote", ""))
        if not q or not p or q in p or p in q:
            return False
    return True


def count_sides(evidence: list[dict]) -> int:
    """Сколько различных сторон у цитат: противоречие бывает и внутри одной строки."""
    taken: list[dict] = []
    for e in evidence:
        if is_new_side(e, taken):
            taken.append(e)
    return len(taken)


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
def question_cap(findings: list[dict]) -> int:
    """Сколько вопросов оставить: 8, если есть critical; иначе 5 главных решений."""
    return MAX_QUESTIONS if any(f.get("severity") == "critical" for f in findings) else MAX_QUESTIONS_NO_CRITICAL


def postprocess(raw: dict, findings: list[dict], view: Any, warnings: list[str] | None = None) -> list[dict]:
    """Ответ модели → вопросы контракта: проверки кодом, сортировка, ID Q-01…

    Каждый вопрос закрывает хотя бы один critical или major (если такие есть); блокирующий — только вопрос
    по critical; тексты для владельца без внутренних кодов; не больше ``question_cap`` вопросов."""
    warnings = warnings if warnings is not None else []
    by_id = {f.get("id"): f for f in findings}
    has_serious = any(f.get("severity") in ("critical", "major") for f in findings)
    keep_codes = doc_codes(view)
    kept: list[dict] = []
    seen_keys: list[tuple[str, str]] = []
    for i, q in enumerate(raw.get("questions") or [], 1):
        ids = [x for x in dict.fromkeys(str(x).strip() for x in q.get("finding_ids") or []) if x in by_id]
        text = plain_text(str(q.get("question", "")).strip(), keep_codes)
        if not ids or not text:
            warnings.append(f"clarify: вопрос {i} отброшен — нет связи с дефектами отчёта")
            continue
        if has_serious and not any(by_id[fid].get("severity") in ("critical", "major") for fid in ids):
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — касается только незначительных дефектов")
            continue
        near = [n for fid in ids for n in finding_lines(by_id[fid])]
        evidence = verified_evidence(view, q.get("evidence") or [], near)
        if not evidence:  # цитаты модели не найдены — берём цитаты самих дефектов (они уже сверены)
            evidence = [dict(e) for fid in ids for e in by_id[fid].get("evidence", [])
                        if e.get("verified", "exact") != "missing"][:3]
        if not evidence:
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — цитата не найдена в документе")
            continue
        if all(is_formatting(by_id[fid]) for fid in ids):
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — вопрос об оформлении")
            continue
        # у конфликта — цитаты обеих сторон (различные цитаты: противоречие бывает внутри одной строки);
        # недостающую сторону берём из сверенных цитат дефекта
        if any(by_id[fid].get("kind") in CONFLICT_KINDS for fid in ids):
            for fid in ids:
                for e in by_id[fid].get("evidence", []):
                    if count_sides(evidence) >= 2 or len(evidence) >= 3:
                        break
                    if e.get("line_start") and e.get("verified", "exact") != "missing" and is_new_side(e, evidence):
                        evidence.append(dict(e))
        options = [plain_text(o, keep_codes) for o in clean_options(q.get("options") or [])]
        options = [o for o in options if len(o) >= 3]
        if len(options) < 2:
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — меньше двух проверяемых вариантов")
            continue
        key = (_norm(q.get("topic") or ""), _norm(text))
        if any((key[0] and key[0] == k[0]) or key[1] == k[1] for k in seen_keys):
            warnings.append(f"clarify: вопрос «{text[:60]}» отброшен — повтор того же решения")
            continue
        seen_keys.append(key)
        sev = [by_id[fid].get("severity", "minor") for fid in ids]
        # блокирующий — только вопрос по critical: без ответа вердикт «нельзя» не снять (контракт, раздел 5)
        blocking = any(by_id[fid].get("severity") == "critical" and by_id[fid].get("blocks", "both") != "none"
                       for fid in ids)
        prio = min((int(by_id[fid].get("priority") or 0) or 99) for fid in ids)
        kept.append({
            "id": "", "topic": plain_text(str(q.get("topic", "")).strip(), keep_codes)[:80], "finding_ids": ids,
            "to": _role(q.get("to")), "blocking": blocking, "question": text, "evidence": evidence[:3],
            "options": options, "why": plain_text(str(q.get("why", "")).strip(), keep_codes),
            "_rank": (0 if blocking else 1, min(_SEV_RANK.get(s, 2) for s in sev), prio, i),
        })
    kept.sort(key=lambda x: x["_rank"])
    cap = question_cap(findings)
    if len(kept) > cap:
        warnings.append(f"clarify: оставлено {cap} вопросов из {len(kept)}")
        kept = kept[:cap]
    for n, q in enumerate(kept, 1):
        q.pop("_rank", None)
        q["id"] = f"Q-{n:02d}"
    return kept


def option_label(index: int) -> str:
    return OPTION_LETTERS[index] if 0 <= index < len(OPTION_LETTERS) else str(index + 1)


# --------------------------------------------------------------------------- этап
def select_findings(findings: list[dict]) -> list[dict]:
    """Что показать модели: critical и major (без оформления), critical первыми, затем по приоритету судьи."""
    serious = [f for f in findings if f.get("severity") in ("critical", "major") and not is_formatting(f)]
    if not serious:
        serious = [f for f in findings if not is_formatting(f)]
    def first_line(f: dict) -> int:
        lines = finding_lines(f)
        return min(lines) if lines else 10 ** 6
    return sorted(serious, key=lambda f: (_SEV_RANK.get(f.get("severity"), 2), int(f.get("priority") or 0) or 99,
                                          first_line(f)))


def _ask_questions(ctx: Any, items: list[dict], block: str) -> dict:
    def build(_items: list) -> tuple[str, str]:
        return build_messages(ctx, STAGE, "findings", block, "Задание: вопросы владельцу")
    system, user = build(items)
    return ctx.llm.ask(STAGE, system, user, SCHEMA, max_output_tokens=OUTPUT_TOKENS) or {}


def run(ctx: Any, findings: list[dict]) -> dict:
    """Вопросы владельцу по итоговым дефектам. Один вызов модели; без дефектов — без вызова."""
    relevant = select_findings(findings)
    if not relevant:  # только оформление (или дефектов нет) — спрашивать владельца не о чем
        return {"questions": []}
    warnings: list[str] = []
    try:
        raw = _ask_questions(ctx, relevant, format_findings(relevant))
    except Exception as exc:  # noqa: BLE001 — вопросы не должны ронять весь прогон
        _warn(ctx, f"clarify: модель не ответила ({type(exc).__name__}: {str(exc)[:200]}); вопросы не сформированы")
        return {"questions": [], "status": "failed"}
    questions = postprocess(raw or {}, findings, ctx.view, warnings)
    for w in warnings:
        _warn(ctx, w)
    return {"questions": questions}


# --------------------------------------------------------------------------- ранний запуск (параллельно с судьёй)
def select_candidates(candidates: list[dict]) -> list[list[dict]]:
    """Кандидаты critical/major со сверенными цитатами, сгруппированные в вероятные дубли (кластеры судьи)."""
    good = [c for c in candidates if c.get("severity") in ("critical", "major") and c.get("id")
            and c.get("kind") not in FORMAT_KINDS and c.get("criterion") not in FORMAT_CRITERIA
            and any(e.get("verified", "exact") != "missing" for e in c.get("evidence") or [])]
    if not good:
        return []
    by_id = {c["id"]: c for c in good}
    try:
        from bcc_review.v2.stages import judge as _judge
        groups = _judge.precluster(good)
    except Exception:  # noqa: BLE001
        groups = [[c["id"]] for c in good]
    out = [[by_id[x] for x in g if x in by_id] for g in groups]
    out = [g for g in out if g]
    out.sort(key=lambda g: (min(_SEV_RANK.get(c.get("severity"), 2) for c in g), -len(g)))
    return out


def format_candidates(groups: list[list[dict]]) -> str:
    """Кластеры кандидатов в том же виде, что и дефекты: ID через запятую в первой колонке."""
    rows: list[str] = []
    for g in groups:
        head = g[0]
        sev = min((c.get("severity", "minor") for c in g), key=lambda s: _SEV_RANK.get(s, 2))
        reqs = sorted({r for c in g for r in c.get("requirement_ids") or []})
        rows.append(f"{', '.join(c['id'] for c in g)} | {sev} | блокирует: {head.get('blocks', 'both')} | "
                    f"{', '.join(reqs) or '—'} | {head.get('title', '')}")
        seen: set[int] = set()
        quotes = []
        for c in g:
            for e in c.get("evidence") or []:
                ln = int(e.get("line_start") or e.get("line") or 0)
                if ln in seen or len(quotes) >= 3:
                    continue
                seen.add(ln)
                quotes.append(f"L{ln:03d} «{e.get('quote', '')}»")
        if quotes:
            rows.append(f"  цитаты: {'; '.join(quotes)}")
        for key, label in (("problem", "проблема"), ("question", "вопрос ревьюера")):
            val = next((str(c.get(key) or "").strip() for c in g if str(c.get(key) or "").strip()), "")
            if val:
                rows.append(f"  {label}: {val[:600]}")
    return "\n".join(rows)


def ask_candidates(ctx: Any, candidates: list[dict]) -> dict | None:
    """Ранний вызов: вопросы по сверенным кандидатам, пока судья ещё работает. ``None`` — спрашивать не о чем."""
    groups = select_candidates(candidates)
    if not groups:
        return None
    return _ask_questions(ctx, [c for g in groups for c in g], format_candidates(groups))


def remap(raw: dict, findings: list[dict]) -> dict:
    """ID кандидатов в ответе раннего вызова → ID итоговых дефектов судьи (по ``candidate_ids``)."""
    to_finding = {str(c): f.get("id") for f in findings for c in f.get("candidate_ids") or []}
    known = {f.get("id") for f in findings}
    out = {"questions": []}
    for q in (raw or {}).get("questions") or []:
        ids: list[str] = []
        for x in q.get("finding_ids") or []:
            x = str(x).strip()
            fid = x if x in known else to_finding.get(x)
            if fid and fid not in ids:
                ids.append(fid)
        out["questions"].append({**q, "finding_ids": ids})
    return out


class Early:
    """Ранний запуск вопросов: вызов модели идёт в фоне, пока работает судья (не удлиняет критический путь)."""

    def __init__(self, ctx: Any, candidates: list[dict]):
        import threading
        self.ctx, self.raw, self.error = ctx, None, None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._work, args=(list(candidates or []),), daemon=True,
                                        name="clarify-early")
        self._thread.start()

    def _work(self, candidates: list[dict]) -> None:
        try:
            self.raw = ask_candidates(self.ctx, candidates)
        except Exception as exc:  # noqa: BLE001
            self.error = exc
        finally:
            self._done.set()

    def result(self, timeout: float | None = None) -> tuple[dict | None, BaseException | None]:
        self._done.wait(timeout)
        return self.raw, self.error


def start(ctx: Any, candidates: list[dict]) -> Early | None:
    """Для конвейера (№01): запустить вопросы сразу после сверки цитат, параллельно с судьёй."""
    if getattr(ctx, "llm", None) is None:
        return None
    return Early(ctx, candidates)


def finish(ctx: Any, findings: list[dict], early: "Early | dict | None" = None) -> dict:
    """Вопросы по итоговым дефектам: ответ раннего вызова привязывается к дефектам судьи.

    Если раннего вызова не было, он упал или ни один его вопрос не лёг на critical/major судьи —
    обычный вызов ``run`` по итоговым дефектам."""
    raw, err = (early.result() if isinstance(early, Early) else (early, None))
    if err is not None or not isinstance(raw, dict):
        if err is not None:
            _warn(ctx, f"clarify: ранний вызов не удался ({type(err).__name__}); вопросы — по итоговым дефектам")
        return run(ctx, findings)
    if not select_findings(findings):
        return {"questions": []}
    warnings: list[str] = []
    questions = postprocess(remap(raw, findings), findings, ctx.view, warnings)
    covered = {fid for q in questions for fid in q["finding_ids"]}
    crit = [f["id"] for f in findings if f.get("severity") == "critical" and f.get("id")]
    if not questions or (crit and not any(c in covered for c in crit)):
        _warn(ctx, "clarify: вопросы раннего вызова не легли на итоговые дефекты — повторный вызов по ним")
        return run(ctx, findings)
    for w in warnings:
        _warn(ctx, w)
    return {"questions": questions}
