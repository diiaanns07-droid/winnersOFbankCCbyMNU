"""Язык требований (ISO/IEC/IEEE 29148, п. 5.2.7): размытые и субъективные слова, лазейки,
открытые перечни, неизмеримые сравнения.

Ищется только в строках-обязательствах: не в заголовках, примерах, JSON, метаданных и шаблонах.
Находка — сигнал для линз. Кандидат — только открытый перечень в перечислении правил или кодов.
"""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, quoted, signal

# (категория, шаблон, пояснение)
VOCAB: list[tuple[str, str, str]] = [
    ("vague_time", r"\bв\s+(?:тот\s+же\s+)?момент\b(?!\s+(?:времени\s+)?(?:\d|получени|создани|сохранени))",
     "момент времени не задан измеримо: нет допуска и точки отсчёта"),
    ("vague_time", r"\bмгновенн\w*|\bнемедленн\w*|\bсвоевременн\w*|\bоперативн\w*|\bв\s+реальном\s+времени\b|"
                   r"\bв\s+кратчайш\w+\s+срок\w*|\bкак\s+можно\s+(?:быстрее|скорее|раньше)\b|\bбез\s+задерж\w*",
     "срок не задан числом"),
    ("vague_quality", r"\bбыстр(?:о|ый|ая|ое|ые|ого|ому)\b|\bудобн\w*|\bинтуитивн\w*|\bдружелюбн\w*|"
                      r"\bэффективн\w*|\bоптимальн\w*|\bнадёжн\w*|\bнадежн\w*|\bгибк\w*|\bкачественн\w*|"
                      r"\bсовременн\w*|\bпрозрачн\w*|\bпростой\b|\bпонятн\w*|\bкрасив\w*|\bнаглядн\w*",
     "субъективная оценка без измеримого критерия"),
    ("vague_quality", r"\b(?:корректн|правильн|адекватн|нормальн|разумн|приемлем|достаточн|соответствующ)\w*",
     "оценочное слово: не сказано, что именно считать выполнением"),
    ("loophole", r"\bпо\s+возможности\b|\bпри\s+необходимости\b|\bв\s+случае\s+необходимости\b|"
                 r"\bпо\s+усмотрению\b|\bкак\s+правило\b|\bесли\s+(?:это\s+)?возможно\b|\bжелательно\b|"
                 r"\bрекомендуется\b|\bпри\s+желании\b|\bпо\s+мере\s+возможности\b|\bесли\s+применимо\b",
     "лазейка: обязательство можно не выполнять"),
    ("open_list", r"\bи\s+т\.\s?д\.?|\bи\s+т\.\s?п\.?|\bи\s+др\.|\bи\s+прочее\b|\bи\s+прочие\b|\bи\s+пр\.|"
                  r"\bи\s+так\s+далее\b|\bи\s+далее\b|\bи\s+другие\b|\bи\s+иные\b|"
                  r"\bвключая,?\s+но\s+не\s+ограничиваясь\b|\w\s?(?:\.\.\.|…)\s*(?:$|[).;])",
     "открытый перечень: состав не определён"),
    ("comparison", r"\b(?:лучше|хуже|быстрее|медленнее|удобнее|проще|надёжнее|надежнее|точнее|понятнее|"
                   r"дешевле|эффективнее)\b|\b(?:улучшить|повысить|ускорить|увеличить|снизить|сократить|"
                   r"минимизировать|максимизировать|оптимизировать)\b",
     "сравнение без базы и числа"),
    # «несколько раз» — повторяемость («можно оплатить несколько раз», «если клиент несколько раз сменил»), а не
    # неопределённое количество: на исправленных ТЗ это ложная подсказка
    ("indefinite", r"\bнекотор\w+\b|\bнескольк\w+\b(?!\s+раз\b)|\bмногие\b|\bбольшинств\w+\b|\bряд\s+\w+(?:ов|ей|ий)\b|"
                   r"\bи/или\b|\bлибо\s+иные\b",
     "неопределённое количество или выбор"),
]
COMPILED = [(cat, re.compile(rx, re.I), why) for cat, rx, why in VOCAB]
QUOTED_SPAN = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")
METADATA_KEYS = re.compile(r"^(наименование|продукт|бизнес-процесс|тип работы|влияние|задача в|author|developer|"
                           r"controller|framework|gitlab|swagger|url type|поле|parameter|параметр)\b", re.I)
CHECKLIST = re.compile(r"\bДа\s*/\s*Нет\b", re.I)
NUMBER = re.compile(r"\d")
# «X считается Y в момент Z», «отказ считается оформленным в момент, когда …» — определение момента событием, а не
# размытый срок; «узнать в момент покупки» (обещание реакции без допуска) остаётся сигналом
# «снимок / остаток / курс / состояние в момент Y» — какое значение данных берётся, тоже определение момента
DEFINES_MOMENT = re.compile(r"\b(?:счита\w+|признаё\w+|признае\w+|определя\w+|фиксиру\w+|снимо?к\w*|"
                            r"состояни\w*|значени\w*|остат\w*|курс\w*|сальдо|баланс\w*)\b", re.I)
