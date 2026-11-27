"""Повторное ревью сохранённого отчёта. Запуск: python -m bcc_review.v2.refute ОТЧЁТ ИСХОДНИК."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from bcc_review.contracts import ProviderError

from . import docview, prompts
from .llm import LLMClient, LLMError
from .pipeline import DEFAULTS, make_llm
from .providers import doctor
from .quotes import verify_quote
from .render import jsonout
from .rules.injection import ADDRESSEE, OVERRIDE
from .stages.judge import CONFLICT_KINDS
from .types import INT, STR, obj

DECISION = obj({
    "id": STR, "decision": {"type": "string", "enum": ["confirmed", "partial", "refuted"]},
    "basis": {"type": "string", "enum": ["none", "rule", "excluded", "precedence"]},
    "line": INT, "quote": STR, "subject": STR, "outcome": STR, "reason": STR, "remaining": STR,
})
SCHEMA = obj({"decisions": {"type": "array", "items": DECISION}})
LOWER = {"critical": "major", "major": "minor"}
# У одной из сторон может быть оговорка. Сам факт, что она написана позже, приоритет не задаёт.
PRECEDENCE = re.compile(
    r"приоритет|преимуществ|преоблада|имеет силу над|вместо|исключени|за исключением|несмотря|"
    r"независимо от|даже (?:при|если)|во всех остальных|в остальных случаях|в первую очередь|"
    r"до (?:всех |любых |остальных |других )?проверок|без (?:других |остальных )?проверок|"
    r"перекрывает|отменяет (?:правило|действие)|"
    r"takes precedence|overrides?|except(?:ion)?\b|regardless of|even if|before (?:any|all) other",
    re.IGNORECASE,
)
EXPLICIT_OVERRIDE = re.compile(
    r"при (?:пересечении|расхождении|конфликте)|приоритет\s+(?:над|перед)|преимущество\s+перед|"
    r"отменяет (?:правило|действие)|вместо (?:правила|пункта)|несмотря на (?:правило|пункт)|"
    r"takes precedence over|overrides? (?:rule|section)", re.I)
UNRESOLVED_PRECEDENCE = re.compile(
    r"(?:приоритет|порядок)\w*[^.!?\n]{0,70}?(?:не (?:определ[её]н|установлен|задан|выбран|согласован)|"
    r"подлежит согласованию|предстоит определить)|(?:не (?:определ[её]н|установлен|задан)|отсутствует)"
    r"[^.!?\n]{0,30}?приоритет|(?:правила|исходы) равнозначны|(?:priority|precedence) (?:is )?"
    r"(?:undefined|unspecified|unresolved|not (?:defined|set))", re.I)
STOP_SUBJECT = frozenset("для при если когда после перед тогда должен должна должно может только каждого "
                         "каждый этого такой такая with when then the shall must".split())


def _words(s: str) -> str:
    return " ".join(s.split())


def _protect(finding: dict, pairs: set[str]) -> bool:
    if finding["id"] in pairs:
        return True
    evidence = {e.get("quote", "").strip() for e in finding.get("evidence", []) if e.get("quote")}
    description = " ".join(str(finding.get(k, "")) for k in ("title", "problem", "scenario"))
    conflict = re.search(r"противореч|несовместим|взаимоисключ|два (?:разных )?(?:исхода|ответа)|"
                         r"conflict|incompatible|contradict", description, re.I)
    return len(evidence) >= 2 and (finding.get("kind") in CONFLICT_KINDS
                                   or finding.get("criterion") == "set_consistent" or bool(conflict))


def _proof(view: dict, finding: dict, d: dict, protected: bool) -> tuple[dict | None, str]:
    if not d["reason"].strip() or (d["decision"] == "partial") != bool(d["remaining"].strip()):
        return None, "Не обоснован результат или оставшаяся часть проблемы."
    q, subject, outcome = (_words(d[k]) for k in ("quote", "subject", "outcome"))
    if d["basis"] == "none" or not (subject and outcome) or subject == outcome or subject not in q or outcome not in q:
        return None, "В цитате не указаны предмет и определённый исход."
    match = verify_quote(view, q, line_hint=d["line"])
    if (not match or match["line_start"] != d["line"] or match["verified"] == "fuzzy"
            or q not in _words(docview.text_of(view, match["line_start"], match["line_end"]))):
        return None, "Дословная непрерывная цитата в указанном месте не найдена."
    context = docview.text_of(view, match["line_start"], match["line_end"])
    if OVERRIDE.search(context) or ADDRESSEE.search(context):
        return None, "Адресованное проверяющему указание не определяет поведение системы."
    sides = [_words(e.get("quote", "")).casefold() for e in finding.get("evidence", [])]
    claim = " ".join([*sides, *(str(finding.get(k, "")) for k in ("title", "problem", "scenario", "impact"))]).casefold()
    terms = re.findall(r"[^\W_]+", subject)
    if not any(t.casefold()[:5] in claim for t in terms if t.casefold() not in STOP_SUBJECT
               and (len(t) >= 3 or t.isupper() or t.isdigit())):
        return None, "Предмет процитированной нормы не привязан к исходному замечанию."
    if protected:
        if (d["basis"] != "precedence" or not PRECEDENCE.search(q) or UNRESOLVED_PRECEDENCE.search(q)
                or (len(outcome) < 2 and not outcome.isdigit())
                or not any(subject.casefold() in side for side in sides)
                or not any(outcome.casefold() in side for side in sides)
                or all(outcome.casefold() in side for side in sides)
                or (any(q.casefold() in s for s in sides) and not EXPLICIT_OVERRIDE.search(q))):
            return None, "Для пересечения правил не доказан явный приоритет одного из исходов."
    return {"quote": q, "line_start": match["line_start"], "line_end": match["line_end"],
            "page": match.get("page"), "section": match.get("section", "")}, ""


def _update_derived(report: dict, removed: set[str], changed: set[str]) -> None:
    if not changed:
        return
    active = {f["id"]: f for f in jsonout.open_findings(report)}
    questions = []
    for q in report.get("questions", []):
        ids = q.get("finding_ids", [])
        if ids and changed.intersection(ids):
            q["finding_ids"] = [i for i in ids if i not in removed]
            if not q["finding_ids"]:
                continue
            q["blocking"] = any(active.get(i, {}).get("severity") == "critical" for i in q["finding_ids"])
        questions.append(q)
    report["questions"] = questions
    for table in ("checklist", "pair_checks", "acceptance_checks", "glossary"):
        for row in report.get(table, []):
            ids = row.get("finding_ids", [])
            if not removed.intersection(ids):
                continue
            row["finding_ids"] = [i for i in ids if i not in removed]
            if table == "checklist":
                row["comment"] = ("После повторной проверки см. " + ", ".join(row["finding_ids"])
                                  if row["finding_ids"] else "Основание исходной оценки снято повторной проверкой.")
                if not row["finding_ids"]:
                    row["answer"] = "Нет данных"
            elif not row["finding_ids"] and table in ("pair_checks", "acceptance_checks") and row.get("verdict") == "conflict":
                # Не объявляем все условия совместимыми по одному снятому замечанию.
                row["verdict"] = "undefined"
    rule = jsonout.rule_verdict(report)
    names = {"no": "нельзя", "yes": "можно", "conditional": "с условиями", "none": "не определено",
             "undetermined": "не определено"}
    counts = Counter(f.get("severity") for f in active.values())
    report["verdict"] = {**rule, "summary": (
        f"После повторной проверки разработку начинать {names[rule['development']]}, "
        f"тестирование — {names[rule['testing']]}. Критичных замечаний {counts['critical']}, "
        f"существенных {counts['major']}."),
        "fix_first": [i for i in report.get("verdict", {}).get("fix_first", [])
                      if i in active and active[i].get("severity") in LOWER]}


def refute_report(report: dict, view: dict, llm: LLMClient, *, batch_size: int = 14) -> dict:
    """Копия отчёта с решением по каждому действующему critical/major и отдельным паспортом прохода."""
    if report.get("schema") != jsonout.SCHEMA_ID or not isinstance(report.get("findings"), list):
        raise ValueError("Нужен отчёт bcc-review/2 с массивом findings.")
    if not view.get("sha256") or report.get("document", {}).get("sha256") != view["sha256"]:
        raise ValueError("Исходник отличается от редакции документа, по которой получен отчёт.")
    if report.get("refutation"):
        raise ValueError("Этот отчёт уже прошёл опровержение. Для повтора возьмите исходный JSON.")
    if batch_size <= 0:
        raise ValueError("Размер пакета должен быть положительным.")
    result = copy.deepcopy(report)
    eligible = [f for f in jsonout.open_findings(result) if f.get("severity") in LOWER
                and f.get("status") != "rejected"]
    ids = [f.get("id") for f in result["findings"]]
    if not all(isinstance(i, str) and i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("В исходном отчёте требуются уникальные идентификаторы замечаний.")
    pairs = {i for p in result.get("pair_checks", []) if p.get("same_subject") is True
             and p.get("verdict") == "conflict" for i in p.get("finding_ids", [])}
    audit, removed, changed = [], set(), set()
    started = time.monotonic()
    before = dict(llm.stats["by_stage"].get("refute", {}))
    previous_calls = llm.stats["calls"]
    numbered = docview.numbered(view)
    batches = 0
    for start in range(0, len(eligible), batch_size):
        batch = eligible[start:start + batch_size]
        cards = [{k: f.get(k) for k in ("id", "kind", "severity", "title", "problem", "scenario", "impact", "evidence")}
                 for f in batch]
        system, user = prompts.task("refute", document=numbered, findings=json.dumps(cards, ensure_ascii=False))
        by_id = defaultdict(list)
        error = ""
        try:
            batches += 1
            answer = llm.ask("refute", system or prompts.system(), user, SCHEMA, expand=False)
            for decision in answer["decisions"]:
                by_id[decision["id"]].append(decision)
        except LLMError as exc:
            error = f"{exc.kind}: {exc.message}"
        for f in batch:
            fid = f["id"]
            entry = {"id": fid, "before": f["severity"], "after": f["severity"], "decision": "unreviewed"}
            audit.append(entry)
            if len(by_id[fid]) != 1:
                entry["reason"] = error or "В ответе отсутствует однозначное решение для этого идентификатора."
                continue
            d = by_id[fid][0]
            if not d["reason"].strip():
                entry["reason"] = "Модель не привела обоснования."
                continue
            if d["decision"] == "confirmed":
                entry.update(decision="confirmed", reason=d["reason"])
                continue
            proof, reason = _proof(view, f, d, _protect(f, pairs))
            if reason:
                entry.update(decision="guarded", proposed=d["decision"], reason=reason)
                continue
            entry.update(decision=d["decision"], basis=d["basis"], reason=d["reason"], evidence=proof,
                         remaining=d["remaining"], subject=d["subject"], outcome=d["outcome"])
            changed.add(fid)
            if d["decision"] == "refuted":
                removed.add(fid)
                entry["after"] = None
                result.setdefault("rejected", []).append({**f, "source": "refute", "reason_code": "refuted",
                                                         "reason": d["reason"], "counterevidence": proof})
            else:
                f["severity"] = entry["after"] = LOWER[f["severity"]]
                entry["original_problem"] = f.get("problem", "")
                f["problem"] = d["remaining"]
                f["counterevidence"] = proof
                if f["severity"] == "minor":
                    f.update(blocks="none", priority=0)
    result["findings"] = [f for f in result["findings"] if f["id"] not in removed]
    # finalize восстанавливает снятые ответами из findings_before; решение опровержения
    # не является ответом владельца. Сохраняем исходный снимок в истории при пересечении ID.
    prior_findings = None
    if result.get("clarification") and any(f.get("id") in removed for f in result.get("findings_before", [])):
        prior_findings = result.pop("findings_before")
    _update_derived(result, removed, changed)
    result = jsonout.finalize(result)
    after = llm.stats["by_stage"].get("refute", {})
    result["refutation"] = {
        "status": "partial" if any(e["decision"] == "unreviewed" for e in audit) else "complete",
        "provider": llm.provider_name, "models_used": list(llm.stats["models_used"]),
        "models_scope": "client_history" if previous_calls else "this_pass",
        "seconds": round(time.monotonic() - started, 3), "batches": batches,
        **{k: after.get(k, 0) - before.get(k, 0) for k in ("calls", "cached", "tokens_in", "tokens_out")},
        "decisions": audit,
    }
    if prior_findings is not None:
        result["refutation"]["findings_before_answers"] = prior_findings
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path)
    p.add_argument("source", type=Path)
    p.add_argument("--provider", default="gemini")
    p.add_argument("--model")
    p.add_argument("--batch-size", type=int, default=14)
    p.add_argument("--mock-dir", type=Path, help="Записанные ответы этапа для автономной проверки")
    args = p.parse_args(argv)
    try:
        original = jsonout.read(args.report)
        view = docview.load(args.source)
        doctor.load_dotenv()
        llm, _ = make_llm({**DEFAULTS, "provider": args.provider, "model": args.model,
                           "mock_dir": args.mock_dir, "cache": False}, None, args.source)
        if llm is None:
            raise ValueError("Для опровержения требуется модель или запись её ответов.")
        result = refute_report(original, view, llm, batch_size=args.batch_size)
        out = args.report.with_name(args.report.stem + ".refuted.json")
        if out.resolve() == args.source.resolve():
            raise ValueError("Путь выходного отчёта совпадает с исходным документом.")
        with tempfile.NamedTemporaryFile(dir=out.parent, delete=False, suffix=".tmp") as tmp:
            temp_path = Path(tmp.name)
        try:
            jsonout.write(result, temp_path, strict=True)
            os.replace(temp_path, out)
        finally:
            temp_path.unlink(missing_ok=True)
        print(out)
        return 0 if result["refutation"]["status"] == "complete" else 3
    except (OSError, ValueError, ProviderError, jsonout.SchemaError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
