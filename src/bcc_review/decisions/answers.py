"""Файл вопросов, разбор ответов владельца и применение решений (№08).

``parse_answers`` читает три формата одним кодом:

1. файл вопросов №08 (``Ответ:`` — последнее поле карточки, ниже);
2. экспорт HTML №13 ``format: bcc-review-answers/1``: фронтматтер с
   ``source_sha256``, ``## Q-01``, строка ``Варианты: A. … | B. …``, заголовок
   ``### Ответ`` и текст ответа (строки, начинавшиеся с решётки или обратной косой черты,
   экранированы обратной косой чертой);
3. резервный формат движка: ``Ответ: …`` и строки ``Правка: «старое» → «новое»``.

Правки берутся без доступа к отчёту: выбранная буква → строка ``Варианты:``
(``Question.options`` несут «· Правка [b0012]: «…» → «…»»), плюс явные строки
``Правка:`` в ответе. Координаты считает код по текущему документу.

Формат файла №08::

    <!-- bcc-review:answers v1 -->
    source_sha256: <64 hex SHA-256 исходного документа>

    ## Q-01. <вопрос>              ← заголовок 2–3 уровня с ID вопроса
    ... карточка (любой текст, парсер её не читает) ...
    Ответ: A                       ← последнее поле карточки

    ## Q-02
    Ответ:
    многострочный ответ —
    всё до следующего заголовка ## Q-…

Правила ответа:

* пусто (или только «—», «?») — вопрос остаётся открытым, решение не создаётся;
* латинская буква варианта: ``A``, ``B. комментарий``, ``Вариант C``.
  Кириллические двойники «А», «В», «С» читаются по начертанию, «Б» — как B.
  Кириллическая буква без точки или тире после неё («В течение…») — это
  свой ответ, а не вариант;
* ``отложить`` — решение отложено, документ не меняется;
* любой другой текст — свой ответ. Строка ``Формулировка: …`` внутри ответа
  задаёт новый текст: он заменяет предложение с цитатой (для пропуска —
  добавляется после него). Без формулировки решение сохраняется, текст не
  меняется;
* «A, B» — несколько вариантов сразу: решение не принимается (invalid).

Допускаются ``**Ответ:**``, CRLF, BOM, неразрывные пробелы и HTML-комментарии
(они вырезаются из ответа).
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ._doc import DocView, format_loc, get, option_letter, short_sha
from .clarify import Question

ANSWERS_MARKER = "<!-- bcc-review:answers v1 -->"

_Q_HEAD = re.compile(r"^[ \t]*#{2,3}[ \t]*(Q-\d{1,4})\b[^\n]*$", re.M)
_ANS = re.compile(
    r"^[ \t]*(?:\*\*|__)?[ \t]*Ответ[ \t]*(?:\*\*|__)?[ \t]*[:：][ \t]*(?:\*\*|__)?[ \t]*(.*)$", re.M)
_SHA = re.compile(r"source_sha256[ \t]*[:=][ \t]*`?([0-9a-fA-F]{64})`?")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DEFER = re.compile(r"^\s*(?:отлож\w*|defer\w*|позже|later)(?=$|[\s.,:;!—–-])[\s.,:;!—–-]*", re.I)
_WORDING = re.compile(
    r"^[ \t]*(?:\*\*)?(?:новая[ \t]+формулировка|формулировка|стало)(?:\*\*)?[ \t]*[:：](?:\*\*)?[ \t]*",
    re.M | re.I)
_LAT = re.compile(r"^\s*(?:(?:вариант|option)\s+)?([A-Fa-f])(?=$|[\s.):;,—–-])[\s.):;,—–-]*", re.I)
_CYR_PREFIXED = re.compile(r"^\s*(?:вариант|option)\s+([АБВСЕабвсе])(?=$|[\s.):;,—–-])[\s.):;,—–-]*", re.I)
_CYR_BARE = re.compile(r"^\s*([АБВСЕабвсе])(?:\s*$|\s*[.):;,]\s*|\s+[—–-]\s*)", re.I)
# Второй вариант сразу после первого («A, B», «A и B»): латиница — до пробела или
# знака, кириллица — только до знака, чтобы «A. В течение…» не считалось двумя вариантами.
_MULTI = re.compile(
    r"^(?:(?:и|или|or|and)\s+)?(?:вариант\s+)?(?:[A-F](?=$|[\s.):;,])|[АБВСЕ](?=$|[.):;,]))")
_EMPTYISH = re.compile(r"^[\s\-—–.?…_*]*$")
_ANS_HEADING = re.compile(r"^[ \t]*#{3,4}[ \t]*Ответ[ \t]*:?[ \t]*$", re.M)
_OPTIONS_LINE = re.compile(r"^[ \t]*Варианты[ \t]*:[ \t]*(.+)$", re.M)
_OPTION_SPLIT = re.compile(r"\s+\|\s+(?=[A-F][.)]\s)")
_EDIT_HEAD = re.compile(r"(?:Правка|Edit)(?:[ \t]*\[([^\]\s]+)\])?[ \t]*:[ \t]*(?=«)", re.I)
_ARROW = re.compile(r"\s*(?:→|->)\s*(?=«)")


def _balanced(text: str, i: int) -> tuple[str, int] | None:
    """Содержимое «…» с учётом вложенных кавычек, начиная с text[i] == '«'."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "«":
            depth += 1
        elif text[j] == "»":
            depth -= 1
            if depth == 0:
                return text[i + 1: j], j + 1
    return None


