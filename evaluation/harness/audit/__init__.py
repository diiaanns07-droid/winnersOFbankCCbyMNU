"""Проверка состава прогонов до подсчёта (bcc-eval-audit/1).

    python -m evaluation.harness.audit --gold labels.jsonl --run out/ro --run out/llm --out out/audit

Аудит читает только файлы каталогов прогона: run_config.json, predictions.jsonl, reports/**/report.json,
reports/index.json и манифест. Продукт и сеть он не вызывает. Код подсчёта (score, matching) не импортирует,
поэтому от политики сопоставления дефектов не зависит; harness_sha256 счётчика от него не меняется.

Единица проверки — case_id эталона в основном представлении прогона; «пара» — этот кейс во всех прогонах.
* SHA-256 входа: report.run.source_sha256 (или document.id) = SHA файла по манифесту (без манифеста —
  source_sha256 эталона) и одинаков во всех прогонах.
* Повтор: больше одной строки run или одного report.json на кейс в прогоне.
* Пропуск: нет report.json, run.status=failed или отчёта нет в predictions.jsonl. Пропуск в части прогонов —
  нарушение; во всех прогонах — симметричный пропуск (кейс выпадает из обоих наборов одинаково).
* Режим: report.run.mode = запрошенному; rules_only без физических вызовов; rules_plus_llm — хотя бы один
  этап с вызовом модели завершён ok/cached.
* Условия прогонов: манифест, кэш, версия счётчика, agent_commit и agent_version продукта, формат кейса.
Отчёт без нужных полей (старый формат) даёт «неизвестно», а не «допустимо» и не «нарушение».
partial, в котором модель ответила, допустим и показывается отдельно с фактическим покрытием LLM.

Коды выхода: 0 — все пары допустимы; 3 — есть нарушения; 4 — нарушений нет, но есть неизвестные; 2 — ошибка входа.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "bcc-eval-audit/1"
MODES = ("rules_only", "rules_plus_llm", "mock")
OK_STAGE = ("ok", "cached")
NOT_OK_STAGE = ("failed", "partial")
EXIT_OK, EXIT_INPUT, EXIT_VIOLATIONS, EXIT_UNKNOWN = 0, 2, 3, 4

# код → (вид, название); вид: violation | unknown | info
CODES = {
    "sha_mismatch": ("violation", "SHA входа не совпадает: под тем же именем другой файл"),
    "repeat": ("violation", "документ прогнан повторно"),
    "missing_report": ("violation", "нет отчёта в части прогонов"),
    "mode_mismatch": ("violation", "режим отчёта не совпадает с запрошенным"),
    "config_mismatch": ("violation", "прогоны собраны в разных условиях"),
    "unknown": ("unknown", "неизвестно: в отчёте нет нужных полей"),
    "missing_all": ("info", "нет измерения во всех прогонах (симметричный пропуск)"),
    "partial": ("info", "partial, допустимо: модель ответила, часть этапов не завершена"),
    "extra_render": ("info", "дополнительное представление: в основные метрики не входит"),
    "outside_gold": ("info", "отчёт вне эталона"),
}

# поля report.json, без которых пару нельзя проверить; ключ — что проверяется
REQUIRED_ALL = {"sha": "run.source_sha256 или document.id", "mode": "run.mode", "status": "run.status"}
REQUIRED_BY_MODE = {"rules_only": {"calls": "run.calls.physical"},
                    "rules_plus_llm": {"calls": "run.calls.physical", "stages": "run.stages"},
                    "mock": {}}


class AuditInputError(ValueError):
    """Вход не читается: сообщение называет файл и причину."""


def audit_sha256() -> str:
    """Хеш кода аудита (переводы строк приведены к LF)."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(p.name.encode("utf-8") + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditInputError(f"{p}: не читается как JSON: {exc}") from exc


def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AuditInputError(f"{p}: не читается: {exc}") from exc
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditInputError(f"{p}:{n}: не JSON: {exc.msg}") from exc
        if isinstance(row, dict):
            row["_where"] = f"{p.parent.name}/{p.name}:{n}"
            rows.append(row)
    return rows


def _short(v: Any) -> str:
    return v[:12] if isinstance(v, str) else "—" if v is None else str(v)


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _one(values) -> Any:
    """Одно значение, список различных значений или None."""
    keys = sorted({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values if v is not None})
    return None if not keys else json.loads(keys[0]) if len(keys) == 1 else [json.loads(k) for k in keys]


# ----------------------------------------------------------------------------- эталон
@dataclass
class GoldCase:
    case_id: str
    family: str
    source_sha256: str
    outcome: str  # present | clean


