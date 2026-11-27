"""Этап revise (№11): «было → стало» по critical и major и исправленная редакция документа.

Модель предлагает правки (замена фрагмента строки или вставка после строки), код их применяет к исходному
тексту и помечает: ``[изменено: D-02]`` у заменённой строки, ``[добавлено: D-05]`` у новой. Если на вопрос
по дефекту есть ответ владельца (режим ``--answers``), подставляется он; иначе значение, которое должен
выбрать бизнес, остаётся маркером ``<уточнить: …>``.

Правка, фрагмент которой не найден в документе, не применяется (в ``rewrites`` у неё ``applied: false``) —
исправленная редакция никогда не содержит текста, который модель «вспомнила» неточно.

Правки не портят другие требования (№11-Б, ``Guard``): вид правки задаёт вид дефекта (``defect_class``) —
недостающий элемент только добавляется, а не подменяет существующую строку; замена строки, которую цитирует
другой дефект или другое требование и которой нет среди мест этого дефекта, не применяется (кроме точечной
правки значения или термина). Причина отказа — в ``reason`` правки.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from bcc_review.v2.stages import clarify as _cl

STAGE = "revise"
_SEV = {"critical": 0, "major": 1, "minor": 2}
_PENDING = re.compile(r"<\s*уточнить\s*:[^>]*>", re.I)

# --------------------------------------------------------------------------- вид дефекта → вид правки (№11-Б)
MISSING_KINDS = {"missing_element"}
CONFLICT_KINDS = {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction"}
AMBIGUITY_KINDS = {"ambiguity", "terminology", "unverifiable", "non_singular", "placeholder"}
CLASS_HINT = {
    "missing": "не хватает элемента → только insert_after рядом с однотипными элементами; существующие строки "
               "не заменять",
    "conflict": "противоречие → replace одной стороны: по решению владельца, без решения — маркер <уточнить: …>",
    "ambiguity": "неоднозначность → replace на месте: точная формулировка вместо расплывчатой",
}


def defect_class(f: dict) -> str:
    """``missing`` (нет операции, поля, шага, сценария), ``conflict``, ``ambiguity`` или ``other``."""
    kind, crit = f.get("kind") or "", f.get("criterion") or ""
    if kind in MISSING_KINDS or (kind in ("incomplete", "api_contract") and crit == "set_complete"):
        return "missing"
    if kind in CONFLICT_KINDS or (kind == "api_contract" and crit == "set_consistent"):
        return "conflict"
    if kind in AMBIGUITY_KINDS:
        return "ambiguity"
    return "other"


def _span(e: dict) -> range:
    a = int(e.get("line_start") or e.get("line") or 0)
    b = int(e.get("line_end") or a)
    return range(a, max(a, b) + 1) if a > 0 else range(0)


def _stems(s: str) -> set[str]:
    """Слова фрагмента без окончаний (первые 5 букв): «отправка» и «отправки» — одно слово."""
    return {w[:5] for w in re.findall(r"\w+", _cnorm(s)) if len(w) > 1 or w.isdigit()}


def _visible(s: str) -> str:
    return re.sub(r"[\s*`_|#>:.,;-]+", "", s)


def _numbers(s: str) -> set[str]:
    """Числа фрагмента без разделителей разрядов: «4 000» → «4000»."""
    return {re.sub(r"\s", "", m) for m in re.findall(r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?", s or "")}


def substitutes(old: str, new: str) -> bool:
    """Замена выбрасывает исходный фрагмент и ставит на его место другой текст — а не правит в нём значение,
    не дополняет и не сокращает его."""
    o, n = _stems(old), _stems(new)
    if not o or not n:
        return False
    if len(o & n) / len(o) >= 0.6:  # исходное сохранено, текст дополнен или поправлен
        return False
    if len(o & n) / len(n) >= 0.9:  # новое — часть старого: фрагмент сокращён
        return False
    return difflib.SequenceMatcher(None, _cnorm(old), _cnorm(new)).ratio() < 0.6


def is_spot(old: str, line: str) -> bool:
    """Точечная правка: меняется значение или термин (не больше половины видимого текста строки)."""
    lo, ll = len(_visible(old)), len(_visible(line))
    return ll > 0 and lo <= 0.5 * ll


class Guard:
    """Страховка кодом: правка не портит требование, к которому дефект не относится.

    Места дефекта — строки его цитат и строки его требований (``requirement_ids``). Чужая строка — та, что
    цитирует другой дефект (любой серьёзности) или другое требование, и её нет среди мест дефекта.
    """

    def __init__(self, findings: list[dict], requirements: list[dict] | None = None):
        self.by_id = {f.get("id"): f for f in findings if f.get("id")}
        self.cited: dict[int, set[str]] = {}
        for f in findings:
            for e in f.get("evidence") or []:
                for ln in _span(e):
                    self.cited.setdefault(ln, set()).add(f.get("id"))
        self.req_lines: dict[str, set[int]] = {}
        self.line_reqs: dict[int, set[str]] = {}
        for r in requirements or []:
            rid = r.get("id")
            if not rid:
                continue
            lines = set(_span(r))
            self.req_lines[rid] = lines
            for ln in lines:
                self.line_reqs.setdefault(ln, set()).add(rid)

    def places(self, fid: str) -> set[int]:
        f = self.by_id.get(fid) or {}
        out = {ln for e in f.get("evidence") or [] for ln in _span(e)}
        for rid in f.get("requirement_ids") or []:
            out |= self.req_lines.get(rid, set())
        return out

    def owners(self, fid: str, line: int) -> list[str]:
        """Чьи это строка: другие дефекты и требования, которые её цитируют (пусто — строка не чужая)."""
        if line in self.places(fid):
            return []
        f = self.by_id.get(fid) or {}
        others = sorted(self.cited.get(line, set()) - {fid})
        others += sorted(self.line_reqs.get(line, set()) - set(f.get("requirement_ids") or []))
        return others

    owner_numbers: frozenset = frozenset()  # числа из ответов владельца: второй проход их не убирает

    def check(self, fid: str, line: int | None, old: str, new: str, line_text: str) -> str:
        """Причина не применять замену (пусто — применять). ``line`` — номер строки исходника (1…) или ``None``
        для строки, добавленной правкой."""
        lost = (_numbers(old) - _numbers(new)) & self.owner_numbers
        if lost:
            return (f"значение {', '.join(sorted(lost))} взято из ответа владельца — самопроверка его не меняет")
        if line is None:
            return ""
        f = self.by_id.get(fid)
        if f is None:
            return ""
        frag = old.strip()[:60]
        if defect_class(f) == "missing":
            if not new.strip():
                return (f"не хватает элемента: строка {line} не удаляется — недостающее добавляется вставкой "
                        f"(insert_after)")
            if substitutes(old, new):
                return (f"не хватает элемента: замена подменила бы «{frag}» в строке {line} описанием нового "
                        f"элемента — нужна вставка (insert_after) рядом с однотипными элементами")
            foreign_reqs = self.line_reqs.get(line, set()) - set(f.get("requirement_ids") or [])
            added = _stems(new) - _stems(old)
            if foreign_reqs and not (self.line_reqs.get(line, set()) & set(f.get("requirement_ids") or [])) \
                    and len(added) > 8:
                return (f"не хватает элемента: новый элемент вписан в строку {line} требования "
                        f"{', '.join(sorted(foreign_reqs))} — нужна вставка отдельной строкой (insert_after)")
        owners = self.owners(fid, line)
        if owners and not is_spot(old, line_text):
            return (f"строка {line} относится к {', '.join(owners[:4])} и не входит в места {fid}: заменять её "
                    f"целиком нельзя, допустима только точечная правка значения или термина")
        return ""

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
            from bcc_review.v2.docview import _decode_text  # та же кодировка, что у view (UTF-16, cp1251)
            raw = _decode_text(p.read_bytes()).splitlines()
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
_HEADING = re.compile(r"^(#{1,6})\s")


def _section_end(lines: list[str], fence: list[bool], anchor: int, level: int) -> int:
    """Последняя непустая строка раздела, в котором стоит ``anchor``: до следующего заголовка уровня ≤ ``level``.
    Новый раздел, вставленный посреди существующего, отрезал бы от него хвост — поэтому он идёт после."""
    j = anchor + 1
    while j < len(lines):
        m = _HEADING.match(lines[j].strip())
        if m and not fence[j] and len(m.group(1)) <= level:
            break
        j += 1
    end = j - 1
    while end > anchor and not lines[end].strip():
        end -= 1
    return end


def apply_edits(lines: list[str], rewrites: list[dict], warnings: list[str] | None = None,
                guard: Guard | None = None, origin: list[int | None] | None = None) -> dict:
    """Применяет правки к строкам документа. Возвращает ``{"markdown", "rewrites", "stats", "origin"}``.

    ``guard`` — страховка от порчи других требований (``Guard.check``); ``origin`` — номер строки исходника
    для каждой строки ``lines`` (``None`` — строка добавлена правкой), когда правки идут по редакции, а не по
    исходнику. В ответе ``origin`` — то же для строк новой редакции."""
    warnings = warnings if warnings is not None else []
    n = len(lines)
    text = list(lines)
    changed: dict[int, list[str]] = {}
    inserts: dict[int, list[tuple[str, str]]] = {}
    fence = _fences(lines)
    used_spans: dict[int, list[tuple[int, int]]] = {}
    out_rewrites: list[dict] = []
    stats = {"replaced": 0, "inserted": 0, "not_applied": 0, "pending": 0, "rejected": 0}
    src_line = (lambda i: origin[i] if origin is not None and i < len(origin) else
                (i + 1 if origin is None else None))

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
                    rec["reason"] = "фрагмент не найден в документе"
                    warnings.append(f"revise: {fid}: фрагмент «{old[:60]}» не найден — правка не применена")
                    rec_edits.append(rec)
                    continue
                i, (a, b) = hit
                if any(not (b <= x or a >= y) for x, y in used_spans.get(i, [])):
                    stats["not_applied"] += 1
                    rec["reason"] = f"фрагмент строки {i + 1} уже изменён другой правкой"
                    warnings.append(f"revise: {fid}: фрагмент строки {i + 1} уже изменён другой правкой")
                    rec_edits.append(rec)
                    continue
                why = guard.check(fid, src_line(i), text[i][a:b], new, lines[i]) if guard is not None else ""
                if why:
                    stats["not_applied"] += 1
                    stats["rejected"] += 1
                    rec.update(line=i + 1, was=text[i][a:b], reason=why, rejected=True)
                    if origin is not None:
                        rec["src_line"] = src_line(i)
                    warnings.append(f"revise: {fid}: правка не применена — {why}")
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
                if origin is not None:  # правка по редакции: номер строки исходника (None — строка добавлена)
                    rec["src_line"] = src_line(i)
                stats["replaced"] += 1
            elif action == "insert_after":
                if not new.strip() or not 1 <= line_no <= n:
                    stats["not_applied"] += 1
                    rec["reason"] = "пустой текст вставки" if not new.strip() else f"строки {line_no} нет в документе"
                    warnings.append(f"revise: {fid}: вставка после строки {line_no} вне документа — не применена")
                    rec_edits.append(rec)
                    continue
                anchor = line_no - 1
                new_rows = [s for s in new.splitlines() if s.strip()]
                head = _HEADING.match(new_rows[0].strip())
                if head:  # новый раздел не разрывает раздел, внутри которого стоит строка
                    anchor = _section_end(lines, fence, anchor, len(head.group(1)))
                elif fence[anchor]:  # внутри блока кода — после его конца
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
                block = _shape_block(new_rows, lines[anchor])
                if head and lines[anchor].strip() and not inserts.get(anchor):
                    block = [("", "raw")] + block  # заголовку нужна пустая строка перед ним (после таблицы — тоже)
                for text_, kind in block:
                    inserts.setdefault(anchor, []).append((text_, fid, kind))
                rec.update(applied=True, line=anchor + 1, was="")
                if origin is not None:
                    rec["src_line"] = src_line(anchor)
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
    org: list[int | None] = []  # номер строки исходника для каждой строки редакции

    def emit(s: str, src: int | None) -> None:
        out.append(s)
        org.append(src)

    inside = False
    fence_marks: list[str] = []
    for i, s in enumerate(text):
        fids = changed.get(i, [])
        is_fence = s.strip().startswith("```")
        here = src_line(i)
        if i in drop:
            if i in deleted:
                fence_marks += [f for f in fids if f not in fence_marks]
            if is_fence and inside and fence_marks:
                emit(f"[удалено: {', '.join(fence_marks)} — пример]", None)
                fence_marks = []
            if is_fence:
                inside = not inside
        elif is_fence:
            emit(s, here)
            if inside and fence_marks:  # закрывающая граница блока кода — пометка отдельной строкой
                emit(f"[изменено: {', '.join(fence_marks)} — пример выше]", None)
                fence_marks = []
            inside = not inside
        elif fids and inside:
            if i not in deleted:
                emit(s, here)
            fence_marks += [f for f in fids if f not in fence_marks]
        elif i in deleted:
            emit(f"[удалено: {', '.join(fids)}]", here)
        elif fids:
            emit(_with_mark(s, f"[изменено: {', '.join(fids)}]"), here)
        else:
            emit(s, here)
        for row, fid, kind in inserts.get(i, []):
            if kind == "mark":
                emit(_with_mark(row, f"[добавлено: {fid}]"), None)
            elif kind == "note":
                emit(f"[добавлено: {fid} — пример выше]", None)
            else:
                emit(row, None)
    return {"markdown": "\n".join(out) + "\n", "rewrites": out_rewrites, "stats": stats, "origin": org,
            "changed_src": {fid: {src_line(i) for i, fs in changed.items() if fid in fs and src_line(i)}
                            for fid in {f for fs in changed.values() for f in fs}}}


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
    for a in answered:
        fids = a.get("finding_ids", [])
        replies = a.get("replies") or []
        head = f"{a.get('question_id')} ({a.get('topic', '')}) → {', '.join(fids)}: "
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
    disputed = _disputed_labels(answers)
    for i, d in enumerate(decisions, 1):
        if f"Решение-{i}" in disputed:  # спорящие реплики адресатов: решение не принято — только маркер
            rows.append(f"Общее решение владельца (Решение-{i}) расходится с другим ответом — значение не вписывай, "
                        f"поставь маркер <уточнить: …> с обоими вариантами: {d}")
        else:
            rows.append(f"Общее решение владельца: {d}")
    return ("\n".join(rows) or "—"), by_finding


def _disputed_labels(answers: Any) -> set[str]:
    """Метки ответов, которые спорят с другими (``answer_conflicts``), — «Q-02.1», «Решение-2»."""
    return {str(x) for c in (answers or {}).get("answer_conflicts") or [] for x in c.get("answers") or []}


def disputed_values(answers: Any) -> dict[str, list[str]]:
    """Число → метки ответов, у которых оно своё в споре (у другой стороны его нет): «422» → [«Решение-2»].

    Правка, которая вписывает такое число вне маркера <уточнить>, выбирает за владельца одну сторону."""
    out: dict[str, list[str]] = {}
    for c in (answers or {}).get("answer_conflicts") or []:
        texts = c.get("texts") or {}
        sides = {str(x): _nums(texts.get(x)) for x in c.get("answers") or [] if texts.get(x)}
        if len(sides) < 2:
            continue
        for lab, vals in sides.items():
            others = set().union(*(v for k, v in sides.items() if k != lab))
            for n in sorted(vals - others):
                out.setdefault(n, []).append(lab)
    return out


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


# правило 1 промпта кодом: «используй выбранное правило и его точные значения… не выдумывай числа, сроки и коды».
# Число правки — «48», «23:59:59», «100 000», «0,5»; одна цифра («2 попытки», номер пункта) не проверяется
_NUM = re.compile(r"(?<![\w.,:-])\d+(?:[.,:]\d+)*(?![\w-])")
_NUMBERING = re.compile(r"(?m)^\s*(?:#{1,6}\s*\d+(?:\.\d+)*\.?|\d+(?:\.\d+)*[.)]|\d+(?:\.\d+)+)(?=\s)"
                        r"|^\s*\|\s*\d+(?:\.\d+)*\s*(?=\|)")  # номер строки таблицы — первая ячейка


def _nums(text: Any) -> set[str]:
    s = _PENDING.sub(" ", str(text or ""))  # варианты внутри <уточнить: …> — вопрос владельцу, а не значение
    s = _NUMBERING.sub(" ", s)  # нумерация раздела, пункта, строки таблицы
    s = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", s)  # «100 000» = «100000»
    return {n.replace(",", ".") for n in _NUM.findall(s) if len(n) >= 2}


def _answered(answers: Any) -> list[dict]:
    if not answers:
        return []
    got = answers.get("answers") if "answers" in answers and "changes" in answers else answers.get("answered")
    return [a for a in got or [] if isinstance(a, dict)]


_RAW_NUM = re.compile(r"(?<![\w.,:-])(\d{1,3}(?:[\u00a0\u202f ]\d{3})+|\d+(?:[.,:]\d+)*)(?![\w-])"
                      r"(\s*(?:[а-яёa-z]+|₸|%))?", re.I)


def _mark_invented(text: str, invented: set[str]) -> str:
    """«через 30 секунд» → «через <уточнить: 30 секунд>»: значение, которого владелец не давал, — вопрос, а не правило.
    Строки таблиц (примеры, тестовые данные) не трогаются."""
    def line(ln: str) -> str:
        if ln.lstrip().startswith("|"):
            return ln
        parts = re.split(r"(<\s*уточнить\s*:[^>]*>)", ln, flags=re.I)  # внутри маркера не трогаем
        for k in range(0, len(parts), 2):
            parts[k] = _RAW_NUM.sub(lambda m: f"<уточнить: {m.group(0).strip()}>"
                                    if _nums(m.group(1)) & invented else m.group(0), parts[k])
        return "".join(parts)
    return "\n".join(line(x) for x in str(text).split("\n"))


def check_values(rewrites: list[dict], answers: Any, lines: list[str], by_id: dict, warnings: list[str]) -> list[dict]:
    """Значения правок по ответам владельца (правило 1 промпта — кодом).

    * Правка вписывает значение варианта, который владелец отверг, без выбранного им значения, — не вносится.
    * В правке по ответу число, которого нет ни в документе, ни в ответах владельца, ни в дефекте (выдуманное
      значение), — помечается маркером «<уточнить: …>»: решает владелец, а не модель.
    """
    known = _nums("\n".join(lines))
    answered = _answered(answers)
    for a in answered:
        known |= _nums(a.get("answer")) | _nums(" ".join(str(r.get("text") or "") for r in a.get("replies") or []))
    for d in (answers or {}).get("decisions") or []:
        known |= _nums(d)
    by_q = {a.get("question_id"): a for a in answered}
    disputed = disputed_values(answers)
    out = []
    for r in rewrites:
        if disputed:  # значение одной стороны спора вне маркера — выбор за владельца, в любой правке
            kept = []
            for e in r["edits"]:
                hit = sorted((_nums(e.get("new")) - _nums(e.get("old"))) & set(disputed))
                if hit:
                    who = ", ".join(dict.fromkeys(x for n in hit for x in disputed[n]))
                    warnings.append(f"revise: {r['finding_id']} — правка вписывает {', '.join(hit)} из ответа {who}, "
                                    f"а ответы адресатов расходятся; правка не внесена — нужен маркер <уточнить: …>")
                    continue
                kept.append(e)
            if not kept:
                continue
            r = dict(r, edits=kept)
        if not r.get("answer_ids"):  # без ответа владельца сверять не с чем — правило 1 держит промпт
            out.append(r)
            continue
        f = by_id.get(r["finding_id"]) or {}
        quotes = " ".join(str(e.get("quote") or "") for e in f.get("evidence") or [] if isinstance(e, dict))
        own = known | _nums(" ".join(str(f.get(k) or "") for k in
                                     ("title", "problem", "scenario", "impact", "recommendation", "rewrite")) + " " + quotes)
        picks = []  # (вопрос, выбранные числа, числа отвергнутых вариантов, ответ)
        for qid in r["answer_ids"]:
            a = by_q.get(qid) or {}
            if a.get("rejected_options"):
                chosen = _nums(a.get("answer"))
                other = set().union(*(_nums(o) for o in a["rejected_options"])) - chosen
                if other:
                    picks.append((qid, chosen, other, str(a.get("answer") or "")))
        edits = []
        for e in r["edits"]:
            new = str(e.get("new") or "")
            body = "\n".join(x for x in new.split("\n") if not x.lstrip().startswith("|"))
            vals = _nums(new)
            wrong = next(((qid, sorted(vals & other), ans) for qid, chosen, other, ans in picks
                          if vals & other and not vals & chosen), None)
            if wrong:
                warnings.append(f"revise: {r['finding_id']} — правка вписывает {', '.join(wrong[1])} из варианта, "
                                f"который владелец отверг в {wrong[0]} (выбрано: «{wrong[2][:60]}»); правка не внесена")
                continue
            invented = _nums(body) - _nums(e.get("old")) - own
            if invented:
                warnings.append(f"revise: {r['finding_id']} — в правке {', '.join(sorted(invented))}: такого значения нет "
                                f"ни в документе, ни в ответах владельца, ни в дефекте — помечено <уточнить: …>")
                e = dict(e, new=_mark_invented(new, invented))
            edits.append(e)
        if edits:
            out.append(dict(r, edits=edits))
    return out

def format_findings(items: list[dict]) -> str:
    """Таблица дефектов для промпта (как у clarify) + вид дефекта и допустимый вид правки."""
    out = []
    for f in items:
        rows = _cl.format_findings([f]).split("\n")
        hint = CLASS_HINT.get(defect_class(f))
        if hint:
            rows.insert(1, f"  вид: {hint}")
        out += rows
    return "\n".join(out)


# --------------------------------------------------------------------------- этап
def run(ctx: Any, findings: list[dict], answers: Any = None, requirements: list[dict] | None = None) -> dict:
    """``{"rewrites": [...], "revised_markdown": str, "stats": {...}}`` по critical и major.

    ``findings`` — все дефекты отчёта (minor нужны страховке: их строки тоже чужие), ``requirements`` —
    требования отчёта (по умолчанию ``ctx.requirements``)."""
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
                                                                  "pending": 0, "rejected": 0}}
    ans_text, by_finding = _answers_block(answers)
    for t in owner:
        by_finding[t["id"]] = [t["id"]]
    if requirements is None:
        requirements = list(getattr(ctx, "requirements", None) or [])
    guard = Guard(findings, requirements)

    def build(items: list) -> tuple[str, str]:
        block = format_findings(items)
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
    rewrites = check_values(rewrites, answers, lines, by_id, warnings)
    applied = apply_edits(lines, rewrites, warnings, guard=guard)
    opts = getattr(ctx, "options", None) or {}
    check = {"fixes": [], "stats": {}}
    if isinstance(opts, dict) and opts.get("revise_check", True) and applied["stats"].get("replaced", 0) + \
            applied["stats"].get("inserted", 0) + applied["stats"].get("rejected", 0):
        guard.owner_numbers = frozenset(_numbers(ans_text)) if by_finding or ans_text != "—" else frozenset()
        check = _check_pass(ctx, applied, warnings, guard)
        guard.owner_numbers = frozenset()
        if check.get("markdown"):
            applied["markdown"] = check["markdown"]
        applied["stats"]["rejected"] += check.get("stats", {}).get("rejected", 0)
    for r in applied["rewrites"]:
        r["pending"] = sum(len(_PENDING.findall(e.get("became", ""))) for e in r["edits"] if e.get("applied"))
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
    # не применённые правки с причиной — в отчёт (revise_stats), а не в таблицу «было → стало»
    skipped = [{"finding_id": r["finding_id"], "pass": n, "action": e.get("action", ""),
                "line": e.get("src_line", e.get("line")) if n == 2 else e.get("line"),
                "was": str(e.get("was", ""))[:300], "became": str(e.get("became", ""))[:300],
                "reason": e.get("reason", "")}
               for n, items in ((1, applied["rewrites"]), (2, check.get("fixes", [])))
               for r in items for e in r.get("edits") or [] if not e.get("applied")]
    return {"rewrites": applied["rewrites"], "revised_markdown": md, "check_fixes": check.get("fixes", []),
            "stats": {**applied["stats"], "findings": n_findings, "decisions": len(owner),
                      "with_rewrite": len(rewrites),
                      "without_rewrite": missing, "check_fixes": len(check.get("fixes", [])),
                      "check_edits": check.get("stats", {}).get("replaced", 0) + check.get("stats", {}).get("inserted", 0),
                      "not_applied_edits": skipped,
                      # что код не внёс или пометил (отвергнутое значение, выбор стороны спора, выдуманное число):
                      # предупреждения этапа идут после сборки run.warnings — без этого поля их нет в отчёте
                      "warnings": list(dict.fromkeys(warnings))}}


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


def _rejected_lines(applied: dict) -> list[str]:
    """Правки первого прохода, которые страховка не применила, — с номером строки уже в редакции."""
    where = {src: i + 1 for i, src in enumerate(applied.get("origin") or []) if src}
    rows = []
    for r in applied.get("rewrites") or []:
        for e in r.get("edits") or []:
            if e.get("rejected"):
                ln = where.get(int(e.get("line") or 0))
                at = f"L{ln:03d}" if ln else f"строка {e.get('line')} исходника"
                rows.append(f"{r['finding_id']} | {at} | было «{str(e.get('was', ''))[:160]}» → предложено "
                            f"«{str(e.get('became', ''))[:240]}» | не применено: {e.get('reason', '')}")
    return rows


def _check_pass(ctx: Any, applied: dict, warnings: list[str], guard: Guard | None = None) -> dict:
    """Второй проход: противоречия, которые внесли сами правки, и их исправление (1 вызов модели); правки,
    которые страховка не применила, модель переделывает вставкой или точечной заменой."""
    md = applied["markdown"]
    md_lines = md.splitlines()
    changes = _changed_lines(md_lines)
    rejected = _rejected_lines(applied)
    if not changes and not rejected:
        return {"fixes": []}
    by_fid = {r["finding_id"]: r for r in applied["rewrites"]}
    summary = "\n".join(f"{fid}: {r.get('title', '')} — {r.get('summary', '')}" for fid, r in by_fid.items())
    block = ("\n".join(changes) or "—") + "\n\nДефекты:\n" + summary
    if rejected:
        block += "\n\nНе применённые правки (страховка):\n" + "\n".join(rejected)
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
                                  "edits": f["edits"]} for f in fixes], warnings, guard=guard,
                      origin=applied.get("origin"))
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
           + (f" Не применено правок, которые задели бы другие требования: {st['rejected']}."
              if st.get("rejected") else "")
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
        if report_path:  # файл ответов следующего круга: что решить + уже согласованное
            try:
                doc = (report.get("document") or {}).get("file") or (report.get("document") or {}).get("name") or ""
                path = recheck.next_answers_path(report_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                sha = str((report.get("document") or {}).get("sha256") or "")
                path.write_text(recheck.render_next_answers(clar, str(doc), Path(report_path).name, sha),
                                encoding="utf-8")
                clar["next_answers_file"] = str(path)
                if clar.get("next_round"):
                    _cl._warn(ctx, f"recheck: осталось решить {len(clar['next_round'])} — строки для следующего круга "
                                   f"в {path.name} (там же уже согласованные ответы)")
            except OSError as exc:
                _cl._warn(ctx, f"recheck: файл ответов следующего круга не записан ({exc})")
    if do_revise:
        try:
            r = run(ctx, list(report.get("findings") or []), clar, requirements=report.get("requirements"))
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
