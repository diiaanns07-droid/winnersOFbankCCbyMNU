"""Конвейер v2: документ → правила → нарезка → линзы и набор (параллельно) → сверка цитат → судья → вопросы →
вердикт по правилу кода → отчёт MD/JSON/HTML (+ экспорт).

Инварианты (№01):
* ни один этап не роняет прогон: сбой этапа = статус этапа ``failed`` + предупреждение, прогон ``partial``;
* обрезанный ответ делится (``LLMClient.ask_split``), а не выбрасывается;
* кандидат без найденной цитаты не доходит до судьи (``rejected`` с причиной «цитата не найдена»);
* вердикт считает код (CONTRACT.md, раздел 5), текст обоснования пишет судья;
* каждый этап пишет ``runs/<id>/stages/<этап>.json`` — по ним этап перезапускается командой ``stage``.
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import hashlib
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from . import AGENT, __version__
from .context import Context
from .llm import BudgetExceeded, LLMClient, LLMError
from .runs import RunDir, now_iso
from .types import LENSES, STANDARD_REFS

ROOT = Path(__file__).resolve().parents[3]
LLM_STAGES = ["segment"] + [f"lens_{x}" for x in LENSES] + ["consistency", "judge", "clarify"]
REUSABLE = set(LLM_STAGES)
DEFAULTS: dict[str, Any] = {
    "provider": "auto", "model": None, "fallback_models": [], "max_calls": 16, "max_seconds": 1500.0,
    "timeout": 600.0, "max_retries": 5, "cache": True, "cache_dir": None, "runs_dir": "runs", "run_id": None,
    "export": [], "html": True, "answers": None, "revise": False, "passes": 1, "parallel": 5,
    "mock_dir": None, "lenses": list(LENSES), "consistency": True, "clarify": True, "judge_check": True,
    "quiet": False,
}


# --------------------------------------------------------------------------- вспомогательное

def git_commit() -> tuple[str, bool]:
    env = os.environ.get("BCC_AGENT_COMMIT", "").strip()
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "", False
    return (sha or env or "unknown"), dirty


def load_view(path: str | Path) -> dict:
    """DocView (docview №03); если модуль недоступен — запасная нумерация строк MD/TXT."""
    try:
        from . import docview
        return docview.load(path)
    except ImportError:
        pass
    p = Path(path)
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    lines = [{"n": i, "text": t.rstrip(), "page": None, "section": "", "src_line": i, "block_id": ""}
             for i, t in enumerate(text.splitlines(), 1)]
    return {"title": p.stem, "file": p.name, "format": p.suffix.lstrip(".").lower() or "txt",
            "sha256": hashlib.sha256(raw).hexdigest(), "lines": lines, "pages": None,
            "warnings": ["docview недоступен: строки взяты из файла как есть"]}


def document_summary(view: dict) -> dict:
    try:
        from . import docview
        return docview.summary(view)
    except Exception:  # noqa: BLE001
        return {"title": view.get("title", ""), "file": view.get("file", ""), "format": view.get("format", ""),
                "sha256": view.get("sha256", ""), "lines": len(view.get("lines") or []), "pages": view.get("pages"),
                "warnings": list(view.get("warnings") or [])}


def verdict_rule(findings: list[dict], status: str) -> dict:
    """CONTRACT.md, раздел 5. ``failed`` — вердикта нет; ``partial`` — не выше ``conditional``."""
    if status == "failed":
        return {"development": "none", "testing": "none"}
    open_f = [f for f in findings if f.get("status") not in ("resolved", "rejected")]
    out = {}
    for target, blockers in (("development", {"development", "both"}), ("testing", {"testing", "both"})):
        if any(f.get("severity") == "critical" and f.get("blocks") in blockers for f in open_f):
            value = "no"
        elif sum(1 for f in open_f if f.get("severity") == "major" and f.get("blocks") in blockers) >= 3:
            value = "conditional"
        else:
            value = "yes"
        if status == "partial" and value == "yes":
            value = "conditional"
        out[target] = value
    return out


def make_llm(opts: dict, run: RunDir | None, input_path: str | Path | None = None) -> tuple[Any, str]:
    """(LLMClient или None для offline, имя провайдера)."""
    name = (opts.get("provider") or "auto").strip().lower()
    if name == "mock":
        from .providers.mock import MockProvider
        mdir = opts.get("mock_dir") or _mock_dir_for(input_path)
        provider, pname = MockProvider(fixtures_dir=mdir, model=opts.get("model")), "mock"
    else:
        from .providers import doctor
        pname = doctor.normalize_name(name)
        if pname == "auto":
            pname, _ = doctor.resolve_auto()
        if pname == "offline":
            return None, "offline"
        kw = {"model": opts["model"]} if opts.get("model") else {}
        provider = doctor.make_provider(pname, **kw)
    cache_dir = None
    if opts.get("cache") and pname != "mock":
        cache_dir = opts.get("cache_dir") or (Path(".bcc_cache") / "v2")
    llm = LLMClient(provider, model=opts.get("model"), provider_name=pname,
                    fallback_models=opts.get("fallback_models") or [], max_calls=opts["max_calls"],
                    max_seconds=opts["max_seconds"], max_retries=opts["max_retries"], timeout_s=opts["timeout"],
                    cache_dir=cache_dir, trace=run.trace if run else None)
    return llm, pname


def _mock_dir_for(input_path: str | Path | None) -> Path:
    base = ROOT / "tests" / "v2" / "fixtures"
    if input_path:
        p = Path(input_path)
        for name in (p.parent.name, p.stem, f"{p.stem}_{p.suffix.lstrip('.')}"):
            if name and (base / name).is_dir() and name not in ("fixtures", "input"):
                return base / name
        if p.suffix.lower() == ".pdf" and (base / "official_pdf").is_dir():
            return base / "official_pdf"
    return base / "official"


# --------------------------------------------------------------------------- конвейер

class Pipeline:
    def __init__(self, input_path: str | Path, opts: dict | None = None, *, reuse: RunDir | None = None,
                 rerun: set[str] = frozenset(), log: Callable[[str], None] | None = None):
        self.input = Path(input_path)
        self.opts = {**DEFAULTS, **(opts or {})}
        self.reuse = reuse
        self.rerun = set(rerun)
        self.log = log or (lambda msg: None)
        self.run = RunDir(self.opts["runs_dir"], self.opts.get("run_id"))
        self.started_at = now_iso()
        self.t0 = time.monotonic()
        self.stages: dict[str, str] = {}
        self.stage_stats: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.ctx: Context | None = None
        self.provider_name = ""

    # ------------------------------------------------------------------ один этап

    def stage(self, name: str, fn: Callable[[], dict], *, inputs: dict | None = None, required: bool = False,
              empty: dict | None = None) -> dict:
        """Выполнить этап (или взять готовый выход из ``reuse``), записать файл этапа. Сбой не роняет прогон."""
        empty = {} if empty is None else empty
        if self.reuse is not None and name in REUSABLE and name not in self.rerun:
            rec = self.reuse.load_stage(name)
            if rec is not None and isinstance(rec.get("output"), dict):
                self.stages[name] = rec.get("status", "ok")
                self.stage_stats[name] = {"calls": 0, "seconds": 0.0, "reused": True,
                                          "candidates": len(rec["output"].get("candidates") or [])}
                self.run.save_stage(name, {**rec, "reused_from": str(self.reuse.path)})
                self.log(f"  {name}: взят из {self.reuse.run_id}")
                return copy.deepcopy(rec["output"])
        llm = self.ctx.llm if self.ctx else None
        before = dict((llm.stats["by_stage"].get(name) or {})) if llm else {}
        t0 = time.monotonic()
        status, err = "ok", ""
        warn_before = len(self.ctx.warnings) if self.ctx else 0
        self.log(f"  {name}: запуск")
        try:
            out = fn() or {}
            if not isinstance(out, dict):
                out = {"value": out}
            if out.pop("_partial", False):
                status = "partial"
        except BudgetExceeded as exc:
            status, err, out = "failed", exc.message, copy.deepcopy(empty)
        except LLMError as exc:
            status, err, out = "failed", f"{exc.kind}: {exc.message}", copy.deepcopy(empty)
        except Exception as exc:  # noqa: BLE001 — инвариант: этап не роняет прогон
            status, err, out = "failed", f"{type(exc).__name__}: {exc}", copy.deepcopy(empty)
            self.run.trace({"stage": name, "event": "exception", "traceback": traceback.format_exc()[-4000:]})
        seconds = round(time.monotonic() - t0, 2)
        if err:
            msg = f"Этап {name} не выполнен: {err[:300]}"
            self.warnings.append(msg)
            self.log(f"  {name}: СБОЙ — {err[:200]}")
        self.stages[name] = status
        after = (llm.stats["by_stage"].get(name) or {}) if llm else {}
        calls = int(after.get("calls", 0)) - int(before.get("calls", 0))
        st = {"calls": calls, "seconds": seconds, "candidates": len(out.get("candidates") or [])}
        if after.get("split", 0) - before.get("split", 0):
            st["split"] = after["split"] - before.get("split", 0)
        self.stage_stats[name] = st
        stage_warnings = list(out.get("warnings") or []) + (self.ctx.warnings[warn_before:] if self.ctx else [])
        self.run.save_stage(name, {"stage": name, "status": status, "seconds": seconds, "calls": calls,
                                   "error": err, "input": inputs or {}, "output": out, "warnings": stage_warnings})
        if status == "ok":
            self.log(f"  {name}: готово за {seconds:.0f} с, вызовов {calls}"
                     + (f", кандидатов {st['candidates']}" if st["candidates"] else ""))
        if required and status == "failed":
            raise _StageFailed(name, err)
        return out

    # ------------------------------------------------------------------ весь прогон

    def execute(self) -> dict:
        opts = self.opts
        self.log(f"Документ: {self.input}")
        view = load_view(self.input)
        llm, self.provider_name = make_llm(opts, self.run, self.input)
        ctx = self.ctx = Context(view=view, llm=llm, options={**opts, "input": str(self.input)},
                                 run_dir=self.run.path, trace=self.run.trace)
        if llm is None:
            return self._offline(view)

        # 1. нарезка (при сбое — эвристика кода, прогон partial)
        seg = self.stage("segment", lambda: self._segment(ctx), inputs={"lines": len(view.get("lines") or [])},
                         empty={"requirements": [], "excluded": []})
        if not seg.get("requirements"):
            seg = self._heuristic_segment(view, seg)
        ctx.requirements = seg.get("requirements") or []
        ctx.excluded = seg.get("excluded") or []

        # 2. правила (код): сигналы линзам, кандидаты — судье
        rules_out = self.stage("rules", lambda: self._rules(view, seg), empty={"signals": [], "candidates": []})
        ctx.signals = rules_out.get("signals") or []

        # 3. линзы и набор — параллельно
        outs = self._parallel_reviewers(ctx)

        # 4. сбор и сверка цитат
        cands, rejected, extras = self._collect(ctx, outs, rules_out)
        q = self.stage("quotes", lambda: self._verify(view, cands, ctx.requirements),
                       inputs={"candidates": len(cands)}, empty={"candidates": cands, "rejected": [], "stats": {}})
        kept = q.get("candidates") or []
        rejected += [self._rejected_entry(c, "no_quote", c.get("reason") or "цитата не найдена")
                     for c in q.get("rejected") or []]

        # 5. судья
        jd = self.stage("judge", lambda: self._judge(ctx, kept), inputs={"candidates": len(kept)},
                        empty={"findings": [], "rejected": [], "checklist": [], "verdict_summary": ""})
        findings = jd.get("findings") or []
        if self.stages.get("judge") == "failed" and kept:
            findings = self._code_findings(kept)
            self.warnings.append("Судья недоступен: реестр собран кодом из сверенных кандидатов без отсева")
        self._finish_findings(findings)
        rejected += list(jd.get("rejected") or [])

        # 6. вопросы владельцу
        questions: list = []
        if opts.get("clarify", True):
            cl = self.stage("clarify", lambda: self._clarify(ctx, findings), inputs={"findings": len(findings)},
                            empty={"questions": []})
            questions = cl.get("questions") or []
        else:
            self.stages["clarify"] = "skipped"

        report = self._report(view, seg, findings, rejected, extras, jd, questions, q.get("stats") or {})

        # 7. режимы --answers / --revise (после судьи и вопросов)
        if opts.get("answers") or opts.get("revise"):
            self._answers_and_revise(ctx, report)
        return report

    # ------------------------------------------------------------------ этапы

    def _segment(self, ctx: Context) -> dict:
        from .stages import segment
        out = segment.run(ctx)
        try:
            from . import quotes
            res = quotes.verify_requirements(ctx.view, out.get("requirements") or [])
            out["requirements"] = res["requirements"]
            if res.get("missing"):
                out.setdefault("warnings", []).append(
                    "Цитата требования не найдена: " + ", ".join(x for x in res["missing"] if x))
        except ImportError:
            pass
        return out

    def _heuristic_segment(self, view: dict, seg: dict) -> dict:
        try:
            from .stages import segment
            h = segment.heuristic_segment(view)
            if h.get("requirements"):
                self.warnings.append("Нарезка моделью не удалась: требования выделены эвристикой кода")
                if self.stages.get("segment") == "ok":
                    self.stages["segment"] = "partial"
                return h
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"Эвристическая нарезка не удалась: {type(exc).__name__}: {exc}")
        return seg

    def _rules(self, view: dict, seg: dict) -> dict:
        try:
            from . import rules
        except ImportError:
            return {"signals": [], "candidates": []}
        return rules.run(view, seg)

    def _lens(self, ctx: Context, name: str) -> dict:
        from .stages import lens
        out = lens.run_named(ctx, name)
        if self.opts.get("passes", 1) >= 2:
            again = lens.run_named(_second_pass(ctx), name)
            for c in again.get("candidates") or []:
                c["pass"] = 2
            out["candidates"] = list(out.get("candidates") or []) + list(again.get("candidates") or [])
        return out

    def _consistency(self, ctx: Context) -> dict:
        from .stages import consistency
        return consistency.run(ctx)

    def _parallel_reviewers(self, ctx: Context) -> dict[str, dict]:
        jobs: dict[str, Callable[[], dict]] = {}
        for name in self.opts.get("lenses") or LENSES:
            jobs[f"lens_{name}"] = (lambda n=name: self._lens(ctx, n))
        if self.opts.get("consistency", True):
            jobs["consistency"] = lambda: self._consistency(ctx)
        for name in [f"lens_{x}" for x in LENSES] + ["consistency"]:
            if name not in jobs:
                self.stages[name] = "skipped"
        outs: dict[str, dict] = {}
        workers = max(1, min(int(self.opts.get("parallel") or 1), len(jobs) or 1))
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self.stage, name, fn, inputs={"requirements": len(ctx.requirements)},
                              empty={"candidates": []}): name for name, fn in jobs.items()}
            for fut in cf.as_completed(futs):
                name = futs[fut]
                try:
                    outs[name] = fut.result()
                except Exception as exc:  # noqa: BLE001 — stage() уже ловит всё; на всякий случай
                    self.stages[name] = "failed"
                    self.warnings.append(f"Этап {name} не выполнен: {exc}")
                    outs[name] = {"candidates": []}
        return outs

    def _collect(self, ctx: Context, outs: dict[str, dict], rules_out: dict) -> tuple[list, list, dict]:
        cands: list[dict] = []
        rejected: list[dict] = []
        extras: dict[str, list] = {"acceptance_checks": [], "test_cases": [], "pair_checks": [], "trace": [],
                                   "glossary": []}
        order = [f"lens_{x}" for x in LENSES] + ["consistency"]
        for name in order:
            out = outs.get(name) or {}
            source = "consistency" if name == "consistency" else "lens:" + name.split("_", 1)[1]
            for c in out.get("candidates") or []:
                if isinstance(c, dict):
                    c = dict(c)
                    c.setdefault("source", source)
                    cands.append(c)
            for key in extras:
                if isinstance(out.get(key), list):
                    extras[key].extend(out[key])
            for d in out.get("dropped") or []:
                if isinstance(d, dict):
                    rejected.append(self._rejected_entry(d, "lens_dropped", d.get("reason") or "снят линзой",
                                                         source=source))
        for c in rules_out.get("candidates") or []:
            c = dict(c)
            c.setdefault("source", "rules")
            cands.append(c)
        for i, c in enumerate(cands, 1):
            c["id"] = f"C-{i:03d}"
            for ev in c.get("evidence") or []:
                if isinstance(ev, dict) and "line" not in ev and ev.get("line_start"):
                    ev["line"] = ev["line_start"]
        return cands, rejected, extras

    def _verify(self, view: dict, cands: list[dict], requirements: list[dict]) -> dict:
        try:
            from . import quotes
        except ImportError:
            self.warnings.append("Сверка цитат недоступна (quotes): кандидаты переданы судье без проверки")
            return {"candidates": cands, "rejected": [], "stats": {}, "_partial": True}
        return quotes.verify_candidates(view, cands, requirements)

    def _judge(self, ctx: Context, kept: list[dict]) -> dict:
        from .stages import judge
        return judge.run(ctx, kept)

    def _clarify(self, ctx: Context, findings: list[dict]) -> dict:
        from .stages import clarify
        return clarify.run(ctx, findings)

    @staticmethod
    def _rejected_entry(c: dict, code: str, reason: str, source: str = "") -> dict:
        ev = c.get("evidence") or []
        line = next((e.get("line_start") or e.get("line") for e in ev if isinstance(e, dict)), 0) or 0
        return {"candidate_id": c.get("id", ""), "title": c.get("title", ""), "source": c.get("source") or source,
                "reason_code": code, "reason": reason, "line": line, "severity": c.get("severity", ""),
                "kind": c.get("kind", ""), "problem": c.get("problem", ""), "evidence": ev}

    def _code_findings(self, kept: list[dict]) -> list[dict]:
        out = []
        for i, c in enumerate(kept, 1):
            f = {k: c.get(k, "") for k in ("title", "kind", "criterion", "severity", "problem", "scenario",
                                           "impact", "recommendation", "rewrite", "question", "blocks")}
            f.update(id=f"D-{i:02d}", candidate_ids=[c.get("id", "")], requirement_ids=c.get("requirement_ids") or [],
                     evidence=c.get("evidence") or [], sources=[c.get("source", "")], priority=0)
            out.append(f)
        return out

    @staticmethod
    def _finish_findings(findings: list[dict]) -> None:
        for f in findings:
            if not f.get("standard_refs"):
                f["standard_refs"] = list(STANDARD_REFS.get(f.get("criterion", ""), []))
            if f.get("severity") == "critical" and f.get("blocks") in (None, "", "none"):
                f["blocks"] = "both"
            f.setdefault("priority", 0)

    def _answers_and_revise(self, ctx: Context, report: dict) -> None:
        try:
            from .stages import revise
        except ImportError:
            self.warnings.append("Режимы --answers/--revise недоступны: нет stages/revise.py")
            return
        t0 = time.monotonic()
        try:
            res = revise.run_modes(ctx, report, answers=self.opts.get("answers"),
                                   do_revise=bool(self.opts.get("revise")),
                                   report_path=self.opts.get("output") or None)
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"Режим --answers/--revise не выполнен: {type(exc).__name__}: {exc}")
            self.stages["recheck"] = "failed"
            return
        self.stages["recheck"] = "ok"
        self.stage_stats["recheck"] = {"calls": 0, "seconds": round(time.monotonic() - t0, 2), "candidates": 0}
        if res.get("clarification"):
            report["clarification"] = res["clarification"]
            report["findings_before"] = report["findings"]
            report["findings"] = res.get("findings_after") or report["findings"]
            report["rejected"] = list(report.get("rejected") or []) + list(res.get("rejected_after") or [])
        for k in ("rewrites", "revised_file", "revise_stats"):
            if res.get(k):
                report[k] = res[k]
        if res.get("markdown_sections"):
            report["extra_markdown"] = res["markdown_sections"]
        self.run.save_stage("recheck", {"stage": "recheck", "status": "ok", "output": res})

    # ------------------------------------------------------------------ отчёт

    def _status(self) -> str:
        llm_ok = [s for s in LLM_STAGES if self.stages.get(s) in ("ok", "partial")]
        reviewers = [s for s in [f"lens_{x}" for x in LENSES] + ["consistency"] if self.stages.get(s) != "skipped"]
        if not any(self.stages.get(s) in ("ok", "partial") for s in reviewers) or not llm_ok:
            return "failed"
        if any(v in ("failed", "partial") for v in self.stages.values()):
            return "partial"
        return "complete"

    def _run_block(self, status: str) -> dict:
        commit, dirty = git_commit()
        llm = self.ctx.llm if self.ctx else None
        s = llm.summary() if llm else {"calls": {"total": 0, "cached": 0, "failed": 0, "split": 0},
                                        "tokens": {"input": 0, "output": 0}, "cost_usd": 0.0, "models_used": []}
        opts = {k: self.opts.get(k) for k in ("max_calls", "passes", "lenses", "export", "revise")}
        opts["answers"] = bool(self.opts.get("answers"))
        return {"agent": AGENT, "version": __version__, "commit": commit, "dirty": dirty,
                "run_id": self.run.run_id, "started_at": self.started_at, "finished_at": now_iso(),
                "duration_s": round(time.monotonic() - self.t0, 1), "provider": self.provider_name,
                "model_requested": self.opts.get("model") or "", "models_used": s["models_used"],
                "calls": s["calls"], "tokens": s["tokens"], "cost_usd": s["cost_usd"], "status": status,
                "stages": dict(self.stages), "stage_stats": dict(self.stage_stats),
                "warnings": _uniq(self.warnings + (self.ctx.warnings if self.ctx else [])), "options": opts}

    def _report(self, view: dict, seg: dict, findings: list, rejected: list, extras: dict, jd: dict,
                questions: list, qstats: dict) -> dict:
        status = self._status()
        verdict = verdict_rule(findings, status)
        verdict["summary"] = jd.get("verdict_summary") or ""
        verdict["fix_first"] = list(jd.get("fix_first") or [f["id"] for f in sorted(
            (f for f in findings if f.get("priority")), key=lambda f: f["priority"])][:7])
        report = {
            "schema": "bcc-review/2", "run": self._run_block(status), "document": document_summary(view),
            "requirements": seg.get("requirements") or [], "excluded": seg.get("excluded") or [],
            "findings": findings, "rejected": rejected, **extras, "questions": questions,
            "checklist": jd.get("checklist") or [], "verdict": verdict,
        }
        if jd.get("checklist_source"):
            report["checklist_source"] = jd["checklist_source"]
        if self.ctx and self.ctx.signals:
            report["signals"] = self.ctx.signals
        if qstats:
            report["quote_stats"] = qstats
        return report

    def _offline(self, view: dict) -> dict:
        self.log("Модель не настроена: предварительная проверка правилами (offline)")
        from .rules import offline
        report = offline.build(view, None)
        run = report.setdefault("run", {})
        base = self._run_block("complete")
        for k, v in base.items():
            if k not in ("stages", "stage_stats", "status") or k not in run:
                run[k] = v
        run["provider"] = "offline"
        run.setdefault("status", "complete")
        return report


class _StageFailed(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage


def _second_pass(ctx: Context) -> Context:
    """Второй проход линз (``--passes 2``): тот же контекст, но без кэша первого ответа."""
    c = copy.copy(ctx)
    c.options = {**ctx.options, "pass": 2}
    orig = ctx.llm

    class _Pass2:
        stats = orig.stats

        def ask(self, stage, system, user, schema, **kw):
            return orig.ask(stage, system, user + "\n\n<!-- проход 2 -->", schema, **kw)

        def ask_split(self, stage, build, items, schema, merge, **kw):
            return orig.ask_split(stage, lambda it: (lambda s, u: (s, u + "\n\n<!-- проход 2 -->"))(*build(it)),
                                  items, schema, merge, **kw)

    c.llm = _Pass2()
    return c


def _uniq(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --------------------------------------------------------------------------- запись отчёта

def write_outputs(report: dict, view: dict | None, input_path: Path, out_md: Path, opts: dict,
                  log: Callable[[str], None] = lambda m: None) -> dict[str, str]:
    """Записать .json, .md, .html (+ экспорт). Сбой одного формата не мешает остальным."""
    written: dict[str, str] = {}
    out_md.parent.mkdir(parents=True, exist_ok=True)
    warnings = report.setdefault("run", {}).setdefault("warnings", [])
    try:
        from .render import jsonout
        jsonout.finalize(report)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Итоговые поля отчёта не досчитаны: {type(exc).__name__}: {exc}")
    md_text = ""
    try:
        from .render import markdown
        md_text = markdown.render(report)
        extra = report.get("extra_markdown") or []
        if extra and not any(s[:60] in md_text for s in extra if s):
            md_text = md_text.rstrip() + "\n\n" + "\n\n".join(s.strip() for s in extra if s) + "\n"
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Отчёт Markdown собран упрощённо: {type(exc).__name__}: {exc}")
        md_text = fallback_markdown(report)
    out_md.write_text(md_text, encoding="utf-8")
    written["md"] = str(out_md)
    out_json = out_md.with_suffix(".json")
    try:
        from .render import jsonout
        jsonout.write(report, out_json)
    except Exception:  # noqa: BLE001
        import json
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    written["json"] = str(out_json)
    if opts.get("html", True) or "html" in (opts.get("export") or []):
        try:
            from .render import html
            written["html"] = str(html.write(report, view, out_md.with_suffix(".html")))
        except Exception as exc:  # noqa: BLE001
            log(f"HTML не записан: {type(exc).__name__}: {exc}")
    fmts = [f for f in (opts.get("export") or []) if f not in ("md", "json", "html")]
    if fmts:
        try:
            from .render import exports
            for r in exports.export(report, view, input_path, out_md.with_suffix(""), fmts, markdown=md_text) or []:
                if r.get("message"):
                    log(r["message"])
                if r.get("path"):
                    written[r.get("format", "export")] = str(r["path"])
        except Exception as exc:  # noqa: BLE001
            log(f"Экспорт {','.join(fmts)} не выполнен: {type(exc).__name__}: {exc}")
    return written


def fallback_markdown(report: dict) -> str:
    """Минимальный отчёт, если рендер №13 недоступен: вердикт и реестр дефектов."""
    sev = {"critical": "🔴 критичный", "major": "🟠 существенный", "minor": "🟡 незначительный"}
    ready = {"no": "нельзя начинать", "conditional": "можно с условиями", "yes": "можно начинать", "none": "не вынесен"}
    v = report.get("verdict") or {}
    lines = [f"# Ревью требований: {report.get('document', {}).get('title', '')}", "",
             f"Разработка: **{ready.get(v.get('development'), v.get('development'))}**; "
             f"тестирование: **{ready.get(v.get('testing'), v.get('testing'))}**.", "", v.get("summary", ""), "",
             "## Дефекты", ""]
    for f in report.get("findings") or []:
        lines.append(f"### {f.get('id')} · {sev.get(f.get('severity'), f.get('severity'))} · {f.get('title')}")
        for e in f.get("evidence") or []:
            lines.append(f"> «{e.get('quote')}» — строка {e.get('line_start') or e.get('line')}")
        for k, title in (("problem", "Проблема"), ("scenario", "Сценарий"), ("impact", "Последствия"),
                         ("recommendation", "Рекомендация")):
            if f.get(k):
                lines.append(f"**{title}.** {f[k]}")
        lines.append("")
    return "\n".join(lines) + "\n"


def review(input_path: str | Path, output_md: str | Path, opts: dict | None = None, *,
           reuse: RunDir | None = None, rerun: set[str] = frozenset(),
           log: Callable[[str], None] | None = None) -> tuple[dict, dict]:
    """Полный прогон: (report, {формат: путь}). Никогда не бросает исключение из-за этапа."""
    opts = {**DEFAULTS, **(opts or {}), "output": str(output_md)}
    p = Pipeline(input_path, opts, reuse=reuse, rerun=rerun, log=log)
    try:
        report = p.execute()
    except Exception as exc:  # noqa: BLE001 — последний рубеж: отчёт о сбое вместо трейсбэка
        p.warnings.append(f"Прогон прерван: {type(exc).__name__}: {exc}")
        p.run.trace({"event": "fatal", "traceback": traceback.format_exc()[-4000:]})
        view = p.ctx.view if p.ctx else {"title": Path(input_path).name, "file": Path(input_path).name,
                                          "format": "", "sha256": "", "lines": []}
        report = {"schema": "bcc-review/2", "run": p._run_block("failed"), "document": document_summary(view),
                  "requirements": [], "findings": [], "verdict": {"development": "none", "testing": "none",
                                                                   "summary": "", "fix_first": []}}
    view = p.ctx.view if p.ctx else None
    llm = p.ctx.llm if p.ctx else None
    for stage, items in (getattr(llm, "responses", None) or {}).items():
        try:
            (p.run.path / "responses").mkdir(exist_ok=True)
            p.run.write_json(f"responses/{stage}.json", items)
        except OSError:
            pass
    written = write_outputs(report, view, Path(input_path), Path(output_md), opts, log or (lambda m: None))
    for fmt in ("json", "md", "html"):
        if fmt in written:
            try:
                import shutil
                shutil.copy2(written[fmt], p.run.path / f"report.{fmt}")
            except OSError:
                pass
    return report, written
