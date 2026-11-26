"""Проверка отдельного требования (направление №05).

Публичный интерфейс::

    review_individual(document, requirements, ask=None, *, criteria=None)
        -> {"checks": [...], "candidates": [...], "warnings": [...], "meta": {...}}

* ``checks`` — матрица «требование × критерий» (scope = requirement из ``criteria.toml``):
  ``{req_id, criterion, status: pass|issue|unknown|na, reason, origin, [question], [severity], [refs]}``.
  Каждое требование получает запись по каждому критерию.
* ``candidates`` — замечания по контракту v1 ``{scope, kind, criterion, severity, title, impact,
  req_ids, hints}`` плюс ``condition``, ``fix``, ``question``, ``root_cause``, ``origin``, ``ref``.
  Одна первопричина — одна кандидатура со ссылками на все затронутые требования.
* ``warnings`` — строки ``"individual.<код>: …"``.
* ``meta`` — версия промпта и конфига, режим, число физических вызовов модели.

При ``ask=None`` работают только детерминированные правила (заглушки, пустые поля,
неоперациональные слова с учётом контекста, сроки, диапазоны, единичность, уровень документа).
С ``ask`` движок вызывает ``ask("individual", payload, schema)`` пакетами; ответ модели
сливается с сигналами правил, цитаты сверяются с текстом, серьёзность калибруется по TOML.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..criteria import SEVERITIES, STATUSES, Criteria, Criterion, load_criteria

__all__ = [
    "STAGE",
    "PROMPT_ID",
    "review_individual",
    "build_prompt",
    "response_schema",
    "prompt_version",
]

STAGE = "individual"
PROMPT_ID = "individual"

Ask = Callable[[str, dict, dict], Any]

_FLAGS = re.IGNORECASE | re.UNICODE
_WS = re.compile(r"[\s  ]+")
_GENERIC_PASS = re.compile(
    r"^\s*(?:ок|ok|да|соответствует|корректн\w*|замечаний нет|нет замечаний|без замечаний|"
    r"требование (?:корректно|соответствует)|всё в порядке|все в порядке)\s*\.?\s*$",
    _FLAGS,
)


# ---------------------------------------------------------------------------
# Доступ к объектам контракта (dict, dataclass или pydantic — без разницы)
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _norm_num(s: str) -> str:
    return re.sub(r"[\s  ]", "", s or "").replace(",", ".")


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _slug(s: str) -> str:
    return re.sub(r"[^\w]+", "_", (s or "").lower().replace("ё", "е"), flags=re.UNICODE).strip("_")


def _short(s: str, n: int = 160) -> str:
    s = _WS.sub(" ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Представление документа и требований
# ---------------------------------------------------------------------------

@dataclass
class _Block:
    id: str
    kind: str
    section: tuple[str, ...]
    text: str
    order: int


@dataclass
class _Doc:
    id: str
    title: str
    blocks: list[_Block]
    by_id: dict[str, _Block]

    @classmethod
    def of(cls, document: Any) -> "_Doc":
        blocks: list[_Block] = []
        for i, b in enumerate(_get(document, "blocks", []) or []):
            section = _get(b, "section", []) or []
            if isinstance(section, str):
                section = [section]
            blocks.append(
                _Block(
                    id=str(_get(b, "id", f"#{i}")),
                    kind=str(_get(b, "kind", "paragraph") or "paragraph"),
                    section=tuple(str(s) for s in section),
                    text=str(_get(b, "text", "") or ""),
                    order=i,
                )
            )
        return cls(
            id=str(_get(document, "id", "") or ""),
            title=str(_get(document, "title", "") or ""),
            blocks=blocks,
            by_id={b.id: b for b in blocks},
        )

    def neighbors(self, block: _Block, foreign: set[str]) -> list[_Block]:
        """Соседние строки того же раздела, не принадлежащие другим требованиям."""
        out = []
        for j in (block.order - 1, block.order + 1):
            if 0 <= j < len(self.blocks):
                nb = self.blocks[j]
                if nb.section == block.section and nb.kind != "heading" and nb.id not in foreign:
                    out.append(nb)
        return out

    def under(self, prefix: tuple[str, ...]) -> list[_Block]:
        n = len(prefix)
        return [b for b in self.blocks if b.section[:n] == prefix]

    def text_without(self, ids: set[str]) -> str:
        return "\n".join(b.text for b in self.blocks if b.id not in ids)


@dataclass
class _Span:
    block: _Block | None
    start: int
    end: int
    override: str = ""

    @property
    def text(self) -> str:
        return self.override if self.block is None else self.block.text[self.start : self.end]

    @property
    def block_id(self) -> str | None:
        return self.block.id if self.block else None


@dataclass
class _Req:
    id: str
    source_id: str | None
    text: str
    spans: list[_Span]
    section: tuple[str, ...]
    role: str
    level: str
    applicable: list[str]
    not_applicable: list[str]

    @property
    def label(self) -> str:
        return self.source_id or self.id

    @property
    def block_ids(self) -> list[str]:
        return [s.block_id for s in self.spans if s.block_id]

    @property
    def body(self) -> str:
        return "\n".join(s.text for s in self.spans)


def _make_req(obj: Any, idx: int, doc: _Doc, crit: Criteria, warnings: list[str]) -> _Req:
    rid = str(_get(obj, "id", "") or f"R{idx + 1}")
    text = str(_get(obj, "text", "") or "")
    spans: list[_Span] = []
    used: set[str] = set()
    for ev in _get(obj, "evidence", []) or []:
        b = doc.by_id.get(str(_get(ev, "block_id", "")))
        s, e, q = _get(ev, "start"), _get(ev, "end"), _get(ev, "quote")
        if b is None or not isinstance(s, int) or not isinstance(e, int):
            continue
        if 0 <= s < e <= len(b.text) and (q is None or b.text[s:e] == q):
            spans.append(_Span(b, s, e))
            used.add(b.id)
    for bid in _get(obj, "block_ids", []) or []:
        bid = str(bid)
        if bid in used:
            continue
        b = doc.by_id.get(bid)
        if b is None:
            warnings.append(f"individual.unknown_block: {rid} — блок {bid} отсутствует в документе")
            continue
        if text and text in b.text and len(text) < len(b.text):
            i = b.text.index(text)
            spans.append(_Span(b, i, i + len(text)))
        else:
            spans.append(_Span(b, 0, len(b.text)))
        used.add(bid)
    if not spans:
        spans.append(_Span(None, 0, len(text), override=text))
        warnings.append(f"individual.no_blocks: {rid} — у требования нет блоков документа, цитаты не привязаны к источнику")
    spans.sort(key=lambda sp: (sp.block.order if sp.block else 10**9, sp.start))
    section = spans[0].block.section if spans[0].block else tuple()
    role = crit.role_for(section)
    level = crit.level_for(section)
    req_criteria = crit.for_scope("requirement")
    return _Req(
        id=rid,
        source_id=_get(obj, "source_id"),
        text=text or "\n".join(s.text for s in spans),
        spans=spans,
        section=section,
        role=role,
        level=level,
        applicable=[c.code for c in req_criteria if c.applies(role)],
        not_applicable=[c.code for c in req_criteria if not c.applies(role)],
    )


# ---------------------------------------------------------------------------
# Сигналы детерминированных правил
# ---------------------------------------------------------------------------

@dataclass
class _Signal:
    criterion: str
    status: str
    reason: str
    rule: str
    kind: str
    strength: str = "heuristic"  # objective | heuristic
    block_id: str | None = None
    quote: str = ""
    context: str = ""
    severity: str | None = None
    severity_rule: str | None = None
    title: str = ""
    impact: str = ""
    condition: str = ""
    fix: str = ""
    question: str = ""
    root_cause: str = ""
    exclusive: bool = False  # пункт целиком не является требованием: прочие критерии na


_SENT_BOUND = re.compile(r"[.!?](?=[\s ]|$)|\n|\|")


def _sentence(text: str, pos: int, end: int | None = None) -> tuple[int, int]:
    a = 0
    for m in _SENT_BOUND.finditer(text, 0, pos):
        a = m.end()
    m = _SENT_BOUND.search(text, end if end is not None else pos)
    b = m.end() if m else len(text)
    return a, b


def _mask(text: str, crit: Criteria) -> str:
    """Скрыть пробелами цитаты, названия кнопок и экранов, примеры и речь клиента."""
    chars = list(text)

    def blank(a: int, b: int) -> None:
        for i in range(a, b):
            if chars[i] != "\n":
                chars[i] = " "

    for key in ("mask.quotes", "mask.example", "mask.speech"):
        rx = crit.patterns.get(key)
        if rx:
            for m in rx.finditer(text):
                blank(m.start(), m.end())
    rx = crit.patterns.get("mask.ui_label")
    if rx:
        for m in rx.finditer(text):
            if m.lastindex:
                blank(m.start(1), m.end(1))
    return "".join(chars)


_MEASURE_CACHE: dict[str, dict[str, re.Pattern[str]]] = {}


def _measure(crit: Criteria) -> dict[str, re.Pattern[str]]:
    hit = _MEASURE_CACHE.get(crit.fingerprint)
    if hit:
        return hit
    m = crit.raw.get("rules", {}).get("measure", {})
    timer = re.compile(
        rf"(?<![\w-])(?P<bound>{m['time_bound']})\s+(?:(?P<num>{m['number']})\s*(?P<unit>{m['time_units']})(?![\w])"
        rf"|(?P<word>{m['time_words']})(?![\w]))",
        _FLAGS,
    )
    start = re.compile(rf"(?<![\w-])(?:{m['time_start']})(?![\w-])[^.;,|\n]{{0,60}}", _FLAGS)
    out = {"timer": timer, "start": start, "quantity": crit.patterns["measure.quantity"]}
    _MEASURE_CACHE[crit.fingerprint] = out
    return out


def _timers(text: str, crit: Criteria) -> list[dict[str, str]]:
    rx = _measure(crit)
    found = []
    for m in rx["timer"].finditer(text):
        a, b = _sentence(text, m.start(), m.end())
        sent = text[a:b]
        st = rx["start"].search(sent)
        found.append({
            "text": m.group(0).strip(),
            "bound": m.group("bound"),
            "timer": (m.group("num") or "").strip() + (" " if m.group("num") else "") + (m.group("unit") or m.group("word") or ""),
            "start": st.group(0).strip() if st else "",
            "pos": str(m.start()),
            "sentence": sent.strip(),
        })
    return found


def _measurable(text: str, kind: str, crit: Criteria) -> str:
    t = _timers(text, crit)
    if t:
        return t[0]["text"] + (f" {t[0]['start']}" if t[0]["start"] else "")
    if kind == "quantity":
        m = _measure(crit)["quantity"].search(text)
        if m:
            return m.group(0).strip()
    return ""


_BULLET = re.compile(r"^\s*(?:[-+•*]\s+|\d+[.)]\s+)")


def _context_quote(text: str, a: int, b: int, crit: Criteria) -> str:
    """Предложение вокруг цитаты, буквальная подстрока блока (без маркера списка)."""
    sa, sb = _sentence(text, a, b)
    sent = text[sa:sb].strip(" |")
    sent = sent[_BULLET.match(sent).end():] if _BULLET.match(sent) else sent
    limit = int(crit.individual.get("max_quote_chars", 300))
    return sent if len(sent) <= limit else text[a:b]


def _rule_signals(req: _Req, doc: _Doc, crit: Criteria, owner: dict[str, str]) -> list[_Signal]:
    sigs: list[_Signal] = []
    applicable = set(req.applicable)
    foreign = {bid for bid, rid in owner.items() if rid != req.id}
    doc_text = doc.text_without(set(req.block_ids))

    def target(code: str, alt: str | None = None) -> str | None:
        if code in applicable:
            return code
        if alt and alt in applicable:
            return alt
        return None

    def sev(kind: str, field: str = "", group: str = "") -> tuple[str, str | None]:
        s, rule = crit.rule_severity(kind=kind, field=field, role=req.role, group=group, document_text=doc_text)
        return s, (rule.id if rule else None)

    def why(rule_id: str | None) -> str:
        for r in crit.severity_rules:
            if r.id == rule_id:
                return r.why
        return ""

    # 1. Строка шаблона («Да / Нет» вместо значения) — не требование.
    tmpl = crit.patterns.get("template.pattern")
    for sp in req.spans:
        if tmpl and tmpl.search(sp.text):
            sigs.append(_Signal(
                criterion="И4", status="na", rule="template", kind="template", strength="objective",
                block_id=sp.block_id, quote=tmpl.search(sp.text).group(0),
                reason="Строка шаблона с вариантами «Да / Нет» вместо значения: это незаполненный пункт чек-листа, а не требование. "
                       "Его заполненность оценивают проверка набора и чек-лист банка.",
                exclusive=True,
            ))
            return sigs

    body = req.body
    stripped = re.sub(r"[*_`|]", " ", body).strip()

    # 2. Пустой пункт или пустое значение.
    min_chars = int(crit.raw.get("rules", {}).get("empty", {}).get("min_chars", 12))
    label_only = crit.patterns.get("empty.label_only")
    c4 = target("И4")
    if c4:
        empty_hit: tuple[_Span, str, str] | None = None
        is_table = all("|" in sp.text for sp in req.spans)
        if not is_table and (len(_WS.sub(" ", stripped)) < min_chars or (label_only and label_only.match(stripped))):
            sp = req.spans[0]
            empty_hit = (sp, sp.text.strip() or sp.text, stripped or "(пусто)")
        elif is_table:
            for sp in req.spans:
                cells = [c.strip() for c in sp.text.strip().strip("|").split("|")]
                if not any(cells):
                    empty_hit = (sp, sp.text.strip() or sp.text, "строка таблицы")
                    break
                if len(cells) >= 2 and cells[0] and not any(cells[1:]):
                    empty_hit = (sp, cells[0], re.sub(r"[*_`]", "", cells[0]).strip())
                    break
        if empty_hit:
            sp, quote, label = empty_hit
            s, rid = sev("empty", field=label)
            sigs.append(_Signal(
                criterion=c4, status="issue", rule="empty", kind="empty", strength="objective",
                block_id=sp.block_id, quote=quote, context=sp.text.strip() if quote != sp.text.strip() else "",
                severity=s, severity_rule=rid,
                title=f"{req.label}: значение «{_short(label, 60)}» не заполнено",
                condition=f"В пункте «{_short(label, 60)}» нет содержания.",
                impact=why(rid) or "Обязательство не сформулировано.",
                fix=f"Заполнить «{_short(label, 60)}» или удалить строку, если она не нужна.",
                question=f"Что должно быть указано в «{_short(label, 60)}»?",
                reason=f"Пункт «{_short(label, 60)}» пуст: проверять нечего.",
                root_cause=f"empty:{_slug(label)}",
                exclusive=not is_table and len(_WS.sub(' ', stripped)) < min_chars,
            ))

    # 3. Заглушка («заполняются тестировщиками», «будет описано позже»).
    stub = crit.patterns.get("stub.pattern")
    if stub and c4:
        for sp in req.spans:
            m = stub.search(sp.text)
            if not m:
                continue
            rest = re.sub(r"[\W_]+", "", (sp.text[: m.start()] + sp.text[m.end():]))
            whole = len(rest) < 10
            s, rid = sev("stub")
            sigs.append(_Signal(
                criterion=c4, status="issue", rule="stub", kind="stub", strength="objective",
                block_id=sp.block_id, quote=m.group(0), context=_context_quote(sp.text, m.start(), m.end(), crit),
                severity=s, severity_rule=rid,
                title=f"{req.label}: вместо содержания заглушка «{m.group(0)}»",
                condition=f"Раздел «{req.section[-1] if req.section else req.label}» содержит только заглушку." if whole
                else f"Часть пункта заменена заглушкой «{m.group(0)}».",
                impact=why(rid) or "Поведение не описано.",
                fix="Заменить заглушку содержанием или явно указать, кто и к какому сроку его готовит.",
                question=f"Кто и к какому сроку заполнит «{req.section[-1] if req.section else req.label}»?",
                reason=f"Вместо требования стоит заглушка «{m.group(0)}»: что реализовать и проверить, не сказано.",
                root_cause=f"stub:{_slug(req.section[-1] if req.section else req.id)}",
                exclusive=whole,
            ))
            break

    # 4. Прочерк или маркер вместо значения.
    if c4:
        dash = crit.patterns.get("placeholder.dash_value")
        ok_fields = crit.patterns.get("placeholder.dash_ok_fields")
        tokens = crit.patterns.get("placeholder.tokens")
        for sp in req.spans:
            hits: list[tuple[int, int, str]] = []
            if dash:
                for m in dash.finditer(sp.text):
                    label = re.sub(r"[*_`]", "", m.group("label")).strip(" .")
                    sep = sp.text[m.end("label"): m.start("value")]
                    if "|" in sep and len([c for c in sp.text.strip().strip("|").split("|") if c.strip()]) > 2:
                        continue  # многоколоночная таблица: прочерк означает «не применяется»
                    if ok_fields and ok_fields.search(label):
                        continue
                    # «Request URL | Dev: … . Prod: —» → метка — последнее слово перед двоеточием
                    label = re.split(r"[.|;]", label)[-1].strip() or label
                    hits.append((m.start("value"), m.end("value"), label))
            if tokens:
                for m in tokens.finditer(sp.text):
                    a, _ = _sentence(sp.text, m.start())
                    hits.append((m.start(), m.end(), _short(sp.text[a:m.start()].strip(" :|*"), 40) or m.group(0)))
            for a, b, label in hits:
                # цитата — метка вместе с прочерком, чтобы №07 нашёл её однозначно
                qa = sp.text.rfind(label, 0, a) if label else -1
                while qa > 0 and sp.text[qa - 1] in "*_`":
                    qa -= 1
                quote = sp.text[qa:b] if qa >= 0 and a - qa < 80 else sp.text[a:b]
                s, rid = sev("placeholder", field=label)
                sigs.append(_Signal(
                    criterion=c4, status="issue", rule="placeholder", kind="placeholder", strength="objective",
                    block_id=sp.block_id, quote=quote, context=_context_quote(sp.text, a, b, crit),
                    severity=s, severity_rule=rid,
                    title=f"{req.label}: у поля «{label}» нет значения",
                    condition=f"Поле «{label}» заполнено прочерком или маркером «{sp.text[a:b]}».",
                    impact=why(rid) or "Значение придётся выбрать без владельца.",
                    fix=f"Указать значение «{label}» или написать «не применяется» с причиной.",
                    question=f"Какое значение у «{label}» и когда оно будет известно?",
                    reason=f"Значение «{label}» не задано («{sp.text[a:b]}»).",
                    root_cause=f"placeholder:{_slug(label)}",
                ))

    exclusive = any(s.exclusive for s in sigs)
    if exclusive:
        return sigs

    # 5. Неоперациональные слова с учётом контекста.
    owner_blocks = {sp.block_id for sp in req.spans}
    for sp in req.spans:
        if sp.block and sp.block.kind == "heading":
            continue  # заголовок интерфейса или раздела — не обязательство
        masked = _mask(sp.text, crit)
        neighbor_text = "\n".join(nb.text for nb in (doc.neighbors(sp.block, foreign) if sp.block else []) if nb.id not in owner_blocks)
        for group in crit.vague:
            code = target(group.criterion, group.alt_criterion)
            if not code:
                continue
            for strength, patterns in (("strong", group.strong), ("weak", group.weak)):
                for rx in patterns:
                    for m in rx.finditer(masked):
                        term = sp.text[m.start(): m.end()]
                        ctx = _context_quote(sp.text, m.start(), m.end(), crit)
                        resolved = ""
                        if group.resolve in ("time", "quantity"):
                            resolved = _measurable(body, group.resolve, crit) or _measurable(neighbor_text, group.resolve, crit)
                        if resolved:
                            sigs.append(_Signal(
                                criterion=code, status="pass", rule=f"vague.{group.id}", kind="vague",
                                block_id=sp.block_id, quote=term, context=ctx,
                                reason=f"Слово «{term}» уточнено измеримым ограничением «{resolved}» в том же пункте или соседней строке.",
                            ))
                            continue
                        s, rid = sev("vague", group=group.id)
                        if strength == "weak":
                            sigs.append(_Signal(
                                criterion=code, status="unknown", rule=f"vague.{group.id}", kind="vague",
                                block_id=sp.block_id, quote=term, context=ctx,
                                reason=f"«{term}» может задавать точное событие или неизмеримое ожидание ({group.title.lower()}); "
                                       "по тексту пункта это не решить.",
                                question=group.question,
                            ))
                            continue
                        if group.resolve == "none":
                            title = f"«{term}»: {group.title.lower()}"
                            condition = f"В обязательстве «{ctx}» выражение «{term}» оставляет состав или условие открытым."
                            reason = f"«{term}» — {group.title.lower()}: перечень или условие обязательства не закрыты."
                        else:
                            title = f"«{term}» не задаёт измеримого значения ({group.title.lower()})"
                            condition = f"В обязательстве «{ctx}» слово «{term}» не имеет числовой границы, и рядом её нет."
                            reason = f"«{term}» — {group.title.lower()}: измеримого ограничения нет ни в пункте, ни в соседних строках."
                        sigs.append(_Signal(
                            criterion=code, status="issue", rule=f"vague.{group.id}", kind="vague",
                            block_id=sp.block_id, quote=term, context=ctx, severity=s, severity_rule=rid,
                            title=title,
                            condition=condition,
                            impact=why(rid) or "Реализацию и тест придётся строить на догадке.",
                            fix=group.fix.format(term=term),
                            question=group.question,
                            reason=reason,
                            root_cause=f"vague:{group.id}:{_slug(term)[:5]}",
                        ))

    # 6. Срок: таймер, граница и точка отсчёта.
    c7 = target("И7")
    timers = _timers(body, crit)
    if c7 and timers:
        t = timers[0]
        if re.match(r"кажд|раз в|с периодом|с интервалом", t["bound"], _FLAGS):
            sigs.append(_Signal(
                criterion=c7, status="pass", rule="timing.period", kind="timing",
                reason=f"Период измерим: «{t['text']}». Тест фиксирует интервалы между событиями и сравнивает их с периодом.",
            ))
        elif t["start"]:
            sigs.append(_Signal(
                criterion=c7, status="pass", rule="timing", kind="timing",
                reason=f"Срок измерим: граница и длительность «{t['text']}», точка отсчёта «{t['start']}». "
                       "Тест фиксирует время точки отсчёта и наблюдаемого результата и сравнивает разницу с границей.",
            ))
        elif t["bound"].lower() not in ("за", "до"):  # «за 30 дней», «до 3 дней» бывают окном данных, а не сроком
            sp = next((x for x in req.spans if t["text"] in x.text), req.spans[0])
            pos = sp.text.find(t["text"])
            s, rid = sev("timing")
            sigs.append(_Signal(
                criterion=c7, status="issue", rule="timing.no_start", kind="timing",
                block_id=sp.block_id, quote=t["text"],
                context=_context_quote(sp.text, max(pos, 0), max(pos, 0) + len(t["text"]), crit),
                severity=s, severity_rule=rid,
                title=f"{req.label}: у срока «{t['text']}» нет точки отсчёта",
                condition=f"Срок «{t['text']}» задан, но не сказано, от какого события его считать.",
                impact=why(rid) or "Тестировщик выберет точку отсчёта сам.",
                fix=f"Дописать точку отсчёта: «{t['text']} после <уточнить у владельца: событие-старт>».",
                question="От какого события отсчитывается срок?",
                reason=f"Граница «{t['text']}» измерима, но точка отсчёта не названа.",
                root_cause=f"timing_no_start:{req.id}",
            ))

    # 7. Диапазон значений: границы и включённость.
    rng = crit.patterns.get("range.pattern")
    inc = crit.patterns.get("range.inclusive")
    exc = crit.patterns.get("range.exclusive")
    if rng:
        for sp in req.spans:
            for m in rng.finditer(_mask(sp.text, crit)):
                a_raw, b_raw = (m.group("a"), m.group("b")) if m.group("a") else (m.group("a2"), m.group("b2"))
                try:
                    a_val, b_val = int(_norm_num(a_raw)), int(_norm_num(b_raw))
                except (TypeError, ValueError):
                    continue
                if a_val >= b_val:
                    continue
                sa, sb = _sentence(sp.text, m.start(), m.end())
                sentence = sp.text[sa:sb]
                range_text = sp.text[m.start(): m.end()].strip()
                is_inc = bool(inc and inc.search(sentence))
                is_exc = bool(exc and exc.search(sentence))
                where = ""
                if not (is_inc or is_exc):
                    where = _range_resolution(doc, req, sp, a_val, b_val, crit)
                    is_inc = bool(where)
                tests = ""
                if is_inc:
                    tests = (f"граничные значения {_fmt_int(a_val - 1)} / {_fmt_int(a_val)} / {_fmt_int(b_val)} / {_fmt_int(b_val + 1)} "
                             "→ отказ / приём / приём / отказ")
                elif is_exc:
                    tests = (f"граничные значения {_fmt_int(a_val)} / {_fmt_int(a_val + 1)} / {_fmt_int(b_val - 1)} / {_fmt_int(b_val)} "
                             "→ отказ / приём / приём / отказ")
                if c7 and tests:
                    sigs.append(_Signal(
                        criterion=c7, status="pass", rule="range", kind="range",
                        reason=f"Диапазон «{range_text}» проверяется тестом: {tests}."
                               + (f" Включённость границ взята из «{where}»." if where else ""),
                    ))
                if m.group("a") and not (is_inc or is_exc):
                    code = target("И3")
                    if not code:
                        continue
                    s, rid = sev("range")
                    sigs.append(_Signal(
                        criterion=code, status="issue", rule="range.inclusivity", kind="range",
                        block_id=sp.block_id, quote=range_text, context=_context_quote(sp.text, m.start(), m.end(), crit),
                        severity=s, severity_rule=rid,
                        title=f"{req.label}: не сказано, входят ли границы «{range_text}»",
                        condition=f"Значения {_fmt_int(a_val)} и {_fmt_int(b_val)} можно принять или отклонить.",
                        impact=why(rid) or "Спорны два граничных значения.",
                        fix=f"Дописать «включительно» или «не включая» после «{range_text}».",
                        question=f"Допустимы ли сами значения {_fmt_int(a_val)} и {_fmt_int(b_val)}?",
                        reason=f"У диапазона «{range_text}» не указана включённость границ.",
                        root_cause=f"range:{a_val}-{b_val}",
                    ))

    # 8. Единичность: несколько независимых предложений-обязательств.
    singular_cfg = crit.raw.get("rules", {}).get("singular", {})
    c5 = target("И5")
    if c5 and req.role in set(singular_cfg.get("roles", [])):
        sentences = _sentences(body)
        if len(sentences) >= int(singular_cfg.get("min_sentences", 3)):
            sp = req.spans[0]
            quote = sp.text.strip()
            bullet = _BULLET.match(quote)
            quote = quote[bullet.end():] if bullet else quote
            if len(quote) > int(crit.individual.get("max_quote_chars", 300)):
                quote = sentences[0] if sentences[0] in sp.text else quote
            s, rid = sev("singular")
            sigs.append(_Signal(
                criterion=c5, status="issue", rule="singular", kind="singular",
                block_id=sp.block_id, quote=quote, severity=s, severity_rule=rid,
                title=f"{req.label}: {len(sentences)} обязательства в одном пункте",
                condition="Пункт содержит " + "; ".join(f"«{_short(x, 60)}»" for x in sentences) + ".",
                impact=why(rid) or "Трассировка и тесты по частям затруднены.",
                fix=f"Разбить {req.label} на {len(sentences)} пункта с отдельными идентификаторами.",
                reason=f"В пункте {len(sentences)} самостоятельных правила: каждое можно выполнить отдельно от остальных.",
                root_cause=f"singular:{req.id}",
            ))

    # 9. Уровень документа и проектные решения (И2).
    c2 = target("И2")
    design = crit.patterns.get("constraint.design_terms")
    if c2 and design:
        m = design.search(_mask(body, crit))
        if m:
            term = m.group(0)
            marker = crit.patterns.get("constraint.markers")
            mk = marker.search(body) if marker else None
            if req.level == "interface":
                sigs.append(_Signal(
                    criterion=c2, status="pass", rule="appropriate.level", kind="appropriate",
                    reason=f"Пункт из спецификации интерфейса: решение «{term}» здесь задаётся по уровню документа. "
                           f"{crit.level_note('interface')}",
                ))
            elif mk:
                sigs.append(_Signal(
                    criterion=c2, status="pass", rule="appropriate.constraint", kind="appropriate",
                    reason=f"Решение «{term}» задано как обязательное внешнее ограничение («{mk.group(0)}»), поэтому уместно в бизнес-требовании.",
                ))
            else:
                sigs.append(_Signal(
                    criterion=c2, status="unknown", rule="appropriate.design", kind="appropriate",
                    reason=f"В бизнес-требовании упомянуто проектное решение «{term}»; не сказано, обязательное ли это ограничение.",
                    question=f"«{term}» — обязательное ограничение (кем задано) или способ реализации на выбор команды?",
                ))
    return sigs


def _sentences(text: str) -> list[str]:
    body = re.sub(r"^[\s*_`|•-]*(?:[A-ZА-ЯЁ]{1,5}-?\d+(?:\.\d+)*)[.:)]?[*_`]*\s*", "", text.strip())
    parts = re.split(r"(?<=[.!?])[\s ]+(?=[«\"A-ZА-ЯЁ])", body)
    return [p.strip() for p in parts if len(re.sub(r"\W", "", p)) >= 8]


def _range_resolution(doc: _Doc, req: _Req, sp: _Span, a: int, b: int, crit: Criteria) -> str:
    """Найти явную включённость тех же границ в другом месте или общий признак в родительском разделе."""
    rng = crit.patterns["range.pattern"]
    inc = crit.patterns["range.inclusive"]
    own = set(req.block_ids)
    for blk in doc.blocks:
        if blk.id in own:
            continue
        for m in rng.finditer(blk.text):
            a_raw, b_raw = (m.group("a"), m.group("b")) if m.group("a") else (m.group("a2"), m.group("b2"))
            try:
                if int(_norm_num(a_raw)) != a or int(_norm_num(b_raw)) != b:
                    continue
            except (TypeError, ValueError):
                continue
            sa, sb = _sentence(blk.text, m.start(), m.end())
            if inc.search(blk.text[sa:sb]):
                return _short(re.sub(r"[*_`]", "", blk.text[sa:sb]).strip(" |-"), 120) + f" [{blk.id}]"
    parent = req.section[:-1] if len(req.section) > 1 else req.section
    for blk in doc.under(parent):
        if blk.id in own:
            continue
        mm = re.search(r"обе границы включ\w*|границы включ\w*", blk.text, _FLAGS)
        if mm:
            return _short(re.sub(r"[*_`]", "", blk.text).strip(" |-"), 120) + f" [{blk.id}]"
    return ""


# ---------------------------------------------------------------------------
# Промпт и схема ответа
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _template() -> tuple[dict[str, str], str, str, str]:
    raw = resources.files("bcc_review").joinpath("prompts", "individual.md").read_bytes()
    text = raw.decode("utf-8")
    front: dict[str, str] = {}
    if text.startswith("---"):
        _, fm, text = text.split("---", 2)
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                front[k.strip()] = v.strip().strip('"')
    sys_part, user_part = re.split(r"^## user\s*$", text, maxsplit=1, flags=re.M)
    sys_part = re.sub(r"^\s*## system\s*$", "", sys_part, flags=re.M).strip()
    version = f"{front.get('version', '0')}+{hashlib.sha256(raw).hexdigest()[:12]}"
    return front, sys_part, user_part.strip(), version


def prompt_version() -> str:
    """Версия промпта: версия из front matter + 12 символов SHA-256 файла."""
    return _template()[3]


@lru_cache(maxsize=1)
def _base_schema() -> dict[str, Any]:
    raw = resources.files("bcc_review").joinpath("prompts", "individual.schema.json").read_text("utf-8")
    return json.loads(raw)


def response_schema(criteria: Criteria | None = None) -> dict[str, Any]:
    """JSON-схема ответа модели; перечень кодов критериев берётся из того же конфига, что и правила."""
    crit = criteria or load_criteria()
    schema = copy.deepcopy(_base_schema())
    schema.pop("$comment", None)
    item = schema["properties"]["results"]["items"]["properties"]["checks"]["items"]
    item["properties"]["criterion"]["enum"] = crit.codes("requirement")
    return schema


_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _fill(template: str, values: Mapping[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"в промпте individual нет значения для {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER.sub(repl, template)


def _render_document(doc: _Doc, batch: Sequence[_Req], crit: Criteria) -> str:
    limit = int(crit.individual.get("full_document_chars", 60000))

    def render(blocks: Iterable[_Block]) -> str:
        lines, prev = [], None
        for b in blocks:
            if b.section != prev:
                lines.append(f"#### {' › '.join(b.section) or '(без раздела)'}")
                prev = b.section
            lines.append(f"[{b.id}] {b.text}")
        return "\n".join(lines)

    full = render(doc.blocks)
    if len(full) <= limit:
        return full
    prefixes = {(r.section[:-1] if len(r.section) > 1 else r.section) for r in batch}
    keep = [b for b in doc.blocks if any(b.section[: len(p)] == p for p in prefixes)]
    part = render(keep)
    note = f"(документ сокращён до родительских разделов проверяемых пунктов: {len(keep)} из {len(doc.blocks)} блоков)"
    return note + "\n" + part[:limit]


def _render_requirements(batch: Sequence[_Req], doc: _Doc, owner: dict[str, str]) -> str:
    out = []
    for r in batch:
        foreign = {bid for bid, rid in owner.items() if rid != r.id}
        nbs = []
        for sp in r.spans:
            if sp.block:
                nbs += [f"[{nb.id}] {_short(nb.text, 200)}" for nb in doc.neighbors(sp.block, foreign) if nb.id not in r.block_ids]
        out.append(
            f"- req_id: {r.id}; ID в документе: {r.source_id or '—'}; роль: {r.role}; уровень: {r.level}\n"
            f"  раздел: {' › '.join(r.section) or '—'}\n"
            f"  применимые критерии: {', '.join(r.applicable) or '—'}; неприменимые (ставь na): {', '.join(r.not_applicable) or '—'}\n"
            f"  блоки: {', '.join(r.block_ids) or '—'}\n"
            f"  текст: {r.body}\n"
            f"  соседние строки без своего ID: {'; '.join(nbs) or '—'}"
        )
    return "\n".join(out)


def _render_signals(batch: Sequence[_Req], signals: Mapping[str, list[_Signal]]) -> str:
    lines = []
    for r in batch:
        for s in signals.get(r.id, []):
            q = f" «{s.quote}»" if s.quote else ""
            sv = f", {s.severity}" if s.severity else ""
            lines.append(f"- {r.id} · {s.criterion} · {s.status}{sv} · {s.rule}{q}: {s.reason}")
    return "\n".join(lines) or "— сигналов нет —"


def _prompt_for(batch: Sequence[_Req], doc: _Doc, crit: Criteria, signals: Mapping[str, list[_Signal]],
                owner: dict[str, str]) -> dict[str, Any]:
    front, system_t, user_t, version = _template()
    values = {
        "criteria_tag": crit.tag,
        "prompt_version": f"{PROMPT_ID}/{version}",
        "criteria_table": crit.render_criteria("requirement"),
        "severity_rubric": crit.render_severity(),
        "roles": crit.render_roles(),
        "document": _render_document(doc, batch, crit),
        "requirements": _render_requirements(batch, doc, owner),
        "rule_signals": _render_signals(batch, signals),
        "codes": "{" + ", ".join(crit.codes("requirement")) + "}",
    }
    return {
        "prompt_id": PROMPT_ID,
        "prompt_version": f"{PROMPT_ID}/{version}",
        "criteria_tag": crit.tag,
        "criteria_fingerprint": crit.fingerprint,
        "system": _fill(system_t, values),
        "user": _fill(user_t, values),
        "req_ids": [r.id for r in batch],
        "temperature": 0,
    }


def build_prompt(document: Any, requirements: Sequence[Any], *, criteria: Criteria | None = None) -> dict[str, Any]:
    """Собрать промпт для всех требований одним пакетом (для отладки, логов и тестов)."""
    crit = criteria or load_criteria()
    warnings: list[str] = []
    doc = _Doc.of(document)
    reqs = [_make_req(r, i, doc, crit, warnings) for i, r in enumerate(requirements or [])]
    owner = _owners(reqs)
    signals = {r.id: _rule_signals(r, doc, crit, owner) for r in reqs}
    return _prompt_for(reqs, doc, crit, signals, owner)


def _owners(reqs: Sequence[_Req]) -> dict[str, str]:
    owner: dict[str, str] = {}
    for r in reqs:
        for bid in r.block_ids:
            owner.setdefault(bid, r.id)
    return owner


# ---------------------------------------------------------------------------
# Вызов модели
# ---------------------------------------------------------------------------

def _ask_model(reqs: Sequence[_Req], doc: _Doc, crit: Criteria, signals: Mapping[str, list[_Signal]],
               owner: dict[str, str], ask: Ask, warnings: list[str]) -> tuple[dict[str, dict[str, dict]], int]:
    size = max(1, int(crit.individual.get("batch_size", 20)))
    schema = response_schema(crit)
    answers: dict[str, dict[str, dict]] = {}
    calls = 0
    by_id = {r.id: r for r in reqs}
    for i in range(0, len(reqs), size):
        batch = reqs[i : i + size]
        payload = _prompt_for(batch, doc, crit, signals, owner)
        calls += 1
        try:
            resp = ask(STAGE, payload, schema)
        except Exception as exc:  # адаптер уже сделал повторы; здесь только деградация
            warnings.append(f"individual.ask_failed: пакет {', '.join(r.id for r in batch)} — {type(exc).__name__}: {_short(str(exc), 200)}")
            continue
        if isinstance(resp, str):
            try:
                resp = json.loads(resp)
            except json.JSONDecodeError:
                warnings.append(f"individual.bad_response: ответ модели не JSON для пакета {batch[0].id}…{batch[-1].id}")
                continue
        for item in _get(resp, "results", []) or []:
            rid = str(_get(item, "req_id", ""))
            if rid not in by_id or rid not in payload["req_ids"]:
                warnings.append(f"individual.unexpected_req: модель вернула оценку для неизвестного требования {rid!r}")
                continue
            per = answers.setdefault(rid, {})
            for chk in _get(item, "checks", []) or []:
                c = crit.resolve(_get(chk, "criterion"))
                status = str(_get(chk, "status", "") or "").lower()
                if c is None or c.scope != "requirement" or status not in STATUSES:
                    warnings.append(f"individual.bad_check: {rid} — неизвестный критерий или статус: {_get(chk, 'criterion')!r}/{status!r}")
                    continue
                if c.code in per:
                    continue
                per[c.code] = {k: _get(chk, k) for k in (
                    "status", "reason", "quote", "condition", "impact", "fix", "question",
                    "severity", "blocks", "scenario", "root_cause")}
                per[c.code]["status"] = status
        for r in batch:
            if r.id not in answers:
                warnings.append(f"individual.missing_answer: {r.id} — модель не вернула оценку; критерии без сигналов правил помечены unknown")
    return answers, calls


# ---------------------------------------------------------------------------
# Сверка цитат, калибровка, защита от выдуманных чисел
# ---------------------------------------------------------------------------

def _locate(quote: str, text: str) -> tuple[int, int] | None:
    if not quote:
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    words = [w for w in re.split(r"[\s  ]+", quote.strip().strip("…").strip()) if w]
    if not words:
        return None
    qmap = {"«": "[«»\"“”„]", "»": "[«»\"“”„]", '"': "[«»\"“”„]", "“": "[«»\"“”„]", "”": "[«»\"“”„]", "„": "[«»\"“”„]"}
    parts = ["".join(qmap.get(ch, re.escape(ch)) for ch in w) for w in words]
    rx = re.compile(r"[*_`]{0,3}[\s  *_`|]+[*_`]{0,3}".join(parts), _FLAGS)
    m = rx.search(text)
    return (m.start(), m.end()) if m else None


def _find_quote(quote: str, req: _Req, doc: _Doc) -> tuple[str | None, str] | None:
    """Буквальная цитата в блоках требования, затем в его разделе. → (block_id, literal)."""
    for sp in req.spans:
        loc = _locate(quote, sp.text)
        if loc:
            return sp.block_id, sp.text[loc[0]: loc[1]]
    for blk in doc.under(req.section) if req.section else []:
        loc = _locate(quote, blk.text)
        if loc:
            return blk.id, blk.text[loc[0]: loc[1]]
    return None


_NUM_UNIT = re.compile(
    r"(?<![\w<\-])(\d[\d   ]*(?:[.,]\d+)?)(\s*(?:%|мс|ms|сек\w*|секунд\w*|с\b|мин\w*|минут\w*|час\w*|дн\w*|день|"
    r"₸|тенге|тиын\w*|раз\w*|шаг\w*|rps|tps|запрос\w*|символ\w*))?",
    _FLAGS,
)


def _guard_numbers(text: str, known: set[str]) -> tuple[str, list[str]]:
    """Числа, которых нет в документе, превращаются в вопрос владельцу."""
    if not text:
        return text, []
    protected = [(m.start(), m.end()) for m in re.finditer(r"<[^<>]*>", text)]
    invented: list[str] = []
    out, last = [], 0
    for m in _NUM_UNIT.finditer(text):
        if any(a <= m.start() < b for a, b in protected):
            continue
        num = _norm_num(m.group(1)).rstrip(".")
        if num in known:
            continue
        token = m.group(0).strip()
        invented.append(token)
        out.append(text[last: m.start()])
        out.append(f"<уточнить у владельца: {token}?>")
        last = m.start() + len(m.group(0).rstrip())
    out.append(text[last:])
    return "".join(out), invented


def _known_numbers(doc: _Doc) -> set[str]:
    nums = set()
    for b in doc.blocks:
        for m in re.finditer(r"\d[\d   ]*(?:[.,]\d+)?", b.text):
            nums.add(_norm_num(m.group(0)).rstrip("."))
            for part in re.split(r"[\s  ]+", m.group(0).strip()):
                nums.add(_norm_num(part))
    return nums


def _calibrate(sev: str | None, ans: Mapping[str, Any], code: str, quotes: list[str], crit: Criteria) -> tuple[str, list[str]]:
    notes: list[str] = []
    pol = crit.severity_policy
    s = sev if sev in SEVERITIES else "major"
    if sev not in SEVERITIES:
        notes.append("серьёзность не указана моделью → major")
    blocks = (ans.get("blocks") or "").strip()
    scenario = (ans.get("scenario") or "").strip()
    if s == "critical":
        need = set(pol.get("critical_requires", []))
        ok = ("blocks" not in need or blocks in ("implement", "verify", "both")) and ("scenario" not in need or len(scenario) >= 10)
        if not ok:
            s = pol.get("critical_fallback", "major")
            notes.append(f"critical → {s}: нет конкретного сценария невозможности реализации или проверки (severity.policy.critical_requires)")
    if blocks == "none":
        lim = pol.get("no_block_max", "minor")
        if crit.rank(s) < crit.rank(lim):
            notes.append(f"{s} → {lim}: замечание не мешает ни реализации, ни проверке (severity.policy.no_block_max)")
            s = lim
    cap = crit.cap_for(code, quotes)
    if cap and crit.rank(s) < crit.rank(cap.max):
        notes.append(f"{s} → {cap.max}: предел {cap.id} — {cap.why}")
        s = cap.max
    return s, notes


# ---------------------------------------------------------------------------
# Сборка результата
# ---------------------------------------------------------------------------

class _Acc:
    def __init__(self) -> None:
        self.candidates: list[dict[str, Any]] = []
        self._n = 0

    def add(self, cand: dict[str, Any]) -> str:
        self._n += 1
        uid = f"_c{self._n}"
        cand["_uid"] = uid
        self.candidates.append(cand)
        return uid


def _cand_from_signal(req: _Req, s: _Signal, crit: Criteria) -> dict[str, Any]:
    sev = s.severity or "major"
    notes: list[str] = []
    cap = crit.cap_for(s.criterion, [s.quote])
    if cap and crit.rank(sev) < crit.rank(cap.max):
        notes.append(f"{sev} → {cap.max}: предел {cap.id}")
        sev = cap.max
    hint = {"block_id": s.block_id, "quote": s.quote}
    if s.context and s.context != s.quote:
        hint["context"] = s.context
    return {
        "scope": "requirement",
        "kind": "defect",
        "criterion": s.criterion,
        "severity": sev,
        "title": s.title,
        "impact": s.impact,
        "req_ids": [req.id],
        "hints": [hint] if s.block_id else [],
        "condition": s.condition,
        "fix": s.fix,
        "question": s.question,
        "root_cause": s.root_cause,
        "origin": "rules",
        "rule": s.rule,
        "severity_rule": s.severity_rule,
        "calibration": notes,
    }


def _cand_from_answer(req: _Req, code: str, ans: Mapping[str, Any], block_id: str | None, quote: str,
                      crit: Criteria, known: set[str]) -> dict[str, Any]:
    sev, notes = _calibrate(ans.get("severity"), ans, code, [quote], crit)
    fix, inv_fix = _guard_numbers(str(ans.get("fix") or ""), known)
    question = str(ans.get("question") or "")
    if inv_fix:
        extra = "Подтвердите значения, которых нет в документе: " + ", ".join(inv_fix) + "."
        question = f"{question} {extra}".strip()
        notes.append("числа из правки модели вынесены в вопрос владельцу: " + ", ".join(inv_fix))
    reason = str(ans.get("reason") or "")
    condition = str(ans.get("condition") or "")
    title = _short(condition or reason, 140)
    hint = {"block_id": block_id, "quote": quote}
    return {
        "scope": "requirement",
        "kind": "defect",
        "criterion": code,
        "severity": sev,
        "title": f"{req.label}: {title}" if title else f"{req.label}: замечание по {code}",
        "impact": str(ans.get("impact") or ""),
        "req_ids": [req.id],
        "hints": [hint] if block_id else [],
        "condition": condition,
        "fix": fix,
        "question": question,
        "root_cause": str(ans.get("root_cause") or ""),
        "origin": "llm",
        "blocks": ans.get("blocks") or None,
        "scenario": ans.get("scenario") or None,
        "calibration": notes,
    }


def _check(req: _Req, code: str, status: str, reason: str, origin: str, **extra: Any) -> dict[str, Any]:
    out = {"req_id": req.id, "criterion": code, "status": status, "reason": _WS.sub(" ", reason).strip(), "origin": origin}
    for k, v in extra.items():
        if v:
            out[k] = v
    return out


def _assemble(reqs: Sequence[_Req], doc: _Doc, crit: Criteria, signals: Mapping[str, list[_Signal]],
              answers: Mapping[str, dict[str, dict]] | None, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    asked = answers is not None
    answers = answers or {}
    acc = _Acc()
    checks: list[dict[str, Any]] = []
    known = _known_numbers(doc)
    role_titles = {r.id: r.title for r in crit.roles}

    for req in reqs:
        sigs = signals.get(req.id, [])
        excl = next((s for s in sigs if s.exclusive), None)
        model = answers.get(req.id)
        for c in crit.for_scope("requirement"):
            code = c.code
            own = [s for s in sigs if s.criterion == code]
            if excl is not None and not own:
                checks.append(_check(req, code, "na", f"Не оценивается: {excl.reason}", "rules"))
                continue
            if not c.applies(req.role):
                if model and model.get(code, {}).get("status") == "issue":
                    warnings.append(f"individual.na_overridden: {req.id}/{code} — модель оценила неприменимый критерий; ответ не учтён")
                checks.append(_check(
                    req, code, "na",
                    f"«{c.name}» не применяется к пункту с ролью «{role_titles.get(req.role, req.role)}» (criteria.toml, not_for).",
                    "config"))
                continue
            checks.append(_decide(req, c, own, model.get(code) if model else None, asked, model is not None,
                                  doc, crit, known, acc, warnings))

    return checks, acc.candidates


def _decide(req: _Req, c: Criterion, own: list[_Signal], ans: Mapping[str, Any] | None, asked: bool,
            answered: bool, doc: _Doc, crit: Criteria, known: set[str], acc: _Acc,
            warnings: list[str]) -> dict[str, Any]:
    code = c.code
    issues = [s for s in own if s.status == "issue"]
    objective = [s for s in issues if s.strength == "objective"]
    unknowns = [s for s in own if s.status == "unknown"]
    passes = [s for s in own if s.status == "pass"]
    na = [s for s in own if s.status == "na"]

    def rule_issue(extra: str = "", origin: str = "rules") -> dict[str, Any]:
        refs = [acc.add(_cand_from_signal(req, s, crit)) for s in issues]
        worst = min((s.severity or "major" for s in issues), key=crit.rank)
        reason = " ".join(dict.fromkeys(s.reason for s in issues)) + (f" {extra}" if extra else "")
        return _check(req, code, "issue", reason, origin, severity=worst, refs=refs,
                      question=next((s.question for s in issues if s.question), ""))

    if na and not issues:
        return _check(req, code, "na", na[0].reason, "rules")

    if ans is None:
        if issues:
            return rule_issue()
        prefix = ("Модель не вернула оценку по этому пункту. " if answered is False and asked
                  else "Модель не вернула оценку по этому критерию. " if asked else "")
        if unknowns:
            return _check(req, code, "unknown", prefix + " ".join(s.reason for s in unknowns), "rules",
                          question=unknowns[0].question)
        if passes and not asked:
            return _check(req, code, "pass", " ".join(dict.fromkeys(s.reason for s in passes)), "rules")
        if asked:
            local = (" Локальные правила: " + " ".join(dict.fromkeys(s.reason for s in passes))) if passes else ""
            return _check(req, code, "unknown", prefix + "Оценка не получена." + local, "rules", question=c.question)
        return _check(
            req, code, "unknown",
            f"Без модели не оценивается: локальные правила не дали сигналов по критерию «{c.name}».",
            "rules", question=c.question)

    status = ans.get("status")
    reason = str(ans.get("reason") or "").strip()

    if status == "issue":
        quote = str(ans.get("quote") or "").strip()
        found = _find_quote(quote, req, doc)
        if found:
            block_id, literal = found
            uid = acc.add(_cand_from_answer(req, code, ans, block_id, literal, crit, known))
            refs = [uid] + [acc.add(_cand_from_signal(req, s, crit)) for s in issues]
            cand = acc.candidates[-1 - len(issues)]
            origin = "rules+llm" if issues else "llm"
            return _check(req, code, "issue", reason or cand["title"], origin, severity=cand["severity"],
                          refs=refs, question=cand.get("question", ""))
        warnings.append(f"individual.quote_not_found: {req.id}/{code} — цитата модели не найдена в тексте: «{_short(quote, 80)}»")
        if issues:
            return rule_issue("Замечание модели отклонено: её цитата не найдена в тексте пункта.", origin="rules")
        return _check(
            req, code, "unknown",
            f"Модель сообщила о дефекте без буквальной цитаты из пункта («{_short(quote, 80) or 'цитата не указана'}»); "
            f"замечание не принято, нужна ручная проверка. Довод модели: {_short(reason, 200)}",
            "llm", question=str(ans.get("question") or c.question))

    if status == "pass":
        if objective:
            return rule_issue("Модель сочла пункт соответствующим, но значение в тексте буквально отсутствует.", origin="rules")
        if not reason or len(reason) < 20 or _GENERIC_PASS.match(reason):
            if passes:
                return _check(req, code, "pass", " ".join(s.reason for s in passes), "rules+llm")
            warnings.append(f"individual.generic_pass: {req.id}/{code} — положительная оценка модели без обоснования")
            return _check(req, code, "unknown", "Модель поставила соответствие без содержательного обоснования; оценка не принята.",
                          "llm", question=c.question)
        note = ""
        rejected = [s for s in issues if s.strength == "heuristic"]
        if rejected:
            note = " Сигнал правил отклонён моделью: " + ", ".join(f"«{s.quote}»" for s in rejected) + "."
        return _check(req, code, "pass", reason + note, "llm" if not passes else "rules+llm")

    if status == "unknown":
        if issues:
            return rule_issue(f"Модель не смогла оценить пункт: {_short(reason, 160)}" if reason else "")
        return _check(req, code, "unknown", reason or "Модель не смогла оценить пункт по имеющимся фактам.", "llm",
                      question=str(ans.get("question") or c.question))

    # status == "na"
    if objective:
        return rule_issue("Модель сочла критерий неприменимым, но значение в тексте буквально отсутствует.")
    return _check(req, code, "na", reason or "Модель сочла критерий неприменимым к пункту.", "llm")


def _merge_candidates(cands: list[dict[str, Any]], crit: Criteria) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Одна первопричина — одна кандидатура. Возвращает список и отображение uid → ref."""
    out: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    alias: dict[str, dict[str, Any]] = {}

    def overlap(a: dict, b: dict) -> bool:
        if not set(a["req_ids"]) & set(b["req_ids"]):
            return False
        for ha in a["hints"]:
            for hb in b["hints"]:
                if ha["block_id"] == hb["block_id"] and (ha["quote"] in hb["quote"] or hb["quote"] in ha["quote"]):
                    return True
        return False

    for c in cands:
        key = (c["criterion"], _slug(c.get("root_cause", ""))) if c.get("root_cause") else None
        target = by_key.get(key) if key else None
        if target is None:
            target = next((o for o in out if o["criterion"] == c["criterion"] and overlap(o, c)), None)
        if target is None:
            out.append(c)
            alias[c["_uid"]] = c
            if key:
                by_key[key] = c
            continue
        alias[c["_uid"]] = target
        if key and key not in by_key:
            by_key[key] = target
        for rid in c["req_ids"]:
            if rid not in target["req_ids"]:
                target["req_ids"].append(rid)
        seen = {(h["block_id"], h["quote"]) for h in target["hints"]}
        for h in c["hints"]:
            if (h["block_id"], h["quote"]) not in seen:
                target["hints"].append(h)
                seen.add((h["block_id"], h["quote"]))
        if crit.rank(c["severity"]) < crit.rank(target["severity"]):
            target["severity"] = c["severity"]
        origins = set(target["origin"].split("+")) | set(c["origin"].split("+"))
        target["origin"] = "+".join(sorted(origins))
        # текст модели содержательнее шаблона правила
        if c["origin"] == "llm" and target["origin"] != "llm":
            for k in ("title", "impact", "condition", "fix", "question", "blocks", "scenario"):
                if c.get(k):
                    target[k] = c[k]
        else:
            for k in ("impact", "condition", "fix", "question"):
                if not target.get(k) and c.get(k):
                    target[k] = c[k]
        target["calibration"] = list(dict.fromkeys(target.get("calibration", []) + c.get("calibration", [])))

    refs: dict[str, str] = {}
    for i, c in enumerate(out, 1):
        c["ref"] = f"IND-{i:03d}"
    for uid, c in alias.items():
        refs[uid] = c["ref"]
    for c in out:
        c.pop("_uid", None)
        for k in [k for k, v in c.items() if v is None]:
            c.pop(k)
    return out, refs


