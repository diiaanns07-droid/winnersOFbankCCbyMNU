"""Единицы измерения: одна величина в разных единицах без правила пересчёта.

* деньги: основная и минорная единица одной валюты (тенге/тиын, рубль/копейка, доллар/евро/цент);
* минорная единица с дробной частью («в … с двумя знаками после точки»);
* время: «по UTC» без смещения и «UTC+N» для одного и того же поля;
* период подсчёта: один и тот же лимит «за час» и «за сутки» (сигнал);
* описание поля API и текст требований задают одну величину в разных единицах: «Срок кредита в днях» ↔
  «на срок от 6 до 60 месяцев», «Ставка, % в месяц» ↔ «ставка 14 % годовых».
Связка ищется по фразе «<величина> в <единица>» — так сравниваются именно величины, а не слова.
"""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, quoted, signal, tables

# Формы: именительный мн. ч., предложный мн. ч., родительный мн. ч.
CURRENCIES = [
    # (major-шаблон, minor-шаблон, формы основной, формы минорной)
    (r"тенге|₸|kzt", r"тиын\w*", ("тенге", "тенге", "тенге"), ("тиыны", "тиынах", "тиынов")),
    (r"рубл\w*|₽|rub", r"копе\w*", ("рубли", "рублях", "рублей"), ("копейки", "копейках", "копеек")),
    (r"доллар\w*|usd|\$", r"цент\w*", ("доллары", "долларах", "долларов"), ("центы", "центах", "центов")),
    (r"евро|eur|€", r"(?:евро)?цент\w*", ("евро", "евро", "евро"), ("центы", "центах", "центов")),
]
DENOM = r"(?:\bв|\bчисл\w*|\bцел\w+\s+числ\w*|\bсумм\w*\s+в)\s+"
SUBJECT_STOP = re.compile(r"[,;:(]|\s(?:и|или|а также)\s")
FRACTION = re.compile(r"знак\w*\s+после\s+(?:точки|запятой)|дробн\w*|десятичн\w*", re.I)


def _subject(text: str, pos: int) -> str:
    """Фраза перед единицей: последние слова клаузы («сумму списания» в «…, сумму списания в копейках»)."""
    head = text[:pos]
    cut = 0
    for m in SUBJECT_STOP.finditer(head):
        cut = m.end()
    for sep in ("|", "."):
        k = head.rfind(sep)
        if k + 1 > cut:
            cut = k + 1
    words = head[cut:].split()
    return " ".join(words[-3:]).strip().lstrip("—–-−:;,. ").strip()


def _stem(phrase: str) -> str:
    w = [x for x in re.findall(r"[а-яёa-z]+", phrase.lower()) if len(x) > 2]
    return w[0][:5] if w else ""


def _conversion(doc: Doc, major: str, minor: str) -> Line | None:
    rx = re.compile(rf"1\s*(?:{major})\s*=\s*100\s*(?:{minor})|100\s*(?:{minor})\s*=\s*1\s*(?:{major})|"
                    rf"(?:пересч\w*|конверт\w*|округл\w*)[^.]{{0,60}}(?:{minor})|"
                    rf"(?:{minor})[^.]{{0,60}}(?:пересч\w*|округл\w*|конверт\w*)", re.I)
    for x in doc.lines:
        if x.text and rx.search(x.joined):
            return x
    return None


