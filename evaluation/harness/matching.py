"""Сопоставление один-к-одному внутри кейса.

Пара (предсказание, дефект эталона) допустима, если совпадает case_id, вид дефекта
совместим (exact, либо parent при --type-match hierarchy) и цитаты находки покрывают
опоры эталона по его anchor_policy. Из допустимых пар строится паросочетание
максимальной мощности (алгоритм Куна), поэтому:

* одна находка засчитывается не больше чем за один дефект (групповая находка не
  закрывает все цели сразу; остальные цели остаются FN с пометкой claimed_by_group);
* второе и следующие предсказания на уже закрытый дефект — дубли, а не TP.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .normalize import coverage
from .schema import CONTROL_ROLE, Decision, GoldLabel, Prediction
from .taxonomy import BORDERLINE, EXACT, NONE, PARENT, Taxonomy


@dataclass
class PairInfo:
    type_rel: str
    covered_roles: list[str]
    required: int
    full: bool
    partial: bool
    share: float

    @property
    def score(self) -> float:
        return (2.0 if self.type_rel == EXACT else 1.0) + self.share


def anchor_relation(pred: Prediction, label: GoldLabel,
                    doc_tokens: list[str] | None = None) -> tuple[bool, bool, list[str], float, int]:
    """(full, partial, covered_roles, mean_share, required) для опор эталона."""
    required = label.required_anchors
    covered: list[str] = []
    shares: list[float] = []
    partial = False
    for ga in required:
        best = 0.0
        hit = False
        for pa in pred.anchors:
            c = coverage(ga.quote, pa.quote, doc_tokens)
            best = max(best, c.share)
            hit = hit or c.covered
            partial = partial or c.partial
        if hit:
            covered.append(ga.role)
        shares.append(best)
    if not required:
        return False, False, [], 0.0, 0
    full = len(covered) == len(required) if label.anchor_policy == "all" else bool(covered)
    partial = partial or (bool(covered) and not full)
    return full, partial, covered, sum(shares) / len(shares), len(required)


def pair_info(pred: Prediction, label: GoldLabel, taxonomy: Taxonomy,
              doc_tokens: list[str] | None = None) -> PairInfo:
    rel = taxonomy.relation(pred.issue_type, label.issue_type) if label.issue_type else NONE
    full, partial, roles, share, req = anchor_relation(pred, label, doc_tokens)
    return PairInfo(rel, roles, req, full, partial, share)


def covers_control(pred: Prediction, label: GoldLabel, doc_tokens: list[str] | None = None) -> bool:
    for ga in label.anchors:
        if ga.role != CONTROL_ROLE:
            continue
        for pa in pred.anchors:
            c = coverage(ga.quote, pa.quote, doc_tokens)
            if c.covered or coverage(pa.quote, ga.quote).covered:
                return True
    return False


def same_finding(a: Prediction, b: Prediction) -> bool:
    """Одна и та же находка в двух кейсах (для фона: ложная находка есть и на чистой базе)."""
    if a.issue_type != b.issue_type or not a.anchors or not b.anchors:
        return False
    def side(x: Prediction, y: Prediction) -> bool:
        return all(any(coverage(xa.quote, ya.quote).covered for ya in y.anchors) for xa in x.anchors)
    return side(a, b) and side(b, a)


@dataclass
class CaseResult:
    case_id: str
    tp: list[dict] = field(default_factory=list)
    fp: list[dict] = field(default_factory=list)
    fn: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    new_real: list[dict] = field(default_factory=list)
    decided_false_alarm: list[dict] = field(default_factory=list)
    ignored_decisions: list[dict] = field(default_factory=list)


def match_case(case_id: str, labels: list[GoldLabel], preds: list[Prediction], taxonomy: Taxonomy,
               type_match: str = "hierarchy", decisions: dict[str, Decision] | None = None,
               doc_tokens: list[str] | None = None) -> CaseResult:
    decisions = decisions or {}
    present = [l for l in labels if l.expected_outcome == "present"]
    controls = [l for l in labels if l.expected_outcome == "absent"]
    is_clean = any(l.expected_outcome == "clean" for l in labels)
    label_idx = {l.label_id: i for i, l in enumerate(present)}

    info: dict[tuple[int, int], PairInfo] = {}
    eligible: dict[int, list[int]] = {}
    near: dict[int, list[dict]] = {}
    for pi, p in enumerate(preds):
        for li, lab in enumerate(present):
            pinfo = pair_info(p, lab, taxonomy, doc_tokens)
            info[(pi, li)] = pinfo
            type_ok = pinfo.type_rel == EXACT or (pinfo.type_rel == PARENT and type_match == "hierarchy")
            if type_ok and pinfo.full:
                eligible.setdefault(pi, []).append(li)
            elif pinfo.type_rel != NONE and (pinfo.full or pinfo.partial):
                reason = []
                if not pinfo.full:
                    reason.append(f"partial_anchors:{len(pinfo.covered_roles)}/{pinfo.required}")
                if pinfo.type_rel == BORDERLINE:
                    reason.append(f"borderline_type:{p.issue_type}~{lab.issue_type}")
                elif pinfo.type_rel == PARENT and type_match != "hierarchy":
                    reason.append(f"parent_type_under_exact_policy:{p.issue_type}~{lab.issue_type}")
                near.setdefault(pi, []).append({"label_id": lab.label_id, "reason": ";".join(reason),
                                                "anchor_share": round(pinfo.share, 3)})
        d = decisions.get(p.key)
        if d and d.decision == "match":
            li = label_idx.get(d.label_id or "")
            if li is None:
                raise ValueError(f"решение для {p.key}: label_id {d.label_id!r} нет среди дефектов кейса {case_id}")
            if li not in eligible.get(pi, []):
                eligible.setdefault(pi, []).append(li)
                info[(pi, li)] = PairInfo("adjudicated", info[(pi, li)].covered_roles, info[(pi, li)].required,
                                          True, False, info[(pi, li)].share)

    for pi in eligible:
        eligible[pi].sort(key=lambda li: (-info[(pi, li)].score, present[li].label_id))
    best = {pi: max((info[(pi, li)].score for li in lis), default=0.0) for pi, lis in eligible.items()}
    order = sorted(range(len(preds)), key=lambda pi: (-best.get(pi, 0.0), pi))

    match_of_label: dict[int, int] = {}

    def assign(pi: int, seen: set[int]) -> bool:
        for li in eligible.get(pi, []):
            if li in seen:
                continue
            seen.add(li)
            if li not in match_of_label or assign(match_of_label[li], seen):
                match_of_label[li] = pi
                return True
        return False

    for pi in order:
        if pi in eligible:
            assign(pi, set())

    matched_pred = {pi: li for li, pi in match_of_label.items()}
    res = CaseResult(case_id)
    for li, pi in sorted(match_of_label.items(), key=lambda x: present[x[0]].label_id):
        lab, p, pinfo = present[li], preds[pi], info[(pi, li)]
        res.tp.append({
            "case_id": case_id, "label_id": lab.label_id, "pred_key": p.key, "defect_id": p.defect_id,
            "gold_type": lab.issue_type, "pred_type": p.issue_type,
            "match_level": pinfo.type_rel if pinfo.type_rel != "adjudicated" else "adjudicated",
            "anchor_share": round(pinfo.share, 3), "covered_roles": pinfo.covered_roles,
            "gold_severity": lab.severity, "pred_severity": p.severity,
        })
        d = decisions.get(p.key)
        if d and d.decision != "match":
            res.ignored_decisions.append({"pred_key": p.key, "decision": d.decision,
                                          "reason": "находка сопоставлена автоматически"})
    for li, lab in enumerate(present):
        if li in match_of_label:
            continue
        claimed = [preds[pi].key for pi, lis in eligible.items() if li in lis and pi in matched_pred]
        near_preds = [preds[pi].key for pi, items in near.items()
                      if any(x["label_id"] == lab.label_id for x in items)]
        res.fn.append({"case_id": case_id, "label_id": lab.label_id, "gold_type": lab.issue_type,
                       "gold_severity": lab.severity, "claimed_by_group": claimed, "near_misses": near_preds})
    for pi, p in enumerate(preds):
        if pi in matched_pred:
            continue
        base = {"case_id": case_id, "pred_key": p.key, "defect_id": p.defect_id, "pred_type": p.issue_type,
                "kind": p.kind, "severity": p.severity, "status": p.status,
                "quotes": [a.quote for a in p.anchors], "where": p.where}
        if pi in eligible:
            li = eligible[pi][0]
            res.duplicates.append({**base, "duplicate_of": present[li].label_id,
                                   "kept_pred_key": preds[match_of_label[li]].key})
            continue
        d = decisions.get(p.key)
        if d and d.decision == "new_real_defect":
            res.new_real.append({**base, "reviewer": d.reviewer, "note": d.note})
            continue
        if d and d.decision == "duplicate":
            res.duplicates.append({**base, "duplicate_of": None, "kept_pred_key": None, "adjudicated": True})
            continue
        reasons = []
        if is_clean:
            reasons.append("clean_false_alarm")
        hits = [c.label_id for c in controls if covers_control(p, c, doc_tokens)]
        if hits:
            reasons.append("control_hit")
        if pi in near:
            reasons.append("near_miss")
        if not p.kind_mapped:
            reasons.append("unmapped_kind")
        fp = {**base, "reasons": reasons or ["unexplained"], "control_labels": hits,
              "near": near.get(pi, []), "background": False,
              "pending": (pi in near) and not (d and d.decision == "false_alarm"),
              "decision": d.decision if d else None}
        if d and d.decision == "false_alarm":
            res.decided_false_alarm.append({"pred_key": p.key, "reviewer": d.reviewer})
        res.fp.append(fp)
    return res
