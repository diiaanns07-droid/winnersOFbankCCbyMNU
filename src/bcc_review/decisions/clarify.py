"""Уточняющие вопросы владельцу продукта (№08).

``build_questions(document, findings, ask) -> list[Question]``

Что делает:

1. Берёт только подтверждённые находки (``status == "confirmed"``) с опорами,
   которые совпадают с текстом документа. Находки «на проверку» и
   редакционные (оформление, дубль, атомарность, нумерация) вопросов не
   порождают: ответ владельца на них не меняет реализацию или приёмку.
2. Объединяет находки, которые закрываются одним ответом: пересекающиеся
   опоры в одном блоке (или явное объединение моделью, если у групп есть общее
   требование или блок).
3. Через ``ask("clarify", payload, schema)`` получает формулировку вопроса,
   трактовки, наблюдаемые результаты и правки «было → стало». Код проверяет
   каждую правку: ``old`` — точная и однозначная подстрока ``block.text``;
   ответ документа (``document_answer``) — дословная цитата; варианты
   различимы. Числа, которых нет в документе, помечаются и в редакцию не
   попадут (см. ``patches.propose_patch``).
4. Без модели или при сбое модели строит вопросы по правилам: для конфликта —
   два варианта из ``witness`` (исход A / исход B).
5. Ранжирует как очередь вопросов интервью InVision-U
   (``_compute_metric_priority``/``_select_question``): базовый приоритет из
   серьёзности, вида развилки и охвата, затем убывающая отдача за уже
   покрытые требования, у каждого вопроса — метка «почему выбран».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ._doc import (
    DocView, as_list, format_loc, get, invented_values, loc_lines, norm_text, option_letter, quantities,
    to_plain,
)

AskFn = Callable[[str, dict, dict], Any]

STAGE = "clarify"
OWNER_ROLES = ("PO", "архитектор", "QA", "ИБ")
SEVERITY_WEIGHT = {"critical": 100, "major": 40, "minor": 10}
FAMILY_WEIGHT = {"conflict": 15, "ambiguity": 10, "gap": 8, "feasibility": 8, "unverifiable": 6}
FAMILY_BLOCKS = {
    "conflict": ["разработку", "тестирование"],
    "ambiguity": ["разработку", "тестирование"],
    "gap": ["разработку"],
    "feasibility": ["разработку"],
    "unverifiable": ["тестирование", "приёмку"],
}
FAMILY_LABEL = {
    "conflict": "противоречие",
    "ambiguity": "неоднозначность",
    "gap": "пропуск",
    "feasibility": "осуществимость",
    "unverifiable": "непроверяемость",
}
MAX_GROUPS_PER_CALL = 6

CLARIFY_INSTRUCTIONS = """\
Ты помогаешь владельцу продукта принять решения по подтверждённым замечаниям
статического ревью ТЗ. Текст документа приложен: блоки помечены [b0012]. Во
входе — группы замечаний с цитатами. Для каждой группы, ответ на которую меняет
реализацию или приёмку, сформулируй один вопрос.

Правила:
1. situation — что именно в тексте допускает разные исходы. Опирайся на цитаты.
2. options — от 2 до 4 взаимоисключающих трактовок с id A, B, C, D. Для каждой:
   interpretation (что считаем верным), observable_result (что увидят клиент или
   тестировщик в конкретном сценарии из документа), consequences (что меняется
   в разработке и тестах). Наблюдаемые результаты вариантов должны различаться.
3. edits — минимальная правка текста под вариант: block_id и old — точная
   подстрока текста этого блока, new — новая формулировка. Меняй только нужное.
4. Не придумывай чисел, сроков, SLA, лимитов, сумм и процентов, которых нет в
   документе. Если варианту нужно новое значение, оставь edits пустым и напиши
   в consequences, какое значение должен дать владелец.
5. Если документ уже однозначно отвечает на вопрос в другом месте, заполни
   document_answer (block_id и дословная цитата) и сделай вариант A «привести
   фрагмент к источнику». Иначе document_answer = {"block_id": "", "quote": ""}.
6. author_intent_hypothesis — твоя догадка о намерении автора (или пустая
   строка). Это не решение.
7. owner: PO — бизнес-правило; архитектор — интеграция, API, НФТ; QA —
   проверяемость и приёмка; ИБ — безопасность, доступ, данные.
8. blocks — что блокирует отсутствие ответа: «разработку», «тестирование»,
   «приёмку».
9. Несколько групп объединяй в один вопрос (group_ids), только если один ответ
   закрывает их все. Группу без влияния на реализацию и приёмку перечисли в
   skipped с причиной.
10. Пиши по-русски, конкретно, без общих фраз.
11. Если противоречие между двумя фразами разных разделов, можно задать по вопросу
   на каждую сторону: target — {block_id, quote} фразы, о которой вопрос; правки
   вариантов такого вопроса меняют только эту фразу. Для вопроса обо всей группе
   target = {"block_id": "", "quote": ""}.
"""

BLOCK_LABELS = ("разработку", "тестирование", "приёмку")
_BLOCKS_RU = {"development": "разработку", "testing": "тестирование"}


def _strict(props: dict) -> dict:
    """Объект для structured outputs: все поля обязательны, лишних нет."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_SA = {"type": "array", "items": _S}

CLARIFY_SCHEMA: dict = _strict({
    "questions": {"type": "array", "items": _strict({
        "group_ids": _SA,
        "owner": {"type": "string", "enum": list(OWNER_ROLES)},
        "situation": _S,
        "prompt": _S,
        "why": _S,
        "blocks": {"type": "array", "items": {"type": "string", "enum": list(BLOCK_LABELS)}},
        "author_intent_hypothesis": _S,
        "document_answer": _strict({"block_id": _S, "quote": _S}),
        "target": _strict({"block_id": _S, "quote": _S}),
        "options": {"type": "array", "items": _strict({
            "id": _S,
            "label": _S,
            "interpretation": _S,
            "observable_result": _S,
            "consequences": _S,
            "edits": {"type": "array", "items": _strict({"block_id": _S, "old": _S, "new": _S})},
        })},
    })},
    "skipped": {"type": "array", "items": _strict({"group_id": _S, "reason": _S})},
})


# ---------------------------------------------------------------------------
# Модель
# ---------------------------------------------------------------------------


