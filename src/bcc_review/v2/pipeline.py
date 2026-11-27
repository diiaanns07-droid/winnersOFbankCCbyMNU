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
import json
import os
import re
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
    "quiet": False, "stage_timeout": 480.0, "rpm": None, "effort": None, "fast_start": None,
    "clarify_early": True,
}
STAGE_RU = {"lens_analyst": "«Аналитик»", "lens_qa": "«Тестировщик»", "lens_architect": "«Архитектор»",
            "lens_risk": "«Риски»", "consistency": "«Набор целиком»", "judge": "«Судья»"}
# Темп запросов по умолчанию: бесплатный ключ Gemini — около 10 запросов в минуту на модель.
DEFAULT_RPM = {"gemini": 10}
# Линзы от самой долгой к самой короткой (замер 27.11 09:00: haiku architect 102 с, analyst 66, risk 51, qa 50).
LONGEST_FIRST = ["architect", "analyst", "risk", "qa"]
# Быстрый старт (--fast-start): рецензенты не ждут нарезку моделью (sonnet 28 с, haiku 58 с), а берут таблицу
# эвристики кода; на официальном документе она совпадает с нарезкой моделью по строкам и видам (42 против 40).
HEURISTIC_TABLE = "heuristic"
FAST_START_MIN_REQUIREMENTS = 5
# «Проба» быстрого старта, с: отказ ключа, квоты и сети приходит за 1–3 с, нарезка моделью идёт 15–60 с
FAST_START_PROBE_S = 8.0


# --------------------------------------------------------------------------- вспомогательное

def explain(exc: BaseException, provider: str = "") -> str:
    """Понятное объяснение ошибки провайдера с советом (doctor №02), без трейсбэка."""
    try:
        from .providers import doctor
        return doctor.explain(exc, provider or None)
    except Exception:  # noqa: BLE001
        return f"Модель недоступна: {getattr(exc, 'message', None) or exc}"


def git_commit() -> tuple[str, bool]:
    env = os.environ.get("BCC_AGENT_COMMIT", "").strip()
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "", False
    return (sha or env or _archive_commit() or "unknown"), dirty


def _archive_commit() -> str:
    """Хеш из архива GitHub (export-subst в .gitattributes); в клоне в файле шаблон «$Format:%H$» — пусто."""
    try:
        value = (Path(__file__).with_name("COMMIT")).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value if re.fullmatch(r"[0-9a-f]{7,40}", value) else ""


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


# Этапы, без которых «можно» и «с условиями» — ложный вердикт: дефекты, которые нашёл бы упавший этап, не видны.
VERDICT_STAGES = [f"lens_{x}" for x in LENSES] + ["consistency", "judge"]


def incomplete_stages(stages: dict) -> list[str]:
    """Упавшие (``failed``) линзы, набор целиком и судья — при них вердикт кроме «нельзя» не определён."""
    return [s for s in VERDICT_STAGES if stages.get(s) == "failed"]


def verdict_rule(findings: list[dict], status: str, incomplete: list[str] | None = None) -> dict:
    """CONTRACT.md, раздел 5. ``failed`` — вердикта нет; ``partial`` — не выше ``conditional``; упал рецензент
    или судья (``incomplete``) — «нельзя», если блокер уже найден, иначе «не определено» (``undetermined``)."""
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
        if incomplete and value != "no":
            value = "undetermined"
        out[target] = value
    return out


