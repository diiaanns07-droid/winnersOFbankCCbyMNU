"""Форматы протокола bcc-eval v1: эталон, предсказания, прогоны, манифест, решения разбора.

Общий формат с GPT Pro (эталон): case_id, family, source_sha256, issue_type, anchors,
expected_outcome. Плоская форма (defect_id, type, criterion, severity, quote,
line/locator, related_quote, explanation) принимается и приводится к anchors.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .normalize import norm
from .taxonomy import Taxonomy

GOLD_SCHEMA = "bcc-eval-label/1"
PRED_SCHEMA = "bcc-eval-pred/1"
OUTCOMES = ("present", "clean", "absent")
ANCHOR_POLICIES = ("all", "any")
SEVERITIES = ("critical", "major", "minor")
CONTROL_ROLE = "control"
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ProtocolError(ValueError):
    """Нарушение формата входа. Сообщение называет файл, строку и поле."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"{path}:{n}: не JSON: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ProtocolError(f"{path}:{n}: строка должна быть объектом JSON")
            row["_line"] = n
            row["_file"] = str(path)
            rows.append(row)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")


def _where(row: dict) -> str:
    return f"{row.get('_file', '<input>')}:{row.get('_line', '?')}"


@dataclass(frozen=True)
class Anchor:
    quote: str
    role: str = "primary"
    locator: str | None = None


def _anchors_from_row(row: dict, what: str) -> list[Anchor]:
    """anchors из канонического поля или из плоских quote/related_quote."""
    out: list[Anchor] = []
    if "anchors" in row and row["anchors"] is not None:
        if not isinstance(row["anchors"], list):
            raise ProtocolError(f"{_where(row)}: {what}.anchors должен быть массивом")
        for i, a in enumerate(row["anchors"]):
            if isinstance(a, str):
                a = {"quote": a}
            if not isinstance(a, dict) or not isinstance(a.get("quote"), str) or not a["quote"].strip():
                raise ProtocolError(f"{_where(row)}: {what}.anchors[{i}].quote должен быть непустой строкой")
            loc = a.get("locator", a.get("line"))
            out.append(Anchor(a["quote"], str(a.get("role") or "primary"), None if loc is None else str(loc)))
        return out
    loc = row.get("locator", row.get("line"))
    if isinstance(row.get("quote"), str) and row["quote"].strip():
        out.append(Anchor(row["quote"], "primary", None if loc is None else str(loc)))
    if isinstance(row.get("related_quote"), str) and row["related_quote"].strip():
        rl = row.get("related_locator", row.get("related_line"))
        out.append(Anchor(row["related_quote"], "related", None if rl is None else str(rl)))
    return out


# --------------------------------------------------------------------------- эталон
@dataclass
class GoldLabel:
    label_id: str
    case_id: str
    family: str
    source_sha256: str
    issue_type: str | None
    anchors: list[Anchor]
    expected_outcome: str
    anchor_policy: str = "all"
    severity: str | None = None
    criterion: str | None = None
    scenario: str | None = None
    explanation: str | None = None
    visibility: str = "public"

    @property
    def required_anchors(self) -> list[Anchor]:
        return [a for a in self.anchors if a.role != CONTROL_ROLE]


