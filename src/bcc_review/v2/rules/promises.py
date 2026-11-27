"""Обещания без реализации: операция названа или обещана, но в спецификации API её нет.

* метод назван по имени («методом getX», «Методы getX и setY»), но не описан;
* документ обещает чтение или показ данных («читает», «показывает», «отображает», «чтение»), а среди
  описанных методов нет ни одной операции чтения;
* фраза интеграции перечисляет операции («Приложение создаёт X, получает Y и выполняет Z через дочерний
  документ / API»), а для части из них нет метода: ни описание, ни название метода не называют операцию,
  и свободного метода подходящего вида не осталось.
"""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, fmt_list, quoted, signal
from .api import MUTATING_TOKENS, READ_TOKENS, Method, split_camel

METHOD_NAME = re.compile(r"\b([a-z]{2,}[A-Z][A-Za-z0-9]*)\b")
METHOD_CTX = re.compile(r"метод\w*|операци\w*|endpoint|вызов\w*|api", re.I)
READ_PROMISE = re.compile(
    r"\b(читает|читают|чтени\w*|считыва\w*|показыва\w*|отобража\w*|выводит|просматрива\w*|"
    r"получени\w+\s+(?:данных|настро\w*|значени\w*|сведени\w*|информаци\w*|статус\w*|остатк\w*|"
    r"сумм\w*|истори\w*)|получа(?:ет|ют)\s+(?:данн\w*|сведени\w*|информаци\w*|настро\w*|статус\w*|состояни\w*|"
    r"список\w*|истори\w*|остат\w*)|на\s+экране\s+видн\w*)", re.I)
INTEGRATION_CTX = re.compile(r"дочерн\w+\s+документ\w*|через\s+api|rest\s+api|метод\w*", re.I)
ACTOR = re.compile(r"приложени\w*|экран\w*|интерфейс\w*|клиент\w*|пользовател\w*|фронт\w*|ui\b|api|"
                   r"документ\w*|функциональн\w+\s+требовани\w*", re.I)


def _defined_names(doc: Doc, methods: list[Method]) -> set[str]:
    names = {m.name.lower() for m in methods if m.name}
    for m in methods:
        if m.url:
            for seg in m.url.split("/"):
                if seg and not seg.startswith("{"):
                    names.add(seg.lower())
    return names


def rule_named_methods(doc: Doc, methods: list[Method], out: dict) -> set[str]:
    if not methods:
        return set()
    defined = _defined_names(doc, methods)
    missing: dict[str, list[Line]] = {}
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        if any(m.start <= x.n <= m.end and x in (m.verb_line, m.url_line, m.name_line, m.curl_line) for m in methods):
            continue
        t = x.joined
        if not METHOD_CTX.search(t):
            continue
        for mm in METHOD_NAME.finditer(t):
            name = mm.group(1)
            toks = split_camel(name)
            if len(toks) < 2 or name.lower() in defined:
                continue
            # имя метода, а не поле: «методом X», «Методы X и Y», «вызов X» рядом или глагол в начале имени
            before = " ".join(re.findall(r"[\wА-Яа-яЁё]+", t[:mm.start()])[-3:])
            if not (re.search(r"метод\w*|вызов\w*|endpoint|операци\w*", before, re.I)
                    or toks[0] in READ_TOKENS or toks[0] in MUTATING_TOKENS):
                continue
            if any(name.lower() == (m.name or "").lower() for m in methods):
                continue
            missing.setdefault(name, []).append(x)
    reported = set()
    for name, lines in missing.items():
        first = lines[0]
        frag = _sentence(first.joined, name)
        evidence = [ev(first, frag)] + [ev(y, _sentence(y.joined, name)) for y in lines[1:2]]
        described = fmt_list([m.label or m.verb for m in methods])
        is_read = split_camel(name)[0] in READ_TOKENS
        out["candidates"].append(candidate(
            f"promises.named_method.{name}",
            title=f"Метод {name} упомянут, но не описан в спецификации API",
            kind="missing_element", criterion="set_complete", severity="critical", blocks="development",
            evidence=evidence,
            problem=(f"Документ ссылается на метод {name}: {quoted(frag)}. В спецификации описаны только "
                     f"{described}; для {name} нет типа запроса, адреса, параметров, ответа и статусов."),
            scenario=(f"Разработчик приложения вызывает {name}, чтобы {'получить данные для экрана' if is_read else 'выполнить операцию'}: "
                      "контракта нет, сервер его не реализует, функция не работает."),
            impact="Обещанную функцию нельзя реализовать и протестировать по документу.",
            recommendation=f"Добавить описание метода {name} (тип запроса, адрес, параметры, ответ, статусы) или убрать ссылку.",
            question=f"Нужен ли метод {name} в этой поставке, и если да — кто опишет его контракт?",
        ))
        out["signals"].append(signal(f"promises.named_method.{name}", first, frag,
                                     f"Метод {name} упомянут, но не описан: есть только {described}.",
                                     ("architect", "qa"), "missing_element"))
        reported.add(name)
    return reported