def make_llm(opts: dict, run: RunDir | None, input_path: str | Path | None = None) -> tuple[Any, str]:
    """(LLMClient или None для offline, имя провайдера)."""
    name = (opts.get("provider") or "auto").strip().lower()
    if opts.get("replay"):
        # --replay runs/<id> (№22): ответы модели — только записанные тем прогоном, без сети, ключа и кэша
        from .providers.mock import ReplayProvider
        provider = ReplayProvider(fixtures_dir=Path(opts["replay"]) / "responses")
        llm = LLMClient(provider, model=None, provider_name="replay", max_calls=opts["max_calls"],
                        max_seconds=opts["max_seconds"], max_retries=0, timeout_s=opts["timeout"], cache_dir=None,
                        trace=run.trace if run else None)
        return llm, "replay"
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
        if pname == "claude_cli":
            effort = opts.get("effort") or weak_profile_effort(opts.get("model"))
            if effort and not os.environ.get("CLAUDE_CLI_EFFORT"):
                kw["effort"] = effort
            if opts.get("stage_timeout"):
                kw["timeout_floor_s"] = min(600.0, float(opts["stage_timeout"]))
        provider = doctor.make_provider(pname, **kw)
    cache_dir = None
    if opts.get("cache") and pname != "mock":
        cache_dir = opts.get("cache_dir") or (Path(".bcc_cache") / "v2")
    llm = LLMClient(provider, model=opts.get("model"), provider_name=pname,
                    fallback_models=opts.get("fallback_models") or [], max_calls=opts["max_calls"],
                    max_seconds=opts["max_seconds"], max_retries=opts["max_retries"], timeout_s=opts["timeout"],
                    cache_dir=cache_dir, trace=run.trace if run else None,
                    stage_timeout_s=float(opts.get("stage_timeout") or 0),
                    rpm=float(opts["rpm"]) if opts.get("rpm") is not None else DEFAULT_RPM.get(pname, 0))
    return llm, pname


