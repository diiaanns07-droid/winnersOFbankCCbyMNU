"""Постобработка ответа линзы «Аналитик» (владелец — №05).

Модель, особенно слабая, нарушает правила промпта: завышает серьёзность, дублирует один дефект,
выходит за лимит кандидатов. Здесь эти правила применяются кодом, детерминированно:

1. кандидат без единой цитаты отбрасывается;
2. дубли (тот же тип и тот же набор строк-цитат) схлопываются в первого;
3. неединичность (`non_singular`) не бывает выше `minor`;
4. `critical` без сценария, последствий, с `blocks = none` или без расхождения двух мест документа (тип не из
   расхождений — `ambiguity`, `incomplete`…, или все цитаты из одной строки) понижается до `major`:
   critical у этой линзы — только когда другое место документа прямо поддерживает иное толкование;
5. `critical` больше двух — лишние понижаются до `major`;
6. **зрелый документ** (см. `maturity`) — строгий режим: остаются только расхождения двух мест документа
   (единицы, границы, события, противоречие правил) — `MATURE_MAX_OTHER_MAJOR = 0` прочих `major`, `minor` нет.
   Замер на корпусе (haiku, v13 с одним прочим major): прочие major на мутантах — 21 лишнее замечание при
   1 попадании, на чистых — 7 из 8 замечаний. Исключение — дефект языка, который доказывает сама цитата
   (субъективное слово «быстро», «удобно», лазейка «по возможности», открытый перечень «и т. д.»): он не зависит
   от зрелости документа, их остаётся до `MATURE_MAX_LANGUAGE`. На сыром документе линза работает в полную силу;
7. заголовок, написанный в основном латиницей (слабая модель иногда переходит на английский), заменяется
   началом поля `problem` (до 12 слов), если оно по-русски: отчёт читает аналитик банка;
8. сортировка: critical → major → minor, внутри — порядок модели;
9. не больше 16 кандидатов.

**Опись вопросов полноты** (`coverage`, №12, 27.11): прежде чем писать кандидатов, модель проходит по темам
промпта (два места об одном, событие, период, состояние в условии, противоположная ветка, изменение настройки,
величины для клиента, перечни, возврат, экран, участники, единицы, нефункциональные) и для каждого места записывает вопрос и
ответ документа (`L0xx: «…»` или пусто). Пустой ответ, прошедший фильтр, становится кандидатом. Опись остаётся
в файле этапа (`runs/<id>/stages/lens_analyst.json`): видно, какие темы линза проверила и где документ молчит.
Замер (официальный документ, по одному запросу на сохранённых входах): без описи Flash давал 4–6 кандидатов
и 2–4 существенных из эталона, haiku — 8 и 6.

Признаки зрелости считаются кодом по тексту документа, без модели: есть раздел терминов, указана версия,
явный часовой пояс (UTC/GMT), нет заглушек («заполняются…», «TBD», неотмеченное «Да / Нет», прочерк
вместо значения). Зрелый — 3 признака из 4.
"""
from __future__ import annotations

import re
from typing import Any

from bcc_review.v2.types import CANDIDATE_SCHEMA, INT, STR, obj  # абсолютный: тесты №05 грузят модуль файлом

MAX_CANDIDATES = 16
MAX_COVERAGE = 40
COVERAGE_ITEM = obj({"topic": STR, "line": INT, "question": STR, "answer": STR})
# Опись первой: модель отвечает полями по порядку схемы и пишет кандидатов, уже пройдя все темы
SCHEMA = obj({"coverage": {"type": "array", "items": COVERAGE_ITEM},
              "candidates": {"type": "array", "items": CANDIDATE_SCHEMA}})
MAX_OUTPUT_TOKENS = 32000  # `lens.run` берёт его из модуля: рассуждение слабой модели + JSON
MAX_CRITICAL = 2
MATURE_MIN_SIGNS = 3
MATURE_MAX_OTHER_MAJOR = 0
MATURE_MAX_LANGUAGE = 2
_RANK = {"critical": 0, "major": 1, "minor": 2}
_MINOR_ONLY_KINDS = {"non_singular"}
_CONFLICT_KINDS = {"event_conflict", "boundary_conflict", "unit_mismatch", "contradiction", "status_conflict"}
_CRITICAL_KINDS = _CONFLICT_KINDS

# Слова, которые сами по себе делают формулировку непроверяемой (ISO/IEC/IEEE 29148, п. 5.2.7)
_VAGUE = re.compile(
    r"быстр\w*|своевременн\w*|мгновенн\w*|моментальн\w*|оперативн\w*|удобн\w*|оптимальн\w*|без\s+задерж\w*|"
    r"по\s+возможности|при\s+необходимости|как\s+правило|и\s+т\.\s?[дп]\.|и\s+други\w*|и\s+далее|"
    r"(?:высок|больш)\w*\s+нагрузк\w*|всегда\s+актуальн\w*", re.I)
