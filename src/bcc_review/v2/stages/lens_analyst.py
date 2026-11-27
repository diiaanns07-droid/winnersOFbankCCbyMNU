"""Постобработка ответа линзы «Аналитик» (владелец — №05).

Модель, особенно слабая, нарушает правила промпта: завышает серьёзность, дублирует один дефект,
выходит за лимит кандидатов. Здесь эти правила применяются кодом, детерминированно:

1. кандидат без единой цитаты отбрасывается;
2. дубли (тот же тип и тот же набор строк-цитат) схлопываются в первого;
3. неединичность (`non_singular`) не бывает выше `minor`;
4. `critical` без сценария, последствий, с `blocks = none` или без расхождения двух мест документа (тип не из
   расхождений — `ambiguity`, `incomplete`…, или все цитаты из одной строки) понижается до `major`:
   critical у этой линзы — только когда другое место документа прямо поддерживает иное толкование;
5. `critical` больше двух — лишние понижаются до `major`; `critical` с цитатой из раздела описания API (заголовок
   раздела называет API или REST; строка — по сверке цитаты) — тоже `major` с `severity_hint = critical` (№28):
   бизнес-правило против шага логики метода или примера ответа — зона архитектора и проверки набора;
6. **зрелый документ** (см. `maturity`) — строгий режим: остаются только расхождения двух мест документа
   (единицы, границы, события, противоречие правил) — `MATURE_MAX_OTHER_MAJOR = 0` прочих `major`, `minor` нет.
   Замер на корпусе (haiku, v13 с одним прочим major): прочие major на мутантах — 21 лишнее замечание при
   1 попадании, на чистых — 7 из 8 замечаний. Исключение — дефект языка, который доказывает сама цитата
   (субъективное слово «быстро», «удобно», лазейка «по возможности», открытый перечень «и т. д.»): он не зависит
   от зрелости документа, их остаётся до `MATURE_MAX_LANGUAGE`. На сыром документе линза работает в полную силу;
7. заголовок, написанный в основном латиницей (слабая модель иногда переходит на английский), заменяется
   началом поля `problem` (до 12 слов), если оно по-русски: отчёт читает аналитик банка;
8. сортировка: critical → major → minor, внутри — порядок модели;
9. не больше 12 кандидатов.

Признаки зрелости считаются кодом по тексту документа, без модели: есть раздел терминов, указана версия,
явный часовой пояс (UTC/GMT), нет заглушек («заполняются…», «TBD», неотмеченное «Да / Нет», прочерк
вместо значения). Зрелый — 3 признака из 4.
"""
from __future__ import annotations

import re
from typing import Any

MAX_CANDIDATES = 12
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


_API_SECTION = re.compile(r"\bAPI\b|\bREST\b", re.I)


def api_lines(view: Any) -> set[int]:
    """Строки раздела описания API (заголовок раздела по docview называет API или REST): поля, коды, логика метода."""
    lines = view.get("lines") if isinstance(view, dict) else None
    out: set[int] = set()
    for x in lines or []:
        if isinstance(x, dict) and isinstance(x.get("n"), int) and _API_SECTION.search(str(x.get("section") or "")):
            out.add(x["n"])
    return out


def touches_api(view: Any, candidates: list[dict], api: set[int]) -> list[bool]:
    """По кандидату: есть ли цитата из раздела API. Строка цитаты — по сверке с документом (как у этапа quotes;
    у модели номер бывает сбит), ненайденная цитата — по номеру модели."""
    try:
        from bcc_review.v2 import quotes
    except ImportError:  # pragma: no cover
        quotes = None
    out = []
    for c in candidates or []:
        hit = False
        for ev in (c.get("evidence") if isinstance(c, dict) else None) or []:
            if not isinstance(ev, dict):
                continue
            n = ev.get("line")
            if quotes is not None and isinstance(view, dict):
                try:
                    m = quotes.verify_quote(view, ev.get("quote"), n)
                except Exception:  # noqa: BLE001 — уточнение строки не условие работы линзы
                    m = None
                n = m.get("line_start") if m else n
            hit = hit or (isinstance(n, int) and n in api)
        out.append(hit)
    return out


def postprocess(candidates: list[dict[str, Any]], *, mature: bool = False, max_candidates: int = MAX_CANDIDATES,
                max_critical: int = MAX_CRITICAL, api_flags: list[bool] | None = None) -> list[dict[str, Any]]:
    """Применить правила линзы к ответу модели. Не меняет входной список. `api_flags` — по входному кандидату, есть
    ли у него цитата из раздела описания API (`touches_api`): critical с такой цитатой понижается до major
    (расхождение бизнес-правила и контракта или логики метода — зона архитектора и проверки набора; на чистых ТЗ №18
    все разобранные ложные critical линзы были такими)."""
    seen: set[tuple] = set()
    kept: list[dict] = []
    for i, raw in enumerate(candidates or []):
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
        if sev == "critical" and api_flags and i < len(api_flags) and api_flags[i]:
            sev = "major"
            c["severity_hint"] = "critical"  # модель считала critical: подсказка судье, в вердикт не идёт
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


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01);
    он сам берёт `MAX_OUTPUT_TOKENS` из этого модуля."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    view = getattr(ctx, "view", None)
    m = maturity(view)
    out = dict(lens_run(ctx, "analyst"))
    cands = out.get("candidates") or []
    out["candidates"] = postprocess(cands, mature=m["mature"], api_flags=touches_api(view, cands, api_lines(view)))
    out["document_maturity"] = m
    return out