def rule_currency(doc: Doc, out: dict) -> None:
    for major, minor, MJ, MN in CURRENCIES:
        rx_minor = re.compile(rf"{DENOM}(?:{minor})", re.I)
        rx_major = re.compile(rf"{DENOM}(?:{major})(?![\w])", re.I)
        minors: list[tuple[Line, str, str]] = []
        majors: list[tuple[Line, str, str]] = []
        for x in doc.lines:
            if not x.text or x.is_code:
                continue
            t = x.joined
            for m in rx_minor.finditer(t):
                minors.append((x, _subject(t, m.start()), t[m.start():m.end()].strip()))
            for m in rx_major.finditer(t):
                majors.append((x, _subject(t, m.start()), t[m.start():m.end()].strip()))
        # дробная часть у минорной единицы — отдельное замечание
        for x, subj, unit in minors:
            tail = x.joined[x.joined.find(unit):]
            if FRACTION.search(tail[:60]):
                frag = f"{subj} {tail[:60].split('|')[0]}".strip() if subj else tail[:60].split("|")[0].strip()
                if frag not in x.joined:
                    frag = x.joined
                evidence = [ev(x, frag)]
                field = next((c for c in (x.cells or []) if re.fullmatch(r"[A-Za-z_]\w*", c)), "")
                if field:  # пример значения этого поля (JSON) — вторая сторона расхождения
                    ex = next((y for y in doc.lines if y is not x and f'"{field}"' in y.joined), None)
                    if ex is not None:
                        jm = re.search(r"\{[^{}]*\}", ex.joined)
                        evidence.append(ev(ex, jm.group(0) if jm else ex.joined))
                out["candidates"].append(candidate(
                    "units.minor_fraction",
                    title=f"Величина в минорных единицах ({MN[0]}) описана с дробной частью",
                    kind="unit_mismatch", criterion="unambiguous", severity="major", blocks="both",
                    evidence=evidence,
                    problem=(f"{quoted(frag)}: {MN[0]} — наименьшая единица валюты, дробной части у неё нет. "
                             f"Похоже, имелись в виду {MJ[0]}; значение примера и правила расходятся в 100 раз."),
                    scenario=f"В ответе приходит «100.00»: по описанию это 100 {MN[2]}, по смыслу — 100 {MJ[2]}.",
                    impact="Клиент покажет сумму в 100 раз меньше или больше; тест не определит правильное значение.",
                    recommendation=f"Указать одну единицу: целое число {MN[2]} либо сумму в {MJ[1]} с двумя знаками.",
                    conflict=len(evidence) >= 2,
                ))
                break
        if not minors or not (majors or _has_major_values(doc, major)):
            continue
        conv = _conversion(doc, major, minor)
        if conv is not None or _implicit_conversion(doc, minors, major):
            continue
        # пара: сначала те же числа в основной единице, затем одна и та же величина, затем любая
        pair = None
        for a in minors:
            nums = _numbers(a[0].joined)
            if len(nums) < 2:
                continue
            rx_val = re.compile(rf"\d\s*(?:{major})(?!\w)|{DENOM}(?:{major})(?!\w)", re.I)
            for y in doc.lines:
                if y is a[0] or not y.text or y.is_code or not rx_val.search(y.joined):
                    continue
                if len(nums & _numbers(y.joined)) >= 2:
                    pair = (a, (y, "", _number_clause(y.joined, nums)), True)
                    break
            if pair:
                break
        for a in minors if pair is None else []:
            for b in majors:
                if _stem(a[1]) and _stem(a[1]) == _stem(b[1]) and a[0].n != b[0].n:
                    pair = (a, b, True)
                    break
            if pair:
                break
        if pair is None and majors:
            a = minors[0]
            b = min(majors, key=lambda y: (abs(y[0].n - a[0].n), y[0].n))
            pair = (a, b, False)
        if pair is None:
            continue
        a, b, same = pair
        qa = f"{a[1]} {a[2]}".strip()
        qb = f"{b[1]} {b[2]}".strip()
        if a[0].cells and b[1] == "":  # строка таблицы: диапазон и единица из соседних ячеек
            cells = a[0].cells
            idx = [i for i, c in enumerate(cells) if _numbers(c) or a[2].split()[-1] in c]
            if idx:
                qa = " | ".join(cells[min(idx):max(idx) + 1])
        if qa not in a[0].joined:
            qa = a[2]
        if qb not in b[0].joined:
            qb = b[2]
        subj = (f"одна и та же величина ({a[1]})" if same else
                f"связанные величины ({a[1]} и {b[1]})")
        out["candidates"].append(candidate(
            "units.currency_mix",
            title=f"Денежные величины в разных единицах без правила пересчёта: {quoted(qa)} и {quoted(qb)}",
            kind="unit_mismatch", criterion="unambiguous", severity="major", blocks="both",
            evidence=[ev(a[0], qa), ev(b[0], qb)],
            problem=(f"В документе {subj} заданы в разных единицах: {quoted(qa)} и {quoted(qb)}. "
                     f"Правила пересчёта {MN[2]} в {MJ[0]} и округления нет."),
            scenario=(f"Значение 1 000 в {MJ[1]} сравнивается с накопленными 100 000 в {MN[1]}: без пересчёта "
                      f"сравнение ложно срабатывает или не срабатывает, а при пересчёте неясно, как округлять "
                      f"остаток в {MN[1]}."),
            impact="Неверный расчёт и сравнение сумм; разные реализации в сервисах; тесты не определят ожидаемое.",
            recommendation=(f"Хранить и сравнивать суммы в одной единице или явно задать правило: "
                            f"1 {MJ[0]} = 100 {MN[2]}, сравнение после пересчёта, округление <уточнить>."),
            rewrite=f"Все суммы хранятся в {MN[1]}; 1 {MJ[0]} = 100 {MN[2]}; округление: <уточнить: правило>.",
            conflict=same,
        ))
        out["signals"].append(signal("units.currency_mix", a[0], qa,
                                     f"Разные денежные единицы без пересчёта: {quoted(qa)} и {quoted(qb)}.",
                                     ("analyst", "risk", "consistency"), "unit_mismatch"))