@dataclass
class Option:
    id: str
    label: str
    interpretation: str
    observable_result: str
    consequences: str = ""
    edits: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    origin: str = "llm"
    changes: list[dict] = field(default_factory=list)   # какая фраза меняется: раздел, строка, было → стало
    keeps: dict | None = None                           # фраза цели, которая при этом варианте не меняется
    acceptance: str = ""                                # влияние на приёмку (строка критерия, совпадает ли)
    intent: str = ""                                    # keep — фраза цели остаётся; rewrite — её заменит «Формулировка:»

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "interpretation": self.interpretation,
            "observable_result": self.observable_result, "consequences": self.consequences,
            "edits": [dict(e) for e in self.edits], "warnings": list(self.warnings),
            "origin": self.origin, "changes": [dict(c) for c in self.changes],
            "keeps": dict(self.keeps) if self.keeps else None, "acceptance": self.acceptance,
            "intent": self.intent,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "Option":
        return cls(
            id=str(get(d, "id")), label=str(get(d, "label") or ""),
            interpretation=str(get(d, "interpretation") or ""),
            observable_result=str(get(d, "observable_result") or ""),
            consequences=str(get(d, "consequences") or ""),
            edits=[dict(to_plain(e)) for e in as_list(get(d, "edits"))],
            warnings=[str(w) for w in as_list(get(d, "warnings"))],
            origin=str(get(d, "origin") or "llm"),
            changes=[dict(to_plain(c)) for c in as_list(get(d, "changes"))],
            keeps=to_plain(get(d, "keeps")), acceptance=str(get(d, "acceptance") or ""),
            intent=str(get(d, "intent") or ""),
        )


def format_edit(e: Any) -> str:
    """Правка строкой для Question.options и файла ответов: «Правка [b0006]: «было» → «стало»».

    Строку читает ``answers.parse_answers`` (формат №13 печатает варианты как есть),
    поэтому выбор буквы варианта в файле ответов сам несёт проверяемую правку."""
    bid = get(e, "block_id")
    return f"Правка [{bid}]: «{get(e, 'old')}» → «{get(e, 'new')}»" if bid else \
        f"Правка: «{get(e, 'old')}» → «{get(e, 'new')}»"


_SYNCED = ("id", "finding_ids", "prompt", "options", "affected_req_ids", "owner", "blocks", "situation",
           "why", "sources", "target", "hypothesis", "document_answer", "kind", "family", "severity",
           "priority", "rank_reason", "source_sha256", "status", "origin", "blocked_decision", "side",
           "counterpart_ids")


@dataclass(eq=False, repr=False)
class Question(dict):
    """Question v1. Это ``dict`` (движок кладёт его в Report.questions как есть,
    JSON и схема контракта видят обычный объект) с атрибутами №08 поверх.

    Содержимое словаря — :meth:`to_dict`; оно обновляется при присваивании
    атрибута и при вызове :meth:`sync` (после правки вложенных списков)."""

    id: str
    finding_ids: list[str]
    prompt: str
    options: list[Option]
    affected_req_ids: list[str]
    owner: str = "PO"
    blocks: list[str] = field(default_factory=list)
    situation: str = ""
    why: str = ""
    sources: list[dict] = field(default_factory=list)
    target: dict | None = None
    hypothesis: str | None = None
    document_answer: dict | None = None
    kind: str = "decision"
    family: str = "ambiguity"
    severity: str = "major"
    priority: float = 0.0
    rank_reason: str = ""
    source_sha256: str | None = None
    status: str = "open"
    origin: str = "llm"
    blocked_decision: str = ""
    side: dict | None = None                       # вопрос об одной стороне противоречия: её фраза
    counterpart_ids: list[str] = field(default_factory=list)  # вопросы о других сторонах того же противоречия

    def __post_init__(self) -> None:
        object.__setattr__(self, "_ready", True)
        self.sync()

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name in _SYNCED and self.__dict__.get("_ready"):
            self.sync()

    def sync(self) -> "Question":
        dict.clear(self)
        dict.update(self, self._contract())
        return self

    def __repr__(self) -> str:
        return f"Question(id={self.id!r}, finding_ids={self.finding_ids!r}, prompt={self.prompt!r})"

    def option(self, option_id: str | None) -> Option | None:
        for o in self.options:
            if o.id == option_id:
                return o
        return None

    def option_texts(self) -> list[str]:
        """Варианты строками — так их требует Question.options контракта v1.

        Каждая проверенная правка варианта дописана как «· Правка [block]: «…» → «…»»:
        экспорт №13 печатает эти строки в файл ответов, и по букве варианта
        ``parse_answers`` восстанавливает правку без доступа к отчёту."""
        out = []
        for o in self.options:
            text = f"{o.id}. {o.label} — {o.observable_result}"
            where = {(c.get("block_id"), c.get("old")): c for c in o.changes}
            for e in o.edits:
                if not e.get("invented") and "|" not in f"{e['old']}{e['new']}":
                    text += " · " + format_edit(e)
                    c = where.get((e.get("block_id"), e.get("old")))
                    if c:
                        text += f" ({c['section']}, строка {c['line']})"
            if not o.edits and o.keeps:
                verb = ("меняется по «Формулировка:»" if o.intent == "rewrite" else "текст не меняется")
                text += f" · {verb}: «{o.keeps['quote']}» ({o.keeps['section']}, строка {o.keeps['line']})"
            out.append(text)
        return out

    def to_dict(self) -> dict:
        """Question v1 (id, finding_ids, prompt, options: list[str], affected_req_ids)
        плюс поля №08; полные варианты с правками — в ``option_details``."""
        return self._contract()

    def _contract(self) -> dict:
        return {
            "id": self.id, "finding_ids": list(self.finding_ids), "prompt": self.prompt,
            "options": self.option_texts(),
            "affected_req_ids": list(self.affected_req_ids),
            "option_details": [o.to_dict() for o in self.options],
            "owner": self.owner, "blocked_decision": self.blocked_decision,
            "blocks": list(self.blocks), "situation": self.situation, "why": self.why,
            "sources": [dict(s) for s in self.sources],
            "target": dict(self.target) if self.target else None,
            "hypothesis": self.hypothesis,
            "document_answer": dict(self.document_answer) if self.document_answer else None,
            "kind": self.kind, "family": self.family, "severity": self.severity,
            "priority": self.priority, "rank_reason": self.rank_reason,
            "source_sha256": self.source_sha256, "status": self.status, "origin": self.origin,
            "side": dict(self.side) if self.side else None, "counterpart_ids": list(self.counterpart_ids),
        }

    @classmethod
    def from_dict(cls, d: Any) -> "Question":
        if isinstance(d, Question):
            return d
        return cls(
            id=str(get(d, "id")),
            finding_ids=[str(x) for x in as_list(get(d, "finding_ids"))],
            prompt=str(get(d, "prompt") or ""),
            options=_options_from(d),
            affected_req_ids=[str(x) for x in as_list(get(d, "affected_req_ids"))],
            owner=str(get(d, "owner") or "PO"),
            blocks=[str(x) for x in as_list(get(d, "blocks"))],
            situation=str(get(d, "situation") or ""), why=str(get(d, "why") or ""),
            sources=[dict(to_plain(s)) for s in as_list(get(d, "sources"))],
            target=to_plain(get(d, "target")), hypothesis=get(d, "hypothesis"),
            document_answer=to_plain(get(d, "document_answer")),
            kind=str(get(d, "kind") or "decision"), family=str(get(d, "family") or "ambiguity"),
            severity=str(get(d, "severity") or "major"),
            priority=float(get(d, "priority") or 0.0), rank_reason=str(get(d, "rank_reason") or ""),
            source_sha256=get(d, "source_sha256"), status=str(get(d, "status") or "open"),
            origin=str(get(d, "origin") or "llm"),
            blocked_decision=str(get(d, "blocked_decision") or ""),
            side=to_plain(get(d, "side")),
            counterpart_ids=[str(x) for x in as_list(get(d, "counterpart_ids"))],
        )


