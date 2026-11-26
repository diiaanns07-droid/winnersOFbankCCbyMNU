"""Единый конфиг критериев и серьёзности (`criteria.toml`).

Все потребители читают конфиг только через :func:`load_criteria`: правила, промпты и
представление отчёта тогда работают с одной и той же версией. Версию подтверждает
``Criteria.fingerprint`` — SHA-256 байтов TOML. Его пишут в предупреждения, метаданные
этапа и в текст промпта.
"""
from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "Criteria",
    "Criterion",
    "CriteriaError",
    "SeverityRule",
    "SeverityCap",
    "VagueGroup",
    "load_criteria",
    "STATUSES",
    "SEVERITIES",
]

STATUSES = ("pass", "issue", "unknown", "na")
SEVERITIES = ("critical", "major", "minor")
_RX_FLAGS = re.IGNORECASE | re.UNICODE | re.MULTILINE


class CriteriaError(ValueError):
    """Конфиг критериев не прошёл проверку."""


def _rx(pattern: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, _RX_FLAGS)
    except re.error as exc:  # pragma: no cover - текст ошибки проверяется в тестах
        raise CriteriaError(f"{where}: неверное регулярное выражение {pattern!r}: {exc}") from exc


@dataclass(frozen=True)
class Criterion:
    """Критерий: ``code`` — код контракта v1 (``unambiguous``), ``short`` — русская метка (``И3``)."""

    code: str
    short: str
    scope: str
    name: str
    kind: str
    definition: str
    question: str
    source: tuple[str, ...]
    not_for: frozenset[str] = frozenset()
    checklist: tuple[str, ...] = ()
    pass_hint: str = ""

    @property
    def slug(self) -> str:  # совместимость: код контракта и есть slug
        return self.code

    @property
    def label(self) -> str:
        return f"{self.short} {self.name}"

    def applies(self, role: str) -> bool:
        return role not in self.not_for

    # Совместимость с резервным справочником движка: crit[code]["name"], ["standard"], ["question"].
    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        d["standard"] = "; ".join(self.source)
        d["definition"] = self.definition
        return d[key]

    def __contains__(self, key: object) -> bool:
        return key in ("code", "short", "kind", "scope", "name", "question", "source", "not_for", "checklist",
                       "standard", "definition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "short": self.short,
            "kind": self.kind,
            "scope": self.scope,
            "name": self.name,
            "definition": self.definition,
            "question": self.question,
            "source": list(self.source),
            "not_for": sorted(self.not_for),
            "checklist": list(self.checklist),
        }


@dataclass(frozen=True)
class SeverityRule:
    id: str
    applies_to: str
    severity: str
    why: str
    field: re.Pattern[str] | None = None
    role: frozenset[str] | None = None
    group: frozenset[str] | None = None
    scenario: re.Pattern[str] | None = None

    def matches(self, *, kind: str, field: str = "", role: str = "", group: str = "",
                document_text: str = "") -> bool:
        if self.applies_to != kind:
            return False
        if self.field is not None and not self.field.search(field or ""):
            return False
        if self.role is not None and role not in self.role:
            return False
        if self.group is not None and group not in self.group:
            return False
        if self.scenario is not None and not self.scenario.search(document_text or ""):
            return False
        return True


@dataclass(frozen=True)
class SeverityCap:
    id: str
    max: str
    why: str
    criterion: frozenset[str] | None = None
    quote: re.Pattern[str] | None = None

    def matches(self, criterion: str, quotes: Iterable[str]) -> bool:
        if self.criterion is not None and criterion not in self.criterion:
            return False
        if self.quote is not None and not any(self.quote.search(q or "") for q in quotes):
            return False
        return True


@dataclass(frozen=True)
class VagueGroup:
    id: str
    title: str
    criterion: str
    alt_criterion: str
    resolve: str
    strong: tuple[re.Pattern[str], ...]
    weak: tuple[re.Pattern[str], ...]
    question: str
    fix: str


@dataclass(frozen=True)
class RoleRule:
    id: str
    title: str
    match: re.Pattern[str]


