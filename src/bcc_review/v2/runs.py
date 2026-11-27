"""Артефакты прогона: ``runs/<run_id>/stages/<этап>.json``, ``trace.jsonl``, ``report.*``.

Персональные данные в ``runs/`` хранятся маскированными (``mask_pd``, модуль №30); при чтении этапов
``RunDir.restore`` подставляет их обратно из текста документа — повтор и пересмотр видят те же цитаты.

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
from typing import Any, Callable

ASTANA = timezone(timedelta(hours=5))


def now_iso() -> str:
    return datetime.now(ASTANA).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(ASTANA).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _redact() -> Any:
    """Модуль маскирования №30 (``rules/redact.py``) или None, если его нет в этой сборке."""
    try:
        from .rules import redact
        return redact
    except Exception:  # noqa: BLE001
        return None


def redact_available() -> bool:
    return _redact() is not None


def mask_pd(obj: Any) -> Any:
    """Персональные данные (карты, ИИН/БИН, телефоны, почта, IBAN) на диск в открытом виде не пишем — закрытый
    контур банка (№30). Прогон читает их обратно через ``RunDir.restore`` по тексту самого документа."""
    r = _redact()
    if r is None:
        return obj
    try:
        return r.mask_obj(obj)
    except Exception:  # noqa: BLE001 — маскирование не роняет прогон
        return obj


def mask_text(text: str) -> str:
    r = _redact()
    if r is None:
        return text
    try:
        return r.mask(text)
    except Exception:  # noqa: BLE001
        return text


def has_pd(obj: Any) -> bool:
    return mask_pd(obj) != obj


def pd_restorer(view: dict) -> Callable[[Any], Any] | None:
    """Обратная подстановка ПДн документа в то, что прогон прочёл из ``runs/`` (там они маскированы): маска
    сохраняет длину, поэтому «маска → значение» берётся из строк документа. Маска, которая означает разные значения
    или сама встречается в документе, не подставляется. ПДн в документе нет (или документ уже маскирован
    ``--redact``) — None."""
    r = _redact()
    if r is None:
        return None
    texts = [ln.get("text") for ln in view.get("lines") or [] if isinstance(ln, dict) and isinstance(ln.get("text"), str)]
    table: dict[str, str] = {}
    bad: set[str] = set()
    try:
        for t in texts:
            hits = r.find(t)
            if not hits:
                continue
            m = r.mask(t)
            for h in hits:
                key, val = m[h["start"]:h["end"]], t[h["start"]:h["end"]]
                if key != val and table.setdefault(key, val) != val:
                    bad.add(key)
    except Exception:  # noqa: BLE001
        return None
    whole = "\n".join(texts)
    table = {k: v for k, v in table.items() if k not in bad and k not in whole}
    if not table:
        return None
    keys = sorted(table, key=len, reverse=True)
    dot = getattr(r, "DOT", "•")

    def restore(obj: Any) -> Any:
        if isinstance(obj, str):
            if dot not in obj:
                return obj
            for k in keys:
                if k in obj:
                    obj = obj.replace(k, table[k])
            return obj
        if isinstance(obj, dict):
            return {k: restore(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [restore(v) for v in obj]
        return obj

    return restore


def _dump(obj: Any) -> str:
    return json.dumps(mask_pd(obj), ensure_ascii=False, indent=2, default=str)


class RunDir:
    # Подстановка ПДн документа при чтении этапов (``pd_restorer``): ставит конвейер, когда документ загружен.
    restore: Callable[[Any], Any] | None = None

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
            rec = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return self.restore(rec) if self.restore else rec

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
        rec = mask_pd({"t": now_iso(), **record})
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