def _options_from(d: Any) -> list[Option]:
    details = as_list(get(d, "option_details"))
    if details:
        return [Option.from_dict(o) for o in details]
    out = []
    for i, o in enumerate(as_list(get(d, "options"))):
        if isinstance(o, str):  # чужой Question v1: только строки
            m = re.match(r"^\s*([A-F])[.)]\s*(.*)$", o)
            oid, text = (m.group(1), m.group(2)) if m else (chr(ord("A") + i), o)
            out.append(Option(id=oid, label=text, interpretation=text, observable_result=text, origin="external"))
        else:
            out.append(Option.from_dict(o))
    return out


# ---------------------------------------------------------------------------
# Находки
# ---------------------------------------------------------------------------


@dataclass
class _F:
    id: str
    status: str
    kind: str
    criterion: str
    severity: str
    title: str
    impact: str
    req_ids: list[str]
    evidence: list[dict]
    witness: dict | None
    needs_decision: bool | None
    blocks: list[str]
    blocked_decision: str
    raw: Any

    @classmethod
    def of(cls, f: Any) -> "_F":
        crit = get(f, "criterion")
        if isinstance(crit, (list, tuple)):
            crit = " ".join(str(c) for c in crit)
        return cls(
            id=str(get(f, "id")), status=str(get(f, "status") or ""),
            kind=str(get(f, "kind") or ""), criterion=str(crit or ""),
            severity=str(get(f, "severity") or "minor").lower(),
            title=str(get(f, "title") or ""), impact=str(get(f, "impact") or ""),
            req_ids=[str(r) for r in as_list(get(f, "req_ids"))],
            evidence=[dict(to_plain(e)) for e in as_list(get(f, "evidence"))],
            witness=to_plain(get(f, "witness")), needs_decision=get(f, "needs_decision"),
            blocks=[str(b) for b in as_list(get(f, "blocks"))],
            blocked_decision=str(get(f, "blocked_decision") or ""),
            raw=f,
        )


# Виды и критерии контракта v1 (contracts.FINDING_KINDS, INDIVIDUAL_CRITERIA, SET_CRITERIA).
# None — редакционная находка: ответ владельца не меняет реализацию или приёмку.
_KIND_FAMILY: dict[str, str | None] = {
    "conflict": "conflict", "ambiguity": "ambiguity", "unverifiable": "unverifiable",
    "incomplete": "gap", "omission": "gap", "infeasible": "feasibility", "incorrect": "ambiguity",
    "terminology": "ambiguity", "placeholder": "gap",
    "non_singular": None, "design_in_requirement": None, "traceability": None,
    "duplicate": None, "format": None,
}
_MINOR_EDITORIAL_KINDS = {"terminology", "placeholder"}  # при minor — правка текста, не развилка
_CRITERION_FAMILY: dict[str, str | None] = {
    "unambiguous": "ambiguity", "complete": "gap", "feasible": "feasibility",
    "verifiable": "unverifiable", "correct": "ambiguity",
    "set_consistent": "conflict", "set_complete": "gap", "set_feasible": "feasibility",
    "set_validatable": "unverifiable", "set_comprehensible": "ambiguity",
    "necessary": None, "appropriate": None, "singular": None, "conforming": None,
    "ranked": None, "modifiable": None, "traceable": None,
}

_EDITORIAL_KEYS = (
    "format", "style", "typo", "template", "placeholder", "conforming", "оформлен",
    "шаблон", "заглушк", "опечат", "numbering", "нумерац", "duplicate", "дубл",
    "singular", "atomic", "атомар", "единичн", "traceab", "прослежив", "priority",
    "ранжир", "necessary", "необходим", "modifiab", "модифицир",
)
_FAMILY_KEYS = (
    ("conflict", ("conflict", "contradict", "inconsisten", "consisten", "противореч", "несогласован", "согласован")),
    ("unverifiable", ("unverifiable", "verifiab", "testab", "непроверя", "проверяем")),
    ("feasibility", ("feasib", "осуществим", "реализуем")),
    ("ambiguity", ("ambigu", "vague", "undefined", "glossary", "неоднознач", "двусмысл", "размыт", "не определ", "термин")),
    ("gap", ("incomplete", "complete", "gap", "missing", "omission", "coverage", "неполн", "полнот", "пропуск", "отсутств", "не задан", "не указан", "покрыт")),
)
# Коды критериев из docs/task-analysis.md, раздел 3.
_CRITERION_CODES = {
    "И3": "ambiguity", "И4": "gap", "И6": "feasibility", "И7": "unverifiable", "И8": "conflict",
    "Н1": "gap", "Н2": "conflict", "Н3": "feasibility", "Н5": "unverifiable",
}
_ROLE_KEYS = (
    ("ИБ", ("безопас", "security", "токен", "token", "авториз", "authoriz", "персональн", "pii",
            "шифр", "encrypt", "утечк", "в логах", "фрод", "fraud", "секрет")),
    ("архитектор", ("api", "rest", "http", "интеграц", "integration", "архитект", "architect",
                    "нагруз", "производительн", "performance", "доступност", "availability",
                    "идемпотент", "idempot", "очеред", "queue", "нфт", "nfr", "latency")),
)