def load_gold(path: str | Path) -> dict[str, GoldCase]:
    by_case: dict[str, list[dict]] = {}
    for row in _read_jsonl(Path(path)):
        if not isinstance(row.get("case_id"), str) or not isinstance(row.get("source_sha256"), str):
            raise AuditInputError(f"{path} ({row['_where']}): нужны case_id и source_sha256")
        by_case.setdefault(row["case_id"], []).append(row)
    cases = {}
    for cid, rows in sorted(by_case.items()):
        shas = {r["source_sha256"] for r in rows}
        if len(shas) != 1:
            raise AuditInputError(f"{path}: у кейса {cid} разные source_sha256 в строках эталона")
        outcomes = {r.get("expected_outcome") for r in rows}
        cases[cid] = GoldCase(cid, str(rows[0].get("family") or ""), shas.pop(),
                              "present" if "present" in outcomes else "clean")
    return cases


# ------------------------------------------------------------------------------ отчёт
@dataclass
class Report:
    path: Path
    rel: str
    unreadable: str | None = None
    sha: str | None = None
    mode: str | None = None
    status: str | None = None
    status_reasons: list[str] = field(default_factory=list)
    run_id: str | None = None
    source_name: str | None = None
    agent_commit: str | None = None
    agent_version: str | None = None
    provider: str | None = None
    model: str | None = None
    physical: int | None = None
    failed_calls: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    stages: list[dict] | None = None
    requirements: int | None = None
    reviewed: int | None = None
    stderr: dict | None = None

    @property
    def unreported_errors(self) -> int:
        """Ошибки адаптера из stderr.txt сверх run.calls.failed: вызовы, которых отчёт не учёл."""
        if not self.stderr:
            return 0
        return max(0, self.stderr["errors"] - (self.failed_calls or 0))

    def missing(self, mode: str | None) -> list[str]:
        need = dict(REQUIRED_ALL, **REQUIRED_BY_MODE.get(mode or "", {}))
        have = {"sha": self.sha, "mode": self.mode, "status": self.status, "calls": self.physical,
                "stages": self.stages}
        return [label for key, label in need.items() if have[key] is None]

    @property
    def llm(self) -> dict:
        """Фактическое покрытие LLM по report.run.stages; при пустом списке этапов — по run.calls."""
        if self.stages is None:
            return {"known": False, "physical_calls": self.physical}
        called = [s for s in self.stages if (_int(s.get("calls")) or 0) > 0 or (_int(s.get("cache_hits")) or 0) > 0]
        ok = [s["name"] for s in called if s.get("status") in OK_STAGE]
        basis = "stages"
        if not self.stages:  # этапы не перечислены: судить можно только по счётчику вызовов
            basis, ok = "calls", (["run.calls"] if (self.physical or 0) - (self.failed_calls or 0) > 0 else [])
        return {"known": True, "basis": basis, "llm_ok": bool(ok), "stages_called": len(called) or len(ok),
                "stages_ok": ok,
                "stages_not_ok": [f"{s['name']}={s.get('status')}(calls={s.get('calls')})" for s in self.stages
                                  if s.get("status") in NOT_OK_STAGE],
                "stages_skipped": [s["name"] for s in self.stages if s.get("status") == "skipped"],
                "physical_calls": self.physical, "failed_calls": self.failed_calls,
                "adapter_errors_stderr": None if self.stderr is None else self.stderr["errors"],
                "unreported_errors": self.unreported_errors,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "requirements_reviewed": None if self.requirements is None else f"{self.reviewed}/{self.requirements}"}

    def llm_text(self) -> str:
        c = self.llm
        if not c["known"]:
            return "покрытие LLM неизвестно (нет run.stages)"
        s = (f"этапов с вызовом модели {c['stages_called']}, ok {len(c['stages_ok'])}"
             f" ({', '.join(c['stages_ok']) or '—'}); физ. вызовов {_short(c['physical_calls'])}")
        if c["stages_not_ok"]:
            s += "; не завершены: " + ", ".join(c["stages_not_ok"])
        if self.unreported_errors:
            s += (f"; в stderr.txt ошибок адаптера {self.stderr['errors']} ("
                  + ", ".join(f"{k}×{v}" for k, v in self.stderr["kinds"].items())
                  + f"), в run.calls.failed {_short(self.failed_calls)}: отчёт их не учёл")
        return s


def adapter_errors(report_dir: Path) -> dict | None:
    """Ошибки адаптера провайдера из stderr.txt, который раннер сохраняет рядом с отчётом.

    Адаптер команды печатает в stderr строку `anthropic {json}` (или `gemini {json}`) на неуспешный вызов.
    В сборке 2821989 такие вызовы не попадают в run.calls и run.stages, поэтому stderr — единственный файл,
    где они видны. None — stderr.txt нет; last_line — последняя строка (причина падения процесса)."""
    p = report_dir / "stderr.txt"
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    kinds: dict[str, int] = {}
    for line in text.splitlines():
        head, _, rest = line.partition(" ")
        if head not in ("anthropic", "gemini") or not rest.startswith("{"):
            continue
        try:
            rec = json.loads(rest)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "error":
            k = f"{rec.get('kind') or 'error'}/{rec.get('http_status') or '—'}"
            kinds[k] = kinds.get(k, 0) + 1
    lines = [x for x in text.splitlines() if x.strip()]
    return {"errors": sum(kinds.values()), "kinds": dict(sorted(kinds.items())),
            "last_line": lines[-1][:300] if lines else None}


