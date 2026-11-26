"""Заглушки и незаполненный шаблон: «—», «TBD», «заполняются …», пустые поля, неотмеченный чек-лист,
пустой блок согласующих, нет версии или даты. Одно minor-замечание на документ на каждый вид."""
from __future__ import annotations

import re

from ._text import Doc, Line, candidate, ev, fmt_list, norm, quoted, signal, tables

DASH = re.compile(r"^\s*(?:—|–|-|−|n/?a|н/д)\s*\.?\s*$", re.I)
INLINE_DASH = re.compile(r"\b([A-Za-zА-Яа-яЁё][\w\-]{1,20})\s*:\s*(?:—|–|−)\s*(?:[.;,|]|$)")
TBD = re.compile(
    r"\b(TBD|TBA|TODO|FIXME)\b|\[\s*(?:заполнить|указать|уточнить)\s*\]|<\s*(?:заполнить|указать|уточнить)[^>]*>|"
    r"\b(?:заполнить|будет\s+(?:уточнен\w*|определен\w*|определён\w*|описан\w*|добавлен\w*))\s+(?:позже|дополнительно)\b",
    re.I)
# Строка целиком — заглушка: «заполняются тестировщиками», «уточняется», «будет описано позже».
TBD_LINE = re.compile(r"^(?:заполня(?:ется|ются)|уточня(?:ется|ются)|будет\s+\w+|будут\s+\w+|в\s+разработке)\b",
                      re.I)
UNMARKED = re.compile(r"\bДа\s*/\s*Нет\b", re.I)
APPROVAL_COLS = ("фио", "подпись", "согласующ", "подразделени", "должност", "дата согласования", "визa", "виза")
APPROVAL_HEAD = re.compile(r"(блок|лист)\s+согласовани\w*|согласующ\w*|согласовани\w+\s+документа", re.I)
VERSION = re.compile(r"верси\w*[^\n]{0,30}?\d+(?:\.\d+)+|\bv(?:er)?\.?\s?\d+\.\d+|\bversion\b[^\n]{0,20}\d", re.I)
DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
NOT_FILLED = re.compile(r"не\s+заполнен\w*|не\s+проставлен\w*|не\s+указан\w*|отсутству\w*", re.I)


def _is_kv_table_row(line: Line, ncols: int) -> bool:
    return bool(line.cells) and ncols == 2


def rule_dash(doc: Doc, out: dict) -> None:
    hits: list[tuple[Line, str]] = []
    for t in tables(doc):
        ncols = len(t.header.cells or [])
        if ncols != 2:
            continue
        for r in t.rows:
            if r.cells and len(r.cells) >= 2 and r.cells[0] and DASH.match(r.cells[1]):
                hits.append((r, " | ".join(r.cells[:2])))
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        for m in INLINE_DASH.finditer(x.joined):
            frag = m.group(0).rstrip(".;,| ").strip()
            if (x, frag) not in hits:
                hits.append((x, frag))
    if not hits:
        return
    hits.sort(key=lambda h: h[0].n)
    labels = [h[1] for h in hits]
    out["candidates"].append(candidate(
        "placeholder.dash",
        title=f"Поля документа заполнены прочерком: {fmt_list([quoted(s) for s in labels[:4]])}",
        kind="placeholder", criterion="complete", severity="minor", blocks="none",
        evidence=[ev(h[0], h[1]) for h in hits[:3]],
        problem=("Вместо значения стоит прочерк. Неясно, значения нет, оно не нужно или его забыли указать: "
                 + fmt_list([quoted(s) for s in labels]) + "."),
        scenario="Команда разработки или эксплуатации ищет значение (адрес, ссылку, параметр) и не находит его.",
        impact="Работа останавливается на уточнении; в промышленную среду нечего настраивать.",
        recommendation="Указать значения или явно написать «не применяется» с причиной.",
        rewrite="; ".join(f"{s.split(':')[0].split('|')[0].strip()}: <уточнить: значение>" for s in labels[:4]),
    ))


def rule_tbd(doc: Doc, out: dict) -> None:
    hits = []
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        m = TBD.search(x.joined)
        if not m and x.cells is None and len(x.text.split()) <= 6:
            m = TBD_LINE.match(x.text)
        if m:
            frag = x.joined if len(x.joined) <= 120 else m.group(0)
            hits.append((x, frag))
    if not hits:
        return
    out["candidates"].append(candidate(
        "placeholder.tbd",
        title=f"Раздел документа оставлен заглушкой: {quoted(hits[0][1])}",
        kind="placeholder", criterion="complete", severity="minor", blocks="testing",
        evidence=[ev(h[0], h[1]) for h in hits[:3]],
        problem=("Вместо содержания стоит заглушка: " + fmt_list([quoted(h[1]) for h in hits[:4]]) + ". "
                 "Раздел не заполнен, и по нему нельзя работать."),
        scenario="Тестировщик или разработчик открывает раздел и видит только заглушку.",
        impact="Раздел не выполняет своей роли; при приёмке нечем подтвердить требования.",
        recommendation="Заполнить раздел до передачи в разработку или указать срок и ответственного.",
    ))