def parse_edit_specs(text: str, origin: str = "owner") -> list[dict]:
    """«Правка [b0012]: «старое» → «новое»» -> [{block_id|None, old, new, origin}]."""
    out = []
    for m in _EDIT_HEAD.finditer(text or ""):
        a = _balanced(text, m.end())
        if a is None:
            continue
        arrow = _ARROW.match(text, a[1])
        if not arrow:
            continue
        b = _balanced(text, arrow.end())
        if b is None:
            continue
        out.append({"block_id": m.group(1), "old": a[0], "new": b[0], "origin": origin})
    return out


def _options_from_section(body: str) -> dict[str, str]:
    """Строка «Варианты: A. … | B. …» (№13 и карточка №08) -> {буква: текст}."""
    m = _OPTIONS_LINE.search(body)
    if not m:
        return {}
    out: dict[str, str] = {}
    for part in _OPTION_SPLIT.split(m.group(1).strip()):
        om = re.match(r"^([A-F])[.)]\s*(.*)$", part.strip(), re.S)
        if om and om.group(1) not in out:
            out[om.group(1)] = om.group(2).strip()
    return out


# ---------------------------------------------------------------------------
# Решение
# ---------------------------------------------------------------------------


def interpret(answer: str) -> tuple[str, str, str]:
    """Текст ответа -> (choice, comment, wording).

    choice: буква варианта | "custom" | "defer" | "open" | "invalid".
    """
    text = (answer or "").strip()
    if _EMPTYISH.match(text):
        return "open", "", ""
    wording = ""
    m = _WORDING.search(text)
    if m:
        wording = text[m.end():].strip()
        text = text[: m.start()].strip()
        if not text:
            return ("custom", "", wording) if wording else ("open", "", "")
    d = _DEFER.match(text)
    if d:
        return "defer", text[d.end():].strip(), wording
    for rx in (_LAT, _CYR_PREFIXED, _CYR_BARE):
        c = rx.match(text)
        if c:
            letter = option_letter(c.group(1))
            rest = text[c.end():].strip()
            if letter:
                if _MULTI.match(rest):
                    return "invalid", text, wording
                return letter, rest, wording
    return "custom", "", wording


