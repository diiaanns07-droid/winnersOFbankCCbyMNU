"""Сценарии веб-демо поверх хранилища и очереди: загрузка, новая редакция, повтор.

Правила, которые проверяют тесты tests/p15:

* каждая загрузка получает новый run_id, даже при одинаковом имени файла;
* повторная отправка той же формы (тот же upload_key) возвращает тот же запуск;
* повторное подтверждение тех же ответов к той же редакции не создаёт второго
  платного запуска (атомарная заявка в ``runs/<parent>/claims``);
* подтверждение к редакции, у которой уже есть более новая, отклоняется
  с 409 и ссылкой на актуальный результат;
* файл ответов применяется только к той версии документа, к вопросам которой он дан:
  заявленный ``source_sha256`` сверяется с SHA-256 документа новой редакции до
  объединения ответов и до создания дочернего запуска. Чужая версия, конфликт или
  отсутствие версии — 409, ноль новых запусков, импорт сохранён как отклонённый;
* ответы не переносятся между версиями по номеру вопроса: следующая редакция
  проверяет документ, о котором были вопросы (вход или файл редакции движка).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .answers import Answer, AnswerSet, Imported, compose_answers, parse_answers, read_import, render_questions, report_version
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

    def version_document(self, parent: dict[str, Any], report: dict[str, Any]) -> tuple[str, bytes, dict[str, Any] | None]:
        """Документ, о котором заданы вопросы редакции: её вход или файл редакции B из артефактов.

        Так веб повторяет CLI: следующий круг проверяет редакцию, которую записал движок,
        а ответы относятся к её SHA-256 (``report.document.id``)."""
        version = report_version(report)
        parent_id = parent["run_id"]
        if not version or version == parent["input"]["sha256"]:
            return parent["input"]["original_name"], self.store.input_path(parent_id).read_bytes(), None
        for a in self.store.list_artifacts(parent_id):
            if a["sha256"] == version:
                path = self.store.artifact_path(parent_id, a["name"])
                return parent["input"]["original_name"], path.read_bytes(), {"run_id": parent_id, "artifact": a["name"]}
        raise StoreError(
            f"Документ, о котором заданы вопросы этой редакции (SHA-256 {version[:12]}…), не найден среди файлов запуска. "
            "Ответы не к чему применить: повторите запуск.",
            409, reason="version_document_missing", target_sha256=version, latest_run_id=parent_id,
        )

    def _reject_import(self, parent_id: str, imp_id: str, imp: Imported, reason: str, message: str, target_sha: str,
                       current_questions: dict[str, str]) -> StoreError:
        matching = [
            {"run_id": r["run_id"], "original_name": r["input"]["original_name"], "revision": r.get("revision"),
             "created_at": r.get("created_at"), "status": r.get("status")}
            for r in (self.store.runs_with_version(imp.declared_sha256) if imp.declared_sha256 else [])
        ]
        self.store.update_import(parent_id, imp_id, status="rejected", reason=reason, message=message, matching_runs=matching)
        clash = [
            {"qid": qid, "in_file": imp.questions.get(qid, ""), "here": current_questions[qid]}
            for qid in [a.qid for a in imp.answers] if qid in current_questions
        ]
        return StoreError(
            message, 409, reason=reason, import_id=imp_id, parent_run_id=parent_id,
            declared_sha256=imp.declared_sha256, sha_values=imp.sha_values, target_sha256=target_sha,
            matching_runs=matching, question_clash=clash, format=imp.format, format_label=imp.format_label, parser=imp.parser,
            questions_url=f"/runs/{parent_id}/questions.md", manual_url=f"/runs/{parent_id}?import={imp_id}#manual-import",
        )

    def confirm_revision(
        self,
        parent_id: str,
        *,
        form_answers: list[Answer],
        answers_file: bytes | None = None,
        answers_name: str = "answers.md",
        document: tuple[str, bytes] | None = None,
        questions_sha256: str | None = None,
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

        version = report_version(report)
        derived = None
        if document is not None:
            doc_name, doc_bytes = document
        else:
            doc_name, doc_bytes, derived = self.version_document(parent, report)
        # Документ, к которому реально применяется решение: его проверит дочерний запуск.
        target_sha = hashlib.sha256(doc_bytes).hexdigest()
        current_questions = {str(q.get("id")): str(q.get("prompt") or q.get("text") or "") for q in report.get("questions") or []}

        # ---- сверка версии: до объединения ответов и до создания дочернего запуска
        extra: dict[str, bytes] = {}
        imp_meta = None
        imp_id = None
        if answers_file is not None:
            imp = read_import(answers_file, filename=answers_name)
            imp_id = self.store.record_import(parent_id, answers_file, {
                "original_name": answers_name, "file_sha256": imp.file_sha256, "size": len(answers_file),
                "format": imp.format, "format_label": imp.format_label, "parser": imp.parser,
                "declared_sha256": imp.declared_sha256, "sha_values": imp.sha_values, "target_sha256": target_sha,
                "warnings": imp.warnings, "status": "checking",
                "answers": [{"qid": a.qid, "text": a.text[:2000], "question": imp.questions.get(a.qid, ""),
                             "provenance": a.provenance, "edits": [list(e) for e in a.edits]} for a in imp.answers],
            })
            if not imp.answers:
                self.store.update_import(parent_id, imp_id, status="rejected", reason="no_answers")
                raise StoreError("В загруженном файле не найдено ни одного заполненного ответа", 400, import_id=imp_id)
            if imp.sha_conflict:
                raise self._reject_import(parent_id, imp_id, imp, "sha_conflict",
                    "В файле ответов несколько разных source_sha256: нельзя понять, к какой версии документа он относится. "
                    "Ответы не применены, новый анализ не запускался.", target_sha, current_questions)
            if imp.declared_sha256 is None:
                raise self._reject_import(parent_id, imp_id, imp, "no_sha",
                    "В файле ответов нет source_sha256: версия, к которой даны ответы, не указана. Автоматически такой файл "
                    "не применяется — номера вопросов в разных версиях означают разное. Перенесите нужные ответы вручную, "
                    "сверив вопросы, или скачайте questions.md этой версии. Новый анализ не запускался.",
                    target_sha, current_questions)
            if imp.declared_sha256 != target_sha:
                where = "новую загруженную редакцию" if document is not None else f"«{doc_name}», редакция {parent.get('revision')}"
                raise self._reject_import(parent_id, imp_id, imp, "stale_answers",
                    f"Файл ответов относится к другой версии документа (SHA-256 {imp.declared_sha256[:12]}…), а решение "
                    f"применяется к {where} (SHA-256 {target_sha[:12]}…). Один и тот же номер вопроса в разных версиях "
                    "может означать разное. Ответы не применены, новый анализ не запускался.",
                    target_sha, current_questions)
            submitted, origin = imp.answers, "upload"
            extra["answers_uploaded.md"] = answers_file  # оригинал аналитика рядом с собранным answers.md
            imp_meta = {"import_id": imp_id, "parent_run_id": parent_id, "original_name": answers_name,
                        "file_sha256": imp.file_sha256, "format": imp.format, "format_label": imp.format_label,
                        "parser": imp.parser, "declared_sha256": imp.declared_sha256}
        else:
            submitted, origin = [Answer(a.qid, a.text.strip(), a.provenance, a.question, list(a.edits)) for a in form_answers], "form"
            asked_about = questions_sha256 or version
            if submitted and asked_about != target_sha:
                raise StoreError(
                    f"Ответы в форме даны к вопросам версии {asked_about[:12]}…, а проверяться будет новая редакция документа "
                    f"({target_sha[:12]}…). Отправьте новую редакцию без ответов: движок задаст вопросы к ней заново.",
                    409, reason="form_other_version", declared_sha256=asked_about, target_sha256=target_sha,
                    latest_run_id=parent_id,
                )
        if not submitted and document is None:
            raise StoreError("Нет ни ответа, ни новой редакции документа: повторный анализ не нужен. Заполните хотя бы один ответ.", 400)

        if submitted:
            answers_bytes = compose_answers(submitted, run_id=parent_id, source_sha256=target_sha).encode("utf-8")
            meta = {"origin": origin, "count": len(submitted), "provenance": AnswerSet(submitted).provenance_summary(),
                    "source_sha256": target_sha, "import": imp_meta}
        else:
            answers_bytes, meta = None, None
        canonical = sorted((a.qid, a.text, a.provenance, [list(e) for e in a.edits]) for a in submitted)

        # Ключ — от смысла решения (ответы + документ), а не от байтов файла: повторная загрузка
        # того же ответа или повторный клик возвращают уже созданную редакцию.
        content_key = hashlib.sha256(
            json.dumps([parent_id, target_sha, canonical], ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:40]

        with self._lineage_guard:
            existing = self.store.run_dir(parent_id) / "claims" / f"rev-{content_key}.json"
            if not existing.is_file():
                latest = self.latest_of(parent)
                if latest and latest["run_id"] != parent_id:
                    if imp_id:
                        self.store.update_import(parent_id, imp_id, status="rejected", reason="stale_parent")
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
                    derived_from=derived,
                )

            claim = self.store.claim(parent_id, f"rev-{content_key}", create)
        if imp_id:
            self.store.update_import(parent_id, imp_id, status="duplicate" if claim.duplicate else "accepted", child_run_id=claim.run_id)
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
            target.write_text(render_questions(report, run_id), encoding="utf-8")
            self.store.update(run_id, artifacts=self.store.list_artifacts(run_id))
        if not target.is_file():
            raise StoreError("questions.md не сохранён в этом прогоне", 404)
        return target

    def run_answers(self, run_id: str, *, store: RunStore | None = None) -> dict[str, Answer]:
        """Ответы, с которыми запущена эта редакция (answers.md во входе запуска)."""
        store = store or self.store
        rec = store.load(run_id)
        if not rec.get("answers"):
            return {}
        path = store.input_dir(run_id) / rec["answers"]["file"]
        if not path.is_file():
            return {}
        return parse_answers(path.read_text(encoding="utf-8")).by_id()
