"""Сценарии веб-демо поверх хранилища и очереди: загрузка, новая редакция, повтор.

Правила, которые проверяют тесты tests/p15:

* каждая загрузка получает новый run_id, даже при одинаковом имени файла;
* повторная отправка той же формы (тот же upload_key) возвращает тот же запуск;
* повторное подтверждение тех же ответов к той же редакции не создаёт второго
  платного запуска (атомарная заявка в ``runs/<parent>/claims``);
* подтверждение к редакции, у которой уже есть более новая, отклоняется
  с 409 и ссылкой на актуальный результат.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .answers import Answer, AnswerSet, compose_answers, parse_answers, render_questions
from .engine import EngineSpec, Runner, preflight, read_report
from .store import Claim, RunStore, StoreError

MAX_UPLOAD = 25 * 1024 * 1024


@dataclass
class Settings:
    provider: str | None = None
    export: tuple[str, ...] = ("html",)
    demo_answers: Path | None = None
    mock_script: Path | None = None  # сценарий mock-провайдера движка (показ без ключа и сети)
    cache_dir: Path | None = None    # кэш ответов модели движка (RunOptions.cache_dir); None — по умолчанию движка


class Service:
    def __init__(self, store: RunStore, runner: Runner, engine: EngineSpec, settings: Settings):
        self.store = store
        self.runner = runner
        self.engine = engine
        self.settings = settings
        self._lineage_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def preflight(self) -> dict[str, Any]:
        return preflight(self.settings.provider, self.engine)

    def _options(self, *, offline: bool) -> dict[str, Any]:
        """Параметры запуска в именах RunOptions (bcc_review.contracts)."""
        opts: dict[str, Any] = {"exports": list(self.settings.export)}
        provider = self.settings.provider
        if not provider and not offline:
            found = self.preflight().get("provider")
            provider = found if found in ("anthropic", "gemini") else None
        if provider:
            opts["provider"] = provider
        if provider == "mock" and self.settings.mock_script:
            opts["mock_script"] = str(Path(self.settings.mock_script).resolve())
        if self.settings.cache_dir:
            opts["cache_dir"] = str(Path(self.settings.cache_dir).resolve())
        if offline:
            opts["offline_lint"] = True
        return opts

    def _require_engine(self) -> None:
        if not self.engine.available:
            raise StoreError(
                "Общий движок не подключён, новый анализ невозможен. " + (self.engine.error or ""),
                503,
            )

    # ------------------------------------------------------------------ upload
    def start_upload(self, filename: str, data: bytes, *, upload_key: str, offline: bool | None = None) -> Claim:
        self._require_engine()
        if len(data) > MAX_UPLOAD:
            raise StoreError("Файл больше 25 МБ", 413)
        pf = self.preflight()
        offline = pf["offline"] if offline is None else (offline or pf["offline"])

        def create() -> str:
            return self.store.create_run(
                original_name=filename,
                data=data,
                options=self._options(offline=offline),
                engine=self.engine.describe(),
                reason="upload",
            )

        claim = self.store.claim(None, f"upload-{upload_key}", create)
        if not claim.duplicate:
            self.runner.submit(claim.run_id)
        return claim

    # ------------------------------------------------------------------ revisions
    def latest_of(self, run: dict[str, Any]) -> dict[str, Any] | None:
        return self.store.latest_in_lineage(run["lineage_id"])

    def confirm_revision(
        self,
        parent_id: str,
        *,
        form_answers: list[Answer],
        answers_file: bytes | None = None,
        document: tuple[str, bytes] | None = None,
    ) -> Claim:
        self._require_engine()
        parent = self.store.load(parent_id)
        if parent["status"] not in ("complete", "partial"):
            raise StoreError(
                "У этой редакции нет готового отчёта: подтверждать нечего. Дождитесь результата или повторите запуск.",
                409,
                latest_run_id=parent_id,
            )
        report, problem = read_report(self.store.report_json(parent_id))
        if report is None:
            raise StoreError(f"Отчёт редакции недоступен: {problem}", 409, latest_run_id=parent_id)

        if document is not None:
            doc_name, doc_bytes = document
        else:
            doc_name = parent["input"]["original_name"]
            doc_bytes = self.store.input_path(parent_id).read_bytes()
        # Ответы относятся к документу, который проверит дочерний запуск (движок сверяет source_sha256).
        source_sha = hashlib.sha256(doc_bytes).hexdigest()
        carried = self.run_answers(parent_id)
        extra: dict[str, bytes] = {}
        if answers_file is not None:
            parsed = parse_answers(answers_file.decode("utf-8", errors="replace"))
            if not parsed.answers:
                raise StoreError("В загруженном answers.md не найдено ни одного ответа (строки после «Ответ:» пустые)", 400)
            submitted, origin = parsed.answers, "upload"
            extra["answers_uploaded.md"] = answers_file  # исходный файл аналитика — для прослеживаемости
        else:
            submitted, origin = [Answer(a.qid, a.text.strip(), a.provenance, a.question, list(a.edits)) for a in form_answers], "form"

        # Ответы накапливаются по цепочке редакций: новый ответ на тот же вопрос заменяет прежний.
        merged: dict[str, Answer] = dict(carried)
        for a in submitted:
            merged[a.qid] = a
        if document is None and [(q, a.text, a.edits) for q, a in sorted(merged.items())] == [(q, a.text, a.edits) for q, a in sorted(carried.items())]:
            raise StoreError(
                "Нет новых ответов и нет исправленной редакции: повторный анализ не нужен. Заполните хотя бы один ответ.",
                400,
            )
        if merged:
            answers_bytes = compose_answers(list(merged.values()), run_id=parent_id, source_sha256=source_sha).encode("utf-8")
            meta = {
                "origin": origin,
                "count": len(merged),
                "new": len(submitted),
                "carried": len([q for q in carried if q not in {a.qid for a in submitted}]),
                "provenance": AnswerSet(list(merged.values())).provenance_summary(),
            }
        else:
            answers_bytes, meta = None, None
        canonical = sorted((a.qid, a.text, a.provenance, [list(e) for e in a.edits]) for a in merged.values())

        # Ключ — от смысла решения (ответы + документ), а не от байтов answers.md:
        # в собранном файле есть метка времени, и повторный клик дал бы новый ключ.
        content_key = hashlib.sha256(
            json.dumps([parent_id, hashlib.sha256(doc_bytes).hexdigest(), canonical], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:40]

        with self._lineage_guard:
            existing = self.store.run_dir(parent_id) / "claims" / f"rev-{content_key}.json"
            if not existing.is_file():
                latest = self.latest_of(parent)
                if latest and latest["run_id"] != parent_id:
                    raise StoreError(
                        f"Редакция {parent['revision']} устарела: после неё уже запущена редакция {latest['revision']}. "
                        "Откройте актуальный результат и отправьте решение к нему.",
                        409,
                        latest_run_id=latest["run_id"],
                        stale=True,
                    )

            def create() -> str:
                return self.store.create_run(
                    original_name=doc_name,
                    data=doc_bytes,
                    options=self._options(offline=self.preflight()["offline"]),
                    engine=self.engine.describe(),
                    parent_run_id=parent_id,
                    answers=answers_bytes,
                    answers_meta=meta,
                    reason="revision",
                    extra_inputs=extra,
                )

            claim = self.store.claim(parent_id, f"rev-{content_key}", create)
        if not claim.duplicate:
            self.runner.submit(claim.run_id)
        return claim

    # ------------------------------------------------------------------ retry
    def retry(self, run_id: str, *, offline: bool) -> Claim:
        self._require_engine()
        rec = self.store.load(run_id)
        if rec["status"] != "failed":
            raise StoreError("Повтор доступен только для запуска со статусом failed", 409, latest_run_id=run_id)
        data = self.store.input_path(run_id).read_bytes()
        answers = None
        if rec.get("answers"):
            answers = (self.store.input_dir(run_id) / rec["answers"]["file"]).read_bytes()
        offline = offline or self.preflight()["offline"]

        def create() -> str:
            return self.store.create_run(
                original_name=rec["input"]["original_name"],
                data=data,
                options=self._options(offline=offline),
                engine=self.engine.describe(),
                answers=answers,
                answers_meta=rec.get("answers") and {k: v for k, v in rec["answers"].items() if k not in ("file", "sha256")},
                reason="retry",
                retry_of=run_id,
            )

        claim = self.store.claim(run_id, "retry-offline" if offline else "retry-same", create)
        if not claim.duplicate:
            self.runner.submit(claim.run_id)
        return claim

    # ------------------------------------------------------------------ questions.md
    def questions_file(self, run_id: str) -> Path:
        """questions.md движка, если он его записал; иначе веб формирует из report.json."""
        engine_q = self.store.artifacts_dir(run_id) / "questions.md"
        if engine_q.is_file():
            return engine_q
        report, problem = read_report(self.store.report_json(run_id))
        if report is None:
            raise StoreError(f"Вопросов нет: {problem}", 404)
        target = self.store.artifacts_dir(run_id) / "web" / "questions.md"
        if not target.is_file() and not self.store.read_only:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_questions(report, run_id, self.run_answers(run_id)), encoding="utf-8")
            self.store.update(run_id, artifacts=self.store.list_artifacts(run_id))
        if not target.is_file():
            raise StoreError("questions.md не сохранён в этом прогоне", 404)
        return target

    def run_answers(self, run_id: str, *, store: RunStore | None = None) -> dict[str, Answer]:
        """Ответы, с которыми запущена редакция (накопленные по цепочке)."""
        store = store or self.store
        rec = store.load(run_id)
        if not rec.get("answers"):
            return {}
        path = store.input_dir(run_id) / rec["answers"]["file"]
        if not path.is_file():
            return {}
        return parse_answers(path.read_text(encoding="utf-8")).by_id()