_LANGUAGE_KINDS = {"ambiguity", "unverifiable"}
_TERMS = re.compile(r"^\s*(?:#+\s*)?(?:термин\w*|глоссари\w*|определени[яе](?:\s+термин\w*)?)\s*:?\s*$", re.I)
_VERSION = re.compile(r"верси[яи]\b[^\n]*\d", re.I)
_TZ = re.compile(r"\b(?:UTC|GMT)\b", re.I)
_PLACEHOLDER = re.compile(
    r"\bTBD\b|\bTODO\b|заполня\w*\s+\w+|не\s+заполнен\w*|Да\s*/\s*Нет|:\s*[—-]\s*(?:\.|$)|\|\s*—\s*(?:\||$)", re.I)


def _texts(view: Any) -> list[str]:
    if isinstance(view, dict):
        return [str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in view.get("lines") or []]
    if isinstance(view, str):
        return view.splitlines()
    return []


def maturity(view: Any) -> dict:
    """Признаки вычитанного документа по его тексту. `mature` — не меньше `MATURE_MIN_SIGNS` из 4."""
    lines = _texts(view)
    signs = {
        "terms": any(_TERMS.match(t) for t in lines),
        "version": any(_VERSION.search(t) for t in lines),
        "timezone": any(_TZ.search(t) for t in lines),
        "no_placeholders": bool(lines) and not any(_PLACEHOLDER.search(t) for t in lines),
    }
    score = sum(signs.values())
    return {**signs, "score": score, "mature": score >= MATURE_MIN_SIGNS}


_LAT = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁё]")
TITLE_MAX_WORDS = 12


def _mostly_latin(text: str) -> bool:
    lat, cyr = len(_LAT.findall(text)), len(_CYR.findall(text))
    return lat > cyr


def _russian_title(c: dict) -> str:
    """Заголовок по-русски: свой, если он не латиницей, иначе начало первой фразы `problem`."""
    title = str(c.get("title", "")).strip()
    if title and not _mostly_latin(title):
        return title
    problem = str(c.get("problem", "")).strip()
    if not problem or _mostly_latin(problem):
        return title
    first = re.split(r"(?<=[.!?])\s+", problem, maxsplit=1)[0].rstrip(".!? ")
    words = first.split()
    if len(words) > TITLE_MAX_WORDS:
        words = words[:TITLE_MAX_WORDS]
        while words and words[-1].lower().strip(",;:—-") in {"и", "а", "но", "или", "в", "на", "с", "по", "к", "от",
                                                              "для", "что", "как", "не", "при", "до", "за", "из"}:
            words.pop()
        first = " ".join(words).rstrip(",;:—- ")
    return first[:1].upper() + first[1:] if first else title


def _lines(c: dict) -> tuple:
    out = []
    for ev in c.get("evidence") or []:
        n = ev.get("line_start", ev.get("line"))
        out.append(n if isinstance(n, int) else str(ev.get("quote", "")).strip().lower())
    return tuple(sorted(out, key=str))


def _has_evidence(c: dict) -> bool:
    return any(str(ev.get("quote", "")).strip() for ev in c.get("evidence") or [])


def _is_vague_language(c: dict) -> bool:
    """Дефект языка, который доказывает сама цитата: в ней есть субъективное слово, лазейка или открытый перечень."""
    if c.get("kind") not in _LANGUAGE_KINDS:
        return False
    return any(_VAGUE.search(str(ev.get("quote", ""))) for ev in c.get("evidence") or [])


def _is_conflict(c: dict) -> bool:
    """Расхождение двух мест: тип расхождения и цитаты хотя бы из двух разных строк."""
    if c.get("kind") not in _CONFLICT_KINDS:
        return False
    lines = {ev.get("line_start", ev.get("line")) for ev in c.get("evidence") or []}
    return len({n for n in lines if isinstance(n, int)}) >= 2


def postprocess(candidates: list[dict[str, Any]], *, mature: bool = False, max_candidates: int = MAX_CANDIDATES,
                max_critical: int = MAX_CRITICAL) -> list[dict[str, Any]]:
    """Применить правила линзы к ответу модели. Не меняет входной список."""
    seen: set[tuple] = set()
    kept: list[dict] = []
    for raw in candidates or []:
        if not isinstance(raw, dict) or not _has_evidence(raw):
            continue
        c = dict(raw)
        key = (c.get("kind", ""), _lines(c))
        if key in seen:
            continue
        seen.add(key)
        sev = c.get("severity") if c.get("severity") in _RANK else "major"
        if c.get("kind") in _MINOR_ONLY_KINDS:
            sev = "minor"
        if sev == "critical" and (not _is_conflict(c)
                                  or not str(c.get("scenario", "")).strip()
                                  or not str(c.get("impact", "")).strip()
                                  or c.get("blocks", "none") == "none"):
            sev = "major"
        c["severity"] = sev
        c["title"] = _russian_title(c)
        kept.append(c)

    critical = 0
    for c in kept:
        if c["severity"] == "critical":
            critical += 1
            if critical > max_critical:
                c["severity"] = "major"

    if mature:
        strict, other, language = [], 0, 0
        for c in kept:
            if _is_vague_language(c):
                language += 1
                if language <= MATURE_MAX_LANGUAGE:
                    strict.append(c)
                continue
            if c["severity"] == "minor":
                continue
            if c["severity"] == "major" and not _is_conflict(c):
                other += 1
                if other > MATURE_MAX_OTHER_MAJOR:
                    continue
            strict.append(c)
        kept = strict

    order = sorted(range(len(kept)), key=lambda i: (_RANK[kept[i]["severity"]], i))
    return [kept[i] for i in order][:max_candidates]


