"""Обещания без реализации: операция названа или обещана, но в спецификации API её нет.

* метод назван по имени («методом getX», «Методы getX и setY»), но не описан;
* документ обещает чтение или показ данных («читает», «показывает», «отображает», «чтение»), а среди
  описанных методов нет ни одной операции чтения.
"""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, fmt_list, quoted, signal
from .api import READ_TOKENS, Method, split_camel

METHOD_NAME = re.compile(r"\b([a-z]{2,}[A-Z][A-Za-z0-9]*)\b")
METHOD_CTX = re.compile(r"метод\w*|операци\w*|endpoint|вызов\w*|api", re.I)
READ_PROMISE = re.compile(
    r"\b(читает|читают|чтени\w*|считыва\w*|показыва\w*|отобража\w*|выводит|просматрива\w*|запрашива\w*|"
    r"получени\w+\s+(?:данных|настро\w*|значени\w*|сведени\w*|информаци\w*|статус\w*|остатк\w*|"
    r"сумм\w*|истори\w*)|на\s+экране\s+видн\w*)", re.I)
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
            if any(name.lower() == (m.name or "").lower() for m in methods):
                continue
            missing.setdefault(name, []).append(x)
    reported = set()
    for name, lines in missing.items():
        first = lines[0]
        frag = _sentence(first.joined, name)
        evidence = [ev(first, frag)] + [ev(y, _sentence(y.joined, name)) for y in lines[1:2]]
        described = fmt_list([m.label for m in methods])
        is_read = split_camel(name)[0] in READ_TOKENS
        out["candidates"].append(candidate(
            "promises.named_method",
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
        out["signals"].append(signal("promises.named_method", first, frag,
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
        if not m or not ACTOR.search(t):
            continue
        promises.append((x, _sentence(t, m.group(0))))
    if not promises:
        return
    if reads:
        # обещание есть и чтение есть — линзе архитектора полезно знать, что именно читается
        names = fmt_list([m.label for m in reads])
        out["signals"].append(signal("promises.read", promises[0][0], promises[0][1],
                                     f"Обещано чтение или показ данных; операции чтения: {names}. "
                                     "Проверьте, что они возвращают всё, что показывается.",
                                     ("architect",), "inventory"))
        return
    if any(split_camel(n)[0] in READ_TOKENS for n in named):
        return  # уже есть кандидат «метод чтения упомянут, но не описан»
    described = fmt_list([f"{m.label} ({m.verb})" for m in methods])
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
    rule_read_promise(doc, methods, out, named)
