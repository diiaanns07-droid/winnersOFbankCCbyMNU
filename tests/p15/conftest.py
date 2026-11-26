"""Общие фикстуры tests/p15: сервер веб-демо на подставном движке и реальном диске."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.web import devengine  # noqa: E402
from bcc_review.web.app import create_app, serve_in_thread  # noqa: E402
from bcc_review.web.engine import EngineSpec  # noqa: E402
from bcc_review.web.service import Settings  # noqa: E402

FIXTURES = Path(__file__).with_name("fixtures")


def _tail(path: str, suffix: str) -> bool:
    """path оканчивается частями suffix (разделитель «/»), независимо от ОС."""
    want = tuple(x for x in suffix.split("/") if x)
    return Path(path).parts[-len(want):] == want
CASE = FIXTURES / "case_ab.md"


class CountingEngine:
    """Обёртка над dev-движком: считает «платные» вызовы run_review."""

    def __init__(self, scenario: str | None = None, delay: float = 0.0, hold: threading.Event | None = None):
        self.calls: list[dict[str, Any]] = []
        self.scenario = scenario
        self.delay = delay
        self.hold = hold
        self._lock = threading.Lock()

    def __call__(self, input_path: str, report_md: str, *, options: dict | None = None) -> Any:
        options = dict(options or {})
        with self._lock:
            self.calls.append({"input": input_path, "report": report_md, "options": {k: v for k, v in options.items() if k != "progress"}})
        if self.hold is not None:
            options["progress"]("parse", "start")
            self.hold.wait(10)
        if self.scenario:
            options.setdefault("dev_scenario", self.scenario)
        options.setdefault("dev_delay", self.delay)
        return devengine.run_review(input_path, report_md, options=options)


class Client:
    def __init__(self, base: str):
        self.base = base

    def request(self, method: str, path: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def get(self, path: str, **kw: Any) -> tuple[int, dict[str, str], bytes]:
        return self.request("GET", path, **kw)

    def get_json(self, path: str) -> Any:
        status, _, body = self.get(path, headers={"Accept": "application/json"})
        assert status == 200, body
        return json.loads(body)

    def post_form(self, path: str, fields: dict[str, str] | None = None, files: dict[str, tuple[str, bytes]] | None = None, *, json_accept: bool = True, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        body, ctype = encode_multipart(fields or {}, files or {})
        h = {"Content-Type": ctype}
        if json_accept:
            h["Accept"] = "application/json"
        h.update(headers or {})
        return self.request("POST", path, data=body, headers=h)

    def upload(self, name: str, data: bytes, *, key: str | None = None, **fields: str) -> dict[str, Any]:
        status, _, body = self.post_form("/api/runs", {"upload_key": key or uuid.uuid4().hex, **fields}, {"file": (name, data)})
        assert status in (200, 201), body
        return json.loads(body)

    def wait(self, run_id: str, timeout: float = 20.0, until: Callable[[dict], bool] | None = None) -> dict[str, Any]:
        deadline = time.time() + timeout
        until = until or (lambda s: s["final"])
        while time.time() < deadline:
            s = self.get_json(f"/api/runs/{run_id}")
            if until(s):
                return s
            time.sleep(0.05)
        raise AssertionError(f"запуск {run_id} не дошёл до нужного состояния: {s}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def encode_multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "----p15" + uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode() + v.encode("utf-8") + b"\r\n"
    for k, (fname, data) in files.items():
        out += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


@pytest.fixture
def make_server(tmp_path: Path):
    servers = []

    def _make(engine: Callable | EngineSpec | None = None, *, name: str = "dev", data_dir: Path | None = None, demo_dir: Path | None = None, settings: Settings | None = None, workers: int = 1):
        if isinstance(engine, EngineSpec):
            spec = engine
        else:
            fn = engine or CountingEngine()
            spec = EngineSpec(name, f"tests.p15:{type(fn).__name__}", fn, "test")
        app = create_app(data_dir or tmp_path / "data", spec, settings=settings, workers=workers, demo_dir=demo_dir)
        server, _ = serve_in_thread(app)
        client = Client(f"http://127.0.0.1:{server.server_address[1]}")
        client.app = app  # type: ignore[attr-defined]

        def close() -> None:  # «процесс сервера завершился»: порт и каталог данных освобождены
            if (server, app) in servers:
                servers.remove((server, app))
                server.shutdown()
                server.server_close()
                app.close()

        client.close = close  # type: ignore[attr-defined]
        servers.append((server, app))
        return client

    yield _make
    for s, app in servers:
        s.shutdown()
        s.server_close()
        app.close()


@pytest.fixture
def case_bytes() -> bytes:
    return CASE.read_bytes()


def make_pdf(pages: list[str]) -> bytes:
    """Минимальный PDF без зависимостей: страницы с текстом Helvetica (пустая строка — пустая страница)."""
    objs: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode())
        stream = (f"BT /F1 12 Tf 72 760 Td ({text}) Tj ET" if text else "").encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