CONDITION = re.compile(r"(?:^|[\s,(])(?:если|когда|при)\s", re.I)
# раздел целей: «Снизить число обращений» — бизнес-цель, а не проверяемое требование
GOAL_SECTION = re.compile(r"(?:^|›\s*)(?:\d+[.)]?\s*)?(?:цел[иья]\b|бизнес-цел|goals?\b|objectives?\b)", re.I)

AUDIENCE = {"vague_time": ("analyst", "qa", "risk"), "vague_quality": ("analyst", "qa"),
            "loophole": ("analyst",), "open_list": ("analyst", "qa"), "comparison": ("analyst", "qa"),
            "indefinite": ("analyst",)}
CAT_RU = {"vague_time": "размытый срок", "vague_quality": "субъективная оценка", "loophole": "лазейка",
          "open_list": "открытый перечень", "comparison": "неизмеримое сравнение",
          "indefinite": "неопределённость"}


def obligation_lines(doc: Doc, requirements: list[dict] | None, excluded: list[dict] | None) -> list[Line]:
    """Строки-обязательства: в диапазонах требований (если нарезка есть) и без шаблонов и примеров."""
    ranges = None
    if requirements:
        ranges = [(int(r.get("line_start") or 0), int(r.get("line_end") or r.get("line_start") or 0))
                  for r in requirements if r.get("line_start")]
    skip = [(int(e.get("line_start") or 0), int(e.get("line_end") or 0)) for e in (excluded or [])]
    res = []
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading or x.is_sep:
            continue
        in_req = ranges is not None and any(a <= x.n <= b for a, b in ranges)
        if ranges is not None and not in_req:
            continue
        if not in_req and any(a <= x.n <= b for a, b in skip):
            continue  # исключённый фрагмент (шаблон, пример); строка требования важнее грубого диапазона
        if x.cells is not None:
            if CHECKLIST.search(x.joined) or (len(x.cells) == 2 and METADATA_KEYS.match(x.cells[0])):
                continue
        if ranges is None and x.cells is None and len(x.text.split()) < 4:
            continue  # короткая строка без нарезки — скорее заголовок или подпись
        res.append(x)
    return res


def _mask_quotes(s: str) -> str:
    return QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), s)


ENUM_BEFORE = re.compile(r"((?:[\w«»\"]+[\w\s«»\"\-]{0,30},\s*){1,}[\w«»\"]+[\w\s«»\"\-]{0,30}?)\s*$")
CODE_ENUM = re.compile(r"[1-5]\d\d(?:\s*,\s*[1-5]\d\d)+\s*$")


NFR_SECTION = re.compile(r"нефункциональн|non-?functional|nfr|качеств\w+\s+характеристик", re.I)
NFR_ID = re.compile(r"^\s*(?:НФ|НФТ|NFR|NF)-?\d+", re.I)
# размытые характеристики качества в НФТ (без «корректно» и «достаточно» — они слишком общие)
NFR_VAGUE = re.compile(
    r"\bбыстр(?:о|ый|ая|ое|ые|ого|ому)\b|\bмгновенн\w*|\bнемедленн\w*|\bсвоевременн\w*|\bоперативн\w*|"
    r"\bв\s+реальном\s+времени\b|\bудобн\w*|\bинтуитивн\w*|\bнадёжн\w*|\bнадежн\w*|\bвысок\w+\s+нагрузк\w*|"
    r"\bвсегда\s+актуальн\w*|\bбез\s+задерж\w*|\bстабильн\w*|\bотзывчив\w*|"
    r"\bточн(?:о|ый|ая|ое|ые)\b|\bбез\s+(?:каких-либо\s+)?ошиб\w*|\bкруглосуточн\w*|\bбесперебойн\w*|"
    r"\bбезотказн\w*|\bбез\s+сбо\w*|\b(?:всегда|постоянно)\s+доступ\w*|\bв\s+любое\s+время\b|\bмасштабируем\w*|"
    r"\bотказоустойчив\w*|\bвысок\w+\s+(?:доступност|производительност|скорост)\w*", re.I)


# срок в НФТ: «в течение минуты», «не позднее 5 с», «не дольше 500 мс», «за 2 секунды»
NFR_TIME = re.compile(
    r"\b(?:в\s+течение|не\s+позднее|не\s+позже|не\s+дольше|не\s+более|не\s+больше|за|до)\s+"
    r"(?:\d+(?:[.,]\d+)?\s*|од(?:ну|ной|ин)\s+|дв[ае]\s+|тр[её]х?\s+|пят\w*\s+|десят\w*\s+)?"
    r"(?:мс|миллисекунд\w*|с\b|сек\w*|секунд\w*|минут\w*|мин\b|час\w*)", re.I)