@dataclass
class Decision:
    """Решение владельца по одному вопросу (контракт: question_id, source_sha256, answer)."""

    question_id: str
    source_sha256: str | None
    answer: str
    choice: str = "open"
    comment: str = ""
    wording: str = ""
    edits: list[dict] = field(default_factory=list)
    note: str = ""
    edit_specs: list[dict] = field(default_factory=list)   # правки без координат (не найдены при разборе)
    option_text: str | None = None                         # текст выбранного варианта из «Варианты:»
    patch_state: str = ""                                  # "collision" / "stale" — решено при разборе

    @classmethod
    def from_answer(cls, question_id: str, source_sha256: str | None, answer: str) -> "Decision":
        choice, comment, wording = interpret(answer)
        return cls(question_id, source_sha256, (answer or "").strip(), choice, comment, wording)

    @classmethod
    def coerce(cls, obj: Any) -> "Decision":
        if isinstance(obj, Decision):
            return obj
        answer = get(obj, "answer")
        if answer is None and get(obj, "choice"):
            answer = str(get(obj, "choice"))
        d = cls.from_answer(str(get(obj, "question_id")), get(obj, "source_sha256"), str(answer or ""))
        d.edits = [dict(e) for e in (get(obj, "edits") or [])]
        d.edit_specs = [dict(e) for e in (get(obj, "edit_specs") or [])]
        d.option_text = get(obj, "option")
        d.patch_state = str(get(obj, "patch_state") or "")
        d.note = str(get(obj, "note") or "")
        if not d.edits and not d.edit_specs and answer:  # dict из резервного формата: правки в тексте ответа
            d.edit_specs = parse_edit_specs(str(answer))
        return d

    @property
    def status(self) -> str:
        return {"open": "open", "defer": "deferred", "invalid": "invalid"}.get(self.choice, "accepted")

    def to_dict(self) -> dict:
        """Decision v1 (question_id, source_sha256, answer, edits, note) и поля №08."""
        d = {
            "question_id": self.question_id, "source_sha256": self.source_sha256,
            "answer": self.answer, "edits": [dict(e) for e in self.edits], "note": self.note,
            "choice": self.choice, "comment": self.comment, "wording": self.wording,
            "status": self.status,
        }
        if self.edit_specs:
            d["edit_specs"] = [dict(e) for e in self.edit_specs]
        if self.option_text is not None:
            d["option"] = self.option_text
        if self.patch_state:
            d["patch_state"] = self.patch_state
        return d


