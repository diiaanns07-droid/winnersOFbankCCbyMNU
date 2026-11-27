"""Приёмка входа до модели (№57): похож ли документ на требования к системе и хватает ли в нём текста.

Жюри может подать не ТЗ (новость, рецепт, договор аренды, резюме) или одну строку. Модель на таком входе
выдумывает дефекты и ставит «нельзя в разработку» — это глупый вердикт. Код решает до модели по признакам
требований, без слов конкретного документа:

* обязательство: «должен», «обязан», «необходимо», «shall», «must», «тиіс», «керек» …;
* предмет-система: «система», «сервис», «приложение», «API», «экран», «поле», «статус», «интеграция»,
  «пользователь», «system», «user», «жүйе» …;
* номер пункта требования: «Ф-1», «FR-2», «REQ-3», «US-4», «3.1.2»; пользовательская история
  «Как …, я хочу» / «As a …, I want»; таблица.

Документ похож на требования, если есть строка «обязательство + система», пользовательская история или слово
«требования» / «ТЗ» / «specification» в заголовке; иначе — если нет признаков чужого жанра (договор между людьми,
резюме, рецепт, новость) и есть хоть один признак: система или предмет продукта, два пронумерованных пункта,
таблица. Порог щадящий: короткое бизнес-правило «СН-1. Лимит снятия — 200 000 в сутки» его проходит. Порог щадящий: настоящее ТЗ на любом
языке (русский, казахский, английский) его проходит, а рецепт и договор аренды — нет.
"""
from __future__ import annotations

import re

OBLIGATION = re.compile(
    r"\b(?:долж(?:ен|на|но|ны)|обязан\w*|обязательн\w*|необходимо|требуется|нужно|следует|"
    r"обеспечива\w+|позволя\w+|поддержива\w+|отобража\w+|формиру\w+|провер(?:яет|яют|ять)|"
    r"shall|must|should|required|will\s+(?:be\s+able|allow|provide|support|display|send)|"
    r"тиіс|тиісті|керек|қажет|міндетті|мүмкіндік\s+береді)\b", re.I)
SYSTEM = re.compile(
    r"\b(?:(?:под)?систем[аеуыо]й?\b|(?:под)?систем(?:ам|ами|ах)\b|сервис\w*|приложени\w*|модул\w*|платформ\w*|портал\w*|"
    r"интерфейс\w*|экран\w*|кнопк\w*|пол(?:е|я|ю|ей|ям|ями)\b|баз\w*\s+данных|БД\b|интеграц\w*|"
    r"статус\w*|уведомлени\w*|пользовател\w*|личн\w+\s+кабинет\w*|авторизац\w*|аутентификац\w*|"
    r"веб-\w+|мобильн\w+\s+(?:приложени|банк)\w*|бэкенд\w*|фронтенд\w*|микросервис\w*|"
    r"API|REST|SOAP|JSON|XML|endpoint\w*|SQL|CRM|АБС|"
    r"system|service|application|app|interface|screen|button|field|database|integration|status|"
    r"notification|user|login|backend|frontend|"
    r"жүйе\w*|қосымша\w*|пайдаланушы\w*|мәртебе\w*|хабарлам\w*|интерфейс\w*|"
    # предмет банковского продукта: бизнес-правила без слова «система» («Лимит снятия — 200 000 в сутки»)
    r"клиент\w*|карт(?:а|ы|у|е|ой|ам|ами|ах|очк\w*)|сч[её]т(?:а|у|ом|е|ов|ам)?|лимит\w*|тариф\w*|комисси\w*|"
    r"заявк\w*|плат[её]ж\w*|перевод\w*|транзакц\w*|операци\w*|оператор\w*|кредит\w*|депозит\w*|"
    r"банкомат\w*|выписк\w*|account|card|payment|transfer|limit|customer|client|transaction|"
    r"шот\w*|төлем\w*|аударым\w*)\b", re.I)
# жанр «не ТЗ»: договор между людьми, резюме, рецепт, новость. Срабатывает, только если нет строки
# «обязательство + система», пользовательской истории и слова «требования» в заголовке
GENRES = {
    "договор": re.compile(r"\bдоговор\w*\s+(?:аренды|найма|купли|подряда|дарения|займа|поставки)|\bарендатор\w*|"
                          r"\bарендодател\w*|\bнаймодател\w*|\bнанимател\w*|\btenant\b|\blandlord\b|"
                          r"\blease\s+agreement\b", re.I),
    "резюме": re.compile(r"\bрезюме\b|\bопыт\s+работы\b|\bобразование\b|\bнавыки\b|\bwork\s+experience\b|"
                         r"\beducation\b|\bskills\b|\bcurriculum\s+vitae\b", re.I),
    "рецепт": re.compile(r"\bингредиент\w*|\bрецепт\w*|\bвыпека\w*|\bдуховк\w*|\bзапека\w*|\bобжар\w*|"
                         r"\bперемешай\w*|\bвзбей\w*|\bingredients?\b|\brecipe\b|\bbake\b|\boven\b", re.I),
    "новость": re.compile(r"\bсообщил\w*|\bзаявил\w*|\bпо\s+словам\b|\bвчера\b|\bмэр\w*|\bкорреспондент\w*|"
                          r"\bжурналист\w*|\bпогод\w+|\breported\b|\byesterday\b|\bmayor\b", re.I),
}
REQ_ID = re.compile(r"^\s*(?:[*#>-]\s*)*(?:\*\*)?(?:[A-Za-zА-ЯЁа-яё]{1,6}[-_ .]?\d+(?:[.\-]\d+)*|\d+(?:\.\d+){1,4})"
                    r"(?:\*\*)?[.):\s]")
