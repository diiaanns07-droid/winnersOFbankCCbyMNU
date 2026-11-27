"""Маскирование персональных данных (№30): номера карт, ИИН/БИН, телефоны, почта, IBAN.

Требование закрытого контура банка: в логах, `runs/`, кэше ответов модели (`.bcc_cache`) и — по флагу `--redact` — в
отчёте персональные данные не лежат в открытом виде.

    from bcc_review.v2.rules import redact
    redact.mask("Карта 4400 4301 2345 6781, ИИН 900101300123")   # «Карта •••• •••• •••• 6781, ИИН ••••••••••23»
    redact.mask_obj(record)          # рекурсивно по dict/list/str (ключи не трогает)
    view2, stats = redact.mask_view(view)   # документ до отправки модели: длина строк сохраняется
    python -m bcc_review.v2.rules.redact --check runs .bcc_cache    # аудит: код 1, если есть ПДн в открытом виде

Маска сохраняет длину и разделители («••••»), поэтому номера строк, позиции и сверка цитат по маскированному
документу работают как обычно. Ложные срабатывания сведены к минимуму: карта — по алгоритму Луна (без разделителей —
только 16 цифр с 4/5 в начале или со словом «карта» рядом), ИИН/БИН — по контрольному разряду и дате рождения
(или со словом «ИИН»/«БИН» рядом), телефон — с «+» или казахстанский мобильный «8 7xx». Уже замаскированные
(«4400 43** **** 1234») не трогаем.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

DOT = "•"
KINDS_RU = {"card": "номер карты", "iin": "ИИН/БИН", "phone": "телефон", "email": "почта", "iban": "счёт IBAN"}

CARD = re.compile(r"(?<![\w•*.,/-])(\d{4}(?:([ -])\d{4}){2,3}(?:\2\d{1,3})?|\d{13,19})(?![\w•*]|[.,]\d)")
CARD_CTX = re.compile(r"(?:карт\w*|card|pan|номер)\W{0,3}(?:\w+\W{1,3}){0,3}$", re.I)
IIN = re.compile(r"(?<![\w•*.,/-])(\d{12})(?![\w•*]|[.,]\d)")
IIN_CTX = re.compile(r"(?:ИИН|БИН|IIN|BIN)\W{0,3}$", re.I)
PHONE = re.compile(r"(?<![\w+•*])(?:\+\d{1,3}[\s(-]{0,2}\d{3}[\s)-]{0,2}\d{3}[\s-]?\d{2}[\s-]?\d{2}|"
                   r"8[\s(-]{0,2}7\d{2}[\s)-]{0,2}\d{3}[\s-]?\d{2}[\s-]?\d{2})(?![\w•*])")
EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]{1,64})@([\w-]{1,63}(?:\.[\w-]{1,63})+)(?![\w-])")
IBAN = re.compile(r"(?<![\w•])(KZ\d{2}(?:\s?[0-9A-Z]{4}){4})(?![\w•])")
# служебные адреса — не персональные
ROLE_MAILBOX = re.compile(r"^(?:support|info|help|noreply|no-reply|admin|security|office|contact|hello|team|dev|test|"
                          r"example|user|client|name)$", re.I)
EXAMPLE_DOMAIN = re.compile(r"(?:^|\.)(?:example\.(?:com|org|net|kz)|example|test|local|localhost|invalid)$", re.I)


def luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iin_checksum(d: str) -> bool:
    """Контрольный разряд ИИН/БИН Казахстана: веса 1…11, при остатке 10 — веса 3…11, 1, 2."""
    if len(d) != 12 or not d.isdigit():
        return False
    a = [int(c) for c in d]
    s = sum(a[i] * (i + 1) for i in range(11)) % 11
    if s == 10:
        s = sum(a[i] * ((i + 2) % 11 + 1) for i in range(11)) % 11
        if s == 10:
            return False
    return s == a[11]


def _iin_date(d: str) -> bool:
    """ИИН физического лица: ГГММДД и разряд века/пола 1–6; БИН: ГГММ, тип 4–6 в пятом разряде."""
    yy, mm, dd, c = int(d[:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    if 1 <= c <= 6:
        year = (1800 + 100 * ((c - 1) // 2)) + yy
        try:
            date(year, mm, dd)
            return True
        except ValueError:
            pass
    return 1 <= mm <= 12 and d[4] in "456"


def _mask_digits(s: str, keep_last: int) -> str:
    n = sum(ch.isdigit() for ch in s)
    out, seen = [], 0
    for ch in s:
        if ch.isdigit() or ("A" <= ch <= "Z" and seen >= 2):
            seen += 1
            out.append(ch if seen > n - keep_last else DOT)
        else:
            out.append(ch)
    return "".join(out)


def find(text: str) -> list[dict]:
    """Найденные ПДн: [{"kind", "start", "end", "value"}] без пересечений, по порядку."""
    if not text or not any(ch.isdigit() or ch == "@" for ch in text):
        return []
    hits: list[dict] = []

    def add(kind: str, a: int, b: int) -> None:
        if any(not (b <= h["start"] or a >= h["end"]) for h in hits):
            return
        hits.append({"kind": kind, "start": a, "end": b, "value": text[a:b]})

    for m in IBAN.finditer(text):
        add("iban", m.start(1), m.end(1))
    for m in EMAIL.finditer(text):
        local, domain = m.group(1), m.group(2)
        if ROLE_MAILBOX.match(local) or EXAMPLE_DOMAIN.search(domain):
            continue
        add("email", m.start(), m.end())
    for m in CARD.finditer(text):
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if not 13 <= len(digits) <= 19 or len(set(digits)) == 1 or not luhn(digits):
            continue
        if raw.isdigit() and not ((len(digits) == 16 and digits[0] in "45")
                                  or CARD_CTX.search(text[max(0, m.start() - 40):m.start()])):
            continue
        add("card", m.start(1), m.end(1))
    for m in IIN.finditer(text):
        d = m.group(1)
        ctx = IIN_CTX.search(text[max(0, m.start() - 12):m.start()])
        if ctx or (iin_checksum(d) and _iin_date(d)):
            add("iin", m.start(1), m.end(1))
    for m in PHONE.finditer(text):
        if sum(ch.isdigit() for ch in m.group(0)) >= 10:
            add("phone", m.start(), m.end())
    hits.sort(key=lambda h: h["start"])
    return hits


def _masked(h: dict) -> str:
    v, k = h["value"], h["kind"]
    if k == "card":
        return _mask_digits(v, 4)
    if k == "iban":
        return v[:2] + _mask_digits(v[2:], 4)
    if k == "iin":
        return _mask_digits(v, 2)
    if k == "phone":
        lead = re.match(r"^(\+\d{1,3}|8)", v)
        head = lead.group(0) if lead else ""
        return head + _mask_digits(v[len(head):], 2)
    if k == "email":
        local, _, domain = v.partition("@")
        return local[:1] + DOT * (len(local) - 1) + "@" + domain
    return DOT * len(v)


def mask(text: str) -> str:
    """Текст с замаскированными ПДн; длина и разделители сохраняются."""
    if not isinstance(text, str):
        return text
    hits = find(text)
    if not hits:
        return text
    out, pos = [], 0
    for h in hits:
        out.append(text[pos:h["start"]])
        out.append(_masked(h))
        pos = h["end"]
    out.append(text[pos:])
    return "".join(out)


def mask_obj(obj: Any) -> Any:
    """Копия словаря/списка со всеми строковыми значениями через `mask` (ключи — как есть)."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_obj(v) for v in obj]
    return obj


