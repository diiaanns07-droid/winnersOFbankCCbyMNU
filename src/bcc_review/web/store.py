"""Файловое хранилище запусков веб-демо.

Каждый запуск живёт в собственном каталоге ``<data>/runs/<run_id>/``::

    run.json        — состояние запуска (единственный источник правды для UI)
    events.jsonl    — журнал этапов, которые сообщил движок
    input/          — загруженный документ и answers.md (только чтение после создания)
    tmp/            — временные данные движка; удаляется после завершения
    artifacts/      — то, что реально записал движок (report.md, report.json, …)
    artifacts/web/  — файлы, которые сформировал веб-слой (questions.md)
    claims/         — атомарные «заявки» на дочерние запуски (защита от повторного клика)

Все записи JSON атомарны (tmp + os.replace); заявки создаются через os.link /
O_EXCL, поэтому повторный клик не порождает второй платный запуск даже при
одновременных запросах (см. tests/p15/test_store.py::test_concurrent_claims).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
FINAL_STATUSES = ("complete", "partial", "failed")
ACTIVE_STATUSES = ("started", "running")
ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt", ".docx", ".html", ".htm"}
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(name: str | None, default: str = "document") -> str:
    """Имя файла без каталогов, управляющих символов и зарезервированных имён.

    Кириллица сохраняется (\\w в Unicode-режиме), всё прочее заменяется на «_».
    """
    raw = unicodedata.normalize("NFC", name or "")
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = "".join(ch for ch in raw if ch.isprintable())
    stem, ext = os.path.splitext(raw)
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("._-")
    ext = re.sub(r"[^0-9a-z]", "", ext.lower())[:10]
    if not stem:
        stem = default
    if stem.lower() in _WINDOWS_RESERVED:
        stem = "_" + stem
    stem = stem[:80]
    return f"{stem}.{ext}" if ext else stem


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_bytes(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))


def create_exclusive_json(path: Path, obj: Any) -> bool:
    """Создать файл с полным содержимым атомарно. False — файл уже есть.

    Сначала пишем во временный файл, затем os.link: ссылка либо появляется
    целиком, либо не появляется. Читатель никогда не видит недописанный JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    except OSError:
        # Файловая система без жёстких ссылок: O_EXCL + запись.
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "wb") as fh:
            fh.write(tmp.read_bytes())
        return True
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path, retries: int = 20) -> Any:
    last: Exception | None = None
    for _ in range(retries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - only O_EXCL fallback
            last = exc
            time.sleep(0.005)
    raise last  # type: ignore[misc]


class StoreError(Exception):
    """Ошибка, которую интерфейс показывает пользователю как есть."""

    def __init__(self, message: str, http_status: int = 400, **extra: Any):
        super().__init__(message)
        self.http_status = http_status
        self.extra = extra


@dataclass
class Claim:
    run_id: str
    duplicate: bool


class RunStore:
    def __init__(self, root: Path | str, *, read_only: bool = False):
        self.root = Path(root).resolve()
        self.runs_dir = self.root / "runs"
        self.read_only = read_only
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._create_guard = threading.Lock()
        if not read_only:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            ignore = self.root / ".gitignore"
            if not ignore.exists():
                ignore.write_text("# данные веб-демо не коммитятся\n*\n", encoding="utf-8")

    # ------------------------------------------------------------------ paths
    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.match(run_id or ""):
            raise StoreError("Некорректный идентификатор запуска", 404)
        return self.runs_dir / run_id

    def input_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "input"

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts"

    def tmp_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "tmp"

    def report_md(self, run_id: str) -> Path:
        return self.artifacts_dir(run_id) / "report.md"

    def report_json(self, run_id: str) -> Path:
        return self.artifacts_dir(run_id) / "report.json"

    def _lock(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    # ------------------------------------------------------------------ create
    def _new_run_dir(self) -> tuple[str, Path]:
        for _ in range(50):
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            path = self.runs_dir / run_id
            try:
                path.mkdir()
            except FileExistsError:
                continue
            for sub in ("input", "tmp", "artifacts", "claims"):
                (path / sub).mkdir()
            return run_id, path
        raise StoreError("Не удалось выделить run_id", 500)  # pragma: no cover

    def create_run(
        self,
        *,
        original_name: str,
        data: bytes,
        options: dict[str, Any],
        engine: dict[str, Any],
        parent_run_id: str | None = None,
        answers: bytes | None = None,
        answers_meta: dict[str, Any] | None = None,
        reason: str = "upload",
        retry_of: str | None = None,
        extra_inputs: dict[str, bytes] | None = None,
    ) -> str:
        if self.read_only:
            raise StoreError("Сохранённый прогон открыт только для просмотра", 403)
        if not data:
            raise StoreError("Файл пустой", 400)
        safe = safe_filename(original_name)
        ext = os.path.splitext(safe)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(e.lstrip(".") for e in ALLOWED_EXTENSIONS))
            raise StoreError(f"Формат «{ext or 'без расширения'}» не поддерживается. Допустимо: {allowed}", 415)

        parent = self.load(parent_run_id) if parent_run_id else None
        if retry_of:
            self.load(retry_of)  # 404, если повторять нечего
        run_id, path = self._new_run_dir()
        atomic_write_bytes(path / "input" / safe, data)
        answers_name = None
        if answers is not None:
            answers_name = "answers.md"
            atomic_write_bytes(path / "input" / answers_name, answers)
        for extra_name, extra_data in (extra_inputs or {}).items():
            atomic_write_bytes(path / "input" / safe_filename(extra_name), extra_data)

        if retry_of:
            # Повтор проваленного запуска занимает ту же позицию в цепочке редакций.
            prev = self.load(retry_of)
            lineage, revision = prev["lineage_id"], prev["revision"]
            parent_run_id = prev.get("parent_run_id")
        elif parent:
            lineage, revision = parent["lineage_id"], parent["revision"] + 1
        else:
            lineage, revision = run_id, 1

        record = {
            "run_id": run_id,
            "status": "started",
            "stage": None,
            "created_at": utcnow(),
            "started_at": None,
            "finished_at": None,
            "duration_s": None,
            "reason": reason,
            "retry_of": retry_of,
            "input": {
                "original_name": original_name,
                "file": safe,
                "sha256": sha256_bytes(data),
                "size": len(data),
            },
            "answers": (
                {"file": answers_name, "sha256": sha256_bytes(answers), **(answers_meta or {})}
                if answers is not None
                else None
            ),
            "parent_run_id": parent_run_id,
            "lineage_id": lineage,
            "revision": revision,
            "options": options,
            "engine": engine,
            "error": None,
            "warnings": [],
            "report": None,
            "artifacts": [],
        }
        atomic_write_json(path / "run.json", record)
        return run_id

    # ------------------------------------------------------------------ read/update
    def exists(self, run_id: str) -> bool:
        try:
            return (self.run_dir(run_id) / "run.json").is_file()
        except StoreError:
            return False

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            raise StoreError("Запуск не найден", 404)
        return read_json(path)

    def update(self, run_id: str, **fields: Any) -> dict[str, Any]:
        if self.read_only:
            raise StoreError("Хранилище только для чтения", 403)
        with self._lock(run_id):
            record = self.load(run_id)
            record.update(fields)
            atomic_write_json(self.run_dir(run_id) / "run.json", record)
            return record

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        event = {"ts": utcnow(), **event}
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self._lock(run_id):
            with open(self.run_dir(run_id) / "events.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()

    def events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.run_dir(run_id) / "events.jsonl"
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # недописанная последняя строка
        return out

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.runs_dir.is_dir():
            return []
        out = []
        for child in self.runs_dir.iterdir():
            if RUN_ID_RE.match(child.name) and (child / "run.json").is_file():
                try:
                    out.append(read_json(child / "run.json"))
                except (OSError, json.JSONDecodeError):
                    continue
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    def lineage(self, lineage_id: str) -> list[dict[str, Any]]:
        runs = [r for r in self.list_runs() if r.get("lineage_id") == lineage_id]
        runs.sort(key=lambda r: (r.get("revision", 0), r.get("created_at") or ""))
        return runs

    def children(self, run_id: str) -> list[dict[str, Any]]:
        return [r for r in self.list_runs() if r.get("parent_run_id") == run_id]

    def latest_in_lineage(self, lineage_id: str) -> dict[str, Any] | None:
        """Самая новая редакция, которая не провалилась (её и надо показывать)."""
        alive = [r for r in self.lineage(lineage_id) if r.get("status") != "failed"]
        return alive[-1] if alive else None

    # ------------------------------------------------------------------ artifacts
    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        base = self.artifacts_dir(run_id)
        out = []
        if not base.is_dir():
            return out
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                rel = path.relative_to(base).as_posix()
                out.append(
                    {
                        "name": rel,
                        "size": path.stat().st_size,
                        "sha256": sha256_file(path),
                        "origin": "web" if rel.startswith("web/") else "engine",
                    }
                )
        return out

    def artifact_path(self, run_id: str, name: str) -> Path:
        """Путь к артефакту только если он реально есть в списке (без path traversal)."""
        base = self.artifacts_dir(run_id)
        for item in self.list_artifacts(run_id):
            if item["name"] == name:
                path = (base / name).resolve()
                if base.resolve() in path.parents:
                    return path
        raise StoreError("Файл не найден среди артефактов этого запуска", 404)

    def input_path(self, run_id: str) -> Path:
        rec = self.load(run_id)
        return self.input_dir(run_id) / rec["input"]["file"]

    def cleanup_tmp(self, run_id: str) -> None:
        shutil.rmtree(self.tmp_dir(run_id), ignore_errors=True)

    # ------------------------------------------------------------------ claims
    def claim(self, scope_run_id: str | None, key: str, create: Callable[[], str]) -> Claim:
        """Создать запуск ровно один раз для пары (scope_run_id, key).

        Повторный вызов с тем же ключом возвращает уже созданный run_id и
        ``duplicate=True`` — второй платный запуск не стартует. Без scope
        (загрузка нового документа) заявки лежат в ``<data>/claims``.
        """
        if not re.fullmatch(r"[0-9a-zA-Z_\-]{8,128}", key or ""):
            raise StoreError("Некорректный ключ подтверждения", 400)
        scope_dir = self.run_dir(scope_run_id) / "claims" if scope_run_id else self.root / "claims"
        path = scope_dir / f"{key}.json"
        if path.is_file():
            return Claim(read_json(path)["run_id"], True)
        # Захватываем «место» до дорогого шага: пустая заявка с pending=True.
        lock = path.with_suffix(".lock")
        if not create_exclusive_json(lock, {"ts": utcnow()}):
            # Кто-то другой уже создаёт этот запуск — ждём его результата.
            for _ in range(600):
                if path.is_file():
                    return Claim(read_json(path)["run_id"], True)
                time.sleep(0.01)
            try:
                stale = time.time() - lock.stat().st_mtime > 60
            except FileNotFoundError:
                stale = True
            if stale:  # создатель упал между заявкой и записью результата
                lock.unlink(missing_ok=True)
                return self.claim(scope_run_id, key, create)
            raise StoreError("Подтверждение уже обрабатывается, обновите страницу", 409)
        try:
            run_id = create()
        except Exception:
            lock.unlink(missing_ok=True)
            raise
        create_exclusive_json(path, {"run_id": run_id, "ts": utcnow()})
        return Claim(run_id, False)

    # ------------------------------------------------------------------ recovery
    def recover_interrupted(self) -> list[str]:
        """Запуски, оставшиеся в started/running после перезапуска сервера, — failed."""
        fixed = []
        if self.read_only:
            return fixed
        for rec in self.list_runs():
            if rec.get("status") in ACTIVE_STATUSES:
                self.update(
                    rec["run_id"],
                    status="failed",
                    finished_at=utcnow(),
                    error={
                        "kind": "interrupted",
                        "message": "Запуск прерван: веб-сервер перезапустили во время выполнения.",
                    },
                )
                fixed.append(rec["run_id"])
        return fixed

    def measured_durations(self, engine_name: str, offline: bool) -> list[float]:
        out = []
        for rec in self.list_runs():
            if (
                rec.get("status") in ("complete", "partial")
                and rec.get("duration_s")
                and (rec.get("engine") or {}).get("name") == engine_name
                and bool((rec.get("options") or {}).get("offline_lint")) == offline
            ):
                out.append(float(rec["duration_s"]))
        return out

    def iter_ids(self) -> Iterator[str]:
        for rec in self.list_runs():
            yield rec["run_id"]