@dataclass(frozen=True)
class LevelRule:
    id: str
    title: str
    match: re.Pattern[str] | None
    note: str


@dataclass
class Criteria:
    """Разобранный и проверенный ``criteria.toml``."""

    raw: dict[str, Any]
    fingerprint: str
    source_path: str
    version: str
    criteria: tuple[Criterion, ...]
    severity_levels: dict[str, dict[str, str]]
    severity_policy: dict[str, Any]
    severity_rules: tuple[SeverityRule, ...]
    severity_caps: tuple[SeverityCap, ...]
    roles: tuple[RoleRule, ...]
    levels: tuple[LevelRule, ...]
    default_role: str
    default_level: str
    vague: tuple[VagueGroup, ...]
    patterns: dict[str, re.Pattern[str]]
    checklist: tuple[dict[str, Any], ...]
    individual: dict[str, Any]
    kind_alias: dict[str, str] = field(default_factory=dict)
    _by_key: dict[str, Criterion] = field(default_factory=dict, repr=False)

    # --- справочник критериев -------------------------------------------------
    def __post_init__(self) -> None:
        for c in self.criteria:
            for key in (c.code, c.short, c.code.lower(), c.name.lower()):
                self._by_key[key] = c

    @property
    def tag(self) -> str:
        """Короткая метка версии: ``1.0.0+<12 символов SHA-256>``."""
        return f"{self.version}+{self.fingerprint[:12]}"

    def get(self, key: str, default: Any = KeyError) -> Criterion | Any:
        """Критерий по коду, метке или имени; без ``default`` неизвестный ключ — KeyError."""
        c = self.resolve(key)
        if c is None:
            if default is KeyError:
                raise KeyError(f"неизвестный критерий: {key!r}")
            return default
        return c

    # Mapping-доступ, как у резервного справочника движка: {code: {name, scope, standard, question}}.
    def __getitem__(self, code: str) -> Criterion:
        return self.get(code)

    def __iter__(self):
        return iter(c.code for c in self.criteria)

    def __len__(self) -> int:
        return len(self.criteria)

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and self.resolve(code) is not None

    def keys(self) -> list[str]:
        return [c.code for c in self.criteria]

    def values(self) -> list[Criterion]:
        return list(self.criteria)

    def items(self) -> list[tuple[str, Criterion]]:
        return [(c.code, c) for c in self.criteria]

    def resolve(self, key: str | None) -> Criterion | None:
        """Код контракта («unambiguous»), метка («И3») или русское имя → критерий."""
        if not key:
            return None
        k = str(key).strip()
        if k in self._by_key:
            return self._by_key[k]
        k = k.lower().replace("ё", "е")
        for alias, c in self._by_key.items():
            if alias.lower().replace("ё", "е") == k:
                return c
        # «И3 Однозначность», «И3: ...», «unambiguous (И3)»
        m = re.match(r"^\s*([ИН]\d+|[a-z_]+)", str(key))
        if m and m.group(1) in self._by_key:
            return self._by_key[m.group(1)]
        return None

    def for_scope(self, scope: str) -> list[Criterion]:
        return [c for c in self.criteria if c.scope == scope]

    def codes(self, scope: str | None = None) -> list[str]:
        return [c.code for c in self.criteria if scope is None or c.scope == scope]

    # --- серьёзность ------------------------------------------------------------
    def rank(self, severity: str) -> int:
        """critical → 0, major → 1, minor → 2."""
        return SEVERITIES.index(severity)

    def lower_of(self, a: str, b: str) -> str:
        return a if self.rank(a) >= self.rank(b) else b

    def rule_severity(self, *, kind: str, field: str = "", role: str = "", group: str = "",
                      document_text: str = "", fallback: str = "major") -> tuple[str, SeverityRule | None]:
        """Серьёзность находки детерминированного правила: первое подходящее правило TOML."""
        for rule in self.severity_rules:
            if rule.matches(kind=kind, field=field, role=role, group=group, document_text=document_text):
                sev = self.lower_of(rule.severity, self.severity_policy.get("rules_max", "major"))
                return sev, rule
        return self.lower_of(fallback, self.severity_policy.get("rules_max", "major")), None

    def cap_for(self, criterion: str, quotes: Iterable[str]) -> SeverityCap | None:
        quotes = list(quotes)
        for cap in self.severity_caps:
            if cap.matches(criterion, quotes):
                return cap
        return None

    # --- контекст ---------------------------------------------------------------
    def role_for_kind(self, kind: str | None) -> str | None:
        """Роль по ``Requirement.kind`` от №04 (таблица ``[context.kind_alias]``)."""
        if not kind:
            return None
        k = str(kind).strip().lower()
        if k in {r.id for r in self.roles}:
            return k
        return self.kind_alias.get(k)

    def role_for(self, section: Iterable[str]) -> str:
        """Роль пункта по самому глубокому подходящему заголовку раздела."""
        for heading in reversed([h for h in section if h]):
            for role in self.roles:
                if role.match.search(heading):
                    return role.id
        return self.default_role

    def level_for(self, section: Iterable[str]) -> str:
        headings = [h for h in section if h]
        for level in self.levels:
            if level.match is None:
                continue
            if any(level.match.search(h) for h in headings):
                return level.id
        return self.default_level

    def level_note(self, level: str) -> str:
        for lv in self.levels:
            if lv.id == level:
                return lv.note
        return ""

    # --- отрисовка для промптов и отчёта ------------------------------------------
    def render_criteria(self, scope: str = "requirement") -> str:
        lines = ["| Код (criterion) | Метка | Критерий | Что проверить | Источник | Не применяется к |",
                 "| :-- | :-- | :-- | :-- | :-- | :-- |"]
        for c in self.for_scope(scope):
            nf = ", ".join(sorted(c.not_for)) or "—"
            lines.append(f"| {c.code} | {c.short} | {c.name} | {c.definition} Вопрос: {c.question} | {'; '.join(c.source)} | {nf} |")
        return "\n".join(lines)

    def render_severity(self) -> str:
        out = []
        for sev in SEVERITIES:
            lv = self.severity_levels[sev]
            out.append(f"- **{sev}** ({lv['name']}): {lv['definition']} Проверка: {lv['test']}")
        pol = self.severity_policy
        out.append(
            f"- critical допустим, только если заполнены поля {', '.join(pol.get('critical_requires', []))}; "
            f"иначе он станет {pol.get('critical_fallback', 'major')}."
        )
        out.append(f"- Если замечание не мешает ни реализации, ни проверке (blocks = none), предел — {pol.get('no_block_max', 'minor')}.")
        out.append("- Числа и сроки, которые решает бизнес, не придумывай: оставь в правке маркер <уточнить у владельца: …> и задай вопрос.")
        out.append("")
        out.append("Правила серьёзности для типовых случаев (первое совпадение выигрывает):")
        for r in self.severity_rules:
            cond = [f"вид={r.applies_to}"]
            if r.field is not None:
                cond.append(f"поле~/{r.field.pattern}/")
            if r.role is not None:
                cond.append("роль∈{" + ", ".join(sorted(r.role)) + "}")
            if r.group is not None:
                cond.append("группа∈{" + ", ".join(sorted(r.group)) + "}")
            if r.scenario is not None:
                cond.append("в документе есть сценарий, требующий значение")
            out.append(f"  - [{r.id}] {'; '.join(cond)} → {r.severity}. {r.why}")
        for cap in self.severity_caps:
            crit = ", ".join(sorted(cap.criterion)) if cap.criterion else "любой"
            out.append(f"  - [предел {cap.id}] критерий {crit}, цитата~/{cap.quote.pattern if cap.quote else '.*'}/ → не выше {cap.max}. {cap.why}")
        return "\n".join(out)

    def render_roles(self) -> str:
        lines = [f"- {r.id}: {r.title}" for r in self.roles]
        lines += [f"- уровень {lv.id} ({lv.title}): {lv.note}" for lv in self.levels]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON-представление для отчёта и других модулей."""
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "criteria": [c.to_dict() for c in self.criteria],
            "severity": {
                "order": list(SEVERITIES),
                "levels": self.severity_levels,
                "policy": self.severity_policy,
            },
            "checklist": [dict(item) for item in self.checklist],
        }


def _req(table: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise CriteriaError(f"{where}: нет обязательного ключа {key!r}")
    return table[key]


def _parse(raw: dict[str, Any], *, fingerprint: str, source_path: str) -> Criteria:
    if raw.get("schema") != "bcc-criteria/1":
        raise CriteriaError("criteria.toml: ожидается schema = \"bcc-criteria/1\"")
    version = str(_req(raw, "version", "criteria.toml"))

    criteria: list[Criterion] = []
    seen: set[str] = set()
    for i, c in enumerate(_req(raw, "criterion", "criteria.toml")):
        where = f"criterion[{i}]"
        code = str(_req(c, "code", where))
        if code in seen:
            raise CriteriaError(f"{where}: повтор кода {code}")
        seen.add(code)
        scope = str(_req(c, "scope", where))
        if scope not in ("requirement", "set"):
            raise CriteriaError(f"{where}: scope должен быть requirement или set")
        criteria.append(
            Criterion(
                code=code,
                short=str(c.get("short", code)),
                scope=scope,
                name=str(_req(c, "name", where)),
                kind=str(c.get("kind", "other")),
                definition=str(_req(c, "definition", where)),
                question=str(_req(c, "question", where)),
                source=tuple(_req(c, "source", where)),
                not_for=frozenset(c.get("not_for", [])),
                checklist=tuple(c.get("checklist", [])),
                pass_hint=str(c.get("pass_hint", "")),
            )
        )
    codes = {c.code for c in criteria}

    sev = _req(raw, "severity", "criteria.toml")
    order = tuple(sev.get("order", SEVERITIES))
    if order != SEVERITIES:
        raise CriteriaError("severity.order должен быть [critical, major, minor]")
    levels = {k: dict(v) for k, v in _req(sev, "level", "severity").items()}
    for s in SEVERITIES:
        if s not in levels:
            raise CriteriaError(f"severity.level.{s} не описан")
    policy = dict(sev.get("policy", {}))
    for key in ("rules_max", "critical_fallback", "no_block_max"):
        if key in policy and policy[key] not in SEVERITIES:
            raise CriteriaError(f"severity.policy.{key}: неизвестная серьёзность {policy[key]!r}")

    rules: list[SeverityRule] = []
    for i, r in enumerate(sev.get("rule", [])):
        where = f"severity.rule[{i}]"
        s = str(_req(r, "severity", where))
        if s not in SEVERITIES:
            raise CriteriaError(f"{where}: неизвестная серьёзность {s!r}")
        rules.append(
            SeverityRule(
                id=str(_req(r, "id", where)),
                applies_to=str(_req(r, "applies_to", where)),
                severity=s,
                why=str(r.get("why", "")),
                field=_rx(r["field"], where) if r.get("field") else None,
                role=frozenset(r["role"]) if "role" in r else None,
                group=frozenset(r["group"]) if "group" in r else None,
                scenario=_rx(r["scenario"], where) if r.get("scenario") else None,
            )
        )
    caps: list[SeverityCap] = []
    for i, cp in enumerate(sev.get("cap", [])):
        where = f"severity.cap[{i}]"
        mx = str(_req(cp, "max", where))
        if mx not in SEVERITIES:
            raise CriteriaError(f"{where}: неизвестная серьёзность {mx!r}")
        crit = cp.get("criterion")
        if crit:
            unknown = set(crit) - codes
            if unknown:
                raise CriteriaError(f"{where}: неизвестные критерии {sorted(unknown)}")
        caps.append(
            SeverityCap(
                id=str(_req(cp, "id", where)),
                max=mx,
                why=str(cp.get("why", "")),
                criterion=frozenset(crit) if crit else None,
                quote=_rx(cp["quote"], where) if cp.get("quote") else None,
            )
        )

    ctx = raw.get("context", {})
    roles = tuple(
        RoleRule(id=str(r["id"]), title=str(r.get("title", r["id"])), match=_rx(r["match"], f"context.role[{r['id']}]") )
        for r in ctx.get("role", [])
    )
    lvls = tuple(
        LevelRule(
            id=str(lv["id"]),
            title=str(lv.get("title", lv["id"])),
            match=_rx(lv["match"], f"context.level[{lv['id']}]") if lv.get("match") else None,
            note=str(lv.get("note", "")),
        )
        for lv in ctx.get("level", [])
    )

    patterns: dict[str, re.Pattern[str]] = {}
    constraint = ctx.get("constraint", {})
    for key in ("markers", "design_terms"):
        if key in constraint:
            patterns[f"constraint.{key}"] = _rx(constraint[key], f"context.constraint.{key}")
    for section, table in raw.get("rules", {}).items():
        for key, value in table.items():
            if isinstance(value, str):
                patterns[f"{section}.{key}"] = _rx(value, f"rules.{section}.{key}")

    vague: list[VagueGroup] = []
    for i, g in enumerate(raw.get("lexicon", {}).get("vague", [])):
        where = f"lexicon.vague[{i}]"
        for key in ("criterion", "alt_criterion"):
            if g.get(key) not in codes:
                raise CriteriaError(f"{where}: {key} {g.get(key)!r} не описан в [[criterion]]")
        vague.append(
            VagueGroup(
                id=str(_req(g, "id", where)),
                title=str(g.get("title", g["id"])),
                criterion=g["criterion"],
                alt_criterion=g["alt_criterion"],
                resolve=str(g.get("resolve", "none")),
                strong=tuple(_rx(rf"(?<![\w-])(?:{t})(?![\w-])", where) for t in g.get("strong", [])),
                weak=tuple(_rx(rf"(?<![\w-])(?:{t})(?![\w-])", where) for t in g.get("weak", [])),
                question=str(g.get("question", "")),
                fix=str(g.get("fix", "")),
            )
        )

    checklist = tuple(dict(item) for item in raw.get("checklist", []))
    for item in checklist:
        bad = set(item.get("criteria", [])) - codes
        if bad:
            raise CriteriaError(f"checklist[{item.get('id')}]: неизвестные критерии {sorted(bad)}")
        if item.get("match"):
            _rx(item["match"], f"checklist[{item.get('id')}]")
    cl_ids = {item["id"] for item in checklist}
    for c in criteria:
        bad = set(c.checklist) - cl_ids
        if bad:
            raise CriteriaError(f"criterion {c.code}: ссылки на неизвестные пункты чек-листа {sorted(bad)}")

    return Criteria(
        raw=raw,
        fingerprint=fingerprint,
        source_path=source_path,
        version=version,
        criteria=tuple(criteria),
        severity_levels=levels,
        severity_policy=policy,
        severity_rules=tuple(rules),
        severity_caps=tuple(caps),
        roles=roles,
        levels=lvls,
        default_role=str(ctx.get("default_role", "functional")),
        default_level=str(ctx.get("default_level", "business")),
        vague=tuple(vague),
        patterns=patterns,
        checklist=checklist,
        individual=dict(raw.get("individual", {})),
        kind_alias={str(k).lower(): str(v) for k, v in ctx.get("kind_alias", {}).items()},
    )


def _load_bytes(data: bytes, source_path: str) -> Criteria:
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise CriteriaError(f"{source_path}: не удалось прочитать TOML: {exc}") from exc
    return _parse(raw, fingerprint=hashlib.sha256(data).hexdigest(), source_path=source_path)


@lru_cache(maxsize=1)
def _load_default() -> Criteria:
    res = resources.files("bcc_review").joinpath("criteria.toml")
    return _load_bytes(res.read_bytes(), "bcc_review/criteria.toml")


def load_criteria(path: str | Path | None = None) -> Criteria:
    """Прочитать конфиг критериев.

    Без аргумента читается ``criteria.toml`` из установленного пакета (кешируется).
    С путём читается указанный файл — так тесты и потребители подменяют правила, а
    правила, промпт и метаданные гарантированно используют одну и ту же версию.
    """
    if path is None:
        return _load_default()
    p = Path(path)
    return _load_bytes(p.read_bytes(), str(p))
