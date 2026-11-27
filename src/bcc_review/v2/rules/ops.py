"""Эксплуатационная полнота (№30): то, без чего требование нельзя реализовать одинаково и проверить.

* повторная доставка события или запроса: документ требует, чтобы повтор не менял итог, но не говорит, по какому
  признаку повтор узнаётся (идентификатор события, ключ идемпотентности) и не ссылается на правило, где это сказано;
* поле шаблона сообщения («SMS «Заказ XXXX готов», где XXXX — последние четыре цифры номера») не хранится:
  в требованиях к данным («Хранить …») такого значения нет.

Правило не знает слов конкретного документа: только общие обороты банковских ТЗ об интеграции.
"""
from __future__ import annotations

import re

from ._text import Doc, candidate, ev, quoted, signal

WORD = re.compile(r"[а-яёa-z]+", re.I)

# «повторная доставка события», «событие доставлено повторно», «дубликат сообщения», «повторное получение уведомления»
REPEAT = re.compile(
    r"\bповторн\w+\s+(?:доставк|получени|приход|поступлени)\w*|\b(?:доставлен|получен|пришл|поступил)\w*\s+повторно\b|"
    r"\bдубл(?:ь|ик)\w*\s+(?:событи|сообщени|уведомлени|запрос)\w*|\bat[\s-]least[\s-]once\b", re.I)
MESSAGE = re.compile(r"событи|сообщени|уведомлени|запрос|вызов|операци|webhook|callback|event|message", re.I)
# признак повтора назван: ключ идемпотентности, идентификатор события / операции / запроса, поле `…Id`
KEY = re.compile(
    r"ключ\w*\s+(?:идемпотентн|дедупликац|повтор)|idempoten|дедупликац|"
    r"идентификатор\w*\s+(?:событи|операци|сообщени|запрос|уведомлени|транзакци)|"
    r"\bс\s+(?:тем\s+же|одинаков\w+)\s+[`'\"«]?[\w-]*(?:id|ид|ключ|номер)\w*|"
    r"[`'\"«]?\b[a-z]+(?:Id|ID|_id|Key)\b[`'\"»]?|\bпо\s+(?:полю|ключу|идентификатору|номеру)\b", re.I)
# ссылка на правило, где повтор описан: «— по Ф-9», «см. особое правило 1», «(п. 4.2)»
REF = re.compile(r"(?:\bпо|\bсм\.?|\bсогласно|\bв\s+соответствии\s+с)\s+(?:[A-ZА-ЯЁ]{1,4}-\d+|п(?:ункт\w*|\.)\s*\d|"
                 r"особ\w+\s+правил\w*|правил\w*\s+\d|раздел\w*\s)", re.I)


def _sentence(text: str, a: int, b: int) -> str:
    s0 = max(text.rfind(". ", 0, a) + 1, text.rfind("|", 0, a) + 1, 0)
    e = text.find(".", b)
    frag = text[s0:e + 1 if e != -1 else len(text)].strip()
    return frag if len(frag) <= 220 else text[max(0, a - 60):b + 100].strip()


def rule_repeat_key(doc: Doc, out: dict) -> None:
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading:
            continue
        t = x.joined
        m = REPEAT.search(t)
        if not m:
            continue
        frag = _sentence(t, m.start(), m.end())
        if not MESSAGE.search(frag) or KEY.search(frag) or REF.search(frag):
            continue
        # признак повтора может стоять в соседнем предложении той же строки
        if KEY.search(t[max(0, m.start() - 200):m.end() + 200]):
            continue
        out["candidates"].append(candidate(
            "ops.repeat_key",
            title="Повторная доставка: не сказано, по какому признаку узнаётся повтор",
            kind="missing_element", criterion="complete", severity="major", blocks="development",
            evidence=[ev(x, frag)],
            problem=(f"Документ требует корректно обработать повтор: {quoted(frag)}. Но не сказано, по какому признаку "
                     "сервис узнаёт повтор (идентификатор события или операции, ключ идемпотентности), сколько времени "
                     "он помнит обработанные и что делать при одновременной доставке двух копий."),
            scenario=("Одно и то же событие приходит дважды с интервалом в несколько секунд: без признака повтора "
                      "сервис учтёт его дважды — или, наоборот, отбросит другое событие с теми же суммой и временем."),
            impact="Двойной учёт или потеря операций; тест на повтор нельзя написать однозначно.",
            recommendation=("Назвать признак повтора (поле с идентификатором события или операции), срок хранения "
                            "обработанных признаков и исход для одновременной доставки двух копий."),
            question="По какому полю сервис распознаёт повторную доставку и сколько хранит обработанные события?",
        ))
        out["signals"].append(signal("ops.repeat_key", x, frag,
                                     "Повтор описан без признака, по которому он распознаётся (идентификатор события, "
                                     "ключ идемпотентности).", ("architect", "risk", "qa"), "missing_element"))
        return  # одно замечание на документ