# доля операций, на которой меряется срок: «для 95 % запросов», «p95», «95-й перцентиль», «в 99 % случаев»
NFR_SHARE = re.compile(r"\d+(?:[.,]\d+)?\s*%|\bp\d{2}\b|перцентил|процентил|percentile|квантил|\bпроцент\w*", re.I)
# пакетная или регламентная задача — одна операция, доля к ней неприменима
NFR_BATCH = re.compile(r"пакетн|регламентн|ежемесячн|ежедневн|ночн\w+\s+(?:обработк|задач|расч)|\bраз\s+в\s+(?:сутки|день|месяц)",
                       re.I)


def _nfr_share(doc: Doc, out: dict) -> None:
    """НФТ со сроком, а доли операций нет ни в одном НФТ документа: «в течение минуты после получения события» — для
    каждой операции, в среднем или для 99 %? Если доля где-то задана, отдельные сроки (тайм-ауты) не трогаем."""
    hits = []
    nfr = [x for x in doc.lines if x.text and not x.is_code and not x.is_heading
           and (NFR_SECTION.search(x.section or "") or NFR_ID.match(x.text))]
    if any(NFR_SHARE.search(x.joined) for x in nfr):
        return  # доля операций где-то задана — отдельные сроки (тайм-ауты, свежесть данных) судим не по этому правилу
    for x in nfr:
        if x.cells is not None:
            continue
        for part in re.split(r"(?<=[.;])\s+(?=(?:\*\*)?[А-ЯЁA-Z])", x.joined):
            m = NFR_TIME.search(part)
            if m and not NFR_SHARE.search(part) and not NFR_BATCH.search(part) \
                    and all(h[1] != part.strip() for h in hits):
                hits.append((x, part.strip(), m.group(0)))
                break
    if not hits:
        return
    x, part, when = hits[0]
    out["candidates"].append(candidate(
        "language.nfr_no_share",
        title=f"Срок в нефункциональном требовании без доли операций: {quoted(when)}",
        kind="unverifiable", criterion="verifiable", severity="major", blocks="testing",
        evidence=[ev(h[0], h[1]) for h in hits[:3]],
        problem=(f"{quoted(part)}: срок есть, но не сказано, для какой доли операций он выполняется (каждая, 95 % или "
                 "99 % за сутки), при какой нагрузке и где начинается и заканчивается замер."
                 + (f" Таких мест: {len(hits)}." if len(hits) > 1 else "")),
        scenario=("Нагрузочный тест: 98 % операций укладываются в срок, 2 % — нет. Одна сторона считает требование "
                  "выполненным, другая — нарушенным: «каждая операция» или «в среднем» документ не уточняет."),
        impact="Требование нельзя принять или отклонить; эксплуатация не знает, при какой задержке поднимать тревогу.",
        recommendation=("Добавить долю операций и условия замера: «… для 95 % (99 %) операций за сутки при нагрузке до "
                        "N в секунду; замер — от получения события до передачи сообщения»."),
        rewrite=f"{part.rstrip('.')} для <уточнить: 95 или 99> % операций за сутки при нагрузке до <уточнить: N> в секунду.",
        question="Для какой доли операций и при какой нагрузке должен выполняться этот срок?",
    ))


def _nfr_candidate(doc: Doc, out: dict) -> None:
    """Нефункциональное требование без числа, но с размытым сроком или оценкой: «быстро», «мгновенно»."""
    hits = []
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading or x.cells is not None:
            continue
        if not (NFR_SECTION.search(x.section or "") or NFR_ID.match(x.text)):
            continue
        if NUMBER.search(re.sub(r"^\s*(?:НФ|НФТ|NFR|NF)-?\d+\.?", "", x.text, flags=re.I)):
            continue
        masked = _mask_quotes(x.joined)
        words = [x.joined[m.start():m.end()] for m in NFR_VAGUE.finditer(masked)]
        if words:
            hits.append((x, words))
    if not hits:
        return
    x, words = hits[0]
    allw = [w for _, ws in hits for w in ws]
    one = len(hits) == 1
    # говорим о конкретных строках: числа в соседних НФТ не делают эти строки проверяемыми
    where = (f"В нефункциональном требовании {quoted(x.joined)} нет измеримого значения"
             if one else f"В {len(hits)} нефункциональных требованиях нет измеримого значения, например {quoted(x.joined)}")
    out["candidates"].append(candidate(
        "language.nfr_unverifiable",
        title=(f"Нефункциональное требование без числа: {', '.join(quoted(w) for w in allw[:3])}" if one else
               f"Нефункциональные требования без чисел: {', '.join(quoted(w) for w in allw[:3])}"),
        kind="unverifiable", criterion="verifiable", severity="major", blocks="testing",
        evidence=[ev(h[0]) for h in hits[:3]],
        problem=(f"{where}. Слова {', '.join(quoted(w) for w in allw[:4])} нельзя проверить тестом: не сказано, "
                 "какое время, доля запросов или нагрузка считаются выполнением."),
        scenario="Нагрузочный тест показывает 3 секунды на 95-й перцентили: одна сторона считает это «быстро», другая — нет.",
        impact="Требование нельзя принять или отклонить; эксплуатационные риски не ограничены договорённостью.",
        recommendation=("Задать измеримые значения: время ответа и доля запросов (например, p95), нагрузка, "
                        "точка начала и конца замера, допустимая задержка данных."),
        rewrite="<уточнить: операция> выполняется не дольше <уточнить: N> с для 95 % запросов при нагрузке <уточнить> rps.",
    ))