def _sentence(text: str, needle: str) -> str:
    k = text.find(needle) if needle in text else 0
    s0 = max(text.rfind(".", 0, k) + 1, text.rfind("|", 0, k) + 1, 0)
    e = text.find(".", k + len(needle))
    frag = text[s0:e + 1 if e != -1 else len(text)].strip()
    return frag if len(frag) <= 200 else text[k:k + 150]


# --- обещанные операции во фразе интеграции -----------------------------------------------------

# «… через дочерний документ», «… через API» (не «через API процессинга» — это другая система)
INTEGRATION_VIA = re.compile(
    r"\bчерез\s+(?:(?:этот|данный)\s+)?(?:дочерн\w+\s+(?:документ|спецификаци)\w*|"
    r"(?:rest[\s-]+)?api(?=\s*(?:[«\"(.,;:]|$))|описанн\w+\s+(?:ниже\s+)?метод\w*)", re.I)
# основа глагола операции → вид (read / compute / mut) и формы, которыми операцию называют методы
OP_STEMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "получ": ("read", ("получ",)), "чита": ("read", ("чтен", "чита")), "показыва": ("read", ("показ", "отображ")),
    "отобража": ("read", ("отображ", "показ")), "запрашива": ("read", ("запрос",)),
    "просматрива": ("read", ("просмотр",)),
    "рассчитыва": ("compute", ("расчет", "расчёт", "рассчит")), "рассчита": ("compute", ("расчет", "расчёт", "рассчит")),
    "вычисля": ("compute", ("вычисл", "расчет", "расчёт")),
    "созда": ("mut", ("созда",)), "отменя": ("mut", ("отмен",)), "удаля": ("mut", ("удал",)),
    "изменя": ("mut", ("измен",)), "меня": ("mut", ("смен", "измен")), "сохраня": ("mut", ("сохран",)),
    "включа": ("mut", ("включ",)), "выключа": ("mut", ("выключ",)), "отключа": ("mut", ("отключ",)),
    "подключа": ("mut", ("подключ",)), "снима": ("mut", ("снят", "сним")), "обновля": ("mut", ("обновл",)),
    "отправля": ("mut", ("отправ",)), "переда": ("mut", ("переда",)), "блокиру": ("mut", ("блокир",)),
    "разблокиру": ("mut", ("разблокир",)), "пополня": ("mut", ("пополн",)), "переводи": ("mut", ("перевод",)),
    "подтвержда": ("mut", ("подтвержд",)), "регистриру": ("mut", ("регистр",)), "настраива": ("mut", ("настро", "настра")),
    "устанавлива": ("mut", ("установ",)), "закрыва": ("mut", ("закрыт", "закрыв")), "открыва": ("mut", ("открыт", "открыв")),
    "активиру": ("mut", ("актив",)), "деактивиру": ("mut", ("деактив",)), "выпуска": ("mut", ("выпуск",)),
    "выбира": ("mut", ("выбор", "выбир")), "привязыва": ("mut", ("привяз",)), "отвязыва": ("mut", ("отвяз",)),
    "подписыва": ("mut", ("подпис",)), "списыва": ("mut", ("списан",)), "оплачива": ("mut", ("оплат",)),
    "заказыва": ("mut", ("заказ",)), "переноси": ("mut", ("перенос",)), "продлева": ("mut", ("продл",)),
    "приостанавлива": ("mut", ("приостанов",)), "возобновля": ("mut", ("возобнов",)), "отзыва": ("mut", ("отзыв",)),
    "добавля": ("mut", ("добавл",)), "редактиру": ("mut", ("редакт",)), "отклоня": ("mut", ("отклон",)),
    "одобря": ("mut", ("одобр",)), "загружа": ("compute", ("загруз",)), "выгружа": ("read", ("выгруз",)),
}
# «остальные методы описаны в документе …», «методы … описаны в отдельной спецификации»
ELSEWHERE = re.compile(r"(?:остальн|прочи|други|осталь)\w*\s+(?:метод|операци)\w*[^.]{0,60}(?:описан|приведен|"
                       r"см\.|смотри)|(?:метод|операци)\w*[^.]{0,50}(?:описан|приведен)\w*\s+в\s+(?:отдельн|друг|"
                       r"смежн|соседн)\w+\s+(?:документ|спецификаци|раздел)", re.I)