def read_report(path: Path, root: Path) -> Report:
    rel = path.relative_to(root).as_posix()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("корень не объект")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return Report(path, rel, unreadable=str(exc))
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    doc = data.get("document") if isinstance(data.get("document"), dict) else {}
    calls = run.get("calls") if isinstance(run.get("calls"), dict) else {}
    tokens = run.get("tokens") if isinstance(run.get("tokens"), dict) else {}
    summ = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    sha = run.get("source_sha256") or doc.get("id")
    stages = run.get("stages")
    stages = [s for s in stages if isinstance(s, dict) and isinstance(s.get("name"), str)] \
        if isinstance(stages, list) else None
    return Report(
        path, rel, sha=sha if isinstance(sha, str) else None,
        mode=run.get("mode") if isinstance(run.get("mode"), str) else None,
        status=run.get("status") if isinstance(run.get("status"), str) else None,
        status_reasons=[str(x) for x in run.get("status_reasons") or []], run_id=run.get("run_id"),
        source_name=run.get("source_name"), agent_commit=run.get("agent_commit"),
        agent_version=run.get("agent_version"), provider=run.get("provider"), model=run.get("model"),
        physical=_int(calls.get("physical")), failed_calls=_int(calls.get("failed")),
        tokens_in=_int(tokens.get("input")), tokens_out=_int(tokens.get("output")), stages=stages,
        requirements=_int(summ.get("requirements")), reviewed=_int(summ.get("reviewed_requirements")),
        stderr=adapter_errors(path.parent))


# ----------------------------------------------------------------------------- прогон
@dataclass
class RunDir:
    name: str
    root: Path
    configs: list[dict]
    requested_mode: str | None
    rows: list[dict]            # строки record=run
    finding_rows: list[dict]
    reports: list[Report]
    report_case: dict[str, tuple[str | None, str | None]]  # rel → (case_id, format) по каталогу отчёта
    manifest: dict | None
    manifest_path: str | None
    notes: list[str] = field(default_factory=list)


def _report_dir_case(d: Path, index: dict) -> tuple[str | None, str | None]:
    """Кейс и формат по каталогу отчёта: reports/index.json (0.1.2) или <case_id>__<fmt> (0.1.0)."""
    rid = index.get(d.name)
    if not isinstance(rid, str) and "__" in d.name:
        rid = "@".join(d.name.rsplit("__", 1))
    if isinstance(rid, str) and "@" in rid:
        cid, fmt = rid.rsplit("@", 1)
        return cid, fmt
    return None, None


def _manifest_for(root: Path, configs: list[dict], explicit: str | None) -> tuple[dict | None, str | None]:
    cands = [Path(explicit)] if explicit else []
    cands.append(root / "manifest.json")
    cands += [Path(c["manifest"]) for c in configs if isinstance(c.get("manifest"), str)]
    for p in cands:
        if p.is_file():
            return _read_json(p), str(p)
    return None, None


def load_run(spec: str, manifest: str | None = None) -> RunDir:
    name, sep, path = spec.partition("=")
    if not sep:
        name, path = "", spec
    root = Path(path)
    if not root.is_dir():
        raise AuditInputError(f"{root}: каталог прогона не найден")
    cfg_paths = sorted(p for p in root.rglob("run_config.json") if "reports" not in p.relative_to(root).parts)
    configs = [dict(_read_json(p), _path=p.relative_to(root).as_posix()) for p in cfg_paths]
    if (root / "predictions.jsonl").is_file():
        pred_paths = [root / "predictions.jsonl"]
    else:
        pred_paths = [p.parent / "predictions.jsonl" for p in cfg_paths if (p.parent / "predictions.jsonl").is_file()]
    rows: list[dict] = []
    for p in pred_paths:
        rows.extend(_read_jsonl(p))
    run_rows = [r for r in rows if r.get("record") == "run"]
    findings = [r for r in rows if r.get("record", "finding") == "finding"]
    modes = sorted({c.get("mode") for c in configs if c.get("mode")}) or \
        sorted({r.get("mode") for r in run_rows if r.get("mode")})
    requested = modes[0] if len(modes) == 1 else None
    reports, report_case = [], {}
    for p in sorted(root.rglob("report.json")):
        rep = read_report(p, root)
        reports.append(rep)
        idx = p.parent.parent / "index.json"
        index = _read_json(idx) if idx.is_file() else {}
        report_case[rep.rel] = _report_dir_case(p.parent, index if isinstance(index, dict) else {})
    man, man_path = _manifest_for(root, configs, manifest)
    run = RunDir(name or requested or root.name, root, configs, requested, run_rows, findings, reports, report_case,
                 man, man_path)
    if not configs:
        run.notes.append("run_config.json нет: запрошенный режим взят из строк run")
    if len(modes) > 1:
        run.notes.append(f"в одном каталоге несколько режимов {modes}")
    if not pred_paths:
        run.notes.append("predictions.jsonl нет: проверка только по report.json")
    if man is None:
        run.notes.append("манифест не найден: ожидаемый SHA берётся из эталона")
    return run