TITLE = re.compile(r"требовани|техническ\w+\s+задани|\bТЗ\b|\bФТ\b|\bБТ\b|спецификац|requirements?|specification|"
                   r"\bSRS\b|\bPRD\b|талап", re.I)
STORY = re.compile(r"\bкак\s+[\w\- ]{2,40},\s*я\s+хочу\b|\bas\s+an?\s+[\w\- ]{2,40},\s*I\s+want\b", re.I)
TABLE = re.compile(r"^[^|]*\|[^|]*\|")
WORD = re.compile(r"[^\W\d_]{2,}", re.U)

MIN_WORDS = 8  # меньше (и нет номера пункта «Ф-1.») — «слишком мало текста»: проверять требования не по чему


def _words_ru(n: int) -> str:
    tail = "слово" if n % 10 == 1 and n % 100 != 11 else (
        "слова" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "слов")
    return f"{n} {tail}"


def _content(view: dict) -> list[str]:
    return [str(x.get("text") or "") for x in view.get("lines") or [] if str(x.get("text") or "").strip()]


def assess(view: dict) -> dict:
    """``{"kind": "ok" | "not_requirements" | "too_short", "words": N, "signals": {...}, "reason": "…"}``."""
    lines = _content(view)
    body = [t for t, x in zip(lines, [x for x in view.get("lines") or [] if str(x.get("text") or "").strip()])
            if not x.get("heading")]
    words = sum(len(WORD.findall(t)) for t in lines)
    sig = {"obligation_system": 0, "system": 0, "obligation": 0, "req_id": 0, "story": 0, "table": 0, "title": 0}
    for t in lines:
        s, o = bool(SYSTEM.search(t)), bool(OBLIGATION.search(t))
        sig["system"] += s
        sig["obligation"] += o
        sig["obligation_system"] += s and o
        sig["req_id"] += bool(REQ_ID.match(t))
        sig["story"] += bool(STORY.search(t))
        sig["table"] += bool(TABLE.match(t))
    heads = lines[:1] + [str(x.get("text") or "") for x in view.get("lines") or [] if x.get("heading")]
    sig["title"] = sum(bool(TITLE.search(t)) for t in heads)
    genre = [g for g, rx in GENRES.items() if sum(bool(rx.search(t)) for t in lines) >= 2
             or any(rx.search(t) for t in heads[:1])]
    strong = sig["obligation_system"] >= 1 or sig["story"] >= 1 or sig["title"] >= 1
    looks = strong or (not genre and (sig["system"] >= 1 or sig["req_id"] >= 2 or sig["table"] >= 2))
    sig["genre"] = genre
    if (words < MIN_WORDS and not sig["req_id"] and len(body) <= 2) or words < 4:
        return {"kind": "too_short", "words": words, "signals": sig,
                "reason": (f"Слишком мало текста для проверки требований: {_words_ru(words)}. Модель не вызывалась, вердикт "
                           "не выносится — пришлите ТЗ целиком: роли, функции, поля, статусы, ограничения.")}
    if not looks:
        return {"kind": "not_requirements", "words": words, "signals": sig,
                "reason": ("Документ не похож на требования к системе: нет обязательств системы («должна», «shall»), "
                           "ролей, интерфейсов, полей и статусов. Модель не вызывалась, вердикт не выносится — "
                           "проверьте, тот ли файл передан.")}
    return {"kind": "ok", "words": words, "signals": sig, "reason": "", "note": size_note(view)}


BIG_CHARS = 80_000  # ≈ 40 страниц: с этого объёма отчёт говорит, что именно прочитано


def size_note(view: dict) -> str:
    """Большой документ: «прочитано целиком — строки 1–N, ≈P стр.» (страницы PDF — по файлу, иначе 2000 знаков)."""
    lines = view.get("lines") or []
    chars = sum(len(str(x.get("text") or "")) for x in lines)
    if chars < BIG_CHARS or not lines:
        return ""
    pages = view.get("pages") if isinstance(view.get("pages"), int) and view.get("pages") else None
    approx = f"{pages} стр." if pages else f"≈{max(1, round(chars / 2000))} стр."
    last = int(lines[-1].get("n") or len(lines))
    return (f"Большой документ: {approx}, {last} строк, {chars // 1000} тыс. знаков. Прочитан целиком — строки "
            f"1–{last}: нарезка шла частями, рецензенты видели весь текст. Реестр ограничен главными дефектами; "
            "мелкие замечания по отдельным разделам лучше проверить отдельным прогоном раздела.")