# «лёгкие» глаголы: операцию называет дополнение («оформляет отказ», «выполняет перевод»)
LIGHT_VERBS = ("оформля", "выполня", "осуществля", "производи", "соверша", "проводи", "инициирует", "инициируют")
VERB_END = re.compile(r"(?:ет|ёт|ют|ит|ят|ут|ат)$")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё][\wЁё-]*")
OBJ_STOP = {"его", "её", "ее", "их", "него", "неё", "нее", "них", "для", "при", "перед", "после", "через", "по",
            "на", "в", "во", "с", "со", "к", "ко", "из", "от", "до", "о", "об", "и", "или", "а", "также", "свой",
            "свою", "своё", "свои", "этот", "эту", "это", "эти", "текущий", "текущую", "текущее", "клиента",
            "клиенту", "клиент", "данные", "данных", "сведения", "сведений"}


def _w(s: str) -> str:
    return s.lower().replace("ё", "е")


def _op_stem(word: str) -> str | None:
    w = _w(word)
    if not VERB_END.search(w):
        return None
    for stem in sorted(OP_STEMS, key=len, reverse=True):
        if w.startswith(_w(stem)) and len(w) > len(stem):
            return stem
    for lv in LIGHT_VERBS:
        if w.startswith(_w(lv)):
            return "light"
    return None


def _content(words: list[str]) -> list[str]:
    return [w for w in (_w(x) for x in words) if len(w) >= 4 and w not in OBJ_STOP]


def _stem5(w: str) -> str:
    return w[:5] if len(w) > 5 else w[:max(3, len(w) - 1)]


def _promised_ops(clause: str) -> list[dict]:
    """Операции фразы интеграции: [{verbs, cls, object, quote}]; глаголы без своего дополнения
    («включает или выключает напоминание») делят дополнение следующего глагола."""
    toks = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(clause)]
    verbs = [(i, _op_stem(t[0])) for i, t in enumerate(toks)]
    verbs = [(i, st) for i, st in verbs if st]
    ops: list[dict] = []
    pending: list[tuple[int, str]] = []
    for k, (i, st) in enumerate(verbs):
        nxt = verbs[k + 1][0] if k + 1 < len(verbs) else len(toks)
        obj = [t[0] for t in toks[i + 1:nxt]]
        obj_words = [w for w in obj if _w(w) not in ("и", "или", "а", "также")]
        if not obj_words and k + 1 < len(verbs):
            pending.append((i, st))
            continue
        group = pending + [(i, st)]
        pending = []
        start = toks[group[0][0]][1]
        end = toks[nxt - 1][2] if nxt - 1 > i else toks[i][2]
        quote = clause[start:end].strip().rstrip(",;").strip()
        quote = re.sub(r"\s+(?:и|или|а также)$", "", quote)
        stems = [g[1] for g in group]
        content = _content(obj_words)
        if all(st == "light" for st in stems):
            if not content:
                continue
            cls = "mut"
        else:
            kinds = {OP_STEMS[st][0] for st in stems if st != "light"}
            cls = "mut" if "mut" in kinds else ("compute" if "compute" in kinds else "read")
        ops.append({"stems": stems, "cls": cls, "object": content, "quote": quote})
    return ops