def _match_report(row: dict, run: RunDir) -> Report | None:
    """report_path строки run → найденный report.json. Каталог могли скопировать, поэтому сравнивается хвост пути:
    побеждает самое длинное совпадение, при равенстве — путь, совпавший целиком."""
    rp = row.get("report_path")
    if not isinstance(rp, str):
        return None
    parts = Path(rp.replace("\\", "/")).parts
    best, best_key = None, (2, False)
    for rep in run.reports:
        rparts = Path(rep.rel).parts
        k = 0
        while k < min(len(parts), len(rparts)) and parts[-1 - k] == rparts[-1 - k]:
            k += 1
        key = (k, k == len(rparts))
        if key > best_key:
            best, best_key = rep, key
    return best if best_key[0] >= 3 else None


def _row_dir(row: dict, run: RunDir) -> Path | None:
    """Каталог отчёта строки run в этом каталоге прогона (по хвосту report_path; отчёта может не быть)."""
    rp = row.get("report_path")
    if not isinstance(rp, str):
        return None
    parts = Path(rp.replace("\\", "/")).parts[:-1]
    for k in range(len(parts), 1, -1):
        d = run.root.joinpath(*parts[-k:])
        if d.is_dir():
            return d
    return None


# --------------------------------------------------------------------------- проверка
@dataclass
class Cell:
    """Кейс в одном прогоне."""
    run: str
    fmt: str | None
    rows: list[dict]
    reports: list[Report]
    findings: int
    expected_sha: str | None
    expected_from: str
    state: str = "measured"  # measured | missing | unknown
    problems: list[tuple[str, str, dict]] = field(default_factory=list)  # (код, причина, доказательства)

    @property
    def report(self) -> Report | None:
        return self.reports[0] if len(self.reports) == 1 else None


def _manifest_case(man: dict | None, cid: str) -> dict | None:
    return next((c for c in (man or {}).get("cases", []) if c.get("case_id") == cid), None)


def _primary_fmt(run: RunDir, cid: str, formats: set[str]) -> str | None:
    explicit = {c.get("format") for c in run.configs} - {None, "primary_render"}
    if len(explicit) == 1 and len(run.configs) == 1:
        return explicit.pop()
    mc = _manifest_case(run.manifest, cid)
    if mc and mc.get("primary_render"):
        return mc["primary_render"]
    if len(formats) == 1:
        return next(iter(formats))
    return "md" if "md" in formats else (sorted(formats)[0] if formats else None)


def _cell(run: RunDir, case: GoldCase, info: list[dict]) -> Cell:
    cid = case.case_id
    rows_all = [r for r in run.rows if r.get("case_id") == cid
                or (isinstance(r.get("render_id"), str) and r["render_id"].rsplit("@", 1)[0] == cid)]
    reps: dict[str, Report] = {}
    for r in rows_all:
        rep = _match_report(r, run)
        if rep is not None:
            reps[rep.rel] = rep
    for rep in run.reports:
        dcid, _ = run.report_case.get(rep.rel, (None, None))
        if dcid == cid or (dcid is None and rep.sha == case.source_sha256):
            reps[rep.rel] = rep
    fmt_of = {rel: run.report_case.get(rel, (None, None))[1] for rel in reps}
    formats = {r.get("format") for r in rows_all if r.get("format")} | {f for f in fmt_of.values() if f}
    fmt = _primary_fmt(run, cid, formats)
    for f in sorted(formats - {fmt}):
        info.append({"code": "extra_render", "run": run.name, "case_id": cid,
                     "reason": f"представление {f} (основное — {fmt}): проверка парсера, в пару не входит"})
    render = next((r for r in (_manifest_case(run.manifest, cid) or {}).get("renders", [])
                   if r.get("format") == fmt and r.get("sha256")), None)
    cell = Cell(run.name, fmt, [r for r in rows_all if r.get("format") in (None, fmt)],
                [rep for rel, rep in sorted(reps.items()) if fmt_of[rel] in (None, fmt)],
                sum(1 for x in run.finding_rows if x.get("case_id") == cid and x.get("format") in (None, fmt)),
                render["sha256"] if render else case.source_sha256, "манифест" if render else "эталон")
    _check_cell(cell, run)
    return cell


