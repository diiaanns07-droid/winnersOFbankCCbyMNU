"""HTTP-сервер веб-демо на стандартной библиотеке (без внешних зависимостей).

Маршруты::

    GET  /                                  загрузка + список запусков
    POST /api/runs                          загрузка файла → 303 /runs/<id> (JSON при Accept: application/json)
    GET  /runs/<id>                         страница запуска
    GET  /api/runs/<id>                     статус запуска в JSON (для опроса и тестов)
    GET  /runs/<id>/files/<name>[?inline=1] скачать/открыть реально записанный артефакт
    GET  /runs/<id>/input/answers.md        ответы, с которыми запущена редакция
    GET  /runs/<id>/questions.md            вопросы для заполнения
    POST /runs/<id>/revisions               ответы/новая редакция → дочерний запуск
    POST /runs/<id>/retry                   повтор проваленного запуска (offline=1 — по правилам)
    GET  /runs/<id>/compare                 сравнение с родительской редакцией
    GET  /demo/...                          те же страницы для сохранённых прогонов (только чтение)
"""

from __future__ import annotations

import email.errors
import email.parser
import email.policy
import json
import mimetypes
import re
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import report_view as rv
from . import views
from .answers import ANALYST, Answer, load_demo_answers
from .engine import EngineSpec, Runner, elapsed_s, read_report, technical_partial_reason, trace_events
from .service import MAX_UPLOAD, Service, Settings
from .store import FINAL_STATUSES, RunStore, StoreError

STATIC_DIR = Path(__file__).with_name("static")
INCOMPLETE_UPLOAD = ("Загрузка оборвалась: сервер получил форму не целиком (страницу обновили или закрыли во время "
                     "отправки, либо пропала сеть). Анализ не запускался — отправьте файл ещё раз.")
RUN_PATH = re.compile(r"^/runs/(?P<id>[0-9]{8}-[0-9]{6}-[0-9a-f]{6})(?P<rest>/.*)?$")


@dataclass
class App:
    store: RunStore
    runner: Runner
    service: Service
    engine: EngineSpec
    demo_store: RunStore | None = None
    demo_answers_path: Path | None = None

    def close(self) -> None:
        """Отпустить каталог данных (как при выходе процесса). Новых заданий этот экземпляр не берёт."""
        self.runner.close()
        self.store.release_owner()

    def ctx(self, *, demo: bool = False) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "preflight": self.service.preflight(),
            "demo": demo,
            "prefix": "/demo" if demo else "",
        }


def create_app(
    data_dir: Path | str,
    engine: EngineSpec,
    *,
    settings: Settings | None = None,
    workers: int = 1,
    demo_dir: Path | str | None = None,
) -> App:
    store = RunStore(data_dir)
    # Один процесс сервера на каталог данных: иначе восстановление ниже пометило бы прерванным
    # живой прогон соседнего процесса, а повтор через соседа дал бы вторую обработку (DataDirBusy).
    store.acquire_owner(engine=engine.target)
    store.recover_interrupted()
    runner = Runner(store, engine, workers=workers)
    settings = settings or Settings()
    service = Service(store, runner, engine, settings)
    demo_store = RunStore(demo_dir, read_only=True) if demo_dir else None
    return App(store, runner, service, engine, demo_store, settings.demo_answers)


# --------------------------------------------------------------------------- multipart
def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    if not msg.is_multipart():
        if "boundary=" in content_type and len(body) < 512:
            return fields, files  # пустая форма: только закрывающая граница
        raise StoreError("Ожидалась форма multipart/form-data", 400)
    # Нет закрывающей границы — форма дошла не целиком (обрыв загрузки): из обрезанного
    # файла запуск не создаём, иначе движок обработал бы часть документа как целый.
    if any(isinstance(d, email.errors.CloseBoundaryNotFoundDefect) for d in msg.defects):
        raise StoreError(INCOMPLETE_UPLOAD, 400, reason="incomplete_body")
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            if payload or filename:
                files[name] = (filename, payload)
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
    return fields, files


