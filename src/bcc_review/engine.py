"""Диспетчер ревью: ``run_review(input_path, report_md, *, options=None) -> Report``.

Порядок этапов: чтение → (ответы аналитика и редакция) → нарезка → правила → проверка каждого
требования → проверка набора → факты и покрытие → проверка цитат → проверка смысла → объединение
по первопричине → вопросы → чек-лист банка → сравнение редакций → вердикт → запись.
Каждый этап отмечается в паспорте с фактическими вызовами; результат этапа пишется атомарно.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import __version__
from . import contracts as C
from .contracts import (INDIVIDUAL_CRITERIA, PARTIAL_READ_CODES, AskError, ContractError, ProviderError, RunOptions)
from .runtime.asker import Asker
from .runtime.context import ContextBuilder
from .runtime.core import Budget, Cache, StageStats, Tracer, atomic_write_json, utc_now
from .runtime.merge import merge_candidates
from .runtime.mock import MockAdapter
from .runtime.modules import Modules
from .runtime.verdict import build_summary, build_verdict, default_blocks

READERS = {".md": "read_text", ".markdown": "read_text", ".txt": "read_text", ".pdf": "read_pdf", ".docx": "read_docx"}
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "gemini": "gemini-2.5-flash", "mock": "mock-1"}
MODEL_ENV = {"anthropic": "ANTHROPIC_MODEL", "gemini": "GEMINI_MODEL"}
LLM_STAGES = ("individual", "cross", "verify_meaning", "questions", "bank")
SLEEP: Callable[[float], None] = time.sleep  # тесты подменяют, чтобы не ждать Retry-After


class UsageError(ValueError):
    """Ошибка входных данных: неподдерживаемый формат, нет файла."""


def load_dotenv(path: str | Path = ".env") -> None:
    """Минимальный загрузчик .env: переменные окружения имеют приоритет над файлом."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def agent_commit() -> Optional[str]:
    env = os.environ.get("BCC_AGENT_COMMIT")
    if env:
        return env
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        if sha.returncode != 0:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                               capture_output=True, text=True, timeout=5)
        return sha.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


class _Disabled:
    """ask, который сразу сообщает причину недоступности модели (без физических вызовов)."""

    def __init__(self, reason: str):
        self.reason = reason

    def __call__(self, stage: str, payload: Any, schema: Any) -> dict:
        raise AskError(stage, "provider_unavailable", self.reason)


