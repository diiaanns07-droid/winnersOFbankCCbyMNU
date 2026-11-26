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
    ("indefinite", r"\bнекотор\w+\b|\bнескольк\w+\b|\bмногие\b|\bбольшинств\w+\b|\bряд\s+\w+(?:ов|ей|ий)\b|"
                   r"\bи/или\b|\bлибо\s+иные\b",
     "неопределённое количество или выбор"),
]
COMPILED = [(cat, re.compile(rx, re.I), why) for cat, rx, why in VOCAB]
QUOTED_SPAN = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")
METADATA_KEYS = re.compile(r"^(наименование|продукт|бизнес-процесс|тип работы|влияние|задача в|author|developer|"
                           r"controller|framework|gitlab|swagger|url type|поле|parameter|параметр)\b", re.I)
CHECKLIST = re.compile(r"\bДа\s*/\s*Нет\b", re.I)
NUMBER = re.compile(r"\d")

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


def run(doc: Doc, out: dict, requirements: list[dict] | None = None, excluded: list[dict] | None = None) -> None:
    open_list_done = False
    for x in obligation_lines(doc, requirements, excluded):
        text = x.joined
        masked = _mask_quotes(text)
        for cat, rx, why in COMPILED:
            for m in rx.finditer(masked):
                word = text[m.start():m.end()].strip()
                if cat == "comparison" and NUMBER.search(text):
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