def _implicit_conversion(doc: Doc, minors: list, major: str) -> bool:
    """Значения в минорных единицах ровно в 100 раз больше тех же значений в основных — пересчёт согласован."""
    rx_val = re.compile(rf"\d\s*(?:{major})(?!\w)|{DENOM}(?:{major})(?!\w)", re.I)
    for a in minors:
        na = _numbers(a[0].joined)
        if len(na) < 2:
            continue
        for y in doc.lines:
            if y is a[0] or not y.text or not rx_val.search(y.joined):
                continue
            if len({v * 100 for v in _numbers(y.joined)} & na) >= 2:
                return True
    return False


def _numbers(text: str) -> set[int]:
    """Числа строки (≥ 100), «10 000» и «3 000 000» — одно число."""
    res = set()
    for m in re.finditer(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+", text):
        try:
            v = int(re.sub(r"\D", "", m.group(0)))
        except ValueError:
            continue
        if v >= 100:
            res.add(v)
    return res


def _number_clause(text: str, nums: set[int]) -> str:
    """Предложение строки, где стоят эти числа."""
    for part in re.split(r"(?<=[.;])\s+|\s\|\s", text):
        if len(_numbers(part) & nums) >= 2:
            return part.strip()
    return text


def _has_major_values(doc: Doc, major: str) -> bool:
    rx = re.compile(rf"\d\s*(?:{major})(?!\w)", re.I)
    return any(x.text and rx.search(x.joined) for x in doc.lines)


TZ_BARE = re.compile(r"\b(?:по|в)\s+(?:времени\s+)?(UTC|GMT)\b(?!\s*[+\-−]\s*\d)", re.I)
TZ_OFFSET = re.compile(r"\b(?:по|в)\s+(?:времени\s+)?(UTC|GMT)\s*[+\-−]\s*\d{1,2}(?::\d{2})?", re.I)


def rule_timezone(doc: Doc, out: dict) -> None:
    bare, offs = [], []
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        t = x.joined
        for m in TZ_BARE.finditer(t):
            bare.append((x, _subject(t, m.start()), t[m.start():m.end()].strip()))
        for m in TZ_OFFSET.finditer(t):
            offs.append((x, _subject(t, m.start()), t[m.start():m.end()].strip()))
    if not bare or not offs:
        return
    for a in bare:
        for b in offs:
            if _stem(a[1]) and _stem(a[1]) == _stem(b[1]):
                qa, qb = f"{a[1]} {a[2]}".strip(), f"{b[1]} {b[2]}".strip()
                qa = qa if qa in a[0].joined else a[2]
                qb = qb if qb in b[0].joined else b[2]
                out["candidates"].append(candidate(
                    "units.timezone_mix",
                    title=f"Одно и то же время описано в разных часовых поясах: {quoted(qa)} и {quoted(qb)}",
                    kind="unit_mismatch", criterion="set_consistent", severity="major", blocks="both",
                    evidence=[ev(a[0], qa), ev(b[0], qb)],
                    problem=(f"{quoted(qa)} и {quoted(qb)} — одна величина в двух поясах: UTC и UTC со смещением. "
                             "Неясно, в каком поясе хранится и передаётся значение."),
                    scenario="Событие в 10:15 по местному времени: одна система запишет 10:15, другая — 05:15.",
                    impact="Сдвиг времени на величину смещения: неверные сутки или месяц, споры при приёмке.",
                    recommendation="Указать один часовой пояс для поля во всех разделах (и смещение в формате ISO 8601).",
                    conflict=True,
                ))
                return
    out["signals"].append(signal("units.timezone_mix", bare[0][0], bare[0][2],
                                 f"В документе есть время «по UTC» и время со смещением ({offs[0][2]}).",
                                 ("consistency", "risk"), "unit_mismatch"))


PERIOD = re.compile(r"\b(?:за|в)\s+(?:один\s+|одн[иу]\s+|текущ\w+\s+|календарн\w+\s+|последн\w+\s+)?"
                    r"(час|сутки|суток|день|дня|недел\w|месяц\w*|минут\w)\b", re.I)
LIMIT = re.compile(r"не\s+больше|не\s+более|максимум|не\s+чаще|не\s+свыше|лимит\w*|ограничен\w*", re.I)
LIMIT_COUNT = re.compile(r"(?:не\s+больше|не\s+более|максимум|не\s+чаще|не\s+свыше)\s+(\d+|[а-яё]+)\s+"
                         r"((?:[а-яё]+\s+){0,1}[а-яё]+)", re.I)
NUM_WORDS = {
    1: ("один", "одна", "одно", "одного", "одной", "одни", "одних"), 2: ("два", "две", "двух"),
    3: ("три", "трёх", "трех"), 4: ("четыре", "четырёх", "четырех"), 5: ("пять", "пяти"),
    6: ("шесть", "шести"), 7: ("семь", "семи"), 8: ("восемь", "восьми"), 9: ("девять", "девяти"),
    10: ("десять", "десяти"),
}
WORD_NUM = {w: n for n, ws in NUM_WORDS.items() for w in ws}
PERIOD_RU = {"час": "час", "сутк": "сутки", "суто": "сутки", "день": "сутки", "дня": "сутки",
             "неде": "неделя", "меся": "месяц", "мину": "минута"}


def _period(word: str) -> str:
    w = word.lower()
    for k, v in PERIOD_RU.items():
        if w.startswith(k):
            return v
    return w


def _num(tok: str) -> int | None:
    t = tok.lower()
    if t.isdigit():
        return int(t)
    return WORD_NUM.get(t)


def _lcs(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def rule_period(doc: Doc, out: dict) -> None:
    """Один и тот же лимит (число + предмет) за разные периоды: «за час» в правиле, «за сутки» в приёмке."""
    lines = [x for x in doc.lines if x.text and not x.is_code]
    for x in lines:
        t = x.joined
        pm = PERIOD.search(t)
        if not pm:
            continue
        for m in LIMIT_COUNT.finditer(t):
            n = _num(m.group(1))
            if n is None:
                continue
            noun = max(m.group(2).split(), key=len)
            if len(noun) < 6:
                continue
            per = _period(pm.group(1))
            for y in lines:
                if y is x:
                    continue
                u = y.joined
                for nm in re.finditer(r"(\d+|[А-Яа-яЁё]+)\s+([А-Яа-яЁё]{6,})", u):
                    if _num(nm.group(1)) != n or _lcs(nm.group(2), noun) < 6:
                        continue
                    qm = PERIOD.search(u, nm.end())
                    if not qm or qm.start() - nm.end() > 30 or _period(qm.group(1)) == per:
                        continue
                    qa = _clause(t, m.start())
                    qb = u[nm.start():qm.end()].strip()
                    out["candidates"].append(candidate(
                        "units.period_mix",
                        title=(f"Один лимит задан за разные периоды: {quoted(pm.group(0))} и "
                               f"{quoted(qm.group(0))}"),
                        kind="unit_mismatch", criterion="set_consistent", severity="major", blocks="both",
                        evidence=[ev(x, qa), ev(y, qb)],
                        problem=(f"Ограничение {quoted(qa)} считается {pm.group(0)}, а в другом месте то же число "
                                 f"{quoted(qb)} отнесено к периоду {quoted(qm.group(0))}. Период подсчёта не определён."),
                        scenario=(f"Лимит исчерпан в одном периоде {quoted(pm.group(0))}, следующее событие приходит "
                                  f"в том же периоде {quoted(qm.group(0))}, но в новом {quoted(pm.group(0))}: по одному "
                                  "месту документа оно допустимо, по другому — нет."),
                        impact="Реализация и тесты выберут разные периоды; лимит будет либо слишком мягким, либо жёстким.",
                        recommendation="Задать один период подсчёта лимита и использовать его в правиле и в критериях приёмки.",
                        rewrite=f"Не больше {n} <уточнить: что> за <уточнить: час или сутки>.",
                        conflict=True,
                    ))
                    return
    found: dict[str, tuple[Line, str]] = {}
    for x in lines:
        if not LIMIT.search(x.joined):
            continue
        for m in PERIOD.finditer(x.joined):
            found.setdefault(_period(m.group(1)), (x, m.group(0)))
    units = sorted(found)
    if len(units) >= 2:
        x, q = found[units[0]]
        out["signals"].append(signal("units.period", x, q,
                                     "Ограничения заданы за разные периоды: "
                                     + ", ".join(quoted(found[u][1]) for u in units)
                                     + ". Проверьте, что один лимит везде считается за один период.",
                                     ("consistency", "qa"), "unit_mismatch"))


def _clause(text: str, pos: int) -> str:
    s0 = max(text.rfind(".", 0, pos) + 1, text.rfind("|", 0, pos) + 1, 0)
    e = text.find(".", pos)
    frag = text[s0:e + 1 if e != -1 else len(text)].strip()
    return frag if len(frag) <= 200 else text[pos:pos + 120]


TIME_OF_DAY = re.compile(r"(?<![\dT:+\-−])([01]?\d|2[0-3]):[0-5]\d(?![:\d])")
ZONE_AFTER = re.compile(r"^\s*(?:\(?\s*(?:по\s+(?:времени\s+)?[A-ZА-ЯЁ][\w+\-]*|UTC|GMT|[+\-−]\d{1,2}(?::\d{2})?|"
                        r"местн\w+|московск\w+))", re.I)


def rule_time_without_zone(doc: Doc, out: dict) -> None:
    """В одной строке два момента времени, пояс указан только у одного (сигнал для приёмки и набора)."""
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        t = x.joined
        times = list(TIME_OF_DAY.finditer(t))
        if len(times) < 2:
            continue
        zoned = [bool(ZONE_AFTER.match(t[m.end():m.end() + 25])) for m in times]
        if any(zoned) and not all(zoned):
            bare = times[zoned.index(False)].group(0)
            withz = times[zoned.index(True)]
            zone = ZONE_AFTER.match(t[withz.end():withz.end() + 25]).group(0).strip()
            out["signals"].append(signal(
                "units.time_without_zone", x, t if len(t) <= 200 else t[:200],
                f"Время {bare} указано без часового пояса, а {withz.group(0)} — {zone}: для дат на границе суток "
                "и месяца исход зависит от пояса.", ("qa", "consistency"), "unit_mismatch"))


TIME_UNIT = re.compile(r"\b([a-z][A-Za-z_]{1,30})\b\s*(?:\)|,)?\s*(?:в|—|-|:)?\s*"
                       r"(секунд\w*|минут\w*|час(?:ах|ов|а)?\b|сутк\w*|суток|дн(?:ях|ей|я)\b|миллисекунд\w*|мс\b)",
                       re.I)
UNIT_NORM = {"секу": "секунды", "мину": "минуты", "час": "часы", "сутк": "сутки", "суто": "сутки", "дн": "дни",
             "милл": "миллисекунды", "мс": "миллисекунды"}
# счётные сроки: «55 календарных дней», «количество рабочих дней» (не «операционный день» как дата)
DAY_KIND = re.compile(r"(?:\d+|количеств\w*|числ\w*|сколько)\s+(календарн|рабоч|банковск)\w*\s+(?:дн(?:ей|я|и|ях)|сут\w*)",
                      re.I)


def _unit(word: str) -> str:
    w = word.lower()
    for k, v in UNIT_NORM.items():
        if w.startswith(k):
            return v
    return w


def rule_time_units(doc: Doc, out: dict) -> None:
    """Одно поле (идентификатор) в разных единицах времени: «`ttl` в минутах» ↔ «`ttl` секунд»."""
    seen: dict[str, tuple[str, Line, str]] = {}
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        for m in TIME_UNIT.finditer(x.joined):
            name, unit = m.group(1), _unit(m.group(2))
            if name.lower() in ("from", "to", "in", "at", "per", "max", "min"):
                continue
            prev = seen.get(name)
            if prev is None:
                seen[name] = (unit, x, m.group(0).strip())
                continue
            if prev[0] != unit and prev[1] is not x:
                qa, qb = prev[2], m.group(0).strip()
                out["candidates"].append(candidate(
                    f"units.time_mix.{name}",
                    title=f"Поле {name} в разных единицах времени: {prev[0]} и {unit}",
                    kind="unit_mismatch", criterion="set_consistent", severity="major", blocks="both",
                    evidence=[ev(prev[1], qa), ev(x, qb)],
                    problem=(f"{quoted(qa)} и {quoted(qb)}: одно и то же поле {name} задано в {prev[0]} и в {unit}."),
                    scenario=f"{name} = 15: по одному месту это 15 {prev[0]}, по другому — 15 {unit}.",
                    impact="Срок или интервал отличается в десятки раз; поведение системы и тесты расходятся.",
                    recommendation=f"Указать одну единицу для {name} во всех разделах.",
                    conflict=True,
                ))
                return


def rule_day_kinds(doc: Doc, out: dict) -> None:
    """Календарные и рабочие дни для одной и той же величины (общий предмет в обеих фразах)."""
    found: dict[str, list[tuple[Line, str, str]]] = {}
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        t = x.joined
        for m in DAY_KIND.finditer(t):
            # предмет срока — только своя клауза: от границы предложения или ячейки до следующей
            a = max(t.rfind(".", 0, m.start()), t.rfind(";", 0, m.start()), t.rfind("|", 0, m.start())) + 1
            ends = [p for p in (t.find(".", m.end()), t.find(";", m.end()), t.find("|", m.end())) if p != -1]
            clause = t[a:min(ends) if ends else len(t)]
            found.setdefault(m.group(1).lower()[:5], []).append((x, m.group(0), clause))
    kinds = list(found)
    if len(kinds) < 2:
        return
    generic = {"сумма", "сумму", "клиен", "карты", "карта", "банка", "течен", "дней", "сутки", "срока", "колич",
               "числа", "число", "сколь"}

    def stems(t: str) -> set[str]:
        return {w.lower()[:5] for w in re.findall(r"[А-Яа-яЁё]{5,}", t)} - generic - {k for k in kinds}

    for i, ka in enumerate(kinds):
        for kb in kinds[i + 1:]:
            for xa, qa, ca in found[ka]:
                for xb, qb, cb in found[kb]:
                    if xa is xb and ca == cb:
                        continue
                    common = stems(ca) & stems(cb)
                    if not common:
                        continue
                    out["candidates"].append(candidate(
                        "units.day_kinds",
                        title=f"Одна величина в разных днях: {quoted(qa)} и {quoted(qb)}",
                        kind="unit_mismatch", criterion="unambiguous", severity="major", blocks="both",
                        evidence=[ev(xa, qa), ev(xb, qb)],
                        problem=(f"{quoted(xa.joined[:160])} и {quoted(xb.joined[:160])}: срок считается в разных днях "
                                 f"({qa} и {qb})."),
                        scenario="Период включает выходные: по одному месту остаётся 5 дней, по другому — 3.",
                        impact="Клиенту показывают неверный срок; расчёт и тесты расходятся на выходных и праздниках.",
                        recommendation="Указать один вид дней для этого срока во всех разделах.",
                        conflict=True,
                    ))
                    return


# --- поле API ↔ текст требований: одна величина в разных единицах ---------------------------------

# величины со своей единицей: срок, период, интервал, ставка (у ставки единица — период процента)
QTY_HEAD = re.compile(r"\b(срок\w*|период\w*|интервал\w*|длительност\w*|продолжительност\w*|тайм-?аут\w*|"
                      r"ставк\w*)", re.I)
DUR_UNIT = (r"(секунд\w*|минут\w*|час(?:а|ов|ах)?\b|сут(?:ки|ок|ках)\b|дн(?:ей|я|ях|и)\b|день\b|"
            r"недел\w*|месяц\w*|мес\.|год(?:а|ах)?\b|лет\b)")
RATE_UNIT = r"(годовых|в\s+год\b|за\s+год\b|в\s+месяц\b|за\s+месяц\b|ежемесячн\w*|в\s+день\b|за\s+день\b|в\s+квартал\b)"
DUR_NORM = (("секу", "секунды"), ("мину", "минуты"), ("час", "часы"), ("сут", "дни"), ("дн", "дни"), ("ден", "дни"),
            ("недел", "недели"), ("мес", "месяцы"), ("год", "годы"), ("лет", "годы"))
RATE_NORM = (("годов", "год"), ("в год", "год"), ("за год", "год"), ("в месяц", "месяц"), ("за месяц", "месяц"),
             ("ежемесяч", "месяц"), ("в день", "день"), ("за день", "день"), ("в квартал", "квартал"))
QTY_GENERIC = {"срок", "срока", "сроке", "сроком", "сроки", "период", "интер", "ставк", "длите", "продо",
               "таймау", "значе", "колич", "число", "указа", "клиен", "время", "течен"}
FIELD_NAME = re.compile(r"^[a-z][A-Za-z0-9_.]{1,40}$")


def _unit_of(text: str, head: str) -> tuple[str, str, str] | None:
    """Единица величины после её названия: («dur», «месяцы», фрагмент) или («rate», «год», фрагмент)."""
    m = QTY_HEAD.search(text)
    if not m or not m.group(1).lower().startswith(head):
        return None
    tail = text[m.start():m.start() + 90]
    tail = re.split(r"[.;|]", tail, maxsplit=1)[0]
    if head == "ставк":
        r = re.search(r"%\s*,?\s*" + RATE_UNIT + r"|процент\w*\s+" + RATE_UNIT, tail, re.I)
        if not r:
            return None
        u = (r.group(1) or r.group(2)).lower()
        for k, v in RATE_NORM:
            if u.startswith(k):
                return ("rate", v, tail[:r.end()].strip())
        return None
    d = re.search(r"(?:\d[\d\s]*|\bв|\bколичеств\w*|\bчисл\w*)\s*" + DUR_UNIT, tail, re.I)
    if not d:
        return None
    u = d.group(1).lower()
    for k, v in DUR_NORM:
        if u.startswith(k):
            return ("dur", v, tail[:d.end()].strip())
    return None


UNIT_FORMS = {  # (как назвать единицу, родительный мн. ч. после числа, предложный мн. ч.)
    "секунды": ("секунды", "секунд", "секундах"), "минуты": ("минуты", "минут", "минутах"),
    "часы": ("часы", "часов", "часах"), "дни": ("дни", "дней", "днях"), "недели": ("недели", "недель", "неделях"),
    "месяцы": ("месяцы", "месяцев", "месяцах"), "годы": ("годы", "лет", "годах")}


def _unit_ru(cls: str, unit: str, form: str = "name") -> str:
    if cls == "rate":
        return "% годовых" if unit == "год" else f"% в {unit}"
    forms = UNIT_FORMS.get(unit, (unit, unit, unit))
    return forms[1] if form == "gen" else forms[2] if form == "prep" else forms[0]


def _rewrite_unit(desc: str, cls: str, unit: str) -> str:
    """Описание поля с единицей из требований: «Срок кредита в днях» → «Срок кредита в месяцах»."""
    if cls == "rate":
        m = re.search(r"%\s*,?\s*" + RATE_UNIT, desc, re.I)
        return (desc[:m.start()] + _unit_ru(cls, unit)).strip() if m else ""
    m = re.search(r"\s*,?\s*(?:\bв\s+)?" + DUR_UNIT, desc, re.I)
    return (desc[:m.start()].rstrip(" ,") + " в " + _unit_ru(cls, unit, "prep")) if m else ""


def _qualifiers(phrase: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[А-Яа-яЁё]{4,}", phrase)} - QTY_GENERIC


def rule_field_units(doc: Doc, out: dict) -> None:
    """Поле таблицы API описано в одной единице, а та же величина в требованиях — в другой.
    Связь: то же название величины и (те же числа диапазона или все уточнения описания поля в предложении)."""
    rows = []
    for t in tables(doc):
        if t.col("поле", "field", "параметр", "parameter", "name", "имя") is None:
            continue
        di = t.col("описание", "description", "назначение")
        if di is None:
            continue
        for r in t.rows:
            cells = r.cells or []
            if not cells or di >= len(cells) or not FIELD_NAME.match(cells[0].strip("`")):
                continue
            desc = cells[di]
            hm = QTY_HEAD.search(desc)
            if not hm:
                continue
            head = "ставк" if hm.group(1).lower().startswith("ставк") else hm.group(1).lower()[:4]
            u = _unit_of(desc, head)
            if not u:
                continue
            nums = {int(n.replace(" ", "")) for c in cells for n in re.findall(r"\d[\d ]*", c) if n.strip()}
            rows.append((r, cells[0].strip("`"), desc, head, u, nums, _qualifiers(desc[hm.start():])))
    if not rows:
        return
    row_lines = {r[0].n for r in rows}
    for r, field_name, desc, head, (cls, unit, _frag), nums, quals in rows:
        _field_unit_one(doc, out, row_lines, r, field_name, desc, head, cls, unit, nums, quals)


def _field_unit_one(doc: Doc, out: dict, row_lines: set[int], r: Line, field_name: str, desc: str, head: str,
                    cls: str, unit: str, nums: set[int], quals: set[str]) -> None:
    """Первое расхождение единиц для одного поля (по полю — не больше одного кандидата)."""
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading or x.n in row_lines:
            continue
        t = x.joined
        for sent in re.split(r"(?<=[.;])\s+|\s\|\s", t):
            hm = QTY_HEAD.search(sent)
            if not hm or not hm.group(1).lower().startswith(head):
                continue
            u2 = _unit_of(sent[hm.start():], head)
            if not u2 or u2[0] != cls or u2[1] == unit:
                continue
            snums = {int(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*", u2[2]) if n.strip()}
            same_nums = len(nums & snums) >= 2 or (snums and snums <= nums and len(snums) >= 1 and cls == "dur")
            sq = _qualifiers(sent)
            if not (same_nums or (quals and quals <= sq) or (cls == "rate" and not quals)):
                continue
            if any(re.search(r"1\s*" + unit[:3] + r"\w*\s*=|=\s*\d+\s*" + u2[1][:3], y.joined, re.I)
                   for y in doc.lines if y.text):
                continue
            what = "Ставка" if cls == "rate" else "Срок"
            ua, ub = _unit_ru(cls, unit), _unit_ru(cls, u2[1])
            n_a, n_b = _unit_ru(cls, unit, "gen"), _unit_ru(cls, u2[1], "gen")
            out["candidates"].append(candidate(
                f"units.field_unit.{field_name}",
                title=f"{what} в разных единицах: поле {field_name} — {ua}, в требованиях — {ub}",
                kind="unit_mismatch", criterion="set_consistent", severity="major", blocks="both",
                evidence=[ev(x, u2[2]), ev(r, desc)],
                problem=(f"Требования задают {quoted(u2[2])}, а поле {field_name} в API описано как "
                         f"{quoted(desc)}: одна величина в разных единицах ({ub} и {ua}), правила пересчёта нет."),
                scenario=(f"{field_name} = 12: по требованиям это 12 {n_b}, по описанию поля — 12 {n_a}; расчёт, "
                          "проверка диапазона и показ клиенту дают разный результат."),
                impact="Клиенту считают неверную сумму или срок; интеграция и тесты расходятся в разы.",
                recommendation=f"Указать одну единицу для {field_name} в описании поля и в требованиях.",
                rewrite=_rewrite_unit(desc, cls, u2[1]),
                conflict=True,
            ))
            return


def run(doc: Doc, out: dict) -> None:
    rule_field_units(doc, out)
    rule_time_units(doc, out)
    rule_day_kinds(doc, out)
    rule_currency(doc, out)
    rule_timezone(doc, out)
    rule_period(doc, out)
    rule_time_without_zone(doc, out)