class Engine:
    def __init__(self, input_path: str | Path, report_md: str | Path, options: RunOptions):
        self.opts = options
        self.input_path = Path(input_path)
        self.out_md = Path(report_md)
        self.out_json = self.out_md.with_suffix(".json")
        if not self.input_path.is_file():
            raise UsageError(f"входной файл не найден: {self.input_path}")
        suffix = self.input_path.suffix.lower()
        if suffix not in READERS:
            raise UsageError(f"формат {suffix or '(без расширения)'} не поддерживается: {', '.join(READERS)}")
        self.source_sha = C.sha256_file(self.input_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = options.run_id or f"{stamp}-{self.source_sha[:8]}-{secrets.token_hex(2)}"
        self.artifacts = Path(options.artifacts_dir) if options.artifacts_dir else \
            self.out_md.parent / f"{self.out_md.stem}.artifacts"
        self.started_at = utc_now()
        self.t0 = time.monotonic()
        self.stats = StageStats()
        self.mods = Modules()
        self.tracer = Tracer(self.artifacts / "trace.jsonl" if options.trace else None, self.run_id)
        self.warnings: list[Any] = []
        self.status_reasons: list[str] = []
        self.stage_no = 0
        self.decisions: list[dict[str, Any]] = []
        self.revision_of: Optional[str] = None
        self.reviewed_path = self.input_path

    # ------------------------------------------------------------------ служебное
    def save_stage(self, name: str, obj: Any) -> None:
        self.stage_no += 1
        try:
            atomic_write_json(self.artifacts / "stages" / f"{self.stage_no:02d}-{name}.json", obj)
        except (OSError, TypeError, ValueError) as exc:
            self.warnings.append({"code": "artifact_write", "message": f"не записан результат этапа {name}: {exc}"})

    def mark(self, stage: str, status: str, reason: Optional[str] = None, *, implementation: Optional[str] = None,
             t: Optional[float] = None) -> None:
        self.stats.mark(stage, status, reason, implementation=implementation,
                        duration_s=(time.monotonic() - t) if t is not None else None)
        self.tracer.emit("stage_end", stage=stage, status=status, reason=reason, implementation=implementation)

    def warn(self, code: str, message: str, stage: Optional[str] = None) -> None:
        w = {"code": code, "message": message}
        if stage:
            w["stage"] = stage
        self.warnings.append(w)

    # ------------------------------------------------------------------ провайдер
    def setup_provider(self) -> None:
        o = self.opts
        self.provider = "none" if o.offline_lint else o.provider
        if self.provider not in C.PROVIDERS:
            raise UsageError(f"неизвестный провайдер {self.provider!r}: anthropic | gemini | mock")
        self.requested_model = None
        self.adapter = None
        self.adapter_label = None
        self.unavailable: Optional[str] = None
        if self.provider == "none":
            self.unavailable = "модель не вызывалась: режим --offline-lint (только детерминированные правила)"
            return
        self.requested_model = o.model or os.environ.get(MODEL_ENV.get(self.provider, ""), "") or DEFAULT_MODELS[self.provider]
        try:
            if self.provider == "mock":
                self.adapter = MockAdapter(o.mock_script, model=o.model or "mock-1")
                self.adapter_label = "runtime.mock:MockAdapter"
            else:
                res = self.mods.get(self.provider)
                if res.func is None:
                    raise ProviderError("not_configured", f"адаптер {self.provider} не подключён: {res.error}")
                self.adapter = res.func()
                self.adapter_label = res.label
        except ProviderError as exc:
            self.unavailable = f"{self.provider}: {exc.kind}: {exc.message}"
        except Exception as exc:  # адаптер команды упал при создании — работаем без модели
            self.unavailable = f"{self.provider}: адаптер не создан: {type(exc).__name__}: {exc}"

    def make_ask(self, context: ContextBuilder) -> Optional[Callable]:
        if self.adapter is None:
            return None
        cache_dir = self.opts.cache_dir or os.environ.get("BCC_CACHE_DIR") or str(Path.cwd() / ".bcc_cache")
        self.cache = Cache(cache_dir, enabled=self.opts.use_cache)
        self.budget = Budget(self.opts.max_calls, self.opts.max_seconds, self.opts.max_tokens)
        self.asker = Asker(adapter=self.adapter, provider=self.provider, model=self.requested_model, budget=self.budget,
                           cache=self.cache, stats=self.stats, tracer=self.tracer, context=context,
                           max_retries=self.opts.max_retries, timeout_s=self.opts.timeout_s, sleep=SLEEP)
        engine = self

        def ask(stage: str, payload: Any, schema: Any) -> dict:
            if engine.unavailable:
                raise AskError(stage, "provider_unavailable", engine.unavailable)
            try:
                return engine.asker(stage, payload, schema)
            except C.BudgetExhausted:
                raise
            except AskError as exc:
                if exc.kind in ("auth", "not_configured", "quota", "not_found"):
                    # без ключа или модели повторять бессмысленно: остальные этапы — без модели
                    engine.unavailable = f"{engine.provider}: {exc.kind}: {exc.message}"
                raise

        return ask

    # ------------------------------------------------------------------ чтение
    def read(self, path: Path) -> dict[str, Any]:
        slot = READERS[path.suffix.lower()]
        res = self.mods.get(slot)
        if res.func is None:
            raise UsageError(f"чтение {path.suffix} недоступно: модуль {slot} не подключён ({res.error})")
        t = time.monotonic()
        doc = res.func(path)
        errs = C.validation_errors(doc, C.subschema("Document"))
        if errs and res.origin == "team":
            self.warn("contract_violation", f"{res.label}: Document нарушает контракт ({errs[0]}); использован резерв", "read")
            fb = self.mods.get(slot, prefer_fallback=True)
            if fb.func is not None:
                doc, res = fb.func(path), fb
                errs = C.validation_errors(doc, C.subschema("Document"))
        if errs:
            raise ContractError("Document нарушает контракт: " + "; ".join(errs[:5]))
        self.mark("read", "ok", implementation=res.label, t=t)
        return doc

    # ------------------------------------------------------------------ основной сценарий
    def run(self) -> dict[str, Any]:
        o = self.opts
        self.tracer.emit("run_start", provider=o.provider, requested_model=o.model)
        self.setup_provider()
        document = self.read(self.input_path)
        self.check_partial_read(document)

        if o.answers_path:
            document = self.apply_answers(document)

        context = ContextBuilder(document, full_context_chars=o.full_context_chars)
        ask = self.make_ask(context) if not self.unavailable else None
        if ask is None:
            ask_or_none = None
        else:
            ask_or_none = ask

        # нарезка
        t = time.monotonic()
        inv_mod = self.mods.get("build_inventory")
        try:
            inv = inv_mod.func(document, ask_or_none)
        except AskError as exc:
            self.warn("stage_degraded", f"нарезка с моделью не удалась ({exc.kind}); детерминированная нарезка", "inventory")
            inv = inv_mod.func(document, None)
        requirements = self.normalize_requirements(document, inv.get("requirements", []))
        excluded = list(inv.get("excluded", []))
        for w in inv.get("warnings", []):
            self.warn("inventory", str(w), "inventory")
        if inv.get("unprocessed_block_ids"):
            self.warn("unprocessed_blocks", "блоки не попали ни в требования, ни в исключения: "
                      + ", ".join(inv["unprocessed_block_ids"][:30]), "inventory")
        self.mark("inventory", "ok" if requirements else "failed",
                  None if requirements else "не выделено ни одного требования", implementation=inv_mod.label, t=t)
        self.save_stage("inventory", inv)
        context.set_requirements(requirements)
        self.context_policy = context.policy

        # правила (всегда, без модели)
        t = time.monotonic()
        try:
            from .runtime.fallback.rules import lint
            rules_out = lint(document, requirements)
            self.mark("rules", "ok", implementation="fallback:bcc_review.runtime.fallback.rules:lint", t=t)
        except ImportError:
            rules_out = {"candidates": [], "checks": [], "warnings": ["модуль правил не найден"]}
            self.mark("rules", "failed", "модуль детерминированных правил не найден", t=t)
        self.save_stage("rules", rules_out)

        # проверка каждого требования
        ind = self.run_individual(document, requirements, ask_or_none)
        # проверка набора
        cross = self.run_cross(document, requirements, ask_or_none, inv.get("fact_hints") or [])

        # опоры, смысл, объединение
        candidates = []
        for src in (rules_out.get("candidates", []), ind.get("candidates", []), cross.get("candidates", [])):
            candidates.extend(src)
        verified, rejected, audit = self.verify_candidates(document, candidates, ask_or_none)
        findings = self.build_findings(verified, requirements)
        checks = self.build_checks(requirements, rules_out.get("checks", []) + ind.get("checks", []), findings,
                                   ind.get("failed") or {}, ask_or_none is not None)
        facts, coverage = self.build_facts_coverage(document, cross)

        # вопросы и чек-лист банка
        questions = self.run_questions(document, findings, ask_or_none)
        bank = self.run_bank(document, requirements, findings, ask_or_none)

        report = C.empty_report_skeleton()
        report.update(document=document, requirements=requirements, checks=checks, findings=findings, facts=facts,
                      coverage=coverage, questions=questions, checklist=bank.get("checklist", []),
                      test_cases=bank.get("test_cases", []), decisions=self.decisions, excluded=excluded,
                      rejected=rejected)

        # паспорт (до сравнения: сравнению нужен список незавершённых этапов)
        report["run"] = self.build_run(audit)
        if o.compare_path:
            report["diff"] = self.run_compare(report, context)
            report["run"] = self.build_run(audit)
        t = time.monotonic()
        report["verdict"] = build_verdict(findings, report["run"], allow_partial_ready=o.allow_partial_ready)
        report["summary"] = build_summary(report)
        self.mark("verdict", "ok", t=t)
        report["run"] = self.build_run(audit)
        report["warnings"] = self.warnings
        self.finalize(report)
        return report

    # ------------------------------------------------------------------ этапы
    def check_partial_read(self, document: dict[str, Any]) -> None:
        bad = [w for w in document.get("warnings", []) if isinstance(w, dict) and w.get("code") in PARTIAL_READ_CODES]
        if bad:
            self.status_reasons.append("документ прочитан не полностью: " + "; ".join(w.get("message", w["code"]) for w in bad[:3]))
            self.mark("read", "partial", "документ прочитан не полностью")

    def apply_answers(self, document: dict[str, Any]) -> dict[str, Any]:
        t = time.monotonic()
        parsed = self.mods.get("parse_answers")
        out = parsed.func(self.opts.answers_path, document)
        if isinstance(out, list):
            out = {"decisions": out, "warnings": []}
        for w in out.get("warnings", []):
            self.warn("answers", str(w), "answers")
        self.decisions = out.get("decisions", [])
        patcher = self.mods.get("propose_patch")
        edits = []
        for d in self.decisions:
            p = patcher.func(document, None, d)
            edits.extend(p.get("edits", []))
            for w in p.get("warnings", []):
                self.warn("answers", str(w), "answers")
        if not edits:
            self.mark("answers", "partial", "в ответах нет применимых правок: проверяется исходная редакция",
                      implementation=parsed.label, t=t)
            return document
        rev_path = self.out_md.parent / f"{self.input_path.stem}.rev-{self.run_id[:16]}{self.input_path.suffix}"
        writer = self.mods.get("write_revision")
        try:
            writer.func(document, edits, rev_path, source_path=self.input_path)
        except TypeError:
            writer.func(document, edits, rev_path)
        self.revision_of = document["id"]
        self.reviewed_path = rev_path
        revised = self.read(rev_path)
        self.check_partial_read(revised)
        self.mark("answers", "ok", f"применено правок: {len(edits)}; исходный файл не изменён, редакция: {rev_path.name}",
                  implementation=writer.label, t=t)
        return revised

    def normalize_requirements(self, document: dict[str, Any], reqs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {b["id"]: b for b in document["blocks"]}
        out = []
        for i, r in enumerate(reqs, 1):
            rid = r.get("id") or f"R-{i:02d}"
            block_ids = [b for b in r.get("block_ids", []) if b in by_id]
            ev = r.get("evidence") or [{"block_id": b, "start": 0, "end": len(by_id[b]["text"]), "quote": by_id[b]["text"]}
                                       for b in block_ids if by_id[b]["text"]]
            item = {"id": rid, "source_id": r.get("source_id"), "text": r.get("text", ""), "block_ids": block_ids,
                    "evidence": ev, "hints": r.get("hints", []), "kind": r.get("kind", "other"),
                    "section": r.get("section") or (by_id[block_ids[0]]["section"] if block_ids else []),
                    "review_status": "not_reviewed", "review_reason": "проверка ещё не выполнялась"}
            errs = C.validation_errors(item, C.subschema("Requirement"))
            if errs:
                self.warn("contract_violation", f"требование {rid} пропущено: {errs[0]}", "inventory")
                continue
            out.append(item)
        return out

    def run_individual(self, document, requirements, ask) -> dict[str, Any]:
        t = time.monotonic()
        mod = self.mods.get("review_individual")
        try:
            out = mod.func(document, requirements, ask)
        except AskError as exc:
            self.mark("individual", "failed", f"{exc.kind}: {exc.message}"[:300], implementation=mod.label, t=t)
            out = mod.func(document, requirements, None)
            out.setdefault("failed", {r["id"]: f"этап individual: {exc.kind}" for r in requirements})
            self.save_stage("individual", out)
            return out
        failed = out.get("failed") or {}
        if ask is None:
            self.mark("individual", "skipped", self.unavailable or "модель недоступна", implementation=mod.label, t=t)
        elif failed and len(failed) >= len(requirements):
            self.mark("individual", "failed", next(iter(failed.values())), implementation=mod.label, t=t)
        elif failed:
            self.mark("individual", "partial", f"не проверено требований: {len(failed)}", implementation=mod.label, t=t)
        else:
            self.mark("individual", "ok", implementation=mod.label, t=t)
        self.save_stage("individual", out)
        return out

    def run_cross(self, document, requirements, ask, fact_hints) -> dict[str, Any]:
        t = time.monotonic()
        mod = self.mods.get("review_set")
        try:
            out = mod.func(document, requirements, ask, fact_hints=fact_hints)
            if ask is None:
                self.mark("cross", "skipped", self.unavailable or "модель недоступна", implementation=mod.label, t=t)
            else:
                self.mark("cross", "ok", implementation=mod.label, t=t)
        except AskError as exc:
            self.mark("cross", "failed", f"{exc.kind}: {exc.message}"[:300], implementation=mod.label, t=t)
            out = mod.func(document, requirements, None, fact_hints=fact_hints)
        self.save_stage("cross", out)
        return out

    def resolve(self, document, candidate) -> dict[str, Any]:
        mod = self.mods.get("resolve_candidate")
        res = dict(mod.func(document, candidate))
        if "witness" not in res and candidate.get("witness"):
            hint = self.mods.get("resolve_hint").func
            ra, rb = hint(document, candidate["witness"].get("hint_a") or {}), hint(document, candidate["witness"].get("hint_b") or {})
            res["witness"] = None
            if ra["status"] == rb["status"] == "matched":
                w = candidate["witness"]
                res["witness"] = {"input": w.get("input", ""), "outcome_a": w.get("outcome_a", ""),
                                  "outcome_b": w.get("outcome_b", ""), "evidence_a": ra["evidence"], "evidence_b": rb["evidence"]}
            else:
                res["anchor_status"] = "incomplete"
        return res

    def verify_candidates(self, document, candidates, ask):
        t = time.monotonic()
        audit = {"checked": 0, "confirmed": 0, "ambiguous": 0, "rejected": 0}
        verified, rejected = [], []
        hint_mod = self.mods.get("resolve_hint")
        for n, c in enumerate(candidates, 1):
            cid = f"C-{n:03d}"
            errs = C.validation_errors(c, C.subschema("Candidate"))
            if errs:
                rejected.append({"candidate": c, "reason": f"нарушает контракт Candidate: {errs[0]}", "stage": "evidence"})
                continue
            res = self.resolve(document, c)
            results = res.get("hint_results")
            if results is None:  # модуль №07 не вернул подробности — пересчитать для учёта
                hs = list(c.get("hints") or [])
                if c.get("witness"):
                    hs += [c["witness"].get("hint_a") or {}, c["witness"].get("hint_b") or {}]
                results = [hint_mod.func(document, h) for h in hs]
            for r in results:
                audit["checked"] += 1
                key = {"matched": "confirmed", "ambiguous": "ambiguous"}.get(r["status"], "rejected")
                audit[key] += 1
            item = {**c, "cid": cid, "evidence": res.get("evidence") or [], "anchor_status": res["anchor_status"],
                    "witness": res.get("witness"), "notes": list(res.get("warnings") or []),
                    "meaning_status": "deterministic" if c.get("source") == "rules" else "unchecked",
                    "meaning_reason": "детерминированное правило: вывод следует из найденного текста"
                    if c.get("source") == "rules" else "смысл не проверялся"}
            if not item["evidence"]:
                rejected.append({"candidate": c, "reason": "ни одна цитата не найдена в документе: "
                                 + "; ".join(item["notes"])[:300], "stage": "evidence"})
                continue
            verified.append(item)
        self.mark("evidence", "ok", implementation=self.mods.get("resolve_candidate").label, t=t)

        # подтверждение смысла — отдельный от цитаты результат
        t = time.monotonic()
        llm_items = [v for v in verified if v.get("source") != "rules" and v["anchor_status"] == "supported"]
        if ask is None:
            self.mark("verify_meaning", "skipped", self.unavailable or "модель недоступна", t=t)
        elif llm_items:
            from .runtime.fallback.llm_stages import verify_meaning
            blocks = {b["id"]: b for b in document["blocks"]}
            payload_items = [{"cid": v["cid"], "kind": v["kind"], "severity": v["severity"], "title": v["title"],
                              "impact": v["impact"], "claim": (v.get("witness") or {}).get("input", "") or v.get("recommendation", ""),
                              "quotes": [{"block_id": e["block_id"], "quote": e["quote"],
                                          "block_text": blocks[e["block_id"]]["text"][:600]} for e in v["evidence"][:4]]}
                             for v in llm_items]
            verdicts: dict[str, Any] = {}
            failures = []
            for n, start in enumerate(range(0, len(payload_items), 40), 1):
                try:
                    verdicts.update(verify_meaning(document, payload_items[start:start + 40],
                                                   lambda s, p, sc, n=n: ask(f"verify_meaning#{n}", p, sc)))
                except AskError as exc:
                    failures.append(f"{exc.kind}: {exc.message}"[:200])
            for v in llm_items:
                verdict = verdicts.get(v["cid"])
                if verdict is None:
                    v["meaning_reason"] = "проверка смысла не завершилась" if failures else "критик не вернул оценку"
                    continue
                v["meaning_reason"] = verdict["reason"]
                if verdict["severity"] != v["severity"]:
                    v["notes"].append(f"серьёзность скорректирована критиком: {v['severity']} → {verdict['severity']}")
                    v["severity"] = verdict["severity"]
                v["meaning_status"] = {"confirmed": "confirmed", "uncertain": "uncertain"}.get(verdict["verdict"], "rejected")
            kept = []
            for v in verified:
                if v["meaning_status"] == "rejected":
                    rejected.append({"candidate": {k: v[k] for k in v if k not in ("evidence",)},
                                     "reason": "критик: " + v["meaning_reason"], "stage": "verify_meaning"})
                else:
                    kept.append(v)
            verified = kept
            if failures and len(failures) == (len(payload_items) + 39) // 40:
                self.mark("verify_meaning", "failed", failures[0], t=t)
            elif failures:
                self.mark("verify_meaning", "partial", failures[0], t=t)
            else:
                self.mark("verify_meaning", "ok", t=t)
        else:
            self.mark("verify_meaning", "ok", "нет кандидатов модели для проверки", t=t)
        audit["note"] = ("Учтена каждая подсказка-цитата кандидатов (включая опоры witness): confirmed — найдена в тексте "
                         "блока, ambiguous — в нескольких блоках, rejected — не найдена. Смысл проверяется отдельно "
                         "(meaning_status).")
        self.save_stage("evidence", {"audit": audit, "verified": len(verified), "rejected": len(rejected)})
        return verified, rejected, audit

    def build_findings(self, verified, requirements) -> list[dict[str, Any]]:
        t = time.monotonic()
        clusters = merge_candidates(verified)
        order = {r["id"]: i for i, r in enumerate(requirements)}
        sev = {"critical": 0, "major": 1, "minor": 2}
        findings = []
        for c in clusters:
            notes = list(c.get("notes", []))
            if c["severity"] == "critical" and (not (c.get("impact") or "").strip() or not (c.get("blocked_decision") or "").strip()):
                c["severity"] = "major"
                notes.append("понижено до существенного: не указано бизнес-последствие или блокируемое решение")
            if c["kind"] == "conflict" and not c.get("witness"):
                notes.append("конфликт без подтверждённой пары опор: требует проверки")
            confirmed = (c["anchor_status"] == "supported" and c["meaning_status"] in ("confirmed", "deterministic")
                         and not (c["kind"] == "conflict" and not c.get("witness")))
            f = {"id": "", "scope": c["scope"], "kind": c["kind"], "criterion": c["criterion"], "severity": c["severity"],
                 "title": c["title"], "impact": c.get("impact", ""), "req_ids": [r for r in c["req_ids"] if r in order],
                 "hints": c.get("hints", []), "evidence": c["evidence"],
                 "status": "confirmed" if confirmed else "needs_review", "anchor_status": c["anchor_status"],
                 "meaning_status": c["meaning_status"], "meaning_reason": c.get("meaning_reason", ""),
                 "recommendation": c.get("recommendation", ""), "blocked_decision": c.get("blocked_decision", ""),
                 "blocks": [], "witness": c.get("witness"), "inspected_block_ids": c.get("inspected_block_ids", []),
                 "merged_from": [c["cid"]] + [x for x in c.get("merged_from", []) if x != c["cid"]],
                 "cause": c.get("cause"), "source": c.get("source", "llm"), "stage": c.get("stage", ""), "notes": notes}
            if c.get("rule_id"):
                f["rule_id"] = c["rule_id"]
            f["blocks"] = default_blocks(f)
            findings.append(f)
        block_pos = {}
        for f in findings:
            ev = f["evidence"][0] if f["evidence"] else None
            block_pos[id(f)] = (ev["block_id"], ev["start"]) if ev else ("~", 0)
        findings.sort(key=lambda f: (sev[f["severity"]], 0 if f["status"] == "confirmed" else 1, block_pos[id(f)]))
        for n, f in enumerate(findings, 1):
            f["id"] = f"F-{n:03d}"
        self.mark("merge", "ok", f"кандидатов {len(verified)} → замечаний {len(findings)}", t=t)
        return findings

    def build_checks(self, requirements, raw_checks, findings, failed, llm_available) -> list[dict[str, Any]]:
        req_ids = {r["id"] for r in requirements}
        checks: dict[tuple[str, str], dict[str, Any]] = {}
        llm_seen: dict[str, set[str]] = {}
        for ch in raw_checks:
            if ch.get("req_id") not in req_ids or ch.get("criterion") not in INDIVIDUAL_CRITERIA:
                continue
            key = (ch["req_id"], ch["criterion"])
            prev = checks.get(key)
            if ch.get("source") == "llm":
                llm_seen.setdefault(ch["req_id"], set()).add(ch["criterion"])
            if prev is None or (prev["status"] != "issue" and ch["status"] == "issue"):
                checks[key] = {"req_id": ch["req_id"], "criterion": ch["criterion"], "status": ch["status"],
                               "reason": ch.get("reason", ""), "finding_ids": [], "source": ch.get("source", "llm")}
        for f in findings:
            if f["criterion"] not in INDIVIDUAL_CRITERIA:
                continue
            for rid in f["req_ids"]:
                key = (rid, f["criterion"])
                ch = checks.get(key)
                if ch is None or ch["status"] in ("pass", "unknown", "na"):
                    checks[key] = ch = {"req_id": rid, "criterion": f["criterion"], "status": "issue",
                                        "reason": f["title"], "finding_ids": [], "source": f["source"]}
                ch["finding_ids"].append(f["id"])
        for r in requirements:
            seen = llm_seen.get(r["id"], set())
            if len(seen) == len(INDIVIDUAL_CRITERIA):
                r["review_status"], r["review_reason"] = "reviewed", None
            elif seen:
                r["review_status"] = "partial"
                r["review_reason"] = f"модель проверила {len(seen)} из {len(INDIVIDUAL_CRITERIA)} критериев"
            else:
                why = failed.get(r["id"]) or (self.unavailable or "модель не вернула результат")
                r["review_status"] = "partial"
                r["review_reason"] = f"только детерминированные правила; LLM-проверка не выполнена: {why}"[:400]
            for crit in INDIVIDUAL_CRITERIA:
                if (r["id"], crit) not in checks:
                    checks[(r["id"], crit)] = {"req_id": r["id"], "criterion": crit, "status": "unknown",
                                               "reason": "не проверено: " + (r["review_reason"] or "нет результата")[:200],
                                               "finding_ids": [], "source": "engine"}
        order = {r["id"]: i for i, r in enumerate(requirements)}
        crit_order = {c: i for i, c in enumerate(INDIVIDUAL_CRITERIA)}
        return sorted(checks.values(), key=lambda c: (order[c["req_id"]], crit_order[c["criterion"]]))

    def build_facts_coverage(self, document, cross) -> tuple[list, list]:
        hint = self.mods.get("resolve_hint").func
        facts = []
        for f in cross.get("facts", []):
            evs = [r["evidence"] for r in (hint(document, h) for h in f.get("hints", [])) if r["status"] == "matched"]
            if evs or f.get("evidence"):
                item = {k: v for k, v in f.items() if k != "hints"}
                item["evidence"] = f.get("evidence") or evs
                facts.append(item)
        coverage = []
        for cv in cross.get("coverage", []):
            evs = [r["evidence"] for r in (hint(document, h) for h in cv.get("hints", [])) if r["status"] == "matched"]
            coverage.append({**cv, "hints": cv.get("hints", []), "evidence": cv.get("evidence") or evs})
        return facts, coverage

    def run_questions(self, document, findings, ask) -> list[dict[str, Any]]:
        t = time.monotonic()
        mod = self.mods.get("build_questions")
        try:
            out = mod.func(document, findings, ask)
        except AskError as exc:
            out = mod.func(document, findings, None)
            self.mark("questions", "partial", f"без модели: {exc.kind}", implementation=mod.label, t=t)
            return out if isinstance(out, list) else out.get("questions", [])
        rec = self.stats.get("questions")
        if ask is None:
            self.mark("questions", "partial", "вопросы построены по правилам без модели", implementation=mod.label, t=t)
        elif rec.calls and rec.failed_calls >= rec.calls and not rec.cache_hits:
            self.mark("questions", "partial", "модель не ответила: вопросы построены по правилам", implementation=mod.label, t=t)
        else:
            self.mark("questions", "ok", implementation=mod.label, t=t)
        return out if isinstance(out, list) else out.get("questions", [])

    def run_bank(self, document, requirements, findings, ask) -> dict[str, Any]:
        t = time.monotonic()
        mod = self.mods.get("build_bank_pack")
        try:
            out = mod.func(document, requirements, findings, self.decisions, ask)
        except AskError as exc:
            out = mod.func(document, requirements, findings, self.decisions, None)
            out.setdefault("warnings", []).append(f"bank: {exc.kind}")
        degraded = ask is None or any("bank:" in str(w) for w in out.get("warnings", []))
        self.mark("bank", "partial" if degraded else "ok",
                  "чек-лист размечен по правилам без модели" if degraded else None, implementation=mod.label, t=t)
        for w in out.get("warnings", []):
            self.warn("bank", str(w), "bank")
        self.save_stage("bank", out)
        return out

    def run_compare(self, report, context: ContextBuilder) -> Optional[dict[str, Any]]:
        t = time.monotonic()
        try:
            previous = json.loads(Path(self.opts.compare_path).read_text(encoding="utf-8"))
            C.validate(previous)
        except (OSError, ValueError, ContractError) as exc:
            self.mark("compare", "failed", f"предыдущий отчёт не прочитан: {exc}"[:300], t=t)
            return None
        mod = self.mods.get("compare_reports")
        diff = mod.func(previous, report)
        if diff["previous"]["source_sha256"] == diff["current"]["source_sha256"]:
            diff["warnings"].append("сравнивается та же редакция документа (SHA-256 совпадает)")
        # связи изменённых мест с набором: требования, связанные межсекционными ссылками
        changed = {b for r in report["requirements"] if r["id"] in set(diff.get("impacted_req_ids", [])) for b in r["block_ids"]}
        linked = context.linked_blocks(changed) if changed else set()
        impacted = set(diff.get("impacted_req_ids", []))
        impacted |= {r["id"] for r in report["requirements"] if set(r["block_ids"]) & linked}
        diff["impacted_req_ids"] = sorted(impacted)
        self.mark("compare", "ok", implementation=mod.label, t=t)
        self.save_stage("compare", diff)
        return diff

    # ------------------------------------------------------------------ паспорт и запись
    def build_run(self, audit: dict[str, Any]) -> dict[str, Any]:
        tot = self.stats.totals()
        stages = [r.to_dict() for r in self.stats.stages.values()]
        incomplete = [s["name"] for s in stages if s["status"] in ("failed", "partial", "skipped")]
        budget = getattr(self, "budget", None)
        reasons = list(self.status_reasons)
        for s in stages:
            if s["status"] in ("failed", "partial", "skipped"):
                reasons.append(f"{s['name']}: {s['reason'] or s['status']}")
        if budget is not None and budget.exhausted_reason:
            reasons.append(budget.exhausted_reason)
        status = "complete" if not incomplete and not self.status_reasons else "partial"
        if not any(s["name"] == "inventory" and s["status"] == "ok" for s in stages):
            status = "failed"
        if self.provider == "mock":
            mode = "mock"
        elif tot["llm_ok"]:
            mode = "rules_plus_llm"
        else:
            mode = "rules_only"
        opts = self.opts.to_dict()
        opts.pop("mock_script", None)
        run = {
            "run_id": self.run_id, "parent_run_id": self.opts.parent_run_id,
            "source_sha256": self.source_sha if self.revision_of is None else self._doc_sha,
            "source_name": self.reviewed_path.name,
            "agent_version": __version__, "agent_commit": agent_commit(),
            "provider": self.provider, "model": tot["models"][-1] if tot["models"] else None,
            "requested_model": self.requested_model, "models_seen": tot["models"],
            "mode": mode, "status": status, "status_reasons": reasons,
            "started_at": self.started_at, "finished_at": utc_now(),
            "duration_s": round(time.monotonic() - self.t0, 3),
            "calls": {"physical": tot["physical"], "cache_hits": tot["cache_hits"], "failed": tot["failed"],
                      "retries": tot["retries"]},
            "tokens": {"input": tot["input"], "output": tot["output"], "cache_read": tot["cache_read"]},
            "budget": budget.to_dict() if budget else {"max_calls": self.opts.max_calls, "max_seconds": self.opts.max_seconds,
                                                       "max_tokens": self.opts.max_tokens, "exhausted": False, "reason": None},
            "stages": stages, "incomplete_stages": incomplete, "modules": self.mods.used(),
            "evidence_audit": {k: audit[k] for k in ("checked", "confirmed", "ambiguous", "rejected", "note")},
            "options": opts, "context_policy": getattr(self, "context_policy", "full"),
        }
        if self.adapter_label:
            run["modules"]["provider"] = self.adapter_label
        if self.revision_of:
            run["revision_of"] = self.revision_of
            run["original_source_name"] = self.input_path.name
        return run

    def finalize(self, report: dict[str, Any]) -> None:
        errs = C.validation_errors(report, C.REPORT_SCHEMA) + C.evidence_errors(report)
        if errs:
            atomic_write_json(self.artifacts / "report.invalid.json", report)
            raise ContractError("итоговый Report нарушает контракт v1: " + "; ".join(errs[:5]))
        self.out_md.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.out_json, report)
        t = time.monotonic()
        mod = self.mods.get("write_markdown")
        try:
            mod.func(report, self.out_md)
        except Exception as exc:  # отчёт важнее красоты: резервный писатель
            if mod.origin != "team":
                raise
            self.warn("export", f"{mod.label}: {type(exc).__name__}: {exc}; использован резервный Markdown", "report")
            self.mods.get("write_markdown", prefer_fallback=True).func(report, self.out_md)
        self.export(report)
        self.tracer.emit("run_end", status=report["run"]["status"], duration_s=round(time.monotonic() - self.t0, 3),
                         calls=report["run"]["calls"]["physical"])

    def export(self, report: dict[str, Any]) -> None:
        targets = {"html": ("write_html", ".html", False), "jira": ("write_jira_csv", ".jira.csv", False),
                   "pdf": ("write_pdf", ".annotated.pdf", True), "docx": ("write_docx", ".annotated.docx", True)}
        written = {}
        for name in self.opts.exports:
            if name not in targets:
                self.warn("export", f"неизвестный экспорт {name!r}")
                continue
            slot, suffix, needs_input = targets[name]
            mod = self.mods.get(slot)
            out = self.out_md.with_name(self.out_md.stem + suffix)
            if mod.func is None:
                self.warn("export", f"экспорт {name} недоступен: модуль {slot} ещё не влит")
                continue
            try:
                path = mod.func(report, self.reviewed_path, out) if needs_input else mod.func(report, out)
                written[name] = str(path)
            except Exception as exc:
                self.warn("export", f"экспорт {name} не выполнен: {type(exc).__name__}: {exc}")
        if written:
            report["warnings"] = self.warnings
            report.setdefault("exports", {}).update(written)
            atomic_write_json(self.out_json, report)

    @property
    def _doc_sha(self) -> str:
        return C.sha256_file(self.reviewed_path)


def run_review(input_path: str | Path, report_md: str | Path, *, options: RunOptions | dict | None = None) -> dict:
    """Единая точка входа CLI и веба. Пишет OUTPUT.md и соседний OUTPUT.json из одного Report."""
    opts = RunOptions.coerce(options)
    load_dotenv()
    return Engine(input_path, report_md, opts).run()