@dataclass
class AnswerSet:
    source_sha256: str | None
    decisions: list[Decision] = field(default_factory=list)
    open_ids: list[str] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    seen_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _contract: list[dict] | None = field(default=None, repr=False, compare=False)

    # Ведёт себя как list[Decision] (точка входа №08 в contracts/HANDOFF.md):
    # итерация, len и индекс — по заполненным решениям; метаданные разбора — в полях.
    def __iter__(self):
        return iter(self.decisions)

    def __len__(self) -> int:
        return len(self.decisions)

    def __getitem__(self, i):
        if isinstance(i, str):
            return self.get(i)
        return self.decisions[i]

    def get(self, key: str, default: Any = None) -> Any:
        """Вид для движка (``engine.apply_answers``): ``decisions`` — список dict Decision v1
        к текущей версии (каждый dict передаётся в propose_patch и попадает в Report),
        ``warnings`` — пояснения разбора."""
        if key == "decisions":
            if self._contract is None:
                self._contract = [d.to_dict() for d in self.decisions
                                  if d.source_sha256 and d.patch_state != "stale"]
            return self._contract
        if key == "warnings":
            return self.warnings
        return default

    def decision(self, question_id: str) -> Decision | None:
        for d in self.decisions:
            if d.question_id == question_id:
                return d
        return None

    def to_dict(self) -> dict:
        return {
            "source_sha256": self.source_sha256,
            "decisions": [d.to_dict() for d in self.decisions],
            "open_ids": list(self.open_ids), "unknown_ids": list(self.unknown_ids),
            "duplicate_ids": list(self.duplicate_ids), "seen_ids": list(self.seen_ids),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Разбор файла ответов
# ---------------------------------------------------------------------------


def _clean_answer(raw: str) -> str:
    raw = _COMMENT.sub("", raw)
    lines = [ln.rstrip() for ln in raw.split("\n")]
    while lines and lines[-1].strip() in ("", "---", "***", "___"):
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    first, rest = lines[0].strip(), textwrap.dedent("\n".join(lines[1:]))
    return (first + ("\n" + rest if rest.strip() else "")).strip()


def parse_answers(
    source: str | Path,
    document: Any = None,
    *,
    questions: Iterable[Any] | None = None,
    expected_sha: str | None = None,
) -> AnswerSet:
    """Разобрать answers.md (или экспорт HTML №13).

    ``document`` — текущая версия документа: его SHA-256 сверяется с
    ``source_sha256`` файла. Результат итерируется как ``list[Decision]``; в него
    попадают только заполненные решения, пустые — в ``open_ids``."""
    if document is not None and expected_sha is None:
        expected_sha = DocView(document).id
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and len(source) < 4096
                                    and Path(source).suffix.lower() in {".md", ".txt", ".markdown"}):
        text = Path(source).read_bytes().decode("utf-8-sig")
    else:
        text = str(source)
        if text.startswith("﻿"):
            text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")

    heads = list(_Q_HEAD.finditer(text))
    header = text[: heads[0].start()] if heads else text
    warns: list[str] = []
    shas = {s.lower() for s in _SHA.findall(header)} or {s.lower() for s in _SHA.findall(text)}
    sha: str | None = None
    if len(shas) == 1:
        sha = shas.pop()
    elif len(shas) > 1:
        warns.append("[sha_conflict] в файле несколько разных source_sha256 — решения не привязаны к версии")
    else:
        warns.append("[no_sha] в файле нет source_sha256 — решения не привязаны к версии")
    stale = bool(sha and expected_sha and sha != expected_sha)
    if stale:
        warns.append(f"[stale_answers] ответы относятся к другой редакции (source_sha256 {short_sha(sha)}…, "
                     f"документ {short_sha(expected_sha)}…): правки не применены")

    known = {str(get(q, "id")) for q in questions} if questions is not None else None
    raw: dict[str, list[str]] = {}
    options: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for i, h in enumerate(heads):
        qid = h.group(1)
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        hm = _ANS_HEADING.search(body)   # №13: «### Ответ», ответ — строки ниже
        m = _ANS.search(body)
        if hm and (not m or hm.start() <= m.start()):
            lines = body[hm.end():].split("\n")
            ans = _clean_answer("\n".join(ln[1:] if ln.startswith("\\") else ln for ln in lines))
            card = body[: hm.start()]
        elif m:
            ans = _clean_answer(m.group(1) + body[m.end():])
            card = body[: m.start()]
        else:
            warns.append(f"[no_answer_field] {qid}: нет поля «Ответ:» — вопрос считается открытым")
            ans, card = "", body
        if qid not in raw:
            order.append(qid)
            options[qid] = _options_from_section(card)
        raw.setdefault(qid, []).append(ans)

    aset = AnswerSet(source_sha256=sha, seen_ids=list(order), warnings=warns)
    for qid in order:
        if known is not None and qid not in known:
            aset.unknown_ids.append(qid)
            warns.append(f"[unknown_id] {qid}: такого вопроса нет в текущем наборе — ответ пропущен")
            continue
        values = raw[qid]
        filled = [v for v in values if interpret(v)[0] != "open"]
        if len(values) > 1:
            aset.duplicate_ids.append(qid)
        if len(set(filled)) > 1:
            warns.append(f"[duplicate_conflict] {qid}: {len(filled)} разных ответа — решение не принято, "
                         "оставьте один")
            continue
        if len(values) > 1:
            warns.append(f"[duplicate_id] {qid}: карточка повторяется {len(values)} раз — "
                         "учтён один заполненный ответ" if filled else
                         f"[duplicate_id] {qid}: карточка повторяется {len(values)} раз, ответов нет")
        if not filled:
            aset.open_ids.append(qid)
            continue
        dec = Decision.from_answer(qid, sha, filled[0])
        dec.edit_specs = parse_edit_specs(dec.answer, "owner")
        if dec.choice in options.get(qid, {}):
            dec.option_text = options[qid][dec.choice]
            dec.edit_specs += parse_edit_specs(dec.option_text, "option")
        if stale:
            dec.patch_state = "stale"
        aset.decisions.append(dec)
    if known is not None:
        for qid in sorted(known - set(order)):
            aset.open_ids.append(qid)
            warns.append(f"[missing_card] {qid}: карточки нет в файле ответов — вопрос открыт")
    if document is not None and not stale:
        _resolve_and_check(DocView(document), aset)
    return aset