def _check_cell(cell: Cell, run: RunDir) -> None:
    add = cell.problems.append
    run_ids = sorted({str(r["run_id"]) for r in cell.rows if r.get("run_id")} |
                     {str(rep.run_id) for rep in cell.reports if rep.run_id})
    if len(cell.rows) > 1 or len(cell.reports) > 1:
        same = len(cell.rows) > 1 and len({json.dumps({k: v for k, v in r.items() if k != "_where"},
                                                      sort_keys=True, ensure_ascii=False) for r in cell.rows}) == 1
        why = (f"строк run: {len(cell.rows)} ({', '.join(r['_where'] for r in cell.rows) or '—'}), "
               f"report.json: {len(cell.reports)} ({', '.join(x.rel for x in cell.reports) or '—'})")
        why += "; одна и та же строка записана дважды" if same else (f"; run_id: {', '.join(run_ids)}" if run_ids else "")
        if cell.findings:
            why += f"; находок кейса в predictions.jsonl: {cell.findings} — подсчёт объединит находки всех запусков"
        add(("repeat", why, {"rows": [r["_where"] for r in cell.rows], "reports": [x.rel for x in cell.reports],
                             "run_ids": run_ids}))
    rep = cell.reports[0] if cell.reports else None
    row = cell.rows[0] if cell.rows else None
    if rep is None:
        cell.state = "missing"
        if row is None:
            why = "нет ни строки run, ни report.json"
        elif row.get("status") == "failed":
            why = "строка run status=failed: " + ("; ".join(row.get("violations") or []) or "причина не указана")
            d = _row_dir(row, run)
            err = adapter_errors(d) if d else None
            if err and err["last_line"]:
                why += f"; stderr.txt: {err['last_line']}"
        else:
            why = (f"строка run status={row.get('status')}, но report.json нет на месте "
                   f"({row.get('report_path') or 'путь не указан'})")
            if cell.findings:
                why += f"; находок в predictions.jsonl: {cell.findings} — подсчёт посчитает кейс измеренным"
        add(("missing_report", why, {"rows": [r["_where"] for r in cell.rows]}))
        return
    if rep.unreadable:
        cell.state = "unknown"
        add(("unknown", f"{rep.rel} не читается: {rep.unreadable}", {"report": rep.rel}))
        return
    if rep.status == "failed":
        cell.state = "missing"
        add(("missing_report", "report.run.status=failed: " + ("; ".join(rep.status_reasons[:2]) or "причина не указана"),
             {"report": rep.rel}))
        return
    if run.rows and not cell.rows:
        cell.state = "missing"
        add(("missing_report", f"{rep.rel} есть, но строки run в predictions.jsonl нет: подсчёт его не увидит",
             {"report": rep.rel}))
        return
    requested = next((r.get("mode") for r in cell.rows if r.get("mode") in MODES), None) or run.requested_mode
    # SHA входа
    row_sha = next((r.get("source_sha256") for r in cell.rows if r.get("source_sha256")), None)
    if rep.sha is not None and rep.sha != cell.expected_sha:
        why = f"report.run.source_sha256={_short(rep.sha)}…, ожидается {_short(cell.expected_sha)}… ({cell.expected_from})"
        if rep.source_name:
            why += f"; source_name={rep.source_name}"
        if row_sha and row_sha != rep.sha:
            why += f"; строка run: {_short(row_sha)}… — подсчёт сопоставит отчёт с эталоном прежнего файла"
        add(("sha_mismatch", why, {"report_sha256": rep.sha, "expected_sha256": cell.expected_sha,
                                   "row_sha256": row_sha, "report": rep.rel}))
    # режим и покрытие LLM
    llm = rep.llm
    if rep.mode is not None and requested is not None and rep.mode != requested:
        why = f"запрошен {requested}, report.run.mode={rep.mode}; {rep.llm_text()}"
        cause = next((s for s in rep.status_reasons if "модель не вызывалась" in s or "адаптер" in s), None)
        if cause:
            why += f"; {cause}"
        add(("mode_mismatch", why, {"requested": requested, "report_mode": rep.mode, "report": rep.rel}))
    elif rep.mode == "rules_only" and (rep.physical or 0) > 0:
        add(("mode_mismatch", f"rules_only, но run.calls.physical={rep.physical}", {"report": rep.rel}))
    elif rep.mode == "rules_plus_llm" and llm["known"] and not llm["llm_ok"]:
        add(("mode_mismatch", "report.run.mode=rules_plus_llm, но ни один этап с вызовом модели не завершён ok",
             {"report": rep.rel}))
    missing = rep.missing(requested)
    if missing:
        cell.state = "unknown"
        add(("unknown", f"в отчёте нет полей: {', '.join(missing)} ({rep.rel})",
             {"report": rep.rel, "missing_fields": missing}))
    if requested is None:
        cell.state = "unknown"
        add(("unknown", "запрошенный режим неизвестен: нет run_config.json и mode в строках run", {}))
    if (cell.state == "measured" and rep.mode == "rules_plus_llm" and llm["known"] and llm["llm_ok"]
            and not any(k == "mode_mismatch" for k, _, _ in cell.problems)):
        if rep.status == "partial":
            add(("partial", rep.llm_text(), {"report": rep.rel}))
        elif rep.unreported_errors:
            add(("partial", f"скрытый partial: report.run.status={rep.status}, но {rep.llm_text()}",
                 {"report": rep.rel, "stderr": rep.stderr}))


