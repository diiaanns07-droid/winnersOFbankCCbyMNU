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

import os
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


def evidence_lines(view: Any, candidates: list[dict]) -> list[set[int]]:
    """Строки цитат каждого кандидата — по сверке с документом (как у этапа quotes; у модели номер бывает сбит),
    ненайденная цитата — по номеру модели."""
    try:
        from bcc_review.v2 import quotes
    except ImportError:  # pragma: no cover
        quotes = None
    out = []
    for c in candidates or []:
        got: set[int] = set()
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
            if isinstance(n, int):
                got.add(n)
        out.append(got)
    return out


def touches_api(view: Any, candidates: list[dict], api: set[int]) -> list[bool]:
    """По кандидату: есть ли цитата из раздела API (строки — `evidence_lines`)."""
    return [bool(lines & api) for lines in evidence_lines(view, candidates)]


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


# Два просмотра (№28): у слабой модели набор найденного от прогона к прогону сильно разный (на официальном haiku
# 5 и 2 пункта эталона из С у одной версии промпта), а ложные на чистых ТЗ — каждый раз свои. Второй независимый
# просмотр (документ в обратном порядке разделов) и объединение поднимают полноту; major и critical остаются только
# у мест, которые нашли оба просмотра, найденное одним — minor с `severity_hint`. На вычитанном документе строгий
# режим и так точен — второй просмотр не делается.
# Замер haiku 20:05 (2 повтора, текущий промпт): офиц. С 4,5 → 6,0; чистые №18 critical 0, major 10 → 7, minor 31 → 41.
# По умолчанию выключено: ветка №28 вливается в релиз (№46), а с судьёй два просмотра не мерены — включение в v2.1
# после замера №31 (`True` здесь или `BCC_ANALYST_VIEWS=2`).
TWO_VIEWS = False
VIEWS_ENV = "BCC_ANALYST_VIEWS"  # «1» или «2» — число просмотров для замера (стенд №28); иначе — TWO_VIEWS
SECOND_VIEW = ("\n\n### Второй просмотр\nЭтот документ уже просмотрел другой аналитик, начиная с первых разделов. "
               "Пройди его в обратном порядке — от последних разделов бизнес-части к первым — с тем же фильтром, той же "
               "шкалой серьёзности и теми же правилами оформления.")


class _SecondView:
    """Клиент модели для второго просмотра: то же задание с пометкой (другой ключ кэша, другой порядок обхода)."""

    def __init__(self, llm: Any):
        self._llm = llm

    def ask(self, stage, system, user, schema, **kw):
        return self._llm.ask(stage, system, user + SECOND_VIEW, schema, **kw)

    def ask_split(self, stage, build, items, schema, merge, **kw):
        return self._llm.ask_split(stage, lambda it: (lambda s_, u_: (s_, u_ + SECOND_VIEW))(*build(it)),
                                   items, schema, merge, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


def _demote(c: dict) -> dict:
    c = dict(c)
    if c.get("severity") != "minor":
        c.setdefault("severity_hint", c.get("severity"))
        c["severity"] = "minor"
    c["views"] = 1
    return c


def merge_views(first: list[dict], second: list[dict], lines_first: list[set[int]], lines_second: list[set[int]],
                max_candidates: int = MAX_CANDIDATES) -> list[dict]:
    """Объединить два просмотра. Совпадение — общая строка цитаты (строки — по сверке с документом). Совпавший
    кандидат берётся из первого просмотра с меньшей из двух серьёзностей (на чистых ТЗ ложный critical одного
    просмотра другой видел как major); найденный одним просмотром — `minor`
    (`severity_hint` — прежняя серьёзность). Найденное только вторым просмотром берётся, лишь если там оно было
    major или critical: одиночный minor второго просмотра — шум (замер haiku на текущем промпте: на 4 чистых ТЗ №18
    minor 17 → 23 с ними и 17 → 19 без них, на официальном те же +2 пункта С). Порядок: critical → major → minor,
    внутри — первый просмотр, затем второй."""
    used: set[int] = set()
    out: list[dict] = []
    for i, c in enumerate(first):
        li = lines_first[i] if i < len(lines_first) else set()
        j = next((j for j, _ in enumerate(second) if j not in used and li
                  and li & (lines_second[j] if j < len(lines_second) else set())), None)
        if j is None:
            out.append(_demote(c))
        else:
            used.add(j)
            x = {**c, "views": 2}
            other = second[j].get("severity")
            if _RANK.get(other, 2) > _RANK.get(c.get("severity"), 2):  # совпали — меньшая из двух серьёзностей
                x.setdefault("severity_hint", c.get("severity"))
                x["severity"] = other
            out.append(x)
    out += [_demote(c) for j, c in enumerate(second) if j not in used and c.get("severity") in ("critical", "major")]
    order = sorted(range(len(out)), key=lambda k: (_RANK.get(out[k].get("severity"), 2), k))
    return [out[k] for k in order][:max_candidates]


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01);
    он сам берёт `MAX_OUTPUT_TOKENS` из этого модуля."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    view = getattr(ctx, "view", None)
    m = maturity(view)
    api = api_lines(view)
    options = getattr(ctx, "options", None) or {}
    enabled = TWO_VIEWS if os.environ.get(VIEWS_ENV, "") not in ("1", "2") else os.environ[VIEWS_ENV] == "2"
    two = enabled and not m["mature"] and int(options.get("passes", 1) or 1) < 2 and getattr(ctx, "llm", None)

    def one(c) -> tuple[dict, list[dict]]:
        res = dict(lens_run(c, "analyst"))
        cands = res.get("candidates") or []
        return res, postprocess(cands, mature=m["mature"], api_flags=touches_api(view, cands, api))

    if not two:
        out, cands = one(ctx)
        out["candidates"] = cands
        out["document_maturity"] = m
        return out
    import concurrent.futures as cf
    import copy
    ctx2 = copy.copy(ctx)
    ctx2.llm = _SecondView(ctx.llm)
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(one, ctx), ex.submit(one, ctx2)]
        results = []
        for f in futs:
            try:
                results.append(f.result())
            except Exception as exc:  # noqa: BLE001 — второй просмотр — улучшение, а не условие работы линзы
                results.append(exc)
    ok = [r for r in results if not isinstance(r, Exception)]
    if not ok:
        raise results[0]
    if len(ok) == 1:
        out, cands = ok[0]
        warn = getattr(ctx, "warn", None)
        failed = next(r for r in results if isinstance(r, Exception))
        if callable(warn):
            warn(f"Линза «Аналитик»: один из двух просмотров не удался ({type(failed).__name__}) — оставлен другой")
        out["candidates"] = cands
    else:
        (out, a), (_, b) = ok
        out["candidates"] = merge_views(a, b, evidence_lines(view, a), evidence_lines(view, b))
        out["view_candidates"] = {"first": a, "second": b}  # для замера: один просмотр против двух на тех же ответах
        out["views"] = {"first": len(a), "second": len(b), "agreed": sum(1 for c in out["candidates"]
                                                                         if c.get("views") == 2)}
    out["document_maturity"] = m
    return out