def mask_view(view: dict) -> tuple[dict, dict]:
    """Документ (DocView) с маскированными строками и счётчик найденного по видам: ({…}, {"card": 2, …})."""
    stats: dict[str, int] = {}
    lines = []
    for ln in view.get("lines") or []:
        if isinstance(ln, dict) and isinstance(ln.get("text"), str):
            hits = find(ln["text"])
            for h in hits:
                stats[h["kind"]] = stats.get(h["kind"], 0) + 1
            lines.append({**ln, "text": mask(ln["text"])} if hits else ln)
        else:
            lines.append(ln)
    out = {**view, "lines": lines}
    if stats:
        out["redacted"] = stats
    return out, stats


def summary(stats: dict[str, int]) -> str:
    """«Скрыто персональных данных: номер карты — 2, телефон — 1» для предупреждения в отчёте."""
    if not stats:
        return ""
    return "Скрыто персональных данных: " + ", ".join(f"{KINDS_RU.get(k, k)} — {n}" for k, n in sorted(stats.items()))


def scan_paths(paths: Iterable[str | Path], limit: int = 50) -> list[dict]:
    """Аудит каталогов (`runs/`, `.bcc_cache`, логи): файлы с ПДн в открытом виде, [{"file", "kind", "sample"}]."""
    found: list[dict] = []
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
        for p in files:
            if p.suffix.lower() not in (".json", ".jsonl", ".log", ".txt", ".md", ".html", ".csv", ""):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for h in find(text):
                found.append({"file": str(p), "kind": h["kind"], "sample": _masked(h)})
                if len(found) >= limit:
                    return found
                break
    return found


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.rules.redact",
                                 description="Маскирование персональных данных и аудит каталогов прогонов.")
    ap.add_argument("paths", nargs="*", help="файлы или каталоги")
    ap.add_argument("--check", action="store_true", help="аудит: код 1, если найдены ПДн в открытом виде")
    a = ap.parse_args(argv)
    if a.check:
        found = scan_paths(a.paths or ["runs", ".bcc_cache"])
        for f in found:
            print(f"{f['file']}: {KINDS_RU.get(f['kind'], f['kind'])} в открытом виде ({f['sample']})")
        print("Персональных данных в открытом виде не найдено." if not found else f"Найдено файлов: {len(found)}.")
        return 1 if found else 0
    for p in a.paths:
        text = Path(p).read_text(encoding="utf-8")
        sys.stdout.write(mask(text))
    if not a.paths:
        sys.stdout.write(mask(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