def _conditions(run: RunDir) -> dict[str, Any]:
    cfg = run.configs
    return {
        "manifest_sha256": _one([c.get("manifest_sha256") for c in cfg] + [r.get("manifest_sha256") for r in run.rows]),
        "cache": _one([(c["cache"].get("policy") if isinstance(c.get("cache"), dict) else c.get("cache")) for c in cfg]),
        "harness_version": _one([c.get("harness_version") for c in cfg]),
        "agent_commit": _one([r.agent_commit for r in run.reports]),
        "agent_version": _one([r.agent_version for r in run.reports]),
    }


def audit(gold_path: str | Path, run_specs: list[str], manifest: str | None = None,
          expect_agent_commit: str | None = None) -> dict:
    gold = load_gold(gold_path)
    runs = [load_run(s, manifest) for s in run_specs]
    names = [r.name for r in runs]
    if len(set(names)) != len(names):
        raise AuditInputError(f"имена прогонов повторяются: {names}; задайте ИМЯ=каталог")
    matrix: list[dict] = []
    info: list[dict] = []

    # ---- условия прогонов (case_id "*": затронуты все пары)
    conditions = {r.name: _conditions(r) for r in runs}
    for key in ("manifest_sha256", "cache", "harness_version", "agent_commit", "agent_version"):
        vals = {n: c[key] for n, c in conditions.items()}
        inner = {n: v for n, v in vals.items() if isinstance(v, list)}
        if inner:
            matrix.append({"code": "config_mismatch", "run": ", ".join(inner), "case_id": "*",
                           "reason": f"{key}: внутри прогона несколько значений {inner}"})
        elif len({json.dumps(v) for v in vals.values()}) > 1:
            matrix.append({"code": "config_mismatch", "run": ", ".join(names), "case_id": "*",
                           "reason": f"{key} различается: " + "; ".join(f"{n}={_short(v)}" for n, v in vals.items())})
    for n, c in conditions.items():
        if expect_agent_commit and c["agent_commit"] is None:
            matrix.append({"code": "unknown", "run": n, "case_id": "*",
                           "reason": "agent_commit в отчётах не указан: сборку продукта не проверить"})
        elif expect_agent_commit and (isinstance(c["agent_commit"], list)
                                      or not str(c["agent_commit"]).startswith(expect_agent_commit)):
            matrix.append({"code": "config_mismatch", "run": n, "case_id": "*",
                           "reason": f"agent_commit={c['agent_commit']}, ожидается {expect_agent_commit}"})

    gold_shas = {g.source_sha256 for g in gold.values()}
    for run in runs:
        for rep in run.reports:
            dcid, _ = run.report_case.get(rep.rel, (None, None))
            if dcid not in gold and rep.sha not in gold_shas:
                info.append({"code": "outside_gold", "run": run.name, "case_id": dcid or "—",
                             "reason": f"{rep.rel}: SHA {_short(rep.sha)}… нет в эталоне"})

    # ---- пары
    pairs = []
    for cid, case in gold.items():
        cells = [_cell(run, case, info) for run in runs]
        if all(c.state == "missing" for c in cells):
            for c in cells:
                c.problems = [("missing_all" if k == "missing_report" else k, why, ev) for k, why, ev in c.problems]
        with_rep = [c for c in cells if c.report is not None and c.report.sha]
        if len({c.report.sha for c in with_rep}) > 1 and not any(k == "sha_mismatch" for c in cells
                                                                   for k, _, _ in c.problems):
            why = "SHA входа различается между прогонами: " + ", ".join(f"{c.run}={_short(c.report.sha)}…"
                                                                         for c in with_rep)
            for c in with_rep:
                c.problems.append(("sha_mismatch", why, {}))
        if len({c.fmt for c in cells}) > 1:
            for c in cells:
                c.problems.append(("config_mismatch", "основной формат кейса различается: " + ", ".join(
                    f"{x.run}={x.fmt}" for x in cells), {}))
        codes = {k for c in cells for k, _, _ in c.problems}
        kinds = {CODES[k][0] for k in codes}
        verdict = ("violation" if "violation" in kinds else "unknown" if "unknown" in kinds else
                   "excluded" if "missing_all" in codes else "admissible")
        for c in cells:
            for code, why, ev in c.problems:
                if code == "missing_report" and case.outcome == "clean":
                    why += " [чистый кейс: его ложные тревоги выпадут из подсчёта, precision завысится]"
                row = {"code": code, "run": c.run, "case_id": cid, "expected_outcome": case.outcome,
                       "reason": why, "evidence": ev}
                (matrix if CODES[code][0] != "info" else info).append(row)
        pairs.append({
            "case_id": cid, "family": case.family, "expected_outcome": case.outcome, "verdict": verdict,
            "gold_sha256": case.source_sha256, "codes": sorted(codes),
            "runs": {c.run: {
                "format": c.fmt, "expected_sha256": c.expected_sha, "expected_from": c.expected_from,
                "report": c.report.rel if c.report else None, "report_sha256": c.report.sha if c.report else None,
                "run_id": c.report.run_id if c.report else None, "status": c.report.status if c.report else None,
                "mode": c.report.mode if c.report else None, "run_rows": len(c.rows), "reports": len(c.reports),
                "findings_rows": c.findings, "llm": c.report.llm if c.report and not c.report.unreadable else None,
            } for c in cells},
        })

    global_violation = any(m["case_id"] == "*" and CODES[m["code"]][0] == "violation" for m in matrix)
    has_violation = any(CODES[m["code"]][0] == "violation" for m in matrix)
    has_unknown = any(CODES[m["code"]][0] == "unknown" for m in matrix)
    admissible = [] if global_violation else [p["case_id"] for p in pairs if p["verdict"] == "admissible"]
    coverage = {}
    for run in runs:
        cells = [p["runs"][run.name] for p in pairs]
        measured = [c for c in cells if c["report"] and c["status"] in ("complete", "partial")]
        known = [c for c in measured if c["llm"] and c["llm"].get("known")]
        not_ok: dict[str, int] = {}
        for c in known:
            for s in c["llm"]["stages_not_ok"]:
                not_ok[s.split("=")[0]] = not_ok.get(s.split("=")[0], 0) + 1
        coverage[run.name] = {
            "requested_mode": run.requested_mode, "cases_with_report": len(measured),
            "complete": sum(1 for c in measured if c["status"] == "complete"),
            "partial": sum(1 for c in measured if c["status"] == "partial"),
            "llm_known": len(known), "llm_ok": sum(1 for c in known if c["llm"]["llm_ok"]),
            "physical_calls": sum(c["llm"]["physical_calls"] or 0 for c in known),
            "adapter_errors_stderr": sum(c["llm"]["adapter_errors_stderr"] or 0 for c in known),
            "reports_with_unreported_errors": sum(1 for c in known if c["llm"]["unreported_errors"]),
            "stages_not_ok": dict(sorted(not_ok.items())),
        }
    exit_code = EXIT_VIOLATIONS if has_violation else EXIT_UNKNOWN if has_unknown else EXIT_OK
    return {
        "schema": SCHEMA, "audit_sha256": audit_sha256(),
        "gold": {"path": str(gold_path), "sha256": _sha_file(Path(gold_path)), "cases": len(gold),
                 "clean": sum(1 for g in gold.values() if g.outcome == "clean")},
        "runs": {r.name: {"dir": str(r.root), "requested_mode": r.requested_mode,
                          "configs": [c["_path"] for c in r.configs], "manifest": r.manifest_path,
                          "reports": len(r.reports), "run_rows": len(r.rows), "conditions": conditions[r.name],
                          "notes": r.notes} for r in runs},
        "verdict": {"exit_code": exit_code,
                    "text": ("НАРУШЕНИЯ: сравнивать F1 на этом составе нельзя" if has_violation else
                             "НЕИЗВЕСТНО: часть пар не доказана" if has_unknown else
                             "состав сопоставим: все пары допустимы"),
                    "pairs": len(pairs), "admissible": len(admissible),
                    "violation_cases": sorted(p["case_id"] for p in pairs if p["verdict"] == "violation"),
                    "unknown_cases": sorted(p["case_id"] for p in pairs if p["verdict"] == "unknown"),
                    "excluded_symmetric": sorted(p["case_id"] for p in pairs if p["verdict"] == "excluded"),
                    "run_level": [m for m in matrix if m["case_id"] == "*"]},
        "admissible_case_ids": admissible,
        "matrix": matrix, "info": info, "llm_coverage": coverage, "pairs": pairs,
        "limits": [
            "Аудит видит то, что записано в report.json и predictions.jsonl. Был ли ответ модели живым, по файлам "
            "не доказать: это подтверждает журнал Max.",
            "Покрытие LLM считается по run.stages: этап с calls>0 и статусом ok/cached. Неуспешные вызовы, которые "
            "продукт не записал в stages и calls, видны только по строкам адаптера в reports/*/stderr.txt; если "
            "stderr.txt нет, они не видны.",
        ],
    }