def _method_words(m: Method, shared: set[str] = frozenset()) -> list[str]:
    parts = [m.desc]
    sec = (m.verb_line.section or "").split("›")[-1].strip() if m.verb_line is not None else ""
    if sec and sec not in shared:
        parts.append(sec)  # свой раздел метода: «7.3. Отзыв заявки»
    vl = m.verb_line
    if vl is not None and vl.cells and vl.n == m.start:
        parts.append(vl.cells[0])  # строка сводной таблицы: «2. Отмена QR-кода | DELETE /qr/{id}»
    for hl in (vl, m.name_line):
        if hl is not None and hl.is_heading:
            parts.append(re.sub(r"/\S*", " ", hl.text))  # «POST /deliveries — Создание заявки»
    return [_w(x) for x in WORD.findall(" ".join(p for p in parts if p))]


def _covers(op: dict, words: list[str]) -> bool:
    for st in op["stems"]:
        if st == "light":
            continue
        if any(w.startswith(f) for f in OP_STEMS[st][1] for w in words):
            return True
    if op["stems"] and all(st == "light" for st in op["stems"]):
        key = _stem5(op["object"][0])
        return any(w.startswith(key) for w in words)
    obj = op["object"]
    # дополнение из двух и более слов целиком названо в описании метода («способ выплаты»)
    return len(obj) >= 2 and all(any(w.startswith(_stem5(o)) for w in words) for o in obj)


def _short_op(quote: str, limit: int = 4) -> str:
    """Операция для заголовка: до 4 слов, без висящего предлога («получают данные QR-кода»)."""
    words = quote.split()
    if len(words) <= limit:
        return quote
    words = words[:limit]
    while words and _w(words[-1]) in OBJ_STOP:
        words.pop()
    return " ".join(words)


def _compatible(op: dict, m: Method) -> bool:
    if op["cls"] == "read":
        return m.is_read()
    if op["cls"] == "mut":
        return not m.is_read()
    return True


def rule_promised_ops(doc: Doc, methods: list[Method], out: dict) -> bool:
    """Фраза интеграции обещает операции, для которых в спецификации нет метода. True — кандидат создан
    (тогда «обещано чтение» не повторяется отдельным кандидатом)."""
    if not methods:
        return False
    if any(x.text and ELSEWHERE.search(x.joined) for x in doc.lines):
        return False  # часть методов описана в другом документе — по этому файлу полноту не судим
    secs = [(m.verb_line.section or "").split("›")[-1].strip() for m in methods]
    shared = {x for x in secs if secs.count(x) > 1}
    mwords = [(m, _method_words(m, shared)) for m in methods]
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading or x.cells is not None:
            continue
        t = x.joined
        mm = INTEGRATION_VIA.search(t)
        if not mm:
            continue
        s0 = max(t.rfind(". ", 0, mm.start()) + 1, 0)
        clause = t[s0:mm.start()]
        ops = _promised_ops(clause)
        if len(ops) < 1:
            continue
        matched: set[int] = set()
        missing: list[dict] = []
        for op in ops:
            hit = [i for i, (m, ws) in enumerate(mwords) if _compatible(op, m) and _covers(op, ws)]
            if hit:
                matched.update(hit)
            elif op["cls"] != "read":
                missing.append(op)
        if not missing:
            continue
        spare = [m for i, (m, _) in enumerate(mwords) if i not in matched]
        if any(_compatible(op, m) for op in missing for m in spare):
            continue  # свободный метод мог описывать операцию другими словами — не гадаем
        reads = [op for op in ops if op["cls"] == "read"]
        no_read = bool(reads) and not any(m.is_read() for m in methods)
        listed = missing + (reads if no_read else [])
        listed.sort(key=lambda op: clause.find(op["quote"]))
        names = [quoted(op["quote"]) for op in listed]
        short = [quoted(_short_op(op["quote"])) for op in listed]
        frag = _sentence(t, clause.strip()[:40])
        described = fmt_list([f"{m.desc or m.label} ({m.verb} {m.url})".replace(" ()", "") if m.url
                              else (m.desc or m.label or m.verb) for m in methods])
        evidence = [ev(x, frag)]
        for m in methods[:2]:
            dl = m.desc_line or (m.verb_line if m.verb_line.n == m.start else None)
            if dl is not None:
                evidence.append(ev(dl, m.desc if m.desc and m.desc in dl.joined else None))
        one = len(listed) == 1
        out["candidates"].append(candidate(
            "promises.promised_ops",
            title=(f"Нет метода API для обещанной операции {short[0]}" if one
                   else f"Нет методов API для обещанных операций: {fmt_list(short)}"),
            kind="missing_element", criterion="set_complete", severity="critical", blocks="development",
            evidence=evidence,
            problem=(f"Раздел интеграции обещает: {quoted(frag)}. В спецификации описано только: {described}. "
                     f"Для {'операции' if one else 'операций'} {fmt_list(names)} нет метода — ни адреса, ни "
                     "параметров, ни ответа, ни статусов."),
            scenario=(f"Приложению нужно выполнить {fmt_list(names)}: в API нет метода, который можно вызвать, — "
                      "обещанная функция не работает, тест на неё не написать."),
            impact="Обещанную функцию нельзя реализовать и проверить по документу; объём работ по API недооценён.",
            recommendation=("Описать метод для каждой обещанной операции (тип запроса, адрес, параметры, ответ, "
                            "статусы) или убрать операцию из раздела интеграции."),
            question=f"Входят ли {fmt_list(names)} в эту поставку, и кто опишет контракт метода?",
        ))
        out["signals"].append(signal("promises.promised_ops", x, frag,
                                     f"Обещаны операции без метода в спецификации: {fmt_list(names)}; "
                                     f"описано только: {described}.", ("architect", "qa"), "missing_element"))
        return no_read
    return False