def parse_gold(rows: list[dict], taxonomy: Taxonomy) -> list[GoldLabel]:
    labels: list[GoldLabel] = []
    seen_ids: set[str] = set()
    per_case_counter: dict[str, int] = {}
    for row in rows:
        w = _where(row)
        for key in ("case_id", "family", "source_sha256", "expected_outcome"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ProtocolError(f"{w}: поле {key} обязательно и должно быть строкой")
        if not _SHA.match(row["source_sha256"]):
            raise ProtocolError(f"{w}: source_sha256 должен быть SHA-256 в нижнем регистре (64 hex)")
        outcome = row["expected_outcome"]
        if outcome not in OUTCOMES:
            raise ProtocolError(f"{w}: expected_outcome={outcome!r}, допустимо {OUTCOMES}")
        issue_type = row.get("issue_type", row.get("type"))
        if issue_type is not None and not taxonomy.known(issue_type):
            raise ProtocolError(f"{w}: issue_type={issue_type!r} нет в таксономии {taxonomy.source}")
        anchors = _anchors_from_row(row, "gold")
        if outcome == "present":
            if issue_type is None:
                raise ProtocolError(f"{w}: у present обязателен issue_type")
            if not [a for a in anchors if a.role != CONTROL_ROLE]:
                raise ProtocolError(f"{w}: у present нужна хотя бы одна опора с ролью не control")
        elif outcome == "clean":
            if issue_type is not None or anchors:
                raise ProtocolError(f"{w}: строка clean описывает чистый кейс: issue_type=null, anchors=[]")
        elif outcome == "absent" and not anchors:
            raise ProtocolError(f"{w}: у absent (контрольное место) нужна опора")
        policy = row.get("anchor_policy", "all")
        if policy not in ANCHOR_POLICIES:
            raise ProtocolError(f"{w}: anchor_policy={policy!r}, допустимо {ANCHOR_POLICIES}")
        sev = row.get("severity")
        if sev is not None and sev not in SEVERITIES:
            raise ProtocolError(f"{w}: severity={sev!r}, допустимо {SEVERITIES}")
        case_id = row["case_id"]
        per_case_counter[case_id] = per_case_counter.get(case_id, 0) + 1
        label_id = row.get("label_id") or row.get("defect_id") or f"{case_id}#{per_case_counter[case_id]}"
        if label_id in seen_ids:
            raise ProtocolError(f"{w}: повтор label_id {label_id!r}")
        seen_ids.add(label_id)
        labels.append(GoldLabel(
            label_id=label_id, case_id=case_id, family=row["family"], source_sha256=row["source_sha256"],
            issue_type=issue_type, anchors=anchors, expected_outcome=outcome, anchor_policy=policy,
            severity=sev, criterion=row.get("criterion"), scenario=row.get("scenario"),
            explanation=row.get("explanation"), visibility=row.get("visibility", "public"),
        ))
    by_case: dict[str, list[GoldLabel]] = {}
    for lab in labels:
        by_case.setdefault(lab.case_id, []).append(lab)
    for case_id, labs in by_case.items():
        outcomes = {l.expected_outcome for l in labs}
        if "clean" in outcomes and "present" in outcomes:
            raise ProtocolError(f"кейс {case_id}: строка clean несовместима с present-дефектами")
        if len({l.source_sha256 for l in labs}) != 1:
            raise ProtocolError(f"кейс {case_id}: у строк эталона разные source_sha256")
        if len({l.family for l in labs}) != 1:
            raise ProtocolError(f"кейс {case_id}: у строк эталона разные family")
        if outcomes == {"absent"}:
            raise ProtocolError(f"кейс {case_id}: только absent-строки; добавьте clean или present, "
                                "чтобы эталон полностью описывал кейс")
    return labels


# ---------------------------------------------------------------------- предсказания
@dataclass
class Prediction:
    key: str
    issue_type: str
    anchors: list[Anchor]
    source_sha256: str | None = None
    case_id: str | None = None
    render_id: str | None = None
    format: str | None = None
    mode: str | None = None
    defect_id: str | None = None
    kind: str | None = None
    kind_mapped: bool = True
    criterion: str | None = None
    severity: str | None = None
    status: str | None = None
    scope: str | None = None
    explanation: str | None = None
    where: str = ""
    # заполняются при разрешении
    r_case: str | None = None
    r_render: str | None = None
    r_format: str | None = None


@dataclass
class RunRecord:
    source_sha256: str | None
    case_id: str | None
    render_id: str | None
    format: str | None
    mode: str | None
    status: str
    physical_calls: int | None
    tokens_in: int | None
    tokens_out: int | None
    duration_s: float | None
    provider: str | None = None
    model: str | None = None
    agent_version: str | None = None
    manifest_sha256: str | None = None
    cache: Any = None
    empty_input_warning: bool | None = None
    violations: list[str] = field(default_factory=list)
    modules: dict = field(default_factory=dict)
    status_reasons: list = field(default_factory=list)
    where: str = ""
    r_case: str | None = None
    r_render: str | None = None
    r_format: str | None = None


def prediction_key(locator: str, mode: str | None, defect_id: str | None, issue_type: str,
                   anchors: list[Anchor]) -> str:
    payload = [locator, mode or "", defect_id or "", issue_type, sorted(norm(a.quote) for a in anchors)]
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()[:16]


def _opt_int(row: dict, *names: str) -> int | None:
    for n in names:
        v = row.get(n)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
    return None


def parse_predictions(rows: list[dict], taxonomy: Taxonomy) -> tuple[list[Prediction], list[RunRecord]]:
    preds: list[Prediction] = []
    runs: list[RunRecord] = []
    for row in rows:
        w = _where(row)
        record = row.get("record", "finding")
        sha = row.get("source_sha256")
        if sha is not None and not (isinstance(sha, str) and _SHA.match(sha)):
            raise ProtocolError(f"{w}: source_sha256 должен быть SHA-256 (64 hex)")
        if not (sha or row.get("case_id") or row.get("render_id")):
            raise ProtocolError(f"{w}: нужен source_sha256, render_id или case_id")
        if record == "run":
            status = row.get("status", "complete")
            if status not in ("complete", "partial", "failed"):
                raise ProtocolError(f"{w}: run.status={status!r}, допустимо complete|partial|failed")
            runs.append(RunRecord(
                source_sha256=sha, case_id=row.get("case_id"), render_id=row.get("render_id"),
                format=row.get("format"), mode=row.get("mode"), status=status,
                physical_calls=_opt_int(row, "physical_calls"), tokens_in=_opt_int(row, "tokens_in"),
                tokens_out=_opt_int(row, "tokens_out"),
                duration_s=row.get("duration_s") if isinstance(row.get("duration_s"), (int, float)) else None,
                provider=row.get("provider"), model=row.get("model"), agent_version=row.get("agent_version"),
                manifest_sha256=row.get("manifest_sha256"), cache=row.get("cache"),
                empty_input_warning=row.get("empty_input_warning"),
                modules=dict(row.get("modules") or {}), status_reasons=list(row.get("status_reasons") or []),
                violations=list(row.get("violations") or []), where=w,
            ))
            continue
        if record != "finding":
            raise ProtocolError(f"{w}: record={record!r}, допустимо finding|run")
        issue_type = row.get("issue_type", row.get("type"))
        kind = row.get("kind")
        mapped = True
        if issue_type is None:
            issue_type, mapped = taxonomy.map_kind(kind)
        elif not taxonomy.known(issue_type):
            issue_type, mapped = taxonomy.map_kind(issue_type)
        anchors = _anchors_from_row(row, "pred")
        sev = row.get("severity")
        locator = sha or row.get("render_id") or row.get("case_id")
        key = row.get("pred_key") or prediction_key(locator, row.get("mode"), row.get("defect_id"), issue_type, anchors)
        preds.append(Prediction(
            key=key, issue_type=issue_type, anchors=anchors, source_sha256=sha, case_id=row.get("case_id"),
            render_id=row.get("render_id"), format=row.get("format"), mode=row.get("mode"),
            defect_id=row.get("defect_id"), kind=kind, kind_mapped=mapped, criterion=row.get("criterion"),
            severity=sev if sev in SEVERITIES else None, status=row.get("status"), scope=row.get("scope"),
            explanation=row.get("explanation"), where=w,
        ))
    return preds, runs


# -------------------------------------------------------------------------- манифест
@dataclass(frozen=True)
class RenderInfo:
    case_id: str
    render_id: str
    format: str
    sha256: str
    path: str | None


@dataclass
class Manifest:
    data: dict
    sha256: str
    renders_by_sha: dict[str, RenderInfo]
    renders_by_id: dict[str, RenderInfo]
    cases: dict[str, dict]
    root: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Manifest":
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
        by_sha: dict[str, RenderInfo] = {}
        by_id: dict[str, RenderInfo] = {}
        cases: dict[str, dict] = {}
        for case in data.get("cases", []):
            cid = case["case_id"]
            if cid in cases:
                raise ProtocolError(f"{path}: повтор case_id {cid!r}")
            cases[cid] = case
            for r in case.get("renders", []):
                info = RenderInfo(cid, r["render_id"], r["format"], r["sha256"], r.get("path"))
                if info.sha256 in by_sha and by_sha[info.sha256].case_id != cid:
                    raise ProtocolError(f"{path}: один файл ({info.sha256[:12]}…) у кейсов "
                                        f"{by_sha[info.sha256].case_id} и {cid}")
                by_sha.setdefault(info.sha256, info)
                by_id[info.render_id] = info
        return cls(data=data, sha256=sha256_bytes(raw), renders_by_sha=by_sha, renders_by_id=by_id, cases=cases,
                   root=Path(path).resolve().parent)

    def primary_format(self, case_id: str) -> str | None:
        return self.cases.get(case_id, {}).get("primary_render")

    def source_text(self, case_id: str) -> str | None:
        """Текст MD/TXT-представления кейса (для правила уникального фрагмента)."""
        for r in self.cases.get(case_id, {}).get("renders", []):
            if r.get("format") in ("md", "txt") and r.get("path") and self.root is not None:
                p = self.root / r["path"]
                if p.exists():
                    return p.read_text(encoding="utf-8")
        return None


# ---------------------------------------------------------------- решения разбора
DECISIONS = ("match", "false_alarm", "new_real_defect", "duplicate")


@dataclass(frozen=True)
class Decision:
    pred_key: str
    decision: str
    label_id: str | None = None
    reviewer: str | None = None
    note: str | None = None


def parse_decisions(rows: list[dict]) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for row in rows:
        w = _where(row)
        if row.get("decision") is None:
            continue  # незаполненная строка листа разбора
        if row["decision"] not in DECISIONS:
            raise ProtocolError(f"{w}: decision={row['decision']!r}, допустимо {DECISIONS}")
        if not isinstance(row.get("pred_key"), str):
            raise ProtocolError(f"{w}: pred_key обязателен")
        if row["decision"] == "match" and not row.get("label_id"):
            raise ProtocolError(f"{w}: для decision=match нужен label_id")
        if row["pred_key"] in out:
            raise ProtocolError(f"{w}: повторное решение для pred_key {row['pred_key']}")
        out[row["pred_key"]] = Decision(row["pred_key"], row["decision"], row.get("label_id"),
                                        row.get("reviewer"), row.get("note"))
    return out