def _resolve_and_check(doc: DocView, aset: AnswerSet) -> None:
    """Координаты правок по текущему документу и коллизии между решениями.

    Только здесь видны все ответы сразу: движок вызывает propose_patch по одному
    решению, поэтому пересечение правок двух решений отклоняется на разборе —
    оба решения получают ``patch_state = "collision"`` и причину с фрагментами."""
    from .patches import describe_collision, find_collisions, resolve_spec

    active = [d for d in aset.decisions if d.choice not in ("open", "defer", "invalid") and d.source_sha256]
    for d in active:
        kept = []
        for spec in d.edit_specs:
            e, why = resolve_spec(doc, spec)
            if e is None:
                kept.append(spec)  # propose_patch даст явную причину
                continue
            e.update(origin=spec.get("origin", "owner"), question_id=d.question_id)
            d.edits.append(e)
        d.edit_specs = kept
    tagged = [e for d in active for e in d.edits]
    for c in find_collisions(tagged):
        a, b = c["a"].get("question_id"), c["b"].get("question_id")
        if a == b:
            continue  # внутри одного решения: своя правка владельца важнее варианта (propose_patch)
        msg = "[collision] " + describe_collision(c, doc)
        if msg not in aset.warnings:
            aset.warnings.append(msg)
        for d in active:
            if d.question_id in (a, b):
                d.patch_state, d.note = "collision", msg


# ---------------------------------------------------------------------------
# Файл вопросов
# ---------------------------------------------------------------------------


def _q(s: str) -> str:
    return "«" + " ".join(str(s).split()) + "»"


def render_card(q: Any, doc: DocView | None = None) -> str:
    q = Question.from_dict(q)
    rows = [
        ("Владелец решения", q.owner),
        ("Что блокируется", (" и ".join(q.blocks) or "—") + (f": {q.blocked_decision}" if q.blocked_decision else "")),
        ("Замечания", ", ".join(q.finding_ids) or "—"),
        ("Затронутые требования", ", ".join(q.affected_req_ids) or "—"),
        ("Почему в этой позиции", q.rank_reason or "—"),
    ]
    out = [f"## {q.id}. {q.prompt}", "", "| Поле | Значение |", "| :--- | :--- |"]
    out += [f"| {k} | {v.replace('|', '/')} |" for k, v in rows]
    out += ["", f"**Ситуация.** {q.situation}", "", f"**Вопрос.** {q.prompt}", "",
            f"**Почему важно.** {q.why}", "", "**Исходные цитаты и координаты:**"]
    for i, s in enumerate(q.sources, start=1):
        fid = f" ({s['finding_id']})" if s.get("finding_id") else ""
        out.append(f"{i}. {_q(s['quote'])} — {s.get('loc', '')}{fid}")
    if q.document_answer:
        da = q.document_answer
        out += ["", f"**Источник ответа в документе:** {_q(da['quote'])} — {da.get('loc', '')}. "
                "Предлагаем привести несовпадающий фрагмент к этому источнику."]
    if q.hypothesis:
        out += ["", f"**Гипотеза о намерении автора (не решение, требует подтверждения):** {q.hypothesis}"]
    out += ["", "**Варианты:**", ""]
    for o in q.options:
        out.append(f"- **{o.id}. {o.label}**")
        out.append(f"  - Трактовка: {o.interpretation}")
        out.append(f"  - Наблюдаемый результат: {o.observable_result}")
        if o.consequences:
            out.append(f"  - Последствия: {o.consequences}")
        for e in o.edits:
            loc = e.get("loc") or (format_loc(doc.block(e["block_id"]), e["start"], e["end"]) if doc else e["block_id"])
            new = _q(e["new"]) if e["new"] else "— (фрагмент удаляется)"
            out.append(f"  - Правка ({loc}): было {_q(e['old'])} → стало {new}")
        if not o.edits:
            out.append("  - Правка: нет — решение фиксируется, текст не меняется без формулировки владельца")
        for w in o.warnings:
            out.append(f"  - ⚠ {w}")
    out += [
        "- **Свой ответ.** Опишите правило своими словами. Чтобы изменить текст, добавьте строку "
        "«Формулировка: …» — она заменит предложение с цитатой (для пропуска — добавится после "
        "него). Без формулировки решение сохранится, текст не изменится.",
        "- **Отложить.** Напишите «отложить»: документ останется как есть, вопрос — открытым.",
        "",
        # машинная строка вариантов — та же, что печатает экспорт №13; по ней разбор находит правку
        "Варианты: " + " | ".join(" ".join(t.split()) for t in q.option_texts()),
        "", "Ответ:", "",
    ]
    return "\n".join(out)