def rule_read_promise(doc: Doc, methods: list[Method], out: dict, named: set[str]) -> None:
    if not methods:
        return
    reads = [m for m in methods if m.is_read()]
    promises: list[tuple[Line, str]] = []
    for x in doc.lines:
        if not x.text or x.is_code or x.is_heading:
            continue
        t = x.joined
        m = READ_PROMISE.search(t)
        if not m or not (ACTOR.search(t) or INTEGRATION_CTX.search(t)):
            continue
        promises.append((x, _sentence(t, m.group(0))))
    if not promises:
        return
    if reads:
        # обещание есть и чтение есть — линзе архитектора полезно знать, что именно читается
        names = fmt_list([m.label or m.verb for m in reads])
        out["signals"].append(signal("promises.read", promises[0][0], promises[0][1],
                                     f"Справка для описи, не дефект: обещанный показ данных читают операции {names}.",
                                     ("architect",), "inventory"))
        return
    if any(split_camel(n)[0] in READ_TOKENS for n in named):
        return  # уже есть кандидат «метод чтения упомянут, но не описан»
    described = fmt_list([f"{m.label} ({m.verb})" if m.label else m.verb for m in methods])
    evidence = [ev(p[0], p[1]) for p in promises[:3]]
    mut = [m for m in methods if m.mutating_reason()]
    if mut and mut[0].desc_line is not None and all(e["line"] != mut[0].desc_line.n for e in evidence):
        evidence.append(ev(mut[0].desc_line, mut[0].desc))
    out["candidates"].append(candidate(
        "promises.read_operation",
        title="Обещано чтение данных, но в спецификации API нет ни одной операции чтения",
        kind="missing_element", criterion="set_complete", severity="critical", blocks="development",
        evidence=evidence,
        problem=(f"Документ обещает чтение или показ данных: {quoted(promises[0][1])}. В спецификации описаны "
                 f"только операции изменения: {described}. Как приложение получает текущие значения для "
                 "показа, не описано."),
        scenario=("Клиент открывает экран: приложению нужно показать текущие настройки и значения, но метода, "
                  "который их возвращает, нет — экран пуст или показывает значения по умолчанию."),
        impact="Обещанную функцию показа нельзя реализовать и протестировать; объём работ недооценён.",
        recommendation=("Добавить в спецификацию метод чтения (GET без побочных эффектов) со всеми показываемыми "
                        "полями или убрать обещание чтения из требований."),
        question="Какие данные приложение должно получать для экрана и каким методом?",
    ))
    out["signals"].append(signal("promises.read_operation", promises[0][0], promises[0][1],
                                 f"Обещано чтение/показ, но описаны только операции изменения: {described}.",
                                 ("architect", "qa"), "missing_element"))


def run(doc: Doc, out: dict) -> None:
    methods = out.get("_methods") or []
    named = rule_named_methods(doc, methods, out)
    if rule_promised_ops(doc, methods, out):
        return  # чтение без метода уже названо среди обещанных операций
    rule_read_promise(doc, methods, out, named)