def review_individual(document: Any, requirements: Sequence[Any], ask: Ask | None = None, *,
                      criteria: Criteria | None = None) -> dict[str, Any]:
    """Оценить каждое требование по критериям из ``criteria.toml``.

    ``ask(stage, payload, schema)`` — транспорт движка; при ``None`` работают только правила.
    ``criteria`` — уже загруженный конфиг (по умолчанию пакетный ``criteria.toml``).
    """
    crit = criteria or load_criteria()
    warnings: list[str] = []
    doc = _Doc.of(document)
    reqs = [_make_req(r, i, doc, crit, warnings) for i, r in enumerate(requirements or [])]
    seen: set[str] = set()
    for r in reqs:
        if r.id in seen:
            warnings.append(f"individual.duplicate_req_id: {r.id} встречается несколько раз")
        seen.add(r.id)
    owner = _owners(reqs)
    signals = {r.id: _rule_signals(r, doc, crit, owner) for r in reqs}

    answers: dict[str, dict[str, dict]] | None = None
    calls = 0
    if ask is not None and reqs:
        answers, calls = _ask_model(reqs, doc, crit, signals, owner, ask, warnings)

    checks, cands = _assemble(reqs, doc, crit, signals, answers, warnings)
    candidates, refs = _merge_candidates(cands, crit)
    for chk in checks:
        if "refs" in chk:
            chk["refs"] = list(dict.fromkeys(refs[u] for u in chk["refs"] if u in refs))

    templates = [r.id for r in reqs if any(s.rule == "template" for s in signals[r.id])]
    if templates:
        warnings.append(f"individual.template_rows: {', '.join(templates)} — строки шаблона переданы как требования; все критерии na")

    return {
        "checks": checks,
        "candidates": candidates,
        "warnings": warnings,
        "meta": {
            "stage": STAGE,
            "mode": "rules_plus_llm" if ask is not None else "rules_only",
            "prompt_version": f"{PROMPT_ID}/{prompt_version()}",
            "criteria_version": crit.version,
            "criteria_fingerprint": crit.fingerprint,
            "criteria_tag": crit.tag,
            "calls": calls,
            "requirements": len(reqs),
        },
    }