def run(doc: Doc, out: dict, requirements: list[dict] | None = None, excluded: list[dict] | None = None) -> None:
    _nfr_candidate(doc, out)
    _nfr_share(doc, out)
    open_list_done = False
    for x in obligation_lines(doc, requirements, excluded):
        text = x.joined
        masked = _mask_quotes(text)
        for cat, rx, why in COMPILED:
            for m in rx.finditer(masked):
                word = text[m.start():m.end()].strip()
                if cat == "comparison" and (NUMBER.search(text) or GOAL_SECTION.search(x.section or "")):
                    continue
                if cat == "indefinite" and m.group(0).lower().startswith("нескольк"):
                    c0 = max(masked.rfind(";", 0, m.start()), masked.rfind(".", 0, m.start())) + 1
                    if CONDITION.search(masked[c0:m.start()]):
                        continue  # «если номер привязан к нескольким картам» — «больше одной», а не размытое число
                if cat == "vague_time" and "момент" in m.group(0).lower():
                    c0 = max(masked.rfind(";", 0, m.start()), masked.rfind(".", 0, m.start())) + 1
                    if DEFINES_MOMENT.search(masked[c0:m.start()]):
                        continue
                if cat == "open_list":
                    before = masked[:m.start()]
                    enum = ENUM_BEFORE.search(before)
                    is_codes = bool(CODE_ENUM.search(before))
                    if enum and not open_list_done:
                        open_list_done = _open_list_candidate(x, text, m, is_codes, out)
                s0 = max(0, text.rfind(".", 0, m.start()) + 1, text.rfind("|", 0, m.start()) + 1)
                e1 = text.find(".", m.end())
                frag = text[s0:e1 + 1 if e1 != -1 and e1 - s0 < 200 else min(len(text), s0 + 200)].strip()
                out["signals"].append(signal(
                    f"language.{cat}", x, frag,
                    f"{CAT_RU[cat].capitalize()}: {quoted(word)} — {why}.", AUDIENCE[cat], "ambiguity"))
                break


def _open_list_candidate(x: Line, text: str, m: re.Match, is_codes: bool, out: dict) -> bool:
    s0 = max(0, text.rfind(".", 0, m.start()) + 1, text.rfind("|", 0, m.start()) + 1)
    e1 = text.find(".", m.end())
    if e1 != -1 and text[e1 - 1:e1 + 1] in ("т.", "п.", "р.") and e1 + 1 < len(text):
        e2 = text.find(".", e1 + 1)
        e1 = e2 if e2 != -1 else e1
    frag = text[s0:(e1 + 1) if e1 != -1 else len(text)].strip()
    marker = text[m.start():m.end()].strip()
    what = "перечень кодов ответа" if is_codes else "перечень"
    out["candidates"].append(candidate(
        "language.open_list",
        title=f"Открытый {what}: {quoted(marker)} вместо полного списка",
        kind="api_contract" if is_codes else "ambiguity", criterion="unambiguous",
        severity="major" if is_codes else "minor", blocks="development" if is_codes else "none",
        evidence=[ev(x, frag)],
        problem=(f"В правиле {quoted(frag)} перечень заканчивается словами {quoted(marker)}: какие ещё элементы "
                 "входят в перечень, не сказано, и каждый поймёт его по-своему."),
        scenario=("Появляется значение, которого нет в явном перечне: одна команда считает, что оно входит в "
                  "«и далее», другая — что нет."),
        impact="Реализация и тесты расходятся на непоименованных значениях; спор при приёмке.",
        recommendation="Заменить открытый перечень полным списком значений или правилом, по которому значение "
                       "однозначно относится к перечню.",
        rewrite=(frag[:m.start() - s0].rstrip(" ,") + " <уточнить: полный перечень>").strip(),
    ))
    return True