def weak_profile_effort(model: str | None) -> str | None:
    """Профиль слабой модели: у haiku рассуждения — 70 % вывода и 2–4 мин на вызов; effort=low вдвое быстрее
    при том же качестве (замер 05:05: линза архитектора 232 → 108 с, судья 259 → 119 с, К и С те же)."""
    return "low" if model and "haiku" in str(model).lower() else None


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
        runs_note = ""
        try:
            self.run = RunDir(self.opts["runs_dir"], self.opts.get("run_id"))
        except OSError as exc:  # каталог только для чтения (установленный пакет, Docker с --user) — не повод терять отчёт
            import tempfile
            self.run = RunDir(Path(tempfile.gettempdir()) / "bcc_review_runs", self.opts.get("run_id"))
            runs_note = (f"Каталог прогонов недоступен для записи ({type(exc).__name__}): артефакты этапов записаны "
                         "во временный каталог системы (bcc_review_runs); отчёт от этого не зависит")
        self.started_at = now_iso()
        self.t0 = time.monotonic()
        self.stages: dict[str, str] = {}
        self.stage_stats: dict[str, dict] = {}
        self.warnings: list[str] = [runs_note] if runs_note else []
        self.ctx: Context | None = None
        self.provider_name = ""
        self.model_error = ""
        self.fast_start_used = False
        self.replay: dict | None = None
        if self.opts.get("replay"):
            self._setup_replay(Path(self.opts["replay"]))

    def _setup_replay(self, src: Path) -> None:
        """``--replay``: все этапы модели — из файлов этапов ``src``, код (правила, цитаты, вердикт, отчёт) — заново."""
        self.reuse = RunDir(src, create=False)
        self.rerun = set()
        orig: dict = {}
        try:
            orig = json.loads((src / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        run0 = orig.get("run") if isinstance(orig.get("run"), dict) else {}
        self.replay = {"from": str(src), "run_id": run0.get("run_id") or src.name,
                       "provider": run0.get("provider") or "", "models_used": list(run0.get("models_used") or []),
                       "model_requested": run0.get("model_requested") or "", "commit": run0.get("commit") or "",
                       "document_sha256": ((orig.get("document") or {}).get("sha256") or ""),
                       "stages": sorted(p.stem for p in self.reuse.stages.glob("*.json"))}
        try:
            import shutil
            if (src / "responses").is_dir():
                shutil.copytree(src / "responses", self.run.path / "responses", dirs_exist_ok=True)
        except OSError:
            pass

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
                self._save_stage(name, {**rec, "reused_from": str(self.reuse.path)})
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
            fatal = getattr(llm, "fatal", None)
            if fatal is not None and not self.model_error:
                self.model_error = explain(fatal, self.provider_name)
                self.warnings.insert(0, self.model_error)
        except Exception as exc:  # noqa: BLE001 — инвариант: этап не роняет прогон
            status, err, out = "failed", f"{type(exc).__name__}: {exc}", copy.deepcopy(empty)
            self.run.trace({"stage": name, "event": "exception", "traceback": traceback.format_exc()[-4000:]})
        seconds = round(time.monotonic() - t0, 2)
        if err:
            msg = f"Этап {name} не выполнен: {err[:300]}"
            self.warnings.append(msg)
            self.log(f"  {name}: СБОЙ — {err[:200]}")
        after = (llm.stats["by_stage"].get(name) or {}) if llm else {}
        calls = int(after.get("calls", 0)) - int(before.get("calls", 0))
        hit = (int(after.get("budget", 0)) - int(before.get("budget", 0))) + \
              (int(after.get("failed", 0)) - int(before.get("failed", 0)))
        if status == "ok" and hit > 0:
            status = "partial"
            self.warnings.append(f"Этап {name} выполнен частично: часть вызовов модели не удалась или упёрлась в бюджет")
        self.stages[name] = status
        st = {"calls": calls, "seconds": seconds, "candidates": len(out.get("candidates") or [])}
        if after.get("split", 0) - before.get("split", 0):
            st["split"] = after["split"] - before.get("split", 0)
        self.stage_stats[name] = st
        stage_warnings = list(out.get("warnings") or []) + (self.ctx.warnings[warn_before:] if self.ctx else [])
        self._save_stage(name, {"stage": name, "status": status, "seconds": seconds, "calls": calls,
                                "error": err, "input": inputs or {}, "output": out, "warnings": stage_warnings})
        if status == "ok":
            self.log(f"  {name}: готово за {seconds:.0f} с, вызовов {calls}"
                     + (f", кандидатов {st['candidates']}" if st["candidates"] else ""))
        if required and status == "failed":
            raise _StageFailed(name, err)
        return out

    def _save_stage(self, name: str, record: dict) -> None:
        """Файл этапа — для команды stage и веб-демо, не для отчёта: сбой записи (Windows: файл держит антивирус
        или демо читает прогресс) — повтор, затем предупреждение, но не падение прогона."""
        for attempt in range(3):
            try:
                self.run.save_stage(name, record)
                return
            except OSError as exc:
                if attempt == 2:
                    self.warnings.append(f"Файл этапа {name} не записан: {exc}")
                    return
                time.sleep(0.2 * (attempt + 1))

    # ------------------------------------------------------------------ весь прогон

    def execute(self) -> dict:
        opts = self.opts
        self.log(f"Документ: {self.input}")
        view = load_view(self.input)
        if self.replay and self.replay.get("document_sha256") and \
                self.replay["document_sha256"] != view.get("sha256"):
            self.warnings.insert(0, "Повтор прогона: документ изменился после исходного прогона (SHA-256 "
                                    f"{str(self.replay['document_sha256'])[:12]}… → {str(view.get('sha256'))[:12]}…). "
                                    "Цитаты сверяются с новым текстом; для отчёта по новой редакции запустите "
                                    "обычную проверку.")
        if not any(str(ln.get("text") or "").strip() for ln in view.get("lines") or []):
            # пустой документ: модель не зовём (нечего проверять), вердикт «можно» невозможен — отчёт правилами
            self.warnings.insert(0, "В документе нет текста: проверять нечего. Модель не вызывалась, вердикт не "
                                    "выносится — проверьте, тот ли файл передан.")
            self.ctx = Context(view=view, llm=None, options={**opts, "input": str(self.input)},
                               run_dir=self.run.path, trace=self.run.trace)
            return self._offline(view)
        try:
            llm, self.provider_name = make_llm(opts, self.run, self.input)
        except Exception as exc:  # noqa: BLE001 — нет ключа / не тот провайдер: отчёт правилами + объяснение
            self.provider_name = str(opts.get("provider") or "")
            self.model_error = explain(exc, self.provider_name)
            self.warnings.insert(0, self.model_error)
            llm = None
        ctx = self.ctx = Context(view=view, llm=llm, options={**opts, "input": str(self.input)},
                                 run_dir=self.run.path, trace=self.run.trace)
        if llm is None:
            report = self._offline(view)
            if self.model_error:
                report["run"]["model_error"] = self.model_error
                report["run"]["warnings"] = _uniq([self.model_error] + list(report["run"].get("warnings") or []))
            return report

        fast = opts.get("fast_start")
        # None (по умолчанию) — быстрый старт с «пробой»: рецензенты стартуют, только если нарезка моделью идёт
        # дольше FAST_START_PROBE_S без фатальной ошибки (неверный ключ, квота, сеть дают отказ за секунды — тогда
        # рецензенты не шлют 5 лишних запросов). True — старт сразу, False — рецензенты ждут нарезку.
        heur = self._fast_start_table(view) if fast is not False else None
        seg: dict | None = None
        if heur is not None:
            # 1–3, быстрый старт: нарезка моделью идёт параллельно с рецензентами; рецензенты работают по таблице
            # эвристики кода, после нарезки ссылки R-ID переводятся на ID нарезки по строкам (_remap_reviewers)
            rctx = copy.copy(ctx)
            rctx.requirements = heur.get("requirements") or []
            rctx.excluded = heur.get("excluded") or []
            try:
                rctx.signals = (self._rules(view, heur) or {}).get("signals") or []
            except Exception:  # noqa: BLE001 — без сигналов рецензенты работают как обычно
                rctx.signals = []
            outs = {}
            with cf.ThreadPoolExecutor(max_workers=1) as pool:
                seg_future = pool.submit(self.stage, "segment", lambda: self._segment(ctx),
                                         inputs={"lines": len(view.get("lines") or [])},
                                         empty={"requirements": [], "excluded": []})
                started = fast is True or self._probe(seg_future, llm)
                if fast is None and getattr(llm, "fatal", None) is None:
                    started = self._fast_start_decision(view, llm, seg_future, started)
                if started:
                    self.fast_start_used = True
                    outs = self._parallel_reviewers(rctx, tag=HEURISTIC_TABLE)
                seg = seg_future.result()
            if not started:
                heur = None  # нарезка уже есть (или модель недоступна): обычный путь ниже, без перевода ссылок
        if heur is not None and seg is not None:
            if not seg.get("requirements"):
                seg = self._heuristic_segment(view, seg)
            ctx.requirements = seg.get("requirements") or []
            ctx.excluded = seg.get("excluded") or []
            rules_out = self.stage("rules", lambda: self._rules(view, seg), empty={"signals": [], "candidates": []})
            ctx.signals = rules_out.get("signals") or []
            try:
                self._remap_reviewers(outs, rctx.requirements, ctx.requirements)
            except Exception as exc:  # noqa: BLE001 — перевод ссылок не этап модели: прогон не роняет
                self.warnings.append(f"Ссылки рецензентов на таблицу эвристики не переведены: {type(exc).__name__}: {exc}")
        else:
            # 1. нарезка (при сбое — эвристика кода, прогон partial); после неудачной «пробы» она уже сделана
            if seg is None:
                seg = self.stage("segment", lambda: self._segment(ctx),
                                 inputs={"lines": len(view.get("lines") or [])},
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
            # выходы, взятые из прогона с быстрым стартом (команда stage), ссылаются на таблицу эвристики
            if any((o or {}).get("requirements_source") == HEURISTIC_TABLE for o in outs.values()):
                try:
                    from .stages import segment as _segment_mod
                    heur_reqs = _segment_mod.heuristic_segment(view).get("requirements") or []
                    self._remap_reviewers(outs, heur_reqs, ctx.requirements)
                except Exception as exc:  # noqa: BLE001
                    self.warnings.append(f"Ссылки рецензентов на таблицу эвристики не переведены: {exc}")

        # 4. сбор и сверка цитат
        cands, rejected, extras = self._collect(ctx, outs, rules_out)
        q = self.stage("quotes", lambda: self._verify(view, cands, ctx.requirements),
                       inputs={"candidates": len(cands)}, empty={"candidates": cands, "rejected": [], "stats": {}})
        kept = q.get("candidates") or []
        rejected += [self._rejected_entry(c, "no_quote", c.get("reason") or "цитата не найдена")
                     for c in q.get("rejected") or []]

        # 5. судья; вопросы владельцу (№11) стартуют параллельно с ним по сверенным кандидатам
        early = self._clarify_start(ctx, kept)
        jd = self.stage("judge", lambda: self._judge(ctx, kept), inputs={"candidates": len(kept)},
                        empty={"findings": [], "rejected": [], "checklist": [], "verdict_summary": ""})
        findings = jd.get("findings") or []
        if self.stages.get("judge") == "failed" and kept:
            findings = self._code_findings(kept)
            self.warnings.append("Судья недоступен: реестр собран кодом из сверенных кандидатов без отсева")
        self._finish_findings(findings)
        self._link(extras, kept, findings)
        rejected += list(jd.get("rejected") or [])

        # 6. вопросы владельцу
        questions: list = []
        if opts.get("clarify", True):
            cl = self.stage("clarify", lambda: self._clarify(ctx, findings, early),
                            inputs={"findings": len(findings), "early": early is not None}, empty={"questions": []})
            questions = cl.get("questions") or []
            if early is not None and ctx.llm is not None and "clarify" in self.stage_stats:
                # ранний вызов закончился до входа в этап: вызовы и время — из клиента модели
                by = ctx.llm.stats["by_stage"].get("clarify") or {}
                self.stage_stats["clarify"].update(calls=int(by.get("calls", 0)), early=True,
                                                   model_seconds=round(float(by.get("seconds", 0.0)), 1))
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
        return segment.run(ctx)  # этап сам сверяет цитаты и строки требований (№04)

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

    def _fast_start_decision(self, view: dict, llm: Any, fut: "cf.Future", started: bool) -> bool:
        """Повторяемость «пробы»: она решает по времени нарезки, а нарезка из кэша заканчивается мгновенно — повтор
        живого прогона шёл бы обычным путём, линзы получали бы другую таблицу, кэш не срабатывал, отчёт менялся.
        Живой прогон записывает решение рядом с кэшем; прогон, у которого нарезка из кэша, его повторяет."""
        d = getattr(llm, "cache_dir", None)
        if not d:
            return started
        key = hashlib.sha256("\x1f".join([str(view.get("sha256") or ""), str(self.provider_name or ""),
                                          str(getattr(llm, "model", "") or "")]).encode("utf-8")).hexdigest()
        marker = Path(d) / "fast_start" / f"{key}.json"
        seg_stats = ((getattr(llm, "stats", None) or {}).get("by_stage") or {}).get("segment") or {}
        if fut.done() and seg_stats.get("cached") and not seg_stats.get("calls"):
            try:
                return bool(json.loads(marker.read_text(encoding="utf-8")).get("fast_start"))
            except (OSError, ValueError):
                return started
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"fast_start": bool(started)}), encoding="utf-8")
        except OSError:
            pass
        return started

    def _probe(self, fut: "cf.Future", llm: Any) -> bool:
        """Запускать ли рецензентов до конца нарезки: да, если нарезка идёт дольше пробы и модель отвечает
        (нет фатальной ошибки). Нарезка закончилась раньше — нет: дальше обычный путь по таблице модели."""
        deadline = time.monotonic() + float(self.opts.get("fast_start_probe", FAST_START_PROBE_S) or 0)
        while True:
            if fut.done() or getattr(llm, "fatal", None) is not None:
                return False
            left = deadline - time.monotonic()
            if left <= 0:
                return True
            cf.wait([fut], timeout=min(0.25, left))

    def _fast_start_table(self, view: dict) -> dict | None:
        """Таблица требований эвристики кода для быстрого старта рецензентов; None — ждать нарезку моделью
        (эвристика нашла слишком мало, или этапы берутся из готового прогона)."""
        if self.reuse is not None:
            return None
        try:
            from .stages import segment
            h = segment.heuristic_segment(view)
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"Быстрый старт отключён: эвристика нарезки не сработала ({type(exc).__name__})")
            return None
        if len(h.get("requirements") or []) < FAST_START_MIN_REQUIREMENTS:
            return None
        return h

    def _remap_reviewers(self, outs: dict[str, dict], heur: list[dict], model: list[dict]) -> None:
        """Ссылки рецензентов на таблицу эвристики (R-ID) → ID нарезки моделью по пересечению строк."""
        mapping = remap_table(heur, model)
        for out in outs.values():
            if (out or {}).get("requirements_source") != HEURISTIC_TABLE:
                continue
            remap_output(out, mapping, model)
            out["requirements_source"] = "segment"

    def _parallel_reviewers(self, ctx: Context, tag: str | None = None) -> dict[str, dict]:
        jobs: dict[str, Callable[[], dict]] = {}
        # Самый долгий рецензент — первым: при паузах темпа (--rpm) или parallel < 5 ждут короткие этапы.
        # Порядок кандидатов в отчёте от этого не зависит (_collect идёт по фиксированному списку).
        if self.opts.get("consistency", True):
            jobs["consistency"] = lambda: self._consistency(ctx)
        names = list(self.opts.get("lenses") or LENSES)
        for bad in [n for n in names if n not in LENSES]:
            names.remove(bad)
            self.stages[f"lens_{bad}"] = "failed"
            self.warnings.append(f"Линза «{bad}» неизвестна — допустимо: {', '.join(LENSES)}")
        for name in sorted(names, key=lambda n: (LONGEST_FIRST.index(n) if n in LONGEST_FIRST else 99)):
            jobs[f"lens_{name}"] = (lambda n=name: self._lens(ctx, n))
        for name in [f"lens_{x}" for x in LENSES] + ["consistency"]:
            if name not in jobs:
                self.stages[name] = "skipped"
        inputs: dict[str, Any] = {"requirements": len(ctx.requirements)}
        if tag:
            inputs["requirements_source"] = tag
            jobs = {name: (lambda f=fn: {**(f() or {}), "requirements_source": tag}) for name, fn in jobs.items()}
        outs: dict[str, dict] = {}
        workers = max(1, min(int(self.opts.get("parallel") or 1), len(jobs) or 1))
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self.stage, name, fn, inputs=dict(inputs),
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

    def _clarify_start(self, ctx: Context, kept: list[dict]) -> Any:
        """Ранний запуск вопросов (№11, ``clarify.start``): вызов модели в фоне, пока работает судья."""
        if not self.opts.get("clarify", True) or not self.opts.get("clarify_early", True) or ctx.llm is None:
            return None
        if self.reuse is not None and "clarify" not in self.rerun:
            return None  # вопросы берутся из готового прогона
        try:
            from .stages import clarify
            start = getattr(clarify, "start", None)
            return start(ctx, kept) if callable(start) else None
        except Exception as exc:  # noqa: BLE001 — без раннего запуска вопросы идут после судьи
            self.warnings.append(f"Ранний запуск вопросов не удался: {type(exc).__name__}: {exc}")
            return None

    def _clarify(self, ctx: Context, findings: list[dict], early: Any = None) -> dict:
        from .stages import clarify
        finish = getattr(clarify, "finish", None)
        if early is not None and callable(finish):
            # часы этапа clarify пошли с ранним вызовом, параллельно судье; если ранний вызов не удался, поздний
            # вызов по итоговым дефектам получает свой лимит времени, а не остаток после медленного судьи
            restart = getattr(ctx.llm, "restart_stage_clock", None)
            if callable(restart):
                restart("clarify")
            return finish(ctx, findings, early)
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

    def _link(self, extras: dict, kept: list[dict], findings: list[dict]) -> None:
        """finding_ids у строк приёмки (через acceptance_row кандидата), пар и понятий глоссария."""
        by_cand: dict[str, list[str]] = {}
        for f in findings:
            for cid in f.get("candidate_ids") or []:
                by_cand.setdefault(str(cid), []).append(str(f.get("id")))
        rows: dict[str, list[str]] = {}
        for c in kept:
            row = c.get("acceptance_row")
            if row:
                for fid in by_cand.get(str(c.get("id")), []):
                    if fid not in rows.setdefault(str(row), []):
                        rows[str(row)].append(fid)
        for chk in extras.get("acceptance_checks") or []:
            key = chk.get("row_requirement_id") or (f"L{chk['row_line']}" if chk.get("row_line") else "")
            chk["finding_ids"] = list(dict.fromkeys(list(chk.get("finding_ids") or []) + rows.get(str(key), [])))
        try:
            from .stages import consistency
            link = getattr(consistency, "link_findings", None)
            if callable(link):
                link(extras.get("pair_checks") or [], extras.get("glossary") or [], kept, findings)
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"Связь пар и глоссария с дефектами не построена: {type(exc).__name__}: {exc}")

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
            msg = f"Режим --answers/--revise не выполнен: {type(exc).__name__}: {exc}"
            self.warnings.append(msg)
            self.stages["recheck"] = "failed"
            # отчёт уже собран — сбой режима должен быть виден в нём, а не только в self.*
            run = report.setdefault("run", {})
            run["warnings"] = _uniq(list(run.get("warnings") or []) + [msg])
            run.setdefault("stages", {})["recheck"] = "failed"
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
        llm = ctx.llm
        if llm is not None:
            report["run"].update(llm.summary())
        report["run"]["duration_s"] = round(time.monotonic() - self.t0, 1)
        report["run"]["finished_at"] = now_iso()
        report["run"]["stages"] = _in_stage_order(self.stages)
        report["run"]["stage_stats"] = _in_stage_order(self.stage_stats)

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
                "stages": _in_stage_order(self.stages), "stage_stats": _in_stage_order(self.stage_stats),
                "warnings": _uniq(self.warnings + (self.ctx.warnings if self.ctx else [])), "options": opts,
                "fast_start": self.fast_start_used,
                **(self._replay_block(s) if self.replay else {}),
                **({"incomplete_stages": incomplete_stages(self.stages)} if incomplete_stages(self.stages) else {}),
                **({"model_error": self.model_error} if self.model_error else {})}

    def _replay_block(self, s: dict) -> dict:
        """Паспорт повтора: провайдер и модели — исходного прогона, живых вызовов — ноль."""
        r = self.replay or {}
        return {"provider": r.get("provider") or "replay",
                "models_used": r.get("models_used") or s.get("models_used") or [],
                "model_requested": r.get("model_requested") or self.opts.get("model") or "",
                "replay": {"from": r.get("from"), "run_id": r.get("run_id"), "commit": r.get("commit"),
                           "calls_replayed": int((s.get("calls") or {}).get("total") or 0), "calls_live": 0}}

    def _report(self, view: dict, seg: dict, findings: list, rejected: list, extras: dict, jd: dict,
                questions: list, qstats: dict) -> dict:
        status = self._status()
        incomplete = incomplete_stages(self.stages)
        if incomplete and status != "failed":
            # первым остаётся объяснение отказа модели (model_error), если оно есть
            self.warnings.insert(1 if self.model_error and self.warnings[:1] == [self.model_error] else 0,
                                 "Вердикт «можно» не выносится: не выполнены этапы " + ", ".join(
                STAGE_RU.get(x, x) for x in incomplete) + ". Дефекты, которые они нашли бы, в отчёте не видны — "
                "повторите прогон (уже готовые этапы возьмутся из кэша).")
        verdict = verdict_rule(findings, status, incomplete)
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
        if (self.opts.get("provider") or "auto") == "auto":
            self.log("Для полного отчёта впишите ключ в .env в корне репозитория: GEMINI_API_KEY=<ключ> (бесплатно: "
                     "https://aistudio.google.com/apikey) и запустите снова; проверка — python -m bcc_review doctor")
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


