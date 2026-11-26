"""Артефакты прогона: ``runs/<run_id>/stages/<этап>.json``, ``trace.jsonl``, ``report.*``.

Файл этапа: ``{"stage", "status", "seconds", "calls", "input", "output", "warnings"}``. По этим файлам
команда ``stage`` перезапускает один этап на готовых входах.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ASTANA = timezone(timedelta(hours=5))


def now_iso() -> str:
    return datetime.now(ASTANA).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(ASTANA).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


class RunDir:
    def __init__(self, root: str | Path, run_id: str | None = None, *, create: bool = True):
        root = Path(root)
        if run_id is None and (root / "stages").is_dir():
            self.path, self.run_id = root, root.name
        else:
            self.run_id = run_id or new_run_id()
            self.path = root / self.run_id
        self.stages = self.path / "stages"
        self._lock = threading.Lock()
        if create:
            self.stages.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ этапы

    def stage_path(self, name: str) -> Path:
        return self.stages / f"{name}.json"

    def save_stage(self, name: str, record: dict) -> Path:
        p = self.stage_path(name)
        tmp = p.with_suffix(f".tmp{os.getpid()}{threading.get_ident()}")
        tmp.write_text(_dump(record), encoding="utf-8")
        tmp.replace(p)
        return p

    def load_stage(self, name: str) -> dict | None:
        p = self.stage_path(name)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def stage_output(self, name: str) -> dict | None:
        rec = self.load_stage(name)
        if rec is None:
            return None
        return rec.get("output") if isinstance(rec.get("output"), dict) else None

    def stage_names(self) -> list[str]:
        return sorted(p.stem for p in self.stages.glob("*.json"))

    def copy_stages_from(self, other: "RunDir", skip: set[str] = frozenset()) -> None:
        for p in other.stages.glob("*.json"):
            if p.stem not in skip:
                shutil.copy2(p, self.stages / p.name)

    # ------------------------------------------------------------------ трасса и прочее

    def trace(self, record: dict) -> None:
        rec = {"t": now_iso(), **record}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path / "trace.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.path / name
        p.write_text(_dump(obj), encoding="utf-8")
        return p


def latest(runs_root: str | Path) -> RunDir | None:
    root = Path(runs_root)
    if not root.is_dir():
        return None
    dirs = sorted((d for d in root.iterdir() if (d / "stages").is_dir()), key=lambda d: d.stat().st_mtime)
    return RunDir(dirs[-1], create=False) if dirs else None