def decision_family(f: Any) -> str | None:
    """Вид развилки или None, если находка редакционная и вопроса не требует."""
    f = f if isinstance(f, _F) else _F.of(f)
    if f.needs_decision is False:
        return None
    if f.witness:
        return "conflict"
    kind = f.kind.lower()
    if kind in _KIND_FAMILY:
        fam = _KIND_FAMILY[kind]
        if fam and kind in _MINOR_EDITORIAL_KINDS and f.severity == "minor" and f.needs_decision is not True:
            return None
        if fam is None and f.needs_decision is True:
            return _CRITERION_FAMILY.get(f.criterion.lower()) or "ambiguity"
        return fam
    crit = f.criterion.lower().strip()
    if crit in _CRITERION_FAMILY:
        fam = _CRITERION_FAMILY[crit]
        return fam if fam or f.needs_decision is not True else "ambiguity"
    if any(k in kind for k in _EDITORIAL_KEYS) and f.needs_decision is not True:
        return None
    hay = f"{kind} {f.criterion.lower()}"
    for fam, keys in _FAMILY_KEYS:
        if any(k in hay for k in keys):
            return fam
    for code, fam in _CRITERION_CODES.items():
        if re.search(rf"(?<!\w){code}(?!\w)", f.criterion) or re.search(rf"(?<!\w){code}(?!\w)", f.kind):
            return fam
    if f.needs_decision is True:
        return "ambiguity"
    return None


def owner_role(f: _F, family: str) -> str:
    hay = f"{f.kind} {f.criterion} {f.title} {f.impact}".lower()
    for role, keys in _ROLE_KEYS:
        if any(k in hay for k in keys):
            return role
    if family == "unverifiable":
        return "QA"
    if family == "feasibility":
        return "архитектор"
    return "PO"


# ---------------------------------------------------------------------------
# Группы
# ---------------------------------------------------------------------------


@dataclass
class _Group:
    gid: str
    findings: list[_F]
    family: str
    severity: str

    @property
    def req_ids(self) -> list[str]:
        out: list[str] = []
        for f in self.findings:
            for r in f.req_ids:
                if r not in out:
                    out.append(r)
        return out

    @property
    def block_ids(self) -> set[str]:
        return {str(e["block_id"]) for f in self.findings for e in f.evidence}

    @property
    def finding_ids(self) -> list[str]:
        return [f.id for f in self.findings]


def _overlap(a: dict, b: dict) -> bool:
    if a.get("block_id") != b.get("block_id"):
        return False
    if a.get("start", 0) < b.get("end", 0) and b.get("start", 0) < a.get("end", 0):
        return True
    return norm_text(a.get("quote", "")) == norm_text(b.get("quote", ""))


def _group(items: list[tuple[_F, str]]) -> list[_Group]:
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if any(_overlap(a, b) for a in items[i][0].evidence for b in items[j][0].evidence):
                parent[find(j)] = find(i)
    clusters: dict[int, list[tuple[_F, str]]] = {}
    for i, it in enumerate(items):
        clusters.setdefault(find(i), []).append(it)
    groups: list[_Group] = []
    for n, members in enumerate(clusters.values(), start=1):
        sev = max((m[0].severity for m in members), key=lambda s: SEVERITY_WEIGHT.get(s, 0))
        fam = max((m[1] for m in members), key=lambda x: FAMILY_WEIGHT.get(x, 0))
        groups.append(_Group(f"G{n}", [m[0] for m in members], fam, sev))
    return groups


# ---------------------------------------------------------------------------
# Правки
# ---------------------------------------------------------------------------


def _all_positions(text: str, sub: str) -> list[int]:
    out, i = [], text.find(sub)
    while sub and i != -1:
        out.append(i)
        i = text.find(sub, i + 1)
    return out


def resolve_edit(doc: DocView, raw: Any, log: list[str], where: str = "") -> dict | None:
    """Правка модели {block_id, old, new} -> Edit с координатами из кода."""
    block_id, old, new = get(raw, "block_id"), get(raw, "old"), get(raw, "new")
    b = doc.block(block_id)
    if b is None:
        log.append(f"[edit_block_unknown] {where}: блок {block_id!r} не найден, правка отброшена")
        return None
    if not old:
        log.append(f"[edit_old_empty] {where}: пустой old в блоке {block_id}, правка отброшена")
        return None
    if new is None or old == new:
        return None
    hits = _all_positions(b.text, str(old))
    if not hits:
        log.append(f"[edit_old_not_found] {where}: «{old}» нет в блоке {block_id}, правка отброшена")
        return None
    occ = get(raw, "occurrence")
    if len(hits) > 1:
        if isinstance(occ, int) and 0 <= occ < len(hits):
            hits = [hits[occ]]
        else:
            log.append(f"[edit_old_ambiguous] {where}: «{old}» встречается в блоке {block_id} "
                       f"{len(hits)} раз, правка отброшена")
            return None
    start = hits[0]
    return {
        "block_id": b.id, "start": start, "end": start + len(old), "old": str(old),
        "new": str(new), "source_sha256": doc.id,
    }


_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$")


def removal_edit(doc: DocView, ev: dict) -> dict | None:
    """Правка-удаление предложения, если цитата — целое предложение блока и после
    удаления в блоке остаётся содержательный текст (или это отдельный абзац)."""
    b = doc.block(ev.get("block_id"))
    if b is None:
        return None
    s, e = int(ev["start"]), int(ev["end"])
    for m in _SENTENCE_RE.finditer(b.text):
        if m.start() <= s and e <= m.end():
            sentence = m.group(0)
            core = sentence.strip()
            if len(norm_text(ev["quote"])) < 0.8 * len(norm_text(core)):
                return None
            rest = (b.text[: m.start()] + b.text[m.end():]).strip()
            rest_wo_id = re.sub(r"^[\w\-]+\.\s*", "", rest)
            if not rest_wo_id and b.kind != "paragraph":
                return None
            return {
                "block_id": b.id, "start": m.start(), "end": m.end(), "old": sentence,
                "new": "", "source_sha256": doc.id, "origin": "rule",
            }
    return None


def _mark_invented(doc: DocView, opt: Option) -> None:
    allowed = [doc.full_text()]
    for e in opt.edits:
        bad = invented_values(e["new"], e["old"], allowed)
        if bad:
            e["invented"] = bad
            msg = (f"[invented_value] вариант {opt.id}: значения {', '.join(bad)} нет в документе — "
                   "правка попадёт в редакцию только со значением владельца")
            if msg not in opt.warnings:
                opt.warnings.append(msg)


# ---------------------------------------------------------------------------
# Сборка вопроса
# ---------------------------------------------------------------------------


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _source(doc: DocView, ev: dict, finding_id: str | None = None) -> dict:
    b = doc.block(ev["block_id"])
    out = {
        "block_id": ev["block_id"], "start": ev["start"], "end": ev["end"], "quote": ev["quote"],
        "loc": format_loc(b, ev["start"], ev["end"]),
    }
    if finding_id:
        out["finding_id"] = finding_id
    return out