_STAGE_ORDER = ["segment", "rules"] + [f"lens_{x}" for x in LENSES] + ["consistency", "quotes", "judge", "clarify",
                                                                     "recheck"]


def _in_stage_order(d: dict) -> dict:
    """Этапы в порядке конвейера, а не в порядке завершения параллельных линз: отчёт повторяем байт в байт."""
    rank = {k: i for i, k in enumerate(_STAGE_ORDER)}
    return {k: d[k] for k in sorted(d, key=lambda k: rank.get(k, len(rank)))}


def _uniq(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --------------------------------------------------------------------------- быстрый старт: перевод ссылок

def _span(r: dict) -> tuple[int, int]:
    a = int(r.get("line_start") or 0)
    b = int(r.get("line_end") or a)
    return a, max(a, b)


def remap_table(heur: list[dict], model: list[dict]) -> dict[str, list[str]]:
    """ID таблицы эвристики → ID нарезки моделью: требования, чьи строки пересекаются; без пересечения —
    ближайшее требование модели не дальше 2 строк; иначе ссылка пропадает (пустой список)."""
    spans = [(str(m.get("id")), *_span(m)) for m in model if m.get("id")]
    out: dict[str, list[str]] = {}
    for h in heur:
        hid = str(h.get("id") or "")
        if not hid:
            continue
        a, b = _span(h)
        hit = [mid for mid, ma, mb in spans if ma <= b and a <= mb]
        if not hit and spans:
            dist, mid = min((min(abs(a - mb), abs(ma - b)), mid) for mid, ma, mb in spans)
            hit = [mid] if dist <= 2 else []
        out[hid] = hit
    return out


def _ids_for_lines(lines: list[int], model: list[dict]) -> list[str]:
    out: list[str] = []
    for n in lines:
        for m in model:
            a, b = _span(m)
            if a <= n <= b and m.get("id") and m["id"] not in out:
                out.append(str(m["id"]))
    return out


def remap_output(out: dict, mapping: dict[str, list[str]], model: list[dict]) -> None:
    """Перевести на месте все ссылки на требования в выходе рецензента (CONTRACT 2.3, 2.5)."""
    model_ids = {str(m.get("id")) for m in model if m.get("id")}

    def many(ids: Any) -> list[str]:
        res: list[str] = []
        for x in ids if isinstance(ids, list) else ([ids] if ids else []):
            x = str(x)
            # ID эвристики → по строкам; чужой для эвристики, но известный модели ID оставляем как есть
            targets = mapping[x] if x in mapping else ([x] if x in model_ids else [])
            for y in targets:
                if y not in res:
                    res.append(y)
        return res

    def one(x: Any) -> str:
        res = many(x)
        return res[0] if res else ""

    for c in out.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        ids = many(c.get("requirement_ids") or [])
        if not ids:  # ссылок не осталось — по строкам цитат
            lines = [int(e.get("line") or e.get("line_start") or 0) for e in c.get("evidence") or []
                     if isinstance(e, dict)]
            ids = _ids_for_lines([n for n in lines if n], model)
        c["requirement_ids"] = ids
        if c.get("acceptance_row"):
            c["acceptance_row"] = one(c["acceptance_row"]) or c["acceptance_row"]
    for chk in out.get("acceptance_checks") or []:
        if isinstance(chk, dict):
            if chk.get("row_requirement_id"):
                chk["row_requirement_id"] = one(chk["row_requirement_id"])
            if "rule_requirement_ids" in chk:
                chk["rule_requirement_ids"] = many(chk.get("rule_requirement_ids") or [])
    for tc in out.get("test_cases") or []:
        if isinstance(tc, dict) and "requirement_ids" in tc:
            tc["requirement_ids"] = many(tc.get("requirement_ids") or [])
    for p in out.get("pair_checks") or []:
        if isinstance(p, dict):
            for k in ("a", "b"):
                if p.get(k):
                    p[k] = one(p[k])
    for t in out.get("trace") or []:
        if isinstance(t, dict):
            if t.get("requirement_id"):
                t["requirement_id"] = one(t["requirement_id"])
            for k in ("verified_by", "implemented_by"):
                if k in t:
                    t[k] = many(t.get(k) or [])
    if isinstance(out.get("trace"), list):  # две строки эвристики могли слиться в одно требование модели
        seen: dict[str, dict] = {}
        merged = []
        for t in out["trace"]:
            rid = t.get("requirement_id") if isinstance(t, dict) else None
            if not rid:
                continue
            if rid in seen:
                for k in ("verified_by", "implemented_by"):
                    seen[rid][k] = _uniq(list(seen[rid].get(k) or []) + list(t.get(k) or []))
                continue
            seen[rid] = t
            merged.append(t)
        out["trace"] = merged


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
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Отчёт Markdown собран упрощённо: {type(exc).__name__}: {exc}")
        md_text = fallback_markdown(report)
        extra = report.get("extra_markdown") or []
        if extra:
            md_text = md_text.rstrip() + "\n\n" + "\n\n".join(x.strip() for x in extra if x) + "\n"
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


def _unread_view(path: Path) -> dict:
    """Паспорт нечитаемого входа для отчёта о сбое: тот же контракт (``contracts/v2.json``), что у прочитанного."""
    try:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        sha = hashlib.sha256(b"").hexdigest()
    fmt = {".md": "md", ".markdown": "md", ".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html"}.get(
        path.suffix.lower(), "txt")
    return {"title": path.name, "file": path.name or "input", "format": fmt, "sha256": sha, "lines": []}


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
        view = p.ctx.view if p.ctx else _unread_view(Path(input_path))
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
