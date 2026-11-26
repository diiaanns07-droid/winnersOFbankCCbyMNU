"""Анти-подгонка: в промптах агента не должно быть слов официального документа хакатона.

    python -m evaluation.v2.antifit [ПУТЬ ...]     # по умолчанию src/bcc_review/v2/prompts/*.md

Агент должен работать на любом банковском ТЗ. Если промпт содержит имена, числа или формулировки
официального документа, качество на нём завышено подгонкой. Список: docs/plan-v2/README.md, раздел 7,
дополнен №15 характерными именами, числами и фразами документа.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .common import ROOT

# (шаблон, пояснение). Регистр не важен, ё = е. Шаблоны — по словам документа, не по общим банковским терминам.
BANNED: list[tuple[str, str]] = [
    (r"\bpush\b", "push (README, разд. 7)"),
    (r"savelimit", "имя метода saveLimit"),
    (r"тиын", "тиын/тиыны"),
    (r"порог", "порог (README, разд. 7)"),
    (r"алмат|almaty", "Алматы"),
    (r"(?<![\w-])ф-\s?[1-4](?!\d)", "Ф-1…Ф-4"),
    (r"alertscontroller", "AlertsController"),
    (r"limit_kzt", "поле limit_kzt"),
    (r"\bcardid\b", "параметр cardId"),
    (r"demo-42", "пример cardId"),
    (r"проверьте сумму", "текст ответа API"),
    (r"карта не найдена", "текст ответа API"),
    (r"требуется вход", "текст ответа API"),
    (r"48 ?500|19 ?900", "числа критериев приёмки"),
    (r"23:58|00:03", "время из критерия приёмки"),
    (r"31 января|1 февраля|февральск", "даты критерия приёмки"),
    (r"личн\w* бюджет", "«личный бюджет» из цели"),
    (r"уведомлени\w* о расходах", "название документа"),
    (r"месячн\w* порог", "название задачи"),
    (r"уч[её]т расходов|сервис расходов", "компоненты архитектуры документа"),
    (r"школа тестирования|учебн\w* контур|практикум", "метаданные документа"),
    (r"проведенн\w* покуп", "формулировка Ф-2"),
    (r"независимо от истории", "формулировка Ф-4"),
    (r"повторная доставка одного события", "формулировка требований к интеграции"),
    (r"сумм\w* покупки в тиынах", "формулировка требований к данным"),
]
_COMPILED = [(re.compile(p, re.I), why) for p, why in BANNED]

DEFAULT_GLOB = "src/bcc_review/v2/prompts/*.md"


def scan_text(text: str) -> list[dict]:
    t = text.replace("ё", "е").replace("Ё", "Е")
    hits = []
    for rx, why in _COMPILED:
        for m in rx.finditer(t):
            line = t.count("\n", 0, m.start()) + 1
            hits.append({"line": line, "match": m.group(0), "why": why})
    return hits


def scan(paths: list[Path]) -> dict[str, list[dict]]:
    out = {}
    for p in paths:
        hits = scan_text(p.read_text(encoding="utf-8"))
        if hits:
            out[str(p.relative_to(ROOT) if p.is_absolute() and ROOT in p.parents else p)] = hits
    return out


def default_paths() -> list[Path]:
    return sorted(ROOT.glob(DEFAULT_GLOB))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in args] or default_paths()
    sys.stdout.reconfigure(encoding="utf-8")
    res = scan(paths)
    if not res:
        print(f"анти-подгонка: чисто ({len(paths)} файлов)")
        return 0
    for f, hits in res.items():
        for h in hits:
            print(f"{f}:{h['line']}: «{h['match']}» — {h['why']}")
    print(f"анти-подгонка: {sum(len(h) for h in res.values())} совпадений в {len(res)} файлах")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
