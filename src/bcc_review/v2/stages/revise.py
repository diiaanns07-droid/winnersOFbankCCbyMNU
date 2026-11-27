"""Этап revise (№11): «было → стало» по critical и major и исправленная редакция документа.

Модель предлагает правки (замена фрагмента строки или вставка после строки), код их применяет к исходному
тексту и помечает: ``[изменено: D-02]`` у заменённой строки, ``[добавлено: D-05]`` у новой. Если на вопрос
по дефекту есть ответ владельца (режим ``--answers``), подставляется он; иначе значение, которое должен
выбрать бизнес, остаётся маркером ``<уточнить: …>``.

Правка, фрагмент которой не найден в документе, не применяется (в ``rewrites`` у неё ``applied: false``) —
исправленная редакция никогда не содержит текста, который модель «вспомнила» неточно.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bcc_review.v2.stages import clarify as _cl

STAGE = "revise"
_SEV = {"critical": 0, "major": 1, "minor": 2}
_PENDING = re.compile(r"<\s*уточнить\s*:[^>]*>", re.I)

SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["rewrites"],
    "properties": {"rewrites": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["finding_id", "summary", "edits"],
        "properties": {
            "finding_id": {"type": "string"},
            "summary": {"type": "string"},
            # промпт просит 1–4 правки; код применяет любое число — пятая правка не стоит повторного ответа
            "edits": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
                "type": "object", "additionalProperties": False, "required": ["action", "line", "old", "new"],
                "properties": {
                    "action": {"type": "string", "enum": ["replace", "insert_after"]},
                    "line": {"type": "integer"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                }}},
        }}}},
}


CHECK_STAGE = "revise_check"
_EDIT_ITEMS = SCHEMA["properties"]["rewrites"]["items"]["properties"]["edits"]
CHECK_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["fixes"],
    "properties": {"fixes": {"type": "array", "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["finding_id", "problem", "edits"],
        "properties": {"finding_id": {"type": "string"}, "problem": {"type": "string"}, "edits": _EDIT_ITEMS}}}},
}
_MARK = re.compile(r"\s*\[(изменено|добавлено|удалено): ([^\]]*)\]")


# --------------------------------------------------------------------------- исходный текст
def _source_lines(ctx: Any, view: Any) -> tuple[list[str], bool]:
    """Строки, к которым применяются правки: исходный MD/TXT (номера строк совпадают с view) или текст view."""
    vlines = _cl._lines(view)
    opts = getattr(ctx, "options", None) or {}
    if not isinstance(opts, dict):
        opts = vars(opts) if hasattr(opts, "__dict__") else {}
    cands = [opts.get(k) for k in ("input", "doc", "path", "input_path", "source")]
    if isinstance(view, dict):
        cands += [view.get("path"), view.get("file")]
    for c in cands:
        if not c:
            continue
        p = Path(str(c))
        if p.suffix.lower() in (".md", ".markdown", ".txt") and p.exists():
            raw = p.read_text(encoding="utf-8-sig").splitlines()
            if not vlines or len(raw) == len(vlines) or abs(len(raw) - len(vlines)) <= 1:
                return raw, True
    return [str(x.get("text", "")) for x in vlines], False


_CMAP = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "'": '"', "—": "-", "–": "-",
                       "‑": "-", "−": "-", " ": " ", " ": " ", " ": " "})


def _cnorm(s: str) -> str:
    """Нормализация 1:1 по символам: позиции в строке сохраняются."""
    return s.translate(_CMAP).lower()


def find_span(raw: str, old: str) -> tuple[int, int] | None:
    """Где в исходной строке стоит фрагмент ``old`` (с точностью до кавычек, тире, пробелов и разметки)."""
    if not old.strip():
        return None
    i = raw.find(old)
    if i >= 0:
        return i, i + len(old)
    target = _cnorm(old).strip()
    target = re.sub(r"\*\*|`|__", "", target)
    parts: list[str] = []
    for ch in target:
        if ch.isspace():
            if not parts or parts[-1] != r"(?:\s|\*\*|`|__)+":
                parts.append(r"(?:\s|\*\*|`|__)+")
        else:
            parts.append(re.escape(ch) + r"(?:\*\*|`|__)*")
    if not parts:
        return None
    m = re.search("".join(parts), _cnorm(raw))
    if not m:
        return None
    end = m.end()
    while end > m.start() and raw[end - 1] in "*`_" and not old.rstrip().endswith(raw[end - 1]):
        end -= 1
    return m.start(), end


def _is_row(s: str) -> bool:
    t = s.strip()
    return t.startswith("|") and t.endswith("|") and t.count("|") >= 2


def _fences(lines: list[str]) -> list[bool]:
    inside, out = False, []
    for s in lines:
        if s.strip().startswith("```"):
            out.append(True)
            inside = not inside
            continue
        out.append(inside)
    return out


def _balance_markup(line: str) -> str:
    """После замены внутри разметки убрать непарные ``**`` и обратные кавычки."""
    if line.strip().startswith("```"):
        return line
    if line.count("**") % 2:
        line = line.replace("**", "")
    if line.count("`") % 2:
        line = line.replace("`", "")
    return line


def _blank(line: str) -> bool:
    """Строка пуста или осталась одна разметка (``****``, ``* ``, ``|  |``)."""
    return not re.sub(r"[\s*`_|#>-]", "", line)


_LIST = re.compile(r"^(\s*(?:[*+-]|\d+[.)])\s+)")


def _shape_insert(new: str, anchor: str) -> str:
    """Новая строка в стиле соседней: строка таблицы с ``|``, тот же маркер списка."""
    t = new.strip()
    if _is_row(anchor):
        if not _is_row(t) and " | " in t:
            t = "| " + t.strip("| ") + " |"
        return t
    if t.startswith(("|", "#", ">")) or _LIST.match(t):
        return t
    m = _LIST.match(anchor)
    if m and not re.match(r"^\s*\d", m.group(1)):
        return m.group(1).lstrip() + t
    return t


_SEP_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")


def _is_sep(row: str) -> bool:
    cells = [c for c in row.strip().strip("|").split("|")]
    return bool(cells) and all(_SEP_CELL.match(c) for c in cells)


def _is_json(line: str) -> bool:
    t = line.strip()
    if not (t[:1] in "{[" and t[-1:] in "}]"):
        return False
    try:
        json.loads(t)
        return True
    except ValueError:
        return False


def _shape_block(rows: list[str], anchor: str) -> list[tuple[str, str]]:
    """Вставляемые строки → разметка документа: строки с « | » — таблица (с разделителем, если она новая),
    строки-JSON — блок кода, остальное — в стиле соседней строки. Возвращает ``[(строка, вид)]``,
    вид: ``mark`` — с пометкой, ``raw`` — как есть (разделитель таблицы, граница блока кода), ``note`` — пометка."""
    out: list[tuple[str, str]] = []
    i = 0
    in_table = _is_row(anchor)
    while i < len(rows):
        t = rows[i].strip()
        if _is_json(t):
            j = i
            while j < len(rows) and _is_json(rows[j]):
                j += 1
            out += [("```json", "raw")] + [(r.strip(), "raw") for r in rows[i:j]] + [("```", "raw"), ("", "note")]
            i = j
            continue
        if " | " in t or _is_row(t):
            j = i
            while j < len(rows) and (" | " in rows[j] or _is_row(rows[j].strip())):
                j += 1
            block = ["| " + r.strip().strip("|").strip() + " |" for r in rows[i:j]]
            if in_table or j - i == 1 and _is_row(anchor):
                out += [(b, "raw" if _is_sep(b) else "mark") for b in block]
            elif j - i >= 2:
                ncols = block[0].count("|") - 1
                if not _is_sep(block[1]):
                    block.insert(1, "| " + " | ".join([":---"] * ncols) + " |")
                if out and out[-1][0].strip():
                    out.append(("", "raw"))  # таблице нужна пустая строка перед ней
                out += [(b, "raw" if _is_sep(b) else "mark") for b in block]
            else:
                out.append((t, "mark"))
            i = j
            continue
        out.append((_shape_insert(t, anchor), "mark"))
        i += 1
    return out


def _with_mark(text: str, mark: str) -> str:
    m_new = _MARK.match(" " + mark)
    found = list(_MARK.finditer(text))
    if found and m_new:  # строка уже помечена (второй проход): добавленную строку не помечаем повторно
        kinds = {f.group(1) for f in found}
        if "добавлено" in kinds or m_new.group(1) in kinds:
            f = next((f for f in found if f.group(1) == m_new.group(1)), None)
            if f is None:
                return text
            ids = [x.strip() for x in f.group(2).split(",")]
            extra = [x.strip() for x in m_new.group(2).split(",") if x.strip() not in ids]
            if not extra:
                return text
            merged = f" [{f.group(1)}: {', '.join(ids + extra)}]"
            return text[:f.start()] + merged + text[f.end():]
    if _is_row(text):
        t = text.rstrip()
        return t[:-1].rstrip() + f" {mark} |"
    return text.rstrip() + f" {mark}"


# --------------------------------------------------------------------------- применение правок
def apply_edits(lines: list[str], rewrites: list[dict], warnings: list[str] | None = None) -> dict:
    """Применяет правки к строкам документа. Возвращает ``{"markdown", "rewrites", "stats"}``."""
    warnings = warnings if warnings is not None else []
    n = len(lines)
    text = list(lines)
    changed: dict[int, list[str]] = {}
    inserts: dict[int, list[tuple[str, str]]] = {}
    fence = _fences(lines)
    used_spans: dict[int, list[tuple[int, int]]] = {}
    out_rewrites: list[dict] = []
    stats = {"replaced": 0, "inserted": 0, "not_applied": 0, "pending": 0}

    def locate(line_no: int, old: str) -> tuple[int, tuple[int, int]] | None:
        order = [line_no - 1] + [line_no - 1 + d for k in range(1, 3) for d in (-k, k)]
        order += sorted(range(n), key=lambda i: abs(i - (line_no - 1)))
        seen: set[int] = set()
        for i in order:
            if i in seen or not 0 <= i < n:
                continue
            seen.add(i)
            span = find_span(text[i], old)
            if span:
                return i, span
        return None

    for rw in rewrites:
        fid = rw["finding_id"]
        rec_edits = []
        for e in rw.get("edits") or []:
            action, line_no = e.get("action"), int(e.get("line") or 0)
            old, new = str(e.get("old") or ""), str(e.get("new") or "").strip("\n")
            rec = {"action": action, "line": line_no, "was": old, "became": new, "applied": False}
            if action == "replace":
                hit = locate(line_no, old) if old.strip() else None
                if hit is None:
                    stats["not_applied"] += 1
                    warnings.append(f"revise: {fid}: фрагмент «{old[:60]}» не найден — правка не применена")
                    rec_edits.append(rec)
                    continue
                i, (a, b) = hit
                if any(not (b <= x or a >= y) for x, y in used_spans.get(i, [])):
                    stats["not_applied"] += 1
                    warnings.append(f"revise: {fid}: фрагмент строки {i + 1} уже изменён другой правкой")
                    rec_edits.append(rec)
                    continue
                was = text[i][a:b]
                new_line = text[i][:a] + new + text[i][b:]
                new_line = _balance_markup(new_line)
                delta = len(new) - (b - a)
                used_spans[i] = [(x if x < a else x + delta, y if y <= a else y + delta) for x, y in used_spans.get(i, [])]
                used_spans[i].append((a, a + len(new)))
                text[i] = new_line
                changed.setdefault(i, [])
                if fid not in changed[i]:
                    changed[i].append(fid)
                rec.update(applied=True, line=i + 1, was=was)
                stats["replaced"] += 1
            elif action == "insert_after":
                if not new.strip() or not 1 <= line_no <= n:
                    stats["not_applied"] += 1
                    warnings.append(f"revise: {fid}: вставка после строки {line_no} вне документа — не применена")
                    rec_edits.append(rec)
                    continue
                anchor = line_no - 1
                new_rows = [s for s in new.splitlines() if s.strip()]
                if fence[anchor]:  # внутри блока кода — после его конца
                    while anchor + 1 < n and fence[anchor + 1]:
                        anchor += 1
                elif _is_row(lines[anchor]) and not all(_is_row(s) for s in new_rows):
                    while anchor + 1 < n and _is_row(lines[anchor + 1]):
                        anchor += 1
                elif not _is_row(lines[anchor]) and anchor + 1 < n and _is_row(lines[anchor + 1]) \
                        and all(_is_row(s) for s in new_rows):
                    anchor += 1  # строки таблицы после заголовка раздела — в конец таблицы
                    while anchor + 1 < n and _is_row(lines[anchor + 1]):
                        anchor += 1
                for text_, kind in _shape_block(new_rows, lines[anchor]):
                    inserts.setdefault(anchor, []).append((text_, fid, kind))
                rec.update(applied=True, line=anchor + 1, was="")
                stats["inserted"] += len(new_rows)
            else:
                stats["not_applied"] += 1
                rec_edits.append(rec)
                continue
            stats["pending"] += len(_PENDING.findall(new))
            rec_edits.append(rec)
        out_rewrites.append({**{k: v for k, v in rw.items() if k != "edits"}, "edits": rec_edits})

    deleted = {i for i in changed if _blank(text[i]) and not _blank(lines[i])}
    # блоки кода, у которых удалено всё содержимое, убираются целиком
    drop: set[int] = set()
    i = 0
    while i < n:
        if text[i].strip().startswith("```"):
            j = i + 1
            while j < n and not text[j].strip().startswith("```"):
                j += 1
            body = [k for k in range(i + 1, min(j, n)) if not _blank(lines[k])]
            if body and all(k in deleted for k in body):
                drop.update(range(i, min(j, n - 1) + 1))
            i = j + 1
        else:
            i += 1
    out: list[str] = []
    inside = False
    fence_marks: list[str] = []
    for i, s in enumerate(text):
        fids = changed.get(i, [])
        is_fence = s.strip().startswith("```")
        if i in drop:
            if i in deleted:
                fence_marks += [f for f in fids if f not in fence_marks]
            if is_fence and inside and fence_marks:
                out.append(f"[удалено: {', '.join(fence_marks)} — пример]")
                fence_marks = []
            if is_fence:
                inside = not inside
        elif is_fence:
            out.append(s)
            if inside and fence_marks:  # закрывающая граница блока кода — пометка отдельной строкой
                out.append(f"[изменено: {', '.join(fence_marks)} — пример выше]")
                fence_marks = []
            inside = not inside
        elif fids and inside:
            if i not in deleted:
                out.append(s)
            fence_marks += [f for f in fids if f not in fence_marks]
        elif i in deleted:
            out.append(f"[удалено: {', '.join(fids)}]")
        elif fids:
            out.append(_with_mark(s, f"[изменено: {', '.join(fids)}]"))
        else:
            out.append(s)
        for row, fid, kind in inserts.get(i, []):
            if kind == "mark":
                out.append(_with_mark(row, f"[добавлено: {fid}]"))
            elif kind == "note":
                out.append(f"[добавлено: {fid} — пример выше]")
            else:
                out.append(row)
    return {"markdown": "\n".join(out) + "\n", "rewrites": out_rewrites, "stats": stats}


def _header(title: str, answered: bool, stats: dict) -> list[str]:
    note = ("Значения выбраны по ответам владельца." if answered else
            "Ответов владельца нет: значения, которые выбирает бизнес, оставлены маркером <уточнить: …>.")
    return [f"> Исправленная редакция документа «{title}», подготовлена агентом ревью. "
            f"Пометки: [изменено: D-…] — формулировка заменена, [добавлено: D-…] — новое требование или критерий "
            f"приёмки. {note} Заменено фрагментов: {stats['replaced']}, добавлено строк: {stats['inserted']}.", ""]


def _answers_block(answers: Any) -> tuple[str, dict[str, list[str]]]:
    """Ответы из режима ``--answers`` (``clarification`` или результат ``recheck.resolve_answers``)."""
    if not answers:
        return "—", {}
    answered = answers.get("answers") if "answers" in answers and "changes" in answers else answers.get("answered")
    answered = answered or []
    decisions = answers.get("decisions") or []
    rows, by_finding = [], {}
    # несколько реплик на вопрос — согласованное правило, только если пересмотр снял по ним дефект без конфликта
    agreed = {c.get("finding_id") for c in answers.get("changes") or []
              if c.get("status") in ("resolved", "changed") and not c.get("answer_conflict")}
    # стороны конфликта, который признал пересмотр («Q-01» против «Решение-1»): ни одна не согласованное правило
    against: dict[str, set[str]] = {}
    for c in answers.get("answer_conflicts") or []:
        sides = {str(x) for x in c.get("answers") or []}
        for x in sides:
            against.setdefault(x, set()).update(sides - {x})
            against.setdefault(x.split(".")[0], set()).update(y for y in sides if y.split(".")[0] != x.split(".")[0])
    for a in answered:
        fids = a.get("finding_ids", [])
        replies = a.get("replies") or []
        head = f"{a.get('question_id')} ({a.get('topic', '')}) → {', '.join(fids)}: "
        rivals = sorted(against.get(str(a.get("question_id")), set()))
        if rivals and len(replies) <= 1:
            rows.append(head + f"ответ спорит с {', '.join(rivals)}, владелец не выбрал одно правило — значение не "
                               f"вписывай ни по ответу, ни по {', '.join(rivals)}; поставь маркер <уточнить: …> с обоими "
                               f"вариантами: {a.get('answer', '')}")
            continue
        if len(replies) > 1 and not agreed & set(fids):
            # ответы адресатов расходятся: правило не согласовано, значение не выбирать — маркер <уточнить: …>
            rows.append(head + "ответы расходятся, владелец не выбрал одно правило — значение не вписывай, "
                               "поставь маркер <уточнить: …> с обоими вариантами: "
                        + " / ".join(r.get("text", "") for r in replies))
        else:
            rows.append(head + f"{a.get('answer', '')}")
        for part in a.get("deferred") or []:
            rows.append(f"  не решено владельцем (не вписывай как правило, поставь маркер <уточнить: …>): {part}")
        if len(replies) > 1 and not agreed & set(fids):
            continue  # несогласованные реплики — не источник значения правки
        for fid in a.get("finding_ids", []):
            by_finding.setdefault(fid, []).append(a.get("question_id"))
    for i, d in enumerate(decisions, 1):
        rivals = sorted(against.get(f"Решение-{i}", set()))
        if rivals:
            rows.append(f"Общее решение владельца Решение-{i} спорит с {', '.join(rivals)} — не согласованное правило: "
                        f"не вписывай его значение, поставь маркер <уточнить: …> с обоими вариантами: {d}")
        else:
            rows.append(f"Общее решение владельца: {d}")
    return ("\n".join(rows) or "—"), by_finding


def decision_targets(answers: Any) -> list[dict]:
    """Общие решения владельца (раздел «Решения», без номера вопроса) — отдельные цели правки.

    Редакция правит дефекты; решение, которое не сняло ни один дефект (новое правило, срок, поле), иначе в
    текст не попадает, хотя владелец его принял. Решение, на которое пересмотр уже сослался при снятии дефекта
    (``answer_ids`` = «Решение-N»), вносится правкой этого дефекта и отдельной целью не становится.
    """
    if not answers:
        return []
    used = {str(x) for c in answers.get("changes") or [] for x in c.get("answer_ids") or []}
    # решение, которое спорит с другим ответом, — не согласованное правило: в текст его не вписываем
    used |= {str(x) for c in answers.get("answer_conflicts") or [] for x in c.get("answers") or []}
    out = []
    for i, d in enumerate(answers.get("decisions") or [], 1):
        text, did = str(d or "").strip(), f"Решение-{i}"
        if not text or did in used:
            continue
        out.append({"id": did, "severity": "major", "blocks": "none", "kind": "owner_decision",
                    "title": "Решение владельца, которого ещё нет в документе",
                    "problem": f"Владелец принял решение: «{text}». В документе этого правила нет.",
                    "recommendation": "Внеси решение в документ с его точными значениями: новое требование в "
                                      "подходящем разделе (insert_after) или правка требования, которое решение "
                                      "меняет; если у раздела есть критерии приёмки — добавь критерий.",
                    "evidence": []})
    return out


def unsettled_findings(answers: Any) -> set[str]:
    """Дефекты, по которым ответы владельца расходятся: правка по ним без маркера <уточнить> — выдуманный выбор."""
    if not answers:
        return set()
    answered = answers.get("answers") if "answers" in answers and "changes" in answers else answers.get("answered")
    agreed = {c.get("finding_id") for c in answers.get("changes") or []
              if c.get("status") in ("resolved", "changed") and not c.get("answer_conflict")}
    out = {c.get("finding_id") for c in answers.get("answer_conflicts") or [] if c.get("finding_id")}
    for a in answered or []:
        if len(a.get("replies") or []) > 1:
            out |= set(a.get("finding_ids") or []) - agreed
    return out


def drop_unsettled(rewrites: list[dict], unsettled: set[str], warnings: list[str]) -> list[dict]:
    """Правка дефекта с расходящимися ответами остаётся, только если оставляет решение владельцу (маркер)."""
    out = []
    for r in rewrites:
        if r["finding_id"] in unsettled and not any(_PENDING.search(str(e.get("new") or "")) for e in r["edits"]):
            warnings.append(f"revise: {r['finding_id']} — ответы владельца расходятся, а правка выбрала значение "
                            f"без маркера <уточнить>; правка не внесена, текст оставлен как был")
            continue
        out.append(r)
    return out


# --------------------------------------------------------------------------- этап
def run(ctx: Any, findings: list[dict], answers: Any = None) -> dict:
    """``{"rewrites": [...], "revised_markdown": str, "stats": {...}}`` по critical и major."""
    view = ctx.view
    targets = sorted((f for f in findings if f.get("severity") in ("critical", "major")),
                     key=lambda f: (_SEV.get(f.get("severity"), 2), int(f.get("priority") or 0) or 99))
    title = (view.get("title") if isinstance(view, dict) else getattr(view, "title", "")) or "документ"
    lines, _raw = _source_lines(ctx, view)
    n_findings = len(targets)
    owner = decision_targets(answers)  # общие решения владельца без вопроса — тоже правка документа
    targets = targets + owner
    if not targets:
        return {"rewrites": [], "revised_markdown": "", "stats": {"replaced": 0, "inserted": 0, "not_applied": 0,
                                                                  "pending": 0}}
    ans_text, by_finding = _answers_block(answers)
    for t in owner:
        by_finding[t["id"]] = [t["id"]]

    def build(items: list) -> tuple[str, str]:
        block = _cl.format_findings(items)
        system, user = ctx.prompt(STAGE, findings=block, answers=ans_text)
        if block[:200] not in user:
            extra = f"<дефекты>\n{block}\n</дефекты>\n\n<ответы>\n{ans_text}\n</ответы>"
            idx = user.find("Задание: исправленная редакция")
            user = (user[:idx] + extra + "\n\n" + user[idx:]) if idx >= 0 else (user + "\n\n" + extra)
        return system, user

    warnings: list[str] = []
    try:
        raw = _cl.ask_items(ctx, STAGE, targets, build, SCHEMA, max_output_tokens=32000)
    except Exception as exc:  # noqa: BLE001
        _cl._warn(ctx, f"revise: модель не ответила ({type(exc).__name__}: {str(exc)[:200]}); редакция не построена")
        return {"rewrites": [], "revised_markdown": "", "stats": {}, "status": "failed"}
    by_id = {f["id"]: f for f in targets}
    rewrites = []
    for rw in raw.get("rewrites") or []:
        fid = str(rw.get("finding_id", "")).strip()
        if fid not in by_id:
            continue
        f = by_id[fid]
        rewrites.append({"finding_id": fid, "title": f.get("title", ""), "severity": f.get("severity", ""),
                         "summary": str(rw.get("summary", "")).strip(), "edits": rw.get("edits") or [],
                         "answer_ids": by_finding.get(fid, [])})
    order = {f["id"]: i for i, f in enumerate(targets)}
    rewrites.sort(key=lambda r: order.get(r["finding_id"], 999))
    rewrites = drop_unsettled(rewrites, unsettled_findings(answers), warnings)
    applied = apply_edits(lines, rewrites, warnings)
    opts = getattr(ctx, "options", None) or {}
    check = {"fixes": [], "stats": {}}
    if isinstance(opts, dict) and opts.get("revise_check", True) and applied["stats"].get("replaced", 0) + \
            applied["stats"].get("inserted", 0):
        check = _check_pass(ctx, applied, warnings)
        if check.get("markdown"):
            applied["markdown"] = check["markdown"]
    for r in applied["rewrites"]:
        r["pending"] = sum(len(_PENDING.findall(e.get("became", ""))) for e in r["edits"])
    body = applied["markdown"].splitlines()
    head = _header(title, bool(by_finding), applied["stats"])  # решения владельца — тоже «по ответам»
    # пометка-шапка после заголовка документа (первая строка «# …»), иначе в начале
    if body and body[0].lstrip().startswith("#"):
        md = "\n".join([body[0], ""] + head + body[1:]) + "\n"
    else:
        md = "\n".join(head + body) + "\n"
    for w in warnings:
        _cl._warn(ctx, w)
    missing = [f["id"] for f in targets if f["id"] not in {r["finding_id"] for r in rewrites}]
    return {"rewrites": applied["rewrites"], "revised_markdown": md, "check_fixes": check.get("fixes", []),
            "stats": {**applied["stats"], "findings": n_findings, "decisions": len(owner),
                      "with_rewrite": len(rewrites),
                      "without_rewrite": missing, "check_fixes": len(check.get("fixes", [])),
                      "check_edits": check.get("stats", {}).get("replaced", 0) + check.get("stats", {}).get("inserted", 0)}}


def _changed_lines(md_lines: list[str]) -> list[str]:
    rows = []
    for i, s in enumerate(md_lines, 1):
        for m in _MARK.finditer(s):
            rows.append(f"L{i:03d} | {m.group(1)}: {m.group(2)}")
    return rows


def _number_markdown(ctx: Any, md: str) -> str:
    """Нумерованный текст редакции так же, как модель видит исходный документ."""
    try:
        from bcc_review.v2 import docview  # type: ignore
        view = docview.from_text(md, file="revised.md", fmt="md")
        return docview.numbered(view)
    except Exception:  # noqa: BLE001 — запасная нумерация без разметки
        out = []
        for i, s in enumerate(md.splitlines(), 1):
            t = re.sub(r"\*\*|__|`", "", s).rstrip()
            out.append(f"L{i:03d}| {t}")
        return "\n".join(out)


def _check_pass(ctx: Any, applied: dict, warnings: list[str]) -> dict:
    """Второй проход: противоречия, которые внесли сами правки, и их исправление (1 вызов модели)."""
    md = applied["markdown"]
    md_lines = md.splitlines()
    changes = _changed_lines(md_lines)
    if not changes:
        return {"fixes": []}
    by_fid = {r["finding_id"]: r for r in applied["rewrites"]}
    summary = "\n".join(f"{fid}: {r.get('title', '')} — {r.get('summary', '')}" for fid, r in by_fid.items())
    block = "\n".join(changes) + "\n\nДефекты:\n" + summary
    try:
        from bcc_review.v2 import prompts as _p  # type: ignore
        own, task = _p.task(CHECK_STAGE, changes=block)
        system = own or _p.system()
    except Exception:  # noqa: BLE001
        system, user0 = ctx.prompt(CHECK_STAGE, changes=block)
        task = user0[user0.find("<правки>"):] if "<правки>" in user0 else user0
    user = f"<документ>\n{_number_markdown(ctx, md)}\n</документ>\n\n{task}"
    try:
        raw = ctx.llm.ask(CHECK_STAGE, system, user, CHECK_SCHEMA, max_output_tokens=24000) or {}
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"revise: самопроверка редакции не выполнена ({type(exc).__name__}: {str(exc)[:160]})")
        return {"fixes": []}
    fixes = [f for f in raw.get("fixes") or [] if f.get("edits")]
    for f in fixes:
        if f.get("finding_id") not in by_fid:
            f["finding_id"] = next(iter(by_fid), "D-00")
    if not fixes:
        return {"fixes": [], "stats": {}}
    res = apply_edits(md_lines, [{"finding_id": f["finding_id"], "summary": f.get("problem", ""),
                                  "edits": f["edits"]} for f in fixes], warnings)
    out_fixes = [{"finding_id": r["finding_id"], "problem": r.get("summary", ""), "edits": r["edits"]}
                 for r in res["rewrites"]]
    return {"fixes": out_fixes, "stats": res["stats"], "markdown": res["markdown"]}


def flat_rewrites(result: dict) -> list[dict]:
    """Применённые правки плоским списком для ``report.json`` и таблицы «было → стало» отчёта (№13):
    ``{finding_id, title, severity, summary, action, line_start, line_end, before, after, answer_ids}``."""
    out = []
    for r in result.get("rewrites") or []:
        for e in r.get("edits") or []:
            if not e.get("applied"):
                continue
            out.append({"finding_id": r.get("finding_id", ""), "title": r.get("title", ""),
                        "severity": r.get("severity", ""), "summary": r.get("summary", ""),
                        "action": e.get("action", ""), "line_start": e.get("line"), "line_end": e.get("line"),
                        "before": e.get("was", "") if e.get("action") == "replace" else "",
                        "after": e.get("became", "") or ("фрагмент удалён" if e.get("action") == "replace" else ""),
                        "answer_ids": list(r.get("answer_ids") or [])})
    return out


def revised_path(report_path: str | Path) -> Path:
    """``reports/requirements.md`` → ``reports/requirements.revised.md``."""
    p = Path(report_path)
    stem = p.name[:-len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{stem}.revised.md")


def write(report_path: str | Path, result: dict) -> Path | None:
    """Пишет исправленную редакцию рядом с отчётом; возвращает путь или ``None``, если редакции нет."""
    md = result.get("revised_markdown") or ""
    if not md.strip():
        return None
    out = revised_path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out


_S = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}


def render_markdown(result: dict, revised_file: str = "") -> str:
    """Раздел отчёта «Было → стало» (№13 может вставить как есть или нарисовать сам)."""
    rws = [r for r in result.get("rewrites") or [] if any(e.get("applied") for e in r.get("edits", []))]
    if not rws:
        return ""
    st = result.get("stats") or {}
    out = ["## Исправленная редакция: было → стало", "",
           f"Правки по {len(rws)} дефектам: заменено фрагментов {st.get('replaced', 0)}, добавлено строк "
           f"{st.get('inserted', 0)}, осталось решений владельца (<уточнить>) {st.get('pending', 0)}."
           + (f" Полный текст: `{revised_file}`." if revised_file else ""), ""]
    for r in rws:
        out.append(f"### {r['finding_id']} ({_S.get(r.get('severity', ''), '')}) {r.get('title', '')}")
        if r.get("summary"):
            out.append(r["summary"])
        out.append("")
        for e in r["edits"]:
            if not e.get("applied"):
                continue
            if e["action"] == "replace":
                out.append(f"* строка {e['line']}, было: «{e['was']}»")
                out.append(f"  стало: «{e['became']}»" if e["became"] else "  стало: фрагмент удалён")
            else:
                out.append(f"* после строки {e['line']} добавлено: «{e['became'].strip()}»")
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- точка входа для pipeline (№01)
def run_modes(ctx: Any, report: dict, *, answers: Any = None, do_revise: bool = False,
              report_path: str | Path | None = None) -> dict:
    """Режимы ``--answers`` и ``--revise`` одним вызовом после судьи и clarify.

    ``report`` — собранный отчёт (``findings``, ``questions``, ``verdict``, ``run.status``).
    Возвращает поля для ``report.json``: ``clarification``, ``findings_after``, ``rejected_after`` (при ответах),
    ``rewrites``, ``revise_stats``, ``revised_file`` (при ``do_revise``) и ``markdown_sections`` — готовые разделы
    «Уточнение: до и после» и «Исправленная редакция: было → стало» для отчёта (№13 может нарисовать свои).
    """
    from bcc_review.v2.stages import recheck  # локально: recheck импортирует clarify, revise — тоже

    out: dict = {"markdown_sections": []}
    clar = None
    if answers:
        a = recheck.apply_answers(ctx, report, answers)
        clar = a["clarification"]
        out.update(clarification=clar, findings_after=a["findings_after"], rejected_after=a["rejected_after"])
        out["markdown_sections"].append(recheck.render_markdown(clar, a["findings_after"]))
    if do_revise:
        try:
            r = run(ctx, list(report.get("findings") or []), clar)
        except Exception as exc:  # noqa: BLE001 — сбой редакции не должен стирать уже готовый пересмотр по ответам
            if not answers:
                raise
            msg = f"revise: редакция не построена ({type(exc).__name__}: {str(exc)[:200]}); пересмотр по ответам сохранён"
            _cl._warn(ctx, msg)
            out["revise_stats"] = {"status": "failed", "error": msg}
            return out
        path = write(report_path, r) if report_path else None
        out.update(rewrites=flat_rewrites(r), revise_stats=r.get("stats", {}),
                   revised_file=str(path) if path else "", revised_markdown=r.get("revised_markdown", ""))
        section = render_markdown(r, path.name if path else "")
        if section:
            out["markdown_sections"].append(section)
    return out