# ----------------------------------------------------------------------------- вывод
def _cell_md(c: dict) -> str:
    if not c["report"]:
        return "нет отчёта"
    s = f"`{_short(c['report_sha256'])}` {c['status']}"
    if c["mode"] == "rules_plus_llm" and c["llm"] and c["llm"].get("known"):
        s += f", этапов LLM ok {len(c['llm']['stages_ok'])}/{c['llm']['stages_called']}"
    elif c["mode"] and c["mode"] != "rules_plus_llm":
        s += f", {c['mode']}"
    return s


def render_md(res: dict) -> str:
    names = list(res["runs"])
    v = res["verdict"]
    out = [f"# Состав прогонов до подсчёта ({res['schema']})", "",
           f"**{v['text']}** (код выхода {v['exit_code']}). Пар: {v['pairs']}, допустимых: {v['admissible']}, "
           f"с нарушениями: {len(v['violation_cases'])}, неизвестных: {len(v['unknown_cases'])}, "
           f"симметричных пропусков: {len(v['excluded_symmetric'])}.", "",
           f"Эталон: `{res['gold']['path']}`, sha256 `{_short(res['gold']['sha256'])}…`, кейсов {res['gold']['cases']} "
           f"(чистых {res['gold']['clean']}). Код аудита: `{_short(res['audit_sha256'])}…`.", "",
           "## Прогоны", "",
           "| Прогон | Запрошен | report.json | Строк run | Манифест | Кэш | Счётчик | agent_commit |",
           "| :--- | :--- | ---: | ---: | :--- | :--- | :--- | :--- |"]
    for n, r in res["runs"].items():
        c = r["conditions"]
        out.append(f"| {n} | {r['requested_mode'] or '—'} | {r['reports']} | {r['run_rows']} | "
                   f"`{_short(c['manifest_sha256'])}` | {c['cache'] or '—'} | {c['harness_version'] or '—'} | "
                   f"`{_short(c['agent_commit'])}` |")
    notes = [f"- {n}: {x}" for n, r in res["runs"].items() for x in r["notes"]]
    if notes:
        out += [""] + notes
    out += ["", "## Матрица: нарушение → case_id → причина", ""]
    if not res["matrix"]:
        out.append("Нарушений и неизвестных нет.")
    else:
        out += ["| Код | Прогон | case_id | Ожидание | Причина |", "| :--- | :--- | :--- | :--- | :--- |"]
        out += [f"| `{m['code']}` — {CODES[m['code']][1]} | {m['run']} | {m['case_id']} | "
                f"{m.get('expected_outcome', 'все')} | {m['reason']} |" for m in res["matrix"]]
    out += ["", "## Фактическое покрытие LLM (report.run.stages и reports/*/stderr.txt)", "",
            "| Прогон | Запрошен | С отчётом | complete / partial | Модель ответила | Физ. вызовов | "
            "Ошибок адаптера в stderr (отчётов, где не учтены) | Этапы failed/partial |",
            "| :--- | :--- | ---: | :--- | ---: | ---: | :--- | :--- |"]
    for n, c in res["llm_coverage"].items():
        bad = ", ".join(f"{k}: {x}" for k, x in c["stages_not_ok"].items()) or "—"
        out.append(f"| {n} | {c['requested_mode'] or '—'} | {c['cases_with_report']} | {c['complete']} / {c['partial']} | "
                   f"{c['llm_ok']} из {c['llm_known']} | {c['physical_calls']} | {c['adapter_errors_stderr']} "
                   f"({c['reports_with_unreported_errors']}) | {bad} |")
    partial = [i for i in res["info"] if i["code"] == "partial"]
    other = [i for i in res["info"] if i["code"] != "partial"]
    if partial:
        out += ["", "## partial — допустимо (модель ответила, часть этапов не завершена)", ""]
        out += [f"- {i['run']}: {i['case_id']} — {i['reason']}" for i in partial]
    if other:
        out += ["", "## Справочно", ""] + [f"- `{i['code']}` {i['run']}: {i['case_id']} — {i['reason']}" for i in other]
    out += ["", "## Пары по ID и SHA", "",
            "| case_id | Ожидание | SHA эталона | " + " | ".join(names) + " | Вердикт |",
            "| :--- | :--- | :--- | " + " | ".join(":---" for _ in names) + " | :--- |"]
    out += [f"| {p['case_id']} | {p['expected_outcome']} | `{_short(p['gold_sha256'])}` | "
            + " | ".join(_cell_md(p["runs"][n]) for n in names) + f" | {p['verdict']} |" for p in res["pairs"]]
    out += ["", "## Ограничения", ""] + [f"- {x}" for x in res["limits"]]
    return "\n".join(out) + "\n"


def write_outputs(res: dict, out_dir: str | Path) -> list[str]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "composition.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "composition.md").write_text(render_md(res), encoding="utf-8")
    with open(d / "matrix.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for m in res["matrix"]:
            fh.write(json.dumps(m, ensure_ascii=False, sort_keys=True) + "\n")
    (d / "admissible_case_ids.txt").write_text("".join(c + "\n" for c in res["admissible_case_ids"]),
                                               encoding="utf-8")
    return ["composition.json", "composition.md", "matrix.jsonl", "admissible_case_ids.txt"]