def coverage(items: Any) -> list[dict]:
    """Опись вопросов полноты из ответа модели: только строки-объекты с темой, не больше `MAX_COVERAGE`."""
    out = []
    for it in items or []:
        if isinstance(it, dict) and str(it.get("topic") or "").strip():
            out.append({"topic": str(it.get("topic")).strip(), "line": it.get("line") if isinstance(it.get("line"), int)
                        else 0, "question": str(it.get("question") or "").strip(),
                        "answer": str(it.get("answer") or "").strip()})
    return out[:MAX_COVERAGE]


_WORD = re.compile(r"[а-яёa-z0-9]{4,}", re.I)
_STOP = frozenset("""если когда какой какая какое какие каком которая который которые описан описано описаны указан
указано указаны определён определено определены задан задано заданы ли для при или это этот документ документе
требовани правило правила""".split())
_SENT = re.compile(r"(?<=[.!?;])\s+")
MAX_GAPS = 6
_CONFLICT_Q = re.compile(r"^\s*(совпада|согласован|противореч|расход|пересека|запрещает ли|разрешает ли)", re.I)


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def _line_text(view: Any, n: int) -> str:
    for ln in (view or {}).get("lines") or [] if isinstance(view, dict) else []:
        if isinstance(ln, dict) and ln.get("n") == n:
            return str(ln.get("text") or "")
    return ""


def _best_sentence(text: str, question: str) -> str:
    sents = [x.strip() for x in _SENT.split(text) if len(x.strip()) >= 8] or [text.strip()]
    q = _stems(question)
    return max(sents, key=lambda x: (len(_stems(x) & q), -sents.index(x)))[:300]


def coverage_gaps(cov: list[dict], candidates: list[dict], view: Any, *, limit: int = MAX_GAPS) -> list[dict]:
    """Строки описи без ответа документа, для которых модель не написала кандидата, — кандидаты кода.

    Слабая модель (Flash) находит в описи 7–12 мест, где документ молчит, но пишет 5–6 кандидатов. Кандидат кода:
    заголовок — вопрос описи, цитата — фраза строки места, серьёзность `minor` (уровень решает судья).
    Не берутся: строки с ответом, темы Т1–Т2 (расхождение требует двух цитат и сценария), строки, у которых
    есть кандидат на той же строке с общими словами вопроса."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for row in cov or []:
        q, n = row.get("question", ""), row.get("line") or 0
        if row.get("answer") or not q or n <= 0 or str(row.get("topic")).strip() in ("Т1", "Т2", "T1", "T2") \
                or _CONFLICT_Q.search(q):
            continue
        qs = _stems(q)
        if any(n in {e.get("line_start", e.get("line")) for e in c.get("evidence") or []}
               and len(qs & _stems(str(c.get("title", "")) + " " + str(c.get("problem", "")))) >= 2
               for c in candidates):
            continue
        text = _line_text(view, n)
        if not text.strip():
            continue
        quote = _best_sentence(text, q)
        key = (n, quote)
        if key in seen:
            continue
        seen.add(key)
        title = q.strip().rstrip("?").strip()
        out.append({
            "title": title[:1].upper() + title[1:] + "?", "kind": "incomplete", "criterion": "complete",
            "severity": "minor", "requirement_ids": [], "evidence": [{"quote": quote, "line": n}],
            "problem": f"Документ не отвечает на вопрос: {q.strip()}", "scenario": "", "impact": "",
            "recommendation": "Дописать ответ в требование или явно исключить случай из объёма.", "rewrite": "",
            "question": q.strip(), "blocks": "none", "origin": "coverage",
        })
        if len(out) >= limit:
            break
    return out


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01);
    он сам берёт `MAX_OUTPUT_TOKENS` из этого модуля."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    m = maturity(getattr(ctx, "view", None))
    out = dict(lens_run(ctx, "analyst"))
    out["candidates"] = postprocess(out.get("candidates") or [], mature=m["mature"])
    out["coverage"] = coverage(out.get("coverage"))
    if not m["mature"]:  # вычитанный документ — только расхождения (см. `postprocess`), пробелы описи не добираем
        gaps = coverage_gaps(out["coverage"], out["candidates"], getattr(ctx, "view", None))
        out["candidates"] += gaps
        out["coverage_gaps"] = len(gaps)
    out["document_maturity"] = m
    return out