def _sources(doc: DocView, g: _Group) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for f in sorted(g.findings, key=lambda f: -SEVERITY_WEIGHT.get(f.severity, 0)):
        evs = list(f.evidence)
        if f.witness:
            evs = [e for e in (f.witness.get("evidence_a"), f.witness.get("evidence_b")) if e] + evs
        for ev in evs:
            key = (ev.get("block_id"), ev.get("start"), ev.get("end"))
            if key in seen or not doc.verify_evidence(ev):
                continue
            seen.add(key)
            out.append(_source(doc, ev, f.id))
    return out


def _conflict_sides(doc: DocView, g: _Group) -> tuple[dict, dict, dict | None] | None:
    for f in g.findings:
        w = f.witness or {}
        a, b = w.get("evidence_a"), w.get("evidence_b")
        if a and b and doc.verify_evidence(a) and doc.verify_evidence(b):
            return a, b, w
    evs = [e for f in g.findings for e in f.evidence]
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            if a["block_id"] != b["block_id"]:
                return a, b, None
    return None


def _side_evidence(doc: DocView, g: _Group) -> list[dict]:
    """Опоры группы в разных разделах без witness — стороны одного противоречия.

    Только для находок о несогласованности (set_consistent, conflict, incorrect): у
    неоднозначности с опорами в двух местах («нет часового пояса») сторон нет."""
    if any(f.witness for f in g.findings):
        return []
    if not any(f.criterion.lower() == "set_consistent" or f.kind.lower() in ("conflict", "incorrect")
               for f in g.findings):
        return []
    out, seen_sections = [], set()
    for f in g.findings:
        for e in f.evidence:
            b = doc.block(e.get("block_id"))
            if b is None or not doc.verify_evidence(e) or b.section in seen_sections:
                continue
            seen_sections.add(b.section)
            out.append(e)
    return out if len(out) >= 2 else []


def _resolve_side(doc: DocView, g: _Group, raw: Any) -> dict | None:
    quote = str(get(raw, "quote") or "").strip()
    if not quote:
        return None
    for f in g.findings:
        for e in f.evidence:
            if norm_text(e["quote"]) == norm_text(quote) or (
                    get(raw, "block_id") == e["block_id"] and quote in e["quote"]):
                return e
    return doc.evidence(quote, str(get(raw, "block_id") or "") or None)


def _side_rule_options(doc: DocView, side: dict) -> list[Option]:
    sec, line = _place(doc, side["block_id"])
    q = side["quote"]
    return [
        Option(id="A", label="Оставить эту фразу как есть",
               interpretation=f"Фраза «{q}» (раздел «{sec}», строка {line}) верна.",
               observable_result=f"Действует правило «{_short(q, 90)}».",
               consequences="Противоречие снимается правкой другой стороны.", origin="rule", intent="keep"),
        Option(id="B", label="Изменить эту фразу",
               interpretation=f"Фраза «{q}» (раздел «{sec}», строка {line}) неверна.",
               observable_result=f"Вместо «{_short(q, 90)}» действует правило владельца.",
               consequences="Новый текст задайте строкой «Формулировка: …» — она заменит именно эту фразу. "
                            "Без неё решение сохранится, текст не изменится.", origin="rule", intent="rewrite"),
    ]


def _rule_options(doc: DocView, g: _Group) -> list[Option]:
    if g.family == "conflict":
        sides = _conflict_sides(doc, g)
        if sides:
            a, b, w = sides
            inp = (w or {}).get("input") or "сценарий из замечания"
            res_a = (w or {}).get("outcome_a") or f"Действует правило «{a['quote']}»"
            res_b = (w or {}).get("outcome_b") or f"Действует правило «{b['quote']}»"
            loc_a = format_loc(doc.block(a["block_id"]), a["start"], a["end"])
            loc_b = format_loc(doc.block(b["block_id"]), b["start"], b["end"])
            opts = []
            for oid, keep, keep_loc, drop, drop_loc, res in (
                ("A", a, loc_a, b, loc_b, res_a), ("B", b, loc_b, a, loc_a, res_b),
            ):
                rm = removal_edit(doc, drop)
                opts.append(Option(
                    id=oid, label=f"Верно «{_short(keep['quote'])}»",
                    interpretation=f"Действует фрагмент ({keep_loc}): «{keep['quote']}».",
                    observable_result=f"{inp}: {res}.",
                    consequences=(f"Фрагмент ({drop_loc}) «{_short(drop['quote'])}» противоречит "
                                  "выбору и должен быть удалён или переписан; тест-кейс сценария "
                                  f"ожидает: {res}."),
                    edits=[rm] if rm else [], origin="rule",
                ))
            return opts
    ev = next((e for f in g.findings for e in f.evidence), None)
    quote = ev["quote"] if ev else ""
    return [
        Option(
            id="A", label="Задать правило своей формулировкой",
            interpretation=f"Владелец задаёт однозначное правило или значение вместо «{_short(quote)}».",
            observable_result="Разработка и тест-кейсы опираются на правило владельца; "
                              "проверка даёт однозначный вердикт.",
            consequences="Нужна формулировка: ответьте своим текстом со строкой «Формулировка: …». "
                         "Без неё решение сохранится, но текст не изменится.",
            origin="rule",
        ),
        Option(
            id="B", label="Оставить как есть, риск принят",
            interpretation=f"Фрагмент «{_short(quote)}» не меняется, трактовку выбирает разработка.",
            observable_result="Поведение определит реализация; приёмка по этому месту не даст "
                              "однозначного вердикта.",
            consequences="Риск фиксируется в отчёте как принятый владельцем.",
            origin="rule",
        ),
    ]


def _distinct(options: list[Option]) -> bool:
    if len(options) < 2:
        return False
    sigs = set()
    for o in options:
        edits = tuple(sorted((e["block_id"], e["start"], e["end"], e["new"]) for e in o.edits))
        sigs.add((norm_text(o.observable_result), edits))
    results = {norm_text(o.observable_result) for o in options}
    return len(sigs) == len(options) and len(results) == len(options)


def _target(sources: list[dict], g: "_Group | None" = None) -> dict | None:
    """Цель правки по умолчанию («Формулировка:», правка варианта без указания места) —
    собственная опора ведущей находки, а не сторона A свидетеля конфликта."""
    if not sources:
        return None
    s = sources[0]
    if g is not None:
        lead = max(g.findings, key=lambda f: SEVERITY_WEIGHT.get(f.severity, 0))
        own = {(e.get("block_id"), e.get("start"), e.get("end")) for e in lead.evidence}
        s = next((x for x in sources if (x["block_id"], x["start"], x["end"]) in own), s)
    return {k: s[k] for k in ("block_id", "start", "end", "quote")}