def rule_empty_fields(doc: Doc, out: dict) -> None:
    hits = []
    for t in tables(doc):
        if len(t.header.cells or []) != 2:
            continue
        if any(k in " ".join(t.cols) for k in APPROVAL_COLS):
            continue
        for r in t.rows:
            if r.cells and len(r.cells) >= 2 and r.cells[0] and not r.cells[1].strip():
                hits.append(r)
    if not hits:
        return
    names = [h.cells[0] for h in hits]
    out["candidates"].append(candidate(
        "placeholder.empty_fields",
        title=f"Не заполнены поля: {fmt_list([quoted(n) for n in names[:4]])}",
        kind="placeholder", criterion="complete", severity="minor", blocks="none",
        evidence=[ev(h, h.cells[0]) for h in hits[:3]],
        problem="Поля шаблона оставлены пустыми: " + fmt_list([quoted(n) for n in names]) + ".",
        impact="Документ не прослеживается до источника и ответственных.",
        recommendation="Заполнить поля или указать «не применяется» с причиной.",
    ))


def rule_checklist(doc: Doc, out: dict) -> None:
    rows = [x for x in doc.lines if x.cells and UNMARKED.search(x.joined)]
    if len(rows) < 2:
        return
    first = rows[0]
    name = first.cells[0] if first.cells and not UNMARKED.search(first.cells[0]) else ""
    frag = f"{name} | {first.cells[1]}" if name and len(first.cells) > 1 else first.joined
    evidence = [ev(first, frag)]
    note = next((x for x in doc.lines[max(0, first.n - 8):first.n] if x.text and NOT_FILLED.search(x.text)
                 and re.search(r"чек|отметк|пункт", x.text, re.I)), None)
    if note is not None:
        evidence.insert(0, ev(note, _sentence(note.text, NOT_FILLED)))
    out["candidates"].append(candidate(
        "placeholder.checklist",
        title=f"Чек-лист ревью не заполнен: в {len(rows)} пунктах не выбрано «Да» или «Нет»",
        kind="placeholder", criterion="conforming", severity="minor", blocks="none",
        evidence=evidence,
        problem=(f"В {len(rows)} строках чек-листа оставлены оба варианта «Да / Нет»: ни один пункт ревью не "
                 "отмечен, поэтому не видно, что проверено, а что нет."),
        impact="Процесс ревью банка не пройден формально; решение о старте разработки нечем подтвердить.",
        recommendation="Пройти чек-лист: отметить каждый пункт и дать комментарий к пунктам «Нет».",
    ))


def _sentence(text: str, rx: re.Pattern) -> str:
    m = rx.search(text)
    if not m:
        return text
    s0 = text.rfind(".", 0, m.start()) + 1
    e = text.find(".", m.end())
    return text[s0:e + 1 if e != -1 else len(text)].strip()


def rule_approvals(doc: Doc, out: dict) -> None:
    for t in tables(doc):
        cols = " ".join(t.cols)
        if sum(1 for k in APPROVAL_COLS if k in cols) < 2:
            continue
        filled = [r for r in t.rows if r.cells and any(c.strip() for c in r.cells)]
        if filled:
            continue
        head = None
        for k in range(t.header.n - 1, max(0, t.header.n - 5), -1):
            x = doc.get(k)
            if x and x.text and APPROVAL_HEAD.search(x.text):
                head = x
                break
        evidence = ([ev(head)] if head else []) + [ev(t.header)]
        out["candidates"].append(candidate(
            "placeholder.approvals",
            title="Блок согласующих пуст: нет ни одного согласующего",
            kind="placeholder", criterion="conforming", severity="minor", blocks="none",
            evidence=evidence,
            problem=(f"В таблице {quoted(t.header.joined)} нет ни одной заполненной строки: не указаны "
                     "подразделения, ответственные и подписи."),
            impact="Документ не согласован; изменения, затрагивающие другие системы, не подтверждены их владельцами.",
            recommendation="Указать согласующих (подразделение, ФИО, дата) и получить согласование до разработки.",
        ))
        return


def rule_version(doc: Doc, out: dict) -> None:
    text = "\n".join(x.joined for x in doc.lines if x.text)
    has_version = bool(VERSION.search(text))
    if has_version:
        return
    explicit = next((x for x in doc.lines if x.text and re.search(r"верси", x.text, re.I)
                     and NOT_FILLED.search(x.text) and not x.cells), None)
    meta = next((x for x in doc.lines[:60] if x.cells and len(x.cells) == 2 and x.cells[0]
                 and norm(x.cells[0]) not in ("поле", "field", "параметр")), None)
    anchor = explicit or meta or next((x for x in doc.lines if x.text), None)
    if anchor is None:
        return
    has_date = bool(DATE.search("\n".join(x.joined for x in doc.lines[:60] if x.text)))
    what = "версия документа" + ("" if has_date else " и дата")
    frag = _sentence(anchor.text, NOT_FILLED) if anchor is explicit else (
        " | ".join(anchor.cells[:2]) if anchor.cells else anchor.joined)
    out["candidates"].append(candidate(
        "placeholder.version",
        title=f"Не указана {what}",
        kind="placeholder", criterion="modifiable", severity="minor", blocks="none",
        evidence=[ev(anchor, frag)],
        problem=(f"В документе не указана {what}"
                 + (f": {quoted(frag)}." if anchor is explicit else " — в общих сведениях нет такого поля.")
                 + " Нельзя сослаться на конкретную редакцию требований."),
        impact="Разработка, тестирование и приёмка могут опираться на разные редакции документа.",
        recommendation="Добавить в общие сведения версию и дату документа и вести историю изменений.",
        rewrite="Версия документа | <уточнить: номер> от <уточнить: дата>",
    ))


def run(doc: Doc, out: dict) -> None:
    rule_dash(doc, out)
    rule_tbd(doc, out)
    rule_empty_fields(doc, out)
    rule_checklist(doc, out)
    rule_approvals(doc, out)
    rule_version(doc, out)
