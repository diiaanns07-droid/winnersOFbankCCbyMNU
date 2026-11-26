"""Правки «было → стало», редакция и закрытие после повторного анализа (№08).

``propose_patch(document, finding, decision, question=None) -> {state, edits, warnings}``
``write_revision(document, edits, output_md, *, source=None, ...) -> Path``

Edit = {block_id, start, end, old, new} (+ source_sha256, question_id, origin).
Координаты — кодовые точки Unicode в ``block.text`` с нуля, правая граница
исключена. Предусловие каждой правки: ``block.text[start:end] == old`` и
``document.id == source_sha256``.

Состояния ``propose_patch``:

* ``open`` — ответа нет; документ не меняется, вопрос открыт;
* ``deferred`` — владелец отложил решение; документ не меняется, вопрос открыт;
* ``proposed`` — решение принято, правки проверены и готовы к записи;
* ``needs_wording`` — решение принято, но допустимой формулировки нет
  (свой ответ без «Формулировка:», правка с вымышленным значением, правка не
  найдена в тексте). Текст не меняется;
* ``stale`` — ответ дан для другой версии документа (``source_sha256``);
* ``already_applied`` — правка уже есть в тексте (повторное применение);
* ``precondition_failed`` — в тексте нет ни старого, ни нового фрагмента;
* ``invalid_choice`` — выбран вариант, которого нет в вопросе;
* ``collision`` — (ставит ``answers.apply_answers``) правка пересекается с
  правкой другого решения; нужен выбор владельца.

Принятие решения и закрытие замечания различаются: ``write_revision``
пишет манифест со статусом ``applied_not_verified``, а «закрыто» появляется
только в ``closure_status`` по повторному анализу именно этой редакции
(совпадает SHA-256 файла).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from ._doc import (
    DocView, as_list, format_loc, get, invented_values, loc_lines, norm_text, sha256_bytes,
    short_sha, to_plain,
)

REVISION_SCHEMA = "bcc-review/revision@1"
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$")


class PatchError(ValueError):
    """Правка не записана. Наследник ValueError: движок ловит его вместе с ошибками резерва."""

    code = "patch_error"

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = details


class StaleSourceError(PatchError):
    code = "stale_source"


class PreconditionError(PatchError):
    code = "precondition_failed"


class AlreadyAppliedError(PatchError):
    code = "already_applied"


class EditCollisionError(PatchError):
    code = "collision"

    def __init__(self, message: str, collisions: list[dict]):
        super().__init__(message, collisions=collisions)
        self.collisions = collisions


# ---------------------------------------------------------------------------
# Правки
# ---------------------------------------------------------------------------


def normalize_edit(e: Any) -> dict:
    d = dict(to_plain(e))
    for k in ("block_id", "old", "new"):
        if k not in d:
            raise PatchError(f"В правке нет поля {k!r}: {d}")
    d["block_id"] = str(d["block_id"])
    d["start"], d["end"] = int(d["start"]), int(d["end"])
    return d


def edit_state(doc: DocView, e: dict) -> str:
    """ok | already_applied | precondition_failed | stale — для одной правки."""
    if e.get("source_sha256") and doc.id and e["source_sha256"] != doc.id:
        return "stale"
    b = doc.block(e["block_id"])
    if b is None:
        return "precondition_failed"
    if b.text[e["start"]: e["end"]] == e["old"]:
        return "ok"
    new = e.get("new", "")
    if new and b.text[e["start"]: e["start"] + len(new)] == new:
        return "already_applied"
    if new and new in b.text and e["old"] not in b.text:
        return "already_applied"
    if not new and e["old"] not in b.text:
        return "already_applied"
    return "precondition_failed"


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    for m in _SENTENCE_RE.finditer(text):
        if m.start() <= start < m.end():
            s, e = m.start(), m.end()
            while e > s and text[e - 1].isspace():
                e -= 1
            if end <= e:
                return s, e
            return s, max(e, end)
    return start, end


def _custom_edit(doc: DocView, q: Any, decision: Any) -> dict | None:
    target = get(q, "target")
    if not target:
        return None
    b = doc.block(get(target, "block_id"))
    if b is None:
        return None
    s, e = _sentence_span(b.text, int(get(target, "start")), int(get(target, "end")))
    old = b.text[s:e]
    wording = decision.wording.strip()
    family = get(q, "family")
    new = f"{old} {wording}" if family == "gap" else wording
    return {
        "block_id": b.id, "start": s, "end": e, "old": old, "new": new,
        "source_sha256": doc.id, "origin": "owner",
    }


def resolve_spec(doc: DocView, spec: Any) -> tuple[dict | None, str]:
    """Правка без координат {block_id?, old, new} -> (Edit, "ok") или (None, причина).

    Координаты считает код: ``old`` должен встретиться ровно один раз — в
    указанном блоке, иначе во всём документе. Пробелы и переносы внутри
    фрагмента сравниваются нестрого (экспорт №13 схлопывает их в строке
    вариантов), но в Edit попадает точный текст блока."""
    old = str(get(spec, "old") or "")
    new = get(spec, "new")
    new = "" if new is None else str(new)
    if not old.strip():
        return None, "пустой старый фрагмент"
    bid = get(spec, "block_id")
    scopes = [[doc.block(bid)]] if bid and doc.block(bid) else []
    scopes.append(doc.blocks)
    for blocks in scopes:
        hits = [(b, i, i + len(old)) for b in blocks for i in _positions(b.text, old)]
        if not hits:
            rx = re.compile(r"\s+".join(re.escape(w) for w in old.split()))
            hits = [(b, m.start(), m.end()) for b in blocks for m in rx.finditer(b.text)]
        if len(hits) == 1:
            b, a, z = hits[0]
            return {"block_id": b.id, "start": a, "end": z, "old": b.text[a:z], "new": new,
                    "source_sha256": doc.id}, "ok"
        if len(hits) > 1:
            return None, (f"фрагмент «{old}» встречается {len(hits)} раз — укажите блок "
                          "(«Правка [b0012]: …») или более длинный фрагмент")
    if new and sum(len(_positions(b.text, new)) for b in doc.blocks) == 1:
        return None, "already_applied"
    return None, f"фрагмента «{old}» нет в текущей версии документа"


def _positions(text: str, sub: str) -> list[int]:
    out, i = [], text.find(sub)
    while sub and i != -1:
        out.append(i)
        i = text.find(sub, i + 1)
    return out


def _overlaps(a: dict, b: dict) -> bool:
    return a["block_id"] == b["block_id"] and a["start"] < b["end"] and b["start"] < a["end"]


def propose_patch(document: Any, finding: Any, decision: Any, question: Any = None) -> dict:
    """Правка по решению владельца. Ничего не пишет на диск.

    Два вызова:

    * ``propose_patch(document, finding, decision, question=q)`` — вариант берётся
      из вопроса (прежний вызов №08);
    * ``propose_patch(document, None, decision)`` — вызов движка: правки уже
      разрешены ``parse_answers`` из файла ответов (строка «Варианты:» №13 и
      явные «Правка: «…» → «…»»).

    Если ``decision`` — dict (так его передаёт движок), итог записывается в него же:
    ``edits`` (проверенные), ``patch_state``, ``decision_status``, ``fix_status``,
    ``note``. Этот dict движок кладёт в Report.decisions."""
    from .answers import Decision  # локально: answers использует этот модуль
    from .clarify import Question

    doc = DocView(document)
    dec = Decision.coerce(decision)
    q = Question.from_dict(question) if question is not None else None
    out: dict[str, Any] = {
        "question_id": dec.question_id,
        "finding_ids": list(q.finding_ids) if q is not None else
        ([str(get(finding, "id"))] if finding is not None else []),
        "choice": dec.choice, "state": "open", "edits": [], "warnings": [], "expected_result": None,
    }
    _propose(doc, finding, dec, q, out)
    if out["state"] == "collision" and dec.note:
        out["reason"] = dec.note  # полная причина с фрагментами — из разбора всех ответов
    if isinstance(decision, dict):
        _record(decision, out)
    return out


def _record(d: dict, out: dict) -> None:
    state = out["state"]
    d["edits"] = out["edits"]  # те же объекты: write_revision отметит их как внесённые
    d["patch_state"] = state
    d["decision_status"] = decision_status(state)
    d["fix_status"] = "awaiting_revision" if state == "proposed" else "not_applied"
    reasons = [w for w in out["warnings"] if not w.startswith("[note]")]
    d["note"] = ("правка передана на запись редакции; закрытие — после повторного анализа"
                 if state == "proposed" else out.get("reason") or (reasons[0] if reasons else state))


def _propose(doc: DocView, finding: Any, dec: Any, q: Any, out: dict) -> None:
    qid = dec.question_id
    warn = out["warnings"]
    if dec.choice == "open":
        warn.append(f"[open] {qid}: ответа нет — документ не меняется, вопрос остаётся открытым")
        return
    if not dec.source_sha256 or (doc.id and dec.source_sha256 != doc.id):
        out["state"] = "stale"
        warn.append(
            f"[stale_source] {qid}: ответ относится к другой редакции ({short_sha(dec.source_sha256)}), "
            f"текущий документ {short_sha(doc.id)}. Правка не применяется; "
            "сформируйте вопросы для текущей версии и перенесите решение."
        )
        return
    if dec.choice == "defer":
        out["state"] = "deferred"
        warn.append(f"[deferred] {qid}: решение отложено — документ не меняется, вопрос остаётся открытым")
        return
    if dec.choice == "invalid":
        out["state"] = "invalid_choice"
        warn.append(f"[invalid_choice] {qid}: выбрано несколько вариантов ({dec.answer!r}) — оставьте один")
        return
    if dec.patch_state == "collision":
        out["state"] = "collision"
        # полный текст с фрагментами — в предупреждении разбора и в note решения
        warn.append(f"[collision] {qid}: решение не применено — его правка пересекается с правкой "
                    "другого решения; нужен выбор владельца")
        return

    allowed = [doc.full_text(), dec.answer]
    owner = [e for e in dec.edits if e.get("origin") == "owner"] + \
            [s for s in dec.edit_specs if s.get("origin") == "owner"]
    option: list[dict] = []
    if dec.choice == "custom":
        out["expected_result"] = dec.answer
        if not owner:
            if not dec.wording:
                out["state"] = "needs_wording"
                warn.append(f"[needs_wording] {qid}: свой ответ сохранён как решение; для правки текста "
                            "добавьте «Правка: «старый фрагмент» → «новый текст»» или «Формулировка: …»")
                return
            target_q = q if q is not None else _finding_question(doc, finding)
            ce = _custom_edit(doc, target_q, dec) if target_q is not None else None
            if ce is None:
                out["state"] = "needs_wording"
                warn.append(f"[no_target] {qid}: «Формулировка:» без цитаты вопроса — укажите "
                            "«Правка: «старый фрагмент» → «новый текст»»")
                return
            option = [ce]
    else:
        if q is not None:
            opt = q.option(dec.choice)
            if opt is None:
                out["state"] = "invalid_choice"
                warn.append(f"[invalid_choice] {qid}: варианта {dec.choice} нет в вопросе")
                return
            out["expected_result"] = opt.observable_result
            option = [dict(to_plain(e)) for e in opt.edits]
        else:
            out["expected_result"] = dec.option_text
            option = [e for e in dec.edits if e.get("origin") != "owner"] + \
                     [s for s in dec.edit_specs if s.get("origin") != "owner"]
            if dec.option_text is None and not owner:
                out["state"] = "needs_wording"
                warn.append(f"[no_option_data] {qid}: в файле ответов нет строки «Варианты:» с вариантом "
                            f"{dec.choice} — правку не из чего построить; добавьте «Правка: «…» → «…»»")
                return
        if dec.comment:
            warn.append(f"[note] {qid}: комментарий владельца сохранён в решении: «{dec.comment}»")

    resolved: list[dict] = []
    for raw in owner + option:
        e = dict(to_plain(raw))
        if not isinstance(e.get("start"), int) or not isinstance(e.get("end"), int):
            r, why = resolve_spec(doc, e)
            if r is None:
                if why == "already_applied":
                    out["state"] = "already_applied"
                    warn.append(f"[already_applied] {qid}: правка уже есть в тексте — повторно не применяется")
                else:
                    out["state"] = "precondition_failed"
                    warn.append(f"[precondition_failed] {qid}: {why}")
                return
            r["origin"] = e.get("origin", "option")
            e = r
        e = normalize_edit(e)
        if e.get("origin") != "owner" and any(_overlaps(e, o) for o in resolved if o.get("origin") == "owner"):
            continue  # своя правка владельца в том же месте важнее правки варианта
        resolved.append(e)
    if not resolved:
        out["state"] = "needs_wording"
        warn.append(f"[needs_wording] {qid}: у варианта {dec.choice} нет проверенной правки текста — "
                    "решение сохранено, текст не меняется")
        return
    inner = find_collisions(resolved)
    if inner:
        out["state"] = "collision"
        warn.append(f"[collision] {qid}: правки одного решения пересекаются: {describe_collision(inner[0], doc)}")
        return

    states = []
    for e in resolved:
        e.setdefault("source_sha256", doc.id)
        e["question_id"] = qid
        bad = invented_values(e["new"], e["old"], allowed)
        if bad:
            out["state"] = "needs_wording"
            out["edits"] = []
            warn.append(f"[invented_value] {qid}: в новой формулировке значения {', '.join(bad)}, "
                        "которых нет ни в документе, ни в ответе владельца — правка не попадает в редакцию")
            return
        states.append(edit_state(doc, e))
        e["loc"] = format_loc(doc.block(e["block_id"]), e["start"], e["end"])
        out["edits"].append(e)

    if all(st == "ok" for st in states):
        out["state"] = "proposed"
    elif all(st == "already_applied" for st in states):
        out["state"] = "already_applied"
        out["edits"] = []
        warn.append(f"[already_applied] {qid}: правка уже есть в тексте — повторно не применяется")
    else:
        out["state"] = "precondition_failed"
        out["edits"] = []
        warn.append(f"[precondition_failed] {qid}: старый фрагмент не совпадает с текстом "
                    f"({', '.join(states)}) — правка не применяется")


def _finding_question(doc: DocView, finding: Any) -> dict:
    ev = next((e for e in as_list(get(finding, "evidence")) if doc.verify_evidence(e)), None)
    return {"target": to_plain(ev), "family": None}


# ---------------------------------------------------------------------------
# Коллизии
# ---------------------------------------------------------------------------


def find_collisions(edits: Iterable[Any]) -> list[dict]:
    """Пары правок, которые меняют пересекающиеся фрагменты одного блока по-разному."""
    es = [normalize_edit(e) for e in edits]
    out = []
    for i, a in enumerate(es):
        for b in es[i + 1:]:
            if a["block_id"] != b["block_id"]:
                continue
            same = (a["start"], a["end"], a["new"]) == (b["start"], b["end"], b["new"])
            touch = a["start"] < b["end"] and b["start"] < a["end"]
            # две вставки в одну точку тоже требуют решения о порядке
            point = a["start"] == a["end"] == b["start"] == b["end"]
            if (touch or point) and not same:
                out.append({
                    "block_id": a["block_id"],
                    "a": {k: a.get(k) for k in ("question_id", "start", "end", "old", "new")},
                    "b": {k: b.get(k) for k in ("question_id", "start", "end", "old", "new")},
                })
    return out


def describe_collision(c: dict, doc: DocView | None = None) -> str:
    b = doc.block(c["block_id"]) if doc else None
    where = format_loc(b) if b else f"блок {c['block_id']}"
    a, bb = c["a"], c["b"]
    return (f"Правки {a.get('question_id') or '?'} и {bb.get('question_id') or '?'} меняют пересекающиеся "
            f"фрагменты ({where}): «{a['old']}» → «{a['new']}» и «{bb['old']}» → «{bb['new']}». "
            "Нужно решение владельца: какой вариант оставить или общая формулировка.")


# ---------------------------------------------------------------------------
# Перенос правки в исходный Markdown
# ---------------------------------------------------------------------------


def _align(src: str, blk: str) -> list[int] | None:
    """Позиция в src для каждого символа blk (blk = src без разметки, пробелы
    сжаты). Пробельные символы эквивалентны друг другу."""
    m, j = [], 0
    for ch in blk:
        while j < len(src) and not (src[j] == ch or (ch.isspace() and src[j].isspace())):
            j += 1
        if j >= len(src):
            return None
        m.append(j)
        j += 1
        if ch.isspace():
            while j < len(src) and src[j].isspace() and src[j] != "\n":
                j += 1
    return m


def _strip_md(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", s)).strip()


def _map_span(seg: str, block_text: str, e: dict, warns: list[str]) -> tuple[int, int]:
    old = e["old"]
    if old and block_text.count(old) == 1 and seg.count(old) == 1:
        a = seg.index(old)
        return a, a + len(old)
    m = _align(seg, block_text)
    if m is None or not block_text:
        raise PreconditionError(f"Не удалось сопоставить блок {e['block_id']} с исходным текстом")
    if e["start"] == e["end"]:
        a = m[e["start"]] if e["start"] < len(m) else m[-1] + 1
        return a, a
    a, b = m[e["start"]], m[e["end"] - 1] + 1
    if _strip_md(seg[a:b]) != _strip_md(old):
        raise PreconditionError(
            f"Фрагмент «{old}» блока {e['block_id']} не сопоставлен с исходной строкой")
    if seg[a:b] != old:
        warns.append(f"[markup_dropped] {e.get('question_id') or ''} {e['block_id']}: "
                     f"внутри «{seg[a:b]}» была разметка, она заменена текстом правки")
    return a, b


def _map_pos(loc_map: list, offsets: list[int], p: int) -> int | None:
    """Позиция p в block.text -> смещение в исходнике по loc.map [[text_start, line, col], ...]."""
    best = None
    for entry in loc_map:
        try:
            ts, line, col = int(entry[0]), int(entry[1]), int(entry[2])
        except (TypeError, ValueError, IndexError):
            return None
        if ts <= p and (best is None or ts >= best[0]):
            best = (ts, line, col)
    if best is None or not (1 <= best[1] < len(offsets)):
        return None
    return offsets[best[1] - 1] + best[2] + (p - best[0])


def _span_via_map(b: Any, text: str, offsets: list[int], e: dict, warns: list[str]) -> tuple[int, int] | None:
    """Точный перенос правки по loc.map (контракт v1). None — карты нет или она не сходится."""
    loc_map = get(b.loc, "map") if b is not None else None
    if not loc_map:
        return None
    if e["start"] == e["end"]:
        a = _map_pos(loc_map, offsets, e["start"])
        return (a, a) if a is not None else None
    a = _map_pos(loc_map, offsets, e["start"])
    z = _map_pos(loc_map, offsets, e["end"] - 1)
    if a is None or z is None:
        return None
    z += 1
    if text[a:z] == e["old"]:
        return a, z
    if _strip_md(text[a:z]) == _strip_md(e["old"]):
        warns.append(f"[markup_dropped] {e.get('question_id') or ''} {e['block_id']}: "
                     f"внутри «{text[a:z]}» была разметка, она заменена текстом правки")
        return a, z
    return None


def _patch_markdown(doc: DocView, text: str, edits: list[dict], warns: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    spans: list[tuple[int, int, str]] = []
    by_block: dict[str, list[dict]] = {}
    for e in edits:
        by_block.setdefault(e["block_id"], []).append(e)
    for bid, es in by_block.items():
        b = doc.block(bid)
        rng = loc_lines(b.loc) if b else None
        if rng and 1 <= rng[0] <= len(lines):
            s0, s1 = offsets[rng[0] - 1], offsets[min(rng[1], len(lines))]
        else:
            s0, s1 = 0, len(text)
        seg = text[s0:s1]
        for e in es:
            exact = _span_via_map(b, text, offsets, e, warns)
            if exact is not None:
                spans.append((exact[0], exact[1], e["new"]))
                continue
            a, z = _map_span(seg, b.text, e, warns)
            spans.append((s0 + a, s0 + z, e["new"]))
    spans.sort(key=lambda t: t[0])
    for (a1, z1, _), (a2, z2, _) in zip(spans, spans[1:]):
        if a2 < z1:
            raise EditCollisionError("Правки пересекаются в исходном тексте", collisions=[])
    out = text
    for a, z, new in sorted(spans, key=lambda t: -t[0]):
        out = out[:a] + new + out[z:]
    return out


# ---------------------------------------------------------------------------
# Текстовая редакция (бинарный исходник или исходник недоступен)
# ---------------------------------------------------------------------------


def _apply_to_block(text: str, es: list[dict]) -> str:
    for e in sorted(es, key=lambda x: -x["start"]):
        text = text[: e["start"]] + e["new"] + text[e["end"]:]
    return text


def _render_text_revision(doc: DocView, edits: list[dict], source_ref: str,
                          manifest_name: str, applied: list[str]) -> str:
    by_block: dict[str, list[dict]] = {}
    for e in edits:
        by_block.setdefault(e["block_id"], []).append(e)
    out = [f"# {doc.title} — текстовая редакция", "",
           "<!-- bcc-review:revision-note -->",
           f"> Текстовая редакция документа «{doc.title}» (формат {doc.format or 'не указан'}, "
           f"SHA-256 `{doc.id}`). Исходный документ: {source_ref}.",
           "> Форматирование оригинала не сохраняется: текст собран из блоков разбора. "
           f"Изменённые блоки и решения перечислены в `{manifest_name}`.",
           f"> Применены решения: {', '.join(applied) if applied else 'нет'}.",
           "<!-- /bcc-review:revision-note -->", ""]
    current: tuple[str, ...] = ()
    for b in doc.blocks:
        path = b.section + ((b.text,) if b.kind == "heading" else ())
        for i, name in enumerate(path):
            if i < len(current) and current[i] == name:
                continue
            out.append("#" * min(i + 2, 6) + " " + name)
            out.append("")
            current = path[: i + 1]
        current = path
        if b.kind == "heading":
            continue
        text = _apply_to_block(b.text, by_block.get(b.id, []))
        if not text.strip():
            continue
        if b.kind == "list_item":
            out.append(f"- {text}")
        elif b.kind == "table_row":
            out.append(f"| {text} |" if " | " in text else text)
        elif b.kind == "code":
            out += ["```", text, "```"]
        else:
            out.append(text)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Запись редакции
# ---------------------------------------------------------------------------


def _source_bytes(source: Any) -> tuple[bytes | None, str | None]:
    if source is None:
        return None, None
    if isinstance(source, bytes):
        return source, None
    p = Path(source)
    return p.read_bytes(), str(p)


def _rel(path: str | None, base: Path) -> str | None:
    if not path:
        return None
    try:
        return os.path.relpath(Path(path).resolve(), base.resolve()).replace(os.sep, "/")
    except ValueError:  # другой диск в Windows
        return Path(path).name


def manifest_path_for(output_md: str | Path) -> Path:
    p = Path(output_md)
    return p.with_name(p.stem + ".revision.json")


def write_revision(
    document: Any,
    edits: Iterable[Any],
    output_md: str | Path,
    *,
    source: Any = None,
    source_path: str | Path | None = None,
    questions: Iterable[Any] | None = None,
    results: dict[str, dict] | None = None,
    decisions: Iterable[Any] | None = None,
) -> Path:
    """Записать одобренную редакцию отдельным файлом и манифест рядом.

    * ``source`` или ``source_path`` (так вызывает движок) — путь или байты
      исходника. Для Markdown/TXT с совпадающим SHA-256 правки переносятся в
      исходный текст, остальные байты (BOM, CRLF, разметка) не меняются. Иначе
      пишется явная текстовая редакция с заголовками и ссылкой на исходник; если
      ``output_md`` не .md/.txt (например, .pdf), она пишется рядом с
      расширением .md — **возвращается фактический путь**.
    * Каждая записанная правка отмечается в переданном dict: ``status =
      "applied_not_verified"``, ``revision``, ``revision_sha256``.
    * Исключения: ``StaleSourceError`` (другая версия), ``AlreadyAppliedError``
      (повтор), ``PreconditionError``, ``EditCollisionError`` (перечень пар).
      При исключении файлы не создаются.
    """
    doc = DocView(document)
    if source is not None and source_path is not None and Path(str(source)) != Path(str(source_path)):
        raise PatchError("Переданы разные source и source_path — непонятно, какой исходник править.")
    if source is None:
        source = source_path
    originals = list(edits)
    es = [normalize_edit(e) for e in originals]
    out_path = Path(output_md)

    for e in es:
        st = edit_state(doc, e)
        if st == "stale":
            raise StaleSourceError(
                f"Правка {e.get('question_id') or ''} подготовлена для версии "
                f"{short_sha(e.get('source_sha256'))}, а документ — {short_sha(doc.id)}. "
                "Редакция не записана.", edit=e)
        if st == "already_applied":
            raise AlreadyAppliedError(
                f"Правка {e.get('question_id') or ''} уже есть в тексте блока {e['block_id']}. "
                "Повторное применение отклонено.", edit=e)
        if st != "ok":
            raise PreconditionError(
                f"В блоке {e['block_id']} нет фрагмента «{e['old']}» в позиции "
                f"{e['start']}–{e['end']}. Редакция не записана.", edit=e)

    uniq: list[dict] = []
    for e in es:
        key = (e["block_id"], e["start"], e["end"], e["new"])
        if any((u["block_id"], u["start"], u["end"], u["new"]) == key for u in uniq):
            continue
        uniq.append(e)
    collisions = find_collisions(uniq)
    if collisions:
        raise EditCollisionError(
            "Редакция не записана: " + " ".join(describe_collision(c, doc) for c in collisions),
            collisions)

    data, src_path = _source_bytes(source)
    if src_path and out_path.resolve() == Path(src_path).resolve():
        raise PatchError("Редакция сохраняется отдельным файлом: путь совпадает с исходником.")
    if data is not None and doc.id and sha256_bytes(data) != doc.id:
        raise StaleSourceError(
            f"Файл исходника ({short_sha(sha256_bytes(data))}) не совпадает с проанализированной "
            f"версией ({short_sha(doc.id)}). Редакция не записана.")

    warns: list[str] = []
    textual = doc.format in {"markdown", "md", "txt", "text", "plain", ""}
    mode = "text_rendition"
    content: str | None = None
    if data is not None and textual:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = None
        if text is not None:
            content = _patch_markdown(doc, text, uniq, warns)
            mode = "markdown_patch"
    applied_q = sorted({e.get("question_id") for e in uniq if e.get("question_id")})
    bom = b"\xef\xbb\xbf" if mode == "markdown_patch" and data.startswith(b"\xef\xbb\xbf") else b""
    if content is None:
        if out_path.suffix.lower() not in {".md", ".markdown", ".txt"}:
            warns.append(f"[revision_suffix] исходник {doc.format or out_path.suffix}: текстовая редакция "
                         f"записана как {out_path.with_suffix('.md').name}, а не {out_path.name}")
            out_path = out_path.with_suffix(".md")
        ref = f"`{_rel(src_path, out_path.parent)}`" if src_path else f"«{doc.title}» (SHA-256 `{doc.id}`)"
        content = _render_text_revision(doc, uniq, ref, manifest_path_for(out_path).name, applied_q)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = bom + content.encode("utf-8")
    out_path.write_bytes(payload)
    rev_sha = sha256_bytes(payload)
    for e in originals:  # «внесено, ожидает проверки» — в тех же dict, что лежат в решениях
        if isinstance(e, dict):
            e.update(status="applied_not_verified", revision=out_path.name, revision_sha256=rev_sha)

    manifest = {
        "schema": REVISION_SCHEMA,
        "status": "applied_not_verified",
        "note": ("Решения владельца приняты и применены к тексту. Закрытие замечаний "
                 "подтверждается только повторным анализом этой редакции (тот же SHA-256)."),
        "base": {"sha256": doc.id, "title": doc.title, "format": doc.format,
                 "source": _rel(src_path, out_path.parent)},
        "revision": {"path": out_path.name, "sha256": rev_sha, "mode": mode},
        "edits": [{**e, "loc": format_loc(doc.block(e["block_id"]), e["start"], e["end"])} for e in uniq],
        "decisions": [to_plain(d) for d in (decisions or [])],
        "questions": _question_records(doc, questions or [], results or {}, uniq),
        "warnings": warns,
    }
    manifest_path_for(out_path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _question_records(doc: DocView, questions: Iterable[Any], results: dict, edits: list[dict]) -> list[dict]:
    recs = []
    for q in questions:
        qid = str(get(q, "id"))
        r = results.get(qid, {})
        q_edits = [e for e in edits if e.get("question_id") == qid]
        state = r.get("state", "open")
        recs.append({
            "id": qid,
            "finding_ids": [str(x) for x in as_list(get(q, "finding_ids"))],
            "family": get(q, "family"),
            "kind": get(q, "kind"),
            "choice": r.get("choice", "open"),
            "patch_state": "applied" if q_edits and state == "proposed" else state,
            "decision_status": decision_status(state),
            "expected_result": r.get("expected_result"),
            "quotes": [get(s, "quote") for s in as_list(get(q, "sources"))],
            "new_texts": [e["new"] for e in q_edits if e["new"]],
        })
    return recs


def decision_status(patch_state: str) -> str:
    """Статус решения владельца (не путать со статусом исправления в тексте)."""
    return {
        "open": "open", "deferred": "deferred", "proposed": "accepted",
        "already_applied": "accepted", "needs_wording": "accepted_needs_wording",
        "stale": "stale", "precondition_failed": "blocked", "invalid_choice": "invalid",
        "collision": "collision",
    }.get(patch_state, patch_state)


def accept_user_revision(base_document: Any, new_path: str | Path, *,
                         questions: Iterable[Any] | None = None,
                         results: dict[str, dict] | None = None,
                         decisions: Iterable[Any] | None = None) -> Path:
    """Принять новую версию, которую владелец подготовил сам (например, DOCX/PDF).

    Пишет манифест рядом с файлом; закрытие по-прежнему только после
    повторного анализа этой версии."""
    doc = DocView(base_document)
    new_path = Path(new_path)
    data = new_path.read_bytes()
    if doc.id and sha256_bytes(data) == doc.id:
        raise PatchError("Новая версия совпадает с исходной по SHA-256 — изменений нет.")
    manifest = {
        "schema": REVISION_SCHEMA,
        "status": "applied_not_verified",
        "note": "Новая версия предоставлена пользователем. Закрытие — после повторного анализа.",
        "base": {"sha256": doc.id, "title": doc.title, "format": doc.format, "source": None},
        "revision": {"path": new_path.name, "sha256": sha256_bytes(data), "mode": "user_supplied"},
        "edits": [],
        "decisions": [to_plain(d) for d in (decisions or [])],
        "questions": [
            {**rec, "patch_state": "applied" if rec["decision_status"] == "accepted" else rec["patch_state"]}
            for rec in _question_records(doc, questions or [], results or {}, [])
        ],
        "warnings": [],
    }
    mp = manifest_path_for(new_path)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mp


# ---------------------------------------------------------------------------
# Закрытие после повторного анализа
# ---------------------------------------------------------------------------

FIX_STATUS_LABEL = {
    "closed_after_reanalysis": "закрыто: повторный анализ редакции замечания не нашёл",
    "still_present": "решение применено, но замечание осталось",
    "applied_unverified": "решение применено, повторного анализа этой редакции нет",
    "open_still_present": "текст не менялся — замечание сохраняется",
    "absent_without_decision": "текст не менялся, но замечание не найдено — проверьте вручную",
    "not_applied": "текст не менялся",
}
_DECISION_PREFIX = {
    "open": "решения нет", "deferred": "решение отложено",
    "accepted_needs_wording": "решение принято без формулировки", "stale": "ответ к другой версии",
    "collision": "коллизия правок", "blocked": "правка не применилась", "invalid": "ответ не распознан",
}


def fix_label(fix: str, decision: str | None) -> str:
    label = FIX_STATUS_LABEL[fix]
    if fix in ("open_still_present", "absent_without_decision", "not_applied") and decision in _DECISION_PREFIX:
        label = f"{_DECISION_PREFIX[decision]}; {label}"
    return label


def _same_issue(rec: dict, nf: Any, new_doc: DocView) -> bool:
    from .clarify import decision_family

    fam = decision_family(nf)
    if rec.get("family") and fam and fam != rec["family"]:
        return False
    old_quotes = [norm_text(q) for q in rec.get("quotes", []) if q]
    news = [norm_text(t) for t in rec.get("new_texts", []) if t]
    for ev in as_list(get(nf, "evidence")):
        q = norm_text(str(get(ev, "quote") or ""))
        if q and any(q == o or (len(q) >= 8 and q in o) or (len(o) >= 8 and o in q) for o in old_quotes):
            return True
        b = new_doc.block(get(ev, "block_id"))
        if b is not None and any(n and n in norm_text(b.text) for n in news):
            return True
    return False


def closure_status(manifest: Any, new_document: Any, new_findings: Iterable[Any]) -> dict:
    """Статус исправления по повторному анализу редакции.

    ``manifest`` — путь к ``*.revision.json`` или его содержимое.
    ``new_document`` — Document, прочитанный из файла редакции.
    ``new_findings`` — находки повторного анализа (Report.findings).
    """
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    nd = DocView(new_document)
    expected = manifest["revision"]["sha256"]
    verified = nd.id == expected
    findings = [f for f in new_findings if str(get(f, "status") or "confirmed") in ("confirmed", "needs_review")]
    warns = []
    if not verified:
        warns.append(f"[not_reanalyzed] анализ выполнен на версии {short_sha(nd.id)}, а редакция — "
                     f"{short_sha(expected)}: статус закрытия не присваивается")
    rows = []
    for rec in manifest.get("questions", []):
        matches = [str(get(f, "id")) for f in findings if _same_issue(rec, f, nd)]
        applied = rec.get("patch_state") == "applied"
        if applied:
            fix = ("still_present" if matches else "closed_after_reanalysis") if verified else "applied_unverified"
        else:
            fix = ("open_still_present" if matches else "absent_without_decision") if verified else "not_applied"
        rows.append({
            "question_id": rec["id"], "finding_ids": rec.get("finding_ids", []),
            "decision_status": rec.get("decision_status"), "choice": rec.get("choice"),
            "fix_status": fix, "fix_label": fix_label(fix, rec.get("decision_status")),
            "matched_finding_ids": matches,
        })
    return {
        "base_sha256": manifest["base"]["sha256"], "revision_sha256": expected,
        "analyzed_sha256": nd.id, "verified_on_revision": verified, "questions": rows,
        "warnings": warns,
    }
