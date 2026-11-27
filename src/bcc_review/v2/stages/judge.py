"""Судья v2 (№10): итоговый реестр дефектов, отклонённые кандидаты, чек-лист банка, текст вердикта.

Вход — кандидаты ``C-001…`` от линз, проверки набора и правил (цитаты уже сверены кодом).
Модель решает только три вещи: какие кандидаты — одна проблема, какие ложны и почему, какая
серьёзность и приоритет; плюс короткие тексты, чек-лист и обоснование вердикта.
Всё, что можно проверить кодом, делает код:

* предварительная кластеризация (тот же вид + те же требования + близкие строки, одно правило),
  при > 60 кандидатов — компактная подача кластера, чтобы уложиться в один вызов;
* деление пакета пополам, если ответ обрезан; запасной реестр без модели, если вызов не удался;
* каждый ``C-xxx`` ровно в одном месте; потерянных — повторный короткий вызов, затем в ``rejected``
  с причиной «не рассмотрен судьёй» и предупреждением;
* ``evidence`` и ``sources`` дефекта — из кандидатов (до 5 цитат, по порядку строк),
  ``standard_refs`` — по коду критерия (CONTRACT, раздел 4);
* шкала серьёзности: critical без сценария, последствий или с ``blocks = none`` понижается;
  виды, которые по шкале не бывают critical, понижаются; не больше 7 critical;
  «нет ID у пунктов» — одно minor на документ;
* приоритеты 1…7 без повторов, все critical — в «исправить первым»;
* вердикт по правилу кода (CONTRACT, раздел 5) — :func:`compute_verdict`.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any, Iterable

STAGE = "judge"

# --- справочники контракта ---------------------------------------------------------------------

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
SEVERITIES = ["critical", "major", "minor"]
BLOCKS = ["development", "testing", "both", "none"]
SEV_RANK = {"critical": 0, "major": 1, "minor": 2}

_ISO = "ISO/IEC/IEEE 29148:2018"
_IEEE = "IEEE 830-1998"
STANDARD_REFS: dict[str, list[str]] = {
    "necessary": [f"{_ISO} п. 5.2.5"],
    "appropriate": [f"{_ISO} п. 5.2.5"],
    "unambiguous": [f"{_ISO} п. 5.2.5", f"{_IEEE} п. 4.3.2"],
    "complete": [f"{_ISO} п. 5.2.5", f"{_IEEE} п. 4.3.3"],
    "singular": [f"{_ISO} п. 5.2.5"],
    "feasible": [f"{_ISO} п. 5.2.5"],
    "verifiable": [f"{_ISO} п. 5.2.5", f"{_IEEE} п. 4.3.6"],
    "correct": [f"{_ISO} п. 5.2.5", f"{_IEEE} п. 4.3.1"],
    "conforming": [f"{_ISO} п. 5.2.5"],
    "language": [f"{_ISO} п. 5.2.7"],
    "set_complete": [f"{_ISO} п. 5.2.6", f"{_IEEE} п. 4.3.3"],
    "set_consistent": [f"{_ISO} п. 5.2.6", f"{_IEEE} п. 4.3.4"],
    "set_feasible": [f"{_ISO} п. 5.2.6"],
    "set_comprehensible": [f"{_ISO} п. 5.2.6"],
    "set_validatable": [f"{_ISO} п. 5.2.6"],
    "ranked": [f"{_IEEE} п. 4.3.5"],
    "modifiable": [f"{_IEEE} п. 4.3.7"],
    "traceable": [f"{_IEEE} п. 4.3.8"],
    "risk": ["Чек-лист ревью требований банка"],
}

REJECT_REASONS = OrderedDict([
    ("misread", "неверное прочтение текста"),
    ("exact_sense", "слово использовано в точном измеримом смысле"),
    ("resolved_elsewhere", "проблема однозначно решена в другом месте документа"),
    ("unrelated", "утверждение не следует из процитированного текста"),
    ("out_of_scope", "вне предмета документа"),
    ("no_quote", "цитата не найдена в документе"),
    ("not_reviewed", "не рассмотрен судьёй"),
])
_MODEL_REJECT_CODES = ["misread", "exact_sense", "resolved_elsewhere", "unrelated", "out_of_scope"]

# По шкале (CONTRACT, раздел 5) эти виды — major или minor, но не critical.
NEVER_CRITICAL_KINDS = {"placeholder", "terminology", "traceability", "duplicate", "non_singular",
                        "design_constraint", "security", "ops_risk"}
NEVER_CRITICAL_CRITERIA = {"conforming", "language", "ranked", "modifiable", "traceable", "necessary",
                           "singular", "risk", "set_comprehensible"}

# Пропуск (critical по пункту «в») должен заметить больше одного ревьюера: «не описано» легко заявить ложно.
MISSING_KINDS = {"missing_element", "incomplete"}
MIN_SOURCES_FOR_CONSENSUS = 3  # правило действует, если в прогоне не меньше трёх разных источников

# Противоречие (critical по пункту «а» шкалы) доказывается цитатами двух разных мест.
CONFLICT_KINDS = {"event_conflict", "status_conflict", "boundary_conflict", "contradiction", "unit_mismatch"}

MAX_CRITICAL = 7
MAX_PRIORITY = 7
MAX_EVIDENCE = 5
COMPACT_THRESHOLD = 60       # больше кандидатов — компактная подача кластеров
MAX_SPLIT_DEPTH = 2          # пакет делится не более чем на 4 части
MAX_OUTPUT_TOKENS = 32000
CHECK_ANSWERS = ["Да", "Нет", "Частично", "Не требуется"]

# Стандартный чек-лист ревью требований банка (шаблон банка; хранится в коде, не в промпте).
# Пункт → критерии, по которым код заполняет пункт, если судья его пропустил.
BANK_CHECKLIST: list[tuple[str, tuple[str, ...]]] = [
    ("Техническое требование зафиксировано и покрывает бизнес-требование",
     ("set_complete", "traceable", "necessary")),
    ("Функциональная спецификация имеет структурированное описание (по стандарту, шаблону)",
     ("conforming", "set_comprehensible", "singular")),
    ("Sequence-диаграммы, предусмотрены взаимодействия систем, компонентов и решений",
     ("set_consistent", "set_complete")),
    ("Требование покрывает спецификацию UX/UI дизайна", ("complete",)),
    ("Реализация задачи/проекта предусматривает схему отката решений", ("feasible",)),
    ("Требование может быть протестировано", ("verifiable", "set_validatable")),
    ("Требование предусматривает модель данных или поток, содержит описание", ("complete", "set_complete")),
    ("Требование не имеет противоречий или явных показателей операционных рисков",
     ("set_consistent", "correct")),
    ("Требование содержит архитектуру и согласовано с архитекторами", ("appropriate", "set_feasible")),
    ("Все изменения, влияющие на иные продукты/системы в требовании, согласованы с ответственными лицами",
     ("traceable",)),
    ("Структура требований не несёт изменений и рисков информационной безопасности", ("risk",)),
    ("В требовании присутствует схема полного бизнес-процесса и часть реализуемой доработки",
     ("set_complete",)),
    ("Требование носит интеграционный характер и имеет четкую постановку реализации интеграционного "
     "взаимодействия", ("set_consistent", "complete")),
    ("Поддерживается версионность документа / зафиксирована", ("modifiable", "conforming")),
]
# Ключевые слова пункта чек-листа → критерии (для пунктов из таблицы самого документа).
_CHECK_HINTS: list[tuple[re.Pattern, tuple[str, ...], tuple[str, ...]]] = [
    # (шаблон пункта, критерии, виды)
    (re.compile(r"противореч|операционн", re.I), ("set_consistent", "correct"),
     ("contradiction", "event_conflict", "status_conflict", "boundary_conflict", "unit_mismatch", "ops_risk")),
    (re.compile(r"протестир|тестир|проверяем", re.I), ("verifiable", "set_validatable"), ("unverifiable",)),
    (re.compile(r"информационной безопасност|\bИБ\b", re.I), ("risk",), ("security",)),
    (re.compile(r"интеграци", re.I), ("set_consistent", "complete"), ("api_contract",)),
    (re.compile(r"модель данных|данных", re.I), ("complete", "set_complete"), ("missing_element",)),
    (re.compile(r"sequence|взаимодейств", re.I), ("set_consistent",), ("api_contract",)),
    (re.compile(r"отката|откат", re.I), ("feasible",), ("ops_risk",)),
    (re.compile(r"версион", re.I), ("modifiable",), ("placeholder",)),
    (re.compile(r"архитектур", re.I), ("appropriate", "set_feasible"), ("design_constraint",)),
    (re.compile(r"структурирован|шаблон|стандарт", re.I), ("conforming", "set_comprehensible"),
     ("non_singular", "terminology")),
    (re.compile(r"UX|UI|дизайн", re.I), ("complete",), ()),
    (re.compile(r"бизнес-процесс", re.I), ("set_complete",), ()),
    (re.compile(r"покрывает бизнес|бизнес-требован", re.I), ("set_complete", "traceable"), ("traceability",)),
    (re.compile(r"согласован", re.I), ("traceable",), ("traceability",)),
]

_NO_ID_RE = re.compile(
    r"(без|нет|отсутств\w*|не (?:имеют|имеет|присвоен\w*))\s+(?:\w+\s+){0,2}"
    r"(ID|идентификатор\w*|номер\w*|нумерац\w*)|не пронумерован|сквозн\w+ нумерац",
    re.I)

# --- схема ответа модели -----------------------------------------------------------------------


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else list(props)}


_S = {"type": "string"}
_SA = {"type": "array", "items": _S}


def response_schema() -> dict:
    """JSON Schema ответа судьи. Поля дефекта идут в порядке рассуждения: сначала место и суть,
    затем сценарий и последствия, и только потом серьёзность."""
    finding = _obj({
        "key": _S,
        "candidate_ids": _SA,
        "base": _S,
        "title": _S,
        "kind": {"type": "string", "enum": KINDS},
        "criterion": {"type": "string", "enum": CRITERIA},
        "requirement_ids": _SA,
        "problem": _S,
        "scenario": _S,
        "severity_basis": _S,
        "severity": {"type": "string", "enum": SEVERITIES},
        "blocks": {"type": "string", "enum": BLOCKS},
        "priority": {"type": "integer"},
    })  # impact, recommendation, rewrite, question — у кандидата base (короче ответ на слабых моделях)
    rejected = _obj({
        "candidate_id": _S,
        "reason_code": {"type": "string", "enum": _MODEL_REJECT_CODES},
        "reason": _S,
        "line": {"type": "integer"},
    })
    check = _obj({
        "n": {"type": "integer"},
        "answer": {"type": "string", "enum": CHECK_ANSWERS},
        "comment": _S,
        "finding_keys": _SA,
    })
    return _obj({
        "findings": {"type": "array", "items": finding},
        "rejected": {"type": "array", "items": rejected},
        "checklist": {"type": "array", "items": check},
        "verdict_summary": _S,
    })


def assign_schema() -> dict:
    """Схема короткого повторного вызова для кандидатов, которых судья пропустил."""
    item = _obj({
        "candidate_id": _S,
        "decision": {"type": "string", "enum": ["merge", "new", "reject"]},
        "finding_key": _S,
        "reason_code": _S,  # код причины при reject (проверяется кодом); иначе пустая строка
        "reason": _S,
        "title": _S,
        "severity": {"type": "string", "enum": SEVERITIES},
    })
    return _obj({"assignments": {"type": "array", "items": item}})


def check_schema() -> dict:
    """Схема второй проверки серьёзности (только понижение)."""
    item = _obj({
        "key": _S,
        "basis": _S,
        "severity": {"type": "string", "enum": SEVERITIES},
        "reason": _S,
    })
    return _obj({"checks": {"type": "array", "items": item}, "verdict_summary": _S})


# --- утилиты -----------------------------------------------------------------------------------


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def _cut(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", _s(text))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _norm_q(text: str) -> str:
    text = re.sub(r"[«»“”„\"'`*]", "", _s(text).lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def _words_cut(text: str, limit: int) -> str:
    words = _s(text).split()
    return " ".join(words) if len(words) <= limit else " ".join(words[:limit]).rstrip(",;:") + "…"


def _cid_num(cid: str) -> int:
    m = re.search(r"(\d+)", cid or "")
    return int(m.group(1)) if m else 10 ** 6


def _ev_line(ev: dict) -> int | None:
    for k in ("line_start", "line"):
        v = ev.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return None


def _ev_ok(ev: dict) -> bool:
    return _s(ev.get("verified")) != "missing" and _ev_line(ev) is not None and bool(_s(ev.get("quote")))


def _lines_of(c: dict) -> list[int]:
    out = sorted({n for n in (_ev_line(e) for e in c.get("evidence") or [] if _ev_ok(e)) if n})
    if not out and isinstance(c.get("line_start"), int) and c["line_start"] > 0:
        out = [c["line_start"]]
    return out


def _first_line(c: dict) -> int:
    ls = _lines_of(c)
    return ls[0] if ls else 10 ** 6


def _warn(ctx: Any, warnings: list[str], msg: str) -> None:
    warnings.append(msg)
    for name in ("warn", "warning", "add_warning"):
        fn = getattr(ctx, name, None)
        if callable(fn):
            try:
                fn(msg)
            except Exception:  # noqa: BLE001 — предупреждение не должно ронять этап
                pass
            return


def _rule_name(c: dict) -> str:
    src = _s(c.get("source"))
    return src.split(":", 1)[1] if src.startswith("rules:") else ""


# --- предварительная кластеризация ---------------------------------------------------------------


class _DSU:
    def __init__(self, items: Iterable[str]):
        self.p = {x: x for x in items}

    def find(self, x: str) -> str:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if _cid_num(ra) <= _cid_num(rb):
                self.p[rb] = ra
            else:
                self.p[ra] = rb


def _close_quotes(a: dict, b: dict) -> bool:
    """Близкие цитаты: общая строка (±1) или почти одинаковый текст цитаты."""
    la, lb = _lines_of(a), _lines_of(b)
    if any(abs(x - y) <= 1 for x in la for y in lb):
        return True
    qa = {_norm_q(e.get("quote")) for e in a.get("evidence") or [] if _ev_ok(e)}
    qb = {_norm_q(e.get("quote")) for e in b.get("evidence") or [] if _ev_ok(e)}
    return any(x and y and len(min(x, y, key=len)) >= 12 and (x in y or y in x) for x in qa for y in qb)


def _same_reqs(a: dict, b: dict) -> bool:
    ra, rb = set(a.get("requirement_ids") or []), set(b.get("requirement_ids") or [])
    if not ra or not rb:
        return not ra and not rb
    return ra == rb or len(ra & rb) / len(ra | rb) >= 0.5


def precluster(candidates: list[dict]) -> list[list[str]]:
    """Кластеры вероятных дублей: тот же ``kind`` + те же требования + близкие цитаты;
    сигналы одного правила одного вида — один кластер. Возвращает списки ID по порядку строк."""
    ids = [c["id"] for c in candidates]
    dsu = _DSU(ids)
    by_rule: dict[tuple[str, str], str] = {}
    for c in candidates:
        rule = _rule_name(c)
        if rule:
            key = (rule, _s(c.get("kind")))
            if key in by_rule:
                dsu.union(by_rule[key], c["id"])
            else:
                by_rule[key] = c["id"]
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if _s(a.get("kind")) == _s(b.get("kind")) and _same_reqs(a, b) and _close_quotes(a, b):
                dsu.union(a["id"], b["id"])
    groups: dict[str, list[str]] = {}
    for cid in ids:
        groups.setdefault(dsu.find(cid), []).append(cid)
    by_id = {c["id"]: c for c in candidates}
    out = [sorted(g, key=lambda x: (_first_line(by_id[x]), _cid_num(x))) for g in groups.values()]
    out.sort(key=lambda g: (min(_first_line(by_id[x]) for x in g), _cid_num(g[0])))
    return out


def _representative(group: list[str], by_id: dict[str, dict]) -> str:
    def score(cid: str) -> tuple:
        c = by_id[cid]
        return (SEV_RANK.get(_s(c.get("severity")), 3), 1 if _rule_name(c) else 0,
                -len(_lines_of(c)), -len(_s(c.get("scenario"))), _cid_num(cid))
    return min(group, key=score)


# --- подача кандидатов в промпт ---------------------------------------------------------------


_ORIGIN_RU = {"acceptance_check": "исполнение строки приёмки", "pair_check": "попарная сверка по сценарию",
              "glossary": "глоссарий"}


def _render_full(c: dict) -> str:
    lines = _lines_of(c)
    origin = _ORIGIN_RU.get(_s(c.get("origin")), "")
    head = " · ".join(x for x in [
        c["id"], _s(c.get("source")) or "?", origin, _s(c.get("severity")) or "?",
        f"{_s(c.get('kind'))}/{_s(c.get('criterion'))}",
        ", ".join(c.get("requirement_ids") or []) or "без требований",
        ("строки " + ", ".join(str(n) for n in lines)) if lines else "строки ?",
        f"blocks={_s(c.get('blocks')) or 'none'}",
    ] if x)
    out = [head, f"  title: {_cut(c.get('title'), 200)}"]
    for field, label, lim in (("problem", "problem", 420), ("scenario", "scenario", 320),
                              ("impact", "impact", 220)):
        if _s(c.get(field)):
            out.append(f"  {label}: {_cut(c.get(field), lim)}")
    quotes = [e for e in c.get("evidence") or [] if _ev_ok(e)][:3]
    if quotes:
        out.append("  цитаты: " + "; ".join(f"L{_ev_line(e):03d} «{_cut(e.get('quote'), 140)}»" for e in quotes))
    return "\n".join(out)


def _render_short(c: dict) -> str:
    lines = _lines_of(c)
    return (f"  + {c['id']} · {_s(c.get('source')) or '?'} · {_s(c.get('severity')) or '?'} · "
            f"строки {', '.join(str(n) for n in lines) or '?'} · {_cut(c.get('title'), 160)}")


def render_candidates(candidates: list[dict], clusters: list[list[str]], compact: bool) -> str:
    """Текст блока кандидатов. Кластер вероятных дублей помечен «Группа Gnn»; в компактном режиме
    полностью показан только представитель, остальные — одной строкой."""
    by_id = {c["id"]: c for c in candidates}
    blocks: list[str] = []
    for gi, group in enumerate(clusters, 1):
        if len(group) == 1:
            blocks.append(_render_full(by_id[group[0]]))
            continue
        rep = _representative(group, by_id)
        title = f"Группа G{gi:02d} (код считает вероятными дублями, проверь): {', '.join(group)}"
        if compact:
            body = [_render_full(by_id[rep])] + [_render_short(by_id[x]) for x in group if x != rep]
        else:
            body = [_render_full(by_id[x]) for x in group]
        blocks.append(title + "\n" + "\n".join(body))
    return "\n\n".join(blocks)


# --- чек-лист ---------------------------------------------------------------------------------


_YES_NO_RE = re.compile(r"\bДа\s*/\s*Нет\b", re.I)
_CHECK_HEAD_RE = re.compile(r"^\s*(проверка|пункт( чек-листа)?|критерий|вопрос|требование к ревью)\s*$", re.I)


def _cells(text: str) -> list[str]:
    t = _s(text).strip("|")
    return [x.strip() for x in t.split("|")] if "|" in t else []


def find_checklist(view: dict | None) -> list[dict]:
    """Пункты чек-листа ревью из таблицы самого документа: строки таблицы с ответом «Да / Нет» или
    таблица под заголовком «Проверка». Пусто — документ своего чек-листа не содержит."""
    lines = (view or {}).get("lines") or []
    items: list[dict] = []
    in_table = False
    for ln in lines:
        text = _s(ln.get("text"))
        cells = _cells(text)
        if not cells:
            in_table = False
            continue
        if _CHECK_HEAD_RE.match(cells[0]):
            in_table = True
            continue
        first = cells[0]
        if len(first) < 8 or set(first) <= set(":- "):
            continue
        if _YES_NO_RE.search(text) or (in_table and len(cells) >= 2):
            items.append({"item": first, "line": ln.get("n")})
    # чек-лист — это хотя бы 4 пункта; иначе это случайная таблица
    seen: set[str] = set()
    uniq = [x for x in items if not (x["item"] in seen or seen.add(x["item"]))]
    return uniq if len(uniq) >= 4 else []


def checklist_items(view: dict | None) -> tuple[list[str], str]:
    """Пункты чек-листа и их источник: ``document`` (таблица в документе) или ``bank`` (шаблон банка)."""
    doc = find_checklist(view)
    if doc:
        return [x["item"] for x in doc], "document"
    return [x for x, _ in BANK_CHECKLIST], "bank"


def _check_hints(item: str) -> tuple[set[str], set[str]]:
    for text, crit in BANK_CHECKLIST:
        if _norm_q(text) == _norm_q(item):
            kinds: set[str] = set()
            for rx, _c, k in _CHECK_HINTS:
                if rx.search(item):
                    kinds |= set(k)
                    break
            return set(crit), kinds
    crit_set: set[str] = set()
    kinds_set: set[str] = set()
    for rx, c, k in _CHECK_HINTS:
        if rx.search(item):
            crit_set |= set(c)
            kinds_set |= set(k)
            break
    return crit_set, kinds_set


def _auto_check(item: str, findings: list[dict]) -> dict:
    """Пункт чек-листа, заполненный кодом по найденным дефектам (если судья пункт пропустил)."""
    crit, kinds = _check_hints(item)
    related = [f for f in findings if f["criterion"] in crit or f["kind"] in kinds]
    if not crit and not kinds:
        return {"item": item, "answer": "Частично", "finding_ids": [],
                "comment": "Пункт не оценён судьёй; связь с найденными дефектами не установлена."}
    if not related:
        return {"item": item, "answer": "Да", "finding_ids": [],
                "comment": "Дефектов по этому пункту не найдено."}
    worst = min(SEV_RANK[f["severity"]] for f in related)
    ids = [f["id"] for f in sorted(related, key=lambda f: (SEV_RANK[f["severity"]], f["id"]))][:5]
    answer = "Нет" if worst <= 1 else "Частично"
    return {"item": item, "answer": answer, "finding_ids": ids,
            "comment": _words_cut(f"Связанные дефекты: {', '.join(ids)}.", 30)}


# --- вызов модели -----------------------------------------------------------------------------


def _is_truncation(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    kind = _s(getattr(exc, "kind", "")).lower()
    return ("trunc" in name or "max_tokens" in msg or "обрез" in msg or "truncat" in msg
            or kind in {"truncated", "max_tokens"})


def _requirements_of(ctx: Any) -> list[dict]:
    reqs = getattr(ctx, "requirements", None)
    if isinstance(reqs, dict):
        reqs = reqs.get("requirements")
    return list(reqs or [])


def _option(ctx: Any, name: str, default: Any) -> Any:
    opts = getattr(ctx, "options", None)
    if isinstance(opts, dict):
        return opts.get(name, default)
    return getattr(opts, name, default) if opts is not None else default


def _view_of(ctx: Any) -> dict:
    view = getattr(ctx, "view", None)
    return view if isinstance(view, dict) else {}


def _checklist_block(items: list[str], source: str) -> str:
    head = ("Пункты чек-листа ревью из самого документа (таблица без отметок):" if source == "document"
            else "В документе нет своего чек-листа ревью; заполни стандартный чек-лист ревью банка:")
    return head + "\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


def _build_messages(ctx: Any, block: str, checklist: str, n_candidates: int, compact: bool,
                    part: str = "") -> tuple[str, str]:
    stats = (f"Кандидатов: {n_candidates}." + (" Кандидатов много: в группах полностью показан один "
             "представитель, остальные — одной строкой; распредели и их." if compact else "") + part)
    prompt = getattr(ctx, "prompt", None)
    if callable(prompt):
        return prompt(STAGE, candidates=block, checklist=checklist, stats=stats)
    # без каркаса (тест, отладка): system — пустой, user — шаблон с подстановками
    from pathlib import Path
    tpl = (Path(__file__).resolve().parents[1] / "prompts" / "judge.md").read_text(encoding="utf-8")
    user = tpl.replace("{{candidates}}", block).replace("{{checklist}}", checklist).replace("{{stats}}", stats)
    return "", user


def _ask(ctx: Any, system: str, user: str, schema: dict) -> dict:
    llm = getattr(ctx, "llm", None)
    if llm is None:
        raise RuntimeError("модель недоступна")
    try:
        data = llm.ask(STAGE, system, user, schema, max_output_tokens=MAX_OUTPUT_TOKENS)
    except TypeError:
        data = llm.ask(STAGE, system, user, schema)
    missing = [k for k in schema.get("required") or [] if not isinstance(data, dict) or k not in data]
    if missing:  # ответ не по схеме этапа — это сбой вызова, а не пустой реестр
        raise ValueError(f"ответ модели без полей {', '.join(missing)}")
    return data


def _call_judge(ctx: Any, cands: list[dict], clusters: list[list[str]], checklist: str,
                warnings: list[str], depth: int = 0, part: str = "") -> list[dict]:
    """Один вызов судьи на пакет кластеров; при обрезке ответа — деление пополам (кластеры не рвём).
    Возвращает список ответов (по одному на часть)."""
    compact = len(cands) > COMPACT_THRESHOLD
    block = render_candidates(cands, clusters, compact)
    system, user = _build_messages(ctx, block, checklist, len(cands), compact, part)
    try:
        return [_ask(ctx, system, user, response_schema())]
    except Exception as exc:  # noqa: BLE001
        if not (_is_truncation(exc) and depth < MAX_SPLIT_DEPTH and len(clusters) > 1):
            raise
        mid = _split_point(clusters, cands)
        _warn(ctx, warnings, f"судья: ответ обрезан, пакет из {len(cands)} кандидатов делится на две части")
        by_id = {c["id"]: c for c in cands}
        out: list[dict] = []
        for k, part_cl in enumerate((clusters[:mid], clusters[mid:]), 1):
            ids = [x for g in part_cl for x in g]
            note = f" Это часть {k} из 2 пакета кандидатов; остальные кандидаты будут оценены отдельно."
            out += _call_judge(ctx, [by_id[x] for x in ids], part_cl, checklist, warnings, depth + 1, note)
        return out


def _split_point(clusters: list[list[str]], cands: list[dict]) -> int:
    total = len(cands)
    acc = 0
    for i, g in enumerate(clusters):
        acc += len(g)
        if acc >= total / 2:
            return max(1, min(i + 1, len(clusters) - 1))
    return max(1, len(clusters) // 2)


# --- сборка реестра ---------------------------------------------------------------------------


def _merge_responses(parts: list[dict]) -> dict:
    """Ответы частей пакета → один ответ: ключи дефектов делаются уникальными, чек-лист — худший ответ."""
    if len(parts) == 1:
        return parts[0]
    findings: list[dict] = []
    rejected: list[dict] = []
    checks: dict[int, dict] = {}
    summaries: list[str] = []
    order = {"Нет": 0, "Частично": 1, "Да": 2, "Не требуется": 3}
    for pi, resp in enumerate(parts, 1):
        remap: dict[str, str] = {}
        for f in resp.get("findings") or []:
            key = f"P{pi}{_s(f.get('key')) or len(findings) + 1}"
            remap[_s(f.get("key"))] = key
            findings.append({**f, "key": key})
        rejected += list(resp.get("rejected") or [])
        for ch in resp.get("checklist") or []:
            n = ch.get("n")
            ch = {**ch, "finding_keys": [remap.get(k, k) for k in ch.get("finding_keys") or []],
                  "comment": _replace_keys(_s(ch.get("comment")), remap)}
            prev = checks.get(n)
            if prev is None:
                checks[n] = ch
            else:
                worse = ch if order.get(ch.get("answer"), 9) < order.get(prev.get("answer"), 9) else prev
                checks[n] = {**worse, "finding_keys": list(dict.fromkeys(
                    (prev.get("finding_keys") or []) + (ch.get("finding_keys") or [])))}
        if _s(resp.get("verdict_summary")):
            summaries.append(_replace_keys(_s(resp["verdict_summary"]), remap))
    return {"findings": findings, "rejected": rejected, "checklist": list(checks.values()),
            "verdict_summary": summaries[0] if summaries else "", "_parts": len(parts)}


def _pick_evidence(members: list[dict], base: dict | None) -> list[dict]:
    """До 5 цитат: по одной на строку (предпочтение — базовому кандидату и точному совпадению),
    при избытке строк — строки базового кандидата и чаще всего цитируемые; итог по порядку строк."""
    per_line: dict[int, dict] = {}
    votes: dict[int, int] = {}
    base_lines: set[int] = set(_lines_of(base)) if base else set()
    rank = {"exact": 0, "normalized": 1, "fuzzy": 2}
    for c in ([base] if base else []) + [m for m in members if m is not base]:
        for ev in c.get("evidence") or []:
            if not _ev_ok(ev):
                continue
            n = _ev_line(ev)
            votes[n] = votes.get(n, 0) + 1
            cur = per_line.get(n)
            cand = {
                "quote": _s(ev.get("quote")),
                "line_start": n,
                "line_end": ev.get("line_end") if isinstance(ev.get("line_end"), int) and ev["line_end"] >= n else n,
                "page": ev.get("page"),
                "section": _s(ev.get("section")),
                "verified": _s(ev.get("verified")) or "exact",
            }
            if cur is None or rank.get(cand["verified"], 3) < rank.get(cur["verified"], 3):
                per_line[n] = cand
    lines = sorted(per_line)
    if len(lines) > MAX_EVIDENCE:
        lines = sorted(lines, key=lambda n: (n not in base_lines, -votes.get(n, 0), n))[:MAX_EVIDENCE]
        lines.sort()
    return [per_line[n] for n in lines]


def _text(f: dict, base: dict | None, field: str, limit: int) -> str:
    val = _s(f.get(field))
    if not val and base is not None:
        val = _s(base.get(field))
    return _cut(val, limit)


def _sources(members: list[dict]) -> list[str]:
    return list(dict.fromkeys(_s(m.get("source")) for m in members if _s(m.get("source"))))


def _valid_reqs(ids: Iterable[str], known: set[str]) -> list[str]:
    out = [i for i in (_s(x) for x in ids) if i and (not known or i in known)]
    return list(dict.fromkeys(out))


def _source_family(src: str) -> str:
    return "rules" if src.startswith("rules:") else src


def _calibrate(f: dict, members: list[dict], ctx: Any, warnings: list[str], run_sources: int = 0) -> None:
    """Защита шкалы серьёзности кодом (CONTRACT, раздел 5)."""
    if f["severity"] == "critical":
        why = ""
        if f["kind"] in NEVER_CRITICAL_KINDS:
            why = f"вид {f['kind']} по шкале не бывает critical"
        elif f["criterion"] in NEVER_CRITICAL_CRITERIA:
            why = f"критерий {f['criterion']} по шкале не бывает critical"
        elif not f["scenario"] or not f["impact"]:
            why = "нет сценария или последствий"
        elif f["blocks"] == "none":
            why = "дефект ничего не блокирует"
        elif f["kind"] in CONFLICT_KINDS and len({e["line_start"] for e in f["evidence"]}) < 2:
            why = "противоречие подтверждено цитатой только одного места"
        elif (f["kind"] in MISSING_KINDS and run_sources >= MIN_SOURCES_FOR_CONSENSUS
              and len({_source_family(_s(m.get("source"))) for m in members}) < 2):
            why = "пропуск заметил только один ревьюер"
        if why:
            f["severity"] = "major"
            _warn(ctx, warnings, f"судья: {f['title'][:60]!r} понижен до major ({why})")
    if f["severity"] != "minor" and f["criterion"] in {"conforming", "ranked"} and _NO_ID_RE.search(
            f["title"] + " " + f["problem"]):
        f["severity"] = "minor"
    if f["severity"] == "minor":
        f["blocks"] = "none"


def _merge_no_id(findings: list[dict], ctx: Any, warnings: list[str]) -> list[dict]:
    """«Нет ID у пунктов» — одно minor на документ: такие дефекты сливаются в один."""
    hits = [f for f in findings if f["criterion"] in {"conforming", "ranked", "traceable"}
            and _NO_ID_RE.search(f["title"])]
    if len(hits) < 2:
        return findings
    main = hits[0]
    for f in hits[1:]:
        main["candidate_ids"] += [x for x in f["candidate_ids"] if x not in main["candidate_ids"]]
        main["_members"] += f["_members"]
        main["requirement_ids"] = list(dict.fromkeys(main["requirement_ids"] + f["requirement_ids"]))
    main["severity"] = "minor"
    _warn(ctx, warnings, f"судья: {len(hits)} замечания об отсутствии ID сведены в одно")
    drop = {id(f) for f in hits[1:]}
    return [f for f in findings if id(f) not in drop]


def _cap_critical(findings: list[dict], ctx: Any, warnings: list[str]) -> None:
    crit = [f for f in findings if f["severity"] == "critical"]
    if len(crit) <= MAX_CRITICAL:
        return
    crit.sort(key=lambda f: (f["priority"] if f["priority"] > 0 else 99, -len(f["candidate_ids"]),
                             f["_first_line"]))
    for f in crit[MAX_CRITICAL:]:
        f["severity"] = "major"
    _warn(ctx, warnings, f"судья: critical {len(crit)} > {MAX_CRITICAL}; "
                         f"{len(crit) - MAX_CRITICAL} наименее приоритетных понижены до major")


def _assign_priorities(findings: list[dict]) -> None:
    """priority 1…7 без повторов: сначала то, что указал судья, затем недостающие critical."""
    for f in findings:  # minor ничего не блокирует — в «исправить первым» не идёт
        if f["severity"] == "minor":
            f["priority"] = 0
    chosen = [f for f in findings if f["priority"] > 0]
    chosen.sort(key=lambda f: (f["priority"], SEV_RANK[f["severity"]], f["_first_line"]))
    crit_missing = [f for f in findings if f["severity"] == "critical" and f["priority"] <= 0]
    crit_missing.sort(key=lambda f: f["_first_line"])
    # critical всегда в «исправить первым»: вытесняют самые поздние не-critical
    order = chosen + crit_missing
    order.sort(key=lambda f: (0 if f["severity"] == "critical" else 1,
                              f["priority"] if f["priority"] > 0 else 99, f["_first_line"]))
    top = [f for f in order if f["severity"] == "critical"][:MAX_PRIORITY]
    top_ids = {id(f) for f in top}
    rest = [f for f in chosen if id(f) not in top_ids]
    rest.sort(key=lambda f: (f["priority"], SEV_RANK[f["severity"]], f["_first_line"]))
    top += rest[: MAX_PRIORITY - len(top)]
    # итоговый порядок: как поставил судья, critical без номера — после своих
    top.sort(key=lambda f: (f["priority"] if f["priority"] > 0 else 50 + f["_first_line"] / 1e6,
                            SEV_RANK[f["severity"]]))
    keep = {id(f) for f in top}
    for f in findings:
        if id(f) not in keep:
            f["priority"] = 0
    for i, f in enumerate(top, 1):
        f["priority"] = i


_SEV_ADJ = {"critical": ("критичный", "критичные", "критичных"),
            "major": ("существенный", "существенные", "существенных"),
            "minor": ("незначительный", "незначительные", "незначительных")}
_SEV_WORD_RE = re.compile(r"\b(critical|major|minor)(?:[- ](дефект|замечание|дефекты|замечания|дефектов|замечаний)\b)?",
                          re.I)


def _sev_sub(m: re.Match) -> str:
    one, many, gen = _SEV_ADJ[m.group(1).lower()]
    noun = (m.group(2) or "").lower()
    if noun in ("дефект", "замечание"):
        return f"{one if noun == 'дефект' else one[:-2] + 'ое'} {noun}"
    if noun in ("дефекты", "замечания"):
        return f"{many} {noun}"
    if noun in ("дефектов", "замечаний"):
        return f"{gen} {noun}"
    prev = m.string[max(0, m.start() - 12):m.start()].lower()
    if re.search(r"(\d|нет|пять|шесть|семь|восемь|много|несколько|два|три|четыре)\s*$", prev):
        return f"{gen} дефектов" if not re.search(r"(два|три|четыре|\b[234])\s*$", prev) else f"{gen} дефекта"
    return f"{many} дефекты"


# Частые латинские термины в текстах линз → по-русски (идентификаторы документа не трогаем).
_TERMS_RU = [
    (re.compile(r"\b(?:защит\w* от )CSRF\b"), "защитой от подделки межсайтовых запросов"),
    (re.compile(r"\bCSRF\b"), "подделка межсайтовых запросов"),
    (re.compile(r"\bв USD\b"), "в долларах США"),
    (re.compile(r"\bUSD\b"), "доллары США"),
    (re.compile(r"\bв EUR\b"), "в евро"),
    (re.compile(r"\bfeature[- ]flag\w*", re.I), "флаг включения функции"),
]


def _ru_levels(text: str) -> str:
    """Страховка «только русский»: латинские названия уровней и частые термины в тексте → русские."""
    if not text:
        return text
    text = _SEV_WORD_RE.sub(_sev_sub, text)
    for rx, ru in _TERMS_RU:
        text = rx.sub(ru, text)
    return text


def _replace_keys(text: str, key_map: dict[str, str]) -> str:
    if not text or not key_map:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(key_map, key=len, reverse=True)) + r")\b")
    return pattern.sub(lambda m: key_map[m.group(1)], text)


def assemble(response: dict, candidates: list[dict], clusters: list[list[str]], *,
             requirements: list[dict] | None = None, checklist: list[str] | None = None,
             ctx: Any = None, warnings: list[str] | None = None,
             pre_rejected: list[dict] | None = None) -> dict:
    """Ответ модели + кандидаты → итог этапа (CONTRACT 2.4): ``findings``, ``rejected``,
    ``checklist``, ``verdict_summary``, ``fix_first``, ``warnings``."""
    warnings = warnings if warnings is not None else []
    by_id = {c["id"]: c for c in candidates}
    known_reqs = {_s(r.get("id")) for r in requirements or [] if _s(r.get("id"))}
    cluster_of = {cid: gi for gi, g in enumerate(clusters) for cid in g}
    placed: dict[str, str] = {}  # C-id → ключ дефекта или "rejected"
    run_sources = len({_source_family(_s(c.get("source"))) for c in candidates if _s(c.get("source"))})

    # 1. дефекты судьи: только известные кандидаты, каждый не более одного раза
    drafts: list[dict] = []
    used_keys: set[str] = set()
    for i, f in enumerate(response.get("findings") or [], 1):
        key = _s(f.get("key")) or f"F{i:02d}"
        if key in used_keys:  # повтор ключа у слабой модели — дефекты не склеиваем
            key = f"{key}#{i}"
        used_keys.add(key)
        ids = []
        for cid in f.get("candidate_ids") or []:
            cid = _s(cid)
            if cid not in by_id:
                if cid:
                    _warn(ctx, warnings, f"судья сослался на несуществующего кандидата {cid}")
                continue
            if cid in placed:
                continue
            ids.append(cid)
        if not ids:
            if not f.get("candidate_ids") and _s(f.get("title")):
                _warn(ctx, warnings, f"судья: дефект {_cut(f.get('title'), 60)!r} без кандидатов отброшен")
            continue
        for cid in ids:
            placed[cid] = key
        drafts.append({"key": key, "raw": f, "ids": ids})

    # 2. отклонённые судьёй (если кандидат уже в дефекте — остаётся в дефекте)
    rejected: list[dict] = list(pre_rejected or [])
    for r in response.get("rejected") or []:
        cid = _s(r.get("candidate_id"))
        if cid not in by_id or cid in placed:
            continue
        code = _s(r.get("reason_code"))
        code = code if code in REJECT_REASONS else "unrelated"
        reason = _s(r.get("reason")) or REJECT_REASONS[code]
        line = r.get("line") if isinstance(r.get("line"), int) and r.get("line", 0) > 0 else 0
        rejected.append(_rejected_entry(by_id[cid], code, reason, line))
        placed[cid] = "rejected"

    # 3. пропущенные: вслед за кластером, если его кандидаты уже в одном дефекте
    key_draft = {d["key"]: d for d in drafts}
    for cid in [c["id"] for c in candidates if c["id"] not in placed]:
        mates = [placed.get(x) for x in clusters[cluster_of[cid]] if x != cid and x in placed] \
            if cid in cluster_of else []
        targets = {m for m in mates if m and m != "rejected"}
        if len(targets) == 1:
            key = targets.pop()
            key_draft[key]["ids"].append(cid)
            placed[cid] = key
            _warn(ctx, warnings, f"судья пропустил {cid}; код присоединил его к дефекту своего кластера")

    # 4. сборка дефектов
    findings: list[dict] = []
    for d in drafts:
        f = d["raw"]
        members = [by_id[x] for x in d["ids"]]
        base_id = _s(f.get("base"))
        base = by_id[base_id] if base_id in d["ids"] else min(
            members, key=lambda c: (SEV_RANK.get(_s(c.get("severity")), 3), _cid_num(c["id"])))
        evidence = _pick_evidence(members, base)
        if not evidence:
            for cid in d["ids"]:
                rejected.append(_rejected_entry(by_id[cid], "no_quote", REJECT_REASONS["no_quote"], 0))
                placed[cid] = "rejected"
            continue
        kind = _s(f.get("kind")) if _s(f.get("kind")) in KINDS else (_s(base.get("kind")) or "other")
        crit = _s(f.get("criterion")) if _s(f.get("criterion")) in CRITERIA else (
            _s(base.get("criterion")) or "complete")
        sev = _s(f.get("severity")) if _s(f.get("severity")) in SEVERITIES else (
            _s(base.get("severity")) if _s(base.get("severity")) in SEVERITIES else "major")
        blocks = _s(f.get("blocks")) if _s(f.get("blocks")) in BLOCKS else (_s(base.get("blocks")) or "none")
        reqs = _valid_reqs(f.get("requirement_ids") or [], known_reqs) or _valid_reqs(
            [r for m in members for r in m.get("requirement_ids") or []], known_reqs)
        prio = f.get("priority") if isinstance(f.get("priority"), int) and 0 < f.get("priority") <= 99 else 0
        item = {
            "key": d["key"],
            "candidate_ids": sorted(d["ids"], key=_cid_num),
            "title": _cut(_s(f.get("title")) or _s(base.get("title")), 180),
            "kind": kind,
            "criterion": crit,
            "standard_refs": list(STANDARD_REFS.get(crit, [])),
            "severity": sev,
            "requirement_ids": reqs,
            "evidence": evidence,
            "problem": _text(f, base, "problem", 900),
            "scenario": _text(f, base, "scenario", 700),
            "impact": _text(f, base, "impact", 500),
            "recommendation": _text(f, base, "recommendation", 600),
            "rewrite": _text(f, base, "rewrite", 700),
            "question": _text(f, base, "question", 400),
            "blocks": blocks,
            "priority": prio,
            "sources": _sources(members),
            "_members": members,
            "_first_line": evidence[0]["line_start"],
        }
        _calibrate(item, members, ctx, warnings, run_sources)
        findings.append(item)

    findings = _merge_no_id(findings, ctx, warnings)
    for f in findings:  # после слияния — доказательства и источники заново
        if len(f["_members"]) > 1:
            f["evidence"] = _pick_evidence(f["_members"], f["_members"][0]) or f["evidence"]
            f["sources"] = _sources(f["_members"])
            f["_first_line"] = f["evidence"][0]["line_start"]
    _cap_critical(findings, ctx, warnings)
    _assign_priorities(findings)

    # 5. номера D-xx: серьёзность → приоритет → строка
    findings.sort(key=lambda f: (SEV_RANK[f["severity"]], f["priority"] if f["priority"] > 0 else 99,
                                 f["_first_line"], _cid_num(f["candidate_ids"][0])))
    key_map: dict[str, str] = {}
    for i, f in enumerate(findings, 1):
        f["id"] = f"D-{i:02d}"
        key_map[f["key"]] = f["id"]
        for cid in f["candidate_ids"]:
            key_map.setdefault(cid, f["id"])

    # 6. чек-лист
    items = checklist or [x for x, _ in BANK_CHECKLIST]
    by_n = {}
    for ch in response.get("checklist") or []:
        n = ch.get("n")
        if isinstance(n, int) and 1 <= n <= len(items) and n not in by_n:
            by_n[n] = ch
    final_check: list[dict] = []
    clean = [_public(f) for f in findings]
    missed_items = 0
    for n, text in enumerate(items, 1):
        ch = by_n.get(n)
        if ch is None or _s(ch.get("answer")) not in CHECK_ANSWERS:
            final_check.append(_auto_check(text, clean))
            missed_items += 1
            continue
        fids = [key_map[k] for k in (_s(x) for x in ch.get("finding_keys") or []) if k in key_map]
        final_check.append({
            "item": text,
            "answer": _s(ch.get("answer")),
            "comment": _words_cut(_ru_levels(_replace_keys(_s(ch.get("comment")), key_map)), 30),
            "finding_ids": list(dict.fromkeys(fids)),
        })
    if missed_items:
        _warn(ctx, warnings, f"судья не заполнил {missed_items} пункт(ов) чек-листа; заполнены кодом")

    summary = _ru_levels(_replace_keys(_s(response.get("verdict_summary")), key_map))
    if not summary:
        summary = fallback_summary(clean)

    # 7. ссылки на ключи в текстах дефектов → D-xx
    for f in clean:
        for field in ("title", "problem", "scenario", "impact", "recommendation", "question"):
            f[field] = _ru_levels(_replace_keys(f[field], {k: v for k, v in key_map.items() if not k.startswith("C-")}))

    fix_first = [f["id"] for f in sorted((f for f in clean if f["priority"] > 0), key=lambda f: f["priority"])]
    changes = [{"id": key_map[k], **v} for k, v in (response.get("_checks") or {}).items() if k in key_map]
    changes.sort(key=lambda x: x["id"])
    return {"findings": clean, "rejected": rejected, "checklist": final_check, "verdict_summary": summary,
            "fix_first": fix_first, "severity_changes": changes, "warnings": warnings, "_placed": placed}


def _public(f: dict) -> dict:
    keys = ["id", "candidate_ids", "title", "kind", "criterion", "standard_refs", "severity", "requirement_ids",
            "evidence", "problem", "scenario", "impact", "recommendation", "rewrite", "question", "blocks",
            "priority", "sources"]
    out = {k: f[k] for k in keys if k in f}
    out["_key"] = f["key"]
    return out


def _rejected_entry(c: dict, code: str, reason: str, line: int) -> dict:
    """Отклонённый кандидат: причина + то, по чему счётчик №15 отличит «линза не нашла» от «судья отклонил»."""
    return {
        "candidate_id": c["id"],
        "title": _cut(c.get("title"), 180),
        "source": _s(c.get("source")),
        "severity": _s(c.get("severity")),
        "kind": _s(c.get("kind")),
        "criterion": _s(c.get("criterion")),
        "requirement_ids": list(c.get("requirement_ids") or []),
        "reason_code": code,
        "reason": _cut(reason, 400),
        "line": line,
        "lines": _lines_of(c),
        "problem": _cut(c.get("problem"), 600),
        "evidence": [{k: e.get(k) for k in ("quote", "line_start", "line_end", "page", "section", "verified")
                      if k in e} for e in c.get("evidence") or []][:5],
    }


def fallback_summary(findings: list[dict]) -> str:
    crit = [f for f in findings if f["severity"] == "critical"]
    major = [f for f in findings if f["severity"] == "major"]
    minor = [f for f in findings if f["severity"] == "minor"]
    parts = [f"Итог ревью: {len(crit)} критичных, {len(major)} существенных и {len(minor)} незначительных замечаний."]
    if crit:
        parts.append("Начинать работу мешают: " + "; ".join(f"{f['id']} — {f['title']}" for f in crit[:3]) + ".")
    elif len(major) >= 3:
        parts.append("Критичных дефектов нет, но существенные замечания нужно закрыть до приёмки: "
                     + "; ".join(f"{f['id']} — {f['title']}" for f in major[:3]) + ".")
    else:
        parts.append("Блокирующих дефектов не найдено.")
    first = sorted((f for f in findings if f.get("priority", 0) > 0), key=lambda f: f["priority"])
    if first:
        parts.append("Исправить первым: " + ", ".join(f["id"] for f in first[:5]) + ".")
    return " ".join(parts)


# --- повторный вызов для пропущенных ------------------------------------------------------------


def _repair_missing(ctx: Any, missing: list[dict], response: dict, warnings: list[str]) -> dict:
    """Короткий второй вызов: пропущенные кандидаты → существующий дефект, новый дефект или отклонение."""
    findings = response.get("findings") or []
    index = "\n".join(f"{_s(f.get('key'))} · {_s(f.get('severity'))} · {_cut(f.get('title'), 140)} · "
                      f"кандидаты {', '.join(f.get('candidate_ids') or [])}" for f in findings)
    block = "\n\n".join(_render_full(c) for c in missing)
    user = (
        "Судья уже собрал реестр дефектов, но не распределил часть кандидатов. Для каждого кандидата ниже "
        "реши: merge — та же проблема, что у дефекта finding_key из реестра; new — отдельная проблема "
        "(дай короткий title и severity строго по шкале); reject — ложный кандидат (reason_code и reason "
        "одним предложением). Не пропускай ни одного кандидата.\n\n"
        f"<реестр>\n{index or '(пусто)'}\n</реестр>\n\n<кандидаты>\n{block}\n</кандидаты>")
    system = ""
    prompt = getattr(ctx, "prompt", None)
    if callable(prompt):
        try:
            system, _ = prompt(STAGE, candidates="", checklist="", stats="")
        except Exception:  # noqa: BLE001
            system = ""
    data = _ask(ctx, system, user, assign_schema())
    by_id = {c["id"]: c for c in missing}
    resp = {**response, "findings": [dict(f, candidate_ids=list(f.get("candidate_ids") or [])) for f in findings],
            "rejected": list(response.get("rejected") or [])}
    keys = {_s(f.get("key")): f for f in resp["findings"]}
    n_new = 0
    for a in data.get("assignments") or []:
        cid = _s(a.get("candidate_id"))
        if cid not in by_id:
            continue
        c = by_id.pop(cid)
        dec = _s(a.get("decision"))
        if dec == "merge" and _s(a.get("finding_key")) in keys:
            keys[_s(a.get("finding_key"))]["candidate_ids"].append(cid)
        elif dec == "reject":
            code = _s(a.get("reason_code"))
            resp["rejected"].append({"candidate_id": cid,
                                     "reason_code": code if code in _MODEL_REJECT_CODES else "unrelated",
                                     "reason": _s(a.get("reason")), "line": 0})
        else:
            n_new += 1
            sev = _s(a.get("severity")) if _s(a.get("severity")) in SEVERITIES else _s(c.get("severity"))
            nf = {"key": f"R{n_new:02d}", "candidate_ids": [cid], "base": cid,
                  "title": _s(a.get("title")) or _s(c.get("title")), "kind": _s(c.get("kind")),
                  "criterion": _s(c.get("criterion")), "requirement_ids": list(c.get("requirement_ids") or []),
                  "problem": "", "scenario": "", "impact": "", "severity_basis": "", "severity": sev,
                  "blocks": _s(c.get("blocks")) or "none", "priority": 0,
                  "recommendation": ""}
            resp["findings"].append(nf)
            keys[nf["key"]] = nf
    return resp


# --- вторая проверка серьёзности -----------------------------------------------------------------


def _render_check(f: dict, members: list[dict]) -> str:
    base = next((m for m in members if m["id"] == _s(f.get("base"))), members[0])
    ev = _pick_evidence(members, base)
    out = [f"{_s(f.get('key'))} · {_s(f.get('severity'))} · {_s(f.get('kind'))}/{_s(f.get('criterion'))} · "
           f"основание судьи: {_cut(f.get('severity_basis'), 200) or '—'}",
           f"  title: {_cut(_s(f.get('title')) or _s(base.get('title')), 200)}",
           f"  problem: {_cut(_s(f.get('problem')) or _s(base.get('problem')), 500)}"]
    scen = _s(f.get("scenario")) or _s(base.get("scenario"))
    if scen:
        out.append(f"  scenario: {_cut(scen, 400)}")
    if ev:
        out.append("  цитаты: " + "; ".join(f"L{e['line_start']:03d} «{_cut(e['quote'], 160)}»" for e in ev))
    return "\n".join(out)


def _check_severity(ctx: Any, response: dict, by_id: dict[str, dict], warnings: list[str]) -> dict:
    """Второй короткий вызов: перепроверка critical по шкале; уровень можно только понизить.
    Major не перепроверяется: на живых прогонах проверка снимала верные major (расхождение терминов, связей)."""
    response = {**response, "findings": [dict(f) for f in response.get("findings") or []]}  # ответ модели не меняем
    todo = []
    for f in response["findings"]:
        if _s(f.get("severity")) != "critical":
            continue
        members = [by_id[c] for c in (_s(x) for x in f.get("candidate_ids") or []) if c in by_id]
        if members:
            todo.append((f, members))
    if not todo:
        return response
    block = "\n\n".join(_render_check(f, m) for f, m in todo)
    summary = _s(response.get("verdict_summary")) or "—"
    prompt = getattr(ctx, "prompt", None)
    if callable(prompt):
        system, user = prompt("judge_check", findings=block, summary=summary)
    else:
        from pathlib import Path
        tpl = (Path(__file__).resolve().parents[1] / "prompts" / "judge_check.md").read_text(encoding="utf-8")
        system, user = "", tpl.replace("{{findings}}", block).replace("{{summary}}", summary)
    data = _ask(ctx, system, user, check_schema())
    by_key = {_s(f.get("key")): f for f, _ in todo}
    changes: dict[str, dict] = dict(response.get("_checks") or {})
    for ch in data.get("checks") or []:
        f = by_key.get(_s(ch.get("key")))
        new = _s(ch.get("severity"))
        if f is None or new not in SEV_RANK:
            continue
        old = _s(f.get("severity"))
        if SEV_RANK[new] <= SEV_RANK[old]:
            continue  # повышать нельзя; без изменений — пропускаем
        if old == "critical" and new == "minor":
            new = "major"  # не больше одной ступени за раз
        f["severity"] = new
        changes[_s(f.get("key"))] = {"from": old, "to": new, "reason": _cut(ch.get("reason"), 300),
                                     "basis": _cut(ch.get("basis"), 200)}
    out = {**response, "_checks": changes}
    if changes:
        new_summary = _s(data.get("verdict_summary"))
        if new_summary or any(v["from"] == "critical" for v in changes.values()):
            out["verdict_summary"] = new_summary  # пусто после понижения critical → код напишет сам
    if changes:
        down = [v for v in changes.values()]
        _warn(ctx, warnings, f"проверка серьёзности понизила {len(down)} дефект(ов): "
              f"critical→major {sum(1 for v in down if v['from'] == 'critical')}, "
              f"major→minor {sum(1 for v in down if v['from'] == 'major')}")
    return out


# --- запасной реестр без модели --------------------------------------------------------------------


def code_only_response(candidates: list[dict], clusters: list[list[str]]) -> dict:
    """Если модель-судья недоступна: кластер кода → дефект по представителю, без отклонений."""
    by_id = {c["id"]: c for c in candidates}
    findings = []
    for gi, g in enumerate(clusters, 1):
        rep = by_id[_representative(g, by_id)]
        findings.append({"key": f"F{gi:02d}", "candidate_ids": list(g), "base": rep["id"],
                         "title": _s(rep.get("title")), "kind": _s(rep.get("kind")),
                         "criterion": _s(rep.get("criterion")),
                         "requirement_ids": list(rep.get("requirement_ids") or []),
                         "problem": "", "scenario": "", "impact": "", "severity_basis": "",
                         "severity": _s(rep.get("severity")), "blocks": _s(rep.get("blocks")) or "none",
                         "priority": 0, "recommendation": ""})
    return {"findings": findings, "rejected": [], "checklist": [], "verdict_summary": "", "_fallback": True}


# --- вердикт (правило кода, CONTRACT раздел 5) -------------------------------------------------


def compute_verdict(findings: list[dict], status: str = "complete") -> dict:
    """Значения вердикта по правилу контракта. Текст обоснования — ``verdict_summary`` судьи."""
    if status == "failed":
        return {"development": "", "testing": "", "fix_first": []}

    def side(direction: str) -> str:
        crit = [f for f in findings if f.get("severity") == "critical"
                and f.get("blocks") in {direction, "both"}]
        if crit:
            return "no"
        major = [f for f in findings if f.get("severity") == "major"
                 and f.get("blocks") in {direction, "both"}]
        val = "conditional" if len(major) >= 3 else "yes"
        if status == "partial" and val == "yes":
            val = "conditional"
        return val

    fix_first = [f["id"] for f in sorted((f for f in findings if f.get("priority", 0) > 0),
                                         key=lambda f: f["priority"])]
    return {"development": side("development"), "testing": side("testing"), "fix_first": fix_first}


# --- план Б: судья поверх находок v1 ------------------------------------------------------------

_V1_KINDS = {"conflict": "contradiction", "contradiction": "contradiction", "gap": "missing_element",
             "missing": "missing_element", "vague": "ambiguity", "unclear": "ambiguity"}


def _find_line(view: dict, quote: str, hint: int | None = None) -> int | None:
    q = _norm_q(quote)
    if not q:
        return None
    lines = view.get("lines") or []
    hits = [ln.get("n") for ln in lines if q in _norm_q(ln.get("text"))]
    if not hits:  # цитата через 2–3 соседние строки
        for i in range(len(lines)):
            if q in _norm_q(" ".join(_s(x.get("text")) for x in lines[i:i + 3])):
                hits.append(lines[i].get("n"))
    if not hits:
        return None
    return min(hits, key=lambda n: abs(n - (hint or n)))


def candidates_from_v1(report: dict, view: dict) -> list[dict]:
    """Замечания отчёта v1 (`contracts/v1.json`) → кандидаты v2 для судьи (план Б из README, раздел 3).
    Цитаты ищутся в нумерованном документе; ненайденные помечаются `missing` (судья их отклонит)."""
    out: list[dict] = []
    for i, f in enumerate(report.get("findings") or [], 1):
        ev = []
        for e in f.get("evidence") or f.get("hints") or []:
            n = _find_line(view, _s(e.get("quote")))
            ev.append({"quote": _s(e.get("quote")), "line": n or 0, "line_start": n or 0, "line_end": n or 0,
                       "page": (e.get("loc") or {}).get("page") if isinstance(e.get("loc"), dict) else None,
                       "section": "", "verified": "normalized" if n else "missing"})
        w = f.get("witness") or {}
        scenario = " ".join(x for x in [_s(w.get("input")), _s(w.get("outcome_a")) and f"По одному месту: {_s(w.get('outcome_a'))}.",
                                        _s(w.get("outcome_b")) and f"По другому: {_s(w.get('outcome_b'))}."] if x)
        kind = _s(f.get("kind"))
        blocks = f.get("blocks") or []
        blocks = blocks if isinstance(blocks, str) else (
            "both" if {"development", "testing"} <= set(blocks) else (blocks[0] if blocks else "none"))
        out.append({
            "id": f"C-{i:03d}",
            "title": _s(f.get("title")),
            "kind": kind if kind in KINDS else _V1_KINDS.get(kind, "other"),
            "criterion": _s(f.get("criterion")) if _s(f.get("criterion")) in CRITERIA else "complete",
            "severity": _s(f.get("severity")) if _s(f.get("severity")) in SEVERITIES else "major",
            "requirement_ids": [],
            "evidence": ev,
            "problem": _s(f.get("meaning_reason")) or _s(f.get("impact")),
            "scenario": scenario,
            "impact": _s(f.get("impact")),
            "recommendation": _s(f.get("recommendation")),
            "rewrite": "",
            "question": "",
            "blocks": blocks if blocks in BLOCKS else "none",
            "source": f"v1:{_s(f.get('stage')) or _s(f.get('source')) or 'engine'}",
        })
    return out


# --- этап -------------------------------------------------------------------------------------


def run(ctx: Any, candidates: list[dict]) -> dict:
    """Этап «судья»: ``{"findings", "rejected", "checklist", "verdict_summary", "fix_first", "warnings"}``."""
    warnings: list[str] = []
    seen: set[str] = set()
    good: list[dict] = []
    pre_rejected: list[dict] = []
    for i, c in enumerate(candidates or [], 1):
        c = dict(c)
        c["id"] = _s(c.get("id")) or f"C-{i:03d}"
        if c["id"] in seen:
            c["id"] = f"{c['id']}-{i}"
        seen.add(c["id"])
        if not any(_ev_ok(e) for e in c.get("evidence") or []):
            pre_rejected.append(_rejected_entry(c, "no_quote", REJECT_REASONS["no_quote"], 0))
            continue
        good.append(c)

    view = _view_of(ctx)
    items, source = checklist_items(view)
    requirements = _requirements_of(ctx)
    if not good:
        result = assemble({"findings": [], "rejected": [], "checklist": [], "verdict_summary": ""}, [], [],
                          requirements=requirements, checklist=items, ctx=ctx, warnings=warnings,
                          pre_rejected=pre_rejected)
        return _finish(result, source)

    good.sort(key=lambda c: (_first_line(c), _cid_num(c["id"])))
    clusters = precluster(good)
    check_block = _checklist_block(items, source)
    try:
        parts = _call_judge(ctx, good, clusters, check_block, warnings)
        response = _merge_responses(parts)
        if not (response.get("findings") or response.get("rejected")):
            raise ValueError("пустой ответ: ни один кандидат не распределён")
    except Exception as exc:  # noqa: BLE001 — запасной реестр лучше, чем пустой отчёт
        _warn(ctx, warnings, f"судья недоступен ({type(exc).__name__}: {_cut(str(exc), 160)}); "
                             "реестр собран кодом из кластеров без отсева ложных")
        response = code_only_response(good, clusters)

    # пропущенные судьёй → один короткий повторный вызов
    mentioned = {_s(x) for f in response.get("findings") or [] for x in f.get("candidate_ids") or []}
    mentioned |= {_s(r.get("candidate_id")) for r in response.get("rejected") or []}
    cluster_of = {cid: gi for gi, g in enumerate(clusters) for cid in g}
    missing = [c for c in good if c["id"] not in mentioned
               and not any(x in mentioned for x in clusters[cluster_of[c["id"]]] if x != c["id"])]
    if missing and getattr(ctx, "llm", None) is not None and not response.get("_fallback"):
        try:
            response = _repair_missing(ctx, missing, response, warnings)
            _warn(ctx, warnings, f"судья пропустил {len(missing)} кандидат(ов); распределены повторным вызовом")
        except Exception as exc:  # noqa: BLE001
            _warn(ctx, warnings, f"повторный вызов судьи не удался ({type(exc).__name__})")

    if getattr(ctx, "llm", None) is not None and not response.get("_fallback") and _option(ctx, "judge_check", True):
        try:
            response = _check_severity(ctx, response, {c["id"]: c for c in good}, warnings)
        except Exception as exc:  # noqa: BLE001
            _warn(ctx, warnings, f"вторая проверка серьёзности не удалась ({type(exc).__name__}); "
                                 "оставлены уровни судьи")

    result = assemble(response, good, clusters, requirements=requirements, checklist=items, ctx=ctx,
                      warnings=warnings, pre_rejected=pre_rejected)
    placed = result.pop("_placed")
    lost = [c for c in good if c["id"] not in placed]
    for c in lost:
        result["rejected"].append(_rejected_entry(c, "not_reviewed", REJECT_REASONS["not_reviewed"], 0))
    if lost:
        _warn(ctx, warnings, f"судья не рассмотрел {len(lost)} кандидат(ов): " + ", ".join(c["id"] for c in lost))
    return _finish(result, source)


def _finish(result: dict, source: str) -> dict:
    result.pop("_placed", None)
    for f in result["findings"]:
        f.pop("_key", None)
    result["rejected"].sort(key=lambda r: _cid_num(r["candidate_id"]))
    result["checklist_source"] = source
    return result


def dumps(result: dict) -> str:  # удобство отладки
    return json.dumps(result, ensure_ascii=False, indent=2)


__all__ = ["run", "assemble", "candidates_from_v1", "precluster", "render_candidates", "find_checklist", "checklist_items",
           "compute_verdict", "response_schema", "BANK_CHECKLIST", "STANDARD_REFS", "REJECT_REASONS"]