# «… «Заказ XXXX готов», где XXXX — последние четыре цифры номера»
TEMPLATE_VAR = re.compile(r"«[^»]{0,120}?(?P<var>\b[A-ZА-ЯЁ]{3,}\b|\{[^}]{1,30}\}|<[^>]{1,30}>)[^»]{0,120}»[^.;]{0,40}?"
                          r",?\s*где\s+(?P=var)\s*[—–-]\s*(?P<what>[^.;]{4,120})")
DATA_SECTION = re.compile(r"требовани\w*\s+к\s+данным|модел\w*\s+данных|хранени\w*\s+данных|^данные$", re.I)
STORE = re.compile(r"^\s*(?:хранить|хранятся|хранится|сохраня\w*|в\s+базе\s+хран\w*)\b", re.I)
STOP = {"номер", "номера", "карты", "карта", "клиент", "клиента", "значение", "время", "дата", "текущий", "текущая"}


def _stems(text: str) -> list[str]:
    return [w.lower()[:5] for w in WORD.findall(text) if len(w) >= 4 and w.lower() not in STOP]


def rule_message_data(doc: Doc, out: dict) -> None:
    data = [x for x in doc.lines if x.text and not x.is_heading
            and (DATA_SECTION.search((x.section or "").split("›")[-1].strip()) or STORE.match(x.text))]
    stored = {st for x in data if STORE.match(x.text) or DATA_SECTION.search(x.section or "")
              for st in _stems(x.joined)}
    if not any(STORE.match(x.text) for x in data):
        return  # перечня хранимых данных нет — полноту хранения не судим
    for x in doc.lines:
        if not x.text or x.is_code or x.cells is not None:
            continue
        m = TEMPLATE_VAR.search(x.joined)
        if not m:
            continue
        head = _stems(m.group("what"))[:3]
        if len(head) < 2 or any(h in stored for h in head):
            continue
        store_line = next(x2 for x2 in data if STORE.match(x2.text))
        what = m.group("what").strip()
        out["candidates"].append(candidate(
            "ops.message_data",
            title=f"Поле сообщения не хранится: {quoted(what)}",
            kind="missing_element", criterion="set_complete", severity="major", blocks="development",
            evidence=[ev(x, m.group(0)[:200]), ev(store_line)],
            problem=(f"Шаблон сообщения подставляет {quoted(m.group('var'))} — {quoted(what)}, но в требованиях к данным "
                     f"этого значения нет: {quoted(store_line.joined[:200])}. Откуда сервис возьмёт его при отправке, "
                     "не сказано."),
            scenario=("Сервис формирует сообщение после события: подставить значение не из чего — сообщение уходит с "
                      "пустым местом или не уходит, тест на текст сообщения не пройти."),
            impact="Сообщение нельзя сформировать по документу; объём доработки хранилища или интеграции недооценён.",
            recommendation=(f"Добавить {quoted(what)} в требования к данным или указать, из какой системы оно берётся "
                            "в момент отправки."),
            question=f"Откуда сервис берёт {quoted(what)} для сообщения — хранит сам или запрашивает у другой системы?",
        ))
        return


def run(doc: Doc, out: dict) -> None:
    rule_repeat_key(doc, out)
    rule_message_data(doc, out)