def render_questions_md(document: Any, questions: Iterable[Any]) -> str:
    doc = DocView(document)
    qs = [Question.from_dict(q) for q in questions]
    for q in qs:
        for o in q.options:
            for e in o.edits:
                e.setdefault("loc", format_loc(doc.block(e["block_id"]), e["start"], e["end"]))
    head = [
        ANSWERS_MARKER,
        f"# Вопросы владельцу продукта: {doc.title}",
        "",
        f"source_sha256: {doc.id}",
        "",
        "Файл ответов к версии документа с этим SHA-256. Впишите решение после «Ответ:» в каждой "
        "карточке: латинскую букву варианта (A, B, …), слово «отложить» или свой текст — можно в "
        "несколько строк. Пустое поле — вопрос остаётся открытым. Повторный прогон с ответами: "
        "`python -m bcc_review INPUT OUTPUT.md --answers answers.md`.",
        "",
        f"Вопросов: {len(qs)}. Порядок — по важности: сначала развилки, которые блокируют "
        "разработку и тестирование.",
        "",
    ]
    return "\n".join(head) + "\n" + "\n".join(render_card(q, doc) for q in qs)


def write_questions(document: Any, questions: Iterable[Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_questions_md(document, questions), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Применение решений
# ---------------------------------------------------------------------------


def apply_answers(
    document: Any,
    questions: Iterable[Any],
    answers: AnswerSet | str | Path,
    *,
    findings: Iterable[Any] | None = None,
    output_md: str | Path | None = None,
    source: Any = None,
) -> dict:
    """Ответы -> предложенные правки -> (при наличии правок) редакция отдельным файлом.

    Коллизии двух решений не применяются: оба вопроса получают состояние
    ``collision`` и остаются открытыми, остальное применяется.
    """
    from .patches import (
        EditCollisionError, decision_status, describe_collision, find_collisions,
        manifest_path_for, propose_patch, write_revision,
    )

    doc = DocView(document)
    qs = [Question.from_dict(q) for q in questions]
    aset = answers if isinstance(answers, AnswerSet) else parse_answers(
        answers, questions=qs, expected_sha=doc.id)
    fmap = {str(get(f, "id")): f for f in (findings or [])}
    results: dict[str, dict] = {}
    for q in qs:
        dec = aset.decision(q.id) or Decision(q.id, aset.source_sha256, "")
        finding = fmap.get(q.finding_ids[0]) if q.finding_ids else None
        if dec.choice == "invalid":
            results[q.id] = {"question_id": q.id, "finding_ids": q.finding_ids, "choice": "invalid",
                             "state": "invalid_choice", "edits": [], "expected_result": None,
                             "warnings": [f"[invalid_choice] {q.id}: выбрано несколько вариантов "
                                          f"({dec.answer!r}) — оставьте один"]}
            continue
        results[q.id] = propose_patch(doc.raw, finding, dec, question=q)

    proposed = [e for r in results.values() if r["state"] == "proposed" for e in r["edits"]]
    collisions = find_collisions(proposed)
    messages = []
    for c in collisions:
        msg = describe_collision(c, doc)
        messages.append(msg)
        for side in ("a", "b"):
            qid = c[side].get("question_id")
            if qid in results and results[qid]["state"] == "proposed":
                results[qid]["state"] = "collision"
                results[qid]["edits"] = []
            if qid in results:
                results[qid]["warnings"].append(f"[collision] {msg}")
    edits = [e for r in results.values() if r["state"] == "proposed" for e in r["edits"]]

    revision = manifest = None
    notes: list[str] = []
    if output_md and edits:
        try:
            revision = write_revision(doc.raw, edits, output_md, source=source, questions=qs,
                                      results=results, decisions=aset.decisions)
            manifest = manifest_path_for(revision)
        except EditCollisionError as exc:  # пересечение, найденное уже в исходном тексте
            notes.append(f"[collision] {exc}")
    elif output_md:
        notes.append("[no_revision] принятых правок нет — документ остаётся в текущем виде, "
                     "редакция не создана")

    statuses = []
    decisions: list[dict] = []
    for q in qs:
        r = results[q.id]
        written = revision is not None and r["state"] == "proposed"
        dec = aset.decision(q.id)
        if dec is not None and dec.source_sha256:
            d = Decision(dec.question_id, dec.source_sha256, dec.answer, dec.choice, dec.comment,
                         dec.wording, edits=[_contract_edit(e) for e in r["edits"]],
                         note=_STATE_RU.get("applied" if written else r["state"], r["state"])).to_dict()
            d.update({"decision_status": decision_status(r["state"]),
                      "patch_state": "applied" if written else r["state"],
                      "fix_status": "applied_not_verified" if written else "not_applied"})
            decisions.append(d)
        statuses.append({
            "question_id": q.id, "finding_ids": q.finding_ids, "choice": r["choice"],
            "decision_status": decision_status(r["state"]),
            "patch_state": "applied" if written else r["state"],
            "fix_status": "applied_not_verified" if written else "not_applied",
            "expected_result": r.get("expected_result"),
        })
    return {
        "source_sha256": doc.id, "answers_sha256": aset.source_sha256,
        "answers": aset.to_dict(), "results": results, "collisions": collisions,
        "collision_messages": messages, "edits": edits,
        "revision": str(revision) if revision else None,
        "manifest": str(manifest) if manifest else None,
        "statuses": statuses, "decisions": decisions, "warnings": aset.warnings + notes,
    }


def _contract_edit(e: dict) -> dict:
    """Edit v1 + привязка к вопросу и версии (дополнительные поля разрешены)."""
    keep = ("block_id", "start", "end", "old", "new", "question_id", "source_sha256", "origin")
    return {k: e[k] for k in keep if k in e}


_STATE_RU = {
    "open": "открыт: ответа нет", "deferred": "отложен владельцем", "proposed": "правка готова",
    "applied": "правка внесена в редакцию", "needs_wording": "решение принято, нужна формулировка",
    "stale": "ответ к другой версии документа", "already_applied": "правка уже в тексте",
    "precondition_failed": "текст не совпал — правка не применена",
    "invalid_choice": "вариант не распознан", "collision": "коллизия с другой правкой — нужен выбор",
}


def render_apply_summary_md(result: dict) -> str:
    """Короткая сводка для владельца: что решено, что применено, что ждёт решения."""
    out = ["# Применение решений владельца", "",
           f"Документ: `{short_sha(result['source_sha256'])}` · ответы к версии "
           f"`{short_sha(result.get('answers_sha256'))}`", ""]
    out += ["| Вопрос | Выбор | Решение | Текст | Ожидаемый результат |", "| :--- | :--- | :--- | :--- | :--- |"]
    for s in result["statuses"]:
        exp = (s.get("expected_result") or "—").replace("|", "/").replace("\n", " ")
        out.append(f"| {s['question_id']} | {s['choice']} | {s['decision_status']} | "
                   f"{_STATE_RU.get(s['patch_state'], s['patch_state'])} | {exp} |")
    if result.get("collision_messages"):
        out += ["", "## Требуют решения владельца", ""]
        out += [f"- {m}" for m in result["collision_messages"]]
    warns = [w for r in result["results"].values() for w in r["warnings"]] + result.get("warnings", [])
    if warns:
        out += ["", "## Пояснения", ""] + [f"- {w}" for w in warns]
    out += ["", "Статус «закрыто» появляется только после повторного анализа редакции "
            "(SHA-256 файла должен совпасть с манифестом): "
            f"`python -m bcc_review {Path(result['revision']).name if result.get('revision') else 'REVISION.md'} "
            "REPORT_v2.md`."]
    return "\n".join(out) + "\n"