_ACCEPT_RE = re.compile(r"приёмк|приемк|acceptance", re.I)


def _place(doc: DocView, block_id: str) -> tuple[str, int | None]:
    b = doc.block(block_id)
    if b is None:
        return "—", None
    lines = loc_lines(b.loc)
    return (b.section[-1] if b.section else doc.title or "—"), (lines[0] if lines else None)


def _is_acceptance(doc: DocView, block_id: str) -> bool:
    b = doc.block(block_id)
    return b is not None and any(_ACCEPT_RE.search(s) for s in b.section)


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[а-яёa-z]{5,}", norm_text(text))}


def _expected_cell(text: str) -> str:
    return text.split(" | ")[-1] if " | " in text else text


def _describe(doc: DocView, sources: list[dict], target: dict | None, o: Option) -> None:
    """Для сотрудника: какая фраза меняется при варианте и что это значит для приёмки."""
    o.changes = []
    for e in o.edits:
        sec, line = _place(doc, e["block_id"])
        o.changes.append({"block_id": e["block_id"], "section": sec, "line": line, "old": e["old"],
                          "new": e["new"], "acceptance": _is_acceptance(doc, e["block_id"])})
    o.keeps = None
    if not o.edits and target:
        sec, line = _place(doc, target["block_id"])
        o.keeps = {"block_id": target["block_id"], "section": sec, "line": line, "quote": target["quote"]}
    if not o.edits and o.intent == "rewrite" and target:
        rows = [b for b in doc.blocks if b.kind == "table_row" and _is_acceptance(doc, b.id)
                and len(_stems(target["quote"]) & _stems(b.text)) >= 2]
        o.acceptance = ("; ".join(f"сверьте критерий приёмки (строка {_place(doc, b.id)[1]}) «{_expected_cell(b.text)}» "
                                  "с вашей формулировкой" for b in rows[:2])
                        or "критерия приёмки на это правило нет — тест по вашей формулировке")
        return
    ac_changes = [c for c in o.changes if c["acceptance"]]
    if ac_changes:
        o.acceptance = "; ".join(f"меняется критерий приёмки (строка {c['line']}): «{c['old']}» → «{c['new']}»"
                                 for c in ac_changes)
        return
    rows = [s for s in sources if _is_acceptance(doc, s["block_id"])]
    if not rows and target:
        key = _stems(target["quote"])
        rows = [{"block_id": b.id, "quote": _expected_cell(b.text)} for b in doc.blocks
                if b.kind == "table_row" and _is_acceptance(doc, b.id) and len(key & _stems(b.text)) >= 2]
    has_ac = any(_is_acceptance(doc, b.id) for b in doc.blocks)
    if not rows:
        o.acceptance = (f"критерия приёмки на это правило нет — нужен тест: {o.observable_result}" if has_ac
                        else f"критериев приёмки в документе нет; проверка ожидает: {o.observable_result}")
        return
    want = quantities(o.observable_result)
    parts = []
    for r in rows[:2]:
        _, line = _place(doc, r["block_id"])
        cell = _expected_cell(doc.block(r["block_id"]).text) if doc.block(r["block_id"]) else r["quote"]
        have = quantities(cell)
        if want and want <= have:
            parts.append(f"критерий приёмки (строка {line}) «{cell}» совпадает с результатом варианта — тест не меняется")
        elif want and have:
            parts.append(f"критерий приёмки (строка {line}) ожидает «{cell}» — с этим вариантом он расходится, "
                         "его нужно переписать")
        else:
            parts.append(f"сверьте критерий приёмки (строка {line}) «{cell}» с результатом: {o.observable_result}")
    o.acceptance = "; ".join(parts)


def _label_sources(sources: list[dict], target: dict | None, g: "_Group", side: dict | None = None) -> None:
    own = {(e.get("block_id"), e.get("start"), e.get("end")) for f in g.findings for e in f.evidence}
    if side is not None:  # вопрос о стороне: остальные опоры группы — другая сторона
        own = {(side["block_id"], side["start"], side["end"])}
    for s in sources:
        key = (s["block_id"], s["start"], s["end"])
        if target and key == (target["block_id"], target["start"], target["end"]):
            s["role"] = "target"
        elif key not in own:
            s["role"] = "other_side"
        else:
            s["role"] = "evidence"


def _default_prompt(g: _Group) -> tuple[str, str, str]:
    f = max(g.findings, key=lambda f: SEVERITY_WEIGHT.get(f.severity, 0))
    situation = f.impact or f.title
    prompt = f"Как трактовать: {f.title}?" if f.title else "Какая трактовка верна?"
    why = f.impact or f"Без ответа {FAMILY_LABEL.get(g.family, g.family)} блокирует " + \
        " и ".join(FAMILY_BLOCKS.get(g.family, ["разработку"])) + "."
    return situation, prompt, why


