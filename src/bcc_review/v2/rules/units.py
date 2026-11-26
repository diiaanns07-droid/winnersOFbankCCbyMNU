"""Единицы измерения: одна величина в разных единицах без правила пересчёта.

* деньги: основная и минорная единица одной валюты (тенге/тиын, рубль/копейка, доллар/евро/цент);
* минорная единица с дробной частью («в … с двумя знаками после точки»);
* время: «по UTC» без смещения и «UTC+N» для одного и того же поля;
* период подсчёта: один и тот же лимит «за час» и «за сутки» (сигнал).
Связка ищется по фразе «<величина> в <единица>» — так сравниваются именно величины, а не слова.
"""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, quoted, signal

CURRENCIES = [
    # (major-шаблон, minor-шаблон, название основной, название минорной, множитель)
    (r"тенге|₸|kzt", r"тиын\w*", "тенге", "тиыны", 100),
    (r"рубл\w*|₽|rub", r"копе\w*", "рубли", "копейки", 100),
    (r"доллар\w*|usd|\$", r"цент\w*", "доллары", "центы", 100),
    (r"евро|eur|€", r"(?:евро)?цент\w*", "евро", "центы", 100),
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
                    rf"(?:пересч\w*|перев\w*|конверт\w*|округл\w*)[^.]{{0,60}}(?:{minor})|"
                    rf"(?:{minor})[^.]{{0,60}}(?:пересч\w*|округл\w*|конверт\w*)", re.I)
    for x in doc.lines:
        if x.text and rx.search(x.joined):
            return x
    return None


def rule_currency(doc: Doc, out: dict) -> None:
    for major, minor, major_ru, minor_ru, _mult in CURRENCIES:
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
                out["candidates"].append(candidate(
                    "units.minor_fraction",
                    title=f"Величина в минорных единицах ({minor_ru}) описана с дробной частью",
                    kind="unit_mismatch", criterion="unambiguous", severity="major", blocks="both",
                    evidence=[ev(x, frag)],
                    problem=(f"{quoted(frag)}: {minor_ru} — наименьшая единица валюты, дробной части у неё нет. "
                             f"Похоже, имелись в виду {major_ru}; значение примера и правила расходятся в 100 раз."),
                    scenario=f"В ответе приходит «100.00»: по описанию это 100 {minor_ru}, по смыслу — 100 {major_ru}.",
                    impact="Клиент покажет сумму в 100 раз меньше или больше; тест не определит правильное значение.",
                    recommendation=f"Указать одну единицу: целое число {minor_ru} либо {major_ru} с двумя знаками.",
                    conflict=False,
                ))
                break
        if not minors or not (majors or _has_major_values(doc, major)):
            continue
        conv = _conversion(doc, major, minor)
        if conv is not None:
            continue
        # пара: сначала по одной и той же величине, затем любая
        pair = None
        for a in minors:
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
                     f"Правила пересчёта {minor_ru} в {major_ru} и округления нет."),
            scenario=(f"Значение 1 000 в {major_ru} сравнивается с накопленными 100 000 в {minor_ru}: без пересчёта "
                      f"сравнение ложно срабатывает или не срабатывает, а при пересчёте неясно, как округлять "
                      f"остаток в {minor_ru}."),
            impact="Неверный расчёт и сравнение сумм; разные реализации в сервисах; тесты не определят ожидаемое.",
            recommendation=(f"Хранить и сравнивать суммы в одной единице или явно задать правило: "
                            f"1 {major_ru} = 100 {minor_ru}, сравнение после пересчёта, округление <уточнить>."),
            rewrite=f"Все суммы хранятся в {minor_ru}; 1 {major_ru} = 100 {minor_ru}; округление: <уточнить: правило>.",
            conflict=same,
        ))
        out["signals"].append(signal("units.currency_mix", a[0], qa,
                                     f"Разные денежные единицы без пересчёта: {quoted(qa)} и {quoted(qb)}.",
                                     ("analyst", "risk", "consistency"), "unit_mismatch"))


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


PERIOD = re.compile(r"\b(?:за|в)\s+(?:один\s+|одн[иу]\s+|текущ\w+\s+|календарн\w+\s+)?"
                    r"(час|сутки|день|недел\w|месяц|минут\w)\b", re.I)
LIMIT = re.compile(r"не\s+больше|не\s+более|максимум|не\s+чаще|не\s+свыше|лимит\w*|ограничен\w*", re.I)


def rule_period(doc: Doc, out: dict) -> None:
    found: dict[str, tuple[Line, str]] = {}
    for x in doc.lines:
        if not x.text or x.is_code or not LIMIT.search(x.joined):
            continue
        for m in PERIOD.finditer(x.joined):
            unit = m.group(1).lower()[:4]
            found.setdefault(unit, (x, m.group(0)))
    units = sorted(found)
    if len(units) >= 2:
        x, q = found[units[0]]
        out["signals"].append(signal("units.period", x, q,
                                     "Ограничения заданы за разные периоды: "
                                     + ", ".join(quoted(found[u][1]) for u in units)
                                     + ". Проверьте, что один лимит везде считается за один период.",
                                     ("consistency", "qa"), "unit_mismatch"))


def run(doc: Doc, out: dict) -> None:
    rule_currency(doc, out)
    rule_timezone(doc, out)
    rule_period(doc, out)
