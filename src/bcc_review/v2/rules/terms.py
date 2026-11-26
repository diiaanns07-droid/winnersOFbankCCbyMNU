"""Терминология компонентов: один и тот же компонент назван по-разному (сигнал для набора, №09).

Берутся именные группы вида «<вид компонента> <предмет>» («сервис …», «учёт …», «хранилище …», «модуль …»)
и стрелочные цепочки «A → B». Группы с одним предметом и разными видами — кандидаты в синонимы.
"""
from __future__ import annotations

import re

from ._text import Doc, fmt_list, quoted, signal

HEAD = r"(сервис\w*|служб\w+|модул\w+|подсистем\w+|хранилищ\w+|уч[её]т\w*|процессинг\w*|шлюз\w*|реестр\w*|" \
       r"журнал\w*|контур\w*|платформ\w+|систем\w+|база\s+данных|бд)"
PHRASE = re.compile(rf"\b{HEAD}\s+([а-яёa-z]{{4,}})\b", re.I)
ARROW_PART = re.compile(r"[→>]|->")


def _stem(w: str) -> str:
    return w.lower()[:6]


def run(doc: Doc, out: dict) -> None:
    groups: dict[str, dict[str, tuple]] = {}
    for x in doc.lines:
        if not x.text or x.is_code or x.cells is not None:
            continue
        t = x.joined
        found = list(PHRASE.finditer(t))
        for m in found:
            head, obj = m.group(1).lower(), m.group(2)
            groups.setdefault(_stem(obj), {}).setdefault(_stem(head), (m.group(0), x))
        if found and ARROW_PART.search(t):  # стрелочная схема компонентов, а не путь по экранам
            for part in re.split(r"\s*(?:→|->|>)\s*|[.:;]", t):
                p = part.strip()
                if 1 <= len(p.split()) <= 2 and re.fullmatch(r"[а-яё]+", p.split()[0], re.I):
                    w = p.split()[-1]
                    if len(w) >= 5:
                        groups.setdefault(_stem(w), {}).setdefault("·" + _stem(p.split()[0]), (p, x))
    for stem, heads in groups.items():
        names = {v[0].lower(): v for v in heads.values()}
        if len(names) < 2 or not any(not h.startswith("·") for h in heads):
            continue
        items = sorted(names.values(), key=lambda v: v[1].n)
        first = items[0]
        out["signals"].append(signal(
            "terms.component_names", first[1], first[0],
            "Похоже, один компонент назван по-разному: " + fmt_list([quoted(v[0]) for v in items[:4]])
            + " (строки " + ", ".join(str(v[1].n) for v in items[:4]) + "). Проверьте, один ли это компонент.",
            ("consistency", "architect"), "terminology"))