def _assemble(doc: DocView, g: _Group, entry: dict | None, log: list[str],
              side: dict | None = None) -> Question:
    sources = _sources(doc, g)
    if side is not None:  # своя сторона — первой
        key = (side["block_id"], side["start"], side["end"])
        sources.sort(key=lambda x: (x["block_id"], x["start"], x["end"]) != key)
    lead = max(g.findings, key=lambda f: SEVERITY_WEIGHT.get(f.severity, 0))
    owner = owner_role(lead, g.family)
    situation, prompt, why = _default_prompt(g)
    # что блокируется: из находок движка (Finding.blocks), иначе по виду развилки
    engine_blocks = [_BLOCKS_RU[b] for b in ("development", "testing")
                     if any(b in f.blocks for f in g.findings)]
    blocks = engine_blocks or list(FAMILY_BLOCKS.get(g.family, ["разработку"]))
    blocked = "; ".join(dict.fromkeys(f.blocked_decision for f in g.findings if f.blocked_decision))
    hypothesis = None
    document_answer = None
    kind = "decision"
    options: list[Option] = []
    origin = "rule"
    if entry:
        where = f"группа {g.gid}"
        for i, raw in enumerate(as_list(entry.get("options"))):
            oid = option_letter(str(get(raw, "id") or "")) or chr(ord("A") + i)
            if any(o.id == oid for o in options):
                oid = chr(ord("A") + i)
            edits = []
            ok = True
            for e in as_list(get(raw, "edits")):
                r = resolve_edit(doc, e, log, f"{where}, вариант {oid}")
                if r is None and get(e, "old") != get(e, "new"):
                    ok = False
                elif r is not None and side is not None and r["block_id"] != side["block_id"]:
                    log.append(f"[edit_outside_side] {where}, вариант {oid}: правка «{_short(r['old'])}» вне фразы "
                               f"вопроса («{_short(side['quote'])}») — отброшена, она относится к другой стороне")
                elif r is not None:
                    edits.append(r)
            opt = Option(
                id=oid, label=str(get(raw, "label") or ""),
                interpretation=str(get(raw, "interpretation") or ""),
                observable_result=str(get(raw, "observable_result") or ""),
                consequences=str(get(raw, "consequences") or ""), edits=edits, origin="llm",
            )
            if not ok:
                opt.edits = []
                opt.warnings.append(f"[edit_rejected] вариант {oid}: правка модели не прошла проверку "
                                    "по тексту — нужна формулировка владельца")
            options.append(opt)
        if _distinct(options):
            origin = "llm"
            owner = entry.get("owner") if entry.get("owner") in OWNER_ROLES else owner
            situation = str(entry.get("situation") or situation)
            prompt = str(entry.get("prompt") or prompt)
            why = str(entry.get("why") or why)
            llm_blocks = [str(b) for b in as_list(entry.get("blocks")) if str(b) in BLOCK_LABELS]
            blocks = list(dict.fromkeys(engine_blocks + llm_blocks)) or blocks
            hyp = str(entry.get("author_intent_hypothesis") or "").strip()
            hypothesis = hyp or None
            da = entry.get("document_answer")
            if da and str(get(da, "quote") or "").strip():
                ev = doc.evidence(str(get(da, "quote") or ""), str(get(da, "block_id") or "")) \
                    if get(da, "block_id") else None
                if ev:
                    document_answer = _source(doc, ev)
                    kind = "align_to_source"
                else:
                    log.append(f"[document_answer_unverified] {where}: цитата «{_short(str(get(da, 'quote')))}» "
                               "не найдена дословно — показана как гипотеза")
                    extra = f"В документе, возможно, есть ответ: «{get(da, 'quote')}» (не подтверждено)."
                    hypothesis = f"{hypothesis} {extra}".strip() if hypothesis else extra
        else:
            log.append(f"[options_indistinct] {where}: варианты модели неразличимы или их меньше двух — "
                       "варианты построены по правилам")
            options = []
    if not options:
        options = _side_rule_options(doc, side) if side is not None else _rule_options(doc, g)
    if side is not None:
        target = {k: side[k] for k in ("block_id", "start", "end", "quote")}
        if not entry:
            sec, line = _place(doc, side["block_id"])
            prompt = f"Фраза «{_short(side['quote'], 90)}» (раздел «{sec}», строка {line}) — оставить или изменить?"
            others = [x for x in sources if (x["block_id"], x["start"], x["end"]) !=
                      (side["block_id"], side["start"], side["end"])]
            if others:
                situation = (f"{situation} Противоречие: «{_short(side['quote'], 90)}» ↔ "
                             f"«{_short(others[0]['quote'], 90)}». Этот вопрос — только о первой фразе.")
    else:
        target = _target(sources, g)
    _label_sources(sources, target, g, side)
    for o in options:
        _mark_invented(doc, o)
        _describe(doc, sources, target, o)
    return Question(
        id="", finding_ids=g.finding_ids, prompt=prompt, options=options,
        affected_req_ids=g.req_ids, owner=owner, blocks=blocks, situation=situation, why=why,
        sources=sources, target=target, hypothesis=hypothesis,
        document_answer=document_answer, kind=kind, family=g.family, severity=g.severity,
        source_sha256=doc.id, origin=origin, blocked_decision=blocked,
        side=dict(target) if side is not None else None,
    )


# ---------------------------------------------------------------------------
# Модель: вызов и разбор
# ---------------------------------------------------------------------------


def _group_payload(g: _Group) -> dict:
    return {
        "group_id": g.gid, "family": g.family, "severity": g.severity,
        "affected_req_ids": g.req_ids,
        "findings": [
            {
                "id": f.id, "kind": f.kind, "criterion": f.criterion, "severity": f.severity,
                "title": f.title, "impact": f.impact, "blocked_decision": f.blocked_decision,
                "req_ids": f.req_ids,
                "evidence": [{"block_id": e["block_id"], "quote": e["quote"]} for e in f.evidence],
                **({"witness": f.witness} if f.witness else {}),
            }
            for f in g.findings
        ],
    }


def build_payload(doc: DocView, groups: list[_Group]) -> dict:
    """Payload этапа по contracts/HANDOFF.md: task, input, context.

    Текст документа прикладывает движок (малый — целиком, большой — индекс и
    запрошенные блоки), поэтому здесь только группы и нужные блоки."""
    wanted = {bid for g in groups for bid in g.block_ids}
    return {
        "task": CLARIFY_INSTRUCTIONS,
        "input": {
            "document_id": doc.id,
            "document_title": doc.title,
            "groups": [_group_payload(g) for g in groups],
        },
        "context": {"mode": "auto", "block_ids": [b.id for b in doc.blocks if b.id in wanted]},
    }


def _call(ask: AskFn, doc: DocView, groups: list[_Group], log: list[str]) -> tuple[dict, dict, dict]:
    """-> (gid -> собственный вопрос модели, gid -> предложение объединить, gid -> причина пропуска).

    Собственный вопрос группы хранится отдельно от предложения объединить её с
    другими: если объединение не пройдёт проверку, группа получит свой вопрос."""
    own: dict[str, list[dict]] = {}
    merged: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for i in range(0, len(groups), MAX_GROUPS_PER_CALL):
        batch = groups[i: i + MAX_GROUPS_PER_CALL]
        try:
            resp = ask(STAGE, build_payload(doc, batch), CLARIFY_SCHEMA)
        except Exception as exc:  # сбой поставщика не должен ронять отчёт
            log.append(f"[llm_failed] этап clarify: {type(exc).__name__}: {exc} — вопросы по правилам")
            continue
        resp = to_plain(resp) or {}
        known = {g.gid for g in batch}
        for s in as_list(resp.get("skipped")):
            gid = str(get(s, "group_id"))
            if gid in known:
                skipped[gid] = str(get(s, "reason") or "")
        for entry in as_list(resp.get("questions")):
            gids = list(dict.fromkeys(str(x) for x in as_list(get(entry, "group_ids")) if str(x) in known))
            if not gids:
                continue
            entry = dict(entry)
            entry["group_ids"] = gids
            if len(gids) == 1:
                own.setdefault(gids[0], []).append(entry)
            else:
                for gid in gids:
                    merged.setdefault(gid, entry)
    return own, merged, skipped


# ---------------------------------------------------------------------------
# Ранжирование (по образцу очереди вопросов InVision-U)
# ---------------------------------------------------------------------------