# --------------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    app: App  # назначается в make_server
    server_version = "bcc-review-web/1"

    # ---------------------------------------------------------------- utils
    def log_message(self, fmt: str, *args: Any) -> None:  # тише, без тел запросов
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, ctype: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def html(self, page: str, status: int = 200) -> None:
        self._send(status, page.encode("utf-8"), "text/html; charset=utf-8", {
            "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'",
        })

    def json(self, obj: Any, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"), "application/json; charset=utf-8")

    def redirect(self, location: str, status: int = 303) -> None:
        self._send(status, b"", "text/plain", {"Location": location})

    def wants_json(self) -> bool:
        return "application/json" in (self.headers.get("Accept") or "")

    def error_out(self, exc: StoreError, *, demo: bool = False) -> None:
        if self.wants_json():
            self.json({"error": str(exc), **exc.extra}, exc.http_status)
            return
        if exc.extra.get("import_id") and exc.extra.get("reason") in ("stale_answers", "no_sha", "sha_conflict"):
            parent = self.app.store.load(exc.extra["parent_run_id"])
            self.html(views.import_rejected_page(self.app.ctx(demo=demo), parent, exc.extra, str(exc)), exc.http_status)
            return
        links = [("К списку запусков", "/")]
        latest = exc.extra.get("latest_run_id")
        if latest:
            links.insert(0, ("Открыть актуальный результат", f"/runs/{latest}"))
        title = "Редакция устарела" if exc.extra.get("stale") else "Не получилось"
        self.html(views.message_page(self.app.ctx(demo=demo), title, str(exc), links), exc.http_status)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD + 1024 * 1024:
            raise StoreError("Запрос больше 25 МБ", 413)
        body = self.rfile.read(length) if length else b""
        if len(body) != length:
            self.close_connection = True
            raise StoreError(INCOMPLETE_UPLOAD, 400, reason="incomplete_body", received=len(body), expected=length)
        return body

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or origin == "null":
            return True
        return urlsplit(origin).netloc == (self.headers.get("Host") or "")

    # ---------------------------------------------------------------- routing
    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)
        try:
            if path in ("/", "/index.html"):
                return self.page_home()
            if path == "/healthz":
                return self.json({"ok": True, "engine": self.app.engine.describe(), "engine_available": self.app.engine.available,
                                  "engine_calls": self.app.runner.engine_calls,
                                  "skipped_executions": self.app.runner.skipped_executions,
                                  "server": self.app.store.owner})
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            if path.startswith("/api/runs/"):
                return self.api_run(self.app.store, path[len("/api/runs/"):])
            demo = False
            store = self.app.store
            if path.startswith("/demo/"):
                if not self.app.demo_store:
                    raise StoreError("Демонстрационные прогоны не подключены (--demo)", 404)
                demo, store, path = True, self.app.demo_store, path[len("/demo"):]
            m = RUN_PATH.match(path)
            if not m:
                raise StoreError("Страница не найдена", 404)
            run_id, rest = m.group("id"), m.group("rest") or ""
            if rest in ("", "/"):
                return self.page_run(store, run_id, demo=demo, duplicate="dup" in query, import_id=(query.get("import") or [None])[0])
            if rest == "/compare":
                return self.page_compare(store, run_id, demo=demo)
            if rest == "/questions.md":
                if demo:
                    raise StoreError("В режиме просмотра скачивайте файлы из списка", 404)
                return self.send_file(self.app.service.questions_file(run_id), attachment=True)
            if rest == "/input/answers.md":
                rec = store.load(run_id)
                if not rec.get("answers"):
                    raise StoreError("Эта редакция запущена без answers.md", 404)
                return self.send_file(store.input_dir(run_id) / "answers.md", attachment="inline" not in query)
            if rest.startswith("/imports/") and rest.endswith(".md"):
                imp_id = rest[len("/imports/"):-3]
                rec = store.load_import(run_id, imp_id)
                path = store.import_original(run_id, imp_id)
                return self.send_file(path, attachment=True, name=f"{imp_id}-{rec.get('original_name') or 'answers.md'}")
            if rest.startswith("/files/"):
                name = rest[len("/files/"):]
                return self.send_file(store.artifact_path(run_id, name), attachment="inline" not in query)
            raise StoreError("Страница не найдена", 404)
        except StoreError as exc:
            self.error_out(exc)

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        path = unquote(url.path)
        try:
            if not self.same_origin():
                raise StoreError("Запрос с чужого источника отклонён", 403)
            if path == "/api/runs":
                return self.post_upload()
            m = RUN_PATH.match(path)
            if m and m.group("rest") == "/revisions":
                return self.post_revision(m.group("id"))
            if m and m.group("rest") == "/retry":
                return self.post_retry(m.group("id"))
            raise StoreError("Страница не найдена", 404)
        except StoreError as exc:
            self.error_out(exc)

    # ---------------------------------------------------------------- pages
    def page_home(self) -> None:
        demo_runs = self.app.demo_store.list_runs() if self.app.demo_store else []
        self.html(views.home(self.app.ctx(), self.app.store.list_runs(), views.new_key(), demo_runs))

    def _view(self, store: RunStore, run_id: str, previous_id: str | None = None) -> tuple[rv.ReportView | None, str | None]:
        report, problem = read_report(store.report_json(run_id))
        previous = read_report(store.report_json(previous_id))[0] if previous_id and store.exists(previous_id) else None
        return (rv.build(report, previous) if report else None), problem

    @staticmethod
    def _events(store: RunStore, run_id: str) -> list[dict[str, Any]]:
        """Этапы от колбэка progress (если движок его принял) и из JSONL-трассы движка."""
        return store.events(run_id) + trace_events(store.artifacts_dir(run_id))

    def page_run(self, store: RunStore, run_id: str, *, demo: bool, duplicate: bool = False, import_id: str | None = None) -> None:
        run = store.load(run_id)
        view, problem = self._view(store, run_id, run.get("parent_run_id")) if run["status"] in FINAL_STATUSES else (None, None)
        parent = store.load(run["parent_run_id"]) if run.get("parent_run_id") and store.exists(run["parent_run_id"]) else None
        parent_view = self._view(store, parent["run_id"])[0] if parent else None
        demo_answers = load_demo_answers(self.app.demo_answers_path) if not demo else []
        page = views.run_page(
            self.app.ctx(demo=demo),
            run,
            events=self._events(store, run_id),
            view=view,
            report_problem=problem,
            artifacts=store.list_artifacts(run_id),
            lineage=store.lineage(run["lineage_id"]),
            latest=store.latest_in_lineage(run["lineage_id"]),
            parent=parent,
            parent_view=parent_view,
            eta=None if demo else self.app.runner.measured_eta(run),
            queue_pos=0 if demo else self.app.runner.queue_position(run_id),
            elapsed=elapsed_s(run),
            demo_answers=demo_answers,
            duplicate=duplicate,
            manual_import=self._manual_import(store, run_id, import_id),
            imports=store.list_imports(run_id),
            retry=self._retry_info(store, run),
            same_content=store.same_content_uploads(run) if run.get("reason") == "upload" else [],
        )
        self.html(page)

    @staticmethod
    def _retry_info(store: RunStore, run: dict[str, Any]) -> dict[str, Any]:
        """Что известно о повторе: техническая причина partial и уже созданные повторы (новые run_id)."""
        reason = None
        if run["status"] == "partial":
            reason = technical_partial_reason(run, read_report(store.report_json(run["run_id"]))[0])
        retries = [
            {"run_id": r["run_id"], "status": r["status"], "offline": bool((r.get("options") or {}).get("offline_lint")),
             "created_at": r.get("created_at"), "job_id": (r.get("job") or {}).get("job_id")}
            for r in store.retries_of(run["run_id"])
        ]
        return {"partial_reason": reason, "retries": retries}

    @staticmethod
    def _manual_import(store: RunStore, run_id: str, import_id: str | None) -> dict[str, Any] | None:
        """Ручной перенос предлагается только для файла без версии (не для чужой версии)."""
        if not import_id:
            return None
        try:
            rec = store.load_import(run_id, import_id)
        except StoreError:
            return None
        return rec if rec.get("status") == "rejected" and rec.get("reason") == "no_sha" else None

    def page_compare(self, store: RunStore, run_id: str, *, demo: bool) -> None:
        run = store.load(run_id)
        if not run.get("parent_run_id"):
            raise StoreError("Это первая редакция: сравнивать не с чем", 404)
        parent = store.load(run["parent_run_id"])
        self.html(views.compare_page(self.app.ctx(demo=demo), run, parent, self._view(store, run_id, parent["run_id"])[0], self._view(store, parent["run_id"])[0]))

    def api_run(self, store: RunStore, run_id: str) -> None:
        run_id = run_id.strip("/")
        run = store.load(run_id)
        latest = store.latest_in_lineage(run["lineage_id"])
        self.json(
            {
                "run_id": run_id,
                "status": run["status"],
                "stage": run.get("stage"),
                "stage_label": rv.stage_label(run.get("stage")),
                "final": run["status"] in FINAL_STATUSES,
                "elapsed_s": elapsed_s(run),
                "duration_s": run.get("duration_s"),
                "events": self._events(store, run_id),
                "error": run.get("error"),
                "warnings": run.get("warnings"),
                "report": run.get("report"),
                "artifacts": store.list_artifacts(run_id),
                "parent_run_id": run.get("parent_run_id"),
                "children": [c["run_id"] for c in store.children(run_id)],
                "imports": [{k: i.get(k) for k in ("import_id", "status", "reason", "format", "parser", "declared_sha256", "target_sha256", "child_run_id")}
                            for i in store.list_imports(run_id)],
                "lineage_id": run["lineage_id"],
                "revision": run["revision"],
                "reason": run.get("reason"),
                "retry_of": run.get("retry_of"),
                "job": run.get("job"),
                "execution": store.execution(run_id),
                "retry": self._retry_info(store, run),
                "same_content_runs": [r["run_id"] for r in store.same_content_uploads(run)] if run.get("reason") == "upload" else [],
                "latest_run_id": latest["run_id"] if latest else None,
                "answers": run.get("answers"),
                "input": run["input"],
                "options": run.get("options"),
                "engine": run.get("engine"),
            }
        )

    def static(self, name: str) -> None:
        if name not in ("app.css", "app.js"):
            raise StoreError("Нет такого файла", 404)
        data = (STATIC_DIR / name).read_bytes()
        ctype = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})

    def send_file(self, path: Path, *, attachment: bool, name: str | None = None) -> None:
        data = path.read_bytes()
        name = name or path.name
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json",):
            ctype += "; charset=utf-8"
        if name.endswith(".md"):
            ctype = "text/plain; charset=utf-8" if not attachment else "text/markdown; charset=utf-8"
        headers = {"Content-Disposition": ("attachment" if attachment else "inline") + f"; filename*=UTF-8''{quote(name)}"}
        if path.suffix in (".html", ".htm"):
            # Отчёт №13 открывается в песочнице: его скрипты не видят API демо. allow-downloads —
            # чтобы работала выгрузка черновика ответов (Blob → answers-….md) из самого отчёта.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-downloads; default-src 'self' 'unsafe-inline' data: blob:"
        self._send(200, data, ctype, headers)

    # ---------------------------------------------------------------- actions
    def _form(self) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
        ctype = self.headers.get("Content-Type") or ""
        body = self.read_body()
        if ctype.startswith("multipart/form-data"):
            return parse_multipart(ctype, body)
        if ctype.startswith("application/x-www-form-urlencoded"):
            return {k: v[-1] for k, v in parse_qs(body.decode("utf-8")).items()}, {}
        raise StoreError("Неподдерживаемый формат запроса", 415)

    def _created(self, claim: Any, message_dup: str) -> None:
        if self.wants_json():
            self.json({"run_id": claim.run_id, "duplicate": claim.duplicate}, 200 if claim.duplicate else 201)
            return
        suffix = "?dup=1" if claim.duplicate else ""
        self.redirect(f"/runs/{claim.run_id}{suffix}")

    def post_upload(self) -> None:
        fields, files = self._form()
        if "file" not in files or not files["file"][1]:
            raise StoreError("Выберите файл с требованиями", 400)
        name, data = files["file"]
        key = fields.get("upload_key") or views.new_key()
        offline = fields.get("offline") == "1" or None
        claim = self.app.service.start_upload(name, data, upload_key=key, offline=offline)
        self._created(claim, "Этот файл уже загружен этой формой")

    def post_revision(self, run_id: str) -> None:
        fields, files = self._form()
        answers: list[Answer] = []
        for k, v in fields.items():
            if not k.startswith("a_"):
                continue
            qid = k[2:]
            text = v.strip()
            if not text and fields.get(f"d_{qid}"):
                # Выбран вариант решения без своего текста — берём текст варианта из отчёта.
                text = self._decision_text(run_id, qid, fields[f"d_{qid}"]) or ""
            edit_old = (fields.get(f"eo_{qid}") or "").strip()
            edits = [(edit_old, (fields.get(f"en_{qid}") or "").strip())] if edit_old else []
            wording = (fields.get(f"w_{qid}") or "").strip()  # «Формулировка» №08: заменит предложение с целью вопроса
            if text or edits or wording:
                answers.append(Answer(qid, text, (fields.get(f"p_{qid}") or ANALYST).strip()[:300], fields.get(f"qt_{qid}", "")[:2000], edits, wording))
        answers_name, answers_file = files.get("answers_file", ("answers.md", b""))
        document = files.get("document")
        if document and not document[1]:
            document = None
        claim = self.app.service.confirm_revision(
            run_id, form_answers=answers, answers_file=answers_file or None, answers_name=answers_name or "answers.md",
            document=document, questions_sha256=(fields.get("questions_sha256") or "").strip() or None,
        )
        self._created(claim, "Это подтверждение уже принято")

    def _decision_text(self, run_id: str, qid: str, option_id: str) -> str | None:
        report, _ = read_report(self.app.store.report_json(run_id))
        if not report:
            return None
        for q in rv.build(report).questions:
            if q["id"] == qid:
                for o in q["options_norm"]:
                    if o["id"] == option_id:
                        return o["text"]
        return None

    def post_retry(self, run_id: str) -> None:
        fields, _ = self._form()
        claim = self.app.service.retry(run_id, offline=fields.get("offline") == "1")
        self._created(claim, "Повтор уже запущен")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    verbose = False


def make_server(app: App, host: str = "127.0.0.1", port: int = 8015, *, verbose: bool = False) -> Server:
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = Server((host, port), handler)
    server.verbose = verbose
    return server


def serve_in_thread(app: App, host: str = "127.0.0.1", port: int = 0) -> tuple[Server, threading.Thread]:
    server = make_server(app, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="bcc-web")
    thread.start()
    return server, thread
