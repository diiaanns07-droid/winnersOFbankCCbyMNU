"""Прогон продукта по манифесту в режимах rules_only и rules_plus_llm.

Оба режима берут один и тот же манифест, формат представления и настройки кэша. Они
записаны в run_config.json и в каждой строке run, а compare сверяет их перед построением
таблицы.

rules_only запускается в «сетевой песочнице»: из окружения дочернего процесса убраны
ключи провайдеров, а HTTP(S)_PROXY указывает на закрытый порт. Реальный запрос к LLM
физически не может уйти. Дополнительно проверяется, что отчёт сообщает physical_calls = 0
и run.mode = rules_only.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .adapter import report_to_rows
from .schema import Manifest, sha256_file, write_jsonl
from .taxonomy import Taxonomy

MODES = ("rules_only", "rules_plus_llm", "mock")
CACHE_POLICIES = ("off", "on")
DEFAULT_PRODUCT_CMD = f"{shlex.quote(sys.executable)} -m bcc_review {{input}} {{output}}"
SECRET_ENV = re.compile(r"(API_KEY|_TOKEN|SECRET|^ANTHROPIC_|^GEMINI_|^GOOGLE_|^OPENAI_|^VERTEX)", re.I)
DEAD_PROXY = "http://127.0.0.1:9"


def mode_args(mode: str, provider: str | None, cache: str = "off") -> list[str]:
    """Аргументы CLI контракта v1: --offline-lint, --provider, --no-cache."""
    args = ["--no-cache"] if cache == "off" else []
    if mode == "rules_only":
        return ["--offline-lint"] + args
    if mode == "mock":
        return ["--provider", "mock"] + args
    return (["--provider", provider] if provider else []) + args


def child_env(mode: str, cache: str, cache_dir: str | None) -> tuple[dict[str, str], dict]:
    env = dict(os.environ)
    sandbox = {"network_sandbox": False, "removed_env": []}
    if mode == "rules_only":
        removed = sorted(k for k in env if SECRET_ENV.search(k))
        for k in removed:
            env.pop(k)
        for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
            env[k] = DEAD_PROXY
        env.pop("NO_PROXY", None)
        env.pop("no_proxy", None)
        env["BCC_REVIEW_OFFLINE"] = "1"
        sandbox = {"network_sandbox": True, "removed_env": removed, "proxy": DEAD_PROXY}
    env["BCC_REVIEW_CACHE"] = cache
    if cache_dir:
        env["BCC_REVIEW_CACHE_DIR"] = str(Path(cache_dir).resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    return env, sandbox


def select_renders(manifest: Manifest, fmt: str | None, cases: list[str] | None, limit: int | None):
    chosen = []
    for cid in sorted(manifest.cases):
        if cases and cid not in cases:
            continue
        case = manifest.cases[cid]
        want = fmt or case.get("primary_render")
        r = next((x for x in case.get("renders", []) if x["format"] == want), None)
        chosen.append((cid, want, r))
    return chosen[:limit] if limit else chosen


def run_manifest(manifest_path: str, mode: str, out_dir: str, taxonomy: Taxonomy, *, fmt: str | None = None,
                 product_cmd: str = DEFAULT_PRODUCT_CMD, provider: str | None = None, cache: str = "off",
                 cache_dir: str | None = None, cases: list[str] | None = None, limit: int | None = None,
                 timeout: float = 900.0, extra_args: list[str] | None = None, cwd: str | None = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode: {MODES}")
    if cache not in CACHE_POLICIES:
        raise ValueError(f"cache: {CACHE_POLICIES}")
    manifest = Manifest.load(manifest_path)
    root = Path(manifest_path).resolve().parent
    out = Path(out_dir)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    env, sandbox = child_env(mode, cache, cache_dir)
    cache_cfg = {"policy": cache, "flag": "--no-cache" if cache == "off" else None,
                 "dir": str(Path(cache_dir).resolve()) if cache_dir else None}
    config = {
        "schema": "bcc-eval-runconfig/1", "harness_version": __version__, "mode": mode,
        "manifest": str(manifest_path), "manifest_sha256": manifest.sha256, "format": fmt or "primary_render",
        "product_cmd": product_cmd, "mode_args": mode_args(mode, provider, cache), "extra_args": extra_args or [],
        "provider": provider, "cache": cache_cfg, "timeout_s": timeout, **sandbox,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "platform": platform.platform(),
    }
    rows: list[dict] = []
    for cid, want, r in select_renders(manifest, fmt, cases, limit):
        base = {"record": "run", "case_id": cid, "mode": mode, "format": want,
                "manifest_sha256": manifest.sha256, "cache": cache_cfg}
        if r is None:
            rows.append({**base, "status": "failed", "violations": [f"нет представления формата {want}"]})
            continue
        src = root / r["path"]
        dst_md = out / "reports" / r["render_id"].replace("@", "__") / "report.md"
        dst_md.parent.mkdir(parents=True, exist_ok=True)
        cmd = [a.replace("{input}", str(src)).replace("{output}", str(dst_md)) for a in shlex.split(product_cmd)]
        cmd += mode_args(mode, provider, cache) + (extra_args or [])
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, timeout=timeout)
            rc, so, se = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            rc, so, se = None, exc.stdout or b"", (exc.stderr or b"") + b"\n[harness] timeout"
        wall = time.perf_counter() - t0
        (dst_md.parent / "stdout.txt").write_bytes(so or b"")
        (dst_md.parent / "stderr.txt").write_bytes(se or b"")
        rep_json = dst_md.with_suffix(".json")
        base.update({"render_id": r["render_id"], "source_sha256": r["sha256"], "exit_code": rc,
                     "report_path": str(rep_json)})
        if not rep_json.exists():
            rows.append({**base, "status": "failed", "duration_s": round(wall, 3),
                         "violations": [f"нет {rep_json.name} рядом с OUTPUT.md (exit={rc})"]})
            continue
        report = json.loads(rep_json.read_text(encoding="utf-8"))
        got = report_to_rows(report, taxonomy, render_id=r["render_id"], case_id=cid, fmt=want,
                             duration_s=round(wall, 3))
        run_row = got[-1]
        violations = []
        rep_sha = (report.get("run") or {}).get("source_sha256") or (report.get("document") or {}).get("id")
        if rep_sha and rep_sha != sha256_file(src):
            violations.append("source_sha256 отчёта не совпадает с SHA-256 входного файла")
        if run_row.get("mode") != mode:
            violations.append(f"run.mode={run_row.get('mode')!r}, запрошен {mode}")
        if mode == "rules_only" and (run_row.get("physical_calls") or 0) != 0:
            violations.append(f"rules_only: physical_calls={run_row.get('physical_calls')} (ожидается 0)")
        if mode == "rules_only" and run_row.get("physical_calls") is None:
            violations.append("rules_only: отчёт не сообщает число физических вызовов")
        if rc not in (0, None) and run_row.get("status") == "complete":
            violations.append(f"exit_code={rc} при status=complete")
        for row in got[:-1]:
            row["mode"] = mode
        run_row.update({**base, "status": run_row.get("status", "complete"), "violations": violations,
                        "physical_calls": run_row.get("physical_calls"),
                        "tokens_in": run_row.get("tokens_in"), "tokens_out": run_row.get("tokens_out"),
                        "provider": run_row.get("provider"), "model": run_row.get("model")})
        rows.extend(got)
    config["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config["renders"] = sum(1 for x in rows if x.get("record") == "run")
    (out / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_jsonl(out / "predictions.jsonl", rows)
    return config