def _base_priority(q: Question) -> float:
    p = SEVERITY_WEIGHT.get(q.severity, 0) + FAMILY_WEIGHT.get(q.family, 0)
    if q.owner == "PO":
        p += 10  # бизнес-развилки раньше технических при равной серьёзности
    p += 4 * min(len(q.affected_req_ids), 5)
    p += 3 * (len(q.finding_ids) - 1)
    if {"разработку", "тестирование"} <= set(q.blocks):
        p += 5
    if q.kind == "align_to_source":
        p -= 15  # ответ уже есть в документе: решение дешёвое, спрашиваем позже
    return float(p)


def rank(questions: list[Question], doc: DocView) -> list[Question]:
    def first_pos(q: Question) -> int:
        if q.side and doc.block(q.side["block_id"]):
            return doc.block(q.side["block_id"]).index
        idx = [doc.block(s["block_id"]).index for s in q.sources if doc.block(s["block_id"])]
        return min(idx) if idx else 10**9

    pool = list(questions)
    covered: set[str] = set()
    ordered: list[Question] = []
    while pool:
        scored = []
        for q in pool:
            base = _base_priority(q)
            overlap = len(set(q.affected_req_ids) & covered)
            scored.append((base - 6 * overlap, base, overlap, q))
        scored.sort(key=lambda t: (-t[0], first_pos(t[3]), t[3].finding_ids))
        adj, base, overlap, q = scored[0]
        reason = [q.severity, FAMILY_LABEL.get(q.family, q.family),
                  "блокирует " + " и ".join(q.blocks) if q.blocks else "",
                  f"требований {len(q.affected_req_ids)}", f"замечаний {len(q.finding_ids)}"]
        if q.owner == "PO":
            reason.append("бизнес-развилка")
        if overlap:
            reason.append(f"−{6 * overlap} за уже покрытые требования")
        if q.kind == "align_to_source":
            reason.append("ответ уже есть в документе")
        q.priority = adj
        q.rank_reason = " · ".join(r for r in reason if r)
        ordered.append(q)
        covered |= set(q.affected_req_ids)
        pool = [x for x in pool if x is not q]  # Question — dict: сравнение по идентичности
    for n, q in enumerate(ordered, start=1):
        q.id = f"Q-{n:02d}"
        for o in q.options:
            for e in o.edits:
                e["question_id"] = q.id
    for q in ordered:  # вопросы о сторонах одного противоречия ссылаются друг на друга
        if q.side:
            q.counterpart_ids = [x.id for x in ordered if x is not q and x.side and x.finding_ids == q.finding_ids]
    return ordered


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------


def build_questions(
    document: Any,
    findings: Iterable[Any],
    ask: AskFn | None = None,
    *,
    limit: int | None = None,
    warnings: list[str] | None = None,
) -> list[Question]:
    """Вопросы владельцу по подтверждённым находкам, самые важные первыми.

    ``warnings`` (необязательно) — список, куда пишутся причины отбраковки,
    отказы модели и отклонённые правки в виде «[код] пояснение».
    """
    doc = DocView(document)
    log = warnings if warnings is not None else []
    items: list[tuple[_F, str]] = []
    for raw in findings:
        f = _F.of(raw)
        if f.status != "confirmed":
            continue
        fam = decision_family(f)
        if fam is None:
            continue
        good = [e for e in f.evidence if doc.verify_evidence(e)]
        if len(good) < len(f.evidence):
            log.append(f"[evidence_mismatch] {f.id}: {len(f.evidence) - len(good)} опор не совпали с текстом")
        if not good:
            log.append(f"[no_evidence] {f.id}: нет подтверждённой опоры — вопрос не строится")
            continue
        f.evidence = good
        items.append((f, fam))
    groups = _group(items)
    own, proposals, skipped = (_call(ask, doc, groups, log) if ask and groups else ({}, {}, {}))

    questions: list[Question] = []
    used: set[str] = set()
    by_gid = {g.gid: g for g in groups}
    for g in groups:
        if g.gid in used:
            continue
        if g.gid in skipped and g.severity != "critical" and g.family != "conflict" \
                and g.gid not in own and g.gid not in proposals:
            log.append(f"[skipped_by_llm] {g.gid} ({', '.join(g.finding_ids)}): {skipped[g.gid]}")
            used.add(g.gid)
            continue
        entry: dict | None = None
        merged = g
        prop = proposals.get(g.gid)
        if prop:
            others = [by_gid[x] for x in prop["group_ids"] if x != g.gid and x not in used]
            bad = [o for o in others if not ((set(o.req_ids) & set(g.req_ids)) or (o.block_ids & g.block_ids))]
            if others and not bad:
                fs = g.findings + [f for o in others for f in o.findings]
                sev = max((x.severity for x in [g, *others]), key=lambda s: SEVERITY_WEIGHT.get(s, 0))
                fam = max((x.family for x in [g, *others]), key=lambda s: FAMILY_WEIGHT.get(s, 0))
                merged = _Group(g.gid, fs, fam, sev)
                used.update(o.gid for o in others)
                entry = prop
            else:
                for o in bad:
                    log.append(f"[merge_rejected] {g.gid}+{o.gid}: нет общего требования или блока — "
                               "вопросы остаются раздельными")
        entries = [] if entry is not None else own.get(g.gid, [])
        sided = [(e, _resolve_side(doc, merged, get(e, "target") or {})) for e in entries]
        sided = [(e, sd) for e, sd in sided if sd is not None]
        if entry is None and len({sd["block_id"] for _, sd in sided}) >= 2:
            used.add(g.gid)  # модель задала по вопросу на каждую сторону противоречия
            seen_blocks: set[str] = set()
            for e, sd in sided:
                if sd["block_id"] not in seen_blocks:
                    seen_blocks.add(sd["block_id"])
                    questions.append(_assemble(doc, merged, e, log, side=sd))
            continue
        if entry is None and entries:
            entry = entries[0]
        if ask and entry is None and g.gid not in skipped:
            log.append(f"[llm_missing_group] {g.gid}: модель не вернула вопрос — построен по правилам")
        used.add(g.gid)
        sides = _side_evidence(doc, merged) if entry is None else []
        if sides:  # без модели: по вопросу на каждую сторону противоречия
            for sd in sides:
                questions.append(_assemble(doc, merged, None, log, side=sd))
            continue
        questions.append(_assemble(doc, merged, entry, log))

    ordered = rank(questions, doc)
    for q in ordered:  # вложенные правки получили question_id — обновить словарь контракта
        q.sync()
    if limit is not None and len(ordered) > limit:
        rest = ordered[limit:]
        log.append("[queued] ниже порога очереди: " + ", ".join(
            f"{q.id} ({', '.join(q.finding_ids)})" for q in rest))
        ordered = ordered[:limit]
    return ordered
