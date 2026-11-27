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

**Проверка состояния кодом** (`state_probes`, №12, 27.11): состояние объекта из функционального требования
(«активная», «открытый», «подтверждённый» …), которого нет в шагах логики метода, — кандидат с двумя цитатами
(требование и шаг логики). На корпусе open2 не срабатывает ни на одном документе: в вычитанных ТЗ шаг проверки
состояния есть всегда.

**Несколько проходов на слабой модели** (`passes_for`, `merge_passes`): на Gemini Flash линза отвечает дважды
(второй проход идёт по темам описи в обратном порядке), кандидаты и опись объединяются без повторов. Один запрос
сверх девяти: на бесплатном ключе это всё те же два прогона в сутки.

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


def coverage(items: Any, *, limit: int = MAX_COVERAGE) -> list[dict]:
    """Опись вопросов полноты из ответа модели: только строки-объекты с темой, не больше `limit`."""
    out = []
    for it in items or []:
        if isinstance(it, dict) and str(it.get("topic") or "").strip():
            out.append({"topic": str(it.get("topic")).strip(), "line": it.get("line") if isinstance(it.get("line"), int)
                        else 0, "question": str(it.get("question") or "").strip(),
                        "answer": str(it.get("answer") or "").strip()})
    return out[:limit]


_WORD = re.compile(r"[а-яёa-z0-9]{4,}", re.I)
_STOP = frozenset("""если когда какой какая какое какие каком которая который которые описан описано описаны указан
указано указаны определён определено определены задан задано заданы ли для при или это этот документ документе
требовани правило правила""".split())
_SENT = re.compile(r"(?<=[.!?;])\s+")
MAX_GAPS = 6
# Чего не хватает в документе по теме описи — начало поля `problem` у кандидата кода (тема без подписи — общая фраза)
_TOPIC_GAP = {
    "Т3": "Событие не определено", "Т4": "Период не определён", "Т5": "Состояние не определено",
    "Т6": "Противоположная ветка условия не описана", "Т7": "Изменение настройки не описано",
    "Т8": "Состав сообщения или экрана не определён", "Т9": "Перечень не закрыт",
    "Т10": "Возврат или отмена не описаны", "Т11": "Экран описан не полностью",
    "Т12": "Участники названы по-разному или их права не определены", "Т13": "Единицы не согласованы",
    "Т14": "Нефункциональное требование не измеримо", "Т15": "Шаг метода описан не полностью",
}
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
    есть кандидат или уже взятый пробел на той же строке, в заголовке которого не меньше 40 % слов вопроса (два
    разных вопроса к одной фразе — два кандидата). `problem` начинается с того, чего не хватает по теме описи."""
    out: list[dict] = []
    for row in cov or []:
        q, n = row.get("question", ""), row.get("line") or 0
        topic = str(row.get("topic") or "").strip().replace("T", "Т")
        if row.get("answer") or not q or n <= 0 or topic in ("Т1", "Т2") or _CONFLICT_Q.search(q):
            continue
        qs = _stems(q)
        need = max(2, -(-len(qs) * 2 // 5))  # не меньше двух и 40 % слов вопроса: общие слова предмета не в счёт
        if any(n in {e.get("line_start", e.get("line")) for e in c.get("evidence") or []}
               and len(qs & _stems(str(c.get("title", "")))) >= need  # по заголовку: в problem цитаты строки
               for c in candidates + out):  # и не повтор уже взятого пробела (второй проход спрашивает то же)
            continue
        text = _line_text(view, n)
        if not text.strip():
            continue
        quote = _best_sentence(text, q)
        title = q.strip().rstrip("?").strip()
        what = _TOPIC_GAP.get(topic, "Случай не описан")
        out.append({
            "title": title[:1].upper() + title[1:] + "?", "kind": "incomplete", "criterion": "complete",
            "severity": "minor", "requirement_ids": [], "evidence": [{"quote": quote, "line": n}],
            "problem": f"{what}: документ не отвечает на вопрос «{q.strip()}».", "scenario": "", "impact": "",
            "recommendation": "Дописать ответ в требование или явно исключить случай из объёма.", "rewrite": "",
            "question": q.strip(), "blocks": "none", "origin": "coverage",
        })
        if len(out) >= limit:
            break
    return out


# ─────────────── проверка кодом: состояние из требования не проверяется в логике метода ───────────────
# Требование допускает действие только для объекта в определённом состоянии («активная карта», «открытый счёт»),
# а шаги логики метода этого состояния не проверяют: не сказано, что это за состояние и что вернуть, если его нет.
# В вычитанных ТЗ корпуса шаг проверки есть всегда («проверить, что карта … активна и открыта в тенге»).
_STATE = re.compile(r"(?<![а-яё])(активн|действующ|открыт|заблокирован|разблокирован|подтвержд[её]нн|верифицированн"
                    r"|идентифицированн)[а-яё]*\s+([а-яё]{3,})(?:\s+([A-Z]{3})(?![A-Za-z]))?", re.I)
_LOGIC_SECTION = re.compile(r"логик", re.I)
_BUSINESS_SECTION_SKIP = re.compile(r"логик|особ\w* правил|rest|api|статус|ответ|параметр", re.I)
_CURRENCY_WORDS = re.compile(r"\b[A-Z]{3}\b|тенге|валют", re.I)
MAX_STATE_PROBES = 2


def _req_lines(requirements: Any, want) -> list[int]:
    out: list[int] = []
    for r in requirements or []:
        if not isinstance(r, dict):
            continue
        a = r.get("line_start")
        b = r.get("line_end") or a
        if isinstance(a, int) and isinstance(b, int) and want(r):
            out.extend(range(a, b + 1))
    return sorted(set(out))


def state_probes(view: Any, requirements: Any, candidates: list[dict], *, limit: int = MAX_STATE_PROBES) -> list[dict]:
    """Кандидаты кода: состояние объекта из функционального требования, которого нет в шагах логики метода.

    Не срабатывает, если в документе нет раздела логики метода (сверять не с чем), если шаги логики называют то же
    состояние, или если у модели уже есть кандидат на той же строке со словом этого состояния в заголовке."""
    logic = _req_lines(requirements, lambda r: _LOGIC_SECTION.search(str(r.get("section") or "")))
    if not logic:
        return []
    logic_text = {n: _line_text(view, n) for n in logic}
    business = _req_lines(requirements, lambda r: r.get("kind") == "functional"
                          and not _BUSINESS_SECTION_SKIP.search(str(r.get("section") or "")))
    out: list[dict] = []
    seen: set[str] = set()
    for n in business:
        text = _line_text(view, n)
        for m in _STATE.finditer(text):
            stem = m.group(1).lower()[:5]
            if stem in seen or any(stem in t.lower() for t in logic_text.values()):
                continue
            noun = m.group(2).lower()
            if any(n in {e.get("line_start", e.get("line")) for e in c.get("evidence") or []}
                   and stem in str(c.get("title", "")).lower() for c in candidates):
                continue
            seen.add(stem)
            phrase = m.group(0).strip()
            currency = m.group(3)
            unchecked_currency = bool(currency) and not any(_CURRENCY_WORDS.search(t) for t in logic_text.values())
            step = next((k for k, t in logic_text.items() if noun[:4] in t.lower()), logic[0])
            what = "состояние и валюта" if unchecked_currency else "состояние"
            out.append({
                "title": f"Условие «{phrase}» не определено и не проверяется в логике метода",
                "kind": "incomplete", "criterion": "complete", "severity": "major", "requirement_ids": [],
                "evidence": [{"quote": _best_sentence(text, phrase), "line": n},
                             {"quote": _best_sentence(logic_text[step], noun), "line": step}],
                "problem": f"Требование ставит условие «{phrase}», но шаги логики метода {what} не проверяют: "
                           "не определено, что это условие означает и какой ответ вернуть, если оно не выполнено.",
                "scenario": f"Запрос приходит для объекта, который не отвечает условию «{phrase}»: по шагам логики "
                            "метода он обрабатывается как обычный.",
                "impact": "Разработчик и тестировщик по-разному решат, отклонять ли такой запрос и каким ответом.",
                "recommendation": f"Определить условие «{phrase}» и добавить в логику метода шаг его проверки "
                                  "с ответом при невыполнении.",
                "rewrite": "", "question": f"Что считается «{phrase}» и какой ответ вернуть, если условие не выполнено?",
                "blocks": "development", "origin": "state_check",
            })
            if len(out) >= limit:
                return out
    return out


# ─────────────── проверка кодом: ограничение частоты за календарный период без границ периода ───────────────
# «Не больше N … за месяц / в сутки»: по дате какого события (операции или реакции на неё) и в каком часовом поясе
# считается период ограничения. Если в той же фразе это сказано («по дате …», «по времени …», UTC) — не срабатывает.
_PERIOD_LIMIT = re.compile(r"(?<![а-яё])(?:максимум|не более|не больше|не чаще|не свыше|только|лишь)\s+(?:[^.;]{0,60}?\s)?"
                           r"(?:за|в)\s+((?:календарн\w+|кажд\w+|одн\w+)\s+)?(месяц|сутки|день|недел\w+|год|час)\b", re.I)
_PERIOD_DEFINED = re.compile(r"по\s+дат\w*|по\s+времен\w*|по\s+местн\w*|час\w*\s+пояс|\bUTC\b|\bGMT\b", re.I)
_PERIOD_RULE = re.compile(r"(?:месяц|день|сутки|период|недел\w+)\w*\s+(?:определя\w+|счита\w+|отсчитыва\w+)\s+по\b", re.I)
# у модели уже есть кандидат о границах периода (не просто упоминание «в месяц»)
_PERIOD_WORDS = re.compile(r"пояс|границ|по\s+дат|по\s+времен|отсчит|какой\s+месяц|какому\s+месяцу|календарн\w*\s+месяц\w*\s+(?:огранич|считает)", re.I)
MAX_PERIOD_PROBES = 1


def period_probes(view: Any, requirements: Any, candidates: list[dict], *, limit: int = MAX_PERIOD_PROBES) -> list[dict]:
    """Кандидаты кода: ограничение количества за календарный период, у которого не задано, по какому событию и
    в каком часовом поясе считается период. Правило периода для другой величины (учёта операций) называется в
    тексте кандидата: оно не отвечает на вопрос, если ограничение на него не ссылается."""
    business = _req_lines(requirements, lambda r: r.get("kind") == "functional"
                          and not _BUSINESS_SECTION_SKIP.search(str(r.get("section") or "")))
    out: list[dict] = []
    for n in business:
        text = _line_text(view, n)
        for sent in _SENT.split(text):
            m = _PERIOD_LIMIT.search(sent)
            if not m or _PERIOD_DEFINED.search(sent):
                continue
            if any(n in {e.get("line_start", e.get("line")) for e in c.get("evidence") or []}
                   and _PERIOD_WORDS.search(str(c.get("title", ""))) for c in candidates):
                break
            period = (m.group(1) or "") + m.group(2)
            other = next(((k, s.strip()) for k in business if k != n for s in _SENT.split(_line_text(view, k))
                          if _PERIOD_RULE.search(s)), None)
            elsewhere = (f" Правило «{other[1]}» (строка {other[0]}) задано для другой величины, и неясно, "
                         "действует ли оно для ограничения.") if other else ""
            out.append({
                "title": f"Не определено, как считается период ограничения «за {period}»",
                "kind": "ambiguity", "criterion": "unambiguous", "severity": "major", "requirement_ids": [],
                "evidence": [{"quote": sent.strip()[:300], "line": n}],
                "problem": f"Ограничение действует «за {period}», но не сказано, по дате какого события (операции "
                           "или отправки реакции) и в каком часовом поясе считается период." + elsewhere,
                "scenario": "Операция совершена в последнюю минуту периода, а реакция на неё отправлена в первую "
                            "минуту следующего: неясно, к какому периоду относится реакция и действует ли ограничение.",
                "impact": "На границе периода реализации и тесты дадут разное число срабатываний.",
                "recommendation": "Указать событие и часовой пояс, по которым считается период ограничения.",
                "rewrite": "", "question": f"По дате какого события и в каком часовом поясе считается «{period}» "
                                           "ограничения?",
                "blocks": "testing", "origin": "period_check",
            })
            break
        if len(out) >= limit:
            break
    return out


# ─────────────── несколько независимых проходов линзы (слабые модели) ───────────────
# Flash от прохода к проходу находит разные пробелы описи (замер 27.11, 9 сохранённых ответов 3.6 Flash на
# официальном документе: С из эталона на уровне кандидатов — один проход 18,0 / 18,2 / 16,6 на входах c1 / c2 / c3,
# объединение двух — 19,4 / 19,4 / 17,8). Второй проход идёт по темам описи в обратном порядке: у длинного
# промпта слабая модель внимательнее к первым темам.
PASSES_BY_FAMILY = {"gemini-flash": 2, "gemini-flash-lite": 2, "gemini": 2}
SECOND_PASS_NOTE = ("\n\nЭто независимый второй проход линзы по тому же документу. Опись заполни, начиная с "
                    "последней темы и до первой (Т15 → Т1), затем кандидаты по тем же правилам.")
MAX_PASS_GAPS = 10


def passes_for(ctx: Any) -> int:
    """Сколько проходов: опция `analyst_passes` / переменная `BCC_ANALYST_PASSES`, иначе по семейству модели."""
    import os
    opts = getattr(ctx, "options", None)
    val = opts.get("analyst_passes") if isinstance(opts, dict) else getattr(opts, "analyst_passes", None)
    val = val if val is not None else os.environ.get("BCC_ANALYST_PASSES")
    if val not in (None, ""):
        try:
            return max(1, min(3, int(val)))
        except (TypeError, ValueError):
            pass
    llm = getattr(ctx, "llm", None)
    model = getattr(llm, "model", None) or getattr(getattr(llm, "provider", None), "default_model", None)
    if not model or str(getattr(llm, "provider_name", "")) not in ("gemini", ""):
        return 1
    try:
        from bcc_review.v2.providers import profiles
    except ImportError:  # pragma: no cover
        return 1
    return PASSES_BY_FAMILY.get(profiles.family(str(model)), 1)


class _NotedContext:
    """Контекст этапа, у которого к заданию промпта дописана заметка прохода (второй вызов не попадает в кэш
    первого и идёт по темам в другом порядке)."""

    def __init__(self, ctx: Any, note: str):
        self._ctx, self._note = ctx, note

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    def prompt(self, name: str, **variables: Any) -> tuple[str, str]:
        system, user = self._ctx.prompt(name, **variables)
        return system, user + self._note


def _near_duplicate(c: dict, kept: list[dict]) -> bool:
    """Тот же дефект из другого прохода: общая строка цитаты и не меньше 40 % слов заголовка."""
    lines = {e.get("line_start", e.get("line")) for e in c.get("evidence") or []}
    ts = _stems(str(c.get("title", "")))
    for k in kept:
        if not lines & {e.get("line_start", e.get("line")) for e in k.get("evidence") or []}:
            continue
        ks = _stems(str(k.get("title", "")))
        need = max(2, -(-min(len(ts), len(ks)) * 2 // 5))
        if len(ts & ks) >= need:
            return True
    return False


def merge_passes(outs: list[dict]) -> dict:
    """Ответы нескольких проходов → один: кандидаты первого прохода, затем новые кандидаты следующих (повтор —
    общая строка и 40 % слов заголовка), опись — все строки, кроме повторов (та же строка и тот же вопрос)."""
    if len(outs) == 1:
        return dict(outs[0])
    merged = dict(outs[0])
    cands: list[dict] = [c for c in outs[0].get("candidates") or [] if isinstance(c, dict)]
    cov: list = list(outs[0].get("coverage") or [])
    for o in outs[1:]:
        for c in o.get("candidates") or []:
            if isinstance(c, dict) and not _near_duplicate(c, cands):
                cands.append(c)
        have = {(r.get("line"), frozenset(_stems(str(r.get("question", ""))))) for r in cov if isinstance(r, dict)}
        for r in o.get("coverage") or []:
            if isinstance(r, dict) and (r.get("line"), frozenset(_stems(str(r.get("question", ""))))) not in have:
                cov.append(r)
    merged["candidates"], merged["coverage"] = cands, cov
    return merged


def _run_passes(ctx: Any, lens_run, n: int) -> tuple[list[dict], list[str]]:
    """`n` проходов параллельно; упавший проход не роняет этап, если удался хотя бы один."""
    if n <= 1:
        return [dict(lens_run(ctx, "analyst"))], []
    import concurrent.futures as cf
    contexts = [ctx] + [_NotedContext(ctx, SECOND_PASS_NOTE if i == 1 else SECOND_PASS_NOTE + f" Проход {i + 1}.")
                        for i in range(1, n)]
    results: list[Any] = [None] * n
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(lens_run, c, "analyst"): i for i, c in enumerate(contexts)}
        for f in cf.as_completed(futs):
            i = futs[f]
            try:
                results[i] = dict(f.result())
            except Exception as exc:  # noqa: BLE001 — разбирается ниже
                results[i] = exc
    ok = [r for r in results if isinstance(r, dict)]
    if not ok:
        raise next(r for r in results if isinstance(r, BaseException))
    notes = [f"Аналитик: проход {i + 1} из {n} не удался ({type(r).__name__}); взяты остальные"
             for i, r in enumerate(results) if isinstance(r, BaseException)]
    return ok, notes


def run(ctx, lens_run=None) -> dict:
    """Запуск линзы с постобработкой. `lens_run(ctx, name)` — общий запуск из `stages/lens.py` (№01);
    он сам берёт `MAX_OUTPUT_TOKENS` из этого модуля. На слабых моделях (см. `passes_for`) — несколько
    независимых проходов, объединённых `merge_passes`."""
    if lens_run is None:
        from . import lens as _lens  # каркас №01
        lens_run = _lens.run
    m = maturity(getattr(ctx, "view", None))
    n = passes_for(ctx)
    outs, notes = _run_passes(ctx, lens_run, n)
    for note in notes:
        warn = getattr(ctx, "warn", None)
        if callable(warn):
            warn(note)
    out = merge_passes(outs)
    view = getattr(ctx, "view", None)
    out["candidates"] = postprocess(out.get("candidates") or [], mature=m["mature"])
    out["coverage"] = coverage(out.get("coverage"), limit=MAX_COVERAGE * len(outs))
    if not m["mature"]:  # вычитанный документ — только расхождения (см. `postprocess`), пробелы описи не добираем
        reqs = getattr(ctx, "requirements", None)
        probes = state_probes(view, reqs, out["candidates"])
        probes += period_probes(view, reqs, out["candidates"])
        gaps = coverage_gaps(out["coverage"], out["candidates"] + probes, view,
                             limit=MAX_GAPS if len(outs) == 1 else MAX_PASS_GAPS)
        out["candidates"] += probes + gaps
        out["coverage_gaps"] = len(gaps)
        out["code_checks"] = len(probes)
    out["passes"] = len(outs)
    out["document_maturity"] = m
    return out
